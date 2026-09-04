"""v11 feature contracts at unit speed.

    python tests/v11_feature_unit.py

Covers the v11 additions: single-spawn git facts, invocation memo, noise-floor
substitution + provisional records, critic isolation, abandon_request,
expensive-terminal protection, sweep cadence config, ERRORS.json capping,
launcher input slimming, and the mature-time SOTA comparability front-shift.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))

import econfig    # noqa: E402
import eflow      # noqa: E402
import esched     # noqa: E402
import eutil      # noqa: E402
import evalid     # noqa: E402
import evcs       # noqa: E402
from _check import check, raises, done  # noqa: E402


def noise_floor_substitution():
    cfg = econfig.merged_default()
    cfg["evaluation_contract"]["noise_floors"] = {"C1": 0.02}
    check(econfig.noise_floor(cfg, "C1") == 0.02, "recorded floor is read")
    check(econfig.noise_floor(cfg, "C2") == 0.0, "absent floor is 0 (v10 behavior)")
    check(econfig.noise_floor(cfg, "C1") >= 0, "floor is non-negative")

    # A bare scalar widens to +-floor; a reported interval is kept as reported.
    p, lo, hi = econfig.result_interval_with_floor(0.80, 0.02)
    check(abs(p - 0.80) < 1e-12 and abs(lo - 0.78) < 1e-12 and abs(hi - 0.82) < 1e-12,
          f"scalar widens to the noise band: {(p, lo, hi)}")
    reported = {"value": 0.80, "uncertainty": {"lower": 0.795, "upper": 0.805, "level": 0.95}}
    p, lo, hi = econfig.result_interval_with_floor(reported, 0.02)
    check((lo, hi) == (0.795, 0.805),
          "an honest (tighter) reported interval is USED as reported - reporting "
          "real uncertainty now lowers one's own bar instead of raising it")
    # Comparison consequence: a scalar delta inside the band cannot clear it.
    d, dl, du = econfig.improvement_interval(0.81, 0.80, "max", floor=0.02)
    check(dl < 0 < du and abs(d - 0.01) < 1e-12,
          f"a +0.01 scalar win inside a 0.02 floor is not a settled improvement: {(d, dl, du)}")
    d2, dl2, du2 = econfig.improvement_interval(0.85, 0.80, "max", floor=0.02)
    check(dl2 > 0, f"a win beyond the band still clears: {(d2, dl2, du2)}")

    # Config validation: margin below floor is the named trap.
    cfg2 = econfig.merged_default()
    cfg2["evaluation_contract"]["cells"] = [
        {"id": "C1", "result_key": "auc", "min_improvement": 0.005}]
    cfg2["evaluation_contract"]["noise_floors"] = {"C1": 0.02}
    errs = econfig.validate_config(cfg2)
    check(any("MARGIN_BELOW_NOISE" in e for e in errs),
          f"a margin below the recorded floor is rejected at config time: "
          f"{[e for e in errs if 'NOISE' in e]}")
    cfg2["evaluation_contract"]["noise_floors"] = {"C9": 0.02}
    check(any("CONFIG_NOISE_FLOOR_C9" in e for e in econfig.validate_config(cfg2)),
          "a floor naming no cell is rejected")


def provisional_records():
    import egraph
    cfg = econfig.merged_default()
    cfg["evaluation_contract"]["cells"] = [
        {"id": "C1", "result_key": "auc", "direction": "max", "role": "target",
         "required": True, "weight": 1.0, "goal_threshold": None}]
    cfg["metrics"] = [{"key": "auc", "direction": "max"}]
    cfg["evaluation_contract"]["noise_floors"] = {"C1": 0.02}

    def node(nid, auc):
        return {"id": nid, "status": "concluded", "role": "variant",
                "scores": {"auc": {"value": auc}}}

    winner = node("N003", 0.815)
    pool = [node("N001", 0.80), node("N002", 0.81), winner]
    check(egraph.provisional_record(winner, pool, cfg),
          "a record whose margin (0.005) sits inside the 0.02 floor is provisional")
    clear = node("N004", 0.86)
    check(not egraph.provisional_record(clear, pool + [clear], cfg),
          "a record clearing the floor is not provisional")
    cfg["evaluation_contract"]["noise_floors"] = {}
    check(not egraph.provisional_record(winner, pool, cfg),
          "no recorded floor -> no labeling (v10 behavior)")


def critic_isolation():
    def ctx_with(mode, tasks):
        cfg = {"policy": {"critic_isolation": mode}}
        return SimpleNamespace(cfg=cfg, st={"tasks": tasks})

    author = {"type": "mature", "status": "done", "session": "sessA",
              "subject": {"lane": "L001"}}
    review = {"type": "red_team", "session": "sessA", "subject": {"lane": "L001"}}

    check(evalid.critic_isolation_errors(
        ctx_with("off", [author]), review, release=True, author_types=("mature",)) == [],
        "off mode never rejects")
    check(evalid.critic_isolation_errors(
        ctx_with("attest", [author]), review, release=True, author_types=("mature",)) == [],
        "attest records but never rejects")
    errs = evalid.critic_isolation_errors(
        ctx_with("strict", [author]), review, release=True, author_types=("mature",))
    check(any("CRITIC_SESSION_SAME" in e for e in errs),
          f"strict rejects a release verdict from the author's own session: {errs}")
    errs = evalid.critic_isolation_errors(
        ctx_with("strict", [author]), {**review, "session": ""}, release=True,
        author_types=("mature",))
    check(any("CRITIC_SESSION_REQUIRED" in e for e in errs),
          "strict requires a session id on release verdicts")
    check(evalid.critic_isolation_errors(
        ctx_with("strict", [author]), {**review, "session": "sessB"}, release=True,
        author_types=("mature",)) == [],
        "a different session releases cleanly")
    check(evalid.critic_isolation_errors(
        ctx_with("strict", [author]), review, release=False, author_types=("mature",)) == [],
        "kill/REVISE verdicts need no isolation - only the release direction does")


def abandon_request_gate():
    check("abandon_request" in econfig.GATE_KINDS, "gate kind is registered")
    pol = eflow.GATE_POLICY["abandon_request"]
    check(pol.protected and pol.auto == "never",
          "the early-exit decision is user-owned in every autonomy mode")

    events = []
    eng = object.__new__(esched.Engine)
    lane = {"id": "L001", "status": "mature", "name": "dead-end"}
    eng.st = {"lanes": [lane], "gates": [], "tasks": [], "runs": []}
    eng.g = {"nodes": []}
    eng.store = SimpleNamespace(
        get_lane=lambda st, lid: next((l for l in st["lanes"] if l["id"] == lid), None),
        event=lambda actor, ev, **d: events.append((actor, ev, d)),
    )
    eng.node = lambda nid: None
    eng.cfg = {"budgets": {}, "policy": {}}
    abandoned = []
    eng._abandon_lane = lambda ln, reason: (ln.__setitem__("status", "abandoned"),
                                            abandoned.append(reason))
    gate = {"id": "G1", "kind": "abandon_request", "status": "open",
            "subject": {"lane": "L001", "reason": "the mechanism cannot express on this dataset"}}
    eng._decide_gate(gate, approve=True, note="agreed", actor="user", retry_stage=None)
    check(lane["status"] == "abandoned" and abandoned
          and "deliberate stop" in abandoned[0],
          f"approve = deliberate stop with the reason on record: {abandoned}")
    check(any(ev == "deliberate_stop" for _a, ev, _d in events),
          f"the stop is a first-class event, not a failure statistic: {events}")

    lane2 = {"id": "L002", "status": "mature", "name": "alive"}
    eng.st["lanes"].append(lane2)
    gate2 = {"id": "G2", "kind": "abandon_request", "status": "open",
             "subject": {"lane": "L002", "reason": "r" * 30}}
    eng._decide_gate(gate2, approve=False, note="keep going", actor="user", retry_stage=None)
    check(lane2["status"] == "mature",
          "reject = the work continues untouched")


def expensive_terminal_protection():
    check(set(eflow.EXPENSIVE_TERMINAL_TASKS) == {"evaluate", "conclude", "scientific_conclude"},
          "the protected set is exactly the paid-compute terminal tasks")
    # The protection composes with the D1 fix: these tasks' subjects are nodes,
    # so falling into on_stuck=abandon would abandon a fully trained node over
    # report formatting.


def sweep_cadence_config():
    cfg = econfig.merged_default()
    check(cfg["policy"]["next_sweep"] == "scoped", "scoped next is the default")
    cfg["policy"]["next_sweep"] = "everything"
    check(any("CONFIG_NEXT_SWEEP" in e for e in econfig.validate_config(cfg)),
          "unknown sweep mode rejected")
    cfg["policy"]["next_sweep"] = "full"
    cfg["policy"]["full_sweep_every"] = 0
    check(any("FULL_SWEEP_EVERY" in e for e in econfig.validate_config(cfg)),
          "cadence must be >= 1")


def git_status_facts():
    with tempfile.TemporaryDirectory() as td:
        import subprocess
        repo = Path(td)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
        evcs.begin_invocation()
        # Unborn HEAD fails closed, same as the old rev-parse path.
        raises(lambda: evcs.status_facts(repo), evcs.GitCheckError,
               "unborn HEAD is refused")
        (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-qm", "c1"], check=True)
        evcs.begin_invocation()
        head, clean, untracked = evcs.status_facts(repo)
        check(len(head) == 40 and clean and untracked == [],
              f"clean tree: {head[:8]} clean={clean} untracked={untracked}")
        (repo / "b.txt").write_text("new\n", encoding="utf-8")
        evcs.begin_invocation()
        head2, clean2, untracked2 = evcs.status_facts(repo)
        check(clean2 and untracked2 == ["b.txt"],
              f"an untracked file is listed but does not dirty the tracked tree: {untracked2}")
        (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
        evcs.begin_invocation()
        _h, clean3, _u = evcs.status_facts(repo)
        check(not clean3, "a tracked edit is dirty")
        # The invocation memo returns identical facts without re-spawning; a new
        # invocation observes fresh state.
        (repo / "a.py").write_text("x = 3\n", encoding="utf-8")
        _h4, clean4, _u4 = evcs.status_facts(repo)
        check(clean4 == clean3, "within one invocation the memo is stable")
        flags = evcs.tracked_file_flags(repo)
        check(flags.get("a.py") == "H", f"a normal tracked file has flag H: {flags}")
        subprocess.run(["git", "-C", str(repo), "update-index", "--skip-worktree", "a.py"],
                       check=True)
        evcs.begin_invocation()
        flags2 = evcs.tracked_file_flags(repo)
        check(flags2.get("a.py") == "S",
              f"skip-worktree is visible - the closure audit falls back to full "
              f"hashing on this bit: {flags2}")


def sota_comparability_front_shift():
    src = (HERE.parent / "engine" / "evalid.py").read_text(encoding="utf-8")
    check("IDEA_SOTA_NONCOMPARABLE" in src and "OUTCOME_SOTA_NONCOMPARABLE" in src,
          "the mature-time check exists alongside the conclude-time one")


def sweep_scope_behavior():
    """The R1 review proved the scoped/cadence machinery had config tests only.
    These exercise the BEHAVIOR on a synthetic engine."""
    import json as _json
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".evo" / "cache").mkdir(parents=True)
        eng = object.__new__(esched.Engine)
        eng.store = SimpleNamespace(repo=repo)
        eng.cfg = {"policy": {"next_sweep": "scoped", "full_sweep_every": 3,
                              "full_sweep_max_minutes": 30},
                   "metrics": [{"key": "auc", "direction": "max"}],
                   "evaluation_contract": {"cells": []}}
        # Fixture discipline (R2): each consumed-set ADDITION must be the ONLY
        # path by which its object enters the set, or reverting the addition
        # stays green. N009 is 'building' (real post-rollback status - the
        # executing/evaluating/evaluated base loop must NOT shadow it); N002
        # enters only as code_parent/comparator; L099 only via a lane-scoped
        # recovery; N014 is the negative control (terminal recovery).
        eng.st = {"phase": "rounds", "current_round": "R002",
                  "lanes": [{"id": "L010", "round": "R002", "parents": ["N005"]},
                            {"id": "L001", "round": "R001", "parents": ["N001"]},
                            {"id": "L099", "round": "R000", "parents": ["N001"]}],
                  "recoveries": [{"status": "replaying",
                                  "scope": {"kind": "node", "id": "N009"}},
                                 {"status": "repairing",
                                  "scope": {"kind": "lane", "id": "L099"}},
                                 {"status": "completed",
                                  "scope": {"kind": "node", "id": "N014"}}],
                  "gates": [{"status": "open", "subject": {"node": "N008", "lane": "L001"}}]}
        eng.g = {"nodes": [
            {"id": "N001", "role": "baseline", "status": "concluded"},
            {"id": "N002", "role": "variant", "status": "concluded", "round": "R000"},
            {"id": "N005", "role": "variant", "status": "concluded",
             "code_parent": "N002", "effect_comparator_node": "N002"},
            {"id": "N006", "role": "variant", "status": "executing", "round": "R002"},
            {"id": "N007", "role": "variant", "status": "concluded", "round": "R000"},
            {"id": "N008", "role": "variant", "status": "concluded", "round": "R000"},
            {"id": "N009", "role": "variant", "status": "building", "round": "R000"},
            {"id": "N014", "role": "variant", "status": "concluded", "round": "R000"},
        ]}
        marker = repo / ".evo" / "cache" / "sweep_cadence.json"

        # Missing marker = stale = full sweep, and _next_sweep_scope itself must
        # NOT re-arm (the reset happens only after a SUCCESSFUL full sweep).
        check(eng._next_sweep_scope() is None, "first call is a full sweep")
        check(not marker.exists(),
              "the tripwire does not re-arm before the sweep succeeds")

        marker.write_text(_json.dumps({"count": 0, "last_full_at": eutil.utc_now()}),
                          encoding="utf-8")
        scope = eng._next_sweep_scope()
        check(scope is not None, "armed marker -> scoped sweep")
        lanes, nodes = scope
        check("L010" in lanes and "L001" in lanes,
              f"current-round lane and open-gate lane are in scope: {lanes}")
        check("L099" in lanes,
              f"a lane-scoped active recovery pulls its lane into scope: {lanes}")
        for expect, why in (("N005", "lane parent"), ("N001", "baseline"),
                            ("N006", "executing"), ("N009", "recovery target (building)"),
                            ("N008", "open-gate node"), ("N002", "code_parent/comparator hop")):
            check(expect in nodes,
                  f"{expect} ({why}) is in the consumed set: {sorted(nodes)}")
        check("N007" not in nodes, "an old unreferenced node is honestly OUT of scope")
        check("N014" not in nodes,
              "a TERMINAL recovery's target does not stay in scope forever")

        # Count trips at K.
        marker.write_text(_json.dumps({"count": 2, "last_full_at": eutil.utc_now()}),
                          encoding="utf-8")
        check(eng._next_sweep_scope() is None, "K-th invocation trips the full sweep")
        # Corrupt marker fails SAFE to full.
        marker.write_text("{not json", encoding="utf-8")
        check(eng._next_sweep_scope() is None, "a corrupt marker degrades to a full sweep")
        # Future timestamp = clock skew = stale.
        marker.write_text(_json.dumps({"count": 0, "last_full_at": "2999-01-01T00:00:00Z"}),
                          encoding="utf-8")
        check(eng._next_sweep_scope() is None, "a future last_full_at fails safe to full")
        # phase!=rounds is always full.
        eng.st["phase"] = "bootstrap"
        marker.write_text(_json.dumps({"count": 0, "last_full_at": eutil.utc_now()}),
                          encoding="utf-8")
        check(eng._next_sweep_scope() is None, "outside rounds every sweep is full")


def main() -> None:
    noise_floor_substitution()
    provisional_records()
    critic_isolation()
    abandon_request_gate()
    expensive_terminal_protection()
    sweep_cadence_config()
    sweep_scope_behavior()
    git_status_facts()
    sota_comparability_front_shift()
    done("V11 FEATURE UNIT")


if __name__ == "__main__":
    main()
