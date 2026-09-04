# TASK {{TASK_ID}} - smoke (role: runner)

Node: {{NODE}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
Smoke results are produced by the ENGINE executing the node spec's smoke_plan -
exit codes and artifacts, not narration.

## Do
1. Run:
   ```
   {{EVO}} run-smoke --node {{NODE}}
   ```
2. If steps FAIL: do NOT edit any implementation file - the implementation is
   SEALED, and any edit makes both `run-smoke` and this submit fail the seal
   audit (`SEALED_IMPLEMENTATION_DIRTY`/`SEALED_ARTIFACT_MUTATED`). Instead,
   read the logs under `.evo/nodes/{{NODE}}/smoke/` and SUBMIT this task with
   the failing RESULTS as they are: the typed `SMOKE_FAILED` rejection routes
   the node back to an `implement` fix pass, which is the ONLY task authorized
   to change sealed code. Your failure analysis goes into that fix.
3. If steps pass: submit this task.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
