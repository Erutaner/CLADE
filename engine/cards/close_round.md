# TASK {{TASK_ID}} - close_round (role: strategist)

Round: {{ROUND}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}` (lane outcomes, frontier)

## Why
Closing a round settles retirements and any newly exposed bottlenecks. The
engine computes frontier movement, stagnation and progress itself; your
strategic judgment for the NEXT round is delivered through the next
open_round's portfolio (which receives the frontier rollups) and through the
dossier addendum below - not through a report nobody reads.

## Do
1. Write `.evo/rounds/{{ROUND}}/RETIRE.json` (write `[]` if nothing retires):
```json
[{"node": "N###", "reason": "pruned|archived", "note": "why"}]
```
   - `pruned`: lineage is a dead end; the engine will refuse future lanes on it
     without user revival. Pruning a frontier node needs a strong note.
   - `archived`: keep for the record, no judgement.
   (Superseding happens automatically via frontier computation - only prune/archive
   need declarations.)
2. Optionally APPEND to `.evo/profile/DOSSIER_ADDENDUM.md`: when this round's
   outcomes exposed a NEW bottleneck the bootstrap dossier does not name, add
   `- B#: <hypothesis> | evidence: <what this round observed> | falsifier:
   <what would kill it> | distinguish: <what separates it from alternatives>`
   with a FRESH B# id (never rebind existing ids - the vocabulary is
   append-only). Keep this addendum problem-facing: do not propose a program,
   kernel, operator, technique or prior-art neighbor. A future repair lane will
   freeze competing H# diagnoses before its route-specific reading;
   constructive, core-synthesis and theory-derived lanes are not obliged to inherit a B# at
   all. Do not add
   bottlenecks speculatively - only ones this round's evidence actually
   surfaced.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
