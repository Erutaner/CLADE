"""Unit-speed coverage for instrumental admission and its knowledge ledger.

    python tests/v102_instrumental_admission_unit.py

The v10.2a test audit found nearly every validator-level admission rule
(INJECT_*, the revisable-rewind hint, parent legality, resolution retraction)
lived ONLY inside the 12-minute mock drive - a regression cost 12 minutes to
observe. These are direct validator calls on synthetic state; the drive keeps
only what genuinely needs a live engine.
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
import estore     # noqa: E402
import evalid     # noqa: E402
from _check import check, done  # noqa: E402


def node(nid, **kw):
    row = {"id": nid, "role": "variant", "status": "concluded", "parents": []}
    row.update(kw)
    return row


def graph(*nodes_):
    return {"nodes": list(nodes_)}


def parent_defect_kinds():
    """model_parent_defects is the shared core of BOTH doors and plan_node."""
    g = graph(
        node("N001"),
        node("N002", status="executing"),
        node("N003", verdict="screened_out"),
        node("N004", experiment_purpose="diagnostic_probe"),
        node("N005", experiment_purpose="maintenance", maintenance_parity="not_met"),
        node("N006", experiment_purpose="maintenance", maintenance_parity="met"),
        node("N007", retire_reason="pruned"),
        # a parity-met repair whose LINEAGE tip is pruned: the firewall must
        # follow effective_frontier_ancestor through the repair
        node("N008", experiment_purpose="maintenance", maintenance_parity="met",
             parents=["N007"]),
    )
    import egraph
    idx = egraph.by_id(g)

    def kinds(p):
        return [k for k, _ in evalid.model_parent_defects(idx, p)]

    check(kinds("N001") == [], "a concluded candidate parent is legal")
    check(kinds("N000") == ["unknown"], "an unknown parent is typed, not a KeyError")
    check(kinds("N002") == ["unfinished"], "an executing parent is refused")
    check(kinds("N003") == ["screened_out"], "a screened-out parent is refused")
    check(kinds("N004") == ["probe"], "a probe is evidence, never lineage")
    check(kinds("N005") == ["maint_unsettled"], "parity not_met blocks inheritance")
    check(kinds("N006") == [], "parity met licenses the repaired base")
    check(kinds("N007") == ["pruned"], "a pruned parent is refused")
    check(kinds("N008") == ["pruned"],
          "the pruned firewall follows the lineage through a parity-met repair")


def make_ctx(st, cfg, g):
    return evalid.Ctx(SimpleNamespace(repo=Path(".")), st, cfg, g, {"artifacts": []})


def base_cfg(**budgets):
    b = {"probes_max_per_round": 1, "maintenance_max_per_round": 1}
    b.update(budgets)
    return {"budgets": b, "project": {}}


def lane_row(lid, purpose, status, *, rid="R001", name=None):
    return {"id": lid, "round": rid, "status": status, "experiment_purpose": purpose,
            "name": name or lid.lower()}


def probe_ln(parent="N001", name="probe-q"):
    return {"name": name, "experiment_purpose": "diagnostic_probe", "intent": "exploit",
            "search_origin": "repair", "min_level": 0, "parents": [parent]}


def injection_door():
    g = graph(node("N001"), node("N009", experiment_purpose="diagnostic_probe"))

    def errs(ln, *, lanes=(), gates=(), cfg=None):
        st = {"lanes": list(lanes), "gates": list(gates)}
        return evalid.injected_lane_errors(make_ctx(st, cfg or base_cfg(), g), ln, "R001")

    e = errs({**probe_ln(), "experiment_purpose": "candidate"})
    check(any(x.startswith("INJECT_PURPOSE") for x in e),
          f"a candidate cannot use the mid-round door: {e}")
    e = errs(probe_ln(name="../../escape"))
    check(any(x.startswith("INJECT_NAME") for x in e),
          f"a traversal name is refused before any write: {e}")
    e = errs(probe_ln(name="Alpha"),
             lanes=[lane_row("L001", "diagnostic_probe", "abandoned", name="alpha")])
    check(any(x.startswith("INJECT_NAME_DUP") for x in e),
          f"names are case-insensitively unique (they become paths): {e}")
    e = errs(probe_ln(parent="N009"))
    check(any(x.startswith("INJECT_PARENT_PROBE") for x in e),
          f"probe parents are refused via the shared core: {e}")

    # Cap semantics: cap<=0 is a disabled door, never an exhausted budget.
    e = errs(probe_ln(), cfg=base_cfg(probes_max_per_round=0))
    check(any(x.startswith("INJECT_DISABLED") for x in e)
          and not any(x.startswith("INJECT_CAP") for x in e),
          f"cap 0 reads as OFF, not as spent: {e}")
    # Opened-including-abandoned counting: no refund churn.
    e = errs(probe_ln(), lanes=[lane_row("L001", "diagnostic_probe", "abandoned")])
    check(any(x.startswith("INJECT_CAP") for x in e),
          f"an abandoned lane still consumes the round's cap: {e}")

    # The rewind hint must be truthful in all three gate states.
    open_gate = {"id": "G1", "kind": "idea_approval", "status": "open",
                 "subject": {"lane": "L001"}}
    decided_gate = {**open_gate, "status": "approved"}
    e = errs(probe_ln(), lanes=[lane_row("L001", "diagnostic_probe", "gate")],
             gates=[open_gate])
    check(any("retry-stage probe_design" in x for x in e),
          f"an OPEN gate is offered as the slot-free rewind: {e}")
    e = errs(probe_ln(), lanes=[lane_row("L001", "diagnostic_probe", "done")],
             gates=[decided_gate])
    check(not any("--gate" in x for x in e),
          f"a decided gate must not be advertised as rewindable: {e}")
    check(any("already had its user gate decided" in x for x in e),
          f"the decided-gate state is described truthfully: {e}")
    e = errs(probe_ln(), lanes=[lane_row("L001", "diagnostic_probe", "abandoned")])
    check(any("No lane of this purpose reached its user gate" in x for x in e),
          f"the never-gated state is described truthfully: {e}")

    # INJECT_PENDING: undecided INCLUDES a lane sitting at its open gate.
    cfg2 = base_cfg(probes_max_per_round=2)
    e = errs(probe_ln(name="probe-two"),
             lanes=[lane_row("L001", "diagnostic_probe", "probe_design")], cfg=cfg2)
    check(any(x.startswith("INJECT_PENDING") for x in e),
          f"a design-stage lane is undecided: {e}")
    e = errs(probe_ln(name="probe-two"),
             lanes=[lane_row("L001", "diagnostic_probe", "gate")], gates=[open_gate],
             cfg=cfg2)
    check(any(x.startswith("INJECT_PENDING") for x in e),
          f"a lane at its OPEN manual gate is still undecided - excluding it queued "
          f"two manual gates at cap>=2: {e}")
    e = errs(probe_ln(name="probe-two"),
             lanes=[lane_row("L001", "diagnostic_probe", "approved")], cfg=cfg2)
    check(not any(x.startswith("INJECT_PENDING") for x in e),
          f"an approved lane is decided; only the cap constrains further opens: {e}")


def gain_chain():
    """maintenance_gain books each link's OWN contribution exactly once."""
    def assessment(deltas):
        return {"target_cells": sorted(deltas), "guardrail_cells": [],
                "cells": {cid: {"delta": d, "status": "improved"}
                          for cid, d in deltas.items()}}

    g1 = evalid.maintenance_gain(assessment({"C1": 3.0}))
    check(g1["C1"]["delta"] == 3.0 and g1["C1"]["cumulative_delta"] == 3.0,
          f"a single repair books its raw vs-ancestor delta: {g1}")
    g2 = evalid.maintenance_gain(assessment({"C1": 5.0}), g1)
    check(g2["C1"]["delta"] == 2.0 and g2["C1"]["cumulative_delta"] == 5.0,
          f"the second link books only its own contribution (5-3), keeping the "
          f"cumulative for the next link: {g2}")
    g3 = evalid.maintenance_gain(assessment({"C1": 4.5}), g2)
    check(abs(g3["C1"]["delta"] - (-0.5)) < 1e-12,
          f"a link that gives headroom back books a negative own-delta: {g3}")
    check(abs(g1["C1"]["delta"] + g2["C1"]["delta"] + g3["C1"]["delta"]
              - g3["C1"]["cumulative_delta"]) < 1e-12,
          "own-deltas telescope to the chain's cumulative - nothing double-booked")
    bad = evalid.maintenance_gain(assessment({"C1": 1.0}), {"C1": {"delta": True}})
    check(bad["C1"]["delta"] == 1.0,
          f"a bool parent delta is junk and must not arithmetic: {bad}")


def resolution_retraction():
    """A recovery voids earlier dispositions; later re-dispositions stay live."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        (repo / ".evo").mkdir()
        store = estore.Store(repo)
        st = {"counters": {}}
        er1 = store.add_error(st, {"node": "N010", "failure_class": "infrastructure",
                                   "note": "loader wrote the wrong path"})
        store.add_error_resolution({"resolves": er1, "node": "N010",
                                    "disposition": "fixed", "surface": "artifact_io",
                                    "fix": "read from run dir, not workarea root"})
        check(len(store.error_resolutions()) == 1, "the disposition is live")

        def pending():
            # real Ctx always carries st; the committed-ER filter reads it
            ctx = SimpleNamespace(store=store, st=st)
            return evalid.pending_infra_errors(ctx, "N010")

        check(pending() == [], "a dispositioned ER is not pending")
        store.retract_error_resolutions("N010", recovery="REC001",
                                        reason="conclusion recovered")
        check(store.error_resolutions() == [],
              "recovery voids the dispositions whose evidence it invalidated")
        check(pending() == [er1],
              "the knowledge duty REOPENS - the surplus check used to forbid "
              "re-dispositioning forever")
        store.add_error_resolution({"resolves": er1, "node": "N010",
                                    "disposition": "fixed", "surface": "artifact_io",
                                    "fix": "corrected after recovery: use run dir"})
        check(len(store.error_resolutions()) == 1 and pending() == [],
              "a re-conclusion's fresh disposition (appended AFTER the "
              "retraction) stays live")
        # Another node's rows are untouched by the retraction.
        er2 = store.add_error(st, {"node": "N011", "failure_class": "infrastructure",
                                   "note": "other node"})
        store.add_error_resolution({"resolves": er2, "node": "N011",
                                    "disposition": "transient"})
        store.retract_error_resolutions("N010", recovery="REC002", reason="again")
        live = store.error_resolutions()
        check([r.get("node") for r in live] == ["N011"],
              f"retraction is per-node, not global: {live}")


def injectable_tables():
    check(set(econfig.INJECTABLE_PURPOSES) ==
          set(econfig.INSTRUMENTAL_PURPOSES) - {"targeted_ablation"},
          "injectable = instrumental minus targeted_ablation, proven, not assumed")
    check(not eflow.check_tables(), "check_tables holds with the injectable tables")


def main() -> None:
    parent_defect_kinds()
    injection_door()
    gain_chain()
    resolution_retraction()
    injectable_tables()
    done("V10.2 INSTRUMENTAL ADMISSION UNIT")


if __name__ == "__main__":
    main()
