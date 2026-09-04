"""Shared counted-check protocol for every fast suite.

Rules this file exists to enforce (v10.2a test audit):
- No bare ``assert`` in suites: under ``python -O`` asserts vanish and a suite
  silently becomes a no-op while still printing "passed".
- No ``check(True, ...)`` / ``ok(True, ...)``: a check that cannot fail is not
  a check; if the falsifier is "the call above raises", write nothing.
- Counts mean OWN-scope assertions: a suite reports what IT verified, never a
  helper's internal checks re-executed on its behalf.
"""
from __future__ import annotations

CHECKS = 0


def check(cond, msg: str) -> None:
    global CHECKS
    CHECKS += 1
    if not cond:
        raise AssertionError(f"[check {CHECKS}] {msg}")


def raises(fn, exc_type, msg: str, *, contains: str | None = None):
    """Assert fn() raises exc_type (optionally with a substring); returns it."""
    global CHECKS
    CHECKS += 1
    try:
        fn()
    except exc_type as exc:
        if contains is not None and contains not in str(exc):
            raise AssertionError(
                f"[check {CHECKS}] {msg}: raised {exc_type.__name__} but without "
                f"{contains!r}: {exc}") from exc
        return exc
    except Exception as exc:  # noqa: BLE001 - report the wrong type helpfully
        raise AssertionError(
            f"[check {CHECKS}] {msg}: raised {type(exc).__name__} instead of "
            f"{exc_type.__name__}: {exc}") from exc
    raise AssertionError(f"[check {CHECKS}] {msg}: did not raise {exc_type.__name__}")


def done(banner: str) -> None:
    print(f"{banner} GREEN: {CHECKS} checks passed")
