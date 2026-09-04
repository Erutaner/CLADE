#!/usr/bin/env python3
"""End-to-end regressions for the DESIGN_V10 §7 fixes that need a live engine:

F1  bounded typed-repair loop (fix_cycles -> escalation -> reset)
F2  honest-unknown root cause is submittable
F8  malformed active hold fails closed
F14 evidence_min_new_per_round is the enforced per-round count
F19 retired node tolerates a deleted worktree; revive re-proves the closure

One coherent mini-drive on a fresh project (reusing mock_drive's canned-agent
helpers), so every check exercises the REAL scheduler/validator path.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import mock_drive as M

sys.path.insert(0, str(M.PKG / "engine"))

import erecover   # noqa: E402
import esched     # noqa: E402
import eutil      # noqa: E402

CHECKS = 0


def ok(cond, message):
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(f"[check {CHECKS}] {message}")


def fresh_project() -> M.D:
    repo = Path(__file__).resolve().parent / "out" / "v10_defect_regressions"
    if repo.exists():
        M.rmtree(repo)
    M.make_repo(repo, with_git=True)
    proc = subprocess.run(
        [M.PY, str(M.PKG / "engine" / "evo.py"), "--repo", str(repo), "init",
         "--project-name", "defect-regressions", "--goal", "pin the v10 defect fixes"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(proc.returncode == 0, f"CLI init failed: {proc.stderr}")
    # F14 needs a per-round evidence count the when-gap floor could never
    # produce. budgets are inside the frozen contract digest (R7), so the
    # discriminating value is set at CONFIGURE time - before the sign-off -
    # instead of edited into a frozen file mid-run.
    orig_cfg_main = M.w_config_main

    def cfg_with_f14_quota(d2, out2, **kw):
        r = orig_cfg_main(d2, out2, **kw)
        cfg_path = d2.repo / ".evo/config.json"
        c2 = json.loads(cfg_path.read_text(encoding="utf-8"))
        gap = int(c2["budgets"].get("evidence_refresh_min_when_gap") or 4)
        c2["budgets"]["evidence_min_new_per_round"] = gap + 3
        cfg_path.write_text(json.dumps(c2, indent=1), encoding="utf-8")
        return r

    M.w_config_main = cfg_with_f14_quota
    try:
        M.run_bootstrap(M.D(repo))
    finally:
        M.w_config_main = orig_cfg_main
    return M.D(repo)


def f8_malformed_hold_fails_closed(d: M.D):
    M.section("F8: an active covering hold without an id is corrupt control state")
    st = d.state()
    g = d.graph()
    st_copy = json.loads(json.dumps(st))
    st_copy.setdefault("holds", []).append(
        {"status": "active", "scope": {"kind": "project", "id": None}, "reason": "malformed fixture"})
    try:
        erecover.is_held(st_copy, g, node="N001")
        ok(False, "an id-less active covering hold must raise, not silently drop the brake")
    except ValueError as exc:
        ok("corrupt" in str(exc), f"typed fail-closed message expected, got: {exc}")


def f14_evidence_min_new_source(d: M.D):
    """The opening round's evidence refresh must carry the configured per-round
    count when it is positive (v9.2 always used the when-gap floor)."""
    M.section("F14: evidence_min_new_per_round is the per-round contract")
    cfg_path = d.repo / ".evo" / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    # the discriminating value was set at configure time (see _fresh_project):
    # budgets are frozen by the sign-off digest, so mid-run edits are illegal
    want = int(cfg["budgets"].get("evidence_refresh_min_when_gap") or 4) + 3
    ok(int(cfg["budgets"].get("evidence_min_new_per_round") or 0) == want,
       "fixture wires the discriminating per-round count at configure time")
    out = M.nx(d, "open_round")
    M.w_portfolio(d, out, "R001", [
        {"name": "f1-lane", "intent": "exploit", "min_level": 2, "parents": ["N001"]},
    ])
    M.sub_ok(d, out)
    out = M.nx(d, "evidence")
    task = next(t for t in d.state()["tasks"] if t["id"] == out["task"])
    ok(int(task["subject"].get("min_new") or 0) == want,
       f"evidence task min_new must equal budgets.evidence_min_new_per_round "
       f"({want}), got {task['subject'].get('min_new')}")
    # satisfy the pool-total and bottleneck-coverage duties on top of min_new
    M.w_evidence_refresh(d, n=want + 2, relevance=("B1",))
    M.sub_ok(d, out)


def f1_bounded_repair_loop(d: M.D) -> str:
    """implement -> smoke-fail cycles must exhaust into an escalation gate."""
    M.section("F1: typed implementation-repair loop is bounded")
    lid, mech = M.drive_lane_to_plan(d, "f1-lane", dims=M.L2_DIMS,
                                     mech_papers=("E001", "E005"))
    M.drive_mature_redteam(d, lid, mech_ids=mech, score=0.712)
    nid = M.drive_plan(d, lid, role="variant", code_parent="N001", stages=[
        M.stage("train", uri="oss://bkt/user/f1-train/checkpoint.zip", key="train|f1")])
    out = M.nx(d, "implement")
    M.do_implement(d, out, nid, break_flag=True)
    M.sub_ok(d, out)
    maxa = int(json.loads((d.repo / ".evo" / "config.json").read_text(encoding="utf-8"))
               ["budgets"].get("max_attempts", 3))
    node_dirty_fix = 0
    for cycle in range(1, maxa):
        out = M.nx(d, "smoke")
        res = d.smoke(nid)
        ok(res["status"] == "fail", f"cycle {cycle}: broken flag must fail smoke")
        r = d.submit(out["task"])
        ok(r["kind"] == "rejected" and r.get("status") == "cancelled" and r.get("repair"),
           f"cycle {cycle}: typed repair reroutes to building, flagged as repair (got {r})")
        ok(int(d.node(nid).get("fix_cycles") or 0) == cycle,
           f"fix_cycles must count typed repairs (cycle {cycle})")
        out = M.nx(d, "implement")
        M.do_fix_implement(d, out, nid)
        # keep the defect alive: re-break the flag INSIDE the reviewed commit
        wd = d.repo / d.node(nid)["workdir"]
        M.wt(d.repo, f"{d.node(nid)['workdir']}/flag.txt", "bad")
        M.sh(wd, "git", "add", "flag.txt")
        M.sh(wd, "git", "commit", "-q", "-m", f"still broken fixture cycle {cycle}")
        M.sub_ok(d, out)
        node_dirty_fix = cycle
    out = M.nx(d, "smoke")
    res = d.smoke(nid)
    ok(res["status"] == "fail", "final cycle: still failing")
    r = d.submit(out["task"])
    ok(r["kind"] == "rejected" and r.get("escalation"),
       f"exhausted typed repairs must raise an escalation gate, got {r}")
    ok(int(d.node(nid).get("fix_cycles") or 0) == maxa,
       "fix_cycles reached the max_attempts bound")
    gate = next(g for g in d.state()["gates"]
                if g["id"] == r["escalation"] and g["status"] == "open")
    ok((gate.get("subject") or {}).get("node") == nid,
       "the escalation gate names the exhausted node")
    d.decide(gate["id"], True, note="reviewed; retry with a reset repair budget")
    ok(int(d.node(nid).get("fix_cycles") or 0) == 0,
       "escalation approval resets the repair budget")
    # R7: approval RESTORES the fix intent - the node goes straight back to
    # implementation with the recorded errors as the fix brief. (The old flow
    # re-ran the same deterministic smoke failure once just to re-arm the fix
    # pass, and under max_attempts<=1 that approve->fail->gate loop never
    # terminated.)
    ok(d.node(nid).get("fix_needed") and d.node(nid).get("status") == "building",
       "approval restores the repair intent, not just the counters")
    out = M.nx(d, "implement")
    M.do_fix_implement(d, out, nid)
    # keep the defect alive once more: a NEW typed failure must count from
    # the fresh budget
    wd = d.repo / d.node(nid)["workdir"]
    M.wt(d.repo, f"{d.node(nid)['workdir']}/flag.txt", "bad")
    M.sh(wd, "git", "add", "flag.txt")
    M.sh(wd, "git", "commit", "-q", "-m", "still broken after reset")
    M.sub_ok(d, out)
    out = M.nx(d, "smoke")
    res = d.smoke(nid)
    ok(res["status"] == "fail", "the defect is still present after the reset")
    r = d.submit(out["task"])
    ok(r["kind"] == "rejected" and r.get("repair") and
       int(d.node(nid).get("fix_cycles") or 0) == 1,
       f"post-reset typed repair counts from a fresh budget, got {r}")
    out = M.nx(d, "implement")
    M.do_fix_implement(d, out, nid)
    M.sub_ok(d, out)
    out = M.nx(d, "smoke")
    res = d.smoke(nid)
    ok(res["status"] == "pass", "a real fix passes smoke after the reset")
    M.sub_ok(d, out)
    M.maybe_fidelity(d, nid)
    ok(node_dirty_fix == maxa - 1, "fixture drove exactly max_attempts-1 dirty fixes")
    return nid


def f2_unknown_root_cause(d: M.D, nid: str):
    """A regressed node may honestly blame no registered assumption."""
    M.section("F2: root_cause note='unknown' is a legal terminal answer")
    out = M.nx(d, "stage_launch")
    stg = d.state()["tasks"][-1]["subject"]["stage"]
    M.w_launch(d, out, stg, job="job-f2")
    M.sub_ok(d, out)
    run_id = M.last_run(d)["id"]
    M.drive_watch_finish(d, run_id, nid, "train")
    out = M.nx(d, "evaluate")
    M.w_eval(d, out, nid, 0.601)   # far below the N001 baseline -> regressed
    M.sub_ok(d, out)
    out = M.nx(d, "conclude")

    def with_root_cause(note):
        M.w_conclude(d, out, nid, root_cause=False)
        outcome_path = d.repo / out["outputs"][0]
        outcome = json.loads(outcome_path.read_text(encoding="utf-8"))
        outcome["root_cause"] = {"assumptions": [], "note": note}
        eutil.write_json_atomic(outcome_path, outcome)

    with_root_cause("x" * 20)
    r = d.submit(out["task"])
    ok(r["kind"] == "rejected" and any("OUTCOME_ROOT_CAUSE" in e for e in r["errors"]),
       f"a short non-unknown note must still be rejected: {r.get('errors', [])[:3]}")
    with_root_cause("unknown")
    r = d.submit(out["task"])
    ok(r["kind"] == "accepted",
       f"the literal honest-unknown must be submittable (F2), got {r}")
    ok(d.node(nid)["verdict"] == "regressed", "the node concluded regressed")


def f19_retired_workdir_and_revive(d: M.D, nid: str):
    """Pruning tolerates a deleted worktree; revive re-proves the closure."""
    M.section("F19: retired nodes relax to snapshot-only; revive re-proves")
    M.drive_close(d, "R001", retire=[{"node": nid, "reason": "pruned",
                                      "note": "l" * 70}])
    node = d.node(nid)
    ok(node.get("retire_reason") == "pruned", "fixture node is pruned")
    wd = d.repo / node["workdir"]
    M.sh(d.repo, "git", "worktree", "remove", "--force", str(wd))
    ok(not wd.exists(), "the pruned worktree is gone")
    # The old membership assertion here ({task,gate,waiting,done}) admitted
    # EVERY possible compute_next return - the only falsifier was an exception,
    # which fails the suite anyway. The regression F19 guards is a stall, so
    # assert PROGRESS: the sweep must surface actionable work, and a second
    # sweep must be deterministic about it.
    out = d.next()
    ok(out.get("kind") in ("task", "gate"),
       f"a sweep with a deleted retired worktree must still surface actionable work "
       f"(got {out})")
    again = d.next()
    ok(again.get("kind") == out.get("kind")
       and again.get("task", again.get("gate")) == out.get("task", out.get("gate")),
       f"the sweep is deterministic, not a churn loop: {out} vs {again}")
    d.doctor_clean("after deleting a pruned node's worktree")
    proc = subprocess.run(
        [M.PY, str(M.PKG / "engine" / "evo.py"), "--repo", str(d.repo), "revive",
         "--node", nid, "--note", "attempt revival without restoring the worktree"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(proc.returncode != 0 and "cannot revive" in (proc.stdout + proc.stderr),
       f"revive must refuse while the executable closure is unverifiable: "
       f"rc={proc.returncode} out={proc.stdout[-200:]} err={proc.stderr[-200:]}")
    ok(d.node(nid).get("retire_reason") == "pruned",
       "a refused revival leaves the node retired")


def f21_worktree_gitdir_pointer_excluded():
    """v10.1 walker regression: a linked-worktree `.git` FILE (gitdir pointer)
    and any file named like a prune dir must stay out of the execution
    closure - its bytes are git-owned and legally change on worktree repair."""
    import tempfile
    sys.path.insert(0, str(M.PKG / "engine"))
    import evalid
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "src").mkdir()
        (root / "src" / "model.py").write_text("x = 1", encoding="utf-8")
        (root / ".git").write_text("gitdir: C:/main/.git/worktrees/wt", encoding="utf-8")
        (root / ".evo").mkdir()
        (root / ".evo" / "state.json").write_text("{}", encoding="utf-8")
        (root / "cache.pyc").write_bytes(b"\x00")
        rels = [rel for _p, rel in evalid._workarea_files(root, [])]
        ok(rels == ["src/model.py"],
           f"F21: worktree .git pointer / .evo / .pyc excluded from closure walk: {rels}")
        # nested node workarea: the whole subtree belongs to the other node
        (root / "workareas" / "n2").mkdir(parents=True)
        (root / "workareas" / "n2" / "train.py").write_text("y = 2", encoding="utf-8")
        nested = [(root / "workareas" / "n2").resolve()]
        rels = [rel for _p, rel in evalid._workarea_files(root, nested)]
        ok(rels == ["src/model.py"],
           f"F21: nested node workarea pruned from the closure walk: {rels}")


def d1_task_abandonment_has_real_semantics():
    """v10.2a livelock: 'abandoning' a task whose subject is a round (or
    nothing) was a silent no-op, so the scheduler recreated an identical task
    with attempts=0 - under full_auto + on_stuck=abandon the escalation gate
    auto-rejected and the loop ran forever with unbounded task/gate growth."""
    M.section("D1: abandoning a subjectless task must change the world")

    def engine_with_task(task, *, lanes=(), phase="rounds"):
        events = []
        eng = object.__new__(esched.Engine)
        eng.st = {"tasks": [task], "lanes": list(lanes), "rounds": [],
                  "gates": [], "phase": phase, "round_status": "running"}
        eng.g = {"nodes": []}
        eng.store = type("S", (), {
            "event": staticmethod(lambda actor, ev, **d_: events.append((actor, ev, d_))),
            "get_lane": staticmethod(lambda st, lid: next(
                (l for l in st["lanes"] if l["id"] == lid), None)),
        })()
        eng.cfg = {"budgets": {}, "metrics": {"primary": "auc"}}
        return eng, events

    close = {"id": "T1", "type": "close_round", "status": "cancelled",
             "subject": {"round": "R003"}}
    lane = {"id": "L001", "round": "R003", "status": "mature"}
    eng, events = engine_with_task(close, lanes=[lane])
    eng._abandon_task_subject(close, "attempts exhausted")
    ok(eng.st["round_status"] == "running" and not eng.st["rounds"]
       and any(ev == "close_round_task_cancelled" for _a, ev, _d in events),
       f"R8: with an ACTIVE lane the force-close is refused - the doomed close is "
       f"cancelled (scheduler re-mints it once the lanes finish): {events}")
    done_lane = {"id": "L001", "round": "R003", "status": "done"}
    close2 = {"id": "T2", "type": "close_round", "status": "cancelled",
              "subject": {"round": "R003"}}
    eng, events = engine_with_task(close2, lanes=[done_lane])
    eng._abandon_task_subject(close2, "attempts exhausted")
    ok(eng.st["round_status"] == "closed"
       and eng.st["rounds"] and eng.st["rounds"][-1]["id"] == "R003"
       and eng.st["rounds"][-1]["lanes"] == ["L001"],
       f"with lanes finished, abandoning close_round force-closes with lanes on record: "
       f"{eng.st['rounds']}")
    ok(any(ev == "round_force_closed" for _a, ev, _d in events),
       f"the force-close is on the event ledger: {events}")

    for duty in ("evidence", "sota_scan"):
        task = {"id": "T2", "type": duty, "status": "cancelled",
                "subject": {"round": "R003"}}
        eng, events = engine_with_task(task)
        eng._abandon_task_subject(task, "attempts exhausted")
        ok(any(ev == "round_duty_waived" for _a, ev, _d in events),
           f"abandoning {duty} records a waiver: {events}")
        ok(eng._task_settled(duty, round="R003"),
           f"the cancelled {duty} suppresses recreation for THIS round")
        ok(not eng._task_settled(duty, round="R004"),
           f"the waiver is round-scoped; the next round re-triggers {duty}")

    boot = {"id": "T3", "type": "profile", "status": "cancelled", "subject": {}}
    eng, events = engine_with_task(boot, phase="bootstrap")
    eng._abandon_task_subject(boot, "attempts exhausted")
    ok(eng.st["phase"] == "done" and eng.st.get("bootstrap_terminated"),
       "abandoning a bootstrap step stops the evolution instead of recreating forever")
    ok(any(ev == "evolution_stopped" for _a, ev, _d in events),
       f"the stop reason is on record: {events}")

    drill = {"id": "T4", "type": "infra_drill", "status": "cancelled", "subject": {}}
    eng, events = engine_with_task(drill, phase="bootstrap")
    eng._abandon_task_subject(drill, "attempts exhausted")
    ok(eng.st["phase"] == "bootstrap"
       and not any(ev == "evolution_stopped" for _a, ev, _d in events),
       "infra_drill keeps its caller's dedicated documented stop - no double report")


def main():
    d = fresh_project()
    f21_worktree_gitdir_pointer_excluded()
    d1_task_abandonment_has_real_semantics()
    f8_malformed_hold_fails_closed(d)
    f14_evidence_min_new_source(d)
    nid = f1_bounded_repair_loop(d)
    f2_unknown_root_cause(d, nid)
    f19_retired_workdir_and_revive(d, nid)
    d.doctor_clean("end of defect regressions")
    print(f"V10 DEFECT REGRESSIONS GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
