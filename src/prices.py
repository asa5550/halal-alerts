"""Price fetching: Yahoo Finance (US, commodities, crypto fallback), Binance spot
public klines (crypto), and a manual CSV override (MSX or anything without a feed).

Every fetcher returns a pandas Series of daily closes indexed by date, in the
instrument's own currency. Failures return None so one bad symbol never kills a run.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
MANUAL_CSV = ROOT / "config" / "manual_prices.csv"
# data-api.binance.vision is Binance's public market-data mirror. GitHub's runners are in the
# US, where api.binance.com answers HTTP 451, so the mirror comes first.
BINANCE_HOSTS = ["https://data-api.binance.vision", "https://api.binance.com"]
HISTORY_CSV = ROOT / "state" / "price_history.csv"
UA = {"User-Agent": "Mozilla/5.0 (halal-alerts personal price check)"}
TIMEOUT = 20


def binance_klines(pair: str, interval: str = "1d", limit: int = 400) -> list | None:
    for host in BINANCE_HOSTS:
        try:
            r = requests.get(f"{host}/api/v3/klines", params={"symbol": pair, "interval": interval,
                             "limit": min(limit, 1000)}, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:  # noqa: BLE001
            print(f"[binance] {host} {pair}: {e}")
    return None


def binance_closes(pair: str, days: int = 400) -> pd.Series | None:
    rows = binance_klines(pair, "1d", days)
    if not rows:
        return None
    idx = pd.to_datetime([row[0] for row in rows], unit="ms").normalize()
    return pd.Series([float(row[4]) for row in rows], index=idx, name=pair)


# ---------- MSX via Mubasher (15-min delayed, public stock pages) ----------
def mubasher_last(ticker: str) -> float | None:
    """Parse the last price from english.mubasher.info/markets/MSM/stocks/<TICKER>.
    Tries several patterns because the page layout can change; returns None on failure."""
    import re

    url = f"https://english.mubasher.info/markets/MSM/stocks/{ticker}"
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT)
        r.raise_for_status()
        h = r.text
    except Exception as e:  # noqa: BLE001
        print(f"[mubasher] {ticker}: {e}")
        return None
    patterns = [
        r'class="[^"]*last-price[^"]*"[^>]*>\s*([0-9]+(?:\.[0-9]+)?)',
        r'"lastPrice"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)',
        r'"price"\s*:\s*"?([0-9]+(?:\.[0-9]+)?)',
        r'Last\s*(?:Trade\s*)?Price[^0-9]{0,200}?([0-9]+\.[0-9]+)',
    ]
    for pat in patterns:
        m = re.search(pat, h, re.I | re.S)
        if m:
            v = float(m.group(1))
            if 0.001 < v < 100:  # MSX prices are in OMR, almost all between 0.01 and 10
                return v
    print(f"[mubasher] {ticker}: price not found in page")
    return None


def record_history(symbol: str, close: float, day: str) -> None:
    """Keep our own daily history for markets with no free history API (MSX)."""
    HISTORY_CSV.parent.mkdir(exist_ok=True)
    new = not HISTORY_CSV.exists()
    rows = [] if new else list(csv.DictReader(HISTORY_CSV.open()))
    rows = [r for r in rows if not (r["symbol"] == symbol and r["date"] == day)]
    rows.append({"date": day, "symbol": symbol, "close": f"{close}"})
    with HISTORY_CSV.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["date", "symbol", "close"])
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["symbol"], r["date"])))


def stored_closes(symbol: str) -> pd.Series | None:
    """Merge our recorded history with your manual entries (manual wins on the same day)."""
    pts = {}
    for path in (HISTORY_CSV, MANUAL_CSV):
        if path.exists():
            for r in csv.DictReader(path.open()):
                if r["symbol"].strip().upper() == symbol.upper():
                    pts[pd.Timestamp(r["date"])] = float(r["close"])
    if not pts:
        return None
    s = pd.Series(pts).sort_index()
    s.name = symbol
    return s


FETCH_FAILURES: list[str] = []  # read by run.py to raise a "fix MSX feed" alert


def yahoo_closes(ticker: str, days: int = 400) -> pd.Series | None:
    try:
        import yfinance as yf

        df = yf.download(ticker, period=f"{days}d", interval="1d", progress=False, auto_adjust=True)
        if df is None or df.empty:
            return None
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.dropna()
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        close.name = ticker
        return close
    except Exception as e:  # noqa: BLE001
        print(f"[yahoo] {ticker}: {e}")
        return None


def manual_closes(symbol: str) -> pd.Series | None:
    """config/manual_prices.csv: date,symbol,close  (append a row whenever you check a price)."""
    if not MANUAL_CSV.exists():
        return None
    rows = [r for r in csv.DictReader(MANUAL_CSV.open()) if r["symbol"].strip().upper() == symbol.upper()]
    if not rows:
        return None
    s = pd.Series({pd.Timestamp(r["date"]): float(r["close"]) for r in rows}).sort_index()
    s.name = symbol
    return s


def get_closes(inst: dict) -> pd.Series | None:
    """Try sources in order of reliability for the instrument."""
    if os.environ.get("OFFLINE_SAMPLE"):
        from sample_data import synthetic_series

        return synthetic_series(inst["symbol"])
    if inst.get("mubasher"):
        px = mubasher_last(inst["mubasher"])
        if px is not None:
            record_history(inst["symbol"], px, pd.Timestamp.utcnow().strftime("%Y-%m-%d"))
        else:
            FETCH_FAILURES.append(inst["symbol"])
        return stored_closes(inst["symbol"])
    for source in ("binance", "yahoo"):
        sym = inst.get(source)
        if not sym:
            continue
        s = binance_closes(sym) if source == "binance" else yahoo_closes(sym)
        if s is not None and len(s) > 0:
            return s
    return stored_closes(inst["symbol"])
