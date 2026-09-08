---
name: clade
description: >
  Long-horizon evolution of an existing ML project through a DAG of typed
  scientific programs. The deterministic engine owns scheduling, the frozen
  effect/mechanism/theory contracts, the four invention routes, digest-bound
  prior-art audits, evaluation, resources, artifacts and gates. Use when the
  user asks to iterate on or systematically surpass an existing model over
  multiple rounds.
---

# CLADE

The engine at `<package>/engine/evo.py` owns the workflow. You execute one task
at a time. The complete operating contract is `OPERATOR_PROMPT.md` in the
package root; this skill is the short form.

## Standing operating contract

1. Run:

   ```bash
   python <package>/engine/evo.py --repo <repo> next
   ```

   It returns exactly one task card, a context bundle and declared outputs.
   Every card ends with `Doors open from here` - the side channels legitimate
   from that task (`... doors` prints the whole table).

2. Do exactly the returned card. Do not invent stages, reorder the route, reuse
   a remembered schema or write undeclared outputs. The current card wins over
   memory and intuition.

3. Before submitting, `... validate --task T####` dry-runs the exact same
   validators read-only - free, no attempt spent. Then:

   ```bash
   python <package>/engine/evo.py --repo <repo> submit --task T####
   ```

   If rejected, the listed deficiencies are the fix list, and every refusal
   names its exit. Never import engine modules or read engine source to
   pre-validate (engine source is readable only under the user-authorized
   deadlock protocol).

4. Never hand-edit engine-owned state (`.evo/state.json`, `graph.json`,
   `artifacts.json`, events, errors, lessons, `amendments.jsonl`, `views/`).
   User gates are decided by the user through `decide`, never by you.

5. After every acceptance, immediately run `next`. Stop only at an open user
   gate, `DONE`, an external-job wait with no other actionable work, a
   concrete onboarding question that requires the user, or an explicit
   STOP-and-ask instruction in the current card's body. "Enough work for this
   session" is not a valid protocol state.

The loop is `next -> work -> validate -> submit -> next`.

## Keep the scientific axes separate

- `intent` controls graph topology;
- `search_origin` controls the invention route;
- `change_scope` / L1-L4 is implementation breadth only;
- `novelty.kind` is the M judgment;
- `effect_case` is the E claim;
- `theory_role` and `theory_rigor` are the independent T claim.

A local program can be irreducible. A full rebuild can be a known composition.
A paradigm need not have a theorem. A derivation does not establish novelty.

## Respect route order

Repair: `diagnose -> deep_read -> sketch -> deep_read(collision audit) ->
tournament`. Constructive: `sketch -> deep_read(collision audit) ->
tournament`. Core synthesis: `deep_read (M# facts) -> engine freezes the
anonymous CORE_PALETTE -> sketch -> deep_read(full-provenance audit) ->
tournament`. Theory-derived: `pose -> theorize <-> challenge -> sketch ->
deep_read -> tournament`. After any tournament: `mature -> red_team -> gate ->
plan_node -> implement -> smoke -> fidelity -> rehearsal -> stages -> eval ->
conclude`. Every route gets an attempt-specific, digest-bound collision audit;
never reuse an old CA# for a resketch.

## How the science ledger settles

- Spend is checked before training, on the workflow gate: declared caps, the
  agent's `cost_estimate` (with its basis - rest it on the rehearsal's
  measured pace), what the rehearsal took, and the user's node ceiling
  (`resource_contract.node_ceiling`, user-set or estimated at the infra
  interview, with its source). Only the ceiling is compared: a cap or an
  estimate above it means a person decides even under full_auto. Launch on
  whatever devices are free under `resource_contract.max_devices`; fewer than
  planned still runs; deviations are recorded beside the run; a busy machine is
  `mode: busy` (no attempt spent). After training an overrun is a record beside
  the gain, not a veto.
- Two frontiers. The performance frontier is measurement only. The
  inheritance frontier is what a lane may build on: in research mode a node
  enters it when its claim stands (a claimed cell really rose and the user's
  vote passed inside the claimed groups) and its build is audited; mechanism
  knowledge never decides parenthood. Verdicts are engine-computed: `improved`
  (every claimed cell won, nothing lost), `specialist` (a declared subset won,
  nothing lost), `tradeoff` (the claim stands plus a loss elsewhere),
  `partial` (cells rose but the vote did not pass - re-scope with `evo claim`),
  `regressed` (nothing claimed won), `inconclusive`. Required cells and
  guardrails decide `deliverable`, never parenthood; the bet's record
  (`effect_contract_status`: met / partial / failed) stays as history and never
  vetoes; a resource overrun is written next to the gain, never a veto. The claim is
  program-level against the comparator's SEALED metrics; bitwise parent
  reproduction was never required, and a zero-initialized shell bolted onto
  the parent is never legal.
- Mechanism knowledge is two facts beside the node and never decides
  parenthood. A registered probe answers "does the model use the part" by its
  frozen rule (`probe_result`: confirmed/refuted/unclear; an aggregate inside
  its own seed scatter of the line is `unclear`) - information only. The
  causal status (`mechanism_status`) is `deferred` until a targeted ablation
  settles it, whatever the probe said; a refuted kernel bars premises on it
  and children carrying it (the control version is the code parent to build
  on). The inheritance tax:
  after a program-level win with a deferred mechanism the engine opens the
  targeted ablation itself (research mode; one for every such win), sized inside
  `evidence_policy.ablation.budget_multiple` x what the parent cost (at least
  one retrain when > 0; 0 = mechanisms stay deferred); inside the allowance
  its gates follow the ordinary autonomy policy, above it the user decides;
  `settles_parent_mechanism` in the design writes the answer back onto the
  parent (`confirmed (via N0xx)`). If the engine could not open it, the
  acceptance says why and the next round's doors list it; `evo ablate` is the
  manual door. Losers get no autopsy. An unsettled mechanism is never a
  planning premise: a lane that builds on a node's MECHANISM declares
  `mechanism_premises` and is refused until it reads confirmed; building on
  its PROGRAM needs nothing.
- Notebook versus history. History: what was bet at production launch (claim,
  scope, decision rules, instrumental contracts), what was measured, and the
  identity of an idea/node (program, kernel, lineage - a change there is a
  different idea, rewound or re-opened). Everything else is corrected on
  record with `... amend --path <file> --from <edited copy> --reason "..."`,
  history kept: briefs, an unlaunched bet, caps, unlaunched commands,
  smoke/rehearsal steps, and the world facts in `.evo/config.json` (noise
  floors, margins, required flags, goal lines, the ablation allowance) -
  forward-only, settled nodes keep the floor they were judged with.
  Reviewers see the history block (config facts under their own
  heading); a hand edit that bypasses `amend` is reported by doctor and leaves
  no reason on record; `evo autonomy` writes the same ledger. A RUN parked
  over a mis-derived cap is adopted by amending the cap and `run-reconcile`;
  nothing is rerun.
- Review calibration: measurement and instrument honesty fully strict; novelty
  judgment calibrated (kill on near-identity only, operational emulation
  definition, from-scratch roots judged against the published family's
  from-scratch results, survivors crowned by expected gain, one headline cell
  per lane). In research mode a core_synthesis lane and a measurement scout
  before a brief usually pay; blind lanes are legal. The engine renders
  `.evo/views/FIELD_MAP.md` (per-cell facts: best, published cap, gap,
  claimants with delta/verdict/mechanism, floor - every line a pointer); you
  may keep `.evo/profile/FIELD_NOTES.md` (short judgment per cell: live
  levers, dead forms in their narrowest form with a pointer, untried), which
  the view appends. Strategists and reviewers see both; the sketch generator
  sees neither. Derive `budget.limits` from worst case x1.3.

## Background workflow jobs

The engine prepares the RUN and attempt token before launch; bind the one
accepted job with the card's exact `run-bind`, report its end with
`run-update` (`--failure-class implementation` needs `--repair-scope
evaluation|workflow`), attach late evidence to the SAME run with
`run-reconcile`, and run `next`. Report measurements, never `passed`/`KILL`;
a missed continuation gate is a finished run the engine screens out.

## The doors

Four doors correct the record, one criterion each. `amend` - a fact was wrong.
`correct-instrument --node N### --proposal <file>` - the FORMULA was wrong:
the argument must hold whatever the result was; an independent session
judges, the user decides, the original readings are re-settled, never re-run;
symmetric. `claim --node N### --proposal <file>` - the LINE was mispriced or
scoped to the wrong cells: a new claim priced with the data in hand, settled
from the sealed metrics, labeled post-hoc, the user decides; the old verdict
is not re-judged because a choice is not an error. `hold` then
`recover-plan` - an accepted authority itself was wrong; it has no
engine-side gate, so present the plan and wait before `recover-apply`, and a
fork classification is terminal. `ablate`, `probe`, `maintain` each open one
lane per round on ONE concluded parent, riding on top of the round's search
bets; probe and maintenance gates are manual even in `full_auto`, an
ablation inside its allowance follows the ordinary autonomy policy;
`--retry-stage` rewinds a rejected one instead of spending a new slot.
`propose-abandon` asks the user to stop a dead direction; work continues
meanwhile. Do not open a door to route around a rejected idea, a validator
you disagree with, or a stage you find slow.

## Honesty rules

Never fabricate papers, quotes, metrics, files, commands, exit codes, SOTA
numbers or resource use. Reconstruct a paper's actual computation, not its
motivation. A paper is unavailable only after the configured retrieval attempts
were made and recorded. Smoke, rehearsal and canary runs are engine-executed.
Fidelity quotes real code and names every load-bearing addition beyond the
frozen program. Failed-run notes state the observed failure. Release verdicts
(tournament advance, red_team ACCEPT, challenge PROCEED, fidelity FAITHFUL,
instrument review FORMULA_ERROR) come from a session that did not author the
work, with its own `--session`.

## User-visible communication

Terminal output is not visible to the user. Relay every gate's `Report for the
user` block verbatim, point them to `.evo/views/DASHBOARD.html`, and describe
temperament as `policy.preset=steady|balanced|frontier|custom`.

## Resume and repair

After a crash, compaction or new session, run `next`. If state appears
inconsistent, run `... doctor`. Do not reconstruct state from memory.
