# TASK {{TASK_ID}} - review_ablation (role: causal-design critic)

Round: {{ROUND}} | lane: {{LANE}} | diagnostic: {{IDEA_ID}} | parent: {{PARENT}}
Attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
This is the only scientific review before the user is asked to spend compute.
Audit whether one changed-component run can answer the stated causal question.
Do not score novelty and do not repair a weak design by adding seeds, controls,
hyperparameter sweeps, mechanism probes or scaling runs.

## Do

Write `.evo/ideas/{{IDEA_ID}}.ablation-review.md`.

Line 1:

`VERDICT: ACCEPT|REVISE|REJECT_NOT_CAUSAL|REJECT_NOT_WORTH_COST|REJECT_INFEASIBLE`

Then these exact sections:

- `## Causal identifiability` - does the registered effect/no-effect outcome
  really discriminate X1 from X2? Name alternative explanations that survive.
- `## Single-change audit` - verify the changed factor is one factor and inspect
  every held constant. Training budget, data, preprocessing, evaluation and
  implementation quality are common hidden changes.
- `## Cheaper evidence audit` - inspect the parent artifacts. If existing logs
  or an eval-only intervention answer the question, reject the training run.
- `## Decision value` - verify the two outcomes lead to genuinely different,
  concrete DAG choices. Curiosity without a changed action is not enough.
- `## Cost audit` - verify exactly one changed-component run and one seed. If
  stochasticity makes one run unable to support the decision, reject the
  design; do not request repeated seeds inside it.
- `## Verdict rationale` - weigh the above.
- `## Strongest surviving risk` - mandatory for ACCEPT; explain why it does not
  invalidate proceeding.

Include at least two `QUOTE:` lines copied literally from the design document,
each at least six words.

Verdict meanings:

- `REVISE`: the same causal question can be repaired without adding runs.
- `REJECT_NOT_CAUSAL`: the intervention cannot distinguish X1/X2.
- `REJECT_NOT_WORTH_COST`: the result would not change a DAG decision, cheaper
  evidence already answers it, or one-run noise makes it uninformative.
- `REJECT_INFEASIBLE`: the one-factor intervention cannot be executed under the
  frozen resource/evaluation contract.

Any `REJECT_*` ends this lane before compute. `ACCEPT` still requires explicit
user approval of both the causal design and the final executable workflow.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
