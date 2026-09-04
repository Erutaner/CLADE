"""Active-authority machinery (v10): seal requiredness, availability,
the cross-file active-contract assertion, and implementation seals/selectors.
Shared verbatim by scheduler, submit postconditions, CLI preflight and doctor.
"""

from __future__ import annotations


import econfig
import erun
import eseal
import eutil
import evalid
import evcs

stages_of = econfig.stages_of

# The single authoritative seal-field registry (v9.2 duplicated these in
# edoctor by hand and the copies drifted).
LANE_SEAL_FIELDS = ("diagnosis_seal", "core_palette_seal", "program_seal", "tournament_seal",
                    "problem_seal", "theory_draft_seal", "theory_seal",
                    "idea_seal", "review_seal")
NODE_SEAL_FIELDS = ("spec_seal", "implementation_seal", "workflow_reuse_seal", "fidelity_seal",
                    "ablation_fidelity_seal", "metric_bridge_seal", "resource_receipt_seal",
                    "eval_seal", "conclusion_seal")



class AuthorityMixin:
    @staticmethod
    def _idea_contract_digest(lane: dict) -> str:
        # A diagnostic probe has no review stage (its protection is the manual
        # gate), so its sealed contract is the design seal alone; every other
        # purpose anchors idea+review as one composite.
        if lane.get("experiment_purpose") == "diagnostic_probe":
            return eseal.combine_digests(
                str((lane.get("idea_seal") or {}).get("digest") or ""))
        return eseal.combine_digests(
            str((lane.get("idea_seal") or {}).get("digest") or ""),
            str((lane.get("review_seal") or {}).get("digest") or ""))

    def _supersede_idea_revision(self, lane: dict, *, verdict: str,
                                 review: str | None = None) -> None:
        if lane.get("idea"):
            lane.setdefault("idea_revisions", []).append({
                "idea": lane.get("idea"), "verdict": verdict, "review": review,
                "winner": lane.get("winner_sketch"),
                "winner_program_digest": lane.get("winner_program_digest"),
                "winner_kernel_hash": lane.get("winner_kernel_hash"),
                "program_set": lane.get("sketches_path"),
                "program_set_digest": lane.get("program_set_digest"),
                "tournament": lane.get("tournament_path"),
                "idea_seal": (lane.get("idea_seal") or {}).get("digest"),
                "review_seal": (lane.get("review_seal") or {}).get("digest"),
            })
        self._archive_seal(lane, "idea_seal")
        self._archive_seal(lane, "review_seal")
        lane["idea"] = None

    def _reset_post_program_theory(self, lane: dict) -> None:
        """Discard theory owned by one selected program, never a source theorem."""
        if lane.get("search_origin") == "theory_derived":
            return
        self._archive_seal(lane, "theory_seal")
        self._archive_seal(lane, "theory_draft_seal")
        self._archive_seal(lane, "problem_seal")
        lane["theory_required"] = False
        lane["theory_claim_status"] = "not_claimed"
        lane["theory_downgraded"] = False
        lane["formal"] = False
        lane["formal_kind"] = None
        lane["theory_path"] = None
        lane["problem_path"] = None
        lane["theory_head_ready"] = False
        lane["theory_cycle"] = 0
        lane["cycles"]["theory"] = 0
        lane["required_topics"] = []
        lane["resume_after_read"] = None

    @staticmethod
    def _lane_seal_required(lane: dict, field: str) -> bool:
        if field == "diagnosis_seal":
            return bool(lane.get("diagnosis_path"))
        if field == "core_palette_seal":
            return bool(lane.get("core_palette_path"))
        if field == "program_seal":
            return bool(lane.get("sketches_path"))
        if field == "tournament_seal":
            return bool(lane.get("tournament_path"))
        if field == "problem_seal":
            return bool(lane.get("problem_path"))
        if field == "theory_seal":
            return bool(lane.get("theory_head_ready")
                        and lane.get("theory_claim_status") == "supported")
        if field == "theory_draft_seal":
            return bool(lane.get("theory_head_ready")
                        and lane.get("theory_claim_status") != "supported")
        if field == "idea_seal":
            # The engine allocates I### when it materializes the mature/design
            # task, before any idea bytes have been accepted.  Require the
            # seal only in states reached by accepting that task.
            return bool(lane.get("idea")) and lane.get("status") in {
                "red_team", "ablation_review", "maintenance_review", "gate",
                "approved", "node_created", "done",
            }
        if field == "review_seal":
            # A diagnostic probe deliberately has no review stage.
            if lane.get("experiment_purpose") == "diagnostic_probe":
                return False
            return bool(lane.get("idea")) and lane.get("status") in {
                "gate", "approved", "node_created", "done",
            }
        return False

    @staticmethod
    def _node_seal_required(node: dict, field: str) -> bool:
        # Abandonment retires post-spec authority into seal_history.  Historical
        # seals are still audited below, but an abandoned owner must not be
        # required to expose any of them as an active head.
        if node.get("status") == "abandoned":
            return False
        if field == "spec_seal":
            # ``spec`` is also the preallocated landing path of a proposed
            # baseline.  A seal becomes mandatory only after the engine has
            # accepted a concrete specification revision.
            return int(node.get("spec_revision") or 0) > 0
        if field == "implementation_seal":
            return (int(node.get("implementation_revision") or 0) > 0
                    and not node.get("implementation_revision_pending")
                    and node.get("status") != "abandoned")
        if field == "workflow_reuse_seal":
            return bool(node.get("workflow_reuse_receipt_path"))
        if field == "fidelity_seal":
            return bool(node.get("needs_fidelity") and
                        int(node.get("implementation_revision") or 0) > 0 and
                        not node.get("fidelity_pending"))
        if field == "ablation_fidelity_seal":
            return bool(node.get("experiment_purpose") == "targeted_ablation" and
                        int(node.get("implementation_revision") or 0) > 0 and
                        not node.get("ablation_fidelity_pending"))
        if field == "metric_bridge_seal":
            return bool(node.get("needs_metric_bridge") and node.get("metric_bridge_ready"))
        if field == "resource_receipt_seal":
            return bool(node.get("resource_receipt_ready"))
        if field == "eval_seal":
            # Platform nodes are deliberately evaluation-free: their workflow
            # enablement is judged at conclusion and no metric artifact exists.
            return bool(node.get("role") != "platform" and node.get("eval_done")
                        and node.get("status") in {"evaluated", "concluded"})
        if field == "conclusion_seal":
            return node.get("status") == "concluded"
        return False

    def _seal_availability(self) -> tuple[set[str], set[str]]:
        """Return (active, active+history) seal digests and composite anchors."""
        active_records: list[dict | None] = []
        historical_records: list[dict | None] = []
        active_anchors: set[str] = set()
        historical_anchors: set[str] = set()
        for lane in self.st.get("lanes", []):
            active_records.extend(lane.get(field) for field in LANE_SEAL_FIELDS)
            historical_records.extend(lane.get("seal_history") or [])
            anchor_ready = lane.get("idea_seal") and (
                lane.get("review_seal")
                or lane.get("experiment_purpose") == "diagnostic_probe")
            current = self._idea_contract_digest(lane) if anchor_ready else ""
            if current:
                active_anchors.add(current)
            for revision in lane.get("idea_revisions") or []:
                if not isinstance(revision, dict):
                    continue
                anchor = eseal.combine_digests(str(revision.get("idea_seal") or ""),
                                               str(revision.get("review_seal") or ""))
                if revision.get("idea_seal") and revision.get("review_seal"):
                    historical_anchors.add(anchor)
        for node in self.g.get("nodes", []):
            active_records.extend(node.get(field) for field in NODE_SEAL_FIELDS)
            historical_records.extend(node.get("seal_history") or [])
            if node.get("idea_contract_digest"):
                # This is a composite of the lane's active idea+review seals,
                # authenticated again as NODE_SPEC's upstream anchor.
                active_anchors.add(str(node["idea_contract_digest"]))
            if node.get("workflow_reuse_receipt_path") \
                    and isinstance(node.get("workflow_reuse_seal"), dict):
                receipt = eutil.read_json(
                    eutil.rpath(self.store.repo, str(node["workflow_reuse_receipt_path"])), {})
                if isinstance(receipt, dict):
                    active_anchors.update(
                        str(x) for x in (receipt.get("preserved_upstream_digests") or []) if str(x))
        for run in self.st.get("runs", []):
            if erun.is_active_evidence(run):
                active_records.append(run.get("evidence_seal"))
            else:
                historical_records.append(run.get("evidence_seal"))
            historical_records.extend(run.get("seal_history") or [])
        active = eseal.digest_set(active_records) | active_anchors
        return active, active | eseal.digest_set(historical_records) | historical_anchors

    def _assert_artifact_seals(self, *, allow_implementation_revision_node: str | None = None,
                               only_lane: str | None = None,
                               only_node: str | None = None,
                               scope_lanes: set[str] | None = None,
                               scope_nodes: set[str] | None = None,
                               check_snapshots: bool = True,
                               digest_seed: dict[str, str] | None = None) -> None:
        """Fail closed if an accepted scientific/execution contract changed.

        Working files remain readable, but approvals are content-addressed.
        Superseded revisions retain immutable snapshots and cannot lend their
        approval to a later file written at the same human-readable path. The
        hot scheduler path verifies active heads; ``evo doctor`` audits the
        append-only history so runtime cost does not grow quadratically.

        v11 scope forms: ``only_lane``/``only_node`` audit one subject (the
        submit pattern); ``scope_lanes``/``scope_nodes`` audit the SET of
        objects the imminent scheduling decision consumes (the scoped-next
        pattern) - runs are audited when their node is in scope. ``digest_seed``
        primes the sweep cache with digests computed milliseconds earlier in
        the SAME invocation (the sealing transition); it must never carry
        snapshot-path digests - the post-submit sweep is the snapshot copy's
        first integrity read.
        """
        checks: list[tuple[str, dict | None, bool]] = []
        contract_errs: list[str] = []
        # One digest cache for the whole sweep: pointer-binding checks and seal
        # verification hash the same working files, and digesting is a pure
        # function of current bytes.  The cache never outlives this sweep - a
        # submit's pre/post assertions each build their own, because the
        # transition between them writes new artifacts (the post sweep may be
        # SEEDED with the transition's own freshly computed working digests,
        # which nothing can have changed inside one single-threaded invocation).
        digest_cache: dict[str, str] = dict(digest_seed or {})
        ctx = self.ctx()
        scoped = bool(only_lane or only_node)
        set_scoped = scope_lanes is not None or scope_nodes is not None
        if only_node and not only_lane:
            scoped_node = self.node(only_node)
            only_lane = str((scoped_node or {}).get("lane") or "") or None

        def _lane_in_scope(lane: dict) -> bool:
            if scoped:
                return lane.get("id") == only_lane
            if set_scoped:
                return str(lane.get("id")) in (scope_lanes or set())
            return True

        def _node_in_scope(node: dict) -> bool:
            if scoped:
                return node.get("id") == only_node
            if set_scoped:
                return str(node.get("id")) in (scope_nodes or set())
            return True

        def _git_audit_needed(node: dict) -> bool:
            if not _node_in_scope(node):
                return False
            if node.get("id") == allow_implementation_revision_node:
                return False
            if not (self._git_mode() and node.get("implementation_commit")
                    and node.get("workdir")):
                return False
            return (node.get("status") != "abandoned"
                    and node.get("retire_reason") not in econfig.RETIRE_REASONS)

        # Prefetch the per-node git facts concurrently: the queries are
        # read-only, each targets a distinct workdir, and on Windows the
        # subprocess spawn dominates the whole sweep (3 spawns x N nodes).
        # Failures are stored and re-raised INSIDE the sequential loop below,
        # so ordering, error text and fail-closed semantics are unchanged.
        git_prefetch: dict[str, object] = {}
        git_targets = [n for n in self.g.get("nodes", []) if _git_audit_needed(n)]
        if len(git_targets) > 1:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(8, len(git_targets))) as pool:
                futures = {str(n.get("id")): pool.submit(
                    evcs.integrity_facts,
                    eutil.rpath(self.store.repo, str(n["workdir"])))
                    for n in git_targets}
                for nid_, fut in futures.items():
                    try:
                        git_prefetch[nid_] = fut.result()
                    except BaseException as exc:  # re-raised at the node's turn
                        git_prefetch[nid_] = exc

        for lane in self.st.get("lanes", []):
            if not _lane_in_scope(lane):
                continue
            contract_errs.extend(evalid.core_palette_contract_errors(
                ctx, lane, digest_cache=digest_cache))
            contract_errs.extend(evalid.lane_pointer_binding_errors(
                ctx, lane, digest_cache=digest_cache))
            for field in LANE_SEAL_FIELDS:
                if self._lane_seal_required(lane, field) or isinstance(lane.get(field), dict):
                    checks.append((f"lane {lane.get('id')} {field}", lane.get(field), True))
        # The nested-workdir exclusion set depends only on graph workdir strings,
        # which cannot change inside one sweep: resolve every workdir ONCE here
        # instead of once per audited node (the walk was O(nodes^2) resolve
        # syscalls and alone would exceed the whole current sweep at ~100 nodes).
        workdir_map = evalid.resolved_workdir_map(ctx)
        for node in self.g.get("nodes", []):
            if not _node_in_scope(node):
                continue
            contract_errs.extend(evalid.node_pointer_binding_errors(
                ctx, node, digest_cache=digest_cache))
            # Retired/abandoned nodes keep their immutable snapshots auditable,
            # but their WORKING bytes (worktree sources) may legitimately be
            # gone; `evo revive` re-proves them before authority returns.
            # ONLY a legal retirement earns the relaxation: an illegal
            # retire_reason is corrupt hand-edited state and keeps every
            # active-byte duty (fail closed; doctor also flags GRAPH_RETIRE).
            node_bytes_active = (node.get("status") != "abandoned"
                                 and node.get("retire_reason") not in econfig.RETIRE_REASONS)
            for field in NODE_SEAL_FIELDS:
                if node.get("id") == allow_implementation_revision_node and field in (
                        "implementation_seal", "fidelity_seal", "ablation_fidelity_seal"):
                    continue
                if self._node_seal_required(node, field) or isinstance(node.get(field), dict):
                    checks.append((f"node {node.get('id')} {field}", node.get(field),
                                   node_bytes_active))
            git_facts_ok = False
            if node_bytes_active and self._git_mode() \
                    and node.get("id") != allow_implementation_revision_node \
                    and node.get("implementation_commit") and node.get("workdir"):
                workdir = eutil.rpath(self.store.repo, str(node["workdir"]))
                try:
                    # No cross-sweep caching of these facts beyond the current
                    # invocation: recovery restores and agent-side commits
                    # legally change git state BETWEEN commands, and a stale
                    # HEAD would fabricate SEALED_IMPLEMENTATION verdicts.
                    # Within one invocation the engine never writes a worktree,
                    # so the per-invocation memo in evcs is sound; the sweep
                    # still prefetches all nodes concurrently (spawn-bound).
                    prefetched = git_prefetch.get(str(node.get("id")))
                    if prefetched is None:
                        prefetched = evcs.integrity_facts(workdir)
                    if isinstance(prefetched, BaseException):
                        raise prefetched
                    git_root, current, tracked_clean = prefetched
                    root_matches = bool(git_root) and \
                        git_root.resolve(strict=False) == workdir.resolve(strict=False)
                except evcs.GitWorkdirMissingError as exc:
                    raise SystemExit(
                        f"[evo] SEALED_IMPLEMENTATION_WORKDIR_MISSING: node {node.get('id')} workdir "
                        f"{node.get('workdir')!r} no longer exists although the node's executable "
                        "authority is active. If the worktree was removed deliberately, retire or "
                        "abandon the node (or run the pending implementation revision); restore the "
                        f"directory otherwise. ({exc})") from exc
                except (evcs.GitCheckError, OSError, RuntimeError) as exc:
                    raise SystemExit(
                        f"[evo] SEALED_IMPLEMENTATION_GIT_CHECK_FAILED: node {node.get('id')} "
                        f"could not be audited safely: {exc}") from exc
                if not root_matches:
                    raise SystemExit(
                        f"[evo] SEALED_IMPLEMENTATION_WORKDIR_NOT_ROOT: node {node.get('id')} workdir "
                        f"{node.get('workdir')!r} is not a dedicated Git worktree root")
                if current != node.get("implementation_commit"):
                    raise SystemExit(
                        f"[evo] SEALED_IMPLEMENTATION_COMMIT: node {node.get('id')} workarea HEAD "
                        f"{current!r} differs from reviewed commit {node.get('implementation_commit')!r}; "
                        "submit an explicit implementation revision before launching or absorbing evidence")
                if not tracked_clean:
                    raise SystemExit(
                        f"[evo] SEALED_IMPLEMENTATION_DIRTY: node {node.get('id')} has tracked or staged "
                        "bytes outside its reviewed commit; submit an explicit implementation revision")
                git_facts_ok = True
            if node_bytes_active and node.get("id") != allow_implementation_revision_node and \
                    int(node.get("implementation_revision") or 0) > 0 and \
                    not node.get("implementation_revision_pending"):
                # v11 middle route for the closure audit (per the v10.2b
                # adversarial finding): when HEAD equals the reviewed commit and
                # the tracked tree is clean, tracked rows are byte-identical to
                # the sealed manifest BY GIT'S OWN FACTS - unless an index bit
                # (assume-unchanged / skip-worktree) makes git blind, which is
                # exactly the spoof the audit demonstrated. So the per-row hash
                # is skipped ONLY when the facts hold AND `git ls-files -v`
                # shows no suspicious bit; gitignored rows (absent from the
                # tracked set) always keep their hash, and copy mode / doctor /
                # the periodic full sweep always hash everything.
                tracked_flags = None
                if git_facts_ok and check_snapshots is False:
                    try:
                        flags = evcs.tracked_file_flags(
                            eutil.rpath(self.store.repo, str(node["workdir"])))
                        if all(letter == "H" or letter == "?" for letter in flags.values()):
                            tracked_flags = flags
                    except (evcs.GitCheckError, OSError, RuntimeError):
                        tracked_flags = None  # unverifiable -> full hash, fail closed
                manifest_errs = evalid.implementation_manifest_errors(
                    ctx, node, known_digests=digest_seed,
                    git_tracked=set(tracked_flags) if tracked_flags is not None else None,
                    workdir_map=workdir_map)
                if manifest_errs:
                    raise SystemExit("[evo] SEALED_IMPLEMENTATION_CLOSURE: "
                                     "the reviewed execution closure changed:\n  - "
                                     + "\n  - ".join(manifest_errs[:20]))
        for run in self.st.get("runs", []):
            if scoped and run.get("node") != only_node:
                continue
            if set_scoped and str(run.get("node")) not in (scope_nodes or set()):
                continue
            contract_errs.extend(evalid.run_pointer_binding_errors(
                ctx, run, digest_cache=digest_cache))
            if (int(run.get("evidence_revision") or 0) > 0 and erun.is_active_evidence(run)) \
                    or isinstance(run.get("evidence_seal"), dict):
                checks.append((f"run {run.get('id')} evidence", run.get("evidence_seal"),
                               erun.is_active_evidence(run)))
        active_digests, all_digests = self._seal_availability()
        errs = list(contract_errs)
        errs.extend(err for label, seal, active in checks
                for err in eseal.verify(self.store.repo, seal, label=label,
                                        require_working=active,
                                        check_snapshot=check_snapshots,
                                        digest_cache=digest_cache))
        errs.extend(err for label, seal, active in checks
                    for err in eseal.upstream_errors(
                        seal, active_digests if active else all_digests, label=label))
        if errs:
            raise SystemExit(
                "[evo] an accepted content-addressed contract changed. Restore the working artifact from "
                "its .evo/seals snapshot or create an explicit new revision; approval was not inherited:\n  - "
                + "\n  - ".join(errs[:20]))

    def _seal_implementation(self, node: dict, report_rel: str, *,
                             repair_scope: str | None = None) -> None:
        paths = evalid.implementation_artifact_paths(self.ctx(), node, report_rel)
        manifest_rel = f".evo/nodes/{node.get('id')}/IMPLEMENTATION_MANIFEST.json"
        try:
            manifest = evalid.build_implementation_manifest(self.ctx(), node)
            implementation_commit = (evcs.head_commit(
                eutil.rpath(self.store.repo, str(node.get("workdir") or ".")), strict=True)
                if self._git_mode() else None)
        except evcs.GitCheckError as exc:
            raise SystemExit(
                f"[evo] BUILD_GIT_CHECK_FAILED: node {node.get('id')} could not be sealed safely: {exc}") from exc
        eutil.write_json_atomic(eutil.rpath(self.store.repo, manifest_rel), manifest)
        # Harvest the workarea digests this build just computed for the
        # postcondition sweep (absolute-path keys; the manifest audit compares
        # its on-disk rows against these instead of re-reading unchanged bytes).
        seed = getattr(self, "_seal_digest_seed", None)
        if seed is not None:
            wd = eutil.rpath(self.store.repo, str(node.get("workdir") or ".")).resolve()
            for row in manifest.get("files") or []:
                if isinstance(row, dict) and row.get("path") and row.get("digest"):
                    seed[str((wd / str(row["path"])).resolve(strict=False))] = str(row["digest"])
        paths.append(manifest_rel)
        artifacts = [("build_report" if i == 0 else f"implementation_source_{i}", path)
                     for i, path in enumerate(paths)]
        self._activate_implementation_selector(
            node, artifacts, manifest_rel=manifest_rel,
            implementation_commit=implementation_commit,
            repair_scope=repair_scope)

    def _seal_baseline_implementation(self, node: dict) -> None:
        """Give the verified baseline the same executable identity as descendants.

        A baseline has no BUILD_REPORT because it starts as the supplied project,
        but its execution closure still needs to bind later RUN contracts.  The
        engine-owned manifest is sufficient: it names and hashes every file that
        may affect execution, while Git mode additionally binds the reviewed HEAD.
        """
        manifest_rel = f".evo/nodes/{node.get('id')}/IMPLEMENTATION_MANIFEST.json"
        workdir = eutil.rpath(self.store.repo, str(node.get("workdir") or "."))
        try:
            manifest = evalid.build_implementation_manifest(self.ctx(), node)
            implementation_commit = evcs.head_commit(workdir, strict=True) if self._git_mode() else None
            if self._git_mode() and not evcs.tracked_tree_clean(workdir):
                raise evcs.GitCheckError("baseline workarea has uncommitted tracked or staged bytes")
        except evcs.GitCheckError as exc:
            raise SystemExit(
                f"[evo] BASELINE_GIT_CHECK_FAILED: node {node.get('id')} could not be sealed safely: {exc}") from exc
        eutil.write_json_atomic(eutil.rpath(self.store.repo, manifest_rel), manifest)
        candidate = dict(node)
        candidate["implementation_manifest"] = manifest_rel
        manifest_errs = evalid.implementation_manifest_errors(self.ctx(), candidate)
        if manifest_errs:
            raise SystemExit("[evo] baseline execution closure could not be sealed:\n  - "
                             + "\n  - ".join(manifest_errs[:20]))
        self._activate_implementation_selector(
            node, [("implementation_manifest", manifest_rel)],
            manifest_rel=manifest_rel, implementation_commit=implementation_commit)

    def _activate_implementation_selector(self, node: dict,
                                            artifacts: list[tuple[str, str]], *,
                                            manifest_rel: str,
                                            implementation_commit: str | None,
                                            repair_scope: str | None = None) -> None:
        """Install one reviewed executable head and retire its dependent heads."""
        self._archive_seal(node, "implementation_seal")
        if repair_scope != "evaluation":
            self._archive_seal(node, "workflow_reuse_seal")
            node.pop("workflow_reuse_receipt_path", None)
            self._archive_seal(node, "fidelity_seal")
            self._archive_seal(node, "ablation_fidelity_seal")
        self._archive_seal(node, "metric_bridge_seal")
        node["implementation_manifest"] = manifest_rel
        node["implementation_seal"] = self._seal(
            artifacts, upstream=[str((node.get("spec_seal") or {}).get("digest") or "")],
            revision=int(node.get("implementation_revision") or 0) + 1)
        node["implementation_revision"] = node["implementation_seal"]["revision"]
        if repair_scope != "evaluation":
            node["fidelity_seal"] = None
            node["ablation_fidelity_seal"] = None
        node["metric_bridge_seal"] = None
        node["metric_bridge_ready"] = False
        node["implementation_commit"] = implementation_commit
        if implementation_commit:
            node["commit"] = implementation_commit
