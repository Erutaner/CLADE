# TASK {{TASK_ID}} - scientific conclusion (analyst)

Node: {{NODE}} | stage: {{STAGE}} | run: {{RUN_ID}} | gate: {{GATE_ID}}
Engine-computed predicate evidence: `{{GATE_EVIDENCE}}`
Bundle: `{{BUNDLE_PATH}}`

## Why
The stage executed successfully, but a pre-registered continuation criterion
was missed. The node is screened out for this project: its bound prerequisite
was falsified, but its unreached final predictions and mechanism are not thereby
declared refuted. This is not an infrastructure failure and not permission to
run the remaining workflow. Preserve the result as usable graph knowledge.

## Do

Write `{{OUTCOME_PATH}}`:

```json
{
  "node": "{{NODE}}",
  "verdict": "screened_out",
  "scientific_stop": {
    "stage": "{{STAGE}}",
    "run": "{{RUN_ID}}",
    "gate_id": "{{GATE_ID}}",
    "decision": "stop_node",
    "reason": ">=30 chars interpreting why the frozen criterion was missed"
  },
  "unreached_predictions": [
    {"id": "P1", "reason": ">=20 chars: final evaluation was not reached"}
  ],
  "root_cause": {
    "assumptions": ["A1"],
    "note": ">=40 chars explaining how the gate evidence falsified the bound A# assumptions"
  },
  "mechanism": {
    "status": "not_reached",
    "note": ">=40 chars; required when a mechanism probe was registered, because normalized probe settlement was not reached"
  },
  "observations": [{
    "statement": ">=30 chars: measured fact",
    "where": "stage/slice",
    "measurement": "numbers including the gate threshold",
    "evidence": "metrics path"
  }],
  "lessons": [{
    "scope": "global|lineage|conditional",
    "statement": ">=30 chars",
    "evidence": ">=20 chars",
    "recommendation": ">=20 chars",
    "tags": ["required for conditional"]
  }]
}
```

Every registered prediction must appear exactly once in
`unreached_predictions`; do not fabricate final metrics or claim a prediction
was tested. At least one observation and one lesson are required because the
gate miss is precisely the knowledge this DAG must retain.
Likewise, a continuation-gate miss is not a substitute mechanism predicate.
Report `not_reached` unless completed stages already produced the probe's
sealed, validated observations - in that case copy the ENGINE-computed
`refuted` or `unclear` result exactly. Never author `confirmed` here, and
never promote a reading of nearby stage numbers into a status.

Write `{{RESULT_PATH}}` with:

- `## What was attempted`
- `## Gate evidence` — name every gate metric and compare observed values with
  the frozen thresholds
- `## Interpretation` — failed assumptions and what the result does or does not
  refute
- `## Unexecuted work` — stages/evaluation deliberately skipped

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
