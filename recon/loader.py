"""CSV の読み込みと入力チェック。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import PRICE_TOLERANCES

REQUIRED_COLUMNS = [
    "as_of_date", "security_code", "security_name", "asset_class",
    "quantity", "price", "price_source",
]


class InputDataError(ValueError):
    """入力ファイルに問題があるときの例外。"""


def load_positions(path: str | Path, label: str) -> pd.DataFrame:
    path = Path(path)
    if not path.exists():
        raise InputDataError(f"{label}のファイルが見つかりません: {path}")

    df = pd.read_csv(path, dtype={"security_code": str, "as_of_date": str})
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise InputDataError(f"{label}に必須列がありません: {', '.join(missing)}")

    df = df[REQUIRED_COLUMNS].copy()
    df["security_code"] = df["security_code"].str.strip()

    dup = df[df["security_code"].duplicated()]["security_code"].tolist()
    if dup:
        raise InputDataError(f"{label}で証券コードが重複しています: {', '.join(dup)}")

    for col in ("quantity", "price"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
        bad = df[df[col].isna()]["security_code"].tolist()
        if bad:
            raise InputDataError(f"{label}の {col} が数値ではありません: {', '.join(bad)}")

    unknown = sorted(set(df["asset_class"]) - set(PRICE_TOLERANCES))
    if unknown:
        raise InputDataError(f"{label}に未対応の資産区分があります: {', '.join(unknown)}")

    dates = df["as_of_date"].unique()
    if len(dates) != 1:
        raise InputDataError(f"{label}に複数の基準日が混在しています: {', '.join(dates)}")

    return df
