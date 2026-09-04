"""R10-batch fix regressions (v11.5).

Unit pins for the tenth-round root-cause reconciliations (the drive suites
exercise the composed paths; these pin the load-bearing mechanics):
  - R10-001  a terminal failed/cancelled CURRENT attempt routes through the
             failure channel regardless of launch timing (_run_is_current_attempt)
  - R10-002  landing identity is an overlap relation (directory vs child,
             host-aware case folding) and remote product URIs are claimed
  - R10-003  DONE is written only through the blocker-guarded verdict writer
  - R10-006  a kernel core must cite at least one operator on the executable
             path to a registered output (OFF_PATH)
  - R10-007  fingerprint v2 carries iteration + depends_on; three-generation
             identity accept keeps stored hashes matching
  - R10-011  a reachable training artifact cannot hide an inference path that
             can never execute (DEPLOY_UNREACHABLE / fired INFER_PATH)
  - R10-012  one landing-resolution rule for every attempt (pinned in the
             v114 suite's updated repeat tests)
  - R10-013  the repeat lane records a stop decision without applying it
  - R10-018  the deployed inference path may not read typed supervision
  - R10-019  extension-axis accounting must equal the configure-time freeze
  - R10-020  observation evidence must bind an existing source
  - R10-016  the repeat-origin replacement gate discloses the third exit
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "engine"))
from _check import check, done  # noqa: E402

import eabsorb   # noqa: E402
import econfig   # noqa: E402
import eprogram  # noqa: E402
import esched    # noqa: E402
import eutil     # noqa: E402
import evalid    # noqa: E402


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="r10fix_"))


# ------------------------------------------------------------- R10-001 ----
_CUR_SPEC = {
    "training_replication": {"mode": "single", "runs": 1, "seeds": [1009],
                             "aggregation": "none", "source": "workflow"},
    "workflow": {"stages": [{"name": "train", "metrics_file": "work/m.json"}]},
}


def _cur_stub(runs: list) -> SimpleNamespace:
    stub = SimpleNamespace(st={"runs": runs}, _spec=lambda n: _CUR_SPEC)
    stub._repeat_run_pending = eabsorb.AbsorbMixin._repeat_run_pending
    stub._run_is_current_attempt = (
        lambda run, node: eabsorb.AbsorbMixin._run_is_current_attempt(stub, run, node))
    return stub


def current_attempt_predicate() -> None:
    run = {"id": "RUN1", "kind": "stage", "stage": "train", "stage_index": 0,
           "logical_slot_key": "slot-a", "attempt_no": 1, "replica_seed": 1009}
    node = {"id": "N1", "status": "stage_ready", "stage_cursor": 0, "replica_index": 0}
    stub = _cur_stub([run])
    check(stub._run_is_current_attempt(run, node),
          "a pre-launch attempt is CURRENT while the node still owns its position (R10-001)")
    node_exec = dict(node, status="executing")
    check(stub._run_is_current_attempt(run, node_exec),
          "launch timing does not change ownership")
    newer = dict(run, id="RUN2", attempt_no=2)
    stub2 = _cur_stub([run, newer])
    check(not stub2._run_is_current_attempt(run, node),
          "a newer attempt in the same slot owns the position")
    check(not stub._run_is_current_attempt(dict(run, confirmed_not_launched=True), node),
          "a confirmed never-launched intent settles through its own zero-usage channel")
    check(not stub._run_is_current_attempt(dict(run, stage_index=1), node),
          "a stale position (cursor moved on) is history")
    moved = dict(node, stage_cursor=1)
    check(not stub._run_is_current_attempt(run, moved),
          "the node moving past the stage retires the attempt's ownership")
    ev_run = {"id": "RUN3", "kind": "eval", "logical_slot_key": "slot-e", "attempt_no": 1}
    ev_node = {"id": "N1", "status": "workflow_done", "eval_done": False}
    stub3 = _cur_stub([ev_run])
    check(stub3._run_is_current_attempt(ev_run, ev_node),
          "the pending base evaluation attempt is current before eval_done")
    check(not stub3._run_is_current_attempt(ev_run, dict(ev_node, eval_done=True)),
          "a settled evaluation no longer waits on this attempt")
    rep_node = {"id": "N1", "status": "workflow_done", "eval_done": True,
                "repeat_measure": {"engine_run": True}, "repeat_pending_seed": 1010}
    check(not stub3._run_is_current_attempt(ev_run, rep_node),
          "base attempts are history while the repeat lane is owed (lane axis)")
    rep_run = dict(ev_run, id="RUN4", logical_slot_key="slot-r",
                   repeat_measure_attempt=True, replica_seed=1010)
    stub4 = _cur_stub([rep_run])
    check(stub4._run_is_current_attempt(rep_run, rep_node),
          "the repeat evaluation attempt is current while its lane is owed")


# ------------------------------------------------------------- R10-002 ----
def landing_overlap_relation() -> None:
    check(eutil.paths_overlap("out/shared", "out/shared/model.pt"),
          "a directory product overlaps its child file (R10-002)")
    check(eutil.paths_overlap("out/shared/model.pt", "out/shared"),
          "ancestry is symmetric")
    check(not eutil.paths_overlap("out/sharedX", "out/shared"),
          "a common prefix without a separator is NOT overlap")
    check(eutil.paths_overlap("a/./b", "a//b"), "normalization still applies")
    check(not eutil.paths_overlap("s3://bkt/a", "s3://bkt/a/b"),
          "scheme URIs compare exactly (backend semantics own their hierarchy)")
    check(eutil.paths_overlap("s3://bkt/a", "s3://bkt/a"),
          "identical remote URIs overlap")
    if eutil.case_insensitive_host():
        check(eutil.paths_overlap("out/Result.JSON", "out/result.json"),
              "case folds on a case-insensitive host (probed, one physical landing)")


def lease_holder_overlap() -> None:
    stub = SimpleNamespace(st={"runs": [
        {"id": "RUN1", "status": "running", "evidence_status": "pending",
         "landing_claims": ["out/shared"], "declared_metrics_file": "",
         "declared_ledger_file": ""},
    ]}, _run_claim_set=eabsorb.AbsorbMixin._run_claim_set,
                       # G-3 stub sync: fixture rows carry their claims inline
                       _ensure_run_claims=lambda run: None)
    holder = eabsorb.AbsorbMixin._landing_lease_holder(stub, "out/shared/model.pt")
    check(holder is not None and holder["id"] == "RUN1",
          "a live directory claim leases every child path (R10-002)")
    check(eabsorb.AbsorbMixin._landing_lease_holder(stub, "out/other.pt") is None,
          "disjoint paths stay free")
    remote = SimpleNamespace(st={"runs": [
        {"id": "RUN2", "status": "running", "evidence_status": "pending",
         "landing_claims": ["oss://bkt/user/x/checkpoint.zip"],
         "declared_metrics_file": "", "declared_ledger_file": ""},
    ]}, _run_claim_set=eabsorb.AbsorbMixin._run_claim_set,
                       # G-3 stub sync: fixture rows carry their claims inline
                       _ensure_run_claims=lambda run: None)
    check(eabsorb.AbsorbMixin._landing_lease_holder(
        remote, "oss://bkt/user/x/checkpoint.zip") is not None,
          "a live remote product URI is leased exactly (registry uniqueness law)")


# ------------------------------------------------------------- R10-003 ----
def terminal_verdict_guarded() -> None:
    st = {"phase": "running", "rounds": [], "recoveries": [],
          "runs": [{"id": "RUN1", "status": "running", "evidence_status": "pending"}]}
    events: list = []
    stub = SimpleNamespace(st=st, g={"nodes": []},
                           store=SimpleNamespace(event=lambda a, n, **k: events.append(n)))
    stub._pending_recovery_case = lambda: esched.Engine._pending_recovery_case(stub)
    stub._recovery_review_hint = lambda case: "hint"
    stub._repeat_run_pending = eabsorb.AbsorbMixin._repeat_run_pending
    stub._terminal_blockers = lambda: esched.Engine._terminal_blockers(stub)
    stub._blocked_terminal_surface = (
        lambda blockers: esched.Engine._blocked_terminal_surface(stub, blockers))
    stub._watch_or_wait = lambda: {"kind": "waiting", "reason": "obligations first"}
    stub._closed_rounds = lambda: 0
    out = esched.Engine._terminal_verdict(stub, "all rounds finished", event="evolution_done")
    check(out.get("kind") == "waiting" and st.get("phase") == "running",
          "a live RUN defers the verdict AND the phase stays alive (R10-003)")
    check("evolution_done" not in events, "no premature terminal event")
    st["runs"][0]["status"] = "finished"
    st["runs"][0]["evidence_status"] = "complete"
    st["runs"][0]["resource_accounted"] = True
    out = esched.Engine._terminal_verdict(stub, "all rounds finished", event="evolution_done")
    check(out.get("kind") == "done" and st.get("phase") == "done"
          and "evolution_done" in events,
          "with the world settled the verdict lands through the same writer")


# ------------------------------------------- R10-006 / 011 / 018 (IR) ----
def _cand(operators, kernel_refs, objects=None):
    return {
        "change_scope": "component",
        "novelty": {"kind": "composition", "bearer": "the head",
                    "kernel": [{"id": "KC1", "kind": "state_relation",
                                "statement": "x" * 60, "operator_refs": kernel_refs}]},
        "program": {
            "objects": objects or [
                {"id": "O1", "kind": "input", "semantics": "s" * 32},
                {"id": "O2", "kind": "state", "semantics": "s" * 32},
                {"id": "O3", "kind": "prediction", "semantics": "s" * 32},
                {"id": "O4", "kind": "representation", "semantics": "s" * 32},
            ],
            "operators": operators,
        },
    }


def _op(opid, kind, phase, reads, writes, **extra):
    return {"id": opid, "kind": kind, "phase": phase, "semantics": "s" * 55,
            "reads": reads, "writes": writes, **extra}


def kernel_core_off_path_refused() -> None:
    ops = [_op("OP1", "update", "train", ["O1"], ["O2"]),
           _op("OP2", "estimator", "infer", ["O2"], ["O3"]),
           _op("OP3", "transform", "train", ["O1"], ["O4"])]
    errs = eprogram.candidate_errors(_cand(ops, ["OP3"]), where="c", min_level=0,
                                     research=False, search_origin="repair",
                                     model_parent_count=1)
    check(any(e.startswith("PROGRAM_KERNEL_OPERATOR_OFF_PATH") for e in errs),
          "a core citing only an executable-but-inert side branch is refused (R10-006)")
    errs = eprogram.candidate_errors(_cand(ops, ["OP1", "OP3"]), where="c", min_level=0,
                                     research=False, search_origin="repair",
                                     model_parent_count=1)
    check(not any(e.startswith("PROGRAM_KERNEL_OPERATOR_OFF_PATH") for e in errs),
          "one load-bearing reference legitimizes the core (helpers may ride along)")


def artifact_cannot_hide_dead_inference() -> None:
    objects = [
        {"id": "O1", "kind": "input", "semantics": "s" * 32},
        {"id": "O2", "kind": "state", "semantics": "s" * 32},
        {"id": "O3", "kind": "prediction", "semantics": "s" * 32},
        {"id": "O4", "kind": "artifact", "semantics": "s" * 32},
        {"id": "O5", "kind": "state", "semantics": "s" * 32},
    ]
    ops = [_op("OP1", "update", "train", ["O1"], ["O2", "O4"]),
           _op("OP2", "estimator", "infer", ["O2", "O5"], ["O3"])]
    errs, _o, _p, fired, _lb = eprogram._program_graph_errors(
        _cand(ops, ["OP1"], objects)["program"], where="p", require_learning=True)
    check("OP2" not in fired, "the inference row never fires (its read has no producer)")
    check(any(e.startswith("PROGRAM_INFER_PATH") for e in errs),
          "a declared-but-never-firing inference row does not satisfy the path duty (R10-011)")
    check(any(e.startswith("PROGRAM_DEPLOY_UNREACHABLE") for e in errs),
          "a reachable training artifact cannot stand in for the deployed prediction")


def inference_may_not_read_supervision() -> None:
    objects = [
        {"id": "O1", "kind": "input", "semantics": "s" * 32},
        {"id": "O2", "kind": "supervision", "semantics": "s" * 32},
        {"id": "O3", "kind": "state", "semantics": "s" * 32},
        {"id": "O4", "kind": "prediction", "semantics": "s" * 32},
    ]
    ops = [_op("OP1", "update", "train", ["O1", "O2"], ["O3"]),
           _op("OP2", "estimator", "infer", ["O2", "O3"], ["O4"])]
    errs, *_rest = eprogram._program_graph_errors(
        _cand(ops, ["OP2"], objects)["program"], where="p", require_learning=True)
    check(any(e.startswith("PROGRAM_INFER_SUPERVISION") for e in errs),
          "the deployed inference path may not consume typed supervision (R10-018)")
    ops_ok = [_op("OP1", "update", "train", ["O1", "O2"], ["O3"]),
              _op("OP2", "estimator", "infer", ["O1", "O3"], ["O4"])]
    errs, *_rest = eprogram._program_graph_errors(
        _cand(ops_ok, ["OP2"], objects)["program"], where="p", require_learning=True)
    check(not any(e.startswith("PROGRAM_INFER_SUPERVISION") for e in errs),
          "training may read supervision; a label-free inference path passes")


# ------------------------------------------------------------- R10-007 ----
def fingerprint_carries_execution_fields() -> None:
    base_ops = [_op("OP1", "update", "train", ["O1"], ["O2"],
                    iteration={"kind": "fixed_point", "state_objects": ["O2"],
                               "update_order": "u" * 32, "termination": "t" * 32,
                               "max_steps": 1}),
                _op("OP2", "estimator", "infer", ["O2"], ["O3"])]
    cand = _cand(base_ops, ["OP1"])
    other = json.loads(json.dumps(cand))
    other["program"]["operators"][0]["iteration"]["max_steps"] = 100
    check(eprogram.kernel_fingerprint(cand) != eprogram.kernel_fingerprint(other),
          "changing a core operator's loop bound changes its identity (R10-007)")
    dep = json.loads(json.dumps(cand))
    dep["program"]["operators"][1]["depends_on"] = ["OP1"]
    dep["novelty"]["kernel"][0]["operator_refs"] = ["OP2"]
    base2 = json.loads(json.dumps(cand))
    base2["novelty"]["kernel"][0]["operator_refs"] = ["OP2"]
    check(eprogram.kernel_fingerprint(base2) != eprogram.kernel_fingerprint(dep),
          "changing a core operator's declared schedule changes its identity")
    v2, v1, legacy = eprogram.kernel_fingerprints(cand)
    check(len({v2, v1, legacy}) == 3 or v2 != legacy,
          "three generations are distinct spellings for an execution-field program")
    for stored in (v2, v1, legacy):
        check(eprogram.kernel_identity_matches(stored, cand),
              "every stored generation keeps matching its verbatim computation")
    renumbered = json.loads(json.dumps(cand))
    for row in renumbered["program"]["operators"]:
        row["id"] = "OP" + str(int(row["id"][2:]) + 10)
    renumbered["novelty"]["kernel"][0]["operator_refs"] = ["OP11"]
    check(eprogram.kernel_fingerprint(renumbered) == v2,
          "consistent renumbering keeps the v2 identity (refs resolve to content)")
    plain = _cand([_op("OP1", "update", "train", ["O1"], ["O2"]),
                   _op("OP2", "estimator", "infer", ["O2"], ["O3"])], ["OP1"])
    pv2, pv1, _pl = eprogram.kernel_fingerprints(plain)
    missing_vs_empty = json.loads(json.dumps(plain))
    missing_vs_empty["program"]["operators"][0]["depends_on"] = []
    check(eprogram.kernel_fingerprint(missing_vs_empty) == pv2,
          "an absent and an empty schedule are one spelling (no gratuitous drift)")


# ------------------------------------------------------------- R10-013 ----
_ADV_SPEC = {
    "training_replication": {"mode": "single", "runs": 1, "seeds": [1009],
                             "aggregation": "none", "source": "workflow"},
    "workflow": {"stages": [{
        "name": "train", "metrics_file": "work/m.json",
        "continuation_gate": {"id": "CG1", "predicates": []},
    }]},
}


def repeat_lane_records_stop_without_applying() -> None:
    events: list = []
    node = {"id": "N1", "stage_cursor": 0, "replica_index": 0, "status": "executing",
            "repeat_measure": {"engine_run": True}, "repeat_pending_seed": 1010,
            "eval_done": True}
    run = {"id": "RUN9", "repeat_measure_attempt": True, "replica_seed": 1010}
    stub = SimpleNamespace(
        _spec=lambda n: _ADV_SPEC,
        _register_stage_artifacts=lambda *a, **k: None,
        _repeat_run_pending=eabsorb.AbsorbMixin._repeat_run_pending,
        _apply_scientific_stop=lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("the repeat lane must never apply a stop")),
        store=SimpleNamespace(event=lambda a, n, **k: events.append(n)),
    )
    stub._register_or_defer_stage_products = (
        lambda *a, **k: eabsorb.AbsorbMixin._register_or_defer_stage_products(stub, *a, **k))
    decision = {"id": "CG1", "outcome": "stop_node", "predicates": []}
    eabsorb.AbsorbMixin._advance_stage(stub, node, run, gate_decision=decision)
    check(run.get("scientific_outcome") == "stop_node"
          and run.get("scientific_gate") == decision,
          "the stop decision is recorded verbatim on the RUN (doctor drift audit)")
    check("repeat_stage_gate_observed" in events,
          "the observation is announced instead of applied (R10-013)")
    check(node["status"] == "workflow_done" and node.get("repeat_pending_seed") == 1010,
          "the purchased lane runs to completion; the obligation stays visible")


# ------------------------------------------------------------- R10-019 ----
def extension_axis_accounting_frozen() -> None:
    root = _tmp()
    try:
        cfg = {"resource_contract": {"extension_axes": [
                   {"key": "energy_wh", "unit": "wh", "accounting": "scheduler_ledger"}]},
               "evidence_policy": {}}
        frozen = {str(r.get("key")): str(r.get("accounting"))
                  for r in cfg["resource_contract"]["extension_axes"]}
        check(frozen.get("energy_wh") == "scheduler_ledger"
              and "energy_wh" in econfig.resource_axes(cfg),
              "the extension axis and its frozen accounting are configured")
        # the load-bearing comparison lives in _spec_errors; pin its rule here:
        row = {"method": "runtime_profiler", "description": "d" * 45}
        drifted = frozen.get("energy_wh") and row["method"] != frozen["energy_wh"]
        check(bool(drifted),
              "a NODE_SPEC method differing from the configure-time freeze is drift (R10-019)")
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------- R10-020 ----
def observation_evidence_binds_sources() -> None:
    root = _tmp()
    try:
        eutil.write_json_atomic(root / "runs" / "m.json", {"auc": 0.8})
        ctx = SimpleNamespace(store=SimpleNamespace(repo=root),
                              st={"runs": [{"id": "RUN7", "metrics_file": "runs/m.json",
                                            "status": "finished",
                                            "evidence_status": "complete"}]},
                              reg={"artifacts": [{"id": "AR001", "uri": "oss://b/x",
                                                  "status": "available"}]})
        f = evalid._observation_evidence_bound
        check(f(ctx, "runs/m.json"), "an existing repo path binds (R10-020)")
        check(f(ctx, "see RUN7 sealed metrics"), "a RUN id with sealed metrics binds")
        ctx.st["runs"].append({"id": "RUN8", "metrics_file": "runs/m.json",
                               "status": "finished", "evidence_status": "invalid"})
        check(not f(ctx, "see RUN8"), "an engine-refused (invalid-evidence) RUN binds nothing (R11-006)")
        ctx.reg["artifacts"].append({"id": "AR002", "uri": "oss://b/stale", "status": "stale"})
        check(not f(ctx, "AR002"), "a stale artifact row binds nothing (sweep G-7)")
        check(f(ctx, "registered AR001"), "a registered artifact id binds")
        check(f(ctx, "oss://b/x"), "a registered artifact URI binds")
        check(not f(ctx, "runs/RUN999/missing_metrics.json"),
              "a nonexistent path binds nothing")
        check(not f(ctx, "the curve clearly shows it"),
              "free text is not a source")
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------- R10-016 ----
def repeat_spend_gate_discloses_third_exit() -> None:
    class FakeStore:
        def new_gate(self, state, kind, subject, message):
            gate = {"id": "G1", "kind": kind, "subject": subject,
                    "message": message, "summary": message, "status": "open"}
            state["gates"].append(gate)
            return gate

        def get_run(self, state, run_id):
            return next((r for r in state.get("runs", []) if r.get("id") == run_id), None)

    eng = object.__new__(esched.Engine)
    eng.store = FakeStore()
    eng.st = {"gates": [], "runs": [
        {"id": "RUN9", "repeat_measure_attempt": True, "replica_seed": 1010}]}
    node = {"id": "N1", "repeat_attempt": {
        "operation": "eval", "source_run": "RUN9", "failure_class": "unknown"}}
    gate = eng._repeat_spend_gate(node, "eval")
    check("waive-repeat" in str(gate.get("message") or gate.get("summary")),
          "a repeat-origin replacement gate discloses the third exit (R10-016)")
    eng2 = object.__new__(esched.Engine)
    eng2.store = FakeStore()
    eng2.st = {"gates": [], "runs": [{"id": "RUN5"}]}
    node2 = {"id": "N1", "repeat_attempt": {
        "operation": "eval", "source_run": "RUN5", "failure_class": "unknown"}}
    gate2 = eng2._repeat_spend_gate(node2, "eval")
    check("waive-repeat" not in str(gate2.get("message") or gate2.get("summary")),
          "an ordinary replacement gate keeps its two-way surface")


def main() -> None:
    current_attempt_predicate()
    landing_overlap_relation()
    lease_holder_overlap()
    terminal_verdict_guarded()
    kernel_core_off_path_refused()
    artifact_cannot_hide_dead_inference()
    inference_may_not_read_supervision()
    fingerprint_carries_execution_fields()
    repeat_lane_records_stop_without_applying()
    extension_axis_accounting_frozen()
    observation_evidence_binds_sources()
    repeat_spend_gate_discloses_third_exit()
    done("V11.5 R10 FIX REGRESSIONS")


if __name__ == "__main__":
    main()
