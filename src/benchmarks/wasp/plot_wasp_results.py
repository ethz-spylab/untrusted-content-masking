"""
Plot WASP attack results comparing defense conditions.

Usage:
    python plot_wasp_results.py [--results-dir results_wasp_attacks_v2_readfollow]
                                [--format important_instructions]
                                [--model claude-sonnet-4-20250514]
                                [--output-dir plots]
                                [--export-csv wasp_summary.csv]

    Log only:  uv run python plot_wasp_results.py ... 2>&1 | tee wasp_run_log.txt

Produces two bar charts:
  1. Attack Success Rate (%) per defense condition
  2. Benign Task Success Rate (%) per defense condition

Error bars: sample SD (ddof=1) of per-run success rates across runs — not SEM.
"""
import argparse
import csv
import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


TASK_RANGE = range(1000, 1012)

DEFENSE_CONDITIONS = [
    {
        "label": "No Defense",
        "prompt": "no_security",
        "reveal": "all_revealed",
        "color": "#e74c3c",
    },
    {
        "label": "WASP Sys-Prompt",
        "prompt": "wasp_defense",
        "reveal": "all_revealed",
        "color": "#f39c12",
    },
    {
        "label": "Mislabeled\nUCM",
        # Your results live under:
        #   .../<model>/mislabeled_ucm/ucm_defense/untrusted_masked/...
        # `load_results_by_run` will join `prompt` as a (possibly nested) directory.
        "prompt": "mislabeled_ucm/ucm_defense",
        "reveal": "untrusted_masked",
        "color": "#27ae60",
    },
    {
        "label": "UCM",
        "prompt": "ucm_defense",
        "reveal": "untrusted_masked",
        "color": "#2ecc71",
    },
]


def load_results_by_run(base_dir: str, fmt: str, model: str, prompt: str, reveal: str):
    """Load success.json grouped by run index for all tasks under a condition.

    Layout: {base_dir}/{fmt}/{model_dir}/{prompt}/{reveal}/webarena_gitlab/template_-1/
    ``model_dir`` is the directory name on disk under ``fmt/`` (e.g. claude-sonnet-4-20250514).
    """
    by_run = {}
    path_prefix = Path(base_dir) / fmt / model / prompt / reveal / "webarena_gitlab" / "template_-1"
    for run_dir in sorted(path_prefix.glob("wa_*/run_*")):
        run_name = run_dir.name
        if not run_name.startswith("run_"):
            continue
        try:
            run_idx = int(run_name.split("_")[1])
        except (IndexError, ValueError):
            continue

        if run_idx not in by_run:
            by_run[run_idx] = [None] * len(TASK_RANGE)

        wa_name = run_dir.parent.name
        try:
            task_id = int(wa_name.split("_")[1])
            task_offset = task_id - TASK_RANGE.start
        except (IndexError, ValueError):
            continue

        if task_offset < 0 or task_offset >= len(TASK_RANGE):
            continue

        sj = run_dir / "success.json"
        if sj.exists():
            with open(sj) as f:
                by_run[run_idx][task_offset] = json.load(f)
    return by_run


def compute_rates(results):
    """Return (attack_success_rate, benign_success_rate, n_complete)."""
    completed = [r for r in results if r is not None]
    n = len(completed)
    if n == 0:
        return 0.0, 0.0, 0

    n_attack = 0
    n_benign = 0
    for d in completed:
        atk = d.get("attack_success", False)
        if isinstance(atk, dict):
            atk = atk.get("success", False)
        if atk:
            n_attack += 1
        if d.get("webarena_score", 0) == 1.0:
            n_benign += 1

    return n_attack / n * 100, n_benign / n * 100, n


def compute_stats_from_runs(results_by_run):
    """Return mean and sample SD (across runs) for attack and benign rate percentages."""
    if not results_by_run:
        return 0.0, 0.0, 0.0, 0.0, 0, 0, 0

    attack_rates = []
    benign_rates = []
    total_attack = 0
    total_benign = 0
    total_n = 0
    for _, run_results in sorted(results_by_run.items()):
        atk_rate, ben_rate, n = compute_rates(run_results)
        attack_rates.append(atk_rate)
        benign_rates.append(ben_rate)
        total_n += n
        total_attack += round(atk_rate * n / 100)
        total_benign += round(ben_rate * n / 100)

    atk_mean = float(np.mean(attack_rates))
    ben_mean = float(np.mean(benign_rates))
    atk_std = float(np.std(attack_rates, ddof=1)) if len(attack_rates) > 1 else 0.0
    ben_std = float(np.std(benign_rates, ddof=1)) if len(benign_rates) > 1 else 0.0
    return atk_mean, atk_std, ben_mean, ben_std, len(attack_rates), total_attack, total_benign


def make_bar_chart(labels, values, errors, colors, ylabel, output_path):
    """Create a single bar chart."""
    fig, ax = plt.subplots(figsize=(6, 4.5))

    x = np.arange(len(labels))
    bars = ax.bar(
        x,
        values,
        yerr=errors,
        capsize=5,
        color=colors,
        width=0.55,
        edgecolor="white",
        linewidth=1.2,
        error_kw={"elinewidth": 1.4, "ecolor": "#333333"},
    )

    for bar, val in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1.5,
                f"{val:.0f}%",
                ha="center", va="bottom", fontweight="bold", fontsize=12)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel(ylabel, fontsize=12)
    ax.set_ylim(0, 115)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))

    plt.tight_layout()
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    print(f"  Saved: {output_path}")
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Plot WASP attack results")
    parser.add_argument("--results-dir", default="results_wasp_attacks_v2_readfollow")
    parser.add_argument("--format", default="important_instructions", dest="fmt")
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-20250514",
        help="Folder name under --results-dir/--format (e.g. claude-sonnet-4-20250514), not a display label",
    )
    parser.add_argument("--output-dir", default="analysis_output/wasp_plots")
    parser.add_argument(
        "--export-csv",
        default=None,
        metavar="PATH",
        help="Write per-defense mean ± SD (across runs) for attack and utility rates for pasting into a table",
    )
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    labels = []
    attack_rates = []
    attack_errs = []
    benign_rates = []
    benign_errs = []
    colors = []
    attack_counts = []
    benign_counts = []
    n_slots_list = []
    n_runs_list = []

    print(f"Loading results from: {args.results_dir}/{args.fmt}/{args.model}/\n")

    for cond in DEFENSE_CONDITIONS:
        results_by_run = load_results_by_run(
            args.results_dir, args.fmt, args.model, cond["prompt"], cond["reveal"]
        )
        atk_rate, atk_std, ben_rate, ben_std, n_runs, n_atk, n_ben = compute_stats_from_runs(results_by_run)
        n = len(TASK_RANGE) * n_runs if n_runs > 0 else 0

        labels.append(cond["label"])
        attack_rates.append(atk_rate)
        attack_errs.append(atk_std)
        benign_rates.append(ben_rate)
        benign_errs.append(ben_std)
        colors.append(cond["color"])

        attack_counts.append(f"{n_atk}/{n}")
        benign_counts.append(f"{n_ben}/{n}")
        n_slots_list.append(n)
        n_runs_list.append(n_runs)

        print(
            f"  {cond['label']:20s}  "
            f"attack={atk_rate:5.1f}% ± {atk_std:4.1f} SD runs ({n_atk}/{n}, n_runs={n_runs})  "
            f"utility={ben_rate:5.1f}% ± {ben_std:4.1f} SD runs ({n_ben}/{n}, n_runs={n_runs})"
        )

    print()

    if args.export_csv:
        csv_path = Path(args.export_csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with open(csv_path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow([
                "defense",
                "attack_mean_pct",
                "attack_sd_across_runs",
                "benign_mean_pct",
                "benign_sd_across_runs",
                "n_runs",
                "n_task_slots",
                "attack_successes",
                "benign_successes",
            ])
            for i, lab in enumerate(labels):
                na = int(attack_counts[i].split("/")[0])
                nb = int(benign_counts[i].split("/")[0])
                w.writerow([
                    lab,
                    f"{attack_rates[i]:.4f}",
                    f"{attack_errs[i]:.4f}",
                    f"{benign_rates[i]:.4f}",
                    f"{benign_errs[i]:.4f}",
                    n_runs_list[i],
                    n_slots_list[i],
                    na,
                    nb,
                ])
        print(f"  Wrote table: {csv_path.resolve()}\n")

    make_bar_chart(
        labels, attack_rates, attack_errs, colors,
        "Attack Success Rate",
        os.path.join(args.output_dir, "wasp_attack_success.png"),
    )

    make_bar_chart(
        labels, benign_rates, benign_errs, colors,
        "Utility Under Attack",
        os.path.join(args.output_dir, "wasp_utility.png"),
    )

    print("\nDone!")


if __name__ == "__main__":
    main()
