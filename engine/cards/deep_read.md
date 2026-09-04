# TASK {{TASK_ID}} - core-work and collision audit (role: prior-art analyst)

Round: {{ROUND}} | lane: {{LANE}} | origin: {{SEARCH_ORIGIN}} | intent: {{LANE_INTENT}}
Reusable paper cards required: >= {{MIN_CARDS}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Purpose

Separate two facts that must never be conflated:

1. `MECH_CARDS.jsonl` reconstructs what a paper actually computes. These M#
   facts are reusable and contain no candidate ids or novelty verdicts.
2. `COLLISION_AUDITS.jsonl` compares one exact frozen candidate digest with one
   M# fact. These CA# edges are attempt-specific and append-only.

Read the work itself, not the motivation used to sell it. Reconstruct old and
new scientific programs, the minimal core, necessary ablations, resource
differences, and gain confounds. When a frozen program set is present, use its
collision queries but do not rewrite the candidates.

Repair lanes call this task once before synthesis to ground the diagnosis and
again after program freeze to audit the actual KC#. Constructive/theory routes
freeze programs first. A `core_synthesis` lane also calls it before synthesis,
but that pass has a narrower handoff: after submission the engine projects the
M# operational facts into a sealed anonymous `CORE_PALETTE.json` and retains a
separate `CORE_PALETTE_PROVENANCE.json` sidecar. Only the palette is injected
into `sketch`; paper/card identity, titles, links, motivations and quotations
remain outside generator input. Do not create or edit either engine-owned file.

The core-synthesis pass after program freeze is ordinary full-provenance
collision analysis. A CP# source is not evidence that the resulting relation
is irreducible, and the pre-read cannot satisfy any CA# duty. Historical M#
facts may be reused; historical CA# edges can never satisfy a new program-set
or candidate digest.

## Retrieval

Use full text. Before marking a relevant paper unavailable, try the configured
number of distinct sources: venue/ACL Anthology or OpenReview, arXiv PDF/HTML,
author page, Semantic Scholar, and official code. Record attempts on EVIDENCE.

## Reusable paper facts

Append M### rows to `MECH_CARDS.jsonl`:

```json
{
  "id": "M0XX", "lane": "{{LANE}}", "paper": "E0YY",
  "name": "actual computational contribution",
  "topic": "only when a challenge requested a topic",
  "problem": ">=30 chars: computational problem, not author motivation",
  "old_program": ">=50 chars: objects and train/infer path before the work",
  "new_program": ">=50 chars: objects and train/infer path after the work",
  "program_operations": ["replace O1 with ...", "reroute gradient ..."],
  "irreducible_core": ">=60 chars: minimal load-bearing computation/relation",
  "necessary_components": ["components whose removal destroys the effect"],
  "support_components": ["known recipe/support pieces"],
  "core_math": ">=40 chars: actual objective/update/factorization",
  "assumptions": ["conditions the computation needs"],
  "reported_effect": "metric, comparator, data and scale",
  "ablation_support": ">=40 chars: evidence or explicit not-reported limitation",
  "resource_delta": ">=40 chars: all material resource changes",
  "gain_confound": ">=40 chars: what besides the core might explain the gain",
  "transfer_conditions": ">=40 chars: what must hold here",
  "failure_modes": ">=30 chars",
  "quote": {"OPTIONAL": "", "text": "verbatim passage", "section": "Method/Ablation section"}
}
```

Do not put `candidate_links`, `collision`, K#, or a candidate novelty judgment
inside M#. Paper facts survive candidate retries; candidate relations do not.

## Digest-bound collision edges

When the bundle contains a frozen `PROGRAMS_c#.json`, append CA### rows to
`COLLISION_AUDITS.jsonl`. Every current K# needs at least one `mechanism` and one
`task_effect` edge:

```json
{
  "id": "CA0XX", "lane": "{{LANE}}",
  "program_set_digest": "copy VERBATIM from the bundle's `Frozen digests` block",
  "candidate_id": "K1", "candidate_digest": "that K#'s digest from the same block (engine canonical-JSON hashes - NEVER recompute from file bytes)",
  "mech_card_id": "M0YY", "axis": "mechanism|task_effect",
  "query": ">=40 chars: precise query that surfaced this neighbor",
  "program_overlap": ">=60 chars: shared objects/operators/effect path",
  "irreducible_difference": ">=80 chars: remaining load-bearing difference",
  "emulation_test": ">=80 chars: whether/how this paper's REGISTERED computation actually produces the candidate core's load-bearing intermediate (capacity/expressiveness arguments are not an emulation test)",
  "recent_search_saturation": "required only if this K# has no recent neighbor: >=80 chars on queries and absence"
}
```

Use a recent neighbor whenever one exists. If both closest neighbors are older,
record an auditable recent-search saturation/absence argument instead of
pretending an old classic establishes current novelty. One M# may support
several CA# edges only when each comparison is separately written and digest-
bound.

Gap-triggered E#/M# additions are encouraged. Adding papers merely to hit a
round count is not.

## Output contract

{{OUTPUTS}}

## Submit

{{SUBMIT_CMD}}
