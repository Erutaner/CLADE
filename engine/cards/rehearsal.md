# TASK {{TASK_ID}} - rehearsal (role: runner)

Node: {{NODE}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
This node is about to spend real full-scale compute. Before that, ONE tiny
real pass over its ENTIRE workflow (a few steps per stage + the real
evaluation) must run on the real platform, proving: every stage launches,
every produced artifact is READ BACK by the code that consumes it next (the
next stage's loader / the evaluator - writer-side self-reads do not count),
and every configured result key comes out. A wiring mistake found here costs
one tiny job; found at full scale it costs the training budget and can
overwrite work you needed. The receipt binds to the sealed implementation:
if the code is revised later, the proof is owed again.

The spec's top-level `rehearsal.command` owns HOW (it may submit tiny jobs to
the real scheduler, wait, and read logs internally); the engine executes it
and owns exit codes, logs and the receipt.

## Do
1. Run:
   ```
   {{EVO}} run-rehearsal --node {{NODE}}
   ```
   The engine supplies environment variables:
   - `EVO_REHEARSAL_REQUEST`: path of request.json (fresh nonce, the stage
     list to prove, result keys, and a DISPOSABLE `rehearsal_uri` namespace -
     tiny products go THERE, never to the node's real landings);
   - `EVO_REHEARSAL_RESULT`: exact path for the observation;
   - `EVO_REHEARSAL_NONCE`: the same fresh nonce.

   On success the command writes (and exits 0):
   ```json
   {"nonce": "exact EVO_REHEARSAL_NONCE",
    "checks": [
      {"stage": "each stage from the request", "status": "pass",
       "detail": ">=20 chars: what actually ran/was observed",
       "read_back_by": ">=20 chars: which CONSUMER code re-read this stage's artifact and what it saw"}
    ],
    "metrics": {"every configured result key": 0.0}}
   ```
   If real access/quota/data is missing, it writes the nonce plus typed
   blockers `[{"missing", "needed_for", "ask"}]` and exits nonzero.
2. If the engine reports `failed`: do NOT edit any implementation file here -
   the implementation is SEALED. Submit this task with the receipt as it is:
   the typed `REHEARSAL_FAILED` rejection routes the node back to an
   `implement` fix pass (the only task authorized to change sealed code), and
   the repaired code owes a fresh rehearsal.
3. If `blocked`: submit as-is; the typed blockers escalate to the user.
4. If `passed`: submit this task. On ACCEPTED the task closes, the node
   proceeds to its first full-scale stage/eval launch, and the receipt stays
   bound to the implementation seal - a later re-seal re-owes the rehearsal.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
