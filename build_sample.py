"""Build the expanded (v2) IPO sample from Nasdaq's IPO calendar.

    python build_sample.py download   # cache every month as raw JSON (~7 minutes the first time)
    python build_sample.py validate   # compare Nasdaq with the 45 hand-verified IPOs
    python build_sample.py filter     # write data/ipos_expanded.csv and data/excluded.csv

Validation showed that Nasdaq's pricedDate is the first trading day (43 of 43),
so ipo_date = pricedDate, and that its share counts are base shares.
"""

from __future__ import annotations

import sys

import pandas as pd

from ipo_study import data, nasdaq

FIRST_MONTH, LAST_MONTH = "2010-01", "2026-06"
MATCH_WINDOW_DAYS = 10  # a ticker can be reused years apart; only match nearby dates
EXPANDED_CSV = data.PROJECT_ROOT / "data" / "ipos_expanded.csv"
EXCLUDED_CSV = data.PROJECT_ROOT / "data" / "excluded.csv"
MIN_OFFER_PRICE = 5.0
SPAC_PRICE, SPAC_ERA_START = 10.0, 2019

# Direct listings have a reference price, not an offer price (rule 5).
# Source: Ritter, "Direct Listings in the U.S." table, plus press coverage.
DIRECT_LISTINGS = {"SPOT", "WORK", "ASAN", "PLTR", "THRY", "RBLX", "COIN", "SQSP", "AMPL", "WRBY"}

# Nasdaq shows a company's *current* name next to its *original* IPO ticker, so a
# SPAC that later merged is listed under the target's name (RTP'U -> "Joby Aviation").
# Names cannot identify SPACs; units, the $10.00 price and name patterns together can.
UNIT_TICKER = r"^[A-Z]{4}U$|['./ ]U$|['./ ][WR]$"
SPAC_NAME = r"acquisition|blank check|\bspac\b"
FUND_NAME = r"\bfund\b|\btrust\b|\betf\b|\bmunicipal\b"
REIT_NAME = r"\breit\b|realty|real estate|properties|apartment|residential"
LP_NAME = r"\bL\.?P\.?\b|partners,? l"
PREFERRED_NAME = r"preferred stock|depositary shares|% notes|notes due"
BANK_NAME = r"bancorp|bankshares|bancshares|savings|\bbank\b|financial corp|mhc"
FOREIGN_NAME = (r"\bltd\b|limited|\bplc\b|n\.v\.|s\.a\.|\bag\b|\bse\b|a/s|\bab\b|"
                r"b\.v\.|s\.p\.a|\bsarl\b|\bllc\b.*cayman")


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
            "company": n["company"],
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
    # The column mixes booleans with NaN (rows not found), so pandas stores it as
    # object; cast to bool before counting or the sum is not a number.
    print(f"\nOffer price matches: {found['price_match'].astype(bool).sum()} of {len(found)}")
    close = (found["shares_ratio"] - 1).abs() < 0.01
    print(f"Shares within 1% of verified base shares: {close.sum()} of {len(found)}")
    print("Shares ratio outside 1%:")
    print(found.loc[~close, ["ticker", "verified_shares", "nasdaq_shares", "shares_ratio"]]
          .to_string(index=False))


def exclusion_reason(calendar: pd.DataFrame) -> pd.Series:
    """The first rule each deal fails, or None if it stays in the sample.

    Rules are checked in a fixed order, so every excluded deal gets exactly one
    reason and excluded.csv can be audited by hand.
    """
    name = calendar["company"].fillna("")
    ticker = calendar["ticker"].fillna("")
    exchange = calendar["exchange"].fillna("")
    price = calendar["offer_price"]
    year = calendar["priced_date"].dt.year

    rules = [
        ("outside 2010-01-01..2026-06-30",
         (calendar["priced_date"] < "2010-01-01") | (calendar["priced_date"] > "2026-06-30")),
        ("no ticker", ticker.eq("")),
        ("exchange not NYSE/Nasdaq",
         ~exchange.str.contains(r"nasdaq|^nyse$|new york stock", case=False)),
        ("no offer price (missing or a range)", price.isna()),
        (f"offer price below ${MIN_OFFER_PRICE:.0f}", price < MIN_OFFER_PRICE),
        ("direct listing", ticker.isin(DIRECT_LISTINGS)),
        ("unit / warrant / right", ticker.str.contains(UNIT_TICKER)),
        ("SPAC (name)", name.str.contains(SPAC_NAME, case=False)),
        ("mutual bank conversion ($10, bank name)",
         price.eq(SPAC_PRICE) & name.str.contains(BANK_NAME, case=False)),
        (f"likely SPAC (${SPAC_PRICE:.2f} offer, {SPAC_ERA_START}+)",
         price.eq(SPAC_PRICE) & (year >= SPAC_ERA_START)),
        ("fund / trust / ETF", name.str.contains(FUND_NAME, case=False)),
        ("REIT / real estate", name.str.contains(REIT_NAME, case=False)),
        ("limited partnership", name.str.contains(LP_NAME, case=False)),
        ("preferred / notes", name.str.contains(PREFERRED_NAME, case=False)),
        ("duplicate row", calendar.duplicated(subset=["ticker", "priced_date"], keep="first")),
    ]
    reason = pd.Series(None, index=calendar.index, dtype=object)
    for label, failed in rules:
        reason = reason.where(reason.notna() | ~failed, label)
    return reason


def build_expanded(calendar: pd.DataFrame, verified: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filtered Nasdaq deals merged with the hand-verified list (verified data wins, rule 8)."""
    calendar = calendar.copy()
    calendar["reason"] = exclusion_reason(calendar)

    # Rule 8: a deal that matches a verified IPO is replaced by the verified row.
    verified_ipos = verified[verified["listing_type"] == "ipo"]
    match = match_verified(verified_ipos, calendar.drop(columns="reason"))
    for v in verified_ipos.itertuples(index=False):
        gap = (calendar["priced_date"] - v.ipo_date).dt.days.abs()
        same = (calendar["ticker"] == v.ticker) & (gap <= MATCH_WINDOW_DAYS)
        calendar.loc[same, "reason"] = "in verified list (verified row used)"

    kept = calendar[calendar["reason"].isna()]
    from_nasdaq = pd.DataFrame({
        "ticker": kept["ticker"],
        "company": kept["company"],
        "ipo_date": kept["priced_date"],  # rule 9: pricedDate is the first trading day
        "offer_price": kept["offer_price"],
        "shares_offered": kept["shares_offered"],
        "offer_size_usd": kept["offer_price"] * kept["shares_offered"],
        "range_low": float("nan"),
        "range_high": float("nan"),
        "listing_type": "ipo",
        "notes": "Nasdaq IPO calendar",
        "likely_foreign": kept["company"].str.contains(FOREIGN_NAME, case=False),
    })

    verified = verified.copy()
    nasdaq_names = match.set_index("ticker")["company"] if "company" in match else pd.Series(dtype=str)
    verified["likely_foreign"] = verified["ticker"].map(nasdaq_names).fillna("").str.contains(
        FOREIGN_NAME, case=False)
    verified["notes"] = verified["notes"].fillna("").str.cat(["verified list (v1)"] * len(verified),
                                                              sep="; ").str.strip("; ")

    expanded = (pd.concat([verified, from_nasdaq], ignore_index=True)
                .sort_values(["ipo_date", "ticker"]).reset_index(drop=True))
    excluded = calendar[calendar["reason"].notna()][
        ["ticker", "company", "exchange", "offer_price", "shares_offered", "priced_date", "reason"]]
    return expanded, excluded


def filter_sample() -> None:
    calendar = nasdaq.load_calendar(FIRST_MONTH, LAST_MONTH)
    verified = data.load_ipos()
    expanded, excluded = build_expanded(calendar, verified)

    expanded.assign(ipo_date=expanded["ipo_date"].dt.strftime("%Y-%m-%d")).to_csv(
        EXPANDED_CSV, index=False)
    excluded.assign(priced_date=excluded["priced_date"].dt.strftime("%Y-%m-%d")).to_csv(
        EXCLUDED_CSV, index=False)

    print(f"{len(calendar)} Nasdaq deals -> {len(expanded)} IPOs in the expanded sample "
          f"({(expanded['listing_type'] == 'ipo').sum()} IPOs, "
          f"{(expanded['listing_type'] == 'direct_listing').sum()} direct listings)\n")
    print("Excluded, by reason:")
    print(excluded["reason"].value_counts().to_string())
    print("\nIPOs per year:")
    print(expanded.groupby(expanded["ipo_date"].dt.year).size().to_string())
    big = expanded["offer_size_usd"] >= 500_000_000
    print(f"\nOffer size >= US$500M (can be hyped): {big.sum()}")
    print(f"Likely foreign issuers: {expanded['likely_foreign'].sum()}")


def download_prices() -> None:
    """Cache Yahoo prices for every IPO in the expanded sample; record the ones with no data.

    Resumable: cached tickers are skipped. Rate-limit errors are retried with a
    growing wait. Tickers Yahoo does not have (delisted, renamed, merged) are
    written to no_yahoo_data.csv so later runs skip them and the study can count
    them as survivorship bias.
    """
    import time
    import warnings

    expanded = data.load_ipos(EXPANDED_CSV)
    done = set()
    if data.NO_YAHOO_CSV.exists():
        known = pd.read_csv(data.NO_YAHOO_CSV, **data.TICKER_SAFE)
        done = {data.ipo_id(t, d) for t, d in zip(known["ticker"], known["ipo_date"])}
    missing = []
    for i, row in enumerate(expanded.itertuples(index=False), start=1):
        if data.ipo_id(row.ticker, row.ipo_date) in done:
            continue
        start, end = data.event_window(row.ipo_date)
        for attempt in range(5):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    prices, _ = data.get_ticker_data(row.ticker, start, end)
                break
            except Exception as error:  # yfinance raises several rate-limit error types
                wait = 30 * (attempt + 1)
                print(f"  {row.ticker}: {type(error).__name__}; retrying in {wait}s")
                time.sleep(wait)
        else:
            prices = pd.DataFrame()
        if prices.empty:
            missing.append({"ticker": row.ticker, "ipo_date": row.ipo_date.date()})
        if i % 100 == 0:
            print(f"[{i}/{len(expanded)}] {len(missing)} without Yahoo data so far", flush=True)

    if missing:
        old = pd.read_csv(data.NO_YAHOO_CSV, **data.TICKER_SAFE) if data.NO_YAHOO_CSV.exists() else pd.DataFrame()
        pd.concat([old, pd.DataFrame(missing)]).dropna(subset=["ticker"]).drop_duplicates(
            ["ticker", "ipo_date"]).to_csv(
            data.NO_YAHOO_CSV, index=False)
    print(f"Done. {len(missing)} new tickers without Yahoo data (listed in {data.NO_YAHOO_CSV.name})")


if __name__ == "__main__":
    commands = {"download": download, "validate": validate, "filter": filter_sample,
                "prices": download_prices}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        sys.exit(f"usage: python build_sample.py [{' | '.join(commands)}]")
    commands[sys.argv[1]]()
