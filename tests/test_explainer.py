"""AI 説明の数値検査・差し戻し・パイプライン全体のテスト（API は呼ばない）。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openpyxl import load_workbook

from recon.classify import classify
from recon.config import Settings
from recon.explainer import (STATUS_AI_OK, STATUS_FALLBACK_ERR, STATUS_FALLBACK_NUM,
                             STATUS_MOCK_OK, Explainer)
from recon.facts import build_facts, facts_for_ai
from recon.loader import load_positions
from recon.pipeline import run
from recon.reconcile import reconcile
from recon.validator import extract_numbers, find_unverified_numbers

DATA = Path(__file__).resolve().parent.parent / "data"
NO_KEY = Settings(api_key=None, model="claude-haiku-5-5", usd_jpy=150, price_in=0.10, price_out=0.50)


@pytest.fixture(scope="module")
def records():
    cust = load_positions(DATA / "custodian.csv", "カストディ")
    intl = load_positions(DATA / "internal.csv", "当社")
    _, disc = reconcile(cust, intl)
    return {d["security_code"]: classify(d) for d in disc}


# ------------------------------------------------------------ validator

def test_extract_numbers_handles_commas_and_fullwidth():
    nums = [format(n, "f") for n in extract_numbers("差は＋２，０００株、率は1.04%、額は5,720,000円")]
    assert nums == ["2000", "1.04", "5720000"]


def test_validator_accepts_numbers_from_facts(records):
    facts = build_facts(records["EQ0007"])
    text = f"カストディは{facts['カストディ数量']}、当社は{facts['当社数量']}です。"
    assert find_unverified_numbers(text, facts) == []


def test_validator_rejects_invented_or_rounded_numbers(records):
    facts = build_facts(records["EQ0022"])
    assert find_unverified_numbers("差異率は約1%です。", facts) == ["1", "約1"]
    assert find_unverified_numbers("評価額差異は1,600,000円です。", facts) == ["1,600,000"]


@pytest.mark.parametrize("text, expected", [
    ("前月末にも10株、30%の差異がありました。", ["10", "30"]),      # 基準日 2026-10-30 の数字
    ("過去7回同様の差異がありました。", ["7"]),                       # 証券コード EQ0007 の数字
    ("前月末にも三千株の同様の差異が出ていました。", ["三千株"]),      # 漢数字
    ("評価額差異は572万円です。", ["572", "572万"]),                  # 「万」を使った概数
    ("評価額差異は-5,720,000円で、当社の方が多い状態です。", ["-5,720,000"]),  # 符号が逆
    ("評価額差異は約5,720,000円です。", ["約5,720,000"]),             # 正しい数字でも概数表現
    ("評価額差異は5,720,000円程度です。", ["5,720,000円程度"]),
])
def test_validator_closes_loopholes(records, text, expected):
    facts = build_facts(records["EQ0007"])
    assert find_unverified_numbers(text, facts) == expected


@pytest.mark.parametrize("text", [
    "評価額差異は+5,720,000円です。",        # 符号も一致
    "差は2,000株です。",                     # 符号なしの数量差
    "数量が一致せず、同一銘柄で十分な確認が必要です。",  # 「一」「十」を含む普通の語
])
def test_validator_accepts_valid_text(records, text):
    assert find_unverified_numbers(text, build_facts(records["EQ0007"])) == []


def test_facts_for_ai_excludes_identifiers(records):
    f = facts_for_ai(build_facts(records["EQ0007"]))
    assert not {"証券コード", "銘柄名", "基準日"} & set(f)
    assert "評価額差異（カストディ−当社）" in f


# ------------------------------------------------------------ explainer

def test_mock_mode_without_api_key(records):
    ex = Explainer(NO_KEY)
    assert ex.mode == "mock"
    for rec in records.values():
        out = ex.explain(rec)
        assert out["explain_status"] == STATUS_MOCK_OK, out["security_code"]
    assert ex.usage.calls == 0


def test_demo_hallucination_is_caught(records):
    ex = Explainer(NO_KEY, demo_hallucination=True)
    out = ex.explain(records["EQ0007"])
    assert out["explain_status"] == STATUS_FALLBACK_NUM
    assert "3,000" in out["rejected_numbers"]
    assert "3,000" in out["rejected_text"]
    assert "3,000" not in out["explanation"]  # 差し戻し後はテンプレート説明


class FakeClient:
    """Claude API の代わりに決まった応答を返す。"""
    def __init__(self, text, stop_reason="end_turn"):
        self.text = text
        self.stop_reason = stop_reason
        self.messages = self
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        content = kwargs["messages"][0]["content"]
        assert "facts:" in content
        assert "証券コード" not in content and "銘柄名" not in content  # 銘柄を特定できる情報は送らない
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)],
                               stop_reason=self.stop_reason,
                               usage=SimpleNamespace(input_tokens=400, output_tokens=120))


def _api_explainer(text, stop_reason="end_turn"):
    ex = Explainer(Settings(api_key="dummy", model="claude-haiku-5-5", usd_jpy=150,
                            price_in=0.10, price_out=0.50))
    ex.mode, ex.client = "api", FakeClient(text, stop_reason)
    return ex


def test_api_response_with_correct_numbers_is_accepted(records):
    rec = records["EQ0007"]
    f = build_facts(rec)
    body = json.dumps({"explanation": f"数量差は{f['数量差異（カストディ−当社）']}です。",
                       "action": "約定記録を確認してください。"}, ensure_ascii=False)
    ex = _api_explainer(f"```json\n{body}\n```")
    out = ex.explain(rec)
    assert out["explain_status"] == STATUS_AI_OK
    assert ex.usage.input_tokens == 400 and ex.usage.output_tokens == 120
    assert ex.usage.cost_usd == pytest.approx(400 / 1e6 * 0.10 + 120 / 1e6 * 0.50)
    assert ex.client.kwargs["output_config"] == {"effort": "low"}
    assert ex.client.kwargs["max_tokens"] >= 1000


def test_api_response_with_wrong_number_falls_back(records):
    body = json.dumps({"explanation": "数量差は2,500株です。", "action": "確認してください。"},
                      ensure_ascii=False)
    out = _api_explainer(body).explain(records["EQ0007"])
    assert out["explain_status"] == STATUS_FALLBACK_NUM
    assert out["rejected_numbers"] == ["2,500"]


def test_wrong_number_in_action_is_recorded(records):
    """問題の数字が対応案にあるときは、対応案を差し戻した文章として残す。"""
    body = json.dumps({"explanation": "数量が一致していません。",
                       "action": "3営業日以内に約定記録を確認してください。"}, ensure_ascii=False)
    out = _api_explainer(body).explain(records["EQ0007"])
    assert out["explain_status"] == STATUS_FALLBACK_NUM
    assert "3営業日" in out["rejected_text"]


def test_api_broken_json_falls_back(records):
    out = _api_explainer("すみません、うまく出力できませんでした").explain(records["BD0004"])
    assert out["explain_status"] == STATUS_FALLBACK_ERR


def test_api_truncated_output_falls_back(records):
    out = _api_explainer('{"explanation": "単価が', stop_reason="max_tokens").explain(records["BD0004"])
    assert out["explain_status"] == STATUS_FALLBACK_ERR
    assert "max_tokens" in out["rejected_text"]


# ------------------------------------------------------------ pipeline

def test_full_pipeline_mock(tmp_path):
    r = run(DATA / "custodian.csv", DATA / "internal.csv", tmp_path, force_mock=True, settings=NO_KEY)
    assert r["summary"]["discrepancies"] == 6
    assert r["summary"]["validation_failed"] == 0
    html = r["html_path"].read_text(encoding="utf-8")
    for code in ["EQ0007", "EQ0015", "EQ0022", "BD0004", "EQ0031", "BD0012"]:
        assert code in html
    wb = load_workbook(r["xlsx_path"])
    assert wb.sheetnames == ["サマリー", "差異明細", "全銘柄", "AI利用ログ"]
    assert wb["差異明細"].max_row == 7  # 見出し + 6 件
