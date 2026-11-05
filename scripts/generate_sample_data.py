"""サンプルデータ（すべて架空）を生成するスクリプト。

    python scripts/generate_sample_data.py

data/custodian.csv と data/internal.csv を上書きします。乱数シードを固定しているため、
何度実行しても同じ内容になります。意図的に埋め込んだ差異は EXPECTED_DISCREPANCIES の
とおりで、tests/ でも同じ前提を使っています。
"""
from __future__ import annotations

import csv
import random
from pathlib import Path

AS_OF = "2026-10-30"
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

EQUITY_NAMES = [
    "架空精機", "サンプル電機", "みなと化学", "あおば製薬", "つばさ自動車部品", "ひかり通信",
    "やまびこ食品", "さくら物流", "かえで建設", "しろがね鉄鋼", "わかば住宅", "こまち電子",
    "あさひ商事", "ほしぞら航空サービス", "ふじみ不動産", "なぎさ海運", "いぶき機械", "ことり玩具",
    "みずほし精密", "あかね化粧品", "そよかぜ電力", "はやて情報システム", "くすのき製紙", "あおぞら銀行持株",
    "ひだまり外食", "まつかぜ保険", "いずみ半導体", "たちばな医療機器", "ゆうなぎ百貨店", "しおさい水産",
    "かがやき光学", "つきみ繊維", "あけぼのガス", "もみじ証券ホールディングス",
]
EQUITY_SOURCE = "東証終値"
JGB_SOURCE = "日証協 売買参考統計値"

# (証券コード, 内容) — README とテストで同じ前提を使う
EXPECTED_DISCREPANCIES = {
    "EQ0007": "数量差異（取引未計上）",
    "EQ0015": "株式分割の未反映（1:2）",
    "EQ0022": "価格差異（価格ソースの違い）",
    "BD0004": "価格差異（同じソースで差異・原因要調査）",
    "EQ0031": "カストディのみに存在",
    "BD0012": "当社記録のみに存在",
}


def build_rows() -> tuple[list[dict], list[dict]]:
    rng = random.Random(20261030)
    custodian: list[dict] = []
    internal: list[dict] = []

    for i, name in enumerate(EQUITY_NAMES, start=1):
        code = f"EQ{i:04d}"
        qty = rng.randint(10, 500) * 100
        price = float(rng.randint(500, 9000))
        row = dict(as_of_date=AS_OF, security_code=code, security_name=name,
                   asset_class="JP_EQUITY", quantity=qty, price=price, price_source=EQUITY_SOURCE)
        c, n = dict(row), dict(row)
        # 許容範囲内のノイズ（1円のずれ。0.1%未満なので差異にならない）
        if price >= 1000 and i % 5 == 0:
            n["price"] = price + rng.choice([-1, 1])
        custodian.append(c)
        internal.append(n)

    for i in range(1, 16):
        code = f"BD{i:04d}"
        name = f"利付国債（10年）第{350 + i}回〔架空〕"
        face = rng.randint(1, 20) * 100_000_000
        price = round(rng.uniform(97.0, 101.5), 2)
        row = dict(as_of_date=AS_OF, security_code=code, security_name=name,
                   asset_class="JGB", quantity=face, price=price, price_source=JGB_SOURCE)
        c, n = dict(row), dict(row)
        if i % 4 == 0:  # 許容範囲（0.05）内のノイズ
            n["price"] = round(price + 0.01, 2)
        custodian.append(c)
        internal.append(n)

    def find(rows, code):
        return next(r for r in rows if r["security_code"] == code)

    # 1) 数量差異：カストディ側に 2,000 株多い（買付の未計上を想定）
    c, n = find(custodian, "EQ0007"), find(internal, "EQ0007")
    c.update(quantity=12_000, price=2_860.0)
    n.update(quantity=10_000, price=2_860.0)

    # 2) 株式分割（1株→2株）がカストディだけに反映されている
    c, n = find(custodian, "EQ0015"), find(internal, "EQ0015")
    c.update(quantity=6_000, price=1_250.0)
    n.update(quantity=3_000, price=2_500.0)

    # 3) 価格ソースの違いによる価格差異
    c, n = find(custodian, "EQ0022"), find(internal, "EQ0022")
    c.update(quantity=45_000, price=3_415.0)
    n.update(quantity=45_000, price=3_380.0, price_source="評価ベンダーA")

    # 4) 同じ価格ソースなのに価格差異（入力ミス等を想定）
    c, n = find(custodian, "BD0004"), find(internal, "BD0004")
    c.update(quantity=1_000_000_000, price=99.82)
    n.update(quantity=1_000_000_000, price=99.12)

    # 5) カストディのみに存在（当社の計上漏れを想定）
    internal.remove(find(internal, "EQ0031"))
    find(custodian, "EQ0031").update(quantity=8_000, price=4_120.0)

    # 6) 当社記録のみに存在（償還・売却の未反映を想定）
    custodian.remove(find(custodian, "BD0012"))
    find(internal, "BD0012").update(quantity=500_000_000, price=100.05)

    return custodian, internal


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = ["as_of_date", "security_code", "security_name", "asset_class",
              "quantity", "price", "price_source"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            out = dict(r)
            p = out["price"]
            out["price"] = f"{p:.2f}" if out["asset_class"] == "JGB" else (
                str(int(p)) if float(p).is_integer() else str(p))
            w.writerow(out)


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    custodian, internal = build_rows()
    write_csv(DATA_DIR / "custodian.csv", custodian)
    write_csv(DATA_DIR / "internal.csv", internal)
    print(f"custodian.csv: {len(custodian)} 行 / internal.csv: {len(internal)} 行")


if __name__ == "__main__":
    main()
