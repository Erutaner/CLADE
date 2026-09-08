# TASK {{TASK_ID}} - open round (role: research portfolio strategist)

Round {{ROUND_ID}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Objective
Place a small portfolio of bets that can expand the resource-normalized effect
frontier. `intent` controls DAG parent topology. `search_origin` independently
controls how the scientific program is invented:

- `repair`: one observed model is diagnosed before candidate synthesis and
  route-specific prior-art evidence. Use when a measured failure or bottleneck
  is the right search object.
- `constructive`: synthesize from task/data/evaluation/resource contracts and a
  code-grounded baseline program. It can edit one update law or rebuild every
  internal object. It is not bound to an incumbent B#/H#.
- `core_synthesis`: first reconstruct papers' actual computations, then let the
  engine expose only an anonymous `CORE_PALETTE` to synthesis. The sketch must
  transform multiple operational cores into a new relation; it does not see
  source identities, and palette membership never proves novelty.
- `theory_derived`: pose an obstruction/desiderata, derive and challenge a
  result, then synthesize programs satisfying its executable obligations.
  It must precommit `theory_rigor`: `partial` permits a scoped theorem or bound;
  `full` asks the engine to spend the deeper derivation/challenge budget needed
  for a theory-led result that can carry the work rather than decorate it.

`min_level` is only a minimum implementation-scope floor: configuration, local,
subsystem, or full-program. Theory and novelty are not inferred from it.
Research novelty independently requires an irreducible or paradigm kernel in
every non-platform candidate; engineering mode may legitimately use
composition. Platform lanes instead owe an enabling computation, explicit
operational/resources bounds and concrete falsifiable consumers.

## Engine-computed policy
{{POLICY_NOTES}}

Your bundle gives you four layers, and they answer four different questions.
**Origin**: where the user started - permanent comparator, never retired.
**Observed performance frontier**: what this project has actually measured. A
verdict judged against a node's own parent does NOT remove it from that list;
the node holding the cell records is often exactly there. **Active inheritance
frontier**: what may legally be exploited - in research mode that additionally
requires the frozen M/E/T claim to have settled. **Measured but not
inheritable**: real numbers with an unsettled or judged-against claim.
The field map (`.evo/views/FIELD_MAP.md`) lists, per cell, our best and its
holder, the published cap, the gap, who claimed the cell and what happened
(delta, verdict, mechanism), plus your own notes when
`.evo/profile/FIELD_NOTES.md` exists - bet where the gap and the untried
levers are.

Exploit parents come from the active inheritance frontier only. But a measured
node that is not inheritable is not waste: it is a legal reform or hybrid
parent and prime repair material, and `science=pending_evidence` means the
claim was never decided against - one missing measurement is blocking it, and
the bundle names which. EXCEPTION: a row marked `(archived - revive first)` or `(pruned - revive first)` is
retired and NOT a legal parent for any lane (reform/hybrid included) until the
user runs `evo revive`. If such a node is genuinely the right parent, STOP and
ask the user to run `evo revive --node <id> --note ...` (waiting for that
decision is a legitimate pause for this card; revive re-renders this card with
the node available). Do not spend an attempt on a portfolio that cites it
unrevived. Prefer reforming a strong unsettled result over
restarting from the origin. If the bundle says FLOOR IN FORCE, the origin is
the only legal exploit parent because nothing has settled yet - that is a
cold-start fallback, not a judgement that the origin is your best model.
Engineering mode uses the performance frontier as its active frontier.
Root wildcat/moonshot lanes have no model parent and must use constructive,
core-synthesis or theory-derived search. Baseline is later used only as code
provenance and external comparator. Hybrids must construct a new coupling, not
merely combine features.

Targeted ablation is a dedicated one-parent causal diagnostic with
min_level=0 - the inheritance tax. After a program-level win with a `deferred`
mechanism the engine opens it itself (research mode), and re-tries a pending one the moment
this round goes running (unless the round is held); declare one here only when the
bundle lists a PENDING ABLATION you want opened for certain (a declared lane
binds to that parent) or the next bet depends on that kernel being the
cause - never at every birth. Like probe and maintenance it rides ON TOP of the
search-bet count (no per-round cap: every program-level win owes one; probes and
maintenance keep their caps) and
never counts toward exploit-share or research-mix arithmetic. An unsettled
mechanism must not be cited as an established cause in a brief; settle it or
build on the program only.

## Outputs

For each lane, write a BRIEF with `## Goal`, `## Constraints`, and
`## Forbidden moves`. A repair brief targets B#/observed failure. A constructive
brief targets C#/external desiderata and may omit B#. A core-synthesis brief
states external C#/resource desiderata and the kind of relation sought, never a
named source mechanism. A theory-derived brief states the obstruction/question.
Never name a paper/technique.

Write `PORTFOLIO.json`:

```json
{"lanes": [{
  "name": "short-slug",
  "intent": "exploit|reform|wildcat|moonshot|hybrid|platform",
  "search_origin": "repair|constructive|core_synthesis|theory_derived",
  "theory_rigor": "partial|full (theory_derived only)",
  "experiment_purpose": "candidate|targeted_ablation|diagnostic_probe|maintenance|exploratory",
  "min_level": 3,
  "parents": ["N###"],
  "bottleneck_ids": ["repair only: B1"],
  "focus": "optional D#",
  "mechanism_premises": ["optional: N### whose MECHANISM this lane treats as an established cause; each must read confirmed on the frontier - a deferred/unclear/refuted story is refused (settle it with evo ablate first). Building on a node's PROGRAM needs no premise."],
  "scaling_followup_of": "optional N### - see below",
  "confirmatory_of": "optional N### (a concluded exploratory scout) - see below",
  "brief_md": ".evo/rounds/{{ROUND_ID}}/lanes/<name>/BRIEF.md"
}]}
```

Scaling follow-up: when a concluded node pre-registered `scaling` with
`execution: "followup_node"`, concluded with a POSITIVE verdict, and
scaling_mode is budgeted|full, open its scale extension as a NORMAL candidate
lane with `scaling_followup_of: "N###"` - intent exploit, that node as the
single parent AND effect comparator. Such a lane submits EXACTLY ONE program:
the parent's frozen kernel VERBATIM at the registered scale points
(`novelty.kind: "scaling_extension"`); the duplicate-kernel block is lifted
for exactly that kernel and nothing else, one follow-up per registered plan,
and its gates are always manual (it spends training on a duplicated kernel).

Confirmatory re-run: to put a SCOUTED effect on the record, open a full-rigor
candidate lane with `confirmatory_of: "N###"` naming a concluded exploratory
node. That lane pays every normal duty (predictions, SOTA, novelty prose -
no exemptions) and should cite the scout's OB### observations as grounding
(good practice, not a validated duty); in exchange the scout's kernel - and
only it - is exempt from the duplicate-kernel block.
The scout itself is never a model parent (observations are not lineage);
parent a normal record node. Confirmatory gates are always manual.

Parent topology: exploit/reform exactly one model parent; wildcat/moonshot no
model parent; hybrid >=2; platform none. Enabled platform parents may be added.
Wildcat/moonshot cannot use repair; hybrid cannot use repair. Research-mode
portfolio floors apply even to a one-lane round—there is no small-round escape.
For the frontier preset, a round with at least three non-platform idea lanes
must allocate at least the configured core-synthesis share; this is additional
idea supply, not permission to lower the M/E gate.

`exploratory` (declare at admission, ordinary slot, always a manual user
gate): a RECONNAISSANCE bet. It runs the full candidate route with novelty
duties intact, but maturation skips registered predictions/SOTA targets -
in exchange its results are OBSERVATIONS ONLY: excluded from every frontier
and record table, promotion pinned not_applicable, and it discharges NO
portfolio duty at all - research shares, wildcat-round L4 supply, stagnation
L3+/moonshot supply, exploit-share arithmetic and starved focus directions all
ignore scouts (any mandated lane must be a full-rigor bet); no research-share
credit,
and its conclusion MUST emit >= 1 phenomenon-ledger observation (OB###). To
put a scouted effect on the record, open a later confirmatory candidate that
cites those OB### and reproduces it under full pre-registration. Use it when
honest numeric foresight does not exist yet; do NOT use it to dodge rigor on
a claim you already believe - the user gate exists to catch exactly that.
Note: in a preplanned multi-seed project, scouts still run SINGLE-seed (cheap
reconnaissance); their OB### are single-run numbers and say so.

Published-territory tombstones: when the bundle carries a tombstones block,
each entry bounds what ONE published work absorbs - an equivalence class of
variants, never a direction. For every lane whose goal overlaps a criterion,
quote that criterion into the lane's brief under `forbidden moves`, together
with its semantics: "published territory - illegal as the claimed novelty
kernel, legal as a known component/support shell" (published means it works;
it just cannot be the flag). Lanes whose territory does not overlap must not
see it - do not paste the tombstone list wholesale into briefs. A criterion
is ONE work's absorption boundary, never a direction ban: if one reads
broader than a single published work could absorb, quote it verbatim anyway
and treat the overflow as open territory - never expand a criterion in your
own words. Reviewer notes on tombstones are your reference only and never go
into a brief; if a note points somewhere worth going, open an explicit lane
with that goal.

Instrumental lanes (`targeted_ablation`/`diagnostic_probe`/`maintenance`)
ride ON TOP of the lanes_per_round slot count: exploit intent, repair origin,
min_level 0, one concluded parent; probes and maintenance are capped per
round by budgets.probes_max_per_round / maintenance_max_per_round, ablations
are not (their off switch is evidence_policy.ablation.budget_multiple = 0).
They satisfy no research share. Probe and
maintenance gates are manual in every autonomy mode; an ablation inside its
allowance follows the ordinary autonomy policy, a larger one waits for the
user. They can also be opened mid-round, the moment the need appears:
`evo ablate` / `evo probe` / `evo maintain`.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
