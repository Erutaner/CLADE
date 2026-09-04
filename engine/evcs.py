"""Git integration: branch <-> DAG mapping.

Mapping contract:
  - graph.json is the source of truth for the SEMANTIC DAG (all parents,
    including conceptual/mechanism parents of hybrids and consumed platforms).
  - git branch ancestry mirrors the CODE-inheritance chain only: every
    non-baseline node's branch must descend from its code_parent's recorded
    commit. Hybrids inherit code from exactly one parent (code_parent); the
    other parents contribute mechanisms, not history.
  - branch naming: evo/<node-id-lower>-<slug>; the engine assigns it at node
    creation and validates it at implement time.
  - node.commit records HEAD of the node's workdir after implement/smoke, so
    evaluations are traceable to exact code states.

Convenience helpers degrade gracefully (None/False on failure); the
``_git_integrity`` family never collapses an operational failure into a
substantive answer, and retries transient Windows conditions (worktree
remove/re-add windows, antivirus handle locks) with a bounded backoff.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path


class GitCheckError(RuntimeError):
    """Git could not establish an integrity fact after bounded retries."""


# --------------------------------------------------------------------------- invocation-scoped memo
# Within ONE engine invocation (one CLI command / one Engine method call) the
# engine provably never mutates a worktree - every transition write lands under
# .evo (v10.2b audit, re-verified: evcs contains only read-only git commands and
# no engine code writes workarea bytes). Repeating an identical probe inside the
# same invocation therefore returns the same answer by construction; across
# invocations the cache MUST die, because out-of-band edits between commands are
# exactly what the sweeps exist to catch. esched.Engine clears this at
# construction and at every public entry point (submit/compute_next/decide/...).
_INVOCATION_CACHE: dict[tuple[str, str], object] = {}


def begin_invocation() -> None:
    """Reset the per-invocation git-fact memo (see comment above)."""
    _INVOCATION_CACHE.clear()


def _cached(kind: str, workdir: Path, compute):
    key = (kind, str(workdir))
    if key not in _INVOCATION_CACHE:
        _INVOCATION_CACHE[key] = compute()
    return _INVOCATION_CACHE[key]


class GitWorkdirMissingError(GitCheckError):
    """The audited workdir directory does not exist at all.

    Callers must treat this as its own typed condition: v9.2 collapsed it into
    a generic git failure, so a worktree in its legal remove/re-add window (or
    removed by an authorized revision) nondeterministically killed unrelated
    full-graph seal sweeps.
    """


def _git(cwd: Path, *args: str, input_text: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(cwd), *args],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=60, input=input_text)
        stdout = (p.stdout or "").strip()
        stderr = (p.stderr or "").strip()
        return p.returncode, stdout if p.returncode == 0 else (stderr or stdout)
    except subprocess.TimeoutExpired:
        return 124, "git command timed out after 60 seconds"
    except OSError as exc:
        return 127, f"could not start git: {exc}"


def ignored_paths(workdir: Path, rels: list[str]) -> set[str]:
    """The subset of ``rels`` that gitignore rules currently classify as
    ignored (pattern-level: works for deleted paths too).

    R8/N003 audit: manifest construction hashes on-disk gitignored files
    (they are in neither the tracked set nor the non-ignored untracked set),
    yet a per-launch runtime bookkeeping file is EXPECTED to change on every
    stage - freezing it wedged the node on a mutated-closure report with no
    repair verb. The audit side needs this classification to demote exactly
    those rows to advisory. rc 0 (some ignored) and rc 1 (none ignored) are
    both substantive answers; anything else raises via the integrity path."""
    wanted = sorted({str(r) for r in rels if str(r)})
    if not wanted:
        return set()
    if not workdir.exists():
        raise GitWorkdirMissingError(
            f"workdir {workdir} does not exist; gitignore classification cannot run there")

    def compute() -> set[str]:
        rc, out = _git(workdir, "check-ignore", "--stdin", "-z",
                       input_text="\0".join(wanted) + "\0")
        if rc not in (0, 1):
            raise GitCheckError(f"git check-ignore failed (rc={rc}): {out}")
        if rc == 1 or not out:
            return set()
        return {p.replace("\\", "/") for p in out.split("\0") if p}

    # ignore RULES are worktree bytes (.gitignore) - immutable within one
    # engine invocation like every other memoized git fact here.
    return _cached("check-ignore:" + "\0".join(wanted), workdir, compute)


def _git_integrity(cwd: Path, *args: str, valid_rcs: tuple[int, ...] = (0,)) -> tuple[int, str]:
    """Run a safety-critical Git query, retrying only operational failures.

    A diff return code of 1 is a valid, substantive answer when explicitly
    admitted by ``valid_rcs``.  Other nonzero codes mean the check itself did
    not run reliably; they must never be collapsed into either clean or dirty.
    A missing workdir raises the typed :class:`GitWorkdirMissingError` so the
    caller can distinguish "directory gone" from "repository corrupt".
    """
    if not cwd.exists():
        raise GitWorkdirMissingError(
            f"workdir {cwd} does not exist; git integrity checks cannot run there")
    last_rc, last_detail = -1, ""
    for attempt in range(3):
        rc, detail = _git(cwd, *args)
        if rc in valid_rcs:
            return rc, detail
        last_rc, last_detail = rc, detail
        if not cwd.exists():
            raise GitWorkdirMissingError(
                f"workdir {cwd} disappeared during a git integrity check")
        # Transient Windows conditions (index.lock held by another git,
        # antivirus/indexer handles) resolve within a short backoff.
        time.sleep(0.15 * (attempt + 1))
    command = "git " + " ".join(args)
    raise GitCheckError(
        f"{command} failed {3} times (rc={last_rc}): {last_detail or 'no diagnostic output'}")


def is_git_repo(path: Path) -> bool:
    rc, out = _git(path, "rev-parse", "--is-inside-work-tree")
    return rc == 0 and out == "true"


def worktree_root(workdir: Path, *, strict: bool = False) -> Path | None:
    """Return the Git worktree root containing ``workdir``."""
    if strict:
        rc, out = _git_integrity(workdir, "rev-parse", "--show-toplevel")
    else:
        rc, out = _git(workdir, "rev-parse", "--show-toplevel")
    return Path(out) if rc == 0 and out else None


def head_branch(workdir: Path) -> str | None:
    rc, out = _git(workdir, "rev-parse", "--abbrev-ref", "HEAD")
    return out if rc == 0 and out else None


def head_commit(workdir: Path, *, strict: bool = False) -> str | None:
    if strict:
        commit, _clean, _untracked = status_facts(workdir)
        return commit

    def compute():
        rc, out = _git(workdir, "rev-parse", "HEAD")
        return out if rc == 0 and out else None
    return _cached("head_loose", workdir, compute)


def status_facts(workdir: Path) -> tuple[str, bool, list[str]]:
    """(head_commit, tracked_tree_clean, untracked_files) in ONE subprocess.

    ``git status --porcelain=v2 --branch`` answers, from documented plumbing
    output, everything the audit used to spawn three processes for: the
    ``# branch.oid`` header equals ``rev-parse HEAD``; any ``1 ``/``2 ``/``u ``
    entry means tracked working bytes or the index differ from HEAD (the exact
    semantics of the two ``diff --quiet`` probes, index bits honored the same
    way); ``? `` entries are the non-ignored untracked list. ``(initial)``
    (unborn HEAD) maps to the same fail-closed GitCheckError the old
    ``rev-parse HEAD`` produced as rc!=0. ``--no-optional-locks`` keeps the
    probe read-only like the diffs it replaces.
    """
    def compute():
        rc, out = _git_integrity(
            workdir, "--no-optional-locks", "status", "--porcelain=v2", "--branch",
            "--untracked-files=all", "--ignore-submodules")
        head = ""
        clean = True
        untracked: list[str] = []
        for line in out.splitlines():
            if line.startswith("# branch.oid "):
                head = line.split(" ", 2)[2].strip()
            elif line.startswith(("1 ", "2 ", "u ")):
                clean = False
            elif line.startswith("? "):
                untracked.append(line[2:].strip().replace("\\", "/"))
        if not head or head == "(initial)":
            raise GitCheckError(
                f"git status reported no commit oid for {workdir} (unborn or corrupt HEAD)")
        return head, clean, sorted(untracked)
    return _cached("status", workdir, compute)


def integrity_facts(workdir: Path) -> tuple[Path | None, str | None, bool]:
    """Strict (worktree_root, head_commit, tracked_tree_clean) in <=2 subprocesses.

    The root comes from one (memoized) ``rev-parse --show-toplevel``; commit and
    cleanliness come from the single ``status --porcelain=v2`` probe. The audit
    used to pay 3 spawns per node per sweep; on Windows the spawn itself is the
    dominant cost (~25 ms each).
    """
    root = _cached("toplevel", workdir, lambda: worktree_root(workdir, strict=True))
    commit, clean, _untracked = status_facts(workdir)
    return root, commit, clean


def tracked_tree_clean(workdir: Path) -> bool:
    """True when neither tracked working bytes nor the index differ from HEAD."""
    _commit, clean, _untracked = status_facts(workdir)
    return clean


def tracked_file_flags(workdir: Path) -> dict[str, str]:
    """{repo-relative path: ls-files status letter} for every tracked file.

    One spawn yields two facts the closure audit needs: the TRACKED SET (a
    manifest row absent from it is gitignored - SOURCE-suffixed rows keep
    their byte hash; non-source ignored rows are enforced as advisory since
    the R8/N003 fix, see implementation_manifest_errors), and the per-file
    index bits - a lowercase letter (assume-unchanged) or ``S``
    (skip-worktree) makes ``git diff``/``status`` blind to real edits of that
    file, which is exactly the spoof the v10.2b audit demonstrated. Callers
    fall back to full byte hashing when any suspicious letter appears.
    """
    def compute():
        rc, out = _git_integrity(workdir, "ls-files", "-v")
        flags: dict[str, str] = {}
        for line in out.splitlines():
            if len(line) > 2:
                flags[line[2:].strip().replace("\\", "/")] = line[0]
        return flags
    return _cached("lsfiles", workdir, compute)


def changed_files_since(workdir: Path, base_commit: str) -> list[str]:
    """Repo-relative paths this worktree changed relative to ``base_commit``.

    Asked of Git rather than by hashing two checkouts: line-ending
    normalization (core.autocrlf) makes raw bytes differ between two working
    trees of the SAME commit, so a byte diff across checkouts reports files
    nobody touched.  Includes staged and unstaged work plus non-ignored new
    files, so a boundary audit cannot be dodged by leaving the edit uncommitted.
    """
    rc, out = _git_integrity(workdir, "diff", "--name-only", base_commit, valid_rcs=(0,))
    changed = [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]
    return sorted(set(changed) | set(untracked_files(workdir)))


def untracked_files(workdir: Path) -> list[str]:
    """Repo-relative, non-ignored untracked paths (used to reject late code)."""
    _commit, _clean, untracked = status_facts(workdir)
    return list(untracked)


def branch_exists(repo: Path, name: str) -> bool:
    rc, _ = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")
    return rc == 0


def is_ancestor(repo: Path, ancestor_ref: str, descendant_ref: str) -> bool:
    """rc=1 is the substantive 'not an ancestor'; any other failure raises.

    v9.2 collapsed bad refs, timeouts and a missing git binary into "not an
    ancestor", turning operational failures into spurious ancestry-violation
    verdicts.
    """
    rc, _ = _git_integrity(repo, "merge-base", "--is-ancestor",
                           ancestor_ref, descendant_ref, valid_rcs=(0, 1))
    return rc == 0
