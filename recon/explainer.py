"""差異ごとの説明文と対応案を作る。AI が担当するのは「文章」だけ。

- API モード：Claude API に facts（差異 1 件分。銘柄コード・銘柄名・基準日は除く）だけを渡し、
  説明と対応案を JSON で受け取る
- モックモード：API キーがないときは、あらかじめ用意した説明文を使う（同じ検査を通す）
- どちらの場合も validator で数字を検査し、不一致ならテンプレート説明に戻す
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .classify import DEFAULT_ACTIONS
from .config import API_EFFORT, API_MAX_RETRIES, API_MAX_TOKENS, API_TIMEOUT_SEC, Settings
from .facts import build_facts, facts_for_ai
from .validator import find_unverified_numbers

STATUS_AI_OK = "AI説明（数値検証OK）"
STATUS_MOCK_OK = "モック説明（数値検証OK）"
STATUS_FALLBACK_NUM = "テンプレート（数値不一致のため差し戻し）"
STATUS_FALLBACK_ERR = "テンプレート（AI応答エラー）"

SYSTEM_PROMPT = """あなたは資産運用会社のミドル・バックオフィスで、カストディ残高照合を担当するアナリストです。
渡される facts は、プログラムが計算した差異 1 件分の事実です。これをもとに、担当者向けの説明文と対応案を日本語で書いてください。

厳守するルール：
1. 数字は facts に書かれている表記（符号 +/- を含む）をそのまま使うこと。計算・四捨五入・概数（「約」「およそ」「程度」）・単位換算・漢数字への書き換えはしない。
2. facts にない数字（日付、件数、比率、手順番号など）は一切書かない。「判定根拠」の中の数字も引用しない。
3. 推定原因はルール判定の結果を尊重し、断定は避けて「可能性があります」などと書く。
4. 出力は次の JSON だけにする。前後に文章やコードブロックを付けない。
{"explanation": "差異の内容と推定原因（2文以内）", "action": "担当者が次に取るべき対応（2文以内）"}"""


@dataclass
class UsageTracker:
    mode: str
    model: str | None
    price_in: float | None
    price_out: float | None
    usd_jpy: float
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    log: list[dict] = field(default_factory=list)

    def add(self, code: str, in_tok: int, out_tok: int) -> None:
        self.calls += 1
        self.input_tokens += in_tok
        self.output_tokens += out_tok
        self.log.append({"security_code": code, "input_tokens": in_tok, "output_tokens": out_tok,
                         "cost_usd": self._cost(in_tok, out_tok)})

    def _cost(self, in_tok: int, out_tok: int) -> float | None:
        if self.price_in is None or self.price_out is None:
            return None
        return in_tok / 1_000_000 * self.price_in + out_tok / 1_000_000 * self.price_out

    @property
    def cost_usd(self) -> float | None:
        return self._cost(self.input_tokens, self.output_tokens)

    @property
    def cost_jpy(self) -> float | None:
        c = self.cost_usd
        return None if c is None else c * self.usd_jpy


# ---------------------------------------------------------------- テンプレート / モック

def template_explanation(rec: dict, facts: dict[str, str]) -> tuple[str, str]:
    """AI を使わない最低限の説明。数字はコードが作るので必ず正しい。"""
    exp = (f"{facts['検出した差異']}を検出しました。推定原因は「{rec['category_label']}」、"
           f"評価額差異は{facts['評価額差異（カストディ−当社）']}です。")
    return exp, DEFAULT_ACTIONS[rec["category"]]


def mock_explanation(rec: dict, f: dict[str, str]) -> tuple[str, str]:
    """API キーがないときに使う、あらかじめ用意した説明文。"""
    cat = rec["category"]
    if cat == "CORPORATE_ACTION":
        return (
            f"カストディの数量は{f['カストディ数量']}、当社は{f['当社数量']}で、比率は{f['分割比率（当社:カストディ）']}です。"
            f"単価もほぼ逆の比率で動き、評価額差異は{f['評価額差異（カストディ−当社）']}にとどまるため、株式分割が当社に未反映の可能性があります。",
            "コーポレートアクション情報で分割比率と効力発生日を確認し、当社の数量と単価を修正してください。",
        )
    if cat == "UNBOOKED_TRADE":
        return (
            f"カストディの数量は{f['カストディ数量']}、当社は{f['当社数量']}で、{f['数量差異（カストディ−当社）']}の差があります。"
            f"約定済みの取引が当社に未計上か、受渡日のずれによる差の可能性があります。",
            "約定記録で該当期間の売買を確認し、未計上があれば計上してください。受渡日のずれであれば、解消する日を確認して経過を追ってください。",
        )
    if cat == "PRICE_SOURCE":
        return (
            f"単価がカストディ{f['カストディ単価']}、当社{f['当社単価']}で、差異率{f['単価差異率']}と許容範囲を超えています。"
            f"カストディは「{f['カストディ価格ソース']}」、当社は「{f['当社価格ソース']}」を使っており、価格ソースの違いによる差の可能性があります。",
            "ファンドの評価方針で定めた価格ソースを確認し、どちらを正とするか評価担当と合意したうえで修正してください。",
        )
    if cat == "PRICE_UNKNOWN":
        return (
            f"単価がカストディ{f['カストディ単価']}、当社{f['当社単価']}で、評価額差異は{f['評価額差異（カストディ−当社）']}です。"
            f"価格ソースは同じ「{f['当社価格ソース']}」のため、入力ミスや取得時点の違いの可能性があります。",
            "双方の価格取得記録と取得時刻を確認し、原因が分かるまで差異として管理してください。",
        )
    if cat == "CUSTODIAN_ONLY":
        return (
            f"カストディには{f['カストディ数量']}（評価額{f['カストディ評価額']}）の残高がありますが、当社記録には該当銘柄がありません。"
            f"買付の未計上や銘柄マスタの登録漏れの可能性があります。",
            "約定記録と銘柄マスタを確認し、該当する取引を計上してください。",
        )
    return (  # INTERNAL_ONLY
        f"当社記録には{f['当社数量']}（評価額{f['当社評価額']}）がありますが、カストディの残高にはありません。"
        f"償還・売却の未反映や、カストディへの受渡未了の可能性があります。",
        "償還スケジュールと受渡状況を確認し、カストディに照会してください。",
    )


# ---------------------------------------------------------------- API

def _parse_json(text: str) -> tuple[str, str]:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    m = re.search(r"\{.*\}", text, re.S)
    data = json.loads(m.group() if m else text)
    exp, act = str(data["explanation"]).strip(), str(data["action"]).strip()
    if not exp or not act:
        raise ValueError("explanation / action が空です")
    return exp, act


class Explainer:
    def __init__(self, settings: Settings, force_mock: bool = False, demo_hallucination: bool = False):
        self.demo_hallucination = demo_hallucination
        self.client = None
        self.mode_reason = ""

        if force_mock:
            self.mode, self.mode_reason = "mock", "--mock 指定"
        elif not settings.api_key:
            self.mode, self.mode_reason = "mock", "ANTHROPIC_API_KEY が未設定"
        else:
            try:
                import anthropic  # noqa: WPS433
                self.client = anthropic.Anthropic(api_key=settings.api_key, timeout=API_TIMEOUT_SEC,
                                                  max_retries=API_MAX_RETRIES)
                self.mode = "api"
            except ImportError:
                self.mode, self.mode_reason = "mock", "anthropic パッケージが未インストール"

        self.settings = settings
        self.usage = UsageTracker(
            mode=self.mode,
            model=settings.model if self.mode == "api" else None,
            price_in=settings.price_in,
            price_out=settings.price_out,
            usd_jpy=settings.usd_jpy,
        )

    def _call_api(self, facts: dict[str, str], code: str) -> tuple[str, str]:
        user = "facts:\n" + json.dumps(facts, ensure_ascii=False, indent=2)
        resp = self.client.messages.create(
            model=self.settings.model,
            max_tokens=API_MAX_TOKENS,
            output_config={"effort": API_EFFORT},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user}],
        )
        self.usage.add(code, resp.usage.input_tokens, resp.usage.output_tokens)
        stop = getattr(resp, "stop_reason", None)
        if stop == "max_tokens":
            raise ValueError(f"出力が max_tokens（{API_MAX_TOKENS}）に達して途中で切れました")
        if stop == "refusal":
            raise ValueError("モデルが応答を拒否しました")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return _parse_json(text)

    def explain(self, rec: dict, index: int = 0) -> dict:
        facts = build_facts(rec)
        try:
            if self.mode == "api":
                exp, act = self._call_api(facts_for_ai(facts), rec["security_code"])
                ok_status = STATUS_AI_OK
            else:
                exp, act = mock_explanation(rec, facts)
                if self.demo_hallucination and rec["category"] == "UNBOOKED_TRADE":
                    # デモ用：AI が根拠のない数字を書いたケースを再現する
                    exp += "なお、前月末にも3,000株の同様の差異が出ていました。"
                ok_status = STATUS_MOCK_OK
        except Exception as e:  # API エラー・JSON 崩れなど
            exp, act = template_explanation(rec, facts)
            return {**rec, "facts": facts, "explanation": exp, "action": act,
                    "explain_status": STATUS_FALLBACK_ERR, "rejected_numbers": [],
                    "rejected_text": f"{type(e).__name__}: {e}"}

        bad_exp = find_unverified_numbers(exp, facts)
        bad_act = find_unverified_numbers(act, facts)
        bad = list(dict.fromkeys(bad_exp + bad_act))
        if bad:
            # 問題の数字を含む方（説明・対応案）を差し戻した文章として残す
            parts = ([f"説明：{exp}"] if bad_exp else []) + ([f"対応案：{act}"] if bad_act else [])
            rejected = "\n".join(parts)
            exp, act = template_explanation(rec, facts)
            return {**rec, "facts": facts, "explanation": exp, "action": act,
                    "explain_status": STATUS_FALLBACK_NUM, "rejected_numbers": bad,
                    "rejected_text": rejected}

        return {**rec, "facts": facts, "explanation": exp, "action": act,
                "explain_status": ok_status, "rejected_numbers": [], "rejected_text": ""}
