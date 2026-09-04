# TASK {{TASK_ID}} - probe_design (role: diagnostician)

Lane: {{LANE}} | parent: {{PARENT}} | idea id: {{IDEA_ID}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
A diagnostic probe answers ONE concrete question with a bounded measurement.
It makes no novelty claim, never enters any frontier, and can never be a
parent - its entire product is observations in the phenomenon ledger that
later diagnosis/sketch work may cite. The user gate after this design is
always manual: the budget cap you declare here is what they approve.

## Do
1. Read the lane brief (the question that opened this lane) and the parent's
   result/metrics. If existing observations already answer the question,
   say so in `## Why now` and design the cheapest confirming measurement.
2. Write `.evo/ideas/{{IDEA_ID}}.md` with sections (>= 40 chars each):
   `## Question`, `## Why now`, `## Measurement plan`, `## Decision impact`,
   `## Cost`.
3. Write `.evo/ideas/{{IDEA_ID}}.meta.json`:

```json
{
  "idea": "{{IDEA_ID}}", "lane": "{{LANE}}", "title": "...",
  "experiment_purpose": "diagnostic_probe", "level": 0,
  "parents": ["{{PARENT}}"],
  "evaluation_scope": {"target_cells": ["the C# cells this probe observes"]},
  "probe": {
    "question": ">= 40 chars - the ONE thing this answers",
    "measurement_plan": ">= 60 chars - what runs, on what data/artifact, measured how",
    "decision_impact": ">= 40 chars - which future choice the answer changes",
    "budget": {"<project resource unit>": <positive cap>}
  }
}
```

Rules: no candidate fields (program/novelty/effect_case/claim_scope/
predictions/mechanism_probe are all rejected); `metric_bridge_needed` stays
false - a probe measures in the existing evaluation space. The later
NODE_SPEC copies `probe` exactly and its planned stage+eval budgets must fit
inside `probe.budget`. Prefer an evaluation-only plan (no training stages)
whenever the question can be answered from existing artifacts.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
