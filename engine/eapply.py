"""Accepted-submission transitions: the single mutation site per task
type. Validation stays in evalid; eapply may assume a validated payload.
"""

from __future__ import annotations

import json
import re

import eartifact
import ecanary
import econfig
import eflow
import egraph
import eprogram
import erehearsal
import erun
import eutil
import evalid
import evcs

stages_of = econfig.stages_of

REVIEW_VERDICT_RE = re.compile(r"^VERDICT:\s*(\S+)", re.M)
TOPIC_LINE_RE = re.compile(r"^\s*[-*]\s*topic\s*:\s*(.+?)\s*$", re.I | re.M)



class ApplyMixin:
    def _transition(self, task: dict) -> None:
        t = task["type"]
        subj = task.get("subject", {})
        st = self.st
        if t == "project_scan":
            if t not in st["bootstrap_done"]:
                st["bootstrap_done"].append(t)
            # The discovery file carries CONTROL FLOW (engine-fit gate,
            # provision step) - stamp the accepted bytes so a post-acceptance
            # edit is detectable instead of silently rewriting the admission
            st.setdefault("profile_digests", {})["project_discovery"] = \
                evalid.text_file_digest(self.ctx(), task["outputs"][1])
        elif t == "configure":
            # Complete but provisional: docs/code reconciliation and the
            # resource envelope still need the user's mandatory sign-off.
            st["config_frozen"] = False
            self.cfg = self.store.load_config()
            if t not in st["bootstrap_done"]:
                st["bootstrap_done"].append(t)
        elif t in ("infra", "infra_interview", "profile", "dossier", "rubric"):
            # "sota_scan" must not join this tuple: its dedicated branch
            # below stamps the accepted-ledger watermark, and without that
            # stamp every later reader freezes the raw file wholesale,
            # cancelled tasks' unaccepted tails included.
            if t not in st["bootstrap_done"]:
                st["bootstrap_done"].append(t)
            if t == "infra_interview":
                st.setdefault("profile_digests", {})["bootstrap_review_config"] = \
                    econfig.bootstrap_contract_digest(self.cfg)
            if t == "infra":
                st.setdefault("profile_digests", {})["infra_facts"] = \
                    ecanary.facts_digest(self.store, self.cfg)
            if t == "dossier":
                st.setdefault("profile_digests", {})["problem_dossier"] = \
                    evalid.text_file_digest(self.ctx(), task["outputs"][0])
        elif t == "infra_drill":
            record = dict(task.get("infra_canary_run") or {})
            if record.get("status") == "passed":
                st["infra_canary"] = record
                if t not in st["bootstrap_done"]:
                    st["bootstrap_done"].append(t)
                if st.get("infra_revision_pending"):
                    # the fresh proof against the revised facts landed: new
                    # spend is legal again
                    st["infra_revision_pending"] = False
                    self.store.event("engine", "infra_revision_proven",
                                     task=task.get("id"), receipt=record.get("receipt"))
                self.store.event("engine", "infra_canary_verified", task=task.get("id"),
                                 receipt=record.get("receipt"))
            else:  # only a typed engine-observed blocked run can reach this transition
                receipt, receipt_errs = ecanary.verified_receipt(self.store, record)
                if receipt is None:
                    raise SystemExit("[evo] blocked infrastructure canary receipt changed during transition:\n  - "
                                     + "\n  - ".join(receipt_errs))
                for blocker in receipt.get("blockers") or []:
                    self.store.add_error(self.st, {
                        "node": None, "stage": "infra_canary", "run": None,
                        "note": f"canary blocked: {blocker.get('missing')} | ask: {blocker.get('ask')}",
                    })
                self.store.new_gate(
                    self.st, "infra_canary_blocked", {"task": task.get("id")},
                    "The project-defined real infrastructure canary is blocked. Supply the typed missing "
                    "resource/access and approve to rerun the complete canary; reject to stop.")
        elif t == "baseline_spec":
            node = self.node(subj["node"])
            spec = self._spec_from(task["outputs"][0])
            spec_artifacts = [("node_spec", task["outputs"][0])]
            spec_protocol = ((spec.get("eval") or {}).get("protocol") or {})
            if isinstance(spec_protocol, dict) and str(spec_protocol.get("episode_order_file") or ""):
                # A streaming episode order is part of the frozen contract;
                # its BYTES freeze with the spec, not merely at evaluation.
                spec_artifacts.append(("episode_order", str(spec_protocol["episode_order_file"])))
            self._archive_seal(node, "spec_seal")
            node["spec_seal"] = self._seal(
                spec_artifacts, revision=int(node.get("spec_revision") or 0) + 1)
            node["spec_revision"] = node["spec_seal"]["revision"]
            node["workdir"] = spec.get("workdir")
            node["status"] = "approved"
            if self._git_mode():
                node["branch"] = evcs.head_branch(eutil.rpath(self.store.repo, node["workdir"] or "."))
                self._capture_commit(node)
            egraph.touch(node)
        elif t == "provision":
            # The preparation pass runs BEFORE configure - its observed
            # facts (real metric keys, data locations, landing paths) are what
            # the contract will be frozen against, and its constructive
            # choices are listed for the user's sign-off at the contract gate.
            data = self._spec_from(task["outputs"][1])
            if data.get("status") == "ready":
                if t not in st["bootstrap_done"]:
                    st["bootstrap_done"].append(t)
                st.setdefault("profile_digests", {})["provision"] = \
                    evalid.text_file_digest(self.ctx(), task["outputs"][1])
                self.store.event("engine", "provision_ready",
                                 work=len(data.get("work") or []),
                                 choices=len(data.get("choices") or []))
            else:  # blocked: typed feedback to the user; supplement -> retry
                for blocker in data.get("blockers") or []:
                    self.store.add_error(self.st, {
                        "node": None, "stage": "provision", "run": None,
                        "note": f"provision blocked: {(blocker or {}).get('missing')} | "
                                f"ask: {(blocker or {}).get('ask')}",
                    })
                self.store.new_gate(self.st, "provision_blocked", {"task": task.get("id")},
                                    "Preparing the project is BLOCKED: it cannot reach a first real "
                                    "number with what was provided. See .evo/profile/PROVISION.md. "
                                    "Approve after supplying the missing items (note what you added) "
                                    "to retry; reject to STOP the evolution.")
                self.store.event("engine", "provision_blocked",
                                 blockers=[str((b or {}).get("missing")) for b in data.get("blockers") or []])
        elif t == "evidence":
            # Acceptance freezes the validated prefix - the next evidence
            # task holds THIS history immutable, while a cancelled task's
            # unaccepted leftovers stay repairable.
            evalid.stamp_ledger_watermark(self.st, "evidence", self.store.evidence())
        elif t == "sota_scan":
            # Acceptance = the whole file just validated; freeze it as the
            # accepted prefix (and keep the bootstrap bookkeeping the generic
            # branch above provides for the other bootstrap tasks).
            if t not in st["bootstrap_done"]:
                st["bootstrap_done"].append(t)
            evalid.stamp_ledger_watermark(
                self.st, "sota",
                eutil.read_jsonl(eutil.rpath(self.store.repo, ".evo/evidence/SOTA.jsonl")))
        elif t == "open_round":
            self._apply_portfolio(task)
        elif t == "diagnose":
            self._apply_diagnose(task)
        elif t == "deep_read":
            self._apply_deep_read(task)
        elif t == "sketch":
            lane = self._lane_of(subj)
            lane["attempt_seq"] = int(lane.get("attempt_seq") or 0) + 1
            lane["sketches_path"] = task["outputs"][0]
            lane["program_set_digest"] = evalid.json_file_digest(self.ctx(), task["outputs"][0])
            upstream = [str((lane.get("diagnosis_seal") or {}).get("digest") or ""),
                        str((lane.get("theory_seal") or {}).get("digest") or ""),
                        str((lane.get("core_palette_seal") or {}).get("digest") or "")]
            lane["program_seal"] = self._seal(
                [("program_set", task["outputs"][0])], upstream=upstream,
                revision=int(lane["attempt_seq"]))
            lane["tournament_path"] = None
            lane["tournament_seal"] = None
            # Every route gets a post-freeze, digest-bound collision audit.
            # Repair keeps its pre-sketch diagnosis reading for invention, but
            # that cannot substitute for checking the eventual KC# against its
            # actual nearest programs.
            lane["resume_after_read"] = "tournament"
            lane["status"] = "deep_read"
        elif t == "tournament":
            self._apply_tournament(task)
        elif t == "pose":
            lane = self._lane_of(subj)
            self._archive_seal(lane, "problem_seal")
            lane["problem_seq"] = int(lane.get("problem_seq") or 0) + 1
            lane["problem_path"] = task["outputs"][0]
            upstream = [str((lane.get("program_seal") or {}).get("digest") or "")]
            lane["problem_seal"] = self._seal(
                [("posed_problem", task["outputs"][0])], upstream=upstream,
                revision=int(lane["problem_seq"]))
            lane["theory_cycle"] = int(lane.get("theory_cycle") or 0) + 1
            lane["status"] = "theorize"
            self.store.event("engine", "problem_posed", lane=lane["id"], problem=lane["problem_path"])
        elif t == "theorize":
            lane = self._lane_of(subj)
            self._archive_seal(lane, "theory_draft_seal")
            lane["theory_seq"] = int(lane.get("theory_seq") or 0) + 1
            lane["theory_path"] = task["outputs"][0]
            # The sketch validator demands
            # data.theory_digest == text_file_digest(theory_path), but nothing
            # ever assigned lane.theory_digest - the Frozen digests block reads
            # it, so the row was unreachable and every theory-derived sketch
            # was a guaranteed three-strike wedge. Keep it on the theory head.
            lane["theory_digest"] = evalid.text_file_digest(self.ctx(), task["outputs"][0])
            upstream = [str((lane.get("problem_seal") or {}).get("digest") or ""),
                        str((lane.get("program_seal") or {}).get("digest") or "")]
            lane["theory_draft_seal"] = self._seal(
                [("theory", task["outputs"][0])], upstream=upstream,
                revision=int(lane["theory_seq"]))
            lane["theory_head_ready"] = True
            lane["status"] = "challenge"
        elif t == "challenge":
            self._apply_challenge(task)
        elif t == "design_ablation":
            lane = self._lane_of(subj)
            self._archive_seal(lane, "idea_seal")
            upstream = [str((lane.get("diagnosis_seal") or {}).get("digest") or "")]
            lane["idea_seal"] = self._seal(
                [("idea", task["outputs"][0]), ("idea_meta", task["outputs"][1])],
                upstream=upstream, revision=len(lane.get("seal_history") or []) + 1)
            lane["status"] = "ablation_review"
        elif t == "review_ablation":
            self._apply_review_ablation(task)
        elif t == "probe_design":
            # A probe's protection is the manual gate right after it; the
            # design seal alone is its contract head (no review stage).
            lane = self._lane_of(subj)
            self._archive_seal(lane, "idea_seal")
            lane["idea_seal"] = self._seal(
                [("idea", task["outputs"][0]), ("idea_meta", task["outputs"][1])],
                revision=len(lane.get("seal_history") or []) + 1)
            lane["status"] = "gate"
        elif t == "maintenance_design":
            lane = self._lane_of(subj)
            self._archive_seal(lane, "idea_seal")
            lane["idea_seal"] = self._seal(
                [("idea", task["outputs"][0]), ("idea_meta", task["outputs"][1])],
                revision=len(lane.get("seal_history") or []) + 1)
            lane["status"] = "maintenance_review"
        elif t == "maintenance_review":
            self._apply_maintenance_review(task)
        elif t == "mature":
            lane = self._lane_of(subj)
            self._archive_seal(lane, "idea_seal")
            upstream = [str((lane.get("program_seal") or {}).get("digest") or ""),
                        str((lane.get("tournament_seal") or {}).get("digest") or ""),
                        str((lane.get("theory_seal") or {}).get("digest") or "")]
            lane["idea_seal"] = self._seal(
                [("idea", task["outputs"][0]), ("idea_meta", task["outputs"][1])],
                upstream=upstream, revision=len(lane.get("seal_history") or []) + 1)
            lane["status"] = "red_team"
        elif t == "red_team":
            self._apply_red_team(task)
        elif t == "plan_node":
            self._apply_plan_node(task)
        elif t == "implement":
            node = self.node(subj["node"])
            pending = bool(node.get("implementation_revision_pending"))
            repair_scope = str(node.get("implementation_repair_scope") or "workflow") if pending else None
            if pending and repair_scope == "evaluation":
                report = eutil.read_text(eutil.rpath(self.store.repo, task["outputs"][0]))
                if evalid.implementation_repair_scope(report) == "workflow":
                    # Widening is always safe and never silent: it changes the
                    # repeat-spend gate to the whole workflow before any new
                    # external work can be released.
                    repair_scope = "workflow"
                    node["implementation_repair_scope"] = "workflow"
                    repeat = node.get("repeat_attempt") or {}
                    if repeat:
                        repeat["operation"] = "workflow"
                        repeat["repair_scope"] = "workflow"
                    self._restart_workflow_after_fix(node)
                    node["fidelity_pending"] = bool(node.get("needs_fidelity"))
                    node["ablation_fidelity_pending"] = \
                        node.get("experiment_purpose") == "targeted_ablation"
                    node["metric_bridge_ready"] = False
                    self.store.event("engine", "implementation_repair_scope_widened",
                                     node=node.get("id"), source_run=node.get("implementation_repair_source_run"),
                                     from_scope="evaluation", to_scope="workflow")
            if not pending:
                self._restart_workflow_after_fix(node)
            node["status"] = "building"
            node["fix_needed"] = False
            node["fix_note"] = None
            if repair_scope != "evaluation" and node.get("needs_fidelity"):
                node["fidelity_pending"] = True   # every (re)build re-arms the audit
            if repair_scope != "evaluation" and node.get("experiment_purpose") == "targeted_ablation":
                node["ablation_fidelity_pending"] = True
            self._capture_commit(node)
            self._seal_implementation(node, task["outputs"][0], repair_scope=repair_scope)
            if repair_scope == "evaluation":
                self._seal_workflow_reuse(node, task["outputs"][0])
            node.pop("implementation_revision_pending", None)
            node.pop("implementation_revision_reason", None)
            node.pop("implementation_repair_scope", None)
            node.pop("implementation_repair_source_run", None)
            if repair_scope != "evaluation":
                node.pop("implementation_revision_baseline_path", None)
                node.pop("implementation_revision_baseline_digest", None)
            egraph.touch(node)
        elif t == "fidelity":
            node = self.node(subj["node"])
            self._archive_seal(node, "fidelity_seal")
            node["fidelity_seal"] = self._seal(
                [("fidelity_report", task["outputs"][0])],
                upstream=[str((node.get("implementation_seal") or {}).get("digest") or "")],
                revision=int(node.get("fidelity_revision") or 0) + 1)
            node["fidelity_revision"] = node["fidelity_seal"]["revision"]
            node["fidelity_pending"] = False
            egraph.touch(node)
            self.store.event("engine", "fidelity_passed", node=node["id"])
        elif t == "ablation_fidelity":
            node = self.node(subj["node"])
            self._archive_seal(node, "ablation_fidelity_seal")
            node["ablation_fidelity_seal"] = self._seal(
                [("ablation_fidelity_report", task["outputs"][0])],
                upstream=[str((node.get("implementation_seal") or {}).get("digest") or "")],
                revision=int(node.get("ablation_fidelity_revision") or 0) + 1)
            node["ablation_fidelity_revision"] = node["ablation_fidelity_seal"]["revision"]
            node["ablation_fidelity_pending"] = False
            egraph.touch(node)
            self.store.event("engine", "ablation_fidelity_passed", node=node["id"])
        elif t == "smoke":
            node = self.node(subj["node"])
            node["status"] = "smoke_pass"
            self._capture_commit(node)
            egraph.touch(node)
        elif t == "rehearsal":
            # A PASSING rehearsal must route here explicitly: in the terminal
            # no-transition branch below the loop would wedge (attempts never
            # increment on that path). The authority is already complete
            # before this transition: run-rehearsal recorded rehearsal_run
            # {passed + receipt + seal binding} and every consumer (launch
            # audits, card minting) reads that record, so acceptance changes no
            # state - it logs the acceptance fact and touches the node. Task
            # closure is generic in the submit path.
            node = self.node(subj["node"])
            if erehearsal.record_errors(self.store, node):
                raise SystemExit("[evo] rehearsal task accepted without a satisfying rehearsal "
                                 "record (engine bug)")
            self.store.event("engine", "rehearsal_accepted", node=node["id"],
                             receipt=str((node.get("rehearsal_run") or {}).get("receipt") or ""))
            egraph.touch(node)
        elif t == "metric_bridge":
            node = self.node(subj["node"])
            baseline = next((n for n in self.g.get("nodes", []) if n.get("role") == "baseline"), {})
            self._archive_seal(node, "metric_bridge_seal")
            node["metric_bridge_seal"] = self._seal(
                [("metric_bridge_anchor",
                  next((o for o in task["outputs"] if str(o).endswith("ANCHOR.json")),
                       task["outputs"][0]))],
                upstream=[str((node.get("implementation_seal") or {}).get("digest") or ""),
                          str((baseline.get("eval_seal") or {}).get("digest") or "")],
                revision=int(node.get("metric_bridge_revision") or 0) + 1)
            node["metric_bridge_revision"] = node["metric_bridge_seal"]["revision"]
            node["metric_bridge_ready"] = True
            node["status"] = "bridge_pass"
            egraph.touch(node)
        elif t == "stage_launch":
            self._apply_stage_launch(task)
        elif t == "eval_launch":
            self._apply_eval_launch(task)
        elif t == "evaluate":
            node = self.node(subj["node"])
            metrics = eutil.read_json(eutil.rpath(self.store.repo, task["outputs"][0]), {}) or {}
            if "_resource_measurements" in metrics:
                raise SystemExit("[evo] analyst attempted to write engine-owned resource fields after validation")
            stale_inject = metrics.pop("_effect_resources", None)
            if stale_inject is not None \
                    and stale_inject != evalid.effect_resources_from_receipt(self.ctx(), node):
                raise SystemExit("[evo] analyst attempted to write engine-owned resource fields after validation")
            # (a byte-identical _effect_resources is this transition's own prior
            # injection, replayed after a crash before the state commit - pop it
            # and re-inject below so the replay converges instead of poisoning)
            if not node.get("eval_resource_accounted") or not node.get("resource_receipt_ready"):
                raise SystemExit("[evo] normalized evaluation cannot advance without accounted eval RUN evidence "
                                 "and an active engine resource receipt")
            probe_unavailable = evalid.active_probe_unavailable(self.ctx(), node)
            if probe_unavailable and metrics.pop("_mechanism_probe", None) is not None:
                # The raw producer RUN remains sealed verbatim.  A normalized
                # assessment may not nevertheless derive a mechanism verdict
                # from the partial payload that the signed gap excluded.
                self.store.event("engine", "unavailable_probe_payload_excluded",
                                 node=node.get("id"), eval_run=node.get("eval_run"))
            metrics["_effect_resources"] = evalid.effect_resources_from_receipt(self.ctx(), node)
            eutil.write_json_atomic(eutil.rpath(self.store.repo, task["outputs"][0]), metrics)
            probe_sources = evalid.active_probe_snapshot_map(self.ctx(), node)
            result_errs = evalid.evaluation_result_errors(
                self.ctx(), self._spec(node), task["outputs"][0],
                where=f"node {node['id']} evaluation transition", metrics_data=metrics,
                allow_probe_unavailable=probe_unavailable,
                probe_artifact_sources=probe_sources, node=node)
            result_errs += evalid.normalized_raw_binding_errors(self.ctx(), node, metrics)
            if result_errs:
                raise SystemExit("[evo] evaluation evidence changed after validation; node was not advanced: "
                                 + "; ".join(result_errs))
            receipt_errs = evalid._effect_resource_receipt_errors(self.ctx(), node,
                                                                  metrics["_effect_resources"])
            if receipt_errs:
                raise SystemExit("[evo] resource receipt changed after analyst validation: "
                                 + "; ".join(receipt_errs))
            task.pop("resource_reservation", None)
            rm = node.get("repeat_measure")
            if isinstance(rm, dict) and not node.get("repeat_measure_done"):
                row = metrics.get(str(rm.get("result_key") or ""))
                if isinstance(row, dict) and isinstance(row.get("training_replication"), dict):
                    # An engine-run buy-back settles only
                    # AFTER its repeat evaluation RUN reached a sealed
                    # terminal state - the aggregate may never outrun the
                    # purchase it reports. The scheduler already withholds the
                    # analysis card until then; this is the transition-side
                    # statement of the same invariant.
                    if rm.get("engine_run") and not node.get("repeat_eval_run"):
                        raise SystemExit(
                            "[evo] repeat_measure aggregate reported before the engine-run repeat "
                            "evaluation settled; the repeat RUN must reach its sealed terminal "
                            "state first")
                    # The buy-back is settled on this aggregate, once.
                    # The done flag is what makes re-triggering impossible.
                    self._flush_repeat_product_registrations(node)
                    node["repeat_measure_done"] = True
                    self.store.event("engine", "repeat_measure_settled", node=node["id"],
                                     cell=rm.get("cell"), result_key=rm.get("result_key"))
            keys = set(econfig.result_spec(self.cfg))
            node["score_evidence"] = {k: v for k, v in metrics.items()
                                      if k in keys and evalid.metric_value(v) is not None}
            node["scores"] = {k: mv for k, v in metrics.items()
                              if k in keys and (mv := evalid.metric_value(v)) is not None}
            node["effect_resources_realized"] = json.loads(json.dumps(metrics.get("_effect_resources") or {}))
            node["evaluation_summary"] = ({}
                if node.get("role") in ("baseline", "platform")
                else evalid.computed_assessment(self.ctx(), node, metrics))
            extra_sealed: list[tuple[str, str]] = []
            protocol = ((self._spec(node).get("eval") or {}).get("protocol") or {})
            if isinstance(protocol, dict) and str(protocol.get("episode_order_file") or ""):
                extra_sealed.append(("episode_order", str(protocol["episode_order_file"])))
            for cell in econfig.evaluation_cells(self.cfg):
                if str(cell.get("source_kind") or "") != "human_study":
                    continue
                row = metrics.get(str(cell.get("result_key") or ""))
                if isinstance(row, dict) and str(row.get("study_artifact") or ""):
                    extra_sealed.append((f"human_study_{cell.get('id')}", str(row["study_artifact"])))
            # An interval's fixed evaluation/prediction artifact is part of
            # the settlement evidence - seal the local ones so a post-hoc
            # rewrite/delete of the file behind the bounds trips the seal
            # audit instead of leaving the interval unauditable.
            for key in econfig.result_spec(self.cfg):
                row = metrics.get(key)
                unc = row.get("uncertainty") if isinstance(row, dict) else None
                src = str(unc.get("source") or "") if isinstance(unc, dict) else ""
                if src and eutil.rpath(self.store.repo, src).is_file():
                    extra_sealed.append((f"uncertainty_source_{key}", src))
            self._archive_seal(node, "eval_seal")
            node["eval_seal"] = self._seal(
                [("normalized_metrics", task["outputs"][0]), ("evaluation_report", task["outputs"][1])]
                + extra_sealed
                + [(f"resource_receipt_{i}", path) for i, path in enumerate(
                    evalid.effect_resource_source_paths(metrics, task["outputs"][0]))]
                + [(f"mechanism_probe_{i}", path) for i, path in enumerate(
                    evalid.mechanism_probe_source_paths(metrics, probe_sources))],
                upstream=[str((node.get("spec_seal") or {}).get("digest") or ""),
                          str((node.get("implementation_seal") or {}).get("digest") or ""),
                          str((node.get("workflow_reuse_seal") or {}).get("digest") or ""),
                          str((node.get("resource_receipt_seal") or {}).get("digest") or "")]
                + [str((run.get("evidence_seal") or {}).get("digest") or "")
                   # Only ADOPTED evidence heads are active upstreams: one
                   # historical digest (quarantined/superseded) in an active
                   # upstream list would make the active-seal audit fail
                   # permanently, bricking every later engine command.
                   for run in self.st.get("runs", [])
                   if run.get("node") == node.get("id") and erun.is_active_evidence(run)],
                revision=int(node.get("eval_revision") or 0) + 1)
            node["eval_revision"] = node["eval_seal"]["revision"]
            node["eval_metrics_path"] = task["outputs"][0]
            node["eval_report_path"] = task["outputs"][1]
            node["status"] = "evaluated"
            egraph.touch(node)
        elif t in ("conclude", "scientific_conclude"):
            self._apply_conclude(task)
        elif t == "close_round":
            self._apply_close_round(task)
        elif t == "instrument_review":
            self._apply_instrument_review(task)
        else:
            raise SystemExit(f"[evo] no transition for task type {t} (engine bug)")

    def _observed_best(self) -> float | None:
        """Best display value this project has actually measured.

        Reading it off the inheritance frontier instead reported the project as
        flat for as long as no claim settled, even while a node several points
        better sat in the graph - and that flat trace is what drives the
        stagnation escalations.
        """
        primary = econfig.primary_metric(self.cfg)
        direction = econfig.result_direction(self.cfg, primary)
        vals = [s for n in self.g.get("nodes", [])
                if egraph.observation_eligible(n, self.cfg)
                and (s := egraph.primary_score(n, primary)) is not None]
        if not vals:
            return None
        return max(vals) if direction == "max" else min(vals)

    def _origin_primary(self) -> float | None:
        """Where the user started, kept as a fixed reference line."""
        origin = egraph.origin_node(self.g)
        return egraph.primary_score(origin, econfig.primary_metric(self.cfg)) \
            if origin is not None else None

    @staticmethod
    def _lane_entry_status(ln: dict) -> str:
        # An instrumental lane starts at the first status of its own route, so
        # a new purpose needs no edit here - only an eflow.INSTRUMENTAL_SEQ row,
        # which check_tables proves total against econfig.INSTRUMENTAL_PURPOSES.
        seq = eflow.INSTRUMENTAL_SEQ.get(econfig.lane_purpose(ln))
        if seq is not None:
            return seq[0]
        return ("diagnose" if ln.get("search_origin") == "repair"
                else ("pose" if ln.get("search_origin") == "theory_derived"
                      else ("deep_read" if ln.get("search_origin") == "core_synthesis"
                            else "sketch")))

    def open_instrumental_lane(self, *, purpose: str, parent: str, text: str, brief_title: str,
                               name: str | None = None, actor: str = "engine",
                               opened_by: str = "cli") -> dict:
        """Mid-round intake for instrumental work (ablate / probe / maintain).

        The round portfolio stays the only door for search bets; a causal
        question, a user question or a discovered defect may enter NOW instead
        of masquerading as next round's research candidate. Same legality rules
        as the portfolio door (evalid.injected_lane_errors), full seal/receipt
        discipline downstream. Raises SystemExit with the reason when the lane
        cannot open; callers that must not abort record the reason instead."""
        import erecover
        st = self.st
        if st.get("phase") != "rounds" or st.get("round_status") != "running":
            raise SystemExit("[evo] mid-round intake needs an open, running round (phase=rounds); "
                             "declare the lane in the next open_round portfolio instead")
        rid = str(st.get("current_round") or "")
        # The RECEIVING round's own hold blocks intake too.
        round_holds = erecover.active_holds_for_subject(st, self.g, round_=rid)
        if round_holds:
            raise SystemExit("[evo] the current round is under active hold(s) "
                             + ", ".join(round_holds)
                             + "; resume them (or finish their recovery) before injecting a lane")
        # Every legality check runs BEFORE any state or event changes below:
        # a refusal has no side effects (no cancelled close_round task, no
        # event row for a cancellation that never happened).
        name = str(name or f"{purpose.replace('_', '-')}-{rid.lower()}")
        text = str(text or "").strip()
        if len(text) < 20:
            flag = "--defect" if purpose == "maintenance" else "--question"
            raise SystemExit(f"[evo] {flag} needs >= 20 chars of substance (it becomes the lane brief)")
        brief_rel = f".evo/rounds/{rid}/lanes/{name}/BRIEF.md"
        ln = {"name": name, "intent": "exploit", "experiment_purpose": purpose,
              "search_origin": "repair", "min_level": 0,
              "parents": [str(parent)], "bottleneck_ids": [], "brief_md": brief_rel}
        errs = evalid.injected_lane_errors(self.ctx(), ln, rid)
        if errs:
            raise SystemExit("[evo] cannot open this lane:\n  - " + "\n  - ".join(errs))
        # Containment belt beside the name slug check: the engine authors this
        # file, so it must be provably inside the managed .evo tree.
        brief_path = eutil.rpath(self.store.repo, brief_rel).resolve()
        evo_root = (self.store.repo / ".evo").resolve()
        if evo_root not in brief_path.parents:
            raise SystemExit(f"[evo] refusing to write a lane brief outside .evo: {brief_path}")
        if brief_path.exists():
            raise SystemExit(f"[evo] a lane brief already exists at {brief_rel}; choose another --name "
                             "(an existing brief is another lane's frozen evidence)")
        # ANY not-yet-terminal close_round lifecycle (open, paused, stuck - and a
        # stuck task's escalation gate) means this round is already closing. An
        # injected lane would make that task permanently unsubmittable while it
        # pre-empts all scheduling. Cancel the whole close lifecycle; the
        # scheduler re-mints it once the lane is done. Only reached once the
        # lane is certain to be created.
        for t in st.get("tasks", []):
            if t.get("type") == "close_round" and t.get("status") in ("open", "paused", "stuck") \
                    and str((t.get("subject") or {}).get("round") or "") == rid:
                for gate in st.get("gates", []):
                    if gate.get("status") == "open" and gate.get("kind") == "escalation" \
                            and str((gate.get("subject") or {}).get("task") or "") == str(t.get("id")):
                        gate["status"] = "cancelled"
                        gate["resolved_at"] = eutil.utc_now()
                        gate["note"] = "superseded: mid-round intake cancelled the stuck close_round task"
                        self.store.event("engine", "gate_cancelled", gate=gate.get("id"),
                                         reason="close_round_lifecycle_cancelled")
                t["status"] = "cancelled"
                t.pop("_render", None)
                t["updated_at"] = eutil.utc_now()
                self.store.event("engine", "close_round_task_cancelled", task=t.get("id"), round=rid,
                                 reason="mid-round instrumental intake reopened the round's work")
        eutil.write_text(eutil.rpath(self.store.repo, brief_rel),
                         f"# {brief_title}\n\n## Goal\n{text}\n\n## Constraints\n"
                         f"- instrumental work: no novelty claim, level 0\n"
                         f"- parent: {parent}\n")
        lane = self._create_lane(rid, ln, opened_by=opened_by)
        # actor=engine, matching the lane_created event this rides beside: this
        # door is open to the agent and to the engine itself by design, and
        # authority over the spend is exercised at the gate (gate_decided
        # records who exercised it).
        self.store.event(actor, "instrumental_lane_injected", lane=lane["id"], round=rid,
                         purpose=purpose, parent=str(parent), note=eutil.clip_words(text, 240), opened_by=opened_by)
        return lane

    def _create_lane(self, rid: str, ln: dict, *, opened_by: str = "portfolio") -> dict:
        """One lane record constructor shared by the round portfolio and the
        mid-round instrumental intake (`evo probe` / `evo maintain`) - the two
        entry points can never drift on lane shape. A targeted-ablation lane
        on a parent whose mechanism is still deferred is that parent's open
        inheritance-tax lane whichever door opened it: the parent points at
        it, a pending tax record is cleared, and who opened it is recorded."""
        st = self.st
        lid = self.store.next_id(st, "L")
        lane = {
            "id": lid, "round": rid, "name": ln.get("name"), "intent": ln.get("intent"),
            "experiment_purpose": ln.get("experiment_purpose"),
            "search_origin": ln.get("search_origin"),
            "min_level": ln.get("min_level"), "parents": list(ln.get("parents") or []),
            "bottleneck_ids": list(ln.get("bottleneck_ids") or []),
            "brief_md": ln.get("brief_md"),
            "status": self._lane_entry_status(ln),
            "cycles": {"sketch": 0, "mature": 0, "theory": 0, "ablation": 0},
            "theory_cycle": 0, "required_topics": [], "theory_path": None,
            "core_palette_path": None, "core_palette_digest": None,
            "core_palette_provenance_path": None, "core_palette_seal": None,
            "theory_required": ln.get("search_origin") == "theory_derived",
            "theory_claim_status": "pending" if ln.get("search_origin") == "theory_derived" else "not_claimed",
            "theory_downgraded": False,
            "formal": ln.get("search_origin") == "theory_derived",
            "formal_kind": ln.get("theory_rigor") if ln.get("search_origin") == "theory_derived" else None,
            "problem_path": None,
            "problem_seq": 0, "problem_seal": None,
            "focus": str(ln.get("focus") or "") or None,
            "mechanism_premises": [str(x) for x in (ln.get("mechanism_premises") or [])],
            "scaling_followup_of": str(ln.get("scaling_followup_of")) if ln.get("scaling_followup_of") else None,
            "confirmatory_of": str(ln.get("confirmatory_of")) if ln.get("confirmatory_of") else None,
            "diagnosis_path": None, "diagnosis_digest": None, "diagnosis_seal": None,
            "sketches_path": None, "tournament_path": None, "winner_sketch": None,
            "program_set_digest": None, "winner_program_digest": None,
            "winner_kernel_hash": None, "attempt_seq": 0,
            "program_seal": None, "tournament_seal": None,
            "theory_seq": 0, "theory_head_ready": False,
            "theory_draft_seal": None, "theory_seal": None,
            "idea_seal": None, "review_seal": None, "seal_history": [],
            "reading_done": False, "resume_after_read": None,
            "attempts": [],
            "idea": None, "node": None, "abandon_reason": None,
        }
        st["lanes"].append(lane)
        self.store.event("engine", "lane_created", lane=lid, round=rid, intent=lane["intent"],
                         search_origin=lane["search_origin"],
                         experiment_purpose=lane["experiment_purpose"], parents=lane["parents"],
                         min_level=lane["min_level"], focus=lane["focus"])
        if lane["experiment_purpose"] == "targeted_ablation":
            idx = egraph.by_id(self.g)
            parent = next((idx[p] for p in lane["parents"]
                           if p in idx and idx[p].get("role") != "platform"), None)
            pending = parent.get("ablation_pending") if isinstance(parent, dict) else None
            if parent is not None and (isinstance(pending, dict)
                                       or (str(parent.get("mechanism_status") or "") == "deferred"
                                           and not egraph.open_ablation_lane(parent, st))):
                parent["ablation_lane"] = lid
                parent["ablation_lane_opened_by"] = opened_by
                parent.pop("ablation_pending", None)
                egraph.touch(parent)
                self.store.event("engine", "ablation_lane_bound", parent=parent.get("id"), lane=lid,
                                 round=rid, opened_by=opened_by, was_pending=isinstance(pending, dict))
        return lane

    def _apply_portfolio(self, task: dict) -> None:
        st = self.st
        rid = task["subject"]["round"]
        pf = self._spec_from(task["outputs"][0])
        for ln in pf.get("lanes", []):
            self._create_lane(rid, ln, opened_by="portfolio")
        st["round_status"] = "running"
        st.setdefault("round_start_primary", {})[rid] = self._observed_best()
        st.setdefault("round_start_frontier", {})[rid] = [n["id"] for n in egraph.frontier(self.g, self.cfg, self.st)]
        st.setdefault("round_start_performance_frontier", {})[rid] = [
            n["id"] for n in egraph.performance_frontier(self.g, self.cfg, self.st)]
        self.store.event("engine", "round_running", round=rid, lanes=len(pf.get("lanes", [])))
        self._accept_advice = self._open_pending_ablations()

    def _open_pending_ablations(self) -> list[str]:
        """Pending inheritance tax is the engine's job: every promoted win whose
        mechanism is still deferred and whose ablation could not open at its
        own conclusion gets another attempt the moment a round goes running.
        Every waiting node gets its lane; what still cannot open (a held
        round) stays pending with a refreshed timestamp and remains on the
        open_round card's doors."""
        advice: list[str] = []
        for node in sorted(self.g.get("nodes", []), key=lambda n: str(n.get("id") or "")):
            pending = node.get("ablation_pending")
            if not isinstance(pending, dict) or egraph.open_ablation_lane(node, self.st) \
                    or str(node.get("mechanism_status") or "") != "deferred" \
                    or node.get("scientific_promotion_status") != "met" \
                    or str(node.get("experiment_purpose") or "candidate") != "candidate" \
                    or node.get("retire_reason") in ("archived", "pruned"):
                continue
            kernels = ", ".join(str(k) for k in (node.get("kernel_ids") or [])) or "its kernel"
            advice.extend(self._open_inheritance_tax(node, kernels, opened_by="open_round"))
        return advice

    def _apply_deep_read(self, task: dict) -> None:
        lane = self._lane_of(task["subject"])
        lane["reading_done"] = True
        # Freeze the validated mech/collision prefixes at acceptance.
        # The evidence watermark must advance here TOO: v_deep_read validates
        # the per-lane evidence top-up this task legally appended, and every
        # consumer reads only the accepted prefix - a watermark left behind
        # makes those just-accepted E### rows invisible (and citing them a
        # validation error) until the next evidence task.
        evalid.stamp_ledger_watermark(self.st, "evidence", self.store.evidence())
        evalid.stamp_ledger_watermark(self.st, "mech", self.store.mech_cards())
        evalid.stamp_ledger_watermark(
            self.st, "collision",
            eutil.read_jsonl(eutil.rpath(self.store.repo, ".evo/evidence/COLLISION_AUDITS.jsonl")))
        if lane.get("search_origin") == "core_synthesis" and not lane.get("core_palette_path"):
            # Project only operational facts from the reconstructed papers.
            # Paper ids, titles, author motivation, prose quotes and card ids
            # are deliberately absent: the generator sees what the works DO,
            # while the later collision audit sees full provenance.
            cards = sorted(
                (c for c in self.store.mech_cards() if c.get("lane") == lane.get("id")),
                key=lambda c: str(c.get("id") or ""))
            palette, provenance = evalid.core_palette_projection(self.ctx(), lane, cards)
            palette_rel = f"{self._lane_dir(lane)}/CORE_PALETTE.json"
            provenance_rel = f"{self._lane_dir(lane)}/CORE_PALETTE_PROVENANCE.json"
            eutil.write_json_atomic(eutil.rpath(self.store.repo, palette_rel), palette)
            eutil.write_json_atomic(eutil.rpath(self.store.repo, provenance_rel), provenance)
            lane["core_palette_path"] = palette_rel
            lane["core_palette_provenance_path"] = provenance_rel
            lane["core_palette_digest"] = evalid.json_file_digest(self.ctx(), palette_rel)
            lane["core_palette_seal"] = self._seal(
                [("anonymous_core_palette", palette_rel),
                 ("audit_only_core_provenance", provenance_rel)],
                revision=len(lane.get("seal_history") or []) + 1)
            self.store.event("engine", "core_palette_frozen", lane=lane["id"],
                             cores=len(palette["cores"]), digest=lane["core_palette_digest"])
        if lane.get("required_topics"):
            lane["required_topics"] = []
            lane["theory_cycle"] = int(lane.get("theory_cycle") or 0) + 1
            resume = str(lane.get("resume_after_read") or "theorize")
            lane["resume_after_read"] = None
            lane["status"] = resume
            self.store.event("engine", "lane_reading_done", lane=lane["id"], resume=resume,
                             cycle=lane["theory_cycle"])
        else:
            resume = lane.get("resume_after_read")
            lane["resume_after_read"] = None
            lane["status"] = str(resume or (
                "sketch" if lane.get("search_origin") in ("repair", "core_synthesis")
                and not lane.get("sketches_path") else "tournament"))

    def _apply_diagnose(self, task: dict) -> None:
        lane = self._lane_of(task["subject"])
        self._archive_seal(lane, "diagnosis_seal")
        lane["diagnosis_path"] = task["outputs"][0]
        lane["diagnosis_digest"] = evalid.json_file_digest(self.ctx(), task["outputs"][0])
        lane["diagnosis_seal"] = self._seal(
            [("diagnosis", task["outputs"][0])], revision=len(lane.get("seal_history") or []) + 1)
        lane["status"] = "deep_read"
        self.store.event("engine", "diagnosis_frozen", lane=lane["id"],
                         digest=lane["diagnosis_digest"])

    def _activate_survivor(self, lane: dict, sketch_id: str) -> None:
        """Atomically make one sealed, ranked survivor the active candidate."""
        lane["winner_sketch"] = sketch_id
        wsk = self.ctx().winner_sketch(lane) or {}
        if not wsk:
            raise SystemExit(f"[evo] ranked survivor {sketch_id!r} is absent from the sealed program set")
        lane["winner_program_digest"] = eprogram.candidate_digest(wsk)
        lane["winner_kernel_hash"] = eprogram.kernel_fingerprint(wsk)
        # The winner's COMPLETE record in its own file, so winner-only
        # stages (pose/theorize/challenge/mature) never re-read the whole
        # 4-program batch (~3/4 dead content, 4-6K tok per lifecycle); the
        # engine keeps validating against the sealed original, only the
        # agent-facing input slims. The batch and tournament stay on disk and
        # remain listed as reference paths.
        tj = eutil.read_json(eutil.rpath(self.store.repo, lane.get("tournament_path") or ""), {}) or {}
        winner_audit = next((a for a in (tj.get("audits") or [])
                             if isinstance(a, dict) and a.get("sketch_id") == sketch_id), {})
        eutil.write_json_atomic(
            eutil.rpath(self.store.repo,
                        f".evo/rounds/{lane.get('round')}/lanes/{lane.get('id')}/WINNER.json"),
            {"lane": lane.get("id"), "sketch_id": sketch_id,
             "program_set_digest": lane.get("program_set_digest"),
             "winner_program_digest": lane.get("winner_program_digest"),
             "sketch": wsk,
             "audit": winner_audit,
             # Honest empty-marker: an input row promising "winner + its audit"
             # must not silently deliver {} when the tournament lacks the row.
             "audit_missing": not bool(winner_audit),
             "full_batch": lane.get("sketches_path"),
             "full_tournament": lane.get("tournament_path")})
        lane["cycles"]["mature"] = 0
        role = str(wsk.get("theory_role") or "none")
        lane["theory_claim_status"] = ("not_claimed" if role == "none" else
                                         ("supported" if lane.get("search_origin") == "theory_derived"
                                          else "pending"))
        if lane.get("search_origin") == "theory_derived":
            # The program instantiates the already-surviving source theorem;
            # each survivor therefore goes straight to maturation.
            lane["status"] = "mature"
        elif role != "none":
            lane["theory_required"] = True
            lane["theory_downgraded"] = False
            formal = role == "derivational"
            lane["formal"] = formal
            lane["formal_kind"] = str(wsk.get("theory_rigor") or "partial") if formal else None
            if formal:
                lane["status"] = "pose"
                self.store.event("engine", "lane_formal", lane=lane["id"],
                                 theory_rigor=lane["formal_kind"])
            else:
                lane["theory_cycle"] = int(lane.get("theory_cycle") or 0) + 1
                lane["status"] = "theorize"
        else:
            lane["theory_required"] = False
            lane["theory_claim_status"] = "not_claimed"
            lane["theory_downgraded"] = False
            lane["formal"] = False
            lane["formal_kind"] = None
            lane["status"] = "mature"

    def _next_ranked_survivor(self, lane: dict) -> str | None:
        tournament = self._spec_from(str(lane.get("tournament_path") or ""))
        ranked = [str((row or {}).get("sketch_id") or "")
                  for row in (tournament.get("survivor_ranking") or [])
                  if isinstance(row, dict)]
        current = str(lane.get("winner_sketch") or "")
        try:
            position = ranked.index(current)
        except ValueError:
            return None
        return ranked[position + 1] if position + 1 < len(ranked) else None

    def _advance_ranked_survivor(self, lane: dict, *, verdict: str,
                                 review: str | None) -> bool:
        """Retire one candidate but keep its sealed batch alive for rank fallback."""
        next_id = self._next_ranked_survivor(lane)
        if not next_id:
            return False
        previous = str(lane.get("winner_sketch") or "")
        self._supersede_idea_revision(lane, verdict=verdict, review=review)
        self._reset_post_program_theory(lane)
        self._activate_survivor(lane, next_id)
        self.store.event("engine", "ranked_survivor_activated", lane=lane["id"],
                         rejected=previous, verdict=verdict, survivor=next_id)
        return True

    def _append_tombstone(self, lane: dict, *, criterion: str, source: dict,
                          note: str | None = None) -> str:
        """Bank a published-territory boundary from a collision death.

        The tombstone is the ONE cross-lane learning channel for idea-level
        deaths: an anonymous absorption criterion plus fixed semantics. It is
        consumed by the ROUND STRATEGIST only (who may quote the criterion
        into an overlapping lane's forbidden moves); generator inputs never
        change - blindness is preserved, anchoring is a strategist judgment.

        Idempotent on the normalized criterion: a same-batch second kill on
        the same territory, or a crash-window replay of this apply, must not
        grow the ledger - the boundary is a set, not a tally."""
        path = eutil.rpath(self.store.repo, ".evo/evidence/TOMBSTONES.jsonl")
        # lenient: a torn append must not brick the next banking; the partial
        # line is doctor's to report, the parseable rows drive dedupe/max-id.
        rows = [r for r in eutil.read_jsonl(path, lenient=True) if isinstance(r, dict)]
        norm = " ".join(str(criterion).split()).casefold()
        for r in rows:
            if " ".join(str(r.get("criterion") or "").split()).casefold() == norm:
                self.store.event("engine", "tombstone_duplicate_skipped",
                                 tombstone=str(r.get("id")), lane=lane.get("id"))
                return str(r.get("id"))
        nums = [int(m.group(1)) for r in rows
                if (m := re.fullmatch(r"TB(\d+)", str(r.get("id") or "")))]
        tb_id = f"TB{(max(nums) + 1) if nums else 1:03d}"
        eutil.append_jsonl(path, {
            "id": tb_id,
            "criterion": str(criterion).strip(),
            "semantics": "published territory: illegal as a claimed novelty kernel, legal as a known "
                         "component/support shell; beyond the criterion this tombstone asserts nothing",
            "context": {"round": lane.get("round"), "lane": lane.get("id"),
                        "intent": lane.get("intent"), "search_origin": lane.get("search_origin"),
                        "bottlenecks": list(lane.get("bottleneck_ids") or [])},
            "source": source,
            "note": (str(note).strip() if note else None),
            "created_at": eutil.utc_now()})
        self.store.event("engine", "tombstone_recorded", tombstone=tb_id, lane=lane.get("id"))
        return tb_id

    def _bank_tombstone_from_review(self, lane: dict, review: str) -> None:
        target = next(iter(evalid.DUPLICATE_TARGET_RE.findall(review or "")), "")
        if not target.startswith("CA"):
            # Graph-internal duplicate (N###): the kernel-fingerprint block
            # already owns that territory mechanically; no tombstone.
            return
        crit = next(iter(evalid.TOMBSTONE_LINE_RE.findall(review or "")), "")
        if not crit:
            # The validator enforces the line; a review that somehow lacks
            # one stays silent rather than half-banked.
            return
        if evalid._TOMBSTONE_KNOWN_RE.fullmatch(crit):
            # `TOMBSTONE: TB###` re-cites territory an existing tombstone
            # already bounds - record the re-hit, grow nothing.
            self.store.event("engine", "tombstone_known_hit", lane=lane.get("id"),
                             tombstone=crit, source="red_team")
            return
        note = next(iter(evalid.TOMBSTONE_NOTE_RE.findall(review or "")), None)
        self._append_tombstone(lane, criterion=crit,
                               source={"kind": "red_team", "idea": lane.get("idea"), "ca": target},
                               note=note)

    def _bank_tournament_tombstones(self, lane: dict, tj: dict, path: str) -> None:
        """Bank every kill-side boundary a validated tournament declared.

        Validation guarantees shape; this only routes: new criterion -> ledger
        (idempotent), known_tombstone -> re-hit event, decisive=false -> the
        collision was not the kill ground, so there is no boundary to bank."""
        for t_audit in (tj.get("audits") or []):
            t_pdup = (t_audit or {}).get("published_dup") if isinstance(t_audit, dict) else None
            if not isinstance(t_pdup, dict):
                continue
            if t_pdup.get("decisive") is False:
                self.store.event("engine", "tombstone_waived_not_decisive", lane=lane.get("id"),
                                 sketch=t_audit.get("sketch_id"), ca=t_pdup.get("ca"))
            elif t_pdup.get("tombstone"):
                self._append_tombstone(
                    lane, criterion=str(t_pdup["tombstone"]),
                    source={"kind": "tournament", "sketch": t_audit.get("sketch_id"),
                            "ca": t_pdup.get("ca"), "path": path})
            elif t_pdup.get("known_tombstone"):
                self.store.event("engine", "tombstone_known_hit", lane=lane.get("id"),
                                 tombstone=str(t_pdup["known_tombstone"]),
                                 sketch=t_audit.get("sketch_id"))

    def _apply_tournament(self, task: dict) -> None:
        lane = self._lane_of(task["subject"])
        lane["tournament_path"] = task["outputs"][0]
        lane["tournament_seal"] = self._seal(
            [("tournament", task["outputs"][0])],
            upstream=[str((lane.get("program_seal") or {}).get("digest") or "")],
            revision=int(lane.get("attempt_seq") or 1))
        tj = self._spec_from(task["outputs"][0])
        self._bank_tournament_tombstones(lane, tj, task["outputs"][0])
        winners = tj.get("winners") or []
        if winners:
            self._activate_survivor(lane, str(winners[0]))
        else:
            lane.setdefault("attempts", []).append({
                "program_set": lane.get("sketches_path"),
                "program_set_digest": lane.get("program_set_digest"),
                "program_seal": (lane.get("program_seal") or {}).get("digest"),
                "tournament": task["outputs"][0],
                "tournament_seal": (lane.get("tournament_seal") or {}).get("digest"),
                "verdict": "all_killed",
            })
            self._archive_seal(lane, "program_seal")
            self._archive_seal(lane, "tournament_seal")
            lane["sketches_path"] = None
            lane["program_set_digest"] = None
            lane["tournament_path"] = None
            lane["cycles"]["sketch"] += 1
            if lane["cycles"]["sketch"] >= int(self.cfg["budgets"].get("max_attempts", 3)):
                failure_summary = self._sketch_failure_summary(lane)
                if self.cfg.get("policy", {}).get("on_stuck") == "abandon":
                    self._abandon_lane(lane, f"sketch/resynthesis budget exhausted: {failure_summary}")
                else:
                    self.store.new_gate(self.st, "escalation", {"lane": lane["id"], "resume_stage": "sketch"},
                                        self._sketch_escalation_message(lane))
                    lane["status"] = "sketch"
            else:
                lane["status"] = "sketch"
                self.store.event("engine", "lane_resketch", lane=lane["id"], cycle=lane["cycles"]["sketch"])

    def _apply_challenge(self, task: dict) -> None:
        lane = self._lane_of(task["subject"])
        review = eutil.read_text(eutil.rpath(self.store.repo, task["outputs"][0]))
        m = REVIEW_VERDICT_RE.search(review)
        verdict = m.group(1) if m else "REVISE"
        artifacts = [("theory", str(lane.get("theory_path") or "")),
                     ("challenge", task["outputs"][0])]
        if lane.get("problem_path"):
            artifacts.insert(0, ("posed_problem", str(lane["problem_path"])))
        upstream = [str((lane.get("problem_seal") or {}).get("digest") or ""),
                    str((lane.get("program_seal") or {}).get("digest") or "")]
        reviewed_seal = self._seal(artifacts, upstream=upstream,
                                   revision=int(lane.get("theory_seq") or 1))
        self._archive_seal(lane, "theory_draft_seal")
        lane["theory_head_ready"] = True
        self.store.event("agent", "challenge_verdict", lane=lane["id"], cycle=lane.get("theory_cycle"),
                         verdict=verdict)
        if verdict == "PROCEED":
            self._archive_seal(lane, "theory_seal")
            lane["theory_seal"] = reviewed_seal
            lane["theory_claim_status"] = "supported"
            lane["status"] = ("sketch" if lane.get("search_origin") == "theory_derived"
                              and not lane.get("sketches_path") else "mature")
            return
        # Keep the rejected/revision-requested attempt active until the next
        # theory revision supersedes it; a downgraded optional T still cites
        # this exact negative result at maturation.
        lane["theory_draft_seal"] = reviewed_seal
        lane["cycles"]["theory"] += 1
        exhausted = lane["cycles"]["theory"] >= int(self.cfg["budgets"].get("theory_cycles_max", 3))
        if exhausted:
            # Optional T is independent of an already-audited M/E program.  A
            # failed post-program theory is retained as a negative result and
            # removed from the final claim.  A theory-derived program cannot be
            # downgraded because its executable obligations came from T.
            if lane.get("search_origin") != "theory_derived" and lane.get("winner_sketch"):
                lane["theory_claim_status"] = "failed"
                lane["theory_downgraded"] = True
                lane["theory_required"] = False
                lane["formal"] = False
                lane["formal_kind"] = None
                lane["status"] = "mature"
                self.store.event("engine", "theory_claim_downgraded", lane=lane["id"],
                                 theory=lane.get("theory_path"), cycles=lane["cycles"]["theory"])
                return
            if self.cfg.get("policy", {}).get("on_stuck") == "abandon":
                self._abandon_lane(lane, f"theory could not survive challenge after {lane['cycles']['theory']} cycles")
            else:
                self.store.new_gate(self.st, "escalation", {
                    "lane": lane["id"], "resume_stage": "theorize",
                    "winner_program_digest": lane.get("winner_program_digest")},
                                    f"Lane {lane['id']}: theory still {verdict} after "
                                    f"{lane['cycles']['theory']} challenge cycles. Approve to retry with reset cycles, reject to abandon.")
                lane["status"] = "theorize"
            return
        if verdict == "READ":
            topics = [t.strip() for t in TOPIC_LINE_RE.findall(review) if t.strip()]
            lane["required_topics"] = topics
            lane["resume_after_read"] = "theorize"
            lane["status"] = "deep_read"
            self.store.event("engine", "lane_reading_required", lane=lane["id"], topics=topics)
        elif verdict == "FORMALIZE":
            # the critic found a precise claim hiding in prose: the lane enters
            # the formal ladder - pose the problem, then re-derive as a chain
            lane["formal"] = True
            # critic-forced formalization defaults to 'partial': the toy-check
            # duty binds only lanes that CLAIMED full formalizability themselves
            lane["formal_kind"] = lane.get("formal_kind") or "partial"
            lane["status"] = "pose"
            self.store.event("engine", "lane_formalize_required", lane=lane["id"])
        else:  # REVISE
            lane["theory_cycle"] = int(lane.get("theory_cycle") or 0) + 1
            lane["status"] = "theorize"

    def _prepare_resynthesis(self, lane: dict, *, verdict: str,
                             review: str | None = None, note: str | None = None,
                             gate: str | None = None) -> None:
        """Archive one rejected scientific contract and atomically reopen search.

        A post-program theory belongs to that exact winner and is reset. A
        theory-derived lane keeps its pre-program theorem and DO# obligations,
        which are the source contract for every replacement program.
        """
        lane.setdefault("attempts", []).append({
            "program_set": lane.get("sketches_path"),
            "program_set_digest": lane.get("program_set_digest"),
            "program_seal": (lane.get("program_seal") or {}).get("digest"),
            "tournament": lane.get("tournament_path"),
            "tournament_seal": (lane.get("tournament_seal") or {}).get("digest"),
            "winner": lane.get("winner_sketch"),
            "winner_program_digest": lane.get("winner_program_digest"),
            "winner_kernel_hash": lane.get("winner_kernel_hash"),
            "idea": lane.get("idea"), "verdict": verdict,
            "review": review, "gate": gate, "note": note,
            "theory": lane.get("theory_path"),
            "problem": lane.get("problem_path"),
            "theory_claim_status": lane.get("theory_claim_status"),
            "theory_seal": (lane.get("theory_seal") or lane.get("theory_draft_seal") or {}).get("digest"),
            "idea_seal": (lane.get("idea_seal") or {}).get("digest"),
            "review_seal": (lane.get("review_seal") or {}).get("digest"),
        })
        self._supersede_idea_revision(lane, verdict=verdict, review=review)
        self._archive_seal(lane, "program_seal")
        self._archive_seal(lane, "tournament_seal")
        lane["sketches_path"] = None
        lane["program_set_digest"] = None
        lane["tournament_path"] = None
        lane["winner_sketch"] = None
        lane["winner_program_digest"] = None
        lane["winner_kernel_hash"] = None
        self._reset_post_program_theory(lane)
        lane["cycles"]["sketch"] += 1
        lane["cycles"]["mature"] = 0

    def _reopen_winner_theory(self, lane: dict, *, retry_stage: str) -> None:
        """Give a frozen winner a fresh T audit without changing its M/E core."""
        winner = self.ctx().winner_sketch(lane) or {}
        role = str(winner.get("theory_role") or "none")
        if role == "none":
            raise SystemExit("[evo] this winner froze theory_role='none'; retry sketch to change the "
                             "scientific contract rather than attaching post-selection theory")
        if retry_stage == "pose" and role != "derivational":
            raise SystemExit("[evo] pose is legal only for a winner that precommitted derivational theory")
        lane["theory_required"] = True
        self._archive_seal(lane, "theory_seal")
        self._archive_seal(lane, "theory_draft_seal")
        lane["theory_head_ready"] = False
        lane["theory_claim_status"] = "pending"
        lane["theory_downgraded"] = False
        lane["formal"] = role == "derivational"
        lane["formal_kind"] = (str(winner.get("theory_rigor") or "partial")
                               if role == "derivational" else None)
        lane["cycles"]["theory"] = 0
        lane["required_topics"] = []
        lane["resume_after_read"] = None
        if retry_stage == "pose":
            lane["problem_path"] = None
            lane["theory_path"] = None
            self._archive_seal(lane, "problem_seal")
            lane["theory_cycle"] = 0
        else:
            lane["theory_cycle"] = int(lane.get("theory_cycle") or 0) + 1
        lane["status"] = retry_stage

    def _apply_red_team(self, task: dict) -> None:
        lane = self._lane_of(task["subject"])
        review = eutil.read_text(eutil.rpath(self.store.repo, task["outputs"][0]))
        m = REVIEW_VERDICT_RE.search(review)
        verdict = m.group(1) if m else "REVISE"
        self._archive_seal(lane, "review_seal")
        lane["review_seal"] = self._seal(
            [("red_team_review", task["outputs"][0])],
            upstream=[str((lane.get("idea_seal") or {}).get("digest") or "")],
            revision=len(lane.get("idea_revisions") or []) + 1)
        self.store.event("agent", "red_team_verdict", lane=lane["id"], idea=lane.get("idea"), verdict=verdict)
        if verdict == "ACCEPT":
            lane["status"] = "gate"
        elif verdict == "REVISE":
            lane["cycles"]["mature"] += 1
            if lane["cycles"]["mature"] >= int(self.cfg["budgets"].get("max_attempts", 3)):
                if self.cfg.get("policy", {}).get("on_stuck") == "abandon":
                    self._abandon_lane(lane, "idea could not satisfy red team after repeated revision")
                else:
                    self.store.new_gate(self.st, "escalation", {
                        "lane": lane["id"], "resume_stage": "mature",
                        "winner_program_digest": lane.get("winner_program_digest")},
                                        f"Lane {lane['id']}: idea {lane.get('idea')} still REVISE after "
                                        f"{lane['cycles']['mature']} maturation cycles. Approve to retry, reject to abandon.")
                    self._supersede_idea_revision(lane, verdict=verdict, review=task["outputs"][0])
                    lane["status"] = "mature"
            else:
                self._supersede_idea_revision(lane, verdict=verdict, review=task["outputs"][0])
                lane["status"] = "mature"
        else:  # any REJECT_*
            if verdict == "REJECT_DUPLICATE":
                self._bank_tombstone_from_review(lane, review)
            if self._advance_ranked_survivor(
                    lane, verdict=verdict, review=task["outputs"][0]):
                return
            self._prepare_resynthesis(lane, verdict=verdict, review=task["outputs"][0])
            if lane["cycles"]["sketch"] >= int(self.cfg["budgets"].get("max_attempts", 3)):
                failure_summary = self._sketch_failure_summary(lane)
                if self.cfg.get("policy", {}).get("on_stuck") == "abandon":
                    self._abandon_lane(lane, f"sketch/resynthesis budget exhausted: {failure_summary}")
                else:
                    self.store.new_gate(self.st, "escalation", {"lane": lane["id"], "resume_stage": "sketch"},
                                        self._sketch_escalation_message(lane))
                    lane["status"] = "sketch"
            else:
                lane["status"] = "sketch"

    def _apply_review_ablation(self, task: dict) -> None:
        """A diagnostic is either causally useful, revised in place, or killed.

        It never falls back into sketch/tournament: that would turn a question
        about existing evidence into an unrelated novelty search.
        """
        lane = self._lane_of(task["subject"])
        review = eutil.read_text(eutil.rpath(self.store.repo, task["outputs"][0]))
        m = REVIEW_VERDICT_RE.search(review)
        verdict = m.group(1) if m else "REVISE"
        self._archive_seal(lane, "review_seal")
        lane["review_seal"] = self._seal(
            [("ablation_review", task["outputs"][0])],
            upstream=[str((lane.get("idea_seal") or {}).get("digest") or "")],
            revision=len(lane.get("idea_revisions") or []) + 1)
        self.store.event("agent", "ablation_review_verdict", lane=lane["id"], idea=lane.get("idea"),
                         verdict=verdict)
        if verdict == "ACCEPT":
            lane["status"] = "gate"
            return
        if verdict.startswith("REJECT_"):
            self._abandon_lane(lane, f"targeted ablation rejected before compute ({verdict})")
            return
        lane["cycles"]["ablation"] = int(lane["cycles"].get("ablation") or 0) + 1
        if lane["cycles"]["ablation"] >= int(self.cfg["budgets"].get("max_attempts", 3)):
            if self.cfg.get("policy", {}).get("on_stuck") == "abandon":
                self._abandon_lane(lane, "causal diagnostic could not satisfy review after repeated revision")
            else:
                self.store.new_gate(
                    self.st, "escalation", {"lane": lane["id"], "resume_stage": "ablation_design"},
                    f"Lane {lane['id']}: targeted ablation {lane.get('idea')} still needs revision after "
                    f"{lane['cycles']['ablation']} cycles. Approve to redesign, reject to abandon without compute.")
                self._supersede_idea_revision(lane, verdict=verdict, review=task["outputs"][0])
                lane["status"] = "ablation_design"
        else:
            self._supersede_idea_revision(lane, verdict=verdict, review=task["outputs"][0])
            lane["status"] = "ablation_design"

    def _apply_maintenance_review(self, task: dict) -> None:
        """Maintenance is repaired plumbing, not smuggled novelty: the review
        either accepts the parity-contracted change, revises it in place, or
        kills it before compute. It never enters the novelty pipeline."""
        lane = self._lane_of(task["subject"])
        review = eutil.read_text(eutil.rpath(self.store.repo, task["outputs"][0]))
        m = REVIEW_VERDICT_RE.search(review)
        verdict = m.group(1) if m else "REVISE"
        self._archive_seal(lane, "review_seal")
        lane["review_seal"] = self._seal(
            [("maintenance_review", task["outputs"][0])],
            upstream=[str((lane.get("idea_seal") or {}).get("digest") or "")],
            revision=len(lane.get("idea_revisions") or []) + 1)
        self.store.event("agent", "maintenance_review_verdict", lane=lane["id"],
                         idea=lane.get("idea"), verdict=verdict)
        if verdict == "ACCEPT":
            lane["status"] = "gate"
            return
        if verdict.startswith("REJECT_"):
            self._abandon_lane(lane, f"maintenance rejected before compute ({verdict})")
            return
        lane["cycles"]["ablation"] = int(lane["cycles"].get("ablation") or 0) + 1
        if lane["cycles"]["ablation"] >= int(self.cfg["budgets"].get("max_attempts", 3)):
            if self.cfg.get("policy", {}).get("on_stuck") == "abandon":
                self._abandon_lane(lane, "maintenance design could not satisfy review after repeated revision")
            else:
                self.store.new_gate(
                    self.st, "escalation", {"lane": lane["id"], "resume_stage": "maintenance_design"},
                    f"Lane {lane['id']}: maintenance {lane.get('idea')} still needs revision after "
                    f"{lane['cycles']['ablation']} cycles. Approve to redesign, reject to abandon without compute.")
                self._supersede_idea_revision(lane, verdict=verdict, review=task["outputs"][0])
                lane["status"] = "maintenance_design"
        else:
            self._supersede_idea_revision(lane, verdict=verdict, review=task["outputs"][0])
            lane["status"] = "maintenance_design"

    def _apply_plan_node(self, task: dict) -> None:
        lane = self._lane_of(task["subject"])
        spec_src = task["outputs"][0]
        spec = self._spec_from(spec_src)
        nid = self.store.next_id(self.st, "N")
        node_spec_path = f".evo/nodes/{nid}/NODE_SPEC.json"
        eutil.write_json_atomic(eutil.rpath(self.store.repo, node_spec_path), spec)
        meta = self._spec_from(f".evo/ideas/{lane['idea']}.meta.json")
        node = egraph.new_node(
            self.g, nid, title=spec.get("title") or f"Node {nid}", role=spec["role"],
            parents=list(spec.get("parents") or []), code_parent=spec.get("code_parent"),
            level=int(spec.get("level") or 0), lane=lane["id"], round_=lane["round"],
            idea_doc=f".evo/ideas/{lane['idea']}.md", spec=node_spec_path,
            experiment_purpose=str(meta.get("experiment_purpose") or "candidate"))
        node["workdir"] = spec.get("workdir")
        node["idea_contract_digest"] = self._idea_contract_digest(lane)
        node["spec_revision"] = 1
        plan_spec_artifacts = [("node_spec", node_spec_path)]
        plan_protocol = ((spec.get("eval") or {}).get("protocol") or {})
        if isinstance(plan_protocol, dict) and str(plan_protocol.get("episode_order_file") or ""):
            plan_spec_artifacts.append(("episode_order", str(plan_protocol["episode_order_file"])))
        node["spec_seal"] = self._seal(
            plan_spec_artifacts, upstream=[node["idea_contract_digest"]], revision=1)
        node["seal_history"] = []
        node["program_digest"] = meta.get("program_digest")
        node["kernel_hash"] = meta.get("kernel_hash")
        node["kernel_ids"] = eprogram.kernel_ids(meta)
        # The once-per-registration duplicate guards scan lanes
        # AND nodes; without these copies the node half was dead code and the
        # guarantee rested entirely on lanes never being archived.
        lane_row = self.store.get_lane(self.st, str(node.get("lane") or "")) or {}
        for copy_field in ("scaling_followup_of", "confirmatory_of"):
            if lane_row.get(copy_field):
                node[copy_field] = str(lane_row[copy_field])
        node["operator_ids"] = sorted({str(op) for row in eprogram.kernel_components(meta)
                                       for op in (row.get("operator_refs") or [])})
        # Freeze the beaten SOTA numbers at node creation -
        # the registered beat-claim must settle against the line as it stood
        # when the claim was made, not against a later in-place ledger rewrite.
        sota_rows = {str(r.get("id") or ""): r for r in eutil.read_jsonl(
            eutil.rpath(self.store.repo, ".evo/evidence/SOTA.jsonl"), lenient=True)
            if isinstance(r, dict)}
        frozen_sota = {}
        for t in (meta.get("sota_targets") or []):
            tid = str((t or {}).get("sota") or "")
            hv = ((sota_rows.get(tid) or {}).get("headline") or {}).get("value")
            if isinstance(hv, (int, float)) and not isinstance(hv, bool):
                frozen_sota[tid] = float(hv)
        if frozen_sota:
            node["sota_targets_frozen"] = frozen_sota
        declared_comparator = str(((meta.get("effect_case") or {}).get("comparator_id") or ""))
        if declared_comparator:
            if declared_comparator == "baseline":
                baseline = next((row for row in self.g.get("nodes", [])
                                 if row.get("role") == "baseline"), None)
                if baseline is None:
                    raise SystemExit("[evo] approved effect contract names baseline but no baseline node exists")
                node["effect_comparator_node"] = str(baseline["id"])
            else:
                node["effect_comparator_node"] = declared_comparator
        node["search_origin"] = lane.get("search_origin")
        # Freeze WHICH bytes each consumed shared
        # artifact meant at plan time. The spec stores only the logical AR id;
        # a producer fix could re-generate the same id in place and this
        # consumer would silently read different bytes (or the registry would
        # later claim it had). Launch re-checks these bindings.
        bindings: dict[str, dict] = {}
        by_id = eartifact.by_id(self.reg)
        for stg in econfig.stages_of(spec):
            for c in (stg.get("consumes") or []):
                aid = str((c or {}).get("artifact") or "") if isinstance(c, dict) else ""
                art = by_id.get(aid)
                if art is not None:
                    bindings[aid] = {"generation": art.get("generation"),
                                     "content_digest": str(art.get("content_digest") or "")}
        if bindings:
            node["artifact_bindings"] = bindings
        node["needs_metric_bridge"] = bool(meta.get("metric_bridge_needed"))
        # Fidelity follows a claimed research kernel (or a heavy workflow), not
        # implementation breadth.  A local irreducible law needs this audit;
        # a broad engineering composition does not acquire novelty duties.
        is_ablation = node.get("experiment_purpose") == "targeted_ablation"
        research_kernel = str((meta.get("novelty") or {}).get("kind") or "") in eprogram.RESEARCH_NOVELTY
        node["needs_fidelity"] = not is_ablation and (research_kernel or spec.get("cost_class") == "heavy")
        node["fidelity_pending"] = node["needs_fidelity"]
        node["ablation_fidelity_pending"] = is_ablation
        node["stage_cursor"] = 0
        node["replica_index"] = 0
        node["replicas_completed"] = []
        node["status"] = "approved"
        if self._git_mode():
            node["branch"] = f"evo/{nid.lower()}-{eutil.slug(spec.get('title') or nid, 24)}"
        lane["node"] = nid
        lane["status"] = "node_created"
        self.store.event("engine", "node_created", node=nid, role=spec["role"], lane=lane["id"],
                         parents=node["parents"], level=node["level"],
                         program_digest=node.get("program_digest"), kernel_ids=node.get("kernel_ids"),
                         operator_ids=node.get("operator_ids"),
                         experiment_purpose=node["experiment_purpose"])

    def _apply_eval_launch(self, task: dict) -> None:
        node = self.node(task["subject"]["node"])
        data = self._spec_from(task["outputs"][0])
        run = self.store.get_run(self.st, str(task["subject"].get("run") or ""))
        if run is None:
            raise SystemExit("[evo] eval launch lost its engine-prepared RUN")
        if data.get("mode") == "completed":
            if str(run.get("evidence_status") or "") == "complete":
                # The terminal sealed package is immutable; the validator
                # enforced byte identity, so this launch only confirms and
                # re-absorbs (adopting a quarantined pre-launch package).
                node["status"] = "evaluating"
                run["absorbed"] = False
                self._absorb_run(run)
                egraph.touch(node)
                return
            metrics_file = str(data.get("metrics_file") or "")
            run["metrics_file"] = metrics_file
            erun.transition_execution(run, "finished", job=str(data.get("job") or "") or None,
                                      note="completed producer reported by launch task")
            node["status"] = "evaluating"
            run["absorbed"] = False
            self._absorb_run(run)
        else:
            node["status"] = "evaluating"
            if erun.is_terminal(run):
                erun.transition_execution(run, str(run.get("status")), job=str(data.get("job") or ""),
                                          note="terminal evaluator reconciled with launch task")
                run["absorbed"] = False
                self._absorb_run(run)
            else:
                erun.transition_execution(run, "running", job=str(data.get("job") or ""),
                                          note="background evaluator bound by launch task")
        egraph.touch(node)

    def _apply_stage_launch(self, task: dict) -> None:
        node = self.node(task["subject"]["node"])
        data = self._spec_from(task["outputs"][0])
        spec = self._spec(node)
        run = self.store.get_run(self.st, str(task["subject"].get("run") or ""))
        if run is None:
            raise SystemExit("[evo] stage launch lost its engine-prepared RUN")
        # The launch happened: a busy-resources escalation still waiting for
        # the user's word is moot and closes here, or it would sit open as a
        # decision about a wait that ended.
        for gate in self.st.get("gates", []):
            subj = gate.get("subject") or {}
            if gate.get("kind") == "escalation" and gate.get("status") in ("open", "paused")                     and subj.get("reason") == "resources_busy" and subj.get("task") == task["id"]:
                gate["status"] = "cancelled"
                gate["resolved_at"] = eutil.utc_now()
                gate["note"] = f"superseded: the launch for {run['id']} happened"
                gate["held_by"] = []
                self.store.event("engine", "gate_cancelled", gate=gate["id"],
                                 reason="launch_happened_after_busy_wait", task=task["id"])
        # What the launch actually did is a record beside the run and the node:
        # how many accelerators it holds, and what it changed from the plan
        # (fewer devices, another batch, another precision). Never a veto and
        # never a comparability judgment - the resource axes carry that.
        devices = data.get("devices")
        if isinstance(devices, int) and not isinstance(devices, bool) and devices > 0:
            run["devices"] = devices
        deviation = str(data.get("deviation") or "").strip()
        if deviation:
            run["launch_deviation"] = deviation[:300]
            node.setdefault("launch_deviations", []).append({
                "run": run["id"], "stage": str(task["subject"].get("stage") or ""),
                "devices": run.get("devices"), "note": deviation[:300], "at": eutil.utc_now()})
        if run.get("repeat_measure_attempt"):
            # The repeat lane's authoritative seed is the pending
            # buy-back seed, not a preplanned replica lane
            replica_seed = node.get("repeat_pending_seed")
        else:
            replica_index = int(node.get("replica_index") or 0)
            replica_seed = econfig.workflow_seed(spec, replica_index)
        if data.get("seed") != replica_seed:
            raise SystemExit(f"[evo] stage launch seed changed after validation: expected {replica_seed!r}, "
                             f"got {data.get('seed')!r}")
        if data.get("mode") == "completed":
            if str(run.get("evidence_status") or "") == "complete":
                # Same terminal-package immutability as the eval branch.
                node["status"] = "executing"
                run["absorbed"] = False
                self._absorb_run(run)
                egraph.touch(node)
                return
            metrics_file = str(data.get("metrics_file") or "")
            run["metrics_file"] = metrics_file
            run["ledger_file"] = data.get("ledger_file")
            erun.transition_execution(run, "finished", job=str(data.get("job") or "") or None,
                                      note="completed producer reported by launch task")
            node["status"] = "executing"
            run["absorbed"] = False
            self._absorb_run(run)
        else:
            if str(run.get("evidence_status") or "") != "complete":
                # Never redirect a terminal-sealed RUN's ledger pointer -
                # a stale background card after a pre-launch reconcile could
                # otherwise re-ingest different bytes over the sealed package.
                run["ledger_file"] = data.get("ledger_file")
            node["status"] = "executing"
            if erun.is_terminal(run):
                erun.transition_execution(run, str(run.get("status")), job=str(data.get("job") or ""),
                                          note="terminal stage reconciled with launch task")
                run["absorbed"] = False
                self._absorb_run(run)
            else:
                # A launch card reopened after a hold (its RUN reset
                # to prepared meanwhile) skipped every slot check - accepting
                # it here could put a second background stage on a single-slot
                # platform. The card was minted under a slot check; re-prove
                # it at the point the slot is actually taken. SystemExit here
                # burns no attempt and the card stays open.
                if not erun.holds_external_slot(run) and self._slots_free() <= 0:
                    raise SystemExit(
                        "[evo] all workflow stage slots are busy; this launch card was reopened "
                        "after a pause and its slot is no longer free - settle a running stage "
                        "first ('evo run-update --run <RUN> ...' when it ends), then submit "
                        "this card again (it stays open; no attempt was spent)")
                erun.transition_execution(run, "running", job=str(data.get("job") or ""),
                                          note="background stage bound by launch task")
        egraph.touch(node)

    def _apply_conclude(self, task: dict) -> None:
        node = self.node(task["subject"]["node"])
        outcome = self._spec_from(task["outputs"][0])
        self._archive_seal(node, "conclusion_seal")
        node["conclusion_seal"] = self._seal(
            [("outcome", task["outputs"][0]), ("node_result", task["outputs"][1])],
            upstream=[str(node.get("idea_contract_digest") or ""),
                      str((node.get("spec_seal") or {}).get("digest") or ""),
                      str((node.get("eval_seal") or {}).get("digest") or "")],
            revision=int(node.get("conclusion_revision") or 0) + 1)
        node["conclusion_revision"] = node["conclusion_seal"]["revision"]
        node["outcome_path"] = task["outputs"][0]
        node["verdict"] = outcome.get("verdict")
        if node.get("role") not in ("baseline", "platform"):
            summary = node.get("evaluation_summary") or {}
            node["effect_contract_status"] = summary.get("effect_contract_status")
            node["scientific_promotion_status"] = summary.get("scientific_promotion_status")
            if str(outcome.get("verdict") or "") == "screened_out":
                # A stage-gate stop never has an evaluation_summary, so
                # promotion fell to None/agent phrasing. The unified rule
                # (promotion_status) counts screened_out as decided-against:
                # the pre-registered continuation criterion was missed.
                node["scientific_promotion_status"] = "blocked"
            if node.get("experiment_purpose") == "maintenance":
                # Engine-computed from the frozen assessment, never copied from
                # the analyst: parity is what licenses this node as a repaired
                # executable base for future lanes, and the gain is the audit
                # record of what the repair actually bought (it licenses
                # nothing - downstream candidates still measure against the
                # repaired base).
                node["maintenance_parity"] = evalid.maintenance_parity_status(summary)
                idx_gain = egraph.by_id(self.g)
                maint_parent = next(
                    (idx_gain[p] for p in (node.get("parents") or [])
                     if p in idx_gain and idx_gain[p].get("experiment_purpose") == "maintenance"),
                    None)
                node["maintenance_gain"] = evalid.maintenance_gain(
                    summary, (maint_parent or {}).get("maintenance_gain"))
        node["status"] = "concluded"
        node["result_doc"] = task["outputs"][1]
        if outcome.get("checkpoint"):
            node["checkpoint"] = outcome["checkpoint"]
        # Two facts. The causal status (did the kernel cause the gain) comes
        # from the engine's settlement: `deferred` for every model claim until
        # a targeted ablation settles it, `not_applicable` where there is no
        # kernel question. The probe's answer (does the trained model use the
        # part, by the frozen rule over sealed observations) is written beside
        # it as information - it decides nothing.
        summary = node.get("evaluation_summary") if isinstance(node.get("evaluation_summary"), dict) else {}
        outcome_mechanism = outcome.get("mechanism") if isinstance(outcome.get("mechanism"), dict) else {}
        node["mechanism_status"] = (str(summary.get("mechanism_contract_status") or "")
                                    or (outcome_mechanism.get("status") if node.get("role") in ("baseline", "platform")
                                        else None) or None)
        probe_status = str(summary.get("probe_contract_status") or "")
        if probe_status and probe_status != "not_registered":
            node["probe_result"] = {"status": probe_status, "at": eutil.utc_now(),
                                    "evidence": str(outcome_mechanism.get("evidence") or ""),
                                    "note": str(outcome_mechanism.get("note") or "")[:300]}
            # A probe reading is knowledge in its own right, ambiguous or not:
            # "the model wins and does not use the part" is a phenomenon the
            # next idea can cite, and the ablation designer's first lead.
            words = {"confirmed": "uses the part", "refuted": "does not use the part",
                     "unclear": "gives no clear reading on the part"}.get(probe_status, probe_status)
            probe_meta = (evalid._idea_meta(self.ctx(), node) or {}).get("mechanism_probe") or {}
            wins = ", ".join(str(c) for c in (summary.get("target_wins") or [])) or "no claimed cell"
            node["probe_result"]["observation"] = self.store.add_observation(self.st, {
                "statement": (f"{node['id']} (verdict {summary.get('verdict') or node.get('verdict') or '-'}, "
                              f"won {wins}) {words} by its registered probe: "
                              f"{str(probe_meta.get('signal') or 'registered signal')[:120]}"),
                "where": f"{node['id']} probe ({str(probe_meta.get('mode') or 'probe')})",
                "measurement": str(outcome_mechanism.get("note") or "")[:200] or "see the probe block of the metrics",
                "evidence": str(outcome_mechanism.get("evidence") or node.get("eval_metrics_path") or ""),
                "node": node["id"], "round": node.get("round"), "status": "open",
                "source": "engine", "kind": "probe_reading"})
            self.store.event("engine", "observation_recorded", id=node["probe_result"]["observation"],
                             node=node["id"], kind="probe_reading")
        # Only this node's still-open infrastructure ERs may be dispositioned:
        # the ledger is engine-owned, so a conclusion cannot close (or forge a
        # playbook entry for) another node's failure even if a validator path
        # ever missed it.
        pending = set(evalid.pending_infra_errors(self.ctx(), str(node.get("id") or "")))
        for row in (outcome.get("infra_resolutions") or []):
            if isinstance(row, dict) and str(row.get("error") or "") in pending:
                self._stage_error_resolution({
                    "resolves": str(row["error"]), "node": node["id"],
                    "disposition": str(row.get("disposition") or ""),
                    "surface": str(row.get("surface") or "") or None,
                    "fix": str(row.get("fix") or "") or None,
                })
        if node.get("experiment_purpose") == "targeted_ablation":
            node["ablation_result"] = dict(outcome.get("ablation_result") or {})
            self._settle_parent_mechanism_from_ablation(node)
        if node.get("role") == "platform" and outcome.get("enabled_services"):
            # dynamic service registry: consumer specs may now bind
            # requires_services to these names
            node["enabled_services"] = outcome["enabled_services"]
            self.store.event("engine", "platform_services_enabled", node=node["id"],
                             services=[str((s or {}).get("name")) for s in outcome["enabled_services"]])
        # Count REGISTERED predictions once each, never the raw array -
        # duplicate/invented rows passed the validator's registered-id loop
        # unvisited and inflated the cross-round calibration record.
        registered_ids = {str(p.get("id") or "")
                          for p in ((evalid._idea_meta(self.ctx(), node) or {}).get("predictions") or [])
                          if isinstance(p, dict)}
        preds_by_id: dict[str, dict] = {}
        for p in outcome.get("predictions") or []:
            pid = str((p or {}).get("id") or "") if isinstance(p, dict) else ""
            if pid in registered_ids and pid not in preds_by_id:
                preds_by_id[pid] = p
        preds = list(preds_by_id.values())
        if preds:
            node["prediction_stats"] = {
                "confirmed": sum(1 for p in preds if p.get("verdict") == "confirmed"),
                "refuted": sum(1 for p in preds if p.get("verdict") == "refuted"),
                "inconclusive": sum(1 for p in preds if p.get("verdict") == "inconclusive"),
                "unreached": 0,
            }
        elif outcome.get("unreached_predictions"):
            node["prediction_stats"] = {
                "confirmed": 0, "refuted": 0, "inconclusive": 0,
                "unreached": len({str((p or {}).get("id") or "")
                                  for p in (outcome.get("unreached_predictions") or [])
                                  if isinstance(p, dict)} & registered_ids),
            }
        # Conclusion ORDER is a fact the graph never
        # recorded - the calibration "recent cohort" borrowed node insertion
        # order, which reverses whenever a later-created node concludes first
        # (routine with parallel lanes and slow external RUNs).
        seq = int(self.st.get("counters", {}).get("conclusion_seq") or 0) + 1
        self.st.setdefault("counters", {})["conclusion_seq"] = seq
        node["conclusion_seq"] = seq
        node["concluded_at"] = eutil.utc_now()
        egraph.touch(node)
        for l in outcome.get("lessons") or []:
            self.store.add_lesson(self.st, {
                "scope": l.get("scope"), "statement": l.get("statement"),
                "evidence": l.get("evidence"), "recommendation": l.get("recommendation"),
                "tags": l.get("tags") or [], "node": node["id"], "round": node.get("round"),
                "source_conclusion_digest": node["conclusion_seal"]["digest"],
                "source_conclusion_revision": node["conclusion_revision"],
            })
        # Phenomenon ledger - validated observations become OB### records
        # that future sketches can anchor diagnoses on and ideas can cite as
        # assumption sources. This is the supply line from execution back into
        # ideation (oral-tier method work is overwhelmingly phenomenon-first).
        for o in outcome.get("observations") or []:
            oid = self.store.add_observation(self.st, {
                "statement": o.get("statement"), "where": o.get("where"),
                "measurement": o.get("measurement"), "evidence": o.get("evidence"),
                "node": node["id"], "round": node.get("round"), "status": "open",
                "source_conclusion_digest": node["conclusion_seal"]["digest"],
                "source_conclusion_revision": node["conclusion_revision"],
            })
            self.store.event("engine", "observation_recorded", id=oid, node=node["id"])
        if node.get("lane"):
            lane = self.store.get_lane(self.st, node["lane"])
            if lane and lane["status"] != "abandoned":
                lane["status"] = "done"
                # Lane->done retires the lane's own
                # undecided proposals in the same transition (mirror of the
                # abandoned arm's cascade) - the lazy pre-present cancellation
                # covered abandon_request only by coincidence of surfacing
                # order, and any future lane-subject gate would outlive its
                # lane silently.
                for gate in self.st.get("gates", []):
                    if gate.get("status") in ("open", "paused") \
                            and (gate.get("subject") or {}).get("lane") == lane.get("id"):
                        gate["status"] = "cancelled"
                        gate["resolved_at"] = eutil.utc_now()
                        gate["note"] = "superseded: the lane finished before the decision"
                        self.store.event("engine", "gate_cancelled", gate=gate.get("id"),
                                         reason="lane_done", lane=lane.get("id"))
        self.store.event("engine", "node_concluded", node=node["id"], verdict=node["verdict"],
                         scores=node.get("scores", {}))
        # Advice that rides on the ACCEPTED output: the doors that matter at
        # this exact moment, so the agent learns them when they are usable.
        advice: list[str] = []
        if node.get("role") not in ("baseline", "platform") \
                and str(node.get("experiment_purpose") or "candidate") == "candidate":
            kernels = ", ".join(str(k) for k in (node.get("kernel_ids") or [])) or "its kernel"
            mech = str(node.get("mechanism_status") or "")
            if mech == "deferred" and node.get("scientific_promotion_status") == "met":
                advice.extend(self._open_inheritance_tax(node, kernels))
            elif mech in ("confirmed", "refuted", "unclear"):
                advice.append(
                    f"{node['id']}'s mechanism settled {mech} by its frozen rule. If the FORMULA behind "
                    "that rule is wrong (a unit mismatch, an imported constant - not a threshold you "
                    f"dislike), the symmetric channel is: write a proposal and run evo correct-instrument "
                    f"--node {node['id']} --proposal <file>; an independent session judges it and the "
                    "user decides. A wrong formula in a PASSING gate goes through the same door.")
        self._accept_advice = advice

    def _open_inheritance_tax(self, node: dict, kernels: str, *, opened_by: str = "conclude") -> list[str]:
        """A program-level win whose mechanism was never instrumented: open the
        targeted ablation now, while the checkpoints are warm. The design card
        and the gates do the rest; here the engine only makes sure the question
        is asked. `opened_by` records which engine moment opened it: the
        parent's conclusion, or a round going running with the tax pending.
        Returns the advice lines that ride on the ACCEPTED output."""
        nid = str(node.get("id") or "")
        multiple = econfig.ablation_budget_multiple(self.cfg)
        summary = node.get("evaluation_summary") or {}
        won = ", ".join(str(c) for c in (summary.get("target_wins") or [])) or "its claimed cells"
        if not econfig.is_research(self.cfg):
            # Engineering mode inherits programs on their measured numbers;
            # mechanism attribution is a research question, so the engine
            # spends nothing on it by itself. The door stays open to people.
            return [f"{nid} settled at program level with its mechanism DEFERRED (engineering mode: the "
                    f"engine opens no ablation; evo ablate --parent {nid} --question \"...\" stays open "
                    "to people). Inherit the program; do not cite its kernel as an established cause."]
        if multiple <= 0:
            return [f"{nid} settled at program level with its mechanism DEFERRED and stays that way: "
                    "evidence_policy.ablation.budget_multiple is 0, so the engine opens no ablation. "
                    "Inherit the program; do not cite its kernel as an established cause. To settle it "
                    "later: evo amend --path .evo/config.json --from <edited copy> --reason \"...\" "
                    f"raising the multiple, then evo ablate --parent {nid} --question \"...\"."]
        question = (f"Is {kernels} the cause of the gain {nid} measured on {won}? The effect settled "
                    f"at program level with the mechanism deferred; settle it with changed-component "
                    f"runs against {nid} as the untreated arm, sized within the allowance "
                    f"({multiple:g} x what {nid} cost).")
        try:
            lane = self.open_instrumental_lane(
                purpose="targeted_ablation", parent=nid, text=question,
                brief_title="Targeted ablation (inheritance tax on a program-level win)",
                name=f"ablate-{nid.lower()}", actor="engine", opened_by=opened_by)
        except SystemExit as exc:
            reason = str(exc).replace("[evo] ", "", 1)
            earlier = node.get("ablation_pending") if isinstance(node.get("ablation_pending"), dict) else {}
            node["ablation_pending"] = {"reason": reason[:400], "at": eutil.utc_now(),
                                        "question": question,
                                        "attempts": int(earlier.get("attempts") or 0) + 1}
            self.store.event("engine", "ablation_deferred_to_next_round", node=nid, reason=eutil.clip_words(reason, 240))
            return [f"{nid} settled at program level with its mechanism DEFERRED. The engine could not "
                    f"open its ablation now ({reason[:160]}); it is recorded as pending: the engine tries "
                    f"again when the next round goes running (or the hold lifts), and the open_round card "
                    f"lists it until then (evo ablate --parent {nid} opens it mid-round). Until it settles, "
                    f"inherit the program, never the story."]
        node["ablation_lane"] = lane["id"]
        node.pop("ablation_pending", None)
        return [f"{nid} settled at program level with its mechanism DEFERRED, so the engine opened ablation "
                f"lane {lane['id']} on it (the inheritance tax: {multiple:g} x what {nid} cost is "
                f"pre-authorized; a larger design waits for the user). Its design card is next in line. "
                f"Until it settles, inherit the program, never the story."]

    def _refuted_kernel_reading(self, parent: dict, ablation: dict) -> tuple[str, list[str], str]:
        """What a refuted kernel means for the parent's gain, by how much the
        parent changed - three different follow-ups:
        `paradigm`: a root / full rebuild - the program minus the kernel carries
        the gain; the paradigm works, try another kernel inside it.
        `unattributed`: a local change - the parent differed from its comparator
        by this kernel alone, so the measured gain is not the change's; re-measure
        before building on it and do not count it as progress.
        `shell`: the parent also changed other components - one of them carries
        the gain; the engine lists them (program IR, by content signature) as
        candidates for a follow-up ablation."""
        pid, aid = str(parent.get("id") or ""), str(ablation.get("id") or "")
        kernels = ", ".join(str(k) for k in (parent.get("kernel_ids") or [])) or "its kernel"
        meta = evalid._idea_meta(self.ctx(), parent) or {}
        scope = str(meta.get("change_scope") or "")
        if parent.get("role") == "root" or scope == "full_program":
            return ("paradigm", [],
                    f"{pid}'s gain does not come from {kernels} (ablation {aid} found no effect); the paradigm "
                    f"carries it. {aid} is the program without that story - build on it and try another "
                    f"kernel inside the paradigm.")
        if scope == "local":
            return ("unattributed", [],
                    f"{pid} differs from its comparator by {kernels} alone, and ablation {aid} found that "
                    f"{kernels} does not carry the gain: the measured improvement is unattributed (seed luck or "
                    "recipe drift). Re-measure before building on it (repeat measure door) and do not count it "
                    "as progress.")
        code_parent = self.node(str(parent.get("code_parent") or "")) or {}
        base_meta = evalid._idea_meta(self.ctx(), code_parent) if code_parent else {}
        base_sigs = set(eprogram.program_operator_signatures(base_meta).values()) if base_meta else set()
        kernel_sigs = eprogram.kernel_operator_signatures(meta)
        candidates: list[str] = []
        for row in ((meta.get("program") or {}).get("operators") or []):
            if not isinstance(row, dict) or not row.get("id"):
                continue
            sig = eprogram.operator_signature(row)
            if sig in kernel_sigs or sig in base_sigs:
                continue
            candidates.append(f"{row.get('id')} ({row.get('kind') or 'operator'})")
        candidates = candidates[:12]
        listed = "; ".join(candidates) if candidates else "the components that differ from the code parent"
        return ("shell", candidates,
                f"{pid}'s gain does not come from {kernels} (ablation {aid} found no effect); it sits in the "
                f"other components {pid} changed - candidates: {listed}. Follow up with evo ablate --parent "
                f"{pid} --question \"which of these carries the gain\" when the next bet depends on it.")

    def _settle_parent_mechanism_from_ablation(self, node: dict) -> None:
        """An ablation that changed the parent's kernel settles the parent's
        mechanism from the same observations: observed effect -> confirmed,
        no effect -> refuted. An inconclusive result settles nothing: the
        parent stays as it was (deferred) with the attempt on record, and the
        doors (evo ablate, a targeted_ablation lane in the next portfolio)
        stay open to people - the engine does not mint a second tax lane by
        itself. Nothing re-runs and nothing about parenthood changes: the
        causal status is knowledge written beside the parent. What a refuted
        kernel changes is what a child may carry (the ablation's control
        version becomes the recommended code parent) and what a lane may cite
        as a premise."""
        result = node.get("ablation_result") if isinstance(node.get("ablation_result"), dict) else {}
        meta = evalid._idea_meta(self.ctx(), node) or {}
        contract = meta.get("ablation") if isinstance(meta.get("ablation"), dict) else {}
        settles = contract.get("settles_parent_mechanism") is True
        parent = self.node(str((node.get("parents") or [""])[0] or ""))
        if parent is None:
            return
        # This ablation was the parent's OPEN inheritance-tax lane: the lane
        # has concluded, so the parent no longer points at it (the pointer
        # means "open"); the lane and who opened it stay on the settlement
        # row and in the event so the follow-up doors bind cleanly.
        opened_by = None
        lane_id = str(node.get("lane") or "")
        if lane_id and str(parent.get("ablation_lane") or "") == lane_id:
            parent.pop("ablation_lane", None)
            opened_by = parent.pop("ablation_lane_opened_by", None)
            egraph.touch(parent)
            self.store.event("engine", "ablation_lane_concluded", parent=parent.get("id"), lane=lane_id,
                             ablation=node.get("id"), opened_by=opened_by,
                             settles_parent_mechanism=settles)
        if not result or not settles:
            return
        effect = str(result.get("effect") or "")
        old_status = str(parent.get("mechanism_status") or "")
        new_status = {"observed": "confirmed", "not_observed": "refuted"}.get(effect, old_status)
        if new_status != old_status:
            parent["mechanism_status"] = new_status
            label = f"{new_status} via {node.get('id')}"
        else:
            label = (f"unclear via {node.get('id')}" if effect == "inconclusive"
                     else f"{old_status or '-'} via {node.get('id')}")
        if new_status == "refuted":
            # The kernel did not carry the gain. When the ablation's control arm
            # was the parent's program with the kernel simply removed, that
            # trained node is the natural thing to build on next and is
            # recorded as the control; a stand-in control (frozen, random) is a
            # diagnostic only, and children remove the kernel themselves. What
            # the gain then means depends on how much the parent changed, and
            # the engine writes that reading down as an observation to follow up.
            reading, candidates, statement = self._refuted_kernel_reading(parent, node)
            clean = contract.get("control_is_clean_program") is True
            parent["refuted_kernel"] = {"kernels": list(parent.get("kernel_ids") or []),
                                        "ablation": node.get("id"),
                                        "control": node.get("id") if clean else None,
                                        "reading": reading, "candidates": candidates,
                                        "at": eutil.utc_now()}
            summary = parent.get("evaluation_summary") if isinstance(parent.get("evaluation_summary"), dict) else {}
            cells = summary.get("cells") if isinstance(summary.get("cells"), dict) else {}
            measurement = ", ".join(
                f"{cid} {float(row.get('delta')):+g} vs {row.get('reference_node') or '-'}"
                for cid, row in sorted(cells.items())
                if isinstance(row, dict) and cid in (summary.get("target_wins") or [])
                and isinstance(row.get("delta"), (int, float))) \
                or ("wins on " + ", ".join(str(c) for c in (summary.get("target_wins") or [])) if summary.get("target_wins")
                    else "see the parent's evaluation summary")
            oid = self.store.add_observation(self.st, {
                "statement": statement, "where": f"{parent.get('id')} vs its comparator; ablation {node.get('id')}",
                "measurement": measurement,
                "evidence": str(node.get("result_doc") or (result.get("evidence") or "")),
                "node": parent.get("id"), "round": parent.get("round"), "status": "open",
                "source": "engine", "kind": f"{reading}_gain"})
            parent["refuted_kernel"]["observation"] = oid
            self.store.event("engine", "observation_recorded", id=oid, node=parent.get("id"),
                             kind=f"{reading}_gain", ablation=node.get("id"))
        elif new_status == "confirmed":
            parent.pop("refuted_kernel", None)
        parent.setdefault("mechanism_settlements", []).append({
            "ablation": node.get("id"), "node": node.get("id"), "lane": node.get("lane"),
            "opened_by": opened_by, "from": old_status, "to": new_status,
            "effect": result.get("effect"), "supports": result.get("supports"),
            "label": label, "at": eutil.utc_now()})
        parent["ablation_attempts"] = int(parent.get("ablation_attempts") or 0) + 1
        parent.pop("ablation_pending", None)
        egraph.touch(parent)
        self.store.event("engine", "parent_mechanism_settled", parent=parent.get("id"),
                         ablation=node.get("id"), effect=effect,
                         mechanism_from=old_status, mechanism_to=new_status,
                         control=node.get("id") if new_status == "refuted" else None)

    def posthoc_claim_settlement(self, node: dict, assessment: dict) -> dict:
        """What a post-hoc claim settles to, in the one shape every surface
        records and prints (the filing record, the gate report, the approved
        assessment): verdict / effect / wins / losses under the claim's lines,
        and - judged under the node's LIVE mechanism, never a re-run of the
        original probe - the scientific promotion approval would install."""
        mechanism = str(node.get("mechanism_status") or assessment.get("mechanism_contract_status") or "")
        promotion = evalid.promotion_status(
            str(assessment.get("verdict") or ""),
            {"status": assessment.get("effect_contract_status")},
            fidelity_settled=not node.get("needs_fidelity") or not node.get("fidelity_pending"),
            real_win=bool(assessment.get("real_win")))
        return {"verdict": assessment.get("verdict"),
                "effect_contract_status": assessment.get("effect_contract_status"),
                "real_win": bool(assessment.get("real_win")),
                "target_cells": assessment.get("target_cells"), "target_wins": assessment.get("target_wins"),
                "target_losses": assessment.get("target_losses"), "deliverable": assessment.get("deliverable"),
                "mechanism_status": mechanism, "scientific_promotion_status": promotion}

    @staticmethod
    def posthoc_claim_refusal(node: dict, record: dict) -> str | None:
        """Why approving this claim would be refused now, or None. The claim
        was priced against ONE conclusion: a node that is no longer concluded,
        or whose conclusion was re-sealed since the claim was filed (a recovery
        re-analysed it), has different data behind it - the exit is a fresh
        claim. The gate report prints this before the decision; the decision
        path checks it before it records anything."""
        filed_against = str(((record.get("proposal_seal") or {}).get("upstream") or [""])[0] or "")
        current = str((node.get("conclusion_seal") or {}).get("digest") or "")
        if node.get("status") != "concluded" or not current or filed_against != current:
            return (f"post-hoc claim {record.get('id')} was filed against a conclusion of {node.get('id')} "
                    f"that is no longer the live one (node status {node.get('status')}); decision not applied - "
                    f"reject this gate and re-file with evo claim --node {node.get('id')} --proposal <file>")
        return None

    def _apply_posthoc_claim(self, node: dict, record: dict, *, gate: dict, note: str | None,
                             actor: str) -> None:
        """The user accepted a post-hoc claim: it becomes the claim inheritance
        reads for this node, labeled as such. The original assessment, verdict
        and effect status stay as they were settled."""
        refusal = self.posthoc_claim_refusal(node, record)
        if refusal:
            raise SystemExit("[evo] " + refusal)
        proposal = eutil.read_json(eutil.rpath(self.store.repo, str(record.get("proposal_path") or "")), {}) or {}
        settled = self.posthoc_claim_settlement(node, evalid.assess_posthoc_claim(self.ctx(), node, proposal))
        mechanism, promotion = settled["mechanism_status"], settled["scientific_promotion_status"]
        old_promotion = node.get("scientific_promotion_status")
        node["active_claim"] = record["id"]
        node["posthoc_assessment"] = {"claim": record["id"], **settled}
        node["scientific_promotion_status"] = promotion
        node.setdefault("posthoc_claims", []).append({
            "id": record["id"], "gate": gate.get("id"), "at": eutil.utc_now(),
            "promotion_from": old_promotion, "promotion_to": promotion, "mechanism_status": mechanism,
            "proposal_digest": str((record.get("proposal_seal") or {}).get("digest") or "")})
        settlement = record.get("settlement") if isinstance(record.get("settlement"), dict) else {}
        settlement.update(settled)
        record["settlement"] = settlement
        record["status"] = "approved"
        record["applied_at"] = eutil.utc_now()
        egraph.touch(node)
        self.store.event(actor, "posthoc_claim_approved", claim=record["id"], node=node["id"],
                         verdict=settled.get("verdict"), mechanism=mechanism,
                         promotion_from=old_promotion, promotion_to=promotion, note=note)
        egraph.recompute_rollups(self.g, self.cfg)
        egraph.render_views(self.store, self.g, self.cfg, self.st)
        for t in self.st.get("tasks", []):
            if t.get("type") == "open_round" and t.get("status") == "open":
                self._refresh_open_round_task(t)

    def _apply_instrument_review(self, task: dict) -> None:
        """The independent judge ruled on a claimed formula error. FORMULA_ERROR
        opens the user's gate; the other two verdicts close the request and
        leave the node exactly as it was."""
        subj = task.get("subject") or {}
        record = next((c for c in self.st.get("corrections", [])
                       if str(c.get("id") or "") == str(subj.get("correction") or "")), None)
        if record is None:
            raise SystemExit("[evo] instrument review accepted for an unknown correction (engine bug)")
        review = eutil.read_text(eutil.rpath(self.store.repo, task["outputs"][0]))
        m = REVIEW_VERDICT_RE.search(review)
        verdict = m.group(1) if m else "INSUFFICIENT"
        record["review_path"] = task["outputs"][0]
        record["review_seal"] = self._seal(
            [("instrument_review", task["outputs"][0])],
            upstream=[str((record.get("proposal_seal") or {}).get("digest") or "")])
        record["review_verdict"] = verdict
        record["review_session"] = str(task.get("session") or "")
        self.store.event("agent", "instrument_review_verdict", correction=record["id"],
                         node=record.get("node"), verdict=verdict)
        if verdict != "FORMULA_ERROR":
            record["status"] = "closed_by_review"
            record["closed_at"] = eutil.utc_now()
            return
        record["status"] = "awaiting_user"
        original = record.get("original") or {}
        corrected = record.get("corrected") or {}
        gate = self.store.new_gate(
            self.st, "instrument_correction",
            {"node": record.get("node"), "correction": record["id"],
             "from": original.get("status"), "to": corrected.get("status"),
             "proposal_digest": str((record.get("proposal_seal") or {}).get("digest") or "")},
            f"Node {record.get('node')}: an independent judge ruled that the mechanism instrument had a "
            f"FORMULA ERROR. Approve to re-settle the mechanism from the SAME sealed observations under "
            f"the corrected rule ({original.get('status')} -> {corrected.get('status')}); reject to keep "
            "the original settlement. Nothing is rerun either way.")
        record["gate"] = gate.get("id")

    def _apply_instrument_correction(self, node: dict, record: dict, *, gate: dict,
                                     note: str | None, actor: str) -> None:
        """Re-settle one node's PROBE answer from sealed observations under the
        corrected rule. The original OUTCOME stays sealed as history; the
        probe result written beside the node is recomputed by the same rule
        machinery that settled it the first time. Parenthood does not move:
        the probe is information, the causal status belongs to the ablation."""
        corrected = record.get("corrected") or {}
        probe = dict(node.get("probe_result") or {}) if isinstance(node.get("probe_result"), dict) else {}
        old_status = str(probe.get("status") or "")
        new_status = str(corrected.get("status") or "")
        probe.update({"status": new_status, "corrected_by": record["id"], "corrected_at": eutil.utc_now()})
        node["probe_result"] = probe
        node.setdefault("mechanism_corrections", []).append({
            "id": record["id"], "from": old_status, "to": new_status,
            "gate": gate.get("id"), "at": eutil.utc_now(),
            "proposal_digest": str((record.get("proposal_seal") or {}).get("digest") or ""),
            "review_digest": str((record.get("review_seal") or {}).get("digest") or ""),
        })
        record["status"] = "applied"
        record["applied_at"] = eutil.utc_now()
        egraph.touch(node)
        self.store.event(actor, "instrument_correction_applied", correction=record["id"],
                         node=node["id"], probe_from=old_status, probe_to=new_status, note=note)
        egraph.recompute_rollups(self.g, self.cfg)
        egraph.render_views(self.store, self.g, self.cfg, self.st)
        for t in self.st.get("tasks", []):
            if t.get("type") == "open_round" and t.get("status") == "open":
                self._refresh_open_round_task(t)

    def _apply_close_round(self, task: dict) -> None:
        st = self.st
        rid = task["subject"]["round"]
        # Defense in depth behind ROUND_ALREADY_CLOSED (v_close_round): never
        # append a second closed record for the same round.
        if any(r.get("id") == rid and r.get("closed_at") for r in st.get("rounds", [])):
            self.store.event("engine", "close_round_replay_ignored", round=rid, task=task.get("id"))
            return
        retire_path = next((o for o in task["outputs"] if str(o).endswith("RETIRE.json")), None)
        # What this round MEASURED is settled before the retirement bookkeeping
        # rearranges the graph.  Reading movement after retirements let pruning
        # the incumbent hand frontier membership - and therefore a progress
        # report - to a node that was strictly worse than it.
        earned_frontier = {n["id"] for n in egraph.frontier(self.g, self.cfg, self.st)}
        earned_performance = {n["id"] for n in egraph.performance_frontier(self.g, self.cfg, self.st)}
        if retire_path and eutil.rpath(self.store.repo, retire_path).exists():
            for r in self._spec_from(retire_path) or []:
                if not isinstance(r, dict):
                    continue  # validator guarantees dict rows; belt for hand-edited files
                node = self.node(r.get("node"))
                if node and node.get("role") != "baseline":
                    node["retire_reason"] = r.get("reason")
                    egraph.touch(node)
                    if r.get("reason") == "pruned":
                        eartifact.invalidate_for_node(self.store, self.reg, node["id"], "producer pruned")
                    elif r.get("reason") == "archived":
                        # BOTH retirement forms relax the producer's
                        # working-byte duties, so both gate new consumers
                        # behind revive (the graph-parent door already did;
                        # the artifact-only door let an archived producer's
                        # rows stay available and skip the re-proof entirely)
                        eartifact.invalidate_for_node(self.store, self.reg, node["id"], "producer archived")
                    self.store.event("engine", "node_retired", node=node["id"], reason=r.get("reason"),
                                     note=r.get("note"))
        best = self._observed_best()
        start = (st.get("round_start_primary") or {}).get(rid)
        start_frontier = set((st.get("round_start_frontier") or {}).get(rid) or [])
        current_frontier = {n["id"] for n in egraph.frontier(self.g, self.cfg, self.st)}
        start_performance = set((st.get("round_start_performance_frontier") or {}).get(rid) or [])
        current_performance = {n["id"] for n in egraph.performance_frontier(self.g, self.cfg, self.st)}
        round_nodes = {n["id"]: n for n in self.g.get("nodes", []) if n.get("round") == rid}
        winning = {"improved", "specialist", "tradeoff", "dominant"}
        # Two ways a round can be progress: a claim settled and became
        # inheritable, or this round measured a genuinely new non-dominated
        # point.  Counting only the first declared five real Pareto advances a
        # dead flat window and escalated the portfolio into moonshots that
        # could not build on any of them.
        #
        # Both are read off the pre-retirement graph, and both have to be a
        # DECIDED advance.  Frontier membership alone is not movement: it is
        # also what an undecidably wide interval looks like, it can be handed
        # to a node for free when this transaction retires its dominator, and a
        # node that merely ties the incumbent enters the list without moving
        # the project anywhere.  Settling a claim at parity is a real result,
        # but it is not the thing the stagnation escalation is asking about.
        by_id = egraph.by_id(self.g)
        prior_inheritance = [by_id[nid] for nid in sorted(start_frontier) if nid in by_id]
        prior_performance = [by_id[nid] for nid in sorted(start_performance) if nid in by_id]
        moved_by = sorted(
            nid for nid in earned_frontier - start_frontier
            if (round_nodes.get(nid) or {}).get("verdict") in winning
            and egraph.advances_measurement(round_nodes[nid], prior_inheritance, self.cfg, self.st))
        performance_moved_by = sorted(
            nid for nid in earned_performance - start_performance
            if nid in round_nodes
            and egraph.advances_measurement(round_nodes[nid], prior_performance, self.cfg, self.st))
        improved = bool(moved_by) or bool(performance_moved_by)
        st["rounds"].append({
            "id": rid, "best_primary": best, "start_primary": start, "improved": improved,
            "origin_primary": self._origin_primary(),
            "performance_moved_by": performance_moved_by,
            "start_frontier": sorted(start_frontier), "end_frontier": sorted(current_frontier),
            "frontier_added": moved_by,
            "start_performance_frontier": sorted(start_performance),
            "end_performance_frontier": sorted(current_performance),
            "performance_frontier_added": sorted(current_performance - start_performance),
            "performance_frontier_removed": sorted(start_performance - current_performance),
            "lanes": [l["id"] for l in st["lanes"] if l["round"] == rid],
            "closed_at": eutil.utc_now(),
        })
        st["round_status"] = "closed"
        # a NORMAL close breaks any force-close streak (see the open_round
        # macro-livelock stop in _abandon_task_subject)
        st.pop("consecutive_forced_round_closes", None)
        self.store.event("engine", "round_closed", round=rid, best_primary=best, improved=improved,
                         frontier_added=moved_by,
                         performance_frontier_added=sorted(current_performance - start_performance))
