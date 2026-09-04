#!/usr/bin/env python3
"""Frontier, selection and settlement semantics (DESIGN_V10 §11).

Regression cover for the field-report defects: a node holding every cell record
was invisible because its verdict was judged against its own parent, a
dominated origin could never be displaced, a required task group vetoed on a
cell its own contract marked optional, a matched resource axis could not be
satisfied by genuinely equal cost, and "not measured yet" was reported as
"claim refuted".  Pure unit level: no engine drive, no subprocesses.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "engine"))

import ebundle     # noqa: E402
import econfig     # noqa: E402
import egraph      # noqa: E402
import eprogram    # noqa: E402
import evalid      # noqa: E402

CHECKS = 0


def ok(cond, message):
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(f"[check {CHECKS}] {message}")


def cfg_of(cells, *, mode="research"):
    tasks = sorted({str(c["task"]) for c in cells})
    return {
        "project": {"name": "unit", "goal": "unit", "mode": mode},
        "evaluation_contract": {
            "display_cell": cells[0]["id"],
            "cells": cells,
            "tasks": [{"id": t, "aggregation": "all", "weight": 1.0} for t in tasks],
            "task_groups": [{"id": f"G{i+1}", "tasks": [t], "aggregation": "all",
                             "required": True} for i, t in enumerate(tasks)],
            "decision": {"min_target_groups_improved": 1, "guardrails_must_be_noninferior": True,
                         "allow_specialist": True},
        },
        "metrics": [{"key": "m", "direction": "max"}],
        "evidence_policy": {"training_replication": {"mode": "record_only"}},
    }


def cell(cid, task, role, key, *, required=False, min_improvement=0.005, margin=0.005):
    return {"id": cid, "task": task, "dataset": "D1", "metric": "m", "role": role,
            "result_key": key, "required": required, "weight": 1.0,
            "min_improvement": min_improvement, "noninferiority_margin": margin,
            "goal_threshold": None}


FOUR_CELLS = [
    cell("C1", "T1", "target", "lp_ap"),
    cell("C2", "T1", "target", "lp_auc", required=True),
    cell("C3", "T2", "target", "nc_f1", required=True),
    cell("C4", "T2", "guardrail", "nc_micro"),
]

RESOURCES = {axis: {"lower": 1.0, "upper": 1.0, "source": "r"} for axis in eprogram.RESOURCE_AXES}


def node(nid, *, role="variant", verdict="improved", scores, parents=(), promotion=None,
         resources=RESOURCES, status="concluded", **extra):
    n = {"id": nid, "title": nid, "role": role, "experiment_purpose": "candidate",
         "parents": list(parents), "level": 2, "status": status, "verdict": verdict,
         "retire_reason": None, "scores": dict(scores), "score_evidence": dict(scores)}
    if resources is not None:
        n["effect_resources_realized"] = copy.deepcopy(resources)
    if promotion is not None:
        n["scientific_promotion_status"] = promotion
    n.update(extra)
    return n


def field_report_graph():
    """The reported shape: the origin is worst everywhere, the record holder was
    judged against its own parent, and one root settled nothing."""
    cfg = cfg_of(FOUR_CELLS)
    g = {"nodes": [
        node("N001", role="baseline", verdict="baseline", resources=None,
             scores={"lp_ap": 0.75, "lp_auc": 0.64, "nc_f1": 0.62, "nc_micro": 0.66}),
        node("N003", verdict="regressed", promotion="blocked", parents=["N001"],
             scores={"lp_ap": 0.92, "lp_auc": 0.88, "nc_f1": 0.69, "nc_micro": 0.71}),
        node("N005", verdict="regressed", promotion="blocked", parents=["N003"],
             scores={"lp_ap": 0.98, "lp_auc": 0.97, "nc_f1": 0.68, "nc_micro": 0.70}),
        node("N014", role="root", verdict="specialist", promotion="pending_evidence",
             scores={"lp_ap": 0.96, "lp_auc": 0.94, "nc_f1": 0.62, "nc_micro": 0.66}),
    ]}
    return cfg, g


def performance_frontier_is_measurement_only():
    cfg, g = field_report_graph()
    perf = [n["id"] for n in egraph.performance_frontier(g, cfg)]
    ok("N005" in perf and "N003" in perf,
       f"a judged-against verdict must not evict a record holder: {perf}")
    ok("N001" not in perf,
       f"an origin dominated on every cell must leave the observed frontier: {perf}")
    records = {row["cell"]: row["node"] for row in egraph.cell_records(g, cfg)}
    ok(records["C1"] == "N005" and records["C2"] == "N005" and records["C3"] == "N003",
       f"per-cell records must name the real holders: {records}")


def inheritance_floor_has_an_exit():
    cfg, g = field_report_graph()
    fr = [n["id"] for n in egraph.frontier(g, cfg)]
    ok(fr == ["N001"] and egraph.frontier_is_origin_floor(g, cfg),
       f"with nothing settled the origin is the floor, and says so: {fr}")
    settled = copy.deepcopy(g)
    for n in settled["nodes"]:
        if n["id"] == "N014":
            n["scientific_promotion_status"] = "met"
    fr2 = [n["id"] for n in egraph.frontier(settled, cfg)]
    ok(fr2 == ["N014"] and not egraph.frontier_is_origin_floor(settled, cfg),
       f"one settled claim retires the floor: {fr2}")
    ok("N014" not in {n["id"] for n in egraph.performance_frontier(settled, cfg)},
       "and it is inheritable as the best SETTLED node even though an unsettled "
       "node dominates it - legality is filtered before non-domination")
    engineering = dict(cfg)
    engineering["project"] = {**cfg["project"], "mode": "engineering"}
    fr3 = {n["id"] for n in egraph.frontier(g, engineering)}
    ok(fr3 == {n["id"] for n in egraph.performance_frontier(g, engineering)} == {"N003", "N005"},
       f"engineering mode inherits observed performance directly: {sorted(fr3)}")


def domination_uses_coverage_not_omniscience():
    cfg = cfg_of(FOUR_CELLS)
    rich = node("A", scores={"lp_ap": 0.9, "lp_auc": 0.9, "nc_f1": 0.9, "nc_micro": 0.9})
    thin = node("B", resources=None,
                scores={"lp_ap": 0.5, "lp_auc": 0.5, "nc_f1": 0.5, "nc_micro": 0.5})
    ok(egraph._pareto_dominates(rich, thin, cfg),
       "a fully measured winner must dominate a rival that never priced its axes")
    ok(not egraph._pareto_dominates(thin, rich, cfg),
       "the worse node must not dominate merely by being under-measured")
    blind = node("C", scores={"lp_ap": 0.99, "lp_auc": 0.99, "nc_f1": 0.99})
    ok(not egraph._pareto_dominates(blind, rich, cfg),
       "you cannot beat a rival on a cell you never measured")
    ok(not egraph._pareto_equivalent(blind, rich, cfg),
       "different measurement coverage is not indistinguishability")
    ok(not egraph._pareto_dominates(node("D", resources=None, scores={}),
                                    node("E", resources=None, scores={}), cfg),
       "two empty vectors dominate nothing")


def mutual_domination_deletes_nobody():
    """A margin wider than the improvement threshold makes domination
    non-antisymmetric; a naive filter would evict both sides."""
    cells = [cell("C1", "T1", "target", "lp_ap", min_improvement=0.002, margin=0.01),
             cell("C2", "T1", "target", "lp_auc", min_improvement=0.002, margin=0.01),
             cell("C3", "T2", "target", "nc_f1", min_improvement=0.002, margin=0.01),
             cell("C4", "T2", "guardrail", "nc_micro", min_improvement=0.002, margin=0.01)]
    cfg = cfg_of(cells, mode="engineering")
    trade_a = node("A", scores={"lp_ap": 0.905, "lp_auc": 0.900, "nc_f1": 0.90, "nc_micro": 0.90})
    trade_b = node("B", scores={"lp_ap": 0.900, "lp_auc": 0.905, "nc_f1": 0.90, "nc_micro": 0.90})
    ok(egraph._pareto_dominates(trade_a, trade_b, cfg)
       and egraph._pareto_dominates(trade_b, trade_a, cfg),
       "inside the margin window each node counts as dominating the other")
    g = {"nodes": [node("B0", role="baseline", verdict="baseline",
                        scores={"lp_ap": 0.1, "lp_auc": 0.1, "nc_f1": 0.1, "nc_micro": 0.1}),
                   trade_a, trade_b]}
    tips = {n["id"] for n in egraph.performance_frontier(g, cfg)}
    ok("A" in tips or "B" in tips,
       f"mutual domination must not empty the frontier of its best nodes: {sorted(tips)}")
    ok("B0" not in tips, f"the dominated origin still leaves: {sorted(tips)}")


def required_group_reads_its_own_aggregation():
    cfg = cfg_of(FOUR_CELLS)
    parent = node("P", scores={"lp_ap": 0.80, "lp_auc": 0.80, "nc_f1": 0.80, "nc_micro": 0.80})
    child = node("K", parents=["P"], verdict=None, status="evaluating", scores={})
    g = {"nodes": [node("B0", role="baseline", verdict="baseline",
                        scores={"lp_ap": 0.1, "lp_auc": 0.1, "nc_f1": 0.1, "nc_micro": 0.1}),
                   parent, child]}
    ctx = evalid.Ctx(None, {}, cfg, g, reg={})
    optional_slip = {"lp_ap": 0.70, "lp_auc": 0.90, "nc_f1": 0.90, "nc_micro": 0.90}
    assessment = evalid.computed_assessment(ctx, child, optional_slip)
    ok(assessment["verdict"] == "tradeoff",
       "a required GROUP must veto only when it is lost under its own declared "
       f"aggregation, not when one optional cell slips: {assessment['verdict']}")
    ok(assessment["required_group_losses"] == [],
       f"the group was not lost: {assessment['required_group_losses']}")
    required_slip = {"lp_ap": 0.90, "lp_auc": 0.70, "nc_f1": 0.90, "nc_micro": 0.90}
    required = evalid.computed_assessment(ctx, child, required_slip)
    ok(required["verdict"] == "regressed" and required["required_target_losses"] == ["C2"],
       f"a cell the user marked required still vetoes: {required['verdict']}")
    guard_slip = {"lp_ap": 0.90, "lp_auc": 0.90, "nc_f1": 0.90, "nc_micro": 0.70}
    guarded = evalid.computed_assessment(ctx, child, guard_slip)
    ok(guarded["verdict"] == "regressed" and guarded["guardrail_losses"] == ["C4"],
       f"a guardrail loss still vetoes: {guarded['verdict']}")
    everything = {"lp_ap": 0.70, "lp_auc": 0.70, "nc_f1": 0.70, "nc_micro": 0.90}
    lost = evalid.computed_assessment(ctx, child, everything)
    ok(lost["verdict"] == "regressed" and lost["required_group_losses"] == ["G1", "G2"],
       f"a group that really is lost under `all` still vetoes: {lost}")


def a_cycle_never_empties_the_frontier():
    """Domination cycles are realizable whenever a margin exceeds its
    improvement threshold; evicting every cycle member would report a project
    with settled, measured winners as having measured nothing at all."""
    cells = [cell("C1", "T1", "target", "a", min_improvement=0.01, margin=0.05),
             cell("C2", "T1", "target", "b", min_improvement=0.01, margin=0.05),
             cell("C3", "T2", "target", "c", min_improvement=0.01, margin=0.05)]
    cfg = cfg_of(cells, mode="engineering")
    ring = [node("N010", scores={"a": 0.910, "b": 0.914, "c": 0.892}),
            node("N011", scores={"a": 0.908, "b": 0.906, "c": 0.904}),
            node("N012", scores={"a": 0.900, "b": 0.916, "c": 0.900})]
    origin = node("N001", role="baseline", verdict="baseline",
                  scores={"a": 0.50, "b": 0.50, "c": 0.50})
    g = {"nodes": [origin] + ring}
    edges = {(a["id"], b["id"]) for a in ring for b in ring
             if a is not b and egraph._pareto_dominates(a, b, cfg)
             and not egraph._pareto_dominates(b, a, cfg)}
    ok(len(edges) >= 3 and all(any(e[0] == n["id"] for e in edges) for n in ring),
       f"the fixture really is a domination cycle: {sorted(edges)}")
    tips = {n["id"] for n in egraph.performance_frontier(g, cfg)}
    ok(tips == {"N010", "N011", "N012"},
       f"a tied cycle survives whole; the dominated origin still leaves: {sorted(tips)}")
    ok(egraph.frontier(g, cfg) and not egraph.frontier_is_origin_floor(g, cfg),
       "and the inheritance frontier does not fall back to the origin floor")


def no_survivor_is_beaten_by_an_evicted_node():
    """The invariant every downstream layer assumes: eviction must not leave a
    kept node dominated by a node that was thrown away."""
    cells = [cell("C1", "T1", "target", "a", min_improvement=0.01, margin=0.05),
             cell("C2", "T1", "target", "b", min_improvement=0.01, margin=0.05),
             cell("C3", "T2", "target", "c", min_improvement=0.01, margin=0.05)]
    cfg = cfg_of(cells, mode="engineering")
    pool = [node("N011", scores={"a": 0.911, "b": 0.905, "c": 0.900}),
            node("N012", scores={"a": 0.900, "b": 0.911, "c": 0.905}),
            node("N013", scores={"a": 0.905, "b": 0.900, "c": 0.911}),
            node("N014", scores={"a": 0.905, "b": 0.905, "c": 0.912})]
    g = {"nodes": pool}
    kept = {n["id"] for n in egraph.performance_frontier(g, cfg)}
    ok(kept, "a non-empty pool always leaves a non-empty frontier")
    evicted = [n for n in pool if n["id"] not in kept]
    for out_node in evicted:
        for keep in [n for n in pool if n["id"] in kept]:
            ok(not (egraph._pareto_dominates(out_node, keep, cfg)
                    and not egraph._pareto_dominates(keep, out_node, cfg)),
               f"{out_node['id']} was evicted yet strictly dominates the kept {keep['id']}")
    ok("N014" in kept, f"the node beaten by nothing must be kept: {sorted(kept)}")


def archiving_does_not_delete_the_record():
    cfg, g = field_report_graph()
    archived = copy.deepcopy(g)
    for n in archived["nodes"]:
        if n["id"] == "N005":
            n["retire_reason"] = "archived"
    records = {row["cell"]: row["node"] for row in egraph.cell_records(archived, cfg)}
    ok(records["C1"] == "N005",
       f"'keep for the record, no judgement' must keep the record: {records}")
    ok("N005" in {n["id"] for n in egraph.performance_frontier(archived, cfg)},
       "an archived node still holds the measured position it holds")
    pruned = copy.deepcopy(g)
    for n in pruned["nodes"]:
        if n["id"] == "N005":
            n["retire_reason"] = "pruned"
    # R9 audit: retirement is a LINEAGE decision, never an observation one.
    # Pruning removes inheritance rights (checked below) but the node's
    # MEASURED numbers stay on the performance frontier and the records -
    # deleting them let closing a dead lineage rewrite measured history and
    # manufacture apparent progress for everyone below it.
    ok("N005" in {n["id"] for n in egraph.performance_frontier(pruned, cfg)},
       "pruning keeps the measured position (observation axis untouched)")
    st_stub = {"lanes": []}
    tips, floored = egraph._inheritance(pruned, cfg, st_stub)
    ok("N005" not in {n["id"] for n in tips},
       "pruning removes inheritance rights (lineage axis) until revive")


def strongest_parent_means_hardest_bar():
    """The reference parent must be picked by the bound the comparison then
    consumes, or quantifying uncertainty demotes a parent out of the reference
    and hands its child an easier comparator than the lineage it inherited."""
    cfg = cfg_of(FOUR_CELLS)
    tight = node("P_tight", scores={"lp_ap": 0.90, "lp_auc": 0.90, "nc_f1": 0.90, "nc_micro": 0.90})
    loose = node("P_loose", scores={
        "lp_ap": {"value": 0.93, "uncertainty": {"lower": 0.88, "upper": 0.98}},
        "lp_auc": 0.90, "nc_f1": 0.90, "nc_micro": 0.90})
    child = node("K", parents=["P_tight", "P_loose"], verdict=None, status="evaluating", scores={})
    g = {"nodes": [tight, loose, child]}
    ctx = evalid.Ctx(None, {}, cfg, g, reg={})
    ref = evalid._reference_node_for_metric(ctx, child, "lp_ap")
    ok(ref is not None and ref["id"] == "P_loose",
       f"the parent that sets the hardest bar is the reference: {ref and ref['id']}")
    result = evalid._cell_result(ctx, child, {"lp_ap": 0.95}, FOUR_CELLS[0])
    ok(result["reference_node"] == "P_loose" and result["status"] != "improved",
       f"and 0.95 does not clear a comparator whose upper bound is 0.98: {result['status']}")


def legality_does_not_depend_on_display_order():
    cfg = cfg_of(FOUR_CELLS)
    twin_a = node("N020", promotion="met",
                  scores={"lp_ap": 0.90, "lp_auc": 0.90, "nc_f1": 0.90, "nc_micro": 0.90})
    twin_b = node("N021", promotion="met",
                  scores={"lp_ap": 0.9001, "lp_auc": 0.9001, "nc_f1": 0.9001, "nc_micro": 0.9001})
    g = {"nodes": [node("N001", role="baseline", verdict="baseline",
                        scores={"lp_ap": 0.1, "lp_auc": 0.1, "nc_f1": 0.1, "nc_micro": 0.1}),
                   twin_a, twin_b]}
    ok(egraph._pareto_equivalent(twin_a, twin_b, cfg), "the fixture twins are indistinguishable")
    legal = {n["id"] for n in egraph.frontier(g, cfg)}
    ok(legal == {"N020", "N021"},
       f"both settled twins keep their inheritance rights: {sorted(legal)}")
    shown = [n["id"] for n in egraph.collapse_equivalent_tips(
        egraph.performance_frontier(g, cfg), cfg)]
    ok(len(shown) == 1, f"the display still collapses the duplicate row: {shown}")


def only_a_decided_advance_counts_as_progress():
    cfg = cfg_of(FOUR_CELLS)
    wide = {"value": 0.80, "uncertainty": {"lower": 0.60, "upper": 0.95}}
    prior = [node("P1", scores={"lp_ap": wide, "lp_auc": wide, "nc_f1": wide, "nc_micro": wide})]
    blurry = node("K1", scores={"lp_ap": {"value": 0.70, "uncertainty": {"lower": 0.55, "upper": 0.90}},
                                "lp_auc": wide, "nc_f1": wide, "nc_micro": wide})
    ok(not egraph._pareto_dominates(prior[0], blurry, cfg),
       "intervals this wide mean nothing dominates anything - the node IS a frontier member")
    ok(not egraph.advances_measurement(blurry, prior, cfg),
       "but worse-on-every-point-estimate is not a round's progress")
    winner = node("K2", scores={"lp_ap": 0.99, "lp_auc": 0.99, "nc_f1": 0.99, "nc_micro": 0.99})
    ok(egraph.advances_measurement(winner, prior, cfg),
       "a materially best-ever value on a decision cell is")
    tight = {"lp_ap": 0.80, "lp_auc": 0.80, "nc_f1": 0.80, "nc_micro": 0.80}
    settled_prior = [node("P2", scores=tight)]
    cheaper = node("K3", scores=dict(tight),
                   resources={axis: {"lower": 0.5, "upper": 0.5} for axis in eprogram.RESOURCE_AXES})
    ok(egraph.advances_measurement(cheaper, settled_prior, cfg),
       "and so is the same measured position at a strictly lower realized cost")
    ok(not egraph.advances_measurement(node("K4", scores=dict(tight)), settled_prior, cfg),
       "while an exact re-measurement of the incumbent advances nothing")
    # The same standard has to hold for the inheritance branch: a settled claim
    # that lands AT parity is a real result, but it is not the movement the
    # stagnation escalation is asking about.
    parity_settled = node("K5", promotion="met", scores=dict(tight))
    ok(not egraph.advances_measurement(parity_settled, settled_prior, cfg),
       "a settled claim at parity is not frontier movement either")
    ok(not egraph.advances_measurement(winner, [], cfg),
       "with no prior frontier there is nothing to have advanced past")


def uncertainty_reads_the_declared_aggregation_too():
    cells = [cell("C1", "T1", "target", "lp_ap"), cell("C2", "T2", "target", "lp_auc"),
             cell("C3", "T3", "target", "nc_f1"), cell("C4", "T1", "guardrail", "nc_micro")]
    cfg = cfg_of(cells)
    ev = cfg["evaluation_contract"]
    ev["task_groups"] = [{"id": "G1", "tasks": ["T1", "T2", "T3"], "aggregation": "majority",
                          "required": True}]
    parent = node("P", scores={"lp_ap": 0.80, "lp_auc": 0.80, "nc_f1": 0.80, "nc_micro": 0.80})
    child = node("K", parents=["P"], verdict=None, status="evaluating", scores={})
    ctx = evalid.Ctx(None, {}, cfg, {"nodes": [parent, child]}, reg={})
    # C3 is never measured: uncertain. The declared majority is already won.
    assessment = evalid.computed_assessment(
        ctx, child, {"lp_ap": 0.95, "lp_auc": 0.95, "nc_micro": 0.85})
    ok(assessment["required_group_uncertain"] == [],
       "a group its own declared rule has already settled is not undecided because a "
       f"minority cell is: {assessment['required_group_uncertain']}")
    ok(assessment["verdict"] == "improved", f"so the node can win: {assessment['verdict']}")
    undecided = evalid.computed_assessment(ctx, child, {"lp_ap": 0.95, "nc_micro": 0.85})
    ok(undecided["required_group_uncertain"] == ["G1"] and undecided["verdict"] == "inconclusive",
       f"a genuinely undecided required group still blocks: {undecided['verdict']}")


def _effect_meta(**resources):
    return {"effect_case": {
        "comparator_id": "P",
        "chain": [{"target_cell": "C2", "direction": "increase",
                   "minimum_worthwhile_delta": 0.01, "expected_delta_interval": [0.02, 0.2]}],
        "resources": {"regime": "matched",
                      "fixed_axes": list(eprogram.RESOURCE_AXES),
                      "tradeoff_axes": [], "improvement_axes": [],
                      "candidate": {axis: 10.0 for axis in eprogram.RESOURCE_AXES},
                      "comparator": {axis: 10.0 for axis in eprogram.RESOURCE_AXES},
                      **resources}}}


def matched_resources_accept_equal_cost():
    cfg = cfg_of(FOUR_CELLS)
    equal = {axis: {"lower": 4.0, "upper": 6.0, "source": "r"} for axis in eprogram.RESOURCE_AXES}
    parent = node("P", scores={"lp_ap": 0.8, "lp_auc": 0.8, "nc_f1": 0.8, "nc_micro": 0.8},
                  resources=equal)
    child = node("K", parents=["P"], verdict=None, status="evaluating", scores={})
    g = {"nodes": [parent, child]}
    ctx = evalid.Ctx(None, {}, cfg, g, reg={})
    metrics = {"lp_ap": 0.9, "lp_auc": 0.9, "nc_f1": 0.9, "nc_micro": 0.9,
               "_effect_resources": copy.deepcopy(equal)}
    contract = evalid.effect_contract_assessment(ctx, child, metrics, _effect_meta())
    ok(contract["resources"]["status"] == "met",
       "a matched axis is satisfied by equal cost, not only by provable cheapness: "
       f"{contract['resources']['axes']['train_flops']}")
    ok(contract["status"] == "met", f"the whole contract settles: {contract['status']}")

    dearer = {axis: {"lower": 40.0, "upper": 60.0, "source": "r"} for axis in eprogram.RESOURCE_AXES}
    worse = evalid.effect_contract_assessment(
        ctx, child, {**metrics, "_effect_resources": copy.deepcopy(dearer)}, _effect_meta())
    ok(worse["resources"]["status"] == "failed",
       "decisively costlier under a matched policy still fails")

    # The comparator's realized cost is not the candidate's to control: a missed
    # pre-run estimate of the INCUMBENT is calibration, not a claim failure.
    mis_forecast = _effect_meta(comparator={axis: 999.0 for axis in eprogram.RESOURCE_AXES})
    audited = evalid.effect_contract_assessment(ctx, child, metrics, mis_forecast)
    ok(audited["status"] == "met",
       f"a mis-forecast comparator must not fail the candidate: {audited['status']}")
    ok(set(audited["resources"]["comparator_forecast_missed"]) == set(eprogram.RESOURCE_AXES),
       "but the forecast miss is recorded for calibration")


def unsettled_is_not_refuted():
    cfg = cfg_of(FOUR_CELLS)
    parent = node("P", scores={"lp_ap": 0.8, "lp_auc": 0.8, "nc_f1": 0.8, "nc_micro": 0.8},
                  resources=None)
    child = node("K", parents=["P"], verdict=None, status="evaluating", scores={})
    g = {"nodes": [parent, child]}
    ctx = evalid.Ctx(None, {}, cfg, g, reg={})
    metrics = {"lp_ap": 0.9, "lp_auc": 0.9, "nc_f1": 0.9, "nc_micro": 0.9,
               "_effect_resources": copy.deepcopy(RESOURCES)}
    assessment = evalid.computed_assessment(ctx, child, {**metrics, "_idea": None})
    contract = evalid.effect_contract_assessment(ctx, child, metrics, _effect_meta())
    ok(contract["status"] == "uncertain" and contract["evidence_gaps"],
       f"an unpriced comparator leaves the contract undecided, with reasons: {contract}")
    ok(all("comparator" in gap or "candidate" in gap for gap in contract["evidence_gaps"]),
       f"each gap names what is missing: {contract['evidence_gaps']}")
    ok(assessment["verdict"] == "improved",
       f"the performance verdict is unaffected: {assessment['verdict']}")


def promotion_status_separates_the_two_failures():
    cases = [
        ({"status": "uncertain"}, {"status": "not_applicable"}, "improved", "pending_evidence"),
        ({"status": "failed"}, {"status": "not_applicable"}, "improved", "blocked"),
        ({"status": "met"}, {"status": "refuted"}, "improved", "blocked"),
        ({"status": "met"}, {"status": "unclear"}, "improved", "pending_evidence"),
        ({"status": "met"}, {"status": "not_applicable"}, "regressed", "blocked"),
        # A paradigm root AT parity with nothing regressed is stronger evidence
        # than the inconclusive below it; it cannot be the harsher status.
        ({"status": "uncertain"}, {"status": "not_applicable"}, "promising", "pending_evidence"),
        ({"status": "uncertain"}, {"status": "not_applicable"}, "inconclusive", "pending_evidence"),
        ({"status": "met"}, {"status": "not_applicable"}, "tradeoff", "blocked"),
        ({"status": "met"}, {"status": "not_applicable"}, "improved", "met"),
        ({"status": "not_applicable"}, {"status": "not_applicable"}, "regressed", "not_applicable"),
    ]
    for effect, mechanism, verdict, expected in cases:
        got = evalid.promotion_status(verdict, effect, mechanism,
                                      research_kernel=False, fidelity_settled=True)
        ok(got == expected,
           f"effect={effect['status']} mechanism={mechanism['status']} verdict={verdict} "
           f"-> {got}, expected {expected}")
    ok(evalid.promotion_status("improved", {"status": "met"}, {"status": "not_applicable"},
                               research_kernel=True, fidelity_settled=True) == "pending_evidence",
       "a research kernel needs its own confirmed mechanism, but an absent one is not a refutation")
    ok(evalid.promotion_status("improved", {"status": "met"}, {"status": "confirmed"},
                               research_kernel=True, fidelity_settled=False) == "pending_evidence",
       "an outstanding fidelity audit is an evidence gap, not a verdict against")


def strategist_sees_what_the_engine_knows():
    cfg, g = field_report_graph()
    text = "\n".join(ebundle.frontier_block(g, cfg))
    ok("Origin" in text and "N001" in text, "the origin stays visible after losing the frontier")
    ok("N005" in text and "records=C1,C2" in text,
       f"the record holder and its records are shown: {text}")
    ok("FLOOR IN FORCE" in text, "a floor-only inheritance frontier announces itself")
    ok("reform" in text, "the bundle says what an unsettled node is still good for")
    view = "\n".join(egraph._frontier_view(g, cfg))
    for section in ("## Origin", "## Observed performance frontier (measurement only)",
                    "## Active inheritance frontier (legal exploit parents)",
                    "## Measured but not inheritable", "## Per-cell record holders"):
        ok(section in view, f"FRONTIER.md must carry {section}")


def contradictory_focus_policy_is_refused_at_config_time():
    # v11.4 reconciliation: with neglect forcing ON the pair is always
    # satisfiable (the one starvation-forced lane rides outside the cap,
    # stated in the configure card); what stays refused is a config whose
    # directions can NEVER be served - forcing off AND a cap below one lane
    # of the largest legal round.
    cfg = {"project": {"name": "u", "goal": "g", "mode": "research",
                       "focus_directions": [{"id": "D1", "text": "x" * 40}]},
           "policy": {"focus_share_max": 0.2, "focus_neglect_rounds": 2},
           "budgets": {"lanes_per_round_min": 2, "lanes_per_round_max": 3}}
    ok(not [e for e in econfig.validate_config(cfg) if e.startswith("CONFIG_FOCUS_UNSATISFIABLE")],
       "with starvation forcing on, the forced lane's explicit cap exemption keeps the pair satisfiable")
    cfg["policy"]["focus_neglect_rounds"] = 0
    errs = [e for e in econfig.validate_config(cfg) if e.startswith("CONFIG_FOCUS_UNSATISFIABLE")]
    ok(errs, "directions that can never legally be served (no forcing, cap below one lane of the "
             "largest round) are refused at config time, not at every open_round forever")
    cfg["policy"]["focus_share_max"] = 0.34
    ok(not [e for e in econfig.validate_config(cfg) if e.startswith("CONFIG_FOCUS_UNSATISFIABLE")],
       "a cap that admits one lane of the largest legal round is fine")


def instrumental_purposes_are_frontier_transparent_both_ways():
    """v10.2: a repair that measures BETTER must not evict the lineage it
    repaired (that deadlocked every later exploit), and a probe is evidence,
    never a tip.  Parent legality still resolves THROUGH the repair."""
    cfg = cfg_of(FOUR_CELLS)
    base = node("N010", promotion="met",
                scores={"lp_ap": 0.90, "lp_auc": 0.90, "nc_f1": 0.90, "nc_micro": 0.90})
    repair = node("N011", parents=["N010"], promotion="not_applicable",
                  experiment_purpose="maintenance", maintenance_parity="met",
                  scores={"lp_ap": 0.95, "lp_auc": 0.95, "nc_f1": 0.95, "nc_micro": 0.95})
    probe = node("N012", parents=["N010"], promotion="not_applicable",
                 experiment_purpose="diagnostic_probe", verdict="inconclusive",
                 scores={"lp_ap": 0.99, "lp_auc": 0.99, "nc_f1": 0.99, "nc_micro": 0.99})
    g = {"nodes": [base, repair, probe]}
    perf = {n["id"] for n in egraph.performance_frontier(g, cfg)}
    inherit = {n["id"] for n in egraph.frontier(g, cfg)}
    ok(perf == {"N010"} and inherit == {"N010"},
       f"a better-measuring repair and a probe stay off both frontiers: perf={perf} inherit={inherit}")
    idx = egraph.by_id(g)
    ok(egraph.effective_frontier_ancestor(idx, "N011") == "N010",
       "parent legality resolves through the repair to the lineage it repaired")
    ok(egraph.effective_frontier_ancestor(idx, "N010") == "N010",
       "a non-maintenance node resolves to itself")
    chain = node("N013", parents=["N011"], experiment_purpose="maintenance",
                 maintenance_parity="met", promotion="not_applicable",
                 scores={"lp_ap": 0.94, "lp_auc": 0.94, "nc_f1": 0.94, "nc_micro": 0.94})
    g2 = {"nodes": [base, repair, chain]}
    idx2 = egraph.by_id(g2)
    ok(egraph.effective_frontier_ancestor(idx2, "N013") == "N010",
       "a repair chain resolves to the scientific base, not the previous repair")
    ctx = evalid.Ctx(None, {}, cfg, g2, reg={})
    ref = evalid._reference_node_for_metric(ctx, chain, "lp_ap")
    ok(ref is not None and ref["id"] == "N010",
       f"anti-ratchet: repair parity settles against the scientific base ({ref and ref['id']})")
    candidate = node("N014", parents=["N011"], verdict=None, status="evaluating", scores={})
    ref_c = evalid._reference_node_for_metric(
        evalid.Ctx(None, {}, cfg, {"nodes": [base, repair, candidate]}, reg={}),
        candidate, "lp_ap")
    ok(ref_c is not None and ref_c["id"] == "N011",
       "but a candidate ON the repaired base still measures against that base - "
       "remapping it would credit the candidate with the repair's headroom")


def instrumental_nodes_do_not_count_as_scientific_descendants():
    """v10.2 R2: rollups must traverse THROUGH instrumental nodes without
    counting them, or a probe reports itself as an improved descendant in the
    strategy bundle."""
    cfg = cfg_of(FOUR_CELLS)
    base = node("N020", promotion="met",
                scores={"lp_ap": 0.90, "lp_auc": 0.90, "nc_f1": 0.90, "nc_micro": 0.90})
    probe = node("N021", parents=["N020"], experiment_purpose="diagnostic_probe",
                 scores={"lp_ap": 0.99, "lp_auc": 0.99, "nc_f1": 0.99, "nc_micro": 0.99})
    repair = node("N022", parents=["N020"], experiment_purpose="maintenance",
                  maintenance_parity="met",
                  scores={"lp_ap": 0.91, "lp_auc": 0.91, "nc_f1": 0.91, "nc_micro": 0.91})
    child = node("N023", parents=["N022"],
                 scores={"lp_ap": 0.93, "lp_auc": 0.93, "nc_f1": 0.93, "nc_micro": 0.93})
    g = {"nodes": [base, probe, repair, child]}
    egraph.recompute_rollups(g, cfg)
    roll = egraph.by_id(g)["N020"].get("rollup") or {}
    ok(roll.get("descendants") == 1 and roll.get("descendants_improved") == 1,
       f"only the real candidate below the repair counts as a descendant: {roll}")


def maintenance_gain_is_recorded_even_though_it_licenses_nothing():
    """v10.2 R2: a repair's recovered headroom had nowhere to be booked, which
    quietly punished doing the plumbing before the science."""
    assessment = {
        "target_cells": ["C1", "C2"], "guardrail_cells": ["C4"],
        "cells": {"C1": {"delta": 0.05, "status": "improved"},
                  "C2": {"delta": 0.0, "status": "noninferior"},
                  "C4": {"delta": -0.001, "status": "noninferior"}},
    }
    ok(evalid.maintenance_parity_status(assessment) == "met",
       "improved-or-noninferior across every decision cell settles parity")
    gain = evalid.maintenance_gain(assessment)
    ok(gain.get("C1", {}).get("delta") == 0.05 and set(gain) == {"C1", "C2", "C4"},
       f"the recovered headroom is frozen per decision cell: {gain}")
    regressed = {"target_cells": ["C1"], "guardrail_cells": [],
                 "cells": {"C1": {"delta": -0.2, "status": "regressed"}}}
    ok(evalid.maintenance_parity_status(regressed) == "not_met",
       "a regression anywhere fails parity closed")
    ok(evalid.maintenance_parity_status({"target_cells": [], "guardrail_cells": [],
                                         "cells": {}}) == "not_met",
       "no decision cells at all cannot silently settle as met")


def main():
    performance_frontier_is_measurement_only()
    inheritance_floor_has_an_exit()
    domination_uses_coverage_not_omniscience()
    mutual_domination_deletes_nobody()
    a_cycle_never_empties_the_frontier()
    no_survivor_is_beaten_by_an_evicted_node()
    strongest_parent_means_hardest_bar()
    archiving_does_not_delete_the_record()
    legality_does_not_depend_on_display_order()
    only_a_decided_advance_counts_as_progress()
    uncertainty_reads_the_declared_aggregation_too()
    contradictory_focus_policy_is_refused_at_config_time()
    required_group_reads_its_own_aggregation()
    matched_resources_accept_equal_cost()
    unsettled_is_not_refuted()
    promotion_status_separates_the_two_failures()
    strategist_sees_what_the_engine_knows()
    instrumental_purposes_are_frontier_transparent_both_ways()
    instrumental_nodes_do_not_count_as_scientific_descendants()
    maintenance_gain_is_recorded_even_though_it_licenses_nothing()
    print(f"V10 FRONTIER/SELECTION SEMANTICS GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
