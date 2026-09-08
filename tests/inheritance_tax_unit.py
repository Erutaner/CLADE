"""The inheritance tax: what happens after a program-level win whose
mechanism was never instrumented.

Unit-speed pins on scratch engines:
  - the ablation allowance is arithmetic on the parent's OWN charged usage
    (k x its cost, never less than one retrain, earlier ablation children
    counted); the run-sizing lines speak only where a floor is recorded
  - a deferred win opens its ablation lane inside the running round, or
    records the pending tax with the reason when it cannot
  - an ablation that changed the parent's kernel settles the parent's
    mechanism and recomputes its promotion; the frontier label says via whom
  - the allowance verdict on a design is arithmetic the gate can read;
    a design above it, and every probe, waits for the user

    python tests/inheritance_tax_unit.py
"""
from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))
from _check import check, done, raises  # noqa: E402

import egraph    # noqa: E402
import esched    # noqa: E402
import estore    # noqa: E402
import eutil     # noqa: E402
import evalid    # noqa: E402


def _fresh_engine(tag: str):
    repo = HERE / "out" / f"inherit-{tag}-{uuid.uuid4().hex[:8]}"
    repo.mkdir(parents=True)
    store = estore.Store(repo)
    store.init("inheritance-unit", "settle the story after the win")
    eng = esched.Engine(store)
    # the inheritance tax is a research-mode instrument; engineering mode
    # inherits programs on their numbers and opens no ablation by itself
    eng.cfg.setdefault("project", {})["mode"] = "research"
    return repo, store, eng


def _write_json(repo: Path, rel: str, data) -> None:
    eutil.write_json_atomic(repo / rel, data)


def _charge(node: str, usage: dict, *, run: str | None = None) -> dict:
    return {"id": f"RC{uuid.uuid4().hex[:4]}", "node": node, "kind": "stage", "run": run, "task": None,
            "usage": dict(usage), "basis": "reported_actual", "charged_at": eutil.utc_now()}


def _candidate(nid: str, *, parents=("N001",), **extra) -> dict:
    node = {"id": nid, "title": nid, "role": "variant", "experiment_purpose": "candidate",
            "status": "concluded", "verdict": "improved", "parents": list(parents), "level": 2,
            "lane": None, "scores": {"auc": 0.75}, "score_evidence": {"auc": 0.75},
            "mechanism_status": "deferred", "scientific_promotion_status": "met",
            "effect_contract_status": "met", "kernel_ids": ["KC1"],
            "evaluation_summary": {"target_wins": ["C1"], "real_win": True,
                                   "effect_contract": {"status": "met"},
                                   "mechanism_contract": {"status": "deferred"}}}
    node.update(extra)
    return node


def _baseline() -> dict:
    return {"id": "N001", "title": "origin", "role": "baseline", "experiment_purpose": "candidate",
            "status": "concluded", "verdict": "baseline", "parents": [], "level": 0,
            "scores": {"auc": 0.70}, "score_evidence": {"auc": 0.70}}


def _set_multiple(eng, value: float) -> None:
    eng.cfg.setdefault("evidence_policy", {}).setdefault("ablation", {})["budget_multiple"] = value


# ------------------------------------------------------------ allowance ----
def allowance_is_a_multiple_of_the_parents_own_charge() -> None:
    repo, store, eng = _fresh_engine("allowance")
    try:
        eng.g["nodes"] += [_baseline(), _candidate("N002")]
        eng.st["resource_ledger"] = [_charge("N002", {"gpu_hours": 4.0}, run="RUN001")]
        _set_multiple(eng, 2.0)
        a = evalid.ablation_allowance(eng.ctx(), "N002")
        check(a["parent_charged"] == {"gpu_hours": 4.0} and a["parent_runs"] == 1
              and a["one_run"] == {"gpu_hours": 4.0},
              f"the parent's charge and per-run cost are read from the ledger: {a}")
        check(a["allowed"] == {"gpu_hours": 8.0} and a["spent"] == {},
              f"multiple 2 on a 4 gpu_hour parent allows 8, nothing spent yet: {a['allowed']}")
        _set_multiple(eng, 0.5)
        a = evalid.ablation_allowance(eng.ctx(), "N002")
        check(a["allowed"] == {"gpu_hours": 4.0},
              f"a multiple below one retrain still allows exactly one run (4): {a['allowed']}")
        # an eval charge on the parent counts too: the allowance follows what the node cost
        eng.st["resource_ledger"].append({**_charge("N002", {"gpu_hours": 1.0}, run="RUN002"), "kind": "eval"})
        _set_multiple(eng, 2.0)
        a = evalid.ablation_allowance(eng.ctx(), "N002")
        check(a["parent_charged"] == {"gpu_hours": 5.0} and a["allowed"] == {"gpu_hours": 10.0},
              f"stage and eval charges both belong to the parent's cost: {a['parent_charged']}")
        # an earlier ablation child's spend is counted against the same allowance
        eng.g["nodes"].append({"id": "N003", "role": "variant", "experiment_purpose": "targeted_ablation",
                               "status": "concluded", "parents": ["N002"], "level": 0})
        eng.st["resource_ledger"].append(_charge("N003", {"gpu_hours": 3.0}, run="RUN003"))
        a = evalid.ablation_allowance(eng.ctx(), "N002")
        check(a["spent"] == {"gpu_hours": 3.0} and a["allowed"] == {"gpu_hours": 10.0},
              f"an earlier ablation child's charge is spent allowance: {a['spent']}")
        check(evalid.ablation_design_estimate(a, 2) == {"gpu_hours": 10.0},
              "a design estimate is costly_runs x the parent's per-run cost")
        inside, lines = evalid.ablation_within_allowance(a, {"gpu_hours": 7.0})
        check(inside and len(lines) == 1 and "inside" in lines[0] and "already spent 3" in lines[0],
              f"7 planned + 3 spent sits inside 10: {lines}")
        inside, lines = evalid.ablation_within_allowance(a, {"gpu_hours": 7.5})
        check(not inside and "ABOVE" in lines[0] and "vs allowed 10" in lines[0],
              f"7.5 planned + 3 spent is above 10, and the line says so: {lines}")
        inside, lines = evalid.ablation_within_allowance(a, {"wallclock_minutes": 30.0})
        check(not inside and "cannot be compared" in lines[0],
              f"a unit the parent never charged cannot be compared - the user decides: {lines}")
        _set_multiple(eng, 0.0)
        a = evalid.ablation_allowance(eng.ctx(), "N002")
        inside, lines = evalid.ablation_within_allowance(a, {"gpu_hours": 1.0})
        check(a["allowed"] == {"gpu_hours": 0.0} and not inside and "budget_multiple" in lines[0],
              f"multiple 0 authorizes nothing and names the knob: {lines}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def run_arithmetic_speaks_only_with_a_recorded_floor() -> None:
    repo, store, eng = _fresh_engine("arith")
    try:
        parent = _candidate("N002", eval_floor_frozen={"C1": 0.005},
                            evaluation_summary={"target_wins": ["C1", "C2"], "real_win": True,
                                                "cells": {"C1": {"delta": 0.02}, "C2": {"delta": 0.03}}})
        eng.g["nodes"] += [_baseline(), parent]
        lines = evalid.ablation_run_arithmetic(eng.ctx(), parent)
        check(len(lines) == 1 and lines[0].startswith("C1:") and "ratio 4.0" in lines[0]
              and "one changed-component run settles it" in lines[0],
              f"a win four floors wide settles in one run; C2 has no floor and stays silent: {lines}")
        parent["evaluation_summary"]["cells"]["C1"]["delta"] = 0.006
        lines = evalid.ablation_run_arithmetic(eng.ctx(), parent)
        check(len(lines) == 1 and "ratio 1.2" in lines[0] and "about 3 paired runs" in lines[0],
              f"a win close to the floor asks for paired runs and says how many: {lines}")
        lines = evalid.ablation_run_arithmetic(eng.ctx(), parent, ["C2"])
        check(lines == [], "an explicit cell without a floor yields no arithmetic")
        parent.pop("eval_floor_frozen")
        check(evalid.ablation_run_arithmetic(eng.ctx(), parent) == [],
              "without any recorded floor the engine invents no number")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# --------------------------------------------------------- opening the tax ----
def _running_round(eng, rid: str = "R001") -> None:
    eng.st.update({"phase": "rounds", "round_status": "running", "current_round": rid})


def a_deferred_win_opens_its_ablation_in_the_running_round() -> None:
    repo, store, eng = _fresh_engine("open")
    try:
        _running_round(eng)
        _set_multiple(eng, 2.0)
        node = _candidate("N002")
        eng.g["nodes"] += [_baseline(), node]
        advice = eng._open_inheritance_tax(node, "KC1")
        lane = eng.st["lanes"][-1]
        check(lane["experiment_purpose"] == "targeted_ablation" and lane["status"] == "ablation_design"
              and lane["parents"] == ["N002"] and lane["round"] == "R001" and lane["name"] == "ablate-n002"
              and lane["intent"] == "exploit" and lane["min_level"] == 0,
              f"the engine minted the targeted-ablation lane on the winner: {lane}")
        check(node.get("ablation_lane") == lane["id"] and "ablation_pending" not in node,
              "the node points at its open ablation lane")
        brief = repo / ".evo/rounds/R001/lanes/ablate-n002/BRIEF.md"
        check(brief.is_file() and "N002" in brief.read_text(encoding="utf-8")
              and "KC1" in brief.read_text(encoding="utf-8") and "C1" in brief.read_text(encoding="utf-8"),
              "the brief names the parent, its kernel and the cells it won")
        check(len(advice) == 1 and lane["id"] in advice[0] and "inheritance tax" in advice[0]
              and "2 x" in advice[0],
              f"the accepted advice names the lane and the pre-authorized multiple: {advice}")
        check(egraph.mechanism_label(node) == f"deferred (ablation {lane['id']} open)",
              f"the frontier label shows the open ablation: {egraph.mechanism_label(node)}")
        injected = [e for e in store.events() if e.get("event") == "instrumental_lane_injected"]
        check(len(injected) == 1 and injected[0].get("opened_by") == "conclude"
              and injected[0].get("lane") == lane["id"],
              f"the intake event records that the conclusion opened it: {injected}")
        # a second deferred win in the same round: no per-round cap and no
        # one-at-a-time rule - every win owes its own ablation, right now
        other = _candidate("N003", kernel_ids=["KC2"])
        eng.g["nodes"].append(other)
        advice = eng._open_inheritance_tax(other, "KC2")
        second = eng.st["lanes"][-1]
        check(len(eng.st["lanes"]) == 2 and other.get("ablation_lane") == second["id"]
              and second["parents"] == ["N003"] and second["name"] == "ablate-n003"
              and "ablation_pending" not in other,
              f"the second win in the same round gets its own ablation lane at once: {second}")
        check(len(advice) == 1 and second["id"] in advice[0],
              f"the advice names the second lane: {advice}")
        check(not [e for e in store.events() if e.get("event") == "ablation_deferred_to_next_round"],
              "nothing was deferred")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def the_engine_says_why_when_it_does_not_mint() -> None:
    repo, store, eng = _fresh_engine("nomint")
    try:
        eng.g["nodes"] += [_baseline(), _candidate("N002"), _candidate("N003"), _candidate("N004")]
        idx = egraph.by_id(eng.g)
        # budget_multiple 0: no lane, no pending record, advice names the knob and its door
        _running_round(eng)
        _set_multiple(eng, 0.0)
        advice = eng._open_inheritance_tax(idx["N002"], "KC1")
        check(eng.st["lanes"] == [] and "ablation_pending" not in idx["N002"]
              and "ablation_lane" not in idx["N002"],
              "multiple 0 opens nothing and records nothing")
        check(len(advice) == 1 and "budget_multiple" in advice[0] and "evo amend" in advice[0]
              and "evo ablate --parent N002" in advice[0],
              f"the advice names budget_multiple and both doors: {advice}")
        # no running round: pending with the intake refusal
        _set_multiple(eng, 2.0)
        eng.st["round_status"] = "closed"
        eng._open_inheritance_tax(idx["N004"], "KC1")
        reason = (idx["N004"].get("ablation_pending") or {}).get("reason", "")
        check(eng.st["lanes"] == [] and "running round" in reason,
              f"without a running round the tax is pending with the reason: {reason}")
        deferred = [e.get("node") for e in store.events() if e.get("event") == "ablation_deferred_to_next_round"]
        check(deferred == ["N004"], f"the deferral is an event on its node: {deferred}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# --------------------------------------------------------------- write-back ----
def _ablation_child(repo: Path, nid: str, parent: str, *, effect: str, settles: bool = True,
                    clean: bool = True) -> dict:
    iid = f"I{nid[1:]}"
    _write_json(repo, f".evo/ideas/{iid}.meta.json",
                {"idea": iid, "experiment_purpose": "targeted_ablation", "parents": [parent],
                 "ablation": {"parent": parent, "costly_runs": 1, "settles_parent_mechanism": settles,
                              "control_is_clean_program": clean,
                              "effect_supports": "X1", "no_effect_supports": "X2"}})
    supports = {"observed": "X1", "not_observed": "X2"}.get(effect, "inconclusive")
    return {"id": nid, "role": "variant", "experiment_purpose": "targeted_ablation", "status": "concluded",
            "parents": [parent], "level": 0, "idea_doc": f".evo/ideas/{iid}.md",
            "ablation_result": {"effect": effect, "supports": supports, "decision": "d" * 50,
                                "evidence": f".evo/nodes/{nid}/eval/metrics.json", "note": "n" * 50}}


def _tradeoff_parent(nid: str, **extra) -> dict:
    return _candidate(nid, verdict="tradeoff", effect_contract_status="failed",
                      evaluation_summary={"target_wins": ["C1"], "target_losses": ["C2"], "real_win": True,
                                          "effect_contract": {"status": "failed"},
                                          "mechanism_contract": {"status": "deferred"}}, **extra)


def an_ablation_settles_the_parents_mechanism_from_its_own_result() -> None:
    repo, store, eng = _fresh_engine("settle")
    try:
        parent = _tradeoff_parent("N002", ablation_pending={"reason": "cap used", "at": eutil.utc_now()})
        child = _ablation_child(repo, "N003", "N002", effect="observed")
        eng.g["nodes"] += [_baseline(), parent, child]
        eng._settle_parent_mechanism_from_ablation(child)
        check(parent["mechanism_status"] == "confirmed" and parent["scientific_promotion_status"] == "met",
              f"an observed effect confirms the parent's story; a tradeoff with a real win stays met: "
              f"{parent['mechanism_status']}, {parent['scientific_promotion_status']}")
        row = parent["mechanism_settlements"][-1]
        check(row["ablation"] == "N003" and row["from"] == "deferred" and row["to"] == "confirmed"
              and row["effect"] == "observed" and row["supports"] == "X1" and "promotion_to" not in row,
              f"the settlement row points at the ablation and records the causal transition only: {row}")
        check("ablation_pending" not in parent, "a settled parent no longer owes the tax")
        check(egraph.mechanism_label(parent) == "confirmed (via N003)",
              f"the frontier label credits the ablation: {egraph.mechanism_label(parent)}")
        settled = [e for e in store.events() if e.get("event") == "parent_mechanism_settled"]
        check(len(settled) == 1 and settled[0].get("parent") == "N002" and settled[0].get("ablation") == "N003"
              and settled[0].get("mechanism_to") == "confirmed",
              f"the write-back is an event: {settled}")

        refuted_parent = _tradeoff_parent("N004", idea_doc=".evo/ideas/I004.md")
        _write_json(repo, ".evo/ideas/I004.meta.json",
                    {"idea": "I004", "change_scope": "local", "kernel_ids": ["KC1"],
                     "program": {"operators": [{"id": "OP1", "kind": "gate", "phase": "train",
                                                "semantics": "learnable gate over tokens"}]},
                     "novelty": {"kernel": [{"id": "KC1", "kind": "operator", "statement": "s" * 30,
                                             "operator_refs": ["OP1"]}]}})
        refuting = _ablation_child(repo, "N005", "N004", effect="not_observed")
        eng.g["nodes"] += [refuted_parent, refuting]
        eng._settle_parent_mechanism_from_ablation(refuting)
        rk = refuted_parent["refuted_kernel"]
        banked = [o for o in store.observations(eng.st) if o.get("node") == "N004"]
        check(rk["reading"] == "unattributed" and rk["candidates"] == [] and rk.get("observation") == banked[-1]["id"]
              and banked[-1]["kind"] == "unattributed_gain" and "re-measure" in banked[-1]["statement"].lower()
              and "C1" in banked[-1]["measurement"],
              f"a local change whose only kernel was refuted reads as an unattributed gain, on the ledger: {rk}, {banked[-1:]}")
        # no effect refutes the STORY, not the numbers: the parent stays a legal
        # parent, the kernel is barred from premises and children, and the
        # control version is the code parent to build on
        check(refuted_parent["mechanism_status"] == "refuted"
              and refuted_parent["scientific_promotion_status"] == "met"
              and refuted_parent["refuted_kernel"]["control"] == "N005"
              and refuted_parent["refuted_kernel"]["ablation"] == "N005"
              and egraph.mechanism_label(refuted_parent) == "refuted (via N005; build on N005)",
              f"no effect refutes the story, keeps the parenthood and names the control to build on: "
              f"{refuted_parent['mechanism_status']}, {refuted_parent['scientific_promotion_status']}, "
              f"{egraph.mechanism_label(refuted_parent)}")

        unclear_parent = _tradeoff_parent("N006")
        unclear = _ablation_child(repo, "N007", "N006", effect="inconclusive")
        eng.g["nodes"] += [unclear_parent, unclear]
        eng._settle_parent_mechanism_from_ablation(unclear)
        # An undecided ablation settles nothing: the parent stays deferred and
        # inheritable, and only the attempt goes on record.
        row = unclear_parent["mechanism_settlements"][-1]
        check(unclear_parent["mechanism_status"] == "deferred"
              and unclear_parent["scientific_promotion_status"] == "met"
              and len(unclear_parent["mechanism_settlements"]) == 1
              and row["effect"] == "inconclusive" and row["from"] == "deferred" and row["to"] == "deferred"
              and unclear_parent["ablation_attempts"] == 1,
              f"an inconclusive run records the attempt and leaves the parent deferred and promoted: "
              f"{unclear_parent['mechanism_status']}, {unclear_parent['scientific_promotion_status']}, {row}")
        check(egraph.mechanism_label(unclear_parent) == "deferred (unclear via N007)",
              f"the frontier label says the attempt was undecided: {egraph.mechanism_label(unclear_parent)}")
        check("ablation_pending" not in unclear_parent and not (unclear_parent.get("ablation_lane")),
              "the engine mints no second tax lane by itself after an undecided one")

        untouched_parent = _tradeoff_parent("N008")
        other_factor = _ablation_child(repo, "N009", "N008", effect="observed", settles=False)
        eng.g["nodes"] += [untouched_parent, other_factor]
        eng._settle_parent_mechanism_from_ablation(other_factor)
        check(untouched_parent["mechanism_status"] == "deferred"
              and "mechanism_settlements" not in untouched_parent,
              "an ablation of some other component leaves the parent's mechanism alone")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def promotion_recomputes_follow_the_claim_inheritance_reads() -> None:
    repo, store, eng = _fresh_engine("claim")
    try:
        # a regressed original bet, re-priced by an approved post-hoc claim
        parent = _candidate("N002", verdict="regressed", effect_contract_status="failed",
                            scientific_promotion_status="met", active_claim="PC001",
                            posthoc_assessment={"claim": "PC001", "verdict": "specialist",
                                                "effect_contract_status": "met", "real_win": True,
                                                "scientific_promotion_status": "met"},
                            evaluation_summary={"target_wins": [], "target_losses": ["C1"], "real_win": False,
                                                "effect_contract": {"status": "failed"},
                                                "mechanism_contract": {"status": "deferred"}})
        child = _ablation_child(repo, "N003", "N002", effect="observed")
        eng.g["nodes"] += [_baseline(), parent, child]
        eng._settle_parent_mechanism_from_ablation(child)
        row = parent["mechanism_settlements"][-1]
        check(parent["mechanism_status"] == "confirmed" and parent["scientific_promotion_status"] == "met"
              and parent["active_claim"] == "PC001" and "promotion_basis" not in row,
              f"a write-back never touches promotion: the post-hoc claim stays the claim inheritance reads: {row}")
        plain = _candidate("N004", verdict="regressed", effect_contract_status="failed",
                           scientific_promotion_status="blocked",
                           evaluation_summary={"target_wins": [], "real_win": False,
                                               "effect_contract": {"status": "failed"}})
        eng.g["nodes"].append(plain)
        # the instrument-correction gate corrects the probe's answer and says
        # plainly that parenthood does not move with it
        eng.st["corrections"] = [{"id": "CR001", "node": "N002", "original": {"status": "confirmed"},
                                  "corrected": {"status": "unclear"}, "proposal_path": "missing.json"}]
        gate = store.new_gate(eng.st, "instrument_correction", {"node": "N002", "correction": "CR001"}, "x")
        report = "\n".join(eng._gate_report(gate))
        check("probe's answer confirmed -> unclear" in report and "Parenthood does not move" in report
              and "currently confirmed" in report,
              f"the correction preview names the probe transition and the unmoved parenthood:\n{report}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def pending_ablations_are_opened_when_a_round_goes_running() -> None:
    repo, store, eng = _fresh_engine("pending")
    try:
        _set_multiple(eng, 2.0)
        waiting = _candidate("N002", ablation_pending={"reason": "no running round", "at": "2026-01-01T00:00:00Z",
                                                       "question": "Is KC1 the cause?", "attempts": 1})
        second = _candidate("N003", kernel_ids=["KC2"],
                            ablation_pending={"reason": "round held", "at": "2026-01-01T00:00:00Z",
                                              "question": "Is KC2 the cause?", "attempts": 1})
        eng.g["nodes"] += [_baseline(), waiting, second]
        eng.st.update({"phase": "rounds", "round_status": "opening", "current_round": "R001"})
        _write_json(repo, ".evo/rounds/R001/PORTFOLIO.json", {"lanes": []})
        eng._apply_portfolio({"subject": {"round": "R001"}, "outputs": [".evo/rounds/R001/PORTFOLIO.json"]})
        lanes = eng.st["lanes"]
        # opened_by says which engine moment opened it: this lane opened when the
        # round went running with the tax pending, not at the parent's conclusion
        check(len(lanes) == 2 and lanes[0]["parents"] == ["N002"] and waiting.get("ablation_lane") == lanes[0]["id"]
              and "ablation_pending" not in waiting and waiting.get("ablation_lane_opened_by") == "open_round"
              and any(e.get("event") == "instrumental_lane_injected" and e.get("lane") == lanes[0]["id"]
                      and e.get("opened_by") == "open_round" for e in store.events()),
              f"the round going running opens the pending tax on the first waiting node: {lanes}")
        check(lanes[1]["parents"] == ["N003"] and second.get("ablation_lane") == lanes[1]["id"]
              and "ablation_pending" not in second and second.get("ablation_lane_opened_by") == "open_round",
              f"and on the second waiting node too - no per-round cap holds a win's ablation back: {lanes}")
        advice = eng._accept_advice
        check(len(advice) == 2 and lanes[0]["id"] in advice[0] and lanes[1]["id"] in advice[1],
              f"the acceptance advice reports both lanes: {advice}")
        # a lane the strategist declares on a pending parent binds to it and clears the record
        eng.st["lanes"].clear()
        second.pop("ablation_lane", None)
        second.pop("ablation_lane_opened_by", None)
        second["ablation_pending"] = {"reason": "round held", "at": "2026-01-01T00:00:00Z",
                                      "question": "Is KC2 the cause?", "attempts": 1}
        lane = eng._create_lane("R001", {"name": "abl-n003", "intent": "exploit",
                                         "experiment_purpose": "targeted_ablation", "search_origin": "repair",
                                         "min_level": 0, "parents": ["N003"]}, opened_by="portfolio")
        check(second.get("ablation_lane") == lane["id"] and "ablation_pending" not in second
              and second.get("ablation_lane_opened_by") == "portfolio"
              and egraph.mechanism_label(second) == f"deferred (ablation {lane['id']} open)",
              f"a portfolio-declared ablation on a pending parent is that parent's tax lane: {second}")
        check(any(e.get("event") == "ablation_lane_bound" and e.get("parent") == "N003"
                  and e.get("opened_by") == "portfolio" for e in store.events()),
              "binding the lane to its parent is an event")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def a_concluded_tax_lane_frees_the_parents_doors() -> None:
    """The parent's `ablation_lane` pointer means OPEN. When the tax ablation
    concludes (settling or not) the pointer goes, the row and the event keep
    the lane and who opened it, and the follow-up doors (evo ablate, a
    portfolio lane) bind to the parent again with their own opened_by."""
    repo, store, eng = _fresh_engine("freed")
    try:
        _running_round(eng)
        _set_multiple(eng, 2.0)
        done_lane = {"id": "L000", "round": "R000", "name": "ablate-n002", "status": "done",
                     "experiment_purpose": "targeted_ablation", "intent": "exploit", "parents": ["N002"],
                     "node": "N003"}
        eng.st["lanes"].append(done_lane)
        parent = _tradeoff_parent("N002", ablation_lane="L000", ablation_lane_opened_by="conclude")
        undecided = _ablation_child(repo, "N003", "N002", effect="inconclusive")
        undecided["lane"] = "L000"
        eng.g["nodes"] += [_baseline(), parent, undecided]
        eng._settle_parent_mechanism_from_ablation(undecided)
        row = parent["mechanism_settlements"][-1]
        check("ablation_lane" not in parent and "ablation_lane_opened_by" not in parent
              and row["lane"] == "L000" and row["opened_by"] == "conclude" and row["effect"] == "inconclusive",
              f"a concluded tax lane is no longer the parent's open lane; the row keeps lane and opener: {parent}")
        check(egraph.mechanism_label(parent) == "deferred (unclear via N003)"
              and egraph.open_ablation_lane(parent, eng.st) is None,
              f"the label credits the undecided attempt and no lane reads as open: {egraph.mechanism_label(parent)}")
        concluded = [e for e in store.events() if e.get("event") == "ablation_lane_concluded"]
        check(len(concluded) == 1 and concluded[0].get("parent") == "N002" and concluded[0].get("lane") == "L000"
              and concluded[0].get("opened_by") == "conclude" and concluded[0].get("settles_parent_mechanism") is True,
              f"the release is an event: {concluded}")
        # the follow-up door: evo ablate --parent N002 binds and records who opened it
        lane = eng.open_instrumental_lane(purpose="targeted_ablation", parent="N002",
                                          text="Is KC1 the cause? Second attempt, sized to a clearer delta.",
                                          brief_title="Targeted ablation", actor="agent", opened_by="cli")
        bound = [e for e in store.events() if e.get("event") == "ablation_lane_bound"]
        check(parent.get("ablation_lane") == lane["id"] and parent.get("ablation_lane_opened_by") == "cli"
              and len(bound) == 1 and bound[0].get("lane") == lane["id"] and bound[0].get("opened_by") == "cli"
              and bound[0].get("was_pending") is False
              and egraph.open_ablation_lane(parent, eng.st) == lane["id"]
              and egraph.mechanism_label(parent) == f"deferred (ablation {lane['id']} open)",
              f"the follow-up ablation is the parent's open tax lane and says who opened it: {parent}")
        # a pointer left at a finished lane (never cleared) is nobody's open tax:
        # a declared lane on that parent still binds
        stale = _tradeoff_parent("N004", ablation_lane="L000", ablation_lane_opened_by="conclude")
        eng.g["nodes"].append(stale)
        declared = eng._create_lane("R001", {"name": "abl-n004", "intent": "exploit",
                                             "experiment_purpose": "targeted_ablation", "search_origin": "repair",
                                             "min_level": 0, "parents": ["N004"]}, opened_by="portfolio")
        check(stale.get("ablation_lane") == declared["id"] and stale.get("ablation_lane_opened_by") == "portfolio",
              f"a stale pointer at a done lane does not block the binding: {stale}")
        # a bound lane that concluded WITHOUT settling the parent (other component):
        # the pointer goes, no settlement row is written, the event says so
        other = _tradeoff_parent("N006", ablation_lane="L005", ablation_lane_opened_by="portfolio")
        eng.st["lanes"].append({**done_lane, "id": "L005", "name": "abl-n006", "parents": ["N006"], "node": "N007"})
        component = _ablation_child(repo, "N007", "N006", effect="observed", settles=False)
        component["lane"] = "L005"
        eng.g["nodes"] += [other, component]
        eng._settle_parent_mechanism_from_ablation(component)
        concluded = [e for e in store.events() if e.get("event") == "ablation_lane_concluded" and e.get("parent") == "N006"]
        check("ablation_lane" not in other and "mechanism_settlements" not in other
              and other["mechanism_status"] == "deferred" and len(concluded) == 1
              and concluded[0].get("settles_parent_mechanism") is False and concluded[0].get("opened_by") == "portfolio",
              f"a non-settling ablation frees the pointer and leaves the mechanism alone: {other}, {concluded}")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def a_refused_intake_has_no_side_effects() -> None:
    repo, store, eng = _fresh_engine("refuse")
    try:
        _running_round(eng)
        _set_multiple(eng, 2.0)
        eng.g["nodes"] += [_baseline(), _candidate("N002")]
        closer = {"id": "T001", "type": "close_round", "status": "open", "subject": {"round": "R001"}}
        eng.st.setdefault("tasks", []).append(closer)
        before = len(store.events())
        raises(lambda: eng.open_instrumental_lane(purpose="targeted_ablation", parent="N002", text="too short",
                                                  brief_title="x"),
               SystemExit, "a short question is refused", contains="--question")
        hold = {"id": "H001", "status": "active", "scope": {"kind": "round", "id": eng.st["current_round"]}}
        eng.st.setdefault("holds", []).append(hold)
        raises(lambda: eng.open_instrumental_lane(purpose="targeted_ablation", parent="N002",
                                                  text="Is KC1 the cause of the gain N002 measured on C1?",
                                                  brief_title="x"),
               SystemExit, "a held round refuses intake", contains="hold")
        check(closer["status"] == "open" and len(store.events()) == before and eng.st["lanes"] == [],
              "a refusal cancels no close_round task and logs no event")
        eng.st["holds"].remove(hold)
        lane = eng.open_instrumental_lane(purpose="targeted_ablation", parent="N002",
                                          text="Is KC1 the cause of the gain N002 measured on C1?",
                                          brief_title="x")
        check(closer["status"] == "cancelled" and lane["id"] == eng.st["lanes"][-1]["id"],
              "once the lane is certain the close lifecycle is cancelled")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def the_mechanism_label_keeps_the_causal_and_probe_facts_apart() -> None:
    # the causal status is credited to the ablation that settled it; the
    # probe's answer is a trailing note, with its correction id when a formula
    # error was corrected on record - two facts, neither outranks the other
    node = _candidate("N002", mechanism_status="confirmed", probe_result={"status": "unclear"},
                      mechanism_corrections=[{"id": "CR001", "from": "confirmed", "to": "unclear",
                                              "at": "2026-03-01T00:00:00Z"}],
                      mechanism_settlements=[{"ablation": "N040", "from": "deferred", "to": "confirmed",
                                              "effect": "observed", "at": "2026-02-01T00:00:00Z"}])
    check(egraph.mechanism_label(node) == "confirmed (via N040); probe unclear (corrected CR001)",
          f"causal status via its ablation, probe answer with its correction: {egraph.mechanism_label(node)}")
    probed = _candidate("N003", probe_result={"status": "confirmed"})
    check(egraph.mechanism_label(probed) == "deferred; probe used",
          f"a passing probe is information beside a still-deferred causal status: {egraph.mechanism_label(probed)}")
    check(egraph.mechanism_label(_candidate("N004")) == "deferred",
          "no probe and nothing settled: the causal status alone")
    refuted = _candidate("N005", mechanism_status="refuted",
                         refuted_kernel={"kernels": ["KC1"], "ablation": "N041", "control": "N041"},
                         mechanism_settlements=[{"ablation": "N041", "from": "deferred", "to": "refuted",
                                                 "effect": "not_observed", "at": "2026-02-01T00:00:00Z"}])
    check(egraph.mechanism_label(refuted) == "refuted (via N041; build on N041)",
          f"a refuted kernel names the clean control version to build on: {egraph.mechanism_label(refuted)}")
    refuted["refuted_kernel"]["control"] = None
    check(egraph.mechanism_label(refuted) == "refuted (via N041; remove KC1 in children)",
          f"without a clean control the label says what children must do: {egraph.mechanism_label(refuted)}")
    losses = egraph.losses_fragment({"evaluation_summary": {"required_target_losses": ["C4", "C5"],
                                                            "target_losses": ["C4", "C5", "C6"],
                                                            "guardrail_losses": ["C3"], "breadth_losses": ["C2"]}})
    check(losses == "required: C4,C5; target: C6; guardrail: C3; breadth: C2",
          f"the losses fragment names every lost cell by kind (no pipe - it sits in a table cell): {losses}")
    check(egraph.losses_fragment(_candidate("N003")) == "-", "no losses prints a dash")


# ---------------------------------------------------------------- the gate ----
def _ablation_lane(eng, repo: Path, lid: str, iid: str, *, parent: str, purpose: str, costly_runs: int) -> dict:
    _write_json(repo, f".evo/ideas/{iid}.meta.json",
                {"idea": iid, "lane": lid, "experiment_purpose": purpose, "level": 0, "parents": [parent],
                 "ablation": {"parent": parent, "costly_runs": costly_runs, "settles_parent_mechanism": True}})
    lane = {"id": lid, "round": "R001", "name": lid.lower(), "intent": "exploit",
            "experiment_purpose": purpose, "search_origin": "repair", "min_level": 0,
            "parents": [parent], "bottleneck_ids": [], "status": "gate", "idea": iid,
            "cycles": {"sketch": 0, "mature": 0, "theory": 0, "ablation": 0},
            "idea_seal": {"digest": uuid.uuid4().hex * 2}, "review_seal": {"digest": uuid.uuid4().hex * 2},
            "node": None, "abandon_reason": None}
    eng.st["lanes"].append(lane)
    return lane


def _idea_gate(eng, store, lane: dict) -> dict:
    return store.new_gate(eng.st, "idea_approval",
                          {"lane": lane["id"], "idea": lane["idea"],
                           "contract_digest": eng._idea_contract_digest(lane)},
                          f"lane {lane['id']} idea {lane['idea']}")


def designs_above_the_allowance_and_every_probe_wait_for_the_user() -> None:
    repo, store, eng = _fresh_engine("gate")
    try:
        _running_round(eng)
        _set_multiple(eng, 2.0)
        eng.cfg.setdefault("policy", {})["autonomy"] = "full_auto"
        eng.g["nodes"] += [_baseline(), _candidate("N002")]
        eng.st["resource_ledger"] = [_charge("N002", {"gpu_hours": 4.0}, run="RUN001")]
        cheap = _ablation_lane(eng, repo, "L001", "I001", parent="N002", purpose="targeted_ablation", costly_runs=1)
        inside, lines = evalid.ablation_design_within_allowance(eng.ctx(), cheap)
        check(inside and "planned 4" in lines[0] and "vs allowed 8" in lines[0],
              f"one changed-component run on a 4 gpu_hour parent sits inside the 2x allowance: {lines}")
        gate = _idea_gate(eng, store, cheap)
        resolved = eng._maybe_auto_resolve(gate)
        check(resolved is True and gate["status"] == "approved",
              f"inside the allowance under full_auto the idea gate resolves itself: {resolved}, {gate['status']}")

        dear = _ablation_lane(eng, repo, "L002", "I002", parent="N002", purpose="targeted_ablation", costly_runs=5)
        inside, lines = evalid.ablation_design_within_allowance(eng.ctx(), dear)
        check(not inside and "planned 20" in lines[0] and "ABOVE" in lines[0],
              f"five runs (20) exceed the allowance (8): {lines}")
        gate = _idea_gate(eng, store, dear)
        check(eng._maybe_auto_resolve(gate) is False and gate["status"] == "open" and dear["status"] == "gate",
              "a design above the allowance waits for the user even under full_auto")

        probe = _ablation_lane(eng, repo, "L003", "I003", parent="N002", purpose="diagnostic_probe", costly_runs=1)
        gate = _idea_gate(eng, store, probe)
        check(eng._maybe_auto_resolve(gate) is False and gate["status"] == "open",
              "a diagnostic probe's gate is manual regardless of any allowance")

        eng.cfg["policy"]["autonomy"] = "gated"
        gated = _ablation_lane(eng, repo, "L004", "I004", parent="N002", purpose="targeted_ablation", costly_runs=1)
        gate = _idea_gate(eng, store, gated)
        check(eng._maybe_auto_resolve(gate) is False and gate["status"] == "open",
              "inside the allowance under gated autonomy the ordinary policy still asks the user")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def engineering_mode_opens_no_ablation_by_itself() -> None:
    repo, store, eng = _fresh_engine("engineering")
    try:
        _running_round(eng)
        _set_multiple(eng, 2.0)
        eng.cfg.setdefault("project", {})["mode"] = "engineering"
        node = _candidate("N002")
        eng.g["nodes"] += [_baseline(), node]
        before = len(eng.st["lanes"])
        advice = eng._open_inheritance_tax(node, "KC1")
        check(len(eng.st["lanes"]) == before and "ablation_lane" not in node and "ablation_pending" not in node,
              "engineering mode inherits programs on their numbers: the engine mints no ablation lane")
        check(len(advice) == 1 and "engineering mode" in advice[0] and "evo ablate --parent N002" in advice[0],
              f"the advice says why and keeps the door open to people: {advice}")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)



def a_child_declares_what_it_did_about_a_refuted_kernel() -> None:
    repo, store, eng = _fresh_engine("disposition")
    try:
        parent = _candidate("N002", refuted_kernel={"kernels": ["KC1"], "ablation": "N020", "control": "N020",
                                                    "reading": "shell", "candidates": [], "at": eutil.utc_now()})
        control = {"id": "N020", "role": "variant", "experiment_purpose": "targeted_ablation",
                   "status": "concluded", "parents": ["N002"], "level": 0}
        eng.g["nodes"] += [_baseline(), parent, control]
        meta = {"parents": ["N002"]}
        spec = {"code_parent": "N002"}
        errs = evalid.refuted_kernel_disposition_errors(eng.ctx(), spec, meta)
        check(len(errs) == 1 and errs[0].startswith("SPEC_REFUTED_KERNEL_DISPOSITION")
              and "built_on_control (code_parent N020)" in errs[0] and "reclaimed" in errs[0],
              f"a child of a refuted parent must say what it did about the kernel; the exits name the control: {errs}")
        built = {"code_parent": "N020", "refuted_kernel_disposition": [
            {"parent": "N002", "action": "built_on_control", "note": "started from the clean control checkpoint"}]}
        check(evalid.refuted_kernel_disposition_errors(eng.ctx(), built, meta) == [],
              "building on the control version with the control as code_parent is accepted")
        wrong = {"code_parent": "N002", "refuted_kernel_disposition": [
            {"parent": "N002", "action": "built_on_control", "note": "started from the clean control checkpoint"}]}
        errs = evalid.refuted_kernel_disposition_errors(eng.ctx(), wrong, meta)
        check(any(e.startswith("SPEC_REFUTED_KERNEL_CONTROL") and "N020" in e for e in errs),
              f"built_on_control with another code_parent is refused naming the control: {errs}")
        removed = {"code_parent": "N002", "refuted_kernel_disposition": [
            {"parent": "N002", "action": "removed", "note": "the gate module was deleted from the program"}]}
        check(evalid.refuted_kernel_disposition_errors(eng.ctx(), removed, meta) == [],
              "removing the kernel on the refuted parent's code is a legal declaration")
        bad_action = {"code_parent": "N002", "refuted_kernel_disposition": [
            {"parent": "N002", "action": "kept", "note": "x" * 30}]}
        check(any(e.startswith("SPEC_REFUTED_KERNEL_ACTION") for e in
                  evalid.refuted_kernel_disposition_errors(eng.ctx(), bad_action, meta)),
              "the action vocabulary is closed")
        # a stand-in control settles the question but is not the program to build on
        parent["refuted_kernel"]["control"] = None
        errs = evalid.refuted_kernel_disposition_errors(eng.ctx(), built, meta)
        check(any(e.startswith("SPEC_REFUTED_KERNEL_CONTROL") and "no clean trained control" in e for e in errs),
              f"without a clean control the child removes or replaces the kernel itself: {errs}")
        check(evalid.refuted_kernel_disposition_errors(eng.ctx(), {"code_parent": "N001"}, {"parents": ["N001"]}) == [],
              "a parent without a refuted kernel owes no disposition")
        # the write-back records the control only when the design said the arm was the clean program
        _running_round(eng)
        standin_parent = _tradeoff_parent("N004")
        standin = _ablation_child(repo, "N005", "N004", effect="not_observed", clean=False)
        eng.g["nodes"] += [standin_parent, standin]
        eng._settle_parent_mechanism_from_ablation(standin)
        check(standin_parent["mechanism_status"] == "refuted" and standin_parent["refuted_kernel"]["control"] is None
              and egraph.mechanism_label(standin_parent) == "refuted (via N005; remove KC1 in children)",
              f"a stand-in control refutes the kernel but names no program to build on: {egraph.mechanism_label(standin_parent)}")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)

def main() -> None:
    allowance_is_a_multiple_of_the_parents_own_charge()
    run_arithmetic_speaks_only_with_a_recorded_floor()
    a_deferred_win_opens_its_ablation_in_the_running_round()
    engineering_mode_opens_no_ablation_by_itself()
    a_child_declares_what_it_did_about_a_refuted_kernel()
    the_engine_says_why_when_it_does_not_mint()
    an_ablation_settles_the_parents_mechanism_from_its_own_result()
    promotion_recomputes_follow_the_claim_inheritance_reads()
    pending_ablations_are_opened_when_a_round_goes_running()
    a_concluded_tax_lane_frees_the_parents_doors()
    a_refused_intake_has_no_side_effects()
    the_mechanism_label_keeps_the_causal_and_probe_facts_apart()
    designs_above_the_allowance_and_every_probe_wait_for_the_user()
    done("INHERITANCE TAX UNIT")


if __name__ == "__main__":
    main()
