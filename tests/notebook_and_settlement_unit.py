"""Notebook amendments, mechanism settlement and instrument corrections.

Unit-speed pins for the contracts that keep history and notebook apart:
  - deferred mechanisms inherit at program level; settlement reads noise
  - `evo amend` keeps old bytes, refuses frozen fields, is tolerated by the
    seal audit, and hand edits behind its back are caught by doctor
  - an instrument-correction proposal is filable only from sealed inputs, an
    independent ruling is isolation-checked, and applying it re-settles the
    node's mechanism and promotion from the same observations
  - every task card carries the doors legitimate from it; the flow tables are
    total with the new task type and gate kind

    python tests/notebook_and_settlement_unit.py
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

import eamend    # noqa: E402
import ecards    # noqa: E402
import econfig   # noqa: E402
import eflow     # noqa: E402
import egraph    # noqa: E402
import esched    # noqa: E402
import eseal     # noqa: E402
import estore    # noqa: E402
import eutil     # noqa: E402
import evalid    # noqa: E402


def _fresh_engine(tag: str):
    repo = HERE / "out" / f"notebook-{tag}-{uuid.uuid4().hex[:8]}"
    repo.mkdir(parents=True)
    store = estore.Store(repo)
    store.init("notebook-unit", "keep history and notebook apart")
    return repo, store, esched.Engine(store)


def _write(repo: Path, rel: str, text: str) -> None:
    eutil.write_text(repo / rel, text)


def _write_json(repo: Path, rel: str, data) -> None:
    eutil.write_json_atomic(repo / rel, data)


# ------------------------------------------------------------- amendments ----
def brief_amendments_keep_history() -> None:
    repo, store, eng = _fresh_engine("brief")
    try:
        brief = ".evo/rounds/R001/lanes/alpha/BRIEF.md"
        eng.st["lanes"].append({"id": "L001", "round": "R001", "name": "alpha", "status": "sketch",
                                "intent": "reform", "experiment_purpose": "candidate",
                                "search_origin": "constructive", "parents": ["N001"],
                                "min_level": 3, "brief_md": brief, "cycles": {}})
        _write(repo, brief, "# brief\n\n## Goal\nbeat 0.9572 on CanParl\n\n## Constraints\n- x\n\n## Forbidden moves\n- y\n")
        owner = eamend.owner_of(store, eng.st, eng.g, brief)
        check(owner["kind"] == "brief" and owner["lane"] == "L001", "a lane brief is notebook material")
        raises(lambda: eamend.owner_of(store, eng.st, eng.g, ".evo/state.json"), SystemExit,
               "engine state is never notebook material", contains="not notebook material")
        # an in-place edit of a never-snapshotted file cannot keep history
        _write(repo, brief, "# brief\n\n## Goal\nbeat 0.55 on CanParl (0.9572 was a padding artefact)\n")
        raises(lambda: eamend.apply(eng, brief, None, "the published 0.9572 was a padding artefact"),
               SystemExit, "in-place edit without a previous snapshot is refused",
               contains="no recorded previous version")
        raises(lambda: eamend.apply(eng, brief, brief, "the published 0.9572 was a padding artefact"),
               SystemExit, "the draft must be a separate file", contains="separate draft")
        _write(repo, "draft_brief.md", "# brief\n\n## Goal\nbeat 0.56 on CanParl\n\n## Constraints\n- x\n\n## Forbidden moves\n- y\n")
        raises(lambda: eamend.apply(eng, brief, "draft_brief.md", "too short"), SystemExit,
               "a reason is mandatory", contains="--reason")
        rec, _warn = eamend.apply(eng, brief, "draft_brief.md",
                                  "the published 0.9572 was a padding artefact; the real line is 0.54-0.56")
        check(rec["id"] == "AM001" and rec["kind"] == "brief" and rec["lane"] == "L001",
              f"the amendment is recorded with its owner: {rec}")
        check("beat 0.56" in eutil.read_text(repo / brief), "the draft was installed")
        check((repo / rec["old_snapshot"]).is_file() and (repo / rec["new_snapshot"]).is_file(),
              "both the previous and the new bytes are kept as snapshots")
        check(eamend.latest_digests(store)[brief] == rec["new_digest"], "the ledger names the live digest")
        check(eamend.integrity_problems(store) == [], "a recorded amendment is clean for doctor")
        # a second correction may now be made in place: the previous version is known
        _write(repo, brief, "# brief\n\n## Goal\nbeat 0.57 on CanParl\n\n## Constraints\n- x\n\n## Forbidden moves\n- y\n")
        probs = eamend.integrity_problems(store)
        check(any(p.startswith("AMENDMENT_DRIFT") for p in probs),
              f"a hand edit behind the ledger's back is caught: {probs}")
        rec2, _ = eamend.apply(eng, brief, None, "second correction after re-reading the leaderboard")
        check(rec2["id"] == "AM002" and rec2["old_digest"] == rec["new_digest"],
              "an in-place amendment chains from the last recorded version")
        check(eamend.integrity_problems(store) == [], "and the ledger is consistent again")
        history = eamend.history_lines(store, lane="L001")
        check(len(history) >= 3 and "AM002" in "\n".join(history), "reviewers get the history lines")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def idea_meta_amendments_respect_the_frozen_core() -> None:
    repo, store, eng = _fresh_engine("idea")
    try:
        meta = {"idea": "I001", "lane": "L002", "title": "first title",
                "effect_case": {"comparator_id": "N001", "chain": []},
                "predictions": [{"id": "P1", "metric": "auc", "comparison": ">=", "value": 0.9}],
                "mechanism_probe": {"mode": "same_run", "signal": "s" * 40, "expect": "e" * 20,
                                    "artifact": "results/p.json", "required_fields": ["gate"],
                                    "decision_rule": {"field": "gate", "aggregation": "mean",
                                                      "comparison": ">=", "threshold": 1.0}}}
        _write(repo, ".evo/ideas/I001.md", "# idea\n")
        _write_json(repo, ".evo/ideas/I001.meta.json", meta)
        seal = eseal.create(repo, [("idea", ".evo/ideas/I001.md"), ("idea_meta", ".evo/ideas/I001.meta.json")])
        lane = {"id": "L002", "round": "R001", "name": "beta", "status": "gate", "intent": "reform",
                "experiment_purpose": "diagnostic_probe", "search_origin": "repair", "parents": ["N001"],
                "min_level": 0, "idea": "I001", "idea_seal": seal, "cycles": {}}
        eng.st["lanes"].append(lane)
        frozen = json.loads(json.dumps(meta))
        frozen["program"] = {"objects": [], "operators": [{"id": "OP9"}]}
        _write_json(repo, "draft_frozen.json", frozen)
        exc = raises(lambda: eamend.apply(eng, ".evo/ideas/I001.meta.json", "draft_frozen.json",
                                          "trying to swap the program under an approved idea"),
                     SystemExit, "the identity of the idea is refused", contains="AMEND_FROZEN")
        check("different idea" in str(exc) and "retry-stage" in str(exc),
              "the refusal says it is a different idea and names the rewind door")
        check("program" not in json.loads((repo / ".evo/ideas/I001.meta.json").read_text()),
              "a refused amendment leaves the file untouched")
        # before production launches the bet itself is notebook: the effect
        # claim, the predictions and the probe rule are corrected on record
        ok_draft = json.loads(json.dumps(meta))
        ok_draft["title"] = "second title"
        ok_draft["effect_case"]["comparator_id"] = "N007"
        ok_draft["predictions"][0]["value"] = 0.91
        ok_draft["mechanism_probe"]["decision_rule"]["threshold"] = 0.98
        _write_json(repo, "draft_ok.json", ok_draft)
        rec, _ = eamend.apply(eng, ".evo/ideas/I001.meta.json", "draft_ok.json",
                              "the gate line was derived from an AP constant; corrected to the same-unit floor")
        check(rec["kind"] == "idea_meta" and any("threshold" in row for row in rec["changed"])
              and any("comparator_id" in row for row in rec["changed"]),
              f"a pre-launch correction of the bet is recorded with its changed paths: {rec['changed']}")
        amended = eamend.latest_digests(store)
        check(eseal.verify(repo, seal, label="idea", amended=amended) == [],
              "the seal audit accepts the amended working file")
        bad = eseal.verify(repo, seal, label="idea")
        check(any("SEALED_ARTIFACT_MUTATED" in e for e in bad),
              "without the ledger the same bytes would be a mutation")
        # once a node exists and production launched, the rule is history
        eng.g["nodes"].append({"id": "N002", "role": "variant", "status": "executing", "lane": "L002",
                               "parents": ["N001"], "spec": ".evo/nodes/N002/NODE_SPEC.json",
                               "experiment_purpose": "candidate"})
        lane["node"] = "N002"
        eng.st["runs"].append({"id": "RUN001", "node": "N002", "kind": "stage", "stage": "train",
                               "stage_index": 0, "status": "running"})
        late = json.loads(json.dumps(ok_draft))
        late["mechanism_probe"]["decision_rule"]["threshold"] = 0.5
        _write_json(repo, "draft_late.json", late)
        exc2 = raises(lambda: eamend.apply(eng, ".evo/ideas/I001.meta.json", "draft_late.json",
                                           "loosening the line after seeing the result"),
                      SystemExit, "after launch the decision rule is history", contains="correct-instrument")
        check("mechanism_probe" in str(exc2) and "post-hoc claim" in str(exc2),
              "the refusal names both doors: the formula channel and the post-hoc claim")
        moved = json.loads(json.dumps(ok_draft))
        moved["effect_case"]["comparator_id"] = "N001"
        _write_json(repo, "draft_moved.json", moved)
        raises(lambda: eamend.apply(eng, ".evo/ideas/I001.meta.json", "draft_moved.json",
                                    "moving the comparator once a node exists"),
               SystemExit, "the comparator frozen onto the node is refused", contains="different bet")
        # there is no spelling exception on frozen fields: a whitespace-only or
        # retyped change to the launched bet is refused like any other change
        spaced = json.loads(json.dumps(ok_draft))
        spaced["mechanism_probe"]["expect"] = ok_draft["mechanism_probe"]["expect"] + " "
        _write_json(repo, "draft_spaced.json", spaced)
        raises(lambda: eamend.apply(eng, ".evo/ideas/I001.meta.json", "draft_spaced.json",
                                    "trailing whitespace from the editor"),
               SystemExit, "a whitespace-only change to the launched bet is refused", contains="AMEND_FROZEN")
        retyped = json.loads(json.dumps(ok_draft))
        retyped["mechanism_probe"]["decision_rule"]["threshold"] = "0.98"
        _write_json(repo, "draft_retyped.json", retyped)
        raises(lambda: eamend.apply(eng, ".evo/ideas/I001.meta.json", "draft_retyped.json",
                                    "the JSON writer quoted the number"),
               SystemExit, "a number retyped as a string is refused after launch", contains="AMEND_FROZEN")
        late_ok = json.loads(json.dumps(ok_draft))
        late_ok["title"] = "third title"
        _write_json(repo, "draft_late_ok.json", late_ok)
        rec3, _ = eamend.apply(eng, ".evo/ideas/I001.meta.json", "draft_late_ok.json",
                               "the title misnamed the dataset the idea targets")
        check(rec3["phase"]["launched"] is True, "the record says the correction came after launch")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def spec_amendments_follow_launch_state() -> None:
    repo, store, eng = _fresh_engine("spec")
    try:
        spec_rel = ".evo/nodes/N002/NODE_SPEC.json"
        spec = {"role": "variant", "experiment_purpose": "candidate", "parents": ["N001"], "level": 3,
                "title": "node two", "cost_class": "medium",
                "smoke_plan": [{"name": "imports", "cmd": "python -c 1", "timeout_s": 60}],
                "workflow": {"stages": [
                    {"name": "train", "launch": "python train.py", "budget": {"limits": {"gpu_hours": 4.0}}},
                    {"name": "finalize", "launch": "python fin.py", "budget": {"limits": {"gpu_hours": 1.0}}}]},
                "eval": {"run": "python eval.py", "budget": {"limits": {"wallclock_minutes": 30}}}}
        _write_json(repo, spec_rel, spec)
        seal = eseal.create(repo, [("node_spec", spec_rel)])
        eng.g["nodes"].append({"id": "N002", "role": "variant", "status": "executing", "lane": "L009",
                               "parents": ["N001"], "spec": spec_rel, "spec_seal": seal,
                               "experiment_purpose": "candidate", "implementation_revision": 1})
        eng.st["runs"].append({"id": "RUN001", "node": "N002", "kind": "stage", "stage": "train",
                               "stage_index": 0, "status": "finished"})

        def draft(mutate, name):
            d = json.loads(json.dumps(spec))
            mutate(d)
            _write_json(repo, name, d)
            return name

        cap = draft(lambda d: d["workflow"]["stages"][0]["budget"]["limits"].__setitem__("gpu_hours", 5.3),
                    "d_cap.json")
        rec, _ = eamend.apply(eng, spec_rel, cap,
                              "the deterministic trajectory measured 4.05 gpu-h; worst case x1.3 = 5.3")
        check(any("gpu_hours" in row and "5.3" in row for row in rec["changed"]),
              f"a cap on a launched stage is notebook material: {rec['changed']}")
        spec = json.loads((repo / spec_rel).read_text())
        cmd = draft(lambda d: d["workflow"]["stages"][0].__setitem__("launch", "python train2.py"),
                    "d_cmd.json")
        raises(lambda: eamend.apply(eng, spec_rel, cmd, "changing a command that already ran"),
               SystemExit, "a launched stage's command is history", contains="already launched")
        later = draft(lambda d: d["workflow"]["stages"][1].__setitem__("launch", "python fin_fixed.py"),
                      "d_later.json")
        rec2, _ = eamend.apply(eng, spec_rel, later, "the finalize command pointed at the wrong script")
        check(any("finalize" in row or "stages[1]" in row for row in rec2["changed"]),
              "an unlaunched stage's command may still be corrected")
        spec = json.loads((repo / spec_rel).read_text())
        role = draft(lambda d: d.__setitem__("role", "root"), "d_role.json")
        raises(lambda: eamend.apply(eng, spec_rel, role, "trying to rewrite the contract role"),
               SystemExit, "the identity of the node is refused", contains="different idea")
        cost = draft(lambda d: d.__setitem__("cost_class", "heavy"), "d_cost.json")
        raises(lambda: eamend.apply(eng, spec_rel, cost, "re-pricing the node after it launched"),
               SystemExit, "a launched node's cost class is history", contains="post-hoc claim")
        spaced = draft(lambda d: d["workflow"]["stages"][0].__setitem__("launch", "python   train.py"),
                       "d_spaced.json")
        raises(lambda: eamend.apply(eng, spec_rel, spaced, "the launch line carried doubled spaces"),
               SystemExit, "a launched command is history even when only its spacing changes",
               contains="already launched")
        check(eseal.verify(repo, seal, label="spec", amended=eamend.latest_digests(store)) == [],
              "the spec seal tolerates the recorded corrections")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def contract_facts_are_notebook() -> None:
    repo, store, eng = _fresh_engine("facts")
    try:
        cfg = json.loads((repo / ".evo/config.json").read_text(encoding="utf-8"))
        raises(lambda: eamend.owner_of(store, eng.st, eng.g, ".evo/config.json"), SystemExit,
               "before the sign-off the config is an open configure output", contains="configure task")
        eng.st["config_frozen"] = True
        eng.st["bootstrap_contract_digest"] = econfig.bootstrap_contract_digest(cfg)
        owner = eamend.owner_of(store, eng.st, eng.g, ".evo/config.json")
        check(owner["kind"] == "contract_facts", "after the sign-off the world facts inside it are notebook")
        facts = json.loads(json.dumps(cfg))
        facts["evaluation_contract"]["noise_floors"] = {"C1": 0.004}
        eutil.write_json_atomic(repo / "facts_draft.json", facts)
        raises(lambda: eamend.apply(eng, ".evo/config.json", "facts_draft.json",
                                    "the field reports a seed spread of 0.004 on this benchmark"),
               SystemExit, "a floor without its provenance is refused", contains="noise_floor_sources")
        facts["evaluation_contract"]["noise_floor_sources"] = {"C1": "literature"}
        eutil.write_json_atomic(repo / "facts_draft.json", facts)
        rec, _ = eamend.apply(eng, ".evo/config.json", "facts_draft.json",
                              "the field reports a seed spread of 0.004 on this benchmark")
        check(rec["kind"] == "contract_facts" and any("noise_floors" in row for row in rec["changed"]),
              f"a noise floor is corrected on record: {rec['changed']}")
        check(econfig.bootstrap_contract_digest(json.loads((repo / ".evo/config.json").read_text(encoding="utf-8")))
              == eng.st["bootstrap_contract_digest"],
              "the signed contract digest does not move when a world fact is corrected")
        contract = json.loads(json.dumps(facts))
        contract["budgets"]["rounds_max"] = 99
        eutil.write_json_atomic(repo / "contract_draft.json", contract)
        raises(lambda: eamend.apply(eng, ".evo/config.json", "contract_draft.json",
                                    "trying to stretch the signed round budget through the notebook"),
               SystemExit, "the signed contract itself is refused", contains="reconfigure")
        check(econfig.smoke_must_contain({"must_contain": {"out.txt": ["ok", "done"]}})
              == econfig.smoke_must_contain({"must_contain": [{"file": "out.txt", "text": "ok"},
                                                                {"file": "out.txt", "text": "done"}]}),
              "both spellings of must_contain read the same")
        raises(lambda: econfig.smoke_must_contain({"must_contain": "ok"}), ValueError,
               "an unreadable must_contain is refused with the runner's words", contains="must_contain")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ------------------------------------------------------- instrument correction
def _concluded_probe_node(repo, eng, *, status="refuted"):
    meta = {"idea": "I002", "lane": "L003", "title": "dual clock", "experiment_purpose": "candidate",
            "novelty": {"kind": "irreducible"},
            "mechanism_probe": {"mode": "same_run", "signal": "s" * 40, "expect": "e" * 20,
                                "artifact": "results/p_s{seed}.json", "required_fields": ["gate"],
                                "extra_eval_arms": 0,
                                "decision_rule": {"field": "gate", "aggregation": "mean",
                                                  "comparison": ">=", "threshold": 1.0}}}
    _write(repo, ".evo/ideas/I002.md", "# idea\n")
    _write_json(repo, ".evo/ideas/I002.meta.json", meta)
    observations, snapshots = [], []
    for seed, (gate, auc, membership) in enumerate([(0.994, 0.9399, 0.9384), (0.995, 0.9410, 0.9380),
                                                     (0.9945, 0.9402, 0.9386)]):
        declared = f"results/p_s{seed}.json"
        snap = f".evo/runs/RUN010/evidence/p_s{seed}.json"
        _write_json(repo, snap, {"gate": gate, "auc_wiki": auc, "membership": membership})
        observations.append({"seed": seed, "artifact": declared, "values": {"gate": gate}})
        snapshots.append({"declared_artifact": declared, "snapshot_artifact": snap, "observation_index": seed})
    _write_json(repo, ".evo/nodes/N003/eval/metrics.json",
                {"auc": 0.97, "_mechanism_probe": {"mode": "same_run", "required_fields": ["gate"],
                                                    "observations": observations}})
    _write_json(repo, ".evo/nodes/N003/OUTCOME.json", {"node": "N003", "verdict": "improved",
                                                        "mechanism": {"status": status}})
    node = {"id": "N003", "role": "variant", "status": "concluded", "lane": "L003", "parents": ["N001"],
            "experiment_purpose": "candidate", "verdict": "improved", "mechanism_status": "deferred",
            "probe_result": {"status": status}, "scientific_promotion_status": "met",
            "effect_contract_status": "met", "idea_doc": ".evo/ideas/I002.md",
            "eval_metrics_path": ".evo/nodes/N003/eval/metrics.json",
            "outcome_path": ".evo/nodes/N003/OUTCOME.json", "kernel_ids": ["KC1"],
            "evaluation_summary": {"effect_contract": {"status": "met"},
                                   "mechanism_contract": {"status": status}},
            "evidence_heads": {"eval": "RUN010"}, "spec": ".evo/nodes/N003/NODE_SPEC.json"}
    eng.g["nodes"].append(node)
    eng.st["runs"].append({"id": "RUN010", "node": "N003", "kind": "eval", "status": "finished",
                           "adoption_status": "adopted", "evidence_status": "complete",
                           "probe_artifact_snapshots": snapshots})
    return node


def _proposal(node_id="N003", **override):
    rows = []
    for seed, (auc, membership) in enumerate([(0.9399, 0.9384), (0.9410, 0.9380), (0.9402, 0.9386)]):
        rows.append({"artifact": f"results/p_s{seed}.json", "seed": seed,
                     "inputs": {"auc_wiki": auc, "membership": membership},
                     "value": round(auc / membership, 6)})
    data = {"node": node_id,
            "argument": ("the gate divides an AUC read in this run by a constant that was derived from an AP "
                         "statistic in the scout: the two are different measures, so the ratio is a unit "
                         "conversion whatever its value; the same-instrument comparison uses the membership "
                         "AUC measured in the same run"),
            "original_rule": {"field": "gate", "aggregation": "mean", "comparison": ">=", "threshold": 1.0},
            "corrected_rule": {"field": "gate_same_unit", "aggregation": "mean", "comparison": ">=",
                               "threshold": 1.0},
            "formula": "auc_wiki / membership (both measured in this run)",
            "inputs": ["auc_wiki", "membership"], "observations": rows}
    data.update(override)
    return data


def instrument_correction_is_mechanical_then_judged() -> None:
    repo, store, eng = _fresh_engine("correction")
    try:
        node = _concluded_probe_node(repo, eng)
        ctx = eng.ctx()
        check(evalid.instrument_proposal_errors(ctx, node, _proposal()) == [],
              "a proposal grounded in the sealed artifacts is filable")
        bad = _proposal()
        bad["observations"][1]["inputs"]["auc_wiki"] = 0.99
        errs = evalid.instrument_proposal_errors(ctx, node, bad)
        check(any("INPUT_MISMATCH" in e for e in errs), f"an input that is not in the sealed bytes is refused: {errs}")
        errs = evalid.instrument_proposal_errors(
            ctx, node, _proposal(original_rule={"field": "gate", "aggregation": "mean",
                                                "comparison": ">=", "threshold": 0.9}))
        check(any("CORRECTION_ORIGINAL_RULE" in e for e in errs), "the frozen rule must be quoted exactly")
        errs = evalid.instrument_proposal_errors(ctx, node, _proposal(observations=_proposal()["observations"][:2]))
        check(any("CORRECTION_OBSERVATIONS" in e for e in errs), "every sealed observation gets a row")
        same = _proposal()
        for row, obs in zip(same["observations"], [0.994, 0.995, 0.9945]):
            row["value"] = obs
        same["corrected_rule"] = dict(same["original_rule"])
        errs = evalid.instrument_proposal_errors(ctx, node, same)
        check(any("CORRECTION_NO_CHANGE" in e for e in errs), "a proposal that changes nothing is not filable")
        unprobed = dict(node, id="N003")
        unprobed.pop("probe_result", None)
        errs = evalid.instrument_proposal_errors(ctx, unprobed, _proposal())
        check(any("CORRECTION_STATUS" in e and "evo ablate" in e for e in errs),
              "a node without a probe answer has nothing to correct; the causal question is settled by ablation")
        # the engine recomputes the verdict the corrected rule would give
        settled = evalid.settle_decision_rule(_proposal()["corrected_rule"],
                                              [r["value"] for r in _proposal()["observations"]])
        check(settled["status"] == "confirmed", f"same-unit values clear the line: {settled}")
        # review validation: sections, quotes, verdict vocabulary, isolation
        record = {"id": "IC001", "node": "N003", "status": "review_open",
                  "proposal_path": ".evo/nodes/N003/corrections/IC001.json",
                  "applicant_session": "sess-author",
                  "original": {"status": "refuted", "rule": _proposal()["original_rule"], "values": [0.994, 0.995, 0.9945]},
                  "corrected": {"status": "confirmed", "rule": _proposal()["corrected_rule"],
                                "values": [r["value"] for r in _proposal()["observations"]], "settlement": settled}}
        _write_json(repo, record["proposal_path"], _proposal())
        eng.st.setdefault("corrections", []).append(record)
        review_rel = ".evo/nodes/N003/corrections/IC001.review.md"
        arg = _proposal()["argument"]
        body = ("VERDICT: FORMULA_ERROR\n\n## Independence test\n" + "x" * 70 + "\n\n## Recomputation check\n"
                + "y" * 70 + "\n\n## Symmetry\n" + "z" * 70 + "\n\n## Verdict rationale\n" + "w" * 70
                + f"\n\nQUOTE: {arg[:60]}\nQUOTE: {arg[80:140]}\n")
        _write(repo, review_rel, body)
        task = {"id": "T0001", "type": "instrument_review", "subject": {"node": "N003", "correction": "IC001"},
                "outputs": [review_rel], "status": "open", "session": "sess-judge"}
        check(evalid.v_instrument_review(ctx, task) == [], "a complete ruling validates")
        eng.cfg.setdefault("policy", {})["critic_isolation"] = "strict"
        ctx2 = eng.ctx()
        same_session = dict(task, session="sess-author")
        errs = evalid.v_instrument_review(ctx2, same_session)
        check(any("CRITIC_SESSION_SAME" in e for e in errs), "under strict the applicant cannot be the judge")
        check(evalid.v_instrument_review(ctx2, task) == [], "a different session is independent")
        _write(repo, review_rel, body.replace("FORMULA_ERROR", "MAYBE"))
        errs = evalid.v_instrument_review(ctx2, task)
        check(any("CORRECTION_REVIEW_VERDICT" in e for e in errs), "the verdict vocabulary is closed")
        # applying re-settles the PROBE's answer from the same observations; the
        # causal status and the parenthood do not move
        eng._apply_instrument_correction(node, record, gate={"id": "G001"}, note="approved", actor="user")
        check(node["probe_result"]["status"] == "confirmed" and node["probe_result"]["corrected_by"] == "IC001"
              and node["mechanism_status"] == "deferred" and node["scientific_promotion_status"] == "met",
              f"the corrected rule re-settles the probe answer only: {node['probe_result']}, "
              f"{node['mechanism_status']}, {node['scientific_promotion_status']}")
        check(egraph.mechanism_label(node) == "deferred; probe used (corrected IC001)",
              f"the label shows the causal status and the corrected probe answer: {egraph.mechanism_label(node)}")
        check(node["mechanism_corrections"][0]["from"] == "refuted" and record["status"] == "applied",
              "the correction is recorded on the node and closed")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def queued_review_is_neither_stale_nor_lethal() -> None:
    repo, store, eng = _fresh_engine("queue")
    try:
        node = _concluded_probe_node(repo, eng)
        eng.st.setdefault("corrections", []).append(
            {"id": "IC001", "node": "N003", "status": "review_open", "proposal_path": "x"})
        task = {"id": "T0007", "type": "instrument_review", "subject": {"node": "N003", "correction": "IC001"},
                "outputs": [".evo/nodes/N003/corrections/IC001.review.md"], "status": "paused",
                "queued_after_hold": True, "held_by": [], "attempts": 0,
                "_render": {"extra_fields": {"NODE": "N003", "CORRECTION": "IC001", "PROPOSAL": "x",
                                             "ORIGINAL_STATUS": "refuted", "CORRECTED_STATUS": "confirmed"},
                            "inputs": [], "extra_blocks": []}}
        eng.st["tasks"].append(task)
        eng._reopen_queued_tasks()
        check(task["status"] == "open", f"a queued review of a CONCLUDED node reopens instead of being cancelled: {task['status']}")
        eng._abandon_task_subject(task, "attempts exhausted")
        check(node["status"] == "concluded" and eng.st["corrections"][0]["status"] == "closed_unreviewed",
              "giving up on the review closes the correction and never touches the node")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ------------------------------------------------------------------ doors ----
def doors_and_tables() -> None:
    conclude = "\n".join(ecards.doors_for("conclude"))
    check("evo ablate" in conclude and "correct-instrument" in conclude and "evo amend" in conclude,
          "the conclude card names the doors that matter after a conclusion")
    sketch = "\n".join(ecards.doors_for("sketch"))
    check("correct-instrument" not in sketch and "evo ablate" in sketch,
          "a sketch card carries the lane doors, not the post-settlement one")
    check(eflow.check_tables(cards_dir=ecards.CARDS_DIR, validators=evalid.VALIDATORS) == [],
          "the flow tables are total with the review task type and the correction gate")
    check(eflow.GATE_POLICY["instrument_correction"].protected
          and eflow.GATE_POLICY["instrument_correction"].auto == "never",
          "re-settling a verdict is a user decision in every autonomy mode")
    check(set(econfig.INJECTABLE_PURPOSES) == set(econfig.INSTRUMENTAL_PURPOSES)
          and "targeted_ablation" not in econfig.INJECTABLE_CAP_KEYS
          and "ablations_max_per_round" not in econfig.merged_default()["budgets"],
          "targeted ablation has a mid-round door and no per-round cap (one per win)")
    rendered = ecards.render("conclude", {**{k: "-" for k in (
        "TASK_ID", "NODE", "NODE_ROLE", "ATTEMPT", "MAX_ATTEMPTS", "BUNDLE_PATH", "OUTCOME_PATH",
        "RESULT_PATH", "OUTPUTS", "SUBMIT_CMD")}})
    check("## Doors open from here" in rendered and "## Stop discipline" in rendered,
          "every rendered task card carries the doors block before the stop discipline")


# ------------------------------------------------------------ config doors ----
def config_doors_share_one_ledger() -> None:
    """The two config doors write one ledger; a refusal never rewrites the
    file; the config's judged projection is the signed digest payload."""
    from types import SimpleNamespace
    import evo
    repo, store, eng = _fresh_engine("doors")
    try:
        cfg_rel = ".evo/config.json"
        cfg = json.loads((repo / cfg_rel).read_text(encoding="utf-8"))
        eng.st["config_frozen"] = True
        eng.st["bootstrap_contract_digest"] = econfig.bootstrap_contract_digest(cfg)
        eng.save()
        # display-only text is not part of the signed contract: recorded like any notebook line
        named = json.loads(json.dumps(cfg))
        named["project"]["name"] = "renamed project"
        eutil.write_json_atomic(repo / "d_name.json", named)
        rec, _ = eamend.apply(eng, cfg_rel, "d_name.json", "the project name misspelled the benchmark family")
        check(rec["kind"] == "contract_facts" and any("project.name" in row for row in rec["changed"]),
              f"a digest-neutral config edit is recorded as an ordinary correction: {rec['changed']}")
        check(econfig.bootstrap_contract_digest(json.loads((repo / cfg_rel).read_text(encoding="utf-8")))
              == eng.st["bootstrap_contract_digest"], "the signed digest did not move")
        cfg = named
        both = json.loads(json.dumps(cfg))
        both["project"]["name"] = "renamed again"
        both["budgets"]["rounds_max"] = 99
        eutil.write_json_atomic(repo / "d_both.json", both)
        exc = raises(lambda: eamend.apply(eng, cfg_rel, "d_both.json", "stretching the round budget next to a rename"),
                     SystemExit, "a contract change is still refused", contains="reconfigure")
        check("budgets.rounds_max" in str(exc) and "project.name" not in str(exc),
              f"the refusal names the signed path only; display text is not history: {exc}")
        sup = json.loads(json.dumps(cfg))
        sup["policy"]["autonomy"] = "auto"
        eutil.write_json_atomic(repo / "d_sup.json", sup)
        raises(lambda: eamend.apply(eng, cfg_rel, "d_sup.json", "trying to release gates through the notebook"),
               SystemExit, "policy.autonomy is switched with its own verb", contains="evo autonomy auto")
        tempo = json.loads(json.dumps(cfg))
        tempo["policy"]["preset"] = "custom"
        tempo["policy"].update(econfig.PRESETS["balanced"])   # a custom preset spells out every tempo key
        tempo["policy"]["max_exploit_share"] = 0.9
        eutil.write_json_atomic(repo / "d_tempo.json", tempo)
        rec_t, _ = eamend.apply(eng, cfg_rel, "d_tempo.json", "the user asked for a more exploitative tempo this month")
        check(not rec_t.get("typo") and any("max_exploit_share" in row for row in rec_t["changed"]),
              f"the preset word and its tempo keys are notebook facts: {rec_t['changed']}")
        eng.save()
        # evo autonomy appends to the same ledger (its validation is not under test here)
        real_validate, real_conflicts = econfig.validate_config, econfig.preset_conflicts
        econfig.validate_config, econfig.preset_conflicts = (lambda c: []), (lambda c: [])
        try:
            rc = evo.cmd_autonomy(store, SimpleNamespace(mode="auto", note="ordinary gates may auto-approve now"))
        finally:
            econfig.validate_config, econfig.preset_conflicts = real_validate, real_conflicts
        rows = eamend.read_all(store)
        check(rc == 0 and rows[-1]["kind"] == "contract_facts" and rows[-1]["actor"] == "user"
              and rows[-1]["changed"] == ["policy.autonomy: gated -> auto"],
              f"evo autonomy records its own amendment row: {rows[-1]}")
        check(eamend.integrity_problems(store) == []
              and eamend.latest_digests(store)[cfg_rel] == eseal.artifact_digest(repo, cfg_rel),
              "the ledger follows the blessed writer; doctor has nothing to report")
        eng = esched.Engine(store)   # the switch committed state
        # an in-place edit that touches a frozen path is refused without rewriting the file
        live = json.loads((repo / cfg_rel).read_text(encoding="utf-8"))
        live["budgets"]["rounds_max"] = 99
        live["evaluation_contract"]["noise_floors"] = {"C1": 0.003}
        live["evaluation_contract"]["noise_floor_sources"] = {"C1": "user"}
        eutil.write_json_atomic(repo / cfg_rel, live)
        exc_b = raises(lambda: eamend.apply(eng, cfg_rel, None, "an in-place edit that also stretches the budget"),
                       SystemExit, "the frozen path is refused", contains="AMEND_FROZEN")
        after = json.loads((repo / cfg_rel).read_text(encoding="utf-8"))
        check(after["budgets"]["rounds_max"] == 99 and after["policy"]["autonomy"] == "auto",
              "the file is left exactly as edited - nothing is rolled back to a snapshot")
        tail = str(exc_b).split("all changed paths", 1)
        check(len(tail) == 2 and "--from" in str(exc_b) and rows[-1]["new_snapshot"] in str(exc_b)
              and "policy.autonomy" not in tail[1].split("\n")[0],
              f"the refusal names the recorded bytes, the changed paths and the re-record exit: {exc_b}")
        check(len(eamend.read_all(store)) == len(rows), "a refusal records nothing")
        shutil.copyfile(repo / rows[-1]["new_snapshot"], repo / cfg_rel)
        check(eamend.integrity_problems(store) == [], "restoring the recorded bytes clears the drift")
        live = json.loads((repo / cfg_rel).read_text(encoding="utf-8"))
        live["evaluation_contract"]["noise_floors"] = {"C1": 0.003}
        live["evaluation_contract"]["noise_floor_sources"] = {"C1": "user"}
        eutil.write_json_atomic(repo / cfg_rel, live)
        rec_p, notes = eamend.apply(eng, cfg_rel, None, "the field measured a seed spread of 0.003 on C1")
        check(all("noise_floor" in row for row in rec_p["changed"]) and any("ruler" in n for n in notes),
              f"an in-place notebook edit after the switch diffs against the live bytes: {rec_p['changed']}")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def contract_facts_rerender_open_cards() -> None:
    """A config-fact correction rebuilds every open card's config-derived
    block from the corrected file and says which cards it re-rendered."""
    repo, store, eng = _fresh_engine("rerender")
    try:
        cfg_rel = ".evo/config.json"
        cfg = json.loads((repo / cfg_rel).read_text(encoding="utf-8"))
        cfg["evaluation_contract"]["cells"] = [{"id": "C1", "role": "target", "metric": "auc",
                                                "result_key": "auc", "dataset": "wiki"}]
        cfg["evaluation_contract"]["noise_floors"] = {"C1": 0.02}
        cfg["evaluation_contract"]["noise_floor_sources"] = {"C1": "literature"}
        eutil.write_json_atomic(repo / cfg_rel, cfg)
        eng.cfg = store.load_config()
        eng.st["config_frozen"] = True
        eng.st["bootstrap_contract_digest"] = econfig.bootstrap_contract_digest(cfg)
        _concluded_probe_node(repo, eng)
        eng.st.setdefault("corrections", []).append(
            {"id": "IC001", "node": "N003", "status": "review_open", "proposal_path": "x"})
        task = {"id": "T0009", "type": "instrument_review", "subject": {"node": "N003", "correction": "IC001"},
                "outputs": [".evo/nodes/N003/corrections/IC001.review.md"], "status": "open", "attempts": 0,
                "_render": {"extra_fields": {"NODE": "N003", "CORRECTION": "IC001", "PROPOSAL": "x",
                                             "ORIGINAL_STATUS": "refuted", "CORRECTED_STATUS": "confirmed",
                                             "POLICY_NOTES": "- TRAINING-SEED POLICY: record_only\n"
                                                             "- ABLATION POLICY: budget multiple 2. stale text"},
                            "inputs": [],
                            "extra_blocks": [["Noise floors on the target cells (advisory: what a rule can resolve)",
                                              ["- C1: floor 0.02 (config). stale advice"]]]}}
        eng.st["tasks"].append(task)
        eng._rematerialize(task)
        check("floor 0.02" in eutil.read_text(repo / task["bundle"]), "the open card carries the floor it was minted with")
        facts = json.loads(json.dumps(cfg))
        facts["evaluation_contract"]["noise_floors"] = {"C1": 0.004}
        facts.setdefault("evidence_policy", {}).setdefault("ablation", {})["budget_multiple"] = 3.0
        eutil.write_json_atomic(repo / "facts_draft.json", facts)
        _rec, notes = eamend.apply(eng, cfg_rel, "facts_draft.json",
                                   "the field reports a seed spread of 0.004 on this benchmark")
        check(any(n.startswith("open cards re-rendered") and "T0009" in n for n in notes),
              f"the amendment reports what it re-rendered: {notes}")
        bundle = eutil.read_text(repo / task["bundle"])
        check("floor 0.004" in bundle and "floor 0.02" not in bundle,
              "the noise block is rebuilt from the corrected config, not replayed")
        check(econfig.noise_floor(eng.cfg, "C1") == 0.004, "the engine's own config was reloaded inside apply")
        policy = task["_render"]["extra_fields"]["POLICY_NOTES"]
        check("budget multiple 3" in policy and "budget multiple 2" not in policy
              and policy.startswith("- TRAINING-SEED POLICY: record_only"),
              f"the stored ABLATION POLICY line follows the corrected multiple, other notes untouched: {policy}")
        check(task.get("presented_at") is None, "the re-rendered card is presented in full again")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def node_copies_follow_the_notebook() -> None:
    """Pre-launch corrections keep the node and its spec in step with the
    idea meta: ablation sizing rewrites the replication block, cost_class
    re-derives the fidelity duty, the node's plain copies follow, and the
    spec's engine-owned copies point at the meta."""
    repo, store, eng = _fresh_engine("copies")
    try:
        abl_meta = {"idea": "I010", "lane": "L010", "experiment_purpose": "targeted_ablation",
                    "ablation": {"parent": "N001", "costly_runs": 1, "settles_parent_mechanism": True,
                                 "question": "does the gate carry the win"}}
        _write(repo, ".evo/ideas/I010.md", "# ablation\n")
        _write_json(repo, ".evo/ideas/I010.meta.json", abl_meta)
        seal = eseal.create(repo, [("idea", ".evo/ideas/I010.md"), ("idea_meta", ".evo/ideas/I010.meta.json")])
        eng.st["lanes"].append({"id": "L010", "round": "R001", "name": "abl", "status": "node_created",
                                "intent": "reform", "experiment_purpose": "targeted_ablation",
                                "search_origin": "constructive", "parents": ["N001"], "min_level": 0,
                                "idea": "I010", "idea_seal": seal, "node": "N010", "cycles": {}})
        spec_rel = ".evo/nodes/N010/NODE_SPEC.json"
        spec = {"role": "variant", "experiment_purpose": "targeted_ablation", "experiment_class": "train",
                "parents": ["N001"], "level": 0, "title": "gate ablation", "cost_class": "light",
                "ablation": json.loads(json.dumps(abl_meta["ablation"])),
                "training_replication": {"mode": "single", "runs": 1, "seeds": [0], "aggregation": "none",
                                         "source": "workflow"},
                "evidence_plan": {"extra_eval_arms": 0, "declared_checks": []},
                "workflow": {"stages": [{"name": "train", "launch": "python train.py --seed {seed}",
                                         "metrics_file": "out/{seed}/m.json",
                                         "budget": {"limits": {"gpu_hours": 1.0}}}]},
                "eval": {"run": "python eval.py", "budget": {"limits": {"wallclock_minutes": 10}}}}
        _write_json(repo, spec_rel, spec)
        eng.g["nodes"].append({"id": "N010", "role": "variant", "status": "approved", "lane": "L010",
                               "parents": ["N001"], "spec": spec_rel, "experiment_purpose": "targeted_ablation",
                               "idea_doc": ".evo/ideas/I010.md", "implementation_revision": 0})
        up = json.loads(json.dumps(abl_meta))
        up["ablation"]["costly_runs"] = 3
        _write_json(repo, "d_runs3.json", up)
        _rec, notes = eamend.apply(eng, ".evo/ideas/I010.meta.json", "d_runs3.json",
                                   "the parent's win on C1 is 1.4 floors wide: three paired runs settle it")
        rep = json.loads((repo / spec_rel).read_text(encoding="utf-8"))["training_replication"]
        check(rep == {"mode": "preplanned", "runs": 3, "seeds": [0, 1, 2], "aggregation": "mean", "source": "workflow"},
              f"costly_runs 1 -> 3 rewrites the whole replication block: {rep}")
        check(any("propagated into" in n for n in notes), "the spec copy is recorded as an engine propagation")
        down = json.loads(json.dumps(up))
        down["ablation"]["costly_runs"] = 1
        _write_json(repo, "d_runs1.json", down)
        eamend.apply(eng, ".evo/ideas/I010.meta.json", "d_runs1.json",
                     "the parent's pipeline is deterministic after all: one run settles it")
        rep = json.loads((repo / spec_rel).read_text(encoding="utf-8"))["training_replication"]
        check(rep["mode"] == "single" and rep["runs"] == 1 and rep["seeds"] == [0],
              f"costly_runs 3 -> 1 shrinks the block back: {rep}")
        live_spec = json.loads((repo / spec_rel).read_text(encoding="utf-8"))
        live_spec["training_replication"]["seeds"] = ["alpha"]
        eutil.write_json_atomic(repo / spec_rel, live_spec)
        two = json.loads(json.dumps(down))
        two["ablation"]["costly_runs"] = 2
        _write_json(repo, "d_runs2.json", two)
        rows_before = len(eamend.read_all(store))
        exc = raises(lambda: eamend.apply(eng, ".evo/ideas/I010.meta.json", "d_runs2.json",
                                          "two paired runs would settle the smaller win"),
                     SystemExit, "a design the spec cannot realize is refused", contains="AMEND_SPEC_INVALID")
        check("SEED_COUNT" in str(exc) and spec_rel in str(exc) and len(eamend.read_all(store)) == rows_before
              and json.loads((repo / ".evo/ideas/I010.meta.json").read_text(encoding="utf-8"))["ablation"]["costly_runs"] == 1,
              f"the refusal names the spec field and has no side effects: {exc}")
        d = json.loads(json.dumps(live_spec))
        d["ablation"]["costly_runs"] = 2
        _write_json(repo, "d_spec_abl.json", d)
        exc_f = raises(lambda: eamend.apply(eng, spec_rel, "d_spec_abl.json", "editing the ablation design on the spec directly"),
                       SystemExit, "an engine-owned copy is refused on the spec", contains="AMEND_FROZEN")
        check(".evo/ideas/I010.meta.json" in str(exc_f) and "propagates" in str(exc_f),
              f"the refusal names the meta as the exit: {exc_f}")
        # cost_class before launch re-derives the fidelity duty
        _write(repo, ".evo/ideas/I020.md", "# idea\n")
        _write_json(repo, ".evo/ideas/I020.meta.json", {"idea": "I020", "lane": "L020", "experiment_purpose": "candidate",
                                                         "novelty": {"kind": "composition"}})
        cand_rel = ".evo/nodes/N020/NODE_SPEC.json"
        cand = {"role": "variant", "experiment_purpose": "candidate", "parents": ["N001"], "level": 2,
                "title": "candidate node", "cost_class": "light",
                "workflow": {"stages": [{"name": "train", "launch": "python train.py",
                                         "budget": {"limits": {"gpu_hours": 1.0}}}]},
                "eval": {"run": "python eval.py", "budget": {"limits": {"wallclock_minutes": 10}}}}
        _write_json(repo, cand_rel, cand)
        node20 = {"id": "N020", "role": "variant", "status": "building", "lane": "L020", "parents": ["N001"],
                  "spec": cand_rel, "experiment_purpose": "candidate", "idea_doc": ".evo/ideas/I020.md",
                  "implementation_revision": 0, "needs_fidelity": False, "fidelity_pending": False}
        eng.g["nodes"].append(node20)
        heavy = json.loads(json.dumps(cand))
        heavy["cost_class"] = "heavy"
        _write_json(repo, "d_heavy.json", heavy)
        rec_g, notes_g = eamend.apply(eng, cand_rel, "d_heavy.json",
                                      "the worst-case trajectory is 40 gpu-hours: this is a heavy workflow")
        check(node20["needs_fidelity"] is True and node20["fidelity_pending"] is True
              and rec_g.get("node_refresh") == ["needs_fidelity: false -> true", "fidelity_pending: false -> true"],
              f"cost_class light -> heavy re-derives the fidelity duty on record: {rec_g.get('node_refresh')}")
        check(any("fidelity audit" in n for n in notes_g), f"the note says the audit is now owed: {notes_g}")
        # the agent's cost estimate is its own notebook number: the rehearsal teaches a better one
        est = json.loads(json.dumps(heavy))
        est["cost_estimate"] = {"per_unit": {"gpu_hours": 0.8},
                                "basis": "rehearsal pace 240 steps/min over the 20k-step schedule on 1 device"}
        _write_json(repo, "d_est.json", est)
        rec_e, _ = eamend.apply(eng, cand_rel, "d_est.json", "the rehearsal measured the real pace")
        check(rec_e.get("kind") == "node_spec"
              and json.loads((repo / cand_rel).read_text(encoding="utf-8"))["cost_estimate"]["per_unit"] == {"gpu_hours": 0.8},
              "cost_estimate is amendable before launch (the workflow gate reads the current number)")
        heavy = est
        # what a node did about a refuted kernel is read by the fidelity audit: notebook until launch, then history
        disp = json.loads(json.dumps(heavy))
        disp["refuted_kernel_disposition"] = [{"parent": "N001", "action": "removed",
                                               "note": "the gate kernel is not in this build at all"}]
        _write_json(repo, "d_disp.json", disp)
        eamend.apply(eng, cand_rel, "d_disp.json", "declaring the disposition the plan forgot")
        heavy = disp
        eng.st.setdefault("runs", []).append({"id": "RUN020", "node": "N020", "kind": "stage", "stage": "train",
                                              "stage_index": 0, "status": "running"})
        disp2 = json.loads(json.dumps(disp))
        disp2["refuted_kernel_disposition"][0]["action"] = "reclaimed"
        _write_json(repo, "d_disp2.json", disp2)
        exc_d = raises(lambda: eamend.apply(eng, cand_rel, "d_disp2.json", "changing the story after launch"),
                       SystemExit, "the disposition is frozen once the node launched", contains="AMEND_FROZEN")
        check("refuted_kernel_disposition" in str(exc_d), f"the refusal names the field: {exc_d}")
        eng.st["runs"] = [r for r in eng.st["runs"] if r.get("id") != "RUN020"]
        scoped = json.loads(json.dumps(heavy))
        scoped["evaluation_scope"] = {"cells": ["C1"]}
        _write_json(repo, "d_scope.json", scoped)
        exc_s = raises(lambda: eamend.apply(eng, cand_rel, "d_scope.json", "narrowing the scope on the spec directly"),
                       SystemExit, "an engine-owned copy is refused on the spec", contains="AMEND_FROZEN")
        check(".evo/ideas/I020.meta.json" in str(exc_s), f"the refusal names this node's meta: {exc_s}")
        # idea-meta fields the node copies stay amendable until launch; the copies follow
        meta30 = {"idea": "I030", "lane": "L030", "title": "probe idea", "sota_targets": [],
                  "metric_bridge_needed": False, "external_interface_changed": False,
                  "mechanism_probe": {"mode": "same_run", "signal": "s" * 40, "expect": "e" * 20,
                                      "artifact": "results/p.json", "required_fields": ["gate"], "extra_eval_arms": 0,
                                      "decision_rule": {"field": "gate", "aggregation": "mean",
                                                        "comparison": ">=", "threshold": 1.0}}}
        _write(repo, ".evo/ideas/I030.md", "# idea\n")
        _write_json(repo, ".evo/ideas/I030.meta.json", meta30)
        seal30 = eseal.create(repo, [("idea", ".evo/ideas/I030.md"), ("idea_meta", ".evo/ideas/I030.meta.json")])
        eng.st["lanes"].append({"id": "L030", "round": "R001", "name": "gamma", "status": "node_created",
                                "intent": "reform", "experiment_purpose": "diagnostic_probe",
                                "search_origin": "repair", "parents": ["N001"], "min_level": 0,
                                "idea": "I030", "idea_seal": seal30, "node": "N030", "cycles": {}})
        spec30_rel = ".evo/nodes/N030/NODE_SPEC.json"
        spec30 = {"role": "variant", "experiment_purpose": "diagnostic_probe", "parents": ["N001"], "level": 0,
                  "title": "probe node", "cost_class": "light",
                  "probe_execution": {"mode": "same_run", "signal": "s" * 40, "expect": "e" * 20,
                                      "artifact": "results/p.json", "required_fields": ["gate"],
                                      "decision_rule": meta30["mechanism_probe"]["decision_rule"]},
                  "evidence_plan": {"extra_eval_arms": 0, "declared_checks": ["mechanism_probe"]},
                  "workflow": {"stages": [{"name": "train", "launch": "python train.py",
                                           "budget": {"limits": {"gpu_hours": 1.0}}}]},
                  "eval": {"run": "python eval.py", "budget": {"limits": {"wallclock_minutes": 10}}}}
        _write_json(repo, spec30_rel, spec30)
        node30 = {"id": "N030", "role": "variant", "status": "approved", "lane": "L030", "parents": ["N001"],
                  "spec": spec30_rel, "experiment_purpose": "diagnostic_probe", "idea_doc": ".evo/ideas/I030.md",
                  "implementation_revision": 0, "needs_metric_bridge": False}
        eng.g["nodes"].append(node30)
        eutil.append_jsonl(repo / ".evo/evidence/SOTA.jsonl", {"id": "S001", "headline": {"value": 0.91}})
        m1 = json.loads(json.dumps(meta30))
        m1["sota_targets"] = [{"sota": "S001", "cell": "C1", "dimension": "effect", "claim": "c" * 60}]
        m1["metric_bridge_needed"] = True
        _write_json(repo, "d_meta30a.json", m1)
        rec_h, _ = eamend.apply(eng, ".evo/ideas/I030.meta.json", "d_meta30a.json",
                                "the scout found the published line this idea beats and a bridge metric it needs")
        check(node30.get("sota_targets_frozen") == {"S001": 0.91} and node30.get("needs_metric_bridge") is True,
              f"the node's copies follow a pre-launch correction: {node30.get('sota_targets_frozen')}")
        check(any("sota_targets_frozen" in r for r in (rec_h.get("node_refresh") or [])),
              f"the refresh is on the record: {rec_h.get('node_refresh')}")
        m2 = json.loads(json.dumps(m1))
        m2["mechanism_probe"]["artifact"] = "results/probe.json"
        m2["mechanism_probe"]["extra_eval_arms"] = 1
        _write_json(repo, "d_meta30b.json", m2)
        eamend.apply(eng, ".evo/ideas/I030.meta.json", "d_meta30b.json",
                     "the artifact path and the extra evaluation arm were wired before any build")
        live30 = json.loads((repo / spec30_rel).read_text(encoding="utf-8"))
        check(live30["probe_execution"]["artifact"] == "results/probe.json"
              and live30["evidence_plan"]["extra_eval_arms"] == 1,
              f"probe wiring follows into the spec while no build exists: {live30['evidence_plan']}")
        node30["implementation_revision"] = 1
        m3 = json.loads(json.dumps(m2))
        m3["mechanism_probe"]["artifact"] = "results/other.json"
        _write_json(repo, "d_meta30c.json", m3)
        exc_h = raises(lambda: eamend.apply(eng, ".evo/ideas/I030.meta.json", "d_meta30c.json",
                                            "moving the artifact after the build realized it"),
                       SystemExit, "wiring a build realizes is frozen", contains="AMEND_FROZEN")
        check("propose-abandon --node N030" in str(exc_h), f"the refusal names a door that exists once the node does: {exc_h}")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def history_folds_prelaunch_and_shows_project_facts() -> None:
    repo, store, _eng = _fresh_engine("history")
    try:
        ledger = repo / eamend.AMENDMENTS_REL
        base = {"path": ".evo/nodes/N001/NODE_SPEC.json", "kind": "node_spec", "lane": "L001", "node": "N001",
                "idea": None, "old_digest": "a", "old_snapshot": "s", "new_digest": "b", "new_snapshot": "t",
                "changed": ["x: 1 -> 2"], "reason": "r" * 20}
        for i in range(1, 13):
            eutil.append_jsonl(ledger, {**base, "id": f"AM{i:03d}", "at": f"2026-09-01T00:{i:02d}:00Z", "actor": "agent",
                                        "phase": {"lane_status": "node_created", "node_status": "approved",
                                                  "launched": False}})
        eutil.append_jsonl(ledger, {**base, "id": "AM013", "at": "2026-09-03T00:00:00Z", "actor": "agent",
                                    "changed": ["workflow.stages[1].budget.limits.gpu_hours: 4 -> 5.3"],
                                    "phase": {"lane_status": "executing", "node_status": "executing", "launched": True}})
        eutil.append_jsonl(ledger, {"id": "AM014", "at": "2026-09-04T00:00:00Z", "actor": "user", "path": ".evo/config.json",
                                    "kind": "contract_facts", "lane": None, "node": None, "idea": None,
                                    "old_digest": "c", "old_snapshot": "u", "new_digest": "d", "new_snapshot": "v",
                                    "changed": ["evaluation_contract.noise_floors.C1: 0.02 -> 0.004"],
                                    "reason": "the field reports 0.004",
                                    "phase": {"lane_status": None, "node_status": None, "launched": False}})
        lines = eamend.history_lines(store, node="N001", lane="L001", limit=10)
        text = "\n".join(lines)
        check("12 correction(s) before production launch" in text and "AM001, AM002" in text and "+4 more" in text,
              f"pre-launch rows fold into one count line that keeps their ids: {text}")
        check(sum(1 for line in lines if line.startswith("- AM0")) == 1 and "AM013" in text
              and "after production launch" in text, "the post-launch row is itemized whatever its position")
        check("AM014" not in text and "suspicious" in text,
              "project rows stay out of a subject's history unless asked; the header says when to open snapshots")
        proj = eamend.history_lines(store, project=True)
        check(proj and proj[0].startswith("- forward-only") and "[project fact]" in "\n".join(proj)
              and "production launch" not in "\n".join(proj),
              f"project rows carry no subject header and print 'project fact': {proj}")
        both = eamend.history_lines(store, node="N001", project=True)
        check(eamend.PROJECT_FACTS_HEADING in both and "AM014" in "\n".join(both),
              "with a subject the project rows sit under their own heading")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def main() -> None:
    brief_amendments_keep_history()
    idea_meta_amendments_respect_the_frozen_core()
    spec_amendments_follow_launch_state()
    contract_facts_are_notebook()
    config_doors_share_one_ledger()
    contract_facts_rerender_open_cards()
    node_copies_follow_the_notebook()
    history_folds_prelaunch_and_shows_project_facts()
    instrument_correction_is_mechanical_then_judged()
    queued_review_is_neither_stale_nor_lethal()
    doors_and_tables()
    done("NOTEBOOK / SETTLEMENT UNIT")


if __name__ == "__main__":
    main()
