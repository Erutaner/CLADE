# TASK {{TASK_ID}} - metric_bridge (role: analyst)

Node: {{NODE}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
This node changes what the model outputs. Comparability with the rest of the graph
is only preserved if an adapter maps the new outputs into the SAME metric
computation - and the proof is mechanical: the adapter, run over baseline-side
outputs, must reproduce the baseline's reported numbers.

## Do
1. Audit the adapter already created and sealed by the implementation task.
   Do not add or modify code in this task.
2. Anchor test: run that sealed adapted evaluation path against the baseline's outputs
   (or the baseline checkpoint) so it should reproduce the baseline metrics.
3. Write `.evo/nodes/{{NODE}}/metric_bridge/ANCHOR.json` (the numeric anchor
   IS the equivalence evidence; no separate prose report):
```json
{"command": "<the anchor command you ran>",
 "adapter": "<workdir-relative adapter path already in the implementation manifest>",
 "produced": {"<result_key>": <number the adapted path produced>,
              "...": "EVERY configured decision result_key must appear"},
 "tolerance_pct": 0.5}
```

Omit `baseline_expected`: the engine reads the sealed baseline metrics itself
and compares `produced` against those engine-read values. The key is optional
and, when present, must EXACTLY equal the engine-read sealed baseline metrics -
a hand-written or rounded value is rejected as forged, and the decision-key
comparison still runs against the engine-read values either way.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
