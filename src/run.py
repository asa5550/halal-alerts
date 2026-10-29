"""Daily run: fetch prices -> signals -> portfolio monitor -> RSS items -> docs/."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import feed  # noqa: E402
import advice  # noqa: E402
import notify  # noqa: E402
import prices  # noqa: E402
import portfolio  # noqa: E402
import widget  # noqa: E402
from prices import get_closes  # noqa: E402
from signals import evaluate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "state.json"


def load_json(p: Path, default):
    return json.loads(p.read_text()) if p.exists() else default


def make_item(title, body, category, key, anchor=""):
    now = datetime.now(timezone.utc)
    guid = hashlib.sha1(f"{key}|{now:%Y-%m-%d}".encode()).hexdigest()
    return {"title": title, "body": body, "category": category, "guid": guid,
            "pubDate": format_datetime(now), "anchor": anchor}


def main():
    cfg = load_json(ROOT / "config" / "settings.json", {})
    watch = load_json(ROOT / "config" / "watchlist.json", {"instruments": []})
    state = load_json(STATE, {"last_signal": {}, "alert_keys": {}, "items": [], "plan_month": "", "digest_week": ""})
    now = datetime.now(timezone.utc)
    labels = cfg["labels"]
    feed.PRIVATE = bool(cfg.get("privacy_mode"))
    new_items = []

    # 1) evaluate everything first: actions depend on holdings, holdings depend on prices
    signals, last_prices, closes = [], {}, {}
    for inst in watch["instruments"]:
        closes[inst["symbol"].upper()] = c = get_closes(inst)
        res = evaluate(inst, c)
        signals.append(res)
        if res.get("ind"):
            ccy = inst.get("currency") or ("USDT" if inst.get("binance") else "USD")
            last_prices[inst["symbol"].upper()] = (res["ind"]["last"], ccy)

    snap = portfolio.value(portfolio.load_positions(), last_prices)
    plan = portfolio.monthly_plan(snap, signals, cfg)
    book = advice.Book(snap, cfg, plan, signals, last_prices)
    masked = feed.PRIVATE
    state["plan"] = {"month": now.strftime("%Y-%m"), "lines": plan["lines"]}  # used by the crypto watcher

    def add(title, pub, priv, category, key, anchor=""):
        it = make_item(title, pub, category, key, anchor)
        it["private"] = priv
        new_items.append(it)

    # 2) signal changes, only the ones that mean something for what you hold or will buy
    for res in signals:
        sym = res["symbol"]
        prev = state["last_signal"].get(sym)
        if res.get("type") == "reference" or prev == res["signal"]:
            continue
        state["last_signal"][sym] = res["signal"]
        act_pub = advice.signal_action(res, book, True)
        if act_pub is None:  # e.g. SELL on something you don't own
            continue
        act_priv = advice.signal_action(res, book, False)
        px = f" @ {res['ind']['last']:,.4g}" if res.get("ind") else ""
        was = f" (was {prev})" if prev else ""
        why = (f" Why: technical {res.get('tech_signal') or 'n/a'}, research {res.get('research_view') or 'n/a'}; "
               f"{'; '.join(res['reasons'])}. {res.get('rationale', '')} Compliance: {res.get('compliance_note', 'n/a')}")
        ctx = f"{labels.get(res['domain'], res['domain'])} · {res.get('name', '')}{px}. "
        add(f"{feed.ICON.get(res['signal'], '')} {res['signal']} {sym}{was}",
            ctx + (act_pub if masked else act_priv) + why, ctx + act_priv + why,
            "signal", f"sig:{sym}:{res['signal']}", "signals")

    if prices.FETCH_FAILURES and state.get("msx_fail_day") != now.strftime("%Y-%m-%d"):
        state["msx_fail_day"] = now.strftime("%Y-%m-%d")
        txt = ("Couldn't read today's price for: " + ", ".join(prices.FETCH_FAILURES)
               + ". Signals for these use the last stored price. Add today's close to "
                 "manual_prices.csv in your private portfolio repo, or ask Claude to fix the parser.")
        add("🛠️ MSX price fetch failed", txt, txt, "system", "msxfail")

    # 3) portfolio alerts with actions (each at most once a week)
    week = now.strftime("%G-W%V")
    priv_alerts = {a["key"]: a for a in advice.portfolio_alerts(book, False)}
    for a in advice.portfolio_alerts(book, True):
        if state["alert_keys"].get(a["key"]) == week:
            continue
        state["alert_keys"][a["key"]] = week
        title = a["title"] if a["title"][:1] in "💰🚨" else f"{feed.ICON[a['level']]} {a['title']}"
        add(title, a["body"] if masked else priv_alerts[a["key"]]["body"], priv_alerts[a["key"]]["body"],
            "portfolio", a["key"], "portfolio")

    # 4) monthly contribution plan
    month = now.strftime("%Y-%m")
    if state["plan_month"] != month and now.day >= cfg.get("plan_day", 1):
        state["plan_month"] = month
        add(f"{feed.ICON['plan']} {now:%B} plan: deploy {plan['budget']:.0f} OMR",
            advice.plan_text(book, masked), advice.plan_text(book, False), "plan", f"plan:{month}", "plan")

    # 5) weekly digest (Sunday, start of the MSX week): one line per holding
    if now.weekday() == 6 and state["digest_week"] != week:
        state["digest_week"] = week
        pnl = snap["total_omr"] - snap["cost_omr"]

        def digest(m):
            pv = f"{snap['total_omr']:.2f} OMR, P&L {pnl:+.2f} OMR" if not m else (
                f"P&L {pnl / snap['cost_omr']:+.1%}" if snap["cost_omr"] else "no holdings")
            lines = [f"{r['symbol']} {r['pnl_pct']:+.0%} → {book.sig.get(r['symbol'], {}).get('signal', 'HOLD')}"
                     for r in snap["rows"]]
            buys = ", ".join(s["symbol"] for s in signals if s["signal"] == "BUY") or "none"
            return f"Portfolio {pv}. Holdings: {'; '.join(lines) or 'none'}. BUY signals: {buys}."
        add(f"{feed.ICON['digest']} Weekly digest {week}", digest(masked), digest(False), "digest", f"digest:{week}")

    notify.push_items(new_items)  # Telegram gets the private (full) text
    for it in new_items:
        it.pop("private", None)   # state/feed are public: never store private text
    state["items"] = (new_items + state["items"])[:100]
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1))
    feed.write_rss(state["items"], cfg)
    widget.build(snap, signals, closes, cfg, plan)  # private repo only (WIDGET_OUT)
    print(f"{len(signals)} instruments, {len(new_items)} new feed items, portfolio {snap['total_omr']:.2f} OMR")


if __name__ == "__main__":
    main()
