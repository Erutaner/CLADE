# TASK {{TASK_ID}} - instrument review (role: independent judge)

Node: {{NODE}} | correction: {{CORRECTION}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Proposal: `{{PROPOSAL}}`
Original mechanism status: {{ORIGINAL_STATUS}} | recomputed under the proposal: {{CORRECTED_STATUS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
A settled mechanism verdict was computed by a frozen rule over sealed
observations. Someone now claims the INSTRUMENT was wrong - the formula that
produced the gated quantity, or the rule's shape - not that the line was set
too high or that the outcome is unwelcome. You are not the applicant and you
have nothing riding on the answer. You decide one question: genuine formula
error, or a post-hoc attempt to move a settled result?

The engine has already checked the mechanics: every `inputs` value in the
proposal equals the number in the sealed artifact it cites, the corrected rule
is well-formed, and the recomputed status above is the engine's own
application of the corrected rule to the proposal's values. What only a
reader can check is whether the argument is true regardless of the verdict.

## Do
1. Read the proposal's `argument`, `formula` and `observations`, then open at
   least one sealed artifact named in the bundle and recompute one corrected
   `value` yourself from its raw fields with the stated formula. If the
   arithmetic does not reproduce, the verdict is INSUFFICIENT.
2. Apply the independence test: strike every reference to the outcome from
   the argument and ask whether what remains still establishes that the
   original formula was wrong (a unit mismatch, a constant imported from a
   different statistic, a quantity that cannot exceed its bound by
   construction). An argument that only stands because the result came out
   badly is POST_HOC.
3. Apply the symmetry test: would this same correction have to be requested
   had the original verdict been the opposite? If the correction would only
   ever be filed in one direction, say so; a channel that only ever loosens
   is not an instrument correction.
4. Write `.evo/nodes/{{NODE}}/corrections/{{CORRECTION}}.review.md`:
   - line 1: `VERDICT: FORMULA_ERROR|POST_HOC|INSUFFICIENT`
   - `## Independence test` (>= 60 chars)
   - `## Recomputation check` (>= 60 chars; the artifact you read, the raw
     numbers, the value you reproduced)
   - `## Symmetry` (>= 60 chars)
   - `## Verdict rationale` (>= 60 chars)
   - at least two `QUOTE:` lines copied literally from the proposal's
     `argument`.

`FORMULA_ERROR` is the release direction: it opens a manual user gate that
would re-settle the node's mechanism from the SAME sealed observations under
the corrected rule (nothing is rerun, the original conclusion stays on record
as history). Under strict critic isolation that verdict must come from a
session other than the applicant's. `POST_HOC` and `INSUFFICIENT` close the
request; the node is untouched.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
