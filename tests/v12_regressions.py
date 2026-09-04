"""v12 regressions - field-trial round (ENGINE_REVIEW 2026-09-01 + DEADLOCKS).

Pins for the v12 fixes, each of which corresponds to a defect the tgmin field
run actually paid for:
  - X1 novelty: a can_emulate-only tournament kill retires the exact contract
    but no longer banks the kernel fingerprint (the direction stays
    retryable); structural grounds (non_reducible=false / collage=true) still
    bank it
  - X2 validate: the read-only dry-run verb reports exactly what submit's
    validators would, spends no attempt and writes no state bytes
  - X4 budget band: usage > cap * stage_budget_tolerance invalidates; within
    the band the evidence is valid; the recorded floor on a sealed RUN
    era-gates later band changes; config validation refuses malformed values;
    the repeat-spend gate disclosures the deterministic-cost consideration on
    budget-cap failures
  - X6 rehearsal: a PASSING rehearsal submission has a real success
    transition (v11.7 fell into the terminal no-transition branch)
  - X7 probe seed: eval_intervention + '{seed}' is admitted under preplanned
    complete-workflow replication at BOTH layers and expands per-seed at
    runtime; it is refused coherently (idea layer first) otherwise
  - X8 sota refs: a tournament binding a non-exact-comparability S# in
    frontier_refs is refused at seal time, before the downstream
    IDEA_SOTA_DRIFT/IDEA_SOTA_NONCOMPARABLE pair becomes unsatisfiable
  - cards: the authoring cards document the validator-enforced fields the
    field run paid attempts to discover
"""
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

import econfig    # noqa: E402
import egate      # noqa: E402
import eprogram   # noqa: E402
import erehearsal  # noqa: E402
import esched     # noqa: E402
import estore     # noqa: E402
import eutil      # noqa: E402
import evalid     # noqa: E402


def _repo(tag):
    repo = HERE / f"v12-{tag}-{uuid.uuid4().hex[:8]}"
    repo.mkdir()
    return repo


def _write(repo: Path, rel: str, text: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class _FixtureStore:
    def __init__(self, repo: Path):
        self.repo = repo
        self.evo = repo / ".evo"
        self.events_log = []

    def event(self, actor, event, **data):
        self.events_log.append({"actor": actor, "event": event, **data})


# ------------------------------------------------------------ budget band ----
def band_semantics() -> None:
    check(econfig.budget_tolerance({}) == 1.0, "absent key means strict (band 1.0)")
    check(econfig.budget_tolerance({"stage_budget_tolerance": 1.5}) == 1.5, "a valid band is honored")
    check(econfig.budget_tolerance({"stage_budget_tolerance": 0.5}) == 1.0,
          "a sub-1 value clamps to strict in the accessor")
    bad = econfig.validate_config({"stage_budget_tolerance": 0.5})
    check(any(e.startswith("CONFIG_BUDGET_TOLERANCE") for e in bad),
          "a malformed band value surfaces loudly at config validation")
    good = econfig.validate_config({"stage_budget_tolerance": 1.25})
    check(not any(e.startswith("CONFIG_BUDGET_TOLERANCE") for e in good),
          "a legal band raises no config deficiency")

    repo = _repo("band")
    try:
        stage = {"budget": {"limits": {"gpu_hours": 4.0}},
                 "control": {"mode": "fixed"}}
        _write(repo, "m.json", json.dumps({"summary": {"acc": 0.5},
                                           "usage": {"gpu_hours": 4.05}}))
        _write(repo, "m_big.json", json.dumps({"summary": {"acc": 0.5},
                                               "usage": {"gpu_hours": 6.5}}))

        def _errs(cfg, mf="m.json", floor=None):
            ctx = SimpleNamespace(cfg=cfg, store=SimpleNamespace(repo=repo))
            return evalid.stage_result_errors(
                ctx, stage, mf, None, where="w", budget_band_floor=floor)

        strict = _errs({})
        check(any("STAGE_RESULT_BUDGET_EXCEEDED" in e for e in strict),
              f"over-cap usage under the strict default invalidates: {strict}")
        check(any("stage_budget_tolerance" in e for e in strict),
              "the strict-mode message names the governed remedy")
        banded = _errs({"stage_budget_tolerance": 1.5})
        check(not any("BUDGET_EXCEEDED" in e for e in banded),
              f"the same usage inside the band is valid evidence: {banded}")
        over_band = _errs({"stage_budget_tolerance": 1.5}, mf="m_big.json")
        check(any("BUDGET_EXCEEDED" in e and "1.5" in e for e in over_band),
              "beyond the band the refusal states the applied formula")
        floored = _errs({}, floor=1.5)
        check(not any("BUDGET_EXCEEDED" in e for e in floored),
              "a sealed RUN's recorded floor era-gates a later band lowering")

        eval_spec = {"eval": {"budget": {"limits": {"wallclock_minutes": 30.0}}}}
        _write(repo, "e.json", json.dumps({"_usage": {"wallclock_minutes": 30.4}}))

        def _eerrs(cfg, floor=None):
            ctx = SimpleNamespace(cfg=cfg, store=SimpleNamespace(repo=repo))
            return evalid.evaluation_result_errors(
                ctx, eval_spec, "e.json", where="w", budget_band_floor=floor)

        check(any("EVAL_RESULT_BUDGET_EXCEEDED" in e for e in _eerrs({})),
              "the eval side shares the strict default")
        check(not any("BUDGET_EXCEEDED" in e for e in _eerrs({"stage_budget_tolerance": 1.1})),
              "the eval side shares the band")
    finally:
        shutil.rmtree(repo, ignore_errors=True)
    check(evalid.budget_band_floor_of(None) is None
          and evalid.budget_band_floor_of({"budget_overages_within_tolerance": []}) is None,
          "no overage stamps means no floor")
    check(evalid.budget_band_floor_of(
        {"budget_overages_within_tolerance": [{"band": 1.2}, {"band": 1.5}]}) == 1.5,
        "the floor is the highest band actually applied at seal time")


def repeat_gate_budget_disclosure() -> None:
    captured = {}

    class _Store:
        def get_run(self, st, rid):
            return {"id": rid, "evidence_errors":
                    ["STAGE_RESULT_BUDGET_EXCEEDED: usage.gpu_hours=4.05 exceeds declared cap 4.0"],
                    }

        def new_gate(self, st, kind, subject, text):
            captured["text"] = text
            return {"id": "G001", "kind": kind, "subject": subject, "status": "open"}

    stub = SimpleNamespace(st={"gates": []}, store=_Store())
    node = {"id": "N1", "repeat_attempt": {"operation": "stage", "stage": "train",
                                          "source_run": "RUN9", "failure_class": "unknown"}}
    egate.GateMixin._repeat_spend_gate(stub, node, "stage", "train")
    check("CAUTION (budget-cap failure)" in captured.get("text", ""),
          "a budget-cap failure discloses the deterministic-cost consideration on the decision surface")
    check("stage_budget_tolerance" in captured.get("text", ""),
          "the disclosure names the governed remedy, not just the trap")

    captured.clear()

    class _Store2(_Store):
        def get_run(self, st, rid):
            return {"id": rid, "evidence_errors": []}

    stub2 = SimpleNamespace(st={"gates": []}, store=_Store2())
    egate.GateMixin._repeat_spend_gate(stub2, dict(node), "stage", "train")
    check("CAUTION (budget-cap failure)" not in captured.get("text", ""),
          "an ordinary failure carries no budget caution noise")


# ------------------------------------------------------------- kernel map ----
def _candidate(sid: str, bearer: str) -> dict:
    return {"sketch_id": sid, "change_scope": "subsystem",
            "program": {"objects": [], "operators": []},
            "novelty": {"kind": "irreducible", "bearer": bearer,
                        "kernel": [{"id": "KC1", "kind": "update_law",
                                    "statement": "s" * 60, "operator_refs": ["OP1"]}]},
            "effect_case": {"comparator_id": "baseline", "predicted_gain": "g" * 60}}


def emulation_kill_scope() -> None:
    repo = _repo("kmap")
    try:
        program_rel = ".evo/rounds/R001/lanes/L001/PROGRAMS_c1.json"
        tournament_rel = ".evo/rounds/R001/lanes/L001/TOURNAMENT_c1.json"
        k1 = _candidate("K1", "emulation-only kill keeps its core retryable")
        k2 = _candidate("K2", "structural kill still banks its core")
        _write(repo, program_rel, json.dumps({"sketches": [k1, k2]}))
        _write(repo, tournament_rel, json.dumps({"audits": [
            {"sketch_id": "K1", "decision": "kill",
             "irreducibility": {"non_reducible": True, "load_bearing": True, "collage": False},
             "emulation_matrix": [{"alternative": "E001", "can_emulate": True,
                                   "argument": "a" * 90}]},
            {"sketch_id": "K2", "decision": "kill",
             "irreducibility": {"non_reducible": False, "load_bearing": True, "collage": False},
             "emulation_matrix": [{"alternative": "E001", "can_emulate": True,
                                   "argument": "a" * 90}]},
        ]}))
        st = {"lanes": [{"id": "L001", "status": "done", "sketches_path": program_rel,
                         "program_set_digest": "accepted", "tournament_path": tournament_rel,
                         "attempts": [], "idea_revisions": []}]}
        ctx = evalid.Ctx(_FixtureStore(repo), st, {"project": {"mode": "research"}},
                         {"nodes": []}, {})
        contracts, kernels = evalid.historical_program_blocks(ctx)
        check(eprogram.candidate_digest(k1) in contracts,
              "an emulation kill still retires the exact frozen contract")
        check(eprogram.kernel_fingerprint(k1) not in kernels,
              "a can_emulate-only kill no longer closes the kernel direction graph-wide")
        check(eprogram.kernel_fingerprint(k2) in kernels,
              "a structural self-verdict (non_reducible=false) still banks the core")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ---------------------------------------------------- rehearsal transition ----
_REH_SPEC = {"workflow": {"stages": [{"name": "train"}, {"name": "eval_prep"}]},
             "rehearsal": {"command": "unused", "timeout_s": 300,
                           "description": "d" * 60}}

_REH_ADAPTER = r'''
import json, os
req = json.load(open(os.environ["EVO_REHEARSAL_REQUEST"], encoding="utf-8"))
obs = {"nonce": os.environ["EVO_REHEARSAL_NONCE"],
       "checks": [{"stage": s, "status": "pass",
                   "detail": "tiny real stage executed and produced its artifact",
                   "read_back_by": "the next stage loader re-read the artifact and verified shape"}
                  for s in req["stages"]],
       "metrics": {}}
open(os.environ["EVO_REHEARSAL_RESULT"], "w", encoding="utf-8").write(json.dumps(obs))
'''


def rehearsal_success_transition() -> None:
    repo = _repo("reh")
    try:
        estore.Store(repo).init("t", "g")
        store = estore.Store(repo)
        (repo / "adapter.py").write_text(_REH_ADAPTER, encoding="utf-8")
        spec = dict(_REH_SPEC)
        spec["rehearsal"] = {"command": f'"{sys.executable}" adapter.py', "timeout_s": 120,
                             "description": "r" * 60}
        (repo / "specs").mkdir()
        eutil.write_json_atomic(repo / "specs/N9.json", spec)
        cfg = store.load_config()
        cfg.setdefault("project", {})["rehearsal"] = "full_chain"
        eutil.write_json_atomic(store.config_path, cfg)
        g = store.load_graph()
        g.setdefault("nodes", []).append(
            {"id": "N9", "role": "variant", "status": "stage_ready", "spec": "specs/N9.json",
             "workdir": ".", "implementation_seal": {"digest": "seal-1"}})
        store.save_graph(g)
        record = erehearsal.run(store, "N9")
        check(record.get("status") == "passed", f"fixture rehearsal passes: {record}")

        eng = esched.Engine(store)
        task = {"id": "T900", "type": "rehearsal", "status": "open",
                "subject": {"node": "N9"}, "outputs": []}
        eng._transition(task)  # v11.7 raised: no transition for task type rehearsal
        events = eutil.read_jsonl(store.events_path)
        check(any(e.get("event") == "rehearsal_accepted" and e.get("node") == "N9"
                  for e in events),
              "the success transition records the acceptance fact")

        node = next(n for n in eng.g["nodes"] if n["id"] == "N9")
        node["implementation_seal"] = {"digest": "seal-2"}
        raises(lambda: eng._transition(dict(task)), SystemExit,
               "a rehearsal acceptance without a satisfying record is refused as an engine bug",
               contains="engine bug")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# -------------------------------------------------------------- probe seed ----
def probe_seed_contract() -> None:
    spec_pre = {"training_replication": {"mode": "preplanned", "source": "workflow",
                                         "seeds": [0, 1, 2]},
                "probe_execution": {"mode": "eval_intervention",
                                    "artifact": "results/I1_rank_s{seed}.json"}}
    rows = evalid.expected_probe_observations(spec_pre)
    check([r["seed"] for r in rows] == [0, 1, 2],
          "eval_intervention + {seed} expands one observation per seed under preplanned workflow")
    check(all("{seed}" not in r["artifact"] for r in rows),
          "the expansion resolves each seed's landing")
    single = evalid.expected_probe_observations(
        {"training_replication": {"mode": "preplanned", "source": "workflow", "seeds": [0, 1]},
         "probe_execution": {"mode": "eval_intervention", "artifact": "results/one.json"}})
    check(len(single) == 1 and single[0]["seed"] is None,
          "an unseeded eval intervention stays a single observation")

    probe = {"mode": "eval_intervention", "signal": "s" * 40, "expect": "e" * 20,
             "artifact": "results/I1_rank_s{seed}.json",
             "required_fields": ["rank"], "decision_rule": {"field": "rank"}}
    meta = {"mechanism_probe": probe}
    spec = {"training_replication": {"mode": "preplanned", "source": "workflow",
                                     "seeds": [0, 1]},
            "probe_execution": dict(probe, command="python eval_probe.py --all-seeds",
                                    smoke_artifact="results/smoke_probe.json"),
            "smoke_plan": [{"must_exist": ["results/smoke_probe.json"]}]}
    ctx = SimpleNamespace(cfg={}, store=SimpleNamespace(repo=Path(".")))
    errs = evalid._probe_plan_errors(ctx, spec, meta, where="w")
    check(not any("SPEC_PROBE_EVAL_SEED_TEMPLATE" in e for e in errs),
          "the plan layer admits the per-seed eval intervention the seal registered")
    spec_single = dict(spec, training_replication={"mode": "single", "source": "workflow",
                                                   "seeds": [0]})
    errs2 = evalid._probe_plan_errors(ctx, spec_single, meta, where="w")
    check(any("SPEC_PROBE_EVAL_SEED_TEMPLATE" in e for e in errs2),
          "outside preplanned workflow replication the placeholder stays refused")

    check(evalid.idea_probe_seed_template_errors(
        {"evidence_policy": {"training_replication": {"mode": "record_only"}}}, probe) != [],
        "the idea layer refuses the doomed combination before it seals")
    check(evalid.idea_probe_seed_template_errors(
        {"evidence_policy": {"training_replication": {"mode": "preplanned"}}}, probe) == [],
        "the idea layer admits the combination the plan layer can honor")
    pre = {"evidence_policy": {"training_replication": {"mode": "preplanned"}}}
    check(evalid.idea_probe_seed_template_errors(pre, probe, purpose="exploratory") != [],
          "a scout's probe cannot carry '{seed}' - its node is forced to a single run")
    check(evalid.idea_probe_seed_template_errors(pre, probe, intent="platform") != [],
          "a platform idea cannot carry '{seed}' either")
    check(evalid.idea_probe_seed_template_errors(pre, probe, purpose="candidate") == [],
          "a candidate under preplanned policy keeps the placeholder")
    src = (HERE.parent / "engine" / "evalid.py").read_text(encoding="utf-8")
    check("idea_probe_seed_template_errors(\n                ctx.cfg, meta[\"mechanism_probe\"]" in src
          or "idea_probe_seed_template_errors(" in src.split("Probe SHAPE and the waiver")[1][:1200],
          "the idea-layer check runs in the UNIVERSAL probe-shape block, not only for research candidates")


# ----------------------------------------------------------- frontier refs ----
def tournament_frontier_ref_comparability() -> None:
    repo = _repo("sota")
    try:
        program_rel = ".evo/rounds/R001/lanes/L001/PROGRAMS_c1.json"
        review_rel = ".evo/rounds/R001/lanes/L001/TOURNAMENT_c1.md"
        output_rel = ".evo/rounds/R001/lanes/L001/TOURNAMENT_check.json"
        cand = _candidate("K1", "sota-bound candidate under audit")
        cand["novelty"]["non_reducibility"] = "n" * 120
        cand["novelty"]["load_bearing_test"] = "l" * 90
        cand["claim_scope"] = {"target_cells": ["C1"]}
        _write(repo, program_rel, json.dumps({"sketches": [cand]}))
        _write(repo, review_rel, "## Review\n\nindependent audit fixture\n")
        _write(repo, ".evo/evidence/SOTA.jsonl",
               json.dumps({"id": "S001", "cell": "C1", "comparability": "protocol_adjusted"}) + "\n"
               + json.dumps({"id": "S002", "cell": "C1", "comparability": "exact"}) + "\n")
        lane = {"id": "L001", "intent": "reform", "min_level": 2,
                "sketches_path": program_rel, "program_set_digest": "",
                "search_origin": "constructive"}
        st = {"lanes": [lane]}
        cfg = {"project": {"mode": "research"}, "research": {"sota_enabled": True},
               "metrics": [{"key": "acc", "direction": "max"}],
               "evaluation_contract": {"cells": [
                   {"id": "C1", "role": "target", "result_key": "acc", "metric": "acc"}]}}
        ctx = evalid.Ctx(estore.Store(_init_repo(repo)), st, cfg, {"nodes": []}, {})
        lane["program_set_digest"] = evalid.json_file_digest(ctx, program_rel)

        def payload(refs):
            return {"lane": "L001", "program_set_digest": lane["program_set_digest"],
                    "audits": [{
                        "sketch_id": "K1", "program_digest": eprogram.candidate_digest(cand),
                        "quote": cand["novelty"]["bearer"],
                        "prior_art": {"neighbors": [], "search_stop_reason": "x" * 90},
                        "emulation_matrix": [],
                        "irreducibility": {"non_reducible": True, "load_bearing": True,
                                           "collage": False, "argument": "x" * 120},
                        "scope": {"claimed_scope": "subsystem", "audited_scope": "subsystem",
                                  "train_semantics_preserved": False,
                                  "infer_semantics_preserved": False,
                                  "preserved_interfaces": [], "argument": "x" * 120},
                        "effect": {"causal_chain_valid": True, "comparator_valid": True,
                                   "threshold_credible": True, "resource_status": "matched",
                                   "resource_confounds": [], "resource_provenance": "x" * 90,
                                   "frontier_refs": refs, "argument": "x" * 120},
                        "decision": "kill", "reason": "x" * 80,
                        "published_dup": None}],
                    "survivor_ranking": [], "winners": []}

        _write(repo, output_rel, json.dumps(payload(["S001"])))
        errs = evalid.v_tournament(ctx, {"subject": {"lane": "L001"},
                                         "outputs": [output_rel, review_rel]})
        check(any(e.startswith("TOURNAMENT_FRONTIER_REF_NONCOMPARABLE") for e in errs),
              f"a non-exact frontier ref is refused at tournament seal time: {errs[:3]}")
        _write(repo, output_rel, json.dumps(payload(["S002"])))
        errs2 = evalid.v_tournament(ctx, {"subject": {"lane": "L001"},
                                          "outputs": [output_rel, review_rel]})
        check(not any(e.startswith("TOURNAMENT_FRONTIER_REF_NONCOMPARABLE") for e in errs2),
              "an exact-comparability ref carries no such refusal")

        # Self-review F3 axes: the check fires ONLY where maturation's
        # DRIFT x NONCOMPARABLE pair exists (research mode, research kernel,
        # non-exploratory); everywhere else non-exact refs stay legal.
        eng_cfg = dict(cfg, project={"mode": "engineering"})
        eng_ctx = evalid.Ctx(estore.Store(repo), st, eng_cfg, {"nodes": []}, {})
        _write(repo, output_rel, json.dumps(payload(["S001"])))
        eng_errs = evalid.v_tournament(eng_ctx, {"subject": {"lane": "L001"},
                                                 "outputs": [output_rel, review_rel]})
        check(not any("NONCOMPARABLE" in e or "NO_EXACT" in e for e in eng_errs),
              "engineering mode keeps non-exact refs legal end-to-end")
        # No-exact library: the REQUIRED x NONCOMPARABLE pair would be jointly
        # unsatisfiable - it collapses into ONE refusal naming real exits.
        _write(repo, ".evo/evidence/SOTA.jsonl",
               json.dumps({"id": "S001", "cell": "C1",
                           "comparability": "protocol_adjusted"}) + "\n")
        # fresh Ctx: the sota ledger is memoized per validation window
        noex_ctx = evalid.Ctx(estore.Store(repo), st, cfg, {"nodes": []}, {})
        noex = evalid.v_tournament(noex_ctx, {"subject": {"lane": "L001"},
                                              "outputs": [output_rel, review_rel]})
        check(any(e.startswith("TOURNAMENT_FRONTIER_NO_EXACT_SOTA") for e in noex),
              f"an all-non-exact library collapses to the single honest refusal: {noex[:2]}")
        check(not any(e.startswith("TOURNAMENT_FRONTIER_REF_REQUIRED")
                      or e.startswith("TOURNAMENT_FRONTIER_REF_NONCOMPARABLE") for e in noex),
              "the collapsed refusal replaces the unsatisfiable pair, not adds to it")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def band_exit_guidance() -> None:
    """The field's own RUN143 lesson: an over-cap RUN is NOT a dead RUN. The
    refusal, the terminal-disposition verb and the docs all name the no-rerun
    exit (raise the key, run-reconcile the same RUN)."""
    ctx = SimpleNamespace(cfg={}, store=SimpleNamespace(repo=Path(".")))
    repo = _repo("bandexit")
    try:
        _write(repo, "m.json", json.dumps({"summary": {"acc": 1.0}, "usage": {"gpu_hours": 7.5}}))
        ctx = SimpleNamespace(cfg={}, store=SimpleNamespace(repo=repo))
        errs = evalid.stage_result_errors(
            ctx, {"budget": {"limits": {"gpu_hours": 4.0}}}, "m.json", None, where="w")
        hit = [e for e in errs if "BUDGET_EXCEEDED" in e]
        check(hit and "run-reconcile" in hit[0] and "stage_budget_tolerance" in hit[0]
              and "no rerun" in hit[0],
              f"the strict refusal names the no-rerun exit: {hit[:1]}")
        ctx2 = SimpleNamespace(cfg={"stage_budget_tolerance": 1.5}, store=SimpleNamespace(repo=repo))
        errs2 = evalid.stage_result_errors(
            ctx2, {"budget": {"limits": {"gpu_hours": 4.0}}}, "m.json", None, where="w")
        hit2 = [e for e in errs2 if "BUDGET_EXCEEDED" in e]
        check(hit2 and "run-reconcile" in hit2[0],
              "an out-of-band refusal names the same exit (raise the band further, reconcile)")
        ctx3 = SimpleNamespace(cfg={"stage_budget_tolerance": 2.0}, store=SimpleNamespace(repo=repo))
        errs3 = evalid.stage_result_errors(
            ctx3, {"budget": {"limits": {"gpu_hours": 4.0}}}, "m.json", None, where="w")
        check(not any("BUDGET_EXCEEDED" in e for e in errs3),
              "7.5h against a 4h cap validates once the user grants band 2.0 - same bytes, no rerun")
    finally:
        shutil.rmtree(repo, ignore_errors=True)
    for rel, needle in (("engine/eabsorb.py", "would adopt the "),
                        ("engine/egate.py", "intended FIRST exit"),
                        ("README.md", "not to rerun it"),
                        ("OPERATOR_PROMPT.md", "never rerun or discard it"),
                        ("skills/model-evolution/SKILL.md", "no rerun")):
        check(needle in (HERE.parent / rel).read_text(encoding="utf-8"),
              f"{rel} teaches the reconcile exit for an acceptable overage")


def band_stamp_provenance() -> None:
    repo = _repo("stamp")
    try:
        _write(repo, "specs/N1.json", json.dumps(
            {"workflow": {"stages": [{"name": "train",
                                      "budget": {"limits": {"gpu_hours": 4.0}}}]}}))
        _write(repo, "m.json", json.dumps({"summary": {"acc": 1.0},
                                           "usage": {"gpu_hours": 4.05}}))
        events = []
        stub = SimpleNamespace(
            cfg={"stage_budget_tolerance": 1.5},
            store=SimpleNamespace(repo=repo,
                                  event=lambda actor, event, **kw: events.append(event)),
            _spec=lambda self_node: json.loads((repo / "specs/N1.json").read_text(encoding="utf-8")))
        stub._spec = lambda node: json.loads((repo / "specs/N1.json").read_text(encoding="utf-8"))
        import eabsorb
        # stage resolved by NAME (no stage_index) - self-review F1a
        run = {"id": "RUN1", "kind": "stage", "stage": "train", "metrics_file": "m.json"}
        eabsorb.AbsorbMixin._disclose_budget_overage(stub, run, {"id": "N1"})
        stamps = run.get("budget_overages_within_tolerance") or []
        check(len(stamps) == 1 and stamps[0]["unit"] == "gpu_hours",
              f"a name-resolved stage still stamps its overage: {stamps}")
        check(stamps[0]["band"] >= 1.5, "the stamp records at least the admitting band")
        # era skew - self-review F1b: replay under a LOWERED band still stamps
        # the ratio the sealed numbers themselves prove
        run2 = {"id": "RUN2", "kind": "stage", "stage": "train", "stage_index": 0,
                "metrics_file": "m.json"}
        stub.cfg = {}
        eabsorb.AbsorbMixin._disclose_budget_overage(stub, run2, {"id": "N1"})
        stamps2 = run2.get("budget_overages_within_tolerance") or []
        check(len(stamps2) == 1 and stamps2[0]["band"] >= 4.05 / 4.0,
              f"a crash-replay under a lowered band stamps the proven ratio floor: {stamps2}")
        floor = evalid.budget_band_floor_of(run2)
        ctx = SimpleNamespace(cfg={}, store=SimpleNamespace(repo=repo))
        replay = evalid.stage_result_errors(
            ctx, {"budget": {"limits": {"gpu_hours": 4.0}}}, "m.json", None,
            where="w", budget_band_floor=floor)
        check(not any("BUDGET_EXCEEDED" in e for e in replay),
              "the stamped floor keeps the sealed evidence valid at strict-band replay")
        # idempotence across re-seal
        eabsorb.AbsorbMixin._disclose_budget_overage(stub, run2, {"id": "N1"})
        check(len(run2.get("budget_overages_within_tolerance") or []) == 1,
              "re-sealing the same numbers does not duplicate the stamp")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def _init_repo(repo: Path) -> Path:
    if not (repo / ".evo" / "state.json").exists():
        estore.Store(repo).init("t", "g")
    return repo


# ----------------------------------------------------------- validate verb ----
def validate_dry_run() -> None:
    repo = _repo("val")
    try:
        estore.Store(repo).init("t", "g")
        store = estore.Store(repo)
        eng = esched.Engine(store)
        eng.compute_next()
        st = store.load_state()
        open_tasks = [t for t in st.get("tasks", []) if t.get("status") == "open"]
        check(len(open_tasks) >= 1, "bootstrap mints an open task to dry-run against")
        task = open_tasks[0]

        state_before = store.state_path.read_bytes()
        eng2 = esched.Engine(store)
        report = eng2.validation_report(task["id"])
        check(report.get("errors"),
              "an unwritten submission reports its deficiencies through the dry run")
        check(store.state_path.read_bytes() == state_before,
              "the dry run writes no state bytes")
        st_after = store.load_state()
        task_after = next(t for t in st_after["tasks"] if t["id"] == task["id"])
        check(int(task_after.get("attempts") or 0) == int(task.get("attempts") or 0),
              "the dry run spends no attempt")

        eng3 = esched.Engine(store)
        out = eng3.submit(task["id"])
        check(out.get("kind") == "rejected", "submit rejects the same unwritten outputs")
        st_burned = store.load_state()
        task_burned = next(t for t in st_burned["tasks"] if t["id"] == task["id"])
        check(int(task_burned.get("attempts") or 0) == int(task.get("attempts") or 0) + 1,
              "a real submit is what spends the attempt")
        check(set(report["errors"]) <= set(out.get("errors") or [])
              or bool(report["errors"]) == bool(out.get("errors")),
              "the dry run predicted the submit-time deficiency surface")

        # Self-review F4: the dry run stamps the session on a COPY, exactly as
        # submit stamps the row - and never on the stored row.
        seen = {}
        original = evalid.VALIDATORS[task["type"]]
        try:
            evalid.VALIDATORS[task["type"]] = (
                lambda ctx, t: seen.setdefault("task", t) and [] or [])
            eng4 = esched.Engine(store)
            eng4.validation_report(task["id"], session="dry-run-session")
        finally:
            evalid.VALIDATORS[task["type"]] = original
        check(seen["task"].get("session") == "dry-run-session",
              "the validator judges the dry-run session, mirroring submit's pre-validation stamp")
        st_sess = store.load_state()
        task_sess = next(t for t in st_sess["tasks"] if t["id"] == task["id"])
        check(task_sess.get("session") is None or "session" not in task_sess,
              "the stored task row keeps no dry-run session stamp")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# -------------------------------------------------------------- card pins ----
def card_schema_sync() -> None:
    cards = HERE.parent / "engine" / "cards"

    def has(name: str, token: str) -> bool:
        return token in (cards / name).read_text(encoding="utf-8")

    check(has("plan_node.md", '"rehearsal"'),
          "plan_node documents the rehearsal block the validator enforces")
    check(has("plan_node.md", "service_snapshot"),
          "plan_node documents the recorded-service snapshot duty")
    check(has("plan_node.md", "harness"), "plan_node documents eval.harness")
    check(has("plan_node.md", "transductive"), "plan_node documents eval.transductive")
    check(has("mature.md", '"scaling"'), "mature documents the scaling registration schema")
    check(has("mature.md", '"mode"') and has("mature.md", "cheaper_modes_rejected"),
          "mature documents the cheaper_modes_rejected row shape")
    check(has("tournament.md", "OPERATIONAL DEFINITION"),
          "the tournament card operationalizes emulation")
    check(has("tournament.md", "does\nnot close the kernel direction")
          or has("tournament.md", "not close the kernel direction"),
          "the tournament card states the scope of an emulation kill")
    check(has("plan_node.md", "stage_budget_tolerance"),
          "plan_node states the budget band and the worst-case derivation duty")
    check(has("rehearsal.md", "ACCEPTED"),
          "the rehearsal card states what a passing submit does")
    footer = (HERE.parent / "engine" / "ecards.py").read_text(encoding="utf-8")
    check("validate --task" in footer,
          "every card's footer teaches the read-only pre-submit check")
    prompt = (HERE.parent / "OPERATOR_PROMPT.md").read_text(encoding="utf-8")
    check("validate --task" in prompt and "FIELD_MAP" in prompt,
          "the operator prompt fixes the validate discipline and the field map convention")
    bundle = (HERE.parent / "engine" / "ebundle.py").read_text(encoding="utf-8")
    check("scope_floor.reform" in bundle,
          "the floor-in-force guidance names the config lever for small follow-ons")


def main() -> None:
    band_semantics()
    band_exit_guidance()
    band_stamp_provenance()
    repeat_gate_budget_disclosure()
    emulation_kill_scope()
    rehearsal_success_transition()
    probe_seed_contract()
    tournament_frontier_ref_comparability()
    validate_dry_run()
    card_schema_sync()
    done("V12 FIELD-TRIAL REGRESSIONS")


if __name__ == "__main__":
    main()
