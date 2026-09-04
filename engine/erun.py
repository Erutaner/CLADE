"""Small, explicit state machine for external RUN attempts (v10).

A RUN carries three independent facts:

``status``
    What happened on the external execution surface.  This keeps the historical
    v9 field name, but no longer says anything about evidence validity.
``evidence_status``
    Whether the bytes needed to interpret that execution have been reconciled.
``adoption_status``
    Whether this attempt is allowed to advance the active node/workflow head.

Keeping those axes separate is the important invariant.  In particular, a
successful job with a missing probe is ``finished + incomplete + candidate``;
it must never be rewritten as a failed execution merely to trigger recovery.

The module deliberately works on JSON-compatible dictionaries.  It has no
store, scheduler, seal, or platform dependency, so callers can use it from the
scheduler, CLI, doctor, and focused tests without creating a second state owner.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, MutableMapping


EXECUTION_STATUSES = frozenset({
    "prepared",       # intent exists; no launch has been confirmed
    "launch_unknown", # a launch may have happened; reconcile before retrying
    "running",
    "finished",       # external execution succeeded, independently of evidence
    "failed",         # external execution failed
    "cancelled",      # cancellation/non-launch has been confirmed
})
TERMINAL_EXECUTION_STATUSES = frozenset({"finished", "failed", "cancelled"})

EVIDENCE_STATUSES = frozenset({
    "pending",     # not audited yet
    "incomplete",  # expected bytes are absent; same-RUN repair remains possible
    "invalid",     # supplied bytes do not satisfy the frozen contract
    "complete",    # accepted package, possibly including an explicit gap receipt
})

ADOPTION_STATUSES = frozenset({
    "candidate",   # not yet authoritative
    "adopted",     # advances/authorizes the active workflow head
    "quarantined", # factual attempt retained, but downstream use is blocked
    "superseded",  # immutable historical attempt; never active again
})

TERMINAL_EVIDENCE_DISPOSITIONS = frozenset({"irrecoverable_quarantined"})

_IN_FLIGHT = frozenset({"prepared", "launch_unknown", "running"})
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,160}$")


class RunError(ValueError):
    """Base class for RUN state/identity errors."""


class RunTransitionError(RunError):
    """Raised when a transition would rewrite external or authority history."""


class RunInvariantError(RunError):
    """Raised when a RUN record is internally inconsistent."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(prefix: str, payload: Mapping[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False)
    return f"{prefix}:v1:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"


def logical_slot_payload(*, node: str, kind: str, stage: str | None = None,
                         stage_index: int | None = None,
                         replica_index: int | None = None,
                         replica_seed: Any | None = None) -> dict[str, Any]:
    """Return the scientific workflow position shared by replacement attempts.

    The contract/implementation digest is intentionally *not* part of the slot:
    it identifies a revision within the same position.  Attempt numbering is
    scoped by both this slot and the execution-contract digest.
    """
    return {
        "node": str(node or ""),
        "kind": str(kind or ""),
        "stage": None if stage is None else str(stage),
        "stage_index": stage_index,
        "replica_index": replica_index,
        # JSON preserves the important distinction between integer 11 and
        # string "11"; bool is rejected by the invariant audit.
        "replica_seed": replica_seed,
    }


def logical_slot_key(*, node: str, kind: str, stage: str | None = None,
                     stage_index: int | None = None,
                     replica_index: int | None = None,
                     replica_seed: Any | None = None) -> str:
    return _digest("slot", logical_slot_payload(
        node=node, kind=kind, stage=stage, stage_index=stage_index,
        replica_index=replica_index, replica_seed=replica_seed))


def logical_slot_key_for(run: Mapping[str, Any]) -> str:
    return logical_slot_key(
        node=str(run.get("node") or ""), kind=str(run.get("kind") or ""),
        stage=run.get("stage"), stage_index=run.get("stage_index"),
        replica_index=run.get("replica_index"),
        replica_seed=run.get("replica_seed"))


def make_attempt_key(slot_key: str, contract_digest: str, attempt_no: int) -> str:
    if not str(slot_key or "") or not str(contract_digest or ""):
        raise RunInvariantError("attempt identity needs a logical slot and contract digest")
    if isinstance(attempt_no, bool) or not isinstance(attempt_no, int) or attempt_no < 1:
        raise RunInvariantError("attempt_no must be an integer >= 1")
    return _digest("attempt", {
        "logical_slot_key": str(slot_key),
        "contract_digest": str(contract_digest),
        "attempt_no": attempt_no,
    })


def new_attempt_token() -> str:
    """Opaque idempotency token shown before any external launch."""
    return "run_" + secrets.token_urlsafe(24)


def next_attempt_no(runs: Iterable[Mapping[str, Any]], *, slot_key: str,
                    contract_digest: str) -> int:
    """Return the next ordinal for one slot under one executable contract."""
    prior: list[int] = []
    for run in runs:
        actual_slot = str(run.get("logical_slot_key") or "")
        if not actual_slot:
            try:
                actual_slot = logical_slot_key_for(run)
            except (TypeError, ValueError):
                continue
        if actual_slot != slot_key or str(run.get("contract_digest") or "") != contract_digest:
            continue
        value = run.get("attempt_no")
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            prior.append(value)
    return max(prior, default=0) + 1


def initialize_run(run: MutableMapping[str, Any], *,
                   existing_runs: Iterable[Mapping[str, Any]] = (),
                   token: str | None = None, now: str | None = None) -> MutableMapping[str, Any]:
    """Add v10 identity/axis defaults to a newly allocated RUN dictionary."""
    timestamp = now or _utc_now()
    slot = logical_slot_key_for(run)
    contract = str(run.get("contract_digest") or "")
    number = run.get("attempt_no")
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        peers = [r for r in existing_runs if str(r.get("id") or "") != str(run.get("id") or "")]
        number = next_attempt_no(peers, slot_key=slot, contract_digest=contract)
    run["logical_slot_key"] = slot
    run["attempt_no"] = number
    run["attempt_key"] = make_attempt_key(slot, contract, number)
    run["attempt_token"] = str(run.get("attempt_token") or token or new_attempt_token())
    run.setdefault("status", "prepared")
    run.setdefault("evidence_status", "pending")
    run.setdefault("adoption_status", "candidate")
    run.setdefault("prepared_at", timestamp)
    run.setdefault("started_at", None)
    run.setdefault("ended_at", None)
    run.setdefault("job", None)
    return run


_EXECUTION_TRANSITIONS = {
    "prepared": frozenset({"launch_unknown", "running", "finished", "failed", "cancelled"}),
    "launch_unknown": frozenset({"running", "finished", "failed", "cancelled"}),
    "running": frozenset({"launch_unknown", "finished", "failed", "cancelled"}),
    "finished": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def transition_execution(run: MutableMapping[str, Any], target: str, *,
                         job: str | None = None, note: str | None = None,
                         now: str | None = None) -> MutableMapping[str, Any]:
    """Record an external-status observation without judging its evidence."""
    current = str(run.get("status") or "")
    target = str(target or "")
    if current not in EXECUTION_STATUSES or target not in EXECUTION_STATUSES:
        raise RunTransitionError(f"unknown execution transition {current!r} -> {target!r}")
    if current != target and target not in _EXECUTION_TRANSITIONS[current]:
        raise RunTransitionError(
            f"execution status is monotonic; {current!r} cannot become {target!r}; use a new RUN attempt")

    bound_job = str(run.get("job") or "").strip()
    supplied_job = str(job or "").strip()
    if bound_job and supplied_job and bound_job != supplied_job:
        raise RunTransitionError(
            f"RUN {run.get('id')} is already bound to job {bound_job!r}; a different job needs a new RUN")
    if supplied_job and target == "prepared":
        # invariant_errors rejects prepared+job; refuse to create that shape
        # instead of silently writing state the module's own auditor calls corrupt
        raise RunTransitionError("a prepared intent cannot carry a job id; bind on launch")
    if supplied_job and not bound_job:
        run["job"] = supplied_job
        bound_job = supplied_job
    if target == "running" and not bound_job:
        raise RunTransitionError("a running external RUN needs a stable job id/url")

    if current == target:
        if note is not None:
            run["note"] = str(note)
        return run

    timestamp = now or _utc_now()
    run["status"] = target
    run["execution_updated_at"] = timestamp
    if target == "running" and not run.get("started_at"):
        run["started_at"] = timestamp
    if target in TERMINAL_EXECUTION_STATUSES:
        run["ended_at"] = timestamp
    if note is not None:
        run["note"] = str(note)
    return run


def confirm_not_launched(run: MutableMapping[str, Any], *, note: str,
                         now: str | None = None) -> MutableMapping[str, Any]:
    """Resolve ``launch_unknown`` back to the same still-unspent intent.

    This is deliberately separate from :func:`transition_execution`: retrying a
    possibly launched command is unsafe unless the platform/operator has first
    confirmed that no external job exists.
    """
    if run.get("status") != "launch_unknown":
        raise RunTransitionError("only a launch_unknown RUN can be confirmed not launched")
    if str(run.get("job") or "").strip():
        raise RunTransitionError("a RUN already bound to a job cannot be declared unlaunched")
    if not str(note or "").strip():
        raise RunTransitionError("confirming non-launch needs an auditable note")
    timestamp = now or _utc_now()
    run["status"] = "prepared"
    run["launch_reconciled_at"] = timestamp
    run["execution_updated_at"] = timestamp
    run["note"] = str(note)
    return run


def transition_evidence(run: MutableMapping[str, Any], target: str, *,
                        note: str | None = None,
                        now: str | None = None) -> MutableMapping[str, Any]:
    """Update evidence independently of external success/failure.

    ``complete`` means the accepted evidence package is closed.  When an
    auxiliary observation is genuinely unavailable, callers should seal an
    explicit gap receipt and can then mark the package complete; downstream
    scientific logic may still compute an ``unclear`` mechanism status.
    """
    current = str(run.get("evidence_status") or "")
    target = str(target or "")
    if current not in EVIDENCE_STATUSES or target not in EVIDENCE_STATUSES:
        raise RunTransitionError(f"unknown evidence transition {current!r} -> {target!r}")
    if target == "pending" and current != "pending":
        raise RunTransitionError("accepted evidence cannot silently return to pending")
    if target != "pending" and run.get("status") not in TERMINAL_EXECUTION_STATUSES:
        raise RunTransitionError("non-pending evidence requires a terminal external observation")
    if current == "complete" and target != "complete" and run.get("adoption_status") == "adopted":
        raise RunTransitionError("quarantine an adopted RUN before reopening its evidence")
    if current == target:
        if note is not None:
            run["evidence_note"] = str(note)
        return run
    timestamp = now or _utc_now()
    run["evidence_status"] = target
    run["evidence_updated_at"] = timestamp
    if note is not None:
        run["evidence_note"] = str(note)
    return run


_ADOPTION_TRANSITIONS = {
    "candidate": frozenset({"adopted", "quarantined", "superseded"}),
    "adopted": frozenset({"quarantined", "superseded"}),
    "quarantined": frozenset({"candidate", "adopted", "superseded"}),
    "superseded": frozenset(),
}


def can_adopt(run: Mapping[str, Any]) -> bool:
    return run.get("status") == "finished" and run.get("evidence_status") == "complete" \
        and run.get("adoption_status") != "superseded"


def is_active_evidence(run: Mapping[str, Any]) -> bool:
    """Whether this RUN is the selected, usable evidence authority."""
    return run.get("adoption_status") == "adopted" and can_adopt(run)


def transition_adoption(run: MutableMapping[str, Any], target: str, *,
                        note: str | None = None,
                        now: str | None = None) -> MutableMapping[str, Any]:
    """Change only which factual attempt the active workflow is allowed to use."""
    current = str(run.get("adoption_status") or "")
    target = str(target or "")
    if current not in ADOPTION_STATUSES or target not in ADOPTION_STATUSES:
        raise RunTransitionError(f"unknown adoption transition {current!r} -> {target!r}")
    if current != target and target not in _ADOPTION_TRANSITIONS[current]:
        raise RunTransitionError(f"adoption status {current!r} cannot become {target!r}")
    if target == "adopted" and not can_adopt(run):
        raise RunTransitionError("only finished RUNs with complete evidence may be adopted")
    if target in {"quarantined", "superseded"} and current != target and not str(note or "").strip():
        raise RunTransitionError(f"{target} needs an auditable reason")
    if current == target:
        return run
    timestamp = now or _utc_now()
    run["adoption_status"] = target
    run["adoption_updated_at"] = timestamp
    if target == "adopted":
        run["adopted_at"] = timestamp
    elif target == "quarantined":
        run["quarantine_reason"] = str(note)
    elif target == "superseded":
        run["superseded_at"] = timestamp
        run["superseded_reason"] = str(note)
    if note is not None:
        run["adoption_note"] = str(note)
    return run


def is_terminal(run: Mapping[str, Any]) -> bool:
    return run.get("status") in TERMINAL_EXECUTION_STATUSES


def holds_external_slot(run: Mapping[str, Any]) -> bool:
    """True only when a job is running or may already have been launched."""
    return run.get("status") in {"launch_unknown", "running"}


def holds_reservation(run: Mapping[str, Any]) -> bool:
    """Retain the cap until execution cost can be accounted without guessing.

    R9 (external audit r6): the lifetime is decided by SETTLEMENT, not by a
    status guess. A terminal failed/cancelled RUN whose accounting was deferred
    (typically by a hold) used to fall out of both arms: its reservation
    vanished, a sibling launched into capacity that was still owed, and the
    later deferred settlement charged the full reserved cap - pushing the
    project past its user-confirmed hard limit with no gate. `confirmed
    not launched` still releases atomically, because that path charges
    ``usage={}`` and sets ``resource_accounted`` in the same transition."""
    if run.get("resource_accounted"):
        return False
    if run.get("status") in _IN_FLIGHT:
        return True
    if run.get("status") == "finished" and \
            run.get("evidence_status") in {"pending", "incomplete", "invalid"}:
        return True
    return bool(is_terminal(run) and (run.get("resource_reservation") or {}))


def needs_reconciliation(run: Mapping[str, Any]) -> bool:
    if run.get("adoption_status") == "superseded":
        return False
    if run.get("evidence_disposition") in TERMINAL_EVIDENCE_DISPOSITIONS:
        return False
    return run.get("status") == "launch_unknown" or (
        is_terminal(run) and run.get("evidence_status") in {"pending", "incomplete", "invalid"})


def invariant_errors(run: Mapping[str, Any]) -> list[str]:
    """Return doctor-friendly errors without mutating the RUN."""
    rid = str(run.get("id") or "?")
    errors: list[str] = []
    for field in ("id", "node", "kind", "contract_digest"):
        if not str(run.get(field) or "").strip():
            errors.append(f"RUN_FIELD: {rid} missing {field}")

    status = str(run.get("status") or "")
    evidence = str(run.get("evidence_status") or "")
    adoption = str(run.get("adoption_status") or "")
    if status not in EXECUTION_STATUSES:
        errors.append(f"RUN_STATUS: {rid} has invalid status {status!r}")
    if evidence not in EVIDENCE_STATUSES:
        errors.append(f"RUN_EVIDENCE_STATUS: {rid} has invalid evidence_status {evidence!r}")
    if adoption not in ADOPTION_STATUSES:
        errors.append(f"RUN_ADOPTION_STATUS: {rid} has invalid adoption_status {adoption!r}")
    disposition = str(run.get("evidence_disposition") or "")
    if disposition:
        if disposition not in TERMINAL_EVIDENCE_DISPOSITIONS:
            errors.append(f"RUN_EVIDENCE_DISPOSITION: {rid} has invalid terminal disposition {disposition!r}")
        elif status != "finished" or evidence not in {"incomplete", "invalid"} \
                or adoption != "quarantined" or not str(run.get("evidence_disposition_receipt") or ""):
            errors.append(f"RUN_EVIDENCE_DISPOSITION: {rid} irrecoverable evidence must be "
                          "finished + incomplete|invalid + quarantined with a receipt")

    stage_index, replica_index, replica_seed = (
        run.get("stage_index"), run.get("replica_index"), run.get("replica_seed"))
    if run.get("kind") == "stage":
        if not str(run.get("stage") or "").strip():
            errors.append(f"RUN_STAGE: {rid} stage RUN has no stage name")
        for field, value in (("stage_index", stage_index), ("replica_index", replica_index)):
            if field == "replica_index" and value is None and run.get("repeat_measure_attempt"):
                # R9-002: the bought-back repeat lane is not a preplanned
                # replica - it has a fresh seed but no replica ordinal
                continue
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"RUN_POSITION: {rid} {field} must be an integer >= 0")
        if isinstance(replica_seed, bool) or (
                replica_seed is not None and not isinstance(replica_seed, (int, str))):
            errors.append(f"RUN_SEED: {rid} replica_seed must be int|string|null, not {replica_seed!r}")

    expected_slot = ""
    try:
        expected_slot = logical_slot_key_for(run)
    except (TypeError, ValueError) as exc:
        errors.append(f"RUN_SLOT_SHAPE: {rid} cannot build logical slot: {exc}")
    actual_slot = str(run.get("logical_slot_key") or "")
    if not actual_slot:
        errors.append(f"RUN_SLOT_MISSING: {rid} has no logical_slot_key")
    elif expected_slot and actual_slot != expected_slot:
        errors.append(f"RUN_SLOT_DRIFT: {rid} logical slot no longer matches node/stage/replica identity")

    attempt_no = run.get("attempt_no")
    if isinstance(attempt_no, bool) or not isinstance(attempt_no, int) or attempt_no < 1:
        errors.append(f"RUN_ATTEMPT_NO: {rid} attempt_no must be an integer >= 1")
    elif actual_slot and str(run.get("contract_digest") or ""):
        expected_attempt = make_attempt_key(actual_slot, str(run["contract_digest"]), attempt_no)
        if str(run.get("attempt_key") or "") != expected_attempt:
            errors.append(f"RUN_ATTEMPT_KEY: {rid} attempt_key does not bind slot+contract+ordinal")
    token = str(run.get("attempt_token") or "")
    if not _TOKEN_RE.fullmatch(token):
        errors.append(f"RUN_ATTEMPT_TOKEN: {rid} needs a 20-160 character URL-safe token")

    job = str(run.get("job") or "").strip()
    if status == "prepared":
        if job or run.get("started_at") or run.get("ended_at"):
            errors.append(f"RUN_PREPARED_STATE: {rid} prepared intent cannot already have job/start/end facts")
    elif status == "running":
        if not job or not run.get("started_at") or run.get("ended_at"):
            errors.append(f"RUN_RUNNING_STATE: {rid} running needs job+started_at and no ended_at")
    elif status == "launch_unknown" and run.get("ended_at"):
        errors.append(f"RUN_UNKNOWN_STATE: {rid} launch_unknown cannot have ended_at")
    elif status in TERMINAL_EXECUTION_STATUSES and not run.get("ended_at"):
        errors.append(f"RUN_TERMINAL_STATE: {rid} terminal status {status!r} needs ended_at")

    if evidence != "pending" and status not in TERMINAL_EXECUTION_STATUSES:
        errors.append(f"RUN_EVIDENCE_BEFORE_TERMINAL: {rid} {evidence!r} evidence on {status!r} execution")
    if adoption == "adopted" and not can_adopt(run):
        errors.append(f"RUN_ADOPTION_INVALID: {rid} adopted without finished+complete evidence")
    if adoption == "superseded" and not run.get("superseded_at"):
        errors.append(f"RUN_SUPERSEDE_TIME: {rid} superseded without superseded_at")

    # Reject NaN/inf early if a caller accidentally uses attempt ordinals or
    # timestamps as numeric placeholders in hand-built fixtures.
    for field in ("attempt_no", "stage_index", "replica_index"):
        value = run.get(field)
        if isinstance(value, float) and not math.isfinite(value):
            errors.append(f"RUN_NONFINITE: {rid} {field} is non-finite")
    return errors


def assert_invariants(run: Mapping[str, Any]) -> None:
    errors = invariant_errors(run)
    if errors:
        raise RunInvariantError("; ".join(errors))


def collection_invariant_errors(runs: Iterable[Mapping[str, Any]]) -> list[str]:
    """Cross-RUN invariants: unique attempts and one active owner per slot."""
    rows = list(runs)
    errors = [error for run in rows for error in invariant_errors(run)]
    seen: dict[str, dict[Any, str]] = {
        "id": {}, "attempt_key": {}, "attempt_token": {},
    }
    ordinals: dict[tuple[str, str, int], str] = {}
    active: dict[str, list[str]] = {}
    adopted: dict[str, list[str]] = {}
    for run in rows:
        rid = str(run.get("id") or "?")
        for field in seen:
            value = str(run.get(field) or "")
            if not value:
                continue
            previous = seen[field].get(value)
            if previous is not None:
                errors.append(f"RUN_DUP_{field.upper()}: {rid} and {previous} share {value!r}")
            else:
                seen[field][value] = rid
        slot = str(run.get("logical_slot_key") or "")
        contract = str(run.get("contract_digest") or "")
        number = run.get("attempt_no")
        if slot and contract and isinstance(number, int) and not isinstance(number, bool):
            key = (slot, contract, number)
            previous = ordinals.get(key)
            if previous is not None:
                errors.append(f"RUN_DUP_ATTEMPT_ORDINAL: {rid} and {previous} share one slot/contract/ordinal")
            else:
                ordinals[key] = rid
        if slot and run.get("status") in _IN_FLIGHT:
            active.setdefault(slot, []).append(rid)
        if slot and run.get("adoption_status") == "adopted":
            adopted.setdefault(slot, []).append(rid)
    for slot, ids in active.items():
        if len(ids) > 1:
            errors.append(f"RUN_SLOT_CONCURRENT: slot {slot} has multiple in-flight attempts {ids}")
    for slot, ids in adopted.items():
        if len(ids) > 1:
            errors.append(f"RUN_SLOT_MULTI_ADOPTED: slot {slot} has multiple adopted attempts {ids}")
    return errors
