"""Config schema, defaults, and validation for .evo/config.json (v10)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

# ``search_origin`` describes how a candidate is generated; it is orthogonal
# to graph role, implementation scope, mechanism novelty and theory role.
SEARCH_ORIGINS = ["repair", "constructive", "core_synthesis", "theory_derived"]

LANE_INTENTS = ["exploit", "reform", "wildcat", "moonshot", "hybrid", "platform"]
INTENT_TO_ROLE = {
    "exploit": "variant",
    "reform": "variant",
    "wildcat": "root",
    "moonshot": "root",
    "hybrid": "hybrid",
    "platform": "platform",
}
# Every persisted lane status is enumerated so the scheduler fails closed.  A
# misspelled/new-but-unhandled status must never make a live lane disappear and
# allow its round to close.
LANE_STATUSES = [
    "diagnose", "deep_read", "pose", "theorize", "challenge",
    "sketch", "tournament", "mature", "red_team", "gate", "approved",
    "node_created", "done", "abandoned", "ablation_design", "ablation_review",
    "probe_design", "maintenance_design", "maintenance_review",
]
NODE_ROLES = ["baseline", "root", "variant", "hybrid", "platform"]
# NOTE: v9.2 carried a "fidelity_pass" value here that no code could ever
# set (a passed fidelity keeps smoke_pass and clears fidelity_pending); v10
# removes the dead value so the flow table cannot claim to handle fiction.
NODE_STATUSES = [
    "proposed", "approved", "building", "smoke_pass", "bridge_pass",
    "executing", "stage_ready", "workflow_done", "evaluating", "evaluated",
    "evidence_pending", "scientific_stop", "concluded", "abandoned",
]
# 'promising': a paradigm-replacing root (L4, no model parents) that reached
# resource-clean, mandatory-guardrail-settled parity with the baseline - it did
# not beat the frontier, but a fresh paradigm matching a long-optimized
# incumbent without buying parity through extra/unknown resources is evidence
# of headroom.
# 'dominant': every pre-registered improvement C# materially improves,
# every parity C# remains non-inferior, and the absolute efficiency threshold
# is met. Display choice has no role in this judgment.
NODE_VERDICTS = ["improved", "specialist", "tradeoff", "regressed", "inconclusive",
                 "promising", "dominant", "screened_out", "enabled", "failed", "baseline"]

# The evaluation contract separates how a number is computed from where it applies;
# an evaluation cell says WHERE/WHY that number participates in a decision.
# Keeping those separate supports arbitrary dataset<->task relationships without
# duplicating metric mathematics.
MODEL_SCOPES = ["single_checkpoint", "task_adapted", "portfolio"]
CELL_ROLES = ["target", "guardrail", "diagnostic"]
CLAIM_KINDS = ["generalist", "specialist", "efficiency"]
GROUP_AGGREGATIONS = ["all", "majority", "weighted_vote"]
SCALING_MODES = ["off", "reuse_only", "budgeted", "full"]
PROBE_MODES = ["same_run", "existing_artifact", "eval_intervention"]
# candidate: full novelty pipeline. targeted_ablation: causal diagnostic.
# diagnostic_probe (v10.2): a user/agent-initiated bounded measurement that
# answers ONE question; no novelty claim, never a parent, never on a frontier.
# maintenance (v10.2): an engineering repair of shared execution code with a
# parity contract; no novelty claim, frontier-transparent (proxies its parent).
# The last three share one firewall: they satisfy no research portfolio share
# and never earn scientific promotion - purposes gate WHAT WORK MAY CLAIM,
# and this axis is what lets instrumental work exist without a claim.
EXPERIMENT_PURPOSES = ["candidate", "targeted_ablation", "diagnostic_probe", "maintenance",
                       "exploratory"]

# Instrumental purposes: admitted outside the research candidate mix, always
# behind a manual idea gate, level 0, one exploit parent.
INSTRUMENTAL_PURPOSES = ("targeted_ablation", "diagnostic_probe", "maintenance")

# v11.1 P5: exploratory is a FOURTH species - a real search bet (full
# sketch -> tournament -> node route, ordinary portfolio slot, novelty duties
# intact) that declares UP FRONT it is reconnaissance: no registered
# predictions/theory/SOTA duties at mature, and in exchange its results are
# observations only - excluded from frontiers/records, promotion pinned
# not_applicable, no research-share credit, conclude must yield >= 1
# observation that a later CONFIRMATORY candidate may cite. It is NOT
# instrumental (it hunts novelty; instrumental work serves an existing node)
# and NOT injectable (it must be declared at round opening, always behind a
# manual gate). This is the honest fix for "pre-registration assumes
# foresight": scout first without corrupting the ledger, then confirm.
EXPLORATORY_PURPOSES = ("exploratory",)
# The instrumental purposes that ride ON TOP of the round's search-bet count
# and may enter mid-round (`evo probe`/`evo maintain`). targeted_ablation is
# instrumental but occupies an ordinary portfolio slot and is portfolio-only.
# This pair used to be spelled as a literal tuple at four validator sites with
# nothing proving totality - the exact shape that silently broke when the
# third purpose arrived. eflow.check_tables now proves: every instrumental
# purpose is either injectable or targeted_ablation, and every injectable
# purpose has a budget cap key that exists in the defaults.
INJECTABLE_PURPOSES = ("diagnostic_probe", "maintenance")
INJECTABLE_CAP_KEYS = {"diagnostic_probe": "probes_max_per_round",
                       "maintenance": "maintenance_max_per_round"}


def lane_purpose(row: dict) -> str:
    """The purpose of a lane/node record, reading a missing one as 'candidate'.

    The axis is mandatory at both intake doors, so a live record always carries
    it explicitly; records written before the axis existed do not, and the whole
    engine already treats those as candidates.  Callers must branch on the
    purpose they mean rather than on "not some other purpose": the inverse-of-
    candidate idiom was correct only while exactly two purposes existed, and
    silently captured the instrumental ones the moment a third was added.
    """
    return str(row.get("experiment_purpose") or "candidate")

# Structured taxonomy for infrastructure failure resolutions (the platform
# playbook routes on these, not on scientific lineage).
INFRA_SURFACES = ["artifact_io", "weights", "launch", "eval_adapter",
                  "service", "data_access", "environment", "other"]
TRAINING_REPLICATION_MODES = ["record_only", "preplanned"]
TRAINING_REPLICATION_AGGREGATIONS = ["none", "mean", "median"]
ABLATION_MODES = ["off", "targeted"]
STAGE_CONTROL_MODES = ["fixed", "preregistered_adaptive"]
# Stage multiplicity describes the method itself.  Training-seed repetition is
# a workflow execution dimension and must never be encoded as one unusually
# large seed-batched stage inside an otherwise single-run pipeline.
STAGE_MULTIPLICITIES = ["single", "algorithmic"]
STAGE_GATE_AGGREGATIONS = ["all", "any"]
STAGE_GATE_COMPARISONS = [">", ">=", "<", "<="]

# Who is this run for? The novelty regime differs by audience:
#   engineering: the goal is metric gains on a production-grade model. Borrowing
#     a genuinely-fitting published method is legitimate and encouraged; the
#     gate is non-triviality + diagnosed fit + argued transfer, NOT novelty
#     against the literature.
#   research: the goal is gains + novelty. Ideas must differ from the nearest
#     published work, portfolios carry a mandatory subsystem/full-program scope
#     share, and the independent mechanism/SOTA duties activate. The formal
#     problem ladder activates only for an actual theory claim.
PROJECT_MODES = ["engineering", "research"]

# What kind of experiment a node runs. train/finetune/data classes need a
# finite workflow. inference/api/analysis may be evaluation-only, or may declare
# workflow stages for bounded prompt search, decoding optimization, data
# transforms, and similar procedures. A stage is a scheduler-visible recovery
# and resource boundary, not a synonym for one gradient-training run.
EXPERIMENT_CLASSES = ["train", "finetune", "inference", "api", "data", "analysis"]
WORKFLOW_OPTIONAL_CLASSES = {"inference", "api", "analysis"}
RETIRE_REASONS = ["superseded", "pruned", "archived"]
COST_CLASSES = ["light", "medium", "heavy"]
AUTONOMY_MODES = ["gated", "auto", "full_auto"]
# ``full_auto`` covers ordinary idea/workflow/round gates. Bootstrap approval,
# targeted-ablation spend, resource-limit increases and ask-mode escalations
# remain user-owned; the name does not broaden the engine's authority.
GATE_KINDS = ["infra_confirm", "infra_canary_blocked", "resource_approval", "provision_blocked", "idea_approval",
              # v11.7: the engine-fit verdict (task-class admission + shape
              # assumptions) is user-owned - approve proceeds with the
              # assessment on record, reject stops bootstrap with the gap named.
              "engine_fit_blocked",
              # v11.7: a mid-run INFRA_FACTS revision is a user decision; the
              # approved revision re-arms the canary proof before new spend.
              "infra_revision",
              "workflow_approval", "repeat_spend", "round_continue", "escalation",
              # v11.1 P4: pre-registered on-the-line repeat. Opens only when a
              # registered repeat_rule fires (single measured delta inside the
              # band around a decision line); spends a training run, so it is
              # user-owned in every autonomy mode.
              "repeat_measure",
              # E2: settlement of a human-study cell is user-owned in every
              # autonomy mode - the sealed study import must be SEEN.
              "human_study_confirm",
              # v11: the honest early-exit verb. The agent may PROPOSE stopping
              # a lane/node it judges dead ("this direction cannot work") with
              # its reasons; the USER decides. Approve = deliberate stop with
              # the reason on record (not a failure statistic); reject = keep
              # going. Before this the cheapest legal exit from a doomed
              # direction was riding it to attempts-exhaustion - the largest
              # recoverable spend in the survival audit.
              "abandon_request"]

# Evaluation uncertainty is intentionally narrower than generic statistics.
# Both supported interval forms are computed from one fixed evaluation artifact
# and add zero training runs.  The separate, user-confirmed preplanned-training
# protocol may report every seed/run explicitly; it never masquerades as this
# sample-level uncertainty and is never inferred from mean/std/n.
UNCERTAINTY_METHODS = ["analytic", "fixed_predictions_bootstrap"]
UNCERTAINTY_UNITS = ["sample", "query", "episode", "case"]

# Project preparation (v11.7, replaces the v8 late bring-up): whether the
# supplied project needs CONSTRUCTIVE work before any contract can honestly be
# frozen is decided at project_scan (PROJECT_DISCOVERY.readiness) - a
# provision pass may wire data, build a minimal evaluation, and fix bugs until
# a first real number exists, and its observed facts feed configure/INFRA.
# Per-node full-chain rehearsal (v11.7): before a node's first full-scale RUN,
# one tiny real pass over the ENTIRE workflow (all stages + eval) on the real
# platform, with consumer-read proof of every produced artifact.
#   full_chain: rehearsal is a duty for every non-baseline node with stages
#               (enforced again at every launch against the implementation seal)
#   none:       the user explicitly waives it (local/cheap platforms)
REHEARSAL_MODES = ["full_chain", "none"]
LESSON_SCOPES = ["global", "lineage", "conditional"]
ARTIFACT_KINDS = ["weights", "dataset", "tokenizer", "index", "embedding", "report",
                  "prompt", "adapter", "config", "collection", "state",
                  # v10 (2025+ survey): procedural dataset generators with a
                  # deterministic sampling contract; stage-discovered programs
                  # (LLM-evolved code) promoted to implementations only through
                  # a follow-up node's normal implement path; interactive
                  # environment bundles (scene+physics) consumed as sandbox
                  # services; recorded external-service response caches that
                  # make live-API comparisons replayable.
                  "generator", "program", "environment", "service_snapshot",
                  "other"]

# ---- tempo presets ---------------------------------------------------------------
# One word owns the seven pacing/risk knobs below (policy.preset). Users pick a
# temperament instead of tuning coupled dials; hand-tuning any of them
# requires preset "custom" - a file that says "balanced" but carries divergent
# numbers is rejected (the file must not lie about the run's temperament).
PRESET_KEYS = ("wildcat_every_rounds", "stagnation_rounds", "stagnation_moonshot_rounds",
               "max_exploit_share", "research_min_structural_scope_share",
               "research_min_constructive_share", "research_min_core_synthesis_share")
PRESETS: dict[str, dict[str, Any]] = {
    # Even the steady research preset keeps a real mechanism supply; engineering
    # mode ignores the research-only shares.
    "steady":   {"wildcat_every_rounds": 6, "stagnation_rounds": 3, "stagnation_moonshot_rounds": 6,
                 "max_exploit_share": 0.67,
                 "research_min_structural_scope_share": 0.34, "research_min_constructive_share": 0.34,
                 "research_min_core_synthesis_share": 0.0},
    # Research means novelty + gain, not an engineering portfolio with a novelty
    # garnish. Every non-platform research candidate carries an
    # irreducible/paradigm kernel; half are constructed from the task/program
    # rather than a local failure inventory.
    "balanced": {"wildcat_every_rounds": 3, "stagnation_rounds": 2, "stagnation_moonshot_rounds": 3,
                 "max_exploit_share": 0.5,
                 "research_min_structural_scope_share": 0.5, "research_min_constructive_share": 0.5,
                 "research_min_core_synthesis_share": 0.0},
    # Frontier keeps a paradigm exit in every round and devotes at least two of
    # three ordinary bets to constructive/theory-derived search.
    "frontier": {"wildcat_every_rounds": 1, "stagnation_rounds": 2, "stagnation_moonshot_rounds": 2,
                 "max_exploit_share": 0.25,
                 "research_min_structural_scope_share": 0.67, "research_min_constructive_share": 0.67,
                 "research_min_core_synthesis_share": 0.25},
}

for _preset_name, _preset in PRESETS.items():
    if set(_preset) != set(PRESET_KEYS):
        raise AssertionError(
            f"PRESETS[{_preset_name!r}] keys drifted from PRESET_KEYS: "
            f"{sorted(set(_preset) ^ set(PRESET_KEYS))}")

DEFAULT_CONFIG: dict[str, Any] = {
    "evo_version": "10",
    "project": {
        "name": "",
        "goal": "",
        "code_root": ".",
        # Display/calibration RESULT key only (an evaluation cell's result_key).
        # Verdicts use evaluation_contract; this key never owns success.
        "primary_metric": "",
        "vcs": "",                     # "git": node branches enforced to mirror the code_parent chain; "copy": plain directories
        "docs": [],                    # user knowledge base paths (dirs/files) the infra scan must read
        "mode": "",                    # engineering | research (see PROJECT_MODES) - decides the novelty regime
        "rehearsal": "",               # full_chain | none (see REHEARSAL_MODES) - tiny real full-chain
                                       # pass before every node's first full-scale RUN, or waived
        "focus_directions": [],        # optional user interests: [{"id": "D1", "text": "..."}]; the
                                       # scheduler dedicates SOME lanes to them (never more than
                                       # policy.focus_share_max of a round)
    },
    "metrics": [
        # {"key": "auc", "name": "ROC-AUC", "direction": "max",
        #  "definition": "sklearn.roc_auc_score on the fixed dev split",
        #  "source": "metrics.json key 'auc' written by the eval command"}
    ],
    "evaluation_contract": {
        # Filled during configure after a plain-language interview.  IDs are
        # stable vocabulary: datasets D#, tasks T#, cells C#, groups G#.
        "model_scope": "",
        "display_cell": "",          # compact UI only; never a hidden primary objective
        "datasets": [],
        "tasks": [],
        "cells": [],                  # each cell has a unique result_key in metrics.json
        "task_groups": [],
        "decision": {
            "min_target_groups_improved": 1,
            "min_target_groups_goal_met": 0,  # 0 when no absolute/SOTA threshold is declared
            "guardrails_must_be_noninferior": True,
            "allow_specialist": True,
        },
        # Every inferred/defaulted choice must be visible here; silence is not
        # consent.  {id, decision, basis, revisit_when}.
        "assumptions": [],
        # v11: {cell_id: width} - the field's own measurement noise for that
        # cell, recorded from literature during evidence/configure (published
        # seed variance, leaderboard neighbor gaps). 0/absent = v10 behavior.
        # A bare-scalar result is compared as [v-width, v+width] so hiding the
        # error bar stops being the winning move; a REPORTED interval is used
        # as reported. Records whose winning margin is below the floor are
        # labeled provisional in the views (label, never a gate).
        "noise_floors": {},
    },
    "evidence_policy": {
        # Probes are cheap measurements, never an implied training arm. Training
        # replication and causal ablation are different questions and therefore
        # have separate, user-confirmed policies below.
        "probe_mode_order": ["same_run", "existing_artifact", "eval_intervention"],
        "max_extra_eval_arms_per_node": 1,
        "require_value_of_information": True,
        "training_replication": {
            # Filled during configure. record_only is the conservative default:
            # one recorded training seed and no engine-created repeats.
            # preplanned is legal only when typical-run stability is itself part
            # of the user-approved scientific question; every run is disclosed.
            "mode": "",
            "planned_runs": 1,
            "aggregation": "none",
            "basis": "",
            "revisit_when": "",
        },
        "ablation": {
            # targeted permits a separately approved child whose single changed
            # component distinguishes two decision-relevant explanations. It is
            # not an automatic L3 duty and never multiplies across training seeds.
            "mode": "",
            "max_costly_runs_per_node": 0,
            "basis": "",
        },
        "scaling_mode": "off",
        "max_scaling_costly_arms": 0,
    },
    "resource_contract": {
        # Project-wide hard limits confirmed by the user at the mandatory
        # bootstrap gate. Units are extensible (gpu_hours, api_tokens,
        # wallclock_minutes, ...); every stage/eval must cap at least one of
        # these units and the scheduler accounts it cumulatively.
        "limits": {},
        "basis": "",
        "on_exhaustion": "ask",
    },
    "budgets": {
        "rounds_max": 0,               # 0 => ask the user after each round (round_continue gate)
        "lanes_per_round_min": 1,
        "lanes_per_round_max": 4,
        # Instrumental-work caps (v10.2): probes/maintenance never satisfy
        # research shares, so without a cap a run could quietly become an
        # engineering run under a research flag. Both are per round, on top
        # of (not inside) lanes_per_round_max.
        "probes_max_per_round": 1,
        "maintenance_max_per_round": 1,
        # These are complete scientific programs, not one-paragraph module
        # sketches. Four gives the critic real alternatives without rewarding
        # six cosmetic rewrites of one core.
        "sketches_per_lane": 4,
        "winners_per_lane": 1,
        "max_attempts": 3,
        # Broad map plus candidate-bound nearest-neighbour audits. Counts are
        # floors, never substitutes for reconstructing the actual program.
        "evidence_min_total": 80,
        "evidence_min_new_per_round": 0,        # refresh is gap-triggered, never a paper-count treadmill
        "evidence_refresh_min_when_gap": 8,
        "evidence_min_per_bottleneck": 12,      # repair-route coverage floor for a targeted bottleneck
        "evidence_recent_min_per_bottleneck": 8,
        "evidence_recent_year": 2025,
        "evidence_min_recent_ratio": 0.75,
        "mech_cards_min_per_lane": 8,
        "mech_cards_recent_min_per_lane": 3,
        "mech_cards_min_constructive": 12,
        "mech_papers_min_constructive": 9,
        "mech_cards_min_theory_derived": 12,
        "mech_papers_min_theory_derived": 9,
        "mech_cards_min_moonshot": 16,
        "mech_papers_min_moonshot": 12,
        "theory_cycles_max": 3,                # full claims may repair one hard objection after cycle 2
        "theory_cycles_min_full": 2,           # full derivations survive >= this many challenge cycles
        "max_lesson_items_in_bundle": 12,
        "max_error_items_in_bundle": 8,
        "predictions_min": 2,
        "predictions_max": 4,
        "derivation_steps_min": 3,             # partial formal theory: minimum S# derivation steps
        "derivation_steps_min_full": 5,        # stronger duty follows theory_rigor=full, never scope
        "sota_min_entries": 24,                # active, venue-published research comparators
        "retrieval_attempts_min": 2,           # sources that must be tried before a paper counts as inaccessible
    },
    "policy": {
        "autonomy": "gated",
        "cost_gate_class": "heavy",    # trainings at/above this class need a user gate (auto mode); gated mode gates medium+
        "on_stuck": "ask",             # ask | abandon
        # v11: `evo next` audits the objects the imminent decision consumes;
        # the full-web tripwire runs every K invocations or T minutes
        # (whichever first) and always in doctor. "full" restores the v10
        # every-call behavior.
        "next_sweep": "scoped",        # scoped | full
        "full_sweep_every": 8,
        "full_sweep_max_minutes": 30,
        # v11: provenance discipline for self-judged release verdicts
        # (tournament advance / red_team ACCEPT / challenge PROCEED /
        # fidelity FAITHFUL). off = v10 behavior; attest = record + surface
        # at the gate; strict = a release verdict must carry a session id
        # different from the authored work's.
        "critic_isolation": "attest",  # off | attest | strict
        "preset": "balanced",          # steady | balanced | frontier | custom - owns PRESET_KEYS
        "stagnation_rounds": 2,        # flat for K closed rounds => next portfolio must contain an L3+ lane
        "stagnation_moonshot_rounds": 3,  # balanced preset
        "wildcat_every_rounds": 3,     # balanced preset: full-program root cadence
        "max_exploit_share": 0.5,
        "focus_share_max": 0.5,        # user focus directions may claim at most this share of a round's lanes
        "focus_neglect_rounds": 3,     # a focus direction unserved for this many closed rounds forces a lane (0 = off)
        "research_min_structural_scope_share": 0.5,  # L3/L4 is breadth, never the novelty verdict
        "research_min_constructive_share": 0.5,
        "research_min_core_synthesis_share": 0.0,
        "scope_floor": {"exploit": 2, "reform": 3, "wildcat": 4, "moonshot": 4, "hybrid": 2, "platform": 2},
    },
    "research": {
        # research-mode extras; ignored in engineering mode
        "sota_enabled": True,           # research should name the effect frontier it intends to move
        "sota_recent_year": 2025,       # SOTA entries must be from this year or later
        "sota_refresh_rounds": 2,
                                        # rolling benchmarks (SWE-rebench-style) go stale in weeks
        "sota_venues": ["NeurIPS", "ICML", "ICLR", "CVPR", "ICCV", "ECCV", "ACL", "EMNLP",
                        "NAACL", "AAAI", "IJCAI", "KDD", "WWW", "SIGIR", "VLDB", "SIGMOD",
                        "TPAMI", "JMLR", "COLM", "arXiv"],
        # Scaling resource policy lives in evidence_policy.scaling_mode.
        # Kept absent here intentionally: scientific ambition must not silently
        # become a global tax on every L4 idea.
    },
    "infra": {
        "facts_file": ".evo/profile/INFRA_FACTS.json",
        "max_concurrent_stage_jobs": 1,  # scheduler-visible workflow jobs; infra scan records the real quota
        "drills": True,                  # mandatory integrated canary (legacy key name; may not be disabled)
    },
    # v12: validity tolerance band for declared stage/eval budget caps.
    # usage > cap * band invalidates the evidence; 1.0 = strict historical
    # semantics. Deliberately a TOP-LEVEL key OUTSIDE the bootstrap contract
    # digest: it is a documented mutable governance control (like
    # policy.autonomy) whose changes affect FUTURE evidence ingestion only.
    # Recorded numbers never move with it - accounting, receipts, capacity
    # reservations and E-gate resource comparisons always use actual usage.
    # Caps themselves remain the contract: derive each budget.limits value
    # from a worst-case estimate (x1.3 is the field-tested rule); the band is
    # an escape valve for mis-derived caps, never a planning allowance.
    "stage_budget_tolerance": 1.0,
}

_COST_ORDER = {c: i for i, c in enumerate(COST_CLASSES)}


def cost_at_least(cls: str, floor: str) -> bool:
    return _COST_ORDER.get(cls, 0) >= _COST_ORDER.get(floor, 99)


def merged_default() -> dict[str, Any]:
    import copy
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    # R7 external audit: a NAMED preset owns its seven tempo keys at load time
    # (apply_preset fills them on every load_config). Materializing them into
    # the written file made the promised one-word preset flip illegal: the
    # stale numbers of the old preset became six CONFIG_PRESET_CONFLICT
    # errors that hard-blocked doctor and `evo autonomy`. "custom" is the one
    # preset that keeps its numbers in the file.
    policy = cfg.get("policy") or {}
    if str(policy.get("preset") or "") in PRESETS:
        for key in PRESET_KEYS:
            policy.pop(key, None)
    return cfg


def apply_preset(cfg: dict[str, Any]) -> None:
    """Expand policy.preset in place: a named preset owns its tempo keys (fills
    missing ones AND overwrites present ones). preset_conflicts() keeps files
    honest so overwrite and file can only agree; 'custom' leaves values alone."""
    pol = cfg.get("policy")
    if isinstance(pol, dict):
        pre = PRESETS.get(str(pol.get("preset") or ""))
        if pre:
            pol.update(pre)


def preset_conflicts(raw_cfg: dict[str, Any]) -> list[str]:
    if not isinstance(raw_cfg, dict) or not isinstance(raw_cfg.get("policy") or {}, dict):
        return ["CONFIG_BLOCK_POLICY: policy must be an object"]
    if not isinstance(raw_cfg, dict) or not isinstance(raw_cfg.get("policy") or {}, dict):
        return ["CONFIG_BLOCK_POLICY: policy must be an object"]
    """Run on the RAW file dict (before apply_preset): a named preset with
    divergent tempo values in the file is an error - either delete the keys to
    accept the preset, or set preset='custom' to hand-tune."""
    pol = (raw_cfg or {}).get("policy") or {}
    name = str(pol.get("preset") or "")
    pre = PRESETS.get(name)
    if not pre:
        return []
    errs = []
    for k, v in pre.items():
        have = pol.get(k)
        if have is not None and have != v:
            errs.append(f"CONFIG_PRESET_CONFLICT: policy.{k}={have} conflicts with preset '{name}' ({k}={v}); "
                        f"delete the key to accept the preset, or set policy.preset='custom' to hand-tune")
    return errs


def describe_policy(cfg: dict[str, Any]) -> str:
    """One human-readable ASCII line: the run's current temperament. Used by
    status, strategist bundles, and the user reports embedded in gates."""
    pol = cfg.get("policy", {}) or {}
    we = int(pol.get("wildcat_every_rounds") or 0)
    k = int(pol.get("stagnation_rounds") or 0)
    k2 = int(pol.get("stagnation_moonshot_rounds") or 0)
    parts = [f"preset={pol.get('preset') or 'custom'}"]
    parts.append(f"one L4 lane forced every {we} rounds" if we else "no forced L4 cadence")
    stag = f"flat {k} rounds -> force L3+" if k else "stagnation forcing off"
    stag += f", flat {k2} -> force moonshot" if k2 else " (moonshot forcing off)"
    parts.append(stag)
    parts.append(f"exploit share <= {pol.get('max_exploit_share')}")
    parts.append("'flat' = a round that neither settled a claim onto the inheritance "
                 "frontier nor measured a decided advance (materiality is the per-cell "
                 "min_improvement, not a display-metric percentage)")
    return " | ".join(parts)


def _finite_number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) \
        and math.isfinite(float(value))


def _hashable_str(value: Any) -> str | None:
    """A referencing field must be a plain string; anything else is a
    deficiency, never a TypeError inside a set-membership test."""
    return value if isinstance(value, str) else None


def _stable_id(value: Any, prefix: str) -> bool:
    s = str(value or "")
    return len(s) > 1 and s.startswith(prefix) and s[1:].isdigit()


def _validate_evaluation_contract(cfg: dict[str, Any], metric_keys: set[str]) -> list[str]:
    """Validate the explicit dataset x task x metric decision contract.

    The engine intentionally refuses a silent scalar fallback. A
    display metric may exist, but every success-bearing number must live in a
    named evaluation cell with an explicit role and tolerance.
    """
    errs: list[str] = []
    ev = cfg.get("evaluation_contract")
    if not isinstance(ev, dict):
        return ["CONFIG_EVAL_CONTRACT: evaluation_contract must be an object completed during the user interview"]
    if ev.get("model_scope") not in MODEL_SCOPES:
        errs.append(f"CONFIG_EVAL_MODEL_SCOPE: evaluation_contract.model_scope must be one of {MODEL_SCOPES}")

    def records(name: str, prefix: str, fields: tuple[str, ...]) -> tuple[list[dict], set[str]]:
        raw = ev.get(name)
        if not isinstance(raw, list) or not raw:
            errs.append(f"CONFIG_EVAL_{name.upper()}: evaluation_contract.{name} must be a non-empty list")
            return [], set()
        out = [x for x in raw if isinstance(x, dict)]
        if len(out) != len(raw):
            errs.append(f"CONFIG_EVAL_{name.upper()}_SHAPE: every {name} entry must be an object")
        seen: set[str] = set()
        for i, rec in enumerate(out):
            rid = str(rec.get("id") or "")
            if not _stable_id(rid, prefix) or rid in seen:
                errs.append(f"CONFIG_EVAL_{name.upper()}_{i}_ID: needs a unique id like {prefix}1")
            seen.add(rid)
            for f in fields:
                if not str(rec.get(f) or "").strip():
                    errs.append(f"CONFIG_EVAL_{name.upper()}_{i}_{f.upper()}: field '{f}' is required")
        return out, seen

    datasets, dids = records("datasets", "D", ("name", "split", "protocol", "source"))
    tasks, tids = records("tasks", "T", ("name", "description"))
    _ = datasets
    for i, task in enumerate(tasks):
        if task.get("aggregation") not in GROUP_AGGREGATIONS:
            errs.append(f"CONFIG_EVAL_TASK_{i}_AGGREGATION: aggregation must be one of {GROUP_AGGREGATIONS}; "
                        "it combines this task's dataset/metric cells before group voting")
        if not _finite_number(task.get("weight")) or float(task.get("weight") or 0) <= 0:
            errs.append(f"CONFIG_EVAL_TASK_{i}_WEIGHT: weight must be > 0 (used only by a group's weighted_vote)")

    # E2 (2025+ survey): a cell may declare source=human_study with a frozen
    # protocol; the engine hosts preregistration/sealing/settlement of the
    # imported study, never its execution, and such cells are user-owned at
    # settlement time.
    cells_raw = ev.get("cells")
    cells = [x for x in cells_raw if isinstance(x, dict)] if isinstance(cells_raw, list) else []
    if not cells:
        errs.append("CONFIG_EVAL_CELLS: evaluation_contract.cells must enumerate dataset x task x metric decisions")
    if isinstance(cells_raw, list) and len(cells) != len(cells_raw):
        errs.append("CONFIG_EVAL_CELLS_SHAPE: every cell must be an object")
    cids: set[str] = set()
    result_keys: set[str] = set()
    target_tasks: set[str] = set()
    threshold_tasks: set[str] = set()
    used_datasets: set[str] = set()
    used_tasks: set[str] = set()
    for i, cell in enumerate(cells):
        cid = str(cell.get("id") or "")
        if not _stable_id(cid, "C") or cid in cids:
            errs.append(f"CONFIG_EVAL_CELL_{i}_ID: needs a unique id like C1")
        cids.add(cid)
        source_kind = str(cell.get("source_kind") or "")
        if source_kind and source_kind not in ("automated", "human_study"):
            errs.append(f"CONFIG_EVAL_CELL_{i}_SOURCE_KIND: source_kind must be automated|human_study")
        if source_kind == "human_study":
            # E2 (2025+ survey): the engine hosts the preregistration, sealed
            # import and settlement of a human study; it never executes one.
            if len(str(cell.get("study_protocol") or "").strip()) < 80:
                errs.append(f"CONFIG_EVAL_CELL_{i}_STUDY_PROTOCOL: a human_study cell must freeze a "
                            ">= 80 char protocol (participants, procedure, response artifact, "
                            "aggregation) BEFORE any candidate is evaluated on it")
            if str(cell.get("role") or "") == "guardrail":
                errs.append(f"CONFIG_EVAL_CELL_{i}_STUDY_ROLE: a human_study cell cannot be a guardrail - "
                            "an automated pipeline cannot settle it on every node; use target or diagnostic")
        result_key = str(cell.get("result_key") or "").strip()
        if not result_key:
            errs.append(f"CONFIG_EVAL_CELL_{i}_RESULT_KEY: result_key is required (the unique metrics.json key for this dataset x task x metric cell)")
        elif result_key in result_keys:
            errs.append(f"CONFIG_EVAL_CELL_{i}_RESULT_KEY_DUP: duplicate result_key {result_key!r}; two datasets may use the same metric definition but not the same reported value")
        result_keys.add(result_key)
        if _hashable_str(cell.get("dataset")) not in dids:
            errs.append(f"CONFIG_EVAL_CELL_{i}_DATASET: {cell.get('dataset')!r} does not resolve to datasets[]")
        else:
            used_datasets.add(str(cell.get("dataset")))
        if _hashable_str(cell.get("task")) not in tids:
            errs.append(f"CONFIG_EVAL_CELL_{i}_TASK: {cell.get('task')!r} does not resolve to tasks[]")
        else:
            used_tasks.add(str(cell.get("task")))
        if _hashable_str(cell.get("metric")) not in metric_keys:
            errs.append(f"CONFIG_EVAL_CELL_{i}_METRIC: {cell.get('metric')!r} does not resolve to metrics[].key")
        role = cell.get("role")
        if role not in CELL_ROLES:
            errs.append(f"CONFIG_EVAL_CELL_{i}_ROLE: role must be one of {CELL_ROLES}")
        if role == "target":
            target_tasks.add(str(cell.get("task") or ""))
            if isinstance(cell.get("goal_threshold"), (int, float)) and not isinstance(cell.get("goal_threshold"), bool):
                threshold_tasks.add(str(cell.get("task") or ""))
        for f in ("weight", "min_improvement", "noninferiority_margin"):
            value = cell.get(f)
            if not _finite_number(value) or float(value) < 0:
                errs.append(f"CONFIG_EVAL_CELL_{i}_{f.upper()}: must be a non-negative number")
        if role == "target" and isinstance(cell.get("weight"), (int, float)) and float(cell["weight"]) <= 0:
            errs.append(f"CONFIG_EVAL_CELL_{i}_WEIGHT: target cells need weight > 0")
        if not isinstance(cell.get("required"), bool):
            errs.append(f"CONFIG_EVAL_CELL_{i}_REQUIRED: required must be true|false")
        if "goal_threshold" not in cell:
            errs.append(f"CONFIG_EVAL_CELL_{i}_GOAL_THRESHOLD: goal_threshold must be an explicit number or null")
        elif cell.get("goal_threshold") is not None and not _finite_number(cell.get("goal_threshold")):
            errs.append(f"CONFIG_EVAL_CELL_{i}_GOAL_THRESHOLD: goal_threshold must be numeric or null")
        if len(str(cell.get("goal_threshold_source") or "").strip()) < 10:
            errs.append(f"CONFIG_EVAL_CELL_{i}_GOAL_SOURCE: explain the absolute threshold source or why this cell is progress-only")
        if role == "diagnostic" and cell.get("required") is True:
            errs.append(f"CONFIG_EVAL_CELL_{i}_DIAGNOSTIC_REQUIRED: a non-decisive diagnostic cell cannot be required")
    if not target_tasks:
        errs.append("CONFIG_EVAL_TARGET_EMPTY: at least one evaluation cell must have role='target'")
    if dids - used_datasets:
        errs.append(f"CONFIG_EVAL_DATASET_UNUSED: declared datasets {sorted(dids - used_datasets)} have no evaluation cell")
    if tids - used_tasks:
        errs.append(f"CONFIG_EVAL_TASK_UNUSED: declared tasks {sorted(tids - used_tasks)} have no evaluation cell")

    display = str(ev.get("display_cell") or "")
    if display not in cids:
        errs.append("CONFIG_EVAL_DISPLAY_CELL: evaluation_contract.display_cell must resolve to a C# cell; it is display-only, not the success criterion")

    groups_raw = ev.get("task_groups")
    groups = [x for x in groups_raw if isinstance(x, dict)] if isinstance(groups_raw, list) else []
    if not groups:
        errs.append("CONFIG_EVAL_GROUPS: task_groups must define how related tasks are judged")
    gids: set[str] = set()
    grouped_tasks: set[str] = set()
    target_group_count = 0
    goal_group_count = 0
    for i, group in enumerate(groups):
        gid = str(group.get("id") or "")
        if not _stable_id(gid, "G") or gid in gids:
            errs.append(f"CONFIG_EVAL_GROUP_{i}_ID: needs a unique id like G1")
        gids.add(gid)
        if not str(group.get("name") or "").strip():
            errs.append(f"CONFIG_EVAL_GROUP_{i}_NAME: name required")
        gtasks = group.get("tasks")
        if not isinstance(gtasks, list) or not gtasks:
            errs.append(f"CONFIG_EVAL_GROUP_{i}_TASKS: tasks must be a non-empty list")
        else:
            unknown = [t for t in gtasks if _hashable_str(t) not in tids]
            if unknown:
                errs.append(f"CONFIG_EVAL_GROUP_{i}_TASK_UNKNOWN: unknown tasks {unknown}")
            grouped_tasks.update(str(t) for t in gtasks)
            if set(str(t) for t in gtasks) & target_tasks:
                target_group_count += 1
            else:
                errs.append(f"CONFIG_EVAL_GROUP_{i}_NO_TARGET: a decision group must contain at least one target task")
            if set(str(t) for t in gtasks) & threshold_tasks:
                goal_group_count += 1
        if group.get("aggregation") not in GROUP_AGGREGATIONS:
            errs.append(f"CONFIG_EVAL_GROUP_{i}_AGGREGATION: must be one of {GROUP_AGGREGATIONS}")
        if not isinstance(group.get("required"), bool):
            errs.append(f"CONFIG_EVAL_GROUP_{i}_REQUIRED: required must be true|false")
    missing_groups = sorted(target_tasks - grouped_tasks)
    if missing_groups:
        errs.append(f"CONFIG_EVAL_TARGET_UNGROUPED: target tasks {missing_groups} are absent from task_groups")

    decision = ev.get("decision") if isinstance(ev.get("decision"), dict) else {}
    if ev.get("decision") is not None and not isinstance(ev.get("decision"), dict):
        errs.append("CONFIG_EVAL_DECISION_SHAPE: evaluation_contract.decision must be an object")
    if not isinstance(decision.get("min_target_groups_improved"), int) \
            or int(decision.get("min_target_groups_improved", 0)) < 1:
        errs.append("CONFIG_EVAL_DECISION_GROUPS: decision.min_target_groups_improved must be int >= 1")
    elif int(decision.get("min_target_groups_improved")) > target_group_count:
        errs.append("CONFIG_EVAL_DECISION_GROUPS_RANGE: decision.min_target_groups_improved "
                    f"cannot exceed the {target_group_count} target-bearing groups")
    goal_min = decision.get("min_target_groups_goal_met")
    if not isinstance(goal_min, int) or goal_min < 0:
        errs.append("CONFIG_EVAL_DECISION_GOAL_GROUPS: decision.min_target_groups_goal_met must be int >= 0")
    elif goal_group_count == 0 and goal_min != 0:
        errs.append("CONFIG_EVAL_DECISION_GOAL_GROUPS_EMPTY: no target cell has an absolute goal_threshold, so min_target_groups_goal_met must be 0")
    elif goal_group_count > 0 and not (1 <= goal_min <= goal_group_count):
        errs.append("CONFIG_EVAL_DECISION_GOAL_GROUPS_RANGE: with absolute thresholds, "
                    f"min_target_groups_goal_met must be 1..{goal_group_count}")
    for f in ("guardrails_must_be_noninferior", "allow_specialist"):
        if not isinstance(decision.get(f), bool):
            errs.append(f"CONFIG_EVAL_DECISION_{f.upper()}: must be true|false")

    assumptions = ev.get("assumptions")
    if not isinstance(assumptions, list):
        errs.append("CONFIG_EVAL_ASSUMPTIONS: assumptions must be a list (empty only when every decision was explicit)")
    else:
        seen_a: set[str] = set()
        for i, a in enumerate(assumptions):
            if not isinstance(a, dict):
                errs.append(f"CONFIG_EVAL_ASSUMPTION_{i}_SHAPE: assumptions[{i}] must be an object")
                continue
            aid = str((a or {}).get("id") or "")
            if not _stable_id(aid, "U") or aid in seen_a:
                errs.append(f"CONFIG_EVAL_ASSUMPTION_{i}_ID: needs a unique id like U1")
            seen_a.add(aid)
            for f in ("decision", "basis", "revisit_when"):
                if len(str((a or {}).get(f) or "").strip()) < 15:
                    errs.append(f"CONFIG_EVAL_ASSUMPTION_{i}_{f.upper()}: explain the inferred choice (>= 15 chars)")
    return errs


def _validate_evidence_policy(cfg: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    ep = cfg.get("evidence_policy")
    if not isinstance(ep, dict):
        return ["CONFIG_EVIDENCE_POLICY: evidence_policy object required"]
    order = ep.get("probe_mode_order")
    if not isinstance(order, list) or any(not isinstance(x, str) for x in order) \
            or set(order) != set(PROBE_MODES) or len(order) != len(PROBE_MODES):
        errs.append(f"CONFIG_PROBE_ORDER: probe_mode_order must contain each of {PROBE_MODES} exactly once")
    for f in ("max_extra_eval_arms_per_node", "max_scaling_costly_arms"):
        if not isinstance(ep.get(f), int) or ep.get(f, -1) < 0:
            errs.append(f"CONFIG_EVIDENCE_{f.upper()}: must be a non-negative integer")
    legacy = sorted(set(ep) & {"max_extra_costly_arms_pre_signal", "in_node_costly_ablations"})
    if legacy:
        errs.append(f"CONFIG_EVIDENCE_LEGACY_COST_BUCKET: remove obsolete fields {legacy}; training replication "
                    "and targeted ablation now have separate user-confirmed policies")
    if not isinstance(ep.get("require_value_of_information"), bool) or not ep.get("require_value_of_information"):
        errs.append("CONFIG_EVIDENCE_VOI: require_value_of_information must be true")

    replication = ep.get("training_replication")
    if not isinstance(replication, dict):
        errs.append("CONFIG_TRAINING_REPLICATION: evidence_policy.training_replication object required")
        replication = {}
    rep_mode = replication.get("mode")
    if rep_mode not in TRAINING_REPLICATION_MODES:
        errs.append(f"CONFIG_TRAINING_REPLICATION_MODE: mode must be one of {TRAINING_REPLICATION_MODES}; "
                    "this is decided with the user after the project/domain scan")
    planned = replication.get("planned_runs")
    if not isinstance(planned, int) or isinstance(planned, bool) or planned < 1:
        errs.append("CONFIG_TRAINING_REPLICATION_RUNS: planned_runs must be an integer >= 1")
    aggregation = replication.get("aggregation")
    if aggregation not in TRAINING_REPLICATION_AGGREGATIONS:
        errs.append(f"CONFIG_TRAINING_REPLICATION_AGGREGATION: aggregation must be one of "
                    f"{TRAINING_REPLICATION_AGGREGATIONS}")
    if rep_mode == "record_only":
        if planned != 1 or aggregation != "none":
            errs.append("CONFIG_TRAINING_REPLICATION_RECORD_ONLY: record_only requires planned_runs=1 and "
                        "aggregation='none'; it never creates repeated training")
    elif rep_mode == "preplanned":
        if not isinstance(planned, int) or isinstance(planned, bool) or planned < 2:
            errs.append("CONFIG_TRAINING_REPLICATION_PREPLANNED_RUNS: preplanned requires planned_runs >= 2")
        if aggregation not in ("mean", "median"):
            errs.append("CONFIG_TRAINING_REPLICATION_PREPLANNED_AGGREGATION: preplanned requires an ex-ante "
                        "mean or median rule; all individual runs are still reported")
    if len(str(replication.get("basis") or "").strip()) < 40:
        errs.append("CONFIG_TRAINING_REPLICATION_BASIS: record the domain/process/claim/cost reasoning and "
                    "the user's decision (>= 40 chars)")
    if len(str(replication.get("revisit_when") or "").strip()) < 30:
        errs.append("CONFIG_TRAINING_REPLICATION_REVISIT: state what new evidence would justify reopening "
                    "this user-confirmed policy (>= 30 chars)")

    ablation = ep.get("ablation")
    if not isinstance(ablation, dict):
        errs.append("CONFIG_ABLATION_POLICY: evidence_policy.ablation object required")
        ablation = {}
    ablation_mode = ablation.get("mode")
    if ablation_mode not in ABLATION_MODES:
        errs.append(f"CONFIG_ABLATION_MODE: mode must be one of {ABLATION_MODES}")
    max_runs = ablation.get("max_costly_runs_per_node")
    if not isinstance(max_runs, int) or isinstance(max_runs, bool) or max_runs < 0:
        errs.append("CONFIG_ABLATION_RUNS: max_costly_runs_per_node must be a non-negative integer")
    if ablation_mode == "off" and max_runs != 0:
        errs.append("CONFIG_ABLATION_OFF: ablation mode off requires max_costly_runs_per_node=0")
    if ablation_mode == "targeted" and max_runs != 1:
        errs.append("CONFIG_ABLATION_TARGETED: targeted mode permits exactly one changed-component run per "
                    "ablation node; broader studies need a new user-approved design")
    if len(str(ablation.get("basis") or "").strip()) < 40:
        errs.append("CONFIG_ABLATION_BASIS: record why targeted ablation is allowed or disabled for this "
                    "project and budget (>= 40 chars)")

    mode = ep.get("scaling_mode")
    if mode not in SCALING_MODES:
        errs.append(f"CONFIG_SCALING_MODE: scaling_mode must be one of {SCALING_MODES}")
    if mode in ("off", "reuse_only") and ep.get("max_scaling_costly_arms") != 0:
        errs.append(f"CONFIG_SCALING_ARMS: scaling_mode={mode} requires max_scaling_costly_arms=0")
    if mode in ("budgeted", "full") and isinstance(ep.get("max_scaling_costly_arms"), int) \
            and ep.get("max_scaling_costly_arms", 0) < 1:
        errs.append(f"CONFIG_SCALING_ARMS: scaling_mode={mode} requires max_scaling_costly_arms >= 1")
    return errs


def validate_config(cfg: dict[str, Any]) -> list[str]:
    """Return list of deficiencies; empty list means the config is complete."""
    errs: list[str] = []
    if not isinstance(cfg, dict):
        return ["CONFIG_NOT_OBJECT: config.json must be a JSON object"]
    policy_keys = set(cfg.get("policy")) if isinstance(cfg.get("policy"), dict) else set()
    budget_keys = set(cfg.get("budgets")) if isinstance(cfg.get("budgets"), dict) else set()
    legacy_policy = sorted(policy_keys & {"novelty_floor", "research_min_l3_share"})
    legacy_budgets = sorted(budget_keys & {"program_assumption_inversions_min", "bold_sketch_required",
                                           "sketch_moves_distinct_min", "sketch_customs_max"})
    if legacy_policy:
        errs.append(f"CONFIG_LEGACY_POLICY: removed policy fields {legacy_policy}; use scope_floor and the independent M gate")
    if legacy_budgets:
        errs.append(f"CONFIG_LEGACY_BUDGETS: removed narrative/assumption quotas {legacy_budgets}")
    if cfg.get("evo_version") != "10":
        errs.append("CONFIG_VERSION: evo_version must be '10'")
    tol = cfg.get("stage_budget_tolerance")
    if tol is not None and (isinstance(tol, bool) or not isinstance(tol, (int, float))
                            or not math.isfinite(float(tol)) or float(tol) < 1.0):
        # The accessor clamps malformed values to 1.0 so validation can never
        # deadlock a live project, but a typo must still surface loudly here
        # instead of silently running strict.
        errs.append("CONFIG_BUDGET_TOLERANCE: stage_budget_tolerance must be a finite number >= 1.0 "
                    "(validity band multiplier for declared budget caps; 1.0 = strict; "
                    "changes affect future evidence ingestion only)")

    # Malformed top-level blocks must yield deficiencies, never AttributeErrors:
    # a validator that crashes on bad input silently exempts that input.
    def _block(name: str, default):
        value = cfg.get(name)
        if value is None:
            return default
        if not isinstance(value, type(default)):
            errs.append(f"CONFIG_BLOCK_{name.upper()}: {name} must be a "
                        f"{'list' if isinstance(default, list) else 'object'}")
            return default
        return value

    proj = _block("project", {})
    for key in ("name", "goal", "primary_metric"):
        if not str(proj.get(key) or "").strip():
            errs.append(f"CONFIG_PROJECT_{key.upper()}: project.{key} must be filled in")
    if proj.get("vcs") not in ("git", "copy"):
        errs.append("CONFIG_PROJECT_VCS: project.vcs must be 'git' (branch/DAG mapping enforced) or 'copy'")
    if not isinstance(proj.get("docs"), list):
        errs.append("CONFIG_PROJECT_DOCS: project.docs must be a list of knowledge-base paths (may be empty "
                    "only if the user has no docs; the infra scan will then rely on code alone)")
    if proj.get("mode") not in PROJECT_MODES:
        errs.append(f"CONFIG_MODE: project.mode must be one of {PROJECT_MODES} - it decides the novelty "
                    f"regime (engineering: borrow-what-fits; research: non-platform candidates owe "
                    f"irreducible M + effect E + structural-scope share)")
    if proj.get("rehearsal") not in REHEARSAL_MODES:
        errs.append(f"CONFIG_REHEARSAL: project.rehearsal must be one of {REHEARSAL_MODES} - ASK the user: "
                    f"should every node prove its ENTIRE workflow with one tiny real pass on the real "
                    f"platform before its first full-scale run (full_chain, recommended for any remote/"
                    f"costly platform), or do they explicitly waive it (none)?")
    fds = proj.get("focus_directions")
    if not isinstance(fds, list):
        errs.append("CONFIG_FOCUS: project.focus_directions must be a list (may be empty)")
    else:
        seen_fd: set[str] = set()
        for i, fd in enumerate(fds):
            if not isinstance(fd, dict):
                errs.append(f"CONFIG_FOCUS_{i}_SHAPE: focus_directions[{i}] must be an object")
                fd = {}
            fid = str((fd or {}).get("id") or "")
            if not fid or not fid.startswith("D") or fid in seen_fd:
                errs.append(f"CONFIG_FOCUS_{i}: focus_directions[{i}] needs a unique 'id' like 'D1'")
            seen_fd.add(fid)
            if len(str((fd or {}).get("text") or "").strip()) < 15:
                errs.append(f"CONFIG_FOCUS_{i}_TEXT: focus_directions[{i}].text must describe the direction (>= 15 chars)")
    metrics = _block("metrics", [])
    if not isinstance(metrics, list) or not metrics:
        errs.append("CONFIG_METRICS_EMPTY: metrics must list every definition referenced by evaluation cells")
    keys = set()
    for i, m in enumerate(metrics if isinstance(metrics, list) else []):
        if not isinstance(m, dict):
            errs.append(f"CONFIG_METRIC_{i}_SHAPE: metrics[{i}] must be an object")
            m = {}
        for f in ("key", "name", "direction", "definition", "source"):
            if not str((m or {}).get(f) or "").strip():
                errs.append(f"CONFIG_METRIC_{i}_{f.upper()}: metrics[{i}].{f} must be filled in")
        if (m or {}).get("direction") not in ("max", "min"):
            errs.append(f"CONFIG_METRIC_{i}_DIRECTION: metrics[{i}].direction must be 'max' or 'min'")
        key = str((m or {}).get("key") or "")
        if key in keys:
            errs.append(f"CONFIG_METRIC_{i}_DUP: duplicate metric key {key!r}")
        keys.add(key)
    errs.extend(_validate_evaluation_contract(cfg, keys))
    result_keys = {str(c.get("result_key") or "") for c in evaluation_cells(cfg)}
    if str(proj.get("primary_metric") or "") and str(proj.get("primary_metric")) not in result_keys:
        errs.append("CONFIG_PRIMARY_METRIC_UNKNOWN: project.primary_metric is display-only and must match an evaluation cell result_key")
    display = cell_spec(cfg).get(str(evaluation_contract(cfg).get("display_cell") or "")) or {}
    if display and str(proj.get("primary_metric") or "") != str(display.get("result_key") or ""):
        errs.append("CONFIG_PRIMARY_METRIC_DISPLAY: project.primary_metric must equal evaluation_contract.display_cell's result_key")
    errs.extend(_validate_evidence_policy(cfg))
    contract = cfg.get("resource_contract")
    if not isinstance(contract, dict):
        errs.append("CONFIG_RESOURCE_CONTRACT: resource_contract must be an object confirmed with the user")
        contract = {}
    limits = contract.get("limits")
    if not isinstance(limits, dict) or not limits:
        errs.append("CONFIG_RESOURCE_LIMITS: resource_contract.limits must contain at least one project-wide "
                    "hard limit (for example gpu_hours, api_tokens, or wallclock_minutes)")
        limits = {}
    for unit, limit in limits.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,47}", str(unit or "")):
            errs.append(f"CONFIG_RESOURCE_UNIT: resource unit {unit!r} must be a lowercase slug")
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or \
                not math.isfinite(float(limit)) or float(limit) <= 0:
            errs.append(f"CONFIG_RESOURCE_LIMIT: resource_contract.limits.{unit} must be finite and > 0")
    if len(str(contract.get("basis") or "").strip()) < 20:
        errs.append("CONFIG_RESOURCE_BASIS: resource_contract.basis must record what limits the user approved (>= 20 chars)")
    if contract.get("on_exhaustion") != "ask":
        errs.append("CONFIG_RESOURCE_EXHAUSTION: resource_contract.on_exhaustion must be 'ask'; "
                    "an agent may not silently raise a user-owned project limit")
    ext_rows = contract.get("extension_axes")
    if ext_rows is not None:
        import eprogram as _ep
        if not isinstance(ext_rows, list):
            errs.append("CONFIG_RESOURCE_EXTENSION: resource_contract.extension_axes must be a list")
            ext_rows = []
        seen_ext: set[str] = set()
        for i, row in enumerate(ext_rows):
            if not isinstance(row, dict):
                errs.append(f"CONFIG_RESOURCE_EXTENSION_{i}: extension_axes[{i}] must be an object")
                continue
            key = str(row.get("key") or "")
            if not re.fullmatch(r"[a-z][a-z0-9_]{1,39}", key):
                errs.append(f"CONFIG_RESOURCE_EXTENSION_{i}_KEY: extension_axes[{i}].key must be a lowercase slug")
            if key in _ep.RESOURCE_AXES or key in seen_ext:
                errs.append(f"CONFIG_RESOURCE_EXTENSION_{i}_DUP: axis {key!r} collides with a core axis or another extension")
            seen_ext.add(key)
            if not str(row.get("unit") or "").strip():
                errs.append(f"CONFIG_RESOURCE_EXTENSION_{i}_UNIT: extension_axes[{i}].unit required (e.g. gb, watt_hours, robot_minutes)")
            direction = row.get("direction")
            if direction is not None and direction != "min":
                errs.append(f"CONFIG_RESOURCE_EXTENSION_{i}_DIRECTION: extension axes are cost-directed "
                            "(always minimized); declare throughput-style measures inversely "
                            "(e.g. ms_per_token) instead of direction='max'")
            direction = row.get("direction")
            if direction is not None and direction != "min":
                errs.append(f"CONFIG_RESOURCE_EXTENSION_{i}_DIRECTION: extension axes are cost-directed "
                            "(always minimized); declare throughput-style measures inversely "
                            "(e.g. ms_per_token) instead of direction='max'")
            if str(row.get("accounting") or "") not in _ep.RESOURCE_ACCOUNTING_METHODS:
                errs.append(f"CONFIG_RESOURCE_EXTENSION_{i}_ACCOUNTING: extension_axes[{i}].accounting must be one of "
                            f"{_ep.RESOURCE_ACCOUNTING_METHODS}")
        if len(seen_ext) > 6:
            errs.append("CONFIG_RESOURCE_EXTENSION_COUNT: at most 6 extension axes (an unauditable vector is not accounting)")
    pol = _block("policy", {})
    if pol.get("autonomy") not in AUTONOMY_MODES:
        errs.append(f"CONFIG_AUTONOMY: policy.autonomy must be one of {AUTONOMY_MODES}")
    if pol.get("on_stuck") not in ("ask", "abandon"):
        errs.append("CONFIG_ON_STUCK: policy.on_stuck must be 'ask' or 'abandon'")
    if pol.get("next_sweep", "scoped") not in ("scoped", "full"):
        errs.append("CONFIG_NEXT_SWEEP: policy.next_sweep must be 'scoped' or 'full'")
    for key in ("full_sweep_every", "full_sweep_max_minutes"):
        value = pol.get(key, 1)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            errs.append(f"CONFIG_POLICY_{key.upper()}: policy.{key} must be an integer >= 1")
    if pol.get("critic_isolation", "attest") not in ("off", "attest", "strict"):
        errs.append("CONFIG_CRITIC_ISOLATION: policy.critic_isolation must be off|attest|strict")
    nf = (_block("evaluation_contract", {}) or {}).get("noise_floors") or {}
    if not isinstance(nf, dict):
        errs.append("CONFIG_NOISE_FLOORS: evaluation_contract.noise_floors must be an object "
                    "{cell_id: width}")
    else:
        cell_ids = {str(c.get("id")) for c in evaluation_cells(cfg)}
        for cell_id, width in nf.items():
            if isinstance(width, bool) or not isinstance(width, (int, float)) \
                    or not math.isfinite(float(width)) or float(width) < 0:
                errs.append(f"CONFIG_NOISE_FLOOR_{str(cell_id).upper()}: noise floor must be a "
                            "finite number >= 0")
            elif cell_ids and str(cell_id) not in cell_ids:
                errs.append(f"CONFIG_NOISE_FLOOR_{str(cell_id).upper()}: names no evaluation cell")
            elif float(width) > 0:
                # The margin below the field's own noise is the exact trap the
                # measurement audit named: the cell's outcome is then decided
                # by seed luck, and the record ratchets on noise maxima.
                for cell in evaluation_cells(cfg):
                    if str(cell.get("id")) == str(cell_id):
                        margin = cell.get("min_improvement")
                        if isinstance(margin, (int, float)) and not isinstance(margin, bool) \
                                and 0 <= float(margin) < float(width):
                            errs.append(
                                f"CONFIG_MARGIN_BELOW_NOISE_{str(cell_id).upper()}: "
                                f"min_improvement {margin:g} is below the recorded noise floor "
                                f"{float(width):g}; a single-run delta inside the noise band "
                                "would decide the cell by seed luck")
    if pol.get("cost_gate_class") not in COST_CLASSES:
        errs.append(f"CONFIG_COST_GATE: policy.cost_gate_class must be one of {COST_CLASSES}")
    if str(pol.get("preset") or "") not in list(PRESETS) + ["custom"]:
        errs.append(f"CONFIG_PRESET: policy.preset must be one of {sorted(PRESETS)} or 'custom'")
    if str(pol.get("preset") or "") == "custom":
        # custom exists precisely for hand-tuned tempo keys, so each one must
        # actually be a sane number - named presets overwrite them wholesale.
        for key in ("wildcat_every_rounds", "stagnation_rounds", "stagnation_moonshot_rounds"):
            value = pol.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errs.append(f"CONFIG_TEMPO_{key.upper()}: custom preset requires policy.{key} "
                            "to be an integer >= 0")
        for key in ("max_exploit_share", "research_min_structural_scope_share",
                    "research_min_constructive_share", "research_min_core_synthesis_share"):
            value = pol.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
                errs.append(f"CONFIG_TEMPO_{key.upper()}: custom preset requires policy.{key} "
                            "to be a number in [0,1]")
    for key, shape in (("focus_share_max", "share"), ("focus_neglect_rounds", "int")):
        value = pol.get(key)
        if value is None:
            continue
        if shape == "share" and (isinstance(value, bool) or not isinstance(value, (int, float))
                                 or not 0 <= float(value) <= 1):
            errs.append(f"CONFIG_POLICY_{key.upper()}: policy.{key} must be a number in [0,1]")
        if shape == "int" and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            errs.append(f"CONFIG_POLICY_{key.upper()}: policy.{key} must be an integer >= 0")
    # Two independently sane focus knobs can contradict each other. R9 audit
    # + v11.4 reconciliation: this satisfiability statement and the runtime
    # admission share ONE explicit rule - the cap binds over qualifying
    # candidate lanes, except that the single lane a starved direction
    # forces rides outside the numerator (so starvation forcing is always
    # satisfiable, in every round size). What remains genuinely
    # unsatisfiable is a config whose directions can NEVER be served: no
    # neglect forcing (0/off) AND a cap too low to ever admit one voluntary
    # focus lane in even the largest legal round - the directions are dead
    # configuration and every tag would be rejected forever.
    _bud = cfg.get("budgets") if isinstance(cfg.get("budgets"), dict) else {}
    _lanes_min, _lanes_max = _bud.get("lanes_per_round_min"), _bud.get("lanes_per_round_max")
    _cap, _negl = pol.get("focus_share_max"), pol.get("focus_neglect_rounds")
    _negl_on = isinstance(_negl, int) and not isinstance(_negl, bool) and _negl > 0
    if focus_directions(cfg) and not _negl_on \
            and _finite_number(_cap) and isinstance(_lanes_min, int) and isinstance(_lanes_max, int) \
            and _lanes_max >= 1 and float(_cap) < 1.0 / _lanes_max - 1e-9:
        errs.append(
            f"CONFIG_FOCUS_UNSATISFIABLE: focus directions are configured, but "
            f"policy.focus_share_max={_cap} rejects even one focus lane out of the largest legal "
            f"round ({_lanes_max} lanes -> {1.0 / _lanes_max:.0%} > {float(_cap):.0%}) and "
            "focus_neglect_rounds is off, so no direction can ever legally be served. Raise "
            f"focus_share_max to >= {1.0 / _lanes_max:.2f}, raise lanes_per_round_max, or enable "
            "focus_neglect_rounds (a starvation-forced lane rides outside the cap)")
    nf = pol.get("scope_floor") if isinstance(pol.get("scope_floor"), dict) else {}
    if pol.get("scope_floor") is not None and not isinstance(pol.get("scope_floor"), dict):
        errs.append("CONFIG_SCOPE_FLOOR_SHAPE: policy.scope_floor must be an object")
    for intent in LANE_INTENTS:
        lv = nf.get(intent)
        if not isinstance(lv, int) or not 1 <= lv <= 4:
            errs.append(f"CONFIG_SCOPE_FLOOR_{intent.upper()}: policy.scope_floor.{intent} must be int 1..4")
    if isinstance(nf.get("moonshot"), int) and nf.get("moonshot") < 4:
        errs.append("CONFIG_SCOPE_FLOOR_MOONSHOT_MIN: moonshot lanes require full-program search; scope_floor.moonshot must be 4")
    if isinstance(nf.get("wildcat"), int) and nf.get("wildcat") < 4:
        errs.append("CONFIG_SCOPE_FLOOR_WILDCAT_MIN: wildcat lanes are parentless full-program roots "
                    "(a lane with no model parent has nothing to make a smaller change to); "
                    "scope_floor.wildcat must be 4")
    bud = _block("budgets", {})
    for f in ("rounds_max", "lanes_per_round_min", "lanes_per_round_max", "sketches_per_lane",
              "probes_max_per_round", "maintenance_max_per_round",
              "winners_per_lane", "max_attempts", "evidence_min_total", "mech_cards_min_per_lane",
              "evidence_min_new_per_round", "evidence_refresh_min_when_gap", "evidence_recent_year",
              "mech_cards_recent_min_per_lane", "mech_cards_min_constructive",
              "mech_papers_min_constructive", "mech_cards_min_theory_derived",
              "mech_papers_min_theory_derived", "mech_cards_min_moonshot", "mech_papers_min_moonshot",
              "theory_cycles_max", "theory_cycles_min_full", "predictions_min", "predictions_max",
              "evidence_min_per_bottleneck", "evidence_recent_min_per_bottleneck",
              "derivation_steps_min", "derivation_steps_min_full",
              "sota_min_entries", "retrieval_attempts_min"):
        if not isinstance(bud.get(f), int) or bud.get(f) < 0:
            errs.append(f"CONFIG_BUDGET_{f.upper()}: budgets.{f} must be a non-negative integer")
    ratio = bud.get("evidence_min_recent_ratio")
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 0 <= float(ratio) <= 1:
        errs.append("CONFIG_BUDGET_EVIDENCE_MIN_RECENT_RATIO: budgets.evidence_min_recent_ratio "
                    "must be a number in [0,1] (it may not be deleted to disable the recency duty)")
    res = _block("research", {})
    if str(proj.get("mode") or "") == "research":
        if res.get("sota_enabled"):
            if not isinstance(res.get("sota_recent_year"), int):
                errs.append("CONFIG_SOTA_YEAR: research.sota_recent_year must be an integer year")
            if not isinstance(res.get("sota_venues"), list) or not res.get("sota_venues"):
                errs.append("CONFIG_SOTA_VENUES: research.sota_venues must list the accepted venues")
            if not isinstance(res.get("sota_refresh_rounds", 0), int) or res.get("sota_refresh_rounds", 0) < 0:
                errs.append("CONFIG_SOTA_REFRESH: research.sota_refresh_rounds must be a non-negative integer")
        # reading floors: 科研档必须饱读新文献 - enforced as config facts, not card prose
        ratio_ok = isinstance(bud.get("evidence_min_recent_ratio"), (int, float)) \
            and not isinstance(bud.get("evidence_min_recent_ratio"), bool)
        if not ratio_ok or float(bud.get("evidence_min_recent_ratio") or 0) < 0.5:
            errs.append("CONFIG_RESEARCH_FLOOR_RECENCY: research mode requires "
                        "budgets.evidence_min_recent_ratio >= 0.5 (the pool must track the frontier)")
        if isinstance(bud.get("mech_cards_recent_min_per_lane"), int) and \
                bud.get("mech_cards_recent_min_per_lane", 0) < 1:
            errs.append("CONFIG_RESEARCH_FLOOR_CARDS: research mode requires "
                        "budgets.mech_cards_recent_min_per_lane >= 1")
        if isinstance(bud.get("mech_papers_min_moonshot"), int) and bud.get("mech_papers_min_moonshot", 0) < 3:
            errs.append("CONFIG_RESEARCH_FLOOR_MOONSHOT_PAPERS: research mode requires "
                        "budgets.mech_papers_min_moonshot >= 3")
        if isinstance(bud.get("mech_cards_min_moonshot"), int) and \
                isinstance(bud.get("mech_cards_min_per_lane"), int) and \
                bud["mech_cards_min_moonshot"] <= bud["mech_cards_min_per_lane"]:
            errs.append("CONFIG_RESEARCH_FLOOR_MOONSHOT_CARDS: research mode requires "
                        "budgets.mech_cards_min_moonshot > mech_cards_min_per_lane "
                        "(the frontier tier reads deeper by construction)")
        for key in ("research_min_structural_scope_share", "research_min_constructive_share",
                    "research_min_core_synthesis_share"):
            val = pol.get(key)
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not 0 <= float(val) <= 1:
                errs.append(f"CONFIG_RESEARCH_SHARE: policy.{key} must be a number in [0,1]")
        # L4 supply floor: 科研档全新节点占比多 - a research run may not
        # disable the wildcat cadence or moonshot forcing. Every named
        # preset, including steady, therefore keeps both cadences positive.
        pol2 = pol
        if not (isinstance(pol2.get("wildcat_every_rounds"), int) and pol2.get("wildcat_every_rounds", 0) >= 1):
            errs.append("CONFIG_RESEARCH_FLOOR_L4: research mode requires policy.wildcat_every_rounds "
                        ">= 1 - no-model-parent L4 lanes must recur by cadence, not by mood")
        if not (isinstance(pol2.get("stagnation_moonshot_rounds"), int) and pol2.get("stagnation_moonshot_rounds", 0) >= 1):
            errs.append("CONFIG_RESEARCH_FLOOR_L4: research mode requires "
                        "policy.stagnation_moonshot_rounds >= 1 (moonshot forcing may not be off; "
                        "choose a positive cadence or use engineering mode)")
    if isinstance(bud.get("lanes_per_round_min"), int) and isinstance(bud.get("lanes_per_round_max"), int):
        if bud["lanes_per_round_min"] > bud["lanes_per_round_max"]:
            errs.append("CONFIG_BUDGET_LANES: lanes_per_round_min must be <= lanes_per_round_max")
        # R9 audit: a 0 lane ceiling passed validation, opened empty rounds,
        # and then the cadence rules (wildcat/stagnation - always positive
        # under every named preset and mandatory in research mode) demanded a
        # reform lane the same portfolio was forbidden to contain: a
        # deterministic dead end reached in finitely many rounds, discovered
        # only after budgets were frozen into the signed contract. A round IS
        # a set of real bets; prove at configure time that one can exist.
        if bud["lanes_per_round_max"] < 1:
            errs.append("CONFIG_BUDGET_LANES_CEILING: lanes_per_round_max must be >= 1 - a 0-lane "
                        "round cannot satisfy the wildcat/stagnation cadence this config also "
                        "mandates, and the contradiction only surfaces after the contract freezes")
    if isinstance(bud.get("predictions_min"), int) and isinstance(bud.get("predictions_max"), int) \
            and bud["predictions_min"] > bud["predictions_max"]:
        errs.append("CONFIG_BUDGET_PREDICTIONS: predictions_min must be <= predictions_max "
                    "(otherwise no idea can ever satisfy the prediction-count duty)")
    if isinstance(bud.get("theory_cycles_min_full"), int) and isinstance(bud.get("theory_cycles_max"), int) \
            and bud["theory_cycles_min_full"] > bud["theory_cycles_max"]:
        errs.append("CONFIG_BUDGET_THEORY_RANGE: theory_cycles_min_full must be <= theory_cycles_max")
    if isinstance(bud.get("derivation_steps_min"), int) and isinstance(bud.get("derivation_steps_min_full"), int) \
            and bud["derivation_steps_min_full"] < bud["derivation_steps_min"]:
        errs.append("CONFIG_BUDGET_DERIVATION_RANGE: derivation_steps_min_full must be >= derivation_steps_min")
    if isinstance(bud.get("sketches_per_lane"), int) and bud.get("sketches_per_lane", 0) < 3:
        errs.append("CONFIG_BUDGET_SKETCHES: budgets.sketches_per_lane must be >= 3 (divergence quota)")
    if bud.get("winners_per_lane") != 1:
        errs.append("CONFIG_BUDGET_WINNERS: winners_per_lane must be exactly 1; the scheduler executes one "
                    "winner per lane and never silently drops additional winners")
    if isinstance(bud.get("theory_cycles_max"), int) and bud.get("theory_cycles_max", 0) < 1:
        errs.append("CONFIG_BUDGET_THEORY_CYCLES: budgets.theory_cycles_max must be >= 1")
    if pol.get("autonomy") == "full_auto" and not (isinstance(bud.get("rounds_max"), int) and bud.get("rounds_max", 0) >= 1):
        errs.append("CONFIG_FULL_AUTO_ROUNDS: full_auto requires budgets.rounds_max >= 1 "
                    "(no unbounded auto-approved round loops)")
    infra = _block("infra", {})
    if not str(infra.get("facts_file") or "").strip():
        errs.append("CONFIG_INFRA_FACTS: infra.facts_file path required")
    if not isinstance(infra.get("max_concurrent_stage_jobs"), int) or infra.get("max_concurrent_stage_jobs", 0) < 1:
        errs.append("CONFIG_INFRA_SLOTS: infra.max_concurrent_stage_jobs must be int >= 1 (the platform's real quota)")
    if infra.get("drills") is not True:
        errs.append("CONFIG_INFRA_CANARY_REQUIRED: infra.drills must be true; the real integrated canary "
                    "cannot be silently skipped")
    return errs


def extension_resource_axes(cfg: dict[str, Any]) -> list[str]:
    """Project-declared extra resource axes (E1). Frozen at configure; every
    candidate vector, receipt and frontier comparison covers core+extension."""
    contract = cfg.get("resource_contract")
    rows = contract.get("extension_axes") if isinstance(contract, dict) else None
    return [str(r.get("key")) for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, dict) and str(r.get("key") or "")]


def resource_axes(cfg: dict[str, Any]) -> list[str]:
    """The nine core axes plus any configured extension axes, in order."""
    import eprogram
    return list(eprogram.RESOURCE_AXES) + extension_resource_axes(cfg)


def budget(cfg: dict[str, Any], key: str) -> int:
    """One budget accessor: the fallback is DEFAULT_CONFIG's value, never a
    per-call-site literal (v9.2's scattered literals had drifted apart)."""
    default = DEFAULT_CONFIG["budgets"].get(key)
    if default is None:
        raise KeyError(f"unknown budget key {key!r}")
    budgets = cfg.get("budgets") if isinstance(cfg.get("budgets"), dict) else {}
    value = budgets.get(key, default)
    if not _finite_number(value):
        value = default
    return float(value) if isinstance(default, float) else int(value)


def metric_spec(cfg: dict[str, Any]) -> dict[str, dict]:
    return {m["key"]: m for m in (cfg.get("metrics") or []) if isinstance(m, dict) and m.get("key")}


def primary_metric(cfg: dict[str, Any]) -> str:
    """Result key used for compact displays only; never the sole verdict."""
    ev = evaluation_contract(cfg)
    display_cell = str(ev.get("display_cell") or "")
    cell = cell_spec(cfg).get(display_cell) or {}
    return str(cell.get("result_key") or (cfg.get("project") or {}).get("primary_metric") or "")


def evaluation_contract(cfg: dict[str, Any]) -> dict[str, Any]:
    ev = cfg.get("evaluation_contract")
    return ev if isinstance(ev, dict) else {}


def evaluation_cells(cfg: dict[str, Any], *, roles: set[str] | None = None) -> list[dict]:
    cells = [c for c in (evaluation_contract(cfg).get("cells") or []) if isinstance(c, dict)]
    return [c for c in cells if c.get("role") in roles] if roles is not None else cells


def cell_spec(cfg: dict[str, Any]) -> dict[str, dict]:
    return {str(c["id"]): c for c in evaluation_cells(cfg) if c.get("id")}


def result_spec(cfg: dict[str, Any]) -> dict[str, dict]:
    """Result-key -> merged cell/metric definition.

    A reusable metric definition (for example accuracy) may appear in many
    dataset/task cells.  Arithmetic must therefore key scores by result_key,
    not by the metric definition key.
    """
    metrics = metric_spec(cfg)
    out: dict[str, dict] = {}
    for cell in evaluation_cells(cfg):
        rk = str(cell.get("result_key") or "")
        if rk:
            out[rk] = {**(metrics.get(str(cell.get("metric") or "")) or {}), **cell}
    return out


def result_direction(cfg: dict[str, Any], result_key: str) -> str:
    return str((result_spec(cfg).get(result_key) or {}).get("direction") or "max")


def result_value(raw: Any) -> float | None:
    """Return a finite point estimate from the public result schema."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
        return float(raw)
    if isinstance(raw, dict):
        value = raw.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)):
            return float(value)
    return None


def result_interval(raw: Any) -> tuple[float | None, float | None, float | None]:
    """Return ``(point, lower, upper)`` at the engine's fixed 95% level.

    Scalars have no supplied uncertainty and therefore return a degenerate
    interval. Structured results are accepted only after ``v_evaluate`` has
    checked provenance and zero extra training runs.
    """
    point = result_value(raw)
    if point is None:
        return None, None, None
    if not isinstance(raw, dict):
        return point, point, point
    uncertainty = raw.get("uncertainty")
    if not isinstance(uncertainty, dict):
        return point, point, point
    lo, hi = uncertainty.get("lower"), uncertainty.get("upper")
    if all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))
           for x in (lo, hi)):
        return point, float(lo), float(hi)
    return point, point, point


def noise_floor(cfg: dict[str, Any], cell_id: str, st: dict[str, Any] | None = None) -> float:
    """Literature/field-calibrated noise width for one evaluation cell (v11).

    0.0 (the default) reproduces v10 behavior exactly. When the user records a
    floor (published seed variance, leaderboard neighbor gaps - captured during
    the evidence/configure phase), a bare-scalar measurement no longer gets a
    free zero-width interval: hiding the error bar stops being the winning
    move, which is the adverse-selection fix the measurement audit demanded.

    v11.1 P3: in preplanned multi-seed mode the engine measures the actual
    seed-to-seed spread per cell (st["observed_noise"], >= 2 seed sets) and
    that measured value outranks the literature guess - our own runs on our
    own harness beat someone else's published variance. Observed noise lives
    in ENGINE STATE, not in the frozen evaluation contract, so calibration
    never rewrites a contract mid-project.
    """
    if st is not None:
        rec = (st.get("observed_noise") or {}).get(str(cell_id)) or {}
        w, sets = rec.get("width"), rec.get("sets")
        if isinstance(sets, int) and sets >= 2 \
                and isinstance(w, (int, float)) and not isinstance(w, bool) \
                and math.isfinite(float(w)) and float(w) > 0:
            return float(w)
    raw = ((cfg.get("evaluation_contract") or {}).get("noise_floors") or {}).get(str(cell_id))
    if isinstance(raw, (int, float)) and not isinstance(raw, bool) \
            and math.isfinite(float(raw)) and float(raw) > 0:
        return float(raw)
    return 0.0


def noise_floor_source(cfg: dict[str, Any], cell_id: str, st: dict[str, Any] | None = None) -> str:
    """'observed' | 'config' | 'none' - which authority the effective floor has."""
    if _observed_floor_active(cfg, cell_id, st):
        return "observed"
    return "config" if noise_floor(cfg, cell_id, None) > 0 else "none"


def _observed_floor_active(cfg: dict[str, Any], cell_id: str, st: dict[str, Any] | None) -> bool:
    if st is None:
        return False
    rec = (st.get("observed_noise") or {}).get(str(cell_id)) or {}
    w, sets = rec.get("width"), rec.get("sets")
    return isinstance(sets, int) and sets >= 2 \
        and isinstance(w, (int, float)) and not isinstance(w, bool) \
        and math.isfinite(float(w)) and float(w) > 0


def result_interval_with_floor(raw: Any, floor: float) \
        -> tuple[float | None, float | None, float | None]:
    """result_interval, but an UNREPORTED (zero-width) interval is widened to
    +-floor. A genuinely reported interval is kept as reported even when
    narrower - the honest paired interval is usually tighter than the field's
    floor, so reporting real uncertainty LOWERS one's own bar. An exactly
    zero-width REPORTED interval (lower==upper==point) is a claim of zero
    measurement noise; it is treated as unreported, so the substitution cannot
    be dodged by echoing the point as its own bounds."""
    point, lo, hi = result_interval(raw)
    if point is None:
        return None, None, None
    if floor > 0 and lo == point and hi == point:
        return point, point - floor, point + floor
    return point, lo, hi


def improvement_interval(candidate: Any, reference: Any, direction: str,
                         *, floor: float = 0.0) \
        -> tuple[float | None, float | None, float | None]:
    """Conservative interval for improvement without independence assumptions.

    The noise floor is applied ONCE to the comparison, not once per side:
    floors are recorded from the field's run-to-run spread and leaderboard
    neighbor gaps, which are already DELTA-scale quantities. Flooring both
    sides doubled the band (a scalar-vs-scalar comparison needed a 2*floor
    win), which silently made every noninferiority margin below 2*floor
    structurally unattainable - repairs could never settle parity. The floor
    widens the delta only when at least one side reported no real interval;
    two honestly-reported intervals use pure interval arithmetic.
    """
    cv, cl, cu = result_interval(candidate)
    rv, rl, ru = result_interval(reference)
    if None in (cv, cl, cu, rv, rl, ru):
        return None, None, None
    if direction == "min":
        delta, lo, hi = rv - cv, rl - cu, ru - cl
    else:
        delta, lo, hi = cv - rv, cl - ru, cu - rl
    scalar_c = (cl == cv == cu)
    scalar_r = (rl == rv == ru)
    if floor > 0 and (scalar_c or scalar_r):
        lo = min(lo, delta - floor)
        hi = max(hi, delta + floor)
    return delta, lo, hi


def resource_limits(cfg: dict[str, Any]) -> dict[str, float]:
    raw = (cfg.get("resource_contract") or {}).get("limits") or {}
    return {str(k): float(v) for k, v in raw.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) and float(v) > 0}


def budget_tolerance(cfg: dict[str, Any]) -> float:
    """Validity tolerance band for declared per-stage/eval budget caps.

    v12: caps are frozen at spec time, but real timing evidence only exists
    after implementation.  Under a registered RNG the cost trajectory is
    deterministic, so a cap set slightly too low invalidates the evidence,
    and every replacement rerun repeats the same overage - a structural
    livelock whose only exit was abandoning the node.  The band moves ONLY
    the validity judgment (usage > cap * band invalidates); every recorded
    number - usage accounting, receipts, capacity reservations, E-gate
    resource comparisons - stays the actual measurement.  The key is a
    documented mutable governance control (like policy.autonomy): it sits
    OUTSIDE the bootstrap contract digest, and changing it affects only
    future ingestions, never already-disposed evidence.  Default 1.0 keeps
    the historical strict semantics; the accessor clamps defensively while
    validate_config reports malformed values loudly.
    """
    raw = cfg.get("stage_budget_tolerance")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 1.0
    value = float(raw)
    if not math.isfinite(value) or value < 1.0:
        return 1.0
    return value


def bootstrap_contract_digest(cfg: dict[str, Any]) -> str:
    """Digest the user-confirmed scientific and resource contract.

    Supervision/tempo may change through their documented controls, but the
    objective, evaluation semantics, evidence-spend policy and project limits
    may not silently change after the mandatory bootstrap sign-off.
    """
    project = cfg.get("project") or {}
    # R7 external audit: freeze by exclusion, not by omission. budgets and
    # policy drive the real state machine (rounds_max, max_attempts, on_stuck,
    # critic_isolation), and README promises they are part of the signed
    # contract - only the DOCUMENTED mutable controls stay outside the digest:
    # policy.autonomy (evo autonomy) and the preset word with its seven
    # preset-owned tempo keys (the documented one-word flip).
    policy = {k: v for k, v in (cfg.get("policy") or {}).items()
              if k not in ("autonomy", "preset") + PRESET_KEYS}
    # R9 audit: the project block now freezes BY EXCLUSION too (the stated
    # principle above) - vcs, code_root, rehearsal and docs all change
    # execution semantics (worktree rules, code root, per-node rehearsal
    # duty, card inputs) and used to drift silently after sign-off because the
    # old include-list carried only four fields. Only the display-only name
    # stays outside the digest.
    payload = {
        "project": {k: v for k, v in project.items() if k not in ("name",)},
        "metrics": cfg.get("metrics"),
        "evaluation_contract": cfg.get("evaluation_contract"),
        "evidence_policy": cfg.get("evidence_policy"),
        "resource_contract": cfg.get("resource_contract"),
        "research": cfg.get("research"),
        "budgets": cfg.get("budgets"),
        "policy": policy,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def budget_limits(budget: Any) -> dict[str, float]:
    raw = (budget or {}).get("limits") if isinstance(budget, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {str(k): float(v) for k, v in raw.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v)) and float(v) > 0}


def tracked_budget(budget: Any, cfg: dict[str, Any]) -> dict[str, float]:
    tracked = resource_limits(cfg)
    return {k: v for k, v in budget_limits(budget).items() if k in tracked}


def eval_budget(spec: dict) -> dict[str, float]:
    return budget_limits(((spec or {}).get("eval") or {}).get("budget"))


def target_cells(cfg: dict[str, Any]) -> list[dict]:
    return evaluation_cells(cfg, roles={"target"})


def guardrail_cells(cfg: dict[str, Any]) -> list[dict]:
    return evaluation_cells(cfg, roles={"guardrail"})


def scaling_mode(cfg: dict[str, Any]) -> str:
    return str((cfg.get("evidence_policy") or {}).get("scaling_mode") or "off")


def training_replication_policy(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = (cfg.get("evidence_policy") or {}).get("training_replication") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def workflow_seeds(spec: dict) -> list[Any]:
    """The ordered seed lanes for this workflow (empty for non-training work)."""
    rep = (spec or {}).get("training_replication")
    if not isinstance(rep, dict) or rep.get("source") != "workflow":
        return []
    seeds = rep.get("seeds")
    return list(seeds) if isinstance(seeds, list) else []


def seed_slug(seed: Any) -> str:
    """Filesystem-safe spelling of a validated training seed."""
    if isinstance(seed, bool):
        raise ValueError("boolean is not a training seed")
    if isinstance(seed, int):
        if seed < 0:
            raise ValueError("training seeds must be >= 0 (a leading '-' is not a safe "
                             "slug and can be parsed as a CLI flag in launch commands)")
        return str(seed)
    value = str(seed).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value):
        raise ValueError(f"training seed {seed!r} is not a safe slug")
    return value


def resolve_seed_template(value: Any, seed: Any) -> Any:
    """Resolve the literal ``{seed}`` token without applying Python format()."""
    if not isinstance(value, str):
        return value
    return value.replace("{seed}", seed_slug(seed))


def workflow_seed(spec: dict, replica_index: int = 0) -> Any | None:
    seeds = workflow_seeds(spec)
    return seeds[replica_index] if 0 <= replica_index < len(seeds) else None


# (R10-012 reconciliation) There is deliberately NO repeat-specific landing
# derivation anymore. v11.4 derived `_seed-X` paths for the bought-back
# repeat attempt, but the frozen launch command of a single-run spec keeps
# writing its fixed paths - so the command, the expected landings, the
# product acceptance check and the registry registration contradicted each
# other. One rule for every attempt now: resolve_seed_template. The repeat
# attempt reuses the spec's own resolved landings; safety against the sealed
# first attempt comes from the four standing mechanisms - prepare-time
# preexisting-landing archives, the landing lease, immutable per-RUN evidence
# snapshots, and registry generation history.


def workflow_replica_count(spec: dict) -> int:
    seeds = workflow_seeds(spec)
    return len(seeds) if seeds else 1


def ablation_mode(cfg: dict[str, Any]) -> str:
    return str((((cfg.get("evidence_policy") or {}).get("ablation") or {}).get("mode")) or "off")


def stage_slots(cfg: dict[str, Any]) -> int:
    infra = cfg.get("infra") or {}
    v = infra.get("max_concurrent_stage_jobs")
    return v if isinstance(v, int) and v >= 1 else 1


def stages_of(spec: dict) -> list[dict]:
    """Return scheduler-visible stages in declared topological order."""
    wf = (spec or {}).get("workflow") or {}
    if isinstance(wf, dict) and isinstance(wf.get("stages"), list):
        return [dict(s) for s in wf["stages"] if isinstance(s, dict)]
    return []


def stage_requires_ledger(stage: dict) -> bool:
    control = (stage or {}).get("control") or {}
    return control.get("mode") == "preregistered_adaptive" or \
        control.get("multiplicity") == "algorithmic"


def stage_budget_totals(spec: dict) -> dict[str, float]:
    """Sum declared per-stage caps by unit for approval displays.

    Units are intentionally extensible: GPU hours, candidate evaluations, API
    tokens and communication rounds are incomparable, but equal units can be
    added without pretending stage count is resource cost.
    """
    out: dict[str, float] = {}
    replicas = workflow_replica_count(spec)
    for stage in stages_of(spec):
        limits = ((stage.get("budget") or {}).get("limits") or {})
        if not isinstance(limits, dict):
            continue
        for unit, value in limits.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                out[str(unit)] = out.get(str(unit), 0.0) + float(value) * replicas
    return out


def experiment_class(spec: dict) -> str:
    """A node's explicitly declared experiment class."""
    return str((spec or {}).get("experiment_class") or "")


def mode(cfg: dict[str, Any]) -> str:
    return str((cfg.get("project") or {}).get("mode") or "engineering")


def is_research(cfg: dict[str, Any]) -> bool:
    return mode(cfg) == "research"


def focus_directions(cfg: dict[str, Any]) -> list[dict]:
    fds = (cfg.get("project") or {}).get("focus_directions")
    return [f for f in fds if isinstance(f, dict) and f.get("id")] if isinstance(fds, list) else []


def sota_enabled(cfg: dict[str, Any]) -> bool:
    return bool(is_research(cfg) and (cfg.get("research") or {}).get("sota_enabled"))
