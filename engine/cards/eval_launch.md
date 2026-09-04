# TASK {{TASK_ID}} - eval_launch (role: evaluator/runner)

Node: {{NODE}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`
Prepared attempt: `{{RUN_ID}}` / token `{{ATTEMPT_TOKEN}}`

## Purpose

Execute the frozen evaluator and register its raw output as a RUN. This is the
only evaluation producer path: a quick inline command and a long background job
have the same evidence and accounting contract. Analysis happens later, after
the engine has ingested and sealed the RUN.

## Do

1. This attempt already exists as `{{RUN_ID}}`. Check whether that exact
   RUN/token is already bound before launching; never submit a second evaluator
   for one prepared attempt. If a job for this token exists, bind it (step 3);
   if you PROVED none exists, `{{EVO}} run-confirm-not-launched --run {{RUN_ID}}
   --note ...` resets the intent cleanly before any fresh launch.
   Run the node spec's exact `eval.run` command against the delivered artifact.
   Respect `eval.budget.limits` (`_usage` exceeding cap x the
   `stage_budget_tolerance` validity band invalidates the evidence; report the
   real number regardless), pinned judge/protocol, and every method frozen
   in `eval.resource_accounting`.
2. The evaluator's raw metrics JSON must contain:
   - every configured evaluation-cell `result_key` in the accepted scalar,
     fixed-evaluation interval, or preplanned-replication form;
   - `_usage` for every eval budget unit; a physical/interactive harness must
     additionally report `_usage.trials_completed` (integer >= 1, <= the
     preregistered `eval.harness.trials`) - trial completion is an execution
     fact only the producer can measure, and normalization may only copy it;
   - `_resource_measurements` with exactly these axes ({{RESOURCE_AXES_COUNT}} of them):
     {{RESOURCE_AXES}}. Each row is exactly
     `{"lower": <finite nonnegative>, "upper": <finite nonnegative>}` with
     `lower <= upper`;
   - {{PROBE_DUTY}}

   A measured zero is valid; a missing measurement is not. Do not emit
   `_effect_resources`: only the engine can create that normalized field.
3. Immediately after a background submission is accepted, bind it with
   `{{EVO}} run-bind --run {{RUN_ID}} --job <id> --attempt-token {{ATTEMPT_TOKEN}}`.
4. Complete `.evo/nodes/{{NODE}}/eval/EVAL_LAUNCH.json` IN PLACE - the engine
   pre-filled `run` and `attempt_token` for this prepared attempt (do not edit
   them). Add one of:

   ```json
   {"mode": "completed", "metrics_file": "<existing raw metrics JSON>"}
   ```

   ```json
   {"mode": "background", "job": "<job id / pid / run URL used to check it>"}
   ```

5. For background mode, when the job finishes report:

   ```text
   evo run-update --run {{RUN_ID}} --status succeeded --metrics-file <raw path>
   ```

   Report a real crash with `--status failed --failure-class
   infrastructure|implementation|operator|unknown --note "<observed error>"`.
   When the class is `implementation`, also pass `--repair-scope evaluation`
   only when the required edit is confined to evaluator-owned code and cannot
   affect delivered workflow artifacts; otherwise pass `--repair-scope
   workflow`. The former preserves completed training, while the latter
   deliberately replays it.
   If execution succeeded but evidence is not local yet, report success without
   fabricating a failure and reconcile this same RUN later.

The reported path is a mutable producer landing path. For either mode the
engine creates/updates an eval RUN, ingests the raw bytes into
`.evo/runs/<RUN>/evidence/`, seals them against the active spec and
implementation, accounts `_usage`, and generates a versioned read-only
`RESOURCE_RECEIPT_r#.json`. That receipt copies the sealed raw intervals and
the spec-frozen accounting methods and binds the spec, implementation, and RUN
evidence digests. Do not create, edit, normalize, or cite a receipt yourself.

## Output contract

{{OUTPUTS}}

## Submit

{{SUBMIT_CMD}}
