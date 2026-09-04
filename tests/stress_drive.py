#!/usr/bin/env python3
"""Long-horizon stress drive for Model Evolution v9.2 (deep debug).

20 rounds, full_auto, git mode - the skeleton (science text) is mocked, but the
substance is REAL:
  - all candidate lanes use schema-v2 forward scientific programs (typed
    objects, train/infer operator DAGs, irreducible KC#/OP# kernels, typed
    effect chains and nine-axis resource comparisons); repair, constructive,
    core-synthesis and theory-derived origins all run through their distinct
    stage orders;
  - workflow stages run as real background OS processes (subprocess.Popen of a
    tiny train.py that sleeps, writes checkpoints/metrics, and can really crash
    with a nonzero exit code); job ids are real PIDs; failure notes are read
    from the real stderr log;
  - evaluation runs the node spec's real eval command; metrics.json numbers
    come from executed code, and node verdicts are recomputed from them;
  - git worktrees/branches/commits are real; ancestry is audited at the end;
  - async completion order is NOT choreographed: the dispatcher handles
    whatever task the engine emits next, so absorption happens at arbitrary
    `next` boundaries (2 workflow-stage slots, overlapping runs and explicit
    full-slot launch deferral).

Complexity exercised across the 20 rounds:
  ~32 lanes / ~33 nodes: chains 6+ generations deep; hybrid-of-hybrid; a
  4-parent hybrid (3 model parents incl. a REVIVED node + a platform); a
  cross-lineage hybrid of two moonshot lineages; 3 platforms (background and
  completed launch modes); 4 wildcats + 2 moonshots (cadence rounds 5/10/15/20);
  preregistered adaptive multi-candidate search with a real completion ledger;
  fixed intrinsic multi-model construction; two long stagnation plateaus forcing tier-1 (L3+) and tier-2 (moonshot)
  escalation twice; artifact reuse across rounds (consume duty + waiver);
  a 2-stage node whose SECOND stage really crashes once (a code revision must
  supersede mixed-revision evidence and replay the full workflow); a node abandoned after 3 real training failures via
  escalation-reject while its sibling lane completes; prune + archive at a
  retro; revive via the real CLI; escalation-approve reset on a stuck task;
  invariants checked after every single engine call; doctor after every round;
  a final audit sweep (verdict recomputation, git ancestry, artifact registry,
  frontier cross-check with an independent implementation).

Run:  python tests/stress_drive.py    (runs the fast suite's helpers via import)
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True                  # test runs must not litter __pycache__
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"     # ...nor must their child processes

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "engine"))

import mock_drive as M  # reuse driver, writers, helpers (module defines only funcs)
import eartifact        # noqa: E402
import econfig          # noqa: E402
import egraph           # noqa: E402
import eprogram         # noqa: E402
import evalid           # noqa: E402
import estore           # noqa: E402
import eutil            # noqa: E402
import evcs             # noqa: E402

PY = sys.executable
ok, section, nx, sub_ok, sub_rej = M.ok, M.section, M.nx, M.sub_ok, M.sub_rej
wt, wj, long = M.wt, M.wj, M.long


BASELINE_Q = 0.600
SK_SHARED = "pretrain|shared-encoder|v1"

# ---------------------------------------------------------------- real project
TRAIN_PY = """import json, os, sys, time, pathlib
stage = sys.argv[1] if len(sys.argv) > 1 else "train"
p = json.loads(os.environ["EVO_TEST_PARAMS"])
time.sleep(float(p.get("sleep", 0.1)))
if p.get("fail_stage") == stage:
    sys.stderr.write("RuntimeError: CUDA out of memory (simulated) at stage %s, batch 4096\\n" % stage)
    sys.exit(1)
q = float(p["quality"])
pathlib.Path("checkpoint_%s.json" % stage).write_text(
    json.dumps({"quality": q, "stage": stage}), encoding="utf-8")
usage = {k: float(v) / 2.0 for k, v in p.get("budget_limits", {}).items()}
result = {"summary": {"loss": 1.0 - q}, "usage": usage}
if p.get("control_mode") == "preregistered_adaptive":
    result["stop_reason"] = "the preregistered finite resource horizon was reached"
pathlib.Path("train_metrics_%s.json" % stage).write_text(json.dumps(result), encoding="utf-8")
if p.get("ledger_file"):
    pathlib.Path(p["ledger_file"]).write_text(
        json.dumps({"step": 1, "observation": q, "decision": "selected registered candidate"}) + "\\n",
        encoding="utf-8")
print("trained stage", stage, "quality", q)
"""

EVAL_PY = """import json, glob, pathlib
cks = sorted(glob.glob("checkpoint_*.json"))
if not cks:
    raise SystemExit("no checkpoint to evaluate")
q = max(json.loads(pathlib.Path(c).read_text(encoding="utf-8"))["quality"] for c in cks)
pathlib.Path("eval_metrics.json").write_text(
    json.dumps({"auc": q, "logloss": 1.0 - q, "latency_ms": 100.0,
                "_usage": {"wallclock_minutes": 1.0}}), encoding="utf-8")
print("evaluated quality", q)
"""


def make_real_repo(path: Path):
    if path.exists():
        M.rmtree(path)
    M.make_repo(path, with_git=True)
    wt(path, "train.py", TRAIN_PY)
    wt(path, "eval.py", EVAL_PY)
    M.git(path, "add", "-A")
    M.git(path, "commit", "-q", "-m", "c3 real train/eval scripts")


# ---------------------------------------------------------------- behavior tables
LB: dict[str, dict] = {}        # lane name -> behavior
NODEQ: dict[str, str] = {}      # lane name -> node id (captured at plan accept)
PROCS: dict[str, dict] = {}     # run id -> {proc, workdir, stage, log}
FAULTS: dict[tuple, int] = {}   # (lane, stage) -> remaining real crashes
TARGET: dict[str, float] = {}   # node id -> planned quality
MAXRUN = {"seen": 0}
SLOT_DEFERRAL = {"seen": False}

# w_sketches keeps a small compatibility argument for the number of divergent
# candidates. These labels are deliberately forward-program variants, not the
# retired coordinate-wise dimension/change-class schema.
PROGRAM_VARIANTS = [
    ("operator_topology", "candidate"),
    ("learned_objects", "candidate"),
    ("effect_chain", "candidate"),
]
L2 = L3 = L4 = L4NB = PROGRAM_VARIANTS
THEORY_INTENTS = ("reform", "wildcat", "moonshot")


def theory_reform(parent_sel):
    return [("T", {"parent_sel": parent_sel}), ("C", {"good": {"verdict": "REVISE"}}),
            ("T", {"parent_sel": parent_sel, "response": True}),
            ("C", {"good": {"verdict": "PROCEED"}})]


def lane(name, intent, min_level, parents_sel=(), *, outcome=("flat",), dims=None,
         stages_fn=None, sleep=0.15, theory=None, theory_rigor=None, hybrid=False,
         platform=False, launch_mode="bg", sketch_garbage=0, lessons=False,
         plan_neg=None, search_origin="constructive"):
    if theory_rigor is not None and search_origin != "theory_derived":
        raise AssertionError("theory_rigor is legal only for theory_derived lanes")
    frozen_rigor = (theory_rigor or "partial") if search_origin == "theory_derived" else None
    LB[name] = {
        "name": name, "intent": intent, "min_level": min_level,
        "search_origin": search_origin,
        "parents_sel": list(parents_sel), "outcome": outcome,
        "dims": dims or L2, "theory_rigor": frozen_rigor,
        "stages_fn": stages_fn, "sleep": sleep,
        "theory": list(theory) if theory else
                  (theory_reform(parents_sel[0] if parents_sel else "baseline")
                   if (intent in THEORY_INTENTS or min_level >= 3) else []),
        "hybrid": hybrid, "platform": platform, "launch_mode": launch_mode,
        "sketch_garbage": sketch_garbage, "lessons": lessons,
        "plan_neg": list(plan_neg or []),
        "mech": [],
    }
    row = {"name": name, "intent": intent, "min_level": min_level,
           "parents_sel": list(parents_sel), "search_origin": search_origin}
    if frozen_rigor is not None:
        row["theory_rigor"] = frozen_rigor
    return row


def resolve_sel(sel):
    if sel == "baseline":
        return "N001"
    if isinstance(sel, tuple) and sel[0] == "lane":
        return NODEQ[sel[1]]
    raise AssertionError(f"bad selector {sel}")


def std_stage(lname, sname, *, key=None, consumes=None, waiver=None, kind="weights",
              mode="fixed", multiplicity="single", controller=None,
              stopping_conditions=None, why_multiple=None, limits=None, launch=None):
    control = {"mode": mode, "multiplicity": multiplicity}
    if controller:
        control["controller"] = controller
    if stopping_conditions:
        control["stopping_conditions"] = stopping_conditions
    if why_multiple:
        control["why_multiple"] = why_multiple
    return {
        "name": sname,
        "purpose": long(35, f"execute bounded {sname} and create a stable downstream handoff"),
        "launch": launch or f'"{PY}" train.py {sname}',
        # R9 landing lease: declared landings are per-RUN exclusive across live
        # attempts, so the spec path must be unique per lane (parallel slots).
        "metrics_file": f"train_metrics_{lname}_{sname}.json",
        "control": control,
        "budget": {"limits": limits or {"wallclock_minutes": 30}},
        "stage_key": key or f"{sname}|{lname}",
        "produces": [{"name": f"{lname} {sname} weights", "kind": kind,
                      "uri": f"oss://bkt/user/{lname}-{sname}/ckpt.zip"}],
        "consumes": consumes or [],
        **({"reuse_waiver": waiver} if waiver else {}),
    }


def single_stage_fn(lname, **kw):
    return lambda d: [std_stage(lname, "train", **kw)]


# ---------------------------------------------------------------- invariants
def check_invariants(d, out):
    st = d.state()
    open_tasks = [t for t in st["tasks"] if t["status"] == "open"]
    ok(len(open_tasks) <= 1, f"single open task invariant: {[t['id'] for t in open_tasks]}")
    running = d.running()
    MAXRUN["seen"] = max(MAXRUN["seen"], len(running))
    ok(len(running) <= 2, f"slot quota respected: {len(running)}")
    if len(running) == 2 and out.get("type") == "stage_watch":
        running_nodes = {run.get("node") for run in running}
        for node in d.graph()["nodes"]:
            if node.get("id") in running_nodes or node.get("status") not in (
                    "smoke_pass", "bridge_pass", "stage_ready"):
                continue
            spec_path = d.repo / str(node.get("spec") or "")
            if not spec_path.exists():
                continue
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            stages = (spec.get("workflow") or {}).get("stages") or []
            if int(node.get("stage_cursor") or 0) < len(stages):
                SLOT_DEFERRAL["seen"] = True
                break
    uris = [a["uri"] for a in d.reg()["artifacts"]]
    ok(len(uris) == len(set(uris)), "artifact URIs unique")


def frontier_independent(d):
    """Independent recomputation of the inheritance frontier (DESIGN_V10 §11.1),
    written from the spec rather than by calling any engine frontier code.

    Legality is filtered first and non-domination second; the origin baseline is
    a floor that applies only when nothing else is legal; verdicts that assert a
    usable deliverable exists are the only ones excluded.
    """
    g = d.graph()
    cfg = d.store().load_config()
    cells = [c for c in econfig.evaluation_cells(cfg) if c.get("role") != "diagnostic"]
    observed = [n for n in g["nodes"]
                if n.get("retire_reason") != "pruned" and n.get("role") != "platform"
                and n.get("status") == "concluded" and n.get("verdict") is not None
                and n.get("verdict") not in ("screened_out", "failed")]
    elig = [n for n in observed
            if not econfig.is_research(cfg)
            or n.get("scientific_promotion_status") == "met"]

    def dominates(a, b):
        better = False
        for c in cells:
            rk = c["result_key"]
            av, bv = (a.get("scores") or {}).get(rk), (b.get("scores") or {}).get(rk)
            if not isinstance(av, (int, float)) or not isinstance(bv, (int, float)):
                return False
            delta = av - bv if econfig.result_direction(cfg, rk) == "max" else bv - av
            margin = float(c.get("noninferiority_margin") or 0)
            if delta < -margin:
                return False
            if delta > max(margin, float(c.get("min_improvement") or 0)):
                better = True
        return better

    # A node leaves only when something beats it that it cannot beat back,
    # directly or transitively: domination cycles keep every member rather than
    # deleting all of them.  De-duplication is a display concern and must not
    # decide who may be inherited from, so it is deliberately absent here.
    beats = {(a["id"], b["id"]) for a in elig for b in elig
             if a["id"] != b["id"] and dominates(a, b) and not dominates(b, a)}
    reach = set(beats)
    for _ in range(len(elig) + 1):
        grown = reach | {(x, z) for (x, y) in reach for (y2, z) in reach if y == y2}
        if grown == reach:
            break
        reach = grown
    tips = [n for n in elig
            if not any((m["id"], n["id"]) in beats and (n["id"], m["id"]) not in reach
                       for m in elig)]
    if not tips:
        base = next((n for n in g["nodes"]
                     if n.get("role") == "baseline" and n.get("status") == "concluded"), None)
        tips = [base] if base is not None else []
    return sorted(n["id"] for n in tips)


# ---------------------------------------------------------------- run/exec helpers
def spec_of(d, nid):
    node = d.node(nid)
    return json.loads((d.repo / node["spec"]).read_text(encoding="utf-8"))


def lane_beh(d, lid):
    return LB[d.lane(lid)["name"]]


def compute_quality(d, nid, beh):
    if nid in TARGET:
        return TARGET[nid]
    store = estore.Store(d.repo)
    ctx = evalid.Ctx(store, store.load_state(), store.load_config(),
                     store.load_graph(), store.load_artifacts())
    node = d.node(nid)
    outc = beh["outcome"]
    if outc[0] in ("above", "at"):
        g = d.graph()
        best = max(egraph.primary_score(n, "auc") or 0.0 for n in egraph.frontier(g, store.load_config()))
        q = best + (outc[1] if outc[0] == "above" else 0.0)
    else:
        ref = evalid._reference_score(ctx, node)
        ok(ref is not None, f"reference score for {nid}")
        q = {"up": ref + outc[1] if len(outc) > 1 else ref,
             "flat": ref,
             "down": ref - (outc[1] if len(outc) > 1 else 0.008)}[outc[0]]
    TARGET[nid] = q
    return q


def task_subject(d, out):
    for t in d.state()["tasks"]:
        if t["id"] == out["task"]:
            return t["subject"]
    raise AssertionError(f"task {out['task']} not in state")


def launch_stage_real(d, out, nid, beh):
    node = d.node(nid)
    subject = task_subject(d, out)
    sname = subject["stage"]
    seed = subject.get("replica_seed")
    wd = d.repo / node["workdir"]
    q = compute_quality(d, nid, beh) if not beh["platform"] else 0.5
    spec = spec_of(d, nid)
    stg = next(x for x in econfig.stages_of(spec) if x.get("name") == sname)
    ledger_rel = stg.get("ledger_file") if econfig.stage_requires_ledger(stg) else None
    ledger_local = Path(ledger_rel).name if ledger_rel else None
    params = {"quality": q, "sleep": beh["sleep"],
              "budget_limits": ((stg.get("budget") or {}).get("limits") or {}),
              "control_mode": (stg.get("control") or {}).get("mode"),
              "ledger_file": ledger_local}
    key = (beh["name"], sname)
    if FAULTS.get(key, 0) > 0:
        FAULTS[key] -= 1
        params["fail_stage"] = sname
    run_env = dict(os.environ)
    run_env["EVO_TEST_PARAMS"] = json.dumps(params)
    if beh["launch_mode"] == "completed":
        p = subprocess.run([PY, "train.py", sname], cwd=str(wd), capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env=run_env)
        ok(p.returncode == 0, f"completed-mode real training must pass: {p.stderr}")
        prepared = next(r for r in d.state()["runs"] if r["id"] == subject["run"])
        data = {"stage": sname, "mode": "completed",
                "run": prepared["id"], "attempt_token": prepared["attempt_token"],
                "metrics_file": f"{node['workdir']}/train_metrics_{sname}.json"}
        if seed is not None:
            data["seed"] = seed
        probe = spec.get("probe_execution") or {}
        if probe.get("mode") == "same_run" and probe.get("producer_stage") == sname:
            artifact = str(econfig.resolve_seed_template(probe.get("artifact") or "", seed)) \
                if seed is not None else str(probe.get("artifact") or "")
            M.wj(d.repo, artifact, {str(field): 0.97 for field in (probe.get("required_fields") or [])})
        if ledger_rel:
            generated = wd / str(ledger_local)
            target = d.repo / str(ledger_rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            if generated.resolve() != target.resolve():
                generated.replace(target)
            data["ledger_file"] = str(ledger_rel)
        wj(d.repo, out["outputs"][0], data)
        sub_ok(d, out)
        return
    log = wd / f"train_{sname}.log"
    proc = subprocess.Popen([PY, "train.py", sname], cwd=str(wd),
                            stdout=open(log, "w", encoding="utf-8"),
                            stderr=subprocess.STDOUT, env=run_env)
    prepared = next(r for r in d.state()["runs"] if r["id"] == subject["run"])
    launch_data = {"stage": sname, "mode": "background", "job": f"pid:{proc.pid}",
                   "run": prepared["id"], "attempt_token": prepared["attempt_token"],
                   "log_path": f"{node['workdir']}/train_{sname}.log"}
    if seed is not None:
        launch_data["seed"] = seed
    if ledger_rel:
        launch_data["ledger_file"] = str(ledger_rel)
    wj(d.repo, out["outputs"][0], launch_data)
    sub_ok(d, out)
    run = M.last_run(d)
    PROCS[run["id"]] = {"proc": proc, "workdir": node["workdir"], "stage": sname,
                        "ledger": ledger_rel, "ledger_local": ledger_local,
                        "log": f"{node['workdir']}/train_{sname}.log", "seed": seed}


def poll_and_report(d):
    """run-update every finished real process; return count reported."""
    n = 0
    for run in d.running():
        info = PROCS.get(run["id"])
        if info is None:
            continue
        rc = info["proc"].poll()
        if rc is None:
            continue
        n += 1
        if rc == 0:
            mrel = f"{info['workdir']}/train_metrics_{info['stage']}.json"
            ok((d.repo / mrel).exists(), f"real training wrote metrics: {mrel}")
            ledger_rel = info.get("ledger")
            if ledger_rel:
                generated = d.repo / info["workdir"] / str(info["ledger_local"])
                target = d.repo / str(ledger_rel)
                target.parent.mkdir(parents=True, exist_ok=True)
                if generated.resolve() != target.resolve():
                    generated.replace(target)
            spec = spec_of(d, run["node"])
            probe = spec.get("probe_execution") or {}
            if probe.get("mode") == "same_run" and probe.get("producer_stage") == info["stage"]:
                artifact = str(econfig.resolve_seed_template(probe.get("artifact") or "", info.get("seed"))) \
                    if info.get("seed") is not None else str(probe.get("artifact") or "")
                M.wj(d.repo, artifact, {str(field): 0.97 for field in (probe.get("required_fields") or [])})
            d.run_update(run["id"], "finished", metrics_file=mrel, ledger_file=ledger_rel)
        else:
            log_text = (d.repo / info["log"]).read_text(encoding="utf-8")
            note = log_text.strip().splitlines()[-1] if log_text.strip() else f"exit {rc}"
            ok("CUDA out of memory" in note, f"real failure note captured: {note}")
            d.run_update(run["id"], "failed", note=note)
        del PROCS[run["id"]]
    return n


def eval_real(d, out, nid):
    node = d.node(nid)
    spec = spec_of(d, nid)
    if out.get("type") == "eval_launch":
        wd = d.repo / node["workdir"]
        cmd = spec["eval"]["run"]
        p = subprocess.run(cmd, cwd=str(wd), shell=True, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        ok(p.returncode == 0, f"real eval must pass for {nid}: {p.stderr} {p.stdout}")
        m = json.loads((wd / "eval_metrics.json").read_text(encoding="utf-8"))
        ok(abs(m["auc"] - TARGET.get(nid, m["auc"])) < 1e-12,
           f"executed eval reproduces the planned quality for {nid}")
    else:
        run = d.store().get_run(d.state(), str(node.get("eval_run") or "")) or {}
        m = json.loads((d.repo / run["metrics_file"]).read_text(encoding="utf-8"))
    normalized = {"auc": m["auc"], "logloss": m["logloss"],
                  "latency_ms": m["latency_ms"], "_usage": m["_usage"]}
    probe_execution = spec.get("probe_execution") or {}
    probe_values_for_report = []
    if probe_execution:
        observations = []
        for expected in evalid.expected_probe_observations(spec):
            artifact = str(expected["artifact"])
            if (probe_execution.get("mode") == "eval_intervention" or
                    (probe_execution.get("mode") == "same_run" and
                     probe_execution.get("producer_stage") == "evaluation")) and not (d.repo / artifact).exists():
                M.wj(d.repo, artifact, {str(field): 0.97 for field in (probe_execution.get("required_fields") or [])})
            pdata = json.loads((d.repo / artifact).read_text(encoding="utf-8"))
            values = {str(field): pdata[str(field)] for field in (probe_execution.get("required_fields") or [])}
            row = {"artifact": artifact, "values": values}
            if expected.get("seed") is not None:
                row["seed"] = expected["seed"]
            observations.append(row)
            probe_values_for_report.extend(values.items())
        normalized["_mechanism_probe"] = {
            "mode": probe_execution.get("mode"), "signal": probe_execution.get("signal"),
            "expect": probe_execution.get("expect"),
            "required_fields": list(probe_execution.get("required_fields") or []),
            "observations": observations,
        }
    if out.get("type") == "eval_launch":
        normalized["_resource_measurements"] = M.planned_resource_measurements(d, nid)
        raw_rel = f".evo/nodes/{nid}/eval/raw_metrics.json"
        wj(d.repo, raw_rel, normalized)
        # v9.2's shipped stress drive omitted the prepared RUN identity here and
        # therefore failed its own engine's EVAL_LAUNCH_RUN/ATTEMPT_TOKEN checks
        # (reproduced on the untouched v9.2 tree, check 68). Carry the identity
        # exactly like mock_drive.w_launch_eval does.
        task = next(t for t in d.state()["tasks"] if t["id"] == out["task"])
        prepared = next(r for r in d.state()["runs"] if r["id"] == task["subject"]["run"])
        wj(d.repo, out["outputs"][0], {"mode": "completed", "metrics_file": raw_rel,
                                        "run": prepared["id"],
                                        "attempt_token": prepared["attempt_token"]})
        return m
    wj(d.repo, out["outputs"][0], normalized)
    # v9 duties: anomaly hunt + registered mechanism probe echo
    meta = {}
    if node.get("idea_doc"):
        mp = d.repo / node["idea_doc"].replace(".md", ".meta.json")
        if mp.exists():
            meta = json.loads(mp.read_text(encoding="utf-8"))
    goal_bits = []
    cfg = d.store().load_config()
    for cell in econfig.evaluation_cells(cfg):
        threshold = cell.get("goal_threshold")
        key = str(cell.get("result_key") or "")
        value = m.get(key)
        if cell.get("role") != "target" or threshold is None or not isinstance(value, (int, float)):
            continue
        direction = econfig.result_direction(cfg, key)
        met = value >= threshold if direction == "max" else value <= threshold
        goal_bits.append(f"goal {cell['id']} {'met' if met else 'not-met'} ({value} vs {threshold})")
    goal_text = "; ".join(goal_bits) or "no absolute target goal is configured"
    secs = [
        ("Setup", long(60, "eval executed the spec eval command in the node workarea")),
        ("Results", long(180, f"Absolute goal status: {goal_text}. Relative results: C1 auc {m['auc']}; C2 logloss {m['logloss']}; C3 latency {m['latency_ms']} from the executed run")),
        *M.dyn_sections(d, nid),
        ("Anomalies", long(50, "NONE - curves, rare level slices and output samples were checked")),
    ]
    if meta.get("mechanism_probe") and not str(meta.get("attribution_waiver") or "").strip():
        observed_text = ", ".join(f"{field}={value:g}" for field, value in probe_values_for_report)
        secs.append(("Mechanism check",
                     long(70, "the structured mechanism artifact was read and compared against the registered expectation")
                     + f" Recorded values: {observed_text}."))
    secs.append(("Comparability", long(60, "V1 same frozen split and V2 same metric code were checked")))
    wt(d.repo, out["outputs"][1], M.md(*secs))
    return m


# ---------------------------------------------------------------- round plan
ROUNDS: dict[str, dict] = {}
TOPICS_M1 = ["distributional value estimation", "propensity model calibration"]


def R(rid, lanes_list, *, neg=None, pre_good=None, retire=None, best, post=None):
    ROUNDS[rid] = {"lanes": lanes_list, "neg": list(neg or []), "pre_good": pre_good,
                   "retire": retire, "best": best, "post": post}


def e4_stages(d):
    art = eartifact.find_available_by_stage_key(d.reg(), SK_SHARED)
    ok(art is not None, "shared pretrain artifact available for e4")
    return [std_stage("e4", "distill", consumes=[{"artifact": art["id"]}]),
            std_stage("e4", "finetune", consumes=[{"stage": "distill"}])]


def e4_bad_stages(d):
    return [std_stage("e4", "pretrain", key=SK_SHARED),
            std_stage("e4", "finetune", consumes=[{"stage": "pretrain"}])]


def m1_stages(d):
    return [std_stage("m1", "train", key=SK_SHARED,
                      waiver=long(60, "the new principle changes the objective so the shared init is invalid here"))]


def e2_search_stages(d):
    return [std_stage(
        "e2", "search", mode="preregistered_adaptive", multiplicity="algorithmic",
        controller=long(70, "rank candidates by the frozen validation objective and allocate the next trial by UCB"),
        stopping_conditions=["candidate_evaluations budget is exhausted", "registered no-improvement rule fires"],
        why_multiple=long(60, "candidate selection is the method that produces the delivered architecture"),
        limits={"candidate_evaluations": 8, "gpu_hours": 2},
        launch=f'"{PY}" train.py search --sweep')]


def e2_bad_search_stages(d):
    return [std_stage("e2-bad", "search", mode="preregistered_adaptive",
                      multiplicity="single", launch=f'"{PY}" train.py search --sweep')]


def h1_merge_stages(d):
    return [std_stage(
        "h1", "merge", multiplicity="algorithmic",
        why_multiple=long(60, "all parent components are required inputs to the delivered merged model"),
        limits={"wallclock_minutes": 45, "models_processed": 2})]


def build_rounds():
    R("R001", [lane("e1", "exploit", 3, ["baseline"], outcome=("up", 0.01),
                    stages_fn=lambda d: [std_stage("e1", "train", key=SK_SHARED)])],
      best=0.610)
    R("R002", [lane("e2", "exploit", 3, [("lane", "e1")], outcome=("up", 0.01), sleep=2.5,
                    stages_fn=e2_search_stages,
                    plan_neg=[(e2_bad_search_stages,
                               ["FIELD_TOO_SHORT", "SPEC_STAGE_STOPPING", "SPEC_MULTIPLICITY_UNDECLARED"])]),
               lane("e3", "exploit", 3, [("lane", "e1")], outcome=("flat",), sleep=2.5),
               lane("plt1", "platform", 2, [], platform=True, sleep=2.5,
                    stages_fn=lambda d: [std_stage("plt1", "build", kind="dataset")])],
      best=0.620)
    R("R003", [lane("rf1", "reform", 3, [("lane", "e2")], outcome=("up", 0.01),
                    dims=L3, search_origin="theory_derived"),
               lane("e4", "exploit", 3, [("lane", "e2")], outcome=("flat",),
                    stages_fn=e4_stages,
                    plan_neg=[(e4_bad_stages, ["SPEC_ARTIFACT_REUSE_IGNORED"]),],
                    search_origin="repair")],
      best=0.630)
    R("R004", [lane("h1", "hybrid", 3, [("lane", "e2"), ("lane", "rf1"), ("lane", "plt1")],
                    outcome=("up", 0.01), hybrid=True, stages_fn=h1_merge_stages),
               lane("e5", "exploit", 3, [("lane", "rf1")], outcome=("flat",))],
      best=0.640)
    R("R005", [lane("w1", "wildcat", 4, [], outcome=("above", 0.01), dims=L4,
                    theory=[("T", {"parent_sel": "baseline"}),
                            ("C", {"good": {"verdict": "REVISE"}}),
                            ("T", {"parent_sel": "baseline", "response": True}),
                            ("C", {"good": {"verdict": "PROCEED"}})],
                    search_origin="theory_derived"),
               lane("e6", "exploit", 3, [("lane", "h1")], outcome=("flat",))],
      best=0.650)
    R("R006", [lane("h2", "hybrid", 3, [("lane", "h1"), ("lane", "w1")],
                    outcome=("up", 0.01), hybrid=True),
               lane("plt2", "platform", 2, [], platform=True, launch_mode="completed",
                    stages_fn=lambda d: [std_stage("plt2", "build", kind="index")])],
      best=0.660)
    R("R007", [lane("e7", "exploit", 3, [("lane", "h2")], outcome=("down", 0.008), lessons=True,
                    search_origin="repair"),
               lane("rfa", "reform", 3, [("lane", "h2")], outcome=("flat",),
                    dims=L3, search_origin="core_synthesis")],
      best=0.660)
    R("R008", [lane("e8", "exploit", 3, [("lane", "h2")], outcome=("flat",)),
               lane("plt3", "platform", 2, [], platform=True, launch_mode="completed",
                    stages_fn=lambda d: [std_stage("plt3", "build", kind="dataset")])],
      best=0.660)
    R("R009", [lane("rfb", "reform", 3, [("lane", "h2")], outcome=("flat",),
                    dims=L3, search_origin="theory_derived")],
      neg=[([{"name": "lazy", "intent": "exploit", "min_level": 2, "parents_sel": [("lane", "h2")]}],
            ["PORTFOLIO_STAGNATION_REQUIRES_REFORM"])],
      best=0.660)
    R("R010", [lane("w2", "wildcat", 4, [], outcome=("at",), dims=L4,
                    theory=[("T", {"parent_sel": "baseline"}),
                            ("C", {"good": {"verdict": "REVISE"}}),
                            ("T", {"parent_sel": "baseline", "response": True}),
                            ("C", {"good": {"verdict": "PROCEED"}})],
                    search_origin="theory_derived")],
      best=0.660)
    R("R011", [lane("m1", "moonshot", 4, [], outcome=("above", 0.02), dims=L4NB,
                    stages_fn=m1_stages, theory_rigor="full",
                    theory=[("T", {"parent_sel": "baseline", "moonshot": True}),
                            ("C", {"pre": [({"verdict": "PROCEED"}, ["CHALLENGE_DEEP_MIN_CYCLES"]),
                                           ({"verdict": "READ", "topics": TOPICS_M1, "bad": "no_topics"},
                                            ["CHALLENGE_READ_TOPICS"])],
                                   "good": {"verdict": "READ", "topics": TOPICS_M1}}),
                            ("DR", {"topics": TOPICS_M1, "neg_uncovered": True}),
                            ("T", {"parent_sel": "baseline", "moonshot": True, "response": True}),
                            ("C", {"good": {"verdict": "PROCEED"}})],
                    search_origin="theory_derived")],
      neg=[([{"name": "lazy-reform", "intent": "reform", "min_level": 3,
              "parents_sel": [("lane", "h2")]}],
            ["PORTFOLIO_STAGNATION_REQUIRES_MOONSHOT"])],
      retire=lambda d: [{"node": NODEQ["e7"], "reason": "pruned",
                         "note": long(70, "the lineage premise was refuted at root cause and holds no promise")},
                        {"node": NODEQ["e6"], "reason": "archived",
                         "note": long(60, "inconclusive side branch kept for the record but out of play")}],
      best=0.680, post="post_r011")
    R("R012", [lane("e10", "exploit", 3, [("lane", "m1")], outcome=("up", 0.01))],
      neg=[([{"name": "necro", "intent": "exploit", "min_level": 2,
              "parents_sel": [("lane", "e7")]}],
            ["PORTFOLIO_PARENT_PRUNED"])],
      pre_good="revive_e7", best=0.690)
    R("R013", [lane("h3", "hybrid", 3, [("lane", "m1"), ("lane", "h2"), ("lane", "e7"), ("lane", "plt2")],
                    outcome=("up", 0.02), hybrid=True),
               lane("e11", "exploit", 3, [("lane", "e10")], outcome=("flat",),
                    search_origin="repair")],
      best=0.700)
    R("R014", [lane("e12", "exploit", 3, [("lane", "h3")], outcome=("up", 0.01), sketch_garbage=3),
               lane("rfc", "reform", 3, [("lane", "e10")], outcome=("flat",),
                    dims=L3, search_origin="repair")],
      best=0.710)
    R("R015", [lane("w3", "wildcat", 4, [], outcome=("at",), dims=L4,
                    theory=[("T", {"parent_sel": "baseline"}),
                            ("C", {"good": {"verdict": "REVISE"}}),
                            ("T", {"parent_sel": "baseline", "response": True}),
                            ("C", {"good": {"verdict": "PROCEED"}})],
                    search_origin="theory_derived"),
               lane("e13", "exploit", 3, [("lane", "e12")], outcome=("flat",),
                    search_origin="repair")],
      best=0.710, post="post_r015")
    R("R016", [lane("e14", "exploit", 3, [("lane", "e12")], outcome=("down", 0.008), lessons=True)],
      best=0.710)
    R("R017", [lane("rfe", "reform", 3, [("lane", "e12")], outcome=("flat",),
                    dims=L3)],
      best=0.710)
    R("R018", [lane("rff", "reform", 3, [("lane", "h3")], outcome=("flat",),
                    dims=L3, search_origin="theory_derived")],
      best=0.710)
    R("R019", [lane("m2", "moonshot", 4, [], outcome=("above", 0.02), dims=L4NB,
                    theory=[("T", {"parent_sel": "baseline", "moonshot": True}),
                            ("C", {"good": {"verdict": "REVISE"}}),
                            ("T", {"parent_sel": "baseline", "moonshot": True, "response": True}),
                            ("C", {"good": {"verdict": "PROCEED"}})],
                    search_origin="theory_derived")],
      neg=[([{"name": "lazy-reform2", "intent": "reform", "min_level": 3,
              "parents_sel": [("lane", "h3")]}],
            ["PORTFOLIO_STAGNATION_REQUIRES_MOONSHOT"])],
      best=0.730)
    R("R020", [lane("w4", "wildcat", 4, [], outcome=("at",), dims=L4,
                    theory=[("T", {"parent_sel": "baseline"}),
                            ("C", {"good": {"verdict": "REVISE"}}),
                            ("T", {"parent_sel": "baseline", "response": True}),
                            ("C", {"good": {"verdict": "PROCEED"}})],
                    search_origin="theory_derived"),
               lane("h4", "hybrid", 3, [("lane", "m2"), ("lane", "e12")],
                    outcome=("up", 0.01), hybrid=True)],
      best=0.740)


FAULTS[("e4", "finetune")] = 1
FAULTS[("e13", "train")] = 3


# ---------------------------------------------------------------- dispatcher
def frontier_best(d):
    fr = egraph.frontier(d.graph(), d.store().load_config())
    return max(egraph.primary_score(n, "auc") or 0.0 for n in fr)


def portfolio_entry(d, ldef):
    origin = ldef.get("search_origin") or (
        "constructive" if ldef.get("intent") in ("wildcat", "moonshot", "hybrid", "platform")
        else "repair")
    row = {"name": ldef["name"], "intent": ldef["intent"], "min_level": ldef["min_level"],
           "experiment_purpose": "candidate", "search_origin": origin,
           "bottleneck_ids": ["B1"] if origin == "repair" else [],
           "parents": [resolve_sel(s) for s in ldef["parents_sel"]]}
    if origin == "theory_derived":
        row["theory_rigor"] = ldef.get("theory_rigor") or "partial"
    return row


def handle_open_round(d, out, rid):
    rd = ROUNDS[rid]
    for bad_lanes, codes in rd["neg"]:
        M.w_portfolio(d, out, rid, [portfolio_entry(d, b) for b in bad_lanes])
        sub_rej(d, out, *codes)
    if rd["pre_good"] == "revive_e7":
        evo = HERE.parent / "engine" / "evo.py"
        p = subprocess.run([PY, str(evo), "--repo", str(d.repo), "revive", "--node", NODEQ["e7"],
                            "--note", "user reopens the lineage for hybridization"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        ok(p.returncode == 0, f"revive CLI: {p.stderr}")
        arts = [a for a in d.reg()["artifacts"] if a["node"] == NODEQ["e7"]]
        ok(arts and all(a["status"] == "available" for a in arts), "revive restored artifacts")
    M.w_portfolio(d, out, rid, [portfolio_entry(d, l) for l in rd["lanes"]])
    sub_ok(d, out)


def model_parents_of(d, beh):
    out = []
    for s in beh["parents_sel"]:
        pid = resolve_sel(s)
        if d.node(pid)["role"] != "platform":
            out.append(pid)
    return out


def all_lane_cards(d, lid):
    return [c for c in eutil.read_jsonl(d.repo / ".evo/evidence/MECH_CARDS.jsonl")
            if c.get("lane") == lid]


def enrich_constructive_cards(d, lid):
    """Write attempt-bound CA# edges without mutating reusable M# paper facts."""
    M.ensure_collision_audits(d, lid)


def handle_deep_read(d, out, lid, beh):
    lane_rec = d.lane(lid)
    creating_palette = (lane_rec.get("search_origin") == "core_synthesis"
                        and not lane_rec.get("core_palette_path"))
    budgets = d.store().load_config().get("budgets", {})
    if beh["intent"] == "moonshot":
        required_need = int(budgets.get("mech_cards_min_moonshot", 4))
    elif lane_rec.get("search_origin") == "theory_derived":
        required_need = int(budgets.get("mech_cards_min_theory_derived", 2))
    elif lane_rec.get("search_origin") in ("constructive", "core_synthesis"):
        required_need = int(budgets.get("mech_cards_min_constructive", 2))
    else:
        required_need = int(budgets.get("mech_cards_min_per_lane", 2))
    # The stress fixture deliberately reads four cores for any L4 program even
    # when the low-cost regression preset requires fewer.
    need = max(required_need, 4 if beh["min_level"] >= 4 else 2)
    if lane_rec.get("required_topics"):
        step = beh["theory"].pop(0)
        ok(step[0] == "DR", f"expected DR step for {beh['name']}, got {step}")
        if step[1].get("neg_uncovered"):
            M.w_mech_cards(d, lid, 1, ["E002"])
            sub_rej(d, out, "MECH_TOPIC_UNCOVERED")
        missing = max(0, need - len(all_lane_cards(d, lid)))
        if missing:
            M.w_mech_cards(d, lid, missing, ["E001", "E002", "E005", "E003"],
                           topics=step[1]["topics"])
        beh["mech"] = [c["id"] for c in all_lane_cards(d, lid)]
        sub_ok(d, out)
        return
    prior = len(all_lane_cards(d, lid))
    if required_need >= 4 and prior == 0:
        # v9: the deep reading program binds any L4 lane, wildcats included
        M.w_mech_cards(d, lid, 3, ["E001", "E002", "E005"])
        sub_rej(d, out, "MECH_COUNT")
    missing = max(0, need - len(all_lane_cards(d, lid)))
    if missing:
        M.w_mech_cards(d, lid, missing, ["E003", "E001", "E002", "E005"])
    enrich_constructive_cards(d, lid)
    beh["mech"] = [c["id"] for c in all_lane_cards(d, lid)]
    sub_ok(d, out)
    if creating_palette:
        frozen = d.lane(lid)
        palette_rel = frozen.get("core_palette_path")
        provenance_rel = frozen.get("core_palette_provenance_path")
        palette = json.loads((d.repo / palette_rel).read_text(encoding="utf-8"))
        provenance = json.loads((d.repo / provenance_rel).read_text(encoding="utf-8"))
        palette_text = json.dumps(palette, ensure_ascii=False)
        ok(len(palette.get("cores") or []) >= 2
           and all(re.fullmatch(r"CP\d{2}", str(row.get("id") or ""))
                   for row in palette["cores"]),
           "core synthesis freezes multiple anonymous actual-work cores before ideation")
        ok(not re.search(r"https?://|\b[EM]\d{3}\b|arxiv", palette_text, re.I)
           and provenance.get("visibility") == "audit_only_not_generator_input"
           and len(provenance.get("sources") or []) == len(palette["cores"]),
           "palette hides paper identity while a separate audit sidecar retains exact provenance")
        ok(not M.eseal.verify(d.repo, frozen.get("core_palette_seal"),
                              label="core palette", require_working=True),
           "anonymous palette and provenance sidecar are jointly content-sealed")


def handle_sketch(d, out, lid, beh):
    if beh["sketch_garbage"] > 0:
        beh["sketch_garbage"] -= 1
        wt(d.repo, out["outputs"][0], "not json at all {")
        r = d.submit(out["task"])
        ok(r["kind"] == "rejected", f"garbage sketch rejected for {beh['name']}")
        return
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    n_lessons = sum(1 for ln in bundle.splitlines() if ln.strip().startswith("- [LS"))
    ok(n_lessons <= 12, f"lesson bundle cap respected: {n_lessons}")
    lane_rec = d.lane(lid)
    if lane_rec.get("search_origin") == "core_synthesis":
        task = next(t for t in d.state()["tasks"] if t.get("id") == out["task"])
        input_paths = [str(row[0]) for row in ((task.get("_render") or {}).get("inputs") or [])]
        ok(lane_rec["core_palette_path"] in input_paths
           and lane_rec["core_palette_provenance_path"] not in input_paths
           and ".evo/evidence/MECH_CARDS.jsonl" not in input_paths
           and ".evo/evidence/EVIDENCE.jsonl" not in input_paths,
           "core-synthesis ideation sees only the anonymous palette, never paper identities or its provenance sidecar")
    M.w_sketches(d, out, lid, beh["dims"], beh["mech"],
                 hybrid_parents=model_parents_of(d, beh) if beh["hybrid"] else None,
                 reframe=beh["intent"] == "moonshot" or beh["min_level"] >= 4)
    data = json.loads((d.repo / out["outputs"][0]).read_text(encoding="utf-8"))
    baseline = json.loads((d.repo / ".evo/profile/BASELINE_PROGRAM.json").read_text(encoding="utf-8"))
    raw = json.dumps(baseline, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    data["baseline_program_digest"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    for candidate in data["sketches"]:
        ok(eprogram.compute_level(candidate) >= beh["min_level"],
           f"{beh['name']}/{candidate['sketch_id']} carries its L{beh['min_level']} contract")
        if beh["platform"]:
            ok(candidate.get("program") and not candidate.get("effect_case") and
               not candidate.get("claim_scope"),
               f"{beh['name']}/{candidate['sketch_id']} is a claim-free platform program")
        else:
            ok(candidate.get("program") and candidate.get("novelty") and candidate.get("effect_case"),
               f"{beh['name']}/{candidate['sketch_id']} is a complete scientific program")
        ok(candidate["program"].get("scientific_parents") == model_parents_of(d, beh),
           f"{beh['name']}/{candidate['sketch_id']} binds the exact scientific parents")
        ok(candidate["program"].get("operators"),
           f"{beh['name']}/{candidate['sketch_id']} carries a forward operator graph")
        if beh["min_level"] >= 3 and not beh["platform"]:
            ok(eprogram.kernel_ids(candidate), f"{beh['name']}/{candidate['sketch_id']} has a kernel")
            ok(candidate["novelty"].get("kind") in eprogram.RESEARCH_NOVELTY,
               f"{beh['name']}/{candidate['sketch_id']} carries research novelty independently of scope")
        if lane_rec.get("search_origin") == "core_synthesis":
            ok(len(set(candidate.get("synthesis_core_ids") or [])) >= 2
               and len((candidate.get("synthesis_relation") or {}).get("discarded_shells") or [])
                   == len(set(candidate.get("synthesis_core_ids") or [])),
               f"{beh['name']}/{candidate['sketch_id']} transforms multiple cores and explicitly discards their shells")
    wj(d.repo, out["outputs"][0], data)
    sub_ok(d, out)


def write_tournament_v2(d, out, lid, beh, winner="K1"):
    # Keep the long-horizon suite on the exact same current-attempt collision
    # protocol as the focused suite.  In particular, neighbors are resolved
    # through CA# edges, never through a hard-coded paper/card pairing.
    M.w_tournament(d, out, lid, winner)


def is_theory_lane(beh):
    return beh["search_origin"] == "theory_derived" or beh["intent"] in THEORY_INTENTS


THEORY_Q1 = "the coupled value state changes both the learning update and the deployed inference relation"
THEORY_Q2 = "overlap failure on rare actions is the explicit boundary where the claimed estimator stops identifying value"


def write_theory_v2(d, out, lid, *, response_from=None):
    lane_rec = d.lane(lid)
    lines = []
    symbols = ["W_cf", "pi_log", "V_hat", "W_cf", "V_hat"]
    for i, sym in enumerate(symbols, 1):
        premise = "A1" if i == 1 else ("A2, S1" if i == 2 else f"S{i - 1}")
        marker = " [establishes: Want]" if i == len(symbols) else ""
        lines.append(
            f"- S{i} [from {premise}]: the coupled estimator constrains {sym} at derivation step {i}{marker} "
            f"; reads: step {i} transfers the identified value relation into an executable design constraint "
            f"; fails-if: overlap or resource matching fails on the rare-action slice")
    derivation = (
        "A1: logged propensities are correct on the exploration slice. "
        "A2: pi_log overlaps the target policy wherever W_cf affects the registered decision.\n" +
        "\n".join(lines) + "\n" +
        long(180, "Together the steps show why one normalized state must mediate both the update and inference, and why an independent weighting add-on cannot establish the wanted result."))
    sections = [
        ("Obstruction or desiderata", long(120, THEORY_Q2 + " The desired result must improve the frozen target without buying the gain from extra data, parameters or hidden calls.")),
        ("Result", long(120, THEORY_Q1 + " Under A1 and A2 the resulting estimator controls the exposure bias while preserving the external prediction contract.")),
        ("Derivation", derivation),
        ("Design consequences", long(120, "KC1 must sit inside the shared state transition; the program must route propensities into training and reuse that same state at inference rather than attach a post-hoc calibrator.")),
        ("Ruled-out alternatives", long(110, "independent importance weighting, an auxiliary calibration head and a larger encoder cannot satisfy the result because none changes the inference-defining learned object.")),
        ("Executable obligations",
         "- DO1: implement KC1 through OP2 so the exposure-sensitive update changes the actual value state.\n"
         "- DO2: make the inference path read that mapped value state and expose its registered intermediate."),
        ("Discriminating predictions", long(90, "TP1: rare-action calibration moves before aggregate auc under the coupled update. TP2: deleting KC1 removes both that intermediate movement and the ranking gain.")),
        ("Scope and failure conditions", long(110, "the result applies only where A1 and A2 hold, the action set remains fixed and the resource comparison is matched; support collapse or evaluator drift invalidates it.")),
    ]
    if response_from is not None:
        prev = (d.repo / response_from).read_text(encoding="utf-8")
        ok(M.CMARK in prev, "the previous challenge exposes a literal response anchor")
        sections.append(("Response to challenge",
                         long(100, "the revised chain makes the weak identification step explicit and binds its failure to the measured support condition") +
                         f"\nQUOTE: {M.CMARK}\n"))
    wt(d.repo, out["outputs"][0], M.md(*sections))
    if str(lane_rec.get("formal_kind") or "") == "full":
        toy_rel = out["outputs"][0].rsplit("/", 1)[0] + "/TOY_CHECK.py"
        wt(d.repo, toy_rel,
           "v = sum(1.0 / (i + 1) for i in range(8))\n"
           "assert v > 1.0, 'S1: self normalization keeps the estimate positive'\n"
           "w = v / 8.0\n"
           "assert w <= 1.0, 'S2: the normalized weight stays bounded'\n"
           "print('verified S1 S2 on the toy instance')\n"
           "print('TOY_CHECK_OK')\n")


def write_challenge_v2(d, out, lid, verdict, *, topics=None, bad=None):
    lane_rec = d.lane(lid)
    theory = (d.repo / lane_rec["theory_path"]).read_text(encoding="utf-8")
    ok(THEORY_Q1 in theory and THEORY_Q2 in theory, "challenge quotes the actual theory")
    sections = [
        ("Premise audit", long(90, "A1 is vulnerable to propensity estimation error and A2 is vulnerable to support collapse; both are observable rather than rhetorical assumptions.")),
        ("Derivation attack", M.CMARK + ". " + long(100, "The attack targets whether S2 truly transfers overlap into the normalized state without hiding a resource-dependent regularizer.")),
        ("Design consequence audit", long(90, "DO1 and DO2 name executable obligations and KC1 is the same kernel the eventual program must implement, so the result constrains code.")),
        ("Alternative explanation", long(90, "a larger effective sample or an auxiliary calibrator could mimic the end metric, but the registered intermediate and fixed resources distinguish those alternatives.")),
        ("Prediction audit", long(90, "TP1 and TP2 separate the coupled-state result from coincidental auc movement; a flat calibration slope would directly refute the mechanism.")),
        ("Verdict rationale", long(90, f"the weakest identification and implementation links were attacked explicitly, yielding the registered {verdict} decision for this cycle.")),
    ]
    if lane_rec.get("formal"):
        sections.append(("Step audit", long(90, "S2 is the weakest numbered step because it imports overlap into the estimator bound; the next revision must expose its exact support dependence.")))
    if verdict == "PROCEED":
        sections.append(("Strongest surviving objection", long(90, "rare-action propensity estimates may be biased enough to preserve the algebra while muting the predicted intermediate in the real frozen slice.")))
    if verdict == "READ":
        body = long(65, "the following core-work questions must be resolved before the support argument can proceed") + "\n"
        if bad != "no_topics":
            body += "".join(f"- topic: {topic}\n" for topic in (topics or []))
        sections.append(("Required reading", body))
    text = "VERDICT: " + verdict + "\n\n" + M.md(*sections) + \
           f"\nQUOTE: {THEORY_Q1}\nQUOTE: {THEORY_Q2}\n"
    wt(d.repo, out["outputs"][0], text)


def handle_theorize(d, out, lid, beh):
    step = beh["theory"].pop(0)
    ok(step[0] == "T", f"expected T step for {beh['name']}, got {step}")
    kw = dict(step[1])
    sel = kw.pop("parent_sel", "baseline")
    parent_ref = "baseline" if sel == "baseline" else resolve_sel(sel)
    resp = None
    if kw.pop("response", False):
        lane_rec = d.lane(lid)
        cyc = int(lane_rec["theory_cycle"])
        resp = f".evo/rounds/{lane_rec['round']}/lanes/{lid}/CHALLENGE_c{cyc - 1}.md"
    write_theory_v2(d, out, lid, response_from=resp)
    sub_ok(d, out)


def handle_challenge(d, out, lid, beh):
    step = beh["theory"].pop(0)
    ok(step[0] == "C", f"expected C step for {beh['name']}, got {step}")
    for kw, codes in step[1].get("pre", []):
        write_challenge_v2(d, out, lid, kw["verdict"], topics=kw.get("topics"), bad=kw.get("bad"))
        sub_rej(d, out, *codes)
    good = step[1]["good"]
    write_challenge_v2(d, out, lid, good["verdict"], topics=good.get("topics"))
    sub_ok(d, out)


def handle_mature(d, out, lid, beh):
    moon = beh["intent"] == "moonshot"
    l4 = beh["min_level"] >= 4
    est = frontier_best(d)
    lane_rec = d.lane(lid)
    sdata = json.loads((d.repo / lane_rec["sketches_path"]).read_text(encoding="utf-8"))
    winner = next(s for s in sdata["sketches"] if s["sketch_id"] == lane_rec["winner_sketch"])
    idx = {n["id"]: n for n in d.graph()["nodes"]}
    model_parents = [p for p in lane_rec.get("parents", []) if idx[p].get("role") != "platform"]
    platform_parents = [p for p in lane_rec.get("parents", []) if idx[p].get("role") == "platform"]
    sibling_rows = [
        {"node": node["id"],
         "difference": long(65, f"the frozen kernel and operator graph differ from sibling {node['id']} under the same parent contract")}
        for node in egraph.siblings(d.graph(), model_parents)
        if node.get("lane") != lid
    ]
    meta = {
        "idea": lane_rec["idea"], "lane": lid,
        "title": f"program-bound idea {lane_rec['idea']} for {beh['name']}",
        "parents": model_parents, "platforms_consumed": platform_parents,
        "predictions": [] if beh["platform"] else M.preds_for(est),
        "siblings_distance": sibling_rows,
    }
    level = eprogram.compute_level(winner)
    copied_fields = ["change_scope", "program", "novelty", "theory_role"]
    if not beh["platform"]:
        copied_fields.extend(("effect_case", "claim_scope"))
    if "theory_rigor" in winner:
        copied_fields.append("theory_rigor")
    if "theory_obligations" in winner:
        copied_fields.append("theory_obligations")
    for field in copied_fields:
        meta[field] = json.loads(json.dumps(winner[field]))
    if winner.get("theory_role") != "none":
        meta["theory_target"] = winner["theory_target"]
        meta["theory_doc"] = lane_rec.get("theory_path")
    else:
        meta.pop("theory_target", None)
        meta.pop("theory_doc", None)
    meta.update({
        "sketch_id": lane_rec["winner_sketch"],
        "search_origin": lane_rec["search_origin"],
        "program_digest": eprogram.candidate_digest(winner),
        "kernel_hash": eprogram.kernel_fingerprint(winner),
        "level": level,
        "experiment_purpose": "candidate",
        "prior_art_card_ids": list(beh["mech"][:2]),
        "bottleneck_ids": list(lane_rec.get("bottleneck_ids") or []),
        "metric_bridge_needed": False,
        "external_interface_changed": False,
    })
    if lane_rec["search_origin"] == "repair":
        meta["diagnosis_digest"] = lane_rec["diagnosis_digest"]
        meta["hypothesis_ids"] = list(winner["hypothesis_ids"])
    else:
        for repair_only in ("diagnosis_digest", "hypothesis_ids", "move"):
            meta.pop(repair_only, None)
    if lane_rec.get("formal"):
        meta["problem_doc"] = lane_rec.get("problem_path")
    else:
        meta.pop("problem_doc", None)
    if beh["platform"]:
        meta.pop("claim_scope", None)
        meta.pop("mechanism_probe", None)
        meta["enables"] = [
            "future reformulation lanes consume the versioned shared scientific artifact",
            "hybrid programs use the registered artifact without silently recomputing it",
        ]
        meta["predictions"] = []
    else:
        research_kernel = str((winner.get("novelty") or {}).get("kind") or "") in eprogram.RESEARCH_NOVELTY
        if research_kernel:
            iid = lane_rec["idea"]
            meta["mechanism_probe"] = {
                "signal": long(50, "rare-action calibration slope produced by the coupled value-state update"),
                "expect": long(25, "the slope moves toward one before aggregate auc moves"),
                "mode": "same_run", "extra_eval_arms": 0,
                "artifact": f".evo/probes/{iid}/observation.json",
                "required_fields": ["calibration_slope"],
                "decision_rule": {"field": "calibration_slope", "aggregation": "mean",
                                  "comparison": "between", "lower": 0.9, "upper": 1.1},
                "decision": long(65, "a flat intermediate blocks descendants that reuse the claimed coupled state transition"),
                "value_of_information": long(80, "the signal separates the load-bearing kernel from a coincidental end-metric gain under the same training run"),
                "cheaper_modes_rejected": [],
            }
            meta.pop("attribution_waiver", None)
    min_assum = 3 if winner.get("theory_role") == "derivational" else 2
    meta["assumptions"] = [
        {"id": f"A{i}",
         "statement": long(55, f"assumption A{i} keeps overlap, labels and the resource-matched evaluation contract valid"),
         "source": "theory" if winner.get("theory_role") == "derivational" else
                   ("dossier" if i % 2 else "profile")}
        for i in range(1, min_assum + 1)
    ]
    meta["nearest_published"] = {
        "paper": "E001",
        "difference": long(105, "the closest program applies propensity weights while leaving its learned object and inference semantics intact; this winner couples both through one state relation"),
    }
    wj(d.repo, out["outputs"][1], meta)

    card = beh["mech"][0]
    aid_walk = " ".join(f"{a['id']}: {a['statement']}" for a in meta["assumptions"])
    if beh["platform"]:
        sections = [
            ("Scientific program", long(150, M.IMARK1) + " " +
             long(120, "The frozen build program produces one versioned reusable artifact with a registered consumer interface and lineage.")),
            ("Enabling capability", long(130, "Future variants reuse the shared representation and hybrid programs consume the registered artifact without silently rebuilding the same state")),
            ("Operational and resource contract", long(130, "The artifact URI version compatibility build budget storage footprint invocation cost and maintenance boundary are fixed before consumer use")),
            ("Prior-art boundary", long(120, "The nearest audited infrastructure lacks the same versioned lineage-bound consumer contract and avoided-work guarantee") + f" [{card}]"),
            ("Consumer/use falsification", long(120, "The claim fails if a declared downstream consumer cannot load the artifact through the frozen interface or if reuse does not avoid the promised duplicated work")),
            ("Implementation sketch", long(110, "Build and register the immutable artifact publish its compatibility metadata and verify one representative consumer invocation in the isolated workarea")),
            ("Risks", long(110, M.IMARK2 + " Version drift stale lineage metadata or an unusable consumer interface would invalidate enablement.")),
        ]
    else:
        sections = [
            ("Scientific program", long(150, M.IMARK1) + " " +
             long(120, "The typed objects, training transition, inference path and resource model are copied from the frozen tournament winner without redesign.")),
            ("Irreducible kernel", long(150, "KC1 is the load-bearing relation that makes one counterfactual value state determine both learning updates and deployed inference; removing it restores the old semantics") + f" [{card}]"),
            ("Effect and resource case", long(150, "The kernel changes the exposure-confounded update, predicts a measurable calibration intermediate and then a C1 gain while examples, parameters, steps and hidden calls stay matched")),
            ("Causal derivation", long(130, M.IMARK2 + " " + aid_walk) + " " + aid_walk),
            ("Prior-art boundary", long(120, "The nearest audited core shares importance weighting but cannot emulate the joint update-and-inference state transition without changing its scientific program") + f" [{card}]"),
            ("Predictions", long(110, "The preregistered numeric thresholds test the claimed target cells, and a flat calibration intermediate falsifies attribution even if aggregate auc fluctuates upward")),
            ("Implementation sketch", long(110, "Implement KC1 in the objective/state transition, preserve the external evaluator and map the exact kernel id through NODE_SPEC, build report and fidelity audit")),
            ("Risks", long(110, M.IMARK2 + " Resource mismatch, overlap failure or an uncoupled implementation would each invalidate the scientific claim.")),
        ]
        research_kernel = str((winner.get("novelty") or {}).get("kind") or "") in eprogram.RESEARCH_NOVELTY
        sections.append(("Mechanism check" if research_kernel else "Falsification experiment",
                         long(120, "Remove or observe the registered load-bearing state relation under the same run; its intermediate must move in the predicted direction before the gain is attributed")))
        if winner.get("theory_role") != "none":
            sections.append(("Theory consequences", long(130, "The surviving derivation constrains the same KC1 state relation, rules out independent post-hoc weighting and predicts failure when overlap breaks")))
        if beh["hybrid"]:
            sections.append(("Bridge", long(120, "The parents are not independently stitched: each parent state changes the other's update coefficients inside the shared normalized transition")))
        if lane_rec.get("formal"):
            sections.append(("Formal statement", long(150, "Given W_cf and pi_log under A1 and A2, the coupled estimator V_hat realizes the frozen program and establishes the registered observable bound")))
    wt(d.repo, out["outputs"][0], M.md(*sections))
    sub_ok(d, out)


def write_red_team_v2(d, out, lid):
    lane_rec = d.lane(lid)
    idea = (d.repo / f".evo/ideas/{lane_rec['idea']}.md").read_text(encoding="utf-8")
    ok(M.IMARK1 in idea and M.IMARK2 in idea, "mature program exposes literal red-team anchors")
    meta = json.loads((d.repo / f".evo/ideas/{lane_rec['idea']}.meta.json").read_text(encoding="utf-8"))
    if lane_rec.get("intent") == "platform":
        sections = [
            ("Program fidelity", long(100, "the mature contract preserves the exact artifact-producing program registry path compatibility metadata and consumer interface without redesign")),
            ("Enablement and load-bearing attack", long(110, "removing the versioned artifact or compatibility contract forces declared consumers to recompute state or fail initialization so the capability is load-bearing")),
            ("Operational and resource attack", long(110, "build storage invocation refresh and maintenance costs are explicit and no hidden duplicated training or consumer-side recomputation is omitted")),
            ("Consumer/use falsification", long(110, "a representative downstream consumer must load and use the registered artifact under the frozen interface otherwise the enablement claim is rejected")),
            ("Prior-art attack", long(110, "the nearest reusable infrastructure lacks the same lineage-bound artifact contract consumer interface and promised avoided work")),
            ("Verdict rationale", long(100, "the platform survives enablement operational consumer and prior-art attacks and may advance to implementation")),
        ]
    else:
        sections = [
            ("Program fidelity", long(100, "the mature contract exactly preserves the tournament program digest, object semantics, kernel and effect path; no narrative redesign was admitted")),
            ("Irreducibility attack", long(110, "independent reweighting plus calibration cannot emulate the shared state transition; deleting KC1 restores the logged-outcome update and removes the claimed capability")),
            ("Effect and resource attack", long(110, "the causal chain reaches C1 through a registered intermediate while data, parameter count, steps, inference work and external calls remain explicitly matched")),
            ("Prior-art attack", long(110, "the nearest audited work shares primitives but not the load-bearing program relation, so the core difference survives comparison to actual work rather than paper motivation")),
            ("Verdict rationale", long(100, "the complete executable program is non-reducible, resource-matched and falsifiable, so it may advance to implementation")),
        ]
        if meta.get("theory_role") != "none":
            sections.append(("Theory alignment", long(100, "the surviving theory constrains the same KC1 relation and predicts its failure boundary; it is neither decorative nor a substitute for the effect case")))
    sections.append(("Strongest surviving objection", long(90, "estimated propensities may violate overlap in the rarest slice and mute the registered intermediate despite correct implementation")))
    text = "VERDICT: ACCEPT\n\n" + M.md(*sections) + \
           f"\nQUOTE: {M.IMARK1}\nQUOTE: {M.IMARK2}\n"
    wt(d.repo, out["outputs"][0], text)


def handle_plan(d, out, lid, beh):
    role = econfig.INTENT_TO_ROLE[beh["intent"]]
    for bad_fn, codes in beh["plan_neg"]:
        M.w_plan(d, out, lid, role=role, workdir=f"workareas/{beh['name']}",
                 stages=bad_fn(d), code_parent=resolve_sel(beh["parents_sel"][0])
                 if role in ("variant", "hybrid") else "N001")
        sub_rej(d, out, *codes)
    beh["plan_neg"] = []
    mp = model_parents_of(d, beh)
    code_parent = mp[0] if role in ("variant", "hybrid") else "N001"
    M.w_plan(d, out, lid, role=role, workdir=f"workareas/{beh['name']}",
             stages=beh["stages_fn"](d) if beh["stages_fn"] else
             [std_stage(beh["name"], "train")],
             code_parent=code_parent,
             enables=["future lanes consume the shared product",
                      "hybrids initialize from the shared build"] if beh["platform"] else None)
    sub_ok(d, out)
    NODEQ[beh["name"]] = d.lane(lid)["node"]


def rewrite_build_report_v2(d, out, nid):
    node = d.node(nid)
    old = (d.repo / out["outputs"][0]).read_text(encoding="utf-8")
    old_sections = eutil.md_sections(old)
    idea = {}
    if node.get("idea_doc"):
        idea = json.loads((d.repo / node["idea_doc"].replace(".md", ".meta.json")).read_text(encoding="utf-8"))
    kids = eprogram.kernel_ids(idea)
    code_rows = []
    for kernel in eprogram.kernel_components(idea):
        kid = str(kernel["id"])
        code_rows.extend(f"- {opid} [{kid}] -> `mod_a.py`"
                         for opid in kernel.get("operator_refs") or [])
    code_map = "\n".join(code_rows)
    if not code_map:
        code_map = "- support implementation -> `mod_a.py`"
    code_map += "\n\n" + long(55, "Every listed load-bearing operator is realized at a verified code path and remains bound to its approved kernel identifier")
    sections = [
        ("Workarea", long(70, f"code for {nid} lives in {node.get('workdir')} and preserves the approved program digest")),
        ("Mechanism to code map", code_map),
        ("Deviations", long(60, "no scientific-program or kernel deviations were introduced; recovery only changes the bounded runtime batch configuration")),
        ("Self test", long(60, "the import check, flag check and kernel instrumentation paths pass in the isolated workarea")),
    ]
    probe = eutil.find_section(old_sections, "probe instrumentation")
    if probe:
        sections.append(("Probe instrumentation", probe))
    wiring = eutil.find_section(old_sections, "artifact wiring")
    if wiring:
        sections.append(("Artifact wiring", wiring))
    wt(d.repo, out["outputs"][0], M.md(*sections))


def handle_implement(d, out, nid, beh):
    node = d.node(nid)
    was_fix = bool(node.get("fix_needed"))
    if was_fix:
        if beh["name"] == "e4":
            # v9.2/v10 actual semantics (empirically identical on the untouched
            # v9.2 tree): a workflow-scope implementation revision BEGINS at fix
            # presentation - the cursor resets and prior stage artifacts are
            # invalidated immediately, because a workflow defect makes their
            # evidence suspect. The preserved failure CONTEXT is the routed
            # error note (asserted below) and the repeat-spend record.
            ok(node["stage_cursor"] == 0,
               f"workflow revision resets the cursor at fix presentation (cursor {node['stage_cursor']})")
            arts = [a for a in d.reg()["artifacts"] if a["node"] == nid]
            ok(len(arts) == 1 and arts[0]["stage"] == "distill" and arts[0]["status"] == "stale",
               f"the stage-1 artifact is invalidated with the workflow restart: {arts}")
            repeat = node.get("repeat_attempt") or {}
            ok(repeat.get("operation") == "workflow" and repeat.get("source_run"),
               f"the repeat-spend record names the whole-workflow replay: {repeat}")
        bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
        ok("CUDA out of memory" in bundle, "real failure note routed into fix bundle")
        M.do_fix_implement(d, out, nid)
    else:
        M.do_implement(d, out, nid)
        # do_implement writes stub train/eval scripts; restore the REAL ones and
        # commit so this node's captured commit (and its children) carry them
        wt(d.repo, f"{node['workdir']}/train.py", TRAIN_PY)
        wt(d.repo, f"{node['workdir']}/eval.py", EVAL_PY)
        wd = d.repo / node["workdir"]
        M.sh(wd, "git", "add", "-A")
        M.sh(wd, "git", "commit", "-q", "-m", f"real scripts for {nid}")
    rewrite_build_report_v2(d, out, nid)
    sub_ok(d, out)
    if was_fix and beh["name"] == "e4":
        fixed = d.node(nid)
        old_runs = [r for r in d.state()["runs"] if r.get("node") == nid]
        old_artifacts = [a for a in d.reg()["artifacts"] if a.get("node") == nid]
        ok(fixed["stage_cursor"] == 0 and fixed["replica_index"] == 0
           and all(r.get("superseded") for r in old_runs)
           and all(a.get("status") == "stale" for a in old_artifacts),
           "implementation revision 2 invalidates mixed-revision evidence and restarts the full workflow")


def write_fidelity_v2(d, out, nid):
    node = d.node(nid)
    meta = json.loads((d.repo / node["idea_doc"].replace(".md", ".meta.json")).read_text(encoding="utf-8"))
    rows = [
        f"- {kernel['id']} {opid} load-bearing implementation -> mod_a.py :: CODE: reweighting module for {nid}"
        for kernel in eprogram.kernel_components(meta)
        for opid in (kernel.get("operator_refs") or [])
    ]
    if not rows:
        rows = [f"- support implementation -> mod_a.py :: CODE: reweighting module for {nid}"]
    wt(d.repo, out["outputs"][0], "FIDELITY: FAITHFUL\n\n" + M.md(
        ("Claim map", "\n".join(rows)),
        ("Omissions and simplifications", long(70, "NONE-FOUND after checking every approved KC identifier against a literal committed code location")),
        ("Audit verdict", long(70, "the implementation realizes the frozen program kernel without replacing it by an easier independent module")),
    ))


def handle_conclude(d, out, nid, beh, role):
    if role == "baseline":
        M.w_conclude(d, out, nid, baseline=True)
    elif role == "platform":
        M.w_conclude(d, out, nid, platform=True)
    else:
        lessons = None
        if beh["outcome"][0] == "down":
            lessons = [{"scope": "lineage",
                        "statement": long(40, f"stacking a mechanism swap on {beh['parents_sel']} regressed the frontier"),
                        "evidence": long(30, f"node {nid} refuted its propensity assumption"),
                        "recommendation": long(30, "test propensity validity before stacking here")}]
        elif beh["lessons"]:
            lessons = [{"scope": "global",
                        "statement": long(40, f"lane {beh['name']} confirms the calibration channel argument"),
                        "evidence": long(30, f"node {nid} moved the metric as registered"),
                        "recommendation": long(30, "prefer calibrated counterfactual targets")}]
        M.w_conclude(d, out, nid, lessons=lessons)
    sub_ok(d, out)


def post_r011(d):
    e7 = NODEQ["e7"]
    ok(d.node(e7)["retire_reason"] == "pruned", "e7 pruned at retro")
    arts = [a for a in d.reg()["artifacts"] if a["node"] == e7]
    ok(arts and all(a["status"] == "stale" for a in arts), "pruned artifacts stale")
    ok(d.node(NODEQ["e6"])["retire_reason"] == "archived", "e6 archived")


def post_r015(d):
    e13 = NODEQ["e13"]
    node = d.node(e13)
    ok(node["status"] == "abandoned" and node["verdict"] == "failed",
       f"e13 abandoned after 3 real failures: {node['status']}/{node['verdict']}")
    fails = [e for e in d.events("stage_failed") if e.get("node") == e13]
    ok(len(fails) == 3, f"3 real failures recorded for e13: {len(fails)}")
    ok(not d.running(), "no orphan runs after abandonment")


POSTS = {"post_r011": post_r011, "post_r015": post_r015}


def handle_close(d, out, rid):
    rd = ROUNDS[rid]
    retire = rd["retire"](d) if callable(rd["retire"]) else rd["retire"]
    M.w_retro(d, out, rid, retire=retire)
    sub_ok(d, out)
    best = frontier_best(d)
    ok(abs(best - rd["best"]) < 1e-9, f"{rid}: frontier best {best} vs planned {rd['best']}")
    eng_fr = sorted(n["id"] for n in egraph.frontier(d.graph(), d.store().load_config()))
    ok(eng_fr == frontier_independent(d), f"{rid}: frontier cross-check {eng_fr}")
    if rd["post"]:
        POSTS[rd["post"]](d)
    d.doctor_clean(f"after {rid}")
    section(f"{rid} closed (best {best})")


def dispatch(d, out):
    typ = out["type"]
    s = task_subject(d, out)
    if typ == "project_scan":
        M.w_project_scan(d, out)
        sub_ok(d, out)
    elif typ == "configure":
        M.w_config(d, out, autonomy="full_auto", rounds_max=20, vcs="git", mode="research")
        cfg_path = d.repo / ".evo/config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["policy"]["research_min_structural_scope_share"] = 1.0
        cfg["policy"]["research_min_constructive_share"] = 0.5
        cfg["policy"]["scope_floor"].update({"exploit": 3, "hybrid": 3})
        wj(d.repo, ".evo/config.json", cfg)
        sub_ok(d, out)
    elif typ == "infra":
        M.w_infra(d, out)
        wj(d.repo, out["outputs"][1], M.infra_facts(slots=2))
        sub_ok(d, out)
    elif typ == "infra_interview":
        M.w_interview(d, out)
        sub_ok(d, out)
    elif typ == "infra_drill":
        # The helper now writes only the project canary plan/report and calls
        # ecanary.run.  The pass therefore comes from a real nonce-bound
        # subprocess receipt, never the old hand-authored per-surface logs.
        receipt = M.w_drills(d, out)
        ok(isinstance(receipt, dict) and receipt.get("status") == "passed"
           and receipt.get("task") == out["task"],
           f"bootstrap canary is engine-observed and bound to {out['task']}: {receipt}")
        sub_ok(d, out)
        active = d.state().get("infra_canary") or {}
        ok(active.get("status") == "passed" and active.get("task") == out["task"]
           and active.get("receipt_digest"),
           f"accepted bootstrap stores the active engine-owned canary receipt: {active}")
    elif typ == "fidelity":
        write_fidelity_v2(d, out, s["node"])
        sub_ok(d, out)
    elif typ == "profile":
        M.w_profile(d, out)
        sub_ok(d, out)
    elif typ == "dossier":
        M.w_dossier(d, out)
        sub_ok(d, out)
    elif typ == "rubric":
        M.w_rubric(d, out)
        sub_ok(d, out)
    elif typ == "baseline_spec":
        M.w_baseline_spec(d, out, s["node"])
        sub_ok(d, out)
    elif typ == "open_round":
        handle_open_round(d, out, s["round"])
    elif typ == "evidence":
        if s.get("prior_evidence_count", 0) == 0:
            M.w_evidence_initial(d)
        else:
            M.w_evidence_refresh(d)
        sub_ok(d, out)
    elif typ == "deep_read":
        handle_deep_read(d, out, s["lane"], lane_beh(d, s["lane"]))
    elif typ == "sketch":
        handle_sketch(d, out, s["lane"], lane_beh(d, s["lane"]))
    elif typ == "tournament":
        beh = lane_beh(d, s["lane"])
        write_tournament_v2(d, out, s["lane"], beh, "K1")
        sub_ok(d, out)
    elif typ == "pose":
        M.w_problem(d, out)
        sub_ok(d, out)
    elif typ == "theorize":
        handle_theorize(d, out, s["lane"], lane_beh(d, s["lane"]))
    elif typ == "challenge":
        handle_challenge(d, out, s["lane"], lane_beh(d, s["lane"]))
    elif typ == "mature":
        handle_mature(d, out, s["lane"], lane_beh(d, s["lane"]))
    elif typ == "red_team":
        write_red_team_v2(d, out, s["lane"])
        sub_ok(d, out)
    elif typ == "plan_node":
        handle_plan(d, out, s["lane"], lane_beh(d, s["lane"]))
    elif typ == "implement":
        nid = s["node"]
        handle_implement(d, out, nid, lane_beh(d, s["lane"]) if s.get("lane") else None)
    elif typ == "smoke":
        res = d.smoke(s["node"])
        ok(res["status"] == "pass", f"real smoke passes for {s['node']}: {res}")
        sub_ok(d, out)
    elif typ == "metric_bridge":
        M.w_bridge(d, out)
        sub_ok(d, out)
    elif typ == "stage_launch":
        handle_stage_launch(d, out, s)
    elif typ == "stage_watch":
        n = poll_and_report(d)
        if n == 0:
            time.sleep(0.05)
        r = d.submit(out["task"])
        ok(r["kind"] in ("waiting", "accepted"), f"watch submit: {r}")
    elif typ == "eval_launch":
        nid = s["node"]
        if d.node(nid)["role"] == "baseline":
            TARGET[nid] = BASELINE_Q
            wt(d.repo, "checkpoint_base.json", json.dumps({"quality": BASELINE_Q, "stage": "base"}))
        eval_real(d, out, nid)
        sub_ok(d, out)
    elif typ == "evaluate":
        nid = s["node"]
        eval_real(d, out, nid)
        sub_ok(d, out)
    elif typ == "conclude":
        nid = s["node"]
        node = d.node(nid)
        beh = lane_beh(d, s["lane"]) if s.get("lane") else None
        handle_conclude(d, out, nid, beh, node["role"])
    elif typ == "close_round":
        handle_close(d, out, s["round"])
    else:
        raise AssertionError(f"unhandled task type {typ}")


def handle_stage_launch(d, out, s):
    beh = lane_beh(d, s["lane"]) if s.get("lane") else None
    ok(beh is not None, "stage_launch always belongs to a lane node in this run")
    launch_stage_real(d, out, s["node"], beh)


def handle_gate(d, out):
    if out["gate_kind"] == "infra_confirm":
        d.decide(out["gate"], True, note="success, infrastructure and cumulative resources confirmed")
        return
    if out["gate_kind"] == "repeat_spend":
        # v9.2 core contract: a repeated external spend after a failed attempt
        # is user-owned in EVERY autonomy mode. The scenario intends the retry.
        d.decide(out["gate"], True,
                 note="reviewed the failed attempt; the whole-workflow replay is intended")
        return
    ok(out["gate_kind"] == "escalation", f"only bootstrap/escalation gates expected in full_auto: {out}")
    st = d.state()
    gate = next(g for g in st["gates"] if g["id"] == out["gate"])
    subj = gate.get("subject", {})
    if subj.get("task"):
        d.decide(out["gate"], True, note="reset and retry with the deficiencies in mind")
    elif subj.get("node"):
        d.decide(out["gate"], False, note="three real failures; the budget is spent, abandon the node")
    else:
        raise AssertionError(f"unexpected escalation subject {subj}")


# ---------------------------------------------------------------- pump + audits
def pump(d):
    guard = 0
    probe_at = 0
    while True:
        guard += 1
        ok(guard < 40000, "global pump guard")
        out = d.next()
        check_invariants(d, out)
        if out["kind"] == "done":
            return out
        if out["kind"] == "gate":
            handle_gate(d, out)
            continue
        if out["kind"] == "waiting":
            time.sleep(0.05)
            poll_and_report(d)
            continue
        # idempotence probe: with no runs in flight, a second `next` must return
        # the same open task
        if guard >= probe_at and not d.running():
            out2 = d.next()
            ok(out2.get("kind") == "task" and out2.get("task") == out["task"],
               f"next() idempotent on open task: {out['task']} vs {out2}")
            probe_at = guard + 40
        dispatch(d, out)


def final_audit(d):
    section("final audit sweep")
    g = d.graph()
    nodes = {n["id"]: n for n in g["nodes"]}
    ok(len(nodes) == 33, f"33 nodes built: {len(nodes)}")
    roles = {}
    for n in g["nodes"]:
        roles[n["role"]] = roles.get(n["role"], 0) + 1
    ok(roles == {"baseline": 1, "variant": 19, "hybrid": 4, "root": 6, "platform": 3},
       f"role census: {roles}")
    lanes = d.state()["lanes"]
    origins = {origin: sum(1 for lane_rec in lanes if lane_rec.get("search_origin") == origin)
               for origin in econfig.SEARCH_ORIGINS}
    ok(origins == {"repair": 5, "constructive": 17, "core_synthesis": 1,
                   "theory_derived": 9},
       f"all search origins exercised with a constructive majority and a real core synthesis lane: {origins}")
    core_lane = next(lane_rec for lane_rec in lanes if lane_rec.get("search_origin") == "core_synthesis")
    ok(not evalid.core_palette_contract_errors(d.eng().ctx(), core_lane),
       "core-synthesis palette, audit-only M/E provenance, joint seal and program upstream remain one exact contract")
    core_programs = json.loads((d.repo / core_lane["sketches_path"]).read_text(encoding="utf-8"))
    palette_ids = {row["id"] for row in json.loads(
        (d.repo / core_lane["core_palette_path"]).read_text(encoding="utf-8"))["cores"]}
    ok(all(set(candidate.get("synthesis_core_ids") or []).issubset(palette_ids)
           for candidate in core_programs["sketches"]),
       "every synthesized candidate remains digest-bound to real anonymous cores in its frozen palette")
    ok(any(lane_rec.get("search_origin") == "theory_derived"
           and lane_rec.get("formal_kind") == "full" for lane_rec in lanes),
       "portfolio-level full theory rigor survives into a theory-derived lane")
    idea_lanes = [lane_rec for lane_rec in lanes if lane_rec.get("intent") != "platform"]
    ok(all(int(lane_rec.get("min_level") or 0) >= 3 for lane_rec in idea_lanes),
       "every research idea lane carries an L3+ scope contract")
    ok(sum(lane_rec.get("search_origin") != "repair" for lane_rec in idea_lanes) / len(idea_lanes) >= 0.8,
       "constructive/theory-derived invention dominates the long horizon")
    # End-to-end immutable scientific-program binding: winner -> mature idea ->
    # NODE_SPEC -> graph node. This catches drift that prose-only stress tests
    # cannot see, including multi-parent hybrid programs.
    kernel_hashes = set()
    program_digests = set()
    theory_roles = set()
    full_programs = 0
    for n in g["nodes"]:
        if n["role"] == "baseline":
            continue
        meta = json.loads((d.repo / n["idea_doc"].replace(".md", ".meta.json")).read_text(encoding="utf-8"))
        spec = json.loads((d.repo / n["spec"]).read_text(encoding="utf-8"))
        lane_rec = d.lane(n["lane"])
        programs = json.loads((d.repo / lane_rec["sketches_path"]).read_text(encoding="utf-8"))
        winner = next(row for row in programs["sketches"] if row["sketch_id"] == lane_rec["winner_sketch"])
        digest = eprogram.candidate_digest(winner)
        ok(digest == meta["program_digest"] == spec["program_digest"] == n["program_digest"],
           f"{n['id']}: exact winner digest survives idea/spec/node transitions")
        ok(spec["program_ir"] == meta["program"], f"{n['id']}: forward program IR is copied exactly")
        ok(spec["novelty_kernel"] == meta["novelty"]["kernel"],
           f"{n['id']}: irreducible kernel is copied exactly")
        if n["role"] == "platform":
            ok("effect_case" not in meta and "claim_scope" not in meta,
               f"{n['id']}: platform omits model-performance claims")
        else:
            ok(spec["effect_case"] == meta["effect_case"],
               f"{n['id']}: typed effect/resource case is copied exactly")
        ok(meta.get("theory_rigor") == winner.get("theory_rigor"),
           f"{n['id']}: independent theory rigor is copied exactly")
        ok(meta.get("theory_obligations") == winner.get("theory_obligations")
           == spec.get("theory_obligations"),
           f"{n['id']}: theory DO# to KC#/OP# mappings are copied exactly")
        ok(spec["kernel_ids"] == eprogram.kernel_ids(meta) == n["kernel_ids"],
           f"{n['id']}: KC identifiers survive planning and graph creation")
        model_parents = [p for p in n.get("parents", []) if nodes[p].get("role") != "platform"]
        ok(meta["program"]["scientific_parents"] == model_parents,
           f"{n['id']}: scientific parents match the complex inheritance graph")
        ok(len(eprogram.operator_ids(meta)) >= 3,
           f"{n['id']}: forward program contains train/infer operators")
        if n["role"] != "platform":
            ok(meta["claim_scope"] == winner["claim_scope"],
               f"{n['id']}: pre-tournament claim scope is copied exactly")
            ok(meta["novelty"]["kind"] in eprogram.RESEARCH_NOVELTY,
               f"{n['id']}: research node has irreducible/paradigm novelty")
            resources = meta["effect_case"]["resources"]
            ok(set(resources["candidate"]) == set(eprogram.RESOURCE_AXES) == set(resources["comparator"]),
               f"{n['id']}: effect comparison covers all nine resource axes")
        kernel_hashes.add(meta["kernel_hash"])
        program_digests.add(meta["program_digest"])
        theory_roles.add(meta["theory_role"])
        full_programs += meta["change_scope"] == "full_program"
    ok(len(kernel_hashes) == 32 and len(program_digests) == 32,
       "all 32 evolved nodes have distinct immutable kernels and programs")
    ok(theory_roles == {"none", "explanatory", "derivational"},
       f"theory remains an independent optional axis: {theory_roles}")
    ok(full_programs >= 6, f"full architecture/program reconstruction exercised {full_programs} times")
    ok(max(sum(1 for p in n.get("parents", []) if nodes[p].get("role") != "platform")
           for n in g["nodes"]) >= 3,
       "a three-model-parent hybrid exercises nontrivial scientific inheritance")
    # every concluded model node's verdict must equal the recomputed one
    store = estore.Store(d.repo)
    ctx = evalid.Ctx(store, store.load_state(), store.load_config(),
                     store.load_graph(), store.load_artifacts())
    audited = 0
    for n in g["nodes"]:
        if n["role"] in ("baseline", "platform") or n["status"] != "concluded":
            continue
        m = json.loads((d.repo / f".evo/nodes/{n['id']}/eval/metrics.json").read_text(encoding="utf-8"))
        want, _ = evalid.computed_verdict(ctx, n, m)
        ok(n["verdict"] == want, f"{n['id']}: stored verdict {n['verdict']} == recomputed {want}")
        audited += 1
    ok(audited >= 25, f"audited {audited} concluded model nodes")
    # git ancestry of every implemented node
    checked = 0
    for n in g["nodes"]:
        if n["role"] == "baseline" or not n.get("branch") or not n.get("commit"):
            continue
        cp = nodes.get(n.get("code_parent") or "")
        ref = (cp or {}).get("commit")
        if ref:
            ok(evcs.is_ancestor(d.repo, ref, f"refs/heads/{n['branch']}"),
               f"{n['id']}: branch descends from code parent {cp['id']}")
            checked += 1
    ok(checked >= 25, f"git ancestry verified for {checked} nodes")
    # registry
    reg = d.reg()
    ok(len(reg["artifacts"]) == 32, f"32 artifacts registered: {len(reg['artifacts'])}")
    ok(not eartifact.check_registry(reg, set(nodes)), "registry clean")
    errs = eutil.read_jsonl(d.repo / ".evo/errors.jsonl")
    # A successful integrated canary no longer manufactures the old blocked
    # quota ER001.  The journal is exactly the four real subprocess crashes:
    # one e4 replay trigger followed by the three e13 abandonment attempts.
    error_ids = [row.get("id") for row in errs]
    ok(len(errs) == 4 and error_ids == ["ER001", "ER002", "ER003", "ER004"],
       f"error journal contains only the 4 real failures with contiguous ids: {error_ids}")
    ok(all("CUDA out of memory" in e["note"] for e in errs), "error notes carry the real stderr")
    # deep generations
    gens = egraph.compute_generations(g)
    ok(max(gens.values()) >= 8, f"deep generation chain: {max(gens.values())}")
    # rounds + improvement pattern
    hist = [r for r in d.state()["rounds"] if r.get("closed_at")]
    ok(len(hist) == 20, f"20 rounds closed: {len(hist)}")
    got = [r["improved"] for r in hist]
    want = [True] * 6 + [False] * 4 + [True] * 4 + [False] * 4 + [True] * 2
    ok(got == want, f"improvement trajectory matches the plan: {got}")
    ok(MAXRUN["seen"] >= 2, f"real training overlap observed: max concurrent {MAXRUN['seen']}")
    ok(SLOT_DEFERRAL["seen"],
       "a launch-ready real node was explicitly deferred while both approved workflow slots were full")
    ok(d.state()["phase"] == "done", "phase done")
    # render CLI once
    evo = HERE.parent / "engine" / "evo.py"
    p = subprocess.run([PY, str(evo), "--repo", str(d.repo), "render"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(p.returncode == 0, f"render CLI: {p.stderr}")
    # User views: the v2 dashboard is one self-contained projection over the
    # same graph/config/state authorities.  Keep this audit structural: DOM
    # layout and interaction belong to the separate real-browser acceptance.
    M.view_asserts(d, nodes=33, rounds_closed=20)
    data = M.dash_data(d)
    dashboard_path = d.repo / ".evo/views/DASHBOARD.html"
    dashboard_html = dashboard_path.read_text(encoding="utf-8")
    payload_match = re.search(r"const DATA = (.*?); /\*END-DATA\*/", dashboard_html, re.S)
    ok(payload_match is not None, "dashboard v2 keeps one parseable embedded JSON payload")
    payload_text = payload_match.group(1)
    ok(data.get("schema") == "evo.dashboard.v2", f"dashboard schema is v2: {data.get('schema')}")

    dashboard_nodes = data.get("nodes") or []
    dashboard_ids = [str(n.get("id") or "") for n in dashboard_nodes]
    dashboard_id_set = set(dashboard_ids)
    ok(len(dashboard_nodes) == data["counts"]["nodes"] == 33
       and len(dashboard_id_set) == len(dashboard_ids) and "" not in dashboard_id_set,
       "dashboard has exactly 33 uniquely identified nodes")
    ok(not data["runs"], "dashboard running-run projection settles empty at the end")
    ok(sum(1 for n in dashboard_nodes if n["retired"] or n["status"] == "abandoned")
       == data["counts"]["retired"], "dashboard retired count consistent")
    ok(len({n["gen"] for n in dashboard_nodes}) >= 9,
       "dashboard carries the deep generation axis")

    # Edges are exactly the node parent relation, not an independently drifting
    # rendering graph.  Platform styling is derived from the parent role.
    role_by_id = {n["id"]: n.get("role") for n in dashboard_nodes}
    parent_pairs = {(parent, n["id"])
                    for n in dashboard_nodes for parent in (n.get("parents") or [])}
    edge_rows = data.get("edges") or []
    edge_pairs = {(e.get("from"), e.get("to")) for e in edge_rows}
    parents_resolve = all(len(n.get("parents") or []) == len(set(n.get("parents") or []))
                          and set(n.get("parents") or []).issubset(dashboard_id_set)
                          for n in dashboard_nodes)
    platform_edges_match = all(bool(e.get("platform")) == (role_by_id.get(e.get("from")) == "platform")
                               for e in edge_rows)
    ok(parents_resolve and len(edge_rows) == len(edge_pairs)
       and edge_pairs == parent_pairs and platform_edges_match,
       "dashboard edges exactly match unique resolving parents and platform roles")

    # Both frontiers have independent engine meanings.  Audit the top-level
    # lists, legacy alias and per-node membership against fresh recomputation.
    cfg = d.store().load_config()
    frontiers = data.get("frontiers") or {}
    inheritance = list(frontiers.get("inheritance") or [])
    performance = list(frontiers.get("performance") or [])
    scientific = list(frontiers.get("scientific") or [])
    expected_inheritance = [n["id"] for n in egraph.frontier(g, cfg)]
    expected_performance = [n["id"] for n in egraph.performance_frontier(g, cfg)]
    frontier_refs_resolve = all(len(rows) == len(set(rows)) and set(rows).issubset(dashboard_id_set)
                                for rows in (inheritance, scientific, performance))
    memberships_match = all(
        bool((n.get("frontiers") or {}).get("inheritance")) == (n["id"] in set(inheritance))
        and bool((n.get("frontiers") or {}).get("performance")) == (n["id"] in set(performance))
        for n in dashboard_nodes)
    expected_active = "scientific" if econfig.is_research(cfg) else "performance"
    ok(frontier_refs_resolve and inheritance == scientific == data.get("frontier")
       and inheritance == expected_inheritance and performance == expected_performance
       and frontiers.get("active") == expected_active and memberships_match,
       "dashboard dual frontiers and every node membership match engine recomputation")

    # The contract projection must remain a complete, joinable D/T/C/G graph.
    contract = data.get("evaluation_contract") or {}
    contract_order = contract.get("order") or {}
    datasets = contract.get("datasets") or {}
    tasks = contract.get("tasks") or {}
    cells = contract.get("cells") or {}
    groups = contract.get("groups") or {}
    metrics = contract.get("metrics") or {}
    ordered_kinds = {"datasets": datasets, "tasks": tasks, "cells": cells, "groups": groups,
                     "metrics": metrics}
    order_complete = all(
        len(contract_order.get(kind) or []) == len(set(contract_order.get(kind) or []))
        and set(contract_order.get(kind) or []) == set(rows)
        for kind, rows in ordered_kinds.items())
    cell_joins = all(
        row.get("id") == cid and row.get("dataset") in datasets and row.get("task") in tasks
        and row.get("metric") in metrics and str(row.get("result_key") or "")
        for cid, row in cells.items())
    all_datasets_and_tasks_used = ({row.get("dataset") for row in cells.values()} == set(datasets)
                                   and {row.get("task") for row in cells.values()} == set(tasks))
    group_joins = all(row.get("id") == gid and bool(row.get("tasks"))
                      and set(row.get("tasks") or []).issubset(tasks)
                      for gid, row in groups.items())
    assessment_ref_errors = []
    for node in dashboard_nodes:
        assessment = node.get("evaluation") or {}
        for cid, row in (assessment.get("cells") or {}).items():
            definition = cells.get(cid) or {}
            if not definition or row.get("cell") != cid \
                    or row.get("metric") != definition.get("metric") \
                    or row.get("result_key") != definition.get("result_key"):
                assessment_ref_errors.append((node["id"], "cell", cid))
        for bucket in ("tasks", "goal_tasks"):
            for tid, row in (assessment.get(bucket) or {}).items():
                if tid not in tasks or row.get("id") != tid \
                        or not set(row.get("cells") or []).issubset(cells):
                    assessment_ref_errors.append((node["id"], bucket, tid))
        for bucket in ("groups", "goal_groups"):
            for row in assessment.get(bucket) or []:
                gid = row.get("id")
                if gid not in groups or not set(row.get("tasks") or []).issubset(tasks) \
                        or not set(row.get("cells") or []).issubset(cells):
                    assessment_ref_errors.append((node["id"], bucket, gid))
    ok(order_complete and cell_joins and all_datasets_and_tasks_used and group_joins
       and not assessment_ref_errors,
       f"dashboard D/T/C/G definitions, order and assessment references are complete: "
       f"{assessment_ref_errors[:5]}")

    # Slot capacity comes from reviewed infrastructure facts when present; only
    # running stage jobs consume it.  Evaluation runs are deliberately outside
    # this counter.
    facts_path = eutil.rpath(d.repo, str((cfg.get("infra") or {}).get("facts_file") or ""))
    facts = eutil.read_json(facts_path, {}) or {}
    facts_slots = ((facts.get("compute") or {}).get("max_concurrent_stage_jobs"))
    config_slots = (cfg.get("infra") or {}).get("max_concurrent_stage_jobs")
    facts_authoritative = isinstance(facts_slots, int) and not isinstance(facts_slots, bool) \
        and facts_slots >= 1
    expected_slots = facts_slots if facts_authoritative else config_slots
    expected_slot_source = "infra_facts" if facts_authoritative else "config"
    expected_busy = sum(1 for run in d.state().get("runs", [])
                        if run.get("status") == "running" and run.get("kind") == "stage")
    slots = data.get("slots") or {}
    ok(slots.get("total") == expected_slots and slots.get("busy") == expected_busy
       and slots.get("free") == max(0, expected_slots - expected_busy)
       and slots.get("source") == expected_slot_source
       and slots == (data.get("infrastructure") or {}).get("slots"),
       f"dashboard slots expose free capacity and its authoritative source: {slots}")

    # Four application views and the two verdict/two-frontier visual markers
    # must live in the self-contained template, not merely in payload text.
    expected_views = ["overview", "evaluation", "resources", "infrastructure"]
    tab_views = re.findall(r'data-view="([a-z]+)"', dashboard_html)
    page_views = re.findall(r'<(?:main|section) id="view-([a-z]+)"', dashboard_html)
    template_markers = (
        "--specialist:", "--tradeoff:", 'specialist:"var(--specialist)"',
        'tradeoff:"var(--tradeoff)"', 'SCIENCE_MODE?"S":"I"',
        "&#9733; inheritance", "P&#9670;",
        "scientific inheritance frontier", "observed performance frontier",
    )
    ok(tab_views == expected_views and page_views == expected_views
       and all(marker in dashboard_html for marker in template_markers),
       "dashboard template contains four views plus specialist/tradeoff and S/P markers")

    # `json.loads` accepts non-standard NaN/Infinity, so reject them both
    # structurally and in the bytes delivered to the browser.  The W3C SVG
    # namespace string is not a network dependency; resource-loading tags,
    # CSS imports and browser network APIs are.
    try:
        json.dumps(data, allow_nan=False)
        finite_payload = True
    except (TypeError, ValueError):
        finite_payload = False
    nonfinite_token = re.compile(r"(?<![A-Za-z0-9_])(?:NaN|[+-]?Infinity)(?![A-Za-z0-9_])")
    unresolved_token = re.compile(r"@@[A-Z][A-Z0-9_]*@@")
    external_dependency_patterns = (
        r"<script\b[^>]*\bsrc\s*=", r"<link\b[^>]*\bhref\s*=",
        r"<(?:img|iframe|embed|source|video|audio)\b[^>]*\bsrc\s*=",
        r"<object\b[^>]*\bdata\s*=", r"<base\b[^>]*\bhref\s*=",
        r"@import\s+", r"url\(\s*['\"]?https?://",
        r"\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(",
    )
    has_external_dependency = any(re.search(pattern, dashboard_html, re.I)
                                  for pattern in external_dependency_patterns)
    ok(finite_payload and not nonfinite_token.search(payload_text)
       and not nonfinite_token.search(dashboard_html),
       "dashboard payload and HTML contain no NaN or Infinity")
    ok(not unresolved_token.search(dashboard_html) and not has_external_dependency,
       "dashboard has no unexpanded template token or external resource dependency")
    palette_path = d.repo / core_lane["core_palette_path"]
    palette_original = palette_path.read_text(encoding="utf-8")
    # JSON seals deliberately hash canonical semantics, so whitespace-only
    # edits are not contract changes.  Mutate an actual frozen core fact to
    # exercise the fail-closed scheduler path.
    palette_tampered = json.loads(palette_original)
    palette_tampered["cores"][0]["source_fact_digest"] = "0" * 64
    wj(d.repo, core_lane["core_palette_path"], palette_tampered)
    caught = False
    try:
        d.next()
    except SystemExit as exc:
        caught = "SEALED_ARTIFACT_MUTATED" in str(exc)
    finally:
        wt(d.repo, core_lane["core_palette_path"], palette_original)
    ok(caught, "post-freeze semantic palette mutation is rejected before any downstream scheduler action")
    d.doctor_clean("end of stress run")


def main():
    t0 = time.time()
    build_rounds()
    repo = HERE / "out" / "proj_stress"
    make_real_repo(repo)
    estore.Store(repo).init("stress-bfr", "20-round long-horizon stress")
    d = M.D(repo)
    out = pump(d)
    ok(out["kind"] == "done" and out.get("rounds") == 20, f"DONE after 20 rounds: {out}")
    final_audit(d)
    print(f"\nSTRESS GREEN: {M.CHECKS} checks passed in {time.time() - t0:.0f}s "
          f"(20 rounds, 33 nodes, real subprocess training/eval, 2 slots + full-slot deferral)")


if __name__ == "__main__":
    main()
