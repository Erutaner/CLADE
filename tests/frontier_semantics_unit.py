#!/usr/bin/env python3
"""Frontier, selection and settlement semantics.

Regression cover for the field-report defects: a node holding every cell record
was invisible because its verdict was judged against its own parent, a
dominated origin could never be displaced, a required task group vetoed on a
cell its own contract marked optional, a matched resource axis could not be
satisfied by genuinely equal cost, and "not measured yet" was reported as
"claim refuted".  Pure unit level: no engine drive, no subprocesses.
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

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
    ok(required["verdict"] == "tradeoff" and required["required_target_losses"] == ["C2"]
       and required["deliverable"] is False and required["real_win"] is True,
       "a required cell that slipped is recorded as a loss and makes the node undeliverable, "
       f"but the real wins keep it a tradeoff, not a regression: {required['verdict']}")
    guard_slip = {"lp_ap": 0.90, "lp_auc": 0.90, "nc_f1": 0.90, "nc_micro": 0.70}
    guarded = evalid.computed_assessment(ctx, child, guard_slip)
    ok(guarded["verdict"] == "tradeoff" and guarded["guardrail_losses"] == ["C4"]
       and guarded["deliverable"] is False,
       f"a guardrail loss is a recorded loss and an undeliverable node, not a regression: {guarded['verdict']}")
    everything = {"lp_ap": 0.70, "lp_auc": 0.70, "nc_f1": 0.70, "nc_micro": 0.90}
    lost = evalid.computed_assessment(ctx, child, everything)
    ok(lost["verdict"] == "regressed" and lost["required_group_losses"] == ["G1", "G2"]
       and lost["real_win"] is False,
       f"a node that won nothing it claimed is regressed: {lost['verdict']}")


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
    # Retirement is a LINEAGE decision, never an observation one.
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
    # Resource rows are sub-rows of the bet's record: an unpriced comparator
    # leaves the RESOURCE block undecided (each gap named) and does not flip
    # the target row's own status.
    ok(contract["status"] == "met" and contract["resources"]["status"] == "uncertain"
       and contract["evidence_gaps"],
       f"an unpriced comparator leaves the resource block undecided, with reasons: {contract}")
    ok(all("comparator" in gap or "candidate" in gap for gap in contract["evidence_gaps"]),
       f"each gap names what is missing: {contract['evidence_gaps']}")
    ok(assessment["verdict"] == "improved",
       f"the performance verdict is unaffected: {assessment['verdict']}")


def promotion_status_separates_the_two_failures():
    cases = [
        # Inheritance follows the measured win; the bet's own record (met /
        # uncertain / failed) stays next to it as history and never vetoes.
        ({"status": "uncertain"}, "improved", "met"),
        ({"status": "failed"}, "improved", "met"),
        ({"status": "invalid"}, "improved", "blocked"),
        ({"status": "met"}, "regressed", "blocked"),
        # cells rose but the claim's own vote did not pass: decided against as
        # claimed (the post-hoc claim door re-scopes it), not an evidence gap
        ({"status": "partial"}, "partial", "blocked"),
        # A paradigm root AT parity with nothing regressed is stronger evidence
        # than the inconclusive below it; it cannot be the harsher status.
        ({"status": "uncertain"}, "promising", "pending_evidence"),
        ({"status": "uncertain"}, "inconclusive", "pending_evidence"),
        ({"status": "met"}, "improved", "met"),
        ({"status": "not_applicable"}, "regressed", "not_applicable"),
    ]
    for effect, verdict, expected in cases:
        got = evalid.promotion_status(verdict, effect, fidelity_settled=True)
        ok(got == expected, f"effect={effect['status']} verdict={verdict} -> {got}, expected {expected}")
    ok(evalid.promotion_status("improved", {"status": "met"}, fidelity_settled=False) == "pending_evidence",
       "an outstanding fidelity audit is an evidence gap, not a verdict against")
    # Gains here, losses there: a tradeoff with a real win on the claimed cells
    # inherits; a tradeoff that won nothing claimed does not.
    ok(evalid.promotion_status("tradeoff", {"status": "failed"}, fidelity_settled=True, real_win=True) == "met",
       "a tradeoff with a real claimed win is a legal parent even though the bet was lost")
    ok(evalid.promotion_status("tradeoff", {"status": "met"}, fidelity_settled=True, real_win=False) == "blocked",
       "a tradeoff without a claimed win is decided against")
    # Mechanism knowledge is written next to the node and gates planning
    # premises; it never decides parenthood - the function does not even read it.
    import inspect
    ok("mechanism" not in inspect.signature(evalid.promotion_status).parameters,
       "parenthood is decided by the claim and the build alone")
    # Noise-aware settlement of a frozen rule: the line is read with the
    # observations' own scatter, in both directions.
    rule = {"field": "gate", "aggregation": "mean", "comparison": ">=", "threshold": 1.0}
    inside = evalid.settle_decision_rule(rule, [1.0004, 0.9996, 1.0002, 0.9999, 1.0001])
    ok(inside["status"] == "unclear" and "scatter" in inside,
       f"a mean within two standard errors of the line is unclear, not a coin-flip verdict: {inside}")
    miss = evalid.settle_decision_rule(rule, [0.9944, 0.9947, 0.9942, 0.9945, 0.9947])
    ok(miss["status"] == "refuted", f"a miss well outside the scatter is refuted: {miss}")
    hit = evalid.settle_decision_rule(rule, [1.02, 1.03, 1.025, 1.04, 1.02])
    ok(hit["status"] == "confirmed", f"a clear pass is confirmed: {hit}")
    single = evalid.settle_decision_rule(rule, [0.9999])
    ok(single["status"] == "refuted" and "scatter" not in single,
       "one observation has no scatter to consult and settles on the bare comparison")


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
    # With neglect forcing ON the pair is always
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
    """A repair that measures BETTER must not evict the lineage it
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
    """Rollups must traverse THROUGH instrumental nodes without
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
    """A repair's recovered headroom had nowhere to be booked, which
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


def a_measured_node_keeps_its_ruler():
    """The per-cell judged constants freeze with the floors at eval absorb: a
    notebook correction of a worthwhile delta / margin / required flag changes
    the ruler for nodes measured after it, never for a node already measured."""
    cfg = cfg_of(FOUR_CELLS)
    parent = node("P", scores={"lp_ap": 0.80, "lp_auc": 0.80, "nc_f1": 0.80, "nc_micro": 0.80})
    measured = node("K", parents=["P"], verdict=None, status="evaluated", scores={},
                    eval_cells_frozen=evalid.frozen_cell_constants(cfg))
    g = {"nodes": [parent, measured]}
    metrics = {"lp_ap": 0.81, "lp_auc": 0.90, "nc_f1": 0.90, "nc_micro": 0.90}
    before = evalid.computed_assessment(evalid.Ctx(None, {}, cfg, g, reg={}), measured, metrics)
    ok(before["cells"]["C1"]["status"] == "improved" and before["verdict"] == "improved",
       f"under the ruler in force at measurement C1's +0.01 clears the 0.005 line: {before['verdict']}")
    corrected = copy.deepcopy(cfg)
    corrected["evaluation_contract"]["cells"][0]["min_improvement"] = 0.05
    corrected["evaluation_contract"]["cells"][1]["required"] = False
    corrected_ctx = evalid.Ctx(None, {}, corrected, g, reg={})
    after = evalid.computed_assessment(corrected_ctx, measured, metrics)
    ok(after == before, "the settlement of a measured node does not move under a later correction")
    held = evalid.settlement_cell_spec(corrected_ctx, measured)
    ok(held["C2"]["required"] is True and held["C1"]["min_improvement"] == 0.005,
       f"the node's ruler is the frozen one: {held['C1']}")
    later = node("L", parents=["P"], verdict=None, status="evaluating", scores={})
    fresh = evalid.computed_assessment(corrected_ctx, later, metrics)
    ok(fresh["cells"]["C1"]["status"] == "noninferior"
       and evalid.settlement_cell_spec(corrected_ctx, later)["C2"]["required"] is False,
       f"a node measured after the correction reads the corrected values: {fresh['cells']['C1']['status']}")
    ok(set(evalid.frozen_cell_constants(cfg)["C1"]) == set(evalid.FROZEN_CELL_KEYS),
       "the frozen ruler carries exactly the judged constants")


def the_group_rule_is_not_a_verdict_input():
    """decision.min_target_groups_improved is the claim's own vote, taken
    inside the groups the claim covers. A cell that rose while the vote failed
    on decided rows is `partial` (not a parent as claimed), never
    inconclusive; the vote passing plus a loss elsewhere is a tradeoff."""
    cells = [cell("C1", "T1", "target", "lp_ap", required=True),
             cell("C2", "T2", "target", "lp_auc"),
             cell("C3", "T2", "guardrail", "nc_micro")]
    cfg = cfg_of(cells)
    cfg["evaluation_contract"]["decision"]["min_target_groups_improved"] = 2
    parent = node("P", scores={"lp_ap": 0.80, "lp_auc": 0.80, "nc_micro": 0.80})
    child = node("K", parents=["P"], verdict=None, status="evaluating", scores={})
    ctx = evalid.Ctx(None, {}, cfg, {"nodes": [parent, child]}, reg={})
    split = evalid.computed_assessment(ctx, child, {"lp_ap": 0.90, "lp_auc": 0.70, "nc_micro": 0.80})
    ok(split["verdict"] == "partial" and split["real_win"] is False and split["group_rule_met"] is False
       and split["target_wins"] == ["C1"] and split["target_losses"] == ["C2"] and split["deliverable"] is False,
       f"C1 rose but C2 lost under a two-group vote: the claim does not stand - partial, not a parent, "
       f"never inconclusive: {split['verdict']}")
    clean = evalid.computed_assessment(ctx, child, {"lp_ap": 0.90, "lp_auc": 0.80, "nc_micro": 0.80})
    ok(clean["verdict"] == "partial" and clean["real_win"] is False and clean["group_rule_met"] is False
       and clean["target_wins"] == ["C1"] and not clean["target_losses"] and clean["deliverable"] is False
       and clean["overall_contract_pass"] is False,
       f"one group rose, nothing lost, but the vote wants two groups: partial - honest about the rise, "
       f"not a parent as claimed: {clean['verdict']}")
    cfg["evaluation_contract"]["decision"]["min_target_groups_improved"] = 1
    one = evalid.computed_assessment(ctx, child, {"lp_ap": 0.90, "lp_auc": 0.80, "nc_micro": 0.80})
    ok(one["verdict"] == "improved" and one["group_rule_met"] is True and one["deliverable"] is True,
       f"with the rule met the same numbers ship: {one['deliverable']}")
    quiet = evalid.computed_assessment(ctx, child, {"lp_ap": 0.80, "lp_auc": 0.80, "nc_micro": 0.80})
    ok(quiet["verdict"] == "inconclusive" and quiet["real_win"] is False and quiet["deliverable"] is False,
       f"nothing beyond noise and nothing lost is inconclusive: {quiet['verdict']}")
    guard_only = evalid.computed_assessment(ctx, child, {"lp_ap": 0.80, "lp_auc": 0.80, "nc_micro": 0.70})
    ok(guard_only["verdict"] == "regressed" and guard_only["guardrail_losses"] == ["C3"],
       f"no claimed win and a guardrail loss is regressed: {guard_only['verdict']}")
    undecided = evalid.computed_assessment(ctx, child, {"lp_ap": 0.90, "lp_auc": 0.80})
    ok(undecided["verdict"] == "inconclusive" and undecided["guardrail_uncertain"] == ["C3"],
       f"a real win with an unmeasured guardrail and no loss stays undecided: {undecided['verdict']}")
    undecided_loss = evalid.computed_assessment(ctx, child, {"lp_ap": 0.90, "lp_auc": 0.70})
    ok(undecided_loss["verdict"] == "tradeoff",
       f"a real win plus a loss is never inconclusive, unmeasured guardrail or not: {undecided_loss['verdict']}")


def the_effect_status_says_partial_when_the_rows_split():
    """met = every target row met and the group rule met; partial = the rows
    split, or all met but the group rule unmet; failed = no row met. Guardrail
    and resource rows stay recorded as sub-rows and never flip it."""
    cfg = cfg_of(FOUR_CELLS)
    equal = {axis: {"lower": 4.0, "upper": 6.0, "source": "r"} for axis in eprogram.RESOURCE_AXES}
    parent = node("P", scores={"lp_ap": 0.8, "lp_auc": 0.8, "nc_f1": 0.8, "nc_micro": 0.8}, resources=equal)
    child = node("K", parents=["P"], verdict=None, status="evaluating", scores={})
    ctx = evalid.Ctx(None, {}, cfg, {"nodes": [parent, child]}, reg={})
    meta = _effect_meta()
    meta["claim_scope"] = {"kind": "generalist", "target_cells": ["C1", "C2", "C3"], "guardrail_cells": []}
    meta["effect_case"]["chain"] = [
        {"target_cell": cid, "direction": "increase", "minimum_worthwhile_delta": 0.01,
         "expected_delta_interval": [0.02, 0.2]} for cid in ("C1", "C2")]
    res = {"_effect_resources": copy.deepcopy(equal)}
    split = evalid.effect_contract_assessment(
        ctx, child, {"lp_ap": 0.9, "lp_auc": 0.7, "nc_f1": 0.9, "nc_micro": 0.9, **res}, meta)
    ok(split["status"] == "partial" and split["targets"]["C1"]["status"] == "met"
       and split["targets"]["C2"]["status"] == "failed",
       f"one row met and one failed is partial: {split['status']}")
    guarded = {"lp_ap": 0.9, "lp_auc": 0.9, "nc_f1": 0.9, "nc_micro": 0.7, **res}
    both = evalid.effect_contract_assessment(ctx, child, guarded, meta)
    ok(both["status"] == "met" and both["guardrails"]["C4"]["status"] == "failed",
       f"a failed guardrail row is recorded and does not flip the status: {both['status']}")
    full = evalid.computed_assessment(ctx, child, guarded, meta_override=meta)
    ok(full["verdict"] == "tradeoff" and full["deliverable"] is False and full["effect_contract_status"] == "met",
       f"the guardrail loss still lands in the verdict and the deliverable: {full['verdict']}/{full['deliverable']}")
    none = evalid.effect_contract_assessment(
        ctx, child, {"lp_ap": 0.7, "lp_auc": 0.7, "nc_f1": 0.9, "nc_micro": 0.9, **res}, meta)
    ok(none["status"] == "failed", f"no row met is failed: {none['status']}")
    cfg["evaluation_contract"]["decision"]["min_target_groups_improved"] = 2
    rule = evalid.effect_contract_assessment(
        ctx, child, {"lp_ap": 0.9, "lp_auc": 0.9, "nc_f1": 0.8, "nc_micro": 0.9, **res}, meta)
    ok(rule["status"] == "partial" and rule["group_rule_met"] is False
       and all(r["status"] == "met" for r in rule["targets"].values()),
       f"every row met but the portfolio rule unmet is partial: {rule['status']}")
    ok(evalid.promotion_status("tradeoff", {"status": "partial"}, fidelity_settled=True, real_win=True) == "met",
       "a partial bet does not veto a lineage that really moved the numbers")
    # the same metrics judged as a whole: cells rose, the vote did not pass
    part = evalid.computed_assessment(
        ctx, child, {"lp_ap": 0.9, "lp_auc": 0.9, "nc_f1": 0.8, "nc_micro": 0.9, **res}, meta_override=meta)
    ok(part["verdict"] == "partial" and part["real_win"] is False and part["group_rule_met"] is False
       and part["target_wins"] and part["scientific_promotion_status"] == "blocked"
       and part["deliverable"] is False,
       f"cells rose but the claim's vote failed: partial, not a parent as claimed: {part['verdict']}")


def the_efficiency_branch_prices_wins_and_losses_honestly():
    """regressed when no improvement cell improved and something lost; tradeoff
    only when an improvement cell improved and something lost; dominant needs
    no loss anywhere; a parity-only dominant is a win and deliverable."""
    cells = [cell("C1", "T1", "target", "a"), cell("C2", "T2", "target", "b"),
             cell("C3", "T3", "target", "c")]
    cfg = cfg_of(cells)
    equal = {axis: {"lower": 4.0, "upper": 6.0, "source": "r"} for axis in eprogram.RESOURCE_AXES}
    parent = node("P", scores={"a": 0.8, "b": 0.8, "c": 0.8}, resources=equal)
    child = node("K", parents=["P"], verdict=None, status="evaluating", scores={})
    ctx = evalid.Ctx(None, {}, cfg, {"nodes": [parent, child]}, reg={})
    meta = _effect_meta()
    meta["effect_case"]["chain"] = [{"target_cell": "C1", "direction": "increase", "minimum_worthwhile_delta": 0.01,
                                     "expected_delta_interval": [0.02, 0.2]}]
    meta["claim_scope"] = {"kind": "efficiency", "target_cells": ["C1", "C2"], "improvement_cells": ["C1"],
                           "parity_cells": ["C2"], "guardrail_cells": []}
    meta["dominance"] = {"metric": "a", "comparison": ">=", "value": 0.85}
    res = {"_effect_resources": copy.deepcopy(equal)}

    def settle(metrics):
        return evalid.computed_assessment(ctx, child, {**metrics, **res}, meta_override=meta)

    no_win = settle({"b": 0.7, "c": 0.8})
    ok(no_win["verdict"] == "regressed" and no_win["real_win"] is False and no_win["target_losses"] == ["C2"],
       f"no improvement cell improved and a parity cell lost: regressed, not tradeoff: {no_win['verdict']}")
    win_loss = settle({"a": 0.9, "b": 0.7, "c": 0.8})
    ok(win_loss["verdict"] == "tradeoff" and win_loss["real_win"] is True and win_loss["target_losses"] == ["C2"],
       f"an improvement cell won and a parity cell lost: tradeoff: {win_loss['verdict']}")
    breadth = settle({"a": 0.9, "b": 0.8, "c": 0.7})
    ok(breadth["verdict"] == "tradeoff" and breadth["breadth_losses"] == ["C3"],
       f"a breadth loss is a loss, so dominance is off the table: {breadth['verdict']}")
    clean = settle({"a": 0.9, "b": 0.8, "c": 0.8})
    ok(clean["verdict"] == "dominant" and clean["deliverable"] is True and clean["real_win"] is True,
       f"the improvement cell won, parity held, nothing lost: dominant: {clean['verdict']}")
    meta["claim_scope"] = {"kind": "efficiency", "target_cells": ["C1", "C2"], "improvement_cells": [],
                           "parity_cells": ["C1", "C2"], "guardrail_cells": []}
    meta["effect_case"]["chain"] = [{"target_cell": "C1", "direction": "stabilize", "minimum_worthwhile_delta": 0.01,
                                     "expected_delta_interval": [-0.01, 0.01]}]
    parity = settle({"a": 0.8, "b": 0.8, "c": 0.8})
    ok(parity["verdict"] == "dominant" and parity["real_win"] is False and parity["deliverable"] is True
       and parity["scientific_promotion_status"] == "met",
       f"same quality, cheaper: a parity-only dominant is a win and deliverable: {parity['verdict']}/"
       f"{parity['deliverable']}")


def one_retrain_at_the_parents_own_caps_is_inside_at_both_gates():
    """allowed = max(k x charged, one run, the parent's declared caps per run):
    the idea gate (runs x per-run charge) and the workflow gate (the spec's
    caps) agree that one retrain at the parent's caps is inside. A planned
    unit the parent never charged is never inside - it cannot be compared."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        spec = {"workflow": {"stages": [{"id": "train", "budget": {"limits": {"gpu_hours": 10}}}]},
                "eval": {"budget": {"limits": {"gpu_hours": 0.5}}}}
        (repo / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
        cfg = cfg_of(FOUR_CELLS)
        cfg["evidence_policy"]["ablation"] = {"budget_multiple": 1.0}
        parent = node("P", scores={"lp_ap": 0.8, "lp_auc": 0.8, "nc_f1": 0.8, "nc_micro": 0.8}, spec="spec.json")
        st = {"resource_ledger": [{"id": "RC1", "node": "P", "kind": "stage", "usage": {"gpu_hours": 6.0}}]}
        ctx = evalid.Ctx(SimpleNamespace(repo=repo), st, cfg, {"nodes": [parent]}, reg={})
        a = evalid.ablation_allowance(ctx, "P")
        ok(a["parent_charged"] == {"gpu_hours": 6.0} and a["declared_caps"] == {"gpu_hours": 10.5}
           and a["allowed"] == {"gpu_hours": 10.5},
           f"k=1 on a parent charged 6 under caps 10 + 0.5 allows one retrain at those caps: {a}")
        design_inside, design_lines = evalid.ablation_within_allowance(a, evalid.ablation_design_estimate(a, 1))
        spec_inside, spec_lines = evalid.ablation_within_allowance(a, evalid.ablation_planned_cost(spec))
        ok(design_inside and spec_inside and "vs allowed 10.5" in spec_lines[0]
           and "one retrain at the parent's own caps 10.5" in spec_lines[0],
           f"both gates price the one-retrain design inside: {design_lines} / {spec_lines}")
        two_runs = json.loads(json.dumps(spec))
        two_runs["training_replication"] = {"source": "workflow", "seeds": [1, 2]}
        above, above_lines = evalid.ablation_within_allowance(a, evalid.ablation_planned_cost(two_runs))
        ok(not above and "ABOVE" in above_lines[0] and "planned 20.5" in above_lines[0],
           f"two retrains at the caps are above k=1: {above_lines}")
        mixed, mixed_lines = evalid.ablation_within_allowance(a, {"gpu_hours": 5.0, "api_tokens": 5e6})
        ok(not mixed and len(mixed_lines) == 2 and mixed_lines[0].startswith("api_tokens: planned 5e+06")
           and "cannot be compared" in mixed_lines[0] and "inside" in mixed_lines[1],
           f"a planned unit the parent never charged makes the design not-inside and says so: {mixed_lines}")
        empty, empty_lines = evalid.ablation_within_allowance(a, {})
        ok(not empty and "nothing to compare" in empty_lines[0],
           f"no declared caps: nothing to compare, the user decides: {empty_lines}")
        cfg["evidence_policy"]["ablation"] = {"budget_multiple": 0.5}
        a = evalid.ablation_allowance(ctx, "P")
        ok(a["allowed"] == {"gpu_hours": 10.5},
           f"a multiple below one retrain still allows one retrain at the parent's caps: {a['allowed']}")
        del parent["spec"]
        a = evalid.ablation_allowance(ctx, "P")
        ok(a["allowed"] == {"gpu_hours": 6.0} and a["declared_caps"] == {},
           f"without a spec the floor is one run of the parent's charge: {a['allowed']}")


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
    a_measured_node_keeps_its_ruler()
    the_group_rule_is_not_a_verdict_input()
    the_effect_status_says_partial_when_the_rows_split()
    the_efficiency_branch_prices_wins_and_losses_honestly()
    one_retrain_at_the_parents_own_caps_is_inside_at_both_gates()
    print(f"FRONTIER / SELECTION SEMANTICS GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
