# TASK {{TASK_ID}} - mature program contract (role: research architect)

Round {{ROUND}} | lane {{LANE}} ({{LANE_INTENT}}, min L{{MIN_LEVEL}}) | idea {{IDEA_ID}}
Winner {{WINNER}} | parents {{PARENTS}} | mode {{MODE}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Experiment purpose: {{EXPERIMENT_PURPOSE}} (exploratory lanes: see the exploratory
paragraph below - predictions/SOTA duties do NOT apply to you)
Surviving theory: {{THEORY_DOC}} | bundle: `{{BUNDLE_PATH}}`

## Purpose
Turn the winning, already-audited scientific program into a finite experimental
contract. You may add assumptions, numeric predictions, probes and implementation
detail. You may not alter its program, irreducible kernel, effect path or theory
role. Program/M/E (where applicable) and theory-derived DO# mappings are
digest-bound; theory role, target and rigor are independent fields frozen by
exact-copy validation.

Formal duty: {{FORMAL_DUTY}}
SOTA duty: {{SOTA_DUTY}}

## IDEA.md

Use these exact sections:

- `## Scientific program` - all learned/state/interface objects and the full
  training, inference, information and resource paths. Make a full rebuild
  implementable without pretending it is a local patch.
- `## Irreducible kernel` - KC# components, known primitives, support shell,
  non-reducibility argument and the load-bearing neutralization test.
- `## Effect and resource case` - KC#→intermediate→C# path; data/tokens/params,
  train+infer compute, teacher/API calls, selection budget and every confound.
- `## Causal derivation` - walk every A# from project fact to mechanism signal
  to numeric prediction; name the failure condition of each link.
- `## Prior-art boundary` - reconstruct nearest published old→new program and
  state the remaining kernel difference. Cite [E###] and core-work [M###].
- `## Theory consequences` when theory_role != none - implementation choices,
  rule-outs and discriminating predictions. For a theory-derived winner, walk
  every frozen DO# and its exact KC#/OP# mapping without changing it. Do not
  restate motivation.
- `## Formal statement` only for a formal lane, in the posed symbols.
- `## Predictions` - every registered P# and kill threshold.
- `## Mechanism check` for non-platform candidates with an
  irreducible/paradigm kernel - the cheapest attributable intermediate signal
  and which DAG decision it changes. An explicit waiver is legal when no
  intermediate can be observed without another training run, but it licenses
  performance recording only: mechanism status remains `unverified` and the
  node cannot receive scientific promotion under this claim.
- `## Falsification experiment` for non-platform candidates whose novelty kind
  is `known`/`composition`. This duty follows mechanism novelty, not L1--L4
  implementation scope.
- `## Implementation sketch` - KC#-addressed code responsibilities, stages,
  artifacts, resource caps and fixed/adaptive control.
- `## Risks` - strongest failure and resource-confound cases.

For a `platform` lane, replace the model-only kernel/effect/derivation/
predictions/falsification sections with these exact sections:

- `## Enabling capability` - the load-bearing service/tool/data capability and
  at least two concrete consumers it unlocks.
- `## Operational and resource contract` - executable interface, artifacts,
  latency/compute/API/storage caps, lifecycle and failure handling.
- `## Consumer/use falsification` - a concrete consumer test that fails if the
  platform is decorative, unusable, or does not change a downstream action.

Platform IDEA.md still includes `Scientific program`, `Prior-art boundary`,
`Implementation sketch`, and `Risks`; it omits the model-only sections above.

## IDEA.meta.json

The engine has PRE-FILLED this file with the frozen winner copies:
`sketch_id`, `experiment_purpose`, `change_scope`, `program`, `novelty`,
`effect_case`, `claim_scope`, `theory_role/rigor/obligations/target`,
`program_digest`, `kernel_hash`, `level` (and `diagnosis_digest` on repair
lanes). Do NOT edit
those fields - equality with the sealed winner is still validated and any
drift rejects the submit. Edit the file IN PLACE and add the fields below:

```json
{
  "idea": "{{IDEA_ID}}", "lane": "{{LANE}}",
  "title": "...",
  "theory_audit": {"status": "failed", "theory_doc": "rejected theory path",
                   "reason": "only when the engine downgraded an optional failed T claim"},
  "hypothesis_ids": ["repair only: H1"],
  "theory_doc": "surviving theory path when theory ran",
  "problem_doc": "posed problem path for formal lanes",
  "parents": [], "platforms_consumed": [],
  "enables": ["platform only: concrete future node/use 1",
              "platform only: distinct concrete future node/use 2"],
  "prior_art_card_ids": ["M###"], "bottleneck_ids": ["repair only: B#"],
  "dominance": {"metric": "efficiency result_key", "comparison": ">=|<=", "value": 0.0,
                "rationale": ">=30 chars"},
  "assumptions": [{"id": "A1", "statement": ">=30 chars", "source": "profile|dossier|theory|M###|OB###"}],
  "predictions": [{"id": "P1", "metric": "evaluation result_key", "comparison": ">=|<=",
                   "value": 0.0, "rationale": ">=40 chars"}],
  "mechanism_probe": {
    "signal": ">=30 chars", "expect": ">=15 chars",
    "mode": "same_run|existing_artifact|eval_intervention", "extra_eval_arms": 0,
    "artifact": "exact repo-relative .json path ('{seed}' placeholder ONLY when the node will run preplanned per-seed workflows - a candidate train/finetune mechanism under the preplanned replication policy; an eval-only/api/scout/platform context has no training seeds)", "required_fields": ["numeric_key"],
    "decision_rule": {"field": "numeric_key", "aggregation": "mean|median|min|max",
                      "comparison": ">=|<=", "threshold": 0.0},
    "decision": ">=50 chars", "value_of_information": ">=60 chars",
    "cheaper_modes_rejected": [{"mode": "<earlier mode>", "reason": ">=30 chars why it cannot answer the question"},
                               "...one row for EVERY mode earlier in evidence_policy.probe_mode_order than the chosen mode; [] only when the chosen mode is first"]
  },
  "attribution_waiver": ">=40 chars: why no measurable intermediate exists; performance-only, scientific promotion blocked",
  "nearest_published": {"paper": "E###", "difference": "research >=80 chars",
                        "adaptation": "engineering >=80 chars"},
  "sota_targets": [{"sota": "S###", "cell": "C#", "dimension": "effect|efficiency|modeling|generality",
                    "claim": ">=60 chars"}],
  "scaling": {"axis": "data|model|compute", "points": [">=2 named scale points"],
              "expect": ">=30 chars: the trend the mechanism predicts across the points",
              "value_of_information": ">=60 chars: which promotion/architecture decision this changes",
              "execution": "reuse_only: existing_artifact | budgeted/full: followup_node",
              "trigger": "budgeted/full only: after_positive_signal",
              "costly_arms": "reuse_only: 0 | budgeted/full: integer 1..max_scaling_costly_arms"},
  "siblings_distance": [{"node": "N###", "difference": ">=40 chars"}, "...one entry for EVERY node in the bundle's 'Sibling nodes' block - the duty is exhaustive"],
  "repeat_rule": {"cell": "decision C# only", "band": 0.02, "when": "decision_within_band", "max_repeats": 1},
  "external_interface_changed": false, "metric_bridge_needed": false
}
```

EXPLORATORY lanes (`experiment_purpose: "exploratory"`, admitted as such at
round opening): you are a declared scout. OMIT `predictions` and
`sota_targets` entirely and skip the `## Predictions` section - do NOT invent
numeric foresight to look rigorous; that fabrication is exactly what this tier
exists to eliminate. Keep every other duty (novelty, effect/resource case,
prior-art boundary). Your results will be observations only: no frontier, no
records, promotion not_applicable, and your conclusion MUST emit >= 1
phenomenon-ledger observation (OB###) - that is your entire deliverable. A
later confirmatory candidate (`confirmatory_of: your node`) may re-run this
kernel under full pre-registration to put the effect on the record.

`repeat_rule` (OPTIONAL, single-run projects only): pre-registers "if the one
measured delta lands within `band` of a decision line (0 / min_improvement /
-noninferiority_margin / goal_threshold), offer the user ONE bought-back
repeat; the verdict then settles once on the two-run mean". `band`, when
given, must be a POSITIVE number (0 is rejected); OMIT the key entirely - do
not write 0 - to use the cell's recorded noise floor; with neither, the
registration is rejected (an undefined "on the line" is empty ceremony). Illegal under preplanned
multi-seed replication - that tier already measures a real interval. This is
the only sanctioned second measurement; adaptive rerun-until-clear stays
forbidden.

Platform ideas omit `effect_case`, `claim_scope`, metric `predictions` and
model-only probe fields, and list >=2 concrete `enables` in the meta JSON.
`mechanism_probe.decision_rule` is mandatory when a probe is present. It must
name one `required_fields` key and use exactly either
`{field,aggregation,comparison,threshold}` for `>=|<=`, or
`{field,aggregation,comparison,lower,upper}` for `between` with `lower < upper`.
This numeric predicate, not later interpretation, will settle the mechanism
status from sealed observations.
An `attribution_waiver` is not a softer probe or a reviewer-discretion escape:
it must replace `mechanism_probe`, preserves any observed performance result,
and necessarily blocks `scientific_promotion_status=met` for the research
claim.
The `scaling` object stays
optional and follows the configured policy: under `scaling_mode=off` the key
is rejected outright; under `reuse_only` only `execution: "existing_artifact"`
with `costly_arms: 0` is legal; under `budgeted|full` it must declare
`execution: "followup_node"`, `trigger: "after_positive_signal"` and
`costly_arms` 1..`max_scaling_costly_arms`. Never hide costly
scale runs in the primary node. Numeric predictions refine the already-frozen
minimum-worthwhile effect case; they may not change its target cells or claim
breadth. `sota_targets` come from the winner audit's `frontier_refs`, not from a
post-selection search. Every `sota_targets` row must include its exact C#
`cell`, matching both the frozen claim scope and the referenced SOTA entry.
`nearest_published` is collision evidence: current papers
need not be the source of the novel kernel. The theory-derived
`theory_obligations` array is part of the winner's digest-bound executable
contract; copy its structure and values exactly and omit it on other routes. If
the engine records an optional theory downgrade, set `theory_role=none`, omit
other theory fields, and preserve the failed theory in `theory_audit`; the M/E
program remains unchanged.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
