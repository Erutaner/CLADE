"""State store: .evo layout, state.json, graph.json, artifacts.json, events, lessons,
error journal, phenomenon ledger, id allocation (v10).

The engine is the ONLY writer of these files. Task roles write artifact files only.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import econfig
import erun
import eutil


class Store:
    def __init__(self, repo: Path):
        self.repo = repo.resolve()
        self.evo = self.repo / ".evo"
        self._recover_torn_generation()

    # ---- generation commit ---------------------------------------------------
    @property
    def _commit_marker_path(self) -> Path: return self.evo / "commit_pending.json"

    def _recover_torn_generation(self) -> None:
        """R7 external audit: save_all replaces graph -> artifacts -> state as
        separate atomic files. A crash between replaces left a MIXED
        generation ("new graph + old state") that the old comment called
        inert - but graph/registry bytes carry decision semantics (recovery
        scopes, repeat grants, probe caps, node status, AR rows), so retrying
        the interrupted command against the mixed world silently changed its
        meaning (scope widened, grants double-applied, ids re-used).
        save_all now stamps a pending-commit marker with pre-images BEFORE
        the first replace; this loader hook rolls a torn generation BACK to
        the consistent pre-transition snapshot (or clears debris when the
        state commit - the last, atomic replace - did land). Either way every
        surviving on-disk world is one the transition system can re-enter."""
        if not self._commit_marker_path.exists():
            return
        with eutil.exclusive_file_lock(
                self.evo / "state.lock",
                "[evo] another engine process holds the state lock while a torn "
                "commit needs recovery; retry this command"):
            self._recover_torn_generation_locked()

    def _recover_torn_generation_locked(self) -> None:
        """Recovery body; the caller MUST hold state.lock. Also invoked at the
        top of every _transactional_write: a long-lived process (the canary
        attach window is hours) constructed its Store before another process
        crashed mid-commit, so its later state-only save would otherwise bump
        state_revision onto an orphan marker's target and CONFIRM the torn
        generation while destroying the rollback pre-images."""
        marker_path = self._commit_marker_path
        if not marker_path.exists():
            return
        marker = eutil.read_json(marker_path, None)
        if not isinstance(marker, dict):
            marker_path.unlink(missing_ok=True)
            return
        st = eutil.read_json(self.state_path, None) or {}
        entries = [e for e in (marker.get("restore") or []) if isinstance(e, dict)]
        if st.get("state_revision") == marker.get("target_revision"):
            # the state commit landed: the generation is complete, the
            # pre-images are debris
            for e in entries:
                (self.evo / (str(e.get("name") or "?") + ".bak")).unlink(missing_ok=True)
        else:
            # the state commit never landed: the transition did not
            # happen - restore every replaced file so the command can be
            # retried with its original semantics
            for e in entries:
                name = str(e.get("name") or "")
                if not name:
                    continue
                bak, live = self.evo / (name + ".bak"), self.evo / name
                if bak.exists():
                    os.replace(bak, live)
                elif not e.get("had_bak", True):
                    live.unlink(missing_ok=True)
        marker_path.unlink(missing_ok=True)

    # ---- paths -------------------------------------------------------------
    @property
    def config_path(self) -> Path: return self.evo / "config.json"
    @property
    def state_path(self) -> Path: return self.evo / "state.json"
    @property
    def graph_path(self) -> Path: return self.evo / "graph.json"
    @property
    def artifacts_path(self) -> Path: return self.evo / "artifacts.json"
    @property
    def events_path(self) -> Path: return self.evo / "events.jsonl"
    @property
    def lessons_path(self) -> Path: return self.evo / "lessons.jsonl"
    @property
    def errors_path(self) -> Path: return self.evo / "errors.jsonl"
    @property
    def evidence_path(self) -> Path: return self.evo / "evidence" / "EVIDENCE.jsonl"
    @property
    def mech_path(self) -> Path: return self.evo / "evidence" / "MECH_CARDS.jsonl"
    @property
    def collision_path(self) -> Path: return self.evo / "evidence" / "COLLISION_AUDITS.jsonl"
    @property
    def observations_path(self) -> Path: return self.evo / "evidence" / "OBSERVATIONS.jsonl"

    def task_dir(self, tid: str) -> Path: return self.evo / "tasks" / tid
    def node_dir(self, nid: str) -> Path: return self.evo / "nodes" / nid
    def round_dir(self, rid: str) -> Path: return self.evo / "rounds" / rid
    def profile_dir(self) -> Path: return self.evo / "profile"
    def views_dir(self) -> Path: return self.evo / "views"

    def exists(self) -> bool:
        return self.state_path.exists()

    # ---- init ----------------------------------------------------------------
    def init(self, name: str, goal: str) -> None:
        if self.exists():
            raise SystemExit("[evo] .evo/state.json already exists; refusing to re-init. Use 'evo status'.")
        legacy = [p for p in ("SESSION_STATE.json", "PROCESS_CARD.md") if (self.evo / p).exists()]
        if legacy:
            raise SystemExit(f"[evo] {self.evo} looks like a legacy project ({legacy}); init v10 in a fresh repo.")
        for d in ("tasks", "nodes", "rounds", "evidence", "views", "profile", "ideas", "runs", "recoveries"):
            (self.evo / d).mkdir(parents=True, exist_ok=True)
        cfg = econfig.merged_default()
        cfg["project"]["name"] = name
        cfg["project"]["goal"] = goal
        eutil.write_json_atomic(self.config_path, cfg)
        eutil.write_text(self.evo / "ONBOARDING.md", _ONBOARDING)
        state = {
            "evo_version": "10",
            "state_revision": 0,
            "created_at": eutil.utc_now(),
            "phase": "bootstrap",          # bootstrap | rounds | done
            "current_round": None,
            "round_status": None,           # opening | running | closed
            "counters": {"N": 0, "L": 0, "I": 0, "T": 0, "G": 0, "R": 0, "RUN": 0, "LS": 0, "AR": 0,
                         "ER": 0, "OB": 0, "H": 0, "REC": 0},
            "bootstrap_done": [],           # ordered list of completed bootstrap task types
            "profile_digests": {},          # immutable bootstrap problem-model files
            "tasks": [],
            "lanes": [],
            "gates": [],
            "runs": [],
            "holds": [],                 # scoped stop-the-bleeding controls
            "recoveries": [],            # planned/applied causal corrections
            "knowledge_dispositions": [],# append-only LS/OB supersession index
            "resource_ledger": [],          # immutable charges by registered run/task
            "resource_overrides": {},       # user-approved additions after exhaustion gates
            "rounds": [],                   # closed active/performance frontier deltas + display trace
            "round_corrections": [],        # append-only overlays; closed snapshots stay immutable
            "config_frozen": False,
            "bootstrap_contract_confirmed": False,
            "bootstrap_contract_digest": None,
            "bootstrap_infra_facts_digest": None,
            # v11.7: an approved INFRA_FACTS revision whose fresh canary proof
            # is still owed; stage/eval launches refuse while it is pending.
            "infra_revision_pending": False,
            "bootstrap_terminated": False,
            "infra_canary": None,           # active passed engine-owned canary record
        }
        eutil.write_json_atomic(self.state_path, state)
        eutil.write_json_atomic(self.graph_path, {"version": "10", "nodes": []})
        eutil.write_json_atomic(self.artifacts_path, {"version": "10", "artifacts": []})
        # Candidate-specific prior-art edges are kept separate from reusable
        # paper facts.  The empty ledger is an explicit deep-read output even
        # before the first constructive program exists.
        eutil.write_text(self.collision_path, "")
        self.event("engine", "init", name=name, goal=goal)

    # ---- state ---------------------------------------------------------------
    def load_state(self) -> dict:
        st = eutil.read_json(self.state_path)
        if st is None:
            raise SystemExit("[evo] no .evo/state.json here. Run 'evo init' first (see README).")
        if st.get("evo_version") != "10":
            raise SystemExit("[evo] state.json is not evo_version 10. Use an explicit migration; v10 never silently reinterprets v9.x state.")
        return st

    def save_state(self, st: dict) -> None:
        self._transactional_write(st)

    def save_all(self, st: dict, g: dict, reg: dict) -> None:
        """Write state+graph+artifacts as ONE optimistic transaction.

        v9.2 revision-guarded only state.json; graph/artifact writes could
        interleave with another process's stale copies. The state revision now
        guards all three files: they change together or not at all (within the
        atomic-per-file guarantee; a crash between files is repaired by doctor
        against the authoritative state)."""
        self._transactional_write(st, extra=((self.graph_path, g), (self.artifacts_path, reg)))

    def _transactional_write(self, st: dict, extra: tuple = ()) -> None:
        expected = st.get("state_revision")
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise SystemExit("[evo] state has no valid revision; refusing a non-transactional write")
        with eutil.exclusive_file_lock(
                self.evo / "state.lock",
                "[evo] another engine process is writing state; retry this command"):
            # A crashed sibling's pending commit must be resolved BEFORE the
            # revision check: otherwise a state-only save could land exactly
            # on the orphan marker's target revision and certify the torn
            # generation (deleting its rollback pre-images), and a full save
            # would overwrite the marker outright.
            self._recover_torn_generation_locked()
            current = eutil.read_json(self.state_path)
            actual = (current or {}).get("state_revision")
            if actual != expected:
                raise SystemExit("[evo] state changed concurrently; no stale state was written. "
                                 "Reload and retry the command.")
            st["state_revision"] = expected + 1
            # R7 external audit: graph/artifacts BEFORE state; state.json (the
            # last, atomic replace) is the commit point. R7 follow-up: "new
            # graph + old state" is NOT inert - graph bytes carry decision
            # semantics - so every replaced file is pre-imaged and a
            # pending-commit marker is stamped first; a crash between the
            # replaces is rolled BACK at the next load (see
            # _recover_torn_generation) instead of leaving a mixed world.
            writes = []
            for path, data in extra:
                # v11: graph/artifacts frequently did not change in this
                # transition (every plain reject, run-bind, gate decision,
                # hold/resume). An identical-bytes skip is observationally
                # equivalent for every reader - no engine reader consumes file
                # mtimes, the revision guard lives in always-written state.json,
                # and skippable bytes grow linearly with project size (the
                # rewrite was O(N^2) cumulative SSD writes over a project).
                payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
                try:
                    if path.exists() and path.read_text(encoding="utf-8") == payload:
                        continue
                except (OSError, UnicodeDecodeError, ValueError):
                    pass  # unreadable/foreign bytes -> just write; never crash the transaction
                writes.append((path, data))
            if writes:
                restore = []
                for path, _data in writes:
                    had = path.exists()
                    if had:
                        shutil.copy2(path, path.with_name(path.name + ".bak"))
                    restore.append({"name": path.name, "had_bak": had})
                eutil.write_json_atomic(self._commit_marker_path,
                                        {"target_revision": expected + 1, "restore": restore})
            for path, data in writes:
                eutil.write_json_atomic(path, data)
            eutil.write_json_atomic(self.state_path, st)
            if writes:
                self._commit_marker_path.unlink(missing_ok=True)
                for path, _data in writes:
                    path.with_name(path.name + ".bak").unlink(missing_ok=True)

    def load_config(self) -> dict:
        cfg = eutil.read_json(self.config_path)
        if cfg is None:
            raise SystemExit("[evo] missing .evo/config.json. Run 'evo init'.")
        econfig.apply_preset(cfg)   # named preset owns the tempo keys (in-memory)
        return cfg

    def load_graph(self) -> dict:
        g = eutil.read_json(self.graph_path, {"version": "10", "nodes": []})
        if g.get("version") != "10":
            raise SystemExit("[evo] graph.json is not version 10.")
        return g

    def save_graph(self, g: dict) -> None:
        eutil.write_json_atomic(self.graph_path, g)

    def load_artifacts(self) -> dict:
        reg = eutil.read_json(self.artifacts_path, {"version": "10", "artifacts": []})
        if reg.get("version") != "10":
            raise SystemExit("[evo] artifacts.json is not version 10.")
        return reg

    def save_artifacts(self, reg: dict) -> None:
        eutil.write_json_atomic(self.artifacts_path, reg)

    # ---- events / lessons / errors ---------------------------------------------
    def event(self, actor: str, event: str, **data: Any) -> None:
        eutil.append_jsonl(self.events_path, {"ts": eutil.utc_now(), "actor": actor, "event": event, **data})

    def events(self) -> list[dict]:
        return eutil.read_jsonl(self.events_path)

    @staticmethod
    def knowledge_dispositions(st: dict | None) -> dict[str, dict]:
        """Latest append-ordered disposition per LS/OB ref (single source)."""
        out: dict[str, dict] = {}
        for row in (st or {}).get("knowledge_dispositions") or []:
            if isinstance(row, dict) and str(row.get("ref") or "").strip():
                out[str(row["ref"]).strip()] = row
        return out

    @classmethod
    def knowledge_is_active(cls, st: dict | None, ref: str) -> bool:
        """One activity predicate for all consumers (v9.2 had four drifted
        copies with two incompatible semantics)."""
        row = cls.knowledge_dispositions(st).get(str(ref or "").strip())
        return str((row or {}).get("status") or "active") not in ("superseded", "retracted")

    @staticmethod
    def _committed_journal_rows(st: dict | None, rows: list[dict], prefix: str) -> list[dict]:
        """R9 (external audit r6): rows whose numeric id exceeds the committed
        state counter are crash ghosts (their transition's state save never
        landed). The next same-id allocation quarantines them; readers that
        hold a state must not treat them as authority meanwhile."""
        if not isinstance(st, dict) or not (st.get("counters") or {}):
            return rows
        try:
            limit = int((st.get("counters") or {}).get(prefix, 0))
        except (TypeError, ValueError):
            return rows
        out = []
        for r in rows:
            rid = str(r.get("id") or "")
            tail = rid[len(prefix):] if rid.startswith(prefix) else ""
            if tail.isdigit() and int(tail) > limit:
                continue
            out.append(r)
        return out

    def lessons(self, st: dict | None = None, *, active_only: bool = False) -> list[dict]:
        rows = self._committed_journal_rows(st, eutil.read_jsonl(self.lessons_path), "LS")
        if not active_only:
            return rows
        # Build the dispositions index ONCE per call, not once per row: the
        # per-row rebuild was O(rows x dispositions) on every bundle build.
        disp = self.knowledge_dispositions(st)
        return [r for r in rows
                if str((disp.get(str(r.get("id") or "")) or {}).get("status") or "active")
                not in ("superseded", "retracted")]

    def _quarantine_ghost_rows(self, path, new_id: str) -> None:
        """R8 (external audit r5): allocate-then-append journals leave a ghost
        row when the process dies between the append and the state commit -
        the committed counter then re-allocates the same id and the ghost
        aliases the real row for every reader. The caller's state counter is
        the commit authority: any EXISTING row carrying the id being
        allocated right now is by definition uncommitted debris from a
        crashed attempt. Quarantine it (and any unparseable raw lines) to
        ``<file>.quarantine`` before appending the committed replacement."""
        rows, bad = eutil.scan_jsonl(path)
        ghosts = [r for r in rows if str(r.get("id") or "") == new_id]
        if not ghosts and not bad:
            return
        qpath = path.with_name(path.name + ".quarantine")
        with qpath.open("a", encoding="utf-8", newline="\n") as fh:
            for r in ghosts:
                fh.write(json.dumps({"quarantined_at": eutil.utc_now(),
                                     "reason": f"uncommitted ghost ({new_id} re-allocated after a crash)",
                                     "row": r}, ensure_ascii=False) + "\n")
            for line_no, raw in bad:
                fh.write(json.dumps({"quarantined_at": eutil.utc_now(),
                                     "reason": f"unparseable line {line_no} (torn append)",
                                     "raw": raw}, ensure_ascii=False) + "\n")
        kept = [r for r in rows if str(r.get("id") or "") != new_id]
        payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in kept)
        # R9: atomic replace - a crash inside a plain truncate+write here
        # destroyed every committed row this cleanup meant to KEEP.
        eutil.write_text_atomic(path, payload)
        self.event("engine", "journal_ghost_quarantined", journal=path.name, id=new_id,
                   ghosts=len(ghosts), torn_lines=len(bad))

    def add_lesson(self, st: dict, rec: dict) -> str:
        """Allocate the LS id from the CALLER's state dict - loading a fresh copy
        here would be overwritten when the caller saves its own state (lost update)."""
        lid = self.next_id(st, "LS")
        self._quarantine_ghost_rows(self.lessons_path, lid)
        rec = {"id": lid, "ts": eutil.utc_now(), **rec}
        eutil.append_jsonl(self.lessons_path, rec)
        return lid

    def observations(self, st: dict | None = None, *, active_only: bool = False) -> list[dict]:
        rows = self._committed_journal_rows(st, eutil.read_jsonl(self.observations_path), "OB")
        if not active_only:
            return rows
        disp = self.knowledge_dispositions(st)
        return [r for r in rows
                if str((disp.get(str(r.get("id") or "")) or {}).get("status") or "active")
                not in ("superseded", "retracted")]

    def add_observation(self, st: dict, rec: dict) -> str:
        """The phenomenon ledger (v9): quantitative anomalies mined from OUR OWN
        runs (loss spikes, slice-level failures, dynamics oddities, eval quirks).
        Oral-tier method work is overwhelmingly phenomenon-first - the ledger is
        the engine's supply line from execution back into ideation: sketches may
        anchor their diagnosis on an OB## and ideas may cite one as an assumption
        source. Same lost-update rule as add_lesson: ids from the caller's state."""
        oid = self.next_id(st, "OB")
        self._quarantine_ghost_rows(self.observations_path, oid)
        rec = {"id": oid, "ts": eutil.utc_now(), **rec}
        eutil.append_jsonl(self.observations_path, rec)
        return oid

    def errors(self, st: dict | None = None) -> list[dict]:
        # The engine is the only in-process writer; every writer below
        # invalidates. Re-reading the whole journal per accessor call was
        # O(errors) per call and the conclude path called it in a loop.
        cached = getattr(self, "_errors_cache", None)
        if cached is None:
            cached = eutil.read_jsonl(self.errors_path)
            self._errors_cache = cached
        # Same crash-ghost rule as lessons/observations (the three journals
        # share the allocate-then-append shape): callers holding a state pass
        # it and see only committed ER rows; the doctor keeps calling without
        # st on purpose - its duplicate-id audit must SEE the ghosts.
        return self._committed_journal_rows(st, list(cached), "ER")

    def error_records(self, st: dict | None = None) -> list[dict]:
        """ER failure rows only (resolution rows filtered out)."""
        # R9 (external audit r6): only real FAILURE rows. Recovery writes
        # kind="resolution_retraction" control rows with no id/stage/run/note;
        # they used to pass this filter and surface as "[None] ... no note
        # recorded" pseudo-errors in bundles while doctor reported them as
        # duplicate empty ids. Dispositions are folded by error_resolutions().
        return [r for r in self.errors(st)
                if str(r.get("kind") or "") not in ("resolution", "resolution_retraction")]

    def error_resolutions(self, st: dict | None = None) -> list[dict]:
        """Engine-appended dispositions for infra-classed failures: the half
        of the journal that carries the PLAYBOOK (what fixed it), routed into
        execution-bearing bundles by surface rather than by lineage.

        A ``resolution_retraction`` row voids every EARLIER resolution row of
        its node (recovery invalidated the conclusion those dispositions were
        validated against); rows appended after the retraction - the
        re-conclusion's fresh dispositions - stay live. Without this, a stale
        "transient" proof survived the recovery of its own evidence and the
        conclude-side surplus check then FORBADE re-dispositioning it."""
        retract_at: dict[object, int] = {}
        rows: list[tuple[int, dict]] = []
        seen_keys: set[str] = set()
        for i, r in enumerate(self.errors(st)):
            kind = r.get("kind")
            if kind == "resolution":
                # R11 interruption audit: two overlapping processes can both
                # append the same staged outbox row (the key rides the state
                # commit; the appends do not). One logical disposition is one
                # row to every reader, however many times it landed.
                key = str(r.get("outbox_key") or "")
                if key:
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                rows.append((i, r))
            elif kind == "resolution_retraction":
                retract_at[r.get("node")] = i
        return [r for i, r in rows if i > retract_at.get(r.get("node"), -1)]

    def retract_error_resolutions(self, node_id: str, *, recovery: str, reason: str) -> None:
        """Void a node's resolution rows after a recovery invalidates its
        conclusion. Callers stage this through the engine's save() buffer,
        which flushes retractions BEFORE the state commit: a retraction
        UN-suppresses knowledge duties, so surviving a half-committed
        transition fails closed - the worst case is conclude asking for a
        disposition again (and doctor's RESOLUTION_RETRACTION_MISSING covers
        the reverse gap left by pre-fix states)."""
        eutil.append_jsonl(self.errors_path, {
            "kind": "resolution_retraction", "ts": eutil.utc_now(),
            "node": str(node_id), "recovery": str(recovery), "reason": str(reason)})
        self._errors_cache = None

    def add_error_resolution(self, rec: dict) -> None:
        """Append one disposition row linked to an ER failure. Engine-owned:
        the agent declares it in OUTCOME.infra_resolutions and conclude-accept
        writes it here after validation.

        Callers inside a transition must stage this through
        ``Engine._stage_error_resolution`` instead, so a row that SUPPRESSES a
        knowledge duty can never outlive an aborted transition."""
        eutil.append_jsonl(self.errors_path, {"kind": "resolution", "ts": eutil.utc_now(), **rec})
        self._errors_cache = None

    def add_error(self, st: dict, rec: dict) -> str:
        """Structured execution-error journal (workflow/evaluation failures). Same
        lost-update rule as add_lesson: ids come from the caller's state dict."""
        eid = self.next_id(st, "ER")
        self._quarantine_ghost_rows(self.errors_path, eid)
        rec = {"id": eid, "ts": eutil.utc_now(), **rec}
        eutil.append_jsonl(self.errors_path, rec)
        self._errors_cache = None
        return eid

    def evidence(self) -> list[dict]:
        return eutil.read_jsonl(self.evidence_path)

    def mech_cards(self) -> list[dict]:
        return eutil.read_jsonl(self.mech_path)

    def collision_audits(self) -> list[dict]:
        return eutil.read_jsonl(self.collision_path)

    # ---- ids -------------------------------------------------------------------
    def next_id(self, st: dict, kind: str) -> str:
        n = int(st["counters"].get(kind, 0)) + 1
        st["counters"][kind] = n
        return eutil.fmt_id(kind, n, eutil.ID_WIDTHS[kind])

    # ---- lookups -----------------------------------------------------------------
    @staticmethod
    def find(items: list[dict], id_: str) -> dict | None:
        for it in items:
            if it.get("id") == id_:
                return it
        return None

    def get_task(self, st: dict, tid: str) -> dict | None:
        return self.find(st["tasks"], tid)

    def get_lane(self, st: dict, lid: str) -> dict | None:
        return self.find(st["lanes"], lid)

    def get_gate(self, st: dict, gid: str) -> dict | None:
        return self.find(st["gates"], gid)

    def get_run(self, st: dict, rid: str) -> dict | None:
        return self.find(st["runs"], rid)

    def open_tasks(self, st: dict) -> list[dict]:
        return [t for t in st["tasks"] if t.get("status") == "open"]

    def open_gates(self, st: dict) -> list[dict]:
        return [g for g in st["gates"] if g.get("status") == "open"]

    def running_runs(self, st: dict) -> list[dict]:
        # Prepared is an unspent local intent, not an external job to watch.
        return [r for r in st.get("runs", []) if erun.holds_external_slot(r)]

    def new_task(self, st: dict, type_: str, subject: dict, outputs: list[str]) -> dict:
        tid = self.next_id(st, "T")
        task = {
            "id": tid, "type": type_, "status": "open", "subject": subject,
            "attempts": 0, "outputs": outputs, "created_at": eutil.utc_now(),
            "updated_at": eutil.utc_now(), "last_errors": [],
        }
        st["tasks"].append(task)
        self.event("engine", "task_created", task=tid, type=type_, subject=subject)
        return task

    def new_gate(self, st: dict, kind: str, subject: dict, summary: str) -> dict:
        if kind not in econfig.GATE_KINDS:
            raise ValueError(f"unknown gate kind {kind!r}; GATE_KINDS is the fail-closed registry")
        gid = self.next_id(st, "G")
        gate = {
            "id": gid, "kind": kind, "status": "open", "subject": subject,
            "summary": summary, "decision_note": None, "round": st.get("current_round"),
            "created_at": eutil.utc_now(), "decided_at": None,
        }
        st["gates"].append(gate)
        self.event("engine", "gate_created", gate=gid, kind=kind, subject=subject)
        return gate

    def new_run(self, st: dict, node: str, kind: str, job: str | None = None, stage: str | None = None,
                 *, replica_seed: Any | None = None, replica_index: int | None = None,
                 replica_total: int | None = None, stage_index: int | None = None,
                 prepared: bool = True, contract_digest: str,
                 implementation_digest: str = "", attempt_token: str | None = None) -> dict:
        """Allocate a durable attempt before its external side effect.

        ``prepared=False`` remains useful for engine-observed synchronous
        producers, but even those receive their identity before the execution
        transition.  Agent-launched work always uses the default prepared
        state and binds the platform job later through ``run-bind``.
        """
        if not str(contract_digest or "").strip():
            raise ValueError("v10 RUNs require a non-empty executable contract digest")
        rid = self.next_id(st, "RUN")
        run = {
            "id": rid, "node": node, "kind": kind, "stage": stage,
            "status": "prepared", "job": None,
            "contract_digest": contract_digest, "implementation_digest": implementation_digest,
            "attempt_token": attempt_token,
            "replica_seed": replica_seed, "replica_index": replica_index,
            "replica_total": replica_total, "stage_index": stage_index,
            "metrics_file": None, "ledger_file": None, "note": None,
            "scientific_outcome": None, "scientific_gate": None,
            "absorbed": False,
            "resource_reservation": {}, "resource_usage": {},
            "resource_charge_basis": None, "resource_accounted": False,
        }
        erun.initialize_run(run, existing_runs=st.get("runs", ()), token=attempt_token)
        if not prepared:
            erun.transition_execution(run, "running", job=job)
        st["runs"].append(run)
        self.event("engine", "run_prepared" if prepared else "run_registered",
                   run=rid, node=node, kind=kind, stage=stage, job=job,
                   replica_seed=replica_seed, replica_index=replica_index,
                   replica_total=replica_total, stage_index=stage_index)
        return run


# Written to .evo/ONBOARDING.md at init: the checklist of what the USER must
# supply for the engine to start well. The project_scan card walks the user
# through it - users otherwise do not know what to provide.
_ONBOARDING = """\
# What this engine needs from you (onboarding checklist)

The evolution engine learns your project before touching it, but it can only
learn from what you provide. The first project-scan task asks for these paths,
reads them with the relevant code, and drafts questions before configuration:

## 1. Knowledge base (`project.docs`) - the highest-leverage item
Paths (files or folders) documenting:
- **Training platform**: how jobs are submitted, watched, cancelled; queue
  quotas (how many jobs may run at once); where logs live.
- **Data**: where each dataset lives (URIs/tables/paths), what each split is
  for, whether eval splits are frozen.
- **Checkpoints / artifact store**: where weights are saved, the path
  convention, what happens when two runs share a path.
- **Evaluation contract**: every dataset/task pair, the exact metric definitions
  and protocols, which cells are targets/guardrails/diagnostics, meaningful
  improvement and non-inferiority margins, and whether one checkpoint or
  task-specific adaptations are being judged.  If you do not know a choice,
  say so: the interview records an explicit revisitable assumption.
- For LLM-flavored projects also: serving/inference endpoints, API quotas and
  budget, base-model weights locations, prompt/eval harness docs.

## 2. Decisions the interview will ask for
- **Mode**: `engineering` (goal: metric gains; borrowing well-fitting published
  methods is legitimate) or `research` (goal: gains + novelty; new ideas must
  differ from the literature; formal-derivation and SOTA duties activate).
- **Readiness**: the scan asks whether your project ALREADY runs end-to-end
  here (certified) or needs preparation first. If it needs preparation, a
  provision pass is authorized to do constructive work - fetch/wire data,
  build a minimal evaluation, fix bugs - until a first real number exists;
  every choice it makes is listed for your sign-off before the contract
  freezes, and it comes back with a concrete list if something you provided
  is missing.
- **Rehearsal**: `full_chain` (before each node's first full-scale run, one tiny
  real pass over the whole workflow on the real platform proves every stage
  AND that each produced artifact is readable by its consumer) or `none`
  (you explicitly waive it). Choose `full_chain` on any remote/costly platform.
- **Decision criteria**: there may be several target metrics. Choose a display
  metric for compact views, but success is claim-scoped and Pareto-aware.
- **Project resource envelope**: hard totals across the whole evolution (for
  example GPU-hours, training/API tokens or wall-clock minutes), rounds to run,
  and how many concurrent stage jobs the platform allows. Every stage/eval is
  reserved and charged against these totals; increasing one always asks you.
- **Temperament**: steady | balanced | frontier (one word; owns all pacing).
- **Supervision**: gated | auto | full_auto. The initial success/resource
  contract always requires your approval before automation starts. With full_auto, a blocked
  provision pass STOPS the run - an unattended run cannot supply missing resources).
  Changeable at ANY point later via `evo autonomy <mode> --note "why"` - e.g.
  approve the first rounds yourself, then hand the wheel over.
- Optional **focus directions**: topics you want a share of lanes to explore
  (e.g. "try reinforcement learning on this task"). Never more than half of a
  round is spent on them.
- Research mode optional: enable the **SOTA library** (the engine will retrieve
  recent top-venue work on your task and bind new ideas to beat named entries).
- **Workflow and evidence policy**: a stage is a finite handoff/recovery/resource
  boundary with explicit caps. Algorithm-intrinsic search/multiple models may
  stay inside one preregistered stage. The project scan recommends, and you
  approve before automation, whether training uses one recorded seed or an
  exact preplanned repeat set. Ablation is separately off or limited to one
  manually approved, decision-changing child run; it is never triggered by
  every gain and never multiplied by seed count. Cheap mechanism probes add no
  training. Scaling is off/reuse-only/budgeted/full, never a global tax hidden
  inside every L4 node.

## 3. What happens next (so you know the engine is working)
project scan -> configure -> infra scan -> success/resource interview (you approve) -> one engine-run
integrated infrastructure canary (tiny real data/compute/store/eval path) -> project profile -> problem
dossier -> innovation rubric -> baseline -> evolution rounds.

Keep `.evo/views/DASHBOARD.html` open in a browser: it is your live view.
"""
