"""RSS 2.0 feed + a small HTML dashboard, written to docs/ for GitHub Pages."""
from __future__ import annotations

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
        "<description>Halal investing alerts: US halal equities, Sharia commodities, MSX. "
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
