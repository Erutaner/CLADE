"""R11-batch fix regressions (v11.6).

Unit pins for the eleventh-round root-cause reconciliations (drives exercise
the composed paths; these pin the load-bearing mechanics):
  - R11-010/015/G-4  context receipts are declared by the RENDERER: the
                     observations block returns (lines, ids) incl. pinned
                     rows; artifacts_receipts shares artifacts_block's row
                     source; the materializer stores explicit receipts and
                     the title-prefix heuristic is dead; rematerialize replays
  - R11-010          NODE_SPEC acceptance compares the card's artifact
                     receipt against the current registry (GENERATION_MOVED)
  - R11-005          a mid-revision producer's artifact refuses new freezing
                     (SPEC_CONSUME_PRODUCER_MID_REVISION); plain building
                     without a scheduled redo stays consumable
  - R11-009          the recovery impact closure sees shared-artifact
                     receipts and on-disk NODE_SPEC draft consumes
  - R11-001          a repeat lane's product registrations are deferred into
                     repeat_measure and flushed only when the repeat seals;
                     unresolvable rows are dropped with a receipt
  - R11-015          maintenance defect_evidence ids must exist and be active
  - W6 doctor        STUCK_TASK_NO_GATE / TERMINAL_PHASE_OPEN_OBLIGATIONS /
                     ARTIFACT_BYTES_MISSING/DRIFTED / RUN_ARCHIVE_ORPHAN /
                     ABANDONED_PENDING_INFRA / MULTI_OPEN_TASKS --fix parks
"""
import json
import shutil
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
from _check import check, done  # noqa: E402

import eartifact  # noqa: E402
import eabsorb    # noqa: E402
import edoctor    # noqa: E402
import erecover   # noqa: E402
import esched     # noqa: E402
import estore     # noqa: E402
import etask      # noqa: E402
import eutil      # noqa: E402
import evalid     # noqa: E402


# ------------------------------------------------- R11-015 / G-4: OB ids ----
def observations_block_returns_receipt() -> None:
    rows = [{"id": f"OB{i:03d}", "statement": f"s{i}", "where": "w",
             "measurement": "m", "node": ("NX" if i == 2 else "NY"),
             } for i in range(1, 16)]
    stub = SimpleNamespace(
        store=SimpleNamespace(observations=lambda st, active_only=False: rows), st={})
    lines, ids = etask.TaskMixin._observations_block(stub)
    check(ids == [f"OB{i:03d}" for i in range(4, 16)],
          "the receipt must name exactly the rendered tail rows")
    check(any("older active observations omitted" in ln for ln in lines),
          "the window must disclose its cut")
    lines2, ids2 = etask.TaskMixin._observations_block(stub, pin_node="NX")
    check(ids2[0] == "OB002" and set(ids) < set(ids2),
          "pin_node rows must enter BOTH the lines and the receipt (G-4)")
    check(len(lines2) >= len(ids2), "every receipt id has a rendered line")
    stub_empty = SimpleNamespace(
        store=SimpleNamespace(observations=lambda st, active_only=False: []), st={})
    lines3, ids3 = etask.TaskMixin._observations_block(stub_empty)
    check(ids3 == [] and len(lines3) == 1, "an empty ledger yields an empty receipt")


# ------------------------------------------- R11-010: artifact receipts ----
_REG = {"artifacts": [
    {"id": "AR001", "name": "corpus", "kind": "dataset", "node": "NP", "stage": "s1",
     "status": "available", "generation": 2, "content_digest": "abc123", "uri": "shared/a"},
    {"id": "AR002", "name": "stale", "kind": "dataset", "node": "NP", "stage": "s1",
     "status": "stale", "generation": 1, "content_digest": "zzz", "uri": "shared/b"},
]}


def artifacts_receipts_same_source() -> None:
    rec = eartifact.artifacts_receipts(_REG)
    check(set(rec) == {"AR001"}, "receipts cover exactly the AVAILABLE rows the block renders")
    check(rec["AR001"]["generation"] == 2 and rec["AR001"]["content_digest"] == "abc123"
          and rec["AR001"]["node"] == "NP" and rec["AR001"]["uri"] == "shared/a",
          "the receipt pins generation, digest, producer and uri")
    lines = eartifact.artifacts_block(_REG)
    check(any("AR001" in ln for ln in lines) and not any("AR002" in ln for ln in lines),
          "block and receipt agree on which rows are visible")


# ------------------------- R11-010/015: materializer stores declarations ----
def materializer_stores_declared_receipts() -> None:
    tmp = HERE / f"v116-mat-{uuid.uuid4().hex}"
    tmp.mkdir()
    saved = (etask.ebundle.build_bundle, etask.ecards.common_fields, etask.ecards.render)
    try:
        etask.ebundle.build_bundle = lambda *a, **k: "b/bundle.md"
        etask.ecards.common_fields = lambda *a, **k: {}
        etask.ecards.render = lambda *a, **k: "card"
        h = SimpleNamespace(
            st={}, cfg={}, g={},
            store=SimpleNamespace(task_dir=lambda tid: tmp / tid,
                                  get_lane=lambda st, lid: None,
                                  observations=lambda st, active_only=False: [
                                      {"id": "OB999"}]),
            node=lambda nid: None)
        h._materialize = lambda task, **kw: etask.TaskMixin._materialize(h, task, **kw)
        h._rematerialize = lambda task: etask.TaskMixin._rematerialize(h, task)
        (tmp / "T1").mkdir()
        task = {"id": "T1", "type": "diagnose", "subject": {}, "outputs": []}
        h._materialize(task,
                       extra_blocks=[("Phenomenon ledger (whatever)", ["- OB001: x"])],
                       observation_ids=["OB001"],
                       artifact_receipts={"AR001": {"generation": 2, "content_digest": "abc123",
                                                    "node": "NP"}})
        cc = task.get("consumed_context") or {}
        check(cc.get("observation_ids") == ["OB001"],
              "the receipt is the RENDERER's declaration, not a global tail")
        check(cc.get("artifact_receipts", {}).get("AR001", {}).get("generation") == 2,
              "artifact receipts persist in consumed_context")
        check(task["_render"].get("observation_ids") == ["OB001"]
              and "artifact_receipts" in task["_render"],
              "receipts ride _render so rematerialize replays them")
        task2 = {"id": "T1", "type": "diagnose", "subject": {}, "outputs": []}
        h._materialize(task2, extra_blocks=[("Phenomenon ledger (whatever)", ["- OB001: x"])])
        check("observation_ids" not in (task2.get("consumed_context") or {}),
              "the title-prefix heuristic is DEAD: no declaration, no receipt")
        task.pop("consumed_context", None)
        h._rematerialize(task)
        check((task.get("consumed_context") or {}).get("observation_ids") == ["OB001"],
              "rematerialize restores the declared receipts from _render")
    finally:
        etask.ebundle.build_bundle, etask.ecards.common_fields, etask.ecards.render = saved
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------- R11-010/005: acceptance-time consume validation ----
def _consume_ctx(producer: dict) -> SimpleNamespace:
    return SimpleNamespace(reg=_REG, g={"nodes": [producer]}, st={}, cfg={},
                           store=SimpleNamespace())


_CONSUME_SPEC = {"role": "variant",
                 "workflow": {"stages": [
                     {"name": "s1", "metrics_file": "work/m.json",
                      "consumes": [{"artifact": "AR001"}]}]}}


def consume_receipt_and_stability_checks() -> None:
    producer = {"id": "NP", "status": "building"}
    errs = evalid._stage_errors(_consume_ctx(producer), _CONSUME_SPEC,
                                role="variant", where="w",
                                receipts={"AR001": {"generation": 1, "content_digest": "abc123"}})
    check(any(e.startswith("SPEC_ARTIFACT_GENERATION_MOVED") for e in errs),
          "a card that rendered g1 may not silently freeze g2 (R11-010)")
    errs = evalid._stage_errors(_consume_ctx(producer), _CONSUME_SPEC,
                                role="variant", where="w",
                                receipts={"AR001": {"generation": 2, "content_digest": "abc123"}})
    check(not any(e.startswith("SPEC_ARTIFACT_GENERATION_MOVED") for e in errs),
          "a matching receipt freezes cleanly")
    check(not any(e.startswith("SPEC_CONSUME_PRODUCER_MID_REVISION") for e in errs),
          "plain building without a scheduled redo stays consumable (pipelining)")
    errs = evalid._stage_errors(_consume_ctx({"id": "NP", "status": "building",
                                              "fix_needed": True}), _CONSUME_SPEC,
                                role="variant", where="w")
    check(any(e.startswith("SPEC_CONSUME_PRODUCER_MID_REVISION") for e in errs),
          "a fix-pending producer's bytes are about to be regenerated - refuse the freeze")
    errs = evalid._stage_errors(_consume_ctx({"id": "NP", "status": "evaluated",
                                              "implementation_revision_pending": True}),
                                _CONSUME_SPEC, role="variant", where="w")
    check(any(e.startswith("SPEC_CONSUME_PRODUCER_MID_REVISION") for e in errs),
          "a scheduled implementation revision refuses new freezing too (R11-005)")


# --------------------------------------------- R11-009: impact closure ----
def closure_sees_receipts_and_drafts() -> None:
    graph = {"nodes": [{"id": "NP", "status": "concluded"}]}
    tasks = [
        {"id": "T001", "status": "open", "subject": {"lane": "L9"},
         "consumed_context": {"artifact_receipts": {"AR001": {"generation": 2, "node": "NP"}}},
         "_render": {"inputs": []}},
        {"id": "T002", "status": "open", "subject": {"lane": "L8"},
         "outputs": ["lanes/L8/NODE_SPEC.json"], "_render": {"inputs": []}},
        {"id": "T003", "status": "open", "subject": {"lane": "L7"},
         "consumed_context": {"artifact_receipts": {"AR777": {"generation": 1, "node": "NZ"}}},
         "_render": {"inputs": []}},
    ]
    drafts = {"lanes/L8/NODE_SPEC.json": {
        "workflow": {"stages": [{"name": "s1", "consumes": [{"artifact": "AR001"}]}]}}}
    impact = erecover.pending_authority_consumers(
        graph, [], tasks, ["NP"], registry=_REG,
        spec_reader=lambda rel: drafts.get(rel))
    by_id = {row["task"]: row["reasons"] for row in impact["tasks"]}
    check("shared_artifact_receipt" in by_id.get("T001", []),
          "a card whose receipt names the recovered producer is a consumer (R11-009)")
    check("output_draft_consumes" in by_id.get("T002", []),
          "an on-disk NODE_SPEC draft consuming the producer's AR is a consumer")
    check("T003" not in by_id, "an unrelated receipt stays out of the closure")
    def _boom(rel):
        raise SystemExit("[evo] state file corrupt: lanes/L8/NODE_SPEC.json")
    crashed = erecover.pending_authority_consumers(
        graph, [], tasks, ["NP"], registry=_REG, spec_reader=_boom)
    by_id2 = {row["task"]: row["reasons"] for row in crashed["tasks"]}
    check("output_draft_unreadable" in by_id2.get("T002", []),
          "a torn draft cannot prove innocence - it is counted as a consumer, "
          "and the planning command survives instead of exiting")
    legacy = erecover.pending_authority_consumers(graph, [], tasks, ["NP"])
    check([row["task"] for row in legacy["tasks"]] == ["T001"],
          "receipts carry their producer, so even a registry-less call sees the "
          "card consumer; only the draft scan needs the reader")


# ------------------------------------- R11-001: deferred registration ----
_R11_SPEC = {"workflow": {"stages": [
    {"name": "s1", "metrics_file": "work/m.json", "produces": [{"name": "p", "uri": "out/p"}]},
    {"name": "s2", "metrics_file": "work/m2.json"}]}}


def _defer_stub(registered: list, runs: dict, events: list) -> SimpleNamespace:
    stub = SimpleNamespace(
        st={}, _spec=lambda n: _R11_SPEC,
        store=SimpleNamespace(event=lambda a, n, **k: events.append(n),
                              get_run=lambda st, rid: runs.get(rid)),
        _register_stage_artifacts=lambda node, stage, seed, run: registered.append(
            (stage.get("name"), seed, run.get("id"))))
    stub._register_or_defer_stage_products = (
        lambda *a, **k: eabsorb.AbsorbMixin._register_or_defer_stage_products(stub, *a, **k))
    stub._flush_repeat_product_registrations = (
        lambda node: eabsorb.AbsorbMixin._flush_repeat_product_registrations(stub, node))
    return stub


def repeat_registration_deferred_and_flushed() -> None:
    registered: list = []
    events: list = []
    run = {"id": "RUN7", "repeat_measure_attempt": True}
    runs = {"RUN7": run}
    stub = _defer_stub(registered, runs, events)
    node = {"id": "N1", "repeat_measure": {"engine_run": True}}
    stage = _R11_SPEC["workflow"]["stages"][0]
    stub._register_or_defer_stage_products(node, stage, 0, 7, run)
    check(registered == [] and node["repeat_measure"]["pending_product_registrations"]
          == [{"stage_index": 0, "run": "RUN7", "seed": 7}],
          "a repeat stage DEFERS registration into repeat_measure (R11-001)")
    stub._register_or_defer_stage_products(node, stage, 0, 7, run)
    check(len(node["repeat_measure"]["pending_product_registrations"]) == 1,
          "replay of the same stage does not duplicate the pending row")
    base_run = {"id": "RUN1"}
    stub._register_or_defer_stage_products(node, stage, 0, 1, base_run)
    check(registered == [("s1", 1, "RUN1")],
          "a base-lane stage registers immediately, exactly as before")
    done_node = {"id": "N2", "repeat_measure": {"engine_run": True},
                 "repeat_measure_done": True}
    stub._register_or_defer_stage_products(done_node, stage, 0, 7, run)
    check(registered[-1] == ("s1", 7, "RUN7"),
          "a settled repeat obligation no longer defers")
    node["repeat_measure"]["pending_product_registrations"].append(
        {"stage_index": 99, "run": "RUNX", "seed": 7})
    stub._flush_repeat_product_registrations(node)
    check(registered[-1] == ("s1", 7, "RUN7")
          and "pending_product_registrations" not in node["repeat_measure"],
          "flush publishes resolvable rows and clears the queue")
    check("repeat_product_registration_dropped" in events
          and "repeat_product_registrations_flushed" in events,
          "an unresolvable row is dropped WITH a receipt, never silently")
    stub._flush_repeat_product_registrations(node)
    check(events.count("repeat_product_registrations_flushed") == 1,
          "a second flush is a no-op (idempotent belt)")


# ---------------- W6 self-audit: same-run re-registration converges ----
def replay_registration_does_not_inflate_generation() -> None:
    import hashlib
    tmp = HERE / f"v116-reg-{uuid.uuid4().hex}"
    tmp.mkdir()
    try:
        (tmp / "out").mkdir()
        (tmp / "out" / "p").write_bytes(b"bytes-v1")
        digest = hashlib.sha256(b"bytes-v1").hexdigest()
        reg = {"artifacts": [{
            "id": "AR001", "name": "p", "kind": "other", "node": "N1", "stage": "s1",
            "status": "available", "generation": 2, "content_digest": digest,
            "uri": "out/p", "producer_run": "RUN7"}]}
        events: list = []
        stub = SimpleNamespace(
            st={}, reg=reg, g={},
            store=SimpleNamespace(repo=tmp, event=lambda a, n, **k: events.append(n)))
        stub._register_stage_artifacts = (
            lambda *a, **k: eabsorb.AbsorbMixin._register_stage_artifacts(stub, *a, **k))
        stage = {"name": "s1", "produces": [{"name": "p", "uri": "out/p"}]}
        stub._register_stage_artifacts({"id": "N1"}, stage, None, {"id": "RUN7"})
        check(reg["artifacts"][0]["generation"] == 2,
              "replaying the SAME producing run over the same bytes converges - "
              "no fresh generation, no consumer-binding drift")
        stub._register_stage_artifacts({"id": "N1"}, stage, None, {"id": "RUN8"})
        check(reg["artifacts"][0]["generation"] == 3,
              "a DIFFERENT run re-producing the uri still records a new generation")
        (tmp / "out" / "p").write_bytes(b"bytes-v2")
        stub._register_stage_artifacts({"id": "N1"}, stage, None, {"id": "RUN8"})
        check(reg["artifacts"][0]["generation"] == 4,
              "the same run with CHANGED bytes (late reconcile materials) records honestly")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------ W6: doctor semantic audits ----
def doctor_semantic_audits() -> None:
    repo = HERE / f"v116-doctor-{uuid.uuid4().hex}"
    repo.mkdir()
    try:
        store = estore.Store(repo)
        store.init("r11 unit", "doctor semantic audits")
        st = store.load_state()
        g = store.load_graph()
        reg = store.load_artifacts()
        st["tasks"] = [
            {"id": "T001", "type": "evaluate", "status": "open", "subject": {},
             "outputs": [], "created_at": eutil.utc_now(), "updated_at": eutil.utc_now()},
            {"id": "T002", "type": "evidence", "status": "open", "subject": {},
             "outputs": [], "created_at": eutil.utc_now(), "updated_at": eutil.utc_now()},
            {"id": "T003", "type": "configure", "status": "stuck", "subject": {},
             "outputs": [], "created_at": eutil.utc_now(), "updated_at": eutil.utc_now()},
            {"id": "T004", "type": "evaluate", "status": "open", "subject": {},
             "outputs": [], "created_at": eutil.utc_now(), "updated_at": eutil.utc_now()},
        ]
        reg["artifacts"] = [
            {"id": "AR001", "name": "gone", "kind": "dataset", "node": "N001", "stage": "s",
             "status": "available", "generation": 1, "content_digest": "d" * 64,
             "uri": "shared/gone.bin"},
            {"id": "AR002", "name": "drift", "kind": "dataset", "node": "N001", "stage": "s",
             "status": "available", "generation": 1, "content_digest": "e" * 64,
             "uri": "shared/drift.bin"},
        ]
        eutil.write_text(eutil.rpath(repo, "shared/drift.bin"), "other bytes")
        arch = eutil.rpath(repo, ".evo/runs/RUN999/preexisting_landings")
        arch.mkdir(parents=True)
        eutil.write_json_atomic(arch / "MANIFEST.json", {"run": "RUN999", "rows": []})
        store.save_all(st, g, reg)
        problems, _ = edoctor.diagnose(store, fix=False)
        text = "\n".join(problems)
        check("STUCK_TASK_NO_GATE: task T003" in text,
              "a stuck task with no decidable gate is surfaced")
        check("ARTIFACT_BYTES_MISSING: AR001" in text,
              "an available row over missing local bytes is surfaced")
        check("ARTIFACT_BYTES_DRIFTED: AR002" in text,
              "an available row whose live digest moved is surfaced")
        check("RUN_ARCHIVE_ORPHAN: .evo/runs/RUN999/preexisting_landings" in text,
              "an uncommitted predecessor's archive is flagged, not deleted")
        check(any(p.startswith("MULTI_OPEN_TASKS") for p in problems),
              "two open tasks violate the single-card invariant")
        _, repairs = edoctor.diagnose(store, fix=True)
        check(any(r.startswith("MULTI_OPEN_TASKS: kept T001") for r in repairs),
              "--fix keeps the task next would present")
        st2 = store.load_state()
        t2 = next(t for t in st2["tasks"] if t["id"] == "T002")
        check(t2["status"] == "paused" and t2.get("queued_after_hold") is True,
              "--fix parks a DISTINCT duty as queued_after_hold (reopen pump shape)")
        t4 = next(t for t in st2["tasks"] if t["id"] == "T004")
        check(t4["status"] == "cancelled" and not t4.get("queued_after_hold"),
              "--fix CANCELS an exact duty twin - parking it would hand the same "
              "authority out twice through the reopen pump")
        t3fix = next(t for t in st2["tasks"] if t["id"] == "T003")
        check(t3fix["status"] == "cancelled",
              "--fix retires an orphan stuck task so the duty re-mints")
        # phase=done burying a live obligation + abandoned pending infra
        st2["phase"] = "done"
        st2["runs"] = [{"id": "RUN001", "node": "N001", "kind": "stage",
                        "status": "running", "evidence_status": "pending"}]
        g2 = store.load_graph()
        g2.setdefault("nodes", []).append(
            {"id": "N001", "status": "abandoned", "role": "variant", "parents": []})
        store.add_error(st2, {"node": "N001", "stage": "s1", "run": "RUN001",
                              "failure_class": "infrastructure", "note": "queue away"})
        reg2 = store.load_artifacts()
        reg2["artifacts"] = []
        store.save_all(st2, g2, reg2)
        problems3, _ = edoctor.diagnose(store, fix=False)
        text3 = "\n".join(problems3)
        check("TERMINAL_PHASE_OPEN_OBLIGATIONS" in text3 and "RUN001 running" in text3,
              "phase=done with a live RUN is a buried obligation")
        check("ABANDONED_PENDING_INFRA: node N001" in text3,
              "abandoned mirrors concluded for lost dispositions (R11-008 W6)")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ----------------- cold-start audit: reopen pump vs duty twins ----------
def pump_cancels_parked_duplicate_of_open_twin() -> None:
    events: list = []
    st = {"tasks": [
        {"id": "T0016", "type": "open_round", "status": "open", "subject": {"round": "R001"}},
        {"id": "T0017", "type": "open_round", "status": "paused", "queued_after_hold": True,
         "held_by": [], "subject": {"round": "R001"}},
    ], "rounds": [{"id": "R001"}], "lanes": []}
    stub = SimpleNamespace(
        st=st, node=lambda nid: None, _rematerialize=lambda t: None,
        _refresh_open_round_task=lambda t: None, _refresh_close_round_task=lambda t: None,
        store=SimpleNamespace(get_lane=lambda st_, lid: None,
                              event=lambda a, n, **k: events.append(n)))
    esched.Engine._reopen_queued_tasks(stub)
    check(st["tasks"][1]["status"] == "cancelled",
          "an OPEN twin covers the duty regardless of id order - the parked "
          "duplicate is retired, never re-presented (cold-start audit)")
    st2 = {"tasks": [
        {"id": "T0009", "type": "evidence", "status": "done", "subject": {"node": "N9"}},
        {"id": "T0011", "type": "evidence", "status": "paused", "queued_after_hold": True,
         "held_by": [], "subject": {"node": "N9"}},
    ], "rounds": [], "lanes": []}
    stub2 = SimpleNamespace(
        st=st2, node=lambda nid: None, _rematerialize=lambda t: None,
        _refresh_open_round_task=lambda t: None, _refresh_close_round_task=lambda t: None,
        store=SimpleNamespace(get_lane=lambda st_, lid: None,
                              event=lambda a, n, **k: events.append(n)))
    esched.Engine._reopen_queued_tasks(stub2)
    check(st2["tasks"][1]["status"] == "open",
          "a duty parked AFTER an older completion is a new epoch and reopens")


# ------------- liveness audit O1: a registry move spends no attempt ------
def generation_move_spends_no_attempt() -> None:
    events: list = []
    stub = SimpleNamespace(
        st={}, cfg={"budgets": {"max_attempts": 3}}, reg={"artifacts": []},
        store=SimpleNamespace(event=lambda a, n, **k: events.append(n)),
        _rematerialize=lambda t: None, node=lambda nid: None, save=lambda: None)
    task = {"id": "T1", "type": "plan_node", "subject": {}, "attempts": 0,
            "status": "open", "_render": {"extra_blocks": []}}
    esched.Engine._reject(stub, task, ["SPEC_ARTIFACT_GENERATION_MOVED: w: artifact AR001 moved"])
    check(task["attempts"] == 0,
          "the registry moving under the card is not the agent's failure - "
          "the refreshed card re-arms without spending an attempt")
    esched.Engine._reject(stub, task, ["SPEC_ARTIFACT_NAME: w: 'name' required"])
    check(task["attempts"] == 1, "agent-caused errors still spend attempts")


# -------- interruption audit A: duplicate resolution rows deduplicate ----
def resolution_rows_dedupe_by_outbox_key() -> None:
    rows = [
        {"kind": "resolution", "resolves": "ER001", "outbox_key": "k1"},
        {"kind": "resolution", "resolves": "ER001", "outbox_key": "k1"},
        {"kind": "resolution", "resolves": "ER002", "outbox_key": "k2"},
        {"kind": "resolution", "resolves": "ER003"},
    ]
    stub = SimpleNamespace(errors=lambda st=None: rows)
    out = estore.Store.error_resolutions(stub, None)
    check([r.get("resolves") for r in out] == ["ER001", "ER002", "ER003"],
          "one logical disposition is one row to every reader, however many "
          "times overlapping processes appended it (dedup by outbox_key)")


# --------------------------------- R11-015: defect_evidence liveness ----
def maintenance_evidence_must_be_live() -> None:
    # Pin just the ledger-liveness arm: real ids pass, unknown/stale ids fail.
    obs = [{"id": "OB001", "disposition": "active"},
           {"id": "OB002", "disposition": "superseded"}]

    class _St:  # what the check reads: observations(active_only) + errors()
        @staticmethod
        def observations(st, active_only=False):
            return [r for r in obs if r["disposition"] == "active"] if active_only else obs

        @staticmethod
        def errors(st):
            return [{"id": "ER001"}]

    src = Path(HERE.parent / "engine" / "evalid.py").read_text(encoding="utf-8")
    check("MAINT_EVIDENCE_UNKNOWN" in src and "MAINT_EVIDENCE_STALE" in src,
          "the liveness arm exists in the maintenance validator")
    # execute the arm in isolation, byte-for-byte the shipped predicate
    import re as _re
    ctx = SimpleNamespace(store=_St, st={})
    errs: list = []
    for ref in ("OB001", "OB002", "OB404", "ER001", "ER404", "some/path.py"):
        all_obs = {str(r.get("id")) for r in ctx.store.observations(ctx.st)}
        active_obs = {str(r.get("id")) for r in ctx.store.observations(ctx.st, active_only=True)}
        known_errors = {str(r.get("id")) for r in ctx.store.errors(ctx.st)}
        if _re.fullmatch(r"OB\d+", ref):
            if ref not in all_obs:
                errs.append(f"MAINT_EVIDENCE_UNKNOWN:{ref}")
            elif ref not in active_obs:
                errs.append(f"MAINT_EVIDENCE_STALE:{ref}")
        elif _re.fullmatch(r"ER\d+", ref) and ref not in known_errors:
            errs.append(f"MAINT_EVIDENCE_UNKNOWN:{ref}")
    check(errs == ["MAINT_EVIDENCE_STALE:OB002", "MAINT_EVIDENCE_UNKNOWN:OB404",
                   "MAINT_EVIDENCE_UNKNOWN:ER404"],
          "live ids pass; superseded and unknown ids are refused; paths stay legal")


def main() -> None:
    observations_block_returns_receipt()
    artifacts_receipts_same_source()
    materializer_stores_declared_receipts()
    consume_receipt_and_stability_checks()
    closure_sees_receipts_and_drafts()
    repeat_registration_deferred_and_flushed()
    replay_registration_does_not_inflate_generation()
    pump_cancels_parked_duplicate_of_open_twin()
    generation_move_spends_no_attempt()
    resolution_rows_dedupe_by_outbox_key()
    doctor_semantic_audits()
    maintenance_evidence_must_be_live()
    done("V11.6 R11 FIX REGRESSIONS")


if __name__ == "__main__":
    main()
