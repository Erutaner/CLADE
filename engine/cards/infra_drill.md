# TASK {{TASK_ID}} - infra_drill (role: infrastructure canary operator)

Project: {{PROJECT_NAME}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}} | Bundle: `{{BUNDLE_PATH}}`

## Why
Facts and documentation are not execution proof. Before any project/science
analysis continues, one tiny real canary must traverse the infrastructure path
this project actually needs. The project owns the command; the engine does not
need a Slurm, Kubernetes, cloud, API, storage or local-GPU adapter. The engine
only runs the exact command and owns its exit code, stdout/stderr and receipt.

## Do
1. Define exactly one project-specific canary command in
   `.evo/profile/INFRA_DRILLS.json`:
   ```json
   {
     "schema": 1,
     "canary": {
       "command": "python tools/evo_infra_canary.py",
       "cwd": ".",
       "timeout_s": 1800,
       "description": ">=40 chars: how this one command joins the real tiny data, compute, artifact, evaluation and declared-service path"
     }
   }
   ```
   You may add one small project canary script when the platform needs it. The command
   can internally use any CLI, SDK, SSH hop, scheduler, HTTP API or local
   process. Do not split readiness into unrelated mocked probes.

   Heterogeneous platforms (e.g. remote training + a separate storage service
   + local evaluation) MAY declare a `"canaries": [...]` LIST instead of the
   single `canary` object - up to 6 commands, each with its own
   command/cwd/timeout_s/description. All run under ONE nonce, the required
   surfaces are covered JOINTLY (each surface must pass in at least one
   command), and one command must run the real tiny evaluator emitting the
   configured result keys. Every command is still a REAL path - a list is for
   platform heterogeneity, never for fragmenting one path into rituals.

2. In one invocation the command must exercise every surface listed in the
   engine request:
   - read a tiny item/slice from every physical dataset declared in
     `INFRA_FACTS` and exercise every approved evaluation D# through its real
     configured access path/protocol;
   - use the real compute path (for a remote scheduler: submit, wait/query,
     reach a terminal state and read its log; for local compute: really run);
   - write a nonce-bound disposable artifact to the requested real URI, read it
     back, compare it and clean it up;
   - run the project's real evaluator on a fixture/tiny slice and emit every
     configured result key;
   - make one tiny real call to every declared runtime service used by the path.

   A fixture reduces input size but still uses the real evaluator. A platform
   dry-run may diagnose syntax but cannot by itself pass this canary. An
   unrelated `echo`, a hand-written transcript or a pre-existing result is not
   evidence. The engine can prove that it launched this fresh command and bind
   its files; it cannot remotely attest a deliberately synthetic project
   script. Writing a simulator that merely echoes the request is fabrication.

3. The engine supplies these environment variables to the command:
   - `EVO_CANARY_REQUEST`: the PATH of a request.json file (read and parse
     that file) containing the fresh nonce, required surfaces, physical
     dataset entries, approved evaluation D# entries, disposable artifact
     URI, evaluation keys and services;
   - `EVO_CANARY_RESULT`: exact path where the command writes its observation;
   - `EVO_CANARY_NONCE`: the same fresh nonce for convenient forwarding to a
     remote job.

   On success, write this shape to `EVO_CANARY_RESULT`, omit `blockers`, and exit 0:
   ```json
   {
     "nonce": "exact EVO_CANARY_NONCE",
     "checks": [
       {"surface": "each required surface from the request", "status": "pass",
        "detail": ">=20 chars: the actual observed round-trip/result"}
     ],
     "metrics": {"every configured result key": 0.0}
   }
   ```
   If real access/quota/data/credentials are missing, write the nonce plus typed
   blockers and exit nonzero:
   ```json
   {"nonce": "exact EVO_CANARY_NONCE",
    "blockers": [{"missing": "what is inaccessible", "needed_for": "which link",
                  "ask": "the concrete item/action requested from the user"}]}
   ```

4. Run the command through the engine (never hand-write its receipt or logs):
   ```
   {{EVO}} run-infra-canary --task {{TASK_ID}}
   ```
   - `passed`: write the report below and submit.
   - `blocked`: write the report and submit; the engine opens a user gate and
     does not complete bootstrap. After the user supplies access, the entire
     canary gets a fresh task and nonce.
   - `failed`: inspect the engine-owned logs/receipt, fix the project canary command, and rerun
     before submitting. Real command failures are capped by
     `budgets.max_attempts`; exhaustion opens a user escalation instead of
     spending indefinitely.

5. Write `.evo/profile/INFRA_DRILLS.md` with substantive sections:
   `## Canary executed`, `## Surprises`, and `## Readiness`. Explain the one
   captured transaction; do not recreate or paraphrase an exit code into being.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
