"""Behavior regressions for the R9 (external audit r6) fix batch and its
repair pass.

    python tests/v113_fix_regressions.py

The r6 batch shipped with zero test coverage; its half-applied edits survived
a fully green wall. Every check here exercises a repaired behavior DIRECTLY
(the v11.1 postmortem rule: composite/validator paths must run, not just
grep): crash-ghost read filtering on all three journals, the deep_read
evidence watermark, retraction write ordering, the parked-task reopen pump,
the landing-lease scheduler probe, the harness-trials era gate, snapshot
publishing over read-only files, and retired-platform recovery closure.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))

import eabsorb    # noqa: E402
import eapply     # noqa: E402
import ebundle    # noqa: E402
import erecover   # noqa: E402
import esched     # noqa: E402
import eseal      # noqa: E402
import estore     # noqa: E402
import eutil      # noqa: E402
import evalid     # noqa: E402
from _check import check, done  # noqa: E402


# ------------------------------------------------------- crash ghosts ------

def test_error_journal_ghost_filter() -> None:
    """ER rows past the committed counter are ghosts for state-holding readers
    (LS/OB had this; ER was the missing third of the same rule)."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".evo").mkdir()
        store = estore.Store(repo)
        st: dict = {"counters": {}}
        real = store.add_error(st, {"node": "N001", "failure_class": "infrastructure",
                                    "note": "committed failure"})
        # simulate the crash window: an appended row whose id was never committed
        eutil.append_jsonl(store.errors_path, {"id": "ER999", "node": "N001",
                                               "failure_class": "infrastructure",
                                               "note": "uncommitted ghost"})
        store._errors_cache = None
        raw_ids = {r.get("id") for r in store.errors()}
        check("ER999" in raw_ids, "the raw accessor (doctor view) still SEES the ghost")
        committed_ids = {r.get("id") for r in store.errors(st)}
        check(real in committed_ids and "ER999" not in committed_ids,
              f"a state-holding reader gets only committed ER rows: {committed_ids}")
        check(all(r.get("id") != "ER999" for r in store.error_records(st)),
              "error_records(st) inherits the committed filter")
        blob = "\n".join(ebundle.errors_block(store, {}, st=st))
        check("ER999" not in blob and real in blob,
              "the bundle errors block no longer feeds ghost failures to agents")


def test_lesson_ghost_filter_on_production_path() -> None:
    """The r6 filter landed on dead code (select_lessons); the production
    bundle path fed ghosts. Both now route through store.lessons(st)."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".evo").mkdir()
        store = estore.Store(repo)
        st: dict = {"counters": {}}
        real = store.add_lesson(st, {"scope": "global", "statement": "committed lesson row",
                                     "evidence": "e", "recommendation": "r"})
        eutil.append_jsonl(store.lessons_path, {"id": "LS999", "scope": "global",
                                                "statement": "uncommitted ghost lesson",
                                                "evidence": "e", "recommendation": "r"})
        committed = {r.get("id") for r in store.lessons(st)}
        check(real in committed and "LS999" not in committed,
              f"store.lessons(st) hides the crash ghost: {committed}")
        check({r.get("id") for r in store.lessons()} >= {real, "LS999"},
              "the raw accessor still sees it (doctor duplicate-id audit)")
        picked = ebundle.select_lessons(store, {"nodes": []}, {}, parents=[], tags=[], st=st)
        check(all(r.get("id") != "LS999" for r in picked) and any(r.get("id") == real for r in picked),
              f"select_lessons delegates to the single committed filter: {[r.get('id') for r in picked]}")


# ------------------------------------------- deep_read evidence watermark --

def test_deep_read_stamps_evidence_watermark() -> None:
    """R9 made every consumer read only the accepted prefix; deep_read appends
    validated evidence rows, so its acceptance must advance the watermark or
    those rows are invisible (and citing them a validation error)."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".evo" / "evidence").mkdir(parents=True)
        rows = [{"id": "E001"}, {"id": "E002"}, {"id": "E003"}]
        lane = {"id": "L1", "search_origin": "focused"}
        stub = SimpleNamespace(
            st={},
            store=SimpleNamespace(repo=repo,
                                  evidence=lambda: rows,
                                  mech_cards=lambda: []),
            _lane_of=lambda subj: lane)
        eapply.ApplyMixin._apply_deep_read(stub, {"subject": {"lane": "L1"}})
        wm = (stub.st.get("ledger_accept") or {}).get("evidence") or {}
        check(wm.get("count") == 3, f"deep_read acceptance stamped the evidence watermark: {wm}")
        check(evalid.accepted_ledger_rows(stub.st, "evidence", rows) == rows,
              "the just-accepted E### rows are visible to accepted-prefix readers")
        check((stub.st.get("ledger_accept") or {}).get("mech", {}).get("count") == 0,
              "mech watermark still stamped alongside (R7 behavior preserved)")


# ---------------------------------------------- retraction write ordering --

def test_retraction_flushes_before_state_commit() -> None:
    """Fail-closed direction: the un-suppressing retraction lands BEFORE
    save_all; the suppressor rows land after (unchanged R7 rule)."""
    order: list[str] = []
    stub = SimpleNamespace(
        st={}, g={}, reg={},
        store=SimpleNamespace(
            save_all=lambda st, g, reg: order.append("save_all"),
            add_error_resolution=lambda rec: order.append("resolution"),
            retract_error_resolutions=lambda node, recovery, reason: order.append("retract"),
            # R11-008 stub sync: the outbox dedup reads the journal
            errors=lambda st=None: []),
        _pending_error_resolutions=[{"resolves": "ER001", "outbox_key": "k1"}],
        _pending_resolution_retractions=[{"node": "N1", "recovery": "REC1", "reason": "r"}])
    esched.Engine.save(stub)
    check(order == ["retract", "save_all", "resolution"],
          f"retractions flush before the state commit, suppressors after: {order}")
    check(not stub._pending_error_resolutions and not stub._pending_resolution_retractions,
          "both staging buffers drained")
    # R11-008: the committed state carried the row as an outbox until the
    # append landed; the NEXT save (nothing pending, journal now has the key)
    # clears it.
    check(stub.st.get("resolution_outbox") == [{"resolves": "ER001", "outbox_key": "k1"}],
          "the staged row rode inside the committed state as an outbox")
    stub.store.errors = lambda st=None: [{"kind": "resolution", "outbox_key": "k1"}]
    esched.Engine.save(stub)
    check("resolution_outbox" not in stub.st,
          "a later save proves the append landed and clears the outbox")


# ------------------------------------------------- parked-task reopen pump --

def _pump_stub(tasks: list[dict], lanes: dict[str, dict] | None = None):
    events: list[tuple] = []
    remat: list[str] = []
    stub = SimpleNamespace(
        st={"tasks": tasks},
        node=lambda nid: None,
        store=SimpleNamespace(
            get_lane=lambda st, lid: (lanes or {}).get(lid),
            event=lambda actor, kind, **kw: events.append((kind, kw.get("task")))),
        _rematerialize=lambda t: remat.append(t.get("id")))
    return stub, events, remat


def test_reopen_pump_reopens_parked_task() -> None:
    t1 = {"id": "T001", "type": "implement", "status": "paused",
          "queued_after_hold": True, "subject": {"lane": "L1"}, "held_by": []}
    stub, events, remat = _pump_stub([t1])
    esched.Engine._reopen_queued_tasks(stub)
    check(t1["status"] == "open" and "queued_after_hold" not in t1,
          f"a parked task reopens when the floor is free: {t1['status']}")
    check(("queued_task_reopened", "T001") in events, f"reopen is evented: {events}")
    check(remat == ["T001"], "the card rematerializes from current truth")


def test_reopen_pump_cancels_stale_and_reopens_one() -> None:
    stale = {"id": "T002", "type": "implement", "status": "paused",
             "queued_after_hold": True, "subject": {"lane": "L2"}, "held_by": []}
    newer_done = {"id": "T005", "type": "implement", "status": "done",
                  "subject": {"lane": "L2"}}
    parked_a = {"id": "T003", "type": "evidence", "status": "paused",
                "queued_after_hold": True, "subject": {"lane": "L3"}, "held_by": []}
    parked_b = {"id": "T004", "type": "sketch", "status": "paused",
                "queued_after_hold": True, "subject": {"lane": "L4"}, "held_by": []}
    stub, events, _ = _pump_stub([stale, newer_done, parked_a, parked_b])
    esched.Engine._reopen_queued_tasks(stub)
    check(stale["status"] == "cancelled",
          "a parked task whose subject was re-covered by a newer task is stale, not resurrected")
    check(("queued_task_cancelled", "T002") in events, f"stale cancel is evented: {events}")
    check(parked_a["status"] == "open" and parked_b["status"] == "paused",
          "exactly ONE task reopens per pump (at-most-one-open floor)")


def test_reopen_pump_cancels_terminal_subject() -> None:
    t = {"id": "T007", "type": "implement", "status": "paused",
         "queued_after_hold": True, "subject": {"lane": "L9"}, "held_by": []}
    stub, events, _ = _pump_stub([t], lanes={"L9": {"id": "L9", "status": "abandoned"}})
    esched.Engine._reopen_queued_tasks(stub)
    check(t["status"] == "cancelled", "a parked task on an abandoned lane never resurfaces")


# ----------------------------------------------------- landing-lease probe --

def test_landing_lease_probe() -> None:
    runs = [{"id": "RUN001", "status": "running", "kind": "stage",
             "declared_metrics_file": "work/m.json", "declared_ledger_file": None}]
    stub = SimpleNamespace(st={"runs": runs},
                           _run_claim_set=eabsorb.AbsorbMixin._run_claim_set,
                           # G-3 stub sync: fixture rows carry their claims inline
                           _ensure_run_claims=lambda run: None)
    probe = eabsorb.AbsorbMixin._landing_lease_holder
    holder = probe(stub, "work/m.json")
    check(holder is not None and holder["id"] == "RUN001",
          "a non-terminal RUN holds its declared landing as a lease")
    check(probe(stub, "work/other.json") is None, "an unclaimed path has no holder")
    check(probe(stub, "work/m.json", exclude_run="RUN001") is None,
          "the holder itself is excluded (idempotent re-prepare)")
    check(probe(stub, "") is None, "empty declarations never match the empty-string field")
    runs[0]["status"] = "finished"
    check(probe(stub, "work/m.json") is None, "a terminal RUN releases the lease")


# ------------------------------------------------ harness-trials era gate --

def test_harness_trials_era_gate() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".evo").mkdir()
        store = estore.Store(repo)
        (repo / "metrics.json").write_text(
            json.dumps({"_usage": {"gpu_hours": 1.0}}), encoding="utf-8")
        ctx = evalid.Ctx(store, {}, {}, {"nodes": []}, reg={})
        spec = {"eval": {"harness": {"type": "physical", "trials": 5}}}
        errs = evalid.evaluation_result_errors(ctx, spec, "metrics.json", where="t")
        check(any("EVAL_HARNESS_TRIALS" in e for e in errs),
              f"fresh production keeps the raw-side trials duty: {errs}")
        errs2 = evalid.evaluation_result_errors(ctx, spec, "metrics.json", where="t",
                                                enforce_harness_trials=False)
        check(not any("EVAL_HARNESS_TRIALS" in e for e in errs2),
              f"doctor's historical replay does not re-litigate sealed pre-R9 raw files: {errs2}")


def test_invented_usage_carveout_for_trials() -> None:
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".evo").mkdir()
        store = estore.Store(repo)
        (repo / "raw.json").write_text(
            json.dumps({"_usage": {"gpu_hours": 1.0}}), encoding="utf-8")
        st = {"runs": [{"id": "RUN001", "metrics_file": "raw.json"}]}
        ctx = evalid.Ctx(store, st, {}, {"nodes": []}, reg={})
        node = {"id": "N1", "eval_run": "RUN001"}
        ok = evalid.normalized_raw_binding_errors(
            ctx, node, {"_usage": {"gpu_hours": 1.0, "trials_completed": 3}})
        check(not any("USAGE_INVENTED" in e for e in ok),
              f"trials_completed may be supplied when the sealed raw predates the duty: {ok}")
        bad = evalid.normalized_raw_binding_errors(
            ctx, node, {"_usage": {"gpu_hours": 1.0, "made_up_unit": 9}})
        check(any("USAGE_INVENTED" in e for e in bad),
              f"every OTHER absent-from-raw usage key is still an invention: {bad}")


# ------------------------------------------- snapshot publish, read-only ---

def test_publish_snapshot_over_readonly_files() -> None:
    """copy2 preserves a read-only bit; os.replace over/from read-only files
    is a permanent PermissionError on Windows. Publishing now normalizes the
    mode (immutability lives in the digest, not the bit)."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        source = repo / "artifact.json"
        source.write_text(json.dumps({"k": "v"}), encoding="utf-8")
        digest = eseal.artifact_digest(repo, "artifact.json")
        os.chmod(source, 0o444)
        snapdir = repo / "snaps"
        snapdir.mkdir()
        snapshot = snapdir / f"{digest}.json"
        try:
            eseal._publish_snapshot(source, snapshot, digest, repo)
            check(snapshot.exists() and eseal.artifact_digest(
                repo, eutil.rel(repo, snapshot)) == digest,
                  "publishing from a read-only source succeeds and verifies")
            snapshot.write_text("{corrupt", encoding="utf-8")
            os.chmod(snapshot, 0o444)
            eseal._publish_snapshot(source, snapshot, digest, repo)
            check(eseal.artifact_digest(repo, eutil.rel(repo, snapshot)) == digest,
                  "a read-only CORRUPT snapshot is rebuilt in place, not wedged forever")
        finally:
            for p in (source, snapshot):
                if p.exists():
                    os.chmod(p, 0o644)


# ------------------------------------- retired-platform recovery closure ---

def test_retired_platform_keeps_recovery_edges() -> None:
    graph = {"nodes": [
        {"id": "P1", "role": "platform", "verdict": "enabled",
         "retire_reason": "superseded", "enabled_services": [{"name": "svc"}]},
        {"id": "P2", "role": "platform", "verdict": "failed",
         "enabled_services": [{"name": "svc2"}]},
        {"id": "C1"}, {"id": "C2"},
    ]}
    specs = {"C1": {"eval": {"requires_services": ["svc"]}},
             "C2": {"eval": {"requires_services": ["svc2"]}}}
    reached = erecover.hard_descendants(graph, {"artifacts": []}, specs, ["P1"])
    check("C1" in set(reached.get("nodes") or []),
          f"a retired-after-enabled platform keeps its historical consumers in the closure: {reached}")
    reached2 = erecover.hard_descendants(graph, {"artifacts": []}, specs, ["P2"])
    check("C2" not in set(reached2.get("nodes") or []),
          f"a never-enabled platform still creates no phantom edges: {reached2}")


def main() -> None:
    test_error_journal_ghost_filter()
    test_lesson_ghost_filter_on_production_path()
    test_deep_read_stamps_evidence_watermark()
    test_retraction_flushes_before_state_commit()
    test_reopen_pump_reopens_parked_task()
    test_reopen_pump_cancels_stale_and_reopens_one()
    test_reopen_pump_cancels_terminal_subject()
    test_landing_lease_probe()
    test_harness_trials_era_gate()
    test_invented_usage_carveout_for_trials()
    test_publish_snapshot_over_readonly_files()
    test_retired_platform_keeps_recovery_edges()
    done("V11.3 FIX REGRESSIONS")


if __name__ == "__main__":
    main()
