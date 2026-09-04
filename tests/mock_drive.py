#!/usr/bin/env python3
"""Mock drive for Model Evolution v9.2 - the package's broad regression suite.

Token-cheap skeleton of an 18-round evolution (research mode, SOTA library,
focus directions) plus a gated/copy-mode engineering mini-run: a scripted
'agent' answers every engine task with minimal canned artifacts that satisfy
the validators, while the choreography exercises the complex machinery:

  everything the v7 suite exercised: staged training + artifact registry with
    reuse/waiver/URI-collision, parallel background training with slot
    deferral and watch supersession, failure -> error journal -> fix ->
    relaunch, theory dialectic (REVISE/READ), moonshot floors, two-tier
    stagnation forcing, wildcat cadence, exploit-share cap, prune/revive,
    escalation reset, doctor --fix, git branch<->DAG mapping, engine-run smoke
  v8 additions:
    an engine-observed integrated infrastructure canary (legacy hand-written
      drill transcripts rejected; blocked/full_auto gate + fresh retry), SOTA
      library scan + idea binding + conclusion settlement
    the formal problem ladder: explicit theory rigor, pose (typed
      symbols/Given/Want), step-chain derivations with premise resolution,
      step-audit challenge attack, FORMALIZE verdict converting a prose lane
      mid-dialectic
    kinship relations replacing the superset reduction gate ([relation:
      reduction|component|recipe|contrast])
    implementation-fidelity audits (claim->code string checks) for L3+/heavy
      nodes, incl. a DEVIATES rejection
    research-mode duties: bold (assumption-inverting) sketches, L3+ portfolio
      share; engineering-mode borrowing (adaptation instead of difference)
    user focus directions: share cap, unknown-id rejection, starvation forcing
    parity-'promising' verdict for an L4 root landing at baseline parity
    inference-class (evaluation-only) node; experiment_class validation
    retrieval-ladder duty on downgraded evidence records
    training-dynamics duty at evaluation (per-stage metric echoes)
  complex inheritance: 2-/3-/4-parent hybrids (one with a REVIVED parent and a
    platform), hybrid whose parents are a variant-of-hybrid and a PROMISING
    L4 root, wildcat/moonshot roots, 6+ generation chains
  ~55 negative validator tests asserted by exact error code
  doctor clean at checkpoints; every engine call is a fresh Engine (resume by
  construction); real subprocess CLI checks

Run:  python tests/mock_drive.py
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.dont_write_bytecode = True                  # test runs must not litter __pycache__
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"     # ...nor must their child processes

HERE = Path(__file__).resolve().parent
PKG = HERE.parent
sys.path.insert(0, str(PKG / "engine"))

import eartifact  # noqa: E402
import ebundle    # noqa: E402
import ecanary    # noqa: E402
import econfig    # noqa: E402
import edash      # noqa: E402
import edoctor    # noqa: E402
import evcs       # noqa: E402
import egraph     # noqa: E402
import eprogram   # noqa: E402
import erun       # noqa: E402
import esched     # noqa: E402
import eseal      # noqa: E402
import esmoke     # noqa: E402
import estore     # noqa: E402
import eutil      # noqa: E402
import evalid     # noqa: E402

PY = sys.executable
OUT = HERE / "out"
CHECKS = 0


def ok(cond, msg):
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(f"[check {CHECKS}] {msg}")


def section(name):
    print(f"--- {name} (checks so far: {CHECKS})")


def sh(cwd, *args):
    p = subprocess.run(list(args), cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"cmd failed in {cwd}: {args}\n{p.stdout}\n{p.stderr}")
    return (p.stdout or "").strip()


def git(repo, *args):
    return sh(repo, "git", *args)


# --------------------------------------------------------------------------- text
FILLER = ("the mechanism rests on the exploration propensity structure of the logged "
          "data and on calibration of the reweighted objective under policy shift, "
          "which the parent model ignores by construction. ")
MARK1 = "the coordinate change moves supervision from realized outcomes to propensity weighted counterfactual estimates"
MARK2 = "the reduction limit recovers the parent objective when the exploration distribution collapses to the logging policy"
CMARK = "the challenge finds the weakest step in the derivation chain and demands a stronger justification of the propensity model"
IMARK1 = "the idea replaces the pointwise completion target with a counterfactual value functional over candidate actions"
IMARK2 = "failure of the overlap assumption manifests as exploding importance weights on rare high price levels"


def long(n, seed=""):
    s = (seed + " " + FILLER * (n // len(FILLER) + 2))
    return s[:n].rstrip() + "."


def md(*sections_):
    return "\n\n".join(f"## {t}\n\n{b}" for t, b in sections_) + "\n"


def wt(repo, rel, text):
    eutil.write_text(repo / rel, text)


def wj(repo, rel, data):
    eutil.write_json_atomic(repo / rel, data)


def file_digest(path: Path) -> str:
    if path.suffix == ".json":
        raw = json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"))
    else:
        raw = path.read_text(encoding="utf-8")
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def resource_accounting():
    methods = {
        "data_examples": "dataset_manifest", "train_tokens": "scheduler_ledger",
        "parameters": "model_profiler", "train_flops": "runtime_profiler",
        "infer_flops": "runtime_profiler", "latency_ms": "runtime_profiler",
        "teacher_calls": "api_meter", "api_calls": "api_meter",
        "selection_budget": "selection_ledger",
    }
    return {axis: {"method": methods[axis],
                   "description": long(60, f"the frozen evaluator counts {axis} from its named meter at the completed node boundary")}
            for axis in eprogram.RESOURCE_AXES}


def planned_resource_measurements(d, nid):
    spec = json.loads((d.repo / d.node(nid)["spec"]).read_text(encoding="utf-8"))
    defaults = {
        "data_examples": 1000, "train_tokens": 10000, "parameters": 1000000,
        "train_flops": 100000000, "infer_flops": 1000000, "latency_ms": 10,
        "teacher_calls": 0, "api_calls": 0, "selection_budget": 3,
    }
    planned = ((((spec.get("effect_case") or {}).get("resources") or {}).get("candidate"))
               or defaults)
    return {axis: {"lower": float(planned.get(axis, 0) if isinstance(planned.get(axis, 0),
                                                                      (int, float)) else 0),
                   "upper": float(planned.get(axis, 0) if isinstance(planned.get(axis, 0),
                                                                      (int, float)) else 0)}
            for axis in eprogram.RESOURCE_AXES}


# --------------------------------------------------------------------------- driver
class D:
    def __init__(self, repo: Path):
        self.repo = repo

    def store(self):
        return estore.Store(self.repo)

    def eng(self):
        return esched.Engine(self.store())  # fresh engine per call = resume by construction

    def next(self):
        # Repair lanes freeze a diagnosis before program synthesis. Most
        # long-run scenarios exercise downstream machinery, so answer this
        # mandatory stage with a valid canned artifact while retaining its real
        # validator and transition.
        while True:
            out = self.eng().compute_next()
            if out.get("kind") != "task" or out.get("type") != "diagnose":
                return out
            task = self.store().get_task(self.state(), out["task"])
            lane = self.lane(task["subject"]["lane"])
            data = {
                "lane": lane["id"],
                "problem": long(100, "the frozen split shows rare price levels are ranked from realized outcomes even when logged exposure differs"),
                "evidence": [
                    {"id": "DX1", "source": "B1", "observation": long(45, "the dossier localizes bias to propensity-skewed rare levels")},
                    {"id": "DX2", "source": "B2", "observation": long(45, "the fixed validation protocol preserves the tail ranking error")},
                ],
                "hypotheses": [
                    {"id": "H1", "statement": long(65, "realized-outcome supervision confounds value with logging exposure"),
                     "explains": ["DX1", "DX2"], "falsifier": long(45, "the error remains after exact exposure balancing"),
                     "discriminating_observation": long(45, "tail calibration changes when propensity is held fixed")},
                    {"id": "H2", "statement": long(65, "limited representation capacity causes tail levels to share an aliased score"),
                     "explains": ["DX1"], "falsifier": long(45, "a richer frozen representation leaves the same aliasing pattern"),
                     "discriminating_observation": long(45, "tail separability changes without changing exposure weights")},
                ],
                "leading_hypothesis": "H1",
                "invariants": [long(30, "the frozen split and candidate pool must remain unchanged")],
                "unknowns": [long(30, "the independent contribution of exposure and representation is unresolved")],
                "solution_proposals": False,
            }
            wj(self.repo, out["outputs"][0], data)
            accepted = self.eng().submit(out["task"])
            ok(accepted.get("kind") == "accepted", f"auto {out['type']} must pass: {accepted}")

    def submit(self, tid):
        return self.eng().submit(tid)

    def decide(self, gid, approve, note=None, retry=None):
        return self.eng().decide(gid, approve, note, retry)

    def state(self):
        return json.loads((self.repo / ".evo/state.json").read_text(encoding="utf-8"))

    def graph(self):
        return json.loads((self.repo / ".evo/graph.json").read_text(encoding="utf-8"))

    def reg(self):
        return json.loads((self.repo / ".evo/artifacts.json").read_text(encoding="utf-8"))

    def node(self, nid):
        return {n["id"]: n for n in self.graph()["nodes"]}[nid]

    def lane(self, lid):
        return {l["id"]: l for l in self.state()["lanes"]}[lid]

    def lane_by_name(self, name):
        cands = [l for l in self.state()["lanes"] if l.get("name") == name]
        return cands[-1]

    def events(self, name=None):
        evs = eutil.read_jsonl(self.repo / ".evo/events.jsonl")
        return [e for e in evs if name is None or e.get("event") == name]

    def run_update(self, run_id, status, metrics_file=None, ledger_file=None, note=None,
                   failure_class=None, repair_scope=None):
        store = self.store()
        st = store.load_state()
        run = store.get_run(st, run_id)
        ok(run is not None and run["status"] in ("running", "launch_unknown"),
           f"run_update target {run_id} must be active")
        if status == "finished":
            ok(metrics_file and (self.repo / metrics_file).exists(), "finished needs existing metrics file")
            if run.get("kind") == "eval":
                raw = json.loads((self.repo / metrics_file).read_text(encoding="utf-8"))
                raw.setdefault("_resource_measurements", planned_resource_measurements(self, run["node"]))
                wj(self.repo, metrics_file, raw)
        self.eng().update_run(
            run_id, status, metrics_file=metrics_file, ledger_file=ledger_file,
            note=note or ("fixture execution failure" if status == "failed" else None),
            failure_class=failure_class or ("implementation" if status == "failed" else None),
            repair_scope=repair_scope or (
                "workflow" if status == "failed" and (failure_class or "implementation") == "implementation"
                else None))

    def running(self):
        return [r for r in self.state()["runs"] if r["status"] == "running"]

    def smoke(self, nid):
        return esmoke.run_smoke(self.store(), nid)

    def doctor_clean(self, where):
        import edoctor
        problems, _ = edoctor.diagnose(self.store(), fix=False)
        ok(not problems, f"doctor must be clean at {where}: {problems}")


def nx(d, typ=None, kind="task"):
    out = d.next()
    # The v2 research path always performs a digest-bound post-freeze prior-art
    # pass.  Older round choreography asks for tournament immediately after a
    # repair sketch; transparently execute that substantive audit here while
    # still exposing deep_read when a test explicitly requests it.
    if typ == "tournament" and out.get("kind") == "task" and out.get("type") == "deep_read":
        ensure_collision_audits(d, (d.state()["tasks"][-1].get("subject") or {}).get("lane"))
        r = d.submit(out["task"])
        ok(r["kind"] == "accepted", f"post-freeze collision audit must accept before tournament: {r}")
        out = d.next()
    # Every research kernel, including a local one, now carries implementation
    # fidelity. Scenarios that are testing another transition still execute the
    # audit; dedicated fidelity scenarios request it explicitly and keep their
    # negative cases visible.
    while typ != "fidelity" and out.get("kind") == "task" and out.get("type") == "fidelity":
        nid = (d.state()["tasks"][-1].get("subject") or {}).get("node")
        w_fidelity(d, out, nid)
        r = d.submit(out["task"])
        ok(r["kind"] == "accepted", f"automatic research-kernel fidelity audit must accept: {r}")
        out = d.next()
    if typ == "evaluate" and out.get("kind") == "task" and out.get("type") == "eval_launch":
        # w_eval knows the intended synthetic score. Defer execution until it
        # can write raw evaluator evidence, then it mutates this dict to the
        # subsequent analyst task. This preserves concise round choreography.
        out["_deferred_evaluate"] = True
        return out
    ok(out["kind"] == kind, f"expected kind={kind}, got {out}")
    if typ is not None:
        ok(out.get("type") == typ, f"expected task type={typ}, got {out.get('type')} ({out})")
    return out


def sub_ok(d, out):
    if out.get("type") == "deep_read":
        ensure_collision_audits(d, (d.state()["tasks"][-1].get("subject") or {}).get("lane"))
    r = d.submit(out["task"])
    ok(r["kind"] == "accepted", f"expected accept for {out['task']} ({out['type']}), got {r}")
    return r


def sub_rej(d, out, *codes):
    r = d.submit(out["task"])
    ok(r["kind"] == "rejected", f"expected reject for {out['task']} ({out['type']}), got {r}")
    for c in codes:
        ok(any(e.startswith(c) for e in r["errors"]), f"expected error {c}, got {r['errors']}")
    return r


# --------------------------------------------------------------------------- repo setup
def make_repo(path: Path, with_git: bool):
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    wt(path, "README.md", "# fake bfr project\nA ranking model over 40 price levels.\n")
    for f in ("main.py", "train.py", "eval.py", "data.py", "model.py"):
        wt(path, f, f"# {f}\nprint('{f}')\n")
    wt(path, "docs/kb/platform.md",
       "# platform guide\nsubmit: hub-cli train --name app --job_name VERSION\n"
       "status: hub-cli train status -i ID\nlogs: hub-cli train logview --path P\n"
       "queue quota: 2 concurrent jobs\n")
    wt(path, "docs/kb/data.md",
       "# data\npretrain: store://proj/tables/train/part=2\nfinetune: store://proj/tables/train/part=8\n"
       "validation: store://proj/tables/train/part=9\n")
    wt(path, "docs/kb/metrics.md",
       "# metrics\nprimary: auc on frozen part=9; secondary logloss.\n"
       "checkpoints: oss://bkt/user/{run}/checkpoint.zip - one dir per run version.\n")
    if with_git:
        git(path, "init", "-q", "-b", "main")
        git(path, "config", "user.email", "mock@test")
        git(path, "config", "user.name", "mock")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "c1")
        wt(path, "model.py", "# model.py v2\nprint('model v2')\n")
        git(path, "add", "-A")
        git(path, "commit", "-q", "-m", "c2 baseline")


# --------------------------------------------------------------------------- content writers
def w_project_scan(d, out, *, gpu_hours=10000, wallclock_minutes=100000,
                   readiness_mode="certified_running", fit=None):
    wt(d.repo, out["outputs"][0], md(
        ("Sources scanned", long(45, "read the project overview, data contract, metric implementation and launcher")
         + " [src: README.md] [src: docs/kb/data.md] [src: eval.py]"),
        ("Draft evaluation map", long(45, "found ranking and calibration tasks over frozen validation data with auc and logloss outputs")),
        ("Draft evidence policy", long(70, "the inspected trainer has ordinary initialization and data-order randomness, but full repeats are costly and stability is not the project claim; targeted one-run causal diagnostics may still change a later DAG choice")),
        ("Unresolved user questions", "NONE - the test user confirmed the split, task roles and metric directions during discovery."),
        ("Draft resource envelope", f"The user set cumulative project limits of gpu_hours={gpu_hours} and "
         f"wallclock_minutes={wallclock_minutes}; later excess requires another approval."),
    ))
    wj(d.repo, out["outputs"][1], {
        "project": {"name": "fake-bfr", "goal": "beat baseline on the frozen validation contract",
                    "docs": ["docs/kb/platform.md", "docs/kb/data.md", "docs/kb/metrics.md"],
                    "code_roots": ["."]},
        "scanned_paths": ["README.md", "docs/kb/data.md", "docs/kb/metrics.md", "eval.py"],
        "inventory": {
            "datasets": [{"id": "D1", "name": "frozen validation", "source": "docs/kb/data.md"}],
            "tasks": [{"id": "T1", "name": "ranking", "source": "README.md"}],
            "metrics": [{"id": "M1", "name": "auc", "source": "eval.py"}],
            "cells": [{"id": "C1", "dataset": "D1", "task": "T1", "metric": "M1", "source": "eval.py"}],
        },
        "training_stochasticity": {
            "recommended_mode": "record_only",
            "randomness_sources": ["parameter initialization", "training minibatch order"],
            "claim_and_cost_reasoning": long(70, "the claim concerns ranking quality rather than typical-run variance and full retraining is material relative to the project envelope"),
        },
        "ablation_assessment": {
            "recommended_mode": "targeted",
            "reasoning": long(70, "a single component intervention may distinguish causal explanations that cheap frozen-output evaluation cannot separate"),
        },
        "unknowns": [],
        "resource_contract_draft": {
            "limits": {"gpu_hours": gpu_hours, "wallclock_minutes": wallclock_minutes},
            "basis": "the test user explicitly confirmed these cumulative project totals",
        },
        # v11.7: engine-fit assessment + readiness are mandatory scan outputs
        "engine_fit": fit if fit is not None else {
            "assumptions": [
                {"id": fid, "verdict": "holds", "evidence": ["README.md"],
                 "note": long(45, f"assumption {fid} verified against the scanned project and launcher facts")}
                for fid in ("F0", "F5", "F6", "F7")],
            "overall": "fit",
        },
        "readiness": ({
            "mode": "certified_running",
            "basis": long(45, "the test user certified a real end-to-end train and eval pass works on this setup today"),
        } if readiness_mode == "certified_running" else {
            "mode": "needs_preparation",
            "basis": long(45, "the supplied project has no wired dataset loader and its evaluation has never produced a number here"),
            "worklist": [{"item": "wire the frozen validation dataset",
                          "why": "the loader path is absent"},
                         {"item": "produce a first real auc number",
                          "why": "no end-to-end evidence exists"}],
        }),
    })


def w_config(d, out, *, autonomy, rounds_max, vcs, on_stuck="ask", bad_docs=False,
             cost_gate="heavy", preset="custom", drop_tempo=False,
             mode="engineering", sota=False, focus=None, focus_neglect=0, sota_refresh=0,
             rehearsal="none", scaling_probe=False, replication_mode="record_only",
             replication_runs=1, ablation_mode="targeted"):
    p = d.repo / ".evo/config.json"
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg["project"].update({
        "name": "fake-bfr", "goal": "beat the baseline auc on the frozen validation split",
        "code_root": ".", "primary_metric": "auc", "vcs": vcs,
        "mode": mode, "rehearsal": rehearsal, "focus_directions": focus or [],
        "docs": ["docs/kb/nonexistent.md"] if bad_docs else
                ["docs/kb/platform.md", "docs/kb/data.md", "docs/kb/metrics.md"],
    })
    cfg["metrics"] = [
        {"key": "auc", "name": "ROC-AUC", "direction": "max",
         "definition": "binary auroc of the completion head over the frozen validation split part=9",
         "source": "eval.py writes metrics.json key auc"},
        {"key": "logloss", "name": "LogLoss", "direction": "min",
         "definition": "mean binary cross entropy on the same frozen split, clamped predictions",
         "source": "eval.py writes metrics.json key logloss"},
        {"key": "latency", "name": "P95 latency", "direction": "min",
         "definition": "p95 end-to-end inference latency in milliseconds on the fixed serving harness",
         "source": "eval.py writes metrics.json key latency_ms"},
    ]
    cfg["evaluation_contract"] = {
        "model_scope": "single_checkpoint", "display_cell": "C1",
        "datasets": [
            {"id": "D1", "name": "Frozen ranking validation", "split": "part=9",
             "protocol": "fixed candidate pool and deterministic labels", "source": "docs/kb/data.md"},
            {"id": "D2", "name": "Calibration and serving suite", "split": "part=9 plus serving replay",
             "protocol": "fixed bins and pinned serving harness", "source": "docs/kb/metrics.md"}],
        "tasks": [
            {"id": "T1", "name": "ranking", "description": "rank candidate price levels by completion value",
             "aggregation": "all", "weight": 1.0},
            {"id": "T2", "name": "calibration", "description": "produce calibrated completion probabilities",
             "aggregation": "all", "weight": 1.0},
            {"id": "T3", "name": "serving", "description": "serve predictions within the deployment latency envelope",
             "aggregation": "all", "weight": 1.0}],
        "cells": [
            {"id": "C1", "dataset": "D1", "task": "T1", "metric": "auc", "result_key": "auc",
             "role": "target", "weight": 1.0, "min_improvement": 0.0,
             "noninferiority_margin": 0.01, "required": True, "goal_threshold": 0.80,
             "goal_threshold_source": "user-stated SOTA goal pinned at configure time"},
            {"id": "C2", "dataset": "D2", "task": "T2", "metric": "logloss", "result_key": "logloss",
             "role": "target", "weight": 1.0, "min_improvement": 0.0,
             "noninferiority_margin": 0.0, "required": False, "goal_threshold": 0.40,
             "goal_threshold_source": "user-stated SOTA goal pinned at configure time"},
            {"id": "C3", "dataset": "D2", "task": "T3", "metric": "latency", "result_key": "latency_ms",
             "role": "guardrail", "weight": 1.0, "min_improvement": 0.0,
             "noninferiority_margin": 2.0, "required": True, "goal_threshold": None,
             "goal_threshold_source": "deployment guardrail is relative non-inferiority only"}],
        "task_groups": [
            {"id": "G1", "name": "ranking quality", "tasks": ["T1"], "aggregation": "all", "required": True},
            {"id": "G2", "name": "calibration quality", "tasks": ["T2"], "aggregation": "all", "required": False}],
        "decision": {"min_target_groups_improved": 1, "min_target_groups_goal_met": 1,
                     "guardrails_must_be_noninferior": True,
                     "allow_specialist": True},
        "assumptions": [],
    }
    cfg["evidence_policy"] = {
        "probe_mode_order": ["same_run", "existing_artifact", "eval_intervention"],
        "max_extra_eval_arms_per_node": 1, "require_value_of_information": True,
        "training_replication": {
            "mode": replication_mode,
            "planned_runs": replication_runs if replication_mode == "preplanned" else 1,
            "aggregation": "mean" if replication_mode == "preplanned" else "none",
            "basis": long(70, "the user reviewed trainer randomness, claim relevance, field convention and full-run cost before approving this fixed seed policy"),
            "revisit_when": long(55, "reopen only if observed instability or a changed scientific claim makes typical-run behavior decision-relevant"),
        },
        "ablation": {
            "mode": ablation_mode,
            "max_costly_runs_per_node": 1 if ablation_mode == "targeted" else 0,
            "basis": long(70, "the user allows only one manually gated intervention when it resolves a concrete causal fork and cheap evidence is insufficient"),
        },
        "scaling_mode": "budgeted" if scaling_probe else "off",
        "max_scaling_costly_arms": 2 if scaling_probe else 0,
    }
    cfg["resource_contract"] = {
        "limits": {"gpu_hours": 10000, "wallclock_minutes": 100000},
        "basis": "the test user explicitly confirmed these cumulative project totals",
        "on_exhaustion": "ask",
    }
    cfg["budgets"].update({
        "rounds_max": rounds_max, "lanes_per_round_min": 1, "lanes_per_round_max": 3,
        "sketches_per_lane": 3, "winners_per_lane": 1, "max_attempts": 3,
        "evidence_min_total": 6, "evidence_min_new_per_round": 2,
        "evidence_refresh_min_when_gap": 2,
        "evidence_recent_year": 2024, "evidence_min_recent_ratio": 0.5,
        "evidence_min_per_bottleneck": 2, "evidence_recent_min_per_bottleneck": 1,
        "mech_cards_min_per_lane": 2, "mech_cards_recent_min_per_lane": 1,
        "mech_cards_min_constructive": 2, "mech_papers_min_constructive": 2,
        "mech_cards_min_theory_derived": 2, "mech_papers_min_theory_derived": 2,
        "mech_cards_min_moonshot": 4, "mech_papers_min_moonshot": 3,
        "theory_cycles_max": 3, "theory_cycles_min_full": 2,
        "max_lesson_items_in_bundle": 12, "max_error_items_in_bundle": 8,
        "predictions_min": 2, "predictions_max": 4,
        "derivation_steps_min": 3, "derivation_steps_min_full": 4,
        "sota_min_entries": 5, "retrieval_attempts_min": 2,
    })
    cfg["policy"].update({
        "autonomy": autonomy, "cost_gate_class": cost_gate, "on_stuck": on_stuck,
        "preset": preset,   # the suite hand-tunes the tempo keys below => "custom"
        "stagnation_rounds": 2, "stagnation_moonshot_rounds": 4,
        "wildcat_every_rounds": 5,
        "max_exploit_share": 0.67,
        "focus_share_max": 0.5, "focus_neglect_rounds": focus_neglect,
        "research_min_structural_scope_share": 0.0,
        # This deliberately hand-tuned regression config exercises repair-heavy
        # histories.  The frontier preset's constructive floor is asserted
        # separately and the stress suite exercises every search origin.
        "research_min_constructive_share": 0.0,
        "research_min_core_synthesis_share": 0.0,
        "scope_floor": {"exploit": 2, "reform": 3, "wildcat": 4, "moonshot": 4,
                        "hybrid": 2, "platform": 2},
    })
    cfg["research"] = {"sota_enabled": bool(sota), "sota_recent_year": 2025,
                       "sota_refresh_rounds": sota_refresh,
                       "sota_venues": ["NeurIPS", "ICML", "ICLR", "arXiv"]}
    if drop_tempo:
        for k in econfig.PRESET_KEYS:
            cfg["policy"].pop(k, None)
    cfg["infra"] = {"facts_file": ".evo/profile/INFRA_FACTS.json",
                    "max_concurrent_stage_jobs": 1, "drills": True}
    wj(d.repo, ".evo/config.json", cfg)


def project_cfg(d):
    return json.loads((d.repo / ".evo/config.json").read_text(encoding="utf-8"))


def planned_seeds(cfg):
    rep = ((cfg.get("evidence_policy") or {}).get("training_replication") or {})
    return [1009 + i * 101 for i in range(int(rep.get("planned_runs") or 1))]


def infra_facts(slots=2, uri_tpl="oss://bkt/user/{run_id}/checkpoint.zip", llm=False,
                service=False):
    facts = _infra_facts_base(slots, uri_tpl)
    if llm:
        facts["llm"] = {"kind": "openai-compatible endpoint",
                        "invoke_pattern": "POST http://serve.internal/v1/chat/completions",
                        "budget": "500k tokens/day", "src": ["docs/kb/platform.md"]}
    if service:
        facts["services"] = [{"name": "kg-endpoint", "kind": "virtuoso sparql endpoint",
                              "invoke_pattern": "POST http://kg.internal/sparql (SPARQL ASK probe)",
                              "src": ["docs/kb/data.md"]}]
    return facts


def _infra_facts_base(slots=2, uri_tpl="oss://bkt/user/{run_id}/checkpoint.zip"):
    return {
        "workspace": {"agent_runs_on": "dev pod with cli access", "code_lives_at": "this repo",
                      "src": ["README.md"]},
        "compute": {"kind": "hub-batch", "submit_pattern": "hub-cli train --name app --job_name VERSION",
                    "status_cmd": "hub-cli train status -i ID", "logs_cmd": "hub-cli train logview --path P",
                    "max_concurrent_stage_jobs": slots, "src": ["docs/kb/platform.md"]},
        "data": {"kind": "warehouse tables", "access_pattern": "table uri passed to the launcher",
                 "datasets": [
                     {"name": "observational", "uri": "store://proj/tables/train/part=2", "role": "pretrain"},
                     {"name": "exploration", "uri": "store://proj/tables/train/part=8", "role": "finetune"},
                     {"name": "validation", "uri": "store://proj/tables/train/part=9", "role": "validation"}],
                 "src": ["docs/kb/data.md"]},
        "artifact_store": {"kind": "object store", "uri_template": uri_tpl,
                           "collision_rule": "same path silently overwrites the zip; one dir per run version",
                           "src": ["docs/kb/metrics.md"]},
        "evaluation": {"how": "eval.py on the frozen part=9 split writes metrics.json",
                       "primary_metric_key": "auc",
                       "result_keys": ["auc", "logloss", "latency_ms"],
                       "src": ["docs/kb/metrics.md"]},
    }


def w_infra(d, out, *, bad=None, service=False, llm=False):
    prof = md(
        ("Where things run", long(70, "the agent runs on a dev pod and code lives here") + " [src: README.md] [src: main.py]"),
        ("How training is submitted and watched", long(70, "jobs go through hub-cli with two queue slots") + " [src: docs/kb/platform.md] [src: train.py]"),
        ("Data access", long(70, "three table partitions serve pretrain finetune validation") + " [src: docs/kb/data.md]"),
        ("Artifact and checkpoint conventions", long(70, "checkpoints zip into one object-store dir per run version") + " [src: docs/kb/metrics.md]"),
        ("Known constraints", long(70, "the validation split is frozen and the queue allows two jobs")),
    )
    if bad == "few_tags":
        prof = md(("Where things run", long(90) + " [src: README.md]"),
                  ("How training is submitted and watched", long(90)),
                  ("Data access", long(80)), ("Artifact and checkpoint conventions", long(80)),
                  ("Known constraints", long(70)))
    wt(d.repo, out["outputs"][0], prof)
    facts = infra_facts(service=service, llm=llm)
    if bad == "uri_tpl":
        facts = infra_facts(uri_tpl="oss://bkt/user/fixed/checkpoint.zip")
    if bad == "no_src":
        facts["compute"].pop("src")
        facts["evaluation"]["result_keys"] = ["auc"]
    wj(d.repo, out["outputs"][1], facts)


def w_interview(d, out, *, bad=None, llm=False):
    cfg = project_cfg(d)
    rep = ((cfg.get("evidence_policy") or {}).get("training_replication") or {})
    abl = ((cfg.get("evidence_policy") or {}).get("ablation") or {})
    pm = ("model_scope single_checkpoint means one shared deliverable. C1 is the required D1/T1 auc target "
          "with its relative margin and absolute goal 0.80; C2 is the optional D2/T2 logloss target with "
          "absolute goal 0.40; C3 is the required D2/T3 latency_ms guardrail. T1, T2 and T3 each aggregate "
          "all their cells; G1 is required/all and G2 is optional/all; at least one group must improve and "
          "one must meet its goal, while specialist findings are allowed but are not an overall pass. "
          "NONE-DECLARED for inferred U# choices. auc is display-only; auc and logloss are emitted by "
          "eval.py on the frozen split, while latency_ms comes from the pinned serving replay "
          "[src: docs/kb/metrics.md]. Relative progress remains separate from absolute goal attainment. "
          "The project resource contract is cumulative: gpu_hours is limited to 10000 and "
          "wallclock_minutes to 100000; exhaustion requires a new user approval. "
          f"The approved training seed mode is {rep.get('mode')}: "
          + (f"{rep.get('planned_runs')} full training runs are fixed in advance and aggregated by {rep.get('aggregation')}; "
             if rep.get("mode") == "preplanned" else
             "one seed is recorded and no full retraining repeats are planned; ")
          + f"the ablation policy is {abl.get('mode')} with at most {abl.get('max_costly_runs_per_node')} "
          "manually approved changed-component run and never an ablation-by-seed cross-product.")
    if bad == "no_pm":
        pm = "the evaluation is confirmed [src: docs/kb/metrics.md] but this section forgets the configured result keys."
    svcs = ("- hub-cli batch queue is the only compute surface documented [src: docs/kb/platform.md]\n"
            "- no LLM serving, vendor API, vector store or KG endpoint appears in docs or code")
    if llm:
        svcs = ("- the openai-compatible LLM endpoint is a declared runtime dependency "
                "[src: docs/kb/platform.md]\n"
                "- no additional vector store or KG endpoint appears in docs or code")
    if bad == "svc_prose":
        svcs = long(60, "there are probably some services around here somewhere but none were itemized")
    wt(d.repo, out["outputs"][0], md(
        ("Contradictions",
         "- C1: queue quota\n  docs say: two concurrent jobs [src: docs/kb/platform.md]\n"
         "  code says: launcher enforces no limit [src: train.py]\n"
         "  resolution: facts record the documented quota of two; the launcher trusts the queue."),
        ("Unknowns",
         "- U1: is the validation split regenerated monthly or frozen forever? assumption: frozen, per the metrics doc."),
        ("Resolutions",
         "- C1 resolved to quota=2 in INFRA_FACTS. - U1 assumed frozen; flagged for the user."),
        ("Runtime services", svcs),
        ("Evaluation contract confirmation", pm),
    ))


def w_profile(d, out, *, bad=None):
    tags = ["README.md", "main.py", "train.py", "eval.py", "data.py", "model.py",
            "docs/kb/platform.md", "docs/kb/data.md"]
    if bad == "few_tags":
        tags = tags[:4]
    body = " ".join(f"[src: {t}]" for t in tags)
    wt(d.repo, out["outputs"][0], md(
        ("Task", long(60, "rank 40 price levels for completion probability") + " " + body),
        ("Data", long(60, "three warehouse partitions; exploration data carries propensities")),
        ("Model", long(60, "a sequence encoder over user history with a completion head")),
        ("Training", long(60, "single stage on observational data in the current baseline")),
        ("Evaluation and metrics", long(60, "auc primary and logloss secondary on the frozen split")),
        ("Runtime", long(60, "hub-batch jobs submitted by cli; eval runs locally")),
        ("Current results", long(60, "baseline reaches auc near 0.70 on the frozen split")),
        ("Known issues", long(60, "observational bias and miscalibration on rare high price levels")),
    ))
    baseline = {
        "schema_version": 2,
        "program": {
            "objects": [
                {"id": "O1", "kind": "input",
                 "semantics": long(55, "logged histories, candidate prices and observed completions"),
                 "code": ["data.py"]},
                {"id": "O2", "kind": "representation",
                 "semantics": long(55, "a learned sequence state shared across all candidate prices"),
                 "code": ["model.py"]},
                {"id": "O3", "kind": "prediction",
                 "semantics": long(55, "forty completion probabilities ranked by the serving system"),
                 "code": ["model.py", "main.py"]},
            ],
            "operators": [
                {"id": "OP1", "kind": "transform", "phase": "both",
                 "semantics": long(65, "encode each logged history into the shared sequence representation"),
                 "reads": ["O1"], "writes": ["O2"], "depends_on": []},
                {"id": "OP2", "kind": "objective", "phase": "train",
                 "semantics": long(65, "fit the completion head with pointwise binary cross entropy on logged outcomes"),
                 "reads": ["O1", "O2"], "writes": ["O3"], "depends_on": ["OP1"]},
                {"id": "OP3", "kind": "inference", "phase": "infer",
                 "semantics": long(65, "score every fixed candidate price from the shared history representation"),
                 "reads": ["O2"], "writes": ["O3"], "depends_on": ["OP1"]},
            ],
            "training_process": long(90, "the encoder and head minimize pointwise binary cross entropy on logged observational examples"),
            "inference_process": long(90, "one encoded history is paired with every price and the head emits a ranked probability vector"),
            "information_flow": long(90, "logged outcomes supervise the shared representation without an explicit intervention variable"),
            "resource_model": long(90, "training and inference scale linearly with sequence length and forty fixed candidate levels"),
        },
        "external_invariants": [
            long(55, "the frozen part nine validation split and labels remain identical for every program"),
            long(55, "C1 auc and C3 latency retain their pinned definitions and evaluation harness"),
        ],
        "unknowns": [],
    }
    if bad == "bad_program":
        baseline["program"]["objects"][0]["code"] = ["missing.py"]
    wj(d.repo, out["outputs"][1], baseline)


def w_dossier(d, out, *, bad=None):
    secs_extra = []
    if bad != "no_discriminator":
        secs_extra.append(("Diagnostic discriminators",
                           "- B1: falsifier: randomized-policy slices show no bias-dependent error change | distinguish: compare errors by logged propensity support\n"
                           "- B2: falsifier: rare-level calibration matches common levels at equal sample size | distinguish: stratify calibration residual by level frequency\n"
                           "- B3: falsifier: separated stage gradients remain aligned throughout training | distinguish: measure gradient conflict before and after stage separation"))
    wt(d.repo, out["outputs"][0], md(
        ("Computational essence", long(120, "estimate the counterfactual completion value of each candidate price level from biased logs")),
        ("Bottleneck hypotheses",
         "- B1: observational bias distorts the completion signal, evidence: [src: docs/kb/data.md]\n"
         "- B2: rare high levels are miscalibrated, evidence: [src: eval.py]\n"
         "- B3: the single stage objective mixes pattern learning with causal correction, evidence: [src: train.py]"),
        ("Invariants",
         "- V1: the validation split part=9 is frozen and shared by every node\n"
         "- V2: auc and logloss are computed by the same eval code for every node"),
        ("Forbidden shallow moves",
         "- F1: hyperparameter sweeps sold as ideas\n- F2: metric reweighting without a causal argument\n"
         "- F3: ensembling the baseline with itself\n- F4: changing the eval split\n"
         "- F5: prompt-level cosmetics with no behavioral difference"),
        *secs_extra,
    ))


def w_rubric(d, out, *, bad=None):
    secs = [
        ("Scientific program", long(230, "a candidate is the complete executable learning and inference program with typed objects, update dependencies, information flow and resource path rather than a story about editing modules")),
        ("Implementation scope", long(230, "configuration local subsystem and full-program classify implementation breadth only; a full-program claim requires both train and inference semantics to be rebuilt while external contracts may remain preserved")),
        ("Mechanism novelty", long(230, "research novelty is non-reducible to a composition of known primitives and identifies a load-bearing irreducible or paradigm kernel whose removal destroys the capability; composition remains engineering unless a new relation is necessary")),
        ("Effect frontier", long(230, "the kernel has an explicit causal path to C1 or another registered cell, a falsifiable gain reason and a resource-matched comparison covering data, parameters, training, inference and hidden calls")),
        ("Theory axis", long(230, "theory is independent of implementation scope: none, explanatory and derivational are legal; strong theory constrains executable design choices, rules out alternatives and predicts discriminating outcomes")),
        ("Engineering boundary", long(230, "configuration and composition may deliver useful gains, but research candidates cannot pass by stitching familiar blocks whose contributions are independent; those programs remain engineering results")),
        ("Project-specific tests", long(230, "non-reducibility asks whether the counterfactual computation can be emulated without changing the baseline program; the load-bearing test removes its kernel and the resource test holds compute fixed")),
    ]
    if bad == "menu":
        secs[-1] = (secs[-1][0], secs[-1][1] + " see https://arxiv.org/abs/1512.03385")
    if bad == "no_leverage":
        secs = secs[:-1]
    wt(d.repo, out["outputs"][0], md(*secs))


def w_baseline_spec(d, out, nid, *, judge=None, protocol=None):
    ev = {"run": f'"{PY}" eval.py', "metrics_file": f".evo/nodes/{nid}/eval/metrics.json",
          "budget": {"limits": {"wallclock_minutes": 30}},
          "resource_accounting": resource_accounting()}
    if judge:
        ev["judge"] = judge
    if protocol:
        ev["protocol"] = protocol
    cfg = project_cfg(d)
    policy = ((cfg.get("evidence_policy") or {}).get("training_replication") or {})
    preplanned = policy.get("mode") == "preplanned"
    seeds = planned_seeds(cfg) if preplanned else [1009]
    wj(d.repo, out["outputs"][0], {
        "title": "Baseline unmodified project", "role": "baseline", "parents": [],
        "code_parent": None, "level": 0, "experiment_purpose": "candidate",
        "experiment_class": "train",
        "cost_class": "light", "workdir": ".",
        "evidence_plan": {"extra_eval_arms": 0, "declared_checks": []},
        "training_replication": {
            "mode": "preplanned" if preplanned else "single",
            "runs": len(seeds), "seeds": seeds,
            "aggregation": policy.get("aggregation") if preplanned else "none",
            "source": "existing_artifacts",
        },
        "smoke_plan": [{"name": "imports", "cmd": f'"{PY}" -c "print(123)"', "timeout_s": 120}],
        "eval": ev,
    })


def w_provision(d, out, *, status="ready", bad=None, work=True):
    pdir = ".evo/profile/provision"
    logs = []
    if status == "ready":
        for nm in ("micro_train", "micro_eval"):
            rel = f"{pdir}/{nm}.log"
            if not (bad == "no_evidence" and nm == "micro_train"):
                wt(d.repo, rel, f"{nm}: executed on a tiny slice; exit 0\n")
            logs.append(rel)
        if bad == "no_evidence":
            logs = [f"{pdir}/micro_train.log"]   # only the missing one is claimed
    rows = []
    if status == "ready" and work:
        wt(d.repo, f"{pdir}/wire_dataloader.log",
           "Traceback: KeyError 'propensity' in data.py collate; wired the missing loader path\n")
        rows.append({"what": long(25, "the supplied project had no loader for the frozen validation data"),
                     "file": "data.py",
                     "evidence": f"{pdir}/wire_dataloader.log"})
    data = {"status": status, "work": rows,
            "choices": ([{"decision": long(20, "used the frozen validation split as the evaluation slice"),
                          "why": long(20, "no other labeled split exists in the supplied project")}]
                        if status == "ready" and work else []),
            "proof": {"logs": logs,
                      "observed_metrics": ({} if bad == "no_metric" else {"auc": 0.51}),
                      "metric_basis": long(25, "the draft auc metric produced by eval.py on the tiny slice"),
                      "note": long(35, "one micro train step and the eval command produced a real number")}}
    if not rows and status == "ready":
        data["no_work_reason"] = long(35, "entry points ran clean on the tiny slice after config checks")
    if status == "blocked":
        data["blockers"] = [] if bad == "empty_block" else [
            {"missing": long(60, "read access to the exploration table part=8 is denied for the runtime"),
             "needed_for": "the finetune data path of every training",
             "ask": long(75, "grant the runtime read permission on store://proj/tables/train/part=8 and confirm")}]
    wj(d.repo, out["outputs"][1], data)
    wt(d.repo, out["outputs"][0], md(
        ("What was run", long(60, "the real train and eval entry points on the smallest full-path slice")),
        ("Work performed", "\n".join(f"- {f['what']} -> {f['file']}" for f in rows)
         or long(40, "no constructive work was needed beyond configuration checks")),
        ("Choices", "\n".join(f"- {c['decision']}" for c in data.get("choices", []))
         or "NONE-MADE - no scientific decision was taken during preparation"),
        ("Blockers", "\n".join(f"- {b['missing']}" for b in data.get("blockers", []))
         or "NONE-FOUND - nothing is missing after the full micro pass"),
        ("Verdict", long(40, f"preparation finished with status {status} and evidence attached")),
    ))


def _evidence_count(d):
    p = d.repo / ".evo/evidence/EVIDENCE.jsonl"
    return len(eutil.read_jsonl(p)) if p.exists() else 0


def w_evidence_initial(d):
    years = [2024, 2025, 2024, 2025, 2016, 1997]
    for i, y in enumerate(years, 1):
        eutil.append_jsonl(d.repo / ".evo/evidence/EVIDENCE.jsonl", {
            "id": f"E{i:03d}", "title": f"paper {i} on counterfactual ranking", "year": y,
            "url": f"https://example.org/p{i}", "source": "mock-search",
            "relevance": ["B1" if i % 2 else "B2"]})


def w_evidence_refresh(d, n=2, year=2025, relevance=("B3",)):
    start = _evidence_count(d)
    for k in range(n):
        i = start + k + 1
        eutil.append_jsonl(d.repo / ".evo/evidence/EVIDENCE.jsonl", {
            "id": f"E{i:03d}", "title": f"paper {i} frontier refresh", "year": year,
            "url": f"https://example.org/p{i}", "source": "mock-search",
            "relevance": list(relevance)})


def rewrite_evidence_last(d, drop_n):
    p = d.repo / ".evo/evidence/EVIDENCE.jsonl"
    recs = eutil.read_jsonl(p)[:-drop_n]
    p.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


def _mech_count(d):
    p = d.repo / ".evo/evidence/MECH_CARDS.jsonl"
    return len(eutil.read_jsonl(p)) if p.exists() else 0


def w_mech_cards(d, lane_id, n, papers, topics=None):
    """Append n cards for the lane cycling through the given evidence ids.
    Returns the list of new card ids (first one is guaranteed recent if papers[0] is)."""
    ids = []
    start = _mech_count(d)
    lane = d.lane(lane_id)
    candidate_ids = []
    if lane.get("sketches_path") and (d.repo / lane["sketches_path"]).exists():
        pdata = json.loads((d.repo / lane["sketches_path"]).read_text(encoding="utf-8"))
        candidate_ids = [str(s.get("sketch_id")) for s in pdata.get("sketches", [])]
    for k in range(n):
        i = start + k + 1
        cid = f"M{i:03d}"
        ids.append(cid)
        card = {
            "id": cid, "lane": lane_id, "paper": papers[k % len(papers)],
            "name": f"mechanism {cid} propensity reweighting variant",
            "problem": long(40, f"card {cid} solves biased completion estimation"),
            "core_math": long(60, f"card {cid} objective sums w_i(pi) times loss_i with self normalization"),
            "assumptions": ["overlap of exploration and target policies"],
            "reported_effect": "lift on logged bandit benchmarks",
            "transfer_conditions": long(50, f"card {cid} needs recorded propensities on the training slice"),
            "failure_modes": long(40, f"card {cid} degrades when weights explode"),
            "old_program": long(75, f"card {cid} starts from a predictor trained directly on logged realized outcomes"),
            "new_program": long(75, f"card {cid} introduces a propensity-aware value estimator inside the learning process"),
            "program_operations": [
                "replace the logged-outcome objective by a counterfactual value objective",
                "reroute policy propensity information into the estimator used for updates",
            ],
            "irreducible_core": long(90, f"card {cid} couples the target policy and logged policy inside one normalized update law"),
            "necessary_components": ["policy ratio inside the learning update"],
            "support_components": ["the existing sequence encoder", "the frozen candidate vocabulary"],
            "ablation_support": long(65, f"card {cid} reports that removing the in-update ratio loses the rare-action lift"),
            "resource_delta": long(65, f"card {cid} matches data and parameter scale with only a linear weighting pass"),
            "gain_confound": long(65, f"card {cid} separates mechanism gain from extra samples, parameters and teacher calls"),
            "quote": {"text": "we reweight the logged samples by inverse propensity and self normalize the estimator over the batch",
                      "section": "Method 3.2"},
        }
        if topics:
            card["topic"] = topics[k % len(topics)]
        eutil.append_jsonl(d.repo / ".evo/evidence/MECH_CARDS.jsonl", card)
    return ids


def ensure_collision_audits(d, lane_id):
    """Bind reusable M# facts to the exact current frozen program attempt."""
    if not lane_id:
        return
    lane = d.lane(lane_id)
    rel = lane.get("sketches_path")
    if not rel or not (d.repo / rel).exists() or not lane.get("program_set_digest"):
        return
    pdata = json.loads((d.repo / rel).read_text(encoding="utf-8"))
    cards = [c for c in eutil.read_jsonl(d.repo / ".evo/evidence/MECH_CARDS.jsonl")
             if c.get("lane") == lane_id]
    if not cards:
        return
    path = d.repo / ".evo/evidence/COLLISION_AUDITS.jsonl"
    existing = eutil.read_jsonl(path)
    current = [e for e in existing if e.get("lane") == lane_id
               and e.get("program_set_digest") == lane.get("program_set_digest")]
    covered = {(str(e.get("candidate_id")), str(e.get("axis"))) for e in current}
    next_id = len(existing) + 1
    for candidate in pdata.get("sketches") or []:
        sid = str(candidate.get("sketch_id"))
        for axis, offset in (("mechanism", 0), ("task_effect", 1)):
            if (sid, axis) in covered:
                continue
            card = cards[offset % len(cards)]
            eutil.append_jsonl(path, {
                "id": f"CA{next_id:03d}", "lane": lane_id,
                "program_set_digest": lane.get("program_set_digest"),
                "candidate_id": sid,
                "candidate_digest": eprogram.candidate_digest(candidate),
                "mech_card_id": card["id"], "axis": axis,
                "query": long(60, f"search the {axis} neighborhood of {sid} using its frozen objects operators and effect cell"),
                "program_overlap": long(80, f"{card['id']} shares propensity-aware estimation primitives with {sid} but not necessarily its complete state semantics"),
                "irreducible_difference": long(105, f"{sid} binds update and inference through one load-bearing state relation that the audited paper program does not contain"),
                "emulation_test": long(105, f"reconstructing {card['id']} under matched resources cannot emit {sid}'s coupled transition unless the claimed KC1 and its OP graph are adopted"),
                "recent_search_saturation": long(90, f"the current-year mechanism and task-effect queries were both screened; this edge remains closest when no newer paper is linked"),
            })
            next_id += 1


def w_sketches(d, out, lane_id, program_variants, mech_ids, *, hybrid_parents=None,
               reframe=False, bad=None, custom_idx=None, theory_rigor=None, obs_ref=None,
               efficiency=False, novelty_kind=None, specialist_last=False):
    """Write schema-v2 programs with scope, novelty and theory kept independent."""
    lane = d.lane(lane_id)
    origin = str(lane.get("search_origin") or "repair")
    model_parents = [p for p in lane.get("parents", [])
                     if p in {n["id"] for n in d.graph()["nodes"]}
                     and d.node(p).get("role") != "platform"]
    comparator_id = model_parents[0] if model_parents else "baseline"
    comparator_node = (d.node(comparator_id) if comparator_id != "baseline" else
                       next((n for n in d.graph()["nodes"] if n.get("role") == "baseline"), None))
    comparator_values = {
        "data_examples": 1000.0, "train_tokens": 10000.0, "parameters": 1000000.0,
        "train_flops": 100000000.0, "infer_flops": 1000000.0, "latency_ms": 10.0,
        "teacher_calls": 0.0, "api_calls": 0.0, "selection_budget": 3.0,
    }
    realized = (comparator_node or {}).get("effect_resources_realized") or {}
    for axis in eprogram.RESOURCE_AXES:
        row = realized.get(axis) if isinstance(realized, dict) else None
        if isinstance(row, dict) and all(
                not isinstance(row.get(bound), bool) and isinstance(row.get(bound), (int, float))
                for bound in ("lower", "upper")):
            comparator_values[axis] = (float(row["lower"]) + float(row["upper"])) / 2.0
    candidate_values = dict(comparator_values)
    if efficiency:
        candidate_values["infer_flops"] = float(comparator_values["infer_flops"]) * 0.9
        candidate_values["latency_ms"] = float(comparator_values["latency_ms"]) * 0.9
    scope_by_level = {1: "configuration", 2: "local", 3: "subsystem", 4: "full_program"}
    research = project_cfg(d)["project"]["mode"] == "research"
    intent_theory = lane.get("intent") in ("reform", "wildcat", "moonshot")
    sks = []
    for i, _variant in enumerate(program_variants, 1):
        sid = f"K{i}"
        level = int(lane.get("min_level") or 2)
        if bad == "under_level" and i == 1:
            level = 1
        change_scope = scope_by_level[max(1, min(level, 4))]
        candidate_novelty = novelty_kind or (
            "composition" if lane.get("intent") == "platform" or not research else
            ("paradigm" if lane.get("intent") in ("wildcat", "moonshot") else "irreducible"))
        kernel_kind = "system_relation" if lane.get("intent") == "hybrid" else (
            "update_law" if i % 2 else "learned_object")
        kernels = [{
            "id": "KC1", "kind": kernel_kind,
            "statement": long(105, f"{lane_id} cycle {lane.get('cycle')} {sid} uses one effect-bearing counterfactual state relation to determine supervision and inference"),
            "operator_refs": ["OP2", "OP3"],
        }]
        cand = {
            "sketch_id": sid,
            "change_scope": change_scope,
            "program": {
                "scientific_parents": list(model_parents),
                "objects": [
                    {"id": "O1", "kind": "input", "semantics": long(55, f"{sid} consumes logged histories, actions and propensities under the frozen data contract")},
                    {"id": "O2", "kind": "state", "semantics": long(55, f"{sid} learns a counterfactual value field whose coordinates correspond to candidate actions")},
                    {"id": "O3", "kind": "prediction", "semantics": long(55, f"{sid} emits calibrated action values for ranking through the unchanged external interface")},
                ],
                "operators": [
                    {"id": "OP1", "kind": "transform", "phase": "both",
                     "semantics": long(70, f"{sid} maps histories, actions and exposure information into the typed value-state inputs"),
                     "reads": ["O1"], "writes": ["O2"], "depends_on": []},
                    {"id": "OP2", "kind": "update", "phase": "train",
                     "semantics": long(75, f"{sid} jointly normalizes policy exposure inside the update that constructs the counterfactual value state"),
                     "reads": ["O1", "O2"], "writes": ["O2"], "depends_on": ["OP1"]},
                    {"id": "OP3", "kind": "inference", "phase": "infer",
                     "semantics": long(75, f"{sid} reads the same coupled value state to produce calibrated action rankings at deployment"),
                     "reads": ["O2"], "writes": ["O3"], "depends_on": ["OP1"]},
                ],
                "training_process": long(100, f"{sid} constructs the value state and updates it through a jointly normalized counterfactual objective rather than an auxiliary loss"),
                "inference_process": long(100, f"{sid} propagates the learned value state across every candidate action and ranks the resulting calibrated values"),
                "information_flow": long(100, f"{sid} routes logging propensities and observed outcomes into the same state transition that determines deployed predictions"),
                "resource_model": long(100, f"{sid} uses the same samples and parameter envelope, adding one linear pass over the fixed action set"),
            },
            "novelty": {
                "kind": candidate_novelty,
                "bearer": long(80, f"{lane_id} {sid} changes the load-bearing relation between the learned value state, policy exposure and the deployed ranking"),
                "kernel": kernels,
                "known_primitives": (["sequence encoder", "importance ratio"]
                                     if candidate_novelty == "composition" else ["sequence encoder"]),
                "support_shell": ["existing dataloader", "unchanged evaluation harness"],
            },
            "effect_case": {
                "comparator_id": comparator_id,
                "chain": [{
                    "id": "Z1", "kernel_refs": ["KC1"],
                    "intermediate": long(75, f"{sid} lowers propensity-conditioned calibration residual on rare candidate actions"),
                    "relation": long(75, f"lower residual prevents exposure frequency from reversing the ordering of true action values"),
                    "target_cell": "C1", "direction": "stabilize" if efficiency else "increase",
                    "minimum_worthwhile_delta": 0.002 if efficiency else 0.001,
                    "expected_delta_interval": [0.001, 0.03],
                }, {
                    "id": "Z2", "kernel_refs": ["KC1"],
                    "intermediate": long(75, f"{sid} removes exposure-conditioned bias from the calibrated probability estimates"),
                    "relation": long(75, f"lower calibration bias reduces the registered logloss on the secondary target cell"),
                    "target_cell": "C2", "direction": "decrease",
                    "minimum_worthwhile_delta": 0.001,
                    "expected_delta_interval": [0.001, 0.02],
                }],
                "predicted_gain": long(105, f"{sid} should gain because the baseline aliases policy exposure with action value exactly where tail ranking errors concentrate"),
                "failure_signal": long(75, f"{sid} fails if balanced-support slices show no calibration or ranking change relative to the baseline"),
                "resources": {
                    "regime": "efficiency" if efficiency else "matched",
                    "candidate": dict(candidate_values),
                    "comparator": dict(comparator_values),
                    "fixed_axes": (["data_examples", "train_tokens", "parameters", "train_flops",
                                    "teacher_calls", "api_calls", "selection_budget"]
                                   if efficiency else list(eprogram.RESOURCE_AXES)),
                    "tradeoff_axes": [],
                    "improvement_axes": ["infer_flops", "latency_ms"] if efficiency else [],
                    "comparison": long(100, f"{sid} holds every declared resource axis fixed; the linear value pass is included in the displayed FLOPs and latency"),
                },
            },
            "claim_scope": ({
                "kind": "efficiency", "target_cells": ["C1", "C2"],
                "guardrail_cells": ["C3"], "improvement_cells": ["C2"],
                "parity_cells": ["C1"],
                "rationale": long(80, f"{sid} pre-registers a C2 calibration-efficiency improvement while holding the primary ranking target at parity"),
            } if efficiency else {
                "kind": "generalist", "target_cells": ["C1", "C2"],
                "guardrail_cells": ["C3"],
                "rationale": long(80, f"{sid} claims the complete registered target set before any winner or numeric result is observed"),
            }),
            "theory_role": "derivational" if origin == "theory_derived" or theory_rigor in ("partial", "full") else (
                "explanatory" if intent_theory else "none"),
        }
        if specialist_last and i == len(program_variants):
            cand["effect_case"]["chain"] = [cand["effect_case"]["chain"][0]]
            cand["claim_scope"] = {
                "kind": "specialist", "target_cells": ["C1"], "guardrail_cells": ["C3"],
                "rationale": long(80, f"{sid} pre-registers only the primary ranking target while retaining the global guardrail"),
            }
        if candidate_novelty in ("irreducible", "paradigm"):
            cand["novelty"]["non_reducibility"] = long(130, f"{sid} cannot be reproduced by independently adding reweighting and calibration because the same state relation changes both the update law and inference semantics")
            cand["novelty"]["load_bearing_test"] = long(105, f"removing KC1 from {sid} restores the logged-outcome update and must erase the rare-action calibration advantage")
        if candidate_novelty == "paradigm":
            cand["novelty"]["semantic_break"] = long(130, f"{sid} replaces outcome prediction as the learned object with an action-indexed value process that defines both learning and inference")
        if cand["theory_role"] != "none":
            cand["theory_target"] = long(80, f"derive when {sid}'s coupled value update is identifiable and dominates the logged-outcome estimator")
        if cand["theory_role"] == "derivational":
            cand["theory_rigor"] = (str(lane.get("formal_kind"))
                                    if origin == "theory_derived" else theory_rigor)
        if origin == "theory_derived":
            cand["theory_obligations"] = [
                {"id": "DO1", "kernel_refs": ["KC1"], "operator_refs": ["OP2"],
                 "satisfaction": long(80, f"{sid} realizes DO1 by placing the derived exposure-sensitive update inside KC1 and OP2")},
                {"id": "DO2", "kernel_refs": ["KC1"], "operator_refs": ["OP2"],
                 "satisfaction": long(80, f"{sid} realizes DO2 by making the same mapped state relation determine the inference-readable value state")},
            ]
        if origin == "repair":
            cand.update({
                "diagnosis_digest": lane.get("diagnosis_digest"),
                "hypothesis_ids": ["H1"] if i != 3 else ["H2"],
                "mech_card_ids": [mech_ids[i % len(mech_ids)]],
            })
        else:
            cand["collision_queries"] = [
                long(70, f"find prior programs that couple an action-indexed value state to both update and inference for {sid}"),
                long(70, f"find methods that emulate {sid}'s joint semantics without the proposed state transition"),
            ]
        if origin == "core_synthesis":
            palette = json.loads((d.repo / lane["core_palette_path"]).read_text(encoding="utf-8"))
            cpids = [row["id"] for row in palette["cores"][:2]]
            cand["synthesis_core_ids"] = cpids
            cand["synthesis_relation"] = {
                "operation": long(130, f"{sid} transforms the two anonymous program invariants into one shared state law that jointly determines training and inference rather than attaching either source computation as a block"),
                "discarded_shells": [
                    long(55, f"discard the source-specific architecture shell for anonymous core {cpid}")
                    for cpid in cpids
                ],
                "non_decomposability": long(130, f"independent execution of the source cores cannot emulate {sid} because neither makes the same state variable jointly constrain the update and deployed inference relation"),
            }
        if lane.get("intent") == "platform":
            cand.pop("effect_case", None)
            cand.pop("claim_scope", None)
        if bad == "bad_repair_evidence" and i == 1:
            cand["mech_card_ids"] = ["M999"]
        if bad == "unknown_field" and i == 1:
            cand["unsupported_field"] = "not part of the scientific-program schema"
        sks.append(cand)
    payload = {
        "schema_version": 2,
        "lane": lane_id,
        "search_origin": origin,
        "baseline_program_digest": file_digest(d.repo / ".evo/profile/BASELINE_PROGRAM.json"),
        "sketches": sks,
    }
    if origin == "repair":
        payload["diagnosis_digest"] = lane.get("diagnosis_digest")
    if origin == "theory_derived":
        payload["theory_digest"] = file_digest(d.repo / lane["theory_path"])
    if origin == "core_synthesis":
        payload["core_palette_digest"] = lane.get("core_palette_digest")
    wj(d.repo, out["outputs"][0], payload)


def w_tournament(d, out, lane_id, winner="K1", *, leverage=False, bad=None):
    lane = d.lane(lane_id)
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    expects_sota = econfig.sota_enabled(project_cfg(d)) and lane.get("intent") != "platform"
    ok((".evo/evidence/SOTA.jsonl" in bundle) == expects_sota,
       f"tournament bundle SOTA input must match the active non-platform research contract for {lane_id}")
    sdata = json.loads((d.repo / lane["sketches_path"]).read_text(encoding="utf-8"))
    lane_cards = [c["id"] for c in eutil.read_jsonl(d.repo / ".evo/evidence/MECH_CARDS.jsonl")
                  if c.get("lane") == lane_id]
    card_by_id = {c["id"]: c for c in eutil.read_jsonl(d.repo / ".evo/evidence/MECH_CARDS.jsonl")}
    collision_rows = [e for e in eutil.read_jsonl(d.repo / ".evo/evidence/COLLISION_AUDITS.jsonl")
                      if e.get("lane") == lane_id and e.get("program_set_digest") == lane.get("program_set_digest")]
    audits = []
    for s in sdata["sketches"]:
        q = str((s.get("novelty") or {}).get("bearer") or "")
        if bad == "quote" and s["sketch_id"] == winner:
            q = "totally fabricated words that are absent from the sketch text entirely"
        sedges = [e for e in collision_rows if e.get("candidate_id") == s["sketch_id"]]
        neighbors = []
        for axis in ("mechanism", "task_effect"):
            edge = next(e for e in sedges if e.get("axis") == axis)
            mid = edge["mech_card_id"]
            neighbors.append({
                "paper": card_by_id[mid]["paper"], "axis": axis,
                "program_overlap": edge["program_overlap"],
                "irreducible_difference": edge["irreducible_difference"],
                "core_work_cards": [mid], "collision_audits": [edge["id"]],
            })
        a = {
            "sketch_id": s["sketch_id"], "quote": q,
            "program_digest": eprogram.candidate_digest(s),
            "prior_art": {
                "neighbors": neighbors,
                "search_stop_reason": long(100, "the mechanism-family and task-effect queries both converged on these audited neighbors and two additional query variants found no closer executable program"),
            },
            "emulation_matrix": [
                {"alternative": alt, "can_emulate": False,
                 "argument": long(100, f"{alt} cannot reproduce this candidate without introducing the same coupled value-state operators and therefore is not a trivial emulation")}
                for alt in ([n["paper"] for n in neighbors] +
                            [x["sketch_id"] for x in sdata["sketches"] if x["sketch_id"] != s["sketch_id"]])
            ],
            "irreducibility": {
                "non_reducible": True,
                "load_bearing": True,
                "collage": False,
                "argument": long(130, "removing the shared state relation restores the baseline learning semantics, while independently attaching known weighting and calibration blocks does not reproduce the coupled transition"),
            },
            "scope": {
                "claimed_scope": s["change_scope"], "audited_scope": s["change_scope"],
                "train_semantics_preserved": s["change_scope"] not in ("subsystem", "full_program"),
                "infer_semantics_preserved": s["change_scope"] != "full_program",
                "preserved_interfaces": ["frozen evaluation result keys"],
                "argument": long(130, f"the baseline-to-candidate semantic comparison supports {s['change_scope']} because the audited train and inference objects change at exactly that breadth"),
            },
            "effect": {
                "causal_chain_valid": True, "comparator_valid": True,
                "threshold_credible": True,
                "resource_status": "matched",
                "argument": long(130, "the proposed causal path targets the observed tail error under the same examples, parameters, steps and serving interface, with the extra linear pass disclosed"),
                "resource_confounds": [],
                "resource_provenance": long(100, "candidate and comparator vectors come from the frozen training recipe, profiler estimate, serving trace, and explicit selection ledger"),
                "frontier_refs": ((["S006"] if bad == "sota_scope" and s["sketch_id"] == "K3" else ["S001"])
                                  if project_cfg(d).get("project", {}).get("mode") == "research"
                                  and (project_cfg(d).get("research") or {}).get("sota_enabled") else []),
            },
            "decision": "advance" if s["sketch_id"] == winner else "kill",
            "reason": long(80, f"audit of {s['sketch_id']} compares the actual program core and its resource-normalized effect claim"),
        }
        if bad == "no_move_audit" and s["sketch_id"] == winner:
            a.pop("irreducibility")
        if s.get("theory_role") != "none":
            a["theory"] = {
                "status": "supported" if lane.get("search_origin") == "theory_derived" else "pending",
                "argument": long(85, "the stated theoretical target constrains the same coupled value-state relation represented by KC1"),
            }
            if lane.get("search_origin") == "theory_derived":
                a["theory"]["obligation_audit"] = [
                    {"id": row["id"],
                     "kernel_refs": json.loads(json.dumps(row["kernel_refs"])),
                     "operator_refs": json.loads(json.dumps(row["operator_refs"])),
                     "aligned": True,
                     "argument": long(90, f"{row['id']} is realized by exactly the frozen KC and OP references and survives the independent program audit")}
                    for row in s.get("theory_obligations") or []
                ]
        audits.append(a)
    wj(d.repo, out["outputs"][0], {
        "lane": lane_id,
        "program_set_digest": lane.get("program_set_digest"),
        "audits": audits,
        "survivor_ranking": ([{"rank": 1, "sketch_id": winner,
                                "pareto_status": "nondominated",
                                "argument": long(100, "pairwise comparison places this survivor first because it offers the strongest minimum effect under the same resource vector and no rival emulates its kernel")}] if winner else []),
        "winners": [winner] if winner else [],
    })


PROBLEM_SYMS = [
    ("W_cf", "R^{L x d} value field", "the counterfactual completion value over the L price levels"),
    ("pi_log", "distribution over actions", "the logging policy on the exploration slice"),
    ("V_hat", "estimator", "the self normalized propensity weighted estimate of W_cf"),
]


def w_problem(d, out, *, bad=None):
    syms = list(PROBLEM_SYMS)
    if bad == "few_syms":
        syms = syms[:2]
    if bad == "unused_sym":
        syms = syms + [("Z_x", "spare tensor", "a symbol that nothing below ever touches")]
    setup = "\n".join(f"- sym: {n} : {t} - {m}" for n, t, m in syms)
    want = long(90, "characterize the bias and variance of V_hat as an estimator of W_cf under the shift away from pi_log")
    if bad == "no_sym_want":
        want = long(90, "characterize the bias and variance of the estimator under the policy shift in general terms")
    wt(d.repo, out["outputs"][0], md(
        ("Setup", setup),
        ("Given", "A1: recorded propensities are correct on the exploration slice under pi_log.\n"
                  "A2: overlap holds between pi_log and the target policy on the levels that matter for W_cf."),
        ("Want", want),
        ("Success criteria", long(80, "a bound on the bias of V_hat that translates into a measurable auc movement on the frozen split")),
    ))


def formal_step_lines(n_steps, *, bad=None):
    """A canned derivation chain that satisfies (or violates) the v8 step audit."""
    lines = []
    for i in range(1, n_steps + 1):
        prem = "A1" if i == 1 else ("A2, S1" if i == 2 else f"S{i - 1}")
        if bad == "chain_bad" and i == 2:
            prem = "S9"
        sym = ["W_cf", "pi_log", "V_hat"][(i - 1) % 3]
        mark = " [establishes: Want]" if (i == n_steps and bad != "chain_bad") else ""
        lines.append(f"- S{i} [from {prem}]: the estimator step {i} constrains {sym} through self normalization{mark} "
                     f"; reads: step {i} pins the value field scale in plain words ; fails-if: overlap breaks on rare levels")
    if bad == "chain_bad":
        # also starve one posed symbol (drop V_hat mentions)
        lines = [ln.replace("V_hat", "W_cf") for ln in lines]
    return "\n".join(lines)


def w_theory(d, out, lane_id, *, parent_ref="baseline", response_from=None, moonshot=False,
             bad=None, formal=False, relation="reduction"):
    deriv = long(430, "A1: recorded propensities are correct on the exploration slice. "
                      "A2: overlap holds on the levels that matter.")
    if formal:
        n = 4 if bad != "few_steps" else 2
        deriv = ("A1: recorded propensities are correct on the exploration slice. "
                 "A2: overlap holds between pi_log and the target on the levels that matter.\n"
                 + formal_step_lines(n, bad=bad) + "\n" + long(120, "the chain closes the posed question"))
    obligations = ("- DO1: implement KC1 through OP2 so propensity exposure changes the actual update law.\n"
                   "- DO2: make OP3 read the same value state and record Z1 before computing C1.")
    predictions = ("- TP1: Z1 decreases first on rare actions before aggregate C1 auc increases.\n"
                   "- TP2: breaking overlap reverses the Z1 movement and removes the C1 advantage.")
    if bad == "no_relation_tag":
        obligations = long(120, "the implementation should broadly respect the result without any numbered executable obligation")
    if bad == "no_precedent":
        predictions = long(120, "the result is expected to help but no discriminating prediction is registered")
    secs = [
        ("Obstruction or desiderata", long(130, "the logged-outcome estimator cannot distinguish action value from policy exposure on rare actions, while the frozen task requires that distinction")),
        ("Result", long(130, MARK1 + " Under A1 and A2 the KC1-coupled update identifies the action value state with bounded exposure bias")),
        ("Derivation", deriv + " " + long(100, "KC1 connects the derived estimator to OP2 and OP3 without an independent calibration patch")),
        ("Design consequences", long(130, "KC1 must inhabit OP2 and OP3; an output-only calibration head or evaluation-time weighting violates the derived dependency")),
        ("Ruled-out alternatives", long(130, MARK2 + " An independently weighted loss and post-hoc calibration are ruled out because neither makes inference read the identified value state")),
        ("Executable obligations", obligations),
        ("Discriminating predictions", predictions),
        ("Scope and failure conditions", long(130, "the result applies only under recorded propensities and overlap; misspecification or support collapse breaks the bound and must surface through Z1")),
    ]
    if response_from is not None and bad != "no_response":
        prev = (d.repo / response_from).read_text(encoding="utf-8")
        ok(CMARK in prev, "previous challenge must contain CMARK")
        secs.append(("Response to challenge",
                     long(90, "the objection about the propensity model is answered by an explicit sensitivity bound")
                     + f"\nQUOTE: {CMARK}\n"))
    wt(d.repo, out["outputs"][0], md(*secs))
    # Full-rigor lanes ship an engine-executed numeric check.
    lane = d.lane(lane_id)
    if formal and str(lane.get("formal_kind") or "") == "full" and bad != "toy_missing":
        toy_rel = out["outputs"][0].rsplit("/", 1)[0] + "/TOY_CHECK.py"
        if bad == "toy_fail":
            body = "assert 1.0 < 0.5, 'S2 bound fails on the toy instance'\nprint('TOY_CHECK_OK')\n"
        else:
            body = ("v = sum(1.0 / (i + 1) for i in range(8))\n"
                    "assert v > 1.0, 'S1: self normalization keeps the estimate positive'\n"
                    "w = v / 8.0\n"
                    "assert w <= 1.0, 'S2: the normalized weight stays bounded'\n"
                    "print('verified S1 S2 on the toy instance')\n"
                    "print('TOY_CHECK_OK')\n")
        wt(d.repo, toy_rel, body)


def w_challenge(d, out, lane_id, verdict, *, topics=None, bad=None, formal=False):
    lane = d.lane(lane_id)
    theory = (d.repo / lane["theory_path"]).read_text(encoding="utf-8")
    ok(MARK1 in theory and MARK2 in theory, "theory must contain quote marks")
    quotes = [f"QUOTE: {MARK1}", f"QUOTE: {MARK2}"]
    if bad == "one_quote":
        quotes = [f"QUOTE: {MARK1}"]
    secs = [
        ("Premise audit", long(100, "A1 is vulnerable to propensity misspecification and A2 is vulnerable precisely on rare actions where the claimed gain concentrates")),
        ("Derivation attack", long(160, CMARK)),
        ("Design consequence audit", long(100, "DO1 and DO2 really follow only if the same state relation is present in both OP2 and OP3")),
        ("Alternative explanation", long(100, "extra effective sample weighting could move C1 without identifying the claimed value state unless Z1 moves first")),
        ("Prediction audit", long(100, "TP1 and TP2 discriminate the result from post-hoc calibration and ordinary importance weighting")),
        ("Verdict rationale", long(80, f"verdict {verdict} because the derivation chain holds except where noted")),
    ]
    if formal:
        sa = long(80, "the weakest link is step S2 whose bound leans on the calibration of the propensity model")
        if bad == "no_s_id":
            sa = long(80, "the chain generally looks fine and no particular numbered link is singled out here")
        secs.insert(3, ("Step audit", sa))
    if verdict == "PROCEED":
        secs.append(("Strongest surviving objection",
                     long(80, "the propensity model itself is estimated and its error is only bounded, not eliminated")))
    if verdict == "READ":
        body = "reading is required before this theory can be judged.\n"
        if bad != "no_topics":
            body += "".join(f"- topic: {t}\n" for t in (topics or []))
        secs.append(("Required reading", body))
    if verdict == "FORMALIZE" and bad != "no_demand":
        secs.append(("Formalization demand",
                     long(90, "the bias claim about the estimator is precise enough to be posed as a bound and derived step by step")))
    text = f"VERDICT: {verdict}\n\n" + md(*secs) + "\n" + "\n".join(quotes) + "\n"
    wt(d.repo, out["outputs"][0], text)


def sibs_for(d, lane):
    g = d.graph()
    idx = {n["id"]: n for n in g["nodes"]}
    mp = [p for p in lane.get("parents", []) if idx.get(p, {}).get("role") != "platform"]
    out = []
    for n in g["nodes"]:
        if n.get("role") in ("platform", "baseline"):
            continue
        if set(n.get("parents", [])) & set(mp) and n.get("lane") != lane["id"]:
            out.append(n["id"])
    return out


def w_mature(d, out, lane_id, *, mech_ids, preds, n_assum=2, deriv_chars=300,
              platform=False, hybrid=False, theory=False, bad=None, dup_of=None,
              formal=False, adapt_only=False, dominance=None, scaling=None, obs_source=None,
              waiver=False, ablation=None, interface_changed=False, meta_extra=None):
    lane = d.lane(lane_id)
    iid = lane["idea"]
    sdata = json.loads((d.repo / lane["sketches_path"]).read_text(encoding="utf-8"))
    winner = next(s for s in sdata["sketches"] if s["sketch_id"] == lane["winner_sketch"])
    level = eprogram.compute_level(winner)
    meta_level = level + 1 if bad == "level" else level
    idx = {n["id"]: n for n in d.graph()["nodes"]}
    model_parents = [p for p in lane.get("parents", []) if idx.get(p, {}).get("role") != "platform"]
    plat_parents = [p for p in lane.get("parents", []) if idx.get(p, {}).get("role") == "platform"]
    purpose = str(lane.get("experiment_purpose") or "candidate")
    if winner.get("theory_role") == "derivational":
        n_assum = max(n_assum, 3)
    assum = [{"id": f"A{i}", "statement": long(45, f"assumption A{i} about propensity validity on slice {i}"),
              "source": "dossier" if i % 2 else "profile"} for i in range(1, n_assum + 1)]
    if obs_source:
        assum[0]["source"] = obs_source   # v9: a ledger observation grounds an assumption
    npb = {"paper": "E001"}
    if adapt_only:
        npb["adaptation"] = long(95, "the published reweighting mechanism is borrowed wholesale and refit to the "
                                     "recorded propensity slice with a clipped weight schedule for this project")
    else:
        npb["difference"] = long(90, "unlike the nearest work the target itself is redefined rather than reweighted at eval")
    meta = {
        "idea": iid, "lane": lane_id, "sketch_id": lane["winner_sketch"],
        "title": f"idea {iid} counterfactual objective",
        "experiment_purpose": purpose,
        "change_scope": winner["change_scope"], "program": winner["program"],
        "novelty": winner["novelty"],
        "theory_role": winner["theory_role"], "level": meta_level,
        "program_digest": lane["winner_program_digest"],
        "kernel_hash": lane["winner_kernel_hash"],
        "parents": model_parents, "platforms_consumed": plat_parents,
        "prior_art_card_ids": mech_ids[:2],
        "bottleneck_ids": ["B1"] if lane.get("search_origin") == "repair" else [],
        "assumptions": assum, "predictions": preds,
        "nearest_published": npb,
        "siblings_distance": [{"node": s, "difference": long(50, f"differs from {s} in the target object itself")}
                              for s in sibs_for(d, lane)],
        "external_interface_changed": bool(interface_changed),
        "metric_bridge_needed": bool(interface_changed),
    }
    if not platform:
        meta["effect_case"] = json.loads(json.dumps(winner.get("effect_case")))
        meta["claim_scope"] = json.loads(json.dumps(winner.get("claim_scope")))
    if winner.get("theory_target"):
        meta["theory_target"] = winner["theory_target"]
    if winner.get("theory_rigor"):
        meta["theory_rigor"] = winner["theory_rigor"]
    if "theory_obligations" in winner:
        meta["theory_obligations"] = json.loads(json.dumps(winner["theory_obligations"]))
    if lane.get("search_origin") == "repair":
        meta["diagnosis_digest"] = lane["diagnosis_digest"]
        meta["hypothesis_ids"] = list(winner.get("hypothesis_ids") or ["H1"])
    research_kernel = str((winner.get("novelty") or {}).get("kind")) in eprogram.RESEARCH_NOVELTY
    if research_kernel and not platform and purpose == "candidate" and bad != "no_probe":
        if waiver:
            meta["attribution_waiver"] = long(45, "the mechanism has no measurable intermediate on this "
                                                  "harness because the decoding change only exists at the API boundary")
        else:
            repeat_policy = ((project_cfg(d).get("evidence_policy") or {}).get("training_replication") or {})
            probe_artifact = (f".evo/probes/{iid}/seed-{{seed}}.json"
                              if repeat_policy.get("mode") == "preplanned"
                              else f".evo/probes/{iid}/observation.json")
            meta["mechanism_probe"] = {
                "signal": long(40, "calibration slope on the exploration slice at rare price levels"),
                "expect": long(20, "the slope moves toward one under the registered objective"),
                "mode": "same_run", "extra_eval_arms": 0,
                "artifact": probe_artifact,
                "required_fields": ["calibration_slope"],
                "decision_rule": {"field": "calibration_slope", "aggregation": "mean",
                                  "comparison": "between", "lower": 0.9, "upper": 1.1},
                "decision": long(55, "a refuted slope blocks descendants that reuse the claimed counterfactual channel"),
                "value_of_information": long(70, "the signal separates a transferable mechanism from a coincidental aggregate metric gain"),
                "cheaper_modes_rejected": []}
    if dominance:
        meta["dominance"] = dominance
    # v9.2 scaling evidence: auto-register an after-signal follow-up contract
    # for L4 non-platform ideas only when evidence_policy permits it.
    cfg0 = project_cfg(d)
    # "== candidate", not "!= targeted_ablation": research fields are candidate
    # privileges, and the negative form is the exact idiom that broke when the
    # third purpose arrived (probe/maintenance meta must not carry these).
    if scaling and purpose == "candidate":
        meta["scaling"] = {**scaling,
                           "value_of_information": scaling.get("value_of_information") or long(70, "the trend decides whether the mechanism deserves a larger-scale promotion node"),
                           "execution": scaling.get("execution") or "followup_node",
                           "trigger": scaling.get("trigger") or "after_positive_signal",
                           "costly_arms": scaling.get("costly_arms", 2)}
    elif level >= 4 and not platform and purpose == "candidate" and bad != "no_scaling" \
            and cfg0.get("project", {}).get("mode") == "research" \
            and (cfg0.get("evidence_policy") or {}).get("scaling_mode") in ("budgeted", "full"):
        meta["scaling"] = {"axis": "data", "points": ["10 percent shard", "50 percent shard"],
                           "expect": long(35, "the auc gain grows monotonically with the data fraction"),
                           "value_of_information": long(70, "the trend decides whether the mechanism deserves a larger-scale promotion node"),
                           "execution": "followup_node", "trigger": "after_positive_signal", "costly_arms": 2}
    if dup_of:
        other = json.loads((d.repo / f".evo/ideas/{dup_of}.meta.json").read_text(encoding="utf-8"))
        meta["kernel_hash"] = other["kernel_hash"]
    if platform:
        meta["enables"] = ["future variant lanes consume the shared pretrained encoder",
                           "hybrid lanes initialize from the shared checkpoint"]
        meta["predictions"] = []
    if winner.get("theory_role") != "none":
        meta["theory_doc"] = lane.get("theory_path")
    if formal and bad != "no_formal_meta":
        meta["problem_doc"] = lane.get("problem_path")
    # SOTA binding (research mode + library + L3+ non-platform lanes)
    cfg = project_cfg(d)
    sota_on = cfg.get("project", {}).get("mode") == "research" and \
        (cfg.get("research") or {}).get("sota_enabled")
    if sota_on and research_kernel and not platform and purpose == "candidate" \
            and bad != "no_formal_meta" and bad != "no_sota":
        meta["sota_targets"] = [{"sota": "S001", "cell": "C1", "dimension": "effect",
                                 "claim": long(70, "the calibrated counterfactual target beats the S001 headline "
                                                   "auc on the shared frozen protocol")}]
    a_walk = " ".join(f"{a['id']}: {a['statement']}" for a in assum)
    deriv = long(max(deriv_chars, 200), IMARK2 + " " + a_walk) + " " + a_walk
    if bad == "short_deriv":
        deriv = long(400, "A1: only the first registered assumption is traced while the others are omitted")
    if platform:
        secs = [
            ("Scientific program", long(130, IMARK1) + f" The frozen build program exposes a versioned reusable artifact and was audited against [{mech_ids[0]}]."),
            ("Enabling capability", long(120, "the artifact gives future variants a shared initialized representation and gives hybrids a registered reusable input without silently recomputing it")),
            ("Operational and resource contract", long(120, "the artifact URI version compatibility envelope build budget storage footprint and consumer invocation contract are fixed before downstream use")),
            ("Prior-art boundary", long(110, f"the nearest audited infrastructure [{mech_ids[0]}] does not expose the same versioned consumer contract or lineage-bound reusable state")),
            ("Consumer/use falsification", long(110, "the platform claim fails if a declared consumer cannot load the artifact under the recorded interface or if reuse does not remove the promised duplicated work")),
            ("Implementation sketch", long(100, "build and register the immutable artifact publish its compatibility metadata and verify one representative consumer invocation in the isolated workarea")),
            ("Risks", IMARK2 + " " + long(90, "version drift stale lineage metadata or an unusable consumer interface would invalidate enablement")),
        ]
    else:
        kill_sec = (("Mechanism check", long(110, "the calibration slope is computed by the eval path and compared against the registered expectation; a moved auc with a flat slope kills the mechanism claim"))
                    if research_kernel else
                    ("Falsification experiment", long(90, "a tiny fixed-output check must move the registered intermediate before any costly training")))
        secs = [
            ("Scientific program", long(130, IMARK1) + f" The forward objects and OP1 through OP3 realize the approved train and inference computation, audited against [{mech_ids[0]}]."),
            ("Irreducible kernel", long(130, "KC1 is carried jointly by OP2 and OP3; removing either restores ordinary logged-outcome semantics and independent familiar modules cannot emulate the coupling")),
            ("Effect and resource case", long(130, "KC1 moves Z1, the rare-action calibration residual, which changes C1 under identical data, tokens, parameters, FLOPs, latency, calls and selection budget")),
            ("Causal derivation", deriv),
            ("Prior-art boundary", long(110, f"the nearest audited programs [{mech_ids[0]}] share propensity information but do not make one state relation determine both learning and inference")),
            ("Predictions", long(90, "the registered thresholds encode the calibration channel argument")),
            kill_sec,
            ("Implementation sketch", long(90, "stage one pretrains the encoder, stage two optimizes the counterfactual objective; artifacts registered per stage")),
            ("Risks", long(90, IMARK2)),
        ]
        if winner.get("theory_role") != "none":
            secs.append(("Theory consequences", long(120, "the surviving derivation constrains KC1 and OP2, rules out an independently calibrated output head, and predicts when overlap failure breaks Z1")))
        if formal and bad != "no_formal_meta":
            secs.insert(1, ("Formal statement",
                            long(140, "given the value field W_cf and the logging policy pi_log under A1 and A2 the "
                                      "mechanism attains the posed bound for V_hat on the frozen protocol")))
    wt(d.repo, out["outputs"][0], md(*secs))
    if meta_extra:
        meta.update(meta_extra)   # v11.1 doors drive: repeat_rule etc.
    wj(d.repo, out["outputs"][1], meta)


def w_red_team(d, out, lane_id, verdict="ACCEPT", *, bad=None):
    lane = d.lane(lane_id)
    idea = (d.repo / f".evo/ideas/{lane['idea']}.md").read_text(encoding="utf-8")
    ok(IMARK1 in idea and IMARK2 in idea, "idea must contain quote markers")
    meta = json.loads((d.repo / f".evo/ideas/{lane['idea']}.meta.json").read_text(encoding="utf-8"))
    if lane.get("intent") == "platform":
        secs = [
            ("Program fidelity", long(90, "the reviewed platform preserves the exact artifact-producing program compatibility metadata and registry path approved at maturation")),
            ("Enablement and load-bearing attack", long(100, "removing the versioned artifact or its compatibility contract makes the declared consumers recompute state or fail to initialize so the enabling capability is load-bearing")),
            ("Operational and resource attack", long(100, "the build storage invocation and maintenance costs are explicit and no hidden refresh job or duplicated training is omitted from the operational envelope")),
            ("Consumer/use falsification", long(100, "a representative downstream consumer must load and use the registered artifact under the frozen interface otherwise the enablement claim is rejected")),
            ("Prior-art attack", long(90, "the nearest reusable infrastructure lacks the same lineage-bound artifact contract consumer interface and promised avoided work")),
            ("Verdict rationale", long(80, f"the platform survives enablement operational consumer and prior-art attacks; verdict {verdict}")),
        ]
    else:
        secs = [
            ("Program fidelity", long(90, "the complete forward program defines the same OP2 update and OP3 inference relation claimed by KC1, with no missing bridge sidecar or post-review drift")),
            ("Irreducibility attack", long(90, "independent weighting and calibration modules cannot emulate the shared state relation; deleting KC1 restores baseline semantics and removes Z1 movement")),
            ("Effect and resource attack", long(90, "the KC1 to Z1 to C1 path is falsifiable and all nine resource axes are matched, so extra data, compute, calls or selection cannot explain the gain")),
            ("Prior-art attack", long(90, "the mechanism-family and task-effect neighbors lack the coupled train-infer relation and the emulation matrix found no known equivalent program")),
            ("Verdict rationale", long(80, f"the idea survives the three attacks; verdict {verdict}")),
        ]
        if meta.get("theory_role") != "none":
            secs.append(("Theory alignment", long(90, "the derivation constrains KC1 and OP2 directly and its failure conditions map to the registered Z1 prediction rather than decorating the proposal")))
    if verdict == "ACCEPT" and bad != "no_objection":
        secs.append(("Strongest surviving objection",
                     long(80, "propensity estimation error remains only bounded and could mute the predicted gain")))
    text = f"VERDICT: {verdict}\n\n" + md(*secs) + f"\nQUOTE: {IMARK1}\nQUOTE: {IMARK2}\n"
    wt(d.repo, out["outputs"][0], text)


def w_design_ablation(d, out, lane_id, *, bad=None):
    lane = d.lane(lane_id)
    iid = lane["idea"]
    idx = {n["id"]: n for n in d.graph()["nodes"]}
    parent = next(p for p in lane["parents"] if idx[p].get("role") != "platform")
    q1 = "The parent gain leaves two causal explanations alive under the frozen evaluation protocol."
    q2 = "Removing only the counterfactual objective term distinguishes mechanism from optimization side effect."
    held = [
        "the frozen validation dataset split and preprocessing remain byte identical",
        "the optimizer schedule training budget and initialization seed remain fixed",
        "the model architecture checkpoint selection and evaluation protocol remain fixed",
    ]
    contract = {
        "parent": parent,
        "question": long(70, f"whether {parent}'s gain comes from the counterfactual objective rather than an optimization side effect"),
        "competing_explanations": [
            {"id": "X1", "statement": long(52, "the counterfactual objective causally carries the parent's measured gain")},
            {"id": "X2", "statement": long(52, "an optimization side effect unrelated to that objective carries the gain")},
        ],
        "trigger_evidence": long(50, f"parent {parent} improved while its result left the causal channel unresolved"),
        "trigger_artifacts": [f".evo/nodes/{parent}/NODE_RESULT.md",
                              f".evo/nodes/{parent}/eval/metrics.json"],
        "changed_factor": {"name": "counterfactual objective term",
                           "parent_value": "enabled with registered coefficient one",
                           "ablated_value": "removed while all remaining loss terms stay unchanged"},
        "intervention": long(60, "remove only the counterfactual objective term and preserve the complete parent recipe"),
        "held_constant": held,
        "effect_supports": "X1", "no_effect_supports": "X2",
        "decision_if_effect": long(65, "retain the objective mechanism and prioritize descendants that strengthen its causal channel"),
        "decision_if_no_effect": long(65, "drop the objective story and redirect descendants toward the optimization-side-effect explanation"),
        "why_cheaper_evidence_insufficient": long(65, "saved logs and fixed-output evaluation cannot remove a train-time objective term"),
        "costly_runs": 1,
    }
    if bad == "missing_trigger":
        contract["trigger_artifacts"] = [f".evo/nodes/{parent}/missing.json"]
    meta = {
        "idea": iid, "lane": lane_id, "title": f"one-factor causal diagnostic for {parent}",
        "experiment_purpose": "targeted_ablation", "level": 0,
        "parents": [parent], "platforms_consumed": [],
        "evaluation_scope": {"target_cells": ["C1"], "guardrail_cells": ["C3"],
                             "rationale": long(70, "C1 measures the parent gain channel while C3 catches a serving-cost confound")},
        "predictions": [
            {"id": "P1", "metric": "auc", "comparison": ">=", "value": 0.773,
             "rationale": long(50, "an effect on the causal channel must preserve the observed ranking movement")},
            {"id": "P2", "metric": "latency_ms", "comparison": "<=", "value": 110.0,
             "rationale": long(50, "latency must stay bounded so systems drift cannot explain the result")},
        ],
        "ablation": contract, "metric_bridge_needed": False,
    }
    wt(d.repo, out["outputs"][0], md(
        ("Causal question", q1 + " X1 is the objective mechanism and X2 is an unrelated optimization effect."),
        ("Parent evidence", long(90, f"parent {parent} metrics and result files show the unresolved gain with exact numeric evidence")),
        ("Controlled intervention", q2 + " " + " ".join(held)),
        ("Decision map", long(100, "an observed effect selects X1 and retains the objective branch; no effect selects X2 and redirects the graph")),
        ("Evaluation and cost", long(100, "P1 and P2 are read from C1 and C3 after one costly run using one explicit seed and no fresh parent run")),
        ("Risks", long(90, "optimizer noise or an accidental recipe drift could make one run causally uninformative and must trigger rejection")),
    ))
    wj(d.repo, out["outputs"][1], meta)


def w_review_ablation(d, out, lane_id, verdict="ACCEPT"):
    q1 = "The parent gain leaves two causal explanations alive under the frozen evaluation protocol."
    q2 = "Removing only the counterfactual objective term distinguishes mechanism from optimization side effect."
    secs = [
        ("Causal identifiability", long(90, "the effect and no-effect outcomes map bijectively to X1 and X2 with no third live cause under the controls")),
        ("Single-change audit", long(90, "one objective term changes while data recipe budget architecture seed and evaluation remain fixed")),
        ("Cheaper evidence audit", long(90, "parent logs expose the ambiguity but cannot remove the train-time term, so eval-only analysis is insufficient")),
        ("Decision value", long(90, "effect and no-effect outcomes send the graph to different named descendant strategies")),
        ("Cost audit", long(90, "exactly one fixed single run is informative at the approved evidence standard; no parent rerun or seed repeat is requested")),
        ("Verdict rationale", long(90, f"the one-factor design is identifiable and decision changing, therefore verdict {verdict}")),
    ]
    if verdict == "ACCEPT":
        secs.append(("Strongest surviving risk", long(90, "one optimizer trajectory may still be atypical, but the user-approved record-only standard accepts one explicit seed")))
    body = "VERDICT: " + verdict + "\n\n" + f"QUOTE: {q1}\nQUOTE: {q2}\n\n" + md(*secs)
    wt(d.repo, out["outputs"][0], body)


def w_ablation_fidelity(d, out, nid, *, bad=None):
    node = d.node(nid)
    meta = json.loads((d.repo / node["idea_doc"].replace(".md", ".meta.json")).read_text(encoding="utf-8"))
    contract = meta["ablation"]
    controls = list(contract["held_constant"])
    if bad == "missing_control":
        controls = controls[:-1]
    control_lines = "\n".join(
        f"CONTROL: {c} :: VERIFIED: the parent and child configs plus the committed diff preserve this control exactly"
        for c in controls)
    wt(d.repo, out["outputs"][0], "FIDELITY: FAITHFUL\n"
       f"FACTOR: {contract['changed_factor']['name']}\n\n" + md(
        ("Changed-factor code map",
         f"- objective removal switch -> mod_a.py :: CODE: reweighting module for {nid}"),
        ("Held-constant audit", control_lines),
        ("Diff audit", long(90, "the complete diff changes only the objective implementation; data recipe budget seed architecture and eval files are unchanged")),
        ("Audit verdict", long(80, "the registered factor is present and every held constant was checked against code and configuration")),
    ))


def stage(name, *, uri=None, key=None, consumes=None, waiver=None, produces_kind="weights",
          mode="fixed", multiplicity="single", controller=None, stopping_conditions=None,
          why_multiple=None, limits=None, ledger_file=None, launch=None):
    control = {"mode": mode, "multiplicity": multiplicity}
    if controller:
        control["controller"] = controller
    if stopping_conditions:
        control["stopping_conditions"] = stopping_conditions
    if why_multiple:
        control["why_multiple"] = why_multiple
    s = {"name": name,
         "purpose": long(35, f"execute the bounded {name} procedure and create its downstream handoff"),
         "launch": launch or f'"{PY}" train.py --stage {name}',
         "metrics_file": f"train_metrics_{name}.json",
         "control": control,
         "budget": {"limits": limits or {"wallclock_minutes": 30}}}
    if ledger_file:
        s["ledger_file"] = ledger_file
    if uri:
        s["stage_key"] = key
        s["produces"] = [{"name": f"{name} weights", "kind": produces_kind, "uri": uri}]
    if consumes:
        s["consumes"] = consumes
    if waiver:
        s["reuse_waiver"] = waiver
    return s


def w_plan(d, out, lane_id, *, role, workdir, stages, cost="medium", enables=None,
           title=None, code_parent=None, level=None, bad_extra=None, judge=None,
           protocol=None, eval_extra=None, experiment_class="train"):
    lane = d.lane(lane_id)
    meta = json.loads((d.repo / f".evo/ideas/{lane['idea']}.meta.json").read_text(encoding="utf-8"))
    parents = list(meta.get("parents") or []) + list(meta.get("platforms_consumed") or [])
    purpose = str(meta.get("experiment_purpose") or "candidate")
    cfg = project_cfg(d)
    policy = ((cfg.get("evidence_policy") or {}).get("training_replication") or {})
    trainish = experiment_class in ("train", "finetune")
    should_repeat = trainish and purpose == "candidate" and role != "platform" \
        and policy.get("mode") == "preplanned"
    seeds = planned_seeds(cfg) if should_repeat else [1009]
    ev = {"run": f'"{PY}" eval.py', "metrics_file": "eval_metrics.json",
          "budget": {"limits": {"wallclock_minutes": 30}},
          "resource_accounting": resource_accounting()}
    if judge:
        ev["judge"] = judge
    if protocol:
        ev["protocol"] = protocol
    if eval_extra:
        ev.update(eval_extra)
    spec = {
        "title": title or f"node from {lane_id}", "role": role, "parents": parents,
        "code_parent": code_parent, "level": level if level is not None else meta["level"],
        "experiment_purpose": purpose, "experiment_class": experiment_class,
        "cost_class": cost, "workdir": workdir,
        "evidence_plan": {
            "extra_eval_arms": int((meta.get("mechanism_probe") or {}).get("extra_eval_arms") or 0),
            "declared_checks": (["mechanism_probe"] if (meta.get("mechanism_probe") or {}).get("mode")
                                in econfig.PROBE_MODES else []),
        },
        "smoke_plan": [{"name": "imports", "cmd": f'"{PY}" -c "print(7)"', "timeout_s": 120},
                       {"name": "flagcheck", "cmd": f'"{PY}" check_flag.py', "timeout_s": 120}],
        "eval": ev,
    }
    if purpose in ("candidate", "exploratory"):
        # v11.1: program-carrying purposes share one custody chain
        spec.update({
            "program_digest": meta["program_digest"],
            "kernel_ids": eprogram.kernel_ids(meta),
            "program_ir": meta["program"],
            "novelty_kernel": (meta.get("novelty") or {}).get("kernel") or [],
            "effect_case": meta.get("effect_case"),
        })
        if "theory_obligations" in meta:
            spec["theory_obligations"] = json.loads(json.dumps(meta["theory_obligations"]))
    if trainish:
        spec["training_replication"] = {
            "mode": "preplanned" if should_repeat else "single",
            "runs": len(seeds), "seeds": seeds,
            "aggregation": policy.get("aggregation") if should_repeat else "none",
            "source": "workflow" if stages else "existing_artifacts",
        }
    if purpose == "targeted_ablation":
        spec["ablation"] = meta["ablation"]
    if purpose == "diagnostic_probe":
        spec["probe"] = meta["probe"]
    if purpose == "maintenance":
        spec["maintenance"] = meta["maintenance"]
    if stages is not None:
        for stg in stages:
            if econfig.stage_requires_ledger(stg) and not stg.get("ledger_file"):
                stg["ledger_file"] = f"{workdir}/ledger_{stg.get('name')}.jsonl"
            # R9 (landing lease): stage landings are per-RUN exclusive now; a
            # bare repo-root name shared by parallel nodes is exactly the
            # cross-RUN aliasing the engine rejects. Namespace bare paths
            # under this node's workdir (mirrors the ledger default above).
            raw_metrics_path = str(stg.get("metrics_file") or "")
            if raw_metrics_path and "/" not in raw_metrics_path and "\\" not in raw_metrics_path:
                stg["metrics_file"] = f"{workdir}/{raw_metrics_path}"
            if should_repeat:
                if "{seed}" not in str(stg.get("launch") or ""):
                    stg["launch"] = str(stg.get("launch") or "") + " --seed {seed}"
                raw_metrics = str(stg.get("metrics_file") or "metrics.json")
                mp = Path(raw_metrics)
                seeded_metrics = mp.with_name(f"{mp.stem}_seed-{{seed}}{mp.suffix}").as_posix()
                if "/" not in raw_metrics and "\\" not in raw_metrics:
                    seeded_metrics = f"{workdir}/{seeded_metrics}"
                stg["metrics_file"] = seeded_metrics
                if stg.get("ledger_file"):
                    lp = Path(str(stg["ledger_file"]))
                    stg["ledger_file"] = lp.with_name(f"{lp.stem}_seed-{{seed}}{lp.suffix}").as_posix()
                if stg.get("produces"):
                    stg["stage_key"] = str(stg.get("stage_key") or stg.get("name")) + "|seed={seed}"
                    for product in stg["produces"]:
                        if "{seed}" not in str(product.get("uri") or ""):
                            product["uri"] = str(product.get("uri") or "").rstrip("/") + "/seed-{seed}"
        spec["workflow"] = {"stages": stages}
    probe = meta.get("mechanism_probe") or {}
    if probe.get("mode") in econfig.PROBE_MODES and not str(meta.get("attribution_waiver") or "").strip():
        execution = {k: json.loads(json.dumps(probe[k]))
                     for k in ("mode", "signal", "expect", "artifact", "required_fields", "decision_rule")}
        if probe["mode"] == "same_run":
            execution["producer_stage"] = str(stages[-1]["name"]) if stages else "evaluation"
            execution["smoke_artifact"] = f".evo/probes/{meta['idea']}/smoke.json"
            spec["smoke_plan"][-1].setdefault("must_exist", []).append(execution["smoke_artifact"])
        elif probe["mode"] == "eval_intervention":
            execution["command"] = f'"{PY}" probe_eval.py'
            execution["smoke_artifact"] = f".evo/probes/{meta['idea']}/smoke.json"
            spec["smoke_plan"][-1].setdefault("must_exist", []).append(execution["smoke_artifact"])
        spec["probe_execution"] = execution
        if int(probe.get("extra_eval_arms") or 0) > 0:
            spec["evidence_plan"]["value_of_information"] = probe["value_of_information"]
    if enables:
        spec["enables"] = enables
    if bad_extra:
        bad_extra(spec)
    if spec.get("experiment_class") not in ("train", "finetune"):
        spec.pop("training_replication", None)
    wj(d.repo, out["outputs"][0], spec)
    return spec


def wiring_section_for(d, node, spec):
    """v10.2 artifact wiring: derive declared consumes/produces from the spec
    and write real load/save lines the literal check binds to (shared by the
    initial, fix-pass and recovery implement writers)."""
    want_reads, want_writes = [], []
    for stg_ in (spec.get("workflow") or {}).get("stages") or []:
        for c in (stg_.get("consumes") or []):
            if isinstance(c, dict) and c.get("artifact"):
                want_reads.append(str(c["artifact"]))
            elif isinstance(c, dict) and c.get("stage"):
                want_reads.append(f"stage:{c['stage']}")
        for p in (stg_.get("produces") or []):
            if isinstance(p, dict) and p.get("uri"):
                want_writes.append(str(p["uri"]))
    want_reads = list(dict.fromkeys(want_reads))
    want_writes = list(dict.fromkeys(want_writes))
    if not want_reads and not want_writes:
        return None
    lines = [f'LOAD_{i} = load_artifact("{tok}")' for i, tok in enumerate(want_reads)]
    lines += [f'SAVE_{i} = save_artifact("{uri}")' for i, uri in enumerate(want_writes)]
    wt(d.repo, f"{node['workdir']}/wiring.py",
       "def load_artifact(x):\n    return x\n\ndef save_artifact(x):\n    return x\n\n"
       + "\n".join(lines) + "\n")
    rows = [f'READS: {tok} -> wiring.py :: CODE: LOAD_{i} = load_artifact("{tok}")'
            for i, tok in enumerate(want_reads)]
    rows += [f'WRITES: {uri} -> wiring.py :: CODE: SAVE_{i} = save_artifact("{uri}")'
             for i, uri in enumerate(want_writes)]
    return ("Artifact wiring",
            long(50, "declared inputs load and outputs save through the wiring shim") +
            "\n\n" + "\n".join(rows))


def do_maintenance_implement(d, out, nid):
    """Implement a repair the way its reviewed boundary promises: inherit the
    parent's tree untouched and rewrite ONLY the declared in-scope files."""
    node = d.node(nid)
    spec = json.loads((d.repo / node["spec"]).read_text(encoding="utf-8"))
    scope = ((spec.get("maintenance") or {}).get("change_boundary") or {}).get("files_in_scope") or []
    wd = d.repo / node["workdir"]
    idx = {n["id"]: n for n in d.graph()["nodes"]}
    cp = idx.get(node.get("code_parent") or "") or {}
    base = cp.get("commit") or cp.get("branch") or "main"
    if wd.exists():
        sh(d.repo, "git", "worktree", "remove", "--force", str(wd))
    git(d.repo, "worktree", "add", str(wd), "-B", node["branch"], base)
    # only the declared files change; wiring.py carries the repaired loader
    wiring_section = wiring_section_for(d, node, spec)   # writes wiring.py
    wt(d.repo, f"{node['workdir']}/train.py",
       "print('train')\n# repaired: resolve the checkpoint path from the declared artifact\n")
    sh(wd, "git", "add", "-A")
    sh(wd, "git", "commit", "-q", "-m", f"maintenance {nid}: repair within {scope}")
    sections = [
        ("Mechanism to code map", "- maintenance repair -> `wiring.py`\n\n"
         + long(55, "the repair keeps every approved operator intact and touches only its declared files")),
        ("Deviations", long(60, "no scientific-program change; the loader path resolution is the whole edit")),
    ]
    if wiring_section:
        sections.append(wiring_section)
    wt(d.repo, out["outputs"][0], md(*sections))


def do_implement(d, out, nid, *, git_mode=True, wrong_base=False, break_flag=False):
    node = d.node(nid)
    wd = d.repo / node["workdir"]
    if git_mode:
        idx = {n["id"]: n for n in d.graph()["nodes"]}
        cp = idx.get(node.get("code_parent") or "") or {}
        base = cp.get("commit") or cp.get("branch") or "main"
        if wrong_base:
            base = git(d.repo, "rev-parse", "HEAD~1") if not cp.get("commit") else \
                git(d.repo, "rev-parse", f"{cp['commit']}~1")
        if wd.exists():
            sh(d.repo, "git", "worktree", "remove", "--force", str(wd))
        git(d.repo, "worktree", "add", str(wd), "-b", node["branch"], base)
    else:
        wd.mkdir(parents=True, exist_ok=True)
    wt(d.repo, f"{node['workdir']}/mod_a.py", f"# reweighting module for {nid}\n")
    wt(d.repo, f"{node['workdir']}/mod_b.py", f"# head module for {nid}\n")
    wt(d.repo, f"{node['workdir']}/check_flag.py",
       "import sys, pathlib\nflag = pathlib.Path(__file__).parent / 'flag.txt'\n"
       "sys.exit(0 if flag.read_text().strip() == 'good' else 1)\n")
    wt(d.repo, f"{node['workdir']}/flag.txt", "bad" if break_flag else "good")
    wt(d.repo, f"{node['workdir']}/eval.py", "print('eval')\n")
    wt(d.repo, f"{node['workdir']}/train.py", "print('train')\n")
    spec = json.loads((d.repo / node["spec"]).read_text(encoding="utf-8"))
    op_rows = []
    for i, opid in enumerate(node.get("operator_ids") or []):
        relp = "mod_a.py" if i % 2 == 0 else "mod_b.py"
        kids = [str(k.get("id")) for k in (spec.get("novelty_kernel") or [])
                if opid in (k.get("operator_refs") or [])]
        op_rows.append(f"- {opid} [{','.join(kids)}] -> `{relp}`")
    probe = spec.get("probe_execution") or {}
    probe_section = None
    if probe:
        fields = [str(x) for x in (probe.get("required_fields") or [])]
        if probe.get("mode") == "existing_artifact":
            probe_section = ("Probe instrumentation",
                             long(55, "the frozen existing observation is read without adding training work") +
                             f"\n\nPROBE_SOURCE: {probe.get('artifact')}")
        else:
            code_lines = ["probe_values = {}"] + [f'probe_values["{field}"] = 0.97' for field in fields]
            wt(d.repo, f"{node['workdir']}/probe_runtime.py", "\n".join(code_lines) + "\n")
            smoke_values = {field: 0.97 for field in fields}
            wj(d.repo, str(probe.get("smoke_artifact")), smoke_values)
            rows = "\n".join(
                f'PROBE_FIELD: {field} -> probe_runtime.py :: CODE: probe_values["{field}"] = 0.97'
                for field in fields)
            probe_section = ("Probe instrumentation",
                             long(55, "the declared producer writes finite intermediate observations into the exact JSON contract") +
                             f"\n\nPROBE_ARTIFACT: {probe.get('artifact')}\n{rows}")
    bridge_section = None
    if node.get("needs_metric_bridge"):
        wt(d.repo, f"{node['workdir']}/metric_adapter.py",
           "def adapt_metrics(raw):\n    return {key: value for key, value in raw.items()}\n")
        bridge_section = (
            "Metric bridge adapter",
            long(50, "the adapter changes only the output container and preserves every metric value") +
            "\n\nBRIDGE_ADAPTER: metric_adapter.py :: CODE: return {key: value for key, value in raw.items()}")
    wiring_section = wiring_section_for(d, node, spec)
    if git_mode:
        sh(wd, "git", "add", "-A")
        sh(wd, "git", "commit", "-q", "-m", f"implement {nid}")
    sections = [
        ("Workarea", long(60, f"code for {nid} lives in {node['workdir']} on its own branch")),
        ("Mechanism to code map",
         "\n".join(op_rows) or "- diagnostic implementation -> `mod_a.py`"),
        ("Deviations", long(50, "no deviations from the approved idea were needed")),
        ("Self test", long(50, "the flag check and import check pass locally")),
    ]
    if probe_section:
        sections.append(probe_section)
    if bridge_section:
        sections.append(bridge_section)
    if wiring_section:
        sections.append(wiring_section)
    wt(d.repo, out["outputs"][0], md(*sections))


def fix_wrong_base(d, nid):
    node = d.node(nid)
    wd = d.repo / node["workdir"]
    sh(d.repo, "git", "worktree", "remove", "--force", str(wd))
    git(d.repo, "branch", "-D", node["branch"])


def preds_for(score, *, refute_second=False):
    p2 = score + (0.05 if refute_second else -0.002)
    return [
        {"id": "P1", "metric": "auc", "comparison": ">=", "value": round(score - 0.001, 4),
         "rationale": long(45, "the calibration channel must show up as at least this auc level")},
        {"id": "P2", "metric": "auc", "comparison": ">=", "value": round(p2, 4),
         "rationale": long(45, "an aggressive threshold that refutes the mechanism if missed")},
    ]


def stage_metrics(d, nid):
    """Numeric summaries and usage per finished stage (mirrors the engine)."""
    by = {}
    for r in d.state()["runs"]:
        if r.get("node") == nid and r.get("kind") == "stage" and r.get("status") == "finished" \
                and r.get("metrics_file") and not r.get("superseded"):
            p = d.repo / r["metrics_file"]
            if p.exists():
                m = json.loads(p.read_text(encoding="utf-8"))
                src = m.get("summary") if isinstance(m.get("summary"), dict) else m
                nums = {k: v for k, v in src.items() if isinstance(v, (int, float))}
                nums.update({f"usage.{k}": v for k, v in (m.get("usage") or {}).items()
                             if isinstance(v, (int, float))})
                if nums:
                    sname = str(r.get("stage") or "stage")
                    key = (f"seed={r.get('replica_seed')}/{sname}"
                           if int(r.get("replica_total") or 1) > 1 or r.get("repeat_measure_attempt")
                           else sname)
                    by[key] = nums
    return by


def dyn_sections(d, nid):
    """Extra EVAL_REPORT sections: stage-evidence duty (stage names +
    echoed numbers). Empty when the node never trained."""
    by = stage_metrics(d, nid)
    if not by:
        return []
    lines = []
    for sname, nums in by.items():
        vals = ", ".join(f"{k} settled at {v:g}" for k, v in nums.items())
        lines.append(f"stage {sname}: {vals}; the curve was monotone with no spikes")
    return [("Stage evidence",
             long(70, "the per stage record shows where the mechanism did its work") + " " + " ".join(lines))]


def w_eval(d, out, nid, auc, logloss=None, *, latency=100.0, bad=None, dist=False, anomalies=None, scaling_txt=None):
    node = {n["id"]: n for n in d.graph()["nodes"]}[nid]
    if logloss is None:
        # Synthetic target cells move coherently in this harness: a ranking
        # gain lowers calibration loss by the same magnitude.  This lets the
        # frozen multi-cell E contract be settled rather than ignored.
        logloss = 0.6 - max(0.0, auc - 0.7)
    m = {"auc": auc, "logloss": logloss, "latency_ms": latency,
         "_usage": {"wallclock_minutes": 1.0}}
    spec = json.loads((d.repo / d.node(nid)["spec"]).read_text(encoding="utf-8"))
    replication = spec.get("training_replication") or {}
    if replication.get("mode") == "preplanned" and not dist:
        for key in ("auc", "logloss", "latency_ms"):
            value = m[key]
            m[key] = {
                "value": value,
                "training_replication": {
                    "aggregation": replication["aggregation"],
                    "runs": [{"seed": seed, "value": value,
                              "source": f".evo/nodes/{nid}/runs/seed-{seed}"}
                             for seed in replication["seeds"]],
                },
            }
    probe_execution = spec.get("probe_execution") or {}
    probe_values_for_report = []
    if probe_execution:
        observations = []
        for expected in evalid.expected_probe_observations(spec):
            artifact = str(expected["artifact"])
            if (probe_execution.get("mode") == "eval_intervention" or
                    (probe_execution.get("mode") == "same_run" and
                     probe_execution.get("producer_stage") == "evaluation")) and not (d.repo / artifact).exists():
                wj(d.repo, artifact, {str(field): 0.97 for field in (probe_execution.get("required_fields") or [])})
            pdata = json.loads((d.repo / artifact).read_text(encoding="utf-8"))
            values = {str(field): pdata[str(field)] for field in (probe_execution.get("required_fields") or [])}
            row = {"artifact": artifact, "values": values}
            if expected.get("seed") is not None:
                row["seed"] = expected["seed"]
            observations.append(row)
            probe_values_for_report.extend(values.items())
        m["_mechanism_probe"] = {
            "mode": probe_execution.get("mode"), "signal": probe_execution.get("signal"),
            "expect": probe_execution.get("expect"),
            "required_fields": list(probe_execution.get("required_fields") or []),
            "observations": observations,
        }
    if dist:   # sampled/noisy eval: interval from one fixed prediction artifact; no retraining
        source = f".evo/nodes/{nid}/eval/fixed_predictions.json"
        wj(d.repo, source, {"prediction_count": 500, "note": "fixed outputs resampled only"})
        m["auc"] = {"value": auc, "uncertainty": {
            "method": "fixed_predictions_bootstrap", "unit": "sample", "unit_count": 500,
            "procedure": "percentile bootstrap over the fixed prediction rows", "level": 0.95,
            "lower": auc - 0.0002, "upper": auc + 0.0002, "source": source,
            "extra_training_runs": 0, "resamples": 1000}}
    raw_m = json.loads(json.dumps(m))
    raw_m["_resource_measurements"] = planned_resource_measurements(d, nid)
    if out.get("_deferred_evaluate"):
        direct_fixture = bool(out.get("_direct_deferred_evaluate"))
        raw_rel = f".evo/nodes/{nid}/eval/raw_metrics_r{int(d.node(nid).get('resource_receipt_revision') or 0) + 1}.json"
        wj(d.repo, raw_rel, raw_m)
        task = next(t for t in d.state()["tasks"] if t["id"] == out["task"])
        run = next(r for r in d.state()["runs"] if r["id"] == task["subject"]["run"])
        wj(d.repo, out["outputs"][0], {"run": run["id"], "attempt_token": run["attempt_token"],
                                      "mode": "completed", "metrics_file": raw_rel})
        accepted = d.submit(out["task"])
        ok(accepted.get("kind") == "accepted", f"unified completed eval RUN must accept: {accepted}")
        analyst = direct_node_next(d, nid, "evaluate") if direct_fixture else d.next()
        ok(analyst.get("kind") == "task" and analyst.get("type") == "evaluate",
           f"sealed raw eval must be followed by analyst task: {analyst}")
        out.clear()
        out.update(analyst)
        node = d.node(nid)
        ok(node.get("resource_receipt_ready") and node.get("resource_receipt_seal"),
           "engine seals a read-only resource receipt before analyst evaluation")
    if bad == "no_n":
        m["auc"] = {"mean": auc, "std": 0.003}
    if bad == "missing":
        m = {"auc": auc, "_usage": {"wallclock_minutes": 1.0}}
    wj(d.repo, out["outputs"][0], m)
    dyn = [] if bad == "no_dyn" else dyn_sections(d, nid)
    meta = {}
    if node.get("idea_doc"):
        mp = d.repo / node["idea_doc"].replace(".md", ".meta.json")
        if mp.exists():
            meta = json.loads(mp.read_text(encoding="utf-8"))
    secs = [
        ("Setup", long(60, "eval ran on the frozen split with the shared metric code")),
        ("Results", long(100, f"C1 ranking auc {auc} against goal 0.80; C2 calibration logloss {logloss} against goal 0.40; C3 serving latency {latency} ms against references")),
        *dyn,
    ]
    # v9 duties: anomaly hunt + registered mechanism probe + scaling probe
    if bad != "no_anom":
        secs.append(("Anomalies", anomalies or
                     long(50, "NONE - curves, rare level slices and output samples were checked")))
    if meta.get("mechanism_probe") and not str(meta.get("attribution_waiver") or "").strip() \
            and bad != "no_mech_section":
        observed_text = ", ".join(f"{field}={value:g}" for field, value in probe_values_for_report)
        secs.append(("Mechanism check",
                     long(70, "the structured probe artifact was read under the frozen mechanism contract and compared with its expectation")
                     + f" Recorded values: {observed_text}."))
    if meta.get("scaling") and (meta.get("scaling") or {}).get("execution") == "existing_artifact" \
            and bad != "no_scaling_section":
        secs.append(("Scaling probe", scaling_txt or
                     long(70, "at the 10 percent point the gain is 0.6 of full and at 50 percent it is 0.9 - the registered trend held")))
    secs.append(("Comparability", long(60, "V1 same frozen split and V2 same metric code were checked")))
    wt(d.repo, out["outputs"][1], md(*secs))


def w_conclude(d, out, nid, *, platform=False, baseline=False, lessons=None,
               root_cause=None, bad=None, services=None, observations=None,
               mech_status="confirmed", infra_resolutions=None):
    store = d.store()
    st = store.load_state()
    g = store.load_graph()
    ctx = evalid.Ctx(store, st, store.load_config(), g, store.load_artifacts())
    node = {n["id"]: n for n in g["nodes"]}[nid]
    outcome = {"lessons": lessons or []}
    if not lessons:
        outcome["no_lessons_reason"] = long(40, "nothing generalizable beyond what earlier lessons record")
    if baseline:
        outcome["verdict"] = "baseline"
    elif platform:
        outcome["verdict"] = "enabled"
        outcome["enabled_artifacts"] = [a["uri"] for a in store.load_artifacts()["artifacts"]
                                        if a["node"] == nid]
        if services:
            outcome["enabled_services"] = (
                [{"name": "bad name!", "invoke_pattern": ""}] if bad == "bad_service"
                else [{"name": s, "invoke_pattern": f"query the {s} endpoint with one key"}
                      for s in services])
    else:
        metrics = json.loads((d.repo / f".evo/nodes/{nid}/eval/metrics.json").read_text(encoding="utf-8"))
        assessment = evalid.computed_assessment(ctx, node, metrics)
        want = str(assessment["verdict"])
        outcome["verdict"] = "regressed" if bad == "verdict" and want != "regressed" else want
        meta = {}
        if node.get("idea_doc"):
            meta = json.loads((d.repo / node["idea_doc"].replace(".md", ".meta.json")).read_text(encoding="utf-8"))
        outcome["predictions"] = [
            {"id": p["id"], "verdict": evalid.check_prediction(p, metrics),
             "observed": evalid.metric_value(metrics.get(p["metric"]))}
            for p in meta.get("predictions", [])]
        if want == "regressed" and bad != "no_root_cause" and root_cause is not False:
            outcome["root_cause"] = {"assumptions": ["A1"],
                                     "note": long(50, "the propensity validity assumption failed on the rare levels slice")}
        # settle every registered SOTA target (v8 duty)
        if meta.get("sota_targets") and bad != "no_sota_settle":
            sota_rows = {r["id"]: r for r in ctx.sota_rows()}
            cells = econfig.cell_spec(ctx.cfg)
            settlements = []
            for t in meta["sota_targets"]:
                row = sota_rows[t["sota"]]
                cell = cells[t["cell"]]
                observed = evalid.metric_value(metrics.get(cell["result_key"]))
                target = row["headline"]["value"]
                met = False
                if row.get("comparability") == "exact" and t.get("dimension") == "effect":
                    met = observed >= target if econfig.result_direction(ctx.cfg, cell["result_key"]) == "max" else observed <= target
                settlements.append(
                    {"sota": t["sota"], "met": met,
                     "note": long(55, f"compared observed {observed} against {t['sota']} headline {target} on the exact frozen protocol")})
            outcome["sota"] = settlements
        # v9: mechanism attribution + scaling settlements
        if meta.get("mechanism_probe") and not str(meta.get("attribution_waiver") or "").strip() \
                and bad != "no_mech_settle":
            outcome["mechanism"] = {"status": mech_status,
                                    "note": long(50, "the calibration slope moved with the metric exactly as registered; the gain flows through the claimed channel"),
                                    "evidence": f".evo/nodes/{nid}/eval/metrics.json"}
        if meta.get("scaling") and bad != "no_scaling_settle":
            if (meta.get("scaling") or {}).get("execution") == "followup_node":
                outcome["scaling"] = {"status": "deferred",
                                      "note": long(50, "scale points are reserved for an explicit descendant after this node shows a positive signal")}
            else:
                outcome["scaling"] = {"held": True,
                                      "note": long(50, "gains at the two reused scale points follow the registered monotone trend")}
        if node.get("experiment_purpose") == "targeted_ablation":
            contract = meta["ablation"]
            outcome.pop("mechanism", None)
            outcome.pop("scaling", None)
            outcome["ablation_result"] = {
                "effect": "observed", "supports": contract["effect_supports"],
                "decision": contract["decision_if_effect"],
                "evidence": f".evo/nodes/{nid}/eval/metrics.json",
                "note": long(65, "the registered target moved under the one-factor intervention while every held constant passed audit"),
            }
        elif node.get("experiment_purpose") == "diagnostic_probe":
            outcome.pop("mechanism", None)
            outcome.pop("scaling", None)
        elif node.get("experiment_purpose") == "maintenance":
            outcome.pop("mechanism", None)
            outcome.pop("scaling", None)
            outcome["maintenance_parity"] = evalid.maintenance_parity_status(assessment)
        else:
            outcome["effect_contract_status"] = assessment["effect_contract_status"]
    # v9: phenomenon-ledger mining (any role)
    if observations:
        outcome["observations"] = observations
    if infra_resolutions is not None:
        outcome["infra_resolutions"] = infra_resolutions
    wj(d.repo, out["outputs"][0], outcome)
    result_sections = [
        ("What was built", long(60, f"node {nid} implements its approved idea in an isolated workarea")),
        ("What happened", long(80, "C1 and C2 target cells plus C3 global latency guardrail were compared with their fixed references")),
        ("Interpretation", long(60, "the verdict follows the engine-computed comparison against the reference")),
    ]
    if not platform:
        result_sections.append(("Absolute goal status",
                                long(65, "the sourced C1 and C2 absolute thresholds were checked separately from relative progress")))
    if not platform and not baseline and node.get("experiment_purpose") not in (
            "targeted_ablation", "diagnostic_probe", "maintenance"):
        result_sections.append((
            "Effect contract",
            long(120, "the exact frozen comparator was used for every C target floor and guardrail, while realized candidate and comparator intervals were reconciled across all nine resource axes")))
    if node.get("experiment_purpose") == "maintenance":
        result_sections.append((
            "Parity settlement",
            long(70, "every claim target and guardrail cell landed noninferior or improved against the repaired parent")))
    wt(d.repo, out["outputs"][1], md(
        *result_sections))


def w_fidelity(d, out, nid, *, bad=None):
    """Claim->code map string-checked by the engine. do_implement wrote mod_a/mod_b
    with node-id-bearing comments; quote those."""
    node = d.node(nid)
    idea = json.loads((d.repo / str(node["idea_doc"]).replace(".md", ".meta.json")).read_text(encoding="utf-8"))
    rows = []
    for i, opid in enumerate(node.get("operator_ids") or []):
        relp = "mod_a.py" if i % 2 == 0 else "mod_b.py"
        snippet = f"reweighting module for {nid}" if relp == "mod_a.py" else f"head module for {nid}"
        kids = [str(k.get("id")) for k in eprogram.kernel_components(idea)
                if opid in (k.get("operator_refs") or [])]
        rows.append((f"{' '.join(kids)} {opid} load-bearing semantics", relp, snippet))
    if bad in ("snippet", "deviates"):
        rows[0] = ("reweighted objective term", "mod_a.py", "a snippet that exists nowhere in the file")
    verdict = "DEVIATES" if bad == "deviates" else "FAITHFUL"
    wt(d.repo, out["outputs"][0], f"FIDELITY: {verdict}\n\n" + md(
        ("Claim map", "\n".join(f"- {c} -> {p} :: CODE: {s}" for c, p, s in rows)),
        ("Omissions and simplifications", long(60, "NONE-FOUND after diffing the idea mechanism against both modules")),
        ("Audit verdict", long(60, "both load bearing claims verified by literal inspection of the committed code")),
    ))


def drive_fidelity(d, nid, *, neg=False):
    out = nx(d, "fidelity")
    if neg:
        w_fidelity(d, out, nid, bad="deviates")
        sub_rej(d, out, "FIDELITY_DEVIATES", "FIDELITY_SNIPPET")
        # A genuine code/idea mismatch is not repaired by rewriting the audit.
        # The engine cancels that audit and opens a new implementation
        # revision, followed by a fresh smoke and fidelity pass.
        out = nx(d, "implement")
        do_fix_implement(d, out, nid)
        sub_ok(d, out)
        out = nx(d, "smoke")
        ok(d.smoke(nid)["status"] == "pass", f"fidelity repair smoke for {nid} should pass")
        sub_ok(d, out)
        out = nx(d, "fidelity")
    w_fidelity(d, out, nid)
    sub_ok(d, out)


def maybe_fidelity(d, nid):
    if d.node(nid).get("fidelity_pending"):
        drive_fidelity(d, nid)


LOCAL_CANARY_ADAPTER = r'''import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path

request_path = Path(os.environ["EVO_CANARY_REQUEST"])
result_path = Path(os.environ["EVO_CANARY_RESULT"])
request = json.loads(request_path.read_text(encoding="utf-8"))
nonce = os.environ["EVO_CANARY_NONCE"]

if "--mutate-request" in sys.argv:
    request["artifact_probe_uri"] = "local://weakened/request/path"
    request["datasets"] = []
    request_path.write_text(json.dumps(request), encoding="utf-8")

sync_arg = next((arg.split("=", 1)[1] for arg in sys.argv
                 if arg.startswith("--sync-file=")), None)
if sync_arg:
    sync_path = Path(sync_arg)
    ready_path = Path(str(sync_path) + ".ready")
    release_path = Path(str(sync_path) + ".release")
    ready_path.write_text(nonce, encoding="utf-8")
    deadline = time.time() + 5.0
    while not release_path.exists() and time.time() < deadline:
        time.sleep(0.01)
    if not release_path.exists():
        raise SystemExit("concurrency test release was not supplied")

if "--blocked" in sys.argv:
    result_path.write_text(json.dumps({
        "nonce": nonce,
        "blockers": [{
            "missing": "local canary credential fixture is deliberately unavailable",
            "needed_for": "the integrated tiny data compute artifact and evaluation path",
            "ask": "install the deterministic test credential and approve a fresh complete canary run"
        }]
    }), encoding="utf-8")
    print("local canary deliberately blocked after receiving nonce", nonce)
    raise SystemExit(23)

# A fresh input byte stream feeds the computation and the disposable artifact,
# so neither a pre-written transcript nor a stale result can satisfy the run.
source = Path("README.md")
payload = source.read_bytes()[:128] + nonce.encode("ascii")
input_digest = hashlib.sha256(payload).hexdigest()
computed = hashlib.sha256((input_digest + nonce).encode("ascii")).hexdigest()

probe_dir = Path(".evo/profile/local_canary_artifacts")
probe_dir.mkdir(parents=True, exist_ok=True)
probe = probe_dir / ("probe-" + nonce + ".bin")
probe.write_bytes(payload + computed.encode("ascii"))
roundtrip = probe.read_bytes()
if roundtrip != payload + computed.encode("ascii"):
    raise SystemExit("artifact round-trip mismatch")
artifact_digest = hashlib.sha256(roundtrip).hexdigest()
probe.unlink()
artifact_deleted = not probe.exists()
if not artifact_deleted:
    raise SystemExit("disposable artifact cleanup failed")

omit_service = "--omit-service" in sys.argv
omit_surface = next((arg.split("=", 1)[1] for arg in sys.argv
                     if arg.startswith("--omit-surface=")), None)
half = next((arg.split("=", 1)[1] for arg in sys.argv
             if arg.startswith("--half=")), None)
surfaces_slice = request["required_surfaces"]
if half == "A":
    surfaces_slice = surfaces_slice[:(len(surfaces_slice) + 1) // 2]
elif half == "B":
    surfaces_slice = surfaces_slice[(len(surfaces_slice) + 1) // 2:]
checks = []
for surface in surfaces_slice:
    if surface == omit_surface or (omit_service and str(surface).startswith("service:")):
        continue
    if str(surface).startswith("service:"):
        # Exercise an actual local request/response boundary without relying on
        # a network service outside the regression environment.
        client, server = socket.socketpair()
        try:
            client.sendall(("ping:" + nonce).encode("ascii"))
            observed = server.recv(256)
            server.sendall(b"pong:" + observed)
            reply = client.recv(512)
            if not reply.startswith(b"pong:ping:"):
                raise SystemExit("local service round-trip failed")
        finally:
            client.close()
            server.close()
        detail = "local service request and response crossed a real socket boundary"
    elif surface == "workspace":
        detail = "adapter resolved and executed inside the requested project workspace"
    elif surface == "data":
        detail = "tiny project input was read and nonce-bound with digest " + input_digest[:12]
    elif str(surface).startswith("dataset:"):
        dataset_name = str(surface).split(":", 1)[1]
        dataset = next(row for row in request["datasets"] if row["name"] == dataset_name)
        detail = ("dataset manifest and tiny access were bound for " + dataset_name
                  + " at " + str(dataset["uri"]))
    elif str(surface).startswith("evaluation-dataset:"):
        dataset_id = str(surface).split(":", 1)[1]
        dataset = next(row for row in request["evaluation_datasets"] if row["id"] == dataset_id)
        detail = ("approved evaluation dataset protocol was exercised for " + dataset_id
                  + " split " + str(dataset["split"]))
    elif surface == "compute":
        detail = "real adapter computation produced nonce-bound digest " + computed[:12]
    elif surface == "artifact_store":
        detail = "disposable artifact was written read byte-checked and deleted"
    elif surface == "evaluation":
        detail = "tiny evaluator emitted every configured result key from the fresh path"
    else:
        detail = "required local surface completed a real nonce-bound canary operation"
    checks.append({"surface": surface, "status": "pass", "detail": detail})

metrics = {key: float(i + 1) / 10.0
           for i, key in enumerate(request["evaluation_result_keys"])}
observation = {
    "nonce": ("definitely-stale-nonce" if "--wrong-nonce" in sys.argv else nonce),
    "checks": checks,
    # half A defers metrics to the command that runs the tiny evaluator (B)
    **({} if half == "A" else {"metrics": metrics}),
    "trace": {
        "input_digest": input_digest,
        "artifact_digest": artifact_digest,
        "artifact_deleted": artifact_deleted,
        "requested_artifact_uri": request["artifact_probe_uri"]
    }
}
if "--pass-with-blocker" in sys.argv:
    observation["blockers"] = [{
        "missing": "contradictory success still claims a required credential is missing",
        "needed_for": "the supposedly successful integrated canary resource path",
        "ask": "supply the missing credential despite this process exiting successfully"
    }]
result_path.write_text(json.dumps(observation), encoding="utf-8")
print("local integrated canary passed", nonce, len(checks), "surfaces")
'''


def _write_canary_report(d, out, status):
    readiness = ("the engine-owned canary receipt proves every required surface passed"
                 if status == "passed" else
                 "the engine-owned canary receipt carries a typed blocker for the user gate")
    wt(d.repo, out["outputs"][0], md(
        ("Canary executed", long(90, "one fresh nonce joined tiny input compute artifact round trip cleanup and evaluation")),
        ("Surprises", long(70, "the local adapter exposed each boundary in one causally linked transaction")),
        ("Readiness", long(70, readiness)),
    ))


def _write_canary_plan(d, out, *args):
    adapter_rel = ".evo/profile/LOCAL_CANARY_ADAPTER.py"
    wt(d.repo, adapter_rel, LOCAL_CANARY_ADAPTER)
    command = f'"{PY}" {adapter_rel}'
    if args:
        command += " " + " ".join(args)
    wj(d.repo, out["outputs"][1], {
        "schema": 1,
        "canary": {
            "command": command,
            "cwd": ".",
            "timeout_s": 60,
            "description": long(120, "one local subprocess reads tiny project input computes a nonce-bound payload writes reads verifies and deletes an artifact then emits every metric"),
        },
    })


def _write_canary_plan_multi(d, out):
    adapter_rel = ".evo/profile/LOCAL_CANARY_ADAPTER.py"
    wt(d.repo, adapter_rel, LOCAL_CANARY_ADAPTER)
    wj(d.repo, out["outputs"][1], {
        "schema": 1,
        "canaries": [
            {"command": f'"{PY}" {adapter_rel} --half=A', "cwd": ".", "timeout_s": 60,
             "description": long(60, "first real command exercises the first half of the required resource surfaces under the shared nonce")},
            {"command": f'"{PY}" {adapter_rel} --half=B', "cwd": ".", "timeout_s": 60,
             "description": long(60, "second real command exercises the remaining surfaces and runs the tiny evaluator emitting every configured key")},
        ],
    })


def w_drills(d, out, *, blocked=False, bad=None, services=(), multi=False):
    """Write the canary plan/report; only ecanary.run may author execution proof.

    The two legacy negative modes intentionally stop before ``ecanary.run``.
    Every positive or blocked path executes the adapter as a real subprocess.
    """
    _write_canary_report(d, out, "blocked" if blocked else "passed")
    if bad == "no_evidence":
        # Regression: old independent, self-authored transcripts are not an
        # integrated canary plan and cannot become execution evidence.
        legacy_dir = ".evo/profile/drills"
        drills = []
        for name, surface in (("tiny-submit", "compute"),
                              ("store-probe", "artifact_store"),
                              ("eval-fixture", "evaluation")):
            evidence = f"{legacy_dir}/{name}.log"
            wt(d.repo, evidence, f"hand-written {name} transcript\nexit 0\n")
            drills.append({"name": name, "category": surface,
                           "cmd": f"echo {name}", "status": "pass",
                           "observed": long(35, "the transcript claims the probe passed"),
                           "evidence": evidence})
        wj(d.repo, out["outputs"][1], {"drills": drills})
        return None
    if multi:
        _write_canary_plan_multi(d, out)
        receipt = ecanary.run(d.store(), out["task"])
        ok(receipt["status"] == "passed",
           f"real multi-command canary status {receipt['status']} == passed: {receipt.get('errors')}")
        rows = receipt.get("commands") or []
        ok(len(rows) == 2 and all(r.get("exit") == 0 for r in rows),
           "both real commands ran under one nonce with exit 0")
        merged = set()
        for row in rows:
            obs = json.loads((d.repo / row["observation"]).read_text(encoding="utf-8"))
            surfaces_here = {c["surface"] for c in obs["checks"]}
            ok(surfaces_here and surfaces_here != set(
                ecanary.required_surfaces(d.store(), d.store().load_config(), d.graph())),
               "each command covers a strict SUBSET - coverage is genuinely joint")
            merged |= surfaces_here
        required = set(ecanary.required_surfaces(d.store(), d.store().load_config(), d.graph()))
        ok(merged == required,
           f"the two commands JOINTLY cover every required surface: {sorted(merged)}")
        return receipt
    args = (["--blocked"] if blocked else
            ["--omit-service"] if bad == "omit_service" else
            ["--wrong-nonce"] if bad == "wrong_nonce" else
            ["--mutate-request"] if bad == "mutate_request" else
            ["--pass-with-blocker"] if bad == "pass_blockers" else
            ["--omit-surface=" + str(bad).split(":", 1)[1]] if str(bad).startswith("omit:") else [])
    _write_canary_plan(d, out, *args)
    if bad == "cover":
        # A valid plan without an engine-issued run/receipt is still only intent.
        return None
    receipt = ecanary.run(d.store(), out["task"])
    expected = ("blocked" if blocked else "failed"
                if bad in ("omit_service", "wrong_nonce", "mutate_request", "pass_blockers") or str(bad).startswith("omit:")
                else "passed")
    ok(receipt["status"] == expected,
       f"real local infrastructure canary status {receipt['status']} == {expected}: {receipt}")
    if expected == "passed":
        observation = json.loads((d.repo / receipt["observation"]).read_text(encoding="utf-8"))
        required = set(ecanary.required_surfaces(d.store(), d.store().load_config(), d.graph()))
        observed = {row["surface"] for row in observation["checks"]}
        ok(observed == required, f"local canary covers every required surface: {sorted(observed)}")
        ok(observation["trace"]["artifact_deleted"] is True
           and not list((d.repo / ".evo/profile/local_canary_artifacts").glob("probe-*.bin")),
           "local canary really writes, byte-checks and deletes its disposable artifact")
        for service in services:
            ok(f"service:{service}" in observed,
               f"local canary performs the required service round-trip for {service}")
    return receipt


def w_sota(d, out, *, bad=None, append=0):
    p = d.repo / ".evo/evidence/SOTA.jsonl"
    # R7: the declared noise-synthesis handoff file must exist (validator
    # SOTA_NOISE_MISSING); the mock states the no-adjustment case explicitly.
    (d.repo / ".evo/evidence/SOTA_NOISE.md").write_text(
        "No noise-floor adjustment needed: the six comparable works report "
        "single-run headline numbers on the frozen split with no published "
        "run-to-run spread; the configured floors already cover the "
        "leaderboard neighbor gaps (S001-S006).\n", encoding="utf-8")
    if append:
        start = len(eutil.read_jsonl(p)) if p.exists() else 0
        for k in range(append):
            i = start + k + 1
            eutil.append_jsonl(p, {
                "id": f"S{i:03d}", "title": f"sota refresh work {i}",
                "venue": "ICLR", "year": 2026, "url": f"https://example.org/s{i}",
                "task": "same-dataset ranking of the forty price levels",
                "dataset": "frozen part=9", "cell": "C1", "comparability": "exact",
                "method": long(35, f"refresh work {i} rescales the target field"),
                "headline": {"metric": "auc", "value": round(0.74 + i / 1000, 4),
                             "protocol": "frozen split shared with this project"},
                "relevance": ["B1"]})
        return
    rows = []
    for i in range(1, 7):
        cell = "C2" if i == 6 else "C1"
        metric = "logloss" if i == 6 else "auc"
        rows.append({"id": f"S{i:03d}", "title": f"sota work {i} on counterfactual ranking",
                     "venue": "NeurIPS" if i % 2 else "ICML", "year": 2025,
                     "url": f"https://example.org/s{i}",
                     "task": "same-dataset ranking of the forty price levels",
                     "dataset": "frozen part=9", "cell": cell, "comparability": "exact",
                     "method": long(35, f"work {i} reweights the target field"),
                     "headline": {"metric": metric, "value": round(0.72 + i / 1000, 4),
                                  "protocol": "frozen split shared with this project"},
                     "relevance": ["B1"]})
    if bad == "venue_year":
        rows[0]["venue"] = "SomeBlog"
        rows[1]["year"] = 2019
        rows[2].pop("headline")
        rows[3]["cell"] = "C999"
        rows[4]["comparability"] = "handwavy"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def w_retro(d, out, rid, *, retire=None, bad=None):
    # v10.1: close_round's only output is RETIRE.json (RETRO.md was removed -
    # the engine computes frontier movement itself and nothing read the prose).
    wj(d.repo, out["outputs"][0], retire or [])


def brief(d, rid, name):
    rel = f".evo/rounds/{rid}/lanes/{name}/BRIEF.md"
    wt(d.repo, rel, md(
        ("Goal", long(60, f"lane {name} attacks B1 with a measurable auc movement on the frozen split")),
        ("Constraints", long(60, "respect V1 and V2; budget one medium training per node")),
        ("Forbidden moves", long(60, "no metric hacks, no split changes, no ensembles of the baseline with itself")),
    ))
    return rel


def w_portfolio(d, out, rid, lanes_def):
    for ln in lanes_def:
        ln.setdefault("experiment_purpose", "candidate")
        ln.setdefault("search_origin", "constructive" if ln.get("intent") in
                      ("wildcat", "moonshot", "hybrid", "platform") else "repair")
        if ln["search_origin"] == "theory_derived":
            ln.setdefault("theory_rigor", "partial")
        ln.setdefault("brief_md", brief(d, rid, ln["name"]))
        ln.setdefault("bottleneck_ids", ["B1"])
    wj(d.repo, out["outputs"][0], {"lanes": lanes_def})


# --------------------------------------------------------------------------- shared drivers
def direct_lane_next(d, lane_id, expected=None):
    """Drive one lane even when the enclosing long-run fixture is already done."""
    eng = d.eng()
    lane = eng.store.get_lane(eng.st, lane_id)
    out = eng._next_lane_task(lane)
    eng.save()
    ok(out is not None, f"lane {lane_id} should have a next action")
    if expected is not None:
        ok(out.get("type") == expected, f"lane {lane_id} expected {expected}, got {out}")
    return out


def direct_node_next(d, node_id, expected=None):
    """Drive one node directly; scheduler logic and task validators stay real."""
    eng = d.eng()
    node = eng.node(node_id)
    out = eng._next_node_task(node)
    eng.save()
    ok(out is not None, f"node {node_id} should have a next action")
    if expected == "evaluate" and out.get("type") == "eval_launch":
        # All evaluators are now evidence-producing RUNs.  ``w_eval`` will
        # complete this launch and replace the dict with the analyst task.
        out["_deferred_evaluate"] = True
        out["_direct_deferred_evaluate"] = True
        return out
    if expected is not None:
        ok(out.get("type") == expected, f"node {node_id} expected {expected}, got {out}")
    return out


def w_bridge(d, out):
    base = json.loads((d.repo / ".evo/nodes/N001/eval/metrics.json").read_text(encoding="utf-8"))
    decision_keys = econfig.result_spec(d.store().load_config())
    produced = {key: evalid.metric_value(base.get(key)) for key in decision_keys}
    wj(d.repo, out["outputs"][0], {
        "command": f'"{PY}" -c "from metric_adapter import adapt_metrics"',
        "adapter": "metric_adapter.py", "produced": produced, "tolerance_pct": 0.5,
    })


def write_stage_result(d, nid, stage_name, metrics_rel, summary, *, seed=None, probe_value=0.97,
                       repeat=False):
    """Write the canonical stage result and any required decision ledger."""
    spec = json.loads((d.repo / d.node(nid)["spec"]).read_text(encoding="utf-8"))
    stg = next(s for s in econfig.stages_of(spec) if s.get("name") == stage_name)
    limits = ((stg.get("budget") or {}).get("limits") or {})
    usage = {k: float(v) / 2.0 for k, v in limits.items()}
    payload = {"summary": summary, "usage": usage}
    rep = spec.get("training_replication") or {}
    if rep.get("mode") == "preplanned" or repeat:
        payload["seed"] = seed
    if (stg.get("control") or {}).get("mode") == "preregistered_adaptive":
        payload["stop_reason"] = "the preregistered finite resource horizon was reached"
    wj(d.repo, metrics_rel, payload)
    probe = spec.get("probe_execution") or {}
    if probe.get("mode") == "same_run" and probe.get("producer_stage") == stage_name and not repeat:
        # the repeat buy-back lane carries no probe duty (R9-002)
        artifact = str(econfig.resolve_seed_template(probe.get("artifact") or "", seed)) \
            if seed is not None else str(probe.get("artifact") or "")
        wj(d.repo, artifact, {str(field): probe_value for field in (probe.get("required_fields") or [])})
    if not econfig.stage_requires_ledger(stg):
        return None
    ledger_rel = (str(econfig.resolve_seed_template(stg["ledger_file"], seed))
                  if seed is not None else str(stg["ledger_file"]))
    wt(d.repo, ledger_rel,
       json.dumps({"step": 1, "observation": "candidate measured", "decision": "selected best registered candidate"}) + "\n")
    return ledger_rel


def w_launch(d, out, stage_name, *, mode="background", job=None, metrics_rel=None, bad_stage=False):
    data = {"stage": "wrong-stage" if bad_stage else stage_name, "mode": mode}
    task = next(t for t in d.state()["tasks"] if t["id"] == out["task"])
    run = next(r for r in d.state()["runs"] if r["id"] == task["subject"]["run"])
    data["run"] = run["id"]
    data["attempt_token"] = run["attempt_token"]
    nid = task["subject"]["node"]
    seed = task["subject"].get("replica_seed")
    if seed is not None:
        data["seed"] = seed
    spec = json.loads((d.repo / d.node(nid)["spec"]).read_text(encoding="utf-8"))
    stg = next(s for s in econfig.stages_of(spec) if s.get("name") == stage_name)
    repeat = bool(run.get("repeat_measure_attempt"))
    ledger_rel = (str(econfig.resolve_seed_template(stg.get("ledger_file"), seed))
                  if seed is not None and econfig.stage_requires_ledger(stg) else
                  stg.get("ledger_file") if econfig.stage_requires_ledger(stg) else None)
    if (spec.get("training_replication") or {}).get("mode") == "preplanned":
        metrics_rel = str(econfig.resolve_seed_template(stg.get("metrics_file") or "", seed))
    if mode == "background":
        data["job"] = job or "job-x"
        if ledger_rel:
            data["ledger_file"] = ledger_rel
    else:
        ledger_rel = write_stage_result(d, nid, stage_name, metrics_rel, {"loss": 0.1}, seed=seed,
                                        repeat=repeat)
        data["metrics_file"] = metrics_rel
        if ledger_rel:
            data["ledger_file"] = ledger_rel
    wj(d.repo, out["outputs"][0], data)


def w_launch_eval(d, out, *, job=None, bad=None):
    data = {"mode": "background"}
    task = next(t for t in d.state()["tasks"] if t["id"] == out["task"])
    run = next(r for r in d.state()["runs"] if r["id"] == task["subject"]["run"])
    data["run"] = run["id"]
    data["attempt_token"] = run["attempt_token"]
    if bad != "no_job" and job:
        data["job"] = job
    wj(d.repo, out["outputs"][0], data)


def last_run(d):
    return d.state()["runs"][-1]


def finish_run(d, run_id, metrics_rel, *, probe_value=0.97):
    run = next(r for r in d.state()["runs"] if r["id"] == run_id)
    spec = json.loads((d.repo / d.node(run["node"])["spec"]).read_text(encoding="utf-8"))
    stg = next(s for s in econfig.stages_of(spec) if s.get("name") == (run.get("stage") or "stage"))
    repeat = bool(run.get("repeat_measure_attempt"))
    if (spec.get("training_replication") or {}).get("mode") == "preplanned":
        metrics_rel = str(econfig.resolve_seed_template(stg.get("metrics_file") or "", run.get("replica_seed")))
    ledger_rel = write_stage_result(d, run["node"], run.get("stage") or "stage",
                                    metrics_rel, {"loss": 0.1}, seed=run.get("replica_seed"),
                                    probe_value=probe_value, repeat=repeat)
    d.run_update(run_id, "finished", metrics_file=metrics_rel, ledger_file=ledger_rel)


def do_fix_implement(d, out, nid):
    node = d.node(nid)
    next_revision = int(node.get("implementation_revision") or 0) + 1
    wt(d.repo, f"{node['workdir']}/mod_a.py",
       f"# reweighting module for {nid} fixed at implementation revision {next_revision}\n")
    flag = d.repo / node["workdir"] / "flag.txt"
    if flag.exists():
        wt(d.repo, f"{node['workdir']}/flag.txt", "good")
    spec = json.loads((d.repo / node["spec"]).read_text(encoding="utf-8"))
    probe = spec.get("probe_execution") or {}
    op_rows = []
    for i, opid in enumerate(node.get("operator_ids") or []):
        relp = "mod_a.py" if i % 2 == 0 else "mod_b.py"
        kids = [str(k.get("id")) for k in (spec.get("novelty_kernel") or [])
                if opid in (k.get("operator_refs") or [])]
        op_rows.append(f"- {opid} [{','.join(kids)}] -> `{relp}`")
    sections = [
        ("Workarea", long(60, f"fix pass for {nid} in {node['workdir']} on the same branch")),
        ("Mechanism to code map",
         "\n".join(op_rows) or "- diagnostic implementation -> `mod_a.py`"),
        ("Deviations", long(50, "reduced the batch size after the recorded out of memory failure")),
        ("Self test", long(50, "the flag check and import check pass locally after the fix")),
    ]
    if probe:
        if probe.get("mode") == "existing_artifact":
            body = long(55, "the fixed implementation still reads the frozen existing observation") + \
                f"\n\nPROBE_SOURCE: {probe.get('artifact')}"
        else:
            rows = "\n".join(
                f'PROBE_FIELD: {field} -> probe_runtime.py :: CODE: probe_values["{field}"] = 0.97'
                for field in (probe.get("required_fields") or []))
            body = long(55, "the fix preserves the exact registered instrumentation and output schema") + \
                f"\n\nPROBE_ARTIFACT: {probe.get('artifact')}\n{rows}"
        sections.append(("Probe instrumentation", body))
    if node.get("needs_metric_bridge"):
        sections.append((
            "Metric bridge adapter",
            long(50, "the existing sealed adapter remains unchanged and preserves every metric value") +
            "\n\nBRIDGE_ADAPTER: metric_adapter.py :: CODE: return {key: value for key, value in raw.items()}"))
    wiring_section = wiring_section_for(d, node, spec)
    if wiring_section:
        sections.append(wiring_section)
    if (project_cfg(d).get("project") or {}).get("vcs") == "git":
        wd = d.repo / node["workdir"]
        # Selective add: the failed stage's untracked runtime landings must NOT
        # become tracked (a later stage rewrites them -> SEALED_IMPLEMENTATION_DIRTY).
        add_files = ["mod_a.py", "flag.txt"]
        if (wd / "wiring.py").exists():
            add_files.append("wiring.py")
        sh(wd, "git", "add", *add_files)
        sh(wd, "git", "commit", "-q", "-m", f"fix implementation {nid} r{next_revision}")
    wt(d.repo, out["outputs"][0], md(*sections))


def drive_lane_to_plan(d, name, *, dims, mech_papers=("E001", "E005"), deep_n=2,
                       hybrid_parents=None, reframe=False, theory_steps=None,
                       leverage=False, winner="K1"):
    """Drive either a fresh or already-frozen lane through tournament/theory.

    Constructive lanes freeze complete programs before literature inspection.  A
    multi-lane round may therefore have already advanced this lane to
    ``deep_read`` while another, higher-priority lane was completed.
    """
    lane = d.lane_by_name(name)
    lid = lane["id"]
    if lane.get("search_origin") == "repair":
        mech_ids = [c["id"] for c in eutil.read_jsonl(d.repo / ".evo/evidence/MECH_CARDS.jsonl")
                    if c.get("lane") == lid]
        # ``D.next`` auto-completes the method-blind diagnosis fixture, so a
        # fresh repair lane may still report ``diagnose`` immediately before
        # the requested deep-read task is emitted.
        if d.lane(lid).get("status") in ("diagnose", "deep_read"):
            out = nx(d, "deep_read")
            mech_ids += w_mech_cards(d, lid, deep_n, list(mech_papers))
            sub_ok(d, out)
        if d.lane(lid).get("status") == "sketch":
            out = nx(d, "sketch")
            w_sketches(d, out, lid, dims, mech_ids, hybrid_parents=hybrid_parents, reframe=reframe)
            sub_ok(d, out)
    else:
        if d.lane(lid).get("status") == "sketch":
            out = nx(d, "sketch")
            w_sketches(d, out, lid, dims, [], hybrid_parents=hybrid_parents, reframe=reframe)
            sub_ok(d, out)
        mech_ids = [c["id"] for c in eutil.read_jsonl(d.repo / ".evo/evidence/MECH_CARDS.jsonl")
                    if c.get("lane") == lid]
        if d.lane(lid).get("status") == "deep_read":
            out = nx(d, "deep_read")
            mech_ids += w_mech_cards(d, lid, deep_n, list(mech_papers))
            sub_ok(d, out)
    # Repair reads once before invention and once after the exact program set
    # is frozen.  The second pass may reuse M# facts but must write new CA#
    # edges for this digest.
    if d.lane(lid).get("status") == "deep_read":
        out = nx(d, "deep_read")
        sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, lid, winner, leverage=leverage)
    sub_ok(d, out)
    for step, kw in (theory_steps or []):
        if step == "theorize":
            out = nx(d, "theorize")
            w_theory(d, out, lid, **kw)
            sub_ok(d, out)
        elif step == "challenge":
            out = nx(d, "challenge")
            w_challenge(d, out, lid, **kw)
            sub_ok(d, out)
    return lid, mech_ids


def drive_mature_redteam(d, lid, *, mech_ids, score, refute_second=False, n_assum=2,
                         deriv_chars=300, platform=False, hybrid=False, theory=False,
                         formal=False, adapt_only=False, dominance=None, waiver=False,
                         interface_changed=False):
    out = nx(d, "mature")
    w_mature(d, out, lid, mech_ids=mech_ids,
             preds=preds_for(score, refute_second=refute_second),
             n_assum=n_assum, deriv_chars=deriv_chars, platform=platform,
             hybrid=hybrid, theory=theory, formal=formal, adapt_only=adapt_only,
             dominance=dominance, waiver=waiver, interface_changed=interface_changed)
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, lid)
    sub_ok(d, out)


def drive_plan(d, lid, *, role, stages, code_parent, cost="medium", enables=None):
    out = nx(d, "plan_node")
    nslug = f"n{int(d.state()['counters']['N']) + 1:03d}"
    w_plan(d, out, lid, role=role, workdir=f"workareas/{nslug}", stages=stages,
           cost=cost, enables=enables, code_parent=code_parent)
    sub_ok(d, out)
    return d.lane(lid)["node"]


def drive_node_to_training(d, nid, *, bridge=False, job="job-bg"):
    out = nx(d, "implement")
    do_implement(d, out, nid)
    sub_ok(d, out)
    out = nx(d, "smoke")
    res = d.smoke(nid)
    ok(res["status"] == "pass", f"smoke for {nid} should pass: {res}")
    sub_ok(d, out)
    maybe_fidelity(d, nid)   # L3+/heavy nodes carry the claim->code audit (v8)
    if bridge:
        out = nx(d, "metric_bridge")
        w_bridge(d, out)
        sub_ok(d, out)
    out = nx(d, "stage_launch")
    stg = d.state()["tasks"][-1]["subject"]["stage"]
    w_launch(d, out, stg, job=job)
    sub_ok(d, out)
    return last_run(d)["id"]


def drive_watch_finish(d, run_id, nid, stage, *, probe_value=0.97):
    node = d.node(nid)
    out = nx(d, "stage_watch")
    r = d.submit(out["task"])
    ok(r["kind"] == "waiting", f"watch should wait while {run_id} runs: {r}")
    finish_run(d, run_id, f"{node['workdir']}/train_metrics_{stage}.json", probe_value=probe_value)
    r = d.submit(out["task"])
    ok(r["kind"] == "accepted", f"watch submit after finish: {r}")


def drive_eval_conclude(d, nid, score, *, logloss=None, latency=100.0, lessons=None, neg_root_cause=False):
    out = nx(d, "evaluate")
    w_eval(d, out, nid, score, logloss=logloss, latency=latency)
    sub_ok(d, out)
    out = nx(d, "conclude")
    if neg_root_cause:
        w_conclude(d, out, nid, bad="no_root_cause")
        sub_rej(d, out, "OUTCOME_ROOT_CAUSE")
    w_conclude(d, out, nid, lessons=lessons)
    sub_ok(d, out)


def w_probe_design(d, out, lid, *, bad=None):
    lane = d.lane(lid)
    iid = lane["idea"]
    parent = lane["parents"][0]
    meta = {
        "idea": iid, "lane": lid, "title": f"probe {iid}",
        "experiment_purpose": "diagnostic_probe", "level": 0,
        "parents": [parent],
        "evaluation_scope": {"target_cells": ["C1"]},
        "probe": {
            "question": long(45, "does the observed auc gain survive on the frozen validation split alone"),
            "measurement_plan": long(65, "run the existing evaluator once against the parent checkpoint on the frozen split and record auc"),
            "decision_impact": long(45, "a stable answer decides whether the next round exploits or reforms this lineage"),
            "budget": {"wallclock_minutes": 60},
        },
    }
    if bad == "leak":
        meta["novelty"] = {"kind": "irreducible"}
    wj(d.repo, out["outputs"][1], meta)
    wt(d.repo, out["outputs"][0], md(
        ("Question", long(45, "does the observed auc gain survive on the frozen split alone")),
        ("Why now", long(45, "the parent concluded and the next portfolio depends on the answer")),
        ("Measurement plan", long(65, "one evaluator pass over the existing checkpoint with recorded auc")),
        ("Decision impact", long(45, "the answer picks between exploit and reform for this lineage")),
        ("Cost", long(45, "one quick evaluation inside a sixty minute wallclock cap")),
    ))


def w_maintenance_design(d, out, lid):
    lane = d.lane(lid)
    iid = lane["idea"]
    parent = lane["parents"][0]
    meta = {
        "idea": iid, "lane": lid, "title": f"maintenance {iid}",
        "experiment_purpose": "maintenance", "level": 0,
        "parents": [parent],
        "maintenance": {
            "defect": long(65, "the checkpoint loader resolves a stale relative path so later nodes read the wrong weights head"),
            "defect_evidence": [f".evo/nodes/{parent}/NODE_RESULT.md"],
            "change_boundary": {"files_in_scope": ["wiring.py", "train.py"],
                                "semantic_intent": "preserve"},
            "expected_unblock": long(45, "descendants inherit a loader that reads the exact declared artifact"),
            "parity_contract": {"cells": "all_decision", "standard": "noninferior"},
        },
    }
    wj(d.repo, out["outputs"][1], meta)
    wt(d.repo, out["outputs"][0], md(
        ("Defect", long(65, "the loader silently resolves a stale relative path against the wrong workarea root")),
        ("Evidence", long(65, "the parent result and journal entries show reads from the superseded artifact location")),
        ("Change boundary", long(65, "only the wiring shim and the train entry point change; semantics preserved")),
        ("Parity argument", long(65, "identical inputs and identical outputs on every decision cell prove preservation")),
        ("Unblock rationale", long(65, "future exploit lanes need the repaired loader before their kernels can express")),
        ("Risks", long(65, "a path fix could mask an environment difference; parity settlement guards it")),
    ))


def w_maintenance_review(d, out, lid, *, verdict="ACCEPT"):
    lane = d.lane(lid)
    iid = lane["idea"]
    design = (d.repo / f".evo/ideas/{iid}.md").read_text(encoding="utf-8")
    q1 = "the loader silently resolves a stale relative path"
    q2 = "only the wiring shim and the train entry point change"
    ok(q1 in design and q2 in design, "maintenance review quotes exist in the design")
    body = [
        f"VERDICT: {verdict}",
        "",
        "## Novelty smuggling audit",
        long(65, "the change touches path resolution only and no train or infer computation is altered"),
        f"QUOTE: {q1}",
        "## Parity risk audit",
        long(65, "silent numeric drift is the risk and the all decision noninferior settlement watches it"),
        f"QUOTE: {q2}",
        "## Cheaper alternative audit",
        long(65, "no config knob controls the resolution root and a revert would keep the defect"),
        "## Boundary audit",
        long(65, "both named files are necessary and no other file participates in path resolution"),
        "## Verdict rationale",
        long(65, "a real defect with a preserving fix and a parity contract that can catch its risk"),
    ]
    if verdict == "ACCEPT":
        body += ["## Strongest surviving risk",
                 long(65, "an environment level override could reintroduce the stale root outside the audited files")]
    wt(d.repo, out["outputs"][0], "\n".join(body) + "\n")


def run_instrumental(d):
    """v10.2: mid-round instrumental intake - a user probe and a maintenance
    repair ride the idea-gate-node rail without novelty gates, firewalls on."""
    section("R018b: mid-round diagnostic probe + parity-contracted maintenance")
    evo_py = str(PKG / "engine" / "evo.py")

    # --- diagnostic probe: evo probe -> design -> manual gate -> eval-only node
    proc = subprocess.run([PY, evo_py, "--repo", str(d.repo), "probe",
                           "--parent", "N024", "--question",
                           "does the observed auc gain survive on the frozen validation split alone"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(proc.returncode == 0, f"evo probe opens a mid-round lane: {proc.stdout[-200:]} {proc.stderr[-200:]}")
    probe_lane = d.state()["lanes"][-1]
    ok(probe_lane["experiment_purpose"] == "diagnostic_probe"
       and probe_lane["status"] == "probe_design",
       f"probe lane created mid-round: {probe_lane['id']} {probe_lane['status']}")

    # --- v11.1 P6: in-rounds tamper E2E. The scoped sweep's fail-closed deal,
    # asserted mid-round for the first time: what the imminent decision
    # CONSUMES is always verified; what it does not consume waits for the
    # cadence tripwire - and the tripwire actually fires.
    def _arm_scoped_tick():
        # A fresh marker guarantees the next tick is SCOPED (count 1 < K,
        # recent last_full_at) - without this the assertion would flap on
        # whatever the cadence counter happened to be.
        wj(d.repo, ".evo/cache/sweep_cadence.json",
           {"count": 0, "last_full_at": eutil.utc_now()})

    spec_rel = ".evo/nodes/N024/NODE_SPEC.json"
    spec_original = (d.repo / spec_rel).read_text(encoding="utf-8")
    spec_tampered = json.loads(spec_original)
    spec_tampered["in_rounds_tamper"] = True
    wj(d.repo, spec_rel, spec_tampered)
    _arm_scoped_tick()
    try:
        d.eng().compute_next()
        in_scope_rejected = False
    except SystemExit as exc:
        in_scope_rejected = "SEALED_ARTIFACT_MUTATED" in str(exc) and "N024" in str(exc) \
            and "NODE_SPEC.json" in str(exc)
    wt(d.repo, spec_rel, spec_original)
    ok(in_scope_rejected,
       "mid-round tamper of an IN-SCOPE sealed spec (current lane's parent) fails "
       "even the scoped next closed")

    # Out-of-scope subject: mirror esched._next_sweep_scope's node set and pick
    # a concluded node OUTSIDE it (the only pruned node, N009, was revived in
    # R011 - old dominated variants are the durable out-of-scope population).
    # If the engine's scope ever widens past this mirror, the "scoped tick
    # passes" assertion below fails loudly and the mirror must be updated.
    st_now, g_now, cfg_now = d.state(), d.graph(), d.store().load_config()
    rid_now = str(st_now.get("current_round") or "")
    idx_now = {str(n["id"]): n for n in g_now["nodes"]}
    scoped_nodes: set[str] = set()
    for n in g_now["nodes"]:
        if n.get("round") == rid_now or n.get("role") in ("baseline", "platform") \
                or n.get("status") in ("executing", "evaluating", "evaluated"):
            scoped_nodes.add(str(n["id"]))
    for l in st_now.get("lanes", []):
        if l.get("round") == rid_now:
            scoped_nodes.update(str(p) for p in (l.get("parents") or []))
    for n in egraph.frontier(g_now, cfg_now, st_now) + egraph.performance_frontier(g_now, cfg_now, st_now):
        scoped_nodes.add(str(n["id"]))
    for case in st_now.get("recoveries", []):
        sc_obj = case.get("scope") or {}
        if sc_obj.get("kind") == "node":
            scoped_nodes.add(str(sc_obj.get("id")))
    for gate_row in st_now.get("gates", []):
        if gate_row.get("status") == "open" and (gate_row.get("subject") or {}).get("node"):
            scoped_nodes.add(str((gate_row.get("subject") or {}).get("node")))
    for nid_s in list(scoped_nodes):
        row = idx_now.get(nid_s) or {}
        scoped_nodes.update(str(p) for p in (row.get("parents") or []))
        for f in ("code_parent", "effect_comparator_node"):
            if row.get(f):
                scoped_nodes.add(str(row.get(f)))
    out_pool = [n for n in g_now["nodes"]
                if str(n["id"]) not in scoped_nodes and n.get("status") == "concluded"
                and (d.repo / f".evo/nodes/{n['id']}/NODE_SPEC.json").is_file()]
    ok(bool(out_pool),
       "a concluded off-scope node with a sealed spec exists for the out-of-scope leg")
    out_rel = f".evo/nodes/{out_pool[0]['id']}/NODE_SPEC.json"
    out_original = (d.repo / out_rel).read_text(encoding="utf-8")
    out_tampered = json.loads(out_original)
    out_tampered["in_rounds_tamper"] = True
    wj(d.repo, out_rel, out_tampered)
    _arm_scoped_tick()
    try:
        scoped_passed = isinstance(d.eng().compute_next(), dict)
    except SystemExit:
        scoped_passed = False
    ok(scoped_passed,
       "an out-of-scope retired artifact does not block the scoped tick (that is the deal)")
    force_full_sweep(d)
    try:
        d.eng().compute_next()
        full_rejected = False
    except SystemExit as exc:
        full_rejected = "SEALED_ARTIFACT_MUTATED" in str(exc) \
            and str(out_pool[0]["id"]) in str(exc) and "NODE_SPEC.json" in str(exc)
    wt(d.repo, out_rel, out_original)
    ok(full_rejected,
       "the cadence full sweep catches the same tamper - the tripwire is real, "
       "not a permanently-scoped blind spot")
    force_full_sweep(d)   # leave the next tick full so the restore is re-audited too

    # v11.1 T3: the engine-written winner file exists for every accepted winner
    # and binds the lane's frozen identity (doctor cross-checks the same).
    won = [l for l in st_now.get("lanes", []) if l.get("winner_sketch")]
    ok(bool(won), "at least one lane accepted a tournament winner by R018")
    wl = won[-1]
    wdata = json.loads((d.repo / f".evo/rounds/{wl['round']}/lanes/{wl['id']}/WINNER.json")
                       .read_text(encoding="utf-8"))
    ok(wdata.get("sketch_id") == wl.get("winner_sketch")
       and wdata.get("winner_program_digest") == wl.get("winner_program_digest")
       and isinstance(wdata.get("sketch"), dict) and wdata.get("sketch"),
       f"WINNER.json carries the frozen winner identity + full sketch payload: "
       f"{wdata.get('sketch_id')}/{str(wdata.get('winner_program_digest'))[:12]}")
    # v11.1 T4: breadth tasks are exempt from ledger slices - deep_read always
    # reads the FULL pools, never a .evo/slices/ path.
    dr_tasks = [t for t in st_now.get("tasks", []) if t.get("type") == "deep_read"]
    ok(bool(dr_tasks), "deep_read tasks exist in the flow by R018")
    # Done tasks drop their _render payload (v11 slimming), so the durable
    # evidence is the bundle file itself.
    dr_bundles = [(d.repo / f".evo/tasks/{t['id']}/BUNDLE.md").read_text(encoding="utf-8")
                  for t in dr_tasks
                  if (d.repo / f".evo/tasks/{t['id']}/BUNDLE.md").is_file()]
    ok(bool(dr_bundles)
       and all(".evo/evidence/MECH_CARDS.jsonl" in b for b in dr_bundles)
       and not any(".evo/slices/" in b for b in dr_bundles),
       f"deep_read (breadth duty) keeps the FULL pools and never a slice path "
       f"({len(dr_bundles)} bundles checked)")
    proc = subprocess.run([PY, evo_py, "--repo", str(d.repo), "probe",
                           "--parent", "N024", "--question",
                           "a second question in the same round must hit the per round cap"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    # While the first probe is still pre-gate the door names the precise reason
    # (one undecided instrumental lane at a time) on top of the spend cap.
    ok(proc.returncode != 0 and "INJECT_PENDING" in (proc.stdout + proc.stderr),
       f"a second probe while one is undecided is refused: {proc.stdout[-150:]}{proc.stderr[-150:]}")
    ctx_now = esched.Engine(d.store()).ctx()

    def probe_errs_with(status, *, gates=None, cap=None):
        """injected_lane_errors for a second probe, with round R018's existing
        probe lane(s) forced into `status` (and optionally a synthetic gate or
        budget cap)."""
        state = d.state()
        rewritten = [dict(l, status=status) if (l.get("experiment_purpose") == "diagnostic_probe"
                                                and l.get("round") == "R018") else l
                     for l in state["lanes"]]
        cfg = ctx_now.cfg
        if cap is not None:
            cfg = {**cfg, "budgets": {**cfg.get("budgets", {}), "probes_max_per_round": cap}}
        return evalid.injected_lane_errors(
            evalid.Ctx(ctx_now.store,
                       {**state, "lanes": rewritten,
                        "gates": list(state.get("gates") or []) + list(gates or [])},
                       cfg, ctx_now.g, ctx_now.reg),
            {"name": "probe-two", "experiment_purpose": "diagnostic_probe", "intent": "exploit",
             "search_origin": "repair", "min_level": 0, "parents": ["N024"]}, "R018")

    committed_errs = probe_errs_with("node_created")
    ok(any(e.startswith("INJECT_CAP") for e in committed_errs)
       and not any(e.startswith("INJECT_PENDING") for e in committed_errs),
       f"a probe already committed to compute consumes the round's cap: {committed_errs}")
    # The cap counts lanes OPENED, not lanes that survived: refunding the slot
    # on abandonment let reject -> reopen -> reject cycles run forever, each lap
    # costing the user another manual gate decision.
    abandoned_errs = probe_errs_with("abandoned")
    ok(any(e.startswith("INJECT_CAP") for e in abandoned_errs),
       f"an abandoned probe still consumes the round's cap (no reject/reopen churn): {abandoned_errs}")
    ok(not any(e.startswith("INJECT_PENDING") for e in abandoned_errs),
       f"an abandoned lane is not an undecided one: {abandoned_errs}")
    # The refusal advertises the slot-free rewind ONLY when a lane it could act
    # on exists.  This lane never reached a user gate, so naming one would send
    # the user hunting for a gate id that was never minted.
    ok(not any("--gate" in e for e in abandoned_errs),
       f"with no user gate ever opened the refusal must not name one: {abandoned_errs}")
    probe_lane_id = probe_lane["id"]
    # The hint is only correct while the gate is still OPEN: `evo decide` refuses
    # a decided gate, so pointing at an approved/rejected one would name a
    # command that can only raise.
    gated_errs = probe_errs_with(
        "gate",
        gates=[{"id": "G900", "kind": "idea_approval", "status": "open",
                "subject": {"lane": probe_lane_id}}])
    ok(any("retry-stage probe_design" in e for e in gated_errs),
       f"an OPEN user gate must be offered as the slot-free rewind: {gated_errs}")
    decided_errs = probe_errs_with(
        "abandoned",
        gates=[{"id": "G900", "kind": "idea_approval", "status": "rejected",
                "subject": {"lane": probe_lane_id}}])
    ok(not any("--gate" in e for e in decided_errs),
       f"an already-decided gate must not be advertised as rewindable: {decided_errs}")
    # The documented off-switch must not claim a budget was spent.
    off_errs = probe_errs_with("abandoned", cap=0)
    ok(any(e.startswith("INJECT_DISABLED") for e in off_errs)
       and not any(e.startswith("INJECT_CAP") for e in off_errs),
       f"cap 0 must read as a disabled door, not as an exhausted budget: {off_errs}")
    # R1 hardening: the lane name is a path component of the engine-written
    # brief, so traversal and duplicates are refused at the door.
    proc = subprocess.run([PY, evo_py, "--repo", str(d.repo), "maintain",
                           "--parent", "N024", "--name", "../../../../escape",
                           "--defect", "a traversing name must never reach the filesystem"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(proc.returncode != 0 and "INJECT_NAME" in (proc.stdout + proc.stderr),
       f"path-traversing lane name refused: {proc.stdout[-150:]}{proc.stderr[-150:]}")
    ok(not (d.repo / "escape").exists() and not (d.repo.parent / "escape").exists(),
       "no lane brief was written outside .evo")
    proc = subprocess.run([PY, evo_py, "--repo", str(d.repo), "maintain",
                           "--parent", "N024", "--name", probe_lane["name"],
                           "--defect", "a duplicate lane name would share the brief path"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(proc.returncode != 0 and "INJECT_NAME_DUP" in (proc.stdout + proc.stderr),
       f"duplicate lane name refused: {proc.stdout[-150:]}{proc.stderr[-150:]}")
    lid_p = probe_lane["id"]
    out = nx(d, "probe_design")
    w_probe_design(d, out, lid_p, bad="leak")
    sub_rej(d, out, "PROBE_NOVELTY_FIELDS")
    w_probe_design(d, out, lid_p)
    sub_ok(d, out)
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "idea_approval",
       f"probe gate is manual even in full_auto: {gate}")
    d.decide(gate["gate"], approve=True)
    out = nx(d, "plan_node")
    w_plan(d, out, lid_p, role="variant", workdir="workareas/nprobe", code_parent="N024",
           stages=None, cost="light", experiment_class="inference",
           eval_extra={"budget": {"limits": {"wallclock_minutes": 999}}})
    sub_rej(d, out, "SPEC_PROBE_BUDGET_EXCEEDED")
    w_plan(d, out, lid_p, role="variant", workdir="workareas/nprobe", code_parent="N024",
           stages=None, cost="light", experiment_class="inference",
           eval_extra={"budget": {"limits": {"wallclock_minutes": 30}}})
    sub_ok(d, out)
    n_probe = d.lane(lid_p)["node"]
    out = nx(d, "implement")
    do_implement(d, out, n_probe)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n_probe)["status"] == "pass", "probe smoke")
    sub_ok(d, out)
    maybe_fidelity(d, n_probe)
    # (blind-operator audit fix) an evaluation-only instrumental node now gets
    # the promised manual workflow gate too - its compute is the eval run.
    out = nx(d, None, "gate")
    ok(out.get("gate_kind") == "workflow_approval", f"expected workflow gate, got {out}")
    d.decide(out["gate"], True, note="mock user approves the probe's evaluation spend")
    out = nx(d, "eval_launch")
    w_launch_eval(d, out, job="probe-eval")
    sub_ok(d, out)
    run_p = d.state()["runs"][-1]["id"]
    # raw values mirror w_eval's synthetic coupling (logloss = 0.6 - (auc-0.7))
    # exactly: the analyst normalization is a verbatim copy of the sealed RUN.
    raw = {"auc": 0.772, "logloss": 0.528, "latency_ms": 100.0,
           "_usage": {"wallclock_minutes": 1.0}}
    wt(d.repo, "workareas/nprobe/agent_eval_raw.json", json.dumps(raw))
    d.run_update(run_p, "finished", metrics_file="workareas/nprobe/agent_eval_raw.json")
    out = nx(d, "evaluate")
    w_eval(d, out, n_probe, 0.772)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, n_probe)
    sub_rej(d, out, "OUTCOME_OBSERVATIONS_REQUIRED")
    w_conclude(d, out, n_probe, observations=[{
        "statement": long(35, "the auc gain persists on the frozen split without the training pipeline"),
        "where": "frozen validation split, parent checkpoint",
        "measurement": "auc 0.772 on one evaluator pass",
        "evidence": f".evo/nodes/{n_probe}/eval/metrics.json"}])
    sub_ok(d, out)
    node_p = d.node(n_probe)
    ok(node_p["experiment_purpose"] == "diagnostic_probe" and node_p["status"] == "concluded",
       f"probe node concluded: {node_p['id']}")
    fr_ids = {n["id"] for n in egraph.frontier(d.graph(), project_cfg(d))}
    perf_ids = {n["id"] for n in egraph.performance_frontier(d.graph(), project_cfg(d))}
    ok(n_probe not in fr_ids and n_probe not in perf_ids,
       "a probe never enters any frontier")
    ctx = evalid.Ctx(d.store(), d.state(), project_cfg(d), d.graph())
    errs = evalid.injected_lane_errors(ctx, {
        "experiment_purpose": "maintenance", "intent": "exploit", "search_origin": "repair",
        "min_level": 0, "parents": [n_probe]}, d.state()["current_round"])
    ok(any(e.startswith("INJECT_PARENT_PROBE") for e in errs),
       f"a probe can never be a parent: {errs}")

    # --- maintenance: evo maintain -> design -> adversarial review -> gate -> parity
    proc = subprocess.run([PY, evo_py, "--repo", str(d.repo), "maintain",
                           "--parent", "N024", "--defect",
                           "the checkpoint loader resolves a stale relative path against the wrong root"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(proc.returncode == 0, f"evo maintain opens a mid-round lane: {proc.stdout[-200:]} {proc.stderr[-200:]}")
    lid_m = d.state()["lanes"][-1]["id"]
    out = nx(d, "maintenance_design")
    w_maintenance_design(d, out, lid_m)
    sub_ok(d, out)
    out = nx(d, "maintenance_review")
    w_maintenance_review(d, out, lid_m, verdict="ACCEPT")
    sub_ok(d, out)
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "idea_approval", "maintenance gate is manual even in full_auto")
    d.decide(gate["gate"], approve=True)
    out = nx(d, "plan_node")
    w_plan(d, out, lid_m, role="variant", workdir="workareas/nmaint", code_parent="N024",
           stages=[stage("train", uri="oss://bkt/user/maint-train/checkpoint.zip", key="train|maint")],
           cost="light")
    sub_ok(d, out)
    n_maint = d.lane(lid_m)["node"]
    # v10.2 R2: a maintenance node inherits its parent's tree and may touch
    # ONLY the files its reviewed change_boundary declared; the engine now
    # diffs the execution closure against the parent's sealed manifest, so an
    # out-of-scope edit is MAINT_BOUNDARY_VIOLATION.  First prove the check
    # bites, then implement the repair honestly.
    out = nx(d, "implement")
    do_implement(d, out, n_maint)          # generic scaffolding = out of scope
    sub_rej(d, out, "MAINT_BOUNDARY_VIOLATION")
    do_maintenance_implement(d, out, n_maint)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n_maint)["status"] == "pass", f"{n_maint} smoke")
    sub_ok(d, out)
    maybe_fidelity(d, n_maint)
    # Instrumental compute is never released without the user. eflow.GATE_POLICY
    # lists all three instrumental purposes as manual for workflow_approval, and
    # _needs_workflow_gate now actually CREATES that gate for each of them - it
    # used to hard-return True for targeted_ablation alone, so under full_auto a
    # repair's workflow launched unattended and the policy entry protected
    # nothing.  This drive runs full_auto, so the gate must appear here.
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "workflow_approval",
       f"full_auto must still pause before spending a repair's workflow: {gate}")
    d.decide(gate["gate"], True, "user approves the repair workflow")
    out = nx(d, "stage_launch")
    stg0 = d.state()["tasks"][-1]["subject"]["stage"]
    w_launch(d, out, stg0, job="job-maint")
    sub_ok(d, out)
    run_m = last_run(d)["id"]
    # infrastructure failure -> repeat-spend gate -> relaunch -> the fix
    # knowledge must be dispositioned at conclude
    d.run_update(run_m, "failed", note="scheduler rejected the submit: stale queue token",
                 failure_class="infrastructure")
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "repeat_spend", f"replacement attempt needs the protected gate: {gate}")
    d.decide(gate["gate"], approve=True)
    out = nx(d, "stage_launch")
    stg_name = d.state()["tasks"][-1]["subject"]["stage"]
    w_launch(d, out, stg_name, job="job-maint-2")
    sub_ok(d, out)
    run_m2 = last_run(d)["id"]
    drive_watch_finish(d, run_m2, n_maint, "train")
    out = nx(d, "eval_launch")
    w_launch_eval(d, out, job="maint-eval")
    sub_ok(d, out)
    run_me = d.state()["runs"][-1]["id"]
    raw = {"auc": 0.772, "logloss": 0.528, "latency_ms": 100.0,
           "_usage": {"wallclock_minutes": 1.0}}
    wt(d.repo, "workareas/nmaint/agent_eval_raw.json", json.dumps(raw))
    d.run_update(run_me, "finished", metrics_file="workareas/nmaint/agent_eval_raw.json")
    out = nx(d, "evaluate")
    w_eval(d, out, n_maint, 0.772)
    sub_ok(d, out)
    er_ids = [r["id"] for r in d.store().error_records()
              if r.get("node") == n_maint and r.get("failure_class") == "infrastructure"]
    ok(len(er_ids) == 1, f"the infra failure landed in the journal: {er_ids}")
    out = nx(d, "conclude")
    w_conclude(d, out, n_maint)
    sub_rej(d, out, "OUTCOME_INFRA_RESOLUTION_REQUIRED")
    # R1 hardening: 'transient' is not a free escape - it must name the later
    # RUN of this node that succeeded under the SAME implementation revision.
    w_conclude(d, out, n_maint, infra_resolutions=[{
        "error": er_ids[0], "disposition": "transient"}])
    sub_rej(d, out, "OUTCOME_INFRA_TRANSIENT_PROOF")
    # shape check asserted directly (a third rejected submit would exhaust the
    # attempt budget and stick the task): a fixed row may not carry the
    # transient-only proof field.
    _shape_errs = []
    evalid.infra_resolution_errors(
        evalid.Ctx(d.store(), d.state(), project_cfg(d), d.graph()), d.node(n_maint),
        {"infra_resolutions": [{"error": er_ids[0], "disposition": "fixed", "surface": "launch",
                                "recovered_run": run_m2,
                                "fix": long(35, "refresh the queue token via hub-cli auth first")}]},
        _shape_errs)
    ok(any(e.startswith("OUTCOME_INFRA_RESOLUTION_SHAPE") for e in _shape_errs),
       f"a fixed disposition may not carry the transient proof field: {_shape_errs}")
    w_conclude(d, out, n_maint, infra_resolutions=[{
        "error": er_ids[0], "disposition": "fixed", "surface": "launch",
        "fix": long(35, "refresh the queue token via hub-cli auth before submit and retry the same command")}])
    sub_ok(d, out)
    node_m = d.node(n_maint)
    ok(node_m["maintenance_parity"] == "met",
       f"maintenance parity settled met at identical scores: {node_m.get('maintenance_parity')}")
    ok(node_m["scientific_promotion_status"] == "not_applicable",
       "maintenance never earns scientific promotion")
    idx = egraph.by_id(d.graph())
    ok(egraph.effective_frontier_ancestor(idx, n_maint) == "N024",
       "maintenance is frontier-transparent to its parent")
    # R1: transparency is BIDIRECTIONAL - a repair (even one that measures
    # better) never competes as a frontier tip, so it cannot evict the very
    # parent whose lineage it repaired and deadlock later exploits.
    cfg_now = project_cfg(d)
    fr_after = {n["id"] for n in egraph.frontier(d.graph(), cfg_now)}
    perf_after = {n["id"] for n in egraph.performance_frontier(d.graph(), cfg_now)}
    ok(n_maint not in fr_after and n_maint not in perf_after,
       f"maintenance stays off both frontiers: fr={sorted(fr_after)} perf={sorted(perf_after)}")
    ok("N024" in fr_after, "the repaired parent keeps its frontier standing")
    ok(egraph.instrumental_frontier_excluded(d.node(n_maint), cfg_now)
       and egraph.instrumental_frontier_excluded(d.node(n_probe), cfg_now),
       "both instrumental purposes are frontier-excluded by one predicate")
    resolutions = d.store().error_resolutions()
    ok(any(r.get("resolves") == er_ids[0] and r.get("disposition") == "fixed" for r in resolutions),
       f"the fix disposition landed in the journal: {resolutions}")
    playbook = ebundle.playbook_block(d.store(), project_cfg(d))
    ok(any("launch" in line and "queue token" in line for line in playbook),
       f"the platform playbook now carries the working fix: {playbook}")
    ctx = evalid.Ctx(d.store(), d.state(), project_cfg(d), d.graph())
    errs = evalid.injected_lane_errors(ctx, {
        "experiment_purpose": "diagnostic_probe", "intent": "exploit", "search_origin": "repair",
        "min_level": 0, "parents": [n_maint]}, "R999")
    ok(not any(e.startswith("INJECT_PARENT") for e in errs),
       f"a parity-met maintenance node is a legal parent: {errs}")


def drive_close(d, rid, *, retire=None):
    out = nx(d, "close_round")
    w_retro(d, out, rid, retire=retire)
    sub_ok(d, out)


def open_round(d, rid, lanes_def):
    out = nx(d, "open_round")
    ok(out["outputs"][0].endswith(f"{rid}/PORTFOLIO.json"), f"round id mismatch: {out}")
    w_portfolio(d, out, rid, lanes_def)
    sub_ok(d, out)
    return out


def evidence_refresh(d):
    out = nx(d, "evidence")
    w_evidence_refresh(d)
    sub_ok(d, out)


def exploit_lane(name, parent, min_level=2, focus=None):
    ln = {"name": name, "intent": "exploit", "min_level": min_level, "parents": [parent]}
    if focus:
        ln["focus"] = focus
    return ln


PROGRAM_VARIANTS = ["operator_topology", "learned_objects", "effect_chain"]
L2_DIMS = L3_DIMS = L3_DIMS_NB = L4_DIMS = L4_DIMS_NB = PROGRAM_VARIANTS


def drive_std_exploit_round(d, rid, name, parent, score, *, lessons=None,
                            neg_root_cause=False, close=True, retire=None):
    """One-lane exploit round: full pipeline, single-stage bg training."""
    open_round(d, rid, [exploit_lane(name, parent)])
    evidence_refresh(d)
    lid, mech = drive_lane_to_plan(d, name, dims=L2_DIMS)
    drive_mature_redteam(d, lid, mech_ids=mech, score=score)
    nid = drive_plan(d, lid, role="variant", code_parent=parent, stages=[
        stage("train", uri=f"oss://bkt/user/{name}-train/checkpoint.zip", key=f"train|{name}")])
    run_id = drive_node_to_training(d, nid)
    drive_watch_finish(d, run_id, nid, "train")
    drive_eval_conclude(d, nid, score, lessons=lessons, neg_root_cause=neg_root_cause)
    if close:
        drive_close(d, rid, retire=retire)
    return nid


# --------------------------------------------------------------------------- main run: bootstrap + R1
MAIN_FOCUS = [{"id": "D1", "text": "explore reinforcement learning style objectives on this ranking task"}]


def w_config_main(d, out, **kw):
    kw.setdefault("autonomy", "full_auto")
    kw.setdefault("rounds_max", 18)
    kw.setdefault("vcs", "git")
    kw.setdefault("mode", "research")
    kw.setdefault("rehearsal", "none")
    kw.setdefault("sota", True)
    kw.setdefault("sota_refresh", 7)
    kw.setdefault("scaling_probe", True)   # v9: L4 ideas pre-register a cross-scale trend
    kw.setdefault("focus", MAIN_FOCUS)
    kw.setdefault("focus_neglect", 4)
    w_config(d, out, **kw)


def run_bootstrap(d):
    section("bootstrap (full_auto, git, research mode + sota + focus + drills)")
    out = nx(d, "project_scan")
    w_project_scan(d, out, fit={"assumptions": [], "overall": "fit"})
    sub_rej(d, out, "DISCOVERY_FIT_COVERAGE")
    w_project_scan(d, out)
    sub_ok(d, out)
    out = nx(d, "configure")
    w_config_main(d, out, bad_docs=True, mode="", rehearsal="")
    sub_rej(d, out, "CONFIG_DOCS_UNRESOLVED", "CONFIG_MODE", "CONFIG_REHEARSAL")
    # preset honesty: a named preset with divergent tempo values in the file lies
    w_config_main(d, out, preset="balanced")
    sub_rej(d, out, "CONFIG_PRESET_CONFLICT")
    # unknown preset name (validator-level; the task has one submit attempt left)
    bad = d.store().load_config()
    bad["policy"]["preset"] = "extreme"
    ok(any(e.startswith("CONFIG_PRESET") for e in econfig.validate_config(bad)),
       "unknown preset name rejected by validate_config")
    bad_focus = d.store().load_config()
    bad_focus["project"]["focus_directions"] = [{"id": "X1", "text": "short"}]
    ok(any(e.startswith("CONFIG_FOCUS") for e in econfig.validate_config(bad_focus)),
       "malformed focus direction rejected by validate_config")
    bad_floor = d.store().load_config()
    bad_floor["budgets"]["evidence_min_recent_ratio"] = 0.2
    ok(any(e.startswith("CONFIG_RESEARCH_FLOOR_RECENCY") for e in econfig.validate_config(bad_floor)),
       "research mode enforces the frontier-reading floor (recency ratio)")
    bad_l4 = d.store().load_config()
    bad_l4["policy"]["stagnation_moonshot_rounds"] = 0
    ok(any(e.startswith("CONFIG_RESEARCH_FLOOR_L4") for e in econfig.validate_config(bad_l4)),
       "research mode refuses configs with moonshot forcing disabled (steady preset is engineering-only)")
    # a named preset with the tempo keys DELETED is legal - the engine fills them
    w_config_main(d, out, preset="frontier", drop_tempo=True)
    eff = d.store().load_config()["policy"]
    ok(eff["wildcat_every_rounds"] == 1 and eff["max_exploit_share"] == 0.25
       and eff["stagnation_moonshot_rounds"] == 2
       and "stagnation_epsilon_pct" not in eff
       and eff["research_min_structural_scope_share"] == 0.67
       and eff["research_min_constructive_share"] == 0.67
       and eff["research_min_core_synthesis_share"] == 0.25,
       f"preset 'frontier' expands into the tempo keys at load: {eff}")
    ok("preset=frontier" in econfig.describe_policy(d.store().load_config())
       and "every 1 rounds" in econfig.describe_policy(d.store().load_config()),
       "describe_policy renders the tempo line")
    w_config_main(d, out)
    sub_ok(d, out)
    ok((d.repo / ".evo/ONBOARDING.md").exists(), "init wrote the onboarding checklist")

    out = nx(d, "infra")
    card = (d.repo / out["card"]).read_text(encoding="utf-8")
    ok("Stop discipline" in card, "cards carry the continuity footer")
    w_infra(d, out, bad="uri_tpl")
    sub_rej(d, out, "INFRA_URI_TEMPLATE")
    w_infra(d, out, bad="no_src")
    sub_rej(d, out, "INFRA_SRC_MISSING", "INFRA_EVAL_CONTRACT")
    w_infra(d, out, llm=True)
    sub_ok(d, out)

    out = nx(d, "infra_interview")
    w_interview(d, out, bad="no_pm")
    sub_rej(d, out, "INTERVIEW_RESULT_KEYS", "INTERVIEW_DISPLAY_RESULT")
    w_interview(d, out, bad="svc_prose")
    sub_rej(d, out, "INTERVIEW_SERVICES")
    w_interview(d, out, llm=True)
    sub_ok(d, out)

    # Bootstrap success/resource rules are never self-approved, even in full_auto.
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "infra_confirm", f"mandatory bootstrap gate presented: {gate}")
    gates = [g for g in d.state()["gates"] if g["kind"] == "infra_confirm"]
    ok(len(gates) == 1 and gates[0]["status"] == "open", f"infra gate cannot auto-approve: {gates}")

    # Both the configuration and resource manifest shown by the review must be
    # the exact snapshots approved at the gate.
    reviewed_facts_path = d.repo / ".evo/profile/INFRA_FACTS.json"
    reviewed_facts_text = reviewed_facts_path.read_text(encoding="utf-8")
    stale_facts = json.loads(reviewed_facts_text)
    stale_facts["review_time_substitution"] = "still schema-valid but not the reviewed manifest"
    wj(d.repo, ".evo/profile/INFRA_FACTS.json", stale_facts)
    try:
        d.decide(gate["gate"], True, "attempt to approve stale infrastructure facts")
        stale_facts_blocked = False
    except SystemExit as exc:
        stale_facts_blocked = "INFRA_FACTS changed after the infrastructure task" in str(exc)
    ok(stale_facts_blocked and next(
        g for g in d.state()["gates"] if g["id"] == gate["gate"])["status"] == "open",
       "bootstrap approval rejects a valid INFRA_FACTS substitution made after review")
    wt(d.repo, ".evo/profile/INFRA_FACTS.json", reviewed_facts_text)

    # A valid config edit between review and approval cannot be smuggled
    # through the old report either.
    config_path = d.repo / ".evo/config.json"
    signed = eutil.read_json(config_path)
    changed = json.loads(json.dumps(signed))
    changed["resource_contract"]["limits"]["gpu_hours"] += 1
    eutil.write_json_atomic(config_path, changed)
    try:
        d.decide(gate["gate"], True, "attempt to approve a stale review")
        stale_blocked = False
    except SystemExit as exc:
        stale_blocked = "changed after INFRA_REVIEW" in str(exc)
    ok(stale_blocked and next(g for g in d.state()["gates"] if g["id"] == gate["gate"])["status"] == "open",
       "bootstrap approval rejects success/resource edits made after the review snapshot")
    eutil.write_json_atomic(config_path, signed)
    d.decide(gate["gate"], True, "success contract, infrastructure and cumulative resource limits confirmed")
    approved_state = d.state()
    ok(approved_state["bootstrap_contract_confirmed"] and approved_state["config_frozen"]
       and approved_state.get("bootstrap_contract_digest"),
       "manual approval freezes and digest-locks the bootstrap contract")

    changed = json.loads(json.dumps(signed))
    changed["evaluation_contract"]["decision"]["min_target_groups_improved"] += 1
    eutil.write_json_atomic(config_path, changed)
    try:
        d.eng().compute_next()
        mutation_blocked = False
    except SystemExit as exc:
        mutation_blocked = "changed after bootstrap approval" in str(exc)
    ok(mutation_blocked, "scheduler refuses post-approval success-contract mutation")
    eutil.write_json_atomic(config_path, signed)
    out = nx(d, "infra_drill")
    w_drills(d, out, bad="no_evidence")
    sub_rej(d, out, "CANARY_PLAN_SCHEMA", "CANARY_PLAN_MISSING", "CANARY_RUN_MISSING")
    w_drills(d, out, bad="cover")
    sub_rej(d, out, "CANARY_RUN_MISSING")

    # The runner binds the exact user-approved contract and infrastructure
    # manifest. Temporarily weakening either one cannot produce a receipt that
    # is later smuggled back under the approved files.
    approved_cfg_text = (d.repo / ".evo/config.json").read_text(encoding="utf-8")
    weakened_cfg = json.loads(approved_cfg_text)
    weakened_cfg["evaluation_contract"]["cells"] = []
    wj(d.repo, ".evo/config.json", weakened_cfg)
    try:
        ecanary.run(d.store(), out["task"])
        contract_run_blocked = False
    except SystemExit as exc:
        contract_run_blocked = "contract changed after bootstrap approval" in str(exc)
    wt(d.repo, ".evo/config.json", approved_cfg_text)
    ok(contract_run_blocked, "canary refuses a temporarily weakened post-approval evaluation contract")

    facts_path = d.repo / ".evo/profile/INFRA_FACTS.json"
    approved_facts_text = facts_path.read_text(encoding="utf-8")
    weakened_facts = json.loads(approved_facts_text)
    weakened_facts.pop("llm")
    wj(d.repo, ".evo/profile/INFRA_FACTS.json", weakened_facts)
    try:
        ecanary.run(d.store(), out["task"])
        facts_run_blocked = False
    except SystemExit as exc:
        facts_run_blocked = "INFRA_FACTS changed after bootstrap approval" in str(exc)
    wt(d.repo, ".evo/profile/INFRA_FACTS.json", approved_facts_text)
    ok(facts_run_blocked, "canary refuses a temporarily reduced post-approval resource manifest")

    # A long remote canary keeps an OS-level task lock and merges its result
    # into freshly reloaded state instead of overwriting intervening changes.
    sync_rel = ".evo/profile/canary_concurrency_sync"
    sync_ready = d.repo / (sync_rel + ".ready")
    sync_release = d.repo / (sync_rel + ".release")
    for sync_file in (sync_ready, sync_release):
        if sync_file.exists():
            sync_file.unlink()
    _write_canary_plan(d, out, f"--sync-file={sync_rel}")
    concurrent_result = []
    concurrent_error = []
    def run_slow_canary():
        try:
            concurrent_result.append(ecanary.run(d.store(), out["task"]))
        except BaseException as exc:
            concurrent_error.append(exc)
    thread = threading.Thread(target=run_slow_canary)
    thread.start()
    deadline = time.time() + 3.0
    while time.time() < deadline and not sync_ready.exists():
        time.sleep(0.01)
    sync_ready_seen = sync_ready.exists()
    try:
        ecanary.run(d.store(), out["task"])
        duplicate_blocked = False
    except SystemExit as exc:
        duplicate_blocked = "already running" in str(exc)
    concurrent_state = d.store().load_state()
    concurrent_state["canary_concurrency_probe"] = "preserve-me"
    d.store().save_state(concurrent_state)
    sync_release.parent.mkdir(parents=True, exist_ok=True)
    sync_release.write_text("release", encoding="utf-8")
    thread.join(timeout=5.0)
    merged_state = d.store().load_state()
    ok(sync_ready_seen and duplicate_blocked and not thread.is_alive() and not concurrent_error
       and concurrent_result and concurrent_result[0]["status"] == "passed",
       "a second invocation cannot race the same long-running canary")
    ok(merged_state.get("canary_concurrency_probe") == "preserve-me"
       and (d.store().get_task(merged_state, out["task"]) or {}).get("infra_canary_run"),
       "long canary attaches its receipt without overwriting a concurrent unrelated state update")
    merged_state.pop("canary_concurrency_probe", None)
    d.store().save_state(merged_state)
    for sync_file in (sync_ready, sync_release):
        if sync_file.exists():
            sync_file.unlink()
    writer_a, writer_b = d.store(), d.store()
    state_a, state_b = writer_a.load_state(), writer_b.load_state()
    state_a["state_cas_probe"] = "first-writer"
    writer_a.save_state(state_a)
    state_b["state_cas_probe"] = "stale-second-writer"
    try:
        writer_b.save_state(state_b)
        stale_state_rejected = False
    except SystemExit as exc:
        stale_state_rejected = "state changed concurrently" in str(exc)
    cas_state = d.store().load_state()
    ok(stale_state_rejected and cas_state.get("state_cas_probe") == "first-writer",
       "state revision CAS rejects a stale writer instead of overwriting a newer engine update")
    cas_state.pop("state_cas_probe", None)
    d.store().save_state(cas_state)

    required = set(ecanary.required_surfaces(d.store(), d.store().load_config(), d.graph()))
    literal_base = {"workspace", "compute", "data", "artifact_store", "evaluation"}
    literal_datasets = {"dataset:observational", "dataset:exploration", "dataset:validation"}
    literal_eval_datasets = {"evaluation-dataset:D1", "evaluation-dataset:D2"}
    expected_required = literal_base | literal_datasets | literal_eval_datasets | {"service:llm"}
    ok(required == expected_required,
       f"request independently contains every literal base, dataset and declared-service surface: {sorted(required)}")
    complete_observation = {
        "nonce": "validator-nonce",
        "checks": [{"surface": surface, "status": "pass",
                    "detail": "independent validator fixture observed this required boundary"}
                   for surface in sorted(required)],
        "metrics": {key: 0.5 for key in econfig.result_spec(d.store().load_config())},
    }
    for missing in sorted(required):
        missing_observation = json.loads(json.dumps(complete_observation))
        missing_observation["checks"] = [row for row in missing_observation["checks"]
                                         if row["surface"] != missing]
        missing_errors = ecanary._observation_errors(
            missing_observation, nonce="validator-nonce",
            surfaces=sorted(required), cfg=d.store().load_config())
        ok(any(err.startswith("CANARY_SURFACE_MISSING") and repr(missing) in err
               for err in missing_errors),
           f"validator independently rejects omission of required surface {missing}")
    failed = w_drills(d, out, bad="omit:workspace")
    ok(failed["status"] == "failed"
       and any("'workspace'" in err for err in failed["errors"]),
       "real runner cannot pass when its observation omits a required base surface")
    weakened_request = w_drills(d, out, bad="mutate_request")
    ok(weakened_request["status"] == "failed"
       and any("CANARY_REQUEST_MUTATED_DURING_RUN" in err
               for err in weakened_request["errors"]),
       "adapter cannot rewrite the issued dataset/artifact/service request to an easier path")
    w_drills(d, out)
    sub_ok(d, out)
    active_canary = d.state().get("infra_canary") or {}
    ok(active_canary.get("status") == "passed",
       "bootstrap stores only the engine-observed passed canary record")
    rebound_errors = ecanary.record_errors(
        d.store(), {**active_canary, "task": "T9999"}, expect_task="T9999")
    ok(any(err.startswith("CANARY_RECEIPT_BINDING") for err in rebound_errors),
       "a record whose outer task id was rebound still fails its engine receipt binding")

    # All engine-observed evidence remains live-auditable after acceptance.
    receipt_path = d.repo / active_canary["receipt"]
    receipt_data = json.loads(receipt_path.read_text(encoding="utf-8"))
    tamper_cases = [
        (d.repo / active_canary["plan_path"], "CANARY_PLAN_MUTATED", True),
        (receipt_path, "CANARY_RECEIPT_MUTATED", True),
        (d.repo / receipt_data["observation"], "CANARY_OBSERVATION_MUTATED", True),
        (d.repo / receipt_data["request"], "CANARY_REQUEST_MUTATED", True),
        (d.repo / receipt_data["plan_snapshot"], "CANARY_PLAN_SNAPSHOT_MUTATED", True),
        (d.repo / receipt_data["stdout"], "CANARY_STDOUT_MUTATED", False),
        (d.repo / receipt_data["stderr"], "CANARY_STDERR_MUTATED", False),
    ]
    for path, code, is_json in tamper_cases:
        original = path.read_text(encoding="utf-8")
        if is_json:
            changed = json.loads(original)
            changed["post_run_tamper"] = True
            wj(d.repo, path.relative_to(d.repo).as_posix(), changed)
        else:
            wt(d.repo, path.relative_to(d.repo).as_posix(), original + "post-run tamper\n")
        try:
            d.eng().compute_next()
            rejected = False
        except SystemExit as exc:
            rejected = code in str(exc)
        doctor_problems, _ = edoctor.diagnose(d.store())
        doctor_rejected = any(code in problem for problem in doctor_problems)
        dashboard_canary = edash._data(
            d.store(), d.graph(), d.store().load_config(), d.state(), d.reg())["infrastructure"]["canary"]
        wt(d.repo, path.relative_to(d.repo).as_posix(), original)
        ok(rejected and doctor_rejected and not dashboard_canary["ready"]
           and dashboard_canary["status"] == "invalid"
           and code in dashboard_canary["error_codes"],
           f"scheduler, doctor and dashboard all fail closed on {code}")
    changed_facts = json.loads(approved_facts_text)
    changed_facts["post_run_tamper"] = True
    wj(d.repo, ".evo/profile/INFRA_FACTS.json", changed_facts)
    try:
        d.eng().compute_next()
        facts_rejected = False
    except SystemExit as exc:
        facts_rejected = "INFRA_FACTS changed after bootstrap approval" in str(exc)
    facts_doctor_problems, _ = edoctor.diagnose(d.store())
    facts_doctor_rejected = any("BOOTSTRAP_INFRA_FACTS_MUTATED" in problem
                                for problem in facts_doctor_problems)
    wt(d.repo, ".evo/profile/INFRA_FACTS.json", approved_facts_text)
    ok(facts_rejected and facts_doctor_rejected,
       "scheduler and doctor fail closed when the approved resource manifest changes")

    out = nx(d, "profile")
    w_profile(d, out, bad="few_tags")
    sub_rej(d, out, "PROFILE_SRC_TAGS")
    w_profile(d, out)
    sub_ok(d, out)

    ok(not (d.repo / ".evo/knowledge/MOVE_CATALOG.md").exists()
       and not (d.repo / ".evo/knowledge/CASE_CARDS.md").exists(),
       "init does not install narrative move/case catalogs into the live search context")

    out = nx(d, "dossier")
    w_dossier(d, out, bad="no_discriminator")
    sub_rej(d, out, "MD_SECTION_MISSING")
    w_dossier(d, out)
    sub_ok(d, out)

    out = nx(d, "rubric")
    w_rubric(d, out, bad="menu")
    sub_rej(d, out, "RUBRIC_IS_A_MENU")
    w_rubric(d, out, bad="no_leverage")
    sub_rej(d, out, "MD_SECTION_MISSING")
    w_rubric(d, out)
    sub_ok(d, out)

    # research mode + sota_enabled -> the SOTA library scan precedes the baseline
    out = nx(d, "sota_scan")
    w_sota(d, out, bad="venue_year")
    sub_rej(d, out, "SOTA_VENUE", "SOTA_YEAR", "SOTA_HEADLINE", "SOTA_CELL", "SOTA_COMPARABILITY")
    w_sota(d, out)
    sub_ok(d, out)

    out = nx(d, "baseline_spec")
    nid = d.state()["tasks"][-1]["subject"]["node"]
    ok(nid == "N001", f"baseline should be N001, got {nid}")
    w_baseline_spec(d, out, nid)
    sub_ok(d, out)

    out = nx(d, "smoke")
    res = d.smoke("N001")
    ok(res["status"] == "pass", f"baseline smoke: {res}")
    sub_ok(d, out)

    out = nx(d, "evaluate")
    w_eval(d, out, "N001", 0.700, bad="missing")
    sub_rej(d, out, "EVAL_METRIC_MISSING")
    w_eval(d, out, "N001", 0.700)
    sub_ok(d, out)

    out = nx(d, "conclude")
    w_conclude(d, out, "N001", baseline=True)
    sub_ok(d, out)

    node = d.node("N001")
    ok(node["status"] == "concluded" and node["verdict"] == "baseline", f"baseline concluded: {node}")
    ok(node.get("commit"), "baseline commit captured")
    d.doctor_clean("end of bootstrap")


def run_r1(d):
    section("R001: exploit + git negatives + smoke fail + retrieval ladder + watch waiting")
    open_round(d, "R001", [exploit_lane("exploit1", "N001")])
    out = nx(d, "evidence")
    w_evidence_initial(d)
    # retrieval ladder: downgrading a paper without documenting the attempts is a rejection
    eutil.append_jsonl(d.repo / ".evo/evidence/EVIDENCE.jsonl", {
        "id": "E007", "title": "paywalled but relevant", "year": 2025,
        "url": "https://example.org/p7", "source": "mock-search",
        "relevance": ["B1"], "access": "abstract"})
    sub_rej(d, out, "RETRIEVAL_LADDER")
    rewrite_evidence_last(d, 1)
    eutil.append_jsonl(d.repo / ".evo/evidence/EVIDENCE.jsonl", {
        "id": "E007", "title": "paywalled but relevant", "year": 2025,
        "url": "https://example.org/p7", "source": "mock-search",
        "relevance": ["B1"], "access": "abstract",
        "retrieval_attempts": ["arxiv", "ar5iv", "semantic-scholar"]})
    sub_ok(d, out)

    lane = d.lane_by_name("exploit1")
    lid = lane["id"]
    out = nx(d, "deep_read")
    w_mech_cards(d, lid, 1, ["E001"])
    sub_rej(d, out, "MECH_COUNT")
    w_mech_cards(d, lid, 1, ["E005"])
    sub_ok(d, out)
    mech = [c["id"] for c in eutil.read_jsonl(d.repo / ".evo/evidence/MECH_CARDS.jsonl") if c["lane"] == lid]

    out = nx(d, "sketch")
    w_sketches(d, out, lid, L2_DIMS, mech, bad="under_level")
    sub_rej(d, out, "PROGRAM_UNDER_LEVEL")
    w_sketches(d, out, lid, L2_DIMS, mech, bad="bad_repair_evidence")
    sub_rej(d, out, "PROGRAM_REPAIR_EVIDENCE")
    w_sketches(d, out, lid, L2_DIMS, mech, specialist_last=True)
    sub_ok(d, out)

    out = nx(d, "tournament")
    w_tournament(d, out, lid, "K3", bad="sota_scope")
    sub_rej(d, out, "TOURNAMENT_FRONTIER_REF_SCOPE")
    lane_after_scope_reject = d.lane(lid)
    ok(lane_after_scope_reject["status"] == "tournament"
       and not lane_after_scope_reject.get("tournament_path")
       and not lane_after_scope_reject.get("tournament_seal"),
       "out-of-scope SOTA refs are rejected before tournament state is sealed")
    w_tournament(d, out, lid, "K1", bad="no_move_audit")
    sub_rej(d, out, "TOURNAMENT_IRREDUCIBILITY")
    w_tournament(d, out, lid, "K1")
    sub_ok(d, out)

    out = nx(d, "mature")
    w_mature(d, out, lid, mech_ids=mech,
             preds=preds_for(0.710), bad="level")
    sub_rej(d, out, "IDEA_LEVEL_MISMATCH")
    w_mature(d, out, lid, mech_ids=mech, preds=preds_for(0.710))
    sub_ok(d, out)

    out = nx(d, "red_team")
    w_red_team(d, out, lid, bad="no_objection")
    sub_rej(d, out, "REVIEW_OBJECTION")
    w_red_team(d, out, lid)
    sub_ok(d, out)

    def exploit_stages():
        return [stage("train", uri="oss://bkt/user/exploit1-train/checkpoint.zip", key="train|exploit1")]

    out = nx(d, "plan_node")
    w_plan(d, out, lid, role="variant", workdir="workareas/n002", stages=exploit_stages(),
           code_parent="N001", bad_extra=lambda spec: spec.update({"branch": "main"}))
    sub_rej(d, out, "SPEC_BRANCH_ENGINE_OWNED")
    w_plan(d, out, lid, role="variant", workdir=".", stages=exploit_stages(), code_parent="N001")
    sub_rej(d, out, "SPEC_WORKDIR_COLLISION")
    w_plan(d, out, lid, role="variant", workdir="workareas/n002", stages=exploit_stages(), code_parent="N001")
    sub_ok(d, out)
    nid = d.lane(lid)["node"]
    ok(nid == "N002", f"first variant should be N002: {nid}")
    node = d.node(nid)
    ok(str(node["branch"]).startswith("evo/n002-"), f"engine-assigned branch: {node['branch']}")

    out = nx(d, "implement")
    do_implement(d, out, nid, git_mode=False)
    sub_rej(d, out, "GIT_WORKDIR_NOT_ROOT")
    rmtree(d.repo / node["workdir"])
    do_implement(d, out, nid, break_flag=True)
    build_report = d.repo / out["outputs"][0]
    original_report = build_report.read_text(encoding="utf-8")
    wt(d.repo, "shared_escape.py", "# this main-worktree file must never become N002 implementation identity\n")
    wt(d.repo, out["outputs"][0], original_report.replace("`mod_a.py`", "`shared_escape.py`", 1))
    sub_rej(d, out, "BUILD_CODE_PATH_ESCAPE")
    wt(d.repo, out["outputs"][0], original_report)
    (d.repo / "shared_escape.py").unlink()
    sub_ok(d, out)

    out = nx(d, "smoke")
    res = d.smoke(nid)
    ok(res["status"] == "fail", f"broken flag must fail smoke: {res}")
    sub_rej(d, out, "SMOKE_FAILED")

    # A failed smoke test invalidates the active implementation head.  The
    # repair must therefore be an explicit, newly sealed implementation
    # revision rather than an in-place mutation beneath the old seal.
    out = nx(d, "implement")
    do_fix_implement(d, out, nid)
    sub_ok(d, out)
    ok(d.node(nid)["implementation_revision"] == 2,
       "smoke repair produced implementation revision 2")

    out = nx(d, "smoke")
    res = d.smoke(nid)
    ok(res["status"] == "pass", f"fixed smoke: {res}")
    sub_ok(d, out)
    maybe_fidelity(d, nid)

    out = nx(d, "stage_launch")
    w_launch(d, out, "train", bad_stage=True)
    sub_rej(d, out, "LAUNCH_STAGE")
    w_launch(d, out, "train", job="job-1")
    sub_ok(d, out)
    run_id = last_run(d)["id"]
    ok(d.node(nid)["status"] == "executing", "node executing after background stage launch")

    drive_watch_finish(d, run_id, nid, "train")
    node = d.node(nid)
    ok(node["status"] == "workflow_done" and node["stage_cursor"] == 1, f"absorbed: {node['status']}")
    reg = d.reg()["artifacts"]
    ok(len(reg) == 1 and reg[0]["id"] == "AR001" and reg[0]["node"] == "N002",
       f"artifact registered: {reg}")

    out = nx(d, "evaluate")
    w_eval(d, out, nid, 0.710)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, nid, bad="verdict")
    sub_rej(d, out, "OUTCOME_VERDICT_MISMATCH")
    w_conclude(d, out, nid, lessons=[{"scope": "global",
                                      "statement": long(40, "reweighting only helps when propensities are recorded"),
                                      "evidence": long(30, "node N002 confirmed both registered predictions"),
                                      "recommendation": long(30, "prefer slices with recorded propensities")}])
    sub_ok(d, out)

    out = nx(d, "close_round")
    w_retro(d, out, "R001")
    sub_ok(d, out)
    hist = d.state()["rounds"]
    ok(hist and hist[-1]["improved"] is True, f"R001 improved: {hist[-1]}")
    d.doctor_clean("after R001")


SKEY_PT = "pretrain|data=part2|obj=bfr|arch=d256l2"


def run_r2(d):
    section("R002: theory dialectic + 2-stage training + parallel lanes + slots + failure journal")
    # v11.4 fixture sync: voluntary focus service needs a round big enough
    # for the share cap (1/2 = the 50% cap exactly); the old early D1 service
    # lived on single-lane R004, which the cap now refuses outside
    # starvation. Serving D1 here keeps the later cadence intact: R007 then
    # serves it as the starvation-forced (cap-exempt) lane, and R012's
    # deliberate starvation window (R008-R011) is unchanged.
    open_round(d, "R002", [
        {"name": "reform-a", "intent": "reform", "min_level": 3, "parents": ["N002"],
         "focus": "D1"},
        exploit_lane("exploit-b", "N002"),
    ])
    out = nx(d, "evidence")
    w_evidence_refresh(d, 2, year=2010)
    sub_rej(d, out, "EVIDENCE_NEW_RECENCY")
    rewrite_evidence_last(d, 2)
    w_evidence_refresh(d, 2, year=2025)
    sub_ok(d, out)

    ra = d.lane_by_name("reform-a")["id"]
    out = nx(d, "deep_read")
    mech_a = w_mech_cards(d, ra, 2, ["E001", "E005"])
    sub_ok(d, out)
    out = nx(d, "sketch")
    w_sketches(d, out, ra, L3_DIMS, mech_a, bad="unknown_field")
    sub_rej(d, out, "PROGRAM_CANDIDATE_FIELDS")
    w_sketches(d, out, ra, L3_DIMS, mech_a)
    sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, ra, "K1", leverage=True, bad="quote")
    sub_rej(d, out, "QUOTE_NOT_LITERAL")
    w_tournament(d, out, ra, "K1", leverage=True)
    sub_ok(d, out)
    ok(d.lane(ra).get("formal") is False, "an explanatory theory keeps the lane on the prose path")

    # theory dialectic with negatives: c1 theorize (kinship tag), c1 challenge (quotes) REVISE,
    # c2 theorize (response duty), c2 challenge PROCEED
    out = nx(d, "theorize")
    w_theory(d, out, ra, parent_ref="N002", bad="no_relation_tag")
    sub_rej(d, out, "THEORY_DESIGN_OBLIGATIONS")
    w_theory(d, out, ra, parent_ref="N002", bad="no_precedent")
    sub_rej(d, out, "THEORY_PREDICTIONS")
    w_theory(d, out, ra, parent_ref="N002", relation="component")
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, ra, "REVISE", bad="one_quote")
    sub_rej(d, out, "QUOTE_TOO_FEW")
    w_challenge(d, out, ra, "REVISE")
    sub_ok(d, out)
    lane = d.lane(ra)
    ok(lane["status"] == "theorize" and lane["theory_cycle"] == 2, f"REVISE cycles: {lane['theory_cycle']}")
    prev_ch = f".evo/rounds/R002/lanes/{ra}/CHALLENGE_c1.md"
    out = nx(d, "theorize")
    w_theory(d, out, ra, parent_ref="N002", response_from=prev_ch, bad="no_response")
    sub_rej(d, out, "THEORY_RESPONSE_MISSING")
    w_theory(d, out, ra, parent_ref="N002", response_from=prev_ch)
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, ra, "PROCEED")
    sub_ok(d, out)

    drive_mature_redteam(d, ra, interface_changed=True, mech_ids=mech_a,
                         score=0.715, refute_second=True, theory=True)

    out = nx(d, "plan_node")
    bad_stages = [
        {"name": "pretrain", "launch": "x", "metrics_file": "m.json",
         "produces": [{"name": "w", "kind": "weights", "uri": "oss://bkt/user/bad/checkpoint.zip"}],
         "consumes": [{"stage": "finetune"}]},
        stage("finetune", uri="oss://bkt/user/reform-a-ft/checkpoint.zip", key="finetune|reform-a"),
    ]
    w_plan(d, out, ra, role="variant", workdir="workareas/n002/n003", stages=bad_stages, code_parent="N002")
    sub_rej(d, out, "SPEC_WORKDIR_OVERLAP", "SPEC_STAGE_KEY", "SPEC_CONSUME_STAGE")

    def reform_stages():
        return [
            stage("pretrain", uri="oss://bkt/user/reform-a-pretrain/checkpoint.zip", key=SKEY_PT),
            stage("finetune", uri="oss://bkt/user/reform-a-finetune/checkpoint.zip",
                  key="finetune|reform-a", consumes=[{"stage": "pretrain"}]),
        ]

    w_plan(d, out, ra, role="variant", workdir="workareas/n003/../n002",
           stages=reform_stages(), code_parent="N002")
    sub_rej(d, out, "SPEC_WORKDIR_COLLISION")
    w_plan(d, out, ra, role="variant", workdir="workareas/n003", stages=reform_stages(), code_parent="N002")
    sub_ok(d, out)
    n3 = d.lane(ra)["node"]
    ok(n3 == "N003", f"reform node: {n3}")

    out = nx(d, "implement")
    do_implement(d, out, n3, wrong_base=True)
    sub_rej(d, out, "GIT_ANCESTRY")
    fix_wrong_base(d, n3)
    do_implement(d, out, n3)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n3)["status"] == "pass", "N003 smoke")
    sub_ok(d, out)
    # v8: an L3 idea passes the implementation-fidelity audit before any compute
    ok(d.node(n3).get("fidelity_pending") is True, "L3 node armed for the fidelity audit")
    drive_fidelity(d, n3, neg=True)
    out = nx(d, "metric_bridge")
    w_bridge(d, out)
    sub_ok(d, out)
    out = nx(d, "stage_launch")
    ok(d.state()["tasks"][-1]["subject"]["stage"] == "pretrain", "first stage is pretrain")
    w_launch(d, out, "pretrain", job="job-2")
    sub_ok(d, out)
    run_pt = last_run(d)["id"]

    # PIPELINING: while N003 pretrains, the OTHER lane's work is issued
    rb = d.lane_by_name("exploit-b")["id"]
    out = nx(d, "deep_read")
    ok(d.state()["tasks"][-1]["subject"]["lane"] == rb, "pipelined task belongs to exploit-b")
    mech_b = w_mech_cards(d, rb, 2, ["E002", "E005"])
    sub_ok(d, out)
    out = nx(d, "sketch")
    w_sketches(d, out, rb, L2_DIMS, mech_b)
    sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, rb, "K1")
    sub_ok(d, out)
    out = nx(d, "mature")
    w_mature(d, out, rb, mech_ids=mech_b,
             preds=preds_for(0.712), dup_of="I001")
    sub_rej(d, out, "IDEA_GLOBAL_DUP")
    w_mature(d, out, rb, mech_ids=mech_b,
             preds=preds_for(0.712))
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, rb)
    sub_ok(d, out)
    n4 = drive_plan(d, rb, role="variant", code_parent="N002", stages=[
        stage("train", uri="oss://bkt/user/exploit-b-train/checkpoint.zip", key="train|exploit-b")])
    ok(n4 == "N004", f"exploit-b node: {n4}")
    out = nx(d, "implement")
    do_implement(d, out, n4)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n4)["status"] == "pass", "N004 smoke")
    sub_ok(d, out)
    maybe_fidelity(d, n4)

    # The approved two-slot manifest is immutable; N003 occupies one slot and
    # N004 may launch into the other without rewriting infrastructure facts.
    out = nx(d, "stage_launch")
    ok(d.state()["tasks"][-1]["subject"]["node"] == "N004", "launch belongs to N004")
    w_launch(d, out, "train", job="job-3")
    sub_ok(d, out)
    run_b1 = last_run(d)["id"]
    ok(len(d.running()) == 2, "two runs in parallel (slot quota)")

    waiting = nx(d, "stage_watch")  # both slots busy, nothing else to do
    ok((d.state()["tasks"][-1].get("subject") or {}).get("run") == run_pt,
       "the open watch is bound to N003 pretraining")
    # N004 training fails -> error journal -> fix pass -> relaunch
    d.run_update(run_b1, "failed", note="OOM: batch 4096 exceeds accelerator memory on worker 2")
    out = nx(d, "implement")
    ok(d.state()["tasks"][-1]["subject"]["node"] == "N004", "fix pass for the failed node")
    superseded = [e for e in d.events("watch_superseded") if e.get("task") == waiting["task"]]
    ok(len(superseded) == 1 and superseded[0].get("watched_run") == run_pt
       and superseded[0].get("trigger_run") == run_b1,
       "a failure on another run supersedes, rather than falsely closes, the pretraining watch")
    errs = eutil.read_jsonl(d.repo / ".evo/errors.jsonl")
    ok(len(errs) == 1 and errs[-1]["id"] == "ER001" and "OOM" in errs[-1]["note"], f"error journal: {errs}")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("ER001" in bundle and "OOM" in bundle, "error journal routed into the fix bundle")
    do_fix_implement(d, out, n4)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n4)["status"] == "pass", "N004 re-smoke")
    sub_ok(d, out)
    gate = nx(d, kind="gate")
    ok(gate.get("gate_kind") == "repeat_spend",
       "a code fix does not itself authorize paying for a replacement training run")
    d.decide(gate["gate"], True, "user reviewed the OOM fix and authorizes one replacement run")
    out = nx(d, "stage_launch")
    w_launch(d, out, "train", job="job-4")
    sub_ok(d, out)
    run_b2 = last_run(d)["id"]

    nx(d, "stage_watch")
    finish_run(d, run_pt, "workareas/n003/train_metrics_pretrain.json")
    out = nx(d, "stage_launch")   # absorb: N003 pretrain done -> stage_ready -> finetune launch
    node3 = d.node(n3)
    ok(node3["stage_cursor"] == 1, f"stage advanced: {node3['stage_cursor']}")
    ok(d.state()["tasks"][-1]["subject"] == {"node": n3, "round": "R002", "lane": ra,
                                               "run": last_run(d)["id"],
                                               "stage": "finetune", "ledger_required": False,
                                               "replica_seed": 1009, "replica_index": 0,
                                               "replica_total": 1},
       "finetune launch subject")
    arts = {a["id"]: a for a in d.reg()["artifacts"]}
    ok("AR002" in arts and arts["AR002"]["stage_key"] == SKEY_PT and arts["AR002"]["node"] == n3,
       f"pretrain artifact registered: {arts.get('AR002')}")
    w_launch(d, out, "finetune", job="job-5")
    sub_ok(d, out)
    run_ft = last_run(d)["id"]

    nx(d, "stage_watch")
    finish_run(d, run_b2, "workareas/n004/train_metrics_train.json")
    out = nx(d, "evaluate")
    ok(d.state()["tasks"][-1]["subject"]["node"] == n4, "evaluate the finished N004 while N003 still trains")
    w_eval(d, out, n4, 0.712)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, n4, lessons=[{"scope": "lineage",
                                     "statement": long(40, "the architecture swap pays only with the larger batch removed"),
                                     "evidence": long(30, "N004 improved after the OOM fix reduced the batch"),
                                     "recommendation": long(30, "keep batch under the accelerator memory envelope")}])
    sub_ok(d, out)

    nx(d, "stage_watch")
    finish_run(d, run_ft, "workareas/n003/train_metrics_finetune.json")
    out = nx(d, "evaluate")
    # The synthetic helper first completes the registered evaluator RUN and
    # then mutates ``out`` to the read-only analyst task.
    w_eval(d, out, n3, 0.715, bad="no_dyn")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("Stage evidence" in bundle and "pretrain" in bundle and "finetune" in bundle,
       "engine injects per-stage summaries and usage into the evaluation bundle")
    sub_rej(d, out, "EVAL_STAGE_EVIDENCE")
    w_eval(d, out, n3, 0.715)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, n3, bad="no_sota_settle")
    sub_rej(d, out, "OUTCOME_SOTA_MISSING")
    w_conclude(d, out, n3)
    sub_ok(d, out)
    oc3 = json.loads((d.repo / f".evo/nodes/{n3}/OUTCOME.json").read_text(encoding="utf-8"))
    ok(oc3.get("sota") and oc3["sota"][0]["sota"] == "S001", "SOTA target settled at conclusion")
    # engine recomputed P2 as refuted (aggressive threshold) - verify from the outcome we wrote
    oc = json.loads((d.repo / f".evo/nodes/{n3}/OUTCOME.json").read_text(encoding="utf-8"))
    ok(any(p["id"] == "P2" and p["verdict"] == "refuted" for p in oc["predictions"]),
       f"aggressive prediction refuted: {oc['predictions']}")

    drive_close(d, "R002")
    ok(len(d.reg()["artifacts"]) == 4, f"AR001..AR004 registered: {len(d.reg()['artifacts'])}")
    ok(len(d.events("stage_failed")) == 1, "one workflow-stage failure recorded")
    d.doctor_clean("after R002")


def run_r3(d):
    section("R003: artifact reuse duty + URI collision + platform node + completed-mode launch")
    open_round(d, "R003", [
        exploit_lane("reuse-c", "N003"),
        {"name": "plat", "intent": "platform", "min_level": 2, "parents": [],
         "search_origin": "repair"},
    ])
    evidence_refresh(d)

    rc = d.lane_by_name("reuse-c")["id"]
    out = nx(d, "deep_read")
    pool_before = _evidence_count(d)
    mech = w_mech_cards(d, rc, 2, ["E002", "E005"])
    eutil.append_jsonl(d.repo / ".evo/evidence/EVIDENCE.jsonl", {
        "id": f"E{pool_before + 1:03d}", "title": "lane-targeted fusion paper", "year": "not-a-year",
        "url": "https://example.org/topup", "source": "mock-search", "relevance": ["B1"]})
    sub_rej(d, out, "DEEPREAD_EVIDENCE_SCHEMA")
    rewrite_evidence_last(d, 1)
    w_evidence_refresh(d, 1, relevance=["B1"])
    sub_ok(d, out)
    ok(_evidence_count(d) == pool_before + 1, "targeted top-up record kept in the pool")
    out = nx(d, "sketch")
    w_sketches(d, out, rc, L2_DIMS, mech)
    sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, rc, "K1")
    sub_ok(d, out)
    lid = rc
    drive_mature_redteam(d, lid, mech_ids=mech, score=0.718)

    out = nx(d, "plan_node")
    # negative 1: same stage_key as the available pretrain artifact, no consume, no waiver
    w_plan(d, out, rc, role="variant", workdir="workareas/n005", code_parent="N003", stages=[
        stage("pretrain", uri="oss://bkt/user/reuse-c-pretrain/checkpoint.zip", key=SKEY_PT),
        stage("finetune", uri="oss://bkt/user/reuse-c-ft0/checkpoint.zip",
              key="finetune|reuse-c0", consumes=[{"stage": "pretrain"}])])
    sub_rej(d, out, "SPEC_ARTIFACT_REUSE_IGNORED")
    # negative 2: URI collision with a registered artifact
    w_plan(d, out, rc, role="variant", workdir="workareas/n005", code_parent="N003", stages=[
        stage("train", uri="oss://bkt/user/exploit1-train/checkpoint.zip", key="train|reuse-c")])
    sub_rej(d, out, "SPEC_ARTIFACT_URI_COLLISION")
    # good: consume the shared pretrain artifact instead of retraining
    w_plan(d, out, rc, role="variant", workdir="workareas/n005", code_parent="N003", stages=[
        stage("finetune", uri="oss://bkt/user/reuse-c-finetune/checkpoint.zip",
              key="finetune|reuse-c", consumes=[{"artifact": "AR002"}])])
    sub_ok(d, out)
    n5 = d.lane(rc)["node"]
    ok(n5 == "N005", f"reuse node: {n5}")

    out = nx(d, "implement")
    do_implement(d, out, n5)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n5)["status"] == "pass", "N005 smoke")
    sub_ok(d, out)
    out = nx(d, "stage_launch")
    w_launch(d, out, "finetune", job="job-6")
    sub_ok(d, out)
    run5 = last_run(d)["id"]

    # platform lane progresses while N005 trains
    pl = d.lane_by_name("plat")["id"]
    out = nx(d, "deep_read")
    ok(d.state()["tasks"][-1]["subject"]["lane"] == pl, "platform lane pipelined during training")
    mech_p = w_mech_cards(d, pl, 2, ["E003", "E005"])
    sub_ok(d, out)
    out = nx(d, "sketch")
    w_sketches(d, out, pl, L2_DIMS, mech_p)
    sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, pl, "K1")
    sub_ok(d, out)
    out = nx(d, "mature")
    w_mature(d, out, pl, mech_ids=mech_p,
             preds=[], platform=True)
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, pl)
    sub_ok(d, out)
    n6 = drive_plan(d, pl, role="platform", code_parent="N001",
                    enables=["variant lanes initialize from the distilled set",
                             "hybrid lanes reuse the shared candidate index"],
                    stages=[stage("build", uri="oss://bkt/user/plat-build/data.zip",
                                  key="platform|distilled", produces_kind="dataset")])
    ok(n6 == "N006", f"platform node: {n6}")
    out = nx(d, "implement")
    do_implement(d, out, n6)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n6)["status"] == "pass", "N006 smoke")
    sub_ok(d, out)
    out = nx(d, "stage_launch")
    w_launch(d, out, "build", mode="completed", metrics_rel="workareas/n006/train_metrics_build.json")
    sub_ok(d, out)
    node6 = d.node(n6)
    ok(node6["status"] in ("workflow_done", "evaluated"), f"completed-mode launch advances immediately: {node6['status']}")
    out = nx(d, "conclude")
    ok(d.state()["tasks"][-1]["subject"]["node"] == n6, "platform skips evaluate, concludes")
    # a platform may stand up runtime services (PRM/verifier/tool-server shape)
    w_conclude(d, out, n6, platform=True, services=["distill-index"], bad="bad_service")
    sub_rej(d, out, "OUTCOME_ENABLED_SERVICE")
    w_conclude(d, out, n6, platform=True, services=["distill-index"])
    sub_ok(d, out)
    ok(d.node(n6)["verdict"] == "enabled", "platform enabled")
    ok(d.node(n6).get("enabled_services") and
       d.node(n6)["enabled_services"][0]["name"] == "distill-index",
       "platform-enabled service recorded on the node")

    nx(d, "stage_watch")
    finish_run(d, run5, "workareas/n005/train_metrics_finetune.json")
    out = nx(d, "evaluate")
    w_eval(d, out, n5, 0.718)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, n5)
    sub_ok(d, out)
    drive_close(d, "R003")

    # CLI subprocess sanity: status + artifacts through the real entry point
    evo = PKG / "engine" / "evo.py"
    p = subprocess.run([PY, str(evo), "--repo", str(d.repo), "status", "--json"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(p.returncode == 0, f"CLI status exit 0: {p.stderr}")
    js = json.loads(p.stdout)
    ok(js["rounds_closed"] == 3, f"CLI status rounds: {js['rounds_closed']}")
    p = subprocess.run([PY, str(evo), "--repo", str(d.repo), "artifacts"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(p.returncode == 0 and "AR001" in p.stdout, "CLI artifacts lists AR001")
    d.doctor_clean("after R003")


def run_r4(d):
    section("R004: 2-parent hybrid consuming a platform")
    # (v11.4 fixture sync: the early D1 service moved to R002's two-lane
    # round - a voluntary single-lane focus round now exceeds the share cap)
    open_round(d, "R004", [
        {"name": "hyb", "intent": "hybrid", "min_level": 2, "parents": ["N005", "N004", "N006"]},
    ])
    evidence_refresh(d)
    lid, mech = drive_lane_to_plan(d, "hyb", dims=L2_DIMS, mech_papers=("E004", "E005"),
                                   hybrid_parents=["N005", "N004"])
    drive_mature_redteam(d, lid, mech_ids=mech,
                         score=0.722, hybrid=True)
    # the hybrid consumes the platform's stood-up service; unknown names rejected
    out = nx(d, "plan_node")
    w_plan(d, out, lid, role="hybrid", workdir="workareas/n007", code_parent="N005",
           eval_extra={"requires_services": ["prm-endpoint"]},
           stages=[stage("train", uri="oss://bkt/user/hyb-train/checkpoint.zip", key="train|hyb")])
    sub_rej(d, out, "SPEC_REQUIRES_SERVICE")
    w_plan(d, out, lid, role="hybrid", workdir="workareas/n007", code_parent="N005",
           eval_extra={"requires_services": ["distill-index"]},
           stages=[stage("train", uri="oss://bkt/user/hyb-train/checkpoint.zip", key="train|hyb")])
    sub_ok(d, out)
    n7 = d.lane(lid)["node"]
    ok(n7 == "N007", f"hybrid node: {n7}")
    node = d.node(n7)
    ok(node["parents"] == ["N005", "N004", "N006"] and node["code_parent"] == "N005",
       f"hybrid parents locked: {node['parents']}")
    run7 = drive_node_to_training(d, n7, job="job-7")
    drive_watch_finish(d, run7, n7, "train")
    drive_eval_conclude(d, n7, 0.722)
    drive_close(d, "R004")
    gens = egraph.compute_generations(d.graph())
    ok(gens["N007"] == max(gens["N005"], gens["N004"]) + 1,
       f"hybrid generation from model parents: {gens['N007']}")
    d.doctor_clean("after R004")


def run_r5(d):
    section("R005: wildcat cadence + exploit-share negative + L4 theory depth")
    out = nx(d, "open_round")
    w_portfolio(d, out, "R005", [exploit_lane("x1", "N007"), exploit_lane("x2", "N007"),
                                 exploit_lane("x3", "N007")])
    sub_rej(d, out, "PORTFOLIO_EXPLOIT_SHARE", "PORTFOLIO_WILDCAT_DUE")
    w_portfolio(d, out, "R005", [{"name": "wild", "intent": "wildcat", "min_level": 4, "parents": []}])
    sub_ok(d, out)
    evidence_refresh(d)

    wl = d.lane_by_name("wild")["id"]
    out = nx(d, "sketch")
    w_sketches(d, out, wl, L4_DIMS, [], custom_idx=3, reframe=True)
    sub_ok(d, out)
    out = nx(d, "deep_read")
    mech = w_mech_cards(d, wl, 4, ["E001", "E005", "E002", "E003"])
    sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, wl, "K1", leverage=True)
    sub_ok(d, out)
    out = nx(d, "theorize")
    w_theory(d, out, wl, parent_ref="baseline", moonshot=True, bad="no_relation_tag")
    sub_rej(d, out, "THEORY_DESIGN_OBLIGATIONS")
    w_theory(d, out, wl, parent_ref="baseline", moonshot=True)
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, wl, "REVISE")
    sub_ok(d, out)
    prev_ch_wl = f".evo/rounds/R005/lanes/{wl}/CHALLENGE_c1.md"
    out = nx(d, "theorize")
    w_theory(d, out, wl, parent_ref="baseline", moonshot=True, response_from=prev_ch_wl)
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, wl, "PROCEED")
    sub_ok(d, out)
    lid = wl
    out = nx(d, "mature")
    w_mature(d, out, lid, interface_changed=True, mech_ids=mech,
             preds=preds_for(0.724), n_assum=4, deriv_chars=1300, theory=True, bad="short_deriv")
    sub_rej(d, out, "IDEA_DERIVATION_TRACE")
    w_mature(d, out, lid, interface_changed=True, mech_ids=mech,
             preds=preds_for(0.724), n_assum=4, deriv_chars=1300, theory=True)
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, lid)
    sub_ok(d, out)
    n8 = drive_plan(d, lid, role="root", code_parent="N001", stages=[
        stage("train", uri="oss://bkt/user/wild-train/checkpoint.zip", key="train|wild")])
    ok(n8 == "N008" and d.node(n8)["role"] == "root" and d.node(n8)["level"] == 4,
       f"wildcat root: {d.node(n8)['role']} L{d.node(n8)['level']}")
    run8 = drive_node_to_training(d, n8, bridge=True, job="job-8")
    drive_watch_finish(d, run8, n8, "train")
    drive_eval_conclude(d, n8, 0.724)
    drive_close(d, "R005")
    ok(d.state()["rounds"][-1]["improved"] is True, "R005 moved the frontier")
    d.doctor_clean("after R005")


def run_r6(d):
    section("R006: regressed node with root-cause attribution")
    drive_std_exploit_round(
        d, "R006", "regress-d", "N008", 0.710, neg_root_cause=True, close=False,
        lessons=[{"scope": "lineage",
                  "statement": long(40, "the reweighted head regresses when applied on top of the new principle root"),
                  "evidence": long(30, "N009 fell from 0.724 to 0.710 with A1 refuted"),
                  "recommendation": long(30, "test propensity validity before stacking mechanisms on this root")}])
    out = nx(d, "close_round")
    wt(d.repo, ".evo/profile/DOSSIER_ADDENDUM.md",
       "# addendum\n- B1: rebinding an existing bottleneck id | evidence: [src: eval.py] "
       "| falsifier: parent-specific interference disappears on controlled slices "
       "| distinguish: compare the same intervention across unrelated parent lineages\n")
    w_retro(d, out, "R006")
    sub_rej(d, out, "RETRO_ADDENDUM_DUP")
    wt(d.repo, ".evo/profile/DOSSIER_ADDENDUM.md",
       "# addendum\n- B4: stacking on the new-principle root interferes with its objective "
       "| evidence: N009 root cause A1 [src: eval.py] "
       "| falsifier: the same regression persists when objective gradients are isolated "
       "| distinguish: compare gradient conflict on this root and an unrelated parent\n")
    w_retro(d, out, "R006")
    sub_ok(d, out)
    n9 = d.node("N009")
    ok(n9["verdict"] == "regressed", f"N009 regressed: {n9['verdict']}")
    oc = json.loads((d.repo / ".evo/nodes/N009/OUTCOME.json").read_text(encoding="utf-8"))
    ok(oc["root_cause"]["assumptions"] == ["A1"], "root cause names the failed assumption")
    ok(d.state()["rounds"][-1]["improved"] is False, "R006 flat")
    d.doctor_clean("after R006")


def doctor_fix_test(d):
    section("doctor --fix repairs a corrupted counter")
    import edoctor
    stp = d.repo / ".evo/state.json"
    st = json.loads(stp.read_text(encoding="utf-8"))
    real = st["counters"]["LS"]
    ok(real >= 2, f"some lessons recorded: {real}")
    st["counters"]["LS"] = 1
    stp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    problems, _ = edoctor.diagnose(d.store(), fix=False)
    ok(any(p.startswith("COUNTER_BEHIND") for p in problems), f"corruption detected: {problems}")
    problems, repairs = edoctor.diagnose(d.store(), fix=True)
    ok(any("LS" in r for r in repairs), f"counter repaired: {repairs}")
    d.doctor_clean("after doctor --fix")


def run_r7(d):
    section("R007: flat round + lesson/sibling routing into bundles")
    out = nx(d, "open_round")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("Prediction calibration" in bundle and "registered predictions" in bundle,
       "calibration ledger routed into the strategist bundle")
    card = (d.repo / out["card"]).read_text(encoding="utf-8")
    ok("USER FOCUS DIRECTIONS" in card and "D1" in card,
       "focus directions surfaced in the strategist's policy notes")
    w_portfolio(d, out, "R007", [{"name": "flat-e", "intent": "exploit", "min_level": 2,
                                  "parents": ["N008"], "bottleneck_ids": ["B4"], "focus": "D9"}])
    sub_rej(d, out, "PORTFOLIO_FOCUS_UNKNOWN")
    w_portfolio(d, out, "R007", [{"name": "flat-e", "intent": "exploit", "min_level": 2,
                                  "parents": ["N008"], "bottleneck_ids": ["B4"], "focus": "D1"}])
    sub_ok(d, out)
    # SOTA refresh cadence: round 7 re-scans the library (rolling frontier)
    out = nx(d, "sota_scan")
    w_sota(d, out, append=2)
    sub_ok(d, out)
    ok(len(eutil.read_jsonl(d.repo / ".evo/evidence/SOTA.jsonl")) == 8,
       "SOTA library refreshed by appending, ids continued")
    out = nx(d, "evidence")
    w_evidence_refresh(d)
    sub_rej(d, out, "EVIDENCE_BOTTLENECK_COVERAGE")
    w_evidence_refresh(d, 2, relevance=["B4"])
    sub_ok(d, out)
    lid = d.lane_by_name("flat-e")["id"]
    out = nx(d, "deep_read")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("LS001" in bundle, "global lesson routed into the deep_read bundle")
    mech = w_mech_cards(d, lid, 2, ["E001", "E005"])
    sub_ok(d, out)
    out = nx(d, "sketch")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("N009" in bundle, "sibling failure (N009) surfaced in the sketch bundle")
    w_sketches(d, out, lid, L2_DIMS, mech, efficiency=True)
    sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, lid, "K1")
    sub_ok(d, out)
    # v9 dominance: pre-registered secondary-axis claim; at primary parity a met
    # claim concludes 'dominant' (same-quality-but-cheaper), not 'inconclusive'
    drive_mature_redteam(d, lid, mech_ids=mech, score=0.724,
                         dominance={"metric": "logloss", "comparison": "<=", "value": 0.65,
                                    "rationale": long(35, "at auc parity the reweighted head must cut logloss measurably")})
    n10 = drive_plan(d, lid, role="variant", code_parent="N008", stages=[
        stage("train", uri="oss://bkt/user/flat-e-train/checkpoint.zip", key="train|flat-e")])
    run10 = drive_node_to_training(d, n10, job="job-10")
    drive_watch_finish(d, run10, n10, "train")
    drive_eval_conclude(d, n10, 0.724, logloss=0.55)
    ok(d.node(n10)["verdict"] == "dominant",
       f"parity + met dominance claim concludes dominant: {d.node(n10)['verdict']}")
    drive_close(d, "R007")
    ok(d.state()["rounds"][-1]["improved"] is True, "R007 moves the Pareto frontier on calibration")
    # Keep the suite's later deep-stagnation scenario compact after this genuine
    # multi-objective gain reset the clock.
    cfg = project_cfg(d)
    cfg["policy"]["stagnation_moonshot_rounds"] = 2
    wj(d.repo, ".evo/config.json", cfg)


def reform_after_open(d, name, parent, score):
    evidence_refresh(d)
    lid, mech = drive_lane_to_plan(
        d, name, dims=L3_DIMS, leverage=True,
        theory_steps=[("theorize", {"parent_ref": parent}), ("challenge", {"verdict": "PROCEED"})])
    drive_mature_redteam(d, lid, interface_changed=True, mech_ids=mech,
                         score=score, theory=True)
    nid = drive_plan(d, lid, role="variant", code_parent=parent, stages=[
        stage("train", uri=f"oss://bkt/user/{name}-train/checkpoint.zip", key=f"train|{name}")])
    run_id = drive_node_to_training(d, nid, bridge=True)
    drive_watch_finish(d, run_id, nid, "train")
    drive_eval_conclude(d, nid, score)
    return nid


def run_r8(d):
    section("R008: stagnation tier 1 forces an L3+ lane")
    out = nx(d, "open_round")
    w_portfolio(d, out, "R008", [exploit_lane("lazy", "N008")])
    sub_rej(d, out, "PORTFOLIO_EXPLOIT_OFF_FRONTIER")
    w_portfolio(d, out, "R008", [{"name": "reform-f", "intent": "reform", "min_level": 3,
                                  "parents": ["N008"]}])
    sub_ok(d, out)
    reform_after_open(d, "reform-f", "N008", 0.724)
    drive_close(d, "R008")
    ok(d.state()["rounds"][-1]["improved"] is False, "R008 flat")


def run_r9(d):
    section("R009: still stagnant; reform on another lineage")
    open_round(d, "R009", [{"name": "reform-g", "intent": "reform", "min_level": 3,
                            "parents": ["N007"]}])
    reform_after_open(d, "reform-g", "N007", 0.722)
    drive_close(d, "R009")
    ok(d.state()["rounds"][-1]["improved"] is False, "R009 flat")


def run_r10(d):
    section("R010: deep stagnation forces MOONSHOT; full frontier-tier pipeline; prune at close")
    out = nx(d, "open_round")
    w_portfolio(d, out, "R010", [{"name": "lazy-reform", "intent": "reform", "min_level": 3,
                                  "parents": ["N008"]}])
    sub_rej(d, out, "PORTFOLIO_STAGNATION_REQUIRES_MOONSHOT")
    w_portfolio(d, out, "R010", [{"name": "moon", "intent": "moonshot", "min_level": 4, "parents": []}])
    sub_ok(d, out)
    evidence_refresh(d)

    ml = d.lane_by_name("moon")["id"]
    out = nx(d, "sketch")
    w_sketches(d, out, ml, L4_DIMS_NB, [], reframe=True, theory_rigor="full", bad="unknown_field")
    sub_rej(d, out, "PROGRAM_CANDIDATE_FIELDS")
    w_sketches(d, out, ml, L4_DIMS_NB, [], reframe=True, theory_rigor="full")
    sub_ok(d, out)
    out = nx(d, "deep_read")
    mech = w_mech_cards(d, ml, 3, ["E001", "E002", "E005"])
    sub_rej(d, out, "MECH_COUNT")
    mech += w_mech_cards(d, ml, 1, ["E002"])
    sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, ml, "K1", leverage=True, bad="no_move_audit")
    sub_rej(d, out, "TOURNAMENT_IRREDUCIBILITY")
    w_tournament(d, out, ml, "K1", leverage=True)
    sub_ok(d, out)
    lane = d.lane(ml)
    ok(lane["formal"] is True and lane["formal_kind"] == "full" and lane["status"] == "pose",
       f"full-rigor winner routes the lane into the formal ladder: {lane['status']}")

    # POSE: the precise problem (typed symbols, Given, Want) before any theory
    out = nx(d, "pose")
    w_problem(d, out, bad="few_syms")
    sub_rej(d, out, "POSE_SYMBOLS")
    w_problem(d, out)
    sub_ok(d, out)
    lane = d.lane(ml)
    ok(lane["problem_path"].endswith("PROBLEM_c1.md") and lane["status"] == "theorize"
       and lane["theory_cycle"] == 1, f"pose accepted -> theorize c1: {lane}")

    out = nx(d, "theorize")
    # A full-rigor chain must survive its own toy instance.
    w_theory(d, out, ml, parent_ref="baseline", moonshot=True, formal=True, bad="toy_fail")
    sub_rej(d, out, "THEORY_TOY_FAILED")
    w_theory(d, out, ml, parent_ref="baseline", moonshot=True, formal=True, bad="chain_bad")
    sub_rej(d, out, "THEORY_STEP_PREMISE", "THEORY_STEP_WANT", "THEORY_SYMBOL_UNUSED")
    w_theory(d, out, ml, parent_ref="baseline", moonshot=True, formal=True)
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, ml, "PROCEED", formal=True)
    sub_rej(d, out, "CHALLENGE_DEEP_MIN_CYCLES")
    w_challenge(d, out, ml, "READ", topics=["distributional value estimation"], bad="no_topics",
                formal=True)
    sub_rej(d, out, "CHALLENGE_READ_TOPICS")
    w_challenge(d, out, ml, "READ",
                topics=["distributional value estimation", "propensity model calibration"],
                formal=True)
    sub_ok(d, out)
    lane = d.lane(ml)
    ok(lane["status"] == "deep_read" and len(lane["required_topics"]) == 2,
       f"READ verdict sends the lane back to reading: {lane['status']}")
    ok(len(d.events("lane_reading_required")) == 1, "reading requirement event recorded")

    out = nx(d, "deep_read")
    w_mech_cards(d, ml, 1, ["E002"])   # no topic field -> uncovered
    sub_rej(d, out, "MECH_TOPIC_UNCOVERED")
    mech += w_mech_cards(d, ml, 2, ["E001", "E002"],
                         topics=["distributional value estimation", "propensity model calibration"])
    sub_ok(d, out)
    lane = d.lane(ml)
    ok(lane["status"] == "theorize" and lane["theory_cycle"] == 2 and not lane["required_topics"],
       f"reading debt paid, back to theory cycle 2: {lane}")

    prev_ch = f".evo/rounds/R010/lanes/{ml}/CHALLENGE_c1.md"
    out = nx(d, "theorize")
    w_theory(d, out, ml, parent_ref="baseline", moonshot=True, formal=True, response_from=prev_ch)
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, ml, "PROCEED", formal=True, bad="no_s_id")
    sub_rej(d, out, "CHALLENGE_STEP_AUDIT")
    w_challenge(d, out, ml, "PROCEED", formal=True)
    sub_ok(d, out)

    out = nx(d, "mature")
    w_mature(d, out, ml, mech_ids=mech,
             preds=preds_for(0.740), n_assum=5, deriv_chars=2100, theory=True, formal=True,
             bad="short_deriv")
    sub_rej(d, out, "IDEA_DERIVATION_TRACE")
    w_mature(d, out, ml, mech_ids=mech,
             preds=preds_for(0.740), n_assum=5, deriv_chars=2100, theory=True, formal=True)
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, ml)
    sub_ok(d, out)

    # reuse waiver: same stage_key as the shared pretrain artifact, but justified retrain
    n13 = drive_plan(d, ml, role="root", code_parent="N001", stages=[
        stage("train", uri="oss://bkt/user/moon-train/checkpoint.zip", key=SKEY_PT,
              waiver=long(60, "the new principle changes the objective so the shared pretrain init is invalid"))])
    ok(n13 == "N013" and d.node(n13)["role"] == "root", f"moonshot root: {n13}")
    run13 = drive_node_to_training(d, n13, job="job-13")
    drive_watch_finish(d, run13, n13, "train")
    drive_eval_conclude(d, n13, 0.740)
    drive_close(d, "R010", retire=[{"node": "N009", "reason": "pruned",
                                    "note": long(70, "the lineage premise was refuted at the root cause and holds no promise")}])
    ok(d.node("N009")["retire_reason"] == "pruned", "N009 pruned at retro")
    stale = [a for a in d.reg()["artifacts"] if a["node"] == "N009"]
    ok(stale and all(a["status"] == "stale" for a in stale), f"pruned node artifacts stale: {stale}")
    ok(d.state()["rounds"][-1]["improved"] is True, "moonshot moved the frontier")
    d.doctor_clean("after R010")


def run_r11(d):
    section("R011: pruned-parent rejection -> revival; 3-parent hybrid + platform; parallel finish")
    out = nx(d, "open_round")
    w_portfolio(d, out, "R011", [exploit_lane("necro", "N009")])
    sub_rej(d, out, "PORTFOLIO_PARENT_PRUNED")
    evo = PKG / "engine" / "evo.py"
    p = subprocess.run([PY, str(evo), "--repo", str(d.repo), "revive", "--node", "N009",
                        "--note", "the user wants the lineage reopened for hybridization"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(p.returncode == 0, f"revive CLI: {p.stderr}")
    revived = [a for a in d.reg()["artifacts"] if a["node"] == "N009"]
    ok(revived and all(a["status"] == "available" for a in revived), "revival restores artifacts")
    # A hybrid is constructive by semantics; it cannot be routed through local repair.
    w_portfolio(d, out, "R011", [
        {"name": "hyb3", "intent": "hybrid", "min_level": 2,
         "parents": ["N013", "N007", "N009", "N006"], "search_origin": "repair"},
        exploit_lane("exp-h", "N013"),
    ])
    sub_rej(d, out, "PORTFOLIO_HYBRID_ORIGIN")
    w_portfolio(d, out, "R011", [
        {"name": "hyb3", "intent": "hybrid", "min_level": 2,
         "parents": ["N013", "N007", "N009", "N006"]},
        {"name": "reform-h", "intent": "reform", "min_level": 3, "parents": ["N013"]},
    ])
    sub_ok(d, out)
    evidence_refresh(d)

    h3 = d.lane_by_name("hyb3")["id"]
    lid, mech = drive_lane_to_plan(d, "hyb3", dims=L2_DIMS, mech_papers=("E003", "E005"),
                                   hybrid_parents=["N013", "N007", "N009"])
    drive_mature_redteam(d, lid, mech_ids=mech,
                         score=0.745, hybrid=True)
    n14 = drive_plan(d, lid, role="hybrid", code_parent="N013", stages=[
        stage("train", uri="oss://bkt/user/hyb3-train/checkpoint.zip", key="train|hyb3")])
    node = d.node(n14)
    ok(node["parents"] == ["N013", "N007", "N009", "N006"], f"4-parent hybrid: {node['parents']}")
    out = nx(d, "implement")
    do_implement(d, out, n14)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n14)["status"] == "pass", "N014 smoke")
    sub_ok(d, out)
    out = nx(d, "stage_launch")
    w_launch(d, out, "train", job="job-14")
    sub_ok(d, out)
    run14 = last_run(d)["id"]

    # reform-h pipelined during N014 training (prose theory dialectic + fidelity)
    lid2, mech2 = drive_lane_to_plan(
        d, "reform-h", dims=L3_DIMS_NB, mech_papers=("E004", "E005"), leverage=True,
        theory_steps=[("theorize", {"parent_ref": "N013"}), ("challenge", {"verdict": "PROCEED"})])
    drive_mature_redteam(d, lid2, mech_ids=mech2, score=0.742,
                         theory=True)
    n15 = drive_plan(d, lid2, role="variant", code_parent="N013", stages=[
        stage("train", uri="oss://bkt/user/reform-h-train/checkpoint.zip", key="train|reform-h")])
    out = nx(d, "implement")
    do_implement(d, out, n15)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n15)["status"] == "pass", "N015 smoke")
    sub_ok(d, out)
    maybe_fidelity(d, n15)
    out = nx(d, "stage_launch")
    w_launch(d, out, "train", job="job-15")
    sub_ok(d, out)
    run15 = last_run(d)["id"]
    ok(len(d.running()) == 2, "hybrid and reform training in parallel")

    nx(d, "stage_watch")
    finish_run(d, run14, "workareas/n014/train_metrics_train.json")
    out = nx(d, "evaluate")
    ok(d.state()["tasks"][-1]["subject"]["node"] == n14, "N014 evaluated while N015 trains")
    w_eval(d, out, n14, 0.745)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, n14)
    sub_ok(d, out)

    nx(d, "stage_watch")
    finish_run(d, run15, "workareas/n015/train_metrics_train.json")
    out = nx(d, "evaluate")
    w_eval(d, out, n15, 0.742)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, n15)
    sub_ok(d, out)
    drive_close(d, "R011")
    gens = egraph.compute_generations(d.graph())
    ok(gens["N014"] == max(gens["N013"], gens["N007"], gens["N009"]) + 1,
       f"hybrid generation: {gens['N014']}")
    d.doctor_clean("after R011")


def run_r12(d):
    section("R012: focus starvation forcing + escalation on a stuck task -> user reset")
    out = nx(d, "open_round")
    # D1 was last served in R007; with focus_neglect_rounds=4 the window R008-R011
    # is starved - a portfolio ignoring it is rejected
    w_portfolio(d, out, "R012", [exploit_lane("final", "N014")])
    sub_rej(d, out, "PORTFOLIO_FOCUS_NEGLECTED")
    w_portfolio(d, out, "R012", [exploit_lane("final", "N014", focus="D1")])
    sub_ok(d, out)
    evidence_refresh(d)
    lid = d.lane_by_name("final")["id"]
    out = nx(d, "deep_read")
    mech = w_mech_cards(d, lid, 2, ["E001", "E005"])
    sub_ok(d, out)

    out = nx(d, "sketch")
    for i in range(3):
        wt(d.repo, out["outputs"][0], "this is not json {")
        r = d.submit(out["task"])
        ok(r["kind"] == "rejected", f"garbage sketch rejected (attempt {i + 1})")
    ok(r.get("escalation"), f"third failure escalates: {r}")
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "escalation", f"escalation gate presented: {gate}")
    d.decide(gate["gate"], True, note="reset and try again with the recorded deficiencies in mind")
    out2 = nx(d, "sketch")
    ok(out2["task"] == out["task"] and out2["attempts"] == 0, f"task reopened with reset attempts: {out2}")
    w_sketches(d, out2, lid, L2_DIMS, mech)
    sub_ok(d, out2)

    out = nx(d, "tournament")
    w_tournament(d, out, lid, "K1")
    sub_ok(d, out)
    drive_mature_redteam(d, lid, mech_ids=mech, score=0.750)
    n16 = drive_plan(d, lid, role="variant", code_parent="N014", stages=[
        stage("train", uri="oss://bkt/user/final-train/checkpoint.zip", key="train|final")])
    run16 = drive_node_to_training(d, n16, job="job-16")
    drive_watch_finish(d, run16, n16, "train")
    drive_eval_conclude(d, n16, 0.750)
    drive_close(d, "R012")
    d.doctor_clean("after R012")


def run_r13(d):
    section("R013: focus lane share + variant-of-hybrid + inference-class (evaluation-only) node")
    out = nx(d, "open_round")
    # focus lanes are capped at half the round
    w_portfolio(d, out, "R013", [
        {"name": "reform-i", "intent": "reform", "min_level": 3, "parents": ["N016"], "focus": "D1"},
        {"name": "infer-j", "intent": "exploit", "min_level": 2, "parents": ["N016"], "focus": "D1"},
    ])
    sub_rej(d, out, "PORTFOLIO_FOCUS_SHARE")
    w_portfolio(d, out, "R013", [
        {"name": "reform-i", "intent": "reform", "min_level": 3, "parents": ["N016"], "focus": "D1"},
        {"name": "infer-j", "intent": "exploit", "min_level": 2, "parents": ["N016"]},
    ])
    sub_ok(d, out)
    evidence_refresh(d)

    # reform-i: prose theory + fidelity, single-stage training
    lid, mech = drive_lane_to_plan(
        d, "reform-i", dims=L3_DIMS_NB, mech_papers=("E001", "E005"), leverage=True,
        theory_steps=[("theorize", {"parent_ref": "N016"}), ("challenge", {"verdict": "PROCEED"})])
    drive_mature_redteam(d, lid, mech_ids=mech, score=0.752,
                         theory=True)
    n17 = drive_plan(d, lid, role="variant", code_parent="N016", stages=[
        stage("train", uri="oss://bkt/user/reform-i-train/checkpoint.zip", key="train|reform-i")])
    ok(n17 == "N017", f"reform-i node: {n17}")
    run17 = drive_node_to_training(d, n17, job="job-17")

    # infer-j: an inference-class experiment on the modern stack - NO training
    # stages (prompting/decoding/memory-style change), a SERVED-model dependency,
    # a BACKGROUND agentic-benchmark eval, and sampled (noisy) metrics
    lid2, mech2 = drive_lane_to_plan(d, "infer-j", dims=L2_DIMS, mech_papers=("E002", "E005"))
    drive_mature_redteam(d, lid2, mech_ids=mech2,
                         score=0.751)
    out = nx(d, "plan_node")
    w_plan(d, out, lid2, role="variant", workdir="workareas/n018", code_parent="N016",
           stages=None, cost="light", eval_extra={"requires_llm": True},
           bad_extra=lambda spec: spec.update({"experiment_class": "quantum"}))
    sub_rej(d, out, "SPEC_EXPERIMENT_CLASS", "SPEC_STAGES")
    # The served-model dependency was declared, reviewed and canary-tested at bootstrap.
    w_plan(d, out, lid2, role="variant", workdir="workareas/n018", code_parent="N016",
           stages=None, cost="light",
           eval_extra={"requires_llm": True, "background": True},
           bad_extra=lambda spec: spec.update({"experiment_class": "inference"}))
    sub_ok(d, out)
    n18 = d.lane(lid2)["node"]
    ok(n18 == "N018", f"inference node: {n18}")
    out = nx(d, "implement")
    do_implement(d, out, n18)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n18)["status"] == "pass", "N018 smoke")
    sub_ok(d, out)
    maybe_fidelity(d, n18)   # inference_procedure replace is semantic (L3) -> audited too
    # evaluation-only + background eval: the hours-long harness is a RUN, not a task
    out = nx(d, "eval_launch")
    ok(d.node(n18)["status"] == "workflow_done", "evaluation-only node reached workflow_done without a stage run")
    w_launch_eval(d, out, bad="no_job")
    sub_rej(d, out, "EVAL_LAUNCH_JOB")
    w_launch_eval(d, out, job="eval-job-18")
    sub_ok(d, out)
    ok(d.node(n18)["status"] == "evaluating", "background eval registered; node evaluating")
    run_ev = last_run(d)["id"]
    st_runs = d.running()
    ok(any(r["kind"] == "eval" for r in st_runs) and any(r["kind"] == "stage" for r in st_runs),
       "a background eval and a workflow-stage run in flight together")
    ok(len([r for r in st_runs if r["kind"] == "stage"]) <= 2,
       "eval runs do not consume workflow-stage slots")
    # harness finishes; absorption returns the node to workflow_done with eval_done
    spec18 = json.loads((d.repo / d.node(n18)["spec"]).read_text(encoding="utf-8"))
    probe18 = spec18["probe_execution"]
    obs18 = evalid.expected_probe_observations(spec18)[0]
    vals18 = {str(field): 0.97 for field in probe18["required_fields"]}
    wj(d.repo, obs18["artifact"], vals18)
    raw18 = {"auc": 0.751, "logloss": 0.549, "latency_ms": 100.0,
             "_usage": {"wallclock_minutes": 1.0},
             "_mechanism_probe": {
                 "mode": probe18["mode"], "signal": probe18["signal"], "expect": probe18["expect"],
                 "required_fields": probe18["required_fields"],
                 "observations": [{"artifact": obs18["artifact"], "values": vals18}],
             }}
    wt(d.repo, "workareas/n018/agent_eval_raw.json", json.dumps(raw18))
    d.run_update(run_ev, "finished", metrics_file="workareas/n018/agent_eval_raw.json")
    out = nx(d, "evaluate")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("agent_eval_raw.json" in bundle, "evaluate bundle points at the background run's metrics")
    w_eval(d, out, n18, 0.751, dist=True, bad="no_n")
    sub_rej(d, out, "EVAL_METRIC_LEGACY_AGGREGATE")
    w_eval(d, out, n18, 0.751, dist=True)
    sub_ok(d, out)
    ok(d.node(n18)["scores"]["auc"] == 0.751,
       "explicit fixed-prediction interval stores its point estimate in the graph")
    out = nx(d, "conclude")
    w_conclude(d, out, n18)
    sub_ok(d, out)
    ok(d.node(n18)["verdict"] == "improved", "inference node improved over its parent")

    drive_watch_finish(d, run17, n17, "train")
    drive_eval_conclude(d, n17, 0.752)
    drive_close(d, "R013")
    ok(d.state()["rounds"][-1]["improved"] is True, "R013 moved the frontier")
    d.doctor_clean("after R013")


def run_r14(d):
    section("R014: FORMALIZE verdict converts a prose lane; L4 root lands at parity -> promising")
    open_round(d, "R014", [{"name": "wild2", "intent": "wildcat", "min_level": 4, "parents": []}])
    out = nx(d, "sota_scan")   # refresh cadence: 14 % 7 == 0
    w_sota(d, out, append=2)
    sub_ok(d, out)
    evidence_refresh(d)
    wl = d.lane_by_name("wild2")["id"]
    out = nx(d, "sketch")
    w_sketches(d, out, wl, L4_DIMS, [], reframe=True)
    sub_ok(d, out)
    out = nx(d, "deep_read")
    mech = w_mech_cards(d, wl, 4, ["E001", "E005", "E002", "E003"])
    sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, wl, "K1", leverage=True)
    sub_ok(d, out)
    ok(d.lane(wl)["formal"] is False and d.lane(wl)["status"] == "theorize",
       "prose path entered for an explanatory theory claim")

    out = nx(d, "theorize")
    w_theory(d, out, wl, parent_ref="baseline", moonshot=True)
    sub_ok(d, out)
    # the critic sees a precise claim hiding in prose and demands the ladder
    out = nx(d, "challenge")
    w_challenge(d, out, wl, "FORMALIZE", bad="no_demand")
    sub_rej(d, out, "CHALLENGE_FORMALIZE_WHY")
    w_challenge(d, out, wl, "FORMALIZE")
    sub_ok(d, out)
    lane = d.lane(wl)
    ok(lane["formal"] is True and lane["status"] == "pose",
       f"FORMALIZE converts the lane mid-dialectic: {lane['status']}")

    out = nx(d, "pose")
    w_problem(d, out, bad="unused_sym")
    sub_rej(d, out, "POSE_SYMBOL_UNUSED")
    w_problem(d, out)
    sub_ok(d, out)
    prev_ch = f".evo/rounds/R014/lanes/{wl}/CHALLENGE_c1.md"
    out = nx(d, "theorize")
    w_theory(d, out, wl, parent_ref="baseline", moonshot=True, formal=True, bad="few_steps",
             response_from=prev_ch)
    sub_rej(d, out, "THEORY_STEPS")
    w_theory(d, out, wl, parent_ref="baseline", moonshot=True, formal=True, response_from=prev_ch)
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, wl, "PROCEED", formal=True)
    sub_ok(d, out)

    out = nx(d, "mature")
    w_mature(d, out, wl, interface_changed=True, mech_ids=mech,
             preds=preds_for(0.695), n_assum=4, deriv_chars=1300, theory=True, formal=True,
             bad="no_formal_meta")
    sub_rej(d, out, "IDEA_PROBLEM_LINK", "MD_SECTION_MISSING", "IDEA_SOTA_TARGET")
    # v9: an L3+ idea without a mechanism probe (and no waiver) is unattributable
    w_mature(d, out, wl, interface_changed=True, mech_ids=mech,
             preds=preds_for(0.695), n_assum=4, deriv_chars=1300, theory=True, formal=True,
             bad="no_probe")
    sub_rej(d, out, "FIELD_TOO_SHORT")
    w_mature(d, out, wl, interface_changed=True, mech_ids=mech,
             preds=preds_for(0.695), n_assum=4, deriv_chars=1300, theory=True, formal=True)
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, wl)
    sub_ok(d, out)
    n19 = drive_plan(d, wl, role="root", code_parent="N001", stages=[
        stage("train", uri="oss://bkt/user/wild2-train/checkpoint.zip", key="train|wild2")])
    ok(n19 == "N019" and d.node(n19)["role"] == "root", f"wild2 root: {n19}")
    run19 = drive_node_to_training(d, n19, bridge=True, job="job-19")
    drive_watch_finish(d, run19, n19, "train")
    # 0.695 vs baseline 0.700: within the 1% parity margin -> a fresh paradigm
    # matching the incumbent on first contact concludes PROMISING, not inconclusive
    out = nx(d, "evaluate")
    w_eval(d, out, n19, 0.695, bad="no_anom")
    sub_rej(d, out, "EVAL_ANOMALIES")
    w_eval(d, out, n19, 0.695,
           anomalies=long(60, "the rare level slice moved opposite to the aggregate with a two point gap on the frozen split"))
    sub_ok(d, out)
    out = nx(d, "conclude")
    # the eval flagged an anomaly: conclude must mine it into the ledger (or waive)
    w_conclude(d, out, n19)
    sub_rej(d, out, "OUTCOME_OBSERVATIONS_MISSING")
    w_conclude(d, out, n19, observations=[{
        "statement": long(35, "the rare level slice moves opposite to the aggregate auc"),
        "where": "eval slice: rare price levels",
        "measurement": "slice auc down 0.021 while aggregate up 0.002",
        "evidence": f".evo/nodes/{n19}/eval/EVAL_REPORT.md"}])
    sub_ok(d, out)
    obs = eutil.read_jsonl(d.repo / ".evo/evidence/OBSERVATIONS.jsonl")
    ok(len(obs) == 1 and obs[0]["id"] == "OB001" and obs[0]["node"] == n19,
       f"observation mined into the phenomenon ledger: {[o.get('id') for o in obs]}")
    ok(len(d.events("observation_recorded")) == 1, "observation event recorded")
    node = d.node(n19)
    ok(node["verdict"] == "promising", f"L4 root at parity concludes promising: {node['verdict']}")
    # Parity is not a loophole around the resource contract.  Recompute the
    # assessment with one realized axis outside its frozen cap: the same root
    # must cease to be promising even though its result cells are unchanged.
    store, st, graph = d.store(), d.state(), d.graph()
    ctx = evalid.Ctx(store, st, store.load_config(), graph, store.load_artifacts())
    metrics_path = next(row["path"] for row in node["eval_seal"]["artifacts"]
                        if row["role"] == "normalized_metrics")
    over_budget = json.loads((d.repo / metrics_path).read_text(encoding="utf-8"))
    axis = next(iter(over_budget["_effect_resources"]))
    over_budget["_effect_resources"][axis]["upper"] = 1.0e30
    resource_failed = evalid.computed_assessment(ctx, node, over_budget)
    ok(resource_failed["effect_contract"]["resources"]["status"] == "failed"
       and resource_failed["verdict"] != "promising",
       "a parity root with failed realized resources cannot conclude promising")
    guardrail_uncertain = json.loads((d.repo / metrics_path).read_text(encoding="utf-8"))
    guardrail_uncertain["latency_ms"] = {
        "value": 100.0, "uncertainty": {"lower": 50.0, "upper": 150.0}}
    guardrail_assessment = evalid.computed_assessment(ctx, node, guardrail_uncertain)
    ok(guardrail_assessment["cells"]["C3"]["status"] == "uncertain"
       and guardrail_assessment["verdict"] != "promising",
       "an unresolved mandatory guardrail cannot be relabeled promising")

    # budgeted_tradeoff can be a valid experimental contract, but a fresh root
    # may not buy baseline parity with an actually larger realized vector and
    # then claim resource-clean first-contact headroom.
    tradeoff_meta = json.loads((d.repo / node["idea_doc"].replace(".md", ".meta.json"))
                               .read_text(encoding="utf-8"))
    baseline_node = next(n for n in graph["nodes"] if n["role"] == "baseline")
    axis = "data_examples"
    ref_upper = baseline_node["effect_resources_realized"][axis]["upper"]
    extra = float(ref_upper) + max(1.0, abs(float(ref_upper)))
    tradeoff_meta["effect_case"]["resources"]["regime"] = "budgeted_tradeoff"
    tradeoff_meta["effect_case"]["resources"]["fixed_axes"] = [
        name for name in eprogram.RESOURCE_AXES if name != axis]
    tradeoff_meta["effect_case"]["resources"]["tradeoff_axes"] = [axis]
    tradeoff_meta["effect_case"]["resources"]["improvement_axes"] = []
    tradeoff_meta["effect_case"]["resources"]["candidate"][axis] = extra
    tradeoff_rel = ".evo/ideas/I_PROMISING_RESOURCE_TEST.meta.json"
    wj(d.repo, tradeoff_rel, tradeoff_meta)
    tradeoff_node = json.loads(json.dumps(node))
    tradeoff_node["idea_doc"] = tradeoff_rel.replace(".meta.json", ".md")
    tradeoff_metrics = json.loads((d.repo / metrics_path).read_text(encoding="utf-8"))
    tradeoff_metrics["_effect_resources"][axis]["lower"] = extra
    tradeoff_metrics["_effect_resources"][axis]["upper"] = extra
    tradeoff_assessment = evalid.computed_assessment(ctx, tradeoff_node, tradeoff_metrics)
    ok(tradeoff_assessment["effect_contract"]["resources"]["status"] == "met"
       and tradeoff_assessment["verdict"] != "promising",
       "baseline parity bought with a realized resource tradeoff is not promising")
    drive_close(d, "R014")
    ok(d.state()["rounds"][-1]["improved"] is False, "R014 flat (promising != frontier move)")
    gm = (d.repo / ".evo/views/GRAPH.md").read_text(encoding="utf-8")
    ok("classDef promising" in gm, "mermaid carries the promising class")
    d.doctor_clean("after R014")


def run_r15(d):
    section("R015: formal moonshot (min cycles) + hybrid of variant-of-hybrid x PROMISING root -> DONE")
    open_round(d, "R015", [
        {"name": "moon2", "intent": "moonshot", "min_level": 4, "parents": []},
        {"name": "hyb4", "intent": "hybrid", "min_level": 2, "parents": ["N018", "N019", "N006"]},
    ])
    evidence_refresh(d)

    m2 = d.lane_by_name("moon2")["id"]
    # Both constructive lanes must freeze candidate programs before either one
    # reads candidate-linked literature.  This also exercises scheduler
    # interleaving between two lanes at different stages.
    out = nx(d, "sketch")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("Phenomenon ledger" in bundle and "OB001" in bundle,
       "phenomenon ledger routed into the sketch bundle")
    ok("Idea-space usage watch" in bundle, "homogenization watch block present in the sketch bundle")
    w_sketches(d, out, m2, L4_DIMS_NB, [], reframe=True, theory_rigor="full", obs_ref="OB001")
    sub_ok(d, out)
    h4 = d.lane_by_name("hyb4")["id"]
    out = nx(d, "sketch")
    w_sketches(d, out, h4, L2_DIMS, [], hybrid_parents=["N018", "N019"])
    sub_ok(d, out)
    out = nx(d, "deep_read")
    mech = w_mech_cards(d, m2, 4, ["E001", "E002", "E005", "E004"])
    sub_ok(d, out)
    out = nx(d, "tournament")
    w_tournament(d, out, m2, "K1", leverage=True)
    sub_ok(d, out)
    out = nx(d, "pose")
    w_problem(d, out, bad="no_sym_want")
    sub_rej(d, out, "POSE_WANT_SYMBOLS")
    w_problem(d, out)
    sub_ok(d, out)
    out = nx(d, "theorize")
    # A full-rigor lane must ship the script at all.
    w_theory(d, out, m2, parent_ref="baseline", moonshot=True, formal=True, bad="toy_missing")
    sub_rej(d, out, "THEORY_TOY_MISSING")
    w_theory(d, out, m2, parent_ref="baseline", moonshot=True, formal=True)
    sub_ok(d, out)
    out = nx(d, "challenge")
    # FORMALIZE cannot target a lane already on the ladder
    w_challenge(d, out, m2, "FORMALIZE", formal=True)
    sub_rej(d, out, "CHALLENGE_ALREADY_FORMAL")
    w_challenge(d, out, m2, "REVISE", formal=True)
    sub_ok(d, out)
    prev_ch = f".evo/rounds/R015/lanes/{m2}/CHALLENGE_c1.md"
    out = nx(d, "theorize")
    w_theory(d, out, m2, parent_ref="baseline", moonshot=True, formal=True, response_from=prev_ch)
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, m2, "PROCEED", formal=True)
    sub_ok(d, out)
    out = nx(d, "mature")
    # Dominance may only name a registered result key.  The old narrative
    w_mature(d, out, m2, mech_ids=mech,
             preds=preds_for(0.760), n_assum=5, deriv_chars=2100, theory=True, formal=True,
             dominance={"metric": "not_a_result", "comparison": ">=", "value": 0.7,
                        "rationale": long(35, "misregistered on an unknown result axis to exercise the guard")})
    sub_rej(d, out, "IDEA_DOMINANCE_METRIC")
    # good version: assumption A1 grounded in the mined ledger observation
    w_mature(d, out, m2, mech_ids=mech,
             preds=preds_for(0.760), n_assum=5, deriv_chars=2100, theory=True, formal=True,
             obs_source="OB001")
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, m2)
    sub_ok(d, out)
    n20 = drive_plan(d, m2, role="root", code_parent="N001", stages=[
        stage("train", uri="oss://bkt/user/moon2-train/checkpoint.zip", key="train|moon2")])
    ok(n20 == "N020", f"moon2 root: {n20}")
    run20 = drive_node_to_training(d, n20, bridge=False, job="job-20")

    # hyb4 pipelined while moon2 trains: variant-of-hybrid x PROMISING L4 root + platform
    lid2, mech2 = drive_lane_to_plan(d, "hyb4", dims=L2_DIMS, mech_papers=("E003", "E005"),
                                     hybrid_parents=["N018", "N019"])
    drive_mature_redteam(d, lid2, mech_ids=mech2,
                         score=0.752, hybrid=True)
    n21 = drive_plan(d, lid2, role="hybrid", code_parent="N018", stages=[
        stage("train", uri="oss://bkt/user/hyb4-train/adapter.zip", key="train|hyb4",
              produces_kind="adapter")])
    node = d.node(n21)
    ok(node["parents"] == ["N018", "N019", "N006"] and node["code_parent"] == "N018",
       f"hybrid over a promising root: {node['parents']}")
    out = nx(d, "implement")
    do_implement(d, out, n21)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n21)["status"] == "pass", "N021 smoke")
    sub_ok(d, out)
    out = nx(d, "stage_launch")
    w_launch(d, out, "train", job="job-21")
    sub_ok(d, out)
    run21 = last_run(d)["id"]
    ok(len(d.running()) == 2, "moonshot and hybrid training in parallel")

    nx(d, "stage_watch")
    finish_run(d, run20, "workareas/n020/train_metrics_train.json")
    out = nx(d, "evaluate")
    ok(d.state()["tasks"][-1]["subject"]["node"] == n20, "N020 evaluated while N021 trains")
    # v9: a registered mechanism probe must be MEASURED in the eval report
    w_eval(d, out, n20, 0.760, bad="no_mech_section")
    sub_rej(d, out, "EVAL_MECHANISM")
    w_eval(d, out, n20, 0.760)
    sub_ok(d, out)
    out = nx(d, "conclude")
    # ...and SETTLED at conclusion
    w_conclude(d, out, n20, bad="no_mech_settle")
    sub_rej(d, out, "OUTCOME_MECHANISM")
    w_conclude(d, out, n20)
    sub_ok(d, out)
    ok(d.node(n20)["verdict"] == "improved", "moon2 improved")

    nx(d, "stage_watch")
    finish_run(d, run21, "workareas/n021/train_metrics_train.json")
    out = nx(d, "evaluate")
    w_eval(d, out, n21, 0.752)
    sub_ok(d, out)
    out = nx(d, "conclude")
    # v9: an observation without evidence is an anecdote, not a ledger entry
    w_conclude(d, out, n21, observations=[{
        "statement": long(35, "the adapter merge shows a loss spike at stage start"),
        "where": "train stage: first 50 steps",
        "measurement": "loss spikes to 2.4 then recovers by step 60", "evidence": ""}])
    sub_rej(d, out, "OUTCOME_OBSERVATION_EVIDENCE")
    w_conclude(d, out, n21, observations=[{
        "statement": long(35, "the adapter merge shows a loss spike at stage start"),
        "where": "train stage: first 50 steps",
        "measurement": "loss spikes to 2.4 then recovers by step 60",
        "evidence": "workareas/n021/train_metrics_train.json"}])
    sub_ok(d, out)
    ok(d.node(n21)["verdict"] == "improved", "hyb4 improved over its best model parent")
    ok(any(a["kind"] == "adapter" for a in d.reg()["artifacts"]),
       "LLM-era artifact kind (adapter) registered and registry-valid")
    drive_close(d, "R015")
    gens = egraph.compute_generations(d.graph())
    ok(gens["N021"] == max(gens["N018"], gens["N019"]) + 1, f"hyb4 generation: {gens['N021']}")


def core_palette_binding_adversarial_checks(d, lane_id):
    """The core-synthesis projection is one active, indivisible contract.

    These attacks are deliberately made after the engine has frozen the
    palette but before an agent sees the sketch task.  A plain content seal is
    not enough here: the state fields, anonymous palette, audit-only
    provenance, and their semantic bijection must still describe the same
    projection.  Every attack is restored before the main round continues.
    """
    import edoctor

    section("core-synthesis palette: active binding adversarial checks")
    original_state = d.state()
    original_lane = next(row for row in original_state["lanes"] if row["id"] == lane_id)
    palette_rel = str(original_lane.get("core_palette_path") or "")
    provenance_rel = str(original_lane.get("core_palette_provenance_path") or "")
    palette_path = d.repo / palette_rel
    provenance_path = d.repo / provenance_rel
    original_palette = json.loads(palette_path.read_text(encoding="utf-8"))
    original_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    original_seal = json.loads(json.dumps(original_lane.get("core_palette_seal")))

    ok(original_lane.get("reading_done") is True
       and palette_rel and provenance_rel and original_lane.get("core_palette_digest")
       and isinstance(original_seal, dict),
       "accepted core-synthesis reading freezes all four active palette bindings")
    ok(not eseal.verify(d.repo, original_seal, label=f"lane {lane_id} core palette"),
       "the unmodified joint palette/provenance seal verifies before adversarial checks")

    def write_state(state):
        wj(d.repo, ".evo/state.json", state)

    def lane_in(state):
        return next(row for row in state["lanes"] if row["id"] == lane_id)

    def assert_next_and_doctor_block(state, expected_codes, label):
        """Require both the hot scheduler and the full audit to fail closed."""
        expected_codes = tuple(expected_codes)
        try:
            write_state(state)
            scheduler_error = ""
            try:
                d.next()
            except SystemExit as exc:
                scheduler_error = str(exc)
            problems, _ = edoctor.diagnose(d.store(), fix=False)
            ok(any(code in scheduler_error for code in expected_codes),
               f"scheduler rejects {label} with {expected_codes}: {scheduler_error}")
            ok(any(any(code in problem for code in expected_codes) for problem in problems),
               f"doctor rejects {label} with {expected_codes}: {problems}")
        finally:
            write_state(original_state)

    # reading_done must not become an escape hatch: deleting every active
    # binding is corruption, not a legitimate pre-projection state.
    missing = json.loads(json.dumps(original_state))
    missing_lane = lane_in(missing)
    for field in ("core_palette_path", "core_palette_digest",
                  "core_palette_provenance_path", "core_palette_seal"):
        missing_lane[field] = None
    assert_next_and_doctor_block(
        missing, ("CORE_PALETTE_ACTIVE_MISSING",),
        "reading_done lane with all palette bindings erased")

    # Pointing state at another internally well-formed palette while retaining
    # the old seal used to pass digest-only checks.  Reverse the list so the
    # alternate JSON has a distinct digest without changing its CP membership.
    alt_rel = palette_rel.rsplit("/", 1)[0] + "/CORE_PALETTE_ALT.json"
    alt_path = d.repo / alt_rel
    alternate = json.loads(json.dumps(original_palette))
    alternate["cores"] = list(reversed(alternate.get("cores") or []))
    try:
        wj(d.repo, alt_rel, alternate)
        redirected = json.loads(json.dumps(original_state))
        redirected_lane = lane_in(redirected)
        redirected_lane["core_palette_path"] = alt_rel
        redirected_lane["core_palette_digest"] = file_digest(alt_path)
        # Deliberately retain the old joint seal.  Its own bytes still verify;
        # what is broken is the active state<->seal binding.
        ok(not eseal.verify(d.repo, redirected_lane["core_palette_seal"],
                            label=f"lane {lane_id} redirected palette"),
           "the stale joint seal remains cryptographically valid during the ALT-path attack")
        assert_next_and_doctor_block(
            redirected, ("SEAL_BINDING_PATH", "CORE_PALETTE_PATH"),
            "ALT palette path/digest under the unchanged old seal")
    finally:
        alt_path.unlink(missing_ok=True)
        write_state(original_state)

    # Re-sealing corrupted provenance must not bless it.  Break both the CP id
    # and source-fact digest mapping, then create a fresh, cryptographically
    # valid joint seal around those bad bytes.
    bad_snapshot_paths = []
    try:
        corrupted = json.loads(json.dumps(original_provenance))
        sources = corrupted.get("sources") or []
        ok(bool(sources), "core palette provenance contains at least one CP mapping")
        sources[0]["core_id"] = "CP999"
        sources[0]["source_fact_digest"] = "0" * 64
        wj(d.repo, provenance_rel, corrupted)
        resealed = eseal.create(
            d.repo,
            [("anonymous_core_palette", palette_rel),
             ("audit_only_core_provenance", provenance_rel)],
            revision=int(original_seal.get("revision") or 1) + 1)
        original_snapshots = {str(row.get("snapshot") or "")
                              for row in (original_seal.get("artifacts") or [])}
        bad_snapshot_paths = [d.repo / str(row.get("snapshot"))
                              for row in (resealed.get("artifacts") or [])
                              if str(row.get("snapshot") or "") not in original_snapshots]
        ok(not eseal.verify(d.repo, resealed, label=f"lane {lane_id} resealed bad provenance"),
           "the corrupted provenance attack uses a fresh internally valid content seal")
        bad_mapping = json.loads(json.dumps(original_state))
        lane_in(bad_mapping)["core_palette_seal"] = resealed
        assert_next_and_doctor_block(
            bad_mapping,
            ("CORE_PALETTE_BIJECTION", "CORE_PALETTE_SOURCE_DRIFT",
             "CORE_PALETTE_PROVENANCE_DRIFT"),
            "re-sealed provenance with a false CP/source-digest mapping")
    finally:
        wj(d.repo, provenance_rel, original_provenance)
        write_state(original_state)
        for path in bad_snapshot_paths:
            path.unlink(missing_ok=True)

    ok(not eseal.verify(d.repo, d.lane(lane_id)["core_palette_seal"],
                        label=f"lane {lane_id} restored core palette"),
       "palette state, files, and seal are fully restored after every attack")


def core_program_upstream_adversarial_check(d, lane_id):
    """A core-synthesis program seal must inherit its exact palette seal."""
    import edoctor

    section("core-synthesis program: required palette-upstream adversarial check")
    original_state = d.state()
    original_lane = next(row for row in original_state["lanes"] if row["id"] == lane_id)
    palette_digest = str((original_lane.get("core_palette_seal") or {}).get("digest") or "")
    program_seal = original_lane.get("program_seal") or {}
    ok(palette_digest and palette_digest in (program_seal.get("upstream") or []),
       "accepted core-synthesis program seal names the exact active palette seal upstream")

    # Re-seal the unchanged program bytes while omitting only the palette
    # dependency.  This keeps the forged seal internally valid and isolates
    # required-upstream validation from ordinary SEAL_RECORD_MUTATED checks.
    forged = eseal.create(
        d.repo,
        [("program_set", str(original_lane["sketches_path"]))],
        upstream=[str(x) for x in (program_seal.get("upstream") or [])
                  if str(x) and str(x) != palette_digest],
        revision=int(program_seal.get("revision") or 1))
    ok(not eseal.verify(d.repo, forged, label=f"lane {lane_id} forged program seal"),
       "program seal without the palette edge is cryptographically self-consistent")
    attacked = json.loads(json.dumps(original_state))
    next(row for row in attacked["lanes"] if row["id"] == lane_id)["program_seal"] = forged
    try:
        wj(d.repo, ".evo/state.json", attacked)
        scheduler_error = ""
        try:
            d.next()
        except SystemExit as exc:
            scheduler_error = str(exc)
        problems, _ = edoctor.diagnose(d.store(), fix=False)
        ok("CORE_PALETTE_REQUIRED_UPSTREAM" in scheduler_error,
           f"scheduler rejects a program seal missing its palette edge: {scheduler_error}")
        ok(any("CORE_PALETTE_REQUIRED_UPSTREAM" in problem for problem in problems),
           f"doctor rejects a program seal missing its palette edge: {problems}")
    finally:
        wj(d.repo, ".evo/state.json", original_state)

    ok(d.lane(lane_id)["program_seal"] == program_seal,
       "the accepted program seal is restored after the missing-upstream attack")


def run_r16(d):
    section("R016: CORE-SYNTHESIS BREAKTHROUGH - full-program scope with a partial derivation")
    ok(eprogram.compute_level({"change_scope": "local"}) == 2,
       "scope level is computed from the amount of executable program replaced")
    ok(eprogram.compute_level({"change_scope": "full_program"}) == 4,
       "a complete learning/inference program replacement computes L4")
    open_round(d, "R016", [{"name": "break-m", "intent": "reform", "min_level": 4,
                            "parents": ["N020"], "search_origin": "core_synthesis"}])
    evidence_refresh(d)
    lid = d.lane_by_name("break-m")["id"]
    out = nx(d, "deep_read")
    # Reading depth follows uncertainty/search origin, not a narrative level
    # proxy.  The two reconstructed works are projected by the engine into an
    # anonymous palette before the generator sees any candidate program.
    mech = w_mech_cards(d, lid, 2, ["E001", "E005"])
    sub_ok(d, out)
    lane = d.lane(lid)
    ok(lane["search_origin"] == "core_synthesis" and lane["reading_done"],
       "R016 exercises the real deep-read -> anonymous core-palette transition")
    core_palette_binding_adversarial_checks(d, lid)
    out = nx(d, "sketch")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("CORE_PALETTE.json" in bundle and "CORE_PALETTE_PROVENANCE.json" not in bundle,
       "core generator receives the anonymous palette but not its audit-only paper provenance")
    w_sketches(d, out, lid, L4_DIMS, mech, reframe=True, theory_rigor="partial")
    sub_ok(d, out)
    core_program_upstream_adversarial_check(d, lid)
    out = nx(d, "tournament")
    w_tournament(d, out, lid, "K1", leverage=True)
    sub_ok(d, out)
    lane = d.lane(lid)
    ok(lane["formal"] is True and lane["formal_kind"] == "partial" and lane["status"] == "pose",
       f"partial triage enters the ladder without arming the toy check: {lane['status']}")
    out = nx(d, "pose")
    w_problem(d, out)
    sub_ok(d, out)
    out = nx(d, "theorize")
    # partial ladder: no TOY_CHECK.py duty; kinship = component (inherits from N020)
    w_theory(d, out, lid, parent_ref="N020", moonshot=True, formal=True, relation="component")
    sub_ok(d, out)
    out = nx(d, "challenge")
    # The partial derivation voluntarily takes a revision cycle; scope alone
    # does not manufacture a formal-rigor quota.
    w_challenge(d, out, lid, "REVISE", formal=True)
    sub_ok(d, out)
    prev_ch = f".evo/rounds/R016/lanes/{lid}/CHALLENGE_c1.md"
    out = nx(d, "theorize")
    w_theory(d, out, lid, parent_ref="N020", moonshot=True, formal=True, relation="component",
             response_from=prev_ch)
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, lid, "PROCEED", formal=True)
    sub_ok(d, out)
    out = nx(d, "mature")
    w_mature(d, out, lid, 
             mech_ids=mech, preds=preds_for(0.768), n_assum=4, deriv_chars=1300,
             theory=True, formal=True)
    sub_ok(d, out)
    out = nx(d, "red_team")
    w_red_team(d, out, lid)
    sub_ok(d, out)
    n22 = drive_plan(d, lid, role="variant", code_parent="N020", stages=[
        stage("train", uri="oss://bkt/user/break-m-train/checkpoint.zip", key="train|break-m")])
    ok(n22 == "N022" and d.node(n22)["role"] == "variant" and int(d.node(n22)["level"]) == 4,
       f"breakthrough reform node: {n22} L{d.node(n22)['level']} (single parent, L4)")
    run22 = drive_node_to_training(d, n22, job="job-22")
    drive_watch_finish(d, run22, n22, "train", probe_value=0.5)
    out = nx(d, "evaluate")
    # v9.2 scaling is an after-positive-signal follow-up node: this primary
    # evaluation must NOT pretend those training arms already ran.
    w_eval(d, out, n22, 0.768, bad="no_scaling_section")
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, n22, bad="no_scaling_settle")
    sub_rej(d, out, "OUTCOME_SCALING")
    # mechanism REFUTED while the metric improved: legal, and recorded as a warning
    w_conclude(d, out, n22, mech_status="refuted")
    sub_ok(d, out)
    ok(d.node(n22)["verdict"] == "improved", "breakthrough reform improved")
    oc = json.loads((d.repo / f".evo/nodes/{n22}/OUTCOME.json").read_text(encoding="utf-8"))
    ok(oc["mechanism"]["status"] == "refuted",
       "an improved node may carry a REFUTED mechanism - the gain came from elsewhere and the graph records it")
    drive_close(d, "R016")
    d.doctor_clean("after R016")


def run_r17(d):
    section("R017: refuted mechanism may feed a newly claimed hybrid, not direct exploit")
    open_round(d, "R017", [{"name": "hyb5", "intent": "hybrid", "min_level": 2,
                            "parents": ["N010", "N022"]}])
    evidence_refresh(d)
    lid, mech = drive_lane_to_plan(d, "hyb5", dims=L2_DIMS, mech_papers=("E004", "E005"),
                                   hybrid_parents=["N010", "N022"])
    drive_mature_redteam(d, lid, mech_ids=mech,
                         score=0.772, hybrid=True)
    n23 = drive_plan(d, lid, role="hybrid", code_parent="N022", stages=[
        stage("train", uri="oss://bkt/user/hyb5-train/checkpoint.zip", key="train|hyb5")])
    node = d.node(n23)
    ok(n23 == "N023" and node["parents"] == ["N010", "N022"],
       f"hybrid inherits from the dominant node: {node['parents']}")
    run23 = drive_node_to_training(d, n23, job="job-23")
    drive_watch_finish(d, run23, n23, "train")
    drive_eval_conclude(d, n23, 0.772, logloss=0.6)
    ok(d.node(n23)["verdict"] == "tradeoff",
       "hyb5 gains ranking quality but loses the dominant parent's calibration advantage")
    drive_close(d, "R017")
    gens = egraph.compute_generations(d.graph())
    ok(gens["N023"] == max(gens["N010"], gens["N022"]) + 1, f"hyb5 generation: {gens['N023']}")
    d.doctor_clean("after R017")


def run_r18(d):
    section("R018: scientific stagnation forces a fresh full-program moonshot -> DONE")
    out = nx(d, "open_round")
    # N022 improved but its registered mechanism was refuted: direct exploit
    # cannot inherit that scientific claim unchanged.
    w_portfolio(d, out, "R018", [exploit_lane("last-e", "N022", focus="D1")])
    sub_rej(d, out, "PORTFOLIO_EXPLOIT_OFF_FRONTIER")
    # D1 was last served in R013 (window R014-R017); a frontier-valid exploit
    # still fails both focus and the now-active paradigm-reform duty.
    w_portfolio(d, out, "R018", [exploit_lane("last-e", "N020")])
    sub_rej(d, out, "PORTFOLIO_FOCUS_NEGLECTED")
    w_portfolio(d, out, "R018", [{"name": "last-e", "intent": "moonshot",
                                  "min_level": 4, "parents": [], "focus": "D1"}])
    sub_ok(d, out)
    evidence_refresh(d)
    lid, mech = drive_lane_to_plan(d, "last-e", dims=L4_DIMS_NB,
                                   mech_papers=("E001", "E002", "E004", "E005"),
                                   deep_n=4, reframe=True,
                                   theory_steps=[("theorize", {"parent_ref": "baseline"}),
                                                 ("challenge", {"verdict": "PROCEED"})])
    # The final scientific move carries a measurable load-bearing channel;
    # textual feasibility waivers are tested separately and cannot promote.
    drive_mature_redteam(d, lid, mech_ids=mech,
                         score=0.772, waiver=False)
    n24 = drive_plan(d, lid, role="root", code_parent="N001", stages=[
        stage("train", uri="oss://bkt/user/last-e-train/checkpoint.zip", key="train|last-e")])
    run24 = drive_node_to_training(d, n24, job="job-24")
    drive_watch_finish(d, run24, n24, "train")
    drive_eval_conclude(d, n24, 0.772)
    ok(d.node(n24)["verdict"] == "improved"
       and d.node(n24)["scientific_promotion_status"] == "met",
       "fresh full-program gain clears the scientific frontier after the stagnation reset")
    run_instrumental(d)
    drive_close(d, "R018")

    out = d.next()
    ok(out["kind"] == "done", f"rounds_max reached -> DONE: {out}")
    ok(d.state()["phase"] == "done", "phase done")


def dash_data(d):
    """Parse the JSON snapshot embedded in DASHBOARD.html (the user's live view)."""
    p = d.repo / ".evo/views/DASHBOARD.html"
    ok(p.exists(), "DASHBOARD.html rendered")
    h = p.read_text(encoding="utf-8")
    ok("@@" not in h, "dashboard has no unexpanded template tokens")
    ok("</html>" in h and "<svg id=\"cv\">" in h, "dashboard html is complete")
    m = re.search(r"const DATA = (.*); /\*END-DATA\*/", h)
    ok(m is not None, "dashboard embeds the DATA snapshot")
    return json.loads(m.group(1))


def frontier_mode_view_asserts(d, cfg):
    """Separate the two frontier semantics with a tiny in-memory counterexample."""
    equal_resources = {axis: {"lower": 1.0, "upper": 1.0}
                       for axis in eprogram.RESOURCE_AXES}

    def node(nid, *, auc, logloss, verdict, promotion, parents=()):
        return {
            "id": nid, "title": nid, "role": "baseline" if not parents else "variant",
            "experiment_purpose": "candidate", "parents": list(parents), "level": 0,
            "status": "concluded", "verdict": verdict, "retire_reason": None,
            "scores": {"auc": auc, "logloss": logloss, "latency_ms": 100.0},
            "score_evidence": {"auc": auc, "logloss": logloss, "latency_ms": 100.0},
            "scientific_promotion_status": promotion,
            "effect_resources_realized": json.loads(json.dumps(equal_resources)),
        }

    graph = {"nodes": [
        node("X001", auc=.70, logloss=.60, verdict="baseline", promotion=None),
        node("X002", auc=.75, logloss=.55, verdict="tradeoff", promotion="met",
             parents=("X001",)),
        node("X003", auc=.80, logloss=.58, verdict="improved", promotion="blocked",
             parents=("X001",)),
    ]}
    expected_performance = ["X003", "X002"]
    snapshots = {}
    for mode in ("research", "engineering"):
        mode_cfg = json.loads(json.dumps(cfg))
        mode_cfg.setdefault("project", {})["mode"] = mode
        snapshots[mode] = edash._data(d.store(), graph, mode_cfg, d.state(), {"artifacts": []})

    research = snapshots["research"]
    engineering = snapshots["engineering"]
    ok(research["frontiers"] == {
        "active": "scientific", "inheritance": ["X002"], "scientific": ["X002"],
        "performance": expected_performance, "origin": "X001", "origin_floor": False,
    }, f"research view separates scientific inheritance from performance: {research['frontiers']}")
    ok(engineering["frontiers"] == {
        "active": "performance", "inheritance": expected_performance, "scientific": [],
        "performance": expected_performance, "origin": "X001", "origin_floor": False,
    }, f"engineering view inherits directly from performance: {engineering['frontiers']}")
    # The origin is a floor, not a peer: it holds inheritance only while nothing
    # else is legal, and hands it over the moment one claim settles.
    unsettled = json.loads(json.dumps(graph))
    for row in unsettled["nodes"]:
        if row["id"] != "X001":
            row["scientific_promotion_status"] = "pending_evidence"
    floor_cfg = json.loads(json.dumps(cfg))
    floor_cfg.setdefault("project", {})["mode"] = "research"
    floor = edash._data(d.store(), unsettled, floor_cfg, d.state(), {"artifacts": []})
    ok(floor["frontiers"]["inheritance"] == ["X001"] and floor["frontiers"]["origin_floor"] is True
       and floor["frontiers"]["performance"] == expected_performance,
       f"with nothing settled the origin is the announced floor: {floor['frontiers']}")
    research_nodes = {n["id"]: n["frontiers"] for n in research["nodes"]}
    engineering_nodes = {n["id"]: n["frontiers"] for n in engineering["nodes"]}
    ok(research_nodes["X002"] == {"inheritance": True, "scientific": True, "performance": True}
       and research_nodes["X003"] == {
           "inheritance": False, "scientific": False, "performance": True},
       f"research node membership preserves a useful claim-blocked result: {research_nodes}")
    ok(all(bits["scientific"] is False for bits in engineering_nodes.values())
       and {nid for nid, bits in engineering_nodes.items() if bits["inheritance"]}
       == set(expected_performance),
       f"engineering node membership follows its active performance frontier: {engineering_nodes}")


def view_asserts(d, *, nodes, rounds_closed, primary="auc"):
    data = dash_data(d)
    html = (d.repo / ".evo/views/DASHBOARD.html").read_text(encoding="utf-8")
    cfg = project_cfg(d)
    graph = d.graph()
    state = d.state()
    marker_html = edash._fill_template(
        "project @@DATA@@ / @@TITLE@@",
        '{"literal":"@@TITLE@@ / @@DATA@@"}')
    ok("<title>project @@DATA@@ / @@TITLE@@</title>" in marker_html
       and 'const DATA = {"literal":"@@TITLE@@ / @@DATA@@"}; /*END-DATA*/' in marker_html
       and marker_html.count('const DATA = ') == 1,
       "dashboard placeholders expand once even when user data contains the other marker")
    ok("mechanism_contract" not in edash._assessment_view({}),
       "an absent mechanism contract is not synthesized into an unknown frontend result")
    focus_cfg = json.loads(json.dumps(cfg))
    focus_cfg["project"]["focus_directions"] = [
        {"id": "D9", "text": "test a user-prioritized structural direction without binding the whole portfolio"},
        {"id": "D10", "text": "test a second user direction while preserving independent discovery lanes"},
    ]
    focus_cfg["policy"]["focus_share_max"] = 0.5
    focus_view = edash._focus_view(focus_cfg, {
        "current_round": "RX",
        "lanes": [
            {"id": "LX1", "round": "RX", "focus": "D9"},
            {"id": "LX2", "round": "RX", "focus": None},
            {"id": "LX3", "round": "RW", "focus": "D9"},
            {"id": "LX4", "round": "RW", "focus": "D10"},
        ],
    })
    ok(focus_view["share_cap"] == 0.5
       and focus_view["current"] == {"focus_lanes": 1, "all_lanes": 2, "share": 0.5}
       and [(row["id"], row["current_lanes"], row["cumulative_lanes"])
            for row in focus_view["directions"]] == [("D9", 1, 2), ("D10", 0, 1)],
       "dashboard reports configured user bets and actual current/cumulative lane service")
    ok(len(data["nodes"]) == nodes, f"dashboard node count {nodes}: {len(data['nodes'])}")
    ok(len(data["rounds"]) == rounds_closed, f"dashboard round history {rounds_closed}: {len(data['rounds'])}")
    ok(all((row.get("performance_frontier") or {}).get("recorded") is True
           for row in data["rounds"]),
       "every newly closed round freezes observed-performance as well as active-frontier movement")
    ok(data["schema"] == "evo.dashboard.v2", "dashboard publishes the v2 frontend schema")
    threshold_projection = edash._assessment_view({"mechanism_contract": {
        "status": "confirmed", "field": "alignment", "aggregation": "mean",
        "aggregate": 0.91, "comparison": ">=", "threshold": 0.9}})
    ok(threshold_projection["mechanism_contract"]["threshold"] == 0.9
       and "lower" not in threshold_projection["mechanism_contract"],
       "dashboard preserves a one-sided mechanism threshold without inventing between bounds")
    ok(data["project"]["primary"] == primary, "dashboard carries the display result key")
    ok(data["frontier"], "dashboard frontier non-empty")
    ids = {n["id"] for n in data["nodes"]}
    ok(all(e["from"] in ids and e["to"] in ids for e in data["edges"]),
       "dashboard edges resolve to embedded nodes")

    # Facts are the observed capacity authority.  The fixture deliberately has
    # config=1 and facts=2 so this cannot pass through an accidental fallback.
    facts = eutil.read_json(d.repo / ".evo/profile/INFRA_FACTS.json")
    configured_slots = int((cfg.get("infra") or {}).get("max_concurrent_stage_jobs") or 0)
    observed_slots = int(((facts.get("compute") or {}).get("max_concurrent_stage_jobs")) or 0)
    ok((configured_slots, observed_slots) == (1, 2),
       "dashboard slot precedence fixture distinguishes config from reviewed facts")
    expected_slots = {"total": 2, "busy": 0, "free": 2, "source": "infra_facts"}
    ok(data["slots"] == expected_slots
       and data["infrastructure"]["slots"] == expected_slots,
       f"facts-priority slots remain exact in both views: {data['slots']}")

    # The two frontiers answer different questions.  Recompute both from the
    # authoritative graph, then require every node-local membership bit to be
    # exactly the inverse index of the corresponding top-level list.
    expected_inheritance = [n["id"] for n in egraph.frontier(graph, cfg)]
    expected_performance = [n["id"] for n in egraph.performance_frontier(graph, cfg)]
    frontiers = data["frontiers"]
    ok(frontiers["active"] == "scientific"
       and frontiers["inheritance"] == expected_inheritance
       and frontiers["scientific"] == expected_inheritance
       and data["frontier"] == expected_inheritance,
       f"dashboard inheritance frontier matches engine order: {frontiers}")
    ok(frontiers["performance"] == expected_performance,
       f"dashboard performance frontier matches engine order: {frontiers['performance']}")
    for kind, expected in (("inheritance", expected_inheritance),
                           ("performance", expected_performance)):
        members = {n["id"] for n in data["nodes"]
                   if (n.get("frontiers") or {}).get(kind) is True}
        ok(members == set(expected) and set(expected) <= ids,
           f"dashboard {kind} frontier list and node membership agree: {members}")
    frontier_mode_view_asserts(d, cfg)

    fr_set = set(expected_inheritance)
    ok(all(n["verdict"] in ("improved", "specialist", "tradeoff", "dominant", "promising", "baseline")
           for n in data["nodes"] if n["id"] in fr_set),
       "dashboard frontier nodes carry a Pareto-eligible verdict")

    # The frontend contract is keyed rather than positional.  Pin the fixture's
    # D/T/C/G mapping exactly and separately prove all cross-references resolve.
    contract = data["evaluation_contract"]
    expected_order = {
        "metrics": ["auc", "logloss", "latency"],
        "datasets": ["D1", "D2"],
        "tasks": ["T1", "T2", "T3"],
        "cells": ["C1", "C2", "C3"],
        "groups": ["G1", "G2"],
    }
    ok(contract["order"] == expected_order, f"dashboard contract order is exact: {contract['order']}")
    dataset_map = {key: (value.get("id"), value.get("name"))
                   for key, value in contract["datasets"].items()}
    task_map = {key: (value.get("id"), value.get("name"))
                for key, value in contract["tasks"].items()}
    cell_map = {key: (value.get("id"), value.get("dataset"), value.get("task"),
                      value.get("metric"), value.get("result_key"), value.get("role"),
                      value.get("required"))
                for key, value in contract["cells"].items()}
    group_map = {key: (value.get("id"), value.get("name"), tuple(value.get("tasks") or []),
                       value.get("required"))
                 for key, value in contract["groups"].items()}
    ok(dataset_map == {
        "D1": ("D1", "Frozen ranking validation"),
        "D2": ("D2", "Calibration and serving suite"),
    }, f"dashboard D mapping is exact: {dataset_map}")
    ok(task_map == {
        "T1": ("T1", "ranking"),
        "T2": ("T2", "calibration"),
        "T3": ("T3", "serving"),
    }, f"dashboard T mapping is exact: {task_map}")
    ok(cell_map == {
        "C1": ("C1", "D1", "T1", "auc", "auc", "target", True),
        "C2": ("C2", "D2", "T2", "logloss", "logloss", "target", False),
        "C3": ("C3", "D2", "T3", "latency", "latency_ms", "guardrail", True),
    }, f"dashboard C mapping is exact: {cell_map}")
    ok(group_map == {
        "G1": ("G1", "ranking quality", ("T1",), True),
        "G2": ("G2", "calibration quality", ("T2",), False),
    }, f"dashboard G mapping is exact: {group_map}")
    ok(all(cell["dataset"] in contract["datasets"]
           and cell["task"] in contract["tasks"]
           and cell["metric"] in contract["metrics"]
           for cell in contract["cells"].values())
       and all(all(task in contract["tasks"] for task in group["tasks"])
               for group in contract["groups"].values()),
       "dashboard D/T/C/G references are complete")
    display_cell = contract["cells"][contract["display_cell"]]
    ok(data["project"]["display"]["cell"] == contract["display_cell"] == "C1"
       and data["project"]["display"]["result_key"] == display_cell["result_key"] == primary,
       "dashboard display metric resolves through its configured cell")

    assessed = [n for n in data["nodes"] if n["role"] not in ("baseline", "platform")
                and n.get("status") == "concluded" and n.get("verdict")]
    ok(assessed and all((n.get("evaluation") or {}).get("cells") for n in assessed),
       "dashboard exposes per-cell contract assessments for concluded model nodes")

    # Resource totals remain auditable and the HTML only receives the bounded
    # tail of the append-only ledger.
    resources = data["resources"]
    ok(resources["health"] == "healthy"
       and set(resources["units"]) == {"gpu_hours", "wallclock_minutes"},
       f"dashboard exposes both resource units: {resources['units']}")
    ledger = state["resource_ledger"]
    for unit, values in resources["units"].items():
        charged = sum(float((row.get("usage") or {}).get(unit) or 0.0) for row in ledger)
        ok(abs(values["effective_limit"]
               - (values["base_limit"] + values["approved_addition"])) < 1e-9
           and abs(values["available"]
                   - (values["effective_limit"] - values["charged"] - values["reserved"])) < 1e-9
           and abs(values["charged"] - charged) < 1e-9,
           f"dashboard {unit} budget arithmetic and ledger charge reconcile")
    ledger_view = resources["ledger"]
    recent_limit = ledger_view["recent_limit"]
    ok(recent_limit == 24 and ledger_view["count"] == len(ledger)
       and len(ledger_view["recent"]) == min(len(ledger), recent_limit)
       and ledger_view["truncated"] is (len(ledger) > recent_limit),
       f"dashboard ledger count and recent bound are exact: {ledger_view['count']}/{recent_limit}")
    ok([row["id"] for row in ledger_view["recent"]]
       == [row["id"] for row in ledger[-recent_limit:]],
       "dashboard recent resource rows are the authoritative ledger tail")

    # A green badge must mean an active, digest-verified integrated receipt,
    # not merely a process that once exited zero.
    canary = data["infrastructure"]["canary"]
    canary_record = state["infra_canary"]
    receipt = eutil.read_json(d.repo / canary_record["receipt"])
    required_surfaces = list(receipt["required_surfaces"])
    by_kind = {"base": 0, "dataset": 0, "evaluation_dataset": 0, "service": 0}
    for surface in required_surfaces:
        if str(surface).startswith("evaluation-dataset:"):
            by_kind["evaluation_dataset"] += 1
        elif str(surface).startswith("dataset:"):
            by_kind["dataset"] += 1
        elif str(surface).startswith("service:"):
            by_kind["service"] += 1
        else:
            by_kind["base"] += 1
    expected_coverage = {
        "required": len(required_surfaces), "passed": len(required_surfaces),
        "by_kind": by_kind,
    }
    ok(data["infrastructure"]["ready"] is True
       and canary["status"] == "passed"
       and canary["ready"] is True and canary["active"] is True
       and canary["verified"] is True and canary["stale"] is False,
       f"dashboard canary is passed, active and verified: {canary}")
    ok(canary["coverage"] == expected_coverage
       and len(required_surfaces) == expected_coverage["required"]
       and len(set(required_surfaces)) == expected_coverage["required"],
       f"dashboard canary coverage matches the integrated receipt: {canary['coverage']}")

    # Verdicts without a current specimen still need first-class template
    # mappings; otherwise the next specialist silently renders as pending.
    for verdict in ("specialist", "tradeoff"):
        # v12: legend rows carry a third element (the glossary tooltip key) -
        # the pinned invariant is the verdict->color binding, not the arity.
        ok(f"--{verdict}:" in html
           and re.search(rf"\b{verdict}\s*:\s*\"var\(--{verdict}\)\"", html)
           and f'["{verdict}",VC.{verdict}' in html,
           f"dashboard template maps {verdict} through CSS, JS and the legend")

    expected_views = {
        "overview": ("Overview", "Phylogeny &middot; evolution atlas"),
        "evaluation": ("Evaluation", "Evaluation matrix"),
        "resources": ("Resources", "Cumulative project contract"),
        "infrastructure": ("Infrastructure", "Real integrated preflight"),
    }
    for view, (label, copy) in expected_views.items():
        ok(re.search(rf'<button id="tab-{view}"[^>]*data-view="{view}"[^>]*>{label}</button>', html)
           and f'id="view-{view}"' in html and copy in html,
           f"dashboard {view} view keeps its tab, panel and user-facing copy")
    ok("reference evidence" in html and "referenceResult" in html
       and "predicted [" in html and "numeric observations" in html
       and "pre-registered stop audit" in html,
       "dashboard renders auditable candidate/reference, forecast, mechanism and stop evidence")
    ok('role="img" aria-label="No completed round trend yet"' in html
       and 'svg.setAttribute("aria-label"' in html
       # v12.1: the faint label colour was lifted for contrast (#8c8576 -> #9c9586);
       # the pinned invariant is a dedicated legible label colour, not its literal value.
       and re.search(r"--faint:#[0-9a-fA-F]{6}", html) is not None,
       "dashboard gives the round trace a screen-reader summary and keeps small labels legible")
    ok('esc(DATA.project.primary||"result")' in html
       and 'esc(DATA.project.primary||"")' in html,
       "dashboard escapes the configured result key before either innerHTML insertion")
    ok("user-focus lanes" in html and "FOCUS_BY_ID" in html
       and 'kv("user focus"' in html,
       "dashboard makes configured focus directions and actual lane allocation visible")

    # Prove that source-side secrets/commands exist, then prove the rendered
    # document does not carry them.  This makes the negative checks non-vacuous.
    infra_sentinels = [
        facts["compute"]["submit_pattern"],
        facts["compute"]["status_cmd"],
        facts["compute"]["logs_cmd"],
        facts["artifact_store"]["uri_template"],
        *[dataset["uri"] for dataset in facts["data"]["datasets"]],
    ]
    canary_plan = eutil.read_json(d.repo / canary_record["plan_path"])
    ok(all(infra_sentinels) and canary_plan["canary"]["command"]
       and receipt["nonce"] and "LOCAL_CANARY_ADAPTER.py" in canary_plan["canary"]["command"],
       "privacy sentinels are present in their authoritative source artifacts")
    ok(all(sentinel not in html for sentinel in infra_sentinels),
       "dashboard HTML excludes sensitive infrastructure commands and URIs")
    ok("LOCAL_CANARY_ADAPTER.py" not in html and receipt["nonce"] not in html,
       "dashboard HTML excludes the canary command and nonce")
    ok("probe_eval.py" not in html
       and all("command" not in (node.get("probe_execution") or {})
               for node in data["nodes"]),
       "dashboard HTML and probe snapshots exclude probe commands")

    ok("preset=" in data["tempo"], "dashboard tempo line present")
    gm = (d.repo / ".evo/views/GRAPH.md").read_text(encoding="utf-8")
    ok("classDef improved" in gm and "classDef retired" in gm, "GRAPH.md mermaid classes")
    ok("class " in gm and "frontier" in gm, "GRAPH.md frontier class assignment")
    ok("DASHBOARD.html" in gm, "GRAPH.md points at the interactive view")


def final_asserts(d):
    section("final invariants (main run)")
    g = d.graph()
    roles = {}
    for n in g["nodes"]:
        roles[n["role"]] = roles.get(n["role"], 0) + 1
    ok(len(g["nodes"]) == 26,  # 24 scientific + 1 probe + 1 maintenance (R018b)
       f"26 nodes built: {len(g['nodes'])}")
    ok(roles == {"baseline": 1, "variant": 15, "hybrid": 4, "root": 5, "platform": 1},  # +probe +maintenance
       f"role census: {roles}")
    reg = d.reg()["artifacts"]
    ok(len(reg) == 24, f"24 artifacts registered: {len(reg)}")  # +maintenance train checkpoint
    fr = egraph.frontier(g, project_cfg(d))
    performance_fr = egraph.performance_frontier(g, project_cfg(d))
    performance_best = max(egraph.primary_score(n, "auc") for n in performance_fr)
    scientific_best = max(egraph.primary_score(n, "auc") for n in fr)
    ok(abs(performance_best - 0.772) < 1e-9,
       f"observed performance frontier retains useful 0.772 result: {performance_best}")
    ok(abs(scientific_best - 0.772) < 1e-9,
       f"scientific frontier reaches 0.772 only through a fully settled later claim: {scientific_best}")
    ok(len([r for r in d.state()["rounds"] if r.get("closed_at")]) == 18, "18 rounds closed")
    ok(len(d.events("watch_superseded")) >= 1, "watch supersession exercised")
    ok(len(d.events("artifact_registered")) == 24, "artifact registration events")  # +maintenance
    auto = [e for e in d.events("gate_decided") if e.get("note", "") and "auto-approved" in str(e.get("note"))]
    ok(len(auto) >= 15, f"full_auto auto-approvals: {len(auto)}")
    # v8: the promising root is on the graph, off the frontier, and a legal parent
    n19 = d.node("N019")
    ok(n19["verdict"] == "promising" and n19["id"] not in {n["id"] for n in fr},
       "promising root recorded and not on the frontier")
    ok(any(n["id"] == "N021" and "N019" in n["parents"] for n in g["nodes"]),
       "a hybrid inherits from the promising root")
    ok(len(d.events("lane_formal")) >= 3 and len(d.events("lane_formalize_required")) == 1,
       "formal ladder entered by triage (incl. a 'partial' breakthrough reform) and by FORMALIZE once")
    ok(len(d.events("fidelity_passed")) >= 8, "fidelity audits ran on L3+/heavy nodes")
    # v9: the breakthrough-reform L4 variant exists with a single model parent
    n22 = d.node("N022")
    ok(n22["role"] == "variant" and int(n22["level"]) == 4 and len(n22["parents"]) == 1,
       "breakthrough reform: L4 with inheritance (the VAR/NSA shape) is on the graph")
    ok(n22["verdict"] == "improved"
       and n22["id"] not in {n["id"] for n in fr}
       and n22.get("mechanism_status") == "refuted",
       "refuted mechanism preserves the measured gain in the graph but blocks direct scientific promotion")
    view_asserts(d, nodes=26, rounds_closed=18)
    data = dash_data(d)
    ok(data["counts"]["improved"] == sum(1 for n in g["nodes"] if n.get("verdict") == "improved"),
       "dashboard improved count matches graph")
    ok(any(n["verdict"] == "promising" for n in data["nodes"]), "dashboard carries the promising verdict")
    html = (d.repo / ".evo/views/DASHBOARD.html").read_text(encoding="utf-8")
    ok("--promising" in html and "fitText" in html,
       "dashboard has the promising color and the overlap-fix truncation")
    # v9: dominant verdict + phenomenon ledger + toy checks
    ok("--dominant" in html, "dashboard has the dominant color")
    ok(d.node("N010")["verdict"] == "dominant"
       and any("N010" in (n.get("parents") or []) for n in g["nodes"]),
       "efficiency-dominant node remained a first-class parent until a later node dominated it")
    gm = (d.repo / ".evo/views/GRAPH.md").read_text(encoding="utf-8")
    ok("classDef dominant" in gm, "mermaid carries the dominant class")
    obs = eutil.read_jsonl(d.repo / ".evo/evidence/OBSERVATIONS.jsonl")
    ok([o.get("id") for o in obs] == ["OB001", "OB002", "OB003"],  # OB003: probe product
       f"phenomenon ledger holds the mined anomalies: {[o.get('id') for o in obs]}")
    ok(len(d.events("observation_recorded")) == 3, "observation events recorded")
    toy_files = list((d.repo / ".evo/rounds").glob("*/lanes/*/TOY_CHECK.py"))
    ok(len(toy_files) >= 2, f"toy checks shipped for full-formal lanes: {len(toy_files)}")
    ok(not data["runs"], "no running jobs at the end")
    d.doctor_clean("end of main run")


# --------------------------------------------------------------------------- gated mini-run
def run_mini():
    section("mini-run: gated + copy + ENGINEERING mode + drills + adaptation borrowing + fidelity")
    repo = OUT / "proj_gated"
    if repo.exists():
        rmtree(repo)
    make_repo(repo, with_git=False)
    estore.Store(repo).init("mini", "gated mini evolution")
    d = D(repo)

    out = nx(d, "project_scan")
    w_project_scan(d, out, readiness_mode="needs_preparation")
    sub_ok(d, out)

    # v11.7: preparation runs BEFORE configure - the contract freezes against
    # observed reality. Blocked path: typed blockers ride a gate; supplement
    # -> multi-round retry; evidence-free claims are rejected.
    out = nx(d, "provision")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("wire the frozen validation dataset" in bundle,
       "the scan's preparation worklist rides the provision bundle")
    w_provision(d, out, status="blocked", bad="empty_block")
    sub_rej(d, out, "PROVISION_BLOCKERS")
    w_provision(d, out, status="blocked")
    sub_ok(d, out)
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "provision_blocked", f"blocked preparation raises the user gate: {gate}")
    gcard = (d.repo / gate["card"]).read_text(encoding="utf-8")
    ok("PREPARATION BLOCKED" in gcard and "read access to the exploration table" in gcard
       and "please provide" in gcard, "gate report relays the typed blockers verbatim")
    d.decide(gate["gate"], True, note="granted read access on part=8 and refreshed the runtime token")
    out = nx(d, "provision")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("granted read access" in bundle and "read access to the exploration table" in bundle,
       "retry cycle carries the user's note AND the previous blockers")
    w_provision(d, out, bad="no_metric")
    sub_rej(d, out, "PROVISION_METRIC")
    w_provision(d, out)
    sub_ok(d, out)
    ok("provision" in d.state()["bootstrap_done"], "preparation recorded ready")

    out = nx(d, "configure")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("PROVISION.json" in bundle, "configure freezes against the preparation's observed facts")
    w_config(d, out, autonomy="gated", rounds_max=4, vcs="copy", on_stuck="abandon", mode="")
    sub_rej(d, out, "CONFIG_MODE")
    w_config(d, out, autonomy="gated", rounds_max=4, vcs="copy", on_stuck="abandon",
             mode="engineering")
    sub_ok(d, out)
    out = nx(d, "infra")
    w_infra(d, out)
    sub_ok(d, out)
    out = nx(d, "infra_interview")
    w_interview(d, out)
    sub_ok(d, out)

    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "infra_confirm", f"infra gate presented in gated mode: {gate}")
    gcard = (d.repo / gate["card"]).read_text(encoding="utf-8")
    ok("Report for the user" in gcard and "RELAY the report" in gcard,
       "infra gate card embeds the user report + verbatim relay duty")
    ok("INFRA_REVIEW.md" in gcard, "infra gate report points at the review file")
    d.decide(gate["gate"], False, note="queue name wrong; the quota is four not two")
    out = nx(d, "project_scan")
    bundle = (d.repo / out["bundle"]).read_text(encoding="utf-8")
    ok("queue name wrong" in bundle, "rejection note routed into the redo bundle")
    w_project_scan(d, out)
    sub_ok(d, out)
    out = nx(d, "configure")
    w_config(d, out, autonomy="gated", rounds_max=4, vcs="copy", on_stuck="abandon",
             mode="engineering")
    sub_ok(d, out)
    out = nx(d, "infra")
    w_infra(d, out, service=True)   # a KGQA-style runtime dependency enters the facts
    sub_ok(d, out)
    out = nx(d, "infra_interview")
    w_interview(d, out)
    sub_ok(d, out)
    gate = nx(d, kind="gate")
    d.decide(gate["gate"], True, note="facts confirmed")

    # The integrated canary follows sign-off; omitting a declared service makes
    # the engine-observed run fail, while the real local socket round-trip passes.
    out = nx(d, "infra_drill")
    w_drills(d, out, bad="omit_service")
    sub_rej(d, out, "CANARY_RUN_FAILED")
    w_drills(d, out, services=("kg-endpoint",))
    sub_ok(d, out)

    out = nx(d, "profile")
    w_profile(d, out)
    sub_ok(d, out)
    out = nx(d, "dossier")
    w_dossier(d, out)
    sub_ok(d, out)
    out = nx(d, "rubric")
    w_rubric(d, out)
    sub_ok(d, out)
    out = nx(d, "baseline_spec")
    w_baseline_spec(d, out, "N001", judge={"model": "judge-4-2026-01", "params": {"temperature": 0}},
                    protocol={"opponents": ["ref-model-a-v1", "ref-model-b-v2"],
                              "harness": "arena-v2", "sampling": {"temperature": 0.7, "n": 40}})
    sub_ok(d, out)

    out = nx(d, "smoke")
    ok(d.smoke("N001")["status"] == "pass", "mini baseline smoke")
    sub_ok(d, out)
    out = nx(d, "evaluate")
    w_eval(d, out, "N001", 0.700)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, "N001", baseline=True)
    sub_ok(d, out)

    # R1: reform on baseline, idea gate rejected with retry-stage=theorize
    open_round(d, "R001", [{"name": "ref", "intent": "reform", "min_level": 3, "parents": ["N001"]}])
    out = nx(d, "evidence")
    w_evidence_initial(d)
    sub_ok(d, out)
    lid, mech = drive_lane_to_plan(
        d, "ref", dims=L3_DIMS_NB, leverage=True,
        theory_steps=[("theorize", {"parent_ref": "N001"}), ("challenge", {"verdict": "PROCEED"})])
    # engineering mode: the idea BORROWS the published mechanism and argues the
    # adaptation - no 'difference vs the literature' duty
    drive_mature_redteam(d, lid, mech_ids=mech,
                         score=0.720, theory=True, adapt_only=True)
    rt = [t for t in d.state()["tasks"] if t["type"] == "red_team"][-1]
    rcard = (d.repo / f".evo/tasks/{rt['id']}/CARD.md").read_text(encoding="utf-8")
    ok("ENGINEERING MODE" in rcard, "engineering red-team card carries the borrow-not-duplicate duty")
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "idea_approval", "idea gate in gated mode")
    gcard = (d.repo / gate["card"]).read_text(encoding="utf-8")
    ok("Report for the user" in gcard and "registered prediction" in gcard
       and "implementation scope: L3" in gcard and "M:" in gcard and "T:" in gcard,
       "idea gate report carries independent Scope/M/T and predictions")
    ok("DASHBOARD.html" in gcard, "idea gate report points at the dashboard")
    d.decide(gate["gate"], False, note="deepen the theory first", retry="theorize")
    lane = d.lane(lid)
    ok(lane["status"] == "theorize" and lane["theory_cycle"] == 2, f"retry stage honored: {lane['theory_cycle']}")
    prev_ch = f".evo/rounds/R001/lanes/{lid}/CHALLENGE_c1.md"
    out = nx(d, "theorize")
    w_theory(d, out, lid, parent_ref="N001", response_from=prev_ch)
    sub_ok(d, out)
    out = nx(d, "challenge")
    w_challenge(d, out, lid, "PROCEED")
    sub_ok(d, out)
    drive_mature_redteam(d, lid, mech_ids=mech,
                         score=0.720, theory=True, adapt_only=True)
    gate = nx(d, kind="gate")
    d.decide(gate["gate"], True, note="approved after the deeper theory")

    out = nx(d, "plan_node")
    # judge pinning: an LLM-judge eval must match the baseline's judge exactly
    w_plan(d, out, lid, role="variant", workdir="workareas/n002", code_parent="N001",
           cost="heavy", judge={"model": "judge-5-latest", "params": {"temperature": 0.7}},
           protocol={"opponents": ["ref-model-a-v1"], "harness": "arena-v1"},
           eval_extra={"requires_services": ["vector-db"]},
           stages=[stage("train", uri="oss://bkt/user/mini-ref/checkpoint.zip",
                         key="train|mini-ref")])
    sub_rej(d, out, "SPEC_JUDGE_MISMATCH", "SPEC_PROTOCOL_MISMATCH", "SPEC_REQUIRES_SERVICE")
    w_plan(d, out, lid, role="variant", workdir="workareas/n002", code_parent="N001",
           cost="heavy", judge={"model": "judge-4-2026-01", "params": {"temperature": 0}},
           protocol={"opponents": ["ref-model-a-v1", "ref-model-b-v2"],
                     "harness": "arena-v2", "sampling": {"temperature": 0.7, "n": 40}},
           eval_extra={"requires_services": ["kg-endpoint"]},
           stages=[stage("train", uri="oss://bkt/user/mini-ref/checkpoint.zip",
                         key="train|mini-ref")])
    sub_ok(d, out)
    n2 = d.lane(lid)["node"]
    out = nx(d, "implement")
    do_implement(d, out, n2, git_mode=False)
    sub_ok(d, out)
    out = nx(d, "smoke")
    ok(d.smoke(n2)["status"] == "pass", "mini smoke")
    sub_ok(d, out)
    # L3 + heavy: the fidelity audit stands between the build and the execution gate
    drive_fidelity(d, n2)
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "workflow_approval", "heavy workflow execution gated")
    gcard = (d.repo / gate["card"]).read_text(encoding="utf-8")
    ok("cost class: heavy" in gcard and "stage 'train'" in gcard
       and "1 sequential scheduler job(s)" in gcard
       and "1 standard eval + 0 extra eval arm(s)" in gcard,
       "execution gate report carries stage shape, budget and evidence-arm count")
    d.decide(gate["gate"], True, note="budget approved")
    out = nx(d, "stage_launch")
    w_launch(d, out, "train", mode="completed", metrics_rel="workareas/n002/train_metrics_train.json")
    sub_ok(d, out)
    out = nx(d, "evaluate")
    w_eval(d, out, n2, 0.720)
    sub_ok(d, out)
    out = nx(d, "conclude")
    w_conclude(d, out, n2)
    sub_ok(d, out)
    drive_close(d, "R001")

    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "round_continue", "round gate after R001")
    gcard = (d.repo / gate["card"]).read_text(encoding="utf-8")
    ok("Rounds closed: 1" in gcard and "Tempo: preset=custom" in gcard
       and "First in display order:" in gcard and "Last round's lanes (R001)" in gcard,
       "round_continue report carries history/frontier/lanes/tempo")
    d.decide(gate["gate"], True)

    # R2: lane dies by validation exhaustion (on_stuck=abandon)
    open_round(d, "R002", [exploit_lane("junk", n2)])
    evidence_refresh(d)
    jl = d.lane_by_name("junk")["id"]
    out = nx(d, "deep_read")
    w_mech_cards(d, jl, 2, ["E001", "E005"])
    sub_ok(d, out)
    out = nx(d, "sketch")
    for i in range(3):
        wt(d.repo, out["outputs"][0], "not json at all {")
        r = d.submit(out["task"])
        ok(r["kind"] == "rejected", f"junk sketch rejected {i + 1}")
    ok(r.get("status") == "cancelled", f"on_stuck=abandon cancels the task: {r}")
    ok(d.lane(jl)["status"] == "abandoned", "lane abandoned")
    drive_close(d, "R002")

    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "round_continue", "round gate after R002")

    # ---- mid-run supervision switch (v9): the blessed channel + live effect ----
    evo_cli = PKG / "engine" / "evo.py"

    def autonomy_cli(mode, note=None):
        cmd = [PY, str(evo_cli), "--repo", str(d.repo), "autonomy", mode]
        if note is not None:
            cmd += ["--note", note]
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")

    p = autonomy_cli("full_auto")
    ok(p.returncode != 0 and "--note" in (p.stderr + p.stdout), "switch without a note refused")
    cfgp = d.repo / ".evo/config.json"
    raw = json.loads(cfgp.read_text(encoding="utf-8"))
    ok(raw["policy"]["autonomy"] == "gated", "refused switch left the config untouched")
    raw["budgets"]["rounds_max"] = 0
    cfgp.write_text(json.dumps(raw), encoding="utf-8")
    p = autonomy_cli("full_auto", "go unattended")
    ok(p.returncode != 0 and "CONFIG_FULL_AUTO_ROUNDS" in (p.stderr + p.stdout),
       "full_auto with rounds_max=0 refused (validated before writing)")
    raw["budgets"]["rounds_max"] = 4
    cfgp.write_text(json.dumps(raw), encoding="utf-8")
    p = autonomy_cli("gated", "same mode")
    ok(p.returncode == 0 and "already" in p.stdout, "same-mode switch is a friendly no-op")
    p = autonomy_cli("full_auto", "user wants the rest unattended")
    ok(p.returncode == 0 and "gated -> full_auto" in p.stdout, f"switch accepted: {p.stdout}")
    ok("1 open gate(s)" in p.stdout, "switch names the waiting gate for re-evaluation")
    # the ALREADY-OPEN round gate now auto-approves; R003 opens within the same next()
    out = nx(d, "open_round")
    ev = [e for e in d.events("gate_decided") if "auto-approved" in str(e.get("note") or "")]
    ok(len(ev) >= 1, "open gate auto-approved after the mid-run switch")
    ach = d.events("autonomy_changed")
    ok(len(ach) == 1 and ach[0]["from"] == "gated" and ach[0]["to"] == "full_auto",
       "switch evented with from/to")
    # switch BACK: the next gate must wait for the user again
    p = autonomy_cli("gated", "user wants the wheel back")
    ok(p.returncode == 0, f"reverse switch accepted: {p.stderr}")
    ok(len(d.events("autonomy_changed")) == 2, "reverse switch evented")

    # R003 under restored gating: quick abandon, then the round gate WAITS again
    w_portfolio(d, out, "R003", [exploit_lane("junk2", n2)])
    sub_ok(d, out)
    evidence_refresh(d)
    j2 = d.lane_by_name("junk2")["id"]
    out = nx(d, "deep_read")
    w_mech_cards(d, j2, 2, ["E001", "E005"])
    sub_ok(d, out)
    out = nx(d, "sketch")
    for i in range(3):
        wt(d.repo, out["outputs"][0], "not json at all {")
        r = d.submit(out["task"])
        ok(r["kind"] == "rejected", f"junk2 sketch rejected {i + 1}")
    ok(d.lane(j2)["status"] == "abandoned", "junk2 lane abandoned")
    drive_close(d, "R003")

    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "round_continue",
       "round gate after R003 waits for the user again (gated restored)")
    d.decide(gate["gate"], False, note="stop here")
    out = d.next()
    ok(out["kind"] == "done", f"user stop ends the session: {out}")
    d.doctor_clean("end of mini run")


def run_canary_blocked_gate():
    section("infrastructure canary: full_auto waits on a real blocked run and retries fresh")
    repo = OUT / "proj_canary_blocked"
    if repo.exists():
        rmtree(repo)
    make_repo(repo, with_git=False)
    estore.Store(repo).init("canary-blocked", "full_auto waits for user-owned canary resources")
    d = D(repo)
    out = nx(d, "project_scan")
    w_project_scan(d, out)
    sub_ok(d, out)
    out = nx(d, "configure")
    w_config(d, out, autonomy="full_auto", rounds_max=1, vcs="copy",
             mode="engineering")
    sub_ok(d, out)
    out = nx(d, "infra")
    w_infra(d, out)
    sub_ok(d, out)
    out = nx(d, "infra_interview")
    w_interview(d, out)
    sub_ok(d, out)
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "infra_confirm", "full_auto still requires bootstrap sign-off")
    d.decide(gate["gate"], True, note="bootstrap contract confirmed for unattended run")
    out = nx(d, "infra_drill")
    blocked_task = out["task"]
    receipt = w_drills(d, out, blocked=True)
    ok(receipt and receipt["status"] == "blocked" and receipt["exit"] == 23,
       "engine observed the adapter's real nonzero exit and typed blocker")
    sub_ok(d, out)
    blocked_record = (d.state()["tasks"][-1].get("infra_canary_run") or {})
    blocked_receipt_path = d.repo / blocked_record["receipt"]
    blocked_receipt_text = blocked_receipt_path.read_text(encoding="utf-8")
    altered_blocked_receipt = json.loads(blocked_receipt_text)
    altered_blocked_receipt["blockers"][0]["ask"] = "supply a forged unrelated item to the operator immediately"
    wj(d.repo, blocked_record["receipt"], altered_blocked_receipt)
    try:
        d.next()
        blocked_tamper_rejected = False
    except SystemExit as exc:
        blocked_tamper_rejected = "CANARY_RECEIPT_MUTATED" in str(exc)
    wt(d.repo, blocked_record["receipt"], blocked_receipt_text)
    ok(blocked_tamper_rejected,
       "the user gate refuses to display a blocker whose engine-owned receipt was altered")
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "infra_canary_blocked",
       f"blocked canary opens its user-owned gate even in full_auto: {gate}")
    st = d.state()
    saved_gate = next(g for g in st["gates"] if g["id"] == gate["gate"])
    ok(st["phase"] == "bootstrap" and saved_gate["status"] == "open"
       and "infra_drill" not in st["bootstrap_done"],
       "full_auto neither stops nor certifies bootstrap after a blocked canary")
    again = d.next()
    ok(again["kind"] == "gate" and again["gate"] == gate["gate"],
       "repeated next remains on the same blocked-canary gate without spinning")
    d.decide(gate["gate"], True,
             note="installed the deterministic local canary credential and request a complete rerun")
    retry = nx(d, "infra_drill")
    ok(retry["task"] != blocked_task,
       "approval creates a fresh infra_drill task whose canary will receive a fresh nonce")
    passed = w_drills(d, retry, multi=True)
    ok(passed and passed["status"] == "passed" and passed["nonce"] != receipt["nonce"],
       "approved retry executes a new passed MULTI-COMMAND canary rather than reusing blocked evidence")
    sub_ok(d, retry)
    ok((d.state().get("infra_canary") or {}).get("task") == retry["task"],
       "only the fresh passed retry becomes the active infrastructure authority")


def run_fit_gate():
    section("engine-fit: an out-of-class project stops at the first card with the gap named")
    repo = OUT / "proj_unfit"
    if repo.exists():
        rmtree(repo)
    make_repo(repo, with_git=False)
    estore.Store(repo).init("unfit", "task-class admission verdict is user-owned")
    d = D(repo)
    out = nx(d, "project_scan")
    w_project_scan(d, out, fit={
        "assumptions": [
            {"id": "F0", "verdict": "violated", "evidence": ["README.md"],
             "note": long(45, "the request is a literature survey with no runnable project entity or data source to iterate on"),
             "consequence_if_wrong": long(45, "every later bootstrap step would fail to name a dataset a metric or a runnable entry point")},
            {"id": "F5", "verdict": "holds", "evidence": ["README.md"],
             "note": long(45, "not applicable once F0 fails but judged from the scanned material anyway")},
            {"id": "F6", "verdict": "holds", "evidence": ["README.md"],
             "note": long(45, "not applicable once F0 fails but judged from the scanned material anyway")},
            {"id": "F7", "verdict": "holds", "evidence": ["README.md"],
             "note": long(45, "not applicable once F0 fails but judged from the scanned material anyway")},
        ],
        "overall": "unfit",
    })
    sub_ok(d, out)
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "engine_fit_blocked",
       f"an unfit verdict opens the user-owned admission gate: {gate}")
    gcard = (d.repo / gate["card"]).read_text(encoding="utf-8")
    ok("ENGINE-FIT ASSESSMENT" in gcard and "literature survey" in gcard
       and "consequence" in gcard,
       "the gate report names the violated assumption and its consequence verbatim")
    d.decide(gate["gate"], False, note="agreed - this request is not an evolution project")
    st = d.state()
    ok(st["phase"] == "done" and "engine-fit" in str(st.get("terminal_reason") or ""),
       f"rejecting the admission stops the project with the gap on record: {st.get('terminal_reason')}")


def run_canary_validation_exhaustion():
    section("infrastructure canary: invalid plans exhaust once instead of rebuilding forever")
    repo = OUT / "proj_canary_invalid"
    if repo.exists():
        rmtree(repo)
    make_repo(repo, with_git=False)
    estore.Store(repo).init("canary-invalid", "invalid canary plans terminate deterministically")
    d = D(repo)
    out = nx(d, "project_scan")
    w_project_scan(d, out)
    sub_ok(d, out)
    out = nx(d, "configure")
    w_config(d, out, autonomy="full_auto", rounds_max=1, vcs="copy",
             mode="engineering", on_stuck="abandon")
    sub_ok(d, out)
    out = nx(d, "infra")
    w_infra(d, out)
    sub_ok(d, out)
    out = nx(d, "infra_interview")
    w_interview(d, out)
    sub_ok(d, out)
    gate = nx(d, kind="gate")
    d.decide(gate["gate"], True, note="approve contract for invalid-plan exhaustion test")
    out = nx(d, "infra_drill")
    original_task = out["task"]
    for _ in range(3):
        w_drills(d, out, bad="no_evidence")
        sub_rej(d, out, "CANARY_PLAN_SCHEMA", "CANARY_RUN_MISSING")
    stopped = d.next()
    canary_tasks = [task for task in d.state()["tasks"] if task.get("type") == "infra_drill"]
    ok(stopped["kind"] == "done" and len(canary_tasks) == 1
       and canary_tasks[0]["id"] == original_task,
       "full_auto/on_stuck=abandon stops after one exhausted canary task without a rebuild loop")
    d.doctor_clean("intentional bootstrap termination after invalid canary plans")


def run_canary_runtime_exhaustion():
    section("infrastructure canary: real execution failures have a bounded retry gate")
    repo = OUT / "proj_canary_runtime_fail"
    if repo.exists():
        rmtree(repo)
    make_repo(repo, with_git=False)
    estore.Store(repo).init("canary-runtime-fail", "bound repeated real canary command failures")
    d = D(repo)
    out = nx(d, "project_scan")
    w_project_scan(d, out)
    sub_ok(d, out)
    out = nx(d, "configure")
    w_config(d, out, autonomy="full_auto", rounds_max=1, vcs="copy",
             mode="engineering", on_stuck="ask")
    sub_ok(d, out)
    out = nx(d, "infra")
    w_infra(d, out)
    sub_ok(d, out)
    out = nx(d, "infra_interview")
    w_interview(d, out)
    sub_ok(d, out)
    gate = nx(d, kind="gate")
    d.decide(gate["gate"], True, note="approve contract for runtime-attempt test")
    out = nx(d, "infra_drill")
    for attempt, failure_mode in enumerate(("pass_blockers", "wrong_nonce", "wrong_nonce"), 1):
        failed = w_drills(d, out, bad=failure_mode)
        ok(failed["status"] == "failed" and failed["attempt"] == attempt,
           f"real failed canary execution is counted exactly once: attempt {attempt}")
        if failure_mode == "pass_blockers":
            ok(any("CANARY_PASS_BLOCKERS" in err for err in failed["errors"]),
               "exit-zero observation cannot pass while simultaneously claiming typed blockers")
    stuck = d.store().get_task(d.state(), out["task"])
    ok(stuck["status"] == "stuck" and stuck["infra_canary_attempts"] == 3,
       "third real execution failure exhausts the configured attempt limit")
    gate = nx(d, kind="gate")
    ok(gate["gate_kind"] == "escalation",
       "execution exhaustion pauses at one user-owned escalation even in full_auto")
    d.decide(gate["gate"], True, note="fixed the project canary command and authorize a bounded retry epoch")
    retry = nx(d, "infra_drill")
    reopened = d.store().get_task(d.state(), retry["task"])
    ok(retry["task"] == out["task"] and reopened["infra_canary_attempts"] == 3
       and reopened["infra_canary_failures"] == 0,
       "approval preserves monotonic run identity while opening a fresh bounded failure epoch")
    passed = w_drills(d, retry)
    ok(passed["status"] == "passed" and passed["attempt"] == 4
       and passed["failure_attempt"] == 0,
       "authorized retry uses a fresh nonce and monotonic canary id in the new failure epoch")
    sub_ok(d, retry)


def v91_policy_checks(d):
    """Focused adversarial checks for the v9.2 contracts added on top of the
    18-round choreography. These are read-only against graph/state; scratch
    artifacts live outside the engine-owned idea/node directories."""
    section("v9.2 policy checks: multi-cell claims, diagnosis binding, experiment budgets")
    cfg = project_cfg(d)
    ok(not econfig.validate_config(d.store().load_config()), "completed multi-dataset config remains valid")

    bad = json.loads(json.dumps(cfg))
    bad["evaluation_contract"]["cells"][1]["result_key"] = "auc"
    errs = econfig.validate_config(bad)
    ok(any(e.startswith("CONFIG_EVAL_CELL_1_RESULT_KEY_DUP") for e in errs),
       f"same metric definition across datasets still needs unique result keys: {errs}")
    bad = json.loads(json.dumps(cfg))
    bad["evaluation_contract"]["cells"][1]["task"] = "T999"
    errs = econfig.validate_config(bad)
    ok(any(e.startswith("CONFIG_EVAL_CELL_1_TASK") for e in errs),
       "dataset-task-metric cells reject dangling task relations")
    bad = json.loads(json.dumps(cfg))
    bad["evaluation_contract"]["decision"]["min_target_groups_improved"] = 3
    errs = econfig.validate_config(bad)
    ok(any(e.startswith("CONFIG_EVAL_DECISION_GROUPS_RANGE") for e in errs),
       "breadth requirement cannot exceed the target-bearing group count")
    bad = json.loads(json.dumps(cfg))
    bad["evaluation_contract"]["cells"][0].pop("goal_threshold")
    errs = econfig.validate_config(bad)
    ok(any(e.startswith("CONFIG_EVAL_CELL_0_GOAL_THRESHOLD") for e in errs),
       "absolute SOTA/acceptance threshold versus progress-only is an explicit per-cell decision")
    bad = json.loads(json.dumps(cfg))
    bad["evaluation_contract"]["tasks"].append(
        {"id": "T9", "name": "orphan", "description": "declared task with no evaluation cell",
         "aggregation": "all", "weight": 1.0})
    errs = econfig.validate_config(bad)
    ok(any(e.startswith("CONFIG_EVAL_TASK_UNUSED") for e in errs),
       "declared tasks cannot silently disappear from the decision matrix")

    store, st, graph = d.store(), d.store().load_state(), d.store().load_graph()
    ctx = evalid.Ctx(store, st, store.load_config(), graph, store.load_artifacts())
    effect_lane = d.lane(d.node("N022")["lane"])
    # Diagnosis-specific attacks must use the route that actually owns a
    # frozen H# diagnosis.  N022 deliberately became core_synthesis in R016;
    # treating every invention route as repair would reintroduce the exact
    # route conflation this version removes.
    repair_lane = next(row for row in reversed(st["lanes"])
                       if row.get("search_origin") == "repair"
                       and row.get("diagnosis_path") and row.get("parents"))
    scratch = ".evo/v91_checks"

    # E is a separately computed scientific contract: exact frozen comparator,
    # worthwhile floor, and realized resource receipts all have veto power.
    effect_node = d.node("N022")
    effect_meta = json.loads((d.repo / effect_node["idea_doc"].replace(".md", ".meta.json")).read_text(encoding="utf-8"))
    eval_metrics_rel = next(
        row["path"] for row in effect_node["eval_seal"]["artifacts"]
        if row.get("role") == "normalized_metrics")
    effect_metrics = json.loads((d.repo / eval_metrics_rel).read_text(encoding="utf-8"))
    settled = evalid.effect_contract_assessment(ctx, effect_node, effect_metrics, effect_meta)
    declared_comparator = effect_meta["effect_case"]["comparator_id"]
    resolved_comparator = (next(n["id"] for n in graph["nodes"] if n.get("role") == "baseline")
                           if declared_comparator == "baseline" else declared_comparator)
    ok(settled["status"] == "met"
       and settled["comparator_node"] == resolved_comparator,
       f"E uses the exact declared comparator and clears all frozen floors/resources: {settled}")
    expected_forecasts = {}
    for target_cell in settled["targets"]:
        links = [link for link in effect_meta["effect_case"]["chain"]
                 if link["target_cell"] == target_cell]
        expected_forecasts[target_cell] = (
            max(float(link["expected_delta_interval"][0]) for link in links),
            min(float(link["expected_delta_interval"][1]) for link in links),
        )
    ok(all((row.get("expected_lower"), row.get("expected_upper"))
           == expected_forecasts[target_cell]
           for target_cell, row in settled["targets"].items()),
       "E assessment preserves the exact pre-registered forecast interval behind its calibration label")
    missed = json.loads(json.dumps(effect_metrics))
    first_link = effect_meta["effect_case"]["chain"][0]
    first_cell = econfig.cell_spec(ctx.cfg)[first_link["target_cell"]]
    comparator = next(n for n in graph["nodes"] if n["id"] == settled["comparator_node"])
    missed[first_cell["result_key"]] = comparator["scores"][first_cell["result_key"]]
    missed_assessment = evalid.effect_contract_assessment(ctx, effect_node, missed, effect_meta)
    ok(missed_assessment["targets"][first_link["target_cell"]]["status"] == "failed",
       "point parity cannot masquerade as a worthwhile E improvement")
    over = json.loads(json.dumps(effect_metrics))
    resource_axis = next(axis for axis, cap in effect_meta["effect_case"]["resources"]["candidate"].items()
                         if isinstance(cap, (int, float)) and not isinstance(cap, bool))
    cap = float(effect_meta["effect_case"]["resources"]["candidate"][resource_axis])
    over["_effect_resources"][resource_axis]["upper"] = cap + max(1.0, abs(cap) * 0.01)
    over_assessment = evalid.effect_contract_assessment(ctx, effect_node, over, effect_meta)
    ok(over_assessment["resources"]["status"] == "failed" and over_assessment["status"] == "failed",
       "buying a gain above the frozen resource cap blocks scientific E promotion")

    # A declared tradeoff is neither hidden matching nor a free engineering
    # escape hatch: only named axes may worsen, and even those remain capped.
    trade_meta = json.loads(json.dumps(effect_meta))
    trade_resources = trade_meta["effect_case"]["resources"]
    trade_resources.update({
        "regime": "budgeted_tradeoff",
        "fixed_axes": [axis for axis in eprogram.RESOURCE_AXES if axis != "latency_ms"],
        "tradeoff_axes": ["latency_ms"], "improvement_axes": [],
        "comparison": long(100, "latency is the sole predeclared tradeoff while every other measured resource axis remains matched to the exact comparator"),
    })
    trade_resources["candidate"]["latency_ms"] = 12.0
    trade_metrics = json.loads(json.dumps(effect_metrics))
    trade_metrics["_effect_resources"]["latency_ms"].update({"lower": 11.0, "upper": 11.0})
    trade_assessment = evalid.effect_contract_assessment(ctx, effect_node, trade_metrics, trade_meta)
    ok(trade_assessment["resources"]["status"] == "met"
       and trade_assessment["resources"]["axes"]["latency_ms"]["relation"] == "worse",
       "a named resource tradeoff may worsen against the comparator while staying inside its frozen cap")
    trade_metrics["_effect_resources"]["latency_ms"].update({"lower": 13.0, "upper": 13.0})
    ok(evalid.effect_contract_assessment(ctx, effect_node, trade_metrics, trade_meta)["resources"]["status"] == "failed",
       "a declared tradeoff still fails when its realized cost exceeds the precommitted cap")
    malformed_trade = json.loads(json.dumps(trade_meta["effect_case"]))
    malformed_trade["resources"]["tradeoff_axes"] = []
    malformed_errs = eprogram._resource_errors(malformed_trade, where="synthetic tradeoff")
    ok(any(e.startswith("PROGRAM_RESOURCE_TRADEOFF_POLICY") for e in malformed_errs),
       "budgeted_tradeoff cannot be an empty label with no explicitly traded axis")

    binding_candidate = json.loads(json.dumps(ctx.winner_sketch(effect_lane)))
    binding_resources = binding_candidate["effect_case"]["resources"]
    binding_resources.update({
        "regime": "efficiency",
        "fixed_axes": [axis for axis in eprogram.RESOURCE_AXES if axis != "latency_ms"],
        "tradeoff_axes": [], "improvement_axes": ["latency_ms"],
    })
    binding_resources["candidate"]["latency_ms"] = 9.0
    binding_errs = eprogram.candidate_errors(
        binding_candidate, where="synthetic efficiency binding",
        min_level=int(effect_lane.get("min_level") or 0), research=True,
        search_origin=str(effect_lane.get("search_origin") or ""),
        model_parent_count=len(effect_lane.get("parents") or []), platform=False)
    ok(any(e.startswith("PROGRAM_RESOURCE_CLAIM_BINDING") for e in binding_errs),
       "an efficiency resource regime is legal iff the scientific claim itself is explicitly efficiency")

    # (delivery debug R1) the contract is now replay-aware: a vector that
    # DIFFERS from the engine's sealed receipt is analyst smuggling; a
    # byte-identical one is the transition's own crash-window injection
    # replayed after a died submit, and blaming the analyst for it would
    # poison the retry. Pin both directions.
    injected_metrics = json.loads(json.dumps(effect_metrics))
    injected_metrics["_effect_resources"][resource_axis]["upper"] = float(
        injected_metrics["_effect_resources"][resource_axis].get("upper") or 0.0) + 1.0
    injected_rel = f"{scratch}/ANALYST_RESOURCE_INJECTION.json"
    injected_report = f"{scratch}/ANALYST_RESOURCE_REPORT.md"
    wj(d.repo, injected_rel, injected_metrics)
    wt(d.repo, injected_report,
       (d.repo / ".evo/nodes/N022/eval/EVAL_REPORT.md").read_text(encoding="utf-8"))
    errs = evalid.v_evaluate(ctx, {"subject": {"node": "N022"},
                                   "outputs": [injected_rel, injected_report]})
    ok(any(e.startswith("EVAL_EFFECT_RESOURCES_ENGINE_OWNED") for e in errs),
       "the analyst cannot smuggle a resource vector differing from the sealed receipt")
    wj(d.repo, injected_rel, json.loads(json.dumps(effect_metrics)))
    errs = evalid.v_evaluate(ctx, {"subject": {"node": "N022"},
                                   "outputs": [injected_rel, injected_report]})
    ok(not any(e.startswith("EVAL_EFFECT_RESOURCES_ENGINE_OWNED") for e in errs),
       "a byte-identical vector is the crash-window replay of the engine's own injection - tolerated")
    measured_metrics = json.loads(json.dumps(effect_metrics))
    measured_metrics["_resource_measurements"] = {resource_axis: {"lower": 1.0, "upper": 2.0}}
    wj(d.repo, injected_rel, measured_metrics)
    errs = evalid.v_evaluate(ctx, {"subject": {"node": "N022"},
                                   "outputs": [injected_rel, injected_report]})
    ok(any(e.startswith("EVAL_EFFECT_RESOURCES_ENGINE_OWNED") for e in errs),
       "_resource_measurements never belongs in analyst metrics (raw payload only)")

    forged_resources = json.loads(json.dumps(effect_metrics["_effect_resources"]))
    forged_resources[resource_axis]["upper"] += 1.0
    errs = evalid._effect_resource_receipt_errors(ctx, effect_node, forged_resources)
    ok(any(e.startswith("EVAL_EFFECT_RESOURCES_ENGINE_MISMATCH") for e in errs),
       "a forged normalized resource vector cannot diverge from the active engine receipt")

    receipt_rel = effect_node["resource_receipt_path"]
    receipt = json.loads((d.repo / receipt_rel).read_text(encoding="utf-8"))
    tampered_receipt = json.loads(json.dumps(receipt))
    tampered_receipt["resources"][resource_axis]["upper"] += 1.0
    wj(d.repo, receipt_rel, tampered_receipt)
    receipt_errs = evalid.resource_receipt_errors(ctx, effect_node)
    seal_errs = eseal.verify(d.repo, effect_node["resource_receipt_seal"],
                             label="tampered resource receipt", require_working=True)
    wj(d.repo, receipt_rel, receipt)
    ok(any(e.startswith("EVAL_RESOURCE_RECEIPT_MISMATCH") for e in receipt_errs)
       and any(e.startswith("SEALED_ARTIFACT_MUTATED") for e in seal_errs),
       "receipt value tampering fails both raw-evidence binding and its content seal")

    ok((effect_node.get("evaluation_summary") or {}).get("mechanism_contract_status") == "refuted"
       and effect_node.get("scientific_promotion_status") == "blocked",
       "sealed numeric probe predicate, not analyst prose, blocks a refuted mechanism claim")
    raw_mechanism = (effect_node.get("evaluation_summary") or {}).get("mechanism_contract") or {}
    projected_mechanism = (edash._assessment_view(effect_node.get("evaluation_summary") or {})
                           .get("mechanism_contract") or {})
    ok(projected_mechanism.get("observation_count") == len(raw_mechanism.get("values") or [])
       and projected_mechanism.get("values") == (raw_mechanism.get("values") or [])[:32],
       "dashboard mechanism audit preserves bounded numeric observations and their exact count")

    waiver_meta = json.loads(json.dumps(effect_meta))
    waiver_meta["attribution_waiver"] = long(
        70, "the intervention has no separately measurable intermediate and is evaluated only as an unapportioned performance change")
    waiver_idea = f"{scratch}/WAIVER_IDEA.md"
    wt(d.repo, waiver_idea, "# synthetic attribution-waiver fixture\n")
    wj(d.repo, waiver_idea.replace(".md", ".meta.json"), waiver_meta)
    waiver_node = json.loads(json.dumps(effect_node))
    waiver_node["id"] = "NWAIVER"
    waiver_node["idea_doc"] = waiver_idea
    waiver_assessment = evalid.computed_assessment(ctx, waiver_node, effect_metrics)
    ok(waiver_assessment["verdict"] == "improved"
       and waiver_assessment["mechanism_contract_status"] == "unverified"
       and waiver_assessment["scientific_promotion_status"] == "blocked",
       "an attribution waiver preserves an observed performance gain but cannot promote an unverified scientific mechanism")

    dossier = (d.repo / ".evo/profile/PROBLEM_DOSSIER.md").read_text(encoding="utf-8")
    dossier_path = f"{scratch}/BAD_DOSSIER.md"
    wt(d.repo, dossier_path, dossier + "\nThe preferred catalog move is MV17.\n")
    errs = evalid.v_dossier(ctx, {"subject": {}, "outputs": [dossier_path]})
    ok(any(e.startswith("DOSSIER_SOLUTION_LEAK") for e in errs),
       "bootstrap problem model rejects solution-catalog priming")
    import edoctor
    wt(d.repo, ".evo/profile/PROBLEM_DOSSIER.md", dossier + "\npost-freeze edit\n")
    dossier_problems, _ = edoctor.diagnose(store)
    wt(d.repo, ".evo/profile/PROBLEM_DOSSIER.md", dossier)
    ok(any(e.startswith("PROBLEM_DOSSIER_MUTATED") for e in dossier_problems),
       "doctor detects post-freeze edits to the method-blind bootstrap problem model")

    diag_task = next(t for t in st["tasks"] if t.get("type") == "diagnose"
                     and (t.get("subject") or {}).get("lane") == repair_lane["id"])
    # v10.1: terminal tasks drop the _render recipe; the persisted BUNDLE.md is
    # the durable record of what the diagnosis actually saw.
    diag_bundle = (d.repo / diag_task["bundle"]).read_text(encoding="utf-8")
    diag_inputs = re.findall(r"^- `([^`]+)` - ", diag_bundle, re.M)
    parent_idea = d.node(repair_lane["parents"][0])["idea_doc"]
    ok(parent_idea in diag_inputs and parent_idea.replace(".md", ".meta.json") in diag_inputs
       and not any("MOVE_CATALOG" in p or "MECH_CARDS" in p or "INNOVATION_RUBRIC" in p
                   for p in diag_inputs)
       and "## Lessons routed to this task" not in diag_bundle,
       f"diagnosis sees the historical parent intervention but no candidate solution catalog: {diag_inputs}")

    diagnosis = json.loads((d.repo / repair_lane["diagnosis_path"]).read_text(encoding="utf-8"))
    diagnosis["problem"] += " The preferred solution is MV17."
    diag_path = f"{scratch}/BAD_DIAGNOSIS.json"
    wj(d.repo, diag_path, diagnosis)
    errs = evalid.v_diagnose(ctx, {"subject": {"lane": repair_lane["id"]}, "outputs": [diag_path]})
    ok(any(e.startswith("DIAGNOSIS_SOLUTION_LEAK") for e in errs),
       "pre-method diagnosis rejects move/paper leakage")

    frozen_diagnosis = json.loads((d.repo / repair_lane["diagnosis_path"]).read_text(encoding="utf-8"))
    tampered_diagnosis = json.loads(json.dumps(frozen_diagnosis))
    tampered_diagnosis["unknowns"].append(long(30, "a target rewritten after reading the mechanism catalog"))
    wj(d.repo, repair_lane["diagnosis_path"], tampered_diagnosis)
    errs = evalid.v_sketch(ctx, {"subject": {"lane": repair_lane["id"]},
                                 "outputs": [repair_lane["sketches_path"]]})
    doctor_problems, _ = edoctor.diagnose(store)
    wj(d.repo, repair_lane["diagnosis_path"], frozen_diagnosis)
    ok(any(e.startswith("DIAGNOSIS_MUTATED") for e in errs),
       "editing the frozen diagnosis is detected by the complete-program validator")
    ok(any(e.startswith("LANE_DIAGNOSIS_MUTATED") for e in doctor_problems),
       "doctor independently audits frozen diagnosis digests")

    sketches = json.loads((d.repo / repair_lane["sketches_path"]).read_text(encoding="utf-8"))
    sketches["diagnosis_digest"] = "f" * 64
    sk_path = f"{scratch}/BAD_SKETCHES.json"
    wj(d.repo, sk_path, sketches)
    errs = evalid.v_sketch(ctx, {"subject": {"lane": repair_lane["id"]}, "outputs": [sk_path]})
    ok(any(e.startswith("PROGRAM_DIAGNOSIS_DIGEST") for e in errs),
       "complete program set is bound to the immutable diagnosis")

    spec = json.loads((d.repo / d.node("N022")["spec"]).read_text(encoding="utf-8"))
    spec["evidence_budget"] = {"extra_costly_arms": 1}
    spec["workflow"]["stages"][0]["launch"] += " --sweep ablation"
    errs = evalid._spec_errors(ctx, spec, expect_role="variant", expect_parents=spec["parents"],
                               expect_level=spec["level"], where="v91 scratch spec")
    ok(any(e.startswith("SPEC_EVIDENCE_BUDGET_LEGACY") for e in errs),
       "the old generic costly-arm bucket is rejected as ambiguous")
    ok(any(e.startswith("SPEC_ABLATION_IN_CANDIDATE") for e in errs),
       "ablation hidden inside a candidate-producing stage is rejected")

    # Adaptive search and fixed multi-model production are primary algorithm
    # shapes, not evidence arms. They are legal only with frozen control, caps
    # and a ledger; the validator must not reject a legitimate --sweep merely
    # because it evaluates several candidates.
    clean_ctx = evalid.Ctx(store, st, store.load_config(), graph, {"artifacts": []})
    adaptive = json.loads((d.repo / d.node("N022")["spec"]).read_text(encoding="utf-8"))
    astage = adaptive["workflow"]["stages"][0]
    astage["launch"] += " --sweep"
    astage["control"] = {
        "mode": "preregistered_adaptive", "multiplicity": "algorithmic",
        "controller": long(70, "select the next candidate by a frozen UCB rule over the registered objective"),
        "stopping_conditions": ["candidate evaluation cap is reached", "registered convergence rule fires"],
        "why_multiple": long(60, "candidate selection is the algorithm that produces the delivered architecture")}
    astage["budget"] = {"limits": {"candidate_evaluations": 12, "gpu_hours": 6}}
    astage["ledger_file"] = f"{scratch}/adaptive_ledger.jsonl"
    errs = evalid._spec_errors(clean_ctx, adaptive, expect_role="variant",
                               expect_parents=adaptive["parents"], expect_level=adaptive["level"],
                               where="adaptive scratch spec")
    forbidden = ("SPEC_STAGE_CONTROL", "SPEC_STAGE_STOPPING", "SPEC_STAGE_MULTIPLICITY",
                 "SPEC_MULTIPLICITY_UNDECLARED", "SPEC_STAGE_LEDGER", "SPEC_STAGE_BUDGET")
    ok(not any(e.startswith(forbidden) for e in errs),
       f"preregistered adaptive candidate search is accepted as algorithmic work: {errs}")

    bad_adaptive = json.loads(json.dumps(adaptive))
    bad_adaptive["workflow"]["stages"][0]["control"].pop("controller")
    bad_adaptive["workflow"]["stages"][0].pop("ledger_file")
    bad_adaptive["workflow"]["stages"][0]["budget"] = {"limits": {}}
    errs = evalid._spec_errors(clean_ctx, bad_adaptive, expect_role="variant",
                               expect_parents=bad_adaptive["parents"], expect_level=bad_adaptive["level"],
                               where="bad adaptive scratch spec")
    ok(any("control.controller" in e for e in errs) and any(e.startswith("SPEC_STAGE_LEDGER") for e in errs)
       and any(e.startswith("SPEC_STAGE_BUDGET") for e in errs),
       "adaptive work cannot omit its controller, ledger or finite caps")

    legacy = json.loads(json.dumps(adaptive))
    legacy["train"] = legacy.pop("workflow")
    errs = evalid._spec_errors(clean_ctx, legacy, expect_role="variant",
                               expect_parents=legacy["parents"], expect_level=legacy["level"],
                               where="legacy scratch spec")
    ok(any(e.startswith("SPEC_TRAIN_SCHEMA_UNSUPPORTED") for e in errs),
       "top-level train schema is unsupported rather than runtime-compatible")

    wt(d.repo, astage["ledger_file"], '{"step":1,"decision":"candidate-7"}\n')
    good_metrics = f"{scratch}/adaptive_metrics.json"
    wj(d.repo, good_metrics, {"summary": {"best_score": 0.8},
                              "usage": {"candidate_evaluations": 10, "gpu_hours": 5},
                              "stop_reason": "registered convergence rule fired"})
    errs = evalid.stage_result_errors(clean_ctx, astage, good_metrics, astage["ledger_file"],
                                      where="adaptive result")
    ok(not errs, f"bounded adaptive result with trace is accepted: {errs}")
    over_metrics = f"{scratch}/over_budget_metrics.json"
    wj(d.repo, over_metrics, {"summary": {"best_score": 0.8},
                              "usage": {"candidate_evaluations": 13, "gpu_hours": 5},
                              "stop_reason": "candidate evaluation cap was exceeded"})
    errs = evalid.stage_result_errors(clean_ctx, astage, over_metrics, astage["ledger_file"],
                                      where="over-budget adaptive result")
    ok(any(e.startswith("STAGE_RESULT_BUDGET_EXCEEDED") for e in errs),
       "reported stage usage above an approved cap cannot advance the node")

    multi = json.loads(json.dumps(adaptive))
    mstage = multi["workflow"]["stages"][0]
    mstage["launch"] = mstage["launch"].replace(" --sweep", "")
    mstage["control"] = {"mode": "fixed", "multiplicity": "algorithmic",
                         "why_multiple": long(60, "all component models are required to construct the delivered merged system")}
    mstage["budget"] = {"limits": {"models_processed": 4, "wallclock_minutes": 60}}
    mstage["produces"][0]["kind"] = "collection"
    errs = evalid._spec_errors(clean_ctx, multi, expect_role="variant",
                               expect_parents=multi["parents"], expect_level=multi["level"],
                               where="fixed multi-model scratch spec")
    ok(not any(e.startswith(("SPEC_STAGE_MULTIPLICITY", "SPEC_STAGE_LEDGER",
                             "SPEC_ARTIFACT_KIND")) for e in errs),
       f"fixed intrinsic multi-model procedure and collection artifact are accepted: {errs}")

    idea_path = d.node("N022")["idea_doc"]
    idea_md = (d.repo / idea_path).read_text(encoding="utf-8")
    original_meta = json.loads((d.repo / idea_path.replace(".md", ".meta.json")).read_text(encoding="utf-8"))
    idea_meta = json.loads(json.dumps(original_meta))
    idea_meta["claim_scope"] = {"kind": "specialist", "target_cells": ["C2"],
                                "guardrail_cells": ["C3"],
                                "rationale": long(75, "this deliberately invalid scope attempts to omit a required ranking target")}
    bad_md, bad_meta = f"{scratch}/BAD_IDEA.md", f"{scratch}/BAD_IDEA.meta.json"
    wt(d.repo, bad_md, idea_md)
    wj(d.repo, bad_meta, idea_meta)
    errs = evalid.v_mature(ctx, {"subject": {"lane": effect_lane["id"]}, "outputs": [bad_md, bad_meta]})
    ok(any(e.startswith("IDEA_CLAIM_REQUIRED_TARGETS") for e in errs),
       "a specialist claim cannot scope away a required target")

    idea_meta = json.loads(json.dumps(original_meta))
    idea_meta["mechanism_probe"].update({
        "mode": "eval_intervention", "extra_eval_arms": 2,
        "cheaper_modes_rejected": [
            {"mode": "same_run", "reason": long(35, "the required counterfactual intervention is absent from normal logging")},
            {"mode": "existing_artifact", "reason": long(35, "no existing artifact contains the intervened representation")}]})
    wt(d.repo, bad_md, idea_md)
    wj(d.repo, bad_meta, idea_meta)
    errs = evalid.v_mature(ctx, {"subject": {"lane": effect_lane["id"]}, "outputs": [bad_md, bad_meta]})
    ok(any(e.startswith("IDEA_PROBE_EVAL_ARMS") for e in errs),
       "mechanism probe cannot exceed the user's eval-only arm cap")

    # Probe closure is mechanical at implementation and smoke, not merely an
    # evaluation-report heading.
    probe_node = d.node("N022")
    probe_spec = json.loads((d.repo / probe_node["spec"]).read_text(encoding="utf-8"))
    bad_build = f"{scratch}/BAD_BUILD.md"
    base_sections = [
        ("Workarea", long(60, f"code remains in {probe_node['workdir']} on the validated branch")),
        ("Mechanism to code map", "- objective -> mod_a.py\n- head -> mod_b.py"),
        ("Deviations", long(50, "no deviations were introduced by this negative fixture")),
        ("Self test", long(50, "the normal import and flag checks were executed successfully")),
    ]
    wt(d.repo, bad_build, md(*base_sections))
    errs = evalid.v_implement(ctx, {"subject": {"node": "N022"}, "outputs": [bad_build]})
    ok(any("probe instrumentation" in e.lower() for e in errs if e.startswith("MD_SECTION_MISSING")),
       "a build cannot omit the registered probe instrumentation section")
    execution = probe_spec["probe_execution"]
    wt(d.repo, bad_build, md(*base_sections, (
        "Probe instrumentation",
        long(55, "the report names an artifact but deliberately omits the literal field-to-code rows") +
        f"\n\nPROBE_ARTIFACT: {execution['artifact']}")))
    errs = evalid.v_implement(ctx, {"subject": {"node": "N022"}, "outputs": [bad_build]})
    ok(any(e.startswith("BUILD_PROBE_FIELDS_MISSING") for e in errs),
       "naming a probe artifact without implementing every required field is rejected")
    smoke_probe = str(execution["smoke_artifact"])
    smoke_backup = (d.repo / smoke_probe).read_text(encoding="utf-8")
    wj(d.repo, smoke_probe, {})
    errs = evalid.v_smoke(ctx, {"subject": {"node": "N022"}, "outputs": []})
    ok(any(e.startswith("PROBE_ARTIFACT_FIELD") for e in errs),
       "a passing command smoke cannot hide a missing numeric probe field")
    wt(d.repo, smoke_probe, smoke_backup)

    # Same score vector under different deliverable/claim contracts. A shared
    # checkpoint cannot call an out-of-scope regression a clean specialist win;
    # task-adapted delivery can retain the old checkpoint for that task.
    syn_meta_path = f"{scratch}/SYN.meta.json"
    syn_node = {"id": "SYN", "role": "variant", "level": 2, "parents": ["N023"],
                "idea_doc": f"{scratch}/SYN.md"}
    metrics = {"auc": 0.790, "logloss": 0.650, "latency_ms": 100.0}
    syn_meta = {"claim_scope": {"kind": "specialist", "target_cells": ["C1"],
                                 "guardrail_cells": ["C3"]}}
    wj(d.repo, syn_meta_path, syn_meta)
    ass = evalid.computed_assessment(ctx, syn_node, metrics)
    ok(ass["verdict"] == "tradeoff" and ass["breadth_losses"] == ["C2"]
       and ass["overall_contract_pass"] is False,
       f"single-checkpoint scoped gain exposes its out-of-scope tradeoff: {ass}")
    adapted_cfg = json.loads(json.dumps(ctx.cfg))
    adapted_cfg["evaluation_contract"]["model_scope"] = "task_adapted"
    adapted_ctx = evalid.Ctx(store, st, adapted_cfg, graph, store.load_artifacts())
    ass = evalid.computed_assessment(adapted_ctx, syn_node, metrics)
    ok(ass["verdict"] == "specialist" and ass["overall_contract_pass"] is False,
       f"task-adapted delivery can retain a scoped specialist without replacing other task checkpoints: {ass}")
    syn_meta["claim_scope"] = {"kind": "generalist", "target_cells": ["C1", "C2"],
                               "guardrail_cells": ["C3"]}
    wj(d.repo, syn_meta_path, syn_meta)
    ass = evalid.computed_assessment(ctx, syn_node, metrics)
    ok(ass["verdict"] == "tradeoff", f"same vector under a broad claim is a tradeoff: {ass}")
    metrics["latency_ms"] = 110.0
    ass = evalid.computed_assessment(ctx, syn_node, metrics)
    ok(ass["verdict"] == "regressed" and ass["guardrail_losses"] == ["C3"],
       "hard global guardrail loss blocks an otherwise positive claim")
    metrics = {"auc": 0.500, "logloss": 0.400, "latency_ms": 100.0}
    ass = evalid.computed_assessment(ctx, syn_node, metrics)
    ok(ass["verdict"] == "regressed" and ass["required_target_losses"] == ["C1"],
       "a gain elsewhere cannot compensate for regression on a required target")
    ass = evalid.computed_assessment(
        ctx, syn_node, {"auc": 0.810, "logloss": 0.650, "latency_ms": 100.0})
    ok(ass["project_goal_attained"] is True and ass["goal_groups_met"] == ["G1"],
       f"absolute multi-dataset goal is reported separately from relative node progress: {ass}")
    guard_goal_cfg = json.loads(json.dumps(ctx.cfg))
    guard_goal_cfg["evaluation_contract"]["cells"][2].update(
        {"goal_threshold": 95.0,
         "goal_threshold_source": "deployment acceptance requires p95 latency at or below 95 ms"})
    guard_goal_ctx = evalid.Ctx(store, st, guard_goal_cfg, graph, store.load_artifacts())
    ass = evalid.computed_assessment(
        guard_goal_ctx, syn_node, {"auc": 0.810, "logloss": 0.650, "latency_ms": 100.0})
    ok(ass["project_goal_attained"] is False and ass["absolute_guardrail_not_met"] == ["C3"],
       f"an absolute deployment guardrail blocks project-goal attainment even at relative parity: {ass}")
    interval_source = f"{scratch}/fixed_predictions.json"
    wj(d.repo, interval_source, {"count": 1000})
    interval_metric = {"value": 0.805, "uncertainty": {
        "method": "fixed_predictions_bootstrap", "unit": "sample", "unit_count": 1000,
        "procedure": "percentile bootstrap over the fixed prediction rows", "level": 0.95,
        "lower": 0.795, "upper": 0.815, "source": interval_source,
        "extra_training_runs": 0, "resamples": 1000}}
    ass = evalid.computed_assessment(
        ctx, syn_node, {"auc": interval_metric,
                        "logloss": 0.650, "latency_ms": 100.0})
    ok(ass["cells"]["C1"]["goal_status"] == "unknown"
       and ass["project_goal_attained"] is False,
       f"a fixed-evaluation interval crossing the absolute goal is not overclaimed: {ass}")
    interval_view = edash._result_view(interval_metric)
    ok(interval_view["interval"] == {"lower": 0.795, "upper": 0.815, "level": 0.95}
       and interval_view["evidence"]["kind"] == "fixed_eval_uncertainty"
       and interval_view["evidence"]["unit_count"] == 1000,
       "dashboard preserves fixed-evaluation interval provenance without exposing its source path")
    legacy_errs = evalid.metric_evidence_errors(ctx, "auc", {"mean": 0.81, "std": 0.01, "n": 3})
    ok(any(e.startswith("EVAL_METRIC_LEGACY_AGGREGATE") for e in legacy_errs),
       "ambiguous mean/std/n cannot trigger hidden seed repetitions")
    seed_errs = evalid.metric_evidence_errors(ctx, "auc", {"value": 0.81, "uncertainty": {
        "method": "repeated_seeds", "unit": "case", "unit_count": 1000,
        "procedure": "aggregate independently retrained random seed runs", "level": 0.95,
        "lower": 0.80, "upper": 0.82, "source": interval_source,
        "extra_training_runs": 3}})
    ok(any(e.startswith("EVAL_UNCERTAINTY_METHOD") for e in seed_errs)
       and any(e.startswith("EVAL_UNCERTAINTY_TRAINING") for e in seed_errs),
       "in-node repeated training is rejected as uncertainty metadata")
    underspecified_errs = evalid.metric_evidence_errors(ctx, "auc", {"value": 0.81, "uncertainty": {
        "method": "analytic", "unit": "sample", "level": 0.95,
        "lower": 0.80, "upper": 0.82, "source": interval_source,
        "extra_training_runs": 0}})
    ok(any(e.startswith("EVAL_UNCERTAINTY_COUNT") for e in underspecified_errs)
       and any(e.startswith("EVAL_UNCERTAINTY_PROCEDURE") for e in underspecified_errs),
       "an interval must disclose fixed evaluation count and reproducible procedure")

    equal_resources = {axis: {"lower": 1.0, "upper": 1.0, "source": "sealed synthetic receipt"}
                       for axis in eprogram.RESOURCE_AXES}
    pareto_ref = {"id": "PB", "scores": {"auc": 0.80, "logloss": 0.50, "latency_ms": 100.0},
                  "score_evidence": {}, "effect_resources_realized": equal_resources}
    pareto_new = {"id": "PA", "scores": {"auc": 0.81, "logloss": 0.50, "latency_ms": 100.0},
                  "effect_resources_realized": json.loads(json.dumps(equal_resources)),
                  "score_evidence": {"auc": {"value": 0.81, "uncertainty": {
                      "method": "fixed_predictions_bootstrap", "unit": "sample", "unit_count": 1000,
                      "procedure": "percentile bootstrap over the fixed prediction rows", "level": 0.95,
                      "lower": 0.79, "upper": 0.83, "source": interval_source,
                      "extra_training_runs": 0, "resamples": 1000}}}}
    ok(not egraph._pareto_dominates(pareto_new, pareto_ref, ctx.cfg),
       "a lucky point estimate whose interval crosses regression cannot Pareto-prune its reference")
    pareto_new["score_evidence"]["auc"]["uncertainty"].update({"lower": 0.805, "upper": 0.815})
    ok(egraph._pareto_dominates(pareto_new, pareto_ref, ctx.cfg),
       "Pareto dominance uses the same conservative interval once improvement is supported")

    # Hierarchical voting: two metrics from T1 are one task vote, not two votes
    # against T2. A flat cell-majority implementation would incorrectly pass G3.
    hier_cfg = json.loads(json.dumps(ctx.cfg))
    hier_cfg["evaluation_contract"]["cells"].append(
        {"id": "C4", "dataset": "D1", "task": "T1", "metric": "auc",
         "result_key": "auc_slice", "role": "target", "weight": 1.0,
         "min_improvement": 0.0, "noninferiority_margin": 0.0, "required": False,
         "goal_threshold": None, "goal_threshold_source": "synthetic progress-only test cell"})
    hier_cfg["evaluation_contract"]["task_groups"].append(
        {"id": "G3", "name": "cross-task breadth", "tasks": ["T1", "T2"],
         "aggregation": "majority", "required": False})
    hier_graph = json.loads(json.dumps(graph))
    next(n for n in hier_graph["nodes"] if n["id"] == "N023").setdefault("scores", {})["auc_slice"] = 0.70
    hier_ctx = evalid.Ctx(store, st, hier_cfg, hier_graph, store.load_artifacts())
    syn_meta["claim_scope"] = {"kind": "generalist", "target_cells": ["C1", "C2", "C4"],
                               "guardrail_cells": ["C3"]}
    wj(d.repo, syn_meta_path, syn_meta)
    ass = evalid.computed_assessment(
        hier_ctx, syn_node, {"auc": 0.790, "auc_slice": 0.800,
                             "logloss": 0.650, "latency_ms": 100.0})
    g3 = next(g for g in ass["groups"] if g["id"] == "G3")
    ok(g3["wins"] == 1 and g3["improved"] is False,
       f"multiple metrics from one task count as one group vote: {g3}")

    # The inverse failure is equally dangerous: once a task's own aggregation
    # says it improved, a minority losing cell must not reappear as a group
    # veto.  G1 contains only T1, whose majority is 2 wins / 1 loss.
    majority_cfg = json.loads(json.dumps(hier_cfg))
    next(task for task in majority_cfg["evaluation_contract"]["tasks"]
         if task["id"] == "T1")["aggregation"] = "majority"
    majority_cfg["evaluation_contract"]["cells"].append(
        {"id": "C5", "dataset": "D1", "task": "T1", "metric": "auc",
         "result_key": "auc_slice_loss", "role": "target", "weight": 1.0,
         "min_improvement": 0.0, "noninferiority_margin": 0.0, "required": False,
         "goal_threshold": None, "goal_threshold_source": "synthetic progress-only losing cell"})
    majority_graph = json.loads(json.dumps(hier_graph))
    next(n for n in majority_graph["nodes"] if n["id"] == "N023").setdefault(
        "scores", {})["auc_slice_loss"] = 0.70
    majority_ctx = evalid.Ctx(store, st, majority_cfg, majority_graph, store.load_artifacts())
    syn_meta["claim_scope"] = {
        "kind": "generalist", "target_cells": ["C1", "C4", "C5"],
        "guardrail_cells": ["C3"],
    }
    wj(d.repo, syn_meta_path, syn_meta)
    majority_assessment = evalid.computed_assessment(
        majority_ctx, syn_node, {"auc": 0.790, "auc_slice": 0.800,
                                 "auc_slice_loss": 0.600,
                                 "logloss": 0.650, "latency_ms": 100.0})
    g1 = next(g for g in majority_assessment["groups"] if g["id"] == "G1")
    ok(g1["wins"] == 1 and g1["losses"] == 0 and g1["uncertain"] == 0
       and g1["improved"] is True
       and "G1" not in majority_assessment["required_group_losses"],
       f"a minority losing cell cannot bypass majority task aggregation and veto its group: {g1}")


def seal_chain_adversarial_checks(d):
    """Accepted science/code/evidence bytes are immutable; explicit revision
    slots, rather than mutable status labels, are the only escape hatch."""
    section("content-seal adversarial checks: theory -> idea -> spec -> code -> evidence -> conclusion")

    def artifact_from(seal, preferred):
        rows = list((seal or {}).get("artifacts") or [])
        return next((row["path"] for row in rows if row.get("role") == preferred), rows[0]["path"])

    lanes = d.state()["lanes"]
    graph = d.graph()
    idea_lane = next(l for l in lanes if isinstance(l.get("idea_seal"), dict))
    theory_lane = next(l for l in lanes if isinstance(l.get("theory_seal"), dict))
    sealed_node = next(n for n in graph["nodes"] if isinstance(n.get("conclusion_seal"), dict)
                       and isinstance(n.get("implementation_seal"), dict))
    targets = [
        (artifact_from(theory_lane["theory_seal"], "theory"), "theory"),
        (artifact_from(idea_lane["idea_seal"], "idea_meta"), "idea"),
        (artifact_from(sealed_node["spec_seal"], "node_spec"), "node spec"),
        (artifact_from(sealed_node["implementation_seal"], "implementation_source_1"), "implementation"),
        (artifact_from(sealed_node["eval_seal"], "normalized_metrics"), "evaluation"),
        (artifact_from(sealed_node["conclusion_seal"], "outcome"), "conclusion"),
    ]

    def mutate_and_expect_block(rel, label):
        path = d.repo / rel
        original = path.read_bytes()
        try:
            if path.suffix.lower() == ".json":
                data = json.loads(original.decode("utf-8"))
                data["__adversarial_mutation__"] = label
                wj(d.repo, rel, data)
            else:
                path.write_bytes(original + f"\nsealed mutation: {label}\n".encode("utf-8"))
            blocked = False
            try:
                d.next()
            except SystemExit as exc:
                blocked = "SEALED_" in str(exc)
            ok(blocked, f"post-approval {label} mutation is rejected before scheduling")
        finally:
            path.write_bytes(original)

    for rel, label in targets:
        mutate_and_expect_block(rel, label)

    # Regression for the subtle bypass: a caller must not be able to flip the
    # mutable display status on an active seal and thereby disable working-path
    # verification. Active/history semantics come from the owner slot.
    graph_path = d.repo / ".evo/graph.json"
    graph_bytes = graph_path.read_bytes()
    code_rel = artifact_from(sealed_node["implementation_seal"], "implementation_source_1")
    code_path, code_bytes = d.repo / code_rel, (d.repo / code_rel).read_bytes()
    try:
        changed = json.loads(graph_bytes.decode("utf-8"))
        target = next(n for n in changed["nodes"] if n["id"] == sealed_node["id"])
        target["implementation_seal"]["status"] = "superseded"
        wj(d.repo, ".evo/graph.json", changed)
        code_path.write_bytes(code_bytes + b"\n# status-flip bypass attempt\n")
        blocked = False
        try:
            d.next()
        except SystemExit as exc:
            blocked = "SEALED_" in str(exc)
        ok(blocked, "active-slot verification ignores a forged superseded status")
    finally:
        code_path.write_bytes(code_bytes)
        graph_path.write_bytes(graph_bytes)

    # Moving an active approval record into history is not a legal way to make
    # the current head unaudited. Requiredness comes from workflow state.
    state_path = d.repo / ".evo/state.json"
    state_bytes = state_path.read_bytes()
    try:
        changed = json.loads(state_bytes.decode("utf-8"))
        target = next(l for l in changed["lanes"] if l["id"] == idea_lane["id"])
        target.setdefault("seal_history", []).append(target.pop("idea_seal"))
        wj(d.repo, ".evo/state.json", changed)
        blocked = False
        try:
            d.next()
        except SystemExit as exc:
            blocked = "SEAL_MISSING" in str(exc)
        ok(blocked, "an active idea seal cannot be deleted or demoted into history")
    finally:
        state_path.write_bytes(state_bytes)

    # The reviewed commit is the execution closure in Git mode. A late,
    # untracked source dependency is executable even though tracked files are
    # clean, so the manifest must reject it before any RUN can launch.
    late_source = d.repo / str(sealed_node["workdir"]) / "late_dependency_attack.py"
    try:
        late_source.write_text("def injected_dependency():\n    return 'unreviewed'\n", encoding="utf-8")
        blocked = False
        try:
            d.next()
        except SystemExit as exc:
            blocked = "UNSEALED_EXECUTION_SOURCE" in str(exc)
        ok(blocked, "a new untracked execution dependency requires an explicit implementation revision")
    finally:
        late_source.unlink(missing_ok=True)

    # Accepted artifact identities are monotonic even when retry-budget counters
    # reset after escalation; no PROGRAMS_c1 can overwrite an earlier revision.
    for lane in lanes:
        program_paths = []
        if lane.get("sketches_path"):
            program_paths.append(str(lane["sketches_path"]))
        program_paths.extend(str(a.get("program_set")) for a in (lane.get("attempts") or [])
                             if a.get("program_set"))
        if not program_paths:
            continue
        seqs = [int(m.group(1)) for p in program_paths
                if (m := re.search(r"PROGRAMS_c(\d+)\.json$", p))]
        ok(len(program_paths) == len(set(program_paths)),
           f"lane {lane['id']} never reuses an accepted program-set path")
        ok(not seqs or int(lane.get("attempt_seq") or 0) >= max(seqs),
           f"lane {lane['id']} attempt_seq is monotonic across budget resets")
    ok(d.next().get("kind") == "done", "restored sealed run remains resumable and done")


def force_full_sweep(d):
    """v11: make the next `evo next` a deterministic FULL sweep by deleting the
    cadence marker. NOTE (R1 audit): the tail adversarial sections run in
    phase=done, where every sweep is already full - there this is explicit
    documentation, not a behavior change. Scoped-sweep mechanics (consumed set,
    cadence trip, fail-safe degradation) are covered at unit level in
    v11_feature_unit.sweep_scope_behavior; the in-rounds tamper E2E lives in
    the R018b section (v11.1 closed that coverage debt)."""
    marker = d.repo / ".evo" / "cache" / "sweep_cadence.json"
    if marker.exists():
        marker.unlink()


def git_integrity_failure_checks(d):
    """Git query failures are neither content differences nor permission to proceed."""
    section("Git integrity checks: dirty vs transient vs operational failure")
    original = evcs._git
    HEAD = "# branch.oid " + "a" * 40
    try:
        # v11: cleanliness comes from ONE status --porcelain=v2 probe. A dirty
        # tree is a SUBSTANTIVE rc=0 answer with entry lines - the old
        # diff-rc=1 semantics moved into the output, and the same fail-closed
        # retry wrapper still owns operational failures.
        evcs.begin_invocation()
        evcs._git = lambda _cwd, *_args, **_kw: (0, HEAD + "\n1 .M N... 100644 100644 100644 x y a.py")
        ok(not evcs.tracked_tree_clean(Path(".")),
           "a status entry line remains a substantive dirty result")

        evcs.begin_invocation()
        answers = iter([(127, "transient launch failure"), (0, HEAD)])
        evcs._git = lambda _cwd, *_args, **_kw: next(answers)
        ok(evcs.tracked_tree_clean(Path(".")),
           "one operational failure is retried without weakening the clean check")

        evcs.begin_invocation()
        evcs._git = lambda _cwd, *_args, **_kw: (127, "persistent synthetic failure")
        try:
            evcs.tracked_tree_clean(Path("."))
            failed_closed = False
        except evcs.GitCheckError as exc:
            # v10: bounded 3-try retry with backoff (F19) instead of v9.2's two
            failed_closed = "failed 3 times" in str(exc) and "rc=127" in str(exc)
        ok(failed_closed, "repeated operational failure raises a typed fail-closed error")

        # The unborn-HEAD refusal is part of the same fail-closed family: a
        # status answer WITHOUT a commit oid can never read as clean.
        evcs.begin_invocation()
        evcs._git = lambda _cwd, *_args, **_kw: (0, "# branch.head (unborn)")
        try:
            evcs.tracked_tree_clean(Path("."))
            unborn_closed = False
        except evcs.GitCheckError:
            unborn_closed = True
        ok(unborn_closed, "a missing branch.oid fails closed instead of reading clean")

        try:
            evcs.untracked_files(Path("."))
            untracked_failed_closed = False
        except evcs.GitCheckError:
            untracked_failed_closed = True
        ok(untracked_failed_closed,
           "an unavailable untracked-source query cannot silently return an empty safe set")

        # v11: the whole-web tripwire runs on a cadence; this scenario tests
        # the tripwire itself, so force the full-sweep tick deterministically.
        force_full_sweep(d)
        try:
            d.next()
            scheduler_classified = False
        except SystemExit as exc:
            message = str(exc)
            scheduler_classified = ("SEALED_IMPLEMENTATION_GIT_CHECK_FAILED" in message
                                    and "SEALED_IMPLEMENTATION_DIRTY" not in message)
        doctor_problems, _ = edoctor.diagnose(d.store())
        doctor_classified = (any("SEALED_IMPLEMENTATION_GIT_CHECK_FAILED" in p
                                 for p in doctor_problems)
                             and not any("SEALED_IMPLEMENTATION_DIRTY" in p
                                         for p in doctor_problems))
        ok(scheduler_classified and doctor_classified,
           "scheduler and doctor report Git operational failure without inventing a dirty tree")
    finally:
        evcs._git = original


def cli_preflight_adversarial_checks(d):
    """Mutating CLI commands must verify the owning scientific chain before
    they execute a subprocess or persist any state/registry/graph side effect."""
    section("CLI preflight adversarial checks: sealed inputs block side effects")
    evo = PKG / "engine" / "evo.py"
    state_path = d.repo / ".evo/state.json"
    graph_path = d.repo / ".evo/graph.json"
    artifacts_path = d.repo / ".evo/artifacts.json"
    events_path = d.repo / ".evo/events.jsonl"

    graph = d.graph()
    registry = d.reg()
    node = next(
        n for n in graph["nodes"]
        if isinstance(n.get("spec_seal"), dict)
        and isinstance(n.get("implementation_seal"), dict)
        and isinstance(n.get("conclusion_seal"), dict)
        and any(a.get("node") == n["id"] for a in registry.get("artifacts") or [])
        and (d.repo / f".evo/nodes/{n['id']}/smoke/RESULTS.json").exists()
    )
    node_id = node["id"]
    spec_rel = next(row["path"] for row in node["spec_seal"]["artifacts"]
                    if row.get("role") == "node_spec")
    spec_path = d.repo / spec_rel
    smoke_dir = d.repo / f".evo/nodes/{node_id}/smoke"
    repository_before = {path: path.read_bytes() for path in
                         (state_path, graph_path, artifacts_path, events_path, spec_path)}

    def cli(*args):
        return subprocess.run(
            [PY, str(evo), "--repo", str(d.repo), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace")

    def assert_seal_rejection(proc, label):
        output = (proc.stdout or "") + (proc.stderr or "")
        ok(proc.returncode != 0 and "SEALED_ARTIFACT_MUTATED" in output,
           f"{label} rejects the mutated active node spec at CLI preflight: {output}")

    def tree_snapshot(root):
        if not root.exists():
            return {}
        return {str(path.relative_to(root)): path.read_bytes()
                for path in root.rglob("*") if path.is_file()}

    def restore_tree(root, snapshot):
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file() and str(path.relative_to(root)) not in snapshot:
                    path.unlink()
        for rel, raw in snapshot.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)

    def tamper_spec(raw):
        spec = json.loads(raw.decode("utf-8"))
        spec["title"] = str(spec.get("title") or "") + " [adversarial semantic edit]"
        wj(d.repo, spec_rel, spec)

    # run-smoke would execute commands and rewrite RESULTS/logs/events.  None
    # of those bytes may move when its active spec no longer matches the seal.
    originals = {path: path.read_bytes() for path in
                 (state_path, graph_path, artifacts_path, events_path, spec_path)}
    smoke_before = tree_snapshot(smoke_dir)
    try:
        tamper_spec(originals[spec_path])
        proc = cli("run-smoke", "--node", node_id)
        assert_seal_rejection(proc, "run-smoke")
        ok(state_path.read_bytes() == originals[state_path]
           and graph_path.read_bytes() == originals[graph_path]
           and artifacts_path.read_bytes() == originals[artifacts_path]
           and events_path.read_bytes() == originals[events_path]
           and tree_snapshot(smoke_dir) == smoke_before,
           "rejected run-smoke executes no smoke command and changes no result/state/event bytes")
    finally:
        for path, raw in originals.items():
            path.write_bytes(raw)
        restore_tree(smoke_dir, smoke_before)

    # Re-open one completed RUN only inside the fixture.  A failed update would
    # otherwise persist status/note/ended_at and append an event.
    originals = {path: path.read_bytes() for path in
                 (state_path, graph_path, artifacts_path, events_path, spec_path)}
    try:
        state = json.loads(originals[state_path].decode("utf-8"))
        run = next(r for r in state.get("runs") or []
                   if r.get("node") == node_id and r.get("status") in ("finished", "failed"))
        run["status"] = "running"
        wj(d.repo, ".evo/state.json", state)
        fixture_state = state_path.read_bytes()
        tamper_spec(originals[spec_path])
        proc = cli("run-update", "--run", run["id"], "--status", "failed",
                   "--note", "adversarial update must never be persisted")
        assert_seal_rejection(proc, "run-update")
        ok(state_path.read_bytes() == fixture_state
           and graph_path.read_bytes() == originals[graph_path]
           and artifacts_path.read_bytes() == originals[artifacts_path]
           and events_path.read_bytes() == originals[events_path],
           "rejected run-update leaves the reopened RUN and every persisted side effect unchanged")
    finally:
        for path, raw in originals.items():
            path.write_bytes(raw)

    # Likewise, make the node/artifacts look retired only for this fixture.  A
    # successful revive would clear retire_reason, restore artifacts and event
    # the user decision; preflight must reject before all three mutations.
    originals = {path: path.read_bytes() for path in
                 (state_path, graph_path, artifacts_path, events_path, spec_path)}
    try:
        fixture_graph = json.loads(originals[graph_path].decode("utf-8"))
        retired = next(n for n in fixture_graph["nodes"] if n["id"] == node_id)
        retired["retire_reason"] = "adversarial preflight fixture"
        wj(d.repo, ".evo/graph.json", fixture_graph)
        fixture_graph_bytes = graph_path.read_bytes()
        fixture_registry = json.loads(originals[artifacts_path].decode("utf-8"))
        owned = [a for a in fixture_registry.get("artifacts") or [] if a.get("node") == node_id]
        ok(bool(owned), "revive preflight fixture owns at least one registered artifact")
        for artifact in owned:
            artifact["status"] = "stale"
        wj(d.repo, ".evo/artifacts.json", fixture_registry)
        fixture_artifact_bytes = artifacts_path.read_bytes()
        tamper_spec(originals[spec_path])
        proc = cli("revive", "--node", node_id, "--note",
                   "adversarial revival must never be persisted")
        assert_seal_rejection(proc, "revive")
        ok(graph_path.read_bytes() == fixture_graph_bytes
           and artifacts_path.read_bytes() == fixture_artifact_bytes
           and state_path.read_bytes() == originals[state_path]
           and events_path.read_bytes() == originals[events_path],
           "rejected revive preserves retire_reason, stale artifacts, state and event history")
    finally:
        for path, raw in originals.items():
            path.write_bytes(raw)

    ok(all(path.read_bytes() == raw for path, raw in repository_before.items()),
       "CLI preflight fixtures restore the completed repository bytes exactly")


def scientific_axes_orthogonality_checks(d):
    """Scope, novelty and theory are independent declarations, not one ladder."""
    section("scientific axes: Scope x Novelty x Theory remain orthogonal")
    lane = next(row for row in d.state()["lanes"]
                if row.get("winner_sketch") and row.get("intent") != "platform")
    programs = json.loads((d.repo / lane["sketches_path"]).read_text(encoding="utf-8"))
    frozen = next(row for row in programs["sketches"]
                  if row["sketch_id"] == lane["winner_sketch"])
    base = json.loads(json.dumps(frozen))
    for field in ("diagnosis_digest", "hypothesis_ids", "mech_card_ids",
                  "theory_target", "theory_rigor", "theory_obligations"):
        base.pop(field, None)
    base["collision_queries"] = [
        long(70, "find the nearest executable program with the same effect-bearing mechanism relation"),
        long(70, "test whether prior work can emulate the declared operators under the same resource vector"),
    ]
    chain = (base.get("effect_case") or {}).get("chain") or []
    for link in chain:
        link.setdefault("minimum_worthwhile_delta", 0.003)
        link.setdefault("expected_delta_interval", [0.003, 0.02])
    target_cells = list(dict.fromkeys(str(link.get("target_cell")) for link in chain))
    base["claim_scope"] = {
        "kind": "generalist", "target_cells": target_cells,
        "guardrail_cells": ["C3"],
        "rationale": long(80, "the candidate freezes every target reached by its effect chain before any winner or result is observed"),
    }

    def axis_case(scope, novelty_kind, theory_role, *, theory_rigor=None, research=True):
        cand = json.loads(json.dumps(base))
        cand["sketch_id"] = "KAXIS"
        cand["change_scope"] = scope
        novelty = cand["novelty"]
        novelty["kind"] = novelty_kind
        novelty["known_primitives"] = (["sequence encoder", "importance ratio"]
                                       if novelty_kind == "composition" else ["sequence encoder"])
        novelty.pop("non_reducibility", None)
        novelty.pop("load_bearing_test", None)
        novelty.pop("semantic_break", None)
        if novelty_kind in eprogram.RESEARCH_NOVELTY:
            novelty["non_reducibility"] = long(130, "the shared state relation cannot be emulated by independently composing the named primitives under the matched program")
            novelty["load_bearing_test"] = long(105, "removing KC1 restores the comparator update and eliminates the registered intermediate and target effect")
        if novelty_kind == "paradigm":
            novelty["semantic_break"] = long(130, "the program changes the learned object from observed-outcome prediction to an action-indexed value process used by learning and inference")
        cand["theory_role"] = theory_role
        if theory_role != "none":
            cand["theory_target"] = long(80, "derive the conditions under which the effect-bearing state relation identifies value and constrains the executable operators")
        if theory_role == "derivational":
            cand["theory_rigor"] = theory_rigor
            cand["theory_obligations"] = [
                {"id": "DO1", "kernel_refs": ["KC1"], "operator_refs": ["OP2"],
                 "satisfaction": long(80, "DO1 is realized by the mapped effect-bearing update relation in KC1 and OP2")},
                {"id": "DO2", "kernel_refs": ["KC1"], "operator_refs": ["OP2"],
                 "satisfaction": long(80, "DO2 is realized by carrying that mapped state relation into the inference-readable value state")},
            ]
        origin = "theory_derived" if theory_role == "derivational" else "constructive"
        errs = eprogram.candidate_errors(
            cand, where=f"{scope}/{novelty_kind}/{theory_role}",
            min_level=eprogram.compute_level(cand), research=research,
            search_origin=origin,
            model_parent_count=len((cand.get("program") or {}).get("scientific_parents") or []))
        ok(not errs, f"orthogonal axis combination is valid: {scope}/{novelty_kind}/{theory_role}: {errs}")
        return cand

    local_paradigm = axis_case("local", "paradigm", "none")
    full_composition = axis_case("full_program", "composition", "explanatory", research=False)
    full_irreducible = axis_case("full_program", "irreducible", "derivational",
                                 theory_rigor="full")
    ok(eprogram.compute_level(local_paradigm) == 2
       and local_paradigm["novelty"]["kind"] == "paradigm",
       "local implementation scope does not cap novelty at composition")
    ok(eprogram.compute_level(full_composition) == 4
       and full_composition["novelty"]["kind"] == "composition"
       and eprogram.kernel_ids(full_composition),
       "full reconstruction may compose known mechanisms while retaining an effect-bearing KC map")
    ok(full_irreducible["theory_rigor"] == "full"
       and full_irreducible["novelty"]["kind"] == "irreducible",
       "full theory rigor is independent of full scope and irreducible novelty")


def seed_and_ablation_policy_checks(d):
    """Exercise the two costly-evidence contracts without launching real work."""
    section("training-seed replication + targeted-ablation contracts and dashboard")
    store = d.store()
    st, graph, reg = store.load_state(), store.load_graph(), store.load_artifacts()
    cfg = store.load_config()
    pre_cfg = json.loads(json.dumps(cfg))
    pre_cfg["evidence_policy"]["training_replication"].update({
        "mode": "preplanned", "planned_runs": 3, "aggregation": "mean",
        "basis": long(75, "the user approved three full runs before evolution because known optimizer instability can reverse the expected gain"),
        "revisit_when": long(55, "reopen only if the training process becomes deterministic or full-run cost changes materially"),
    })
    ok(not econfig.validate_config(pre_cfg), "a fully specified user-approved preplanned seed policy validates")
    bad_cfg = json.loads(json.dumps(pre_cfg))
    bad_cfg["evidence_policy"]["training_replication"]["planned_runs"] = 1
    ok(any(e.startswith("CONFIG_TRAINING_REPLICATION_PREPLANNED_RUNS")
           for e in econfig.validate_config(bad_cfg)),
       "preplanned replication cannot hide behind one run")
    legacy_cfg = json.loads(json.dumps(cfg))
    legacy_cfg["evidence_policy"]["max_extra_costly_arms_pre_signal"] = 0
    ok(any(e.startswith("CONFIG_EVIDENCE_LEGACY_COST_BUCKET")
           for e in econfig.validate_config(legacy_cfg)),
       "the ambiguous generic costly-arm bucket is rejected at configuration")

    ctx_pre = evalid.Ctx(store, st, pre_cfg, graph, reg)
    base_spec = json.loads((d.repo / d.node("N022")["spec"]).read_text(encoding="utf-8"))
    repeated = json.loads(json.dumps(base_spec))
    seeds = [11, 29, 47]
    repeated["workflow"] = {"stages": [
        stage("pretrain", uri="oss://v91/pretrain/seed-{seed}", key="pretrain|v91|seed={seed}",
              launch='python train.py --stage pretrain --seed {seed}'),
        stage("posttrain", uri="oss://v91/posttrain/seed-{seed}", key="posttrain|v91|seed={seed}",
              consumes=[{"stage": "pretrain"}],
              launch='python train.py --stage posttrain --seed {seed}'),
    ]}
    for rs in repeated["workflow"]["stages"]:
        rs["metrics_file"] = f".evo/v91_checks/{rs['name']}_seed-{{seed}}.json"
    repeated["training_replication"] = {
        "mode": "preplanned", "runs": 3, "seeds": seeds, "aggregation": "mean",
        "source": "workflow",
    }
    errs = evalid._spec_errors(ctx_pre, repeated, expect_role="variant",
                               expect_parents=repeated["parents"], expect_level=repeated["level"],
                               where="preplanned replication spec")
    ok(not any(e.startswith(("SPEC_TRAINING_REPLICATION", "SPEC_STAGE_MULTIPLICITY",
                             "SPEC_STAGE_REPLICATION")) for e in errs),
       f"each approved seed binds to the complete two-stage workflow: {errs}")
    ok(econfig.stage_budget_totals(repeated)["wallclock_minutes"] == 180.0,
       "workflow approval multiplies two 30-minute stage caps by all three complete seed runs")

    rstage = repeated["workflow"]["stages"][0]
    stage_metrics = str(econfig.resolve_seed_template(rstage["metrics_file"], 11))
    usage = {k: float(v) / 2 for k, v in ((rstage.get("budget") or {}).get("limits") or {}).items()}
    wj(d.repo, stage_metrics, {"seed": 11, "summary": {"loss": 0.21}, "usage": usage})
    errs = evalid.stage_result_errors(ctx_pre, rstage, stage_metrics, None,
                                      where="seed-11 pretrain result", expected_seed=11,
                                      expected_metrics_file=stage_metrics)
    ok(not errs, f"one stage result represents exactly one seed lane: {errs}")
    wj(d.repo, stage_metrics, {"seed": 29, "summary": {"loss": 0.21}, "usage": usage})
    errs = evalid.stage_result_errors(ctx_pre, rstage, stage_metrics, None,
                                      where="wrong seed result", expected_seed=11,
                                      expected_metrics_file=stage_metrics)
    ok(any(e.startswith("STAGE_RESULT_SEED") for e in errs),
       "a stage result from another seed cannot be absorbed into the current workflow lane")
    bad_templates = json.loads(json.dumps(repeated))
    bad_templates["workflow"]["stages"][1]["metrics_file"] = "shared_posttrain.json"
    errs = evalid.training_replication_errors(ctx_pre, bad_templates, role="variant",
                                               where="shared seed output")
    ok(any(e.startswith("SPEC_TRAINING_REPLICATION_TEMPLATE") for e in errs),
       "preplanned seed lanes cannot share an untemplated output path")

    expected = repeated["training_replication"]
    metric = {"value": 0.8, "training_replication": {"aggregation": "mean", "runs": [
        {"seed": 11, "value": 0.7, "source": "run/seed-11"},
        {"seed": 29, "value": 0.8, "source": "run/seed-29"},
        {"seed": 47, "value": 0.9, "source": "run/seed-47"},
    ]}}
    ok(not evalid.metric_evidence_errors(ctx_pre, "auc", metric, expected),
       "the engine accepts and recomputes an explicit preplanned per-seed aggregate")
    replication_view = edash._result_view(metric)
    ok(replication_view["interval"] is None
       and replication_view["evidence"]["kind"] == "training_replication"
       and replication_view["evidence"]["aggregation"] == "mean"
       and [(r["seed"], r["value"]) for r in replication_view["evidence"]["runs"]]
           == [(11, 0.7), (29, 0.8), (47, 0.9)],
       "dashboard preserves bounded seed/value replication evidence without inventing an interval")
    scalar_view = edash._result_view(0.8)
    ok(scalar_view["interval"] is None and scalar_view["evidence"] == {
        "kind": "scalar", "uncertainty_supplied": False},
       "dashboard labels a scalar as point-only rather than a fake 95% interval")
    wrong = json.loads(json.dumps(metric))
    wrong["value"] = 0.81
    ok(any(e.startswith("EVAL_TRAINING_REPLICATION_RECOMPUTE")
           for e in evalid.metric_evidence_errors(ctx_pre, "auc", wrong, expected)),
       "an authored mean that disagrees with the disclosed seed values is rejected")
    ok(any(e.startswith("EVAL_TRAINING_REPLICATION_MISSING")
           for e in evalid.metric_evidence_errors(ctx_pre, "auc", 0.8, expected)),
       "a scalar cannot conceal the runs required by a preplanned protocol")
    ctx_single = evalid.Ctx(store, st, cfg, graph, reg)
    errs = evalid.training_replication_errors(ctx_single, repeated, role="variant",
                                               where="record-only project")
    ok(any(e.startswith("SPEC_TRAINING_REPLICATION_SINGLE")
           for e in errs),
       "record-only policy rejects a planner-created seed array")

    ablation_contract = {
        "parent": repeated["parents"][0],
        "question": long(70, "whether the parent's gain is caused by the changed objective rather than an unchanged optimization side effect"),
        "competing_explanations": [
            {"id": "X1", "statement": long(50, "the changed objective carries the gain through the claimed mechanism")},
            {"id": "X2", "statement": long(50, "an unchanged optimization side effect carries the observed gain")},
        ],
        "intervention": long(50, "remove only the changed objective term while freezing the parent recipe"),
        "trigger_evidence": long(40, f"parent {repeated['parents'][0]} improved but left this causal fork unresolved"),
        "decision_if_effect": long(60, "retain the objective mechanism and stop descendants that remove its causal channel"),
        "decision_if_no_effect": long(60, "drop the objective story and investigate the alternative optimization explanation"),
        "why_cheaper_evidence_insufficient": long(60, "existing logs and fixed-output evaluation cannot remove a train-time term"),
        "costly_runs": 1,
    }
    ab_spec = json.loads(json.dumps(base_spec))
    ab_spec["experiment_purpose"] = "targeted_ablation"
    ab_spec["ablation"] = ablation_contract
    ab_spec["evidence_plan"] = {"extra_eval_arms": 0, "declared_checks": []}
    ab_spec["training_replication"] = {
        "mode": "single", "runs": 1, "seeds": [1009], "aggregation": "none",
        "source": "workflow",
    }
    ab_stage = ab_spec["workflow"]["stages"][0]
    ab_stage["control"] = {"mode": "fixed", "multiplicity": "single"}
    ab_stage.pop("ledger_file", None)
    errs = evalid._spec_errors(ctx_pre, ab_spec, expect_role="variant",
                               expect_parents=ab_spec["parents"], expect_level=ab_spec["level"],
                               where="targeted ablation spec")
    ok(not any(e.startswith(("SPEC_TRAINING_REPLICATION", "SPEC_ABLATION")) for e in errs),
       f"preplanned projects still keep each targeted ablation to one diagnostic run: {errs}")
    bad_ab = json.loads(json.dumps(ab_spec))
    bad_ab["training_replication"] = dict(expected)
    errs = evalid.training_replication_errors(ctx_pre, bad_ab, role="variant", where="ablation seed cross-product")
    ok(any(e.startswith("SPEC_TRAINING_REPLICATION_SINGLE")
           for e in errs),
       "targeted ablation cannot multiply itself by the project's candidate seed count")

    fake = {"id": "NABL", "title": "one-run ablation", "role": "variant", "level": 2,
            "experiment_purpose": "targeted_ablation", "parents": [ablation_contract["parent"]],
            "status": "concluded", "verdict": "improved", "retire_reason": None,
            "scores": {"auc": 1.0, "logloss": 0.0, "latency_ms": 0.0},
            "score_evidence": {}, "spec": ".evo/v91_checks/ablation_spec.json"}
    wj(d.repo, fake["spec"], ab_spec)
    g2 = json.loads(json.dumps(graph))
    g2["nodes"].append(fake)
    ok("NABL" in {n["id"] for n in egraph.performance_frontier(g2, cfg)},
       "under record-only evidence, a one-run ablated model remains visible on the diagnostic performance frontier")
    ok("NABL" not in {n["id"] for n in egraph.performance_frontier(g2, pre_cfg)},
       "under preplanned evidence, one diagnostic ablation cannot contaminate the performance frontier")

    dash = edash._data(store, g2, pre_cfg, st, reg)
    dn = next(n for n in dash["nodes"] if n["id"] == "NABL")
    ok(dn["purpose"] == "targeted_ablation" and dn["performance_frontier_eligible"] is False
       and dash["evidence_policy"]["training_replication"]["planned_runs"] == 3,
       "dashboard data exposes node purpose, frontier eligibility and the approved seed count")
    edash.render(store, g2, pre_cfg, st, reg)
    dashboard_html = (d.repo / ".evo/views/DASHBOARD.html").read_text(encoding="utf-8")
    ok("training-seed contract" in dashboard_html and "targeted ablation" in dashboard_html
       and "cheap evidence plan" in dashboard_html and '"performance_frontier_eligible": false' in dashboard_html,
       "self-contained frontend renders seed, cheap-probe and ablation semantics instead of only total budget")
    meta_rel = ".evo/ideas/IABL.meta.json"
    wj(d.repo, meta_rel, {"idea": "IABL", "experiment_purpose": "targeted_ablation"})
    gate = {"id": "GABL", "kind": "idea_approval", "status": "open",
            "subject": {"idea": "IABL"}}
    ok(esched.Engine(store)._maybe_auto_resolve(gate) is False,
       "targeted ablation cannot auto-approve even in full_auto mode")


def workflow_replication_execution_checks(source_d):
    """Execute 2 stages x 3 seeds and audit restart/probe provenance."""
    section("complete-workflow seed execution + probe artifact closure")
    repo = OUT / "workflow_replication"
    make_repo(repo, with_git=False)
    store = estore.Store(repo)
    store.init("workflow replication", "repeat every stage for each approved seed")
    cfg = project_cfg(source_d)
    cfg["evidence_policy"]["training_replication"].update({
        "mode": "preplanned", "planned_runs": 3, "aggregation": "mean",
        "basis": long(70, "three complete runs were approved because optimizer instability is part of the scientific question"),
        "revisit_when": long(50, "revisit if training becomes deterministic or the resource contract changes"),
    })
    wj(repo, ".evo/config.json", cfg)
    st, graph = store.load_state(), store.load_graph()
    nid = store.next_id(st, "N")
    stages = [
        stage("pretrain", uri="oss://workflow-rep/pretrain/seed-{seed}",
              key="workflow-rep|pretrain|seed={seed}",
              launch="python train.py --stage pretrain --seed {seed}"),
        stage("posttrain", uri="oss://workflow-rep/posttrain/seed-{seed}",
              key="workflow-rep|posttrain|seed={seed}", consumes=[{"stage": "pretrain"}],
              launch="python train.py --stage posttrain --seed {seed}"),
    ]
    for stg in stages:
        stg["metrics_file"] = f".evo/nodes/{nid}/runs/{stg['name']}_seed-{{seed}}.json"
    spec_rel = f".evo/nodes/{nid}/NODE_SPEC.json"
    spec = {
        "title": "two-stage complete-run fixture", "role": "root", "parents": [],
        "code_parent": None, "level": 3, "experiment_purpose": "candidate",
        "experiment_class": "train", "cost_class": "medium", "workdir": "workareas/replicated",
        "evidence_plan": {"extra_eval_arms": 0, "declared_checks": ["mechanism_probe"]},
        "training_replication": {"mode": "preplanned", "runs": 3, "seeds": [11, 29, 47],
                                 "aggregation": "mean", "source": "workflow"},
        "workflow": {"stages": stages},
        "probe_execution": {
            "mode": "same_run", "signal": long(40, "calibration slope on the frozen exploration slice"),
            "expect": long(20, "the slope moves toward one"),
            "artifact": f".evo/nodes/{nid}/probes/seed-{{seed}}.json",
            "required_fields": ["calibration_slope"], "producer_stage": "posttrain",
            "smoke_artifact": f".evo/nodes/{nid}/probes/smoke.json",
        },
        "smoke_plan": [{"name": "probe", "cmd": "python probe.py",
                        "must_exist": [f".evo/nodes/{nid}/probes/smoke.json"]}],
        "eval": {"run": "python eval.py", "metrics_file": f".evo/nodes/{nid}/eval/metrics.json",
                 "budget": {"limits": {"wallclock_minutes": 30}}},
    }
    wj(repo, spec_rel, spec)
    node = egraph.new_node(graph, nid, title=spec["title"], role="root", parents=[],
                           code_parent=None, level=3, lane=None, round_="R001",
                           idea_doc=None, spec=spec_rel)
    node["workdir"] = spec["workdir"]
    node["status"] = "stage_ready"
    store.save_state(st)
    store.save_graph(graph)

    def complete(seed, stage_name, *, assert_missing_probe=False):
        eng = esched.Engine(store)
        current = eng.node(nid)
        sidx = int(current["stage_cursor"])
        ridx = int(current["replica_index"])
        stg = stages[sidx]
        ok(stage_name == stg["name"] and seed == spec["training_replication"]["seeds"][ridx],
           f"scheduler position is seed={seed}/{stage_name}")
        metrics_rel = str(econfig.resolve_seed_template(stg["metrics_file"], seed))
        probe = spec["probe_execution"]
        probe_rel = str(econfig.resolve_seed_template(probe["artifact"], seed))
        launch_rel = f".evo/nodes/{nid}/stages/{stage_name}_seed-{seed}.json"
        request = econfig.tracked_budget(stg.get("budget"), eng.cfg)
        run = eng._prepare_run(
            current, "stage", request, stage=stage_name, stage_index=sidx,
            replica_seed=seed, replica_index=ridx, replica_total=3,
            resolved_launch=str(econfig.resolve_seed_template(stg.get("launch") or "", seed)),
            declared_metrics_file=metrics_rel)
        # the job executes AFTER the prepared intent (real completed-mode
        # order); R7 archives any pre-attempt leftovers at prepare, so the
        # landing is written post-prepare exactly like a real job's output
        wj(repo, metrics_rel, {"seed": seed, "summary": {"loss": 0.2 + sidx / 100},
                               "usage": {"wallclock_minutes": 2.0}})
        launch = {"stage": stage_name, "mode": "completed", "seed": seed,
                  "run": run["id"], "attempt_token": run["attempt_token"],
                  "metrics_file": metrics_rel}
        wj(repo, launch_rel, launch)
        task = {"id": f"fixture-{seed}-{stage_name}",
                "subject": {"node": nid, "run": run["id"], "stage": stage_name, "replica_seed": seed,
                            "replica_index": ridx, "replica_total": 3},
                "outputs": [launch_rel], "resource_reservation": request}
        if assert_missing_probe:
            ok(not evalid.v_stage_launch(eng.ctx(), task),
               "a completed launch records execution truth even while same-RUN probe evidence is late")
            eng._apply_stage_launch(task)
            eng.save()
            pending = egraph.by_id(store.load_graph())[nid]
            ok(pending["status"] == "evidence_pending" and pending["stage_cursor"] == sidx,
               "missing same-RUN probe holds evidence adoption without forgetting or rerunning the stage")
            wj(repo, probe_rel, {"calibration_slope": 0.9 + seed / 10000})
            esched.Engine(store).reconcile_run(run["id"])
            return
        if stage_name == "posttrain":
            wj(repo, probe_rel, {"calibration_slope": 0.9 + seed / 10000})
        errs = evalid.v_stage_launch(eng.ctx(), task)
        ok(not errs, f"seed={seed}/{stage_name} completed launch validates: {errs}")
        eng._apply_stage_launch(task)
        eng.save()

    # Finish one complete run, then simulate the implementation fix path. Old
    # runs remain auditable but cannot contribute to the final aggregate.
    complete(11, "pretrain")
    complete(11, "posttrain", assert_missing_probe=True)
    eng = esched.Engine(store)
    eng._restart_workflow_after_fix(eng.node(nid))
    eng.save()
    reset_node = egraph.by_id(store.load_graph())[nid]
    old_runs = [r for r in store.load_state()["runs"] if r.get("node") == nid]
    ok(reset_node["stage_cursor"] == 0 and reset_node["replica_index"] == 0
       and all(r.get("superseded") for r in old_runs),
       "an implementation change invalidates all earlier seed lanes and restarts at seed 1/stage 1")
    ok(all("/evidence/" in str(r.get("metrics_file") or "") and r.get("seal_history")
           for r in old_runs)
       and any((repo / str(row.get("snapshot_artifact") or "")).exists()
               for r in old_runs for row in (r.get("probe_artifact_snapshots") or [])),
       "superseded RUN metrics and probe evidence remain in immutable per-attempt snapshots")

    for seed in (11, 29, 47):
        complete(seed, "pretrain")
        complete(seed, "posttrain")
    final_state, final_graph, final_reg = store.load_state(), store.load_graph(), store.load_artifacts()
    final_node = egraph.by_id(final_graph)[nid]
    active_runs = [r for r in final_state["runs"] if r.get("node") == nid and not r.get("superseded")]
    order = [(r.get("replica_seed"), r.get("stage")) for r in active_runs]
    expected_order = [(seed, sname) for seed in (11, 29, 47) for sname in ("pretrain", "posttrain")]
    ok(final_node["status"] == "workflow_done" and order == expected_order,
       f"every seed traverses all stages in order before evaluation: {order}")
    ok([x["seed"] for x in final_node["replicas_completed"]] == [11, 29, 47],
       "node state records completion of the exact preplanned seed set")
    available = [a for a in final_reg["artifacts"] if a.get("node") == nid and a.get("status") == "available"]
    ok(len(available) == 6 and len({a["uri"] for a in available}) == 6,
       "two stages x three seeds publish six non-overwriting artifacts")
    ctx = evalid.Ctx(store, final_state, cfg, final_graph, final_reg)
    stm = evalid.stage_metrics_of(ctx, nid)
    ok(len(stm) == 6 and all(f"seed={seed}/" in " ".join(stm) for seed in (11, 29, 47)),
       "superseded runs are excluded and all six active stage summaries remain visible")

    metrics = {"_usage": {"wallclock_minutes": 1.0}}
    for key, value in (("auc", 0.8), ("logloss", 0.6), ("latency_ms", 100.0)):
        metrics[key] = {"value": value, "training_replication": {
            "aggregation": "mean",
            "runs": [{"seed": seed, "value": value, "source": f"run/seed-{seed}/final"}
                     for seed in (11, 29, 47)],
        }}
    observations = []
    for expected in evalid.expected_probe_observations(spec):
        pdata = json.loads((repo / expected["artifact"]).read_text(encoding="utf-8"))
        observations.append({"seed": expected["seed"], "artifact": expected["artifact"],
                             "values": {"calibration_slope": pdata["calibration_slope"]}})
    metrics["_mechanism_probe"] = {
        "mode": spec["probe_execution"]["mode"], "signal": spec["probe_execution"]["signal"],
        "expect": spec["probe_execution"]["expect"], "required_fields": ["calibration_slope"],
        "observations": observations,
    }
    metrics_rel = f".evo/nodes/{nid}/eval/metrics.json"
    wj(repo, metrics_rel, metrics)
    errs = evalid.evaluation_result_errors(ctx, spec, metrics_rel, where="replicated workflow evaluation")
    ok(not errs, f"evaluation binds aggregate metrics and one probe artifact per complete seed run: {errs}")
    wrong = json.loads(json.dumps(metrics))
    wrong["_mechanism_probe"]["observations"][0]["values"]["calibration_slope"] += 0.1
    errs = evalid.evaluation_result_errors(ctx, spec, metrics_rel, where="tampered probe", metrics_data=wrong)
    ok(any(e.startswith("EVAL_PROBE_VALUE_MISMATCH") for e in errs),
       "normalized probe values cannot drift from the recorded runtime JSON")
    D(repo).doctor_clean("complete-workflow seed execution fixture")


def targeted_ablation_flow_checks(d):
    """End-to-end causal diagnostic: dedicated design/review, two human gates,
    one fixed run, controlled-change audit, evaluation and causal settlement."""
    section("targeted ablation end-to-end: no novelty pipeline, no seed/control multiplication")
    store = d.store()
    st, graph = store.load_state(), store.load_graph()
    parent_node = next(n for n in reversed(graph["nodes"])
                       if n.get("status") == "concluded" and n.get("role") not in ("platform", "baseline")
                       and n.get("experiment_purpose") == "candidate" and n.get("result_doc"))
    parent = parent_node["id"]
    lid = store.next_id(st, "L")
    rid = "RABL"
    lane = {
        "id": lid, "round": rid, "name": "causal-one-factor", "intent": "exploit",
        "search_origin": "repair", "experiment_purpose": "targeted_ablation",
        "min_level": 0, "parents": [parent],
        "bottleneck_ids": [], "brief_md": brief(d, rid, "causal-one-factor"),
        "status": "ablation_design", "cycles": {"sketch": 0, "mature": 0, "theory": 0, "ablation": 0},
        "theory_cycle": 0, "required_topics": [], "theory_path": None,
        "formal": False, "formal_kind": None, "problem_path": None, "focus": None,
        "diagnosis_path": None, "diagnosis_digest": None,
        "sketches_path": None, "tournament_path": None, "winner_sketch": None,
        "idea": None, "node": None, "abandon_reason": None,
    }
    st["lanes"].append(lane)
    store.save_state(st)

    out = direct_lane_next(d, lid, "design_ablation")
    card = (d.repo / out["card"]).read_text(encoding="utf-8")
    ok("not a new-method contest" in card and "Never schedule a fresh parent/control" in card,
       "dedicated design card rejects novelty theater and a fresh control arm")
    w_design_ablation(d, out, lid, bad="missing_trigger")
    sub_rej(d, out, "ABLATION_TRIGGER_ARTIFACT_MISSING")
    w_design_ablation(d, out, lid)
    sub_ok(d, out)

    out = direct_lane_next(d, lid, "review_ablation")
    w_review_ablation(d, out, lid, verdict="REVISE")
    sub_ok(d, out)
    ok(d.lane(lid)["status"] == "ablation_design",
       "a repairable causal design revises in place instead of falling into sketch/tournament")
    out = direct_lane_next(d, lid, "design_ablation")
    w_design_ablation(d, out, lid)
    sub_ok(d, out)
    out = direct_lane_next(d, lid, "review_ablation")
    w_review_ablation(d, out, lid, verdict="ACCEPT")
    sub_ok(d, out)

    gate_out = direct_lane_next(d, lid)
    ok(gate_out.get("kind") == "gate" and gate_out.get("gate_kind") == "idea_approval",
       "full_auto still pauses for user approval of a targeted causal design")
    d.decide(gate_out["gate"], True, "user approves the one-factor causal question and one-run ceiling")

    out = direct_lane_next(d, lid, "plan_node")
    bad_stage = stage(
        "ablation_search", mode="preregistered_adaptive", multiplicity="algorithmic",
        controller=long(60, "choose another objective variant after observing each candidate"),
        stopping_conditions=["stop after four variants"],
        why_multiple=long(55, "several variants would be selected to produce the delivered model"),
        uri=f"oss://mock/{lid}/bad-multiple", key=f"ablation|{lid}|bad-multiple")
    w_plan(d, out, lid, role="variant", workdir=f"workareas/{lid.lower()}-ablation",
           stages=[bad_stage], code_parent=parent, level=0)
    sub_rej(d, out, "SPEC_ABLATION_STAGE_CONTROL")
    good_stage = stage("changed_component_run", uri=f"oss://mock/{lid}/one-run",
                       key=f"ablation|{lid}|factor=counterfactual-objective")
    w_plan(d, out, lid, role="variant", workdir=f"workareas/{lid.lower()}-ablation",
           stages=[good_stage], code_parent=parent, level=0)
    sub_ok(d, out)
    nid = d.lane(lid)["node"]
    ok(d.node(nid)["level"] == 0 and egraph.level_label(d.node(nid)) == "diagnostic",
       "internal level zero is displayed as diagnostic, not as a fake L0 idea")

    out = direct_node_next(d, nid, "implement")
    implement_card = (d.repo / out["card"]).read_text(encoding="utf-8")
    ok("experiment_purpose=targeted_ablation" in implement_card and
       "change only the registered factor" in implement_card and
       "Diagnostics without a kernel use a" in implement_card,
       "implementation card does not invite an ablation to touch a second file merely to satisfy candidate ceremony")
    do_implement(d, out, nid)
    sub_ok(d, out)
    out = direct_node_next(d, nid, "smoke")
    ok(d.smoke(nid)["status"] == "pass", "targeted ablation smoke passes")
    sub_ok(d, out)
    out = direct_node_next(d, nid, "ablation_fidelity")
    w_ablation_fidelity(d, out, nid, bad="missing_control")
    sub_rej(d, out, "ABLATION_FIDELITY_CONTROLS")
    w_ablation_fidelity(d, out, nid)
    sub_ok(d, out)

    workflow_gate = direct_node_next(d, nid)
    ok(workflow_gate.get("kind") == "gate" and workflow_gate.get("gate_kind") == "workflow_approval",
       "full_auto also pauses before spending the one costly ablation run")
    d.decide(workflow_gate["gate"], True, "user approves the audited fixed/single workflow")
    out = direct_node_next(d, nid, "stage_launch")
    metrics_rel = f"{d.node(nid)['workdir']}/ablation_stage_metrics.json"
    write_stage_result(d, nid, "changed_component_run", metrics_rel, {"loss": 0.12})
    w_launch(d, out, "changed_component_run", mode="completed", metrics_rel=metrics_rel)
    sub_ok(d, out)

    out = direct_node_next(d, nid, "evaluate")
    score = float((parent_node.get("scores") or {}).get("auc") or 0.772) + 0.005
    w_eval(d, out, nid, score, logloss=0.55, latency=100.0)
    sub_ok(d, out)
    out = direct_node_next(d, nid, "conclude")
    w_conclude(d, out, nid)
    sub_ok(d, out)
    node = d.node(nid)
    ok(node.get("ablation_result", {}).get("supports") == "X1" and d.lane(lid)["status"] == "done",
       "causal settlement follows the preregistered X1/X2 decision map and closes the lane")
    lane_task_types = {t["type"] for t in d.state()["tasks"] if (t.get("subject") or {}).get("lane") == lid}
    ok(not lane_task_types.intersection({"diagnose", "deep_read", "sketch", "tournament",
                                         "mature", "red_team", "fidelity"}),
       f"diagnostic never traverses candidate novelty or ordinary fidelity stages: {lane_task_types}")
    gates = [g for g in d.state()["gates"] if (g.get("subject") or {}).get("lane") == lid or
             (g.get("subject") or {}).get("node") == nid]
    ok({g["kind"] for g in gates} >= {"idea_approval", "workflow_approval"}
       and all(g["status"] == "approved" for g in gates),
       "both targeted-ablation gates were explicit user decisions")
    html = (d.repo / ".evo/views/DASHBOARD.html").read_text(encoding="utf-8")
    ok("causal settlement" in html and '"level_label": "diagnostic"' in html,
       "frontend exposes diagnostic identity and the causal outcome separately from performance verdict")

    # A causal reviewer can kill a low-value diagnostic before either user gate
    # or any implementation/training task exists.  It must not fall back into
    # the candidate sketch pipeline.
    st = store.load_state()
    rejected_lid = store.next_id(st, "L")
    rejected_lane = dict(lane)
    rejected_lane.update({
        "id": rejected_lid, "round": "RABR", "name": "causal-reject-before-compute",
        "brief_md": brief(d, "RABR", "causal-reject-before-compute"),
        "status": "ablation_design", "idea": None, "node": None,
        "abandon_reason": None,
        "cycles": {"sketch": 0, "mature": 0, "theory": 0, "ablation": 0},
    })
    st["lanes"].append(rejected_lane)
    store.save_state(st)
    out = direct_lane_next(d, rejected_lid, "design_ablation")
    w_design_ablation(d, out, rejected_lid)
    sub_ok(d, out)
    out = direct_lane_next(d, rejected_lid, "review_ablation")
    w_review_ablation(d, out, rejected_lid, verdict="REJECT_NOT_WORTH_COST")
    sub_ok(d, out)
    rejected = d.lane(rejected_lid)
    ok(rejected["status"] == "abandoned" and rejected.get("node") is None,
       "a rejected causal diagnostic is killed before user gates, implementation and compute")
    rejected_types = {t["type"] for t in d.state()["tasks"]
                      if (t.get("subject") or {}).get("lane") == rejected_lid}
    ok(rejected_types == {"design_ablation", "review_ablation"},
       f"rejected diagnostic created no candidate or execution tasks: {rejected_types}")
    d.doctor_clean("targeted ablation end-to-end")


def scientific_transition_checks(source_d):
    """Exercise scientific continuation as a third outcome, not a fake failure."""
    section("scientific continuation: pass, stop, malformed evidence, completed/background parity")
    repo = OUT / "scientific_transition"
    make_repo(repo, with_git=False)
    store = estore.Store(repo)
    store.init("scientific transition", "stop expensive work when a frozen prerequisite is refuted")
    wj(repo, ".evo/config.json", project_cfg(source_d))
    d = D(repo)

    def add_node(label, observed=None, *, missing_metric=False, completed=False,
                 disappear_after_validation=False):
        st, graph, reg = store.load_state(), store.load_graph(), store.load_artifacts()
        nid = store.next_id(st, "N")
        lid = store.next_id(st, "L")
        idea_base = f".evo/ideas/{label}"
        wt(repo, f"{idea_base}.md", md(
            ("Mechanism", long(80, "the method requires baseline collapse before the tied readout can be informative")),
            ("Predictions", long(80, "final predictions are deliberately not fabricated if the prerequisite misses"))))
        wj(repo, f"{idea_base}.meta.json", {
            "assumptions": [{"id": "A1", "statement": long(45, "the frozen baseline exhibits collapse under the registered protocol")}],
            "predictions": [
                {"id": "P1", "metric": "auc", "comparison": ">=", "value": 0.8,
                 "rationale": long(45, "the final model should improve the target if the prerequisite holds")},
                {"id": "P2", "metric": "logloss", "comparison": "<=", "value": 0.6,
                 "rationale": long(45, "the final model should preserve calibration if the prerequisite holds")},
            ],
        })
        metrics_rel = f"workareas/{label}/gate_metrics.json"
        first = {
            "name": "prerequisite", "purpose": long(45, "measure the necessary collapse condition before expensive model construction"),
            "launch": "python prerequisite.py", "metrics_file": metrics_rel,
            "control": {"mode": "fixed", "multiplicity": "single"},
            "budget": {"limits": {"wallclock_minutes": 10}},
            "continuation_gate": {
                "id": "collapse_reproduced", "aggregation": "all",
                "predicates": [{"metric": "min_fresh_auc", "comparison": "<", "value": 0.6}],
                "assumptions": ["A1"], "on_miss": "stop_node",
                "rationale": long(70, "without baseline collapse the tied-readout construction cannot test the claimed mechanism"),
            },
            "stage_key": f"prerequisite|{label}|protocol=frozen-v1",
            "produces": [{"name": "eligible baseline state", "kind": "state",
                          "uri": f"oss://scientific/{label}/eligible-state"}],
            "consumes": [],
        }
        second = {
            "name": "expensive_build", "purpose": long(45, "construct the final model only after its necessary prerequisite holds"),
            "launch": "python expensive.py", "metrics_file": f"workareas/{label}/build_metrics.json",
            "control": {"mode": "fixed", "multiplicity": "single"},
            "budget": {"limits": {"gpu_hours": 24}},
            "stage_key": f"build|{label}|v1",
            "produces": [{"name": "candidate", "kind": "weights",
                          "uri": f"oss://scientific/{label}/candidate"}],
            "consumes": [{"stage": "prerequisite"}],
        }
        spec_rel = f".evo/nodes/{nid}/NODE_SPEC.json"
        wj(repo, spec_rel, {
            "title": f"scientific fixture {label}", "role": "root", "parents": [],
            "code_parent": None, "level": 3, "experiment_purpose": "candidate",
            "experiment_class": "train",
            "cost_class": "heavy", "workdir": f"workareas/{label}",
            "evidence_plan": {"extra_eval_arms": 0, "declared_checks": []},
            "training_replication": {"mode": "single", "runs": 1, "seeds": [1009],
                                     "aggregation": "none", "source": "workflow"},
            "workflow": {"stages": [first, second]},
            "smoke_plan": [{"name": "imports", "cmd": f'"{PY}" -c "print(1)"', "timeout_s": 120}],
            "eval": {"run": "python eval.py", "metrics_file": f".evo/nodes/{nid}/eval/metrics.json"},
        })
        node = egraph.new_node(graph, nid, title=f"fixture {label}", role="root", parents=[],
                               code_parent=None, level=3, lane=lid, round_="R001",
                               idea_doc=f"{idea_base}.md", spec=spec_rel)
        node["workdir"] = f"workareas/{label}"
        node["status"] = "stage_ready" if completed else "executing"
        st["lanes"].append({"id": lid, "name": label, "intent": "wildcat",
                            "search_origin": "constructive", "experiment_purpose": "candidate",
                            "round": "R001", "status": "node_created", "node": nid})
        summary = {"other_measurement": 1.0} if missing_metric else {"min_fresh_auc": observed}
        store.save_state(st)
        store.save_graph(graph)
        store.save_artifacts(reg)
        eng = esched.Engine(store)
        run = eng._prepare_run(
            eng.node(nid), "stage", econfig.tracked_budget(first.get("budget"), eng.cfg),
            stage="prerequisite", stage_index=0, replica_seed=1009,
            replica_index=0, replica_total=1, resolved_launch=str(first.get("launch") or ""),
            declared_metrics_file=metrics_rel)
        # written post-prepare (real completed-mode order; R7 archives
        # pre-attempt leftovers at prepare)
        wj(repo, metrics_rel, {"summary": summary, "usage": {"wallclock_minutes": 2}})
        if completed:
            launch_rel = f".evo/nodes/{nid}/stages/LAUNCH_prerequisite.json"
            wj(repo, launch_rel, {"stage": "prerequisite", "mode": "completed",
                                  "seed": 1009, "run": run["id"],
                                  "attempt_token": run["attempt_token"], "metrics_file": metrics_rel})
            task = {"subject": {"node": nid, "run": run["id"], "stage": "prerequisite",
                                 "replica_seed": 1009, "replica_index": 0, "replica_total": 1},
                    "outputs": [launch_rel]}
            errs = evalid.v_stage_launch(eng.ctx(), task)
            ok(not errs, f"completed scientific fixture launch validates: {errs}")
            if disappear_after_validation:
                (repo / metrics_rel).unlink()
                eng._apply_stage_launch(task)
                eng.save()
                pending_node = d.node(nid)
                pending_run = next(r for r in d.state()["runs"] if r["id"] == run["id"])
                ok(pending_run["status"] == "finished" and pending_run["evidence_status"] == "incomplete"
                   and pending_node["status"] == "evidence_pending" and pending_node["stage_cursor"] == 0,
                   "evidence disappearing after validation preserves execution truth and opens same-RUN repair")
            else:
                eng._apply_stage_launch(task)
                eng.save()
        else:
            erun.transition_execution(run, "finished", job="fixture-job", note="fixture producer finished")
            run["metrics_file"] = metrics_rel
            eng._absorb_run(run)
            eng.save()
        return nid, lid, first, metrics_rel

    stop_nid, stop_lid, stop_stage, stop_metrics = add_node("background_stop", 0.658, completed=False)
    stop_node = d.node(stop_nid)
    stop_run = next(r for r in d.state()["runs"] if r["node"] == stop_nid)
    ok(stop_run["status"] == "finished" and stop_run["absorbed"] is True
       and stop_run["scientific_outcome"] == "stop_node",
       f"scientific miss preserves successful execution: {stop_run}")
    ok(stop_node["status"] == "scientific_stop" and stop_node["stage_cursor"] == 0
       and stop_node["stage_failures"] == 0,
       f"scientific miss stops without cursor/failure drift: {stop_node}")
    ok(not [a for a in d.reg()["artifacts"] if a.get("node") == stop_nid],
       "stopped stage does not publish candidate artifacts")
    ok(not store.errors(), "scientific stop does not pollute the execution-error journal")
    before_events = len([e for e in d.events("stage_scientific_stop") if e.get("node") == stop_nid])
    eng = esched.Engine(store)
    eng._absorb_run(eng.store.get_run(eng.st, stop_run["id"]))
    eng.save()
    after_events = len([e for e in d.events("stage_scientific_stop") if e.get("node") == stop_nid])
    ok(before_events == after_events == 1, "re-absorption is idempotent")

    eng = esched.Engine(store)
    out = eng._next_node_task(eng.node(stop_nid))
    eng.save()
    ok(out and out.get("type") == "scientific_conclude", f"scientific stop routes to knowledge conclusion: {out}")
    wj(repo, out["outputs"][0], {
        "node": stop_nid, "verdict": "screened_out",
        "scientific_stop": {"stage": "prerequisite", "run": stop_run["id"],
                            "gate_id": "collapse_reproduced", "decision": "stop_node",
                            "reason": long(55, "all frozen seed measurements remained above the collapse threshold")},
        "unreached_predictions": [
            {"id": "P1", "reason": long(30, "final evaluation was intentionally not reached")},
            {"id": "P2", "reason": long(30, "final evaluation was intentionally not reached")},
        ],
        "root_cause": {"assumptions": ["A1"],
                       "note": long(55, "the frozen baseline-collapse assumption was directly falsified by the census")},
        "observations": [{"statement": long(45, "fresh AUC remained above the registered collapse threshold for every seed"),
                          "where": "prerequisite stage", "measurement": "min_fresh_auc=0.658 versus <0.6",
                          "evidence": stop_metrics}],
        "lessons": [{"scope": "conditional",
                     "statement": long(45, "do not build the tied readout when baseline collapse is absent"),
                     "evidence": long(30, f"{stop_metrics} records the frozen-seed census"),
                     "recommendation": long(35, "screen this prerequisite before allocating accelerator time"),
                     "tags": ["baseline-collapse"]}],
    })
    wt(repo, out["outputs"][1], md(
        ("What was attempted", long(70, "the prerequisite census ran under the frozen protocol before model construction")),
        ("Gate evidence", long(80, "min_fresh_auc was 0.658 against the frozen comparison min_fresh_auc < 0.6")),
        ("Interpretation", long(80, "A1 is refuted for this dataset and the result does not assess unreached final predictions")),
        ("Unexecuted work", long(70, "expensive_build and final evaluation were deliberately skipped"))))
    sub_ok(d, out)
    concluded = d.node(stop_nid)
    ok(concluded["status"] == "concluded" and concluded["verdict"] == "screened_out"
       and concluded["prediction_stats"].get("unreached") == 2
       and concluded["prediction_stats"].get("inconclusive") == 0
       and d.lane(stop_lid)["status"] == "done",
       "scientific negative result concludes as screened_out rather than abandoned/failed/refuted")
    stop_snapshot = edash._data(store, d.graph(), project_cfg(source_d), d.state(), d.reg())
    stop_view = next(node for node in stop_snapshot["nodes"] if node["id"] == stop_nid)["scientific_stop"]
    stop_gate = stop_view["gate"]
    ok(stop_gate["id"] == "collapse_reproduced"
       and stop_gate["aggregation"] == "all" and stop_gate["outcome"] == "stop_node"
       and stop_gate["predicates"] == [{
           "metric": "min_fresh_auc", "comparison": "<", "value": 0.6,
           "observed": 0.658, "passed": False,
       }],
       "dashboard exposes the exact frozen predicate and observation behind a scientific stop")
    ok(any(o.get("node") == stop_nid for o in store.observations())
       and any(l.get("node") == stop_nid for l in store.lessons()),
       "scientific stop reaches phenomenon and lesson memory")
    calibration = "\n".join(ebundle.calibration_block(d.graph()))
    ok("2 unreached" in calibration and "do not affect calibration" in calibration,
       "unreached predictions are visible but excluded from forecast calibration")

    pass_nid, _, _, _ = add_node("background_continue", 0.55, completed=False)
    pass_node = d.node(pass_nid)
    pass_run = next(r for r in d.state()["runs"] if r["node"] == pass_nid)
    ok(pass_run["scientific_outcome"] == "continue" and pass_node["stage_cursor"] == 1
       and pass_node["status"] == "stage_ready",
       f"gate hit advances exactly one stage: run={pass_run}, node={pass_node}")
    ok(len([a for a in d.reg()["artifacts"] if a.get("node") == pass_nid]) == 1,
       "continued stage publishes its declared handoff artifact")

    bad_nid, _, _, bad_metrics = add_node("missing_gate_metric", missing_metric=True, completed=False)
    bad_node = d.node(bad_nid)
    bad_run = next(r for r in d.state()["runs"] if r["node"] == bad_nid)
    ok(bad_run["status"] == "finished" and bad_run["evidence_status"] == "invalid"
       and bad_node["status"] == "evidence_pending" and bad_node["stage_cursor"] == 0,
       "missing gate evidence awaits same-RUN repair; it is never an inferred scientific stop or rerun")
    wj(repo, bad_metrics, {"summary": {"min_fresh_auc": 0.55},
                           "usage": {"wallclock_minutes": 2}})
    esched.Engine(store).reconcile_run(bad_run["id"])
    ok(d.node(bad_nid)["status"] == "stage_ready" and d.node(bad_nid)["stage_cursor"] == 1
       and next(r for r in d.state()["runs"] if r["id"] == bad_run["id"])["adoption_status"] == "adopted",
       "late gate evidence repairs and adopts the original RUN without another execution")

    completed_nid, _, _, _ = add_node("completed_stop", 0.70, completed=True)
    completed_run = next(r for r in d.state()["runs"] if r["node"] == completed_nid)
    background_predicate = stop_run["scientific_gate"]["predicates"][0]
    completed_predicate = completed_run["scientific_gate"]["predicates"][0]
    ok(d.node(completed_nid)["status"] == "scientific_stop"
       and completed_run["scientific_outcome"] == stop_run["scientific_outcome"] == "stop_node"
       and {k: completed_predicate[k] for k in ("metric", "comparison", "value", "passed")}
       == {k: background_predicate[k] for k in ("metric", "comparison", "value", "passed")},
       "completed and background launches use the same scientific transition")

    toctou_nid, _, _, toctou_metrics = add_node(
        "completed_toctou", 0.55, completed=True, disappear_after_validation=True)
    toctou_run = next(r for r in d.state()["runs"] if r["node"] == toctou_nid)
    wj(repo, toctou_metrics, {"summary": {"min_fresh_auc": 0.55},
                              "usage": {"wallclock_minutes": 2}})
    esched.Engine(store).reconcile_run(toctou_run["id"])
    ok(d.node(toctou_nid)["status"] == "stage_ready" and d.node(toctou_nid)["stage_cursor"] == 1,
       "post-validation evidence loss is repaired on the original completed RUN")

    self_metrics = ".evo/self_authored_decision.json"
    wj(repo, self_metrics, {"summary": {"score": 1.0}, "usage": {"wallclock_minutes": 1},
                            "passed": False, "gate": {"decision": "KILL"}})
    plain_stage = json.loads(json.dumps(stop_stage))
    plain_stage.pop("continuation_gate")
    errs = evalid.stage_result_errors(evalid.Ctx(store, store.load_state(), store.load_config(),
                                                  store.load_graph(), store.load_artifacts()),
                                      plain_stage, self_metrics, None, where="self-authored decision")
    ok(any(e.startswith("STAGE_RESULT_SELF_DECISION") for e in errs),
       "a result cannot invent a post-hoc KILL field")

    ctx = evalid.Ctx(store, store.load_state(), store.load_config(),
                     store.load_graph(), store.load_artifacts())
    stop_spec = eutil.read_json(repo / d.node(stop_nid)["spec"])
    target_key = next(c["result_key"] for c in econfig.evaluation_cells(ctx.cfg)
                      if c.get("role") == "target")
    target_gate_spec = json.loads(json.dumps(stop_spec))
    target_gate_spec["workflow"]["stages"][0]["continuation_gate"]["predicates"][0]["metric"] = target_key
    errs = evalid._stage_errors(ctx, target_gate_spec, role="root", where="target-metric gate")
    ok(any(e.startswith("SPEC_STAGE_GATE_DECISION_METRIC") for e in errs),
       "continuation gate cannot suppress evaluation based on a target/guardrail result")

    final_gate_spec = json.loads(json.dumps(stop_spec))
    final_gate = final_gate_spec["workflow"]["stages"][0].pop("continuation_gate")
    final_gate_spec["workflow"]["stages"][-1]["continuation_gate"] = final_gate
    errs = evalid._stage_errors(ctx, final_gate_spec, role="root", where="final-stage gate")
    ok(any(e.startswith("SPEC_STAGE_GATE_NO_DOWNSTREAM") for e in errs),
       "continuation gate must screen real downstream work rather than hide final evaluation")
    d.doctor_clean("scientific continuation transition fixture")


def resource_contract_checks(source_d):
    section("project resource contract: reserve, charge once, and require human extension")
    repo = OUT / "resource_contract"
    if repo.exists():
        rmtree(repo)
    make_repo(repo, with_git=False)
    store = estore.Store(repo)
    store.init("resource contract", "enforce one cumulative project envelope")
    cfg = project_cfg(source_d)
    cfg["policy"]["autonomy"] = "full_auto"
    cfg["resource_contract"] = {
        "limits": {"wallclock_minutes": 5.0},
        "basis": "the fixture user explicitly approved five cumulative wallclock minutes",
        "on_exhaustion": "ask",
    }
    wj(repo, ".evo/config.json", cfg)
    eng = esched.Engine(store)
    gate = eng._resource_gate({"id": "NX"}, "eval", {"wallclock_minutes": 10.0})
    ok(gate is not None and gate["kind"] == "resource_approval", "over-limit operation creates a resource gate")
    eng.save()
    d = D(repo)
    out = d.next()
    ok(out["kind"] == "gate" and out["gate_kind"] == "resource_approval",
       "full_auto cannot approve its own project-limit increase")
    d.decide(out["gate"], True, note="approve exactly five additional minutes for this operation")
    st = d.state()
    ok(st["resource_overrides"] == {"wallclock_minutes": 5.0},
       f"approval adds only the computed deficit: {st['resource_overrides']}")

    metrics_rel = ".evo/resource_eval.json"
    wj(repo, metrics_rel, {"_usage": {"wallclock_minutes": 2.0}})
    st = store.load_state()
    run = store.new_run(st, "NX", "eval", "job-resource",
                        contract_digest=eseal.combine_digests("resource-fixture", "eval"))
    run["resource_reservation"] = {"wallclock_minutes": 4.0}
    run["status"] = "finished"
    run["metrics_file"] = metrics_rel
    store.save_state(st)
    eng = esched.Engine(store)
    target = store.get_run(eng.st, run["id"])
    eng._account_run(target)
    eng._account_run(target)
    eng.save()
    ledger = d.state()["resource_ledger"]
    ok(len(ledger) == 1 and ledger[0]["usage"] == {"wallclock_minutes": 2.0}
       and ledger[0]["basis"] == "reported_actual",
       f"successful usage is charged exactly once at reported actual: {ledger}")

    st = store.load_state()
    failed = store.new_run(st, "NX", "stage", "job-failed", stage="train",
                           contract_digest=eseal.combine_digests("resource-fixture", "stage"))
    failed["resource_reservation"] = {"wallclock_minutes": 3.0}
    failed["status"] = "failed"
    store.save_state(st)
    eng = esched.Engine(store)
    target = store.get_run(eng.st, failed["id"])
    eng._account_run(target)
    eng.save()
    ledger = d.state()["resource_ledger"]
    ok(len(ledger) == 2 and ledger[-1]["usage"] == {"wallclock_minutes": 3.0}
       and ledger[-1]["basis"] == "reserved_cap_on_failure",
       "failed external work is conservatively charged at its reservation")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    repo = OUT / "proj"
    if repo.exists():
        rmtree(repo)
    make_repo(repo, with_git=True)
    evo = PKG / "engine" / "evo.py"
    p = subprocess.run([PY, str(evo), "--repo", str(repo), "init",
                        "--project-name", "fake-bfr", "--goal", "beat baseline auc"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    ok(p.returncode == 0, f"CLI init: {p.stderr}")
    d = D(repo)
    run_bootstrap(d)
    run_r1(d)
    run_r2(d)
    run_r3(d)
    run_r4(d)
    run_r5(d)
    run_r6(d)
    doctor_fix_test(d)
    run_r7(d)
    run_r8(d)
    run_r9(d)
    run_r10(d)
    run_r11(d)
    run_r12(d)
    run_r13(d)
    run_r14(d)
    run_r15(d)
    run_r16(d)
    run_r17(d)
    run_r18(d)
    final_asserts(d)
    git_integrity_failure_checks(d)
    seal_chain_adversarial_checks(d)
    cli_preflight_adversarial_checks(d)
    v91_policy_checks(d)
    scientific_axes_orthogonality_checks(d)
    seed_and_ablation_policy_checks(d)
    workflow_replication_execution_checks(d)
    targeted_ablation_flow_checks(d)
    scientific_transition_checks(d)
    resource_contract_checks(d)
    run_mini()
    run_fit_gate()
    run_canary_blocked_gate()
    run_canary_validation_exhaustion()
    run_canary_runtime_exhaustion()
    print(f"\nALL GREEN: {CHECKS} checks passed "
          f"(18-round full_auto research-mode git run + gated copy-mode engineering mini run "
          f"+ complete-workflow seed/probe execution + explicit ablation contracts "
          f"+ end-to-end causal diagnostic + real infrastructure-canary blocked/retry scenario)")


def rmtree(p):
    def onerr(func, path, exc):
        os.chmod(path, 0o777)
        func(path)
    shutil.rmtree(p, onerror=onerr)


if __name__ == "__main__":
    main()
