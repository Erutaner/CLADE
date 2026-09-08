"""Post-hoc claims and mechanism premises.

A concluded candidate may be re-priced with the data in hand: a NEW claim
on the same sealed metrics, labeled post-hoc, judged by the user, never
rewriting the original bet. And a lane that builds on a node's STORY (not
its numbers) declares the premise, which must already be settled.

Unit-speed pins on a scratch engine with a two-cell contract:
  - which proposals are filable, and what each refusal names
  - the settlement is computed from the sealed metrics under the new scope
  - `evo claim` files, seals and opens the user's gate; approve installs the
    claim as the one inheritance reads, reject records the rejection
  - the portfolio validator refuses an unsettled mechanism premise and names
    its exit

    python tests/posthoc_claim_unit.py
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))
from _check import check, done, raises  # noqa: E402

import ecards    # noqa: E402
import econfig   # noqa: E402
import eflow     # noqa: E402
import egraph    # noqa: E402
import eprogram  # noqa: E402
import esched    # noqa: E402
import eseal     # noqa: E402
import estore    # noqa: E402
import eutil     # noqa: E402
import evalid    # noqa: E402
import evo       # noqa: E402

AXES = list(eprogram.RESOURCE_AXES)
REALIZED = {axis: {"lower": 1.0, "upper": 1.0, "source": "receipt"} for axis in AXES}


def _cell(cid: str, task: str, key: str, *, required: bool) -> dict:
    return {"id": cid, "dataset": "D1", "task": task, "metric": key, "result_key": key, "role": "target",
            "weight": 1.0, "min_improvement": 0.005, "noninferiority_margin": 0.005, "required": required,
            "goal_threshold": None}


def _two_cell_contract(cfg: dict) -> dict:
    """C1 (required) and C2 (not required) on two tasks; higher is better on both."""
    cfg["project"]["primary_metric"] = "m1"
    cfg["metrics"] = [{"key": k, "name": k, "direction": "max", "definition": f"{k} on the frozen split",
                       "source": f"eval writes {k}"} for k in ("m1", "m2")]
    cfg["evaluation_contract"].update({
        "model_scope": "single_checkpoint", "display_cell": "C1",
        "datasets": [{"id": "D1", "name": "frozen split", "split": "val", "protocol": "fixed", "source": "kb"}],
        "tasks": [{"id": "T1", "name": "ranking", "aggregation": "all", "weight": 1.0},
                  {"id": "T2", "name": "calibration", "aggregation": "all", "weight": 1.0}],
        "cells": [_cell("C1", "T1", "m1", required=True), _cell("C2", "T2", "m2", required=False)],
        "task_groups": [{"id": "G1", "tasks": ["T1"], "aggregation": "all", "required": True},
                        {"id": "G2", "tasks": ["T2"], "aggregation": "all", "required": False}],
        "decision": {"min_target_groups_improved": 1, "min_target_groups_goal_met": 0,
                     "guardrails_must_be_noninferior": True, "allow_specialist": True},
    })
    return cfg


def _fresh_engine(tag: str):
    repo = HERE / "out" / f"posthoc-{tag}-{uuid.uuid4().hex[:8]}"
    repo.mkdir(parents=True)
    store = estore.Store(repo)
    store.init("posthoc-unit", "re-price a bet on record")
    cfg_path = repo / ".evo/config.json"
    cfg_path.write_text(json.dumps(_two_cell_contract(json.loads(cfg_path.read_text(encoding="utf-8"))),
                                   indent=1), encoding="utf-8")
    return repo, store, esched.Engine(store)


def _write_json(repo: Path, rel: str, data) -> None:
    eutil.write_json_atomic(repo / rel, data)


def _original_meta(scope_kind: str, cells: list[str], lines: dict[str, float]) -> dict:
    return {"idea": "I001", "lane": "L001", "title": "reweighted head", "experiment_purpose": "candidate",
            "level": 2, "parents": ["N001"], "platforms_consumed": [],
            "novelty": {"kind": "irreducible", "kernel": [{"id": "KC1"}]},
            "claim_scope": {"kind": scope_kind, "target_cells": cells, "guardrail_cells": []},
            "effect_case": {"comparator_id": "baseline",
                            "chain": [{"target_cell": cid, "direction": "increase",
                                       "minimum_worthwhile_delta": delta,
                                       "expected_delta_interval": [delta, delta + 0.1],
                                       "kernel_refs": ["KC1"]} for cid, delta in lines.items()],
                            "resources": {"regime": "matched", "fixed_axes": AXES, "tradeoff_axes": [],
                                          "improvement_axes": [], "candidate": {a: 10.0 for a in AXES},
                                          "comparator": {a: 10.0 for a in AXES}}},
            "predictions": []}


def _concluded_candidate(repo: Path, eng, *, metrics: dict, meta: dict) -> dict:
    """A concluded candidate settled the way the engine settles one: the
    frozen assessment on its sealed metrics, mechanism deferred (no probe)."""
    baseline = {"id": "N001", "title": "origin", "role": "baseline", "experiment_purpose": "candidate",
                "status": "concluded", "verdict": "baseline", "parents": [], "level": 0,
                "scores": {"m1": 0.70, "m2": 0.60}, "score_evidence": {"m1": 0.70, "m2": 0.60},
                "effect_resources_realized": json.loads(json.dumps(REALIZED))}
    node = {"id": "N002", "title": "reweighted head", "role": "variant", "experiment_purpose": "candidate",
            "status": "concluded", "parents": ["N001"], "code_parent": "N001", "level": 2, "round": "R001",
            "idea_doc": ".evo/ideas/I001.md", "effect_comparator_node": "N001", "kernel_ids": ["KC1"],
            "eval_metrics_path": ".evo/nodes/N002/eval/metrics.json",
            "outcome_path": ".evo/nodes/N002/OUTCOME.json", "result_doc": ".evo/nodes/N002/NODE_RESULT.md",
            "scores": {k: v for k, v in metrics.items() if not k.startswith("_")},
            "score_evidence": {k: v for k, v in metrics.items() if not k.startswith("_")}}
    eng.g["nodes"] += [baseline, node]
    eutil.write_text(repo / ".evo/ideas/I001.md", "# reweighted head\n")
    _write_json(repo, ".evo/ideas/I001.meta.json", meta)
    _write_json(repo, node["eval_metrics_path"], metrics)
    assessment = evalid.computed_assessment(eng.ctx(), node, metrics)
    node["evaluation_summary"] = assessment
    node["verdict"] = assessment["verdict"]
    node["effect_contract_status"] = assessment["effect_contract_status"]
    node["mechanism_status"] = assessment["mechanism_contract_status"]
    node["scientific_promotion_status"] = assessment["scientific_promotion_status"]
    _write_json(repo, node["outcome_path"], {"verdict": node["verdict"], "effect_contract_status":
                                             node["effect_contract_status"]})
    eutil.write_text(repo / node["result_doc"], "# result\n\nsettled on the sealed metrics\n")
    node["conclusion_seal"] = eseal.create(repo, [("outcome", node["outcome_path"]),
                                                  ("node_result", node["result_doc"])])
    eng.save()
    return node


def _claim(**override) -> dict:
    data = {"node": "N002",
            "reason": ("the generalist line on C2 was a guess made before any calibration run existed; the "
                       "ranking gain on C1 is four floors wide and is the result this lineage is built on"),
            "claim_scope": {"kind": "specialist", "target_cells": ["C1"], "guardrail_cells": []},
            "lines": [{"target_cell": "C1", "direction": "increase", "minimum_worthwhile_delta": 0.02}]}
    data.update(override)
    return data


METRICS = {"m1": 0.75, "m2": 0.58, "_effect_resources": json.loads(json.dumps(REALIZED))}


def a_claim_is_filable_only_when_it_prices_something_new() -> None:
    repo, store, eng = _fresh_engine("filable")
    try:
        node = _concluded_candidate(repo, eng, metrics=METRICS,
                                    meta=_original_meta("generalist", ["C1", "C2"], {"C1": 0.02, "C2": 0.01}))
        # effect status: the C1 row met its line, the C2 row failed -> the rows split -> `partial`
        check(node["verdict"] == "tradeoff" and node["effect_contract_status"] == "partial"
              and node["mechanism_status"] == "deferred" and node["scientific_promotion_status"] == "met",
              f"the original bet: won C1, lost C2, missed its C2 line, still a real win: "
              f"{node['verdict']}/{node['effect_contract_status']}/{node['scientific_promotion_status']}")
        ctx = eng.ctx()

        def errs(**override):
            return evalid.posthoc_claim_errors(ctx, node, _claim(**override))

        check(errs() == [], "a specialist claim on the cell it really won is filable")
        e = errs(claim_scope={"kind": "generalist", "target_cells": ["C1", "C2"], "guardrail_cells": []},
                 lines=[{"target_cell": "C1", "direction": "increase", "minimum_worthwhile_delta": 0.02},
                        {"target_cell": "C2", "direction": "increase", "minimum_worthwhile_delta": 0.01}])
        check(any(x.startswith("CLAIM_NO_CHANGE") for x in e), f"restating the original bet is not a claim: {e}")
        e = errs(claim_scope={"kind": "specialist", "target_cells": ["C2"], "guardrail_cells": []},
                 lines=[{"target_cell": "C2", "direction": "increase", "minimum_worthwhile_delta": 0.0}])
        check(any(x.startswith("CLAIM_REQUIRED_TARGETS") and "C1" in x for x in e),
              f"a required cell cannot be scoped away: {e}")
        e = errs(claim_scope={"kind": "narrow", "target_cells": ["C1"], "guardrail_cells": []})
        check(any(x.startswith("CLAIM_KIND") for x in e), f"the claim kind vocabulary is closed: {e}")
        e = errs(claim_scope={"kind": "generalist", "target_cells": ["C1", "C2"], "guardrail_cells": []})
        check(any(x.startswith("CLAIM_LINES_COVERAGE") and "C2" in x for x in e),
              f"every claimed cell needs its line: {e}")
        e = errs(lines=[{"target_cell": "C1", "direction": "sideways", "minimum_worthwhile_delta": -1}])
        check(any(x.startswith("CLAIM_LINE_DIRECTION") for x in e)
              and any(x.startswith("CLAIM_LINE_DELTA") for x in e), f"lines are numeric and directed: {e}")
        e = errs(reason="too short")
        check(any(x.startswith("FIELD_TOO_SHORT") and "reason" in x for x in e),
              f"the reason must stand on its own: {e}")
        e = errs(node="N001")
        check(any(x.startswith("CLAIM_NODE_BINDING") for x in e), f"the proposal binds its node: {e}")
        executing = dict(node, status="executing")
        e = evalid.posthoc_claim_errors(ctx, executing, _claim())
        check(any(x.startswith("CLAIM_NODE") for x in e), f"an unfinished node has no data to re-price: {e}")
        e = evalid.posthoc_claim_errors(ctx, node, "not an object")
        check(e == ["CLAIM_SHAPE: the proposal must be a JSON object"], f"shape is checked first: {e}")

        settled = evalid.assess_posthoc_claim(ctx, node, _claim())
        check(settled["claim_kind"] == "specialist" and settled["target_cells"] == ["C1"]
              and settled["real_win"] is True and settled["target_wins"] == ["C1"]
              and settled["effect_contract_status"] == "met",
              f"the new claim settles from the same sealed metrics: {settled['verdict']}/"
              f"{settled['effect_contract_status']} wins={settled['target_wins']}")
        check(settled["verdict"] == "tradeoff" and settled["breadth_losses"] == ["C2"],
              f"scoping C2 out of the claim does not hide its loss - it is listed: {settled['verdict']} "
              f"{settled['breadth_losses']}")
        check(settled["scientific_promotion_status"] == "met" and settled["mechanism_contract_status"] == "deferred",
              "promotion under the new claim follows the measured win; the mechanism question is untouched")
        check(node["evaluation_summary"]["effect_contract_status"] == "partial"
              and node["verdict"] == "tradeoff",
              "assessing a proposal changes nothing on the node")
        # The settlement reads the node's LIVE mechanism, never the registered
        # probe again: a mechanism refuted since evaluate is what approval
        # would inherit under.
        refuted = dict(node, mechanism_status="refuted")
        under_refuted = evalid.assess_posthoc_claim(ctx, refuted, _claim())
        check(under_refuted["mechanism_contract_status"] == "refuted"
              and under_refuted["scientific_promotion_status"] == "met"
              and under_refuted["verdict"] == settled["verdict"]
              and under_refuted["effect_contract_status"] == settled["effect_contract_status"],
              "the settlement records the live causal status and the promotion ignores it - a refuted "
              f"story never moves parenthood: {under_refuted['mechanism_contract_status']}/"
              f"{under_refuted['scientific_promotion_status']}")
        # The ruler is the node's frozen one: correcting C1's `required` flag
        # away after the node was measured does not let its claim scope C1 out.
        node["eval_cells_frozen"] = evalid.frozen_cell_constants(ctx.cfg)
        amended_cfg = json.loads(json.dumps(ctx.cfg))
        amended_cfg["evaluation_contract"]["cells"][0]["required"] = False
        amended_cfg["evaluation_contract"]["cells"][0]["min_improvement"] = 0.2
        amended_ctx = evalid.Ctx(store, eng.st, amended_cfg, eng.g, reg={})
        e = evalid.posthoc_claim_errors(amended_ctx, node,
                                        _claim(claim_scope={"kind": "specialist", "target_cells": ["C2"],
                                                            "guardrail_cells": []},
                                               lines=[{"target_cell": "C2", "direction": "increase",
                                                       "minimum_worthwhile_delta": 0.0}]))
        check(any(x.startswith("CLAIM_REQUIRED_TARGETS") and "C1" in x for x in e),
              f"the frozen ruler still holds C1 required for this node: {e}")
        frozen_settled = evalid.assess_posthoc_claim(amended_ctx, node, _claim())
        check(frozen_settled["target_wins"] == ["C1"] and frozen_settled["verdict"] == settled["verdict"],
              "a worthwhile delta raised after the measurement does not move this node's settlement: "
              f"{frozen_settled['target_wins']}/{frozen_settled['verdict']}")
        node.pop("eval_cells_frozen", None)
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def the_cli_files_the_claim_and_the_user_decides() -> None:
    repo, store, eng = _fresh_engine("cli")
    try:
        _concluded_candidate(repo, eng, metrics=METRICS,
                             meta=_original_meta("generalist", ["C1", "C2"], {"C1": 0.02, "C2": 0.01}))
        _write_json(repo, "claims/c1_specialist.json", _claim())
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            rc = evo.cmd_claim(store, SimpleNamespace(node="N002", proposal="claims/c1_specialist.json",
                                                      session="sess-proposer"))
        st = store.load_state()
        record = st["posthoc_claims"][0]
        check(rc == 0 and record["id"] == "PC001" and record["node"] == "N002"
              and record["status"] == "awaiting_user" and record["gate"] == "G001"
              and record["proposer_session"] == "sess-proposer"
              and record["settlement"]["effect_contract_status"] == "met"
              and record["settlement"]["target_wins"] == ["C1"],
              f"the claim is filed, settled and handed to the user: {record}")
        # the filing record and the CLI print show the mechanism the claim is
        # judged under and the promotion approval would install
        check(record["settlement"]["mechanism_status"] == "deferred"
              and record["settlement"]["scientific_promotion_status"] == "met"
              and "live mechanism deferred" in printed.getvalue()
              and "approval would set scientific promotion met -> met" in printed.getvalue(),
              f"filing records and prints mechanism + would-be promotion: {record['settlement']}\n{printed.getvalue()}")
        filed = json.loads((repo / record["proposal_path"]).read_text(encoding="utf-8"))
        check(filed["post_hoc"] is True and filed["id"] == "PC001" and filed["filed_at"]
              and eseal.verify(repo, record["proposal_seal"], label="claim") == [],
              "the filed proposal is labeled post-hoc, timestamped and sealed")
        gate = next(g for g in st["gates"] if g["id"] == "G001")
        check(gate["kind"] == "posthoc_claim" and gate["status"] == "open"
              and gate["subject"] == {"node": "N002", "claim": "PC001"},
              f"the gate is the user's: {gate}")
        check(eflow.GATE_POLICY["posthoc_claim"].protected and eflow.GATE_POLICY["posthoc_claim"].auto == "never"
              and "posthoc_claim" in econfig.GATE_KINDS,
              "the gate kind is registered and never auto-resolved")
        raises(lambda: evo.cmd_claim(store, SimpleNamespace(node="N002", proposal="claims/c1_specialist.json",
                                                           session=None)),
               SystemExit, "a second claim waits for the first decision", contains="awaits the user")

        eng = esched.Engine(store)
        report = "\n".join(eng._gate_report(next(g for g in eng.st["gates"] if g["id"] == "G001")))
        check("POST-HOC CLAIM PC001 on N002" in report and "ORIGINAL bet: generalist on C1, C2" in report
              and "settled verdict tradeoff / effect partial / promotion met" in report
              and "NEW claim: specialist on C1" in report and "SAME sealed metrics: verdict tradeoff / effect met" in report
              and "claim filed" in report,
              f"the report shows both claims, both settlements and the timing:\n{report}")
        check("judged under the node's LIVE mechanism: deferred" in report
              and "approval would set scientific promotion met -> met" in report,
              f"the report shows the mechanism the claim is judged under and the promotion approval produces:\n{report}")
        check(eng._maybe_auto_resolve(next(g for g in eng.st["gates"] if g["id"] == "G001")) is False,
              "full_auto never decides a post-hoc claim")
        eng.decide("G001", True, "the C2 line was a guess; the C1 win is what we build on", None)

        eng = esched.Engine(store)
        node = eng.node("N002")
        check(node["active_claim"] == "PC001" and node["scientific_promotion_status"] == "met"
              and node["posthoc_assessment"]["effect_contract_status"] == "met"
              and node["posthoc_assessment"]["real_win"] is True
              and node["posthoc_assessment"]["target_wins"] == ["C1"],
              f"approval installs the claim inheritance reads: {node.get('posthoc_assessment')}")
        check(node["verdict"] == "tradeoff" and node["effect_contract_status"] == "partial"
              and node["evaluation_summary"]["effect_contract_status"] == "partial",
              "the original verdict and effect record are untouched")
        check(egraph.promotion_label(node) == "met (post-hoc PC001)",
              f"the frontier says which claim it reads: {egraph.promotion_label(node)}")
        check(node["posthoc_claims"][-1]["id"] == "PC001" and node["posthoc_claims"][-1]["gate"] == "G001"
              and node["posthoc_claims"][-1]["promotion_from"] == "met",
              f"the node keeps the ledger of its claims: {node['posthoc_claims']}")
        record = eng.st["posthoc_claims"][0]
        check(record["status"] == "approved" and record.get("applied_at"), f"the record closes approved: {record}")
        check(any(e.get("event") == "posthoc_claim_approved" and e.get("claim") == "PC001"
                  for e in store.events()), "approval is an event")
        graph_md = (repo / ".evo/views/GRAPH.md").read_text(encoding="utf-8")
        check("post-hoc PC001" in graph_md, "the rendered views carry the post-hoc marker")

        # a second, dearer line: the user rejects it and nothing moves
        _write_json(repo, "claims/c1_dearer.json",
                    _claim(lines=[{"target_cell": "C1", "direction": "increase", "minimum_worthwhile_delta": 0.04}]))
        evo.cmd_claim(store, SimpleNamespace(node="N002", proposal="claims/c1_dearer.json", session=None))
        eng = esched.Engine(store)
        record2 = eng.st["posthoc_claims"][1]
        check(record2["id"] == "PC002" and record2["gate"] == "G002", f"the second claim files as PC002: {record2}")
        eng.decide("G002", False, "one re-pricing is enough", None)
        eng = esched.Engine(store)
        node = eng.node("N002")
        record2 = eng.st["posthoc_claims"][1]
        check(record2["status"] == "rejected_by_user" and record2.get("closed_at")
              and node["active_claim"] == "PC001" and len(node["posthoc_claims"]) == 1,
              f"a rejected claim is recorded and changes nothing: {record2['status']}, {node['active_claim']}")
        check(any(e.get("event") == "posthoc_claim_rejected" and e.get("claim") == "PC002"
                  for e in store.events()), "rejection is an event")
        check(any("evo claim" in row for row in ecards.doors_for("conclude")),
              "the conclude card lists the claim door")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def a_claim_is_bound_to_the_conclusion_it_priced() -> None:
    """Transition pins: approve refuses when the node's live conclusion is not
    the one the claim was filed against (exit named); approval records the
    LIVE mechanism it was judged under; a recovery re-analysis supersedes the
    approved claim, cancels an undecided one, and frees the claim door."""
    repo, store, eng = _fresh_engine("bound")
    try:
        _concluded_candidate(repo, eng, metrics=METRICS,
                             meta=_original_meta("generalist", ["C1", "C2"], {"C1": 0.02, "C2": 0.01}))
        _write_json(repo, "claims/c1_specialist.json", _claim())
        evo.cmd_claim(store, SimpleNamespace(node="N002", proposal="claims/c1_specialist.json", session=None))
        eng = esched.Engine(store)
        node = eng.node("N002")
        # the node re-concluded under a fresh seal (what a recovery replay leaves behind)
        node["conclusion_seal"] = eseal.create(repo, [("outcome", node["outcome_path"]),
                                                      ("node_result", node["result_doc"])], revision=2)
        events_before = len(store.events())
        raises(lambda: eng.decide("G001", True, "approve anyway", None), SystemExit,
               "a claim filed against a conclusion that moved is not applied", contains="re-file with evo claim")
        # a refusal has no side effects: the gate row is untouched in memory
        # and on disk, and no decision event was appended
        gate_row = next(g for g in eng.st["gates"] if g["id"] == "G001")
        appended = [e.get("event") for e in store.events()[events_before:]]
        check(gate_row["status"] == "open" and gate_row.get("decided_at") is None and appended == [],
              f"the refused decision left the gate open and wrote no event: {gate_row}, appended {appended}")
        eng = esched.Engine(store)
        node = eng.node("N002")
        check(node.get("active_claim") is None and eng.st["posthoc_claims"][0]["status"] == "awaiting_user"
              and next(g for g in eng.st["gates"] if g["id"] == "G001")["status"] == "open",
              "the refused decision changed nothing on record")
        report = "\n".join(eng._gate_report(next(g for g in eng.st["gates"] if g["id"] == "G001")))
        node["status"] = "workflow_done"
        report_moved = "\n".join(eng._gate_report(next(g for g in eng.st["gates"] if g["id"] == "G001")))
        check("approve will be refused" not in report and "approve will be refused" in report_moved
              and "re-file with evo claim" in report_moved,
              f"the gate report warns exactly when approval would be refused:\n{report_moved}")
        raises(lambda: eng.decide("G001", True, "approve anyway", None), SystemExit,
               "an un-concluded node cannot take a claim", contains="re-file with evo claim")
        eng = esched.Engine(store)
        # a live mechanism moved by an ablation write-back: the claim is judged under it
        node = eng.node("N002")
        node["mechanism_status"] = "refuted"
        node["mechanism_settlements"] = [{"ablation": "N009", "from": "deferred", "to": "refuted",
                                          "effect": "not_observed", "at": eutil.utc_now()}]
        report_refuted = "\n".join(eng._gate_report(next(g for g in eng.st["gates"] if g["id"] == "G001")))
        check("LIVE mechanism: refuted (via N009; remove the kernel in children)" in report_refuted
              and "approval would set scientific promotion met -> met" in report_refuted,
              f"a refuted live mechanism shows in the report; the promotion it implies is unmoved by it:\n{report_refuted}")
        node["mechanism_status"] = "deferred"
        node.pop("mechanism_settlements")
        eng.decide("G001", True, "the C1 win is what we build on", None)
        eng = esched.Engine(store)
        node = eng.node("N002")
        check(node["active_claim"] == "PC001" and node["posthoc_assessment"]["mechanism_status"] == "deferred"
              and node["posthoc_assessment"]["scientific_promotion_status"] == "met"
              and eng.st["posthoc_claims"][0]["settlement"]["mechanism_status"] == "deferred"
              and eng.st["posthoc_claims"][0]["settlement"]["scientific_promotion_status"] == "met",
              f"approval records the mechanism it was judged under and the promotion: {node['posthoc_assessment']}")
        # a second claim awaits the user when a recovery re-analyses the node
        _write_json(repo, "claims/c1_dearer.json",
                    _claim(lines=[{"target_cell": "C1", "direction": "increase", "minimum_worthwhile_delta": 0.04}]))
        evo.cmd_claim(store, SimpleNamespace(node="N002", proposal="claims/c1_dearer.json", session=None))
        eng = esched.Engine(store)
        node = eng.node("N002")
        eng._clear_conclusion_projection(node, "RV001")
        records = {c["id"]: c for c in eng.st["posthoc_claims"]}
        gate2 = next(g for g in eng.st["gates"] if g["id"] == "G002")
        check("active_claim" not in node and "posthoc_assessment" not in node
              and records["PC001"]["status"] == "superseded_by_recovery" and records["PC001"]["superseded_by"] == "RV001"
              and records["PC002"]["status"] == "cancelled_by_recovery" and gate2["status"] == "cancelled"
              and "re-file with evo claim" in gate2["decision_note"],
              f"recovery pops the live claim, supersedes the approved record and cancels the open one: {records}")
        check(any(e.get("event") == "posthoc_claim_superseded" and e.get("claim") == "PC001" for e in store.events())
              and any(e.get("event") == "posthoc_claim_cancelled" and e.get("claim") == "PC002" for e in store.events()),
              "supersession and cancellation are events")
        eng.save()
        _write_json(repo, "claims/again.json", _claim())
        rc = evo.cmd_claim(store, SimpleNamespace(node="N002", proposal="claims/again.json", session=None))
        st = store.load_state()
        check(rc == 0 and st["posthoc_claims"][-1]["id"] == "PC003" and st["posthoc_claims"][-1]["status"] == "awaiting_user",
              f"the claim door is open again after the recovery: {st['posthoc_claims'][-1]}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def an_unsettled_mechanism_is_not_a_planning_premise() -> None:
    """The premise block of v_open_round on a minimal portfolio: only the
    PORTFOLIO_MECHANISM_PREMISE* codes are asserted - other portfolio
    refusals of this bare fixture are not the subject here."""
    repo, store, eng = _fresh_engine("premise")
    try:
        _concluded_candidate(repo, eng, metrics=METRICS,
                             meta=_original_meta("generalist", ["C1", "C2"], {"C1": 0.02, "C2": 0.01}))
        node = eng.node("N002")
        eng.cfg["budgets"].update({"lanes_per_round_min": 1, "lanes_per_round_max": 3})
        task = {"subject": {"round": "R001"}, "outputs": [".evo/rounds/R001/PORTFOLIO.json"]}

        def errs(**lane):
            ln = {"name": "on-the-story", "intent": "exploit", "experiment_purpose": "candidate",
                  "search_origin": "repair", "min_level": 2, "parents": ["N002"], "bottleneck_ids": [],
                  "brief_md": ".evo/rounds/R001/lanes/on-the-story/BRIEF.md"}
            ln.update(lane)
            _write_json(repo, task["outputs"][0], {"lanes": [ln]})
            return [e for e in evalid.v_open_round(eng.ctx(), task) if "MECHANISM_PREMISE" in e]

        e = errs(mechanism_premises=["N002"])
        check(len(e) == 1 and e[0].startswith("PORTFOLIO_MECHANISM_PREMISE_UNSETTLED")
              and "N002's mechanism is deferred" in e[0] and "evo ablate --parent N002" in e[0]
              and "PROGRAM" in e[0],
              f"a deferred story cannot be a premise, and the exit names both doors: {e}")
        check(errs() == [], "a lane that inherits the program declares no premise and is not asked")
        e = errs(mechanism_premises="N002")
        check(len(e) == 1 and e[0].startswith("PORTFOLIO_MECHANISM_PREMISES"), f"the field is a list: {e}")
        e = errs(mechanism_premises=["N999"])
        check(len(e) == 1 and e[0].startswith("PORTFOLIO_MECHANISM_PREMISE_UNKNOWN"), f"unknown premise: {e}")
        for status in ("refuted", "unclear"):
            node["mechanism_status"] = status
            e = errs(mechanism_premises=["N002"])
            check(len(e) == 1 and f"mechanism is {status}" in e[0], f"{status} is not an established cause: {e}")
        node["mechanism_status"] = "confirmed"
        check(errs(mechanism_premises=["N002"]) == [], "a confirmed mechanism may be a premise")
        lane = eng._create_lane("R001", {"name": "on-the-story", "intent": "exploit",
                                         "experiment_purpose": "candidate", "search_origin": "repair",
                                         "min_level": 2, "parents": ["N002"], "mechanism_premises": ["N002"]})
        check(lane["mechanism_premises"] == ["N002"], "the lane record keeps the declared premise")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def main() -> None:
    a_claim_is_filable_only_when_it_prices_something_new()
    the_cli_files_the_claim_and_the_user_decides()
    a_claim_is_bound_to_the_conclusion_it_priced()
    an_unsettled_mechanism_is_not_a_planning_premise()
    done("POST-HOC CLAIM UNIT")


if __name__ == "__main__":
    main()
