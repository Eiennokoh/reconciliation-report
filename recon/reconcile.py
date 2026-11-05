"""照合ロジック。数字はすべてここで計算し、AI には渡すだけにする。"""
from __future__ import annotations

import pandas as pd

from .config import ASSET_CLASS_LABELS, PRICE_TOLERANCES

DIFF_QTY = "数量差異"
DIFF_PRICE = "価格差異"
DIFF_ONE_SIDED = "片側のみ"


class AsOfDateMismatch(ValueError):
    pass


def market_value(asset_class: str, quantity: float | None, price: float | None) -> int | None:
    """評価額（円）。株式は 数量×単価、国債は 額面×単価÷100。"""
    if quantity is None or price is None or pd.isna(quantity) or pd.isna(price):
        return None
    if asset_class == "JGB":
        return round(quantity * price / 100)
    return round(quantity * price)


def price_exceeds_tolerance(asset_class: str, cust_price: float, int_price: float) -> bool:
    tol = PRICE_TOLERANCES[asset_class]
    diff = abs(cust_price - int_price)
    if tol["type"] == "relative":
        if int_price == 0:
            return diff > 0
        return diff / abs(int_price) > tol["value"] + 1e-12
    return diff > tol["value"] + 1e-9


def _none_if_nan(v):
    return None if v is None or pd.isna(v) else v


def reconcile(custodian: pd.DataFrame, internal: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """証券コードで突き合わせ、全銘柄の照合結果と差異リストを返す。"""
    c_date, i_date = custodian["as_of_date"].iloc[0], internal["as_of_date"].iloc[0]
    if c_date != i_date:
        raise AsOfDateMismatch(f"基準日が一致しません（カストディ {c_date} / 当社 {i_date}）")

    merged = custodian.merge(
        internal, on="security_code", how="outer", suffixes=("_cust", "_int"), indicator=True
    ).sort_values("security_code", kind="stable")

    rows: list[dict] = []
    discrepancies: list[dict] = []

    for _, r in merged.iterrows():
        side = r["_merge"]
        asset_class = r["asset_class_cust"] if side != "right_only" else r["asset_class_int"]
        name = r["security_name_cust"] if side != "right_only" else r["security_name_int"]

        cq, iq = _none_if_nan(r["quantity_cust"]), _none_if_nan(r["quantity_int"])
        cp, ip = _none_if_nan(r["price_cust"]), _none_if_nan(r["price_int"])
        cmv, imv = market_value(asset_class, cq, cp), market_value(asset_class, iq, ip)

        diff_types: list[str] = []
        if side != "both":
            diff_types.append(DIFF_ONE_SIDED)
        else:
            if cq != iq:
                diff_types.append(DIFF_QTY)
            if price_exceeds_tolerance(asset_class, cp, ip):
                diff_types.append(DIFF_PRICE)

        rec = {
            "as_of_date": c_date,
            "security_code": r["security_code"],
            "security_name": name,
            "asset_class": asset_class,
            "asset_class_label": ASSET_CLASS_LABELS.get(asset_class, asset_class),
            "presence": {"both": "両方", "left_only": "カストディのみ", "right_only": "当社のみ"}[side],
            "cust_qty": cq,
            "int_qty": iq,
            "qty_diff": (cq or 0) - (iq or 0),
            "cust_price": cp,
            "int_price": ip,
            "price_diff": (cp - ip) if cp is not None and ip is not None else None,
            "price_diff_pct": ((cp - ip) / ip * 100) if cp is not None and ip else None,
            "cust_mv": cmv,
            "int_mv": imv,
            "mv_diff": (cmv or 0) - (imv or 0),
            "cust_source": _none_if_nan(r["price_source_cust"]),
            "int_source": _none_if_nan(r["price_source_int"]),
            "diff_types": diff_types,
            "status": "差異" if diff_types else "一致",
        }
        rows.append(rec)
        if diff_types:
            discrepancies.append(rec)

    return pd.DataFrame(rows), discrepancies
