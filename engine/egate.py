"""Gate lifecycle: reports, protection/auto-resolve policy (driven by
eflow.GATE_POLICY), decisions and their side effects.
"""

from __future__ import annotations

import json
import shutil

import eamend
import ecanary
import econfig
import eflow
import egraph
import einfra
import erecover
import erun
import eutil
import evalid

stages_of = econfig.stages_of



def _facts_field_diff(cur, prop, *, indent: str = "    ") -> list[str]:
    """Field-level diff of one facts block (D2): the decision surface must
    show exactly what moved - a fixed-width block dump could truncate the
    very change under review into two identical lines."""
    out: list[str] = []
    if isinstance(cur, dict) and isinstance(prop, dict):
        for key in sorted(set(cur) | set(prop)):
            if cur.get(key) == prop.get(key):
                continue
            a, b = cur.get(key), prop.get(key)
            if isinstance(a, list) and isinstance(b, list):
                for i in range(max(len(a), len(b))):
                    x = a[i] if i < len(a) else None
                    y = b[i] if i < len(b) else None
                    if x == y:
                        continue
                    name = next((f" ('{r.get('name')}')" for r in (y, x)
                                 if isinstance(r, dict) and r.get("name")), "")
                    out.append(f"{indent}{key}[{i}]{name} approved: {json.dumps(x, ensure_ascii=False)}")
                    out.append(f"{indent}{key}[{i}]{name} proposed: {json.dumps(y, ensure_ascii=False)}")
            else:
                out.append(f"{indent}{key} approved: {json.dumps(a, ensure_ascii=False)}")
                out.append(f"{indent}{key} proposed: {json.dumps(b, ensure_ascii=False)}")
        return out or [f"{indent}(no field-level difference)"]
    out.append(f"{indent}approved: {json.dumps(cur, ensure_ascii=False)}")
    out.append(f"{indent}proposed: {json.dumps(prop, ensure_ascii=False)}")
    return out


class GateMixin:
    def _project_facts_report_lines(self) -> list[str]:
        """Project-level notebook rows (floors, margins, required cells, the
        ablation allowance) for the idea and workflow gates: the user decides
        knowing which ruler changed, when and why. Empty when none."""
        try:
            rows = list(eamend.history_lines(self.store, project=True) or [])
        except (AttributeError, TypeError, OSError, ValueError):
            rows = []
        if not rows:
            return []
        return ["- Project facts corrected (floors / margins / required / ablation allowance):"] \
            + [f"  {line}" for line in rows]

    def _gate_report(self, gate: dict) -> list[str]:
        """Engine-built, human-readable status block embedded in every gate card.
        Gates are the moments the user is guaranteed to be paying attention -
        stdout is the agent's API, so run state the user must see rides HERE.
        Tolerant by design: a missing file degrades a line, never blocks a gate."""
        kind, subj = gate["kind"], gate.get("subject", {}) or {}
        primary = econfig.primary_metric(self.cfg)
        out: list[str] = []
        if kind == "round_continue":
            hist = [r for r in self.st.get("rounds", []) if r.get("closed_at")]
            out.append(f"Rounds closed: {len(hist)} | display result: {primary} (decision is multi-cell)")
            for r in hist[-6:]:
                b, s = r.get("best_primary"), r.get("start_primary")
                tag = ("corrected/unknown" if not isinstance(r.get("improved"), bool)
                       or r.get("projection_status") not in {None, "active"}
                       else "improved" if r.get("improved") else "flat")
                out.append(f"- {r.get('id')}: display leader {b if b is not None else '-'}"
                           f" (start {s if s is not None else '-'}) -> {tag}")
            fr = egraph.frontier(self.g, self.cfg, self.st)
            if fr:
                top = fr[0]
                out.append(f"First in display order: {top['id']} '{top.get('title')}' "
                           f"{primary}={egraph.primary_score(top, primary)} (frontier size {len(fr)})")
            if hist:
                out.append(f"Last round's lanes ({hist[-1].get('id')}):")
                out.extend(f"  {line}" for line in self._round_summary_block(hist[-1].get("id")))
                # Retirement is a strategy decision the user reviews HERE, not
                # something to discover later in GRAPH.md/events. This is
                # an advisory read on the user's only decision surface: a
                # damaged file degrades the line, never the gate.
                try:
                    retire_rows = eutil.read_json(
                        eutil.rpath(self.store.repo,
                                    f".evo/rounds/{hist[-1].get('id')}/RETIRE.json"), None)
                except SystemExit:
                    retire_rows = None
                    out.append(f"Retired at this close: RETIRE.json for {hist[-1].get('id')} "
                               "is unreadable - see GRAPH.md for retirement state")
                if isinstance(retire_rows, list) and retire_rows:
                    out.append("Retired at this close (reversible later via 'evo revive'):")
                    for row in retire_rows:
                        if isinstance(row, dict):
                            out.append(f"  - {row.get('node')} [{row.get('reason')}] "
                                       f"{str(row.get('note') or '')[:120]}")
                fid_prov = evalid.node_review_provenance_lines(self.ctx(), str(hist[-1].get("id")))
                if fid_prov:
                    out.append("Workflow-side review provenance (implementer vs fidelity auditor):")
                    out.extend(f"  {line}" for line in fid_prov)
            running = self.store.running_runs(self.st)
            if running:
                out.append("Runs still in flight: "
                           + ", ".join(f"{r['id']} (node {r['node']}, stage {r.get('stage') or '-'})" for r in running))
            out.append(f"Tempo: {econfig.describe_policy(self.cfg)}")
            pol = self.cfg.get("policy", {})
            if evalid._stagnant_window(self.ctx(), int(pol.get("stagnation_moonshot_rounds", 0) or 0)) \
                    and int(pol.get("stagnation_moonshot_rounds", 0) or 0):
                out.append("NOTE: deep stagnation - the next round will be forced to contain a MOONSHOT lane.")
            elif evalid._stagnant_window(self.ctx(), int(pol.get("stagnation_rounds", 2))):
                out.append("NOTE: stagnation - the next round will include a subsystem/full-program search lane.")
        elif kind == "idea_approval":
            lane = self.store.get_lane(self.st, str(subj.get("lane") or "")) or {}
            iid = str(subj.get("idea") or "")
            meta = eutil.read_json(eutil.rpath(self.store.repo, f".evo/ideas/{iid}.meta.json")) or {}
            # Level 0 is a real, mandated value for every instrumental lane, and
            # `0 or '?'` printed it as unknown - the gate report told the user
            # the scope was undetermined on exactly the lanes whose scope the
            # engine fixes.
            def _lvl(value):
                return value if isinstance(value, int) and not isinstance(value, bool) else "?"
            out.append(f"Idea {iid} '{meta.get('title') or '?'}' from lane {lane.get('id') or '?'} "
                       f"'{lane.get('name') or '?'}' (intent {lane.get('intent') or '?'}, "
                       f"min L{_lvl(lane.get('min_level'))})")
            out.append(f"- implementation scope: L{_lvl(meta.get('level'))} ({meta.get('change_scope') or '?'}) | "
                       f"M: {(meta.get('novelty') or {}).get('kind') or '?'} | T: {meta.get('theory_role') or 'none'} | "
                       f"parents: {', '.join(meta.get('parents') or []) or '(none - new root)'}")
            out.append(f"- mode: {econfig.mode(self.cfg)}"
                       + (" | formal problem ladder passed" if lane.get("formal") else ""))
            out.append(f"- experiment purpose: {meta.get('experiment_purpose') or 'candidate'}")
            purpose = econfig.lane_purpose(meta)
            if purpose == "targeted_ablation":
                ab = meta.get("ablation") or {}
                inside, lines = evalid.ablation_design_within_allowance(self.ctx(), lane)
                out.append(f"- TARGETED ABLATION ({'inside the pre-authorized allowance' if inside else 'ABOVE the allowance - your decision'}): "
                           f"{ab.get('question') or '?'}")
                out.append(f"- changed-component run(s): {ab.get('costly_runs')} - {ab.get('intervention') or '?'}")
                out.append(f"- run count sized by: {ab.get('runs_basis') or '?'}")
                out.append(f"- settles the parent's mechanism: {ab.get('settles_parent_mechanism')}")
                for line in lines:
                    out.append(f"- allowance: {line}")
                out.append(f"- decision if effect/no-effect: {ab.get('decision_if_effect') or '?'} / "
                           f"{ab.get('decision_if_no_effect') or '?'}")
            elif purpose == "diagnostic_probe":
                # The manual gate IS the protection for instrumental work, so the
                # user has to see what they are approving: the question, what it
                # changes, and the resource cap they are agreeing to spend.
                pr = meta.get("probe") or {}
                budget = ", ".join(f"{u} <= {v:g}" for u, v in sorted((pr.get("budget") or {}).items())
                                   if isinstance(v, (int, float)) and not isinstance(v, bool)) or "?"
                out.append(f"- DIAGNOSTIC PROBE (manual approval required): {pr.get('question') or '?'}")
                out.append(f"- measurement plan: {pr.get('measurement_plan') or '?'}")
                out.append(f"- answers change: {pr.get('decision_impact') or '?'} | budget cap: {budget}")
            elif purpose == "maintenance":
                mt = meta.get("maintenance") or {}
                boundary = mt.get("change_boundary") or {}
                files = ", ".join(str(f) for f in (boundary.get("files_in_scope") or [])) or "?"
                out.append(f"- MAINTENANCE REPAIR (manual approval required): {mt.get('defect') or '?'}")
                out.append(f"- change boundary (enforced against the parent's reviewed commit): {files}")
                out.append(f"- unblocks: {mt.get('expected_unblock') or '?'} | semantics: "
                           f"{boundary.get('semantic_intent') or '?'} (parity settled over every decision cell)")
            if purpose == "exploratory":
                #  approving this waives real rigor - the user
                # must see the whole trade before deciding, like every other
                # manual-only purpose above.
                out.append("- EXPLORATORY SCOUT (manual approval required): approving WAIVES registered "
                           "predictions, SOTA targets and the mechanism-probe duty for this lane.")
                out.append("- in exchange its results are OBSERVATIONS ONLY: never on a frontier, never a "
                           "record, promotion pinned not_applicable, no research-share/portfolio-duty "
                           "credit; the conclusion MUST emit >= 1 OB### observation.")
                out.append("- to put a scouted effect on the record later, a confirmatory candidate "
                           "(confirmatory_of) re-runs this kernel under FULL rigor.")
            for p in (meta.get("predictions") or [])[:4]:
                out.append(f"- registered prediction {p.get('id')}: {p.get('metric')} "
                           f"{p.get('comparison')} {p.get('value')}"
                           + (f" on {p.get('slice')}" if p.get("slice") else ""))
            for t in (meta.get("sota_targets") or [])[:3]:
                out.append(f"- SOTA target {t.get('sota')}: beat on '{t.get('dimension')}'")
            rr = meta.get("repeat_rule")
            if isinstance(rr, dict):
                if rr.get("band") is not None:
                    band_txt = f"{rr.get('band')}"
                else:
                    band_txt = (f"the recorded noise floor (currently "
                                f"{econfig.noise_floor(self.cfg, str(rr.get('cell') or ''), self.st):g}, "
                                f"{econfig.noise_floor_source(self.cfg, str(rr.get('cell') or ''), self.st)}; "
                                "frozen before each evaluation)")
                out.append(f"- pre-registered repeat rule: if the measured delta on {rr.get('cell')} lands "
                           f"within {band_txt} of a decision line, you will be offered EXACTLY ONE "
                           "bought-back repeat (own gate)")
            if lane.get("scaling_followup_of"):
                out.append(f"- SCALING FOLLOW-UP of {lane.get('scaling_followup_of')}: re-runs that parent's "
                           "frozen kernel at the registered scale points; comparator = the parent")
            if lane.get("confirmatory_of"):
                out.append(f"- CONFIRMATORY re-run of exploratory {lane.get('confirmatory_of')}: same kernel "
                           "under full pre-registration - the only legal duplication of a scout's kernel")
            # The human sees whose judgment they are trusting - a release
            # review from the authoring session is a self-audit and says so.
            provenance = evalid.review_provenance_lines(self.ctx(), lane)
            if provenance:
                out.append("- release-review provenance:")
                out.extend(f"  {line}" for line in provenance)
            # Each purpose keeps its review under its own suffix, and a probe has
            # no review stage at all.  A single hard-coded `.review.md` sent the
            # user to a file that never exists on all three instrumental
            # purposes - at the one gate the design makes manual on purpose.
            review_suffix = {"candidate": ".review.md", "exploratory": ".review.md",
                             "targeted_ablation": ".ablation-review.md",
                             "maintenance": ".maintenance-review.md"}.get(purpose)
            reads = [f".evo/ideas/{iid}.md (the design)"]
            if review_suffix:
                reads.append(f".evo/ideas/{iid}{review_suffix} (adversarial review verdict)")
            out.append("- read: " + ", ".join(reads))
            history = eamend.history_lines(self.store, lane=str(lane.get("id") or "") or None, idea=iid)
            if history:
                out.append("- notebook corrections on this lane/idea:")
                out.extend(f"  {line}" for line in history)
            out.extend(self._project_facts_report_lines())
        elif kind == "workflow_approval":
            nid = str(subj.get("node") or "")
            node = self.node(nid) or {}
            spec = self._spec(node) if node else {}
            stages = econfig.stages_of(spec)
            # Same falsy-zero trap as the idea-gate header: every instrumental
            # node is level 0, and this gate is now mandatory for all of them.
            lvl = node.get("level")
            lvl_txt = lvl if isinstance(lvl, int) and not isinstance(lvl, bool) else "?"
            purpose_note = {"targeted_ablation": " [TARGETED ABLATION]",
                            "diagnostic_probe": " [DIAGNOSTIC PROBE]",
                            "maintenance": " [MAINTENANCE REPAIR]",
                            "exploratory": " [EXPLORATORY SCOUT - results are observations only]"}.get(
                str(node.get("experiment_purpose") or ""), "")
            out.append(f"Node {nid} '{node.get('title') or '?'}' (role {node.get('role') or '?'}, "
                       f"L{lvl_txt}){purpose_note} asks to execute its finite workflow")
            wf_lane = self.store.get_lane(self.st, str(node.get("lane") or "")) or {}
            for fld, label in (("scaling_followup_of", "scaling follow-up"),
                               ("confirmatory_of", "confirmatory re-run")):
                if wf_lane.get(fld):
                    out.append(f"- CARBON-COPY SPEND: this trains a verbatim duplicate of "
                               f"{wf_lane.get(fld)}'s kernel ({label}) - that is why this gate never "
                               "auto-approves")
            out.append(f"- cost class: {spec.get('cost_class', 'light')} | "
                       f"scheduler-visible stages: {', '.join(s.get('name') or '?' for s in stages) or '(none)'}")
            ep = spec.get("evidence_plan") or {}
            replication = spec.get("training_replication") or {}
            totals = econfig.stage_budget_totals(spec)
            budget_text = ", ".join(f"{k}<={v:g}" for k, v in sorted(totals.items())) or "undeclared"
            workflow_runs = econfig.workflow_replica_count(spec)
            out.append(f"- execution shape: {len(stages)} stage(s) x {workflow_runs} complete seed run(s) = "
                       f"{len(stages) * workflow_runs} sequential scheduler job(s); "
                       f"declared aggregate caps: {budget_text}; "
                       f"training runs={replication.get('runs', 0)} ({replication.get('mode', 'not-applicable')}); "
                       f"1 standard eval + {ep.get('extra_eval_arms', '?')} extra eval arm(s).")
            if node.get("experiment_purpose") == "targeted_ablation":
                ab = spec.get("ablation") or {}
                inside, lines = evalid.ablation_spec_within_allowance(self.ctx(), node, spec)
                out.append(f"- targeted-ablation spend ({'inside the pre-authorized allowance' if inside else 'ABOVE the allowance - your decision'}): "
                           f"{ab.get('costly_runs')} changed-component run(s) "
                           f"({ab.get('runs_basis') or 'no sizing basis recorded'}); question: {ab.get('question') or '?'}")
                for line in lines:
                    out.append(f"- allowance: {line}")
            for s in stages:
                control = s.get("control") or {}
                cons = ", ".join(
                    (c.get("artifact") or f"stage '{c.get('stage')}'") if isinstance(c, dict) else str(c)
                    for c in (s.get("consumes") or [])) or "-"
                limits = ", ".join(f"{k}<={v}" for k, v in sorted((((s.get('budget') or {}).get('limits')) or {}).items()))
                out.append(f"  - stage '{s.get('name')}': {control.get('mode') or '-'}/{control.get('multiplicity') or '-'}; "
                           f"budget {limits or '-'}; consumes {cons}; produces {len(s.get('produces') or [])} artifact(s)")
            out.extend(evalid.workflow_spend_review(self.ctx(), node, spec)[0])
            out.append(f"- spec: .evo/nodes/{nid}/NODE_SPEC.json | idea: {node.get('idea_doc') or '-'}")
            history = eamend.history_lines(self.store, node=nid, lane=str(node.get("lane") or "") or None,
                                           idea=str(wf_lane.get("idea") or "") or None)
            if history:
                out.append("- notebook corrections on this node/idea (weigh WHEN each was made):")
                out.extend(f"  {line}" for line in history)
            out.extend(self._project_facts_report_lines())
        elif kind == "human_study_confirm":
            nid = str(subj.get("node") or "")
            out.append(f"Node {nid} asks to settle human-study evaluation cell(s). The engine "
                       "cannot execute or verify a human study; it seals what you approve here.")
            # The node's own pointer, not a hard-coded path: after an
            # evaluation-boundary recovery the live metrics are metrics_r{N}.json,
            # and showing the superseded revision while sealing the new one asks
            # the user to approve numbers they were never shown.
            metrics_rel = self._eval_metrics_path(egraph.by_id(self.g).get(nid) or {"id": nid})
            metrics = eutil.read_json(eutil.rpath(self.store.repo, metrics_rel), {}) or {}
            out.append(f"- evidence read from `{metrics_rel}`")
            for cell in econfig.evaluation_cells(self.cfg):
                if str(cell.get("source_kind") or "") != "human_study":
                    continue
                row = metrics.get(str(cell.get("result_key") or ""))
                value = (row or {}).get("value") if isinstance(row, dict) else row
                artifact = (row or {}).get("study_artifact") if isinstance(row, dict) else None
                out.append(f"- {cell.get('id')} [{cell.get('result_key')}]: value={value!r}; "
                           f"raw responses: {artifact or 'MISSING'}")
                out.append(f"  frozen protocol: {str(cell.get('study_protocol') or '')[:160]}")
            out.append("Approval seals these exact bytes into the evaluation; rejection demands "
                       "revised study evidence (the same bytes cannot be resubmitted).")
        elif kind == "resource_approval":
            nid = str(subj.get("node") or "")
            if subj.get("probe_cap_over"):
                out.append(f"Probe node {nid} requests a PROBE-CAP increase for {subj.get('operation')}"
                           + (f" stage '{subj.get('stage')}'" if subj.get("stage") else "")
                           + " (project limits untouched; approval buys exactly the shown overage)")
            else:
                out.append(f"Node {nid} requests a project-limit increase for {subj.get('operation')}"
                           + (f" stage '{subj.get('stage')}'" if subj.get("stage") else ""))
            charged, reserved = self._resource_charged(), self._resource_reserved()
            limits = self._resource_effective_limits()
            probe_over = subj.get("probe_cap_over") or {}
            for unit, amount in sorted((subj.get("request") or {}).items()):
                if probe_over:
                    pair = probe_over.get(unit) or [None, None]
                    over_txt = (f"projected {float(pair[0]):g} vs probe cap {float(pair[1]):g} "
                                f"(overage {max(float(pair[0]) - float(pair[1]), 0.0):g})"
                                if isinstance(pair, (list, tuple)) and len(pair) == 2
                                and all(isinstance(x, (int, float)) for x in pair)
                                else "within cap")
                    out.append(f"- {unit}: retry needs {float(amount):g}; {over_txt}")
                else:
                    out.append(f"- {unit}: operation cap {float(amount):g}; charged {charged.get(unit, 0):g}; "
                               f"currently reserved {reserved.get(unit, 0):g}; effective project limit {limits.get(unit, 0):g}; "
                               f"requested addition {float((subj.get('deficit') or {}).get(unit, 0)):g}")
            if probe_over:
                out.append("Approval raises THIS probe's cap by exactly the listed overage(s); project "
                           "limits are untouched. Rejection abandons the probe with what it already "
                           "measured on record; full_auto cannot decide this gate.")
            else:
                out.append("Approval increases only the listed project limits by the listed deficits. "
                           "Rejection abandons this node; full_auto cannot decide this gate.")
        elif kind == "infra_confirm":
            out.append("The infrastructure review is ready for your sign-off. It decides how every "
                       "future workflow work is launched, tracked, and stored.")
            out.append("- read: .evo/profile/INFRA_REVIEW.md (docs-vs-code contradictions, unknowns, "
                       "and the primary-metric confirmation)")
            out.append("- the machine facts behind it: workflow-slot quota, artifact URI template, datasets")
            limits = econfig.resource_limits(self.cfg)
            out.append("- project-wide resource contract: "
                       + (", ".join(f"{u}<={v:g}" for u, v in sorted(limits.items())) or "MISSING"))
            rep = econfig.training_replication_policy(self.cfg)
            abl = ((self.cfg.get("evidence_policy") or {}).get("ablation") or {})
            out.append(f"- training seed policy: {rep.get('mode')} (planned runs {rep.get('planned_runs')}, "
                       f"aggregation {rep.get('aggregation')})")
            out.append(f"- ablation allowance: {econfig.ablation_budget_multiple(self.cfg):g} x a node's own "
                       "cost (0 = mechanisms stay deferred)")
            out.append("- approval authorizes the next tiny engine-run infrastructure canary; it does not "
                       "declare the infrastructure ready by itself")
            prov = eutil.read_json(eutil.rpath(self.store.repo, ".evo/profile/PROVISION.json"), None)
            if isinstance(prov, dict) and prov.get("choices"):
                out.append("PREPARATION CHOICES (your sign-off): the preparation pass made these "
                           "scientific decisions while getting the project to its first real number - "
                           "approving this gate ADOPTS them:")
                for c in prov.get("choices") or []:
                    out.append(f"- {(c or {}).get('decision')} (why: {(c or {}).get('why')})")
                out.append("  full report: .evo/profile/PROVISION.md")
            out.append("- automation remains disabled until you approve this gate")
        elif kind == "infra_canary_blocked":
            task_id = str(subj.get("task") or "")
            task = self.store.get_task(self.st, task_id) or {}
            record = task.get("infra_canary_run") or {}
            record_errs = ecanary.record_errors(self.store, record, expect_task=task_id)
            if record_errs or record.get("status") != "blocked":
                raise SystemExit("[evo] blocked infrastructure canary evidence is invalid:\n  - "
                                 + "\n  - ".join(record_errs or ["CANARY_RUN_NOT_BLOCKED"]))
            receipt, receipt_errs = ecanary.verified_receipt(self.store, record)
            if receipt is None:
                raise SystemExit("[evo] blocked infrastructure canary receipt changed while rendering gate:\n  - "
                                 + "\n  - ".join(receipt_errs))
            out.append("INFRASTRUCTURE CANARY BLOCKED: the real integrated tiny run did not establish readiness.")
            out.append(f"- command: {receipt.get('command') or '-'}")
            out.append(f"- exit: {receipt.get('exit')} | receipt: {record.get('receipt') or '-'}")
            for blocker in receipt.get("blockers") or []:
                out.append(f"- missing: {blocker.get('missing')} | needed for: {blocker.get('needed_for')} | "
                           f"please provide: {blocker.get('ask')}")
            if self.st.get("infra_revision_pending"):
                out.append("- APPROVE after supplying the missing item(s): a fresh task reruns the "
                           "complete canary against the REVISED facts. REJECT gives up on the "
                           "revision: the previously proven facts are restored and the project "
                           "continues under them (nothing is stopped).")
            else:
                out.append("- APPROVE after supplying the missing item(s): a fresh task reruns the complete canary. "
                           "REJECT to stop. This gate never auto-resolves, including in full_auto.")
            out.append("- If the ROOT CAUSE is an approved INFRA_FACTS entry that turned out to be "
                       "wrong (not a missing resource), write the corrected file to "
                       ".evo/profile/INFRA_FACTS_PROPOSED.json and run `evo revise-infra --note ...` "
                       "- approving that revision re-arms this canary against the corrected facts.")
        elif kind == "provision_blocked":
            pj = eutil.read_json(eutil.rpath(self.store.repo, ".evo/profile/PROVISION.json"), {}) or {}
            out.append("PREPARATION BLOCKED: your project cannot reach a first real end-to-end "
                       "number with what was provided. The engine needs the following from you:")
            for b in pj.get("blockers") or []:
                out.append(f"- missing: {b.get('missing')} | needed for: {b.get('needed_for')} | "
                           f"please provide: {b.get('ask')}")
            out.append("- full report: .evo/profile/PROVISION.md (incl. everything already tried)")
            out.append("- APPROVE once you have supplied the items (say what you added in the note) - "
                       "the engine retries preparation; REJECT to stop the evolution.")
        elif kind == "infra_revision":
            proposed = eutil.read_json(eutil.rpath(self.store.repo,
                                                   ".evo/profile/INFRA_FACTS_PROPOSED.json"), {}) or {}
            current = einfra.load_facts(self.store, self.cfg) or {}
            out.append("INFRA_FACTS REVISION: evolution learned an approved infrastructure fact is "
                       "wrong. Exact changes (approved -> proposed):")
            for block in (subj or {}).get("changed_blocks") or []:
                out.append(f"- {block}:")
                out.extend(_facts_field_diff(current.get(block), proposed.get(block), indent="    "))
            out.append("- APPROVE to adopt: the old facts are archived, the approved digest moves, and "
                       "NEW stage/eval spend stays refused until the integrated canary passes again "
                       "against the revised facts (the engine re-mints the canary task). REJECT keeps "
                       "the approved facts; the proposal file stays for a corrected retry.")
        elif kind == "engine_fit_blocked":
            disc = eutil.read_json(eutil.rpath(self.store.repo, ".evo/profile/PROJECT_DISCOVERY.json"), {}) or {}
            fit = disc.get("engine_fit") if isinstance(disc.get("engine_fit"), dict) else {}
            out.append(f"ENGINE-FIT ASSESSMENT: overall '{fit.get('overall')}'. This engine evolves "
                       "an existing, runnable-or-preparable ML project through iterative measured "
                       "improvement; the scan found the following assumptions violated or uncertain:")
            fit_names = {"F0": "task class", "F5": "iteration cadence",
                         "F6": "decidability", "F7": "harness shape"}
            for row in (fit.get("assumptions") or []):
                if not isinstance(row, dict) or row.get("verdict") == "holds":
                    continue
                out.append(f"- [{row.get('id')} {fit_names.get(str(row.get('id')), '?')}] "
                           f"{str(row.get('verdict') or '').upper()}: {row.get('note')}")
                if row.get("consequence_if_wrong"):
                    out.append(f"    consequence: {row.get('consequence_if_wrong')}")
            out.append("- APPROVE to proceed ANYWAY (your note joins the record; later failures that "
                       "hit these assumptions will point back here); REJECT to stop now - the gap "
                       "list above is exactly what this engine cannot promise for this project.")
        elif kind == "abandon_request":
            out.append("The agent proposes STOPPING this direction as dead - you are being asked "
                       "to discard admitted work on its judgment.")
            #  the discard decision comes WITH its numbers -
            # what the subject is, what it measured, and what is already paid.
            if subj.get("node"):
                n = self.node(str(subj.get("node"))) or {}
                primary = econfig.primary_metric(self.cfg)
                out.append(f"- node {n.get('id')} '{n.get('title') or '?'}' role={n.get('role') or '?'} "
                           f"status={n.get('status') or '?'} verdict={n.get('verdict') or '(none yet)'} "
                           f"{primary}={egraph.primary_score(n, primary)}")
                if self._node_training_paid(n):
                    out.append("- STAKES: this node's training is ALREADY PAID FOR - approving discards "
                               "a trained model and its sealed evidence.")
            elif subj.get("lane"):
                ln = self.store.get_lane(self.st, str(subj.get("lane"))) or {}
                out.append(f"- lane {ln.get('id')} '{ln.get('name') or '?'}' intent={ln.get('intent')} "
                           f"status={ln.get('status')} idea={ln.get('idea') or '(pre-idea)'}")
            out.append(f"- agent's reason: {str(subj.get('reason') or '(none recorded)')}")
            out.append("- approve = deliberate stop, recorded as a decision (not a failure); "
                       "reject = the work continues unchanged.")
        elif kind == "posthoc_claim":
            record = next((c for c in self.st.get("posthoc_claims", [])
                           if str(c.get("id") or "") == str(subj.get("claim") or "")), None) or {}
            node = self.node(str(subj.get("node") or "")) or {}
            proposal = eutil.read_json(eutil.rpath(self.store.repo, str(record.get("proposal_path") or "")), {}) or {}
            summary = node.get("evaluation_summary") or {}
            meta = evalid._idea_meta(self.ctx(), node) if node else {}
            original_scope = (meta.get("claim_scope") or {}) if isinstance(meta, dict) else {}
            settlement = record.get("settlement") or {}
            out.append(f"- POST-HOC CLAIM {record.get('id')} on {node.get('id')} (concluded "
                       f"{str(node.get('concluded_at') or node.get('updated_at') or '?')[:16]}; "
                       f"claim filed {str(record.get('filed_at') or '?')[:16]})")
            out.append(f"- the ORIGINAL bet: {original_scope.get('kind') or '?'} on "
                       f"{', '.join(original_scope.get('target_cells') or []) or '?'}; settled verdict "
                       f"{node.get('verdict')} / effect {node.get('effect_contract_status')} / promotion "
                       f"{node.get('scientific_promotion_status')} - this record does not change")
            lines = "; ".join(f"{r.get('target_cell')} {r.get('direction')} >= {r.get('minimum_worthwhile_delta')}"
                              for r in (proposal.get("lines") or []) if isinstance(r, dict))
            out.append(f"- the NEW claim: {(proposal.get('claim_scope') or {}).get('kind')} on "
                       f"{', '.join((proposal.get('claim_scope') or {}).get('target_cells') or [])}; lines: {lines}")
            out.append(f"- settled from the SAME sealed metrics: verdict {settlement.get('verdict')} / effect "
                       f"{settlement.get('effect_contract_status')}; wins on "
                       f"{', '.join(settlement.get('target_wins') or []) or 'none'}; losses on "
                       f"{', '.join(settlement.get('target_losses') or []) or 'none'}")
            out.append(f"- proposer's reason: {str(proposal.get('reason') or '')[:400]}")
            # The claim is judged under the node's LIVE mechanism (an ablation
            # write-back or an instrument correction may have moved it since
            # the original probe), so the user sees the promotion approval
            # would actually produce.
            live: dict = {}
            if node and proposal and node.get("status") == "concluded":
                try:
                    live = evalid.assess_posthoc_claim(self.ctx(), node, proposal) or {}
                except (KeyError, TypeError, ValueError, OSError):
                    live = {}
            would = self.posthoc_claim_settlement(node, live or settlement)["scientific_promotion_status"] \
                if node else "?"
            out.append(f"- judged under the node's LIVE mechanism: {egraph.mechanism_label(node) if node else '?'}; "
                       f"approval would set scientific promotion {node.get('scientific_promotion_status')} -> {would}")
            refusal = self.posthoc_claim_refusal(node, record) if node else None
            if refusal:
                out.append(f"- NOTE: approve will be refused (nothing is recorded by a refused decision): {refusal}")
            out.append("- approve = this claim becomes the one inheritance reads (labeled post-hoc on the "
                       "frontier); reject = recorded as rejected, nothing changes. Either way the original "
                       "bet and its verdict stay exactly as settled.")
        elif kind == "instrument_correction":
            record = next((c for c in self.st.get("corrections", [])
                           if str(c.get("id") or "") == str(subj.get("correction") or "")), None) or {}
            node = self.node(str(subj.get("node") or "")) or {}
            original, corrected = record.get("original") or {}, record.get("corrected") or {}
            proposal = eutil.read_json(eutil.rpath(self.store.repo, str(record.get("proposal_path") or "")), {}) or {}
            out.append(f"INSTRUMENT CORRECTION on node {node.get('id')} '{node.get('title') or '?'}': an "
                       "independent judge ruled the mechanism rule's FORMULA was wrong. Nothing is rerun; "
                       "approval re-settles the SAME sealed observations under the corrected rule.")
            out.append(f"- original rule {json.dumps(original.get('rule') or {}, ensure_ascii=False)} over "
                       f"{original.get('values')} -> {original.get('status')}")
            out.append(f"- corrected rule {json.dumps(corrected.get('rule') or {}, ensure_ascii=False)} over "
                       f"{corrected.get('values')} -> {corrected.get('status')}"
                       + (f" ({(corrected.get('settlement') or {}).get('reason')})"
                          if (corrected.get("settlement") or {}).get("reason") else ""))
            out.append(f"- applicant's argument: {str(proposal.get('argument') or '')[:400]}")
            out.append(f"- formula: {str(proposal.get('formula') or '')[:200]}")
            out.append(f"- judge's ruling: {record.get('review_verdict')} "
                       f"(read {record.get('review_path')}); applicant session "
                       f"{record.get('applicant_session') or 'unrecorded'}, judge session "
                       f"{record.get('review_session') or 'unrecorded'}")
            out.append(f"- consequence: the probe's answer {original.get('status')} -> {corrected.get('status')} "
                       "on record (probe_result, with the correction id). Parenthood does not move: a probe "
                       "is information about whether the trained model uses the part; the causal status "
                       f"(currently {node.get('mechanism_status') or '-'}) is settled only by a targeted "
                       "ablation. The original OUTCOME stays sealed as history.")
            out.append("- symmetry: this channel re-judges in BOTH directions; a formula error that "
                       "inflated a passing gate is corrected the same way.")
            out.append("- approve = re-settle under the corrected rule; reject = keep the original settlement "
                       "(the proposal and ruling stay on record either way).")
        elif kind == "escalation" and subj.get("reason") == "resources_busy":
            t = self.store.get_task(self.st, str(subj.get("task") or ""))
            run = self.store.get_run(self.st, str(((t or {}).get("subject") or {}).get("run") or ""))
            waits = list((run or {}).get("busy_waits") or [])
            out.append(f"The launch for node {subj.get('node')} keeps finding the shared machine busy "
                       f"({len(waits)} report(s); limit {econfig.busy_wait_minutes(self.cfg)} min of waiting). "
                       "Nothing has been trained and no attempt was spent.")
            for w in waits[-3:]:
                out.append(f"  - {w.get('at')}: {w.get('note')}")
            out.append("- approve = keep waiting: the launch card stays open and the wait window restarts "
                       "from this decision; the agent relaunches when devices free up (fewer devices "
                       "than planned is a launch-time choice and is recorded, not judged).")
            out.append("- reject = stop waiting: the launch card is cancelled and the node is abandoned "
                       "(nothing paid for is lost). Raise resource_contract.max_devices or "
                       "busy_wait_minutes with 'evo amend' if the allowance itself is the problem.")
        elif kind == "escalation":
            out.append(f"Something is stuck and policy says ask: {json.dumps(subj, ensure_ascii=False)}")
            t = self.store.get_task(self.st, str(subj.get("task") or ""))
            stakes_node = self.node(str(subj.get("node")
                                        or ((t or {}).get("subject") or {}).get("node") or ""))
            if t and t.get("type") in eflow.EXPENSIVE_TERMINAL_TASKS:
                out.append("- STAKES: this node's training is ALREADY PAID FOR. Rejecting abandons "
                           "the trained node and its sealed evidence over report formatting; "
                           "approving resets the attempts so the report can be fixed.")
            elif stakes_node is not None and self._node_training_paid(stakes_node):
                # same stakes for the widened protection class (stuck
                # eval_launch/metric_bridge/... on a trained node)
                out.append(f"- STAKES: node {stakes_node.get('id')}'s training is ALREADY PAID FOR - "
                           "this gate exists because auto-reject would abandon a trained node over "
                           "a fixable task. Rejecting abandons it; approving resets the attempts.")
            if t:
                out.append(f"- task {t['id']} ({t['type']}) failed {t.get('attempts', 0)} attempt(s); last errors:")
                out.extend(f"  - {e}" for e in (t.get("last_errors") or [])[:5])
            out.append("- approve = retry with reset counters; reject = abandon the stuck lane/node/task")
        out.append("Live view: open .evo/views/DASHBOARD.html in a browser "
                   "(full DAG, frontier, running jobs; auto-refreshes). Text views: .evo/views/GRAPH.md, FRONTIER.md.")
        return out

    def _last_gate_note(self, kind: str, statuses: tuple[str, ...] = ("rejected",)) -> str | None:
        """Latest user decision note on a gate of this kind. The caller picks
        which decision arm can carry a follow-up note -
        infra_canary_blocked's continuable arm is APPROVE (reject terminates
        the project), so the rejected-only default silently discarded the
        user's "here is what I fixed" note on the exact retry it was for."""
        for gt in reversed(self.st.get("gates", [])):
            if gt.get("kind") == kind and gt.get("status") in statuses:
                return gt.get("decision_note")
        return None

    def _find_lane_gate(self, lane: dict) -> dict | None:
        for g in self.st["gates"]:
            if g["kind"] == "idea_approval" and g.get("subject", {}).get("lane") == lane["id"]:
                if g["status"] in ("open", "approved"):
                    return g
        return None

    def _needs_workflow_gate(self, node: dict) -> bool:
        if econfig.lane_purpose(node) in econfig.INSTRUMENTAL_PURPOSES:
            # Instrumental spend is never silently released by full_auto:
            # eflow.GATE_POLICY["workflow_approval"].manual_when lists all three
            # instrumental purposes, and creation must deliver exactly that
            # protection - otherwise under full_auto (any cost class) a
            # repair's retraining would launch with no human decision at all.
            # Every instrumental cap is one per round, so this costs at most a
            # few extra decisions per round and keeps manual_when load-bearing.
            return True
        # The SAME table lists 'exploratory' in manual_when,
        # and carbon-copy lanes (scaling follow-up / confirmatory) buy real
        # training with a duplicated kernel. The auto-resolve guards can only
        # protect a gate this creation path actually makes under full_auto,
        # so creation must match the table and the CLI promise
        # ("exploratory and kernel-copy gates ALWAYS wait for you").
        if econfig.lane_purpose(node) in econfig.EXPLORATORY_PURPOSES:
            return True
        lane_id = str(node.get("lane") or "")
        lane = (self.store.get_lane(self.st, lane_id) or {}) if lane_id else {}
        if lane.get("scaling_followup_of") or lane.get("confirmatory_of"):
            return True
        cost = self._spec(node).get("cost_class", "light")
        mode = self._autonomy()
        if mode == "full_auto":
            return False
        if mode == "gated":
            return cost in ("medium", "heavy")
        return econfig.cost_at_least(cost, self.cfg.get("policy", {}).get("cost_gate_class", "heavy"))

    def _workflow_gate(self, node: dict) -> dict | None:
        for g in reversed(self.st["gates"]):
            if g["kind"] == "workflow_approval" and g.get("subject", {}).get("node") == node["id"] \
                    and g.get("status") in {"open", "paused", "approved", "rejected"}:
                return g
        return None

    def _repeat_spend_gate(self, node: dict, operation: str,
                           stage: str | None = None) -> dict | None:
        repeat = node.get("repeat_attempt") or {}
        repeat_operation = str(repeat.get("operation") or "")
        if repeat_operation != operation and not (
                repeat_operation == "workflow" and operation in {"stage", "eval"}):
            return None
        source_run = str(repeat.get("source_run") or "")
        for gate in reversed(self.st.get("gates", [])):
            subject = gate.get("subject") or {}
            if gate.get("kind") == "repeat_spend" and gate.get("status") in {
                    "open", "paused", "approved", "rejected"} and subject.get("node") == node["id"] \
                    and subject.get("source_run") == source_run:
                return gate
        operation_label = ("whole workflow" if repeat_operation == "workflow" else repeat_operation)
        start_label = (f" beginning at {stage}" if stage and repeat_operation == "workflow" else
                       f" {stage}" if stage else "")
        source_row = self.store.get_run(self.st, source_run) or {}
        # When the failed attempt belongs to the approved repeat
        # buy-back lane, a THIRD exit exists and must be on the decision
        # surface - waiving keeps the paid first measurement and retires this
        # very gate; hiding it compressed a three-way user decision into
        # approve-or-abandon.
        third_exit = (
            " THIRD option (this failure belongs to the approved repeat buy-back lane): "
            "'evo waive-repeat --node " + str(node["id"]) + " --note ...' releases the repeat, "
            "keeps the PAID first measurement as the verdict basis, cancels this gate, and the "
            "node proceeds to analysis - neither a new spend nor an abandonment."
            if source_row.get("repeat_measure_attempt") else "")
        # Decision-surface honesty (same principle as the third exit above):
        # when the source attempt died on a declared budget cap, the user
        # must know BEFORE approving that a deterministic cost profile
        # (registered RNG, unchanged code) makes the replacement spend roughly
        # the SAME amount and fail the SAME cap - approval buys a rerun, not a
        # different number. The remedy for a mis-derived cap is named.
        budget_trap = (
            " CAUTION (budget-cap failure): the failed attempt exceeded a declared budget cap. "
            "If its cost profile is deterministic, a replacement will repeat the same overage and "
            "die the same way; approving then only spends the experiment again. If the cap itself "
            "was mis-derived, correct it on record first - 'evo amend' the node's NODE_SPEC.json "
            "budget.limits with the reason - so the rerun's evidence can be valid. (The intended "
            "FIRST exit for an acceptable overage is earlier: while the source RUN's evidence is "
            "still pending, amending the cap and 'evo run-reconcile --run <source RUN>' adopts the "
            "SAME evidence with no rerun; this gate exists after that evidence was disposed of.)"
            if any("BUDGET_EXCEEDED" in str(e) for e in (source_row.get("evidence_errors") or []))
            else "")
        return self.store.new_gate(
            self.st, "repeat_spend",
            {"node": node["id"], "operation": repeat_operation, "stage": stage,
             "source_run": source_run, "failure_class": repeat.get("failure_class"),
             "repair_scope": repeat.get("repair_scope")},
            f"RUN {source_run} ended with {repeat.get('failure_class') or 'unknown'} failure. "
            f"Approve one replacement {operation_label}{start_label} attempt; reject to stop "
            "this node. This gate never auto-approves because it spends the experiment again."
            + third_exit + budget_trap)

    def _require_repeat_spend_decision(self, node: dict, operation: str,
                                       stage: str | None = None) -> dict | None:
        gate = self._repeat_spend_gate(node, operation, stage)
        if gate is None:
            return None
        if gate.get("status") == "open":
            return self._present_gate(gate)
        if gate.get("status") == "paused":
            return {"kind": "waiting", "reason": f"replacement spend gate {gate.get('id')} is paused by a hold"}
        if gate.get("status") == "rejected":
            return {"kind": "waiting", "reason": f"replacement spend for {node['id']} was rejected"}
        return None

    def _require_repeat_measure_decision(self, node: dict) -> dict | None:
        """An open repeat-measure offer blocks the evaluation
        analysis (the decision changes what that analysis must report)."""
        for gate in reversed(self.st.get("gates", [])):
            if gate.get("kind") == "repeat_measure" \
                    and (gate.get("subject") or {}).get("node") == node["id"] \
                    and gate.get("status") in {"open", "paused", "approved", "rejected"}:
                if gate.get("status") == "open":
                    return self._present_gate(gate)
                if gate.get("status") == "paused":
                    return {"kind": "waiting",
                            "reason": f"repeat_measure gate {gate.get('id')} is paused by a hold"}
                return None
        return None

    def _maybe_auto_resolve(self, gate: dict) -> bool:
        """Resolve a gate automatically when eflow.GATE_POLICY allows it.

        The policy table is the single statement of which gates are protected
        (user-owned under every autonomy mode) and which auto policy applies;
        this method interprets the policy ids; the table is load-bearing.
        """
        policy = eflow.GATE_POLICY.get(str(gate.get("kind") or ""))
        if policy is None:
            return False  # unknown kinds are never auto-resolved (fail closed)
        mode = self._autonomy()
        # manual_when subjects force a user decision even where auto would apply
        if policy.manual_when:
            if gate.get("kind") == "idea_approval":
                # Purpose comes from ENGINE state (the lane), not the
                # agent-authored idea meta: reading the file made the firewall
                # depend on a writable artifact, and a missing/edited file
                # failed OPEN into auto-approval.  The meta file remains a
                # belt-and-suspenders check.
                subj = gate.get("subject") or {}
                lane = self.store.get_lane(self.st, str(subj.get("lane") or "")) or {}
                if lane.get("experiment_purpose") in policy.manual_when:
                    # The ablation allowance is the user's standing pre-authorization:
                    # a design inside it falls through to the ordinary autonomy
                    # policy; anything larger, and every probe or repair, waits.
                    if lane.get("experiment_purpose") != "targeted_ablation" \
                            or not evalid.ablation_design_within_allowance(self.ctx(), lane)[0]:
                        return False
                # A carbon-copy lane (scaling follow-up /
                # confirmatory re-run) buys real training with a duplicated
                # kernel - a spend-shaped decision, user-owned like
                # repeat_spend, never auto-approved.
                if lane.get("scaling_followup_of") or lane.get("confirmatory_of"):
                    return False
                iid = str(subj.get("idea") or "")
                meta = eutil.read_json(eutil.rpath(self.store.repo, f".evo/ideas/{iid}.meta.json"), {}) or {}
                meta_purpose = meta.get("experiment_purpose")
                if meta_purpose in policy.manual_when:
                    if meta_purpose != "targeted_ablation" or lane.get("experiment_purpose") != "targeted_ablation" \
                            or not evalid.ablation_design_within_allowance(self.ctx(), lane)[0]:
                        return False
            if gate.get("kind") == "workflow_approval":
                subj = gate.get("subject") or {}
                node = self.node(str(subj.get("node") or "")) or {}
                if node.get("experiment_purpose") in policy.manual_when:
                    if node.get("experiment_purpose") != "targeted_ablation" \
                            or not evalid.ablation_spec_within_allowance(self.ctx(), node, self._spec(node))[0]:
                        return False
                lane = self.store.get_lane(self.st, str(node.get("lane") or "")) or {}
                if lane.get("scaling_followup_of") or lane.get("confirmatory_of"):
                    return False
        auto_policy = policy.auto
        if auto_policy == "never":
            return False
        if auto_policy == "provision_full_auto_reject":
            # never auto-approvable: approval means the USER supplied resources.
            # An unattended run cannot do that - stop deterministically instead
            # of looping on the same blockers forever.
            if mode == "full_auto":
                self._decide_gate(gate, approve=False,
                                  note="auto: unattended run cannot supply missing resources",
                                  actor="engine")
                return True
            return False
        if auto_policy == "escalation_on_stuck":
            # A launch waiting on a busy shared machine is nobody's failure:
            # whatever on_stuck says, only a person decides to keep waiting
            # or to stop - an unattended reject would abandon a node over a
            # colleague's job.
            if (gate.get("subject") or {}).get("reason") == "resources_busy":
                return False
            # The drill escalation inside a pending facts
            # revision decides between re-proving and ROLLING BACK the
            # revision - both are user calls on a mid-rounds project; an
            # unattended reject here would bury paid work over an environment
            # flake.
            subj_task = self.store.get_task(self.st, str((gate.get("subject") or {}).get("task") or ""))
            if subj_task is not None and subj_task.get("type") == "infra_drill" \
                    and self.st.get("infra_revision_pending"):
                return False
            if mode == "full_auto" and self.cfg.get("policy", {}).get("on_stuck") == "abandon":
                # Never auto-reject the escalation of an expensive
                # terminal task - the reject would abandon the fully-trained
                # node, which is exactly what its protection exists to prevent.
                # The gate waits for the user instead.
                subj_task = self.store.get_task(self.st, str((gate.get("subject") or {}).get("task") or ""))
                if subj_task and subj_task.get("type") in eflow.EXPENSIVE_TERMINAL_TASKS:
                    return False
                # Same protection for NODE-subject escalations raised after the
                # node's training already ran (eval-failure exhaustion): an
                # auto-reject would abandon a fully trained node unattended.
                # A stuck-TASK escalation carries the node too
                # now, but resolve it through the task as well so an older
                # task-only gate row can never dodge the trained-node guard.
                subj_node = self.node(str((gate.get("subject") or {}).get("node")
                                          or ((subj_task or {}).get("subject") or {}).get("node") or ""))
                if subj_node and self._node_training_paid(subj_node):
                    return False
                self._decide_gate(gate, approve=False, note="auto: on_stuck=abandon", actor="engine")
                return True
            return False
        approve = False
        if auto_policy == "auto_or_full_approve":
            approve = mode in ("auto", "full_auto")
        elif auto_policy == "round_continue":
            approve = mode == "full_auto" or (
                mode == "auto" and self.cfg.get("budgets", {}).get("rounds_max", 0) > 0)
        elif auto_policy == "workflow_cost":
            nid = gate.get("subject", {}).get("node")
            node = self.node(nid) if nid else None
            spec = self._spec(node) if node else {}
            # Money is protected BEFORE it is spent: whatever the autonomy, a
            # declared cap or the agent's own estimate above the user's node
            # ceiling puts the gate in front of a person with the numbers
            # side by side (the engine projects nothing itself).
            if node and evalid.workflow_spend_review(self.ctx(), node, spec)[1]:
                return False
            if mode == "full_auto":
                approve = True
            elif mode == "auto":
                cost = spec.get("cost_class", "heavy")
                approve = not econfig.cost_at_least(
                    cost, self.cfg.get("policy", {}).get("cost_gate_class", "heavy"))
        if approve:
            self._decide_gate(gate, approve=True, note=f"auto-approved (autonomy={mode})", actor="engine")
            return True
        return False

    def decide(self, gate_id: str, approve: bool, note: str | None, retry_stage: str | None) -> dict:
        self._assert_frozen_contract()
        gate = self.store.get_gate(self.st, gate_id)
        if gate is None:
            raise SystemExit(f"[evo] no gate {gate_id}; 'evo next' presents the pending gate "
                             "('evo status' lists open gates)")
        subject = gate.get("subject") or {}
        self._assert_artifact_seals(only_lane=str(subject.get("lane") or "") or None,
                                    only_node=str(subject.get("node") or "") or None)
        if gate["status"] != "open":
            raise SystemExit(f"[evo] gate {gate_id} already {gate['status']}; nothing to decide - run "
                             "'evo next' for the current card")
        # Re-check holds at the DECISION point. Hold creation pauses the
        # gates that exist at that moment; a gate created afterwards (e.g. a
        # propose-abandon injected during a repairing recovery) could be
        # decided inside the hold's scope and mutate authority the brake was
        # protecting - abandoning a node out from under its active recovery.
        holding = erecover.active_holds_for_subject(
            self.st, self.g,
            lane=str(subject.get("lane") or "") or None,
            node=str(subject.get("node") or "") or None,
            run=str(subject.get("run") or "") or None,
            round_=str(subject.get("round") or "") or None)
        authorized = {str(case.get("hold")) for case in self.st.get("recoveries", [])
                      if case.get("status") == "replaying" and case.get("hold")}
        holding = [h for h in holding if h not in authorized]
        if holding:
            raise SystemExit("[evo] gate " + gate_id + " is inside the scope of active hold(s) "
                             + ", ".join(holding)
                             + "; resume the hold or complete its recovery before deciding it")
        out = self._decide_gate(gate, approve=approve, note=note, actor="user", retry_stage=retry_stage)
        self.save()
        return out

    def _rollback_infra_revision(self, task: dict, *, note: str | None) -> None:
        """Give up on an adopted-but-unproven facts revision (S2).

        The pre-revision snapshot was archived at approval; restore it, move
        the rejected revision aside for the record, re-stamp the prior
        digest, clear the pending window, and retire the drill task. The
        project continues under the facts that WERE proven."""
        info = self.st.get("infra_revision") if isinstance(self.st.get("infra_revision"), dict) else {}
        facts_rel = str((self.cfg.get("infra") or {}).get("facts_file")
                        or ".evo/profile/INFRA_FACTS.json")
        facts_path = eutil.rpath(self.store.repo, facts_rel)
        archived_rel = str(info.get("archived") or "")
        archived_path = eutil.rpath(self.store.repo, archived_rel) if archived_rel else None
        rejected_rel = f".evo/profile/INFRA_FACTS.rejected-{eutil.utc_now().replace(':', '')}.json"
        if facts_path.exists():
            shutil.copy2(facts_path, eutil.rpath(self.store.repo, rejected_rel))
        restored = eutil.read_json(archived_path, None) if archived_path is not None else None
        if isinstance(restored, dict):
            # one atomic replacement; the archived copy stays as the audit
            # record - the facts file never has an absent window
            eutil.write_json_atomic(facts_path, restored)
        prior_digest = str(info.get("prior_digest") or "")
        if prior_digest:
            self.st["bootstrap_infra_facts_digest"] = prior_digest
            self.st.setdefault("profile_digests", {})["infra_facts"] = prior_digest
        self.st["infra_revision_pending"] = False
        self.st.pop("infra_revision", None)
        task["status"] = "cancelled"
        task.pop("_render", None)
        task["updated_at"] = eutil.utc_now()
        self.store.event("user", "infra_revision_rolled_back",
                         rejected=rejected_rel, restored=archived_rel, note=note)
        # parked launch cards may reopen: the proven facts are back in force
        print("[evo] the facts revision was rolled back; the previously proven facts are "
              "restored and parked work resumes ('evo next')")

    def _decide_gate(self, gate: dict, *, approve: bool, note: str | None, actor: str,
                     retry_stage: str | None = None) -> dict:
        # Several decision arms abandon nodes/lanes. Detect any
        # graph-shaped change across this decision and re-render the formal
        # consumers in the same persisted step (see _sync_graph_consumers).
        graph_sig_before = self._graph_consumer_sig()
        try:
            return self._decide_gate_inner(gate, approve=approve, note=note, actor=actor,
                                           retry_stage=retry_stage)
        finally:
            if self._graph_consumer_sig() != graph_sig_before:
                self._sync_graph_consumers()

    def _decide_gate_inner(self, gate: dict, *, approve: bool, note: str | None, actor: str,
                           retry_stage: str | None = None) -> dict:
        if gate.get("kind") == "idea_approval":
            lane_now = self.store.get_lane(self.st, (gate.get("subject") or {}).get("lane"))
            if lane_now is None or (gate.get("subject") or {}).get("contract_digest") != \
                    self._idea_contract_digest(lane_now):
                raise SystemExit("[evo] idea approval does not match the active sealed idea+review contract; "
                                 "approval was not recorded - run 'evo next' to re-render the gate "
                                 "against the current contract ('evo doctor' if it persists)")
        if gate.get("kind") == "workflow_approval":
            node_now = self.node(str((gate.get("subject") or {}).get("node") or "")) or {}
            if (gate.get("subject") or {}).get("contract_digest") != \
                    str((node_now.get("spec_seal") or {}).get("digest") or ""):
                raise SystemExit("[evo] workflow approval does not match the active sealed NODE_SPEC; "
                                 "approval was not recorded - run 'evo next' to re-render the gate "
                                 "against the current spec ('evo doctor' if it persists)")
        if gate.get("kind") == "abandon_request" and approve:
            # The hold guard tested only the DECLARED
            # subject, but approving a lane abandonment cascades to lane.node -
            # a node-scoped hold (the standing brake of a pending recovery) was
            # walked straight past because the gate named only the lane. Expand
            # to the transition's effect closure before recording the decision.
            lane_row = self.store.get_lane(self.st, str((gate.get("subject") or {}).get("lane") or ""))
            eff_node = str((lane_row or {}).get("node") or "") or \
                str((gate.get("subject") or {}).get("node") or "")
            if eff_node:
                covering = erecover.active_holds_for_subject(self.st, self.g, node=eff_node)
                # Same replaying-recovery exemption as the declared-subject
                # guard above: an authorized hold must not block the abandon
                # decision on one subject spelling but not the other.
                replay_authorized = {str(case.get("hold")) for case in self.st.get("recoveries", [])
                                     if case.get("status") == "replaying" and case.get("hold")}
                covering = [h for h in covering if h not in replay_authorized]
                if covering:
                    raise SystemExit(f"[evo] approving this abandonment would retire node {eff_node}, "
                                     f"which is under active hold(s) {', '.join(covering)}; finish that "
                                     "recovery first ('evo recover-status' names the step: recover-apply / "
                                     "recover-abort) or resume the hold ('evo resume --hold <id> --note "
                                     "...') - decision not recorded")
        if gate.get("kind") == "round_continue" and not approve:
            # Rejecting round continuation writes phase=done. Done must not
            # bury an in-flight recovery - the case and its hold would survive
            # invisibly with no next ever presenting them again;
            # repairing/replaying count too (their RUN may be in flight; DONE
            # would bury live training).
            pending_case = self._pending_recovery_case()
            if pending_case is not None:
                raise SystemExit(f"[evo] recovery {pending_case.get('id')} is still "
                                 f"{pending_case.get('status')} - "
                                 + self._recovery_review_hint(pending_case)
                                 + "; finish it before ending the project ('evo recover-status' "
                                   "reprints this step) - decision not recorded")
        if gate.get("kind") == "infra_canary_blocked":
            canary_task = self.store.get_task(
                self.st, str((gate.get("subject") or {}).get("task") or "")) or {}
            canary_record = canary_task.get("infra_canary_run") or {}
            canary_errs = ecanary.record_errors(
                self.store, canary_record, expect_task=canary_task.get("id"))
            if canary_errs or canary_record.get("status") != "blocked":
                raise SystemExit("[evo] blocked infrastructure canary evidence changed; gate decision "
                                 "was not recorded - run 'evo next' to re-render the gate against the "
                                 "current record:\n  - "
                                 + "\n  - ".join(canary_errs or ["CANARY_RUN_NOT_BLOCKED"]))
        if gate.get("kind") == "infra_confirm" and approve:
            errs = econfig.validate_config(self.cfg)
            errs.extend(econfig.preset_conflicts(eutil.read_json(self.store.config_path) or {}))
            facts = einfra.load_facts(self.store, self.cfg)
            errs.extend(einfra.validate_facts(self.store, facts))
            if errs:
                raise SystemExit("[evo] bootstrap contract is no longer valid; approval was not recorded - "
                                 "fix the listed fields in .evo/config.json (or reject this gate with a "
                                 "note so configure is rebuilt), then decide again:\n  - "
                                 + "\n  - ".join(errs))
            reviewed = str((self.st.get("profile_digests") or {}).get("bootstrap_review_config") or "")
            current = econfig.bootstrap_contract_digest(self.cfg)
            if not reviewed or current != reviewed:
                raise SystemExit(
                    "[evo] success/resource fields changed after INFRA_REVIEW was written; approval was "
                    "not recorded. Reject this gate with a note so project_scan/configure/infra review "
                    "are rebuilt from the changed contract.")
            reviewed_facts = str((self.st.get("profile_digests") or {}).get("infra_facts") or "")
            current_facts = ecanary.facts_digest(self.store, self.cfg)
            if not reviewed_facts or current_facts != reviewed_facts:
                raise SystemExit(
                    "[evo] INFRA_FACTS changed after the infrastructure task was validated; approval was "
                    "not recorded. Reject this gate so the infrastructure review is rebuilt from the "
                    "changed resource manifest.")
        if retry_stage and gate.get("kind") != "idea_approval":
            # --retry-stage is an idea-gate verb. argparse offers it on every
            # gate, and on an escalation gate the reject branch never reads it:
            # the flag was accepted with exit 0 and the lane abandoned anyway,
            # which on an instrumental lane also burned the round's only slot.
            # (An escalation's rewind is --approve, which resumes at the
            # recorded resume_stage with the cycle counters reset.)
            raise SystemExit(
                f"[evo] --retry-stage applies to an idea_approval gate; {gate.get('id')} is a "
                f"{gate.get('kind')} gate. Approve it to retry, or reject it without "
                f"--retry-stage to abandon. The gate is still open.")
        if gate.get("kind") == "idea_approval" and not approve and retry_stage:
            # A rewind stage belongs to a lane FAMILY. argparse offers every
            # stage for every gate, so a stage the lane does not have must not
            # fall through the dispatch chain to the abandon branch: the lane
            # would be destroyed with no hint that the requested rewind was
            # impossible, and since the cap counts lanes opened, the round's
            # instrumental slot would go with it, unrecoverable.
            # Refuse before anything mutates - the gate stays open, so the user
            # simply decides again with a stage that exists.
            lane_for_stage = self.store.get_lane(self.st, (gate.get("subject") or {}).get("lane")) or {}
            purpose_for_stage = econfig.lane_purpose(lane_for_stage)
            seq_for_stage = eflow.INSTRUMENTAL_SEQ.get(purpose_for_stage)
            legal_stages = ((seq_for_stage[0],) if seq_for_stage is not None
                            else ("sketch", "mature", "pose", "theorize"))
            if retry_stage not in legal_stages:
                raise SystemExit(
                    f"[evo] --retry-stage {retry_stage} is not a stage a {purpose_for_stage} lane has; "
                    f"legal for this gate: {'|'.join(legal_stages)}. The gate is still open - decide it "
                    f"again with a legal stage, or reject without --retry-stage to abandon the lane.")
        if gate.get("kind") == "idea_approval" and not approve and retry_stage in ("pose", "theorize"):
            lane = self.store.get_lane(self.st, (gate.get("subject") or {}).get("lane"))
            if (lane or {}).get("search_origin") == "theory_derived":
                raise SystemExit("[evo] a theory-derived program cannot reopen its source theorem after program "
                                 "selection; reject with --retry-stage sketch only if the same sealed theory "
                                 "remains the source, or open a new theory-derived lane (next open_round "
                                 "portfolio) for a changed theorem. The gate is still open.")
            winner = self.ctx().winner_sketch(lane or {}) or {}
            role = str(winner.get("theory_role") or "none")
            if role == "none":
                raise SystemExit("[evo] this winner froze theory_role='none'; retry sketch to change the "
                                 "scientific contract rather than attaching post-selection theory")
            if retry_stage == "pose" and role != "derivational":
                raise SystemExit("[evo] pose is legal only for a winner that precommitted derivational theory; "
                                 "reject with --retry-stage sketch (or theorize) instead. The gate is still open.")
        if gate.get("kind") == "posthoc_claim":
            # Everything that can refuse a post-hoc claim decision runs BEFORE
            # the gate row or the event log changes: a refusal has no side
            # effects (the gate stays open, no orphan decision event).
            import eseal
            claim_subject = gate.get("subject") or {}
            claim_record = next((c for c in self.st.get("posthoc_claims", [])
                                 if str(c.get("id") or "") == str(claim_subject.get("claim") or "")), None)
            claim_node = self.node(str(claim_subject.get("node") or ""))
            if claim_record is None or claim_node is None:
                raise SystemExit(f"[evo] post-hoc claim gate {gate.get('id')} names an unknown claim/node; the "
                                 "gate is still open - run 'evo doctor'")
            if approve:
                refusal = self.posthoc_claim_refusal(claim_node, claim_record)
                if refusal:
                    raise SystemExit("[evo] " + refusal)
                errs = eseal.verify(self.store.repo, claim_record.get("proposal_seal"),
                                    label=f"claim {claim_record.get('id')} proposal")
                if errs:
                    raise SystemExit("[evo] the claim changed since it was filed; decision not applied - "
                                     "restore the proposal file to its filed bytes, or reject this gate and "
                                     "re-file with 'evo claim':\n  - "
                                     + "\n  - ".join(errs))
        gate["status"] = "approved" if approve else "rejected"
        if gate.get("kind") == "idea_approval" and not approve:
            gate["retry_stage"] = retry_stage
        gate["decision_note"] = note
        gate["decided_at"] = eutil.utc_now()
        self.store.event(actor, "gate_decided", gate=gate["id"], kind=gate["kind"],
                         decision=gate["status"], note=note)
        kind, subj = gate["kind"], gate.get("subject", {})
        # On these kinds a REJECT leaves the subject's task open and
        # unchanged, so the user's correction note lived only on the gate row -
        # a fresh session re-read the same card/bundle with no trace of what
        # the user actually asked for, and a blind resubmit burned an attempt.
        # Route the note into the still-open task's rejection surface (the
        # bundle prints it verbatim) and re-render the card from it.
        if not approve and str(note or "").strip() and kind in ("human_study_confirm", "abandon_request"):
            # The owner is matched by IDENTITY, never by status - a task
            # parked by a hold (paused+queued_after_hold) or stuck must not
            # miss the delivery, or the user's exact corrections would live
            # only in gate history and the reopened card would show a
            # generic rejection. A paused/stuck owner gets the note
            # stamped now; its own reopen path rematerializes the card from
            # current truth (last_errors included).
            target = next(
                (t for t in self.st.get("tasks", [])
                 if t.get("status") in ("open", "paused", "stuck") and (
                     (subj.get("task") and t.get("id") == subj.get("task"))
                     or (subj.get("node") and (t.get("subject") or {}).get("node") == subj.get("node"))
                     or (subj.get("lane") and (t.get("subject") or {}).get("lane") == subj.get("lane")))),
                None)
            if target is not None:
                marker = f"USER DECISION ({kind} rejected): {note}"
                errs = [e for e in (target.get("last_errors") or []) if not str(e).startswith("USER DECISION (")]
                target["last_errors"] = errs + [marker]
                target["updated_at"] = eutil.utc_now()
                if target.get("status") == "open" and target.get("_render"):
                    self._rematerialize(target)
        if kind == "infra_confirm":
            if not approve:
                done = self.st.get("bootstrap_done", [])
                self.st["bootstrap_done"] = [d for d in done
                                             if d not in ("project_scan", "provision", "configure",
                                                          "infra", "infra_interview")]
                # the rescan re-judges readiness AND engine fit from scratch
                self.st["engine_fit_gate"] = None
                self.st["infra_gate"] = None
                self.st["config_frozen"] = False
                self.st["bootstrap_contract_confirmed"] = False
                self.st["bootstrap_contract_digest"] = None
                self.st["bootstrap_infra_facts_digest"] = None
                self.st["bootstrap_terminated"] = False
                self.st.setdefault("profile_digests", {}).pop("bootstrap_review_config", None)
                self.st.setdefault("profile_digests", {}).pop("infra_facts", None)
                self.store.event(actor, "infra_rescan_requested", note=note)
            else:
                self.st["config_frozen"] = True
                self.st["bootstrap_contract_confirmed"] = True
                self.st["bootstrap_contract_digest"] = current
                self.st["bootstrap_infra_facts_digest"] = current_facts
                self.store.event(actor, "bootstrap_contract_confirmed",
                                 resources=econfig.resource_limits(self.cfg))
        elif kind == "infra_canary_blocked":
            if not approve and self.st.get("infra_revision_pending"):
                # Inside a facts-revision window this
                # reject means "give up on the revision", NOT "stop the
                # project" - the mid-rounds project rolls back to the proven
                # facts and continues (same semantics as the drill
                # escalation's reject).
                drill = self.store.get_task(self.st, str((gate.get("subject") or {}).get("task") or ""))
                if drill is not None:
                    self._rollback_infra_revision(drill, note=note)
                    return
            if not approve:
                # Every semantic stop lands through the one writer
                self.st["bootstrap_terminated"] = True
                self._write_terminal_phase(
                    "infrastructure canary blocked and resources not supplied",
                    event="evolution_stopped", note=note)
            else:
                self.store.event(actor, "infra_canary_retry_authorized", task=subj.get("task"), note=note)
            # On approval infra_drill is still absent from bootstrap_done, so
            # the scheduler creates a fresh task and the engine issues a fresh nonce.
        elif kind == "resource_approval":
            # Decide on LIVE capacity. The approve side caps its grant on live
            # capacity; a reject on the frozen deficit would destroy a node
            # whose increase is not needed at all.
            if not subj.get("probe_cap_over") and not self._resource_deficit(subj.get("request") or {}):
                gate["status"] = "cancelled"
                gate["resolved_at"] = eutil.utc_now()
                gate["note"] = ("capacity returned before this decision; no contract change was needed "
                                f"(recorded decision: {'approve' if approve else 'reject'})")
                self.store.event(actor, "gate_cancelled", gate=gate["id"],
                                 reason="resource_deficit_cleared_at_decision", note=note)
                self.save()
                return {"gate": gate["id"], "status": gate["status"]}
            if approve:
                probe_over = subj.get("probe_cap_over") or {}
                if probe_over:
                    # probe-cap overrun: raise THIS node's cap by exactly the
                    # approved overage; the project contract is untouched
                    node = self.node(str(subj.get("node") or ""))
                    if node is not None:
                        extra = node.setdefault("probe_cap_extra", {})
                        for unit, pair in probe_over.items():
                            try:
                                overage = float(pair[0]) - float(pair[1])
                            except (TypeError, ValueError, IndexError):
                                continue
                            extra[str(unit)] = float(extra.get(str(unit), 0.0) or 0.0) + max(overage, 0.0)
                        egraph.touch(node)
                    self.store.event(actor, "probe_cap_extended", node=subj.get("node"),
                                     operation=subj.get("operation"), stage=subj.get("stage"),
                                     additions=probe_over, note=note)
                else:
                    overrides = self.st.setdefault("resource_overrides", {})
                    # Grant what is STILL missing, capped at what the user
                    # was shown - capacity released between presentation and
                    # decision must not be double-purchased into the contract.
                    shown = {str(u): float(a) for u, a in (subj.get("deficit") or {}).items()
                             if isinstance(a, (int, float)) and not isinstance(a, bool)}
                    current = self._resource_deficit(subj.get("request") or {})
                    granted = {u: min(a, float(current.get(u, 0.0))) for u, a in shown.items()
                               if float(current.get(u, 0.0)) > 0}
                    for unit, amount in granted.items():
                        overrides[unit] = float(overrides.get(unit, 0.0) or 0.0) + float(amount)
                    self.store.event(actor, "resource_limit_extended", node=subj.get("node"),
                                     operation=subj.get("operation"), stage=subj.get("stage"),
                                     additions=granted, presented=shown, note=note)
            else:
                node = self.node(str(subj.get("node") or ""))
                if node:
                    if node.get("role") == "baseline":
                        self._write_terminal_phase(
                            "baseline evaluation cannot fit the approved resource contract",
                            event="evolution_stopped", note=note)
                    else:
                        self._abandon_node(
                            node,
                            (f"probe-cap increase rejected: {note or 'no note'}"
                             if subj.get("probe_cap_over")
                             else f"project resource-limit increase rejected: {note or 'no note'}"))
        elif kind == "provision_blocked":
            if not approve:
                # no resources forthcoming and the project cannot reach a first
                # real number: nothing downstream is meaningful - stop with the
                # reason on record
                self._write_terminal_phase("preparation blocked and resources not supplied",
                                           event="evolution_stopped", note=note)
            # approve: the scheduler re-issues a fresh provision cycle with the
            # note + previous blockers in the bundle (multi-round retry)
        elif kind == "infra_revision":
            if approve:
                facts_rel = str((self.cfg.get("infra") or {}).get("facts_file")
                                or ".evo/profile/INFRA_FACTS.json")
                facts_path = eutil.rpath(self.store.repo, facts_rel)
                proposed_path = eutil.rpath(self.store.repo, ".evo/profile/INFRA_FACTS_PROPOSED.json")
                proposed = eutil.read_json(proposed_path, None)
                perrs = einfra.validate_facts(self.store, proposed)
                if proposed is None or perrs:
                    raise SystemExit("[evo] the proposed facts vanished or became invalid since the "
                                     "gate opened; re-run 'evo revise-infra' with a valid proposal"
                                     + ("\n  - " + "\n  - ".join(perrs) if perrs else ""))
                want_digest = str((subj or {}).get("proposed_digest") or "")
                if want_digest and ecanary.facts_digest_of(proposed) != want_digest:
                    raise SystemExit("[evo] the PROPOSED facts changed since this gate opened - the "
                                     "approval must adopt exactly the bytes it reviewed; re-run "
                                     "'evo revise-infra' to open a fresh gate for the new proposal")
                # The swap must never leave a
                # window where the facts file is ABSENT (every command dies at
                # the frozen-contract assertion with no documented recovery).
                # COPY the old bytes aside, then ONE atomic replacement writes
                # the new bytes - at every crash point the facts file exists
                # and is complete old or complete new. The PROPOSED file is
                # retained as the revision record (and makes an approve retry
                # after a torn commit idempotent).
                archived_rel = f".evo/profile/INFRA_FACTS.superseded-{eutil.utc_now().replace(':', '')}.json"
                if facts_path.exists():
                    shutil.copy2(facts_path, eutil.rpath(self.store.repo, archived_rel))
                eutil.write_json_atomic(facts_path, proposed)
                prior_digest = str(self.st.get("bootstrap_infra_facts_digest") or "")
                new_digest = ecanary.facts_digest_of(proposed)
                self.st["bootstrap_infra_facts_digest"] = new_digest
                self.st.setdefault("profile_digests", {})["infra_facts"] = new_digest
                # the old canary proof is about the OLD facts: re-owe it, and
                # refuse new spend until the fresh proof lands. Keep the
                # rollback coordinates (S2): rejecting the re-proof restores
                # the archived, previously-proven snapshot.
                self.st["infra_revision_pending"] = True
                self.st["infra_revision"] = {"archived": archived_rel,
                                             "prior_digest": prior_digest}
                # bootstrap-era revision (post-approval, pre/mid drill): the
                # bootstrap scheduler re-mints the drill when it is not in
                # bootstrap_done; rounds-era re-minting is the 2c branch
                self.st["bootstrap_done"] = [d for d in self.st.get("bootstrap_done", [])
                                             if d != "infra_drill"]
                self.store.event(actor, "infra_revision_adopted",
                                 changed_blocks=(subj or {}).get("changed_blocks"),
                                 archived=archived_rel, note=note)
                # An OPEN launch card would hold the
                # one-open-card floor forever - the scheduler then never
                # reaches the 2c branch that mints the canary re-proof, while
                # the card's own submission is refused with
                # INFRA_REVISION_UNPROVEN: a mutual-prerequisite standstill.
                # Park launch cards (reopen-pump shape); the pump re-presents
                # them once the fresh canary proof lands. Other execution
                # cards are not refused by the pending window - just rebuild
                # their platform-convention blocks from current truth.
                for t in self.st.get("tasks", []):
                    if t.get("status") == "open" and t.get("type") in (
                            "stage_launch", "eval_launch"):
                        t["status"] = "paused"
                        t["queued_after_hold"] = True
                        t["held_by"] = []
                        t.pop("presented_at", None)
                        t["updated_at"] = eutil.utc_now()
                        self.store.event("engine", "task_parked_for_infra_revision",
                                         task=t.get("id"))
                for t in self.st.get("tasks", []):
                    if t.get("status") in ("open", "paused") and t.get("type") in (
                            "implement", "smoke", "rehearsal", "stage_launch", "eval_launch",
                            "stage_watch", "infra_drill"):
                        self._rematerialize(t)
                    elif t.get("status") == "open" and t.get("type") == "open_round":
                        # The strategist plans lane
                        # COUNT from the slot quota on its card - a revised
                        # quota must reach the open strategy card too
                        self._refresh_open_round_task(t)
            else:
                self.store.event(actor, "infra_revision_rejected", note=note,
                                 changed_blocks=(subj or {}).get("changed_blocks"))
        elif kind == "engine_fit_blocked":
            if approve:
                self.store.event(actor, "engine_fit_overridden", note=note,
                                 overall=self._engine_fit_overall())
            else:
                self._write_terminal_phase(
                    "engine-fit assessment rejected: this project is outside what the engine "
                    "can promise (see .evo/profile/PROJECT_DISCOVERY.md for the exact gap)",
                    event="evolution_stopped", note=note)
        elif kind == "idea_approval":
            lane = self.store.get_lane(self.st, subj.get("lane"))
            if lane:
                # Which rewind stages exist depends on WHAT THE LANE IS, and the
                # two families own disjoint ones.  Both are named positively,
                # off the one route table - never as "purpose !=
                # targeted_ablation" meaning "is a candidate", a negative form
                # that would match probe/maintenance too and drive a rejected
                # probe into candidate-only machinery (resynthesis, winner
                # theory), parked in a status its own route never contains.
                # A lane record with no purpose reads as a candidate
                # (econfig.lane_purpose), as everywhere else in the engine.
                purpose = econfig.lane_purpose(lane)
                instrumental_seq = eflow.INSTRUMENTAL_SEQ.get(purpose)
                if approve:
                    lane["status"] = "approved"
                elif instrumental_seq is not None and retry_stage == instrumental_seq[0]:
                    # Instrumental lanes need the same "revise, do not discard"
                    # path every other purpose has: without it, the manual gate
                    # the design deliberately relies on could only ever abandon
                    # the lane, so using the quality gate cost the round's whole
                    # instrumental budget.  A lane may only rewind to its OWN
                    # design stage - the first status of its own route.
                    self._supersede_idea_revision(lane, verdict="USER_REVISE", review=None)
                    lane["status"] = retry_stage
                    self.store.event(actor, "lane_retry", lane=lane["id"], stage=retry_stage)
                elif purpose in ("candidate", "exploratory") and retry_stage == "sketch":
                    self._prepare_resynthesis(lane, verdict="USER_REJECT_SKETCH", note=note, gate=gate.get("id"))
                    lane["status"] = "sketch"
                    self.store.event(actor, "lane_retry", lane=lane["id"], stage=retry_stage)
                elif purpose in ("candidate", "exploratory") and retry_stage in ("pose", "theorize"):
                    self._supersede_idea_revision(lane, verdict="USER_REVISE_THEORY", review=None)
                    self._reopen_winner_theory(lane, retry_stage=retry_stage)
                    self.store.event(actor, "lane_retry", lane=lane["id"], stage=retry_stage)
                elif purpose in ("candidate", "exploratory") and retry_stage == "mature":
                    self._supersede_idea_revision(lane, verdict="USER_REVISE", review=None)
                    lane["status"] = "mature"
                    self.store.event(actor, "lane_retry", lane=lane["id"], stage=retry_stage)
                else:
                    self._abandon_lane(lane, f"idea rejected at user gate: {note or 'no note'}")
        elif kind == "abandon_request":
            # The early-exit verb: approve = the USER ratifies the agent's
            # judgment that this direction is dead; the stop is deliberate,
            # reasoned, and cheap - not an attempts-exhaustion failure.
            # Reject = keep going; the decision note reaches the next task
            # bundle like any other gate note.
            reason = str(subj.get("reason") or "no reason recorded")
            if approve:
                if subj.get("node"):
                    node = self.node(str(subj.get("node")))
                    if node and node.get("status") not in ("concluded", "abandoned"):
                        self.store.event(actor, "deliberate_stop", node=node.get("id"),
                                         reason=reason, note=note)
                        self._abandon_node(node, f"deliberate stop (user-approved): {reason}")
                elif subj.get("lane"):
                    lane = self.store.get_lane(self.st, subj.get("lane"))
                    if lane and lane.get("status") not in ("done", "abandoned"):
                        self.store.event(actor, "deliberate_stop", lane=lane.get("id"),
                                         reason=reason, note=note)
                        self._abandon_lane(lane, f"deliberate stop (user-approved): {reason}")
            else:
                self.store.event(actor, "deliberate_stop_rejected",
                                 lane=subj.get("lane"), node=subj.get("node"), note=note)
        elif kind == "workflow_approval":
            if not approve:
                nid = subj.get("node")
                node = self.node(nid)
                if node:
                    self._abandon_node(node, f"workflow execution rejected: {note or 'no note'}")
        elif kind == "repeat_spend":
            node = self.node(str(subj.get("node") or ""))
            if node:
                active = node.get("repeat_attempt") or {}
                if str(active.get("source_run") or "") != str(subj.get("source_run") or ""):
                    raise SystemExit("[evo] repeat-spend gate no longer matches the active failed attempt; "
                                     "nothing recorded - run 'evo next' for the current card")
                if approve:
                    node.pop("repeat_attempt", None)
                    self.store.event(actor, "repeat_spend_authorized", node=node["id"],
                                     operation=subj.get("operation"), stage=subj.get("stage"),
                                     source_run=subj.get("source_run"), note=note)
                else:
                    self._abandon_node(node, f"replacement execution rejected: {note or 'no note'}")
        elif kind == "repeat_measure":
            # Approval buys back exactly one measurement. The node
            # keeps its normal life either way - rejection just keeps the
            # single-run verdict as measured, with the decision on record.
            node = self.node(str(subj.get("node") or ""))
            if node:
                if approve:
                    node["repeat_measure"] = {
                        "cell": subj.get("cell"), "result_key": subj.get("result_key"),
                        "band": subj.get("band"), "band_source": subj.get("band_source"),
                        "lines": list(subj.get("lines") or []),
                        "base_seed": subj.get("base_seed"), "seed": subj.get("seed"),
                        "approved_at": eutil.utc_now(), "gate": gate.get("id"),
                        # Approval hands the repeat to the ENGINE - a
                        # full workflow+eval pair of first-class RUNs. The
                        # resume snapshot is how a user waive restores the
                        # node's pre-repeat position without replaying the
                        # preplanned lanes.
                        "engine_run": True,
                        "resume": {"stage_cursor": node.get("stage_cursor"),
                                   "replica_index": node.get("replica_index"),
                                   "status": node.get("status")}}
                    node["repeat_pending_seed"] = subj.get("seed")
                    node["stage_cursor"] = 0
                    node["status"] = "stage_ready"
                    egraph.touch(node)
                    self.store.event(actor, "repeat_measure_authorized", node=node["id"],
                                     cell=subj.get("cell"), seed=subj.get("seed"), note=note)
                else:
                    node["repeat_measure_done"] = True
                    egraph.touch(node)
                    self.store.event(actor, "repeat_measure_rejected", node=node["id"],
                                     cell=subj.get("cell"), note=note)
        elif kind == "escalation":
            if subj.get("reason") == "resources_busy" and subj.get("task"):
                # A launch that keeps finding the shared machine busy is an
                # OPEN card, not a stuck one, so the stuck-epoch arm below
                # (whose staleness test is "still stuck?") would retire this
                # decision as superseded. Approve = keep waiting: the card
                # stays open and the wait window restarts from this decision
                # (esched._submit_launch_busy measures from it). Reject = stop
                # waiting: nothing was trained; the node is abandoned like any
                # other launch that never happened.
                task = self.store.get_task(self.st, subj["task"])
                if task is None or task.get("status") not in ("open", "paused"):
                    stale = ("the task no longer exists" if task is None
                             else f"the launch card is now '{task.get('status')}'")
                    gate["status"] = "cancelled"
                    gate["resolved_at"] = eutil.utc_now()
                    gate["note"] = (f"superseded before this decision: {stale} "
                                    f"(recorded decision: {'approve' if approve else 'reject'})")
                    self.store.event(actor, "gate_cancelled", gate=gate["id"],
                                     reason="escalation_subject_settled", detail=stale, note=note)
                    self.save()
                    return {"gate": gate["id"], "status": gate["status"]}
                if approve:
                    render = task.setdefault("_render", {})
                    blocks = [(str(row[0]), list(row[1]))
                              for row in (render.get("extra_blocks") or [])
                              if isinstance(row, (list, tuple)) and len(row) == 2
                              and str(row[0]) != "Busy-resources decision"]
                    wait_note = " ".join(str(note or "").split())
                    blocks.append(("Busy-resources decision",
                                   [f"- {gate.get('id')}: keep waiting"
                                    + (f" - {wait_note}" if wait_note else "")
                                    + f"; the {econfig.busy_wait_minutes(self.cfg)}-minute window restarts "
                                    "from this decision"]))
                    render["extra_blocks"] = blocks
                    self._rematerialize(task)
                    self.store.event(actor, "stage_launch_busy_wait_continued", task=task["id"],
                                     gate=gate["id"], note=note)
                else:
                    task["status"] = "cancelled"
                    task.pop("_render", None)
                    task["updated_at"] = eutil.utc_now()
                    self._abandon_task_subject(
                        task, note, reason=f"the user stopped waiting on busy resources for launch card "
                                           f"{task['id']}: {note or 'no note'}")
                    self.store.event(actor, "stage_launch_busy_wait_stopped", task=task["id"],
                                     gate=gate["id"], note=note)
            elif subj.get("task"):
                task = self.store.get_task(self.st, subj["task"])
                # An escalation is a decision ABOUT a
                # specific stuck epoch. If that task was meanwhile settled
                # (cancelled by the documented non-launch protocol, waived,
                # superseded), approving it must not resurrect a task nobody can
                # discharge - a launch card bound to a now-terminal RUN accepts
                # neither bind, nor confirm-not-launched, nor any submit shape.
                # While a facts revision awaits its
                # re-proof, rejecting the drill's escalation must NOT bury a
                # full mid-rounds project - the honest semantics is "give up
                # on the revision": roll the approved facts back to the
                # archived pre-revision snapshot and continue under them.
                if task is not None and task.get("type") == "infra_drill" \
                        and self.st.get("infra_revision_pending") and not approve:
                    self._rollback_infra_revision(task, note=note)
                    return
                stale = None
                if task is None:
                    stale = "the task no longer exists"
                elif task.get("status") != "stuck":
                    stale = f"the task is now '{task.get('status')}', not stuck"
                elif task.get("type") in ("stage_launch", "eval_launch"):
                    run_now = self.store.get_run(self.st, str((task.get("subject") or {}).get("run") or ""))
                    if run_now is None or erun.is_terminal(run_now):
                        stale = (f"its RUN {(task.get('subject') or {}).get('run')} is already terminal "
                                 f"({(run_now or {}).get('status')}) - no launch receipt can be produced")
                if stale:
                    gate["status"] = "cancelled"
                    gate["resolved_at"] = eutil.utc_now()
                    gate["note"] = (f"superseded before this decision: {stale} "
                                    f"(recorded decision: {'approve' if approve else 'reject'})")
                    self.store.event(actor, "gate_cancelled", gate=gate["id"],
                                     reason="escalation_subject_settled", detail=stale, note=note)
                    # Cancelling the gate is only HALF the
                    # transition - the stuck owner task must be settled in the
                    # SAME decision, or it waits forever for a decision object
                    # that no longer exists (a launch card bound to a terminal
                    # RUN accepts no submit shape; the replaying recovery then
                    # re-presented "requires its escalation decision" on every
                    # next while doctor stayed clean).
                    if task is not None and task.get("status") == "stuck" \
                            and task.get("type") in ("stage_launch", "eval_launch"):
                        stale_run = self.store.get_run(
                            self.st, str((task.get("subject") or {}).get("run") or ""))
                        if stale_run is None or erun.is_terminal(stale_run):
                            self._settle_unfinishable_launch_task(
                                task, stale_run,
                                f"escalation {gate.get('id')} was superseded ({stale}); "
                                "no launch receipt can ever be produced")
                    self.save()
                    return {"gate": gate["id"], "status": gate["status"]}
                if approve and task:
                    task["attempts"] = 0
                    # EVERY stuck/paused->open flip goes through the
                    # same one-open floor - approving an escalation while a
                    # sibling ordinary task is already open would mint a
                    # second live authority card (MULTI_OPEN_TASKS that
                    # doctor --fix cannot converge).
                    other_open = next(
                        (t for t in self.st.get("tasks", [])
                         if t is not task and t.get("status") == "open"
                         and t.get("type") != "stage_watch"), None)
                    if other_open is not None:
                        task["status"] = "paused"
                        task["queued_after_hold"] = True
                        task["held_by"] = []
                        self.store.event(actor, "task_reopen_queued", task=subj["task"],
                                         behind=other_open.get("id"))
                    else:
                        task["status"] = "open"
                    # Reset only the retry counter.  The validation diagnosis
                    # and the user's approval note are the information that
                    # makes this retry different from the failed epoch.
                    render = task.setdefault("_render", {})
                    blocks = [(str(row[0]), list(row[1]))
                              for row in (render.get("extra_blocks") or [])
                              if isinstance(row, (list, tuple)) and len(row) == 2
                              and str(row[0]) != "Approved task retry direction"]
                    retry_note = " ".join(str(note or "").split())
                    if retry_note:
                        blocks.append(("Approved task retry direction",
                                       [f"- {gate.get('id')}: {retry_note}"]))
                    render["extra_blocks"] = blocks
                    if task.get("type") == "infra_drill":
                        task["infra_canary_failures"] = 0
                        task.pop("infra_canary_run", None)
                    self._rematerialize(task)
                    self.store.event(actor, "task_reopened", task=subj["task"])
                elif task:
                    task["status"] = "cancelled"
                    task.pop("_render", None)
                    self._abandon_task_subject(task, note)
                    if task.get("type") == "infra_drill":
                        self.st["bootstrap_terminated"] = True
                        self._write_terminal_phase(
                            "infrastructure canary validation escalation rejected",
                            event="evolution_stopped", note=note)
            elif subj.get("lane"):
                lane = self.store.get_lane(self.st, subj["lane"])
                # The lane/node escalation arms get the
                # SAME staleness recheck as the task arm - a
                # decision about a subject that meanwhile reached a terminal
                # state must retire as superseded, never resurrect it.
                if lane is not None and lane.get("status") in ("done", "abandoned"):
                    gate["status"] = "cancelled"
                    gate["resolved_at"] = eutil.utc_now()
                    gate["note"] = (f"superseded before this decision: lane is "
                                    f"'{lane.get('status')}' (recorded decision: "
                                    f"{'approve' if approve else 'reject'})")
                    self.store.event(actor, "gate_cancelled", gate=gate["id"],
                                     reason="escalation_subject_settled", note=note)
                    self.save()
                    return {"gate": gate["id"], "status": gate["status"]}
                if lane:
                    if approve:
                        stage = subj.get("resume_stage") or "sketch"
                        # cycles["ablation"] is the shared instrumental review
                        # counter - both _apply_review_ablation and
                        # _apply_maintenance_review increment that same key.
                        # Mapping only "ablation_design" onto it meant approving
                        # a maintenance escalation reset nothing, so the next
                        # REVISE re-escalated immediately and, because an open
                        # gate blocks all scheduling, the whole run stopped once
                        # per revision forever while the ledger still logged a
                        # lane_cycles_reset that had not happened. Derive the
                        # stage set from the route table so a future purpose
                        # cannot reintroduce the omission.
                        instrumental_designs = {seq[0] for seq in eflow.INSTRUMENTAL_SEQ.values()}
                        counter = ("theory" if stage in ("pose", "theorize") else
                                   "ablation" if stage in instrumental_designs else stage)
                        if counter in lane.setdefault("cycles", {}):
                            lane["cycles"][counter] = 0
                        if stage == "theorize":
                            lane["theory_cycle"] = int(lane.get("theory_cycle") or 0) + 1
                        lane["status"] = stage
                        self.store.event(actor, "lane_cycles_reset", lane=lane["id"], stage=lane["status"])
                    else:
                        self._abandon_lane(lane, f"escalation rejected: {note or 'no note'}")
            elif subj.get("node"):
                node = self.node(subj["node"])
                if node is not None and node.get("status") in ("concluded", "abandoned"):
                    # 
                    gate["status"] = "cancelled"
                    gate["resolved_at"] = eutil.utc_now()
                    gate["note"] = (f"superseded before this decision: node is "
                                    f"'{node.get('status')}' (recorded decision: "
                                    f"{'approve' if approve else 'reject'})")
                    self.store.event(actor, "gate_cancelled", gate=gate["id"],
                                     reason="escalation_subject_settled", note=note)
                    self.save()
                    return {"gate": gate["id"], "status": gate["status"]}
                if node:
                    if approve:
                        node["stage_failures"] = 0
                        node["eval_failures"] = 0
                        node["fix_cycles"] = 0
                        # Do NOT discard a pending
                        # repeat_attempt here. This escalation only resets the
                        # code-FIX budget; the repeat_attempt is a separate,
                        # still-unapproved replacement-workflow/eval SPEND whose
                        # own repeat_spend gate must still fire when the workflow
                        # re-runs. Popping it let one whole training rerun bypass
                        # its dedicated human gate. Only the exact repeat_spend
                        # decision may clear it.
                        intent = subj.get("repair_intent")
                        if isinstance(intent, dict):
                            # A typed-repair exhaustion approval must also
                            # RESTORE the fix intent the non-exhausted path
                            # writes - a bare counter reset re-ran the same
                            # deterministic failure with nothing changed.
                            node["status"] = "building"
                            node["fix_needed"] = True
                            node["fix_note"] = str(intent.get("fix_note") or "") or \
                                str(node.get("fix_note") or "repair budget reset; fix the recorded failure")
                        self.store.event(actor, "node_stage_failures_reset", node=node["id"],
                                         repair_intent=bool(intent))
                    else:
                        self._abandon_node(node, f"escalation rejected: {note or 'no note'}")
        elif kind == "round_continue":
            if not approve:
                self._write_terminal_phase(
                    f"user declined to continue after round "
                    f"{subj.get('after_rounds')} (round_continue rejected)",
                    event="evolution_stopped", after_rounds=subj.get("after_rounds"), note=note)
        elif kind == "posthoc_claim":
            # Checked (record, node, staleness, proposal seal) before the gate
            # row changed, above.
            record = next(c for c in self.st.get("posthoc_claims", [])
                          if str(c.get("id") or "") == str(subj.get("claim") or ""))
            node = self.node(str(subj.get("node") or ""))
            if approve:
                self._apply_posthoc_claim(node, record, gate=gate, note=note, actor=actor)
            else:
                record["status"] = "rejected_by_user"
                record["closed_at"] = eutil.utc_now()
                self.store.event(actor, "posthoc_claim_rejected", claim=record.get("id"),
                                 node=node.get("id"), note=note)
        elif kind == "instrument_correction":
            import eseal
            record = next((c for c in self.st.get("corrections", [])
                           if str(c.get("id") or "") == str(subj.get("correction") or "")), None)
            node = self.node(str(subj.get("node") or ""))
            if record is None or node is None:
                raise SystemExit("[evo] instrument correction gate names an unknown correction/node")
            if approve:
                # the bytes the judge ruled on must be the bytes applied
                errs = eseal.verify(self.store.repo, record.get("proposal_seal"),
                                    label=f"correction {record.get('id')} proposal")
                errs += eseal.verify(self.store.repo, record.get("review_seal"),
                                     label=f"correction {record.get('id')} review")
                if errs:
                    raise SystemExit("[evo] the proposal or ruling changed since the judge ruled; decision "
                                     "not applied - restore those files to their ruled bytes, or reject this "
                                     "gate and re-file with 'evo correct-instrument':\n  - "
                                     + "\n  - ".join(errs))
                self._apply_instrument_correction(node, record, gate=gate, note=note, actor=actor)
            else:
                record["status"] = "rejected_by_user"
                record["closed_at"] = eutil.utc_now()
                self.store.event(actor, "instrument_correction_rejected", correction=record.get("id"),
                                 node=node.get("id"), note=note)
        return {"gate": gate["id"], "status": gate["status"]}
