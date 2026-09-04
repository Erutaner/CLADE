# TASK {{TASK_ID}} - stage watch (runner)

Node: {{NODE}} | run: {{RUN_ID}} | stage: {{STAGE}} | job: {{JOB}}
Bundle: `{{BUNDLE_PATH}}`

## Why
Nothing else is currently actionable while workflow runs are in flight. Waiting
costs no attempts; check every running job listed in the bundle.

## Do
1. If still running, submit this task unchanged; the engine keeps waiting.
2. If execution succeeded, report that fact even when a local artifact is late:
   `{{EVO}} run-update --run <RUN> --status succeeded [--metrics-file <path>]
   [--ledger-file <path when required>]`. If evidence is absent or rejected, use
   `run-reconcile` on this same RUN; never submit a replacement job merely to
   recover a missing file.
   These reported paths are producer landing paths. On the next absorption the
   engine copies metrics and ledger into `.evo/runs/<RUN>/evidence/`, rewrites
   the run record, and seals the snapshots; only those ingested paths are used
   downstream.
3. If failed, run `{{EVO}} run-update --run <RUN> --status failed
   --failure-class infrastructure|implementation|operator|unknown
   [--repair-scope evaluation|workflow] --note "<specific observed error>"`.
   {{REPAIR_SCOPE_RULE}}
   A scientifically missed continuation
   gate is still a finished run; report its measurements honestly and let the
   engine compute the stop. Do not misreport it as an execution failure.

## Output contract
- run status via `run-update` (no files owned by this task)

## Submit
{{SUBMIT_CMD}}
