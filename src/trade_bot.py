"""Log trades by messaging your Telegram bot.

Runs inside the crypto-watch job (every ~15 min). Reads new messages from YOUR chat only,
appends trades to the private repo's transactions.csv, and replies with a confirmation.

Message formats (case-insensitive, fee optional, date optional - defaults to today):
  bought 100 OQGN at 0.217 fee 0.4
  sold 0.0005 BTC at 81200 fee 0.04
  buy 1.5 SPUS @ 59.9 fee 1 on 2026-11-02
Commands:
  /help   - formats
  /last   - last 5 logged trades
  /undo   - remove the last trade logged through Telegram
  /pos    - your current positions

Usage: python src/trade_bot.py <path-to-private transactions.csv>
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parents[1]
OFFSET = ROOT / "state" / "telegram_offset.json"
FIELDS = ["date", "domain", "symbol", "qty", "price", "currency", "fees", "note"]

HELP = ("Log a trade by sending, e.g.:\n"
        "• bought 100 OQGN at 0.217 fee 0.4\n"
        "• sold 0.0005 BTC at 81200 fee 0.04\n"
        "• buy 1.5 SPUS @ 59.9 fee 1 on 2026-11-02\n\n"
        "Price and fee are per the instrument's currency (MSX = OMR, crypto = USDT, US/gold = USD, 9405 = SAR). "
        "Fee is optional. Date defaults to today.\n\n"
        "Commands: /last  /undo  /pos  /help\n"
        "Trades are processed every ~15 min.")

TRADE_RE = re.compile(
    r"^\s*(?P<side>buy|bought|sell|sold)\s+(?P<qty>[0-9]*\.?[0-9]+)\s+(?P<sym>[A-Za-z0-9.\-]+)\s+(?:at|@)\s*"
    r"(?P<price>[0-9]*\.?[0-9]+)\s*(?P<ccy>omr|usd|usdt|sar)?"
    r"(?:\s+(?:fees?|commission)\s*(?P<fee>[0-9]*\.?[0-9]+))?"
    r"(?:\s+on\s+(?P<date>\d{4}-\d{2}-\d{2}))?\s*$", re.I)


def api(method: str, **params):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=30)
    r.raise_for_status()
    return r.json()


def reply(text: str):
    try:
        api("sendMessage", chat_id=os.environ["TELEGRAM_CHAT_ID"], text=text)
    except Exception as e:  # noqa: BLE001
        print(f"[telegram reply] {e}")


def load_watch() -> dict:
    w = json.loads((ROOT / "config" / "watchlist.json").read_text())
    return {i["symbol"].upper(): i for i in w["instruments"] if i.get("type") != "reference"}


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [r for r in csv.DictReader(path.open()) if (r.get("date") or "").strip() and not r["date"].startswith("#")]


def write_rows(path: Path, rows: list[dict]):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def parse_trade(text: str, watch: dict) -> tuple[dict | None, str]:
    m = TRADE_RE.match(text)
    if not m:
        return None, "I couldn't read that. Send /help for the format."
    sym = m["sym"].upper()
    inst = watch.get(sym)
    if not inst:
        return None, f"{sym} isn't in your watchlist. Known symbols: " + ", ".join(sorted(watch))
    qty, price = float(m["qty"]), float(m["price"])
    if qty <= 0 or price <= 0:
        return None, "Quantity and price must be above zero."
    sell = m["side"].lower() in ("sell", "sold")
    ccy = (m["ccy"] or inst.get("currency") or "USD").upper()
    day = m["date"] or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    fee = float(m["fee"] or 0)
    if inst.get("view") == "AVOID" and not sell:
        warn = f"\n⚠️ Note: {sym} is on your AVOID list ({inst.get('compliance_note', '')})."
    else:
        warn = ""
    row = {"date": day, "domain": inst["domain"], "symbol": sym, "qty": f"{-qty if sell else qty:g}",
           "price": f"{price:g}", "currency": ccy, "fees": f"{fee:g}", "note": "telegram"}
    return row, warn


def position_qty(rows: list[dict], sym: str) -> float:
    return sum(float(r["qty"]) for r in rows if r["symbol"].strip().upper() == sym)


def main(tx_path: str):
    path = Path(tx_path)
    chat = str(os.environ.get("TELEGRAM_CHAT_ID", ""))
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not chat:
        print("telegram not configured")
        return
    offset = json.loads(OFFSET.read_text()).get("offset", 0) if OFFSET.exists() else 0
    upd = api("getUpdates", offset=offset, timeout=0, allowed_updates=["message"]).get("result", [])
    if not upd:
        print("no new messages")
        return
    watch = load_watch()
    rows = read_rows(path)
    changed = False
    for u in upd:
        offset = max(offset, u["update_id"] + 1)
        msg = u.get("message") or {}
        if str(msg.get("chat", {}).get("id")) != chat:  # ignore anyone else who finds your bot
            continue
        text = (msg.get("text") or "").strip()
        low = text.lower()
        if low in ("/start", "/help", "help"):
            reply(HELP)
        elif low == "/last":
            last = rows[-5:]
            reply("Last trades:\n" + "\n".join(
                f"{r['date']} {'SELL' if float(r['qty']) < 0 else 'BUY'} {abs(float(r['qty'])):g} {r['symbol']} @ {r['price']} "
                f"{r['currency']} fee {r.get('fees') or 0}" for r in last) if last else "No trades logged yet.")
        elif low == "/undo":
            idx = next((i for i in range(len(rows) - 1, -1, -1) if (rows[i].get("note") or "").startswith("telegram")), None)
            if idx is None:
                reply("Nothing logged through Telegram to undo.")
            else:
                r = rows.pop(idx)
                changed = True
                reply(f"↩️ Removed: {r['date']} {r['symbol']} qty {r['qty']} @ {r['price']} {r['currency']}")
        elif low == "/pos":
            syms = sorted({r["symbol"].upper() for r in rows})
            held = [(s, position_qty(rows, s)) for s in syms]
            held = [h for h in held if h[1] > 1e-12]
            reply("Positions:\n" + "\n".join(f"{s}: {q:g}" for s, q in held) if held else "No open positions.")
        else:
            row, info = parse_trade(text, watch)
            if not row:
                reply(info)
                continue
            sym, q = row["symbol"], float(row["qty"])
            if q < 0 and position_qty(rows, sym) + q < -1e-9:
                reply(f"You only hold {position_qty(rows, sym):g} {sym}. That sell would go negative (no short selling). Not logged.")
                continue
            rows.append(row)
            changed = True
            total = abs(q) * float(row["price"])
            side = "SELL" if q < 0 else "BUY"
            reply(f"✅ Logged {side} {abs(q):g} {sym} @ {row['price']} {row['currency']} "
                  f"(total {total:,.4g} + fee {row['fees']} {row['currency']}) on {row['date']}.\n"
                  f"Position now: {position_qty(rows, sym):g} {sym}. /undo to remove.{info}")
    if changed:
        write_rows(path, rows)
    OFFSET.parent.mkdir(exist_ok=True)
    OFFSET.write_text(json.dumps({"offset": offset}))
    print(f"processed {len(upd)} messages, changed={changed}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "portfolio" / "transactions.csv"))
