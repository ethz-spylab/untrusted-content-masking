# Plotting

Two scripts that turn a results directory into figures:

- [plot_custom_websites.py](plot_custom_websites.py) — figures for the custom-website benchmark suites.
- [plot_webarena.py](plot_webarena.py) — figures for the WebArena GitLab benchmark.

Both write outputs under `analysis_output/<results_dir_name>/`.

## Quick start

From the project root:

```bash
# Custom websites
python -m src.plot.plot_custom_websites <path/to/results_dir>

# WebArena GitLab
python -m src.plot.plot_webarena <path/to/results_dir>
```

Each script takes the results directory as its first positional argument. Add
`--help` to see all available filtering flags (per-model, per-suite, per-condition,
output location, etc.).

## Two modes: quick vs full

Both scripts accept `--verbose` (or `-v`), and it's off by default.

**Without** `--verbose` you get just the headline comparison of UCM vs  
Undefended: one figure for task accuracy and one figure for  
cost per task. This is the mode to use when you want a fast look at how UCM  
performs against the undefended baseline.

**With `--verbose`** you get the same two headline figures *plus* a lot more:
extra breakdowns by suite or category, cost and token diagnostics, per-model
versions of the plots, and supporting CSVs. Expect many more files — turn
this on when you want to dig into the details of a run, not when you just
want the headline UCM-vs-undefended comparison.

Cross-model comparison panels (under `all_models/`) are produced automatically
when the results directory contains 2+ model subdirs, and skipped silently with
a single model. `--all-models` / `--side-by-side-models` are optional force-ons.

## Q-Model string-output allowed (WebArena only)

When `plot_webarena.py` is given a second results directory via
`--user-help-dir`, tasks that the masking defense initially failed but a retry
run (with Q-Model string output allowed) solved are shown as a lighter shaded
segment stacked on top of each Masking Defense bar in the accuracy figure.
Per `(model, condition, task_id)`, any task present in the retry directory has
its outcome overridden by the retry outcome; tasks absent from it keep their
main-run result. Without `--user-help-dir`, the bars show only the standalone
defended outcome.

```bash
python -m src.plot.plot_webarena <path/to/main_results_dir> \
    --user-help-dir <path/to/retry_results_dir>
```

## Examples

```bash
# Headline figures only
python -m src.plot.plot_custom_websites results_custom
python -m src.plot.plot_webarena results_webarena

# Headline + full breakdown + per-model panels
python -m src.plot.plot_custom_websites results_custom --verbose
python -m src.plot.plot_webarena results_webarena --verbose

# Restrict to a subset of models / suites
python -m src.plot.plot_custom_websites results_custom \
    --models claude-sonnet-4-5 gpt-5 --suites banking forum
python -m src.plot.plot_webarena results_webarena \
    --models claude-sonnet-4-5-20250929 --conditions ucm_defense no_security
```
