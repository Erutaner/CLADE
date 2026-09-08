# TASK {{TASK_ID}} - plan_node (role: architect)

Round: {{ROUND}} | lane: {{LANE}} | idea: {{IDEA_ID}} (approved) | role: {{NODE_ROLE}} | purpose: {{EXPERIMENT_PURPOSE}}
Parents: {{PARENTS}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}` (includes infra facts and the shared-artifact registry)

## Why
`NODE_SPEC.json` is the executable and resource contract for this node. Parents,
level, scientific claim and any theory-derived DO# -> KC#/OP# mappings are
already frozen. Here you decide only how the finite candidate-producing
procedure is split into recoverable stages.

## Experiment class
Declare `train|finetune|inference|api|data|analysis`. Train, finetune and data
nodes require a workflow. Inference, API and analysis nodes may be evaluation-
only, or may use a workflow for bounded prompt search, decoding optimization or
other finite procedures.

## What counts as one stage
A stage is one scheduler-visible job and recovery/resource boundary. Split when
there is a stable downstream handoff, a material execution/resource change, or
a need to pause/retry the part independently. Do not split every optimizer
alternation, client, agent, candidate, task batch or search iteration; those are
internal to one bounded procedure unless they create a stable handoff.

Stages are listed in topological order and execute sequentially. Branch/merge is
represented by later stages consuming several earlier artifacts. This engine
does not orchestrate clients or candidates as an internal sub-DAG.

## Algorithm work versus evidence work
Use this removal test: if removing a model/candidate/run changes or prevents the
delivered method, it is algorithmic work and may live inside the workflow. If
removing it only weakens comparison, attribution or confidence, it is an extra
evidence arm and must not be hidden here.

- `control.mode=fixed`: the launch follows a frozen procedure.
- `control.mode=preregistered_adaptive`: observations may choose later actions,
  but the controller, search space, objective, caps and stopping conditions are
  frozen before launch. Changing those after seeing results creates a child node.
- `control.multiplicity=algorithmic`: several models/candidates/runs are intrinsic
  to the delivered method; explain `why_multiple` and write a ledger.

Seed repetition is not stage multiplicity. `control.multiplicity` is only
`single|algorithmic`; project-approved seeds repeat the complete workflow.

`evidence_plan` contains only cheap same-run/existing-artifact/eval-only checks.
It cannot authorize training. Search required to produce the candidate is not
an ablation; comparing search algorithms or removing components is evidence and
may not be hidden in a candidate workflow.

Training seeds and ablation are separate frozen contracts:
- For every `train|finetune` node, `training_replication` records what actually
  runs. Under project policy `record_only`, use `single`, exactly one explicit
  seed and no aggregation. Under `preplanned`, an ordinary candidate uses the
  exact approved count and `mean|median`. Seed 1 traverses every stage, then
  seed 2 traverses every stage, and so on; evaluation exposes one final result
  per seed. Every stage `launch` and `metrics_file` must contain `{seed}`;
  ledgers, produced URIs and stage keys also contain it when present. This both
  injects the seed and prevents cross-run overwrite. A preplanned workflow may
  not use continuation gates, because that would let some seeds skip later
  stages and cease to be a complete-run protocol. Never create repeats because
  a result looked promising or because mean/std is desired.
  If a failed run requires a code change, the engine snapshots and supersedes
  earlier seed-lane evidence, then restarts the entire seed set; it never mixes
  results from two implementations in one aggregate.
- A `targeted_ablation` copies the approved idea's `ablation` object exactly.
  Its training replication is the approved design's `costly_runs`: one run is
  `single` with one recorded seed; more than one is `preplanned` with exactly
  that many seeds and `mean|median` aggregation, every seed traversing every
  stage. Every stage is `fixed/single`; sequential stages may express real
  handoffs in the one workflow, but none may adaptively search or produce
  multiple models. After implementation, a no-compute controlled-change audit
  checks the exact factor and held constants before the workflow gate.
- A `diagnostic_probe` copies the approved `probe` object exactly (engine
  pre-filled); planned stage+eval budgets must fit inside `probe.budget`.
  Prefer an evaluation-only plan (`stages: []`) on existing artifacts.
- A `maintenance` node copies the approved `maintenance` object exactly
  (engine pre-filled); its workflow mirrors the parent's so parity can settle
  on comparable evaluation. It cannot contain a sweep, scaling, nested
  mechanism probe, or seed cross-product. Do not rerun the parent: its existing
  result is the reference.
- Probe and maintenance workflow gates are MANUAL in every autonomy mode,
  full_auto included. A targeted ablation's gate follows the allowance the
  user pre-authorized (`evidence_policy.ablation.budget_multiple` x the
  parent's own cost): inside it the ordinary autonomy policy applies, above
  it the user decides.

## Resource and trace contract
Every stage and the standard evaluation declare finite caps in `budget.limits`.
At least one unit of each must occur in the user-confirmed project-wide
`resource_contract`. Units are
extensible (`gpu_hours`, `wallclock_minutes`, `training_tokens`,
`candidate_evaluations`, `model_calls`, `api_tokens`, etc.); stage count is not a
cost estimate.

For every non-platform node, `eval.resource_accounting` also freezes how each
of the {{RESOURCE_AXES_COUNT}} scientific resource axes ({{RESOURCE_AXES}}) will be measured. Each row uses exactly
`method` and a substantive `description`. Legal methods are
`dataset_manifest|scheduler_ledger|model_profiler|runtime_profiler|api_meter|selection_ledger`.
This is an execution plan, not a future analyst estimate: the eval runner emits
the {{RESOURCE_AXES_COUNT}} raw intervals, the engine seals the receipt, and the analyst cannot
edit either source.

The completed stage metrics JSON must contain:

```json
{"seed": 11,
 "summary": {"loss": 0.1},
 "usage": {"gpu_hours": 3.2},
 "stop_reason": "required for preregistered_adaptive only"}
```

This file is one stage result for one seed. It never contains a `replicas[]`
batch. The stage cap is per seed execution; the workflow approval displays and
accounts the sum across all stages and all approved seeds.

Declared stage/eval `metrics_file` and `ledger_file` values are producer landing
paths. They may be reused by later invocations because, during run absorption,
the engine validates the reported content and ingests it into
`.evo/runs/<RUN>/evidence/` before publishing any later handoff or evaluation
input. Do not design downstream consumers around mutable landing filenames.

Usage above a declared cap parks the evidence (the RUN's execution stands,
nothing is rerun); every recorded number stays the actual measurement. Caps
are notebook numbers: derive each `budget.limits` value from a worst-case
estimate (worst case x1.3) and state the basis in the spec, and when real
timing later proves a cap mis-derived, correct it on record - `evo amend` the
spec's `budget.limits` with the reason, then `evo run-reconcile` the parked
RUN so the same evidence is adopted. The same notebook covers the rest of
the spec until production launches: the evidence plan, the cost class, the
training replication, the smoke and rehearsal steps, any stage or evaluation
command that has not run yet. What launched is history (a code fix is an
implementation revision); the node's identity (role, parents, level, program
digest, kernel ids, workdir) never changes. Adaptive or algorithmically-multiple
stages also declare `ledger_file`; it records ordered choices/components,
observations and the stopping event.

## Optional scientific continuation gate
Use a continuation gate only for a cheap measurement of a **necessary,
pre-registered A# assumption**: if it misses, the remaining workflow has no
scientific information value. It is not an early-exit target, a way to hide a
bad final score, or a replacement for evaluation. The engine computes the
decision from numeric `summary` values; the run must not author `passed` or
`KILL` fields. A gate must precede at least one later stage, and its predicates
cannot reuse configured target or guardrail result keys.

```json
"continuation_gate": {
  "id": "prerequisite_holds",
  "aggregation": "all",
  "predicates": [
    {"metric": "stage_local_measurement", "comparison": ">=", "value": 0.7}
  ],
  "assumptions": ["A1"],
  "on_miss": "stop_node",
  "rationale": ">=40 chars: why falsifying A1 makes every remaining stage uninformative"
}
```

On a miss, execution is still successful. The engine retains the metrics,
does not register the current candidate artifacts or advance the cursor, skips
remaining stages and final evaluation, then requires a scientific conclusion
with verdict `screened_out`. It records the falsified prerequisite as
observations and lessons without pretending unreached final predictions were
refuted.

Artifacts are generic: weights, data, prompt/config, a collection of models or
an opaque resumable state are all legal. A producing stage needs a canonical
`stage_key` including every factor that changes interchangeability, including an
adaptive controller/search space/budget where applicable. Consume an AVAILABLE
matching artifact or write a substantive `reuse_waiver`.

## Do
Complete `NODE_SPEC.json` IN PLACE. The engine has PRE-FILLED the frozen idea
copies: `role`, `experiment_purpose`, `parents`, `level`, `program_digest`,
`kernel_ids`, `program_ir`, `novelty_kernel`, `effect_case`,
`theory_obligations`, the six copied `probe_execution` fields, and (for a
targeted ablation) `ablation`. Do NOT edit those - equality with the approved
idea is still validated. Add the planning fields:

```json
{
  "title": "<short node title>",
  "code_parent": "<required by node-role rules; when a model parent's kernel was REFUTED by its ablation, that parent's control version (the ablation node) is also legal here and is the program to build on>",
  "experiment_class": "train|finetune|inference|api|data|analysis",
  "cost_class": "light|medium|heavy",
  "workdir": "workareas/<node_slug>",
  "evidence_plan": {
    "extra_eval_arms": "<exactly mechanism_probe.extra_eval_arms>",
    "declared_checks": ["mechanism_probe when measured in this node"],
    "value_of_information": "required only when extra_eval_arms > 0"
  },
  "training_replication": {
    "mode": "single|preplanned",
    "runs": 1,
    "seeds": [11],
    "aggregation": "none|mean|median",
    "source": "workflow|existing_artifacts"
  },
  "probe_execution": {
    "mode": "exactly the approved same_run|existing_artifact|eval_intervention",
    "signal": "exactly mechanism_probe.signal",
    "expect": "exactly mechanism_probe.expect",
    "artifact": "exact repo-relative JSON path; same_run preplanned training uses {seed}",
    "required_fields": ["exact numeric JSON keys from mechanism_probe"],
    "decision_rule": {"field": "COPY mechanism_probe.decision_rule field EXACTLY",
                      "aggregation": "COPY EXACTLY", "comparison": "COPY EXACTLY",
                      "threshold": "COPY EXACTLY; between instead copies lower and upper"},
    "producer_stage": "same_run only: workflow stage name, or evaluation for an evaluation-only node",
    "smoke_artifact": "same_run/eval_intervention: distinct repo-relative JSON created by smoke",
    "command": "eval_intervention only: exact eval-only command; no training"
  },
  "ablation": "targeted_ablation only: exact copy from approved idea; omit for candidates",
  "smoke_plan": [
    {"name": "imports", "cmd": "...", "timeout_s": 120},
    {"name": "tiny_end_to_end", "cmd": "...", "timeout_s": 900,
     "must_exist": ["probe_execution.smoke_artifact when applicable"]}
  ],
  "cost_estimate": {
    "per_unit": {"gpu_hours": 9.5},
    "basis": ">=20 chars: what the forecast rests on - the rehearsal's measured pace, a prior run of this size, scale reasoning; say what it excludes"
  },
  "refuted_kernel_disposition": [
    {"parent": "N###", "action": "built_on_control|removed|replaced|reclaimed",
     "note": ">=20 chars: ONLY when a model parent's kernel was refuted by its ablation - what this node did about that kernel"}
  ],
  "rehearsal": {
    "command": "<one command that runs the WHOLE workflow tiny (a few steps per stage + the real evaluation) on the real platform>",
    "timeout_s": 3600,
    "description": ">=40 chars: how the tiny pass traverses every stage AND how each consumer re-reads its input artifact"
  },
  "workflow": {"stages": [
    {
      "name": "candidate_search",
      "purpose": "produce the selected candidate under a frozen search policy",
      "launch": "<one top-level job command>",
      "metrics_file": "<repo-relative JSON path>",
      "ledger_file": "<required here because this procedure is adaptive/multiple>",
      "control": {
        "mode": "preregistered_adaptive",
        "multiplicity": "algorithmic",
        "controller": "<frozen rule mapping observations to the next action>",
        "stopping_conditions": ["candidate_evaluations cap is reached", "registered convergence rule fires"],
        "why_multiple": "selection among candidates is the algorithm that creates the delivered architecture"
      },
      "budget": {"limits": {"gpu_hours": 24, "candidate_evaluations": 50}},
      "continuation_gate": {
        "id": "candidate_viable",
        "aggregation": "all",
        "predicates": [{"metric": "validation_score", "comparison": ">=", "value": 0.7}],
        "assumptions": ["A1"],
        "on_miss": "stop_node",
        "rationale": "The selected candidate must clear this pre-registered viability condition or finalization cannot test the claimed mechanism."
      },
      "stage_key": "search|data=...|objective=...|controller=...|space=...|budget=...",
      "requires_llm": false,
      "requires_services": [],
      "produces": [{"name": "selected candidate", "kind": "weights", "uri": "<unique URI>"}],
      "consumes": []
    },
    {
      "name": "finalize",
      "purpose": "convert the selected candidate into the evaluated deliverable",
      "launch": "<command>",
      "metrics_file": "<repo-relative JSON path>",
      "control": {"mode": "fixed", "multiplicity": "single"},
      "budget": {"limits": {"wallclock_minutes": 60}},
      "stage_key": "finalize|candidate=...|recipe=...",
      "produces": [{"name": "final model", "kind": "weights", "uri": "<unique URI>"}],
      "consumes": [{"stage": "candidate_search"}]
    }
  ]},
  "eval": {
    "run": "<command>",
    "metrics_file": "<all configured result keys>",
    "budget": {"limits": {"wallclock_minutes": 30}},
    "resource_accounting": {
      "data_examples": {"method": "dataset_manifest", "description": ">=40 chars: exact examples counted and deduplication rule"},
      "train_tokens": {"method": "scheduler_ledger", "description": ">=40 chars: tokens accumulated over the complete workflow"},
      "parameters": {"method": "model_profiler", "description": ">=40 chars: parameter inclusion and sharing convention"},
      "train_flops": {"method": "model_profiler", "description": ">=40 chars: profiler/ledger aggregation over training"},
      "infer_flops": {"method": "model_profiler", "description": ">=40 chars: per declared inference protocol"},
      "latency_ms": {"method": "runtime_profiler", "description": ">=40 chars: hardware, batch, warmup and interval rule"},
      "teacher_calls": {"method": "scheduler_ledger", "description": ">=40 chars: complete counted call boundary including zero"},
      "api_calls": {"method": "api_meter", "description": ">=40 chars: provider request accounting boundary"},
      "selection_budget": {"method": "selection_ledger", "description": ">=40 chars: candidates/queries charged by the frozen selector"}
    },
    "background": false,
    "requires_llm": false,
    "requires_services": [],
    "harness": {"type": "optional: standard|physical|interactive",
                "trials": "physical/interactive only: preregistered integer >= 1",
                "reset": "physical/interactive only: manual|auto",
                "nondeterminism_note": "physical/interactive only: >=40 chars: what varies between trials and why seeds cannot control it"},
    "judge": {"model": "<optional pinned judge>", "params": {"temperature": 0}},
    "protocol": {"<optional arena protocol>": "must equal baseline; type=streaming adds two duties (see notes)"},
    "transductive": {"cells": ["optional block: configured C# cells whose unlabeled test inputs the node consumes"],
                     "consuming_stage": "declared workflow stage that consumes them",
                     "verifier_label_free_argument": ">=60 chars: why the training signal uses no test labels"}
  },
  "enables": ["platform nodes only"]
}
```

Notes:
- `probe_execution`: the engine pre-filled the six frozen predicate fields
  (`mode`, `signal`, `expect`, `artifact`, `required_fields`,
  `decision_rule`). Planning ADDS only the producer/command wiring
  (`producer_stage` / `command` / `smoke_artifact`); it cannot tune the
  predicate after seeing data.
- A fixed one-model stage uses `fixed/single` and needs no ledger.
- A fixed ensemble, merge over several inputs, or co-trained model set uses
  `fixed/algorithmic`, explains why the multiplicity is intrinsic, and logs it.
- A NAS/BO/active-selection/self-play controller normally uses
  `preregistered_adaptive`; its internal candidate count does not become child
  nodes. Comparing controllers does.
- A preplanned training workflow keeps ordinary stage controls. Every seed
  traverses the entire ordered stage list; `{seed}` appears in commands and
  output paths. Stage caps apply once per seed and the approval view multiplies
  them by the exact seed count.
- Omit `training_replication` for non-training experiment classes. A trained
  baseline that already exists uses `source:existing_artifacts`; a workflow
  uses `source:workflow`.
- Omit `probe_execution` when the idea registers no probe.
  `same_run` names the stage that writes the real JSON (or `evaluation` for an
  evaluation-only node). `existing_artifact` points to an already valid JSON.
  `eval_intervention` is one capped eval-only arm and may not invoke training.
- `consumes` uses `{"stage":"earlier_name"}` or `{"artifact":"AR###"}`.
- Top-level `rehearsal` is REQUIRED when `project.rehearsal=full_chain` for
  every staged non-baseline spec; omit it otherwise and for the baseline.
  `timeout_s` is an integer in [1,86400]. The block may not contain `status`,
  `pass`, `passed`, `evidence` or `exit` keys: the spec owns the command, the
  engine owns the outcome.
- Any name in `requires_llm`/`requires_services` that the infra facts pin with
  `pinning: "recorded"` is a drifting external surface: some stage must then
  produce a `kind: "service_snapshot"` artifact or consume a registered
  service_snapshot artifact, or the spec carries top-level
  `"service_snapshot_waiver": ">=40 chars why replayable comparison is
  impossible or unneeded"`.
- An `eval.protocol` with `type: "streaming"` must set `episode_order_file` to
  an EXISTING repo-relative file (no absolute paths, no '..'; its bytes are
  sealed with the evaluation) and `sequential_dependence: true` - episode
  order changes the numbers and the uncertainty method must account for it.
- `eval.transductive`, when present, must name configured C# `cells`, a
  `consuming_stage` declared in the workflow, and a
  `verifier_label_free_argument` of >= 60 chars.
- Copy `theory_obligations` exactly for a theory-derived candidate and omit it
  otherwise. Stage decomposition may implement the mapped operators but cannot
  rename DO#/KC#/OP# ids, change refs or rewrite satisfaction after approval.
- Top-level `train`, `experiment_role`, `main_training_paths` and
  `extra_train_arms` are not part of the schema.
- After acceptance this file is notebook material within limits: caps, the
  smoke plan, the rehearsal command, `cost_class`, `evidence_plan`,
  `training_replication`, `service_snapshot_waiver` and the commands of stages
  that have not launched yet may be corrected with `evo amend --path <this
  spec> --from <edited copy> --reason ...` (a `cost_class` change before launch
  re-derives the node's fidelity duty). The engine-owned copies of the idea
  (`effect_case`, `ablation`, `probe`, `maintenance`, `evaluation_scope`,
  `theory_obligations`) are corrected on the idea meta and propagated here - an
  `ablation.costly_runs` change rewrites `training_replication` to one complete
  seed run per costly run. Identity fields, the evaluation protocol and any
  launched stage are history; each refusal names its door.
- Live human/robot collection, indefinite deployment and cross-organization
  orchestration are outside this engine. Use a finite, already-accessible
  dataset/replay instead.

`cost_estimate` (recommended for every node that spends): your declared caps
are a promise; the estimate is your forecast of what one full run will really
cost, per resource unit the project tracks, with the basis it rests on. Use
the rehearsal's measured pace where you have it (it ran the real launch
configuration for a few steps), a prior run of this size, or scale reasoning
- and say what the forecast excludes. The engine prints it on the workflow
gate next to the declared caps, what the rehearsal actually took, and the
user's node ceiling; it never extrapolates on its own. A declared cap or an
estimate above the ceiling puts the gate in front of a person in every
autonomy mode; nothing else about the estimate is judged. Correct it before
launch with `evo amend` when the rehearsal teaches you better.

`refuted_kernel_disposition` is owed only when a model parent's kernel was
refuted by its ablation (the FRONTIER row says `refuted (via N###; build on
N###)` or `refuted (via N###; remove ...)`). Say in one line what this node
did about that kernel: `built_on_control` (then `code_parent` is the control
version), `removed`, `replaced` (say what with) or `reclaimed` (it is this
idea's own bet again and the ablation will test it again). The workflow gate
prints the line and the fidelity audit checks the code against it; the
engine records, people verify.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
