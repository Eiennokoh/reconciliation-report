"""残高照合レポートの実行入口。

    python main.py                      # .env に API キーがあれば Claude API、なければモック
    python main.py --mock               # API を使わずに実行
    python main.py --demo-hallucination --open   # AI の数字の誤りを検査が弾く様子を再現し、HTML を開く
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
import webbrowser
from pathlib import Path

from recon.config import load_dotenv
from recon.explainer import STATUS_AI_OK, STATUS_MOCK_OK
from recon.loader import InputDataError
from recon.pipeline import run
from recon.reconcile import AsOfDateMismatch

ROOT = Path(__file__).resolve().parent


def _width(s: str) -> int:
    """端末での表示幅（全角は 2）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _ljust(s: str, n: int) -> str:
    return s + " " * max(n - _width(s), 0)


def _rjust(s: str, n: int) -> str:
    return " " * max(n - _width(s), 0) + s


def _sentences_with(text: str, tokens: list[str]) -> list[str]:
    """差し戻した文章のうち、問題の数字を含む文だけを取り出す。"""
    sents = [s for s in re.split(r"(?<=。)|\n", text) if s.strip()]
    hit = [re.sub(r"^(説明|対応案)：", "", s).strip() for s in sents if any(t in s for t in tokens)]
    return hit or [text.strip()]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="カストディ残高と当社記録の照合レポートを作成します")
    p.add_argument("--custodian", default=ROOT / "data" / "custodian.csv")
    p.add_argument("--internal", default=ROOT / "data" / "internal.csv")
    p.add_argument("--out", default=ROOT / "output")
    p.add_argument("--mock", action="store_true", help="API を呼ばずに用意済みの説明文で実行する")
    p.add_argument("--demo-hallucination", action="store_true",
                   help="モック説明に根拠のない数字を混ぜ、検査で差し戻される様子を見せる")
    p.add_argument("--open", action="store_true", help="終了後に HTML 報告書をブラウザで開く")
    args = p.parse_args(argv)

    # 中国語・日本語版 Windows などで出力先の文字コード（GBK / CP932）が日本語の一部
    # （「・」など）を表せないと print が UnicodeEncodeError で止まるため、表せない文字は置き換える。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

    load_dotenv(ROOT / ".env")
    try:
        r = run(args.custodian, args.internal, args.out,
                force_mock=args.mock, demo_hallucination=args.demo_hallucination)
    except (InputDataError, AsOfDateMismatch) as e:
        print(f"[エラー] {e}", file=sys.stderr)
        return 1

    s, u = r["summary"], r["usage"]
    mode = f"Claude API（{u.model}）" if u.mode == "api" else f"モック（{r['mode_reason']}）"
    print(f"\n基準日 {s['as_of_date']}｜照合 {s['total']} 銘柄｜一致 {s['matched']}｜差異 {s['discrepancies']}｜AI: {mode}\n")

    cols = (8, 8, 18, 10)
    print("  " + _ljust("優先度", cols[0]) + _ljust("コード", cols[1]) + _rjust("評価額差異（円）", cols[2])
          + "  " + _ljust("説明", cols[3]) + "推定原因")
    for d in r["discrepancies"]:
        ok = d["explain_status"] in (STATUS_AI_OK, STATUS_MOCK_OK)
        print("  " + _ljust(d["priority"], cols[0]) + _ljust(d["security_code"], cols[1])
              + _rjust(f"{d['mv_diff']:+,}", cols[2]) + "  " + _ljust("検証OK" if ok else "差し戻し", cols[3])
              + d["category_label"])
        if d["rejected_numbers"]:
            nums = "」「".join(d["rejected_numbers"])
            print(f"      ! 計算結果にない数字・表現「{nums}」があったため、テンプレート説明に差し替えました")
            for sent in _sentences_with(d["rejected_text"], d["rejected_numbers"]):
                print(f"        差し戻した文：{sent}")
        elif d["rejected_text"]:
            print(f"      ! AI の応答を使えなかったため、テンプレート説明に差し替えました：{d['rejected_text']}")

    if u.mode != "api":
        cost = "0 円（API 未使用）"
    else:
        cost = "—（料金未設定のモデル）" if u.cost_usd is None else f"${u.cost_usd:.6f}（約 {u.cost_jpy:.3f} 円）"
    print(f"\nAI 呼び出し {u.calls} 回｜トークン 入力 {u.input_tokens:,} / 出力 {u.output_tokens:,}｜推定費用 {cost}")
    print(f"HTML : {r['html_path']}\nExcel: {r['xlsx_path']}")
    if args.open:
        webbrowser.open(Path(r["html_path"]).resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
