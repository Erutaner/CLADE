#!/usr/bin/env python3
"""Focused integration checks for v9.2 recovery semantics.

This intentionally exercises the state transitions that the old large harness
could not express.  It is not a second end-to-end fixture.
"""
from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import mock_drive as M

sys.path.insert(0, str(M.PKG / "engine"))

import egraph  # noqa: E402
import erecover  # noqa: E402
import erun  # noqa: E402
import esched  # noqa: E402


CHECKS = 0


def ok(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[check {CHECKS}] {message}")


def fresh_project() -> M.D:
    out = Path(__file__).resolve().parent / "out" / "v92_recovery_integration"
    out.mkdir(parents=True, exist_ok=True)
    repo = out / "proj"
    if repo.exists():
        M.rmtree(repo)
    M.make_repo(repo, with_git=True)
    proc = subprocess.run(
        [M.PY, str(M.PKG / "engine" / "evo.py"), "--repo", str(repo), "init",
         "--project-name", "v92-recovery-integration",
         "--goal", "exercise evidence repair and authority replay"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(proc.returncode == 0, f"CLI init failed: {proc.stderr}")
    drive = M.D(repo)
    M.run_bootstrap(drive)
    return drive


def add_probe_node(drive: M.D) -> tuple[dict, dict]:
    """Add a seal-free diagnostic node that reuses the real baseline eval contract."""
    store = drive.store()
    graph = store.load_graph()
    baseline = drive.node("N001")
    baseline_spec = M.json.loads((drive.repo / baseline["spec"]).read_text(encoding="utf-8"))
    spec = copy.deepcopy(baseline_spec)
    spec["role"] = "root"
    spec["parents"] = []
    spec["code_parent"] = None
    spec["probe_execution"] = {
        "mode": "same_run",
        "producer_stage": "evaluation",
        "artifact": ".evo/nodes/N900/eval/probe.json",
        "required_fields": ["signal"],
        "signal": "diagnostic signal",
        "expect": "signal remains positive",
    }
    spec_rel = ".evo/nodes/N900/NODE_SPEC.json"
    M.wj(drive.repo, spec_rel, spec)
    node = egraph.new_node(
        graph, "N900", title="late-probe diagnostic", role="root", parents=[],
        code_parent=None, level=4, lane=None, round_=None, idea_doc=None,
        spec=spec_rel, experiment_purpose="candidate")
    node.update({
        "status": "evaluating", "workdir": baseline.get("workdir") or ".",
        "spec_revision": 0, "implementation_revision": 0,
        "stage_cursor": 0, "replica_index": 0, "replicas_completed": [],
        "eval_done": False, "eval_resource_accounted": False,
    })
    store.save_graph(graph)
    state = store.load_state()
    state.setdefault("counters", {})["N"] = max(int(state.get("counters", {}).get("N") or 0), 900)
    store.save_state(state)
    return node, spec


def same_run_reconciliation(drive: M.D) -> None:
    node, _spec = add_probe_node(drive)
    store = drive.store()
    state = store.load_state()
    baseline_run = next(
        row for row in reversed(state["runs"])
        if row.get("node") == "N001" and row.get("kind") == "eval"
        and row.get("adoption_status") == "adopted")
    raw_metrics = str(baseline_run["metrics_file"])
    run = store.new_run(
        state, node["id"], "eval", prepared=True,
        contract_digest="integration-contract-v1",
        implementation_digest="integration-implementation-v1")
    run["resource_reservation"] = {"wallclock_minutes": 2.0}
    erun.transition_execution(run, "launch_unknown", note="integration launch card released")
    store.save_state(state)

    esched.Engine(store).update_run(run["id"], "succeeded", metrics_file=raw_metrics)
    eng = esched.Engine(store)
    before_count = len(eng.st["runs"])
    eng._absorb_finished_runs()
    eng.save()
    pending = store.get_run(store.load_state(), run["id"])
    pending_node = next(row for row in store.load_graph()["nodes"] if row["id"] == node["id"])
    ok(pending["status"] == "finished", "missing probe must not rewrite successful execution as failed")
    ok(pending["evidence_status"] == "incomplete", "missing probe must be evidence-incomplete")
    ok(pending["adoption_status"] == "candidate", "incomplete evidence must not advance authority")
    ok(not pending["resource_accounted"], "late evidence keeps the cap reserved instead of guessing usage")
    ok(pending_node["status"] == "evidence_pending", "node must wait for same-RUN evidence repair")
    ok(len(store.load_state()["runs"]) == before_count, "evidence failure must not create a replacement RUN")

    recovery = esched.Engine(store).plan_recovery(
        f"run:{run['id']}", "stage_evidence", "late same-run probe evidence must be reconciled")
    esched.Engine(store).apply_recovery(recovery["id"], recovery["plan_digest"])
    extra_hold = esched.Engine(store).create_hold(
        "project", "operator requested an additional stop while evidence is inspected")
    deferred = esched.Engine(store).reconcile_run(
        run["id"], metrics_file=raw_metrics, accept_missing_probe=True,
        note="remote training/eval succeeded; the optional probe print was irrecoverably omitted")
    ok(deferred["adoption_status"] == "candidate" and deferred["evidence_status"] == "incomplete",
       "a recovery may bypass only its own hold, never an additional operator hold")
    esched.Engine(store).release_hold(extra_hold["id"], "operator inspection completed")

    repaired = esched.Engine(store).reconcile_run(
        run["id"], metrics_file=raw_metrics, accept_missing_probe=True,
        note="remote training/eval succeeded; the optional probe print was irrecoverably omitted")
    repaired_node = next(row for row in store.load_graph()["nodes"] if row["id"] == node["id"])
    ok(repaired["status"] == "finished", "reconciliation preserves execution truth")
    ok(repaired["evidence_status"] == "complete", "explicit gap receipt closes the evidence package")
    ok(repaired["adoption_status"] == "adopted", "validated same-RUN package becomes the active head")
    ok(repaired.get("probe_gap_receipt"), "unavailable probe must have an engine-owned gap receipt")
    ok(repaired_node.get("probe_evidence_status") == "unavailable",
       "downstream analysis must see the explicit mechanism-evidence gap")
    ok(repaired_node["status"] == "workflow_done" and repaired_node["eval_done"],
       "same-RUN repair resumes after execution rather than retraining")
    ok(len(store.load_state()["runs"]) == before_count, "successful reconciliation still uses exactly one RUN")
    recovery_eng = esched.Engine(store)
    recovery_eng._next_recovery()
    recovery_eng.save()
    recovered_case = next(row for row in store.load_state()["recoveries"] if row["id"] == recovery["id"])
    ok(recovered_case["status"] == "completed", "successful same-RUN repair must terminate its recovery case")


def failure_routing_and_hold(drive: M.D) -> None:
    store = drive.store()
    eng = esched.Engine(store)
    node = eng.node("N900")
    node["status"] = "executing"
    infra = {"id": "RUN-INFRA", "stage": "train", "replica_seed": None,
             "failure_class": "infrastructure", "note": "queue preemption"}
    eng._handle_stage_failure(node, infra)
    ok(node["status"] == "stage_ready", "infrastructure failure must retry the stage, not edit code")
    ok(not node.get("fix_needed"), "infrastructure failure must not manufacture an implementation defect")
    ok((node.get("repeat_attempt") or {}).get("source_run") == "RUN-INFRA",
       "replacement spend must remain explicitly bound to the failed attempt")
    gate = eng._repeat_spend_gate(node, "stage", "train")
    ok(gate and gate["kind"] == "repeat_spend" and gate["status"] == "open",
       "a replacement external spend needs its own non-auto gate")

    task = store.new_task(eng.st, "implement", {"node": "N900"}, [".evo/test.md"])
    eng.save()
    hold = esched.Engine(store).create_hold("node:N900", "inspect the failed attempt before more mutations")
    paused = store.get_task(store.load_state(), task["id"])
    ok(paused["status"] == "paused", "node hold must pause already-open authority-changing tasks")
    esched.Engine(store).release_hold(hold["id"], "inspection complete")
    reopened = store.get_task(store.load_state(), task["id"])
    ok(reopened["status"] == "open", "releasing the only hold must restore the paused task")


def confirmed_nonlaunch_cancels_launch_cards(drive: M.D) -> None:
    store = drive.store()
    for kind, task_type, stage in (("stage", "stage_launch", "discarded-stage"),
                                   ("eval", "eval_launch", None)):
        state = store.load_state()
        run = store.new_run(
            state, "N900", kind, stage=stage, stage_index=(0 if stage else None),
            replica_index=(0 if stage else None), replica_total=(1 if stage else None),
            contract_digest=f"confirmed-nonlaunch-{kind}",
            implementation_digest="integration-implementation-v1")
        erun.transition_execution(run, "launch_unknown", note="launch card exposed")
        task = store.new_task(
            state, task_type, {"node": "N900", "run": run["id"]},
            [f".evo/test/{run['id']}-launch.json"])
        run["launch_task"] = task["id"]
        store.save_state(state)
        esched.Engine(store).confirm_run_not_launched(
            run["id"], "scheduler token search confirmed that no job exists")
        cancelled = esched.Engine(store).update_run(
            run["id"], "cancelled", note="discard the unspent intent")
        saved = store.load_state()
        saved_task = store.get_task(saved, task["id"])
        ok(saved_task["status"] == "cancelled",
           f"confirmed-unlaunched {task_type} card must be cancelled with its RUN")
        ok(cancelled["resource_charge_basis"] == "confirmed_unlaunched"
           and cancelled["resource_usage"] == {},
           f"confirmed-unlaunched {kind} intent must not invent resource spend")
        impact = erecover.operational_run_impact(saved, run_ids=[run["id"]])
        ok(not impact["external_effects"] and not impact["blocks_authority_change"],
           f"discarded unlaunched {kind} intent must not block or require compensation")


def derived_recovery_preserves_node_work(drive: M.D) -> None:
    """A view-only correction must not invalidate node-local launch/build work."""
    store = drive.store()
    before = store.load_state()
    task = next(row for row in before["tasks"]
                if row.get("type") == "implement" and
                (row.get("subject") or {}).get("node") == "N900" and
                row.get("status") == "open")
    run_count = len(before["runs"])
    case = esched.Engine(store).plan_recovery(
        "project", "frontier", "rebuild a corrupted derived frontier view")
    paused = store.get_task(store.load_state(), task["id"])
    ok(paused["status"] == "paused", "project recovery hold should temporarily brake open work")
    applied = esched.Engine(store).apply_recovery(case["id"], case["plan_digest"])
    after = store.get_task(store.load_state(), task["id"])
    ok(applied["status"] == "completed", "derived frontier recovery should finish immediately")
    ok(after["status"] == "open", "frontier recomputation must reopen, not cancel, node-local work")
    ok(len(store.load_state()["runs"]) == run_count,
       "a derived correction must not prepare a replacement external attempt")


def historical_conclusion_replay() -> None:
    # Keep this authority world deliberately unconsumed: once a round or child
    # exists, a baseline correction must use the project-fork path tested below.
    drive = fresh_project()
    store = drive.store()
    state = store.load_state()
    state["phase"] = "done"
    store.save_state(state)
    before = drive.node("N001")
    old_digest = str((before.get("conclusion_seal") or {}).get("digest") or "")
    case = esched.Engine(store).plan_recovery(
        "node:N001", "conclusion",
        "the interpretation was found to misstate an already-sealed result")
    ok(case["status"] == "planned" and case.get("plan_digest"), "recovery must be reviewable before apply")
    plan = M.json.loads((drive.repo / case["plan_path"]).read_text(encoding="utf-8"))
    ok(plan["head_preconditions"]["nodes"]["N001"]["seals"]["conclusion_seal"] == old_digest,
       "plan digest must bind the authority head being replaced")
    additional_hold = esched.Engine(store).create_hold(
        "node:N001", "independent operator inspection must finish before authority changes")
    try:
        esched.Engine(store).apply_recovery(case["id"], case["plan_digest"])
    except SystemExit as exc:
        ok("additional active hold" in str(exc),
           "recover-apply must be blocked by a second hold covering its impact")
    else:
        ok(False, "recover-apply bypassed an independent active hold")
    unchanged = drive.node("N001")
    ok(unchanged["status"] == "concluded" and
       str((unchanged.get("conclusion_seal") or {}).get("digest") or "") == old_digest,
       "a blocked apply must not mutate the active conclusion head")
    esched.Engine(store).release_hold(additional_hold["id"], "independent inspection completed")
    applied = esched.Engine(store).apply_recovery(case["id"], case["plan_digest"])
    node = drive.node("N001")
    ok(applied["status"] == "replaying" and node["status"] == "evaluated",
       "conclusion repair must reopen only interpretation")
    ok(node.get("eval_seal"), "conclusion repair must preserve the accepted evaluation")
    ok(not node.get("conclusion_seal"), "old conclusion must stop being active without deleting history")
    ok(node["result_doc"].endswith("NODE_RESULT_r2.md"), "replacement output needs a new immutable path")
    out = esched.Engine(store).compute_next()
    ok(out.get("kind") == "task" and out.get("type") == "conclude",
       "recovery must remain schedulable even after the ordinary phase is done")
    ok(out["outputs"][1].endswith("NODE_RESULT_r2.md"),
       "historical replay must write the versioned authority path")


def revision_rejection_and_abort_remain_operable() -> None:
    drive = fresh_project()
    store = drive.store()

    # Explicitly giving up on unrecoverable evidence is terminal history, not
    # an eternal request to run-reconcile.
    node, _ = add_probe_node(drive)
    state = store.load_state()
    run = store.new_run(
        state, node["id"], "eval", contract_digest="irrecoverable-evidence-v1",
        implementation_digest="integration-implementation-v1")
    erun.transition_execution(run, "finished", note="remote evaluator finished")
    erun.transition_evidence(run, "incomplete", note="core metrics never returned")
    graph = store.load_graph()
    live_node = next(row for row in graph["nodes"] if row["id"] == node["id"])
    live_node["status"] = "evidence_pending"
    live_node["evidence_pending_run"] = run["id"]
    live_node["evidence_pending_resume"] = "evaluating"
    store.save_state(state)
    store.save_graph(graph)
    case = esched.Engine(store).plan_recovery(
        f"run:{run['id']}", "stage_evidence", "the remote metrics package is irrecoverable")
    esched.Engine(store).apply_recovery(case["id"], case["plan_digest"])
    esched.Engine(store).abort_recovery(
        case["id"], "platform retention expired and no copy exists", abandon_node=True)
    disposed = store.get_run(store.load_state(), run["id"])
    ok(disposed["evidence_disposition"] == "irrecoverable_quarantined"
       and not erun.needs_reconciliation(disposed),
       "aborted evidence recovery must leave an honest terminal disposition")
    ok((drive.repo / disposed["evidence_disposition_receipt"]).is_file(),
       "terminal evidence disposition needs an engine-owned receipt")

    # A revision retires the old executable head before the builder edits it.
    # Use an unconsumed baseline authority world; the project-fork rule quite
    # correctly rejects this operation once N900 (or a round) exists.
    drive = fresh_project()
    store = drive.store()
    before = drive.node("N001")
    old_impl = str((before.get("implementation_seal") or {}).get("digest") or "")
    recovery = esched.Engine(store).plan_recovery(
        "node:N001", "implementation", "implementation authority needs correction",
        repair_scope="workflow")
    esched.Engine(store).apply_recovery(recovery["id"], recovery["plan_digest"])
    task = esched.Engine(store).compute_next()
    pending = drive.node("N001")
    ok(task.get("type") == "implement" and pending.get("implementation_revision_pending"),
       "implementation replay must persist an under-revision selector before edit access")
    ok(not pending.get("implementation_seal") and not pending.get("implementation_commit"),
       "the mutable workarea must no longer be certified by the old active selector")
    ok(any(row.get("digest") == old_impl for row in pending.get("seal_history") or []),
       "the prior implementation remains verifiable history")
    M.wt(drive.repo, task["outputs"][0], "# deliberately incomplete revision\n")
    rejected = esched.Engine(store).submit(task["task"])
    ok(rejected.get("kind") == "rejected", "invalid revision fixture must exercise retry")
    retry = esched.Engine(store).compute_next()
    ok(retry.get("task") == task["task"],
       "a rejected revision must remain schedulable instead of tripping the old seal")
    esched.Engine(store).abort_recovery(
        recovery["id"], "the replacement implementation cannot be completed", abandon_node=True)
    abandoned = drive.node("N001")
    ok(abandoned["status"] == "abandoned" and not abandoned.get("implementation_seal")
       and not abandoned.get("implementation_commit"),
       "abort must retire partial executable authority before abandoning the node")
    # falsifier: _assert_artifact_seals raising - a counted always-true row
    # after it only inflated the total
    esched.Engine(store)._assert_artifact_seals()


def abandoned_authority_is_terminal_not_required() -> None:
    """Retired baseline authority is history, never a route into new rounds."""
    drive = fresh_project()
    store = drive.store()
    graph = store.load_graph()
    baseline = next(row for row in graph["nodes"] if row.get("role") == "baseline")
    historical = copy.deepcopy(baseline["implementation_seal"])
    baseline["needs_fidelity"] = True
    baseline["fidelity_pending"] = False
    baseline["fidelity_seal"] = copy.deepcopy(historical)
    baseline["needs_metric_bridge"] = True
    baseline["metric_bridge_ready"] = True
    baseline["metric_bridge_seal"] = copy.deepcopy(historical)
    store.save_graph(graph)

    case = esched.Engine(store).plan_recovery(
        "node:N001", "conclusion", "the sealed baseline interpretation cannot be repaired")
    esched.Engine(store).apply_recovery(case["id"], case["plan_digest"])
    esched.Engine(store).abort_recovery(
        case["id"], "the replacement authority is unavailable", abandon_node=True)
    retired = drive.node("N001")
    ok(retired["status"] == "abandoned" and not retired.get("fidelity_seal")
       and not retired.get("metric_bridge_seal"),
       "abort must retire completed audit heads instead of leaving false active authority")
    esched.Engine(store)._assert_artifact_seals()
    drive.doctor_clean("after baseline recovery abandonment")
    nxt = esched.Engine(store).compute_next()
    ok(nxt.get("kind") == "done" and "baseline authority abandoned" in nxt.get("reason", ""),
       "an abandoned baseline must terminate this authority world")
    state = store.load_state()
    ok(state.get("current_round") is None and not state.get("rounds"),
       "baseline abandonment must not silently open R001")


def historical_baseline_consumption_requires_project_fork() -> None:
    drive = fresh_project()
    store = drive.store()
    state = store.load_state()
    state["phase"] = "done"
    state["round_status"] = "closed"
    state["rounds"] = [{
        "id": "R001", "closed_at": "2026-01-01T00:00:00Z", "lanes": [],
        "improved": False, "best_primary": None,
    }]
    store.save_state(state)
    case = esched.Engine(store).plan_recovery(
        "node:N001", "evaluation",
        "a closed round was generated against the old baseline evaluation")
    plan = M.json.loads((drive.repo / case["plan_path"]).read_text(encoding="utf-8"))
    classification = plan["classification"]
    ok(not classification["supported"] and classification["actions"] == ["fork_project"],
       "closed round history consumes the baseline even when it produced no child node")
    esched.Engine(store).release_hold(
        case["hold"], "review confirmed that continuation needs a fresh project authority")
    spec_case = esched.Engine(store).plan_recovery(
        "node:N001", "spec", "the consumed baseline specification itself was wrong")
    spec_plan = M.json.loads((drive.repo / spec_case["plan_path"]).read_text(encoding="utf-8"))
    ok(spec_plan["classification"]["actions"] == ["fork_project"],
       "a consumed baseline spec cannot be mislabeled as an ordinary node fork")
    esched.Engine(store).release_hold(
        spec_case["hold"], "the baseline spec correction will move to a project fork")


def unsubmitted_round_projection_is_reversible() -> None:
    drive = fresh_project()
    store = drive.store()
    opening = esched.Engine(store).compute_next()
    ok(opening.get("type") == "open_round",
       "the fixture must expose an unsubmitted opening-round projection")
    case = esched.Engine(store).plan_recovery(
        "node:N001", "conclusion",
        "correct the baseline interpretation before accepting the first portfolio")
    plan = M.json.loads((drive.repo / case["plan_path"]).read_text(encoding="utf-8"))
    ok(plan["classification"]["supported"],
       "allocating a round id alone must not turn a reversible draft into historical consumption")
    esched.Engine(store).apply_recovery(case["id"], case["plan_digest"])
    held = store.get_task(store.load_state(), opening["task"])
    ok(held.get("status") == "paused" and held.get("refresh_after_recovery") == case["id"],
       "the old open-round projection must wait to be regenerated from the replacement head")
    conclude = esched.Engine(store).compute_next()
    ok(conclude.get("type") == "conclude", "recovery must replay the baseline conclusion first")
    M.w_conclude(drive, conclude, "N001", baseline=True)
    accepted = esched.Engine(store).submit(conclude["task"])
    ok(accepted.get("kind") == "accepted", "the replacement baseline conclusion must seal")
    refreshed = esched.Engine(store).compute_next()
    reopened = store.get_task(store.load_state(), opening["task"])
    ok(refreshed.get("task") == opening["task"] and reopened.get("status") == "open"
       and not reopened.get("refresh_after_recovery"),
       "the same unsubmitted round task must reopen with a freshly materialized bundle")


def main() -> None:
    drive = fresh_project()
    same_run_reconciliation(drive)
    confirmed_nonlaunch_cancels_launch_cards(drive)
    failure_routing_and_hold(drive)
    derived_recovery_preserves_node_work(drive)
    historical_conclusion_replay()
    revision_rejection_and_abort_remain_operable()
    abandoned_authority_is_terminal_not_required()
    historical_baseline_consumption_requires_project_fork()
    unsubmitted_round_projection_is_reversible()
    print(f"V9.2 RECOVERY INTEGRATION GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
