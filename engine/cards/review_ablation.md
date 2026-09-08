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
  Check the design's answers to the two admission questions: does the
  component have an inference-time switch, and what does one evaluation cost?
- `## Decision value` - verify the two outcomes lead to genuinely different,
  concrete DAG choices. Curiosity without a changed action is not enough.
- `## Cost audit` - verify the run count against its own stated basis: does
  the reason given in `runs_basis` really make this many changed-component
  runs decisive (a deterministic pipeline, an effect far above any plausible
  spread, a reported interval, or the engine's arithmetic where a floor is
  recorded)? The bundle's "Ablation allowance and sizing" block carries the
  engine's own allowance and floor/win/ratio numbers - check the count and
  the spend against them, not against the design's self-report. Too few runs
  for the claimed resolution is REVISE; a claim no
  affordable count can resolve is REJECT_NOT_WORTH_COST; a design above the
  allowance the bundle prints is not yours to refuse - the user decides it at
  the gate - but say so. Never wave a sweep or a seed cross-product through as
  an ablation. Check `settles_parent_mechanism`: true only when the changed
  factor is the parent's kernel.
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

Any `REJECT_*` ends this lane before compute (the parent's mechanism stays
deferred, with the declined attempt on record). `ACCEPT` goes to the design
gate and later the workflow gate: inside the pre-authorized allowance they
follow the autonomy policy, above it the user decides.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
