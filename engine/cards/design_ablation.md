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
4. existing logs, saved tensors or an eval-only intervention cannot answer it;
5. either outcome changes a later DAG decision; and
6. one run is actually informative. If stochastic variation can plausibly flip
   the causal decision, reject the premise in the design instead of adding
   seeds. A seed study is a separately user-approved project protocol, not an
   ablation multiplier.

The existing parent is the reference. Never schedule a fresh parent/control
run, a comparison arm, a sweep, or several seeds inside this diagnostic.

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
  the question, one costly run, one explicit seed, and why this has positive
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
    "costly_runs": 1
  },
  "metric_bridge_needed": false
}
```

Omit every candidate scientific-program field (`change_scope`, `program`,
`novelty`, `effect_case`, `theory_role`, program/kernel digests, sketch or
diagnosis bindings, prior-art cards, SOTA targets and claim_scope). Omit
mechanism_probe, attribution waiver and scaling: this run is already the
diagnostic. X1/X2 replace generic A# assumptions.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
