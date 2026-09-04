"""Engine-observed full-chain rehearsal for one node (v11.7).

Before a node's first FULL-SCALE run, one tiny real pass over its ENTIRE
workflow (every stage + the evaluation) must run on the real platform: every
stage launches for real, every produced artifact is READ BACK BY ITS
CONSUMER's real reading code, and the metrics come out. A wiring mistake then
costs one tiny job instead of the full training budget - and the receipt binds
to the implementation seal, so a later code revision re-owes the proof.

The trust boundary is the canary's (ecanary): the node spec owns the command,
the engine executes it, owns exit codes/stdout/stderr, and validates a
nonce-bound observation. It is an honest-operator guardrail, not remote
attestation.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shlex
import subprocess
import sys
from typing import Any

import econfig
import egraph
import einfra
import eutil

SCHEMA = 1
MAX_TIMEOUT_S = 86_400


def _json_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _bytes_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def required(cfg: dict, node: dict, spec: dict) -> bool:
    """Whether this node owes a full-chain rehearsal at all."""
    if str((cfg.get("project") or {}).get("rehearsal") or "") != "full_chain":
        return False
    if str(node.get("role") or "") == "baseline":
        # the baseline's own path was proven by provision + the integrated
        # canary + the engine-run smoke; its spec predates candidate planning
        return False
    return bool(econfig.stages_of(spec))


def plan_errors(spec: dict, *, where: str) -> list[str]:
    """Validate the spec's top-level rehearsal block (called from _spec_errors)."""
    errs: list[str] = []
    plan = spec.get("rehearsal")
    if not isinstance(plan, dict):
        return [f"SPEC_REHEARSAL: {where}: project.rehearsal=full_chain requires a top-level "
                "'rehearsal' object {command, timeout_s, description} - one command that runs "
                "the WHOLE workflow tiny (a few steps per stage + the real evaluation) on the "
                "real platform and proves every artifact hand-off"]
    if any(key in plan for key in ("status", "pass", "passed", "evidence", "exit")):
        errs.append(f"SPEC_REHEARSAL_OWNERSHIP: {where}: the spec may define the command but "
                    "never its outcome; the engine owns status/evidence/exit")
    if len(str(plan.get("command") or "").strip()) < 3:
        errs.append(f"SPEC_REHEARSAL_COMMAND: {where}: rehearsal.command must be the exact "
                    "command to execute")
    if len(str(plan.get("description") or "").strip()) < 40:
        errs.append(f"SPEC_REHEARSAL_DESCRIPTION: {where}: rehearsal.description must explain "
                    "how the tiny pass traverses every stage AND how each consumer re-reads "
                    "its input artifact (>= 40 chars)")
    timeout = plan.get("timeout_s")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= MAX_TIMEOUT_S:
        errs.append(f"SPEC_REHEARSAL_TIMEOUT: {where}: rehearsal.timeout_s must be an integer "
                    f"in [1,{MAX_TIMEOUT_S}]")
    return errs


def _request_payload(store, cfg: dict, node: dict, spec: dict, *, nonce: str) -> dict:
    facts = einfra.load_facts(store, cfg) or {}
    template = str(((facts.get("artifact_store") or {}).get("uri_template")) or "")
    stages = [str(s.get("name") or f"stage{i}") for i, s in enumerate(econfig.stages_of(spec))]
    return {
        "schema": SCHEMA,
        "node": str(node.get("id") or ""),
        "nonce": nonce,
        "implementation_digest": str((node.get("implementation_seal") or {}).get("digest") or ""),
        "stages": stages,
        "evaluation_result_keys": list(econfig.result_spec(cfg)),
        # a DISPOSABLE landing namespace: tiny products must never collide
        # with the node's real landings or the shared registry
        "rehearsal_uri": template.replace("{run_id}", f"rehearsal-{node.get('id')}-{nonce[:8]}")
        if template else "",
    }


def _observation_errors(observation: Any, *, nonce: str, stages: list[str], cfg: dict) -> list[str]:
    if not isinstance(observation, dict):
        return ["REHEARSAL_OBSERVATION_SHAPE: the command must write one JSON object to "
                "EVO_REHEARSAL_RESULT"]
    errs: list[str] = []
    if observation.get("nonce") != nonce:
        errs.append("REHEARSAL_NONCE: observation must echo the fresh EVO_REHEARSAL_NONCE; "
                    "stale/prewritten results are invalid")
    checks = observation.get("checks")
    if not isinstance(checks, list):
        errs.append("REHEARSAL_CHECKS: observation.checks must be a list")
        checks = []
    by_stage: dict[str, dict] = {}
    for i, check in enumerate(checks):
        if not isinstance(check, dict):
            errs.append(f"REHEARSAL_CHECK_SHAPE: checks[{i}] must be an object")
            continue
        stage = str(check.get("stage") or "")
        if not stage:
            errs.append(f"REHEARSAL_CHECK_STAGE: checks[{i}].stage required")
            continue
        if stage in by_stage:
            errs.append(f"REHEARSAL_CHECK_DUP: duplicate check for stage {stage!r}")
        by_stage[stage] = check
    for stage in stages:
        check = by_stage.get(stage)
        if check is None:
            errs.append(f"REHEARSAL_STAGE_MISSING: the tiny pass did not report stage {stage!r}")
            continue
        if check.get("status") != "pass":
            errs.append(f"REHEARSAL_STAGE_FAILED: stage {stage!r} did not pass")
        if len(str(check.get("detail") or "").strip()) < 20:
            errs.append(f"REHEARSAL_STAGE_DETAIL: stage {stage!r} needs a substantive observed "
                        "result (>= 20 chars)")
        # the load-bearing half (R-audit: producer-writes was always checked
        # somewhere; consumer-READS never was until full scale): every stage's
        # product must have been read back by the code that consumes it next
        if len(str(check.get("read_back_by") or "").strip()) < 20:
            errs.append(f"REHEARSAL_READBACK: stage {stage!r} needs read_back_by (>= 20 chars): "
                        "WHICH consumer code (the next stage's loader / the evaluator) re-read "
                        "the artifact this stage just wrote, and what it saw - writer-side "
                        "self-reads do not count")
    metrics = observation.get("metrics")
    if not isinstance(metrics, dict):
        errs.append("REHEARSAL_METRICS: the real tiny evaluation must emit observation.metrics")
        metrics = {}
    for key in econfig.result_spec(cfg):
        value = econfig.result_value(metrics.get(key))
        if value is None:
            errs.append(f"REHEARSAL_METRIC_KEY: configured result key {key!r} is missing")
    if observation.get("blockers") not in (None, []):
        errs.append("REHEARSAL_PASS_BLOCKERS: a success observation cannot also claim typed "
                    "blockers; blocked access must exit nonzero")
    return errs


def _blocker_errors(blockers: Any) -> list[str]:
    if not isinstance(blockers, list) or not blockers:
        return ["REHEARSAL_BLOCKERS: a blocked rehearsal must emit at least one typed blocker"]
    errs: list[str] = []
    for i, blocker in enumerate(blockers):
        if not isinstance(blocker, dict):
            errs.append(f"REHEARSAL_BLOCKER_SHAPE: blockers[{i}] must be an object")
            continue
        for field, minimum in (("missing", 15), ("needed_for", 10), ("ask", 15)):
            if len(str(blocker.get(field) or "").strip()) < minimum:
                errs.append(f"REHEARSAL_BLOCKER_FIELD: blockers[{i}].{field} must be actionable "
                            f"(>={minimum} chars)")
    return errs


def receipt_path(store, node_id: str):
    return store.node_dir(node_id) / "rehearsal" / "RECEIPT.json"


def run(store, node_id: str) -> dict:
    lock_path = store.node_dir(node_id) / "rehearsal" / "RUN.lock"
    with eutil.exclusive_file_lock(
            lock_path, f"[evo] rehearsal for {node_id} is already running"):
        return _run_locked(store, node_id)


def _run_locked(store, node_id: str) -> dict:
    cfg = store.load_config()
    g = store.load_graph()
    node = egraph.by_id(g).get(node_id)
    if node is None:
        raise SystemExit(f"[evo] no node {node_id} - see 'evo status' or .evo/views/GRAPH.md "
                         "for the graph's node ids")
    spec = eutil.read_json(eutil.rpath(store.repo, str(node.get("spec") or "")), None)
    if spec is None:
        raise SystemExit(f"[evo] node {node_id} has no spec at {node.get('spec')}")
    if not required(cfg, node, spec):
        if str((cfg.get("project") or {}).get("rehearsal") or "") != "full_chain":
            raise SystemExit(f"[evo] node {node_id} owes no rehearsal: project.rehearsal is "
                             f"'{(cfg.get('project') or {}).get('rehearsal')}' - the duty exists "
                             "only under full_chain (chosen at configure)")
        if str(node.get("role") or "") == "baseline":
            raise SystemExit(f"[evo] node {node_id} owes no rehearsal: the baseline's own path "
                             "was already proven by preparation, the integrated canary and the "
                             "engine-run smoke")
        raise SystemExit(f"[evo] node {node_id} owes no rehearsal: its spec declares no workflow "
                         "stages, so there is no full-scale stage spend to protect")
    impl_digest = str((node.get("implementation_seal") or {}).get("digest") or "")
    if not impl_digest:
        raise SystemExit(f"[evo] node {node_id} has no implementation seal yet; the rehearsal "
                         "binds to the sealed code it proves - run it from the rehearsal task")
    errs = plan_errors(spec, where=f"spec({node_id})")
    if errs:
        raise SystemExit("[evo] invalid rehearsal plan:\n  - " + "\n  - ".join(errs))
    plan = spec["rehearsal"]
    # idempotency: a receipt for this exact seal + plan is already the answer
    prior = node.get("rehearsal_run")
    plan_digest = _json_digest(plan)
    if isinstance(prior, dict) and prior.get("status") == "passed" \
            and str(prior.get("implementation_digest") or "") == impl_digest \
            and str(prior.get("plan_digest") or "") == plan_digest:
        # C2 (correctness audit): reuse only what still AUTHENTICATES - a
        # damaged receipt would otherwise short-circuit here forever while
        # every launch keeps refusing it, with no verb able to regenerate it.
        try:
            raw = eutil.rpath(store.repo, str(prior.get("receipt") or "")).read_bytes()
        except OSError:
            raw = b""
        if _bytes_digest(raw) == str(prior.get("receipt_digest") or ""):
            store.event("engine", "rehearsal_reused", node=node_id, receipt=prior.get("receipt"))
            return dict(prior)
        store.event("engine", "rehearsal_receipt_unusable", node=node_id,
                    receipt=prior.get("receipt"))
    nonce = secrets.token_hex(16)
    stages = [str(s.get("name") or f"stage{i}") for i, s in enumerate(econfig.stages_of(spec))]
    request = _request_payload(store, cfg, node, spec, nonce=nonce)
    # C3 (correctness audit): persist the attempt INTENT through the
    # TRANSACTIONAL channel before any external side effect - the command may
    # submit real platform jobs, and a crash between execution and the attach
    # must leave a discoverable trace (doctor: REHEARSAL_RECEIPT_ORPHAN plus
    # this row), never a silent re-spend with no record.
    st0 = store.load_state()
    reg0 = store.load_artifacts()
    node.setdefault("rehearsal_intents", []).append(
        {"nonce": nonce, "launched_at": eutil.utc_now()})
    egraph.touch(node)
    store.save_all(st0, g, reg0)
    run_dir = store.node_dir(node_id) / "rehearsal"
    run_dir.mkdir(parents=True, exist_ok=True)
    request_path = run_dir / "request.json"
    result_path = run_dir / "observation.json"
    if result_path.exists():
        result_path.unlink()
    eutil.write_json_atomic(request_path, request)
    env = dict(os.environ)
    env["EVO_REHEARSAL_REQUEST"] = str(request_path)
    env["EVO_REHEARSAL_RESULT"] = str(result_path)
    env["EVO_REHEARSAL_NONCE"] = nonce
    command = str(plan.get("command") or "")
    workdir = eutil.rpath(store.repo, str(spec.get("workdir") or "."))
    timeout = int(plan.get("timeout_s") or 3600)
    started = eutil.utc_now()
    try:
        args = command if sys.platform == "win32" else shlex.split(command)
        proc = subprocess.run(
            args, cwd=str(workdir), shell=(sys.platform == "win32"),
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace", env=env)
        exit_code: int | None = proc.returncode
        stdout, stderr = proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        stderr = ((exc.stderr or "") if isinstance(exc.stderr, str) else "") \
            + f"\n[evo] rehearsal timed out after {timeout}s"
    except OSError as exc:
        exit_code = None
        stdout, stderr = "", f"[evo] could not run rehearsal command: {exc}"
    eutil.write_text(run_dir / "stdout.txt", stdout)
    eutil.write_text(run_dir / "stderr.txt", stderr)
    observation = eutil.read_json(result_path, None)
    request_now = eutil.read_json(request_path, None)
    status = "failed"
    errors: list[str] = []
    if request_now != request:
        errors.append("REHEARSAL_REQUEST_MUTATED_DURING_RUN: the engine-owned request file changed")
    elif exit_code == 0:
        errors = _observation_errors(observation, nonce=nonce, stages=stages, cfg=cfg)
        status = "passed" if not errors else "failed"
    elif exit_code not in (None, 0) and isinstance(observation, dict) \
            and observation.get("nonce") == nonce \
            and observation.get("blockers") not in (None, []):
        errors = _blocker_errors(observation.get("blockers"))
        status = "blocked" if not errors else "failed"
    else:
        errors = [f"rehearsal command exited {exit_code} without a typed nonce-bound observation"]
    receipt = {
        "schema": SCHEMA, "node": node_id, "status": status,
        "command": command, "cwd": str(spec.get("workdir") or "."),
        "plan_digest": plan_digest, "nonce": nonce,
        "implementation_digest": impl_digest,
        "request_digest": _json_digest(request),
        "stages": stages,
        "observation": observation if isinstance(observation, dict) else None,
        "blockers": (observation or {}).get("blockers") if isinstance(observation, dict) else None,
        "errors": errors, "exit": exit_code,
        "stdout_digest": _bytes_digest(stdout.encode("utf-8")),
        "stderr_digest": _bytes_digest(stderr.encode("utf-8")),
        "started_at": started, "ended_at": eutil.utc_now(),
    }
    rp = receipt_path(store, node_id)
    eutil.write_json_atomic(rp, receipt)
    raw = rp.read_bytes()
    record = {
        "node": node_id, "status": status,
        "plan_digest": plan_digest, "implementation_digest": impl_digest,
        "receipt": rp.relative_to(store.repo).as_posix(), "receipt_digest": _bytes_digest(raw),
        "ran_at": receipt["ended_at"],
    }
    node["rehearsal_run"] = record
    node["rehearsal_intents"] = [row for row in (node.get("rehearsal_intents") or [])
                                 if str(row.get("nonce") or "") != nonce]
    egraph.touch(node)
    # the attach rides the SAME three-file transactional channel as every
    # other authority write (C3) - a torn generation is rolled back/forward
    # by the store's own recovery instead of silently overwriting it
    st1 = store.load_state()
    reg1 = store.load_artifacts()
    store.save_all(st1, g, reg1)
    store.event("engine", "rehearsal_ran", node=node_id, status=status,
                errors=errors[:5], exit=exit_code)
    return record


def record_errors(store, node: dict, *, require_passed: bool = True) -> list[str]:
    """Authenticate the node's rehearsal record against its receipt bytes and
    the CURRENT implementation seal - the enforcement read for launches."""
    record = node.get("rehearsal_run")
    if not isinstance(record, dict):
        return ["REHEARSAL_REQUIRED: this node owes a full-chain rehearsal before real spend - "
                "run its rehearsal task first ('evo run-rehearsal --node <id>')"]
    rp = eutil.rpath(store.repo, str(record.get("receipt") or ""))
    try:
        raw = rp.read_bytes()
    except OSError:
        return ["REHEARSAL_RECEIPT_MISSING: the engine-owned rehearsal receipt is missing"]
    if _bytes_digest(raw) != str(record.get("receipt_digest") or ""):
        return ["REHEARSAL_RECEIPT_MUTATED: the rehearsal receipt changed after execution"]
    try:
        receipt = json.loads(raw.decode("utf-8"))
    except Exception:
        return ["REHEARSAL_RECEIPT_SHAPE: the rehearsal receipt is not valid JSON"]
    errs: list[str] = []
    impl = str((node.get("implementation_seal") or {}).get("digest") or "")
    if str(receipt.get("implementation_digest") or "") != impl or \
            str(record.get("implementation_digest") or "") != impl:
        errs.append("REHEARSAL_STALE: the implementation was re-sealed after this rehearsal - "
                    "the proof no longer covers the code about to spend; re-run it with "
                    f"'evo run-rehearsal --node {node.get('id')}' and submit the rehearsal task")
    if str(receipt.get("status") or "") != str(record.get("status") or ""):
        errs.append("REHEARSAL_RECEIPT_BINDING: receipt/record status disagree")
    if require_passed and str(record.get("status") or "") != "passed":
        errs.append(f"REHEARSAL_NOT_PASSED: the rehearsal record is "
                    f"'{record.get('status')}', not passed")
    return errs
