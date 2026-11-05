"""Excel 出力（サマリー・差異明細・全銘柄・AI利用ログの 4 シート）。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def _style(ws, widths: dict[str, int], num_formats: dict[str, str] | None = None, wrap: set[str] = frozenset()):
    headers = [c.value for c in ws[1]]
    for idx, h in enumerate(headers, start=1):
        col = get_column_letter(idx)
        cell = ws.cell(row=1, column=idx)
        cell.fill, cell.font = HEADER_FILL, HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[col].width = widths.get(h, 14)
        fmt = (num_formats or {}).get(h)
        for row in ws.iter_rows(min_row=2, min_col=idx, max_col=idx):
            for c in row:
                if fmt:
                    c.number_format = fmt
                if h in wrap:
                    c.alignment = Alignment(wrap_text=True, vertical="top")
                else:
                    c.alignment = Alignment(vertical="top")
    ws.freeze_panes = "A2"


def render_excel(result: dict, path: Path) -> None:
    s, u, items = result["summary"], result["usage"], result["discrepancies"]

    summary = pd.DataFrame([
        ("ファンド", result["fund_name"]),
        ("基準日", s["as_of_date"]),
        ("作成日時", result["generated_at"]),
        ("照合銘柄数", s["total"]),
        ("一致", s["matched"]),
        ("差異", s["discrepancies"]),
        ("　うち数量差異", s["by_type"].get("数量差異", 0)),
        ("　うち価格差異", s["by_type"].get("価格差異", 0)),
        ("　うち片側のみ", s["by_type"].get("片側のみ", 0)),
        ("評価額差異（絶対値合計・円）", s["abs_mv_diff"]),
        ("実行モード", "Claude API" if u.mode == "api" else f"モック（{result['mode_reason']}）"),
        ("モデル", u.model or "—"),
        ("AI 呼び出し回数", u.calls),
        ("入力トークン", u.input_tokens),
        ("出力トークン", u.output_tokens),
        ("推定費用（USD）", round(u.cost_usd, 6) if u.cost_usd is not None else "—"),
        ("推定費用（円）", round(u.cost_jpy, 3) if u.cost_jpy is not None else "—"),
    ], columns=["項目", "値"])

    detail = pd.DataFrame([{
        "優先度": d["priority"],
        "証券コード": d["security_code"],
        "銘柄名": d["security_name"],
        "資産区分": d["asset_class_label"],
        "差異区分": "・".join(d["diff_types"]),
        "推定原因": d["category_label"],
        "判定根拠": d["basis"],
        "カストディ数量": d["cust_qty"],
        "当社数量": d["int_qty"],
        "数量差異": d["qty_diff"],
        "カストディ単価": d["cust_price"],
        "当社単価": d["int_price"],
        "単価差異率(%)": round(d["price_diff_pct"], 4) if d["price_diff_pct"] is not None else None,
        "カストディ評価額": d["cust_mv"],
        "当社評価額": d["int_mv"],
        "評価額差異": d["mv_diff"],
        "説明": d["explanation"],
        "対応案": d["action"],
        "説明の状態": d["explain_status"],
        "差し戻した数字": "、".join(d["rejected_numbers"]),
        "差し戻した文章・エラー": d["rejected_text"],
        "対応状況": d["follow_up"],
        "担当者メモ": "",
    } for d in items])

    all_rows = result["all_rows"].rename(columns={
        "security_code": "証券コード", "security_name": "銘柄名", "asset_class_label": "資産区分",
        "presence": "存在", "status": "照合結果", "cust_qty": "カストディ数量", "int_qty": "当社数量",
        "cust_price": "カストディ単価", "int_price": "当社単価", "cust_mv": "カストディ評価額",
        "int_mv": "当社評価額", "mv_diff": "評価額差異", "cust_source": "カストディ価格ソース",
        "int_source": "当社価格ソース",
    })
    all_rows["差異区分"] = result["all_rows"]["diff_types"].map(lambda t: "・".join(t))
    all_rows = all_rows[["証券コード", "銘柄名", "資産区分", "照合結果", "差異区分", "存在",
                         "カストディ数量", "当社数量", "カストディ単価", "当社単価",
                         "カストディ評価額", "当社評価額", "評価額差異",
                         "カストディ価格ソース", "当社価格ソース"]]

    usage_log = pd.DataFrame(u.log or [], columns=["security_code", "input_tokens", "output_tokens", "cost_usd"])
    usage_log.columns = ["証券コード", "入力トークン", "出力トークン", "推定費用（USD）"]

    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="サマリー", index=False)
        detail.to_excel(xw, sheet_name="差異明細", index=False)
        all_rows.to_excel(xw, sheet_name="全銘柄", index=False)
        usage_log.to_excel(xw, sheet_name="AI利用ログ", index=False)

        num = "#,##0;-#,##0"
        _style(xw.sheets["サマリー"], {"項目": 30, "値": 36}, {"値": "#,##0.######"})
        _style(xw.sheets["差異明細"],
               {"銘柄名": 26, "推定原因": 30, "判定根拠": 34, "説明": 60, "対応案": 50, "説明の状態": 30,
                "差し戻した文章・エラー": 50,
                "カストディ数量": 16, "当社数量": 16, "カストディ評価額": 16, "当社評価額": 16, "評価額差異": 14},
               {"カストディ数量": num, "当社数量": num, "数量差異": num, "カストディ単価": "#,##0.00",
                "当社単価": "#,##0.00", "カストディ評価額": num, "当社評価額": num, "評価額差異": num,
                "単価差異率(%)": "0.00"},
               wrap={"推定原因", "判定根拠", "説明", "対応案", "説明の状態", "差し戻した文章・エラー"})
        _style(xw.sheets["全銘柄"],
               {"銘柄名": 30, "差異区分": 16, "カストディ数量": 16, "当社数量": 16,
                "カストディ評価額": 16, "当社評価額": 16, "カストディ価格ソース": 22, "当社価格ソース": 22},
               {"カストディ数量": num, "当社数量": num, "カストディ単価": "#,##0.00", "当社単価": "#,##0.00",
                "カストディ評価額": num, "当社評価額": num, "評価額差異": num})
        _style(xw.sheets["AI利用ログ"], {"推定費用（USD）": 18}, {"推定費用（USD）": "0.000000"})
