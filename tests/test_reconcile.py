"""照合・分類のテスト。サンプルデータに埋め込んだ差異がすべて検出されることを確認する。"""
from pathlib import Path

import pandas as pd
import pytest

from recon.classify import classify
from recon.loader import InputDataError, load_positions
from recon.reconcile import DIFF_ONE_SIDED, DIFF_PRICE, DIFF_QTY, market_value, reconcile

DATA = Path(__file__).resolve().parent.parent / "data"

# サンプルデータに意図的に埋め込んだ差異（scripts/generate_sample_data.py と同じ前提）
EXPECTED = {
    "EQ0007": ([DIFF_QTY], "UNBOOKED_TRADE"),
    "EQ0015": ([DIFF_QTY, DIFF_PRICE], "CORPORATE_ACTION"),
    "EQ0022": ([DIFF_PRICE], "PRICE_SOURCE"),
    "BD0004": ([DIFF_PRICE], "PRICE_UNKNOWN"),
    "EQ0031": ([DIFF_ONE_SIDED], "CUSTODIAN_ONLY"),
    "BD0012": ([DIFF_ONE_SIDED], "INTERNAL_ONLY"),
}


@pytest.fixture(scope="module")
def result():
    cust = load_positions(DATA / "custodian.csv", "カストディ")
    intl = load_positions(DATA / "internal.csv", "当社")
    all_rows, disc = reconcile(cust, intl)
    return all_rows, {d["security_code"]: classify(d) for d in disc}


def test_all_embedded_discrepancies_are_detected(result):
    _, disc = result
    missing = set(EXPECTED) - set(disc)
    assert not missing, f"検出漏れ: {missing}"


def test_no_false_positives(result):
    """許容誤差内のノイズ（1円・0.01円のずれ）は差異にしない。"""
    _, disc = result
    extra = set(disc) - set(EXPECTED)
    assert not extra, f"余計な検出: {extra}"


@pytest.mark.parametrize("code", EXPECTED)
def test_diff_types_and_category(result, code):
    _, disc = result
    types, category = EXPECTED[code]
    assert disc[code]["diff_types"] == types
    assert disc[code]["category"] == category


def test_numbers_are_computed_correctly(result):
    _, disc = result
    assert disc["EQ0007"]["qty_diff"] == 2_000
    assert disc["EQ0007"]["mv_diff"] == 2_000 * 2_860
    assert disc["EQ0015"]["split_ratio"] == (1, 2)
    assert disc["EQ0015"]["mv_diff"] == 0
    assert disc["EQ0022"]["mv_diff"] == 45_000 * (3_415 - 3_380)
    assert disc["BD0004"]["mv_diff"] == 7_000_000          # 額面10億 × 0.70 ÷ 100
    assert disc["EQ0031"]["mv_diff"] == 8_000 * 4_120
    assert disc["BD0012"]["mv_diff"] == -500_250_000


def test_row_counts(result):
    all_rows, disc = result
    assert len(all_rows) == 49
    assert (all_rows["status"] == "一致").sum() == 49 - len(EXPECTED)


def test_market_value_formula():
    assert market_value("JP_EQUITY", 100, 1_234) == 123_400
    assert market_value("JGB", 100_000_000, 99.5) == 99_500_000


def test_tolerance_boundary():
    """株式の許容誤差（0.5%）ちょうどは一致、超えたら差異。"""
    def frame(price):
        return pd.DataFrame([dict(as_of_date="2026-10-30", security_code="X1", security_name="テスト",
                                  asset_class="JP_EQUITY", quantity=100, price=price, price_source="S")])
    _, d1 = reconcile(frame(1_005.0), frame(1_000.0))
    _, d2 = reconcile(frame(1_006.0), frame(1_000.0))
    assert d1 == []
    assert d2[0]["diff_types"] == [DIFF_PRICE]


def test_loader_rejects_duplicates(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("as_of_date,security_code,security_name,asset_class,quantity,price,price_source\n"
                 "2026-10-30,A1,x,JP_EQUITY,1,1,S\n2026-10-30,A1,x,JP_EQUITY,1,1,S\n", encoding="utf-8")
    with pytest.raises(InputDataError):
        load_positions(p, "テスト")
