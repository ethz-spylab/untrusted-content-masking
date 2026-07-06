# WASP attacks

Seeded prompt-injection experiment using  
[WASP](https://github.com/facebookresearch/wasp). Attacks are injected into
GitLab issue descriptions in the WebArena GitLab instance.

## Prerequisites

- The **WebArena GitLab proxy** running locally — see
[../../../environments/webarena/gitlab-setup/README.md](../../../environments/webarena/gitlab-setup/README.md).
The attacks need a live GitLab instance to inject into.
- `ANTHROPIC_API_KEY` exported.
- Python deps installed at the repo root: `uv sync`.

## Attack definitions (`configs/`)

WASP attack payloads in WebArena task format. The runners read these and
hand each payload to `wasp_inject.py`, which pushes it into the live
GitLab:

- [wasp_gitlab_attacks.json](configs/wasp_gitlab_attacks.json) — original
WASP attacks (4 injection formats).
- [wasp_gitlab_attacks_strengthened.json](configs/wasp_gitlab_attacks_strengthened.json) — iteratively-strengthened variants produced by `red_team_inject.py`.

## Running

Main runner — strengthened attacks vs the UCM defense and the baseline:

```bash
bash ../../../runners/run_wasp_attacks.sh
```

Original (unmodified) WASP attacks across all 4 injection formats:

```bash
MODE=original bash ../../../runners/run_wasp_attacks.sh
```

> **Note**: the original WASP attacks no longer succeed against recent
> agents (Claude 4 and beyond) even without any defense — they're kept
> here for reference and for the strengthening pipeline
> (`red_team_inject.py`), which iteratively improves them.

Mislabel ablation — UCM defense but the issue description is **not**
marked untrusted (tests robustness to a labeling error). The script swaps
`gitlab-marker.js` for the run:

```bash
bash run_wasp_mislabel_experiment.sh
```

Plot the resulting attack-success / benign-utility comparison:

```bash
uv run python plot_wasp_results.py --results-dir results_wasp_attacks_strengthened
```

Override defaults via env vars (`MODEL`, `SYSTEM_PROMPT`, `N_VALUES`,
`INJECTION_FORMATS`, …) — see the headers of the `.sh` files.

## What each Python file does

**Injection + evaluation** (called by the runners):

- [wasp_inject.py](wasp_inject.py) — Pre-run step: pushes WASP attack
payloads into the live GitLab via REST API and writes the matching
WebArena task JSON. Reads from [configs/](configs/).
- [wasp_exfil_eval.py](wasp_exfil_eval.py) — Action-based evaluator for  
data-exfiltration attacks.
- [llm_judge_malicious_follow.py](llm_judge_malicious_follow.py) — LLM  
judge that decides whether the agent followed the injected instruction.

**Red-team helpers** (offline analyses; not part of the standard runner):

- [red_team_inject.py](red_team_inject.py) — Iterative attacker: a Claude red-teamer adapts its injection text after seeing the target agent's reasoning, until the agent gets fooled or the iteration budget is hit. Produces the strengthened attacks in  
[configs/wasp_gitlab_attacks_strengthened.json](configs/wasp_gitlab_attacks_strengthened.json).
- [red_team_qmodel.py](red_team_qmodel.py) — Replays existing agent +  
Q-Model traces and asks a red-teamer model to propose concrete attacks on the Q-Model (data leak, privilege escalation, etc.). Used for the Q-Model threat-model analysis in the paper, not for live attacks.

> **Note — red-teaming is model-specific.** The strengthened attacks in
> [configs/wasp_gitlab_attacks_strengthened.json](configs/wasp_gitlab_attacks_strengthened.json)
> were produced by red-teaming (`red_team_inject.py`) against **Claude
> Sonnet 4** (`claude-sonnet-4-20250514`). Whether an attack succeeds depends heavily on the target model: a
> payload strengthened for Sonnet 4 may fail to fool a different or newer
> model **even in the undefended baseline**.