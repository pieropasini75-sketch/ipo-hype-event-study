"""Run the whole study and write tables and charts to results/.

    python run_study.py

Steps: load the IPO list -> load cached prices (downloading what is missing)
-> abnormal returns vs QQQ -> choose N* on train -> evaluate N* on test
-> repeat with SPY using the same N* -> save CSVs and the main chart.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # write files only; never open a window
import matplotlib.pyplot as plt  # noqa: E402

from ipo_study import analysis, data  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# Chart colors: categorical slots 1-2 of a colorblind-validated palette.
COLORS = {"hype": "#2a78d6", "no_hype": "#eb6834"}
LABELS = {"hype": "Hyped IPOs", "no_hype": "Not hyped"}
SURFACE, TEXT, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def plot_abnormal_curve(panel, n_star: int, benchmark_name: str, path: Path) -> None:
    """Mean abnormal return by N: hype vs not hyped, train and test side by side."""
    curve = panel.groupby(["period", "group", "N"])["abnormal_return"].mean() * 100
    counts = panel[panel["N"] == 0].groupby(["period", "group"])["ticker"].nunique()

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
            ax.annotate(LABELS[group], (y.index[-1], y.values[-1]), xytext=(4, 0),
                        textcoords="offset points", color=TEXT, fontsize=9, va="center")
        ax.set_title(title, color=TEXT, fontsize=11, loc="left")
        ax.set_xlabel("Trading days held (N)", color=MUTED)
        ax.set_xlim(0, 22)
        ax.set_xticks(range(0, 21, 5))  # N is a whole number of days
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.tick_params(colors=MUTED)
        for side in ["top", "right"]:
            ax.spines[side].set_visible(False)
        for side in ["left", "bottom"]:
            ax.spines[side].set_color(GRID)
        ax.legend(frameon=False, fontsize=9, labelcolor=TEXT, loc="upper right")
    axes[0].set_ylabel(f"Mean abnormal return vs {benchmark_name} (%)", color=MUTED)
    fig.suptitle("Buy at the first trade, sell at the day-N close (after 0.2% costs)",
                 color=TEXT, fontsize=12, x=0.01, ha="left")
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


def main() -> None:
    RESULTS_DIR.mkdir(exist_ok=True)
    ipos = data.load_ipos()
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
    print(f"Tables and charts written to {RESULTS_DIR}")


if __name__ == "__main__":
    main()
