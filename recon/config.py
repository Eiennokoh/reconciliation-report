"""設定値（許容誤差・モデル・料金）をまとめたモジュール。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 資産区分ごとの価格の許容誤差
#   relative: 単価差 ÷ 当社単価 がこの比率を超えたら差異
#   absolute: 単価差（額面100円あたり）がこの値を超えたら差異
PRICE_TOLERANCES: dict[str, dict] = {
    "JP_EQUITY": {"type": "relative", "value": 0.005, "label": "±0.5%"},
    "JGB": {"type": "absolute", "value": 0.05, "label": "±0.05円（額面100円あたり）"},
}

ASSET_CLASS_LABELS = {"JP_EQUITY": "国内株式", "JGB": "日本国債"}

# 優先度の判定に使う評価額差異のしきい値（円）
PRIORITY_HIGH_YEN = 10_000_000
PRIORITY_MID_YEN = 1_000_000

DEFAULT_MODEL = "claude-haiku-5-5"

# API 呼び出しの設定
#   Haiku 5.5 は思考（thinking）が既定でオンで、思考のトークンも max_tokens に含まれる。
#   短い説明文なので effort を low にし、JSON が途中で切れないよう max_tokens に余裕を持たせる。
API_MAX_TOKENS = 1500
API_EFFORT = "low"
API_TIMEOUT_SEC = 30.0   # SDK の既定（10分）だと、通信が詰まったときに長く止まるため
API_MAX_RETRIES = 1      # SDK の既定は 2 回

# 料金（USD / 100万トークン）。2026年11月時点の公開料金。
# 変わることがあるため、環境変数 PRICE_INPUT_PER_MTOK / PRICE_OUTPUT_PER_MTOK で上書きできる。
MODEL_PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    model: str
    usd_jpy: float
    price_in: float | None   # USD / 1M input tokens
    price_out: float | None  # USD / 1M output tokens


def _float_env(name: str) -> float | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def load_dotenv(path: Path) -> None:
    """依存ライブラリを増やさないための簡易 .env ローダー（既存の環境変数は上書きしない）。"""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def get_settings() -> Settings:
    model = os.environ.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODEL
    default_in, default_out = MODEL_PRICING_USD_PER_MTOK.get(model, (None, None))
    price_in = _float_env("PRICE_INPUT_PER_MTOK")
    price_out = _float_env("PRICE_OUTPUT_PER_MTOK")
    return Settings(
        api_key=os.environ.get("ANTHROPIC_API_KEY", "").strip() or None,
        model=model,
        usd_jpy=_float_env("USD_JPY") or 150.0,
        price_in=price_in if price_in is not None else default_in,
        price_out=price_out if price_out is not None else default_out,
    )
