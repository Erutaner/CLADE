# TASK {{TASK_ID}} - baseline_spec (role: analyst)

Node: {{NODE}} (the unmodified project) | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
The baseline anchors every future comparison. Its spec teaches the engine how to
smoke-test and evaluate this project; every later node's spec follows this shape.

## Do
Write `.evo/nodes/{{NODE}}/NODE_SPEC.json`:

```json
{
  "title": "Baseline (unmodified project)",
  "role": "baseline",
  "parents": [],
  "code_parent": null,
  "level": 0,
  "experiment_purpose": "candidate",
  "experiment_class": "train",
  "cost_class": "light",
  "workdir": "<code_root, usually .>",
  "evidence_plan": {"extra_eval_arms": 0, "declared_checks": []},
  "training_replication": {
    "mode": "single|preplanned according to the approved project policy",
    "runs": 1,
    "seeds": ["explicit recorded seed"],
    "aggregation": "none|mean|median",
    "source": "existing_artifacts|workflow"
  },
  "smoke_plan": [
    {"name": "imports", "cmd": "<python -c 'import ...' or equivalent>", "timeout_s": 120},
    {"name": "tiny_eval", "cmd": "<eval on a tiny slice>", "timeout_s": 600,
     "must_exist": ["<produced file>"]}
  ],
  "eval": {"run": "<command that produces metrics>",
           "metrics_file": "<path to metrics.json it writes>",
           "budget": {"limits": {"wallclock_minutes": 30}}}
}
```

- Omit `workflow` when a trained baseline already exists (normal case). If the
  baseline must first be produced, declare canonical `workflow.stages` with the
  same purpose/control/budget/result contract used by later nodes. Top-level
  `train` is not a v9.2 schema field.
- The baseline obeys the same user-approved training-seed protocol as ordinary
  candidates. `record_only` records the existing run's one seed and never
  launches repeats. `preplanned` exposes every approved seed/run, either from
  existing artifacts or by sending every seed through the complete workflow.
  In the latter case every stage command/output path uses `{seed}`, stage caps
  are per seed, and approval shows their sum. Do not derive repeats from mean/std.
- `eval.metrics_file` must be a JSON file containing every evaluation-cell
  `result_key` declared in the contract. If the project reports numbers some other way, `eval.run` should be a
  small adapter script you add to the repo that writes that JSON.
- `eval.resource_accounting` must declare every configured resource axis
  ({{RESOURCE_AXES_COUNT}} of them: {{RESOURCE_AXES}})
  as `{"method": "dataset_manifest|scheduler_ledger|model_profiler|runtime_profiler|api_meter|selection_ledger", "description": ">=40 chars"}`,
  and the evaluator's RAW output must emit `_usage` plus
  `_resource_measurements.{axis}={lower,upper}` for each declared axis - the
  adapter is sealed at implementation, so make it complete now.
- `eval.budget.limits` must include at least one unit from the user-confirmed
  project resource contract. The resulting metrics JSON reports actual use in
  `_usage` so baseline evaluation is charged like every later node.
- smoke_plan commands must be fast (< ~10 min total) and runnable on this machine
  exactly as written; the ENGINE executes them, not you.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
