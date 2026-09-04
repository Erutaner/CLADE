"""Pure recovery planning helpers for the v10 control-plane boundary.

This module deliberately does not mutate engine state, write files, schedule
tasks, or launch/cancel external work.  It answers the questions that must be
settled *before* a recovery transition is allowed:

* what a project/round/lane/node/run scope contains;
* whether a subject is covered by an active hold;
* which nodes are hard downstream consumers of a node;
* which append-only knowledge records and tasks were softly exposed;
* which RUNs still represent unresolved or irreversible operational effects;
* whether the active heads still match a previously rendered plan; and
* which recovery actions are legal at a given authority boundary.

The scheduler/CLI integration is intentionally kept elsewhere.  In
particular, this is not a generic rollback or transaction framework.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any

import erun


SCOPE_KINDS = ("project", "round", "lane", "node", "run")
BOUNDARIES = (
    "bootstrap", "lane", "spec", "implementation", "stage_evidence",
    "evaluation", "conclusion", "frontier", "round",
)
ACTIONS = (
    "repair", "reopen", "replace", "fork_lane", "fork_node",
    "fork_project", "compensate", "recompute", "annotate",
)

# This is a fail-closed capability table, not an instruction to execute every
# listed action. ``classify_boundary_action`` selects the narrow action set for
# one case; integrations may reject a plan that asks for anything else.
BOUNDARY_ACTIONS: dict[str, frozenset[str]] = {
    "bootstrap": frozenset({"repair", "reopen", "fork_project", "compensate"}),
    "lane": frozenset({"repair", "reopen", "replace", "fork_lane", "fork_node", "compensate"}),
    "spec": frozenset({"repair", "fork_node", "fork_project", "compensate"}),
    "implementation": frozenset({"repair", "reopen", "replace", "fork_node", "compensate"}),
    "stage_evidence": frozenset({"repair", "reopen", "replace", "fork_node", "compensate"}),
    "evaluation": frozenset({"repair", "reopen", "replace", "fork_node", "compensate"}),
    "conclusion": frozenset({"repair", "reopen", "replace", "fork_node", "compensate"}),
    "frontier": frozenset({"recompute"}),
    "round": frozenset({"annotate"}),
}

_SEAL_FIELDS = (
    "diagnosis_seal", "core_palette_seal", "program_seal", "tournament_seal",
    "problem_seal", "theory_draft_seal", "theory_seal", "idea_seal",
    "review_seal", "spec_seal", "implementation_seal", "workflow_reuse_seal", "fidelity_seal",
    "ablation_fidelity_seal", "metric_bridge_seal", "resource_receipt_seal", "eval_seal",
    "conclusion_seal", "evidence_seal",
)


def _id_index(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(row.get("id")): row for row in rows if str(row.get("id") or "")}


def normalize_scope(scope: Mapping[str, Any] | str) -> dict[str, str | None]:
    """Return one canonical recovery/hold scope or raise ``ValueError``.

    String shorthand accepts ``"project"`` or ``"node:N012"``.  Mapping
    input uses ``{"kind": "node", "id": "N012"}``.
    """
    if isinstance(scope, str):
        raw = scope.strip()
        if ":" in raw:
            kind, id_ = raw.split(":", 1)
        else:
            kind, id_ = raw, ""
    elif isinstance(scope, Mapping):
        kind = str(scope.get("kind") or "").strip()
        id_ = str(scope.get("id") or "").strip()
    else:
        raise ValueError("recovery scope must be a mapping or string")
    if kind not in SCOPE_KINDS:
        raise ValueError(f"unsupported recovery scope {kind!r}; expected one of {SCOPE_KINDS}")
    if kind == "project":
        if id_:
            raise ValueError("project scope must not carry an id")
        return {"kind": "project", "id": None}
    if not id_:
        raise ValueError(f"{kind} scope needs an id")
    return {"kind": kind, "id": id_}


def scope_members(scope: Mapping[str, Any] | str, state: Mapping[str, Any],
                  graph: Mapping[str, Any]) -> dict[str, list[str]]:
    """Resolve a scope to deterministic lane/node/run membership.

    A lane includes all graph nodes historically carrying that lane id, not
    only the lane's mutable current ``node`` pointer.  A node/run scope includes
    its owning lane for hold presentation but never pulls in sibling nodes.
    """
    sc = normalize_scope(scope)
    lanes = list(state.get("lanes") or [])
    nodes = list(graph.get("nodes") or [])
    runs = list(state.get("runs") or [])
    lane_idx, node_idx, run_idx = _id_index(lanes), _id_index(nodes), _id_index(runs)
    lane_ids: set[str] = set()
    node_ids: set[str] = set()
    run_ids: set[str] = set()

    kind, id_ = str(sc["kind"]), sc["id"]
    if kind == "project":
        lane_ids.update(lane_idx)
        node_ids.update(node_idx)
        run_ids.update(run_idx)
    elif kind == "round":
        known_rounds = {str(row.get("id")) for row in state.get("rounds") or []
                        if isinstance(row, Mapping) and str(row.get("id") or "")}
        known_rounds.update(str(row.get("round")) for row in lanes
                            if str(row.get("round") or ""))
        if state.get("current_round"):
            known_rounds.add(str(state.get("current_round")))
        if str(id_) not in known_rounds:
            raise ValueError(f"unknown round {id_}")
        lane_ids.update(str(row.get("id")) for row in lanes if row.get("round") == id_)
        node_ids.update(str(row.get("id")) for row in nodes if row.get("round") == id_)
        run_ids.update(str(row.get("id")) for row in runs if str(row.get("node") or "") in node_ids)
    elif kind == "lane":
        if str(id_) not in lane_idx:
            raise ValueError(f"unknown lane {id_}")
        lane_ids.add(str(id_))
        node_ids.update(str(row.get("id")) for row in nodes if row.get("lane") == id_)
        current = str(lane_idx[str(id_)].get("node") or "")
        if current:
            node_ids.add(current)
        run_ids.update(str(row.get("id")) for row in runs if str(row.get("node") or "") in node_ids)
    elif kind == "node":
        if str(id_) not in node_idx:
            raise ValueError(f"unknown node {id_}")
        node_ids.add(str(id_))
        lane = str(node_idx[str(id_)].get("lane") or "")
        if lane:
            lane_ids.add(lane)
        run_ids.update(str(row.get("id")) for row in runs if row.get("node") == id_)
    elif kind == "run":
        if str(id_) not in run_idx:
            raise ValueError(f"unknown run {id_}")
        run_ids.add(str(id_))
        node = str(run_idx[str(id_)].get("node") or "")
        if node:
            node_ids.add(node)
            lane = str((node_idx.get(node) or {}).get("lane") or "")
            if lane:
                lane_ids.add(lane)
    return {
        "lanes": sorted(x for x in lane_ids if x),
        "nodes": sorted(x for x in node_ids if x),
        "runs": sorted(x for x in run_ids if x),
    }


def subject_in_scope(scope: Mapping[str, Any] | str, state: Mapping[str, Any],
                     graph: Mapping[str, Any], *, lane: str | None = None,
                     node: str | None = None, run: str | None = None,
                     round_: str | None = None) -> bool:
    """Whether any declared subject identity belongs to ``scope``."""
    sc = normalize_scope(scope)
    kind = str(sc["kind"])
    if kind == "project":
        return True
    members = scope_members(sc, state, graph)
    if kind == "round":
        return bool(round_ == sc["id"]
                    or (lane and lane in members["lanes"])
                    or (node and node in members["nodes"])
                    or (run and run in members["runs"]))
    if kind == "lane":
        return bool((lane and lane == sc["id"])
                    or (node and node in members["nodes"])
                    or (run and run in members["runs"]))
    if kind == "node":
        # scope_members carries the owning lane for display and impact plans;
        # it must not make a node hold cover every sibling in that lane.
        return bool((node and node == sc["id"])
                    or (run and run in members["runs"]))
    if kind == "run":
        # A RUN repair brakes its owning node authority, but not its lane.
        return bool((run and run == sc["id"])
                    or (node and node in members["nodes"]))
    return False


def hold_covers_subject(hold: Mapping[str, Any], state: Mapping[str, Any],
                        graph: Mapping[str, Any], *, lane: str | None = None,
                        node: str | None = None, run: str | None = None,
                        round_: str | None = None) -> bool:
    """Apply one hold's base scope plus its frozen impact expansion.

    Recovery plans may expand a narrow target to already-exposed downstream
    consumers.  The expansion is stored in ``hold.members`` so the reviewed
    brake is stable even while facts continue to arrive.  A round-level task
    is covered when any frozen member belongs to that round; this is the one
    rule used both when pausing and releasing (not an ad-hoc close-round case).
    """
    if subject_in_scope(hold.get("scope") or {}, state, graph,
                        lane=lane, node=node, run=run, round_=round_):
        return True
    # ``members`` is the descriptive owner closure (node -> owning lane, run
    # -> owning node) and must never widen a hold.  Only a recovery planner's
    # explicit impact expansion adds coverage beyond subject_in_scope.
    expanded = hold.get("expanded_members") or {}
    if lane and lane in set(str(x) for x in expanded.get("lanes") or []):
        return True
    if node and node in set(str(x) for x in expanded.get("nodes") or []):
        return True
    if run and run in set(str(x) for x in expanded.get("runs") or []):
        return True
    if round_ and not any((lane, node, run)):
        members = hold.get("members") or {}
        member_nodes = (set(str(x) for x in members.get("nodes") or []) |
                        set(str(x) for x in expanded.get("nodes") or []))
        member_lanes = (set(str(x) for x in members.get("lanes") or []) |
                        set(str(x) for x in expanded.get("lanes") or []))
        if any(str(row.get("round") or "") == str(round_) and
               str(row.get("id") or "") in member_nodes
               for row in graph.get("nodes") or []):
            return True
        if any(str(row.get("round") or "") == str(round_) and
               str(row.get("id") or "") in member_lanes
               for row in state.get("lanes") or []):
            return True
    return False


def active_holds_for_subject(state: Mapping[str, Any], graph: Mapping[str, Any], *,
                             lane: str | None = None, node: str | None = None,
                             run: str | None = None, round_: str | None = None) -> list[str]:
    """Return sorted ids of active holds covering a task/gate/RUN subject."""
    out: list[str] = []
    for hold in state.get("holds") or []:
        if not isinstance(hold, Mapping) or hold.get("status") != "active":
            continue
        covered = hold_covers_subject(hold, state, graph,
                                      lane=lane, node=node, run=run, round_=round_)
        if not covered:
            continue
        # A malformed active hold is corrupt control state.  Fail closed: the
        # brake must never be silently dropped so work can proceed past it.
        if not str(hold.get("id") or ""):
            raise ValueError(
                "active hold covering this subject has no id; control state is "
                "corrupt - run 'evo doctor' before continuing")
        out.append(str(hold["id"]))
    return sorted(out)


def is_held(state: Mapping[str, Any], graph: Mapping[str, Any], **subject: Any) -> bool:
    return bool(active_holds_for_subject(state, graph, **subject))


def _artifact_consumers(specs: Mapping[str, Mapping[str, Any]]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for nid, spec in specs.items():
        stages = ((spec.get("workflow") or {}).get("stages") or []) \
            if isinstance(spec, Mapping) else []
        for stage in stages:
            for consume in (stage.get("consumes") or []) if isinstance(stage, Mapping) else []:
                aid = str((consume or {}).get("artifact") or "") \
                    if isinstance(consume, Mapping) else ""
                if aid:
                    out.setdefault(aid, set()).add(str(nid))
    return out


def _required_services(spec: Mapping[str, Any]) -> set[str]:
    out: set[str] = set()
    ev = spec.get("eval") or {}
    if isinstance(ev, Mapping):
        out.update(str(x) for x in ev.get("requires_services") or [] if str(x))
    stages = ((spec.get("workflow") or {}).get("stages") or [])
    for stage in stages:
        if isinstance(stage, Mapping):
            out.update(str(x) for x in stage.get("requires_services") or [] if str(x))
    return out


def hard_descendants(graph: Mapping[str, Any], registry: Mapping[str, Any],
                     specs: Mapping[str, Mapping[str, Any]],
                     roots: Iterable[str]) -> dict[str, Any]:
    """Compute the transitive hard-consumer closure of ``roots``.

    Edges cover graph ancestry/code ancestry, the frozen effect comparator,
    registered artifact consumption, and dynamic platform-service consumption.
    ``specs`` is an already-loaded ``node id -> NODE_SPEC`` mapping so this
    helper remains filesystem-free.
    """
    nodes = list(graph.get("nodes") or [])
    idx = _id_index(nodes)
    root_set = {str(x) for x in roots if str(x)}
    unknown = sorted(root_set - set(idx))
    if unknown:
        raise ValueError(f"unknown hard-dependency root node(s): {unknown}")

    edge_reasons: dict[tuple[str, str], set[str]] = {}

    def add(source: str, consumer: str, reason: str) -> None:
        if source and consumer and source != consumer:
            edge_reasons.setdefault((source, consumer), set()).add(reason)

    for node in nodes:
        nid = str(node.get("id") or "")
        for parent in node.get("parents") or []:
            add(str(parent), nid, "graph_parent")
        cp = str(node.get("code_parent") or "")
        if cp:
            add(cp, nid, "code_parent")
        # A candidate's effect verdict reads the sealed measurements and
        # resource receipt of this exact node.  It is therefore a hard
        # authority dependency even when it is neither a scientific nor code
        # parent (notably a root lane using the baseline comparator).
        comparator = str(node.get("effect_comparator_node") or "")
        if comparator:
            add(comparator, nid, "effect_comparator")

    consumers = _artifact_consumers(specs)
    for artifact in registry.get("artifacts") or []:
        aid = str((artifact or {}).get("id") or "")
        producer = str((artifact or {}).get("node") or "")
        for consumer in consumers.get(aid, set()):
            add(producer, consumer, f"artifact:{aid}")

    service_producers: dict[str, set[str]] = {}
    for node in nodes:
        if node.get("role") != "platform":
            continue
        # R9 (external audit r6): only a platform that actually REACHED
        # "enabled" creates hard dependency edges. A failed row still carrying
        # enabled_services made every consumer of the slug a phantom hard
        # descendant (nothing was ever scheduled under it), reclassifying an
        # in-place recovery as fork_node. A RETIRED-after-enabled platform is
        # different: consumers' sealed evidence WAS produced under its
        # authority, so recovery classification must keep those edges (the
        # scheduling-time liveness predicate in einfra stays strict - retired
        # platforms serve no new consumers; over-approximating here only
        # escalates in-place toward fork, the safe direction).
        if node.get("verdict") != "enabled":
            continue
        for service in node.get("enabled_services") or []:
            name = str((service or {}).get("name") or "") if isinstance(service, Mapping) else str(service)
            if name:
                service_producers.setdefault(name, set()).add(str(node.get("id") or ""))
    for consumer, spec in specs.items():
        for service in _required_services(spec):
            for producer in service_producers.get(service, set()):
                add(producer, str(consumer), f"service:{service}")

    adjacency: dict[str, set[str]] = {}
    for source, consumer in edge_reasons:
        adjacency.setdefault(source, set()).add(consumer)
    reached = set(root_set)
    queue = deque(sorted(root_set))
    while queue:
        source = queue.popleft()
        for consumer in sorted(adjacency.get(source, set())):
            if consumer not in reached:
                reached.add(consumer)
                queue.append(consumer)
    closure = reached - root_set
    edges = [
        {"source": source, "consumer": consumer,
         "reasons": sorted(edge_reasons[(source, consumer)])}
        for source, consumer in sorted(edge_reasons)
        if source in reached and consumer in reached
    ]
    return {"roots": sorted(root_set), "nodes": sorted(closure), "edges": edges}


def pending_authority_consumers(graph: Mapping[str, Any],
                                lanes: Iterable[Mapping[str, Any]],
                                tasks: Iterable[Mapping[str, Any]],
                                node_ids: Iterable[str], *,
                                registry: Mapping[str, Any] | None = None,
                                spec_reader: Any = None) -> dict[str, Any]:
    """Find not-yet-materialized consumers of active node authority.

    Graph ancestry only sees nodes that already exist.  A lane can already be
    committed to a parent, and a materialized task can already name a sealed
    result path, before that lane becomes a node.  Those are real consumers and
    must be included in a recovery plan/hold rather than silently continuing on
    the old authority.

    R11-009: a plan card that rendered the recovered node's SHARED ARTIFACT
    (non-parent consumption) and an open task whose on-disk NODE_SPEC draft
    already consumes such an artifact are consumers too - the card's
    artifact_receipts (recorded at materialization) and the draft's consumes
    list are the machine evidence. ``registry`` maps artifact ids to their
    producer; ``spec_reader(rel) -> dict|None`` reads a draft output.
    """
    affected = {str(x) for x in node_ids if str(x)}
    affected_artifacts: set[str] = set()
    artifact_producer: dict[str, str] = {}
    if registry is not None:
        for row in (registry.get("artifacts") or []):
            aid = str((row or {}).get("id") or "")
            producer = str((row or {}).get("node") or "")
            if aid and producer:
                artifact_producer[aid] = producer
                if producer in affected:
                    affected_artifacts.add(aid)
    idx = _id_index(graph.get("nodes") or [])
    head_paths: set[str] = set()
    for nid in affected:
        node = idx.get(nid) or {}
        for field in ("idea_doc", "spec", "result_doc", "outcome_path",
                      "eval_metrics_path", "eval_report_path", "resource_receipt_path"):
            value = str(node.get(field) or "")
            if value:
                head_paths.add(value)
        for seal_field in _SEAL_FIELDS:
            seal = node.get(seal_field)
            if not isinstance(seal, Mapping):
                continue
            for artifact in seal.get("artifacts") or []:
                path = str((artifact or {}).get("path") or "") if isinstance(artifact, Mapping) else ""
                if path:
                    head_paths.add(path)

    pending_lanes = sorted({str(lane.get("id")) for lane in lanes
                            if str(lane.get("id") or "") and
                            affected.intersection(str(x) for x in lane.get("parents") or []) and
                            str(lane.get("status") or "") not in {"done", "abandoned"}})
    task_rows: list[dict[str, Any]] = []
    for task in tasks:
        if str(task.get("status") or "") not in {"open", "paused", "stuck"}:
            continue
        render = task.get("_render") or {}
        raw_inputs = render.get("inputs") or [] if isinstance(render, Mapping) else []
        paths = {str(row[0]) for row in raw_inputs
                 if isinstance(row, (list, tuple)) and row and str(row[0] or "")}
        subject = task.get("subject") or {}
        lane = str(subject.get("lane") or "") if isinstance(subject, Mapping) else ""
        node = str(subject.get("node") or "") if isinstance(subject, Mapping) else ""
        reasons: list[str] = []
        if paths & head_paths:
            reasons.append("active_head_path")
        if lane and lane in pending_lanes:
            reasons.append("pending_parent_lane")
        if node and node in affected:
            reasons.append("affected_node")
        if str(task.get("type") or "") in {"open_round", "close_round"}:
            reasons.append("global_frontier_projection")
        receipts = (task.get("consumed_context") or {}).get("artifact_receipts") \
            if isinstance(task.get("consumed_context"), Mapping) else None
        if isinstance(receipts, Mapping):
            for aid, receipt in receipts.items():
                producer = str((receipt or {}).get("node") or "") \
                    if isinstance(receipt, Mapping) else ""
                if producer in affected or str(aid) in affected_artifacts:
                    reasons.append("shared_artifact_receipt")
                    break
        if spec_reader is not None and "shared_artifact_receipt" not in reasons:
            for out in (task.get("outputs") or []):
                rel = str(out or "")
                if not rel.endswith("NODE_SPEC.json"):
                    continue
                try:
                    draft = spec_reader(rel)
                except (Exception, SystemExit):
                    # A torn/half-written draft cannot prove it does NOT
                    # consume the recovered authority - fail closed: count the
                    # task as a consumer instead of letting the unreadable
                    # bytes wedge the whole recovery-planning command.
                    reasons.append("output_draft_unreadable")
                    break
                if not isinstance(draft, Mapping):
                    continue
                consumed: set[str] = set()
                workflow = draft.get("workflow") if isinstance(draft.get("workflow"), Mapping) else {}
                for stage in (workflow.get("stages") or []):
                    if not isinstance(stage, Mapping):
                        continue
                    for c in (stage.get("consumes") or []):
                        if isinstance(c, Mapping) and str(c.get("artifact") or ""):
                            consumed.add(str(c["artifact"]))
                if consumed & affected_artifacts or \
                        any(artifact_producer.get(a) in affected for a in consumed):
                    reasons.append("output_draft_consumes")
                    break
        if reasons:
            task_rows.append({"task": str(task.get("id") or ""),
                              "lane": lane or None, "node": node or None,
                              "round": (str(subject.get("round") or "") or None)
                              if isinstance(subject, Mapping) else None,
                              "reasons": sorted(set(reasons))})
    task_rows.sort(key=lambda row: row["task"])
    return {"lanes": pending_lanes, "tasks": task_rows,
            "head_paths": sorted(head_paths)}


def _task_refs(task: Mapping[str, Any]) -> set[str]:
    refs: set[str] = set()
    candidates: list[Any] = [task.get("input_refs"), task.get("knowledge_refs")]
    render = task.get("_render") or {}
    if isinstance(render, Mapping):
        candidates.extend((render.get("input_refs"), render.get("knowledge_refs")))
    consumed = task.get("consumed_context") or {}
    if isinstance(consumed, Mapping):
        candidates.extend((consumed.get("lesson_ids"), consumed.get("observation_ids")))
    for values in candidates:
        sequence = [values] if isinstance(values, (str, Mapping)) else (values or [])
        for value in sequence:
            if isinstance(value, Mapping):
                ref = str(value.get("id") or value.get("ref") or "")
            else:
                ref = str(value or "")
            if ref:
                refs.add(ref)
    return refs


def soft_knowledge_impact(node_ids: Iterable[str],
                          ledgers: Mapping[str, Iterable[Mapping[str, Any]]],
                          tasks: Iterable[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Return knowledge records produced by nodes and explicit task exposure.

    ``ledgers`` may contain lessons, observations, evidence, collision audits,
    or future typed ledgers.  A row is source-bound when its ``node`` or
    ``source_node`` names a target node.  Exposure is deliberately limited to
    explicit ``input_refs``/``knowledge_refs``; this helper does not pretend a
    prose bundle substring proves causal dependence.
    """
    targets = {str(x) for x in node_ids if str(x)}
    refs: set[str] = set()
    records: list[dict[str, str]] = []
    for ledger_name, rows in sorted(ledgers.items()):
        for row in rows:
            source_nodes = {str(row.get("node") or ""), str(row.get("source_node") or "")}
            extra_nodes = row.get("nodes") or []
            if isinstance(extra_nodes, (list, tuple, set, frozenset)):
                source_nodes.update(str(x) for x in extra_nodes if str(x))
            if not (targets & source_nodes):
                continue
            ref = str(row.get("id") or "")
            if ref:
                refs.add(ref)
                records.append({"ledger": str(ledger_name), "id": ref,
                                "node": sorted(targets & source_nodes)[0]})
    exposures: list[dict[str, Any]] = []
    for task in tasks:
        seen = sorted(refs & _task_refs(task))
        if seen:
            exposures.append({"task": str(task.get("id") or ""), "refs": seen,
                              "status": str(task.get("status") or "")})
    records.sort(key=lambda row: (row["ledger"], row["id"], row["node"]))
    exposures.sort(key=lambda row: row["task"])
    return {"refs": sorted(refs), "records": records, "task_exposures": exposures}


def operational_run_impact(state: Mapping[str, Any], *,
                           node_ids: Iterable[str] = (),
                           run_ids: Iterable[str] = ()) -> dict[str, Any]:
    """Summarize unresolved and irreversible RUN effects for a recovery plan."""
    wanted_nodes = {str(x) for x in node_ids if str(x)}
    wanted_runs = {str(x) for x in run_ids if str(x)}
    selected: list[Mapping[str, Any]] = []
    for run in state.get("runs") or []:
        rid, nid = str(run.get("id") or ""), str(run.get("node") or "")
        if (wanted_runs and rid in wanted_runs) or (wanted_nodes and nid in wanted_nodes) \
                or (not wanted_runs and not wanted_nodes):
            selected.append(run)
    rows: list[dict[str, Any]] = []
    unresolved: list[str] = []
    external: list[str] = []
    evidence_pending: list[str] = []
    for run in sorted(selected, key=lambda row: str(row.get("id") or "")):
        rid = str(run.get("id") or "")
        status = str(run.get("status") or "")
        ev_status = str(run.get("evidence_status") or "pending")
        reservation = dict(run.get("resource_reservation") or {})
        usage = dict(run.get("resource_usage") or {})
        confirmed_unlaunched = bool(
            run.get("confirmed_not_launched")
            or run.get("resource_charge_basis") == "confirmed_unlaunched")
        has_external = not confirmed_unlaunched and bool(
            run.get("job") or run.get("resource_accounted") or usage
            or status in {"launch_unknown", "running", "finished", "failed", "cancelled"})
        is_unresolved = status in erun._IN_FLIGHT
        # Deliberately narrower than erun.needs_reconciliation: only a
        # SUCCESSFUL run with unreconciled evidence blocks an authority change.
        # A failed run's evidence legitimately stays pending forever (it routes
        # through fix/retry, not reconciliation); counting it here would let
        # every historical failure block recovery planning permanently.
        is_pending = status == "finished" and ev_status in {"pending", "incomplete", "invalid"}
        if is_unresolved:
            unresolved.append(rid)
        if has_external:
            external.append(rid)
        if is_pending:
            evidence_pending.append(rid)
        rows.append({
            "id": rid, "node": str(run.get("node") or ""),
            "status": status, "evidence_status": ev_status,
            "job": run.get("job"), "slot": {
                "kind": run.get("kind"), "replica_index": run.get("replica_index"),
                "stage_index": run.get("stage_index")},
            "reservation": reservation, "usage": usage,
            "resource_accounted": bool(run.get("resource_accounted")),
            "unresolved": is_unresolved, "has_external_effect": has_external,
        })
    return {
        "runs": rows,
        "unresolved": sorted(unresolved),
        "evidence_pending": sorted(evidence_pending),
        "external_effects": sorted(external),
        "blocks_authority_change": bool(unresolved or evidence_pending),
        "requires_compensation": bool(external),
    }


def _canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("recovery plans cannot contain NaN or infinity")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("recovery plan object keys must be strings")
        return {key: _canonicalize(item) for key, item in value.items()
                if key != "plan_digest"}
    if isinstance(value, (list, tuple)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        normalized = [_canonicalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(
            item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    raise ValueError(f"recovery plan contains non-JSON value {type(value).__name__}")


def canonical_plan_bytes(plan: Mapping[str, Any]) -> bytes:
    """Canonical JSON bytes, excluding the self-referential plan_digest."""
    normalized = _canonicalize(plan)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def plan_digest(plan: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


def _seal_digests(owner: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for field in _SEAL_FIELDS:
        seal = owner.get(field)
        if isinstance(seal, Mapping) and str(seal.get("digest") or ""):
            out[field] = str(seal["digest"])
    return out


def capture_head_preconditions(scope: Mapping[str, Any] | str,
                               state: Mapping[str, Any], graph: Mapping[str, Any],
                               registry: Mapping[str, Any]) -> dict[str, Any]:
    """Capture only authority selectors that must remain stable before apply."""
    sc = normalize_scope(scope)
    members = scope_members(sc, state, graph)
    lanes = _id_index(state.get("lanes") or [])
    nodes = _id_index(graph.get("nodes") or [])
    runs = _id_index(state.get("runs") or [])
    artifacts = _id_index(registry.get("artifacts") or [])
    out: dict[str, Any] = {"scope": sc, "members": members, "lanes": {},
                           "nodes": {}, "runs": {}, "artifacts": {}}
    if sc["kind"] == "project":
        canary = state.get("infra_canary") or {}
        out["project"] = {
            "phase": state.get("phase"),
            "config_frozen": bool(state.get("config_frozen")),
            "bootstrap_contract_confirmed": bool(state.get("bootstrap_contract_confirmed")),
            "bootstrap_contract_digest": state.get("bootstrap_contract_digest"),
            "bootstrap_infra_facts_digest": state.get("bootstrap_infra_facts_digest"),
            "infra_gate": state.get("infra_gate"),
            "infra_canary_status": canary.get("status") if isinstance(canary, Mapping) else None,
            "infra_canary_receipt": canary.get("receipt") if isinstance(canary, Mapping) else None,
        }
    for lid in members["lanes"]:
        lane = lanes.get(lid) or {}
        out["lanes"][lid] = {
            "status": lane.get("status"), "node": lane.get("node"),
            "idea": lane.get("idea"), "seals": _seal_digests(lane),
        }
    for nid in members["nodes"]:
        node = nodes.get(nid) or {}
        out["nodes"][nid] = {
            "status": node.get("status"), "verdict": node.get("verdict"),
            "retire_reason": node.get("retire_reason"),
            "evidence_heads": _canonicalize(node.get("evidence_heads") or {}),
            "seals": _seal_digests(node),
        }
    for rid in members["runs"]:
        run = runs.get(rid) or {}
        out["runs"][rid] = {
            "node": run.get("node"), "status": run.get("status"),
            "evidence_status": run.get("evidence_status"),
            "superseded": bool(run.get("superseded")),
            "job": run.get("job"), "seals": _seal_digests(run),
        }
    node_set = set(members["nodes"])
    for aid, artifact in artifacts.items():
        if str(artifact.get("node") or "") in node_set:
            out["artifacts"][aid] = {
                "node": artifact.get("node"), "status": artifact.get("status"),
                "uri": artifact.get("uri"), "producer_run": artifact.get("producer_run"),
            }
    return out


def _first_mismatch(expected: Any, actual: Any, path: str = "heads") -> str | None:
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return f"{path}: expected object, got {type(actual).__name__}"
        if set(expected) != set(actual):
            missing, extra = sorted(set(expected) - set(actual)), sorted(set(actual) - set(expected))
            return f"{path}: key set changed (missing={missing}, extra={extra})"
        for key in sorted(expected):
            mismatch = _first_mismatch(expected[key], actual[key], f"{path}.{key}")
            if mismatch:
                return mismatch
        return None
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(expected) != len(actual):
            return f"{path}: list changed"
        for i, value in enumerate(expected):
            mismatch = _first_mismatch(value, actual[i], f"{path}[{i}]")
            if mismatch:
                return mismatch
        return None
    return None if expected == actual else f"{path}: expected {expected!r}, got {actual!r}"


def verify_head_preconditions(expected: Mapping[str, Any], state: Mapping[str, Any],
                              graph: Mapping[str, Any], registry: Mapping[str, Any]) -> list[str]:
    """Fail closed when a planned scope gained/lost/changed an authority head."""
    scope = expected.get("scope") if isinstance(expected, Mapping) else None
    if not isinstance(scope, Mapping):
        return ["RECOVERY_HEAD_SCOPE: expected head snapshot has no valid scope"]
    try:
        actual = capture_head_preconditions(scope, state, graph, registry)
    except ValueError as exc:
        return [f"RECOVERY_HEAD_SCOPE: {exc}"]
    mismatch = _first_mismatch(_canonicalize(expected), actual)
    return [] if mismatch is None else [f"RECOVERY_HEAD_CHANGED: {mismatch}"]


def supported_actions(boundary: str) -> frozenset[str]:
    if boundary not in BOUNDARY_ACTIONS:
        raise ValueError(f"unsupported recovery boundary {boundary!r}; expected one of {BOUNDARIES}")
    return BOUNDARY_ACTIONS[boundary]


def classify_boundary_action(boundary: str, *, changes_authority: bool,
                             same_contract: bool = True,
                             evidence_incomplete: bool = False,
                             cross_owner_consumers: bool = False,
                             external_effects: bool = False,
                             foundation_consumed: bool = False,
                             repair_scope: str = "workflow") -> dict[str, Any]:
    """Classify one recovery without inventing an arbitrary rollback.

    ``cross_owner_consumers`` means a different node/lane consumed the active
    authority.  Local suffixes are replayable; cross-owner consumers require a
    fork/quarantine decision.  The result is descriptive and has no side
    effects.
    """
    allowed = supported_actions(boundary)
    actions: list[str] = []
    replay_from: str | None = None
    reason: str

    if boundary == "frontier":
        actions, reason = ["recompute"], "frontier is a derived view"
    elif boundary == "round":
        actions, reason = ["annotate"], "closed-round history is annotated, not rewritten"
    elif not changes_authority:
        actions, reason = ["repair"], "active scientific bytes and meaning stay unchanged"
    elif evidence_incomplete and same_contract and boundary in {"stage_evidence", "evaluation"}:
        actions, reason = ["repair"], "complete the same execution attempt before selecting evidence"
    elif boundary == "bootstrap":
        if foundation_consumed or not same_contract:
            actions, reason = ["fork_project"], "a consumed foundational contract defines a new experiment world"
        else:
            actions, reason = ["reopen"], "bootstrap suffix is still unconsumed"
            replay_from = "bootstrap"
    elif not same_contract:
        if boundary == "lane":
            actions, reason = ["fork_lane"], "the scientific lane contract changed"
        else:
            actions, reason = ["fork_node"], "the accepted node/experiment contract changed"
    elif boundary == "spec":
        actions, reason = ["fork_node"], "an accepted NODE_SPEC identifies one experiment"
    elif cross_owner_consumers:
        if boundary == "lane":
            actions, reason = ["fork_lane"], "another owner consumed the accepted lane authority"
        else:
            actions, reason = ["fork_node"], "another owner consumed the accepted node authority"
    elif boundary == "lane":
        actions, replay_from, reason = ["reopen", "replace"], "lane", "replay the lane-local suffix"
    elif boundary == "implementation":
        replay_from = "evaluation" if repair_scope == "evaluation" else "workflow"
        actions, reason = ["replace", "reopen"], (
            "evaluation-only implementation revision preserves completed workflow evidence"
            if repair_scope == "evaluation" else
            "workflow implementation revision invalidates its node-local execution suffix")
    elif boundary == "stage_evidence":
        actions, replay_from, reason = ["replace", "reopen"], "stage_successor", \
            "replace the same-slot evidence and replay only its dependent suffix"
    elif boundary == "evaluation":
        actions, replay_from, reason = ["replace", "reopen"], "evaluation", \
            "raw authority is unchanged; redo evaluation and conclusion"
    elif boundary == "conclusion":
        actions, replay_from, reason = ["replace", "reopen"], "conclusion", \
            "redo interpretation from the same evaluation authority"
    else:
        # The exhaustive boundary table should make this unreachable.
        raise ValueError(f"no recovery classification for boundary {boundary!r}")

    if external_effects and "compensate" in allowed and "compensate" not in actions:
        actions.append("compensate")
    illegal = [action for action in actions if action not in allowed]
    if illegal:
        return {"supported": False, "boundary": boundary, "actions": actions,
                "replay_from": replay_from, "reason": reason,
                "errors": [f"boundary {boundary} does not support {action}" for action in illegal]}
    return {"supported": True, "boundary": boundary, "actions": actions,
            "replay_from": replay_from, "reason": reason, "errors": []}
