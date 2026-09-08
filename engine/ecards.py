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
# Field observation: sessions halted at arbitrary points because the
# operating agent treated any completed step as a natural pause. It is not.
# This text is the SAME four-point contract stated in evo.py, README and
# OPERATOR_PROMPT.
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

# Every side door the engine has, with the moment it is for. Each task card
# carries the doors that make sense from that task ("## Doors open from
# here"); `evo doors` prints the whole table. Knowing a door exists is part
# of the agent's job: work that belongs behind one must never be smuggled
# into a candidate, dropped, or reported as "the engine does not allow it".
_ALL = frozenset()
_LANE_TASKS = frozenset({"diagnose", "deep_read", "sketch", "tournament", "pose", "theorize",
                         "challenge", "mature", "red_team", "design_ablation", "review_ablation",
                         "probe_design", "maintenance_design", "maintenance_review", "plan_node"})
_NODE_TASKS = frozenset({"implement", "smoke", "fidelity", "ablation_fidelity", "metric_bridge",
                         "rehearsal", "stage_launch", "stage_watch", "eval_launch", "evaluate",
                         "conclude", "scientific_conclude"})
_STRATEGY_TASKS = frozenset({"open_round", "close_round", "evidence", "sota_scan"})
DOORS: tuple[tuple[str, str, str, frozenset], ...] = (
    ("validate", "evo validate --task <T####>",
     "before every submit: the same validators, read-only, no attempt spent - never read engine "
     "source to pre-validate", _ALL),
    ("amend", "evo amend --path <file> --from <edited copy> --reason \"...\"",
     "a NOTEBOOK line is wrong - a fact in a lane brief, an idea's prose, any part of a bet that has not "
     "launched yet (claim, scope, predictions, probe rule), a budget cap, a smoke/rehearsal command, an "
     "unlaunched stage command, a noise floor or margin in .evo/config.json: correct it on record (old "
     "bytes kept, reviewers see the history). Refused, each naming its exit: an idea's identity "
     "(program/kernel - that is a different idea), a bet that has launched (the refusal names the "
     "settlement door that applies), the comparator once the node exists, probe wiring once a build exists, and the spec's "
     "engine-owned copies (amend the idea meta; the engine propagates)", _ALL),
    ("ablate", "evo ablate --parent <N###> --question \"...\"",
     "a concluded node's causal status is DEFERRED and the engine did not open the ablation itself (it does "
     "after every program-level win in research mode, whatever the probe said, inside the project's "
     "allowance), the next bet depends on that kernel being the cause, or a refuted kernel's gain needs its "
     "real source found: settle it with one changed factor (remove, freeze, randomize - your design), one run "
     "by default; inside the allowance it resolves under the normal autonomy policy, above it the user decides",
     _LANE_TASKS | _STRATEGY_TASKS | frozenset({"conclude", "scientific_conclude"})),
    ("probe", "evo probe --parent <N###> --question \"...\"",
     "a MEASUREMENT, not a mechanism, would settle what to try next; ends in a recorded observation "
     "(manual gate, capped)", _LANE_TASKS | _STRATEGY_TASKS | frozenset({"conclude", "scientific_conclude"})),
    ("maintain", "evo maintain --parent <N###> --defect \"...\"",
     "shared execution code is mechanically broken and blocks work: repair with parity settled and "
     "semantics preserved (manual gate); a change meant to move numbers is a candidate instead",
     _LANE_TASKS | _STRATEGY_TASKS | _NODE_TASKS),
    ("correct-instrument", "evo correct-instrument --node <N###> --proposal <file.json>",
     "the FORMULA behind a probe's answer was wrong (a unit mismatch, an imported constant - not a "
     "threshold you dislike): an independent session judges, the user decides, the SAME sealed "
     "observations are re-settled into probe_result; parenthood does not move. Symmetric: a wrong "
     "formula in a passing probe too",
     frozenset({"conclude", "scientific_conclude", "evaluate", "close_round", "open_round"})),
    ("claim", "evo claim --node <N###> --proposal <file.json>",
     "a concluded node's LINE was set too high or scoped to the wrong cells - the numbers are real, the "
     "bet was mispriced: file a new claim priced with the data in hand (labeled post-hoc, settled from "
     "the sealed metrics, the user decides); the original bet stays on record. Not for a wrong formula "
     "(correct-instrument) or a wrong fact (amend)",
     frozenset({"conclude", "scientific_conclude", "evaluate", "close_round", "open_round"})),
    ("propose-abandon", "evo propose-abandon --lane <L###>|--node <N###> --reason \"...\"",
     "you judge an ADMITTED direction dead ('the mechanism cannot work here', not 'this is slow'): "
     "the user decides at a gate; nothing blocks meanwhile", _LANE_TASKS | _NODE_TASKS),
    ("run facts", "evo run-bind | run-update | run-confirm-not-launched | run-reconcile",
     "the external job's facts: bind the one accepted job, report how it ended, resolve an unknown "
     "launch, attach late evidence to the SAME run (a missing file never authorizes a relaunch)",
     frozenset({"stage_launch", "stage_watch", "eval_launch", "evaluate", "rehearsal", "conclude"})),
    ("hold / recover-plan", "evo hold --scope <...> --reason \"...\"; evo recover-plan --target <...> --boundary <...>",
     "an already-ACCEPTED authority (spec, implementation, evaluation, conclusion) was itself wrong: "
     "brake first, plan the re-judgment, and show the plan to the user BEFORE recover-apply - this "
     "door has no engine-side gate", _ALL),
    ("user-only verbs", "evo decide | revive | waive-repeat | rebind-artifact | revise-infra | autonomy",
     "decisions only the human records: present the engine's report verbatim and wait; never run "
     "them on the human's behalf", _ALL),
)


def doors_for(task_type: str) -> list[str]:
    """The doors block for one task card."""
    rows = [f"- **{name}** - `{cmd}`: {when}"
            for name, cmd, when, scope in DOORS if not scope or task_type in scope]
    return ["## Doors open from here",
            "Side channels this task may need. `evo doors` prints the whole table with the moment "
            "each is for; using one is never a protocol violation, smuggling its work into this "
            "task is."] + rows


def doors_table() -> list[str]:
    out = ["Every side door the engine has, and the moment it is for. Each task card repeats the",
           "ones that matter from that task; the full contract lives in OPERATOR_PROMPT.md.", ""]
    for name, cmd, when, _scope in DOORS:
        out.append(f"{name}")
        out.append(f"    {cmd}")
        out.append(f"    when: {when}")
        out.append("")
    return out


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
        out = out.rstrip() + "\n\n" + "\n".join(doors_for(card_type)) + "\n" + _CONTINUITY_FOOTER
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
