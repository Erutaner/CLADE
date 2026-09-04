"""Content-addressed seals for decision-authoritative evolution artifacts.

The engine deliberately keeps human-readable working paths, but an accepted
scientific contract must never inherit an approval after those bytes change.
Each seal therefore records both the working-path digest and an immutable,
content-addressed snapshot.  Upstream seal digests form a compact provenance
chain (theory -> idea -> spec -> evidence -> conclusion).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable

import eutil


def _publish_snapshot(source: Path, snapshot: Path, expected_digest: str, repo: Path) -> None:
    """R9 (external audit r6): copy2 straight to the final content-addressed
    path could crash mid-copy; the exists() fast path then trusted the partial
    file FOREVER (every later verify: SEALED_SNAPSHOT_CORRUPT, no repair verb,
    working bytes irrelevant). Publish via temp + verified digest + atomic
    replace, and when the final path already exists, verify it - rebuilding
    from the still-correct working bytes instead of trusting existence."""
    rel = eutil.rel(repo, snapshot)
    if snapshot.exists():
        if artifact_digest(repo, rel) == expected_digest:
            return
    # the temp file must carry the FINAL suffix: artifact_digest canonicalizes
    # .json by content, so hashing a ".tmp" copy would compare raw bytes
    # against a canonical digest and never match.
    fd, tmp = tempfile.mkstemp(dir=str(snapshot.parent), suffix=f".tmp{snapshot.suffix}")
    os.close(fd)
    try:
        shutil.copy2(source, tmp)
        if artifact_digest(repo, eutil.rel(repo, Path(tmp))) != expected_digest:
            raise ValueError(f"snapshot copy of {source} did not reproduce digest {expected_digest[:12]}")
        # copy2 preserves a read-only bit from the source; on Windows that
        # makes both the fsync open below and os.replace over/from read-only
        # files a PERMANENT PermissionError (the retry loop only absorbs
        # transient locks). Publish writable; the snapshot's immutability is
        # the digest, not the bit.
        os.chmod(tmp, 0o644)
        # Data must be durable BEFORE the rename publishes it (same rule as
        # write_text_atomic): a power cut after the replace otherwise leaves a
        # torn snapshot that verify reports forever with no repair verb.
        with open(tmp, "rb+") as fh:
            os.fsync(fh.fileno())
        import time
        for attempt in range(6):
            try:
                os.replace(tmp, snapshot)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                if snapshot.exists():
                    try:
                        os.chmod(snapshot, 0o644)
                    except OSError:
                        pass
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _canonical_json_bytes(path: Path) -> bytes:
    data = json.loads(path.read_text(encoding="utf-8"))
    return json.dumps(data, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def artifact_digest(repo: Path, relpath: str) -> str:
    path = eutil.rpath(repo, relpath)
    if not path.exists() or not path.is_file():
        return ""
    try:
        payload = _canonical_json_bytes(path) if path.suffix.lower() == ".json" else path.read_bytes()
    except (OSError, UnicodeError, json.JSONDecodeError):
        # Digesting is an integrity boundary.  An unreadable or malformed
        # artifact is therefore "not verifiable", not an engine exception:
        # callers will reject it as missing/mutated and fail closed.
        return ""
    return hashlib.sha256(payload).hexdigest()


def combine_digests(*parts: str) -> str:
    clean = [str(part) for part in parts if str(part or "")]
    raw = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def create(repo: Path, artifacts: Iterable[tuple[str, str]], *,
           upstream: Iterable[str] = (), revision: int = 1) -> dict:
    """Seal existing ``(role, relative_path)`` artifacts and snapshot them."""
    rows: list[dict] = []
    seal_dir = eutil.rpath(repo, ".evo/seals")
    seal_dir.mkdir(parents=True, exist_ok=True)
    for role, relpath in artifacts:
        relpath = str(relpath or "")
        path = eutil.rpath(repo, relpath)
        digest = artifact_digest(repo, relpath)
        if not digest:
            raise ValueError(f"cannot seal missing artifact {relpath!r}")
        suffix = path.suffix.lower() or ".bin"
        snapshot = seal_dir / f"{digest}{suffix}"
        _publish_snapshot(path, snapshot, digest, repo)
        rows.append({
            "role": str(role), "path": relpath, "digest": digest,
            "snapshot": eutil.rel(repo, snapshot),
        })
    upstream_clean = [str(x) for x in upstream if str(x or "")]
    payload = {
        "revision": int(revision),
        "artifacts": [{k: row[k] for k in ("role", "path", "digest")} for row in rows],
        "upstream": upstream_clean,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        **payload, "digest": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "artifacts": rows, "status": "active", "sealed_at": eutil.utc_now(),
    }


def verify(repo: Path, seal: dict | None, *, label: str = "contract",
           require_working: bool = True,
           check_snapshot: bool = True,
           digest_cache: dict[str, str] | None = None) -> list[str]:
    if not isinstance(seal, dict) or not str(seal.get("digest") or ""):
        return [f"SEAL_MISSING: {label} has no content seal"]
    errs: list[str] = []
    rows = seal.get("artifacts")
    if not isinstance(rows, list) or not rows:
        return [f"SEAL_EMPTY: {label} has no sealed artifacts"]
    compact: list[dict] = []
    cache = digest_cache if digest_cache is not None else {}
    for i, row in enumerate(rows):
        row = row if isinstance(row, dict) else {}
        role, relpath = str(row.get("role") or ""), str(row.get("path") or "")
        expected = str(row.get("digest") or "")
        snapshot = str(row.get("snapshot") or "")
        # Whether a seal is active is decided by its state location, never by
        # the mutable ``status`` field inside the record.  Active-field callers
        # require the working bytes; history callers require only the immutable
        # snapshot - so the working-path digest is computed only when required.
        # Flipping status therefore cannot disable verification.
        #
        # Snapshot depth (v11): no engine DECISION ever reads snapshot bytes -
        # they are the restore source. Hot scoped sweeps may skip re-hashing
        # them (check_snapshot=False) because a corrupted snapshot cannot lend
        # approval: any restore lands on the working path, whose digest is
        # checked here every time. The periodic full sweep, doctor, revive and
        # the post-submit sweep (crash-between-write-and-validate window) keep
        # snapshot scrubbing on. When the working bytes are NOT required
        # (retired/history rows) the snapshot hash is the only byte check and
        # is therefore never skipped.
        if require_working:
            actual = cache.get(relpath)
            if actual is None:
                actual = artifact_digest(repo, relpath)
                cache[relpath] = actual
            if not expected or actual != expected:
                errs.append(f"SEALED_ARTIFACT_MUTATED: {label}/{role or i} {relpath!r} no longer matches {expected[:12]}")
        if check_snapshot or not require_working:
            snapshot_digest = cache.get(snapshot)
            if snapshot_digest is None:
                snapshot_digest = artifact_digest(repo, snapshot)
                cache[snapshot] = snapshot_digest
            if not snapshot or snapshot_digest != expected:
                errs.append(f"SEALED_SNAPSHOT_CORRUPT: {label}/{role or i} snapshot {snapshot!r} no longer matches {expected[:12]}")
        elif not snapshot:
            errs.append(f"SEALED_SNAPSHOT_CORRUPT: {label}/{role or i} has no snapshot path recorded")
        compact.append({"role": role, "path": relpath, "digest": expected})
    payload = {
        "revision": int(seal.get("revision") or 0),
        "artifacts": compact,
        "upstream": [str(x) for x in (seal.get("upstream") or []) if str(x or "")],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    actual_seal = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    if actual_seal != seal.get("digest"):
        errs.append(f"SEAL_RECORD_MUTATED: {label} seal metadata no longer matches its digest")
    return errs


def binding_errors(repo: Path, seal: dict | None,
                   expected: Iterable[tuple[str, str]], *,
                   label: str = "contract", exact: bool = True,
                   digest_cache: dict[str, str] | None = None,
                   legacy_extra_roles: Iterable[str] = ()) -> list[str]:
    """Bind an active state pointer to the exact roles in its seal.

    ``verify`` proves that the paths *recorded by the seal* still carry the
    approved content.  A state regression could nevertheless point the active
    object at a different file while leaving the old, valid seal in place.
    This companion check closes that gap and also makes the content-addressed
    snapshot location deterministic.  It is an integrity check for accidental
    state drift and engine regressions, not an external-signature scheme.
    """
    wanted = [(str(role), str(path)) for role, path in expected]
    errs: list[str] = []
    if not isinstance(seal, dict):
        return [f"SEAL_BINDING_MISSING: {label} has no seal record"]
    rows = seal.get("artifacts")
    if not isinstance(rows, list):
        return [f"SEAL_BINDING_ROWS: {label} has no artifact rows"]
    actual: dict[str, dict] = {}
    for i, value in enumerate(rows):
        row = value if isinstance(value, dict) else {}
        role = str(row.get("role") or "")
        if not role:
            errs.append(f"SEAL_BINDING_ROLE: {label} row {i} has no role")
        elif role in actual:
            errs.append(f"SEAL_BINDING_DUP_ROLE: {label} repeats role {role!r}")
        else:
            actual[role] = row
    wanted_roles = [role for role, _path in wanted]
    if len(set(wanted_roles)) != len(wanted_roles):
        errs.append(f"SEAL_BINDING_EXPECTATION: {label} has duplicate expected roles")
    # v10.1 removed prose-report roles from two seals; a v10-created project
    # legally carries them.  Named legacy extras are tolerated in the role-set
    # comparison (their rows stay content-verified by eseal.verify) so an
    # in-place upgrade does not hard-lock every command on old active seals.
    actual_effective = set(actual) - set(legacy_extra_roles)
    role_mismatch = (actual_effective != set(wanted_roles) if exact
                     else not set(wanted_roles).issubset(set(actual)))
    if role_mismatch:
        errs.append(
            f"SEAL_BINDING_ROLES: {label} roles {sorted(actual)} do not "
            f"{'equal' if exact else 'contain'} {sorted(set(wanted_roles))}")
    cache = digest_cache if digest_cache is not None else {}
    for role, relpath in wanted:
        path = Path(relpath)
        if not relpath or path.is_absolute() or ".." in path.parts:
            errs.append(f"SEAL_BINDING_PATH_UNSAFE: {label}/{role} path {relpath!r} is not repo-relative")
            continue
        row = actual.get(role)
        if row is None:
            continue
        if str(row.get("path") or "") != relpath:
            errs.append(
                f"SEAL_BINDING_PATH: {label}/{role} active path {relpath!r} does not equal "
                f"sealed path {str(row.get('path') or '')!r}")
        digest = str(row.get("digest") or "")
        current = cache.get(relpath)
        if current is None:
            current = artifact_digest(repo, relpath)
            cache[relpath] = current
        if not digest or current != digest:
            errs.append(
                f"SEAL_BINDING_DIGEST: {label}/{role} active content {current[:12]!r} does not "
                f"equal sealed digest {digest[:12]!r}")
        suffix = path.suffix.lower() or ".bin"
        snapshot = f".evo/seals/{digest}{suffix}" if digest else ""
        if str(row.get("snapshot") or "") != snapshot:
            errs.append(
                f"SEAL_BINDING_SNAPSHOT: {label}/{role} snapshot must be the deterministic "
                f"content-addressed path {snapshot!r}")
    return errs


def digest_set(seals: Iterable[dict | None]) -> set[str]:
    """Return the non-empty digests carried by a collection of seals."""
    return {str(seal.get("digest")) for seal in seals
            if isinstance(seal, dict) and str(seal.get("digest") or "")}


def upstream_errors(seal: dict | None, available: set[str], *,
                    label: str = "contract") -> list[str]:
    """Require every provenance edge to resolve to an available seal/anchor.

    The seal record authenticates the literal upstream digest list, but that is
    not enough on its own: deleting an upstream active head and moving it to
    history must make an active descendant stale.  Callers therefore pass the
    active digest/anchor set for active heads and the all-history set when
    auditing an immutable historical record.
    """
    if not isinstance(seal, dict):
        return []
    out: list[str] = []
    for digest in [str(x) for x in (seal.get("upstream") or []) if str(x or "")]:
        if digest not in available:
            out.append(f"SEAL_UPSTREAM_MISSING: {label} references unavailable upstream {digest[:12]}")
    return out


def superseded(seal: dict | None) -> dict | None:
    if not isinstance(seal, dict):
        return None
    out = json.loads(json.dumps(seal))
    out["status"] = "superseded"
    out["superseded_at"] = eutil.utc_now()
    return out
