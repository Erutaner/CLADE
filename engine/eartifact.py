"""Shared-artifact registry for reusable workflow products.

Multi-stage ideas can produce weights, datasets, model collections, prompts or
opaque procedure state that later nodes consume instead of recomputing. Reuse is
mechanical:
  - every producing stage declares a `stage_key` (canonical content key);
  - at plan time, a spec whose stage matches an AVAILABLE artifact's stage_key
    must either consume it or carry an explicit reuse_waiver;
  - artifact URIs must be unique registry-wide (a colliding checkpoint path -
    the classic silent-overwrite bug - is a validation error, not an incident).

The engine is the only writer of artifacts.json; registration happens when a
workflow stage's run is absorbed as finished.
"""
from __future__ import annotations

import hashlib
from typing import Any

import econfig
import eutil


def all_artifacts(reg: dict) -> list[dict]:
    return list(reg.get("artifacts") or [])


def by_id(reg: dict) -> dict[str, dict]:
    return {a["id"]: a for a in all_artifacts(reg) if a.get("id")}


def available(reg: dict) -> list[dict]:
    return [a for a in all_artifacts(reg) if a.get("status") == "available"]


def find_by_uri(reg: dict, uri: str) -> dict | None:
    # R7 audit: identity is the canonical path, not the raw spelling -
    # `a/./b` and `a/b` are the same landing on every supported filesystem.
    wanted = eutil.norm_uri(str(uri or ""))
    for a in all_artifacts(reg):
        if eutil.norm_uri(str(a.get("uri") or "")) == wanted:
            return a
    return None


def find_overlapping(reg: dict, uri: str) -> dict | None:
    """R11-004: registry identity is the OVERLAP relation, not string
    equality - a registered directory product and a later child path inside
    it denote one physical object (record_generation digests the whole
    tree). Exact lookups stay `find_by_uri`; every collision/uniqueness
    question goes through this."""
    raw = str(uri or "")
    if not raw:
        return None
    for a in all_artifacts(reg):
        if eutil.paths_overlap(raw, str(a.get("uri") or "")):
            return a
    return None


def find_available_by_stage_key(reg: dict, stage_key: str) -> dict | None:
    if not str(stage_key or "").strip():
        return None
    for a in available(reg):
        if a.get("stage_key") == stage_key:
            return a
    return None


def find_all_available_by_stage_key(reg: dict, stage_key: str) -> list[dict]:
    """R11-018: the reuse duty judges EVERY available match for a key -
    first-hit semantics let one consumed row silence the check for every
    remaining equivalent product."""
    if not str(stage_key or "").strip():
        return []
    return [a for a in available(reg) if a.get("stage_key") == stage_key]


def _seal_digest(seal: Any) -> str | None:
    if not isinstance(seal, dict):
        return None
    digest = str(seal.get("digest") or "").strip()
    return digest or None


def _producer_record(st: dict, node: str, stage: str,
                     producer_run: str | dict | None) -> dict | None:
    if isinstance(producer_run, dict):
        return producer_run
    runs = st.get("runs") or []
    if producer_run:
        return next((r for r in runs if str(r.get("id") or "") == str(producer_run)), None)
    # Focused fixtures and early registrations may omit an explicit producer
    # RUN. Infer only the latest finished, adopted stage attempt.
    return next((r for r in reversed(runs)
                 if r.get("node") == node and r.get("kind") == "stage"
                 and r.get("stage") == stage and r.get("status") == "finished"
                 and (r.get("adoption_status") == "adopted"
                      or (r.get("adoption_status") is None and not r.get("superseded")))), None)


def _active_implementation_digest(store, node: str) -> str | None:
    try:
        graph = store.load_graph()
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        return None
    record = next((n for n in (graph.get("nodes") or []) if n.get("id") == node), None)
    return _seal_digest((record or {}).get("implementation_seal"))


def _history_snapshot(artifact: dict, *, change: str, reason: str, at: str) -> dict:
    """Capture the disposition being left without rewriting its provenance."""
    return {
        "generation": int(artifact.get("generation") or 1),
        "status": artifact.get("status"),
        "stale_reason": artifact.get("stale_reason"),
        "producer_run": artifact.get("producer_run"),
        "producer_implementation_digest": artifact.get("producer_implementation_digest"),
        "producer_evidence_digest": artifact.get("producer_evidence_digest"),
        "change": change,
        "reason": reason,
        "at": at,
    }


def _append_history(artifact: dict, *, change: str, reason: str, at: str) -> None:
    artifact.setdefault("history", []).append(
        _history_snapshot(artifact, change=change, reason=reason, at=at))


def content_custody(store, uri: str) -> tuple[str, bool]:
    """R8 (external audit r5): (content_digest, locally_checkable).

    A repo-local product URI is stat-able and hashable at registration; a
    schemed URI (oss://, s3://, ...) is not - its custody is the producer
    receipt, and the digest stays empty rather than pretended."""
    rel = str(uri or "")
    if not rel or "://" in rel:
        return "", False
    try:
        p = eutil.rpath(store.repo, rel)
        if p.is_file():
            return hashlib.sha256(p.read_bytes()).hexdigest(), True
        if p.is_dir():
            # directory products: digest the sorted (relpath, sha) listing
            rows = []
            for f in sorted(x for x in p.rglob("*") if x.is_file()):
                rows.append(f"{f.relative_to(p).as_posix()}:{hashlib.sha256(f.read_bytes()).hexdigest()}")
            return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest(), True
    except OSError:
        pass
    return "", True


def register(store, st: dict, reg: dict, *, node: str, stage: str, stage_key: str | None,
             name: str, kind: str, uri: str,
             producer_run: str | dict | None = None,
             producer_implementation_digest: str | None = None,
             producer_evidence_digest: str | None = None) -> dict:
    run = _producer_record(st, node, stage, producer_run)
    run_id = str((run or {}).get("id") or producer_run or "").strip() or None
    implementation_digest = (str(producer_implementation_digest or "").strip() or
                             _active_implementation_digest(store, node))
    evidence_digest = (str(producer_evidence_digest or "").strip() or
                       _seal_digest((run or {}).get("evidence_seal")))
    created_at = eutil.utc_now()
    digest, checkable = content_custody(store, uri)
    art = {
        "id": store.next_id(st, "AR"),
        "node": node,
        "stage": stage,
        "stage_key": stage_key,
        "name": name,
        "kind": kind,
        "uri": uri,
        # R8: a locally-checkable product that does not exist is a GHOST -
        # registering it available handed later consumers a name with no
        # bytes behind it, discovered only when their stage crashed.
        "status": ("invalid" if checkable and not digest else "available"),
        "content_digest": digest,
        "generation": 1,
        "producer_run": run_id,
        "producer_implementation_digest": implementation_digest,
        "producer_evidence_digest": evidence_digest,
        "stale_reason": ("declared product missing/unreadable at registration"
                         if checkable and not digest else None),
        "history": [],
        "created_at": created_at,
        "produced_at": created_at,
    }
    # R8: same crash-window rule as egraph.new_node - artifacts.json can be
    # written before the state commit marker; an existing row under the id
    # the committed counter allocates NOW is uncommitted debris, replaced.
    reg["artifacts"] = [a for a in reg.get("artifacts", []) if str(a.get("id")) != str(art["id"])]
    reg.setdefault("artifacts", []).append(art)
    store.event("engine", "artifact_registered", artifact=art["id"], node=node, stage=stage,
                kind=kind, uri=uri, stage_key=stage_key, generation=1,
                producer_run=run_id, implementation_digest=implementation_digest,
                evidence_digest=evidence_digest)
    return art


def record_generation(store, artifact: dict, *, producer_run: str | dict | None,
                      producer_implementation_digest: str | None = None,
                      producer_evidence_digest: str | None = None,
                      stage: str | None = None, stage_key: str | None = None,
                      reason: str = "artifact reproduced") -> dict:
    """Advance one logical AR identity to a newly produced immutable generation.

    The URI remains the logical artifact identity, while the old producer
    binding is retained in ``history``.  Scheduler integration should call this
    instead of changing a stale artifact back to ``available`` in place.
    """
    now = eutil.utc_now()
    _append_history(artifact, change="generation_replaced", reason=reason, at=now)
    previous = artifact.get("generation")
    generation = int(previous) + 1 if isinstance(previous, int) and not isinstance(previous, bool) else 2
    run = producer_run if isinstance(producer_run, dict) else None
    run_id = str((run or {}).get("id") or producer_run or "").strip() or None
    implementation_digest = (str(producer_implementation_digest or "").strip() or
                             _active_implementation_digest(store, str(artifact.get("node") or "")))
    evidence_digest = (str(producer_evidence_digest or "").strip() or
                       _seal_digest((run or {}).get("evidence_seal")))
    artifact["generation"] = generation
    artifact["producer_run"] = run_id
    artifact["producer_implementation_digest"] = implementation_digest
    artifact["producer_evidence_digest"] = evidence_digest
    digest, checkable = content_custody(store, str(artifact.get("uri") or ""))
    artifact["content_digest"] = digest
    artifact["status"] = "invalid" if checkable and not digest else "available"
    artifact["produced_at"] = now
    artifact["replaced_at"] = now
    artifact.pop("stale_at", None)
    artifact["stale_reason"] = ("declared product missing/unreadable at registration"
                                if checkable and not digest else None)
    if stage is not None:
        artifact["stage"] = stage
    if stage_key is not None:
        artifact["stage_key"] = stage_key
    store.event("engine", "artifact_generation_recorded", artifact=artifact.get("id"),
                node=artifact.get("node"), stage=artifact.get("stage"),
                generation=generation, producer_run=run_id,
                implementation_digest=implementation_digest,
                evidence_digest=evidence_digest, reason=reason)
    return artifact


def invalidate_for_node(store, reg: dict, node: str, reason: str) -> None:
    """When a node is abandoned/pruned, its artifacts must not silently keep
    feeding future plans."""
    for a in all_artifacts(reg):
        if a.get("node") == node and a.get("status") == "available":
            now = eutil.utc_now()
            _append_history(a, change="invalidated", reason=reason, at=now)
            a["status"] = "stale"
            a["stale_reason"] = reason
            a["stale_at"] = now
            store.event("engine", "artifact_stale", artifact=a.get("id"), node=node, reason=reason,
                        generation=int(a.get("generation") or 1),
                        producer_run=a.get("producer_run"))


def revive_for_node(store, reg: dict, node: str, *,
                    allowed_reasons: set[str] | frozenset[str] | None = None,
                    active_implementation_digest: str | None = None) -> tuple[int, list[dict]]:
    """Restore only retirement-stale artifacts from the active producer build.

    Workflow-restart staleness is intentionally not revivable.  Passing the
    active implementation digest is the fail-closed form used by recovery code:
    legacy or old-generation artifacts without an exact match remain stale.

    R8 audit: registry metadata alone must not certify availability -
    retirement legitimately relaxed working-byte duties, so the URI may have
    been cleaned up or rewritten since. Locally checkable artifacts are
    re-hashed against the registered content digest; missing/drifted ones
    stay stale and are returned in the second element so the CLI reports the
    truth instead of promising consumers a product that is not there.
    Returns (revived_count, skipped_rows)."""
    allowed = ({"producer pruned", "producer archived"}
               if allowed_reasons is None else set(allowed_reasons))
    revived = 0
    skipped: list[dict] = []
    for artifact in all_artifacts(reg):
        if artifact.get("node") != node or artifact.get("status") != "stale":
            continue
        stale_reason = str(artifact.get("stale_reason") or "")
        if stale_reason not in allowed:
            continue
        if active_implementation_digest is not None and \
                artifact.get("producer_implementation_digest") != active_implementation_digest:
            continue
        digest_now, checkable = content_custody(store, artifact.get("uri"))
        registered = str(artifact.get("content_digest") or "")
        if checkable and (not digest_now or (registered and digest_now != registered)):
            skipped.append({"id": str(artifact.get("id") or "?"),
                            "uri": str(artifact.get("uri") or ""),
                            "reason": ("bytes missing at uri" if not digest_now
                                       else "bytes drifted from the registered digest")})
            continue
        now = eutil.utc_now()
        _append_history(artifact, change="revived", reason=stale_reason, at=now)
        artifact["status"] = "available"
        artifact["stale_reason"] = None
        artifact.pop("stale_at", None)
        artifact["revived_at"] = now
        revived += 1
        store.event("engine", "artifact_revived", artifact=artifact.get("id"), node=node,
                    generation=int(artifact.get("generation") or 1),
                    producer_run=artifact.get("producer_run"), reason=stale_reason)
    return revived, skipped


def check_registry(reg: dict, graph_ids: set[str]) -> list[str]:
    errs: list[str] = []
    seen_ids: set[str] = set()
    seen_uris: dict[str, str] = {}
    for a in all_artifacts(reg):
        aid = str(a.get("id") or "?")
        if aid in seen_ids:
            errs.append(f"ARTIFACT_DUP_ID: duplicate artifact id {aid}")
        seen_ids.add(aid)
        if a.get("kind") not in econfig.ARTIFACT_KINDS:
            errs.append(f"ARTIFACT_KIND: {aid} has illegal kind {a.get('kind')!r} "
                        f"(legal: {econfig.ARTIFACT_KINDS})")
        if a.get("status") not in ("available", "stale", "invalid"):
            errs.append(f"ARTIFACT_STATUS: {aid} has illegal status {a.get('status')!r}")
        generation = a.get("generation")
        if generation is not None and (isinstance(generation, bool) or
                                       not isinstance(generation, int) or generation < 1):
            errs.append(f"ARTIFACT_GENERATION: {aid} generation must be a positive integer")
        history = a.get("history")
        if history is not None and not isinstance(history, list):
            errs.append(f"ARTIFACT_HISTORY: {aid} history must be an array")
        uri = eutil.norm_uri(str(a.get("uri") or ""))
        if not uri:
            errs.append(f"ARTIFACT_URI_EMPTY: {aid} has no uri")
        elif uri in seen_uris:
            errs.append(f"ARTIFACT_URI_DUP: {aid} and {seen_uris[uri]} share uri {uri}")
        else:
            # R11-004: uniqueness is the OVERLAP relation - a directory
            # product and a row inside it digest the same physical bytes
            container = next((other_id for other_uri, other_id in seen_uris.items()
                              if eutil.paths_overlap(uri, other_uri)), None)
            if container is not None:
                errs.append(f"ARTIFACT_URI_CONTAINMENT: {aid} ({uri}) overlaps {container}'s "
                            "registered landing - one physical object may not carry two rows")
            seen_uris[uri] = aid
        if a.get("node") and a["node"] not in graph_ids:
            errs.append(f"ARTIFACT_NODE_UNKNOWN: {aid} produced by nonexistent node {a.get('node')}")
    return errs


def artifacts_block(reg: dict) -> list[str]:
    """Bundle block: what shared artifacts exist for planning/reuse."""
    arts = available(reg)
    if not arts:
        return ["- none yet"]
    out = []
    for a in arts:
        out.append(f"- {a['id']} '{a.get('name')}' kind={a.get('kind')} from {a.get('node')}/{a.get('stage')} "
                   f"generation={a.get('generation') or 1} run={a.get('producer_run') or '-'} "
                   f"stage_key={a.get('stage_key') or '-'} uri={a.get('uri')}")
    return out


def artifacts_receipts(reg: dict) -> dict:
    """Machine receipt for what artifacts_block just rendered (R11-010).

    Keyed by artifact id; the generation/digest pin lets acceptance-time
    validation detect that the registry moved under an open card (the card
    text is static after creation) instead of silently freezing a binding
    the author never saw.  Built from the SAME row source as the rendered
    block so the receipt can never drift from the prose.
    """
    return {str(a.get("id")): {"generation": int(a.get("generation") or 1),
                               "content_digest": str(a.get("content_digest") or ""),
                               "node": str(a.get("node") or ""),
                               "uri": str(a.get("uri") or "")}
            for a in available(reg) if str(a.get("id") or "")}


def render_view(store, reg: dict) -> None:
    lines = ["# Shared Artifacts (generated; do not edit)", ""]
    lines.append("| id | name | kind | producer | stage | generation | run | stage_key | status | stale reason | uri |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for a in all_artifacts(reg):
        lines.append(f"| {a.get('id')} | {a.get('name')} | {a.get('kind')} | {a.get('node')} | "
                     f"{a.get('stage')} | {a.get('generation') or 1} | {a.get('producer_run') or '-'} | "
                     f"{a.get('stage_key') or '-'} | {a.get('status')} | {a.get('stale_reason') or '-'} | "
                     f"{a.get('uri')} |")
    eutil.write_text(store.views_dir() / "ARTIFACTS.md", "\n".join(lines) + "\n")
