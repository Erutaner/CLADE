"""Task-card rendering. Cards live in engine/cards/<type>.md with {{KEY}} placeholders.

The card IS the instruction set for the current task: role, why-now recap, inputs,
outputs, done-criteria. Cards are rendered fresh at task creation so instructions
arrive at time-of-use, not at time-of-skill-load.
"""
from __future__ import annotations

import re
from pathlib import Path

import econfig
import eutil

CARDS_DIR = Path(__file__).resolve().parent / "cards"

_PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


# Appended to every task card (not gates): the anti-drift stop discipline.
# Field observation (v7): sessions halted at arbitrary points because the
# operating agent treated any completed step as a natural pause. It is not.
# This text is the SAME four-point contract stated in evo.py, README and
# OPERATOR_PROMPT (v9.2's footer stated three points and contradicted them).
# One compact restatement per card (the full contract lives in
# OPERATOR_PROMPT.md); at ~190 bytes x every rendered card this footer is
# read more often than any other engine text, so it stays terse.
_CONTINUITY_FOOTER = """
## Stop discipline
Legal stops: a user GATE, DONE, WAITING on an external run, an open
interview question, or an explicit STOP-and-ask instruction in THIS card's
body (waiting for user-owned material or a user-only decision named there
is legitimate - do not burn attempts submitting without it). After an
ACCEPT, immediately run `next` - do not summarize, ask permission, or end
the session mid-run.
Before `submit`, `evo validate --task <id>` dry-runs the exact same
validators against your current output bytes - free, no attempt spent, no
state written (one disclosed exception: a formalizable theorize task
executes your own TOY_CHECK.py, as submit would). Use it instead of
guessing or reading engine code; a PASS is not an acceptance guarantee,
but every listed deficiency is real.
"""

# Interview-capable tasks may legitimately hold their task open while a
# concrete user answer is pending; their footer states that exception inline.
_INTERVIEW_TASKS = ("project_scan", "configure", "infra_interview")

_INTERVIEW_NOTE = """
This task conducts a USER INTERVIEW: if a concrete answer is missing, ask the
user and keep this task open while their answer is pending - that pause is
legitimate. Everything else in the stop discipline still applies.
"""


def render(card_type: str, mapping: dict[str, str]) -> str:
    path = CARDS_DIR / f"{card_type}.md"
    if not path.exists():
        raise SystemExit(f"[evo] missing card template {path}")
    text = eutil.read_text(path)

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in mapping:
            raise SystemExit(f"[evo] card '{card_type}' placeholder {{{{{key}}}}} has no value (engine bug)")
        return str(mapping[key])

    out = _PLACEHOLDER.sub(sub, text)
    if card_type != "gate":
        out = out.rstrip() + "\n" + _CONTINUITY_FOOTER
        if card_type in _INTERVIEW_TASKS:
            out = out.rstrip() + "\n" + _INTERVIEW_NOTE
    return out


def common_fields(store, st: dict, cfg: dict, task: dict) -> dict[str, str]:
    subj = task.get("subject", {})
    outputs = "\n".join(f"- `{o}`" for o in task.get("outputs", [])) or "- (none)"
    engine = Path(__file__).resolve().parent.as_posix()
    evo_cmd = f"python \"{engine}/evo.py\" --repo \"{store.repo.as_posix()}\""
    axes = ", ".join(econfig.resource_axes(cfg))
    return {
        "RESOURCE_AXES": axes,
        "RESOURCE_AXES_COUNT": str(len(econfig.resource_axes(cfg))),
        "TASK_ID": task["id"],
        "TASK_TYPE": task["type"],
        "REPO": store.repo.as_posix(),
        "ROUND": str(subj.get("round") or st.get("current_round") or "-"),
        "LANE": str(subj.get("lane") or "-"),
        "NODE": str(subj.get("node") or "-"),
        "ATTEMPT": str(task.get("attempts", 0) + 1),
        "MAX_ATTEMPTS": str(cfg.get("budgets", {}).get("max_attempts", 3)),
        "PROJECT_NAME": str(cfg.get("project", {}).get("name") or ""),
        "PROJECT_GOAL": str(cfg.get("project", {}).get("goal") or ""),
        "PRIMARY_METRIC": econfig.primary_metric(cfg),
        "OUTPUTS": outputs,
        "EVO": evo_cmd,
        "SUBMIT_CMD": f"{evo_cmd} submit --task {task['id']}" + (
            "\n(strict critic isolation is ON: the RELEASE direction - advance/ACCEPT/PROCEED/"
            "FAITHFUL - must be submitted from a NON-author session: append "
            "--session <your-distinct-session-id>)"
            if str((cfg.get("policy") or {}).get("critic_isolation") or "") == "strict"
            and task.get("type") in ("tournament", "red_team", "challenge", "fidelity")
            else "") + (
            "\n(strict critic isolation is ON: submit WITH --session <your-stable-session-id> - "
            "the release critic must later prove independence against your recorded identity; "
            "an unnamed author submission is rejected)"
            if str((cfg.get("policy") or {}).get("critic_isolation") or "") == "strict"
            and task.get("type") in ("sketch", "mature", "theorize", "implement")
            else ""),
        "BUNDLE_PATH": f".evo/tasks/{task['id']}/BUNDLE.md",
    }
