"""50-round soak: liveness + growth ceilings at scale, on the real engine.

    python tests/soak_drive.py

What this buys that mock/stress/doors do not:
- 50 full research rounds through one adaptive dispatcher: any unexpected task
  or gate FAILS LOUD (a liveness probe, not a script that knows the schedule).
- Agent-ledger id spaces driven PAST 1000 through the real validators (the
  \\d{3,4} widening exercised live: CA via preload + organic minting, M via
  preload + 4-digit citations inside accepted IDEA.md files).
- Structural growth bounds: state bytes and event counts must stay ~linear in
  rounds; superlinear growth fails. Wall times are REPORTED, never asserted
  (single-run wall clocks are not evidence - project discipline).

Exclusive like every drive: shares tests/out with mock/stress/doors.
"""
from __future__ import annotations

import os
import shutil
import stat
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))

import mock_drive as m   # noqa: E402  (reuses its writers/pipeline helpers)
import estore            # noqa: E402
import eutil             # noqa: E402

ROUNDS = 50
WILDCAT_CADENCE = 5      # mock config runs wildcat_every=5, positional (R005, R010, ...)
CA_PRELOAD_TO = 950      # organic minting then crosses CA1000 by ~round 9
M_PRELOAD_TO = 990       # lane cards then mint M991+; citations go 4-digit


# ---------------------------------------------------------------- dispatcher
_orig_nx = m.nx


def soak_nx(d, typ=None, kind="task"):
    """m.nx with scheduler-owed duties auto-handled and everything else loud.

    The scripted drives know their schedule; a 50-round loop cannot. Evidence
    refreshes and sota rescans arrive on the engine's cadence and are served
    inline; ANY other surprise (gate, unknown task) is a soak failure by
    definition - that is the liveness probe.
    """
    for _ in range(80):
        out = d.next()
        k, t = out.get("kind"), out.get("type")
        if k == "task" and t == "evidence" and typ != "evidence":
            if m._evidence_count(d) < 6:
                m.w_evidence_initial(d)   # first pool: full B-coverage fill
            else:
                m.w_evidence_refresh(d)
            m.sub_ok(d, out)
            continue
        if k == "task" and t == "sota_scan" and typ != "sota_scan":
            m.w_sota(d, out)
            m.sub_ok(d, out)
            continue
        if typ == "tournament" and k == "task" and t == "deep_read":
            m.ensure_collision_audits(d, (d.state()["tasks"][-1].get("subject") or {}).get("lane"))
            r = d.submit(out["task"])
            m.ok(r["kind"] == "accepted", f"post-freeze collision pass must accept: {r}")
            continue
        if typ != "fidelity" and k == "task" and t == "fidelity":
            nid = (d.state()["tasks"][-1].get("subject") or {}).get("node")
            m.w_fidelity(d, out, nid)
            r = d.submit(out["task"])
            m.ok(r["kind"] == "accepted", f"kernel fidelity audit must accept: {r}")
            continue
        if typ == "evaluate" and k == "task" and t == "eval_launch":
            out["_deferred_evaluate"] = True
            return out
        m.ok(k == kind, f"soak: expected kind={kind}, got {out}")
        if typ is not None:
            m.ok(t == typ, f"soak: expected task type={typ}, got {t} ({out})")
        return out
    m.ok(False, "soak: 80 dispatcher steps without reaching the wanted task - livelock?")


m.nx = soak_nx


# ---------------------------------------------------------------- preloaders
def preload_collision_ledger(d):
    path = d.repo / ".evo/evidence/COLLISION_AUDITS.jsonl"
    existing = len(eutil.read_jsonl(path))
    for i in range(existing + 1, CA_PRELOAD_TO + 1):
        eutil.append_jsonl(path, {
            "id": f"CA{i:03d}", "lane": "L000", "program_set_digest": f"preload{i:04d}",
            "candidate_id": "K0", "candidate_digest": f"preload{i:04d}",
            "mech_card_id": "M001", "axis": "mechanism" if i % 2 else "task_effect",
            "query": m.long(60, f"preloaded scale row {i} searching the mechanism neighborhood of a synthetic candidate"),
            "program_overlap": m.long(80, f"preloaded scale row {i} shares estimation primitives with the synthetic candidate program"),
            "irreducible_difference": m.long(105, f"preloaded scale row {i} keeps one load-bearing state relation the audited paper program does not contain"),
            "emulation_test": m.long(105, f"preloaded scale row {i} cannot be emitted by the paper program without adopting the claimed kernel and operator graph"),
            "recent_search_saturation": m.long(90, f"preloaded scale row {i} screened current-year mechanism and task-effect queries without a closer program"),
        })
    return CA_PRELOAD_TO - existing


def preload_mech_ledger(d):
    path = d.repo / ".evo/evidence/MECH_CARDS.jsonl"
    existing = len(eutil.read_jsonl(path))
    for i in range(existing + 1, M_PRELOAD_TO + 1):
        eutil.append_jsonl(path, {
            "id": f"M{i:03d}", "lane": "L000", "paper": "E001",
            "name": f"preloaded core work {i}",
            "problem": m.long(35, f"scale row {i} isolates exposure-conditioned supervision bias in ranking"),
            "core_math": m.long(45, f"scale row {i} reweights the per-example loss with an inverse exposure estimate under clipping"),
            "transfer_conditions": m.long(45, f"scale row {i} requires logged exposure estimates and a fixed candidate pool at training time"),
            "failure_modes": m.long(35, f"scale row {i} degrades when exposure estimates are near zero variance"),
            "old_program": m.long(55, f"scale row {i} trains on realized outcomes directly with uniform per-example weighting throughout"),
            "new_program": m.long(55, f"scale row {i} multiplies each example loss by a clipped inverse exposure weight before aggregation"),
            "program_operations": [m.long(20, f"scale row {i} op weight"), m.long(20, f"scale row {i} op clip")],
            "irreducible_core": m.long(65, f"scale row {i} binds the weight computation to the loss aggregation in one load-bearing relation"),
            "necessary_components": ["exposure estimate", "clipping constant"],
            "support_components": ["logging pipeline"],
            "ablation_support": m.long(45, f"scale row {i} removing the weight restores the uniform-loss tail ranking error"),
            "resource_delta": m.long(45, f"scale row {i} adds one multiply per example and no extra training passes"),
            "gain_confound": m.long(45, f"scale row {i} the gain persists under matched token and parameter budgets"),
            "assumptions": [m.long(25, f"scale row {i} logged exposure is faithful")],
        })
    return M_PRELOAD_TO - existing


# ---------------------------------------------------------------- round legs
def soak_exploit_round(d, rid, i, parent, score):
    name = f"soak-e{i:03d}"
    # v11.4 fixture sync: a 1-lane round with a focus tag now exceeds the
    # 50% focus share cap (no single-candidate exception); the soak's rounds
    # never needed the tag.
    m.open_round(d, rid, [m.exploit_lane(name, parent)])
    lid, mech = m.drive_lane_to_plan(d, name, dims=m.L2_DIMS)
    m.drive_mature_redteam(d, lid, mech_ids=mech, score=score)
    nid = m.drive_plan(d, lid, role="variant", code_parent=parent, stages=[
        m.stage("train", uri=f"oss://bkt/user/{name}-train/checkpoint.zip", key=f"train|{name}")])
    run_id = m.drive_node_to_training(d, nid)
    m.drive_watch_finish(d, run_id, nid, "train")
    m.drive_eval_conclude(d, nid, score)
    m.drive_close(d, rid)
    return nid


def soak_wildcat_round(d, rid, i, score):
    name = f"soak-w{i:03d}"
    m.open_round(d, rid, [{"name": name, "intent": "wildcat", "min_level": 4, "parents": []}])
    lid, mech = m.drive_lane_to_plan(d, name, dims=m.L4_DIMS)
    # wildcat intent carries the theory route after tournament (mock r5
    # choreography: theorize -> REVISE -> response theorize -> PROCEED)
    out = m.nx(d, "theorize")
    m.w_theory(d, out, lid, parent_ref="baseline", moonshot=True)
    m.sub_ok(d, out)
    out = m.nx(d, "challenge")
    m.w_challenge(d, out, lid, "REVISE")
    m.sub_ok(d, out)
    out = m.nx(d, "theorize")
    m.w_theory(d, out, lid, parent_ref="baseline", moonshot=True,
               response_from=f".evo/rounds/{rid}/lanes/{lid}/CHALLENGE_c1.md")
    m.sub_ok(d, out)
    out = m.nx(d, "challenge")
    m.w_challenge(d, out, lid, "PROCEED")
    m.sub_ok(d, out)
    m.drive_mature_redteam(d, lid, mech_ids=mech, score=score, theory=True,
                           n_assum=4, deriv_chars=1300, interface_changed=True)
    nid = m.drive_plan(d, lid, role="root", code_parent="N001", stages=[
        m.stage("train", uri=f"oss://bkt/user/{name}-train/checkpoint.zip", key=f"train|{name}")])
    run_id = m.drive_node_to_training(d, nid, bridge=True)   # roots carry the metric anchor bridge
    m.drive_watch_finish(d, run_id, nid, "train")
    m.drive_eval_conclude(d, nid, score)
    m.drive_close(d, rid)
    return nid


# ---------------------------------------------------------------- the soak
def _force_rmtree(path: Path) -> None:
    """rmtree that survives Windows read-only git object files."""
    if not path.exists():
        return
    try:
        shutil.rmtree(path)
    except OSError:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    os.chmod(os.path.join(root, name), stat.S_IWRITE)
                except OSError:
                    pass
        shutil.rmtree(path)


def main():
    t0 = time.time()
    base = HERE / "out" / "soak"
    repo = base / "repo"
    _force_rmtree(base)
    m.make_repo(repo, with_git=True)
    estore.Store(repo).init("soak", "50-round scale/liveness soak")
    d = m.D(repo)

    # rounds_max must cover bootstrap + 50 rounds (full_auto forbids 0)
    orig_cfg = m.w_config_main

    def cfg_override(dd, out, **kw):
        kw.setdefault("rounds_max", ROUNDS + 10)
        # v11.4 fixture sync: the focus share cap has no single-candidate
        # exception anymore - a serial single-lane soak can never legally
        # serve a starved focus direction, so push the neglect window past
        # the whole soak horizon (same treatment as the doors drive).
        kw.setdefault("focus_neglect", ROUNDS + 10)
        orig_cfg(dd, out, **kw)

    m.w_config_main = cfg_override
    try:
        m.run_bootstrap(d)
    finally:
        m.w_config_main = orig_cfg

    ca_added = preload_collision_ledger(d)
    me_added = preload_mech_ledger(d)
    m.section(f"soak preload: +{ca_added} CA rows (to {CA_PRELOAD_TO}), +{me_added} M rows (to {M_PRELOAD_TO})")

    sizes, events_n, walls = [], [], []
    parent, best = "N001", 0.70
    for i in range(1, ROUNDS + 1):
        rid = f"R{i:03d}"
        best = round(best + 0.003, 4)
        rt = time.time()
        if i % WILDCAT_CADENCE == 0:
            nid = soak_wildcat_round(d, rid, i, best)
        else:
            nid = soak_exploit_round(d, rid, i, parent, best)
        parent = nid   # winner becomes the next exploit parent (frontier tip)
        walls.append(time.time() - rt)
        sizes.append((repo / ".evo/state.json").stat().st_size)
        events_n.append(m.line_count(repo) if hasattr(m, "line_count")
                        else sum(1 for _ in (repo / ".evo/events.jsonl").open(encoding="utf-8")))
        closed = [r for r in d.state()["rounds"] if r.get("closed_at")]
        m.ok(len(closed) >= i, f"round {rid} must be closed (got {len(closed)})")
        if i % 10 == 0:
            m.section(f"soak {rid}: wall {walls[-1]:.1f}s state {sizes[-1] // 1024}KB "
                      f"events {events_n[-1]} (checks so far: {m.CHECKS})")

    # --- id spaces actually crossed 1000 through the real validators
    ca_ids = [int(r["id"][2:]) for r in eutil.read_jsonl(repo / ".evo/evidence/COLLISION_AUDITS.jsonl")
              if isinstance(r, dict) and str(r.get("id") or "")[2:].isdigit()]
    m.ok(max(ca_ids) >= 1000, f"CA ledger must cross id 1000 organically (max {max(ca_ids)})")
    me_ids = [int(r["id"][1:]) for r in eutil.read_jsonl(repo / ".evo/evidence/MECH_CARDS.jsonl")
              if isinstance(r, dict) and str(r.get("id") or "")[1:].isdigit()]
    m.ok(max(me_ids) >= 1000, f"M ledger must cross id 1000 (max {max(me_ids)})")
    idea_files = sorted((repo / ".evo/ideas").glob("I*.md"))
    late_cites = any("[M1" in p.read_text(encoding="utf-8") for p in idea_files[-6:])
    m.ok(late_cites, "late accepted IDEA.md files must cite 4-digit M ids (widened citation extractor live)")

    # --- growth stays ~linear (structural; wall times reported, not asserted)
    early_sz = sizes[9] - sizes[2]
    late_sz = sizes[-1] - sizes[-8]
    m.ok(late_sz <= max(early_sz, 1) * 4,
         f"state.json growth per 7 rounds must stay ~linear (early {early_sz}B late {late_sz}B)")
    early_ev = events_n[9] - events_n[2]
    late_ev = events_n[-1] - events_n[-8]
    m.ok(late_ev <= max(early_ev, 1) * 3,
         f"event growth per 7 rounds must stay ~linear (early {early_ev} late {late_ev})")

    # --- the tree is still healthy and renderable at scale
    d.doctor_clean("after 50 soak rounds")
    m.dash_data(d)
    m.ok(len([r for r in d.state()["rounds"] if r.get("closed_at")]) >= ROUNDS,
         "all 50 soak rounds closed")

    half = ROUNDS // 2
    m.section(f"soak wall profile: first-half median {sorted(walls[:half])[half // 2]:.1f}s, "
              f"second-half median {sorted(walls[half:])[half // 2]:.1f}s, max {max(walls):.1f}s "
              "(reported only - single-run wall clocks are not regression evidence)")
    print(f"\nSOAK GREEN: {m.CHECKS} checks passed in {time.time() - t0:.0f}s "
          f"({ROUNDS} rounds, adaptive dispatcher, CA max {max(ca_ids)}, M max {max(me_ids)})")


if __name__ == "__main__":
    main()
