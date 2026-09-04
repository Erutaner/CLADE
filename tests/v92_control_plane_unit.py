#!/usr/bin/env python3
"""Small contradiction tests for v9.2 holds and recovery impact discovery."""
from __future__ import annotations

import os
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))

import erecover  # noqa: E402
import esched  # noqa: E402
import evalid  # noqa: E402


CHECKS = 0


def check(value: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not value:
        raise AssertionError(f"[check {CHECKS}] {message}")


def raises_value_error(fn, message: str) -> None:
    try:
        fn()
    except ValueError:
        check(True, message)
    else:
        check(False, message)


def fixture() -> tuple[dict, dict]:
    state = {
        "current_round": "R001",
        "rounds": [{"id": "R001", "closed_at": "t", "improved": False}],
        "lanes": [
            {"id": "L001", "round": "R001", "status": "done", "node": "N002",
             "parents": ["N001"]},
            {"id": "L002", "round": "R001", "status": "diagnose", "node": None,
             "parents": ["N001"]},
        ],
        "runs": [
            {"id": "RUN001", "node": "N001"},
            {"id": "RUN002", "node": "N002"},
        ],
        "holds": [],
    }
    graph = {"nodes": [
        {"id": "N001", "lane": "L001", "round": "R001", "parents": [],
         "result_doc": ".evo/nodes/N001/NODE_RESULT_r2.md",
         "eval_metrics_path": ".evo/nodes/N001/eval/metrics_r2.json"},
        {"id": "N002", "lane": "L001", "round": "R001", "parents": []},
    ]}
    return state, graph


def scope_and_hold_checks() -> None:
    state, graph = fixture()
    check(not erecover.subject_in_scope(
        "node:N001", state, graph, lane="L001", node="N002", round_="R001"),
        "node scope must not expand through its owning lane to a sibling node")
    h1 = {"id": "H001", "scope": {"kind": "node", "id": "N001"},
          "members": {"lanes": ["L001"], "nodes": ["N001"], "runs": ["RUN001"]},
          "status": "active"}
    h2 = {"id": "H002", "scope": {"kind": "node", "id": "N002"},
          "members": {"lanes": ["L001"], "nodes": ["N002"], "runs": ["RUN002"]},
          "status": "active"}
    state["holds"] = [h1, h2]
    check(not erecover.hold_covers_subject(
        h1, state, graph, lane="L001", node="N002", round_="R001"),
        "descriptive owner members must not widen a node hold to a sibling in the same lane/round")
    check(erecover.active_holds_for_subject(state, graph, round_="R001") == ["H001", "H002"],
          "both node holds must continue to cover a shared round-closing task")
    raises_value_error(lambda: erecover.scope_members("round:R999", state, graph),
                       "an unknown round must be rejected before a no-op hold is created")


def pending_consumer_checks() -> None:
    state, graph = fixture()
    tasks = [{
        "id": "T001", "status": "open", "type": "diagnose",
        "subject": {"lane": "L002", "round": "R001"},
        "_render": {"inputs": [
            [".evo/nodes/N001/NODE_RESULT_r2.md", "active parent result"]]},
    }]
    impact = erecover.pending_authority_consumers(
        graph, state["lanes"], tasks, ["N001"])
    check(impact["lanes"] == ["L002"],
          "a lane committed to the recovering parent is a real pending consumer")
    check([row["task"] for row in impact["tasks"]] == ["T001"],
          "a materialized active-head input must appear in the impact plan")


def round_projection_checks() -> None:
    ctx = SimpleNamespace(st={"rounds": [
        {"id": "R001", "closed_at": "t1", "improved": False},
        {"id": "R002", "closed_at": "t2", "improved": None,
         "projection_status": "invalidated_by_recovery"},
    ]})
    check(not evalid._stagnant_window(ctx, 2),
          "invalidated historical authority must not be misread as a flat round")
    ctx.st["rounds"][1] = {"id": "R002", "closed_at": "t2", "improved": False}
    check(evalid._stagnant_window(ctx, 2),
          "two active, explicitly flat snapshots still establish stagnation")


def stage_probe_gap_reaches_eval_checks() -> None:
    """An eval RUN inherits the adopted stage producer's explicit probe gap."""
    node = {"id": "N010", "evidence_heads": {"stage:0:0": "RUN-STAGE"}}
    stage_run = {
        "id": "RUN-STAGE", "node": "N010", "adoption_status": "adopted",
        "probe_evidence_status": "unavailable", "probe_gap_receipt": ".evo/gap.json",
    }
    spec = {"probe_execution": {
        "mode": "same_run", "producer_stage": "train",
        "artifact": ".evo/missing-probe.json", "required_fields": ["signal"],
    }}
    eng = object.__new__(esched.Engine)
    eng.store = SimpleNamespace(repo=HERE)
    eng.st = {"runs": [stage_run]}
    eng.cfg, eng.g, eng.reg = {}, {"nodes": [node]}, {"artifacts": []}
    eng._spec = lambda _node: spec
    seen: dict[str, bool] = {}
    original_eval = evalid.evaluation_result_errors
    original_resource = evalid.resource_measurement_errors
    try:
        def capture(_ctx, _spec, _path, *, where, allow_probe_unavailable=False, **_kwargs):
            seen["allow"] = bool(allow_probe_unavailable)
            return []
        evalid.evaluation_result_errors = capture
        evalid.resource_measurement_errors = lambda *_args, **_kwargs: []
        errors = eng._run_result_errors(
            {"id": "RUN-EVAL", "kind": "eval", "metrics_file": None},
            node, enforce_current=True)
    finally:
        evalid.evaluation_result_errors = original_eval
        evalid.resource_measurement_errors = original_resource
    check(not errors and seen.get("allow") is True,
          "eval validation must read the active stage producer's gap instead of demanding a second waiver")


def probe_landing_overwrite_cannot_rewrite_history() -> None:
    """A reused producer path must resolve to the first RUN-owned snapshot."""
    repo = HERE / "out" / "v92_probe_snapshot"
    repo.mkdir(parents=True, exist_ok=True)
    landing = repo / "probe.json"
    landing.write_text(json.dumps({"signal": 1.0}), encoding="utf-8")
    node = {"id": "N020", "evidence_heads": {"stage:0:0": "RUN-STAGE"}}
    run = {
        "id": "RUN-STAGE", "node": "N020", "kind": "stage", "stage": "train",
        "replica_seed": None, "adoption_status": "adopted",
    }
    spec = {"probe_execution": {
        "mode": "same_run", "producer_stage": "train", "artifact": "probe.json",
        "required_fields": ["signal"], "signal": "hidden activation",
        "expect": "activation remains positive",
    }}
    eng = object.__new__(esched.Engine)
    eng.store = SimpleNamespace(repo=repo, event=lambda *_args, **_kwargs: None)
    eng.st = {"runs": [run]}
    eng.cfg, eng.g, eng.reg = {}, {"nodes": [node]}, {"artifacts": []}
    eng._spec = lambda _node: spec
    eng._ingest_probe_artifacts(run, node)
    sources = evalid.active_probe_snapshot_map(eng.ctx(), node, include_run=run)
    snapshot = repo / sources["probe.json"]
    check(json.loads(snapshot.read_text(encoding="utf-8"))["signal"] == 1.0,
          "producer ingestion must create a RUN-owned probe snapshot")

    run["evidence_status"] = "incomplete"
    landing.write_text(json.dumps({"signal": -1.0}), encoding="utf-8")
    eng._ingest_probe_artifacts(run, node)
    check(json.loads(snapshot.read_text(encoding="utf-8"))["signal"] == 1.0,
          "reconciliation must not overwrite an existing immutable snapshot from a reused landing path")
    metrics = {"_mechanism_probe": {
        "mode": "same_run", "signal": "hidden activation",
        "expect": "activation remains positive", "required_fields": ["signal"],
        "observations": [{"seed": None, "artifact": "probe.json",
                          "values": {"signal": 1.0}}],
    }}
    errors = evalid.probe_result_errors(
        eng.ctx(), spec, metrics, where="snapshot regression", artifact_sources=sources)
    check(not errors, "downstream validation must use the producer snapshot, not overwritten landing bytes")
    check(evalid.mechanism_probe_source_paths(metrics, sources) == [sources["probe.json"]],
          "evaluation seals must bind the immutable snapshot path")

    # A malformed, not-yet-sealed snapshot may be superseded inside the same
    # RUN; its old bytes remain explicit history.
    bad_run = {
        "id": "RUN-BAD", "node": "N020", "kind": "stage", "stage": "train",
        "replica_seed": None, "adoption_status": "candidate",
    }
    landing.write_text(json.dumps({"wrong": 0.0}), encoding="utf-8")
    eng.st["runs"].append(bad_run)
    eng._ingest_probe_artifacts(bad_run, node)
    bad_run["evidence_status"] = "invalid"
    landing.write_text(json.dumps({"signal": 2.0}), encoding="utf-8")
    eng._ingest_probe_artifacts(bad_run, node)
    repaired = repo / evalid.probe_snapshot_map(bad_run)["probe.json"]
    check(json.loads(repaired.read_text(encoding="utf-8"))["signal"] == 2.0
          and len(bad_run.get("probe_snapshot_history") or []) == 1,
          "same-RUN repair may append a corrected snapshot while preserving the rejected one")


def new_attempt_cannot_borrow_old_probe() -> None:
    repo = HERE / "out" / "v92_probe_snapshot"
    node = {"id": "N030", "stage_cursor": 0, "replica_index": 0,
            "evidence_heads": {"stage:0:0": "RUN-OLD"}}
    old = {
        "id": "RUN-OLD", "node": "N030", "kind": "stage", "stage": "train",
        "adoption_status": "adopted", "probe_artifact_snapshots": [{
            "declared_artifact": "probe.json",
            "snapshot_artifact": ".evo/runs/RUN-STAGE/evidence/probe_0_probe.json",
        }],
    }
    current = {
        "id": "RUN-NEW", "node": "N030", "kind": "stage", "stage": "train",
        "stage_index": 0, "replica_index": 0, "replica_seed": None,
        "metrics_file": None, "adoption_status": "candidate",
    }
    spec = {
        "workflow": {"stages": [{"name": "train"}]},
        "probe_execution": {"mode": "same_run", "producer_stage": "train",
                            "artifact": "probe.json", "required_fields": ["signal"]},
    }
    eng = object.__new__(esched.Engine)
    eng.store = SimpleNamespace(repo=repo)
    eng.store.event = lambda *_args, **_kwargs: None
    eng.st = {"runs": [old, current]}
    eng.cfg, eng.g, eng.reg = {}, {"nodes": [node]}, {"artifacts": []}
    eng._spec = lambda _node: spec
    seen: dict[str, dict[str, str]] = {}
    original_stage = evalid.stage_result_errors
    original_probe = evalid.stage_probe_errors
    try:
        evalid.stage_result_errors = lambda *_args, **_kwargs: []
        def capture(*_args, artifact_sources=None, **_kwargs):
            seen["sources"] = dict(artifact_sources or {})
            return []
        evalid.stage_probe_errors = capture
        eng._run_result_errors(current, node, enforce_current=True)
    finally:
        evalid.stage_result_errors = original_stage
        evalid.stage_probe_errors = original_probe
    check(seen.get("sources") == {},
          "a producer retry/late RUN must validate only its own snapshots, never an older active head")

    landing = repo / "probe.json"
    landing.write_text(json.dumps({"signal": 99.0}), encoding="utf-8")
    eng._archive_preexisting_probe_landings(current, node)
    check(not landing.exists() and bool(current.get("preexisting_probe_landings")),
          "a new producer attempt must archive stale landing bytes before launch")


def seed_filesystem_identity_checks() -> None:
    ctx = SimpleNamespace(cfg={"evidence_policy": {"training_replication": {
        "mode": "preplanned", "planned_runs": 2, "aggregation": "mean",
    }}})
    spec = {
        "experiment_class": "train", "experiment_purpose": "candidate",
        "training_replication": {"mode": "preplanned", "runs": 2,
                                 "seeds": [1, "1"], "aggregation": "mean",
                                 "source": "workflow"},
        "workflow": {"stages": [{"name": "train", "launch": "train --seed {seed}",
                                  "metrics_file": "metrics-{seed}.json"}]},
    }
    errors = evalid.training_replication_errors(ctx, spec, role="root", where="collision fixture")
    check(any("SEED_PATH_COLLISION" in err for err in errors),
          "typed-distinct seeds must not collapse to one filesystem landing identity")


def main() -> None:
    scope_and_hold_checks()
    pending_consumer_checks()
    round_projection_checks()
    stage_probe_gap_reaches_eval_checks()
    probe_landing_overwrite_cannot_rewrite_history()
    new_attempt_cannot_borrow_old_probe()
    seed_filesystem_identity_checks()
    print(f"V9.2 CONTROL PLANE UNIT GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
