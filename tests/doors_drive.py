"""Doors drive: full-lifecycle E2E for the composite paths the unit suites
cannot reach - the class where green unit walls hide deadlocks.

    python tests/doors_drive.py

Own workspace (tests/out/proj_doors), research mode + git + sota, scaling
budgeted, wildcat cadence 7 (past the scenario rounds). Scenarios:
  R001  parent candidate registering follow-up scaling (positive verdict)
  R002  scaling follow-up lane (carbon copy, manual idea gate, comparator=parent);
        the copy's deferred mechanism opens the tax, the reviewer declines it
  R003  exploratory scout (no predictions/SOTA/probe; observations only;
        off both frontiers; promotion not_applicable)
  R004  confirmatory re-run of the scout's kernel (full rigor, kernel-dup
        exemption, lands on the record)
  R005  repeat-measure: on-the-line eval -> protected gate -> approve ->
        bundle duty block -> 2-run aggregate settles ONCE; then the
        inheritance tax: the deferred win's conclusion opens its ablation lane
        inside the round -> design -> review -> gate(s) -> one run -> conclude
        -> the parent's mechanism is confirmed via the ablation -> doctor clean

Every stage runs the real scheduler/validators; drives are exclusive
(never run in parallel with mock/stress - shared tests/out).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))

import mock_drive as M                                    # noqa: E402
from mock_drive import (                                  # noqa: E402
    D, ok, section, nx, sub_ok, wj, wt, long, md, open_round, exploit_lane,
    drive_lane_to_plan, drive_plan, drive_node_to_training,
    drive_watch_finish, drive_eval_conclude, drive_close, evidence_refresh,
    w_mature, w_red_team, w_tournament, w_conclude, preds_for,
    stage, dyn_sections, planned_resource_measurements, L2_DIMS, rmtree, make_repo)
import econfig     # noqa: E402
import egraph      # noqa: E402
import evalid      # noqa: E402

PY = sys.executable
PKG = HERE.parent

SCALING_REG = {
    "axis": "data",
    "points": ["10pct", "100pct"],
    "expect": long(35, "the counterfactual gain grows with data because rare levels densify"),
    "value_of_information": long(65, "whether the mechanism holds at full data decides if the lineage becomes the deployment architecture"),
    "execution": "followup_node",
    "trigger": "after_positive_signal",
    "costly_arms": 1,
}


def decide_gate(d, *, kinds=None, approve=True, note=None):
    """Next MUST be a user gate (manual doors are the point); decide it."""
    out = d.next()
    ok(out.get("kind") == "gate", f"expected a MANUAL gate, got {out}")
    st_gate = next(g for g in d.state()["gates"] if g["id"] == out["gate"])
    if kinds:
        ok(st_gate.get("kind") in kinds, f"expected gate kind in {kinds}, got {st_gate.get('kind')}")
    r = d.decide(out["gate"], approve, note=note or "doors drive: user approves the copy spend")
    ok(r.get("kind") in ("decided", "accepted", "ok") or r is not None, f"decide failed: {r}")
    return st_gate


def run_node_pipeline(d, lid, *, parent, score, stages_key, manual_gates,
                      observations=None):
    """gate(s) -> plan -> implement -> train -> eval -> conclude for one lane."""
    if manual_gates:
        decide_gate(d, kinds=("idea_approval",))
    nid = drive_plan(d, lid, role="variant", code_parent=parent, stages=[
        stage("train", uri=f"oss://bkt/user/{stages_key}-train/checkpoint.zip",
              key=f"train|{stages_key}")])
    # Carbon/scout lanes now ALWAYS get a manual workflow gate, even in
    # full_auto (delivery logic fix: creation finally matches the table and
    # the CLI promise). The gate materializes when the node reaches launch -
    # AFTER implement/smoke/fidelity - so inline those steps and peek there.
    out = nx(d, "implement")
    M.do_implement(d, out, nid)
    sub_ok(d, out)
    out = nx(d, "smoke")
    res = d.smoke(nid)
    ok(res["status"] == "pass", f"smoke for {nid} should pass: {res}")
    sub_ok(d, out)
    M.maybe_fidelity(d, nid)
    peek = d.next()
    if peek.get("kind") == "gate":
        st_gate = next(g for g in d.state()["gates"] if g["id"] == peek["gate"])
        ok(st_gate.get("kind") == "workflow_approval",
           f"unexpected gate kind before training: {st_gate.get('kind')}")
        d.decide(peek["gate"], True, note="doors drive: workflow spend approved (carbon/scout door)")
    out = nx(d, "stage_launch")
    launch_stage = d.state()["tasks"][-1]["subject"]["stage"]
    M.w_launch(d, out, launch_stage, job="job-bg")
    sub_ok(d, out)
    run_id = M.last_run(d)["id"]
    drive_watch_finish(d, run_id, nid, "train")
    if observations is None:
        drive_eval_conclude(d, nid, score)
    else:
        out = nx(d, "evaluate")
        M.w_eval(d, out, nid, score)
        sub_ok(d, out)
        out = nx(d, "conclude")
        # Observation evidence must bind an existing
        # source; the node id exists only here, so resolve the sentinel now
        for row in observations:
            if row.get("evidence") == "__node_eval_metrics__":
                row["evidence"] = f".evo/nodes/{nid}/eval/metrics.json"
        w_conclude(d, out, nid, observations=observations)
        sub_ok(d, out)
    return nid


def carbon_sketch(d, lid, source_batch, source_winner, *, kind, comparator):
    """Submit the ONE-program carbon-copy batch for a followup/confirmatory lane.

    Clones the source lane's ENTIRE frozen batch file (schema/version/digest
    header included), keeps only the winner, and rebinds the lane-local
    fields - the kernel payload itself stays verbatim."""
    out = nx(d, "sketch")
    lane = d.lane(lid)
    batch = {k: v for k, v in json.loads(json.dumps(source_batch)).items() if k != "sketches"}
    batch["lane"] = lid
    batch["search_origin"] = str(lane.get("search_origin") or "repair")
    cand = json.loads(json.dumps(source_winner))
    cand["sketch_id"] = "K1"
    cand["novelty"]["kind"] = kind
    cand.setdefault("effect_case", {})["comparator_id"] = comparator
    cand.setdefault("program", {})["scientific_parents"] = [comparator]
    for obj in (batch, cand):
        for key in list(obj.keys()):
            if "diagnosis" in key and lane.get("diagnosis_digest"):
                obj[key] = lane["diagnosis_digest"]
    batch["sketches"] = [cand]
    wj(d.repo, out["outputs"][0], batch)
    sub_ok(d, out)
    return cand


def main():
    M.OUT.mkdir(parents=True, exist_ok=True)
    repo = M.OUT / "proj_doors"
    if repo.exists():
        rmtree(repo)
    make_repo(repo, with_git=True)
    evo = PKG / "engine" / "evo.py"
    p = subprocess.run([PY, str(evo), "--repo", str(repo), "init",
                        "--project-name", "fake-bfr", "--goal", "beat baseline auc"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(p.returncode == 0, f"CLI init: {p.stderr}")
    d = D(repo)

    # Same bootstrap as the mock, with ONE config difference: scaling budgeted.
    orig_cfg_main = M.w_config_main

    def cfg_with_scaling(d2, out2, **kw):
        kw.setdefault("scaling_probe", True)
        r = orig_cfg_main(d2, out2, **kw)
        # serial single-lane choreography: push the wildcat cadence past the
        # five scenario rounds (research floors demand >= 1, so 7, not 0)
        cfg_path = d2.repo / ".evo/config.json"
        c2 = json.loads(cfg_path.read_text(encoding="utf-8"))
        c2["policy"]["wildcat_every_rounds"] = 7
        cfg_path.write_text(json.dumps(c2, indent=1), encoding="utf-8")
        return r

    M.w_config_main = cfg_with_scaling
    try:
        M.run_bootstrap(d)
    finally:
        M.w_config_main = orig_cfg_main
    cfg = d.store().load_config()
    ok(econfig.scaling_mode(cfg) == "budgeted", "workspace runs scaling_mode=budgeted")
    baseline = next(n for n in d.graph()["nodes"] if n.get("role") == "baseline")
    base_id, base_auc = baseline["id"], float(econfig.result_value(baseline["scores"]["auc"]))

    # ------------------------------------------------------------- R001 ----
    section("DOORS R001: parent candidate pre-registers follow-up scaling")
    open_round(d, "R001", [exploit_lane("scale-parent", base_id)])
    out = nx(d, "evidence")
    M.w_evidence_initial(d)
    sub_ok(d, out)
    lid, mech = drive_lane_to_plan(d, "scale-parent", dims=L2_DIMS)
    out = nx(d, "mature")
    w_mature(d, out, lid, mech_ids=mech, preds=preds_for(base_auc + 0.02),
             scaling=SCALING_REG)
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, lid)
    sub_ok(d, out)
    p1 = run_node_pipeline(d, lid, parent=base_id, score=base_auc + 0.02,
                           stages_key="scale-parent", manual_gates=False)
    ok(d.node(p1).get("verdict") == "improved", f"parent concluded positive: {d.node(p1).get('verdict')}")
    parent_meta = json.loads((d.repo / f".evo/ideas/{d.lane(lid)['idea']}.meta.json")
                             .read_text(encoding="utf-8"))
    ok((parent_meta.get("scaling") or {}).get("execution") == "followup_node",
       "the scaling plan is registered in the parent's sealed meta")
    parent_sketches = json.loads((d.repo / d.lane(lid)["sketches_path"]).read_text(encoding="utf-8"))
    parent_winner = next(s for s in parent_sketches["sketches"]
                         if s["sketch_id"] == d.lane(lid)["winner_sketch"])
    drive_close(d, "R001")

    # ------------------------------------------------------------- R002 ----
    section("DOORS R002: scaling follow-up (carbon copy, manual gate)")
    p1_score = float(econfig.result_value(d.node(p1)["scores"]["auc"]))
    open_round(d, "R002", [
        dict(exploit_lane("scale-up", p1), scaling_followup_of=p1),
    ])
    evidence_refresh(d)

    # follow-up lane: diagnosis auto-answered, deep_read, then the ONE-copy batch
    fu = d.lane_by_name("scale-up")
    lid_fu, mech_fu = None, []
    while d.lane(fu["id"]).get("status") in ("diagnose", "deep_read"):
        out = nx(d, "deep_read")
        mech_fu += M.w_mech_cards(d, fu["id"], 2, ["E001", "E005"])
        sub_ok(d, out)
    lid_fu = fu["id"]
    carbon_sketch(d, lid_fu, parent_sketches, parent_winner, kind="scaling_extension", comparator=p1)
    out = nx(d, "tournament")
    w_tournament(d, out, lid_fu, "K1")
    sub_ok(d, out)
    ok(d.lane(lid_fu).get("winner_sketch") == "K1", "the single copy is the winner")
    out = nx(d, "mature")
    w_mature(d, out, lid_fu, mech_ids=mech_fu, preds=preds_for(p1_score + 0.015))
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, lid_fu)
    sub_ok(d, out)
    fu_node = run_node_pipeline(d, lid_fu, parent=p1, score=p1_score + 0.015,
                                stages_key="scale-up", manual_gates=True)
    ok(d.node(fu_node).get("verdict") == "improved",
       f"the follow-up concluded against its parent comparator: {d.node(fu_node).get('verdict')}")
    # The copy registers no instrument of its own, so its mechanism settles
    # deferred and the engine opens the tax inside R002. The causal reviewer
    # may decline it (the story was settled on the original kernel): the lane
    # abandons before any gate or compute and the round is free to close.
    fu_abl = d.node(fu_node).get("ablation_lane")
    ok(fu_abl and d.node(fu_node).get("mechanism_status") == "deferred"
       and d.lane(fu_abl).get("status") == "ablation_design" and d.lane(fu_abl).get("round") == "R002",
       f"a deferred win in R002 opened its ablation lane in R002: {fu_abl}")
    out = nx(d, "design_ablation")
    M.w_design_ablation(d, out, fu_abl)
    sub_ok(d, out)
    out = nx(d, "review_ablation")
    M.w_review_ablation(d, out, fu_abl, verdict="REJECT_NOT_WORTH_COST")
    sub_ok(d, out)
    ok(d.lane(fu_abl).get("status") == "abandoned" and d.lane(fu_abl).get("node") is None
       and d.node(fu_node).get("mechanism_status") == "deferred",
       "a declined tax abandons the lane before compute and leaves the mechanism deferred")
    drive_close(d, "R002")

    # ------------------------------------------------------------- R003 ----
    section("DOORS R003: exploratory scout (no predictions, observations only)")
    open_round(d, "R003", [
        dict(exploit_lane("scout", p1), experiment_purpose="exploratory"),
    ])
    evidence_refresh(d)
    # scout lane: full candidate route, novelty duties intact, NO predictions
    lid_sc, mech_sc = drive_lane_to_plan(d, "scout", dims=L2_DIMS)
    out = nx(d, "mature")
    w_mature(d, out, lid_sc, mech_ids=mech_sc, preds=[])
    sub_ok(d, out)
    scout_meta = json.loads((d.repo / f".evo/ideas/{d.lane(lid_sc)['idea']}.meta.json")
                            .read_text(encoding="utf-8"))
    ok(scout_meta.get("experiment_purpose") == "exploratory"
       and not scout_meta.get("predictions") and not scout_meta.get("sota_targets"),
       "the scout matured WITHOUT predictions or SOTA targets - and validated")
    out = nx(d, "red_team")
    w_red_team(d, out, lid_sc)
    sub_ok(d, out)
    sc_node = run_node_pipeline(
        d, lid_sc, parent=p1, score=p1_score + 0.03, stages_key="scout",
        manual_gates=True,
        observations=[{
            "statement": long(35, "the reweighted objective moves rare-level auc far above the lineage trend"),
            "where": "rare price levels of the frozen validation split",
            "measurement": long(15, "auc lift observed on the scouting run"),
            "evidence": "__node_eval_metrics__"}])
    scout_sketches = json.loads((d.repo / d.lane(lid_sc)["sketches_path"]).read_text(encoding="utf-8"))
    scout_winner = next(s for s in scout_sketches["sketches"]
                        if s["sketch_id"] == d.lane(lid_sc)["winner_sketch"])
    cfg_now = d.store().load_config()
    st_now = d.state()
    fr = {n["id"] for n in egraph.frontier(d.graph(), cfg_now, st_now)}
    perf = {n["id"] for n in egraph.performance_frontier(d.graph(), cfg_now, st_now)}
    ok(sc_node not in fr and sc_node not in perf,
       f"the scout's better number stays OFF both frontiers: fr={sorted(fr)}")
    ok(d.node(sc_node).get("scientific_promotion_status") == "not_applicable",
       f"scout promotion pinned: {d.node(sc_node).get('scientific_promotion_status')}")
    obs = [o for o in d.store().observations(d.state(), active_only=True)
           if o.get("node") == sc_node]
    ok(bool(obs), "the scout's conclusion emitted phenomenon-ledger observations")
    drive_close(d, "R003")

    # ------------------------------------------------------------- R004 ----
    section("DOORS R004: confirmatory re-run of the scout's kernel (full rigor)")
    fu_score = float(econfig.result_value(d.node(fu_node)["scores"]["auc"]))
    open_round(d, "R004", [
        dict(exploit_lane("confirm", fu_node), confirmatory_of=sc_node),
    ])
    evidence_refresh(d)
    cf = d.lane_by_name("confirm")
    mech_cf = []
    while d.lane(cf["id"]).get("status") in ("diagnose", "deep_read"):
        out = nx(d, "deep_read")
        mech_cf += M.w_mech_cards(d, cf["id"], 2, ["E001", "E005"])
        sub_ok(d, out)
    lid_cf = cf["id"]
    carbon_sketch(d, lid_cf, scout_sketches, scout_winner, kind=str(scout_winner["novelty"]["kind"]), comparator=fu_node)
    out = nx(d, "tournament")
    w_tournament(d, out, lid_cf, "K1")
    sub_ok(d, out)
    out = nx(d, "mature")
    w_mature(d, out, lid_cf, mech_ids=mech_cf, preds=preds_for(fu_score + 0.01))
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, lid_cf)
    sub_ok(d, out)
    cf_node = run_node_pipeline(d, lid_cf, parent=fu_node, score=fu_score + 0.01,
                                stages_key="confirm", manual_gates=True)
    cfg_now = d.store().load_config()
    perf = {n["id"] for n in egraph.performance_frontier(d.graph(), cfg_now, d.state())}
    ok(cf_node in perf,
       f"the CONFIRMED effect now legally holds the record the scout could not: {sorted(perf)}")
    drive_close(d, "R004")

    # ------------------------------------------------------------- R005 ----
    section("DOORS R005: repeat-measure - on-the-line eval buys exactly one repeat")
    cf_score = float(econfig.result_value(d.node(cf_node)["scores"]["auc"]))
    # R005 serves the starved D1 direction from a single-lane round: the one
    # starvation-forced lane rides outside the focus share cap - this drive
    # is the e2e proof of that composition.
    open_round(d, "R005", [exploit_lane("edge", cf_node, focus="D1")])
    evidence_refresh(d)
    lid_e, mech_e = drive_lane_to_plan(d, "edge", dims=L2_DIMS)
    out = nx(d, "mature")
    w_mature(d, out, lid_e, mech_ids=mech_e, preds=preds_for(cf_score + 0.001),
             waiver=True, meta_extra={"repeat_rule": {"cell": "C1", "band": 0.02,
                                         "when": "decision_within_band", "max_repeats": 1}})
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, lid_e)
    sub_ok(d, out)
    e_node = drive_plan(d, lid_e, role="variant", code_parent=cf_node, stages=[
        stage("train", uri="oss://bkt/user/edge-train/checkpoint.zip", key="train|edge")])
    run_id = drive_node_to_training(d, e_node)
    drive_watch_finish(d, run_id, e_node, "train")

    # eval lands ON the line: raw single value = parent + 0.002 inside band 0.02
    on_line = round(cf_score + 0.002, 4)
    out = nx(d, "evaluate")            # deferred eval_launch
    ok(out.get("_deferred_evaluate"), f"expected deferred eval launch, got {out}")
    logloss = 0.6 - max(0.0, on_line - 0.7)
    raw_m = {"auc": on_line, "logloss": logloss, "latency_ms": 100.0,
             "_usage": {"wallclock_minutes": 1.0},
             "_resource_measurements": planned_resource_measurements(d, e_node)}
    raw_rel = f".evo/nodes/{e_node}/eval/raw_metrics_r1.json"
    wj(d.repo, raw_rel, raw_m)
    task = next(t for t in d.state()["tasks"] if t["id"] == out["task"])
    run = next(r for r in d.state()["runs"] if r["id"] == task["subject"]["run"])
    wj(d.repo, out["outputs"][0], {"run": run["id"], "attempt_token": run["attempt_token"],
                                   "mode": "completed", "metrics_file": raw_rel})
    accepted = d.submit(out["task"])
    ok(accepted.get("kind") == "accepted", f"on-the-line eval run must absorb: {accepted}")

    gate = decide_gate(d, kinds=("repeat_measure",))
    subj = gate.get("subject") or {}
    ok(subj.get("cell") == "C1" and abs(float(subj.get("delta")) - 0.002) < 1e-9,
       f"the offer names the registered cell and the true delta: {subj}")
    rm = d.node(e_node).get("repeat_measure") or {}
    ok(rm.get("result_key") == "auc", f"approval stamped the duty onto the node: {rm}")
    # Approval hands the repeat to the ENGINE - the node re-enters the
    # workflow as a first-class repeat lane with the fresh seed.
    ok(rm.get("engine_run") is True
       and d.node(e_node).get("repeat_pending_seed") == rm.get("seed"),
       f"approval arms the engine-run repeat lane: {rm}")
    ok(d.node(e_node).get("status") == "stage_ready",
       f"the node re-enters the workflow for the repeat: {d.node(e_node).get('status')}")

    # repeat training: a real prepared RUN (token, slot, lease, ledger charge)
    out = nx(d, "stage_launch")
    task = next(t for t in d.state()["tasks"] if t["id"] == out["task"])
    ok(task["subject"].get("repeat_measure") is True
       and task["subject"].get("replica_seed") == rm.get("seed"),
       f"the repeat stage launch binds the fresh seed: {task['subject']}")
    M.w_launch(d, out, "train", job="job-repeat-train")
    sub_ok(d, out)
    repeat_train = M.last_run(d)
    ok(repeat_train.get("repeat_measure_attempt") is True
       and repeat_train.get("replica_seed") == rm.get("seed"),
       f"the repeat training is a first-class engine RUN: {repeat_train.get('id')}")
    drive_watch_finish(d, repeat_train["id"], e_node, "train")
    ok(d.node(e_node).get("status") == "workflow_done"
       and d.node(e_node).get("eval_done") is True,
       "the repeat workflow finished without disturbing the settled base eval bit")

    # repeat evaluation: its own engine RUN, landing beside the sealed base
    out = d.next()
    ok(out.get("kind") == "task" and out.get("type") == "eval_launch",
       f"the repeat evaluation launch presents: {out}")
    task = next(t for t in d.state()["tasks"] if t["id"] == out["task"])
    ok(task["subject"].get("repeat_measure") is True,
       f"the repeat eval launch is marked as the buy-back lane: {task['subject']}")
    rrun = next(r for r in d.state()["runs"] if r["id"] == task["subject"]["run"])
    ok(rrun.get("repeat_measure_attempt") is True and rrun.get("replica_seed") == rm.get("seed"),
       f"the repeat eval RUN carries the fresh seed in its slot: {rrun.get('id')}")
    run2_val = round(on_line + 0.012, 4)
    # The repeat eval lands at the evaluation's OWN declared landing
    # (one resolution rule for every attempt); identity is enforced, and the
    # base leftover bytes there were archived when the repeat RUN was prepared
    raw2_rel = str(rrun.get("declared_metrics_file"))
    ok(raw2_rel == f".evo/nodes/{e_node}/eval/raw_metrics.json",
       f"the repeat eval RUN declares the evaluation's own landing: {raw2_rel}")
    wj(d.repo, raw2_rel, {"auc": run2_val, "logloss": logloss, "latency_ms": 100.0,
                          "_usage": {"wallclock_minutes": 1.0},
                          "_resource_measurements": planned_resource_measurements(d, e_node)})
    # landing identity: pointing the repeat at the BASE landing is refused
    wj(d.repo, out["outputs"][0], {"run": rrun["id"], "attempt_token": rrun["attempt_token"],
                                   "mode": "completed", "metrics_file": raw_rel})
    r = d.submit(out["task"])
    ok(r.get("kind") == "rejected"
       and any(e.startswith("EVAL_LAUNCH_REPEAT_LANDING") for e in r["errors"]),
       f"the repeat eval may never report over the base landing: {r}")
    wj(d.repo, out["outputs"][0], {"run": rrun["id"], "attempt_token": rrun["attempt_token"],
                                   "mode": "completed", "metrics_file": raw2_rel})
    accepted = d.submit(out["task"])
    ok(accepted.get("kind") == "accepted", f"the repeat eval run must absorb: {accepted}")
    node_now = d.node(e_node)
    base_eval_run = str(node_now.get("eval_run") or "")
    ok(node_now.get("repeat_eval_run") == rrun["id"] and base_eval_run
       and base_eval_run != rrun["id"] and node_now.get("repeat_pending_seed") is None,
       f"the repeat eval settled BESIDE the base eval, never over it: "
       f"base={base_eval_run} repeat={node_now.get('repeat_eval_run')}")

    analyst = d.next()
    ok(analyst.get("kind") == "task" and analyst.get("type") == "evaluate",
       f"after the repeat settled the analyst task presents: {analyst}")
    bundle = (d.repo / f".evo/tasks/{analyst['task']}/BUNDLE.md").read_text(encoding="utf-8")
    ok("APPROVED repeat measurement" in bundle,
       "the evaluation bundle carries the repeat duty block")
    ok("engine-run" in bundle,
       "the duty block describes the engine-run buy-back (aggregate only, no re-run)")
    mean = round((on_line + run2_val) / 2, 6)
    base_run_row = next(r for r in d.state()["runs"] if r["id"] == base_eval_run)
    rep_run_row = next(r for r in d.state()["runs"] if r["id"] == node_now["repeat_eval_run"])
    m = {"auc": {"value": mean, "training_replication": {
            "aggregation": "mean",
            "runs": [{"seed": rm.get("base_seed"), "value": on_line,
                      "source": str(base_run_row.get("metrics_file"))},
                     {"seed": rm.get("seed"), "value": run2_val,
                      "source": str(rep_run_row.get("metrics_file"))}]}},
         "logloss": logloss, "latency_ms": 100.0, "_usage": {"wallclock_minutes": 1.0}}
    wj(d.repo, analyst["outputs"][0], m)
    wt(d.repo, analyst["outputs"][1], md(
        ("Setup", long(60, "eval ran on the frozen split with the shared metric code")),
        ("Results", long(100, f"C1 ranking auc mean {mean} of two approved runs against goal 0.80; "
                              f"C2 calibration logloss {logloss}; C3 latency 100.0 ms")),
        *dyn_sections(d, e_node),
        ("Anomalies", long(50, "NONE - curves, rare level slices and output samples were checked")),
        ("Comparability", long(60, "V1 same frozen split and V2 same metric code were checked"))))
    sub_ok(d, analyst)
    ok(d.node(e_node).get("repeat_measure_done") is True,
       "the aggregate settled the repeat exactly once")
    out = nx(d, "conclude")
    w_conclude(d, out, e_node)
    accepted = sub_ok(d, out)
    ok(d.node(e_node).get("verdict") == "improved",
       f"verdict settled on the two-run mean: {d.node(e_node).get('verdict')}")
    rm_gates = [g for g in d.state()["gates"] if g.get("kind") == "repeat_measure"
                and (g.get("subject") or {}).get("node") == e_node]
    ok(len(rm_gates) == 1, f"exactly one offer ever existed for the node: {len(rm_gates)}")

    # ------------------------------------------------- R005: inheritance tax ----
    section("DOORS R005 (cont.): deferred win -> engine-opened ablation -> parent settled")
    e_now = d.node(e_node)
    ok(e_now.get("mechanism_status") == "deferred" and e_now.get("scientific_promotion_status") == "met",
       f"the waiver left the mechanism deferred on a promoted win: {e_now.get('mechanism_status')}")
    abl_lid = e_now.get("ablation_lane")
    advice = accepted.get("advice") or []
    ok(bool(abl_lid) and any(abl_lid in line for line in advice)
       and "inheritance tax" in " ".join(advice),
       f"the ACCEPTED advice names the ablation lane the engine opened: {advice}")
    abl = d.lane(abl_lid)
    ok(abl.get("experiment_purpose") == "targeted_ablation" and abl.get("status") == "ablation_design"
       and abl.get("parents") == [e_node] and abl.get("round") == "R005"
       and abl.get("name") == f"ablate-{e_node.lower()}",
       f"the lane rides inside R005 on the winner: {abl}")
    ok((d.repo / abl["brief_md"]).is_file()
       and e_node in (d.repo / abl["brief_md"]).read_text(encoding="utf-8"),
       "the engine-authored brief exists and names the parent")
    ok(any(ev.get("opened_by") == "conclude" and ev.get("lane") == abl_lid
           for ev in d.events("instrumental_lane_injected")),
       "the intake event says the conclusion opened it")
    ok(egraph.mechanism_label(e_now) == f"deferred (ablation {abl_lid} open)",
       f"the frontier label shows the open ablation: {egraph.mechanism_label(e_now)}")

    out = nx(d, "design_ablation")
    task = next(t for t in d.state()["tasks"] if t["id"] == out["task"])
    ok(task["subject"].get("lane") == abl_lid, f"the design card is for the engine's lane: {task['subject']}")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("Ablation allowance and sizing" in bundle and f"x what {e_node} cost" in bundle,
       "the design bundle states the allowance in the parent's own units")
    M.w_design_ablation(d, out, abl_lid)          # reads PARENT from the lane; settles_parent_mechanism=True
    sub_ok(d, out)
    out = nx(d, "review_ablation")
    M.w_review_ablation(d, out, abl_lid, verdict="ACCEPT")
    sub_ok(d, out)
    inside, allowance_lines = evalid.ablation_design_within_allowance(d.eng().ctx(), d.lane(abl_lid))
    ok(inside, f"a one-run design on this parent is inside the 2x allowance: {allowance_lines}")
    surface = d.next()
    idea_gate_was_manual = surface.get("kind") == "gate"
    if idea_gate_was_manual:
        st_gate = next(g for g in d.state()["gates"] if g["id"] == surface["gate"])
        ok(st_gate.get("kind") == "idea_approval" and (st_gate.get("subject") or {}).get("lane") == abl_lid,
           f"the surface before planning is the ablation's idea gate: {st_gate}")
        gate_card = (d.repo / surface["card"]).read_text(encoding="utf-8")
        ok("inside the pre-authorized allowance" in gate_card and "settles the parent's mechanism: True" in gate_card,
           "the gate report shows the allowance verdict and the write-back promise")
        d.decide(surface["gate"], True, note="doors drive: user approves the one-run causal design")
        surface = d.next()
    ok(surface.get("kind") == "task" and surface.get("type") == "plan_node",
       f"after the idea decision the plan card presents: {surface}")
    idea_gate = next(g for g in d.state()["gates"] if g.get("kind") == "idea_approval"
                     and (g.get("subject") or {}).get("lane") == abl_lid)
    ok(idea_gate.get("status") == "approved"
       and (("auto-approved" in str(idea_gate.get("decision_note"))) != idea_gate_was_manual),
       f"the idea gate's decision record matches how it was decided: {idea_gate.get('decision_note')}")

    out = surface
    a_stage = stage("changed_component_run", uri=f"oss://mock/{abl_lid}/one-run",
                    key=f"ablation|{abl_lid}|factor=counterfactual-objective")
    M.w_plan(d, out, abl_lid, role="variant", workdir=f"workareas/{abl_lid.lower()}-ablation",
             stages=[a_stage], code_parent=e_node, level=0)
    sub_ok(d, out)
    a_node = d.lane(abl_lid)["node"]
    ok(d.node(a_node).get("parents") == [e_node] and egraph.level_label(d.node(a_node)) == "diagnostic",
       f"the ablation node hangs off the winner as a diagnostic: {d.node(a_node).get('parents')}")
    out = nx(d, "implement")
    M.do_implement(d, out, a_node)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(a_node)["status"] == "pass", "the ablation smoke passes")
    sub_ok(d, out)
    out = nx(d, "ablation_fidelity")
    M.w_ablation_fidelity(d, out, a_node)
    sub_ok(d, out)
    surface = d.next()
    workflow_gate_was_manual = surface.get("kind") == "gate"
    if workflow_gate_was_manual:
        st_gate = next(g for g in d.state()["gates"] if g["id"] == surface["gate"])
        ok(st_gate.get("kind") == "workflow_approval", f"the spend gate before launch: {st_gate.get('kind')}")
        d.decide(surface["gate"], True, note="doors drive: user approves the audited one-run spend")
        surface = d.next()
    ok(surface.get("kind") == "task" and surface.get("type") == "stage_launch",
       f"the one changed-component run launches: {surface}")
    spec_inside, spec_lines = evalid.ablation_spec_within_allowance(
        d.eng().ctx(), d.node(a_node), json.loads((d.repo / d.node(a_node)["spec"]).read_text(encoding="utf-8")))
    ok(spec_inside == (not workflow_gate_was_manual),
       f"the workflow gate was manual exactly when the spec exceeded the allowance: {spec_lines}")
    out = surface
    metrics_rel = f"{d.node(a_node)['workdir']}/ablation_stage_metrics.json"
    M.write_stage_result(d, a_node, "changed_component_run", metrics_rel, {"loss": 0.12})
    M.w_launch(d, out, "changed_component_run", mode="completed", metrics_rel=metrics_rel)
    sub_ok(d, out)
    out = nx(d, "evaluate")
    e_score = float(econfig.result_value(d.node(e_node)["scores"]["auc"]))
    M.w_eval(d, out, a_node, round(e_score + 0.005, 4), logloss=0.55, latency=100.0)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, a_node)                    # ablation_result effect observed -> supports X1
    sub_ok(d, out)

    a_done = d.node(a_node)
    ok(a_done.get("ablation_result", {}).get("effect") == "observed"
       and a_done.get("ablation_result", {}).get("supports") == "X1"
       and d.lane(abl_lid)["status"] == "done",
       f"the causal settlement follows the pre-registered map and closes the lane: {a_done.get('ablation_result')}")
    e_settled = d.node(e_node)
    ok(e_settled.get("mechanism_status") == "confirmed",
       f"the observed effect confirms the parent's mechanism: {e_settled.get('mechanism_status')}")
    settlement = (e_settled.get("mechanism_settlements") or [{}])[-1]
    ok(settlement.get("ablation") == a_node and settlement.get("from") == "deferred"
       and settlement.get("to") == "confirmed" and "promotion_to" not in settlement,
       f"the parent records who settled it and how: {settlement}")
    ok(e_settled.get("scientific_promotion_status") == "met",
       f"promotion recomputed on the confirmed story: {e_settled.get('scientific_promotion_status')}")
    frontier_md = (d.repo / ".evo/views/FRONTIER.md").read_text(encoding="utf-8")
    e_rows = [line for line in frontier_md.splitlines() if line.startswith(f"| {e_node} ")]
    ok(bool(e_rows) and all(f"via {a_node}" in line for line in e_rows),
       f"FRONTIER shows the parent confirmed via its ablation: {e_rows}")
    ok(any(ev.get("parent") == e_node and ev.get("ablation") == a_node
           for ev in d.events("parent_mechanism_settled")),
       "the write-back is an event")
    ok(d.node(a_node).get("scientific_promotion_status") == "not_applicable",
       "the diagnostic itself earns no promotion")
    drive_close(d, "R005")

    # ----------------------------------------------------------- doctor ----
    problems, _ = M.edoctor.diagnose(d.store())
    ok(problems == [], f"doctor clean after all four door lifecycles: {problems[:6]}")
    print(f"\nDOORS GREEN: {M.CHECKS} checks passed (scaling follow-up + exploratory scout "
          f"+ confirmatory re-run + repeat-measure + inheritance tax, full lifecycles, real validators)")


if __name__ == "__main__":
    main()
