# TASK {{TASK_ID}} - challenge theory (role: adversarial theorist)

Round {{ROUND}} | lane {{LANE}} | cycle {{CYCLE}} | position {{THEORY_POSITION}}
Attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}} | bundle `{{BUNDLE_PATH}}`

## Verdict
Start with `VERDICT: PROCEED|REVISE|READ|FORMALIZE`.

## Audit
Use exact sections:

- `## Premise audit` - attack the most fragile A# and its project grounding.
- `## Derivation attack` - find the first invalid implication (formal lanes also
  add `## Step audit` naming the weakest S#).
- `## Design consequence audit` - do DO# obligations actually follow, and are
  they executable rather than vague desiderata?
- `## Alternative explanation` - a plausible result/program that fits the same
  facts without this theory.
- `## Prediction audit` - can TP# distinguish the alternatives under the frozen
  evaluation/resource contract?
- `## Verdict rationale`.

Include >=2 literal `QUOTE:` lines from the theory. PROCEED also requires
`## Strongest surviving objection` (>=60 chars). READ requires `## Required
reading` with >=2 `- topic:` lines; the engine returns to theory after those
core-work audits. FORMALIZE requires `## Formalization demand` explaining which
precise prose claim is hiding its weakest step.

On a `theory_rigor=full` lane, PROCEED before challenge cycle {{MIN_CYCLES}} is
illegal - the deep-rigor budget must actually be spent; until then use
REVISE/READ/FORMALIZE (this is cycle {{CYCLE}}).

{{FORMAL_FLAG}}

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
