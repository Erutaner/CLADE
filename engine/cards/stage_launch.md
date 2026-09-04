# TASK {{TASK_ID}} - stage launch (runner)

Node: {{NODE}} | stage: {{STAGE}} ({{STAGE_INDEX}} of {{STAGE_TOTAL}}) | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Complete-run lane: {{REPLICA_INDEX}} of {{REPLICA_TOTAL}} | seed: {{REPLICA_SEED}}
Control: {{STAGE_CONTROL}} / {{STAGE_MULTIPLICITY}} | caps: `{{STAGE_BUDGET}}`
Ledger: {{LEDGER_REQUIREMENT}}
Bundle: `{{BUNDLE_PATH}}`

Resolved command: `{{RESOLVED_LAUNCH}}`
Resolved metrics JSON: `{{RESOLVED_METRICS}}` (REPO-ROOT relative - see step 3)
Resolved products: `{{RESOLVED_PRODUCTS}}`
Prepared attempt: `{{RUN_ID}}` / token `{{ATTEMPT_TOKEN}}`

## Why
The engine tracks each scheduler-visible workflow stage as one recoverable run.
The command may internally perform bounded search or operate on several models;
the frozen controller, resource caps and optional continuation gate in
`NODE_SPEC.json` remain authoritative.

## Do
1. This attempt already exists in engine state as `{{RUN_ID}}`. First check
   whether that exact RUN/token is already bound to a remote job. Never create
   a second job for one prepared attempt. If the platform DOES show a job for
   this token, bind it (step 2) instead of launching; if you PROVED none
   exists, `{{EVO}} run-confirm-not-launched --run {{RUN_ID}} --note ...`
   resets the intent cleanly before any fresh launch. Launch only stage
   `{{STAGE}}` with the resolved command above and propagate the token as a
   job label/environment value when the platform permits it. Verify consumed artifacts,
   unique output URIs, local hard caps, the already-reserved project-wide
   resource envelope, and the execution-error journal.
2. Immediately after a platform accepts a background job, bind it using
   `{{EVO}} run-bind --run {{RUN_ID}} --job <id> --attempt-token {{ATTEMPT_TOKEN}}`.
   Repeating this for the same
   job is safe; trying to bind a different job is rejected.
3. Complete the LAUNCH file IN PLACE - the engine pre-filled `run`,
   `attempt_token`, `stage` and `seed` for this exact prepared attempt (do not
   edit them). Add:
   - background: `"mode":"background","job":"<id>","log_path":"<path>",
     "ledger_file":"<declared path when required>"`
   - already completed: `"mode":"completed","metrics_file":"{{RESOLVED_METRICS}}",
     "ledger_file":"<existing path when required>"`
   Use the original JSON type shown by `seed: {{REPLICA_SEED}}`; omit `seed`
   entirely when it says `not-applicable`.
   IMPORTANT: the engine resolves `metrics_file`/`ledger_file` from the
   REPOSITORY ROOT, never from the stage working directory. If the command
   runs inside the workdir and writes beside its code, the file's real
   location is `<workdir>/<name>` - that workdir-qualified repo-relative path
   is what the landing must be (declare it that way in the spec).
4. A completed metrics JSON contains this run's `seed` for a preplanned
   workflow, numeric `summary`, actual `usage` for every
   approved budget unit (usage exceeding cap x the `stage_budget_tolerance`
   validity band invalidates the evidence; record the real number regardless),
   and `stop_reason` for adaptive control. Do not write
   `passed`, `KILL` or another self-authored workflow decision: when the stage has
   a continuation gate, the engine computes it from the pre-registered summary
   predicates.
5. For a background run, report completion with:
   `{{EVO}} run-update --run {{RUN_ID}} --status succeeded --metrics-file <path>
   --ledger-file <path when required>`.

The reported metrics/ledger paths are producer **landing paths**, not durable
evidence addresses. On completed submission or `run-update` absorption, the
engine copies them into `.evo/runs/<RUN>/evidence/`, rewrites the run record to
those immutable snapshots, and seals them against the current spec,
implementation revision and fidelity audit. Downstream stages/evaluation read
the ingested paths from their bundle; never retain or cite a landing path that a
later job may overwrite.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
