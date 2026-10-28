"""Deterministic synthetic prices for offline testing (OFFLINE_SAMPLE=1)."""
import hashlib

import numpy as np
import pandas as pd


def synthetic_series(symbol: str, days: int = 400) -> pd.Series:
    seed = int(hashlib.md5(symbol.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    drift = rng.uniform(-0.0015, 0.002)
    rets = rng.normal(drift, 0.02, days)
    prices = 100 * np.exp(np.cumsum(rets))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    return pd.Series(prices, index=idx, name=symbol)
