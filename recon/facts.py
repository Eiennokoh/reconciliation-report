"""差異レコードを、AI に渡す「事実（facts）」の文字列に整形する。

AI はここで整形された文字列だけを見る。説明文に出てくる数字は、必ずこの中のどれかと
一致していなければならない（validator.py で検査する）。
"""
from __future__ import annotations


def _num(v: float, decimals: int = 0) -> str:
    return f"{v:,.{decimals}f}"


def fmt_qty(asset_class: str, v: float | None) -> str | None:
    if v is None:
        return None
    return f"額面{_num(v)}円" if asset_class == "JGB" else f"{_num(v)}株"


def fmt_signed_qty(asset_class: str, v: float) -> str:
    sign = "+" if v > 0 else ("-" if v < 0 else "±")
    body = fmt_qty(asset_class, abs(v))
    return f"{sign}{body}"


def fmt_price(asset_class: str, v: float | None) -> str | None:
    if v is None:
        return None
    if asset_class == "JGB":
        return f"{v:.2f}円"
    return f"{_num(v)}円" if float(v).is_integer() else f"{_num(v, 1)}円"


def fmt_signed(v: float, decimals: int = 0, suffix: str = "") -> str:
    sign = "+" if v > 0 else ("-" if v < 0 else "±")
    return f"{sign}{_num(abs(v), decimals)}{suffix}"


def build_facts(rec: dict) -> dict[str, str]:
    ac = rec["asset_class"]
    facts: dict[str, str | None] = {
        "基準日": rec["as_of_date"],
        "証券コード": rec["security_code"],
        "銘柄名": rec["security_name"],
        "資産区分": rec["asset_class_label"],
        "検出した差異": "・".join(rec["diff_types"]),
        "推定原因（ルール判定）": rec["category_label"],
        "判定根拠": rec["basis"],
        "存在": rec["presence"],
        "カストディ数量": fmt_qty(ac, rec["cust_qty"]),
        "当社数量": fmt_qty(ac, rec["int_qty"]),
        "カストディ単価": fmt_price(ac, rec["cust_price"]),
        "当社単価": fmt_price(ac, rec["int_price"]),
        "カストディ評価額": f"{_num(rec['cust_mv'])}円" if rec["cust_mv"] is not None else None,
        "当社評価額": f"{_num(rec['int_mv'])}円" if rec["int_mv"] is not None else None,
        "評価額差異（カストディ−当社）": fmt_signed(rec["mv_diff"], suffix="円"),
        "カストディ価格ソース": rec["cust_source"],
        "当社価格ソース": rec["int_source"],
    }
    if rec["presence"] == "両方":
        facts["数量差異（カストディ−当社）"] = fmt_signed_qty(ac, rec["qty_diff"])
        dec = 2 if ac == "JGB" else 0
        facts["単価差異（カストディ−当社）"] = fmt_signed(rec["price_diff"], dec, "円")
        facts["単価差異率"] = fmt_signed(rec["price_diff_pct"], 2, "%")
    if rec.get("split_ratio"):
        a, b = rec["split_ratio"]
        facts["分割比率（当社:カストディ）"] = f"{a}:{b}"
    return {k: v for k, v in facts.items() if v is not None}


# 説明文を書くのに不要で、外部に出したくない項目。AI には送らない（報告書には載せる）。
AI_EXCLUDED_KEYS = ("基準日", "証券コード", "銘柄名")


def facts_for_ai(facts: dict[str, str]) -> dict[str, str]:
    """AI に送る facts。銘柄を特定できる情報（コード・銘柄名）と基準日を除く。"""
    return {k: v for k, v in facts.items() if k not in AI_EXCLUDED_KEYS}
