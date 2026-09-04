#!/usr/bin/env python3
"""v10 regression checks for the declarative flow tables, the defect-ledger
fixes (DESIGN_V10 §7) and the capability extensions (§8). Pure unit level:
no engine drive, no subprocesses."""
from __future__ import annotations

import copy
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG / "engine"))

import ecards      # noqa: E402
import econfig     # noqa: E402
import eflow       # noqa: E402
import eprogram    # noqa: E402
import erun        # noqa: E402
import estore      # noqa: E402
import eutil       # noqa: E402

CHECKS = 0


def ok(cond, message):
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(f"[check {CHECKS}] {message}")


def flow_tables():
    import evalid
    errs = eflow.check_tables(cards_dir=ecards.CARDS_DIR, validators=evalid.VALIDATORS)
    ok(not errs, f"flow tables must be total and card-backed: {errs}")
    for status in econfig.LANE_STATUSES:
        ok(status in eflow.LANE_FLOW, f"lane status {status} unhandled")
    for status in econfig.NODE_STATUSES:
        ok(status in eflow.NODE_FLOW, f"node status {status} unhandled")
    for kind in econfig.GATE_KINDS:
        ok(kind in eflow.GATE_POLICY, f"gate kind {kind} unpoliced")
    # every task type named by a flow step has a card on disk
    for table in (eflow.LANE_FLOW, eflow.NODE_FLOW):
        for step in table.values():
            if step.kind == "task":
                ok((ecards.CARDS_DIR / f"{eflow.TASK_TYPES[step.task_type].card}.md").is_file(),
                   f"card missing for {step.task_type}")
    # the scheduler/task modules carry a branch for every task-issuing status
    etask_src = (PKG / "engine" / "etask.py").read_text(encoding="utf-8")
    for status, step in eflow.LANE_FLOW.items():
        if step.kind == "task":
            ok(f'stg == "{status}"' in etask_src,
               f"etask has no dispatch branch for lane status {status}")


def instrumental_route_table():
    """v10.2: one purpose -> one route, and the table is what the engine reads.

    Three facts used to be spelled out per purpose - the entry status, the only
    legal rewind stage, and the statuses doctor accepts - which is how the
    inverse-of-candidate idiom ("purpose != targeted_ablation") survived the
    arrival of a third purpose.  Assert the table is total, that nothing else
    re-states it, and that check_tables refuses a route with a hole.
    """
    import copy
    import eapply
    import evalid

    ok(set(eflow.INSTRUMENTAL_SEQ) == set(econfig.INSTRUMENTAL_PURPOSES),
       f"every instrumental purpose needs exactly one route: {sorted(eflow.INSTRUMENTAL_SEQ)} "
       f"vs {sorted(econfig.INSTRUMENTAL_PURPOSES)}")
    for purpose, seq in eflow.INSTRUMENTAL_SEQ.items():
        ok(tuple(seq[-3:]) == ("gate", "approved", "node_created"),
           f"{purpose} must end at the manual user gate and node creation, got {seq[-3:]}")
        ok(all(s in econfig.LANE_STATUSES for s in seq),
           f"{purpose} route names an unknown lane status: {seq}")
        ok(all(s in eflow.LANE_FLOW for s in seq),
           f"{purpose} route names a status the scheduler cannot drive: {seq}")
        # The entry status is DERIVED from the route, not restated beside it.
        entry = eapply.ApplyMixin._lane_entry_status(
            {"experiment_purpose": purpose, "search_origin": "repair"})
        ok(entry == seq[0],
           f"{purpose} lanes must start at their route head {seq[0]!r}, got {entry!r}")
    # Candidate lanes keep the search-origin routing they always had.
    ok(eapply.ApplyMixin._lane_entry_status(
        {"experiment_purpose": "candidate", "search_origin": "repair"}) == "diagnose",
       "a repair candidate must still enter at diagnose")
    # A purpose-less legacy record reads as a candidate everywhere.
    ok(econfig.lane_purpose({}) == "candidate"
       and econfig.lane_purpose({"experiment_purpose": None}) == "candidate"
       and econfig.lane_purpose({"experiment_purpose": "maintenance"}) == "maintenance",
       "lane_purpose must default a missing purpose to candidate")

    # check_tables is the proof, so verify the proof actually bites.
    original = eflow.INSTRUMENTAL_SEQ
    try:
        holed = copy.deepcopy(dict(original))
        holed.pop("diagnostic_probe")
        eflow.INSTRUMENTAL_SEQ = holed
        errs = eflow.check_tables(cards_dir=ecards.CARDS_DIR, validators=evalid.VALIDATORS)
        ok(any(e.startswith("FLOW_INSTRUMENTAL_ROUTE_MISSING") for e in errs),
           f"a purpose with no route must fail check_tables: {errs}")

        stray = dict(original)
        stray["candidate"] = ("sketch", "gate", "approved", "node_created")
        eflow.INSTRUMENTAL_SEQ = stray
        errs = eflow.check_tables(cards_dir=ecards.CARDS_DIR, validators=evalid.VALIDATORS)
        ok(any(e.startswith("FLOW_INSTRUMENTAL_ROUTE_UNKNOWN") for e in errs),
           f"a route for a non-instrumental purpose must fail check_tables: {errs}")

        ungated = dict(original)
        ungated["diagnostic_probe"] = ("probe_design", "approved", "node_created")
        eflow.INSTRUMENTAL_SEQ = ungated
        errs = eflow.check_tables(cards_dir=ecards.CARDS_DIR, validators=evalid.VALIDATORS)
        ok(any(e.startswith("FLOW_INSTRUMENTAL_TAIL") for e in errs),
           f"an instrumental route that skips the user gate must fail check_tables: {errs}")
    finally:
        eflow.INSTRUMENTAL_SEQ = original
    ok(not eflow.check_tables(cards_dir=ecards.CARDS_DIR, validators=evalid.VALIDATORS),
       "the real tables must still be clean after the tamper checks")

    # Both instrumental caps are documented as the operator's door knob, so a
    # bad value must be a config diagnostic rather than a ValueError traceback
    # out of the middle of a validator.
    for key in ("probes_max_per_round", "maintenance_max_per_round"):
        for bad in ("two", -1, 1.5, None):
            cfg = econfig.merged_default()
            cfg["budgets"][key] = bad
            errs = econfig.validate_config(cfg)
            ok(any(e.startswith(f"CONFIG_BUDGET_{key.upper()}") for e in errs),
               f"budgets.{key}={bad!r} must be rejected by validate_config, got {errs[:3]}")
        cfg = econfig.merged_default()
        cfg["budgets"][key] = 0
        ok(not any(e.startswith(f"CONFIG_BUDGET_{key.upper()}")
                   for e in econfig.validate_config(cfg)),
           f"budgets.{key}=0 is the documented off-switch and must stay legal")


def fence_aware_markdown():
    text = "# alpha\nbody\n```python\n# not a heading\nx = 1\n```\ntail\n## beta\nz\n"
    sections = eutil.md_sections(text)
    ok(set(sections) == {"alpha", "beta"}, f"fence-blind sections: {sorted(sections)}")
    ok("# not a heading" in sections["alpha"], "fenced content must stay in the section body")
    ok(eutil.find_section({"presetup notes": "x", "setup": "y"}, "setup") == "y",
       "find_section must be whole-word, earliest exact")
    ok(eutil.find_section({"presetup notes": "x"}, "setup") is None,
       "substring heading match must be rejected")


def id_registry():
    for kind in eutil.ID_WIDTHS:
        sample = eutil.fmt_id(kind, 7, eutil.ID_WIDTHS[kind])
        parsed = eutil.parse_id(sample)
        ok(parsed == (kind, 7), f"parse_id must parse every allocatable kind: {kind} -> {parsed}")


def config_fail_closed():
    cfg = econfig.merged_default()
    cfg["project"].update({"name": "x", "goal": "y"})
    base_errs = econfig.validate_config(copy.deepcopy(cfg))
    # the default config is not fully filled (metrics etc.) - we only compare deltas
    def errs_with(mutate):
        cand = copy.deepcopy(cfg)
        mutate(cand)
        return econfig.validate_config(cand)

    def has(errors, code):
        return any(e.startswith(code) for e in errors)

    e = errs_with(lambda c: c["budgets"].pop("evidence_min_recent_ratio", None))
    ok(has(e, "CONFIG_BUDGET_EVIDENCE_MIN_RECENT_RATIO"),
       "deleting the recency ratio must fail closed (F12)")
    e = errs_with(lambda c: c["policy"]["scope_floor"].update({"wildcat": 2}))
    ok(has(e, "CONFIG_SCOPE_FLOOR_WILDCAT_MIN"), "wildcat scope floor must pin to 4 (F13)")
    e = errs_with(lambda c: c["budgets"].update({"predictions_min": 5, "predictions_max": 2}))
    ok(has(e, "CONFIG_BUDGET_PREDICTIONS"), "prediction range must cross-validate")
    e = errs_with(lambda c: c["budgets"].update({"theory_cycles_min_full": 9}))
    ok(has(e, "CONFIG_BUDGET_THEORY_RANGE"), "theory cycle range must cross-validate")
    e = errs_with(lambda c: c.update({"policy": "broken"}))
    ok(has(e, "CONFIG_BLOCK_POLICY") and isinstance(e, list),
       "a malformed policy block must be a deficiency, not a crash")
    e = errs_with(lambda c: c.update({"metrics": ["auc"]}))
    ok(has(e, "CONFIG_METRIC_0_SHAPE"), "a scalar metric entry must be a deficiency, not a crash")
    e = errs_with(lambda c: (c["policy"].update({"preset": "custom", "max_exploit_share": 7})))
    ok(has(e, "CONFIG_TEMPO_MAX_EXPLOIT_SHARE"), "custom preset must validate tempo keys")
    # E1: extension axes validation
    e = errs_with(lambda c: c["resource_contract"].update(
        {"extension_axes": [{"key": "train_tokens", "unit": "gb", "accounting": "runtime_profiler"}]}))
    ok(has(e, "CONFIG_RESOURCE_EXTENSION_0_DUP"), "core-axis collision must be rejected (E1)")
    e = errs_with(lambda c: c["resource_contract"].update(
        {"extension_axes": [{"key": "peak_gpu_memory_gb", "unit": "gb", "accounting": "runtime_profiler"}]}))
    ok(not has(e, "CONFIG_RESOURCE_EXTENSION"), f"a well-formed extension axis must validate: {e[:3]}")
    ok(econfig.resource_axes({**cfg, "resource_contract": {
        **cfg["resource_contract"],
        "extension_axes": [{"key": "peak_gpu_memory_gb", "unit": "gb",
                            "accounting": "runtime_profiler"}]}})[-1] == "peak_gpu_memory_gb",
       "resource_axes must append configured extensions")
    ok(econfig.resource_axes(cfg) == list(eprogram.RESOURCE_AXES),
       "with no extensions the axis list is exactly the core nine")
    # E2: human-study cells
    e = errs_with(lambda c: c["evaluation_contract"]["cells"].append(
        {"id": "C99", "dataset": "D1", "task": "T1", "metric": "auc", "result_key": "auc",
         "role": "guardrail", "source_kind": "human_study", "study_protocol": "x" * 90,
         "direction": "max"}))
    ok(has(e, "CONFIG_EVAL_CELL") and any("STUDY_ROLE" in x for x in e),
       "a human-study guardrail cell must be rejected (E2)")
    _ = base_errs


def config_nan_and_shape_robustness():
    cfg = econfig.merged_default()
    cfg["project"].update({"name": "x", "goal": "y"})

    def errs_with(mutate):
        c = copy.deepcopy(cfg)
        mutate(c)
        return econfig.validate_config(c)

    def has(errors, code):
        return any(e.startswith(code) for e in errors)

    nan = float("nan")
    e = errs_with(lambda c: c["evaluation_contract"]["cells"].append(
        {"id": "C98", "dataset": "D1", "task": "T1", "metric": "auc", "result_key": "auc98",
         "role": "diagnostic", "weight": nan, "min_improvement": 0.0,
         "noninferiority_margin": 0.0, "required": False, "goal_threshold": None,
         "goal_threshold_source": "progress-only cell for the NaN check"}))
    ok(has(e, "CONFIG_EVAL_CELL"), "NaN cell weight must be a deficiency")
    ok(any("WEIGHT" in x and "C98" not in x for x in e) or any("_WEIGHT" in x for x in e),
       f"NaN weight rejected: {[x for x in e if 'WEIGHT' in x][:2]}")
    e = errs_with(lambda c: c["evaluation_contract"].update({"decision": "auto"}))
    ok(has(e, "CONFIG_EVAL_DECISION_SHAPE"), "non-dict decision must be a deficiency, not a crash")
    e = errs_with(lambda c: c["evaluation_contract"].update({"assumptions": ["prose"]}))
    ok(has(e, "CONFIG_EVAL_ASSUMPTION_0_SHAPE"), "non-dict assumption must be a deficiency")
    e = errs_with(lambda c: c["policy"].update({"scope_floor": "high"}))
    ok(has(e, "CONFIG_SCOPE_FLOOR_SHAPE"), "non-dict scope_floor must be a deficiency")
    e = errs_with(lambda c: (c["project"].update({"mode": "research"}),
                             c.update({"policy": "fast"})))
    ok(has(e, "CONFIG_BLOCK_POLICY"), "research mode + string policy must not crash")
    e = errs_with(lambda c: c["evaluation_contract"]["cells"].append(
        {"id": "C97", "dataset": {"x": 1}, "task": "T1", "metric": "auc", "result_key": "auc97",
         "role": "diagnostic", "weight": 1.0, "min_improvement": 0.0,
         "noninferiority_margin": 0.0, "required": False, "goal_threshold": None,
         "goal_threshold_source": "progress-only cell for the shape check"}))
    ok(any("_DATASET" in x for x in e), "unhashable dataset ref must be a deficiency")
    e = errs_with(lambda c: c["evidence_policy"].update({"probe_mode_order": [{}, "same_run"]}))
    ok(has(e, "CONFIG_PROBE_ORDER"), "unhashable probe_mode_order entry must be a deficiency")
    ok(econfig.preset_conflicts({"policy": "balanced"}) != [], "string policy in preset_conflicts must not crash")
    broken = copy.deepcopy(cfg)
    broken["budgets"]["sketches_per_lane"] = float("nan")
    ok(econfig.budget(broken, "sketches_per_lane") == econfig.DEFAULT_CONFIG["budgets"]["sketches_per_lane"],
       "NaN budget falls back to the default instead of crashing")
    ok(econfig.resource_axes({"resource_contract": "broken"}) == list(eprogram.RESOURCE_AXES),
       "malformed resource_contract does not crash the axis accessor")


def probe_vector_nan():
    errs = eprogram.candidate_errors(
        {"sketch_id": "K1", "change_scope": "local",
         "program": {"scientific_parents": [], "objects": [], "operators": [],
                     "training_process": "x" * 50, "inference_process": "x" * 50,
                     "information_flow": "x" * 50, "resource_model": "x" * 50},
         "novelty": {"kind": "known", "bearer": "x" * 60, "kernel": [],
                     "known_primitives": [], "support_shell": []},
         "effect_case": {"comparator_id": "N001", "chain": [],
                          "predicted_gain": "x" * 90, "failure_signal": "x" * 60,
                          "resources": {"regime": "matched",
                                        "candidate": {a: float("nan") for a in eprogram.RESOURCE_AXES},
                                        "comparator": {a: 1 for a in eprogram.RESOURCE_AXES},
                                        "fixed_axes": list(eprogram.RESOURCE_AXES),
                                        "tradeoff_axes": [], "improvement_axes": [],
                                        "comparison": "y" * 90}},
         "claim_scope": {"kind": "generalist", "target_cells": ["C1"],
                          "guardrail_cells": [], "rationale": "z" * 70},
         "theory_role": "none"},
        where="K1", min_level=1, research=False, search_origin="constructive",
        model_parent_count=1)
    ok(any("PROGRAM_RESOURCE_VALUE" in e for e in errs),
       f"NaN resource values must be rejected: {[e for e in errs if 'RESOURCE' in e][:2]}")


def budget_accessor():
    cfg = econfig.merged_default()
    ok(econfig.budget(cfg, "sketches_per_lane") == cfg["budgets"]["sketches_per_lane"],
       "budget accessor reads the config")
    broken = copy.deepcopy(cfg)
    broken["budgets"]["sketches_per_lane"] = "six"
    ok(econfig.budget(broken, "sketches_per_lane") == econfig.DEFAULT_CONFIG["budgets"]["sketches_per_lane"],
       "budget accessor falls back to DEFAULT_CONFIG on malformed values")
    try:
        econfig.budget(cfg, "no_such_budget")
        ok(False, "unknown budget key must raise")
    except KeyError:
        ok(True, "unknown budget key raises")


def run_state_machine_guards():
    run = {"id": "RUN001", "node": "N001", "kind": "stage", "stage": "train",
           "contract_digest": "d" * 16, "stage_index": 0, "replica_index": 0}
    erun.initialize_run(run)
    try:
        erun.transition_execution(run, "prepared", job="job-1")
        ok(False, "binding a job onto a prepared intent must raise")
    except erun.RunTransitionError:
        ok(True, "prepared+job shape is refused at the transition layer")
    ok(not hasattr(erun, "prepare_identity"), "dead prepare_identity helper is gone")


def seed_rules():
    try:
        econfig.seed_slug(-5)
        ok(False, "negative int seeds must be rejected")
    except ValueError:
        ok(True, "negative int seed raises")
    ok(econfig.seed_slug(1337) == "1337", "plain int seeds keep their spelling")


def gate_kind_registry():
    store = estore.Store(Path("."))
    try:
        store.new_gate({"counters": {}, "gates": []}, "made_up_gate", {}, "x")
        ok(False, "unknown gate kinds must be refused")
    except ValueError:
        ok(True, "new_gate fails closed on unknown kinds")


def preset_invariant():
    for name, preset in econfig.PRESETS.items():
        ok(set(preset) == set(econfig.PRESET_KEYS), f"preset {name} drifted from PRESET_KEYS")


def main():
    flow_tables()
    instrumental_route_table()
    fence_aware_markdown()
    id_registry()
    config_fail_closed()
    config_nan_and_shape_robustness()
    probe_vector_nan()
    budget_accessor()
    run_state_machine_guards()
    seed_rules()
    gate_kind_registry()
    preset_invariant()
    print(f"V10 FLOW/FIX/EXTENSION UNIT GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
