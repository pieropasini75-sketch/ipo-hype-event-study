"""Build the expanded (v2) IPO sample from Nasdaq's IPO calendar.

    python build_sample.py download   # cache every month as raw JSON (~7 minutes the first time)
    python build_sample.py validate   # compare Nasdaq with the 45 hand-verified IPOs

The filter that produces data/ipos_expanded.csv is added only after the
validation fixes the date rule (rule 9 in the plan).
"""

from __future__ import annotations

import sys

import pandas as pd

from ipo_study import data, nasdaq

FIRST_MONTH, LAST_MONTH = "2010-01", "2026-06"
MATCH_WINDOW_DAYS = 10  # a ticker can be reused years apart; only match nearby dates


def download() -> None:
    all_months = nasdaq.months(FIRST_MONTH, LAST_MONTH)
    for i, (year, month) in enumerate(all_months, start=1):
        payload = nasdaq.fetch_month(year, month)
        n = len(payload["data"]["priced"].get("rows") or [])
        print(f"[{i}/{len(all_months)}] {year}-{month:02d}: {n} priced")
    calendar = nasdaq.load_calendar(FIRST_MONTH, LAST_MONTH)
    print(f"\n{len(calendar)} priced deals from {FIRST_MONTH} to {LAST_MONTH}")


def match_verified(verified: pd.DataFrame, calendar: pd.DataFrame) -> pd.DataFrame:
    """Each hand-verified IPO next to its Nasdaq row (same ticker, dates within the window)."""
    rows = []
    for v in verified.itertuples(index=False):
        candidates = calendar[calendar["ticker"] == v.ticker]
        gap = (candidates["priced_date"] - v.ipo_date).dt.days
        candidates = candidates[gap.abs() <= MATCH_WINDOW_DAYS]
        if candidates.empty:
            rows.append({"ticker": v.ticker, "found": False})
            continue
        n = candidates.iloc[0]
        rows.append({
            "ticker": v.ticker,
            "found": True,
            "verified_date": v.ipo_date.date(),
            "nasdaq_date": n["priced_date"].date(),
            "date_gap_days": (n["priced_date"] - v.ipo_date).days,
            "price_match": n["offer_price"] == v.offer_price,
            "verified_shares": v.shares_offered,
            "nasdaq_shares": n["shares_offered"],
            "shares_ratio": n["shares_offered"] / v.shares_offered,
            "exchange": n["exchange"],
        })
    return pd.DataFrame(rows)


def validate() -> None:
    verified = data.load_ipos()
    verified = verified[verified["listing_type"] == "ipo"]
    calendar = nasdaq.load_calendar(FIRST_MONTH, LAST_MONTH)
    report = match_verified(verified, calendar)

    pd.set_option("display.width", 200)
    print(report.to_string(index=False))
    found = report[report["found"]]
    print(f"\nFound {len(found)} of {len(report)} verified IPOs in the Nasdaq calendar")
    print("Not found:", report.loc[~report["found"], "ticker"].tolist())
    print("\nDate gap (Nasdaq - verified first trading day), in days:")
    print(found["date_gap_days"].value_counts().sort_index().to_string())
    print(f"\nOffer price matches: {found['price_match'].sum()} of {len(found)}")
    close = (found["shares_ratio"] - 1).abs() < 0.01
    print(f"Shares within 1% of verified base shares: {close.sum()} of {len(found)}")
    print("Shares ratio outside 1%:")
    print(found.loc[~close, ["ticker", "verified_shares", "nasdaq_shares", "shares_ratio"]]
          .to_string(index=False))


if __name__ == "__main__":
    commands = {"download": download, "validate": validate}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: python build_sample.py [{' | '.join(commands)}]")
    commands[sys.argv[1]]()
