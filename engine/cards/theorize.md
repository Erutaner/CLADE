# TASK {{TASK_ID}} - theorize (role: theorist) - cycle {{CYCLE}}

Round {{ROUND}} | lane {{LANE}} | position: {{THEORY_POSITION}} | winner {{WINNER}}
Parents: {{PARENTS}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}} | bundle `{{BUNDLE_PATH}}`

## Purpose
A useful theory either produces/constrains a program or makes discriminating
predictions about one. It need not be a coordinate change, and novelty does not
come from mathematical presentation. Derive consequences that an implementation
and experiment can violate.

Formal duty:
{{FORMAL_DUTY}}

## Output
Write `{{THEORY_OUTPUT}}` with exact sections. `cycle {{CYCLE}}` is this
candidate's local rigor/retry count; the filename uses the lane-global sealed
artifact sequence and may therefore have a different number.

- `## Obstruction or desiderata` - the precise fact the result addresses.
- `## Result` - theorem/proposition/structural claim, including scope.
- `## Derivation` - A# premises to result with failure conditions (>=400 chars);
  formal lanes use the required S# step-chain format.
- `## Design consequences` - what class of program follows from the result.
- `## Ruled-out alternatives` - plausible programs/approximations the result
  excludes, and why.
- `## Executable obligations` - >=2 unique bullet lines in the exact form
  `- DO1: <concrete program/code property>`. For before-program theory, these
  are the complete obligations that every synthesized program must map exactly
  once to real KC#/OP# entries. For after-program theory, each DO# must cite
  existing winner KC#/OP# entries and may not redesign them; those DO# rows are
  an audit of the frozen program and do not create a `theory_obligations` field.
- `## Discriminating predictions` - >=2 `TP#:` predictions that separate the
  result from the ruled-out alternatives, including scale/failure behavior.
- `## Scope and failure conditions` - what breaks the result and what remains an
  empirical conjecture.

Cycle >=2 also needs `## Response to challenge` and a literal `QUOTE:` from the
previous challenge. Cite M# only when literature supplied a premise; a theory-
first cycle is not required to pretend a recent paper generated its core.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
