# TASK {{TASK_ID}} - conclude (role: analyst)

Node: {{NODE}} (role: {{NODE_ROLE}}) | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
This is where the graph learns. The verdict and any registered mechanism status
are COMPUTED by the engine from the claim-scoped contract, frozen decision rule
and sealed observations. Your job is the interpretation: which predictions
survived, which assumption broke, and what transfers to the graph as lessons.

## Verdict semantics (engine-computed; you must match)
- `improved`: a generalist claim met its target-group rule with no required
  target/guardrail regression. `specialist`: an honest subset claim succeeded.
  `tradeoff`: a target gain exists but breadth or a non-hard constraint lost.
  `regressed` / `inconclusive`: no accepted gain, a hard guardrail failed, or
  required evidence is uncertain. Every C# cell is direction/margin-aware.
- `promising` (v8): a full-program ROOT (no model parents) with
  `novelty.kind=paradigm` whose score lands within the parity margin of the
  reference, every mandatory guardrail settled, and every realized resource
  axis conservatively no worse than the comparator. Scope alone and parity
  bought with extra/unknown resources never earn this verdict. A fresh paradigm
  matching a long-optimized incumbent on first contact is headroom, not a null
  result - interpret it that way (what would exploit it? what did the dynamics
  show?).
- `dominant`: a pre-registered efficiency/Pareto claim succeeded while quality
  guardrails remained non-inferior. A
  dominant node is a win: first-class parent, teal in views.
- baseline nodes: `baseline`; platform nodes: `enabled|failed`.

The engine keeps two views. The **performance frontier** records observed
resource-normalized Pareto gains even when their proposed explanation fails -
it is computed from measurements alone, so a `regressed` or `inconclusive`
verdict does not evict a node that still holds the best numbers. In research
mode, the active **scientific inheritance frontier** additionally requires the
frozen M/E/T settlement (`scientific_promotion_status=met`); the origin
baseline is only a floor there, inheritable while nothing else has settled. A
refuted mechanism can therefore leave a useful measured gain to diagnose
without licensing descendants to inherit that scientific claim. In engineering
mode, the active inheritance frontier is the performance frontier. Do not
choose frontier membership in the outcome prose.

`scientific_promotion_status` separates two different failures:
`blocked` means something was decided against (contract failed/invalid,
mechanism refuted or waived, or a judged-against verdict);
`pending_evidence` means nothing was decided against and only an unsettled
measurement stands in the way - the engine lists exactly which rows under
`effect_contract.evidence_gaps`.

## Do (two files)

### 1. `{{OUTCOME_PATH}}`

The engine has PRE-FILLED the computed settlements in this file: `verdict`,
`effect_contract_status`, each prediction's `verdict`/`observed`, and
`mechanism.status`/`evidence` (platform nodes decide their own
enabled|failed). Do NOT edit those - they are recomputed and asserted at
submit. Your work is the INTERPRETATION: notes, root cause, observations,
lessons and the report. Edit the file in place:

```json
{"node": "{{NODE}}",
 "predictions": [{"note": "add a mechanism-level reading per pre-filled P# row"}],
 "mechanism": {"note": ">=40 chars - the measured probe signal vs
                the registered expectation; mandatory when the idea registered a mechanism_probe"},
 "scaling": {"note": ">=40 chars - per-point numbers vs the registered trend; mandatory when the
              idea pre-registered scaling. SHAPE BY EXECUTION MODE - reuse_only evidence:
              {\"held\": true|false, \"note\": ...}; follow-up node: {\"status\": \"deferred\",
              \"note\": ...} (the literal string 'deferred', nothing longer)"},
 "ablation_result": {"effect": "observed|not_observed|inconclusive",
                      "supports": "X1|X2|inconclusive",
                      "decision": "exact registered branch for an observed/no effect; substantive no-branch reason if inconclusive",
                      "evidence": "existing metrics/report artifact path",
                      "note": ">=50 chars: numbers and confound-aware causal interpretation"},
 "observations": [{"statement": ">=30 chars - the surprising measured fact",
                    "where": "component/stage/slice", "measurement": "the number/curve, with values",
                    "evidence": "path or run/metrics ref"}],
 "no_observations_reason": "only when the eval flagged anomalies you are NOT mining (>= 30 chars)",
 "effect_contract_status": "met|failed|uncertain|invalid|not_applicable - REQUIRED for every
              CANDIDATE model node (all three instrumental purposes - targeted_ablation,
              diagnostic_probe, maintenance - are exempt, they make no effect claim;
              an EXPLORATORY node pays every normal conclude duty - engine-copied
              verdict, effect_contract_status, Effect contract section, C# coverage -
              PLUS one duty on top: >= 1 observations[] entry, because the OB### ledger
              is what makes a scout worth running; only registered predictions/SOTA
              settlement are absent, since a scout registered none);
              must equal the engine's settlement of the frozen
              KC#->Z#->C# effect/resource contract. `uncertain` is the undecided state whose
              blocking rows the engine lists in effect_contract.evidence_gaps (-> pending_evidence)",
 "root_cause": {"assumptions": ["A2"], "note": ">=40 chars - which assumption failed and how you know;
              the literal note \"unknown\" is legal when no registered assumption is implicated"},
 "sota": [{"sota": "S###", "met": true, "note": ">=40 chars - the comparison, with numbers when
            same dataset+metric; settle EVERY sota_target the idea registered"}],
 "lessons": [{"scope": "global|lineage|conditional", "statement": "...", "evidence": "...",
               "recommendation": "...", "tags": ["..."]}],
 "no_lessons_reason": "only if lessons is empty",
 "infra_resolutions": [{"error": "ER### (REQUIRED for each of this node's unresolved
                        infrastructure-classed failures; omit the array when none exist)",
                        "disposition": "fixed|transient",
                        "surface": "fixed only: artifact_io|weights|launch|eval_adapter|service|data_access|environment|other",
                        "fix": "fixed only, >=30 chars: the working way - command/path/lines, replayable",
                        "recovered_run": "transient only: the RUN### of this node that later
                        succeeded UNCHANGED (same implementation revision) - that is what makes
                        it transient rather than fixed"}],
 "maintenance_parity": "maintenance nodes: engine-prefilled met|not_met; do not edit",
 "enabled_artifacts": ["platform nodes: paths that now exist for consumers"],
 "enabled_services": [{"name": "prm-endpoint", "invoke_pattern": "how a consumer calls it"}],
 "checkpoint": "optional path to the best checkpoint"}
```
- Every prediction registered in the idea meta must appear, with `observed` and a
  verdict consistent with its registered threshold (the engine recomputes).
- `root_cause` is mandatory when regressed: blame specific assumption ids from the
  idea (or note "unknown" honestly). This is what makes failure propagate as
  knowledge instead of vibes.
- `sota` is mandatory when the idea registered sota_targets: an honest settlement
  per target - beaten or not, on the claimed dimension, with the numbers when the
  dataset+metric are shared.
- `enabled_services` (platforms only, optional): runtime services this platform
  STOOD UP - a served PRM/verifier, a reward-model endpoint, a tool server.
  Once the platform concludes enabled, later node specs may bind
  `requires_services` to these names.
- Use the eval report's Stage evidence: a conclusion that only reads the final
  number wastes handoff, controller, component and resource evidence (for example,
  search exhausted its cap before convergence, or finetuning erased pretraining).
- **Mine the anomalies (v9)**: every surprising fact the eval's Anomalies section
  flagged should become an `observations` entry - the engine appends them to the
  phenomenon ledger (OB###), where future sketches anchor diagnoses and ideas
  ground assumptions. LESSONS say what to DO; OBSERVATIONS say what IS. An
  anomaly left unmined is an idea the next round cannot have. Skipping requires
  an explicit no_observations_reason.
- **Report the mechanism settlement (v9.2)**: when a mechanism probe was
  registered, copy the status computed by the engine from its frozen
  `decision_rule` and sealed `_mechanism_probe.observations`; do not promote an
  interpretive reading into the status. Use `note` to explain the aggregate
  versus the registered threshold and what the result may mean. An improved
  node with a computed REFUTED mechanism preserves its performance evidence but
  cannot transfer the original causal claim onto the research inheritance
  frontier.
  If the idea carried an attribution waiver, do not manufacture a settlement:
  the measured performance/verdict remains valid evidence, but mechanism status
  is unverified and `scientific_promotion_status` must be blocked.
  `evidence` points to the normalized metrics JSON whose `_mechanism_probe`
  block has already been cross-checked against the runtime observation files.
  After-positive-signal scaling follow-ups remain explicitly deferred.
- **Targeted ablation**: `verdict` still reports the model's performance effect;
  it is not the causal answer. Separately fill `ablation_result`: the engine
  checks the observed/no-effect result against the pre-registered X1/X2 and
  decision map. It was one
  manually approved run, not a seed study. Under a project-level preplanned
  seed protocol it is diagnostic and cannot join the performance frontier; a
  promising ablated design needs a normal candidate promotion.
- Lesson scopes: `global` (holds for the whole project - e.g. runtime/eval traps),
  `lineage` (holds for descendants of this node's parents - e.g. "this parent's
  representation saturates under X"), `conditional` (holds when tags match - tag
  with bottleneck ids/intents). Write lessons someone would act on; no platitudes.

### 2. `{{RESULT_PATH}}`
Sections: `## What was built`, `## What happened` (numbers vs predictions,
including the stage dynamics), `## Interpretation` (mechanism-level: what the
outcome says about the bottleneck and the idea's premise), and - for every
CANDIDATE model node (instrumental purposes are exempt) - `## Effect contract`
(>= 80 chars settling the frozen
KC#->Z#->C# links and resource regime against the sealed measurements; discuss
EVERY claim target and global guardrail cell by its C# id). When the contract
contains numeric goal thresholds, add `## Absolute goal status` (which C#/T#/G#
absolute goals are met, including any absolute guardrail limit). Keep this
separate from the relative verdict; a mean whose confidence interval crosses
the threshold is unknown, not met.
A `maintenance` node writes `## Parity settlement` instead (>= 60 chars walking
every decision cell against the repaired parent) - the engine settles parity and
rejects the conclusion without that section. A `diagnostic_probe` conclusion
must carry at least one `observations` entry: the measurement IS the product,
and a probe that records none is rejected.

## If this node revealed work that is not a new idea
Two findings here belong in neither a lesson nor the next candidate, and the
engine has a door for each. SUBMIT THIS TASK FIRST - both commands need a
concluded parent, so run them only after this conclusion is accepted. Propose
them to the user with the reason; each is capped per round and each stops at a
manual gate, so neither is yours to spend freely.
- A question you cannot answer from what was measured, where the answer would
  change what to try next -> `evo probe --parent {{NODE}} --question "..."`.
  It ends in an OB###; keep it inside a resource cap the user approves.
- Shared execution code is mechanically broken and held this idea back - the
  loader truncated a head, the launcher wrote the wrong path - so the idea never
  got a fair test -> `evo maintain --parent {{NODE}} --defect "..."`. The
  contract is parity: the repair preserves measured semantics, and the engine
  looks through a parity-met repair to this node's standing. If the fix is meant
  to IMPROVE results, it is a candidate instead.
If THIS node is itself a diagnostic probe, it is evidence and never lineage, so
neither command may name it: hang the follow-up off the node this probe was
measuring instead.
Neither door re-judges this node's verdict. Only `evo recover-plan` does that,
and only when the accepted authority was itself wrong - and it opens no gate, so
present its plan to the user before applying it.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
