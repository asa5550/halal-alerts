"""Data for the iPhone home-screen widget (Scriptable).

Writes widget.json with full, unmasked figures. It must only ever be written into your
PRIVATE halal-portfolio repo (the workflows pass WIDGET_OUT=private/widget.json), never docs/.

- build(): daily run, from all instruments' closes: totals, allocation vs target,
  holdings, 90-day portfolio value history, sparklines and this month's plan.
"""
from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import portfolio

HISTORY_DAYS = 90
SPARK_DAYS = 30


def out_path() -> Path | None:
    p = os.environ.get("WIDGET_OUT")
    if not p:
        return None
    path = Path(p)
    if "docs" in path.parts:  # public Pages folder: refuse
        raise ValueError("widget.json must not be written to docs/")
    return path if path.parent.exists() else None


def _rows() -> list[dict]:
    if not portfolio.TX.exists():
        return []
    rows = [r for r in csv.DictReader(portfolio.TX.open())
            if (r.get("symbol") or "").strip() and not (r.get("date") or "").lstrip().startswith("#")]
    return sorted(rows, key=lambda r: r["date"].strip())


def _history(rows: list[dict], closes: dict, ccys: dict, today: pd.Timestamp) -> list[dict]:
    """Rebuild daily portfolio value and cost from the trade log and daily closes."""
    if not rows:
        return []
    first = max(pd.Timestamp(rows[0]["date"].strip()), today - pd.Timedelta(days=HISTORY_DAYS - 1))
    ff = {s: c.sort_index().reindex(pd.date_range(c.index.min(), today)).ffill() for s, c in closes.items() if c is not None and len(c)}
    out, qty, cost, i = [], {}, {}, 0
    for day in pd.date_range(first - pd.Timedelta(days=0), today):
        # replay trades on or before this day (average-cost, like portfolio.load_positions)
        while i < len(rows) and pd.Timestamp(rows[i]["date"].strip()) <= day:
            r = rows[i]
            s, q, px = r["symbol"].strip().upper(), float(r["qty"]), float(r["price"])
            ccy = (r.get("currency") or "USD").strip().upper()
            if q >= 0:
                cost[s] = cost.get(s, 0) + portfolio.to_omr(q * px + float(r.get("fees") or 0), ccy)
            elif qty.get(s, 0) > 0:
                cost[s] = cost.get(s, 0) * max(0.0, 1 + q / qty[s])
            qty[s] = qty.get(s, 0) + q
            i += 1
        val = 0.0
        for s, q in qty.items():
            if q <= 1e-12:
                continue
            c = ff.get(s)
            px = c.get(day) if c is not None else None
            val += portfolio.to_omr(q * float(px), ccys.get(s, "USD")) if px is not None and pd.notna(px) else cost.get(s, 0)
        out.append({"d": day.strftime("%Y-%m-%d"), "v": round(val, 3),
                    "c": round(sum(v for s, v in cost.items() if qty.get(s, 0) > 1e-12), 3)})
    return out


def _spark(c: pd.Series | None) -> list[float]:
    if c is None or not len(c):
        return []
    return [round(float(x), 6) for x in c.dropna().iloc[-SPARK_DAYS:]]


def _chg(sp: list[float]) -> float | None:
    return round(sp[-1] / sp[0] - 1, 4) if len(sp) > 1 and sp[0] else None


def build(snap: dict, signals: list[dict], closes: dict, cfg: dict, plan: dict) -> None:
    path = out_path()
    if not path:
        return
    try:
        now = datetime.now(timezone.utc)
        today = pd.Timestamp(now.date())
        sig = {s["symbol"].upper(): s for s in signals}
        ccys = {s["symbol"].upper(): s.get("currency") or "USD" for s in signals}
        tot = snap["total_omr"]
        hist = _history(_rows(), closes, ccys, today)
        holdings = [{"symbol": r["symbol"], "domain": r["domain"], "qty": r["qty"], "value": round(r["value_omr"], 3),
                     "cost": round(r["cost_omr"], 3), "pnl_pct": round(r["pnl_pct"], 4), "weight": round(r["weight"], 4),
                     "signal": sig.get(r["symbol"], {}).get("signal"), "spark": _spark(closes.get(r["symbol"])),
                     "last": (sig.get(r["symbol"], {}).get("ind") or {}).get("last"), "ccy": ccys.get(r["symbol"], "USD")}
                    for r in snap["rows"]]
        held = {h["symbol"] for h in holdings}
        planned = [l["symbol"] for l in plan["lines"] if l["symbol"] != "—"]
        watch_syms = list(dict.fromkeys([*planned, "SPUS", "UMMA", "GOLD"]))
        watch = []
        for s in watch_syms:
            if s in held or s not in sig:
                continue
            sp = _spark(closes.get(s))
            watch.append({"symbol": s, "signal": sig[s]["signal"], "last": sp[-1] if sp else None,
                          "ccy": ccys.get(s, "USD"), "chg": _chg(sp), "spark": sp})
        counts: dict = {}
        for s in signals:
            if s.get("type") != "reference":
                counts[s["signal"]] = counts.get(s["signal"], 0) + 1
        data = {
            "updated": now.isoformat(timespec="seconds"),
            "total": round(tot, 3), "cost": round(snap["cost_omr"], 3), "pnl": round(tot - snap["cost_omr"], 3),
            "pnl_pct": round((tot / snap["cost_omr"] - 1) if snap["cost_omr"] else 0, 4),
            "history": hist,
            "domains": [{"key": d, "label": cfg["labels"].get(d, d), "value": round(snap["by_domain"].get(d, 0), 3),
                         "pct": round(snap["by_domain"].get(d, 0) / tot * 100, 1) if tot else 0, "target": t}
                        for d, t in cfg["targets_pct"].items()],
            "holdings": holdings,
            "watch": watch,
            "plan": {"month": now.strftime("%B"), "budget": plan["budget"],
                     "lines": [{"symbol": l["symbol"], "domain": cfg["labels"].get(l["domain"], l["domain"]),
                                "omr": l["omr"], "note": l["note"]} for l in plan["lines"]]},
            "signals": counts,
        }
        path.write_text(json.dumps(data, indent=1, default=float))
        print(f"[widget] wrote {path}")
    except Exception as e:  # noqa: BLE001 - the widget must never break alerts
        print(f"[widget] {e}")

