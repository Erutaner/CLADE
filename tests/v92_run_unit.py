#!/usr/bin/env python3
"""Focused unit checks for the v9.2 independent RUN state machine."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))

import erun  # noqa: E402


CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[check {CHECKS}] {message}")


def raises(exc_type, fn, message: str) -> None:
    try:
        fn()
    except exc_type:
        check(True, message)
    else:
        check(False, message)


def fresh(rid: str = "RUN001", *, seed=11, contract: str = "spec+impl:r1",
          existing_runs=(), token: str = "run_0123456789abcdefghij") -> dict:
    run = {
        "id": rid, "node": "N002", "kind": "stage", "stage": "train",
        "stage_index": 0, "replica_index": 0, "replica_total": 1,
        "replica_seed": seed, "contract_digest": contract,
        "implementation_digest": "impl:r1", "status": "prepared",
        "evidence_status": "pending", "adoption_status": "candidate",
        "job": None, "started_at": None, "ended_at": None,
    }
    erun.initialize_run(
        run, existing_runs=existing_runs, token=token,
        now="2026-01-01T00:00:00+00:00")
    return run


def identity_checks() -> None:
    a = fresh()
    b = fresh("RUN002", existing_runs=[a], token="run_abcdefghij0123456789")
    check(a["logical_slot_key"] == b["logical_slot_key"], "replacement attempt keeps one logical slot")
    check((a["attempt_no"], b["attempt_no"]) == (1, 2), "attempt ordinal increases within slot+contract")
    check(a["attempt_key"] != b["attempt_key"], "each replacement has a distinct attempt key")

    changed = fresh(
        "RUN003", contract="spec+impl:r2", existing_runs=[a, b],
        token="run_zxcvbnmasdfghjkl1234")
    check(changed["attempt_no"] == 1, "new executable contract starts a fresh attempt epoch")
    string_seed = fresh("RUN004", seed="11")
    check(string_seed["logical_slot_key"] != a["logical_slot_key"], "integer and string seeds never alias")


def independent_axis_checks() -> None:
    run = fresh()
    erun.transition_execution(run, "running", job="job://cluster/77", now="t1")
    check(run["status"] == "running" and run["evidence_status"] == "pending",
          "launch changes external status only")
    erun.transition_execution(run, "finished", now="t2")
    erun.transition_evidence(run, "incomplete", note="same-run probe did not land", now="t3")
    check(run["status"] == "finished" and run["evidence_status"] == "incomplete",
          "successful execution stays successful when evidence is incomplete")
    check(not erun.can_adopt(run) and erun.needs_reconciliation(run),
          "incomplete evidence blocks adoption and requests repair")
    raises(erun.RunTransitionError,
           lambda: erun.transition_adoption(run, "adopted"),
           "incomplete evidence cannot be adopted")

    erun.transition_evidence(run, "complete", note="gap receipt sealed; mechanism remains unclear", now="t4")
    erun.transition_adoption(run, "adopted", now="t5")
    check(run["status"] == "finished" and run["adoption_status"] == "adopted",
          "evidence repair adopts the same successful RUN without a relaunch")
    raises(erun.RunTransitionError,
           lambda: erun.transition_execution(run, "running", job="job://cluster/77"),
           "terminal execution cannot be rewritten into a retry")


def recovery_checks() -> None:
    run = fresh()
    erun.transition_execution(run, "launch_unknown", note="client died after submit")
    check(erun.holds_external_slot(run) and erun.holds_reservation(run),
          "unknown launch keeps slot and reservation conservative")
    erun.confirm_not_launched(run, note="scheduler query found no job with the attempt token")
    check(run["status"] == "prepared" and not erun.holds_external_slot(run),
          "confirmed non-launch safely reopens the existing intent")
    raises(erun.RunTransitionError,
           lambda: erun.transition_execution(fresh(), "running"),
           "running requires a checkable job identity")

    adopted = fresh("RUN010")
    erun.transition_execution(adopted, "finished", now="t1")
    erun.transition_evidence(adopted, "complete", now="t2")
    erun.transition_adoption(adopted, "adopted", now="t3")
    raises(erun.RunTransitionError,
           lambda: erun.transition_evidence(adopted, "invalid", note="late audit"),
           "active authority must be quarantined before evidence is reopened")
    erun.transition_adoption(adopted, "quarantined", note="late audit found a provenance gap", now="t4")
    erun.transition_evidence(adopted, "invalid", note="wrong producer path", now="t5")
    erun.transition_evidence(adopted, "complete", note="same RUN evidence reconciled", now="t6")
    erun.transition_adoption(adopted, "adopted", now="t7")
    check(adopted["status"] == "finished" and adopted["adoption_status"] == "adopted",
          "quarantine/reconcile restores authority without changing execution truth")

    erun.transition_adoption(adopted, "superseded", note="implementation revision r2 became active", now="t8")
    check(adopted["status"] == "finished" and adopted["evidence_status"] == "complete",
          "superseding authority preserves historical execution and evidence facts")
    raises(erun.RunTransitionError,
           lambda: erun.transition_adoption(adopted, "adopted"),
           "superseded authority is terminal")

    abandoned = fresh("RUN011")
    erun.transition_execution(abandoned, "finished", now="t1")
    erun.transition_evidence(abandoned, "incomplete", note="metrics lost", now="t2")
    erun.transition_adoption(abandoned, "quarantined", note="recovery abandoned", now="t3")
    abandoned["evidence_disposition"] = "irrecoverable_quarantined"
    abandoned["evidence_disposition_receipt"] = ".evo/runs/RUN011/evidence/IRRECOVERABLE.json"
    check(not erun.needs_reconciliation(abandoned) and not erun.invariant_errors(abandoned),
          "an explicit irrecoverable quarantine is honest terminal history, not an eternal repair request")


def invariant_checks() -> None:
    run = fresh()
    check(not erun.invariant_errors(run), "fresh prepared RUN satisfies all local invariants")
    erun.transition_execution(run, "running", job="job-1", now="t1")
    check(not erun.invariant_errors(run), "running RUN satisfies job/timestamp invariants")
    erun.transition_execution(run, "finished", now="t2")
    erun.transition_evidence(run, "complete", now="t3")
    erun.transition_adoption(run, "adopted", now="t4")
    check(not erun.invariant_errors(run), "adopted RUN satisfies finished+complete invariant")

    drift = dict(run)
    drift["stage_index"] = 1
    check(any(x.startswith("RUN_SLOT_DRIFT") for x in erun.invariant_errors(drift)),
          "slot key detects stage-position mutation")
    bad = fresh("RUN020")
    bad["adoption_status"] = "adopted"
    check(any(x.startswith("RUN_ADOPTION_INVALID") for x in erun.invariant_errors(bad)),
          "doctor audit catches authority without evidence")

    first = fresh("RUN030")
    second = fresh(
        "RUN031", existing_runs=[first], token="run_qwertyuiopasdfghjkl1")
    errors = erun.collection_invariant_errors([first, second])
    check(any(x.startswith("RUN_SLOT_CONCURRENT") for x in errors),
          "two in-flight attempts cannot own one logical slot")
    erun.transition_execution(first, "cancelled", note="never launched", now="t1")
    check(not any(x.startswith("RUN_SLOT_CONCURRENT")
                  for x in erun.collection_invariant_errors([first, second])),
          "terminal predecessor releases the logical slot")


def main() -> None:
    identity_checks()
    independent_axis_checks()
    recovery_checks()
    invariant_checks()
    print(f"V9.2 RUN UNIT GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
