#!/usr/bin/env python3
"""Focused regressions for workdir isolation and tournament SOTA scope."""
from __future__ import annotations

import subprocess
from pathlib import Path

import mock_drive as M


def comparator_boundary_checks(drive: M.D) -> None:
    """Keep causal comparators separate from graph/SOTA promotion evidence."""
    primary = M.econfig.primary_metric(M.project_cfg(drive))
    M.ok(M.egraph.primary_score(drive.node("N002"), primary) >
         M.egraph.primary_score(drive.node("N001"), primary),
         "fixture has a stronger off-lineage N# than the baseline")

    M.open_round(drive, "R002", [{
        "name": "root-comparator", "intent": "wildcat", "min_level": 4,
        "parents": [], "search_origin": "constructive"}])
    root = drive.lane_by_name("root-comparator")
    rel = ".evo/v91_checks/ROOT_PROGRAMS.json"
    M.w_sketches(drive, {"outputs": [rel]}, root["id"], M.L4_DIMS, [])
    ctx = M.evalid.Ctx(drive.store(), drive.state(), M.project_cfg(drive),
                       drive.graph(), drive.reg())
    task = {"subject": {"lane": root["id"]}, "outputs": [rel]}
    errs = M.evalid.v_sketch(ctx, task)
    M.ok(not errs, f"root baseline comparator remains legal despite stronger N002: {errs}")

    payload = M.json.loads((drive.repo / rel).read_text(encoding="utf-8"))
    payload["sketches"][0]["effect_case"]["comparator_id"] = "N002"
    M.wj(drive.repo, rel, payload)
    errs = M.evalid.v_sketch(ctx, task)
    M.ok(any(e.startswith("PROGRAM_EFFECT_COMPARATOR_UNKNOWN") for e in errs),
         f"root must reject an off-lineage N# as its effect comparator: {errs}")

    r1 = drive.lane_by_name("exploit1")
    tournament = M.json.loads(
        (drive.repo / r1["tournament_path"]).read_text(encoding="utf-8"))
    tournament["audits"][0]["effect"]["frontier_refs"] = ["N002"]
    tournament_rel = ".evo/v91_checks/TOURNAMENT_NREF.json"
    M.wj(drive.repo, tournament_rel, tournament)
    tournament_md = r1["tournament_path"].replace(".json", ".md")
    errs = M.evalid.v_tournament(ctx, {
        "subject": {"lane": r1["id"]},
        "outputs": [tournament_rel, tournament_md]})
    M.ok(any(e.startswith("TOURNAMENT_FRONTIER_REF_UNKNOWN") for e in errs),
         f"frontier_refs must remain S### only: {errs}")


def main() -> None:
    M.CHECKS = 0
    out = Path(__file__).resolve().parent / "out" / "bugfix_regressions"
    out.mkdir(parents=True, exist_ok=True)
    repo = out / "proj"
    if repo.exists():
        M.rmtree(repo)
    M.make_repo(repo, with_git=True)
    evo = M.PKG / "engine" / "evo.py"
    proc = subprocess.run(
        [M.PY, str(evo), "--repo", str(repo), "init",
         "--project-name", "bugfix-regressions",
         "--goal", "validate workdir isolation and SOTA scope"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    M.ok(proc.returncode == 0, f"CLI init: {proc.stderr}")
    drive = M.D(repo)
    M.run_bootstrap(drive)
    M.run_r1(drive)
    comparator_boundary_checks(drive)
    print(f"\nBUGFIX REGRESSIONS GREEN: {M.CHECKS} checks passed")


if __name__ == "__main__":
    main()
