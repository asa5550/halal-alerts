"""Rules-based technical signals, blended with the research desk's view.

Signals are long-only by design: BUY, ACCUMULATE, HOLD, REDUCE, SELL, AVOID.
There is no SHORT signal because short selling (selling what you don't own) and
leveraged/derivative exposure are not Sharia-compliant.
"""
from __future__ import annotations

import pandas as pd

LADDER = ["SELL", "REDUCE", "HOLD", "ACCUMULATE", "BUY"]


def rsi(closes: pd.Series, n: int = 14) -> float:
    d = closes.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, 1e-12)
    return float(100 - 100 / (1 + rs.iloc[-1]))


def indicators(c: pd.Series) -> dict:
    c = c.dropna()
    last = float(c.iloc[-1])
    n = len(c)
    sma50 = float(c.tail(50).mean()) if n >= 50 else None
    sma200 = float(c.tail(200).mean()) if n >= 200 else None
    mom3m = float(last / c.iloc[-63] - 1) if n >= 63 else None
    high52 = float(c.tail(252).max())
    return {
        "last": last,
        "date": c.index[-1].strftime("%Y-%m-%d"),
        "sma50": sma50,
        "sma200": sma200,
        "rsi14": rsi(c) if n >= 20 else None,
        "mom3m": mom3m,
        "drawdown": last / high52 - 1,
        "chg1d": float(last / c.iloc[-2] - 1) if n >= 2 else 0.0,
        "points": n,
    }


def technical_signal(ind: dict) -> tuple[str, list[str]]:
    """Score trend + momentum + mean-reversion. Returns (signal, reasons)."""
    score, why = 0, []
    last, s50, s200, r, m = ind["last"], ind["sma50"], ind["sma200"], ind["rsi14"], ind["mom3m"]
    if s50 and s200:
        if last > s200 and s50 > s200:
            score += 2; why.append("uptrend (price & 50d above 200d)")
        elif last < s200 and s50 < s200:
            score -= 2; why.append("downtrend (price & 50d below 200d)")
        else:
            why.append("trend mixed around 200d")
    elif s50:
        score += 1 if last > s50 else -1
        why.append(f"price {'above' if last > s50 else 'below'} 50d (short history)")
    if r is not None:
        if r < 30:
            score += 1; why.append(f"RSI {r:.0f} oversold")
        elif r > 75:
            score -= 1; why.append(f"RSI {r:.0f} overbought")
    if m is not None:
        if m > 0.10:
            score += 1; why.append(f"3m momentum +{m:.0%}")
        elif m < -0.15:
            score -= 1; why.append(f"3m momentum {m:.0%}")
    if score >= 3:
        sig = "BUY"
    elif score == 2:
        sig = "ACCUMULATE"
    elif score <= -3:
        sig = "SELL"
    elif score == -2:
        sig = "REDUCE"
    else:
        sig = "HOLD"
    return sig, why


def blend(tech: str, research: str | None) -> str:
    """Research AVOID always wins (compliance or thesis broken). Otherwise average the
    two positions on the ladder, rounding toward caution."""
    research = (research or "HOLD").upper()
    if research == "AVOID":
        return "AVOID"
    if research not in LADDER:
        return tech
    a, b = LADDER.index(tech), LADDER.index(research)
    return LADDER[(a + b) // 2]


def evaluate(inst: dict, closes: pd.Series | None) -> dict:
    out = {**inst, "research_view": inst.get("view")}
    if closes is None or len(closes) < 5:
        ind = None
        if closes is not None and len(closes):
            ind = {"last": float(closes.iloc[-1]), "date": closes.index[-1].strftime("%Y-%m-%d"), "sma50": None,
                   "sma200": None, "rsi14": None, "mom3m": None, "drawdown": None, "chg1d": None, "points": len(closes)}
        rv = (inst.get("view") or "HOLD").upper()
        out.update(signal=rv if rv in LADDER + ["AVOID"] else "HOLD", tech_signal=None,
                   reasons=["not enough price history - research view only"], ind=ind)
        return out
    ind = indicators(closes)
    tech, why = technical_signal(ind)
    out.update(signal=blend(tech, inst.get("view")), tech_signal=tech, reasons=why, ind=ind)
    return out
