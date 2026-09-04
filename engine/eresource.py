"""Resource accounting (v10): charged/reserved/effective-limit computation,
reservation transfer and usage charging. The ONLY implementation - views,
doctor and the CLI call these instead of hand-rolling copies (v9.2 had 4).
"""

from __future__ import annotations

import math


import econfig
import erun
import eutil

stages_of = econfig.stages_of



class ResourceMixin:
    def _resource_charged(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for entry in self.st.get("resource_ledger", []):
            for unit, value in (entry.get("usage") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    out[str(unit)] = out.get(str(unit), 0.0) + float(value)
        return out

    def _resource_reserved(self) -> dict[str, float]:
        out: dict[str, float] = {}
        holders = [t for t in self.st.get("tasks", []) if t.get("status") == "open"] + \
                  [r for r in self.st.get("runs", []) if erun.holds_reservation(r)]
        for holder in holders:
            for unit, value in (holder.get("resource_reservation") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    out[str(unit)] = out.get(str(unit), 0.0) + float(value)
        return out

    def _resource_effective_limits(self) -> dict[str, float]:
        base = econfig.resource_limits(self.cfg)
        extra = self.st.get("resource_overrides") or {}
        return {unit: limit + float(extra.get(unit, 0.0) or 0.0) for unit, limit in base.items()}

    def _resource_deficit(self, request: dict[str, float]) -> dict[str, float]:
        limits = self._resource_effective_limits()
        charged, reserved = self._resource_charged(), self._resource_reserved()
        out: dict[str, float] = {}
        for unit, amount in request.items():
            available = limits.get(unit, 0.0) - charged.get(unit, 0.0) - reserved.get(unit, 0.0)
            if float(amount) > available + 1e-12:
                out[unit] = float(amount) - available
        return out

    def _probe_budget_exceeded(self, node: dict, request: dict[str, float]) -> dict[str, tuple[float, float]]:
        """Reconcile a probe's approved cap against what it has ACTUALLY spent.

        The cap was declaration-time arithmetic only (planned budgets summed
        once at plan_node), so a relaunch, a repeat-spend approval or a
        conservative failure charge could take a "bounded" probe past the
        number the user approved without anything noticing.  This reads the
        real ledger, so the cap binds spend rather than intent.
        """
        if node.get("experiment_purpose") != "diagnostic_probe":
            return {}
        cap = ((self._spec(node).get("probe") or {}).get("budget") or {})
        if not isinstance(cap, dict) or not cap:
            return {}
        spent: dict[str, float] = {}
        for entry in self.st.get("resource_ledger", []):
            if str(entry.get("node") or "") != str(node.get("id") or ""):
                continue
            for unit, value in (entry.get("usage") or {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    spent[str(unit)] = spent.get(str(unit), 0.0) + float(value)
        extra = node.get("probe_cap_extra") or {}
        over: dict[str, tuple[float, float]] = {}
        for unit, limit in cap.items():
            if isinstance(limit, bool) or not isinstance(limit, (int, float)):
                continue
            cap_eff = float(limit) + float(extra.get(str(unit), 0.0) or 0.0)
            projected = spent.get(str(unit), 0.0) + float(request.get(str(unit), 0.0) or 0.0)
            if projected > cap_eff + 1e-9:
                over[str(unit)] = (projected, cap_eff)
        return over

    def _resource_gate(self, node: dict, operation: str, request: dict[str, float],
                       stage: str | None = None, *, repeat: bool = False) -> dict | None:
        # R10-015: a gate born from the repeat buy-back lane carries that
        # identity in its subject, so waive-repeat can retire it together
        # with the purchase it guards (approve would otherwise widen the
        # project contract for a spend that no longer exists; reject would
        # discard the restored node).
        over = self._probe_budget_exceeded(node, request)
        if over:
            # R3 liveness audit: this used to raise SystemExit, which
            # crash-looped every `evo next` after one failed probe run (the
            # conservative failure charge alone exhausts a cap==plan budget)
            # and pre-empted the repeat_spend gate built for exactly this
            # decision. Project-limit overruns one branch below gate instead
            # of crashing - probe-cap overruns now do the same: approve buys
            # exactly the overage for THIS probe, reject abandons it.
            subject = {"node": node["id"], "operation": operation, "stage": stage,
                       "request": request,
                       "probe_cap_over": {u: [p, c] for u, (p, c) in sorted(over.items())},
                       **({"repeat_measure": True} if repeat else {})}
            for gate in reversed(self.st.get("gates", [])):
                gs = gate.get("subject") or {}
                if gate.get("kind") == "resource_approval" and gate.get("status") == "open" and \
                        gs.get("node") == node["id"] and gs.get("operation") == operation and \
                        gs.get("stage") == stage and gs.get("probe_cap_over"):
                    return gate
            detail = ", ".join(f"{u}: {p:g} > approved cap {c:g}" for u, (p, c) in sorted(over.items()))
            return self.store.new_gate(
                self.st, "resource_approval", subject,
                f"Probe node {node['id']} would exceed the probe budget the user approved ({detail}). "
                "A probe is a bounded measurement: approve to raise THIS probe's cap by exactly the "
                "overage shown (one retry's honest price); reject to abandon the probe with what it "
                "already measured on record.")
        deficit = self._resource_deficit(request)
        subject = {"node": node["id"], "operation": operation, "stage": stage,
                   "request": request, "deficit": deficit,
                   **({"repeat_measure": True} if repeat else {})}
        for gate in reversed(self.st.get("gates", [])):
            gs = gate.get("subject") or {}
            if gate.get("kind") == "resource_approval" and gate.get("status") == "open" and \
                    gs.get("node") == node["id"] and gs.get("operation") == operation and \
                    gs.get("stage") == stage and not gs.get("probe_cap_over"):
                # R7: the deficit is RECOMPUTED on every pass. The frozen
                # snapshot kept demanding an increase after other RUNs had
                # released their reservations - forcing the user to either
                # widen a contract that no longer needed widening or discard
                # a node that had become legal.
                if not deficit:
                    gate["status"] = "cancelled"
                    gate["resolved_at"] = eutil.utc_now()
                    gate["note"] = "capacity returned before any decision; no contract change needed"
                    self.store.event("engine", "gate_cancelled", gate=gate.get("id"),
                                     reason="resource_deficit_cleared")
                    return None
                if gs.get("deficit") != deficit:
                    gs["deficit"] = deficit
                    gate["subject"] = gs
                    self.store.event("engine", "resource_gate_deficit_refreshed",
                                     gate=gate.get("id"), deficit=deficit)
                return gate
        if not deficit:
            return None
        used = self._resource_charged()
        limits = self._resource_effective_limits()
        detail = ", ".join(f"{u}: need +{d:g} (charged {used.get(u, 0):g} / limit {limits.get(u, 0):g})"
                           for u, d in sorted(deficit.items()))
        return self.store.new_gate(
            self.st, "resource_approval", subject,
            f"Node {node['id']} cannot reserve {operation}{' '+stage if stage else ''} within the "
            f"user-confirmed project resource contract. {detail}. Approve to add exactly this deficit "
            "to the project limit; reject to abandon this node.")

    def refresh_resource_gate(self, gate: dict) -> bool:
        """Re-settle an OPEN resource_approval gate against live capacity.

        R9 (external audit r6): the recompute above lives inside
        ``_resource_gate``, which is only reached from node scheduling - and an
        open gate preempts scheduling entirely, so the "recomputed on every
        pass" promise was unreachable while the gate was open. The presenter
        and the decision point call this instead. Returns True when the gate
        was cancelled because the deficit is gone."""
        if gate.get("kind") != "resource_approval" or gate.get("status") != "open":
            return False
        gs = gate.get("subject") or {}
        if gs.get("probe_cap_over"):
            return False           # a probe cap overage is not project capacity
        deficit = self._resource_deficit(gs.get("request") or {})
        if not deficit:
            gate["status"] = "cancelled"
            gate["resolved_at"] = eutil.utc_now()
            gate["note"] = "capacity returned before any decision; no contract change needed"
            self.store.event("engine", "gate_cancelled", gate=gate.get("id"),
                             reason="resource_deficit_cleared")
            return True
        if gs.get("deficit") != deficit:
            gs["deficit"] = deficit
            gate["subject"] = gs
            self.store.event("engine", "resource_gate_deficit_refreshed",
                             gate=gate.get("id"), deficit=deficit)
        return False

    def _reserve_task(self, task: dict, request: dict[str, float]) -> dict:
        task["resource_reservation"] = dict(request)
        self.store.event("engine", "resource_reserved", task=task["id"], node=task.get("subject", {}).get("node"),
                         usage=request)
        return task

    def _charge_resource(self, *, node: str, kind: str, usage: dict[str, float], basis: str,
                         run: dict | None = None, task: dict | None = None) -> None:
        clean = {u: float(v) for u, v in usage.items()
                 if isinstance(v, (int, float)) and not isinstance(v, bool) and float(v) >= 0}
        entry = {"id": f"RC{len(self.st.setdefault('resource_ledger', [])) + 1:04d}",
                 "node": node, "kind": kind, "run": (run or {}).get("id"),
                 "task": (task or {}).get("id"), "usage": clean, "basis": basis,
                 "charged_at": eutil.utc_now()}
        self.st["resource_ledger"].append(entry)
        if run is not None:
            run["resource_usage"] = clean
            run["resource_charge_basis"] = basis
            run["resource_accounted"] = True
        if task is not None:
            task.pop("resource_reservation", None)
            task["resource_accounted"] = True
        self.store.event("engine", "resource_charged", **entry)

    def _account_run(self, run: dict) -> None:
        if run.get("resource_accounted"):
            return
        reservation = dict(run.get("resource_reservation") or {})
        usage = reservation
        basis = "reserved_cap_on_failure"
        if run.get("status") == "finished" and run.get("metrics_file"):
            data = eutil.read_json(eutil.rpath(self.store.repo, str(run["metrics_file"])), {}) or {}
            field = "usage" if run.get("kind") == "stage" else "_usage"
            reported = data.get(field) if isinstance(data, dict) else None
            if isinstance(reported, dict):
                # R8 (external audit r5): a partial/invalid usage dict used to
                # be trusted for whatever subset happened to parse - a missing
                # or NaN unit was silently charged 0 and its reservation
                # released, i.e. an INVALID report bought a cheaper bill than
                # no report at all. Per-unit rule: a valid finite number is the
                # actual; anything else falls back to that unit's reserved cap.
                merged: dict[str, float] = {}
                complete = True
                for u in reservation:
                    v = reported.get(u)
                    if isinstance(v, (int, float)) and not isinstance(v, bool) \
                            and math.isfinite(float(v)) and float(v) >= 0:
                        merged[u] = float(v)
                    else:
                        merged[u] = float(reservation[u])
                        complete = False
                # R9 (external audit r6): the loop above walks the RESERVATION,
                # so an honestly reported unit the stage never pre-declared -
                # legal, since a stage need only declare one tracked unit -
                # was accepted by the evidence validator and then erased from
                # the ledger, letting the next RUN spend that axis's whole
                # limit again. Every reported unit inside the project's hard
                # contract is charged.
                tracked = econfig.resource_limits(self.cfg)
                for u, v in reported.items():
                    if str(u) in merged or str(u) not in tracked:
                        continue
                    if isinstance(v, (int, float)) and not isinstance(v, bool) \
                            and math.isfinite(float(v)) and float(v) >= 0:
                        merged[str(u)] = float(v)
                usage = merged
                basis = "reported_actual" if complete else "partial_report_reserved_fallback"
        self._charge_resource(node=str(run.get("node") or ""), kind=str(run.get("kind") or "run"),
                              usage=usage, basis=basis, run=run)
