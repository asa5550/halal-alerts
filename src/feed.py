"""RSS 2.0 feed + a small HTML dashboard, written to docs/ for GitHub Pages."""
from __future__ import annotations

import html
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
ICON = {"BUY": "🟢", "ACCUMULATE": "🟩", "HOLD": "⚪", "REDUCE": "🟧", "SELL": "🔴", "AVOID": "⛔",
        "warn": "⚠️", "alert": "🚨", "plan": "📅", "digest": "🗞️"}


def write_rss(items: list[dict], cfg: dict) -> Path:
    now = format_datetime(datetime.now(timezone.utc))
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>',
        f"<title>{escape(cfg['feed_title'])}</title>",
        f"<link>{escape(cfg['site_url'])}</link>",
        f'<atom:link href="{escape(cfg["site_url"].rstrip("/"))}/feed.xml" rel="self" type="application/rss+xml"/>',
        "<description>Halal investing alerts: US halal equities, spot crypto, Sharia commodities, MSX. "
        "Long-only signals. Not financial advice.</description>",
        f"<lastBuildDate>{now}</lastBuildDate><ttl>60</ttl>",
    ]
    for it in items[:60]:
        parts.append(
            "<item>"
            f"<title>{escape(it['title'])}</title>"
            f"<link>{escape(cfg['site_url'])}#{escape(it.get('anchor', ''))}</link>"
            f'<guid isPermaLink="false">{escape(it["guid"])}</guid>'
            f"<pubDate>{it['pubDate']}</pubDate>"
            f"<category>{escape(it.get('category', 'signal'))}</category>"
            f"<description>{escape(it['body'])}</description>"
            "</item>"
        )
    parts.append("</channel></rss>")
    DOCS.mkdir(exist_ok=True)
    out = DOCS / "feed.xml"
    out.write_text("\n".join(parts), encoding="utf-8")
    return out


PRIVATE = False  # set from settings.privacy_mode by run.py


def fmt(x, nd=2):
    return "—" if x is None else f"{x:,.{nd}f}"


def money(x):
    """OMR amounts are masked in privacy mode (public repo / public Pages site)."""
    return "•••" if PRIVATE else fmt(x)


def write_dashboard(signals: list[dict], snap: dict, plan: dict, cfg: dict, items: list[dict]) -> Path:
    e = html.escape
    labels = cfg["labels"]
    sig_rows = "".join(
        f"<tr><td>{e(labels.get(s['domain'], s['domain']))}</td><td><b>{e(s['symbol'])}</b><br><small>{e(s.get('name',''))}</small></td>"
        f"<td class='sig {s['signal']}'>{ICON.get(s['signal'],'')} {s['signal']}</td>"
        f"<td>{e(s.get('tech_signal') or '—')} / {e(s.get('research_view') or '—')}</td>"
        f"<td>{fmt(s['ind']['last']) if s.get('ind') else '—'}</td>"
        f"<td>{fmt(s['ind']['rsi14'],0) if s.get('ind') else '—'}</td>"
        f"<td><small>{e('; '.join(s.get('reasons', [])))}</small></td></tr>"
        for s in signals)
    pf_rows = "".join(
        f"<tr><td>{e(r['symbol'])}</td><td>{e(labels.get(r['domain'], r['domain']))}</td><td>{'•••' if PRIVATE else f"{r['qty']:g}"}</td>"
        f"<td>{money(r['cost_omr'])}</td><td>{money(r['value_omr'])}{'' if r['priced'] else '*'}</td>"
        f"<td class='{'pos' if r['pnl_omr']>=0 else 'neg'}'>{money(r['pnl_omr'])} ({r['pnl_pct']:.1%})</td><td>{r['weight']:.0%}</td></tr>"
        for r in snap["rows"]) or "<tr><td colspan=7>No holdings yet. Add rows to portfolio/transactions.csv.</td></tr>"
    tot = snap["total_omr"] or 0
    dom_rows = "".join(
        f"<tr><td>{e(labels.get(d, d))}</td><td>{money(snap['by_domain'].get(d, 0))}</td>"
        f"<td>{(snap['by_domain'].get(d, 0) / tot * 100 if tot else 0):.1f}%</td><td>{t}%</td></tr>"
        for d, t in cfg["targets_pct"].items())
    plan_rows = "".join(
        f"<tr><td>{e(labels.get(l['domain'], l['domain']))}</td><td>{e(l['symbol'])}</td><td>{fmt(l['omr'])}</td><td>{e(l['note'])}</td></tr>"
        for l in plan["lines"])
    feed_rows = "".join(f"<li id='{e(i.get('anchor',''))}'><b>{e(i['title'])}</b><br><small>{e(i['pubDate'])}</small><p>{e(i['body'])}</p></li>"
                        for i in items[:20])
    pnl = tot - snap["cost_omr"]
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(cfg['feed_title'])}</title>
<link rel="alternate" type="application/rss+xml" title="{e(cfg['feed_title'])}" href="feed.xml">
<style>
body{{font:15px -apple-system,system-ui,sans-serif;margin:0;padding:16px;background:#f6f7f9;color:#1d2433}}
h1{{font-size:20px}} h2{{font-size:16px;margin-top:28px}} .card{{background:#fff;border-radius:12px;padding:12px;overflow-x:auto;box-shadow:0 1px 2px #0001}}
table{{border-collapse:collapse;width:100%}} td,th{{padding:6px 8px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}}
.sig{{font-weight:600;white-space:nowrap}} .BUY,.pos{{color:#137333}} .ACCUMULATE{{color:#2e7d32}} .REDUCE{{color:#c25e00}} .SELL,.neg{{color:#c5221f}} .AVOID{{color:#555}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap}} .kpi div{{background:#fff;border-radius:12px;padding:10px 14px;box-shadow:0 1px 2px #0001}} .kpi b{{display:block;font-size:20px}}
ul{{padding-left:18px}} small{{color:#667}}
</style></head><body>
<h1>{e(cfg['feed_title'])}</h1><small>Updated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · <a href="feed.xml">RSS feed</a> · Long-only, Sharia-screened. Not financial advice.</small>
<h2>Portfolio</h2><div class="kpi"><div>Value<b>{money(tot)} OMR</b></div><div>Invested<b>{money(snap['cost_omr'])} OMR</b></div>
<div>P&amp;L<b class="{'pos' if pnl>=0 else 'neg'}">{money(pnl)} OMR</b></div></div>
<div class="card" style="margin-top:12px"><table><tr><th>Domain</th><th>Value OMR</th><th>Weight</th><th>Target</th></tr>{dom_rows}</table></div>
<div class="card" style="margin-top:12px"><table><tr><th>Symbol</th><th>Domain</th><th>Qty</th><th>Cost</th><th>Value</th><th>P&amp;L</th><th>Wt</th></tr>{pf_rows}</table><small>* no live price, shown at cost</small></div>
<h2>This month's {fmt(plan['budget'],0)} OMR plan</h2><div class="card"><table><tr><th>Domain</th><th>Buy</th><th>OMR</th><th>Why</th></tr>{plan_rows}</table></div>
<h2>Signals</h2><div class="card"><table><tr><th>Domain</th><th>Instrument</th><th>Signal</th><th>Tech / Research</th><th>Last</th><th>RSI</th><th>Reasons</th></tr>{sig_rows}</table></div>
<h2>Recent alerts</h2><div class="card"><ul>{feed_rows}</ul></div>
</body></html>"""
    out = DOCS / "index.html"
    out.write_text(page, encoding="utf-8")
    return out
