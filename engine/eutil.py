"""Shared helpers: IO, ids, time, text. Stdlib only, Windows-safe, UTF-8 everywhere."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@contextmanager
def exclusive_file_lock(path: Path, busy_message: str):
    """Small stdlib-only cross-process advisory lock (released on process exit)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a+b")
    locked = False
    try:
        fh.seek(0, os.SEEK_END)
        if fh.tell() == 0:
            fh.write(b"0")
            fh.flush()
        fh.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SystemExit(busy_message) from exc
        locked = True
        yield
    finally:
        if locked:
            try:
                fh.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        fh.close()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel(repo: Path, p: Path) -> str:
    """Repo-relative POSIX string for storage."""
    try:
        return p.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def rpath(repo: Path, stored: str) -> Path:
    """Resolve a stored POSIX-relative path against the repo."""
    p = Path(stored)
    return p if p.is_absolute() else (repo / p)


def norm_uri(uri: str) -> str:
    """Canonical form for landing/artifact identity COMPARISONS (R7 audit).

    Exclusivity checks (landing lease, registry duplicate, pending-producer
    reservation) used to compare raw strings, so `a/./b`, `a//b` and `a\\b`
    all bypassed a guard while the filesystem resolved them to the same file
    as `a/b`. Local scheme-less paths are normalized to a canonical POSIX
    spelling; scheme URIs (s3://...) keep backend semantics and are returned
    verbatim. Case handling follows the HOST (R10-002): on a
    case-insensitive filesystem `out/Result.JSON` and `out/result.json` are
    one physical landing, so comparisons fold case exactly where the host
    does; on case-sensitive hosts case is preserved (collapsing there would
    merge genuinely distinct files). Stored values stay as written - only
    comparisons go through this."""
    s = str(uri or "")
    if not s or "://" in s:
        return s
    import posixpath
    out = posixpath.normpath(s.replace("\\", "/"))
    if out == ".":
        return ""
    if case_insensitive_host():
        out = out.lower()
    return out


_CASE_INSENSITIVE_HOST: bool | None = None


def case_insensitive_host() -> bool:
    """Does this host's filesystem treat two case-variant spellings as ONE
    object? R10 self-audit: the OS family is not the filesystem - a
    case-insensitive volume exists on posix hosts too (and the identity
    guards must match what the filesystem actually does). Probed once per
    process with a real file; Windows short-circuits (its supported volumes
    are case-insensitive)."""
    global _CASE_INSENSITIVE_HOST
    if _CASE_INSENSITIVE_HOST is None:
        if os.name == "nt":
            _CASE_INSENSITIVE_HOST = True
        else:
            try:
                with tempfile.TemporaryDirectory(prefix="evo_case_probe_") as td:
                    probe = Path(td) / "Case_Probe.tmp"
                    probe.write_text("x", encoding="utf-8")
                    _CASE_INSENSITIVE_HOST = (Path(td) / "case_probe.tmp").exists()
            except OSError:
                _CASE_INSENSITIVE_HOST = False
    return _CASE_INSENSITIVE_HOST


def paths_overlap(a: str, b: str) -> bool:
    """Do two landing identities denote overlapping filesystem objects?

    R10-002: claim comparisons used exact string equality, so a directory
    product `out/shared` and a sibling's file `out/shared/model.pt` were
    judged disjoint while prepare-time archiving moved the whole directory -
    the overlap relation is equality OR ancestry for local paths. Scheme
    URIs compare exactly (backend semantics own their hierarchy)."""
    na, nb = norm_uri(a), norm_uri(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if "://" in na or "://" in nb:
        return False
    return na.startswith(nb + "/") or nb.startswith(na + "/")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_text_atomic(path: Path, text: str) -> None:
    """R9 (external audit r6): temp + fsync + os.replace. In-place rewrites of
    engine-owned journals (ghost quarantine, doctor torn-tail repair) used
    plain write_text - a crash inside the truncate/write window destroyed the
    very rows the rewrite meant to KEEP. Same Windows retry as
    write_json_atomic."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        import time
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(read_text(path))
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"[evo] corrupt JSON at {path}: {exc}. Every command (including doctor) needs this "
            "file readable - restore it to valid JSON first: your editor's undo, "
            "'git checkout -- <file>' (git projects), or re-copy the last good version; "
            "engine-owned files usually have a .evo sibling/backup to compare against.")


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        # Windows: antivirus/indexers transiently lock freshly written files and
        # os.replace fails with WinError 5. Retry briefly before giving up.
        import time
        for attempt in range(6):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def rmtree_robust(path: Path) -> None:
    """Windows-safe recursive delete: clears read-only attributes (git object
    files) and retries briefly on transient handle locks (antivirus/indexer)."""
    import shutil
    import stat
    import time
    if not path.exists():
        return

    def _onerror(func, target, _exc_info):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            raise

    for attempt in range(4):
        try:
            shutil.rmtree(path, onerror=_onerror)
            return
        except OSError:
            if attempt == 3:
                raise
            time.sleep(0.1 * (attempt + 1))


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = ""
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as fh:
            fh.seek(-1, 2)
            if fh.read(1) != b"\n":
                # torn tail from a crashed append: never concatenate a valid
                # row onto the partial line (that would swallow this record
                # too); the tear itself stays for doctor to report
                prefix = "\n"
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(prefix + json.dumps(record, ensure_ascii=False) + "\n")


def state_fingerprint(st: dict, g: dict, reg: dict) -> str:
    """Canonical byte-identity of the authoritative (state, graph, artifacts)
    triple.  Shared by the scheduler's no-op detection and the dashboard's
    rendered-state marker so they can never drift.  state_revision is
    excluded: it bumps on every save, carries no content of its own, and
    including it would force one spurious re-render after every save."""
    core = {k: v for k, v in st.items() if k != "state_revision"}
    raw = json.dumps((core, g, reg), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def jsonl_line_count(path: Path) -> int:
    """Count non-empty lines without parsing (display counters only)."""
    if not path.exists():
        return 0
    return sum(1 for line in read_text(path).splitlines() if line.strip())


def read_jsonl(path: Path, *, lenient: bool = False) -> list[dict]:
    """Strict by default (evidence ledgers fail closed). ``lenient=True`` skips
    unparseable lines instead - for readers that must keep working through a
    torn append (doctor diagnostics, advisory bundle blocks, idempotent
    banking) where a SystemExit would brick the very recovery path."""
    if not path.exists():
        return []
    out: list[dict] = []
    for i, line in enumerate(read_text(path).splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            if lenient:
                continue
            raise SystemExit(f"[evo] corrupt JSONL at {path} line {i}. Run 'evo doctor --fix' "
                             "(a torn final line is quarantined automatically; deeper damage is "
                             "reported with its exact line numbers).")
    return out


def scan_jsonl(path: Path) -> tuple[list[dict], list[tuple[int, str]]]:
    """R8: tolerant scanner for recovery surfaces - parsed rows plus
    (line_number, raw_line) for every unparseable line, so doctor can keep
    working through the very damage it is asked to diagnose."""
    if not path.exists():
        return [], []
    rows: list[dict] = []
    bad: list[tuple[int, str]] = []
    for i, line in enumerate(read_text(path).splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError:
            bad.append((i, line))
    return rows, bad


def fmt_id(prefix: str, n: int, width: int) -> str:
    return f"{prefix}{n:0{width}d}"


ID_WIDTHS = {"N": 3, "L": 3, "I": 3, "T": 4, "G": 3, "R": 3, "RUN": 3, "E": 3, "M": 3, "LS": 3,
             "AR": 3, "ER": 3, "OB": 3, "H": 3, "REC": 3}

# Derived from ID_WIDTHS (longest prefix first) so the parseable-id set can
# never drift from the allocatable-id set again (v9.2 forgot OB here and the
# doctor counter audit silently skipped the whole phenomenon ledger).
_ID_RE = re.compile(
    "(" + "|".join(sorted(ID_WIDTHS, key=len, reverse=True)) + r")(\d+)")


def parse_id(s: str) -> tuple[str, int] | None:
    m = _ID_RE.fullmatch(s or "")
    if not m:
        return None
    return m.group(1), int(m.group(2))


def slug(text: str, max_len: int = 32) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:max_len] or "node"


def norm_ws(text: str) -> str:
    """Normalize whitespace for literal-quote substring checks."""
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


_FENCE_RE = re.compile(r"^\s{0,3}(```|~~~)")


def md_sections(text: str) -> dict[str, str]:
    """Map heading title (lowercased, '#' stripped) -> body text.

    Fence-aware: a '#' line inside a ``` / ~~~ code block is content, never a
    heading (v9.2 was fence-blind, so a Python comment inside a required
    section truncated the section and corrupted ~38 validators).
    LEVEL-aware (R6 blind-operator audit): a child heading (###) inside a
    parent section (##) is part of the parent's body - the parent closes only
    at the next heading of the SAME or HIGHER level. The old flat parser
    closed on ANY heading, so a normally-nested `### A1` made its populated
    parent read as empty and fail MD_SECTION_THIN. Every heading still gets
    its own entry (child titles stay directly findable), and entries keep
    document order (find_section's fallback depends on it)."""
    sections: dict[str, str] = {}
    open_secs: list[list] = []   # [title, level, buf]
    fence: str | None = None

    def _close(upto_level: int) -> None:
        while open_secs and open_secs[-1][1] >= upto_level:
            title, _level, buf = open_secs.pop()
            sections[title] = "\n".join(buf).strip()

    for line in text.splitlines():
        fm = _FENCE_RE.match(line)
        if fm:
            marker = fm.group(1)
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            for sec in open_secs:
                sec[2].append(line)
            continue
        m = None if fence is not None else re.match(r"^(#{1,6})\s+(.*?)\s*$", line)
        if m:
            level = len(m.group(1))
            _close(level)
            for sec in open_secs:
                sec[2].append(line)   # the child heading line is parent content
            title = re.sub(r"\s+", " ", m.group(2)).strip().lower()
            sections.setdefault(title, "")   # reserve the document-order slot
            open_secs.append([title, level, []])
        else:
            for sec in open_secs:
                sec[2].append(line)
    _close(0)
    return sections


def find_section(sections: dict[str, str], name: str) -> str | None:
    """Exact key, else the first heading (document order) containing every word
    of ``name`` as a whole word. v9.2 used substring containment, which let a
    required section bind to an unrelated heading ('setup' -> 'presetup')."""
    key = name.strip().lower()
    if key in sections:
        return sections[key]
    words = [w for w in re.split(r"\W+", key) if w]
    if not words:
        return None
    for k, v in sections.items():
        heading_words = set(re.split(r"\W+", k))
        if all(w in heading_words for w in words):
            return v
    return None
