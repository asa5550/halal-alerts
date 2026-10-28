"""Portfolio monitor across all four domains.

Reads portfolio/transactions.csv (one row per buy/sell), values everything in OMR,
and raises alerts for drift, concentration and drawdown versus cost.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TX = ROOT / "portfolio" / "transactions.csv"

# OMR is pegged: 1 OMR = 2.6008 USD. USDT treated as USD.
FX_TO_OMR = {"OMR": 1.0, "USD": 0.3845, "USDT": 0.3845, "USDC": 0.3845, "SAR": 0.10253, "AED": 0.10469}


def to_omr(amount: float, ccy: str) -> float:
    return amount * FX_TO_OMR.get(ccy.upper(), 0.3845)


def load_positions() -> dict:
    pos: dict = defaultdict(lambda: {"qty": 0.0, "cost_omr": 0.0, "domain": "", "currency": "USD"})
    if not TX.exists():
        return {}
    for r in csv.DictReader(TX.open()):
        if (r.get("date") or "").lstrip().startswith("#") or not (r.get("symbol") or "").strip():
            continue
        sym = r["symbol"].strip().upper()
        qty, px = float(r["qty"]), float(r["price"])
        fee = float(r.get("fees") or 0)
        ccy = (r.get("currency") or "USD").strip().upper()
        p = pos[sym]
        p["domain"], p["currency"] = r["domain"].strip(), ccy
        if qty >= 0:
            p["cost_omr"] += to_omr(qty * px + fee, ccy)
            p["qty"] += qty
        else:  # sell: reduce cost basis proportionally (average cost)
            if p["qty"] > 0:
                p["cost_omr"] *= max(0.0, 1 + qty / p["qty"])
            p["qty"] += qty
    return {k: v for k, v in pos.items() if v["qty"] > 1e-12}


def value(positions: dict, last_prices: dict) -> dict:
    """last_prices: symbol -> (price, currency). Falls back to cost if unknown."""
    rows, by_domain = [], defaultdict(float)
    for sym, p in positions.items():
        lp = last_prices.get(sym)
        if lp:
            mv = to_omr(p["qty"] * lp[0], lp[1] or p["currency"])
            priced = True
        else:
            mv, priced = p["cost_omr"], False
        pnl = mv - p["cost_omr"]
        rows.append({"symbol": sym, "domain": p["domain"], "qty": p["qty"], "cost_omr": p["cost_omr"],
                     "value_omr": mv, "pnl_omr": pnl,
                     "pnl_pct": pnl / p["cost_omr"] if p["cost_omr"] else 0.0, "priced": priced})
        by_domain[p["domain"]] += mv
    total = sum(r["value_omr"] for r in rows)
    for r in rows:
        r["weight"] = r["value_omr"] / total if total else 0
    rows.sort(key=lambda r: -r["value_omr"])
    return {"rows": rows, "total_omr": total, "cost_omr": sum(r["cost_omr"] for r in rows),
            "by_domain": dict(by_domain)}


def alerts(snapshot: dict, cfg: dict) -> list[dict]:
    out = []
    total = snapshot["total_omr"]
    if total <= 0:
        return out
    targets = cfg["targets_pct"]
    for dom, tgt in targets.items():
        w = snapshot["by_domain"].get(dom, 0) / total * 100
        if abs(w - tgt) >= cfg["drift_alert_pp"]:
            side = "over" if w > tgt else "under"
            out.append({"key": f"drift:{dom}:{side}", "level": "warn",
                        "title": f"Allocation drift: {cfg['labels'].get(dom, dom)} {side}weight",
                        "body": f"{w:.1f}% of portfolio vs target {tgt}%. "
                                f"Next monthly plan will steer new money to rebalance (no forced selling)."})
    for r in snapshot["rows"]:
        if r["weight"] * 100 >= cfg["max_position_pct"]:
            out.append({"key": f"conc:{r['symbol']}", "level": "warn",
                        "title": f"Concentration: {r['symbol']} is {r['weight']:.0%} of portfolio",
                        "body": f"Above your {cfg['max_position_pct']}% single-position limit."})
        if r["priced"] and r["pnl_pct"] * 100 <= cfg["loss_alert_pct"]:
            out.append({"key": f"loss:{r['symbol']}", "level": "alert",
                        "title": f"Drawdown: {r['symbol']} {r['pnl_pct']:.0%} vs your cost",
                        "body": ("" if cfg.get("privacy_mode") else f"Value {r['value_omr']:.2f} OMR vs cost {r['cost_omr']:.2f} OMR. ")
                                + f"Review the thesis; check the latest signal before averaging down."})
    return out


def monthly_plan(snapshot: dict, signals: list[dict], cfg: dict) -> dict:
    """Split the monthly budget: first by domain (filling underweight domains), then
    across BUY/ACCUMULATE instruments in each domain. Long-only, no selling."""
    budget = cfg["monthly_budget_omr"]
    targets = cfg["targets_pct"]
    total_after = snapshot["total_omr"] + budget
    gaps = {d: max(0.0, total_after * t / 100 - snapshot["by_domain"].get(d, 0)) for d, t in targets.items() if t > 0}
    gap_sum = sum(gaps.values())
    dom_amt = {d: budget * (g / gap_sum if gap_sum else targets[d] / 100) for d, g in gaps.items()}
    # broker minimums/fees make tiny tickets wasteful: fold sub-minimum domains into the rest
    min_t = cfg.get("min_ticket_omr", 5)
    small = {d: a for d, a in dom_amt.items() if a < min_t}
    big = {d: a for d, a in dom_amt.items() if a >= min_t}
    if small and big:
        extra, bsum = sum(small.values()), sum(big.values())
        dom_amt = {d: a + extra * a / bsum for d, a in big.items()}

    lines, parked = [], 0.0
    for dom, amt in dom_amt.items():
        if amt < 0.5:
            continue
        cands = [s for s in signals if s["domain"] == dom and s["signal"] in ("BUY", "ACCUMULATE")
                 and s.get("type") != "reference"]
        if not cands:
            parked += amt
            lines.append({"domain": dom, "symbol": "—", "omr": round(amt, 2),
                          "note": "No BUY/ACCUMULATE signal: keep as cash, re-check next month"})
            continue
        wts = {c["symbol"]: (2 if c["signal"] == "BUY" else 1) for c in cands}
        # keep tickets meaningful: max 2 instruments per domain per month
        top = sorted(cands, key=lambda c: -wts[c["symbol"]])[:2]
        wsum = sum(wts[c["symbol"]] for c in top)
        for c in top:
            lines.append({"domain": dom, "symbol": c["symbol"], "omr": round(amt * wts[c["symbol"]] / wsum, 2),
                          "note": c["signal"]})
    return {"budget": budget, "lines": lines, "parked": round(parked, 2)}


def bought_this_month(month: str) -> dict:
    """symbol -> OMR spent on buys in the given YYYY-MM (from your trade log)."""
    out: dict = defaultdict(float)
    if not TX.exists():
        return out
    for r in csv.DictReader(TX.open()):
        if (r.get("date") or "").startswith(month) and float(r.get("qty") or 0) > 0:
            out[r["symbol"].strip().upper()] += to_omr(float(r["qty"]) * float(r["price"]) + float(r.get("fees") or 0),
                                                       (r.get("currency") or "USD").strip())
    return out
