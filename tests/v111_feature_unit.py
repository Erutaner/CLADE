"""v11.1 feature contracts at unit speed.

    python tests/v111_feature_unit.py

Covers the v11.1 additions: unchanged-block bundle references (T2), winner
file inputs (T3), ledger slices (T4), the scaling follow-up door (P2),
observed-noise self-calibration (P3), the pre-registered repeat_measure
trigger/door/aggregation (P4), the exploratory purpose tier (P5), and the
workflow-side fidelity provenance lines (P6).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))

import eabsorb    # noqa: E402
import ebundle    # noqa: E402
import econfig    # noqa: E402
import eflow      # noqa: E402
import egraph     # noqa: E402
import eprogram   # noqa: E402
import etask      # noqa: E402
import eutil      # noqa: E402
import evalid     # noqa: E402
from _check import check, done  # noqa: E402


# ---------------------------------------------------------------- P3 ------
def observed_noise_floor():
    cfg = econfig.merged_default()
    cfg["evaluation_contract"]["noise_floors"] = {"C1": 0.02}
    st2 = {"observed_noise": {"C1": {"width": 0.008, "sets": 2}}}
    st1 = {"observed_noise": {"C1": {"width": 0.008, "sets": 1}}}
    check(econfig.noise_floor(cfg, "C1") == 0.02, "no st -> config floor (v11 behavior)")
    check(econfig.noise_floor(cfg, "C1", st1) == 0.02,
          "one observed set is not yet evidence - config floor stays")
    check(econfig.noise_floor(cfg, "C1", st2) == 0.008,
          "two observed sets outrank the literature guess")
    check(econfig.noise_floor(cfg, "C2", st2) == 0.0, "unknown cell stays 0")
    check(econfig.noise_floor_source(cfg, "C1", st2) == "observed", "source: observed")
    check(econfig.noise_floor_source(cfg, "C1", st1) == "config", "source: config")
    check(econfig.noise_floor_source(cfg, "C2", st2) == "none", "source: none")
    bad = {"observed_noise": {"C1": {"width": -1.0, "sets": 5}}}
    check(econfig.noise_floor(cfg, "C1", bad) == 0.02, "corrupt observed width falls back to config")


def observed_noise_calibration_writer():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        cfg = econfig.merged_default()
        cfg["evaluation_contract"]["cells"] = [
            {"id": "C1", "result_key": "auc", "role": "target", "required": True,
             "weight": 1.0, "goal_threshold": None}]
        cfg["metrics"] = [{"key": "auc", "direction": "max"}]
        events = []
        spec = {"training_replication": {"mode": "preplanned", "runs": 2,
                                         "aggregation": "mean", "seeds": [1, 2]}}
        (repo / ".evo/nodes/N1/eval").mkdir(parents=True)
        (repo / ".evo/nodes/N1/eval/raw.json").write_text(json.dumps({
            "auc": {"value": 0.805, "training_replication": {
                "aggregation": "mean",
                "runs": [{"seed": 1, "value": 0.80, "source": "run-a artifact"},
                         {"seed": 2, "value": 0.81, "source": "run-b artifact"}]}}}),
            encoding="utf-8")
        self = SimpleNamespace(
            st={}, cfg=cfg,
            store=SimpleNamespace(repo=repo, event=lambda *a, **k: events.append(k)),
            _spec=lambda node: spec)
        node = {"id": "N1"}
        run = {"id": "R1", "metrics_file": ".evo/nodes/N1/eval/raw.json"}
        eabsorb.AbsorbMixin._calibrate_observed_noise(self, node, run)
        rec = self.st["observed_noise"]["C1"]
        check(abs(rec["width"] - 0.01) < 1e-9 and rec["sets"] == 1,
              f"one seed set -> width=max-min=0.01, sets=1: {rec}")
        # R7: contributions key on the TRAINING SET (node + seed set), not the
        # eval RUN id - an evaluation-only recovery re-measures the SAME
        # trained seeds under a fresh RUN id and must REPLACE, never add.
        eabsorb.AbsorbMixin._calibrate_observed_noise(
            self, node, {"id": "R2", "metrics_file": ".evo/nodes/N1/eval/raw.json"})
        rec = self.st["observed_noise"]["C1"]
        check(rec["sets"] == 1 and abs(rec["width"] - 0.01) < 1e-9,
              f"a re-evaluation of the same trained seed set replaces in place: {rec}")
        # a genuinely DISTINCT training set (another node) accumulates
        eabsorb.AbsorbMixin._calibrate_observed_noise(
            self, {"id": "N2"}, {"id": "R2b", "metrics_file": ".evo/nodes/N1/eval/raw.json"})
        rec = self.st["observed_noise"]["C1"]
        check(rec["sets"] == 2 and abs(rec["width"] - 0.01) < 1e-9,
              f"a second DISTINCT training set accumulates and the median publishes: {rec}")
        check(econfig.noise_floor(cfg, "C1", self.st) == rec["width"],
              "noise_floor() now serves the observed value")
        # replaying the SAME eval run (crash recovery) must not double-count
        eabsorb.AbsorbMixin._calibrate_observed_noise(self, node, run)
        check(self.st["observed_noise"]["C1"]["sets"] == 2,
              "a recovery replay of one run overwrites its own entry - never double-counts")
        (repo / ".evo/nodes/N1/eval/raw3.json").write_text(json.dumps({
            "auc": {"value": 0.775, "training_replication": {
                "aggregation": "mean",
                "runs": [{"seed": 1, "value": 0.75, "source": "run-a artifact"},
                         {"seed": 2, "value": 0.80, "source": "run-b artifact"}]}}}),
            encoding="utf-8")
        eabsorb.AbsorbMixin._calibrate_observed_noise(
            self, {"id": "N3"}, {"id": "R3", "metrics_file": ".evo/nodes/N1/eval/raw3.json"})
        rec = self.st["observed_noise"]["C1"]
        check(abs(rec["width"] - 0.01) < 1e-9 and rec["sets"] == 3,
              f"widths [0.01, 0.01, 0.05] -> the MEDIAN (0.01) publishes, not the mean "
              f"(0.023) or the newest (0.05): {rec}")
    # final-audit guard greps: exploratory meta bans + carbon exemptions
    vsrc = open(HERE.parent / "engine" / "evalid.py", encoding="utf-8").read()
    for anchor in ("IDEA_EXPLORATORY_", "PROGRAM_CONFIRMATORY_TARGET_META",
                   'not lane.get("scaling_followup_of")'):
        check(anchor in vsrc, f"final-audit guard present: {anchor}")
        # single-run mode never calibrates
        self2 = SimpleNamespace(st={}, cfg=cfg, store=self.store,
                                _spec=lambda node: {"training_replication": {"mode": "single"}})
        eabsorb.AbsorbMixin._calibrate_observed_noise(self2, node, run)
        check("observed_noise" not in self2.st, "single mode writes no observed noise")


# ---------------------------------------------------------------- P4 ------
def _p4_fixture(td: str, *, band=None, value=0.812, mode="single", floors=None,
                meta_extra=None, gates=None, min_improvement=0.03):
    repo = Path(td)
    cfg = econfig.merged_default()
    cfg["evaluation_contract"]["cells"] = [
        {"id": "C1", "result_key": "auc", "role": "target", "required": True,
         "weight": 1.0, "goal_threshold": None, "min_improvement": min_improvement}]
    cfg["metrics"] = [{"key": "auc", "direction": "max"}]
    if floors:
        cfg["evaluation_contract"]["noise_floors"] = floors
    events, new_gates = [], []
    rr = {"cell": "C1", "when": "decision_within_band", "max_repeats": 1}
    if band is not None:
        rr["band"] = band
    meta = {"repeat_rule": rr}
    meta.update(meta_extra or {})
    (repo / ".evo/ideas").mkdir(parents=True)
    (repo / ".evo/ideas/I1.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (repo / ".evo/nodes/N2/eval").mkdir(parents=True)
    (repo / ".evo/nodes/N2/eval/raw.json").write_text(
        json.dumps({"auc": value}), encoding="utf-8")
    parent = {"id": "N1", "role": "variant", "status": "concluded",
              "scores": {"auc": {"value": 0.80}}}
    node = {"id": "N2", "parents": ["N1"], "idea_doc": ".evo/ideas/I1.md",
            "eval_floor_frozen": {"C1": econfig.noise_floor(cfg, "C1")}}
    self = SimpleNamespace(
        st={"gates": list(gates or [])}, cfg=cfg, g={"nodes": [parent, node]},
        store=SimpleNamespace(
            repo=repo, event=lambda *a, **k: events.append(k),
            new_gate=lambda st, kind, subject, msg: (
                new_gates.append({"kind": kind, "subject": subject, "msg": msg}) or new_gates[-1])),
        _spec=lambda n: {"training_replication": {"mode": mode}})
    run = {"id": "R9", "metrics_file": ".evo/nodes/N2/eval/raw.json"}
    return self, node, run, new_gates


def repeat_measure_trigger():
    # delta=0.012 vs band 0.02 around 0 -> fires; also within band of margin 0.03
    with tempfile.TemporaryDirectory() as td:
        self, node, run, gates = _p4_fixture(td, band=0.02)
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(len(gates) == 1 and gates[0]["kind"] == "repeat_measure",
              f"on-the-line single delta opens the offer gate: {gates}")
        subj = gates[0]["subject"]
        check(subj["cell"] == "C1" and abs(subj["delta"] - 0.012) < 1e-9
              and subj["band"] == 0.02, f"payload carries cell/delta/band: {subj}")
        check(any("0 (parity" in ln for ln in subj["lines"])
              and any("min_improvement" in ln for ln in subj["lines"]),
              f"both nearby decision lines are named: {subj['lines']}")
        check("EXACTLY ONE" in gates[0]["msg"], "card text promises exactly one repeat")
    # clear win far from every line -> silent
    with tempfile.TemporaryDirectory() as td:
        self, node, run, gates = _p4_fixture(td, band=0.02, value=0.90)
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(gates == [], "a clear result triggers nothing")
    # band priority: explicit band absent -> frozen floor is the band
    with tempfile.TemporaryDirectory() as td:
        self, node, run, gates = _p4_fixture(td, floors={"C1": 0.02})
        node["eval_floor_frozen"] = {"C1": 0.02}
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(len(gates) == 1 and "frozen" in gates[0]["subject"]["band_source"],
              f"floor frozen before eval serves as the band: {gates and gates[0]['subject']}")
    # neither band nor floor -> dormant
    with tempfile.TemporaryDirectory() as td:
        self, node, run, gates = _p4_fixture(td)
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(gates == [], "no band + no floor = mechanism dormant")
    # preplanned mode -> never fires (mutually exclusive tiers)
    with tempfile.TemporaryDirectory() as td:
        self, node, run, gates = _p4_fixture(td, band=0.02, mode="preplanned")
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(gates == [], "preplanned tier never uses repeat_measure")
    # done / already-decided guards
    with tempfile.TemporaryDirectory() as td:
        self, node, run, gates = _p4_fixture(td, band=0.02)
        node["repeat_measure_done"] = True
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(gates == [], "a settled (or rejected) node never re-triggers")
    with tempfile.TemporaryDirectory() as td:
        prior = {"kind": "repeat_measure", "status": "rejected", "subject": {"node": "N2"}}
        self, node, run, gates = _p4_fixture(td, band=0.02, gates=[prior])
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(gates == [], "an existing decided gate blocks a second offer")
    # an APPROVED (still-pending) repeat also blocks any second offer - the
    # aggregated result can never buy another run
    with tempfile.TemporaryDirectory() as td:
        self, node, run, gates = _p4_fixture(td, band=0.02)
        node["repeat_measure"] = {"cell": "C1", "result_key": "auc"}
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(gates == [], "an approved repeat in flight never triggers a second offer")
    # frozen effect comparator wins over the first parent when they diverge
    with tempfile.TemporaryDirectory() as td:
        self, node, run, gates = _p4_fixture(td, band=0.02,
                                             meta_extra={"effect_case": {"comparator_id": "baseline"}})
        origin = {"id": "N000", "role": "baseline", "status": "concluded",
                  "scores": {"auc": {"value": 0.90}}}
        self.g["nodes"].insert(0, origin)
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(gates == [] or all(g["subject"].get("comparator") == "N000" for g in gates),
              f"the trigger judges against the FROZEN comparator (baseline), not the parent: "
              f"{[g['subject'].get('comparator') for g in gates]}")
        check(gates == [],
              "delta vs baseline (-0.088) sits far outside every line -> no offer, although "
              "delta vs the parent (+0.012) would have been on the line")


def repeat_rule_registration():
    cfg = econfig.merged_default()
    cfg["evaluation_contract"]["cells"] = [
        {"id": "C1", "result_key": "auc", "role": "target", "required": True,
         "weight": 1.0, "goal_threshold": None}]
    cfg["metrics"] = [{"key": "auc", "direction": "max"}]
    ok_rule = {"cell": "C1", "band": 0.02, "when": "decision_within_band", "max_repeats": 1}
    check(evalid.repeat_rule_errors(cfg, {"repeat_rule": ok_rule}) == [],
          "a well-formed single-run registration passes")
    cfg_pre = json.loads(json.dumps(cfg))
    cfg_pre.setdefault("evidence_policy", {})["training_replication"] = \
        {"mode": "preplanned", "runs": 2, "aggregation": "mean", "seeds": [1, 2]}
    errs = evalid.repeat_rule_errors(cfg_pre, {"repeat_rule": ok_rule})
    check(any("IDEA_REPEAT_RULE_MODE" in e for e in errs),
          f"preplanned projects reject the rule outright (mutually exclusive tiers): {errs}")
    errs = evalid.repeat_rule_errors(cfg, {"repeat_rule": {**ok_rule, "max_repeats": 2}})
    check(any("IDEA_REPEAT_RULE_MAX" in e for e in errs),
          "max_repeats=2 (the adaptive loop) is refused")
    errs = evalid.repeat_rule_errors(cfg, {"repeat_rule": {**ok_rule, "cell": "C9"}})
    check(any("IDEA_REPEAT_RULE_CELL" in e for e in errs), "unknown cell is refused")
    no_band = {"cell": "C1", "when": "decision_within_band", "max_repeats": 1}
    errs = evalid.repeat_rule_errors(cfg, {"repeat_rule": no_band})
    check(any("IDEA_REPEAT_RULE_NO_BAND" in e for e in errs),
          "no band and no recorded floor -> registration refused as empty ceremony")
    cfg_floor = json.loads(json.dumps(cfg))
    cfg_floor["evaluation_contract"]["noise_floors"] = {"C1": 0.02}
    check(evalid.repeat_rule_errors(cfg_floor, {"repeat_rule": no_band}) == [],
          "a recorded floor stands in for an omitted band (priority tier 2)")
    errs = evalid.repeat_rule_errors(cfg, {"repeat_rule": {**ok_rule, "junk": 1}})
    check(any("IDEA_REPEAT_RULE_FIELDS" in e for e in errs), "unknown fields are refused")
    check(evalid.repeat_rule_errors(cfg, {}) == [], "no rule registered -> silent (optional)")


def repeat_measure_metric_door():
    ctx = SimpleNamespace()
    node = {"id": "N2", "repeat_measure": {
        "cell": "C1", "result_key": "auc", "gate": "G7",
        "base_seed": 11, "seed": 12}}
    errs = evalid.metric_evidence_errors(ctx, "auc", 0.81, None, node=node)
    check(any("EVAL_REPEAT_MEASURE_MISSING" in e for e in errs),
          f"approved repeat makes a bare scalar illegal on that metric: {errs}")
    good = {"value": 0.805, "training_replication": {
        "aggregation": "mean",
        "runs": [{"seed": 11, "value": 0.80, "source": "first run artifact"},
                 {"seed": 12, "value": 0.81, "source": "repeat run artifact"}]}}
    check(evalid.metric_evidence_errors(ctx, "auc", good, None, node=node) == [],
          "the approved 2-run set validates through the preplanned machinery")
    bad = json.loads(json.dumps(good))
    bad["value"] = 0.81
    errs = evalid.metric_evidence_errors(ctx, "auc", bad, None, node=node)
    check(any("RECOMPUTE" in e for e in errs),
          f"the engine recomputes the mean and rejects a wrong aggregate: {errs}")
    check(any("EVAL_TRAINING_REPLICATION_UNAPPROVED" in e for e in
              evalid.metric_evidence_errors(ctx, "auc", good, None, node={"id": "N9"})),
          "without the approval, a repeat block stays illegal in single mode")
    check(evalid.metric_evidence_errors(ctx, "loss", 1.5, None, node=node) == [],
          "other metrics stay single-run scalars")
    # seed pinning: the reported pair must be exactly {base, repeat}
    wrong_seeds = json.loads(json.dumps(good))
    wrong_seeds["training_replication"]["runs"][1]["seed"] = 99
    errs = evalid.metric_evidence_errors(ctx, "auc", wrong_seeds, None, node=node)
    check(any("SEED_SET" in e for e in errs),
          f"a cherry-picked seed pair is rejected: {errs}")
    # dodge via a well-formed uncertainty object instead of the block
    dodge = {"value": 0.81, "uncertainty": {"method": "bootstrap", "unit": "samples",
                                            "unit_count": 1000, "procedure": "x" * 40,
                                            "source": "artifact path", "lower": 0.80, "upper": 0.82,
                                            "level": 0.95}}
    errs = evalid.metric_evidence_errors(ctx, "auc", dodge, None, node=node)
    check(any("EVAL_REPEAT_MEASURE_MISSING" in e for e in errs),
          f"an interval object cannot dodge the approved repeat duty: {errs}")
    # waived approval releases the duty; the single-run scalar is legal again
    waived = {"id": "N2", "repeat_measure": {**node["repeat_measure"], "waived": True}}
    check(evalid.metric_evidence_errors(ctx, "auc", 0.81, None, node=waived) == [],
          "a user-waived repeat releases the aggregate duty (single-run verdict stands)")
    # base-run value is anchored to the SEALED raw eval measurement
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".evo/nodes/N2/eval").mkdir(parents=True)
        (repo / ".evo/nodes/N2/eval/raw.json").write_text(json.dumps({"auc": 0.80}), encoding="utf-8")
        (repo / ".evo/nodes/N2/eval/repeat.json").write_text(json.dumps({"auc": 0.81}), encoding="utf-8")
        sealed_ctx = SimpleNamespace(
            st={"runs": [{"id": "R1", "metrics_file": ".evo/nodes/N2/eval/raw.json"}]},
            store=SimpleNamespace(repo=repo))
        anchored = {"id": "N2", "eval_run": "R1", "repeat_measure": dict(node["repeat_measure"])}
        # R8: with a real repo in context, the repeat run's source must be a
        # checkable citation - pin both directions of the new contract.
        anchored_good = json.loads(json.dumps(good))
        anchored_good["training_replication"]["runs"][0]["source"] = ".evo/nodes/N2/eval/raw.json"
        anchored_good["training_replication"]["runs"][1]["source"] = ".evo/nodes/N2/eval/repeat.json"
        check(evalid.metric_evidence_errors(sealed_ctx, "auc", anchored_good, None, node=anchored) == [],
              "a base value equal to the sealed measurement passes")
        prose_src = json.loads(json.dumps(anchored_good))
        prose_src["training_replication"]["runs"][1]["source"] = "manual repeat notes only"
        errs = evalid.metric_evidence_errors(sealed_ctx, "auc", prose_src, None, node=anchored)
        check(any("EVAL_REPEAT_SOURCE_MISSING" in e for e in errs),
              f"a prose-only repeat source is rejected when a repo can check it: {errs}")
        moved = json.loads(json.dumps(anchored_good))
        moved["training_replication"]["runs"][0]["value"] = 0.799
        moved["value"] = (0.799 + 0.81) / 2
        errs = evalid.metric_evidence_errors(sealed_ctx, "auc", moved, None, node=anchored)
        check(any("BASE_MISMATCH" in e for e in errs),
              f"rewriting the first run's value at aggregation time is rejected: {errs}")


# ---------------------------------------------------------------- P2 ------
def scaling_followup_novelty():
    def cand(kind):
        # 'program' present so validation reaches the novelty block; its own
        # graph errors are irrelevant to what this test asserts.
        return {"sketch_id": "SK1", "program": {},
                "novelty": {"kind": kind, "bearer": "x" * 60,
                            "kernel": [], "known_primitives": [],
                            "support_shell": []}}
    errs = eprogram.candidate_errors(
        cand("scaling_extension"), where="SK1", min_level=1, research=True,
        search_origin="constructive", model_parent_count=1, scaling_followup=False)
    check(any("PROGRAM_NOVELTY_KIND" in e and "scaling_extension" in e for e in errs),
          "scaling_extension outside a follow-up lane is rejected")
    errs = eprogram.candidate_errors(
        cand("scaling_extension"), where="SK1", min_level=1, research=True,
        search_origin="constructive", model_parent_count=1, scaling_followup=True)
    check(not any("PROGRAM_RESEARCH_NOVELTY" in e or "PROGRAM_NOVELTY_KIND" in e for e in errs),
          f"in a follow-up lane the scale dimension satisfies the research tier: "
          f"{[e for e in errs if 'NOVELTY' in e]}")
    errs = eprogram.candidate_errors(
        cand("irreducible"), where="SK1", min_level=1, research=True,
        search_origin="constructive", model_parent_count=1, scaling_followup=True)
    check(any("PROGRAM_SCALING_FOLLOWUP_KIND" in e for e in errs),
          "claiming fresh novelty inside the dup-exempt lane is rejected")


# ---------------------------------------------------------------- P5 ------
def exploratory_tier():
    errs = [e for e in eflow.check_tables(validators=None) if "EXPLORATORY" in e]
    check(errs == [], f"purpose tables + gate policy are complete: {errs}")
    check("exploratory" in econfig.EXPERIMENT_PURPOSES
          and "exploratory" not in econfig.INSTRUMENTAL_PURPOSES
          and "exploratory" not in econfig.INJECTABLE_PURPOSES,
          "exploratory is a declared, non-instrumental, non-injectable purpose")
    for gk in ("idea_approval", "workflow_approval"):
        check("exploratory" in eflow.GATE_POLICY[gk].manual_when,
              f"{gk} is always user-owned for exploratory")
    cfg = econfig.merged_default()
    node = {"id": "N5", "experiment_purpose": "exploratory", "status": "concluded",
            "verdict": "inconclusive", "role": "variant"}
    check(egraph.instrumental_frontier_excluded(node, cfg),
          "exploratory results never enter a frontier")
    check(not egraph.observation_eligible(node, cfg),
          "exploratory numbers are observations, not record material")
    check(eflow.INSTRUMENTAL_SEQ.get("exploratory") is None,
          "exploratory takes the full candidate route, not an instrumental one")
    # the two v_mature purpose checks must be SATISFIABLE for exploratory
    # (R1: they were jointly unsatisfiable - the tier died at its own door)
    node = {"id": "N9", "experiment_purpose": "exploratory", "status": "concluded", "role": "variant"}
    defects = [k for k, _ in evalid.model_parent_defects({"N9": node}, "N9")]
    check("exploratory" in defects,
          "a scout is never a model parent (observations are not lineage)")


def exploratory_mature_satisfiable():
    """The exact R1 contradiction: purpose gate vs purpose binding vs prefill."""
    src = open(HERE.parent / "engine" / "evalid.py", encoding="utf-8").read()
    check('purpose not in ("candidate", "exploratory")' in src,
          "v_mature's purpose gate admits exploratory (was: only candidate)")
    tsrc = open(HERE.parent / "engine" / "etask.py", encoding="utf-8").read()
    check('"experiment_purpose": str(lane.get("experiment_purpose") or "candidate")' in tsrc,
          "the mature prefill copies the LANE's purpose (was: hard-coded candidate)")
    gsrc = open(HERE.parent / "engine" / "egate.py", encoding="utf-8").read()
    check(gsrc.count('purpose in ("candidate", "exploratory")') >= 3,
          "gate reject can rewind an exploratory lane (sketch/theory/mature) instead of abandoning it")
    # R2: the custody chain must include scouts at every station
    check(tsrc.count('in ("candidate", "exploratory")') >= 2,
          "plan_node prefill + stale-draft custody include exploratory")
    check('meta.get("experiment_purpose") in ("candidate", "exploratory")' in src,
          "SPEC_* program bindings include exploratory")
    dsrc = open(HERE.parent / "engine" / "edoctor.py", encoding="utf-8").read()
    check(dsrc.count('in ("candidate", "exploratory")') >= 2,
          "doctor custody audits include exploratory")
    check(gsrc.count('scaling_followup_of") or lane.get("confirmatory_of")') >= 2,
          "carbon-copy lanes force manual idea AND workflow gates")
    check("repeat_rule" in evalid._INSTRUMENTAL_FORBIDDEN_META,
          "instrumental metas can never smuggle a repeat_rule past registration")


def carbon_copy_doors():
    """R2: the confirmatory door must be as locked as the scaling door."""
    src = open(HERE.parent / "engine" / "evalid.py", encoding="utf-8").read()
    for anchor in ("PROGRAM_CARBON_COPY_COUNT", "PROGRAM_CONFIRMATORY_KERNEL",
                   "PORTFOLIO_CONFIRMATORY_DUP", "PORTFOLIO_SCALING_FOLLOWUP_DUP",
                   "PROGRAM_SCALING_FOLLOWUP_PARENT_META"):
        check(anchor in src, f"{anchor} guard present")
    check('not lane.get("scaling_followup_of") and not lane.get("confirmatory_of")' in src,
          "diversity rules skip BOTH carbon-copy species (a 1-batch cannot be diverse)")
    # trigger revalidation: a malformed rule (never validated at any door)
    # cannot open the protected gate
    with tempfile.TemporaryDirectory() as td:
        self, node, run, gates = _p4_fixture(td, band=0.02)
        meta_path = Path(td) / ".evo/ideas/I1.meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["repeat_rule"]["max_repeats"] = 2
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        eabsorb.AbsorbMixin._maybe_open_repeat_measure(self, node, run)
        check(gates == [],
              "a rule failing the registration validator (max_repeats=2) never triggers")


def scaling_fingerprint_substitution():
    """R9 identity normalization: novelty.kind is a classification label and
    is no longer part of the computation identity (the R1 deadlock came from
    embedding it; the old fix substituted the parent's kind before hashing -
    that normalization IS the identity now). The legacy algorithm keeps the
    old behavior so hashes stored by earlier releases still match via
    kernel_identity_matches."""
    base = {"novelty": {"kind": "irreducible", "bearer": "b" * 60,
                        "kernel": [{"id": "KC1", "kind": "update_law",
                                    "statement": "s" * 60, "operator_refs": ["OP1"]}]}}
    parent_hash = eprogram.kernel_fingerprint(base)
    follow = json.loads(json.dumps(base))
    follow["novelty"]["kind"] = "scaling_extension"
    check(eprogram.kernel_fingerprint(follow) == parent_hash,
          "re-classifying the same computation keeps the same identity (R9)")
    check(eprogram.legacy_kernel_fingerprint(follow) != eprogram.legacy_kernel_fingerprint(base),
          "the LEGACY algorithm still embeds kind (stored-hash compatibility only)")
    check(eprogram.kernel_identity_matches(eprogram.legacy_kernel_fingerprint(base), base)
          and eprogram.kernel_identity_matches(parent_hash, base),
          "identity matching dual-accepts legacy and normalized stored hashes")
    def _with_program(op_id: str, obj_id: str) -> dict:
        cand = json.loads(json.dumps(base))
        cand["novelty"]["kernel"][0]["operator_refs"] = [op_id]
        cand["program"] = {
            "objects": [{"id": obj_id, "kind": "state", "semantics": "m" * 40}],
            "operators": [{"id": op_id, "kind": "update", "phase": "train",
                           "semantics": "u" * 60, "reads": [obj_id],
                           "writes": [obj_id], "depends_on": []}]}
        return cand
    check(eprogram.kernel_fingerprint(_with_program("OP1", "O1"))
          == eprogram.kernel_fingerprint(_with_program("OP9", "O7")),
          "consistently renumbered OP/O labels keep the same computation identity")
    neutral = eprogram.kernel_fingerprint(
        {**follow, "novelty": {**follow["novelty"], "kind": "irreducible"}})
    check(neutral == parent_hash,
          "kind substitution is now a no-op on the normalized identity")
    mutated = json.loads(json.dumps(follow))
    mutated["novelty"]["kernel"][0]["statement"] = "t" * 60
    check(eprogram.kernel_fingerprint(
        {**mutated, "novelty": {**mutated["novelty"], "kind": "irreducible"}}) != parent_hash,
        "any kernel-payload change still breaks the carbon-copy equality")


def provisional_st_threading():
    """Observed floors must reach the frontier bundle block and the dashboard
    rows - reverting the st thread anywhere here goes red."""
    cfg = econfig.merged_default()
    cfg["evaluation_contract"]["cells"] = [
        {"id": "C1", "result_key": "auc", "role": "target", "required": True,
         "weight": 1.0, "goal_threshold": None}]
    cfg["metrics"] = [{"key": "auc", "direction": "max"}]
    st = {"observed_noise": {"C1": {"width": 0.02, "sets": 2}}, "lanes": []}
    g = {"nodes": [
        {"id": "N1", "status": "concluded", "verdict": "improved", "role": "variant",
         "scores": {"auc": {"value": 0.80}}},
        {"id": "N2", "status": "concluded", "verdict": "improved", "role": "variant",
         "scores": {"auc": {"value": 0.815}}}]}
    block = "\n".join(ebundle.frontier_block(g, cfg, st))
    check("C1?" in block,
          "a record lead (0.015) inside the OBSERVED floor (0.02) is tagged '?' in the bundle")
    check("C1?" not in "\n".join(ebundle.frontier_block(g, cfg, None)),
          "without st there is no floor and no tag (v11 behavior)")
    import edash
    rows = edash._cell_records_with_provisional(g, cfg, st)
    check(rows and rows[0]["provisional"] is True, f"dashboard row carries the label: {rows}")
    rows0 = edash._cell_records_with_provisional(g, cfg, None)
    check(rows0 and rows0[0]["provisional"] is False, "no st -> dashboard label off")


def reference_line_chain():
    digest = "a" * 12
    line = ebundle._reference_line(digest, ".evo/tasks/T001/BUNDLE.md",
                                   "Phenomenon ledger (observations)")
    check("sha " + digest in line and "If you are not CERTAIN" in line,
          "the reference line carries digest + path + the read-if-uncertain rule")
    src = ebundle._chain_source(line, digest)
    check(src == (".evo/tasks/T001/BUNDLE.md", "Phenomenon ledger (observations)"),
          f"the chain parser round-trips the emitted format exactly: {src}")
    check(ebundle._chain_source(line, "b" * 12) is None,
          "a different sha never chains (changed content reprints in full)")
    hop2 = ebundle._reference_line(digest, src[0], src[1])
    check(ebundle._chain_source(hop2, digest) == src,
          "three bundles deep, the reference still names the ORIGINAL full text")
    check(ebundle._norm_block_title("Phenomenon ledger (repair evidence)")
          == ebundle._norm_block_title("Phenomenon ledger (observations)"),
          "per-stage title variants normalize to one key (body equality still decides)")


# ------------------------------------------------------------- P1 T2 ------
def bundle_reference_collapse():
    check(ebundle._REFERENCEABLE_BLOCKS.search("Lessons from prior work") is not None,
          "lessons blocks are referenceable")
    check(ebundle._REFERENCEABLE_BLOCKS.search("Execution playbook") is None,
          "playbook (execution-critical) is never referenceable")
    check(ebundle._REFERENCEABLE_BLOCKS.search("Execution-error journal") is None,
          "the errors journal is never referenceable")
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        tdir = repo / ".evo/tasks/T001"
        tdir.mkdir(parents=True)
        tdir.joinpath("BUNDLE.md").write_text(
            "# TASK T001\n\n## Lessons (inherited)\n- L1: do not overfit\n\n"
            "## Execution playbook\n- step one\n", encoding="utf-8")
        store = SimpleNamespace(repo=repo)
        st = {"tasks": [
            {"id": "T001", "type": "sketch", "subject": {"lane": "L001"},
             "bundle": ".evo/tasks/T001/BUNDLE.md"},
            {"id": "T002", "type": "mature", "subject": {"lane": "L001"}}]}
        task = {"id": "T002", "subject": {"lane": "L001"}}
        blocks, ref = ebundle._previous_bundle_blocks(store, st, task)
        check("Lessons (inherited)" in blocks and ref == ".evo/tasks/T001/BUNDLE.md",
              f"previous same-subject bundle parses into titled blocks: {list(blocks)}")
        check(blocks["Lessons (inherited)"].strip() == "- L1: do not overfit",
              "block body is exact")
        other = {"id": "T003", "subject": {"lane": "L999"}}
        st["tasks"].append({"id": "T003", "type": "sketch", "subject": {"lane": "L999"}})
        blocks2, _ = ebundle._previous_bundle_blocks(store, st, other)
        check(blocks2 == {}, "a different subject never inherits references")


# ------------------------------------------------------------- P1 T3 ------
def winner_stage_inputs():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        self = SimpleNamespace(store=SimpleNamespace(repo=repo))
        lane = {"id": "L001", "round": "R1", "sketches_path": "sk.json",
                "tournament_path": "tj.json"}
        rows = etask.TaskMixin._winner_stage_inputs(self, lane, "the winner")
        check(rows[0][0] == "sk.json" and len(rows) == 2,
              "no winner file (pre-v11.1 lane) -> old full rows, cold start intact")
        wdir = repo / ".evo/rounds/R1/lanes/L001"
        wdir.mkdir(parents=True)
        wdir.joinpath("WINNER.json").write_text("{}", encoding="utf-8")
        rows = etask.TaskMixin._winner_stage_inputs(self, lane, "the winner")
        check(rows[0][0].endswith("WINNER.json") and len(rows) == 3,
              f"winner file becomes the primary input: {rows[0]}")
        check(all(r[1].startswith("REFERENCE") for r in rows[1:]),
              "batch + tournament stay listed as REFERENCE rows - never hidden")


# ------------------------------------------------------------- P1 T4 ------
def ledger_slices():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".evo/evidence").mkdir(parents=True)
        pool = [{"id": f"M{i:03d}", "fact": f"fact {i}", "topic": ("adapters" if i == 3 else "misc")}
                for i in range(1, 41)]
        (repo / ".evo/evidence/MECH_CARDS.jsonl").write_text(
            "\n".join(json.dumps(r) for r in pool) + "\n", encoding="utf-8")
        ldir = repo / ".evo/rounds/R1/lanes/L001"
        ldir.mkdir(parents=True)
        ldir.joinpath("THEORY.md").write_text("built on M007 and M002", encoding="utf-8")
        self = object.__new__(etask.TaskMixin)   # real class attrs, no __init__
        self.store = SimpleNamespace(repo=repo)
        lane = {"id": "L001", "round": "R1", "focus": "adapters"}
        rows = etask.TaskMixin._ledger_slice_rows(self, lane, [("MECH", "cards it cites")])
        check(len(rows) == 2 and rows[0][0] == ".evo/slices/L001_MECH.jsonl"
              and rows[1][0] == ".evo/evidence/MECH_CARDS.jsonl",
              f"slice row + full-pool REFERENCE row: {[r[0] for r in rows]}")
        check("REFERENCE" in rows[1][1] and "40 entries" in rows[1][1],
              "the full pool is disclosed, with its size")
        sliced = eutil.read_jsonl(repo / ".evo/slices/L001_MECH.jsonl")
        ids = [r["id"] for r in sliced]
        check(len(sliced) == 16, f"cap 16 enforced: {len(sliced)}")
        check("M007" in ids and "M002" in ids, f"cited ids always make the slice: {ids[:6]}")
        check("M003" in ids, "focus-matched record makes the slice")
        check(ids == sorted(ids, key=lambda x: int(x[1:])),
              "slice preserves pool order (stable numbering for the reader)")
        check("M040" in ids, "newest entries fill the remainder")
        # small pool -> no ceremony
        (repo / ".evo/evidence/SOTA.jsonl").write_text(
            "\n".join(json.dumps({"id": f"S{i:03d}"}) for i in range(1, 6)) + "\n",
            encoding="utf-8")
        rows = etask.TaskMixin._ledger_slice_rows(self, lane, [("SOTA", "the library")])
        check(len(rows) == 1 and rows[0][0] == ".evo/evidence/SOTA.jsonl"
              and rows[0][1].startswith("the library"),
              f"a pool at/under its cap keeps the single full-pool row: {rows}")
        check("accepted prefix" in rows[0][1] and "do not cite" in rows[0][1],
              f"the full-pool row warns that only the accepted prefix is citable: {rows}")


# ---------------------------------------------------------------- P6 ------
def fidelity_provenance_lines():
    g = {"nodes": [{"id": "N1", "round": "R1"}]}
    tasks = [
        {"type": "implement", "status": "done", "session": "sessA", "subject": {"node": "N1"}},
        {"type": "fidelity", "status": "done", "session": "sessA", "subject": {"node": "N1"}}]
    ctx = SimpleNamespace(cfg={"policy": {"critic_isolation": "attest"}},
                          st={"tasks": tasks}, g=g)
    lines = evalid.node_review_provenance_lines(ctx, "R1")
    check(len(lines) == 1 and "self-audit" in lines[0],
          f"same-session fidelity audit is disclosed as a self-audit: {lines}")
    tasks[1]["session"] = "sessB"
    check("independent session" in evalid.node_review_provenance_lines(ctx, "R1")[0],
          "a fresh session reads as independent")
    ctx.cfg["policy"]["critic_isolation"] = "off"
    check(evalid.node_review_provenance_lines(ctx, "R1") == [],
          "off mode stays silent (v10 behavior)")


if __name__ == "__main__":
    observed_noise_floor()
    observed_noise_calibration_writer()
    repeat_rule_registration()
    repeat_measure_trigger()
    repeat_measure_metric_door()
    scaling_followup_novelty()
    scaling_fingerprint_substitution()
    exploratory_tier()
    exploratory_mature_satisfiable()
    carbon_copy_doors()
    provisional_st_threading()
    reference_line_chain()
    bundle_reference_collapse()
    winner_stage_inputs()
    ledger_slices()
    fidelity_provenance_lines()
    done("V11.1 FEATURE UNIT")
