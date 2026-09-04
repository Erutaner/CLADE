# TASK {{TASK_ID}} - pose theoretical problem (role: theorist)

Round {{ROUND}} | lane {{LANE}} | theory position: {{THEORY_POSITION}}
Winner: {{WINNER}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}} | bundle `{{BUNDLE_PATH}}`

## Purpose
State a problem precise enough to constrain an algorithm. Before-program theory
may start from a formal obstruction or desiderata in the external task. After-
program theory must pose the actual winner's KC# claim. Neither route is required
to tell a coordinate-change or parent-kinship story.

## Output
Write the revision-addressed `PROBLEM_c<revision>.md` named in the output
contract with these exact sections:

- `## Setup` - >=3 typed lines `- sym: X : space/type - meaning`.
- `## Given` - >=2 A# assumptions with their empirical/mathematical status.
- `## Want` - a precise result in the declared symbols. Before-program: the
  result must imply executable design obligations. After-program: it must settle
  the winner's claimed theory target.
- `## Success criteria` - connection to a measurable result_key/intermediate and
  what would count as a counterexample.

Every symbol must be used outside Setup. Do not add notation for appearance.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
