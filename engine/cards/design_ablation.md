# TASK {{TASK_ID}} - design_ablation (role: causal experiment designer)

Round: {{ROUND}} | lane: {{LANE}} | diagnostic: {{IDEA_ID}} | parent: {{PARENT}}
Attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
An observed parent result left one decision-relevant causal fork unresolved.
Design the cheapest valid intervention that can distinguish the two live
explanations. This is not a new-method contest: do not invent alternatives,
claim novelty, search papers for decoration, or assign candidate scope/M status.

## Admission test
Proceed only when all are true:

1. existing files from parent `{{PARENT}}` show the result that triggered the
   question;
2. exactly two explanations, X1 and X2, remain live;
3. changing one factor can distinguish them while the parent recipe, data,
   evaluation and budget stay controlled;
4. existing logs, saved tensors or an eval-only intervention cannot answer it.
   Answer two questions explicitly in `why_cheaper_evidence_insufficient`:
   does the component have an inference-time switch (can it be turned off in
   the trained model without retraining?), and what does one evaluation cost?
   A switch plus a cheap evaluation means the eval-only intervention comes
   first and a training run is not admitted;
5. either outcome changes a later DAG decision; and
6. the run count is a reasoned choice, one by default: say in `runs_basis`
   why THIS many changed-component runs settle the question - a deterministic
   pipeline, an effect far above any plausible run-to-run spread, an interval
   the evaluation reports itself, or the engine's noise arithmetic where the
   bundle prints a recorded floor for the cells the parent won. Spend is
   governed by the allowance the bundle prints (the project's multiple of what
   the parent itself cost): a design inside it resolves under the normal
   autonomy policy, a larger one waits for the user - it is not refused. If no
   affordable count can resolve the claim, the claim is too fine to settle -
   coarsen the question or accept `unclear` rather than run it anyway.

Say what the changed factor is. When it IS the parent's kernel, set
`settles_parent_mechanism: true`: the outcome then settles the parent's
mechanism from these same runs (effect observed -> confirmed, not observed ->
refuted; an inconclusive result settles nothing - the parent stays deferred
with the attempt on record) and the parent's row on the frontier says so.
When you isolate some other component, set it `false`; the parent's
mechanism stays as it was. Which of X1/X2 the effect supports is your
registration; the parent settlement reads only the effect.

The existing parent is the reference (its sealed measurements are the
untreated arm). Never schedule a fresh parent/control run, a comparison arm,
or a sweep inside this diagnostic; the changed-component runs you register are
the whole spend.

## Do

Write `.evo/ideas/{{IDEA_ID}}.md` with these exact headings:

- `## Causal question` - the one uncertainty and the two live explanations X1/X2.
- `## Parent evidence` - quote the observed numbers and name the exact existing
  parent result/eval files that created the fork.
- `## Controlled intervention` - one changed factor, its parent and ablated
  values, plus what is held constant. Explain unavoidable confounds honestly.
- `## Decision map` - what later graph action follows from effect, no effect, or
  an inconclusive result.
- `## Evaluation and cost` - 1-3 numeric predictions, the C# cells that answer
  the question, the noise arithmetic behind the run count (decision-relevant
  effect vs noise floor -> runs), the explicit seeds, and why this has positive
  value of information.
- `## Risks` - especially stochasticity, implementation drift, and reasons the
  intervention may fail to identify causality.

Also write `.evo/ideas/{{IDEA_ID}}.meta.json`:

```json
{
  "idea": "{{IDEA_ID}}",
  "lane": "{{LANE}}",
  "title": "short diagnostic title",
  "experiment_purpose": "targeted_ablation",
  "level": 0,
  "parents": ["{{PARENT}}"],
  "platforms_consumed": [],
  "evaluation_scope": {
    "target_cells": ["C# cells whose result distinguishes X1/X2"],
    "guardrail_cells": ["C# project guardrails"],
    "rationale": ">=60 chars: why these cells answer this causal question"
  },
  "predictions": [
    {"id": "P1", "metric": "configured result_key", "comparison": ">=|<=",
     "value": 0.0, "rationale": ">=40 chars tied to X1/X2"}
  ],
  "ablation": {
    "parent": "{{PARENT}}",
    "question": ">=50 chars: one causal uncertainty",
    "competing_explanations": [
      {"id": "X1", "statement": ">=40 chars"},
      {"id": "X2", "statement": ">=40 chars"}
    ],
    "trigger_evidence": ">=30 chars naming parent {{PARENT}} and the observed ambiguity",
    "trigger_artifacts": ["{{PARENT_RESULT}}", "{{PARENT_METRICS}}"],
    "changed_factor": {
      "name": "the one factor",
      "parent_value": "exact parent setting/component",
      "ablated_value": "exact intervened setting/component"
    },
    "intervention": ">=40 chars: how only that factor changes",
    "held_constant": [
      ">=20 chars: dataset/split and preprocessing",
      ">=20 chars: training recipe and resource cap",
      ">=20 chars: evaluation protocol and all other components"
    ],
    "effect_supports": "X1",
    "no_effect_supports": "X2",
    "decision_if_effect": ">=50 chars: exact next DAG action",
    "decision_if_no_effect": ">=50 chars: different next DAG action",
    "why_cheaper_evidence_insufficient": ">=50 chars",
    "costly_runs": 1,
    "settles_parent_mechanism": true,
    "control_is_clean_program": true,
    "runs_basis": ">=40 chars: why this many changed-component runs settle the question (deterministic pipeline / effect far above any plausible spread / reported interval / the engine's arithmetic on a recorded floor)"
  },
  "metric_bridge_needed": false
}
```

Omit every candidate scientific-program field (`change_scope`, `program`,
`novelty`, `effect_case`, `theory_role`, program/kernel digests, sketch or
diagnosis bindings, prior-art cards, SOTA targets and claim_scope). Omit
mechanism_probe and scaling: this run is already the diagnostic. X1/X2 replace generic A# assumptions.

`control_is_clean_program`: the control arm is YOUR design - remove the
part, freeze it, randomize it, swap in a stand-in - whatever separates the
question. Say whether that arm is the parent's program with the kernel simply
REMOVED (`true`): if the kernel then turns out not to carry the gain, that
trained arm is the natural thing to build on next and the engine names it
as the control version; a stand-in control (`false`) settles the causal
question just as well but is a diagnostic only, and children remove the
kernel themselves. Read the bundle's line on the parent's probe first: what
the probe saw (uses the part / does not / unclear) is your first lead for the
factor to change and for X2 - and never a reason to skip the run.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
