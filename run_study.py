"""Run the whole study and write tables and charts to results/.

    python run_study.py            # v1: the 47 hand-verified IPOs
    python run_study.py v2         # v2: the expanded Nasdaq sample
    python run_study.py anthropic  # prospective case: apply the fixed rule to Anthropic

Steps: load the IPO list -> load cached prices (downloading what is missing)
-> abnormal returns vs QQQ -> choose N* on train -> evaluate N* on test
-> repeat with SPY using the same N* -> save CSVs and the main chart.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files only; never open a window
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from ipo_study import analysis, data  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Chart colors: categorical slots 1-2 of a colorblind-validated palette.
COLORS = {"hype": "#2a78d6", "no_hype": "#eb6834"}
LABELS = {"hype": "Hyped IPOs", "no_hype": "Not hyped"}
SURFACE, TEXT, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def plot_abnormal_curve(panel, n_star: int, benchmark_name: str, path: Path) -> None:
    """Mean abnormal return by N: hype vs not hyped, train and test side by side."""
    curve = panel.groupby(["period", "group", "N"])["abnormal_return"].mean() * 100
    counts = panel[panel["N"] == 0].groupby(["period", "group"])["ipo_id"].nunique()

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=True, facecolor=SURFACE)
    for ax, period, title in zip(axes, ["train", "test"], ["Train: 2010-2019", "Test: 2020+"]):
        ax.set_facecolor(SURFACE)
        ax.axhline(0, color=MUTED, linewidth=1)
        ax.axvline(n_star, color=MUTED, linewidth=1, linestyle="--")
        ax.text(n_star + 0.3, 0.98, f"N* = {n_star}", transform=ax.get_xaxis_transform(),
                color=MUTED, fontsize=9, va="top")
        for group in ["hype", "no_hype"]:
            if (period, group) not in curve.index:
                continue
            y = curve.loc[(period, group)]
            n_ipos = counts.get((period, group), 0)
            ax.plot(y.index, y.values, color=COLORS[group], linewidth=2,
                    label=f"{LABELS[group]} (n={n_ipos})")
        ax.set_title(title, color=TEXT, fontsize=11, loc="left")
        ax.set_xlabel("Trading days held (N)", color=MUTED)
        ax.set_xlim(0, 20)
        ax.set_xticks(range(0, 21, 5))  # N is a whole number of days
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.tick_params(colors=MUTED)
        for side in ["top", "right"]:
            ax.spines[side].set_visible(False)
        for side in ["left", "bottom"]:
            ax.spines[side].set_color(GRID)
        ax.legend(frameon=False, fontsize=9, labelcolor=TEXT, loc="best")
    axes[0].set_ylabel(f"Mean abnormal return vs {benchmark_name} (%)", color=MUTED)
    fig.suptitle("Buy at the first trade, sell at the day-N close (after 0.2% costs)",
                 color=TEXT, fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def plot_prospective(new, past, n_star: int, path: Path) -> None:
    """A new IPO's abnormal curve against the hyped test-period IPOs (median and 10-90% band)."""
    ref = analysis.curves(past, "hype", "test") * 100
    lo, mid, hi = (ref.quantile(q) for q in (0.10, 0.50, 0.90))
    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor=SURFACE)
    ax.set_facecolor(SURFACE)
    ax.fill_between(mid.index, lo, hi, color=COLORS["hype"], alpha=0.15, linewidth=0,
                    label=f"Hyped IPOs 2020+, 10th-90th percentile (n={len(ref)})")
    ax.plot(mid.index, mid, color=COLORS["hype"], linewidth=2, label="Hyped IPOs 2020+, median")
    for ticker, sub in new.groupby("ticker"):
        ax.plot(sub["N"], sub["abnormal_return"] * 100, color=COLORS["no_hype"], linewidth=2.5,
                marker="o", markersize=4, label=f"{ticker} (through {sub['date'].max():%Y-%m-%d})")
    ax.axhline(0, color=MUTED, linewidth=1)
    ax.axvline(n_star, color=MUTED, linewidth=1, linestyle="--")
    ax.text(n_star + 0.3, 0.98, f"N* = {n_star}", transform=ax.get_xaxis_transform(),
            color=MUTED, fontsize=9, va="top")
    ax.set_xlim(0, 20)
    ax.set_xticks(range(0, 21, 5))
    ax.set_xlabel("Trading days held (N)", color=MUTED)
    ax.set_ylabel("Abnormal return vs QQQ (%)", color=MUTED)
    ax.set_title("Prospective case: the fixed rule applied to a new IPO", color=TEXT,
                 fontsize=12, loc="left")
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.tick_params(colors=MUTED)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)
    for side in ["left", "bottom"]:
        ax.spines[side].set_color(GRID)
    ax.legend(frameon=False, fontsize=9, labelcolor=TEXT, loc="upper right")
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def run_benchmark(benchmark_name, benchmark, ipos, ipo_data, n_star=None):
    """Panel, summary table and N* for one benchmark. N* is chosen only if not given."""
    panel, ipo_table = analysis.build_events(ipos, ipo_data, benchmark)
    table = analysis.summary_table(panel)
    if n_star is None:
        n_star = analysis.choose_best_n(table)

    tag = benchmark_name.lower()
    panel.to_csv(RESULTS_DIR / f"panel_{tag}.csv", index=False)
    ipo_table.to_csv(RESULTS_DIR / f"ipos_{tag}.csv", index=False)
    table.to_csv(RESULTS_DIR / f"summary_by_n_{tag}.csv", index=False)
    analysis.at_n(table, n_star).to_csv(RESULTS_DIR / f"headline_{tag}.csv")
    plot_abnormal_curve(panel, n_star, benchmark_name, RESULTS_DIR / f"abnormal_curve_{tag}.png")
    return n_star, table


def report_robustness(benchmark, ipos, ipo_data, n_star: int) -> None:
    """Multiple-testing correction, hype-label test and investor risk (vs QQQ)."""
    panel, _ = analysis.build_events(ipos, ipo_data, benchmark)

    # 1. Is the best N in training better than luck, given that 21 N were searched?
    mt = analysis.max_t_bootstrap(analysis.curves(panel, "hype", "train"))
    # 2. In the test period, does the hype label separate IPOs at N*?
    at = panel[(panel["N"] == n_star) & (panel["period"] == "test")]
    label = analysis.label_permutation_test(
        at.loc[at["group"] == "hype", "abnormal_return"],
        at.loc[at["group"] == "no_hype", "abnormal_return"])
    pd.DataFrame([{**mt, **{f"label_{k}": v for k, v in label.items()}}]).to_csv(
        RESULTS_DIR / "multiple_testing_qqq.csv", index=False)
    print(f"Max-t correction (train): max t = {mt['max_t']:.2f}, adjusted p = {mt['p_adjusted']:.4f}")
    print(f"Hype label (test, N*): diff in means = {label['diff_in_means']:+.4f}, "
          f"p = {label['p_value']:.4f}\n")

    # 3. Risk of the trade we would use for Anthropic: hyped IPOs, test period, N*.
    hyped = at[at["group"] == "hype"]
    rows = []
    for measure in ["abnormal_return", "ipo_return"]:
        rows.append({"measure": measure, "k": 1, **analysis.single_trade_risk(hyped[measure])})
        many = analysis.average_of_k_risk(hyped[measure])
        rows += [{"measure": measure, **r} for r in many.to_dict("records")]
    risk = pd.DataFrame(rows)
    risk.to_csv(RESULTS_DIR / "investor_risk_qqq.csv", index=False)
    print("Investor risk (hyped IPOs, test, N*; k = trades averaged):")
    print(risk.round(3).to_string(index=False), "\n")


def report_coverage(ipos, ipo_data, ipo_table) -> None:
    """How many IPOs were lost and why, by year and by offer size (survivorship bias)."""
    keys = [data.ipo_id(t, d) for t, d in zip(ipos["ticker"], ipos["ipo_date"])]
    status = pd.Series("used", index=keys)
    status[~status.index.isin(ipo_data)] = "no Yahoo data"
    status[status.index.isin(ipo_data) & ~status.index.isin(ipo_table["ipo_id"])] = "failed data checks"
    out = ipos.assign(
        status=status.to_numpy(),
        year=ipos["ipo_date"].dt.year,
        size_class=(ipos["offer_size_usd"] >= analysis.HYPE_MIN_OFFER_SIZE_USD).map(
            {True: ">= US$500M", False: "< US$500M"}),
    )
    by_year = pd.crosstab(out["year"], out["status"])
    by_year["share_lost"] = 1 - by_year.get("used", 0) / by_year.sum(axis=1)
    by_size = pd.crosstab(out["size_class"], out["status"], normalize="index")
    by_year.to_csv(RESULTS_DIR / "coverage_by_year.csv")
    by_size.to_csv(RESULTS_DIR / "coverage_by_size.csv")
    print("Coverage (survivorship bias) by offer size:")
    print(by_size.round(3).to_string(), "\n")


def report_data_screen(benchmark, ipos, ipo_data, n_star: int) -> None:
    """Robustness: the same N* without IPOs whose prices look inconsistently adjusted."""
    panel, ipo_table = analysis.build_events(ipos, ipo_data, benchmark)
    suspect = ipo_table[analysis.suspect_data(ipo_table)]
    suspect.to_csv(RESULTS_DIR / "suspect_data.csv", index=False)
    clean = panel[~panel["ipo_id"].isin(suspect["ipo_id"])]
    table = analysis.at_n(analysis.summary_table(clean), n_star)
    table.to_csv(RESULTS_DIR / "headline_qqq_screened.csv")
    plot_abnormal_curve(clean, n_star, "QQQ", RESULTS_DIR / "abnormal_curve_qqq_screened.png")
    print(f"--- At N* = {n_star}, vs QQQ, without {len(suspect)} IPOs with suspect prices ---")
    print(suspect.groupby(["period", "group"]).size().to_string())
    print(table.round(4).to_string(), "\n")


def report_without_foreign(benchmark, ipos, ipo_data, n_star: int) -> None:
    """Robustness: the same N* on US issuers only (likely foreign issuers removed)."""
    domestic = ipos[~ipos["likely_foreign"]]
    panel, _ = analysis.build_events(domestic, ipo_data, benchmark)
    table = analysis.at_n(analysis.summary_table(panel), n_star)
    table.to_csv(RESULTS_DIR / "headline_qqq_domestic.csv")
    print(f"--- At N* = {n_star}, vs QQQ, without likely foreign issuers ---")
    print(table.round(4).to_string(), "\n")


SAMPLES = {
    "v1": (data.IPOS_CSV, RESULTS_DIR),
    "v2": (data.PROJECT_ROOT / "data" / "ipos_expanded.csv", RESULTS_DIR / "v2"),
}


def main(sample: str = "v1") -> None:
    global RESULTS_DIR
    ipos_path, RESULTS_DIR = SAMPLES[sample]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ipos = data.load_ipos(ipos_path)
    ipo_data = data.load_all_ipos(ipos)
    benchmarks = data.load_benchmarks(ipos)
    print(f"{len(ipo_data)} of {len(ipos)} IPOs have usable prices")

    n_star, qqq_table = run_benchmark("QQQ", benchmarks["QQQ"], ipos, ipo_data)
    _, spy_table = run_benchmark("SPY", benchmarks["SPY"], ipos, ipo_data, n_star=n_star)

    print(f"\nN* (highest t-stat, hyped IPOs, train, vs QQQ) = {n_star}\n")
    report_robustness(benchmarks["QQQ"], ipos, ipo_data, n_star)
    for name, table in [("QQQ", qqq_table), ("SPY", spy_table)]:
        print(f"--- At N* = {n_star}, vs {name} ---")
        print(analysis.at_n(table, n_star).round(4).to_string(), "\n")
    if "likely_foreign" in ipos:
        _, ipo_table = analysis.build_events(ipos, ipo_data, benchmarks["QQQ"])
        report_coverage(ipos, ipo_data, ipo_table)
        report_without_foreign(benchmarks["QQQ"], ipos, ipo_data, n_star)
        report_data_screen(benchmarks["QQQ"], ipos, ipo_data, n_star)
    print(f"Tables and charts written to {RESULTS_DIR}")


PROSPECTIVE_CSV = data.PROJECT_ROOT / "data" / "prospective.csv"


def prospective(results_dir: Path = RESULTS_DIR) -> None:
    """Apply the rule fixed on past IPOs to new ones (Anthropic), without changing anything.

    Hype is decided by the same code as for the historical sample; N* and the
    reference distribution are read from results already written by v1 / v2,
    so nothing is re-chosen after seeing the new IPO.
    """
    ipos = data.load_ipos(PROSPECTIVE_CSV)
    ipo_data = data.load_all_ipos(ipos)  # open windows are downloaded, never cached
    benchmarks = data.load_benchmarks(ipos)
    rows = []
    for sample, folder in [("v1", results_dir), ("v2", results_dir / "v2")]:
        if not (folder / "summary_by_n_qqq.csv").exists():
            continue  # that sample has not been run yet
        n_star = analysis.choose_best_n(pd.read_csv(folder / "summary_by_n_qqq.csv"))
        for name in ["QQQ", "SPY"]:
            panel, ipo_table = analysis.build_events(ipos, ipo_data, benchmarks[name])
            past = pd.read_csv(folder / f"panel_{name.lower()}.csv", **data.TICKER_SAFE)
            reference = past.loc[(past["group"] == "hype") & (past["period"] == "test")
                                 & (past["N"] == n_star), "abnormal_return"]
            for info in ipo_table.itertuples(index=False):
                curve = panel[panel["ipo_id"] == info.ipo_id].set_index("N")["abnormal_return"]
                rows.append({"ticker": info.ticker, "sample": sample, "benchmark": name,
                             "group": info.group, "open_premium": info.open_premium,
                             "offer_size_usd": info.offer_size_usd,
                             **analysis.prospective_verdict(curve, n_star, reference)})
    out = pd.DataFrame(rows)
    out.to_csv(results_dir / "prospective.csv", index=False)
    pd.set_option("display.width", 200)
    print(out.round(4).to_string(index=False))
    curves = analysis.build_events(ipos, ipo_data, benchmarks["QQQ"])[0]
    curves.to_csv(results_dir / "prospective_curve_qqq.csv", index=False)
    # The chart uses the largest sample that has been run (v2 if available).
    folder = results_dir / "v2" if (results_dir / "v2" / "panel_qqq.csv").exists() else results_dir
    past = pd.read_csv(folder / "panel_qqq.csv", **data.TICKER_SAFE)
    n_star = analysis.choose_best_n(pd.read_csv(folder / "summary_by_n_qqq.csv"))
    plot_prospective(curves, past, n_star, results_dir / "prospective_qqq.png")
    print(f"\nWritten to {results_dir / 'prospective.csv'}")


if __name__ == "__main__":
    import sys

    sample = sys.argv[1] if len(sys.argv) > 1 else "v1"
    prospective() if sample == "anthropic" else main(sample)
