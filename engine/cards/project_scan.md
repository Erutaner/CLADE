# TASK {{TASK_ID}} - project scan (role: discovery interviewer)

Project: {{PROJECT_NAME}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
The engine must inspect the supplied project before freezing its dataset/task/
metric and resource contract. This pass extracts facts and questions; it does
not pretend that a config skeleton is already the truth.

## Do
1. Ask the user for any project/data/evaluation/platform documents and the code
   roots that should be inspected. Read every relevant supplied path, then scan
   the repository entry points, dataset loaders, evaluation code, launchers and
   existing result files. If the user has no documents, record that explicitly
   and use code as evidence.
2. Ask for project-wide hard resource limits in units the project actually
   consumes, such as `gpu_hours`, `training_tokens`, `api_tokens`, or
   `wallclock_minutes`. These are total limits for the whole evolution, not a
   guess made later by a node planner.
3. Inspect the actual training procedure and stated claim, then make two
   recommendations for the configure interview:
   - **Training-seed replication**: recommend `record_only` unless full
     retraining variability is itself decision-relevant (for example the claim
     is about typical-run stability, known training instability is comparable
     to the expected gain, or the field protocol requires repeats and the user
     can afford them). Domain name alone is not enough. Record randomness
     sources, claim relevance and repeat cost. `record_only` still records the
     one seed used; it creates no repeats.
   - **Ablation**: recommend `targeted` only if this project could plausibly
     face a causal fork where one changed-component run would change the next
     DAG decision and cheap logs/eval interventions may be insufficient.
     Otherwise recommend `off`. This is permission for later manual proposals,
     never an automatic duty.
4. Write `.evo/profile/PROJECT_DISCOVERY.json`:
```json
{
  "project": {"name": "...", "goal": "...", "docs": [], "code_roots": ["."]},
  "scanned_paths": ["README.md", "eval.py"],
  "inventory": {"datasets": [], "tasks": [], "metrics": [], "cells": []},
  "training_stochasticity": {
    "recommended_mode": "record_only|preplanned",
    "randomness_sources": ["initialization", "data order"],
    "claim_and_cost_reasoning": ">=40 chars: process + claim + field norm + cost"
  },
  "ablation_assessment": {
    "recommended_mode": "off|targeted",
    "reasoning": ">=40 chars: likely decision value versus training cost"
  },
  "unknowns": [{"id": "U1", "question": "...", "why_it_matters": "...", "provisional_default": "..."}],
  "resource_contract_draft": {"limits": {"gpu_hours": 100}, "basis": "user stated ..."},
  "engine_fit": {
    "assumptions": [
      {"id": "F0", "verdict": "holds|violated|uncertain", "evidence": ["path"],
       "note": ">=40 chars: why, from the evidence",
       "consequence_if_wrong": "required when violated/uncertain: how the evolution would repeatedly fail"},
      {"id": "F5", "verdict": "...", "evidence": ["..."], "note": "..."},
      {"id": "F6", "verdict": "...", "evidence": ["..."], "note": "..."},
      {"id": "F7", "verdict": "...", "evidence": ["..."], "note": "..."}
    ],
    "overall": "fit | degraded | unfit  (derived: F0 violated = unfit; any other violated/uncertain = degraded; all holds = fit)"
  },
  "readiness": {
    "mode": "certified_running | needs_preparation",
    "basis": ">=40 chars: what the user said / what the scan observed",
    "worklist": [{"item": "wire dataset X", "why": "code has no loader for it"}]
  }
}
```
   Inventory records should carry a `source` path. Empty inventory lists are
   legal only when the missing facts are named in `unknowns`; never invent a
   dataset, task, metric direction, protocol or success threshold.

   **engine_fit** judges the engine's own load-bearing assumptions against
   THIS project, once, at the entrance - so a mismatch is a clear early
   conversation instead of months of repeated validation failures:
   - **F0 task class (hard)**: this is an ML project/model to ITERATIVELY
     IMPROVE - a project entity exists (code or a named runnable system), the
     user can point at a data source (even if not wired yet), and the goal is
     measured improvement, not a one-shot deliverable (a literature survey, a
     report, a from-scratch build with nothing to run are all F0 violations).
   - **F5 iteration cadence**: the work decomposes into rounds of candidate
     nodes whose single runs finish in hours-to-days, not weeks.
   - **F6 decidability**: node success can be judged by pre-registered
     numeric rules; human review is the exception, not every node.
   - **F7 harness shape**: evaluation fits standard/physical/interactive
     harness semantics the engine supports.
   Judge honestly; `violated` does NOT end the project by itself - a gate
   shows the user the exact gap and THEY decide (proceed on record / stop).
   **readiness** asks the user whether the project already RUNS end-to-end
   here (certified_running) or needs a preparation pass first
   (needs_preparation + a concrete worklist); preparation is authorized
   constructive work, so "no evaluation exists yet" belongs in the worklist,
   never in a refusal.
5. Write `.evo/profile/PROJECT_DISCOVERY.md` with exactly these sections:
   `## Sources scanned`, `## Draft evaluation map`,
   `## Draft evidence policy`, `## Unresolved user questions`, and
   `## Draft resource envelope`.
   Cite factual claims using `[src: repo-relative-path]`.
6. This is a draft. The following configure task resolves the listed questions
   with the user and builds the complete contract. A mandatory user gate after
   docs/code validation freezes both success and resource rules; configured
   automation starts only after that approval.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
