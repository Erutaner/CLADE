# TASK {{TASK_ID}} - synthesize complete programs (role: research architect)

Round: {{ROUND}} | lane: {{LANE}} | origin: {{SEARCH_ORIGIN}} | intent: {{LANE_INTENT}}
Minimum implementation scope: L{{MIN_LEVEL}} | parents: {{PARENTS}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Carbon-copy duty: {{COPY_DUTY}}
Bundle: `{{BUNDLE_PATH}}`

## Objective

Produce {{SKETCH_COUNT}} genuinely different, complete scientific programs that
could plausibly create a resource-normalized frontier gain. The search object is
the forward computation itself, not a story about editing the incumbent. State
the learned objects, train/inference operators, irreducible novelty kernel, and
the typed path by which that kernel can change a registered C# result.

`change_scope` and novelty are independent. L1--L4 says how much executable
program is replaced; it does not certify originality. In research mode every
non-platform candidate, including an L1/L2 candidate, needs an `irreducible` or
`paradigm` kernel. A full-program rebuild is legal and need not preserve any
internal object or operator from the baseline. (Exception: a carbon-copy lane -
scaling follow-up / confirmatory re-run - copies its source kernel VERBATIM and
uses that route's registered `novelty.kind` from its COPY duty, e.g.
`scaling_extension`; the headline rule above does not apply to it.)

Platform candidates are auxiliary experimental infrastructure rather than
model-effect claims: omit `effect_case` and `claim_scope`. Their program must
still make the enabling computation and resource path explicit; later stages
judge concrete consumers/capabilities instead of inventing a model comparator.

For every non-platform candidate, `effect_case.comparator_id` is the frozen
causal and resource reference: `baseline` or an exact scientific parent of the
lane. A root lane therefore uses `baseline`. A stronger sibling, off-lineage
node, or current frontier node is promotion evidence, not a legal replacement
for that reference. Separately, `predicted_gain` must explain whether the
candidate's absolute expected results and resource vector could be a
non-dominated improvement over the strongest protocol-compatible observations
provided in the bundle. A comparator can be valid while that independent
promotion case fails; narrow the claim or reject the candidate rather than
rewriting its ancestry.

For `wildcat|moonshot`, read the bundle's lane admission policy literally. A
`full_program + paradigm` root is a first-contact program: after the same M/E,
prior-art, scope and resource hard gates, a credible baseline-relative case may
justify its first experiment even when a mature many-generation N# remains
stronger. That exception does not apply to an irreducible local/subsystem idea
or to any ordinary exploit/reform/hybrid candidate.

The routes differ intentionally:

- `repair`: bind the method-blind diagnosis, H# hypotheses, and the M# core-work
  audits already read for this lane. Do not turn an explanatory diagnosis into
  the novelty claim.
- `constructive`: synthesize from task, data, evaluation, resource contracts,
  and the code-grounded `BASELINE_PROGRAM.json`. The set is frozen before the
  lane-specific literature reader runs. Supply precise collision queries.
- `core_synthesis`: use only the engine-projected anonymous `CORE_PALETTE` in
  the bundle. Bind its digest and transform at least two CP# operational cores
  into one new load-bearing relation. Do not inspect the provenance sidecar or
  reconstruct source identities. The palette supplies raw computational
  invariants, not a novelty verdict; supply post-freeze collision queries.
- `theory_derived`: instantiate the surviving theory's executable obligations.
  Every candidate uses `theory_role=derivational`, binds the theory digest and
  maps the complete surviving DO# set to its real KC#/OP# entries.

## Output

Write `PROGRAMS_c#.json` at the exact output path. Unknown fields are rejected.

```json
{
  "schema_version": 2,
  "lane": "{{LANE}}",
  "search_origin": "{{SEARCH_ORIGIN}}",
  "baseline_program_digest": "copy VERBATIM from the bundle's `Frozen digests` block (engine canonical-JSON hash - NOT the file's raw sha256)",
  "diagnosis_digest": "repair only: copy from the Frozen digests block",
  "core_palette_digest": "core_synthesis only: copy from the Frozen digests block",
  "theory_digest": "theory_derived only: copy from the Frozen digests block",
  "sketches": [{
    "sketch_id": "K1",
    "change_scope": "configuration|local|subsystem|full_program",
    "program": {
      "scientific_parents": ["exact ordered model-parent N# ids; [] for a root"],
      "objects": [
        {"id": "O1", "kind": "input|state|representation|prediction|supervision|memory|latent|controller|interface|artifact|other",
         "semantics": ">=30 chars: mathematical/computational meaning"}
      ],
      "operators": [
        {"id": "OP1", "kind": "transform|objective|estimator|update|transition|inference|routing|memory|data|system",
         "phase": "train|infer|both", "semantics": ">=50 chars: executable action",
         "reads": ["O1"], "writes": ["O2"], "depends_on": [],
         "iteration": {"kind": "recurrent|fixed_point|adaptive_search|self_play",
           "state_objects": ["O2"], "update_order": ">=30 chars",
           "termination": ">=30 chars", "max_steps": 100}}
      ],
      "training_process": ">=40 chars: full objective/estimator/update path",
      "inference_process": ">=40 chars: full deployed prediction/generation path",
      "information_flow": ">=40 chars: dependencies, feedback, state lifetime",
      "resource_model": ">=40 chars: how the complete program consumes resources"
    },
    "novelty": {
      "kind": "known|composition|irreducible|paradigm (scaling_extension ONLY in a scaling_followup_of lane: re-run the parent's frozen kernel at the registered scale points; new kernels are illegal there. A confirmatory_of lane instead copies the scout's kernel INCLUDING its original kind)",
      "bearer": ">=50 chars: minimal load-bearing fact claimed as new",
      "kernel": [
        {"id": "KC1", "kind": "learned_object|objective|update_law|coupling|representation|inference_rule|data_rule|system_relation",
         "statement": ">=50 chars: load-bearing computation/relation", "operator_refs": ["OP2"]}
      ],
      "known_primitives": ["borrowed primitives; [] is legal"],
      "support_shell": ["known support pieces not claimed as novelty"],
      "non_reducibility": "irreducible/paradigm: >=100 chars; why no known piece's REGISTERED computation produces this kernel's load-bearing intermediate (emulation is an operational test, not a function-class capacity claim)",
      "load_bearing_test": "irreducible/paradigm: >=80 chars; neutralize KC# and name what must vanish",
      "semantic_break": "paradigm only: >=100 chars; which learning/inference semantics is replaced"
    },
    "synthesis_core_ids": ["core_synthesis only: at least two unique CP# ids"],
    "synthesis_relation": {
      "operation": "core_synthesis only: >=100 chars; the new transformed relation, not an A+B stack",
      "discarded_shells": ["one >=35-char discarded source shell per CP# id"],
      "non_decomposability": ">=100 chars: why independent source modules cannot emulate this relation"
    },
    "effect_case": {
      "comparator_id": "frozen causal/resource reference: baseline or exact scientific-parent N#",
      "chain": [
        {"id": "Z1", "kernel_refs": ["KC1"],
         "intermediate": ">=50 chars: measurable state changed by the kernel",
         "relation": ">=50 chars: why that state changes the target",
         "target_cell": "C1", "direction": "increase|decrease|stabilize",
         "minimum_worthwhile_delta": 0.01,
         "expected_delta_interval": [0.01, 0.03]}
      ],
      "predicted_gain": ">=80 chars: delta/absolute result versus this reference plus the separate frontier-promotion case",
      "failure_signal": ">=50 chars: observation that refutes the chain",
      "resources": {
        "regime": "matched|budgeted_tradeoff|efficiency",
        "candidate": {"data_examples": 0, "train_tokens": 0, "parameters": 0,
          "train_flops": 0, "infer_flops": 0, "latency_ms": 0,
          "teacher_calls": 0, "api_calls": 0, "selection_budget": 0},
        "comparator": {"data_examples": 0, "train_tokens": 0, "parameters": 0,
          "train_flops": 0, "infer_flops": 0, "latency_ms": 0,
          "teacher_calls": 0, "api_calls": 0, "selection_budget": 0},
        "fixed_axes": ["axes held no worse than the comparator"],
        "tradeoff_axes": ["budgeted_tradeoff only: explicit allowed increases"],
        "improvement_axes": ["efficiency only: axes required to be strictly better"],
        "comparison": ">=80 chars: what is matched, every delta, and where unknown is used"
      }
    },
    "claim_scope": {
      "kind": "generalist|specialist|efficiency (specialist is legal only when the project decision policy allows it)",
      "target_cells": ["all C# cells this candidate claims, each covered by a Z# link; cells the contract marks required=true can NEVER be scoped away"],
      "guardrail_cells": ["registered guardrail C# ids"],
      "improvement_cells": ["efficiency only: partition of target_cells"],
      "parity_cells": ["efficiency only: complementary partition"],
      "rationale": ">=60 chars: freeze claim breadth before winner selection"
    },
    "theory_role": "none|explanatory|derivational",
    "theory_target": "required unless none: executable choice/prediction constrained",
    "theory_rigor": "derivational only: partial|full",
    "theory_obligations": [
      {"id": "theory_derived only: exact DO1 from surviving THEORY",
       "kernel_refs": ["KC1"], "operator_refs": ["OP2"],
       "satisfaction": ">=60 chars: how this program concretely instantiates the obligation"}
    ],
    "collision_queries": ["all non-repair routes: >=2 precise post-freeze prior-art queries, EACH >=30 chars"],
    "diagnosis_digest": "repair candidate only",
    "hypothesis_ids": ["repair candidate only: H1"],
    "mech_card_ids": ["repair candidate only: M###"]
  }]
}
```

Use the literal string `"unknown"` when a resource cannot yet be estimated; do
not silently omit an axis. The three axis arrays are disjoint and cover all
{{RESOURCE_AXES_COUNT}} axes ({{RESOURCE_AXES}}). `matched` puts every axis in `fixed_axes`;
`budgeted_tradeoff` uses a non-empty `tradeoff_axes` and otherwise fixed axes;
`efficiency` uses a non-empty `improvement_axes` and otherwise fixed axes, and
is legal exactly when `claim_scope.kind=efficiency`. Candidate values are caps
and comparator values are frozen reference estimates; use the legal
baseline/parent metrics and engine receipt supplied in the bundle, and keep
each numeric comparator estimate inside that sealed realized interval. A research
candidate may retain `unknown` while being audited, but it cannot become the
tournament winner until all {{RESOURCE_AXES_COUNT}} values on both sides are numeric; this does not
ask for the candidate's future receipt. Realized intervals later come from the
eval RUN and engine receipt. Every KC# must reference real OP# operators and be
covered by at least one Z# link. KC# denotes the effect-bearing mechanism, not
an automatic novelty claim: `known` and `composition` programs still identify
their KC# core, while `novelty.kind` records its relation to prior art. Every
claim target must have a numeric
minimum-worthwhile magnitude and an expected interval before literature or
winner selection. Multiple causal links may converge on one C#, but every link
for that C# must use the same direction; a mixed improve/stabilize contract has
no possible post-run settlement and is rejected before selection. The within-step operator graph must connect an input to a
declared output and expose which trained state inference consumes. Omit
`iteration` for an ordinary operator; iterative feedback must be explicit
rather than hidden in prose.

A `theory_derived` candidate must map every surviving theory DO# exactly once
to real KC#/OP# entries, and its `theory_rigor` must equal the portfolio's
precommitted rigor. A digest alone is not evidence that a program satisfies a
theorem-derived design obligation. This exact mapping is part of the candidate
digest. Omit `theory_obligations` entirely on repair, constructive and
core-synthesis routes;
their optional post-program theory cannot retroactively alter a frozen program.

Only a `core_synthesis` candidate carries `synthesis_core_ids` and
`synthesis_relation`; omit both on every other route. Its `discarded_shells`
array has exactly one substantive entry per referenced CP# in the same order.
Do not read or cite `CORE_PALETTE_PROVENANCE.json`, even if it is visible in the
worktree: it is an audit sidecar, not an authorized generator input.

For a hybrid, `scientific_parents` exactly lists all model parents and the
kernel itself has kind `coupling` or `system_relation`. The new relation must be
load-bearing; independently useful A+B stitching is a collage and cannot pass
the research tournament.

Do not cite a current paper to make the core look current. Constructive and
core-synthesis programs instead supply collision queries; the post-freeze reader
and tournament will reconstruct the nearest executable programs. For
core-synthesis, `synthesis_relation.non_decomposability` is a design hypothesis,
not a substitute for `novelty.non_reducibility` or the independent tournament.
Across this set, exact novelty kernel/bearer duplicates are illegal.

## Output contract

{{OUTPUTS}}

## Submit

{{SUBMIT_CMD}}
