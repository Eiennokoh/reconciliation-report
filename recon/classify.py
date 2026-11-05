"""差異の原因をルールで推定して分類する。判定はすべてコード側で行い、AI には任せない。"""
from __future__ import annotations

from .config import PRIORITY_HIGH_YEN, PRIORITY_MID_YEN
from .reconcile import DIFF_PRICE, DIFF_QTY

CATEGORIES = {
    "CUSTODIAN_ONLY": "当社記録漏れの疑い（カストディのみに存在）",
    "INTERNAL_ONLY": "償還・売却の未反映の疑い（当社記録のみに存在）",
    "CORPORATE_ACTION": "株式分割（併合）の未反映",
    "UNBOOKED_TRADE": "取引の未計上（約定・受渡のずれを含む）",
    "PRICE_SOURCE": "価格ソースの違い",
    "PRICE_UNKNOWN": "価格差異（原因要調査）",
}

# 分割・併合とみなす比率
SPLIT_RATIOS = (2, 3, 4, 5, 10)
# 分割前後の評価額のずれをどこまで許すか（1%）
SPLIT_MV_TOLERANCE = 0.01

DEFAULT_ACTIONS = {
    "CUSTODIAN_ONLY": "約定記録と銘柄マスタを確認し、必要に応じて計上してください。",
    "INTERNAL_ONLY": "償還スケジュールと受渡状況を確認し、カストディへ照会してください。",
    "CORPORATE_ACTION": "コーポレートアクション情報で比率と効力発生日を確認し、当社の数量と単価を修正してください。",
    "UNBOOKED_TRADE": "約定記録を確認し、未計上の取引があれば計上してください。",
    "PRICE_SOURCE": "評価方針で定めた価格ソースを確認し、どちらを正とするか決めてください。",
    "PRICE_UNKNOWN": "双方の価格取得記録を確認し、原因が分かるまで差異として管理してください。",
}


def _split_ratio(cust_qty: float, int_qty: float) -> tuple[int, int] | None:
    """数量比が分割・併合の比率にあてはまれば (当社側, カストディ側) を返す。例：1:2。"""
    if not cust_qty or not int_qty:
        return None
    for n in SPLIT_RATIOS:
        if abs(cust_qty - int_qty * n) < 1e-9:
            return (1, n)   # カストディ側だけ分割済み
        if abs(int_qty - cust_qty * n) < 1e-9:
            return (n, 1)   # カストディ側だけ併合済み
    return None


def classify(rec: dict) -> dict:
    """差異レコードに category / category_label / basis / priority / split_ratio を付けて返す。"""
    presence = rec["presence"]
    types = rec["diff_types"]
    split = None

    if presence == "カストディのみ":
        code, basis = "CUSTODIAN_ONLY", "カストディの残高にあり、当社記録に該当銘柄がない"
    elif presence == "当社のみ":
        code, basis = "INTERNAL_ONLY", "当社記録にあり、カストディの残高に該当銘柄がない"
    elif DIFF_QTY in types:
        ratio = _split_ratio(rec["cust_qty"], rec["int_qty"])
        mv_close = (
            rec["int_mv"] and abs(rec["mv_diff"]) / abs(rec["int_mv"]) <= SPLIT_MV_TOLERANCE
        )
        if rec["asset_class"] == "JP_EQUITY" and ratio and mv_close:
            split = ratio
            code = "CORPORATE_ACTION"
            basis = f"数量比が{ratio[0]}:{ratio[1]}で、評価額の差が1%以内（単価が逆比率で動いている）"
        else:
            code = "UNBOOKED_TRADE"
            basis = "数量だけが一致しない" if DIFF_PRICE not in types else "数量と価格の両方が一致しない"
    else:  # 価格差異のみ
        if rec["cust_source"] != rec["int_source"]:
            code, basis = "PRICE_SOURCE", "単価が許容範囲を超え、価格ソースも異なる"
        else:
            code, basis = "PRICE_UNKNOWN", "単価が許容範囲を超えているが、価格ソースは同じ"

    mv = abs(rec["mv_diff"])
    if presence != "両方" or mv >= PRIORITY_HIGH_YEN:
        priority = "高"
    elif code == "CORPORATE_ACTION" or mv >= PRIORITY_MID_YEN:
        priority = "中"
    else:
        priority = "低"

    return {
        **rec,
        "category": code,
        "category_label": CATEGORIES[code],
        "basis": basis,
        "priority": priority,
        "split_ratio": split,
    }
