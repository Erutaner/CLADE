# TASK {{TASK_ID}} - red team (role: independent adversarial reviewer)

Idea {{IDEA_ID}} | lane {{LANE}} | origin {{SEARCH_ORIGIN}} | mode {{MODE}}
Minimum L{{MIN_LEVEL}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Purpose
Try to falsify the mature experimental contract. Audit the executable work and
its frozen resource-regime effect, not whether its paper story sounds elegant.

{{MODE_DUTY}}

## Output
Start with one verdict:

`VERDICT: ACCEPT|REVISE|REJECT_SHALLOW|REJECT_DUPLICATE|REJECT_NOT_COMPARABLE|REJECT_INFEASIBLE`

Use the verdicts as dispositions, not synonyms:

- `REVISE` means the current frozen survivor is repairable in maturation.
- `REJECT_SHALLOW` means its actual KC# core is trivial; name at least one
  winner KC# explicitly.
- `REJECT_DUPLICATE` requires the next line `DUPLICATE_OF: CA###|N###`.
  In research mode, CA### must be the collision record bound to this exact
  candidate and the Prior-art section must cite its resolving M### and E###;
  that disposition retires the exact program contract, not every future use of
  its kernel. N### must name a graph node with the same exact frozen kernel and
  therefore supports a core disposition. In engineering mode only such an N###
  can justify this verdict - matching published work is legitimate borrowing.
  In research mode a CA### duplicate additionally requires exactly one line
  `TOMBSTONE: <absorption criterion, >= 60 chars>` - a self-contained,
  anonymous predicate stating WHICH variations the collided work absorbs
  (e.g. "any variant differing only in the functional form of a per-sample
  weight computed from offline exposure statistics"). Keep the whole
  criterion on ONE physical line (never hard-wrap it), and bound the
  NARROWEST class the published work actually absorbs - one work, never a
  direction. It is the boundary of the death and nothing more: no paper
  names/links/ids/venues/method brand-names, no verdict words, and NO
  enumeration of untested directions - beyond the criterion the tombstone
  asserts nothing. If the bundle's tombstone list already bounds this
  territory, write `TOMBSTONE: TB###` (that exact id) instead of authoring a
  near-duplicate criterion. Optionally add `TOMBSTONE_NOTE: <one line>` (at
  most one; strategist-facing reference, still anonymous) if you see a
  structurally different escape worth commissioning; the note never reaches
  generators.
- `REJECT_NOT_COMPARABLE` and `REJECT_INFEASIBLE` reject this executable/effect/
  resource contract; they do not prove that every future use of the KC# is bad.

Then use the following exact sections for a model candidate:

- `## Program fidelity` - compare the mature program/kernel/effect objects with
  the frozen winner; identify the KC# most likely to be simplified in code.
- `## Irreducibility attack` - attempt known-module emulation, KC# neutralization,
  and independent A+B explanations. An emulation finding must show the known
  module's registered computation producing the load-bearing intermediate, not
  merely a function class able to express it. Research mode rejects reducible
  collage; engineering mode may accept a well-fitted composition.
- `## Effect and resource attack` - independently attack (a) fidelity and
  causal/resource suitability of the frozen baseline/scientific-parent
  comparator and (b) plausibility of promotion beyond stronger compatible
  observations and S# evidence. A stronger non-parent result may defeat
  promotion but does not by itself invalidate the frozen comparator. Also attack
  KC#→C#, data, tokens, params, training/inference compute, teacher/API calls,
  selection budget, probe attribution and sandbagged numeric thresholds. For a registered
  probe, verify before results exist that its frozen field, aggregation and
  threshold actually separate the claimed channel; for resources, require a
  plausible pre-registered accounting method. Realized intervals must later
  come from sealed eval-RUN measurements and an engine-generated receipt,
  never future analyst self-report.
  For an eligible `wildcat|moonshot` `full_program + paradigm` root, preserve
  the bundle's first-contact admission rule: a mature N# is long-run context,
  not by itself a reason to reject an otherwise hard-gate-clean first experiment.
- `## Prior-art attack` - reconstruct the closest published old→new program and
  test whether the claimed kernel difference survives. Cite evidence, not a
  motivation paragraph.
- `## Theory alignment` when theory_role != none - what executable choice the
  theory forces, which alternative it rules out, and whether approximations
  break its conditions.
- `## Verdict rationale` - synthesize the hard gates.
- `## Strongest surviving objection` (mandatory for ACCEPT, >=60 chars).

For a `platform` lane, keep `Program fidelity`, `Prior-art attack`, `Verdict
rationale`, and the ACCEPT objection, but replace the model-only
`Irreducibility attack` and `Effect and resource attack` with all three exact
sections below:

- `## Enablement and load-bearing attack` - try removing the claimed service or
  substituting ordinary infrastructure; ask whether any downstream action
  really changes.
- `## Operational and resource attack` - attack interfaces, artifact lifetime,
  capacity, latency/compute/API/storage bounds, recovery and feasibility.
- `## Consumer/use falsification` - execute mentally the named consumers and
  identify the observation that proves the platform decorative or unusable.

Include >=2 literal `QUOTE:` lines from IDEA.md. A terminal rejection keeps the
idea files and hash immutable. If the sealed tournament has another ranked
survivor, the engine tries that survivor next; only exhaustion of every survivor
reopens synthesis. Exact rejected contracts cannot be replayed unchanged, while
an effect/comparator/resource-only failure does not silently become a permanent
ban on every future contract using related core work.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
