# TASK {{TASK_ID}} - maintenance_review (role: adversarial auditor)

Lane: {{LANE}} | parent: {{PARENT}} | idea: {{IDEA_ID}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
Maintenance bypasses every novelty gate, so this review is the only
adversarial eye before the user gate. Your job is to catch novelty wearing
overalls: a "repair" that actually changes what the model computes, a parity
contract that cannot catch the risk it creates, or a fix a cheaper action
(config change, revert, existing recovery boundary) already covers.

## Do
Write `.evo/ideas/{{IDEA_ID}}.maintenance-review.md`. First line:
`VERDICT: ACCEPT|REVISE|REJECT_NOT_MAINTENANCE|REJECT_SEMANTIC_CHANGE|REJECT_NOT_WORTH_COST`

Sections (>= 60 chars each), each quoting the design literally (>= 2
`QUOTE:` lines total):
- `## Novelty smuggling audit` - does any in-scope change alter train/infer
  semantics beyond the declared preservation? If yes: REJECT_SEMANTIC_CHANGE.
- `## Parity risk audit` - can all_decision/noninferior actually catch what
  this change could break (silent numeric drift, seed handling, data order)?
- `## Cheaper alternative audit` - would a config change, a revert, or a
  recovery-boundary repair of one node achieve the unblock without a new
  node?
- `## Boundary audit` - are files_in_scope complete and minimal? A repair
  that must touch files outside its declared boundary fails implementation.
- `## Verdict rationale`

ACCEPT additionally requires `## Strongest surviving risk` (>= 60 chars).

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
