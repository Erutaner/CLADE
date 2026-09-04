"""Engine-executed smoke tests: the agent cannot narrate exit codes into existence.

Runs the node spec's smoke_plan steps, captures stdout/stderr/exit per step,
writes .evo/nodes/<N>/smoke/RESULTS.json plus logs, and appends events.
"""
from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import egraph
import eutil


def run_smoke(store, node_id: str) -> dict:
    g = store.load_graph()
    node = egraph.by_id(g).get(node_id)
    if node is None:
        raise SystemExit(f"[evo] no node {node_id}")
    spec = eutil.read_json(eutil.rpath(store.repo, node.get("spec") or ""), None)
    if spec is None:
        raise SystemExit(f"[evo] node {node_id} has no spec at {node.get('spec')}")
    plan = spec.get("smoke_plan") or []
    if not plan:
        raise SystemExit(f"[evo] node {node_id} spec has an empty smoke_plan")
    workdir = eutil.rpath(store.repo, spec.get("workdir") or ".")
    out_dir = store.node_dir(node_id) / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = []
    all_pass = True
    for i, step in enumerate(plan):
        # A malformed step must fail THAT step with a diagnosable record, never
        # kill the whole smoke pass with an uncaught TypeError (the spec
        # validator checks these shapes too; this is the engine-side backstop).
        if not isinstance(step, dict):
            steps.append({"name": f"step{i}", "cmd": "", "cwd": "", "status": "fail",
                          "exit": None, "detail": "smoke_plan step must be an object"})
            all_pass = False
            continue
        shape_errs = []
        for field, want in (("must_exist", str), ("must_contain", dict)):
            rows = step.get(field)
            if rows is not None and (not isinstance(rows, list)
                                     or any(not isinstance(x, want) for x in rows)):
                shape_errs.append(f"{field} must be a list of "
                                  f"{'strings' if want is str else 'objects with file+text'}")
        if any(not str((mc or {}).get("file") or "") for mc in (step.get("must_contain") or [])
               if isinstance(mc, dict)):
            shape_errs.append("every must_contain entry needs a 'file'")
        name = str(step.get("name") or f"step{i}")
        cmd = str(step.get("cmd") or "")
        cwd = eutil.rpath(store.repo, str(step["cwd"])) if step.get("cwd") else workdir
        try:
            timeout = int(step.get("timeout_s") or 300)
            expect_exit = int(step.get("expect_exit") or 0)
        except (TypeError, ValueError):
            # same backstop contract as above: a "300s" in a sealed spec must
            # fail THIS step with a diagnosable record, not kill the pass
            steps.append({"name": name, "cmd": cmd, "cwd": str(cwd), "status": "fail",
                          "exit": None, "detail": "timeout_s/expect_exit must be integers"})
            all_pass = False
            continue
        rec = {"name": name, "cmd": cmd, "cwd": str(cwd), "status": "pass", "exit": None, "detail": ""}
        if shape_errs:
            rec["status"] = "fail"
            rec["detail"] = "malformed step: " + "; ".join(shape_errs)
            steps.append(rec)
            all_pass = False
            continue
        try:
            args = cmd if sys.platform == "win32" else shlex.split(cmd)
            proc = subprocess.run(
                args, cwd=str(cwd), shell=(sys.platform == "win32"),
                capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",
            )
            rec["exit"] = proc.returncode
            eutil.write_text(out_dir / f"{i:02d}_{eutil.slug(name)}.stdout.txt", proc.stdout or "")
            eutil.write_text(out_dir / f"{i:02d}_{eutil.slug(name)}.stderr.txt", proc.stderr or "")
            if proc.returncode != expect_exit:
                rec["status"] = "fail"
                rec["detail"] = f"exit {proc.returncode} != expected {expect_exit}; see logs"
        except subprocess.TimeoutExpired:
            rec["status"] = "fail"
            rec["detail"] = f"timeout after {timeout}s"
        except OSError as exc:
            rec["status"] = "fail"
            rec["detail"] = f"could not run: {exc}"
        if rec["status"] == "pass":
            for p in step.get("must_exist") or []:
                target = (cwd / p) if not Path(p).is_absolute() else Path(p)
                alt = eutil.rpath(store.repo, p)
                if not target.exists() and not alt.exists():
                    rec["status"] = "fail"
                    rec["detail"] = f"required artifact missing: {p}"
                    break
        if rec["status"] == "pass":
            for mc in step.get("must_contain") or []:
                fp = mc.get("file"); txt = str(mc.get("text") or "")
                target = (cwd / fp) if not Path(fp).is_absolute() else Path(fp)
                alt = eutil.rpath(store.repo, fp)
                target = target if target.exists() else alt
                if not target.exists() or txt not in eutil.read_text(target):
                    rec["status"] = "fail"
                    rec["detail"] = f"'{txt}' not found in {fp}"
                    break
        if rec["status"] != "pass":
            all_pass = False
        steps.append(rec)
    results = {"node": node_id, "status": "pass" if all_pass else "fail",
               "steps": steps, "ran_at": eutil.utc_now()}
    eutil.write_json_atomic(out_dir / "RESULTS.json", results)
    store.event("engine", "smoke_ran", node=node_id, status=results["status"],
                failed=[s["name"] for s in steps if s["status"] != "pass"])
    return results
