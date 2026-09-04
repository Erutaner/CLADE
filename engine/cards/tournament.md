# TASK {{TASK_ID}} - program tournament (role: independent research critic)

Round: {{ROUND}} | lane: {{LANE}} | origin: {{SEARCH_ORIGIN}} | mode: {{MODE}} | lane intent: {{LANE_INTENT}}
(Exploratory lanes: frontier_refs may be empty - a scout binds no S# beat-claims;
audit mechanism honesty and coherence instead.)
Minimum implementation scope: L{{MIN_LEVEL}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Purpose

Audit the frozen work itself, not its motivation or prose. A research winner
must pass two independent hard gates: an irreducible, load-bearing kernel (M)
and a credible resource-normalized path to a frontier effect (E). Theory (T) is
reported separately and cannot rescue weak M or E.

For `core_synthesis`, the anonymous palette was generative material only. CP#
membership, the engine's provenance binding, and a well-written synthesis
relation contribute zero novelty credit. Judge the frozen KC#/OP# program
against named full-provenance M#/CA# neighbors using the same emulation,
neutralization and collage attacks as any other route.

Platform lanes are auxiliary experimental infrastructure, not model-effect
claims: still audit prior art, emulation, load-bearing structure and honest
scope, but omit the model `effect` gate. Their later mature contract must name
at least two concrete consumers/uses, and execution must prove those
capabilities before the platform can be enabled.

{{MODE_DUTY}}

## Audit each program

1. Bind the exact candidate digest and quote literal text from its JSON.
2. Reconstruct at least two nearest executable programs: one nearest on the
   mechanism axis and one nearest on the task/effect axis. Use E#/M# evidence,
   actual computations, necessary ablations, and resource confounds—not paper
   introductions. State why the search can stop at this neighbor set.
3. Build an emulation matrix against every nearest-neighbor paper and every
   other K# in the frozen set. In research mode, a published alternative that
   can reproduce the claimed core defeats novelty. In engineering mode it is
   legitimate borrowing; only same-set K# emulation prevents both entries from
   surviving as distinct programs.
   OPERATIONAL DEFINITION - what counts as emulation: the alternative's
   REGISTERED computation, as actually published or implemented, produces the
   same load-bearing intermediate on the same inputs. Function-class
   expressiveness arguments ("a trained X could in principle fit this",
   "the neighbor's architecture family can express it") are INADMISSIBLE as
   emulation grounds - by that standard a transformer is just an MLP. A
   `can_emulate=true` row's argument must name WHICH registered computation of
   the alternative produces WHICH load-bearing intermediate; an argument that
   only asserts representational capacity does not meet the >=80-char duty in
   substance and the kill it supports will not survive review.
4. Test removal, emulation, and collage separately. A+B parts that can improve
   independently are not an irreducible hybrid relation.
5. For non-platform programs, audit every KC# -> Z# -> C# link and the {{RESOURCE_AXES_COUNT}}
   resource axes against the candidate's frozen
   `matched|budgeted_tradeoff|efficiency` regime and fixed/tradeoff/improvement
   partition. The audit's `resource_status` is a feasibility judgment
   (`matched|advantaged|confounded|unknown`), not a second regime declaration;
   never turn unknown into matched by assertion. Platform programs omit this
   model-effect audit and instead justify their enabling computation.
   `comparator_valid` audits the declared baseline/scientific-parent reference
   as causal and resource context. Do not set it false merely because a
   stronger sibling or off-lineage result exists. Audit promotion separately:
   compare the complete claim-scoped result/resource vector with the strongest
   protocol-compatible observations supplied in the bundle and with the S#
   evidence in `frontier_refs`. A valid comparator may still accompany a
   `kill` when the candidate cannot plausibly expand the frontier; record that
   failure in `effect.argument`, `reason`, and survivor ranking. The narrow
   first-contact exception is stated in the bundle's `Lane admission policy`:
   a `wildcat|moonshot` candidate that is both `full_program` and `paradigm`
   may earn one experiment from a credible baseline-relative case after every
   ordinary hard gate, without pretending it already had a mature lineage's
   development history. Do not grant that exception to any other candidate.
6. When theory is claimed, name the executable choice it forces and a plausible
   alternative it rules out. For a theory-derived candidate, audit every
   frozen DO# row against the exact copied KC#/OP# refs; do not reinterpret the
   obligation or repair a weak mapping in review. A post-hoc explanation has
   `aligned=false`.

## Outputs

Write the JSON audit (no separate prose report is required):

```json
{
  "lane": "{{LANE}}",
  "program_set_digest": "copy VERBATIM from the bundle's `Frozen digests` block",
  "audits": [{
    "sketch_id": "K1",
    "program_digest": "that K#'s digest from the same block (engine canonical-JSON hashes - NEVER recompute from file bytes)",
    "quote": ">=6 literal words copied from the candidate JSON",
    "prior_art": {
      "neighbors": [
        {"paper": "E###", "axis": "mechanism", "core_work_cards": ["M###"],
         "collision_audits": ["current digest-bound CA###"],
         "program_overlap": ">=60 chars: shared executable computation",
         "irreducible_difference": ">=80 chars: remaining kernel difference"},
        {"paper": "E###", "axis": "task_effect", "core_work_cards": ["M###"],
         "collision_audits": ["current digest-bound CA###"],
         "program_overlap": ">=60 chars: shared task/effect computation",
         "irreducible_difference": ">=80 chars: remaining kernel difference"}
      ],
      "search_stop_reason": ">=80 chars: query coverage and why no closer program remains"
    },
    "emulation_matrix": [
      {"alternative": "E### or another K#", "can_emulate": false,
       "argument": ">=80 chars: exact operator/kernel comparison; for can_emulate=true it must name the alternative's registered computation and the load-bearing intermediate it actually produces - capacity/expressiveness claims are inadmissible"}
    ],
    "irreducibility": {
      "non_reducible": true, "load_bearing": true, "collage": false,
      "argument": ">=100 chars covering emulation, neutralization, and independent-part tests"
    },
    "scope": {
      "claimed_scope": "candidate.change_scope",
      "audited_scope": "configuration|local|subsystem|full_program",
      "train_semantics_preserved": false,
      "infer_semantics_preserved": false,
      "preserved_interfaces": ["external contracts that remain unchanged"],
      "argument": ">=100 chars: compare complete baseline and candidate train/infer semantics"
    },
    "effect": {
      "causal_chain_valid": true,
      "comparator_valid": true,
      "threshold_credible": true,
      "resource_status": "matched|advantaged|confounded|unknown",
      "resource_confounds": [],
      "resource_provenance": ">=80 chars: source/bound and frozen regime duty for every resource axis",
      "worst_case_bound": "required when unknown axes are still claimed advantageous",
      "frontier_refs": ["external S### entries fixed before selecting the winner; never N# nodes"],
      "argument": ">=100 chars: KC#->Z#->C#, frozen-reference audit, separate promotion audit, threshold, and costs"
    },
    "theory": {"status": "pending|supported", "argument": ">=60 chars; required when theory_role != none",
      "obligation_audit": [
        {"id": "theory_derived: exact DO#", "kernel_refs": ["exact KC# mapping"],
         "operator_refs": ["exact OP# mapping"], "aligned": true,
         "argument": ">=80 chars: why these operators satisfy the actual obligation"}
      ]},
    "decision": "advance|kill",
    "reason": ">=60 chars",
    "published_dup": "RESEARCH MODE, REQUIRED when a kill stands on published-work ground: the reason cites a CA###, OR a screened paper's emulation row (can_emulate=true) defeats the core. Three legal forms. (1) New boundary: {\"ca\": \"CA###\" (a collision audit bound to THIS audited candidate), \"tombstone\": \"<absorption criterion, >=60 chars, ONE physical line: the NARROWEST class of variations that ONE published work absorbs - anonymous (no ids/links/venues/method brand-names), never a direction, no untested-direction lists; beyond it you assert nothing>\"}. (2) Re-hit: {\"ca\": \"CA###\", \"known_tombstone\": \"TB###\"} when the bundle's tombstone list already bounds this territory. (3) Not the kill ground: {\"ca\": \"CA###\", \"decisive\": false, \"ground\": \">=60 chars: what actually killed it\"} when the citation/emulation is real but something else killed the candidate - never author a tombstone for a death the collision did not cause. Omit entirely for non-collision kills and in engineering mode (borrowing published work is legitimate there)."
  }],
  "survivor_ranking": [
    {"rank": 1, "sketch_id": "K3", "pareto_status": "nondominated|tradeoff",
     "argument": ">=80 chars: pairwise resource-normalized comparison with every survivor"}
  ],
  "winners": ["K3"]
}
```

The emulation matrix must contain one row for every distinct neighbor paper and
every other candidate K#. Scope of an emulation kill: it retires THIS
candidate's exact frozen contract and blocks THIS program's advance; it does
not close the kernel direction. A rejected direction may return under a
different contract and face the same audit fresh. (The core itself is retired
only by the candidate's OWN structural verdicts - non_reducible=false or
collage=true - or by a later review that proves identity: an N# graph node
carrying the identical frozen kernel, or a shallow finding naming the
candidate's own KC#.) A non-platform research program may advance only when
 `non_reducible=true`, `load_bearing=true`, `collage=false`, the typed effect
 chain survives, resources are `matched` or explicitly `advantaged`, no matrix
 alternative can emulate it, and any theory-derived obligation is supported.
All {{RESOURCE_AXES_COUNT}} frozen candidate and comparator resource values must be numeric before
a research program advances. `unknown` may remain on a killed draft, but the
post-run checker cannot settle prose; this is a pre-execution numeric cap duty,
not a demand for the candidate's future realized receipt. Use the supplied
sealed baseline/parent receipt to ground comparator estimates: every numeric
comparator value must lie inside its already-realized sealed interval.
The frozen causal/resource comparator and the promotion frontier are different
contracts. A stronger non-parent N# can defeat promotion and therefore kill a
program, but cannot by itself make the frozen comparator invalid; conversely a
valid comparator does not establish frontier expansion. `frontier_refs` remain
S# literature records and never carry graph-node IDs.
Platform programs omit that model-effect conjunction and advance only on the
prior-art, emulation, scope and enabling-capability audit stated above.
Engineering mode may advance a well-fitted borrowed published program; an E#
alternative's ability to emulate it is not a novelty veto there. Two K# entries
in this same frozen set still cannot occupy separate survivor slots when one
emulates the other. Among ordinary surviving programs choose the strongest
resource-normalized frontier expansion. For the explicitly eligible
first-contact paradigm-root path, rank the credible baseline-relative programs
without converting a mature N# into an age-blind birth threshold. `winner` must
be rank 1, the ranking covers every program marked advance, and non-empty
survivors require exactly one winner. A post-program theory is `pending` here; only theory-derived work can
already be `supported`, and it advances only when every frozen DO# mapping is
audited aligned. Omit `obligation_audit` on repair/constructive/core-synthesis candidates:
their optional T claim is still pending and cannot rewrite the program. Zero
winners is legal only when every program was killed. Ranked survivors after the
winner are real fallbacks: if an earlier rank is terminally rejected before
execution, the engine activates the next rank without rerunning this tournament.

## Output contract

{{OUTPUTS}}

## Submit

{{SUBMIT_CMD}}
