"""R8-batch fix regressions (v11.3).

Unit-level pins for the r8 audit fixes (the drive suites exercise the full
paths; these pin the load-bearing mechanics):
  - R8-01 sota acceptance stamps the ledger watermark (branch un-shadowed)
  - R8-02 landing lease covers the material lifecycle (finished+incomplete)
  - R8-05 adoption deferral persists past the hold and clears on reconcile
  - R8-06 revive verifies local bytes before promising availability
  - R8-08 stage settlement requires declared local products to exist
  - R8-13 _create_task reuses a parked same-duty task (attempts preserved)
  - R8-14 retirement floor suggests only revivable verdicts
  - N003  gitignore classification API + advisory demotion inputs
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from _check import check, done  # noqa: E402

import eabsorb  # noqa: E402
import eapply  # noqa: E402
import eartifact  # noqa: E402
import egraph  # noqa: E402
import etask  # noqa: E402
import evalid  # noqa: E402
import evcs  # noqa: E402


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="r8fix_"))


def sota_acceptance_stamps_watermark() -> None:
    root = _tmp()
    try:
        (root / ".evo" / "evidence").mkdir(parents=True)
        (root / ".evo" / "evidence" / "SOTA.jsonl").write_text(
            json.dumps({"id": "S001"}) + "\n", encoding="utf-8")
        stub = SimpleNamespace(
            st={"bootstrap_done": []},
            store=SimpleNamespace(repo=root, event=lambda *a, **k: None))
        eapply.ApplyMixin._transition(stub, {"type": "sota_scan", "subject": {}, "outputs": []})
        wm = (stub.st.get("ledger_accept") or {}).get("sota") or {}
        check(wm.get("count") == 1 and bool(wm.get("digest")),
              "sota acceptance stamps the accepted-ledger watermark (R8-01)")
        check("sota_scan" in stub.st["bootstrap_done"],
              "the dedicated branch keeps the bootstrap bookkeeping")
        check(evalid.stamped_ledger_watermark(stub.st, "sota")[0] == 1,
              "stamped_ledger_watermark reads the stamp back")
        check(evalid.stamped_ledger_watermark({}, "sota") == (0, ""),
              "no stamp -> nothing frozen (legacy states may repair the whole table)")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def lease_covers_material_lifecycle() -> None:
    stub = SimpleNamespace(st={"runs": [
        {"id": "RUN001", "status": "finished", "evidence_status": "incomplete",
         "declared_metrics_file": "shared/metrics.json", "declared_ledger_file": ""},
    ]}, _run_claim_set=eabsorb.AbsorbMixin._run_claim_set,
                       # G-3 stub sync: fixture rows carry their claims inline
                       _ensure_run_claims=lambda run: None)
    holder = eabsorb.AbsorbMixin._landing_lease_holder(stub, "shared/metrics.json")
    check(holder is not None and holder["id"] == "RUN001",
          "a finished RUN still awaiting evidence keeps its landing lease (R8-02)")
    stub.st["runs"][0]["evidence_status"] = "complete"
    stub.st["runs"][0]["resource_accounted"] = True
    check(eabsorb.AbsorbMixin._landing_lease_holder(stub, "shared/metrics.json") is None,
          "a settled RUN releases the landing")


def adoption_deferral_persists() -> None:
    st = {"runs": [], "holds": [
        {"id": "H001", "status": "active", "scope": {"kind": "node", "id": "N1"},
         "members": {"nodes": ["N1"], "lanes": [], "runs": []}}],
        "recoveries": []}
    g = {"nodes": [{"id": "N1", "status": "executing"}]}
    run = {"id": "RUN001", "node": "N1", "status": "finished", "evidence_status": "pending"}
    stub = SimpleNamespace(st=st, g=g,
                           _authorized_recovery_hold_for_run=lambda r: None)
    blocked = eabsorb.AbsorbMixin._run_adoption_blocked(stub, run)
    check(blocked and run.get("adoption_deferred_by_hold") == ["H001"],
          "an active hold defers adoption AND persists the obligation (R8-05)")
    st["holds"][0]["status"] = "released"
    check(eabsorb.AbsorbMixin._run_adoption_blocked(stub, run),
          "the deferral outlives the hold: absorption stays blocked after release")
    run.pop("adoption_deferred_by_hold", None)
    check(not eabsorb.AbsorbMixin._run_adoption_blocked(stub, run),
          "clearing the marker (run-reconcile's job) re-enables adoption")
    failed = {"id": "RUN002", "node": "N1", "status": "failed", "evidence_status": "pending"}
    st["holds"][0]["status"] = "active"
    check(eabsorb.AbsorbMixin._run_adoption_blocked(stub, failed)
          and not failed.get("adoption_deferred_by_hold"),
          "failed runs defer while held but carry no adoption obligation")


def revive_verifies_bytes() -> None:
    root = _tmp()
    try:
        store = SimpleNamespace(repo=root, event=lambda *a, **k: None)
        good = root / "artifacts" / "good.bin"
        good.parent.mkdir(parents=True)
        good.write_bytes(b"payload")
        good_digest = eartifact.content_custody(store, "artifacts/good.bin")[0]
        reg = {"artifacts": [
            {"id": "AR001", "node": "N1", "status": "stale", "stale_reason": "producer pruned",
             "uri": "artifacts/good.bin", "content_digest": good_digest, "history": []},
            {"id": "AR002", "node": "N1", "status": "stale", "stale_reason": "producer pruned",
             "uri": "artifacts/missing.bin", "content_digest": "deadbeef", "history": []},
        ]}
        revived, skipped = eartifact.revive_for_node(store, reg, "N1")
        check(revived == 1 and reg["artifacts"][0]["status"] == "available",
              "matching local bytes revive (R8-06)")
        check(len(skipped) == 1 and skipped[0]["id"] == "AR002"
              and reg["artifacts"][1]["status"] == "stale",
              "missing bytes stay stale and are reported, not promised")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def stage_settlement_requires_products() -> None:
    root = _tmp()
    try:
        metrics = root / "m.json"
        metrics.write_text(json.dumps(
            {"summary": {"loss": 1.0}, "usage": {"wallclock_minutes": 1}}), encoding="utf-8")
        ctx = SimpleNamespace(store=SimpleNamespace(repo=root), cfg={})
        stage = {"name": "train", "budget": {"wallclock_minutes": 5},
                 "produces": [{"name": "ckpt", "kind": "weights", "uri": "out/model.bin"}]}
        errs = evalid.stage_result_errors(ctx, stage, "m.json", None, where="t")
        check(any(str(e).startswith("STAGE_PRODUCT_MISSING") for e in errs),
              "a completed stage without its declared product is refused (R8-08)")
        (root / "out").mkdir()
        (root / "out" / "model.bin").write_bytes(b"w")
        errs2 = evalid.stage_result_errors(ctx, stage, "m.json", None, where="t")
        check(not any(str(e).startswith("STAGE_PRODUCT_MISSING") for e in errs2),
              "an existing product satisfies the check")
        remote = {"name": "ckpt", "kind": "weights", "uri": "s3://bucket/model.bin"}
        errs3 = evalid.stage_result_errors(
            ctx, {"name": "train", "produces": [remote]}, "m.json", None, where="t")
        check(not any(str(e).startswith("STAGE_PRODUCT_MISSING") for e in errs3),
              "remote scheme URIs keep their producer-receipt protocol")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def create_task_reuses_parked_duty() -> None:
    parked = {"id": "T007", "type": "implement", "status": "paused",
              "queued_after_hold": True, "held_by": [],
              "subject": {"node": "N1"}, "attempts": 2,
              "last_errors": ["IMPL_X: fix exactly this"], "outputs": ["old.md"]}
    events = []
    stub = SimpleNamespace(
        st={"tasks": [parked]},
        store=SimpleNamespace(event=lambda actor, ev, **k: events.append(ev),
                              new_task=lambda *a, **k: (_ for _ in ()).throw(
                                  AssertionError("must reuse, not mint"))),
        _materialize=lambda task, **k: None)
    out = etask.TaskMixin._create_task(stub, "implement", {"node": "N1"}, ["new.md"])
    check(out is parked and out["status"] == "open" and out["attempts"] == 2
          and out["last_errors"] == ["IMPL_X: fix exactly this"]
          and out["outputs"] == ["new.md"] and "queued_after_hold" not in out,
          "a parked same-duty task is reopened with its history (R8-13)")
    check("queued_task_reopened" in events, "the reuse is on the event record")


def retirement_floor_suggests_only_revivable() -> None:
    cfg = {"project": {"mode": "engineering"}}
    g = {"nodes": [
        {"id": "N1", "status": "concluded", "verdict": "screened_out", "retire_reason": "pruned"},
        {"id": "N2", "status": "concluded", "verdict": "validated", "retire_reason": "pruned"},
    ]}
    ids = egraph.retired_settled_ids(g, cfg)
    check(ids == ["N2"],
          "screened_out is never suggested for revival (R8-14); deliverable verdicts are")


def gitignore_classification() -> None:
    root = _tmp()
    try:
        subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
        (root / ".gitignore").write_text("runtime.json\n", encoding="utf-8")
        (root / "runtime.json").write_text("{}", encoding="utf-8")
        (root / "kept.json").write_text("{}", encoding="utf-8")
        got = evcs.ignored_paths(root, ["runtime.json", "kept.json", "gone/also_runtime.json"])
        check("runtime.json" in got and "kept.json" not in got,
              "on-disk classification matches gitignore rules (N003)")
        got2 = evcs.ignored_paths(root, ["kept.json"])
        check(got2 == set(), "rc=1 (nothing ignored) is a substantive empty answer")
        check(evcs.ignored_paths(root, []) == set(), "empty candidate set short-circuits")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> None:
    sota_acceptance_stamps_watermark()
    lease_covers_material_lifecycle()
    adoption_deferral_persists()
    revive_verifies_bytes()
    stage_settlement_requires_products()
    create_task_reuses_parked_duty()
    retirement_floor_suggests_only_revivable()
    gitignore_classification()
    done("V11.3 R8 FIX REGRESSIONS")


if __name__ == "__main__":
    main()
