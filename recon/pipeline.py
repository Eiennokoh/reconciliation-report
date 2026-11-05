"""読込 → 照合 → 分類 → 説明 → 報告書 の流れをまとめる。"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from .classify import classify
from .config import Settings, get_settings
from .explainer import STATUS_AI_OK, STATUS_MOCK_OK, Explainer
from .loader import load_positions
from .reconcile import reconcile
from .report_excel import render_excel
from .report_html import render_html

PRIORITY_ORDER = {"高": 0, "中": 1, "低": 2}


def run(custodian_path: str | Path, internal_path: str | Path, out_dir: str | Path,
        fund_name: str = "架空日本株・国債バランスファンド",
        force_mock: bool = False, demo_hallucination: bool = False,
        settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 読込
    cust = load_positions(custodian_path, "カストディ残高")
    intl = load_positions(internal_path, "当社記録")

    # 2. 照合（数字はすべてここで確定）
    all_rows, raw = reconcile(cust, intl)

    # 3. 分類（ルール判定）
    classified = [classify(r) for r in raw]
    classified.sort(key=lambda d: (PRIORITY_ORDER[d["priority"]], -abs(d["mv_diff"]), d["security_code"]))

    # 4. 説明（AI は差異の行だけを受け取る）
    explainer = Explainer(settings, force_mock=force_mock, demo_hallucination=demo_hallucination)
    explained = []
    for i, d in enumerate(classified):
        e = explainer.explain(d, index=i)
        e["follow_up"] = "未対応"
        explained.append(e)

    by_type = Counter(t for d in explained for t in d["diff_types"])
    summary = {
        "as_of_date": cust["as_of_date"].iloc[0],
        "custodian_rows": len(cust),
        "internal_rows": len(intl),
        "total": len(all_rows),
        "matched": int((all_rows["status"] == "一致").sum()),
        "discrepancies": len(explained),
        "by_type": dict(by_type),
        "abs_mv_diff": int(sum(abs(d["mv_diff"]) for d in explained)),
        "validation_failed": sum(1 for d in explained
                                 if d["explain_status"] not in (STATUS_AI_OK, STATUS_MOCK_OK)),
    }

    result = {
        "fund_name": fund_name,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "summary": summary,
        "all_rows": all_rows,
        "discrepancies": explained,
        "usage": explainer.usage,
        "mode_reason": explainer.mode_reason,
    }

    # 5. 報告書
    stamp = summary["as_of_date"].replace("-", "")
    html_path = out_dir / f"reconciliation_{stamp}.html"
    xlsx_path = out_dir / f"reconciliation_{stamp}.xlsx"
    render_html(result, html_path)
    render_excel(result, xlsx_path)
    result["html_path"], result["xlsx_path"] = html_path, xlsx_path
    return result
