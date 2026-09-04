# TASK {{TASK_ID}} - maintenance_design (role: repair engineer)

Lane: {{LANE}} | parent: {{PARENT}} | idea id: {{IDEA_ID}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
Maintenance repairs shared execution code WITHOUT making a scientific claim:
the defect (not an idea) is the reason, semantic preservation (not
improvement) is the contract, and engine-settled parity over every decision
cell is the evidence. A parity-met maintenance node becomes the repaired
executable base future lanes build on - it is frontier-TRANSPARENT in both
directions (it never enters a frontier itself, and parent legality looks
through it to {{PARENT}}'s standing), and it never earns scientific
promotion. If your change intends to ALTER measured semantics,
stop: that is a candidate and belongs in the novelty pipeline.

## Do
1. Ground the defect in evidence: cite ER###/OB### entries or exact repo
   paths. A wish ("code is ugly") is not a defect; a mechanism ("the loader
   silently truncates the checkpoint head, so KC effects cannot express")
   is.
2. Write `.evo/ideas/{{IDEA_ID}}.md` with sections (>= 60 chars each):
   `## Defect`, `## Evidence`, `## Change boundary`, `## Parity argument`,
   `## Unblock rationale`, `## Risks`.
3. Write `.evo/ideas/{{IDEA_ID}}.meta.json`:

```json
{
  "idea": "{{IDEA_ID}}", "lane": "{{LANE}}", "title": "...",
  "experiment_purpose": "maintenance", "level": 0,
  "parents": ["{{PARENT}}"],
  "maintenance": {
    "defect": ">= 60 chars - the mechanical flaw",
    "defect_evidence": ["ER###/OB###/N### or repo path, >= 1"],
    "change_boundary": {"files_in_scope": ["exact files this repair may touch - ENFORCED: "
                                           "the engine diffs your workarea against the parent's "
                                           "reviewed commit and rejects any executable file "
                                           "changed outside this list"],
                        "semantic_intent": "preserve"},
    "expected_unblock": ">= 40 chars - what later work this lets express",
    "parity_contract": {"cells": "all_decision", "standard": "noninferior"}
  }
}
```

Rules: no candidate fields; `metric_bridge_needed` stays false (changing the
output/eval space is a semantics change, not a repair); `parity_contract` is
the exact literal shown - the engine settles it over every claim target and
guardrail, and `parity != met` means the repaired base is NOT inheritable.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
