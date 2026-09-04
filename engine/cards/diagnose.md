# TASK {{TASK_ID}} - diagnose (role: problem diagnostician)

Round {{ROUND}} | lane {{LANE}} ({{LANE_INTENT}}, min L{{MIN_LEVEL}})

Freeze a causal model of the observed failure before route-specific reading or
program synthesis. This stage deliberately withholds candidate programs,
mechanism reconstructions and candidate-specific prior-art comparisons. The
bundle does include each parent idea beside its outcome: treat that pair as the
historical intervention and response needed to explain what happened, not as a
program to copy. Use the project profile, dossier, parent idea+outcome pairs,
lane brief and measured OB### phenomena. A later repair program must bind this
diagnosis; the diagnosis must never be rewritten to flatter what is later
invented or retrieved.

Write the JSON output below. Register at least two competing causal hypotheses,
state what would falsify each, and name the observation that would distinguish
them. Do not name papers, techniques, architectures, program operators,
mechanism components, evidence-card ids or URLs. `solution_proposals` must be
`false`.

```json
{
  "lane": "{{LANE}}",
  "problem": ">=80 chars describing the observed failure and where it occurs",
  "evidence": [
    {"id": "DX1", "source": "B#|OB###|N###|profile:<existing path>",
     "observation": ">=35 chars, concrete and testable"},
    {"id": "DX2", "source": "...", "observation": "..."}
  ],
  "hypotheses": [
    {"id": "H1", "statement": ">=50 chars", "explains": ["DX1"],
     "falsifier": ">=40 chars", "discriminating_observation": ">=40 chars"},
    {"id": "H2", "statement": "...", "explains": ["DX2"],
     "falsifier": "...", "discriminating_observation": "..."}
  ],
  "leading_hypothesis": "OPTIONAL: H1 (when stated, must be a registered H#)",
  "invariants": [">=20 chars: comparability or behavior that must remain true"],
  "unknowns": [">=20 chars: unresolved fact whose answer could change the diagnosis"],
  "solution_proposals": false
}
```

Output:
{{OUTPUTS}}

Submit: `{{SUBMIT_CMD}}`
