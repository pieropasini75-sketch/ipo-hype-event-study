"""Download, cache and parse Nasdaq's monthly IPO calendar (the "priced" section).

The endpoint is unofficial: no API key, one calendar month per request, and it
rejects clients without a browser-like User-Agent. Raw responses are cached as
JSON in data/nasdaq_raw/ so the sample can always be rebuilt without the network.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

from ipo_study.data import PROJECT_ROOT

RAW_DIR = PROJECT_ROOT / "data" / "nasdaq_raw"
URL = "https://api.nasdaq.com/api/ipo/calendar?date={year}-{month:02d}"
HEADERS = {
    # Generic browser User-Agent; the endpoint refuses requests without one.
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"),
    "Accept": "application/json",
}
PAUSE_SECONDS = 2.0  # be polite: one request every 2 seconds


def months(first: str, last: str) -> list[tuple[int, int]]:
    """Every (year, month) from `first` to `last` inclusive, e.g. months("2010-01", "2010-03")."""
    periods = pd.period_range(first, last, freq="M")
    return [(p.year, p.month) for p in periods]


def fetch_month(year: int, month: int, raw_dir: Path = RAW_DIR) -> dict:
    """The raw JSON for one month, from the cache or from Nasdaq.

    Returns the cached file if it exists. Otherwise downloads it, checks that
    it has a "priced" section, and only then writes it to the cache, so a
    failed or empty response is never saved and is retried on the next run.
    """
    path = raw_dir / f"{year}-{month:02d}.json"
    if path.exists():
        return json.loads(path.read_text())

    request = urllib.request.Request(URL.format(year=year, month=month), headers=HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    if not (payload.get("data") or {}).get("priced"):
        raise ValueError(f"{year}-{month:02d}: response has no 'priced' section")

    raw_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    time.sleep(PAUSE_SECONDS)  # only after a real download, not after a cache hit
    return payload


def _number(text) -> float:
    """'$1,425,000,000.00' or '13,300,000' -> float. Empty, missing or a range -> NaN.

    A few rows are malformed: stray spaces ('14 .00'), invisible HTML characters
    ('10.00\\t&#8203;') and price *ranges* ('10.45-12.80'). The first two are
    cleaned; a range does not tell us the final price, so it becomes NaN and the
    filter later excludes that IPO instead of guessing.
    """
    if text is None:
        return float("nan")
    text = html.unescape(str(text))
    if "-" in text:
        return float("nan")
    cleaned = re.sub(r"[^0-9.]", "", text)  # keep digits and the decimal point only
    return float(cleaned) if cleaned else float("nan")


def parse_priced(payload: dict) -> pd.DataFrame:
    """The 'priced' rows of one month as a typed DataFrame."""
    rows = payload["data"]["priced"].get("rows") or []
    return pd.DataFrame({
        "deal_id": [r.get("dealID") for r in rows],
        "ticker": [r.get("proposedTickerSymbol") for r in rows],
        "company": [r.get("companyName") for r in rows],
        "exchange": [r.get("proposedExchange") for r in rows],
        "offer_price": [_number(r.get("proposedSharePrice")) for r in rows],
        "shares_offered": [_number(r.get("sharesOffered")) for r in rows],
        "nasdaq_dollar_value": [_number(r.get("dollarValueOfSharesOffered")) for r in rows],
        "priced_date": pd.to_datetime([r.get("pricedDate") for r in rows], format="%m/%d/%Y"),
    })


def load_calendar(first: str, last: str, raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """All priced IPOs from `first` to `last` (YYYY-MM), downloading missing months."""
    frames = [parse_priced(fetch_month(y, m, raw_dir)) for y, m in months(first, last)]
    return pd.concat(frames, ignore_index=True)
