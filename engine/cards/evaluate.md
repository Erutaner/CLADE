# TASK {{TASK_ID}} - evaluate (role: analyst)

Node: {{NODE}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}` (includes engine-recorded stage summaries, usage and ledgers)

## Purpose

Interpret and normalize the already-finished eval RUN. The bundle contains the
engine-ingested raw snapshot and a sealed, versioned
`RESOURCE_RECEIPT_r#.json`. Execution, accounting, and resource measurement are
complete before this task opens; comparability and scientific interpretation
belong here.

## Do
1. Do not rerun `eval.run`, reread its mutable producer landing path, or edit the
   receipt. Read the ingested `.evo/runs/<RUN>/evidence/` snapshot and the
   engine-generated receipt supplied in the bundle.
   EXCEPTION - approved repeat_measure: when the bundle carries an "APPROVED
   repeat measurement" block, THAT block overrides this rule and the
   single-run rule of step 2: execute the one bought-back repeat exactly as
   the block instructs and report the 2-run set on the named metric.
2. Write `{{EVAL_METRICS}}` with every configured
   evaluation-cell `result_key`, `_usage` copied from the RUN, and any validated
   `_mechanism_probe` block. Physical/interactive harness: `_usage.trials_completed`
   comes from the producer's raw RUN - copy it verbatim (only when a pre-upgrade
   raw file lacks the key may you supply it, from the producer's own records). Omit both `_resource_measurements` and
   `_effect_resources`. The former belongs only to raw RUN evidence; after this
   file validates, the engine injects the latter exactly from the active
   receipt and then seals metrics, report, receipt and mechanism observations.

   HUMAN-STUDY cells (`source_kind: human_study` in the evaluation contract):
   the result key must be an OBJECT carrying `study_artifact` = the
   repo-relative raw-response file the USER supplies (its filename is named by
   the cell's frozen `study_protocol`). The engine cannot produce those bytes.
   If the file is not in the repo yet, STOP and ask the user to place it at
   the protocol-named path - asking for user-owned raw data is a legitimate
   pause for this task, not a protocol violation; never fabricate responses
   and never burn attempts submitting without the file. After validation the
   user confirms the exact bytes at a protected gate.

   A scalar result is legal. For a sampled/noisy eval, an optional interval must
   be explicit and must add zero training runs:
   `{"value":x,"uncertainty":{"method":"analytic|fixed_predictions_bootstrap",
   "unit":"sample|query|episode|case","unit_count":500,
   "procedure":"named formula/script applied to fixed outputs","level":0.95,"lower":l,"upper":u,
   "source":"<existing fixed prediction/eval artifact>","extra_training_runs":0,
   "resamples":1000}}` (`resamples` is required only for bootstrap).
   The old `{mean,n,std}` form is rejected because `n` could mean examples,
   episodes, folds or expensive seed retraining. It never causes the engine to
   launch repeats.
   If this node's frozen `training_replication.mode` is `preplanned`, each
   decision metric instead exposes all approved runs so the engine can
   recompute the aggregate:
   `{"value":x,"training_replication":{"aggregation":"mean|median",
   "runs":[{"seed":11,"value":x1,"source":"run/artifact"},...]}}`.
   The seed set and count must exactly match the node spec. A single-run node
   must report a scalar or fixed-evaluation interval and cannot use this form -
   with ONE exception: a user-approved repeat_measure (see the bundle block)
   REQUIRES this form on its named metric, with exactly the two seeds the
   block states and the base run's value equal to the sealed first measurement.
   The repeat run's `source` must be a CHECKABLE citation - an existing
   repo-relative path (write the repeat's measurement artifact) or a
   registered AR###; prose is rejected. If the bought-back repeat physically
   CANNOT be executed (lost checkpoint, expired quota), do not fake it and do
   not burn attempts: report it, and the USER may release the duty with
   `evo waive-repeat --node <N###> --note "why"` - the single-run verdict
   then stands, on record.
   These are final results from complete workflow traversals: the engine has
   already required every seed to finish every stage.
   When `probe_execution` exists, also include a structured block copied from
   the validated JSON artifacts (not recomputed prose):
   `"_mechanism_probe":{"mode":"...","signal":"...","expect":"...",
   "required_fields":["field"],"observations":[{"seed":11,
   "artifact":"exact/path.json","values":{"field":0.97}}]}`.
   A same-run preplanned probe has one observation per seed; existing-artifact
   and one eval intervention have one. Values must exactly equal the files.
   **Judge discipline**: if a judge model scored this eval, it must be the
   spec's pinned judge - note model+version in Setup.
3. Write `{{EVAL_REPORT}}` with sections:
   - `## Setup` - checkpoint, data split, command actually run.
   - `## Results` - a C#-indexed table: dataset, task, metric, role, new value,
     reference, uncertainty/margin status, sourced absolute goal (or
     progress-only), and goal met/not-met. Do not present one display metric as
     the whole result or confuse a relative gain with SOTA attainment.
   - `## Stage evidence` (when a workflow ran) - analyze each stage's summary,
     actual versus approved resource use, and any adaptive/component ledger.
     Explain the handoff between stages and, for adaptive procedures, why the
     registered controller stopped and selected its output. Discuss every stage
     by name and echo recorded values.
   - `## Comparability` - walk the dossier invariants BY ID and state how each
     held; the ids must be real V# ids from PROBLEM_DOSSIER.md (checked). If this node has a metric
     bridge, reference its anchor result.
   - `## Anomalies` - the phenomenon hunt (v9): anything SURPRISING in curves,
     slices, or behaviors - a loss spike at one stage, a slice that moves
     opposite to the aggregate, an output pathology. Each anomaly you report
     here is a candidate OB### ledger entry (mined at conclusion) - the raw
     material of the next oral-tier idea. If genuinely nothing: write
     'NONE - <what you checked>' (>= 40 chars). Never skip the hunt.
   - `## Mechanism check` (when a cheap probe is registered for this node) - MEASURE
     the registered intermediate signal and report it against the registered
     expectation. This is what separates "the mechanism worked" from "the number
     moved"; name every registered field and quote at least one recorded value.
     Do not choose its status: the engine applies the frozen `decision_rule` to
     the sealed observation values; conclusion must copy that computed result.
   - `## Scaling probe` only for `existing_artifact` scaling - report the reused
     per-point numbers. Follow-up scaling is not run or fabricated here.

## Output contract

{{OUTPUTS}}

## Submit

{{SUBMIT_CMD}}
