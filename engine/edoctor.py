"""Cross-file consistency checks and safe repairs (v8)."""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path

import eartifact
import ecanary
import econfig
import egraph
import eprogram
import erecover
import erun
import eseal
import eutil
import evalid
import evcs


def _scope_error(scope, st: Mapping, g: Mapping) -> str | None:
    """Return why a hold/recovery scope cannot identify engine state."""
    try:
        normalized = erecover.normalize_scope(scope)
        if normalized["kind"] == "round":
            rid = normalized["id"]
            known_rounds = {str(row.get("id")) for row in st.get("rounds") or []
                            if isinstance(row, Mapping) and str(row.get("id") or "")}
            if st.get("current_round"):
                known_rounds.add(str(st["current_round"]))
            known_rounds.update(str(row.get("round")) for row in st.get("lanes") or []
                                if isinstance(row, Mapping) and str(row.get("round") or ""))
            known_rounds.update(str(row.get("round")) for row in g.get("nodes") or []
                                if isinstance(row, Mapping) and str(row.get("round") or ""))
            if rid not in known_rounds:
                return f"unknown round {rid}"
        erecover.scope_members(normalized, st, g)
    except (TypeError, ValueError) as exc:
        return str(exc)
    return None


def _recovery_control_errors(store, st: Mapping, g: Mapping) -> list[str]:
    """Audit recovery control records and frozen plans without changing them."""
    problems: list[str] = []

    holds = st.get("holds")
    if not isinstance(holds, list):
        problems.append("HOLD_COLLECTION: state.holds must be a list")
        holds = []
    seen_holds: set[str] = set()
    for index, hold in enumerate(holds):
        if not isinstance(hold, Mapping):
            problems.append(f"HOLD_RECORD: holds[{index}] must be an object")
            continue
        hid_value = hold.get("id")
        hid = hid_value.strip() if isinstance(hid_value, str) else ""
        label = hid or f"holds[{index}]"
        if not hid:
            problems.append(f"HOLD_ID: {label} needs a non-empty string id")
        elif hid in seen_holds:
            problems.append(f"HOLD_DUP_ID: duplicate hold id {hid}")
        else:
            seen_holds.add(hid)
        if not isinstance(hold.get("status"), str) or not hold["status"].strip():
            problems.append(f"HOLD_STATUS: {label} needs a non-empty string status")
        scope_problem = _scope_error(hold.get("scope"), st, g)
        if scope_problem:
            problems.append(f"HOLD_SCOPE: {label} {scope_problem}")

    recoveries = st.get("recoveries")
    if not isinstance(recoveries, list):
        problems.append("RECOVERY_COLLECTION: state.recoveries must be a list")
        recoveries = []
    seen_recoveries: set[str] = set()
    repo = Path(store.repo).resolve()
    for index, recovery in enumerate(recoveries):
        if not isinstance(recovery, Mapping):
            problems.append(f"RECOVERY_RECORD: recoveries[{index}] must be an object")
            continue
        rec_value = recovery.get("id")
        rec_id = rec_value.strip() if isinstance(rec_value, str) else ""
        label = rec_id or f"recoveries[{index}]"
        if not rec_id:
            problems.append(f"RECOVERY_ID: {label} needs a non-empty string id")
        elif rec_id in seen_recoveries:
            problems.append(f"RECOVERY_DUP_ID: duplicate recovery id {rec_id}")
        else:
            seen_recoveries.add(rec_id)
        if not isinstance(recovery.get("status"), str) or not recovery["status"].strip():
            problems.append(f"RECOVERY_STATUS: {label} needs a non-empty string status")
        if not isinstance(recovery.get("target"), str) or not recovery["target"].strip():
            problems.append(f"RECOVERY_TARGET: {label} needs a non-empty string target")
        scope_problem = _scope_error(recovery.get("scope"), st, g)
        if scope_problem:
            problems.append(f"RECOVERY_SCOPE: {label} {scope_problem}")

        raw_path = recovery.get("plan_path")
        raw_digest = recovery.get("plan_digest")
        plan_path = raw_path.strip() if isinstance(raw_path, str) else ""
        recorded_digest = raw_digest.strip() if isinstance(raw_digest, str) else ""
        if not plan_path or not recorded_digest:
            problems.append(
                f"RECOVERY_PLAN_BINDING: {label} needs both plan_path and plan_digest")
            continue
        relative = Path(plan_path)
        if relative.is_absolute():
            problems.append(f"RECOVERY_PLAN_PATH: {label} plan_path must be repository-relative")
            continue
        candidate = (repo / relative).resolve(strict=False)
        try:
            candidate.relative_to(repo)
        except ValueError:
            problems.append(f"RECOVERY_PLAN_PATH: {label} plan_path escapes the repository")
            continue
        if not candidate.is_file():
            problems.append(f"RECOVERY_PLAN_MISSING: {label} plan file {plan_path!r} is missing")
            continue
        try:
            plan = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            problems.append(f"RECOVERY_PLAN_JSON: {label} cannot read {plan_path!r}: {exc}")
            continue
        if not isinstance(plan, Mapping):
            problems.append(f"RECOVERY_PLAN_SHAPE: {label} plan must be a JSON object")
            continue
        try:
            actual_digest = erecover.plan_digest(plan)
        except (TypeError, ValueError) as exc:
            problems.append(f"RECOVERY_PLAN_SHAPE: {label} plan is not canonicalizable: {exc}")
            continue
        if actual_digest != recorded_digest:
            problems.append(
                f"RECOVERY_PLAN_DIGEST: {label} plan digest is {actual_digest}, "
                f"state records {recorded_digest}")
        embedded = plan.get("plan_digest")
        if embedded is not None and embedded != recorded_digest:
            problems.append(
                f"RECOVERY_PLAN_SELF_DIGEST: {label} plan embeds a digest different from state")
    return problems


def diagnose(store, fix: bool = False) -> tuple[list[str], list[str]]:
    """Return (problems, repairs_done)."""
    problems: list[str] = []
    repairs: list[str] = []
    import eflow
    import ecards
    import evalid as _evalid
    problems.extend(eflow.check_tables(cards_dir=ecards.CARDS_DIR,
                                       validators=_evalid.VALIDATORS))
    st = store.load_state()
    cfg = store.load_config()
    g = store.load_graph()
    reg = store.load_artifacts()
    # R8 (external audit r5): a torn JSONL tail used to kill doctor itself -
    # every strict reader exits with "run doctor", and doctor ran the same
    # strict readers. Sweep the journals tolerantly FIRST. --fix quarantines
    # a torn FINAL line (exactly the crash append_jsonl models: raw bytes
    # preserved in <name>.quarantine beside the journal); mid-journal damage
    # is reported with exact line numbers and honestly stops the audit.
    journal_damage = False
    for path in (store.lessons_path, store.observations_path, store.errors_path,
                 store.evidence_path, store.mech_path, store.collision_path,
                 eutil.rpath(store.repo, ".evo/evidence/SOTA.jsonl"),
                 eutil.rpath(store.repo, ".evo/evidence/TOMBSTONES.jsonl")):
        rows, bad = eutil.scan_jsonl(path)
        if not bad:
            continue
        text_lines = eutil.read_text(path).splitlines()
        last_nonempty = max((i for i, l in enumerate(text_lines, 1) if l.strip()), default=0)
        is_torn_tail = len(bad) == 1 and bad[0][0] == last_nonempty
        if fix and is_torn_tail:
            qpath = path.with_name(path.name + ".quarantine")
            with qpath.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps({"quarantined_at": eutil.utc_now(),
                                     "reason": f"torn append tail (line {bad[0][0]})",
                                     "raw": bad[0][1]}, ensure_ascii=False) + "\n")
            eutil.write_text_atomic(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
            repairs.append(f"{path.name}: quarantined torn tail line {bad[0][0]} "
                           f"(raw bytes preserved in {qpath.name})")
            continue
        journal_damage = True
        problems.append(
            f"JSONL_CORRUPT: {path.name} line(s) {[ln for ln, _ in bad]} unparseable"
            + ("; run 'evo doctor --fix' to quarantine the torn final line"
               if is_torn_tail else
               " MID-journal - manual review required (doctor never auto-deletes interior history)"))
    if journal_damage:
        problems.append("DOCTOR_DEGRADED: journal damage above blocks the full cross-file audit; "
                        "repair the reported lines, then re-run 'evo doctor'")
        return problems, repairs
    ctx = evalid.Ctx(store, st, cfg, g, reg)

    # RUN truth and recovery controls are independently auditable.  Doctor is
    # intentionally read-only here: neither malformed authority nor a stale
    # plan is repaired by rewriting history under ``--fix``.
    problems.extend(erun.collection_invariant_errors(st.get("runs") or []))
    for run in st.get("runs", []):
        if run.get("evidence_disposition") != "irrecoverable_quarantined":
            continue
        receipt_rel = str(run.get("evidence_disposition_receipt") or "")
        receipt = eutil.read_json(eutil.rpath(store.repo, receipt_rel), None) if receipt_rel else None
        if not isinstance(receipt, dict) or receipt.get("run") != run.get("id") or \
                receipt.get("disposition") != "irrecoverable_quarantined":
            problems.append(f"RUN_EVIDENCE_DISPOSITION_RECEIPT: run {run.get('id')} has no valid "
                            "irrecoverable-evidence receipt")
    problems.extend(_recovery_control_errors(store, st, g))

    # v11.1 T3: WINNER.json is agent-facing but unsealed - doctor cross-checks
    # it against the lane's frozen winner identity so a corrupted copy cannot
    # silently mislead four stages while validators keep passing the originals.
    for lane in st.get("lanes", []):
        if not lane.get("winner_sketch"):
            continue
        wpath = eutil.rpath(store.repo,
                            f".evo/rounds/{lane.get('round')}/lanes/{lane.get('id')}/WINNER.json")
        if not wpath.is_file():
            continue
        try:
            wdata = eutil.read_json(wpath, {}) or {}
        except (SystemExit, OSError):
            problems.append(f"WINNER_FILE_CORRUPT: lane {lane.get('id')} WINNER.json is unreadable "
                            "(torn write?) - delete it; the sealed originals are unaffected and "
                            "stages fall back to them")
            continue
        if not isinstance(wdata, Mapping):
            problems.append(f"WINNER_FILE_STALE: lane {lane.get('id')} WINNER.json is not a JSON "
                            "object - delete this WINNER.json (stages fall back to the sealed originals)")
            continue
        if str(wdata.get("sketch_id") or "") != str(lane.get("winner_sketch")) \
                or str(wdata.get("winner_program_digest") or "") != str(lane.get("winner_program_digest") or ""):
            problems.append(f"WINNER_FILE_STALE: lane {lane.get('id')} WINNER.json names "
                            f"{wdata.get('sketch_id')!r}/{str(wdata.get('winner_program_digest'))[:12]} "
                            f"but the lane's frozen winner is {lane.get('winner_sketch')!r}/"
                            f"{str(lane.get('winner_program_digest'))[:12]}; the sealed originals are "
                            "unaffected - delete this WINNER.json (stages fall back to them)")
        elif eprogram.candidate_digest(wdata.get("sketch") or {}) != str(lane.get("winner_program_digest") or ""):
            # Header fields intact but the sketch PAYLOAD was altered - the
            # only part four stages actually read (R2: header-only checking
            # left the body unguarded).
            problems.append(f"WINNER_FILE_BODY_MUTATED: lane {lane.get('id')} WINNER.json sketch payload "
                            "no longer matches the frozen winner_program_digest; the sealed batch/"
                            "tournament are unaffected - delete this WINNER.json (stages fall back to "
                            "the sealed originals) or let the next tournament accept rewrite it")

    # v11.1 (final audit C31): ledger slices share WINNER.json's threat shape -
    # engine-written, unsealed, agent-facing. Every slice row must be
    # byte-identical to the same-id row of its source pool.
    slice_dir = eutil.rpath(store.repo, ".evo/slices")
    if slice_dir.is_dir():
        pools = {"EVIDENCE": ".evo/evidence/EVIDENCE.jsonl",
                 "MECH": ".evo/evidence/MECH_CARDS.jsonl",
                 "SOTA": ".evo/evidence/SOTA.jsonl"}
        pool_rows: dict[str, dict] = {}
        for sf in sorted(slice_dir.glob("*.jsonl")):
            kind = sf.stem.rsplit("_", 1)[-1]
            pool_rel = pools.get(kind)
            if not pool_rel:
                continue
            if kind not in pool_rows:
                pool_rows[kind] = {str((r or {}).get("id") or ""): r
                                   for r in eutil.read_jsonl(eutil.rpath(store.repo, pool_rel))}
            for row in eutil.read_jsonl(sf):
                rid_s = str((row or {}).get("id") or "")
                if pool_rows[kind].get(rid_s) != row:
                    problems.append(f"SLICE_ROW_DIVERGED: {sf.name} row {rid_s!r} no longer matches its "
                                    f"source pool {pool_rel}; slices are convenience views - delete the "
                                    "file (the next task creation regenerates it)")
                    break

    if st.get("config_frozen"):
        problems.extend(f"CONFIG: {e}" for e in econfig.validate_config(cfg))
        # preset honesty runs on the raw file (load_config expands the preset)
        problems.extend(f"CONFIG: {e}" for e in econfig.preset_conflicts(eutil.read_json(store.config_path) or {}))
        if not st.get("bootstrap_contract_confirmed"):
            problems.append("BOOTSTRAP_CONFIRMATION_MISSING: frozen config has no mandatory user contract approval")
        expected_contract = str(st.get("bootstrap_contract_digest") or "")
        actual_contract = econfig.bootstrap_contract_digest(cfg)
        if not expected_contract:
            problems.append("BOOTSTRAP_CONTRACT_DIGEST_MISSING: frozen success/resource contract has no signed digest")
        elif expected_contract != actual_contract:
            problems.append("BOOTSTRAP_CONTRACT_MUTATED: confirmed objective/evaluation/evidence/resource fields changed; "
                            "the scheduler will refuse to continue under unapproved rules")
        expected_facts = str(st.get("bootstrap_infra_facts_digest") or "")
        if not expected_facts:
            problems.append("BOOTSTRAP_INFRA_FACTS_DIGEST_MISSING: approved infrastructure facts have no digest")
        elif expected_facts != ecanary.facts_digest(store, cfg):
            proposed = eutil.read_json(eutil.rpath(store.repo, ".evo/profile/INFRA_FACTS_PROPOSED.json"), None)
            torn = (isinstance(proposed, dict)
                    and ecanary.facts_digest_of(proposed) == ecanary.facts_digest(store, cfg)
                    and any(g.get("kind") == "infra_revision" and g.get("status") == "open"
                            for g in st.get("gates", [])))
            problems.append("BOOTSTRAP_INFRA_FACTS_MUTATED: approved infrastructure facts changed; "
                            "the scheduler will refuse to continue until they are reviewed again"
                            + (" - this LOOKS like an interrupted facts-revision approval (the "
                               "proposed bytes landed, the approval did not): restore the newest "
                               ".evo/profile/INFRA_FACTS.superseded-*.json over the facts file, "
                               "then re-decide the still-open infra_revision gate" if torn else ""))
        required_bootstrap = {"project_scan", "configure", "infra", "infra_interview"}
        missing_bootstrap = sorted(required_bootstrap - set(st.get("bootstrap_done") or []))
        if missing_bootstrap:
            problems.append(f"BOOTSTRAP_ORDER: frozen config is missing completed prerequisites {missing_bootstrap}")
        # C6: the two decision-carrying preparation files are stamped at
        # acceptance; a post-acceptance edit silently rewrites the admission
        # verdict / the signed-off preparation facts
        for label, rel, key in (
                ("PROJECT_DISCOVERY", ".evo/profile/PROJECT_DISCOVERY.json", "project_discovery"),
                ("PROVISION", ".evo/profile/PROVISION.json", "provision")):
            stamped = str((st.get("profile_digests") or {}).get(key) or "")
            if not stamped:
                continue
            current = evalid.text_file_digest(ctx, rel)
            if current != stamped:
                problems.append(f"{label}_MUTATED: {rel} changed after its acceptance stamp - "
                                "the engine-fit/readiness/preparation record no longer matches "
                                "what was accepted and signed off")
        disc_doc = eutil.read_json(eutil.rpath(store.repo, ".evo/profile/PROJECT_DISCOVERY.json"), None)
        if isinstance(disc_doc, dict) \
                and str(((disc_doc.get("readiness") or {}).get("mode")) or "") == "needs_preparation" \
                and "provision" not in (st.get("bootstrap_done") or []):
            problems.append("BOOTSTRAP_ORDER: the scan recorded needs_preparation but the frozen "
                            "config has no completed provision step")
        if st.get("infra_revision_pending"):
            # disclosed transition (INFRA_REVISION_PENDING above): the active
            # canary record is bound to the superseded facts by design, and
            # new spend is already refused until the fresh proof lands
            pass
        elif "infra_drill" in (st.get("bootstrap_done") or []):
            problems.extend(f"INFRA_CANARY: {e}" for e in ecanary.record_errors(
                store, st.get("infra_canary"), require_passed=True))
        elif st.get("phase") != "bootstrap" and not st.get("bootstrap_terminated"):
            problems.append("INFRA_CANARY_MISSING: evolution left bootstrap without a passed engine-owned canary")
    # A canary intent row that survived (attach clears rows at or below the
    # attached attempt) marks an attempt whose external command ran but whose
    # receipt was never attached - a possibly-live remote job / spent physical
    # attempt nobody adopted. This is the read side of the R9 intent row.
    for t in st.get("tasks", []):
        for row in (t.get("infra_canary_intents") or []):
            problems.append(
                f"CANARY_INTENT_ORPHANED: task {t.get('id')} attempt {row.get('attempt')} recorded a "
                f"launch intent at {row.get('launched_at')} with no attached receipt - inspect "
                f"{row.get('run_dir')} for the orphan receipt/remote job before re-running the canary")
    problems.extend(egraph.check_graph(g))
    problems.extend(eartifact.check_registry(reg, set(egraph.by_id(g))))
    # Full seal audit lives here rather than on every scheduler tick. The hot
    # path checks active heads; doctor additionally verifies every immutable
    # superseded snapshot so provenance remains append-only without quadratic
    # per-task I/O as a project grows.
    # Shared with the scheduler: one seal-field registry, one requiredness
    # predicate, one availability computation (v9.2 hand-copied all four
    # blocks here and the copies had drifted).
    import eauthority
    import esched
    eng = esched.Engine(store)
    lane_seals = eauthority.LANE_SEAL_FIELDS
    node_seals = eauthority.NODE_SEAL_FIELDS
    lane_required = eauthority.AuthorityMixin._lane_seal_required
    node_required = eauthority.AuthorityMixin._node_seal_required
    active_digests, all_digests = eng._seal_availability()
    seal_digest_cache: dict[str, str] = {}
    for lane in st.get("lanes", []):
        problems.extend(evalid.core_palette_contract_errors(ctx, lane))
        problems.extend(evalid.lane_pointer_binding_errors(ctx, lane))
        for field in lane_seals:
            seal = lane.get(field)
            if lane_required(lane, field) or isinstance(seal, dict):
                label = f"lane {lane.get('id')} {field}"
                problems.extend(eseal.verify(store.repo, seal, label=label,
                                             require_working=True, digest_cache=seal_digest_cache))
                problems.extend(eseal.upstream_errors(seal, active_digests, label=label))
        for i, seal in enumerate(lane.get("seal_history") or []):
            if isinstance(seal, dict):
                label = f"lane {lane.get('id')} history[{i}]"
                problems.extend(eseal.verify(store.repo, seal, label=label,
                                             require_working=False, digest_cache=seal_digest_cache))
                problems.extend(eseal.upstream_errors(seal, all_digests, label=label))
    for node in g.get("nodes", []):
        problems.extend(evalid.node_pointer_binding_errors(ctx, node))
        bytes_active = (node.get("status") != "abandoned"
                        and node.get("retire_reason") not in econfig.RETIRE_REASONS)
        for field in node_seals:
            seal = node.get(field)
            if node_required(node, field) or isinstance(seal, dict):
                label = f"node {node.get('id')} {field}"
                problems.extend(eseal.verify(store.repo, seal, label=label,
                                             require_working=bytes_active, digest_cache=seal_digest_cache))
                problems.extend(eseal.upstream_errors(
                    seal, active_digests if bytes_active else all_digests, label=label))
        for i, seal in enumerate(node.get("seal_history") or []):
            if isinstance(seal, dict):
                label = f"node {node.get('id')} history[{i}]"
                problems.extend(eseal.verify(store.repo, seal, label=label,
                                             require_working=False, digest_cache=seal_digest_cache))
                problems.extend(eseal.upstream_errors(seal, all_digests, label=label))
        node_bytes_active = (node.get("status") != "abandoned"
                             and node.get("retire_reason") not in econfig.RETIRE_REASONS)
        if node_bytes_active and int(node.get("implementation_revision") or 0) > 0 and \
                not node.get("implementation_revision_pending"):
            problems.extend(evalid.implementation_manifest_errors(ctx, node))
            if (cfg.get("project") or {}).get("vcs") == "git" and node.get("workdir"):
                workdir = eutil.rpath(store.repo, str(node["workdir"]))
                try:
                    git_root = evcs.worktree_root(workdir, strict=True)
                    root_matches = bool(git_root) and \
                        git_root.resolve(strict=False) == workdir.resolve(strict=False)
                    current = evcs.head_commit(workdir, strict=True)
                    tracked_clean = evcs.tracked_tree_clean(workdir)
                except evcs.GitWorkdirMissingError as exc:
                    problems.append(f"SEALED_IMPLEMENTATION_WORKDIR_MISSING: node {node.get('id')} "
                                    f"active executable workdir is gone: {exc}")
                except (evcs.GitCheckError, OSError, RuntimeError) as exc:
                    problems.append(f"SEALED_IMPLEMENTATION_GIT_CHECK_FAILED: node {node.get('id')} "
                                    f"could not be audited safely: {exc}")
                else:
                    if not root_matches:
                        problems.append(f"SEALED_IMPLEMENTATION_WORKDIR_NOT_ROOT: node {node.get('id')} "
                                        "workdir is not a dedicated Git worktree root")
                    if node.get("implementation_commit") and \
                            current != node.get("implementation_commit"):
                        problems.append(f"SEALED_IMPLEMENTATION_COMMIT: node {node.get('id')} HEAD differs from "
                                        "the reviewed implementation commit")
                    if not tracked_clean:
                        problems.append(f"SEALED_IMPLEMENTATION_DIRTY: node {node.get('id')} has tracked/staged changes")
        if node.get("resource_receipt_ready"):
            problems.extend(evalid.resource_receipt_errors(ctx, node))
    for run in st.get("runs", []):
        problems.extend(evalid.run_pointer_binding_errors(ctx, run))
        seal = run.get("evidence_seal")
        if (int(run.get("evidence_revision") or 0) > 0 and erun.is_active_evidence(run)) \
                or isinstance(seal, dict):
            label = f"run {run.get('id')} evidence"
            active = erun.is_active_evidence(run)
            problems.extend(eseal.verify(store.repo, seal, label=label,
                                         require_working=active, digest_cache=seal_digest_cache))
            problems.extend(eseal.upstream_errors(
                seal, active_digests if active else all_digests, label=label))
        for i, seal in enumerate(run.get("seal_history") or []):
            if isinstance(seal, dict):
                label = f"run {run.get('id')} history[{i}]"
                problems.extend(eseal.verify(store.repo, seal, label=label,
                                             require_working=False, digest_cache=seal_digest_cache))
                problems.extend(eseal.upstream_errors(seal, all_digests, label=label))
    # The bootstrap problem model is frozen before method exposure. If it
    # changes later, lane-level digest binding is insufficient because every
    # future diagnosis would be primed by the edited dossier.
    dossier_digest = (st.get("profile_digests") or {}).get("problem_dossier")
    dossier_rel = ".evo/profile/PROBLEM_DOSSIER.md"
    if dossier_digest:
        dossier_path = eutil.rpath(store.repo, dossier_rel)
        if not dossier_path.exists():
            problems.append("PROBLEM_DOSSIER_MISSING: frozen bootstrap dossier is missing")
        elif evalid.text_file_digest(evalid.Ctx(store, st, cfg, g, reg), dossier_rel) != dossier_digest:
            problems.append("PROBLEM_DOSSIER_MUTATED: method-blind bootstrap dossier changed after it was frozen")

    # counters must dominate used ids (engine-allocated kinds only; E/M ids are
    # agent-numbered inside their JSONL files and checked for uniqueness there)
    used: dict[str, int] = {}

    # Engine-allocated kinds = every counter estore initializes; E/M ids are
    # agent-numbered inside their JSONL files and checked for uniqueness there.
    engine_kinds = set((st.get("counters") or {})) | set(eutil.ID_WIDTHS) - {"E", "M"}

    def see(id_: str | None):
        if not id_:
            return
        p = eutil.parse_id(id_)
        if p and p[0] in engine_kinds:
            used[p[0]] = max(used.get(p[0], 0), p[1])

    for n in g.get("nodes", []):
        see(n.get("id"))
    for coll, key in ((st.get("tasks", []), "id"), (st.get("lanes", []), "id"),
                      (st.get("gates", []), "id"), (st.get("runs", []), "id")):
        for it in coll:
            see(it.get(key))
    for l in st.get("lanes", []):
        see(l.get("idea"))
    for r in st.get("rounds", []):
        see(r.get("id"))
    see(st.get("current_round"))
    # R7: duplicate-id audits for lessons/errors, mirroring observations. A
    # transition abort AFTER these journal appends but BEFORE the state commit
    # re-allocates the same id on retry - the ghost row then aliases the real
    # one for every later reader.
    lesson_seen: set[str] = set()
    for rec in store.lessons():
        lid = str(rec.get("id") or "")
        see(lid)
        if lid in lesson_seen:
            problems.append(f"LESSON_DUP_ID: duplicate id {lid} in lessons.jsonl")
        lesson_seen.add(lid)
    err_seen: set[str] = set()
    for rec in store.error_records():
        eid = str(rec.get("id") or "")
        see(eid)
        if eid in err_seen:
            problems.append(f"ERROR_DUP_ID: duplicate id {eid} in errors.jsonl")
        err_seen.add(eid)
    # R7: a concluded node with still-open infrastructure ERs means its
    # conclusion's dispositions were lost in the post-commit journal window -
    # otherwise invisible, because no future conclude task exists for it.
    for n in g.get("nodes", []):
        # R11-008 (W6): abandoned mirrors concluded - an abandon's disposition
        # rows ride the same post-commit window, and no future task exists for
        # either terminal state to re-surface the loss.
        if n.get("status") in ("concluded", "abandoned"):
            open_ers = evalid.pending_infra_errors(ctx, str(n.get("id") or ""))
            if open_ers:
                label = ("CONCLUDED_PENDING_INFRA" if n.get("status") == "concluded"
                         else "ABANDONED_PENDING_INFRA")
                problems.append(f"{label}: node {n.get('id')} is {n.get('status')} but "
                                f"infra error(s) {sorted(open_ers)[:6]} carry no disposition - "
                                "the playbook row was lost after the state commit (disclosure; "
                                "if the fix knowledge matters, record it with 'evo log')")
    # A recovery that superseded a node's knowledge must also have voided its
    # ER resolutions (one staged flush writes the retraction BEFORE the state
    # commit). A committed supersede with no retraction row is the fail-open
    # gap left by a pre-fix crash: stale "fixed"/"transient" proofs keep
    # suppressing duties for evidence the recovery already invalidated.
    retracted_nodes = {str(r.get("node") or "") for r in store.errors()
                       if str(r.get("kind") or "") == "resolution_retraction"}
    resolution_nodes = {str(r.get("node") or "") for r in store.errors()
                        if str(r.get("kind") or "") == "resolution"}
    flagged_retraction: set[str] = set()
    for row in st.get("knowledge_dispositions", []) or []:
        node_id = str((row or {}).get("node") or "")
        if str((row or {}).get("status") or "") != "superseded" \
                or not str((row or {}).get("recovery") or "") \
                or node_id in flagged_retraction or node_id in retracted_nodes \
                or node_id not in resolution_nodes:
            continue
        flagged_retraction.add(node_id)
        problems.append(f"RESOLUTION_RETRACTION_MISSING: node {node_id} was superseded by "
                        f"recovery {row.get('recovery')} but its ER resolutions were never "
                        "retracted - stale playbook/suppressor rows are still live")
    # v11.7: repeated DIFFERENT fixes on one infrastructure surface are the
    # signature of an approved fact being wrong (the playbook keeps patching
    # around it) - point at the revision verb instead of letting the pile grow.
    fix_keys: dict[str, set[str]] = {}
    for row in store.error_resolutions(st):
        if row.get("disposition") != "fixed" or not str(row.get("fix") or ""):
            continue
        surface = str(row.get("surface") or "other")
        fix_keys.setdefault(surface, set()).add(eutil.norm_ws(str(row.get("fix"))))
    for surface, fixes in sorted(fix_keys.items()):
        if len(fixes) >= 2:
            problems.append(f"INFRA_FACTS_SUSPECT: surface '{surface}' accumulated {len(fixes)} "
                            "DISTINCT working fixes - an approved INFRA_FACTS field behind that "
                            "surface may simply be wrong; consider 'evo revise-infra' (write the "
                            "corrected file to .evo/profile/INFRA_FACTS_PROPOSED.json first)")
    if st.get("infra_revision_pending"):
        problems.append("INFRA_REVISION_PENDING: a facts revision was adopted; its fresh canary "
                        "proof is still owed and new stage/eval spend is refused meanwhile - "
                        "the canary task is presented once the current open card settles "
                        "('evo next' shows the queue)")
    # v9 phenomenon ledger: id continuity + record shape + node references
    node_ids = {n.get("id") for n in g.get("nodes", [])}
    obs_seen: set[str] = set()
    for rec in store.observations():
        oid = str(rec.get("id") or "")
        see(oid)
        if oid in obs_seen:
            problems.append(f"OBSERVATION_DUP_ID: duplicate id {oid} in OBSERVATIONS.jsonl")
        obs_seen.add(oid)
        for field in ("statement", "where", "measurement", "evidence"):
            if not str(rec.get(field) or "").strip():
                problems.append(f"OBSERVATION_FIELD: {oid} missing '{field}' (the ledger holds "
                                f"measured facts, not anecdotes)")
        if rec.get("node") and rec["node"] not in node_ids:
            problems.append(f"OBSERVATION_NODE_MISSING: {oid} references unknown node {rec.get('node')}")
    for a in reg.get("artifacts", []):
        see(a.get("id"))
    for row in st.get("holds", []):
        see(row.get("id"))
    for row in st.get("recoveries", []):
        see(row.get("id"))
    # uniqueness inside agent-numbered stores
    for name, rows in (("EVIDENCE", store.evidence()), ("MECH_CARDS", store.mech_cards())):
        seen_ids: set[str] = set()
        for rec in rows:
            rid = str(rec.get("id") or "")
            if rid in seen_ids:
                problems.append(f"{name}_DUP_ID: duplicate id {rid} in {name}.jsonl")
            seen_ids.add(rid)
    # v11.2 tombstone ledger: it routes future briefs via the strategist, so a
    # corrupt or duplicated row is a routing hazard, not cosmetic noise.
    tb_path = eutil.rpath(store.repo, ".evo/evidence/TOMBSTONES.jsonl")
    tb_rows: list = []
    tb_corrupt = 0
    if tb_path.exists():
        for tb_line in eutil.read_text(tb_path).splitlines():
            tb_line = tb_line.strip()
            if not tb_line:
                continue
            try:
                tb_rows.append(json.loads(tb_line))
            except json.JSONDecodeError:
                tb_corrupt += 1
    if tb_corrupt:
        problems.append(f"TOMBSTONE_CORRUPT: {tb_corrupt} unparseable line(s) in TOMBSTONES.jsonl "
                        "(torn append) - remove the partial line; parseable rows keep working")
    tb_seen: set[str] = set()
    for rec in tb_rows:
        if not isinstance(rec, Mapping):
            problems.append("TOMBSTONE_SHAPE: TOMBSTONES.jsonl carries a non-object row")
            continue
        tid = str(rec.get("id") or "")
        if tid in tb_seen:
            problems.append(f"TOMBSTONE_DUP_ID: duplicate id {tid} in TOMBSTONES.jsonl")
        tb_seen.add(tid)
        if not (tid.startswith("TB") and tid[2:].isdigit() and len(tid) >= 5) \
                or len(str(rec.get("criterion") or "").strip()) < 60 \
                or not str(rec.get("semantics") or "").strip():
            problems.append(f"TOMBSTONE_SHAPE: {tid or '(missing id)'} needs a TB### id, a >=60-char "
                            "criterion and the fixed semantics sentence")
    for kind, mx in used.items():
        have = int(st.get("counters", {}).get(kind, 0))
        if have < mx:
            problems.append(f"COUNTER_BEHIND: counter {kind}={have} but id "
                            f"{eutil.fmt_id(kind, mx, eutil.ID_WIDTHS.get(kind, 3))} exists "
                            "(id collision risk)")
            if fix:
                st.setdefault("counters", {})[kind] = mx
                if kind in ("LS", "OB", "ER"):
                    # R9 (external audit r6): a behind counter has two causes -
                    # counter corruption (rows are real; forward is the repair,
                    # this branch) or a crash ghost (row uncommitted; the next
                    # allocation would have quarantined it, and this forward
                    # push ADOPTS it instead). The two are not mechanically
                    # distinguishable here, so the repair receipt names the
                    # adopted rows for the human to verify.
                    repairs.append(f"counter {kind} -> {mx} (rows {kind}{have + 1}..{kind}{mx} are now "
                                   "committed authority; if this followed a process crash rather than "
                                   "counter corruption, verify those rows - an uncommitted ghost row "
                                   "would otherwise have been replaced at the next allocation)")
                else:
                    repairs.append(f"counter {kind} -> {mx}")

    # single open task invariant
    open_tasks = [t["id"] for t in st.get("tasks", []) if t.get("status") == "open"]
    if len(open_tasks) > 1:
        problems.append(f"MULTI_OPEN_TASKS: {open_tasks} (engine invariant: at most one)")
        if fix:
            # R11-014: converge instead of just reporting - keep the task
            # `evo next` would present (state order) and park the rest as
            # queued_after_hold, the exact shape the reopen pump re-presents
            # one at a time. Nothing is cancelled; only the presentation
            # exclusivity is restored.
            keep = open_tasks[0]
            keep_task = next(t for t in st.get("tasks", []) if t.get("id") == keep)
            parked: list[str] = []
            cancelled: list[str] = []
            for t in st.get("tasks", []):
                if t.get("status") == "open" and t.get("id") != keep:
                    # An exact duty twin (same type+subject) is a duplicate of
                    # the kept card, not a second duty: cancel it outright.
                    # Parking it would hand the SAME authority out twice - the
                    # reopen pump re-presents parked cards, and a re-submitted
                    # twin would act on a world the kept card already changed.
                    if t.get("type") == keep_task.get("type") and \
                            (t.get("subject") or {}) == (keep_task.get("subject") or {}):
                        t["status"] = "cancelled"
                        t.pop("queued_after_hold", None)
                        t.pop("_render", None)
                        t["updated_at"] = eutil.utc_now()
                        cancelled.append(str(t.get("id")))
                    else:
                        t["status"] = "paused"
                        t["queued_after_hold"] = True
                        t["held_by"] = []
                        t.pop("presented_at", None)
                        t["updated_at"] = eutil.utc_now()
                        parked.append(str(t.get("id")))
            repairs.append(f"MULTI_OPEN_TASKS: kept {keep} open; cancelled exact duplicates "
                           f"{cancelled}; parked distinct duties {parked} as queued_after_hold "
                           "(the reopen pump re-presents those one at a time)")

    # workflow-slot invariant: running stage runs must not exceed the quota
    import einfra
    running = [r for r in st.get("runs", []) if r.get("kind") == "stage"
               and erun.holds_external_slot(r)]
    slots = einfra.slots_from_facts(store, cfg)
    if len(running) > slots:
        problems.append(f"SLOT_OVERRUN: {len(running)} workflow-stage runs hold external slots "
                        f"(running or launch-unknown) but the platform quota is {slots}")

    # Project-wide resource ledger: one charge per operation, finite values,
    # and charged+active reservations never exceed the user-approved effective
    # limit. This catches hand-edited state and double accounting.
    charged: dict[str, float] = {}
    charge_keys: set[tuple] = set()
    for entry in st.get("resource_ledger", []):
        key = (entry.get("run"), entry.get("task"))
        if key in charge_keys:
            problems.append(f"RESOURCE_DOUBLE_CHARGE: duplicate run/task charge identity {key}")
        charge_keys.add(key)
        for unit, value in (entry.get("usage") or {}).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or \
                    not math.isfinite(float(value)) or float(value) < 0:
                problems.append(f"RESOURCE_USAGE_INVALID: ledger {entry.get('id')} {unit}={value!r}")
            else:
                charged[str(unit)] = charged.get(str(unit), 0.0) + float(value)
    reserved: dict[str, float] = {}
    holders = [t for t in st.get("tasks", []) if t.get("status") == "open"] + \
              [r for r in st.get("runs", []) if erun.holds_reservation(r)]
    for holder in holders:
        for unit, value in (holder.get("resource_reservation") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                reserved[str(unit)] = reserved.get(str(unit), 0.0) + float(value)
    effective = {u: v + float((st.get("resource_overrides") or {}).get(u, 0.0) or 0.0)
                 for u, v in econfig.resource_limits(cfg).items()}
    for unit, limit in effective.items():
        if charged.get(unit, 0.0) + reserved.get(unit, 0.0) > limit + 1e-9:
            problems.append(f"RESOURCE_LIMIT_EXCEEDED: {unit} charged={charged.get(unit, 0):g} "
                            f"reserved={reserved.get(unit, 0):g} effective_limit={limit:g}")
    for run in st.get("runs", []):
        # For every LEGAL execution status, holds_reservation() structurally
        # covers an unaccounted reservation (in-flight, finished-pending and
        # terminal-with-reservation all hold), so the old "ended uncharged"
        # condition became unsatisfiable. What CAN still leak is a run whose
        # status fell outside the enum (hand-edited state): it neither holds
        # nor settles, and the capacity sum above silently ignores it.
        if run.get("kind") in ("stage", "eval") and run.get("resource_reservation") \
                and not run.get("resource_accounted") \
                and str(run.get("status") or "") not in erun.EXECUTION_STATUSES:
            problems.append(f"RESOURCE_RUN_UNACCOUNTED: run {run.get('id')} holds a reservation but its "
                            f"execution status {str(run.get('status') or '')!r} is outside the legal enum - "
                            "the reservation can neither settle nor release")
    # a running run must belong to a node in the matching in-flight status
    idx = egraph.by_id(g)
    running_all = [r for r in st.get("runs", []) if r.get("status") == "running"
                   and r.get("kind") in ("stage", "eval")]
    for r in running_all:
        n = idx.get(r.get("node") or "")
        expect = "executing" if r.get("kind") == "stage" else "evaluating"
        if n is None:
            problems.append(f"RUN_NODE_MISSING: run {r['id']} references unknown node {r.get('node')}")
        else:
            launch_task = next((t for t in st.get("tasks", [])
                                if t.get("id") == r.get("launch_task")), None)
            launch_receipt_pending = bool(launch_task and launch_task.get("status") in {"open", "paused"})
            if n.get("status") != expect and not launch_receipt_pending:
                problems.append(f"RUN_NODE_STATUS: run {r['id']} ({r.get('kind')}) is running but node "
                                f"{r.get('node')} is {n.get('status')} (expected {expect})")
    run_idx = {str(r.get("id")): r for r in st.get("runs", []) if str(r.get("id") or "")}
    for n in g.get("nodes", []):
        for head, rid in (n.get("evidence_heads") or {}).items():
            run = run_idx.get(str(rid))
            if run is None:
                problems.append(f"EVIDENCE_HEAD_RUN_MISSING: node {n.get('id')} {head} -> {rid}")
            elif run.get("node") != n.get("id") or not erun.is_active_evidence(run):
                problems.append(f"EVIDENCE_HEAD_INACTIVE: node {n.get('id')} {head} points to "
                                f"non-adopted/superseded run {rid}")
        eval_run_id = str(n.get("eval_run") or "")
        if eval_run_id:
            eval_run = run_idx.get(eval_run_id)
            if eval_run is None or eval_run.get("node") != n.get("id") \
                    or eval_run.get("kind") != "eval" or not erun.is_active_evidence(eval_run):
                problems.append(f"EVAL_RUN_INACTIVE: node {n.get('id')} eval_run {eval_run_id} is not active eval evidence")

    # stage cursor sanity
    specs: dict[str, dict] = {}
    for n in g.get("nodes", []):
        spec_rel = str(n.get("spec") or "")
        if not spec_rel:
            # rpath(repo, "") would resolve to the repo DIRECTORY and die with
            # PermissionError inside the doctor - nothing to audit here
            continue
        try:
            spec = eutil.read_json(eutil.rpath(store.repo, spec_rel), None)
        except (SystemExit, OSError):
            problems.append(f"NODE_SPEC_CORRUPT: node {n.get('id')} spec {spec_rel} is unreadable "
                            "(torn write / wrong path) - restore it from the sealed copy")
            continue
        if spec is None:
            continue
        if not isinstance(spec, Mapping):
            problems.append(f"NODE_SPEC_CORRUPT: node {n.get('id')} spec {spec_rel} is not a JSON object")
            continue
        specs[n["id"]] = spec
        stages = econfig.stages_of(spec)
        cur = n.get("stage_cursor")
        if cur is not None and (not isinstance(cur, int) or cur < 0 or cur > max(len(stages), 0)):
            problems.append(f"NODE_STAGE_CURSOR: node {n['id']} stage_cursor {cur} out of range 0..{len(stages)}")
        seeds = econfig.workflow_seeds(spec)
        ridx = n.get("replica_index")
        if seeds and (not isinstance(ridx, int) or ridx < 0 or ridx >= len(seeds)):
            problems.append(f"NODE_REPLICA_INDEX: node {n['id']} replica_index {ridx} out of range 0..{len(seeds)-1}")
        completed = n.get("replicas_completed") or []
        # R9-002: the bought-back repeat lane records its completion beside the
        # preplanned lanes but is not one of them - the prefix law governs the
        # preplanned rows only.
        planned_rows = [x for x in completed
                        if not (isinstance(x, dict) and x.get("repeat_measure"))]
        completed_seeds = [x.get("seed") for x in planned_rows if isinstance(x, dict)]
        if len(completed_seeds) != len(planned_rows) or completed_seeds != seeds[:len(completed_seeds)]:
            problems.append(f"NODE_REPLICA_COMPLETION: node {n['id']} completed seeds {completed_seeds} "
                            f"are not an ordered prefix of {seeds}")
        if stages and seeds and n.get("status") in ("workflow_done", "evaluating", "evaluated", "concluded") \
                and not (n.get("status") == "concluded" and n.get("verdict") == "screened_out") \
                and completed_seeds != seeds:
            problems.append(f"NODE_REPLICA_INCOMPLETE: node {n['id']} reached {n.get('status')} before all "
                            f"workflow seeds completed ({completed_seeds} vs {seeds})")

    # Every active stage run is pinned to one exact (seed lane, stage) position.
    active_positions: set[tuple[str, int, int]] = set()
    for r in st.get("runs", []):
        if r.get("kind") != "stage" or r.get("adoption_status") == "superseded":
            continue
        nid = str(r.get("node") or "")
        spec = specs.get(nid)
        if not spec:
            continue
        stages = econfig.stages_of(spec)
        seeds = econfig.workflow_seeds(spec)
        stage_index = next((i for i, s in enumerate(stages) if s.get("name") == r.get("stage")), -1)
        if r.get("stage_index") != stage_index:
            problems.append(f"RUN_STAGE_INDEX: run {r.get('id')} stage_index={r.get('stage_index')} but "
                            f"stage {r.get('stage')!r} is index {stage_index}")
        if r.get("repeat_measure_attempt"):
            # R9-002: the repeat buy-back lane binds a fresh seed outside the
            # preplanned lanes (no replica index/total); its own position law
            # is the pending-seed check in absorption, not the lane table.
            if r.get("replica_seed") is None:
                problems.append(f"RUN_REPLICA_BINDING: repeat run {r.get('id')} carries no seed")
        elif seeds:
            ridx = r.get("replica_index")
            expected_seed = seeds[ridx] if isinstance(ridx, int) and 0 <= ridx < len(seeds) else None
            if expected_seed != r.get("replica_seed") or r.get("replica_total") != len(seeds):
                problems.append(f"RUN_REPLICA_BINDING: run {r.get('id')} has seed/index/total "
                                f"{r.get('replica_seed')!r}/{ridx}/{r.get('replica_total')}, expected "
                                f"{expected_seed!r}/{ridx}/{len(seeds)}")
            if (erun.holds_external_slot(r) or erun.is_active_evidence(r)) \
                    and isinstance(ridx, int) and stage_index >= 0:
                pos = (nid, ridx, stage_index)
                if pos in active_positions:
                    problems.append(f"RUN_REPLICA_DUP: multiple active-history runs occupy {nid} seed-index "
                                    f"{ridx} stage-index {stage_index}")
                active_positions.add(pos)

    # Finished canonical stages must retain the structured result/ledger that
    # justified advancing the cursor. This catches hand-edited state or deleted
    # evidence after scheduler absorption.
    for r in st.get("runs", []):
        if r.get("kind") != "stage" or r.get("status") != "finished":
            continue
        if r.get("evidence_disposition") == "irrecoverable_quarantined":
            continue
        stages = econfig.stages_of(specs.get(str(r.get("node") or ""), {}))
        stage = next((s for s in stages if s.get("name") == r.get("stage")), None)
        if stage is None:
            problems.append(f"RUN_STAGE_UNKNOWN: run {r.get('id')} names stage {r.get('stage')!r} absent from its node spec")
            continue
        spec = specs.get(str(r.get("node") or ""), {})
        strict_paths = ((spec.get("training_replication") or {}).get("mode") == "preplanned") \
            and r.get("adoption_status") != "superseded"
        expected_metrics = (str(econfig.resolve_seed_template(stage.get("metrics_file") or "",
                                                               r.get("replica_seed")))
                            if strict_paths else None)
        expected_ledger = (str(econfig.resolve_seed_template(stage.get("ledger_file") or "",
                                                              r.get("replica_seed")))
                           if strict_paths and econfig.stage_requires_ledger(stage) else None)
        producer_metrics = str(r.get("producer_metrics_file") or r.get("metrics_file") or "")
        producer_ledger = str(r.get("producer_ledger_file") or r.get("ledger_file") or "")
        if expected_metrics is not None and producer_metrics != expected_metrics:
            problems.append(f"RUN_STAGE_PRODUCER_METRICS_PATH: run {r.get('id')} landed at "
                            f"{producer_metrics!r}, expected {expected_metrics!r}")
        if expected_ledger is not None and producer_ledger != expected_ledger:
            problems.append(f"RUN_STAGE_PRODUCER_LEDGER_PATH: run {r.get('id')} landed at "
                            f"{producer_ledger!r}, expected {expected_ledger!r}")
        result_errs = evalid.stage_result_errors(
            ctx, stage, r.get("metrics_file"), r.get("ledger_file"), where=f"doctor run {r.get('id')}",
            # historical replay: honor the band actually applied at seal time
            # (v12 era-gating; see evalid.budget_band_floor_of)
            budget_band_floor=evalid.budget_band_floor_of(r),
            expected_seed=(r.get("replica_seed") if strict_paths else None),
            # Active run fields point at immutable ingested snapshots; producer
            # landing paths are checked separately above.
            expected_metrics_file=(str(r.get("metrics_file") or "") if strict_paths else None),
            expected_ledger_file=(str(r.get("ledger_file") or "")
                                  if strict_paths and econfig.stage_requires_ledger(stage) else None))
        if erun.is_active_evidence(r):
            probe_sources = evalid.active_probe_snapshot_map(ctx, idx.get(str(r.get("node") or "")) or {},
                                                              include_run=r)
            result_errs.extend(evalid.stage_probe_errors(
                ctx, spec, stage, r.get("replica_seed"), where=f"doctor run {r.get('id')} probe",
                allow_unavailable=r.get("probe_evidence_status") == "unavailable",
                artifact_sources=probe_sources))
        for err in result_errs:
            problems.append(f"RUN_STAGE_RESULT: {err}")
        if result_errs or not r.get("absorbed"):
            continue
        metrics = eutil.read_json(eutil.rpath(store.repo, r.get("metrics_file") or ""), {}) or {}
        decision = evalid.stage_gate_decision(stage, metrics)
        if decision is None:
            if r.get("scientific_outcome") is not None or r.get("scientific_gate") is not None:
                problems.append(f"RUN_GATE_UNDECLARED: run {r.get('id')} records a scientific decision but its stage has no gate")
            continue
        if r.get("scientific_outcome") != decision.get("outcome") or r.get("scientific_gate") != decision:
            problems.append(f"RUN_GATE_DRIFT: run {r.get('id')} scientific decision does not match the frozen gate and metrics")
        if decision.get("outcome") == "stop_node" and not r.get("repeat_measure_attempt"):
            # (R10-013: the repeat buy-back lane records a stop decision as an
            # observation but never applies it - the purchased second
            # measurement runs to completion by design)
            node = idx.get(str(r.get("node") or "")) or {}
            stage_index = next((i for i, s in enumerate(stages) if s.get("name") == r.get("stage")), -1)
            if node.get("stage_cursor") != stage_index:
                problems.append(f"SCIENTIFIC_STOP_CURSOR: node {node.get('id')} cursor advanced past stopped stage {r.get('stage')}")
            if node.get("status") not in ("scientific_stop", "concluded") or \
                    (node.get("status") == "concluded" and node.get("verdict") != "screened_out"):
                problems.append(f"SCIENTIFIC_STOP_NODE_STATE: node {node.get('id')} does not preserve the "
                                "stop/screened-out state")
            leaked = [a.get("id") for a in reg.get("artifacts", [])
                      if a.get("node") == node.get("id") and a.get("stage") == r.get("stage")]
            if leaked:
                problems.append(f"SCIENTIFIC_STOP_ARTIFACT_LEAK: stopped stage {r.get('stage')} registered artifacts {leaked}")

    for r in st.get("runs", []):
        if r.get("kind") != "eval" or not erun.is_active_evidence(r):
            continue
        spec = specs.get(str(r.get("node") or ""), {})
        node = idx.get(str(r.get("node") or "")) or {}
        for err in evalid.evaluation_result_errors(ctx, spec, r.get("metrics_file"),
                                                   where=f"doctor eval run {r.get('id')}",
                                                   budget_band_floor=evalid.budget_band_floor_of(r),
                                                   allow_probe_unavailable=(
                                                       r.get("probe_evidence_status") == "unavailable"
                                                       or evalid.active_probe_unavailable(ctx, node)),
                                                   probe_artifact_sources=evalid.active_probe_snapshot_map(
                                                       ctx, node, include_run=r),
                                                   # historical replay: RUNs sealed before the R9
                                                   # raw-side trials duty must not fail it forever
                                                   enforce_harness_trials=False):
            problems.append(f"RUN_EVAL_RESULT: {err}")

    # lanes reference real things
    lane_ids = set()
    for l in st.get("lanes", []):
        lane_ids.add(l["id"])
        if l.get("status") not in econfig.LANE_STATUSES:
            problems.append(f"LANE_STATUS_UNKNOWN: lane {l['id']} has unhandled status {l.get('status')!r}")
        if l.get("search_origin") not in econfig.SEARCH_ORIGINS:
            problems.append(f"LANE_SEARCH_ORIGIN: lane {l['id']} has invalid search_origin {l.get('search_origin')!r}")
        if l.get("node") and not egraph.by_id(g).get(l["node"]):
            problems.append(f"LANE_NODE_MISSING: lane {l['id']} references node {l['node']} not in graph")
        if l.get("brief_md") and not eutil.rpath(store.repo, l["brief_md"]).exists():
            problems.append(f"LANE_BRIEF_MISSING: lane {l['id']} brief {l['brief_md']} not on disk")
        if l.get("diagnosis_path"):
            if not eutil.rpath(store.repo, l["diagnosis_path"]).exists():
                problems.append(f"LANE_DIAGNOSIS_MISSING: lane {l['id']} diagnosis is missing")
            elif l.get("diagnosis_digest") and \
                    evalid.json_file_digest(evalid.Ctx(store, st, cfg, g, reg), l["diagnosis_path"]) != l["diagnosis_digest"]:
                problems.append(f"LANE_DIAGNOSIS_MUTATED: lane {l['id']} frozen diagnosis digest no longer matches")
        if l.get("search_origin") != "repair" and l.get("diagnosis_path"):
            problems.append(f"LANE_ROUTE_LEAK: non-repair lane {l['id']} carries a repair-only diagnosis")
        if l.get("search_origin") == "repair" and l.get("status") not in ("diagnose", "abandoned") \
                and not l.get("diagnosis_path") \
                and l.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES:
            problems.append(f"LANE_REPAIR_DIAGNOSIS: repair lane {l['id']} advanced without a frozen diagnosis")
        if l.get("theory_path") and l["status"] in ("challenge", "mature", "red_team", "gate", "approved",
                                                    "node_created", "done") and \
                not eutil.rpath(store.repo, l["theory_path"]).exists():
            problems.append(f"LANE_THEORY_MISSING: lane {l['id']} theory {l['theory_path']} not on disk")
        if l.get("formal") and l.get("problem_path") and \
                l["status"] in ("theorize", "challenge", "mature", "red_team", "gate", "approved",
                                "node_created", "done") and \
                not eutil.rpath(store.repo, l["problem_path"]).exists():
            problems.append(f"LANE_PROBLEM_MISSING: lane {l['id']} posed problem {l['problem_path']} not on disk")
        if l.get("idea"):
            for suffix in (".md", ".meta.json"):
                # Every status at or past a lane's review step, for every route:
                # this list gained "ablation_review" when ablation arrived and
                # was not extended for maintenance_review, so a maintenance lane
                # with a lost idea file passed doctor and failed later inside
                # v_maintenance_review as an opaque load error instead.
                if l["status"] in ("red_team", "ablation_review", "maintenance_review",
                                   "gate", "approved", "node_created", "done") and \
                        not eutil.rpath(store.repo, f".evo/ideas/{l['idea']}{suffix}").exists():
                    problems.append(f"LANE_IDEA_MISSING: lane {l['id']} idea file .evo/ideas/{l['idea']}{suffix} missing")
            if l.get("experiment_purpose") == "targeted_ablation" and \
                    l["status"] in ("gate", "approved", "node_created", "done") and \
                    not eutil.rpath(store.repo, f".evo/ideas/{l['idea']}.ablation-review.md").exists():
                    problems.append(f"LANE_ABLATION_REVIEW_MISSING: lane {l['id']} accepted causal review is missing")
            if l.get("experiment_purpose") == "maintenance" and \
                    l["status"] in ("gate", "approved", "node_created", "done") and \
                    not eutil.rpath(store.repo, f".evo/ideas/{l['idea']}.maintenance-review.md").exists():
                    problems.append(f"LANE_MAINTENANCE_REVIEW_MISSING: lane {l['id']} accepted maintenance review is missing")
            meta = eutil.read_json(eutil.rpath(store.repo, f".evo/ideas/{l['idea']}.meta.json"), {}) or {}
            # Winner program/kernel digests exist only where a tournament ran -
            # candidates AND exploratory scouts (v11.1 R2 fix: keying this on
            # == "candidate" silently dropped scouts from the custody audit).
            if meta and econfig.lane_purpose(l) in ("candidate", "exploratory"):
                if meta.get("program_digest") != l.get("winner_program_digest"):
                    problems.append(f"LANE_PROGRAM_DIGEST: lane {l['id']} winner and idea digests differ")
                if meta.get("kernel_hash") != l.get("winner_kernel_hash"):
                    problems.append(f"LANE_KERNEL_HASH: lane {l['id']} winner and idea kernel hashes differ")
        # An instrumental lane may only ever hold a status on its OWN route (or
        # a terminal one).  Nothing else pins this down: lane status is written
        # from several places, and a mis-routed rewind parks the lane in a
        # candidate status whose scheduler branch then demands artifacts the
        # lane never had - a stall that reads like a missing feature rather than
        # a corrupted record.
        seq = eflow.INSTRUMENTAL_SEQ.get(econfig.lane_purpose(l))
        if seq is not None and str(l.get("status")) not in set(seq) | {"done", "abandoned"}:
            problems.append(f"LANE_ROUTE_STATUS: {econfig.lane_purpose(l)} lane {l['id']} is in status "
                            f"{l.get('status')!r}, which is not on its route {list(seq)}")
    for n in g.get("nodes", []):
        if n.get("lane") and n["lane"] not in lane_ids:
            problems.append(f"NODE_LANE_MISSING: node {n['id']} references unknown lane {n['lane']}")
        if n.get("spec") and not eutil.rpath(store.repo, n["spec"]).exists():
            problems.append(f"NODE_SPEC_MISSING: node {n['id']} spec {n['spec']} not on disk")
        # Program IR, kernel operators and the frozen effect comparator are
        # parts of a novelty claim, carried by every PROGRAM-bearing purpose
        # (candidate + exploratory); the negative form excluded ablations alone
        # and silently began auditing probe and maintenance nodes for a
        # program they are defined not to have.
        if n.get("idea_doc") and econfig.lane_purpose(n) in ("candidate", "exploratory"):
            meta = eutil.read_json(eutil.rpath(store.repo, str(n["idea_doc"]).replace(".md", ".meta.json")), {}) or {}
            spec_rel = str(n.get("spec") or "")
            spec: dict = {}
            if not spec_rel:
                # an approved idea always has a spec; empty means the pointer
                # was wiped - report it (an unguarded rpath(repo, "") here used
                # to read the repo DIRECTORY and crash the doctor); meta-only
                # checks below still run against the empty spec
                problems.append(f"NODE_SPEC_MISSING: node {n['id']} carries an approved idea but no "
                                "spec path is recorded")
            else:
                try:
                    spec = eutil.read_json(eutil.rpath(store.repo, spec_rel), {}) or {}
                except (SystemExit, OSError):
                    spec = {}  # NODE_SPEC_CORRUPT is reported by the stage-cursor sweep
            expected = meta.get("program_digest")
            if expected and (n.get("program_digest") != expected or spec.get("program_digest") != expected):
                problems.append(f"NODE_PROGRAM_DIGEST: node {n['id']} idea/spec/state program digests diverge")
            expected_ops = sorted({str(op) for row in eprogram.kernel_components(meta)
                                   for op in (row.get("operator_refs") or [])})
            if spec.get("program_ir") != meta.get("program") or spec.get("effect_case") != meta.get("effect_case"):
                problems.append(f"NODE_PROGRAM_SEMANTICS: node {n['id']} spec does not exactly carry the approved program/effect case")
            if sorted(n.get("operator_ids") or []) != expected_ops:
                problems.append(f"NODE_OPERATOR_IDS: node {n['id']} state omits approved load-bearing operators")
            declared_comparator = str(((meta.get("effect_case") or {}).get("comparator_id") or ""))
            if declared_comparator:
                expected_comparator = declared_comparator
                if declared_comparator == "baseline":
                    baseline = next((row for row in g.get("nodes", [])
                                     if row.get("role") == "baseline"), None)
                    expected_comparator = str((baseline or {}).get("id") or "")
                if str(n.get("effect_comparator_node") or "") != expected_comparator:
                    problems.append(
                        f"NODE_EFFECT_COMPARATOR: node {n['id']} frozen comparator does not match its approved effect contract")

    for rnd in st.get("rounds", []):
        if not rnd.get("closed_at"):
            continue
        active = [(l.get("id"), l.get("status")) for l in st.get("lanes", [])
                  if l.get("round") == rnd.get("id") and l.get("status") not in ("done", "abandoned")]
        if active:
            problems.append(f"ROUND_CLOSED_WITH_ACTIVE_LANE: round {rnd.get('id')} has active lanes {active}")
    # R7 external audit: an ACTIVE lane whose node is already terminal is a
    # torn abandon cascade (graph committed, state lane update lost - possible
    # in pre-generation-commit states or foreign backups). It wedges
    # close_round on ROUND_ACTIVE_LANES forever; surface it with the verb.
    node_idx = egraph.by_id(g)
    for l in st.get("lanes", []):
        if l.get("status") in ("done", "abandoned") or not l.get("node"):
            continue
        n = node_idx.get(str(l.get("node")))
        if n is not None and n.get("status") in ("abandoned",):
            problems.append(
                f"LANE_NODE_TERMINAL: active lane {l.get('id')} ({l.get('status')}) points at "
                f"abandoned node {n.get('id')} - a torn abandon cascade; finish it with "
                f"'evo propose-abandon --lane {l.get('id')} --reason ...' and approve the gate")

    # R11 (W6) semantic audits.
    # A STUCK task is by contract waiting on an escalation decision; with no
    # open/paused escalation gate naming it, nothing can ever decide it - the
    # scheduler's settlement arms should have retired it, so surface the gap.
    esc_subjects = {str((gt.get("subject") or {}).get("task") or "")
                    for gt in st.get("gates", [])
                    if gt.get("kind") == "escalation" and gt.get("status") in ("open", "paused")}
    for t in st.get("tasks", []):
        if t.get("status") == "stuck" and str(t.get("id")) not in esc_subjects:
            problems.append(f"STUCK_TASK_NO_GATE: task {t.get('id')} ({t.get('type')}) is stuck but "
                            "no open/paused escalation gate names it - nothing can decide it; "
                            "'evo doctor --fix' retires the orphan so the scheduler re-mints the duty")
            if fix:
                # Only reachable after external state damage (task and gate
                # rows commit atomically, the engine never writes this shape):
                # retire the orphan so the scheduler re-mints the duty with a
                # fresh attempt budget, and say so in the receipt.
                t["status"] = "cancelled"
                t.pop("_render", None)
                t["updated_at"] = eutil.utc_now()
                repairs.append(f"STUCK_TASK_NO_GATE: cancelled orphan stuck task {t.get('id')} "
                               f"({t.get('type')}); the scheduler re-mints the duty with a fresh "
                               "attempt budget (its escalation gate row was lost to external damage)")
    # phase=done must hold zero open terminal obligations - the write points
    # disclose at flip time (terminal_phase_with_open_obligations); this
    # audits the PERSISTED result so a pre-fix or hand-edited DONE surfaces.
    if st.get("phase") == "done":
        term_blockers: list[str] = []
        term_blockers += [f"recovery {c.get('id')} ({c.get('status')})"
                          for c in st.get("recoveries", [])
                          if c.get("status") in ("planned", "fork_required", "repairing", "replaying")]
        for r in st.get("runs", []):
            rstatus = str(r.get("status") or "")
            if rstatus in ("launch_unknown", "running"):
                term_blockers.append(f"RUN {r.get('id')} {rstatus}")
            elif erun.needs_reconciliation(r):
                term_blockers.append(f"RUN {r.get('id')} evidence {r.get('evidence_status')}")
        for n in g.get("nodes", []):
            rm = n.get("repeat_measure")
            if isinstance(rm, Mapping) and not rm.get("waived")                     and not n.get("repeat_measure_done")                     and n.get("repeat_pending_seed") is not None:
                term_blockers.append(f"node {n.get('id')} owes its approved repeat measurement")
        if term_blockers:
            problems.append("TERMINAL_PHASE_OPEN_OBLIGATIONS: phase is 'done' but "
                            + "; ".join(term_blockers[:6])
                            + " - the terminal verdict buried live obligations")
    # An 'available' LOCAL artifact must stand behind its bytes; the registry
    # digest is what consumers freeze, so missing/drifted bytes are a live
    # hazard, not history. Remote URIs stay producer-receipt custody.
    for a in reg.get("artifacts", []):
        if str(a.get("status")) != "available":
            continue
        live, checkable = eartifact.content_custody(store, str(a.get("uri") or ""))
        if not checkable:
            continue
        want = str(a.get("content_digest") or "")
        if not live:
            problems.append(f"ARTIFACT_BYTES_MISSING: {a.get('id')} is available but local uri "
                            f"{a.get('uri')!r} holds no bytes - restore them, re-produce, or let the "
                            "producer's revive/recovery re-prove the row")
        elif want and live != want:
            problems.append(f"ARTIFACT_BYTES_DRIFTED: {a.get('id')} ({a.get('uri')}): live digest "
                            f"{live[:12]} != registered {want[:12]} - something overwrote a "
                            "registered product outside the engine; restore the sealed bytes, or "
                            "have the producer re-run the stage (a wanted new content must become "
                            "a new generation through its producer)")
    # A frozen consumer binding whose artifact moved generations will refuse
    # EVERY launch - that rejection only fires when external spend is next
    # requested, so surface it at checkup time with the actual repair verbs.
    by_art = {str(a.get("id") or ""): a for a in reg.get("artifacts", [])}
    for n in g.get("nodes", []):
        binds = n.get("artifact_bindings") if isinstance(n.get("artifact_bindings"), dict) else {}
        if not binds or n.get("status") in ("concluded", "abandoned"):
            continue
        for aid, bound in binds.items():
            a = by_art.get(str(aid))
            if a is None or str(a.get("status")) != "available":
                continue  # missing/unavailable rows surface at launch with their own verbs
            if a.get("generation") != (bound or {}).get("generation") or \
                    str(a.get("content_digest") or "") != str((bound or {}).get("content_digest") or ""):
                problems.append(
                    f"ARTIFACT_BINDING_DRIFT: node {n.get('id')} froze {aid} at generation "
                    f"{(bound or {}).get('generation')} but the registry now heads generation "
                    f"{a.get('generation')} - every launch will be refused; if the new bytes are "
                    f"the intended input run `evo rebind-artifact --node {n.get('id')} "
                    f"--artifact {aid} --note <why>`, otherwise recover the producer back to "
                    "the sealed generation")

    # v11.7 (interruption audit): a rehearsal RECEIPT whose node record is
    # missing/mismatched marks an interrupted attach - the tiny platform work
    # ran but was never adopted; the re-run re-spends it (tiny, but disclose).
    for n in g.get("nodes", []):
        rp = store.node_dir(str(n.get("id") or "")) / "rehearsal" / "RECEIPT.json"
        if not rp.is_file():
            continue
        rec = n.get("rehearsal_run")
        try:
            raw = rp.read_bytes()
        except OSError:
            continue
        import hashlib as _hl
        if not isinstance(rec, dict) or _hl.sha256(raw).hexdigest() != str(rec.get("receipt_digest") or ""):
            problems.append(f"REHEARSAL_RECEIPT_ORPHAN: node {n.get('id')} has a rehearsal receipt "
                            "on disk that its graph record does not adopt (interrupted attach) - "
                            "re-running the rehearsal re-spends one tiny pass; the orphan receipt "
                            "stays for the audit trail")

    # An archive dir whose run id the state never committed is the uncommitted
    # predecessor of a prepare-window interruption (R11-013); the reconciler
    # restores it when that id is re-allocated - flag it so nobody deletes it.
    runs_known = {str(r.get("id") or "") for r in st.get("runs", [])}
    runs_root = eutil.rpath(store.repo, ".evo/runs")
    if runs_root.exists():
        for rdir in sorted(runs_root.iterdir()):
            if not rdir.is_dir() or rdir.name in runs_known:
                continue
            for arch in ("preexisting_probe_landings", "preexisting_landings"):
                if (rdir / arch / "MANIFEST.json").exists():
                    problems.append(f"RUN_ARCHIVE_ORPHAN: .evo/runs/{rdir.name}/{arch} archives "
                                    "landings for a run id the state never committed - the RUN "
                                    "counter rolled back with that state, so the next prepared RUN "
                                    "re-allocates this id and restores them automatically; do NOT "
                                    "delete the directory")

    # lessons well formed
    for rec in store.lessons():
        if rec.get("scope") not in econfig.LESSON_SCOPES:
            problems.append(f"LESSON_SCOPE: {rec.get('id')} has illegal scope {rec.get('scope')!r}")

    if fix:
        import edash
        egraph.recompute_rollups(g, cfg)
        egraph.render_views(store, g, cfg, st)
        eartifact.render_view(store, reg)
        edash.render(store, g, cfg, st, reg)
        repairs.append("rollups recomputed; views re-rendered")
        store.save_all(st, g, reg)
        store.event("engine", "doctor_fix", repairs=repairs)
    return problems, repairs
