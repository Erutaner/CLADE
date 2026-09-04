'''Deterministic scheduler core (v10): owns compute_next/submit and the
phase walk. All heavy machinery lives in the mixins; policy tables in eflow.'''

from __future__ import annotations

import hashlib
import secrets

import json
import os

import eartifact
import ebundle
import ecanary
import ecards
import econfig
import eflow
import egraph
import einfra
import erecover
import erun
import eseal
import eutil
import evalid
import evcs

stages_of = econfig.stages_of


import eabsorb
import eapply
import eauthority
import edash
import egate
import erepair
import eresource
import etask

class Engine(etask.TaskMixin, eapply.ApplyMixin, eabsorb.AbsorbMixin,
             egate.GateMixin, erepair.RepairMixin, eresource.ResourceMixin,
             eauthority.AuthorityMixin):
    def __init__(self, store):
        self.store = store
        self.st = store.load_state()
        self.cfg = store.load_config()
        self.g = store.load_graph()
        self.reg = store.load_artifacts()
        self._open_watch = None
        self._infra_memo = None
        self._pending_error_resolutions: list[dict] = []
        self._pending_resolution_retractions: list[dict] = []
        self._seal_digest_seed: dict[str, str] = {}
        evcs.begin_invocation()

    def ctx(self) -> evalid.Ctx:
        return evalid.Ctx(self.store, self.st, self.cfg, self.g, self.reg)

    def _stage_error_resolution(self, rec: dict) -> None:
        """Buffer an infra disposition until the transition actually commits.

        These rows are SUPPRESSORS: pending_infra_errors treats a dispositioned
        ER as handled.  Written eagerly, a transition that raised before save()
        would permanently silence a knowledge duty for an abandon/conclusion
        that never happened.  Events stay eager (they are pure history); this
        one is not. R11-008: each staged row carries an outbox key - the row
        rides INSIDE the committed state until its journal append lands, so
        the commit-then-append window can no longer lose it (see save()).
        """
        row = dict(rec)
        row.setdefault("outbox_key", secrets.token_hex(8))
        self._pending_error_resolutions.append(row)

    def _stage_resolution_retraction(self, node_id: str, *, recovery: str, reason: str) -> None:
        """R9 (external audit r6): staged like the suppressors so nothing lands
        when the transition raises before save(). Flush ORDER differs: a
        retraction UN-suppresses knowledge duties, so it is written before the
        state commit (see save()) - the crash window then fails closed (duty
        re-asked, doctor-visible) instead of open (committed supersedes still
        silenced by stale resolutions, invisible)."""
        self._pending_resolution_retractions.append(
            {"node": str(node_id), "recovery": str(recovery), "reason": str(reason)})

    def save(self) -> None:
        # Retractions flush BEFORE the state commit: they UN-suppress duties,
        # so the crash window between the two writes must fail closed (an
        # orphan retraction re-asks a disposition and doctor's
        # CONCLUDED_PENDING_INFRA sees it; the reverse order left committed
        # supersedes silently suppressed by stale resolutions - fail-open and
        # invisible). Staging still holds: nothing lands if the transition
        # raised before reaching save().
        while self._pending_resolution_retractions:
            row = self._pending_resolution_retractions[0]
            self.store.retract_error_resolutions(
                row["node"], recovery=row["recovery"], reason=row["reason"])
            self._pending_resolution_retractions.pop(0)
        # R11-008: the staged suppressor rows ride INSIDE the state commit as
        # an outbox - "state committed, appends lost to a mid-command
        # interruption" used to leave a concluded/abandoned node permanently
        # owing rows nobody could re-stage (the task was done, the schedule
        # skips terminal nodes, doctor --fix does not write rows). Any outbox
        # left by an interrupted predecessor is merged in front (journal-key
        # dedup makes the replay idempotent).
        carried = [row for row in (self.st.get("resolution_outbox") or [])
                   if isinstance(row, dict)]
        appended_keys = {str(r.get("outbox_key") or "")
                         for r in self.store.errors()
                         if isinstance(r, dict) and r.get("kind") == "resolution"}
        pending = ([row for row in carried
                    if str(row.get("outbox_key") or "") not in appended_keys]
                   + self._pending_error_resolutions)
        if pending:
            self.st["resolution_outbox"] = [dict(row) for row in pending]
        else:
            self.st.pop("resolution_outbox", None)
        # One optimistic transaction: the state revision guards all three files.
        self.store.save_all(self.st, self.g, self.reg)
        # Only after the authoritative write succeeded do the staged
        # suppressor rows become real. R7: pop each row only after its own
        # append returned - detaching the whole buffer first meant an append
        # failure dropped every remaining row with no retry left anywhere.
        # The outbox stays in the committed state until the NEXT save proves
        # every append landed (dedup above); a second interruption between
        # this commit and these appends therefore replays instead of losing.
        self._pending_error_resolutions = list(pending)
        while self._pending_error_resolutions:
            self.store.add_error_resolution(self._pending_error_resolutions[0])
            self._pending_error_resolutions.pop(0)

    def _assert_frozen_contract(self) -> None:
        """Refuse science under success/resource rules the user did not sign."""
        if not self.st.get("config_frozen"):
            return
        expected = str(self.st.get("bootstrap_contract_digest") or "")
        actual = econfig.bootstrap_contract_digest(self.cfg)
        if not expected or actual != expected:
            raise SystemExit(
                "[evo] the confirmed success/resource contract in .evo/config.json changed after "
                "bootstrap approval. The engine will not run under unapproved rules. Restore the "
                "confirmed fields, or deliberately restart/reconfigure this fresh v10 project; "
                "'evo doctor' reports the mismatch. Supervision changes remain available through "
                "'evo autonomy'.")
        approved_facts = str(self.st.get("bootstrap_infra_facts_digest") or "")
        facts = einfra.load_facts(self.store, self.cfg) or {}
        facts_digest = ecanary.facts_digest_of(facts)
        if not approved_facts or facts_digest != approved_facts:
            # C4 (correctness audit): a facts-revision decision writes the
            # file before its state commits; a crash in that window leaves
            # disk bytes ahead of (approve) or behind (rollback) the stamped
            # digest. BOTH torn shapes are identified by the still-open gate
            # or the recorded rollback coordinates - let the decide/rollback
            # retry through instead of refusing every command forever.
            open_rev = next((gt for gt in self.st.get("gates", [])
                             if gt.get("kind") == "infra_revision"
                             and gt.get("status") == "open"), None)
            torn_approve = (open_rev is not None and facts_digest ==
                            str((open_rev.get("subject") or {}).get("proposed_digest") or ""))
            info = self.st.get("infra_revision") if isinstance(self.st.get("infra_revision"), dict) else {}
            torn_rollback = facts_digest == str(info.get("prior_digest") or "")
            if torn_approve or torn_rollback:
                print("[evo] note: an interrupted facts-revision decision left the facts file "
                      "one step ahead of the recorded approval - re-decide the open "
                      "infra_revision gate (torn approve) or re-reject the drill escalation "
                      "(torn rollback) to converge; commands continue meanwhile")
            else:
                raise SystemExit(
                    "[evo] INFRA_FACTS changed after bootstrap approval. The active resource manifest "
                    "and any canary evidence are no longer valid; restore the approved facts or "
                    "deliberately restart/reconfigure this fresh v10 project.")
        if self.st.get("infra_revision_pending"):
            # the revised facts are approved but their canary proof is still
            # owed; the launch validators refuse new spend meanwhile, so the
            # stale canary record is a DISCLOSED transition state, not drift
            return
        if "infra_drill" in (self.st.get("bootstrap_done") or []):
            record = self.st.get("infra_canary")
            canary_errs = ecanary.record_errors_for_snapshot(
                self.store, record, cfg=self.cfg, st=self.st,
                require_passed=True, facts=facts)
            if canary_errs:
                raise SystemExit("[evo] active infrastructure canary evidence is invalid:\n  - "
                                 + "\n  - ".join(canary_errs))
            # The dashboard render later in this same invocation re-validates
            # the identical record against identical bytes; hand it this
            # already-proven answer instead (require_passed=False differs only
            # by the NOT_PASSED line, which an empty error list cannot carry).
            self._infra_memo = {"facts": facts, "facts_digest": facts_digest,
                                "canary_record": record, "canary_errors": []}

    @staticmethod
    def _archive_seal(owner: dict, field: str) -> None:
        seal = owner.pop(field, None)
        archived = eseal.superseded(seal)
        if archived:
            owner.setdefault("seal_history", []).append(archived)

    def _seal(self, artifacts: list[tuple[str, str]], *, upstream: list[str] | None = None,
              revision: int = 1) -> dict:
        seal = eseal.create(self.store.repo, artifacts, upstream=upstream or [], revision=revision)
        # Working-path digests this invocation just computed, harvested for the
        # postcondition sweep's cache. NEVER the snapshot digests: the post
        # sweep is the snapshot copy's first integrity read.
        seed = getattr(self, "_seal_digest_seed", None)
        if seed is not None:
            for row in seal.get("artifacts") or []:
                if isinstance(row, dict) and row.get("path") and row.get("digest"):
                    seed[str(row["path"])] = str(row["digest"])
        return seal

    def _done_task(self, type_: str, **subject_match) -> bool:
        for t in self.st["tasks"]:
            if t["type"] == type_ and t["status"] == "done":
                subj = t.get("subject", {})
                if all(subj.get(k) == v for k, v in subject_match.items()):
                    return True
        return False

    def _task_settled(self, type_: str, **subject_match) -> bool:
        """Done OR deliberately abandoned. Recreation triggers for waivable
        round duties (evidence, sota_scan) must ask this, not _done_task: a
        cancelled duty is a recorded decision, and recreating it turned every
        abandonment into an infinite recreate loop."""
        for t in self.st["tasks"]:
            if t["type"] == type_ and t["status"] in ("done", "cancelled"):
                subj = t.get("subject", {})
                if all(subj.get(k) == v for k, v in subject_match.items()):
                    return True
        return False

    def node(self, nid: str) -> dict | None:
        return egraph.by_id(self.g).get(nid)

    def _autonomy(self) -> str:
        return self.cfg.get("policy", {}).get("autonomy", "gated")

    def _git_mode(self) -> bool:
        return (self.cfg.get("project") or {}).get("vcs") == "git"

    def _policy_projection_digest(self) -> str:
        """Digest of everything the strategist card renders from policy (R9).

        The tempo controls are legally mutable mid-run; what must not happen is
        the card and the live validator disagreeing about them."""
        policy = self.cfg.get("policy") or {}
        return hashlib.sha256(json.dumps(policy, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()

    def _node_training_paid(self, node: dict) -> bool:
        """True when this node's training compute has already been spent: the
        one shared predicate behind every trained-node death protection (a
        stuck terminal task, eval-failure exhaustion, repair-budget exhaustion
        and the escalation auto-reject exemption must all agree, or the
        protection has a bypass for every path that misses it)."""
        if int(node.get("eval_failures") or 0) > 0:
            return True
        if node.get("status") in ("workflow_done", "evaluating", "evaluated"):
            return True
        if node.get("workflow_reuse_seal"):
            return True
        # R9 (external audit r6): compute that is CURRENTLY BURNING is paid for
        # too. Counting only finished stage RUNs let on_stuck=abandon destroy a
        # node whose training was already bound and running on the platform -
        # the money was spent, the protection just could not see it yet.
        return any(r.get("node") == node.get("id") and r.get("kind") == "stage"
                   and (r.get("status") == "finished" or erun.holds_external_slot(r))
                   for r in self.st.get("runs", []))

    def _capture_commit(self, node: dict) -> None:
        # v11: the implement-path HEAD spawn this used to make was provably dead
        # (its write is unconditionally overwritten by
        # _activate_implementation_selector moments later); the remaining
        # callers get the memoized status probe, so repeat calls in one
        # invocation cost nothing.
        if not self._git_mode() or not node.get("workdir"):
            return
        commit = evcs.head_commit(eutil.rpath(self.store.repo, node["workdir"]))
        if commit:
            node["commit"] = commit
        else:
            self.store.event("engine", "git_commit_capture_failed", node=node["id"])

    def _lane_dir(self, lane: dict) -> str:
        return f".evo/rounds/{lane['round']}/lanes/{lane['id']}"

    def _needs_theory(self, lane: dict) -> bool:
        return lane.get("search_origin") == "theory_derived" or bool(lane.get("theory_required"))

    def _slots(self) -> int:
        memo = self._infra_memo if isinstance(self._infra_memo, dict) else {}
        return einfra.slots_from_facts(self.store, self.cfg, facts=memo.get("facts"))

    def _running_stage_runs(self) -> list[dict]:
        return [r for r in self.st.get("runs", [])
                if r.get("kind") == "stage" and erun.holds_external_slot(r)]

    def _slots_free(self) -> int:
        return max(0, self._slots() - len(self._running_stage_runs()))

    def _spec(self, node: dict) -> dict:
        return eutil.read_json(eutil.rpath(self.store.repo, node["spec"]), {}) or {}

    def _spec_index(self) -> dict[str, dict]:
        return {str(node.get("id")): self._spec(node) for node in self.g.get("nodes", [])
                if node.get("id") and node.get("spec")}

    def _spec_from(self, relp: str) -> dict:
        return eutil.read_json(eutil.rpath(self.store.repo, relp), {}) or {}

    def _lane_of(self, subj: dict) -> dict:
        lane = self.store.get_lane(self.st, subj.get("lane"))
        if lane is None:
            raise SystemExit(f"[evo] missing lane {subj.get('lane')} (engine bug)")
        return lane

    def _next_sweep_scope(self) -> tuple[set[str], set[str]] | None:
        """The (lanes, nodes) the imminent scheduling decision consumes, or
        None for a full-web sweep.

        `evo next` used to re-audit EVERY object the project ever created on
        every call - 48-88% of a steady-state next, growing with project age
        while per-round work does not. submit/gate/absorb already use scoped
        sweeps for the same contract, and doctor owns the full-history audit.
        The full-web tripwire is kept on a CADENCE (every K invocations or T
        minutes, whichever first), persisted OUTSIDE state.json so a no-op next
        stays a no-op. The cadence is count/time based on purpose: the state
        fingerprint cannot see artifact bytes, so it can never be the trigger.
        Fail-closed for everything the decision CONSUMES is unchanged.
        """
        pol = self.cfg.get("policy", {})
        if str(pol.get("next_sweep", "scoped")) == "full" or self.st.get("phase") != "rounds":
            return None
        marker_path = eutil.rpath(self.store.repo, ".evo/cache/sweep_cadence.json")
        try:
            marker = eutil.read_json(marker_path, {}) or {}
        except (SystemExit, OSError):
            # A corrupt cache file must degrade to the SAFE mode (full sweep),
            # never brick `evo next`.
            marker = {}
        if not isinstance(marker, dict):
            marker = {}
        try:
            count = int(marker.get("count") or 0) + 1
        except (TypeError, ValueError):
            count = 10 ** 9  # type-corrupt cache degrades to the SAFE mode: full sweep
        every = max(1, int(pol.get("full_sweep_every", 8) or 8))
        max_min = max(1, int(pol.get("full_sweep_max_minutes", 30) or 30))
        stale = True
        last = str(marker.get("last_full_at") or "")
        if last:
            try:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                delta_s = (datetime.now(timezone.utc) - dt).total_seconds()
                # A last_full_at in the future is clock skew or corruption:
                # treat as stale, fail safe.
                stale = delta_s > max_min * 60 or delta_s < 0
            except ValueError:
                stale = True
        if count >= every or stale:
            # Do NOT reset here: the tripwire re-arms only after the full sweep
            # SUCCEEDS (compute_next writes the reset). A full sweep that fails
            # closed used to have already reset the counter, silently disarming
            # the tripwire for the next K calls.
            return None
        eutil.write_json_atomic(marker_path, {"count": count, "last_full_at": last})
        rid = str(self.st.get("current_round") or "")
        lanes = {str(l.get("id")) for l in self.st.get("lanes", []) if l.get("round") == rid}
        idx = egraph.by_id(self.g)
        nodes: set[str] = set()
        for n in self.g.get("nodes", []):
            if n.get("round") == rid or n.get("role") in ("baseline", "platform") \
                    or n.get("status") in ("executing", "evaluating", "evaluated"):
                nodes.add(str(n.get("id")))
        for l in self.st.get("lanes", []):
            if l.get("round") == rid:
                for p in (l.get("parents") or []):
                    nodes.add(str(p))
        for n in egraph.frontier(self.g, self.cfg, self.st) + egraph.performance_frontier(self.g, self.cfg, self.st):
            nodes.add(str(n.get("id")))
        # Active recoveries: _next_recovery reads and mutates their target
        # nodes/lanes regardless of round (R1 finding: a replaying recovery's
        # target was schedulable while out of scope).
        for case in self.st.get("recoveries", []):
            if case.get("status") in ("planned", "fork_required", "repairing", "replaying"):
                scope_obj = case.get("scope") or {}
                if scope_obj.get("kind") == "node":
                    nodes.add(str(scope_obj.get("id")))
                elif scope_obj.get("kind") == "lane":
                    lanes.add(str(scope_obj.get("id")))
        # Nodes referenced by OPEN gates: gate presentation reads them.
        for gate in self.st.get("gates", []):
            if gate.get("status") == "open":
                gs = gate.get("subject") or {}
                if gs.get("node"):
                    nodes.add(str(gs.get("node")))
                if gs.get("lane"):
                    lanes.add(str(gs.get("lane")))
        # One hop of parents AND code parents plus frozen comparators:
        # comparator lookups, bundle inputs and effective-ancestor chains
        # resolve through them.
        for nid in list(nodes):
            row = idx.get(nid) or {}
            for p in (row.get("parents") or []):
                nodes.add(str(p))
            if row.get("code_parent"):
                nodes.add(str(row.get("code_parent")))
            if row.get("effect_comparator_node"):
                nodes.add(str(row.get("effect_comparator_node")))
        return lanes, nodes

    def compute_next(self) -> dict:
        evcs.begin_invocation()
        self._assert_frozen_contract()
        scope = self._next_sweep_scope()
        if scope is None:
            self._assert_artifact_seals()
            # Re-arm the cadence tripwire only AFTER the full sweep passed.
            eutil.write_json_atomic(
                eutil.rpath(self.store.repo, ".evo/cache/sweep_cadence.json"),
                {"count": 0, "last_full_at": eutil.utc_now()})
        else:
            scope_lanes, scope_nodes = scope
            self._assert_artifact_seals(scope_lanes=scope_lanes, scope_nodes=scope_nodes,
                                        check_snapshots=False)
        before = eutil.state_fingerprint(self.st, self.g, self.reg)
        out = self._compute_next_inner()
        # A deferred abandon_request surfaces exactly when nothing else is
        # actionable: the proposal never blocks live work, and the user still
        # sees it at the next natural pause. R7: "done" is a natural pause too
        # - the old waiting-only surface let a project reach DONE with the
        # proposal permanently buried (deciding it there was a silent no-op).
        # A proposal whose subject already ended is cancelled, not presented.
        if out.get("kind") in ("waiting", "done"):
            for gate in list(self.store.open_gates(self.st)):
                if gate.get("kind") != "abandon_request":
                    continue
                subj = gate.get("subject") or {}
                node = self.node(str(subj.get("node") or ""))
                lane = self.store.get_lane(self.st, str(subj.get("lane") or ""))
                if (node is not None and node.get("status") in ("concluded", "abandoned")) \
                        or (lane is not None and lane.get("status") in ("done", "abandoned")):
                    gate["status"] = "cancelled"
                    gate["resolved_at"] = eutil.utc_now()
                    gate["note"] = "subject reached a terminal state before the user decided"
                    self.store.event("engine", "gate_cancelled", gate=gate.get("id"),
                                     reason="abandon_request_subject_terminal")
            pending = next((g for g in self.store.open_gates(self.st)
                            if g.get("kind") == "abandon_request"), None)
            if pending is not None:
                out = self._present_gate(pending)
        # R9 audit: every next carries the standing-obligation notices so no
        # parallel duty stays invisible behind the single primary surface.
        notices = self._standing_notices()
        if notices:
            out["notices"] = notices
        # runs/gates/tasks may have changed (absorption, new tasks): keep the
        # user's live dashboard current even between submits.  `next` is
        # idempotent and the operator protocol calls it repeatedly, so a call
        # that changed nothing skips the three-file rewrite and the dashboard
        # render instead of bumping state_revision and rewriting ~1 MB per
        # no-op.  The persisted rendered-state marker covers every mutation
        # path OUTSIDE this method (rejected submits, gate decisions, holds):
        # if some command saved state without rendering, the next no-op call
        # re-renders once even though nothing changed here.
        after = eutil.state_fingerprint(self.st, self.g, self.reg)
        if after != before:
            edash.render(self.store, self.g, self.cfg, self.st, self.reg,
                         infra_memo=self._infra_memo, fingerprint=after)
            self.save()
        else:
            marker_path = edash.rendered_marker_path(self.store)
            marker = eutil.read_text(marker_path) if marker_path.exists() else ""
            # R9 audit: compare the FULL marker (state triple + config
            # projection) so a config-only tempo change re-renders too.
            if marker.strip() != edash.marker_value(self.st, self.g, self.reg, self.cfg,
                                                    fingerprint=after):
                edash.render(self.store, self.g, self.cfg, self.st, self.reg,
                             infra_memo=self._infra_memo, fingerprint=after)
        return out

    def _compute_next_inner(self) -> dict:
        st = self.st
        # 0. absorb externally finished/failed runs (engine bookkeeping, no attention needed)
        self._absorb_finished_runs()
        recovery_out = self._next_recovery()
        if recovery_out is not None:
            return recovery_out
        active_holds = [row for row in st.get("holds", []) if row.get("status") == "active"]
        blocking_holds = [row for row in active_holds
                          if (row.get("scope") or {}).get("kind") == "project"
                          or ((row.get("scope") or {}).get("kind") == "round" and
                              (row.get("scope") or {}).get("id") == st.get("current_round"))]
        if blocking_holds:
            hold_ids = [str(row.get("id")) for row in blocking_holds]
            return {"kind": "waiting",
                    "reason": "authority-changing scheduling is paused by hold(s) "
                              + ", ".join(hold_ids)
                              + "; external RUN facts may still be reported/reconciled."
                              + self._hold_waiting_suffix(hold_ids)}
        if st.get("phase") == "done":
            # R9 audit (root cause): "finished" is a PROVED claim, not a phase
            # bit. Four audit rounds patched individual done WRITE points
            # while this READ point returned the verdict unexamined - so a
            # done written by any path (baseline abandonment, legacy states)
            # buried live recoveries, running external jobs and open evidence
            # obligations. One predicate now guards the verdict itself.
            blockers = self._terminal_blockers()
            if blockers:
                return self._blocked_terminal_surface(blockers)
            closed = self._closed_rounds()
            return {"kind": "done", "reason": st.get("terminal_reason") or "evolution finished",
                    "rounds": closed}
        # 1. a gate awaiting the user blocks everything - EXCEPT an
        # abandon_request (v11 R2): that gate is the agent's own proposal to
        # stop, and its advertised contract is "work stays schedulable until
        # the user decides". Blocking on it would make proposing an early exit
        # strictly worse than riding the dead direction. It is presented only
        # when nothing else is actionable (deferred below).
        for gate in self.store.open_gates(st):
            if gate.get("kind") == "abandon_request":
                continue
            # R9 (external audit r6): a resource gate must be re-settled against
            # LIVE capacity before it is shown - otherwise a gate whose deficit
            # disappeared (a sibling RUN settled under its cap) keeps preempting
            # all scheduling, and the honest REJECT destroys a node that is now
            # perfectly affordable.
            if self.refresh_resource_gate(gate):
                continue
            resolved = self._maybe_auto_resolve(gate)
            if not resolved:
                return self._present_gate(gate)
        # an auto-resolution may have STOPPED the run (e.g. full_auto against a
        # blocked provision pass) - re-check before scheduling anything further
        if st.get("phase") == "done":
            return {"kind": "done", "reason": st.get("terminal_reason") or "evolution stopped",
                    "rounds": self._closed_rounds()}
        # 1b. a task parked at hold release (queued_after_hold: another task
        # legitimately held the one-open-card floor at that moment) is
        # reopened HERE, the single point that can see the floor is free.
        # A parked task whose subject was re-covered by a newer task, or
        # whose subject reached a terminal state while parked, is stale:
        # cancel it instead of resurrecting a second authority card.
        if not self.store.open_tasks(st):
            self._reopen_queued_tasks()
        # 2. an already-open task is THE task - except a stage_watch, which is a
        #    placeholder: if the world changed and real work exists, it yields.
        watch = None
        open_tasks = self.store.open_tasks(st)
        if open_tasks:
            t = open_tasks[0]
            if t["type"] != "stage_watch":
                # R8 (external audit r5): a mid-run tempo change (documented
                # raw policy.preset edit) left an already-materialized
                # open_round showing the OLD preset while the live validator
                # enforced the new one - the authoritative card contradicted
                # its own validation. Rebuild the strategy projection when the
                # preset drifted (same refresh recovery uses).
                if t["type"] == "open_round":
                    # R9 (external audit r6): compare the WHOLE rendered policy
                    # projection, not the preset word - a legal custom->custom
                    # tempo edit (e.g. max_exploit_share) changed what the live
                    # validator enforces while the card kept the old numbers and
                    # `next` still reported "unchanged".
                    current_policy = self._policy_projection_digest()
                    if t.get("policy_digest") is None:
                        # Pre-binding (v11.2) task: it carried only the preset
                        # WORD. Adopt the digest without churn when that word
                        # still matches; refresh when it drifted while unbound
                        # - silently adopting swallowed the one drift v11.2
                        # itself would have caught.
                        legacy_preset = t.pop("policy_preset", None)
                        current_preset = str((self.cfg.get("policy") or {}).get("preset") or "")
                        if legacy_preset is not None and str(legacy_preset) != current_preset:
                            self._refresh_open_round_task(t)
                            self.store.event("engine", "open_round_policy_refreshed",
                                             task=t.get("id"), preset=current_preset)
                        t["policy_digest"] = current_policy
                    elif str(t.get("policy_digest")) != current_policy:
                        self._refresh_open_round_task(t)
                        t["policy_digest"] = current_policy
                        self.store.event("engine", "open_round_policy_refreshed",
                                         task=t.get("id"),
                                         preset=str((self.cfg.get("policy") or {}).get("preset") or ""))
                return self._present_task(t)
            watch = t
            self._open_watch = t
        out = self._phase_next()
        if watch is not None and not (out.get("kind") == "task" and out.get("task") == watch["id"]):
            watch["status"] = "done"
            watch.pop("_render", None)
            watch["updated_at"] = eutil.utc_now()
            self.store.event("engine", "watch_superseded", task=watch["id"])
        return out

    def _phase_next(self) -> dict:
        st = self.st
        # 2c. v11.7: an adopted facts revision owes a fresh canary proof.
        # The re-minted infra_drill task takes priority over ordinary rounds
        # work; stage/eval launches are refused meanwhile (validator-side).
        if st.get("infra_revision_pending") and st["phase"] == "rounds":
            drill = next((t for t in st.get("tasks", [])
                          if t.get("type") == "infra_drill"
                          and t.get("status") in ("open", "paused", "stuck")), None)
            if drill is None:
                drill = self._create_task(
                    "infra_drill", {"round": None},
                    [".evo/profile/INFRA_DRILLS.md", ".evo/profile/INFRA_DRILLS.json"],
                    inputs=[(".evo/profile/INFRA_PROFILE.md", "the prose infra profile"),
                            (str((self.cfg.get("infra") or {}).get("facts_file")
                                 or ".evo/profile/INFRA_FACTS.json"),
                             "the REVISED machine facts to drill")],
                    extra_blocks=[("Infrastructure facts (REVISED - re-prove the real path)",
                                   einfra.infra_block(self.store, self.cfg))])
            if drill.get("status") == "open":
                return self._present_task(drill)
        # 3. bootstrap
        if st["phase"] == "bootstrap":
            nxt = self._next_bootstrap()
            if nxt is not None:
                return nxt
            st["phase"] = "rounds"
            self.store.event("engine", "phase_rounds")
        # 4. rounds
        return self._next_rounds()

    def _present_task(self, task: dict) -> dict:
        if task.get("status") == "paused" and (task.get("held_by") or []):
            # R10-009: a duty whose task is paused under an active hold is
            # NOT schedulable - presenting it (or minting a twin for it)
            # would walk the duty around the review the pause exists for.
            holds = ", ".join(str(h) for h in (task.get("held_by") or []))
            return {"kind": "waiting",
                    "reason": (f"task {task.get('id')} ({task.get('type')}) is paused by hold(s) "
                               f"{holds} - the duty resumes when the hold ends (a recovery hold "
                               "ends with its case; a plain hold with 'evo resume --hold ... "
                               "--note ...')")}
        # R11 interruption audit: presented_at alone lied after a torn
        # _reject window (card bytes rewritten on disk, state rolled back) -
        # "Card unchanged" pointed at a file that HAD changed. The receipt is
        # the card bytes themselves.
        card_digest = ""
        try:
            card_path = eutil.rpath(self.store.repo, str(task.get("card") or ""))
            if task.get("card") and card_path.is_file():
                card_digest = hashlib.sha256(card_path.read_bytes()).hexdigest()
        except OSError:
            card_digest = ""
        represented = bool(task.get("presented_at")) and bool(card_digest) \
            and str(task.get("presented_card_digest") or "") == card_digest
        if not represented:
            task["presented_at"] = eutil.utc_now()
            task["presented_card_digest"] = card_digest
        return {"kind": "task", "task": task["id"], "type": task["type"],
                "card": task.get("card"), "bundle": task.get("bundle"),
                "outputs": task.get("outputs", []), "attempts": task.get("attempts", 0),
                "represented": represented, "attempt": int(task.get("attempts", 0)) + 1}

    def _present_gate(self, gate: dict) -> dict:
        fields = {
            "GATE_ID": gate["id"], "GATE_KIND": gate["kind"], "SUMMARY": gate.get("summary", ""),
            "REPO": self.store.repo.as_posix(),
            "SUBJECT": json.dumps(gate.get("subject", {}), ensure_ascii=False),
            "REPORT": "\n".join(self._gate_report(gate)),
        }
        card = ecards.render("gate", fields)
        gdir = self.store.evo / "gates"
        eutil.write_text(gdir / f"{gate['id']}.md", card)
        return {"kind": "gate", "gate": gate["id"], "gate_kind": gate["kind"],
                "summary": gate.get("summary", ""), "card": f".evo/gates/{gate['id']}.md"}

    def _next_bootstrap(self) -> dict | None:
        done = set(self.st.get("bootstrap_done", []))
        if "project_scan" not in done:
            blocks = []
            note = self._last_gate_note("infra_confirm")
            if note:
                blocks.append(("The user rejected the previous bootstrap contract",
                               [f"- {note}",
                                "- rescan the affected evidence and carry the correction into the draft"]))
            return self._present_task(self._create_task(
                "project_scan", {"round": None},
                [".evo/profile/PROJECT_DISCOVERY.md", ".evo/profile/PROJECT_DISCOVERY.json"],
                inputs=[(".evo/ONBOARDING.md", "questions to resolve with the user before configuration"),
                        (".evo/config.json", "untrusted skeleton; do not treat empty/default fields as facts")],
                extra_blocks=blocks))
        # v11.7: the engine-fit verdict gates everything after the scan. A
        # non-fit overall stops here until the USER decides - proceed with the
        # assessment on record, or stop with the gap named. Fit projects fall
        # straight through with zero extra surface.
        fit_overall = self._engine_fit_overall()
        if fit_overall in ("degraded", "unfit"):
            fit_gate = self.store.get_gate(self.st, self.st.get("engine_fit_gate") or "")
            if fit_gate is None:
                fit_gate = self.store.new_gate(
                    self.st, "engine_fit_blocked", {},
                    f"The discovery scan judged this project '{fit_overall}' for this engine's "
                    "task class or shape assumptions. Read the assessment (violated rows carry "
                    "their consequence) in .evo/profile/PROJECT_DISCOVERY.md/.json. Approve to "
                    "proceed ANYWAY with the assessment on record; reject to stop now instead "
                    "of failing repeatedly mid-evolution.")
                self.st["engine_fit_gate"] = fit_gate["id"]
            if fit_gate["status"] == "open":
                if not self._maybe_auto_resolve(fit_gate):
                    return self._present_gate(fit_gate)
        # v11.7: the preparation pass runs BEFORE configure, so the contract is
        # frozen against observed reality instead of guesses. It exists only
        # when the scan recorded needs_preparation; certified-running projects
        # skip it entirely.
        if "provision" not in done and self._provision_needed():
            blocks: list[tuple[str, list[str]]] = []
            prev = eutil.read_json(eutil.rpath(self.store.repo, ".evo/profile/PROVISION.json"), None)
            if isinstance(prev, dict) and prev.get("status") == "blocked":
                blocks.append(("Previous cycle's blockers (verify each is now resolved)",
                               [f"- {b.get('missing')} (needed for: {b.get('needed_for')})"
                                for b in prev.get("blockers") or []] or ["- none recorded"]))
            note = self._last_gate_note("provision_blocked", statuses=("approved",))
            if note:
                blocks.append(("The user's note on what they supplied", [f"- {note}"]))
            worklist = self._discovery_worklist()
            if worklist:
                blocks.append(("The scan's preparation worklist (do these, then prove the number)",
                               worklist))
            return self._present_task(self._create_task(
                "provision", {"round": None},
                [".evo/profile/PROVISION.md", ".evo/profile/PROVISION.json"],
                inputs=[(".evo/profile/PROJECT_DISCOVERY.json",
                         "scanned facts, readiness worklist and the draft evaluation map to prove"),
                        (".evo/profile/PROJECT_DISCOVERY.md", "human-readable discovery report"),
                        (".evo/config.json", "untrusted skeleton; the REAL facts you observe here "
                                             "feed its completion next")],
                extra_blocks=blocks + [("Execution-error journal",
                                        ebundle.errors_block(self.store, self.cfg, st=self.st)
                                        or ["- empty"])]))
        if "configure" not in done:
            return self._present_task(self._create_task(
                "configure", {"round": None}, [".evo/config.json"],
                inputs=[(".evo/config.json", "the config skeleton to complete (edit in place)"),
                        (".evo/profile/PROJECT_DISCOVERY.json", "scanned facts, draft topology, open questions and resource envelope"),
                        (".evo/profile/PROJECT_DISCOVERY.md", "human-readable discovery report")]
                       + ([(".evo/profile/PROVISION.json",
                            "what preparation actually observed (real metric keys, data locations, "
                            "landing paths) - freeze the contract against THESE facts"),
                           (".evo/profile/PROVISION.md", "the preparation report")]
                          if eutil.rpath(self.store.repo, ".evo/profile/PROVISION.json").exists()
                          else [])))
        if "infra" not in done:
            blocks = []
            note = self._last_gate_note("infra_confirm")
            if note:
                blocks.append(("The user rejected the previous infra review with this note",
                               [f"- {note}", "- address it explicitly in the new facts"]))
            facts_rel = str((self.cfg.get("infra") or {}).get("facts_file") or ".evo/profile/INFRA_FACTS.json")
            return self._present_task(self._create_task(
                "infra", {"round": None},
                [".evo/profile/INFRA_PROFILE.md", facts_rel],
                inputs=self._infra_inputs(), extra_blocks=blocks))
        if "infra_interview" not in done:
            facts_rel = str((self.cfg.get("infra") or {}).get("facts_file") or ".evo/profile/INFRA_FACTS.json")
            blocks = [("Infrastructure facts distilled so far", einfra.infra_block(self.store, self.cfg))]
            note = self._last_gate_note("infra_confirm")
            if note:
                blocks.append(("The user rejected the previous review with this note", [f"- {note}"]))
            return self._present_task(self._create_task(
                "infra_interview", {"round": None}, [".evo/profile/INFRA_REVIEW.md"],
                inputs=self._infra_inputs() + [(facts_rel, "the machine-readable facts under review"),
                                               (".evo/profile/INFRA_PROFILE.md", "the prose infra profile")],
                extra_blocks=blocks))
        gate = self.store.get_gate(self.st, self.st.get("infra_gate") or "")
        if gate is None:
            gate = self.store.new_gate(self.st, "infra_confirm", {},
                                       "Infrastructure review ready: .evo/profile/INFRA_REVIEW.md lists "
                                       "contradictions, unknowns, and the full dataset-task-metric success "
                                       "contract (roles, margins, absolute goals, aggregation, assumptions), plus "
                                       "the project-wide resource limits. This user approval freezes the bootstrap "
                                       "contract and only then enables configured automation. Reject with a note "
                                       "to rescan and rebuild the contract.")
            self.st["infra_gate"] = gate["id"]
        if gate["status"] == "open":
            if not self._maybe_auto_resolve(gate):
                return self._present_gate(gate)
        if "infra_drill" not in done:
            canary_blocks = [("Infrastructure facts (confirmed at the gate)",
                               einfra.infra_block(self.store, self.cfg))]
            retry_note = self._last_gate_note("infra_canary_blocked",
                                              statuses=("approved", "rejected"))
            if retry_note:
                canary_blocks.append(("User note after the blocked canary", [f"- {retry_note}"]))
            return self._present_task(self._create_task(
                "infra_drill", {"round": None},
                [".evo/profile/INFRA_DRILLS.md", ".evo/profile/INFRA_DRILLS.json"],
                inputs=[(".evo/profile/INFRA_PROFILE.md", "the prose infra profile"),
                        (str((self.cfg.get("infra") or {}).get("facts_file")
                             or ".evo/profile/INFRA_FACTS.json"), "the confirmed machine facts to drill")],
                extra_blocks=canary_blocks))
        if "profile" not in done:
            return self._present_task(self._create_task(
                "profile", {"round": None}, [".evo/profile/PROJECT_PROFILE.md",
                                                  ".evo/profile/BASELINE_PROGRAM.json"],
                inputs=[(".evo/config.json", "project + metric declarations"),
                        (".evo/profile/INFRA_PROFILE.md", "the infrastructure profile")]))
        if "dossier" not in done:
            return self._present_task(self._create_task(
                "dossier", {"round": None}, [".evo/profile/PROBLEM_DOSSIER.md"],
                inputs=[(".evo/config.json", "the frozen evaluation contract"),
                        (".evo/profile/PROJECT_PROFILE.md", "the verified project facts")]))
        if "rubric" not in done:
            return self._present_task(self._create_task(
                "rubric", {"round": None}, [".evo/profile/INNOVATION_RUBRIC.md"],
                inputs=[(".evo/profile/PROJECT_PROFILE.md", "project facts"),
                        (".evo/profile/BASELINE_PROGRAM.json", "the actual current scientific program"),
                        (".evo/profile/PROBLEM_DOSSIER.md", "repair-route bottlenecks and external invariants")]))
        if "sota_scan" not in done and econfig.sota_enabled(self.cfg) \
                and not self._task_settled("sota_scan", round=None):
            # R7: _task_settled, not bootstrap_done membership alone - an
            # exhausted/cancelled bootstrap scan is a recorded decision, and
            # recreating it with fresh attempts was an infinite loop (the
            # round-refresh trigger already asked the right predicate).
            res = self.cfg.get("research") or {}
            return self._present_task(self._create_task(
                "sota_scan", {"round": None},
                [".evo/evidence/SOTA.jsonl", ".evo/evidence/SOTA_NOISE.md"],
                extra_fields={"SOTA_YEAR": str(res.get("sota_recent_year") or ""),
                              "SOTA_VENUES": ", ".join(str(v) for v in (res.get("sota_venues") or [])),
                              "SOTA_MIN": str(self.cfg.get("budgets", {}).get("sota_min_entries", 5))},
                inputs=[(".evo/profile/PROJECT_PROFILE.md", "the task/dataset/metric this library must match"),
                        (".evo/profile/PROBLEM_DOSSIER.md", "the problem the SOTA entries must be about"),
                        (".evo/config.json", "metric spec (headline numbers should be in these terms when shared)")]))
        # baseline node pipeline
        base = next((n for n in self.g["nodes"] if n["role"] == "baseline"), None)
        if base is None:
            nid = self.store.next_id(self.st, "N")
            base = egraph.new_node(self.g, nid, title="Baseline (unmodified project)", role="baseline",
                                   parents=[], code_parent=None, level=0, lane=None, round_=None,
                                   idea_doc=None, spec=f".evo/nodes/{nid}/NODE_SPEC.json",
                                   experiment_purpose="candidate")
            self.store.event("engine", "node_created", node=nid, role="baseline")
        else:
            # R9 (external audit r6): ADOPTING an existing graph row must also
            # cover its id in the committed counter. A crash between the graph
            # write and the state commit leaves baseline N001 on disk with
            # counters.N=0; this branch then adopts it WITHOUT allocating, the
            # state commits with the counter still behind, and the first
            # candidate later allocates N001 - whose ghost-cleanup would delete
            # the real, adopted baseline. The invariant "graph id above the
            # counter = uncommitted debris" only holds if adoption fast-forwards
            # the counter.
            tail = str(base.get("id") or "")[1:]
            if tail.isdigit() and int(tail) > int(self.st.get("counters", {}).get("N", 0)):
                self.st.setdefault("counters", {})["N"] = int(tail)
                self.store.event("engine", "counter_adopted_graph_id", kind="N", value=int(tail),
                                 node=base.get("id"))
        if base.get("status") == "abandoned":
            # R10-003: even this stop routes through the unified writer - an
            # abandoned baseline may still have live orphan RUNs or open
            # evidence obligations behind it, and the first DONE is the one a
            # standard operator stops on.
            return self._terminal_verdict(
                "baseline authority is abandoned; fork the project to continue",
                event="evolution_stopped")
        if base["status"] == "proposed":
            if not self._done_task("baseline_spec", node=base["id"]):
                return self._present_task(self._create_task(
                    "baseline_spec", {"node": base["id"], "round": None},
                    [f".evo/nodes/{base['id']}/NODE_SPEC.json"],
                    extra_fields={"NODE": base["id"]},
                    inputs=[(".evo/profile/PROJECT_PROFILE.md", "runtime commands and layout"),
                            (".evo/profile/INFRA_PROFILE.md", "platform commands and paths"),
                            (".evo/config.json", "metric spec the eval must produce")]))
        # The provision pass (pre-configure) was the one bootstrap step allowed
        # to repair/extend supplied code. Freeze the executable head before
        # exposing the smoke card, so run-smoke and its later submission audit
        # exactly the same bytes.
        if base["status"] == "approved" and not base.get("implementation_seal"):
            self._seal_baseline_implementation(base)
        if base["status"] not in ("concluded", "abandoned"):
            out = self._next_node_task(base)
            if out is not None:
                return out
            return self._watch_or_wait()
        return None

    def _engine_fit_overall(self) -> str:
        """The scan's engine-fit verdict ('' before the scan wrote one)."""
        disc = eutil.read_json(eutil.rpath(self.store.repo, ".evo/profile/PROJECT_DISCOVERY.json"), None)
        if not isinstance(disc, dict):
            return ""
        fit = disc.get("engine_fit")
        return str((fit or {}).get("overall") or "") if isinstance(fit, dict) else ""

    def _provision_needed(self) -> bool:
        """True when the scan recorded needs_preparation (v11.7).

        Absent/legacy discovery files read as certified-running - an already
        mid-bootstrap project keeps its old sequence instead of being forced
        through a step its scan never defined."""
        disc = eutil.read_json(eutil.rpath(self.store.repo, ".evo/profile/PROJECT_DISCOVERY.json"), None)
        if not isinstance(disc, dict):
            return False
        readiness = disc.get("readiness")
        return isinstance(readiness, dict) and str(readiness.get("mode") or "") == "needs_preparation"

    def _discovery_worklist(self) -> list[str]:
        disc = eutil.read_json(eutil.rpath(self.store.repo, ".evo/profile/PROJECT_DISCOVERY.json"), None)
        rows = ((disc or {}).get("readiness") or {}).get("worklist") if isinstance(disc, dict) else None
        return [f"- {r.get('item')}: {r.get('why')}" for r in rows
                if isinstance(r, dict)] if isinstance(rows, list) else []

    def _closed_rounds(self) -> int:
        return len([r for r in self.st.get("rounds", []) if r.get("closed_at")])

    def _standing_notices(self) -> list[str]:
        """R9 audit: next returns ONE primary surface, but a complex project
        carries parallel standing obligations that used to become visible
        only after every other surface drained - each audit round found
        another buried combination (launch_unknown behind its own card, a
        held terminal RUN behind unrelated work, a planned review behind an
        open task). One builder, appended to every next output. Scheduling
        order is untouched: this is visibility, not priority."""
        notes: list[str] = []
        if self.st.get("infra_revision_pending"):
            notes.append("an adopted INFRA_FACTS revision still owes its canary re-proof - new "
                         "stage/eval spend is refused meanwhile; the canary task is presented "
                         "once the current open card settles")
        for case in self.st.get("recoveries", []):
            if case.get("status") in ("planned", "fork_required"):
                notes.append(f"recovery {case.get('id')} awaits the HUMAN - "
                             + self._recovery_review_hint(case))
        for r in self.st.get("runs", []):
            status = str(r.get("status") or "")
            rid = str(r.get("id") or "")
            if status == "launch_unknown":
                notes.append(f"RUN {rid} launch UNKNOWN - check the platform for its attempt "
                             f"token FIRST; 'evo run-bind --run {rid} ...' if the job exists, "
                             f"'evo run-confirm-not-launched --run {rid}' after proving it does "
                             "not; never start a second job for one prepared attempt")
            elif erun.needs_reconciliation(r):
                covering = erecover.active_holds_for_subject(
                    self.st, self.g, node=str(r.get("node") or "") or None, run=rid or None)
                if covering:
                    # R10-008: a hold OWNED by an active recovery case must
                    # never be answered with a generic "resume first" - for a
                    # planned case that resume CANCELS the pending review,
                    # and for an applied case the resume is refused while
                    # run-reconcile works directly (the case's own hold never
                    # defers its own RUN's adoption).
                    case_by_hold = {str(c.get("hold") or ""): c
                                    for c in self.st.get("recoveries", [])
                                    if c.get("status") in ("planned", "fork_required",
                                                           "repairing", "replaying")}
                    plain = [h for h in covering if h not in case_by_hold]
                    owned = [h for h in covering if h in case_by_hold]
                    after = ("its factual failure absorbs automatically"
                             if status in ("failed", "cancelled")
                             else f"'evo run-reconcile --run {rid}' adopts its evidence")
                    if owned and not plain:
                        case = case_by_hold[owned[0]]
                        if case.get("status") in ("planned", "fork_required"):
                            notes.append(
                                f"RUN {rid} ({status}) waits under recovery {case.get('id')}'s own "
                                f"hold - decide the case ({self._recovery_review_hint(case)}); do "
                                "NOT 'evo resume' that hold, it cancels the pending review")
                        else:
                            notes.append(
                                f"RUN {rid} ({status}) belongs to recovery {case.get('id')} "
                                f"({case.get('status')}) - {after} directly; the case's own hold "
                                "does not defer it")
                    else:
                        owned_note = (
                            f" (hold(s) {', '.join(owned)} belong to recovery case(s) - decide "
                            "those cases instead of resuming them)" if owned else "")
                        notes.append(f"RUN {rid} ({status}) waits under hold(s) "
                                     f"{', '.join(covering)} - 'evo resume --hold {plain[0]} "
                                     f"--note ...' first{owned_note}, then {after}")
                else:
                    notes.append(f"RUN {rid} evidence {r.get('evidence_status')} - "
                                 f"'evo run-reconcile --run {rid} ...' "
                                 "(--accept-missing-evidence if permanently unavailable)")
        if len(notes) > 8:
            notes = notes[:8] + [f"(+{len(notes) - 8} more standing obligations; 'evo status' lists all)"]
        return notes

    def _blocked_terminal_surface(self, blockers: list[dict]) -> dict:
        """The waiting surface shown instead of DONE while obligations live -
        shared by the done READ point and every same-call DONE writer."""
        recovery_b = next((b for b in blockers if b["kind"] == "recovery"), None)
        if recovery_b is not None and all(b["kind"] == "recovery" for b in blockers):
            return {"kind": "waiting",
                    "reason": (f"the project is otherwise finished, but recovery "
                               f"{recovery_b.get('id')} is still open - "
                               + str(recovery_b.get("hint") or "finish it first")
                               + "; the terminal verdict returns after it ends")}
        repeat_b = next((b for b in blockers if b["kind"] == "repeat_obligation"), None)
        if repeat_b is not None and all(b["kind"] == "repeat_obligation" for b in blockers):
            return {"kind": "waiting",
                    "reason": ("the project is otherwise finished, but "
                               + str(repeat_b.get("hint") or "an approved repeat measurement is owed")
                               + "; the terminal verdict returns after it settles")}
        return self._watch_or_wait()

    def _write_terminal_phase(self, reason: str, *, event: str, **event_kw) -> None:
        """Sweep G-5: the ONE writer for every semantic stop that cannot
        return a scheduling surface (gate decision arms, cascade stops).
        Behavior matches the historical direct writes - the phase lands and
        the done READ point keeps arbitrating live obligations - but the
        write itself now records when blockers were still open, so a torn
        world is visible in the ledger instead of only at the next read."""
        self.st["phase"] = "done"
        self.st.setdefault("terminal_reason", reason)
        blockers = self._terminal_blockers()
        if blockers:
            self.store.event("engine", "terminal_phase_with_open_obligations",
                             reason=reason,
                             blockers=[{k: b.get(k) for k in ("kind", "id")} for b in blockers[:8]])
        self.store.event("engine", event, reason=reason, **event_kw)

    def _terminal_verdict(self, reason: str, *, event: str, **event_kw) -> dict:
        """R10-003: DONE is WRITTEN only through the same predicate the read
        point verifies. Every earlier round patched individual write points
        (pending-recovery here, nothing there) while live orphan RUNs and
        open evidence obligations slid past - the first next after a
        recover-abort returned DONE with external compute still burning, and
        a standard operator correctly stops on the first DONE. If anything
        blocks, the phase stays alive and the blocker surface is returned;
        the verdict lands on a later call once the world is actually
        settled."""
        blockers = self._terminal_blockers()
        if blockers:
            return self._blocked_terminal_surface(blockers)
        self.st["phase"] = "done"
        self.st.setdefault("terminal_reason", reason)
        self.store.event("engine", event, reason=reason, **event_kw)
        return {"kind": "done", "reason": self.st.get("terminal_reason") or reason,
                "rounds": self._closed_rounds()}

    def _terminal_blockers(self) -> list[dict]:
        """Everything that must settle before a terminal verdict is honest.

        R9 audit: consulted by the done READ point (and usable by any close
        logic). Three blocker kinds, each carrying its surface:
        - an active recovery case (planned/fork_required/repairing/replaying);
        - a RUN that may still be executing externally (launch_unknown or
          running - orphaned ones included: abandoning a node never stops its
          external job);
        - a terminal RUN whose evidence obligation is still open
          (needs_reconciliation: late materials or an explicit terminal
          disposition are still owed)."""
        out: list[dict] = []
        case = self._pending_recovery_case()
        if case is not None:
            out.append({"kind": "recovery", "id": case.get("id"),
                        "hint": self._recovery_review_hint(case)})
        for r in self.st.get("runs", []):
            status = str(r.get("status") or "")
            if status in ("launch_unknown", "running"):
                out.append({"kind": "run_active", "id": r.get("id"), "status": status})
            elif erun.needs_reconciliation(r):
                out.append({"kind": "run_obligation", "id": r.get("id"),
                            "evidence": r.get("evidence_status")})
        # R10-013: an approved repeat_measure whose engine-run second
        # measurement has not settled is an open obligation exactly like a
        # live RUN - a terminal verdict may not bury a purchase the user
        # already authorized.
        for n in self.g.get("nodes", []):
            if self._repeat_run_pending(n) is not None:
                out.append({"kind": "repeat_obligation", "id": n.get("id"),
                            "hint": (f"node {n.get('id')} owes its approved repeat measurement "
                                     f"(seed {n.get('repeat_pending_seed')!r}); let the scheduler "
                                     "finish the repeat lane, or 'evo waive-repeat' releases it")})
        return out

    def _pending_recovery_case(self) -> dict | None:
        """An ACTIVE recovery case. Every phase=done write point must consult
        this (R9 added it to rounds_max; the R7 audit found the open_round
        failure spiral skipped it): DONE must not bury an in-flight recovery -
        nothing re-presents the case or its hold after the phase flips.
        repairing/replaying count too: _next_recovery legitimately returns
        None while the case's RUN is in flight or its node is parked, and a
        done write in that window buried live training under DONE."""
        return next((c for c in self.st.get("recoveries", [])
                     if c.get("status") in ("planned", "fork_required",
                                            "repairing", "replaying")), None)

    @staticmethod
    def fork_handoff_lines(case: dict) -> list[str]:
        """The fork handoff, rebuilt from the persisted case (R8 audit: it
        used to exist only on the stdout of the session that planned the
        case, so a fresh session had 'follow the printed handoff' pointing at
        text that no longer existed anywhere)."""
        actions = {str(a) for a in (case.get("action") or [])}
        cid = str(case.get("id") or "?")
        if "fork_lane" in actions:
            return [
                f"fork_lane handoff (terminal diagnosis, no apply): 1) retire the damaged lane "
                f"NOW: evo recover-abort --recovery {cid} --reason 'superseded by fork' "
                "--abandon-node (a lane case abandons the lane, and its node when one exists); "
                "2) build the replacement lane via the NEXT open_round; "
                "3) record the linkage: evo log --note 'fork of <old lane id>: <why>'."]
        if "fork_project" in actions:
            return [
                f"fork_project handoff (terminal diagnosis, no apply): 1) KEEP the hold; "
                "2) build the replacement world with a fresh 'evo init' project; "
                "3) record the linkage: evo log --note 'fork of this project: <why>'; "
                f"4) only then close this case: evo recover-abort --recovery {cid} "
                "--reason 'superseded by fork'."]
        return [
            f"fork_node handoff (terminal diagnosis, no apply): while the round is OPENING the "
            "scheduler re-mints the strategy card under this hold automatically - keep the hold, "
            "build the replacement via that open_round, record the linkage (evo log --note "
            f"'fork of <old id>: <why>'), and close last: evo recover-abort --recovery {cid} "
            "--reason 'superseded by fork' --abandon-node. If the current round is still "
            "RUNNING, retire first (the same recover-abort --abandon-node) and build the "
            "replacement in the round that follows."]

    @classmethod
    def _recovery_review_hint(cls, case: dict) -> str:
        """The status- and action-correct exit verbs for an active recovery
        case. A fork-classified case has NO apply path - printing
        recover-apply for it (which the uniform status line used to do even
        for planned cases whose action was already fork_*) sent the operator
        into a wall."""
        status = str(case.get("status") or "")
        actions = {str(a) for a in (case.get("action") or [])}
        forkish = bool(actions & {"fork_node", "fork_lane", "fork_project"})
        if status == "fork_required" or (status == "planned" and forkish):
            return ("this diagnosis is terminal (no apply path): "
                    + " ".join(cls.fork_handoff_lines(case)))
        if status == "planned":
            return (f"PRESENT its plan at {case.get('plan_path')} (digest "
                    f"{case.get('plan_digest')}) to the USER and wait for their decision - that "
                    "wait is a legitimate stop. On their approval: 'evo recover-apply --recovery "
                    f"{case.get('id')} --confirm {case.get('plan_digest')}' (applies exactly the "
                    "reviewed plan); otherwise 'evo recover-abort'")
        return (f"it is {status}; run 'evo next' to continue it, settle its external RUN facts "
                "(run-update / run-reconcile), or 'evo recover-abort' to terminate it")

    def _hold_waiting_suffix(self, hold_ids: list[str]) -> str:
        """R7 audit: a hold waiting used to print only the hold id. When the
        hold belongs to a recovery awaiting review, the next step is already
        engine-determined (read THIS plan, apply exactly it, or abort) - and a
        fresh session's only standard entry point is `next`, so the full
        handoff must be re-presented HERE, not just on the stdout of the
        session that created the plan. The generic 'evo resume' hint is also
        wrong for those holds (resume CANCELS the pending case)."""
        wanted = {str(h) for h in hold_ids}
        parts: list[str] = []
        for case in self.st.get("recoveries", []):
            if str(case.get("hold") or "") not in wanted:
                continue
            status = str(case.get("status") or "")
            if status in ("planned", "fork_required"):
                parts.append(
                    f" Recovery {case.get('id')} ({status}) owns this hold: "
                    + self._recovery_review_hint(case)
                    + ". Do NOT release this hold with 'evo resume' - that cancels the "
                    "pending case.")
            elif status in ("repairing", "replaying"):
                parts.append(
                    f" Recovery {case.get('id')} ({status}) owns this hold; run 'evo next' "
                    "again to continue it, or 'evo recover-abort' to terminate it.")
        return "".join(parts)

    def _next_rounds(self) -> dict:
        st, cfg = self.st, self.cfg
        bud = cfg.get("budgets", {})
        if st.get("round_status") in (None, "closed"):
            if st.get("spiral_stop_pending_recovery"):
                # R7 audit: the open_round failure spiral tried to stop while a
                # recovery review was pending. Mint no further rounds (the
                # spiral verdict stands); present the review until decided,
                # then let the deferred stop land.
                pending_case = self._pending_recovery_case()
                if pending_case is not None:
                    return {"kind": "waiting",
                            "reason": (f"the round strategist failed repeatedly (stop deferred), and "
                                       f"recovery {pending_case.get('id')} is still "
                                       f"{pending_case.get('status')} - "
                                       + self._recovery_review_hint(pending_case)
                                       + "; the project stops after that case ends")}
                # R10-003: the spiral verdict lands through the unified
                # writer - live orphan RUNs / open evidence obligations defer
                # it exactly like a pending recovery review always did. The
                # deferral flag survives until the verdict actually lands, or
                # a blocked attempt would silently resume minting rounds.
                st["terminal_reason"] = (
                    "open_round failed and was force-closed repeatedly with no successfully "
                    "closed round in between - the round strategist cannot produce a legal "
                    "portfolio here; fix the config/state and restart")
                out = self._terminal_verdict(st["terminal_reason"], event="evolution_stopped")
                if out.get("kind") == "done":
                    st.pop("spiral_stop_pending_recovery", None)
                return out
            closed = self._closed_rounds()
            if bud.get("rounds_max", 0) and closed >= bud["rounds_max"]:
                # R9 (external audit r6) + R10-003: DONE must not bury an
                # in-flight recovery review, a live orphan RUN or an open
                # evidence obligation - the unified writer consults the SAME
                # blocker predicate the read point verifies.
                return self._terminal_verdict(f"rounds_max={bud['rounds_max']} reached",
                                              event="evolution_done", rounds=closed)
            need_gate = closed > 0 and (self._autonomy() == "gated" or bud.get("rounds_max", 0) == 0)
            if need_gate and not self._round_continue_approved(closed):
                gate = self.store.new_gate(st, "round_continue", {"after_rounds": closed},
                                           f"{closed} round(s) closed. Continue with a new round?")
                resolved = self._maybe_auto_resolve(gate)
                if not resolved:
                    return self._present_gate(gate)
            rid = eutil.fmt_id("R", int(st["counters"].get("R", 0)) + 1, 3)
            st["counters"]["R"] = int(st["counters"].get("R", 0)) + 1
            st["current_round"] = rid
            st["round_status"] = "opening"
            self.store.event("engine", "round_opening", round=rid)
            return self._present_task(self._mint_open_round_task(rid))
        if st.get("round_status") == "opening":
            # A node-scoped recovery hold legitimately PAUSES the open_round
            # task (pending_authority_consumers tags every open round task as a
            # frontier-projection consumer). That is a waiting state, not an
            # inconsistency: crashing here sent the user to 'doctor --fix',
            # which has no repair for it, while the real exits are the
            # recovery verbs.
            paused = next((t for t in self.st["tasks"]
                           if t["type"] == "open_round" and t["status"] == "paused"), None)
            if paused is not None:
                # R9 (external audit r6): when the pausing hold belongs to a
                # TERMINAL fork diagnosis, this waiting state was a self-lock -
                # the printed handoff protocol says "build the replacement via
                # the next open_round" while the only open_round sat paused
                # under the very hold the protocol says to keep. A fork case
                # has no apply path, so cancel the stale projection and mint a
                # fresh one from current truth; the damaged authority stays
                # held and is excluded from legal parents by its own validator.
                holder_ids = {str(h) for h in (paused.get("held_by") or [])}
                # R10-010: fork_project is EXCLUDED from the local re-mint -
                # its handoff is "keep the hold, build the replacement world
                # in a fresh 'evo init' project"; re-minting a strategy card
                # in the OLD project's current round contradicted that
                # handoff in the same next output, and the held baseline
                # could re-enter as an execution source.
                project_fork = next(
                    (c for c in self.st.get("recoveries", [])
                     if str(c.get("hold") or "") in holder_ids
                     and c.get("status") in ("planned", "fork_required")
                     and "fork_project" in set(c.get("action") or [])), None)
                if project_fork is not None:
                    return {"kind": "waiting",
                            "reason": (f"recovery {project_fork.get('id')} is a fork_project "
                                       "diagnosis: this project's comparison world does not "
                                       "continue - no further rounds are minted here. "
                                       + " ".join(self.fork_handoff_lines(project_fork)))}
                fork_case = next(
                    (c for c in self.st.get("recoveries", [])
                     if str(c.get("hold") or "") in holder_ids
                     and c.get("status") in ("planned", "fork_required")
                     and set(((c.get("action") or []))) & {"fork_node", "fork_lane"}),
                    None)
                if fork_case is not None:
                    paused["status"] = "cancelled"
                    paused.pop("_render", None)
                    paused["updated_at"] = eutil.utc_now()
                    self.store.event("engine", "open_round_task_cancelled", task=paused.get("id"),
                                     recovery=fork_case.get("id"),
                                     reason="stale projection under a terminal fork hold; re-minting")
                    # The re-mint IS the handoff: a fresh projection built from
                    # current truth, not paused by the fork hold (a hold's
                    # consumer set is frozen at plan time, and an opening
                    # round has no members the hold could cover). The damaged
                    # authority stays held; validators exclude it from legal
                    # parents, so the strategist routes around it.
                    fresh = self._mint_open_round_task(st["current_round"])
                    self.store.event("engine", "open_round_task_minted",
                                     task=fresh.get("id"), recovery=fork_case.get("id"),
                                     round=st["current_round"])
                    return self._present_task(fresh)
                else:
                    # R9: after a session/context loss this WAITING is the only
                    # surface a fresh agent sees - it must carry the review
                    # handoff (plan path + digest + exact commands), not just
                    # "finish the recovery".
                    case_now = next(
                        (c for c in self.st.get("recoveries", [])
                         if str(c.get("hold") or "") in holder_ids
                         and c.get("status") in ("planned", "fork_required", "repairing", "replaying")),
                        None)
                    if case_now is not None and case_now.get("status") == "planned":
                        # status- AND action-aware: a fork-classified planned
                        # case must get the fork handoff here too, not a
                        # recover-apply that is guaranteed to refuse.
                        return {"kind": "waiting",
                                "reason": (f"recovery {case_now.get('id')} awaits the human: "
                                           + self._recovery_review_hint(case_now))}
                    return {"kind": "waiting",
                            "reason": ("the open_round task is paused by an active recovery hold; "
                                       "finish the recovery (evo recover-apply / recover-abort) or "
                                       "release its hold (evo resume) and run next again")}
            return self._present_task(self._recover_open_task("open_round"))
        rid = st["current_round"]
        # SOTA refresh cadence (research mode): rolling benchmarks go stale -
        # every K rounds the library is re-scanned before new evidence lands
        if econfig.sota_enabled(cfg):
            k_ref = int((cfg.get("research") or {}).get("sota_refresh_rounds") or 0)
            if k_ref and int(rid[1:]) % k_ref == 0 and not self._task_settled("sota_scan", round=rid):
                res = cfg.get("research") or {}
                # R8 audit: bind only STAMPED accepted history (a shadowed
                # stamp branch meant no project ever had a sota watermark; the
                # raw-file fallback froze cancelled tasks' unaccepted tails)
                sota_n, sota_digest = evalid.stamped_ledger_watermark(st, "sota")
                return self._present_task(self._create_task(
                    "sota_scan", {"round": rid,
                                  "prior_sota_count": sota_n,
                                  "prior_sota_digest": sota_digest},
                    [".evo/evidence/SOTA.jsonl", ".evo/evidence/SOTA_NOISE.md"],
                    extra_fields={"SOTA_YEAR": str(res.get("sota_recent_year") or ""),
                                  "SOTA_VENUES": ", ".join(str(v) for v in (res.get("sota_venues") or [])),
                                  "SOTA_MIN": str(cfg.get("budgets", {}).get("sota_min_entries", 5))},
                    inputs=[(".evo/evidence/SOTA.jsonl", "the current library - APPEND new entries "
                                                         "(continue S### ids); rows accepted by an earlier "
                                                         "submit are immutable history (prefix-checked at "
                                                         "submit; a cancelled task's leftovers stay "
                                                         "repairable); express a superseded claim by "
                                                         "appending the newer S# row"),
                            (".evo/profile/PROJECT_PROFILE.md", "the task/dataset/metric terms")]))
        # Gap-triggered evidence refresh. A fixed "new papers every round" tax
        # rewards title collection and is skipped when coverage is already live.
        if not self._task_settled("evidence", round=rid) and self._round_needs_evidence_refresh(rid):
            prior, prior_digest = evalid.ledger_watermark(st, "evidence", self.store.evidence())
            # F14: a positive evidence_min_new_per_round is the explicit
            # per-round contract; the when-gap floor applies only to
            # gap-triggered refreshes (v9.2 always used the gap floor and the
            # configured per-round count was never enforced anywhere).
            min_new = int(cfg.get("budgets", {}).get("evidence_min_new_per_round", 0) or 0)
            if min_new <= 0:
                min_new = econfig.budget(cfg, "evidence_refresh_min_when_gap")
            task = self._create_task(
                "evidence", {"round": rid, "prior_evidence_count": prior, "min_new": min_new,
                             "prior_digest": prior_digest},
                [".evo/evidence/EVIDENCE.jsonl"],
                inputs=self._profile_inputs() + [(f".evo/rounds/{rid}/PORTFOLIO.json", "this round's lanes and bottlenecks"),
                                                 (".evo/evidence/EVIDENCE.jsonl", "existing pool (continue E### numbering)")],
                extra_fields={"PRIOR_COUNT": str(prior), "MIN_NEW": str(min_new),
                              # R5: the card must state EVERY enforced floor -
                              # on an empty pool the real work is the total
                              # floor, not the refresh increment.
                              "TOTAL_MIN": str(econfig.budget(cfg, "evidence_min_total")),
                              "PER_B_MIN": str(econfig.budget(cfg, "evidence_min_per_bottleneck"))})
            return self._present_task(task)
        # nodes in flight first (executing nodes are non-blocking: they are skipped
        # unless a run finished; launch-ready nodes wait for a free slot)
        waiting_on_runs = False
        for n in sorted(self.g["nodes"], key=lambda x: x["id"]):
            if n.get("round") != rid or n["status"] in ("concluded", "abandoned"):
                continue
            if n["status"] in ("executing", "evaluating"):
                waiting_on_runs = True
                continue
            out = self._next_node_task(n)
            if out is not None:
                return out
            waiting_on_runs = True  # launch deferred by full slots
        # lanes by most-advanced stage
        lanes = [l for l in st["lanes"] if l["round"] == rid and l["status"] not in ("done", "abandoned")]
        illegal = [l for l in lanes if l.get("status") not in econfig.LANE_STATUSES]
        if illegal:
            raise SystemExit("[evo] refusing to continue/close the round: unknown lane status(es) "
                             + ", ".join(f"{l.get('id')}={l.get('status')!r}" for l in illegal)
                             + ". Run 'evo doctor'.")
        lanes.sort(key=lambda l: (-eflow.LANE_STAGE_ORDER.get(l["status"], 0), l["id"]))
        for lane in lanes:
            out = self._next_lane_task(lane)
            if out is not None:
                return out
            if lane.get("node") and (self.node(lane["node"]) or {}).get("status") == "executing":
                waiting_on_runs = True
        # R9 (external audit r6): abandoning a node does NOT stop its external
        # job - the RUN is marked orphaned and left running on purpose, so the
        # execution fact stays honest. But the round then closed and the project
        # could reach DONE while real compute burned, holding a stage slot and a
        # reservation, with no card ever telling the agent to reconcile it. A
        # live orphan is unfinished business: keep the watch/reconcile channel
        # open until it reaches a terminal state.
        # ANY live orphan holds the channel open, whichever round abandoned it
        # (RUN rows carry no round field; the old per-round filter read a key
        # that is never written and so was inert - saying so honestly).
        live_orphans = [str(r.get("id")) for r in self.st.get("runs", [])
                        if r.get("orphaned") and not erun.is_terminal(r)]
        if live_orphans:
            waiting_on_runs = True
        # R9 audit: an open EVIDENCE obligation blocks the close exactly like
        # a live job does - a terminal RUN still owed late materials (or an
        # explicit terminal disposition via run-reconcile
        # --accept-missing-evidence) used to be forgotten by close/DONE while
        # its landing stayed leased forever.
        if any(erun.needs_reconciliation(r) for r in self.st.get("runs", [])):
            waiting_on_runs = True
        if waiting_on_runs:
            return self._watch_or_wait()
        # close the round
        if erecover.is_held(self.st, self.g, round_=rid):
            return self._watch_or_wait()
        # R7 audit: a closer for this round may already exist but sit PAUSED
        # under a recovery hold - impact scans mark every open/paused
        # close_round a frontier-projection consumer, and the round-subject
        # is_held check above cannot see that task-only coverage. Minting a
        # second closer created two authority cards over the same RETIRE file
        # and let one round be accepted twice. Wait on the existing one.
        parked_closer = next((t for t in self.st.get("tasks", [])
                              if t.get("type") == "close_round"
                              and (t.get("subject") or {}).get("round") == rid
                              and t.get("status") in ("open", "paused", "stuck")), None)
        if parked_closer is not None:
            if parked_closer.get("status") == "open":
                return self._present_task(parked_closer)
            return {"kind": "waiting",
                    "reason": (f"close_round task {parked_closer.get('id')} for round {rid} is "
                               f"{parked_closer.get('status')} (typically parked under a recovery "
                               "hold); finish the recovery (evo recover-apply / recover-abort) or "
                               "resolve its escalation instead of minting a second closer")}
        if not self._done_task("close_round", round=rid):
            # R7: the addendum is decision-bearing (B# ids gate repair lanes)
            # and append-only by card contract, but nothing bound the prior
            # bytes - a whole-file rewrite silently rebound history. Freeze
            # the prefix at task creation, checked at submit.
            add_p = self.store.profile_dir() / "DOSSIER_ADDENDUM.md"
            add_bytes = add_p.read_bytes() if add_p.exists() else b""
            task = self._create_task(
                "close_round", {"round": rid,
                                "prior_addendum_len": len(add_bytes),
                                "prior_addendum_digest":
                                    hashlib.sha256(add_bytes).hexdigest() if add_bytes else ""},
                [f".evo/rounds/{rid}/RETIRE.json"],
                inputs=[(f".evo/rounds/{rid}/PORTFOLIO.json", "what this round planned"),
                        (".evo/views/FRONTIER.md", "frontier after this round"),
                        (".evo/views/GRAPH.md", "full graph")],
                extra_blocks=[("This round's lanes and outcomes", self._round_summary_block(rid)),
                              ("Frontiers, origin and per-cell records",
                               ebundle.frontier_block(self.g, self.cfg, self.st))])
            return self._present_task(task)
        return {"kind": "waiting", "reason": "round closed; run next again"}

    def _watch_or_wait(self) -> dict:
        """Nothing else to do while workflow stages/background evals are in flight:
        issue a watch task for the oldest running run so the agent goes and
        checks the platform."""
        w = getattr(self, "_open_watch", None)
        if w is not None and w.get("status") == "open":
            # R7 audit: the watch card is a cached placeholder; when a sibling
            # RUN became settle-able (or got settled) after the card was cut,
            # re-present it with the fresh actionable list instead of a stale
            # "nothing else is actionable" claim.
            current = sorted(str(r.get("id") or "") for r in self.st.get("runs", [])
                             if erun.needs_reconciliation(r) and r.get("status") != "launch_unknown")
            if current == list(w.get("reconcilable_runs") or []):
                return self._present_task(w)
            w["status"] = "done"
            w.pop("_render", None)
            w["updated_at"] = eutil.utc_now()
            self.store.event("engine", "watch_superseded", task=w["id"],
                             reason="reconcilable run set changed")
            self._open_watch = None
        running = self.store.running_runs(self.st)
        if not running:
            pending = [r for r in self.st.get("runs", []) if erun.needs_reconciliation(r)]
            if pending:
                run = sorted(pending, key=lambda row: str(row.get("id") or ""))[0]
                # R9 audit: when an ACTIVE hold covers this RUN, the true
                # first step is resume - reconcile is refused for
                # failed/cancelled outright and re-deferred for finished, so
                # the old hint looped on a command that could not advance.
                covering = erecover.active_holds_for_subject(
                    self.st, self.g, node=str(run.get("node") or "") or None,
                    run=str(run.get("id") or "") or None)
                if covering:
                    after = ("its factual failure is absorbed automatically"
                             if str(run.get("status")) in ("failed", "cancelled")
                             else f"then 'evo run-reconcile --run {run.get('id')} ...' adopts its evidence")
                    # R10 self-audit: never front-recommend resuming a hold an
                    # active recovery case owns (planned: resume cancels the
                    # review; applied: resume is refused and reconcile works
                    # directly) - the resume verb points at a PLAIN hold only.
                    case_holds = {str(c.get("hold") or "") for c in self.st.get("recoveries", [])
                                  if c.get("status") in ("planned", "fork_required",
                                                         "repairing", "replaying")}
                    plain = [h for h in covering if h not in case_holds]
                    first_step = (f"FIRST 'evo resume --hold {plain[0]} --note ...' "
                                  "(or finish that hold's recovery); after the release, "
                                  if plain else
                                  "the covering hold(s) belong to recovery case(s) - decide/finish "
                                  "the case(s) (see the suffix below), then ")
                    return {"kind": "waiting",
                            "reason": (f"run {run.get('id')} ({run.get('status')}) finished under "
                                       f"active hold(s) {', '.join(covering)} - {first_step}{after}."
                                       + self._hold_waiting_suffix(list(covering)))}
                return {"kind": "waiting",
                        "reason": f"run {run.get('id')} execution={run.get('status')} has "
                                  f"evidence={run.get('evidence_status')}; attach late files with "
                                  f"'evo run-reconcile --run {run.get('id')} ...'. If the materials are "
                                  "confirmed PERMANENTLY unavailable, that disposition is a USER "
                                  f"decision: 'evo run-reconcile --run {run.get('id')} "
                                  "--accept-missing-evidence --note ...' closes the obligation on "
                                  "record (--accept-missing-probe for a registered probe). Waiting "
                                  "for that answer is a legitimate stop. No replacement run is "
                                  "authorized."}
            holds = [row for row in self.st.get("holds", []) if row.get("status") == "active"]
            if holds:
                hold_ids = [str(row.get("id")) for row in holds]
                suffix = self._hold_waiting_suffix(hold_ids)
                generic = ("; reconcile external facts or use 'evo resume --hold H### --note ...'."
                           if not suffix else ";")
                return {"kind": "waiting",
                        "reason": "work is paused by active hold(s) "
                                  + ", ".join(hold_ids) + generic + suffix}
            return {"kind": "waiting", "reason": "no runnable task; run 'evo doctor' if this persists"}
        uncertain = [r for r in running if r.get("status") == "launch_unknown"]
        if uncertain:
            run = sorted(uncertain, key=lambda row: str(row.get("id") or ""))[0]
            return {"kind": "waiting",
                    "reason": f"run {run.get('id')} may have launched. Check the platform/token, then use "
                              "run-bind for the found job or run-confirm-not-launched after proving none exists. "
                              "Do not create another attempt while launch is unknown."}
        run = sorted(running, key=lambda r: r["id"])[0]
        node = self.node(run["node"]) or {}
        # R7: one card watched both run kinds and its hard rule ("workflow is
        # required for an implementation failure") is WRONG for an eval RUN -
        # an evaluator-only fix is --repair-scope evaluation, and the engine
        # accepts the destructive value silently, replaying paid training.
        scope_rule = (
            "This is an EVALUATION run: for an implementation failure choose the scope "
            "honestly - `--repair-scope evaluation` when the edit is confined to "
            "evaluator-owned code (completed workflow evidence is preserved), "
            "`--repair-scope workflow` only when training/data/workflow code must "
            "change (that replay invalidates and re-pays the whole workflow)."
            if run.get("kind") == "eval" else
            "`--repair-scope workflow` is required for an implementation failure: a "
            "stage-code change can invalidate the whole workflow, so the repeat-spend "
            "gate will disclose that whole replay.")
        # R7 audit: a terminal sibling awaiting late materials IS actionable
        # right now - hiding it until every unrelated job ended idled its
        # node, its reservation and its follow-up chain behind a possibly
        # hours-long run (and made this card's "nothing else is actionable"
        # claim false). Surface the reconcile verb alongside the watch.
        reconcilable = [r for r in self.st.get("runs", []) if erun.needs_reconciliation(r)
                        and r.get("status") != "launch_unknown"]
        reconcile_block = [
            f"- {r['id']} node {r['node']} execution={r.get('status')} "
            f"evidence={r.get('evidence_status')}: attach its late files NOW with "
            f"`evo run-reconcile --run {r['id']} ...` - do not wait for the running jobs"
            for r in sorted(reconcilable, key=lambda row: str(row.get("id") or ""))]
        task = self._create_task(
            "stage_watch", {"node": run["node"], "round": node.get("round"), "lane": node.get("lane"),
                            "run": run["id"]},
            [],
            extra_fields={"NODE": run["node"], "RUN_ID": run["id"], "JOB": str(run.get("job")),
                          "STAGE": str(run.get("stage") or ("evaluation" if run.get("kind") == "eval" else "stage")),
                          "REPAIR_SCOPE_RULE": scope_rule},
            inputs=self._node_inputs(node) if node else [],
            extra_blocks=[("All running jobs (workflow stages and background evals)",
                           [f"- {r['id']} node {r['node']} kind {r.get('kind')} stage {r.get('stage') or '-'} "
                            f"job {r.get('job')}"
                            for r in running])]
                         + ([("Terminal runs you can settle RIGHT NOW (actionable before any job ends)",
                              reconcile_block)] if reconcile_block else [])
                         + [("Platform commands", einfra.infra_block(self.store, self.cfg))])
        task["reconcilable_runs"] = sorted(str(r.get("id") or "") for r in reconcilable)
        return self._present_task(task)

    def _graph_consumer_sig(self) -> list:
        """Cheap change signature for graph-shaped facts whose formal
        consumers (rendered views + open strategy/close cards) must follow.
        Partial engine doubles in unit fixtures may lack g/st - they have no
        graph consumers, so an empty signature (never "changed") is exact."""
        g = getattr(self, "g", None) or {}
        st = getattr(self, "st", None) or {}
        return ([(str(n.get("id") or ""), str(n.get("status") or ""),
                  str(n.get("retire_reason") or ""), str(n.get("verdict") or ""))
                 for n in g.get("nodes", [])]
                + [(str(l.get("id") or ""), str(l.get("status") or ""))
                   for l in st.get("lanes", [])])

    def _sync_graph_consumers(self) -> None:
        """R8 audit: a graph-changing decision must update its formal
        consumers in the SAME persisted step. Gate decisions (abandon arms)
        and recovery aborts changed nodes/lanes/frontiers while the rendered
        FRONTIER/GRAPH views and an already-open close_round card kept the
        pre-decision world - the agent then filled RETIRE.json against one
        graph while validators judged another."""
        if not hasattr(self.store, "views_dir"):
            return  # unit-test store double without a rendering surface
        egraph.render_views(self.store, self.g, self.cfg, self.st)
        for task in self.st.get("tasks", []):
            if task.get("status") not in {"open", "paused", "stuck"}:
                continue
            if task.get("type") == "close_round":
                self._refresh_close_round_task(task)
            elif task.get("type") == "open_round":
                self._refresh_open_round_task(task)
            else:
                continue
            self.store.event("engine", "derived_consumer_refreshed",
                             task=task.get("id"), reason="graph changed")

    def _reopen_queued_tasks(self) -> None:
        """Give the one-open-card floor back to tasks parked by a hold release.

        ``queued_after_hold`` is written by ``_release_hold_in_memory`` when a
        sibling held the floor; this is its single consumer. At most ONE task
        reopens per call (the doctor invariant is at most one open agent
        task); stale parked tasks are cancelled with an event so no second
        authority card for the same subject can ever resurface.
        """
        st = self.st

        def _seq(t: dict) -> int:
            try:
                return int(str(t.get("id") or "T0")[1:])
            except ValueError:
                return 0

        parked = sorted((t for t in st.get("tasks", [])
                         if t.get("status") == "paused" and t.get("queued_after_hold")
                         and not (t.get("held_by") or [])), key=_seq)
        for t in parked:
            subj = t.get("subject") or {}
            node = self.node(str(subj.get("node") or "")) if subj.get("node") else None
            lane = self.store.get_lane(st, str(subj.get("lane") or "")) if subj.get("lane") else None
            round_closed = t.get("type") in ("open_round", "close_round") and any(
                r.get("id") == str(subj.get("round") or "") and r.get("closed_at")
                for r in st.get("rounds", []))
            stale = round_closed \
                or (node is not None and node.get("status") in ("concluded", "abandoned")) \
                or (lane is not None and lane.get("status") in ("done", "abandoned")) \
                or any(t2 is not t and t2.get("type") == t.get("type")
                       and (t2.get("subject") or {}) == subj
                       # R11 cold-start audit: an OPEN twin covers the duty
                       # regardless of id order - the old '_seq(t2) > _seq(t)'
                       # test pointed the wrong way for a duplicate parked by
                       # doctor --fix (kept card has the SMALLER id), so the
                       # pump re-opened the copy and a second authority card
                       # for the same subject resurfaced. A DONE twin still
                       # needs the sequence test: a duty re-minted AFTER an
                       # earlier completion is a new epoch and must reopen.
                       and (t2.get("status") == "open"
                            or (t2.get("status") == "done" and _seq(t2) > _seq(t)))
                       for t2 in st.get("tasks", []))
            if stale:
                t["status"] = "cancelled"
                t.pop("queued_after_hold", None)
                t.pop("_render", None)
                t["updated_at"] = eutil.utc_now()
                self.store.event("engine", "queued_task_cancelled", task=t.get("id"),
                                 reason="subject re-covered or terminal while parked")
                continue
            # R8 audit: a parked launch card whose RUN dropped back to
            # prepared holds no slot; reopening it into a full platform
            # would authorize a second concurrent stage. Leave it parked and
            # try the next candidate; submit re-proves the slot either way.
            if t.get("type") == "stage_launch":
                run_row = self.store.get_run(st, str(subj.get("run") or ""))
                if run_row is not None and not erun.holds_external_slot(run_row) \
                        and self._slots_free() <= 0:
                    continue
            t["status"] = "open"
            t.pop("queued_after_hold", None)
            t["updated_at"] = eutil.utc_now()
            # The world moved while this card was parked: rebuild bundle+card
            # from current truth and force a full re-present (not "unchanged").
            if t.get("type") == "close_round":
                self._refresh_close_round_task(t)
            else:
                self._rematerialize(t)
            self.store.event("engine", "queued_task_reopened", task=t.get("id"))
            return

    def _mint_open_round_task(self, rid: str) -> dict:
        """Create the strategy-round task from current truth (single mint point).

        Used both when a round first opens and when a terminal fork handoff
        cancels a stale pre-fork projection: the replacement world is built by
        THIS task, so cancelling without re-minting would strand the round in
        'opening' with no exit (the doctor has no repair for round_status).
        """
        task = self._create_task(
            "open_round", {"round": rid},
            [f".evo/rounds/{rid}/PORTFOLIO.json"],
            extra_fields=self._portfolio_fields(rid),
            **self._round_strategy_context(rid))
        # R8/R9: stamp the tempo projection the card was rendered under, so
        # any mid-run tempo change (preset switch OR a custom numeric edit)
        # refreshes the projection instead of presenting a card its own
        # validator contradicts.
        task["policy_digest"] = self._policy_projection_digest()
        return task

    def _recover_open_task(self, type_: str) -> dict:
        for t in self.st["tasks"]:
            if t["type"] == type_ and t["status"] == "open":
                return t
        # R9 audit (root-cause form of the r6 fix): the strategy projection is
        # DERIVED state - an opening round with no live card is not an
        # inconsistency to crash on, it is a projection to re-materialize.
        # Cancel sites multiplied across releases (fork handoff, recovery
        # abort's stale-projection cleanup, future ones) and pairing a re-mint
        # into each cancel site kept leaving one path uncovered; the CONSUMER
        # rebuilding on demand closes every past and future cancel path at
        # once. (The old SystemExit pointed at 'doctor --fix', which has no
        # such repair.)
        if type_ == "open_round":
            rid = str(self.st.get("current_round") or "")
            if rid:
                fresh = self._mint_open_round_task(rid)
                self.store.event("engine", "open_round_task_minted", task=fresh.get("id"),
                                 round=rid, reason="opening round had no live strategy card")
                return fresh
        raise SystemExit(f"[evo] inconsistent state: round_status=opening but no open {type_} task. Run 'evo doctor --fix'.")

    def _round_continue_approved(self, closed: int) -> bool:
        for g in self.st["gates"]:
            if g["kind"] == "round_continue" and g.get("subject", {}).get("after_rounds") == closed:
                return g["status"] == "approved"
        return False

    def _abandon_lane(self, lane: dict, reason: str) -> None:
        lane["status"] = "abandoned"
        lane["abandon_reason"] = reason
        self.store.event("engine", "lane_abandoned", lane=lane["id"], reason=reason)
        # R5 blind-operator audit: a pre-node lane abandonment used to leave
        # its open lane-subject task alive - the scheduler kept presenting it,
        # and a VALID submission then wrote lane.status back to a live stage,
        # silently undoing the user's approved stop; the only blind exit was
        # attempt exhaustion. Abandonment cancels everything the lane owns
        # (mirror of the node-side cleanup below).
        affected_tasks: set[str] = set()
        for task in self.st.get("tasks", []):
            if (task.get("subject") or {}).get("lane") != lane["id"] or \
                    task.get("status") not in {"open", "paused", "stuck"}:
                continue
            affected_tasks.add(str(task.get("id") or ""))
            if task.get("resource_reservation") and not task.get("resource_accounted"):
                released = dict(task.pop("resource_reservation", {}) or {})
                self.store.event("engine", "resource_reservation_released", task=task.get("id"),
                                 node=str((task.get("subject") or {}).get("node") or ""),
                                 usage=released, reason="task abandoned before side effect")
            task["status"] = "cancelled"
            task.pop("_render", None)
            task["cancel_reason"] = f"owning lane abandoned: {reason}"
            task["held_by"] = []
            task["updated_at"] = eutil.utc_now()
        for gate in self.st.get("gates", []):
            subject = gate.get("subject") or {}
            if gate.get("status") not in {"open", "paused"} or \
                    (subject.get("lane") != lane["id"] and
                     str(subject.get("task") or "") not in affected_tasks):
                continue
            gate["status"] = "cancelled"
            gate["decision_note"] = f"owning lane abandoned: {reason}"
            gate["held_by"] = []
        nid = lane.get("node")
        node = self.node(nid) if nid else None
        if node and node["status"] not in ("concluded", "abandoned"):
            self._abandon_node(node, f"lane abandoned: {reason}", cascade_lane=False)

    def _abandon_node(self, node: dict, reason: str, cascade_lane: bool = True) -> None:
        node["status"] = "abandoned"
        node["verdict"] = "failed"
        # R10 self-audit: abandonment retires every obligation the node owed -
        # including an approved-but-unsettled repeat measurement. Left in
        # place, its pending seed kept feeding the terminal blocker forever
        # while both advertised exits were closed (the scheduler never
        # touches an abandoned node, and waive refuses non-lane states) -
        # the same pairing the recovery retirement path already had.
        self._archive_repeat_measure(node, f"node abandoned: {reason}")
        # R11 matrix sweep (M4): the replacement-spend marker dies with the
        # node too (its gate is cancelled by the cascade below; the marker
        # alone would be an inert field claiming a decision is still owed).
        node.pop("repeat_attempt", None)
        egraph.touch(node)
        # Abandonment is terminal: this node will never reach conclude, so its
        # unresolved infrastructure failures would hang forever - and the nodes
        # that exhaust their retry budget are exactly the ones carrying the
        # most infra failures.  Close the ledger honestly instead: the entries
        # are marked unresolved (they never enter the playbook, which only
        # routes `fixed` rows) so `evo doctor` and the user can see what was
        # never explained.
        for eid in evalid.pending_infra_errors(self.ctx(), str(node.get("id") or "")):
            self._stage_error_resolution({
                "resolves": eid, "node": node["id"],
                "disposition": "unresolved_at_abandon", "surface": None,
                "fix": None, "note": reason,
            })
        self.store.event("engine", "node_abandoned", node=node["id"], reason=reason)
        if node.get("role") == "baseline":
            # No later decision is meaningful after the comparison authority
            # has been retired.  Recovery cannot resurrect it; continuation is
            # a new project authority world. (G-5: one terminal writer.)
            self._write_terminal_phase(f"baseline authority abandoned: {reason}",
                                       event="project_stopped_baseline_abandoned",
                                       node=node["id"])
        eartifact.invalidate_for_node(self.store, self.reg, node["id"], "producer abandoned")
        affected_tasks: set[str] = set()
        for task in self.st.get("tasks", []):
            if (task.get("subject") or {}).get("node") != node["id"] or \
                    task.get("status") not in {"open", "paused", "stuck"}:
                continue
            affected_tasks.add(str(task.get("id") or ""))
            if task.get("resource_reservation") and not task.get("resource_accounted"):
                released = dict(task.pop("resource_reservation", {}) or {})
                self.store.event("engine", "resource_reservation_released", task=task.get("id"),
                                 node=node["id"], usage=released,
                                 reason="task abandoned before side effect")
            task["status"] = "cancelled"
            # Terminal tasks never rematerialize: every _render consumer
            # (retry, escalation reopen, recovery pause) skips them, and the
            # rendered blocks it carries dominate state.json growth.
            task.pop("_render", None)
            task["cancel_reason"] = f"owning node abandoned: {reason}"
            task["held_by"] = []
            task["updated_at"] = eutil.utc_now()
        for gate in self.st.get("gates", []):
            subject = gate.get("subject") or {}
            if gate.get("status") not in {"open", "paused"} or \
                    (subject.get("node") != node["id"] and
                     str(subject.get("task") or "") not in affected_tasks):
                continue
            gate["status"] = "cancelled"
            gate["decision_note"] = f"owning node abandoned: {reason}"
            gate["held_by"] = []
        for run in self.st.get("runs", []):
            if run.get("node") != node["id"]:
                continue
            if erun.is_terminal(run):
                # R7 external audit: abandoning the DIRECTION does not erase an
                # already-executed fact. A finished RUN still awaiting
                # materials/settlement used to be skipped wholesale: its
                # reservation held project capacity forever and its open
                # reconciliation axis was buried under the terminal node (and
                # under DONE). Settle both axes honestly: bill the run
                # (reported usage, or the reserved cap when unreported) and
                # record the evidence gap as permanent - with the SAME receipt
                # protocol the abort-recovery disposition uses, or the run
                # shape violates erun's own invariant audit forever.
                settled = False
                if erun.holds_reservation(run):
                    self._account_run(run)
                    settled = True
                if erun.needs_reconciliation(run):
                    if run.get("adoption_status") == "candidate":
                        erun.transition_adoption(run, "quarantined",
                                                 note="owning node abandoned; evidence gap is permanent")
                    if run.get("status") == "finished":
                        if run.get("evidence_status") == "pending":
                            erun.transition_evidence(
                                run, "invalid",
                                note=f"never audited; owning node abandoned: {reason}")
                        receipt_rel = f".evo/runs/{run['id']}/evidence/IRRECOVERABLE.json"
                        eutil.write_json_atomic(eutil.rpath(self.store.repo, receipt_rel), {
                            "schema_version": 1, "run": run.get("id"), "node": node["id"],
                            "disposition": "irrecoverable_quarantined",
                            "reason": f"owning node abandoned: {reason}",
                            "evidence_status": run.get("evidence_status"),
                            "errors": list(run.get("evidence_errors") or []),
                            "recorded_at": eutil.utc_now(),
                        })
                        run["evidence_disposition"] = "irrecoverable_quarantined"
                        run["evidence_disposition_receipt"] = receipt_rel
                    else:
                        # failed/cancelled with an un-audited evidence axis:
                        # the disposition protocol is finished-only; close the
                        # axis the way confirmed-not-launched does.
                        erun.transition_evidence(
                            run, "complete",
                            note=f"no evidence will be supplied; owning node abandoned: {reason}")
                    settled = True
                if settled:
                    self.store.event("engine", "run_settled_on_abandon", run=run["id"],
                                     node=node["id"], status=run.get("status"),
                                     evidence=run.get("evidence_status"))
                continue
            if run.get("status") == "prepared":
                erun.transition_execution(run, "cancelled", note=f"prepared intent released: {reason}")
                erun.transition_evidence(run, "complete", note="confirmed no external launch")
                if run.get("adoption_status") == "candidate":
                    erun.transition_adoption(run, "quarantined", note="owning node abandoned before launch")
                self._charge_resource(node=node["id"], kind=str(run.get("kind") or "run"), usage={},
                                      basis="confirmed_unlaunched", run=run)
                run["absorbed"] = True
                self.store.event("engine", "prepared_run_cancelled", run=run["id"], node=node["id"])
            else:
                run["orphaned"] = True
                run["orphaned_reason"] = f"node abandoned: {reason}"
                if run.get("adoption_status") == "candidate":
                    erun.transition_adoption(run, "quarantined",
                                             note="owner abandoned; external outcome still requires reconciliation")
                self.store.event("engine", "run_orphaned_unresolved", run=run["id"], node=node["id"],
                                 status=run.get("status"))
        if cascade_lane and node.get("lane"):
            lane = self.store.get_lane(self.st, node["lane"])
            if lane and lane["status"] != "abandoned":
                lane["status"] = "abandoned"
                lane["abandon_reason"] = reason
                self.store.event("engine", "lane_abandoned", lane=lane["id"], reason=reason)

    def _abandon_task_subject(self, task: dict, note: str | None) -> None:
        subj = task.get("subject", {})
        reason = f"stuck task {task['id']} abandoned: {note or 'attempts exhausted'}"
        if task.get("resource_reservation") and not task.get("resource_accounted"):
            released = dict(task.pop("resource_reservation", {}) or {})
            self.store.event("engine", "resource_reservation_released", task=task.get("id"),
                             node=str(subj.get("node") or ""), usage=released,
                             reason="task abandoned before side effect")
        if subj.get("lane"):
            lane = self.store.get_lane(self.st, subj["lane"])
            if lane:
                self._abandon_lane(lane, reason)
                return
        if subj.get("node"):
            node = self.node(subj["node"])
            if node:
                self._abandon_node(node, reason)
                return
        if task["type"] == "open_round":
            self.st["round_status"] = "closed"
            self.st["rounds"].append({"id": subj.get("round"), "best_primary": self._observed_best(),
                                      "origin_primary": self._origin_primary(),
                                      "lanes": [], "improved": False, "closed_at": eutil.utc_now(),
                                      "note": reason})
            self.store.event("engine", "round_abandoned", round=subj.get("round"), reason=reason)
            # full_auto + on_stuck=abandon + rounds_max=0 would otherwise
            # force-close and reopen forever on a deterministic open_round
            # failure (attempts reset per fresh round: a macro-livelock with
            # unbounded rounds/gates/events growth - R3 logic audit). Three
            # consecutive strategist failures with zero settled work is a
            # project defect, not a scheduling blip: stop honestly.
            spiral = int(self.st.get("consecutive_forced_round_closes", 0)) + 1
            self.st["consecutive_forced_round_closes"] = spiral
            if spiral >= 3 and self.st.get("phase") != "done":
                # R7 audit: this DONE write point skipped the pending-recovery
                # guard the rounds_max path has - a planned/fork case and its
                # hold would be buried under the terminal phase forever. Keep
                # the spiral verdict on record but leave the phase alive until
                # the review is decided (next then re-presents the case).
                pending_case = self._pending_recovery_case()
                if pending_case is not None:
                    # No new rounds are minted while this flag stands (the
                    # spiral verdict holds), but the phase stays alive so
                    # next keeps presenting the review; done lands once the
                    # case is decided (see _next_rounds).
                    self.st["spiral_stop_pending_recovery"] = True
                    self.store.event("engine", "spiral_stop_deferred_for_recovery",
                                     recovery=pending_case.get("id"), spiral=spiral)
                    return
                self._write_terminal_phase(
                    f"open_round failed and was force-closed {spiral} times with no successfully "
                    "closed round in between - the round strategist cannot produce a legal "
                    "portfolio here; fix the config/state and restart",
                    event="evolution_stopped")
            return
        # The branches above cover every task family whose subject names a thing
        # that CAN be abandoned. The remaining families used to fall through as
        # a silent no-op: the task was cancelled, nothing changed, and the very
        # next scheduling pass recreated an identical task with attempts=0 -
        # so "reject = abandon" on their escalation gates was a lie, and under
        # full_auto + on_stuck=abandon the reject was automatic and the
        # recreate loop ran forever with unbounded task/gate/event growth.
        # Each family gets the honest semantics of "this duty will not be met":
        if task["type"] == "close_round":
            # The strategist could not produce a close review; force-close so
            # the run can move on, with the reason on the round record.
            # R7: improved=None, not False - the close REPORT failed, but the
            # round's real work may have moved the frontier (the node evidence
            # is already sealed). A hard False fed the stagnation window and
            # could force L3/moonshot rounds over a formatting failure;
            # _stagnant_window treats a non-bool as not-decisive. The forced-
            # close spiral counter is for OPEN_round strategist failures: a
            # round that ran its lanes is not that, so it breaks the streak.
            rid = str(subj.get("round") or "")
            # R8 (external audit r5): NEVER force-close a round that still has
            # active lanes (a mid-round injection may have legitimately
            # reopened work after this close task went stuck) - that stranded
            # the accepted lane in a closed round forever. Cancel the doomed
            # close instead; the scheduler re-mints it once the lanes finish.
            active = [l["id"] for l in self.st.get("lanes", [])
                      if l.get("round") == rid and l.get("status") not in ("done", "abandoned")]
            if active:
                self.store.event("engine", "close_round_task_cancelled", task=task.get("id"),
                                 round=rid, reason=f"force-close refused: active lanes {active}; "
                                                   "the scheduler re-mints close_round when they finish")
                return
            self.st["round_status"] = "closed"
            self.st["rounds"].append({"id": rid, "best_primary": self._observed_best(),
                                      "origin_primary": self._origin_primary(),
                                      "improved": None, "closed_at": eutil.utc_now(),
                                      "improvement_unassessed": "close_round report was force-abandoned",
                                      "lanes": [l["id"] for l in self.st.get("lanes", [])
                                                if l.get("round") == rid],
                                      "note": reason})
            self.st.pop("consecutive_forced_round_closes", None)
            self.store.event("engine", "round_force_closed", round=rid, reason=reason)
            return
        if task["type"] in ("evidence", "sota_scan"):
            # Round-scoped duties: abandoning waives them for THIS round only.
            # The cancelled task suppresses recreation (the triggers ask
            # _task_settled, not _done_task); the next round re-triggers
            # naturally if the gap persists.
            self.store.event("engine", "round_duty_waived", task=task.get("id"),
                             duty=task["type"], round=str(subj.get("round") or ""), reason=reason)
            return
        if task["type"] in eflow.BOOTSTRAP_SEQ or task["type"] == "baseline_spec":
            # Bootstrap is structurally unabandonable: without it nothing
            # downstream is meaningful. Abandoning it stops the evolution with
            # the reason on record instead of looping on recreation forever.
            # (infra_drill keeps its caller's dedicated stop with the
            # documented canary reason - do not double-report it here.)
            if task["type"] != "infra_drill" and self.st.get("phase") != "done":
                self.st["bootstrap_terminated"] = True
                self._write_terminal_phase(
                    f"bootstrap step {task['type']} abandoned - project cannot start",
                    event="evolution_stopped", note=reason)

    def validation_report(self, task_id: str, *, session: str | None = None) -> dict:
        """v12: read-only dry run of exactly what submit would validate.

        Purpose: burning an attempt on a schema mismatch teaches the agent to
        import engine internals for pre-validation - the field run did exactly
        that. This verb is the legal front door: it mirrors submit's
        precondition order and validator dispatch (KEEP IN LOCKSTEP with
        submit() below - any new pre-check added there must appear here) but
        never stamps provenance, never routes to _reject, never transitions,
        never saves. Refusal-class preconditions are converted to report rows
        instead of SystemExit so the agent learns everything in one call.

        Two honest caveats the caller must relay: (1) validators are read-only
        with ONE disclosed exception - a formalizable theorize task executes
        the agent's own TOY_CHECK.py exactly as submit would; (2) pass here is
        not an acceptance guarantee - transition-time postconditions (human
        study gate, post-transition seal sweep) run only at real submit.
        """
        evcs.begin_invocation()
        self._seal_digest_seed = {}
        report: dict = {"kind": "validation", "task": task_id, "errors": [], "notes": []}
        try:
            self._assert_frozen_contract()
        except SystemExit as exc:
            report["errors"] = [str(exc)]
            return report
        task = self.store.get_task(self.st, task_id)
        if task is None:
            raise SystemExit(f"[evo] no task {task_id}")
        report["type"] = task["type"]
        report["attempts"] = int(task.get("attempts") or 0)
        report["max_attempts"] = int(self.cfg.get("budgets", {}).get("max_attempts", 3))
        report["outputs"] = list(task.get("outputs") or [])
        sess = str(session or os.environ.get("EVO_SESSION") or "").strip()
        subject = task.get("subject") or {}
        allow_revision = (str(subject.get("node") or "")
                          if task.get("type") == "implement" and task.get("status") == "open" else None)
        try:
            self._assert_artifact_seals(
                allow_implementation_revision_node=allow_revision,
                only_lane=str(subject.get("lane") or "") or None,
                only_node=str(subject.get("node") or "") or None)
        except SystemExit as exc:
            report["errors"] = [str(exc)]
            return report
        if task["status"] != "open":
            report["notes"].append(f"task is {task['status']}, not open - submit would be refused")
            return report
        holding = erecover.active_holds_for_subject(
            self.st, self.g, lane=str(subject.get("lane") or "") or None,
            node=str(subject.get("node") or "") or None,
            run=str(subject.get("run") or "") or None,
            round_=str(subject.get("round") or "") or None)
        holding += [str(row.get("id") or "?") for row in self.st.get("holds", [])
                    if row.get("status") == "active"
                    and task_id in set(row.get("consumer_task_ids") or [])
                    and str(row.get("id") or "?") not in holding]
        authorized = {str(case.get("hold")) for case in self.st.get("recoveries", [])
                      if case.get("status") == "replaying" and case.get("hold")}
        holding = [h for h in holding if h not in authorized]
        if holding:
            report["notes"].append("submit would be paused by active hold(s) " + ", ".join(holding))
        if task["type"] == "stage_watch":
            report["notes"].append("stage_watch validates the RUN's terminal report, not authored "
                                   "outputs; there is nothing to dry-run - use run-update/run-reconcile")
            return report
        if str((self.cfg.get("policy") or {}).get("critic_isolation") or "") == "strict" \
                and task["type"] in ("sketch", "mature", "theorize", "implement") \
                and not sess:
            report["notes"].append("critic_isolation=strict: submit WITHOUT --session would be "
                                   "rejected (CRITIC_SESSION_AUTHOR_REQUIRED) before validation")
        validator = evalid.VALIDATORS.get(task["type"])
        if validator is None:
            raise SystemExit(f"[evo] no validator for task type {task['type']} (engine bug)")
        # Self-review F4: submit stamps task["session"] BEFORE validation so
        # critic-isolation checks judge the submitting session. Predict with
        # the same stamp on a COPY - never on the stored row - or the dry run
        # reports session deficiencies the real submit would not (and vice
        # versa against a stale stamp from an earlier rejected submit).
        probe_task = dict(task)
        if sess:
            probe_task["session"] = sess
        report["errors"] = validator(self.ctx(), probe_task)
        return report

    def submit(self, task_id: str, *, session: str | None = None) -> dict:
        # KEEP IN LOCKSTEP with validation_report() above: it mirrors this
        # method's precondition order and validator dispatch so the dry run
        # predicts real submission - a pre-check added here must appear there.
        evcs.begin_invocation()
        self._seal_digest_seed = {}
        self._assert_frozen_contract()
        task = self.store.get_task(self.st, task_id)
        if task is None:
            raise SystemExit(f"[evo] no task {task_id}")
        # Provenance record (v11): who claims to have done this work. Written
        # BEFORE validation so critic-isolation checks can compare the review's
        # session against the authored work's. Absent = recorded as unknown.
        sess = str(session or os.environ.get("EVO_SESSION") or "").strip()
        if sess:
            task["session"] = sess
        allow_revision = (str((task.get("subject") or {}).get("node") or "")
                          if task.get("type") == "implement" and task.get("status") == "open" else None)
        subject = task.get("subject") or {}
        self._assert_artifact_seals(
            allow_implementation_revision_node=allow_revision,
            only_lane=str(subject.get("lane") or "") or None,
            only_node=str(subject.get("node") or "") or None)
        if task["status"] != "open":
            raise SystemExit(f"[evo] task {task_id} is {task['status']}, not open")
        # Defense in depth for the scoped brake (G1): even if a covered task
        # was reopened through an escalation approved before/around the hold,
        # no submission may mutate authority inside an active hold's scope.
        holding = erecover.active_holds_for_subject(
            self.st, self.g, lane=str(subject.get("lane") or "") or None,
            node=str(subject.get("node") or "") or None,
            run=str(subject.get("run") or "") or None,
            round_=str(subject.get("round") or "") or None)
        holding += [str(row.get("id") or "?") for row in self.st.get("holds", [])
                    if row.get("status") == "active"
                    and task_id in set(row.get("consumer_task_ids") or [])
                    and str(row.get("id") or "?") not in holding]
        authorized = set()
        for case in self.st.get("recoveries", []):
            if case.get("status") == "replaying" and case.get("hold"):
                authorized.add(str(case.get("hold")))
        holding = [h for h in holding if h not in authorized]
        if holding:
            raise SystemExit("[evo] submission is paused by active hold(s) "
                             + ", ".join(holding)
                             + "; resume the hold or complete its recovery first")
        if task["type"] == "stage_watch":
            return self._submit_stage_watch(task)
        # R6 blind-operator audit: under strict isolation an author task that
        # closes without a recorded session leaves its release critic in an
        # unrepairable CRITIC_SESSION_AUTHOR_UNKNOWN trap (done tasks cannot
        # be re-submitted; lane authority cannot be rewritten). Fail-early
        # while the fix is still one flag away.
        if str((self.cfg.get("policy") or {}).get("critic_isolation") or "") == "strict" \
                and task["type"] in ("sketch", "mature", "theorize", "implement") \
                and not sess:
            return self._reject(task, [
                "CRITIC_SESSION_AUTHOR_REQUIRED: critic_isolation=strict records author identity at "
                "submit time - re-run this exact submit WITH --session <your-stable-session-id>. "
                "The release critic must later prove independence against YOUR recorded identity; "
                "an author that closes unnamed can never be released under strict."])
        validator = evalid.VALIDATORS.get(task["type"])
        if validator is None:
            raise SystemExit(f"[evo] no validator for task type {task['type']} (engine bug)")
        errs = validator(self.ctx(), task)
        if errs:
            return self._reject(task, errs)
        gate_pending = self._require_human_study_confirmation(task)
        if gate_pending is not None:
            self.save()
            return gate_pending
        self._transition(task)
        # Validate the state produced by the transition as well as the state
        # consumed by it.  This turns seal/pointer/upstream binding into an
        # engine postcondition, so a regression cannot persist a malformed
        # scientific head and wait for a later command to notice.
        post_node = str(subject.get("node") or "") or None
        if task.get("type") == "plan_node" and subject.get("lane"):
            post_node = str((self._lane_of(subject) or {}).get("node") or "") or None
        # Seed the postcondition sweep with the working-path digests the
        # transition itself just computed: inside one single-threaded invocation
        # nothing can have changed those bytes, so re-reading them adds no
        # information - the sweep still checks the on-disk rows EQUAL the seed
        # (write integrity) and still makes the snapshot copy's first
        # integrity read (never seeded).
        self._assert_artifact_seals(
            only_lane=str(subject.get("lane") or "") or None,
            only_node=post_node,
            digest_seed=dict(self._seal_digest_seed))
        task["status"] = "done"
        task.pop("_render", None)
        task["updated_at"] = eutil.utc_now()
        self.store.event("agent", "task_done", task=task_id, type=task["type"])
        egraph.recompute_rollups(self.g, self.cfg)
        egraph.render_views(self.store, self.g, self.cfg, self.st)
        # ARTIFACTS.md has no engine or bundle reader; the registry block that
        # tasks consume is rendered inline by eartifact.artifacts_block.  The
        # view is refreshed on demand by `evo render` and `evo doctor` instead
        # of on every accepted submit.
        edash.render(self.store, self.g, self.cfg, self.st, self.reg, infra_memo=self._infra_memo)
        self.save()
        return {"kind": "accepted", "task": task_id, "type": task["type"]}

    def _require_human_study_confirmation(self, task: dict) -> dict | None:
        """E2: a human-study cell's settlement is user-owned in EVERY autonomy
        mode. The validated evaluation bytes are digest-bound to a protected
        gate; acceptance proceeds only after the user has seen and approved
        the sealed study import. Automated-only projects never hit this."""
        if task.get("type") != "evaluate":
            return None
        cells = [c for c in econfig.evaluation_cells(self.cfg)
                 if str(c.get("source_kind") or "") == "human_study"]
        if not cells:
            return None
        node = self.node(str((task.get("subject") or {}).get("node") or ""))
        if node is None:
            return None
        metrics_rel = str(task.get("outputs", [""])[0] or "")
        digest = evalid.json_file_digest(self.ctx(), metrics_rel)
        # R7 external audit: the decision object is the RAW response bytes,
        # not just the normalized JSON that cites them. Binding only the
        # metrics digest let an approved gate seal bytes the user never saw
        # (swap after approval) and let a rejection permanently block a
        # legitimate raw-file correction (same summary, fixed responses).
        metrics_data = eutil.read_json(eutil.rpath(self.store.repo, metrics_rel), {}) or {}
        arts_digest, art_rows = evalid.human_study_artifacts_digest(self.ctx(), metrics_data)
        for gate in reversed(self.st.get("gates", [])):
            if gate.get("kind") != "human_study_confirm":
                continue
            subject = gate.get("subject") or {}
            if subject.get("node") != node.get("id") or subject.get("metrics_digest") != digest \
                    or subject.get("artifacts_digest") != arts_digest:
                if gate.get("status") == "open" and subject.get("node") == node.get("id") \
                        and subject.get("metrics_digest") == digest:
                    # Same summary, different raw bytes: the presented gate no
                    # longer describes what would be sealed - supersede it.
                    gate["status"] = "cancelled"
                    gate["resolved_at"] = eutil.utc_now()
                    gate["note"] = "superseded: study_artifact bytes changed before any decision"
                    self.store.event("engine", "gate_cancelled", gate=gate.get("id"),
                                     reason="human_study_artifacts_changed")
                continue
            if gate.get("status") == "approved":
                return None
            if gate.get("status") == "rejected":
                return self._reject(task, [
                    "HUMAN_STUDY_REJECTED: the user rejected this exact study import "
                    f"(gate {gate.get('id')}); revise the study evidence (changing the raw "
                    "response file's bytes creates a fresh gate) before resubmitting"])
            if gate.get("status") == "open":
                return self._present_gate(gate)
        summary_cells = ", ".join(
            f"{c.get('id')} ({c.get('result_key')})" for c in cells)
        bound_files = "; ".join(
            f"{r['artifact'] or '(missing)'} (sha256 {r['digest'][:12] or 'unreadable'})"
            for r in art_rows)
        gate = self.store.new_gate(
            self.st, "human_study_confirm",
            {"node": node.get("id"), "task": task.get("id"), "metrics_digest": digest,
             "artifacts_digest": arts_digest, "artifacts": art_rows},
            f"Node {node.get('id')} settles human-study cell(s) {summary_cells}. Review the "
            "cited study_artifact files against each cell's frozen study_protocol, then "
            "approve to accept this exact evaluation or reject to demand revised evidence. "
            f"Raw response bytes bound to this decision: {bound_files}. Any byte change "
            "voids this gate and opens a fresh one.")
        return self._present_gate(gate)

    def _reject(self, task: dict, errs: list[str]) -> dict:
        # R11 liveness audit (O1): GENERATION_MOVED means the REGISTRY moved
        # under the card, not that the agent got it wrong - burning an attempt
        # per background producer re-run could walk an innocent task into
        # stuck/escalation. The refresh below re-arms the card; only mixed or
        # agent-caused errors spend attempts.
        moved_only = bool(errs) and all(
            str(e).startswith(("SPEC_ARTIFACT_GENERATION_MOVED", "INFRA_REVISION_UNPROVEN"))
            for e in errs)
        task["attempts"] = task.get("attempts", 0) + (0 if moved_only else 1)
        task["last_errors"] = errs
        task["updated_at"] = eutil.utc_now()
        if any(str(e).startswith("SPEC_ARTIFACT_GENERATION_MOVED") for e in errs):
            # R11-010: the rejection just proved this card's registry view is
            # stale, and _render replays VERBATIM on rematerialize - so
            # refresh the Shared-artifacts lines and the machine receipt in
            # place. The retry card must show the registry the resubmission
            # will be judged against, not the one the first draft saw.
            r = task.get("_render") or {}
            r["extra_blocks"] = [
                (title, eartifact.artifacts_block(self.reg)
                 if "shared artifacts" in str(title).lower() else list(lines))
                for title, lines in (r.get("extra_blocks") or [])]
            r["artifact_receipts"] = eartifact.artifacts_receipts(self.reg)
            task["_render"] = r
            self._rematerialize(task)
        self.store.event("agent", "task_rejected", task=task["id"], type=task["type"],
                         attempt=task["attempts"], errors=errs)
        maxa = int(self.cfg.get("budgets", {}).get("max_attempts", 3))
        escalated = None
        # v11.7: a BLOCKED rehearsal is not the agent's failure and not a code
        # defect - it needs the USER (access/quota/data). Escalate immediately
        # instead of burning attempts on an unwinnable retry loop.
        if task.get("type") == "rehearsal" and any(
                str(err).startswith("REHEARSAL_BLOCKED") for err in errs):
            task["status"] = "stuck"
            task["last_errors"] = errs
            gate = self.store.new_gate(
                self.st, "escalation", {"task": task["id"]},
                "The tiny full-chain rehearsal is BLOCKED on access/resources only the user can "
                "supply: " + "; ".join(str(e) for e in errs[:3])
                + ". Approve after supplying them (the task reopens and reruns); reject to "
                  "route the node's disposal per policy.")
            self.store.event("engine", "rehearsal_blocked_escalated", task=task["id"],
                             gate=gate.get("id"))
            if task.get("card"):
                eutil.write_json_atomic(
                    eutil.rpath(self.store.repo, f".evo/tasks/{task['id']}/ERRORS.json"),
                    {"task": task["id"], "attempt": task["attempts"], "errors": errs})
            self.save()
            return {"kind": "rejected", "task": task["id"], "attempt": task["attempts"],
                    "max_attempts": maxa, "errors": errs, "escalation": gate["id"],
                    "errors_file": (f".evo/tasks/{task['id']}/ERRORS.json"
                                    if task.get("card") else None),
                    "status": task["status"]}
        typed_implementation_repair = (
            task.get("type") == "smoke" and any(str(err).startswith("SMOKE_FAILED") for err in errs)
        ) or (
            task.get("type") == "fidelity" and any(str(err).startswith("FIDELITY_DEVIATES") for err in errs)
        ) or (
            task.get("type") == "ablation_fidelity" and
            any(str(err).startswith("ABLATION_FIDELITY_DEVIATES") for err in errs)
        ) or (
            # v11.7: a failed full-chain rehearsal is a WIRING defect in the
            # sealed implementation (a stage that cannot launch, an artifact
            # its consumer cannot read) - route to the fix pass, and the
            # re-sealed code owes a fresh rehearsal.
            task.get("type") == "rehearsal" and any(
                str(err).startswith("REHEARSAL_FAILED") for err in errs)
        ) or (
            # R9 (external audit r6): a bridge anchor mismatch PROVES the sealed
            # adapter does not reproduce the baseline numbers - an implementation
            # defect. Its own card forbids editing code, so without a typed route
            # the only outcomes were infinite retries of an unwinnable audit, or
            # (under on_stuck=abandon) destroying the node over an adapter bug.
            # Schema/missing-file bridge errors stay on the analyst-retry path.
            task.get("type") == "metric_bridge" and
            any(str(err).startswith("BRIDGE_ANCHOR_MISMATCH") for err in errs)
        )
        if typed_implementation_repair:
            node = self.node(str((task.get("subject") or {}).get("node") or ""))
            if node is not None:
                # F1: the typed repair loop is bounded by the same max_attempts
                # machinery as every other failure path. v9.2 re-armed fix
                # passes forever with no counter: implement->smoke->fail could
                # loop unbounded, never escalate and ignore on_stuck=abandon.
                node["fix_cycles"] = int(node.get("fix_cycles") or 0) + 1
                if node["fix_cycles"] >= maxa:
                    task["status"] = "cancelled"
                    task.pop("_render", None)
                    if self.cfg.get("policy", {}).get("on_stuck") == "abandon" \
                            and not self._node_training_paid(node):
                        # v11 R2: once the node's training is paid for (e.g. an
                        # evaluation-only repair after workflow reuse), repair
                        # exhaustion escalates like every other expensive
                        # terminal state instead of silently destroying paid
                        # compute over evaluator plumbing.
                        self._abandon_node(node, "implementation repair budget exhausted "
                                                 f"({node['fix_cycles']} typed fix cycles)")
                        self.save()
                        return {"kind": "rejected", "task": task["id"], "attempt": task["attempts"],
                                "max_attempts": maxa, "errors": errs, "escalation": None,
                                "status": task["status"]}
                    gate = self.store.new_gate(
                        self.st, "escalation",
                        # R7: carry the repair intent ON the gate. Approval
                        # used to reset counters only - the node then sat in
                        # its old status, the scheduler recreated the SAME
                        # deterministic check, and (max_attempts<=1) the very
                        # first failure re-opened this gate: approve promised
                        # a repair it never delivered.
                        {"node": node.get("id"),
                         "repair_intent": {"fix_note": "; ".join(str(err) for err in errs[:5]),
                                           "task_type": task["type"]}},
                        f"Node {node.get('id')} failed {node['fix_cycles']} typed implementation "
                        f"repair cycles ({task['type']}). Approve to reset the repair budget and "
                        "send the node back to implementation with these errors as the fix brief; "
                        "reject to abandon the node.")
                    self.store.event("engine", "implementation_repair_exhausted",
                                     node=node.get("id"), cycles=node["fix_cycles"])
                    self.save()
                    return {"kind": "rejected", "task": task["id"], "attempt": task["attempts"],
                            "max_attempts": maxa, "errors": errs, "escalation": gate["id"],
                            "status": task["status"]}
                task["status"] = "cancelled"
                task.pop("_render", None)
                node["status"] = "building"
                node["fix_needed"] = True
                node["fix_note"] = "; ".join(str(err) for err in errs[:5])
                if task.get("type") == "smoke" and node.get("workflow_reuse_seal"):
                    # A smoke failure while an evaluation-only revision is
                    # active does not itself prove the preserved workflow was
                    # wrong.  Keep the narrow boundary for the correction;
                    # protected-file validation can still widen it to the
                    # whole workflow, but a typo in evaluator code must not
                    # silently force retraining.
                    receipt = eutil.read_json(eutil.rpath(
                        self.store.repo, str(node.get("workflow_reuse_receipt_path") or "")), {}) or {}
                    node["implementation_repair_scope"] = "evaluation"
                    node["implementation_repair_source_run"] = receipt.get("source_run")
                egraph.touch(node)
                self.store.event("engine", "implementation_fix_required", node=node.get("id"),
                                 source_task=task.get("type"),
                                 implementation_revision=node.get("implementation_revision"),
                                 repair_scope=node.get("implementation_repair_scope"),
                                 errors=errs[:5])
                self.save()
                return {"kind": "rejected", "task": task["id"], "attempt": task["attempts"],
                        "max_attempts": maxa, "errors": errs, "escalation": None,
                        "status": task["status"], "repair": True}
        if task["attempts"] >= maxa:
            task["status"] = "stuck"
            self.store.event("engine", "task_stuck", task=task["id"])
            # Bootstrap steps are structurally unabandonable (minus the
            # optional sota_scan) plus the round-strategy tasks; derived from
            # the canonical sequence so the two can never drift (D3).
            # v11: the EXPENSIVE terminal tasks joined the list - a stuck
            # conclude used to abandon the WHOLE TRAINED NODE over report
            # formatting, the single most disproportionate death in the
            # survival audit: all compute spent, evidence sealed, and the
            # engine already knows most of the answers it is rejecting.
            protected = tuple(step for step in eflow.BOOTSTRAP_SEQ if step != "sota_scan") + (
                "baseline_spec", "open_round", "close_round", "evidence") + eflow.EXPENSIVE_TERMINAL_TASKS
            # v11 R2: ANY stuck task whose subject node already paid its
            # training (eval_launch, metric_bridge, ...) is expensive-terminal
            # in effect - the type list alone left bypasses.
            stuck_node = self.node(str((task.get("subject") or {}).get("node") or ""))
            trained_subject = bool(stuck_node) and self._node_training_paid(stuck_node)
            if self.cfg.get("policy", {}).get("on_stuck") == "abandon" \
                    and task["type"] not in protected and not trained_subject:
                task["status"] = "cancelled"
                task.pop("_render", None)
                self._abandon_task_subject(task, "attempts exhausted (on_stuck=abandon)")
            else:
                # The full_auto auto-reject exemption reads gate.subject.node
                # (egate escalation_on_stuck): a stuck task whose node already
                # paid training MUST carry the node key, or the protection's
                # two halves read different keys and the trained node is
                # auto-rejected into abandonment unattended (R3 logic audit).
                gate_subject = {"task": task["id"]}
                if stuck_node:
                    gate_subject["node"] = stuck_node["id"]
                gate = self.store.new_gate(self.st, "escalation", gate_subject,
                                           f"Task {task['id']} ({task['type']}) failed validation {task['attempts']} times. "
                                           f"Last errors: {'; '.join(errs[:5])}")
                escalated = gate["id"]
        else:
            self._rematerialize(task)
        # Full error list on disk, always: stdout and the bundle cap their
        # copies (anti-starvation needs availability, not four full channels).
        if task.get("card"):
            eutil.write_json_atomic(
                eutil.rpath(self.store.repo, f".evo/tasks/{task['id']}/ERRORS.json"),
                {"task": task["id"], "attempt": task["attempts"], "errors": errs})
        self.save()
        return {"kind": "rejected", "task": task["id"], "attempt": task["attempts"],
                "max_attempts": maxa, "errors": errs, "escalation": escalated,
                "errors_file": f".evo/tasks/{task['id']}/ERRORS.json" if task.get("card") else None,
                "status": task["status"]}

    def _submit_stage_watch(self, task: dict) -> dict:
        run = self.store.get_run(self.st, task["subject"].get("run"))
        if run is None:
            raise SystemExit("[evo] stage_watch without run; run 'evo doctor'")
        if not erun.is_terminal(run):
            return {"kind": "waiting", "task": task["id"],
                    "reason": f"run {run['id']} is {run.get('status')} (job={run.get('job')}). Check the job, then "
                              f"'evo run-update --run {run['id']} --status succeeded|failed "
                              "[--metrics-file <path>] [--failure-class ...] [--note ...]' and submit again."}
        if self._run_adoption_blocked(run):
            # The blocked predicate just PERSISTED the deferral obligation on
            # the RUN (adoption_deferred_by_hold) - save it, or a hold whose
            # only engine touch was this watch submit would lose the marker
            # and the release would adopt the reviewed RUN past the promised
            # reconcile window.
            self.save()
            return {"kind": "waiting", "task": task["id"],
                    "reason": f"run {run['id']} terminal fact is recorded; active hold defers evidence adoption"}
        self._absorb_run(run)
        if task["status"] == "open":  # _close_watch_tasks may already have closed it
            task["status"] = "done"
            task.pop("_render", None)
            task["updated_at"] = eutil.utc_now()
        self.save()
        return {"kind": "accepted", "task": task["id"], "type": "stage_watch", "run_status": run["status"]}
