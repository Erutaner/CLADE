"""Declarative control-plane tables (v10).

v9.2 encoded the flow topology four times: in scheduler if-chains, in the
validator registry, in per-transition apply code, and again by hand inside
doctor. The copies drifted; a legal-but-unhandled status was a runtime crash.

v10 states the topology once, as data, and proves it total at import/check
time:

* ``LANE_FLOW`` / ``NODE_FLOW``: one entry per persisted lane/node status.
* ``ROUTE_SEQUENCES``: the enforced temporal order of each search origin.
* ``TASK_TYPES``: every issuable task type and its card template.
* ``GATE_POLICY``: one entry per gate kind - who may resolve it and how.

Consumption map (kept HONEST - every named table has a live consumer):
``LANE_FLOW``/``NODE_FLOW``/``TASK_TYPES``/``GATE_POLICY`` are proven total
against the econfig vocabularies and the card directory by ``check_tables``
(run by edoctor and the unit tests, which additionally assert congruence
between these tables and the explicit dispatch branches in etask/esched);
``GATE_POLICY`` drives egate's protection/auto-resolve decisions;
``TASK_TYPES[..].card`` is the card-template registry used by etask;
``LANE_STAGE_ORDER`` orders lane scheduling in esched; ``BOOTSTRAP_SEQ``
derives the protected-task set in esched._reject; ``INSTRUMENTAL_SEQ`` gives
eapply the entry status of an instrumental lane, egate the only stage such a
lane may be rewound to, and edoctor the statuses it may legally hold.
Dispatch itself remains
explicit, reviewed branch code - the tables are its checked contract, not a
runtime indirection layer.

This module depends only on ``econfig`` vocabularies. Implementing modules
import it; it never imports them.
"""
from __future__ import annotations

from dataclasses import dataclass

import econfig

# --------------------------------------------------------------------------- steps
# Step kinds:
#   task     - the status issues (or re-presents) exactly one agent task.
#   gate     - the status is owned by a user/engine gate lifecycle handler.
#   delegate - another flow drives (a lane whose node pipeline is running).
#   wait     - engine-side wait; the scheduler may look elsewhere for work.
#   terminal - no further scheduling for this owner.

STEP_KINDS = ("task", "gate", "delegate", "wait", "terminal")


@dataclass(frozen=True)
class Step:
    kind: str
    # For kind == "task": the task type this status issues. ``handler`` is a
    # descriptive label for composite/wait/gate steps (documentation only; the
    # dispatch code is explicit and congruence-tested).
    task_type: str | None = None
    handler: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in STEP_KINDS:
            raise ValueError(f"unknown step kind {self.kind!r}")
        if self.kind == "task" and not self.task_type:
            raise ValueError("task step needs task_type")


# --------------------------------------------------------------------------- lane flow
# One entry per persisted lane status (econfig.LANE_STATUSES). The builders /
# handlers named here are registered by etask/esched at import.

LANE_FLOW: dict[str, Step] = {
    "diagnose":        Step("task", task_type="diagnose"),
    "deep_read":       Step("task", task_type="deep_read"),
    "sketch":          Step("task", task_type="sketch"),
    "tournament":      Step("task", task_type="tournament"),
    "pose":            Step("task", task_type="pose"),
    "theorize":        Step("task", task_type="theorize"),
    "challenge":       Step("task", task_type="challenge"),
    "mature":          Step("task", task_type="mature"),
    "red_team":        Step("task", task_type="red_team"),
    "ablation_design": Step("task", task_type="design_ablation"),
    "ablation_review": Step("task", task_type="review_ablation"),
    "probe_design":    Step("task", task_type="probe_design"),
    "maintenance_design": Step("task", task_type="maintenance_design"),
    "maintenance_review": Step("task", task_type="maintenance_review"),
    "gate":            Step("gate", handler="lane_idea_gate"),
    "approved":        Step("task", task_type="plan_node"),
    "node_created":    Step("delegate", handler="lane_node_pipeline"),
    "done":            Step("terminal"),
    "abandoned":       Step("terminal"),
}

# --------------------------------------------------------------------------- node flow
# One entry per persisted node status (econfig.NODE_STATUSES). Statuses whose
# next task depends on sub-state (pending fidelity/bridge flags, workflow
# cursor, eval progress) use a named composite handler; the handler is still
# registered and totality-checked.

NODE_FLOW: dict[str, Step] = {
    "proposed":         Step("task", task_type="baseline_spec"),   # baseline only; lanes plan via plan_node
    "approved":         Step("task", task_type="implement", handler="node_approved"),
    "building":         Step("task", task_type="smoke", handler="node_building"),
    "smoke_pass":       Step("task", task_type="stage_launch", handler="node_pre_stage"),
    "bridge_pass":      Step("task", task_type="stage_launch", handler="node_pre_stage"),
    "stage_ready":      Step("task", task_type="stage_launch", handler="node_pre_stage"),
    "executing":        Step("wait", handler="node_run_in_flight"),
    "evaluating":       Step("wait", handler="node_run_in_flight"),
    "evidence_pending": Step("wait", handler="node_run_in_flight"),
    "workflow_done":    Step("task", task_type="eval_launch", handler="node_workflow_done"),
    "evaluated":        Step("task", task_type="conclude"),
    "scientific_stop":  Step("task", task_type="scientific_conclude"),
    "concluded":        Step("terminal"),
    "abandoned":        Step("terminal"),
}

# Scheduling priority: most-advanced lane first (higher = later pipeline stage).
LANE_STAGE_ORDER: dict[str, int] = {
    "diagnose": 0, "deep_read": 1, "sketch": 2,
    "tournament": 3, "pose": 4, "theorize": 5, "challenge": 6,
    "mature": 7, "ablation_design": 7, "probe_design": 7, "maintenance_design": 7,
    "red_team": 8, "ablation_review": 8, "maintenance_review": 8, "gate": 9, "approved": 10,
    "node_created": 11,
}

# --------------------------------------------------------------------------- bootstrap
BOOTSTRAP_SEQ: tuple[str, ...] = (
    "project_scan", "provision", "configure", "infra", "infra_interview", "infra_drill",
    "profile", "dossier", "rubric", "sota_scan",
)

# v11: tasks whose subject has ALREADY paid its full compute by the time they
# run. Abandoning one over report formatting destroys a trained node and its
# sealed evidence - the survival audit's single most disproportionate death.
# They are protected from on_stuck=abandon (a stuck one escalates instead) and
# their escalation gates stay MANUAL even under full_auto+abandon: an
# auto-reject would abandon the node anyway, defeating the protection.
EXPENSIVE_TERMINAL_TASKS: tuple[str, ...] = ("evaluate", "conclude", "scientific_conclude")

# --------------------------------------------------------------------------- routes
# The enforced temporal order per search origin (lane statuses in order).
# ``deep_read`` appears twice on repair (pre-sketch priors, post-freeze
# collision audit) and core_synthesis (actual-work reconstruction, post-freeze
# audit); the scheduler distinguishes the passes by lane sub-state
# (reading_done / sketches_path), exactly as v9.2 did.

ROUTE_SEQUENCES: dict[str, tuple[str, ...]] = {
    "repair":         ("diagnose", "deep_read", "sketch", "deep_read", "tournament"),
    "constructive":   ("sketch", "deep_read", "tournament"),
    "core_synthesis": ("deep_read", "sketch", "deep_read", "tournament"),
    "theory_derived": ("pose", "theorize", "challenge", "sketch", "deep_read", "tournament"),
}
# After any route's tournament: [optional post-program theory] -> mature ->
# red_team -> gate -> approved -> node_created. Targeted ablation uses
# ablation_design -> ablation_review -> gate -> approved -> node_created.
POST_TOURNAMENT_SEQ: tuple[str, ...] = ("mature", "red_team", "gate", "approved", "node_created")
ABLATION_SEQ: tuple[str, ...] = ("ablation_design", "ablation_review", "gate", "approved", "node_created")
# Instrumental purposes (v10.2): same idea-gate-node rail, lighter admission.
# A probe's protection is its manual user gate + budget cap, so it carries no
# separate review stage; maintenance keeps an adversarial review (novelty
# smuggling / parity risk) before the user gate.
PROBE_SEQ: tuple[str, ...] = ("probe_design", "gate", "approved", "node_created")
MAINTENANCE_SEQ: tuple[str, ...] = ("maintenance_design", "maintenance_review", "gate", "approved", "node_created")

# One purpose -> one route.  Three facts used to be spelled out separately per
# purpose - the status a lane ENTERS at (eapply._lane_entry_status), the stage a
# user-rejected lane may rewind to (egate), and the statuses that lane may
# legally hold (edoctor) - so adding a purpose meant finding all three.  It also
# invited the inverse-of-candidate idiom ("purpose != targeted_ablation" to mean
# "is candidate"), which quietly broke the moment a third purpose existed.
# Stating the routes once makes "is instrumental" a lookup and the entry stage a
# derivation.
INSTRUMENTAL_SEQ: dict[str, tuple[str, ...]] = {
    "targeted_ablation": ABLATION_SEQ,
    "diagnostic_probe": PROBE_SEQ,
    "maintenance": MAINTENANCE_SEQ,
}

# --------------------------------------------------------------------------- tasks
@dataclass(frozen=True)
class TaskDef:
    """One issuable task type: its card template (must exist under
    engine/cards/) and whether it is an engine-internal placeholder exempt
    from the validator-registry requirement (stage_watch)."""
    card: str
    special: bool = False


TASK_TYPES: dict[str, TaskDef] = {
    # bootstrap
    "project_scan":       TaskDef(card="project_scan"),
    "configure":          TaskDef(card="configure"),
    "infra":              TaskDef(card="infra"),
    "infra_interview":    TaskDef(card="infra_interview"),
    "infra_drill":        TaskDef(card="infra_drill"),
    "profile":            TaskDef(card="profile"),
    "dossier":            TaskDef(card="dossier"),
    "rubric":             TaskDef(card="rubric"),
    "sota_scan":          TaskDef(card="sota_scan"),
    "baseline_spec":      TaskDef(card="baseline_spec"),
    "provision":          TaskDef(card="provision"),
    "rehearsal":          TaskDef(card="rehearsal"),
    # rounds / lanes
    "open_round":         TaskDef(card="open_round"),
    "evidence":           TaskDef(card="evidence"),
    "diagnose":           TaskDef(card="diagnose"),
    "deep_read":          TaskDef(card="deep_read"),
    "sketch":             TaskDef(card="sketch"),
    "tournament":         TaskDef(card="tournament"),
    "pose":               TaskDef(card="pose"),
    "theorize":           TaskDef(card="theorize"),
    "challenge":          TaskDef(card="challenge"),
    "mature":             TaskDef(card="mature"),
    "red_team":           TaskDef(card="red_team"),
    "design_ablation":    TaskDef(card="design_ablation"),
    "review_ablation":    TaskDef(card="review_ablation"),
    "probe_design":       TaskDef(card="probe_design"),
    "maintenance_design": TaskDef(card="maintenance_design"),
    "maintenance_review": TaskDef(card="maintenance_review"),
    "close_round":        TaskDef(card="close_round"),
    # nodes
    "plan_node":          TaskDef(card="plan_node"),
    "implement":          TaskDef(card="implement"),
    "smoke":              TaskDef(card="smoke"),
    "fidelity":           TaskDef(card="fidelity"),
    "ablation_fidelity":  TaskDef(card="ablation_fidelity"),
    "metric_bridge":      TaskDef(card="metric_bridge"),
    "stage_launch":       TaskDef(card="stage_launch"),
    "stage_watch":        TaskDef(card="stage_watch", special=True),
    "eval_launch":        TaskDef(card="eval_launch"),
    "evaluate":           TaskDef(card="evaluate"),
    "conclude":           TaskDef(card="conclude"),
    "scientific_conclude": TaskDef(card="scientific_conclude"),
}


# --------------------------------------------------------------------------- gates
# ``protected`` gates are user-owned under every autonomy mode (full_auto may
# at most REJECT provision_blocked deterministically - an unattended run cannot
# supply missing resources). ``auto`` names a policy id interpreted by egate;
# policies are data here so doctor/tests can audit the whole table.

@dataclass(frozen=True)
class GatePolicy:
    protected: bool
    # auto policy id: "never" | "full_auto_approve" | "auto_or_full_approve"
    #   | "workflow_cost" | "round_continue" | "escalation_on_stuck"
    #   | "provision_full_auto_reject"
    auto: str
    # subjects that force manual decision even when auto would apply
    manual_when: tuple[str, ...] = ()


GATE_POLICY: dict[str, GatePolicy] = {
    "infra_confirm":        GatePolicy(protected=True,  auto="never"),
    "infra_canary_blocked": GatePolicy(protected=True,  auto="never"),
    "provision_blocked":    GatePolicy(protected=True,  auto="provision_full_auto_reject"),
    # v11.7: fit questions NEED a human in every mode - an unattended run
    # never proceeds past (or overrides) an unfit assessment on its own.
    "engine_fit_blocked":   GatePolicy(protected=True,  auto="never"),
    "infra_revision":       GatePolicy(protected=True,  auto="never"),
    "resource_approval":    GatePolicy(protected=True,  auto="never"),
    "repeat_spend":         GatePolicy(protected=True,  auto="never"),
    # v11.1 P4: buying back one measurement spends a training run - user-owned.
    "repeat_measure":       GatePolicy(protected=True,  auto="never"),
    "idea_approval":        GatePolicy(protected=False, auto="auto_or_full_approve",
                                       manual_when=("targeted_ablation", "diagnostic_probe", "maintenance",
                                                    "exploratory")),
    "workflow_approval":    GatePolicy(protected=False, auto="workflow_cost",
                                       manual_when=("targeted_ablation", "diagnostic_probe", "maintenance",
                                                    "exploratory")),
    "round_continue":       GatePolicy(protected=False, auto="round_continue"),
    "human_study_confirm":  GatePolicy(protected=True,  auto="never"),
    "escalation":           GatePolicy(protected=False, auto="escalation_on_stuck"),
    # Deliberate abandonment spends nothing but discards admitted work - the
    # user owns that call in every autonomy mode.
    "abandon_request":      GatePolicy(protected=True,  auto="never"),
}

AUTO_POLICY_IDS = {
    "never", "full_auto_approve", "auto_or_full_approve", "workflow_cost",
    "round_continue", "escalation_on_stuck", "provision_full_auto_reject",
}


# --------------------------------------------------------------------------- totality
def check_tables(*, cards_dir=None, validators=None) -> list[str]:
    """Prove the declarative tables total and mutually consistent.

    Run by edoctor and the unit tests. ``validators`` is the live dispatch
    registry (evalid.VALIDATORS); when given, every non-special task type must
    have an entry - the check runs against what submit actually uses, so the
    proof cannot drift from the implementation.
    """
    errs: list[str] = []
    for status in econfig.LANE_STATUSES:
        if status not in LANE_FLOW:
            errs.append(f"FLOW_LANE_STATUS_UNHANDLED: {status!r} has no LANE_FLOW step")
    for status in LANE_FLOW:
        if status not in econfig.LANE_STATUSES:
            errs.append(f"FLOW_LANE_STATUS_UNKNOWN: LANE_FLOW names unknown status {status!r}")
    for status in econfig.NODE_STATUSES:
        if status not in NODE_FLOW:
            errs.append(f"FLOW_NODE_STATUS_UNHANDLED: {status!r} has no NODE_FLOW step")
    for status in NODE_FLOW:
        if status not in econfig.NODE_STATUSES:
            errs.append(f"FLOW_NODE_STATUS_UNKNOWN: NODE_FLOW names unknown status {status!r}")

    for table_name, table in (("LANE_FLOW", LANE_FLOW), ("NODE_FLOW", NODE_FLOW)):
        for status, step in table.items():
            if step.kind == "task" and step.task_type not in TASK_TYPES:
                errs.append(f"FLOW_TASK_UNKNOWN: {table_name}[{status!r}] issues "
                            f"unregistered task type {step.task_type!r}")

    for origin in econfig.SEARCH_ORIGINS:
        if origin not in ROUTE_SEQUENCES:
            errs.append(f"FLOW_ROUTE_MISSING: search origin {origin!r} has no route sequence")
    for origin, seq in ROUTE_SEQUENCES.items():
        if origin not in econfig.SEARCH_ORIGINS:
            errs.append(f"FLOW_ROUTE_UNKNOWN: route table names unknown origin {origin!r}")
        for status in seq + POST_TOURNAMENT_SEQ + ABLATION_SEQ + PROBE_SEQ + MAINTENANCE_SEQ:
            if status not in econfig.LANE_STATUSES:
                errs.append(f"FLOW_ROUTE_STATUS: route/{origin} names unknown lane status {status!r}")

    # Total both ways: a purpose with no route would enter a lane at a status
    # nothing schedules, and a route for an unknown purpose is a dead branch
    # that reviewers would read as live coverage.
    for purpose in econfig.INSTRUMENTAL_PURPOSES:
        if purpose not in INSTRUMENTAL_SEQ:
            errs.append(f"FLOW_INSTRUMENTAL_ROUTE_MISSING: instrumental purpose {purpose!r} has no route")
    for purpose, seq in INSTRUMENTAL_SEQ.items():
        if purpose not in econfig.INSTRUMENTAL_PURPOSES:
            errs.append(f"FLOW_INSTRUMENTAL_ROUTE_UNKNOWN: route table names non-instrumental "
                        f"purpose {purpose!r}")
        if seq[-3:] != ("gate", "approved", "node_created"):
            errs.append(f"FLOW_INSTRUMENTAL_TAIL: route/{purpose} must end at the manual user gate "
                        f"and node creation, got {seq[-3:]}")

    # The injectable subset (rides on top of the portfolio, mid-round intake)
    # must partition INSTRUMENTAL_PURPOSES with targeted_ablation, and every
    # injectable purpose needs a real budget cap key: these facts used to live
    # as literal tuples at four validator sites with nothing proving them.
    for purpose in econfig.INSTRUMENTAL_PURPOSES:
        if purpose != "targeted_ablation" and purpose not in econfig.INJECTABLE_PURPOSES:
            errs.append(f"FLOW_INJECTABLE_MISSING: instrumental purpose {purpose!r} is neither "
                        "targeted_ablation nor injectable - it could not enter any round")
    for purpose in econfig.INJECTABLE_PURPOSES:
        if purpose not in econfig.INSTRUMENTAL_PURPOSES or purpose == "targeted_ablation":
            errs.append(f"FLOW_INJECTABLE_UNKNOWN: injectable purpose {purpose!r} is not an "
                        "on-top instrumental purpose")
        cap_key = econfig.INJECTABLE_CAP_KEYS.get(purpose)
        if not cap_key or cap_key not in (econfig.merged_default().get("budgets") or {}):
            errs.append(f"FLOW_INJECTABLE_CAP: injectable purpose {purpose!r} has no default "
                        f"budget cap key (got {cap_key!r})")
    if set(econfig.INJECTABLE_CAP_KEYS) != set(econfig.INJECTABLE_PURPOSES):
        errs.append("FLOW_INJECTABLE_CAP_KEYS: INJECTABLE_CAP_KEYS and INJECTABLE_PURPOSES disagree")

    # v11.1 P5: exploratory is a declared purpose, never instrumental/injectable
    # (it is a real search bet), and its gates must be user-owned - the duty
    # exemptions it buys make an auto-approved exploratory lane a rigor bypass.
    for purpose in econfig.EXPLORATORY_PURPOSES:
        if purpose not in econfig.EXPERIMENT_PURPOSES:
            errs.append(f"FLOW_EXPLORATORY_UNKNOWN: exploratory purpose {purpose!r} is not a "
                        "declared experiment purpose")
        if purpose in econfig.INSTRUMENTAL_PURPOSES or purpose in econfig.INJECTABLE_PURPOSES:
            errs.append(f"FLOW_EXPLORATORY_OVERLAP: {purpose!r} cannot be instrumental/injectable")
        for gk in ("idea_approval", "workflow_approval"):
            policy = GATE_POLICY.get(gk)
            if policy is None:
                # the totality loop below reports the missing entry; a bare
                # GatePolicy() fallback would TypeError (two required fields)
                # and kill the very diagnostic this table check exists for
                continue
            if purpose not in policy.manual_when:
                errs.append(f"FLOW_EXPLORATORY_GATE: GATE_POLICY[{gk!r}].manual_when must include "
                            f"{purpose!r} - exploratory gates are always user-owned")

    for kind in econfig.GATE_KINDS:
        if kind not in GATE_POLICY:
            errs.append(f"FLOW_GATE_UNPOLICIED: gate kind {kind!r} has no GATE_POLICY entry")
    for kind, policy in GATE_POLICY.items():
        if kind not in econfig.GATE_KINDS:
            errs.append(f"FLOW_GATE_UNKNOWN: GATE_POLICY names unknown gate kind {kind!r}")
        if policy.auto not in AUTO_POLICY_IDS:
            errs.append(f"FLOW_GATE_POLICY: gate {kind!r} names unknown auto policy {policy.auto!r}")

    if validators is not None:
        for name, td in TASK_TYPES.items():
            if not td.special and name not in validators:
                errs.append(f"FLOW_TASK_VALIDATOR_MISSING: task type {name!r} has no entry in the "
                            "live validator registry submit dispatches on")
    if cards_dir is not None:
        for name, td in TASK_TYPES.items():
            if not (cards_dir / f"{td.card}.md").is_file():
                errs.append(f"FLOW_CARD_MISSING: task type {name!r} card {td.card!r} not found")
        gate_card = cards_dir / "gate.md"
        if not gate_card.is_file():
            errs.append("FLOW_CARD_MISSING: gate card 'gate' not found")
    return errs
