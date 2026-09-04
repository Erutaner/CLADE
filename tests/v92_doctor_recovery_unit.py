#!/usr/bin/env python3
"""Focused doctor checks for v9.2 RUN and recovery-control integrity."""
from __future__ import annotations

import copy
import os
import shutil
import sys
import uuid
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))

import edoctor  # noqa: E402
import erecover  # noqa: E402
import erun  # noqa: E402
import estore  # noqa: E402
import eutil  # noqa: E402


CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[check {CHECKS}] {message}")


def fresh_run(rid: str, *, existing=(), token: str) -> dict:
    run = {
        "id": rid, "node": "N002", "kind": "eval", "stage": None,
        "stage_index": None, "replica_index": None, "replica_total": None,
        "replica_seed": None, "contract_digest": "spec+impl:r1",
        "implementation_digest": "impl:r1", "status": "prepared",
        "evidence_status": "pending", "adoption_status": "candidate",
        "job": None, "started_at": None, "ended_at": None,
    }
    erun.initialize_run(
        run, existing_runs=existing, token=token,
        now="2026-01-01T00:00:00+00:00")
    return run


def head_seal_check() -> None:
    state = {"lanes": [], "runs": []}
    graph = {"nodes": [{
        "id": "N002", "lane": None, "status": "building",
        "metric_bridge_seal": {"digest": "bridge:v1"},
    }]}
    registry = {"artifacts": []}
    heads = erecover.capture_head_preconditions(
        {"kind": "node", "id": "N002"}, state, graph, registry)
    check(heads["nodes"]["N002"]["seals"]["metric_bridge_seal"] == "bridge:v1",
          "recovery head must bind the metric-bridge seal")
    graph["nodes"][0]["metric_bridge_seal"]["digest"] = "bridge:v2"
    check(any(error.startswith("RECOVERY_HEAD_CHANGED") for error in
              erecover.verify_head_preconditions(heads, state, graph, registry)),
          "metric-bridge drift must invalidate a frozen recovery plan")


def doctor_control_check() -> None:
    # tempfile uses a restrictive Windows ACL that the managed test sandbox
    # cannot reopen; a uniquely named ordinary directory stays inside tests.
    repo = HERE / f"v92-doctor-{uuid.uuid4().hex}"
    repo.mkdir()
    try:
        store = estore.Store(repo)
        store.init("doctor recovery unit", "audit control-plane consistency")
        plan = {
            "id": "REC001", "scope": {"kind": "project"},
            "target": "project", "actions": ["repair"],
        }
        digest = erecover.plan_digest(plan)
        plan["plan_digest"] = digest
        plan_path = ".evo/recoveries/REC001/plan.json"
        eutil.write_json_atomic(store.repo / plan_path, plan)

        first = fresh_run("RUN001", token="run_0123456789abcdefghij")
        second = fresh_run(
            "RUN002", existing=[first], token="run_abcdefghij0123456789")
        state = store.load_state()
        state["runs"] = [first, second]
        state["holds"] = [{
            "id": "H001", "status": "active", "scope": {"kind": "project"},
        }]
        state["recoveries"] = [{
            "id": "REC001", "status": "planned", "scope": {"kind": "project"},
            "target": "project", "plan_path": plan_path, "plan_digest": digest,
        }]
        store.save_state(state)

        problems, _ = edoctor.diagnose(store, fix=False)
        check(any(problem.startswith("RUN_SLOT_CONCURRENT") for problem in problems),
              "doctor must invoke the collection-level RUN slot audit")
        check(not any(problem.startswith(("HOLD_", "RECOVERY_")) for problem in problems),
              f"well-formed recovery controls must pass doctor: {problems}")

        before = copy.deepcopy(state["recoveries"])
        plan["actions"].append("reopen")
        eutil.write_json_atomic(store.repo / plan_path, plan)
        control_errors = edoctor._recovery_control_errors(store, state, store.load_graph())
        check(any(problem.startswith("RECOVERY_PLAN_DIGEST") for problem in control_errors),
              "doctor must detect a plan changed after its digest was recorded")
        check(state["recoveries"] == before,
              "recovery audit must not rewrite recovery facts")

        state["holds"].append(copy.deepcopy(state["holds"][0]))
        state["recoveries"][0]["plan_path"] = "../outside-plan.json"
        control_errors = edoctor._recovery_control_errors(store, state, store.load_graph())
        check(any(problem.startswith("HOLD_DUP_ID") for problem in control_errors),
              "duplicate hold identities must be diagnosed")
        check(any(problem.startswith("RECOVERY_PLAN_PATH") for problem in control_errors),
              "doctor must not follow a recovery plan path outside the repository")
    finally:
        shutil.rmtree(repo)


def instrumental_route_status_check() -> None:
    """v10.2: an instrumental lane must only ever hold a status on its own route.

    Lane status is written from several places, so a mis-routed rewind parks the
    lane in a candidate status whose scheduler branch then asks for artifacts
    the lane never had.  That reads like a missing feature rather than the
    corrupted record it is, so doctor names it directly.
    """
    import eflow

    repo = HERE / f"v102-route-{uuid.uuid4().hex}"
    repo.mkdir()
    try:
        store = estore.Store(repo)
        store.init("instrumental route audit", "lane status must stay on its route")
        state = store.load_state()

        def lane(lid, purpose, status):
            return {"id": lid, "round": "R001", "name": lid.lower(), "status": status,
                    "experiment_purpose": purpose, "intent": "exploit",
                    "search_origin": "repair", "min_level": 0, "parents": ["N001"],
                    "idea": None, "node": None, "theory_path": None, "formal": False}

        lanes = [lane("L001", "diagnostic_probe", "mature"),
                 lane("L002", "diagnostic_probe", "probe_design"),
                 lane("L003", "maintenance", "maintenance_review"),
                 lane("L004", "maintenance", "abandoned"),
                 lane("L005", "targeted_ablation", "sketch"),
                 lane("L006", "candidate", "mature")]
        state["lanes"] = lanes
        store.save_state(state)

        problems, _ = edoctor.diagnose(store, fix=False)
        # "LANE_ROUTE_STATUS: <purpose> lane <id> is in status ..."
        flagged = {p.split()[3] for p in problems if p.startswith("LANE_ROUTE_STATUS")}
        check(flagged == {"L001", "L005"},
              f"doctor must flag exactly the off-route instrumental lanes, got {flagged} "
              f"from {[p for p in problems if p.startswith('LANE_ROUTE_STATUS')]}")

        # A lost idea file must be reported at every status from a lane's own
        # review step onward. The status list gained "ablation_review" when
        # ablation arrived and was not extended for maintenance_review, so a
        # corrupted maintenance lane passed doctor and failed later inside
        # v_maintenance_review as an opaque load error.
        for status, expect in (("maintenance_review", True), ("ablation_review", True),
                               ("red_team", True), ("maintenance_design", False)):
            lost = lane("L010", "maintenance" if "maint" in status else "targeted_ablation", status)
            lost["idea"] = "I099"
            state["lanes"] = [lost]
            store.save_state(state)
            problems, _ = edoctor.diagnose(store, fix=False)
            found = any(p.startswith("LANE_IDEA_MISSING") for p in problems)
            check(found == expect,
                  f"a missing idea file at status {status!r} must{'' if expect else ' not'} be "
                  f"reported (got {found})")

        # Every status on a purpose's own route, plus the terminal pair, is legal
        # - the audit must not creep into rejecting the flow the engine drives.
        for purpose, seq in eflow.INSTRUMENTAL_SEQ.items():
            for status in tuple(seq) + ("done", "abandoned"):
                state["lanes"] = [lane("L001", purpose, status)]
                store.save_state(state)
                problems, _ = edoctor.diagnose(store, fix=False)
                check(not any(p.startswith("LANE_ROUTE_STATUS") for p in problems),
                      f"{purpose} lane in {status!r} is on its own route and must pass: "
                      f"{[p for p in problems if p.startswith('LANE_ROUTE_STATUS')]}")
    finally:
        shutil.rmtree(repo)


def main() -> None:
    head_seal_check()
    doctor_control_check()
    instrumental_route_status_check()
    print(f"V9.2 DOCTOR RECOVERY UNIT GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
