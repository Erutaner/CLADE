"""RUN lifecycle (v10): preparation, binding, updates, reconciliation,
evidence ingest/sealing, resource receipts, stage advancement, scientific
stops and failure routing. External facts are monotone; evidence and adoption
are separate axes (see erun).
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import statistics
from typing import Any

import eartifact
import econfig
import egraph
import erecover
import erun
import eseal
import eutil
import evalid

stages_of = econfig.stages_of

# The one authority-upstream field list (v9.2 kept three copies and the
# fallback copy had drifted: it omitted workflow_reuse_seal).
AUTHORITY_UPSTREAM_FIELDS = (
    "spec_seal", "implementation_seal", "workflow_reuse_seal", "fidelity_seal",
    "ablation_fidelity_seal", "metric_bridge_seal")

# Sentinel distinguishing "gate not yet computed" from "computed as None".
_GATE_UNCHECKED = object()



class AbsorbMixin:
    def _run_contract_digest(self, node: dict, *, kind: str,
                             launch: str = "") -> str:
        """Bind an attempt to the executable authority, not just a node id."""
        return eseal.combine_digests(
            str((node.get("spec_seal") or {}).get("digest") or ""),
            str((node.get("implementation_seal") or {}).get("digest") or ""),
            str((node.get("workflow_reuse_seal") or {}).get("digest") or ""),
            str((node.get("fidelity_seal") or {}).get("digest") or ""),
            str((node.get("ablation_fidelity_seal") or {}).get("digest") or ""),
            str((node.get("metric_bridge_seal") or {}).get("digest") or ""),
            kind, launch)

    @staticmethod
    def _repeat_run_pending(node: dict) -> Any | None:
        """The approved repeat_measure's fresh seed while its engine-run
        workflow+eval is still owed (R9-002: the buy-back is a REAL pair of
        RUNs now, scheduled/leased/charged like any other attempt). Returns
        None once the repeat evaluation settled, or when the approval was
        waived/archived/settled."""
        rm = node.get("repeat_measure")
        if not isinstance(rm, dict) or rm.get("waived") or node.get("repeat_measure_done"):
            return None
        return node.get("repeat_pending_seed")

    def _run_is_current_attempt(self, run: dict, node: dict) -> bool:
        """R10 audit (owner-transition unity): is this RUN the attempt whose
        outcome the owner is still waiting on? The old test - "the node has
        already transitioned to executing/evaluating" - missed every attempt
        that ended BEFORE a job id existed (the launch transition is what
        flips the node), so a real external failure was archived as unrelated
        history: no failure ledger entry, no retry counter, no
        replacement-spend door, and the scheduler immediately re-prepared the
        same position for free. Ownership is judged from the RUN's slot
        identity and the node's position, never from launch timing."""
        if node is None or run.get("superseded") or run.get("orphaned") \
                or run.get("confirmed_not_launched"):
            return False
        slot = str(run.get("logical_slot_key") or "")
        my_no = int(run.get("attempt_no") or 0)
        for other in self.st.get("runs", []):
            if other is run:
                continue
            if str(other.get("logical_slot_key") or "") == slot \
                    and int(other.get("attempt_no") or 0) > my_no:
                return False  # a newer attempt owns this position now
        repeat_pending = self._repeat_run_pending(node)
        if bool(run.get("repeat_measure_attempt")) != (repeat_pending is not None):
            # base attempts are history while the repeat lane is owed, and a
            # repeat attempt is history once its lane settled or was archived
            return False
        if run.get("kind") == "stage":
            if node.get("status") not in ("stage_ready", "executing", "evidence_pending"):
                return False
            sidx = run.get("stage_index")
            if not (isinstance(sidx, int) and not isinstance(sidx, bool)
                    and sidx == int(node.get("stage_cursor") or 0)):
                return False
            if run.get("repeat_measure_attempt"):
                expected_seed = repeat_pending
            else:
                expected_seed = econfig.workflow_seed(
                    self._spec(node), int(node.get("replica_index") or 0))
            return type(run.get("replica_seed")) is type(expected_seed) \
                and run.get("replica_seed") == expected_seed
        if run.get("kind") == "eval":
            if node.get("status") not in ("workflow_done", "evaluating", "evidence_pending"):
                return False
            if run.get("repeat_measure_attempt"):
                return True  # lane match already established above
            return not node.get("eval_done")
        return False

    def _ensure_run_claims(self, run: dict) -> None:
        """Sweep G-3: RUN rows written before the unified claim set (pre-R9
        states) carry only the two declared landing fields, so every overlap
        guard judged them by that fragment - probe artifacts and
        seed-resolved products of a migrated, still-unsettled RUN were
        invisible to the lease and the later-claimant rule. Backfill the full
        canonical set once from the frozen spec; it persists with the next
        state commit."""
        if "landing_claims" in run:
            return
        node = self.node(str(run.get("node") or ""))
        claims: list[str] = []
        if node is not None:
            try:
                claims = self._landing_claims(
                    node, str(run.get("kind") or ""), stage=run.get("stage"),
                    replica_seed=run.get("replica_seed"),
                    declared_metrics_file=str(run.get("declared_metrics_file") or ""),
                    declared_ledger_file=str(run.get("declared_ledger_file") or ""),
                    repeat=bool(run.get("repeat_measure_attempt")))
            except (ValueError, OSError, KeyError):
                claims = []
        if not claims:
            claims = [c for c in (
                eutil.norm_uri(str(run.get("declared_metrics_file") or "")),
                eutil.norm_uri(str(run.get("declared_ledger_file") or ""))) if c]
        run["landing_claims"] = claims
        self.store.event("engine", "run_claims_backfilled", run=run.get("id"))

    @staticmethod
    def _run_claim_set(run: dict) -> set[str]:
        """Every canonical landing path a RUN row claims. New rows carry the
        full precomputed set (landing_claims); legacy rows fall back to the
        two declared fields they were written with."""
        claims = {eutil.norm_uri(str(c)) for c in (run.get("landing_claims") or [])}
        claims |= {eutil.norm_uri(str(run.get("declared_metrics_file") or "")),
                   eutil.norm_uri(str(run.get("declared_ledger_file") or ""))}
        claims.discard("")
        return claims

    def _landing_claims(self, node: dict, kind: str, *, stage: str | None,
                        replica_seed: Any | None,
                        declared_metrics_file: str = "",
                        declared_ledger_file: str = "",
                        repeat: bool = False) -> list[str]:
        """R9 audit (root cause): ownership was retailed per field - metrics
        and ledger got a lease while the producer probe artifact and the
        seed-resolved declared products stayed unowned, so two spec-obeying
        parallel RUNs could archive each other's files and seal the wrong
        producer's bytes. ONE resolved, canonical claim set per attempt now
        covers every path it writes; the lease, the scheduler probes and the
        later-claimant rule all judge this set.

        repeat=True marks the bought-back repeat attempt (R9-002/R10-012): it
        claims the SAME spec-resolved landings as any attempt (one resolution
        rule everywhere; the prepare-time archive and the lease protect the
        sealed first attempt), and it claims no probe artifacts - mechanism
        authority stays with the base head, the repeat buys only the decision
        metric's second measurement."""
        claims: set[str] = set()
        for rel in (declared_metrics_file, declared_ledger_file):
            if rel and "://" not in rel:
                claims.add(eutil.norm_uri(rel))
        spec = self._spec(node) if node else {}
        probe = spec.get("probe_execution") or {}
        is_producer = (not repeat) and \
                      ((kind == "stage" and probe.get("mode") == "same_run"
                        and probe.get("producer_stage") == stage) or
                       (kind == "eval" and
                        ((probe.get("mode") == "same_run" and
                          probe.get("producer_stage") == "evaluation") or
                         probe.get("mode") == "eval_intervention")))
        if is_producer:
            for row in evalid.expected_probe_observations(spec):
                if kind == "stage" and not (
                        type(row.get("seed")) is type(replica_seed)
                        and row.get("seed") == replica_seed):
                    continue
                art = str(row.get("artifact") or "")
                if art and "://" not in art:
                    claims.add(eutil.norm_uri(art))
        if kind == "stage":
            stage_row = next((s for s in stages_of(spec)
                              if str(s.get("name") or "stage") == str(stage or "")), None)
            for p_row in ((stage_row or {}).get("produces") or []):
                uri = str(p_row.get("uri") or "") if isinstance(p_row, dict) else ""
                if not uri:
                    continue
                # R10-002: remote scheme URIs are claimed too - registry law
                # says a producer URI is globally unique, so two live
                # attempts declaring the same remote landing must serialize
                # exactly like two local writers (the later one used to lose
                # its product row to a conflict event silently)
                resolved = str(econfig.resolve_seed_template(uri, replica_seed)) \
                    if replica_seed is not None else uri
                if "{" not in resolved:
                    claims.add(eutil.norm_uri(resolved))
        claims.discard("")
        return sorted(claims)

    def _landing_lease_holder(self, *declared: str, exclude_run: str = "") -> dict | None:
        """The RUN (if any) whose claim on one of these landing paths is still
        live. A landing is an exclusive lease while its RUN lives - schedulers
        probe this BEFORE preparing a competing attempt and defer (watch/wait)
        instead of crashing mid-scheduling. Comparison is by canonical path
        (R7 audit: `a/./b` vs `a/b` reached the same file while missing the
        lease). R8 audit: the lease must cover the MATERIAL lifecycle, not
        just the execution one - a finished RUN still awaiting late evidence
        (needs_reconciliation) repairs files at this very landing, so
        releasing at execution-terminal let a sibling take the path over and
        the late repair then ingested the sibling's bytes. R9 audit: the
        holder's side of the comparison is its full claim set (metrics,
        ledger, probe artifact, seed-resolved products), not just the two
        declared fields."""
        wanted = {eutil.norm_uri(d) for d in declared if d}
        wanted.discard("")
        if not wanted:
            return None
        # R10-002: overlap-aware - a directory claim and a file inside it are
        # ONE landing (equality alone let two live attempts write/move the
        # same physical object while every guard said they were disjoint)
        for r in self.st.get("runs", []):
            if str(r.get("id") or "") == exclude_run:
                continue
            if erun.is_terminal(r) and not erun.needs_reconciliation(r):
                continue
            self._ensure_run_claims(r)  # G-3: legacy rows get their full set
            if any(eutil.paths_overlap(w, c)
                   for w in wanted for c in self._run_claim_set(r)):
                return r
        return None

    def _prepare_run(self, node: dict, kind: str, request: dict[str, float], *,
                     stage: str | None = None, stage_index: int | None = None,
                     replica_seed: Any | None = None, replica_index: int | None = None,
                     replica_total: int | None = None, resolved_launch: str = "",
                     declared_metrics_file: str = "", declared_ledger_file: str = "",
                     repeat: bool = False) -> dict:
        """Persist an idempotent intent before an agent can cause external work."""
        # R9 (external audit r6): a landing path is an exclusive LEASE while
        # any other RUN that declared it is still non-terminal. Without this,
        # RUN-B's prepare archived RUN-A's half-written landing as "leftovers",
        # then A's ingest sealed B's bytes under A's identity - two spec-obeying
        # RUNs silently swapping scientific results. Checked BEFORE the RUN id
        # is allocated (nothing to roll back); schedulers probe the same
        # helper first and defer, so reaching this raise means a non-scheduler
        # caller raced the lease.
        claims = self._landing_claims(node, kind, stage=stage, replica_seed=replica_seed,
                                      declared_metrics_file=declared_metrics_file,
                                      declared_ledger_file=declared_ledger_file,
                                      repeat=repeat)
        holder = self._landing_lease_holder(*claims)
        if holder is not None:
            raise SystemExit(
                f"[evo] landing path is still leased by non-terminal RUN "
                f"{holder.get('id')} ({holder.get('status')}); two live attempts may not share a "
                "result landing. Settle that RUN first (run-update / run-reconcile, or watch it "
                "to completion). If the frozen spec forces the shared path, the spec itself needs "
                "a fork: 'evo recover-plan' on the node's spec boundary (accepted spec authority "
                "is never rewritten in place)")
        run = self.store.new_run(
            self.st, node["id"], kind, stage=stage, replica_seed=replica_seed,
            replica_index=replica_index, replica_total=replica_total,
            stage_index=stage_index, prepared=True,
            contract_digest=self._run_contract_digest(
                node, kind=kind, launch=resolved_launch),
            implementation_digest=str((node.get("implementation_seal") or {}).get("digest") or ""))
        if repeat:
            # R9-002: stamped BEFORE the landing archives below, so every
            # helper that branches on the repeat lane sees it from birth
            run["repeat_measure_attempt"] = True
        # R11-013: an interrupted predecessor prepare may have moved landing
        # bytes under this very id (allocated ids only collide with
        # UNCOMMITTED predecessors) - restore that world before archiving
        self._reconcile_orphan_archives(str(run.get("id") or ""))
        run["resource_reservation"] = dict(request)
        run["authority_upstreams"] = [
            digest for digest in (
                str((node.get("spec_seal") or {}).get("digest") or ""),
                str((node.get("implementation_seal") or {}).get("digest") or ""),
                str((node.get("workflow_reuse_seal") or {}).get("digest") or ""),
                str((node.get("fidelity_seal") or {}).get("digest") or ""),
                str((node.get("ablation_fidelity_seal") or {}).get("digest") or ""),
                str((node.get("metric_bridge_seal") or {}).get("digest") or ""),
            ) if digest]
        run["resolved_launch"] = resolved_launch
        run["declared_metrics_file"] = declared_metrics_file or None
        run["declared_ledger_file"] = declared_ledger_file or None
        run["landing_claims"] = claims
        self._archive_preexisting_probe_landings(run, node)
        self._archive_preexisting_result_landings(run, node)
        # Releasing the launch card means a submission may happen before the
        # next local write.  Record that uncertainty up front; run-bind or a
        # completed launch resolves it monotonically.
        erun.transition_execution(run, "launch_unknown",
                                  note="launch card released; reconcile before any replacement attempt")
        self.store.event("engine", "run_launch_authorized", run=run["id"],
                         node=node["id"], kind=kind, stage=stage,
                         attempt_key=run.get("attempt_key"), usage=request)
        return run

    def _probe_expectations(self, run: dict, node: dict) -> tuple[bool, list[dict]]:
        # R9-002: the bought-back repeat attempt is never a probe producer.
        # The mechanism probe was measured and sealed by the base attempt
        # (whose evidence head stays authoritative); re-demanding it here
        # would re-archive the base landing and re-open a settled duty over a
        # purchase that buys only the decision metric's second measurement.
        if run.get("repeat_measure_attempt"):
            return False, []
        spec = self._spec(node)
        probe = spec.get("probe_execution") or {}
        stage_producer = run.get("kind") == "stage" and probe.get("mode") == "same_run" and \
            probe.get("producer_stage") == run.get("stage")
        eval_producer = run.get("kind") == "eval" and (
            (probe.get("mode") == "same_run" and probe.get("producer_stage") == "evaluation") or
            probe.get("mode") == "eval_intervention")
        expected = evalid.expected_probe_observations(spec) if stage_producer or eval_producer else []
        if stage_producer:
            expected = [row for row in expected
                        if type(row.get("seed")) is type(run.get("replica_seed"))
                        and row.get("seed") == run.get("replica_seed")]
        return stage_producer or eval_producer, expected

    _ARCHIVE_DIRS = ("preexisting_probe_landings", "preexisting_landings")

    def _reconcile_orphan_archives(self, run_id: str) -> None:
        """R11-013 (+ sweep G-2): a landing archive whose manifest sits under
        a run id that is only NOW being allocated belongs to an interrupted
        predecessor prepare - committed ids are never reused (the counter
        advances with the same state commit that persists the RUN row), so
        the collision itself proves the moves happened while the state that
        described them never landed. Restore every archived byte to its
        declared landing (only where the landing is empty: no RUN was
        committed and no card was issued, so nothing else can have written
        there) and clear the manifest; the fresh prepare then re-archives
        from a consistent world."""
        for dirname in self._ARCHIVE_DIRS:
            archive_dir = eutil.rpath(self.store.repo, f".evo/runs/{run_id}/{dirname}")
            manifest_path = archive_dir / "MANIFEST.json"
            if not manifest_path.is_file():
                continue
            manifest = eutil.read_json(manifest_path, {}) or {}
            restored = 0
            for row in manifest.get("rows") or []:
                declared = str(row.get("declared") or "")
                archived = str(row.get("archived") or "")
                if not declared or not archived:
                    continue
                source = eutil.rpath(self.store.repo, archived)
                target = eutil.rpath(self.store.repo, declared)
                if source.exists() and not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_dir():
                        shutil.move(str(source), str(target))
                    else:
                        source.replace(target)
                    restored += 1
            self.store.event("engine", "orphan_landing_archive_restored",
                             run=run_id, archive=dirname, restored=restored,
                             rows=len(manifest.get("rows") or []))
            try:
                manifest_path.unlink()
            except OSError:
                pass

    def _write_archive_manifest(self, archive_dir, run_id: str, rows: list[dict]) -> None:
        """R11-013: the manifest is the committed intent for the destructive
        moves that follow - durably written BEFORE the first byte moves, so
        an interruption anywhere in the move batch leaves a disk-recoverable
        record even though the state may know nothing about this RUN yet."""
        archive_dir.mkdir(parents=True, exist_ok=True)
        eutil.write_json_atomic(archive_dir / "MANIFEST.json", {
            "schema_version": 1, "run": run_id, "created_at": eutil.utc_now(),
            "rows": rows})

    def _archive_preexisting_probe_landings(self, run: dict, node: dict) -> None:
        """Prevent a new attempt from inheriting a prior attempt's landing bytes."""
        is_producer, expected = self._probe_expectations(run, node)
        if not is_producer:
            return
        archive_dir = eutil.rpath(
            self.store.repo, f".evo/runs/{run.get('id')}/preexisting_probe_landings")
        plan: list[tuple[dict, Any, Any]] = []
        for index, row in enumerate(expected):
            declared = str(row.get("artifact") or "")
            source = eutil.rpath(self.store.repo, declared)
            if not declared or not source.is_file():
                continue
            target = archive_dir / f"probe_{index}_{source.name}"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            plan.append(({
                "declared_artifact": declared,
                "archived_artifact": eutil.rel(self.store.repo, target),
                "seed": row.get("seed"), "digest": digest,
                "archived_at": eutil.utc_now(),
            }, source, target))
        if not plan:
            return
        # manifest first, moves second (R11-013)
        self._write_archive_manifest(
            archive_dir, str(run.get("id") or ""),
            [{"declared": rec["declared_artifact"], "archived": rec["archived_artifact"]}
             for rec, _s, _t in plan])
        for _rec, source, target in plan:
            source.replace(target)
        run["preexisting_probe_landings"] = [rec for rec, _s, _t in plan]
        self.store.event("engine", "preexisting_probe_landings_archived",
                         run=run.get("id"), node=node.get("id"),
                         artifacts=run["preexisting_probe_landings"])

    def _archive_preexisting_result_landings(self, run: dict, node: dict) -> None:
        """R7 external audit: the probe-landing archive existed because a new
        attempt must never inherit a prior attempt's bytes - but ordinary
        stage/eval metrics and ledger landings had no such guard, so a job
        that silently wrote nothing (or elsewhere) let the previous attempt's
        pre-fix numbers be absorbed and billed as fresh evidence. Archive
        every declared result landing that already exists at prepare time;
        a job that actually runs recreates its output."""
        archive_dir = eutil.rpath(
            self.store.repo, f".evo/runs/{run.get('id')}/preexisting_landings")
        plan: list[tuple[dict, Any, Any]] = []
        for field in ("declared_metrics_file", "declared_ledger_file"):
            declared = str(run.get(field) or "")
            if not declared:
                continue
            source = eutil.rpath(self.store.repo, declared)
            if not source.is_file():
                continue
            target = archive_dir / f"{field}_{source.name}"
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            plan.append(({
                "declared": declared, "field": field,
                "archived_artifact": eutil.rel(self.store.repo, target),
                "digest": digest, "archived_at": eutil.utc_now(),
            }, source, target))
        # R8 audit: declared PRODUCTS need the same guard. Bytes left at a
        # produces[] URI by an earlier attempt (or an earlier implementation
        # revision) used to be re-attributed to the new RUN at settlement -
        # record_generation hashed whatever sat there. Move them aside at
        # prepare; whatever exists at settlement was written by THIS attempt
        # (STAGE_PRODUCT_MISSING enforces the other half).
        if run.get("kind") == "stage" and node is not None:
            stage_row = next(
                (s for s in stages_of(self._spec(node))
                 if str(s.get("name") or "stage") == str(run.get("stage") or "")), None)
            for index, p_row in enumerate((stage_row or {}).get("produces") or []):
                uri = str(p_row.get("uri") or "") if isinstance(p_row, dict) else ""
                if not uri or "://" in uri:
                    continue
                resolved = str(econfig.resolve_seed_template(uri, run.get("replica_seed"))) \
                    if run.get("replica_seed") is not None else uri
                if "{" in resolved:
                    continue
                source = eutil.rpath(self.store.repo, resolved)
                if not source.exists():
                    continue
                target = archive_dir / f"produce_{index:02d}_{source.name}"
                digest = "" if source.is_dir() else \
                    hashlib.sha256(source.read_bytes()).hexdigest()
                plan.append(({
                    "declared": resolved, "field": "produces",
                    "archived_artifact": eutil.rel(self.store.repo, target),
                    "digest": digest, "archived_at": eutil.utc_now(),
                }, source, target))
        if not plan:
            return
        # manifest first, moves second (R11-013)
        self._write_archive_manifest(
            archive_dir, str(run.get("id") or ""),
            [{"declared": rec["declared"], "archived": rec["archived_artifact"]}
             for rec, _s, _t in plan])
        for _rec, source, target in plan:
            if source.is_dir():
                shutil.move(str(source), str(target))
            else:
                source.replace(target)
        run["preexisting_result_landings"] = [rec for rec, _s, _t in plan]
        self.store.event("engine", "preexisting_result_landings_archived",
                         run=run.get("id"), node=node.get("id"),
                         artifacts=run["preexisting_result_landings"])

    def _ingest_probe_artifacts(self, run: dict, node: dict) -> None:
        """Copy producer observations before validating; revise only while unsealed."""
        is_producer, expected = self._probe_expectations(run, node)
        if not is_producer:
            return
        evidence_dir = eutil.rpath(self.store.repo, f".evo/runs/{run.get('id')}/evidence")
        evidence_dir.mkdir(parents=True, exist_ok=True)
        existing = {
            str(row.get("declared_artifact") or ""): row
            for row in (run.get("probe_artifact_snapshots") or [])
            if isinstance(row, dict) and row.get("declared_artifact")
        }
        for index, row in enumerate(expected):
            declared = str(row.get("artifact") or "")
            if not declared:
                continue
            source = eutil.rpath(self.store.repo, declared)
            if not source.is_file():
                continue
            prior = existing.get(declared)
            revision = int((prior or {}).get("snapshot_revision") or 1)
            if prior is not None:
                prior_path = eutil.rpath(self.store.repo, str(prior.get("snapshot_artifact") or ""))
                source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
                prior_digest = hashlib.sha256(prior_path.read_bytes()).hexdigest() \
                    if prior_path.is_file() else ""
                required_fields = [str(x) for x in
                                   ((self._spec(node).get("probe_execution") or {}).get("required_fields") or [])]
                prior_valid = not evalid.probe_artifact_errors(
                    self.ctx(), str(prior.get("snapshot_artifact") or ""), required_fields,
                    where=f"run {run.get('id')} prior immutable probe")
                revisable = run.get("evidence_status") in {"incomplete", "invalid"} \
                    and not isinstance(run.get("evidence_seal"), dict) and not prior_valid
                if not revisable or (prior_path.is_file() and source_digest == prior_digest):
                    continue
                archived = dict(prior)
                archived["superseded_at"] = eutil.utc_now()
                archived["superseded_reason"] = "same-RUN evidence reconciliation supplied different bytes"
                run.setdefault("probe_snapshot_history", []).append(archived)
                revision += 1
            suffix = "" if revision == 1 else f"_r{revision}"
            target = evidence_dir / f"probe_{index}{suffix}_{source.name}"
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            snapshot = eutil.rel(self.store.repo, target)
            existing[declared] = {
                "declared_artifact": declared,
                "snapshot_artifact": snapshot,
                "observation_index": index,
                "snapshot_revision": revision,
                "seed": row.get("seed"),
                "digest": hashlib.sha256(target.read_bytes()).hexdigest(),
                "ingested_at": eutil.utc_now(),
            }
        ordered = [existing[str(row.get("artifact") or "")] for row in expected
                   if str(row.get("artifact") or "") in existing]
        if ordered:
            run["probe_artifact_snapshots"] = ordered

    def _ingest_run_landings(self, run: dict) -> None:
        """R7 external audit: snapshot the producer landing BEFORE validation.
        Validation, the stage gate decision and the seal each re-opened the
        mutable landing path, so the bytes that were validated and the bytes
        that were sealed could differ (a still-flushing job, a late remote
        sync, a duplicate writer). Ingest at absorption entry; every later
        reader - validators, gate decision, seal - uses the immutable per-run
        snapshot. While the evidence is UNSEALED and incomplete/invalid, a
        reconciliation that supplies different producer bytes re-ingests as a
        fresh snapshot revision (same rule as probe snapshots); a sealed
        snapshot is never replaced."""
        prefix = f".evo/runs/{run.get('id')}/evidence/"
        evidence_dir = eutil.rpath(self.store.repo, prefix)
        revisable = run.get("evidence_status") in {"incomplete", "invalid"} \
            and not isinstance(run.get("evidence_seal"), dict)
        # R7 external audit: field-LEVEL revision. The old whole-RUN rule let a
        # ledger-only reconcile silently re-read the producer metrics landing -
        # which a sibling RUN may legally occupy by then (the lease ends at
        # execution-terminal, the revision window ends at the seal) - and seal
        # the sibling's bytes under this RUN's identity. A snapshotted field is
        # re-read ONLY when the operator explicitly resupplied it.
        refresh = {str(x) for x in (run.get("evidence_refresh_fields") or [])}
        for field in ("metrics_file", "ledger_file"):
            rel = str(run.get(field) or "")
            snapshotted = bool(rel) and rel.replace("\\", "/").startswith(prefix)
            if snapshotted and not (revisable and field in refresh):
                continue
            source_rel = str(run.get(f"producer_{field}") or "") if snapshotted else rel
            if not source_rel:
                continue
            source = eutil.rpath(self.store.repo, source_rel)
            if not source.exists() or not source.is_file():
                continue
            if snapshotted:
                current = eutil.rpath(self.store.repo, rel)
                if current.is_file() and current.read_bytes() == source.read_bytes():
                    continue
                revision = int(run.get(f"{field}_snapshot_revision") or 1) + 1
                run[f"{field}_snapshot_revision"] = revision
                target = evidence_dir / f"{field}_r{revision}_{source.name}"
            else:
                target = evidence_dir / f"{field}_{source.name}"
                # R9 (external audit r6): when the operator reconciles with a
                # NEW producer path, run[field] points back at a live landing,
                # so the branch above is skipped and this fixed name overwrote
                # the FIRST cost/measurement snapshot in place - erasing the
                # earlier reported usage with no revision to audit. Version it.
                if target.exists() and target.read_bytes() != source.read_bytes():
                    revision = int(run.get(f"{field}_snapshot_revision") or 1) + 1
                    run[f"{field}_snapshot_revision"] = revision
                    target = evidence_dir / f"{field}_r{revision}_{source.name}"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            run[f"producer_{field}"] = source_rel
            run[field] = eutil.rel(self.store.repo, target)
        run.pop("evidence_refresh_fields", None)  # one reconcile, one refresh

    def _seal_run_evidence(self, run: dict, node: dict, *, adopt: bool = True) -> None:
        artifacts: list[tuple[str, str]] = []
        # Producer landing paths may be reused by a later stage or by the
        # normalized evaluator. The immutable per-run snapshots were ingested
        # at absorption entry (before validation); seal exactly those.
        self._ingest_run_landings(run)
        for field, role in (("metrics_file", "run_metrics"), ("ledger_file", "run_ledger")):
            rel = str(run.get(field) or "")
            if rel and eutil.rpath(self.store.repo, rel).is_file():
                artifacts.append((role, rel))
        is_probe_producer, expected_probes = self._probe_expectations(run, node)
        if is_probe_producer:
            self._ingest_probe_artifacts(run, node)
            snapshots = {str(row.get("declared_artifact") or ""): row
                         for row in (run.get("probe_artifact_snapshots") or [])
                         if isinstance(row, dict)}
            present: list[str] = []
            valid_snapshots: list[dict] = []
            required_fields = [str(x) for x in
                               ((self._spec(node).get("probe_execution") or {}).get("required_fields") or [])]
            for index, row in enumerate(expected_probes):
                probe_path = str(row.get("artifact") or "")
                snapshot = snapshots.get(probe_path) or {}
                sealed_path = str(snapshot.get("snapshot_artifact") or "")
                if not sealed_path or not eutil.rpath(self.store.repo, sealed_path).is_file():
                    continue
                if evalid.probe_artifact_errors(
                        self.ctx(), sealed_path, required_fields,
                        where=f"run {run.get('id')} immutable probe {probe_path}"):
                    continue
                artifacts.append((f"mechanism_probe_{index}", sealed_path))
                present.append(probe_path)
                valid_snapshots.append(snapshot)
            if expected_probes and len(present) == len(expected_probes):
                run["producer_probe_artifacts"] = present
                if run.get("probe_evidence_status") == "unavailable":
                    run["probe_gap_superseded_at"] = eutil.utc_now()
                run["probe_evidence_status"] = "available"
            elif run.get("probe_evidence_status") == "unavailable":
                gap_rel = f".evo/runs/{run.get('id')}/evidence/PROBE_GAP.json"
                gap_path = eutil.rpath(self.store.repo, gap_rel)
                if not gap_path.is_file():
                    raise SystemExit("[evo] explicit probe-unavailability decision has no engine gap receipt")
                artifacts.append(("mechanism_probe_gap", gap_rel))
                invalid = [row for row in (run.get("probe_artifact_snapshots") or [])
                           if row not in valid_snapshots]
                for row in invalid:
                    archived = dict(row)
                    archived["superseded_at"] = eutil.utc_now()
                    archived["superseded_reason"] = "excluded from authority by explicit probe-gap decision"
                    run.setdefault("probe_snapshot_history", []).append(archived)
                run["probe_artifact_snapshots"] = valid_snapshots
            elif expected_probes:
                raise SystemExit(
                    f"[evo] RUN {run.get('id')} cannot seal incomplete mechanism-probe evidence without "
                    "an explicit same-RUN gap receipt")
        if not artifacts:
            return
        self._archive_seal(run, "evidence_seal")
        frozen_upstreams = [str(x) for x in (run.get("authority_upstreams") or []) if str(x)]
        if not frozen_upstreams:
            # Engine-created RUNs always carry the frozen list.  Keep a narrow
            # fallback for hand-built focused fixtures - over the SAME field
            # tuple as _prepare_run (the v9.2 fallback had drifted).
            frozen_upstreams = [str((node.get(field) or {}).get("digest") or "")
                                for field in AUTHORITY_UPSTREAM_FIELDS]
        run["evidence_seal"] = self._seal(
            artifacts, upstream=[digest for digest in frozen_upstreams if digest],
            revision=int(run.get("evidence_revision") or 0) + 1)
        run["evidence_revision"] = run["evidence_seal"]["revision"]
        erun.transition_evidence(run, "complete", note="engine validation and evidence seal passed")
        self._disclose_budget_overage(run, node)
        if adopt:
            slot = str(run.get("logical_slot_key") or "")
            for prior in self.st.get("runs", []):
                if prior is run or str(prior.get("logical_slot_key") or "") != slot:
                    continue
                if prior.get("adoption_status") == "adopted":
                    erun.transition_adoption(
                        prior, "superseded", note=f"active evidence head replaced by {run.get('id')}")
            erun.transition_adoption(run, "adopted")
            # R9-002: the bought-back repeat lands under its OWN head keys.
            # Sharing the base keys would evict the sealed first measurement
            # from the active-evidence view the moment the purchased second
            # one arrives - the repeat buys a second number, never a rewrite.
            if run.get("repeat_measure_attempt"):
                head_key = ("repeat_eval" if run.get("kind") == "eval"
                            else f"repeat_stage:{run.get('stage_index')}")
            else:
                head_key = ("eval" if run.get("kind") == "eval" else
                            f"stage:{run.get('replica_index')}:{run.get('stage_index')}")
            node.setdefault("evidence_heads", {})[head_key] = run.get("id")
            if is_probe_producer:
                if evalid.active_probe_unavailable(self.ctx(), node):
                    node["probe_evidence_status"] = "unavailable"
                else:
                    node.pop("probe_evidence_status", None)
        elif run.get("adoption_status") == "candidate":
            erun.transition_adoption(run, "quarantined",
                                     note="evidence sealed as history; node authority no longer expects this RUN")

    def _seal_resource_receipt(self, node: dict, run: dict) -> None:
        """Mechanically freeze raw eval-run measurements before analysis."""
        node["eval_run"] = run.get("id")
        raw = eutil.read_json(eutil.rpath(self.store.repo, str(run.get("metrics_file") or "")), {}) or {}
        spec = self._spec(node)
        measurement_errs = evalid.resource_measurement_errors(
            spec, raw, where=f"ingested eval run {run.get('id')}")
        if measurement_errs:
            raise SystemExit("[evo] cannot build a resource receipt from invalid raw measurements:\n  - "
                             + "\n  - ".join(measurement_errs))
        revision = int(node.get("resource_receipt_revision") or 0) + 1
        rel = f".evo/nodes/{node.get('id')}/eval/RESOURCE_RECEIPT_r{revision}.json"
        charges = [json.loads(json.dumps(row)) for row in self.st.get("resource_ledger", [])
                   if row.get("node") == node.get("id")]
        receipt = {
            "schema_version": 1, "producer": "engine_scheduler",
            "node": node.get("id"), "eval_run": run.get("id"),
            "spec_seal_digest": str((node.get("spec_seal") or {}).get("digest") or ""),
            "implementation_seal_digest": str((node.get("implementation_seal") or {}).get("digest") or ""),
            "workflow_reuse_seal_digest": str((node.get("workflow_reuse_seal") or {}).get("digest") or ""),
            "run_evidence_digest": str((run.get("evidence_seal") or {}).get("digest") or ""),
            "accounting": json.loads(json.dumps(((spec.get("eval") or {}).get("resource_accounting") or {}))),
            "resources": json.loads(json.dumps(raw.get("_resource_measurements") or {})),
            "resource_charges": charges, "created_at": eutil.utc_now(),
        }
        eutil.write_json_atomic(eutil.rpath(self.store.repo, rel), receipt)
        self._archive_seal(node, "resource_receipt_seal")
        upstream = [str((node.get(field) or {}).get("digest") or "")
                    for field in AUTHORITY_UPSTREAM_FIELDS]
        upstream += [str((run.get("evidence_seal") or {}).get("digest") or "")]
        node["resource_receipt_path"] = rel
        node["resource_receipt_seal"] = self._seal(
            [("engine_resource_receipt", rel)], upstream=upstream, revision=revision)
        node["resource_receipt_revision"] = revision
        node["resource_receipt_ready"] = True
        errs = evalid.resource_receipt_errors(self.ctx(), node)
        if errs:
            raise SystemExit("[evo] engine-generated resource receipt failed its own binding audit:\n  - "
                             + "\n  - ".join(errs))
        self.store.event("engine", "resource_receipt_sealed", node=node.get("id"),
                         run=run.get("id"), revision=revision,
                         digest=node["resource_receipt_seal"]["digest"])

    def _authorized_recovery_hold_for_run(self, run: dict) -> str | None:
        for case in self.st.get("recoveries", []):
            if case.get("status") == "repairing" and (case.get("scope") or {}).get("kind") == "run" \
                    and (case.get("scope") or {}).get("id") == run.get("id"):
                return str(case.get("hold") or "") or None
            if case.get("status") == "replaying":
                try:
                    members = erecover.scope_members(case.get("scope") or {}, self.st, self.g)
                except ValueError:
                    continue
                if run.get("node") in members.get("nodes", []):
                    return str(case.get("hold") or "") or None
        return None

    def _run_adoption_blocked(self, run: dict) -> bool:
        """A recovery may bypass only its own brake, never another hold.

        R7 external audit: the brake is SCOPED. active_holds_for_subject
        already returns every hold that genuinely covers this RUN's node/run
        (recovery holds included); the former second clause additionally
        froze adoption of every unrelated terminal RUN in the project for as
        long as ANY recovery hold existed anywhere - a project-global brake
        the recovery design document explicitly rejects, human-paced in
        duration because a planned case waits on plan review."""
        own_hold = self._authorized_recovery_hold_for_run(run)
        covering = set(erecover.active_holds_for_subject(
            self.st, self.g, node=run.get("node"), run=run.get("id")))
        blocking = sorted(hid for hid in covering if hid != own_hold)
        if blocking:
            # R8 audit: the deferral must OUTLIVE the hold. The hold's own
            # stdout promises "resume -> run-reconcile (adopts) -> plan
            # BEFORE next", but next's very first step is this absorption -
            # once the hold was released, the RUN was adopted before the
            # promised review window. Persist the obligation on the RUN
            # (finished runs only: a failed run's absorption is factual
            # failure routing, not authority adoption); run-reconcile - the
            # promised adopting step - clears it.
            if run.get("status") == "finished":
                run["adoption_deferred_by_hold"] = blocking
            return True
        return bool(run.get("adoption_deferred_by_hold")) and run.get("status") == "finished"

    def _absorb_finished_runs(self) -> None:
        """Engine-side processing of stage/eval runs the agent has already
        reported finished/failed via `evo run-update`. No agent task needed."""
        for run in self.st.get("runs", []):
            # Cheap filters first: the launch-task lookup is a linear scan of
            # st["tasks"], so run it only for the rare absorbable candidates.
            if run.get("kind") not in ("stage", "eval") or run.get("absorbed") \
                    or not erun.is_terminal(run) or self._run_adoption_blocked(run):
                continue
            launch_task = self.store.get_task(self.st, str(run.get("launch_task") or ""))
            if launch_task and launch_task.get("status") in {"open", "paused"}:
                continue
            self._absorb_run(run)

    @staticmethod
    def _run_evidence_is_incomplete(errors: list[str]) -> bool:
        markers = ("MISSING", "NOT_FOUND", "does not exist", "needs an existing",
                   "needs --metrics-file", "no metrics_file")
        return any(any(marker in str(error) for marker in markers) for error in errors)

    def _settle_unfinishable_launch_task(self, task: dict, run: dict | None,
                                         reason: str) -> None:
        """R11 audit (gate<->owner unity): ONE settlement for a launch task
        that can never be discharged again - its RUN is terminal (or gone), so
        neither bind, nor confirm-not-launched, nor any submit shape can ever
        be accepted. Four callers used to hold three private copies of half
        of this (update_run's stranded branch, the gap-acceptance branch) and
        two callers had none at all (the stale-escalation decision and the
        replaying recovery's stuck check) - the ownerless halves are exactly
        where a recovery wedged forever on a decision nobody could make."""
        if not task or task.get("status") not in {"open", "paused", "stuck"}:
            return
        run_id = str((run or {}).get("id") or (task.get("subject") or {}).get("run") or "")
        archive_root = eutil.rpath(
            self.store.repo, f".evo/runs/{run_id or 'unbound'}/cancelled_launch_output")
        for index, rel in enumerate(task.get("outputs") or []):
            source = eutil.rpath(self.store.repo, str(rel))
            if source.is_file():
                archive_root.mkdir(parents=True, exist_ok=True)
                source.replace(archive_root / f"{index}_{source.name}")
        task.pop("resource_reservation", None)
        task["status"] = "cancelled"
        task.pop("_render", None)
        task["cancel_reason"] = reason
        task["held_by"] = []
        task["updated_at"] = eutil.utc_now()
        self._cancel_task_gates(task, "its launch task was settled with the RUN")
        self.store.event("engine", "unfinishable_launch_task_settled",
                         task=task.get("id"), run=run_id or None, reason=reason)

    def _cancel_task_gates(self, task: dict, reason: str) -> None:
        """R9 (external audit r6): cancelling/superseding a task must retire the
        undecided gates that point at it, in the SAME transition. A surviving
        escalation gate is presented before all other work and its APPROVE
        reopens a task whose world has moved on."""
        tid = str(task.get("id") or "")
        if not tid:
            return
        for gate in self.st.get("gates", []):
            if gate.get("status") not in ("open", "paused"):
                continue
            if str((gate.get("subject") or {}).get("task") or "") != tid:
                continue
            gate["status"] = "cancelled"
            gate["resolved_at"] = eutil.utc_now()
            gate["note"] = f"superseded: {reason}"
            self.store.event("engine", "gate_cancelled", gate=gate.get("id"),
                             reason="task_superseded", task=tid)

    def _mark_run_evidence_pending(self, node: dict, run: dict,
                                   errors: list[str]) -> None:
        target = self._record_run_evidence_errors(run, errors)
        # R9 (external audit r6): the producer already reported what it spent.
        # Evidence being INVALID (e.g. over its declared cap) must not make that
        # cost invisible to capacity: hold the higher of reserved vs reported so
        # a sibling cannot launch into money that is already gone. This raises a
        # RESERVATION, never a charge - evidence validity is untouched.
        reported = None
        mf = str(run.get("metrics_file") or "")
        if mf:
            data = eutil.read_json(eutil.rpath(self.store.repo, mf), {}) or {}
            field = "usage" if run.get("kind") == "stage" else "_usage"
            if isinstance(data, dict) and isinstance(data.get(field), dict):
                reported = data[field]
        if isinstance(reported, dict) and not run.get("resource_accounted"):
            held = dict(run.get("resource_reservation") or {})
            bumped = {}
            for unit, value in reported.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    continue
                if not math.isfinite(float(value)) or float(value) < 0:
                    continue
                if float(value) > float(held.get(str(unit), 0.0) or 0.0):
                    bumped[str(unit)] = float(value)
            if bumped:
                held.update(bumped)
                run["resource_reservation"] = held
                self.store.event("engine", "reservation_raised_to_reported", run=run.get("id"),
                                 node=node.get("id"), units=bumped)
        run["absorbed"] = True
        node["status"] = "evidence_pending"
        node["evidence_pending_run"] = run["id"]
        egraph.touch(node)
        self.store.event("engine", "run_evidence_pending", node=node["id"], run=run["id"],
                         evidence_status=target, errors=errors[:12])

    def _disclose_budget_overage(self, run: dict, node: dict) -> None:
        """v12: an over-cap-but-within-band ingestion leaves a visible trace.

        The tolerance band (econfig.budget_tolerance) moves only the validity
        judgment; honesty requires the overage FACT to be on the record the
        moment the evidence is accepted, not discoverable only by re-deriving
        usage against caps later. No numbers change - this is disclosure.
        """
        mf = str(run.get("metrics_file") or "")
        data = (eutil.read_json(eutil.rpath(self.store.repo, mf), {}) or {}) if mf else {}
        if not isinstance(data, dict):
            return
        spec = self._spec(node)
        if run.get("kind") == "stage":
            stages = econfig.stages_of(spec)
            idx = run.get("stage_index")
            # Self-review F1a: mirror _run_result_errors' stage resolution
            # exactly (index, then name fallback) - a name-resolved row that
            # sealed without a stamp would fail forever under a later, lower
            # band at doctor replay.
            stage = (stages[idx] if isinstance(idx, int) and not isinstance(idx, bool)
                     and 0 <= idx < len(stages) else
                     next((row for row in stages if row.get("name") == run.get("stage")), {}))
            limits = ((stage.get("budget") or {}).get("limits") or {})
            usage = data.get("usage")
        else:
            limits = econfig.eval_budget(spec)
            usage = data.get("_usage")
        if not isinstance(usage, dict):
            return
        for unit, limit in limits.items():
            actual = usage.get(unit)
            if isinstance(actual, bool) or not isinstance(actual, (int, float)):
                continue
            if isinstance(limit, (int, float)) and float(limit) + 1e-12 < float(actual):
                # Sealing implies the validators admitted these numbers, so an
                # over-cap seal was necessarily authorized by SOME band. Do
                # not trust the live config for the stamp (self-review F1b: a
                # crash-replay re-seals in a LATER invocation, possibly after
                # the band was lowered) - record at least the minimal band the
                # sealed ratio itself proves, so the floor survives any era.
                band = max(econfig.budget_tolerance(self.cfg),
                           float(actual) / float(limit) * (1.0 + 1e-9))
                row = {"unit": str(unit), "actual": float(actual), "cap": float(limit), "band": band}
                stamps = run.setdefault("budget_overages_within_tolerance", [])
                if any(r.get("unit") == row["unit"] and r.get("actual") == row["actual"]
                       and r.get("cap") == row["cap"] for r in stamps if isinstance(r, dict)):
                    continue  # re-seal (reconcile/revision) repeats the numbers, not the fact
                stamps.append(row)
                self.store.event("engine", "budget_overage_within_tolerance",
                                 run=str(run.get("id") or ""), node=str(node.get("id") or ""),
                                 unit=str(unit), actual=float(actual), cap=float(limit), band=band)

    def _record_run_evidence_errors(self, run: dict, errors: list[str]) -> str:
        target = "incomplete" if self._run_evidence_is_incomplete(errors) else "invalid"
        erun.transition_evidence(run, target, note="; ".join(errors[:12]))
        run["evidence_errors"] = errors[:24]
        return target

    def _run_result_errors(self, run: dict, node: dict, *, enforce_current: bool) -> list[str]:
        spec = self._spec(node)
        is_probe_producer, _ = self._probe_expectations(run, node)
        probe_sources = (evalid.probe_snapshot_map(run) if is_probe_producer else
                         evalid.active_probe_snapshot_map(self.ctx(), node))
        expected_probes = evalid.expected_probe_observations(spec)
        if run.get("kind") == "stage":
            expected_probes = [row for row in expected_probes
                               if type(row.get("seed")) is type(run.get("replica_seed"))
                               and row.get("seed") == run.get("replica_seed")]
        required_probe_fields = [str(x) for x in
                                 ((spec.get("probe_execution") or {}).get("required_fields") or [])]
        probe_bytes_complete = bool(expected_probes) and all(
            bool(source := probe_sources.get(str(row.get("artifact") or ""))) and
            not evalid.probe_artifact_errors(
                self.ctx(), source, required_probe_fields,
                where=f"run {run.get('id')} immutable probe")
            for row in expected_probes)
        # R9-002: the repeat attempt carries no probe duty at all (mechanism
        # authority stays with the base head; _probe_expectations already
        # returns no expectations for it) - so its raw metrics are validated
        # with the probe envelope waived, not against the base snapshots.
        allow_probe_gap = (bool(run.get("repeat_measure_attempt"))
                           or ((run.get("probe_evidence_status") == "unavailable"
                                or (run.get("kind") == "eval"
                                    and evalid.active_probe_unavailable(self.ctx(), node)))
                               and not probe_bytes_complete))
        if run.get("kind") == "eval":
            errors = evalid.evaluation_result_errors(
                self.ctx(), spec, run.get("metrics_file"), where=f"run {run.get('id')} evaluation",
                allow_probe_unavailable=allow_probe_gap,
                probe_artifact_sources=probe_sources)
            metrics_path = eutil.rpath(self.store.repo, str(run.get("metrics_file") or ""))
            raw = eutil.read_json(metrics_path, {}) if metrics_path.is_file() else {}
            errors.extend(evalid.resource_measurement_errors(
                spec, raw, where=f"run {run.get('id')} evaluation"))
            if run.get("repeat_measure_attempt"):
                # R9-002 (reviewer finding): the repeat evaluation's landing
                # identity is enforced like the stage half - reporting the
                # base attempt's leftover landing would let the pin check
                # endorse a copied base value as the "repeat measurement".
                declared = eutil.norm_uri(str(run.get("declared_metrics_file") or ""))
                produced = eutil.norm_uri(str(run.get("producer_metrics_file")
                                              or run.get("metrics_file") or ""))
                if declared and produced != declared:
                    errors.append(
                        f"EVAL_REPEAT_LANDING: run {run.get('id')} reported metrics at "
                        f"{produced!r}, but the repeat lane's engine-derived landing is "
                        f"{declared!r} - the repeat reports at the evaluation's own declared "
                        "landing (the base leftover there was archived at prepare; its sealed "
                        "evidence is immutable), never anywhere else")
            return errors
        stages = stages_of(spec)
        stage_index = run.get("stage_index")
        stage = (stages[stage_index] if isinstance(stage_index, int) and not isinstance(stage_index, bool)
                 and 0 <= stage_index < len(stages) else
                 next((row for row in stages if row.get("name") == run.get("stage")), {}))
        seed = run.get("replica_seed")
        errors: list[str] = []
        if not stage:
            return [f"RUN_STAGE_UNKNOWN: run {run.get('id')} has no matching frozen workflow stage"]
        if enforce_current:
            cur = int(node.get("stage_cursor") or 0)
            if run.get("repeat_measure_attempt"):
                # R9-002: the repeat lane's expected position is the pending
                # repeat seed with no replica index (it is not a preplanned
                # lane), judged against the same stage cursor.
                expected_index = None
                expected_seed = node.get("repeat_pending_seed")
            else:
                expected_index = int(node.get("replica_index") or 0)
                expected_seed = econfig.workflow_seed(spec, expected_index)
            if stage_index not in (None, cur) or run.get("replica_index") not in (None, expected_index) \
                    or type(seed) is not type(expected_seed) or seed != expected_seed:
                errors.append(
                    f"RUN_WORKFLOW_POSITION: run {run.get('id')} belongs to seed/index/stage "
                    f"{seed!r}/{run.get('replica_index')}/{stage_index}, "
                    f"but node expects {expected_seed!r}/{expected_index}/{cur}")
        strict_paths = ((spec.get("training_replication") or {}).get("mode") == "preplanned")
        if run.get("repeat_measure_attempt") and seed is not None:
            # R9-002/R10-012: the repeat attempt lands at the spec's OWN
            # resolved paths (one resolution rule for every attempt); path
            # identity stays enforced so the repeat cannot report elsewhere.
            expected_metrics = str(econfig.resolve_seed_template(stage.get("metrics_file") or "", seed))
            expected_ledger = str(econfig.resolve_seed_template(stage.get("ledger_file") or "", seed)) \
                if econfig.stage_requires_ledger(stage) else None
        else:
            expected_metrics = str(econfig.resolve_seed_template(stage.get("metrics_file") or "", seed)) \
                if seed is not None and strict_paths else None
            expected_ledger = str(econfig.resolve_seed_template(stage.get("ledger_file") or "", seed)) \
                if seed is not None and strict_paths and econfig.stage_requires_ledger(stage) else None
        # R7: path IDENTITY binds the producer landing (where the job wrote),
        # which ingestion preserves as producer_*; CONTENT reads use the
        # ingested immutable snapshot in run["metrics_file"].
        declared_metrics = str(run.get("producer_metrics_file") or run.get("metrics_file") or "")
        declared_ledger = str(run.get("producer_ledger_file") or run.get("ledger_file") or "")
        metrics_path = eutil.rpath(self.store.repo, str(run.get("metrics_file") or ""))
        metrics = eutil.read_json(metrics_path, None) if metrics_path.is_file() else None
        errors.extend(evalid.stage_result_errors(
            self.ctx(), stage, declared_metrics or None, declared_ledger or None,
            where=f"run {run.get('id')} stage {run.get('stage')} seed {seed!r}",
            metrics_data=metrics,
            expected_seed=(seed if (strict_paths or run.get("repeat_measure_attempt")) else None),
            expected_metrics_file=expected_metrics, expected_ledger_file=expected_ledger))
        errors.extend(evalid.stage_probe_errors(
            self.ctx(), spec, stage, seed, where=f"run {run.get('id')} stage {run.get('stage')} probe",
            allow_unavailable=allow_probe_gap, artifact_sources=probe_sources))
        return errors

    @staticmethod
    def _clear_run_evidence_pending(node: dict, run: dict) -> None:
        if node.get("evidence_pending_run") == run.get("id"):
            node.pop("evidence_pending_run", None)

    def bind_run(self, run_id: str, job: str, attempt_token: str) -> dict:
        """Idempotently bind the pre-recorded attempt to one platform job."""
        self._assert_frozen_contract()
        run = self.store.get_run(self.st, run_id)
        if run is None:
            raise SystemExit(f"[evo] no run {run_id}")
        self._assert_artifact_seals(only_node=str(run.get("node") or "") or None)
        if str(run.get("attempt_token") or "") != str(attempt_token or ""):
            raise SystemExit("[evo] attempt token does not match the prepared RUN")
        try:
            erun.transition_execution(run, "running", job=str(job or ""),
                                      note="platform job bound through run-bind")
        except erun.RunError as exc:
            raise SystemExit(f"[evo] cannot bind {run_id}: {exc}") from exc
        self.store.event("agent", "run_bound", run=run_id, job=run.get("job"),
                         attempt_key=run.get("attempt_key"))
        self.save()
        return run

    def confirm_run_not_launched(self, run_id: str, note: str) -> dict:
        self._assert_frozen_contract()
        run = self.store.get_run(self.st, run_id)
        if run is None:
            raise SystemExit(f"[evo] no run {run_id}")
        try:
            erun.confirm_not_launched(run, note=note)
        except erun.RunError as exc:
            raise SystemExit(f"[evo] cannot reconcile non-launch for {run_id}: {exc}") from exc
        node = self.node(str(run.get("node") or ""))
        if node and node.get("status") == "abandoned":
            erun.transition_execution(run, "cancelled", note="owner abandoned; confirmed never launched")
            erun.transition_evidence(run, "complete", note="confirmed no external effect")
            if run.get("adoption_status") == "candidate":
                erun.transition_adoption(run, "quarantined", note="owner abandoned before launch")
            self._charge_resource(node=node["id"], kind=str(run.get("kind") or "run"), usage={},
                                  basis="confirmed_unlaunched", run=run)
            run["absorbed"] = True
        self.store.event("user", "run_non_launch_confirmed", run=run_id, note=note)
        self.save()
        return run

    def update_run(self, run_id: str, status: str, *, metrics_file: str | None = None,
                   ledger_file: str | None = None, note: str | None = None,
                   failure_class: str | None = None,
                   repair_scope: str | None = None) -> dict:
        """Record execution truth; evidence completeness is deliberately separate."""
        self._assert_frozen_contract()
        run = self.store.get_run(self.st, run_id)
        if run is None:
            raise SystemExit(f"[evo] no run {run_id}")
        self._assert_artifact_seals(only_node=str(run.get("node") or "") or None)
        target = "finished" if status in {"succeeded", "finished"} else status
        if target not in {"running", "finished", "failed", "cancelled"}:
            raise SystemExit("[evo] --status must be running|succeeded|finished|failed|cancelled")
        for label, rel in (("metrics", metrics_file), ("ledger", ledger_file)):
            if rel and not eutil.rpath(self.store.repo, rel).is_file():
                raise SystemExit(f"[evo] {label} file {rel} does not exist")
        if erun.is_terminal(run):
            if target != run.get("status"):
                raise SystemExit("[evo] terminal execution facts are immutable; a different execution needs a new RUN")
            supplied = {"metrics_file": metrics_file, "ledger_file": ledger_file,
                        "failure_class": failure_class, "repair_scope": repair_scope,
                        "note": note}
            changed = [field for field, value in supplied.items()
                       if value is not None and str(value) != str(run.get(field) or "")]
            if changed:
                hint = ("use run-reconcile for late evidence" if run.get("status") == "finished"
                        and run.get("adoption_status") not in {"adopted", "superseded"}
                        else "accepted facts require a reviewed recovery/new attempt")
                raise SystemExit(f"[evo] terminal RUN fields cannot be rewritten ({', '.join(changed)}); {hint}")
            return run
        if target == "failed":
            if failure_class not in {"infrastructure", "implementation", "operator", "unknown"}:
                raise SystemExit("[evo] failed runs need --failure-class infrastructure|implementation|operator|unknown")
            if not str(note or "").strip():
                raise SystemExit("[evo] failed runs need --note with the observed error")
            if failure_class == "implementation":
                if repair_scope not in {"evaluation", "workflow"}:
                    raise SystemExit("[evo] implementation failures need --repair-scope evaluation|workflow")
                if run.get("kind") != "eval" and repair_scope != "workflow":
                    raise SystemExit("[evo] only an eval RUN may use --repair-scope evaluation; "
                                     "a workflow-stage implementation failure needs scope workflow")
            elif repair_scope is not None:
                raise SystemExit("[evo] --repair-scope is only valid with --failure-class implementation")
        confirmed_unlaunched = bool(
            target == "cancelled" and run.get("status") == "prepared"
            and run.get("launch_reconciled_at") and not str(run.get("job") or "").strip())
        try:
            erun.transition_execution(run, target, note=note)
        except erun.RunError as exc:
            raise SystemExit(f"[evo] cannot update {run_id}: {exc}") from exc
        if target == "failed":
            run["failure_class"] = failure_class
            if repair_scope:
                run["repair_scope"] = repair_scope
        if target == "finished":
            run["metrics_file"] = metrics_file or run.get("metrics_file")
            run["ledger_file"] = ledger_file or run.get("ledger_file")
            # R10-004: the hold-review obligation is persisted at the moment
            # the terminal fact lands, not at whichever later scan happens to
            # run first - otherwise "run-update then resume" and "run-update
            # then next then resume" gave the same facts different adoption
            # semantics (the first skipped the promised reconcile review).
            # _run_adoption_blocked writes the durable marker as a side
            # effect when an active hold covers this finished RUN.
            self._run_adoption_blocked(run)
        if confirmed_unlaunched:
            run["confirmed_not_launched"] = True
            erun.transition_evidence(run, "complete", note="confirmed no external execution")
            if run.get("adoption_status") == "candidate":
                erun.transition_adoption(run, "quarantined", note="unspent launch intent discarded")
            self._charge_resource(node=str(run.get("node") or ""),
                                  kind=str(run.get("kind") or "run"), usage={},
                                  basis="confirmed_unlaunched", run=run)
            run["absorbed"] = True
            launch_task = self.store.get_task(self.st, str(run.get("launch_task") or ""))
            if launch_task and launch_task.get("status") in {"open", "paused", "stuck"}:
                archive_root = eutil.rpath(
                    self.store.repo, f".evo/runs/{run_id}/cancelled_launch_output")
                for index, rel in enumerate(launch_task.get("outputs") or []):
                    source = eutil.rpath(self.store.repo, str(rel))
                    if source.is_file():
                        archive_root.mkdir(parents=True, exist_ok=True)
                        source.replace(archive_root / f"{index}_{source.name}")
                launch_task.pop("resource_reservation", None)
                launch_task["status"] = "cancelled"
                launch_task.pop("_render", None)
                launch_task["cancel_reason"] = "confirmed-unlaunched RUN intent was discarded"
                launch_task["held_by"] = []
                launch_task["updated_at"] = eutil.utc_now()
                # Same-transaction gate cleanup as the stranded branch below:
                # a stuck launch card may carry an open escalation gate, and a
                # cancelled task's gate otherwise survives as a decision the
                # stale-check must later self-cancel (pure noise).
                self._cancel_task_gates(launch_task, "its launch task was settled with the RUN")
            self.store.event("user", "unlaunched_run_intent_cancelled", run=run_id,
                             note=note or run.get("note"))
        # R9 (external audit r6): a launcher can die BEFORE the platform returns
        # a job id. The terminal fact is legal and irreversible, but the launch
        # card that produced it had no failure output shape - background needs a
        # job, completed needs passing metrics, confirm-not-launched only accepts
        # launch_unknown - so every later `next` re-presented a card nobody could
        # honestly submit. Settle the card in the same transition as the RUN.
        if target in ("failed", "cancelled") and not confirmed_unlaunched \
                and not str(run.get("job") or "").strip():
            stranded = self.store.get_task(self.st, str(run.get("launch_task") or ""))
            if stranded is not None:
                self._settle_unfinishable_launch_task(
                    stranded, run,
                    f"RUN {run_id} ended '{target}' before any job id existed; "
                    "the launch receipt can never be produced")
        self.store.event("agent", "run_update", run=run_id, status=target,
                         evidence_status=run.get("evidence_status"), note=note,
                         failure_class=failure_class, repair_scope=repair_scope)
        self.save()
        return run

    def reconcile_run(self, run_id: str, *, metrics_file: str | None = None,
                      ledger_file: str | None = None, accept_missing_probe: bool = False,
                      note: str | None = None,
                      accept_missing_evidence: bool = False) -> dict:
        """Attach late bytes to the same finished attempt and re-run ingestion.

        ``accept_missing_evidence`` (R9 audit): the USER's terminal
        disposition for materials that are confirmed permanently unavailable.
        A run abandoned mid-flight whose late arrival lacked its files used to
        keep an evidence obligation open forever with no closing verb (the
        probe gap had one, ordinary materials did not) - blocking landings and
        the terminal verdict while nothing could ever settle it."""
        self._assert_frozen_contract()
        run = self.store.get_run(self.st, run_id)
        if run is None:
            raise SystemExit(f"[evo] no run {run_id}")
        node = self.node(str(run.get("node") or ""))
        if node is None:
            raise SystemExit(f"[evo] run {run_id} has no owning node")
        self._assert_artifact_seals(only_node=node["id"])
        if accept_missing_evidence:
            if not str(note or "").strip():
                raise SystemExit("[evo] --accept-missing-evidence needs --note explaining why the "
                                 "materials are permanently unavailable")
            if metrics_file or ledger_file or accept_missing_probe:
                raise SystemExit("[evo] --accept-missing-evidence closes the gap on record; do not "
                                 "combine it with supplied files or the probe disposition")
            if not erun.is_terminal(run):
                raise SystemExit("[evo] settle the execution fact first (run-update / run-bind / "
                                 "run-confirm-not-launched); the evidence disposition comes after")
            if run.get("evidence_disposition") in erun.TERMINAL_EVIDENCE_DISPOSITIONS:
                raise SystemExit("[evo] this RUN already carries a terminal evidence disposition")
            if run.get("adoption_status") == "adopted":
                raise SystemExit("[evo] adopted evidence is immutable; use recover-plan for an "
                                 "authority revision")
            # v12 field case (RUN143 class): a finished RUN whose ONLY defect
            # is a declared-cap overage has its materials right there - the
            # terminal disposition below discards evidence that a raised
            # validity band would adopt as-is. Say so on the way through; the
            # user's --note already makes this a knowing decision.
            budget_only = bool(run.get("evidence_errors")) and all(
                "BUDGET_EXCEEDED" in str(e) for e in (run.get("evidence_errors") or []))
            if budget_only and str(run.get("metrics_file") or "") and                     eutil.rpath(self.store.repo, str(run.get("metrics_file"))).is_file():
                print("[evo] CAUTION: this RUN's materials exist; its only defect is a budget-cap "
                      "overage. Raising the config key stage_budget_tolerance and "
                      f"'evo run-reconcile --run {run_id}' (without this flag) would adopt the "
                      "SAME evidence with no rerun. Proceeding discards it terminally.")
            # R10-014 (shape b): an applied stage_evidence recovery's whole
            # completion condition is THIS RUN reaching complete+adopted. A
            # terminal disposition makes that condition unsatisfiable forever
            # - the case would sit repairing while every same-RUN verb is
            # refused. The disposition therefore settles the case in the SAME
            # transition: it ends as failed-with-reason, its hold releases,
            # and the owner routing below gives the node its ordinary
            # retry/spend path (no forced abandonment).
            owning_case = next(
                (c for c in self.st.get("recoveries", [])
                 if c.get("status") == "repairing"
                 and (c.get("scope") or {}).get("kind") == "run"
                 and str((c.get("scope") or {}).get("id") or "") == run_id), None)
            if owning_case is not None:
                self._terminate_recovery(
                    owning_case, status="failed",
                    result=f"target RUN {run_id}'s materials were declared permanently "
                           f"unavailable by the user: {note}")
            if run.get("status") == "finished" and run.get("evidence_status") == "pending":
                erun.transition_evidence(run, "invalid",
                                         note=f"never audited; materials declared unavailable: {note}")
            receipt_rel = f".evo/runs/{run_id}/evidence/IRRECOVERABLE.json"
            eutil.write_json_atomic(eutil.rpath(self.store.repo, receipt_rel), {
                "schema_version": 1, "run": run_id, "node": node["id"],
                "disposition": "irrecoverable_quarantined",
                "reason": str(note), "evidence_status": run.get("evidence_status"),
                "errors": list(run.get("evidence_errors") or []),
                "recorded_at": eutil.utc_now(),
            })
            run["evidence_disposition"] = "irrecoverable_quarantined"
            run["evidence_disposition_receipt"] = receipt_rel
            if run.get("adoption_status") == "candidate":
                erun.transition_adoption(run, "quarantined",
                                         note="materials permanently unavailable; gap closed by the user")
            if not run.get("resource_accounted"):
                self._account_run(run)
            run["absorbed"] = True
            run.pop("adoption_deferred_by_hold", None)
            # R10 self-audit: a still-open launch card for this RUN has no
            # legal submission shape once the RUN is terminally dispositioned
            # - settle it in the SAME transition through the shared primitive.
            launch_task = self.store.get_task(self.st, str(run.get("launch_task") or ""))
            if launch_task is not None:
                self._settle_unfinishable_launch_task(
                    launch_task, run,
                    "the RUN's evidence gap was accepted as permanent; "
                    "the launch receipt can never be produced")
            self.store.event("user", "run_evidence_gap_accepted", run=run_id,
                             node=node["id"], note=note)
            pending_match = (node.get("status") == "evidence_pending"
                             and node.get("evidence_pending_run") == run_id)
            # R10-014 (shape a): the v11.4 seam fix routed only the
            # evidence_pending holder; a node still executing/evaluating on
            # this very attempt (the finished RUN not yet absorbed - a hold
            # window, or accept before the next scan) was left claiming to
            # execute forever with no live RUN, no material obligation and no
            # generatable card. ONE ownership predicate now decides: the
            # current attempt's disposition always routes its owner through
            # the ordinary failure channel (replacement spend stays behind
            # its protected gate; exhaustion still escalates).
            if pending_match or (node.get("status") in ("executing", "evaluating")
                                 and self._run_is_current_attempt(run, node)):
                self._clear_run_evidence_pending(node, run)
                if run.get("kind") == "eval":
                    self._handle_eval_failure(node, run)
                else:
                    self._handle_stage_failure(node, run)
            self.save()
            return run
        if run.get("status") != "finished":
            raise SystemExit("[evo] only a successfully finished RUN can reconcile result evidence")
        if run.get("evidence_disposition") in erun.TERMINAL_EVIDENCE_DISPOSITIONS:
            raise SystemExit("[evo] this RUN was terminally quarantined by an aborted recovery; "
                             "its historical evidence gap is immutable")
        if run.get("adoption_status") in {"adopted", "superseded"}:
            raise SystemExit("[evo] accepted/superseded evidence is immutable; use recover-plan for an authority revision")
        if run.get("evidence_status") == "complete":
            raise SystemExit("[evo] this RUN already has a sealed complete historical package; it is immutable")
        for label, rel in (("metrics", metrics_file), ("ledger", ledger_file)):
            if rel and not eutil.rpath(self.store.repo, rel).is_file():
                raise SystemExit(f"[evo] {label} file {rel} does not exist")
        # R7 external audit: a supplied landing must not be one a LIVE sibling
        # RUN currently leases - reading it would ingest the sibling's bytes
        # under this RUN's identity.
        lease = self._landing_lease_holder(metrics_file or "", ledger_file or "",
                                           exclude_run=run_id)
        if lease is not None:
            raise SystemExit(
                f"[evo] that landing path is leased by live RUN {lease.get('id')} "
                f"({lease.get('status')}); settle it first or supply this RUN's own bytes "
                "at a distinct path")
        refresh = set()
        if metrics_file:
            run["metrics_file"] = metrics_file
            refresh.add("metrics_file")
        if ledger_file:
            run["ledger_file"] = ledger_file
            refresh.add("ledger_file")
        # Fields NOT explicitly resupplied may still be repaired IN PLACE at
        # their original producer landing (fix-the-file-then-reconcile is the
        # documented same-RUN repair loop). That re-read is safe exactly when
        # no LATER attempt has claimed the same landing meanwhile - otherwise
        # the bytes there are a sibling's results and re-ingesting them seals
        # the wrong producer's science under this RUN (the R7-010 poisoning).

        def _run_seq(row) -> int:
            try:
                return int(str((row or {}).get("id") or "RUN0")[3:])
            except ValueError:
                return 0

        def _later_claimant(rel: str):
            wanted = eutil.norm_uri(rel)
            if not wanted:
                return None
            # R9 audit: judged against the full claim set (probe artifact and
            # seed-resolved products included), not just the two declared
            # landing fields. R10-002: overlap-aware (directory vs child).
            # G-3: legacy rows are backfilled before judging.
            for r2 in self.st.get("runs", []):
                if str(r2.get("id") or "") == run_id or _run_seq(r2) <= _run_seq(run):
                    continue
                self._ensure_run_claims(r2)
                if any(eutil.paths_overlap(wanted, c) for c in self._run_claim_set(r2)):
                    return r2
            return None

        # R8 audit: the later-claimant rule must also cover EXPLICITLY
        # resupplied paths. With the claimant already terminal, the live-lease
        # check above passes, and the old code skipped resupplied fields here
        # - so pointing --metrics-file at the shared landing ingested the
        # sibling's bytes under this RUN's identity. Refuse outright: the fix
        # is to supply this RUN's own bytes at a distinct path.
        for field in sorted(refresh):
            supplied = str(run.get(field) or "")
            claimant = _later_claimant(supplied)
            if claimant is not None:
                raise SystemExit(
                    f"[evo] {field} path {supplied!r} was later claimed by RUN "
                    f"{claimant.get('id')} - its bytes there are not this RUN's evidence; "
                    "supply this RUN's own bytes at a distinct path")
        for field in ("metrics_file", "ledger_file"):
            if field in refresh:
                continue
            producer = str(run.get(f"producer_{field}") or "")
            claimant = _later_claimant(producer)
            if claimant is not None:
                self.store.event("engine", "run_landing_refresh_suppressed", run=run_id,
                                 field=field, landing=eutil.norm_uri(producer),
                                 claimed_by=claimant.get("id"))
                continue
            if producer:
                refresh.add(field)
        if refresh:
            # field-level revision marker: only these fields re-read producer
            # bytes at the next ingest (see _ingest_run_landings)
            run["evidence_refresh_fields"] = sorted(refresh)
        if accept_missing_probe:
            if not str(note or "").strip():
                raise SystemExit("[evo] --accept-missing-probe needs --note explaining why the observation is unrecoverable")
            # R9-002 pairing: judge producer-ship through the SAME predicate
            # absorption/claims/seal use. The repeat buy-back lane is never a
            # probe producer, so a probe-gap disposition on it must be refused
            # here too - accepting it used to stamp probe_evidence_status=
            # "unavailable" on a lane with no probe duty, and once that RUN
            # became the repeat_eval head, active_probe_unavailable degraded
            # the whole node's mechanism evidence from a lane that never owed
            # any.
            is_producer, _ = self._probe_expectations(run, node)
            if not is_producer:
                raise SystemExit("[evo] this RUN is not the frozen mechanism-probe producer"
                                 + (" (the repeat buy-back lane carries no probe duty)"
                                    if run.get("repeat_measure_attempt") else ""))
            probe = self._spec(node).get("probe_execution") or {}
            gap_rel = f".evo/runs/{run_id}/evidence/PROBE_GAP.json"
            eutil.write_json_atomic(eutil.rpath(self.store.repo, gap_rel), {
                "schema_version": 1, "run": run_id, "node": node["id"],
                "status": "unavailable", "reason": str(note),
                "expected_artifact": probe.get("artifact"), "recorded_at": eutil.utc_now(),
            })
            run["probe_evidence_status"] = "unavailable"
            run["probe_gap_receipt"] = gap_rel
        run["absorbed"] = False
        run.pop("evidence_errors", None)
        # R8 audit: run-reconcile IS the promised adopting step after a hold
        # review - clear the persisted deferral BEFORE the blocked check so a
        # released hold's obligation ends here (a still-active hold keeps
        # deferring below).
        run.pop("adoption_deferred_by_hold", None)
        self.store.event("user", "run_evidence_reconciled", run=run_id,
                         metrics_file=metrics_file, ledger_file=ledger_file,
                         probe_unavailable=accept_missing_probe, note=note)
        if self._run_adoption_blocked(run):
            self.store.event("engine", "run_evidence_adoption_deferred", run=run_id,
                             reason="active authority hold")
        else:
            self._absorb_run(run)
        self.save()
        return run

    def _absorb_run(self, run: dict) -> None:
        if run.get("absorbed"):
            return
        # R8 follow-up: the hold-review deferral must hold at THIS choke
        # point, not only in the periodic sweep - the launch-card submit arms
        # call here directly, and used to adopt a reviewed RUN right past an
        # active hold (and past the persisted deferral marker). run-reconcile
        # clears the marker before it calls in, so the promised
        # "reconcile adopts" path is unaffected.
        if run.get("kind") in ("stage", "eval") and self._run_adoption_blocked(run):
            self.store.event("engine", "run_evidence_adoption_deferred",
                             run=run.get("id"), reason="hold review pending")
            return
        node = self.node(run.get("node") or "")
        if run.get("status") == "finished":
            self._ingest_run_landings(run)
        if node is not None and run.get("status") == "finished":
            self._ingest_probe_artifacts(run, node)
        expect = "executing" if run.get("kind") == "stage" else "evaluating"
        recovering_same_run = bool(node and node.get("status") == "evidence_pending" and
                                   node.get("evidence_pending_run") == run.get("id"))
        # R9 (external audit r6): crash-replay convergence. save_all commits
        # graph/registry BEFORE the state marker; a crash in that window leaves
        # the GRAPH already advanced by this very absorption (node moved on,
        # this RUN recorded as an evidence head) while the old state still says
        # unabsorbed. The late-run branch then QUARANTINED our own already-
        # credited evidence - graph pointing at an inactive head forever, with
        # reconcile/recovery both refusing that shape. If the graph already
        # names this RUN as an evidence head or the active eval run, this is
        # the replay of a committed absorption: finish it forward (adopt).
        own_replay = bool(
            node is not None and run.get("status") == "finished"
            and (run.get("id") in set((node.get("evidence_heads") or {}).values())
                 or node.get("eval_run") == run.get("id")
                 or node.get("repeat_eval_run") == run.get("id")))
        if own_replay and node.get("status") != expect and not recovering_same_run:
            if run.get("evidence_status") != "complete":
                self._seal_run_evidence(run, node)
            self._account_run(run)
            run["absorbed"] = True
            if run.get("adoption_status") == "candidate":
                erun.transition_adoption(run, "adopted",
                                         note="crash-replay of an absorption the graph already credits")
            if run.get("kind") == "eval" and run.get("repeat_measure_attempt"):
                # R9-002 replay convergence: the graph already credits this
                # repeat evaluation - converge the repeat bookkeeping the
                # crash may have dropped, and leave the BASE eval fields
                # (eval_run, floor freeze, receipt) strictly alone.
                rm = node.get("repeat_measure")
                if isinstance(rm, dict):
                    rm.setdefault("eval_run", run["id"])
                node.setdefault("repeat_eval_run", run["id"])
                node.pop("repeat_pending_seed", None)
                self._flush_repeat_product_registrations(node)
            elif run.get("kind") == "eval":
                # both are idempotent (calibration keys on the eval RUN id, the
                # repeat gate deduplicates) - re-run them so the state-side
                # effects the crash dropped converge too
                node.setdefault("eval_run", run["id"])
                node["eval_resource_accounted"] = True
                self._calibrate_observed_noise(node, run)
                self._maybe_open_repeat_measure(node, run)
            else:
                stop = node.get("scientific_stop") if isinstance(node.get("scientific_stop"), dict) else {}
                if str(stop.get("run") or "") == str(run.get("id") or ""):
                    # The committed absorption STOPPED at this stage: converge
                    # to the same shape - the original transaction deliberately
                    # registered no artifacts for a stopped stage, and the
                    # run-side gate fields (state, dropped by the crash) are
                    # restored from the graph's stop record. Plain assignment:
                    # new_run pre-initializes both keys to None, so setdefault
                    # would never write (the doctor's gate-drift audit then
                    # reported the None forever, with no repair verb).
                    if run.get("scientific_outcome") is None:
                        run["scientific_outcome"] = "stop_node"
                    if run.get("scientific_gate") is None and stop.get("gate") is not None:
                        run["scientific_gate"] = stop.get("gate")
                else:
                    spec = self._spec(node)
                    stages = stages_of(spec)
                    sidx = run.get("stage_index")
                    if isinstance(sidx, int) and not isinstance(sidx, bool) and 0 <= sidx < len(stages):
                        # A gated stage that did NOT stop also recorded its
                        # verdict on the run (state, dropped by the crash):
                        # recompute it from the same frozen metrics the
                        # original transaction read, exactly as the doctor's
                        # drift audit will.
                        if run.get("scientific_gate") is None:
                            frozen = eutil.read_json(
                                eutil.rpath(self.store.repo, run.get("metrics_file") or ""), {}) or {}
                            decision = evalid.stage_gate_decision(stages[sidx], frozen)
                            if decision is not None:
                                run["scientific_outcome"] = decision["outcome"]
                                run["scientific_gate"] = decision
                        # registry may be one write behind the graph (it commits
                        # between graph and state) - registration is a no-op when
                        # the rows already exist (and a repeat stage stays
                        # deferred, exactly as the committed transaction chose)
                        self._register_or_defer_stage_products(
                            node, stages[sidx], sidx, run.get("replica_seed"), run)
            self.store.event("engine", "run_replay_converged", run=run["id"], node=node.get("id"),
                             node_status=node.get("status"))
            self._close_watch_tasks(run)
            return
        # R9-002 (reviewer finding): while the approved repeat lane is still
        # owed, the node's CURRENT position belongs to the repeat attempt -
        # but the stage cursor is shared with the base lane, so a late
        # base-lane reconcile could satisfy the position check by coincidence
        # (single-run: seed None==None, index 0==0, and the repeat re-walks
        # the same stage indices) and then advance the REPEAT lane on base
        # evidence. Any non-repeat attempt absorbed in this window is
        # history, never the current head.
        lane_mismatch = bool(
            node is not None and run.get("kind") in ("stage", "eval")
            and not run.get("repeat_measure_attempt")
            and self._repeat_run_pending(node) is not None)
        # R10-001: a real external failure that ended BEFORE a job id existed
        # never flipped the node to executing/evaluating, so the status test
        # below filed it as unrelated history - no failure ledger entry, no
        # retry counter, no replacement-spend door, and the same position was
        # immediately re-prepared for free. A terminal failed/cancelled RUN
        # that is still the owner's CURRENT attempt routes through the
        # failure handlers regardless of launch timing. (A confirmed
        # never-launched cancel is excluded by the predicate: nothing was
        # spent and the intent settles through its own zero-usage channel.)
        current_failure = bool(
            node is not None and not lane_mismatch
            and run.get("status") in ("failed", "cancelled")
            and run.get("kind") in ("stage", "eval")
            and self._run_is_current_attempt(run, node))
        if node is None or lane_mismatch or (
                node.get("status") != expect and not recovering_same_run and not current_failure):
            if run.get("status") == "finished":
                errors = (self._run_result_errors(run, node, enforce_current=False) if node is not None
                          else [f"RUN_NODE_MISSING: cannot validate evidence for unknown node {run.get('node')}"])
                if errors:
                    self._record_run_evidence_errors(run, errors)
                    if run.get("adoption_status") == "candidate":
                        erun.transition_adoption(
                            run, "quarantined", note="node authority no longer expects this incomplete RUN")
                else:
                    self._seal_run_evidence(run, node, adopt=False)
            elif run.get("evidence_status") != "complete":
                erun.transition_evidence(run, "complete", note="typed terminal execution fact recorded")
            self._account_run(run)
            run["absorbed"] = True
            if run.get("adoption_status") == "candidate":
                erun.transition_adoption(
                    run, "quarantined",
                    note=f"node head no longer expects this attempt (status={(node or {}).get('status')})")
            self.store.event("engine", "late_run_quarantined", run=run["id"], node=run.get("node"),
                             node_status=(node or {}).get("status"), status=run.get("status"))
            self._close_watch_tasks(run)
            return
        if run.get("kind") == "eval":
            if run["status"] == "finished":
                result_errs = self._run_result_errors(run, node, enforce_current=True)
                if result_errs:
                    self._mark_run_evidence_pending(node, run, result_errs)
                elif run.get("repeat_measure_attempt"):
                    # R9-002: the bought-back repeat is a REAL eval RUN. It
                    # settles BESIDE the first measurement, never over it: the
                    # base eval_run pointer, the frozen floor, the resource
                    # receipt and the calibration inputs all stay untouched -
                    # the repeat contributes exactly one purchased second
                    # number, which the analysis aggregates once.
                    self._seal_run_evidence(run, node)
                    self._account_run(run)
                    run["absorbed"] = True
                    self._clear_run_evidence_pending(node, run)
                    rm = node.get("repeat_measure")
                    if isinstance(rm, dict):
                        rm["eval_run"] = run["id"]
                        rm["executed_at"] = eutil.utc_now()
                    node["repeat_eval_run"] = run["id"]
                    node.pop("repeat_pending_seed", None)
                    node["status"] = "workflow_done"
                    # R11-001: the second measurement is now sealed - publish
                    # the repeat workflow's deferred product generations in
                    # the SAME transaction, so registry head and adopted
                    # measurement move together.
                    self._flush_repeat_product_registrations(node)
                    egraph.touch(node)
                    self.store.event("engine", "repeat_eval_run_finished", node=node["id"],
                                     run=run["id"], seed=run.get("replica_seed"),
                                     metrics_file=run.get("metrics_file"))
                else:
                    self._seal_run_evidence(run, node)
                    self._account_run(run)
                    run["absorbed"] = True
                    self._clear_run_evidence_pending(node, run)
                    self._seal_resource_receipt(node, run)
                    node["status"] = "workflow_done"
                    node["eval_done"] = True
                    node["eval_run"] = run["id"]
                    node["eval_resource_accounted"] = True
                    # v11.1 P4 boundary: the repeat-measure trigger must judge
                    # with the floor as it stood BEFORE this evaluation - the
                    # measurement being judged may not move its own ruler - so
                    # freeze it before self-calibration ingests this seed set.
                    node["eval_floor_frozen"] = {
                        str(c.get("id") or ""): econfig.noise_floor(self.cfg, str(c.get("id") or ""), self.st)
                        for c in egraph.decision_cells(self.cfg)}
                    self._calibrate_observed_noise(node, run)
                    self._maybe_open_repeat_measure(node, run)
                    egraph.touch(node)
                    self.store.event("engine", "eval_run_finished", node=node["id"], run=run["id"],
                                     metrics_file=run.get("metrics_file"))
            else:
                erun.transition_evidence(run, "complete", note="typed external failure observation recorded")
                if run.get("adoption_status") == "candidate":
                    erun.transition_adoption(run, "quarantined", note="external evaluation did not finish")
                self._account_run(run)
                run["absorbed"] = True
                self._handle_eval_failure(node, run)
        elif run["status"] == "finished":
            spec = self._spec(node)
            stages = stages_of(spec)
            cur = int(node.get("stage_cursor") or 0)
            stage = stages[cur] if cur < len(stages) else {}
            metrics_path = eutil.rpath(self.store.repo, str(run.get("metrics_file") or ""))
            metrics = eutil.read_json(metrics_path, None) if metrics_path.is_file() else None
            result_errs = self._run_result_errors(run, node, enforce_current=True)
            if result_errs:
                self._mark_run_evidence_pending(node, run, result_errs)
            else:
                gate_decision = evalid.stage_gate_decision(stage, metrics)
                self._seal_run_evidence(run, node)
                self._account_run(run)
                run["absorbed"] = True
                self._clear_run_evidence_pending(node, run)
                self._advance_stage(node, run, gate_decision=gate_decision)
        else:  # failed workflow stage
            erun.transition_evidence(run, "complete", note="typed external failure observation recorded")
            if run.get("adoption_status") == "candidate":
                erun.transition_adoption(run, "quarantined", note="external stage did not finish")
            self._account_run(run)
            run["absorbed"] = True
            self._handle_stage_failure(node, run)
        self._close_watch_tasks(run)

    def _handle_eval_failure(self, node: dict, run: dict) -> None:
        """Route a typed failure without guessing that code was at fault."""
        self.store.add_error(self.st, {
            "node": node["id"], "stage": "eval", "run": run["id"],
            "failure_class": run.get("failure_class"),
            "note": run.get("note") or "evaluation run failed (no note recorded)",
        })
        fails = int(node.get("eval_failures", 0)) + 1
        node["eval_failures"] = fails
        failure_class = str(run.get("failure_class") or "unknown")
        repair_scope = (str(run.get("repair_scope") or "workflow")
                        if failure_class == "implementation" else None)
        node["repeat_attempt"] = {
            # The repair scope, not the broad failure class, determines which
            # already-paid evidence is invalidated.  The manual gate must name
            # exactly the external work that approval will release.
            "operation": (("eval" if repair_scope == "evaluation" else "workflow")
                          if failure_class == "implementation" else "eval"),
            "source_run": run["id"], "failure_class": failure_class,
            "repair_scope": repair_scope}
        if failure_class == "implementation":
            node["status"] = "building"
            node["fix_needed"] = True
            node["fix_note"] = f"evaluation run {run['id']} exposed an implementation failure: {run.get('note')}"
            node["implementation_repair_scope"] = repair_scope
            node["implementation_repair_source_run"] = run["id"]
        else:
            node["status"] = "workflow_done"   # retry only after a repeat-spend decision
        maxa = int(self.cfg.get("budgets", {}).get("max_attempts", 3))
        if fails >= maxa:
            # v11 R1: this node's TRAINING is already paid for - eval-failure
            # exhaustion is exactly the expensive-terminal situation the
            # protected-task list guards, and auto-abandoning here bypassed it.
            # The user decides; on_stuck=abandon no longer silently destroys a
            # trained node over evaluation plumbing.
            self.store.new_gate(
                self.st, "escalation",
                {"node": node["id"],
                 # R10-015: an exhaustion born from the repeat buy-back lane
                 # is retired together with the purchase when the user waives
                 **({"repeat_source_run": run["id"]}
                    if run.get("repeat_measure_attempt") else {})},
                f"Node {node['id']} background evaluation failed {fails} times "
                f"(run {run['id']}). Its TRAINING IS ALREADY PAID FOR - rejecting "
                "abandons the trained node and its sealed evidence. Approve to "
                "reset and retry the evaluation, reject to abandon."
                # (only advertised where the verb is currently accepted: an
                # implementation-class failure routes the node to building,
                # where waive correctly refuses until the fix lands)
                + (" (This exhaustion belongs to the APPROVED REPEAT buy-back lane; a third "
                   "exit exists: 'evo waive-repeat --node ... --note ...' keeps the paid "
                   "first measurement, releases the repeat and retires this decision.)"
                   if run.get("repeat_measure_attempt") and failure_class != "implementation"
                   else ""))
        egraph.touch(node)
        self.store.event("engine", "eval_run_failed", node=node["id"], run=run["id"], failures=fails,
                         failure_class=failure_class, repair_scope=repair_scope)

    def _close_watch_tasks(self, run: dict) -> None:
        """Any absorbed run changes the world: close ALL open watch tasks so the
        scheduler re-decides (a watch bound to run A must not block a fix pass
        for run B)."""
        for t in self.st["tasks"]:
            if t["type"] == "stage_watch" and t["status"] == "open":
                t["status"] = "done"
                t.pop("_render", None)
                t["updated_at"] = eutil.utc_now()
                watched_run = str((t.get("subject") or {}).get("run") or "")
                if watched_run == str(run.get("id") or ""):
                    self.store.event("engine", "watch_closed", task=t["id"], run=run["id"])
                else:
                    self.store.event("engine", "watch_superseded", task=t["id"],
                                     watched_run=watched_run, trigger_run=run.get("id"))

    def _advance_stage(self, node: dict, run: dict, *, gate_decision: Any = _GATE_UNCHECKED) -> None:
        spec = self._spec(node)
        stages = stages_of(spec)
        cur = int(node.get("stage_cursor") or 0)
        replica_index = int(node.get("replica_index") or 0)
        seeds = econfig.workflow_seeds(spec)
        repeat_lane = bool(run.get("repeat_measure_attempt"))
        replica_seed = (run.get("replica_seed") if repeat_lane
                        else econfig.workflow_seed(spec, replica_index))
        stage = stages[cur] if cur < len(stages) else None
        if stage is not None:
            if gate_decision is _GATE_UNCHECKED:
                metrics = eutil.read_json(eutil.rpath(self.store.repo, run.get("metrics_file") or ""), {}) or {}
                decision = evalid.stage_gate_decision(stage, metrics)
            else:
                decision = gate_decision
            if decision is not None:
                run["scientific_outcome"] = decision["outcome"]
                run["scientific_gate"] = decision
                if decision["outcome"] == "stop_node":
                    if repeat_lane:
                        # R10-013: a continuation gate is a spend-control rule
                        # for this node's pipeline, and the base pass already
                        # decided it. The user bought EXACTLY ONE full
                        # workflow+eval as a second measurement - letting a
                        # seed-sensitive stop line silently convert that
                        # purchase into a node conclusion swallowed the
                        # approved measurement and left its obligation
                        # dangling past conclude/close/DONE. Record the
                        # observation verbatim (the doctor's drift audit
                        # compares it); the lane runs to completion and the
                        # aggregate settles once.
                        self.store.event("engine", "repeat_stage_gate_observed",
                                         node=node["id"], run=run["id"],
                                         stage=(stage or {}).get("name"),
                                         outcome=decision["outcome"],
                                         gate=(decision or {}).get("id"))
                    else:
                        self._apply_scientific_stop(node, run, stage, decision)
                        return
        if stage is not None:
            self._register_or_defer_stage_products(node, stage, cur, replica_seed, run)
        node["stage_cursor"] = cur + 1
        if node["stage_cursor"] >= len(stages):
            if replica_seed is not None:
                completion = {"seed": replica_seed, "run": run["id"],
                              "completed_at": eutil.utc_now()}
                if repeat_lane:
                    completion["repeat_measure"] = True
                node.setdefault("replicas_completed", []).append(completion)
            if repeat_lane:
                # R9-002: the repeat lane finishes exactly once - it must
                # never re-enter the preplanned seed loop below (its seed is
                # not one of the spec lanes). The node returns to
                # workflow_done, where the scheduler prepares the repeat
                # evaluation next.
                node["status"] = "workflow_done"
                self.store.event("engine", "repeat_workflow_finished", node=node["id"],
                                 run=run["id"], seed=replica_seed)
            elif seeds and replica_index + 1 < len(seeds):
                node["replica_index"] = replica_index + 1
                node["stage_cursor"] = 0
                node["status"] = "stage_ready"
                self.store.event("engine", "workflow_replica_finished", node=node["id"], run=run["id"],
                                 seed=replica_seed, replica_index=replica_index,
                                 next_seed=seeds[replica_index + 1])
            else:
                node["status"] = "workflow_done"
                self.store.event("engine", "workflow_finished", node=node["id"], run=run["id"],
                                 stage=(stage or {}).get("name"), replicas=len(seeds) if seeds else 1)
        else:
            node["status"] = "stage_ready"
            self.store.event("engine", "stage_finished", node=node["id"], run=run["id"],
                             stage=(stage or {}).get("name"),
                             next_stage=stages[node["stage_cursor"]].get("name"), seed=replica_seed,
                             replica_index=replica_index)
        egraph.touch(node)

    def _calibrate_observed_noise(self, node: dict, run: dict) -> None:
        """v11.1 P3: self-calibrated noise floors, preplanned mode only.

        A completed preplanned seed set is a direct measurement of THIS
        project's run-to-run spread on THIS harness, which beats any
        literature guess. Per decision cell with >= 2 seed values we record
        the set's max-min width (conservative) plus its stdev, keep a short
        rolling history, and publish the MEDIAN width to engine STATE
        (st.observed_noise) - never to the frozen evaluation contract.
        econfig.noise_floor() prefers this value once >= 2 sets exist.
        Single-run mode never reaches here, so it keeps literature floors.
        """
        spec = self._spec(node)
        if ((spec.get("training_replication") or {}).get("mode")) != "preplanned":
            return
        metrics = eutil.read_json(eutil.rpath(self.store.repo, run.get("metrics_file") or ""), {}) or {}
        for cell in egraph.decision_cells(self.cfg):
            raw = metrics.get(str(cell.get("result_key") or ""))
            block = raw.get("training_replication") if isinstance(raw, dict) else None
            vals: list[float] = []
            for r in (block.get("runs") or []) if isinstance(block, dict) else []:
                v = (r or {}).get("value")
                if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)):
                    vals.append(float(v))
            if len(vals) < 2:
                continue
            cid = str(cell.get("id") or "")
            rec = self.st.setdefault("observed_noise", {}).setdefault(
                cid, {"runs": {}, "sets": 0})
            # (final audit C30 + R7) contributions are keyed by the TRAINING
            # SET's identity (node + its seed set), not the eval RUN id: a
            # crash replay reuses the same RUN and overwrote itself already,
            # but an evaluation-only recovery mints a NEW eval RUN over the
            # SAME trained seeds - keying on the RUN id counted that single
            # spread twice (the known-broken first evaluation kept voting and
            # prematurely flipped the floor source to 'observed'). Same
            # training set -> same key -> replace; only the newest 8 vote.
            runs = rec.setdefault("runs", {})
            # pop-then-insert: a replacement must re-enter as the NEWEST
            # entry, or the next contribution would evict it instead of the
            # oldest one and the "newest 8 vote" claim above would be off by one
            seed_tokens = sorted(
                str(evalid._seed_token(r.get("seed")))
                for r in ((block.get("runs") or []) if isinstance(block, dict) else [])
                if isinstance(r, dict))
            run_key = f"{node.get('id')}|{'/'.join(seed_tokens)}"
            runs.pop(run_key, None)
            runs[run_key] = [max(vals) - min(vals), statistics.pstdev(vals)]
            for stale_key in list(runs)[:-8]:
                del runs[stale_key]
            rec["widths"] = [v[0] for v in runs.values()]
            rec["stdevs"] = [v[1] for v in runs.values()]
            rec["sets"] = len(runs)
            rec["width"] = float(statistics.median(rec["widths"]))
            rec["updated_at"] = eutil.utc_now()
            self.store.event("engine", "observed_noise_updated", node=node["id"], cell=cid,
                             width=rec["width"], sets=rec["sets"])

    def _maybe_open_repeat_measure(self, node: dict, run: dict) -> None:
        """v11.1 P4 trigger. Fires at most once per node, purely mechanically:
        the node pre-registered a repeat_rule, the project is single-run, and
        the SINGLE measured delta lands within the registered band (explicit
        band first, else the floor FROZEN BEFORE this evaluation - the
        measurement may not move its own ruler) of a decision line
        (0 / min_improvement / -noninferiority_margin / goal_threshold).
        The offer is a protected user gate; the aggregate of an approved
        repeat can never re-trigger (repeat_measure/_done guards)."""
        if node.get("repeat_measure") or node.get("repeat_measure_done"):
            return
        spec = self._spec(node)
        if ((spec.get("training_replication") or {}).get("mode")) == "preplanned":
            return
        for gate in self.st.get("gates", []):
            if gate.get("kind") == "repeat_measure" \
                    and (gate.get("subject") or {}).get("node") == node["id"] \
                    and gate.get("status") in {"open", "paused", "approved", "rejected"} \
                    and not gate.get("superseded_by_restart"):
                # R7 follow-up: a gate stamped superseded_by_restart belongs to
                # a PREVIOUS implementation revision (its settled repeat was
                # archived by the restart) - it must not dedup the fresh
                # revision's own near-the-line judgement.
                return
        meta = {}
        if node.get("idea_doc"):
            meta = eutil.read_json(eutil.rpath(
                self.store.repo, str(node["idea_doc"]).replace(".md", ".meta.json")), {}) or {}
        rr = meta.get("repeat_rule")
        if not isinstance(rr, dict):
            return
        rule_errs = evalid.repeat_rule_errors(self.cfg, meta, st=self.st)
        if rule_errs:
            # v11.1 (R2 fix): the trigger honors only rules that pass the SAME
            # registration validator the mature door applies - a rule smuggled
            # into a meta no validator saw (or malformed) can never open the
            # protected gate under a false "pre-registered" banner.
            self.store.event("engine", "repeat_rule_invalid_ignored", node=node["id"],
                             errors=rule_errs[:3])
            return
        cid = str(rr.get("cell") or "")
        cell = next((c for c in egraph.decision_cells(self.cfg) if str(c.get("id") or "") == cid), None)
        if cell is None:
            return
        band = rr.get("band")
        band_source = "registered band"
        if isinstance(band, bool) or not isinstance(band, (int, float)):
            band = (node.get("eval_floor_frozen") or {}).get(cid)
            band_source = "noise floor frozen before this evaluation"
        if isinstance(band, bool) or not isinstance(band, (int, float)) or float(band) <= 0:
            return
        band = float(band)
        key = str(cell.get("result_key") or "")
        metrics = eutil.read_json(eutil.rpath(self.store.repo, run.get("metrics_file") or ""), {}) or {}
        value = econfig.result_value(metrics.get(key))
        if value is None:
            return
        value = float(value)
        idx = egraph.by_id(self.g)
        # v11.1 (R1 fix): judge the delta against the FROZEN effect comparator
        # (the quantity the verdict will actually settle on), not blindly the
        # first parent - the two may legally differ (declared baseline
        # comparator, hybrid parents). Boundary (2) is about the decision.
        declared = str(((meta.get("effect_case") or {}).get("comparator_id")) or "")
        if declared == "baseline":
            comp = egraph.origin_node(self.g)
        elif declared:
            comp = idx.get(declared)
        else:
            comp = next((idx[p] for p in node.get("parents", [])
                         if p in idx and idx[p].get("role") != "platform"), None) \
                or egraph.origin_node(self.g)
        comp_value = econfig.result_value(egraph.cell_raw(comp, key)) if comp else None
        direction = econfig.result_direction(self.cfg, key)
        hits: list[str] = []
        delta = None
        if comp_value is not None:
            delta = (value - float(comp_value)) if direction == "max" else (float(comp_value) - value)
            if abs(delta - 0.0) <= band:
                hits.append("0 (parity with the comparator)")
            margin = float(cell.get("min_improvement") or 0.0)
            if margin > 0 and abs(delta - margin) <= band:
                hits.append(f"min_improvement {margin:g}")
            noninf = float(cell.get("noninferiority_margin") or 0.0)
            if noninf > 0 and abs(delta + noninf) <= band:
                hits.append(f"noninferiority -{noninf:g}")
        gt = cell.get("goal_threshold")
        if isinstance(gt, (int, float)) and not isinstance(gt, bool) and abs(value - float(gt)) <= band:
            hits.append(f"goal_threshold {float(gt):g}")
        # R4 science audit: when a floor is active, the verdict's EFFECTIVE
        # flip lines sit floor-shifted from the registered ones (improved at
        # improve+floor, regressed at -max(margin,floor), goal at gt+/-floor).
        # A registered band narrower than the floor would patrol lines the
        # floored verdict never flips on and miss the ones it does - so ALSO
        # check the effective lines. floor==0 leaves behavior identical.
        eff_floor = (node.get("eval_floor_frozen") or {}).get(cid)
        eff_floor = float(eff_floor) if isinstance(eff_floor, (int, float)) \
            and not isinstance(eff_floor, bool) else 0.0
        if eff_floor > 0:
            if delta is not None:
                margin = float(cell.get("min_improvement") or 0.0)
                t_imp = (margin if margin > 0 else 0.0) + eff_floor
                if abs(delta - t_imp) <= band:
                    hits.append(f"improvement decision line {t_imp:g} (floor-adjusted)")
                noninf = float(cell.get("noninferiority_margin") or 0.0)
                t_reg = -max(noninf, eff_floor)
                if abs(delta - t_reg) <= band:
                    hits.append(f"regression decision line {t_reg:g} (floor-adjusted)")
            if isinstance(gt, (int, float)) and not isinstance(gt, bool):
                if abs(value - (float(gt) + eff_floor)) <= band or \
                        abs(value - (float(gt) - eff_floor)) <= band:
                    hits.append(f"goal decision line {float(gt):g}+/-{eff_floor:g} (floor-adjusted)")
        if not hits:
            return
        seeds = econfig.workflow_seeds(spec)
        base_seed = seeds[0] if seeds else "base"
        if isinstance(base_seed, int) and not isinstance(base_seed, bool):
            repeat_seed: Any = base_seed + 1
            # same duplicate rule as the string branch (reviewer hardening):
            # a spec carrying extra workflow seeds must not receive a
            # "fresh" seed that names one of its existing lanes
            taken_int: set[str] = set()
            for s in seeds:
                try:
                    taken_int.add(econfig.seed_slug(s))
                except ValueError:
                    continue
            while econfig.seed_slug(repeat_seed) in taken_int:
                repeat_seed += 1
        else:
            # R7: the constant "repeat" collided with a project whose seed IS
            # the string "repeat" - the gate then promised a "fresh seed" that
            # the replication validator would reject as a duplicate.
            taken = {econfig.seed_slug(s) for s in seeds}
            repeat_seed = "repeat"
            n = 2
            while econfig.seed_slug(repeat_seed) in taken:
                repeat_seed = f"repeat{n}"
                n += 1
        delta_txt = f"{delta:g}" if delta is not None else "n/a (no comparator value)"
        self.store.new_gate(
            self.st, "repeat_measure",
            {"node": node["id"], "cell": cid, "result_key": key, "band": band,
             "band_source": band_source, "value": value, "delta": delta,
             "comparator": (comp or {}).get("id"), "lines": hits,
             "base_seed": base_seed, "seed": repeat_seed},
            f"Node {node['id']} measured {key}={value:g} (delta vs {(comp or {}).get('id') or 'none'}: "
            f"{delta_txt}); that lands within the band {band:g} ({band_source}) of decision "
            f"line(s): {'; '.join(hits)}. The pre-registered repeat_rule offers to buy back EXACTLY ONE "
            f"repeat of the full training+eval with a fresh seed ({repeat_seed!r}); both runs are then "
            "reported as a 2-run set on that metric and the verdict settles ONCE on their mean - the "
            "aggregate can never trigger another repeat. On approval the ENGINE schedules the repeat "
            "as first-class RUNs (R9-002): every stage and the evaluation get their own prepared "
            "attempt with token, scheduler slot, landing lease and resource-ledger charge. The repeat "
            "executes the frozen commands at the spec's OWN landings (R10-012: one resolution rule "
            "for every attempt): the first attempt's leftover LOCAL bytes at those landings are "
            "archived per-RUN before the repeat writes (its sealed evidence lives in immutable "
            "snapshots either way), shared product rows advance to a new registry generation with "
            "the earlier custody kept in history, and a REMOTE product URI, if the spec declares "
            "one, WILL be overwritten by the frozen command - consume the first attempt's remote "
            "bytes before approving if you need them. The resource doors still apply, so an "
            "underfunded repeat waits at a resource gate instead of launching. Reject to keep the "
            "single-run verdict exactly as measured (recorded either way).")
        self.store.event("engine", "repeat_measure_triggered", node=node["id"], run=run["id"],
                         cell=cid, band=band, delta=delta, lines=hits)

    def _apply_scientific_stop(self, node: dict, run: dict, stage: dict, decision: dict) -> None:
        """Terminate remaining work without pretending the execution failed."""
        reason = (f"pre-registered continuation gate {decision.get('id')!r} missed at "
                  f"stage {stage.get('name')!r}")
        node["scientific_stop"] = {
            "run": run["id"], "stage": stage.get("name"), "gate": decision,
            "metrics_file": run.get("metrics_file"), "reason": reason,
            "stopped_at": eutil.utc_now(),
        }
        node["status"] = "scientific_stop"
        egraph.touch(node)
        self.store.event("engine", "stage_scientific_stop", node=node["id"], run=run["id"],
                         stage=stage.get("name"), gate=decision.get("id"),
                         predicates=decision.get("predicates"))

    def _register_or_defer_stage_products(self, node: dict, stage: dict, stage_index: int,
                                          replica_seed: Any | None, run: dict) -> None:
        """R11-001: a repeat lane's product registrations are DEFERRED.

        While the repeat executes, the registry head keeps the BASE
        measurement's generation - a consumer that binds mid-repeat binds
        settled bytes, and the launch-time live-digest audit refuses the
        landing while it temporarily holds repeat bytes. The rows ride inside
        repeat_measure and are flushed in the same transaction that seals the
        repeat evaluation; a waive (or a recovery that archives the approval)
        discards them, so the head never moves for a measurement that never
        finished."""
        rm = node.get("repeat_measure")
        if run.get("repeat_measure_attempt") and isinstance(rm, dict) \
                and not node.get("repeat_measure_done"):
            rows = rm.setdefault("pending_product_registrations", [])
            if not any(r.get("run") == run["id"] and r.get("stage_index") == stage_index
                       for r in rows):
                rows.append({"stage_index": stage_index, "run": run["id"], "seed": replica_seed})
                self.store.event("engine", "repeat_product_registration_deferred",
                                 node=node["id"], run=run["id"], stage_index=stage_index,
                                 stage=(stage or {}).get("name"))
            return
        self._register_stage_artifacts(node, stage, replica_seed, run)

    def _flush_repeat_product_registrations(self, node: dict) -> None:
        """Flush the repeat lane's deferred product registrations (R11-001).

        Called in the same absorption that seals the repeat evaluation, and
        as an idempotent belt when the 2-run aggregate settles - registration
        no-ops on rows that already exist."""
        rm = node.get("repeat_measure")
        if not isinstance(rm, dict):
            return
        rows = rm.pop("pending_product_registrations", None) or []
        if not rows:
            return
        spec = self._spec(node)
        stages = stages_of(spec)
        flushed = 0
        for row in rows:
            sidx = row.get("stage_index")
            run = self.store.get_run(self.st, str(row.get("run") or ""))
            if run is None or not isinstance(sidx, int) or isinstance(sidx, bool) \
                    or not (0 <= sidx < len(stages)):
                self.store.event("engine", "repeat_product_registration_dropped",
                                 node=node["id"], row=dict(row),
                                 reason="run or stage no longer resolvable")
                continue
            self._register_stage_artifacts(node, stages[sidx], row.get("seed"), run)
            flushed += 1
        self.store.event("engine", "repeat_product_registrations_flushed",
                         node=node["id"], count=flushed)

    def _register_stage_artifacts(self, node: dict, stage: dict, replica_seed: Any | None,
                                  run: dict) -> None:
        for p in stage.get("produces") or []:
            uri = str(econfig.resolve_seed_template(p.get("uri") or "", replica_seed)) \
                if replica_seed is not None else str(p.get("uri") or "")
            if not uri:
                continue
            existing = eartifact.find_by_uri(self.reg, uri)
            # R9 (external audit r6): 'invalid' (a local product missing at first
            # registration) is the SAME node's own row and must be repairable by
            # its own producer's later, now-present bytes - not frozen forever in
            # the conflict-event branch. record_generation re-runs content_custody
            # and flips status to available when the bytes now exist.
            # R10 self-audit (major): the SAME node re-producing its own
            # 'available' row is a legitimate NEW GENERATION too - a repeat
            # buy-back lane (and a later preplanned replica) writes the same
            # fixed URI with fresh bytes, and the conflict-event branch left
            # the registry digest pointing at the PREVIOUS attempt's bytes
            # forever: every frozen consumer binding then failed its bytes
            # audit with no repair verb, and revive could never re-prove the
            # row. Generation history preserves the earlier custody; only a
            # CROSS-node collision remains a conflict event.
            if existing is not None and existing.get("node") == node["id"] \
                    and existing.get("status") in ("stale", "invalid", "available"):
                # R11 (W6 self-audit): a generation is minted by exactly one
                # producing RUN. The estore commit order (graph, registry,
                # state) leaves a window where the registry already carries
                # this run's generation but the state lost the absorbed flag -
                # the crash replay then re-entered here and record_generation
                # minted a FRESH generation for the SAME bytes, silently
                # "drifting" every consumer binding frozen on the committed
                # one. Same run + same live bytes = the write already
                # happened; converge, don't inflate. (Different bytes under
                # the same run - late reconcile materials - still record.)
                if str(existing.get("producer_run") or "") == str(run.get("id") or ""):
                    live, checkable = eartifact.content_custody(self.store, uri)
                    if not checkable or live == str(existing.get("content_digest") or ""):
                        continue
                eartifact.record_generation(
                    self.store, existing, producer_run=run,
                    producer_implementation_digest=str(
                        (node.get("implementation_seal") or {}).get("digest") or ""),
                    producer_evidence_digest=str((run.get("evidence_seal") or {}).get("digest") or ""),
                    stage=str(stage.get("name") or "stage"),
                    stage_key=(str(econfig.resolve_seed_template(stage.get("stage_key"), replica_seed))
                               if replica_seed is not None and stage.get("stage_key") is not None
                               else stage.get("stage_key")),
                    reason=("repeat buy-back lane re-produced this node's product"
                            if run.get("repeat_measure_attempt") else
                            "the producing node wrote a new generation of its own product"))
                continue
            if existing is not None:
                self.store.event("engine", "artifact_uri_conflict_at_register", node=node["id"],
                                 stage=stage.get("name"), uri=uri)
                continue
            eartifact.register(self.store, self.st, self.reg, node=node["id"],
                               stage=str(stage.get("name") or "stage"),
                               stage_key=(str(econfig.resolve_seed_template(stage.get("stage_key"), replica_seed))
                                          if replica_seed is not None and stage.get("stage_key") is not None
                                          else stage.get("stage_key")),
                               name=(str(p.get("name") or uri) +
                                     (f" [seed={replica_seed}]" if replica_seed is not None else "")),
                               kind=str(p.get("kind") or "other"), uri=uri,
                               producer_run=run,
                               producer_implementation_digest=str(
                                   (node.get("implementation_seal") or {}).get("digest") or ""),
                               producer_evidence_digest=str(
                                   (run.get("evidence_seal") or {}).get("digest") or ""))

    def _handle_stage_failure(self, node: dict, run: dict) -> None:
        self.store.add_error(self.st, {
            "node": node["id"], "stage": run.get("stage"), "run": run["id"],
            "seed": run.get("replica_seed"),
            "failure_class": run.get("failure_class"),
            "note": run.get("note") or "workflow stage failed (no note recorded)",
        })
        fails = int(node.get("stage_failures", 0)) + 1
        node["stage_failures"] = fails
        failure_class = str(run.get("failure_class") or "unknown")
        repair_scope = "workflow" if failure_class == "implementation" else None
        node["repeat_attempt"] = {
            # An implementation repair resets the complete workflow.  Calling
            # this a one-stage approval would understate the spend that follows.
            "operation": ("workflow" if failure_class == "implementation" else "stage"),
            "stage": run.get("stage"),
            "source_run": run["id"], "failure_class": failure_class,
            "repair_scope": repair_scope,
        }
        if failure_class == "implementation":
            node["implementation_repair_scope"] = "workflow"
            node["implementation_repair_source_run"] = run["id"]
        maxa = int(self.cfg.get("budgets", {}).get("max_attempts", 3))
        if fails >= maxa:
            # R2 audit: stage exhaustion was the ONE exhaustion door that
            # auto-abandoned a training-paid node (multi-seed: earlier seeds
            # fully trained, last seed's stage failing). Every sibling path
            # (eval exhaustion, stuck tasks, fix cycles, full_auto escalation
            # auto-reject) consults _node_training_paid - so does this now.
            if self.cfg.get("policy", {}).get("on_stuck") == "abandon" \
                    and not self._node_training_paid(node):
                self._abandon_node(node, f"workflow stage failed {fails} times")
            else:
                paid_note = (" Its TRAINING IS ALREADY PAID FOR - rejecting abandons the trained "
                             "seeds and their sealed evidence." if self._node_training_paid(node) else "")
                self.store.new_gate(
                    self.st, "escalation",
                    {"node": node["id"],
                     **({"repeat_source_run": run["id"]}
                        if run.get("repeat_measure_attempt") else {})},
                    f"Node {node['id']} workflow stage failed {fails} times (run {run['id']}, "
                    f"stage {run.get('stage')}).{paid_note} Approve to reset and retry, "
                    "reject to abandon."
                    + (" (This exhaustion belongs to the APPROVED REPEAT buy-back lane; a third "
                       "exit exists: 'evo waive-repeat --node ... --note ...' keeps the paid "
                       "first measurement, releases the repeat and retires this decision.)"
                       if run.get("repeat_measure_attempt") and failure_class != "implementation"
                       else ""))
                node["status"] = "building" if failure_class == "implementation" else "stage_ready"
                node["fix_needed"] = failure_class == "implementation"
                node["fix_note"] = (f"workflow stage failed {fails} times; escalated"
                                    if failure_class == "implementation" else None)
        else:
            if failure_class == "implementation":
                node["status"] = "building"
                node["fix_needed"] = True
                node["fix_note"] = (f"workflow run {run['id']} (stage {run.get('stage')}) "
                                    f"failed in implementation: {run.get('note') or 'see logs'}")
            else:
                node["status"] = "stage_ready"
                node["fix_needed"] = False
                node["fix_note"] = None
        egraph.touch(node)
        self.store.event("engine", "stage_failed", node=node["id"], run=run["id"],
                         stage=run.get("stage"), seed=run.get("replica_seed"), failures=fails,
                         failure_class=failure_class, repair_scope=repair_scope)

    def _archive_repeat_measure(self, node: dict, reason: str) -> None:
        """R7 external audit: a settled repeat_measure is evidence of the OLD
        implementation revision. Leaving it across a restart forced the new
        evaluation to report "BOTH runs" with an old-revision repeat against a
        new-revision base (exactly the mixing these restarts forbid), while
        waive-repeat refused because done=True. Archive it; the fresh eval
        re-judges near-the-line and reopens its own gate if warranted."""
        if not (node.get("repeat_measure") or node.get("repeat_measure_done")):
            return
        node.setdefault("repeat_measure_history", []).append(json.loads(json.dumps(
            {"repeat_measure": node.get("repeat_measure"),
             "done": bool(node.get("repeat_measure_done")),
             "pending_seed": node.get("repeat_pending_seed"),
             "repeat_eval_run": node.get("repeat_eval_run"),
             "superseded_reason": reason})))
        node.pop("repeat_measure", None)
        node.pop("repeat_measure_done", None)
        # R9-002: the engine-run repeat execution state belongs to the archived
        # approval - a restart must not leave the scheduler owing a repeat
        # lane for a revision that no longer exists.
        node.pop("repeat_pending_seed", None)
        node.pop("repeat_eval_run", None)
        # The old revision's DECIDED gate must stop deduplicating the fresh
        # revision's near-the-line judgement (_maybe_open_repeat_measure skips
        # stamped gates), or the re-judgement this archive promises never
        # happens and a genuinely ambiguous new measurement settles silently.
        for gate in self.st.get("gates", []):
            if gate.get("kind") == "repeat_measure" \
                    and (gate.get("subject") or {}).get("node") == node.get("id") \
                    and gate.get("status") in {"approved", "rejected"} \
                    and not gate.get("superseded_by_restart"):
                gate["superseded_by_restart"] = reason

    def _restart_workflow_after_fix(self, node: dict) -> None:
        """Never mix stage/eval evidence produced by different code revisions."""
        prior = [r for r in self.st.get("runs", [])
                 if r.get("node") == node.get("id") and r.get("kind") in ("stage", "eval")
                 and r.get("adoption_status") != "superseded"]
        unresolved = [r.get("id") for r in prior if not erun.is_terminal(r)]
        if unresolved:
            raise SystemExit("[evo] implementation authority cannot change while external RUNs are unresolved: "
                             + ", ".join(str(x) for x in unresolved))
        for run in prior:
            self._archive_seal(run, "evidence_seal")
            # Evidence seals already point at immutable per-RUN snapshots.
            # Superseding authority must never move/delete those bytes; doing
            # so would make append-only history unverifiable.  Producer landing
            # paths may be reused independently and are not the sealed copy.
            if run.get("adoption_status") != "superseded":
                erun.transition_adoption(run, "superseded",
                                         note="implementation revision changed")
            run["superseded"] = True
            run["superseded_reason"] = "implementation revision changed"
        eartifact.invalidate_for_node(
            self.store, self.reg, str(node.get("id")),
            "workflow restarted after implementation revision")
        self._archive_seal(node, "eval_seal")
        self._archive_seal(node, "conclusion_seal")
        self._archive_seal(node, "resource_receipt_seal")
        self._archive_seal(node, "workflow_reuse_seal")
        node["eval_seal"] = None
        node["conclusion_seal"] = None
        node["resource_receipt_seal"] = None
        node["resource_receipt_path"] = None
        node["resource_receipt_ready"] = False
        node.pop("workflow_reuse_receipt_path", None)
        node["evidence_heads"] = {}
        node.pop("eval_run", None)
        node.pop("probe_evidence_status", None)
        node.pop("evidence_pending_run", None)
        self._archive_repeat_measure(node, "implementation revision changed")
        if node.get("scientific_stop"):
            node.setdefault("scientific_stop_history", []).append(
                json.loads(json.dumps(node["scientific_stop"])))
            node.pop("scientific_stop", None)
        for field in ("scores", "score_evidence", "evaluation_summary",
                      "effect_resources_realized", "effect_contract_status",
                      "scientific_promotion_status", "mechanism_status",
                      "maintenance_parity", "maintenance_gain", "verdict"):
            node.pop(field, None)
        node["eval_done"] = False
        node["eval_resource_accounted"] = False
        node["stage_cursor"] = 0
        node["replica_index"] = 0
        node["replicas_completed"] = []
        self.store.event("engine", "workflow_restarted_for_implementation", node=node.get("id"),
                         superseded_runs=[r.get("id") for r in prior])

    def _restart_evaluation_after_fix(self, node: dict) -> None:
        """Invalidate only evaluation authority while preserving completed workflow evidence."""
        prior_eval = [r for r in self.st.get("runs", [])
                      if r.get("node") == node.get("id") and r.get("kind") == "eval"
                      and r.get("adoption_status") != "superseded"]
        unresolved = [r.get("id") for r in self.st.get("runs", [])
                      if r.get("node") == node.get("id") and not erun.is_terminal(r)]
        if unresolved:
            raise SystemExit("[evo] evaluation implementation authority cannot change while external RUNs "
                             "are unresolved: " + ", ".join(str(x) for x in unresolved))
        for run in prior_eval:
            if run.get("adoption_status") == "adopted":
                self._archive_seal(run, "evidence_seal")
                erun.transition_adoption(run, "superseded",
                                         note="evaluation implementation revision changed")
                run["superseded"] = True
                run["superseded_reason"] = "evaluation implementation revision changed"
        self._archive_seal(node, "eval_seal")
        self._archive_seal(node, "conclusion_seal")
        self._archive_seal(node, "resource_receipt_seal")
        node["eval_seal"] = None
        node["conclusion_seal"] = None
        node["resource_receipt_seal"] = None
        node["resource_receipt_path"] = None
        node["resource_receipt_ready"] = False
        node["evidence_heads"] = {
            key: value for key, value in (node.get("evidence_heads") or {}).items()
            if key not in ("eval", "repeat_eval")
        }
        for field in ("eval_run", "evidence_pending_run"):
            node.pop(field, None)
        probe = self._spec(node).get("probe_execution") or {}
        if str(probe.get("producer_stage") or "") == "evaluation":
            node.pop("probe_evidence_status", None)
        self._archive_repeat_measure(node, "evaluation implementation revision changed")
        if node.get("scientific_stop"):
            node.setdefault("scientific_stop_history", []).append(
                json.loads(json.dumps(node["scientific_stop"])))
            node.pop("scientific_stop", None)
        for field in ("scores", "score_evidence", "evaluation_summary",
                      "effect_resources_realized", "effect_contract_status",
                      "scientific_promotion_status", "mechanism_status",
                      "maintenance_parity", "maintenance_gain", "verdict"):
            node.pop(field, None)
        node["eval_done"] = False
        node["eval_resource_accounted"] = False
        self.store.event(
            "engine", "evaluation_restarted_for_implementation", node=node.get("id"),
            preserved_stage_runs=[r.get("id") for r in self.st.get("runs", [])
                                  if r.get("node") == node.get("id") and r.get("kind") == "stage"
                                  and r.get("adoption_status") == "adopted"],
            superseded_eval_runs=[r.get("id") for r in prior_eval
                                  if r.get("adoption_status") == "superseded"])

    def _prepare_evaluation_repair_baseline(self, node: dict, reason: str) -> None:
        manifest_rel = str(node.get("implementation_manifest") or "")
        manifest = eutil.read_json(eutil.rpath(self.store.repo, manifest_rel), None)
        if not isinstance(manifest, dict):
            raise SystemExit("[evo] evaluation-only implementation repair needs the active implementation manifest")
        stages = stages_of(self._spec(node))
        expected = len(stages) * econfig.workflow_replica_count(self._spec(node))
        stage_runs = [r for r in self.st.get("runs", [])
                      if r.get("node") == node.get("id") and r.get("kind") == "stage"
                      and r.get("adoption_status") == "adopted" and r.get("status") == "finished"
                      and r.get("evidence_status") == "complete"
                      # R9-002: the repeat lane is an extra purchased attempt,
                      # not part of the preplanned workflow head this count
                      # proves complete
                      and not r.get("repeat_measure_attempt")]
        if expected and len(stage_runs) != expected:
            raise SystemExit("[evo] evaluation-only repair cannot prove a complete workflow head; "
                             "use repair scope workflow")
        revision = int(node.get("implementation_revision") or 0) + 1
        rel = f".evo/nodes/{node.get('id')}/repairs/IMPLEMENTATION_BASELINE_r{revision}.json"
        baseline = {
            "schema_version": 1, "node": node.get("id"), "repair_scope": "evaluation",
            "reason": str(reason), "source_run": node.get("implementation_repair_source_run"),
            "prior_implementation_digest": str((node.get("implementation_seal") or {}).get("digest") or ""),
            "manifest": manifest,
            "workflow_protected_paths": evalid.workflow_protected_implementation_paths(self.ctx(), node),
            "preserved_stage_runs": [r.get("id") for r in stage_runs],
            "created_at": eutil.utc_now(),
        }
        eutil.write_json_atomic(eutil.rpath(self.store.repo, rel), baseline)
        node["implementation_revision_baseline_path"] = rel
        node["implementation_revision_baseline_digest"] = eseal.artifact_digest(self.store.repo, rel)

    def _seal_workflow_reuse(self, node: dict, report_rel: str) -> None:
        """Authorize old stage evidence under a new evaluator implementation.

        The receipt does not rewrite old RUN provenance.  It records the exact
        old upstream digests that remain active solely for the preserved stage
        heads, while the replacement eval binds the new implementation digest.
        """
        baseline_rel = str(node.get("implementation_revision_baseline_path") or "")
        baseline = eutil.read_json(eutil.rpath(self.store.repo, baseline_rel), None)
        if not isinstance(baseline, dict):
            raise SystemExit("[evo] evaluation-only repair lost its frozen implementation baseline")
        changes, change_errs = evalid.implementation_manifest_changes(self.ctx(), node)
        if change_errs:
            raise SystemExit("[evo] cannot seal workflow reuse:\n  - " + "\n  - ".join(change_errs))
        run_ids = [str(x) for x in (baseline.get("preserved_stage_runs") or []) if str(x)]
        rows: list[dict] = []
        upstreams = {str(baseline.get("prior_implementation_digest") or "")}
        for rid in run_ids:
            run = self.store.get_run(self.st, rid) or {}
            if run.get("kind") != "stage" or run.get("adoption_status") != "adopted" \
                    or run.get("status") != "finished" or run.get("evidence_status") != "complete":
                raise SystemExit(f"[evo] evaluation-only repair cannot preserve inactive workflow RUN {rid}")
            upstreams.update(str(x) for x in (run.get("authority_upstreams") or []) if str(x))
            rows.append({
                "run": rid, "stage": run.get("stage"), "seed": run.get("replica_seed"),
                "implementation_digest": str(run.get("implementation_digest") or ""),
                "evidence_digest": str((run.get("evidence_seal") or {}).get("digest") or ""),
            })
        revision = int(node.get("workflow_reuse_revision") or 0) + 1
        rel = f".evo/nodes/{node.get('id')}/repairs/WORKFLOW_REUSE_r{revision}.json"
        receipt = {
            "schema_version": 1, "node": node.get("id"), "repair_scope": "evaluation",
            "source_run": node.get("implementation_repair_source_run"),
            "baseline_path": baseline_rel,
            "baseline_digest": node.get("implementation_revision_baseline_digest"),
            "prior_implementation_digest": baseline.get("prior_implementation_digest"),
            "current_implementation_digest": str((node.get("implementation_seal") or {}).get("digest") or ""),
            "changed_files": changes, "build_report": report_rel,
            "preserved_stage_runs": rows,
            "preserved_upstream_digests": sorted(x for x in upstreams if x),
            "created_at": eutil.utc_now(),
        }
        eutil.write_json_atomic(eutil.rpath(self.store.repo, rel), receipt)
        self._archive_seal(node, "workflow_reuse_seal")
        node["workflow_reuse_receipt_path"] = rel
        node["workflow_reuse_seal"] = self._seal(
            [("workflow_reuse_receipt", rel)],
            upstream=[str((node.get("spec_seal") or {}).get("digest") or ""),
                      str((node.get("implementation_seal") or {}).get("digest") or "")],
            revision=revision)
        node["workflow_reuse_revision"] = revision
        errs = evalid.workflow_reuse_receipt_errors(self.ctx(), node)
        if errs:
            raise SystemExit("[evo] engine-generated workflow-reuse receipt failed its own audit:\n  - "
                             + "\n  - ".join(errs))
        self.store.event(
            "engine", "workflow_evidence_reused_after_evaluation_fix", node=node.get("id"),
            source_run=node.get("implementation_repair_source_run"),
            preserved_runs=run_ids, changed_files=[row["path"] for row in changes],
            receipt=rel)

    def _begin_implementation_revision(self, node: dict, reason: str) -> None:
        """Open one code revision at the narrowest explicitly declared replay boundary."""
        if node.get("implementation_revision_pending"):
            return
        repair_scope = str(node.get("implementation_repair_scope") or "workflow")
        previous = {
            "revision": int(node.get("implementation_revision") or 0),
            "implementation_digest": str((node.get("implementation_seal") or {}).get("digest") or ""),
            "implementation_commit": node.get("implementation_commit"),
            "implementation_manifest": node.get("implementation_manifest"),
            "reason": str(reason), "retired_at": eutil.utc_now(),
        }
        if repair_scope == "evaluation":
            self._prepare_evaluation_repair_baseline(node, reason)
            self._restart_evaluation_after_fix(node)
        else:
            self._restart_workflow_after_fix(node)
            for field in ("implementation_seal", "workflow_reuse_seal", "fidelity_seal",
                          "ablation_fidelity_seal", "metric_bridge_seal"):
                self._archive_seal(node, field)
        node.setdefault("implementation_selector_history", []).append(previous)
        if repair_scope != "evaluation":
            node["implementation_commit"] = None
            node["implementation_manifest"] = None
        node["implementation_revision_pending"] = True
        node["implementation_revision_reason"] = str(reason)
        if repair_scope != "evaluation":
            node["fidelity_pending"] = bool(node.get("needs_fidelity"))
            node["ablation_fidelity_pending"] = node.get("experiment_purpose") == "targeted_ablation"
            node["metric_bridge_ready"] = False
        self.store.event("engine", "implementation_revision_started", node=node.get("id"),
                         prior_revision=previous["revision"], reason=reason,
                         repair_scope=repair_scope)
