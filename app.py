"""SK Hynix price dashboard backend.

Tracks three instruments:
  * 7709.HK  - CSOP SK Hynix Daily (2x) Leveraged Product (HK-listed, HKD)
  * 000660.KS - SK hynix Inc. on KOSPI (KRW)
  * SKHY     - SK hynix Inc. US direct listing (USD)

Run:
    uv run python app.py
Then open http://127.0.0.1:8787
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import yfinance as yf
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

# ---------------------------------------------------------------------------
# Instrument definitions
# ---------------------------------------------------------------------------

INSTRUMENTS = [
    {"symbol": "7709.HK", "name": "南方两倍做多海力士 (CSOP 2x)", "market": "HK", "currency": "HKD", "kind": "etf_2x"},
    {"symbol": "000660.KS", "name": "SK 海力士 (韩国 KOSPI)", "market": "KR", "currency": "KRW", "kind": "stock"},
    {"symbol": "SKHY", "name": "SK 海力士 (美国)", "market": "US", "currency": "USD", "kind": "stock"},
]

UNDERLYING_FOR_2X = "000660.KS"  # the 2x ETF tracks SK Hynix (Korea)

HISTORY_DAYS = 90

# ---------------------------------------------------------------------------
# Simple TTL cache so we don't hammer Yahoo on every browser poll
# ---------------------------------------------------------------------------


@dataclass
class Cache:
    ttl: float = 60.0
    data: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get_or_set(self, key: str, factory):
        now = time.time()
        async with self.lock:
            entry = self.data.get(key)
            if entry and now - entry["t"] < self.ttl:
                return entry["v"]
        # compute outside the lock
        value = await asyncio.to_thread(factory)
        async with self.lock:
            self.data[key] = {"t": time.time(), "v": value}
        return value


CACHE = Cache(ttl=60.0)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _safe_round(x, n=2):
    try:
        if x is None or (isinstance(x, float) and (np.isnan(x))):
            return None
        return round(float(x), n)
    except Exception:
        return None


def _fetch_snapshot() -> dict:
    """Pull latest quote + recent daily history for every instrument."""
    quotes = []
    histories = {}

    for inst in INSTRUMENTS:
        sym = inst["symbol"]
        df = None
        try:
            df = yf.download(
                sym,
                period=f"{HISTORY_DAYS + 30}d",
                interval="1d",
                auto_adjust=False,
                progress=False,
                threads=False,
                actions=False,
            )
        except Exception as e:
            print(f"[warn] download failed for {sym}: {e}")

        if df is None or df.empty:
            quotes.append({**inst, "quote": None, "history": []})
            histories[sym] = []
            continue

        # Flatten possible MultiIndex columns: keep the field-name level
        if isinstance(df.columns, pd.MultiIndex):
            # yfinance >=0.2.x returns (field, ticker) -> take field (level 0)
            df.columns = df.columns.get_level_values(0)

        df = df.sort_index()
        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else None

        def _col(series, name):
            try:
                return float(series[name])
            except Exception:
                return float("nan")

        close = _col(last, "Close")
        prev_close = _col(prev, "Close") if prev is not None else close
        chg = close - prev_close
        chg_pct = (chg / prev_close * 100.0) if prev_close else 0.0

        quote = {
            "price": _safe_round(close, 4),
            "prev_close": _safe_round(prev_close, 4),
            "change": _safe_round(chg, 4),
            "change_pct": _safe_round(chg_pct, 3),
            "open": _safe_round(_col(last, "Open"), 4),
            "high": _safe_round(_col(last, "High"), 4),
            "low": _safe_round(_col(last, "Low"), 4),
            "volume": int(_col(last, "Volume")) if not np.isnan(_col(last, "Volume")) else None,
            "date": str(df.index[-1].date()),
        }

        hist_df = df.tail(HISTORY_DAYS)
        hist = [
            {"date": str(d.date()), "close": _safe_round(float(r["Close"]), 4)}
            for d, r in hist_df.iterrows()
            if not pd.isna(r["Close"])
        ]
        histories[sym] = hist
        quotes.append({**inst, "quote": quote, "history": hist})

    return {"quotes": quotes, "histories": histories, "fetched_at": time.time()}


def _build_dashboard_payload(snapshot: dict) -> dict:
    """Compose all four views the frontend needs."""
    histories = snapshot["histories"]

    # --- normalized comparison (each symbol normalized to its own first day = 100) ---
    series_by_sym = {sym: {h["date"]: h["close"] for h in hist} for sym, hist in histories.items()}
    all_dates = sorted(set().union(*[set(s.keys()) for s in series_by_sym.values()])) if series_by_sym else []

    norm = []
    base = {}
    for d in all_dates:
        row = {"date": d}
        for sym, s in series_by_sym.items():
            v = s.get(d)
            if v is None:
                continue
            if sym not in base:
                base[sym] = v
            row[sym] = round(v / base[sym] * 100.0, 4) if base[sym] else None
        norm.append(row)

    # --- 2x ETF vs theoretical 2x underlying ---
    lever = []
    etf_hist = histories.get("7709.HK", [])
    und_hist = histories.get(UNDERLYING_FOR_2X, [])
    if etf_hist and und_hist:
        # align by date
        und_map = {h["date"]: h["close"] for h in und_hist}
        etf_map = {h["date"]: h["close"] for h in etf_hist}
        dates = sorted(set(etf_map.keys()) & set(und_map.keys()))
        if len(dates) >= 2:
            # daily returns
            etf_base = etf_map[dates[0]]
            und_base = und_map[dates[0]]
            theo_nav = 100.0  # theoretical 2x nav starting at 100
            etf_nav = 100.0
            prev_und = und_map[dates[0]]
            rows = [{"date": dates[0], "etf": round(etf_nav, 4), "theoretical_2x": round(theo_nav, 4)}]
            for d in dates[1:]:
                u = und_map[d]
                r = (u - prev_und) / prev_und if prev_und else 0.0
                theo_nav = theo_nav * (1 + 2 * r)
                etf_nav = etf_map[d] / etf_base * 100.0
                rows.append({"date": d, "etf": round(etf_nav, 4), "theoretical_2x": round(theo_nav, 4)})
                prev_und = u
            lever = rows

    return {
        "fetched_at": snapshot["fetched_at"],
        "instruments": snapshot["quotes"],
        "normalized": norm,
        "leverage": lever,
        "underlying_for_2x": UNDERLYING_FOR_2X,
    }


def _load_all():
    snap = _fetch_snapshot()
    return _build_dashboard_payload(snap)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="SK Hynix Dashboard")


@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/api/data")
async def data():
    payload = await CACHE.get_or_set("data", _load_all)
    return JSONResponse(payload)


@app.get("/data.json")
async def data_json():
    # Same payload as /api/data, served at the relative path the static
    # frontend (and GitHub Pages build) fetches. Disable caching for local mode.
    payload = await CACHE.get_or_set("data", _load_all)
    return JSONResponse(payload, headers={"Cache-Control": "no-store, max-age=0"})


@app.post("/api/refresh")
async def refresh():
    # force cache invalidation
    async with CACHE.lock:
        CACHE.data.pop("data", None)
    payload = await CACHE.get_or_set("data", _load_all)
    return JSONResponse(payload)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8787, reload=False, log_level="info")
