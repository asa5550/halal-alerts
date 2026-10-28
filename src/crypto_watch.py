"""Fast crypto watcher, run every 15 minutes by GitHub Actions.

Alerts (each with a cooldown so you aren't spammed):
  * sharp move: |1h change| >= move_1h_pct          (coins you hold)
  * big day:    |24h change| >= move_24h_pct         (coins you hold)
  * dip zone:   a BUY/ACCUMULATE coin falls >= dip_from_30d_high_pct below its 30-day high
                (held or not), with the OMR left in this month's plan for it
  * 200-day trend cross                               (coins you hold or want)
Alerts go to Telegram instantly and are added to the RSS feed.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import feed  # noqa: E402
import notify  # noqa: E402
import portfolio  # noqa: E402
from advice import money, units  # noqa: E402
from prices import binance_klines  # noqa: E402
from run import load_json, make_item  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state" / "state.json"
CSTATE = ROOT / "state" / "crypto_state.json"


def main():
    cfg = load_json(ROOT / "config" / "settings.json", {})
    rules = cfg.get("crypto_alerts", {})
    watch = load_json(ROOT / "config" / "watchlist.json", {"instruments": []})
    cstate = load_json(CSTATE, {"cooldown": {}, "above200": {}})
    now = datetime.now(timezone.utc)
    cool = timedelta(hours=rules.get("cooldown_hours", 6))
    new = []
    masked_default = bool(cfg.get("privacy_mode"))
    positions = portfolio.load_positions()
    state0 = load_json(STATE, {})
    month = now.strftime("%Y-%m")
    plan = state0.get("plan", {}) if state0.get("plan", {}).get("month") == month else {"lines": []}
    spent = portfolio.bought_this_month(month)

    def fire(key, title, body_fn):
        """body_fn(masked) -> text; public feed gets masked text, Telegram the full one."""
        last = cstate["cooldown"].get(key)
        if last and now - datetime.fromisoformat(last) < cool:
            return
        cstate["cooldown"][key] = now.isoformat()
        it = make_item(title, body_fn(masked_default), "crypto", f"{key}:{now:%H%M}", "signals")
        it["private"] = body_fn(False)
        new.append(it)

    def holding(sym, inst, last, m):
        p = positions.get(sym)
        if not p:
            return "You don't hold it. "
        val = portfolio.to_omr(p["qty"] * last, "USDT")
        pnl = val / p["cost_omr"] - 1 if p["cost_omr"] else 0
        return f"You hold {units(p['qty'], inst, m)} (≈{money(val, m)}, {pnl:+.0%} vs cost). "

    def budget_left(sym):
        planned = sum(l["omr"] for l in plan["lines"] if l["symbol"] == sym)
        return planned, max(0.0, planned - spent.get(sym, 0.0))

    for inst in watch["instruments"]:
        if inst.get("domain") != "crypto_spot" or not inst.get("binance") or inst.get("view") == "AVOID":
            continue
        sym, pair = inst["symbol"], inst["binance"]
        hourly = binance_klines(pair, "1h", 25)
        daily = binance_klines(pair, "1d", 210)
        if not hourly or not daily:
            continue
        last = float(hourly[-1][4])
        c1h = last / float(hourly[-2][4]) - 1
        c24 = last / float(hourly[0][4]) - 1
        closes = [float(k[4]) for k in daily]
        hi30 = max(float(k[2]) for k in daily[-30:])
        sma200 = sum(closes[-200:]) / min(200, len(closes))
        px = f"{last:,.6g} USDT"

        held = sym in positions
        wanted = inst.get("view") in ("BUY", "ACCUMULATE")
        if held and abs(c1h) * 100 >= rules.get("move_1h_pct", 4):
            up = c1h > 0
            fire(f"1h:{sym}:{'up' if up else 'dn'}", f"{'🚀' if up else '📉'} {sym} {c1h:+.1%} in 1h",
                 lambda m, up=up, last=last, c24=c24, inst=inst, sym=sym, px=px: f"{sym} now {px}, 24h {c24:+.1%}. " + holding(sym, inst, last, m)
                 + ("ACTION: no action needed. Don't chase a spike; the monthly plan handles buying." if up else
                    "ACTION: no panic selling on a one-hour move. If it's on your ACCUMULATE list, watch for a dip-zone alert."))
        if held and abs(c24) * 100 >= rules.get("move_24h_pct", 8):
            up = c24 > 0
            fire(f"24h:{sym}:{'up' if up else 'dn'}", f"{'📈' if up else '📉'} {sym} {c24:+.1%} in 24h",
                 lambda m, last=last, inst=inst, sym=sym, px=px, hi30=hi30: f"{sym} now {px}, 30-day high {hi30:,.6g}. "
                 + holding(sym, inst, last, m) + "ACTION: check the daily signal tomorrow morning before you trade.")
        dd = last / hi30 - 1
        if inst.get("view") in ("BUY", "ACCUMULATE") and dd * 100 <= -rules.get("dip_from_30d_high_pct", 15):
            def dip_body(m, sym=sym, inst=inst, last=last, px=px, dd=dd, hi30=hi30):
                planned, left = budget_left(sym)
                pxo = portfolio.to_omr(last, "USDT")
                if left >= 1:
                    act = (f"ACTION: buy {money(left, m)} now (≈{units(left / pxo, inst, m)}). That's the rest of this "
                           f"month's {money(planned, m)} for {sym}, used at a discount.")
                elif planned:
                    act = "ACTION: this month's money for it is already used. Wait for next month's plan."
                else:
                    act = "ACTION: it's not in this month's plan. Consider it in next month's crypto share."
                return f"{sym} at {px}, {dd:.0%} under its 30-day high of {hi30:,.6g}. " + holding(sym, inst, last, m) + act
            fire(f"dip:{sym}", f"🟩 {sym} dip zone: {dd:.0%} from 30-day high", dip_body)
        above = last > sma200
        prev = cstate["above200"].get(sym)
        if prev is not None and above != prev and (held or wanted):
            fire(f"200d:{sym}:{above}", f"{'✅' if above else '⚠️'} {sym} crossed {'above' if above else 'below'} its 200-day average",
                 lambda m, above=above, last=last, inst=inst, sym=sym, px=px, sma200=sma200:
                 f"{sym} {px}; 200-day average {sma200:,.6g}. " + holding(sym, inst, last, m)
                 + ("ACTION: the long-term trend is repairing. Expect an upgrade in the daily signal." if above else
                    "ACTION: the long-term trend is weakening. If tomorrow's signal turns REDUCE, you'll get exact sell amounts."))
        cstate["above200"][sym] = above

    CSTATE.parent.mkdir(exist_ok=True)
    CSTATE.write_text(json.dumps(cstate, indent=1))
    if new:
        notify.push_items(new)
        for it in new:
            it.pop("private", None)
        state = load_json(STATE, {"last_signal": {}, "alert_keys": {}, "items": [], "plan_month": "", "digest_week": ""})
        state["items"] = (new + state["items"])[:100]
        STATE.write_text(json.dumps(state, indent=1))
        feed.write_rss(state["items"], cfg)
    print(f"crypto watch: {len(new)} alerts")


if __name__ == "__main__":
    main()
