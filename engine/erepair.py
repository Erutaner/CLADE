"""Holds and recovery orchestration (v10): scoped brakes, two-phase
RecoveryCase planning/application, projection invalidation and honest
abandonment. Uses erecover primitives; owns the engine-side transitions.
"""

from __future__ import annotations

import json

import ebundle
import econfig
import egraph
import erecover
import erun
import eutil

stages_of = econfig.stages_of



class RepairMixin:
    def _pause_for_hold(self, hold: dict) -> None:
        for task in self.st.get("tasks", []):
            subject = task.get("subject") or {}
            if task.get("status") not in {"open", "paused"} or task.get("type") == "stage_watch":
                continue
            # F18: a recovery hold brakes exactly its reviewed impact set
            # (base scope + plan-frozen expanded_members). v9.2 short-circuited
            # every recovery hold into a global freeze, contradicting the
            # documented scoped-brake design and making the computed impact
            # set irrelevant for pausing.
            covered = erecover.hold_covers_subject(
                hold, self.st, self.g, lane=subject.get("lane"), node=subject.get("node"),
                run=subject.get("run"), round_=subject.get("round")) \
                or str(task.get("id") or "") in set(hold.get("consumer_task_ids") or [])
            if covered:
                task["status"] = "paused"
                if hold["id"] not in task.setdefault("held_by", []):
                    task["held_by"].append(hold["id"])
                task["updated_at"] = eutil.utc_now()
        consumer_ids = set(hold.get("consumer_task_ids") or [])
        for gate in self.st.get("gates", []):
            subject = gate.get("subject") or {}
            if gate.get("status") not in {"open", "paused"}:
                continue
            # A task-subject gate (escalation) belongs to the task's OWNER:
            # resolve it exactly like the apply-time cancel path does, or an
            # approved escalation reopens work inside the braked scope (G1).
            gate_lane, gate_node = subject.get("lane"), subject.get("node")
            gate_task_id = str(subject.get("task") or "")
            in_consumers = bool(gate_task_id and gate_task_id in consumer_ids)
            if gate_task_id and not (gate_lane or gate_node):
                owner = self.store.get_task(self.st, gate_task_id) or {}
                owner_subject = owner.get("subject") or {}
                gate_lane = owner_subject.get("lane")
                gate_node = owner_subject.get("node")
            if in_consumers or erecover.hold_covers_subject(
                    hold, self.st, self.g, lane=gate_lane, node=gate_node,
                    run=subject.get("run"), round_=subject.get("round")):
                gate["status"] = "paused"
                if hold["id"] not in gate.setdefault("held_by", []):
                    gate["held_by"].append(hold["id"])

    def create_hold(self, scope: str | dict, reason: str, *, actor: str = "user",
                    save: bool = True) -> dict:
        if not str(reason or "").strip():
            raise SystemExit("[evo] hold needs a concrete --reason")
        try:
            normalized = erecover.normalize_scope(scope)
            members = erecover.scope_members(normalized, self.st, self.g)
        except ValueError as exc:
            raise SystemExit(f"[evo] invalid hold scope: {exc}") from exc
        hid = self.store.next_id(self.st, "H")
        hold = {"id": hid, "scope": normalized, "members": members, "reason": str(reason),
                "status": "active", "created_at": eutil.utc_now(), "released_at": None}
        self.st.setdefault("holds", []).append(hold)
        self._pause_for_hold(hold)
        self.store.event(actor, "hold_created", hold=hid, scope=normalized, reason=reason,
                         members=members)
        if save:
            self.save()
        return hold

    def _release_hold_in_memory(self, hold: dict, *, note: str, actor: str) -> None:
        if hold.get("status") != "active":
            return
        hold["status"] = "released"
        hold["released_at"] = eutil.utc_now()
        hold["release_note"] = note
        for collection in (self.st.get("tasks", []), self.st.get("gates", [])):
            for record in collection:
                held_by = [str(x) for x in (record.get("held_by") or []) if str(x) != hold["id"]]
                if "held_by" in record:
                    record["held_by"] = held_by
                if record.get("status") != "paused" or held_by:
                    continue
                subject = record.get("subject") or {}
                other = erecover.active_holds_for_subject(
                    self.st, self.g, lane=subject.get("lane"), node=subject.get("node"),
                    run=subject.get("run"), round_=subject.get("round"))
                if not other:
                    # R7 audit: a round task whose round CLOSED while it was
                    # parked is stale forever - resurrecting a close_round
                    # accepted the same round twice (double closed rows,
                    # rounds_max double-count). Cancel it here, symmetrical
                    # with the scheduler pump's stale rules.
                    if "type" in record and record.get("type") in ("open_round", "close_round"):
                        rid = str(subject.get("round") or "")
                        if any(r.get("id") == rid and r.get("closed_at")
                               for r in self.st.get("rounds", [])):
                            record["status"] = "cancelled"
                            record.pop("queued_after_hold", None)
                            record.pop("_render", None)
                            record["cancel_reason"] = "round closed while this task was parked"
                            if "updated_at" in record:
                                record["updated_at"] = eutil.utc_now()
                            self.store.event("engine", "queued_task_cancelled",
                                             task=record.get("id"),
                                             reason="round closed while parked")
                            continue
                    # R9 (external audit r6): the engine invariant is AT MOST ONE
                    # open agent task (doctor: MULTI_OPEN_TASKS). While this one
                    # was paused a sibling legitimately became the open task, so
                    # blindly reopening produced two competing authority cards.
                    # Keep it queued; the scheduler reopens it when the floor
                    # is free.
                    if "type" in record and any(
                            t.get("status") == "open" and t is not record
                            for t in self.st.get("tasks", [])):
                        record["queued_after_hold"] = True
                        continue
                    # R8 audit: a launch card whose RUN went back to prepared
                    # while paused no longer holds its slot - reopening it
                    # without re-proving the slot let a single-slot platform
                    # accept two concurrent stages. Park it; the pump reopens
                    # it when a slot frees (submit re-proves it either way).
                    if "type" in record and record.get("type") == "stage_launch":
                        run_row = self.store.get_run(
                            self.st, str((record.get("subject") or {}).get("run") or ""))
                        if run_row is not None and not erun.holds_external_slot(run_row) \
                                and self._slots_free() <= 0:
                            record["queued_after_hold"] = True
                            continue
                    record["status"] = "open"
                    record.pop("queued_after_hold", None)
                    if "updated_at" in record:
                        record["updated_at"] = eutil.utc_now()
                    # R8 audit: a strategy-round consumer reopened after the
                    # world moved must not present its pre-pause bytes.
                    if "type" in record and record.get("type") == "close_round":
                        self._refresh_close_round_task(record)
        self.store.event(actor, "hold_released", hold=hold["id"], note=note)

    def release_hold(self, hold_id: str, note: str, *, actor: str = "user") -> dict:
        hold = next((row for row in self.st.get("holds", []) if row.get("id") == hold_id), None)
        if hold is None:
            raise SystemExit(f"[evo] no hold {hold_id}")
        if hold.get("status") != "active":
            raise SystemExit(f"[evo] hold {hold_id} is already {hold.get('status')}")
        if not str(note or "").strip():
            raise SystemExit("[evo] releasing a hold needs --note")
        if hold.get("recovery"):
            case = next((row for row in self.st.get("recoveries", [])
                         if row.get("id") == hold.get("recovery")), None)
            if case and case.get("status") in {"repairing", "replaying"}:
                raise SystemExit("[evo] an applied recovery owns this hold; finish it or use recover-abort")
            if case and case.get("status") in {"planned", "fork_required"}:
                case["status"] = "cancelled"
                case["completed_at"] = eutil.utc_now()
                case["result"] = f"recovery hold released without apply: {note}"
        self._release_hold_in_memory(hold, note=note, actor=actor)
        self.save()
        return hold

    def plan_recovery(self, target: str, boundary: str, reason: str, *,
                      repair_scope: str | None = None) -> dict:
        """Create a deterministic impact plan and a scoped brake; change no authority."""
        active_case = next((row for row in self.st.get("recoveries", [])
                            if row.get("status") in {"planned", "repairing", "replaying", "fork_required"}), None)
        if active_case is not None:
            raise SystemExit(f"[evo] recovery {active_case.get('id')} is still {active_case.get('status')}; "
                             "complete/abort it (or release its fork-required hold) before planning another")
        if boundary not in erecover.BOUNDARIES:
            raise SystemExit(f"[evo] unsupported recovery boundary {boundary!r}")
        if not str(reason or "").strip():
            raise SystemExit("[evo] recovery planning needs a concrete --reason")
        if boundary == "implementation":
            if repair_scope not in {"evaluation", "workflow"}:
                raise SystemExit("[evo] implementation recovery needs --repair-scope evaluation|workflow")
        elif repair_scope is not None:
            raise SystemExit("[evo] --repair-scope is only valid for implementation recovery")
        try:
            scope = erecover.normalize_scope(target)
            members = erecover.scope_members(scope, self.st, self.g)
        except ValueError as exc:
            raise SystemExit(f"[evo] invalid recovery target: {exc}") from exc
        required_scope = {
            "bootstrap": "project", "lane": "lane", "spec": "node",
            "implementation": "node", "evaluation": "node", "conclusion": "node",
            "stage_evidence": "run", "frontier": "project", "round": "round",
        }.get(boundary)
        if required_scope and scope["kind"] != required_scope:
            raise SystemExit(f"[evo] {boundary} recovery must target {required_scope}:..., "
                             f"not {scope['kind']}:...")
        node = self.node(members["nodes"][0]) if len(members["nodes"]) == 1 else None
        run = self.store.get_run(self.st, members["runs"][0]) if boundary == "stage_evidence" \
            and len(members["runs"]) == 1 else None
        if boundary == "implementation" and (node is None or not node.get("implementation_seal")):
            raise SystemExit("[evo] target has no active implementation authority to recover")
        if boundary == "implementation" and repair_scope == "evaluation":
            if node.get("role") == "platform":
                raise SystemExit("[evo] platform nodes have no evaluator implementation; "
                                 "use --repair-scope workflow")
            spec = self._spec(node)
            expected = len(stages_of(spec)) * econfig.workflow_replica_count(spec)
            completed = [run for run in self.st.get("runs", [])
                         if run.get("node") == node.get("id") and run.get("kind") == "stage"
                         and run.get("adoption_status") == "adopted" and run.get("status") == "finished"
                         and run.get("evidence_status") == "complete"]
            if expected and len(completed) != expected:
                raise SystemExit("[evo] evaluation-only implementation recovery needs a complete active "
                                 "workflow head; use --repair-scope workflow")
        if boundary == "evaluation":
            eval_run = self.store.get_run(self.st, str((node or {}).get("eval_run") or "")) or {}
            if node is None or not node.get("eval_seal") or node.get("scientific_stop") or \
                    eval_run.get("adoption_status") != "adopted" or eval_run.get("evidence_status") != "complete":
                raise SystemExit("[evo] target has no sealed standard-evaluation authority to recover")
        if boundary == "conclusion" and (node is None or not node.get("conclusion_seal")
                                           or node.get("status") != "concluded"):
            raise SystemExit("[evo] target has no active sealed conclusion to recover")
        if boundary == "stage_evidence" and (run is None or run.get("status") != "finished"):
            raise SystemExit("[evo] stage_evidence recovery needs one successfully finished RUN")
        if boundary == "stage_evidence" and (
                run.get("adoption_status") != "candidate"
                or run.get("evidence_status") not in {"incomplete", "invalid"}
                or node is None or node.get("status") != "evidence_pending"
                or node.get("evidence_pending_run") != run.get("id")):
            raise SystemExit("[evo] stage_evidence recovery is only for the active candidate RUN; "
                             "late quarantined history can use run-reconcile without changing node authority")
        if boundary == "round" and not any(
                row.get("id") == scope.get("id") and row.get("closed_at")
                for row in self.st.get("rounds", [])):
            raise SystemExit("[evo] round recovery annotates closed history only; the target round is not closed")
        rid = self.store.next_id(self.st, "REC")
        specs = self._spec_index()
        hard = (erecover.hard_descendants(self.g, self.reg, specs, members["nodes"])
                if members["nodes"] else {"roots": [], "nodes": [], "edges": []})
        pending = erecover.pending_authority_consumers(
            self.g, self.st.get("lanes", []), self.st.get("tasks", []),
            list(members["nodes"]) + list(hard.get("nodes") or []),
            registry=self.reg,
            spec_reader=lambda rel: eutil.read_json(eutil.rpath(self.store.repo, rel), None))
        soft = erecover.soft_knowledge_impact(
            members["nodes"],
            {"lessons": self.store.lessons(self.st), "observations": self.store.observations(self.st)},
            self.st.get("tasks", []))
        operational = erecover.operational_run_impact(
            self.st, node_ids=members["nodes"], run_ids=(members["runs"] if scope["kind"] == "run" else ()))
        if boundary in {"implementation", "evaluation", "conclusion"} and \
                operational.get("blocks_authority_change"):
            # R8 audit: the generic hint offered two verbs that are TYPE-
            # impossible for some blocking shapes (run-reconcile needs
            # finished; stage_evidence needs finished+incomplete). Name the
            # settling verb per RUN, or the operator loops between two
            # commands that both refuse.
            verbs: list[str] = []
            member_nodes = set(members.get("nodes") or [])
            for row in self.st.get("runs", []):
                if str(row.get("node") or "") not in member_nodes:
                    continue
                status = str(row.get("status") or "")
                rid_ = str(row.get("id") or "?")
                if status == "prepared":
                    verbs.append(f"{rid_}: prepared intent - settle it with 'evo run-update --run "
                                 f"{rid_} --status cancelled' (zero-usage settlement after "
                                 "confirm-not-launched), or launch it first")
                elif status == "launch_unknown":
                    verbs.append(f"{rid_}: launch unknown - 'evo run-bind' the found job or "
                                 f"'evo run-confirm-not-launched --run {rid_}'")
                elif status == "running":
                    verbs.append(f"{rid_}: still running - wait/settle it (watch card, run-update)")
                elif status == "finished" and str(row.get("evidence_status") or "") in (
                        "pending", "incomplete", "invalid"):
                    verbs.append(f"{rid_}: finished awaiting evidence - 'evo run-reconcile --run "
                                 f"{rid_} ...' or a run:{rid_} stage_evidence recovery")
            detail = ("; ".join(verbs) if verbs
                      else "use run-reconcile or a run:RUN stage_evidence recovery")
            raise SystemExit("[evo] reconcile unresolved RUN launch/evidence facts first - " + detail)
        evidence_incomplete = bool(operational.get("evidence_pending"))
        classification = erecover.classify_boundary_action(
            boundary, changes_authority=boundary not in {"frontier", "round"},
            same_contract=True, evidence_incomplete=evidence_incomplete,
            # Materialized but unsubmitted tasks are reversible projections:
            # pause and regenerate them.  Frozen lanes/nodes are authority
            # owners and therefore require a fork.
            cross_owner_consumers=bool(hard.get("nodes") or pending.get("lanes")),
            external_effects=bool(operational.get("requires_compensation")),
            foundation_consumed=bool(self.g.get("nodes") or self.st.get("phase") != "bootstrap"),
            repair_scope=str(repair_scope or "workflow"))
        # v9.2 intentionally implements only narrow suffix replay.  Earlier
        # contracts need a new authority world, not a planner promise whose
        # apply path does not exist.
        if boundary in {"bootstrap", "lane", "spec"}:
            fork = "fork_project" if boundary == "bootstrap" else \
                   "fork_lane" if boundary == "lane" else "fork_node"
            classification = {"supported": False, "boundary": boundary, "actions": [fork],
                              "replay_from": None,
                              "reason": f"v10 does not rewrite accepted {boundary} authority in place",
                              "errors": []}
        baseline_consumed = bool(
            node is not None and node.get("role") == "baseline" and (
                self.st.get("rounds")
                or self.st.get("lanes")
                or any(row.get("id") != node.get("id") for row in self.g.get("nodes", []))))
        if baseline_consumed and boundary in {
                "spec", "implementation", "evaluation", "conclusion", "stage_evidence"}:
            classification = {**classification, "supported": False, "actions": ["fork_project"],
                              "replay_from": None,
                              "reason": "a baseline consumed by round history defines the project's comparison world"}
        hold = self.create_hold(scope, f"recovery {rid}: {reason}", actor="user", save=False)
        hold["recovery"] = rid
        # R8 (external audit r5): the documented incident flow is "hold first,
        # then recover-plan" - but apply refuses ANY other active hold on the
        # impact, so the operator's own preliminary brake always blocked its
        # own recovery. A preliminary user hold with the exact same scope is
        # absorbed into the recovery-owned hold (brake continuity, one owner;
        # released AFTER the new hold is active so nothing paused reopens).
        for prior in self.st.get("holds", []):
            if prior is not hold and prior.get("status") == "active" \
                    and not prior.get("recovery") \
                    and (prior.get("scope") or {}) == (hold.get("scope") or {}):
                self._release_hold_in_memory(
                    prior, note=f"absorbed into recovery {rid}'s own hold {hold.get('id')}",
                    actor="engine")
        # Freeze already-exposed consumers into the same brake.  This is not a
        # transitive scheduler: it is the reviewed impact set at plan time.
        expanded_nodes = set(hard.get("nodes") or [])
        expanded_lanes = set(pending.get("lanes") or [])
        for impacted in self.g.get("nodes", []):
            if impacted.get("id") in expanded_nodes and impacted.get("lane"):
                expanded_lanes.add(str(impacted["lane"]))
        for task_impact in pending.get("tasks") or []:
            if task_impact.get("lane"):
                expanded_lanes.add(str(task_impact["lane"]))
            if task_impact.get("node"):
                expanded_nodes.add(str(task_impact["node"]))
        hold["expanded_members"] = {
            "nodes": sorted(expanded_nodes), "lanes": sorted(expanded_lanes),
            "runs": sorted({
            str(row.get("id")) for row in self.st.get("runs", [])
            if str(row.get("node") or "") in expanded_nodes and str(row.get("id") or "")}),
        }
        consumer_task_ids = {str(row.get("task") or "") for row in (pending.get("tasks") or [])}
        consumer_task_ids.update(str(row.get("task") or "")
                                 for row in (soft.get("task_exposures") or []))
        hold["consumer_task_ids"] = sorted(x for x in consumer_task_ids if x)
        self._pause_for_hold(hold)
        plan = {
            "schema_version": 1, "id": rid, "target": target, "scope": scope,
            "boundary": boundary, "reason": str(reason), "created_at": eutil.utc_now(),
            "repair_scope": repair_scope,
            "hold": hold["id"], "members": members,
            "classification": classification, "hard_impact": hard,
            "pending_authority_impact": pending,
            "soft_knowledge_impact": soft, "operational_impact": operational,
            "authority_kind": ("scientific_stop" if (node or {}).get("scientific_stop") else "standard"),
            "head_preconditions": erecover.capture_head_preconditions(scope, self.st, self.g, self.reg),
        }
        digest = erecover.plan_digest(plan)
        plan["plan_digest"] = digest
        plan_rel = f".evo/recoveries/{rid}/PLAN.json"
        eutil.write_json_atomic(eutil.rpath(self.store.repo, plan_rel), plan)
        case = {"id": rid, "target": target, "scope": scope, "boundary": boundary,
                "reason": str(reason), "status": "planned", "action": classification.get("actions"),
                "repair_scope": repair_scope,
                "hold": hold["id"], "plan_path": plan_rel, "plan_digest": digest,
                "created_at": plan["created_at"], "replay_from": classification.get("replay_from")}
        self.st.setdefault("recoveries", []).append(case)
        self.store.event("user", "recovery_planned", recovery=rid, target=target,
                         boundary=boundary, digest=digest, hold=hold["id"],
                         actions=classification.get("actions"), repair_scope=repair_scope)
        self.save()
        return case

    def _supersede_node_knowledge(self, node: dict, recovery: dict) -> None:
        latest = {str(row.get("ref")): row for row in self.st.get("knowledge_dispositions", [])
                  if str(row.get("ref") or "")}
        records = self.store.lessons(self.st) + self.store.observations(self.st)
        for row in records:
            ref = str(row.get("id") or "")
            if row.get("node") != node.get("id") or not ref or \
                    str((latest.get(ref) or {}).get("status") or "active") in {"superseded", "retracted"}:
                continue
            disposition = {"ref": ref, "status": "superseded", "node": node.get("id"),
                           "recovery": recovery.get("id"), "reason": recovery.get("reason"),
                           "source_conclusion_digest": row.get("source_conclusion_digest"),
                           "recorded_at": eutil.utc_now()}
            self.st.setdefault("knowledge_dispositions", []).append(disposition)
            latest[ref] = disposition
        # Infra dispositions are conclusion products exactly like lessons and
        # observations: the evidence a "transient" proof or a "fixed" playbook
        # row cited is being invalidated here, so the rows must not keep
        # suppressing knowledge duties (or routing a superseded fix into every
        # future bundle). The re-conclusion writes fresh ones.
        # R9 (external audit r6): staged, not eager - nothing lands if this
        # transition raises before save(). The flush itself runs just BEFORE
        # the state commit (fail-closed: an orphan retraction re-asks a
        # disposition; the reverse gap silently kept stale suppressors alive).
        self._stage_resolution_retraction(
            str(node.get("id") or ""), recovery=str(recovery.get("id") or ""),
            reason=str(recovery.get("reason") or "conclusion recovered"))

    # maintenance_parity/maintenance_gain are conclusion-derived settlements
    # like the rest of these fields: leaving them behind kept a stale
    # parity="met" - computed from evidence a recovery just invalidated - as
    # live state.  Every consumer today re-reads them only behind a
    # status=="concluded" guard, but "fail closed" must hold as STATE, not as
    # a property of who happens to read it.  Re-conclusion recomputes both.
    def _clear_conclusion_projection(self, node: dict) -> None:
        for field in ("verdict", "checkpoint", "mechanism_status", "prediction_stats",
                      "ablation_result", "effect_contract_status", "scientific_promotion_status",
                      "maintenance_parity", "maintenance_gain",
                      "enabled_services"):
            node.pop(field, None)

    def _clear_evaluation_projection(self, node: dict) -> None:
        for field in ("scores", "score_evidence", "evaluation_summary", "effect_resources_realized",
                      "effect_contract_status", "scientific_promotion_status", "mechanism_status",
                      "maintenance_parity", "maintenance_gain", "verdict"):
            node.pop(field, None)

    def _cancel_recovery_suffix_tasks(self, node: dict, boundary: str, recovery_id: str) -> None:
        invalidated = {
            "conclusion": {"conclude", "scientific_conclude"},
            "evaluation": {"evaluate", "conclude", "scientific_conclude"},
            "implementation": {"implement", "smoke", "fidelity", "ablation_fidelity",
                               "metric_bridge", "stage_launch", "eval_launch", "evaluate",
                               "conclude", "scientific_conclude"},
        }.get(boundary, set())
        for task in self.st.get("tasks", []):
            if (task.get("subject") or {}).get("node") != node.get("id") or \
                    task.get("type") not in invalidated or task.get("status") not in {"open", "paused", "stuck"}:
                continue
            task["status"] = "cancelled"
            task.pop("_render", None)
            task["cancel_reason"] = f"superseded by recovery {recovery_id} at {boundary} boundary"
            task["updated_at"] = eutil.utc_now()
            self.store.event("engine", "task_superseded_by_recovery", task=task.get("id"),
                             recovery=recovery_id, boundary=boundary)
        for gate in self.st.get("gates", []):
            subject = gate.get("subject") or {}
            task = self.store.get_task(self.st, str(subject.get("task") or ""))
            task_node = str(((task or {}).get("subject") or {}).get("node") or "")
            if gate.get("status") not in {"open", "paused"} or \
                    (subject.get("node") != node.get("id") and task_node != node.get("id")):
                continue
            gate["status"] = "cancelled"
            gate["decision_note"] = f"superseded by recovery {recovery_id} at {boundary} boundary"
            gate["held_by"] = []
            self.store.event("engine", "gate_superseded_by_recovery", gate=gate.get("id"),
                             recovery=recovery_id, boundary=boundary)

    def _invalidate_round_projection(self, node: dict, case: dict) -> None:
        """Do not time-travel a closed round after one of its heads changes.

        Rebuilding an old frontier from today's graph would be another lie.
        Preserve the snapshot, mark its decision field unknown, and append a
        correction overlay.  Stagnation policy treats unknown as insufficient
        evidence for declaring stagnation.
        """
        rid = str(node.get("round") or "")
        if not rid:
            return
        row = next((item for item in self.st.get("rounds", [])
                    if item.get("id") == rid and item.get("closed_at")), None)
        if row is None:
            return
        if "original_improved" not in row:
            row["original_improved"] = row.get("improved")
        row["improved"] = None
        row["projection_status"] = "invalidated_by_recovery"
        correction = {"recovery": case.get("id"), "round": rid, "node": node.get("id"),
                      "status": "pending", "recorded_at": eutil.utc_now(),
                      "reason": case.get("reason")}
        self.st.setdefault("round_corrections", []).append(correction)

    def _invalidate_recovery_consumers(self, plan: dict, case: dict) -> None:
        """Discard unsubmitted projections that captured superseded authority."""
        task_ids = {str(row.get("task") or "")
                    for row in ((plan.get("pending_authority_impact") or {}).get("tasks") or [])}
        task_ids.update(str(row.get("task") or "")
                        for row in ((plan.get("soft_knowledge_impact") or {}).get("task_exposures") or []))
        for task in self.st.get("tasks", []):
            if task.get("id") not in task_ids or task.get("status") not in {"open", "paused", "stuck"}:
                continue
            self._archive_unsubmitted_outputs(task, case)
            if task.get("type") == "open_round":
                # round_status=opening expects this identity.  Re-render it
                # from current heads when recovery completes rather than
                # manufacture another round id.
                task["refresh_after_recovery"] = case.get("id")
                continue
            task["status"] = "cancelled"
            task.pop("_render", None)
            task["cancel_reason"] = f"input authority superseded by recovery {case.get('id')}"
            task["updated_at"] = eutil.utc_now()
            for gate in self.st.get("gates", []):
                if (gate.get("subject") or {}).get("task") == task.get("id") \
                        and gate.get("status") in {"open", "paused"}:
                    gate["status"] = "cancelled"
                    gate["decision_note"] = task["cancel_reason"]
            self.store.event("engine", "consumer_task_invalidated", task=task.get("id"),
                             recovery=case.get("id"))

    def _archive_unsubmitted_outputs(self, task: dict, case: dict) -> None:
        """Move stale, unaccepted projections aside before rematerialization.

        A task may already have written its declared output when a hold lands.
        Leaving those bytes at the canonical path would let a replacement card
        accidentally submit an answer produced from superseded inputs.
        """
        archived: list[dict[str, str]] = []
        root = eutil.rpath(
            self.store.repo,
            f".evo/recoveries/{case.get('id')}/invalidated_outputs/{task.get('id')}")
        for index, rel in enumerate(task.get("outputs") or []):
            source = eutil.rpath(self.store.repo, str(rel))
            if not source.is_file():
                continue
            root.mkdir(parents=True, exist_ok=True)
            target = root / f"{index}_{source.name}"
            source.replace(target)
            archived.append({"from": str(rel), "to": eutil.rel(self.store.repo, target)})
        if archived:
            task.setdefault("invalidated_output_history", []).append({
                "recovery": case.get("id"), "files": archived, "at": eutil.utc_now()})
            self.store.event("engine", "unsubmitted_outputs_archived", task=task.get("id"),
                             recovery=case.get("id"), files=archived)

    def _refresh_open_round_task(self, task: dict) -> None:
        rid = str((task.get("subject") or {}).get("round") or "")
        self._materialize(task, extra_fields=self._portfolio_fields(rid),
                          **self._round_strategy_context(rid))
        task.pop("refresh_after_recovery", None)
        # R9 (external audit r6): the CARD/BUNDLE on disk just changed, so the
        # presentation receipt is stale - leaving it made the next `evo next`
        # print "Card unchanged", and an agent still holding the old card in
        # context would keep working from a revoked frontier / an old tempo.
        task.pop("presented_at", None)
        task["updated_at"] = eutil.utc_now()

    def _refresh_close_round_task(self, task: dict) -> None:
        rid = str((task.get("subject") or {}).get("round") or "")
        self._materialize(
            task,
            inputs=[(f".evo/rounds/{rid}/PORTFOLIO.json", "what this round planned"),
                    (".evo/views/FRONTIER.md", "frontier after this round"),
                    (".evo/views/GRAPH.md", "full graph")],
            extra_blocks=[("This round's lanes and outcomes", self._round_summary_block(rid)),
                          ("Frontiers, origin and per-cell records",
                           ebundle.frontier_block(self.g, self.cfg, self.st))])
        task.pop("presented_at", None)      # R9: the card changed - never claim "unchanged"
        task["updated_at"] = eutil.utc_now()

    def _refresh_derived_strategy_tasks(self, case: dict, *, include_close_round: bool) -> None:
        """Refresh only tasks that actually consume corrected derived views."""
        for task in self.st.get("tasks", []):
            if task.get("status") not in {"open", "paused", "stuck"}:
                continue
            if task.get("type") == "open_round":
                self._archive_unsubmitted_outputs(task, case)
                self._refresh_open_round_task(task)
            elif include_close_round and task.get("type") == "close_round":
                self._archive_unsubmitted_outputs(task, case)
                self._refresh_close_round_task(task)
            else:
                continue
            self.store.event("engine", "derived_consumer_refreshed", task=task.get("id"),
                             recovery=case.get("id"), boundary=case.get("boundary"))

    def _complete_recovery(self, case: dict, result: str) -> None:
        case["status"] = "completed"
        case["completed_at"] = eutil.utc_now()
        case["result"] = result
        for correction in self.st.get("round_corrections", []):
            if correction.get("recovery") == case.get("id") and correction.get("status") == "pending":
                correction["status"] = "sealed"
                correction["completed_at"] = eutil.utc_now()
                node = self.node(str(correction.get("node") or "")) or {}
                correction["new_conclusion_digest"] = str(
                    (node.get("conclusion_seal") or {}).get("digest") or "")
        for task in self.st.get("tasks", []):
            if task.get("refresh_after_recovery") == case.get("id"):
                self._refresh_open_round_task(task)
        hold = next((row for row in self.st.get("holds", []) if row.get("id") == case.get("hold")), None)
        if hold and hold.get("status") == "active":
            self._release_hold_in_memory(
                hold, note=f"recovery {case.get('id')} completed: {result}", actor="engine")
        self.store.event("engine", "recovery_completed", recovery=case.get("id"), result=result)

    def _terminate_recovery(self, case: dict, *, status: str, result: str,
                            actor: str = "engine") -> None:
        case["status"] = status
        case["completed_at"] = eutil.utc_now()
        case["result"] = result
        hold = next((row for row in self.st.get("holds", []) if row.get("id") == case.get("hold")), None)
        if hold and hold.get("status") == "active":
            self._release_hold_in_memory(hold, note=f"recovery {case.get('id')} {status}: {result}", actor=actor)
        self.store.event(actor, "recovery_terminated", recovery=case.get("id"),
                         status=status, result=result)

    def _retire_recovery_authority_for_abandonment(self, node: dict, case: dict,
                                                    reason: str) -> None:
        """Make a partially revised node historical before abandoning it."""
        active_selector = {
            "revision": int(node.get("implementation_revision") or 0),
            "implementation_digest": str((node.get("implementation_seal") or {}).get("digest") or ""),
            "implementation_commit": node.get("implementation_commit"),
            "implementation_manifest": node.get("implementation_manifest"),
            "reason": f"recovery {case.get('id')} abandoned: {reason}",
            "retired_at": eutil.utc_now(),
        }
        if active_selector["implementation_digest"] or active_selector["implementation_commit"]:
            node.setdefault("implementation_selector_history", []).append(active_selector)
        for run in self.st.get("runs", []):
            if run.get("node") != node.get("id"):
                continue
            if run.get("adoption_status") == "adopted":
                self._archive_seal(run, "evidence_seal")
                erun.transition_adoption(
                    run, "superseded", note=f"owning authority abandoned by recovery {case.get('id')}")
            elif erun.is_terminal(run) and run.get("adoption_status") == "candidate":
                erun.transition_adoption(
                    run, "quarantined", note=f"owning authority abandoned by recovery {case.get('id')}")
        for field in ("implementation_seal", "workflow_reuse_seal", "fidelity_seal", "ablation_fidelity_seal",
                      "metric_bridge_seal", "resource_receipt_seal", "eval_seal",
                      "conclusion_seal"):
            self._archive_seal(node, field)
        node["implementation_commit"] = None
        node["implementation_manifest"] = None
        node.pop("implementation_revision_pending", None)
        node.pop("implementation_revision_reason", None)
        node["resource_receipt_ready"] = False
        node["resource_receipt_path"] = None
        node.pop("workflow_reuse_receipt_path", None)
        node["eval_done"] = False
        node["evidence_heads"] = {}
        for field in ("eval_run", "probe_evidence_status", "evidence_pending_run",
                      # R9-002: a retired authority owes no repeat lane either
                      "repeat_pending_seed", "repeat_eval_run"):
            node.pop(field, None)
        self._clear_evaluation_projection(node)
        self._clear_conclusion_projection(node)
        node["authority_retired_at"] = eutil.utc_now()
        node["authority_retired_by"] = case.get("id")
        self.store.event("engine", "recovery_authority_retired", recovery=case.get("id"),
                         node=node.get("id"), reason=reason)

    def abort_recovery(self, recovery_id: str, reason: str, *, abandon_node: bool = False) -> dict:
        """Exit a recovery honestly; never restore superseded authority bytes."""
        case = next((row for row in self.st.get("recoveries", []) if row.get("id") == recovery_id), None)
        if case is None:
            raise SystemExit(f"[evo] no recovery {recovery_id}")
        if case.get("status") not in {"planned", "fork_required", "repairing", "replaying"}:
            raise SystemExit(f"[evo] recovery {recovery_id} is already terminal ({case.get('status')})")
        if not str(reason or "").strip():
            raise SystemExit("[evo] recover-abort needs an auditable --reason")
        applied = case.get("status") in {"repairing", "replaying"}
        try:
            members = erecover.scope_members(case.get("scope") or {}, self.st, self.g)
        except ValueError as exc:
            # The scope's target row no longer exists (external graph.json
            # corruption). Refusing to abort here closed EVERY exit: next
            # crashed on the same ValueError, resume refused the applied hold,
            # and abort crashed too - a wedge with no CLI escape. Aborting a
            # recovery whose target vanished is the one honest move left: no
            # authority can be restored or retired, the hold is released, and
            # doctor keeps reporting the underlying corruption.
            self.store.event("engine", "recovery_scope_lost", recovery=recovery_id,
                             scope=dict(case.get("scope") or {}), detail=str(exc))
            members = {}
        node = self.node(str((members.get("nodes") or [""])[0])) if members.get("nodes") else None
        if applied and not abandon_node:
            raise SystemExit("[evo] an applied recovery cannot restore its old authority; "
                             "repeat with --abandon-node or finish the repair")
        graph_sig_before = self._graph_consumer_sig()
        if applied and node is not None:
            if case.get("status") == "repairing":
                run = self.store.get_run(self.st, str((case.get("scope") or {}).get("id") or ""))
                if run and run.get("adoption_status") == "candidate":
                    erun.transition_adoption(run, "quarantined", note=f"recovery aborted: {reason}")
                if run and run.get("status") == "finished" and \
                        run.get("evidence_status") in {"incomplete", "invalid"}:
                    receipt_rel = f".evo/runs/{run.get('id')}/evidence/IRRECOVERABLE.json"
                    eutil.write_json_atomic(eutil.rpath(self.store.repo, receipt_rel), {
                        "schema_version": 1, "run": run.get("id"), "node": run.get("node"),
                        "recovery": recovery_id, "disposition": "irrecoverable_quarantined",
                        "reason": str(reason), "evidence_status": run.get("evidence_status"),
                        "errors": list(run.get("evidence_errors") or []),
                        "recorded_at": eutil.utc_now(),
                    })
                    run["evidence_disposition"] = "irrecoverable_quarantined"
                    run["evidence_disposition_receipt"] = receipt_rel
                if run and not run.get("resource_accounted"):
                    self._account_run(run)
                    run["absorbed"] = True
            self._retire_recovery_authority_for_abandonment(node, case, str(reason))
            self._abandon_node(node, f"recovery {recovery_id} aborted: {reason}")
        elif abandon_node and node is not None and \
                case.get("status") in {"planned", "fork_required"}:
            # R9 (external audit r6): on a planned/fork case --abandon-node was
            # SILENTLY IGNORED (the retirement body was applied-only), so
            # closing a terminal fork diagnosis released the hold and put the
            # damaged authority straight back on the frontier - the opposite
            # of what the operator asked for in the same command.
            if node.get("role") == "baseline":
                raise SystemExit("[evo] the baseline cannot be abandoned by recover-abort; a damaged "
                                 "baseline is a project fork (see the printed fork handoff)")
            self._retire_recovery_authority_for_abandonment(node, case, str(reason))
            self._abandon_node(node, f"recovery {recovery_id} aborted: {reason}")
        elif abandon_node and node is None and members.get("lanes") and \
                case.get("status") in {"planned", "fork_required"}:
            # R7 audit: a lane-target fork case with NO node yet (sketch/idea
            # stage) had no working retirement arm at all - the flag was
            # silently ignored, the hold released, and the damaged lane
            # returned to scheduling. Worse, the mid-round fork_lane handoff
            # was circular: its hold kept the round from closing, so "build
            # the replacement via the next open_round" was unreachable.
            # Retiring the lane HERE is the reachable order: the lane leaves
            # the round's active set, the round can close, and the NEXT
            # open_round builds the replacement.
            lane = self.store.get_lane(self.st, str((members.get("lanes") or [""])[0]))
            if lane is not None and lane.get("status") not in ("done", "abandoned"):
                self._abandon_lane(lane, f"recovery {recovery_id} aborted: {reason}")
                for t in self.st.get("tasks", []):
                    if (t.get("subject") or {}).get("lane") == lane.get("id") \
                            and t.get("status") in {"open", "paused", "stuck"}:
                        t["status"] = "cancelled"
                        t.pop("_render", None)
                        t["cancel_reason"] = f"owning lane abandoned: recovery {recovery_id} aborted"
                        t["held_by"] = []
                        t["updated_at"] = eutil.utc_now()
        # R8 (external audit r5): an open_round paused with this recovery's
        # refresh marker must NOT come back verbatim - its strategy context
        # still cites the pre-recovery frontier/knowledge (the marker is only
        # consumed on recovery SUCCESS). Cancel it before the hold release
        # below would reopen it; the scheduler re-materializes the projection
        # from the post-abort truth.
        for t in self.st.get("tasks", []):
            if t.get("type") == "open_round" and t.get("status") in ("open", "paused") \
                    and str(t.get("refresh_after_recovery") or "") == str(recovery_id):
                t["status"] = "cancelled"
                t.pop("_render", None)
                t.pop("refresh_after_recovery", None)
                t["updated_at"] = eutil.utc_now()
                self.store.event("engine", "open_round_refreshed_after_abort",
                                 task=t.get("id"), recovery=recovery_id)
        # R8 audit: an abandoning abort changed nodes/lanes/frontiers - the
        # rendered views and any open strategy/close card must follow in the
        # same persisted step (the hold release below may reopen them).
        if self._graph_consumer_sig() != graph_sig_before:
            self._sync_graph_consumers()
        self._terminate_recovery(case, status="aborted", result=str(reason), actor="user")
        self.save()
        return case

    def apply_recovery(self, recovery_id: str, confirm_digest: str) -> dict:
        case = next((row for row in self.st.get("recoveries", []) if row.get("id") == recovery_id), None)
        if case is None:
            raise SystemExit(f"[evo] no recovery {recovery_id}")
        if case.get("status") != "planned":
            raise SystemExit(f"[evo] recovery {recovery_id} is {case.get('status')}, not planned")
        plan = eutil.read_json(eutil.rpath(self.store.repo, str(case.get("plan_path") or "")), None)
        if not isinstance(plan, dict):
            raise SystemExit("[evo] recovery plan file is missing or malformed")
        actual_digest = erecover.plan_digest(plan)
        if confirm_digest != case.get("plan_digest") or actual_digest != case.get("plan_digest"):
            raise SystemExit("[evo] recovery plan digest mismatch; re-plan before applying")
        precondition_errors = erecover.verify_head_preconditions(
            plan.get("head_preconditions") or {}, self.st, self.g, self.reg)
        if precondition_errors:
            raise SystemExit("[evo] recovery plan is stale:\n  - " + "\n  - ".join(precondition_errors))
        planned_members = plan.get("members") or {}
        current_hard = (erecover.hard_descendants(
            self.g, self.reg, self._spec_index(), planned_members.get("nodes") or [])
            if planned_members.get("nodes") else {"roots": [], "nodes": [], "edges": []})
        current_pending = erecover.pending_authority_consumers(
            self.g, self.st.get("lanes", []), self.st.get("tasks", []),
            list(planned_members.get("nodes") or []) + list(current_hard.get("nodes") or []),
            registry=self.reg,
            spec_reader=lambda rel: eutil.read_json(eutil.rpath(self.store.repo, rel), None))
        current_soft = erecover.soft_knowledge_impact(
            planned_members.get("nodes") or [],
            {"lessons": self.store.lessons(self.st), "observations": self.store.observations(self.st)},
            self.st.get("tasks", []))
        planned_soft = plan.get("soft_knowledge_impact") or {}
        soft_signature = lambda value: {
            "refs": value.get("refs") or [], "records": value.get("records") or [],
            "task_exposures": [{"task": row.get("task"), "refs": row.get("refs") or []}
                               for row in value.get("task_exposures") or []],
        }
        # R11 liveness audit (S1): every fresh card carries the full
        # shared-artifact receipt, so ANY task minted in the plan->apply
        # window that renders the recovered producer's artifact becomes a new
        # pending-consumer row - and the strict equality gate then refused
        # apply forever (each re-plan opened a fresh window; no verb recomputed
        # the plan in place). A pure EXTENSION - same hard impact, same soft
        # knowledge, same head paths, planned rows all still present, only NEW
        # consumer rows added - is safe to engulf: the pause set below is
        # computed from the CURRENT pending consumers anyway, so the additions
        # are protected exactly like the reviewed ones. Anything else (rows
        # gone, hard/soft drift) is real staleness and still refuses.
        planned_pending = plan.get("pending_authority_impact") or {}
        pending_extension: list[str] = []
        pending_ok = current_pending == planned_pending
        if not pending_ok:
            planned_tasks = {str(r.get("task")) for r in (planned_pending.get("tasks") or [])}
            current_tasks = {str(r.get("task")) for r in (current_pending.get("tasks") or [])}
            planned_lanes = {str(x) for x in (planned_pending.get("lanes") or [])}
            current_lanes = {str(x) for x in (current_pending.get("lanes") or [])}
            if planned_tasks <= current_tasks and planned_lanes <= current_lanes and \
                    list(planned_pending.get("head_paths") or []) == \
                    list(current_pending.get("head_paths") or []):
                pending_extension = sorted(current_tasks - planned_tasks) + \
                    sorted(current_lanes - planned_lanes)
                pending_ok = True
        if current_hard != (plan.get("hard_impact") or {}) or not pending_ok or \
                soft_signature(current_soft) != soft_signature(planned_soft):
            raise SystemExit("[evo] recovery impact changed after planning; create and review a fresh plan")
        if pending_extension:
            self.store.event("engine", "recovery_pending_consumers_extended",
                             recovery=recovery_id, added=pending_extension)
            print(f"[evo] note: {len(pending_extension)} consumer(s) appeared after the plan was "
                  f"reviewed ({', '.join(pending_extension[:6])}); they are engulfed by the same "
                  "hold and refreshed with the reviewed ones")
        classification = plan.get("classification") or {}
        actions = set(classification.get("actions") or [])
        if not classification.get("supported") or actions & {"fork_node", "fork_lane", "fork_project"}:
            case["status"] = "fork_required"
            case["result"] = classification.get("reason")
            self.save()
            raise SystemExit("[evo] this authority cannot be rewritten in place: "
                             + str(classification.get("reason") or "fork required")
                             + ". This classification is TERMINAL by design (no in-place apply "
                             "exists): keep the hold, build the replacement world externally "
                             "(new lane/node via open_round, or a fresh project), record the "
                             "linkage with 'evo log', and close this case last with recover-abort "
                             "- see recover-plan's printed handoff protocol")
        members = plan.get("members") or {}
        node = self.node(str((members.get("nodes") or [""])[0])) if members.get("nodes") else None
        boundary = str(case.get("boundary") or "")
        if boundary in {"implementation", "evaluation", "conclusion"} and \
                (plan.get("operational_impact") or {}).get("blocks_authority_change"):
            raise SystemExit("[evo] authority replay is blocked until RUN launch/evidence facts are reconciled")
        own_hold = str(case.get("hold") or "")
        impact_lanes = set(str(x) for x in (planned_members.get("lanes") or []) if str(x))
        impact_nodes = set(str(x) for x in (planned_members.get("nodes") or []) if str(x))
        impact_runs = set(str(x) for x in (planned_members.get("runs") or []) if str(x))
        impact_nodes.update(str(x) for x in (current_hard.get("nodes") or []) if str(x))
        impact_lanes.update(str(x) for x in (current_pending.get("lanes") or []) if str(x))
        blocking_holds: list[str] = []
        for hold in self.st.get("holds", []):
            if hold.get("status") != "active" or hold.get("id") == own_hold:
                continue
            covered = str((hold.get("scope") or {}).get("kind") or "") == "project"
            covered = covered or any(erecover.hold_covers_subject(
                hold, self.st, self.g, lane=lane) for lane in impact_lanes)
            covered = covered or any(erecover.hold_covers_subject(
                hold, self.st, self.g, node=node) for node in impact_nodes)
            covered = covered or any(erecover.hold_covers_subject(
                hold, self.st, self.g, run=run) for run in impact_runs)
            if (case.get("scope") or {}).get("kind") == "round":
                covered = covered or erecover.hold_covers_subject(
                    hold, self.st, self.g, round_=str((case.get("scope") or {}).get("id") or ""))
            if covered:
                blocking_holds.append(str(hold.get("id") or "?"))
        if blocking_holds:
            raise SystemExit("[evo] recovery apply is blocked by additional active hold(s) "
                             + ", ".join(sorted(blocking_holds))
                             + "; release them explicitly before changing authority")
        if boundary not in {"frontier", "round"}:
            self._invalidate_recovery_consumers(plan, case)
        if boundary == "stage_evidence":
            if (case.get("scope") or {}).get("kind") != "run":
                raise SystemExit("[evo] stage_evidence repair must target run:RUN###")
            case["status"] = "repairing"
            case["applied_at"] = eutil.utc_now()
        elif boundary == "conclusion" and node is not None:
            self._cancel_recovery_suffix_tasks(node, boundary, recovery_id)
            self._supersede_node_knowledge(node, case)
            self._archive_seal(node, "conclusion_seal")
            node["conclusion_seal"] = None
            self._clear_conclusion_projection(node)
            revision = int(node.get("conclusion_revision") or 0) + 1
            node["outcome_path"] = f".evo/nodes/{node['id']}/OUTCOME_r{revision}.json"
            node["result_doc"] = f".evo/nodes/{node['id']}/NODE_RESULT_r{revision}.md"
            node["status"] = ("scientific_stop" if plan.get("authority_kind") == "scientific_stop"
                              else "evaluated")
            self._invalidate_round_projection(node, case)
            case["status"] = "replaying"
            case["applied_at"] = eutil.utc_now()
        elif boundary == "evaluation" and node is not None:
            self._cancel_recovery_suffix_tasks(node, boundary, recovery_id)
            self._supersede_node_knowledge(node, case)
            self._archive_seal(node, "eval_seal")
            self._archive_seal(node, "conclusion_seal")
            node["eval_seal"] = None
            node["conclusion_seal"] = None
            self._clear_evaluation_projection(node)
            self._clear_conclusion_projection(node)
            revision = int(node.get("eval_revision") or 0) + 1
            node["eval_metrics_path"] = f".evo/nodes/{node['id']}/eval/metrics_r{revision}.json"
            node["eval_report_path"] = f".evo/nodes/{node['id']}/eval/EVAL_REPORT_r{revision}.md"
            conclusion_revision = int(node.get("conclusion_revision") or 0) + 1
            node["outcome_path"] = f".evo/nodes/{node['id']}/OUTCOME_r{conclusion_revision}.json"
            node["result_doc"] = f".evo/nodes/{node['id']}/NODE_RESULT_r{conclusion_revision}.md"
            node["status"] = "workflow_done"
            node["eval_done"] = True  # preserve the adopted raw eval RUN; redo analysis only
            self._invalidate_round_projection(node, case)
            case["status"] = "replaying"
            case["applied_at"] = eutil.utc_now()
        elif boundary == "implementation" and node is not None:
            operational = plan.get("operational_impact") or {}
            if operational.get("blocks_authority_change"):
                raise SystemExit("[evo] implementation recovery is blocked by unresolved RUN/evidence effects")
            repair_scope = str(plan.get("repair_scope") or "workflow")
            self._cancel_recovery_suffix_tasks(node, boundary, recovery_id)
            self._supersede_node_knowledge(node, case)
            self._archive_seal(node, "eval_seal")
            self._archive_seal(node, "conclusion_seal")
            self._archive_seal(node, "resource_receipt_seal")
            node["eval_seal"] = None
            node["conclusion_seal"] = None
            node["resource_receipt_seal"] = None
            node["resource_receipt_path"] = None
            node["resource_receipt_ready"] = False
            self._clear_conclusion_projection(node)
            self._clear_evaluation_projection(node)
            # R10-021: an implementation recovery changes the node's authority
            # generation - a repeat_measure approved against the PREVIOUS
            # generation (and its resume snapshot) must not survive it: the
            # fresh evaluation re-judges near-the-line and reopens its own
            # offer if warranted, exactly like the ordinary restart paths.
            self._archive_repeat_measure(node, f"implementation recovery {recovery_id} "
                                               "superseded the approval's authority generation")
            if node.get("scientific_stop"):
                node.setdefault("scientific_stop_history", []).append(
                    json.loads(json.dumps(node["scientific_stop"])))
                node.pop("scientific_stop", None)
            eval_revision = int(node.get("eval_revision") or 0) + 1
            node["eval_metrics_path"] = f".evo/nodes/{node['id']}/eval/metrics_r{eval_revision}.json"
            node["eval_report_path"] = f".evo/nodes/{node['id']}/eval/EVAL_REPORT_r{eval_revision}.md"
            conclusion_revision = int(node.get("conclusion_revision") or 0) + 1
            node["outcome_path"] = f".evo/nodes/{node['id']}/OUTCOME_r{conclusion_revision}.json"
            node["result_doc"] = f".evo/nodes/{node['id']}/NODE_RESULT_r{conclusion_revision}.md"
            node["status"] = "building"
            node["fix_needed"] = True
            node["fix_note"] = f"approved recovery {recovery_id}: {case.get('reason')}"
            node["implementation_repair_scope"] = repair_scope
            node["implementation_repair_source_run"] = (
                node.get("eval_run") if repair_scope == "evaluation" else None)
            self._invalidate_round_projection(node, case)
            case["status"] = "replaying"
            case["applied_at"] = eutil.utc_now()
        elif boundary == "frontier":
            egraph.recompute_rollups(self.g, self.cfg)
            egraph.render_views(self.store, self.g, self.cfg, self.st)
            self._refresh_derived_strategy_tasks(case, include_close_round=True)
            self._complete_recovery(case, "derived frontier recomputed")
        elif boundary == "round":
            round_id = str((case.get("scope") or {}).get("id") or "")
            row = next((item for item in self.st.get("rounds", [])
                        if item.get("id") == round_id and item.get("closed_at")), None)
            if row is not None:
                row["projection_status"] = "annotated"
            self.st.setdefault("round_corrections", []).append({
                "recovery": recovery_id, "round": round_id, "node": None,
                "status": "annotated", "reason": case.get("reason"),
                "recorded_at": eutil.utc_now()})
            self.store.event("user", "closed_round_annotation", recovery=recovery_id,
                             reason=case.get("reason"))
            egraph.render_views(self.store, self.g, self.cfg, self.st)
            self._refresh_derived_strategy_tasks(case, include_close_round=False)
            self._complete_recovery(case, "closed history annotated; not rewritten")
        else:
            raise SystemExit(f"[evo] boundary {boundary!r} has no safe in-place apply path")
        if (plan.get("operational_impact") or {}).get("requires_compensation"):
            case["compensation"] = {
                "mode": "retain_external_facts_and_charges",
                "runs": list((plan.get("operational_impact") or {}).get("external_effects") or []),
                "recorded_at": eutil.utc_now(),
            }
        self.store.event("user", "recovery_applied", recovery=recovery_id,
                         boundary=boundary, status=case.get("status"))
        self.save()
        return case

    def _next_recovery(self) -> dict | None:
        case = next((row for row in self.st.get("recoveries", [])
                     if row.get("status") in {"repairing", "replaying"}), None)
        if case is None:
            return None
        scope = case.get("scope") or {}
        if case.get("status") == "repairing":
            run = self.store.get_run(self.st, str(scope.get("id") or ""))
            other_holds = [hold for hold in self.st.get("holds", [])
                           if hold.get("status") == "active" and hold.get("id") != case.get("hold")
                           and erecover.hold_covers_subject(
                               hold, self.st, self.g, node=(run or {}).get("node"),
                               run=(run or {}).get("id"))]
            if other_holds:
                # R10-022: name the release verb - the cold-start entrances
                # (next/status/recover-status) all reuse this reason, and
                # without the verb they looped between "run next again" and
                # aborting the whole case.
                extra = ", ".join(str(row.get("id")) for row in other_holds)
                return {"kind": "waiting",
                        "reason": (f"recovery {case.get('id')} is additionally paused by hold(s) "
                                   f"{extra} - release each with 'evo resume --hold "
                                   f"{other_holds[0].get('id')} --note ...' (the case's own hold "
                                   f"{case.get('hold')} stays until the case ends)")}
            if run and run.get("evidence_status") == "complete" and run.get("adoption_status") == "adopted":
                self._complete_recovery(case, f"same RUN {run.get('id')} evidence reconciled")
                return None
            # R11 matrix sweep (M2): the replaying branch has always lazily
            # terminated on an abandoned target; the repairing branch had no
            # such arm, so a case whose completion condition became
            # unsatisfiable (owner abandoned, or the RUN terminally
            # dispositioned outside the accept-missing transition) sat
            # repairing forever with its hold in force.
            owner = self.node(str((run or {}).get("node") or "")) if run else None
            if run is None:
                self._terminate_recovery(case, status="failed",
                                         result=f"target RUN {scope.get('id')} no longer exists")
                return None
            if run.get("evidence_disposition") in erun.TERMINAL_EVIDENCE_DISPOSITIONS:
                self._terminate_recovery(
                    case, status="failed",
                    result=f"target RUN {run.get('id')}'s evidence was terminally dispositioned; "
                           "the case's completion condition is unsatisfiable")
                return None
            if owner is not None and owner.get("status") == "abandoned":
                self._terminate_recovery(
                    case, status="failed",
                    result=f"target RUN {run.get('id')}'s owner node was abandoned during repair")
                return None
            # R10-017: waiting on late materials is a LOCAL condition - the
            # case's guidance rides the RUN's standing reconcile notice, and
            # the round close is already blocked by the open evidence
            # obligation. Returning waiting here made one node's material
            # wait the whole project's primary surface (siblings' open tasks
            # and watch cards became unreachable); the replaying branch has
            # always yielded in the same situation.
            return None
        try:
            members = erecover.scope_members(scope, self.st, self.g)
        except ValueError:
            # scope_members raises on an unknown id, so the lost-target waiting
            # branch below was unreachable for the very corruption it describes
            # and every `evo next` crashed instead of presenting a way out.
            members = {}
        node = self.node(str((members.get("nodes") or [""])[0])) if members.get("nodes") else None
        if node is None:
            return {"kind": "waiting",
                    "reason": (f"recovery {case.get('id')} lost its target node (graph row missing); "
                               "run evo doctor to see the corruption, then evo recover-abort "
                               f"--recovery {case.get('id')} to release its hold")}
        other_holds = [hold for hold in self.st.get("holds", [])
                       if hold.get("status") == "active" and hold.get("id") != case.get("hold")
                       and erecover.hold_covers_subject(
                           hold, self.st, self.g, node=node.get("id"), lane=node.get("lane"),
                           round_=node.get("round"))]
        if other_holds:
            # R10-022: same release-verb duty as the repairing branch above
            extra = ", ".join(str(row.get("id")) for row in other_holds)
            return {"kind": "waiting",
                    "reason": (f"recovery {case.get('id')} is additionally paused by hold(s) "
                               f"{extra} - release each with 'evo resume --hold "
                               f"{other_holds[0].get('id')} --note ...' (the case's own hold "
                               f"{case.get('hold')} stays until the case ends)")}
        if node.get("status") == "abandoned":
            self._terminate_recovery(case, status="failed",
                                     result=f"target node {node.get('id')} was abandoned during replay")
            return None
        if node.get("status") == "concluded":
            self._complete_recovery(case, f"node {node.get('id')} reached a new sealed conclusion")
            return None
        for gate in self.st.get("gates", []):
            if gate.get("status") != "open":
                continue
            # R11-017: the abandon_request proposal is NON-BLOCKING by
            # contract (the main loop only surfaces it when nothing else is
            # actionable; evo.py prints that promise) - presenting it here
            # ahead of the replay target's live task inverted the priority
            # for every fresh session.
            if gate.get("kind") == "abandon_request":
                continue
            subject = gate.get("subject") or {}
            task = self.store.get_task(self.st, str(subject.get("task") or ""))
            task_node = str(((task or {}).get("subject") or {}).get("node") or "")
            if subject.get("node") == node.get("id") or task_node == node.get("id"):
                return self._present_gate(gate)
        stuck = [task for task in self.st.get("tasks", [])
                 if task.get("status") == "stuck"
                 and (task.get("subject") or {}).get("node") == node.get("id")]
        for task in stuck:
            # R11-012 (belt): "waiting for its escalation decision" is only
            # honest while a DECIDABLE gate exists. A stale-cancelled
            # escalation used to leave the stuck launch card waiting forever
            # for a decision object that no longer exists; with a terminal
            # RUN behind it, no submit shape can ever discharge it - settle
            # it here and let the scheduler re-mint from the node's state.
            has_decidable = any(
                g.get("kind") == "escalation" and g.get("status") in ("open", "paused")
                and str((g.get("subject") or {}).get("task") or "") == str(task.get("id") or "")
                for g in self.st.get("gates", []))
            if has_decidable:
                return {"kind": "waiting",
                        "reason": f"recovery {case.get('id')} task {task.get('id')} "
                                  "is stuck and requires its escalation decision"}
            if task.get("type") in ("stage_launch", "eval_launch"):
                stale_run = self.store.get_run(
                    self.st, str((task.get("subject") or {}).get("run") or ""))
                if stale_run is None or erun.is_terminal(stale_run):
                    self._settle_unfinishable_launch_task(
                        task, stale_run,
                        "its escalation was superseded and its RUN is terminal; "
                        "no launch receipt can ever be produced")
                    continue
            return {"kind": "waiting",
                    "reason": (f"recovery {case.get('id')} task {task.get('id')} is stuck with no "
                               "open escalation - decide/settle it (a superseded escalation is "
                               "re-minted by the ordinary retry path once the task is discharged)")}
        for task in self.store.open_tasks(self.st):
            if (task.get("subject") or {}).get("node") == node.get("id"):
                return self._present_task(task)
        # R7 audit: this fast path runs BEFORE the main loop's global gate
        # scan and one-open-card floor. Creating the recovery's next task
        # while an UNRELATED gate awaits the user, or while an unrelated task
        # legitimately holds the floor, minted a second live authority card
        # (doctor: MULTI_OPEN_TASKS) and demoted a pending user decision.
        # Yield to the main loop; the recovery resumes when the floor frees.
        # A stage_watch is the one exception - it is a placeholder card and
        # yields exactly as it does in the main loop (superseded below).
        blocking_gate = next((g for g in self.store.open_gates(self.st)
                              if g.get("kind") != "abandon_request"), None)
        if blocking_gate is not None:
            return None
        open_now = self.store.open_tasks(self.st)
        watch = next((t for t in open_now if t.get("type") == "stage_watch"), None)
        if any(t.get("type") != "stage_watch" for t in open_now):
            return None
        out = self._next_node_task(node, ignore_hold=True)
        if out is not None and watch is not None and not (
                out.get("kind") == "task" and out.get("task") == watch.get("id")):
            watch["status"] = "done"
            watch.pop("_render", None)
            watch["updated_at"] = eutil.utc_now()
            self.store.event("engine", "watch_superseded", task=watch["id"])
        return out
