"""AI が書いた説明文の数字チェック。

方針：説明文に出てくる数字は、facts（コードが計算した値）に含まれる数字のどれかと
完全に一致しなければならない。次のものも不合格にする。

- 基準日・証券コード・銘柄名・判定根拠に含まれる数字だけを根拠にした数字
  （例：基準日 2026-10-30 の「10」「30」、EQ0007 の「7」）
- 符号つきの数字で、符号が facts と逆のもの（例：facts は +5,720,000円 なのに -5,720,000円）
- 概数の表現（「約」「およそ」「程度」など）
- 漢数字や「千・万・億」を使った数字（例：「三千株」「572万円」）

誤検知（正しいのに弾く）は起こりうるが、その場合はテンプレート説明に戻るだけなので、
「間違った数字が報告書に載る」より安全側に倒している。
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation

# 数量・金額ではなく、識別用の数字しか含まない facts の項目
NON_NUMERIC_KEYS = frozenset({"基準日", "証券コード", "銘柄名", "判定根拠"})

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SIGNED_NUMBER = re.compile(r"([+\-−△±])?(\d[\d,]*(?:\.\d+)?)")
_SIGN_MAP = {"+": "+", "-": "-", "−": "-", "△": "-", "±": "±"}

_APPROX = re.compile(
    r"(?:約|およそ|概ね|おおむね|ほぼ)\s*[+\-−△±]?\d[\d,]*(?:\.\d+)?"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:株|円|%|％)?\s*(?:程度|前後|余り|あまり)"
)
_KANJI_NUMBER = re.compile(
    r"(?<![同統唯均単])[〇一二三四五六七八九十百千万億兆]+"
    r"(?:株|円|回|件|営業日|日|か月|ヶ月|カ月|年|倍|割|銘柄|%|％)"
    r"|\d[\d,]*(?:\.\d+)?\s*[千万億兆]"
)


def _normalize(token: str) -> Decimal | None:
    try:
        return Decimal(token.replace(",", "")).normalize()
    except InvalidOperation:
        return None


def extract_numbers(text: str) -> list[Decimal]:
    """文中の数字を取り出す（全角は半角に、カンマは除去、符号は無視）。"""
    text = unicodedata.normalize("NFKC", text)
    out = []
    for m in _NUMBER.finditer(text):
        val = _normalize(m.group().rstrip(","))
        if val is not None:
            out.append(val)
    return out


def _signed_tokens(text: str) -> list[tuple[str | None, Decimal, str]]:
    """(符号, 値, 原文の表記) のリスト。符号がなければ None。"""
    text = unicodedata.normalize("NFKC", text)
    out = []
    for m in _SIGNED_NUMBER.finditer(text):
        raw = m.group(2).rstrip(",")
        val = _normalize(raw)
        if val is None:
            continue
        sign = _SIGN_MAP.get(m.group(1)) if m.group(1) else None
        out.append((sign, val, (m.group(1) or "") + raw))
    return out


def allowed_numbers(facts: dict[str, str]) -> tuple[set[Decimal], set[tuple[str, Decimal]]]:
    """(符号なしで使ってよい値, 符号つきで使ってよい (符号, 値)) を返す。"""
    unsigned: set[Decimal] = set()
    signed: set[tuple[str, Decimal]] = set()
    for key, value in facts.items():
        if key in NON_NUMERIC_KEYS:
            continue
        for sign, val, _ in _signed_tokens(str(value)):
            unsigned.add(val)
            if sign:
                signed.add((sign, val))
    return unsigned, signed


def find_unverified_numbers(text: str, facts: dict[str, str]) -> list[str]:
    """facts と一致しない数字・表現を、文中の表記のまま返す。空リストなら合格。"""
    unsigned, signed = allowed_numbers(facts)
    bad: list[str] = []
    for sign, val, raw in _signed_tokens(text):
        ok = (sign, val) in signed if sign else val in unsigned
        if not ok:
            bad.append(raw)
    norm = unicodedata.normalize("NFKC", text)
    bad += [m.group().strip() for m in _APPROX.finditer(norm)]
    bad += [m.group().strip() for m in _KANJI_NUMBER.finditer(norm)]
    return list(dict.fromkeys(bad))  # 重複を除き、出てきた順に
