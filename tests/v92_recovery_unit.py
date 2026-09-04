#!/usr/bin/env python3
"""Pure unit checks for the v9.2 recovery planning helpers."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG / "engine"))

import erecover  # noqa: E402


CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[check {CHECKS}] {message}")


def fixture():
    state = {
        "lanes": [
            {"id": "L001", "round": "R001", "status": "done", "node": "N002",
             "idea": "I001", "idea_seal": {"digest": "idea-a"}},
            {"id": "L002", "round": "R002", "status": "node_created", "node": "N005"},
        ],
        "runs": [
            {"id": "RUN001", "node": "N002", "kind": "stage", "status": "finished",
             "evidence_status": "valid", "evidence_seal": {"digest": "run-a"},
             "resource_accounted": True, "resource_usage": {"gpu_hours": 2.0}},
            {"id": "RUN002", "node": "N003", "kind": "stage", "status": "running",
             "evidence_status": "pending", "job": "job-2",
             "resource_reservation": {"gpu_hours": 3.0}},
            {"id": "RUN003", "node": "N005", "kind": "eval", "status": "prepared",
             "evidence_status": "pending", "resource_reservation": {"gpu_hours": 1.0}},
            {"id": "RUN004", "node": "N005", "kind": "eval", "status": "finished",
             "evidence_status": "pending", "job": "job-4", "resource_accounted": True},
            {"id": "RUN005", "node": "N006", "kind": "stage", "status": "launch_unknown",
             "evidence_status": "pending", "resource_reservation": {"gpu_hours": 1.0}},
            {"id": "RUN006", "node": "N006", "kind": "stage", "status": "cancelled",
             "evidence_status": "complete", "adoption_status": "quarantined",
             "confirmed_not_launched": True, "resource_accounted": True,
             "resource_charge_basis": "confirmed_unlaunched", "resource_usage": {}},
        ],
        "holds": [
            {"id": "H001", "scope": {"kind": "node", "id": "N002"}, "status": "active"},
            {"id": "H002", "scope": {"kind": "project"}, "status": "released"},
        ],
    }
    graph = {"nodes": [
        {"id": "N001", "round": None, "lane": None, "role": "baseline", "parents": [],
         "status": "concluded", "verdict": "baseline", "retire_reason": None,
         "spec_seal": {"digest": "spec-base"}},
        {"id": "N002", "round": "R001", "lane": "L001", "role": "variant", "parents": ["N001"],
         "code_parent": "N001", "status": "concluded", "verdict": "improved", "retire_reason": None,
         "eval_seal": {"digest": "eval-a"}, "conclusion_seal": {"digest": "conclusion-a"},
         "evidence_heads": {"stage:0:0": "RUN001"}},
        {"id": "N003", "round": "R001", "lane": "L001", "role": "variant", "parents": ["N002"],
         "code_parent": "N002", "status": "executing", "verdict": None, "retire_reason": None},
        {"id": "N004", "round": "R002", "lane": None, "role": "platform", "parents": [],
         "status": "concluded", "verdict": "enabled", "retire_reason": None,
         "enabled_services": [{"name": "search-service"}]},
        {"id": "N005", "round": "R002", "lane": "L002", "role": "variant", "parents": ["N001"],
         "status": "evaluating", "verdict": None, "retire_reason": None},
        {"id": "N006", "round": "R002", "lane": None, "role": "variant", "parents": ["N001"],
         "status": "approved", "verdict": None, "retire_reason": None},
        {"id": "N007", "round": "R002", "lane": None, "role": "variant", "parents": ["N004"],
         "code_parent": "N004", "effect_comparator_node": "N001",
         "status": "concluded", "verdict": "improved", "retire_reason": None},
    ]}
    registry = {"artifacts": [
        {"id": "AR001", "node": "N003", "status": "available", "uri": "remote://a"},
    ]}
    specs = {
        "N005": {"workflow": {"stages": [{"consumes": [{"artifact": "AR001"}]}]}},
        "N006": {"workflow": {"stages": [{"requires_services": ["search-service"]}]}},
    }
    return state, graph, registry, specs


def scope_and_hold_checks() -> None:
    state, graph, _registry, _specs = fixture()
    check(erecover.normalize_scope("node:N002") == {"kind": "node", "id": "N002"},
          "string scope must normalize")
    check(erecover.scope_members("lane:L001", state, graph) == {
        "lanes": ["L001"], "nodes": ["N002", "N003"], "runs": ["RUN001", "RUN002"]},
        "lane scope must retain historical nodes and their runs")
    check(erecover.scope_members("run:RUN002", state, graph) == {
        "lanes": ["L001"], "nodes": ["N003"], "runs": ["RUN002"]},
        "run scope must resolve owner without pulling siblings")
    check(erecover.scope_members("round:R002", state, graph)["nodes"] == ["N004", "N005", "N006", "N007"],
          "round scope must resolve every node in the round")
    check(erecover.is_held(state, graph, node="N002"), "active node hold must apply")
    check(not erecover.is_held(state, graph, node="N003"), "node hold must not widen to same-lane siblings")
    check(erecover.active_holds_for_subject(state, graph, run="RUN001") == ["H001"],
          "run must inherit its node hold")


def dependency_checks() -> None:
    state, graph, registry, specs = fixture()
    impact = erecover.hard_descendants(graph, registry, specs, ["N002"])
    check(impact["nodes"] == ["N003", "N005"],
          f"graph then artifact consumption must be transitive: {impact}")
    edge_reasons = {(row["source"], row["consumer"]): row["reasons"] for row in impact["edges"]}
    check(edge_reasons[("N002", "N003")] == ["code_parent", "graph_parent"],
          "duplicate hard edges must retain both exact reasons")
    check(edge_reasons[("N003", "N005")] == ["artifact:AR001"],
          "artifact consumption must be a hard edge")
    services = erecover.hard_descendants(graph, registry, specs, ["N004"])
    check(services["nodes"] == ["N006", "N007"], "platform service and graph consumption must be hard edges")
    comparator = erecover.hard_descendants(graph, registry, specs, ["N001"])
    check("N007" in comparator["nodes"] and any(
        row["source"] == "N001" and row["consumer"] == "N007" and
        row["reasons"] == ["effect_comparator"] for row in comparator["edges"]),
        "a frozen baseline comparator must be a hard edge even when it is not a parent")

    knowledge = erecover.soft_knowledge_impact(
        ["N002"],
        {"lessons": [{"id": "LS001", "node": "N002"}, {"id": "LS002", "node": "N005"}],
         "observations": [{"id": "OB001", "source_node": "N002"}]},
        [{"id": "T0100", "status": "done", "input_refs": ["LS001"]},
         {"id": "T0101", "status": "open", "_render": {"knowledge_refs": [{"id": "OB001"}]}},
         {"id": "T0102", "status": "done", "input_refs": ["LS002"]}],
    )
    check(knowledge["refs"] == ["LS001", "OB001"], "only target-produced knowledge should be returned")
    check([row["task"] for row in knowledge["task_exposures"]] == ["T0100", "T0101"],
          "only explicit soft exposures should be reported")

    operational = erecover.operational_run_impact(state, node_ids=["N005"])
    check(operational["unresolved"] == ["RUN003"], "prepared RUN must block authority changes")
    check(operational["evidence_pending"] == ["RUN004"], "finished incomplete evidence must be distinct")
    check(operational["external_effects"] == ["RUN004"],
          "mere prepared reservation is not proof of an external side effect")
    check(operational["blocks_authority_change"] and operational["requires_compensation"],
          "operational summary must expose both independent hazards")
    unknown = erecover.operational_run_impact(state, run_ids=["RUN005"])
    check(unknown["blocks_authority_change"] and unknown["requires_compensation"],
          "launch_unknown must remain blocked and compensatable without a job id")
    unspent = erecover.operational_run_impact(state, run_ids=["RUN006"])
    check(not unspent["blocks_authority_change"] and not unspent["requires_compensation"],
          "a confirmed-unlaunched cancelled intent must neither block recovery nor invent an external effect")


def plan_and_head_checks() -> None:
    state, graph, registry, _specs = fixture()
    a = {"target": {"kind": "node", "id": "N002"}, "actions": {"replace", "reopen"},
         "reason": "test"}
    b = {"reason": "test", "actions": {"reopen", "replace"},
         "target": {"id": "N002", "kind": "node"}, "plan_digest": "ignored"}
    check(erecover.plan_digest(a) == erecover.plan_digest(b),
          "canonical digest must ignore key/set order and its self field")
    b["reason"] = "changed"
    check(erecover.plan_digest(a) != erecover.plan_digest(b), "semantic plan changes must change digest")
    try:
        erecover.plan_digest({"x": float("nan")})
    except ValueError:
        pass
    else:
        check(False, "NaN must not enter a recovery plan")

    expected = erecover.capture_head_preconditions("node:N002", state, graph, registry)
    check(not erecover.verify_head_preconditions(expected, state, graph, registry),
          "fresh head snapshot must verify")
    # Unrelated state is deliberately outside this scoped precondition.
    next(n for n in graph["nodes"] if n["id"] == "N006")["status"] = "building"
    check(not erecover.verify_head_preconditions(expected, state, graph, registry),
          "unrelated lane progress must not invalidate a node recovery plan")
    next(n for n in graph["nodes"] if n["id"] == "N002")["eval_seal"]["digest"] = "eval-b"
    errors = erecover.verify_head_preconditions(expected, state, graph, registry)
    check(errors and errors[0].startswith("RECOVERY_HEAD_CHANGED"),
          f"target head drift must fail closed: {errors}")
    project_heads = erecover.capture_head_preconditions("project", state, graph, registry)
    state["bootstrap_contract_digest"] = "changed-contract"
    check(erecover.verify_head_preconditions(project_heads, state, graph, registry),
          "project recovery plan must bind the foundational contract head")


def classification_checks() -> None:
    check(erecover.supported_actions("frontier") == frozenset({"recompute"}),
          "frontier must remain derived-only")
    repair = erecover.classify_boundary_action(
        "stage_evidence", changes_authority=True, same_contract=True, evidence_incomplete=True)
    check(repair["actions"] == ["repair"], "same-attempt evidence completion is repair")
    spec = erecover.classify_boundary_action("spec", changes_authority=True, same_contract=True)
    check(spec["actions"] == ["fork_node"], "accepted spec correction gets a new node")
    impl = erecover.classify_boundary_action("implementation", changes_authority=True,
                                               same_contract=True, external_effects=True)
    check(impl["actions"] == ["replace", "reopen", "compensate"]
          and impl["replay_from"] == "workflow",
          "implementation revision replays its suffix and preserves external effects")
    eval_impl = erecover.classify_boundary_action(
        "implementation", changes_authority=True, same_contract=True,
        repair_scope="evaluation")
    check(eval_impl["actions"] == ["replace", "reopen"]
          and eval_impl["replay_from"] == "evaluation",
          "evaluation-only implementation recovery preserves the completed workflow suffix")
    consumed = erecover.classify_boundary_action("conclusion", changes_authority=True,
                                                   same_contract=True, cross_owner_consumers=True)
    check(consumed["actions"] == ["fork_node"], "cross-owner authority cannot be silently rewritten")
    bootstrap = erecover.classify_boundary_action("bootstrap", changes_authority=True,
                                                    same_contract=False, foundation_consumed=True)
    check(bootstrap["actions"] == ["fork_project"], "consumed foundational change needs a new project")
    check(erecover.classify_boundary_action("frontier", changes_authority=True)["actions"] == ["recompute"],
          "frontier correction is recomputation")
    check(erecover.classify_boundary_action("round", changes_authority=True)["actions"] == ["annotate"],
          "closed round correction is annotation")


def main() -> None:
    scope_and_hold_checks()
    dependency_checks()
    plan_and_head_checks()
    classification_checks()
    print(f"V9.2 RECOVERY UNIT GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
