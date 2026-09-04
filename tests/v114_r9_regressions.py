"""R9-batch fix regressions (v11.4).

Unit-level pins for the ninth-round fixes (the doors drive R005 exercises the
full engine-run repeat lifecycle end to end; these pin the load-bearing
mechanics):
  - G1  _terminal_blockers: the one predicate behind "project done" reads
  - G4  _landing_claims: ONE canonical claim set per attempt (metrics, ledger,
        probe artifact, seed-resolved products) + the repeat-lane variant
  - G6  kernel identity dual-accept (re-classification / renumbering keep
        identity; stored legacy hashes keep matching)
  - G7  a load-bearing kernel reference must cite an EXECUTABLE operator
  - cfg  lanes_per_round_max = 0 is refused at the config layer
  - sup  an interrupted autonomy-change record is closed on re-run
  - W3   one landing-resolution rule for every attempt (R10-012)
  - W3   _repeat_run_pending truth table
  - W3   _advance_stage: the repeat lane never re-enters the preplanned loop
  - W3   metric door three states (pending / sealed-pinned / legacy)
  - W3   stage_metrics_of keys the repeat lane by seed (no shadowing)
  - W3   erun invariants admit the repeat lane's missing replica ordinal

Not re-pinned here (covered elsewhere): observation/inheritance axis split
(v10_frontier_semantics_unit), identity re-classification fixture
(v111_feature_unit), approval arming + doctor repeat exemptions + waive
guards (doors drive R005 + CLI paths).
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
import erun      # noqa: E402
import esched    # noqa: E402
import eutil     # noqa: E402
import evalid    # noqa: E402
import evo       # noqa: E402


def _tmp() -> Path:
    return Path(tempfile.mkdtemp(prefix="r9fix_"))


# ------------------------------------------------------------------ G1 ----
def terminal_blockers_three_kinds() -> None:
    st = {
        "recoveries": [{"id": "RC1", "status": "planned"}],
        "runs": [
            {"id": "RUN1", "status": "launch_unknown", "evidence_status": "pending"},
            {"id": "RUN2", "status": "running", "evidence_status": "pending"},
            {"id": "RUN3", "status": "finished", "evidence_status": "incomplete"},
            {"id": "RUN4", "status": "finished", "evidence_status": "complete",
             "resource_accounted": True},
        ],
    }
    g = {"nodes": [{"id": "N9", "repeat_measure": {"engine_run": True},
                    "repeat_pending_seed": 7}]}
    stub = SimpleNamespace(st=st, g=g)
    stub._pending_recovery_case = lambda: esched.Engine._pending_recovery_case(stub)
    stub._recovery_review_hint = lambda case: "review hint"
    stub._repeat_run_pending = eabsorb.AbsorbMixin._repeat_run_pending
    out = esched.Engine._terminal_blockers(stub)
    kinds = sorted((b["kind"], str(b.get("id"))) for b in out)
    check(("recovery", "RC1") in kinds, "an active recovery case blocks the terminal verdict (G1)")
    check(("run_active", "RUN1") in kinds and ("run_active", "RUN2") in kinds,
          "launch_unknown and running RUNs both block (external work may exist)")
    check(("run_obligation", "RUN3") in kinds,
          "a terminal RUN with an open evidence obligation blocks")
    check(("repeat_obligation", "N9") in kinds,
          "an approved, unsettled repeat measurement blocks the terminal verdict (R10-013)")
    check(all(str(b.get("id")) != "RUN4" for b in out),
          "a settled RUN does not block")
    st["recoveries"][0]["status"] = "applied"
    st["runs"] = [st["runs"][3]]
    g["nodes"][0]["repeat_measure_done"] = True
    check(esched.Engine._terminal_blockers(stub) == [],
          "nothing pending -> no blockers (the done read point may proceed)")


# ------------------------------------------------------------------ G4 ----
_CLAIM_SPEC = {
    "training_replication": {"mode": "preplanned", "runs": 2, "seeds": [7, 8],
                             "aggregation": "mean", "source": "workflow"},
    "probe_execution": {"mode": "same_run", "producer_stage": "train",
                        "artifact": "probes/probe_seed-{seed}.json",
                        "required_fields": ["signal"]},
    "workflow": {"stages": [{
        "name": "train", "metrics_file": "work/m_seed-{seed}.json",
        "ledger_file": "work/l_seed-{seed}.jsonl",
        "produces": [{"name": "w", "kind": "weights", "uri": "work/ckpt_seed-{seed}.bin"},
                     {"name": "r", "kind": "weights", "uri": "oss://bucket/ckpt.bin"}],
    }]},
}


def landing_claims_full_set() -> None:
    stub = SimpleNamespace(_spec=lambda node: _CLAIM_SPEC)
    claims = eabsorb.AbsorbMixin._landing_claims(
        stub, {"id": "N1"}, "stage", stage="train", replica_seed=7,
        declared_metrics_file="work/m_seed-7.json",
        declared_ledger_file="work/l_seed-7.jsonl")
    check("work/m_seed-7.json" in claims and "work/l_seed-7.jsonl" in claims,
          "declared metrics and ledger are claimed (G4)")
    check("probes/probe_seed-7.json" in claims,
          "the producer probe artifact is claimed for the matching seed")
    check("work/ckpt_seed-7.bin" in claims,
          "seed-resolved declared products are claimed")
    check("oss://bucket/ckpt.bin" in claims,
          "remote product URIs are claimed too (R10-002: registry law makes a "
          "producer URI globally unique, so live attempts serialize on it)")
    check("probes/probe_seed-8.json" not in claims and "work/ckpt_seed-8.bin" not in claims,
          "the sibling seed's landings belong to the sibling attempt")


def landing_claims_repeat_variant() -> None:
    spec = json.loads(json.dumps(_CLAIM_SPEC))
    spec["workflow"]["stages"][0]["metrics_file"] = "work/m.json"
    spec["workflow"]["stages"][0]["produces"][0]["uri"] = "work/ckpt.bin"
    stub = SimpleNamespace(_spec=lambda node: spec)
    claims = eabsorb.AbsorbMixin._landing_claims(
        stub, {"id": "N1"}, "stage", stage="train", replica_seed=9,
        declared_metrics_file="work/m.json", repeat=True)
    check("work/ckpt.bin" in claims,
          "the repeat lane claims the SAME spec-resolved product landing (R10-012: "
          "one resolution rule; the prepare-time archive protects the base bytes)")
    check(all("probe" not in c for c in claims),
          "the repeat lane claims no probe artifacts (probe authority stays with the base)")


# ------------------------------------------------------------------ G6 ----
_KERNEL_CAND = {
    "novelty": {"kind": "composition", "bearer": "the reweighting head",
                "kernel": [{"id": "KC1", "kind": "state_relation",
                            "statement": "counterfactual estimates supervise the head",
                            "operator_refs": ["OP1"]}]},
    "program": {
        "objects": [{"id": "O1", "kind": "input", "semantics": "logged data"},
                    {"id": "O2", "kind": "state", "semantics": "head weights"}],
        "operators": [{"id": "OP1", "kind": "train", "phase": "train",
                       "semantics": "fit the head", "reads": ["O1"], "writes": ["O2"]}],
    },
}


def identity_dual_accept() -> None:
    base = json.loads(json.dumps(_KERNEL_CAND))
    new_hash = eprogram.kernel_fingerprint(base)
    old_hash = eprogram.legacy_kernel_fingerprint(base)
    reclassified = json.loads(json.dumps(base))
    reclassified["novelty"]["kind"] = "irreducible"
    check(eprogram.kernel_fingerprint(reclassified) == new_hash,
          "re-classifying the same computation keeps its identity (G6)")
    check(eprogram.legacy_kernel_fingerprint(reclassified) != old_hash,
          "the legacy algorithm did fold the classification in (why dual-accept exists)")
    renumbered = json.loads(json.dumps(base))
    renumbered["program"]["operators"][0]["id"] = "OP9"
    renumbered["novelty"]["kernel"][0]["operator_refs"] = ["OP9"]
    check(eprogram.kernel_fingerprint(renumbered) == new_hash,
          "consistent renumbering keeps identity (refs resolve to content signatures)")
    check(eprogram.kernel_identity_matches(old_hash, base)
          and eprogram.kernel_identity_matches(new_hash, base),
          "stored hashes from either era keep matching (no migration)")
    check(not eprogram.kernel_identity_matches("deadbeef", base)
          and not eprogram.kernel_identity_matches("", base),
          "a foreign or empty stored hash never matches")


# ------------------------------------------------------------------ G7 ----
def kernel_core_must_be_executable() -> None:
    cand = json.loads(json.dumps(_KERNEL_CAND))
    cand["change_scope"] = "component"
    cand["program"]["objects"].append({"id": "O3", "kind": "state", "semantics": "orphan state"})
    cand["program"]["operators"].append(
        {"id": "OP2", "kind": "train", "phase": "train",
         "semantics": "consumes state no operator produces", "reads": ["O3"], "writes": ["O2"]})
    cand["novelty"]["kernel"][0]["operator_refs"] = ["OP2"]
    errs = eprogram.candidate_errors(cand, where="cand", min_level=0, research=False,
                                     search_origin="repair", model_parent_count=1)
    check(any(e.startswith("PROGRAM_KERNEL_OPERATOR_UNREACHABLE") for e in errs),
          "a core citing a never-executable operator is refused (G7)")
    cand["novelty"]["kernel"][0]["operator_refs"] = ["OP1"]
    errs = eprogram.candidate_errors(cand, where="cand", min_level=0, research=False,
                                     search_origin="repair", model_parent_count=1)
    check(not any(e.startswith("PROGRAM_KERNEL_OPERATOR_UNREACHABLE") for e in errs),
          "citing the executable operator passes the same check")


# ------------------------------------------------------------------ cfg ----
def config_rejects_zero_lane_ceiling() -> None:
    cfg = {"budgets": {"lanes_per_round_min": 1, "lanes_per_round_max": 0}}
    errs = econfig.validate_config(cfg)
    check(any(e.startswith("CONFIG_BUDGET_LANES_CEILING") for e in errs),
          "a 0-lane ceiling is refused at the config layer (rounds could never submit)")
    cfg["budgets"]["lanes_per_round_max"] = 1
    errs = econfig.validate_config(cfg)
    check(not any(e.startswith("CONFIG_BUDGET_LANES_CEILING") for e in errs),
          "a >=1 ceiling passes the same check")


# ------------------------------------------------------------------ sup ----
def supervision_interrupted_record_closes() -> None:
    root = _tmp()
    try:
        cfg_path = root / "config.json"
        cfg_path.write_text(json.dumps({"policy": {"autonomy": "auto"}}), encoding="utf-8")
        recorded: list[dict] = []
        events = [{"event": "autonomy_change_intent", "from": "gated", "to": "auto"}]
        store = SimpleNamespace(
            load_state=lambda: {"config_frozen": True},
            config_path=cfg_path,
            events=lambda: list(events),
            event=lambda actor, name, **kw: recorded.append({"event": name, **kw}),
        )
        rc = evo.cmd_autonomy(store, SimpleNamespace(mode="auto", note="close the torn record"))
        check(rc == 0 and any(r["event"] == "autonomy_changed" and r.get("to") == "auto"
                              for r in recorded),
              "re-running the same switch closes a dangling intent record (sup)")
        events.append({"event": "autonomy_changed", "from": "gated", "to": "auto"})
        recorded.clear()
        rc = evo.cmd_autonomy(store, SimpleNamespace(mode="auto", note="nothing dangling now"))
        check(rc == 0 and recorded == [],
              "a completed record is not double-closed on a second re-run")
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------ W3 ----
def repeat_landing_resolution_unified() -> None:
    # R10-012 reconciliation: there is deliberately NO repeat-specific landing
    # derivation - every attempt resolves through resolve_seed_template, so
    # the frozen command, the expected landings, the product acceptance and
    # the registration can never disagree.
    check(not hasattr(econfig, "resolve_repeat_landing"),
          "the repeat-specific derivation function is gone (one rule per attempt)")
    f = econfig.resolve_seed_template
    check(f("work/m_seed-{seed}.json", 9) == "work/m_seed-9.json",
          "a {seed} template resolves the same for every lane")
    check(f("work/metrics.json", 9) == "work/metrics.json",
          "a literal single-run path stays the spec's own landing for the repeat too")


def probe_expectations_repeat_exempt() -> None:
    stub = SimpleNamespace(_spec=lambda node: _CLAIM_SPEC)
    is_p, expected = eabsorb.AbsorbMixin._probe_expectations(
        stub, {"kind": "stage", "stage": "train", "replica_seed": 7}, {"id": "N1"})
    check(is_p and len(expected) == 1 and expected[0]["seed"] == 7,
          "an ordinary producer stage keeps its seed-filtered probe expectations")
    is_p, expected = eabsorb.AbsorbMixin._probe_expectations(
        stub, {"kind": "stage", "stage": "train", "replica_seed": 9,
               "repeat_measure_attempt": True}, {"id": "N1"})
    check(is_p is False and expected == [],
          "the repeat lane is never a probe producer - the SAME predicate every "
          "consumer (claims/archive/ingest/seal/probe-gap disposition) judges by")


def repeat_pending_predicate() -> None:
    f = eabsorb.AbsorbMixin._repeat_run_pending
    check(f({"repeat_measure": {"engine_run": True}, "repeat_pending_seed": 9}) == 9,
          "an armed approval exposes the pending seed (R9-002)")
    check(f({"repeat_measure": {"engine_run": True}}) is None,
          "no pending seed -> nothing owed (already executed or legacy)")
    check(f({"repeat_measure": {"waived": True}, "repeat_pending_seed": 9}) is None,
          "a waived approval owes nothing")
    check(f({"repeat_measure": {}, "repeat_measure_done": True,
             "repeat_pending_seed": 9}) is None,
          "a settled approval owes nothing")
    check(f({}) is None, "no approval at all owes nothing")


_ADV_SPEC = {
    "training_replication": {"mode": "preplanned", "runs": 2, "seeds": [7, 8],
                             "aggregation": "mean", "source": "workflow"},
    "workflow": {"stages": [{"name": "train", "metrics_file": "work/m.json"}]},
}


def _advance_stub(node: dict, events: list) -> SimpleNamespace:
    stub = SimpleNamespace(
        _spec=lambda n: _ADV_SPEC,
        _register_stage_artifacts=lambda *a, **k: None,
        store=SimpleNamespace(event=lambda actor, name, **kw: events.append(name)),
    )
    # R11-001: _advance_stage routes registration through the deferral
    # helper; bind the REAL one so repeat lanes exercise deferral semantics.
    stub._register_or_defer_stage_products = (
        lambda *a, **k: eabsorb.AbsorbMixin._register_or_defer_stage_products(stub, *a, **k))
    return stub


def advance_stage_repeat_no_reloop() -> None:
    events: list = []
    node = {"id": "N1", "stage_cursor": 0, "replica_index": 1, "status": "executing",
            "repeat_measure": {"engine_run": True}, "repeat_pending_seed": 9,
            "eval_done": True}
    run = {"id": "RUN9", "repeat_measure_attempt": True, "replica_seed": 9}
    eabsorb.AbsorbMixin._advance_stage(_advance_stub(node, events), node, run,
                                       gate_decision=None)
    check(node["status"] == "workflow_done" and node["stage_cursor"] == 1,
          "the repeat lane finishes to workflow_done (R9-002)")
    check(node["replica_index"] == 1 and "workflow_replica_finished" not in events,
          "the repeat lane NEVER re-enters the preplanned seed loop")
    rows = node.get("replicas_completed") or []
    check(len(rows) == 1 and rows[0].get("seed") == 9 and rows[0].get("repeat_measure") is True,
          "the repeat completion is recorded and marked beside the planned rows")
    check("repeat_workflow_finished" in events,
          "the repeat lane announces its own completion event")


def advance_stage_planned_loop_unchanged() -> None:
    events: list = []
    node = {"id": "N1", "stage_cursor": 0, "replica_index": 0, "status": "executing"}
    run = {"id": "RUN1", "replica_seed": 7, "replica_index": 0}
    eabsorb.AbsorbMixin._advance_stage(_advance_stub(node, events), node, run,
                                       gate_decision=None)
    check(node["status"] == "stage_ready" and node["replica_index"] == 1
          and node["stage_cursor"] == 0 and "workflow_replica_finished" in events,
          "an ordinary replica still advances to the next preplanned seed lane")


def metric_door_three_states() -> None:
    root = _tmp()
    try:
        eutil.write_json_atomic(root / "base_raw.json", {"auc": 0.80})
        eutil.write_json_atomic(root / "repeat_raw.json", {"auc": 0.82})
        st = {"runs": [
            {"id": "RUN1", "kind": "eval", "metrics_file": "base_raw.json"},
            {"id": "RUN9", "kind": "eval", "metrics_file": "repeat_raw.json"},
        ]}
        ctx = SimpleNamespace(store=SimpleNamespace(repo=root), st=st,
                              reg={"artifacts": []})
        rm = {"result_key": "auc", "base_seed": 7, "seed": 9, "engine_run": True,
              "gate": "G1"}

        def block(rep_value, rep_source):
            return {"value": round((0.80 + rep_value) / 2, 9), "training_replication": {
                "aggregation": "mean",
                "runs": [{"seed": 7, "value": 0.80, "source": "base_raw.json"},
                         {"seed": 9, "value": rep_value, "source": rep_source}]}}

        pending_node = {"id": "N1", "repeat_measure": rm, "eval_run": "RUN1"}
        errs = evalid.metric_evidence_errors(ctx, "auc", block(0.82, "repeat_raw.json"),
                                             node=pending_node)
        check(any(e.startswith("EVAL_REPEAT_RUN_PENDING") for e in errs),
              "an engine-run approval refuses aggregation before the repeat RUN settles (W3)")

        settled = {"id": "N1", "repeat_measure": rm, "eval_run": "RUN1",
                   "repeat_eval_run": "RUN9"}
        errs = evalid.metric_evidence_errors(ctx, "auc", block(0.82, "repeat_raw.json"),
                                             node=settled)
        check(errs == [], f"a correct sealed aggregate passes: {errs}")
        errs = evalid.metric_evidence_errors(ctx, "auc", block(0.83, "repeat_raw.json"),
                                             node=settled)
        check(any(e.startswith("EVAL_REPEAT_MEASURE_REPEAT_MISMATCH") for e in errs),
              "the repeat row is pinned to the sealed repeat measurement")
        errs = evalid.metric_evidence_errors(ctx, "auc", block(0.82, "elsewhere.json"),
                                             node=settled)
        check(any(e.startswith("EVAL_REPEAT_SOURCE_RUN") for e in errs),
              "the repeat row must cite the sealed repeat RUN, not an arbitrary artifact")
        errs = evalid.metric_evidence_errors(ctx, "auc", block(0.82, "RUN9"),
                                             node=settled)
        check(not any(e.startswith("EVAL_REPEAT_SOURCE_RUN") for e in errs),
              "citing the RUN id is the accepted alternative spelling")
        base_off = block(0.82, "repeat_raw.json")
        base_off["training_replication"]["runs"][0]["value"] = 0.81
        base_off["value"] = round((0.81 + 0.82) / 2, 9)
        errs = evalid.metric_evidence_errors(ctx, "auc", base_off, node=settled)
        check(any(e.startswith("EVAL_REPEAT_MEASURE_BASE_MISMATCH") for e in errs),
              "the base row stays pinned to the sealed first measurement too")

        legacy_rm = {k: v for k, v in rm.items() if k != "engine_run"}
        legacy = {"id": "N1", "repeat_measure": legacy_rm, "eval_run": "RUN1"}
        errs = evalid.metric_evidence_errors(ctx, "auc", block(0.82, "missing_artifact.json"),
                                             node=legacy)
        check(any(e.startswith("EVAL_REPEAT_SOURCE_MISSING") for e in errs),
              "a legacy (pre-engine-run) approval keeps the checkable-citation rule")
        errs = evalid.metric_evidence_errors(ctx, "auc", block(0.82, "repeat_raw.json"),
                                             node=legacy)
        check(not any("EVAL_REPEAT" in e for e in errs),
              "a legacy aggregate with an existing citation still passes untouched")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def stage_metrics_keys_repeat_lane() -> None:
    root = _tmp()
    try:
        eutil.write_json_atomic(root / "m_base.json", {"summary": {"loss": 0.10}})
        eutil.write_json_atomic(root / "m_rep.json", {"summary": {"loss": 0.12}})
        st = {"runs": [
            {"id": "RUN1", "node": "N1", "kind": "stage", "stage": "train",
             "status": "finished", "adoption_status": "adopted",
             "metrics_file": "m_base.json", "replica_seed": 7, "replica_total": 1},
            {"id": "RUN9", "node": "N1", "kind": "stage", "stage": "train",
             "status": "finished", "adoption_status": "adopted",
             "metrics_file": "m_rep.json", "replica_seed": 9,
             "repeat_measure_attempt": True},
        ]}
        ctx = SimpleNamespace(store=SimpleNamespace(repo=root), st=st)
        out = evalid.stage_metrics_of(ctx, "N1")
        check(set(out) == {"train", "seed=9/train"},
              f"the repeat lane's rows key by seed and never shadow the base: {sorted(out)}")
        check(out["train"]["loss"] == 0.10 and out["seed=9/train"]["loss"] == 0.12,
              "both attempts' numbers stay visible to the analysis")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def invariants_admit_repeat_lane() -> None:
    def fresh(repeat: bool) -> dict:
        run = {"id": "RUN9", "node": "N1", "kind": "stage", "stage": "train",
               "contract_digest": "c1", "stage_index": 0,
               "replica_index": None, "replica_seed": 9}
        if repeat:
            run["repeat_measure_attempt"] = True
        erun.initialize_run(run)
        return run

    errs = [e for e in erun.invariant_errors(fresh(repeat=True))
            if e.startswith("RUN_POSITION")]
    check(errs == [], "the repeat lane's missing replica ordinal is legal (R9-002)")
    errs = [e for e in erun.invariant_errors(fresh(repeat=False))
            if e.startswith("RUN_POSITION")]
    check(len(errs) == 1 and "replica_index" in errs[0],
          "an ordinary stage RUN still requires its replica ordinal")


def main() -> None:
    terminal_blockers_three_kinds()
    landing_claims_full_set()
    landing_claims_repeat_variant()
    identity_dual_accept()
    kernel_core_must_be_executable()
    config_rejects_zero_lane_ceiling()
    supervision_interrupted_record_closes()
    repeat_landing_resolution_unified()
    probe_expectations_repeat_exempt()
    repeat_pending_predicate()
    advance_stage_repeat_no_reloop()
    advance_stage_planned_loop_unchanged()
    metric_door_three_states()
    stage_metrics_keys_repeat_lane()
    invariants_admit_repeat_lane()
    done("V11.4 R9 FIX REGRESSIONS")


if __name__ == "__main__":
    main()
