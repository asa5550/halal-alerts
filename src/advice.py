"""Turns signals + your holdings into concrete actions.

Every builder takes masked=True/False: masked text goes to the public RSS/dashboard
(no amounts or units), unmasked text goes to your private Telegram.
"""
from __future__ import annotations

import math

from portfolio import to_omr


def money(x: float, masked: bool) -> str:
    return "•••" if masked else f"{x:,.2f} OMR"


def units(q: float, inst: dict, masked: bool) -> str:
    if masked:
        return "•••"
    if inst.get("domain") == "msx":
        return f"{int(math.floor(q)):,} shares"
    if inst.get("domain") == "crypto_spot":
        return f"{q:.6g} {inst['symbol']}"
    return f"{q:.4g} units"


def round_units(q: float, inst: dict) -> float:
    return math.floor(q) if inst.get("domain") == "msx" else q


class Book:
    """Everything the advice needs: positions, prices, plan, settings."""

    def __init__(self, snap, cfg, plan, signals, last_prices):
        self.snap, self.cfg, self.plan = snap, cfg, plan
        self.pos = {r["symbol"]: r for r in snap["rows"]}
        self.sig = {s["symbol"].upper(): s for s in signals}
        self.px = last_prices  # symbol -> (price, ccy)
        self.total = snap["total_omr"]

    def px_omr(self, sym):
        p = self.px.get(sym.upper())
        return to_omr(p[0], p[1]) if p else None

    def plan_amt(self, sym):
        return sum(l["omr"] for l in self.plan["lines"] if l["symbol"] == sym)

    def holding_line(self, sym, masked):
        r = self.pos.get(sym.upper())
        if not r:
            return ""
        inst = self.sig.get(sym.upper(), {"symbol": sym, "domain": r["domain"]})
        return (f"You hold {units(r['qty'], inst, masked)} ({money(r['value_omr'], masked)}, "
                f"{r['pnl_pct']:+.0%} vs cost, {r['weight']:.0%} of portfolio). ")


def signal_action(s: dict, book: Book, masked: bool) -> str | None:
    """Action for a signal change. None = not relevant to you (e.g. SELL on something you don't own)."""
    sym, sig = s["symbol"].upper(), s["signal"]
    r = book.pos.get(sym)
    plan = book.plan_amt(sym)
    pxo = book.px_omr(sym)
    if r:
        head = book.holding_line(sym, masked)
        if sig == "AVOID":
            return head + (f"ACTION: exit fully, sell {units(r['qty'], s, masked)} (≈{money(r['value_omr'], masked)}). "
                           "It no longer passes the screen or its case is broken. Give any impermissible gain to charity (purification).")
        if sig == "SELL":
            return head + f"ACTION: sell all {units(r['qty'], s, masked)} (≈{money(r['value_omr'], masked)}). The downtrend and weak momentum both confirm it."
        if sig == "REDUCE":
            q = round_units(r["qty"] / 2, s)
            return head + (f"ACTION: sell about half, {units(q, s, masked)} (≈{money(r['value_omr'] / 2, masked)}). "
                           "Keep the rest in case the trend recovers.")
        if sig == "HOLD":
            return head + "ACTION: keep it and put no new money in for now."
        if plan > 0:
            return head + f"ACTION: add {money(plan, masked)} from this month's plan."
        return head + "ACTION: keep it. It's in line for new money when its part of the portfolio is underweight."
    # not held
    if sig in ("BUY", "ACCUMULATE"):
        if plan > 0:
            est = f" (≈{units(round_units(plan / pxo, s), s, masked)})" if pxo else ""
            return f"You don't hold it. ACTION: buy {money(plan, masked)}{est} from this month's plan."
        return "You don't hold it. It's a candidate for next month's plan."
    return None  # HOLD/REDUCE/SELL/AVOID on something you don't own: nothing to do


def portfolio_alerts(book: Book, masked: bool) -> list[dict]:
    cfg, snap, total = book.cfg, book.snap, book.total
    out = []
    if total <= 0:
        return out
    labels = cfg["labels"]
    tp = cfg.get("take_profit_pct", 30) / 100
    maxp = cfg["max_position_pct"] / 100
    dom_w = {d: snap["by_domain"].get(d, 0) / total for d in cfg["targets_pct"]}
    dom_over = {d: dom_w[d] * 100 - t >= cfg["drift_alert_pp"] for d, t in cfg["targets_pct"].items()}

    # domain drift: say where new money goes
    for d, t in cfg["targets_pct"].items():
        w = dom_w[d] * 100
        if abs(w - t) < cfg["drift_alert_pp"]:
            continue
        side = "over" if w > t else "under"
        amt = sum(l["omr"] for l in book.plan["lines"] if l["domain"] == d)
        act = (f"ACTION: no sale needed. This month's plan puts {money(amt, masked)} here to close the gap."
               if side == "under" else
               "ACTION: no new money goes here this month. Selling is suggested only for holdings in it that are up a lot (see any 💰 take-profit alert).")
        out.append({"key": f"drift:{d}:{side}", "level": "warn",
                    "title": f"{labels.get(d, d)} {side}weight: {w:.0f}% vs {t}% target", "body": act})

    for r in snap["rows"]:
        sym = r["symbol"]
        s = book.sig.get(sym, {"symbol": sym, "domain": r["domain"], "signal": "HOLD"})
        head = book.holding_line(sym, masked)
        pxo = book.px_omr(sym)
        over_pos = r["weight"] > maxp
        # take profit: big gain AND (position over its cap OR its domain overweight)
        if r["priced"] and r["pnl_pct"] >= tp and (over_pos or dom_over.get(r["domain"])):
            excess_pos = r["value_omr"] - maxp * total if over_pos else 0
            d = r["domain"]
            excess_dom = (snap["by_domain"][d] - cfg["targets_pct"][d] / 100 * total) if dom_over.get(d) else 0
            trim = min(max(excess_pos, excess_dom), r["value_omr"] * 0.5)
            q = round_units(trim / pxo, s) if pxo else 0
            out.append({"key": f"tp:{sym}", "level": "warn", "title": f"💰 Take profit: {sym} {r['pnl_pct']:+.0%}",
                        "body": head + f"ACTION: sell {units(q, s, masked)} (≈{money(trim, masked)}) to get back to your target "
                                       "and lock in part of the gain. Put the proceeds into next month's plan."})
        elif over_pos:
            out.append({"key": f"conc:{sym}", "level": "warn", "title": f"{sym} is {r['weight']:.0%} of your portfolio",
                        "body": head + f"ACTION: no sale (gain under {tp:.0%}). New money goes elsewhere until it's back under {maxp:.0%}."})
        if r["priced"] and r["pnl_pct"] * 100 <= cfg["loss_alert_pct"]:
            sig = s.get("signal", "HOLD")
            if sig in ("BUY", "ACCUMULATE"):
                plan = book.plan_amt(sym)
                act = (f"Signal is still {sig}. ACTION: average down with this month's {money(plan, masked)}."
                       if plan else f"Signal is still {sig}. ACTION: keep it. You can average down when the plan funds it.")
            elif sig == "HOLD":
                act = "Signal is HOLD. ACTION: keep it, but don't add money until the trend improves."
            else:
                act = (f"Signal is {sig}: the trend and the case for owning it are both broken. ACTION: suggest exiting, sell "
                       f"{units(r['qty'], s, masked)} (≈{money(r['value_omr'], masked)}) and accept the loss "
                       f"of {money(-r['pnl_omr'], masked)} rather than letting it grow.")
            out.append({"key": f"loss:{sym}", "level": "alert", "title": f"🚨 {sym} {r['pnl_pct']:+.0%} vs your cost",
                        "body": head + act})
    return out


def plan_text(book: Book, masked: bool) -> str:
    labels = book.cfg["labels"]
    parts = []
    for l in book.plan["lines"]:
        inst = book.sig.get(l["symbol"].upper(), {"symbol": l["symbol"], "domain": l["domain"]})
        pxo = book.px_omr(l["symbol"]) if l["symbol"] != "—" else None
        est = f" ≈ {units(round_units(l['omr'] / pxo, inst), inst, masked)}" if pxo else ""
        held = " (adding to holding)" if l["symbol"].upper() in book.pos else (" (new)" if l["symbol"] != "—" else "")
        parts.append(f"{labels.get(l['domain'], l['domain'])}: {l['symbol']} {money(l['omr'], masked)}{est}{held}, {l['note']}")
    return " | ".join(parts)
