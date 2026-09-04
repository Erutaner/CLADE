# TASK {{TASK_ID}} - profile (role: program analyst)

Project: {{PROJECT_NAME}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
Later search must be able to edit one update law or replace the whole learning
system. Prose about an "architecture" is not enough: first reconstruct the
executable scientific program from code, including training and inference.

## Do
Read the actual code and docs from `project.code_root`. Produce both outputs.

### `PROJECT_PROFILE.md`

Use the exact sections `## Task`, `## Data`, `## Model`, `## Training`,
`## Evaluation and metrics`, `## Runtime`, `## Current results`, and
`## Known issues`. Every substantive claim carries `[src: relative/path]` or
`[src: relative/path:line]`. Code wins when docs disagree; record disagreement.

### `BASELINE_PROGRAM.json`

Reconstruct what is actually computed rather than copying class names:

```json
{
  "schema_version": 2,
  "program": {
    "objects": [
      {"id": "O1", "kind": "input|state|representation|prediction|supervision|memory|latent|controller|interface|artifact|other",
       "semantics": ">=30 chars: mathematical/computational meaning",
       "code": ["real/repo/path.py"]}
    ],
    "operators": [
      {"id": "OP1", "kind": "transform|objective|estimator|update|transition|inference|routing|memory|data|system",
       "phase": "train|infer|both", "semantics": ">=50 chars: executable action",
       "reads": ["O1"], "writes": ["O2"], "depends_on": [],
       "iteration": {"kind": "recurrent|fixed_point|adaptive_search|self_play",
         "state_objects": ["O2"], "update_order": ">=30 chars",
         "termination": ">=30 chars", "max_steps": 100}}
    ],
    "training_process": ">=40 chars: objective, estimator, update and gradient dependencies in execution order",
    "inference_process": ">=40 chars: prediction/generation/state-transition computation",
    "information_flow": ">=40 chars: which objects can influence which others, including feedback/cache lifetime",
    "resource_model": ">=40 chars: parameters, data/tokens, train/infer compute, teacher/API calls and dominant costs"
  },
  "external_invariants": [">=2 entries: task/data/evaluation contracts later programs must preserve", "..."],
  "unknowns": ["facts code inspection could not settle; empty array is legal"]
}
```

Omit `iteration` for ordinary feed-forward operators. For recurrent,
fixed-point, adaptive-search, or self-play computation, declare it explicitly;
`depends_on` remains the acyclic within-step schedule. Do not force a familiar
paper vocabulary onto the code. If an object is implicit in a tensor or control
loop, name its semantics and cite the file that realizes it. This IR is a
baseline for comparison, not a list of components future ideas must inherit.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
