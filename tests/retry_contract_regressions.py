#!/usr/bin/env python3
"""Focused regressions for lane recovery context and comparator roles."""
from __future__ import annotations

import copy
import json
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG / "engine"))

import ebundle  # noqa: E402
import eprogram  # noqa: E402
import eseal  # noqa: E402
import esched  # noqa: E402
import evalid  # noqa: E402


CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[check {CHECKS}] {message}")


def write(repo: Path, rel: str, text: str = "fixture\n") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def recovery_context_checks() -> None:
    scratch_root = HERE / "out"
    scratch_root.mkdir(parents=True, exist_ok=True)
    fixture = scratch_root / "retry_contract_fixture"
    fixture.mkdir(parents=True, exist_ok=True)
    with nullcontext(str(fixture)) as raw:
        repo = Path(raw)
        paths = [
            "artifacts/R002/L007/TOURNAMENT_c1.json",
            "artifacts/R002/L007/TOURNAMENT_c1.md",
            "artifacts/I011.review.md",
            "artifacts/R002/L007/TOURNAMENT_c2.json",
            "artifacts/R002/L007/TOURNAMENT_c2.md",
            "artifacts/R002/L007/TOURNAMENT_c3.json",
            "artifacts/R002/L007/TOURNAMENT_c3.md",
        ]
        for rel in paths:
            write(repo, rel)

        engine = object.__new__(esched.Engine)
        engine.store = SimpleNamespace(repo=repo)
        engine.st = {"gates": [
            {"id": "G008", "kind": "escalation", "status": "approved",
             "subject": {"lane": "L007", "resume_stage": "sketch"},
             "decision_note": "older direction must be shadowed"},
            {"id": "G010", "kind": "escalation", "status": "approved",
             "subject": {"lane": "L007", "resume_stage": "sketch"},
             "decision_note": "read every prior audit before generating a new program"},
            {"id": "G011", "kind": "escalation", "status": "approved",
             "subject": {"lane": "L999", "resume_stage": "sketch"},
             "decision_note": "OTHER_LANE_SENTINEL"},
        ]}
        lane = {
            "id": "L007",
            "cycles": {"sketch": 3},
            "attempts": [
                {"verdict": "REJECT_SHALLOW", "tournament": paths[0],
                 "review": paths[2]},
                {"verdict": "all_killed", "tournament": paths[3]},
                {"verdict": "all_killed", "tournament": paths[5]},
            ],
        }

        summary = engine._sketch_failure_summary(lane)
        check("red-team REJECT_SHALLOW: 1" in summary
              and "tournament all-killed: 2" in summary,
              f"mixed failure summary must preserve the real sources: {summary}")
        check("tournament killed all sketches 3 times" not in summary,
              "mixed failure summary must not invent three tournament failures")
        gate_message = engine._sketch_escalation_message(lane)
        check("red-team REJECT_SHALLOW: 1" in gate_message
              and "tournament all-killed: 2" in gate_message
              and "same sealed lane" in gate_message,
              f"the actual escalation text must report causes and retry semantics: {gate_message}")

        blocks = engine._sketch_retry_blocks(lane)
        rendered = "\n".join(line for _title, lines in blocks for line in lines)
        for rel in paths:
            check(rendered.count(rel) == 1, f"all existing audit paths must appear once: {rel}")
        check(rendered.index(paths[0]) < rendered.index(paths[3]) < rendered.index(paths[5]),
              "historical audits must remain oldest-first")
        check("read every prior audit before generating a new program" in rendered,
              "the latest approved sketch-retry direction must be routed")
        check("older direction must be shadowed" not in rendered
              and "OTHER_LANE_SENTINEL" not in rendered,
              "retry directions must not leak across epochs or lanes")
        check("/TOURNAMENT.md" not in rendered,
              "the removed nonexistent generic tournament path must not reappear")

        # A later decision for another stage must not erase the still-active
        # sketch retry direction; stage counters define separate epochs.
        engine.st["gates"].append(
            {"id": "G012", "kind": "escalation", "status": "approved",
             "subject": {"lane": "L007", "resume_stage": "mature"},
             "decision_note": "mature-only direction"})
        shadowed = "\n".join(line for _title, lines in engine._sketch_retry_blocks(lane)
                              for line in lines)
        check("read every prior audit" in shadowed and "mature-only direction" not in shadowed,
              "a differently staged escalation must neither shadow nor leak into sketch guidance")

        reset_lane = {"cycles": {"sketch": 3},
                      "attempts": lane["attempts"] + [{"verdict": "all_killed"}] * 3}
        reset_summary = engine._sketch_failure_summary(reset_lane)
        check("tournament all-killed: 3" in reset_summary
              and "REJECT_SHALLOW" not in reset_summary,
              "gate diagnostics must use only the current reset epoch")
        partial = engine._sketch_failure_summary(
            {"cycles": {"sketch": 3}, "attempts": [{"verdict": "all_killed"}]})
        check("unclassified: 2" in partial,
              "legacy state with missing records must stay generic rather than invent a cause")


def comparator_contract_checks() -> None:
    cfg = {
        "metrics": [{"key": "acc", "direction": "max"}],
        "evaluation_contract": {
            "cells": [{"id": "C1", "role": "target", "metric": "acc",
                       "result_key": "acc", "min_improvement": 0.01}],
        },
    }
    def resources(value: float) -> dict:
        return {axis: {"lower": value, "upper": value, "source": f"receipt:{axis}"}
                for axis in eprogram.RESOURCE_AXES}

    def observed(nid: str, role: str, verdict: str, score: object, cost: float,
                 **extra: object) -> dict:
        return {
            "id": nid, "role": role, "status": "concluded", "verdict": verdict,
            "scores": {"acc": score} if isinstance(score, (int, float)) else {},
            "score_evidence": {"acc": score} if isinstance(score, dict) else {},
            "effect_resources_realized": resources(cost),
            "resource_receipt_path": f".evo/nodes/{nid}/RESOURCE_RECEIPT_r1.json",
            "resource_receipt_seal": {"digest": f"seal-{nid}"},
            "result_doc": f".evo/nodes/{nid}/NODE_RESULT.md",
            "parents": [], "experiment_purpose": "candidate", **extra,
        }

    graph = {"nodes": [
        observed("N001", "baseline", "baseline", 0.70, 10),
        observed("N002", "variant", "improved",
                 {"value": 0.82, "uncertainty": {"lower": 0.78, "upper": 0.84}}, 100),
        observed("N003", "root", "tradeoff", 0.79, 1),
        observed("N004", "variant", "improved", 0.99, 0.5,
                 experiment_purpose="targeted_ablation"),
        observed("N005", "platform", "enabled", 1.0, 0.1),
    ]}
    preplanned_cfg = copy.deepcopy(cfg)
    preplanned_cfg["evidence_policy"] = {"training_replication": {"mode": "preplanned"}}
    block = "\n".join(ebundle.promotion_reference_block(graph, preplanned_cfg))
    check("not legal values for effect_case.comparator_id" in block,
          "observed promotion references must be explicitly separated from the effect comparator")
    check("N002 generation=" in block and "N003 generation=" in block
          and "N004" not in block and "N005" not in block,
          f"preplanned replication must exclude one-run ablations but retain complete Pareto tradeoffs: {block}")
    check("do not combine the best cell from different rows" in block,
          "promotion evidence must not synthesize a fictitious per-cell incumbent")
    record_only_block = "\n".join(ebundle.promotion_reference_block(graph, cfg))
    check("N004 generation=" in record_only_block,
          "record_only policy must not hide a real Pareto ablation measurement from promotion context")

    sketch = (PKG / "engine" / "cards" / "sketch.md").read_text(encoding="utf-8")
    tournament = (PKG / "engine" / "cards" / "tournament.md").read_text(encoding="utf-8")
    red_team = (PKG / "engine" / "cards" / "red_team.md").read_text(encoding="utf-8")
    architecture = (PKG / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    check("A root lane therefore uses `baseline`" in sketch,
          "the architect card must state the root causal comparator contract")
    check("A valid comparator may still accompany a" in tournament
          and "`kill` when the candidate cannot plausibly expand the frontier" in tournament
          and "cannot by itself make the frozen comparator invalid" in tournament,
          "the tournament card must separate comparator validity from promotion")
    check("does not by itself invalidate the frozen comparator" in red_team,
          "red-team must preserve the same comparator/promotion separation")
    check("Promotion is a separate pre-execution question" in architecture,
          "architecture must document the two contracts")

    # Exercise the real red-team scheduler branch, not just its card text: the
    # critic must receive the frozen selection audit plus both internal and
    # external promotion evidence without changing the effect comparator.
    engine = object.__new__(esched.Engine)
    engine.cfg = {
        **cfg,
        "project": {"mode": "research"},
        "research": {"sota_enabled": True},
    }
    engine.g = graph
    engine.st = {"runs": [], "gates": []}
    engine.reg = {}
    engine.store = SimpleNamespace(
        repo=PKG,
        get_run=lambda _st, _rid: None,
    )
    engine._lane_dir = lambda _lane: ".evo/rounds/R001/lanes/L001"
    engine.node = lambda _nid: None
    engine._lane_common_inputs = lambda _lane: [(".evo/config.json", "project contract")]
    engine._create_task = lambda kind, subject, outputs, **kwargs: {
        "kind": kind, "subject": subject, "outputs": outputs, **kwargs}
    engine._present_task = lambda task: task
    lane = {"id": "L001", "round": "R001", "status": "red_team",
            "intent": "root", "min_level": 3, "idea": "I001", "parents": [],
            "search_origin": "constructive",
            "tournament_path": ".evo/rounds/R001/lanes/L001/TOURNAMENT_c1.json"}
    task = engine._next_lane_task(lane)
    input_paths = [path for path, _role in task["inputs"]]
    block_titles = [title for title, _lines in task["extra_blocks"]]
    check(lane["tournament_path"] in input_paths,
          "red-team bundle must receive the frozen tournament audit")
    check(".evo/evidence/SOTA.jsonl" in input_paths,
          "SOTA-enabled red-team bundle must receive the external promotion library")
    check("Observed promotion references (NOT effect comparators)" in block_titles,
          "red-team bundle must receive graph promotion evidence under a non-comparator label")
    check("Lane admission policy" in block_titles,
          "red-team must receive the same lane-aware admission rule as tournament")


class FixtureStore:
    def __init__(self, repo: Path, *, evidence=None, cards=None, collisions=None):
        self.repo = repo
        self.evo = repo / ".evo"
        self._evidence = evidence or []
        self._cards = cards or []
        self._collisions = collisions or []
        self.events = []

    def evidence(self):
        return self._evidence

    def mech_cards(self):
        return self._cards

    def collision_audits(self):
        return self._collisions

    def get_lane(self, st, lane_id):
        return next((lane for lane in st.get("lanes", []) if lane.get("id") == lane_id), None)

    def get_run(self, st, run_id):
        return next((run for run in st.get("runs", []) if run.get("id") == run_id), None)

    def event(self, *args, **kwargs):
        self.events.append((args, kwargs))


def candidate(sid: str, marker: str, *, theory_role: str = "none",
              unknown: bool = False) -> dict:
    values = {axis: ("unknown" if unknown else 10.0) for axis in eprogram.RESOURCE_AXES}
    return {
        "sketch_id": sid, "change_scope": "full_program",
        "program": {
            "scientific_parents": [],
            "operators": [{"id": "OP1", "kind": "update", "phase": "both",
                           "semantics": f"{marker} operator performs the frozen candidate update"}],
        },
        "novelty": {
            "kind": "paradigm",
            "bearer": f"{marker} is the exact load bearing relation used by this candidate program",
            "kernel": [{"id": "KC1", "kind": "update_law",
                        "statement": f"{marker} changes the learned state and deployed prediction through one relation",
                        "operator_refs": ["OP1"]}],
        },
        "effect_case": {
            "comparator_id": "baseline",
            "chain": [{"id": "Z1", "kernel_refs": ["KC1"], "target_cell": "C1",
                       "direction": "increase", "minimum_worthwhile_delta": 0.01,
                       "expected_delta_interval": [0.01, 0.03]}],
            "predicted_gain": f"{marker} predicts a baseline-relative gain under the frozen resource vector",
            "resources": {"regime": "matched", "candidate": dict(values),
                          "comparator": dict(values), "fixed_axes": list(eprogram.RESOURCE_AXES),
                          "tradeoff_axes": [], "improvement_axes": []},
        },
        "claim_scope": {"kind": "generalist", "target_cells": ["C1"],
                        "guardrail_cells": []},
        "theory_role": theory_role,
    }


def survivor_lifecycle_checks() -> None:
    fixture = HERE / "out" / "survivor_lifecycle_fixture"
    fixture.mkdir(parents=True, exist_ok=True)
    programs_rel = ".evo/rounds/R001/lanes/L001/PROGRAMS_c1.json"
    tournament_rel = ".evo/rounds/R001/lanes/L001/TOURNAMENT_c1.json"
    programs = [candidate("K1", "rank one"),
                candidate("K2", "rank two", theory_role="explanatory"),
                candidate("K3", "rank three")]
    write(fixture, programs_rel, json.dumps({"sketches": programs}))
    write(fixture, tournament_rel, json.dumps({
        "survivor_ranking": [
            {"rank": 1, "sketch_id": "K1"}, {"rank": 2, "sketch_id": "K2"},
            {"rank": 3, "sketch_id": "K3"}], "winners": ["K1"]}))
    store = FixtureStore(fixture)
    engine = object.__new__(esched.Engine)
    engine.store, engine.st, engine.cfg = store, {"lanes": [], "runs": []}, {}
    engine.g, engine.reg = {"nodes": []}, {}
    lane = {
        "id": "L001", "search_origin": "constructive", "status": "red_team",
        "sketches_path": programs_rel, "program_set_digest": "batch-digest",
        "tournament_path": tournament_rel, "winner_sketch": "K1",
        "winner_program_digest": eprogram.candidate_digest(programs[0]),
        "winner_kernel_hash": eprogram.kernel_fingerprint(programs[0]),
        "program_seal": {"digest": "program-seal", "status": "active"},
        "tournament_seal": {"digest": "tournament-seal", "status": "active"},
        "idea": "I001", "idea_seal": {"digest": "idea-1"},
        "review_seal": {"digest": "review-1"}, "seal_history": [],
        "idea_revisions": [], "attempts": [],
        "cycles": {"sketch": 0, "mature": 2, "theory": 2},
        "theory_path": "old-theory.md", "problem_path": "old-problem.md",
        "theory_seal": {"digest": "old-theory-seal"}, "problem_seal": {"digest": "old-problem-seal"},
        "theory_draft_seal": None, "theory_required": True,
        "theory_claim_status": "supported", "theory_downgraded": False,
        "formal": True, "formal_kind": "partial", "theory_head_ready": True,
        "theory_cycle": 2, "required_topics": ["old candidate topic"],
        "resume_after_read": "theorize",
    }
    program_seal = copy.deepcopy(lane["program_seal"])
    tournament_seal = copy.deepcopy(lane["tournament_seal"])
    check(engine._advance_ranked_survivor(
        lane, verdict="REJECT_NOT_COMPARABLE", review="I001.review.md"),
        "rank one terminal rejection must activate rank two")
    check(lane["winner_sketch"] == "K2" and lane["status"] == "theorize",
          "rank two must run its own explanatory-theory route")
    check(lane["program_seal"] == program_seal and lane["tournament_seal"] == tournament_seal
          and lane["sketches_path"] == programs_rel and lane["tournament_path"] == tournament_rel,
          "rank fallback must preserve the exact sealed batch")
    check(lane["cycles"]["sketch"] == 0 and lane["cycles"]["mature"] == 0,
          "candidate fallback must reset local maturation without spending a sketch batch")
    check(lane["idea_revisions"][0]["winner"] == "K1"
          and lane["idea_revisions"][0]["winner_program_digest"] == eprogram.candidate_digest(programs[0]),
          "the rejected survivor must retain an immutable candidate-specific disposition")

    lane.update({"idea": "I002", "idea_seal": {"digest": "idea-2"},
                 "review_seal": {"digest": "review-2"},
                 "theory_path": "k2-theory.md", "theory_seal": {"digest": "k2-theory"},
                 "theory_claim_status": "supported", "theory_head_ready": True,
                 "cycles": {"sketch": 0, "mature": 1, "theory": 1}})
    check(engine._advance_ranked_survivor(
        lane, verdict="REJECT_INFEASIBLE", review="I002.review.md"),
        "rank two terminal rejection must activate rank three")
    check(lane["winner_sketch"] == "K3" and lane["status"] == "mature"
          and lane["theory_path"] is None and lane.get("theory_seal") is None,
          "candidate-owned theory must not leak into the next ranked survivor")
    check(not engine._advance_ranked_survivor(
        lane, verdict="REJECT_SHALLOW", review="I003.review.md"),
        "the last ranked survivor must report batch exhaustion")
    lane.update({"idea": "I003", "idea_seal": {"digest": "idea-3"},
                 "review_seal": {"digest": "review-3"}})
    engine._prepare_resynthesis(lane, verdict="REJECT_SHALLOW", review="I003.review.md")
    check(lane["cycles"]["sketch"] == 1 and len(lane["attempts"]) == 1,
          "only exhaustion of all ranked survivors may consume one resynthesis budget")
    check(lane["sketches_path"] is None and lane["tournament_path"] is None
          and lane["winner_sketch"] is None,
          "exhausted batch must be cleared exactly once")


def retry_binding_checks() -> None:
    fixture = HERE / "out" / "retry_binding_fixture"
    fixture.mkdir(parents=True, exist_ok=True)

    # Artifact sequence is lane-global (never overwrite), while cycle is local
    # to the active survivor.  A K2 retry must quote K2's c2 challenge, not
    # K1's c1 challenge merely because this is K2's local cycle 2.
    old_challenge = ".evo/rounds/R001/lanes/L001/CHALLENGE_c1.md"
    current_challenge = ".evo/rounds/R001/lanes/L001/CHALLENGE_c2.md"
    theory_path = ".evo/rounds/R001/lanes/L001/THEORY_c3.md"
    write(fixture, old_challenge,
          "the earlier survivor failed for an unrelated obsolete mechanism objection\n")
    literal = "the current survivor must justify all six frozen causal links"
    write(fixture, current_challenge, literal + " before its resource claim can survive\n")
    pad = "This explicit derivation sentence states a premise consequence and falsifiable boundary. "
    theory = "\n\n".join([
        "## Obstruction or desiderata\n\n" + pad * 2,
        "## Result\n\n" + pad * 2,
        "## Derivation\n\nA1: frozen premise. A2: comparator premise. " + pad * 7,
        "## Design consequences\n\n" + pad * 2,
        "## Ruled-out alternatives\n\n" + pad * 2,
        "## Executable obligations\n\n- DO1: " + pad + "\n- DO2: " + pad,
        "## Discriminating predictions\n\nTP1: " + pad + "\nTP2: " + pad,
        "## Scope and failure conditions\n\n" + pad * 2,
        "## Response to challenge\n\nQUOTE: " + literal + "\n" + pad * 2,
    ])
    write(fixture, theory_path, theory)
    lane = {"id": "L001", "round": "R001", "formal": False,
            "winner_sketch": None, "theory_cycle": 2, "theory_seq": 2}
    store = FixtureStore(fixture)
    ctx = evalid.Ctx(store, {"lanes": [lane]}, {"budgets": {}}, {"nodes": []}, {})
    task = {"subject": {"lane": "L001", "cycle": 2, "artifact_seq": 3,
                        "previous_challenge": current_challenge},
            "outputs": [theory_path]}
    errs = evalid.v_theorize(ctx, task)
    check(not any("THEORY.response" in err or err.startswith("THEORY_RESPONSE_BINDING") for err in errs),
          f"candidate-local retry must validate against its exact engine-bound challenge: {errs}")
    theorize_card = (PKG / "engine" / "cards" / "theorize.md").read_text(encoding="utf-8")
    check("{{THEORY_OUTPUT}}" in theorize_card and "THEORY_c{{CYCLE}}" not in theorize_card,
          "theory card must not confuse a local retry cycle with global artifact identity")

    # Red-team revisions are routed only to the same frozen survivor.
    review_a = ".evo/ideas/I001.review.md"
    review_b = ".evo/ideas/I002.review.md"
    review_other = ".evo/ideas/I003.review.md"
    for rel in (review_a, review_b, review_other):
        write(fixture, rel, "review\n")
    engine = object.__new__(esched.Engine)
    engine.store = store
    engine.st = {"gates": [
        {"id": "G1", "kind": "idea_approval", "status": "rejected",
         "subject": {"lane": "L001", "winner_program_digest": "digest-a"},
         "retry_stage": "mature", "decision_note": "repair the exact effect argument"},
        {"id": "G2", "kind": "idea_approval", "status": "rejected",
         "subject": {"lane": "L999", "winner_program_digest": "digest-a"},
         "retry_stage": "mature", "decision_note": "other lane"},
    ]}
    revision_lane = {"id": "L001", "winner_program_digest": "digest-a",
                     "idea_revisions": [
                         {"idea": "I001", "winner_program_digest": "digest-a",
                          "review": review_a, "verdict": "REVISE"},
                         {"idea": "I002", "winner_program_digest": "digest-a",
                          "review": review_b, "verdict": "REVISE"},
                         {"idea": "I003", "winner_program_digest": "digest-b",
                          "review": review_other, "verdict": "REJECT_SHALLOW"}]}
    routed = "\n".join(line for _title, lines in engine._winner_revision_blocks(revision_lane)
                         for line in lines)
    check(review_a in routed and review_b in routed and review_other not in routed,
          "maturation must retain every same-survivor review without leaking another rank's critique")
    direction = "\n".join(line for _title, lines in engine._retry_direction_blocks(
        revision_lane, "mature") for line in lines)
    check("repair the exact effect argument" in direction and "other lane" not in direction,
          "manual retry direction must bind the exact lane, survivor and stage")

    # A theory-derived lane has no winner digest before program synthesis; its
    # approved challenge-escalation note is therefore bound by lane+stage.
    engine.st["gates"].append({
        "id": "G3", "kind": "escalation", "status": "approved",
        "subject": {"lane": "L002", "resume_stage": "theorize",
                    "winner_program_digest": None},
        "decision_note": "repair the source derivation before proposing any program"})
    pre_program_direction = "\n".join(
        line for _title, lines in engine._retry_direction_blocks(
            {"id": "L002", "winner_program_digest": None}, "theorize") for line in lines)
    check("repair the source derivation" in pre_program_direction,
          "pre-program theory retry notes must not disappear merely because no winner digest exists yet")

    # Targeted-ablation REVISE allocates a new I#, so the old design, contract
    # and review must be recovered from lane revision state rather than by
    # looking for a review under the new id.
    old_ablation = "I010"
    old_ablation_review = f".evo/ideas/{old_ablation}.ablation-review.md"
    write(fixture, f".evo/ideas/{old_ablation}.md", "old causal design\n")
    write(fixture, f".evo/ideas/{old_ablation}.meta.json", "{}")
    write(fixture, old_ablation_review, "review the X1/X2 decision map\n")
    ablation_lane = {"id": "L003", "winner_program_digest": None,
                     "experiment_purpose": "targeted_ablation",
                     "idea_revisions": [{"idea": old_ablation, "verdict": "REVISE",
                                         "review": old_ablation_review}]}
    engine.st["gates"].append({
        "id": "G4", "kind": "idea_approval", "status": "rejected",
        "subject": {"lane": "L003", "winner_program_digest": None},
        "retry_stage": "ablation_design",
        "decision_note": "redesign the single intervention without adding another arm"})
    ablation_history = "\n".join(
        line for _title, lines in engine._instrumental_revision_blocks(ablation_lane) for line in lines)
    ablation_direction = "\n".join(
        line for _title, lines in engine._retry_direction_blocks(
            ablation_lane, "ablation_design") for line in lines)
    check(f".evo/ideas/{old_ablation}.md" in ablation_history
          and old_ablation_review in ablation_history,
          "a new ablation I# must receive the superseded design and its actual review")
    check("redesign the single intervention" in ablation_direction,
          "an ablation user retry note must route without a nonexistent winner digest")

    # Maintenance and probe redrafts must recover the superseded design the same
    # way.  A REVISE nulls lane["idea"], so the branch that looked for a review
    # under the FRESHLY minted id could never find one; only idea_revisions has
    # the real paths.  Ablation always had this; the other two did not.
    for purpose, suffix in (("maintenance", ".maintenance-review.md"),
                            ("diagnostic_probe", None)):
        old_id = "I02" + ("1" if purpose == "maintenance" else "2")
        old_review = f".evo/ideas/{old_id}{suffix}" if suffix else ""
        write(fixture, f".evo/ideas/{old_id}.md", "superseded instrumental design\n")
        write(fixture, f".evo/ideas/{old_id}.meta.json", "{}")
        if old_review:
            write(fixture, old_review, "answer these objections\n")
        lane_i = {"id": "L00" + ("4" if purpose == "maintenance" else "5"),
                  "winner_program_digest": None, "experiment_purpose": purpose,
                  "idea_revisions": [{"idea": old_id, "verdict": "REVISE",
                                      "review": old_review or None}]}
        history = "\n".join(line for _t, lines in engine._instrumental_revision_blocks(lane_i)
                            for line in lines)
        check(f".evo/ideas/{old_id}.md" in history,
              f"a {purpose} redraft must receive its superseded design: {history!r}")
        if old_review:
            check(old_review in history,
                  f"a {purpose} redraft must receive the review written under the OLD id: {history!r}")
    # A candidate lane has its own survivor-review machinery and must not pick up
    # the instrumental block.
    check(engine._instrumental_revision_blocks(
        {"id": "L006", "experiment_purpose": "candidate",
         "idea_revisions": [{"idea": "I021", "verdict": "REVISE", "review": None}]}) == [],
          "the instrumental revision block must not fire on a candidate lane")

    # Approving a validation escalation resets the count, not the diagnosis.
    failed_task = {"id": "T001", "type": "mature", "attempts": 3,
                   "status": "stuck", "last_errors": ["IDEA_PROGRAM_DRIFT: exact failure"],
                   "_render": {"extra_blocks": [("Existing context", ["- keep me"])]}}
    events = []
    retry_store = SimpleNamespace(
        get_task=lambda _st, tid: failed_task if tid == "T001" else None,
        event=lambda *args, **kwargs: events.append((args, kwargs)))
    retry_engine = object.__new__(esched.Engine)
    retry_engine.store = retry_store
    retry_engine.st = {"tasks": [failed_task]}
    retry_engine._rematerialize = lambda _task: None
    gate = {"id": "G100", "kind": "escalation", "status": "open",
            "subject": {"task": "T001"}}
    retry_engine._decide_gate(gate, approve=True,
                              note="use the frozen winner instead of rewriting it",
                              actor="user")
    retry_blocks = failed_task["_render"]["extra_blocks"]
    check(failed_task["attempts"] == 0 and failed_task["status"] == "open"
          and failed_task["last_errors"] == ["IDEA_PROGRAM_DRIFT: exact failure"],
          "task escalation must reset only the counter and preserve the exact validation diagnosis")
    check(any(title == "Approved task retry direction" and "frozen winner" in " ".join(lines)
              for title, lines in retry_blocks),
          "approved task retry must receive the user's task-bound direction")

    counter_lane = {"id": "L010", "status": "mature",
                    "cycles": {"sketch": 2, "mature": 3, "theory": 2, "ablation": 1}}
    counter_store = FixtureStore(fixture)
    counter_engine = object.__new__(esched.Engine)
    counter_engine.store, counter_engine.st = counter_store, {"lanes": [counter_lane]}
    counter_gate = {"id": "G101", "kind": "escalation", "status": "open",
                    "subject": {"lane": "L010", "resume_stage": "mature"}}
    counter_engine._decide_gate(counter_gate, approve=True, note="retry maturation", actor="user")
    check(counter_lane["cycles"] == {"sketch": 2, "mature": 0, "theory": 2, "ablation": 1},
          "a mature escalation must not silently grant new sketch/theory/ablation budgets")
    gate_card = (PKG / "engine" / "cards" / "gate.md").read_text(encoding="utf-8")
    check("`theorize`" in gate_card and "`pose`" in gate_card and "derivational" in gate_card,
          "the operator gate card must expose the theory retry routes the engine actually supports")


def disposition_and_validator_checks() -> None:
    fixture = HERE / "out" / "disposition_fixture"
    fixture.mkdir(parents=True, exist_ok=True)
    program_rel = ".evo/rounds/R010/lanes/L010/PROGRAMS_c1.json"
    tournament_rel = ".evo/rounds/R010/lanes/L010/TOURNAMENT_c1.json"
    k1, k2, k3 = (candidate("K1", "formal survivor"),
                  candidate("K2", "effect only failure"),
                  candidate("K3", "mechanism failure"))
    write(fixture, program_rel, json.dumps({"sketches": [k1, k2, k3]}))
    write(fixture, tournament_rel, json.dumps({"audits": [
        {"sketch_id": "K1", "decision": "advance", "irreducibility": {
            "non_reducible": True, "load_bearing": True, "collage": False}, "emulation_matrix": []},
        {"sketch_id": "K2", "decision": "kill", "irreducibility": {
            "non_reducible": True, "load_bearing": True, "collage": False}, "emulation_matrix": [],
         "effect": {"threshold_credible": False}},
        {"sketch_id": "K3", "decision": "kill", "irreducibility": {
            "non_reducible": False, "load_bearing": True, "collage": False}, "emulation_matrix": []},
    ]}))
    state = {"lanes": [{"id": "L010", "status": "done", "sketches_path": program_rel,
                         "program_set_digest": "accepted-digest", "tournament_path": tournament_rel,
                         "attempts": [], "idea_revisions": []}]}
    cfg = {"project": {"mode": "research"}}
    ctx = evalid.Ctx(FixtureStore(fixture), state, cfg, {"nodes": []}, {})
    contracts, kernels = evalid.historical_program_blocks(ctx)
    check(eprogram.candidate_digest(k1) not in contracts
          and eprogram.kernel_fingerprint(k1) not in kernels,
          "an advanced survivor must not become historical rejection material")
    check(eprogram.candidate_digest(k2) in contracts
          and eprogram.kernel_fingerprint(k2) not in kernels,
          "an E-only kill must reject the exact contract while preserving its core")
    revised = copy.deepcopy(k2)
    revised["effect_case"]["predicted_gain"] += " with a substantively revised comparator-bound effect case"
    check(eprogram.candidate_digest(revised) not in contracts
          and eprogram.kernel_fingerprint(revised) == eprogram.kernel_fingerprint(k2),
          "a substantive E-contract revision must remain admissible for re-audit")
    check(eprogram.candidate_digest(k3) in contracts
          and eprogram.kernel_fingerprint(k3) in kernels,
          "an explicit research M failure may block the exact frozen core")

    orphan = candidate("K9", "orphan unvalidated draft")
    write(fixture, ".evo/rounds/R999/lanes/L999/PROGRAMS_c99.json",
          json.dumps({"sketches": [orphan]}))
    write(fixture, ".evo/ideas/I999.meta.json",
          json.dumps({"idea": "I999", "kernel_hash": eprogram.kernel_fingerprint(orphan)}))
    _contracts2, kernels2 = evalid.historical_program_blocks(ctx)
    check(eprogram.kernel_fingerprint(orphan) not in kernels2,
          "orphan program/meta files that state never accepted must have no blacklist authority")

    # The tournament must not expose a non-empty survivor set to a scheduler
    # that sees zero winners, and a research winner cannot carry un-settleable
    # unknown planned resources.
    numeric_rel = ".evo/rounds/R020/lanes/L020/PROGRAMS_c1.json"
    review_rel = ".evo/rounds/R020/lanes/L020/TOURNAMENT_c1.md"
    output_rel = ".evo/rounds/R020/lanes/L020/TOURNAMENT_check.json"
    ku = candidate("K1", "unknown resource candidate", unknown=True)
    write(fixture, numeric_rel, json.dumps({"sketches": [ku]}))
    write(fixture, review_rel, "## Review\n\nindependent audit fixture\n")
    lane = {"id": "L020", "intent": "moonshot", "min_level": 4,
            "sketches_path": numeric_rel, "program_set_digest": "", "search_origin": "constructive"}
    st = {"lanes": [lane]}
    store = FixtureStore(fixture)
    research_cfg = {"project": {"mode": "research"}, "research": {"sota_enabled": False},
                    "metrics": [{"key": "acc", "direction": "max"}],
                    "evaluation_contract": {"cells": [
                        {"id": "C1", "role": "target", "result_key": "acc", "metric": "acc"}]}}
    ctx2 = evalid.Ctx(store, st, research_cfg, {"nodes": []}, {})
    lane["program_set_digest"] = evalid.json_file_digest(ctx2, numeric_rel)
    audit = {
        "sketch_id": "K1", "program_digest": eprogram.candidate_digest(ku),
        "quote": ku["novelty"]["bearer"], "prior_art": {"neighbors": [], "search_stop_reason": "x" * 90},
        "emulation_matrix": [], "irreducibility": {"non_reducible": True, "load_bearing": True,
                                                       "collage": False, "argument": "x" * 120},
        "scope": {"claimed_scope": "full_program", "audited_scope": "full_program",
                  "train_semantics_preserved": False, "infer_semantics_preserved": False,
                  "preserved_interfaces": [], "argument": "x" * 120},
        "effect": {"causal_chain_valid": True, "comparator_valid": True, "threshold_credible": True,
                   "resource_status": "advantaged", "resource_confounds": [],
                   "resource_provenance": "x" * 90, "worst_case_bound": "x" * 90,
                   "frontier_refs": [], "argument": "x" * 120},
        "decision": "advance", "reason": "x" * 80,
    }
    payload = {"lane": "L020", "program_set_digest": lane["program_set_digest"],
               "audits": [audit], "survivor_ranking": [
                   {"rank": 1, "sketch_id": "K1", "pareto_status": "nondominated", "argument": "x" * 90}],
               "winners": []}
    write(fixture, output_rel, json.dumps(payload))
    errs = evalid.v_tournament(ctx2, {"subject": {"lane": "L020"},
                                      "outputs": [output_rel, review_rel]})
    check(any(err.startswith("TOURNAMENT_WINNER_SURVIVOR_CONSISTENCY") for err in errs),
          "advanced survivors with winners=[] must be rejected before scheduler transition")
    check(any(err.startswith("TOURNAMENT_RESOURCE_NUMERIC_ADVANCE") for err in errs),
          "unknown+advantaged prose cannot create an un-settleable research winner")
    payload["audits"][0]["decision"] = "kill"
    payload["survivor_ranking"] = []
    write(fixture, output_rel, json.dumps(payload))
    killed_errs = evalid.v_tournament(ctx2, {"subject": {"lane": "L020"},
                                             "outputs": [output_rel, review_rel]})
    check(not any(err.startswith("TOURNAMENT_RESOURCE_NUMERIC_ADVANCE") for err in killed_errs),
          "unknown remains legal evidence on a killed research draft")
    duplicate_payload = copy.deepcopy(payload)
    duplicate_audit = copy.deepcopy(duplicate_payload["audits"][0])
    duplicate_audit["decision"] = "advance"
    duplicate_payload["audits"].append(duplicate_audit)
    duplicate_payload["survivor_ranking"] = [
        {"rank": 1, "sketch_id": "K1", "pareto_status": "nondominated", "argument": "x" * 90}]
    duplicate_payload["winners"] = ["K1"]
    write(fixture, output_rel, json.dumps(duplicate_payload))
    duplicate_errs = evalid.v_tournament(ctx2, {"subject": {"lane": "L020"},
                                                "outputs": [output_rel, review_rel]})
    check(any(err.startswith("TOURNAMENT_AUDIT_DUP") for err in duplicate_errs),
          "one K# cannot be simultaneously killed and advanced by duplicate audit rows")

    # A contract with two individually legal directions for one C# is still
    # impossible to settle after execution and must be rejected at sketch.
    baseline_rel = ".evo/profile/BASELINE_PROGRAM.json"
    write(fixture, baseline_rel, "{}")
    mixed = candidate("K1", "mixed direction candidate")
    mixed["effect_case"]["chain"] = [
        {"id": "Z1", "kernel_refs": ["KC1"], "target_cell": "C1",
         "direction": "increase", "minimum_worthwhile_delta": 0.01,
         "expected_delta_interval": [0.01, 0.03]},
        {"id": "Z2", "kernel_refs": ["KC1"], "target_cell": "C1",
         "direction": "stabilize", "minimum_worthwhile_delta": 0.01,
         "expected_delta_interval": [0.01, 0.03]},
        {"id": "Z3", "kernel_refs": ["KC1"], "target_cell": "C2",
         "direction": "increase", "minimum_worthwhile_delta": 0.01,
         "expected_delta_interval": [0.01, 0.03]},
    ]
    mixed["claim_scope"] = {
        "kind": "efficiency", "target_cells": ["C1", "C2"], "guardrail_cells": [],
        "improvement_cells": ["C2"], "parity_cells": ["C1"],
        "rationale": "freeze one parity cell and one improvement cell before selection",
    }
    mixed["collision_queries"] = ["query the closest executable mechanism and its exact update semantics",
                                  "query the closest task-effect program under matched resources"]
    mixed_rel = ".evo/rounds/R030/lanes/L030/PROGRAMS_c1.json"
    mixed_cfg = {
        "project": {"mode": "research"}, "budgets": {"sketches_per_lane": 1},
        "metrics": [{"key": "acc", "direction": "max"}],
        "evaluation_contract": {"cells": [
            {"id": "C1", "role": "target", "result_key": "acc", "metric": "acc"},
            {"id": "C2", "role": "target", "result_key": "acc", "metric": "acc"},
        ]},
    }
    mixed_lane = {"id": "L030", "intent": "moonshot", "min_level": 4,
                  "parents": [], "search_origin": "constructive", "attempts": [],
                  "idea_revisions": []}
    mixed_store = FixtureStore(fixture)
    mixed_ctx = evalid.Ctx(mixed_store, {"lanes": [mixed_lane]}, mixed_cfg,
                           {"nodes": [{"id": "N001", "role": "baseline"}]}, {})
    mixed_payload = {
        "schema_version": 2, "lane": "L030", "search_origin": "constructive",
        "baseline_program_digest": evalid.json_file_digest(mixed_ctx, baseline_rel),
        "sketches": [mixed],
    }
    write(fixture, mixed_rel, json.dumps(mixed_payload))
    mixed_errs = evalid.v_sketch(
        mixed_ctx, {"subject": {"lane": "L030"}, "outputs": [mixed_rel]})
    check(any(err.startswith("PROGRAM_EFFECT_DIRECTION_MIXED") for err in mixed_errs),
          "mixed directions for one target cell must fail before tournament and execution")

    # In engineering mode a killed same-batch alternative may emulate the
    # survivor; the conflict exists only if both occupy survivor slots.
    emulation_rel = ".evo/rounds/R010/lanes/L010/TOURNAMENT_emulation.json"
    emulation_md = ".evo/rounds/R010/lanes/L010/TOURNAMENT_emulation.md"
    write(fixture, emulation_md, "## Independent review\n\nengineering emulation fixture\n")

    def emulation_audit(cand: dict, decision: str, emulator: str | None = None) -> dict:
        sid = str(cand["sketch_id"])
        return {
            "sketch_id": sid, "program_digest": eprogram.candidate_digest(cand),
            "quote": cand["novelty"]["bearer"],
            "prior_art": {"neighbors": [], "search_stop_reason": "x" * 90},
            "emulation_matrix": [
                {"alternative": other, "can_emulate": other == emulator, "argument": "x" * 90}
                for other in ("K1", "K2", "K3") if other != sid],
            "irreducibility": {"non_reducible": True, "load_bearing": True,
                               "collage": False, "argument": "x" * 120},
            "scope": {"claimed_scope": "full_program", "audited_scope": "full_program",
                      "train_semantics_preserved": False, "infer_semantics_preserved": False,
                      "preserved_interfaces": [], "argument": "x" * 120},
            "effect": {"causal_chain_valid": True, "comparator_valid": True,
                       "threshold_credible": True, "resource_status": "matched",
                       "resource_confounds": [], "resource_provenance": "x" * 90,
                       "frontier_refs": [], "argument": "x" * 120},
            "decision": decision, "reason": "x" * 80,
        }

    engineering_state = {"lanes": [{"id": "L010", "intent": "moonshot", "min_level": 4,
                                      "sketches_path": program_rel,
                                      "program_set_digest": evalid.json_file_digest(ctx, program_rel),
                                      "search_origin": "constructive"}]}
    engineering_ctx = evalid.Ctx(
        FixtureStore(fixture), engineering_state,
        {"project": {"mode": "engineering"}, "research": {"sota_enabled": False}},
        {"nodes": []}, {})
    emulation_payload = {
        "program_set_digest": engineering_state["lanes"][0]["program_set_digest"],
        "audits": [emulation_audit(k1, "advance", "K2"),
                   emulation_audit(k2, "kill"), emulation_audit(k3, "kill")],
        "survivor_ranking": [{"rank": 1, "sketch_id": "K1", "pareto_status": "nondominated",
                              "argument": "x" * 90}],
        "winners": ["K1"],
    }
    write(fixture, emulation_rel, json.dumps(emulation_payload))
    killed_emulator_errs = evalid.v_tournament(
        engineering_ctx, {"subject": {"lane": "L010"},
                          "outputs": [emulation_rel, emulation_md]})
    check(not any(err.startswith("TOURNAMENT_CANDIDATE_EMULATED_ADVANCE")
                  for err in killed_emulator_errs),
          "a killed engineering alternative must not veto the sole surviving program")
    emulation_payload["audits"][1]["decision"] = "advance"
    emulation_payload["survivor_ranking"].append(
        {"rank": 2, "sketch_id": "K2", "pareto_status": "tradeoff", "argument": "x" * 90})
    write(fixture, emulation_rel, json.dumps(emulation_payload))
    two_survivor_errs = evalid.v_tournament(
        engineering_ctx, {"subject": {"lane": "L010"},
                          "outputs": [emulation_rel, emulation_md]})
    check(any(err.startswith("TOURNAMENT_CANDIDATE_EMULATED_ADVANCE")
              for err in two_survivor_errs),
          "two engineering programs must not both survive when one emulates the other")


def duplicate_and_context_checks() -> None:
    fixture = HERE / "out" / "duplicate_context_fixture"
    fixture.mkdir(parents=True, exist_ok=True)
    digest = "candidate-digest"
    collision = {"id": "CA001", "lane": "L001", "program_set_digest": "set-digest",
                 "candidate_id": "K1", "candidate_digest": digest, "mech_card_id": "M001"}
    store = FixtureStore(fixture, evidence=[{"id": "E001"}],
                         cards=[{"id": "M001", "paper": "E001"}], collisions=[collision])
    graph = {"nodes": [{"id": "N001", "role": "baseline", "kernel_hash": "kernel-a"}]}
    research = evalid.Ctx(store, {"lanes": []}, {"project": {"mode": "research"}}, graph, {})
    valid = ("VERDICT: REJECT_DUPLICATE\nDUPLICATE_OF: CA001\n\n## Prior-art attack\n\n"
             "The exact candidate-bound comparison CA001 resolves through M001 to E001 and shows the same program.\n")
    check(not evalid._duplicate_evidence_errors(
        research, valid, lane_id="L001", program_set_digest="set-digest",
        winner="K1", candidate_digest=digest),
        "research duplicate rejection must resolve a candidate-bound CA/M/E chain")
    check(any(err.startswith("REVIEW_DUPLICATE_TARGET") for err in
              evalid._duplicate_evidence_errors(
                  research, valid.replace("DUPLICATE_OF: CA001\n", ""), lane_id="L001",
                  program_set_digest="set-digest", winner="K1", candidate_digest=digest)),
          "a vague duplicate accusation without an exact target must fail")
    check(any(err.startswith("REVIEW_DUPLICATE_TARGET") for err in
              evalid._duplicate_evidence_errors(
                  research, valid + "DUPLICATE_OF: N001\n", lane_id="L001",
                  program_set_digest="set-digest", winner="K1", candidate_digest=digest)),
          "a duplicate rejection must name exactly one target, not an ambiguous list")
    engineering = evalid.Ctx(store, {"lanes": []}, {"project": {"mode": "engineering"}}, graph, {})
    check(any(err.startswith("REVIEW_DUPLICATE_ENGINEERING") for err in
              evalid._duplicate_evidence_errors(
                  engineering, valid, lane_id="L001", program_set_digest="set-digest",
                  winner="K1", candidate_digest=digest)),
          "engineering may not reject merely because a published program matches")
    graph_review = ("VERDICT: REJECT_DUPLICATE\nDUPLICATE_OF: N001\n\n## Prior-art attack\n\n"
                    "N001 already implements the same graph-local program and effect contract exactly.\n")
    check(not evalid._duplicate_evidence_errors(
        engineering, graph_review, lane_id="L001", program_set_digest="set-digest",
        winner="K1", candidate_digest=digest, candidate_kernel_hash="kernel-a"),
        "engineering duplicate rejection remains legal against an exact existing graph node")
    check(any(err.startswith("REVIEW_DUPLICATE_KERNEL") for err in
              evalid._duplicate_evidence_errors(
                  engineering, graph_review, lane_id="L001", program_set_digest="set-digest",
                  winner="K1", candidate_digest=digest, candidate_kernel_hash="different-kernel")),
          "an arbitrary existing N# cannot serve as duplicate evidence for a different kernel")

    ca_review = ".evo/ideas/I004.review.md"
    write(fixture, ca_review, valid)
    ca_state = {"lanes": [{"id": "L001", "idea_revisions": [{
        "idea": "I004", "verdict": "REJECT_DUPLICATE", "review": ca_review,
        "winner": "K1", "program_set_digest": "set-digest",
        "winner_program_digest": digest, "winner_kernel_hash": "kernel-ca"}],
        "attempts": []}]}
    ca_ctx = evalid.Ctx(store, ca_state, {"project": {"mode": "research"}}, graph, {})
    ca_contracts, ca_kernels = evalid.historical_program_blocks(ca_ctx)
    check(digest in ca_contracts and "kernel-ca" not in ca_kernels,
          "a candidate-bound CA# rejection retires the exact contract but is not a formal global core ban")

    measured = {axis: {"lower": 9.0, "upper": 11.0, "source": "sealed-receipt"}
                for axis in eprogram.RESOURCE_AXES}
    receipt_rel = ".evo/nodes/N099/RESOURCE_RECEIPT_r1.json"
    write(fixture, receipt_rel, json.dumps({"resources": measured}, sort_keys=True))
    receipt_seal = eseal.create(fixture, [("resource_receipt", receipt_rel)])
    check(not eseal.verify(fixture, receipt_seal, label="fixture comparator receipt"),
          "comparator-binding fixture itself must carry a valid content seal")
    binding_graph = {"nodes": [{"id": "N099", "role": "baseline",
                                 "effect_resources_realized": measured,
                                 "resource_receipt_path": receipt_rel,
                                 "resource_receipt_seal": receipt_seal}]}
    binding_ctx = evalid.Ctx(store, {"lanes": []}, {"project": {"mode": "research"},
                                                    "research": {"sota_enabled": False}},
                             binding_graph, {})
    bound_candidate = candidate("K1", "receipt-bound comparator")
    check(not evalid._planned_comparator_resource_errors(
        binding_ctx, bound_candidate, where="audit(K1)"),
        "numeric comparator estimates inside the sealed receipt must pass before execution")
    bound_candidate["effect_case"]["resources"]["comparator"][eprogram.RESOURCE_AXES[0]] = 99.0
    check(any(err.startswith("TOURNAMENT_COMPARATOR_RESOURCE_BINDING") for err in
              evalid._planned_comparator_resource_errors(
                  binding_ctx, bound_candidate, where="audit(K1)")),
          "a numeric comparator vector contradicting its existing receipt must be rejected before execution")

    # Legal comparator measurements must be present even when a mature node has
    # removed baseline from the observed promotion frontier.
    for rel in (".evo/nodes/N001/NODE_RESULT.md", ".evo/runs/RUN_BASE/metrics.json",
                ".evo/nodes/N001/eval/metrics.json",
                ".evo/nodes/N001/RESOURCE_RECEIPT_r1.json",
                ".evo/nodes/N010/NODE_RESULT.md", ".evo/runs/RUN_PARENT/metrics.json",
                ".evo/nodes/N010/eval/metrics.json",
                ".evo/nodes/N010/RESOURCE_RECEIPT_r1.json"):
        write(fixture, rel, "{}" if rel.endswith(".json") else "result\n")
    engine = object.__new__(esched.Engine)
    engine.store = FixtureStore(fixture)
    engine.st = {"runs": [
        {"id": "RUN_BASE", "metrics_file": ".evo/runs/RUN_BASE/metrics.json"},
        {"id": "RUN_PARENT", "metrics_file": ".evo/runs/RUN_PARENT/metrics.json"}]}
    engine.g = {"nodes": [
        {"id": "N001", "role": "baseline", "result_doc": ".evo/nodes/N001/NODE_RESULT.md",
         "eval_run": "RUN_BASE", "resource_receipt_path": ".evo/nodes/N001/RESOURCE_RECEIPT_r1.json",
         "eval_seal": {"artifacts": [{"role": "normalized_metrics",
                                         "path": ".evo/nodes/N001/eval/metrics.json"}]}},
        {"id": "N010", "role": "variant", "result_doc": ".evo/nodes/N010/NODE_RESULT.md",
         "eval_run": "RUN_PARENT", "resource_receipt_path": ".evo/nodes/N010/RESOURCE_RECEIPT_r1.json",
         "eval_seal": {"artifacts": [{"role": "normalized_metrics",
                                         "path": ".evo/nodes/N010/eval/metrics.json"}]}}]}
    root_inputs = [path for path, _role in engine._effect_comparator_inputs(
        {"intent": "moonshot", "parents": []})]
    check(".evo/nodes/N001/RESOURCE_RECEIPT_r1.json" in root_inputs
          and ".evo/nodes/N001/eval/metrics.json" in root_inputs
          and ".evo/runs/RUN_BASE/metrics.json" not in root_inputs,
          "a root must receive baseline metrics and receipt even when baseline is not global frontier")
    variant_inputs = [path for path, _role in engine._effect_comparator_inputs(
        {"intent": "reform", "parents": ["N010"]})]
    check(".evo/nodes/N001/RESOURCE_RECEIPT_r1.json" in variant_inputs
          and ".evo/nodes/N010/RESOURCE_RECEIPT_r1.json" in variant_inputs,
          "a variant must receive both legal baseline and scientific-parent comparator receipts")
    engine.cfg = {"project": {"mode": "research"}}
    root_policy = "\n".join(line for _title, lines in engine._promotion_blocks(
        {"intent": "moonshot"}) for line in lines)
    ordinary_policy = "\n".join(line for _title, lines in engine._promotion_blocks(
        {"intent": "reform"}) for line in lines)
    check("first-contact root lane" in root_policy and "full_program + paradigm" in root_policy,
          "wildcat/moonshot must expose the narrow first-contact admission path")
    check("first-contact root lane" not in ordinary_policy and "Ordinary admission applies" in ordinary_policy,
          "ordinary lanes must not inherit the paradigm-root exception")


def instrumental_retry_routing_checks() -> None:
    """A lane may only be rewound to a stage its own purpose actually has.

    The routing branches once said "experiment_purpose != targeted_ablation" to
    mean "is a candidate".  That held while those were the only two purposes;
    when diagnostic_probe and maintenance arrived, the negative form matched
    them too, so rejecting a probe with --retry-stage sketch|mature ran
    candidate-only machinery over it and parked the lane in a status its route
    never contains - a corrupted record that later reads as a scheduler stall.
    """
    import econfig
    import eflow

    def engine_with(lane: dict, gate: dict):
        events: list[tuple] = []
        eng = object.__new__(esched.Engine)
        eng.st = {"lanes": [lane], "gates": [gate]}
        eng.store = SimpleNamespace(
            get_lane=lambda st, lid: next((l for l in st["lanes"] if l["id"] == lid), None),
            get_gate=lambda st, gid: next((g for g in st["gates"] if g["id"] == gid), None),
            event=lambda actor, ev, **d: events.append((actor, ev, d)),
        )
        # Routing is what is under test; the sealed-contract precondition and
        # node cascade are exercised by the drive suites.
        eng._idea_contract_digest = lambda ln: "CD"
        eng.node = lambda nid: None
        return eng, events

    def lane_record(purpose, status):
        # Shaped like eapply._create_lane writes it: a thinner fixture would
        # make a regressed guard blow up inside candidate machinery instead of
        # failing the assertion that names the actual contract.
        return {"id": "L001", "round": "R001", "status": status,
                "experiment_purpose": purpose, "idea": "I001",
                "winner_sketch": None, "winner_program_digest": None,
                "cycles": {"sketch": 0, "mature": 0, "theory": 0, "ablation": 0},
                "theory_cycle": 0, "required_topics": [], "idea_revisions": [],
                "seal_history": [], "attempts": []}

    def reject(purpose: str, status: str, retry_stage: str) -> tuple[dict, dict, object]:
        """Returns (lane, gate, raised SystemExit or None) after one rejection."""
        lane = lane_record(purpose, status)
        gate = {"id": "G1", "kind": "idea_approval", "status": "open",
                "subject": {"lane": "L001", "contract_digest": "CD"}}
        eng, _events = engine_with(lane, gate)
        try:
            eng._decide_gate(gate, approve=False, note="no", actor="user",
                             retry_stage=retry_stage)
        except SystemExit as exc:
            return lane, gate, exc
        return lane, gate, None

    for purpose, seq in eflow.INSTRUMENTAL_SEQ.items():
        design_stage = seq[0]
        # A stage the lane does not have must be refused BEFORE anything mutates.
        # Falling through to the abandon branch destroyed the lane silently, and
        # because the cap counts lanes opened, the round's instrumental slot went
        # with it and could not be recovered by re-deciding the gate.
        foreign_stages = ["sketch", "mature"] + [s[0] for p, s in eflow.INSTRUMENTAL_SEQ.items()
                                                 if p != purpose]
        for foreign in foreign_stages:
            lane, gate, exc = reject(purpose, design_stage, foreign)
            check(exc is not None and foreign in str(exc),
                  f"a {purpose} lane rejected with --retry-stage {foreign} must be refused by name, "
                  f"not routed into another purpose's machinery (raised {exc!r})")
            check(lane["status"] == design_stage and lane["idea"] == "I001",
                  f"a refused --retry-stage must leave the {purpose} lane untouched "
                  f"(got {lane['status']!r}/{lane['idea']!r})")
            check(gate["status"] == "open",
                  f"a refused --retry-stage must leave the gate open so the user can decide "
                  f"again (got {gate['status']!r})")
        revived, _gate, exc = reject(purpose, design_stage, design_stage)
        check(exc is None and revived["status"] == design_stage and revived["idea"] is None,
              f"a {purpose} lane must still rewind to its own design stage with the idea "
              f"superseded (got {revived['status']!r}/{revived['idea']!r}, {exc!r})")
        # Rejecting outright, with no stage, still abandons - that is how a user
        # says "no instrumental work of this kind this round".
        dropped, _gate, exc = reject(purpose, design_stage, None)
        check(exc is None and dropped["status"] == "abandoned",
              f"a {purpose} lane rejected without --retry-stage must be abandoned "
              f"(got {dropped['status']!r}, {exc!r})")

    # The candidate path is unchanged - the fix narrows the guard, it does not
    # remove the rewind every candidate lane relies on.
    cand, _cand_gate, cand_exc = reject("candidate", "gate", "mature")
    check(cand_exc is None and cand["status"] == "mature" and cand["idea"] is None,
          f"a candidate lane must still rewind to mature (got {cand['status']!r}, {cand_exc!r})")
    # ...and a candidate may not borrow an instrumental design stage either.
    borrowed, borrowed_gate, borrowed_exc = reject("candidate", "gate", "probe_design")
    check(borrowed_exc is not None and borrowed["status"] == "gate"
          and borrowed_gate["status"] == "open",
          f"a candidate lane must not accept probe_design (got {borrowed['status']!r}, {borrowed_exc!r})")
    # Lanes written before the purpose axis existed carry no purpose at all and
    # the engine reads them as candidates; the positive guard must too.
    legacy_lane = lane_record(None, "gate")
    legacy_gate = {"id": "G1", "kind": "idea_approval", "status": "open",
                   "subject": {"lane": "L001", "contract_digest": "CD"}}
    eng, _ = engine_with(legacy_lane, legacy_gate)
    eng._decide_gate(legacy_gate, approve=False, note="no", actor="user", retry_stage="mature")
    check(econfig.lane_purpose(legacy_lane) == "candidate" and legacy_lane["status"] == "mature",
          f"a purpose-less legacy lane must keep the candidate rewind (got {legacy_lane['status']!r})")

    # --retry-stage is an idea-gate verb. On an escalation gate the reject branch
    # never reads it, so the flag used to be accepted with exit 0 while the lane
    # was abandoned anyway - and on an instrumental lane that also burned the
    # round's only slot, with the gate card promising the opposite.
    for purpose, seq in eflow.INSTRUMENTAL_SEQ.items():
        esc_lane = lane_record(purpose, seq[0])
        esc_gate = {"id": "G8", "kind": "escalation", "status": "open",
                    "subject": {"lane": "L001", "resume_stage": seq[0]}}
        eng, _ = engine_with(esc_lane, esc_gate)
        raised = None
        try:
            eng._decide_gate(esc_gate, approve=False, note="no", actor="user",
                             retry_stage=seq[0])
        except SystemExit as exc:
            raised = exc
        check(raised is not None and "idea_approval" in str(raised),
              f"--retry-stage on a {purpose} escalation gate must be refused by name (got {raised!r})")
        check(esc_lane["status"] == seq[0] and esc_gate["status"] == "open",
              f"a refused --retry-stage must not abandon the {purpose} lane or decide its gate "
              f"(got {esc_lane['status']!r}/{esc_gate['status']!r})")

    # Instrumental compute is never released without the user: eflow.GATE_POLICY
    # lists all three purposes as manual for workflow_approval, and the gate has
    # to actually be CREATED for that entry to protect anything.
    # One check per purpose at the WEAKEST configuration (full_auto + light):
    # _needs_workflow_gate returns before reading cost or autonomy for
    # instrumental purposes, so sweeping 3x3 combinations exercised one line
    # 27 times and only inflated the count.
    for purpose in econfig.INSTRUMENTAL_PURPOSES:
        eng = object.__new__(esched.Engine)
        eng.cfg = {"policy": {"autonomy": "full_auto", "cost_gate_class": "heavy"}}
        eng._spec = lambda node: {"cost_class": "light"}
        eng._autonomy = lambda: "full_auto"
        check(eng._needs_workflow_gate({"experiment_purpose": purpose}),
              f"a {purpose} workflow gate must be manual even at full_auto + light cost")
    # A candidate keeps the ordinary cost/autonomy ladder.
    eng = object.__new__(esched.Engine)
    eng.cfg = {"policy": {"autonomy": "full_auto", "cost_gate_class": "heavy"}}
    eng._spec = lambda node: {"cost_class": "heavy"}
    eng._autonomy = lambda: "full_auto"
    check(not eng._needs_workflow_gate({"experiment_purpose": "candidate"}),
          "full_auto must still release an ordinary candidate workflow without a gate")

    # Approving an escalation must reset the counter that RAISED it. Both
    # instrumental review paths increment cycles["ablation"], but the stage->
    # counter map named only "ablation_design", so approving a maintenance
    # escalation reset nothing: the next REVISE re-escalated at once and, since
    # an open gate blocks all scheduling, the run stalled once per revision.
    for purpose, seq in eflow.INSTRUMENTAL_SEQ.items():
        stuck = lane_record(purpose, seq[0])
        stuck["cycles"]["ablation"] = 3
        esc = {"id": "G9", "kind": "escalation", "status": "open",
               "subject": {"lane": "L001", "resume_stage": seq[0]}}
        eng, _ = engine_with(stuck, esc)
        eng._decide_gate(esc, approve=True, note="redesign it", actor="user", retry_stage=None)
        check(stuck["cycles"]["ablation"] == 0,
              f"approving a {purpose} escalation must reset the review counter it was raised on "
              f"(still {stuck['cycles']['ablation']})")
        check(stuck["status"] == seq[0],
              f"an approved {purpose} escalation must resume on its own route (got {stuck['status']!r})")

    # The rejection note is the ONLY revision signal an instrumental redraft can
    # carry (a probe has no review stage at all), and the digest-bound epoch test
    # silently dropped it for every stage but theorize/ablation_design.
    for purpose, seq in eflow.INSTRUMENTAL_SEQ.items():
        noted = lane_record(purpose, seq[0])
        eng, _ = engine_with(noted, {})
        eng.st["gates"] = [{"id": "G7", "kind": "idea_approval", "status": "rejected",
                            "retry_stage": seq[0], "decision_note": "narrow the boundary first",
                            "subject": {"lane": "L001", "winner_program_digest": None}}]
        routed = "\n".join(line for _t, lines in eng._retry_direction_blocks(noted, seq[0])
                           for line in lines)
        check("narrow the boundary first" in routed,
              f"a {purpose} redraft must receive the user's rejection note (got {routed!r})")


def main() -> None:
    recovery_context_checks()
    comparator_contract_checks()
    survivor_lifecycle_checks()
    retry_binding_checks()
    disposition_and_validator_checks()
    duplicate_and_context_checks()
    instrumental_retry_routing_checks()
    print(f"RETRY CONTRACT REGRESSIONS GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
