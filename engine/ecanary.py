"""One engine-observed, project-defined infrastructure canary.

The engine deliberately knows nothing about Slurm, Kubernetes, cloud APIs or
local GPUs.  The project supplies one command which traverses its real tiny
data -> compute -> artifact round-trip -> evaluation path (and any declared
runtime services).  This module only owns the generic trust boundary:

* issue a fresh request/nonce;
* execute the exact command;
* capture process evidence;
* validate the command's nonce-bound observation; and
* write the receipt which is allowed to decide bootstrap readiness.

It is an honest-operator guardrail, not remote cryptographic attestation.  A
provider-specific adapter may be as small or unusual as the project requires.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import econfig
import einfra
import eutil


SCHEMA = 1
MAX_TIMEOUT_S = 86_400


def _json_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _bytes_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def plan_digest(plan: dict) -> str:
    return _json_digest(plan)


def facts_digest(store, cfg: dict | None = None) -> str:
    return _json_digest(einfra.load_facts(store, cfg or store.load_config()) or {})


def facts_digest_of(facts: dict | None) -> str:
    """Digest an already-loaded facts snapshot (same function as facts_digest)."""
    return _json_digest(facts or {})


def required_surfaces(store, cfg: dict, graph: dict | None = None, *,
                      facts: dict | None = None) -> list[str]:
    surfaces = list(einfra.REQUIRED_BLOCKS)
    facts = facts if facts is not None else (einfra.load_facts(store, cfg) or {})
    surfaces.extend(f"dataset:{str((dataset or {}).get('name') or '').strip()}"
                    for dataset in ((facts.get("data") or {}).get("datasets") or [])
                    if str((dataset or {}).get("name") or "").strip())
    surfaces.extend(f"evaluation-dataset:{str((dataset or {}).get('id') or '').strip()}"
                    for dataset in (((cfg.get("evaluation_contract") or {}).get("datasets")) or [])
                    if str((dataset or {}).get("id") or "").strip())
    surfaces.extend(f"service:{name}" for name in sorted(einfra.service_names(store, cfg, graph)))
    return surfaces


def _request_payload(*, cfg: dict, facts: dict, task_id: str, attempt: int,
                     nonce: str, surfaces: list[str], approved_contract: str) -> dict:
    artifact_template = str(((facts.get("artifact_store") or {}).get("uri_template")) or "")
    return {
        "schema": SCHEMA,
        "task": task_id,
        "canary_id": f"{task_id}-a{attempt:02d}",
        "nonce": nonce,
        "infra_facts_digest": _json_digest(facts),
        "bootstrap_contract_digest": approved_contract,
        "required_surfaces": surfaces,
        "datasets": list((facts.get("data") or {}).get("datasets") or []),
        "evaluation_datasets": list(((cfg.get("evaluation_contract") or {}).get("datasets")) or []),
        "artifact_probe_uri": artifact_template.replace("{run_id}", f"infra-canary-{nonce}"),
        "evaluation_result_keys": list(econfig.result_spec(cfg)),
        "services": list(facts.get("services") or []) + ([{**facts["llm"], "name": "llm"}]
                                                         if isinstance(facts.get("llm"), dict) else []),
    }


MAX_CANARY_COMMANDS = 6


def plan_commands(plan: Any) -> list[dict]:
    """Normalize a plan to its command list (v11.7: single 'canary' object OR
    a 'canaries' list - heterogeneous platforms may need one real command per
    resource family; each is still the real path, never a mock fragment)."""
    if not isinstance(plan, dict):
        return []
    rows = plan.get("canaries")
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    canary = plan.get("canary")
    return [canary] if isinstance(canary, dict) else []


def _command_errors(store, canary: dict, *, where: str) -> list[str]:
    errs: list[str] = []
    if any(key in canary for key in ("status", "pass", "passed", "evidence", "exit")):
        errs.append(f"CANARY_PLAN_OWNERSHIP: {where}: the agent may define the command but may not author status/evidence/exit; the engine owns those fields")
    command = str(canary.get("command") or "").strip()
    if len(command) < 3:
        errs.append(f"CANARY_PLAN_COMMAND: {where}: command must be the exact project-specific command to execute")
    description = str(canary.get("description") or "").strip()
    if len(description) < 40:
        errs.append(f"CANARY_PLAN_DESCRIPTION: {where}: description must explain which real required resources THIS command traverses (>= 40 chars)")
    timeout = canary.get("timeout_s")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_S:
        errs.append(f"CANARY_PLAN_TIMEOUT: {where}: timeout_s must be an integer in [1,{MAX_TIMEOUT_S}]")
    cwd_rel = str(canary.get("cwd") or ".")
    cwd = eutil.rpath(store.repo, cwd_rel)
    try:
        cwd.resolve().relative_to(store.repo)
    except (OSError, ValueError):
        errs.append(f"CANARY_PLAN_CWD_SCOPE: {where}: cwd must stay inside the project repository")
    else:
        if not cwd.exists() or not cwd.is_dir():
            errs.append(f"CANARY_PLAN_CWD: {where}: cwd is not an existing directory: {cwd_rel!r}")
    return errs


def plan_errors(store, plan: Any) -> list[str]:
    errs: list[str] = []
    if not isinstance(plan, dict):
        return ["CANARY_PLAN_SHAPE: INFRA_DRILLS.json must be an object"]
    if plan.get("schema") != SCHEMA:
        errs.append(f"CANARY_PLAN_SCHEMA: schema must be {SCHEMA}")
    single = plan.get("canary")
    rows = plan.get("canaries")
    if isinstance(single, dict) and isinstance(rows, list):
        errs.append("CANARY_PLAN_FORM: declare EITHER one 'canary' object OR a 'canaries' list, not both")
    commands = plan_commands(plan)
    if not commands:
        return errs + ["CANARY_PLAN_MISSING: one 'canary' object (or a 'canaries' list) is required; "
                       "per-surface self-reported drills are not execution proof"]
    if isinstance(rows, list):
        if len(rows) != len(commands):
            errs.append("CANARY_PLAN_SHAPE: every 'canaries' entry must be an object")
        if len(commands) > MAX_CANARY_COMMANDS:
            errs.append(f"CANARY_PLAN_COUNT: at most {MAX_CANARY_COMMANDS} canary commands "
                        "(surfaces are covered JOINTLY - do not fragment one path into rituals)")
        for i, canary in enumerate(commands):
            errs.extend(_command_errors(store, canary, where=f"canaries[{i}]"))
    else:
        # single form keeps its historical error spellings (field-dotted for
        # value errors, un-prefixed for the ownership rule)
        for err in _command_errors(store, commands[0], where="canary"):
            err = err.replace(": canary: the agent may define", ": the agent may define")
            errs.append(err.replace(": canary: ", ": canary."))
    return errs


def _blocker_errors(blockers: Any) -> list[str]:
    if not isinstance(blockers, list) or not blockers:
        return ["CANARY_BLOCKERS: a blocked canary must emit at least one typed blocker"]
    errs: list[str] = []
    for i, blocker in enumerate(blockers):
        if not isinstance(blocker, dict):
            errs.append(f"CANARY_BLOCKER_SHAPE: blockers[{i}] must be an object")
            continue
        for field, minimum in (("missing", 15), ("needed_for", 10), ("ask", 15)):
            if len(str(blocker.get(field) or "").strip()) < minimum:
                errs.append(f"CANARY_BLOCKER_FIELD: blockers[{i}].{field} must be actionable (>={minimum} chars)")
    return errs


def _observation_shape_errors(observation: Any, *, nonce: str) -> tuple[list[str], dict, dict]:
    """Per-command half: shape, nonce, in-command duplicates, pass/blocker
    exclusivity. Returns (errors, by_surface, metrics)."""
    if not isinstance(observation, dict):
        return (["CANARY_OBSERVATION_SHAPE: adapter must write one JSON object to EVO_CANARY_RESULT"],
                {}, {})
    errs: list[str] = []
    if observation.get("nonce") != nonce:
        errs.append("CANARY_NONCE: observation must echo the fresh EVO_CANARY_NONCE; stale/prewritten results are invalid")
    checks = observation.get("checks")
    if not isinstance(checks, list):
        errs.append("CANARY_CHECKS: observation.checks must be a list")
        checks = []
    by_surface: dict[str, dict] = {}
    for i, check in enumerate(checks):
        if not isinstance(check, dict):
            errs.append(f"CANARY_CHECK_SHAPE: checks[{i}] must be an object")
            continue
        surface = str(check.get("surface") or "")
        if not surface:
            errs.append(f"CANARY_CHECK_SURFACE: checks[{i}].surface required")
            continue
        if surface in by_surface:
            errs.append(f"CANARY_CHECK_DUP: duplicate check for surface {surface!r}")
        by_surface[surface] = check
    metrics = observation.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else None
    if observation.get("blockers") not in (None, []):
        errs.append("CANARY_PASS_BLOCKERS: a success observation cannot also claim typed blockers; "
                    "blocked access must exit nonzero")
    return errs, by_surface, (metrics if metrics is not None else {})


def _coverage_errors(by_surface: dict, metrics: dict | None, *, surfaces: list[str],
                     cfg: dict) -> list[str]:
    """Merged half: every required surface covered (any command may cover it),
    every configured result key present in the merged metrics."""
    errs: list[str] = []
    for surface in surfaces:
        check = by_surface.get(surface)
        if check is None:
            errs.append(f"CANARY_SURFACE_MISSING: the integrated canary did not report required surface {surface!r}")
            continue
        if check.get("status") != "pass":
            errs.append(f"CANARY_SURFACE_FAILED: required surface {surface!r} did not pass")
        if len(str(check.get("detail") or "").strip()) < 20:
            errs.append(f"CANARY_SURFACE_DETAIL: surface {surface!r} needs a substantive observed result (>=20 chars)")
    if metrics is None:
        errs.append("CANARY_METRICS: the real tiny evaluator must emit observation.metrics")
        metrics = {}
    for key in econfig.result_spec(cfg):
        value = econfig.result_value(metrics.get(key))
        if value is None or not math.isfinite(float(value)):
            errs.append(f"CANARY_METRIC_KEY: configured result key {key!r} is missing or non-finite")
    return errs


def _observation_errors(observation: Any, *, nonce: str, surfaces: list[str], cfg: dict) -> list[str]:
    """Single-observation validation (the historical single-command contract)."""
    shape_errs, by_surface, metrics = _observation_shape_errors(observation, nonce=nonce)
    if not isinstance(observation, dict):
        return shape_errs
    raw_metrics = observation.get("metrics")
    return shape_errs + _coverage_errors(
        by_surface, raw_metrics if isinstance(raw_metrics, dict) else None,
        surfaces=surfaces, cfg=cfg)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _json_from_bytes(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return None


def verified_receipt(store, record: Any) -> tuple[dict | None, list[str]]:
    """Read receipt bytes once, then authenticate and parse those same bytes."""
    if not isinstance(record, dict):
        return None, ["CANARY_RUN_MISSING: engine canary record is missing"]
    receipt_path = eutil.rpath(store.repo, str(record.get("receipt") or ""))
    try:
        raw = receipt_path.read_bytes()
    except OSError:
        return None, ["CANARY_RECEIPT_MISSING: engine-owned receipt is missing"]
    if _bytes_digest(raw) != str(record.get("receipt_digest") or ""):
        return None, ["CANARY_RECEIPT_MUTATED: engine-owned receipt changed after execution"]
    receipt = _json_from_bytes(raw)
    if not isinstance(receipt, dict):
        return None, ["CANARY_RECEIPT_SHAPE: engine-owned receipt is not valid JSON"]
    return receipt, []


def run(store, task_id: str) -> dict:
    lock_path = store.task_dir(task_id) / "infra_canary" / "RUN.lock"
    with eutil.exclusive_file_lock(
            lock_path, f"[evo] infrastructure canary {task_id} is already running"):
        return _run_locked(store, task_id)


def _run_locked(store, task_id: str) -> dict:
    st = store.load_state()
    cfg = store.load_config()
    graph = store.load_graph()
    task = store.get_task(st, task_id)
    if task is None:
        raise SystemExit(f"[evo] no task {task_id}")
    if task.get("type") != "infra_drill" or task.get("status") != "open":
        raise SystemExit(f"[evo] task {task_id} is not an open infra_drill task")
    if not st.get("bootstrap_contract_confirmed") or not st.get("config_frozen"):
        raise SystemExit("[evo] infrastructure canary may run only after the mandatory bootstrap approval")
    approved_contract = str(st.get("bootstrap_contract_digest") or "")
    if not approved_contract or econfig.bootstrap_contract_digest(cfg) != approved_contract:
        raise SystemExit("[evo] success/resource contract changed after bootstrap approval; "
                         "the infrastructure canary was not run")
    approved_facts = str(st.get("bootstrap_infra_facts_digest") or "")
    if not approved_facts or facts_digest(store, cfg) != approved_facts:
        raise SystemExit("[evo] INFRA_FACTS changed after bootstrap approval; review the resource "
                         "manifest before running the infrastructure canary")
    outputs = list(task.get("outputs") or [])
    if len(outputs) < 2:
        raise SystemExit("[evo] infra_drill task has no plan output (engine bug)")
    plan_path = eutil.rpath(store.repo, str(outputs[1]))
    plan = eutil.read_json(plan_path, None)
    errs = plan_errors(store, plan)
    if errs:
        raise SystemExit("[evo] invalid infrastructure canary plan:\n  - " + "\n  - ".join(errs))

    current_plan_digest = plan_digest(plan)
    approved_receipt_probe = None
    # R7 audit (idempotency): a PASSED record for this exact plan+contract is
    # already the answer - the task stays open only because the agent has not
    # written/submitted the report yet. Re-executing the physical command from
    # a fresh session overwrote the single record slot, so a later flake could
    # bury a valid pass (and double-spend a real platform run). blocked/failed
    # records do NOT short-circuit: re-running them IS the retry protocol.
    attached = task.get("infra_canary_run") or {}
    if isinstance(attached, dict) and attached.get("status") == "passed" \
            and str(attached.get("plan_digest") or "") == current_plan_digest \
            and str(attached.get("bootstrap_contract_digest") or "") == approved_contract:
        approved_receipt_probe, probe_errs = verified_receipt(store, attached)
        if not probe_errs and isinstance(approved_receipt_probe, dict):
            store.event("engine", "infra_canary_reused", task=task_id,
                        attempt=attached.get("attempt"), receipt=attached.get("receipt"))
            return approved_receipt_probe
    # R7 audit (orphan adoption): a crash between the receipt publish and the
    # state attach leaves intent rows whose receipts are complete on disk.
    # Re-running the physical command re-spent real platform work (and after
    # repeated crashes the failure counter never advanced, so the max-attempt
    # gate never fired). Adopt the newest still-valid orphan receipt instead;
    # a stale/mismatched orphan falls through to a fresh execution.
    for intent in sorted([row for row in (task.get("infra_canary_intents") or [])
                          if isinstance(row, dict)],
                         key=lambda r: int(r.get("attempt") or 0), reverse=True):
        orphan_path = eutil.rpath(store.repo, str(intent.get("run_dir") or "")) / "RECEIPT.json"
        if not orphan_path.is_file():
            continue
        try:
            raw = orphan_path.read_bytes()
        except OSError:
            continue
        orphan = _json_from_bytes(raw)
        if not isinstance(orphan, dict) \
                or str(orphan.get("task") or "") != task_id \
                or str(orphan.get("nonce") or "") != str(intent.get("nonce") or "") \
                or str(orphan.get("plan_digest") or "") != current_plan_digest \
                or str(orphan.get("bootstrap_contract_digest") or "") != approved_contract:
            continue
        record = {
            "task": task_id,
            "attempt": int(orphan.get("attempt") or 0),
            "status": str(orphan.get("status") or ""),
            "plan_path": str(outputs[1]),
            "plan_digest": orphan.get("plan_digest"),
            "infra_facts_digest": orphan.get("infra_facts_digest"),
            "bootstrap_contract_digest": orphan.get("bootstrap_contract_digest"),
            "receipt": eutil.rel(store.repo, orphan_path),
            "receipt_digest": _bytes_digest(raw),
            "ran_at": orphan.get("ended_at"),
        }
        store.event("engine", "infra_canary_orphan_adopted", task=task_id,
                    attempt=record["attempt"], receipt=record["receipt"],
                    status=record["status"])
        return _attach_record(store, task_id, plan_path=plan_path,
                              approved_contract=approved_contract,
                              approved_facts=approved_facts,
                              record=record, receipt=orphan,
                              exit_code=orphan.get("exit"), adopted=True)
    attempt = int(task.get("infra_canary_attempts") or 0) + 1
    prior_failures = int(task.get("infra_canary_failures") or 0)
    attempt_limit = int((cfg.get("budgets") or {}).get("max_attempts", 3))
    nonce = secrets.token_hex(16)
    run_dir = store.task_dir(task_id) / "infra_canary" / f"attempt_{attempt:02d}_{nonce[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    observation_path = run_dir / "observation.json"
    request_path = run_dir / "request.json"
    plan_snapshot_path = run_dir / "plan.json"
    stdout_path = run_dir / "stdout.txt"
    stderr_path = run_dir / "stderr.txt"
    receipt_path = run_dir / "RECEIPT.json"
    facts = einfra.load_facts(store, cfg) or {}
    surfaces = required_surfaces(store, cfg, graph)
    eutil.write_json_atomic(plan_snapshot_path, plan)
    request = _request_payload(
        cfg=cfg, facts=facts, task_id=task_id, attempt=attempt, nonce=nonce,
        surfaces=surfaces, approved_contract=approved_contract)
    eutil.write_json_atomic(request_path, request)
    issued_request_digest = _file_digest(request_path)
    # R9 (external audit r6): persist the attempt INTENT before any external
    # side effect. The command may submit remote jobs / touch restricted data;
    # a crash between execution and the final state attach used to leave the
    # attempt counter at its old value, so the next session re-ran the whole
    # physical canary as the "same" logical attempt with a fresh nonce and an
    # orphan receipt nobody adopted. The intent row makes the orphan
    # discoverable and the attempt paid for before the side effect exists.
    intent_state = store.load_state()
    intent_task = store.get_task(intent_state, task_id)
    if intent_task is None or intent_task.get("status") != "open":
        raise SystemExit(f"[evo] task {task_id} changed while the canary was being prepared; re-run next")
    intent_task["infra_canary_attempts"] = attempt
    intent_task.setdefault("infra_canary_intents", []).append({
        "attempt": attempt, "nonce": nonce,
        "run_dir": eutil.rel(store.repo, run_dir),
        "request_digest": issued_request_digest,
        "launched_at": eutil.utc_now(),
    })
    store.save_state(intent_state)
    commands = plan_commands(plan)
    multi = isinstance(plan.get("canaries"), list)
    started_at = eutil.utc_now()
    runs: list[dict] = []       # per-command runtime facts
    observations: list[Any] = []
    for index, cmd_row in enumerate(commands):
        obs_path = (run_dir / f"observation_{index:02d}.json") if multi else observation_path
        out_path = (run_dir / f"stdout_{index:02d}.txt") if multi else stdout_path
        err_path = (run_dir / f"stderr_{index:02d}.txt") if multi else stderr_path
        row: dict = {"index": index, "command": str(cmd_row["command"]),
                     "cwd": str(cmd_row.get("cwd") or "."), "skipped": False,
                     "exit": None, "process_error": ""}
        if runs and runs[-1]["exit"] != 0:
            # an earlier command already failed/blocked this attempt; running
            # the rest would spend real platform work on a dead attempt
            row["skipped"] = True
            runs.append(row)
            observations.append(None)
            continue
        env = os.environ.copy()
        env.update({
            "EVO_CANARY_REQUEST": str(request_path),
            "EVO_CANARY_RESULT": str(obs_path),
            "EVO_CANARY_NONCE": nonce,
        })
        cwd = eutil.rpath(store.repo, row["cwd"])
        timeout = int(cmd_row["timeout_s"])
        stdout = ""
        stderr = ""
        try:
            args = row["command"] if sys.platform == "win32" else shlex.split(row["command"])
            proc = subprocess.run(
                args, cwd=str(cwd), shell=(sys.platform == "win32"), env=env,
                capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",
            )
            row["exit"] = proc.returncode
            stdout = proc.stdout or ""
            stderr = proc.stderr or ""
        except subprocess.TimeoutExpired as exc:
            row["process_error"] = f"timeout after {timeout}s"
            stdout = str(exc.stdout or "")
            stderr = str(exc.stderr or "")
        except OSError as exc:
            row["process_error"] = f"could not run: {exc}"
        eutil.write_text(out_path, stdout)
        eutil.write_text(err_path, stderr)
        row["stdout"] = eutil.rel(store.repo, out_path)
        row["stdout_digest"] = _file_digest(out_path)
        row["stderr"] = eutil.rel(store.repo, err_path)
        row["stderr_digest"] = _file_digest(err_path)
        obs = _read_json(obs_path) if obs_path.exists() else None
        row["observation"] = eutil.rel(store.repo, obs_path) if obs_path.exists() else None
        row["observation_digest"] = _file_digest(obs_path) if obs_path.exists() else None
        runs.append(row)
        observations.append(obs)

    request_mutated = (not request_path.exists() or not request_path.is_file()
                       or _file_digest(request_path) != issued_request_digest)
    exec_rows = [row for row in runs if not row["skipped"]]
    all_zero = bool(exec_rows) and all(row["exit"] == 0 and not row["process_error"]
                                       for row in exec_rows)
    # merged validation: per-command shape, then joint surface/metric coverage
    observation_errs: list[str] = []
    merged_by_surface: dict[str, dict] = {}
    merged_metrics: dict = {}
    saw_metrics = False
    for row, obs in zip(runs, observations):
        if row["skipped"]:
            continue
        label = f"command[{row['index']}]: " if multi else ""
        shape_errs, by_surface, metrics = _observation_shape_errors(obs, nonce=nonce)
        observation_errs.extend(label + e for e in shape_errs)
        for surface, check in by_surface.items():
            if surface not in merged_by_surface or check.get("status") == "pass" \
                    and merged_by_surface[surface].get("status") != "pass":
                merged_by_surface[surface] = check
        if isinstance(obs, dict) and isinstance(obs.get("metrics"), dict):
            saw_metrics = True
            merged_metrics.update(obs["metrics"])
    if all_zero:
        observation_errs.extend(_coverage_errors(
            merged_by_surface, merged_metrics if saw_metrics else None,
            surfaces=surfaces, cfg=cfg))
    if request_mutated:
        observation_errs.insert(0, "CANARY_REQUEST_MUTATED_DURING_RUN: adapter changed the "
                                "engine-issued request instead of using it read-only")
    # blocked: the FIRST nonzero command carries the typed blockers
    stopper = next((row for row in exec_rows if row["exit"] not in (None, 0)), None)
    stopper_obs = observations[stopper["index"]] if stopper is not None else None
    blocker_errs = _blocker_errors((stopper_obs or {}).get("blockers")
                                   if isinstance(stopper_obs, dict) else None)
    nonce_matches = isinstance(stopper_obs, dict) and stopper_obs.get("nonce") == nonce
    observation = stopper_obs if stopper is not None else (observations[0] if observations else None)
    exit_code: int | None = (0 if all_zero else
                             (stopper["exit"] if stopper is not None else None))
    process_error = "; ".join(row["process_error"] for row in exec_rows if row["process_error"])
    if all_zero and not observation_errs:
        status = "passed"
        errors: list[str] = []
    elif stopper is not None and nonce_matches and not blocker_errs \
            and not request_mutated:
        # Typed blockers are trusted only from an adapter that left the
        # engine-issued request intact; a mutated request is an integrity
        # failure regardless of how well-formed the blockers look.
        status = "blocked"
        errors = []
    else:
        status = "failed"
        errors = ([f"CANARY_PROCESS: {process_error}"] if process_error else [])
        if exit_code not in (None, 0):
            errors.append(f"CANARY_EXIT: command exited {exit_code}")
        errors.extend(observation_errs)
        if isinstance(observation, dict) and observation.get("blockers") is not None:
            errors.extend(blocker_errs)
    failure_attempt = prior_failures + (1 if status == "failed" else 0)
    exhausted = status == "failed" and failure_attempt >= attempt_limit
    ended_at = eutil.utc_now()
    observation_rel = eutil.rel(store.repo, observation_path) if observation_path.exists() else None
    receipt = {
        "schema": SCHEMA,
        "task": task_id,
        "attempt": attempt,
        "failure_attempt": failure_attempt,
        "attempt_limit": attempt_limit,
        "exhausted": exhausted,
        "status": status,
        "command": " && ".join(row["command"] for row in runs),
        "cwd": str((commands[0] or {}).get("cwd") or ".") if commands else ".",
        "commands": (runs if multi else None),
        "plan_digest": plan_digest(plan),
        "plan_snapshot": eutil.rel(store.repo, plan_snapshot_path),
        "plan_snapshot_digest": _file_digest(plan_snapshot_path),
        "request": eutil.rel(store.repo, request_path),
        "request_digest": issued_request_digest,
        "nonce": nonce,
        "infra_facts_digest": _json_digest(facts),
        "bootstrap_contract_digest": approved_contract,
        "required_surfaces": surfaces,
        "started_at": started_at,
        "ended_at": ended_at,
        "exit": exit_code,
        "stdout": (None if multi else eutil.rel(store.repo, stdout_path)),
        "stdout_digest": (None if multi else _file_digest(stdout_path)),
        "stderr": (None if multi else eutil.rel(store.repo, stderr_path)),
        "stderr_digest": (None if multi else _file_digest(stderr_path)),
        "observation": (None if multi else observation_rel),
        "observation_digest": (None if multi else (
            _file_digest(observation_path) if observation_path.exists() else None)),
        "blockers": list((observation or {}).get("blockers") or []) if isinstance(observation, dict) else [],
        "errors": errors,
    }
    eutil.write_json_atomic(receipt_path, receipt)
    published_receipt = receipt_path.read_bytes()
    if _json_from_bytes(published_receipt) != receipt:
        raise SystemExit("[evo] engine-owned infrastructure canary receipt changed while it was published")
    published_receipt_digest = _bytes_digest(published_receipt)
    record = {
        "task": task_id,
        "attempt": attempt,
        "status": status,
        "plan_path": str(outputs[1]),
        "plan_digest": receipt["plan_digest"],
        "infra_facts_digest": receipt["infra_facts_digest"],
        "bootstrap_contract_digest": receipt["bootstrap_contract_digest"],
        "receipt": eutil.rel(store.repo, receipt_path),
        "receipt_digest": published_receipt_digest,
        "ran_at": ended_at,
    }
    # The command may be remote and long-running. Never save the state snapshot
    # loaded before it ran: another legitimate engine action may have happened
    # meanwhile. Re-read, fail closed on task/contract/plan changes, and update
    # only the still-open task.
    return _attach_record(store, task_id, plan_path=plan_path,
                          approved_contract=approved_contract, approved_facts=approved_facts,
                          record=record, receipt=receipt, exit_code=exit_code)


def _attach_record(store, task_id: str, *, plan_path, approved_contract: str,
                   approved_facts: str, record: dict, receipt: dict,
                   exit_code=None, adopted: bool = False) -> dict:
    """Attach a finished canary receipt to the still-open task (shared by the
    fresh-execution path and the R7 orphan-adoption path). All attempt-shaped
    scalars come from the receipt itself so an adopted orphan restores exactly
    what its interrupted session would have written - including the failure
    counter the max-attempt gate keys on."""
    attempt = int(receipt.get("attempt") or 0)
    failure_attempt = int(receipt.get("failure_attempt") or 0)
    attempt_limit = int(receipt.get("attempt_limit") or 0)
    exhausted = bool(receipt.get("exhausted"))
    status = str(receipt.get("status") or "")
    errors = [str(x) for x in (receipt.get("errors") or [])]
    ended_at = receipt.get("ended_at") or eutil.utc_now()
    fresh = store.load_state()
    fresh_task = store.get_task(fresh, task_id)
    fresh_cfg = store.load_config()
    current_plan = eutil.read_json(plan_path, None)
    # v11.7: a canary may legitimately re-run mid-rounds - the re-proof an
    # adopted INFRA_FACTS revision owes. Any other rounds-phase attach is
    # still a state change (the drill task would not be open anyway).
    phase_legal = (fresh.get("phase") == "bootstrap"
                   or (fresh.get("phase") == "rounds" and fresh.get("infra_revision_pending")))
    state_changed = (fresh_task is None or fresh_task.get("type") != "infra_drill"
                     or fresh_task.get("status") != "open"
                     or not phase_legal)
    contract_changed = (str(fresh.get("bootstrap_contract_digest") or "") != approved_contract
                        or econfig.bootstrap_contract_digest(fresh_cfg) != approved_contract
                        or str(fresh.get("bootstrap_infra_facts_digest") or "") != approved_facts
                        or facts_digest(store, fresh_cfg) != approved_facts)
    plan_changed = not isinstance(current_plan, dict) or plan_digest(current_plan) != receipt["plan_digest"]
    if state_changed or contract_changed or plan_changed:
        store.event("engine", "infra_canary_discarded", task=task_id, attempt=attempt,
                    state_changed=state_changed, contract_changed=contract_changed,
                    plan_changed=plan_changed, receipt=record["receipt"])
        raise SystemExit("[evo] infrastructure canary finished, but its task, approved contract or plan "
                         "changed while it was running; the result was recorded for audit but not attached")
    fresh_task["infra_canary_attempts"] = max(
        int(fresh_task.get("infra_canary_attempts") or 0), attempt)
    fresh_task["infra_canary_failures"] = max(
        int(fresh_task.get("infra_canary_failures") or 0), failure_attempt)
    fresh_task["infra_canary_run"] = record
    # The attach retires every intent at or below this attempt: whatever
    # intent rows survive afterwards ARE the orphans (crash between execution
    # and attach), and the doctor reports them - the discoverability half the
    # intent row was written for.
    fresh_task["infra_canary_intents"] = [
        row for row in (fresh_task.get("infra_canary_intents") or [])
        if int(row.get("attempt") or 0) > attempt]
    fresh_task["updated_at"] = ended_at
    exhausted_gate_id = None
    if exhausted:
        fresh_task["attempts"] = max(int(fresh_task.get("attempts") or 0), attempt_limit)
        fresh_task["last_errors"] = list(errors[:24])
        fresh_task["status"] = "stuck"
        window = bool(fresh.get("infra_revision_pending"))
        gate = store.new_gate(
            fresh, "escalation", {"task": task_id},
            f"Infrastructure canary command failed {failure_attempt} real execution attempts. "
            f"Last errors: {'; '.join(errors[:5])}"
            + (" NOTE: this canary re-proves an adopted facts revision - approve retries it; "
               "reject ROLLS BACK to the previously proven facts and the project continues."
               if window else
               " Reject STOPS the project (bootstrap cannot complete without a passed canary)."))
        exhausted_gate_id = gate["id"]
    store.save_state(fresh)
    if exhausted_gate_id:
        store.event("engine", "infra_canary_attempts_exhausted", task=task_id,
                    attempt=attempt, failure_attempt=failure_attempt, gate=exhausted_gate_id)
    store.event("engine", "infra_canary_ran", task=task_id, attempt=attempt, status=status,
                exit=exit_code, receipt=record["receipt"], adopted=adopted)
    return receipt


def record_errors(store, record: Any, *, expect_task: str | None = None,
                  require_passed: bool = False) -> list[str]:
    """Validate against the last persisted snapshot (CLI/doctor call sites)."""
    return record_errors_for_snapshot(
        store, record, cfg=store.load_config(), st=store.load_state(),
        expect_task=expect_task, require_passed=require_passed)


def record_errors_for_snapshot(store, record: Any, *, cfg: dict, st: dict,
                               expect_task: str | None = None,
                               require_passed: bool = False,
                               facts: dict | None = None) -> list[str]:
    """Fully validate a canary against an explicit engine snapshot.

    The scheduler renders views before persisting its in-memory transition.
    Passing that snapshot keeps dashboard readiness and scheduler authority on
    the same contract without weakening any receipt/evidence binding check.
    """
    if not isinstance(record, dict):
        return ["CANARY_RUN_MISSING: run the canary through 'evo run-infra-canary --task <TASK>' first"]
    errs: list[str] = []
    if expect_task is not None and record.get("task") != expect_task:
        errs.append("CANARY_RUN_BINDING: canary record belongs to a different task")
    if record.get("status") not in ("passed", "blocked", "failed"):
        errs.append("CANARY_RUN_STATUS: engine canary record has an invalid status")
    if require_passed and record.get("status") != "passed":
        errs.append("CANARY_RUN_NOT_PASSED: active infrastructure canary is not passed")
    approved_contract = str(st.get("bootstrap_contract_digest") or "")
    if not approved_contract or econfig.bootstrap_contract_digest(cfg) != approved_contract \
            or str(record.get("bootstrap_contract_digest") or "") != approved_contract:
        errs.append("CANARY_CONTRACT_MUTATED: canary is not bound to the currently approved "
                    "success/resource contract")
    current_facts = facts if facts is not None else (einfra.load_facts(store, cfg) or {})
    approved_facts = str(st.get("bootstrap_infra_facts_digest") or "")
    if not approved_facts or _json_digest(current_facts) != approved_facts \
            or str(record.get("infra_facts_digest") or "") != approved_facts:
        errs.append("CANARY_FACTS_MUTATED: INFRA_FACTS changed after the canary ran; "
                    "review the new resource contract and run a fresh complete canary")
    plan_path = eutil.rpath(store.repo, str(record.get("plan_path") or ""))
    plan = eutil.read_json(plan_path, None) if plan_path.exists() and plan_path.is_file() else None
    if plan is None or plan_digest(plan) != str(record.get("plan_digest") or ""):
        errs.append("CANARY_PLAN_MUTATED: the plan changed after the engine executed it")
    receipt, receipt_errs = verified_receipt(store, record)
    errs.extend(receipt_errs)
    if receipt is None:
        return errs
    if not isinstance(receipt, dict) or receipt.get("task") != record.get("task") \
            or receipt.get("status") != record.get("status") \
            or receipt.get("attempt") != record.get("attempt") \
            or receipt.get("plan_digest") != record.get("plan_digest") \
            or receipt.get("infra_facts_digest") != record.get("infra_facts_digest") \
            or receipt.get("bootstrap_contract_digest") != record.get("bootstrap_contract_digest"):
        errs.append("CANARY_RECEIPT_BINDING: receipt does not match the active engine record")
        return errs
    multi_rows = receipt.get("commands") if isinstance(receipt.get("commands"), list) else None
    evidence_bytes: dict[str, bytes] = {}
    _shared = (("request", "request_digest"), ("plan_snapshot", "plan_snapshot_digest"))
    _single = (("stdout", "stdout_digest"), ("stderr", "stderr_digest"),
               ("observation", "observation_digest"))
    for field, digest_field in (_shared if multi_rows is not None else _shared + _single):
        expected = receipt.get(digest_field)
        rel = receipt.get(field)
        if expected is None and rel is None:
            if field == "observation" and record.get("status") in ("passed", "blocked"):
                errs.append("CANARY_OBSERVATION_MISSING: a passed/blocked canary lost its observation")
            continue
        path = eutil.rpath(store.repo, str(rel or ""))
        try:
            raw = path.read_bytes()
        except OSError:
            errs.append(f"CANARY_{field.upper()}_MISSING: engine-observed {field} evidence is missing")
            continue
        if _bytes_digest(raw) != str(expected or ""):
            errs.append(f"CANARY_{field.upper()}_MUTATED: engine-observed {field} evidence changed after execution")
        else:
            evidence_bytes[field] = raw
    request = _json_from_bytes(evidence_bytes["request"]) if "request" in evidence_bytes else None
    plan_snapshot = _json_from_bytes(
        evidence_bytes["plan_snapshot"]) if "plan_snapshot" in evidence_bytes else None
    if not isinstance(plan_snapshot, dict) or plan_digest(plan_snapshot) != record.get("plan_digest"):
        errs.append("CANARY_PLAN_SNAPSHOT_BINDING: engine plan snapshot disagrees with the executed plan")
    else:
        snapshot_commands = plan_commands(plan_snapshot)
        if multi_rows is not None:
            want = [(str(c.get("command") or ""), str(c.get("cwd") or ".")) for c in snapshot_commands]
            got = [(str((r or {}).get("command") or ""), str((r or {}).get("cwd") or "."))
                   for r in multi_rows]
            if want != got:
                errs.append("CANARY_COMMAND_BINDING: receipt command list disagrees with the "
                            "executed plan snapshot")
        else:
            snapshot_canary = snapshot_commands[0] if snapshot_commands else {}
            if receipt.get("command") != snapshot_canary.get("command") \
                    or receipt.get("cwd") != str(snapshot_canary.get("cwd") or "."):
                errs.append("CANARY_COMMAND_BINDING: receipt command/cwd disagree with the executed plan snapshot")
    # v11.7 multi-command receipts: authenticate every command's evidence trio
    # and rebuild the merged observation exactly as the run did
    multi_observations: list = []
    if multi_rows is not None:
        for row in multi_rows:
            idx = row.get("index")
            if row.get("skipped"):
                multi_observations.append(None)
                continue
            obs_bytes = None
            for field, digest_field in (("stdout", "stdout_digest"),
                                        ("stderr", "stderr_digest"),
                                        ("observation", "observation_digest")):
                expected = row.get(digest_field)
                rel = row.get(field)
                if expected is None and rel is None:
                    continue
                path = eutil.rpath(store.repo, str(rel or ""))
                try:
                    raw = path.read_bytes()
                except OSError:
                    errs.append(f"CANARY_{field.upper()}_MISSING: engine-observed {field} evidence "
                                f"for command[{idx}] is missing")
                    continue
                if _bytes_digest(raw) != str(expected or ""):
                    errs.append(f"CANARY_{field.upper()}_MUTATED: engine-observed {field} evidence "
                                f"for command[{idx}] changed after execution")
                elif field == "observation":
                    obs_bytes = raw
            multi_observations.append(_json_from_bytes(obs_bytes) if obs_bytes is not None else None)
    expected_surfaces = required_surfaces(store, cfg, facts=current_facts)
    raw_attempt = record.get("attempt")
    request_attempt = raw_attempt if isinstance(raw_attempt, int) and not isinstance(raw_attempt, bool) else 0
    expected_request = _request_payload(
        cfg=cfg, facts=current_facts, task_id=str(record.get("task") or ""),
        attempt=request_attempt, nonce=str(receipt.get("nonce") or ""),
        surfaces=expected_surfaces, approved_contract=approved_contract)
    if request != expected_request or receipt.get("required_surfaces") != expected_surfaces:
        errs.append("CANARY_REQUEST_BINDING: engine request, receipt and approved resource surfaces disagree")
    if multi_rows is not None:
        nonce_now = str(receipt.get("nonce") or "")
        if record.get("status") == "passed":
            if receipt.get("exit") != 0 or any(
                    (r.get("exit") != 0 or r.get("skipped")) for r in multi_rows):
                errs.append("CANARY_PASS_BINDING: a passed receipt must have exit 0 on EVERY command")
            merged: dict[str, dict] = {}
            merged_metrics: dict = {}
            saw_metrics = False
            for row, obs in zip(multi_rows, multi_observations):
                shape_errs, by_surface, _m = _observation_shape_errors(obs, nonce=nonce_now)
                errs.extend(f"command[{row.get('index')}]: " + e for e in shape_errs)
                for surface, check in by_surface.items():
                    if surface not in merged or check.get("status") == "pass" \
                            and merged[surface].get("status") != "pass":
                        merged[surface] = check
                if isinstance(obs, dict) and isinstance(obs.get("metrics"), dict):
                    saw_metrics = True
                    merged_metrics.update(obs["metrics"])
            errs.extend(_coverage_errors(merged, merged_metrics if saw_metrics else None,
                                         surfaces=expected_surfaces, cfg=cfg))
        elif record.get("status") == "blocked":
            stopper = next((row for row in multi_rows
                            if not row.get("skipped") and row.get("exit") not in (None, 0)), None)
            obs = multi_observations[multi_rows.index(stopper)] if stopper is not None else None
            blocker_errs = _blocker_errors(obs.get("blockers") if isinstance(obs, dict) else None)
            if stopper is None or not isinstance(obs, dict) \
                    or obs.get("nonce") != nonce_now or blocker_errs:
                errs.append("CANARY_BLOCKED_BINDING: blocked receipt needs a matching nonce, typed "
                            "blockers and a real nonzero command exit")
            elif receipt.get("blockers") != obs.get("blockers"):
                errs.append("CANARY_BLOCKER_BINDING: receipt blockers disagree with the verified observation")
        return errs
    observation = _json_from_bytes(
        evidence_bytes["observation"]) if "observation" in evidence_bytes else None
    if record.get("status") == "passed":
        if receipt.get("exit") != 0:
            errs.append("CANARY_PASS_BINDING: a passed receipt must have exit 0")
        errs.extend(_observation_errors(
            observation, nonce=str(receipt.get("nonce") or ""), surfaces=expected_surfaces, cfg=cfg))
    elif record.get("status") == "blocked":
        blocker_errs = _blocker_errors(
            observation.get("blockers") if isinstance(observation, dict) else None)
        if receipt.get("exit") in (None, 0) or not isinstance(observation, dict) \
                or observation.get("nonce") != receipt.get("nonce") or blocker_errs:
            errs.append("CANARY_BLOCKED_BINDING: blocked receipt needs a matching nonce, typed blockers "
                        "and a real nonzero command exit")
        elif receipt.get("blockers") != observation.get("blockers"):
            errs.append("CANARY_BLOCKER_BINDING: receipt blockers disagree with the verified observation")
    return errs
