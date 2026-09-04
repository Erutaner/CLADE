"""Task materialization (v10): cards, bundles, per-status lane/node task
builders and the prose block builders they share. All agent-facing task
construction lives here; scheduling order lives in esched; policy in eflow.
"""

from __future__ import annotations

import json
import re
from typing import Any

import eartifact
import erehearsal
import ebundle
import ecards
import econfig
import eflow
import egraph
import einfra
import eprogram
import erecover
import eutil
import evalid

stages_of = econfig.stages_of



class TaskMixin:
    def _create_task(self, type_: str, subject: dict, outputs: list[str], *,
                     extra_fields: dict[str, str] | None = None,
                     inputs: list[tuple[str, str]] | None = None,
                     extra_blocks: list[tuple[str, list[str]]] | None = None,
                     lesson_parents: list[str] | None = None,
                     lesson_tags: list[str] | None = None,
                     observation_ids: list[str] | None = None,
                     artifact_receipts: dict | None = None) -> dict:
        # R8 audit: the SAME duty may already exist as a task parked by a hold
        # release (queued_after_hold) that the reopen pump has not reached yet
        # (an open stage_watch keeps the pump off while the scheduler walks
        # right past it into this creation path). Minting a fresh identity
        # reset attempts/last_errors - unbounding the bounded retry and losing
        # the validator's recorded corrections. Reopen the parked task
        # instead, with its history, and rebuild its card from current truth.
        # R10-009: a task for the SAME duty that is still paused UNDER an
        # active hold is that duty's frozen identity - minting a fresh twin
        # gave the duty a new task id outside every hold's frozen consumer
        # set, so the twin could be submitted right through the recovery
        # review the pause exists for. The duty stays paused with its task;
        # _present_task renders a held task as a waiting surface.
        held_twin = next(
            (t for t in self.st.get("tasks", [])
             if t.get("status") == "paused" and (t.get("held_by") or [])
             and t.get("type") == type_ and (t.get("subject") or {}) == subject),
            None)
        if held_twin is not None:
            return held_twin
        parked = next(
            (t for t in self.st.get("tasks", [])
             if t.get("status") == "paused" and t.get("queued_after_hold")
             and not (t.get("held_by") or [])
             and t.get("type") == type_ and (t.get("subject") or {}) == subject),
            None)
        if parked is not None:
            parked["status"] = "open"
            parked.pop("queued_after_hold", None)
            parked["outputs"] = list(outputs)
            parked["updated_at"] = eutil.utc_now()
            self._materialize(parked, extra_fields=extra_fields, inputs=inputs,
                              extra_blocks=extra_blocks,
                              lesson_parents=lesson_parents, lesson_tags=lesson_tags,
                              observation_ids=observation_ids,
                              artifact_receipts=artifact_receipts)
            parked.pop("presented_at", None)
            self.store.event("engine", "queued_task_reopened", task=parked.get("id"),
                             reason="same duty rescheduled while parked")
            return parked
        task = self.store.new_task(self.st, type_, subject, outputs)
        self._materialize(task, extra_fields=extra_fields, inputs=inputs, extra_blocks=extra_blocks,
                          lesson_parents=lesson_parents, lesson_tags=lesson_tags,
                          observation_ids=observation_ids, artifact_receipts=artifact_receipts)
        return task

    def _materialize(self, task: dict, *, extra_fields: dict[str, str] | None = None,
                     inputs: list[tuple[str, str]] | None = None,
                     extra_blocks: list[tuple[str, list[str]]] | None = None,
                     lesson_parents: list[str] | None = None,
                     lesson_tags: list[str] | None = None,
                     observation_ids: list[str] | None = None,
                     artifact_receipts: dict | None = None) -> None:
        bundle_rel = ebundle.build_bundle(self.store, self.st, self.cfg, self.g, task,
                                          inputs=inputs or [], extra_blocks=extra_blocks,
                                          lesson_parents=lesson_parents, lesson_tags=lesson_tags)
        # R11-010/015 (+G-4): the receipt is DECLARED by the rendering call
        # site - the same code that produced the block lines - never inferred
        # from block titles.  The old title-prefix trigger recorded a global
        # tail-12 that ignored pinned rows and missed every differently-headed
        # observation surface, so the machine record contradicted the card.
        cc = task.setdefault("consumed_context", {})
        if observation_ids is not None:
            cc["observation_ids"] = [str(x) for x in observation_ids if str(x)]
        if artifact_receipts is not None:
            cc["artifact_receipts"] = {str(k): dict(v) for k, v in dict(artifact_receipts).items()
                                       if str(k)}
        fields = ecards.common_fields(self.store, self.st, self.cfg, task)
        fields["BUNDLE_PATH"] = bundle_rel
        lane_id = str((task.get("subject") or {}).get("lane") or "")
        lane = self.store.get_lane(self.st, lane_id) if lane_id else None
        node_id = str((task.get("subject") or {}).get("node") or "")
        node = self.node(node_id) if node_id else None
        fields["EXPERIMENT_PURPOSE"] = str((lane or node or {}).get("experiment_purpose") or "candidate")
        # Keep rematerialization of pre-upgrade open theory tasks compatible:
        # their saved _render fields predate THEORY_OUTPUT, but task.outputs is
        # already the engine-owned, collision-free artifact identity.
        if task.get("type") == "theorize" and task.get("outputs"):
            fields["THEORY_OUTPUT"] = str(task["outputs"][0])
        for k, v in (extra_fields or {}).items():
            fields[k] = v
        card = ecards.render(eflow.TASK_TYPES[task["type"]].card, fields)
        eutil.write_text(self.store.task_dir(task["id"]) / "CARD.md", card)
        task["card"] = f".evo/tasks/{task['id']}/CARD.md"
        task["bundle"] = bundle_rel
        task["_render"] = {
            "extra_fields": extra_fields or {}, "inputs": inputs or [],
            "extra_blocks": extra_blocks or [],
            "lesson_parents": lesson_parents, "lesson_tags": lesson_tags,
            "observation_ids": observation_ids, "artifact_receipts": artifact_receipts,
        }

    def _prefill_output(self, rel: str, payload: dict) -> None:
        """Engine-authored head start for an agent output file (v10.1).

        Fields the validator asserts byte-equal to engine-held sources (winner
        program copies, digests, computed verdicts, prepared RUN identity) are
        written by the engine at task creation; the agent completes the
        remaining fields in place.  Never overwrites - a retry keeps the
        agent's edits - and the exact-copy validators still run unchanged, so
        a hand-edited pre-fill fails exactly as a hand-copied one did.
        """
        path = eutil.rpath(self.store.repo, rel)
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        eutil.write_json_atomic(path, payload)

    def _rematerialize(self, task: dict) -> None:
        r = task.get("_render", {})
        blocks = [(b[0], list(b[1])) for b in (r.get("extra_blocks") or [])]
        self._materialize(task, extra_fields=r.get("extra_fields"), inputs=r.get("inputs"),
                          extra_blocks=blocks,
                          lesson_parents=r.get("lesson_parents"), lesson_tags=r.get("lesson_tags"),
                          observation_ids=r.get("observation_ids"),
                          artifact_receipts=r.get("artifact_receipts"))
        # The card/bundle just CHANGED (rejection feedback, escalation retry
        # direction): the next `evo next` must print in full again, not claim
        # "unchanged" and point at a file the agent believes it already read.
        task.pop("presented_at", None)

    def _profile_inputs(self) -> list[tuple[str, str]]:
        return [
            (".evo/config.json", "evaluation contract (D#/T#/C#/G#, claim roles and evidence budget)"),
            (".evo/profile/PROJECT_PROFILE.md", "project facts (what/how/metrics/runtime)"),
            (".evo/profile/BASELINE_PROGRAM.json", "code-grounded objects and train/inference/information-flow program"),
            (".evo/profile/INNOVATION_RUBRIC.md", "mechanism novelty, effect and theory standards for this project"),
        ]

    def _round_strategy_context(self, rid: str) -> dict:
        """The one definition of what a round strategist may see.

        The scheduler and the recovery refresh both build this bundle; keeping
        two copies means a widened field of view silently applies to fresh
        rounds and not to recovered ones.
        """
        inputs = self._profile_inputs() + [
            (".evo/views/FRONTIER.md", "origin, observed performance frontier, inheritance "
                                       "frontier and the measured-but-unsettled remainder"),
            (".evo/views/GRAPH.md", "every node with lineage, verdict, scores and settlement - "
                                    "including the ones no frontier lists"),
            # A repair lane is rejected unless its bottleneck_ids are real
            # dossier B# ids, so the vocabulary has to be in the bundle.
            (".evo/profile/PROBLEM_DOSSIER.md", "the frozen B# bottleneck vocabulary a repair "
                                                "lane must name (plus V# invariants and F# facts)")]
        if (self.store.profile_dir() / "DOSSIER_ADDENDUM.md").exists():
            inputs.append((".evo/profile/DOSSIER_ADDENDUM.md",
                           "later B# bottlenecks appended by closed rounds"))
        tombstones = ebundle.tombstones_block(self.store)
        # R7 multi-round audit: a positive node's pre-registered scaling
        # follow-up is a DOOR the strategist must be able to see rounds later
        # - succession moves the parent off the visible frontier, and nothing
        # else in the designated context carried the registration. Without
        # this inventory the door was undiscoverable by a fresh session.
        doors: list[str] = []
        # R8 audit: "spent" must mean a LIVE follow-up, exactly as
        # v_open_round judges it - an abandoned follow-up lane/node does not
        # consume the registration there, so hiding the door here made this
        # inventory (the door's only cold-session carrier) contradict the
        # validator and bury a still-legal action forever.
        spent_parents = {str(l.get("scaling_followup_of") or "")
                         for l in self.st.get("lanes", [])
                         if l.get("scaling_followup_of")
                         and l.get("status") not in ("abandoned",)}
        spent_parents |= {str(n.get("scaling_followup_of") or "")
                          for n in self.g.get("nodes", [])
                          if n.get("scaling_followup_of")
                          and n.get("status") not in ("abandoned",)}
        for node in self.g.get("nodes", []):
            nid = str(node.get("id") or "")
            if node.get("status") != "concluded" or nid in spent_parents \
                    or node.get("retire_reason") or not node.get("idea_doc"):
                continue
            if node.get("verdict") in (None, "failed", "regressed", "screened_out"):
                continue
            meta = eutil.read_json(eutil.rpath(
                self.store.repo, str(node["idea_doc"]).replace(".md", ".meta.json")), {}) or {}
            plan = meta.get("scaling") if isinstance(meta.get("scaling"), dict) else {}
            if str(plan.get("execution") or "") != "followup_node":
                continue
            doors.append(f"- {nid} scaling follow-up AVAILABLE (registered points: "
                         f"{plan.get('points')}; open with `scaling_followup_of: \"{nid}\"`, "
                         "intent exploit, that node as single parent)")
        # R9 (external audit r6): a targeted ablation's engine-enforced exact
        # next-DAG decision landed only on the node/dashboard - the strategist
        # (a fresh session whose bundle IS its memory) never received the very
        # action a costly causal run settled. Project unconsumed settlements as
        # doors; consumed = a later lane/node already names the ablation as a
        # parent. (The filter mirrors the scaling doors' spent_parents above -
        # without it every settled ablation stayed in this block forever and
        # the doors list grew monotonically round over round.)
        consumed_ablations: set[str] = set()
        for l in self.st.get("lanes", []):
            consumed_ablations.update(str(p) for p in (l.get("parents") or []))
        for n2 in self.g.get("nodes", []):
            consumed_ablations.update(str(p) for p in (n2.get("parents") or []))
        for node in self.g.get("nodes", []):
            if node.get("experiment_purpose") != "targeted_ablation" \
                    or node.get("status") != "concluded" \
                    or str(node.get("id") or "") in consumed_ablations:
                continue
            result = node.get("ablation_result") if isinstance(node.get("ablation_result"), dict) else None
            if not result or not str(result.get("decision") or "").strip():
                continue
            parent = str((node.get("parents") or [""])[0] or "")
            doors.append(f"- {node.get('id')} TARGETED-ABLATION SETTLEMENT on parent {parent}: "
                         f"effect={result.get('effect')} (supports {result.get('supports')}); the "
                         f"pre-registered exact next action is: {str(result.get('decision'))[:240]}")
        # R11 matrix sweep (M5): the user's round_continue APPROVE note is a
        # directional instruction for exactly this round - it used to land
        # only in the gate row and the event stream, with no consumer.
        continue_note = self._last_gate_note("round_continue", statuses=("approved",))
        note_block = ([("User direction from the round-continue decision",
                        [f"- {continue_note}"])] if str(continue_note or "").strip() else [])
        obs_lines, obs_ids = self._observations_block()
        return {
            "inputs": inputs,
            "extra_blocks": note_block
                            + ([("Eligible cross-round doors (pre-registered follow-ups awaiting a lane)",
                               doors)] if doors else [])
                            + ([("Published-territory tombstones (strategist-only; route via briefs)",
                               tombstones)] if tombstones else []) + [
                ("Frontiers, origin and per-cell records", ebundle.frontier_block(self.g, self.cfg, self.st)),
                ("Shared artifacts available for reuse", eartifact.artifacts_block(self.reg)),
                ("Round history", ebundle.rounds_history_block(self.st)),
                ("Prediction calibration (engine-checked outcomes of registered predictions)",
                 ebundle.calibration_block(self.g)),
                ("Phenomenon ledger (OB### - open anomalies are lane material: a lane that "
                 "chases a measured anomaly beats a lane that chases a trend)",
                 obs_lines),
                ("Idea-space usage watch (cross-round homogenization guard)", self._usage_block()),
                ("Policy constraints in force", self._policy_block(rid))],
            "lesson_parents": [], "lesson_tags": ["strategy"],
            "observation_ids": obs_ids,
            "artifact_receipts": eartifact.artifacts_receipts(self.reg),
        }

    def _infra_inputs(self) -> list[tuple[str, str]]:
        ins = [(".evo/config.json", "project declarations incl. the docs list")]
        for d in (self.cfg.get("project") or {}).get("docs") or []:
            ins.append((str(d), "user knowledge base (read every relevant file)"))
        return ins

    def _portfolio_fields(self, rid: str) -> dict[str, str]:
        pol = self.cfg.get("policy", {})
        rnum = int(rid[1:])
        we = int(pol.get("wildcat_every_rounds", 0))
        notes = []
        if evalid._stagnant_window(self.ctx(), int(pol.get("stagnation_rounds", 2))):
            notes.append("STAGNATION DETECTED: this round MUST contain a lane with min_level >= 3 (reform, wildcat or moonshot).")
        k2 = int(pol.get("stagnation_moonshot_rounds", 0))
        if k2 and evalid._stagnant_window(self.ctx(), k2):
            notes.append(f"DEEP STAGNATION ({k2} flat rounds): this round MUST contain a MOONSHOT lane - "
                         "a full-program frontier reformulation/paradigm attempt; theory remains an independent choice.")
        if we and rnum % we == 0:
            notes.append(f"WILDCAT ROUND: round number {rnum} is a multiple of {we}; include one L4 lane (wildcat or moonshot).")
        slots = self._slots()
        if slots > 1:
            notes.append(f"PARALLEL EXECUTION: the platform allows {slots} concurrent stage jobs; "
                         f"plan enough lanes to keep the pipeline full (external waits are free).")
        if econfig.is_research(self.cfg):
            notes.append(f"RESEARCH MODE: >= {float(pol.get('research_min_structural_scope_share', 0.5)):.0%} of candidate "
                         f"lanes must target subsystem/full-program scope, and >= "
                         f"{float(pol.get('research_min_constructive_share', 0.5)):.0%} must be "
                         "constructive/theory-derived. Every candidate separately owes an irreducible M gate, "
                         "including local-scope work.")
        replication = econfig.training_replication_policy(self.cfg)
        ablation = ((self.cfg.get("evidence_policy") or {}).get("ablation") or {})
        notes.append(f"TRAINING-SEED POLICY: {replication.get('mode')}"
                     + (f", exactly {replication.get('planned_runs')} preplanned runs per ordinary train/finetune "
                        f"candidate aggregated by {replication.get('aggregation')}"
                        if replication.get("mode") == "preplanned"
                        else ", one recorded seed per train/finetune node; do not create repeats"))
        notes.append(f"ABLATION POLICY: {ablation.get('mode')}; targeted ablation is never automatic, "
                     "requires one decision-changing causal question and one manually approved changed-component run.")
        fds = econfig.focus_directions(self.cfg)
        if fds:
            fd_lines = "; ".join(f"{f['id']}: {str(f.get('text') or '')[:80]}" for f in fds)
            notes.append(f"USER FOCUS DIRECTIONS (tag a lane with \"focus\": \"D#\" to serve one; "
                         f"cap {float(pol.get('focus_share_max', 0.5)):.0%} of lanes): {fd_lines}")
            negl = int(pol.get("focus_neglect_rounds", 0) or 0)
            closed = [r for r in self.st.get("rounds", []) if r.get("closed_at")]
            if negl and len(closed) >= negl:
                recent_lane_ids = {lid for r in closed[-negl:] for lid in (r.get("lanes") or [])}
                # R7 audit: mirror the validator - scout/instrumental lanes
                # discharge no starved direction, so they must not silence
                # the FOCUS STARVATION card line either.
                served = {l.get("focus") for l in self.st.get("lanes", [])
                          if l.get("id") in recent_lane_ids and l.get("focus")
                          and l.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES
                          and l.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES}
                starved = [f["id"] for f in fds if f["id"] not in served]
                if starved:
                    notes.append(f"FOCUS STARVATION: direction(s) {starved} got no lane in the last {negl} "
                                 f"closed rounds - this round MUST serve one of them.")
        return {"ROUND_ID": rid, "POLICY_NOTES": "\n".join(f"- {n}" for n in notes) or "- none"}

    def _policy_block(self, rid: str) -> list[str]:
        pol, bud = self.cfg.get("policy", {}), self.cfg.get("budgets", {})
        return [
            f"- tempo: {econfig.describe_policy(self.cfg)}",
            f"- lanes per round: {bud.get('lanes_per_round_min')}..{bud.get('lanes_per_round_max')}",
            f"- implementation-scope floors per intent: {json.dumps(pol.get('scope_floor', {}))}",
            f"- max exploit share: {pol.get('max_exploit_share')}",
            f"- research constructive share: {pol.get('research_min_constructive_share')}",
            f"- wildcat/moonshot cadence: every {pol.get('wildcat_every_rounds')} rounds; "
            f"stagnation windows: L3+ after {pol.get('stagnation_rounds')}, moonshot after {pol.get('stagnation_moonshot_rounds')} flat rounds",
            f"- stagnant now: {evalid._stagnant_window(self.ctx(), int(pol.get('stagnation_rounds', 2)))}",
            f"- workflow stage slots: {self._slots()}",
            f"- training-seed policy: {econfig.training_replication_policy(self.cfg).get('mode')}",
            f"- targeted-ablation policy: {econfig.ablation_mode(self.cfg)} (manual approval always)",
        ]

    def _round_summary_block(self, rid: str) -> list[str]:
        out = []
        idx = egraph.by_id(self.g)
        for lane in self.st["lanes"]:
            if lane["round"] != rid:
                continue
            n = idx.get(lane.get("node") or "")
            score = None
            if n:
                score = egraph.primary_score(n, econfig.primary_metric(self.cfg))
            out.append(
                f"- {lane['id']} '{lane.get('name')}' intent={lane['intent']} "
                f"purpose={lane.get('experiment_purpose') or 'candidate'} status={lane['status']} "
                f"idea={lane.get('idea') or '-'} node={lane.get('node') or '-'} verdict={(n or {}).get('verdict') or '-'} "
                f"primary={score if score is not None else '-'} abandon_reason={lane.get('abandon_reason') or '-'}"
            )
        return out or ["- no lanes"]

    def _round_needs_evidence_refresh(self, rid: str) -> bool:
        """Refresh only when the field pool or a repair target is under-covered."""
        # R9: count only ACCEPTED evidence - a cancelled task's leftover rows
        # must not make the pool look covered and suppress the refresh.
        rows = evalid.accepted_ledger_rows(self.st, "evidence", self.store.evidence())
        bud = self.cfg.get("budgets", {})
        # R5 blind-operator audit: an instrumental-only round (e.g. a single
        # targeted ablation) is a diagnostic, not idea search - the cards say
        # it "does not enter the candidate novelty pipeline", so the
        # literature pool floors must not block it.
        round_lanes = [l for l in self.st.get("lanes", []) if l.get("round") == rid]
        research_lanes = [l for l in round_lanes
                          if str(l.get("experiment_purpose") or "candidate")
                          not in econfig.INSTRUMENTAL_PURPOSES]
        if round_lanes and not research_lanes:
            return False
        # A project may deliberately request a fixed per-round refresh.  The
        # frontier preset leaves this at zero and therefore uses the
        # coverage-driven policy below; a positive value is an explicit
        # contract, not a legacy fallback.
        if int(bud.get("evidence_min_new_per_round", 0)) > 0:
            return True
        if len(rows) < int(bud.get("evidence_min_total", 0)):
            return True
        years = [r.get("year") for r in rows if isinstance(r.get("year"), int)]
        if years:
            recent = sum(1 for y in years if y >= int(bud.get("evidence_recent_year", 0)))
            if recent / len(years) + 1e-9 < float(bud.get("evidence_min_recent_ratio", 0)):
                return True
        targets = {b for lane in research_lanes
                   if lane.get("search_origin") == "repair"
                   for b in (lane.get("bottleneck_ids") or [])}
        for bid in targets:
            matched = [r for r in rows if bid in (r.get("relevance") or [])]
            if len(matched) < int(bud.get("evidence_min_per_bottleneck", 0)):
                return True
            recent = sum(1 for r in matched if isinstance(r.get("year"), int) and
                         r["year"] >= int(bud.get("evidence_recent_year", 0)))
            if recent < int(bud.get("evidence_recent_min_per_bottleneck", 0)):
                return True
        return False

    @staticmethod
    def _sketch_failure_summary(lane: dict) -> str:
        """Describe the failures in the current retry epoch without changing its budget.

        ``cycles.sketch`` is reset only by an approved escalation.  Every
        increment appends one immutable attempt record, so the tail of
        ``attempts`` is the compatible source of truth for old and new state.
        """
        total = max(0, int((lane.get("cycles") or {}).get("sketch") or 0))
        if total == 0:
            return "no failed scientific contracts"
        attempts = lane.get("attempts") if isinstance(lane.get("attempts"), list) else []
        window = attempts[-total:]
        counts: dict[str, int] = {}

        def add(label: str) -> None:
            counts[label] = counts.get(label, 0) + 1

        for raw in window:
            if not isinstance(raw, dict):
                add("unclassified")
                continue
            verdict = str(raw.get("verdict") or "")
            if verdict == "all_killed":
                add("tournament all-killed")
            elif verdict.startswith("REJECT_"):
                add(f"red-team {verdict}")
            elif verdict == "USER_REJECT_SKETCH":
                add("user-requested resynthesis")
            elif verdict:
                add(f"other {verdict}")
            else:
                add("unclassified")
        missing = total - len(window)
        if missing > 0:
            counts["unclassified"] = counts.get("unclassified", 0) + missing
        detail = "; ".join(f"{label}: {count}" for label, count in counts.items())
        noun = "contract" if total == 1 else "contracts"
        return f"{total} failed scientific {noun} ({detail})"

    @classmethod
    def _sketch_escalation_message(cls, lane: dict) -> str:
        return (f"Lane {lane.get('id')}: sketch/resynthesis budget reached after "
                f"{cls._sketch_failure_summary(lane)}. Approve to retry the same sealed lane with "
                "reset counters; reject to abandon it. Any decision note will be routed to "
                "subsequent sketch tasks in this retry epoch.")

    def _sketch_retry_blocks(self, lane: dict) -> list[tuple[str, list[str]]]:
        """Route every prior scientific rejection and the active retry direction.

        Attempt artifacts stay append-only, so listing paths is enough; copying
        their contents into state or the bundle would create a second ledger.
        """
        history: list[str] = []
        seen_paths: set[str] = set()

        def add_existing(refs: list[tuple[str, str]], raw_path: Any, role: str) -> None:
            path = str(raw_path or "")
            if not path or path in seen_paths or not eutil.rpath(self.store.repo, path).exists():
                return
            seen_paths.add(path)
            refs.append((path, role))

        attempts = lane.get("attempts") if isinstance(lane.get("attempts"), list) else []
        for seq, raw in enumerate(attempts, start=1):
            if not isinstance(raw, dict):
                continue
            refs: list[tuple[str, str]] = []
            add_existing(refs, raw.get("program_set"), "rejected frozen program contract")
            tournament = str(raw.get("tournament") or "")
            add_existing(refs, tournament, "tournament audit")
            if tournament.endswith(".json"):
                add_existing(refs, tournament[:-5] + ".md", "readable tournament review")
            add_existing(refs, raw.get("review"), "red-team review")
            note = " ".join(str(raw.get("note") or "").split())
            if not refs and not note:
                continue
            verdict = str(raw.get("verdict") or "rejected")
            if refs:
                rendered = "; ".join(f"read `{path}` ({role})" for path, role in refs)
                history.append(f"- attempt {seq} [{verdict}]: {rendered}")
            else:
                history.append(f"- attempt {seq} [{verdict}]")
            if note:
                history.append(f"  - recorded direction: {note}")

        # A batch can contain several formally advanced survivors.  Their
        # candidate-specific reviews live in idea_revisions while the batch is
        # active and remain useful if the whole batch is eventually exhausted.
        for raw in lane.get("idea_revisions") or []:
            if not isinstance(raw, dict):
                continue
            refs = []
            add_existing(refs, raw.get("program_set"), "rejected frozen program contract")
            tournament = str(raw.get("tournament") or "")
            add_existing(refs, tournament, "tournament audit")
            if tournament.endswith(".json"):
                add_existing(refs, tournament[:-5] + ".md", "readable tournament review")
            add_existing(refs, raw.get("review"), "candidate-specific red-team review")
            if refs:
                verdict = str(raw.get("verdict") or "rejected")
                rendered = "; ".join(f"read `{path}` ({role})" for path, role in refs)
                history.append(f"- idea {raw.get('idea') or '?'} [{verdict}]: {rendered}")

        # Compatibility fallback for a pre-existing state that reached sketch
        # before its active rejection was archived into ``attempts``.
        active_refs: list[tuple[str, str]] = []
        active_tournament = str(lane.get("tournament_path") or "")
        add_existing(active_refs, active_tournament, "tournament audit")
        if active_tournament.endswith(".json"):
            add_existing(active_refs, active_tournament[:-5] + ".md",
                         "readable tournament review")
        active_review = (f".evo/ideas/{lane.get('idea')}.review.md"
                         if lane.get("idea") else "")
        add_existing(active_refs, active_review, "red-team review")
        if active_refs:
            rendered = "; ".join(f"read `{path}` ({role})" for path, role in active_refs)
            history.append(f"- active rejected contract: {rendered}")

        blocks: list[tuple[str, list[str]]] = []
        if history:
            blocks.append(("Prior rejected scientific contracts (oldest first; read every listed audit)",
                           history))

        # The latest sketch-resume escalation owns the current retry epoch.
        # Resolve it from persisted gates so pre-fix state also retains the
        # user's instruction; never borrow a note from another lane or stage.
        for gate in reversed(self.st.get("gates", [])):
            subject = gate.get("subject") if isinstance(gate, dict) else {}
            if not isinstance(subject, dict) or subject.get("lane") != lane.get("id") \
                    or gate.get("kind") != "escalation":
                continue
            if str(subject.get("resume_stage") or "sketch") != "sketch":
                continue
            note = " ".join(str(gate.get("decision_note") or "").split())
            if gate.get("status") == "approved" and note:
                blocks.append(("Approved retry direction (applies to this retry epoch)",
                               [f"- {gate.get('id')}: {note}"]))
            break
        return blocks

    def _promotion_blocks(self, lane: dict) -> list[tuple[str, list[str]]]:
        """Observed promotion context plus the lane's actual admission rule."""
        if lane.get("intent") == "platform":
            return []
        if lane.get("experiment_purpose") in econfig.EXPLORATORY_PURPOSES:
            # (final audit C29) a scout owes none of the frontier-expansion
            # plausibility below - asserting it in the bundle taught agents an
            # obligation the tier deliberately waives.
            return [("Lane admission policy", [
                "- EXPLORATORY LANE: results are observations only - no frontier-expansion "
                "plausibility duty, no promotion, no records. Judge coherence, mechanism honesty, "
                "and whether the reconnaissance question is worth one run.",
                "- M/E hard gates still apply to the PROGRAM (novelty duties are intact); only the "
                "forward-commitment ceremony (predictions, SOTA targets, probes) is waived.",
            ]), ("Observed promotion references (NOT effect comparators)",
                 ebundle.promotion_reference_block(self.g, self.cfg, self.st))]
        if lane.get("intent") in ("wildcat", "moonshot"):
            admission = [
                "- This is a first-contact root lane. A full_program + paradigm candidate may advance "
                "after all ordinary M/E, prior-art, scope and numeric-resource hard gates pass when its "
                "baseline-relative effect case is credible, even if its first implementation is not yet "
                "predicted to beat a many-generation graph node.",
                "- The observed N#/S# frontier remains the long-run target and risk context. It is not an "
                "age-blind birth threshold for that narrow paradigm-root case; every other candidate still "
                "owes ordinary immediate frontier-expansion plausibility.",
            ]
        else:
            admission = [
                "- Ordinary admission applies: after the M/E hard gates, the frozen claim-scoped result/resource "
                "vector must plausibly expand the observed compatible frontier.",
            ]
        return [("Lane admission policy", admission),
                ("Observed promotion references (NOT effect comparators)",
                 ebundle.promotion_reference_block(self.g, self.cfg, self.st))]

    def _effect_comparator_inputs(self, lane: dict) -> list[tuple[str, str]]:
        """Expose measurements for every comparator the frozen schema permits."""
        if lane.get("intent") == "platform":
            return []
        idx = egraph.by_id(self.g)
        ids = [str(n.get("id")) for n in self.g.get("nodes", [])
               if isinstance(n, dict) and n.get("role") == "baseline"]
        model_parents, _ = egraph.split_parents(
            [p for p in lane.get("parents", []) if p in idx], idx)
        ids.extend(model_parents)
        out: list[tuple[str, str]] = []
        seen: set[str] = set()

        def add(path: Any, role: str) -> None:
            rel = str(path or "")
            if rel and rel not in seen and eutil.rpath(self.store.repo, rel).exists():
                seen.add(rel)
                out.append((rel, role))

        for nid in dict.fromkeys(ids):
            node = idx.get(nid) or {}
            label = "baseline" if node.get("role") == "baseline" else "scientific parent"
            # Parent result documents are already in ``_lane_common_inputs``.
            # Add only missing comparator results here, while always exposing
            # the engine-owned numeric evidence that the common bundle lacks.
            if nid not in set(str(p) for p in lane.get("parents", [])):
                add(node.get("result_doc") or f".evo/nodes/{nid}/NODE_RESULT.md",
                    f"legal {label} {nid} result")
            normalized = next((str(row.get("path") or "")
                               for row in ((node.get("eval_seal") or {}).get("artifacts") or [])
                               if isinstance(row, dict) and row.get("role") == "normalized_metrics"), "")
            add(normalized, f"sealed normalized metrics for legal {label} {nid}")
            if not normalized or not eutil.rpath(self.store.repo, normalized).exists():
                # Compatibility for concluded pre-seal state: expose the raw
                # evaluator evidence under its honest label rather than call
                # it normalized.
                run = self.store.get_run(self.st, str(node.get("eval_run") or "")) or {}
                add(run.get("metrics_file"), f"sealed raw metrics for legal {label} {nid}")
            add(node.get("resource_receipt_path"),
                f"engine-generated resource receipt for legal {label} {nid}")
        return out

    def _winner_revision_blocks(self, lane: dict) -> list[tuple[str, list[str]]]:
        """Return reviews for this survivor only; never leak a prior rank's critique."""
        digest = str(lane.get("winner_program_digest") or "")
        lines: list[str] = []
        for row in lane.get("idea_revisions") or []:
            if not isinstance(row, dict):
                continue
            row_digest = str(row.get("winner_program_digest") or "")
            if not row_digest and row.get("idea"):
                meta = eutil.read_json(
                    eutil.rpath(self.store.repo, f".evo/ideas/{row['idea']}.meta.json"), {}) or {}
                row_digest = str(meta.get("program_digest") or "")
            review = str(row.get("review") or "")
            if digest and row_digest == digest and review \
                    and eutil.rpath(self.store.repo, review).exists():
                lines.append(f"- read `{review}` ({row.get('verdict') or 'review'} of {row.get('idea') or '?'})")
        return [("Earlier reviews of this same frozen survivor (address every point)", lines)] if lines else []

    _INSTRUMENTAL_REVISION_LABELS = {
        "targeted_ablation": ("previous causal design", "previous frozen X1/X2 and decision map",
                              "Earlier targeted-ablation revisions (oldest first; address every review)"),
        "maintenance": ("previous repair design", "previous defect, change boundary and parity contract",
                        "Earlier maintenance revisions (oldest first; address every review)"),
        "diagnostic_probe": ("previous probe design", "previous question, measurement plan and budget",
                             "Earlier probe revisions (oldest first; address every objection)"),
    }

    def _instrumental_revision_blocks(self, lane: dict) -> list[tuple[str, list[str]]]:
        """Expose earlier instrumental designs and reviews after their I# is superseded.

        A REVISE nulls ``lane["idea"]`` (eauthority._supersede_idea_revision), so
        the redraft task mints a FRESH id and any path built from that new id -
        including the review that was just written - cannot exist.  The
        superseded ids and their exact review paths survive only in
        ``lane["idea_revisions"]``, so that is what a redraft must be handed.
        Ablation always did this; maintenance instead looked for a review under
        the new id and so silently handed the agent nothing, and probe had no
        recovery path at all.
        """
        labels = self._INSTRUMENTAL_REVISION_LABELS.get(econfig.lane_purpose(lane))
        if labels is None:
            return []
        lines: list[str] = []
        for row in lane.get("idea_revisions") or []:
            if not isinstance(row, dict) or not row.get("idea"):
                continue
            iid = str(row["idea"])
            refs = [
                (f".evo/ideas/{iid}.md", labels[0]),
                (f".evo/ideas/{iid}.meta.json", labels[1]),
                (str(row.get("review") or ""), "review to answer"),
            ]
            existing = [(path, role) for path, role in refs
                        if path and eutil.rpath(self.store.repo, path).exists()]
            if existing:
                rendered = "; ".join(f"read `{path}` ({role})" for path, role in existing)
                lines.append(f"- {iid} [{row.get('verdict') or 'REVISE'}]: {rendered}")
        return [(labels[2], lines)] if lines else []

    def _retry_direction_blocks(self, lane: dict, stage: str) -> list[tuple[str, list[str]]]:
        """Route the newest explicit note for this lane, stage and survivor epoch."""
        digest = str(lane.get("winner_program_digest") or "")
        for gate in reversed(self.st.get("gates", [])):
            subject = gate.get("subject") if isinstance(gate, dict) else {}
            if not isinstance(subject, dict) or subject.get("lane") != lane.get("id"):
                continue
            gate_stage = (str(subject.get("resume_stage") or "")
                          if gate.get("kind") == "escalation"
                          else str(gate.get("retry_stage") or ""))
            bound = str(subject.get("winner_program_digest") or "")
            is_retry = ((gate.get("kind") == "escalation" and gate.get("status") == "approved") or
                        (gate.get("kind") == "idea_approval" and gate.get("status") == "rejected"))
            if not is_retry:
                continue
            if gate_stage != stage:
                continue
            # Ordinary candidate epochs are digest-bound.  The legal routes that
            # have no winner digest BY CONSTRUCTION use lane+stage as their
            # stable identity instead: pre-program theory, and every
            # instrumental design stage (an instrumental lane never runs a
            # tournament, so _activate_survivor never stamps a digest on it).
            # This used to name ablation_design literally, which left the
            # maintenance and probe rewinds - the very path the user gate is
            # supposed to offer - silently unable to carry the user's note.
            digest_matches = bool(digest) and bound == digest
            unbound_epoch = (not digest and not bound and
                             (stage == "theorize"
                              or stage in {seq[0] for seq in eflow.INSTRUMENTAL_SEQ.values()}))
            if not (digest_matches or unbound_epoch):
                continue
            note = " ".join(str(gate.get("decision_note") or "").split())
            if note:
                return [("Approved retry direction for this survivor and stage",
                         [f"- {gate.get('id')}: {note}"])]
            # A newer matching decision with no note intentionally shadows an
            # older note for the same stage/epoch.
            return []
        return []

    _LEDGER_CITE = re.compile(r"\b([EMS]\d{2,4})\b")
    _LEDGER_POOLS = {
        "EVIDENCE": (".evo/evidence/EVIDENCE.jsonl", "E", 24),
        "MECH": (".evo/evidence/MECH_CARDS.jsonl", "M", 16),
        "SOTA": (".evo/evidence/SOTA.jsonl", "S", 12),
    }
    # R9 (external audit r6): slices are a CONSUMER view - they must not hand a
    # later lane rows that no ledger validator ever accepted.
    _LEDGER_WATERMARKS = {"EVIDENCE": "evidence", "MECH": "mech", "SOTA": "sota"}

    def _ledger_slice_rows(self, lane: dict, wants: list[tuple[str, str]]) -> list[tuple[str, str]]:
        """v11.1 T4: narrow-purpose stages get an engine-written slice of the
        big append-only ledgers instead of the full pool. Selection: ids this
        lane's own artifacts cite, then focus-keyword matches, then newest
        entries up to the cap. The full pool always stays listed as a REFERENCE
        row - nothing is hidden, and a pool at-or-under its cap keeps the plain
        full row (no ceremony). Breadth tasks (deep_read/tournament/conclude)
        never call this."""
        cited: set[str] = set()
        subject_texts: list[str] = []
        ldir = eutil.rpath(self.store.repo, f".evo/rounds/{lane.get('round')}/lanes/{lane.get('id')}")
        if ldir.is_dir():
            for f in sorted(ldir.iterdir()):
                if f.is_file() and f.suffix in (".md", ".json"):
                    subject_texts.append(eutil.read_text(f) or "")
        iid = lane.get("idea")
        if iid:
            for rel in (f".evo/ideas/{iid}.md", f".evo/ideas/{iid}.meta.json", f".evo/ideas/{iid}.review.md"):
                p = eutil.rpath(self.store.repo, rel)
                if p.exists():
                    subject_texts.append(eutil.read_text(p) or "")
        for t in subject_texts:
            cited.update(self._LEDGER_CITE.findall(t))
        focus_terms = [w.lower() for w in re.split(r"[^A-Za-z0-9_-]+", str(lane.get("focus") or ""))
                       if len(w) >= 4]
        # Bottleneck ids are part of the ordered selection basis: records that
        # name the lane's B# (in relevance/tags/prose) belong in the slice.
        focus_terms += [str(b).lower() for b in (lane.get("bottleneck_ids") or []) if str(b).strip()]
        rows: list[tuple[str, str]] = []
        for kind, why in wants:
            pool_rel, prefix, cap = self._LEDGER_POOLS[kind]
            pool_path = eutil.rpath(self.store.repo, pool_rel)
            records = eutil.read_jsonl(pool_path) if pool_path.exists() else []
            records = evalid.accepted_ledger_rows(getattr(self, "st", None) or {},
                                                  self._LEDGER_WATERMARKS[kind], records)
            if len(records) <= cap:
                # The raw pool file may carry rows past the accepted watermark
                # (a cancelled task's unaccepted leftovers). Validators only
                # honor the accepted view - say so, or the author cites a row
                # they can see and gets a baffling rejection.
                rows.append((pool_rel,
                             why + (f" (validators accept only the first {len(records)} entries -"
                                    " the accepted prefix; rows after that, if any, are unaccepted"
                                    " leftovers: do not cite them)")))
                continue
            def _key(r: dict) -> str:
                return str((r or {}).get("id") or "")
            picked: list[dict] = [r for r in records if _key(r) in cited]
            if focus_terms and len(picked) < cap:
                have = {_key(r) for r in picked}
                for r in records:
                    if _key(r) in have:
                        continue
                    blob = json.dumps(r, ensure_ascii=False).lower()
                    if any(t in blob for t in focus_terms):
                        picked.append(r); have.add(_key(r))
                        if len(picked) >= cap:
                            break
            if len(picked) < cap:
                have = {_key(r) for r in picked}
                for r in reversed(records):
                    if _key(r) not in have:
                        picked.append(r); have.add(_key(r))
                        if len(picked) >= cap:
                            break
            picked = picked[:cap]
            order = {_key(r): i for i, r in enumerate(records)}
            picked.sort(key=lambda r: order.get(_key(r), 1 << 30))
            slice_rel = f".evo/slices/{lane.get('id')}_{kind}.jsonl"
            eutil.write_text(eutil.rpath(self.store.repo, slice_rel),
                             "\n".join(json.dumps(r, ensure_ascii=False) for r in picked) + "\n")
            rows.append((slice_rel,
                         why + f" (engine-sliced view of the {prefix}# ledger: entries this lane cites"
                               " + focus matches + newest, up to "
                               f"{cap}; ids and numbering are the pool's own)"))
            rows.append((pool_rel,
                         f"REFERENCE - the FULL {prefix}# pool ({len(records)} entries); the slice above is a"
                         " convenience view. If you are not CERTAIN the slice covers what your duty needs,"
                         " or your duty is a full sweep, read this instead (validators accept only the"
                         f" first {len(records)} entries; later rows, if any, are unaccepted leftovers -"
                         " do not cite them)"))
        return rows

    def _repeat_measure_block(self, node: dict) -> list[tuple[str, list[str]]]:
        """v11.1 P4: duty block on the evaluation card once a repeat is bought.
        Stays on the card after settlement too (a recovery may re-open the
        evaluation, and the validator keeps demanding the 2-run aggregate -
        the card and the door must tell one story); only a user waive
        (evo waive-repeat) releases both."""
        rm = node.get("repeat_measure")
        if not isinstance(rm, dict) or rm.get("waived"):
            return []
        if node.get("repeat_measure_done"):
            return [("Repeat measurement already settled (report BOTH runs again)", [
                f"- This node's repeat_measure (gate {rm.get('gate')}) was already executed and settled. "
                f"If you are re-reporting this evaluation (e.g. after a recovery), metrics.json must "
                f"carry '{rm.get('result_key')}' with the 2-run training_replication block "
                f"(seeds {rm.get('base_seed')!r} and {rm.get('seed')!r}, aggregation mean, value = mean); "
                "the base run's value = the CURRENT sealed eval measurement (re-read the eval run's raw "
                "metrics after any recovery) - the repeat happened; reporting it is not optional."])]
        if rm.get("engine_run") or node.get("repeat_eval_run"):
            # R9-002: the repeat already ran as first-class engine RUNs; the
            # analyst only AGGREGATES the two sealed measurements.
            base_run = self.store.get_run(self.st, str(node.get("eval_run") or "")) or {}
            rep_run = self.store.get_run(self.st, str(node.get("repeat_eval_run") or "")) or {}
            return [("APPROVED repeat measurement (engine-run buy-back; gate " + str(rm.get("gate")) + ")", [
                f"- The user approved repeating this node's full training+eval ONCE because "
                f"{rm.get('result_key')} landed within {rm.get('band')} ({rm.get('band_source')}) of: "
                + "; ".join(str(x) for x in (rm.get("lines") or [])) + ".",
                f"- The ENGINE already executed the repeat as first-class RUNs - do NOT re-run "
                f"anything. Base evaluation RUN {base_run.get('id')} sealed its raw metrics at "
                f"{str(base_run.get('metrics_file') or '')!r}; repeat evaluation RUN "
                f"{rep_run.get('id')} (fresh seed {rm.get('seed')!r}) sealed its raw metrics at "
                f"{str(rep_run.get('metrics_file') or '')!r}.",
                f"- In metrics.json report '{rm.get('result_key')}' as an object: value = the MEAN of "
                "the two sealed measurements, plus training_replication = {\"aggregation\": \"mean\", "
                "\"runs\": [" +
                f"{{\"seed\": {json.dumps(rm.get('base_seed'))}, \"value\": <sealed base measurement>, "
                f"\"source\": <the base RUN's sealed metrics path above>}}, "
                f"{{\"seed\": {json.dumps(rm.get('seed'))}, \"value\": <sealed repeat measurement>, "
                f"\"source\": <the repeat RUN's sealed metrics path above>}}]}}. The engine recomputes "
                "the mean and cross-checks EACH row against its sealed RUN - neither number is "
                "negotiable at aggregation time.",
                "- All other metrics stay single-run as usual (from the BASE evaluation). EXACTLY one "
                "repeat: a still-ambiguous aggregate is recorded as uncertain, honestly - it can "
                "never buy another run."])]
        return [("APPROVED repeat measurement (one buy-back; gate " + str(rm.get("gate")) + ")", [
            f"- The user approved repeating this node's full training+eval ONCE because "
            f"{rm.get('result_key')} landed within {rm.get('band')} ({rm.get('band_source')}) of: "
            + "; ".join(str(x) for x in (rm.get("lines") or [])) + ".",
            f"- Run the complete workflow+eval again with seed {rm.get('seed')!r} (the first run used "
            f"{rm.get('base_seed')!r}). Write the repeat's artifacts under NEW paths - never overwrite "
            "the first run's sealed outputs. NOTE (recorded degraded delivery, disclosed at the "
            "approval gate): this repeat runs OUTSIDE the engine's RUN/slot/resource machinery - "
            "respect the platform's concurrency etiquette yourself and keep the executed command "
            "and its outputs referenceable (existing repo path or registered artifact).",
            f"- In metrics.json report '{rm.get('result_key')}' as an object: value = the MEAN of the two "
            "runs, plus training_replication = {\"aggregation\": \"mean\", \"runs\": [" +
            f"{{\"seed\": {json.dumps(rm.get('base_seed'))}, \"value\": <run1>, \"source\": \"<artifact>\"}}, "
            f"{{\"seed\": {json.dumps(rm.get('seed'))}, \"value\": <run2>, \"source\": \"<artifact>\"}}]}}. "
            "The engine recomputes the mean and the verdict settles ONCE on this aggregate.",
            "- All other metrics stay single-run as usual. EXACTLY one repeat: a still-ambiguous "
            "aggregate is recorded as uncertain, honestly - it can never buy another run.",
            "- If the repeat cannot be executed (missing resources/artifacts), say so explicitly in the "
            "evaluation report; validation will fail and escalate the blocker to the user rather than "
            "silently keeping the single run."])]

    def _winner_stage_inputs(self, lane: dict, why: str) -> list[tuple[str, str]]:
        """v11.1 T3: winner-only stages (pose/theorize/challenge/mature) read the
        winner's own record (WINNER.json: sketch + its tournament audit) instead
        of re-reading the whole program batch. The batch and tournament stay
        listed as reference paths - never hidden - and validators keep reading
        the sealed originals. Lanes whose winner predates v11.1 have no
        WINNER.json and keep the full rows (cold start = old behavior)."""
        wpath = f".evo/rounds/{lane.get('round')}/lanes/{lane.get('id')}/WINNER.json"
        if eutil.rpath(self.store.repo, wpath).exists():
            psd = str(lane.get("program_set_digest") or "")[:12]
            return [(wpath, why + " (winner record + its audit; engine-written at tournament accept)"),
                    (lane["sketches_path"],
                     f"REFERENCE - full program batch (sealed digest {psd or 'n/a'}); if you are not "
                     "CERTAIN the winner record covers what you need (losing siblings, batch context), "
                     "read it"),
                    (lane["tournament_path"],
                     "REFERENCE - full rankings/audits; read it unless you are CERTAIN this stage needs "
                     "no cross-sketch comparison (losing branches, rank rationale)")]
        return [(lane["sketches_path"], why),
                (lane["tournament_path"], "the tournament audits that bind this stage")]

    def _lane_common_inputs(self, lane: dict) -> list[tuple[str, str]]:
        ins = self._profile_inputs()
        if lane.get("search_origin") == "repair":
            ins.append((".evo/profile/PROBLEM_DOSSIER.md",
                        "repair-only frozen bottlenecks/invariants; constructive search is not bound to these"))
        ins.append((lane["brief_md"], "this lane's brief (goal, constraints, forbidden moves)"))
        idx = egraph.by_id(self.g)
        for p in lane.get("parents", []):
            n = idx.get(p)
            if not n:
                continue
            ins.append((self._node_result_path(n), f"parent {p} result"))
            if n.get("idea_doc"):
                ins.append((n["idea_doc"], f"parent {p} idea"))
        return ins

    def _diagnosis_inputs(self, lane: dict) -> list[tuple[str, str]]:
        """Observed behavior plus the intervention that produced it.

        Candidate programs and candidate-specific prior-art comparisons remain
        hidden, but a parent result is uninterpretable without its parent idea.
        Diagnosis receives that historical intervention as causal context while
        its output remains problem-only and cannot prescribe the next program.
        """
        ins: list[tuple[str, str]] = [
            (".evo/config.json", "evaluation cells, protocols and invariants"),
            (".evo/profile/PROJECT_PROFILE.md", "method-neutral project facts"),
            (".evo/profile/PROBLEM_DOSSIER.md", "method-blind frozen bottleneck hypotheses"),
            (lane["brief_md"], "this lane's goal and constraints"),
        ]
        addendum = ".evo/profile/DOSSIER_ADDENDUM.md"
        if eutil.rpath(self.store.repo, addendum).exists():
            ins.append((addendum, "later method-blind bottlenecks grounded in completed runs"))
        idx = egraph.by_id(self.g)
        for p in lane.get("parents", []):
            n = idx.get(p)
            if n and n.get("role") != "platform":
                ins.append((self._node_result_path(n), f"observed outcome of parent {p}"))
                if n.get("idea_doc"):
                    ins.append((str(n["idea_doc"]),
                                f"historical intervention that produced parent {p}; understand the result, do not copy it as the next solution"))
                    ins.append((str(n["idea_doc"]).replace(".md", ".meta.json"),
                                f"registered assumptions and predictions of parent {p}"))
        return ins

    def _theory_paths(self, lane: dict) -> tuple[str, str]:
        # theory_cycle is a local rigor/budget counter and may be reset after
        # explicit user escalation.  theory_seq is artifact identity and never
        # decreases, so no retry can overwrite an earlier accepted derivation.
        c = int(lane.get("theory_seq") or 0)
        if lane.get("status") == "theorize":
            c += 1
        c = max(c, 1)
        ldir = self._lane_dir(lane)
        return f"{ldir}/THEORY_c{c}.md", f"{ldir}/CHALLENGE_c{c}.md"

    def _observations_block(self, pin_node: str | None = None) -> tuple[list[str], list[str]]:
        """v9: the phenomenon ledger, rendered for bundles. Newest last, capped.

        R7 audit: the 12-row window silently dropped older rows with no
        disclosure - late strategy went recency-blind, and a confirmatory
        lane could not see the very OB rows of the scout it re-runs. The
        window now discloses its cut, and ``pin_node`` always includes that
        node's own active rows (the confirmatory source scout)."""
        rows = self.store.observations(self.st, active_only=True)
        if not rows:
            return (["- (empty - no run phenomena mined yet; the first evaluations will feed it)"], [])
        shown = rows[-12:]
        if pin_node:
            shown_ids = {str(r.get("id")) for r in shown}
            pinned = [r for r in rows if str(r.get("node") or "") == str(pin_node)
                      and str(r.get("id")) not in shown_ids]
            shown = pinned + shown
        out = []
        for r in shown:
            out.append(f"- {r.get('id')}: {r.get('statement')} | where: {r.get('where')} | "
                       f"{r.get('measurement')} (node {r.get('node')})")
        if len(rows) > len(shown):
            out.append(f"- (+{len(rows) - len(shown)} older active observations omitted; full ledger "
                       "at `.evo/evidence/OBSERVATIONS.jsonl`)")
        return out, [str(r.get("id")) for r in shown if str(r.get("id") or "")]

    def _usage_block(self) -> list[str]:
        """Warn when independent rounds converge to the same program core."""
        kernel_kinds: dict[str, int] = {}
        kernel_hashes: dict[str, int] = {}
        anchors: dict[str, int] = {}
        meta_paths = sorted({
            str(n.get("idea_doc") or "").replace(".md", ".meta.json")
            for n in self.g.get("nodes", [])
            if isinstance(n, dict) and n.get("idea_doc")
        })
        for rel in meta_paths:
            meta = eutil.read_json(eutil.rpath(self.store.repo, rel), {}) or {}
            kh = str(meta.get("kernel_hash") or "")
            if kh:
                kernel_hashes[kh] = kernel_hashes.get(kh, 0) + 1
            for row in eprogram.kernel_components(meta):
                kind = str(row.get("kind") or "")
                if kind:
                    kernel_kinds[kind] = kernel_kinds.get(kind, 0) + 1
            for m in meta.get("prior_art_card_ids") or []:
                anchors[str(m)] = anchors.get(str(m), 0) + 1
        warn: list[str] = []
        total = sum(kernel_kinds.values())
        if total >= 4:
            for kind, c in sorted(kernel_kinds.items(), key=lambda kv: -kv[1])[:3]:
                if c / total > 0.4:
                    warn.append(f"- OVERUSED kernel kind {kind}: {c}/{total} load-bearing components use it; "
                                "seek a genuinely different computation when the task permits")
        for kh, c in sorted(kernel_hashes.items(), key=lambda kv: -kv[1])[:3]:
            if c >= 2:
                warn.append(f"- REPEATED exact kernel {kh[:12]}: present in {c} approved ideas; do not "
                            "resubmit it (does NOT apply to a carbon-copy lane's mandated duplicate)")
        for mid, c in sorted(anchors.items(), key=lambda kv: -kv[1])[:3]:
            if c >= 3:
                warn.append(f"- OVERUSED prior-art card {mid}: used in {c} audits; widen the neighbor set")
        return warn or ["- (no overuse detected)"]

    def _next_lane_task(self, lane: dict) -> dict | None:
        if erecover.is_held(self.st, self.g, lane=lane.get("id"), round_=lane.get("round")):
            return None
        stg = lane["status"]
        ldir = self._lane_dir(lane)
        model_parents = [p for p in lane.get("parents", []) if (self.node(p) or {}).get("role") != "platform"]
        tags = list(lane.get("bottleneck_ids") or []) + [lane["intent"]]
        # Reading depth follows the search route/risk. Novelty and theory are
        # independent: an empirical L4 program is not forced to manufacture a
        # derivation, while constructive prior-art audit reads more broadly.
        moon = lane["intent"] == "moonshot"
        if stg == "ablation_design":
            if not lane.get("idea"):
                lane["idea"] = self.store.next_id(self.st, "I")
            iid = lane["idea"]
            parent = model_parents[0] if len(model_parents) == 1 else "(invalid parent contract)"
            parent_node = self.node(parent) or {}
            ins = self._lane_common_inputs(lane) + [
                (str(parent_node.get("idea_doc") or f".evo/nodes/{parent}/NODE_SPEC.json"),
                 "the parent method/idea; understand what produced the observed result"),
                (self._node_result_path(parent_node), "the parent interpretation that created the causal fork"),
                (self._eval_metrics_path(parent_node), "the actual parent measurements; this is the existing reference, never rerun it"),
                (self._eval_report_path(parent_node), "parent slices/anomalies and comparability evidence"),
                (".evo/config.json", "evaluation cells and the user-approved one-run ablation policy"),
            ]
            feedback = (self._instrumental_revision_blocks(lane)
                        + self._retry_direction_blocks(lane, "ablation_design"))
            # Only reachable when the review was written under the CURRENT id
            # (a first-pass redraft before any supersession); superseded ids and
            # their reviews come from _instrumental_revision_blocks above.
            review_path = f".evo/ideas/{iid}.ablation-review.md"
            if eutil.rpath(self.store.repo, review_path).exists():
                feedback.append(("Previous causal-design review (address every objection)",
                                 [f"read `{review_path}`"]))
            obs_lines, obs_ids = self._observations_block()
            return self._present_task(self._create_task(
                "design_ablation", {"round": lane["round"], "lane": lane["id"], "idea": iid},
                [f".evo/ideas/{iid}.md", f".evo/ideas/{iid}.meta.json"],
                extra_fields={"IDEA_ID": iid, "PARENT": parent,
                              "PARENT_RESULT": self._node_result_path(parent_node),
                              "PARENT_METRICS": self._eval_metrics_path(parent_node)},
                inputs=ins,
                extra_blocks=[("Observed graph facts available as additional trigger evidence",
                               obs_lines)] + feedback,
                observation_ids=obs_ids,
                lesson_parents=model_parents, lesson_tags=["ablation", "causal"] + tags))
        if stg == "probe_design":
            if not lane.get("idea"):
                lane["idea"] = self.store.next_id(self.st, "I")
            iid = lane["idea"]
            parent = model_parents[0] if len(model_parents) == 1 else "(invalid parent contract)"
            parent_node = self.node(parent) or {}
            obs_lines, obs_ids = self._observations_block()
            return self._present_task(self._create_task(
                "probe_design", {"round": lane["round"], "lane": lane["id"], "idea": iid},
                [f".evo/ideas/{iid}.md", f".evo/ideas/{iid}.meta.json"],
                extra_fields={"IDEA_ID": iid, "PARENT": parent},
                inputs=self._lane_common_inputs(lane) + [
                    (self._node_result_path(parent_node), "the parent result the question grows out of"),
                    (self._eval_metrics_path(parent_node), "parent measurements; a probe may reuse them"),
                    (".evo/config.json", "evaluation cells and project resource units"),
                ],
                extra_blocks=[("Phenomenon ledger (existing observations - do not re-measure these)",
                               obs_lines),
                              ("The question that opened this probe lane",
                               [f"- read `{lane.get('brief_md')}`"] if lane.get("brief_md") else ["- (see lane brief)"])]
                             # A probe has no review stage, so the user's gate
                             # rejection note is the ONLY revision signal this
                             # redraft can carry; without this the agent redraws
                             # from byte-identical inputs.
                             + self._retry_direction_blocks(lane, "probe_design")
                             + self._instrumental_revision_blocks(lane),
                observation_ids=obs_ids,
                lesson_parents=model_parents, lesson_tags=["probe"] + tags))
        if stg == "maintenance_design":
            if not lane.get("idea"):
                lane["idea"] = self.store.next_id(self.st, "I")
            iid = lane["idea"]
            parent = model_parents[0] if len(model_parents) == 1 else "(invalid parent contract)"
            parent_node = self.node(parent) or {}
            feedback = (self._instrumental_revision_blocks(lane)
                        + self._retry_direction_blocks(lane, "maintenance_design"))
            # As for ablation: only reachable while the review still sits under
            # the CURRENT id.  After a REVISE the id has been superseded, and
            # the block above is what recovers the real review path.
            review_path = f".evo/ideas/{iid}.maintenance-review.md"
            if eutil.rpath(self.store.repo, review_path).exists():
                feedback.append(("Previous maintenance review (address every objection)",
                                 [f"read `{review_path}`"]))
            obs_lines, obs_ids = self._observations_block()
            return self._present_task(self._create_task(
                "maintenance_design", {"round": lane["round"], "lane": lane["id"], "idea": iid},
                [f".evo/ideas/{iid}.md", f".evo/ideas/{iid}.meta.json"],
                extra_fields={"IDEA_ID": iid, "PARENT": parent},
                inputs=self._lane_common_inputs(lane) + [
                    (self._node_result_path(parent_node), "the parent whose executable base this repairs"),
                    (self._eval_metrics_path(parent_node), "the parity reference measurements"),
                    (".evo/config.json", "evaluation cells the parity contract covers"),
                ],
                extra_blocks=[("Defect evidence available (ER/OB ids are citable)",
                               (ebundle.errors_block(self.store, self.cfg, st=self.st) or ["- none recorded"])
                               + obs_lines),
                              ("The defect that opened this maintenance lane",
                               [f"- read `{lane.get('brief_md')}`"] if lane.get("brief_md") else ["- (see lane brief)"])] + feedback,
                observation_ids=obs_ids,
                lesson_parents=model_parents, lesson_tags=["maintenance"] + tags))
        if stg == "maintenance_review":
            iid = lane["idea"]
            parent = model_parents[0] if len(model_parents) == 1 else "(invalid parent contract)"
            return self._present_task(self._create_task(
                "maintenance_review", {"round": lane["round"], "lane": lane["id"], "idea": iid},
                [f".evo/ideas/{iid}.maintenance-review.md"],
                extra_fields={"IDEA_ID": iid, "PARENT": parent},
                inputs=self._lane_common_inputs(lane) + [
                    (f".evo/ideas/{iid}.md", "the proposed maintenance change"),
                    (f".evo/ideas/{iid}.meta.json", "its frozen defect/boundary/parity contract"),
                    (self._node_result_path(self.node(parent) or {"id": parent}),
                     "the parent result whose semantics must be preserved"),
                    (".evo/config.json", "decision cells the parity settlement will cover"),
                ],
                lesson_parents=model_parents, lesson_tags=["maintenance"] + tags))
        if stg == "ablation_review":
            iid = lane["idea"]
            parent = model_parents[0] if len(model_parents) == 1 else "(invalid parent contract)"
            return self._present_task(self._create_task(
                "review_ablation", {"round": lane["round"], "lane": lane["id"], "idea": iid},
                [f".evo/ideas/{iid}.ablation-review.md"],
                extra_fields={"IDEA_ID": iid, "PARENT": parent},
                inputs=self._lane_common_inputs(lane) + [
                    (f".evo/ideas/{iid}.md", "the proposed causal diagnostic"),
                    (f".evo/ideas/{iid}.meta.json", "its frozen X1/X2, intervention and decision map"),
                    (self._node_result_path(self.node(parent) or {"id": parent}), "the parent result claimed as trigger"),
                    (self._eval_metrics_path(self.node(parent) or {"id": parent}), "the parent measurements; check that the question is real"),
                    (".evo/config.json", "resource, seed and ablation limits"),
                ],
                lesson_parents=model_parents, lesson_tags=["ablation", "causal"] + tags))
        if stg == "diagnose":
            obs_lines, obs_ids = self._observations_block()
            return self._present_task(self._create_task(
                "diagnose", {"round": lane["round"], "lane": lane["id"]},
                [f"{ldir}/DIAGNOSIS.json"],
                extra_fields={"LANE_INTENT": lane["intent"], "MIN_LEVEL": str(lane["min_level"])},
                inputs=self._diagnosis_inputs(lane),
                extra_blocks=[("Phenomenon ledger (observed facts only; candidate programs and "
                               "candidate-specific prior-art comparisons are deliberately withheld)",
                               obs_lines)],
                observation_ids=obs_ids))
        if stg == "deep_read":
            blocks = []
            topics = lane.get("required_topics") or []
            if topics:
                blocks.append(("The challenge critic requires reading on these topics (cover EVERY one with new cards)",
                               [f"- topic: {t}" for t in topics]))
            origin = str(lane.get("search_origin") or "repair")
            if moon:
                key = "mech_cards_min_moonshot"
            elif origin == "theory_derived":
                key = "mech_cards_min_theory_derived"
            elif origin in ("constructive", "core_synthesis"):
                key = "mech_cards_min_constructive"
            else:
                key = "mech_cards_min_per_lane"
            need = econfig.budget(self.cfg, key)
            reading_inputs = self._lane_common_inputs(lane) + [
                *(([(lane["diagnosis_path"], "the frozen repair diagnosis; reading may test it but may not rewrite it")]
                   if lane.get("diagnosis_path") else [])),
                *(([(lane["sketches_path"], "the already-frozen program set; map prior art and evidence without rewriting it")]
                   if origin != "repair" and lane.get("sketches_path") else [])),
                (".evo/evidence/EVIDENCE.jsonl", "screened paper pool; append only need-driven gaps"),
                (".evo/evidence/MECH_CARDS.jsonl", "reusable paper core-work facts; continue M### numbering"),
                (".evo/evidence/COLLISION_AUDITS.jsonl",
                 "candidate-bound comparison edges; continue CA### numbering and never rewrite old attempts")]
            if lane.get("sketches_path") and not any(p == lane["sketches_path"] for p, _ in reading_inputs):
                reading_inputs.append((lane["sketches_path"],
                                       "the frozen program set; bind every collision edge to its exact digest"))
            if lane.get("sketches_path") and lane.get("program_set_digest"):
                # R3 operability audit: these are ENGINE canonical-JSON hashes
                # (sorted keys, tight separators, subset fields) - an agent
                # cannot recompute them from file bytes, and state.json is off
                # limits. Print them or the digest duties are unsatisfiable.
                sdata = eutil.read_json(eutil.rpath(self.store.repo, str(lane["sketches_path"])), {}) or {}
                digest_rows = [
                    "Engine-computed canonical-JSON hashes. Copy VERBATIM - they are NOT the",
                    "sha256 of any file's raw bytes and cannot be recomputed by hand.",
                    f"- program_set_digest (every new CA edge): {lane['program_set_digest']}"]
                digest_rows += [
                    f"- {str(s.get('sketch_id'))} candidate_digest: {eprogram.candidate_digest(s)}"
                    for s in (sdata.get("sketches") or []) if isinstance(s, dict)]
                blocks.append(("Frozen digests (copy VERBATIM into collision edges)", digest_rows))
            mech_rows = self.store.mech_cards()
            collision_rows = eutil.read_jsonl(
                eutil.rpath(self.store.repo, ".evo/evidence/COLLISION_AUDITS.jsonl"))
            ev_n, ev_digest = evalid.ledger_watermark(self.st, "evidence", self.store.evidence())
            mech_n, mech_digest = evalid.ledger_watermark(self.st, "mech", mech_rows)
            col_n, col_digest = evalid.ledger_watermark(self.st, "collision", collision_rows)
            return self._present_task(self._create_task(
                "deep_read", {"round": lane["round"], "lane": lane["id"],
                              "prior_evidence_count": ev_n,
                              "prior_evidence_digest": ev_digest,
                              "prior_mech_count": mech_n,
                              "prior_mech_digest": mech_digest,
                              "prior_collision_count": col_n,
                              "prior_collision_digest": col_digest},
                [".evo/evidence/MECH_CARDS.jsonl", ".evo/evidence/COLLISION_AUDITS.jsonl"],
                extra_fields={"LANE_INTENT": lane["intent"], "MIN_LEVEL": str(lane["min_level"]),
                              "SEARCH_ORIGIN": origin,
                              "MIN_CARDS": str(need)},
                inputs=reading_inputs,
                extra_blocks=blocks,
                lesson_parents=model_parents, lesson_tags=tags))
        if stg == "sketch":
            fb = self._sketch_retry_blocks(lane)
            origin = str(lane.get("search_origin") or "repair")
            cycle = int(lane.get("attempt_seq") or 0) + 1
            program_inputs = self._lane_common_inputs(lane) + self._effect_comparator_inputs(lane)
            if origin == "repair":
                program_inputs += [
                    (lane["diagnosis_path"], "the immutable repair diagnosis; cite H# without rewriting it"),
                    *self._ledger_slice_rows(lane, [("MECH", "core-work audits already read for this repair")])]
            elif origin == "theory_derived":
                program_inputs += [
                    (str(lane.get("problem_path")), "the posed obstruction/desiderata"),
                    (str(lane.get("theory_path")), "the surviving derivation and its executable consequences")]
            elif origin == "core_synthesis":
                program_inputs += [
                    (str(lane.get("core_palette_path")),
                     "the engine-projected anonymous core-work palette: transform operational invariants "
                     "into one new load-bearing relation; do not stack its source mechanisms as modules")]
            sketch_count = str(econfig.budget(self.cfg, "sketches_per_lane"))
            copy_duty = "(none - normal novelty search)"
            for field, label in (("scaling_followup_of", "SCALING FOLLOW-UP"),
                                 ("confirmatory_of", "CONFIRMATORY RE-RUN")):
                src = lane.get(field)
                if not src:
                    continue
                # v11.1 (R1 fix): a cold agent could not even discover the lane
                # was a carbon-copy lane, let alone find the kernel to copy -
                # surface the identity AND the parent's frozen kernel sources.
                sn = egraph.by_id(self.g).get(str(src)) or {}
                if sn.get("idea_doc"):
                    program_inputs += [
                        (str(sn["idea_doc"]).replace(".md", ".meta.json"),
                         f"{label} SOURCE {src}: its frozen program/novelty/kernel_hash - copy the kernel "
                         "payload (statements, components, operator refs, bearer) VERBATIM"),
                        (str(sn["idea_doc"]), f"{label} source {src}: the idea prose for context")]
                copy_duty = (f"{label} of {src}: submit EXACTLY ONE program re-running that node's frozen "
                             "kernel verbatim" + (" at the registered scale points; novelty.kind must be "
                                                  "'scaling_extension'; effect comparator = that parent"
                                                  if field == "scaling_followup_of" else
                                                  " under FULL pre-registration (all duties apply); "
                                                  "cite its OB### observations"))
                # (final audit C12) BOTH copy species submit exactly one
                # program - the card headline must agree with the validator.
                sketch_count = "1"
            promotion_blocks = self._promotion_blocks(lane)
            sk_digests = [
                "Engine-computed canonical-JSON hashes. Copy VERBATIM - they are NOT the",
                "sha256 of any file's raw bytes and cannot be recomputed by hand.",
                "- baseline_program_digest (top level): "
                + evalid.json_file_digest(self.ctx(), ".evo/profile/BASELINE_PROGRAM.json")]
            if lane.get("diagnosis_digest"):
                sk_digests.append(f"- diagnosis_digest (each candidate): {lane['diagnosis_digest']}")
            if lane.get("theory_digest"):
                sk_digests.append(f"- theory_digest (top level): {lane['theory_digest']}")
            if lane.get("core_palette_digest"):
                sk_digests.append(f"- core_palette_digest (top level): {lane['core_palette_digest']}")
            obs_lines, obs_ids = self._observations_block(
                pin_node=str(lane.get("confirmatory_of") or "") or None)
            return self._present_task(self._create_task(
                "sketch", {"round": lane["round"], "lane": lane["id"]},
                [f"{ldir}/PROGRAMS_c{cycle}.json"],
                extra_fields={"LANE_INTENT": lane["intent"], "MIN_LEVEL": str(lane["min_level"]),
                              "SEARCH_ORIGIN": origin,
                              "SKETCH_COUNT": sketch_count,
                              "COPY_DUTY": copy_duty,
                              "PARENTS": ", ".join(lane.get("parents", [])) or "(none)"},
                inputs=program_inputs,
                extra_blocks=promotion_blocks + [("Frozen digests (copy VERBATIM where the schema requires them)",
                               sk_digests),
                              ("Sibling nodes (already tried on these parents)",
                               ebundle.sibling_summary(self.g, model_parents, econfig.primary_metric(self.cfg)) or ["- none"]),
                              ("Shared artifacts available for reuse (design stages around them)",
                               eartifact.artifacts_block(self.reg)),
                              ("Phenomenon ledger (OB### - anomalies measured in THIS graph's own runs; "
                               "a program grounded in one outranks an ungrounded pattern analogy)",
                               obs_lines),
                              ("Idea-space usage watch (cross-round homogenization guard)",
                               self._usage_block())] + fb,
                observation_ids=obs_ids,
                artifact_receipts=eartifact.artifacts_receipts(self.reg),
                lesson_parents=model_parents, lesson_tags=tags))
        if stg == "tournament":
            mode_duty = (
                "RESEARCH MODE: a sketch whose mechanism nearly matches published work needs a stated "
                "difference to advance."
                if econfig.is_research(self.cfg) else
                "ENGINEERING MODE: overlap with published work is legitimate - audit FIT and NON-TRIVIALITY "
                "instead (does the proposed program fit the available evidence? would a config-level change do the same?). "
                "Boldness is never a kill reason; only incoherence, misfit and triviality are.")
            tcycle = int(lane.get("attempt_seq") or 1)
            tournament_inputs = self._lane_common_inputs(lane) + [
                (lane["sketches_path"], "the frozen complete-program set under review"),
                (".evo/evidence/EVIDENCE.jsonl", "evidence pool for nearest-prior checks"),
                (".evo/evidence/MECH_CARDS.jsonl", "reusable paper core-work facts"),
                (".evo/evidence/COLLISION_AUDITS.jsonl", "digest-bound program/paper collision audits")]
            tournament_inputs += self._effect_comparator_inputs(lane)
            if econfig.sota_enabled(self.cfg) and lane.get("intent") != "platform":
                tournament_inputs.append(
                    (".evo/evidence/SOTA.jsonl", "the SOTA library whose C# bindings constrain frontier_refs"))
            promotion_blocks = self._promotion_blocks(lane)
            tomb_rows = ebundle.tombstones_reviewer_block(self.store)
            t_sdata = eutil.read_json(eutil.rpath(self.store.repo, str(lane.get("sketches_path") or "")), {}) or {}
            t_digests = [
                "Engine-computed canonical-JSON hashes. Copy VERBATIM - they are NOT the",
                "sha256 of any file's raw bytes and cannot be recomputed by hand.",
                f"- TOURNAMENT.json program_set_digest: {lane.get('program_set_digest')}"]
            t_digests += [
                f"- audit({str(s.get('sketch_id'))}).program_digest: {eprogram.candidate_digest(s)}"
                for s in (t_sdata.get("sketches") or []) if isinstance(s, dict)]
            return self._present_task(self._create_task(
                "tournament", {"round": lane["round"], "lane": lane["id"]},
                [f"{ldir}/TOURNAMENT_c{tcycle}.json"],
                extra_fields={"LANE_INTENT": lane["intent"], "MIN_LEVEL": str(lane["min_level"]),
                              "SEARCH_ORIGIN": str(lane.get("search_origin")),
                              "WINNERS_MAX": str(econfig.budget(self.cfg, "winners_per_lane")),
                              "MODE": econfig.mode(self.cfg), "MODE_DUTY": mode_duty},
                inputs=tournament_inputs,
                extra_blocks=promotion_blocks + [("Frozen digests (bind your audit to these exact values)",
                               t_digests),
                              ("Sibling nodes (potential duplicates)",
                               ebundle.sibling_summary(self.g, model_parents, econfig.primary_metric(self.cfg)) or ["- none"])]
                             + ([("Known published-territory tombstones (cite known_tombstone on a re-hit; "
                                  "author new criteria narrowly)", tomb_rows)] if tomb_rows else []),
                lesson_parents=model_parents, lesson_tags=tags))
        if stg == "pose":
            before_program = lane.get("search_origin") == "theory_derived" and not lane.get("winner_sketch")
            pose_inputs = self._lane_common_inputs(lane)
            if before_program:
                pose_inputs += [(".evo/config.json", "task/evaluation/resource desiderata the result must serve"),
                                (".evo/profile/BASELINE_PROGRAM.json", "comparison baseline only; no internal-kinship duty")]
            else:
                pose_inputs += self._winner_stage_inputs(
                    lane, "the winning program whose theoretical claim is being posed")
            return self._present_task(self._create_task(
                "pose", {"round": lane["round"], "lane": lane["id"]},
                [f"{ldir}/PROBLEM_c{int(lane.get('problem_seq') or 0) + 1}.md"],
                extra_fields={"LANE_INTENT": lane["intent"], "MIN_LEVEL": str(lane["min_level"]),
                              "WINNER": str(lane.get("winner_sketch") or "(theory before program)"),
                              "THEORY_POSITION": "before program" if before_program else "after program"},
                inputs=pose_inputs,
                extra_blocks=self._retry_direction_blocks(lane, "pose"),
                lesson_parents=model_parents, lesson_tags=tags))
        if stg == "theorize":
            tpath, cpath = self._theory_paths(lane)
            cyc = int(lane.get("theory_cycle") or 1)
            fb = []
            previous_challenge = None
            if int(lane.get("theory_seq") or 0) > 0 and lane.get("theory_path"):
                prev = f"{ldir}/CHALLENGE_c{int(lane.get('theory_seq') or 0)}.md"
                if eutil.rpath(self.store.repo, prev).exists():
                    previous_challenge = prev
                    fb.append(("Previous challenge (answer EVERY objection; quote it where you respond)",
                               [f"read `{prev}`"]))
            fb += self._retry_direction_blocks(lane, "theorize")
            before_program = lane.get("search_origin") == "theory_derived" and not lane.get("winner_sketch")
            moon_extra = ""
            ins = self._lane_common_inputs(lane)
            if before_program:
                ins += [(str(lane.get("problem_path")), "the posed obstruction/desiderata to solve"),
                        (".evo/profile/BASELINE_PROGRAM.json", "baseline for external comparison, not a required ancestor")]
            else:
                ins += self._winner_stage_inputs(
                    lane, "the winning executable program this theory must explain/constrain")
            if lane.get("required_topics") or lane.get("reading_done"):
                ins += self._ledger_slice_rows(lane, [("MECH", "core-work audits relevant to the derivation")])
            formal_duty = "(this lane is not formal: derive in prose, assumption -> consequence)"
            if lane.get("formal"):
                ins.append((str(lane.get("problem_path")), "THE POSED PROBLEM - the theory must solve "
                                                           "exactly this, in its declared symbols"))
                bud = self.cfg.get("budgets", {})
                need = (int(bud.get("derivation_steps_min_full", 5))
                        if str(lane.get("formal_kind") or "") == "full"
                        else int(bud.get("derivation_steps_min", 3)))
                formal_duty = (
                    f"FORMAL LANE: the `## Derivation` section must be a numbered STEP CHAIN of >= {need} lines:\n"
                    f"  - S1 [from A1, A2]: <formal claim> ; reads: <plain-language meaning> ; fails-if: <condition>\n"
                    f"  each step cites its premises (A# from the posed problem's Given, or EARLIER S#);\n"
                    f"  every step carries a 'reads:' shadow; >= half carry 'fails-if:'; one step carries the\n"
                    f"  literal marker '[establishes: Want]'; every posed symbol must appear in the chain.\n"
                    f"  Solve the POSED problem - do not quietly change what is being asked.")
                if str(lane.get("formal_kind") or "") == "full":
                    formal_duty += (
                        "\n  TOY CHECK (formalizable=full): also ship TOY_CHECK.py in this lane's round "
                        "directory - a tiny stdlib-only script (no imports beyond the stdlib, < 60s) that "
                        "instantiates the posed objects on a TOY INSTANCE, asserts >= 1 derivation step "
                        "numerically, and prints 'TOY_CHECK_OK' plus the S# ids it verified. The engine "
                        "EXECUTES it at submit - a chain your own toy instance falsifies is rejected "
                        "before it can waste an expensive stage run.")
            return self._present_task(self._create_task(
                "theorize", {"round": lane["round"], "lane": lane["id"], "cycle": cyc,
                              "artifact_seq": int(lane.get("theory_seq") or 0) + 1,
                              "previous_challenge": previous_challenge},
                [tpath],
                extra_fields={"LANE_INTENT": lane["intent"], "MIN_LEVEL": str(lane["min_level"]),
                              "CYCLE": str(cyc), "WINNER": str(lane.get("winner_sketch")),
                              "THEORY_OUTPUT": tpath,
                              "THEORY_POSITION": "before program" if before_program else "after program",
                              "CYCLE_EXTRA": moon_extra, "FORMAL_DUTY": formal_duty,
                              "PARENTS": ", ".join(lane.get("parents", [])) or "(none; only external contract is shared)"},
                inputs=ins,
                extra_blocks=fb,
                lesson_parents=model_parents, lesson_tags=tags))
        if stg == "challenge":
            tpath, cpath = self._theory_paths(lane)
            cyc = int(lane.get("theory_cycle") or 1)
            min_cyc = (int(self.cfg["budgets"].get("theory_cycles_min_full", 2))
                       if str(lane.get("formal_kind") or "") == "full" else 1)
            before_program = lane.get("search_origin") == "theory_derived" and not lane.get("winner_sketch")
            ins = self._lane_common_inputs(lane) + [(tpath, "the theory under adversarial audit")]
            if before_program:
                ins.append((str(lane.get("problem_path")), "the posed problem the theory must actually solve"))
            else:
                ins += self._winner_stage_inputs(
                    lane, "the executable program whose mechanism the theory addresses")
            if lane.get("reading_done"):
                ins += self._ledger_slice_rows(lane, [("EVIDENCE", "evidence for collision/factual checks"),
                                                      ("MECH", "core-work audits used by the theory")])
            if lane.get("formal"):
                ins.append((str(lane.get("problem_path")), "the posed problem - audit that the chain solves "
                                                           "THIS and not a quietly-substituted easier one"))
            return self._present_task(self._create_task(
                "challenge", {"round": lane["round"], "lane": lane["id"], "cycle": cyc},
                [cpath],
                extra_fields={"LANE_INTENT": lane["intent"], "MIN_LEVEL": str(lane["min_level"]),
                              "CYCLE": str(cyc), "MIN_CYCLES": str(min_cyc), "THEORY_PATH": tpath,
                              "THEORY_POSITION": "before program" if before_program else "after program",
                              "FORMAL_FLAG": "FORMAL lane: the '## Step audit' attack is mandatory."
                              if lane.get("formal") else
                              "Prose lane: you may verdict FORMALIZE if a precise claim is hiding in prose."},
                inputs=ins,
                lesson_parents=model_parents, lesson_tags=tags))
        if stg == "mature":
            if not lane.get("idea"):
                lane["idea"] = self.store.next_id(self.st, "I")
            iid = lane["idea"]
            fb = self._winner_revision_blocks(lane) + self._retry_direction_blocks(lane, "mature")
            if eutil.rpath(self.store.repo, f".evo/ideas/{iid}.review.md").exists():
                fb.append(("Red-team review of your previous version (address every point)",
                           [f"read `.evo/ideas/{iid}.review.md`"]))
            ins = self._lane_common_inputs(lane) + self._winner_stage_inputs(
                lane, "your winning sketch + why it won; its audit binds you") + [
                *self._ledger_slice_rows(lane, [("MECH", "mechanism cards to cite as [M###]")]),
                (".evo/config.json", "metric spec for predictions")]
            theory_doc = ""
            if self._needs_theory(lane):
                theory_doc = str(lane.get("theory_path") or "")
                ins.append((theory_doc, "the surviving theory; the idea formalizes it"))
            elif lane.get("theory_downgraded") and lane.get("theory_path"):
                theory_doc = str(lane.get("theory_path"))
                ins.append((theory_doc, "rejected optional theory; preserve its failure in theory_audit, "
                                        "but do not retain a theory claim"))
                challenge = (f"{ldir}/CHALLENGE_c{int(lane.get('theory_seq') or 0)}.md"
                             if int(lane.get("theory_seq") or 0) > 0 else "")
                if challenge and eutil.rpath(self.store.repo, challenge).exists():
                    ins.append((challenge, "the final critic verdict that rejected the optional theory; "
                                           "use its actual objections in theory_audit"))
            formal_duty = "(not a formal lane)"
            if lane.get("formal"):
                ins.append((str(lane.get("problem_path")), "the posed problem - the idea's Formal statement "
                                                           "states the RESULT in its symbols"))
                formal_duty = ("FORMAL lane: add a `## Formal statement` section (proposition style, in the "
                               "posed problem's symbols) and set meta.problem_doc to the problem path above.")
            sota_duty = "(no SOTA library in force)"
            winner = self.ctx().winner_sketch(lane) or {}
            research_kernel = str((winner.get("novelty") or {}).get("kind") or "") in eprogram.RESEARCH_NOVELTY
            if winner:
                # Engine-authored exact copies (v10.1): the mature contract may
                # expand but not redesign the winner, so every field validated
                # by byte-equality against the winner/lane state is pre-filled.
                prefill: dict = {
                    "sketch_id": lane.get("winner_sketch"),
                    # v11.1 P5 (R1 fix): was hard-coded "candidate", which
                    # guaranteed the purpose-binding rejection for exploratory.
                    "experiment_purpose": str(lane.get("experiment_purpose") or "candidate"),
                    "change_scope": winner.get("change_scope"),
                    "program": winner.get("program"),
                    "novelty": winner.get("novelty"),
                    "program_digest": lane.get("winner_program_digest"),
                    "kernel_hash": lane.get("winner_kernel_hash"),
                }
                if lane.get("intent") != "platform":
                    prefill["effect_case"] = winner.get("effect_case")
                    prefill["claim_scope"] = winner.get("claim_scope")
                if lane.get("theory_downgraded"):
                    prefill["theory_role"] = "none"
                else:
                    for field in ("theory_role", "theory_rigor", "theory_obligations"):
                        prefill[field] = winner.get(field)
                    if winner.get("theory_role") != "none":
                        prefill["theory_target"] = winner.get("theory_target")
                if lane.get("search_origin") == "repair":
                    prefill["diagnosis_digest"] = lane.get("diagnosis_digest")
                prefill["level"] = eprogram.compute_level(prefill)
                self._prefill_output(f".evo/ideas/{iid}.meta.json", prefill)
            if lane.get("experiment_purpose") in econfig.EXPLORATORY_PURPOSES:
                # v11.1 P5 (R1 fix): the duty text used to be purpose-blind, so
                # an exploratory lane was affirmatively TOLD to invent SOTA
                # targets its validators would then ignore.
                sota_duty = ("EXPLORATORY LANE: no sota_targets, no registered predictions - your results "
                             "are observations only (no frontier, no records, promotion not_applicable). "
                             "Spend the foresight budget on honest mechanism description instead; the "
                             "conclusion MUST emit >= 1 phenomenon-ledger observation.")
            elif econfig.sota_enabled(self.cfg) and research_kernel and lane.get("intent") != "platform":
                ins += self._ledger_slice_rows(lane, [("SOTA", "the SOTA library - name >= 1 entry this idea beats")])
                sota_duty = ("SOTA duty: meta.sota_targets = [{\"sota\": \"S###\", \"cell\": \"C#\", "
                             "\"dimension\": \"effect|efficiency|modeling|generality\", "
                             "\"claim\": \">=60 chars\"}] - "
                             "name whom you beat and on which axis; the conclusion will settle each claim.")
            obs_lines, obs_ids = self._observations_block()
            return self._present_task(self._create_task(
                "mature", {"round": lane["round"], "lane": lane["id"], "idea": iid},
                [f".evo/ideas/{iid}.md", f".evo/ideas/{iid}.meta.json"],
                extra_fields={"LANE_INTENT": lane["intent"], "MIN_LEVEL": str(lane["min_level"]),
                              "IDEA_ID": iid, "WINNER": str(lane.get("winner_sketch")),
                              "PARENTS": ", ".join(lane.get("parents", [])) or "(none)",
                              "THEORY_DOC": theory_doc or "(no theory stage for this lane)",
                              "FORMAL_DUTY": formal_duty, "SOTA_DUTY": sota_duty,
                              "EXPERIMENT_PURPOSE": str(lane.get("experiment_purpose") or "candidate"),
                              "MODE": econfig.mode(self.cfg)},
                inputs=ins,
                extra_blocks=([("Sibling nodes (differentiate from these)",
                                ebundle.sibling_summary(self.g, model_parents, econfig.primary_metric(self.cfg)) or ["- none"]),
                               ("Shared artifacts available for reuse",
                                eartifact.artifacts_block(self.reg)),
                               ("Phenomenon ledger (OB### - legal assumption sources)",
                                obs_lines)] + fb),
                observation_ids=obs_ids,
                artifact_receipts=eartifact.artifacts_receipts(self.reg),
                lesson_parents=model_parents, lesson_tags=tags))
        if stg == "red_team":
            iid = lane["idea"]
            mode_duty = (
                "RESEARCH MODE: near-identity with published work without a stated, meaningful difference "
                "is REJECT_DUPLICATE - novelty is a goal of this run."
                if econfig.is_research(self.cfg) else
                "ENGINEERING MODE: matching published literature is NOT a rejection reason - borrowing a "
                "well-fitting method is the point. REJECT_DUPLICATE applies only to duplicates of ideas/nodes "
                "already in THIS graph. Attack triviality and fit instead: would a competent engineer try this "
                "in the first hour (REJECT_SHALLOW)? do the transfer conditions actually hold here?")
            red_team_inputs = self._lane_common_inputs(lane) + [
                (lane["tournament_path"],
                 "the frozen winner audit; keep its effect comparator distinct from promotion evidence"),
                (f".evo/ideas/{iid}.md", "the idea under adversarial review"),
                (f".evo/ideas/{iid}.meta.json", "its frozen program, kernel, typed effect/resource case, predictions and assumptions"),
                (".evo/evidence/EVIDENCE.jsonl", "evidence pool for prior-art attack"),
                *self._ledger_slice_rows(lane, [("MECH", "mechanism cards it cites")]),
                (".evo/evidence/COLLISION_AUDITS.jsonl", "candidate-bound prior-program comparisons")]
            red_team_inputs += self._effect_comparator_inputs(lane)
            if econfig.sota_enabled(self.cfg) and lane.get("intent") != "platform":
                red_team_inputs += self._ledger_slice_rows(
                    lane, [("SOTA", "the SOTA library whose S# entries may support or refute promotion claims")])
            tomb_rows = ebundle.tombstones_reviewer_block(self.store)
            return self._present_task(self._create_task(
                "red_team", {"round": lane["round"], "lane": lane["id"], "idea": iid},
                [f".evo/ideas/{iid}.review.md"],
                extra_fields={"IDEA_ID": iid, "LANE_INTENT": lane["intent"], "MIN_LEVEL": str(lane["min_level"]),
                              "SEARCH_ORIGIN": str(lane.get("search_origin")),
                              "MODE": econfig.mode(self.cfg), "MODE_DUTY": mode_duty},
                inputs=red_team_inputs,
                extra_blocks=self._promotion_blocks(lane)
                             + ([("Known published-territory tombstones (a re-hit writes `TOMBSTONE: TB###`; "
                                  "author new criteria narrowly)", tomb_rows)] if tomb_rows else []),
                lesson_parents=model_parents, lesson_tags=tags))
        if stg == "gate":
            gate = self._find_lane_gate(lane)
            if gate is None:
                iid = lane["idea"]
                purpose = str(lane.get("experiment_purpose") or "candidate")
                contract_digest = self._idea_contract_digest(lane)
                review_needed = purpose != "diagnostic_probe"
                if not contract_digest or not lane.get("idea_seal") or \
                        (review_needed and not lane.get("review_seal")):
                    raise SystemExit(f"[evo] lane {lane['id']} reached approval without its sealed "
                                     f"{'idea' if not review_needed else 'idea+review'} contract")
                review_path = {
                    "targeted_ablation": f".evo/ideas/{iid}.ablation-review.md",
                    "maintenance": f".evo/ideas/{iid}.maintenance-review.md",
                }.get(purpose, f".evo/ideas/{iid}.review.md")
                label = {"targeted_ablation": "targeted causal diagnostic",
                         "diagnostic_probe": "bounded diagnostic probe (no novelty claim)",
                         "maintenance": "parity-contracted maintenance change (no novelty claim)",
                         }.get(purpose, "matured idea")
                pointer = (f"see .evo/ideas/{iid}.md" if not review_needed
                           else f"see .evo/ideas/{iid}.md and its ACCEPT review {review_path}")
                gate = self.store.new_gate(self.st, "idea_approval",
                                           {"lane": lane["id"], "idea": iid,
                                            "contract_digest": contract_digest,
                                            "winner_program_digest": lane.get("winner_program_digest")},
                                           f"Lane {lane['id']} ({lane['intent']}) {label} {iid}: {pointer}")
            if (gate.get("subject") or {}).get("contract_digest") != self._idea_contract_digest(lane):
                raise SystemExit(f"[evo] idea gate {gate.get('id')} does not bind the active sealed contract")
            if gate["status"] == "approved":
                lane["status"] = "approved"
                return self._next_lane_task(lane)
            if self._maybe_auto_resolve(gate):
                return self._next_lane_task(lane) if lane["status"] not in ("abandoned", "done") else None
            return self._present_gate(gate)
        if stg == "approved":
            gate = self._find_lane_gate(lane)
            if gate is None or gate.get("status") != "approved" or \
                    (gate.get("subject") or {}).get("contract_digest") != self._idea_contract_digest(lane):
                raise SystemExit(f"[evo] lane {lane['id']} cannot plan from an unsealed or differently approved idea")
            ldirp = self._lane_dir(lane)
            meta = eutil.read_json(
                eutil.rpath(self.store.repo, f".evo/ideas/{lane['idea']}.meta.json"), {}) or {}
            # Engine-authored exact copies from the approved idea (v10.1); the
            # agent adds workflow/eval/smoke planning to the same file.
            prefill = {
                "role": econfig.INTENT_TO_ROLE[lane["intent"]],
                "experiment_purpose": meta.get("experiment_purpose"),
                "parents": list(meta.get("parents") or []) + list(meta.get("platforms_consumed") or []),
                "level": meta.get("level"),
            }
            # v11.1 (R2 fix): exploratory carries a full audited program too -
            # keying custody on == "candidate" severed the scout's chain
            # (digest/kernel/effect bindings silently skipped). Program-carrying
            # purposes share one custody path; only instrumental purposes lack
            # a program.
            if meta.get("experiment_purpose") in ("candidate", "exploratory"):
                prefill.update({
                    "program_digest": meta.get("program_digest"),
                    "kernel_ids": eprogram.kernel_ids(meta),
                    "program_ir": meta.get("program"),
                    "novelty_kernel": (meta.get("novelty") or {}).get("kernel") or [],
                    "effect_case": meta.get("effect_case"),
                    "theory_obligations": meta.get("theory_obligations"),
                })
                if evalid.is_probe_active(meta):
                    probe = meta.get("mechanism_probe") or {}
                    prefill["probe_execution"] = {
                        field: probe.get(field)
                        for field in ("mode", "signal", "expect", "artifact",
                                      "required_fields", "decision_rule")}
            if meta.get("experiment_purpose") == "targeted_ablation":
                prefill["ablation"] = meta.get("ablation")
            if meta.get("experiment_purpose") == "diagnostic_probe":
                prefill["probe"] = meta.get("probe")
            if meta.get("experiment_purpose") == "maintenance":
                prefill["maintenance"] = meta.get("maintenance")
            # Replace a draft bound to a DIFFERENT idea (a superseded attempt
            # left its spec at this lane path); keep the agent's in-progress
            # draft for the same approved idea untouched.  Identity is judged
            # per purpose: candidates by program_digest (a draft without one
            # predates the engine pre-fill and cannot be this idea's),
            # ablations by their exact-copy contract, and a purpose flip is
            # always a different idea.
            existing = eutil.read_json(eutil.rpath(self.store.repo, f"{ldirp}/NODE_SPEC.json"), None)
            stale = False
            if isinstance(existing, dict):
                if existing.get("experiment_purpose") != meta.get("experiment_purpose"):
                    stale = True
                elif meta.get("experiment_purpose") in ("candidate", "exploratory"):
                    stale = existing.get("program_digest") != meta.get("program_digest")
                else:
                    # Every instrumental purpose carries an exact-copy contract
                    # object under its own key; a draft bound to a superseded
                    # contract (gate reject -> retry-stage -> new approval)
                    # must be replaced, not kept for the binding validators to
                    # bounce. Only ablation had this; a redrafted probe or
                    # maintenance spec started from the rejected contract.
                    key = {"targeted_ablation": "ablation", "diagnostic_probe": "probe",
                           "maintenance": "maintenance"}.get(str(meta.get("experiment_purpose") or ""))
                    if key:
                        stale = existing.get(key) != meta.get(key)
            if stale:
                eutil.write_json_atomic(eutil.rpath(self.store.repo, f"{ldirp}/NODE_SPEC.json"), prefill)
            else:
                self._prefill_output(f"{ldirp}/NODE_SPEC.json", prefill)
            return self._present_task(self._create_task(
                "plan_node", {"round": lane["round"], "lane": lane["id"], "idea": lane["idea"]},
                [f"{ldirp}/NODE_SPEC.json"],
                extra_fields={"IDEA_ID": lane["idea"], "NODE_ROLE": econfig.INTENT_TO_ROLE[lane["intent"]],
                              "PARENTS": ", ".join(lane.get("parents", [])) or "(none)"},
                inputs=self._lane_common_inputs(lane) + [
                    (f".evo/ideas/{lane['idea']}.md", "the approved idea"),
                    (f".evo/ideas/{lane['idea']}.meta.json", "parents/level contract the spec must match"),
                    (".evo/nodes/" + self._baseline_id() + "/NODE_SPEC.json", "baseline spec as command reference")],
                extra_blocks=[("Infrastructure facts (submit/status/log commands; artifact URI template)",
                               einfra.infra_block(self.store, self.cfg)),
                              ("Shared artifacts (reuse duty: same stage_key must be consumed or waived)",
                               eartifact.artifacts_block(self.reg))],
                artifact_receipts=eartifact.artifacts_receipts(self.reg),
                lesson_parents=model_parents, lesson_tags=tags))
        if stg == "node_created":
            return None  # node pipeline drives; lane closes at conclude
        if stg not in econfig.LANE_STATUSES:
            raise SystemExit(f"[evo] lane {lane.get('id')} has unknown status {stg!r}; run 'evo doctor'. "
                             "The engine refuses to close a round with an unhandled lane state.")
        raise SystemExit(f"[evo] lane {lane.get('id')} status {stg!r} is legal but has no scheduler branch "
                         "(engine bug; run 'evo doctor').")

    def _baseline_id(self) -> str:
        base = next((n for n in self.g["nodes"] if n["role"] == "baseline"), None)
        return base["id"] if base else "N001"

    @staticmethod
    def _eval_metrics_path(node: dict) -> str:
        return str(node.get("eval_metrics_path") or f".evo/nodes/{node.get('id')}/eval/metrics.json")

    @staticmethod
    def _eval_report_path(node: dict) -> str:
        return str(node.get("eval_report_path") or f".evo/nodes/{node.get('id')}/eval/EVAL_REPORT.md")

    @staticmethod
    def _outcome_path(node: dict) -> str:
        return str(node.get("outcome_path") or f".evo/nodes/{node.get('id')}/OUTCOME.json")

    @staticmethod
    def _node_result_path(node: dict) -> str:
        return str(node.get("result_doc") or f".evo/nodes/{node.get('id')}/NODE_RESULT.md")

    def _node_inputs(self, node: dict, *, research_context: bool = True) -> list[tuple[str, str]]:
        """research_context=False (v11) is for LAUNCHER-class tasks: their card
        duties consume the spec, run identity and platform facts - the idea doc
        and registered predictions were dead weight re-read on every launch."""
        ins = [(node["spec"], "this node's spec (commands, workdir, stages, plan)")]
        if research_context and node.get("idea_doc"):
            ins.append((node["idea_doc"], "the idea being implemented"))
            ins.append((node["idea_doc"].replace(".md", ".meta.json"), "its registered predictions and assumptions"))
        cp = node.get("code_parent")
        if cp:
            cp_node = self.node(str(cp)) or {"id": cp}
            ins.append((self._node_result_path(cp_node), f"code parent {cp} result (if present)"))
        ins.append((".evo/profile/PROJECT_PROFILE.md", "project facts"))
        return ins

    def _next_node_task(self, node: dict, *, ignore_hold: bool = False) -> dict | None:
        """Return the node's current task, or None when the node cannot proceed
        right now (a workflow run is in flight elsewhere / no free slot)."""
        nid = node["id"]
        if not ignore_hold and erecover.is_held(
                self.st, self.g, node=nid, lane=node.get("lane"), round_=node.get("round")):
            return None
        parents = [p for p in node.get("parents", []) if (self.node(p) or {}).get("role") != "platform"]
        status = node["status"]
        if status == "approved" and node["role"] == "baseline":
            return self._present_task(self._create_task(
                "smoke", {"node": nid, "round": node.get("round")},
                [f".evo/nodes/{nid}/smoke/RESULTS.json"],
                extra_fields={"NODE": nid},
                inputs=self._node_inputs(node)))
        if status == "approved" or (status == "building" and node.get("fix_needed")):
            fixnote: list[tuple[str, list[str]]] = []
            if node.get("fix_needed"):
                self._begin_implementation_revision(
                    node, str(node.get("fix_note") or "implementation correction requested"))
                fixnote.append(("This is a FIX pass", [f"reason: {node.get('fix_note') or 'previous smoke/stage failed'}"]))
                if node.get("implementation_repair_scope") == "evaluation":
                    baseline = eutil.read_json(eutil.rpath(
                        self.store.repo, str(node.get("implementation_revision_baseline_path") or "")), {}) or {}
                    fixnote.append(("Evaluation-only repair boundary", [
                        "The completed workflow is provisionally preserved. Change only evaluator-owned files.",
                        "Add a '## Repair scope' section with exactly 'REPAIR_SCOPE: evaluation', one "
                        "'CHANGED_FILE: <path>' row for every manifest change, and one substantive "
                        "'WORKFLOW_REUSE_ARGUMENT: ...' line.",
                        "Workflow-protected files: " + (", ".join(
                            str(x) for x in (baseline.get("workflow_protected_paths") or [])) or "none declared"),
                        "If the real fix touches workflow behavior, declare 'REPAIR_SCOPE: workflow'. "
                        "That one-way widening will invalidate prior stage evidence and the later spend gate "
                        "will disclose a whole-workflow replay.",
                    ]))
                errs = ebundle.errors_block(self.store, self.cfg, node=nid, st=self.st)
                if errs:
                    fixnote.append(("Execution-error journal (yours first, then platform-wide; do not repeat these)", errs))
            cp = self.node(node.get("code_parent") or "") or {}
            base_ref = cp.get("commit") or cp.get("branch") or "(copy the code parent's workdir)"
            return self._present_task(self._create_task(
                "implement", {"node": nid, "round": node.get("round"), "lane": node.get("lane")},
                [f".evo/nodes/{nid}/BUILD_REPORT.md"],
                extra_fields={"NODE": nid, "WORKDIR": node.get("workdir") or "?",
                              "VCS_MODE": "git" if self._git_mode() else "copy",
                              "BRANCH": node.get("branch") or "(copy mode: no branch)",
                              "BASE_REF": str(base_ref)},
                inputs=self._node_inputs(node),
                extra_blocks=fixnote + [
                    ("Platform playbook (infrastructure fixes that worked here before)",
                     ebundle.playbook_block(self.store, self.cfg, self.st) or ["- none recorded yet"]),
                    ("How recent nodes wired their artifact I/O (READS/WRITES rows)",
                     ebundle.prior_wiring_block(self.store, self.g) or ["- no prior wiring rows"])],
                lesson_parents=parents, lesson_tags=["build"]))
        if status == "building":
            return self._present_task(self._create_task(
                "smoke", {"node": nid, "round": node.get("round"), "lane": node.get("lane")},
                [f".evo/nodes/{nid}/smoke/RESULTS.json"],
                extra_fields={"NODE": nid},
                inputs=self._node_inputs(node)))
        if status == "smoke_pass" and node.get("fidelity_pending"):
            return self._present_task(self._create_task(
                "fidelity", {"node": nid, "round": node.get("round"), "lane": node.get("lane")},
                [f".evo/nodes/{nid}/FIDELITY.md"],
                extra_fields={"NODE": nid, "WORKDIR": node.get("workdir") or "?"},
                inputs=self._node_inputs(node) + [
                    (f".evo/nodes/{nid}/BUILD_REPORT.md", "the builder's own map (audit it, do not trust it)")]))
        if status == "smoke_pass" and node.get("ablation_fidelity_pending"):
            return self._present_task(self._create_task(
                "ablation_fidelity", {"node": nid, "round": node.get("round"), "lane": node.get("lane")},
                [f".evo/nodes/{nid}/ABLATION_FIDELITY.md"],
                extra_fields={"NODE": nid, "WORKDIR": node.get("workdir") or "?"},
                inputs=self._node_inputs(node) + [
                    (f".evo/nodes/{nid}/BUILD_REPORT.md", "the builder's changed-file account; verify against code"),
                    (str(node.get("idea_doc") or "").replace(".md", ".meta.json"),
                     "the frozen changed factor and held-constant controls")]))
        if status == "smoke_pass" and node.get("needs_metric_bridge") and not node.get("metric_bridge_ready"):
            baseline = self.node(self._baseline_id()) or {"id": self._baseline_id()}
            return self._present_task(self._create_task(
                "metric_bridge", {"node": nid, "round": node.get("round"), "lane": node.get("lane")},
                [f".evo/nodes/{nid}/metric_bridge/ANCHOR.json"],
                extra_fields={"NODE": nid},
                inputs=self._node_inputs(node) + [(self._eval_metrics_path(baseline),
                                                   "baseline metrics the adapter must reproduce")]))
        if status in ("smoke_pass", "bridge_pass", "stage_ready"):
            spec = self._spec(node)
            stages = stages_of(spec)
            cur = int(node.get("stage_cursor") or 0)
            replica_index = int(node.get("replica_index") or 0)
            replica_total = econfig.workflow_replica_count(spec)
            replica_seed = econfig.workflow_seed(spec, replica_index)
            # R9-002: an approved repeat_measure re-enters the workflow as a
            # first-class engine lane with the fresh seed. The repeat lane has
            # no replica index (it is not a preplanned lane); its landings
            # resolve through the SAME rule as every attempt (R10-012).
            repeat_seed = self._repeat_run_pending(node)
            repeat_lane = repeat_seed is not None
            if repeat_lane:
                replica_seed = repeat_seed
                replica_index = None
            # R5 blind-operator audit: the empty-stages fast path used to sit
            # ABOVE the gate, so an evaluation-only instrumental node (stages
            # []) skipped the manual workflow gate the cards promise for ALL
            # instrumental compute. Gate first; the fast path runs after
            # approval (an approved gate falls through this block).
            if status != "stage_ready" and self._needs_workflow_gate(node):
                gate = self._workflow_gate(node)
                if gate is None:
                    cost = spec.get("cost_class")
                    gate = self.store.new_gate(
                        self.st, "workflow_approval",
                        {"node": nid, "contract_digest": str((node.get("spec_seal") or {}).get("digest") or "")},
                                               f"Node {nid} '{node.get('title')}' requests {cost} workflow execution "
                                               + (f"({len(stages)} stage(s)). " if stages else
                                                  "(evaluation-only: 0 stages; this gate covers its evaluation run). ")
                                               + f"Spec: {node['spec']}. "
                                               # R10-023: the reject arm's real terminal state was
                                               # never disclosed at the decision surface
                                               + "APPROVE starts the spend; REJECT permanently "
                                                 "abandons this node AND its lane (verdict=failed, "
                                                 "implementation work discarded) - there is no "
                                                 "'not now, later' arm on this gate.")
                if (gate.get("subject") or {}).get("contract_digest") != \
                        str((node.get("spec_seal") or {}).get("digest") or ""):
                    raise SystemExit(f"[evo] workflow gate {gate.get('id')} does not bind node {nid}'s sealed spec")
                if gate["status"] == "open":
                    if self._maybe_auto_resolve(gate):
                        return self._next_node_task(node, ignore_hold=ignore_hold)
                    return self._present_gate(gate)
                if gate["status"] == "rejected":
                    return {"kind": "waiting", "reason": f"workflow execution for {nid} rejected"}
                if gate["status"] != "approved":
                    return {"kind": "waiting", "reason": f"workflow gate {gate.get('id')} is {gate.get('status')}"}
            if not stages or cur >= len(stages):
                node["status"] = "workflow_done"
                egraph.touch(node)
                self.store.event("engine", "workflow_skipped", node=nid,
                                 reason="no workflow stages (evaluation-only or pre-existing anchor)" if not stages else "all stages done")
                return self._next_node_task(node, ignore_hold=ignore_hold)
            # v11.7: before the FIRST full-scale stage spend, one tiny real
            # pass over the entire workflow must have proven the chain for
            # exactly the code about to run (the receipt binds the
            # implementation seal; a fix pass re-seals and re-owes it). The
            # repeat lane re-runs an already-proven pipeline and is exempt.
            if not repeat_lane and erehearsal.required(self.cfg, node, spec) \
                    and erehearsal.record_errors(self.store, node):
                return self._present_task(self._create_task(
                    "rehearsal", {"node": nid, "round": node.get("round")},
                    [f".evo/nodes/{nid}/rehearsal/RECEIPT.json"],
                    extra_fields={"NODE": nid},
                    inputs=[(str(node.get("spec") or ""),
                             "the sealed spec incl. the top-level rehearsal plan"),
                            (".evo/config.json",
                             "result keys the tiny evaluation must emit")],
                    extra_blocks=[("Platform commands and conventions",
                                   einfra.infra_block(self.store, self.cfg)),
                                  ("Platform playbook (fixes that worked here)",
                                   ebundle.playbook_block(self.store, self.cfg, self.st)
                                   or ["- none recorded yet"]),
                                  ("Execution-error journal",
                                   ebundle.errors_block(self.store, self.cfg, node=nid, st=self.st)
                                   or ["- empty"])]))
            if self._slots_free() <= 0:
                return None  # defer: all workflow-stage slots busy
            stage = stages[cur]
            resolved_launch = str(econfig.resolve_seed_template(stage.get("launch") or "", replica_seed)) \
                if replica_seed is not None else str(stage.get("launch") or "")
            resolved_metrics = str(econfig.resolve_seed_template(stage.get("metrics_file") or "", replica_seed)) \
                if replica_seed is not None else str(stage.get("metrics_file") or "")
            resolved_ledger = str(econfig.resolve_seed_template(stage.get("ledger_file") or "", replica_seed)) \
                if replica_seed is not None and stage.get("ledger_file") else str(stage.get("ledger_file") or "")
            resolved_products = [
                {**p, "uri": str(econfig.resolve_seed_template(p.get("uri") or "", replica_seed))}
                if replica_seed is not None and isinstance(p, dict) else p
                for p in (stage.get("produces") or [])
            ]
            request = econfig.tracked_budget(stage.get("budget"), self.cfg)
            resource_gate = self._resource_gate(node, "stage", request,
                                                stage=str(stage.get("name") or "stage"),
                                                repeat=repeat_lane)
            if resource_gate is not None:
                return self._present_gate(resource_gate)
            repeat_decision = self._require_repeat_spend_decision(
                node, "stage", str(stage.get("name") or "stage"))
            if repeat_decision is not None:
                return repeat_decision
            stage_claims = self._landing_claims(
                node, "stage", stage=str(stage.get("name") or "stage"),
                replica_seed=replica_seed,
                declared_metrics_file=resolved_metrics,
                declared_ledger_file=resolved_ledger,
                repeat=repeat_lane)
            if self._landing_lease_holder(*stage_claims) is not None:
                # R9 landing lease + fix: defer exactly like a busy slot. The
                # holder RUN is non-terminal, so the scheduler's watch/wait
                # surface stays reachable and every other lane keeps moving;
                # crashing here (the old behavior) blocked ALL scheduling,
                # including the very watch card that settles the holder.
                return None
            run = self._prepare_run(
                node, "stage", request, stage=str(stage.get("name") or "stage"),
                stage_index=cur, replica_seed=replica_seed,
                replica_index=replica_index,
                replica_total=(None if repeat_lane else replica_total),
                resolved_launch=resolved_launch, declared_metrics_file=resolved_metrics,
                declared_ledger_file=resolved_ledger, repeat=repeat_lane)
            seed_suffix = (f"_seed-{econfig.seed_slug(replica_seed)}"
                           if replica_seed is not None and replica_total > 1 else "")
            launch_rel = (f".evo/nodes/{nid}/stages/"
                          f"LAUNCH_{eutil.slug(str(stage.get('name') or 'stage'), 24)}{seed_suffix}.json")
            launch_prefill = {"run": run["id"],
                              "attempt_token": str(run.get("attempt_token") or ""),
                              "stage": str(stage.get("name") or "stage")}
            if replica_seed is not None:
                launch_prefill["seed"] = replica_seed
            # Force-write: a relaunch prepares a NEW run at the same path, and
            # the RUN identity is engine-owned - a stale run/attempt_token here
            # would be a guaranteed LAUNCH_RUN rejection.
            launch_path = eutil.rpath(self.store.repo, launch_rel)
            launch_path.parent.mkdir(parents=True, exist_ok=True)
            eutil.write_json_atomic(launch_path, launch_prefill)
            task = self._create_task(
                "stage_launch", {"node": nid, "round": node.get("round"), "lane": node.get("lane"),
                                 "run": run["id"],
                                 "stage": str(stage.get("name") or "stage"),
                                 "ledger_required": econfig.stage_requires_ledger(stage),
                                 "replica_seed": replica_seed, "replica_index": replica_index,
                                 "replica_total": (None if repeat_lane else replica_total),
                                 # only the buy-back lane carries the marker -
                                 # ordinary subjects stay byte-identical to
                                 # every stored/pinned task row
                                 **({"repeat_measure": True} if repeat_lane else {})},
                [f".evo/nodes/{nid}/stages/LAUNCH_{eutil.slug(str(stage.get('name') or 'stage'), 24)}{seed_suffix}.json"],
                extra_fields={"NODE": nid, "STAGE": str(stage.get("name") or "stage"),
                              "STAGE_INDEX": str(cur + 1), "STAGE_TOTAL": str(len(stages)),
                              "REPLICA_SEED": str(replica_seed) if replica_seed is not None else "not-applicable",
                              "REPLICA_INDEX": ("repeat buy-back" if repeat_lane else str(replica_index + 1)),
                              "REPLICA_TOTAL": ("repeat buy-back" if repeat_lane else str(replica_total)),
                              "RESOLVED_LAUNCH": resolved_launch,
                              "RESOLVED_METRICS": resolved_metrics,
                              "RESOLVED_PRODUCTS": json.dumps(resolved_products, ensure_ascii=False),
                              "STAGE_CONTROL": str((stage.get("control") or {}).get("mode") or "?"),
                              "STAGE_MULTIPLICITY": str((stage.get("control") or {}).get("multiplicity") or "?"),
                               "STAGE_BUDGET": json.dumps(((stage.get("budget") or {}).get("limits") or {}), ensure_ascii=False),
                               "RUN_ID": run["id"], "ATTEMPT_TOKEN": str(run.get("attempt_token") or ""),
                               "LEDGER_REQUIREMENT": (f"required; report ledger_file (resolved: {resolved_ledger})"
                                                      if econfig.stage_requires_ledger(stage) else "optional")},
                inputs=self._node_inputs(node, research_context=False),
                extra_blocks=([(
                    "APPROVED repeat buy-back lane (engine-run; R9-002)", [
                        f"- This stage re-runs the workflow with the FRESH seed {replica_seed!r} bought "
                        "back at the approved repeat_measure gate. It is a first-class engine RUN: "
                        "attempt token, slot, landing lease and resource charge all apply.",
                        f"- Landings are the spec's OWN resolved paths (metrics_file={resolved_metrics!r}"
                        + (f", ledger_file={resolved_ledger!r}" if resolved_ledger else "")
                        + "): the frozen command writes exactly where it always writes. The first "
                        "attempt's leftover bytes there were archived when this RUN was prepared, and "
                        "its sealed evidence lives in immutable per-RUN snapshots - nothing you write "
                        "can reach it.",
                        "- The stage metrics JSON must record this seed in its 'seed' field.",
                        "- No mechanism-probe duty on this lane: probe authority stays with the "
                        "sealed base attempt."])] if repeat_lane else [])
                + [("Platform commands and conventions", einfra.infra_block(self.store, self.cfg)),
                   ("Platform playbook (infrastructure fixes that worked here before)",
                    ebundle.playbook_block(self.store, self.cfg, self.st) or ["- none recorded yet"]),
                   ("Execution-error journal (avoid repeating these)",
                    ebundle.errors_block(self.store, self.cfg, node=nid, st=self.st) or ["- empty"])])
            run["launch_task"] = task["id"]
            return self._present_task(task)
        if status in ("executing", "evaluating", "evidence_pending"):
            return None  # non-blocking: run in flight; absorbed when reported
        if status == "scientific_stop":
            stop = node.get("scientific_stop") or {}
            decision = stop.get("gate") or {}
            metrics_file = str(stop.get("metrics_file") or "")
            stop_inputs = self._node_inputs(node)
            if node.get("idea_doc"):
                stop_inputs.append((node["idea_doc"].replace(".md", ".meta.json"),
                                    "registered assumptions and predictions; predictions were not reached"))
            if metrics_file:
                stop_inputs.append((metrics_file, "stage evidence that triggered the pre-registered gate"))
            return self._present_task(self._create_task(
                "scientific_conclude", {"node": nid, "round": node.get("round"), "lane": node.get("lane")},
                [self._outcome_path(node), self._node_result_path(node)],
                extra_fields={"NODE": nid, "STAGE": str(stop.get("stage") or "?"),
                              "RUN_ID": str(stop.get("run") or "?"),
                              "GATE_ID": str(decision.get("id") or "?"),
                              "GATE_EVIDENCE": json.dumps(decision.get("predicates") or [], ensure_ascii=False),
                              "OUTCOME_PATH": self._outcome_path(node),
                              "RESULT_PATH": self._node_result_path(node)},
                inputs=stop_inputs, lesson_parents=parents,
                lesson_tags=["scientific-stop", str(decision.get("id") or "gate")]))
        if status == "workflow_done":
            if node["role"] == "platform":
                node["status"] = "evaluated"
                egraph.touch(node)
                self.store.event("engine", "eval_skipped", node=nid, reason="platform enablement is judged at conclude")
                return self._next_node_task(node, ignore_hold=ignore_hold)
            eval_request = {} if node.get("eval_resource_accounted") else \
                econfig.tracked_budget((self._spec(node).get("eval") or {}).get("budget"), self.cfg)
            if eval_request:
                resource_gate = self._resource_gate(node, "eval", eval_request)
                if resource_gate is not None:
                    return self._present_gate(resource_gate)
            # Every evaluator is a registered producer RUN. Quick evaluators
            # submit mode=completed; long evaluators submit mode=background.
            # In both cases raw bytes are ingested and sealed before analysis.
            # S4 (liveness audit): an evaluation-scope fix pass re-seals the
            # implementation WITHOUT re-walking the stages, so the node can
            # reach eval minting with a stale rehearsal receipt - the eval
            # validator refuses (REHEARSAL_STALE) and without this mint the
            # scheduler never presented the card that repairs the refusal.
            if not node.get("eval_done") and self._repeat_run_pending(node) is None \
                    and erehearsal.required(self.cfg, node, self._spec(node)) \
                    and erehearsal.record_errors(self.store, node):
                return self._present_task(self._create_task(
                    "rehearsal", {"node": nid, "round": node.get("round")},
                    [f".evo/nodes/{nid}/rehearsal/RECEIPT.json"],
                    extra_fields={"NODE": nid},
                    inputs=[(str(node.get("spec") or ""),
                             "the sealed spec incl. the top-level rehearsal plan"),
                            (".evo/config.json",
                             "result keys the tiny evaluation must emit")],
                    extra_blocks=[("Platform commands and conventions",
                                   einfra.infra_block(self.store, self.cfg)),
                                  ("Platform playbook (fixes that worked here)",
                                   ebundle.playbook_block(self.store, self.cfg, self.st)
                                   or ["- none recorded yet"]),
                                  ("Execution-error journal",
                                   ebundle.errors_block(self.store, self.cfg, node=nid, st=self.st)
                                   or ["- empty"])]))
            if not node.get("eval_done"):
                repeat_decision = self._require_repeat_spend_decision(node, "eval")
                if repeat_decision is not None:
                    return repeat_decision
                eval_launch = str((self._spec(node).get("eval") or {}).get("run") or "")
                eval_claims = self._landing_claims(
                    node, "eval", stage=None, replica_seed=None,
                    declared_metrics_file=f".evo/nodes/{nid}/eval/raw_metrics.json")
                if self._landing_lease_holder(*eval_claims) is not None:
                    return None  # defer: a live RUN still leases this eval landing
                run = self._prepare_run(
                    node, "eval", eval_request, resolved_launch=eval_launch,
                    declared_metrics_file=f".evo/nodes/{nid}/eval/raw_metrics.json")
                eval_launch_path = eutil.rpath(self.store.repo, f".evo/nodes/{nid}/eval/EVAL_LAUNCH.json")
                eval_launch_path.parent.mkdir(parents=True, exist_ok=True)
                eutil.write_json_atomic(eval_launch_path, {
                    "run": run["id"], "attempt_token": str(run.get("attempt_token") or "")})
                # R6 blind-operator audit: the launch card enumerated every raw
                # duty EXCEPT the probe envelope, whose only example lived in a
                # card the scheduler refuses to issue until the envelope
                # already exists (circular disclosure). Print it here.
                spec_probe = self._spec(node).get("probe_execution")
                if isinstance(spec_probe, dict):
                    probe_duty = (
                        "REGISTERED MECHANISM PROBE - the raw metrics JSON must ALSO carry "
                        "`_mechanism_probe` (absorption enforces it the instant a completed launch "
                        "is accepted): {\"mode\": " + json.dumps(str(spec_probe.get("mode") or ""))
                        + ", \"signal\": " + json.dumps(str(spec_probe.get("signal") or ""))
                        + ", \"expect\": " + json.dumps(str(spec_probe.get("expect") or ""))
                        + ", \"required_fields\": "
                        + json.dumps([str(x) for x in (spec_probe.get("required_fields") or [])])
                        + ", \"observations\": [{\"seed\": <this run's seed, or null when "
                          "not-applicable>, \"artifact\": \"<repo-relative frozen probe artifact>\", "
                          "\"values\": {<each required field: number>}}]} - one observation per "
                          "frozen probe artifact.")
                else:
                    probe_duty = "(no mechanism probe registered - omit `_mechanism_probe` entirely)"
                task = self._create_task(
                    "eval_launch", {"node": nid, "round": node.get("round"), "lane": node.get("lane"),
                                    "run": run["id"]},
                    [f".evo/nodes/{nid}/eval/EVAL_LAUNCH.json"],
                    extra_fields={"NODE": nid, "RUN_ID": run["id"],
                                  "ATTEMPT_TOKEN": str(run.get("attempt_token") or ""),
                                  "PROBE_DUTY": probe_duty},
                    inputs=self._node_inputs(node, research_context=False),
                    extra_blocks=[("Platform commands and conventions", einfra.infra_block(self.store, self.cfg)),
                                  ("Platform playbook (infrastructure fixes that worked here before)",
                                   ebundle.playbook_block(self.store, self.cfg, self.st) or ["- none recorded yet"]),
                                  ("Execution-error journal (avoid repeating these)",
                                   ebundle.errors_block(self.store, self.cfg, node=nid, st=self.st) or ["- empty"])])
                run["launch_task"] = task["id"]
                return self._present_task(task)
            rm_pending = self._require_repeat_measure_decision(node)
            if rm_pending is not None:
                return rm_pending
            repeat_seed = self._repeat_run_pending(node)
            if repeat_seed is not None:
                # R9-002: the approved repeat's workflow lanes are done (this
                # status is workflow_done) - now buy the repeat EVALUATION as
                # a first-class RUN. Charged again in full: the buy-back is a
                # second spend, and the resource doors still guard it.
                repeat_request = econfig.tracked_budget(
                    (self._spec(node).get("eval") or {}).get("budget"), self.cfg)
                if repeat_request:
                    resource_gate = self._resource_gate(node, "eval", repeat_request, repeat=True)
                    if resource_gate is not None:
                        return self._present_gate(resource_gate)
                repeat_decision = self._require_repeat_spend_decision(node, "eval")
                if repeat_decision is not None:
                    return repeat_decision
                eval_launch = str((self._spec(node).get("eval") or {}).get("run") or "")
                # R10-012: same declared landing as the base evaluation (one
                # resolution rule for every attempt); the base leftover bytes
                # are archived at prepare, its sealed copies are immutable
                repeat_metrics_rel = f".evo/nodes/{nid}/eval/raw_metrics.json"
                eval_claims = self._landing_claims(
                    node, "eval", stage=None, replica_seed=repeat_seed,
                    declared_metrics_file=repeat_metrics_rel, repeat=True)
                if self._landing_lease_holder(*eval_claims) is not None:
                    return None  # defer: the live repeat eval RUN holds this landing
                run = self._prepare_run(
                    node, "eval", repeat_request, replica_seed=repeat_seed,
                    resolved_launch=str(econfig.resolve_seed_template(eval_launch, repeat_seed)),
                    declared_metrics_file=repeat_metrics_rel, repeat=True)
                launch_rel = f".evo/nodes/{nid}/eval/EVAL_LAUNCH.json"
                launch_path = eutil.rpath(self.store.repo, launch_rel)
                launch_path.parent.mkdir(parents=True, exist_ok=True)
                eutil.write_json_atomic(launch_path, {
                    "run": run["id"], "attempt_token": str(run.get("attempt_token") or "")})
                task = self._create_task(
                    "eval_launch", {"node": nid, "round": node.get("round"), "lane": node.get("lane"),
                                    "run": run["id"], "repeat_measure": True},
                    [launch_rel],
                    extra_fields={"NODE": nid, "RUN_ID": run["id"],
                                  "ATTEMPT_TOKEN": str(run.get("attempt_token") or ""),
                                  "PROBE_DUTY": ("(repeat buy-back lane: no mechanism-probe duty - "
                                                 "probe authority stays with the sealed base "
                                                 "evaluation; omit `_mechanism_probe`)")},
                    inputs=self._node_inputs(node, research_context=False),
                    extra_blocks=[(
                        "APPROVED repeat buy-back EVALUATION (engine-run; R9-002)", [
                            f"- Evaluate the repeat-seed ({repeat_seed!r}) trained workflow exactly like "
                            "the base evaluation, as this prepared engine RUN.",
                            f"- The raw metrics land at {repeat_metrics_rel!r} - the evaluation's own "
                            "declared landing. The base attempt's leftover bytes there were archived "
                            "when this RUN was prepared; its sealed evidence lives in immutable "
                            "per-RUN snapshots and cannot be reached from here.",
                            "- Report the full raw metrics shape (every configured metric, _usage, "
                            "_resource_measurements) - the repeat is a real evaluation, only the "
                            "mechanism-probe envelope is waived."]),
                        ("Platform commands and conventions", einfra.infra_block(self.store, self.cfg)),
                        ("Platform playbook (infrastructure fixes that worked here before)",
                         ebundle.playbook_block(self.store, self.cfg, self.st) or ["- none recorded yet"]),
                        ("Execution-error journal (avoid repeating these)",
                         ebundle.errors_block(self.store, self.cfg, node=nid, st=self.st) or ["- empty"])])
                run["launch_task"] = task["id"]
                return self._present_task(task)
            stm = evalid.stage_metrics_of(self.ctx(), nid)
            ledgers = evalid.stage_ledgers_of(self.ctx(), nid)
            dyn_block = []
            for sname, nums in stm.items():
                dyn_block.append(f"- stage '{sname}': " + ", ".join(f"{k}={v:g}" for k, v in nums.items()))
            for sname, path in ledgers.items():
                dyn_block.append(f"- stage '{sname}' procedure ledger: {path}")
            ev_ins = []
            if node.get("eval_run"):
                run = self.store.get_run(self.st, node["eval_run"]) or {}
                if run.get("metrics_file"):
                    ev_ins.append((str(run["metrics_file"]),
                                   "the finished background eval run's metrics (copy/normalize into metrics.json)"))
            if node.get("idea_doc"):
                ev_ins.append((node["idea_doc"].replace(".md", ".meta.json"),
                               "the idea's registrations: mechanism_probe to MEASURE (Mechanism check "
                               "section), scaling points if pre-registered, dominance metric if claimed"))
            if not node.get("eval_run") or not node.get("eval_resource_accounted") or \
                    not node.get("resource_receipt_ready"):
                raise SystemExit(f"[evo] node {nid} reached analysis without a completed, accounted eval RUN "
                                 "and sealed engine resource receipt")
            task = self._create_task(
                "evaluate", {"node": nid, "round": node.get("round"), "lane": node.get("lane")},
                [self._eval_metrics_path(node), self._eval_report_path(node)],
                extra_fields={"NODE": nid, "EVAL_METRICS": self._eval_metrics_path(node),
                              "EVAL_REPORT": self._eval_report_path(node)},
                inputs=self._node_inputs(node) + ev_ins
                + [(str(node.get("resource_receipt_path")),
                    "engine-generated read-only resource receipt; do not edit or recreate")]
                + [(".evo/config.json", "metric spec keys metrics.json must contain"),
                   (".evo/profile/PROBLEM_DOSSIER.md", "invariants V# the comparability section must check")],
                extra_blocks=[("Stage evidence (engine-recorded; your Stage evidence section must "
                               "analyze summaries, usage and procedure ledgers)",
                               dyn_block or ["- none recorded (no executed workflow stages)"])]
                + self._repeat_measure_block(node))
            return self._present_task(self._reserve_task(task, eval_request))
        if status == "evaluated":
            # Engine-authored settlement copies (v10.1): the conclusion's
            # verdict/effect/mechanism/prediction verdicts are engine-computed
            # facts the validator asserts equal - the analyst interprets them
            # in prose but never chooses them, so the engine writes them.
            summary = node.get("evaluation_summary") or {}
            prefill = {}
            if node["role"] == "baseline":
                prefill["verdict"] = "baseline"
            elif node["role"] != "platform" and summary:
                prefill["verdict"] = summary.get("verdict")
                if node.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES:
                    prefill["effect_contract_status"] = summary.get("effect_contract_status")
                if node.get("experiment_purpose") == "maintenance":
                    prefill["maintenance_parity"] = evalid.maintenance_parity_status(summary)
                idea_meta = eutil.read_json(
                    eutil.rpath(self.store.repo, node["idea_doc"].replace(".md", ".meta.json")),
                    {}) if node.get("idea_doc") else {}
                idea_meta = idea_meta or {}
                metrics = eutil.read_json(
                    eutil.rpath(self.store.repo, self._eval_metrics_path(node)), {}) or {}
                preds = []
                rk_cell = {str((c or {}).get("result_key") or ""): str(cid)
                           for cid, c in econfig.cell_spec(self.cfg).items()}
                for p in idea_meta.get("predictions") or []:
                    # prefill with the SAME floored settlement the validator
                    # runs - a card showing a different verdict than submit
                    # accepts is the operability bug class
                    row = {"id": p.get("id"), "verdict": evalid.check_prediction(
                        p, metrics, floor=evalid._settlement_floor(
                            self.ctx(), node, rk_cell.get(str(p.get("metric") or ""), "")))}
                    observed = evalid.metric_value(metrics.get(str(p.get("metric") or "")))
                    if isinstance(observed, (int, float)):
                        row["observed"] = observed
                    preds.append(row)
                if preds:
                    prefill["predictions"] = preds
                probe = idea_meta.get("mechanism_probe") or {}
                if probe.get("signal") and not str(idea_meta.get("attribution_waiver") or "").strip():
                    prefill["mechanism"] = {
                        "status": str((summary.get("mechanism_contract") or {}).get("status") or "unclear"),
                        "evidence": self._eval_metrics_path(node)}
            if prefill:
                self._prefill_output(self._outcome_path(node), prefill)
            iid_inputs = []
            if node.get("idea_doc"):
                iid_inputs.append((node["idea_doc"].replace(".md", ".meta.json"), "registered predictions to verdict"))
            if econfig.sota_enabled(self.cfg):
                iid_inputs.append((".evo/evidence/SOTA.jsonl", "SOTA library - settle every registered sota_target"))
            return self._present_task(self._create_task(
                "conclude", {"node": nid, "round": node.get("round"), "lane": node.get("lane")},
                [self._outcome_path(node), self._node_result_path(node)],
                extra_fields={"NODE": nid, "NODE_ROLE": node["role"],
                              "EVAL_METRICS": self._eval_metrics_path(node),
                              "EVAL_REPORT": self._eval_report_path(node),
                              "OUTCOME_PATH": self._outcome_path(node),
                              "RESULT_PATH": self._node_result_path(node)},
                inputs=self._node_inputs(node) + iid_inputs + [
                    (self._eval_metrics_path(node), "observed metrics (if model node)"),
                    (self._eval_report_path(node), "evaluation detail (if model node)")],
                lesson_parents=parents, lesson_tags=["outcome"]))
        raise SystemExit(f"[evo] node {nid} in unexpected status {status}; run 'evo doctor'.")
