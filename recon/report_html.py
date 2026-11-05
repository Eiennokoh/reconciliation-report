"""HTML 報告書（1 ファイルで完結、外部読み込みなし）。"""
from __future__ import annotations

from html import escape
from pathlib import Path

from .config import PRICE_TOLERANCES, ASSET_CLASS_LABELS
from .explainer import STATUS_AI_OK, STATUS_MOCK_OK

CSS = """
:root{--bg:#f6f5f2;--panel:#fff;--ink:#1d1f23;--muted:#666b73;--line:#e3e1dc;
--accent:#1f4e79;--hi:#b42318;--hi-bg:#fde8e6;--mid:#9a5b00;--mid-bg:#fdf1dc;--lo:#3d6b35;--lo-bg:#e6f2e2;
--ok:#1f6f43;--ok-bg:#e3f3ea;--warn:#8a3b00;--warn-bg:#fdebd9;--code-bg:#f0eee9}
@media (prefers-color-scheme:dark){:root{--bg:#15171a;--panel:#1e2125;--ink:#e8e6e1;--muted:#9aa0a8;--line:#30343a;
--accent:#8cb8e6;--hi:#ff8a80;--hi-bg:#3a1f1d;--mid:#f0b45a;--mid-bg:#3a2d17;--lo:#9fd28f;--lo-bg:#1f3320;
--ok:#7fd3a4;--ok-bg:#183326;--warn:#f5a66b;--warn-bg:#3a2516;--code-bg:#262a2f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 "Hiragino Sans","Yu Gothic UI","Noto Sans JP",system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:28px 16px 48px}
header h1{margin:0 0 4px;font-size:22px;letter-spacing:.02em}
header .meta{color:var(--muted);font-size:13px}
.mode{display:inline-block;margin-top:8px;padding:2px 10px;border-radius:999px;font-size:12px;border:1px solid var(--line);background:var(--panel)}
h2{font-size:16px;margin:32px 0 12px;padding-left:10px;border-left:4px solid var(--accent)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-top:20px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.kpi .l{font-size:12px;color:var(--muted)} .kpi .v{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}
.kpi .s{font-size:12px;color:var(--muted)}
.tbl{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px}
.tbl th,.tbl td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
.tbl th{background:var(--code-bg);font-weight:600;white-space:nowrap}
.tbl td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.scroll{overflow-x:auto;border-radius:10px}
.badge{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.p-高{color:var(--hi);background:var(--hi-bg)} .p-中{color:var(--mid);background:var(--mid-bg)} .p-低{color:var(--lo);background:var(--lo-bg)}
.st-ok{color:var(--ok);background:var(--ok-bg)} .st-fb{color:var(--warn);background:var(--warn-bg)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:14px}
.card .top{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:6px}
.card .code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px;color:var(--muted)}
.card .name{font-weight:700;font-size:16px}
.card .cat{color:var(--accent);font-weight:600;font-size:14px;margin-bottom:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:6px 18px;font-size:13px;margin:8px 0 12px;
padding:10px 12px;background:var(--code-bg);border-radius:8px}
.grid div span{color:var(--muted);margin-right:6px}
.grid b{font-variant-numeric:tabular-nums}
.label{font-size:12px;color:var(--muted);margin-top:8px}
.text{margin:2px 0 0}
.rej{margin-top:10px;padding:8px 12px;border-left:3px solid var(--warn);background:var(--warn-bg);font-size:13px}
.rej s{opacity:.8}
.note{font-size:13px;color:var(--muted)}
footer{margin-top:40px;font-size:12px;color:var(--muted);border-top:1px solid var(--line);padding-top:12px}
"""


def _e(v) -> str:
    return escape("" if v is None else str(v))


def _yen(v) -> str:
    return "—" if v is None else f"{v:,.0f}"


def _signed_yen(v) -> str:
    return f"{v:+,.0f}" if v else "0"


def render_html(result: dict, path: Path) -> None:
    s = result["summary"]
    u = result["usage"]
    items = result["discrepancies"]

    if u.mode == "api":
        mode_text = f"AI：Claude API（{_e(u.model)}）"
    else:
        mode_text = f"AI：モックモード（{_e(result['mode_reason'])}）"

    kpis = f"""
<div class="kpis">
 <div class="kpi"><div class="l">照合銘柄数</div><div class="v">{s['total']}</div><div class="s">カストディ {s['custodian_rows']} / 当社 {s['internal_rows']}</div></div>
 <div class="kpi"><div class="l">一致</div><div class="v">{s['matched']}</div><div class="s">許容誤差内を含む</div></div>
 <div class="kpi"><div class="l">差異</div><div class="v" style="color:var(--hi)">{s['discrepancies']}</div><div class="s">数量 {s['by_type'].get('数量差異',0)} ・ 価格 {s['by_type'].get('価格差異',0)} ・ 片側 {s['by_type'].get('片側のみ',0)}</div></div>
 <div class="kpi"><div class="l">評価額差異（絶対値合計）</div><div class="v">{_yen(s['abs_mv_diff'])}</div><div class="s">円</div></div>
</div>"""

    rows = []
    for d in items:
        ok = d["explain_status"] in (STATUS_AI_OK, STATUS_MOCK_OK)
        rows.append(
            f"<tr><td><span class='badge p-{_e(d['priority'])}'>{_e(d['priority'])}</span></td>"
            f"<td>{_e(d['security_code'])}</td><td>{_e(d['security_name'])}</td>"
            f"<td>{_e('・'.join(d['diff_types']))}</td><td>{_e(d['category_label'])}</td>"
            f"<td class='n'>{_signed_yen(d['mv_diff'])}</td>"
            f"<td><span class='badge {'st-ok' if ok else 'st-fb'}'>{'検証OK' if ok else '差し戻し'}</span></td>"
            f"<td>{_e(d['follow_up'])}</td></tr>"
        )
    table = f"""
<div class="scroll"><table class="tbl">
<thead><tr><th>優先度</th><th>コード</th><th>銘柄</th><th>差異区分</th><th>推定原因</th><th>評価額差異（円）</th><th>説明</th><th>対応状況</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>"""

    cards = []
    for d in items:
        f = d["facts"]
        keys = ["カストディ数量", "当社数量", "数量差異（カストディ−当社）", "カストディ単価", "当社単価",
                "単価差異率", "カストディ評価額", "当社評価額", "評価額差異（カストディ−当社）",
                "カストディ価格ソース", "当社価格ソース", "分割比率（当社:カストディ）"]
        grid = "".join(f"<div><span>{_e(k)}</span><b>{_e(f[k])}</b></div>" for k in keys if k in f)
        ok = d["explain_status"] in (STATUS_AI_OK, STATUS_MOCK_OK)
        rej = ""
        if d["rejected_numbers"]:
            rej_text = _e(d["rejected_text"]).replace("\n", "<br>")
            rej = (f"<div class='rej'><b>AI の説明を差し戻しました。</b>計算結果にない数字・表現："
                   f"{_e('、'.join(d['rejected_numbers']))}<br><s>{rej_text}</s></div>")
        elif d["rejected_text"]:
            rej = f"<div class='rej'><b>AI の応答を使えませんでした。</b>{_e(d['rejected_text'])}</div>"
        cards.append(f"""
<div class="card">
 <div class="top"><span class="badge p-{_e(d['priority'])}">優先度 {_e(d['priority'])}</span>
  <span class="code">{_e(d['security_code'])}・{_e(d['asset_class_label'])}</span>
  <span class="name">{_e(d['security_name'])}</span>
  <span class="badge {'st-ok' if ok else 'st-fb'}">{_e(d['explain_status'])}</span></div>
 <div class="cat">{_e(d['category_label'])}<span class="note">　判定根拠：{_e(d['basis'])}</span></div>
 <div class="grid">{grid}</div>
 <div class="label">説明</div><p class="text">{_e(d['explanation'])}</p>
 <div class="label">対応案</div><p class="text">{_e(d['action'])}</p>
 {rej}
</div>""")

    if u.mode != "api":
        cost_text, price_note = "0 円（API を呼んでいません）", "API キーを設定すると、実際のトークン数と推定費用がここに入ります。"
    elif u.cost_usd is None:
        cost_text, price_note = "—", "このモデルの料金が未設定です（PRICE_INPUT_PER_MTOK / PRICE_OUTPUT_PER_MTOK で指定できます）。"
    else:
        cost_text = f"${u.cost_usd:.6f}（約 {u.cost_jpy:.3f} 円）"
        price_note = (f"入力 ${u.price_in}／100万トークン、出力 ${u.price_out}／100万トークン、"
                      f"1 USD = {u.usd_jpy:g} 円で換算")
    send_note = (f"差異 {len(items)} 件分だけを送信。一致した {s['matched']} 銘柄と、証券コード・銘柄名は送っていません"
                 if u.mode == "api" else
                 f"モックのため送信なし。API モードでも送るのは差異 {len(items)} 件分の数値だけで、証券コード・銘柄名は送りません")
    fallback_n = sum(1 for d in items if d["explain_status"] not in (STATUS_AI_OK, STATUS_MOCK_OK))
    usage = f"""
<table class="tbl">
<tr><th>実行モード</th><td>{mode_text}</td></tr>
<tr><th>AI 呼び出し回数</th><td>{u.calls} 回（{send_note}）</td></tr>
<tr><th>トークン数</th><td>入力 {u.input_tokens:,} ／ 出力 {u.output_tokens:,}</td></tr>
<tr><th>推定費用</th><td>{cost_text}<div class="note">{_e(price_note)}</div></td></tr>
<tr><th>数値検証</th><td>{len(items) - fallback_n} 件合格 ／ {fallback_n} 件はテンプレート説明に差し戻し</td></tr>
</table>"""

    tol_rows = "".join(
        f"<tr><td>{_e(ASSET_CLASS_LABELS[k])}</td><td>{_e(v['label'])}</td></tr>"
        for k, v in PRICE_TOLERANCES.items())
    rules = f"""
<table class="tbl"><thead><tr><th>資産区分</th><th>価格の許容誤差</th></tr></thead><tbody>{tol_rows}</tbody></table>
<p class="note">数量は完全一致で判定します。評価額は、株式＝数量×単価、国債＝額面×単価÷100 で計算しています。
差異の検出・原因の分類・すべての数字はプログラムが算出し、AI は説明文と対応案の作成だけを担当します。</p>"""

    html = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>残高照合レポート</title><style>{CSS}</style></head>
<body><div class="wrap">
<header><h1>カストディ残高照合レポート</h1>
<div class="meta">{_e(result['fund_name'])}　|　基準日 {_e(s['as_of_date'])}　|　作成 {_e(result['generated_at'])}</div>
<span class="mode">{mode_text}</span></header>
{kpis}
<h2>差異一覧</h2>{table}
<h2>差異の詳細と説明</h2>{''.join(cards)}
<h2>AI 利用状況</h2>{usage}
<h2>照合ルール</h2>{rules}
<footer>このレポートのデータはすべて架空です。実在の銘柄・ファンド・金融機関とは関係ありません。</footer>
</div></body></html>"""
    path.write_text(html, encoding="utf-8")
