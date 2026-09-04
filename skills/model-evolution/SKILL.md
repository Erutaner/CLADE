---
name: model-evolution
description: >
  Long-horizon evolution of an existing ML project through a DAG of typed
  scientific programs. The deterministic engine owns scheduling, M/E/T
  contracts, repair/constructive/theory-derived search routes, digest-bound
  prior-art audits, evaluation, resources, artifacts and gates. Use when the
  user asks to iterate or systematically surpass an existing model over
  multiple rounds.
---

# Model Evolution v10

The engine at `<package>/engine/evo.py` owns the workflow. You execute one task
at a time.

## Standing operating contract

1. Run:

   ```bash
   python <package>/engine/evo.py --repo <repo> next
   ```

   It returns exactly one task card, a context bundle and declared outputs;
   validation runs at submit and a REJECTED submit lists every deficiency.
   Before submitting, `... validate --task T####` dry-runs the exact same
   validators read-only - free, no attempt spent. Use it instead of guessing;
   never import engine modules or read engine source to pre-validate (engine
   source is readable only under the user-authorized deadlock protocol).

2. Do exactly the returned card. Do not invent stages, reorder the route, reuse
   a remembered schema or write undeclared outputs. The current card wins over
   memory and intuition.

3. Submit:

   ```bash
   python <package>/engine/evo.py --repo <repo> submit --task T####
   ```

   If rejected, the listed deficiencies are the fix list. Correct the declared
   outputs and resubmit. A running external job is not a rejection.

4. Never hand-edit engine-owned state:

   - `.evo/state.json`
   - `.evo/graph.json`
   - `.evo/artifacts.json`
   - events, errors, lessons or `views/`

   User gates are decided by the user through `decide`, never by the operating
   agent.

5. After every acceptance, immediately run `next`. Stop only at an open user
   gate, `DONE`, an external-job wait with no other actionable work, a
   concrete onboarding question that requires the user, or an explicit
   STOP-and-ask instruction in the current task card's body (user-owned
   material or a user-only decision named there is legitimately waited for -
   never fabricate it, never burn attempts submitting without it). "Enough
   work for this session" is not a valid protocol state.

The complete loop is `next -> work -> submit -> next`.

## Keep the scientific axes separate

Do not collapse the current schema into one scalar:

- `intent` controls graph topology;
- `search_origin` controls the invention route;
- `change_scope` / L1-L4 is implementation breadth only;
- `novelty.kind` is the M judgment;
- `effect_case` is the E claim;
- `theory_role` and `theory_rigor` are the independent T claim.

A local program can be irreducible. A full rebuild can be a known composition.
A paradigm need not have a theorem. A derivation does not establish novelty.
Repeat these distinctions faithfully when explaining a gate to the user.

## Respect route order

The engine supports four invention routes.

### Repair

```text
diagnose -> deep_read -> sketch -> deep_read(collision audit) -> tournament
```

The diagnosis must be frozen before candidate mechanisms and candidate-specific
prior-art comparison. Reading may test the H# hypotheses but may not rewrite
them. After programs are frozen, the second reading pass compares their actual
KC# cores to nearest executable programs.

### Constructive

```text
sketch -> deep_read(collision audit) -> tournament
```

Construct from the task, data, evaluation/resource contract and baseline
program. Do not force the result into a dossier bottleneck or claim that a
paper's motivation generated it. Freeze complete programs first; use reading
to try to disprove novelty and effect afterward.

### Core synthesis

```text
deep_read (reconstruct actual work as reusable M# facts)
  -> engine freezes the anonymous CORE_PALETTE -> sketch
  -> deep_read(full-provenance collision audit) -> tournament
```

Use pre-invention literature without a named-module menu: the reader
reconstructs what works actually compute; the engine projects only anonymous
operational CP# facts into the sketch bundle (provenance sidecar is audit-only).
Each sketch transforms >= 2 CP# cores into one new load-bearing relation. The
frozen program still faces the same full-provenance collision audit and
tournament as every other route - palette membership is never novelty evidence.

### Theory-derived

```text
pose -> theorize <-> challenge -> sketch -> deep_read(collision audit) -> tournament
```

Derive executable obligations before program synthesis. The program must
instantiate them. Full theory rigor follows `theory_rigor=full`, never L4 or
moonshot intent.

Every route receives an attempt-specific post-freeze collision audit. M# paper
facts are reusable; CA# candidate edges are bound to the exact program-set and
candidate digests. Never reuse an old CA# to satisfy a resketch attempt.

## First run

```bash
python <package>/engine/evo.py --repo <repo> init --project-name "<name>" --goal "<goal>"
python <package>/engine/evo.py --repo <repo> next
```

Init writes `.evo/ONBOARDING.md`. `project_scan` inspects user documents and
code, then records sourced facts and open U# questions. `configure` resolves
the evaluation cells, margins, guardrails, claim breadth, evidence policy,
replication, resources, mode, autonomy and temperament. The bootstrap
decision/resource contract requires user confirmation even in `full_auto`.

`project.mode=engineering` seeks gains and may borrow a genuinely fitting known
program. `project.mode=research` seeks gains plus an irreducible/paradigm M
kernel in every ordinary candidate, while portfolio policy separately enforces
scope breadth and constructive/theory-derived supply.

## Background workflow jobs

Workflow stages are registered runs. The engine prepares the RUN and immutable
attempt token before launch; bind the one accepted external job with the exact
`run-bind` command on the card. Never create a second job for one prepared RUN.
While one runs, `next` may issue work for other lanes/nodes up to the confirmed
slot count. When a job ends:

```bash
python <package>/engine/evo.py --repo <repo> run-update \
  --run RUN### --status finished --metrics-file <path> --ledger-file <path>
```

or:

```bash
python <package>/engine/evo.py --repo <repo> run-update \
  --run RUN### --status failed --failure-class infrastructure \
  --note "<observed error>"
```

For `--failure-class implementation`, also supply `--repair-scope
evaluation|workflow`. `evaluation` is legal only for an eval RUN whose fix
cannot affect prior workflow artifacts; a shared model, preprocessing,
training, or stage-code change is `workflow` even if evaluation exposed it.

Then run `next`. Report measurements and usage, not a self-invented
`passed`/`KILL`/continuation decision. When a node has a frozen continuation
gate, the engine computes it. A missed scientific prerequisite is still a
finished run and may become `screened_out`; do not misreport it as an execution
failure.

If execution finished but result bytes or a same-run probe arrive late, keep
the execution fact successful and attach evidence to that same attempt:

```bash
python <package>/engine/evo.py --repo <repo> run-reconcile \
  --run RUN### --metrics-file <late-path>
```

Do not retrain merely to recreate a missing return. An explicitly
unrecoverable registered probe is recorded on the same RUN with
`--accept-missing-probe --note ...`; any true repeat spend needs the engine's
gate.

## Work that is not a new idea

Not everything worth doing is a candidate. Three narrow doors exist, and part of
your job is knowing they are there: work that belongs behind one of them must
never be smuggled into a candidate idea, silently dropped, or reported to the
user as something the engine forbids. You propose; the user decides.

`probe` and `maintain` behave alike: level 0 on a single already-concluded
parent, no novelty claim, no research share, no scientific promotion, one per
round, and an idea approval that stays MANUAL even in `full_auto`.
`recover-plan` is not like them and the difference is safety-critical: it opens
no gate, consults no autonomy mode and has no per-round cap, so the engine will
not stop `recover-apply` for you. Present the plan and wait for the user
yourself.

```bash
python <package>/engine/evo.py --repo <repo> probe \
  --parent N### --question "<what measurement would settle this>"

python <package>/engine/evo.py --repo <repo> maintain \
  --parent N### --defect "<the mechanical flaw and what it blocks>"
```

- **`probe`** - you need a MEASUREMENT, not a mechanism. It must end in a
  recorded observation, it never enters a frontier and never becomes a parent.
  What bounds it is the resource cap declared in the design and approved at the
  gate: prefer answering from existing artifacts, but a probe MAY carry a short
  stage when the question needs one and the planned cost fits inside that cap.
  A mid-round "just check whether X still holds" from the user is this.
- **`maintain`** - shared execution code is mechanically broken and blocking
  work. The contract is preservation, not improvement: the engine settles parity
  over every decision cell, so a change meant to move measured behaviour is a
  candidate instead. `files_in_scope` is enforced - the engine diffs the workarea
  against the parent's reviewed commit and rejects executable edits outside it.
  A parity-met repair is frontier-transparent: later lanes inherit through it to
  the parent's standing, and `maintenance_gain` records the headroom it restored.
- **`recover-plan`** (next section) - an already-accepted authority was itself
  wrong. It is the only mechanism that RE-JUDGES a settled record. Maintenance
  never re-judges: it fixes the code going forward and leaves the parent's
  verdict standing.

Do not open a door to route around a rejected idea, a validator you disagree
with, or a stage you find slow; fix exactly what the deficiency list names. To
revise a rejected instrumental lane, reuse it:

```bash
python <package>/engine/evo.py --repo <repo> decide --gate G### --reject \
  --retry-stage probe_design|maintenance_design
```

Opening a replacement lane instead spends the round's only slot - the cap counts
lanes opened, abandoned ones included. `budgets.probes_max_per_round` and
`budgets.maintenance_max_per_round` set to 0 disable a door outright.

## Holds and recovery

For a suspected authority problem, use a scoped `hold`, then `recover-plan`.
Review the generated plan and apply only its exact digest with `recover-apply`.
An implementation recovery requires `--repair-scope evaluation|workflow`;
evaluation-only reuse is subject to the same protected-file audit as a failed
eval RUN and may widen only toward workflow.
Recovery is append-only forward repair: execution, cost, evidence and old
conclusions remain facts; corrected active outputs receive new revisions and
affected unsubmitted consumers are refreshed. Do not hand-restore old files.
If an applied recovery cannot complete, `recover-abort --abandon-node` is the
only escape. Accepted contracts or authority with hard downstream consumers
fork rather than mutate in place. An abandoned node's seals are historical and
cannot authorize work. An abandoned baseline terminates the current project;
after a closed round, accepted lane, or child consumes it, baseline correction
requires a project fork.

## User-visible communication

Terminal output is not automatically visible to the user.

- Every gate card contains an engine-generated `Report for the user` block.
  Relay it faithfully before asking for a decision.
- `.evo/views/DASHBOARD.html` is the live DAG, frontier, gate and run view.
  Point the user to it at startup and after each round.
- Temperament is `policy.preset=steady|balanced|frontier|custom`. Do not ask the
  user to tune coupled policy fields unless they explicitly choose `custom`.

## Role isolation

When subagents are available, use fresh context to preserve the intended
temporal boundary:

- repair `diagnose`: give a fresh diagnostician only its card and bundle;
- constructive `sketch`: give a fresh program synthesizer the card and bundle
  before candidate-specific reading;
- theory-derived `pose/theorize`: use a fresh theorist, then a different
  challenger;
- core-synthesis first `deep_read`: a reader who reconstructs actual work as
  M# facts; the later sketch role sees only the engine-projected anonymous
  palette, never the provenance sidecar;
- post-freeze `deep_read`: use a reader/analyst who treats candidates as fixed
  objects and tries to find collisions;
- `tournament` and `red_team`: use independent critics;
- `implement` and `fidelity`: do not let the builder certify its own build.

For `sketch`, `mature`, `plan_node` and implementation tasks, preserve the
machine-readable object exactly where the card says COPY or bind by digest.
Fresh prose never authorizes changing the frozen program.

Without subagents, execute the same separation yourself: read only the inputs
listed in the current bundle and do not import undeclared facts from earlier
roles.

## Scientific operating rules (v12)

- Bitwise parent reproduction was never an engine requirement; do not
  self-impose it. Comparability = frozen protocol + the parent's sealed
  metrics as comparator. Children share load-bearing lineage with parents and
  may own parts the parent lacks; attribution is settled by the registered
  arms/probes, never by a zero-initialized bolt-on shell.
- Measurement/instrument honesty reviews stay fully strict. Novelty reviews
  are calibrated: kill near-identity only, use the tournament card's
  operational emulation definition (a registered computation producing the
  load-bearing intermediate - function-class capacity is inadmissible), judge
  from-scratch roots against the published family's from-scratch results,
  crown survivors by expected gain (attribution cleanliness is a tiebreaker),
  one headline cell per lane.
- In research mode open at least one core_synthesis lane per round and run a
  measurement scout on the target cell before writing its BRIEF.
- Maintain `.evo/profile/FIELD_MAP.md` (cell x lever decision table, every
  line with an evidence pointer and grade A/B/C, dead levers recorded at
  their narrowest form, never fed into generator inputs). The map decides
  where to bet, never what to build.
- Derive every `budget.limits` from worst-case x1.3 and state the basis; the
  `stage_budget_tolerance` band is an escape valve, not a planning allowance.
- An over-cap finished RUN keeps its evidence pending: if the user accepts the actual
  cost, raise `stage_budget_tolerance` and `evo run-reconcile --run <RUN>` (same
  evidence adopted, no rerun); never discard or rerun it for a mis-derived cap.

## Honesty rules

- Never fabricate papers, quotes, metrics, files, commands, exit codes, SOTA
  numbers or resource use.
- Reconstruct a paper's actual computational work, not only its stated
  motivation. M# records must distinguish necessary core from support recipe
  and gain confounds.
- A relevant paper is unavailable only after the configured distinct retrieval
  attempts were actually made and recorded.
- Candidate collision judgments must bind the exact current digest. Similar
  titles or recycled K# labels are not identity.
- Smoke and toy checks are engine-executed. Do not claim they passed before the
  engine reports it.
- Fidelity quotes real code; validators string-check the snippets.
- Failed-run notes state the observed failure, not an inferred story.
- If a card requires a capability you lack, tell the user instead of simulating
  the result.

## Resume and repair

After a crash, compaction or new session, run `next`. If state appears
inconsistent, run:

```bash
python <package>/engine/evo.py --repo <repo> doctor
```

Do not reconstruct state from memory.
