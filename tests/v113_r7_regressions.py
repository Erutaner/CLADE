"""R7-batch fix regressions (v11.3).

Covers the load-bearing mechanics of the R7 audit fixes that are unit-testable
without a full engine drive:
  - generation commit: torn save_all rolls BACK, committed generation rolls
    FORWARD, normal/state-only saves leave no debris (R7-006/007/014/017/018/
    019/022/024 root fix)
  - norm_uri canonicalization + landing-lease equivalence (R7-016)
  - v_close_round refuses an already-closed round (R7-020)
  - _archive_repeat_measure clears settled repeats on restart (R7-012)
  - _ingest_run_landings re-reads a snapshotted field ONLY when explicitly
    resupplied (R7-010)
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from _check import check, done  # noqa: E402

import estore  # noqa: E402
import eutil  # noqa: E402
import eabsorb  # noqa: E402
import evalid  # noqa: E402


def _mk_repo() -> Path:
    root = Path(tempfile.mkdtemp(prefix="r7fix_"))
    (root / ".evo").mkdir(parents=True)
    (root / ".evo" / "state.json").write_text(
        json.dumps({"evo_version": "10", "state_revision": 5}), encoding="utf-8")
    (root / ".evo" / "graph.json").write_text(
        json.dumps({"version": "10", "nodes": [{"id": "N001", "status": "concluded"}]}),
        encoding="utf-8")
    (root / ".evo" / "artifacts.json").write_text(
        json.dumps({"version": "10", "artifacts": []}), encoding="utf-8")
    return root


def generation_commit_windows() -> None:
    root = _mk_repo()
    try:
        store = estore.Store(root)
        st, g, reg = store.load_state(), store.load_graph(), store.load_artifacts()
        g["nodes"][0]["status"] = "evaluated"
        orig = eutil.write_json_atomic

        def crash_before_state(path, data):
            if path.name == "state.json" and (root / ".evo") in path.parents:
                raise RuntimeError("crash before state commit")
            return orig(path, data)

        eutil.write_json_atomic = crash_before_state
        try:
            store.save_all(st, g, reg)
            check(False, "save_all must crash in this probe")
        except RuntimeError:
            pass
        finally:
            eutil.write_json_atomic = orig
        check((root / ".evo" / "commit_pending.json").exists(),
              "torn commit leaves the pending marker")
        s2 = estore.Store(root)
        check(s2.load_graph()["nodes"][0]["status"] == "concluded",
              "pre-state crash rolls the graph BACK to the consistent generation")
        check(s2.load_state()["state_revision"] == 5, "state revision untouched by rollback")
        check(not (root / ".evo" / "commit_pending.json").exists(), "marker cleared after recovery")
        check(not (root / ".evo" / "graph.json.bak").exists(), "pre-image cleared after recovery")

        st2, g2 = s2.load_state(), s2.load_graph()
        g2["nodes"][0]["status"] = "evaluated"

        def crash_after_state(path, data):
            r = orig(path, data)
            if path.name == "state.json" and (root / ".evo") in path.parents:
                raise RuntimeError("crash after state commit")
            return r

        eutil.write_json_atomic = crash_after_state
        try:
            s2.save_all(st2, g2, reg)
        except RuntimeError:
            pass
        finally:
            eutil.write_json_atomic = orig
        s3 = estore.Store(root)
        check(s3.load_graph()["nodes"][0]["status"] == "evaluated",
              "post-state crash keeps the committed generation (roll forward)")
        check(s3.load_state()["state_revision"] == 6, "committed revision survives")
        check(not (root / ".evo" / "commit_pending.json").exists(), "marker cleared on roll forward")

        st3, g3 = s3.load_state(), s3.load_graph()
        st3["phase"] = "x"
        s3.save_all(st3, g3, reg)
        check(not (root / ".evo" / "commit_pending.json").exists(), "normal save leaves no marker")
        check(not (root / ".evo" / "graph.json.bak").exists(), "normal save leaves no pre-image")
        check(estore.Store(root).load_state()["state_revision"] == 7, "normal save commits")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def generation_commit_concurrent_marker() -> None:
    """A long-lived Store (constructed before a sibling crashed mid-commit)
    must resolve the orphan marker INSIDE its own save - otherwise a
    state-only save lands exactly on the marker's target revision and
    certifies the torn generation while deleting its rollback pre-images."""
    root = _mk_repo()
    try:
        long_lived = estore.Store(root)          # constructed while disk is clean
        st = long_lived.load_state()             # revision 5
        # sibling process crashes mid-commit: graph replaced, state not
        shutil.copy2(root / ".evo" / "graph.json", root / ".evo" / "graph.json.bak")
        (root / ".evo" / "graph.json").write_text(
            json.dumps({"version": "10", "nodes": [{"id": "N001", "status": "evaluated"}]}),
            encoding="utf-8")
        (root / ".evo" / "commit_pending.json").write_text(
            json.dumps({"target_revision": 6,
                        "restore": [{"name": "graph.json", "had_bak": True}]}),
            encoding="utf-8")
        long_lived.save_state(st)                # state-only save -> revision 6
        check(not (root / ".evo" / "commit_pending.json").exists(),
              "the save resolves the orphan marker before committing")
        s2 = estore.Store(root)
        check(s2.load_graph()["nodes"][0]["status"] == "concluded",
              "the sibling's torn graph was rolled back, not certified")
        check(s2.load_state()["state_revision"] == 6,
              "the state-only save itself still committed")
        check(not (root / ".evo" / "graph.json.bak").exists(),
              "rollback consumed the pre-image")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def norm_uri_rules() -> None:
    check(eutil.norm_uri("results/train/./metrics.json") == "results/train/metrics.json",
          "dot segment collapses")
    check(eutil.norm_uri("results//train/metrics.json") == "results/train/metrics.json",
          "double slash collapses")
    check(eutil.norm_uri("results\\train\\metrics.json") == "results/train/metrics.json",
          "backslashes normalize")
    check(eutil.norm_uri("s3://bucket/./x") == "s3://bucket/./x", "scheme URIs stay verbatim")
    check(eutil.norm_uri("") == "", "empty stays empty")
    # R10-002 semantics change: case handling follows the HOST FILESYSTEM
    # (probed, not inferred from the OS family) - on a case-insensitive
    # volume `A/b.json` and `a/b.json` are one physical landing and must
    # compare equal; on case-sensitive hosts they stay distinct.
    if eutil.case_insensitive_host():
        check(eutil.norm_uri("A/b.json") == eutil.norm_uri("a/b.json"),
              "case folds on a case-insensitive host (one physical landing)")
    else:
        check(eutil.norm_uri("A/b.json") != eutil.norm_uri("a/b.json"),
              "case is preserved on case-sensitive hosts (distinct files)")


def lease_holder_normalized() -> None:
    stub = SimpleNamespace(st={"runs": [
        {"id": "RUN001", "status": "running",
         "declared_metrics_file": "results/train/metrics.json",
         "declared_ledger_file": ""},
    ]}, _run_claim_set=eabsorb.AbsorbMixin._run_claim_set,
                       # G-3 stub sync: fixture rows carry their claims inline
                       _ensure_run_claims=lambda run: None)
    holder = eabsorb.AbsorbMixin._landing_lease_holder(
        stub, "results/train/./metrics.json")
    check(holder is not None and holder["id"] == "RUN001",
          "equivalent spelling hits the lease")
    holder2 = eabsorb.AbsorbMixin._landing_lease_holder(
        stub, "results/train/metrics2.json")
    check(holder2 is None, "distinct landing does not hit the lease")
    check(eabsorb.AbsorbMixin._landing_lease_holder(stub, "") is None,
          "empty declaration never matches")


def close_round_idempotent() -> None:
    ctx = SimpleNamespace(st={"rounds": [{"id": "R002", "closed_at": "t"}],
                              "lanes": []})
    errs = evalid.v_close_round(ctx, {"subject": {"round": "R002"}, "outputs": []})
    check(len(errs) == 1 and errs[0].startswith("ROUND_ALREADY_CLOSED"),
          "closing a closed round is refused up front")


def repeat_measure_archived() -> None:
    node = {"id": "N9", "repeat_measure": {"gate": "G1"}, "repeat_measure_done": True}
    old_gate = {"id": "G1", "kind": "repeat_measure", "status": "approved",
                "subject": {"node": "N9"}}
    stub = SimpleNamespace(st={"gates": [old_gate]})
    eabsorb.AbsorbMixin._archive_repeat_measure(stub, node, "implementation revision changed")
    check("repeat_measure" not in node and "repeat_measure_done" not in node,
          "restart clears the settled repeat")
    hist = node.get("repeat_measure_history") or []
    check(len(hist) == 1 and hist[0]["done"] is True
          and hist[0]["superseded_reason"] == "implementation revision changed",
          "the old repeat is archived, not erased")
    check(old_gate.get("superseded_by_restart") == "implementation revision changed",
          "the old DECIDED gate is stamped so it stops deduplicating a fresh judgement")
    node2 = {"id": "N10"}
    eabsorb.AbsorbMixin._archive_repeat_measure(SimpleNamespace(st={"gates": []}), node2, "x")
    check("repeat_measure_history" not in node2, "no-op without a settled repeat")


def ingest_field_level_refresh() -> None:
    root = Path(tempfile.mkdtemp(prefix="r7ing_"))
    try:
        prefix = ".evo/runs/RUN001/evidence/"
        (root / prefix).mkdir(parents=True)
        snap = root / prefix / "metrics_file_metrics.json"
        snap.write_text('{"v": 1}', encoding="utf-8")
        producer = root / "landing" / "metrics.json"
        producer.parent.mkdir(parents=True)
        producer.write_text('{"v": 2}', encoding="utf-8")
        run = {"id": "RUN001", "evidence_status": "incomplete",
               "metrics_file": prefix + "metrics_file_metrics.json",
               "producer_metrics_file": "landing/metrics.json",
               "ledger_file": ""}
        stub = SimpleNamespace(store=SimpleNamespace(repo=root))
        eabsorb.AbsorbMixin._ingest_run_landings(stub, run)
        check(run["metrics_file"] == prefix + "metrics_file_metrics.json"
              and not run.get("metrics_file_snapshot_revision"),
              "without an explicit resupply the snapshot is NOT re-read (R7-010)")
        run["evidence_refresh_fields"] = ["metrics_file"]
        eabsorb.AbsorbMixin._ingest_run_landings(stub, run)
        check(int(run.get("metrics_file_snapshot_revision") or 0) == 2,
              "an explicit resupply creates snapshot revision 2")
        new_rel = run["metrics_file"]
        check(new_rel != prefix + "metrics_file_metrics.json"
              and (root / new_rel).read_text(encoding="utf-8") == '{"v": 2}',
              "revision 2 carries the resupplied bytes")
        check("evidence_refresh_fields" not in run, "the refresh marker is consumed")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    generation_commit_windows()
    generation_commit_concurrent_marker()
    norm_uri_rules()
    lease_holder_normalized()
    close_round_idempotent()
    repeat_measure_archived()
    ingest_field_level_refresh()
    done("V11.3 R7 FIX REGRESSIONS")


if __name__ == "__main__":
    main()
