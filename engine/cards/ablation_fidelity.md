# TASK {{TASK_ID}} - ablation_fidelity (role: controlled-change auditor)

Node: {{NODE}} | workdir: {{WORKDIR}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
The causal design is valid only if code changes the one registered factor and
keeps every registered control fixed. This audit happens after smoke testing
but before the single costly run. It replaces the ordinary innovation-fidelity
audit; it does not launch any experiment.
The report is sealed against the exact implementation revision. If this audit
changes code, submission creates a new implementation revision and any earlier
run evidence is superseded; the causal comparison may never mix revisions.

## Do

Read the approved ablation meta, parent code/spec, current code and build
report. Inspect the actual diff. If the factor is absent or any held constant
drifted, do not mutate the sealed source in this audit: return to implementation
repair, submit a new revision, rerun smoke, and then repeat the audit.

Write `.evo/nodes/{{NODE}}/ABLATION_FIDELITY.md`:

1. A line `FIDELITY: FAITHFUL` (`DEVIATES` is rejected until fixed).
2. Exactly one line `FACTOR: <literal changed_factor.name from the contract>`.
3. `## Changed-factor code map` with at least one row:
   `- <what realizes the factor> -> <relative/file.py> :: CODE: <literal snippet>`
4. `## Held-constant audit` with one exact line per registered control:
   `CONTROL: <literal held_constant string> :: VERIFIED: <>=20 chars: file/config/diff evidence>`
5. `## Diff audit` - list every changed file and explain why each is necessary
   for the one factor. State how you ruled out data, recipe, resource, seed and
   evaluation drift.
6. `## Audit verdict` - what was inspected and the strongest remaining risk.

Do not argue that extra changes are harmless. Either revert them or redesign
the causal contract and return it through user approval.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
