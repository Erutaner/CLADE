"""Per-task artifact validators for the v10 scientific-program engine.

Design rule: validators never judge science; they enforce structure that makes
hollow work impossible to submit unnoticed:
  - every citation must resolve to the evidence/mechanism store;
  - critic quotes must be literal (whitespace-normalized) substrings of the reviewed text;
  - implementation scope is distinct from irreducible mechanism novelty;
  - effects bind kernels to measurable intermediates, cells and resource vectors;
  - predictions are numeric and pre-registered; conclusions must address each one;
  - repo-fact claims carry [src: path] tags pointing at real files;
  - infrastructure facts carry src paths into the user's knowledge base / repo;
  - workflow-stage artifact URIs are unique registry-wide (no silent checkpoint
    overwrites) and a plan that would retrain an available shared artifact must
    consume it or waive reuse explicitly;
  - claimed theory survives an adversarial challenge with rigor set only by T;
  - (v8) formal lanes carry a POSED problem (typed symbols, Given, Want) and a
    derivation as a numbered step chain whose premises the engine resolves -
    decorative notation and orphan steps are rejections, not style issues;
  - (v8) the novelty regime is mode-dependent: engineering runs demand fit and
    non-triviality (borrowing published mechanisms is legitimate); research
    runs demand difference from the nearest published work on top of that;
  - (v8) high-complexity implementations pass a fidelity audit whose claim->code
    map is string-checked against the real files.
"""
from __future__ import annotations

import math
import hashlib
import json
import os
import re
import statistics
from pathlib import Path
from typing import Any

import eartifact
import ecanary
import econfig
import eflow
import egraph
import einfra
import eprogram
import erehearsal
import erecover
import eseal
import eutil
import evcs

BANNED_FILLER = ("todo", "tbd", "placeholder", "lorem ipsum", "fill me", "xxx")

SRC_TAG = re.compile(r"\[src:\s*([^\]\s][^\]]*?)(?::(\d+))?\s*\]")
CIT_E = re.compile(r"\[(E\d{3,4})\]")
CIT_M = re.compile(r"\[(M\d{3,4})\]")
B_ID = re.compile(r"^\s*[-*]\s*(B\d+)\s*:", re.M)
V_ID = re.compile(r"^\s*[-*]\s*(V\d+)\s*:", re.M)
F_ID = re.compile(r"^\s*[-*]\s*(F\d+)\s*:", re.M)
A_ID = re.compile(r"\b(A\d+)\s*:")
QUOTE_LINE = re.compile(r"^\s*QUOTE:\s*(.+?)\s*$", re.M)
TOPIC_LINE = re.compile(r"^\s*[-*]\s*topic\s*:\s*(.+?)\s*$", re.I | re.M)
PAPERISH = re.compile(r"(arxiv\.org|doi\.org|10\.\d{4,9}/)", re.I)
STAGE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$")
STAGE_METRIC_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_STAGE_RESULT_UNREAD = object()

CORE_PALETTE_SOURCE_FIELDS = (
    "old_program", "new_program", "program_operations", "irreducible_core",
    "necessary_components", "support_components", "core_math", "assumptions",
    "reported_effect", "ablation_support", "resource_delta", "gain_confound",
    "transfer_conditions", "failure_modes",
)

# v8 formal problem ladder ---------------------------------------------------------
# Symbol declaration line in a PROBLEM doc's Setup section:
#   - sym: W : R^{d x k} - the value-field weight matrix
SYM_LINE = re.compile(r"^\s*[-*]\s*sym:\s*(\S+)\s*:\s*([^-\n]+?)\s*-\s*(.+?)\s*$", re.M)
# Derivation chain step in a THEORY doc:
#   - S3 [from A1, S2]: <claim> ; reads: <plain meaning> ; fails-if: <condition>
STEP_LINE = re.compile(r"^\s*[-*]\s*(S\d+)\s*\[from\s+([^\]]+)\]\s*:\s*(.+?)\s*$", re.M)
DO_LINE = re.compile(r"^\s*[-*]\s*(DO\d+)\s*:\s*(.+?)\s*$", re.M)
# Lineage claim in a THEORY doc's 'relation to parent' section:
#   [relation: reduction|component|recipe|contrast]
# Fidelity claim row:  - <claim> -> path/to/file.py :: CODE: <literal snippet>
FID_ROW = re.compile(r"^\s*[-*]\s*(.+?)\s*->\s*`?([\w./\\-]+\.\w{1,8})`?\s*::\s*CODE:\s*(.+?)\s*$", re.M)
BUILD_OPERATOR_ROW = re.compile(
    r"^\s*[-*]\s*(OP\d+)\s*\[\s*((?:KC\d+\s*,?\s*)+)\]\s*->\s*`?([\w./\\-]+\.\w{1,8})`?\s*$", re.M)
PROBE_FIELD_ROW = re.compile(
    r"^\s*PROBE_FIELD:\s*([A-Za-z][A-Za-z0-9_.-]{0,63})\s*->\s*`?([\w./\\-]+\.\w{1,8})`?\s*::\s*CODE:\s*(.+?)\s*$",
    re.M)
# Artifact wiring rows (v10.2): the highest-frequency infrastructure error is
# code reading the wrong artifact or saving to an undeclared place, and no
# check bound the declared consumes/produces contract to actual code.  These
# rows are the fidelity-style literal binding for that contract: source token
# (AR### | stage:<name> | the uri itself) -> file :: literal snippet.
# A lane name is a filesystem path component (lane brief / lane dir), so it is
# a slug by contract - never free text.
LANE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
ARTIFACT_READ_ROW = re.compile(
    r"^\s*READS:\s*(\S+)\s*->\s*`?([\w./\\-]+\.\w{1,8})`?\s*::\s*CODE:\s*(.+?)\s*$", re.M)
ARTIFACT_WRITE_ROW = re.compile(
    r"^\s*WRITES:\s*(\S+)\s*->\s*`?([\w./\\-]+\.\w{1,8})`?\s*::\s*CODE:\s*(.+?)\s*$", re.M)
PROBE_ARTIFACT_LINE = re.compile(r"^\s*PROBE_ARTIFACT:\s*(\S.*?)\s*$", re.M)
PROBE_SOURCE_LINE = re.compile(r"^\s*PROBE_SOURCE:\s*(\S.*?)\s*$", re.M)
BRIDGE_ADAPTER_ROW = re.compile(
    r"^\s*BRIDGE_ADAPTER:\s*`?([\w./\\-]+\.\w{1,8})`?\s*::\s*CODE:\s*(.+?)\s*$", re.M)
REPAIR_SCOPE_LINE = re.compile(r"^\s*REPAIR_SCOPE:\s*(evaluation|workflow)\s*$", re.M)
REPAIR_CHANGED_FILE_LINE = re.compile(
    r"^\s*CHANGED_FILE:\s*`?([\w./\\-]+)`?\s*$", re.M)
WORKFLOW_REUSE_ARGUMENT_LINE = re.compile(
    r"^\s*WORKFLOW_REUSE_ARGUMENT:\s*(.+?)\s*$", re.M)
ABLATION_FACTOR_LINE = re.compile(r"^\s*FACTOR:\s*(.+?)\s*$", re.M)
ABLATION_CONTROL_LINE = re.compile(r"^\s*CONTROL:\s*(.+?)\s*::\s*VERIFIED:\s*(.+?)\s*$", re.M)
STEP_MARK_WANT = "establishes: Want"


class Ctx:
    """Validation context handed to every validator."""

    def __init__(self, store, st: dict, cfg: dict, g: dict, reg: dict | None = None):
        self.store = store
        self.st = st
        self.cfg = cfg
        self.g = g
        self.reg = reg if reg is not None else store.load_artifacts()
        # Per-instance memo for append-only ledgers the AGENT writes between
        # CLI invocations and the engine never writes: within one validation
        # window their bytes are fixed, so re-reading them per loop iteration
        # (evidence_years per collision edge, mech_by_id per historical row)
        # was pure waste.  Deliberately NOT memoized: observations, lessons,
        # errors - the engine appends to those during accept transitions.
        self._memo: dict[str, Any] = {}

    # -- common loaders -------------------------------------------------------
    def dossier_ids(self) -> tuple[set[str], set[str], set[str]]:
        """(B, V, F) ids. R9 (external audit r6): SOURCE-AWARE. The addendum is
        a close-round output whose validator only checks B rows, so unioning
        V/F from it let an agent mint a phantom invariant that then satisfied
        the evaluate comparability gate. Invariants/facts come from the sealed
        bootstrap dossier only; the addendum may contribute bottlenecks (B)."""
        cached = self._memo.get("dossier_ids")
        if cached is None:
            base = ""
            addendum = ""
            for name, sink in (("PROBLEM_DOSSIER.md", "base"), ("DOSSIER_ADDENDUM.md", "addendum")):
                p = self.store.profile_dir() / name
                if p.exists():
                    if sink == "base":
                        base += eutil.read_text(p) + "\n"
                    else:
                        addendum += eutil.read_text(p) + "\n"
            cached = (set(B_ID.findall(base + addendum)),
                      set(V_ID.findall(base)), set(F_ID.findall(base)))
            self._memo["dossier_ids"] = cached
        return cached

    def draft_ledgers(self) -> set[str]:
        """Ledgers whose UNACCEPTED suffix this validation may see (R9).

        A ledger task validates the rows it is submitting right now, including
        their cross-references to each other, so its own draft must be visible
        to it. Every other task sees accepted history only."""
        return getattr(self, "_draft_ledgers", set())

    def use_draft_ledgers(self, *names: str) -> None:
        self._draft_ledgers = set(names)
        for key in ("evidence", "mech", "collisions", "sota"):
            self._memo.pop(key, None)

    def _accepted(self, name: str, rows: list[dict]) -> list[dict]:
        """Committed view of an append-only ledger (R9, external audit r6).

        The acceptance watermark froze prefix IMMUTABILITY but no reader ever
        applied it, so rows appended by a task that was later rejected and
        cancelled stayed visible: they were displayed in bundles, resolved
        citations and satisfied coverage duties as if a ledger validator had
        passed them. Consumers now see only accepted history; the ledger's OWN
        validator still reads the raw file so its unaccepted suffix stays
        repairable."""
        if name in self.draft_ledgers():
            return rows
        return accepted_ledger_rows(self.st, name, rows)

    def _evidence_rows(self) -> list[dict]:
        cached = self._memo.get("evidence")
        if cached is None:
            cached = self._memo["evidence"] = self._accepted("evidence", self.store.evidence())
        return cached

    def evidence_ids(self) -> set[str]:
        return {r.get("id") for r in self._evidence_rows()}

    def evidence_years(self) -> dict[str, int]:
        return {r.get("id"): r.get("year") for r in self._evidence_rows()
                if isinstance(r.get("year"), int)}

    def mech_by_id(self) -> dict[str, dict]:
        cached = self._memo.get("mech")
        if cached is None:
            cached = self._memo["mech"] = {r.get("id"): r for r in
                                           self._accepted("mech", self.store.mech_cards())}
        return cached

    def collision_by_id(self) -> dict[str, dict]:
        cached = self._memo.get("collisions")
        if cached is None:
            cached = self._memo["collisions"] = {r.get("id"): r for r in
                                                 self._accepted("collision", self.store.collision_audits())}
        return cached

    def recent_year(self) -> int:
        return int(self.cfg.get("budgets", {}).get("evidence_recent_year", 0))


    # -- v8 additions ----------------------------------------------------------
    def is_research(self) -> bool:
        return econfig.is_research(self.cfg)

    def sota_rows(self) -> list[dict]:
        cached = self._memo.get("sota")
        if cached is None:
            p = self.store.evo / "evidence" / "SOTA.jsonl"
            cached = self._memo["sota"] = self._accepted(
                "sota", eutil.read_jsonl(p) if p.exists() else [])
        return cached

    def sota_ids(self) -> set[str]:
        return {str(r.get("id") or "") for r in self.sota_rows()}

    # -- v9 additions ----------------------------------------------------------
    def obs_ids(self) -> set[str]:
        """Ids in the phenomenon ledger (OBSERVATIONS.jsonl) - quantitative
        anomalies mined from this graph's own runs, citable as diagnosis
        anchors and assumption sources."""
        return {str(r.get("id") or "")
                for r in self.store.observations(self.st, active_only=True)}

    def winner_sketch(self, lane: dict) -> dict | None:
        if not lane.get("sketches_path") or not lane.get("winner_sketch"):
            return None
        p = eutil.rpath(self.store.repo, lane["sketches_path"])
        if not p.exists():
            return None
        try:
            import json
            data = json.loads(eutil.read_text(p))
        except Exception:
            return None
        for s in data.get("sketches") or []:
            if s.get("sketch_id") == lane["winner_sketch"]:
                return s
        return None

    def problem_symbols(self, lane: dict) -> list[str]:
        """Symbols declared in the lane's posed problem doc (formal lanes)."""
        pp = lane.get("problem_path")
        if not pp or not _exists(self, pp):
            return []
        text = eutil.read_text(eutil.rpath(self.store.repo, pp))
        setup = eutil.find_section(eutil.md_sections(text), "setup") or ""
        return [m[0] for m in SYM_LINE.findall(setup)]


# ---- small helpers ---------------------------------------------------------------

def _exists(ctx: Ctx, relp: str) -> bool:
    return eutil.rpath(ctx.store.repo, relp).exists()


def _probe_path_errors(path: Any, field: str) -> list[str]:
    value = str(path or "").strip()
    if not value:
        return [f"PROBE_PATH: {field} must be an exact repo-relative JSON path"]
    p = Path(value)
    errs: list[str] = []
    if p.is_absolute() or ".." in p.parts:
        errs.append(f"PROBE_PATH_SCOPE: {field} must stay inside the repository")
    if p.suffix.lower() != ".json":
        errs.append(f"PROBE_PATH_JSON: {field} must end in .json so fields can be validated mechanically")
    if any(ch in value for ch in ("*", "?", "[", "]")):
        errs.append(f"PROBE_PATH_GLOB: {field} must be exact, not a glob")
    unknown = re.findall(r"\{([^{}]+)\}", value)
    if any(token != "seed" for token in unknown):
        errs.append(f"PROBE_PATH_TEMPLATE: {field} may use only the literal '{{seed}}' template token")
    return errs


def probe_artifact_errors(ctx: Ctx, path: str, required_fields: list[str], *, where: str) -> list[str]:
    """Validate a probe observation file and return field-specific failures."""
    if not path or not _exists(ctx, path):
        return [f"PROBE_ARTIFACT_MISSING: {where}: expected probe artifact {path!r} does not exist"]
    try:
        data = eutil.read_json(eutil.rpath(ctx.store.repo, path), None)
    except (OSError, SystemExit) as exc:
        return [f"PROBE_ARTIFACT_JSON: {where}: {path!r} is not readable valid JSON ({exc})"]
    if not isinstance(data, dict):
        return [f"PROBE_ARTIFACT_SHAPE: {where}: {path!r} must contain a JSON object"]
    errs: list[str] = []
    for field in required_fields:
        value = data.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            errs.append(f"PROBE_ARTIFACT_FIELD: {where}: {path!r}.{field} must be a finite numeric observation")
    return errs


def idea_probe_seed_template_errors(cfg: dict, mp: dict, *, purpose: str = "",
                                    intent: str = "") -> list[str]:
    """v12 (field deadlock T0611): cross-check probe mode x artifact template
    BEFORE the idea seals. The plan layer copies the sealed probe verbatim
    (SPEC_PROBE_BINDING), so a combination admitted at maturation and refused
    at planning is a jointly unsatisfiable contract with no legal submission.
    A '{seed}' template is only meaningful when the NODE will actually run
    per-seed workflows: the replication policy must be preplanned, and the
    lane must be a candidate on a non-platform intent (an exploratory scout
    and a platform node are forced to a single run at plan time). The class
    axis (a candidate whose node turns out non-train) is plan-time knowledge
    the idea cannot see - the plan-layer refusal stays honest about the exit
    for that residual. (Rule: any probe mode x template combination must be
    constrained identically at the idea layer, the plan layer and the runtime
    expansion in expected_probe_observations.)"""
    if "{seed}" not in str((mp or {}).get("artifact") or ""):
        return []
    if econfig.training_replication_policy(cfg).get("mode") != "preplanned":
        return ["IDEA_PROBE_SEED_TEMPLATE: mechanism_probe.artifact carries '{seed}' but the "
                "project's training_replication policy is not preplanned - there is one "
                "training run, so one observation; drop the placeholder"]
    if purpose in econfig.EXPLORATORY_PURPOSES or intent == "platform":
        return ["IDEA_PROBE_SEED_TEMPLATE: mechanism_probe.artifact carries '{seed}' but this "
                "lane's node is forced to a single run at plan time (exploratory/platform) - "
                "per-seed observations cannot exist; drop the placeholder"]
    return []


def expected_probe_observations(spec: dict) -> list[dict]:
    """Resolved runtime probe artifacts expected in normalized evaluation."""
    probe = (spec or {}).get("probe_execution")
    if not isinstance(probe, dict):
        return []
    template = str(probe.get("artifact") or "")
    seeds = econfig.workflow_seeds(spec)
    if probe.get("mode") == "same_run" and seeds:
        return [{"seed": seed, "artifact": str(econfig.resolve_seed_template(template, seed))}
                for seed in seeds]
    # v12 (field deadlock T0611): an eval-only intervention under preplanned
    # complete-workflow replication may read the sealed per-seed checkpoints
    # and keep one observation per seed - mirror the same_run expansion when
    # the sealed template says so. (Rule: any probe mode x template combination
    # must be constrained identically at the idea layer, the plan layer and
    # this runtime expansion - a combination the seal admits may never be
    # vetoed downstream.)
    if probe.get("mode") == "eval_intervention" and seeds and "{seed}" in template:
        return [{"seed": seed, "artifact": str(econfig.resolve_seed_template(template, seed))}
                for seed in seeds]
    return [{"seed": None, "artifact": template}]


def active_probe_unavailable(ctx: Ctx, node: dict) -> bool:
    """Derive a probe waiver from the adopted producer RUN, never a sticky node bit."""
    active_ids = {str(value) for value in (node.get("evidence_heads") or {}).values() if str(value)}
    for run in ctx.st.get("runs", []):
        if str(run.get("id") or "") not in active_ids or run.get("adoption_status") != "adopted":
            continue
        if run.get("probe_evidence_status") == "unavailable" and run.get("probe_gap_receipt"):
            return True
    return False


def probe_snapshot_map(run: dict) -> dict[str, str]:
    """Return only one attempt's active declared-to-snapshot bindings."""
    resolved: dict[str, str] = {}
    for row in run.get("probe_artifact_snapshots") or []:
        if not isinstance(row, dict):
            continue
        declared = str(row.get("declared_artifact") or "")
        snapshot = str(row.get("snapshot_artifact") or "")
        if declared and snapshot:
            resolved[declared] = snapshot
    return resolved


def active_probe_snapshot_map(ctx: Ctx, node: dict, *,
                              include_run: dict | None = None) -> dict[str, str]:
    """Resolve declared probe landing paths to immutable RUN-owned snapshots."""
    active_ids = {str(value) for value in (node.get("evidence_heads") or {}).values() if str(value)}
    selected = [run for run in ctx.st.get("runs", [])
                if str(run.get("id") or "") in active_ids
                and run.get("adoption_status") == "adopted"]
    if include_run is not None and include_run not in selected:
        selected.append(include_run)
    resolved: dict[str, str] = {}
    for run in selected:
        resolved.update(probe_snapshot_map(run))
    return resolved


def stage_probe_errors(ctx: Ctx, spec: dict, stage: dict, seed: Any | None, *, where: str,
                       allow_unavailable: bool = False,
                       artifact_sources: dict[str, str] | None = None) -> list[str]:
    """Require the real same-run observation at its declared producer stage."""
    probe = (spec or {}).get("probe_execution")
    if not isinstance(probe, dict) or probe.get("mode") != "same_run" or \
            str(probe.get("producer_stage") or "") != str(stage.get("name") or ""):
        return []
    if allow_unavailable:
        return []
    artifact = str(probe.get("artifact") or "")
    try:
        resolved = str(econfig.resolve_seed_template(artifact, seed)) if seed is not None else artifact
    except ValueError as exc:
        return [f"PROBE_SEED_RESOLUTION: {where}: {exc}"]
    if "{seed}" in resolved:
        return [f"PROBE_SEED_UNRESOLVED: {where}: probe artifact {artifact!r} needs a workflow seed"]
    source = (artifact_sources or {}).get(resolved, resolved)
    return probe_artifact_errors(ctx, source, [str(x) for x in (probe.get("required_fields") or [])],
                                 where=where)


def probe_result_errors(ctx: Ctx, spec: dict, metrics: dict, *, where: str,
                        allow_unavailable: bool = False,
                        artifact_sources: dict[str, str] | None = None) -> list[str]:
    """Cross-check normalized probe evidence against the frozen JSON artifacts."""
    probe = (spec or {}).get("probe_execution")
    if not isinstance(probe, dict):
        if metrics.get("_mechanism_probe") is not None:
            return [f"EVAL_PROBE_UNDECLARED: {where}: _mechanism_probe is present without a frozen probe_execution"]
        return []
    block = metrics.get("_mechanism_probe")
    if allow_unavailable:
        # A signed gap receipt excludes the whole untrusted probe payload. Core
        # metrics remain validated by the caller; partial malformed probe bytes
        # must not make an explicit same-RUN disposition impossible.
        return []
    if not isinstance(block, dict):
        # R6 blind-operator audit: this error used to name no schema while the
        # only card carrying the example (evaluate) cannot be scheduled until
        # the envelope already exists - circular disclosure. Self-describe.
        example = {"mode": probe.get("mode"), "signal": probe.get("signal"),
                   "expect": probe.get("expect"),
                   "required_fields": [str(x) for x in (probe.get("required_fields") or [])],
                   "observations": [
                       {"seed": r.get("seed"), "artifact": str(r.get("artifact") or ""),
                        "values": {str(f): "<number>" for f in (probe.get("required_fields") or [])}}
                       for r in expected_probe_observations(spec)]}
        return [f"EVAL_PROBE_MISSING: {where}: metrics JSON needs structured _mechanism_probe evidence - "
                "copy this envelope EXACTLY (bindings from the frozen plan) and fill each numeric value: "
                + json.dumps(example, ensure_ascii=False)]
    errs: list[str] = []
    for field, expected in (("mode", probe.get("mode")), ("signal", probe.get("signal")),
                            ("expect", probe.get("expect"))):
        if block.get(field) != expected:
            errs.append(f"EVAL_PROBE_BINDING: {where}: _mechanism_probe.{field} must equal the frozen plan")
    required = [str(x) for x in (probe.get("required_fields") or [])]
    if block.get("required_fields") != required:
        errs.append(f"EVAL_PROBE_FIELDS_BINDING: {where}: _mechanism_probe.required_fields must equal {required}")
    expected_rows = expected_probe_observations(spec)
    rows = block.get("observations")
    if not isinstance(rows, list) or len(rows) != len(expected_rows):
        errs.append(f"EVAL_PROBE_OBSERVATIONS: {where}: expected {len(expected_rows)} observation record(s)")
        rows = []
    # (identity sweep #28) observation set membership goes through the
    # canonical spelling on BOTH sides - a raw-string keyed set judged a
    # legal spelling variant of a declared probe landing as "unexpected"
    expected_by_artifact = {eutil.norm_uri(str(row["artifact"])): row for row in expected_rows}
    canon_sources = {eutil.norm_uri(str(k)): v for k, v in (artifact_sources or {}).items()}
    seen: set[str] = set()
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errs.append(f"EVAL_PROBE_OBSERVATION_SHAPE: {where}: observations[{i}] must be an object")
            continue
        artifact = str(row.get("artifact") or "")
        canon = eutil.norm_uri(artifact)
        expected = expected_by_artifact.get(canon)
        if expected is None or canon in seen:
            errs.append(f"EVAL_PROBE_ARTIFACT_SET: {where}: observations[{i}] has unexpected or duplicate artifact {artifact!r}")
            continue
        seen.add(canon)
        if _seed_token(row.get("seed")) != _seed_token(expected.get("seed")):
            errs.append(f"EVAL_PROBE_SEED: {where}: observations[{i}].seed must match {expected.get('seed')!r}")
        source_artifact = canon_sources.get(canon, artifact)
        artifact_errs = probe_artifact_errors(ctx, source_artifact, required,
                                              where=f"{where} observation[{i}]")
        errs.extend(artifact_errs)
        data = eutil.read_json(eutil.rpath(ctx.store.repo, source_artifact), {}) if not artifact_errs else {}
        values = row.get("values")
        if not isinstance(values, dict) or set(values) != set(required):
            errs.append(f"EVAL_PROBE_VALUES: {where}: observations[{i}].values must contain exactly {required}")
            continue
        for field in required:
            value = values.get(field)
            source = data.get(field) if isinstance(data, dict) else None
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                errs.append(f"EVAL_PROBE_VALUE: {where}: observations[{i}].values.{field} must be finite numeric")
            elif not isinstance(source, (int, float)) or isinstance(source, bool) or \
                    not math.isclose(float(value), float(source), rel_tol=1e-12, abs_tol=1e-12):
                errs.append(f"EVAL_PROBE_VALUE_MISMATCH: {where}: observations[{i}].values.{field} must equal "
                            f"the immutable observation for {artifact!r}")
    if seen != set(expected_by_artifact):
        errs.append(f"EVAL_PROBE_ARTIFACT_SET: {where}: observation artifacts must exactly match the frozen plan")
    return errs


def mechanism_probe_assessment(probe: dict | None, metrics: dict) -> dict:
    """Mechanically settle a frozen intermediate-signal predicate."""
    if not isinstance(probe, dict) or not probe.get("signal"):
        return {"status": "not_applicable"}
    rule = probe.get("decision_rule") if isinstance(probe.get("decision_rule"), dict) else {}
    field = str(rule.get("field") or "")
    values = [float((row.get("values") or {})[field])
              for row in ((metrics.get("_mechanism_probe") or {}).get("observations") or [])
              if isinstance(row, dict) and isinstance((row.get("values") or {}).get(field), (int, float))
              and not isinstance((row.get("values") or {}).get(field), bool)]
    aggregation = str(rule.get("aggregation") or "")
    if not values or aggregation not in ("mean", "median", "min", "max"):
        return {"status": "unclear", "field": field, "values": values,
                "reason": "missing observations or invalid frozen aggregation"}
    aggregate = (statistics.mean(values) if aggregation == "mean" else
                 statistics.median(values) if aggregation == "median" else
                 min(values) if aggregation == "min" else max(values))
    comparison = str(rule.get("comparison") or "")

    def _num(key: str):
        value = rule.get(key)
        return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    threshold, lower, upper = _num("threshold"), _num("lower"), _num("upper")
    if comparison == ">=" and threshold is not None:
        confirmed = aggregate >= threshold
    elif comparison == "<=" and threshold is not None:
        confirmed = aggregate <= threshold
    elif comparison == "between" and lower is not None and upper is not None:
        confirmed = lower <= aggregate <= upper
    else:
        # Same graceful posture as the malformed-aggregation branch above:
        # a malformed frozen rule yields unclear, never a KeyError crash.
        return {"status": "unclear", "field": field, "values": values,
                "aggregate": aggregate, "reason": "invalid frozen comparison"}
    return {"status": "confirmed" if confirmed else "refuted", "field": field,
            "values": values, "aggregation": aggregation, "aggregate": aggregate,
            "comparison": comparison,
            **({"threshold": rule.get("threshold")} if comparison != "between" else
               {"lower": rule.get("lower"), "upper": rule.get("upper")})}


def _nontrivial(text: Any, min_len: int, field: str, errs: list[str]) -> None:
    s = str(text or "").strip()
    if len(s) < min_len:
        errs.append(f"FIELD_TOO_SHORT: {field} needs >= {min_len} chars of substance (got {len(s)})")
        return
    low = s.lower()
    for bad in BANNED_FILLER:
        if bad in low:
            errs.append(f"FIELD_FILLER: {field} contains filler token '{bad}'")
            return


def _require_sections(text: str, names: list[str], where: str, errs: list[str],
                      min_chars: int = 40) -> dict[str, str]:
    secs = eutil.md_sections(text)
    found: dict[str, str] = {}
    for name in names:
        body = eutil.find_section(secs, name)
        if body is None:
            errs.append(f"MD_SECTION_MISSING: {where}: no '{name}' heading")
        elif len(body.strip()) < min_chars:
            errs.append(f"MD_SECTION_THIN: {where}: section '{name}' has < {min_chars} chars")
        else:
            found[name] = body
    return found


def _read_md(ctx: Ctx, relp: str, errs: list[str]) -> str | None:
    p = eutil.rpath(ctx.store.repo, relp)
    if not p.exists():
        errs.append(f"OUTPUT_MISSING: expected file {relp}")
        return None
    return eutil.read_text(p)


def _read_json(ctx: Ctx, relp: str, errs: list[str]) -> Any:
    p = eutil.rpath(ctx.store.repo, relp)
    if not p.exists():
        errs.append(f"OUTPUT_MISSING: expected file {relp}")
        return None
    try:
        return json.loads(eutil.read_text(p))
    except Exception as exc:
        errs.append(f"OUTPUT_BAD_JSON: {relp}: {exc}")
        return None


def json_file_digest(ctx: Ctx, relp: str) -> str:
    """Digest the parsed JSON canonically so whitespace edits do not rebind it."""
    data = eutil.read_json(eutil.rpath(ctx.store.repo, relp), None)
    if data is None:
        return ""
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def text_file_digest(ctx: Ctx, relp: str) -> str:
    """Byte-stable UTF-8 digest for immutable non-JSON contracts."""
    p = eutil.rpath(ctx.store.repo, relp)
    if not p.exists():
        return ""
    return hashlib.sha256(eutil.read_text(p).encode("utf-8")).hexdigest()


def core_palette_projection(ctx: Ctx, lane: dict,
                            cards: list[dict] | None = None) -> tuple[dict, dict]:
    """Deterministically project selected actual-work cards into blind cores.

    Generation and integrity auditing share this function.  The audit can
    therefore prove that the sealed anonymous palette is still the projection
    of the M/E records named only in its audit-only sidecar, rather than merely
    trusting the sidecar's own assertion.
    """
    chosen = cards if cards is not None else sorted(
        (card for card in ctx.store.mech_cards() if card.get("lane") == lane.get("id")),
        key=lambda card: str(card.get("id") or ""))
    evidence_by_id = {str(row.get("id") or ""): row for row in ctx.store.evidence()}

    def anonymous(value: Any, identities: list[str]) -> Any:
        if isinstance(value, dict):
            return {key: anonymous(item, identities) for key, item in value.items()}
        if isinstance(value, list):
            return [anonymous(item, identities) for item in value]
        if not isinstance(value, str):
            return value
        out = re.sub(r"https?://\S+|\barxiv(?:\.org)?\b|\b[EM]\d{3,4}\b",
                     "[source-redacted]", value, flags=re.I)
        for identity in identities:
            if len(identity.strip()) >= 5:
                out = re.sub(re.escape(identity.strip()), "[source-redacted]", out,
                             flags=re.I)
        return out

    cores: list[dict] = []
    sources: list[dict] = []
    for i, card in enumerate(chosen, 1):
        raw_facts = {field: card.get(field) for field in CORE_PALETTE_SOURCE_FIELDS}
        evidence = evidence_by_id.get(str(card.get("paper") or "")) or {}
        identities = [str(card.get("name") or ""), str(evidence.get("title") or ""),
                      str(evidence.get("url") or "")]
        fact_digest = eseal.combine_digests(
            json.dumps(raw_facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        core_id = f"CP{i:02d}"
        cores.append({
            "id": core_id,
            "source_fact_digest": fact_digest,
            **anonymous(raw_facts, identities),
        })
        sources.append({
            "core_id": core_id, "mech_card_id": card.get("id"),
            "evidence_id": card.get("paper"), "source_fact_digest": fact_digest,
        })
    return ({
        "schema_version": 1, "lane": lane.get("id"),
        "projection": "anonymous_actual_work_core_v1", "cores": cores,
    }, {
        "schema_version": 1, "lane": lane.get("id"),
        "visibility": "audit_only_not_generator_input", "sources": sources,
    })


def core_palette_contract_errors(ctx: Ctx, lane: dict, *,
                                 digest_cache: dict[str, str] | None = None) -> list[str]:
    """Audit the complete active contract of a ``core_synthesis`` palette.

    The ready predicate is state-derived rather than pointer-derived: deleting
    the four pointer/seal fields after the initial read cannot switch the audit
    off.  Conversely, non-core routes may not smuggle a palette into their
    generator bundle.
    """
    errs: list[str] = []
    fields = ("core_palette_path", "core_palette_provenance_path",
              "core_palette_digest", "core_palette_seal")
    is_core = lane.get("search_origin") == "core_synthesis"
    ready = bool(is_core and lane.get("reading_done"))
    present = [field for field in fields if lane.get(field)]
    if not is_core:
        if present:
            errs.append(
                f"CORE_PALETTE_ROUTE: lane {lane.get('id')} is not core_synthesis but carries {present}")
        return errs
    if not ready:
        if present:
            errs.append(
                f"CORE_PALETTE_PREMATURE: lane {lane.get('id')} carries a palette before its read froze")
        return errs
    missing = [field for field in fields if not lane.get(field)]
    if missing:
        errs.append(
            f"CORE_PALETTE_ACTIVE_MISSING: lane {lane.get('id')} completed its read but lacks {missing}")
        return errs

    lane_dir = f".evo/rounds/{lane.get('round')}/lanes/{lane.get('id')}"
    palette_rel = str(lane.get("core_palette_path") or "")
    provenance_rel = str(lane.get("core_palette_provenance_path") or "")
    expected_palette_rel = f"{lane_dir}/CORE_PALETTE.json"
    expected_provenance_rel = f"{lane_dir}/CORE_PALETTE_PROVENANCE.json"
    if palette_rel != expected_palette_rel:
        errs.append(
            f"CORE_PALETTE_PATH: lane {lane.get('id')} path {palette_rel!r} must be {expected_palette_rel!r}")
    if provenance_rel != expected_provenance_rel:
        errs.append(
            f"CORE_PALETTE_PROVENANCE_PATH: lane {lane.get('id')} path {provenance_rel!r} "
            f"must be {expected_provenance_rel!r}")
    seal = lane.get("core_palette_seal")
    cache = digest_cache if digest_cache is not None else {}
    errs.extend(eseal.binding_errors(
        ctx.store.repo, seal,
        [("anonymous_core_palette", palette_rel),
         ("audit_only_core_provenance", provenance_rel)],
        label=f"lane {lane.get('id')} core_palette_seal", digest_cache=cache))
    actual_digest = cache.get(palette_rel)
    if actual_digest is None:
        actual_digest = eseal.artifact_digest(ctx.store.repo, palette_rel)
        cache[palette_rel] = actual_digest
    if str(lane.get("core_palette_digest") or "") != actual_digest:
        errs.append(
            f"CORE_PALETTE_DIGEST: lane {lane.get('id')} active digest does not match its palette")

    palette = eutil.read_json(eutil.rpath(ctx.store.repo, palette_rel), None)
    provenance = eutil.read_json(eutil.rpath(ctx.store.repo, provenance_rel), None)
    if not isinstance(palette, dict):
        errs.append(f"CORE_PALETTE_JSON: lane {lane.get('id')} palette is not a JSON object")
        return errs
    if not isinstance(provenance, dict):
        errs.append(f"CORE_PALETTE_PROVENANCE_JSON: lane {lane.get('id')} provenance is not a JSON object")
        return errs
    cores = palette.get("cores")
    sources = provenance.get("sources")
    if not isinstance(cores, list) or not cores:
        errs.append(f"CORE_PALETTE_CORES: lane {lane.get('id')} needs a non-empty core list")
        return errs
    if not isinstance(sources, list) or not sources:
        errs.append(f"CORE_PALETTE_SOURCES: lane {lane.get('id')} needs a non-empty provenance list")
        return errs
    core_pairs = [(str((row or {}).get("id") or ""),
                   str((row or {}).get("source_fact_digest") or ""))
                  for row in cores if isinstance(row, dict)]
    source_pairs = [(str((row or {}).get("core_id") or ""),
                     str((row or {}).get("source_fact_digest") or ""))
                    for row in sources if isinstance(row, dict)]
    if len(core_pairs) != len(cores) or len(set(core_pairs)) != len(core_pairs):
        errs.append(f"CORE_PALETTE_CORE_IDS: lane {lane.get('id')} has malformed or duplicate cores")
    if len(source_pairs) != len(sources) or len(set(source_pairs)) != len(source_pairs):
        errs.append(f"CORE_PALETTE_SOURCE_IDS: lane {lane.get('id')} has malformed or duplicate sources")
    if core_pairs != source_pairs:
        errs.append(
            f"CORE_PALETTE_BIJECTION: lane {lane.get('id')} palette and provenance are not an exact ordered bijection")

    mech = ctx.mech_by_id()
    evidence_ids = ctx.evidence_ids()
    selected: list[dict] = []
    resolvable = True
    seen_mech: set[str] = set()
    for i, raw in enumerate(sources):
        row = raw if isinstance(raw, dict) else {}
        mid = str(row.get("mech_card_id") or "")
        eid = str(row.get("evidence_id") or "")
        card = mech.get(mid)
        if not mid or mid in seen_mech:
            errs.append(f"CORE_PALETTE_MECH_UNIQUE: source row {i} has missing/duplicate M id {mid!r}")
            resolvable = False
        seen_mech.add(mid)
        if card is None:
            errs.append(f"CORE_PALETTE_MECH_MISSING: source row {i} references unknown {mid!r}")
            resolvable = False
            continue
        selected.append(card)
        if card.get("lane") != lane.get("id"):
            errs.append(f"CORE_PALETTE_MECH_LANE: {mid} does not belong to lane {lane.get('id')}")
        if str(card.get("paper") or "") != eid or eid not in evidence_ids:
            errs.append(f"CORE_PALETTE_EVIDENCE: {mid} does not bind the resolvable evidence id {eid!r}")
    if resolvable and len(selected) == len(sources):
        expected_palette, expected_provenance = core_palette_projection(ctx, lane, selected)
        if palette != expected_palette:
            errs.append(
                f"CORE_PALETTE_SOURCE_DRIFT: lane {lane.get('id')} palette is not the deterministic projection of its M/E sources")
        if provenance != expected_provenance:
            errs.append(
                f"CORE_PALETTE_PROVENANCE_DRIFT: lane {lane.get('id')} sidecar is not the deterministic M/E mapping")

    sketches_rel = str(lane.get("sketches_path") or "")
    if sketches_rel:
        programs = eutil.read_json(eutil.rpath(ctx.store.repo, sketches_rel), None)
        if not isinstance(programs, dict):
            errs.append(f"CORE_PALETTE_PROGRAM_JSON: lane {lane.get('id')} program set is not a JSON object")
        else:
            if programs.get("core_palette_digest") != lane.get("core_palette_digest"):
                errs.append(
                    f"CORE_PALETTE_PROGRAM_DIGEST: lane {lane.get('id')} program set is not bound to the active palette")
            palette_ids = {pair[0] for pair in core_pairs if pair[0]}
            for candidate in programs.get("sketches") or []:
                unknown = set((candidate or {}).get("synthesis_core_ids") or []) - palette_ids
                if unknown:
                    errs.append(
                        f"CORE_PALETTE_PROGRAM_IDS: candidate {(candidate or {}).get('sketch_id')} uses unknown cores {sorted(unknown)}")
        program_seal = lane.get("program_seal")
        upstream = [str(value) for value in ((program_seal or {}).get("upstream") or [])]
        required = str((seal or {}).get("digest") or "")
        if not required or upstream.count(required) != 1:
            errs.append(
                f"CORE_PALETTE_REQUIRED_UPSTREAM: lane {lane.get('id')} program seal must cite its active palette seal exactly once")
    return errs


def lane_pointer_binding_errors(ctx: Ctx, lane: dict, *,
                                digest_cache: dict[str, str] | None = None) -> list[str]:
    """Bind every active lane pointer used by later reasoning to its seal."""
    errs: list[str] = []
    lid = str(lane.get("id") or "")
    specs: list[tuple[str, list[tuple[str, str]], bool]] = []
    if lane.get("diagnosis_path"):
        specs.append(("diagnosis_seal", [("diagnosis", str(lane["diagnosis_path"]))], True))
    if lane.get("sketches_path"):
        specs.append(("program_seal", [("program_set", str(lane["sketches_path"]))], True))
    if lane.get("tournament_path"):
        # legacy_extra_roles: a v10-created seal also bound the (since removed)
        # prose report; tolerated so upgraded projects keep running.
        specs.append(("tournament_seal",
                      [("tournament", str(lane["tournament_path"]))], True))
    if lane.get("problem_path"):
        specs.append(("problem_seal", [("posed_problem", str(lane["problem_path"]))], True))
    if lane.get("theory_path"):
        theory = [("theory", str(lane["theory_path"]))]
        if isinstance(lane.get("theory_draft_seal"), dict):
            specs.append(("theory_draft_seal", theory, False))
        if isinstance(lane.get("theory_seal"), dict):
            specs.append(("theory_seal", theory, False))
    if lane.get("idea"):
        idea = str(lane["idea"])
        if isinstance(lane.get("idea_seal"), dict):
            specs.append(("idea_seal", [("idea", f".evo/ideas/{idea}.md"),
                                         ("idea_meta", f".evo/ideas/{idea}.meta.json")], True))
        if isinstance(lane.get("review_seal"), dict):
            purpose = econfig.lane_purpose(lane)
            if purpose == "diagnostic_probe":
                # A probe has no review stage at all (the manual gate is its
                # protection), so a present review_seal is itself the
                # corruption. Auditing it against the CANDIDATE suffix - the
                # old .get default - reported a missing .review.md, a file a
                # probe can never legally have, instead of naming the real
                # problem.
                errs.append(f"LANE_SEAL_PURPOSE: lane {lid} is a diagnostic_probe and can never "
                            "carry a review_seal; the seal record itself is illegal")
            else:
                review_role, review_suffix = {
                    "targeted_ablation": ("ablation_review", ".ablation-review.md"),
                    "maintenance": ("maintenance_review", ".maintenance-review.md"),
                }.get(purpose, ("red_team_review", ".review.md"))
                specs.append(("review_seal", [(review_role, f".evo/ideas/{idea}{review_suffix}")], True))
    legacy = {"tournament_seal": ("tournament_report",)}
    for field, expected, exact in specs:
        errs.extend(eseal.binding_errors(
            ctx.store.repo, lane.get(field), expected,
            label=f"lane {lid} {field}", exact=exact, digest_cache=digest_cache,
            legacy_extra_roles=legacy.get(field, ())))
    return errs


def workflow_reuse_receipt_errors(ctx: Ctx, node: dict) -> list[str]:
    """Audit the narrow bridge that keeps old stage evidence active after an eval-only fix."""
    rel = str(node.get("workflow_reuse_receipt_path") or "")
    if not rel:
        return [] if not node.get("workflow_reuse_seal") else [
            f"WORKFLOW_REUSE_RECEIPT_MISSING: node {node.get('id')} has a reuse seal without a receipt"]
    data = eutil.read_json(eutil.rpath(ctx.store.repo, rel), None)
    if not isinstance(data, dict) or data.get("schema_version") != 1 \
            or data.get("node") != node.get("id") or data.get("repair_scope") != "evaluation":
        return [f"WORKFLOW_REUSE_RECEIPT_INVALID: node {node.get('id')} receipt identity/schema is invalid"]
    errs: list[str] = []
    current = str((node.get("implementation_seal") or {}).get("digest") or "")
    if data.get("current_implementation_digest") != current:
        errs.append("WORKFLOW_REUSE_CURRENT_IMPLEMENTATION: receipt does not bind the active implementation")
    prior = str(data.get("prior_implementation_digest") or "")
    if not prior or prior == current:
        errs.append("WORKFLOW_REUSE_PRIOR_IMPLEMENTATION: receipt needs a distinct prior implementation digest")
    rows = data.get("preserved_stage_runs")
    if not isinstance(rows, list):
        return errs + ["WORKFLOW_REUSE_RUNS: preserved_stage_runs must be an array"]
    actual_runs = {str(run.get("id") or ""): run for run in ctx.st.get("runs", [])}
    seen: set[str] = set()
    upstreams = {prior}
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("run") or ""):
            errs.append("WORKFLOW_REUSE_RUN_ROW: every preserved stage row needs a RUN id")
            continue
        rid = str(row["run"])
        if rid in seen:
            errs.append(f"WORKFLOW_REUSE_RUN_DUP: receipt repeats {rid}")
            continue
        seen.add(rid)
        run = actual_runs.get(rid) or {}
        if run.get("kind") != "stage" or run.get("adoption_status") != "adopted" \
                or run.get("status") != "finished" or run.get("evidence_status") != "complete":
            errs.append(f"WORKFLOW_REUSE_RUN_INACTIVE: {rid} is not active completed stage evidence")
        if row.get("evidence_digest") != str((run.get("evidence_seal") or {}).get("digest") or ""):
            errs.append(f"WORKFLOW_REUSE_EVIDENCE_DIGEST: {rid} receipt digest does not match its evidence seal")
        if row.get("implementation_digest") != str(run.get("implementation_digest") or ""):
            errs.append(f"WORKFLOW_REUSE_IMPLEMENTATION_DIGEST: {rid} implementation binding changed")
        upstreams.update(str(x) for x in (run.get("authority_upstreams") or []) if str(x))
    declared_upstreams = {str(x) for x in (data.get("preserved_upstream_digests") or []) if str(x)}
    if declared_upstreams != upstreams:
        errs.append("WORKFLOW_REUSE_UPSTREAMS: receipt must name exactly the old authority digests needed by "
                    "its preserved stage evidence")
    return errs


def node_pointer_binding_errors(ctx: Ctx, node: dict, *,
                                digest_cache: dict[str, str] | None = None) -> list[str]:
    """Bind graph pointers that select active executable/evaluation evidence."""
    errs: list[str] = []
    nid = str(node.get("id") or "")
    specs: list[tuple[str, list[tuple[str, str]], bool]] = []
    if node.get("spec") and isinstance(node.get("spec_seal"), dict):
        specs.append(("spec_seal", [("node_spec", str(node["spec"]))], True))
    if isinstance(node.get("fidelity_seal"), dict):
        specs.append(("fidelity_seal", [("fidelity_report", f".evo/nodes/{nid}/FIDELITY.md")], True))
    if isinstance(node.get("ablation_fidelity_seal"), dict):
        specs.append(("ablation_fidelity_seal",
                      [("ablation_fidelity_report", f".evo/nodes/{nid}/ABLATION_FIDELITY.md")], True))
    if isinstance(node.get("metric_bridge_seal"), dict):
        specs.append(("metric_bridge_seal", [
            ("metric_bridge_anchor", f".evo/nodes/{nid}/metric_bridge/ANCHOR.json")], True))
    if node.get("resource_receipt_path") and isinstance(node.get("resource_receipt_seal"), dict):
        specs.append(("resource_receipt_seal",
                      [("engine_resource_receipt", str(node["resource_receipt_path"]))], True))
    if node.get("workflow_reuse_receipt_path") and isinstance(node.get("workflow_reuse_seal"), dict):
        specs.append(("workflow_reuse_seal",
                      [("workflow_reuse_receipt", str(node["workflow_reuse_receipt_path"]))], True))
    if isinstance(node.get("eval_seal"), dict):
        specs.append(("eval_seal", [
            ("normalized_metrics", str(node.get("eval_metrics_path") or f".evo/nodes/{nid}/eval/metrics.json")),
            ("evaluation_report", str(node.get("eval_report_path") or f".evo/nodes/{nid}/eval/EVAL_REPORT.md"))], False))
    if isinstance(node.get("conclusion_seal"), dict):
        specs.append(("conclusion_seal", [
            ("outcome", str(node.get("outcome_path") or f".evo/nodes/{nid}/OUTCOME.json")),
            ("node_result", str(node.get("result_doc") or f".evo/nodes/{nid}/NODE_RESULT.md"))], True))
    cache = digest_cache if digest_cache is not None else {}
    legacy = {"metric_bridge_seal": ("metric_bridge_report",)}
    for field, expected, exact in specs:
        errs.extend(eseal.binding_errors(
            ctx.store.repo, node.get(field), expected,
            label=f"node {nid} {field}", exact=exact, digest_cache=cache,
            legacy_extra_roles=legacy.get(field, ())))

    # The implementation seal contains a variable number of source roles, but
    # the active manifest pointer must still name exactly one sealed row.
    manifest = str(node.get("implementation_manifest") or "")
    seal = node.get("implementation_seal")
    if manifest and isinstance(seal, dict):
        rows = [row for row in (seal.get("artifacts") or []) if isinstance(row, dict)
                and str(row.get("path") or "") == manifest]
        if len(rows) != 1:
            errs.append(
                f"SEAL_BINDING_IMPLEMENTATION_MANIFEST: node {nid} active manifest {manifest!r} "
                "must resolve to exactly one implementation-seal row")
        else:
            manifest_digest = cache.get(manifest)
            if manifest_digest is None:
                manifest_digest = eseal.artifact_digest(ctx.store.repo, manifest)
                cache[manifest] = manifest_digest
            if manifest_digest != str(rows[0].get("digest") or ""):
                errs.append(
                    f"SEAL_BINDING_IMPLEMENTATION_MANIFEST_DIGEST: node {nid} active manifest changed")
    errs.extend(workflow_reuse_receipt_errors(ctx, node))
    return errs


def run_pointer_binding_errors(ctx: Ctx, run: dict, *,
                               digest_cache: dict[str, str] | None = None) -> list[str]:
    """Bind ingested run landing pointers to the immutable evidence seal."""
    seal = run.get("evidence_seal")
    if not isinstance(seal, dict):
        return []
    expected: list[tuple[str, str]] = []
    if run.get("metrics_file"):
        expected.append(("run_metrics", str(run["metrics_file"])))
    if run.get("ledger_file"):
        expected.append(("run_ledger", str(run["ledger_file"])))
    for index, row in enumerate(run.get("probe_artifact_snapshots") or []):
        if isinstance(row, dict) and row.get("snapshot_artifact"):
            observation_index = row.get("observation_index")
            role_index = observation_index if isinstance(observation_index, int) \
                and not isinstance(observation_index, bool) else index
            expected.append((f"mechanism_probe_{role_index}", str(row["snapshot_artifact"])))
    if not expected:
        return []
    return eseal.binding_errors(
        ctx.store.repo, seal, expected,
        label=f"run {run.get('id')} evidence", exact=False, digest_cache=digest_cache)


def _check_citations(ctx: Ctx, text: str, where: str, errs: list[str],
                     min_mech: int = 0) -> None:
    ev, mech = ctx.evidence_ids(), set(ctx.mech_by_id())
    for eid in set(CIT_E.findall(text)):
        if eid not in ev:
            errs.append(f"CITATION_UNRESOLVED: {where}: [{eid}] not in EVIDENCE.jsonl")
    mrefs = set(CIT_M.findall(text))
    for mid in mrefs:
        if mid not in mech:
            errs.append(f"CITATION_UNRESOLVED: {where}: [{mid}] not in MECH_CARDS.jsonl")
    if len(mrefs) < min_mech:
        errs.append(f"CITATION_TOO_FEW_MECH: {where}: needs >= {min_mech} [M###] mechanism-card citations")


def _check_quotes(quotes: list[str], source_text: str, where: str, errs: list[str],
                  min_quotes: int, min_words: int = 6) -> None:
    norm_src = eutil.norm_ws(source_text)
    ok = 0
    for q in quotes:
        qn = eutil.norm_ws(q.strip().strip('"').strip("'"))
        if len(qn.split()) < min_words:
            errs.append(f"QUOTE_TOO_SHORT: {where}: quote must be >= {min_words} words: '{q[:60]}'")
        elif qn not in norm_src:
            errs.append(f"QUOTE_NOT_LITERAL: {where}: quote is not a literal substring of the reviewed text: '{q[:60]}'")
        else:
            ok += 1
    if ok < min_quotes:
        errs.append(f"QUOTE_TOO_FEW: {where}: needs >= {min_quotes} literal QUOTE: lines from the reviewed doc")


def _needs_theory(lane: dict) -> bool:
    return lane.get("search_origin") == "theory_derived" or bool(lane.get("theory_required"))


def deep_rigor(lane: dict) -> bool:
    """Theory rigor follows an actual theory claim, never an innovation label."""
    return _needs_theory(lane) and str(lane.get("formal_kind") or "") == "full"


def lane_min_level(lane: dict) -> int:
    """One lane scope-floor accessor (v9.2 had three copies with two different
    fallback defaults, 0 vs 2)."""
    value = (lane or {}).get("min_level")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else 2


def metric_value(v: Any) -> float | None:
    """Compatibility wrapper around the explicit result schema."""
    return econfig.result_value(v)


def metric_interval(v: Any) -> tuple[float | None, float | None, float | None]:
    return econfig.result_interval(v)


# ---- bootstrap validators -----------------------------------------------------------

def v_project_scan(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    report = _read_md(ctx, task["outputs"][0], errs)
    data = _read_json(ctx, task["outputs"][1], errs)
    if report is None or data is None:
        return errs
    _require_sections(report, ["sources scanned", "draft evaluation map", "draft evidence policy",
                               "unresolved user questions", "draft resource envelope"],
                      "PROJECT_DISCOVERY", errs, min_chars=20)
    project = data.get("project")
    if not isinstance(project, dict):
        errs.append("DISCOVERY_PROJECT: PROJECT_DISCOVERY.json needs a project object")
        project = {}
    for field in ("name", "goal"):
        if not str(project.get(field) or "").strip():
            errs.append(f"DISCOVERY_PROJECT_{field.upper()}: project.{field} required")
    for field in ("docs", "code_roots"):
        paths = project.get(field)
        if not isinstance(paths, list):
            errs.append(f"DISCOVERY_{field.upper()}: project.{field} must be a list")
            continue
        bad = [str(p) for p in paths if not _exists(ctx, str(p))]
        if bad:
            errs.append(f"DISCOVERY_{field.upper()}_UNRESOLVED: paths do not exist: {bad[:5]}")
    scanned = data.get("scanned_paths")
    if not isinstance(scanned, list) or not scanned:
        errs.append("DISCOVERY_SCAN_EMPTY: scanned_paths must list the docs/code/eval entry points actually inspected")
    else:
        bad = [str(p) for p in scanned if not _exists(ctx, str(p))]
        if bad:
            errs.append(f"DISCOVERY_SCAN_UNRESOLVED: scanned paths do not exist: {bad[:5]}")
    inventory = data.get("inventory")
    if not isinstance(inventory, dict):
        errs.append("DISCOVERY_INVENTORY: inventory object required")
        inventory = {}
    known = 0
    for kind in ("datasets", "tasks", "metrics", "cells"):
        rows = inventory.get(kind)
        if not isinstance(rows, list):
            errs.append(f"DISCOVERY_INVENTORY_{kind.upper()}: inventory.{kind} must be a list")
            continue
        known += len(rows)
        for i, row in enumerate(rows):
            source = str((row or {}).get("source") or "") if isinstance(row, dict) else ""
            if not source or not _exists(ctx, source):
                errs.append(f"DISCOVERY_SOURCE: inventory.{kind}[{i}].source must resolve to the fact's source")
    unknowns = data.get("unknowns")
    if not isinstance(unknowns, list):
        errs.append("DISCOVERY_UNKNOWNS: unknowns must be a list")
        unknowns = []
    for i, item in enumerate(unknowns):
        uid = str((item or {}).get("id") or "")
        if not re.fullmatch(r"U\d+", uid):
            errs.append(f"DISCOVERY_UNKNOWN_ID: unknowns[{i}].id must be U#")
        _nontrivial((item or {}).get("question"), 12, f"unknowns[{i}].question", errs)
        _nontrivial((item or {}).get("why_it_matters"), 15, f"unknowns[{i}].why_it_matters", errs)
        if not str((item or {}).get("provisional_default") or "").strip():
            errs.append(f"DISCOVERY_UNKNOWN_DEFAULT: unknowns[{i}] needs a visible provisional_default")
    if known == 0 and not unknowns:
        errs.append("DISCOVERY_EMPTY_WITHOUT_QUESTIONS: no evaluation facts were found, so the missing topology must be asked as U# questions")
    stochasticity = data.get("training_stochasticity")
    if not isinstance(stochasticity, dict):
        errs.append("DISCOVERY_TRAINING_STOCHASTICITY: training_stochasticity assessment required after scanning "
                    "the actual training procedure and stated research question")
        stochasticity = {}
    if stochasticity.get("recommended_mode") not in econfig.TRAINING_REPLICATION_MODES:
        errs.append(f"DISCOVERY_TRAINING_RECOMMENDATION: recommended_mode must be one of "
                    f"{econfig.TRAINING_REPLICATION_MODES}")
    sources = stochasticity.get("randomness_sources")
    if not isinstance(sources, list):
        errs.append("DISCOVERY_TRAINING_RANDOMNESS: randomness_sources must be a list (empty is legal after inspection)")
    _nontrivial(stochasticity.get("claim_and_cost_reasoning"), 40,
                "training_stochasticity.claim_and_cost_reasoning", errs)
    ablation = data.get("ablation_assessment")
    if not isinstance(ablation, dict):
        errs.append("DISCOVERY_ABLATION_ASSESSMENT: ablation_assessment object required")
        ablation = {}
    if ablation.get("recommended_mode") not in econfig.ABLATION_MODES:
        errs.append(f"DISCOVERY_ABLATION_RECOMMENDATION: recommended_mode must be one of {econfig.ABLATION_MODES}")
    _nontrivial(ablation.get("reasoning"), 40, "ablation_assessment.reasoning", errs)
    draft = data.get("resource_contract_draft")
    limits = (draft or {}).get("limits") if isinstance(draft, dict) else None
    if not isinstance(limits, dict) or not limits:
        errs.append("DISCOVERY_RESOURCE_LIMITS: resource_contract_draft.limits needs at least one user-supplied project limit")
        limits = {}
    for unit, value in limits.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,47}", str(unit or "")) or isinstance(value, bool) or \
                not isinstance(value, (int, float)) or not math.isfinite(float(value)) or float(value) <= 0:
            errs.append(f"DISCOVERY_RESOURCE_VALUE: {unit!r} must be a lowercase unit with finite positive limit")
    if len(str((draft or {}).get("basis") or "").strip()) < 20:
        errs.append("DISCOVERY_RESOURCE_BASIS: resource_contract_draft.basis must record what the user stated (>= 20 chars)")
    # v11.7: the engine-fit assessment - the engine's implicit runnability
    # assumptions made explicit and judged ONCE at the entrance, instead of
    # surfacing as repeated mid-evolution validation failures. F0 is the
    # task-class admission (hard); F5/F6/F7 are shape judgments with evidence.
    fit = data.get("engine_fit")
    if not isinstance(fit, dict):
        errs.append("DISCOVERY_ENGINE_FIT: engine_fit object required - judge the four engine "
                    "assumptions (F0 task class, F5 iteration cadence, F6 metric-rule "
                    "decidability, F7 harness shape) with evidence")
        fit = {}
    rows = fit.get("assumptions")
    rows = rows if isinstance(rows, list) else []
    by_id: dict[str, dict] = {}
    for i, row in enumerate(rows):
        w = f"engine_fit.assumptions[{i}]"
        if not isinstance(row, dict):
            errs.append(f"DISCOVERY_FIT_SHAPE: {w} must be an object")
            continue
        fid = str(row.get("id") or "")
        if fid not in ("F0", "F5", "F6", "F7"):
            errs.append(f"DISCOVERY_FIT_ID: {w}.id must be one of F0/F5/F6/F7 (got {fid!r})")
            continue
        if fid in by_id:
            errs.append(f"DISCOVERY_FIT_DUP: duplicate assumption {fid}")
        by_id[fid] = row
        verdict = str(row.get("verdict") or "")
        if verdict not in ("holds", "violated", "uncertain"):
            errs.append(f"DISCOVERY_FIT_VERDICT: {w}.verdict must be holds|violated|uncertain")
        ev = row.get("evidence")
        if not isinstance(ev, list) or not ev:
            errs.append(f"DISCOVERY_FIT_EVIDENCE: {w}.evidence must list >= 1 path")
        else:
            bad = [str(p) for p in ev if not _exists(ctx, str(p))]
            if bad:
                errs.append(f"DISCOVERY_FIT_EVIDENCE_UNRESOLVED: {w}.evidence paths do not exist: {bad[:3]}")
        _nontrivial(row.get("note"), 40, f"{w}.note (why this verdict, from the evidence)", errs)
        if verdict in ("violated", "uncertain"):
            _nontrivial(row.get("consequence_if_wrong"), 40,
                        f"{w}.consequence_if_wrong (how the evolution would repeatedly fail)", errs)
    missing = [fid for fid in ("F0", "F5", "F6", "F7") if fid not in by_id]
    if missing:
        errs.append(f"DISCOVERY_FIT_COVERAGE: engine_fit must judge every assumption; missing {missing}")
    verdicts = {fid: str((by_id.get(fid) or {}).get("verdict") or "") for fid in by_id}
    expected = ("unfit" if verdicts.get("F0") in ("violated",)
                else ("degraded" if any(v in ("violated", "uncertain") for v in verdicts.values())
                      else "fit"))
    if not missing and str(fit.get("overall") or "") != expected:
        errs.append(f"DISCOVERY_FIT_OVERALL: overall must be derived from the verdicts "
                    f"(expected {expected!r}): F0 violated = unfit; any other violated/uncertain "
                    f"= degraded; all holds = fit")
    # v11.7: readiness - does this project already run end-to-end here, or
    # does it need a constructive preparation pass before any contract can
    # honestly be frozen? ASK the user; a wrong 'certified_running' just
    # bounces at the canary, but the honest path is to say so now.
    readiness = data.get("readiness")
    if not isinstance(readiness, dict):
        errs.append("DISCOVERY_READINESS: readiness object required - "
                    "{mode: certified_running|needs_preparation, basis, worklist}")
        readiness = {}
    mode = str(readiness.get("mode") or "")
    if mode not in ("certified_running", "needs_preparation"):
        errs.append("DISCOVERY_READINESS_MODE: readiness.mode must be certified_running "
                    "(the user certifies a real end-to-end run works here today) or "
                    "needs_preparation (a provision pass will wire data / build a minimal "
                    "evaluation / fix bugs first)")
    _nontrivial(readiness.get("basis"), 40,
                "readiness.basis (what the user said / what the scan observed)", errs)
    if mode == "needs_preparation":
        rows = readiness.get("worklist")
        if not isinstance(rows, list) or not rows:
            errs.append("DISCOVERY_READINESS_WORKLIST: needs_preparation requires a worklist of "
                        ">= 1 concrete items ({item, why})")
        else:
            for i, row in enumerate(rows):
                _nontrivial((row or {}).get("item"), 10, f"readiness.worklist[{i}].item", errs)
                _nontrivial((row or {}).get("why"), 10, f"readiness.worklist[{i}].why", errs)
    tags = SRC_TAG.findall(report)
    if not tags:
        errs.append("DISCOVERY_REPORT_SOURCES: report needs at least one [src: path] citation")
    elif any(not _exists(ctx, p) for p, _line in tags):
        errs.append("DISCOVERY_REPORT_SOURCE_UNRESOLVED: every [src:] path must exist")
    return errs


def v_configure(ctx: Ctx, task: dict) -> list[str]:
    cfg = ctx.store.load_config()
    errs = econfig.validate_config(cfg)
    # preset honesty runs on the RAW file: load_config already expanded the preset
    errs.extend(econfig.preset_conflicts(eutil.read_json(ctx.store.config_path) or {}))
    if (cfg.get("project") or {}).get("vcs") == "git":
        if not evcs.is_git_repo(ctx.store.repo):
            errs.append("CONFIG_VCS_NOT_GIT: project.vcs='git' but the repo is not a git working tree; "
                        "run 'git init' + an initial commit first, or set vcs='copy'")
        else:
            # R9 (external audit r6): the error text above always DEMANDED an
            # initial commit but never checked one - a just-initialized repo
            # with an unborn HEAD sailed through configure and then died at the
            # pre-smoke baseline seal with a raw SystemExit outside any task
            # protocol. With no preparation pass before that seal (the
            # provision step already ran, or was never needed), the
            # sealability preconditions are checked HERE, where the answer is
            # still an ordinary fixable rejection.
            if evcs.head_commit(ctx.store.repo) is None:
                errs.append("CONFIG_VCS_NO_HEAD: project.vcs='git' needs at least one commit "
                            "(HEAD is unborn); make the initial commit before configure")
            else:
                _commit, clean, _untracked = evcs.status_facts(ctx.store.repo)
                if not clean:
                    errs.append("CONFIG_VCS_DIRTY: the baseline must be sealable as-is by the time "
                                "the contract freezes, but the tree has uncommitted tracked/staged "
                                "changes; commit them (a provision pass commits its own repairs - "
                                "loose edits outside it have no provenance)")
    for i, d in enumerate((cfg.get("project") or {}).get("docs") or []):
        if not eutil.rpath(ctx.store.repo, str(d)).exists():
            errs.append(f"CONFIG_DOCS_UNRESOLVED: project.docs[{i}] = {d!r} does not exist")
    return errs


def v_infra(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    text = _read_md(ctx, task["outputs"][0], errs)
    facts = _read_json(ctx, task["outputs"][1], errs)
    if text is None or facts is None:
        return errs
    _require_sections(text, ["where things run", "how training is submitted and watched",
                             "data access", "artifact and checkpoint conventions",
                             "known constraints"], "INFRA_PROFILE", errs)
    tags = SRC_TAG.findall(text)
    if len(tags) < 6:
        errs.append(f"INFRA_PROFILE_SRC_TAGS: needs >= 6 [src: path] tags (got {len(tags)}); every infra claim "
                    "must point at a knowledge-base doc or repo file")
    bad = [t for t, _ln in tags if not _exists(ctx, t)]
    if bad:
        errs.append(f"INFRA_PROFILE_SRC_UNRESOLVED: [src:] paths do not exist: {sorted(set(bad))[:5]}")
    errs.extend(einfra.validate_facts(ctx.store, facts))
    configured_results = set(econfig.result_spec(ctx.cfg))
    fact_eval = facts.get("evaluation") or {}
    fact_results = {str(k) for k in (fact_eval.get("result_keys") or [])}
    if fact_results != configured_results:
        errs.append(f"INFRA_EVAL_CONTRACT: evaluation.result_keys must exactly match the configured "
                    f"evaluation cells (expected {sorted(configured_results)}, got {sorted(fact_results)})")
    if str(fact_eval.get("primary_metric_key") or "") != econfig.primary_metric(ctx.cfg):
        errs.append("INFRA_EVAL_DISPLAY: evaluation.primary_metric_key must equal the configured display result "
                    f"{econfig.primary_metric(ctx.cfg)!r}")
    return errs


def v_infra_interview(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    text = _read_md(ctx, task["outputs"][0], errs)
    if text is None:
        return errs
    secs = _require_sections(text, ["contradictions", "unknowns", "resolutions",
                                    "runtime services", "evaluation contract confirmation"],
                             "INFRA_REVIEW", errs, min_chars=20)
    # LLM-surface auto-detection forcing function (v8): the interview must
    # actively DECIDE whether this platform has model-serving/API/vector/KG
    # surfaces - silently omitting the llm/services blocks is how inference-
    # class experiments discover mid-run that nobody recorded the endpoint.
    rs = secs.get("runtime services") or ""
    if rs and "NONE-FOUND" not in rs and not re.search(r"^\s*[-*]\s+", rs, re.M):
        errs.append("INTERVIEW_SERVICES: list the runtime surfaces found (LLM serving/APIs/vector "
                    "stores/KG endpoints/sandboxes) as '-' items feeding the facts' llm/services "
                    "blocks, or state the literal token NONE-FOUND after actually looking")
    contra = secs.get("contradictions") or ""
    if contra and "NONE-FOUND" not in contra:
        items = re.findall(r"^\s*[-*]\s*C\d+\s*:", contra, re.M)
        if not items:
            errs.append("INTERVIEW_CONTRADICTIONS: list contradictions as '- C1: ...' items, or state the literal "
                        "token NONE-FOUND after actually diffing docs against code")
        if items and ("docs say" not in contra.lower() or "code says" not in contra.lower()):
            errs.append("INTERVIEW_CONTRADICTION_SIDES: every contradiction needs both a 'docs say:' and a "
                        "'code says:' line with [src:] tags - a contradiction has two cited sides")
    unk = secs.get("unknowns") or ""
    if unk and "NONE-FOUND" not in unk:
        if not re.findall(r"^\s*[-*]\s*U\d+\s*:", unk, re.M):
            errs.append("INTERVIEW_UNKNOWNS: list unknowns as '- U1: ...' items or state NONE-FOUND")
    pm = econfig.primary_metric(ctx.cfg)
    pmc = secs.get("evaluation contract confirmation") or ""
    contract = econfig.evaluation_contract(ctx.cfg)
    missing_results = sorted(k for k in econfig.result_spec(ctx.cfg) if k not in pmc)
    if missing_results:
        errs.append(f"INTERVIEW_RESULT_KEYS: the confirmation section must name every configured result key; "
                    f"missing {missing_results}")
    def missing_ids(records: list[dict]) -> list[str]:
        return sorted(str(r.get("id")) for r in records
                      if not re.search(rf"\b{re.escape(str(r.get('id') or ''))}\b", pmc))
    missing_cells = missing_ids(contract.get("cells") or [])
    missing_tasks = missing_ids(contract.get("tasks") or [])
    missing_groups = missing_ids(contract.get("task_groups") or [])
    if missing_cells:
        errs.append(f"INTERVIEW_EVAL_CELLS: the user review must enumerate every C# decision cell; missing {missing_cells}")
    if missing_tasks or missing_groups:
        errs.append(f"INTERVIEW_EVAL_HIERARCHY: the user review must name every T#/G# aggregation; "
                    f"missing tasks={missing_tasks}, groups={missing_groups}")
    model_scope = str(contract.get("model_scope") or "")
    if model_scope and model_scope not in pmc:
        errs.append(f"INTERVIEW_EVAL_MODEL_SCOPE: state the deliverable shape/model_scope {model_scope!r}")
    if "goal" not in pmc.lower() or "relative" not in pmc.lower():
        errs.append("INTERVIEW_EVAL_GOALS: distinguish sourced absolute goals from relative progress in the user review")
    assumptions = contract.get("assumptions") or []
    missing_assumptions = missing_ids(assumptions)
    if missing_assumptions:
        errs.append(f"INTERVIEW_EVAL_ASSUMPTIONS: name every inferred U# decision and revisit trigger; "
                    f"missing {missing_assumptions}")
    elif not assumptions and "NONE-DECLARED" not in pmc:
        errs.append("INTERVIEW_EVAL_ASSUMPTIONS: write NONE-DECLARED when the success contract has no inferred U# choices")
    if pm and (pm not in pmc or "display" not in pmc.lower()):
        errs.append(f"INTERVIEW_DISPLAY_RESULT: name '{pm}' explicitly as display-only, not the success criterion")
    missing_resource_units = sorted(u for u in econfig.resource_limits(ctx.cfg) if u not in pmc)
    if missing_resource_units or "resource" not in pmc.lower() or "cumulative" not in pmc.lower():
        errs.append(f"INTERVIEW_RESOURCE_CONTRACT: state every project-wide resource limit and cumulative "
                    f"exhaustion rule; missing units={missing_resource_units}")
    rep = econfig.training_replication_policy(ctx.cfg)
    if str(rep.get("mode") or "") not in pmc or "training" not in pmc.lower() or "seed" not in pmc.lower():
        errs.append("INTERVIEW_TRAINING_REPLICATION: the user review must state the approved training-seed "
                    "replication mode and make clear whether full retraining repeats are planned")
    abl = ((ctx.cfg.get("evidence_policy") or {}).get("ablation") or {})
    if str(abl.get("mode") or "") not in pmc or "ablation" not in pmc.lower():
        errs.append("INTERVIEW_ABLATION_POLICY: the user review must state whether targeted ablation nodes are "
                    "off or allowed, including their one-run cap")
    if not SRC_TAG.search(pmc or ""):
        errs.append("INTERVIEW_EVAL_CONTRACT_SRC: the evaluation-contract confirmation needs a [src: path] tag")
    return errs


def v_profile(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    text = _read_md(ctx, task["outputs"][0], errs)
    if text is None:
        return errs
    _require_sections(text, ["task", "data", "model", "training", "evaluation and metrics",
                             "runtime", "current results", "known issues"], "PROJECT_PROFILE", errs)
    tags = SRC_TAG.findall(text)
    resolved = [t for t, _ln in tags if _exists(ctx, t)]
    if len(tags) < 8:
        errs.append(f"PROFILE_SRC_TAGS: needs >= 8 [src: path] fact tags (got {len(tags)}); every claim about the project must point into the repo")
    bad = [t for t, _ln in tags if not _exists(ctx, t)]
    if bad:
        errs.append(f"PROFILE_SRC_UNRESOLVED: [src:] paths do not exist: {sorted(set(bad))[:5]}")
    if len(resolved) < 8 and len(tags) >= 8:
        errs.append("PROFILE_SRC_RESOLVED: fewer than 8 [src:] tags resolve to real files")
    if len(task.get("outputs") or []) < 2:
        errs.append("PROFILE_PROGRAM_OUTPUT: profile task must also produce BASELINE_PROGRAM.json")
        return errs
    data = _read_json(ctx, task["outputs"][1], errs)
    if data is not None:
        errs.extend(eprogram.baseline_program_errors(data))
        for row in ((data.get("program") or {}).get("objects") or []):
            for relp in (row.get("code") or []) if isinstance(row, dict) else []:
                if not _exists(ctx, str(relp)):
                    errs.append(f"BASELINE_PROGRAM_CODE: object {row.get('id')} cites missing path {relp!r}")
    return errs


def v_dossier(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    text = _read_md(ctx, task["outputs"][0], errs)
    if text is None:
        return errs
    secs = _require_sections(text, ["computational essence", "bottleneck hypotheses",
                                    "diagnostic discriminators", "invariants",
                                    "forbidden shallow moves"], "PROBLEM_DOSSIER", errs)
    bs, vs, fs = set(B_ID.findall(text)), set(V_ID.findall(text)), set(F_ID.findall(text))
    if len(bs) < 3:
        errs.append(f"DOSSIER_BOTTLENECKS: needs >= 3 '- B#:' ranked bottleneck hypotheses (got {len(bs)})")
    if len(vs) < 2:
        errs.append(f"DOSSIER_INVARIANTS: needs >= 2 '- V#:' invariants (metric definitions, eval protocol) (got {len(vs)})")
    if len(fs) < 5:
        errs.append(f"DOSSIER_FORBIDDEN: needs >= 5 '- F#:' forbidden shallow moves (got {len(fs)})")
    hyp = eutil.find_section(eutil.md_sections(text), "bottleneck hypotheses") or text
    for m in re.finditer(r"^\s*[-*]\s*(B\d+)\s*:(.*)$", hyp, re.M):
        if "evidence:" not in m.group(2).lower() and not SRC_TAG.search(m.group(2)):
            errs.append(f"DOSSIER_B_EVIDENCE: {m.group(1)} has no 'evidence:' pointer or [src:] tag on its line")
    # The problem model is frozen before candidate synthesis or
    # candidate-specific prior-art comparison. Every bottleneck therefore owes
    # a falsifier/discriminator rather than a proposed program label.
    diag = secs.get("diagnostic discriminators") or ""
    for b in sorted(bs):
        m = re.search(rf"^\s*[-*]\s*{re.escape(b)}\s*:(.*)$", diag, re.M)
        if not m:
            errs.append(f"DOSSIER_DISCRIMINATOR_MISSING: {b} needs its own line in "
                        "'diagnostic discriminators'")
            continue
        body = m.group(1)
        fm = re.search(r"falsifier\s*:\s*(.+?)(?:\||$)", body, re.I)
        dm = re.search(r"distinguish\s*:\s*(.+?)(?:\||$)", body, re.I)
        if not fm or len(fm.group(1).strip()) < 20:
            errs.append(f"DOSSIER_FALSIFIER: {b} needs 'falsifier: <>=20 chars>'")
        if not dm or len(dm.group(1).strip()) < 20:
            errs.append(f"DOSSIER_DISTINGUISH: {b} needs 'distinguish: <>=20 chars>'")
    if re.search(r"\b(?:SIG\d{2}|MV\d{2}|M\d{3,4}|E\d{3,4})\b|https?://|arxiv\.org", text, re.I):
        errs.append("DOSSIER_SOLUTION_LEAK: the bootstrap dossier must be method-blind; "
                    "do not cite candidate patterns, program mechanisms, papers, or URLs")
    return errs


def v_rubric(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    text = _read_md(ctx, task["outputs"][0], errs)
    if text is None:
        return errs
    _require_sections(text, ["scientific program", "implementation scope", "mechanism novelty", "effect frontier",
                             "theory axis", "engineering boundary", "project-specific tests"],
                      "INNOVATION_RUBRIC", errs, min_chars=160)
    low = text.lower()
    for phrase in ("non-reduc", "load-bearing", "resource", "composition", "subsystem", "full-program", "paradigm"):
        if phrase not in low:
            errs.append(f"RUBRIC_STANDARD: the research standard must explicitly define {phrase!r} for this project")
    if PAPERISH.search(text):
        errs.append("RUBRIC_IS_A_MENU: rubric contains paper links/DOIs - it defines project-specific tests, not candidate techniques")
    return errs


# ---- evidence / reading ---------------------------------------------------------------

def _evidence_schema_errors(rec: dict, i: int, attempts_min: int = 2) -> list[str]:
    errs = []
    if not re.fullmatch(r"E\d{3,4}", str(rec.get("id") or "")):
        errs.append(f"EVIDENCE_ID: record {i}: id must be E###")
    for f in ("title", "url", "source"):
        if not str(rec.get(f) or "").strip():
            errs.append(f"EVIDENCE_FIELD: record {i} ({rec.get('id')}): '{f}' required")
    if not isinstance(rec.get("year"), int):
        errs.append(f"EVIDENCE_YEAR: record {i} ({rec.get('id')}): integer 'year' required")
    if not isinstance(rec.get("relevance"), list) or not rec.get("relevance"):
        errs.append(f"EVIDENCE_RELEVANCE: record {i} ({rec.get('id')}): 'relevance' must list bottleneck ids (B#)")
    # retrieval ladder: a paper may be downgraded to abstract-only/unavailable
    # ONLY with a documented ladder of attempted sources. One failed fetch is
    # never a reason to drop a relevant paper.
    access = rec.get("access")
    if access is not None and access not in ("full", "abstract", "unavailable"):
        errs.append(f"EVIDENCE_ACCESS: record {i} ({rec.get('id')}): access must be full|abstract|unavailable")
    if access in ("abstract", "unavailable"):
        tries = rec.get("retrieval_attempts")
        distinct = {str(t).strip().lower() for t in tries} if isinstance(tries, list) else set()
        if len(distinct) < attempts_min:
            errs.append(
                f"RETRIEVAL_LADDER: record {i} ({rec.get('id')}): access='{access}' requires "
                f"retrieval_attempts listing >= {attempts_min} distinct sources actually tried "
                f"(arxiv/ar5iv/semantic scholar/openreview/acl anthology/author page/github...). "
                f"Giving up after one failed fetch loses exactly the papers worth reading."
            )
    return errs


def ledger_prefix_digest(rows: list) -> str:
    """Canonical digest of an append-only ledger's row prefix (R7 multi-round
    audit). Stored on the task at creation, re-checked at submit: the cards
    promise "append, never renumber/rewrite", and without this binding a
    rewrite-oriented tool could replace history and still be ACCEPTED -
    silently rebinding every earlier M#/E#/S# citation."""
    payload = "\n".join(json.dumps(r, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                        for r in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def accepted_ledger_rows(st: dict, name: str, rows: list) -> list:
    """Rows an append-only ledger has actually ACCEPTED (R9, external audit r6).

    A project with no watermark for this ledger (pre-binding state) keeps the
    old whole-file behaviour; a watermark ahead of the file is left to the
    prefix validators to report rather than silently hiding rows."""
    wm = ((st.get("ledger_accept") or {}).get(name) or {})
    count = wm.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0 or count > len(rows):
        return rows
    return rows[:count]


def ledger_watermark(st: dict, name: str, rows: list) -> tuple[int, str]:
    """The frozen prefix for a new ledger task: what the LAST ACCEPTED submit
    validated (R7 external audit). Snapshotting the raw file instead froze a
    cancelled task's unvalidated leftovers into immutable history - rows that
    both fail every future whole-ledger validation and may not be repaired.
    Accepted history is immutable; an unaccepted suffix stays repairable.
    Falls back to the current rows when no acceptance ever stamped this
    ledger (bootstrap, or a project predating the watermark)."""
    wm = ((st.get("ledger_accept") or {}).get(name) or {})
    count, digest = wm.get("count"), str(wm.get("digest") or "")
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0 and digest:
        return count, digest
    return len(rows), ledger_prefix_digest(rows)


def stamped_ledger_watermark(st: dict, name: str) -> tuple[int, str]:
    """The watermark ONLY if an acceptance ever stamped it; (0, "") otherwise.

    R8 audit: the sota stamp branch was shadowed for the whole life of R7-R9,
    so no project has a sota watermark; the full-file fallback then froze
    cancelled tasks' unaccepted tails as immutable prefix - simultaneously
    must-fix (whole-table checks) and may-not-fix (prefix immutability).
    Refresh-task creation now binds only STAMPED history; with none, nothing
    is frozen and the task may repair the whole table (its acceptance then
    stamps the first real watermark)."""
    wm = ((st.get("ledger_accept") or {}).get(name) or {})
    count, digest = wm.get("count"), str(wm.get("digest") or "")
    if isinstance(count, int) and not isinstance(count, bool) and count >= 0 and digest:
        return count, digest
    return 0, ""


def stamp_ledger_watermark(st: dict, name: str, rows: list) -> None:
    """Record, at acceptance time, the validated ledger prefix that every
    later task must preserve byte-for-byte."""
    st.setdefault("ledger_accept", {})[name] = {
        "count": len(rows), "digest": ledger_prefix_digest(rows), "at": eutil.utc_now()}


def _ledger_prefix_errors(rows: list, prior_count, prior_digest, label: str) -> list[str]:
    try:
        n = int(prior_count or 0)
    except (TypeError, ValueError):
        n = 0
    if n <= 0 or not prior_digest:
        return []   # pre-binding tasks (or empty prior pool): nothing to hold
    if len(rows) < n:
        return [f"LEDGER_PREFIX_REWRITTEN: {label}: the ledger holds {len(rows)} rows but held {n} "
                "when this task was created - append-only history was deleted; restore the old rows "
                "exactly, then APPEND your new ones"]
    if ledger_prefix_digest(rows[:n]) != str(prior_digest):
        return [f"LEDGER_PREFIX_REWRITTEN: {label}: rows 1..{n} changed since this task was created - "
                "append-only means existing rows are immutable facts (other ledgers cite them by id); "
                "restore them byte-for-byte and APPEND new rows instead"]
    return []


def v_evidence(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    ctx.use_draft_ledgers("evidence")   # R9: this task owns EVIDENCE.jsonl
    recs = ctx.store.evidence()
    errs.extend(_ledger_prefix_errors(recs, task["subject"].get("prior_evidence_count"),
                                      task["subject"].get("prior_digest"), "EVIDENCE.jsonl"))
    bud = ctx.cfg.get("budgets", {})
    bs, _, _ = ctx.dossier_ids()
    att_min = int(bud.get("retrieval_attempts_min", 2))
    ids: set[str] = set()
    allowed_relevance = bs | set(econfig.cell_spec(ctx.cfg))
    for i, rec in enumerate(recs):
        errs.extend(_evidence_schema_errors(rec, i, att_min))
        rid = str(rec.get("id") or "")
        if rid in ids:
            errs.append(f"EVIDENCE_DUP: duplicate id {rid}")
        ids.add(rid)
        for b in rec.get("relevance") or []:
            if not isinstance(b, str) or b not in allowed_relevance:
                errs.append(f"EVIDENCE_RELEVANCE_UNKNOWN: {rid}: relevance {b!r} is neither a dossier B# nor a target cell C# (the same domain deep_read appends under)")
    prior = int(task["subject"].get("prior_evidence_count") or 0)
    new = len(recs) - prior
    if len(recs) < bud.get("evidence_min_total", 0):
        errs.append(f"EVIDENCE_TOTAL: pool has {len(recs)} records; needs >= {bud.get('evidence_min_total')}")
    min_new = int(task["subject"].get("min_new") or bud.get("evidence_min_new_per_round", 0))
    if prior > 0 and new < min_new:
        errs.append(f"EVIDENCE_NEW: a detected coverage gap needs >= {min_new} targeted additions; added {new}")
    years = [r.get("year") for r in recs if isinstance(r.get("year"), int)]
    if years:
        recent = sum(1 for y in years if y >= bud.get("evidence_recent_year", 0))
        ratio = recent / len(years)
        if ratio < float(bud.get("evidence_min_recent_ratio", 0)):
            errs.append(
                f"EVIDENCE_RECENCY: only {ratio:.0%} of the pool is from {bud.get('evidence_recent_year')}+; "
                f"needs >= {float(bud.get('evidence_min_recent_ratio', 0)):.0%}. Retrieve current work, not classics only."
            )
    new_recs = recs[prior:]
    new_years = [r.get("year") for r in new_recs if isinstance(r.get("year"), int)]
    if new_years:
        recent_new = sum(1 for y in new_years if y >= bud.get("evidence_recent_year", 0))
        if recent_new / len(new_years) < float(bud.get("evidence_min_recent_ratio", 0)):
            errs.append(
                f"EVIDENCE_NEW_RECENCY: only {recent_new}/{len(new_years)} records added this round are from "
                f"{bud.get('evidence_recent_year')}+; the refresh must track the frontier, not restock classics."
            )
    # coverage duty: every bottleneck targeted by THIS round's portfolio must be supplied -
    # a global pool total can hide a lane whose bottleneck got zero records
    rid = task["subject"].get("round")
    pf_p = eutil.rpath(ctx.store.repo, f".evo/rounds/{rid}/PORTFOLIO.json") if rid else None
    if pf_p is not None and pf_p.exists():
        try:
            import json as _json
            pf = _json.loads(eutil.read_text(pf_p))
        except Exception:
            pf = {}
        targeted: set[str] = set()
        for ln in pf.get("lanes") or []:
            if str((ln or {}).get("experiment_purpose") or "candidate") in econfig.INSTRUMENTAL_PURPOSES:
                continue  # R5: diagnostics don't enter the novelty pipeline
            targeted.update((ln or {}).get("bottleneck_ids") or [])
        need_b = int(bud.get("evidence_min_per_bottleneck", 0))
        need_br = int(bud.get("evidence_recent_min_per_bottleneck", 0))
        ry = int(bud.get("evidence_recent_year", 0))
        for b in sorted(targeted):
            rows = [r for r in recs if b in (r.get("relevance") or [])]
            if len(rows) < need_b:
                errs.append(f"EVIDENCE_BOTTLENECK_COVERAGE: bottleneck {b} is targeted by this round's "
                            f"portfolio but the pool has only {len(rows)} records tagged for it "
                            f"(need >= {need_b}); retrieve for THIS bottleneck, not just for the pool average")
            elif sum(1 for r in rows if isinstance(r.get("year"), int) and r["year"] >= ry) < need_br:
                errs.append(f"EVIDENCE_BOTTLENECK_RECENT: bottleneck {b} has no fresh supply "
                            f"(need >= {need_br} records from {ry}+ tagged for it)")
    return errs


def v_deep_read(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    # R9: this task owns the mechanism/collision ledgers and appends evidence -
    # its own draft rows (and their cross-references to each other) must be
    # visible to it, while every consumer elsewhere sees accepted history only.
    ctx.use_draft_ledgers("evidence", "mech", "collision")
    lane_id = task["subject"].get("lane")
    lane = ctx.store.get_lane(ctx.st, lane_id) or {}
    origin = str(lane.get("search_origin") or "repair")
    moon = lane.get("intent") == "moonshot"
    all_mech = ctx.store.mech_cards()
    # R7 multi-round audit: M ids are GLOBAL facts (every later card cites a
    # bare M###), but uniqueness was only checked inside the current lane -
    # a cross-lane duplicate was accepted and silently rebound every earlier
    # citation (global consumers are last-row-wins dicts). Check the whole
    # ledger BEFORE the lane filter; prefix binding below protects old bytes.
    _seen_mech_global: set[str] = set()
    _dup_reported: set[str] = set()
    for _row in all_mech:
        _rid = str((_row or {}).get("id") or "") if isinstance(_row, dict) else ""
        if _rid and _rid in _seen_mech_global and _rid not in _dup_reported:
            errs.append(f"MECH_DUP_GLOBAL: {_rid} appears more than once in MECH_CARDS.jsonl - "
                        "M ids are global facts and a duplicate rebinds every earlier citation; "
                        "continue numbering from the FULL ledger's maximum id")
            _dup_reported.add(_rid)
        _seen_mech_global.add(_rid)
    errs.extend(_ledger_prefix_errors(ctx.store.evidence(), task["subject"].get("prior_evidence_count"),
                                      task["subject"].get("prior_evidence_digest"), "EVIDENCE.jsonl"))
    errs.extend(_ledger_prefix_errors(all_mech, task["subject"].get("prior_mech_count"),
                                      task["subject"].get("prior_mech_digest"), "MECH_CARDS.jsonl"))
    errs.extend(_ledger_prefix_errors(ctx.store.collision_audits(),
                                      task["subject"].get("prior_collision_count"),
                                      task["subject"].get("prior_collision_digest"),
                                      "COLLISION_AUDITS.jsonl"))
    cards = [c for c in all_mech if c.get("lane") == lane_id]
    bud = ctx.cfg.get("budgets", {})
    # per-lane targeted top-up: deep_read MAY append evidence records the round's
    # batch retrieval missed (need-driven; no recency duty, but full schema + dedup)
    prior_ev = int(task["subject"].get("prior_evidence_count") or 0)
    all_recs = ctx.store.evidence()
    seen_ids = {str(r.get("id") or "") for r in all_recs[:prior_ev]}
    bs_all, _, _ = ctx.dossier_ids()
    att_min = int(bud.get("retrieval_attempts_min", 2))
    for i, rec in enumerate(all_recs[prior_ev:]):
        for e in _evidence_schema_errors(rec, prior_ev + i, att_min):
            errs.append(f"DEEPREAD_EVIDENCE_SCHEMA: {e}")
        rid_ = str(rec.get("id") or "")
        if rid_ in seen_ids:
            errs.append(f"DEEPREAD_EVIDENCE_DUP: appended record reuses id {rid_}")
        seen_ids.add(rid_)
        allowed_relevance = bs_all | set(econfig.cell_spec(ctx.cfg))
        for b in rec.get("relevance") or []:
            if not isinstance(b, str) or b not in allowed_relevance:
                errs.append(f"DEEPREAD_EVIDENCE_RELEVANCE: {rid_}: {b!r} is neither dossier B# nor target C#")
    if moon:
        need = econfig.budget(ctx.cfg, "mech_cards_min_moonshot")
        min_papers = econfig.budget(ctx.cfg, "mech_papers_min_moonshot")
    elif origin == "theory_derived":
        need = econfig.budget(ctx.cfg, "mech_cards_min_theory_derived")
        min_papers = econfig.budget(ctx.cfg, "mech_papers_min_theory_derived")
    elif origin in ("constructive", "core_synthesis"):
        need = econfig.budget(ctx.cfg, "mech_cards_min_constructive")
        min_papers = econfig.budget(ctx.cfg, "mech_papers_min_constructive")
    else:
        need = econfig.budget(ctx.cfg, "mech_cards_min_per_lane")
        min_papers = min(need, 5)
    if len(cards) < need:
        errs.append(f"MECH_COUNT: lane {lane_id} has {len(cards)} mechanism cards; needs >= {need}"
                    + (" (L4/moonshot lanes carry a deeper reading program)" if moon else ""))
    ev = ctx.evidence_ids()
    seen: set[str] = set()
    papers: set[str] = set()
    for c in cards:
        cid = str(c.get("id") or "")
        allowed_card = {
            "id", "lane", "paper", "name", "topic", "problem", "old_program",
            "new_program", "program_operations", "irreducible_core",
            "necessary_components", "support_components", "core_math", "assumptions",
            "reported_effect", "ablation_support", "resource_delta", "gain_confound",
            "transfer_conditions", "failure_modes", "quote",
        }
        extra_card = sorted(set(c) - allowed_card)
        if extra_card:
            errs.append(f"MECH_FIELDS: {cid}: reusable paper facts have unknown fields {extra_card}; "
                        "candidate-specific comparisons belong in COLLISION_AUDITS.jsonl")
        if not re.fullmatch(r"M\d{3,4}", cid):
            errs.append(f"MECH_ID: card id must be M### (got {cid!r})")
        if cid in seen:
            errs.append(f"MECH_DUP: duplicate mechanism card id {cid}")
        seen.add(cid)
        if not isinstance(c.get("paper"), str) or c.get("paper") not in ev:
            errs.append(f"MECH_PAPER_UNRESOLVED: {cid}: paper {c.get('paper')!r} not in EVIDENCE.jsonl")
        else:
            papers.add(c["paper"])
        _nontrivial(c.get("name"), 5, f"{cid}.name", errs)
        _nontrivial(c.get("problem"), 30, f"{cid}.problem", errs)
        _nontrivial(c.get("core_math"), 40, f"{cid}.core_math (the actual formulation, not a summary)", errs)
        _nontrivial(c.get("transfer_conditions"), 40, f"{cid}.transfer_conditions", errs)
        _nontrivial(c.get("failure_modes"), 30, f"{cid}.failure_modes", errs)
        # Schema v2 reconstructs the paper's actual core work, not its stated
        # motivation. These fields make nearest-prior comparison program-level.
        _nontrivial(c.get("old_program"), 50, f"{cid}.old_program", errs)
        _nontrivial(c.get("new_program"), 50, f"{cid}.new_program", errs)
        ops = c.get("program_operations")
        if not isinstance(ops, list) or not ops or any(len(str(x).strip()) < 10 for x in ops):
            errs.append(f"MECH_PROGRAM_OPS: {cid}: program_operations needs substantive old->new operations")
        _nontrivial(c.get("irreducible_core"), 60, f"{cid}.irreducible_core", errs)
        for field in ("necessary_components", "support_components"):
            if not isinstance(c.get(field), list):
                errs.append(f"MECH_COMPONENT_LEDGER: {cid}.{field} must be an explicit array")
        _nontrivial(c.get("ablation_support"), 40, f"{cid}.ablation_support", errs)
        _nontrivial(c.get("resource_delta"), 40, f"{cid}.resource_delta", errs)
        _nontrivial(c.get("gain_confound"), 40, f"{cid}.gain_confound", errs)
        if not isinstance(c.get("assumptions"), list) or not c.get("assumptions"):
            errs.append(f"MECH_ASSUMPTIONS: {cid}: 'assumptions' must be a non-empty list")
        # v10.1: the quote requirement was dropped.  Unlike the critic quotes
        # (checked literally against a local document), a paper quote cannot be
        # verified here, and no downstream check reads it - it was a length
        # check pretending to be a grounding check.  The field stays legal.
    if cards and len(papers) < min_papers:
        errs.append(f"MECH_PAPER_SPREAD: cards for lane {lane_id} cover {len(papers)} distinct papers; need >= {min_papers}")
    years = ctx.evidence_years()
    ry = ctx.recent_year()
    recent_cards = sum(1 for c in cards if isinstance(c.get("paper"), str)
                       and isinstance(years.get(c["paper"]), int) and years[c["paper"]] >= ry)
    need_recent = int(bud.get("mech_cards_recent_min_per_lane", 1))
    if recent_cards < need_recent:
        errs.append(
            f"MECH_RECENCY: lane {lane_id} has {recent_cards} mechanism cards from {ry}+ papers; needs >= {need_recent}. "
            f"Classics may support, but the lane must extract at least this much from the current frontier."
        )
    # critic-directed reading: every required topic must be covered by a card of this lane
    for topic in lane.get("required_topics") or []:
        tn = eutil.norm_ws(topic)
        covered = any(tn in eutil.norm_ws(str(c.get("topic") or "") + " " + str(c.get("name") or ""))
                      for c in cards)
        if not covered:
            errs.append(f"MECH_TOPIC_UNCOVERED: the challenge critic required reading on '{topic}'; no card of "
                        f"lane {lane_id} carries it (set the card's 'topic' field to the requested topic)")
    # Candidate-specific comparisons are append-only edges, not mutable fields
    # on reusable M# paper facts.  Binding both file and candidate digests makes
    # resketch attempts with recycled K1..K4 ids impossible to satisfy using an
    # earlier program set's reading.
    if lane.get("sketches_path"):
        if json_file_digest(ctx, lane["sketches_path"]) != lane.get("program_set_digest"):
            errs.append("DEEPREAD_PROGRAM_MUTATED: program set changed after the constructive freeze")
        pdata = eutil.read_json(eutil.rpath(ctx.store.repo, lane["sketches_path"]), {}) or {}
        candidates = {str(s.get("sketch_id")): s for s in pdata.get("sketches") or [] if isinstance(s, dict)}
        all_edges = ctx.store.collision_audits()
        edge_ids: set[str] = set()
        current: list[dict] = []
        mech_all = ctx.mech_by_id()
        for i, edge in enumerate(all_edges):
            edge = edge if isinstance(edge, dict) else {}
            eid = str(edge.get("id") or "")
            # \d{3,4}: agent-numbered append-only ledgers must not have a
            # validator-imposed 1000-id ceiling - a long research run consumes
            # tens of CA ids per round and would otherwise deadlock at CA999
            # (R1 audit; the tombstone-side regexes already accept 4 digits).
            if not re.fullmatch(r"CA\d{3,4}", eid) or eid in edge_ids:
                errs.append(f"COLLISION_ID: collision_audits[{i}] needs a globally unique CA### id")
            edge_ids.add(eid)
            allowed_edge = {"id", "lane", "program_set_digest", "candidate_id", "candidate_digest",
                            "mech_card_id", "axis", "query", "program_overlap",
                            "irreducible_difference", "emulation_test", "recent_search_saturation"}
            extra_edge = sorted(set(edge) - allowed_edge)
            if extra_edge:
                errs.append(f"COLLISION_FIELDS: {eid}: unknown fields {extra_edge}")
            if edge.get("program_set_digest") != lane.get("program_set_digest") or edge.get("lane") != lane_id:
                continue
            current.append(edge)
            sid = str(edge.get("candidate_id") or "")
            cand = candidates.get(sid)
            if cand is None:
                errs.append(f"COLLISION_CANDIDATE: {eid}: candidate_id {sid!r} is not in the current frozen set")
            elif edge.get("candidate_digest") != eprogram.candidate_digest(cand):
                errs.append(f"COLLISION_CANDIDATE_DIGEST: {eid}: edge does not bind the exact current program")
            mid = str(edge.get("mech_card_id") or "")
            if mid not in mech_all:
                errs.append(f"COLLISION_MECH: {eid}: mech_card_id {mid!r} does not resolve")
            if edge.get("axis") not in ("mechanism", "task_effect"):
                errs.append(f"COLLISION_AXIS: {eid}: axis must be mechanism|task_effect")
            _nontrivial(edge.get("query"), 40, f"{eid}.query", errs)
            _nontrivial(edge.get("program_overlap"), 60, f"{eid}.program_overlap", errs)
            _nontrivial(edge.get("irreducible_difference"), 80, f"{eid}.irreducible_difference", errs)
            _nontrivial(edge.get("emulation_test"), 80, f"{eid}.emulation_test", errs)
        stale_same_lane = sum(
            1 for e in all_edges
            if isinstance(e, dict) and e.get("lane") == lane_id
            and e.get("program_set_digest") != lane.get("program_set_digest"))
        for sid in candidates:
            bound = [e for e in current if str(e.get("candidate_id") or "") == sid]
            axes = {str(e.get("axis") or "") for e in bound}
            if axes != {"mechanism", "task_effect"}:
                # R3 operability audit: digest-mismatched edges are silently
                # skipped above (historical attempts legitimately stay in the
                # append-only ledger), so this error used to blame MISSING
                # edges the agent had visibly just written. Name the expected
                # digest and the mismatch count so the fix is discoverable.
                errs.append(f"COLLISION_COVERAGE: {sid}: the current frozen set (program_set_digest "
                            f"{str(lane.get('program_set_digest'))}) needs candidate-bound mechanism and "
                            f"task_effect edges (got {sorted(axes)})"
                            + (f"; {stale_same_lane} same-lane edge(s) bind a DIFFERENT digest - stale "
                               "earlier attempts are normal, but if you just wrote them, copy the digest "
                               "above VERBATIM (it is the engine's canonical-JSON hash from the bundle's "
                               "Frozen digests block, not a raw-file sha256)" if stale_same_lane else ""))
            recent = any(isinstance(ctx.evidence_years().get((mech_all.get(str(e.get("mech_card_id") or "")) or {}).get("paper")), int)
                         and ctx.evidence_years()[(mech_all.get(str(e.get("mech_card_id") or "")) or {}).get("paper")] >= ctx.recent_year()
                         for e in bound)
            if bound and not recent and not any(len(str(e.get("recent_search_saturation") or "").strip()) >= 80
                                                for e in bound):
                errs.append(f"COLLISION_RECENCY: {sid}: needs a {ctx.recent_year()}+ neighbor or an >=80-char "
                            "recent_search_saturation on the queries that established absence")
    return errs


# ---- frozen repair diagnosis -------------------------------------------------------------

def v_diagnose(ctx: Ctx, task: dict) -> list[str]:
    """Freeze a repair diagnosis before program synthesis and targeted reading.

    This is not a prose preference: the canonical digest is carried through
    reading, program synthesis and maturation, making post-hoc re-diagnosis a
    mechanically visible contract break.
    """
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"].get("lane"))
    data = _read_json(ctx, task["outputs"][0], errs)
    if lane is None or not isinstance(data, dict):
        return errs or ["INTERNAL: lane missing"]
    allowed = {"lane", "problem", "evidence", "hypotheses", "leading_hypothesis",
               "invariants", "unknowns", "solution_proposals"}
    extra = sorted(set(data) - allowed)
    if extra:
        errs.append(f"DIAGNOSIS_FIELDS: unknown top-level fields {extra}; diagnosis cannot smuggle in solution choices")
    if data.get("lane") != lane["id"]:
        errs.append(f"DIAGNOSIS_LANE: lane must be {lane['id']!r}")
    _nontrivial(data.get("problem"), 80, "diagnosis.problem (the observed failure, not a proposed method)", errs)
    if data.get("solution_proposals") is not False:
        errs.append("DIAGNOSIS_NO_SOLUTION: solution_proposals must be false; freeze the problem before candidate synthesis")
    serialized = json.dumps(data, ensure_ascii=False)
    if re.search(r"\b(?:SIG\d{2}|MV\d{2}|M\d{3,4}|E\d{3,4})\b|https?://|arxiv\.org", serialized, re.I):
        errs.append("DIAGNOSIS_SOLUTION_LEAK: diagnosis may not cite candidate-pattern ids, mechanism cards, papers, or URLs; route-specific evidence follows the frozen diagnosis")

    evidence = data.get("evidence")
    if not isinstance(evidence, list) or len(evidence) < 2:
        errs.append("DIAGNOSIS_EVIDENCE_COUNT: diagnosis needs >= 2 concrete, independently named observations")
        evidence = []
    eids: set[str] = set()
    bs, _, _ = ctx.dossier_ids()
    obs, nodes = ctx.obs_ids(), set(egraph.by_id(ctx.g))
    for i, item in enumerate(evidence):
        item = item if isinstance(item, dict) else {}
        extra_i = sorted(set(item) - {"id", "source", "observation"})
        if extra_i:
            errs.append(f"DIAGNOSIS_EVIDENCE_FIELDS: evidence[{i}] has unknown fields {extra_i}")
        eid = str(item.get("id") or "")
        if not re.fullmatch(r"DX\d+", eid) or eid in eids:
            errs.append(f"DIAGNOSIS_EVIDENCE_ID: evidence[{i}] needs a unique id DX#")
        eids.add(eid)
        src = str(item.get("source") or "")
        profile_src = src.startswith("profile:") and _exists(ctx, src.split(":", 1)[1])
        if src not in bs and src not in obs and src not in nodes and not profile_src:
            errs.append(f"DIAGNOSIS_SOURCE: {eid}: source {src!r} must resolve to B#, OB###, N###, or profile:<existing path>")
        _nontrivial(item.get("observation"), 35, f"diagnosis evidence {eid}.observation", errs)

    hypotheses = data.get("hypotheses")
    if not isinstance(hypotheses, list) or len(hypotheses) < 2:
        errs.append("DIAGNOSIS_HYPOTHESES_COUNT: register >= 2 competing hypotheses before selecting a method")
        hypotheses = []
    hids: set[str] = set()
    for i, hyp in enumerate(hypotheses):
        hyp = hyp if isinstance(hyp, dict) else {}
        extra_h = sorted(set(hyp) - {"id", "statement", "explains", "falsifier", "discriminating_observation"})
        if extra_h:
            errs.append(f"DIAGNOSIS_HYPOTHESIS_FIELDS: hypotheses[{i}] has unknown fields {extra_h}")
        hid = str(hyp.get("id") or "")
        if not re.fullmatch(r"H\d+", hid) or hid in hids:
            errs.append(f"DIAGNOSIS_HYPOTHESIS_ID: hypotheses[{i}] needs a unique id H#")
        hids.add(hid)
        _nontrivial(hyp.get("statement"), 50, f"hypothesis {hid}.statement", errs)
        explains = hyp.get("explains")
        if not isinstance(explains, list) or not explains \
                or any(not isinstance(x, str) or x not in eids for x in explains):
            errs.append(f"DIAGNOSIS_HYPOTHESIS_EVIDENCE: {hid}.explains must be a non-empty list of DX# ids")
        _nontrivial(hyp.get("falsifier"), 40, f"hypothesis {hid}.falsifier", errs)
        _nontrivial(hyp.get("discriminating_observation"), 40,
                    f"hypothesis {hid}.discriminating_observation", errs)
    if data.get("leading_hypothesis") is not None \
            and (not isinstance(data.get("leading_hypothesis"), str)
                 or data.get("leading_hypothesis") not in hids):
        errs.append("DIAGNOSIS_LEADER: leading_hypothesis, when given, must resolve to a registered H#")
    for field in ("invariants", "unknowns"):
        vals = data.get(field)
        if not isinstance(vals, list) or not vals or any(len(str(v).strip()) < 20 for v in vals):
            errs.append(f"DIAGNOSIS_{field.upper()}: {field} needs a non-empty list of substantive statements")
    return errs


def _stagnant_window(ctx: Ctx, k: int) -> bool:
    """True when no contract-level frontier movement occurred for k rounds."""
    if k <= 0:
        return False
    hist = [r for r in ctx.st.get("rounds", []) if r.get("closed_at")]
    if len(hist) < k:
        return False
    window = hist[-k:]
    # A corrected historical snapshot cannot be reconstructed from today's
    # graph without time travel.  Unknown history is not evidence of
    # stagnation, so fail open on exploration mandates rather than treating a
    # stale False/True as authoritative.
    if any(not isinstance(r.get("improved"), bool)
           or r.get("projection_status") not in {None, "active"} for r in window):
        return False
    return not any(r.get("improved") for r in window)


def v_open_round(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    rid = task["subject"]["round"]
    pf = _read_json(ctx, task["outputs"][0], errs)
    if pf is None:
        return errs
    lanes = pf.get("lanes")
    bud, pol = ctx.cfg.get("budgets", {}), ctx.cfg.get("policy", {})
    # probe/maintenance lanes ride ON TOP of the search-bet count: they are
    # instrumental work, so they neither crowd out nor stand in for idea lanes.
    bet_count = (sum(1 for ln in lanes
                     if (ln or {}).get("experiment_purpose") not in econfig.INJECTABLE_PURPOSES)
                 if isinstance(lanes, list) else 0)
    if not isinstance(lanes, list) or not (bud.get("lanes_per_round_min", 1) <= bet_count <= bud.get("lanes_per_round_max", 3)):
        # "portfolio slots", not "search bets": a targeted ablation occupies a
        # slot here although the exploit-share arithmetic below rightly refuses
        # to count it as a search bet - one shared word for two different sets
        # misled readers of either message.
        errs.append(f"PORTFOLIO_LANE_COUNT: need {bud.get('lanes_per_round_min')}..{bud.get('lanes_per_round_max')} "
                    f"portfolio lanes (candidates + targeted ablations; probe/maintenance ride on top), "
                    f"got {bet_count if isinstance(lanes, list) else 'none'}")
        return errs
    for cap_purpose, cap_key in sorted(econfig.INJECTABLE_CAP_KEYS.items()):
        cap = int(bud.get(cap_key, 1) or 0)
        declared = sum(1 for ln in lanes if (ln or {}).get("experiment_purpose") == cap_purpose)
        if declared > cap:
            errs.append(f"PORTFOLIO_INSTRUMENTAL_CAP: {declared} {cap_purpose} lanes exceed "
                        f"budgets.{cap_key}={cap}")
    idx = egraph.by_id(ctx.g)
    fr_ids = {n["id"] for n in egraph.frontier(ctx.g, ctx.cfg, ctx.st)}
    plat_ok = {n["id"] for n in egraph.platforms(ctx.g) if n.get("verdict") == "enabled"}
    bs, _, _ = ctx.dossier_ids()
    floors = pol.get("scope_floor", {})
    names = set()
    for i, ln in enumerate(lanes):
        w = f"lane[{i}]({ln.get('name')})"
        name = str(ln.get("name") or "").strip()
        if not name or name in names:
            errs.append(f"PORTFOLIO_LANE_NAME: {w}: unique non-empty 'name' required")
        names.add(name)
        intent = ln.get("intent")
        if intent not in econfig.LANE_INTENTS:
            errs.append(f"PORTFOLIO_INTENT: {w}: intent must be one of {econfig.LANE_INTENTS}")
            continue
        purpose = ln.get("experiment_purpose")
        if purpose not in econfig.EXPERIMENT_PURPOSES:
            errs.append(f"PORTFOLIO_PURPOSE: {w}: experiment_purpose must be one of "
                        f"{econfig.EXPERIMENT_PURPOSES}")
            purpose = "candidate"
        if purpose == "targeted_ablation":
            if econfig.ablation_mode(ctx.cfg) != "targeted":
                errs.append(f"PORTFOLIO_ABLATION_OFF: {w}: the user-approved ablation policy is off")
        if purpose in econfig.INSTRUMENTAL_PURPOSES and intent != "exploit":
            errs.append(f"PORTFOLIO_INSTRUMENTAL_INTENT: {w}: {purpose} is instrumental work on "
                        "exactly one observed parent, not a novelty/theory, root, hybrid or platform bet")
        if purpose in econfig.EXPLORATORY_PURPOSES and intent == "platform":
            errs.append(f"PORTFOLIO_EXPLORATORY_PLATFORM: {w}: platform lanes carry no claims to "
                        "exempt - declare the platform lane plainly instead of exploratory")
        origin = ln.get("search_origin")
        if origin not in econfig.SEARCH_ORIGINS:
            errs.append(f"PORTFOLIO_SEARCH_ORIGIN: {w}: search_origin must be one of {econfig.SEARCH_ORIGINS}")
            origin = "repair"
        theory_rigor = ln.get("theory_rigor")
        if origin == "theory_derived":
            if theory_rigor not in ("partial", "full"):
                errs.append(f"PORTFOLIO_THEORY_RIGOR: {w}: theory_derived lanes must precommit "
                            "theory_rigor='partial' or 'full'")
        elif "theory_rigor" in ln:
            errs.append(f"PORTFOLIO_THEORY_RIGOR_ROUTE: {w}: theory_rigor belongs only to theory_derived lanes; "
                        "post-program theory is declared independently by a winning sketch")
        if purpose in econfig.INSTRUMENTAL_PURPOSES and origin != "repair":
            errs.append(f"PORTFOLIO_INSTRUMENTAL_ORIGIN: {w}: {purpose} uses search_origin='repair' "
                        "(it grows out of an observed parent, not a search route)")
        floor = int(floors.get(intent, 2))
        ml = ln.get("min_level")
        if purpose in econfig.INSTRUMENTAL_PURPOSES:
            if ml != 0:
                errs.append(f"PORTFOLIO_INSTRUMENTAL_LEVEL: {w}: {purpose} must use min_level=0. "
                            "It is instrumental work, not an innovation-level claim.")
        elif not isinstance(ml, int) or isinstance(ml, bool) or ml < floor:
            errs.append(f"PORTFOLIO_MIN_LEVEL: {w}: min_level must be int >= {floor} for intent '{intent}'")
        parents = ln.get("parents") or []
        bad_parents = [p for p in parents if not isinstance(p, str)]
        if bad_parents:
            errs.append(f"PORTFOLIO_PARENT_UNKNOWN: {w}: parents {bad_parents!r} must be N### strings")
            parents = [p for p in parents if isinstance(p, str)]
        # R8 (external audit r5): a repeated parent id satisfied the hybrid
        # ">= 2 parents" length check here, then downstream sketch validation
        # demanded BOTH exact equality with the frozen duplicate list AND a
        # unique array - a frozen contract with no satisfying candidate.
        dup_parents = sorted({p for p in parents if parents.count(p) > 1})
        if dup_parents:
            errs.append(f"PORTFOLIO_PARENT_DUP: {w}: parents list repeats {dup_parents} - each parent "
                        "may appear once (hybrid needs >= 2 DISTINCT model parents)")
        parents = list(dict.fromkeys(parents))
        model_parents = [p for p in parents if p in idx and idx[p].get("role") != "platform"]
        plats = [p for p in parents if p in idx and idx[p].get("role") == "platform"]
        unknown = [p for p in parents if p not in idx]
        if unknown:
            errs.append(f"PORTFOLIO_PARENT_UNKNOWN: {w}: parents {unknown} do not exist")
        for p in model_parents:
            for kind, detail in model_parent_defects(idx, p):
                errs.append(f"PORTFOLIO_PARENT_{kind.upper()}: {w}: {detail}")
            for detail in parent_hold_defects(ctx, p):
                errs.append(f"PORTFOLIO_PARENT_HELD: {w}: {detail}")
        for p in plats:
            if p not in plat_ok:
                errs.append(f"PORTFOLIO_PLATFORM_NOT_ENABLED: {w}: platform {p} is not concluded/enabled")
        if intent in ("exploit", "reform") and len(model_parents) != 1:
            errs.append(f"PORTFOLIO_PARENTS_{intent.upper()}: {w}: needs exactly 1 model parent, got {model_parents}")
        if intent == "exploit" and purpose == "candidate" and model_parents \
                and not ln.get("scaling_followup_of"):
            # Maintenance nodes are frontier-transparent: an exploit may parent
            # the repaired base when the lineage it proxies is on the frontier.
            # v11.1 (R1 fix): a scaling follow-up's parent is pinned by its own
            # pre-registration ("after_positive_signal" = parent concluded
            # positive) - requiring settled-promotion frontier membership on
            # top re-created the door-blocked-by-another-rule contradiction.
            effective = egraph.effective_frontier_ancestor(idx, model_parents[0])
            if effective not in fr_ids:
                errs.append(f"PORTFOLIO_EXPLOIT_OFF_FRONTIER: {w}: exploit parent {model_parents[0]} "
                            f"(frontier ancestor {effective}) is not on the active frontier")
        if intent in ("wildcat", "moonshot") and model_parents:
            errs.append(f"PORTFOLIO_PARENTS_{intent.upper()}: {w}: {intent} lanes take no model parents (platforms allowed)")
        if intent in ("wildcat", "moonshot") and origin == "repair":
            errs.append(f"PORTFOLIO_ROOT_ORIGIN: {w}: a root lane must be constructive or theory_derived; "
                        "repair requires an observed model parent")
        if intent == "hybrid" and len(model_parents) < 2:
            errs.append(f"PORTFOLIO_PARENTS_HYBRID: {w}: needs >= 2 model parents, got {model_parents}")
        if intent == "hybrid" and origin == "repair":
            errs.append(f"PORTFOLIO_HYBRID_ORIGIN: {w}: hybrid search constructs a new coupling and cannot use repair")
        if intent == "platform" and model_parents:
            errs.append(f"PORTFOLIO_PARENTS_PLATFORM: {w}: platform lanes take no model parents")
        # v11.1 P2: the legal door for pre-registered follow-up scaling. Until
        # now IDEA_SCALING_FOLLOWUP demanded a follow-up node while kernel-dup
        # and research-novelty checks made that node impossible to open.
        sfo = ln.get("scaling_followup_of")
        if sfo is not None:
            sfo = str(sfo)
            sp = idx.get(sfo)
            if not sp:
                errs.append(f"PORTFOLIO_SCALING_FOLLOWUP_UNKNOWN: {w}: scaling_followup_of {sfo} does not exist")
            else:
                if econfig.scaling_mode(ctx.cfg) not in ("budgeted", "full"):
                    errs.append(f"PORTFOLIO_SCALING_FOLLOWUP_MODE: {w}: scaling_mode="
                                f"'{econfig.scaling_mode(ctx.cfg)}' does not fund follow-up scale arms")
                if intent != "exploit":
                    errs.append(f"PORTFOLIO_SCALING_FOLLOWUP_INTENT: {w}: a scaling follow-up extends one "
                                "observed parent; intent must be exploit")
                if purpose != "candidate":
                    errs.append(f"PORTFOLIO_SCALING_FOLLOWUP_PURPOSE: {w}: a scaling follow-up is a real "
                                f"candidate bet, not {purpose}")
                meta = {}
                if sp.get("idea_doc"):
                    meta = eutil.read_json(eutil.rpath(ctx.store.repo,
                                                       str(sp["idea_doc"]).replace(".md", ".meta.json")), {}) or {}
                if ((meta.get("scaling") or {}).get("execution")) != "followup_node":
                    errs.append(f"PORTFOLIO_SCALING_FOLLOWUP_UNREGISTERED: {w}: {sfo} did not pre-register "
                                "execution='followup_node' scaling in its idea meta; only a declared "
                                "after-positive-signal plan may buy scale arms")
                if model_parents != [sfo]:
                    errs.append(f"PORTFOLIO_SCALING_FOLLOWUP_PARENTS: {w}: the lane's single model parent "
                                f"must be {sfo} itself - it is the comparator at the base scale")
                if sp.get("verdict") not in ("improved", "specialist", "dominant", "promising"):
                    errs.append(f"PORTFOLIO_SCALING_FOLLOWUP_SIGNAL: {w}: the registered trigger is "
                                f"after_POSITIVE_signal; parent {sfo} concluded "
                                f"'{sp.get('verdict')}' - there is no positive signal to scale")
                # (final audit C23) the pool includes THIS portfolio's other
                # lanes - two same-plan lanes naming one parent both predate
                # lane creation, so state/graph scanning alone missed them.
                spent = [x for x in list(ctx.st.get("lanes", [])) + list(ctx.g.get("nodes", []))
                         + [l2 for j, l2 in enumerate(lanes) if j != i and isinstance(l2, dict)]
                         if str(x.get("scaling_followup_of") or "") == sfo
                         and x.get("status") not in ("abandoned",)]
                if spent:
                    errs.append(f"PORTFOLIO_SCALING_FOLLOWUP_DUP: {w}: {sfo} already has a live scaling "
                                f"follow-up ({str(spent[0].get('id') or spent[0].get('name'))}); one "
                                "registered plan buys one follow-up - a second requires its own "
                                "registration on a new node")
        # v11.1 (R1 fix): the confirmatory door - the only legal way to re-run
        # an exploratory scout's kernel, and it pays FULL rigor (no exemption
        # from predictions/SOTA/novelty duties anywhere on this lane).
        cfo = ln.get("confirmatory_of")
        if cfo is not None:
            cfo = str(cfo)
            cp = idx.get(cfo)
            if not cp:
                errs.append(f"PORTFOLIO_CONFIRMATORY_UNKNOWN: {w}: confirmatory_of {cfo} does not exist")
            else:
                if ln.get("scaling_followup_of"):
                    errs.append(f"PORTFOLIO_CONFIRMATORY_OVERLOAD: {w}: one lane cannot be both a scaling "
                                "follow-up and a confirmatory re-run")
                if cp.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES:
                    errs.append(f"PORTFOLIO_CONFIRMATORY_TARGET: {w}: {cfo} is not an exploratory node; "
                                "only a declared scout's kernel may be re-run for confirmation")
                if cp.get("retire_reason"):
                    # R7 audit: a deliberately retired (pruned/archived) scout
                    # slipped through the copy-exemption door without the
                    # revival its retirement demands - the parent firewall
                    # never fires because a scout is not a model parent.
                    errs.append(f"PORTFOLIO_CONFIRMATORY_RETIRED: {w}: scout {cfo} is retired "
                                f"({cp.get('retire_reason')}); reopen it explicitly first "
                                f"('evo revive --node {cfo} --note ...') before its confirmation "
                                "door grants the duplicate-kernel exemption")
                if cp.get("status") != "concluded":
                    errs.append(f"PORTFOLIO_CONFIRMATORY_UNFINISHED: {w}: scout {cfo} is "
                                f"'{cp.get('status')}' - only a CONCLUDED scout can be confirmed; an "
                                "abandoned/pruned scout never will be, so drop this lane in that case")
                if purpose != "candidate":
                    errs.append(f"PORTFOLIO_CONFIRMATORY_PURPOSE: {w}: a confirmatory re-run is a full-rigor "
                                f"candidate, not {purpose} (an exploratory confirming an exploratory "
                                "would compound exemptions)")
                if intent == "platform":
                    # R9 (external audit r6): a platform lane skips evaluation
                    # entirely and can never own a model record, yet it would
                    # permanently consume the scout's ONE confirmation slot -
                    # the engine would then claim the confirmation was spent
                    # while no full-rigor confirmation exists.
                    errs.append(f"PORTFOLIO_CONFIRMATORY_PLATFORM: {w}: a confirmatory re-run must be a "
                                "model candidate that runs the full evaluation/effect contract; a "
                                "platform lane skips evaluation and cannot become the scout's record "
                                "owner, so it may not consume the one confirmation slot")
                spent_c = [x for x in list(ctx.st.get("lanes", [])) + list(ctx.g.get("nodes", []))
                           + [l2 for j, l2 in enumerate(lanes) if j != i and isinstance(l2, dict)]
                           if str(x.get("confirmatory_of") or "") == cfo
                           and x.get("status") not in ("abandoned",)]
                if spent_c:
                    errs.append(f"PORTFOLIO_CONFIRMATORY_DUP: {w}: scout {cfo} already has a "
                                f"confirmatory re-run ({str(spent_c[0].get('id') or spent_c[0].get('name'))}); "
                                "one scout buys ONE confirmation - after it concludes, that kernel has a "
                                "real record owner and further copies are ordinary duplicates")
        bots = ln.get("bottleneck_ids") or []
        if origin == "repair" and intent != "platform" and purpose not in econfig.INSTRUMENTAL_PURPOSES \
                and (not bots or any(b not in bs for b in bots)):
            errs.append(f"PORTFOLIO_BOTTLENECKS: {w}: repair lanes need non-empty dossier B# ids (got {bots})")
        if origin != "repair" and any(b not in bs for b in bots):
            errs.append(f"PORTFOLIO_BOTTLENECK_UNKNOWN: {w}: optional bottleneck_ids contain unknown ids {bots}")
        brief = ln.get("brief_md")
        if not brief or not _exists(ctx, brief):
            errs.append(f"PORTFOLIO_BRIEF_MISSING: {w}: brief_md must point at an existing lane brief file")
        else:
            btext = eutil.read_text(eutil.rpath(ctx.store.repo, brief))
            _require_sections(btext, ["goal", "constraints", "forbidden moves"], f"{w} brief", errs)
            if PAPERISH.search(btext):
                errs.append(f"PORTFOLIO_BRIEF_MENU: {w}: brief contains paper links - briefs carry targets and constraints, never candidate techniques")
    # Denominator note (self-review round 2, deliberately NOT changed): the
    # research-mix floors below drop platform lanes from their arithmetic, this
    # cap does not, so a platform lane widens the round enough to admit one more
    # exploit.  Tightening it is a real policy change - it makes portfolios that
    # every earlier version accepted illegal - and the cap is a soft temperament
    # dial, not a correctness gate.  Left as is; the floors, which are the
    # binding research duty, already exclude platforms.
    # v11.1 P5 (R1 fix): exploratory is rigor-exempt BOTH ways in the research
    # shares - and spend-shape-exempt here too: scouts neither dilute the
    # exploit-temperament ratio nor discharge a starved focus direction (their
    # results cannot reach a record, so "service" by scout would be hollow).
    candidate_lanes_for_mix = [ln for ln in lanes
                               if ln.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES
                               and ln.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES]
    n_exploit = sum(1 for ln in candidate_lanes_for_mix if ln.get("intent") == "exploit")
    if len(candidate_lanes_for_mix) >= 2 and \
            n_exploit / len(candidate_lanes_for_mix) > float(pol.get("max_exploit_share", 1.0)) + 1e-9:
        errs.append(f"PORTFOLIO_EXPLOIT_SHARE: {n_exploit}/{len(candidate_lanes_for_mix)} candidate lanes "
                    f"are exploit, above max_exploit_share={pol.get('max_exploit_share')}; diagnostic "
                    "ablation lanes do not count as search bets")
    rnum = int(rid[1:])
    wildcat_every = int(pol.get("wildcat_every_rounds", 0))
    if wildcat_every and rnum % wildcat_every == 0 and not any(
            ln.get("intent") in ("wildcat", "moonshot")
            and ln.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES for ln in lanes):
        errs.append(f"PORTFOLIO_WILDCAT_DUE: round {rid} is a wildcat round (every {wildcat_every}); include one L4 lane (wildcat or moonshot)")
    if _stagnant_window(ctx, int(pol.get("stagnation_rounds", 2))):
        # v9 dedup: in research mode the round-composition floor
        # structural-scope portfolio floor already guarantees L3+ supply whenever the
        # round carries >= 2 idea lanes; re-checking it here was a second rule
        # for the same duty. The stagnation-L3 rule now bites only where the
        # floor does not reach: engineering runs and 1-lane rounds.
        candidate_lanes = [ln for ln in lanes if ln.get("intent") != "platform"
                           and ln.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES
                           and ln.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES]
        subsumed = ctx.is_research() and float(pol.get("research_min_structural_scope_share", 0.5)) > 0 \
            and len(candidate_lanes) >= 2
        if not subsumed and not any(isinstance(ln.get("min_level"), int) and ln.get("min_level", 0) >= 3
                                    for ln in candidate_lanes):
            errs.append(
                "PORTFOLIO_STAGNATION_REQUIRES_REFORM: the frontier has been flat for "
                f"{pol.get('stagnation_rounds')} rounds; this round must contain a lane with min_level >= 3 "
                "(reform, wildcat or moonshot). Incremental exploitation is no longer allowed."
            )
    k2 = int(pol.get("stagnation_moonshot_rounds", 0))
    if k2 and _stagnant_window(ctx, k2):
        # R7 audit: a scout moonshot is observations-only - it cannot pay the
        # forced full-rigor paradigm escape (the card says so; the adjacent
        # wildcat/L3 checks already exclude scouts; this branch missed it).
        if not any(ln.get("intent") == "moonshot"
                   and ln.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES
                   and ln.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES
                   for ln in lanes):
            errs.append(
                f"PORTFOLIO_STAGNATION_REQUIRES_MOONSHOT: the frontier has been flat for {k2} rounds; "
                "this round must contain a MOONSHOT lane - a full-program frontier reformulation/paradigm "
                "attempt. Theory remains independent; local mechanism swaps have stopped paying."
            )
    # Research-mode structural-scope supply: M novelty is enforced separately
    # inside every candidate. Platform lanes are
    # infrastructure, not idea bets - they stay out of the mix arithmetic.
    if ctx.is_research():
        # v11.1 P5: exploratory lanes are rigor-exempt BOTH ways - they neither
        # discharge the research shares nor force other lanes to compensate.
        idea_lanes = [ln for ln in lanes if ln.get("intent") != "platform"
                      and ln.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES
                      and ln.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES]
        if idea_lanes:
            share = float(pol.get("research_min_structural_scope_share", 0.5))
            n_l3 = sum(1 for ln in idea_lanes if isinstance(ln.get("min_level"), int) and ln["min_level"] >= 3)
            if n_l3 / len(idea_lanes) + 1e-9 < share:
                errs.append(f"PORTFOLIO_RESEARCH_MIX: research mode requires >= {share:.0%} of non-platform "
                            f"lanes at subsystem/full-program scope L3+ (got {n_l3}/{len(idea_lanes)}); "
                            "scope is portfolio breadth, while every executed research candidate still passes the independent M gate")
            cshare = float(pol.get("research_min_constructive_share", 0.5))
            n_constructive = sum(1 for ln in idea_lanes
                                 if ln.get("search_origin") in ("constructive", "core_synthesis",
                                                                 "theory_derived"))
            if n_constructive / len(idea_lanes) + 1e-9 < cshare:
                errs.append(f"PORTFOLIO_RESEARCH_CONSTRUCTIVE: research mode requires >= {cshare:.0%} "
                            f"constructive/core-synthesis/theory-derived lanes "
                            f"(got {n_constructive}/{len(idea_lanes)}); "
                            "local repair cannot monopolize invention")
            synthesis_share = float(pol.get("research_min_core_synthesis_share", 0.0))
            if len(idea_lanes) >= 3 and synthesis_share > 0:
                n_synthesis = sum(1 for ln in idea_lanes
                                  if ln.get("search_origin") == "core_synthesis")
                if n_synthesis / len(idea_lanes) + 1e-9 < synthesis_share:
                    errs.append(f"PORTFOLIO_RESEARCH_CORE_SYNTHESIS: frontier research requires >= "
                                f"{synthesis_share:.0%} anonymous core-synthesis lanes when the round has "
                                f">=3 idea bets (got {n_synthesis}/{len(idea_lanes)}); retain blind "
                                "constructive search, but do not use literature only as a post-hoc veto")
    # user focus directions: bounded service. Focus lanes are capped at
    # focus_share_max of the round; a direction unserved for focus_neglect_rounds
    # closed rounds forces one lane (the human's interest is a bet the portfolio
    # must place occasionally - but never let it dominate the search).
    fds = {f["id"]: f for f in econfig.focus_directions(ctx.cfg)}
    # Focus is a duty on SEARCH BETS, so instrumental lanes neither dilute the
    # share denominator nor discharge a starved direction (every other
    # portfolio arithmetic already excludes them).
    for ln in lanes:
        if str(ln.get("focus") or "").strip() and \
                ln.get("experiment_purpose") in econfig.INSTRUMENTAL_PURPOSES:
            errs.append(f"PORTFOLIO_FOCUS_INSTRUMENTAL: lane '{ln.get('name')}' is "
                        f"{ln.get('experiment_purpose')}; instrumental work cannot carry a focus tag "
                        "or serve a starved focus direction")
    focus_lanes = [ln for ln in candidate_lanes_for_mix if str(ln.get("focus") or "").strip()]
    for ln in lanes:
        # id validity is checked for EVERY lane that carries a tag (an
        # exploratory scout may carry one - it just discharges nothing).
        if str(ln.get("focus") or "").strip() and ln.get("focus") not in fds \
                and ln.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES:
            errs.append(f"PORTFOLIO_FOCUS_UNKNOWN: lane '{ln.get('name')}' claims focus "
                        f"{ln.get('focus')!r}, not a configured focus direction id")
    negl = int(pol.get("focus_neglect_rounds", 0) or 0)
    starved: list[str] = []
    if fds and negl:
        closed = [r for r in ctx.st.get("rounds", []) if r.get("closed_at")]
        if len(closed) >= negl:
            recent_lane_ids = {lid for r in closed[-negl:] for lid in (r.get("lanes") or [])}
            # R7 audit: scouts discharge no starved direction (their results
            # cannot reach a record) - the HISTORICAL served set must apply
            # the same predicate the current-round arithmetic already does,
            # or repeated reconnaissance postpones the promised full-rigor
            # focus bet forever while every visible surface says it cannot.
            served = {l.get("focus") for l in ctx.st.get("lanes", [])
                      if l.get("id") in recent_lane_ids and l.get("focus")
                      and l.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES
                      and l.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES}
            starved = [fid for fid in fds if fid not in served]
    if fds and candidate_lanes_for_mix:
        # R9 audit + v11.4 reconciliation: the old ">=2 candidates" skip
        # silently waived the cap for single-candidate rounds; removing it
        # alone made the two focus rules unsatisfiable for any round smaller
        # than ceil(1/cap) whenever a direction starves - the neglect rule
        # FORCED a lane the cap then rejected, with no legal composition.
        # One EXPLICIT rule, both layers (config-time states the same): the
        # cap binds over the qualifying candidates, except that the single
        # lane a starved direction forces rides outside the numerator -
        # bounded service means the user's interest cannot dominate, and one
        # mandated catch-up bet in a small round is not domination.
        cap = float(pol.get("focus_share_max", 0.5))
        numerator = len(focus_lanes)
        if starved and any(ln.get("focus") in starved for ln in focus_lanes):
            numerator -= 1
        if numerator / len(candidate_lanes_for_mix) > cap + 1e-9:
            errs.append(f"PORTFOLIO_FOCUS_SHARE: {len(focus_lanes)}/{len(candidate_lanes_for_mix)} search-bet "
                        f"lanes serve user focus directions, above the cap {cap:.0%} - the user's interest "
                        "guides, it must not bind"
                        + (" (the one starvation-forced lane is already exempt)" if starved else ""))
    if starved and not any(ln.get("focus") in starved for ln in candidate_lanes_for_mix):
        errs.append(f"PORTFOLIO_FOCUS_NEGLECTED: focus direction(s) {starved} got no lane in the "
                    f"last {negl} closed rounds; this round must serve one (tag a lane with "
                    f"\"focus\": \"{starved[0]}\")")
    return errs


def _sketches(ctx: Ctx, task: dict, errs: list[str]) -> tuple[dict | None, list[dict]]:
    data = _read_json(ctx, task["outputs"][0], errs)
    if data is None:
        return None, []
    sk = data.get("sketches")
    if not isinstance(sk, list):
        errs.append("SKETCHES_SHAPE: SKETCHES.json must contain a 'sketches' array")
        return data, []
    return data, sk


DUPLICATE_TARGET_RE = re.compile(r"^DUPLICATE_OF:\s*((?:CA|N)\d{3,4})\s*$", re.M)
# [^\S\n] = whitespace except newline: a bare `TOMBSTONE:` label must NOT
# absorb the next physical line as its criterion (a \s* here walks across
# line breaks and silently banks the wrong text forever).
TOMBSTONE_LINE_RE = re.compile(r"^TOMBSTONE:[^\S\n]*(.+?)[^\S\n]*$", re.M)
TOMBSTONE_NOTE_RE = re.compile(r"^TOMBSTONE_NOTE:[^\S\n]*(.+?)[^\S\n]*$", re.M)
_TOMBSTONE_LEDGER_ID_RE = re.compile(r"\b(?:CA|TB|OB|[EMSN])\d{3,4}\b")
_TOMBSTONE_KNOWN_RE = re.compile(r"TB\d{3,4}$")
# Identity tells beyond bare links: venue names, citation shorthand, and
# MixedCase method/brand tokens (LoRA, AdamW) read as retrieval content.
_TOMBSTONE_VENUE_RE = re.compile(
    r"\b(?:NeurIPS|NIPS|ICML|ICLR|CVPR|ICCV|ECCV|ACL|EMNLP|NAACL|COLING|KDD|SIGIR|"
    r"RecSys|WSDM|AAAI|IJCAI|JMLR|TMLR|CoRR|arXiv)\b|\bet\s+al\b")
_TOMBSTONE_CAMEL_RE = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z]*)+\b")
# A criterion states what the work ABSORBS; enumerating what escapes it is a
# menu, and menus steer blind generators (the settled no-escape-list rule).
_TOMBSTONE_MENU_RE = re.compile(r"\b(?:except|unless|untested|unexplored|other than|but not)\b", re.I)


def _tombstone_identity_errors(ctx: Ctx, text: str, where: str) -> list[str]:
    """Anonymity checks shared by the criterion and the strategist-facing note."""
    errs: list[str] = []
    if PAPERISH.search(text):
        errs.append(f"TOMBSTONE_IDENTITY: {where}: contains paper links/DOIs - tombstones "
                    "are anonymous; provenance stays in the collision audit")
    m = _TOMBSTONE_LEDGER_ID_RE.search(text)
    if m:
        errs.append(f"TOMBSTONE_IDENTITY: {where}: {m.group(0)!r} reads as a ledger id "
                    "(E#/M#/S#/N#/OB#/CA#/TB#) - describe the mechanism shape itself; if this is "
                    "domain vocabulary, reword it so it cannot be mistaken for a reference")
    m = _TOMBSTONE_VENUE_RE.search(text)
    if m:
        errs.append(f"TOMBSTONE_IDENTITY: {where}: {m.group(0)!r} is citation language "
                    "(venue/et-al) - describe the shape, not the literature")
    m = _TOMBSTONE_CAMEL_RE.search(text)
    if m:
        errs.append(f"TOMBSTONE_IDENTITY: {where}: mixed-case name {m.group(0)!r} reads as a "
                    "method/brand identity - describe the mechanism generically")
    low = text.casefold()
    for row in ctx._evidence_rows():
        title = str((row or {}).get("title") or "").strip()
        if len(title) >= 12 and title.casefold() in low:
            errs.append(f"TOMBSTONE_IDENTITY: {where}: quotes an evidence title - "
                        "describe the shape, do not name the work")
            break
    return errs


def tombstone_criterion_errors(ctx: Ctx, criterion: str, where: str) -> list[str]:
    """v11.2: a tombstone's absorption criterion is a self-contained anonymous
    PREDICATE - it states which variations one published work absorbs, and
    nothing else. Never a direction, never a menu of untested escapes, never
    an identity: the strategist may quote it into a lane brief that a
    literature-blind generator reads, so any name/link/id in it would leak
    retrieval content through the side door."""
    errs: list[str] = []
    crit = str(criterion or "").strip()
    if "\n" in crit:
        errs.append(f"TOMBSTONE_CRITERION: {where}: the criterion must be ONE physical line "
                    "(no embedded line breaks)")
        crit = " ".join(crit.split())
    if len(crit) < 60:
        errs.append(f"TOMBSTONE_CRITERION: {where}: the absorption criterion needs >= 60 chars of "
                    "substance - state WHICH variations the collided work absorbs (e.g. 'any variant "
                    "differing only in the weight's functional form'), not a verdict word")
    if len(crit) > 400:
        errs.append(f"TOMBSTONE_CRITERION: {where}: over 400 chars stops being one predicate - "
                    "bound the NARROWEST class ONE published work absorbs, not an essay")
    m = _TOMBSTONE_MENU_RE.search(crit)
    if m:
        errs.append(f"TOMBSTONE_MENU: {where}: {m.group(0)!r} starts an escape list - the criterion "
                    "states what the work ABSORBS and asserts nothing beyond it; untested directions "
                    "belong in a TOMBSTONE_NOTE for the strategist, never in the criterion")
    errs.extend(_tombstone_identity_errors(ctx, crit, where))
    return errs


def _tombstone_ledger_ids(ctx: Ctx) -> set[str]:
    # lenient: one torn append must not brick review/tournament validation;
    # doctor reports the corrupt line, parseable rows keep working.
    return {str(r.get("id") or "") for r in eutil.read_jsonl(
        eutil.rpath(ctx.store.repo, ".evo/evidence/TOMBSTONES.jsonl"), lenient=True)
        if isinstance(r, dict)}


def _review_tombstone_errors(ctx: Ctx, review: str) -> list[str]:
    """The red-team side of the tombstone contract (research CA-target only).

    Exactly one criterion line; `TOMBSTONE: TB###` re-cites already-bounded
    territory instead of re-authoring; at most one anonymous note; and a
    wrapped continuation line is refused rather than silently truncated."""
    errs: list[str] = []
    tomb_lines = TOMBSTONE_LINE_RE.findall(review)
    if len(tomb_lines) != 1:
        errs.append("REVIEW_TOMBSTONE: REJECT_DUPLICATE against published work (CA target) "
                    "requires exactly one non-empty `TOMBSTONE: <absorption criterion>` line - state "
                    "what the collided work absorbs; beyond that criterion the tombstone asserts "
                    "nothing, and it must not enumerate untested directions")
    elif _TOMBSTONE_KNOWN_RE.fullmatch(tomb_lines[0]):
        if tomb_lines[0] not in _tombstone_ledger_ids(ctx):
            errs.append(f"REVIEW_TOMBSTONE_KNOWN: {tomb_lines[0]} is not an existing TB### id - "
                        "re-cite a tombstone from the bundle's list, or author a new criterion")
    else:
        errs.extend(tombstone_criterion_errors(ctx, tomb_lines[0], "review TOMBSTONE"))
    notes = TOMBSTONE_NOTE_RE.findall(review)
    if len(notes) > 1:
        errs.append("REVIEW_TOMBSTONE_NOTE: at most one TOMBSTONE_NOTE line - one death, one "
                    "strategist-facing pointer")
    for rt_note in notes:
        errs.extend(_tombstone_identity_errors(ctx, rt_note, "review TOMBSTONE_NOTE"))
    lines = review.splitlines()
    allowed_next = ("##", "VERDICT:", "DUPLICATE_OF:", "TOMBSTONE:", "TOMBSTONE_NOTE:", "QUOTE:")
    for i, ln in enumerate(lines):
        if ln.startswith(("TOMBSTONE:", "TOMBSTONE_NOTE:")) and i + 1 < len(lines):
            nxt = lines[i + 1].strip()
            if nxt and not nxt.startswith(allowed_next):
                errs.append("REVIEW_TOMBSTONE_WRAP: the line after a TOMBSTONE/TOMBSTONE_NOTE label "
                            "reads like a wrapped continuation - keep the whole criterion/note on ONE "
                            "physical line; a validator that captured only the first fragment would "
                            "bank a truncated boundary forever")
                break
    return errs


def _published_dup_errors(ctx: Ctx, audit: dict, cand: dict, *, where: str, lane_id: str,
                          program_set_digest: str, known_ids: set[str]) -> list[str]:
    """The tournament side of the tombstone contract (research mode only).

    A kill standing on published-work ground - the reason cites a CA###, or a
    screened paper's emulation row defeats the core - must either bank an
    absorption criterion, re-cite a known TB###, or state decisive=false with
    the actual kill ground (a collision may be mentioned without being what
    killed the candidate; forcing a false tombstone would corrupt the ledger
    that routes future briefs)."""
    errs: list[str] = []
    pdup = audit.get("published_dup")
    decision = audit.get("decision")
    reason = str(audit.get("reason") or "")
    prior = audit.get("prior_art") if isinstance(audit.get("prior_art"), dict) else {}
    screened = {str(r.get("paper") or "") for r in (prior.get("neighbors") or [])
                if isinstance(r, dict)}
    matrix = audit.get("emulation_matrix") if isinstance(audit.get("emulation_matrix"), list) else []
    paper_emulators = sorted({str(r.get("alternative") or "") for r in matrix
                              if isinstance(r, dict) and bool(r.get("can_emulate"))
                              and str(r.get("alternative") or "") in screened})
    if pdup is None:
        cited = re.search(r"\bCA\d{3,4}\b", reason)
        if decision == "kill" and (cited or paper_emulators):
            ground = (f"the reason cites collision audit {cited.group(0)}" if cited
                      else f"screened paper(s) {', '.join(paper_emulators)} can emulate the core")
            errs.append(f"TOURNAMENT_TOMBSTONE_MISSING: {where}: this kill stands on published-work "
                        f"ground ({ground}); add published_dup = {{\"ca\": \"CA###\", \"tombstone\": "
                        "\"<absorption criterion>\"} - or known_tombstone: \"TB###\" for territory an "
                        "existing tombstone bounds - or {\"ca\": ..., \"decisive\": false, \"ground\": "
                        "\"...\"} when the collision/emulation is NOT what actually killed it")
        return errs
    if decision != "kill":
        return [f"TOURNAMENT_TOMBSTONE_ADVANCE: {where}: published_dup belongs on kills only"]
    if not isinstance(pdup, dict) or (set(pdup) - {"ca", "tombstone", "known_tombstone",
                                                   "decisive", "ground"}):
        return [f"TOURNAMENT_TOMBSTONE_SHAPE: {where}: published_dup fields are 'ca' plus exactly one "
                "of 'tombstone'|'known_tombstone' - or 'ca' with 'decisive': false and a 'ground'"]
    caid = str(pdup.get("ca") or "")
    edge = ctx.collision_by_id().get(caid) or {}
    if not edge:
        errs.append(f"TOURNAMENT_TOMBSTONE_CA: {where}: published_dup.ca must resolve to "
                    "COLLISION_AUDITS.jsonl")
    else:
        expected = {
            "lane": lane_id,
            "program_set_digest": program_set_digest,
            "candidate_id": str(audit.get("sketch_id") or ""),
            "candidate_digest": eprogram.candidate_digest(cand),
        }
        mismatched = [key for key, value in expected.items() if value and edge.get(key) != value]
        if mismatched:
            errs.append(f"TOURNAMENT_TOMBSTONE_CA_BINDING: {where}: {caid} is not bound to this exact "
                        f"audited candidate on {mismatched} - a tombstone's provenance must trace to "
                        "the collision of the program it killed")
    decisive = pdup.get("decisive")
    if decisive is False:
        if "tombstone" in pdup or "known_tombstone" in pdup:
            errs.append(f"TOURNAMENT_TOMBSTONE_SHAPE: {where}: decisive=false waives the tombstone - "
                        "do not also bank or cite one")
        if len(" ".join(str(pdup.get("ground") or "").split())) < 60:
            errs.append(f"TOURNAMENT_TOMBSTONE_GROUND: {where}: decisive=false requires 'ground' "
                        "(>= 60 chars): what actually killed this candidate, if not the "
                        "published-work collision")
        return errs
    if decisive not in (None, True):
        errs.append(f"TOURNAMENT_TOMBSTONE_SHAPE: {where}: 'decisive' must be a boolean")
    if "ground" in pdup:
        errs.append(f"TOURNAMENT_TOMBSTONE_SHAPE: {where}: 'ground' belongs only with decisive=false")
    has_new = "tombstone" in pdup
    has_known = "known_tombstone" in pdup
    if has_new == has_known:
        errs.append(f"TOURNAMENT_TOMBSTONE_SHAPE: {where}: give exactly one of "
                    "'tombstone'|'known_tombstone'")
    elif has_new:
        errs.extend(tombstone_criterion_errors(
            ctx, str(pdup.get("tombstone") or ""), f"{where}.published_dup"))
    elif str(pdup.get("known_tombstone") or "") not in known_ids:
        errs.append(f"TOURNAMENT_TOMBSTONE_KNOWN: {where}: "
                    f"{str(pdup.get('known_tombstone'))!r} is not an existing TB### id")
    return errs


def _duplicate_evidence_errors(ctx: Ctx, review: str, *, lane_id: str,
                               program_set_digest: str, winner: str,
                               candidate_digest: str,
                               candidate_kernel_hash: str = "") -> list[str]:
    """Validate the one exact prior contract that licenses REJECT_DUPLICATE."""
    errs: list[str] = []
    matches = DUPLICATE_TARGET_RE.findall(review)
    if len(matches) != 1:
        return ["REVIEW_DUPLICATE_TARGET: REJECT_DUPLICATE requires one exact `DUPLICATE_OF: "
                "CA###|N###` line"]
    target = matches[0]
    prior = eutil.find_section(eutil.md_sections(review), "prior-art attack") or ""
    if target.startswith("N"):
        target_node = egraph.by_id(ctx.g).get(target)
        same_kernel = bool(candidate_kernel_hash) and target_node is not None \
            and str(target_node.get("kernel_hash") or "") == candidate_kernel_hash
        if not same_kernel and candidate_kernel_hash and target_node is not None \
                and target_node.get("idea_doc"):
            # R9 identity normalization bridge: the two STORED hashes may have
            # been written under different algorithm eras. Recompute the
            # target's fingerprint pair from its frozen idea meta and accept
            # the winner's stored hash if it matches either spelling.
            meta = eutil.read_json(eutil.rpath(
                ctx.store.repo, str(target_node["idea_doc"]).replace(".md", ".meta.json")), {}) or {}
            if meta.get("novelty"):
                same_kernel = candidate_kernel_hash in eprogram.kernel_fingerprints(meta)
        if target_node is None:
            errs.append(f"REVIEW_DUPLICATE_NODE: {target} does not resolve to an existing graph node")
        elif not same_kernel:
            errs.append(f"REVIEW_DUPLICATE_KERNEL: {target} does not carry the same exact frozen kernel as "
                        "the current winner")
        elif target not in prior:
            errs.append(f"REVIEW_DUPLICATE_EXPLANATION: Prior-art attack must explain exact graph target {target}")
        return errs
    if not ctx.is_research():
        return ["REVIEW_DUPLICATE_ENGINEERING: engineering mode may reject duplicate only against an "
                "existing N### in this graph; matching published work is legitimate borrowing"]
    edge = ctx.collision_by_id().get(target) or {}
    if not edge:
        return [f"REVIEW_DUPLICATE_COLLISION: {target} does not resolve to COLLISION_AUDITS.jsonl"]
    expected = {
        "lane": lane_id,
        "program_set_digest": program_set_digest,
        "candidate_id": winner,
        "candidate_digest": candidate_digest,
    }
    mismatched = [key for key, value in expected.items() if value and edge.get(key) != value]
    if mismatched:
        errs.append(f"REVIEW_DUPLICATE_BINDING: {target} is not bound to this exact winner on {mismatched}")
    mid = str(edge.get("mech_card_id") or "")
    paper = str((ctx.mech_by_id().get(mid) or {}).get("paper") or "")
    if not mid or not paper or mid not in prior or paper not in prior:
        errs.append(f"REVIEW_DUPLICATE_PRIOR_TRACE: Prior-art attack must cite the resolving {mid or 'M###'} "
                    f"and {paper or 'E###'} behind {target}")
    return errs


def _accepted_program_pairs(ctx: Ctx) -> list[tuple[str, str, str]]:
    """Program/tournament pairs named by engine state; orphan files have no authority."""
    out: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for lane in ctx.st.get("lanes", []):
        rows = [{
            "program_set": lane.get("sketches_path"),
            "program_set_digest": lane.get("program_set_digest"),
            "tournament": lane.get("tournament_path"),
        }] + [row for row in (lane.get("attempts") or []) if isinstance(row, dict)]
        for row in rows:
            key = (str(row.get("program_set") or ""), str(row.get("tournament") or ""),
                   str(row.get("program_set_digest") or ""))
            if not key[0] or not key[1] or key in seen:
                continue
            if not eutil.rpath(ctx.store.repo, key[0]).exists() \
                    or not eutil.rpath(ctx.store.repo, key[1]).exists():
                continue
            seen.add(key)
            out.append(key)
    return out


def historical_program_blocks(ctx: Ctx, *, ignore_idea: str | None = None) -> tuple[dict[str, str], dict[str, str]]:
    """Return exact rejected contracts and cores with an authoritative hard disposition."""
    contracts: dict[str, str] = {}
    kernels: dict[str, str] = {}

    for program_path, tournament_path, _digest in _accepted_program_pairs(ctx):
        pdata = eutil.read_json(eutil.rpath(ctx.store.repo, program_path), {}) or {}
        tournament = eutil.read_json(eutil.rpath(ctx.store.repo, tournament_path), {}) or {}
        candidates = {str(row.get("sketch_id") or ""): row for row in (pdata.get("sketches") or [])
                      if isinstance(row, dict)}
        for audit in tournament.get("audits") or []:
            if not isinstance(audit, dict) or audit.get("decision") != "kill":
                continue
            candidate = candidates.get(str(audit.get("sketch_id") or ""))
            if not candidate:
                continue
            contracts[eprogram.candidate_digest(candidate)] = tournament_path
            irreducibility = audit.get("irreducibility") or {}
            # v12: can_emulate no longer banks the kernel fingerprint. It is a
            # judgment about a NEIGHBOR's computation, structurally more
            # error-prone than the audit of the candidate's own body
            # (non_reducible/collage), and a wrong call here used to close the
            # whole kernel direction graph-wide and permanently. An emulation
            # kill still retires the candidate's exact contract (line above)
            # and still blocks that program's advance inside its own
            # tournament (TOURNAMENT_EMULATED_ADVANCE); the direction stays
            # retryable under a different contract. Because this map is
            # recomputed from the audit files on every validation, the change
            # applies retroactively to historical emulation-only kills.
            if ctx.is_research() and (irreducibility.get("non_reducible") is False
                                      or irreducibility.get("collage") is True):
                kernels[eprogram.kernel_fingerprint(candidate)] = tournament_path

    for lane in ctx.st.get("lanes", []):
        records = ([row for row in (lane.get("idea_revisions") or []) if isinstance(row, dict)] +
                   [row for row in (lane.get("attempts") or []) if isinstance(row, dict)])
        for row in records:
            verdict = str(row.get("verdict") or "")
            if not verdict.startswith("REJECT_"):
                continue
            idea = str(row.get("idea") or "")
            meta = (eutil.read_json(eutil.rpath(ctx.store.repo, f".evo/ideas/{idea}.meta.json"), {}) or {}
                    if idea else {})
            program_digest = str(row.get("winner_program_digest") or meta.get("program_digest") or "")
            kernel_hash = str(row.get("winner_kernel_hash") or meta.get("kernel_hash") or "")
            source = str(row.get("review") or idea or lane.get("id") or "historical review")
            if program_digest:
                contracts[program_digest] = source
            review_path = str(row.get("review") or "")
            review = (eutil.read_text(eutil.rpath(ctx.store.repo, review_path))
                      if review_path and eutil.rpath(ctx.store.repo, review_path).exists() else "")
            hard = False
            if verdict == "REJECT_DUPLICATE" and review:
                duplicate_errors = _duplicate_evidence_errors(
                    ctx, review, lane_id=str(lane.get("id") or ""),
                    program_set_digest=str(row.get("program_set_digest") or ""),
                    winner=str(row.get("winner") or meta.get("sketch_id") or ""),
                    candidate_digest=program_digest,
                    candidate_kernel_hash=kernel_hash)
                targets = DUPLICATE_TARGET_RE.findall(review)
                # A graph node with the identical engine fingerprint is a hard
                # core disposition.  A CA# is a candidate-bound literature
                # comparison, not a formal equivalence certificate; it may
                # retire this exact contract but must not blacklist every
                # future use of the kernel.
                hard = not duplicate_errors and len(targets) == 1 and targets[0].startswith("N")
            elif verdict == "REJECT_SHALLOW" and review:
                hard = any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(kid)}(?![A-Za-z0-9_])", review)
                           for kid in eprogram.kernel_ids(meta))
            if hard and kernel_hash:
                kernels[kernel_hash] = source
                # R10-005: where the rejected idea's program survives, its
                # identity is registered under EVERY generation's spelling -
                # a stored legacy hash cannot recognize a consistently
                # renumbered copy on its own (the same recompute bridge
                # _duplicate_evidence_errors has always used).
                if isinstance(meta.get("program"), dict):
                    for spelling in eprogram.kernel_fingerprints(meta):
                        if spelling:
                            kernels.setdefault(spelling, source)

    for node in ctx.g.get("nodes", []):
        if not isinstance(node, dict) or not node.get("kernel_hash"):
            continue
        kernels[str(node["kernel_hash"])] = f"graph node {node.get('id')}"
        if node.get("idea_doc"):
            node_meta = eutil.read_json(eutil.rpath(
                ctx.store.repo, str(node["idea_doc"]).replace(".md", ".meta.json")), {}) or {}
            if isinstance(node_meta.get("program"), dict):
                for spelling in eprogram.kernel_fingerprints(node_meta):
                    if spelling:
                        kernels.setdefault(spelling, f"graph node {node.get('id')}")
    for lane in ctx.st.get("lanes", []):
        if lane.get("status") not in ("red_team", "gate", "approved", "node_created") \
                or not lane.get("idea") or lane.get("idea") == ignore_idea:
            continue
        meta = eutil.read_json(
            eutil.rpath(ctx.store.repo, f".evo/ideas/{lane['idea']}.meta.json"), {}) or {}
        if meta.get("kernel_hash"):
            kernels[str(meta["kernel_hash"])] = f"active idea {lane.get('idea')}"
            if isinstance(meta.get("program"), dict):
                for spelling in eprogram.kernel_fingerprints(meta):
                    if spelling:
                        kernels.setdefault(spelling, f"active idea {lane.get('idea')}")
    return contracts, kernels


def v_sketch(ctx: Ctx, task: dict) -> list[str]:
    """Schema-v2 complete scientific-program synthesis validator.

    Repair retains the frozen H# contract. Blind constructive and
    theory-derived candidates are free of paper templates at generation time.
    The separate core_synthesis route sees only an anonymous projection of
    papers' actual program transformations, never their titles or motivation.
    Every route still receives candidate-specific collision analysis only
    after this file is frozen.
    """
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    data, candidates = _sketches(ctx, task, errs)
    if data is None or lane is None:
        return errs or ["INTERNAL: lane missing"]
    origin = str(lane.get("search_origin") or "")
    if origin == "core_synthesis":
        errs.extend(core_palette_contract_errors(ctx, lane))
    allowed_set_fields = {"schema_version", "lane", "search_origin", "baseline_program_digest",
                          "sketches", "diagnosis_digest", "theory_digest", "core_palette_digest"}
    extra_set_fields = sorted(set(data) - allowed_set_fields)
    if extra_set_fields:
        errs.append(f"PROGRAM_SET_FIELDS: unknown top-level fields {extra_set_fields}")
    if data.get("schema_version") != 2:
        errs.append("PROGRAM_SET_VERSION: schema_version must be 2")
    if data.get("lane") != lane.get("id"):
        errs.append(f"PROGRAM_SET_LANE: lane must be {lane.get('id')!r}")
    if data.get("search_origin") != origin:
        errs.append(f"PROGRAM_SET_ORIGIN: search_origin must be frozen as {origin!r}")
    baseline_digest = json_file_digest(ctx, ".evo/profile/BASELINE_PROGRAM.json")
    if data.get("baseline_program_digest") != baseline_digest:
        errs.append("PROGRAM_BASELINE_DIGEST: bind the code-grounded BASELINE_PROGRAM digest")

    want = econfig.budget(ctx.cfg, "sketches_per_lane")
    if lane.get("scaling_followup_of") or lane.get("confirmatory_of"):
        # v11.1 (R1/R2 fix): a carbon-copy lane re-runs ONE frozen kernel - a
        # batch of alternatives is impossible by construction (every extra
        # candidate would be the same core, which the within-batch duplicate
        # rules rightly reject). Exactly one, for BOTH copy species.
        if len(candidates) != 1:
            what = ("a scaling follow-up (the parent's kernel at the registered scale points)"
                    if lane.get("scaling_followup_of") else
                    "a confirmatory re-run (the scout's kernel under full rigor)")
            errs.append(f"PROGRAM_CARBON_COPY_COUNT: lane {lane['id']} is {what} - submit "
                        f"exactly 1 program, got {len(candidates)}")
    elif len(candidates) < want:
        errs.append(f"PROGRAM_COUNT: lane {lane['id']} needs >= {want} complete programs, got {len(candidates)}")

    hids: set[str] = set()
    if origin == "repair":
        diagnosis = eutil.read_json(eutil.rpath(ctx.store.repo, lane.get("diagnosis_path") or ""), {}) or {}
        hids = {str(h.get("id")) for h in (diagnosis.get("hypotheses") or []) if isinstance(h, dict)}
        if data.get("diagnosis_digest") != lane.get("diagnosis_digest"):
            errs.append("PROGRAM_DIAGNOSIS_DIGEST: repair program set must bind the frozen diagnosis")
        if json_file_digest(ctx, lane.get("diagnosis_path") or "") != lane.get("diagnosis_digest"):
            errs.append("DIAGNOSIS_MUTATED: frozen repair diagnosis changed after method exposure")
    else:
        leaked = [f for f in ("diagnosis_digest", "hypothesis_ids", "move") if f in data]
        if leaked:
            errs.append(f"PROGRAM_ROUTE_LEAK: non-repair program set carries repair fields {leaked}")
    if origin == "theory_derived":
        expected = text_file_digest(ctx, str(lane.get("theory_path") or ""))
        if data.get("theory_digest") != expected:
            errs.append("PROGRAM_THEORY_DIGEST: bind the surviving theory digest")
    if origin == "core_synthesis":
        palette_path = str(lane.get("core_palette_path") or "")
        if not palette_path or not _exists(ctx, palette_path):
            errs.append("PROGRAM_CORE_PALETTE_MISSING: core_synthesis requires the engine-frozen anonymous palette")
        elif data.get("core_palette_digest") != lane.get("core_palette_digest") or \
                json_file_digest(ctx, palette_path) != lane.get("core_palette_digest"):
            errs.append("PROGRAM_CORE_PALETTE_DIGEST: bind the unchanged engine-frozen anonymous palette")
    theory_text = ""
    theory_dos: set[str] = set()
    if origin == "theory_derived":
        theory_text = eutil.read_text(eutil.rpath(ctx.store.repo, str(lane.get("theory_path") or "")))
        theory_dos = {did for did, _ in DO_LINE.findall(theory_text)}

    target_cells = set(econfig.cell_spec(ctx.cfg))
    cell_map = econfig.cell_spec(ctx.cfg)
    global_targets = {str(c.get("id")) for c in econfig.target_cells(ctx.cfg)}
    mech = ctx.mech_by_id()
    palette_ids: set[str] = set()
    if origin == "core_synthesis" and lane.get("core_palette_path"):
        palette = eutil.read_json(eutil.rpath(ctx.store.repo, lane["core_palette_path"]), {}) or {}
        palette_ids = {str(row.get("id") or "") for row in (palette.get("cores") or [])
                       if isinstance(row, dict)}
    ids: set[str] = set()
    model_parents = [p for p in lane.get("parents", []) if _is_model_parent(ctx, p)]
    is_platform = lane.get("intent") == "platform"
    for cand in candidates:
        cand = cand if isinstance(cand, dict) else {}
        sid = str(cand.get("sketch_id") or "")
        if not re.fullmatch(r"K\d+", sid) or sid in ids:
            errs.append(f"PROGRAM_ID: sketch_id must be a unique K# (got {sid!r})")
        ids.add(sid)
        errs.extend(eprogram.candidate_errors(
            cand, where=sid or "candidate", min_level=lane_min_level(lane),
            research=ctx.is_research(), search_origin=origin,
            model_parent_count=len(model_parents), platform=is_platform,
            scaling_followup=bool(lane.get("scaling_followup_of")),
            extra_axes=tuple(econfig.extension_resource_axes(ctx.cfg))))
        if origin == "theory_derived":
            if cand.get("theory_rigor") != lane.get("formal_kind"):
                errs.append(f"PROGRAM_THEORY_RIGOR_BINDING: {sid}: theory_rigor must equal the portfolio/theory "
                            f"precommitment {lane.get('formal_kind')!r}")
            mapped_dos = {str(row.get("id") or "") for row in (cand.get("theory_obligations") or [])
                          if isinstance(row, dict)}
            if mapped_dos != theory_dos:
                errs.append(f"PROGRAM_THEORY_OBLIGATION_COVERAGE: {sid}: mapped DO# ids {sorted(mapped_dos)} "
                            f"must exactly cover surviving theory obligations {sorted(theory_dos)}")
        if origin == "core_synthesis":
            core_ids = cand.get("synthesis_core_ids")
            if not isinstance(core_ids, list) or len(core_ids) < 2 or \
                    len(set(str(x) for x in (core_ids or []))) != len(core_ids) or \
                    any(str(x) not in palette_ids for x in (core_ids or [])):
                errs.append(f"PROGRAM_CORE_SYNTHESIS_IDS: {sid}: synthesis_core_ids needs >=2 unique "
                            "CP# ids resolving to the frozen anonymous palette")
                core_ids = []
            relation = cand.get("synthesis_relation")
            if not isinstance(relation, dict) or set(relation) != {
                    "operation", "discarded_shells", "non_decomposability"}:
                errs.append(f"PROGRAM_CORE_SYNTHESIS_RELATION: {sid}: synthesis_relation must use exactly "
                            "operation, discarded_shells, non_decomposability")
            else:
                _nontrivial(relation.get("operation"), 100,
                            f"{sid}.synthesis_relation.operation (the NEW relation formed by transforming cores)", errs)
                shells = relation.get("discarded_shells")
                if not isinstance(shells, list) or len(shells) != len(core_ids) or \
                        any(len(str(x).strip()) < 35 for x in (shells or [])):
                    errs.append(f"PROGRAM_CORE_SYNTHESIS_SHELLS: {sid}: discarded_shells must give one "
                                ">=35-char discarded implementation shell per source core")
                _nontrivial(relation.get("non_decomposability"), 100,
                            f"{sid}.synthesis_relation.non_decomposability (why independent modules cannot emulate it)", errs)
                if re.search(r"\b(?:M\d{3,4}|E\d{3,4})\b|https?://|arxiv", json.dumps(relation), re.I):
                    errs.append(f"PROGRAM_CORE_SYNTHESIS_PROVENANCE_LEAK: {sid}: synthesize anonymous work "
                                "semantics; paper/card ids and links belong to the later collision audit")
        elif "synthesis_core_ids" in cand or "synthesis_relation" in cand:
            errs.append(f"PROGRAM_CORE_SYNTHESIS_ROUTE: {sid}: synthesis fields are legal only on core_synthesis")
        declared_parents = ((cand.get("program") or {}).get("scientific_parents") or [])
        if list(declared_parents) != model_parents:
            errs.append(f"PROGRAM_SCIENTIFIC_PARENTS: {sid}: program.scientific_parents must exactly equal {model_parents}")
        cells = [str(link.get("target_cell") or "")
                 for link in ((cand.get("effect_case") or {}).get("chain") or [])
                 if isinstance(link, dict)]
        if not is_platform:
            unknown_cells = [c for c in cells if c not in target_cells]
            if unknown_cells:
                errs.append(f"PROGRAM_EFFECT_CELL_UNKNOWN: {sid}: unknown C# ids {unknown_cells}")
            effect = cand.get("effect_case") or {}
            comparator = str(effect.get("comparator_id") or "")
            # The declared effect comparator is causal context, not a
            # post-hoc leaderboard choice: it must be the baseline or one of
            # the exact scientific parents frozen for this lane.
            allowed_comparators = {"baseline"} | set(model_parents)
            if comparator not in allowed_comparators:
                errs.append(f"PROGRAM_EFFECT_COMPARATOR_UNKNOWN: {sid}: causal/resource comparator_id must be "
                            f"baseline or one of the lane's scientific parents {model_parents}; stronger "
                            "off-lineage/frontier nodes are separate promotion evidence, not legal comparators")
            claim = cand.get("claim_scope") or {}
            claim_targets = [str(x) for x in (claim.get("target_cells") or [])]
            if set(claim_targets) != set(cells):
                errs.append(f"PROGRAM_EFFECT_SCOPE_BINDING: {sid}: effect-chain target cells must exactly equal frozen claim_scope targets")
            if any(cid not in global_targets for cid in claim_targets):
                errs.append(f"PROGRAM_CLAIM_TARGET_UNKNOWN: {sid}: claim_scope targets must be project target cells")
            if claim.get("kind") == "generalist" and set(claim_targets) != global_targets:
                errs.append(f"PROGRAM_CLAIM_GENERALIST: {sid}: generalist must freeze every project target cell")
            if claim.get("kind") == "specialist" and set(claim_targets) == global_targets:
                errs.append(f"PROGRAM_CLAIM_SPECIALIST: {sid}: specialist must be a strict target subset")
            # R3 logic audit (fail-early): v_mature enforces these two config-
            # structure conditions AND exact-copy drift from the frozen winner.
            # A winner frozen in violation could therefore never mature - the
            # lane's only exit was death after tournament spend. The wall must
            # stand HERE, where the claim is still editable (precedent: the
            # efficiency partition is already sketch-checked for this reason).
            if claim.get("kind") == "specialist" and not (
                    (ctx.cfg.get("evaluation_contract", {}).get("decision") or {}).get(
                        "allow_specialist", True)):
                errs.append(f"PROGRAM_CLAIM_SPECIALIST_DISABLED: {sid}: the user did not allow "
                            "specialist success in this project - claim every target cell "
                            "(generalist) or reshape the idea")
            required_missing = sorted(
                cid for cid in global_targets
                if (cell_map.get(cid) or {}).get("required") and cid not in set(claim_targets))
            if required_missing:
                errs.append(f"PROGRAM_CLAIM_REQUIRED_TARGETS: {sid}: required target cells "
                            f"{required_missing} cannot be scoped away - a claim frozen without "
                            "them can never pass maturation")
            guards = [str(x) for x in (claim.get("guardrail_cells") or [])]
            if any(cid not in cell_map or (cell_map.get(cid) or {}).get("role") != "guardrail" for cid in guards):
                errs.append(f"PROGRAM_CLAIM_GUARD_UNKNOWN: {sid}: guardrail_cells must resolve to project guardrails")
            for link in (effect.get("chain") or []):
                cid = str((link or {}).get("target_cell") or "")
                result_key = str((cell_map.get(cid) or {}).get("result_key") or "")
                expected = "increase" if result_key and econfig.result_direction(ctx.cfg, result_key) == "max" else "decrease"
                if result_key and (link or {}).get("direction") not in (expected, "stabilize"):
                    errs.append(f"PROGRAM_EFFECT_DIRECTION_CONTRACT: {sid}/{cid}: direction must follow the configured metric ({expected}) or stabilize")
                if (link or {}).get("direction") == "stabilize" and not (
                        claim.get("kind") == "efficiency"
                        and cid in {str(x) for x in (claim.get("parity_cells") or [])}):
                    errs.append(f"PROGRAM_EFFECT_STABILIZE_SCOPE: {sid}/{cid}: stabilize is an equivalence "
                                "claim allowed only for an efficiency claim's frozen parity_cells; ordinary "
                                "generalist/specialist targets must improve in the configured direction")
            directions_by_cell: dict[str, set[str]] = {}
            for link in (effect.get("chain") or []):
                if isinstance(link, dict):
                    directions_by_cell.setdefault(str(link.get("target_cell") or ""), set()).add(
                        str(link.get("direction") or ""))
            for cid, directions in sorted(directions_by_cell.items()):
                if len(directions) > 1:
                    errs.append(f"PROGRAM_EFFECT_DIRECTION_MIXED: {sid}/{cid}: every causal link for one "
                                f"target cell must use one settleable direction, got {sorted(directions)}")
        if origin == "repair":
            if cand.get("diagnosis_digest") != lane.get("diagnosis_digest"):
                errs.append(f"PROGRAM_DIAGNOSIS_BINDING: {sid}: digest differs from frozen repair diagnosis")
            hs = cand.get("hypothesis_ids")
            if not isinstance(hs, list) or not hs \
                    or any(not isinstance(h, str) or h not in hids for h in hs):
                errs.append(f"PROGRAM_HYPOTHESIS_BINDING: {sid}: hypothesis_ids must resolve to frozen H# ids")
            mc = cand.get("mech_card_ids") or []
            if not mc or any(not isinstance(m, str) or m not in mech for m in mc):
                errs.append(f"PROGRAM_REPAIR_EVIDENCE: {sid}: repair programs need resolving core-work cards")
        else:
            for field in ("diagnosis_digest", "hypothesis_ids"):
                if field in cand:
                    errs.append(f"PROGRAM_ROUTE_FIELD: {sid}: {field} is repair-only")
            queries = cand.get("collision_queries")
            if not isinstance(queries, list) or len([q for q in queries if len(str(q).strip()) >= 30]) < 2:
                errs.append(f"PROGRAM_COLLISION_QUERIES: {sid}: need >=2 prior-art queries (>=30 chars) "
                            "for the post-freeze reader")
        if lane.get("intent") == "hybrid":
            kinds = {str(k.get("kind") or "") for k in eprogram.kernel_components(cand)}
            if not kinds.intersection({"coupling", "system_relation"}):
                errs.append(f"PROGRAM_HYBRID_KERNEL: {sid}: hybrid needs a coupling/system_relation kernel")

    if not lane.get("scaling_followup_of") and not lane.get("confirmatory_of"):
        # A carbon-copy batch is one mandated copy of one frozen core;
        # diversity rules are meaningless (and unsatisfiable) there.
        errs.extend(eprogram.diversity_errors(candidates))
    rejected_contracts, rejected_kernels = historical_program_blocks(ctx)
    scaling_parent_kernels, scaling_parent_kind = _kernel_carbon_copy_target(
        ctx, lane.get("scaling_followup_of"))
    confirm_kernels, _ck = _kernel_carbon_copy_target(ctx, lane.get("confirmatory_of"))
    for cand in candidates:
        digest = eprogram.candidate_digest(cand)
        # R9 identity normalization: every stored hash may be either spelling
        # (normalized or legacy); membership and equality checks consult both
        # so no stored disposition goes blind - and no mandated copy wedges -
        # across the algorithm change.
        fp_pair = eprogram.kernel_fingerprints(cand)
        hit_source = next((rejected_kernels[f] for f in fp_pair if f in rejected_kernels), None)
        if digest in rejected_contracts:
            errs.append(f"PROGRAM_REJECTED_CONTRACT_REPEAT: {cand.get('sketch_id')} exactly repeats a "
                        f"previously rejected executable/effect/resource contract from "
                        f"{rejected_contracts[digest]}")
        elif hit_source is not None and not (confirm_kernels and set(confirm_kernels) & set(fp_pair)) \
                and not lane.get("scaling_followup_of"):
            # v11.1 (R1 fix): the confirmatory door - reproducing a declared
            # exploratory scout's kernel under full rigor is the one legal way
            # a graph-node kernel may be run again.
            # v11.1 (final audit C24): a scaling follow-up lane is FULLY exempt
            # from the core-repeat block - its kernel legality is owned by the
            # affirmative carbon-copy check below (must equal the parent's,
            # verbatim), so nothing else can ride this exemption; without it,
            # one hard rejection of the mandated copy poisoned the fingerprint
            # and wedged the lane permanently (demanded X, forbade X).
            errs.append(f"PROGRAM_REJECTED_CORE_REPEAT: {cand.get('sketch_id')} repeats a frozen core "
                        f"with an explicit mechanistic/duplicate disposition from {hit_source}")
        if scaling_parent_kernels:
            # R9: the normalized identity no longer embeds novelty.kind, so a
            # new-era parent hash matches the verbatim copy directly. A parent
            # stored under the LEGACY algorithm still needs the historical
            # kind-substitution arm (its hash embeds the parent's kind).
            # R10-005: every acceptable parent spelling participates - the
            # recomputed generations bridge renumbered copies of legacy rows.
            nov = cand.get("novelty") or {}
            legacy_neutral = (eprogram.legacy_kernel_fingerprint(
                {**cand, "novelty": {**nov, "kind": scaling_parent_kind}})
                if scaling_parent_kind else "")
            copy_ok = any(eprogram.kernel_identity_matches(k, cand)
                          for k in scaling_parent_kernels) \
                or (bool(legacy_neutral) and legacy_neutral in scaling_parent_kernels)
            if not copy_ok and not scaling_parent_kind:
                # R2 fix: with the parent's kind unknown the legacy arm is
                # unsatisfiable - say so instead of gaslighting the agent
                # with "this core differs".
                errs.append(f"PROGRAM_SCALING_FOLLOWUP_PARENT_META: {cand.get('sketch_id')}: parent "
                            f"{lane.get('scaling_followup_of')}'s idea meta (novelty.kind) is unreadable; "
                            "the carbon-copy check cannot run - restore the parent's .meta.json first")
                continue
            if not copy_ok:
                errs.append(f"PROGRAM_SCALING_FOLLOWUP_KERNEL: {cand.get('sketch_id')}: a scaling follow-up "
                            f"lane must re-run its parent's frozen kernel VERBATIM (statements, components, "
                            f"operator structure, bearer); this core differs from parent "
                            f"{lane.get('scaling_followup_of')}'s")
            comparator = str(((cand.get("effect_case") or {}).get("comparator_id")) or "")
            if comparator != str(lane.get("scaling_followup_of")):
                errs.append(f"PROGRAM_SCALING_FOLLOWUP_COMPARATOR: {cand.get('sketch_id')}: the follow-up's "
                            f"effect comparator must be the parent {lane.get('scaling_followup_of')} itself "
                            f"(the same kernel at the base scale), got {comparator!r}")
        if lane.get("confirmatory_of") and not confirm_kernels:
            # (final audit L17) mirror of the scaling PARENT_META guard: an
            # unreadable scout kernel must fail loudly, not skip silently.
            errs.append(f"PROGRAM_CONFIRMATORY_TARGET_META: {cand.get('sketch_id')}: scout "
                        f"{lane.get('confirmatory_of')}'s kernel_hash is unreadable; the carbon-copy "
                        "check cannot run - restore the scout node's record first")
        elif confirm_kernels and not any(eprogram.kernel_identity_matches(k, cand)
                                         for k in confirm_kernels):
            # v11.1 (R2 fix): the confirmatory promise is enforced, not
            # honor-system - the one program must BE the scout's kernel.
            errs.append(f"PROGRAM_CONFIRMATORY_KERNEL: {cand.get('sketch_id')}: a confirmatory lane must "
                        f"re-run scout {lane.get('confirmatory_of')}'s frozen kernel VERBATIM (statements, "
                        "components, operator structure, bearer); this core differs")
    return errs


def _kernel_carbon_copy_target(ctx: Ctx, nid: Any) -> tuple[tuple[str, ...], str]:
    """(acceptable kernel spellings, novelty.kind) of the node a lane declares
    it will re-run (scaling_followup_of / confirmatory_of), or ((), "").

    R10-005: the stored hash alone cannot recognize a consistently renumbered
    copy when it was written by an older identity algorithm (the legacy
    spelling embeds local OP# labels). Where the target's idea program still
    exists, its identity is RECOMPUTED under every generation and each
    spelling is acceptable - same bridge _duplicate_evidence_errors has
    always used."""
    if not nid:
        return (), ""
    node = egraph.by_id(ctx.g).get(str(nid)) or {}
    spellings: list[str] = []
    stored = str(node.get("kernel_hash") or "")
    if stored:
        spellings.append(stored)
    kind = ""
    if node.get("idea_doc"):
        meta = eutil.read_json(eutil.rpath(ctx.store.repo,
                                           str(node["idea_doc"]).replace(".md", ".meta.json")), {}) or {}
        kind = str(((meta.get("novelty") or {}).get("kind")) or "")
        if isinstance(meta.get("program"), dict):
            spellings.extend(s for s in eprogram.kernel_fingerprints(meta) if s)
    seen: list[str] = []
    for s in spellings:
        if s not in seen:
            seen.append(s)
    return tuple(seen), kind


def _is_model_parent(ctx: Ctx, pid: str) -> bool:
    n = egraph.by_id(ctx.g).get(pid)
    return bool(n) and n.get("role") != "platform"


def _effect_comparator_node(ctx: Ctx, candidate: dict, owner: dict | None = None) -> dict | None:
    # Once a node exists, use the concrete identity frozen at node creation.
    # Pre-node tournament validation still resolves the public ``baseline``
    # alias against the single baseline node.
    frozen = str((owner or {}).get("effect_comparator_node") or "")
    if frozen:
        node = egraph.by_id(ctx.g).get(frozen)
        return node if node and node.get("role") != "platform" else None
    comparator_id = str(((candidate.get("effect_case") or {}).get("comparator_id") or ""))
    if comparator_id == "baseline":
        return next((node for node in ctx.g.get("nodes", [])
                     if isinstance(node, dict) and node.get("role") == "baseline"), None)
    node = egraph.by_id(ctx.g).get(comparator_id)
    return node if node and node.get("role") != "platform" else None


def _interval_contains(value: object, lower: object, upper: object) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and not isinstance(lower, bool) and isinstance(lower, (int, float))
            and not isinstance(upper, bool) and isinstance(upper, (int, float))
            and float(lower) <= float(value) <= float(upper))


def _planned_comparator_resource_errors(ctx: Ctx, candidate: dict, *, where: str) -> list[str]:
    """Bind pre-execution comparator estimates to its already sealed receipt."""
    comparator = _effect_comparator_node(ctx, candidate)
    if comparator is None:
        return []  # comparator topology has its own validation error
    planned = ((((candidate.get("effect_case") or {}).get("resources") or {}).get("comparator")) or {})
    realized = comparator.get("effect_resources_realized") or {}
    errs: list[str] = []
    for axis in econfig.resource_axes(ctx.cfg):
        value = planned.get(axis) if isinstance(planned, dict) else None
        if value == "unknown":
            continue
        raw_row = realized.get(axis) if isinstance(realized, dict) else None
        row = raw_row if isinstance(raw_row, dict) else {}
        if not _interval_contains(value, row.get("lower"), row.get("upper")):
            errs.append(f"TOURNAMENT_COMPARATOR_RESOURCE_BINDING: {where}: planned comparator.{axis}="
                        f"{value!r} must lie inside sealed {comparator.get('id')} receipt interval "
                        f"[{row.get('lower')!r}, {row.get('upper')!r}]")
    return errs


def v_tournament(ctx: Ctx, task: dict) -> list[str]:
    """Independent M/E/T audit of frozen scientific programs."""
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    tj = _read_json(ctx, task["outputs"][0], errs)
    if tj is None or lane is None:
        return errs
    is_platform = lane.get("intent") == "platform"
    if json_file_digest(ctx, str(lane.get("sketches_path") or "")) != lane.get("program_set_digest"):
        errs.append("PROGRAM_SET_MUTATED: frozen programs changed after post-construction literature exposure")
    sdata = eutil.read_json(eutil.rpath(ctx.store.repo, str(lane.get("sketches_path") or "")), {}) or {}
    programs = {str(s.get("sketch_id")): s for s in (sdata.get("sketches") or []) if isinstance(s, dict)}
    audits = tj.get("audits")
    if not isinstance(audits, list):
        return errs + ["TOURNAMENT_SHAPE: TOURNAMENT.json needs an audits array"]
    if tj.get("program_set_digest") != lane.get("program_set_digest"):
        errs.append("TOURNAMENT_PROGRAM_SET_DIGEST: bind the immutable program-set digest")
    errs.extend(critic_isolation_errors(
        ctx, task,
        release=any(isinstance(a, dict) and a.get("decision") == "advance" for a in audits),
        author_types=("sketch",)))
    ev = ctx.evidence_ids()
    mech = ctx.mech_by_id()
    collision = ctx.collision_by_id()
    sota_by_id = {str(row.get("id") or ""): row for row in ctx.sota_rows()}
    research_mode = ctx.is_research()
    tomb_known_ids = _tombstone_ledger_ids(ctx)
    audited: set[str] = set()
    advanced: set[str] = set()
    emulators_by_program: dict[str, set[str]] = {}
    for audit in audits:
        audit = audit if isinstance(audit, dict) else {}
        sid = str(audit.get("sketch_id") or "")
        where = f"audit({sid})"
        if sid in audited:
            errs.append(f"TOURNAMENT_AUDIT_DUP: {where}: each frozen K# must have exactly one audit row")
            continue
        audited.add(sid)
        cand = programs.get(sid)
        if cand is None:
            errs.append(f"TOURNAMENT_UNKNOWN_PROGRAM: {where}: no such K#")
            continue
        if audit.get("program_digest") != eprogram.candidate_digest(cand):
            errs.append(f"TOURNAMENT_PROGRAM_DIGEST: {where}: digest does not bind the audited program")
        decision = audit.get("decision")
        if decision not in ("advance", "kill"):
            errs.append(f"TOURNAMENT_DECISION: {where}: decision must be advance|kill")
        elif decision == "advance":
            advanced.add(sid)
        _nontrivial(audit.get("reason"), 60, f"{where}.reason", errs)
        # v11.2: a kill grounded in published work must bank the boundary
        # (research mode; engineering-mode borrowing has no boundary to bank).
        if research_mode:
            errs.extend(_published_dup_errors(
                ctx, audit, cand, where=where, lane_id=str(lane.get("id") or ""),
                program_set_digest=str(lane.get("program_set_digest") or ""),
                known_ids=tomb_known_ids))
        elif audit.get("published_dup") is not None:
            errs.append(f"TOURNAMENT_TOMBSTONE_RESEARCH: {where}: published_dup is a research-mode "
                        "contract; engineering-mode overlap with published work is legitimate "
                        "borrowing, not a novelty boundary")
        source = json.dumps(cand, ensure_ascii=False, sort_keys=True)
        _check_quotes([str(audit.get("quote") or "")], source, where, errs, 1)

        prior = audit.get("prior_art") or {}
        neighbors = prior.get("neighbors")
        if not isinstance(neighbors, list) or len(neighbors) < 2:
            errs.append(f"TOURNAMENT_PRIOR_SET: {where}: prior_art.neighbors needs >=2 program-level nearest neighbors")
            neighbors = []
        neighbor_papers: set[str] = set()
        axes: set[str] = set()
        for j, row in enumerate(neighbors):
            row = row if isinstance(row, dict) else {}
            paper = str(row.get("paper") or "")
            if paper not in ev:
                errs.append(f"TOURNAMENT_PRIOR_ART: {where}.neighbors[{j}].paper must resolve to E###")
            neighbor_papers.add(paper)
            axis = str(row.get("axis") or "")
            if axis not in ("mechanism", "task_effect"):
                errs.append(f"TOURNAMENT_PRIOR_AXIS: {where}.neighbors[{j}].axis must be mechanism|task_effect")
            axes.add(axis)
            _nontrivial(row.get("program_overlap"), 60, f"{where}.neighbors[{j}].program_overlap", errs)
            _nontrivial(row.get("irreducible_difference"), 80,
                        f"{where}.neighbors[{j}].irreducible_difference", errs)
            cards = row.get("core_work_cards") or []
            if not isinstance(cards, list) or not cards \
                    or any(not isinstance(c, str) or c not in mech for c in cards):
                errs.append(f"TOURNAMENT_CORE_WORK: {where}.neighbors[{j}] needs resolving M### audits")
                cards = []
            elif any((mech.get(c) or {}).get("paper") != paper for c in cards):
                errs.append(f"TOURNAMENT_CORE_WORK_PAPER: {where}.neighbors[{j}] M# facts must reconstruct paper {paper}")
            edge_ids = row.get("collision_audits") or []
            if not isinstance(edge_ids, list) or not edge_ids:
                errs.append(f"TOURNAMENT_COLLISION_AUDIT: {where}.neighbors[{j}] needs current CA### edges")
                edge_ids = []
            for caid in edge_ids:
                edge = (collision.get(caid) or {}) if isinstance(caid, str) else {}
                if not edge:
                    errs.append(f"TOURNAMENT_COLLISION_UNKNOWN: {where}.neighbors[{j}] unknown {caid!r}")
                    continue
                if edge.get("lane") != lane.get("id") or edge.get("program_set_digest") != lane.get("program_set_digest") \
                        or edge.get("candidate_id") != sid or edge.get("candidate_digest") != eprogram.candidate_digest(cand):
                    errs.append(f"TOURNAMENT_COLLISION_BINDING: {where}.neighbors[{j}] {caid} is not bound to this exact program attempt")
                if edge.get("mech_card_id") not in cards or edge.get("axis") != axis:
                    errs.append(f"TOURNAMENT_COLLISION_RELATION: {where}.neighbors[{j}] {caid} must bind one listed M# on axis {axis}")
        if neighbors and axes != {"mechanism", "task_effect"}:
            errs.append(f"TOURNAMENT_PRIOR_COVERAGE: {where}: nearest set must cover both mechanism and task_effect axes")
        _nontrivial(prior.get("search_stop_reason"), 80, f"{where}.prior_art.search_stop_reason", errs)

        matrix = audit.get("emulation_matrix")
        if not isinstance(matrix, list):
            errs.append(f"TOURNAMENT_EMULATION_MATRIX: {where}: emulation_matrix must be an array")
            matrix = []
        represented: set[str] = set()
        for j, row in enumerate(matrix):
            row = row if isinstance(row, dict) else {}
            alternative = str(row.get("alternative") or "")
            if alternative not in neighbor_papers and alternative not in programs:
                errs.append(f"TOURNAMENT_EMULATION_ALTERNATIVE: {where}.emulation_matrix[{j}] unknown alternative {alternative!r}")
            represented.add(alternative)
            if not isinstance(row.get("can_emulate"), bool):
                errs.append(f"TOURNAMENT_EMULATION_BOOL: {where}.emulation_matrix[{j}].can_emulate must be boolean")
            _nontrivial(row.get("argument"), 80, f"{where}.emulation_matrix[{j}].argument", errs)
        required_alternatives = neighbor_papers | (set(programs) - {sid})
        missing_alternatives = sorted(required_alternatives - represented)
        if missing_alternatives:
            errs.append(f"TOURNAMENT_EMULATION_COVERAGE: {where}: matrix omits {missing_alternatives}")
        emulators_by_program[sid] = {
            str(row.get("alternative") or "") for row in matrix
            if isinstance(row, dict) and bool(row.get("can_emulate"))
        }

        ir = audit.get("irreducibility") or {}
        for field in ("non_reducible", "load_bearing", "collage"):
            if not isinstance(ir.get(field), bool):
                errs.append(f"TOURNAMENT_IRREDUCIBILITY: {where}.{field} must be boolean")
        _nontrivial(ir.get("argument"), 100, f"{where}.irreducibility.argument", errs)
        scope_audit = audit.get("scope") or {}
        if scope_audit.get("claimed_scope") != cand.get("change_scope"):
            errs.append(f"TOURNAMENT_SCOPE_CLAIM: {where}: scope.claimed_scope must quote candidate.change_scope")
        audited_scope = str(scope_audit.get("audited_scope") or "")
        if audited_scope not in eprogram.CHANGE_SCOPES:
            errs.append(f"TOURNAMENT_SCOPE_CLASS: {where}: audited_scope must be one of {eprogram.CHANGE_SCOPES}")
        for field in ("train_semantics_preserved", "infer_semantics_preserved"):
            if not isinstance(scope_audit.get(field), bool):
                errs.append(f"TOURNAMENT_SCOPE_BOOL: {where}.scope.{field} must be boolean")
        if not isinstance(scope_audit.get("preserved_interfaces"), list):
            errs.append(f"TOURNAMENT_SCOPE_INTERFACES: {where}.scope.preserved_interfaces must be an explicit array")
        _nontrivial(scope_audit.get("argument"), 100, f"{where}.scope.argument", errs)
        if audited_scope == "full_program" and (scope_audit.get("train_semantics_preserved") or
                                                  scope_audit.get("infer_semantics_preserved")):
            errs.append(f"TOURNAMENT_SCOPE_FULL_PROGRAM: {where}: full_program cannot preserve the incumbent's overall train or infer semantics")
        effect = audit.get("effect") or {}
        resource_status = ""
        has_unknown = False
        if not is_platform:
            if not isinstance(effect.get("causal_chain_valid"), bool):
                errs.append(f"TOURNAMENT_EFFECT_CHAIN: {where}.effect.causal_chain_valid must be boolean")
            for field in ("comparator_valid", "threshold_credible"):
                if not isinstance(effect.get(field), bool):
                    errs.append(f"TOURNAMENT_EFFECT_BOOL: {where}.effect.{field} must be boolean")
            resource_status = str(effect.get("resource_status") or "")
            if resource_status not in ("matched", "advantaged", "confounded", "unknown"):
                errs.append(f"TOURNAMENT_RESOURCE_STATUS: {where}.effect.resource_status invalid")
            _nontrivial(effect.get("argument"), 100, f"{where}.effect.argument", errs)
            confounds = effect.get("resource_confounds")
            if not isinstance(confounds, list):
                errs.append(f"TOURNAMENT_RESOURCE_CONFOUNDS: {where}: explicit array required (may be empty)")
            _nontrivial(effect.get("resource_provenance"), 80, f"{where}.effect.resource_provenance", errs)
            vectors = ((cand.get("effect_case") or {}).get("resources") or {})
            has_unknown = any(v == "unknown" for side in ("candidate", "comparator")
                              for v in ((vectors.get(side) or {}).values()))
            if has_unknown and resource_status == "matched":
                errs.append(f"TOURNAMENT_RESOURCE_UNKNOWN_MATCHED: {where}: material unknown axes cannot be asserted matched")
            if has_unknown and resource_status == "advantaged":
                _nontrivial(effect.get("worst_case_bound"), 80, f"{where}.effect.worst_case_bound", errs)
            frontier_refs = effect.get("frontier_refs")
            if not isinstance(frontier_refs, list):
                errs.append(f"TOURNAMENT_FRONTIER_REFS: {where}.effect.frontier_refs must be an explicit array")
                frontier_refs = []
            frontier_ids = [str(ref) for ref in frontier_refs]
            if any(ref not in sota_by_id for ref in frontier_ids):
                errs.append(f"TOURNAMENT_FRONTIER_REF_UNKNOWN: {where}: frontier_refs must resolve to S### entries")
            research_kernel = str((cand.get("novelty") or {}).get("kind") or "") in eprogram.RESEARCH_NOVELTY
            lane_sota_duty = (ctx.is_research() and econfig.sota_enabled(ctx.cfg)
                              and lane.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES)
            # v12 (field deadlock, L001): a sealed tournament whose
            # frontier_refs carry a non-exact-comparability S# makes the
            # downstream idea contract jointly unsatisfiable (IDEA_SOTA_DRIFT
            # demands sota_targets equal these refs while
            # IDEA_SOTA_NONCOMPARABLE bars every non-exact target). Same
            # front-shift principle as the mature-side check: the doomed
            # binding dies HERE, before the winner seals, not three tasks
            # later against an unrewritable file. Guarded to the EXACT lanes
            # whose maturation carries that pair (research mode, sota enabled,
            # non-exploratory, research kernel) - everywhere else a non-exact
            # ref is legal end-to-end and must stay admissible (self-review).
            # And when the library holds NO exact entry at all, the pair
            # REQUIRED x NONCOMPARABLE would itself be jointly unsatisfiable -
            # collapse it into one refusal that names the real exits.
            sota_has_exact = any(
                str((row or {}).get("comparability") or "") in ("", "exact")
                for row in sota_by_id.values())
            if lane_sota_duty and research_kernel and not sota_has_exact:
                errs.append(f"TOURNAMENT_FRONTIER_NO_EXACT_SOTA: {where}: the SOTA library holds no "
                            "exact-comparability entry, so a research kernel cannot bind a frontier "
                            "reference that maturation could ever settle - register an "
                            "exact-comparability S# at the next sota_scan if the field has one; if "
                            "the field genuinely publishes no protocol-exact number, this claim "
                            "cannot bind SOTA ('evo propose-abandon' the lane, or re-scope it)")
            else:
                noncomparable = [
                    f"{ref}({str((sota_by_id.get(ref) or {}).get('comparability'))})"
                    for ref in frontier_ids
                    if ref in sota_by_id
                    and str((sota_by_id.get(ref) or {}).get("comparability") or "") not in ("", "exact")]
                if noncomparable and lane_sota_duty and research_kernel:
                    errs.append(f"TOURNAMENT_FRONTIER_REF_NONCOMPARABLE: {where}: frontier_refs {noncomparable} "
                                "bind non-exact-comparability SOTA entries; maturation must copy these refs as "
                                "sota_targets and a non-exact target can never settle 'met' - bind "
                                "exact-comparability S# entries before winner selection")
                if lane_sota_duty and not frontier_refs:
                    errs.append(f"TOURNAMENT_FRONTIER_REF_REQUIRED: {where}: research M/E audit must bind a current S# comparator before winner selection")
            if econfig.sota_enabled(ctx.cfg) and research_kernel:
                claim_targets = {str(cell) for cell in ((cand.get("claim_scope") or {}).get("target_cells") or [])}
                outside = [
                    f"{ref}({str((sota_by_id.get(ref) or {}).get('cell') or '')})"
                    for ref in frontier_ids
                    if ref in sota_by_id and str((sota_by_id.get(ref) or {}).get("cell") or "") not in claim_targets
                ]
                if outside:
                    errs.append(
                        f"TOURNAMENT_FRONTIER_REF_SCOPE: {where}: frontier_refs {outside} must bind SOTA "
                        f"cells inside the candidate's frozen claim_scope.target_cells {sorted(claim_targets)}")

        theory_role = str(cand.get("theory_role") or "none")
        obligations_aligned = True
        if theory_role != "none":
            ta = audit.get("theory") or {}
            expected_status = "supported" if lane.get("search_origin") == "theory_derived" else "pending"
            if ta.get("status") != expected_status:
                errs.append(f"TOURNAMENT_THEORY: {where}: theory.status must be {expected_status!r}; "
                            "post-program theory is not pre-approved before challenge")
            _nontrivial(ta.get("argument"), 60, f"{where}.theory.argument", errs)
            if lane.get("search_origin") == "theory_derived":
                expected_obligations = {str(row.get("id")): row for row in
                                        (cand.get("theory_obligations") or []) if isinstance(row, dict)}
                rows = ta.get("obligation_audit")
                if not isinstance(rows, list):
                    errs.append(f"TOURNAMENT_THEORY_OBLIGATIONS: {where}: theory.obligation_audit array required")
                    rows = []
                seen_obligations: set[str] = set()
                for j, row in enumerate(rows):
                    row = row if isinstance(row, dict) else {}
                    did = str(row.get("id") or "")
                    expected_row = expected_obligations.get(did)
                    if expected_row is None or did in seen_obligations:
                        errs.append(f"TOURNAMENT_THEORY_OBLIGATION_ID: {where}.theory.obligation_audit[{j}] "
                                    "must name one unique mapped DO#")
                    seen_obligations.add(did)
                    if expected_row is not None and (row.get("kernel_refs") != expected_row.get("kernel_refs") or
                                                     row.get("operator_refs") != expected_row.get("operator_refs")):
                        errs.append(f"TOURNAMENT_THEORY_OBLIGATION_BINDING: {where}/{did}: KC#/OP# refs must "
                                    "exactly copy the frozen candidate mapping")
                    if not isinstance(row.get("aligned"), bool):
                        errs.append(f"TOURNAMENT_THEORY_OBLIGATION_BOOL: {where}/{did}.aligned must be boolean")
                        obligations_aligned = False
                    elif not row.get("aligned"):
                        obligations_aligned = False
                    _nontrivial(row.get("argument"), 80, f"{where}/{did}.argument", errs)
                if seen_obligations != set(expected_obligations):
                    errs.append(f"TOURNAMENT_THEORY_OBLIGATION_COVERAGE: {where}: audit must cover exactly "
                                f"{sorted(expected_obligations)}")
                    obligations_aligned = False

        if decision == "advance":
            if audited_scope != cand.get("change_scope") or eprogram.SCOPE_LEVEL.get(audited_scope, 0) < lane_min_level(lane):
                errs.append(f"TOURNAMENT_SCOPE_ADVANCE: {where}: independently audited scope must equal the claim and satisfy the lane floor")
            if not is_platform and (not effect.get("causal_chain_valid") or not effect.get("comparator_valid") or
                                    not effect.get("threshold_credible") or
                                    resource_status not in ("matched", "advantaged")):
                errs.append(f"TOURNAMENT_EFFECT_ADVANCE: {where}: the typed effect chain and frozen "
                            "causal/resource comparator must survive, and resources must be matched or "
                             "explicitly advantageous; promotion against stronger non-parent evidence is a "
                             "separate advance/kill judgment")
            if not is_platform:
                errs.extend(_planned_comparator_resource_errors(ctx, cand, where=where))
            if ctx.is_research() and not is_platform and has_unknown:
                errs.append(f"TOURNAMENT_RESOURCE_NUMERIC_ADVANCE: {where}: a research winner must freeze "
                            f"numeric candidate caps and comparator estimates on all "
                            f"{len(econfig.resource_axes(ctx.cfg))} configured resource axes. `unknown` may "
                            "remain on a killed draft, but prose is not a value the post-run contract can settle; "
                            "the candidate's realized receipt is still generated only after execution")
            if ctx.is_research() and not is_platform and \
                    (not ir.get("non_reducible") or not ir.get("load_bearing") or ir.get("collage")):
                errs.append(f"TOURNAMENT_RESEARCH_GATE: {where}: research winners need a non-reducible, "
                            "load-bearing kernel and cannot be A+B stitching")
            if lane.get("search_origin") == "theory_derived" and theory_role != "none" and \
                    (audit.get("theory") or {}).get("status") != "supported":
                errs.append(f"TOURNAMENT_THEORY_ADVANCE: {where}: a theory-derived program must instantiate its already-supported theory")
            if lane.get("search_origin") == "theory_derived" and not obligations_aligned:
                errs.append(f"TOURNAMENT_THEORY_OBLIGATION_ADVANCE: {where}: every surviving DO# must align "
                            "to the frozen KC#/OP# mapping before a theory-derived program advances")
            emulators = emulators_by_program.get(sid, set())
            if ctx.is_research() and emulators:
                errs.append(f"TOURNAMENT_EMULATED_ADVANCE: {where}: a research program emulated by a "
                            "frozen prior/candidate cannot advance as a new core")
    missing = set(programs) - audited
    if missing:
        errs.append(f"TOURNAMENT_COVERAGE: programs never audited: {sorted(missing)}")
    if not ctx.is_research():
        for sid in sorted(advanced):
            surviving_emulators = sorted(emulators_by_program.get(sid, set()) & advanced)
            if surviving_emulators:
                errs.append(
                    f"TOURNAMENT_CANDIDATE_EMULATED_ADVANCE: audit({sid}): engineering may borrow "
                    "published work, but two same-batch programs cannot both occupy survivor slots when "
                    f"{surviving_emulators} can emulate {sid}")
    winners = tj.get("winners")
    ranking = tj.get("survivor_ranking")
    if not isinstance(ranking, list):
        errs.append("TOURNAMENT_SURVIVOR_RANKING: survivor_ranking array required (empty when all are killed)")
        ranking = []
    ranked_ids: list[str] = []
    for i, row in enumerate(ranking, 1):
        row = row if isinstance(row, dict) else {}
        sid = str(row.get("sketch_id") or "")
        ranked_ids.append(sid)
        if row.get("rank") != i:
            errs.append(f"TOURNAMENT_RANK_ORDER: survivor_ranking[{i - 1}].rank must be {i}")
        if sid not in advanced or sid in ranked_ids[:-1]:
            errs.append(f"TOURNAMENT_RANK_MEMBER: rank {i} must name one unique advanced program")
        if row.get("pareto_status") not in ("nondominated", "tradeoff"):
            errs.append(f"TOURNAMENT_PARETO_STATUS: rank {i} must be nondominated|tradeoff")
        _nontrivial(row.get("argument"), 80, f"survivor_ranking[{i - 1}].argument", errs)
    if set(ranked_ids) != advanced:
        errs.append(f"TOURNAMENT_RANK_COVERAGE: ranking must cover exactly advanced programs {sorted(advanced)}")
    if not isinstance(winners, list):
        errs.append("TOURNAMENT_WINNERS: winners array required (empty is legal)")
    else:
        if bool(advanced) != bool(winners):
            errs.append("TOURNAMENT_WINNER_SURVIVOR_CONSISTENCY: advanced survivors require exactly one "
                        "rank-1 winner; winners may be empty only when every program was killed")
        if len(winners) > 1:
            errs.append("TOURNAMENT_WINNER_COUNT: exactly zero or one winner is supported per lane")
        for sid in winners:
            if not isinstance(sid, str) or sid not in advanced:
                errs.append(f"TOURNAMENT_WINNER_NOT_ADVANCED: {sid!r} was not marked advance")
        if winners and (not ranked_ids or winners[0] != ranked_ids[0]):
            errs.append("TOURNAMENT_WINNER_NOT_RANK1: winner must be rank 1 after pairwise/Pareto survivor comparison")
    return errs


# ---- theory dialectic (lanes with a declared T claim) ---------------------------------

def v_pose(ctx: Ctx, task: dict) -> list[str]:
    """The formal problem statement (v8). LLMs derive better on well-defined
    problems: before theorizing, a formal lane must POSE one - typed objects,
    named assumptions, a precise Want - like a theoretical physicist writing
    the problem before solving it. Anti-decorative-notation duty: every symbol
    declared in Setup must be USED outside Setup; notation that decorates
    instead of working is rejected here, before it can pollute a derivation."""
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    text = _read_md(ctx, task["outputs"][0], errs)
    if text is None:
        return errs
    secs = _require_sections(text, ["setup", "given", "want", "success criteria"],
                             "PROBLEM", errs, min_chars=40)
    setup = secs.get("setup") or ""
    syms = SYM_LINE.findall(setup)
    names = [s[0] for s in syms]
    if len(names) < 3:
        errs.append("POSE_SYMBOLS: Setup must declare >= 3 typed symbols as lines "
                    "'- sym: <symbol> : <space/type> - <meaning>' (got "
                    f"{len(names)}) - objects first, prose second")
    if len(set(names)) != len(names):
        errs.append("POSE_SYMBOL_DUP: Setup declares a symbol twice")
    given = secs.get("given") or ""
    if len(set(A_ID.findall(given))) < 2:
        errs.append("POSE_ASSUMPTIONS: Given must state >= 2 assumptions with ids (A1:, A2:, ...)")
    want = secs.get("want") or ""
    body_outside_setup = "\n".join(v for k, v in eutil.md_sections(text).items() if k != "setup")
    if names and not any(re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", want) for n in names):
        errs.append("POSE_WANT_SYMBOLS: the Want section must state the question IN the declared "
                    "symbols (none of them appears) - a Want that ignores its own Setup is prose, not a problem")
    for n in names:
        if not re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", body_outside_setup):
            errs.append(f"POSE_SYMBOL_UNUSED: declared symbol '{n}' never appears outside Setup - "
                        f"delete it or use it; decorative notation is the failure mode this stage exists to stop")
    sc = secs.get("success criteria") or ""
    result_keys = set(econfig.result_spec(ctx.cfg))
    if not any(k in sc for k in result_keys) and not any(
            re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", sc) for n in names):
        errs.append(f"POSE_SUCCESS_CRITERIA: success criteria must connect the formal answer to the "
                    f"observable (one of {sorted(result_keys)} or a declared symbol) - a solved problem "
                    "nobody can measure is decoration")
    return errs


def _derivation_chain_errors(ctx: Ctx, lane: dict, deriv: str) -> list[str]:
    """Mechanical audit of a formal derivation chain: numbered steps, resolved
    premises, plain-language shadows, failure conditions, symbol usage, and a
    step that establishes the posed Want."""
    errs: list[str] = []
    bud = ctx.cfg.get("budgets", {})
    need = (int(bud.get("derivation_steps_min_full", 5))
            if str(lane.get("formal_kind") or "") == "full"
            else int(bud.get("derivation_steps_min", 3)))
    steps = STEP_LINE.findall(deriv)
    if len(steps) < need:
        errs.append(f"THEORY_STEPS: formal lanes derive in a numbered chain '- S1 [from A1]: claim ; "
                    f"reads: plain meaning ; fails-if: condition' - found {len(steps)} steps, need >= {need}")
        return errs
    seen_steps: set[str] = set()
    reads = 0
    fails = 0
    for sid, premises, body in steps:
        if sid in seen_steps:
            errs.append(f"THEORY_STEP_DUP: step {sid} defined twice")
        for p in re.split(r"[,\s]+", premises.strip()):
            if not p:
                continue
            if re.fullmatch(r"A\d+", p):
                continue
            if re.fullmatch(r"S\d+", p):
                if p not in seen_steps:
                    errs.append(f"THEORY_STEP_PREMISE: step {sid} cites {p} which is not an EARLIER step - "
                                f"a chain that cites forward (or nothing) is not a derivation")
            else:
                errs.append(f"THEORY_STEP_PREMISE: step {sid} premise {p!r} must be an assumption id (A#) "
                            f"or an earlier step id (S#)")
        seen_steps.add(sid)
        if "reads:" in body:
            reads += 1
        if "fails-if:" in body:
            fails += 1
    if reads < len(steps):
        errs.append(f"THEORY_STEP_READS: every step needs a '; reads: <plain-language meaning>' shadow "
                    f"({reads}/{len(steps)} have one) - formulas whose meaning cannot be said in words are "
                    f"the garbage-formula failure mode")
    if fails < (len(steps) + 1) // 2:
        errs.append(f"THEORY_STEP_FAILS: >= half the steps need a 'fails-if: <condition>' marker "
                    f"({fails}/{len(steps)}) - a step with no failure condition is a step nobody checked")
    if STEP_MARK_WANT not in deriv:
        errs.append(f"THEORY_STEP_WANT: some step must carry the literal marker '[{STEP_MARK_WANT}]' - "
                    f"the chain must land on the posed problem's Want, not near it")
    for n in ctx.problem_symbols(lane):
        if not re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", deriv):
            errs.append(f"THEORY_SYMBOL_UNUSED: posed symbol '{n}' never appears in the derivation - "
                        f"the theory must solve the problem it posed, in the problem's own objects")
    return errs


def _toy_check_errors(ctx: Ctx, lane: dict, deriv: str) -> list[str]:
    """v9: a fully-formalizable chain must COMPUTE. The theorist ships
    TOY_CHECK.py next to the theory - stdlib-only, instantiates the posed
    objects on a toy instance, asserts >= 1 derivation step numerically, and
    prints 'TOY_CHECK_OK' plus the S# ids it verified. The engine executes it
    (same trust boundary as the engine-run smoke). A formal chain that never
    touches a number is the garbage-formula failure mode wearing a suit."""
    errs: list[str] = []
    rel = f".evo/rounds/{lane['round']}/lanes/{lane['id']}/TOY_CHECK.py"
    if not _exists(ctx, rel):
        errs.append(f"THEORY_TOY_MISSING: formalizable=full lanes must ship {rel} - a tiny stdlib-only "
                    f"script that instantiates the posed objects on a toy instance, asserts >= 1 "
                    f"derivation step numerically, and prints TOY_CHECK_OK plus the S# ids it verified")
        return errs
    import subprocess
    import sys as _sys
    try:
        proc = subprocess.run([_sys.executable, str(eutil.rpath(ctx.store.repo, rel))],
                              cwd=str(ctx.store.repo), capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        return [f"THEORY_TOY_TIMEOUT: {rel} exceeded 60s - toy instances are supposed to be tiny"]
    if proc.returncode != 0:
        tail = "; ".join((proc.stderr or proc.stdout or "").strip().splitlines()[-3:])
        errs.append(f"THEORY_TOY_FAILED: {rel} exited {proc.returncode} - the chain does not survive its "
                    f"own toy instance ({tail[:300]})")
        return errs
    out = proc.stdout or ""
    if "TOY_CHECK_OK" not in out:
        errs.append(f"THEORY_TOY_MARKER: {rel} must print the literal marker TOY_CHECK_OK after its assertions")
    step_ids = {m[0] for m in STEP_LINE.findall(deriv)}
    verified = set(re.findall(r"\bS\d+\b", out))
    if step_ids and not (verified & step_ids):
        errs.append(f"THEORY_TOY_STEPS: {rel} must print WHICH derivation step ids (S#) its assertions "
                    f"verify - none of {sorted(step_ids)[:6]} appears in its output")
    return errs


def v_theorize(ctx: Ctx, task: dict) -> list[str]:
    """Validate a theory by what it constrains or produces, not one narrative shape."""
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    text = _read_md(ctx, task["outputs"][0], errs)
    if text is None:
        return errs
    wanted = ["obstruction or desiderata", "result", "derivation", "design consequences",
              "ruled-out alternatives", "executable obligations", "discriminating predictions",
              "scope and failure conditions"]
    secs = _require_sections(text, wanted, "THEORY", errs, min_chars=80)
    deriv = secs.get("derivation") or ""
    if len(deriv.strip()) < 400:
        errs.append("THEORY_DERIVATION_THIN: derivation needs >=400 chars of explicit premise -> result steps")
    if len(set(A_ID.findall(text))) < 2:
        errs.append("THEORY_ASSUMPTIONS: name >=2 A# assumptions")
    if lane.get("formal"):
        errs.extend(_derivation_chain_errors(ctx, lane, deriv))
        if str(lane.get("formal_kind") or "") == "full":
            errs.extend(_toy_check_errors(ctx, lane, deriv))
    obligations = secs.get("executable obligations") or ""
    obligation_rows = DO_LINE.findall(obligations)
    if len({did for did, _ in obligation_rows}) < 2:
        errs.append("THEORY_DESIGN_OBLIGATIONS: executable obligations needs >=2 unique bullet rows "
                    "'- DO1: ...' that a program/implementation can satisfy")
    for did, body in obligation_rows:
        _nontrivial(body, 50, f"executable obligation {did}", errs)
    predictions = secs.get("discriminating predictions") or ""
    if len(set(re.findall(r"\bTP\d+\b", predictions))) < 2:
        errs.append("THEORY_PREDICTIONS: name >=2 TP# predictions that distinguish the result from plausible alternatives")
    if lane.get("winner_sketch"):
        winner = ctx.winner_sketch(lane) or {}
        kernels = set(eprogram.kernel_ids(winner))
        if kernels and not kernels.intersection(set(re.findall(r"\bKC\d+\b", text))):
            errs.append(f"THEORY_PROGRAM_LINK: post-program theory must address winner kernel ids {sorted(kernels)}")
    cyc = int(task["subject"].get("cycle") or 1)
    if cyc > 1:
        resp = eutil.find_section(eutil.md_sections(text), "response to challenge")
        if not resp or len(resp.strip()) < 80:
            errs.append("THEORY_RESPONSE_MISSING: cycle>=2 needs a substantive Response to challenge")
        else:
            # ``cycle`` is candidate-local rigor budget; artifact ids remain
            # lane-global so retries and ranked-survivor fallbacks never
            # overwrite sealed history.  Validate against the exact prior
            # challenge bound into this engine-created task, not cycle-1.
            prev = str(task["subject"].get("previous_challenge") or "")
            if not prev:
                # Compatibility for an open task materialized before explicit
                # binding existed: derive identity from the immutable output
                # sequence, never from the candidate-local cycle counter.
                output = str((task.get("outputs") or [""])[0])
                match = re.search(r"^(.*[/\\])THEORY_c(\d+)\.md$", output)
                if match and int(match.group(2)) > 1:
                    prev = f"{match.group(1)}CHALLENGE_c{int(match.group(2)) - 1}.md"
                else:
                    errs.append("THEORY_RESPONSE_BINDING: cycle>=2 task is missing its engine-bound previous challenge")
            prev_text = eutil.read_text(eutil.rpath(ctx.store.repo, prev)) if _exists(ctx, prev) else ""
            _check_quotes(QUOTE_LINE.findall(resp), prev_text, "THEORY.response", errs, min_quotes=1)
    return errs


def v_challenge(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    review = _read_md(ctx, task["outputs"][0], errs)
    tpath = lane.get("theory_path") or ""
    theory = eutil.read_text(eutil.rpath(ctx.store.repo, tpath)) if tpath and _exists(ctx, tpath) else ""
    if review is None:
        return errs
    if not theory:
        errs.append("CHALLENGE_NO_THEORY: no theory document on record for this lane (engine bug; run 'evo doctor')")
        return errs
    m = re.search(r"^VERDICT:\s*(\S+)", review, re.M)
    verdicts = ("PROCEED", "REVISE", "READ", "FORMALIZE")
    if not m or m.group(1) not in verdicts:
        errs.append(f"CHALLENGE_VERDICT: review must start a line with 'VERDICT: <{'|'.join(verdicts)}>'")
    errs.extend(critic_isolation_errors(
        ctx, task, release=bool(m and m.group(1) == "PROCEED"), author_types=("theorize",)))
    wanted = ["premise audit", "derivation attack", "design consequence audit",
              "alternative explanation", "prediction audit", "verdict rationale"]
    if lane.get("formal"):
        wanted.append("step audit")
    secs = _require_sections(review, wanted, "CHALLENGE", errs, min_chars=60)
    if lane.get("formal"):
        sa = secs.get("step audit") or ""
        if sa and not re.search(r"\bS\d+\b", sa):
            errs.append("CHALLENGE_STEP_AUDIT: the step audit must name the weakest derivation step by "
                        "its S# id and attack its justification - 'the chain looks fine' is not an audit")
    _check_quotes(QUOTE_LINE.findall(review), theory, "CHALLENGE", errs, min_quotes=2)
    if m and m.group(1) == "PROCEED":
        cyc = int(task["subject"].get("cycle") or 1)
        if deep_rigor(lane):
            min_cyc = int(ctx.cfg.get("budgets", {}).get("theory_cycles_min_full", 2))
            if cyc < min_cyc:
                errs.append(f"CHALLENGE_DEEP_MIN_CYCLES: a theory_rigor=full claim cannot PROCEED at cycle {cyc}; "
                            f"it must survive >= {min_cyc} challenge cycles - find the weakest step and attack it "
                            f"(REVISE) or demand reading (READ)")
        obj = eutil.find_section(eutil.md_sections(review), "strongest surviving objection")
        if not obj or len(obj.strip()) < 60:
            errs.append("CHALLENGE_OBJECTION: a PROCEED must state the strongest surviving objection (>= 60 chars)")
    if m and m.group(1) == "READ":
        topics = [t.strip() for t in TOPIC_LINE.findall(review) if t.strip()]
        if len(topics) < 2:
            errs.append("CHALLENGE_READ_TOPICS: a READ verdict needs a 'required reading' section with >= 2 "
                        "'- topic: ...' lines naming what must be read and why the theory cannot proceed without it")
    if m and m.group(1) == "FORMALIZE":
        if lane.get("formal"):
            errs.append("CHALLENGE_ALREADY_FORMAL: FORMALIZE demands the formal ladder for a lane that "
                        "skipped it; this lane already posed a problem - attack the chain instead (REVISE)")
        just = eutil.find_section(eutil.md_sections(review), "formalization demand")
        if not just or len(just.strip()) < 80:
            errs.append("CHALLENGE_FORMALIZE_WHY: a FORMALIZE verdict needs a 'formalization demand' section "
                        "(>= 80 chars): which claim of the theory is precise enough to be posed and derived, "
                        "and why prose is hiding its weakest step")
    return errs


def _load_idea(ctx: Ctx, lane: dict, errs: list[str]) -> tuple[dict | None, str | None]:
    meta = _read_json(ctx, f".evo/ideas/{lane['idea']}.meta.json", errs) if lane.get("idea") else None
    md_path = f".evo/ideas/{lane['idea']}.md" if lane.get("idea") else None
    md = _read_md(ctx, md_path, errs) if md_path else None
    return meta, md


def _ablation_contract_errors(ctx: Ctx, lane: dict, meta: dict, errs: list[str]) -> dict:
    """Validate the one-run causal contract shared by design and execution.

    A targeted ablation is deliberately not a small candidate idea.  Its
    admissibility rests on a real parent result, one structured intervention,
    held-constant factors, and a decision that changes under the two outcomes.
    """
    idx = egraph.by_id(ctx.g)
    model_parents = [p for p in lane.get("parents", []) if p in idx and idx[p].get("role") != "platform"]
    if econfig.ablation_mode(ctx.cfg) != "targeted":
        errs.append("ABLATION_POLICY_OFF: the user-approved project policy does not allow targeted ablation nodes")
    if len(model_parents) != 1:
        errs.append("ABLATION_PARENT: targeted ablation needs exactly one concluded model parent")
    ablation = meta.get("ablation")
    if not isinstance(ablation, dict):
        errs.append("ABLATION_SCHEMA: targeted_ablation requires an ablation object")
        return {}
    parent = str(ablation.get("parent") or "")
    if len(model_parents) == 1 and parent != model_parents[0]:
        errs.append(f"ABLATION_PARENT_BINDING: ablation.parent must be {model_parents[0]!r}")
    if parent and parent not in str(ablation.get("trigger_evidence") or ""):
        errs.append("ABLATION_TRIGGER_PARENT: trigger_evidence must name the parent result that created "
                    "this causal uncertainty")
    _nontrivial(ablation.get("question"), 50,
                "ablation.question (the one causal uncertainty this run resolves)", errs)
    alternatives = ablation.get("competing_explanations")
    if not isinstance(alternatives, list) or len(alternatives) != 2:
        errs.append("ABLATION_ALTERNATIVES: competing_explanations must contain exactly X1 and X2")
    else:
        alt_ids: set[str] = set()
        for i, alt in enumerate(alternatives):
            aid = str((alt or {}).get("id") or "")
            if not re.fullmatch(r"X[12]", aid) or aid in alt_ids:
                errs.append(f"ABLATION_ALTERNATIVE_ID: alternative[{i}].id must uniquely be X1 or X2")
            alt_ids.add(aid)
            _nontrivial((alt or {}).get("statement"), 40,
                        f"ablation.competing_explanations[{i}].statement", errs)
        if alt_ids != {"X1", "X2"}:
            errs.append("ABLATION_ALTERNATIVE_COVERAGE: competing_explanations must contain one X1 and one X2")
    for field, minimum in (("intervention", 40), ("trigger_evidence", 30),
                           ("decision_if_effect", 50), ("decision_if_no_effect", 50),
                           ("why_cheaper_evidence_insufficient", 50)):
        _nontrivial(ablation.get(field), minimum, f"ablation.{field}", errs)
    effect_supports = str(ablation.get("effect_supports") or "")
    no_effect_supports = str(ablation.get("no_effect_supports") or "")
    if {effect_supports, no_effect_supports} != {"X1", "X2"}:
        errs.append("ABLATION_OUTCOME_MAP: effect_supports and no_effect_supports must map the two outcomes "
                    "bijectively to X1 and X2 before the run")
    trigger_artifacts = ablation.get("trigger_artifacts")
    if not isinstance(trigger_artifacts, list) or not trigger_artifacts:
        errs.append("ABLATION_TRIGGER_ARTIFACTS: trigger_artifacts must list existing parent evidence files")
    else:
        bad = [str(p) for p in trigger_artifacts if not _exists(ctx, str(p))]
        if bad:
            errs.append(f"ABLATION_TRIGGER_ARTIFACT_MISSING: trigger evidence files do not exist: {bad[:4]}")
        if parent and not any(str(p).startswith(f".evo/nodes/{parent}/") for p in trigger_artifacts):
            errs.append(f"ABLATION_TRIGGER_ARTIFACT_PARENT: at least one trigger artifact must come from "
                        f".evo/nodes/{parent}/")
        parent_node = idx.get(parent) or {}
        active_result = str(parent_node.get("result_doc") or f".evo/nodes/{parent}/NODE_RESULT.md")
        active_metrics = str(parent_node.get("eval_metrics_path") or f".evo/nodes/{parent}/eval/metrics.json")
        if set(str(p) for p in trigger_artifacts) != {active_result, active_metrics}:
            errs.append("ABLATION_TRIGGER_ACTIVE_HEADS: trigger_artifacts must be exactly the parent's "
                        f"active result/evaluation heads {[active_result, active_metrics]}; superseded paths are history")
    factor = ablation.get("changed_factor")
    if not isinstance(factor, dict):
        errs.append("ABLATION_CHANGED_FACTOR: changed_factor object required")
    else:
        _nontrivial(factor.get("name"), 8, "ablation.changed_factor.name", errs)
        parent_value = str(factor.get("parent_value") or "").strip()
        ablated_value = str(factor.get("ablated_value") or "").strip()
        if not parent_value or not ablated_value:
            errs.append("ABLATION_CHANGED_FACTOR_VALUES: changed_factor needs non-empty parent_value and ablated_value")
        elif parent_value == ablated_value:
            errs.append("ABLATION_CHANGED_FACTOR_NOOP: parent_value and ablated_value must differ")
    held = ablation.get("held_constant")
    if not isinstance(held, list) or len(held) < 3:
        errs.append("ABLATION_HELD_CONSTANT: held_constant needs >= 3 concrete controls, including data/eval "
                    "and training-budget/recipe controls")
    else:
        for i, item in enumerate(held):
            _nontrivial(item, 20, f"ablation.held_constant[{i}]", errs)
    cap = int((((ctx.cfg.get("evidence_policy") or {}).get("ablation") or {})
               .get("max_costly_runs_per_node") or 0))
    if ablation.get("costly_runs") != 1 or cap != 1:
        errs.append("ABLATION_RUNS: a targeted ablation is exactly one changed-component run; it cannot "
                    "smuggle a sweep or seed cross-product into the node")
    for forbidden in ("mechanism_probe", "attribution_waiver", "scaling"):
        if meta.get(forbidden) is not None:
            errs.append(f"ABLATION_RECURSIVE_EVIDENCE: targeted ablation must omit {forbidden}; it is already "
                        "the diagnostic run")
    return ablation


def maintenance_gain(assessment: dict, parent_gain: dict | None = None) -> dict:
    """Per-cell headroom THIS repair recovered.

    A repair's real effect had nowhere to be recorded: the node is frontier
    excluded, earns no promotion, and its downstream candidate is (correctly)
    measured against the repaired base, so a genuine +5% unlock silently
    vanished from the project's books - which quietly punished doing the
    plumbing work first.  This freezes it as an explicit engine-computed
    fact: it licenses nothing, it is the audit trail of what the repair
    bought, and the frontier view names it.

    The assessment's delta is measured against the nearest NON-maintenance
    ancestor (the parity anti-ratchet reference), so in a chain A->m1->m2 the
    raw delta of m2 INCLUDES m1's already-booked gain and summing the column
    overstated what the chain recovered.  ``delta`` is therefore this link's
    own contribution (raw minus the immediate maintenance parent's cumulative,
    both in the same reference frame and direction normalization), and
    ``cumulative_delta`` keeps the raw vs-ancestor number for the next link's
    subtraction.
    """
    cells = assessment.get("cells") or {}
    decision = list(dict.fromkeys((assessment.get("target_cells") or [])
                                  + (assessment.get("guardrail_cells") or [])))
    out: dict[str, dict] = {}
    for cid in decision:
        row = cells.get(cid) or {}
        delta = row.get("delta")
        if not isinstance(delta, (int, float)) or isinstance(delta, bool):
            continue
        entry = {"delta": delta, "cumulative_delta": delta, "status": row.get("status")}
        prev = (parent_gain or {}).get(cid)
        if isinstance(prev, dict):
            prev_cum = prev.get("cumulative_delta", prev.get("delta"))
            if isinstance(prev_cum, (int, float)) and not isinstance(prev_cum, bool):
                entry["delta"] = delta - prev_cum
        out[cid] = entry
    return out


def maintenance_parity_status(assessment: dict) -> str:
    """Engine-computed parity settlement for a maintenance node: every claim
    target and guardrail cell must land improved or noninferior against the
    repaired parent.  unknown/regressed anywhere -> not_met (fail closed)."""
    cells = assessment.get("cells") or {}
    decision = list(dict.fromkeys((assessment.get("target_cells") or [])
                                  + (assessment.get("guardrail_cells") or [])))
    if not decision:
        return "not_met"
    for cid in decision:
        if str((cells.get(cid) or {}).get("status") or "") not in ("improved", "noninferior"):
            return "not_met"
    return "met"


_INSTRUMENTAL_FORBIDDEN_META = (
    "change_scope", "program", "novelty", "effect_case", "theory_role", "theory_target",
    "program_digest", "kernel_hash", "kernel_ids", "sketch_id", "diagnosis_digest",
    "hypothesis_ids", "prior_art_card_ids", "nearest_published", "sota_targets",
    "siblings_distance", "claim_scope", "mechanism_probe", "attribution_waiver",
    "scaling", "dominance", "predictions", "repeat_rule",
)


def critic_isolation_errors(ctx: Ctx, task: dict, *, release: bool,
                            author_types: tuple[str, ...]) -> list[str]:
    """Provenance discipline for self-judged RELEASE verdicts (v11).

    The decisive booleans of tournament/red_team/challenge/fidelity are written
    by the same agent that authored the work, with independence existing only
    as role-play prose. A CLI cannot verify who executes a task; what it CAN
    own is the submission record. Direction-sensitive by design: only the
    RELEASE direction (advance/ACCEPT/PROCEED/FAITHFUL) needs a fresh session -
    kill/REVISE verdicts are self-punishing and keep repair continuity.
    off = no check; attest = provenance recorded on the task row and surfaced
    to the human; strict = a release verdict must carry a session id different
    from the authored work's (honest-agent enforcement, same trust boundary as
    the rest of the engine: it stops drift, not a lying operator).
    """
    mode = str((ctx.cfg.get("policy") or {}).get("critic_isolation", "attest"))
    if mode != "strict" or not release:
        return []
    subj = task.get("subject") or {}
    sess = str(task.get("session") or "")
    author_task, author_sess = None, ""
    for t in reversed(ctx.st.get("tasks", [])):
        if t.get("type") not in author_types or t.get("status") != "done":
            continue
        ts = t.get("subject") or {}
        same_subject = (ts.get("lane") == subj.get("lane")) if subj.get("lane") \
            else (ts.get("node") == subj.get("node"))
        if same_subject:
            author_task = t
            author_sess = str(t.get("session") or "")
            break
    if not sess:
        return ["CRITIC_SESSION_REQUIRED: policy.critic_isolation=strict - a release verdict "
                "must be submitted with --session (or EVO_SESSION) from a session that did not "
                "author the work; spawn a fresh sub-agent for the review"]
    if author_task is not None and not author_sess:
        # Fail closed, not open: with the author's session unrecorded, "my
        # session differs" is unfalsifiable and strict would be satisfied by
        # ANY id - including the author quietly minting a fresh one.
        return [f"CRITIC_SESSION_AUTHOR_UNKNOWN: the authored work (task {author_task.get('id')}) "
                "recorded no session and is CLOSED - it cannot be re-submitted, so under strict this "
                "exact candidate can never be released. Real exits: give a kill/REVISE verdict (those "
                "need no isolation) so the revision/resketch cycle re-authors WITH --session, or switch "
                "policy to critic_isolation=attest. (New author submissions without --session are now "
                "rejected before they close, so this trap only exists for pre-fix history.)"]
    if author_sess and sess == author_sess:
        return ["CRITIC_SESSION_SAME: this release verdict comes from the SAME session that "
                "authored the work under review; the review must be a fresh session/sub-agent "
                "(kill/REVISE verdicts need no isolation - only the release direction does)"]
    return []


def review_provenance_lines(ctx: Ctx, lane: dict) -> list[str]:
    """Human-facing provenance summary for a lane's release reviews (v11).

    This is what makes attest mode REAL: the human at the idea gate sees
    whether the decisive reviews came from the authoring session or a fresh
    one. Records, never blocks - strict is the blocking tier.
    """
    if str((ctx.cfg.get("policy") or {}).get("critic_isolation", "attest")) == "off":
        return []
    pairs = (("sketch", "tournament", "tournament advance"),
             ("mature", "red_team", "red-team ACCEPT"),
             ("theorize", "challenge", "challenge PROCEED"))
    lid = str(lane.get("id") or "")
    latest: dict[str, dict] = {}
    for t in ctx.st.get("tasks", []):
        if t.get("status") == "done" and (t.get("subject") or {}).get("lane") == lid:
            latest[str(t.get("type"))] = t
    out: list[str] = []
    for author_type, review_type, label in pairs:
        review = latest.get(review_type)
        if review is None:
            continue
        a_sess = str((latest.get(author_type) or {}).get("session") or "")
        r_sess = str(review.get("session") or "")
        if not a_sess or not r_sess:
            verdict = "provenance UNKNOWN (a session id was not recorded)"
        elif a_sess == r_sess:
            verdict = "SAME SESSION as the author - this review is a self-audit"
        else:
            verdict = "independent session"
        out.append(f"- {label}: {verdict}")
    return out


def repeat_rule_errors(cfg: dict, meta: dict, st: dict | None = None) -> list[str]:
    """v11.1 P4 registration validator (extracted for direct testability).

    Six-boundary contract: single-run tier only (preplanned is the mutually
    exclusive other tier), exactly one decision cell, the literal
    when/max_repeats values (no adaptive loops), and a defined band - explicit,
    else the cell's recorded noise floor, else the registration is refused as
    empty ceremony."""
    errs: list[str] = []
    rr = meta.get("repeat_rule")
    if rr is None:
        return errs
    cells_by_id = {str(c.get("id") or ""): c for c in egraph.decision_cells(cfg)}
    if not isinstance(rr, dict):
        errs.append("IDEA_REPEAT_RULE: repeat_rule must be an object {cell, band?, when, max_repeats}")
        rr = {}
    if econfig.training_replication_policy(cfg).get("mode") == "preplanned":
        errs.append("IDEA_REPEAT_RULE_MODE: the project runs preplanned multi-seed training - it already "
                    "has a real interval on every measurement, so an on-the-line repeat rule is illegal "
                    "(the two tiers are mutually exclusive)")
    cell = cells_by_id.get(str(rr.get("cell") or ""))
    if cell is None:
        errs.append(f"IDEA_REPEAT_RULE_CELL: repeat_rule.cell {rr.get('cell')!r} is not a decision cell")
    if rr.get("when") != "decision_within_band":
        errs.append("IDEA_REPEAT_RULE_WHEN: repeat_rule.when must be the literal 'decision_within_band'")
    if rr.get("max_repeats") != 1:
        errs.append("IDEA_REPEAT_RULE_MAX: repeat_rule.max_repeats must be the literal 1 - one repeat, "
                    "never an adaptive run-until-it-clears loop")
    band = rr.get("band")
    if band is not None and (isinstance(band, bool) or not isinstance(band, (int, float))
                             or not math.isfinite(float(band)) or float(band) <= 0):
        errs.append("IDEA_REPEAT_RULE_BAND: repeat_rule.band must be a positive finite number when given")
    if band is None and cell is not None \
            and econfig.noise_floor(cfg, str(rr.get("cell") or ""), st) <= 0:
        errs.append("IDEA_REPEAT_RULE_NO_BAND: repeat_rule needs an explicit band or a recorded noise "
                    "floor for that cell; with neither, 'lands on the line' is undefined and the rule "
                    "is empty ceremony - either register a band (your own 'below this I do not trust "
                    "it' line) or drop the rule")
    extra_rr = sorted(set(rr) - {"cell", "band", "when", "max_repeats"})
    if extra_rr:
        errs.append(f"IDEA_REPEAT_RULE_FIELDS: repeat_rule has unknown fields {extra_rr}")
    return errs


def node_review_provenance_lines(ctx: Ctx, rid: str) -> list[str]:
    """v11.1 P6 - the R2 lens the network cut short: implementer-vs-auditor
    session pairing on the WORKFLOW side (implement vs fidelity), per node of
    one round, shown at the round gate. The lane-side twin is
    review_provenance_lines. Records, never blocks - strict stays the
    blocking tier."""
    if str((ctx.cfg.get("policy") or {}).get("critic_isolation", "attest")) == "off":
        return []
    out: list[str] = []
    for n in ctx.g.get("nodes", []):
        if str(n.get("round") or "") != str(rid):
            continue
        latest: dict[str, dict] = {}
        for t in ctx.st.get("tasks", []):
            if t.get("status") == "done" and (t.get("subject") or {}).get("node") == n.get("id"):
                latest[str(t.get("type"))] = t
        imp = latest.get("implement")
        for review_type, label in (("fidelity", "fidelity audit"),
                                   ("ablation_fidelity", "ablation-fidelity audit")):
            review = latest.get(review_type)
            if review is None or imp is None:
                continue
            a_sess, r_sess = str(imp.get("session") or ""), str(review.get("session") or "")
            if not a_sess or not r_sess:
                verdict = "provenance UNKNOWN (a session id was not recorded)"
            elif a_sess == r_sess:
                verdict = "SAME SESSION as the implementer - this audit is a self-audit"
            else:
                verdict = "independent session"
            out.append(f"- node {n.get('id')} {label}: {verdict}")
    return out


def parent_hold_defects(ctx: Ctx, p: str) -> list[str]:
    """R9 (external audit r6): a node under an active hold is quarantined -
    typically by a pending recovery or a TERMINAL fork diagnosis whose handoff
    keeps the hold while a replacement is built. Nothing stopped a new lane
    from adopting exactly that damaged authority as its parent; with the fork
    handoff now allowed to open a fresh round under the hold, this is the
    guard that keeps the quarantine meaningful."""
    holds = erecover.active_holds_for_subject(ctx.st, ctx.g, node=str(p))
    if holds:
        return [f"parent {p} is under active hold(s) {', '.join(holds)} - a pending recovery/fork "
                "quarantines this authority; resolve the recovery (or pick another parent) before "
                "new work consumes it"]
    return []


def model_parent_defects(idx: dict, p: str) -> list[tuple[str, str]]:
    """(defect_kind, detail) rows for using node ``p`` as a model parent.

    One shared core for the portfolio door, the mid-round intake door and
    plan_node. Parent legality used to be enforced only at the two doors, so a
    parent that died AFTER admission - e.g. recover-abort --abandon-node mid
    round - slipped into execution and the child was silently measured against
    the baseline comparator instead of its real reference.
    """
    n = idx.get(p)
    if n is None:
        return [("unknown", f"parent {p} does not exist")]
    rows: list[tuple[str, str]] = []
    tip = egraph.effective_frontier_ancestor(idx, p)
    tip_node = idx.get(tip) or {}
    # R7 audit: the old combined message ALWAYS named the tip, so when the
    # parent itself (e.g. a maintenance proxy) was the pruned object - or both
    # were - following the printed command revived the wrong node and the same
    # error returned verbatim. Name every retired object with its own command.
    pruned_ids = list(dict.fromkeys(
        pid for pid, node_row in ((p, n), (tip, tip_node))
        if node_row.get("retire_reason") == "pruned"))
    archived_ids = list(dict.fromkeys(
        pid for pid, node_row in ((p, n), (tip, tip_node))
        if node_row.get("retire_reason") == "archived"))
    if pruned_ids:
        cmds = "; ".join(f"'evo revive --node {pid} --note ...'" for pid in pruned_ids)
        rows.append(("pruned", f"parent {p} (lineage tip {tip}): pruned object(s) {pruned_ids} need an "
                               f"explicit user decision to reopen ({cmds}); any id still listed after a "
                               "revive is the one that remains pruned"))
    elif archived_ids:
        # R7 audit: retirement (ANY legal reason) waives the node's working-
        # byte/Git duties, so an archived lineage keeps its measured record
        # but may no longer have intact working artifacts - new consumers
        # need the revival the CLI promises ("Future portfolios may extend
        # it again" - after revive re-proves the bytes).
        cmds = "; ".join(f"'evo revive --node {pid} --note ...'" for pid in archived_ids)
        rows.append(("archived", f"parent {p} (lineage tip {tip}): archived object(s) {archived_ids} "
                                 f"keep their measured record, but retirement waived their working-byte "
                                 f"checks - revive before any new consumer builds on them ({cmds})"))
    elif n.get("status") != "concluded":
        rows.append(("unfinished", f"parent {p} is not concluded (status {n.get('status')!r})"))
    elif n.get("verdict") == "screened_out":
        rows.append(("screened_out", f"parent {p} stopped before producing a valid deliverable; use its "
                                     "observations/lessons as evidence, not the node as a model parent"))
    elif n.get("experiment_purpose") == "diagnostic_probe":
        rows.append(("probe", f"probe {p} is evidence, never lineage; parent the node it probed instead"))
    elif n.get("experiment_purpose") in econfig.EXPLORATORY_PURPOSES:
        # v11.1 P5 (R1 fix): observations-only everywhere means HERE too - a
        # scout's numbers must not become a child's causal comparator. Cite its
        # OB### and open a confirmatory candidate instead.
        rows.append(("exploratory", f"exploratory node {p} is observations-only, never lineage; cite its "
                                    f"OB### or open a confirmatory candidate (confirmatory_of: {p})"))
    elif n.get("experiment_purpose") == "maintenance" and n.get("maintenance_parity") != "met":
        rows.append(("maint_unsettled", f"maintenance node {p} did not settle parity=met; "
                                        "its repaired base is not inheritable"))
    return rows


def injected_lane_errors(ctx: Ctx, ln: dict, rid: str) -> list[str]:
    """Legality of ONE mid-round instrumental lane (`evo probe`/`evo maintain`).

    Deliberately the same rules the portfolio validator applies to these
    purposes - purpose/intent/origin/level, one legal parent, per-round cap -
    so the two intake doors can never accept different shapes.  Shares and
    idea-mix arithmetic do not apply: instrumental lanes ride on top of the
    round's search bets by construction.
    """
    errs: list[str] = []
    purpose = str(ln.get("experiment_purpose") or "")
    if purpose not in econfig.INJECTABLE_PURPOSES:
        return [f"INJECT_PURPOSE: mid-round intake accepts only "
                f"{'|'.join(econfig.INJECTABLE_PURPOSES)}, got {purpose!r}"]
    # The name becomes a path component of the engine-authored lane brief, so
    # it is a slug, not free text: anything else could escape .evo entirely.
    name = str(ln.get("name") or "")
    if not LANE_NAME_RE.fullmatch(name):
        errs.append(f"INJECT_NAME: lane name {name!r} must match {LANE_NAME_RE.pattern} "
                    "(it is a path component of the engine-written lane brief)")
    # Case-insensitive and abandonment-blind: the name resolves to a lane brief
    # PATH, and on a case-insensitive filesystem 'Alpha' and 'alpha' are the
    # same directory.  An abandoned lane's brief is frozen evidence of what was
    # attempted; re-using its name would overwrite it.
    elif any(str(l.get("name") or "").casefold() == name.casefold()
             for l in ctx.st.get("lanes", []) if l.get("round") == rid):
        errs.append(f"INJECT_NAME_DUP: round {rid} already has a lane named {name!r} "
                    "(case-insensitively, abandoned lanes included - their brief is frozen evidence)")
    if ln.get("intent") != "exploit":
        errs.append("INJECT_INTENT: instrumental lanes are exploit work on one observed parent")
    if ln.get("search_origin") != "repair":
        errs.append("INJECT_ORIGIN: instrumental lanes use search_origin='repair'")
    if ln.get("min_level") != 0:
        errs.append("INJECT_LEVEL: instrumental lanes use min_level=0")
    idx = egraph.by_id(ctx.g)
    parents = list(ln.get("parents") or [])
    model_parents = [p for p in parents if p in idx and idx[p].get("role") != "platform"]
    if len(model_parents) != 1 or len(parents) != len(model_parents):
        errs.append(f"INJECT_PARENT: exactly one concluded model parent required, got {parents}")
    for p in model_parents:
        # Shared per-parent core (the pruned firewall inside it follows the
        # lineage through repairs: a maintenance child of a pruned node is the
        # same dead lineage wearing a fresh id).
        for kind, detail in model_parent_defects(idx, p):
            errs.append(f"INJECT_PARENT_{kind.upper()}: {detail}")
        for detail in parent_hold_defects(ctx, p):
            errs.append(f"INJECT_PARENT_HELD: {detail}")
    cap_key = econfig.INJECTABLE_CAP_KEYS[purpose]
    cap = int((ctx.cfg.get("budgets") or {}).get(cap_key, 1) or 0)
    # The cap counts every instrumental lane the round OPENED, abandoned ones
    # included.  An earlier version counted only lanes that reached the gate, so
    # that rejecting a badly-posed one would not burn the round's budget - but
    # that refunded the slot on every rejection, and reject -> reopen -> reject
    # cycles could then run forever, each lap costing the user another manual
    # gate decision.  Revising a rejected lane is not what opening a new one is
    # for: `evo decide --reject --retry-stage <design stage>` rewinds the SAME
    # lane for another draft and spends no slot, so an outright reject can mean
    # what it says.  Portfolio-declared lanes are likewise fixed at round open
    # and not refunded when abandoned; counting opens keeps both doors equal.
    design_stage = eflow.INSTRUMENTAL_SEQ[purpose][0]
    opened = [l for l in ctx.st.get("lanes", [])
              if l.get("round") == rid and l.get("experiment_purpose") == purpose]
    if cap <= 0:
        # The documented off-switch. Saying "already opened 0 lane(s)" and
        # offering a retry stage would both be false here, and the second would
        # send the user hunting for a gate that does not exist.
        errs.append(f"INJECT_DISABLED: {purpose} work is turned off for this project "
                    f"(budgets.{cap_key}={cap}); raise it to admit any")
    elif len(opened) + 1 > cap:
        # Only advertise the slot-free revise path when a lane that path can
        # actually act on exists: it rewinds a lane from its OWN user gate, so a
        # lane abandoned before ever reaching one has no gate to name.
        # The gate must still be OPEN: `evo decide` refuses a decided gate, so a
        # historical idea_approval row is not something to rewind from.  Without
        # the status test the hint fired in the commonest exhausted-cap state of
        # all - the round's one probe already ran and its gate was approved -
        # and named a command that can only raise.
        revisable = [l for l in opened
                     if any(g.get("kind") == "idea_approval" and g.get("status") == "open"
                            and (g.get("subject") or {}).get("lane") == l.get("id")
                            for g in ctx.st.get("gates", []))]
        if revisable:
            hint = (f". To revise one instead of spending another slot, rewind it from its own user "
                    f"gate: 'evo decide --gate <id> --reject --retry-stage {design_stage}'")
        elif any(g.get("kind") == "idea_approval"
                 and (g.get("subject") or {}).get("lane") in {l.get("id") for l in opened}
                 for g in ctx.st.get("gates", [])):
            # A gate exists but is already decided - saying "never reached its
            # gate" here was factually false in the commonest exhausted state
            # of all (the round's one lane was approved and ran).
            hint = (". This round's lane already had its user gate decided, so there is nothing "
                    "to rewind; declare the next one in the following round's portfolio")
        else:
            hint = (". No lane of this purpose reached its user gate this round, so there is nothing "
                    "to rewind; declare the next one in the following round's portfolio")
        errs.append(f"INJECT_CAP: round {rid} already opened {len(opened)} {purpose} lane(s) "
                    f"(abandoned ones included); budgets.{cap_key}={cap}{hint}")
    # Orthogonal to spend: two undecided lanes of one purpose would queue two
    # manual gates at once for work meant to be answered one question at a time.
    # "Undecided" = anywhere before the user's decision, which INCLUDES status
    # "gate" (the lane is sitting at its open manual gate): excluding it let a
    # second lane open at cap>=2 while the first was still awaiting the user -
    # exactly the two-queued-gates state this check exists to prevent.
    undecided = [l for l in ctx.st.get("lanes", [])
                 if l.get("round") == rid and l.get("experiment_purpose") == purpose
                 and not l.get("node")
                 and str(l.get("status")) not in {"approved", "node_created",
                                                  "done", "abandoned"}]
    if undecided:
        errs.append(f"INJECT_PENDING: round {rid} already has an undecided {purpose} lane "
                    f"({undecided[0].get('id')}); finish or abandon it before opening another")
    return errs


def v_probe_design(ctx: Ctx, task: dict) -> list[str]:
    """A bounded diagnostic probe: one question, one measurement plan, one
    budget cap.  Its protection is the manual user gate right after it."""
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    meta = _read_json(ctx, task["outputs"][1], errs)
    text = _read_md(ctx, task["outputs"][0], errs)
    if meta is None or text is None:
        return errs
    if lane.get("experiment_purpose") != "diagnostic_probe":
        errs.append("PROBE_LANE_PURPOSE: probe_design is legal only for a diagnostic_probe lane")
    if meta.get("idea") != lane.get("idea") or meta.get("lane") != lane.get("id"):
        errs.append("PROBE_ID_BINDING: idea and lane must match the scheduler-assigned ids")
    _nontrivial(meta.get("title"), 8, "probe title", errs)
    if meta.get("experiment_purpose") != "diagnostic_probe":
        errs.append("PROBE_PURPOSE_BINDING: experiment_purpose must be diagnostic_probe")
    if meta.get("level") != 0:
        errs.append("PROBE_LEVEL: level must be 0; a probe makes no innovation-level claim")
    leaked = [k for k in _INSTRUMENTAL_FORBIDDEN_META if k in meta]
    if leaked:
        errs.append(f"PROBE_NOVELTY_FIELDS: a probe must omit candidate-only fields {leaked}")
    if meta.get("metric_bridge_needed") not in (None, False):
        errs.append("PROBE_METRIC_BRIDGE: a probe measures in the existing evaluation space")
    idx = egraph.by_id(ctx.g)
    model_parents = [p for p in lane.get("parents", []) if p in idx and idx[p].get("role") != "platform"]
    if list(meta.get("parents") or []) != model_parents:
        errs.append(f"PROBE_PARENTS: meta.parents must equal the one lane model parent {model_parents}")
    probe = meta.get("probe")
    if not isinstance(probe, dict):
        errs.append("PROBE_SCHEMA: probe design requires a 'probe' object")
        probe = {}
    _nontrivial(probe.get("question"), 40, "probe.question (the ONE thing this answers)", errs)
    _nontrivial(probe.get("measurement_plan"), 60, "probe.measurement_plan (what runs, on what, measured how)", errs)
    _nontrivial(probe.get("decision_impact"), 40, "probe.decision_impact (which future choice the answer changes)", errs)
    budget = probe.get("budget")
    units = set(econfig.resource_limits(ctx.cfg))
    if not isinstance(budget, dict) or not budget:
        errs.append(f"PROBE_BUDGET: probe.budget must cap >= 1 project resource unit from {sorted(units)}")
    else:
        for unit, value in budget.items():
            if unit not in units:
                errs.append(f"PROBE_BUDGET_UNIT: {unit!r} is not a project resource unit ({sorted(units)})")
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)) or float(value) <= 0:
                errs.append(f"PROBE_BUDGET_VALUE: probe.budget[{unit!r}] must be a positive number")
    scope = meta.get("evaluation_scope")
    cell_ids = {str(c.get("id")) for c in econfig.evaluation_cells(ctx.cfg)}
    targets = list((scope or {}).get("target_cells") or []) if isinstance(scope, dict) else []
    if not targets or any(str(t) not in cell_ids for t in targets):
        errs.append(f"PROBE_SCOPE: evaluation_scope.target_cells must name >= 1 configured C# to observe (got {targets})")
    _require_sections(text, ["question", "why now", "measurement plan", "decision impact", "cost"],
                      "PROBE_DESIGN", errs, min_chars=40)
    return errs


def v_maintenance_design(ctx: Ctx, task: dict) -> list[str]:
    """A parity-contracted repair of shared execution code: no novelty claim,
    every decision cell watched, files-in-scope declared before the change."""
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    meta = _read_json(ctx, task["outputs"][1], errs)
    text = _read_md(ctx, task["outputs"][0], errs)
    if meta is None or text is None:
        return errs
    if lane.get("experiment_purpose") != "maintenance":
        errs.append("MAINT_LANE_PURPOSE: maintenance_design is legal only for a maintenance lane")
    if meta.get("idea") != lane.get("idea") or meta.get("lane") != lane.get("id"):
        errs.append("MAINT_ID_BINDING: idea and lane must match the scheduler-assigned ids")
    _nontrivial(meta.get("title"), 8, "maintenance title", errs)
    if meta.get("experiment_purpose") != "maintenance":
        errs.append("MAINT_PURPOSE_BINDING: experiment_purpose must be maintenance")
    if meta.get("level") != 0:
        errs.append("MAINT_LEVEL: level must be 0; maintenance makes no innovation-level claim")
    leaked = [k for k in _INSTRUMENTAL_FORBIDDEN_META if k in meta]
    if leaked:
        errs.append(f"MAINT_NOVELTY_FIELDS: maintenance must omit candidate-only fields {leaked}")
    if meta.get("metric_bridge_needed") not in (None, False):
        errs.append("MAINT_METRIC_BRIDGE: maintenance may not change the output/eval space; "
                    "that would be a semantics change, not a repair")
    idx = egraph.by_id(ctx.g)
    model_parents = [p for p in lane.get("parents", []) if p in idx and idx[p].get("role") != "platform"]
    if list(meta.get("parents") or []) != model_parents:
        errs.append(f"MAINT_PARENTS: meta.parents must equal the one lane model parent {model_parents}")
    mnt = meta.get("maintenance")
    if not isinstance(mnt, dict):
        errs.append("MAINT_SCHEMA: maintenance design requires a 'maintenance' object")
        mnt = {}
    _nontrivial(mnt.get("defect"), 60, "maintenance.defect (the mechanical flaw, not a wish)", errs)
    evidence = mnt.get("defect_evidence")
    if not isinstance(evidence, list) or not evidence \
            or not all(str(x or "").strip() for x in evidence):
        errs.append("MAINT_EVIDENCE: maintenance.defect_evidence must cite >= 1 concrete pointer "
                    "(ER###/OB###/N### id or a repo path)")
    else:
        # R11-015: a ledger id is only evidence while the ledger stands behind
        # it. A repair justified by a superseded/retracted observation (its
        # source node was re-concluded) or by a nonexistent id used to pass as
        # a bare string - the design froze withdrawn knowledge as its
        # justification and nothing downstream re-parsed it.
        all_obs = {str(r.get("id")) for r in ctx.store.observations(ctx.st)}
        active_obs = {str(r.get("id")) for r in ctx.store.observations(ctx.st, active_only=True)}
        known_errors = {str(r.get("id")) for r in ctx.store.errors(ctx.st)}
        for x in evidence:
            ref = str(x or "").strip()
            if re.fullmatch(r"OB\d+", ref):
                if ref not in all_obs:
                    errs.append(f"MAINT_EVIDENCE_UNKNOWN: defect_evidence cites {ref}, which is not in "
                                "the observation ledger - cite a real OB id or a repo path")
                elif ref not in active_obs:
                    errs.append(f"MAINT_EVIDENCE_STALE: defect_evidence cites {ref}, which is no longer "
                                "active (superseded or retracted) - re-ground the defect in a live "
                                "observation before repairing on withdrawn knowledge")
            elif re.fullmatch(r"ER\d+", ref) and ref not in known_errors:
                errs.append(f"MAINT_EVIDENCE_UNKNOWN: defect_evidence cites {ref}, which is not in "
                            "the error ledger - cite a real ER id or a repo path")
    boundary = mnt.get("change_boundary") if isinstance(mnt.get("change_boundary"), dict) else {}
    files = boundary.get("files_in_scope")
    if not isinstance(files, list) or not files \
            or not all(isinstance(f, str) and f.strip() for f in files):
        errs.append("MAINT_BOUNDARY: change_boundary.files_in_scope must list the exact files this repair may touch")
    if boundary.get("semantic_intent") != "preserve":
        errs.append("MAINT_INTENT: change_boundary.semantic_intent must be the literal 'preserve'; "
                    "a semantics-changing fix is a candidate, not maintenance")
    _nontrivial(mnt.get("expected_unblock"), 40,
                "maintenance.expected_unblock (what later work this repair lets express itself)", errs)
    parity = mnt.get("parity_contract")
    if not isinstance(parity, dict) or parity.get("cells") != "all_decision" \
            or parity.get("standard") != "noninferior":
        errs.append('MAINT_PARITY: parity_contract must be exactly {"cells": "all_decision", '
                    '"standard": "noninferior"} - the engine settles it over every claim target and '
                    "guardrail; a narrower parity would let a repair quietly regress unwatched cells")
    _require_sections(text, ["defect", "evidence", "change boundary", "parity argument",
                             "unblock rationale", "risks"],
                      "MAINT_DESIGN", errs, min_chars=60)
    return errs


def v_maintenance_review(ctx: Ctx, task: dict) -> list[str]:
    """Adversarial audit: is this really maintenance, or novelty in overalls?"""
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    review = _read_md(ctx, task["outputs"][0], errs)
    _, design = _load_idea(ctx, lane, errs)
    if review is None or design is None:
        return errs
    verdicts = ("ACCEPT", "REVISE", "REJECT_NOT_MAINTENANCE",
                "REJECT_SEMANTIC_CHANGE", "REJECT_NOT_WORTH_COST")
    m = re.search(r"^VERDICT:\s*(\S+)", review, re.M)
    if not m or m.group(1) not in verdicts:
        errs.append(f"MAINT_REVIEW_VERDICT: review must start VERDICT: {'|'.join(verdicts)}")
    _require_sections(review, ["novelty smuggling audit", "parity risk audit",
                               "cheaper alternative audit", "boundary audit", "verdict rationale"],
                      "MAINT_REVIEW", errs, min_chars=60)
    _check_quotes(QUOTE_LINE.findall(review), design, "MAINT_REVIEW", errs, min_quotes=2)
    if m and m.group(1) == "ACCEPT":
        risk = eutil.find_section(eutil.md_sections(review), "strongest surviving risk")
        if not risk or len(risk.strip()) < 60:
            errs.append("MAINT_REVIEW_RISK: ACCEPT requires a substantive Strongest surviving risk section")
    return errs


def v_design_ablation(ctx: Ctx, task: dict) -> list[str]:
    """Validate the dedicated, non-novelty path for one causal diagnostic."""
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    meta = _read_json(ctx, task["outputs"][1], errs)
    text = _read_md(ctx, task["outputs"][0], errs)
    if meta is None or text is None:
        return errs
    if lane.get("experiment_purpose") != "targeted_ablation":
        errs.append("ABLATION_LANE_PURPOSE: design_ablation is legal only for a targeted_ablation lane")
    if meta.get("idea") != lane.get("idea") or meta.get("lane") != lane.get("id"):
        errs.append("ABLATION_ID_BINDING: idea and lane must match the scheduler-assigned ids")
    _nontrivial(meta.get("title"), 8, "ablation title", errs)
    if meta.get("experiment_purpose") != "targeted_ablation":
        errs.append("ABLATION_PURPOSE_BINDING: experiment_purpose must be targeted_ablation")
    if meta.get("level") != 0:
        errs.append("ABLATION_LEVEL: level must be 0 because this node makes no innovation-level claim")
    novelty_fields = (
        "change_scope", "program", "novelty", "effect_case", "theory_role", "theory_target",
        "program_digest", "kernel_hash", "kernel_ids", "sketch_id", "diagnosis_digest",
        "hypothesis_ids", "prior_art_card_ids", "nearest_published", "sota_targets",
        "siblings_distance", "claim_scope",
    )
    leaked = [k for k in novelty_fields if k in meta]
    if leaked:
        errs.append(f"ABLATION_NOVELTY_FIELDS: targeted diagnostics must omit candidate-only fields {leaked}")
    idx = egraph.by_id(ctx.g)
    model_parents = [p for p in lane.get("parents", []) if p in idx and idx[p].get("role") != "platform"]
    platform_parents = [p for p in lane.get("parents", []) if p in idx and idx[p].get("role") == "platform"]
    if list(meta.get("parents") or []) != model_parents:
        errs.append(f"ABLATION_PARENTS: meta.parents must equal the one lane model parent {model_parents}")
    consumed = meta.get("platforms_consumed") or []
    if not isinstance(consumed, list) or len(set(consumed)) != len(consumed) or any(p not in platform_parents for p in consumed):
        errs.append("ABLATION_PLATFORMS: platforms_consumed must be a unique subset of lane platform parents")
    ablation = _ablation_contract_errors(ctx, lane, meta, errs)

    cells = econfig.cell_spec(ctx.cfg)
    global_targets = {str(c.get("id")) for c in econfig.target_cells(ctx.cfg)}
    scope = meta.get("evaluation_scope")
    if not isinstance(scope, dict):
        errs.append("ABLATION_EVALUATION_SCOPE: evaluation_scope object required")
        scope = {}
    targets = scope.get("target_cells")
    if not isinstance(targets, list) or not targets or len(set(targets)) != len(targets) \
            or any(cid not in global_targets for cid in targets):
        errs.append("ABLATION_EVALUATION_TARGETS: target_cells must be a unique non-empty subset of project target C# cells")
        targets = []
    guards = scope.get("guardrail_cells") or []
    if not isinstance(guards, list) or len(set(guards)) != len(guards) or any(
            cid not in cells or cells[cid].get("role") != "guardrail" for cid in guards):
        errs.append("ABLATION_EVALUATION_GUARDS: guardrail_cells must be unique project guardrail C# cells")
    _nontrivial(scope.get("rationale"), 60,
                "evaluation_scope.rationale (why these cells answer the causal question)", errs)
    preds = meta.get("predictions")
    rspec = econfig.result_spec(ctx.cfg)
    if not isinstance(preds, list) or not (1 <= len(preds) <= 3):
        errs.append("ABLATION_PREDICTIONS_COUNT: targeted ablation needs 1..3 numeric predictions, not a sweep")
        preds = []
    pids: set[str] = set()
    for pred in preds:
        pid = str((pred or {}).get("id") or "")
        if not re.fullmatch(r"P\d+", pid) or pid in pids:
            errs.append(f"ABLATION_PREDICTION_ID: prediction ids must be unique P# (got {pid!r})")
        pids.add(pid)
        if (pred or {}).get("metric") not in rspec:
            errs.append(f"ABLATION_PREDICTION_METRIC: {pid}: metric must be an evaluation result_key")
        if (pred or {}).get("comparison") not in (">=", "<="):
            errs.append(f"ABLATION_PREDICTION_CMP: {pid}: comparison must be >= or <=")
        if not isinstance((pred or {}).get("value"), (int, float)) or isinstance((pred or {}).get("value"), bool):
            errs.append(f"ABLATION_PREDICTION_VALUE: {pid}: numeric value required")
        _nontrivial((pred or {}).get("rationale"), 40, f"prediction {pid}.rationale", errs)
    target_keys = {str((cells.get(cid) or {}).get("result_key") or "") for cid in targets}
    if preds and not any((p or {}).get("metric") in target_keys for p in preds):
        errs.append("ABLATION_PREDICTION_SCOPE: at least one prediction must test an evaluation_scope target cell")
    if meta.get("metric_bridge_needed") is not False:
        errs.append("ABLATION_METRIC_BRIDGE: metric_bridge_needed must be false; changing the output/eval space "
                    "would destroy the controlled comparison")
    if meta.get("assumptions") not in (None, []):
        errs.append("ABLATION_ASSUMPTIONS: X1/X2 are the causal hypotheses; do not add a second generic assumption theory")
    _require_sections(text, ["causal question", "parent evidence", "controlled intervention",
                             "decision map", "evaluation and cost", "risks"],
                      "ABLATION_DESIGN", errs, min_chars=60)
    for token in [str((ablation or {}).get("parent") or ""), "X1", "X2"]:
        if token and token not in text:
            errs.append(f"ABLATION_TEXT_BINDING: ABLATION_DESIGN must explicitly discuss {token}")
    return errs


def v_review_ablation(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    review = _read_md(ctx, task["outputs"][0], errs)
    _, design = _load_idea(ctx, lane, errs)
    if review is None or design is None:
        return errs
    verdicts = ("ACCEPT", "REVISE", "REJECT_NOT_CAUSAL", "REJECT_NOT_WORTH_COST", "REJECT_INFEASIBLE")
    m = re.search(r"^VERDICT:\s*(\S+)", review, re.M)
    if not m or m.group(1) not in verdicts:
        errs.append(f"ABLATION_REVIEW_VERDICT: review must start VERDICT: {'|'.join(verdicts)}")
    _require_sections(review, ["causal identifiability", "single-change audit", "cheaper evidence audit",
                               "decision value", "cost audit", "verdict rationale"],
                      "ABLATION_REVIEW", errs, min_chars=60)
    _check_quotes(QUOTE_LINE.findall(review), design, "ABLATION_REVIEW", errs, min_quotes=2)
    if m and m.group(1) == "ACCEPT":
        risk = eutil.find_section(eutil.md_sections(review), "strongest surviving risk")
        if not risk or len(risk.strip()) < 60:
            errs.append("ABLATION_REVIEW_RISK: ACCEPT requires a substantive Strongest surviving risk section")
    return errs


def v_mature(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    purpose = econfig.lane_purpose(lane)
    if purpose in econfig.INSTRUMENTAL_PURPOSES:
        # A typed refusal for EVERY instrumental purpose: a probe/maintenance
        # lane mis-parked in the candidate pipeline (the corruption
        # LANE_ROUTE_STATUS exists to catch) used to fall through and fail
        # deep inside winner/tournament machinery with unrelated noise.
        route = " -> ".join(eflow.INSTRUMENTAL_SEQ.get(purpose) or ())
        return [f"IDEA_INSTRUMENTAL_PIPELINE: a {purpose} lane uses its own route ({route}), "
                "not the candidate novelty/maturation pipeline"]
    meta = _read_json(ctx, task["outputs"][1], errs)
    md = _read_md(ctx, task["outputs"][0], errs)
    if meta is None or md is None:
        return errs
    legacy = sorted({"delta_descriptor", "primary_dimension", "move", "move_fit",
                     "mech_card_ids", "reframe", "principle"} & set(meta))
    if legacy:
        errs.append(f"IDEA_LEGACY_FIELDS: schema-v2 mature meta must omit legacy idea fields {legacy}")
    bud = ctx.cfg.get("budgets", {})
    rspec = econfig.result_spec(ctx.cfg)
    idx = egraph.by_id(ctx.g)
    # The mature contract expands but may not redesign the tournament winner.
    # Program, irreducible kernel and effect path are copied exactly and bound
    # by digest, preventing a persuasive mature narrative from drifting.
    winner = ctx.winner_sketch(lane) or {}
    research_kernel = str((winner.get("novelty") or {}).get("kind") or "") in eprogram.RESEARCH_NOVELTY
    copied_fields = ["change_scope", "program", "novelty"]
    if lane.get("intent") != "platform":
        copied_fields.extend(("effect_case", "claim_scope"))
    for field in copied_fields:
        if meta.get(field) != winner.get(field):
            errs.append(f"IDEA_PROGRAM_DRIFT: meta.{field} must exactly copy the winning program")
    if lane.get("theory_downgraded"):
        if meta.get("theory_role") != "none" or any(
                key in meta for key in ("theory_target", "theory_rigor", "theory_obligations",
                                        "theory_doc", "problem_doc")):
            errs.append("IDEA_THEORY_DOWNGRADE: failed optional T must mature as theory_role=none and omit theory-only bindings")
        audit = meta.get("theory_audit") or {}
        if audit.get("status") != "failed" or audit.get("theory_doc") != lane.get("theory_path"):
            errs.append("IDEA_THEORY_AUDIT: downgraded T needs theory_audit.status=failed bound to the rejected theory document")
        _nontrivial(audit.get("reason"), 60, "theory_audit.reason", errs)
    else:
        for field in ("theory_role", "theory_rigor", "theory_obligations"):
            if meta.get(field) != winner.get(field):
                errs.append(f"IDEA_PROGRAM_DRIFT: meta.{field} must exactly copy the winner's independent T declaration")
        if winner.get("theory_role") != "none" and meta.get("theory_target") != winner.get("theory_target"):
            errs.append("IDEA_THEORY_TARGET_DRIFT: theory_target changed after tournament")
    if meta.get("program_digest") != lane.get("winner_program_digest") or \
            eprogram.candidate_digest(winner) != lane.get("winner_program_digest"):
        errs.append("IDEA_PROGRAM_DIGEST: meta/program state must bind the exact tournament winner")
    if meta.get("kernel_hash") != lane.get("winner_kernel_hash"):
        errs.append("IDEA_KERNEL_HASH: meta.kernel_hash must bind the winner's irreducible core")
    lv = eprogram.compute_level(meta)
    if meta.get("level") != lv:
        errs.append(f"IDEA_LEVEL_MISMATCH: meta.level={meta.get('level')} but change_scope computes L{lv}")
    if lv < lane_min_level(lane):
        errs.append(f"IDEA_UNDER_LEVEL: computed L{lv} < lane min_level L{lane.get('min_level')}")
    # winner linkage
    if meta.get("sketch_id") != lane.get("winner_sketch"):
        errs.append(f"IDEA_SKETCH_LINK: meta.sketch_id must be the tournament winner {lane.get('winner_sketch')!r}")
    if lane.get("search_origin") == "repair":
        if meta.get("diagnosis_digest") != lane.get("diagnosis_digest"):
            errs.append("IDEA_DIAGNOSIS_BINDING: repair idea must bind the frozen diagnosis digest")
        if json_file_digest(ctx, lane.get("diagnosis_path") or "") != lane.get("diagnosis_digest"):
            errs.append("DIAGNOSIS_MUTATED: frozen repair diagnosis changed before maturation")
        diagnosis = eutil.read_json(eutil.rpath(ctx.store.repo, lane.get("diagnosis_path") or ""), {}) or {}
        dhids = {str(h.get("id")) for h in (diagnosis.get("hypotheses") or []) if isinstance(h, dict)}
        idea_hids = meta.get("hypothesis_ids")
        if not isinstance(idea_hids, list) or not idea_hids or any(h not in dhids for h in idea_hids):
            errs.append("IDEA_HYPOTHESIS_BINDING: repair hypothesis_ids must resolve to frozen H# ids")
    else:
        for field in ("diagnosis_digest", "hypothesis_ids", "move"):
            if field in meta:
                errs.append(f"IDEA_ROUTE_FIELD: constructive/theory-derived meta must omit repair-only {field}")

    purpose = str(meta.get("experiment_purpose") or "")
    # v11.1 P5 (R1 fix): exploratory rides the full candidate pipeline through
    # this very task, so the two checks below were jointly unsatisfiable for it
    # (meta='exploratory' tripped the first, meta='candidate' tripped the
    # binding) - the tier died at its own maturation door.
    if purpose not in ("candidate", "exploratory"):
        errs.append("IDEA_EXPERIMENT_PURPOSE: the mature task is only for candidate/exploratory ideas")
    if purpose != str(lane.get("experiment_purpose") or ""):
        errs.append("IDEA_EXPERIMENT_PURPOSE_BINDING: meta.experiment_purpose must equal the purpose frozen in "
                    "the round portfolio")
    if meta.get("ablation") is not None:
        errs.append("IDEA_ABLATION_UNDECLARED: candidate ideas must omit ablation; targeted diagnostics use "
                    "the dedicated design_ablation path")

    # Claim scope makes partial wins honest. Generalist, specialist and
    # efficiency claims are different scientific statements; none is reduced
    # to a hidden weighted average.
    cells = econfig.cell_spec(ctx.cfg)
    global_targets = {str(c.get("id")) for c in econfig.target_cells(ctx.cfg)}
    scope = meta.get("claim_scope") or {}
    kind = str(scope.get("kind") or "")
    claim_targets: list[str] = []
    if lane.get("intent") == "platform":
        if scope:
            errs.append("IDEA_PLATFORM_CLAIM_SCOPE: platform nodes enable later experiments; omit model-performance claim_scope")
    else:
        if kind not in econfig.CLAIM_KINDS:
            errs.append(f"IDEA_CLAIM_KIND: claim_scope.kind must be one of {econfig.CLAIM_KINDS}")
        raw_targets = scope.get("target_cells")
        if not isinstance(raw_targets, list) or not raw_targets or len(set(raw_targets)) != len(raw_targets) \
                or any(t not in global_targets for t in raw_targets):
            errs.append("IDEA_CLAIM_TARGETS: claim_scope.target_cells must be a unique non-empty subset of contract target C# cells")
        else:
            claim_targets = [str(t) for t in raw_targets]
        if kind == "generalist" and set(claim_targets) != global_targets:
            errs.append("IDEA_CLAIM_GENERALIST: a generalist claim must target every contract target cell; use specialist for an honest subset claim")
        if kind == "specialist":
            if not (ctx.cfg.get("evaluation_contract", {}).get("decision") or {}).get("allow_specialist", True):
                errs.append("IDEA_CLAIM_SPECIALIST_DISABLED: the user did not allow specialist success")
            if set(claim_targets) == global_targets:
                errs.append("IDEA_CLAIM_SPECIALIST_SCOPE: specialist must target a strict subset; all targets is a generalist claim")
        required_targets = {cid for cid in global_targets if (cells.get(cid) or {}).get("required")}
        omitted_required = sorted(required_targets - set(claim_targets))
        if omitted_required:
            errs.append(f"IDEA_CLAIM_REQUIRED_TARGETS: required target cells {omitted_required} cannot be scoped away; "
                        "they need only remain non-inferior unless the contract separately requires improvement")
        if kind == "efficiency":
            improvement_cells = scope.get("improvement_cells")
            parity_cells = scope.get("parity_cells")
            for name, values in (("improvement_cells", improvement_cells), ("parity_cells", parity_cells)):
                # R5: improvement_cells may be [] (parity-only efficiency);
                # parity_cells stays non-empty - with nothing held at parity
                # the claim is not an efficiency claim at all.
                required_nonempty = name == "parity_cells"
                if not isinstance(values, list) or (required_nonempty and not values) \
                        or len(set(values)) != len(values) \
                        or any(cid not in claim_targets for cid in values):
                    errs.append(f"IDEA_CLAIM_EFFICIENCY_{name.upper()}: {name} must be a unique "
                                f"{'non-empty ' if required_nonempty else ''}subset of target_cells"
                                + ("" if required_nonempty else " ([] = parity-only efficiency claim)"))
            if isinstance(improvement_cells, list) and isinstance(parity_cells, list):
                if set(improvement_cells) & set(parity_cells):
                    errs.append("IDEA_CLAIM_EFFICIENCY_OVERLAP: improvement_cells and parity_cells must be disjoint")
                if set(improvement_cells) | set(parity_cells) != set(claim_targets):
                    errs.append("IDEA_CLAIM_EFFICIENCY_COVERAGE: improvement_cells + parity_cells must partition target_cells")
        guards = scope.get("guardrail_cells") or []
        if not isinstance(guards, list) or len(set(guards)) != len(guards) or any(
                g not in cells or cells[g].get("role") != "guardrail" for g in guards):
            errs.append("IDEA_CLAIM_GUARDRAILS: guardrail_cells must be unique contract guardrail C# ids")
        _nontrivial(scope.get("rationale"), 60,
                    "claim_scope.rationale (why this breadth is the honest claim before seeing results)", errs)
    my_sig = str(meta.get("kernel_hash") or "")
    _contracts, hard_kernels = historical_program_blocks(
        ctx, ignore_idea=str(lane.get("idea") or ""))
    confirm_kernels, _ck = _kernel_carbon_copy_target(ctx, lane.get("confirmatory_of"))
    if my_sig and my_sig in hard_kernels \
            and not (confirm_kernels and my_sig in confirm_kernels) \
            and not lane.get("scaling_followup_of"):
        # v11.1 (R1 fix): a confirmatory lane EXISTS to re-run its declared
        # scout's kernel under full rigor - that one duplication is the point.
        # (final audit C24): scaling follow-up lanes are likewise exempt - the
        # sketch-level carbon-copy check pins their kernel to the parent's, so
        # a hard disposition of their own earlier attempt must not wedge the
        # mandated resubmission.
        errs.append(f"IDEA_GLOBAL_DUP: this exact frozen kernel already has an implemented, active, or "
                    f"explicitly core-rejected disposition at {hard_kernels[my_sig]}; changing citations or "
                    "support modules does not make that frozen core new")
    # Theory linkage follows the candidate's independent T axis.
    if _needs_theory(lane):
        if meta.get("theory_doc") != lane.get("theory_path"):
            errs.append(f"IDEA_THEORY_LINK: meta.theory_doc must be the surviving theory {lane.get('theory_path')!r} "
                        f"(got {meta.get('theory_doc')!r}) - the idea formalizes the theory that survived challenge")
    # formal-ladder linkage (v8): the idea inherits the posed problem
    if lane.get("formal"):
        if meta.get("problem_doc") != lane.get("problem_path"):
            errs.append(f"IDEA_PROBLEM_LINK: meta.problem_doc must be the posed problem "
                        f"{lane.get('problem_path')!r} (got {meta.get('problem_doc')!r})")
    # SOTA binding follows the M/E research claim, not implementation breadth.
    # The tournament already selected the frontier references; maturation may
    # explain them but cannot choose a friendlier target after the winner.
    if econfig.sota_enabled(ctx.cfg) and ctx.is_research() and research_kernel \
            and lane.get("intent") != "platform" \
            and lane.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES:
        targets = meta.get("sota_targets") or []
        tournament = eutil.read_json(eutil.rpath(ctx.store.repo, lane.get("tournament_path") or ""), {}) or {}
        winner_audit = next((a for a in (tournament.get("audits") or [])
                             if (a or {}).get("sketch_id") == lane.get("winner_sketch")), {})
        frozen_refs = set(((winner_audit.get("effect") or {}).get("frontier_refs") or []))
        if {str((t or {}).get("sota") or "") for t in targets} != frozen_refs:
            errs.append(f"IDEA_SOTA_DRIFT: sota_targets must exactly explain tournament frontier_refs {sorted(frozen_refs)}")
        sids = ctx.sota_ids()
        sota_by_id = {str(r.get("id")): r for r in ctx.sota_rows()}
        okc = 0
        for t in targets:
            tid = str((t or {}).get("sota") or "")
            if tid not in sids:
                errs.append(f"IDEA_SOTA_TARGET: sota_targets entry {tid!r} not in SOTA.jsonl")
                continue
            cid = str(t.get("cell") or "")
            if cid not in claim_targets:
                errs.append(f"IDEA_SOTA_CELL: target {tid}: cell must be one of the idea's claim_scope.target_cells")
            if str((sota_by_id.get(tid) or {}).get("cell") or "") != cid:
                errs.append(f"IDEA_SOTA_CELL_MISMATCH: target {tid}: cell must match the SOTA library entry's C# binding")
            if str(t.get("dimension") or "") not in ("effect", "efficiency", "modeling", "generality"):
                errs.append(f"IDEA_SOTA_DIMENSION: target {tid}: dimension must be "
                            f"effect|efficiency|modeling|generality - name the axis you beat them on")
            # v11 front-shift: conclude has ALWAYS refused 'met' for a non-exact
            # protocol comparison (OUTCOME_SOTA_NONCOMPARABLE) - but that fired
            # AFTER training, although the comparability field sat in the SOTA
            # library at registration time. A doomed claim now dies here,
            # before any compute, with the same quality bar. R7: conclude's
            # refusal is dimension-blind (every non-exact row is barred from
            # 'met'), so the front-shift must be too - the old effect-only
            # check even ADVISED "claim a different dimension", steering the
            # agent into a wall it would hit after full training.
            if str((sota_by_id.get(tid) or {}).get("comparability") or "") not in ("", "exact"):
                errs.append(f"IDEA_SOTA_NONCOMPARABLE: target {tid}: its SOTA entry is marked "
                            f"comparability={str((sota_by_id.get(tid) or {}).get('comparability'))!r}; a "
                            "claim against a non-exact protocol can never settle 'met' at conclude "
                            "(any dimension) - pick an exact-comparability entry NOW instead of "
                            "after training")
            if len(str(t.get("claim") or "").strip()) < 60:
                errs.append(f"IDEA_SOTA_CLAIM: target {tid}: claim needs >= 60 chars - what concretely "
                            f"will be better than this published result, and why the mechanism delivers it")
            okc += 1
        if okc < 1:
            errs.append("IDEA_SOTA_TARGET: research mode with the SOTA library requires >= 1 resolving "
                        "sota_targets entry for a research kernel - an idea that cannot name whom it beats is not "
                        "aiming at the frontier")
    if lane.get("experiment_purpose") in econfig.EXPLORATORY_PURPOSES:
        # v11.1 P5 (doors-drive + final-audit fixes): a scout must not carry
        # forward-commitment machinery of ANY kind - beat-claims flow into
        # conclude settlement, predictions get verdicted, a scaling plan's
        # follow-up door demands the scout as model parent (which scouts can
        # never be), and a repeat rule spends real training on an
        # observations-only number. The cards already order all four omitted;
        # the validator now enforces what the cards teach.
        for fld, why in (("sota_targets", "its results are observations, not claims; the confirmatory "
                                          "re-run carries the beat-claims"),
                         ("predictions", "numeric foresight is exactly what this tier waives; the "
                                         "confirmatory re-run registers the predictions"),
                         ("scaling", "a scaling follow-up needs its registrant as model parent, which an "
                                     "observations-only scout can never be - register scaling on the "
                                     "confirmatory candidate instead"),
                         ("repeat_rule", "a bought-back repeat spends training on a number that can never "
                                         "hold a record - repeat the CONFIRMATORY run instead")):
            if meta.get(fld):
                errs.append(f"IDEA_EXPLORATORY_{fld.upper().replace('_TARGETS', '').replace('_RULE', '')}: "
                            f"an exploratory idea registers NO {fld} - {why}")
    # Attribution is mandatory for novel mechanisms, independently of theory.
    research_kernel = str((meta.get("novelty") or {}).get("kind") or "") in eprogram.RESEARCH_NOVELTY
    # Probe SHAPE and the waiver/probe mutual exclusion are universal: any idea
    # that registers a probe registers a valid one (the drifted v9.2 predicates
    # let an engineering probe with mode='bogus' or no signal slip through and
    # then diverge downstream). The probe REQUIREMENT stays research-only below.
    if meta.get("mechanism_probe") is not None:
        if not isinstance(meta.get("mechanism_probe"), dict):
            errs.append("IDEA_PROBE_SHAPE: mechanism_probe must be an object")
        else:
            if meta["mechanism_probe"].get("mode") not in econfig.PROBE_MODES:
                errs.append(f"IDEA_PROBE_MODE: mechanism_probe.mode must be one of {econfig.PROBE_MODES}")
            _nontrivial(meta["mechanism_probe"].get("signal"), 30,
                        "mechanism_probe.signal (the measurable INTERMEDIATE)", errs)
            # v12 self-review: the seed-template cross-check is UNIVERSAL like
            # the shape checks above - a scout's voluntary probe or an
            # engineering-mode probe hits the same plan-layer template rules,
            # so admitting '{seed}' here only for research candidates would
            # recreate the seal-admits/plan-vetoes pair for everyone else.
            errs.extend(idea_probe_seed_template_errors(
                ctx.cfg, meta["mechanism_probe"],
                purpose=str(lane.get("experiment_purpose") or ""),
                intent=str(lane.get("intent") or "")))
    if str(meta.get("attribution_waiver") or "").strip() and meta.get("mechanism_probe"):
        errs.append("IDEA_WAIVER_PROBE_CONFLICT: an attribution_waiver and a mechanism_probe "
                    "are mutually exclusive - the waiver argues no measurable signal exists, "
                    "the probe registers one; keep exactly one")
    if research_kernel and lane.get("intent") != "platform" \
            and lane.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES:
        # v11.1 P5 (doors-drive fix): the probe/waiver duty exists to license
        # scientific promotion; a scout's promotion is pinned not_applicable,
        # so demanding pre-registered probe machinery from it is the same
        # manufactured-foresight ceremony the tier exists to remove. A scout
        # MAY still register a probe; it is never forced to.
        mp = meta.get("mechanism_probe") or {}
        waiver = str(meta.get("attribution_waiver") or "").strip()
        if waiver:
            if len(waiver) < 40:
                errs.append("IDEA_ATTRIBUTION_WAIVER: attribution_waiver needs >= 40 chars - why no "
                            "measurable intermediate signal exists for this mechanism")
        else:
            _nontrivial(mp.get("signal"), 30, "mechanism_probe.signal (the measurable INTERMEDIATE the "
                        "mechanism must move - an attention statistic, a rate, a curve feature - not the "
                        "declared target result itself)", errs)
            _nontrivial(mp.get("expect"), 15, "mechanism_probe.expect (which way it moves if the mechanism is real)", errs)
            mode = str(mp.get("mode") or "")
            if mode not in econfig.PROBE_MODES:
                errs.append(f"IDEA_PROBE_MODE: mechanism_probe.mode must be one of {econfig.PROBE_MODES}")
            arms = mp.get("extra_eval_arms")
            cap = int((ctx.cfg.get("evidence_policy") or {}).get("max_extra_eval_arms_per_node", 0))
            if not isinstance(arms, int) or arms < 0 or arms > cap:
                errs.append(f"IDEA_PROBE_EVAL_ARMS: extra_eval_arms must be an integer 0..{cap}")
            if mode == "eval_intervention" and arms != 1:
                errs.append("IDEA_PROBE_EVAL_ARM_REQUIRED: eval_intervention is exactly one cheap eval-only "
                            "arm; use same_run/existing_artifact when zero arms are needed")
            if mode != "eval_intervention" and arms != 0:
                errs.append(f"IDEA_PROBE_MODE_ARMS: mode={mode!r} may not add eval arms; only eval_intervention can use the configured cheap-eval allowance")
            errs.extend(_probe_path_errors(mp.get("artifact"), "mechanism_probe.artifact"))
            fields = mp.get("required_fields")
            if not isinstance(fields, list) or not (1 <= len(fields) <= 5):
                errs.append("IDEA_PROBE_FIELDS: mechanism_probe.required_fields must contain 1..5 numeric JSON keys")
                fields = []
            seen_fields: set[str] = set()
            for i, field in enumerate(fields):
                name = str(field or "")
                if not STAGE_METRIC_KEY.fullmatch(name):
                    errs.append(f"IDEA_PROBE_FIELD: required_fields[{i}] must be a metric-key slug")
                elif name in seen_fields:
                    errs.append(f"IDEA_PROBE_FIELD_DUP: required field {name!r} repeats")
                seen_fields.add(name)
            rule = mp.get("decision_rule")
            if not isinstance(rule, dict):
                errs.append("IDEA_PROBE_DECISION_RULE: mechanism_probe.decision_rule must freeze a numeric predicate")
                rule = {}
            allowed_rule_fields = ({"field", "aggregation", "comparison", "threshold"}
                                   if rule.get("comparison") in (">=", "<=") else
                                   {"field", "aggregation", "comparison", "lower", "upper"})
            if set(rule) != allowed_rule_fields:
                errs.append(f"IDEA_PROBE_DECISION_RULE_FIELDS: decision_rule must use exactly "
                            f"{sorted(allowed_rule_fields)}")
            if rule.get("field") not in seen_fields:
                errs.append("IDEA_PROBE_DECISION_FIELD: decision_rule.field must name one required numeric field")
            if rule.get("aggregation") not in ("mean", "median", "min", "max"):
                errs.append("IDEA_PROBE_DECISION_AGGREGATION: decision_rule.aggregation must be mean|median|min|max")
            comparison = rule.get("comparison")
            if comparison not in (">=", "<=", "between"):
                errs.append("IDEA_PROBE_DECISION_COMPARISON: decision_rule.comparison must be >=|<=|between")
            if comparison in (">=", "<="):
                threshold = rule.get("threshold")
                if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) \
                        or not math.isfinite(float(threshold)):
                    errs.append("IDEA_PROBE_DECISION_THRESHOLD: decision_rule.threshold must be finite")
            elif comparison == "between":
                lower, upper = rule.get("lower"), rule.get("upper")
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v))
                       for v in (lower, upper)) or (isinstance(lower, (int, float)) and
                                                    isinstance(upper, (int, float)) and lower >= upper):
                    errs.append("IDEA_PROBE_DECISION_INTERVAL: decision_rule needs finite lower < upper")
            if mode == "existing_artifact" and not _probe_path_errors(mp.get("artifact"), "mechanism_probe.artifact"):
                errs.extend(probe_artifact_errors(ctx, str(mp.get("artifact") or ""), fields,
                                                  where="registered existing-artifact probe"))
            _nontrivial(mp.get("decision"), 50, "mechanism_probe.decision (which later DAG choice changes)", errs)
            _nontrivial(mp.get("value_of_information"), 60,
                        "mechanism_probe.value_of_information (why this signal can change a decision)", errs)
            if mode in econfig.PROBE_MODES:
                order = list((ctx.cfg.get("evidence_policy") or {}).get("probe_mode_order") or econfig.PROBE_MODES)
                earlier = order[:order.index(mode)] if mode in order else []
                rejected = {str((x or {}).get("mode")): str((x or {}).get("reason") or "")
                            for x in (mp.get("cheaper_modes_rejected") or []) if isinstance(x, dict)}
                for cheaper in earlier:
                    if len(rejected.get(cheaper, "").strip()) < 30:
                        errs.append(f"IDEA_PROBE_CHEAPER_MODE: choosing {mode} requires a >=30-char reason why cheaper mode {cheaper} cannot answer the question")
    dom = meta.get("dominance")
    if kind == "efficiency" and dom is None and (scope.get("improvement_cells") or []):
        # R5: a parity-only efficiency claim has no quality cell to threshold;
        # its win is settled by the resource regime's improvement_axes.
        errs.append("IDEA_DOMINANCE_REQUIRED: efficiency claims with quality improvement_cells need "
                    "an absolute pre-registered dominance threshold")
    if dom is not None:
        dm = str((dom or {}).get("metric") or "")
        if dm not in rspec:
            errs.append(f"IDEA_DOMINANCE_METRIC: dominance.metric must be an evaluation-contract result_key (got {dm!r})")
        elif kind != "efficiency":
            errs.append("IDEA_DOMINANCE_KIND: dominance is only meaningful with claim_scope.kind='efficiency'")
        else:
            improvement_keys = {str((cells.get(cid) or {}).get("result_key") or "")
                                for cid in (scope.get("improvement_cells") or [])}
            if dm not in improvement_keys:
                errs.append("IDEA_DOMINANCE_AXIS: dominance.metric must belong to claim_scope.improvement_cells")
        if (dom or {}).get("comparison") not in (">=", "<="):
            errs.append("IDEA_DOMINANCE_CMP: dominance.comparison must be '>=' or '<='")
        elif dm in rspec:
            expected_cmp = ">=" if econfig.result_direction(ctx.cfg, dm) == "max" else "<="
            if (dom or {}).get("comparison") != expected_cmp:
                errs.append(f"IDEA_DOMINANCE_DIRECTION: {dm} is optimized in direction "
                            f"{econfig.result_direction(ctx.cfg, dm)!r}; comparison must be {expected_cmp!r}")
        dval = (dom or {}).get("value")
        if isinstance(dval, bool) or not isinstance(dval, (int, float)) \
                or not math.isfinite(float(dval)):
            errs.append("IDEA_DOMINANCE_VALUE: dominance.value must be a pre-registered finite number, not a direction")
        _nontrivial((dom or {}).get("rationale"), 30, "dominance.rationale", errs)
    scaling_mode = econfig.scaling_mode(ctx.cfg)
    sc = meta.get("scaling")
    if sc is not None and scaling_mode == "off":
        errs.append("IDEA_SCALING_OFF: scaling_mode=off; do not silently add scaling work to this node")
    if sc is not None and scaling_mode != "off":
        sc = sc or {}
        if str(sc.get("axis") or "") not in ("data", "model", "compute"):
            errs.append("IDEA_SCALING_AXIS: scaling.axis must be data|model|compute")
        pts = sc.get("points") or []
        if not (isinstance(pts, list) and len(pts) >= 2 and all(str(p or "").strip() for p in pts)):
            errs.append("IDEA_SCALING_POINTS: scaling.points needs >= 2 named scale points")
        _nontrivial(sc.get("expect"), 30, "scaling.expect (the trend the mechanism predicts across the points)", errs)
        _nontrivial(sc.get("value_of_information"), 60,
                    "scaling.value_of_information (which promotion/architecture decision this changes)", errs)
        execution = str(sc.get("execution") or "")
        costly_arms = sc.get("costly_arms")
        if scaling_mode == "reuse_only":
            if execution != "existing_artifact" or costly_arms != 0:
                errs.append("IDEA_SCALING_REUSE_ONLY: reuse_only permits only existing_artifact evidence with costly_arms=0")
        else:
            if execution != "followup_node" or sc.get("trigger") != "after_positive_signal":
                errs.append("IDEA_SCALING_FOLLOWUP: budgeted/full scaling must execute as a followup_node triggered after_positive_signal, never inside the unproven primary node")
            cap = int((ctx.cfg.get("evidence_policy") or {}).get("max_scaling_costly_arms", 0))
            if not isinstance(costly_arms, int) or not (1 <= costly_arms <= cap):
                errs.append(f"IDEA_SCALING_COSTLY_ARMS: follow-up scaling costly_arms must be 1..{cap}")
    # v11.1 P4: pre-registered on-the-line repeat rule (single-run mode only).
    errs.extend(repeat_rule_errors(ctx.cfg, meta, st=ctx.st))
    # parents must match the lane contract
    lane_model = [p for p in lane.get("parents", []) if _is_model_parent(ctx, p)]
    lane_plat = [p for p in lane.get("parents", []) if p in idx and not _is_model_parent(ctx, p)]
    if list(meta.get("parents") or []) != lane_model:
        errs.append(f"IDEA_PARENTS: meta.parents must equal the lane's model parents {lane_model} (got {meta.get('parents')})")
    extra_plat = [p for p in (meta.get("platforms_consumed") or []) if p not in lane_plat]
    if extra_plat:
        errs.append(f"IDEA_PLATFORMS: platforms_consumed {extra_plat} were not declared in the lane")
    # Prior-art grounding is an audit of novelty, not a claim that the new core
    # was borrowed from a recent mechanism.
    mech = ctx.mech_by_id()
    mc = meta.get("prior_art_card_ids") or []
    if not mc or any(m not in mech for m in mc):
        errs.append(f"IDEA_PRIOR_ART_CARDS: prior_art_card_ids must resolve (got {mc})")
    bs, _, _ = ctx.dossier_ids()
    bot = meta.get("bottleneck_ids") or []
    if lane.get("search_origin") == "repair" and lane.get("intent") != "platform" \
            and (not bot or any(b not in bs for b in bot)):
        errs.append(f"IDEA_BOTTLENECK: repair bottleneck_ids must resolve to dossier B# ids (got {bot})")
    elif any(b not in bs for b in bot):
        errs.append(f"IDEA_BOTTLENECK_UNKNOWN: optional bottleneck_ids contain unknown ids (got {bot})")
    # Assumptions support falsification; their count does not define novelty.
    assumptions = meta.get("assumptions") or []
    min_assumptions = 3 if meta.get("theory_role") == "derivational" else 2
    if len(assumptions) < min_assumptions:
        errs.append(f"IDEA_ASSUMPTIONS: >= {min_assumptions} registered assumptions required; "
                    "theory role, not L level, determines the extra duty")
    aids: set[str] = set()
    for a in assumptions:
        aid = str(a.get("id") or "")
        if not re.fullmatch(r"A\d+", aid):
            errs.append(f"IDEA_ASSUMPTION_ID: assumption id must be A# (got {aid!r})")
        aids.add(aid)
        _nontrivial(a.get("statement"), 30, f"assumption {aid}.statement", errs)
        src = str(a.get("source") or "")
        if src not in ("profile", "dossier", "theory") and src not in mech and src not in ctx.obs_ids():
            errs.append(f"IDEA_ASSUMPTION_SOURCE: {aid}: source must be 'profile', 'dossier', 'theory', "
                        f"a mech card id, or a ledger observation id OB### (got {src!r}) - findings "
                        f"measured in this graph's own runs are first-class assumption grounds")
    # predictions (platform ideas declare enablement instead of metric predictions)
    preds = meta.get("predictions") or []
    if lane.get("intent") == "platform":
        enables = meta.get("enables") or []
        if len(enables) < 2:
            errs.append("IDEA_ENABLES: platform ideas must list >= 2 concrete future nodes/uses they unlock in meta.enables")
    elif lane.get("experiment_purpose") in econfig.EXPLORATORY_PURPOSES:
        # v11.1 P5: reconnaissance declared at admission is exactly the case
        # where forcing numeric foresight manufactures noise - predictions are
        # OPTIONAL here, and the lane already paid with observations-only
        # status (no frontier, no records, no research-share credit).
        pass
    elif not (bud.get("predictions_min", 2) <= len(preds) <= bud.get("predictions_max", 4)):
        errs.append(f"IDEA_PREDICTIONS_COUNT: need {bud.get('predictions_min')}..{bud.get('predictions_max')} registered predictions, got {len(preds)}")
    pids: set[str] = set()
    for p in preds:
        pid = str(p.get("id") or "")
        if not re.fullmatch(r"P\d+", pid) or pid in pids:
            errs.append(f"IDEA_PREDICTION_ID: prediction ids must be unique P# (got {pid!r})")
        pids.add(pid)
        if p.get("metric") not in rspec:
            errs.append(f"IDEA_PREDICTION_METRIC: {pid}: metric must be an evaluation-contract result_key "
                        f"(got {p.get('metric')!r})")
        if p.get("comparison") not in (">=", "<="):
            errs.append(f"IDEA_PREDICTION_CMP: {pid}: comparison must be '>=' or '<='")
        if not isinstance(p.get("value"), (int, float)):
            errs.append(f"IDEA_PREDICTION_VALUE: {pid}: numeric 'value' required (a pre-registered number, not a direction)")
        if "slice" in p:
            # R4 science audit: the settlement reads the GLOBAL result_key; a
            # slice annotation would be displayed at the approval gate and then
            # silently ignored at settlement - refuse the dishonest shape.
            errs.append(f"IDEA_PREDICTION_SLICE: {pid}: slice-scoped predictions are not engine-settleable "
                        "(settlement reads the global result_key); register a dedicated metric cell for "
                        "the slice instead")
        _nontrivial(p.get("rationale"), 40, f"prediction {pid}.rationale (mechanism-level why)", errs)
    claimed_result_keys = {str((cells.get(cid) or {}).get("result_key") or "") for cid in claim_targets}
    if lane.get("intent") != "platform" and preds and not any(p.get("metric") in claimed_result_keys for p in preds):
        errs.append("IDEA_PREDICTION_SCOPE: at least one registered prediction must test a result_key in claim_scope.target_cells")
    # novelty + sibling distance - MODE-DEPENDENT (v8):
    #   research: the idea must DIFFER from the nearest published work (novelty
    #     is a goal); engineering: the idea may BORROW the published mechanism
    #     wholesale, but must argue the ADAPTATION - why it fits THIS project's
    #     diagnosis and what is tuned/changed to transfer. Matching the
    #     literature is not a defect when the goal is gains.
    npb = meta.get("nearest_published") or {}
    if npb.get("paper") not in ctx.evidence_ids():
        errs.append("IDEA_NEAREST_PUBLISHED: nearest_published.paper must cite an evidence id - 'nothing similar exists' requires citing the closest thing that does")
    if ctx.is_research():
        _nontrivial(npb.get("difference"), 80,
                    "nearest_published.difference (research mode: what is NEW vs that work)", errs)
    else:
        adapt = str(npb.get("adaptation") or npb.get("difference") or "")
        _nontrivial(adapt, 80,
                    "nearest_published.adaptation (engineering mode: what is borrowed, what is adapted "
                    "for THIS project, and why the transfer conditions hold - borrowing is legal, "
                    "unfitted transplanting is not)", errs)
    sib_nodes = [n for n in egraph.siblings(ctx.g, lane_model) if n.get("lane") != lane["id"]]
    listed = {s.get("node") for s in (meta.get("siblings_distance") or [])}
    for s in (meta.get("siblings_distance") or []):
        if s.get("node") not in idx:
            errs.append(f"IDEA_SIBLING_UNKNOWN: siblings_distance names nonexistent node {s.get('node')!r}")
        _nontrivial(s.get("difference"), 40, f"siblings_distance[{s.get('node')}].difference", errs)
    missing_sibs = [n["id"] for n in sib_nodes if n["id"] not in listed]
    if lane.get("intent") != "platform" and missing_sibs:
        # R7 audit: the old [:5] slice revealed the required set five ids at a
        # time, so literally following each rejection exhausted the default
        # three attempts on a fully repairable task. Name the WHOLE duty.
        shown = missing_sibs[:30]
        errs.append("IDEA_SIBLING_DISTANCE: siblings_distance must cover EVERY node in the bundle's "
                    f"'Sibling nodes' block - missing {shown}"
                    + (f" and {len(missing_sibs) - 30} more (see the block for the complete set)"
                       if len(missing_sibs) > 30 else ""))
    if not isinstance(meta.get("metric_bridge_needed"), bool):
        errs.append("IDEA_METRIC_BRIDGE_FLAG: meta.metric_bridge_needed (bool) required")
    if not isinstance(meta.get("external_interface_changed"), bool):
        errs.append("IDEA_INTERFACE_FLAG: external_interface_changed boolean required")
    elif meta.get("external_interface_changed") and meta.get("metric_bridge_needed") is False:
        errs.append("IDEA_METRIC_BRIDGE_REQUIRED: an external output/eval interface change needs a metric bridge")
    # Scientific contract sections mirror the program object and independent
    # M/E/T axes; no paper-story or coordinate-change template is imposed.
    if lane.get("intent") == "platform":
        md_sections_wanted = ["scientific program", "enabling capability",
                              "operational and resource contract", "prior-art boundary",
                              "consumer/use falsification", "implementation sketch", "risks"]
    else:
        md_sections_wanted = ["scientific program", "irreducible kernel", "effect and resource case",
                              "causal derivation", "prior-art boundary",
                              "implementation sketch", "risks"]
        if lane.get("experiment_purpose") not in econfig.EXPLORATORY_PURPOSES:
            # v11.1 P5 (R1 fix): the numeric-predictions section is exactly the
            # foresight ceremony an exploratory lane is exempt from; demanding
            # the heading while the count check waived the content taught cold
            # agents to fabricate numbers that then got verdicted.
            md_sections_wanted.append("predictions")
        if research_kernel:
            md_sections_wanted.append("mechanism check")
        else:
            md_sections_wanted.append("falsification experiment")
    if meta.get("theory_role") != "none":
        md_sections_wanted.append("theory consequences")
    if lane.get("formal"):
        md_sections_wanted.append("formal statement")
    secs_md = _require_sections(md, md_sections_wanted, "IDEA.md", errs, min_chars=80)
    if lane.get("formal"):
        fs = secs_md.get("formal statement") or ""
        psyms = ctx.problem_symbols(lane)
        used = [n for n in psyms if re.search(rf"(?<![\w]){re.escape(n)}(?![\w])", fs)]
        if fs and psyms and len(used) < min(2, len(psyms)):
            errs.append("IDEA_FORMAL_SYMBOLS: the Formal statement must state the result in the POSED "
                        "problem's symbols (proposition style: given ..., the mechanism achieves ...) - "
                        f"none/too few of {psyms[:6]} appear")
    _check_citations(ctx, md, "IDEA.md", errs, min_mech=1)
    body_aids = set(A_ID.findall(md))
    missing_a = aids - body_aids
    if lane.get("intent") != "platform" and missing_a:
        errs.append(f"IDEA_DERIVATION_TRACE: causal derivation must walk each assumption id; missing {sorted(missing_a)}")
    return errs


def v_red_team(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    review = _read_md(ctx, task["outputs"][0], errs)
    _, idea_md = _load_idea(ctx, lane, errs)
    if review is None or idea_md is None:
        return errs
    m = re.search(r"^VERDICT:\s*(\S+)", review, re.M)
    verdicts = ("ACCEPT", "REVISE", "REJECT_SHALLOW", "REJECT_DUPLICATE", "REJECT_NOT_COMPARABLE", "REJECT_INFEASIBLE")
    if not m or m.group(1) not in verdicts:
        errs.append(f"REVIEW_VERDICT: review must start a line with 'VERDICT: <{('|'.join(verdicts))}>'")
    errs.extend(critic_isolation_errors(
        ctx, task, release=bool(m and m.group(1) == "ACCEPT"), author_types=("mature",)))
    meta, _ = _load_idea(ctx, lane, [])
    if lane.get("intent") == "platform":
        wanted = ["program fidelity", "enablement and load-bearing attack",
                  "operational and resource attack", "consumer/use falsification",
                  "prior-art attack", "verdict rationale"]
    else:
        wanted = ["program fidelity", "irreducibility attack", "effect and resource attack",
                  "prior-art attack", "verdict rationale"]
    if (meta or {}).get("theory_role") != "none":
        wanted.append("theory alignment")
    _require_sections(review, wanted, "review", errs, min_chars=60)
    _check_quotes(QUOTE_LINE.findall(review), idea_md, "review", errs, min_quotes=2)
    if m and m.group(1) == "REJECT_DUPLICATE":
        # v11.2: a published-work duplicate death must BANK its boundary. One
        # criterion line, so later rounds inherit "what that work absorbs"
        # instead of re-walking it; deliberately placed here (not inside
        # _duplicate_evidence_errors) so historical pre-v11.2 reviews keep
        # their hard-disposition status unchanged.
        rt_target = next(iter(DUPLICATE_TARGET_RE.findall(review)), "")
        if rt_target.startswith("CA") and ctx.is_research():
            # (engineering CA targets are already rejected wholesale by the
            # license fn below - no tombstone demand on top of that verdict)
            errs.extend(_review_tombstone_errors(ctx, review))
        errs.extend(_duplicate_evidence_errors(
            ctx, review, lane_id=str(lane.get("id") or ""),
            program_set_digest=str(lane.get("program_set_digest") or ""),
            winner=str(lane.get("winner_sketch") or ""),
            candidate_digest=str(lane.get("winner_program_digest") or ""),
            candidate_kernel_hash=str(lane.get("winner_kernel_hash") or "")))
    if m and m.group(1) == "REJECT_SHALLOW":
        kernel_ids = eprogram.kernel_ids(meta or {})
        if kernel_ids and not any(re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(kid)}(?![A-Za-z0-9_])", review)
                for kid in kernel_ids):
            errs.append(f"REVIEW_SHALLOW_KERNEL: REJECT_SHALLOW is a core disposition and must name at "
                        f"least one actual winner kernel id from {kernel_ids}")
    if m and m.group(1) == "ACCEPT":
        secs = eutil.md_sections(review)
        obj = eutil.find_section(secs, "strongest surviving objection")
        if not obj or len(obj.strip()) < 60:
            errs.append("REVIEW_OBJECTION: an ACCEPT must state the strongest surviving objection (>= 60 chars); frictionless acceptance is not review")
    return errs


# ---- node validators ------------------------------------------------------------------

def load_spec(ctx: Ctx, relp: str, errs: list[str]) -> dict | None:
    return _read_json(ctx, relp, errs)


def _resolved_uri_variants(uri: str, spec: dict | None) -> set[str]:
    """Every canonical spelling a declared product URI can take at runtime:
    the raw form plus each preplanned-seed expansion. R9 audit: reservation
    compared raw strings only, so `out/{seed}.pt` and a sibling's literal
    `out/1.pt` never collided on paper while the filesystem resolved them to
    one file. R10-002: remote scheme URIs participate too - the registry law
    makes a producer URI globally unique, so two pending specs declaring one
    remote landing are a reservation conflict exactly like two local ones."""
    out: set[str] = set()
    raw = str(uri or "")
    if not raw:
        return out
    out.add(eutil.norm_uri(raw))
    # R11-003: seed expansion applies to REMOTE templates too -
    # resolve_seed_template is pure string substitution, and the runtime
    # (claims, registration) expands both alike; keeping the remote template
    # unexpanded made `oss://b/x/{seed}.pt` and a sibling's literal
    # `oss://b/x/1.pt` disjoint on paper while identical on the backend.
    if "{" in raw and spec is not None:
        for seed in econfig.workflow_seeds(spec):
            resolved = str(econfig.resolve_seed_template(raw, seed))
            if "{" not in resolved:
                out.add(eutil.norm_uri(resolved))
    out.discard("")
    return out


def _resolved_product_uris(spec: dict) -> set[str]:
    out: set[str] = set()
    for s_row in econfig.stages_of(spec):
        for p_row in (s_row.get("produces") or []):
            if isinstance(p_row, dict):
                out |= _resolved_uri_variants(str(p_row.get("uri") or ""), spec)
    return out


def _pending_uri_producer(ctx: Ctx, uri: str, exclude_node: str | None = None,
                          *, spec: dict | None = None) -> str | None:
    """R9: the node id of a NON-TERMINAL node whose frozen spec already
    declares ``uri`` as a product landing (registry rows cover only produced
    artifacts; reservation must cover pending producers too). Comparison is
    over seed-RESOLVED canonical variants on both sides."""
    wanted = _resolved_uri_variants(uri, spec)
    if not wanted:
        return None
    for n in ctx.g.get("nodes", []):
        nid = str(n.get("id") or "")
        if not nid or nid == str(exclude_node or "") \
                or n.get("status") in ("concluded", "abandoned"):
            continue
        spec_rel = str(n.get("spec") or "")
        if not spec_rel:
            continue
        other = eutil.read_json(eutil.rpath(ctx.store.repo, spec_rel), None)
        if not isinstance(other, dict):
            continue
        # R10-002: overlap-aware (directory product vs a child path inside it)
        theirs = _resolved_product_uris(other)
        if any(eutil.paths_overlap(w, t) for w in wanted for t in theirs):
            return nid
    return None


def _stage_errors(ctx: Ctx, spec: dict, *, role: str, where: str,
                  exclude_node: str | None = None,
                  receipts: dict | None = None) -> list[str]:
    errs: list[str] = []
    purpose = str(spec.get("experiment_purpose") or "")
    workflow = spec.get("workflow")
    if workflow is not None and not isinstance(workflow, dict):
        return [f"SPEC_WORKFLOW_SHAPE: {where}: workflow must be an object with a stages list"]
    if "train" in spec:
        errs.append(f"SPEC_TRAIN_SCHEMA_UNSUPPORTED: {where}: top-level 'train' is not part of the v9.2 "
                    "schema; declare scheduler-visible procedures only under workflow.stages")
    if isinstance(workflow, dict) and "stages" in workflow and not isinstance(workflow.get("stages"), list):
        errs.append(f"SPEC_WORKFLOW_STAGES_SHAPE: {where}: workflow.stages must be a list")
    if isinstance(workflow, dict) and isinstance(workflow.get("stages"), list) and \
            any(not isinstance(s, dict) for s in workflow["stages"]):
        errs.append(f"SPEC_WORKFLOW_STAGE_SHAPE: {where}: every workflow.stages entry must be an object")
    stages = econfig.stages_of(spec)
    if role in ("baseline", "platform") and not stages:
        return errs  # a workflow is optional for pre-existing anchors
    # Inference/API/analysis nodes may be evaluation-only, but can also carry a
    # finite workflow (prompt search, decoding optimization, data transforms).
    if econfig.experiment_class(spec) in econfig.WORKFLOW_OPTIONAL_CLASSES and not stages:
        return errs
    if not stages:
        errs.append(f"SPEC_STAGES: {where}: workflow.stages must be a non-empty list of finite procedures "
                    f"(a single stage is fine; an evaluation-only node must declare "
                    f"experiment_class inference|api|analysis)")
        return errs
    names: set[str] = set()
    gate_ids: set[str] = set()
    uris: set[str] = set()
    decision_result_keys = {
        str(c.get("result_key") or "")
        for c in econfig.evaluation_cells(ctx.cfg, roles={"target", "guardrail"})
    }
    for i, s in enumerate(stages):
        sw = f"{where}.stage[{i}]({s.get('name')})"
        name = str(s.get("name") or "")
        if not STAGE_NAME.fullmatch(name):
            errs.append(f"SPEC_STAGE_NAME: {sw}: 'name' must be a short slug ([A-Za-z0-9_-], <= 32 chars)")
        if name in names:
            errs.append(f"SPEC_STAGE_DUP: {sw}: duplicate stage name '{name}'")
        names.add(name)
        _nontrivial(s.get("purpose"), 25, f"{sw}.purpose (why this is a scheduler-visible handoff/recovery boundary)", errs)
        if "experiment_role" in s:
            errs.append(f"SPEC_STAGE_ROLE_OBSOLETE: {sw}: experiment_role is obsolete; every workflow stage "
                        "is part of the declared node purpose")
        control = s.get("control")
        if not isinstance(control, dict):
            errs.append(f"SPEC_STAGE_CONTROL: {sw}: control object required")
            control = {}
        mode = control.get("mode")
        multiplicity = control.get("multiplicity")
        if mode not in econfig.STAGE_CONTROL_MODES:
            errs.append(f"SPEC_STAGE_CONTROL_MODE: {sw}: control.mode must be one of {econfig.STAGE_CONTROL_MODES}")
        if multiplicity not in econfig.STAGE_MULTIPLICITIES:
            errs.append(f"SPEC_STAGE_MULTIPLICITY: {sw}: control.multiplicity must be one of {econfig.STAGE_MULTIPLICITIES}")
        if purpose == "targeted_ablation" and (mode != "fixed" or multiplicity != "single"):
            errs.append(f"SPEC_ABLATION_STAGE_CONTROL: {sw}: targeted ablation stages must be fixed/single; "
                        "adaptive search, intrinsic model multiplicity and replication would turn one causal "
                        "intervention into several experiments")
        if mode == "preregistered_adaptive":
            _nontrivial(control.get("controller"), 50,
                        f"{sw}.control.controller (the rule mapping observed results to the next action)", errs)
            stops = control.get("stopping_conditions")
            if not isinstance(stops, list) or not stops:
                errs.append(f"SPEC_STAGE_STOPPING: {sw}: preregistered_adaptive control needs non-empty stopping_conditions")
            elif any(len(str(x or "").strip()) < 12 for x in stops):
                errs.append(f"SPEC_STAGE_STOPPING_THIN: {sw}: every stopping condition must be explicit (>= 12 chars)")
        if multiplicity == "algorithmic":
            _nontrivial(control.get("why_multiple"), 40,
                        f"{sw}.control.why_multiple (why removing the candidates/models/runs changes the delivered method)", errs)
        if any(k in control for k in ("replica_seeds", "aggregation")):
            errs.append(f"SPEC_STAGE_REPLICATION_OBSOLETE: {sw}: seed repetition belongs to top-level "
                        "training_replication and repeats the complete workflow; stage control may not carry "
                        "replica_seeds or a seed aggregation")
        if econfig.stage_requires_ledger(s) and not str(s.get("ledger_file") or "").strip():
            errs.append(f"SPEC_STAGE_LEDGER: {sw}: adaptive, algorithmic or replicated procedures need "
                        "ledger_file for ordered decisions/runs and resource usage")
        budget = s.get("budget")
        limits = (budget or {}).get("limits") if isinstance(budget, dict) else None
        if not isinstance(limits, dict) or not limits:
            errs.append(f"SPEC_STAGE_BUDGET: {sw}: budget.limits must be a non-empty map of finite resource caps")
            limits = {}
        for unit, limit in limits.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{1,47}", str(unit or "")):
                errs.append(f"SPEC_STAGE_BUDGET_UNIT: {sw}: budget unit {unit!r} must be a lowercase slug")
            if isinstance(limit, bool) or not isinstance(limit, (int, float)) or \
                    not math.isfinite(float(limit)) or float(limit) <= 0:
                errs.append(f"SPEC_STAGE_BUDGET_VALUE: {sw}: budget limit {unit!r} must be finite and > 0")
        if limits and not econfig.tracked_budget(budget, ctx.cfg):
            errs.append(f"SPEC_STAGE_PROJECT_BUDGET: {sw}: at least one budget unit must appear in the "
                        "user-confirmed project resource_contract; otherwise this stage bypasses the global cap")
        if not str(s.get("launch") or "").strip():
            errs.append(f"SPEC_STAGE_LAUNCH: {sw}: 'launch' command required")
        else:
            launch = str(s.get("launch"))
            if re.search(r"comparison.?arm", launch, re.I):
                errs.append(f"SPEC_COMPARISON_ARM_IN_WORKFLOW: {sw}: a separate comparison arm may not be hidden "
                            "inside a node; reuse the protocol-matched parent result")
            if re.search(r"ablation", launch, re.I) and purpose != "targeted_ablation":
                errs.append(f"SPEC_ABLATION_IN_CANDIDATE: {sw}: an ablation command is legal only in a separately "
                            "declared targeted_ablation node")
            if re.search(r"--sweep\b|multirun|grid.?search|array.?job", launch, re.I) and \
                    multiplicity != "algorithmic":
                errs.append(f"SPEC_MULTIPLICITY_UNDECLARED: {sw}: launch appears multi-candidate; declare "
                            "algorithmic multiplicity when those candidates are intrinsic to the method; "
                            "approved seed repetition is represented only at workflow level")
        if not str(s.get("metrics_file") or "").strip():
            errs.append(f"SPEC_STAGE_METRICS: {sw}: 'metrics_file' path required")
        continuation = s.get("continuation_gate")
        if continuation is not None:
            if purpose == "targeted_ablation":
                errs.append(f"SPEC_ABLATION_CONTINUATION_GATE: {sw}: the dedicated causal contract already "
                            "defines the effect/no-effect decision after standard evaluation; do not add a "
                            "second result-dependent gate inside the run")
            if role not in ("root", "variant", "hybrid"):
                errs.append(f"SPEC_STAGE_GATE_ROLE: {sw}: continuation_gate is only for scientific model-idea "
                            f"nodes (root|variant|hybrid), not {role!r}")
            if i >= len(stages) - 1:
                errs.append(f"SPEC_STAGE_GATE_NO_DOWNSTREAM: {sw}: continuation_gate must screen at least one "
                            "later candidate-producing stage; a gate on the final stage can only suppress "
                            "evaluation after seeing results")
            if not isinstance(continuation, dict):
                errs.append(f"SPEC_STAGE_GATE_SHAPE: {sw}: continuation_gate must be an object")
            else:
                gid = str(continuation.get("id") or "")
                if not STAGE_NAME.fullmatch(gid):
                    errs.append(f"SPEC_STAGE_GATE_ID: {sw}: continuation_gate.id must be a short slug")
                elif gid in gate_ids:
                    errs.append(f"SPEC_STAGE_GATE_ID_DUP: {sw}: continuation gate id {gid!r} repeats in this workflow")
                gate_ids.add(gid)
                if continuation.get("aggregation") not in econfig.STAGE_GATE_AGGREGATIONS:
                    errs.append(f"SPEC_STAGE_GATE_AGGREGATION: {sw}: continuation_gate.aggregation must be one of "
                                f"{econfig.STAGE_GATE_AGGREGATIONS}")
                if continuation.get("on_miss") != "stop_node":
                    errs.append(f"SPEC_STAGE_GATE_ACTION: {sw}: continuation_gate.on_miss must be 'stop_node'; "
                                "branching/recovery belongs in the algorithm, not an ad-hoc scheduler action")
                _nontrivial(continuation.get("rationale"), 40,
                            f"{sw}.continuation_gate.rationale (why a miss invalidates the remaining workflow)", errs)
                assumptions = continuation.get("assumptions")
                if not isinstance(assumptions, list) or not assumptions or \
                        any(not re.fullmatch(r"A\d+", str(a or "")) for a in assumptions):
                    errs.append(f"SPEC_STAGE_GATE_ASSUMPTIONS: {sw}: continuation_gate.assumptions must be a "
                                "non-empty list of pre-registered A# ids")
                predicates = continuation.get("predicates")
                if not isinstance(predicates, list) or not predicates:
                    errs.append(f"SPEC_STAGE_GATE_PREDICATES: {sw}: continuation_gate.predicates must be a non-empty list")
                    predicates = []
                for j, pred in enumerate(predicates):
                    pw = f"{sw}.continuation_gate.predicates[{j}]"
                    if not isinstance(pred, dict):
                        errs.append(f"SPEC_STAGE_GATE_PREDICATE_SHAPE: {pw}: predicate must be an object")
                        continue
                    metric = str(pred.get("metric") or "")
                    if not STAGE_METRIC_KEY.fullmatch(metric):
                        errs.append(f"SPEC_STAGE_GATE_METRIC: {pw}: metric must be a stage-summary key slug")
                    if metric in decision_result_keys:
                        errs.append(f"SPEC_STAGE_GATE_DECISION_METRIC: {pw}: {metric!r} is a configured target/"
                                    "guardrail result; continuation gates may test an upstream prerequisite, "
                                    "not hide an unfavorable decision result")
                    if pred.get("comparison") not in econfig.STAGE_GATE_COMPARISONS:
                        errs.append(f"SPEC_STAGE_GATE_COMPARISON: {pw}: comparison must be one of "
                                    f"{econfig.STAGE_GATE_COMPARISONS}")
                    value = pred.get("value")
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or \
                            not math.isfinite(float(value)):
                        errs.append(f"SPEC_STAGE_GATE_VALUE: {pw}: value must be a finite number")
        produces = s.get("produces") or []
        if not isinstance(produces, list):
            errs.append(f"SPEC_STAGE_PRODUCES_SHAPE: {sw}: produces must be a list")
            produces = []
        if produces and not str(s.get("stage_key") or "").strip():
            errs.append(f"SPEC_STAGE_KEY: {sw}: a stage that produces artifacts needs a 'stage_key' - the canonical "
                        f"content key (data|objective|procedure|controller|budget...) that makes equivalent outputs recognizable for reuse")
        elif produces and len(str(s.get("stage_key"))) < 8:
            errs.append(f"SPEC_STAGE_KEY_THIN: {sw}: stage_key too short to identify the procedure and output content")
        for j, p in enumerate(produces):
            pw = f"{sw}.produces[{j}]"
            if not isinstance(p, dict):
                errs.append(f"SPEC_ARTIFACT_SHAPE: {pw}: artifact declaration must be an object")
                continue
            if not str(p.get("name") or "").strip():
                errs.append(f"SPEC_ARTIFACT_NAME: {pw}: 'name' required")
            if p.get("kind") not in econfig.ARTIFACT_KINDS:
                errs.append(f"SPEC_ARTIFACT_KIND: {pw}: kind must be one of {econfig.ARTIFACT_KINDS}")
            uri = str(p.get("uri") or "")
            if not uri:
                errs.append(f"SPEC_ARTIFACT_URI: {pw}: 'uri' required (where the artifact will live; instantiate "
                            f"the infra artifact_store.uri_template with a run id unique to this node+stage)")
                continue
            variants = _resolved_uri_variants(uri, spec) or {eutil.norm_uri(uri)}
            # R11-004: intra-spec uniqueness is the overlap relation too - a
            # declared directory product and a sibling stage's child path
            # inside it are one physical landing.
            if variants & uris or any(eutil.paths_overlap(v, u)
                                      for v in variants for u in uris):
                errs.append(f"SPEC_ARTIFACT_URI_DUP: {pw}: uri {uri} repeats or overlaps another "
                            "declared product inside this spec (seed-resolved forms compared)")
            uris |= variants
            # R11-003/004: the registry check runs over EVERY seed-resolved
            # spelling (a template must collide with a registered literal
            # expansion) and uses the overlap relation (a registered
            # directory product vs a later child path).
            clash = next((hit for hit in (eartifact.find_overlapping(ctx.reg, v)
                                          for v in sorted(variants)) if hit is not None), None)
            if clash is not None:
                errs.append(f"SPEC_ARTIFACT_URI_COLLISION: {pw}: uri {uri} is already registered as {clash['id']} "
                            f"(produced by {clash.get('node')}/{clash.get('stage')}; seed-resolved and "
                            f"directory-overlap forms compared) - reusing an output path silently "
                            f"overwrites checkpoints; derive a fresh run id for this node+stage")
            else:
                # R9 (external audit r6): the registry only knows PRODUCED
                # artifacts - two not-yet-produced specs could reserve the same
                # URI and the second producer to land just logged a conflict
                # event while overwriting the first's bytes. Reservation must
                # cover pending producers too. R9 follow-up: both sides are
                # compared over seed-RESOLVED canonical variants, so a
                # template and a sibling's literal expansion collide on paper
                # exactly as they do on disk.
                pending = _pending_uri_producer(ctx, uri, exclude_node=exclude_node, spec=spec)
                if pending:
                    errs.append(f"SPEC_ARTIFACT_URI_RESERVED: {pw}: uri {uri} is already declared by "
                                f"non-terminal node {pending}'s frozen spec (seed-resolved forms "
                                "compared); two producers may not share an output path - derive a "
                                "fresh run id for this node+stage")
        consumed_ids: set[str] = set()
        consumes = s.get("consumes") or []
        if not isinstance(consumes, list):
            errs.append(f"SPEC_STAGE_CONSUMES_SHAPE: {sw}: consumes must be a list")
            consumes = []
        for j, c in enumerate(consumes):
            cw = f"{sw}.consumes[{j}]"
            if not isinstance(c, dict):
                errs.append(f"SPEC_CONSUME_SHAPE: {cw}: consume declaration must be an object")
                continue
            has_art = bool(str((c or {}).get("artifact") or "").strip())
            has_stage = bool(str((c or {}).get("stage") or "").strip())
            if has_art == has_stage:
                errs.append(f"SPEC_CONSUME_SHAPE: {cw}: exactly one of 'artifact' (AR###) or 'stage' (earlier stage name) required")
                continue
            if has_art:
                aid = str(c["artifact"])
                art = eartifact.by_id(ctx.reg).get(aid)
                if art is None:
                    errs.append(f"SPEC_CONSUME_UNKNOWN: {cw}: artifact {aid} not in the registry")
                elif art.get("status") != "available":
                    errs.append(f"SPEC_CONSUME_UNAVAILABLE: {cw}: artifact {aid} is {art.get('status')}; only "
                                f"available artifacts may be consumed")
                else:
                    consumed_ids.add(aid)
                    # R11-010: the card that authored this spec carried a
                    # machine receipt of the registry it rendered. If the
                    # artifact's generation or digest moved between card
                    # materialization and this acceptance, the author reasoned
                    # about bytes that no longer head the id - refuse to
                    # freeze the binding blind instead of silently recording
                    # the NEW generation as the author's choice.
                    rec = (receipts or {}).get(aid) if isinstance(receipts, dict) else None
                    if rec is not None and (
                            int(rec.get("generation") or 0) != int(art.get("generation") or 1)
                            or str(rec.get("content_digest") or "")
                            != str(art.get("content_digest") or "")):
                        errs.append(
                            f"SPEC_ARTIFACT_GENERATION_MOVED: {cw}: artifact {aid} moved to generation "
                            f"{art.get('generation') or 1} after this card was rendered (the card showed "
                            f"generation {rec.get('generation')}); the refreshed card now lists the "
                            f"current registry - re-read the Shared artifacts block and resubmit a spec "
                            f"reasoned against the artifact's CURRENT content")
                    # R11-005: a producer that is mid-revision (a typed fix or
                    # an implementation redo is already scheduled) is ABOUT to
                    # regenerate these bytes; freezing the binding now
                    # guarantees a later launch rejection with no ordinary
                    # rebinding entry for an accepted node. Refuse at the last
                    # reversible moment instead.
                    producer = egraph.by_id(ctx.g).get(str(art.get("node") or ""))
                    if producer is not None and (
                            producer.get("fix_needed")
                            or producer.get("implementation_revision_pending")):
                        errs.append(
                            f"SPEC_CONSUME_PRODUCER_MID_REVISION: {cw}: artifact {aid}'s producer "
                            f"{art.get('node')} has a pending implementation revision - its products are "
                            f"about to be regenerated, so this binding would be rejected at launch; wait "
                            f"for the producer to settle (or consume a settled artifact) before freezing. "
                            f"If this stage_key's only match IS the mid-revision product, drop the consume "
                            f"and state a reuse_waiver (>= 40 chars) explaining the fresh execution")
            else:
                ref = str(c["stage"])
                earlier = [str(x.get("name") or "") for x in stages[:i]]
                if ref not in earlier:
                    errs.append(f"SPEC_CONSUME_STAGE: {cw}: 'stage' must name an EARLIER stage of this spec "
                                f"(got {ref!r}; earlier: {earlier})")
        # reuse duty: an equivalent available artifact must be consumed or explicitly waived
        skey = str(s.get("stage_key") or "").strip()
        if skey:
            # F5: under preplanned replication the spec key is a '{seed}'
            # template while the registry stores seed-resolved keys; compare
            # each RESOLVED spelling or the duty can never fire.
            seeds = econfig.workflow_seeds(spec) or [None]
            candidate_keys = []
            for seed_value in seeds:
                resolved = str(econfig.resolve_seed_template(skey, seed_value)) \
                    if seed_value is not None else skey
                if resolved not in candidate_keys:
                    candidate_keys.append(resolved)
            # R11-018: the duty covers EVERY resolved seed lane, not the
            # first hit - one consumed match used to silence the check for
            # every remaining seed's existing product.
            uncovered = []
            for k in candidate_keys:
                for m in eartifact.find_all_available_by_stage_key(ctx.reg, k):
                    if m["id"] not in consumed_ids:
                        uncovered.append(m)
            if uncovered:
                waiver = str(s.get("reuse_waiver") or "").strip()
                if len(waiver) < 40:
                    listing = "; ".join(
                        f"{m['id']} ({m.get('uri')}) by {m.get('node')}/{m.get('stage')}"
                        for m in uncovered[:4])
                    errs.append(
                        f"SPEC_ARTIFACT_REUSE_IGNORED: {sw}: stage_key '{skey}' matches available "
                        f"artifact(s) not consumed here: {listing} - consume them instead of "
                        f"recomputing, or state a reuse_waiver (>= 40 chars) explaining why a new "
                        f"execution is genuinely necessary"
                    )
    return errs


def budget_band_floor_of(run: dict | None) -> float | None:
    """Highest validity band actually applied when this RUN's evidence sealed.

    v12 era-gating: the tolerance band (econfig.budget_tolerance) is a mutable
    governance control whose changes affect FUTURE ingestions only. Lowering
    it later must not turn a lawfully-sealed RUN into a permanent replay
    violation (doctor, normalized re-checks). The floor comes from the overage
    disclosure rows stamped at seal time; a RUN sealed with no overage needs
    no floor.
    """
    rows = (run or {}).get("budget_overages_within_tolerance") or []
    bands = [float(row.get("band") or 0.0) for row in rows if isinstance(row, dict)]
    return max(bands) if bands else None


def stage_result_errors(ctx: Ctx, stage: dict, metrics_file: str | None,
                        ledger_file: str | None, *, where: str,
                        metrics_data: Any = _STAGE_RESULT_UNREAD,
                        expected_seed: Any | None = None,
                        expected_metrics_file: str | None = None,
                        expected_ledger_file: str | None = None,
                        budget_band_floor: float | None = None) -> list[str]:
    """Validate a completed canonical workflow stage against its declared cap.

    The engine cannot meter an external cluster itself, but it can require the
    stage to report the same resource units that the user approved and reject a
    result that admits exceeding a cap. Scientific continuation is computed by
    the engine from a gate frozen in the node spec, never trusted from a result.
    """
    errs: list[str] = []
    if not metrics_file or not _exists(ctx, metrics_file):
        return [f"STAGE_RESULT_METRICS: {where}: completed stage needs an existing metrics_file "
                "(resolved from the REPOSITORY ROOT, not the stage working directory)"]
    data = eutil.read_json(eutil.rpath(ctx.store.repo, metrics_file), None) \
        if metrics_data is _STAGE_RESULT_UNREAD else metrics_data
    if not isinstance(data, dict):
        return [f"STAGE_RESULT_SHAPE: {where}: metrics_file must contain a JSON object"]
    if expected_metrics_file is not None             and eutil.norm_uri(str(metrics_file or "")) != eutil.norm_uri(expected_metrics_file):
        errs.append(f"STAGE_RESULT_METRICS_PATH: {where}: metrics_file must equal the seed-resolved declared "
                    f"path {expected_metrics_file!r}, got {metrics_file!r}")
    if expected_seed is not None and _seed_token(data.get("seed")) != _seed_token(expected_seed):
        errs.append(f"STAGE_RESULT_SEED: {where}: metrics JSON seed must equal this workflow lane's "
                    f"declared seed {expected_seed!r}")
    authored_decisions = [k for k in ("passed", "gate", "scientific_decision", "continuation")
                          if k in data]
    if authored_decisions:
        errs.append(f"STAGE_RESULT_SELF_DECISION: {where}: result fields {authored_decisions} may not control "
                    "the workflow; declare continuation_gate predicates in NODE_SPEC and let the engine compute them")
    summary = data.get("summary")
    if not isinstance(summary, dict) or not any(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))
            for v in summary.values()):
        errs.append(f"STAGE_RESULT_SUMMARY: {where}: metrics JSON needs summary with >=1 finite numeric measurement")
    limits = ((stage.get("budget") or {}).get("limits") or {})
    usage = data.get("usage")
    if not isinstance(usage, dict):
        errs.append(f"STAGE_RESULT_USAGE: {where}: metrics JSON needs usage for every declared budget unit")
        usage = {}
    band = max(econfig.budget_tolerance(ctx.cfg), float(budget_band_floor or 1.0))
    for unit, limit in limits.items():
        actual = usage.get(unit)
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or \
                not math.isfinite(float(actual)) or float(actual) < 0:
            errs.append(f"STAGE_RESULT_USAGE_VALUE: {where}: usage.{unit} must be finite and >= 0")
        elif isinstance(limit, (int, float)) and float(actual) > float(limit) * band + 1e-12:
            # v12: validity band (see econfig.budget_tolerance). The recorded
            # usage stays the actual measurement either way; only the
            # valid/invalid judgment moves with the band.
            errs.append(f"STAGE_RESULT_BUDGET_EXCEEDED: {where}: usage.{unit}={actual} exceeds declared cap "
                        + (f"{limit} * stage_budget_tolerance {band} = {float(limit) * band:g}" if band > 1.0
                           else f"{limit} (strict)")
                        + "; the RUN's execution stands and its evidence waits: if the overage is "
                          "acceptable, raise the config key stage_budget_tolerance (>= actual/cap) and "
                          "'evo run-reconcile --run <this RUN>' re-ingests THIS evidence - no rerun")
    if ((stage.get("control") or {}).get("mode") == "preregistered_adaptive"):
        _nontrivial(data.get("stop_reason"), 15,
                    f"{where}.stop_reason (which preregistered stopping condition fired)", errs)
    if econfig.stage_requires_ledger(stage):
        if expected_ledger_file is not None                 and eutil.norm_uri(str(ledger_file or "")) != eutil.norm_uri(expected_ledger_file):
            errs.append(f"STAGE_RESULT_LEDGER_PATH: {where}: ledger_file must equal the seed-resolved declared "
                        f"path {expected_ledger_file!r}, got {ledger_file!r}")
        if not ledger_file or not _exists(ctx, ledger_file):
            errs.append(f"STAGE_RESULT_LEDGER: {where}: adaptive/algorithmic multiplicity requires an existing ledger_file")
        else:
            try:
                if not eutil.read_text(eutil.rpath(ctx.store.repo, ledger_file)).strip():
                    errs.append(f"STAGE_RESULT_LEDGER_EMPTY: {where}: ledger_file is empty")
            except (OSError, UnicodeError):
                errs.append(f"STAGE_RESULT_LEDGER_READ: {where}: ledger_file could not be read")
    continuation = stage.get("continuation_gate")
    if isinstance(continuation, dict) and isinstance(summary, dict):
        for pred in continuation.get("predicates") or []:
            if not isinstance(pred, dict):
                continue
            metric = str(pred.get("metric") or "")
            observed = summary.get(metric)
            if isinstance(observed, bool) or not isinstance(observed, (int, float)) or \
                    not math.isfinite(float(observed)):
                errs.append(f"STAGE_RESULT_GATE_METRIC: {where}: continuation gate needs finite numeric "
                            f"summary.{metric}; a missing gate observation is an evidence failure, not a scientific stop")
    # R8 audit: a completed stage must have PRODUCED its declared products.
    # Well-shaped metrics said nothing about the output contract, so a job
    # that silently wrote no checkpoint still advanced the workflow (the
    # registry row went invalid with nobody reading the result), and after an
    # implementation revision the PREVIOUS implementation's bytes still at
    # the URI were re-attributed to the new RUN. Local declared products must
    # exist at settlement; prepare-time archiving guarantees whatever exists
    # was written by THIS attempt. Remote scheme URIs keep their
    # producer-receipt protocol.
    for p_row in (stage.get("produces") or []):
        if not isinstance(p_row, dict):
            continue
        uri = str(p_row.get("uri") or "")
        if not uri or "://" in uri:
            continue
        resolved = str(econfig.resolve_seed_template(uri, expected_seed)) \
            if expected_seed is not None else uri
        if "{" in resolved:
            continue  # unresolved template: existence is not decidable here
        if not eutil.rpath(ctx.store.repo, resolved).exists():
            errs.append(f"STAGE_PRODUCT_MISSING: {where}: declared product "
                        f"'{str(p_row.get('name') or resolved)}' was not produced at {resolved!r} - "
                        "a completed stage must write every produces[] entry in THIS attempt "
                        "(pre-existing bytes were archived at prepare; an earlier attempt's "
                        "output does not satisfy a new attempt's contract)")
    return errs


def stage_gate_decision(stage: dict, metrics: dict) -> dict | None:
    """Compute an optional pre-registered continuation gate from stage metrics.

    Callers must run ``stage_result_errors`` first. Invalid input raises instead
    of silently continuing an expensive workflow.
    """
    gate = stage.get("continuation_gate")
    if not isinstance(gate, dict):
        return None
    aggregation = str(gate.get("aggregation") or "")
    if aggregation not in econfig.STAGE_GATE_AGGREGATIONS:
        raise ValueError(f"unsupported continuation aggregation {aggregation!r}")
    if gate.get("on_miss") != "stop_node":
        raise ValueError(f"unsupported continuation miss action {gate.get('on_miss')!r}")
    summary = metrics.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("continuation gate requires a summary object")
    evaluations: list[dict] = []
    for pred in gate.get("predicates") or []:
        metric = str(pred.get("metric") or "")
        observed = summary.get(metric)
        threshold = pred.get("value")
        if isinstance(observed, bool) or not isinstance(observed, (int, float)) or \
                not math.isfinite(float(observed)):
            raise ValueError(f"continuation gate metric {metric!r} is missing or non-finite")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or \
                not math.isfinite(float(threshold)):
            raise ValueError(f"continuation gate threshold for {metric!r} is not finite numeric evidence")
        comparison = str(pred.get("comparison") or "")
        if comparison == ">":
            passed = float(observed) > float(threshold)
        elif comparison == ">=":
            passed = float(observed) >= float(threshold)
        elif comparison == "<":
            passed = float(observed) < float(threshold)
        elif comparison == "<=":
            passed = float(observed) <= float(threshold)
        else:
            raise ValueError(f"unsupported continuation comparison {comparison!r}")
        evaluations.append({"metric": metric, "comparison": comparison,
                            "value": threshold, "observed": observed, "passed": passed})
    if not evaluations:
        raise ValueError("continuation gate has no predicates")
    gate_passed = all(x["passed"] for x in evaluations) \
        if aggregation == "all" else any(x["passed"] for x in evaluations)
    return {
        "id": str(gate.get("id") or ""),
        "aggregation": aggregation,
        "outcome": "continue" if gate_passed else "stop_node",
        "predicates": evaluations,
        "assumptions": list(gate.get("assumptions") or []),
        "rationale": str(gate.get("rationale") or ""),
    }


def _seed_token(value: Any) -> str | None:
    """Canonical seed identity without treating bool as integer seed 0/1."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return f"i:{value}"
    if isinstance(value, str) and value.strip():
        return f"s:{value.strip()}"
    return None


def training_replication_errors(ctx: Ctx, spec: dict, *, role: str, where: str) -> list[str]:
    """Bind node execution to the user-confirmed full-training repeat policy.

    A seed is always recorded for train/finetune work. Under a preplanned
    protocol, each seed traverses the complete ordered workflow. Seed repeats
    are never hidden inside one stage. Targeted ablations stay single-run so
    ablation x seed cannot appear as a hidden Cartesian product.
    """
    errs: list[str] = []
    cls = econfig.experiment_class(spec)
    purpose = str(spec.get("experiment_purpose") or "")
    rep = spec.get("training_replication")
    stages = econfig.stages_of(spec)
    if cls not in ("train", "finetune"):
        if rep is not None:
            errs.append(f"SPEC_TRAINING_REPLICATION_NONTRAIN: {where}: training_replication is only legal for "
                        "train|finetune experiment classes")
        return errs
    if not isinstance(rep, dict):
        return [f"SPEC_TRAINING_REPLICATION: {where}: train|finetune specs must explicitly record whether "
                "this is one training seed or a user-approved preplanned repeat set"]
    mode = rep.get("mode")
    runs = rep.get("runs")
    seeds = rep.get("seeds")
    aggregation = rep.get("aggregation")
    source = rep.get("source")
    if mode not in ("single", "preplanned"):
        errs.append(f"SPEC_TRAINING_REPLICATION_MODE: {where}: mode must be single|preplanned")
    if not isinstance(runs, int) or isinstance(runs, bool) or runs < 1:
        errs.append(f"SPEC_TRAINING_REPLICATION_RUNS: {where}: runs must be an integer >= 1")
    if not isinstance(seeds, list) or not seeds:
        errs.append(f"SPEC_TRAINING_REPLICATION_SEEDS: {where}: seeds must explicitly list every training seed")
        seeds = []
    tokens = [_seed_token(x) for x in seeds]
    if any(x is None for x in tokens):
        errs.append(f"SPEC_TRAINING_REPLICATION_SEED_VALUE: {where}: every seed must be an integer or non-empty string")
    seed_slugs: list[str] = []
    for seed in seeds:
        if _seed_token(seed) is None:
            continue
        try:
            seed_slugs.append(econfig.seed_slug(seed))
        except ValueError:
            errs.append(f"SPEC_TRAINING_REPLICATION_SEED_PATH: {where}: string seeds must match "
                        "[A-Za-z0-9][A-Za-z0-9_-]{0,63} so commands and artifact paths are unambiguous")
    if len([x for x in tokens if x is not None]) != len(set(x for x in tokens if x is not None)):
        errs.append(f"SPEC_TRAINING_REPLICATION_SEED_DUP: {where}: training seeds must be unique")
    if len(seed_slugs) != len({slug.casefold() for slug in seed_slugs}):
        errs.append(f"SPEC_TRAINING_REPLICATION_SEED_PATH_COLLISION: {where}: seeds must remain unique after "
                    "filesystem rendering (for example integer 1 vs string '1', or 'A' vs 'a')")
    if isinstance(runs, int) and not isinstance(runs, bool) and len(seeds) != runs:
        errs.append(f"SPEC_TRAINING_REPLICATION_SEED_COUNT: {where}: len(seeds) must equal runs={runs}")
    if aggregation not in econfig.TRAINING_REPLICATION_AGGREGATIONS:
        errs.append(f"SPEC_TRAINING_REPLICATION_AGGREGATION: {where}: aggregation must be one of "
                    f"{econfig.TRAINING_REPLICATION_AGGREGATIONS}")
    if source not in ("workflow", "existing_artifacts"):
        errs.append(f"SPEC_TRAINING_REPLICATION_SOURCE: {where}: source must be workflow|existing_artifacts")
    if source == "existing_artifacts" and stages:
        errs.append(f"SPEC_TRAINING_REPLICATION_EXISTING_WITH_WORKFLOW: {where}: existing_artifacts is only for "
                    "a pre-existing baseline/platform without workflow stages")
    if source == "workflow" and not stages:
        errs.append(f"SPEC_TRAINING_REPLICATION_WORKFLOW_MISSING: {where}: source=workflow needs workflow stages")
    if rep.get("stage") not in (None, ""):
        errs.append(f"SPEC_TRAINING_REPLICATION_STAGE_OBSOLETE: {where}: training_replication.stage is obsolete; "
                    "every declared seed repeats every workflow stage")

    policy = econfig.training_replication_policy(ctx.cfg)
    should_repeat = policy.get("mode") == "preplanned" and role != "platform" and purpose == "candidate"
    if should_repeat:
        expected_runs = policy.get("planned_runs")
        expected_agg = policy.get("aggregation")
        if mode != "preplanned" or runs != expected_runs or aggregation != expected_agg:
            errs.append(f"SPEC_TRAINING_REPLICATION_POLICY: {where}: the approved project protocol requires "
                        f"preplanned runs={expected_runs}, aggregation={expected_agg}")
        if source == "workflow":
            # A continuation gate would let one seed skip later stages, which is
            # no longer the same complete-run protocol. Aggregate decisions are
            # made only after every seed reaches final evaluation.
            gated = [str(s.get("name") or "?") for s in stages if s.get("continuation_gate") is not None]
            if gated:
                errs.append(f"SPEC_TRAINING_REPLICATION_PARTIAL_WORKFLOW: {where}: preplanned seed repeats must "
                            f"traverse the complete workflow; continuation gates are present on {gated}")
            resolved_uris: dict[str, str] = {}  # keyed by canonical spelling (identity sweep #8)
            for i, stage in enumerate(stages):
                sw = f"{where}.stage[{i}]({stage.get('name')})"
                for field in ("launch", "metrics_file"):
                    if "{seed}" not in str(stage.get(field) or ""):
                        errs.append(f"SPEC_TRAINING_REPLICATION_TEMPLATE: {sw}.{field} must contain literal "
                                    "'{seed}' so every complete run receives its seed and writes separately")
                if econfig.stage_requires_ledger(stage) and "{seed}" not in str(stage.get("ledger_file") or ""):
                    errs.append(f"SPEC_TRAINING_REPLICATION_TEMPLATE: {sw}.ledger_file must contain literal "
                                "'{seed}' so adaptive/component traces cannot overwrite one another")
                produces = stage.get("produces") or []
                if produces and "{seed}" not in str(stage.get("stage_key") or ""):
                    errs.append(f"SPEC_TRAINING_REPLICATION_TEMPLATE: {sw}.stage_key must contain literal "
                                "'{seed}' for per-seed artifact identity")
                for j, product in enumerate(produces):
                    uri = str((product or {}).get("uri") or "")
                    if "{seed}" not in uri:
                        errs.append(f"SPEC_TRAINING_REPLICATION_TEMPLATE: {sw}.produces[{j}].uri must contain "
                                    "literal '{seed}' to prevent checkpoint overwrite")
                        continue
                    for seed in seeds:
                        try:
                            resolved = str(econfig.resolve_seed_template(uri, seed))
                        except ValueError:
                            continue
                        canon = eutil.norm_uri(resolved)
                        owner = resolved_uris.get(canon)
                        if owner is not None:
                            errs.append(f"SPEC_TRAINING_REPLICATION_URI_DUP: {sw}.produces[{j}] resolves to "
                                        f"{resolved!r}, already used by {owner}")
                        else:
                            resolved_uris[canon] = f"{stage.get('name')}/seed={seed}"
                        clash = eartifact.find_overlapping(ctx.reg, resolved)
                        if clash is not None:
                            errs.append(f"SPEC_TRAINING_REPLICATION_URI_COLLISION: {sw}.produces[{j}] seed "
                                        f"{seed!r} resolves to registered URI {resolved!r} ({clash.get('id')})")
        elif source == "existing_artifacts" and role not in ("baseline", "platform"):
            errs.append(f"SPEC_TRAINING_REPLICATION_EXISTING_ROLE: {where}: only a pre-existing baseline/platform "
                        "may satisfy preplanned repeats from existing artifacts")
    else:
        if mode != "single" or runs != 1 or aggregation != "none":
            errs.append(f"SPEC_TRAINING_REPLICATION_SINGLE: {where}: this node is not covered by a preplanned "
                        "repeat protocol and must use one recorded seed with no aggregation")
    return errs


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _workdir_isolation_errors(ctx: Ctx, spec: dict, *, role: str, where: str,
                              current_node_id: str | None = None) -> list[str]:
    """Reject node workareas that alias an existing execution checkout."""
    stored = str(spec.get("workdir") or "").strip()
    if not stored:
        return []
    try:
        proposed = eutil.rpath(ctx.store.repo, stored).resolve(strict=False)
        repo_root = ctx.store.repo.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        return [f"SPEC_WORKDIR_INVALID: {where}: workdir {stored!r} cannot be resolved safely: {exc}"]

    errs: list[str] = []
    if role != "baseline" and proposed == repo_root:
        errs.append(f"SPEC_WORKDIR_ROOT: {where}: non-baseline nodes need an isolated workdir, not the project root")
    if role != "baseline" and "branch" in spec:
        errs.append(f"SPEC_BRANCH_ENGINE_OWNED: {where}: branch is assigned by the engine; omit spec.branch")

    for node in ctx.g.get("nodes", []):
        if current_node_id and str((node or {}).get("id") or "") == current_node_id:
            continue
        prior_stored = str((node or {}).get("workdir") or "").strip()
        if not prior_stored:
            continue
        try:
            prior = eutil.rpath(ctx.store.repo, prior_stored).resolve(strict=False)
        except (OSError, RuntimeError):
            continue
        if proposed == prior:
            errs.append(
                f"SPEC_WORKDIR_COLLISION: {where}: workdir {stored!r} resolves to the same path as "
                f"node {node.get('id')} workdir {prior_stored!r}")
            continue
        # Candidate worktrees normally live below the baseline repository, so
        # that one containment relation is intentional.  Distinct non-baseline
        # workareas must not contain one another: their manifests and live
        # source paths would otherwise overlap.
        if node.get("role") != "baseline" and (
                _path_is_within(proposed, prior) or _path_is_within(prior, proposed)):
            errs.append(
                f"SPEC_WORKDIR_OVERLAP: {where}: workdir {stored!r} overlaps node {node.get('id')} "
                f"workdir {prior_stored!r}")
        elif node.get("role") == "baseline" and _path_is_within(prior, proposed):
            errs.append(
                f"SPEC_WORKDIR_OVERLAP: {where}: workdir {stored!r} would contain baseline node "
                f"{node.get('id')} workdir {prior_stored!r}")
    return errs


def _spec_errors(ctx: Ctx, spec: dict, *, expect_role: str, expect_parents: list[str] | None,
                 expect_level: int | None, where: str,
                 exclude_node: str | None = None,
                 receipts: dict | None = None) -> list[str]:
    errs: list[str] = []
    idx = egraph.by_id(ctx.g)
    role = spec.get("role")
    purpose = spec.get("experiment_purpose")
    if spec.get("role") != expect_role:
        errs.append(f"SPEC_ROLE: {where}: role must be '{expect_role}' (got {spec.get('role')!r})")
    if expect_parents is not None and list(spec.get("parents") or []) != list(expect_parents):
        errs.append(f"SPEC_PARENTS: {where}: parents must equal {expect_parents} (idea/lane contract), got {spec.get('parents')}")
    if expect_level is not None and spec.get("level") != expect_level:
        errs.append(f"SPEC_LEVEL: {where}: level must equal the idea's computed level L{expect_level}")
    _nontrivial(spec.get("title"), 8, f"{where}.title", errs)
    if spec.get("cost_class") not in econfig.COST_CLASSES:
        errs.append(f"SPEC_COST: {where}: cost_class must be one of {econfig.COST_CLASSES} "
                    f"(api-heavy experiments count their token budget as cost, not just GPU time)")
    if spec.get("experiment_class") not in econfig.EXPERIMENT_CLASSES:
        errs.append(f"SPEC_EXPERIMENT_CLASS: {where}: experiment_class must be one of "
                    f"{econfig.EXPERIMENT_CLASSES}; it is required for every new node")
    if purpose not in econfig.EXPERIMENT_PURPOSES:
        errs.append(f"SPEC_EXPERIMENT_PURPOSE: {where}: experiment_purpose must be one of "
                    f"{econfig.EXPERIMENT_PURPOSES}")
    if purpose in econfig.INSTRUMENTAL_PURPOSES and role != "variant":
        errs.append(f"SPEC_INSTRUMENTAL_ROLE: {where}: {purpose} must be a single-parent variant")
    if purpose == "targeted_ablation" and not isinstance(spec.get("ablation"), dict):
        errs.append(f"SPEC_ABLATION_SCHEMA: {where}: targeted_ablation must copy its approved ablation contract")
    if purpose != "targeted_ablation" and spec.get("ablation") is not None:
        errs.append(f"SPEC_ABLATION_UNDECLARED: {where}: only targeted_ablation specs carry ablation")
    if purpose == "diagnostic_probe" and not isinstance(spec.get("probe"), dict):
        errs.append(f"SPEC_PROBE_CONTRACT_SCHEMA: {where}: diagnostic_probe must copy its approved probe contract")
    if purpose != "diagnostic_probe" and spec.get("probe") is not None:
        errs.append(f"SPEC_PROBE_CONTRACT_UNDECLARED: {where}: only diagnostic_probe specs carry probe")
    if purpose == "maintenance" and not isinstance(spec.get("maintenance"), dict):
        errs.append(f"SPEC_MAINTENANCE_SCHEMA: {where}: maintenance must copy its approved maintenance contract")
    if purpose != "maintenance" and spec.get("maintenance") is not None:
        errs.append(f"SPEC_MAINTENANCE_UNDECLARED: {where}: only maintenance specs carry maintenance")
    if purpose == "diagnostic_probe":
        cap = (spec.get("probe") or {}).get("budget") if isinstance(spec.get("probe"), dict) else None
        if isinstance(cap, dict) and cap:
            planned: dict[str, float] = {}
            for stage in econfig.stages_of(spec):
                for unit, value in econfig.tracked_budget((stage or {}).get("budget"), ctx.cfg).items():
                    planned[unit] = planned.get(unit, 0.0) + float(value)
            for unit, value in econfig.tracked_budget(((spec.get("eval") or {}).get("budget")), ctx.cfg).items():
                planned[unit] = planned.get(unit, 0.0) + float(value)
            for unit, value in cap.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool) \
                        and planned.get(str(unit), 0.0) > float(value) + 1e-9:
                    errs.append(f"SPEC_PROBE_BUDGET_EXCEEDED: {where}: planned {unit} "
                                f"{planned.get(str(unit), 0.0):g} exceeds the approved probe cap {value:g}")
    if "evidence_budget" in spec:
        errs.append(f"SPEC_EVIDENCE_BUDGET_LEGACY: {where}: evidence_budget/extra_costly_arms was ambiguous; "
                    "use evidence_plan for cheap checks and the separate training_replication/ablation contracts")
    evidence_plan = spec.get("evidence_plan")
    if not isinstance(evidence_plan, dict):
        errs.append(f"SPEC_EVIDENCE_PLAN: {where}: evidence_plan object required for explicit cheap checks")
        evidence_plan = {}
    extra_eval = evidence_plan.get("extra_eval_arms")
    eval_cap = int((ctx.cfg.get("evidence_policy") or {}).get("max_extra_eval_arms_per_node", 0))
    if not isinstance(extra_eval, int) or not (0 <= extra_eval <= eval_cap):
        errs.append(f"SPEC_EXTRA_EVAL_ARMS: {where}: extra_eval_arms must be an integer 0..{eval_cap}")
    declared = evidence_plan.get("declared_checks")
    if not isinstance(declared, list):
        errs.append(f"SPEC_DECLARED_CHECKS: {where}: evidence_plan.declared_checks must be a list (may be empty)")
    if isinstance(extra_eval, int) and extra_eval > 0:
        _nontrivial(evidence_plan.get("value_of_information"), 60,
                    f"{where}.evidence_plan.value_of_information", errs)
    wd = str(spec.get("workdir") or "").strip()
    if not wd:
        errs.append(f"SPEC_WORKDIR: {where}: workdir required (where this node's code lives)")
    else:
        errs.extend(_workdir_isolation_errors(ctx, spec, role=str(role or ""), where=where))
    cp = spec.get("code_parent")
    if role == "baseline":
        if cp is not None:
            errs.append(f"SPEC_CODE_PARENT: {where}: baseline has no code_parent")
    else:
        if cp is not None and cp not in idx:
            errs.append(f"SPEC_CODE_PARENT_UNKNOWN: {where}: code_parent {cp!r} not in graph")
        model_parents = [p for p in (spec.get("parents") or []) if p in idx and idx[p].get("role") != "platform"]
        if role == "variant" and cp not in model_parents:
            errs.append(f"SPEC_CODE_PARENT_VARIANT: {where}: variant code_parent must be its model parent")
        if role == "hybrid" and cp not in model_parents:
            errs.append(f"SPEC_CODE_PARENT_HYBRID: {where}: hybrid code_parent must be one of its model parents")
        if role in ("root", "platform") and cp is None:
            errs.append(f"SPEC_CODE_PARENT_ROOT: {where}: root/platform must name a code_parent (which codebase to start from, usually the baseline)")
    smoke = spec.get("smoke_plan")
    if not isinstance(smoke, list) or not smoke:
        errs.append(f"SPEC_SMOKE: {where}: smoke_plan must be a non-empty list of steps")
    else:
        for i, stp in enumerate(smoke):
            if not isinstance(stp, dict):
                errs.append(f"SPEC_SMOKE_STEP: {where}: smoke_plan[{i}] must be an object with 'name' and 'cmd'")
                continue
            if not str(stp.get("name") or "").strip() or not str(stp.get("cmd") or "").strip():
                errs.append(f"SPEC_SMOKE_STEP: {where}: smoke_plan[{i}] needs 'name' and 'cmd'")
            for fld in ("timeout_s", "expect_exit"):
                if stp.get(fld) is not None:
                    try:
                        int(stp.get(fld))
                    except (TypeError, ValueError):
                        # a sealed spec with "300s" here would wedge the node at
                        # run-smoke with no revision verb - refuse pre-seal
                        errs.append(f"SPEC_SMOKE_STEP: {where}: smoke_plan[{i}].{fld} must be an integer")
    if role == "platform":
        if not isinstance(spec.get("enables"), list) or len(spec.get("enables") or []) < 2:
            errs.append(f"SPEC_ENABLES: {where}: a platform must list >= 2 prospective consumers/uses in 'enables'")
    else:
        ev = spec.get("eval") or {}
        if not str(ev.get("run") or "").strip() or not str(ev.get("metrics_file") or "").strip():
            errs.append(f"SPEC_EVAL: {where}: eval.run and eval.metrics_file required")
        harness = ev.get("harness")
        if harness is not None:
            # E9 (2025+ survey): hardware-in-the-loop / interactive evaluation
            # uses trial-count semantics, not seed replication, and must
            # disclose its manual-reset and non-determinism protocol.
            if not isinstance(harness, dict) or str(harness.get("type") or "") not in (
                    "standard", "physical", "interactive"):
                errs.append(f"SPEC_EVAL_HARNESS: {where}: eval.harness.type must be "
                            "standard|physical|interactive")
            elif harness.get("type") in ("physical", "interactive"):
                trials = harness.get("trials")
                if isinstance(trials, bool) or not isinstance(trials, int) or trials < 1:
                    errs.append(f"SPEC_EVAL_HARNESS_TRIALS: {where}: a physical/interactive harness "
                                "must preregister trials as an integer >= 1")
                if str(harness.get("reset") or "") not in ("manual", "auto"):
                    errs.append(f"SPEC_EVAL_HARNESS_RESET: {where}: eval.harness.reset must be manual|auto")
                if len(str(harness.get("nondeterminism_note") or "").strip()) < 40:
                    errs.append(f"SPEC_EVAL_HARNESS_NOTE: {where}: eval.harness.nondeterminism_note "
                                "(>= 40 chars) must state what varies between trials and why seeds "
                                "cannot control it")
        protocol = ev.get("protocol")
        if isinstance(protocol, dict) and str(protocol.get("type") or "") == "streaming":
            # E4: order-dependent (online-within-eval) protocols freeze the
            # episode order and declare sequential dependence explicitly.
            order_rel = str(protocol.get("episode_order_file") or "")
            order_bad = (not order_rel or order_rel.startswith(("/", "\\"))
                         or (len(order_rel) > 1 and order_rel[1] == ":")
                         or ".." in order_rel.replace("\\", "/").split("/"))
            if order_bad or not eutil.rpath(ctx.store.repo, order_rel).is_file():
                errs.append(f"SPEC_EVAL_STREAMING_ORDER: {where}: eval.protocol.episode_order_file "
                            "must be a repo-relative existing FILE (no absolute paths, no '..'); "
                            "its bytes are sealed with the evaluation")
            if protocol.get("sequential_dependence") is not True:
                errs.append(f"SPEC_EVAL_STREAMING_DEPENDENCE: {where}: a streaming protocol must set "
                            "sequential_dependence=true - episode order changes the numbers and the "
                            "uncertainty method must account for it")
        transductive = ev.get("transductive")
        if transductive is not None and not isinstance(transductive, dict):
            errs.append(f"SPEC_EVAL_TRANSDUCTIVE: {where}: eval.transductive must be an object")
            transductive = None
        if transductive is not None:
            # E4: test-time training may see a cell's UNLABELED inputs when the
            # contract says so and the reward/verifier is argued label-free.
            cells_known = set(econfig.cell_spec(ctx.cfg))
            t_cells = transductive.get("cells") if isinstance(transductive, dict) else None
            if not isinstance(t_cells, list) or not t_cells or \
                    any(str(c) not in cells_known for c in t_cells):
                errs.append(f"SPEC_EVAL_TRANSDUCTIVE_CELLS: {where}: eval.transductive.cells must "
                            "name configured C# cells whose unlabeled test inputs the node consumes")
            consuming = str((transductive or {}).get("consuming_stage") or "")
            stage_names = {str(x.get("name") or "") for x in econfig.stages_of(spec)}
            if consuming not in stage_names:
                errs.append(f"SPEC_EVAL_TRANSDUCTIVE_STAGE: {where}: eval.transductive.consuming_stage "
                            "must name the workflow stage that consumes the unlabeled test inputs "
                            f"(declared stages: {sorted(stage_names) or 'none'})")
            if len(str((transductive or {}).get("verifier_label_free_argument") or "").strip()) < 60:
                errs.append(f"SPEC_EVAL_TRANSDUCTIVE_VERIFIER: {where}: "
                            "eval.transductive.verifier_label_free_argument (>= 60 chars) must argue "
                            "why the training signal uses no test labels")
        accounting = ev.get("resource_accounting")
        if not isinstance(accounting, dict):
            errs.append(f"SPEC_RESOURCE_ACCOUNTING: {where}: eval.resource_accounting must freeze how "
                        "every scientific resource axis is measured before execution")
            accounting = {}
        spec_axes = econfig.resource_axes(ctx.cfg)
        missing_axes = [axis for axis in spec_axes if axis not in accounting]
        extra_axes = [axis for axis in accounting if axis not in spec_axes]
        if missing_axes or extra_axes:
            errs.append(f"SPEC_RESOURCE_ACCOUNTING_AXES: {where}: resource_accounting must use exactly "
                        f"{spec_axes}; missing={missing_axes}, extra={extra_axes}")
        # R10-019: extension axes were frozen with an accounting method at
        # configure time (they enter every candidate vector, receipt and
        # frontier comparison) - the NODE_SPEC row must copy that method
        # verbatim, or a spec could silently swap to another allowed method
        # and the receipt chain would seal the drifted one.
        frozen_ext_accounting = {
            str(r.get("key") or ""): str(r.get("accounting") or "")
            for r in (((ctx.cfg.get("resource_contract") or {}).get("extension_axes")) or [])
            if isinstance(r, dict)}
        for axis in spec_axes:
            row = accounting.get(axis)
            if not isinstance(row, dict) or set(row) != {"method", "description"}:
                errs.append(f"SPEC_RESOURCE_ACCOUNTING_ROW: {where}: resource_accounting.{axis} must use "
                            "exactly method, description")
                continue
            if row.get("method") not in eprogram.RESOURCE_ACCOUNTING_METHODS:
                errs.append(f"SPEC_RESOURCE_ACCOUNTING_METHOD: {where}: resource_accounting.{axis}.method "
                            f"must be one of {eprogram.RESOURCE_ACCOUNTING_METHODS}")
            frozen = frozen_ext_accounting.get(axis)
            if frozen and str(row.get("method") or "") != frozen:
                errs.append(f"SPEC_RESOURCE_ACCOUNTING_FROZEN: {where}: resource_accounting.{axis}.method "
                            f"{row.get('method')!r} must equal the configure-time frozen accounting "
                            f"{frozen!r} for this extension axis")
            _nontrivial(row.get("description"), 40,
                        f"{where}.resource_accounting.{axis}.description (what the evaluator counts)", errs)
        eval_budget = ev.get("budget")
        eval_limits = econfig.budget_limits(eval_budget)
        if not eval_limits:
            errs.append(f"SPEC_EVAL_BUDGET: {where}: eval.budget.limits must be a non-empty map of finite resource caps")
        else:
            raw_eval_limits = ((eval_budget or {}).get("limits") or {}) if isinstance(eval_budget, dict) else {}
            for unit, limit in raw_eval_limits.items():
                if not re.fullmatch(r"[a-z][a-z0-9_]{1,47}", str(unit or "")):
                    errs.append(f"SPEC_EVAL_BUDGET_UNIT: {where}: eval budget unit {unit!r} must be a lowercase slug")
                if isinstance(limit, bool) or not isinstance(limit, (int, float)) or \
                        not math.isfinite(float(limit)) or float(limit) <= 0:
                    errs.append(f"SPEC_EVAL_BUDGET_VALUE: {where}: eval budget limit {unit!r} must be finite and > 0")
            if not econfig.tracked_budget(eval_budget, ctx.cfg):
                errs.append(f"SPEC_EVAL_PROJECT_BUDGET: {where}: at least one eval budget unit must appear in the "
                            "user-confirmed project resource_contract")
        # judge pinning (v8): LLM-as-judge / simulated-user evals are comparable
        # across nodes ONLY under the identical judge config. A node that
        # declares a judge must match the baseline's exactly - judge drift
        # silently voids every verdict in the graph.
        if role != "baseline" and (ev.get("judge") is not None or ev.get("protocol") is not None):
            base = next((n for n in ctx.g.get("nodes", []) if n.get("role") == "baseline"), None)
            base_ev = (eutil.read_json(eutil.rpath(ctx.store.repo, (base or {}).get("spec") or ""), {})
                       or {}).get("eval") or {}
            if ev.get("judge") is not None and base_ev.get("judge") != ev.get("judge"):
                errs.append(f"SPEC_JUDGE_MISMATCH: {where}: eval.judge must EQUAL the baseline's judge "
                            f"config (baseline: {base_ev.get('judge')!r}) - model, version and params "
                            f"pinned; a drifted judge voids cross-node comparability")
            # arena/pairwise protocol pinning (v8): win-rates and Elo are only
            # comparable under the identical opponent pool, harness version and
            # sampling setup - pin the whole protocol object like the judge
            if ev.get("protocol") is not None and base_ev.get("protocol") != ev.get("protocol"):
                errs.append(f"SPEC_PROTOCOL_MISMATCH: {where}: eval.protocol must EQUAL the baseline's "
                            f"(baseline: {base_ev.get('protocol')!r}) - opponent pool / harness version / "
                            f"sampling params pinned; a drifted arena voids every win-rate in the graph")
    # service dependencies (v8): experiments lean on runtime surfaces beyond the
    # trainer - a served model (RL rollouts, distillation teachers, judge loops),
    # a KG/SPARQL endpoint (KGQA retrieval), a vector store, a sandbox. A spec
    # declares requires_llm / requires_services; every name must resolve to the
    # infra facts' llm block or services registry, or the run discovers the gap
    # mid-flight (the Virtuoso-was-down failure class).
    req: set[str] = set()
    ev_dep = spec.get("eval") or {}
    if ev_dep.get("requires_llm"):
        req.add("llm")
    for name in (ev_dep.get("requires_services") or []):
        req.add(str(name))
    for s in econfig.stages_of(spec):
        if s.get("requires_llm"):
            req.add("llm")
        for name in (s.get("requires_services") or []):
            req.add(str(name))
    if req:
        have = einfra.service_names(ctx.store, ctx.cfg, ctx.g)
        # E3: a service pinned as pinning="recorded" in the infra facts is a
        # drifting external surface; comparisons must consume or produce a
        # service_snapshot artifact (or state an explicit waiver).
        recorded = einfra.recorded_service_names(ctx.store, ctx.cfg)
        wants_recorded = sorted(req & recorded)
        if wants_recorded:
            snapshot_touch = False
            for s_row in econfig.stages_of(spec):
                for produce in (s_row.get("produces") or []):
                    if isinstance(produce, dict) and str(produce.get("kind") or "") == "service_snapshot":
                        snapshot_touch = True
                for consume in (s_row.get("consumes") or []):
                    if isinstance(consume, dict) and str(consume.get("artifact") or ""):
                        art = eartifact.by_id(ctx.reg).get(str(consume.get("artifact")))
                        if art is not None and str(art.get("kind") or "") == "service_snapshot":
                            snapshot_touch = True
            waiver = str(spec.get("service_snapshot_waiver") or "").strip()
            if not snapshot_touch and len(waiver) < 40:
                errs.append(f"SPEC_SERVICE_SNAPSHOT: {where}: services {wants_recorded} are pinned "
                            "'recorded' - consume/produce a service_snapshot artifact for replayable "
                            "comparisons, or state service_snapshot_waiver (>= 40 chars)")
        for name in sorted(req):
            if name in have:
                continue
            if name == "llm":
                errs.append(f"SPEC_REQUIRES_LLM: {where}: the spec declares requires_llm but INFRA_FACTS.json "
                            f"has no 'llm' block (how models are served/invoked on this platform) - re-run "
                            f"the infra scan to record it")
            else:
                errs.append(f"SPEC_REQUIRES_SERVICE: {where}: the spec requires service {name!r} but "
                            f"INFRA_FACTS.json declares no such entry in 'services' (declared: "
                            f"{sorted(have) or 'none'}) - record the endpoint in the infra facts (and drill "
                            f"it) before planning runs against it")
    errs.extend(_stage_errors(ctx, spec, role=str(role or "?"), where=where,
                              exclude_node=exclude_node, receipts=receipts))
    # v11.7: under project.rehearsal=full_chain every staged non-baseline spec
    # must plan its tiny full-chain pass up front - the duty is discovered at
    # planning time, not at the first launch refusal.
    if str((ctx.cfg.get("project") or {}).get("rehearsal") or "") == "full_chain" \
            and econfig.stages_of(spec) and str(role or "") != "baseline":
        errs.extend(erehearsal.plan_errors(spec, where=where))
    errs.extend(training_replication_errors(ctx, spec, role=str(role or "?"), where=where))
    return errs


def v_provision(ctx: Ctx, task: dict) -> list[str]:
    """Project preparation (v11.7, pre-configure): the mechanic did whatever
    CONSTRUCTIVE work the supplied project needed - fetch/wire data, build a
    minimal evaluation, fix bugs - until a first real end-to-end number
    exists, or reports TYPED blockers the user can act on. Every scientific
    choice made along the way (which data, which metric, which evaluation
    slice) is listed for the user's sign-off at the contract gate. Vague
    blockers are rejected - 'something is missing' is not a request the user
    can fulfill."""
    errs: list[str] = []
    text = _read_md(ctx, task["outputs"][0], errs)
    data = _read_json(ctx, task["outputs"][1], errs)
    if text is None or data is None:
        return errs
    _require_sections(text, ["what was run", "work performed", "choices", "blockers", "verdict"],
                      "PROVISION", errs, min_chars=20)
    status = data.get("status")
    if status not in ("ready", "blocked"):
        errs.append("PROVISION_STATUS: PROVISION.json status must be 'ready' or 'blocked'")
        return errs
    work = data.get("work") or []
    for i, f in enumerate(work):
        w = f"work[{i}]"
        _nontrivial(f.get("what"), 20, f"{w}.what (the gap or failure addressed)", errs)
        relp = str(f.get("file") or "")
        if not relp or not _exists(ctx, relp):
            errs.append(f"PROVISION_WORK_FILE: {w}: 'file' must name the real touched file (got {relp!r})")
        ev = str(f.get("evidence") or "")
        if not ev or not _exists(ctx, ev):
            errs.append(f"PROVISION_EVIDENCE: {w}: 'evidence' must point at a captured trace/log "
                        f"file proving the work was real (got {ev!r})")
    choices = data.get("choices")
    if not isinstance(choices, list):
        errs.append("PROVISION_CHOICES: choices must be a list (empty is legal when no scientific "
                    "decision was made) - each {decision, why} is shown to the user at the "
                    "contract gate for sign-off")
    else:
        for i, c in enumerate(choices):
            _nontrivial((c or {}).get("decision"), 15, f"choices[{i}].decision", errs)
            _nontrivial((c or {}).get("why"), 15, f"choices[{i}].why", errs)
    if status == "ready":
        if not work:
            _nontrivial(data.get("no_work_reason"), 30,
                        "no_work_reason (nothing needed doing - say what was checked)", errs)
        proof = data.get("proof") or {}
        logs = [p for p in (proof.get("logs") or []) if str(p or "").strip()]
        live = [p for p in logs if _exists(ctx, p)]
        if not live:
            errs.append("PROVISION_EVIDENCE: proof.logs must list >= 1 existing log of the micro "
                        "end-to-end pass (tiny train step + eval) - a 'ready' verdict without a "
                        "captured first real number is narration")
        metrics = proof.get("observed_metrics")
        finite = {k: v for k, v in (metrics or {}).items()
                  if isinstance(v, (int, float)) and not isinstance(v, bool)
                  and math.isfinite(float(v))} if isinstance(metrics, dict) else {}
        if not finite:
            errs.append("PROVISION_METRIC: proof.observed_metrics must carry >= 1 finite numeric "
                        "value actually produced by the micro pass - the first real number IS "
                        "the readiness proof, and configure freezes the contract against it")
        _nontrivial(proof.get("metric_basis"), 20,
                    "proof.metric_basis (which draft metric this number corresponds to and how "
                    "it was produced)", errs)
        _nontrivial(proof.get("note"), 30, "proof.note (what the micro pass demonstrated)", errs)
    else:  # blocked
        blockers = data.get("blockers") or []
        if not blockers:
            errs.append("PROVISION_BLOCKERS: a blocked preparation must list >= 1 typed blocker - "
                        "'blocked' without an actionable ask is indistinguishable from giving up")
        for i, b in enumerate(blockers):
            w = f"blockers[{i}]"
            _nontrivial(b.get("missing"), 15, f"{w}.missing (what does not exist / is not accessible)", errs)
            _nontrivial(b.get("needed_for"), 10, f"{w}.needed_for (which step it blocks)", errs)
            _nontrivial(b.get("ask"), 15, f"{w}.ask (the concrete, actionable request to the user)", errs)
    return errs


def v_baseline_spec(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    spec = load_spec(ctx, task["outputs"][0], errs)
    if spec is None:
        return errs
    errs.extend(_spec_errors(ctx, spec, expect_role="baseline", expect_parents=[], expect_level=None,
                             where="baseline spec",
                             exclude_node=str(task["subject"].get("node") or "") or None))
    return errs


def spec_wiring_expectations(spec: dict) -> tuple[list[str], list[str]]:
    """Source/sink tokens the artifact-wiring rows must cover: consumed
    artifacts (AR### or stage:<name>) and produced URIs, spec-order, deduped."""
    want_reads: list[str] = []
    want_writes: list[str] = []
    for stage in econfig.stages_of(spec):
        for entry in ((stage or {}).get("consumes") or []):
            if isinstance(entry, dict) and entry.get("artifact"):
                want_reads.append(str(entry["artifact"]))
            elif isinstance(entry, dict) and entry.get("stage"):
                want_reads.append(f"stage:{entry['stage']}")
        for product in ((stage or {}).get("produces") or []):
            if isinstance(product, dict) and product.get("uri"):
                want_writes.append(str(product["uri"]))
    return list(dict.fromkeys(want_reads)), list(dict.fromkeys(want_writes))


def artifact_wiring_errors(ctx: Ctx, node: dict, spec: dict, text: str) -> list[str]:
    """Bind the declared consumes/produces contract to literal code (v10.2).

    Wrong read paths and undeclared save locations were the highest-frequency
    infrastructure failure, and the cheapest place to catch them is implement
    time - before a stage burns real compute.  Like the fidelity/probe rows,
    this proves the agent LOOKED at the wiring code, not that the semantics
    are right; the string check makes hollow rows impossible.
    """
    errs: list[str] = []
    want_reads, want_writes = spec_wiring_expectations(spec)
    if not want_reads and not want_writes:
        return errs
    wiring = eutil.find_section(eutil.md_sections(text), "artifact wiring") or ""
    if not wiring.strip():
        errs.append("BUILD_WIRING_SECTION: the spec declares artifact consumes/produces; BUILD_REPORT "
                    "needs an '## Artifact wiring' section with one 'READS: <AR###|stage:<name>> -> "
                    "<file> :: CODE: <literal snippet>' row per input and one 'WRITES: <uri> -> <file> "
                    ":: CODE: <literal snippet>' row per produced uri")
        return errs
    wd = eutil.rpath(ctx.store.repo, str(node.get("workdir") or "."))
    reads = ARTIFACT_READ_ROW.findall(wiring)
    writes = ARTIFACT_WRITE_ROW.findall(wiring)
    wd_resolved = wd.resolve(strict=False)
    for kind, rows in (("READS", reads), ("WRITES", writes)):
        for token, rel, snippet in rows:
            rel = str(rel).replace("\\", "/")
            # The row proves THIS node's code does the I/O, so the cited file
            # must live in THIS workarea: a `..` path could satisfy the binding
            # with another node's (or any) file.
            if Path(rel).is_absolute() or ".." in Path(rel).parts:
                errs.append(f"BUILD_WIRING_PATH: {kind} {token}: {rel!r} must be a path inside this "
                            "node's workarea")
                continue
            target = wd / rel
            if wd_resolved not in target.resolve(strict=False).parents:
                errs.append(f"BUILD_WIRING_PATH: {kind} {token}: {rel!r} resolves outside this node's "
                            "workarea")
                continue
            if not target.is_file():
                errs.append(f"BUILD_WIRING_FILE: {kind} {token}: file {rel!r} does not exist in the workarea")
            elif len(snippet.split()) < 3 \
                    or eutil.norm_ws(snippet) not in eutil.norm_ws(eutil.read_text(target)):
                errs.append(f"BUILD_WIRING_SNIPPET: {kind} {token}: CODE must be a literal >=3-token "
                            f"snippet of {rel!r}")
    read_tokens = {row[0] for row in reads}
    write_tokens = {row[0] for row in writes}
    for token in want_reads:
        if token not in read_tokens:
            errs.append(f"BUILD_WIRING_READ_MISSING: declared input {token!r} has no READS: row - "
                        "point at the exact code that loads it")
    for token in want_writes:
        if token not in write_tokens:
            errs.append(f"BUILD_WIRING_WRITE_MISSING: declared output {token!r} has no WRITES: row - "
                        "point at the exact code that saves to it")
    return errs


def maintenance_boundary_errors(ctx: Ctx, node: dict, spec: dict) -> list[str]:
    """Enforce a maintenance change_boundary against the ACTUAL diff (v10.2 R2).

    `files_in_scope` was validated for shape and never compared to anything -
    a declaration with no consequence, i.e. exactly the ceremony this engine
    exists to eliminate.  Maintenance skips every novelty gate ON THE PROMISE
    that its blast radius is declared in advance, so the promise has to be
    checkable: compare the node's execution closure against the parent's
    sealed manifest and reject any changed/added executable file outside the
    declared set.  Deleting is covered too - a removed file is a change.
    """
    if node.get("experiment_purpose") != "maintenance":
        return []
    declared = (spec.get("maintenance") or {}).get("change_boundary") or {}
    scope = {str(f).replace("\\", "/") for f in (declared.get("files_in_scope") or [])
             if str(f or "").strip()}
    idx = egraph.by_id(ctx.g)
    parents = [p for p in node.get("parents", []) if p in idx and idx[p].get("role") != "platform"]
    parent = idx.get(parents[0]) if parents else None
    if parent is None:
        return ["MAINT_BOUNDARY_NO_PARENT: a maintenance node needs its repaired parent to diff against"]
    if (ctx.cfg.get("project") or {}).get("vcs") == "git":
        # Ask Git, not two hashed checkouts: core.autocrlf normalizes line
        # endings on checkout, so byte-comparing this worktree against the
        # parent's manifest (built in a DIFFERENT working tree) reports files
        # nobody touched.  Every other manifest comparison in the engine stays
        # inside one working tree, which is why this is the first place it bit.
        base = str(parent.get("implementation_commit") or "")
        if not base:
            return []
        try:
            changed = evcs.changed_files_since(
                eutil.rpath(ctx.store.repo, str(node.get("workdir") or ".")), base)
        except (evcs.GitCheckError, OSError, RuntimeError) as exc:
            return [f"MAINT_BOUNDARY_UNVERIFIABLE: node {node.get('id')} change boundary could not be "
                    f"audited against parent commit {base[:12]}: {exc}"]
        current_manifest = None
    else:
        parent_manifest = eutil.read_json(
            eutil.rpath(ctx.store.repo, str(parent.get("implementation_manifest") or "")), None)
        if not isinstance(parent_manifest, dict):
            # The parent may predate manifests (or have been pruned): fail OPEN
            # here rather than blocking a legitimate repair - the seal machinery
            # still binds this node's own closure.
            return []
        before = _manifest_file_map(parent_manifest)
        current_manifest = build_implementation_manifest(ctx, node)
        after = _manifest_file_map(current_manifest)
        changed = sorted({rel for rel in set(before) | set(after)
                          if before.get(rel) != after.get(rel)})
    # The boundary is the EXECUTION CLOSURE, not a code-suffix list. The old
    # suffix filter let a repair edit config/train.yaml (a longer schedule, a
    # different eval protocol) without tripping the boundary although the
    # implementation manifest - the engine's own definition of "can affect a
    # run" - includes those very bytes; semantic change could enter an
    # inheritable base through the purpose that exists to skip novelty gates.
    # Membership = "the file belongs to this node's or the parent's sealed
    # closure": the parent's manifest FILE LIST is checkout-independent (only
    # its hashes are not), so this works identically in git and copy mode, and
    # runtime landing artifacts stay excluded because the walker already
    # excludes them from every manifest.
    # v11: reuse the manifest the copy-mode diff above already built (the
    # double build hashed every workarea byte twice per validation, ~2s wasted
    # per submit at a 1GB checkout); membership needs only the PATH SET, so the
    # git-mode build skips hashing entirely.
    if current_manifest is not None:
        closure_now = set(_manifest_file_map(current_manifest))
    else:
        closure_now = set(_manifest_file_map(
            build_implementation_manifest(ctx, node, paths_only=True)))
    parent_rows = eutil.read_json(
        eutil.rpath(ctx.store.repo, str(parent.get("implementation_manifest") or "")), None)
    closure_parent = set(_manifest_file_map(parent_rows)) if isinstance(parent_rows, dict) else set()
    outside = [rel for rel in changed
               if rel not in scope and (rel in closure_now or rel in closure_parent)]
    if outside:
        return [f"MAINT_BOUNDARY_VIOLATION: node {node.get('id')} changed execution-closure files outside its "
                f"approved change_boundary.files_in_scope: {outside[:8]}. A repair whose blast radius "
                "exceeds its reviewed boundary is a candidate, not maintenance - take it through the "
                "novelty pipeline or open a new maintenance lane with the true boundary."]
    return []


def is_probe_active(meta: dict) -> bool:
    """THE probe-activity predicate: a valid mechanism_probe not silenced by an
    attribution waiver. v9.2 kept two drifted copies (one waiver-aware, one
    not), so a waivered idea had to declare a probe it was forbidden to run."""
    idea_probe = (meta or {}).get("mechanism_probe")
    return isinstance(idea_probe, dict) and idea_probe.get("mode") in econfig.PROBE_MODES \
        and not str((meta or {}).get("attribution_waiver") or "").strip()


def _probe_plan_errors(ctx: Ctx, spec: dict, meta: dict, *, where: str) -> list[str]:
    """Bind an approved probe to an executable producer and smoke contract."""
    errs: list[str] = []
    idea_probe = meta.get("mechanism_probe")
    active = is_probe_active(meta)
    execution = spec.get("probe_execution")
    if not active:
        if execution is not None:
            errs.append(f"SPEC_PROBE_UNDECLARED: {where}: probe_execution is legal only for an approved mechanism_probe")
        return errs
    if spec.get("experiment_purpose") == "targeted_ablation":
        return [f"SPEC_ABLATION_PROBE_EXECUTION: {where}: targeted ablation may not nest a mechanism probe"]
    if not isinstance(execution, dict):
        return [f"SPEC_PROBE_EXECUTION: {where}: approved mechanism_probe requires a probe_execution object"]
    for field in ("mode", "signal", "expect", "artifact", "required_fields", "decision_rule"):
        if execution.get(field) != idea_probe.get(field):
            errs.append(f"SPEC_PROBE_BINDING: {where}: probe_execution.{field} must exactly copy mechanism_probe.{field}")
    mode = str(execution.get("mode") or "")
    artifact = str(execution.get("artifact") or "")
    fields = list(execution.get("required_fields") or []) if isinstance(execution.get("required_fields"), list) else []
    errs.extend(_probe_path_errors(artifact, f"{where}.probe_execution.artifact"))
    smoke_paths = {
        str(path)
        for step in (spec.get("smoke_plan") or []) if isinstance(step, dict)
        for path in (step.get("must_exist") or [])
    }
    if mode == "same_run":
        if execution.get("command") not in (None, ""):
            errs.append(f"SPEC_PROBE_SAME_RUN_COMMAND: {where}: same_run uses the declared producer and may not "
                        "smuggle in a separate eval command")
        producer = str(execution.get("producer_stage") or "")
        names = {str(s.get("name") or "") for s in econfig.stages_of(spec)}
        if names and producer not in names:
            errs.append(f"SPEC_PROBE_PRODUCER: {where}: same_run producer_stage must name one workflow stage")
        if not names and producer != "evaluation":
            errs.append(f"SPEC_PROBE_PRODUCER: {where}: an evaluation-only node must use "
                        "producer_stage='evaluation' for same-run logging")
        rep = spec.get("training_replication") or {}
        if rep.get("mode") == "preplanned" and rep.get("source") == "workflow" and "{seed}" not in artifact:
            errs.append(f"SPEC_PROBE_SEED_TEMPLATE: {where}: a same_run probe under complete-workflow "
                        "replication must put '{seed}' in artifact so each seed keeps its own observation")
    elif mode == "existing_artifact":
        forbidden = [k for k in ("producer_stage", "command", "smoke_artifact") if execution.get(k) not in (None, "")]
        if forbidden:
            errs.append(f"SPEC_PROBE_EXISTING_EXTRA: {where}: existing_artifact probe may not declare {forbidden}")
        errs.extend(probe_artifact_errors(ctx, artifact, fields, where=f"{where} existing probe"))
    elif mode == "eval_intervention":
        if execution.get("producer_stage") not in (None, ""):
            errs.append(f"SPEC_PROBE_EVAL_PRODUCER: {where}: eval_intervention is produced by its command, not a workflow stage")
        cmd = str(execution.get("command") or "").strip()
        if len(cmd) < 8:
            errs.append(f"SPEC_PROBE_COMMAND: {where}: eval_intervention needs the exact eval-only command")
        if re.search(r"\b(train|finetune|optimizer|backward|gradient)\b", cmd, re.I):
            errs.append(f"SPEC_PROBE_COMMAND_TRAINING: {where}: probe command appears to launch training; "
                        "an eval intervention may only inspect fixed artifacts")
        # v12 (field deadlock T0611): under preplanned complete-workflow
        # replication the sealed checkpoints are per-seed, so an eval-only
        # intervention may legitimately keep one observation per seed - the
        # same situation in which the same_run branch REQUIRES '{seed}'. The
        # old unconditional refusal, combined with SPEC_PROBE_BINDING's exact
        # copy duty, made a sealed eval_intervention+{seed} idea jointly
        # unsatisfiable at plan time. The idea layer now front-shifts the
        # remaining refusal (v_mature cross-checks mode x template), keeping
        # both layers on one invariant.
        rep = spec.get("training_replication") or {}
        if "{seed}" in artifact and not (rep.get("mode") == "preplanned" and rep.get("source") == "workflow"):
            # The residual reachable case here (idea layer cannot see the
            # node's experiment class): a sealed candidate probe assuming
            # per-seed training artifacts on a node that has none. The sealed
            # probe is unsatisfiable as authored - be honest that no spec edit
            # fixes it, instead of letting SPEC_PROBE_BINDING and this check
            # point in opposite directions until attempts exhaust silently.
            errs.append(f"SPEC_PROBE_EVAL_SEED_TEMPLATE: {where}: one eval-only intervention produces one "
                        "artifact after the workflow; '{seed}' is only legal under preplanned "
                        "complete-workflow replication where each seed keeps its own observation. "
                        "If this node legitimately has no per-seed training runs, the SEALED probe "
                        "itself assumes artifacts that cannot exist - no spec edit satisfies both "
                        "this rule and the verbatim-copy duty; let attempts route to escalation "
                        "and re-author the idea (or 'evo propose-abandon' the lane)")
    if mode in ("same_run", "eval_intervention"):
        smoke_artifact = str(execution.get("smoke_artifact") or "")
        errs.extend(_probe_path_errors(smoke_artifact, f"{where}.probe_execution.smoke_artifact"))
        if "{seed}" in smoke_artifact:
            errs.append(f"SPEC_PROBE_SMOKE_TEMPLATE: {where}: smoke runs once and smoke_artifact may not contain '{{seed}}'")
        if smoke_artifact == artifact:
            errs.append(f"SPEC_PROBE_SMOKE_RUNTIME_COLLISION: {where}: smoke_artifact must differ from the real observation artifact")
        if smoke_artifact not in smoke_paths:
            errs.append(f"SPEC_PROBE_SMOKE_WIRING: {where}: a smoke_plan step must list probe_execution.smoke_artifact "
                        "in must_exist so instrumentation is exercised before costly work")
    return errs


def v_plan_node(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    lane = ctx.store.get_lane(ctx.st, task["subject"]["lane"])
    if lane is None:
        return ["INTERNAL: lane missing"]
    spec = load_spec(ctx, task["outputs"][0], errs)
    meta, _ = _load_idea(ctx, lane, errs)
    if spec is None or meta is None:
        return errs
    role = econfig.INTENT_TO_ROLE[lane["intent"]]
    expect_parents = list(meta.get("parents") or []) + list(meta.get("platforms_consumed") or [])
    errs.extend(_spec_errors(ctx, spec, expect_role=role, expect_parents=expect_parents,
                             expect_level=meta.get("level"), where=f"spec({lane['id']})",
                             receipts=(task.get("consumed_context") or {}).get("artifact_receipts")))
    # Parent legality again, at the LAST validation point before a node exists.
    # The two doors checked it at admission, but a parent can die between the
    # door and here (recover-abort --abandon-node mid-round): the child then
    # ran anyway and its every comparator lookup silently fell back to the
    # baseline - a wrong reference, not an error.  Wildcat roots have no model
    # parent and are exempt by shape.
    idx_now = egraph.by_id(ctx.g)
    for p in (meta.get("parents") or []):
        if (idx_now.get(str(p)) or {}).get("role") == "platform":
            continue
        for kind, detail in model_parent_defects(idx_now, str(p)):
            errs.append(f"PLAN_PARENT_{kind.upper()}: {detail} - it was legal when this lane was "
                        "admitted but is not now; abandon the lane (reject its next gate) or "
                        "recover the parent first")
        for detail in parent_hold_defects(ctx, str(p)):
            errs.append(f"PLAN_PARENT_HELD: {detail}")
    # R10-010: the EXECUTION source axis gets the same quarantine check as
    # the scientific parents - a held baseline (e.g. under a fork_project
    # diagnosis) used to re-enter through code_parent because this walk only
    # covered meta.parents.
    code_parent = str(spec.get("code_parent") or "") if isinstance(spec, dict) else ""
    if code_parent and code_parent not in {str(p) for p in (meta.get("parents") or [])}:
        for detail in parent_hold_defects(ctx, code_parent):
            errs.append(f"PLAN_CODE_PARENT_HELD: {detail} - a held authority cannot serve as the "
                        "execution source either")
    if spec.get("experiment_purpose") != meta.get("experiment_purpose"):
        errs.append("SPEC_EXPERIMENT_PURPOSE_BINDING: spec.experiment_purpose must equal the approved idea")
    # v11.1 (R2 fix): custody bindings key on "carries an audited program"
    # (candidate AND exploratory), not on == "candidate" - the scout's spec
    # must execute the tournament-audited kernel like any candidate's.
    if meta.get("experiment_purpose") in ("candidate", "exploratory"):
        if spec.get("program_digest") != meta.get("program_digest"):
            errs.append("SPEC_PROGRAM_DIGEST: NODE_SPEC must bind the approved program digest")
        expected_kernels = eprogram.kernel_ids(meta)
        if list(spec.get("kernel_ids") or []) != expected_kernels:
            errs.append(f"SPEC_KERNEL_IDS: kernel_ids must exactly equal approved kernel order {expected_kernels}")
        if spec.get("program_ir") != meta.get("program"):
            errs.append("SPEC_PROGRAM_IR: NODE_SPEC.program_ir must exactly copy the approved forward program")
        if spec.get("novelty_kernel") != ((meta.get("novelty") or {}).get("kernel") or []):
            errs.append("SPEC_NOVELTY_KERNEL: NODE_SPEC.novelty_kernel must exactly copy the approved kernel")
        if spec.get("effect_case") != meta.get("effect_case"):
            errs.append("SPEC_EFFECT_CASE: NODE_SPEC.effect_case must exactly copy the approved typed effect/resource case")
        if spec.get("theory_obligations") != meta.get("theory_obligations"):
            errs.append("SPEC_THEORY_OBLIGATIONS: NODE_SPEC.theory_obligations must exactly copy the approved DO# -> KC#/OP# mapping")
    if meta.get("experiment_purpose") == "targeted_ablation" and spec.get("ablation") != meta.get("ablation"):
        errs.append("SPEC_ABLATION_BINDING: spec.ablation must exactly copy the user-reviewed idea contract; "
                    "the intervention or decision map may not drift during planning")
    if meta.get("experiment_purpose") == "diagnostic_probe" and spec.get("probe") != meta.get("probe"):
        errs.append("SPEC_PROBE_CONTRACT_BINDING: spec.probe must exactly copy the user-approved probe "
                    "contract; question, measurement plan and budget may not drift during planning")
    if meta.get("experiment_purpose") == "maintenance" and spec.get("maintenance") != meta.get("maintenance"):
        errs.append("SPEC_MAINTENANCE_BINDING: spec.maintenance must exactly copy the reviewed maintenance "
                    "contract; defect, boundary and parity may not drift during planning")
    ep = spec.get("evidence_plan") or {}
    probe = meta.get("mechanism_probe") or {}
    probe_active = is_probe_active(meta)
    expected_eval_arms = int(probe.get("extra_eval_arms") or 0) if probe_active else 0
    if ep.get("extra_eval_arms") != expected_eval_arms:
        errs.append(f"SPEC_PROBE_BUDGET_MISMATCH: evidence_plan.extra_eval_arms must equal the idea's registered {expected_eval_arms}")
    checks = set(str(x) for x in (ep.get("declared_checks") or []))
    if meta.get("experiment_purpose") == "targeted_ablation":
        if ep.get("extra_eval_arms") != 0 or checks:
            errs.append("SPEC_ABLATION_EVIDENCE_PLAN: targeted ablation evidence_plan must contain zero extra "
                        "eval arms and no nested checks; standard evaluation settles the registered X1/X2 map")
    if probe_active and "mechanism_probe" not in checks:
        errs.append("SPEC_PROBE_NOT_WIRED: current-node mechanism probe must appear in evidence_plan.declared_checks")
    errs.extend(_probe_plan_errors(ctx, spec, meta, where=f"spec({lane['id']})"))
    if meta.get("scaling") and "scaling_probe" in checks:
        errs.append("SPEC_SCALING_IN_PRIMARY_NODE: scaling work is reuse-only or an after-signal follow-up node; it may not be hidden in the primary node plan")
    idea_assumptions = {str(a.get("id") or "") for a in (meta.get("assumptions") or [])}
    for stage in econfig.stages_of(spec):
        gate = stage.get("continuation_gate")
        if not isinstance(gate, dict):
            continue
        unknown = sorted(set(str(a) for a in (gate.get("assumptions") or [])) - idea_assumptions)
        if unknown:
            errs.append(f"SPEC_STAGE_GATE_ASSUMPTION_UNKNOWN: stage {stage.get('name')!r} continuation gate "
                        f"references assumptions not registered by the idea: {unknown}")
    idx = egraph.by_id(ctx.g)
    errs.extend(egraph.role_parent_errors(role, "spec", [p for p in expect_parents if p in idx], idx))
    return errs


def _mapped_workdir_path(ctx: Ctx, node: dict, relpath: str) -> tuple[Path, bool]:
    """Resolve a reviewed code mapping and report whether it stays in workdir."""
    raw = Path(str(relpath or "").replace("\\", "/"))
    try:
        wd = eutil.rpath(ctx.store.repo, str(node.get("workdir") or ".")).resolve(strict=False)
        candidates = [raw] if raw.is_absolute() else [wd / raw, eutil.rpath(ctx.store.repo, raw.as_posix())]
        target = next((path for path in candidates if path.exists()), candidates[0])
        resolved = target.resolve(strict=False)
    except (OSError, RuntimeError):
        fallback = eutil.rpath(ctx.store.repo, str(node.get("workdir") or ".")) / raw
        return fallback, False
    return resolved, resolved == wd or _path_is_within(resolved, wd)


def implementation_artifact_paths(ctx: Ctx, node: dict, report_rel: str) -> list[str]:
    """Return the exact code surface accepted by the build contract.

    Every load-bearing OP#/KC# is required to appear in the mechanism-to-code
    map, and probe instrumentation has its own literal rows.  Sealing those
    resolved files plus the report binds later smoke/training/evaluation
    evidence to the implementation that was actually reviewed without sealing
    transient checkpoints or metric files in the whole workarea.
    """
    report = eutil.read_text(eutil.rpath(ctx.store.repo, report_rel))
    rels = [row[2] for row in BUILD_OPERATOR_ROW.findall(
        eutil.find_section(eutil.md_sections(report), "mechanism to code map") or "")]
    rels.extend(row[1] for row in PROBE_FIELD_ROW.findall(
        eutil.find_section(eutil.md_sections(report), "probe instrumentation") or ""))
    rels.extend(row[0] for row in BRIDGE_ADAPTER_ROW.findall(
        eutil.find_section(eutil.md_sections(report), "metric bridge adapter") or ""))
    # Platform/diagnostic builds have no KC# map but still must name at least
    # one real changed file; retain the same generic paths accepted by
    # v_implement for those roles.
    if not rels:
        rels.extend(re.findall(r"->\s*`?([\w./\\-]+\.\w{1,8})`?", report))
    out = [str(report_rel)]
    for relp in rels:
        target, confined = _mapped_workdir_path(ctx, node, relp)
        if confined and target.exists() and target.is_file():
            stored = eutil.rel(ctx.store.repo, target)
            if stored not in out:
                out.append(stored)
    return out


def workflow_protected_implementation_paths(ctx: Ctx, node: dict) -> list[str]:
    """Freeze the code paths that an evaluation-only repair may not touch.

    This is deliberately conservative and local: the accepted mechanism map,
    workflow-produced probe code, and files named by stage commands are the
    workflow authority.  Other changes still need an exact declaration and
    written non-interference argument in the repair report.
    """
    seal = node.get("implementation_seal") or {}
    report_row = next((row for row in (seal.get("artifacts") or [])
                       if isinstance(row, dict) and row.get("role") == "build_report"), None)
    report_path = str((report_row or {}).get("snapshot") or (report_row or {}).get("path") or "")
    report = eutil.read_text(eutil.rpath(ctx.store.repo, report_path)) if report_path else ""
    sections = eutil.md_sections(report)
    protected = {
        str(path).replace("\\", "/")
        for path in re.findall(
            r"->\s*`?([\w./\\-]+\.\w{1,8})`?",
            eutil.find_section(sections, "mechanism to code map") or "")
    }
    spec = eutil.read_json(eutil.rpath(ctx.store.repo, str(node.get("spec") or "")), {}) or {}
    probe = spec.get("probe_execution") if isinstance(spec.get("probe_execution"), dict) else {}
    # F10: eval_intervention probes run AFTER the workflow by definition, and
    # producer_stage='evaluation' marks evaluation-owned same-run logging;
    # neither is workflow authority. v9.2 protected eval_intervention code and
    # thereby forced full retraining for evaluation-only probe fixes.
    probe_is_workflow_owned = (str(probe.get("mode") or "") != "eval_intervention"
                               and str(probe.get("producer_stage") or "") != "evaluation")
    if probe_is_workflow_owned:
        protected.update(str(row[1]).replace("\\", "/") for row in PROBE_FIELD_ROW.findall(
            eutil.find_section(sections, "probe instrumentation") or ""))
    manifest = eutil.read_json(
        eutil.rpath(ctx.store.repo, str(node.get("implementation_manifest") or "")), {}) or {}
    manifest_paths = set(_manifest_file_map(manifest))
    stage_commands = "\n".join(
        str(stage.get("launch") or "")
        for stage in ((spec.get("workflow") or {}).get("stages") or [])
        if isinstance(stage, dict))
    normalized_commands = stage_commands.replace("\\", "/")
    for relpath in manifest_paths:
        if relpath in normalized_commands:
            protected.add(relpath)
    return sorted(path for path in protected if path)


_EXECUTION_SOURCE_SUFFIXES = {
    ".py", ".pyi", ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".kt", ".scala",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp", ".cu", ".go", ".rs", ".rb", ".pl",
}

# R9: volatile run by-products a stage may legitimately append to; they stay
# OUTSIDE the sealed execution closure (recorded residual - a dependency
# disguised under one of these names is not covered).
_VOLATILE_BYPRODUCT = re.compile(
    r"(^|/)(__pycache__|\.cache|\.pytest_cache|node_modules)(/|$)"
    r"|\.(log|tmp|temp|swp|bak)$|~$", re.IGNORECASE)


def resolved_workdir_map(ctx: Ctx) -> dict[str, Path]:
    """{node id: resolved workdir} computed ONCE per sweep/validation.

    The set depends only on graph workdir strings, which cannot change inside
    one invocation; resolving every workdir per audited node made the closure
    audit O(nodes^2) filesystem calls (measured 1.68s at 100 nodes for the
    resolves alone).
    """
    out: dict[str, Path] = {}
    for other in ctx.g.get("nodes", []):
        if not other.get("workdir") or not other.get("id"):
            continue
        try:
            out[str(other["id"])] = eutil.rpath(
                ctx.store.repo, str(other["workdir"])).resolve(strict=False)
        except (OSError, RuntimeError):
            continue
    return out


def _nested_node_workdirs(ctx: Ctx, node: dict, workdir: Path,
                          workdir_map: dict[str, Path] | None = None) -> list[Path]:
    """Other graph-owned workareas nested below this node's filesystem root."""
    resolved = workdir_map if workdir_map is not None else resolved_workdir_map(ctx)
    out: list[Path] = []
    for nid, candidate in resolved.items():
        if nid == str(node.get("id")):
            continue
        if candidate != workdir and _path_is_within(candidate, workdir) and candidate not in out:
            out.append(candidate)
    return out


def _raw_file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


_MANIFEST_PRUNE_DIRS = {".git", ".evo", "__pycache__"}


def _workarea_files(wd: Path, nested_workdirs: list[Path]) -> list[tuple[Path, str]]:
    """Enumerate execution-closure candidate files under one workarea.

    Pruning ``.git``/``.evo``/``__pycache__`` and nested node workareas at the
    directory level is equivalent to the previous per-file filters (a matching
    name component or nested root excluded every file below it), but skips the
    subtree instead of enumerating and resolving each file first - ``.evo``
    grows monotonically, so this is what keeps closure checks O(project) rather
    than O(project age).  Returns ``(path, repo-style relative posix)`` pairs
    sorted by the relative path.
    """
    if not wd.exists() or not wd.is_dir():
        return []
    wd_resolved = wd.resolve(strict=False)
    out: list[tuple[Path, str]] = []
    seen_dirs: set[str] = set()

    def _keep_dir(rbase: Path, name: str) -> bool:
        if name in _MANIFEST_PRUNE_DIRS:
            return False
        joined = rbase / name
        rd = joined.resolve(strict=False)
        # Old prefix semantics: anything resolving INTO a nested node workarea
        # (its root or interior, e.g. via a junction) belongs to that node.
        for root in nested_workdirs:
            if rd == root or _path_is_within(rd, root):
                return False
        # A junction/symlink aliasing a location inside this workarea would
        # double-seal those bytes under an alias-relative path (and whichever
        # alias walks first would shadow the real one); the real path is (or
        # was) walked under its own name, so skip the alias.
        if os.path.normcase(str(rd)) != os.path.normcase(str(joined)) \
                and _path_is_within(rd, wd_resolved):
            return False
        return True

    # followlinks=False matches Path.rglob on Python 3.13 (no descent into
    # directory symlinks); Windows junctions can still alias directories, so
    # the resolved-path guards above and below keep aliased subtrees from
    # double-sealing or cycling.
    for dirpath, dirnames, filenames in os.walk(wd, followlinks=False):
        base = Path(dirpath)
        rbase = base.resolve(strict=False)
        key = rbase.as_posix()
        if key in seen_dirs:  # junction/alias cycle guard
            dirnames[:] = []
            continue
        seen_dirs.add(key)
        dirnames[:] = [d for d in dirnames if _keep_dir(rbase, d)]
        rel_base = base.relative_to(wd)
        for name in filenames:
            path = base / name
            # A FILE named .git (the linked-worktree gitdir pointer) or .evo
            # must be excluded exactly as the old any-component filter did -
            # its bytes are git-owned and change on legal worktree repair.
            if name in _MANIFEST_PRUNE_DIRS or path.suffix.lower() == ".pyc" \
                    or not path.is_file():
                continue
            out.append((path, (rel_base / name).as_posix()))
    out.sort(key=lambda pair: pair[1])
    return out


def _runtime_output_roots(ctx: Ctx, node: dict, workdir: Path) -> list[Path]:
    """Resolve only contract-declared mutable outputs inside one workarea.

    Copy-mode workareas cannot use Git tracking to distinguish inherited code
    from products left by an earlier RUN.  The spec and RUN records already
    own that distinction, so the implementation manifest excludes their exact
    local landing paths instead of guessing from file extensions.
    """
    raw_paths: set[str] = set()
    spec = eutil.read_json(eutil.rpath(ctx.store.repo, str(node.get("spec") or "")), {}) or {}
    seeds = econfig.workflow_seeds(spec) or [None]
    for stage in ((spec.get("workflow") or {}).get("stages") or []):
        if not isinstance(stage, dict):
            continue
        for seed in seeds:
            for field in ("metrics_file", "ledger_file"):
                value = str(stage.get(field) or "")
                if value:
                    raw_paths.add(str(econfig.resolve_seed_template(value, seed))
                                  if seed is not None else value)
            for product in (stage.get("produces") or []):
                if not isinstance(product, dict):
                    continue
                value = str(product.get("uri") or "")
                if value:
                    raw_paths.add(str(econfig.resolve_seed_template(value, seed))
                                  if seed is not None else value)
    evaluation = spec.get("eval") if isinstance(spec.get("eval"), dict) else {}
    if evaluation.get("metrics_file"):
        raw_paths.add(str(evaluation["metrics_file"]))
    # R6 blind-operator audit: a smoke step's declared observable landings
    # (must_exist / must_contain files) are runtime outputs too - the sealed
    # spec's own smoke command creates them, a pre-seal self-test (which the
    # implement card explicitly authorizes) legitimately leaves them in the
    # workarea, and the MANDATORY post-seal formal smoke rewrites them.
    # Sealing them wedged such nodes on SEALED_EXECUTION_FILE_MUTATED with no
    # card-derivable repair. Same trust class as spec-declared stage metrics.
    for step in (spec.get("smoke_plan") or []):
        if not isinstance(step, dict):
            continue
        for me_path in (step.get("must_exist") or []):
            if isinstance(me_path, str) and me_path:
                raw_paths.add(me_path)
        for mc in (step.get("must_contain") or []):
            if isinstance(mc, dict) and str(mc.get("file") or ""):
                raw_paths.add(str(mc["file"]))
    probe = spec.get("probe_execution") if isinstance(spec.get("probe_execution"), dict) else {}
    if probe.get("smoke_artifact"):
        raw_paths.add(str(probe["smoke_artifact"]))
    if probe.get("mode") != "existing_artifact" and probe.get("artifact"):
        for seed in seeds:
            value = str(probe["artifact"])
            raw_paths.add(str(econfig.resolve_seed_template(value, seed))
                          if seed is not None else value)
    for run in ctx.st.get("runs", []):
        if run.get("node") != node.get("id"):
            continue
        for field in ("metrics_file", "ledger_file", "declared_metrics_file", "declared_ledger_file"):
            if run.get(field):
                raw_paths.add(str(run[field]))
        raw_paths.update(str(path) for path in (run.get("producer_probe_artifacts") or []) if str(path))

    roots: set[Path] = set()
    repo = ctx.store.repo.resolve()
    for raw in raw_paths:
        if not raw or "://" in raw:
            continue
        value = Path(raw)
        candidates = [value] if value.is_absolute() else [repo / value, workdir / value]
        for candidate in candidates:
            resolved = candidate.resolve(strict=False)
            if resolved != workdir and _path_is_within(resolved, workdir):
                roots.add(resolved)
    return sorted(roots, key=lambda path: path.as_posix())


def build_implementation_manifest(ctx: Ctx, node: dict, *, paths_only: bool = False) -> dict:
    """Snapshot every existing file in the execution workarea.

    The manifest is deliberately broader than the KC#/OP# review map.  The map
    says which files realize the claimed mechanism; this tree says which code,
    configuration and inherited dependency bytes can actually affect runs.
    Runtime products created later are allowed, but a pre-existing file may not
    change and a new source-code file may not appear outside a new explicit
    implementation revision.
    """
    wd = eutil.rpath(ctx.store.repo, str(node.get("workdir") or ".")).resolve()
    nested_workdirs = _nested_node_workdirs(ctx, node, wd)
    runtime_roots = _runtime_output_roots(ctx, node, wd)
    rows: list[dict] = []
    tracked_only = (ctx.cfg.get("project") or {}).get("vcs") == "git"
    untracked = {str(p).replace("\\", "/") for p in evcs.untracked_files(wd)} if tracked_only else set()
    for path, rel in _workarea_files(wd, nested_workdirs):
        if path.suffix.lower() not in _EXECUTION_SOURCE_SUFFIXES and runtime_roots:
            # Runtime roots are resolved; resolve the candidate too so a
            # junction/symlink alias in the walked path cannot dodge the
            # declared-landing exclusion (only non-source files pay this).
            full = path.resolve(strict=False)
            if any(full == root or _path_is_within(full, root) for root in runtime_roots):
                continue
        if tracked_only and rel in untracked:
            if path.suffix.lower() in _EXECUTION_SOURCE_SUFFIXES:
                # Untracked SOURCE files are rejected at approval; skipping
                # them here keeps the manifest consistent with that rejection.
                continue
            # R9 (external audit r6): untracked NON-source files that survive
            # the runtime-root exclusion are execution dependencies the commit
            # does not cover (runtime.yaml, tokenizer vocab, a compiled .dll
            # the formal smoke produced, a weights sidecar). Skipping them
            # wholesale meant their bytes could be swapped after approval
            # while HEAD stayed clean and every closure audit stayed green.
            # Hash them - EXCEPT volatile by-products (logs/temp/caches),
            # which runs legitimately append to; that carve-out is a recorded
            # residual, not an oversight.
            if _VOLATILE_BYPRODUCT.search(rel):
                continue
        rows.append({"path": rel, "digest": "" if paths_only else _raw_file_digest(path)})
    return {
        "schema_version": 1,
        "node": str(node.get("id") or ""),
        "workdir": str(node.get("workdir") or "."),
        "tracked_only": tracked_only,
        "files": rows,
    }


def implementation_manifest_errors(ctx: Ctx, node: dict, *,
                                   known_digests: dict[str, str] | None = None,
                                   git_tracked: set[str] | None = None,
                                   workdir_map: dict[str, Path] | None = None) -> list[str]:
    """Audit the sealed execution closure against the workarea.

    v11 cost levers, each preserving the audit's verdicts:
    - ``known_digests`` ({abs path: digest}) carries digests THIS invocation
      already computed while sealing; the on-disk manifest row must still equal
      the known value (write-integrity preserved), only the byte re-read goes.
    - ``git_tracked``: when the caller has just proven HEAD==reviewed commit,
      tracked tree clean, and NO suspicious index bits (assume-unchanged /
      skip-worktree - the spoof that blinds git), rows present in the tracked
      set are byte-identical to the sealed manifest by git's own facts and skip
      hashing; rows ABSENT from it (gitignored files inside the closure) keep
      their hash, and the new-source walk below stays on (it never hashed).
      Copy mode and doctor never pass this.
    """
    relpath = str(node.get("implementation_manifest") or "")
    if not relpath:
        return [f"IMPLEMENTATION_MANIFEST_MISSING: node {node.get('id')} has no execution-closure manifest"]
    try:
        data = eutil.read_json(eutil.rpath(ctx.store.repo, relpath), None)
    except SystemExit:
        return [f"SEALED_IMPLEMENTATION_MANIFEST_UNREADABLE: node {node.get('id')} "
                "reviewed execution-closure manifest is malformed or unreadable"]
    if not isinstance(data, dict) or data.get("schema_version") != 1 \
            or data.get("node") != node.get("id") or data.get("workdir") != node.get("workdir"):
        return [f"IMPLEMENTATION_MANIFEST_INVALID: node {node.get('id')} manifest identity/schema is invalid"]
    rows = data.get("files")
    if not isinstance(rows, list):
        return [f"IMPLEMENTATION_MANIFEST_INVALID: node {node.get('id')} files must be an array"]
    wd = eutil.rpath(ctx.store.repo, str(node.get("workdir") or ".")).resolve()
    nested_workdirs = _nested_node_workdirs(ctx, node, wd, workdir_map)
    walked_paths = {rel: path for path, rel in _workarea_files(wd, nested_workdirs)}
    known = known_digests or {}
    expected: dict[str, str] = {}
    errs: list[str] = []
    # R8/N003 audit: a row whose path is CURRENTLY gitignored and not source
    # is enforced as advisory only. gitignore is the project's own standing
    # declaration "runtime by-product, not reviewed implementation" - a
    # per-launch bookkeeping file in that class is rewritten by every stage,
    # and freezing its bytes wedged the node (and every engine verb) on a
    # mutated-closure report with no repair verb, since the only manifest
    # rewrite lives behind a new implement revision. Ignored SOURCE files
    # keep hard enforcement (hiding source via ignore rules is not a runtime
    # shape), and .gitignore itself is tracked - widening it after approval
    # trips the reviewed-commit/clean-tree checks first. The advisory rows'
    # sealed digests remain in the manifest for after-the-fact comparison.
    ignored_runtime: set[str] = set()
    if data.get("tracked_only"):
        candidates = [str(r.get("path") or "").replace("\\", "/") for r in rows
                      if isinstance(r, dict)
                      and Path(str(r.get("path") or "")).suffix.lower()
                      not in _EXECUTION_SOURCE_SUFFIXES]
        if candidates:
            try:
                ignored_runtime = evcs.ignored_paths(wd, candidates)
            except (evcs.GitCheckError, evcs.GitWorkdirMissingError):
                ignored_runtime = set()  # classification unavailable: keep hard enforcement
    for row in rows:
        if not isinstance(row, dict):
            errs.append(f"IMPLEMENTATION_MANIFEST_ROW: node {node.get('id')} has a non-object row")
            continue
        rel = str(row.get("path") or "").replace("\\", "/")
        digest = str(row.get("digest") or "")
        if not rel or rel.startswith("../") or rel in expected:
            errs.append(f"IMPLEMENTATION_MANIFEST_PATH: node {node.get('id')} has invalid/duplicate path {rel!r}")
            continue
        expected[rel] = digest
        if rel in ignored_runtime:
            continue
        path = (wd / Path(rel)).resolve(strict=False)
        if any(path == root or _path_is_within(path, root) for root in nested_workdirs):
            continue
        walk_path = walked_paths.get(rel, path)
        seeded = known.get(str(walk_path))
        if seeded is not None:
            if seeded != digest:
                errs.append(f"SEALED_EXECUTION_FILE_MUTATED: node {node.get('id')} {rel!r} no longer matches "
                            f"implementation manifest {digest[:12]}")
            continue
        if git_tracked is not None and rel in git_tracked and digest:
            continue
        actual = _raw_file_digest(walk_path)
        if not actual or actual != digest:
            errs.append(f"SEALED_EXECUTION_FILE_MUTATED: node {node.get('id')} {rel!r} no longer matches "
                        f"implementation manifest {digest[:12]}")
    for rel, path in walked_paths.items():
        if rel not in expected and path.suffix.lower() in _EXECUTION_SOURCE_SUFFIXES:
            errs.append(f"UNSEALED_EXECUTION_SOURCE: node {node.get('id')} gained source file {rel!r} "
                        "after implementation approval")
    return errs


def implementation_repair_scope(report: str) -> str | None:
    """Return the single declared repair scope, if the report has one."""
    values = REPAIR_SCOPE_LINE.findall(
        eutil.find_section(eutil.md_sections(report), "repair scope") or "")
    return values[0] if len(values) == 1 else None


def _manifest_file_map(manifest: Any) -> dict[str, str]:
    if not isinstance(manifest, dict):
        return {}
    return {
        str(row.get("path") or "").replace("\\", "/"): str(row.get("digest") or "")
        for row in (manifest.get("files") or []) if isinstance(row, dict) and row.get("path")
    }


def implementation_manifest_changes(ctx: Ctx, node: dict) -> tuple[list[dict], list[str]]:
    """Compare the live candidate closure with the engine-frozen repair baseline."""
    rel = str(node.get("implementation_revision_baseline_path") or "")
    expected_digest = str(node.get("implementation_revision_baseline_digest") or "")
    if not rel or not expected_digest:
        return [], ["BUILD_REPAIR_BASELINE_MISSING: evaluation-only repair has no engine-frozen baseline"]
    path = eutil.rpath(ctx.store.repo, rel)
    if not path.is_file() or eseal.artifact_digest(ctx.store.repo, rel) != expected_digest:
        return [], ["BUILD_REPAIR_BASELINE_MUTATED: the engine-frozen implementation baseline changed"]
    baseline = eutil.read_json(path, None)
    if not isinstance(baseline, dict) or baseline.get("schema_version") != 1 \
            or baseline.get("node") != node.get("id"):
        return [], ["BUILD_REPAIR_BASELINE_INVALID: repair baseline identity/schema is invalid"]
    before = _manifest_file_map(baseline.get("manifest"))
    after = _manifest_file_map(build_implementation_manifest(ctx, node))
    changes: list[dict] = []
    for relpath in sorted(set(before) | set(after)):
        if before.get(relpath) == after.get(relpath):
            continue
        change = "added" if relpath not in before else "removed" if relpath not in after else "modified"
        # Copy-mode workareas legitimately gain checkpoints, metrics and logs
        # after the first seal.  They are execution products, not a code
        # revision.  New executable source remains part of the diff; modified
        # or removed pre-existing files remain fail-closed regardless of suffix.
        if change == "added" and Path(relpath).suffix.lower() not in _EXECUTION_SOURCE_SUFFIXES:
            continue
        changes.append({"path": relpath, "change": change,
                        "before": before.get(relpath), "after": after.get(relpath)})
    return changes, []


def evaluation_only_repair_errors(ctx: Ctx, node: dict, report: str) -> list[str]:
    """Validate the narrow claim that a code revision cannot affect old workflow output.

    Semantic non-interference is not generally statically decidable.  The
    engine therefore combines an exact changed-file account with a conservative
    protected set frozen before editing.  Touching that set requires widening
    the repair to ``workflow``; it can never be waved through as evaluation-only.
    """
    section = eutil.find_section(eutil.md_sections(report), "repair scope") or ""
    scopes = REPAIR_SCOPE_LINE.findall(section)
    errs: list[str] = []
    if len(scopes) != 1:
        return ["BUILD_REPAIR_SCOPE: evaluation-triggered repair needs exactly one "
                "REPAIR_SCOPE: evaluation|workflow line"]
    if scopes[0] == "workflow":
        return []  # explicit one-way widening; transition performs the full reset
    changes, change_errs = implementation_manifest_changes(ctx, node)
    errs.extend(change_errs)
    if change_errs:
        return errs
    actual = {str(row.get("path") or "") for row in changes}
    declared = {str(path).replace("\\", "/") for path in REPAIR_CHANGED_FILE_LINE.findall(section)}
    if not actual:
        errs.append("BUILD_EVAL_REPAIR_NO_CHANGE: evaluation-only implementation repair changed no sealed file")
    if declared != actual:
        errs.append(f"BUILD_EVAL_REPAIR_CHANGED_FILES: CHANGED_FILE rows must exactly match the manifest diff; "
                    f"missing={sorted(actual - declared)}, extra={sorted(declared - actual)}")
    baseline = eutil.read_json(
        eutil.rpath(ctx.store.repo, str(node.get("implementation_revision_baseline_path") or "")), {}) or {}
    protected = {str(path).replace("\\", "/")
                 for path in (baseline.get("workflow_protected_paths") or [])}
    overlap = sorted(actual & protected)
    if overlap:
        errs.append("BUILD_EVAL_REPAIR_TOUCHES_WORKFLOW: evaluation-only repair changed workflow-authoritative "
                    f"files {overlap}; declare REPAIR_SCOPE: workflow so prior training evidence is invalidated")
    arguments = WORKFLOW_REUSE_ARGUMENT_LINE.findall(section)
    if len(arguments) != 1 or len(arguments[0].strip()) < 80:
        errs.append("BUILD_EVAL_REPAIR_ARGUMENT: evaluation-only repair needs one "
                    "WORKFLOW_REUSE_ARGUMENT of at least 80 characters explaining why the exact changed files "
                    "cannot affect prior stage artifacts")
    return errs


def v_implement(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    nid = task["subject"]["node"]
    node = egraph.by_id(ctx.g).get(nid) or {}
    text = _read_md(ctx, task["outputs"][0], errs)
    if text is None:
        return errs
    spec = eutil.read_json(eutil.rpath(ctx.store.repo, node.get("spec") or ""), {}) or {}
    errs.extend(_workdir_isolation_errors(
        ctx, spec, role=str(node.get("role") or ""), where=f"implementation({nid})",
        current_node_id=nid))
    probe_execution = spec.get("probe_execution") if isinstance(spec.get("probe_execution"), dict) else None
    # v10.1: "workarea" (the engine already knows the workdir) and "self test"
    # (the engine runs smoke itself) were presence-only sections nobody read.
    # "deviations" stays: it is real context for the fidelity auditor.
    sections = ["mechanism to code map", "deviations"]
    if node.get("implementation_repair_scope") == "evaluation":
        sections.append("repair scope")
    if probe_execution:
        sections.append("probe instrumentation")
    if node.get("needs_metric_bridge"):
        sections.append("metric bridge adapter")
    _require_sections(text, sections, "BUILD_REPORT", errs)
    errs.extend(artifact_wiring_errors(ctx, node, spec, text))
    errs.extend(maintenance_boundary_errors(ctx, node, spec))
    if node.get("implementation_repair_scope") == "evaluation":
        errs.extend(evaluation_only_repair_errors(ctx, node, text))
    wd = eutil.rpath(ctx.store.repo, node.get("workdir") or ".")
    if (ctx.cfg.get("project") or {}).get("vcs") == "git":
        try:
            git_root = evcs.worktree_root(wd, strict=True)
            root_matches = bool(git_root) and git_root.resolve(strict=False) == wd.resolve(strict=False)
            tracked_clean = evcs.tracked_tree_clean(wd)
            late_sources = [p for p in evcs.untracked_files(wd)
                            if Path(p).suffix.lower() in _EXECUTION_SOURCE_SUFFIXES]
        except (evcs.GitCheckError, OSError, RuntimeError) as exc:
            errs.append(f"BUILD_GIT_CHECK_FAILED: Git could not audit the implementation safely: {exc}")
        else:
            if not root_matches:
                errs.append(f"GIT_WORKDIR_NOT_ROOT: node {nid} workdir {node.get('workdir')!r} must be a "
                            f"dedicated Git worktree root, not a subdirectory of {str(git_root)!r}")
            if not tracked_clean:
                errs.append("BUILD_GIT_DIRTY: commit all tracked/staged implementation and configuration bytes "
                            "before approval; runtime evidence may not bind a dirty working tree")
            if late_sources:
                errs.append(f"BUILD_GIT_UNTRACKED_SOURCE: commit or remove untracked execution sources {late_sources}")
    paths = re.findall(r"->\s*`?([\w./\\-]+\.\w{1,8})`?", text)
    live: list[str] = []
    escaped: set[str] = set()
    for relp in paths:
        target, confined = _mapped_workdir_path(ctx, node, relp)
        if not confined:
            if relp not in escaped:
                errs.append(f"BUILD_CODE_PATH_ESCAPE: mapped code path {relp!r} must resolve inside "
                            f"node {nid} workdir {node.get('workdir')!r}")
                escaped.add(relp)
        elif target.is_file():
            live.append(relp)
    idea_rel = str(node.get("idea_doc") or "").replace(".md", ".meta.json")
    idea = eutil.read_json(eutil.rpath(ctx.store.repo, idea_rel), {}) if idea_rel else {}
    idea = idea or {}
    expected_kernels = set(eprogram.kernel_ids(idea))
    if expected_kernels:
        rows = BUILD_OPERATOR_ROW.findall(eutil.find_section(eutil.md_sections(text), "mechanism to code map") or "")
        seen_kernels: set[str] = set()
        seen_operators: set[str] = set()
        kernel_rows = eprogram.kernel_components(idea)
        expected_operators = {str(op) for row in kernel_rows for op in (row.get("operator_refs") or [])}
        for opid, kid_text, relp in rows:
            kids = set(re.findall(r"KC\d+", kid_text))
            if opid not in expected_operators:
                errs.append(f"BUILD_OPERATOR_UNDECLARED: code map names {opid}, not a load-bearing approved operator")
            unknown_kids = kids - expected_kernels
            if unknown_kids:
                errs.append(f"BUILD_KERNEL_UNDECLARED: code map names unapproved kernels {sorted(unknown_kids)}")
            target, confined = _mapped_workdir_path(ctx, node, relp)
            if not confined:
                continue
            if not target.is_file():
                errs.append(f"BUILD_OPERATOR_FILE: {opid} points at missing file {relp!r}")
            else:
                seen_operators.add(opid)
                seen_kernels.update(kids)
        missing_kernels = sorted(expected_kernels - seen_kernels)
        missing_operators = sorted(expected_operators - seen_operators)
        if missing_kernels:
            errs.append(f"BUILD_KERNEL_COVERAGE: every approved KC# must map through a real operator; missing {missing_kernels}")
        if missing_operators:
            errs.append(f"BUILD_OPERATOR_COVERAGE: every load-bearing OP# must map to real code; missing {missing_operators}")
    elif not live:
        errs.append("BUILD_CODE_MAP: non-kernel/diagnostic implementation needs >=1 real changed file")
    if probe_execution:
        mode = str(probe_execution.get("mode") or "")
        artifact = str(probe_execution.get("artifact") or "")
        fields = [str(x) for x in (probe_execution.get("required_fields") or [])]
        probe_section = eutil.find_section(eutil.md_sections(text), "probe instrumentation") or ""
        if mode == "existing_artifact":
            sources = PROBE_SOURCE_LINE.findall(probe_section)
            if len(sources) != 1 or str(sources[0]).strip() != artifact:
                errs.append("BUILD_PROBE_SOURCE: existing_artifact mode needs exactly one "
                            "'PROBE_SOURCE: <registered artifact path>' line matching probe_execution.artifact")
            errs.extend(probe_artifact_errors(ctx, artifact, fields, where="implementation probe source"))
        else:
            artifacts = PROBE_ARTIFACT_LINE.findall(probe_section)
            if len(artifacts) != 1 or str(artifacts[0]).strip() != artifact:
                errs.append("BUILD_PROBE_ARTIFACT: probe instrumentation needs exactly one "
                            "'PROBE_ARTIFACT: <runtime JSON path/template>' line matching the frozen plan")
            rows = PROBE_FIELD_ROW.findall(probe_section)
            seen: set[str] = set()
            for field, relp, snippet in rows:
                if field not in fields:
                    errs.append(f"BUILD_PROBE_FIELD_UNDECLARED: {field!r} was not registered in required_fields")
                    continue
                if field in seen:
                    errs.append(f"BUILD_PROBE_FIELD_DUP: {field!r} has more than one instrumentation row")
                    continue
                seen.add(field)
                target, confined = _mapped_workdir_path(ctx, node, relp)
                if not confined:
                    continue
                if not target.is_file():
                    errs.append(f"BUILD_PROBE_FILE: field {field!r} points at missing file {relp!r}")
                    continue
                if len(snippet.split()) < 3:
                    errs.append(f"BUILD_PROBE_SNIPPET_SHORT: field {field!r} CODE snippet needs >=3 tokens")
                    continue
                if eutil.norm_ws(snippet) not in eutil.norm_ws(eutil.read_text(target)):
                    errs.append(f"BUILD_PROBE_SNIPPET: field {field!r} CODE snippet is not literally present in {relp}")
            missing = sorted(set(fields) - seen)
            if missing:
                errs.append(f"BUILD_PROBE_FIELDS_MISSING: every required numeric field needs one verified "
                            f"PROBE_FIELD row; missing {missing}")
    if node.get("needs_metric_bridge"):
        bridge_section = eutil.find_section(eutil.md_sections(text), "metric bridge adapter") or ""
        rows = BRIDGE_ADAPTER_ROW.findall(bridge_section)
        if len(rows) != 1:
            errs.append("BUILD_BRIDGE_ADAPTER: output-space changes require exactly one "
                        "BRIDGE_ADAPTER: <file> :: CODE: <literal adapter snippet> row")
        else:
            relp, snippet = rows[0]
            target, confined = _mapped_workdir_path(ctx, node, relp)
            if not confined or not target.is_file():
                errs.append(f"BUILD_BRIDGE_ADAPTER_FILE: adapter {relp!r} must be a real file inside the node workdir")
            elif len(snippet.split()) < 3 or eutil.norm_ws(snippet) not in eutil.norm_ws(eutil.read_text(target)):
                errs.append("BUILD_BRIDGE_ADAPTER_SNIPPET: adapter CODE must be a literal substantive snippet "
                            "from the implementation file")
    if (ctx.cfg.get("project") or {}).get("vcs") == "git" and node.get("role") != "baseline":
        branch = node.get("branch")
        if not branch:
            errs.append("GIT_BRANCH_UNSET: node has no branch recorded (engine bug; run 'evo doctor')")
        elif not evcs.branch_exists(ctx.store.repo, branch):
            errs.append(f"GIT_BRANCH_MISSING: branch '{branch}' does not exist; create it from the code parent and check it out in {node.get('workdir')}")
        else:
            hb = evcs.head_branch(wd)
            if hb != branch:
                errs.append(f"GIT_WORKDIR_BRANCH: workdir {node.get('workdir')} has '{hb}' checked out, expected '{branch}' (use a worktree of the node's branch)")
            cp = egraph.by_id(ctx.g).get(node.get("code_parent") or "")
            cp_ref = (cp or {}).get("commit") or (cp or {}).get("branch")
            if cp_ref and not evcs.is_ancestor(ctx.store.repo, cp_ref, f"refs/heads/{branch}"):
                errs.append(
                    f"GIT_ANCESTRY: branch '{branch}' does not descend from code parent {node.get('code_parent')} "
                    f"({cp_ref[:12]}) - the git history must mirror the code_parent chain of the DAG"
                )
    return errs


def v_fidelity(ctx: Ctx, task: dict) -> list[str]:
    """Implementation-fidelity audit (v8): complex ideas invite lazy builds -
    the report maps every mechanism claim to a code location WITH a literal
    snippet the engine string-checks against the real file. A coding agent
    cannot narrate fidelity into existence."""
    errs: list[str] = []
    nid = task["subject"]["node"]
    node = egraph.by_id(ctx.g).get(nid) or {}
    text = _read_md(ctx, task["outputs"][0], errs)
    if text is None:
        return errs
    _require_sections(text, ["claim map", "omissions and simplifications", "audit verdict"],
                      "FIDELITY", errs, min_chars=30)
    m = re.search(r"^FIDELITY:\s*(\S+)", text, re.M)
    if not m or m.group(1) not in ("FAITHFUL", "DEVIATES"):
        errs.append("FIDELITY_VERDICT: report must carry a line 'FIDELITY: FAITHFUL|DEVIATES'")
    errs.extend(critic_isolation_errors(
        ctx, task, release=bool(m and m.group(1) == "FAITHFUL"), author_types=("implement",)))
    if m and m.group(1) == "DEVIATES":
        errs.append("FIDELITY_DEVIATES: the implementation does not match the approved idea - fix the CODE "
                    "to match the mechanism (or route a genuine design change through Deviations in the "
                    "build report), then re-audit; a deviating build must not reach training")
    rows = FID_ROW.findall(text)
    live = 0
    idea_rel = str(node.get("idea_doc") or "").replace(".md", ".meta.json")
    idea = eutil.read_json(eutil.rpath(ctx.store.repo, idea_rel), {}) or {}
    expected_kernels = set(eprogram.kernel_ids(idea))
    covered: set[str] = set()
    expected_operators = {str(op) for row in eprogram.kernel_components(idea)
                          for op in (row.get("operator_refs") or [])}
    covered_operators: set[str] = set()
    for claim, relp, snippet in rows:
        target, confined = _mapped_workdir_path(ctx, node, relp)
        if not confined:
            errs.append(f"FIDELITY_PATH_ESCAPE: claim row path {relp!r} must resolve inside "
                        f"node {nid} workdir {node.get('workdir')!r}")
            continue
        if not target.is_file():
            errs.append(f"FIDELITY_FILE: claim row points at missing file {relp!r}")
            continue
        if len(snippet.split()) < 3:
            errs.append(f"FIDELITY_SNIPPET_SHORT: claim '{claim[:40]}': CODE snippet needs >= 3 tokens "
                        f"copied from the file")
            continue
        if eutil.norm_ws(snippet) not in eutil.norm_ws(eutil.read_text(target)):
            errs.append(f"FIDELITY_SNIPPET: claim '{claim[:40]}': CODE snippet is not literally present "
                        f"in {relp} - quote the real code, not what you meant to write")
            continue
        live += 1
        found = set(re.findall(r"\bKC\d+\b", claim))
        found_ops = set(re.findall(r"\bOP\d+\b", claim))
        unknown = found - expected_kernels
        if unknown:
            errs.append(f"FIDELITY_KERNEL_UNDECLARED: claim row names unapproved kernels {sorted(unknown)}")
        covered.update(found & expected_kernels)
        covered_operators.update(found_ops & expected_operators)
    if expected_kernels:
        missing = sorted(expected_kernels - covered)
        if missing:
            errs.append(f"FIDELITY_KERNEL_COVERAGE: verified snippets do not cover approved kernels {missing}")
        missing_ops = sorted(expected_operators - covered_operators)
        if missing_ops:
            errs.append(f"FIDELITY_OPERATOR_COVERAGE: verified snippets do not cover load-bearing operators {missing_ops}")
    elif live < 1:
        errs.append("FIDELITY_CLAIMS: claim map needs >=1 verified row")
    return errs


def v_ablation_fidelity(ctx: Ctx, task: dict) -> list[str]:
    """Prove that the implementation changed the registered factor and did not
    quietly change the controls before the single costly run is released."""
    errs: list[str] = []
    nid = task["subject"]["node"]
    node = egraph.by_id(ctx.g).get(nid) or {}
    if node.get("experiment_purpose") != "targeted_ablation":
        errs.append("ABLATION_FIDELITY_PURPOSE: this audit is only for targeted_ablation nodes")
    text = _read_md(ctx, task["outputs"][0], errs)
    if text is None:
        return errs
    _require_sections(text, ["changed-factor code map", "held-constant audit", "diff audit", "audit verdict"],
                      "ABLATION_FIDELITY", errs, min_chars=30)
    m = re.search(r"^FIDELITY:\s*(\S+)", text, re.M)
    if not m or m.group(1) not in ("FAITHFUL", "DEVIATES"):
        errs.append("ABLATION_FIDELITY_VERDICT: report must carry FIDELITY: FAITHFUL|DEVIATES")
    elif m.group(1) == "DEVIATES":
        errs.append("ABLATION_FIDELITY_DEVIATES: more than the registered factor changed or the factor was "
                    "not implemented; fix the code and re-audit before compute")
    meta = _idea_meta(ctx, node)
    contract = meta.get("ablation") or {}
    factor = (contract.get("changed_factor") or {}).get("name")
    factors = ABLATION_FACTOR_LINE.findall(text)
    if len(factors) != 1 or eutil.norm_ws(str(factors[0] if factors else "")) != eutil.norm_ws(str(factor or "")):
        errs.append("ABLATION_FIDELITY_FACTOR: report needs exactly one FACTOR line equal to the registered "
                    "changed_factor.name")
    registered_controls = {eutil.norm_ws(str(x)) for x in (contract.get("held_constant") or [])}
    controls = ABLATION_CONTROL_LINE.findall(text)
    reported_controls = {eutil.norm_ws(str(name)) for name, _proof in controls}
    missing_controls = sorted(registered_controls - reported_controls)
    if missing_controls:
        errs.append(f"ABLATION_FIDELITY_CONTROLS: every registered held_constant needs a matching CONTROL "
                    f"line; missing {missing_controls[:4]}")
    for name, proof in controls:
        _nontrivial(proof, 20, f"control proof for {name}", errs)
    rows = FID_ROW.findall(text)
    live = 0
    for claim, relp, snippet in rows:
        target, confined = _mapped_workdir_path(ctx, node, relp)
        if not confined:
            errs.append(f"ABLATION_FIDELITY_PATH_ESCAPE: changed-factor row path {relp!r} must resolve inside "
                        f"node {nid} workdir {node.get('workdir')!r}")
            continue
        if not target.is_file():
            errs.append(f"ABLATION_FIDELITY_FILE: changed-factor row points at missing file {relp!r}")
            continue
        if len(snippet.split()) < 3:
            errs.append(f"ABLATION_FIDELITY_SNIPPET_SHORT: claim '{claim[:40]}' needs >=3 literal code tokens")
            continue
        if eutil.norm_ws(snippet) not in eutil.norm_ws(eutil.read_text(target)):
            errs.append(f"ABLATION_FIDELITY_SNIPPET: claim '{claim[:40]}' snippet is not present in {relp}")
            continue
        live += 1
    if live < 1:
        errs.append("ABLATION_FIDELITY_CODE: changed-factor code map needs >=1 verified literal code row")
    return errs


def v_infra_drill(ctx: Ctx, task: dict) -> list[str]:
    """Accept only an engine-observed, integrated infrastructure canary.

    The agent still chooses the project-specific command, so unusual platforms
    remain first-class.  It no longer gets to author the command's exit/status
    or substitute hand-written evidence files for execution.
    """
    errs: list[str] = []
    report = _read_md(ctx, task["outputs"][0], errs)
    plan = _read_json(ctx, task["outputs"][1], errs)
    if report is None or plan is None:
        return errs
    _require_sections(report, ["canary executed", "surprises", "readiness"],
                      "INFRA_CANARY", errs, min_chars=40)
    errs.extend(ecanary.plan_errors(ctx.store, plan))
    record = task.get("infra_canary_run")
    errs.extend(ecanary.record_errors(ctx.store, record, expect_task=task.get("id")))
    if not isinstance(record, dict):
        return errs
    if record.get("status") == "failed":
        receipt, _ = ecanary.verified_receipt(ctx.store, record)
        receipt = receipt or {}
        details = "; ".join(str(x) for x in (receipt.get("errors") or [])[:5]) or "see engine-owned receipt/logs"
        errs.append(f"CANARY_RUN_FAILED: {details}; fix the project canary command and run-infra-canary again")
    return errs


def v_sota_scan(ctx: Ctx, task: dict) -> list[str]:
    """Research mode: the SOTA library - recent top-venue results on THIS task
    (same dataset/metric when they exist; at minimum a very close task), each
    with the headline number, so ideas can be bound to beat named entries."""
    errs: list[str] = []
    # R9: this task OWNS the ledger, so it validates the RAW file (its own
    # unaccepted suffix is exactly what it must repair); consumers elsewhere
    # see only the accepted prefix via ctx.sota_rows().
    ctx.use_draft_ledgers("sota")
    rows = ctx.sota_rows()
    errs.extend(_ledger_prefix_errors(rows, task["subject"].get("prior_sota_count"),
                                      task["subject"].get("prior_sota_digest"), "SOTA.jsonl"))
    res = ctx.cfg.get("research") or {}
    need = int(ctx.cfg.get("budgets", {}).get("sota_min_entries", 5))
    year_min = int(res.get("sota_recent_year") or 0)
    venues = {str(v).lower() for v in (res.get("sota_venues") or [])}
    if len(rows) < need:
        errs.append(f"SOTA_COUNT: SOTA.jsonl has {len(rows)} entries; needs >= {need} recent same-task "
                    f"(or nearest-task) results from the accepted venues")
    ids: set[str] = set()
    cells = econfig.cell_spec(ctx.cfg)
    for i, r in enumerate(rows):
        rid = str(r.get("id") or "")
        if not re.fullmatch(r"S\d{3,4}", rid):
            errs.append(f"SOTA_ID: entry {i}: id must be S###")
        if rid in ids:
            errs.append(f"SOTA_DUP: duplicate id {rid}")
        ids.add(rid)
        for f in ("title", "url", "method", "task"):
            if not str(r.get(f) or "").strip():
                errs.append(f"SOTA_FIELD: {rid}: '{f}' required")
        ven = str(r.get("venue") or "")
        if venues and ven.lower() not in venues:
            errs.append(f"SOTA_VENUE: {rid}: venue {ven!r} not in the accepted list - the library binds "
                        f"ideas to work worth beating, not to arbitrary preprint noise")
        if not isinstance(r.get("year"), int) or (year_min and r["year"] < year_min):
            errs.append(f"SOTA_YEAR: {rid}: integer year >= {year_min} required (the library is the "
                        f"CURRENT frontier, not a history lesson)")
        if not str(r.get("dataset") or "").strip():
            errs.append(f"SOTA_DATASET: {rid}: 'dataset' required ('none-shared' is legal when the task "
                        f"matches but no common benchmark exists)")
        cid = str(r.get("cell") or "")
        if cid not in cells or (cells.get(cid) or {}).get("role") != "target":
            errs.append(f"SOTA_CELL: {rid}: cell must resolve to a configured target C# cell")
        comparability = str(r.get("comparability") or "")
        if comparability not in ("exact", "protocol_adjusted", "near_task"):
            errs.append(f"SOTA_COMPARABILITY: {rid}: comparability must be exact|protocol_adjusted|near_task")
        hm = r.get("headline") or {}
        hv = hm.get("value")
        if not str(hm.get("metric") or "").strip() or isinstance(hv, bool) \
                or not isinstance(hv, (int, float)) or not math.isfinite(float(hv)):
            errs.append(f"SOTA_HEADLINE: {rid}: headline.metric + finite numeric headline.value required - "
                        f"a SOTA entry without its number cannot be beaten or checked")
        elif comparability == "exact" and cid in cells and str(hm.get("metric")) not in {
                str((cells[cid] or {}).get("metric") or ""), str((cells[cid] or {}).get("result_key") or "")}:
            errs.append(f"SOTA_EXACT_METRIC: {rid}: exact comparison headline metric must match cell {cid}")
    # R7 audit follow-up: the card orders a cross-source noise synthesis and
    # promises the engine preserves it for the USER - without this check the
    # promised handoff surface could silently not exist (submit ACCEPTed with
    # the synthesis skipped entirely). Old tasks without the declared output
    # are exempt (backward compatibility).
    noise_rel = next((o for o in (task.get("outputs") or [])
                      if str(o).endswith("SOTA_NOISE.md")), None)
    if noise_rel:
        noise_path = eutil.rpath(ctx.store.repo, str(noise_rel))
        if not noise_path.is_file() or not noise_path.read_text(
                encoding="utf-8", errors="replace").strip():
            errs.append(f"SOTA_NOISE_MISSING: {noise_rel}: write the cross-source measurement-noise "
                        "synthesis (per affected cell: recommended floor, the per-source spreads it "
                        "is the median of, citations) - or state explicitly that no adjustment is "
                        "needed and why; the engine preserves this file for the user's decision")
    return errs


def v_smoke(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    nid = task["subject"]["node"]
    res = _read_json(ctx, f".evo/nodes/{nid}/smoke/RESULTS.json", errs)
    if res is None:
        errs.append("SMOKE_NOT_RUN: run 'evo run-smoke --node %s' first; the engine executes the smoke plan itself" % nid)
        return errs
    if res.get("status") != "pass":
        failed = [s.get("name") for s in res.get("steps", []) if s.get("status") != "pass"]
        errs.append(f"SMOKE_FAILED: steps failed: {failed}; this rejection routes the node back to an "
                    "implement fix pass - do NOT edit the sealed implementation directly (the seal "
                    "audit would block every later command); fix inside the implement task, then a "
                    "fresh smoke runs")
    node = egraph.by_id(ctx.g).get(nid) or {}
    spec = eutil.read_json(eutil.rpath(ctx.store.repo, node.get("spec") or ""), {}) or {}
    probe = spec.get("probe_execution") if isinstance(spec.get("probe_execution"), dict) else None
    if probe and probe.get("mode") in ("same_run", "eval_intervention"):
        errs.extend(probe_artifact_errors(
            ctx, str(probe.get("smoke_artifact") or ""),
            [str(x) for x in (probe.get("required_fields") or [])],
            where=f"node {nid} probe smoke"))
    return errs


def v_metric_bridge(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    anchor_rel = next((o for o in task["outputs"] if str(o).endswith("ANCHOR.json")),
                      task["outputs"][0])
    anchor = _read_json(ctx, anchor_rel, errs)
    if anchor is None:
        return errs
    nid = str(task.get("subject", {}).get("node") or "")
    node = egraph.by_id(ctx.g).get(nid) or {}
    baseline = next((n for n in ctx.g.get("nodes", []) if n.get("role") == "baseline"), None) or {}
    baseline_path = str(baseline.get("eval_metrics_path") or f".evo/nodes/{baseline.get('id')}/eval/metrics.json")
    exp_raw = eutil.read_json(eutil.rpath(ctx.store.repo, baseline_path), None)
    if not isinstance(exp_raw, dict) or not isinstance(baseline.get("eval_seal"), dict):
        return errs + ["BRIDGE_BASELINE_AUTHORITY: the engine needs active sealed baseline evaluation metrics"]
    decision_keys = set(econfig.result_spec(ctx.cfg))
    exp = {k: metric_value(exp_raw.get(k)) for k in decision_keys}
    exp = {k: v for k, v in exp.items() if v is not None}
    got = anchor.get("produced") or {}
    tol_raw = anchor.get("tolerance_pct")
    if isinstance(tol_raw, bool) or not isinstance(tol_raw, (int, float)) or not math.isfinite(float(tol_raw)) \
            or not (0 <= float(tol_raw) <= 0.5):
        errs.append("BRIDGE_TOLERANCE: tolerance_pct must be finite and between 0 and 0.5")
        tol = 0.0
    else:
        tol = float(tol_raw) / 100.0
    if not exp or not isinstance(got, dict) or not got:
        errs.append("BRIDGE_ANCHOR: ANCHOR.json needs produced metrics and the sealed baseline must contain decision metrics")
        return errs
    claimed = anchor.get("baseline_expected")
    if claimed is not None and claimed != exp:
        errs.append("BRIDGE_BASELINE_EXPECTED_FORGED: optional baseline_expected must exactly equal engine-read sealed baseline metrics")
    missing = sorted(k for k in decision_keys if k not in exp or k not in got)
    if missing:
        errs.append(f"BRIDGE_ANCHOR_KEYS: the engine-read sealed baseline and produced must contain every configured result key; missing {missing}")
    # Operational metadata such as _usage is not a metric and must never enter
    # equivalence arithmetic.
    for k in sorted(decision_keys & set(exp) & set(got)):
        v = exp[k]
        pv = got.get(k)
        if not isinstance(pv, (int, float)) or not isinstance(v, (int, float)):
            errs.append(f"BRIDGE_ANCHOR_VALUE: metric {k}: numeric expected/produced required")
        elif abs(pv - v) > abs(v) * tol + 1e-12:
            errs.append(f"BRIDGE_ANCHOR_MISMATCH: metric {k}: produced {pv} vs baseline {v} exceeds tolerance {anchor.get('tolerance_pct')}% - the adapter does not reproduce baseline numbers")
    command = str(anchor.get("command") or "").strip()
    if len(command) < 8:
        errs.append("BRIDGE_COMMAND: ANCHOR.json must record the substantive command actually run")
    adapter = str(anchor.get("adapter") or "")
    target, confined = _mapped_workdir_path(ctx, node, adapter)
    manifest = eutil.read_json(eutil.rpath(ctx.store.repo, str(node.get("implementation_manifest") or "")), {}) or {}
    manifest_paths = {str((row or {}).get("path") or "") for row in (manifest.get("files") or [])
                      if isinstance(row, dict)}
    try:
        rel_adapter = target.relative_to(eutil.rpath(ctx.store.repo, str(node.get("workdir") or ".")).resolve()).as_posix()
    except (ValueError, OSError):
        rel_adapter = ""
    if not adapter or not confined or not target.is_file() or rel_adapter not in manifest_paths:
        errs.append("BRIDGE_ADAPTER_AUTHORITY: ANCHOR.json.adapter must name the adapter already sealed in the "
                    "current implementation manifest; this audit may not add code after implementation")
    return errs


def _terminal_launch_immutable_errors(ctx: Ctx, run: dict, data: dict) -> list[str]:
    """R8 (external audit r5): a pre-launch reconcile can seal a RUN's terminal
    evidence package (complete + quarantined) while its launch task is still
    open. run-update/run-reconcile both refuse to touch a terminal package -
    but the leftover completed-mode launch overwrote it and re-sealed the SAME
    attempt with different bytes as the new active revision. A launch against
    a complete package may only CONFIRM the identical bytes (whose absorption
    then adopts the quarantined package); any different execution needs a new
    RUN or a reviewed recovery."""
    if str(run.get("evidence_status") or "") != "complete":
        return []
    # R9 (external audit r6): the guard was completed-mode only, but a stale
    # BACKGROUND launch card submitted after a pre-launch reconcile sealed the
    # package could still redirect the ledger field and trigger a re-ingest of
    # different bytes over the terminal snapshot. Background mode confirms only
    # the fields it actually declares; completed mode stays strict on both.
    strict = data.get("mode") == "completed"
    errs: list[str] = []
    for field, label in (("metrics_file", "metrics_file"), ("ledger_file", "ledger_file")):
        declared = str(data.get(field) or "")
        sealed_rel = str(run.get(field) or "")
        if not strict and not declared:
            continue
        if not declared and not sealed_rel:
            continue
        same = False
        try:
            a = eutil.rpath(ctx.store.repo, declared) if declared else None
            b = eutil.rpath(ctx.store.repo, sealed_rel) if sealed_rel else None
            same = (a is not None and b is not None and a.is_file() and b.is_file()
                    and a.read_bytes() == b.read_bytes())
        except OSError:
            same = False
        if not same:
            errs.append(f"LAUNCH_TERMINAL_EVIDENCE_IMMUTABLE: RUN {run.get('id')} already holds a "
                        f"complete sealed evidence package; the launch's {label} must be byte-identical "
                        "to the sealed package (which is then simply adopted). A different execution or "
                        "result needs a NEW RUN or a reviewed recovery - a settled attempt is immutable")
    return errs


def _artifact_binding_errors(ctx: Ctx, node: dict) -> list[str]:
    """R8 (external audit r5): the frozen spec consumes a LOGICAL AR id, but
    the plan bound specific bytes (generation + content digest, engine-recorded
    at node creation). A producer fix that re-generates the same AR in place
    must not let this consumer silently execute on different input bytes."""
    bindings = node.get("artifact_bindings") if isinstance(node.get("artifact_bindings"), dict) else None
    if not bindings:
        return []
    errs: list[str] = []
    by_id = eartifact.by_id(ctx.reg)
    for aid, bound in bindings.items():
        art = by_id.get(str(aid))
        if art is None:
            errs.append(f"LAUNCH_ARTIFACT_MISSING: consumed artifact {aid} vanished from the registry; "
                        "recover the producer or replan this node")
            continue
        if str(art.get("status")) != "available":
            errs.append(f"LAUNCH_ARTIFACT_UNAVAILABLE: consumed artifact {aid} is {art.get('status')} "
                        f"({art.get('stale_reason') or 'producer superseded it'}); wait for / recover the "
                        "producer, or replan this node - executing on retracted input bytes would poison "
                        "the result's provenance")
            continue
        if art.get("generation") != (bound or {}).get("generation") or \
                str(art.get("content_digest") or "") != str((bound or {}).get("content_digest") or ""):
            errs.append(f"LAUNCH_ARTIFACT_GENERATION_DRIFT: {aid} is now generation "
                        f"{art.get('generation')} but this node's plan sealed generation "
                        f"{(bound or {}).get('generation')}; the input identity changed after freeze - "
                        "if the new bytes are the intended input, re-freeze with `evo rebind-artifact "
                        f"--node {node.get('id')} --artifact {aid} --note <why>`; otherwise recover the producer "
                        "back to the sealed generation - never silently execute on different bytes")
            continue
        # R9 (external audit r6): the registry digest and the frozen binding
        # come from the SAME registration-time snapshot, so an in-place
        # overwrite of the underlying local file left both equal while the
        # bytes changed. Re-hash the live bytes at the moment external spend
        # is authorized (remote URIs stay producer-receipt custody).
        live_digest, checkable = eartifact.content_custody(ctx.store, str(art.get("uri") or ""))
        if checkable and live_digest != str((bound or {}).get("content_digest") or ""):
            errs.append(f"LAUNCH_ARTIFACT_BYTES_DRIFTED: {aid} ({art.get('uri')}): the live bytes no "
                        f"longer match the digest frozen at plan time ({'missing' if not live_digest else live_digest[:12]}); "
                        "something overwrote the product in place - recover the producer or replan "
                        "before executing on unverified input bytes")
    return errs


def v_rehearsal(ctx: Ctx, task: dict) -> list[str]:
    """The rehearsal task submits the ENGINE's receipt, nothing else: passed
    receipts bound to the current seal accept; failed ones route to an
    implementation fix pass (typed); blocked ones escalate to the user."""
    node = egraph.by_id(ctx.g).get(str((task.get("subject") or {}).get("node") or ""))
    if node is None:
        return ["INTERNAL: node missing"]
    record = node.get("rehearsal_run")
    if not isinstance(record, dict):
        return ["REHEARSAL_RUN_MISSING: run the engine-executed rehearsal first "
                "('evo run-rehearsal --node " + str(node.get("id")) + "') - a hand-written "
                "receipt is not evidence"]
    errs = erehearsal.record_errors(ctx.store, node, require_passed=False)
    if errs:
        return errs
    status = str(record.get("status") or "")
    if status == "passed":
        return []
    receipt = eutil.read_json(eutil.rpath(ctx.store.repo, str(record.get("receipt") or "")), {}) or {}
    if status == "blocked":
        rows = "; ".join(f"{(b or {}).get('missing')} (ask: {(b or {}).get('ask')})"
                         for b in (receipt.get("blockers") or [])[:4])
        return [f"REHEARSAL_BLOCKED: the tiny full-chain pass is blocked on user-suppliable "
                f"access/resources: {rows}"]
    rows = "; ".join(str(e) for e in (receipt.get("errors") or [])[:5])
    return [f"REHEARSAL_FAILED: the tiny full-chain pass did not prove the workflow: {rows} - "
            "the fix pass repairs the wiring, then a fresh rehearsal re-proves it"]


def v_stage_launch(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    data = _read_json(ctx, task["outputs"][0], errs)
    if data is None:
        return errs
    expected_run = str(task["subject"].get("run") or "")
    run = ctx.store.get_run(ctx.st, expected_run) or {}
    if not expected_run or str(data.get("run") or "") != expected_run:
        errs.append(f"LAUNCH_RUN: LAUNCH.json run must equal the engine-prepared attempt {expected_run!r}")
    if not run or str(data.get("attempt_token") or "") != str(run.get("attempt_token") or ""):
        errs.append("LAUNCH_ATTEMPT_TOKEN: LAUNCH.json must carry the exact prepared RUN attempt_token")
    expect_stage = str(task["subject"].get("stage") or "stage")
    expected_seed = task["subject"].get("replica_seed")
    if str(data.get("stage") or "") != expect_stage:
        errs.append(f"LAUNCH_STAGE: LAUNCH.json stage must be '{expect_stage}' (the node's current stage), got {data.get('stage')!r}")
    if data.get("mode") not in ("background", "completed"):
        errs.append("LAUNCH_MODE: LAUNCH.json mode must be 'background' or 'completed'")
    if data.get("mode") == "background" and not str(data.get("job") or "").strip():
        errs.append("LAUNCH_JOB: background launches must record a 'job' identifier (how to check status)")
    if run.get("job") and str(data.get("job") or "").strip() \
            and str(data.get("job")) != str(run.get("job")):
        # both modes: a completed-mode conflict would otherwise surface as a raw
        # RunTransitionError traceback in the transition instead of a rejection
        errs.append(f"LAUNCH_JOB_MISMATCH: prepared RUN {expected_run} is already bound to job {run.get('job')!r}")
    if expected_seed is not None and _seed_token(data.get("seed")) != _seed_token(expected_seed):
        errs.append(f"LAUNCH_SEED: LAUNCH.json seed must equal this workflow lane's declared seed {expected_seed!r}")
    node = egraph.by_id(ctx.g).get(str(task["subject"].get("node") or "")) or {}
    errs.extend(_artifact_binding_errors(ctx, node))
    spec = eutil.read_json(eutil.rpath(ctx.store.repo, node.get("spec") or ""), {}) or {}
    stage = next((s for s in econfig.stages_of(spec)
                  if str(s.get("name") or "") == expect_stage), {})
    strict_seed_paths = ((spec.get("training_replication") or {}).get("mode") == "preplanned")
    repeat_lane = bool(task["subject"].get("repeat_measure"))
    # v11.7: real spend rides only a proven chain - the tiny full-chain
    # rehearsal receipt must exist, authenticate, and bind the CURRENT
    # implementation seal. The repeat lane re-runs a proven pipeline.
    if not repeat_lane and erehearsal.required(ctx.cfg, node, spec):
        errs.extend(erehearsal.record_errors(ctx.store, node))
    if ctx.st.get("infra_revision_pending"):
        errs.append("INFRA_REVISION_UNPROVEN: a facts revision was adopted but its fresh canary "
                    "proof is still owed - new stage spend waits for it (run 'evo next'; the "
                    "engine presents the canary task)")
    if repeat_lane and stage and expected_seed is not None:
        # R9-002/R10-012: the repeat lane lands at the spec's OWN resolved
        # paths (one resolution rule for every attempt); identity enforced
        expected_metrics = str(econfig.resolve_seed_template(stage.get("metrics_file") or "", expected_seed))
        expected_ledger = str(econfig.resolve_seed_template(stage.get("ledger_file") or "", expected_seed)) \
            if econfig.stage_requires_ledger(stage) else None
    else:
        expected_metrics = str(econfig.resolve_seed_template(stage.get("metrics_file") or "", expected_seed)) \
            if stage and expected_seed is not None and strict_seed_paths else None
        expected_ledger = str(econfig.resolve_seed_template(stage.get("ledger_file") or "", expected_seed)) \
            if stage and expected_seed is not None and strict_seed_paths and econfig.stage_requires_ledger(stage) else None
    if data.get("mode") == "background" and expected_ledger is not None \
            and str(data.get("ledger_file") or "") != expected_ledger:
        errs.append(f"LAUNCH_LEDGER_PATH: background launch must bind ledger_file to {expected_ledger!r}")
    errs.extend(_terminal_launch_immutable_errors(ctx, run, data))
    if data.get("mode") == "completed":
        mf = data.get("metrics_file")
        if not mf or not _exists(ctx, mf):
            errs.append("LAUNCH_METRICS: completed launches must point at an existing metrics_file "
                        "(paths resolve from the REPOSITORY ROOT, never from the stage working "
                        "directory - a file written beside the stage code needs its "
                        "workdir-qualified repo-relative path)")
        if stage:
            errs.extend(stage_result_errors(ctx, stage, str(mf or ""), data.get("ledger_file"),
                                            where=f"completed stage {expect_stage}",
                                            expected_seed=(expected_seed
                                                           if (strict_seed_paths or repeat_lane) else None),
                                            expected_metrics_file=expected_metrics,
                                            expected_ledger_file=expected_ledger))
            # LAUNCH.json acknowledges the execution fact; evidence ingestion
            # below owns probe completeness.  Rejecting a completed launch for
            # a late/missing probe would prevent the RUN from ever reaching the
            # explicit same-RUN reconciliation state.
    return errs


def stage_metrics_of(ctx: Ctx, nid: str) -> dict[str, dict]:
    """Summary metrics and resource use of every active finished stage run."""
    out: dict[str, dict] = {}
    for r in ctx.st.get("runs", []):
        if r.get("node") == nid and r.get("kind") == "stage" and r.get("status") == "finished" \
                and r.get("adoption_status") == "adopted":
            mf = r.get("metrics_file")
            data = eutil.read_json(eutil.rpath(ctx.store.repo, mf), None) if mf else None
            if isinstance(data, dict):
                source = data.get("summary") if isinstance(data.get("summary"), dict) else data
                nums = {k: v for k, v in source.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)}
                usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
                nums.update({f"usage.{k}": v for k, v in usage.items()
                             if isinstance(v, (int, float)) and not isinstance(v, bool)})
                if nums:
                    stage_name = str(r.get("stage") or "stage")
                    # R9-002: the repeat lane's rows must never shadow the base
                    # attempt's rows in the evidence view - key them by seed
                    key = (f"seed={r.get('replica_seed')}/{stage_name}"
                           if int(r.get("replica_total") or 1) > 1 or r.get("repeat_measure_attempt")
                           else stage_name)
                    out[key] = nums
    return out


def stage_ledgers_of(ctx: Ctx, nid: str) -> dict[str, str]:
    """Engine-recorded decision/component ledgers for adaptive/multiple stages."""
    return {
        (f"seed={r.get('replica_seed')}/{r.get('stage') or 'stage'}"
         if int(r.get("replica_total") or 1) > 1 or r.get("repeat_measure_attempt")
         else str(r.get("stage") or "stage")): str(r.get("ledger_file"))
        for r in ctx.st.get("runs", [])
        if r.get("node") == nid and r.get("kind") == "stage" and r.get("status") == "finished"
        and str(r.get("ledger_file") or "").strip() and r.get("adoption_status") == "adopted"
    }


def _replication_metric_errors(key: str, raw: dict, expected: dict) -> list[str]:
    errs: list[str] = []
    block = raw.get("training_replication")
    if not isinstance(block, dict):
        return [f"EVAL_TRAINING_REPLICATION_MISSING: '{key}' must report every preplanned training run; "
                "a scalar/mean alone is not evidence of replication"]
    if raw.get("uncertainty") is not None:
        errs.append(f"EVAL_TRAINING_REPLICATION_UNCERTAINTY_MIXED: '{key}' may not mix training-run aggregation "
                    "with sample-level uncertainty in one object")
    aggregation = block.get("aggregation")
    if aggregation != expected.get("aggregation") or aggregation not in ("mean", "median"):
        errs.append(f"EVAL_TRAINING_REPLICATION_AGGREGATION: '{key}' aggregation must equal the preplanned "
                    f"rule {expected.get('aggregation')!r}")
    runs = block.get("runs")
    expected_seeds = expected.get("seeds") or []
    if not isinstance(runs, list) or len(runs) != expected.get("runs"):
        errs.append(f"EVAL_TRAINING_REPLICATION_RUNS: '{key}' must contain exactly {expected.get('runs')} run records")
        runs = []
    observed: dict[str, float] = {}
    for i, run in enumerate(runs):
        if not isinstance(run, dict):
            errs.append(f"EVAL_TRAINING_REPLICATION_RUN_SHAPE: '{key}'.runs[{i}] must be an object")
            continue
        token = _seed_token(run.get("seed"))
        if token is None:
            errs.append(f"EVAL_TRAINING_REPLICATION_SEED: '{key}'.runs[{i}].seed must be an integer or non-empty string")
        elif token in observed:
            errs.append(f"EVAL_TRAINING_REPLICATION_SEED_DUP: '{key}' repeats seed {run.get('seed')!r}")
        value = run.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            errs.append(f"EVAL_TRAINING_REPLICATION_VALUE: '{key}'.runs[{i}].value must be finite")
        elif token is not None:
            observed[token] = float(value)
        if len(str(run.get("source") or "").strip()) < 8:
            errs.append(f"EVAL_TRAINING_REPLICATION_SOURCE: '{key}'.runs[{i}].source must identify the run/artifact")
    expected_tokens = {_seed_token(x) for x in expected_seeds}
    if None not in expected_tokens and set(observed) != expected_tokens:
        errs.append(f"EVAL_TRAINING_REPLICATION_SEED_SET: '{key}' run seeds must exactly match the preplanned set")
    if aggregation in ("mean", "median") and None not in expected_tokens \
            and set(observed) == expected_tokens:
        values = [observed[_seed_token(seed)] for seed in expected_seeds]
        aggregate = statistics.mean(values) if aggregation == "mean" else statistics.median(values)
        point = raw.get("value")
        if isinstance(point, bool) or not isinstance(point, (int, float)) or not math.isfinite(float(point)):
            errs.append(f"EVAL_METRIC_VALUE: '{key}'.value must be the finite preplanned aggregate")
        elif not math.isclose(float(point), float(aggregate), rel_tol=1e-12, abs_tol=1e-12):
            errs.append(f"EVAL_TRAINING_REPLICATION_RECOMPUTE: '{key}'.value={point} does not equal the "
                        f"engine-recomputed {aggregation}={aggregate}")
    return errs


def metric_evidence_errors(ctx: Ctx, key: str, raw: Any,
                           training_replication: dict | None = None,
                           node: dict | None = None) -> list[str]:
    """Validate one decision metric without implying any extra training.

    A plain finite number is legal for a single training run. An uncertainty interval is legal only when
    it was derived from a fixed evaluation artifact using an analytic formula
    or resampling predictions from that same artifact. Full-training repeats are
    representable only when the bootstrap contract preplanned them and the
    metric exposes every run/seed/source for engine recomputation.
    """
    expected = training_replication if isinstance(training_replication, dict) \
        and training_replication.get("mode") == "preplanned" else None
    # v11.1 P4: a user-approved repeat_measure on THIS metric is the one legal
    # way a single-run project reports a 2-run set - and once approved, the
    # aggregate is mandatory, or approval would be free to ignore. A waived
    # approval (evo waive-repeat: the repeat physically could not run) releases
    # the duty and the single-run verdict stands, on record.
    rm = (node or {}).get("repeat_measure") if isinstance(node, dict) else None
    rm = rm if isinstance(rm, dict) and str(rm.get("result_key") or "") == str(key) \
        and not rm.get("waived") else None
    if isinstance(raw, bool):
        return [f"EVAL_METRIC_VALUE: '{key}' must be a finite number"]
    if isinstance(raw, (int, float)):
        if expected:
            return [f"EVAL_TRAINING_REPLICATION_MISSING: '{key}' is scalar but the approved protocol requires "
                    "explicit per-training-run evidence"]
        if rm:
            return [f"EVAL_REPEAT_MEASURE_MISSING: '{key}': the user approved buying back one repeat "
                    f"(gate {rm.get('gate')}); report BOTH runs in training_replication (seeds "
                    f"{rm.get('base_seed')!r}, {rm.get('seed')!r}, aggregation mean) with value = the mean. "
                    "If the repeat physically cannot be executed, the USER may release the duty with "
                    "'evo waive-repeat --node ... --note ...' and the single-run verdict stands, on record"]
        return [] if math.isfinite(float(raw)) else [f"EVAL_METRIC_VALUE: '{key}' must be finite"]
    if not isinstance(raw, dict):
        return [f"EVAL_METRIC_MISSING: metrics.json must contain '{key}' as a finite number or explicit interval object"]
    legacy = sorted(set(raw) & {"mean", "std", "n"})
    if legacy:
        return [f"EVAL_METRIC_LEGACY_AGGREGATE: '{key}' uses {legacy}; mean/std/n is ambiguous about "
                "samples versus repeated training. Use value + uncertainty with explicit method/unit_count/"
                "procedure/source, "
                "or report a scalar"]
    if "training_replication" in raw:
        if rm and not expected:
            errs2 = _replication_metric_errors(key, raw, {
                "mode": "preplanned", "runs": 2, "aggregation": "mean",
                "seeds": [rm.get("base_seed"), rm.get("seed")]})
            repeat_token = _seed_token(rm.get("seed"))
            reg = getattr(ctx, "reg", None)
            has_repo = getattr(getattr(ctx, "store", None), "repo", None) is not None
            st_runs = (getattr(ctx, "st", None) or {}).get("runs", [])
            repeat_run = next((r for r in st_runs
                               if r.get("id") == (node or {}).get("repeat_eval_run")), None)
            if rm.get("engine_run") and repeat_run is None:
                # R9-002: an engine-run buy-back may only aggregate sealed
                # engine facts - before the repeat RUN settles there is no
                # second number to report, and no citation can substitute.
                errs2.append(f"EVAL_REPEAT_RUN_PENDING: '{key}': the engine-run repeat evaluation has "
                             "not settled yet; the 2-run aggregate cites sealed engine RUNs only - "
                             "let the scheduler finish the repeat lane first")
            elif repeat_run is not None and has_repo:
                # R9-002: the repeat is a first-class engine RUN - its row is
                # pinned to the sealed repeat measurement exactly like the
                # base row is pinned below (neither number is negotiable).
                sealed_rep = econfig.result_value(
                    (eutil.read_json(eutil.rpath(ctx.store.repo,
                                                 str(repeat_run.get("metrics_file") or "")), {}) or {}).get(key))
                rep_src_expected = str(repeat_run.get("metrics_file") or "")
                for r in (raw.get("training_replication") or {}).get("runs") or []:
                    if not (isinstance(r, dict) and _seed_token(r.get("seed")) == repeat_token):
                        continue
                    v = r.get("value")
                    if isinstance(sealed_rep, (int, float)) and not isinstance(sealed_rep, bool) \
                            and isinstance(v, (int, float)) and not isinstance(v, bool) \
                            and not math.isclose(float(v), float(sealed_rep), rel_tol=1e-9, abs_tol=1e-12):
                        errs2.append(f"EVAL_REPEAT_MEASURE_REPEAT_MISMATCH: '{key}': the repeat run's "
                                     f"reported value {v} does not equal the sealed repeat-RUN "
                                     f"measurement {sealed_rep}; the repeat buys a second number, "
                                     "never an editable one")
                    src = str(r.get("source") or "").strip()
                    if eutil.norm_uri(src) != eutil.norm_uri(rep_src_expected)                             and src != str(repeat_run.get("id") or ""):
                        errs2.append(f"EVAL_REPEAT_SOURCE_RUN: '{key}': the repeat row's source must "
                                     f"cite the sealed repeat RUN - use its sealed metrics path "
                                     f"{rep_src_expected!r} (or the RUN id {repeat_run.get('id')!r})")
            else:
                # R8 (external audit r5), legacy pre-engine-run approvals: the
                # bought-back second run has no engine RUN behind it (recorded
                # degraded delivery) - its source citation is its ONLY custody,
                # so it must at least resolve to something checkable: an
                # existing repo path or a registered artifact.
                for r in (raw.get("training_replication") or {}).get("runs") or []:
                    if isinstance(r, dict) and _seed_token(r.get("seed")) == repeat_token and has_repo:
                        src = str(r.get("source") or "").strip()
                        registered = (eartifact.by_id(reg).get(src) if src and reg else None) \
                            or (eartifact.find_by_uri(reg, src) if src and reg else None)
                        if src and not _exists(ctx, src) and not registered:
                            errs2.append(f"EVAL_REPEAT_SOURCE_MISSING: '{key}': the repeat run's source "
                                         f"{src!r} must be an existing repo path or a registered "
                                         "artifact - the manual repeat's only custody is a checkable "
                                         "citation (if the repeat physically cannot run, the USER may "
                                         "release the duty: 'evo waive-repeat --node ... --note ...')")
            # v11.1 (R1 fix): the base run's reported value must equal the
            # SEALED raw eval measurement the engine already holds - the first
            # run's truth is not negotiable at aggregation time.
            sealed = None
            st_runs = (getattr(ctx, "st", None) or {}).get("runs", [])
            eval_run = next((r for r in st_runs if r.get("id") == (node or {}).get("eval_run")), None)
            if eval_run:
                sealed = econfig.result_value(
                    (eutil.read_json(eutil.rpath(ctx.store.repo,
                                                 str(eval_run.get("metrics_file") or "")), {}) or {}).get(key))
            if isinstance(sealed, (int, float)) and not isinstance(sealed, bool):
                base_token = _seed_token(rm.get("base_seed"))
                for r in (raw.get("training_replication") or {}).get("runs") or []:
                    if isinstance(r, dict) and _seed_token(r.get("seed")) == base_token:
                        v = r.get("value")
                        if isinstance(v, (int, float)) and not isinstance(v, bool) \
                                and not math.isclose(float(v), float(sealed), rel_tol=1e-9, abs_tol=1e-12):
                            errs2.append(f"EVAL_REPEAT_MEASURE_BASE_MISMATCH: '{key}': the base run's "
                                         f"reported value {v} does not equal the sealed first-run "
                                         f"measurement {sealed}; the repeat buys a second number, "
                                         "never a rewrite of the first")
            return errs2
        if not expected:
            return [f"EVAL_TRAINING_REPLICATION_UNAPPROVED: '{key}' reports repeated training, but this node's "
                    "user-approved protocol is single-run"]
        return _replication_metric_errors(key, raw, expected)
    if rm:
        return [f"EVAL_REPEAT_MEASURE_MISSING: '{key}': the approved repeat_measure requires the 2-run "
                "training_replication block (see the evaluation card's repeat block)"]
    if expected:
        return [f"EVAL_TRAINING_REPLICATION_MISSING: '{key}' must report the preplanned runs explicitly"]
    errs: list[str] = []
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        errs.append(f"EVAL_METRIC_VALUE: '{key}'.value must be a finite number")
    unc = raw.get("uncertainty")
    if not isinstance(unc, dict):
        return errs + [f"EVAL_UNCERTAINTY_SHAPE: '{key}'.uncertainty must be an object"]
    method = unc.get("method")
    if method not in econfig.UNCERTAINTY_METHODS:
        errs.append(f"EVAL_UNCERTAINTY_METHOD: '{key}' method must be one of {econfig.UNCERTAINTY_METHODS}; "
                    "training-seed repeats are legal only through the project-level preplanned protocol")
    if unc.get("unit") not in econfig.UNCERTAINTY_UNITS:
        errs.append(f"EVAL_UNCERTAINTY_UNIT: '{key}' unit must be one of {econfig.UNCERTAINTY_UNITS}")
    unit_count = unc.get("unit_count")
    if not isinstance(unit_count, int) or isinstance(unit_count, bool) or unit_count < 2:
        errs.append(f"EVAL_UNCERTAINTY_COUNT: '{key}' unit_count must be an integer >= 2 and counts fixed "
                    "evaluation units, never seeds or training runs")
    if len(str(unc.get("procedure") or "").strip()) < 20:
        errs.append(f"EVAL_UNCERTAINTY_PROCEDURE: '{key}' procedure must name the formula/script or resampling "
                    "rule used on the fixed artifact (>= 20 chars)")
    if unc.get("level") != 0.95:
        errs.append(f"EVAL_UNCERTAINTY_LEVEL: '{key}' level must be 0.95 so all node and Pareto decisions use one semantics")
    lo, hi = unc.get("lower"), unc.get("upper")
    finite_bounds = all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(float(x))
                        for x in (lo, hi))
    if not finite_bounds:
        errs.append(f"EVAL_UNCERTAINTY_BOUNDS: '{key}' lower/upper must be finite numbers")
    elif isinstance(value, (int, float)) and not isinstance(value, bool) and \
            not (float(lo) <= float(value) <= float(hi)):
        errs.append(f"EVAL_UNCERTAINTY_ORDER: '{key}' must satisfy lower <= value <= upper")
    source = str(unc.get("source") or "")
    registered = eartifact.by_id(ctx.reg).get(source) if source else None
    registered = registered or (eartifact.find_by_uri(ctx.reg, source) if source else None)
    # R7: a registry row authorizes the interval only while it is AVAILABLE -
    # an invalid/stale AR (producer pruned, artifact superseded) with a dead
    # URI could still license bounds that then voted in noninferiority and
    # dominance decisions with no seal anyone could audit.
    if registered is not None and str(registered.get("status") or "") != "available" \
            and not _exists(ctx, source):
        errs.append(f"EVAL_UNCERTAINTY_SOURCE_STATUS: '{key}' source {source} resolves to registry entry "
                    f"{registered.get('id')} with status={registered.get('status')!r}; the fixed artifact "
                    "behind an interval must be available (or an existing local path)")
    if not source or (not _exists(ctx, source) and not registered):
        errs.append(f"EVAL_UNCERTAINTY_SOURCE: '{key}' source must be an existing local path, registered AR###, "
                    "or registered URI for the fixed evaluation/prediction artifact")
    if unc.get("extra_training_runs") != 0:
        errs.append(f"EVAL_UNCERTAINTY_TRAINING: '{key}' extra_training_runs must be exactly 0; "
                    "evaluation uncertainty may not create training runs")
    if method == "fixed_predictions_bootstrap":
        resamples = unc.get("resamples")
        if not isinstance(resamples, int) or isinstance(resamples, bool) or resamples < 100:
            errs.append(f"EVAL_UNCERTAINTY_RESAMPLES: '{key}' fixed_predictions_bootstrap needs integer resamples >= 100")
    return errs


def _raw_binding_close(a: Any, b: Any) -> bool:
    return (isinstance(a, (int, float)) and not isinstance(a, bool)
            and isinstance(b, (int, float)) and not isinstance(b, bool)
            and math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-12))


def normalized_raw_binding_errors(ctx: Ctx, node: dict, metrics: dict) -> list[str]:
    """R7 external audit: normalization interprets the sealed eval RUN - it
    never re-measures. Every configured point value, per-seed replication row,
    producer-sealed uncertainty bound and producer-reported usage unit must
    equal the sealed raw measurement; the analyst may only ADD what the
    evaluation card licenses (an uncertainty interval derived from a fixed
    artifact around a raw scalar, report text, the probe reading). The
    repeat_measure base run always had this equality check; the ordinary
    path - every project's main road - did not, so one mistyped
    normalization silently replaced the experiment's facts."""
    run = next((r for r in (ctx.st.get("runs") or [])
                if str(r.get("id") or "") == str(node.get("eval_run") or "")), None)
    if not run:
        return []
    raw = eutil.read_json(eutil.rpath(ctx.store.repo, str(run.get("metrics_file") or "")), None)
    if not isinstance(raw, dict):
        return [f"EVAL_NORMALIZED_RAW_UNREADABLE: the sealed raw metrics of RUN {run.get('id')} "
                f"({run.get('metrics_file')}) cannot be read back for the raw-binding audit; "
                "run 'evo doctor' - the sealed producer evidence is the settlement authority"]
    errs: list[str] = []
    human_keys = {str(c.get("result_key") or "") for c in econfig.evaluation_cells(ctx.cfg)
                  if str(c.get("source_kind") or "") == "human_study"}
    rm = node.get("repeat_measure") if isinstance(node.get("repeat_measure"), dict) else None
    rm_key = str(rm.get("result_key") or "") if rm and not rm.get("waived") else ""
    for key in econfig.result_spec(ctx.cfg):
        if key in human_keys or key == rm_key or key not in raw:
            continue
        raw_v, norm_v = raw.get(key), metrics.get(key)
        raw_point, norm_point = metric_value(raw_v), metric_value(norm_v)
        if raw_point is not None and norm_point is not None \
                and not _raw_binding_close(raw_point, norm_point):
            errs.append(f"EVAL_NORMALIZED_RAW_MISMATCH: '{key}': normalized point {norm_point} != sealed "
                        f"raw measurement {raw_point} (RUN {run.get('id')}); copy the raw value verbatim - "
                        "an uncertainty interval may be added around it, the point itself is not negotiable")
        raw_rep = raw_v.get("training_replication") if isinstance(raw_v, dict) else None
        norm_rep = norm_v.get("training_replication") if isinstance(norm_v, dict) else None
        if isinstance(raw_rep, dict):
            def _rep_rows(rep: dict) -> dict:
                return {_seed_token(r.get("seed")): r.get("value")
                        for r in (rep.get("runs") or []) if isinstance(r, dict)}
            r_rows = _rep_rows(raw_rep)
            n_rows = _rep_rows(norm_rep) if isinstance(norm_rep, dict) else {}
            if set(r_rows) != set(n_rows) \
                    or any(not _raw_binding_close(r_rows[s], n_rows[s]) for s in r_rows):
                errs.append(f"EVAL_NORMALIZED_RAW_REPLICATION: '{key}': per-seed replication rows must "
                            f"equal the sealed raw RUN's rows verbatim (RUN {run.get('id')}); "
                            "aggregation happens on the sealed numbers, never on restated ones")
        raw_unc = raw_v.get("uncertainty") if isinstance(raw_v, dict) else None
        norm_unc = norm_v.get("uncertainty") if isinstance(norm_v, dict) else None
        if isinstance(raw_unc, dict) and not (
                isinstance(norm_unc, dict)
                and _raw_binding_close(raw_unc.get("lower"), norm_unc.get("lower"))
                and _raw_binding_close(raw_unc.get("upper"), norm_unc.get("upper"))):
            errs.append(f"EVAL_NORMALIZED_RAW_UNCERTAINTY: '{key}': the producer RUN sealed an "
                        "uncertainty interval; the normalized bounds must carry it verbatim")
    raw_u = raw.get("_usage") if isinstance(raw.get("_usage"), dict) else {}
    norm_u = metrics.get("_usage") if isinstance(metrics.get("_usage"), dict) else {}
    for unit, v in raw_u.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        if not _raw_binding_close(v, norm_u.get(unit)):
            errs.append(f"EVAL_NORMALIZED_RAW_USAGE: _usage.{unit}: normalized value {norm_u.get(unit)!r} "
                        f"!= sealed raw usage {v} (RUN {run.get('id')}); usage is measured by the "
                        "producer, never restated by the analyst")
    # R9 (external audit r6): the binding only compared units PRESENT in raw, so
    # an analyst could INVENT an execution fact the producer never reported
    # (e.g. _usage.trials_completed on a physical harness) and the downstream
    # gate believed it. Normalization copies usage; it never adds to it.
    # Era carve-out: trials_completed may be SUPPLIED on the normalized side
    # when the sealed raw lacks it - that is the pre-R9 reporting channel, and
    # closing it wedged in-flight upgrades between this error and
    # EVAL_HARNESS_TRIALS (raw sealed without the key is immutable). Fresh
    # raw carries the key (absorption/launch enforce it), so the verbatim
    # binding above governs it from then on and this window self-retires.
    invented = sorted(k for k in norm_u if k not in raw_u and k != "trials_completed")
    if invented:
        errs.append(f"EVAL_NORMALIZED_RAW_USAGE_INVENTED: _usage keys {invented} do not exist in the "
                    f"sealed raw usage of RUN {run.get('id')}; the producer measures execution facts - "
                    "normalization copies them, it may not add new ones")
    return errs


def human_study_artifacts_digest(ctx: Ctx, metrics: dict) -> tuple[str, list[dict]]:
    """R7 external audit: the user's human-study approval must bind the RAW
    response bytes, not only the normalized summary that cites them. Returns
    (combined digest, per-cell rows) over every human_study cell's
    study_artifact content; a missing/unreadable file digests as ''."""
    rows: list[dict] = []
    for cell in econfig.evaluation_cells(ctx.cfg):
        if str(cell.get("source_kind") or "") != "human_study":
            continue
        row = metrics.get(str(cell.get("result_key") or ""))
        rel = str((row or {}).get("study_artifact") or "") if isinstance(row, dict) else ""
        digest = ""
        if rel:
            try:
                digest = hashlib.sha256(eutil.rpath(ctx.store.repo, rel).read_bytes()).hexdigest()
            except OSError:
                digest = ""
        rows.append({"cell": str(cell.get("id")), "artifact": rel, "digest": digest})
    combined = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":"),
                                         ensure_ascii=False).encode("utf-8")).hexdigest()
    return combined, rows


def human_study_cell_errors(ctx: Ctx, data: dict, *, where: str) -> list[str]:
    """E2: a source_kind=human_study cell's normalized value must cite the
    sealed raw-response artifact it was imported from; the engine hosts the
    import + seal, never the study execution."""
    errs: list[str] = []
    for cell in econfig.evaluation_cells(ctx.cfg):
        if str(cell.get("source_kind") or "") != "human_study":
            continue
        key = str(cell.get("result_key") or "")
        row = data.get(key)
        artifact = row.get("study_artifact") if isinstance(row, dict) else None
        rel = str(artifact or "")
        bad = (not rel or rel.startswith(("/", "\\")) or (len(rel) > 1 and rel[1] == ":")
               or ".." in rel.replace("\\", "/").split("/"))
        if bad or not eutil.rpath(ctx.store.repo, rel).is_file():
            errs.append(f"EVAL_HUMAN_STUDY_ARTIFACT: {where}: cell {cell.get('id')} is a human_study "
                        f"cell; metrics['{key}'] must be an object carrying study_artifact = the "
                        "repo-relative sealed raw-response file the user supplied (the frozen "
                        "study_protocol names it). If the user has not delivered the file yet, "
                        "ASK them to place it at the protocol-named path - waiting for user-owned "
                        "raw data is a legitimate pause here; do not fabricate responses or resubmit "
                        "without the file")
        elif eutil.rpath(ctx.store.repo, rel).name.lower() not in str(cell.get("study_protocol") or "").lower():
            errs.append(f"EVAL_HUMAN_STUDY_PROTOCOL_BINDING: {where}: cell {cell.get('id')}: the frozen "
                        f"study_protocol does not name the supplied file '{eutil.rpath(ctx.store.repo, rel).name}' - "
                        "the protocol frozen at configure must identify its raw-response artifact")
    return errs


def evaluation_result_errors(ctx: Ctx, spec: dict, metrics_file: str | None, *, where: str,
                             metrics_data: Any = _STAGE_RESULT_UNREAD,
                             allow_probe_unavailable: bool = False,
                             probe_artifact_sources: dict[str, str] | None = None,
                             node: dict | None = None,
                             enforce_harness_trials: bool = True,
                             budget_band_floor: float | None = None) -> list[str]:
    """Validate evaluation resource use against its local approved cap.

    ``enforce_harness_trials=False`` is the doctor's historical-replay mode:
    the physical/interactive ``_usage.trials_completed`` duty landed on the
    raw side in R9 with no era gate, so replaying it against RUNs sealed
    BEFORE the duty existed produced a permanent, unfixable diagnostic (raw
    evidence is immutable). Fresh production paths keep the duty."""
    if not metrics_file or not _exists(ctx, metrics_file):
        return [f"EVAL_RESULT_METRICS: {where}: evaluation needs an existing metrics_file"]
    data = eutil.read_json(eutil.rpath(ctx.store.repo, metrics_file), None) \
        if metrics_data is _STAGE_RESULT_UNREAD else metrics_data
    if not isinstance(data, dict):
        return [f"EVAL_RESULT_SHAPE: {where}: metrics_file must contain a JSON object"]
    errs: list[str] = []
    rep = spec.get("training_replication") if isinstance(spec.get("training_replication"), dict) else None
    for key in econfig.result_spec(ctx.cfg):
        errs.extend(metric_evidence_errors(ctx, key, data.get(key), rep, node=node))
    errs.extend(probe_result_errors(ctx, spec, data, where=where,
                                    allow_unavailable=allow_probe_unavailable,
                                    artifact_sources=probe_artifact_sources))
    limits = econfig.eval_budget(spec)
    usage = data.get("_usage")
    if not isinstance(usage, dict):
        errs.append(f"EVAL_RESULT_USAGE: {where}: metrics JSON needs _usage for every eval budget unit")
        return errs
    band = max(econfig.budget_tolerance(ctx.cfg), float(budget_band_floor or 1.0))
    for unit, limit in limits.items():
        actual = usage.get(unit)
        if isinstance(actual, bool) or not isinstance(actual, (int, float)) or \
                not math.isfinite(float(actual)) or float(actual) < 0:
            errs.append(f"EVAL_RESULT_USAGE_VALUE: {where}: _usage.{unit} must be finite and >= 0")
        elif float(actual) > float(limit) * band + 1e-12:
            # v12: same validity band as the stage side (econfig.budget_tolerance).
            errs.append(f"EVAL_RESULT_BUDGET_EXCEEDED: {where}: _usage.{unit}={actual} exceeds declared cap "
                        + (f"{limit} * stage_budget_tolerance {band} = {float(limit) * band:g}" if band > 1.0
                           else f"{limit} (strict)")
                        + "; the RUN's execution stands and its evidence waits: if the overage is "
                          "acceptable, raise the config key stage_budget_tolerance (>= actual/cap) and "
                          "'evo run-reconcile --run <this RUN>' re-ingests THIS evidence - no rerun")
    # R9 (external audit r6): trial completion is an EXECUTION fact of a
    # physical/interactive harness, so the PRODUCER must report it - this check
    # used to live only on the normalized side, which (with the raw-binding
    # gap) let an analyst invent the number. Enforced on both sides here so the
    # raw run carries it and normalization can only copy it.
    harness = (spec.get("eval") or {}).get("harness")
    if enforce_harness_trials and isinstance(harness, dict) \
            and harness.get("type") in ("physical", "interactive"):
        preregistered = harness.get("trials")
        completed = usage.get("trials_completed")
        if isinstance(completed, bool) or not isinstance(completed, int) or completed < 1 \
                or (isinstance(preregistered, int) and completed > preregistered):
            errs.append(f"EVAL_HARNESS_TRIALS: {where}: a physical/interactive harness must report "
                        "_usage.trials_completed as an integer >= 1 and <= the preregistered "
                        f"eval.harness.trials ({preregistered})")
    return errs


def resource_measurement_errors(spec: dict, data: dict, *, where: str) -> list[str]:
    """Validate raw, pre-analysis resource measurements from the eval runner.

    These values are accepted only on a registered eval RUN and are ingested
    into its evidence seal before an analyst can normalize results.  The
    evaluator supplies intervals; the sealed NODE_SPEC supplies the method.
    """
    errs: list[str] = []
    if "_effect_resources" in data:
        errs.append(f"EVAL_RAW_EFFECT_RESOURCES_FORBIDDEN: {where}: the raw evaluator emits "
                    "_resource_measurements; only the engine may create _effect_resources")
    rows = data.get("_resource_measurements")
    if not isinstance(rows, dict):
        return errs + [f"EVAL_RESOURCE_MEASUREMENTS: {where}: raw eval metrics need "
                       "_resource_measurements for every configured resource axis"]
    accounting = ((spec.get("eval") or {}).get("resource_accounting") or {})
    # The frozen spec accounting is the axis registry for this node (core
    # nine + any configured extension axes at freeze time).
    expected_axes = [axis for axis in accounting] or list(eprogram.RESOURCE_AXES)
    missing = [axis for axis in expected_axes if axis not in rows]
    extra = [axis for axis in rows if axis not in expected_axes]
    if missing or extra:
        errs.append(f"EVAL_RESOURCE_MEASUREMENT_AXES: {where}: use exactly {expected_axes}; "
                    f"missing={missing}, extra={extra}")
    for axis in expected_axes:
        row = rows.get(axis)
        if not isinstance(row, dict) or set(row) != {"lower", "upper"}:
            errs.append(f"EVAL_RESOURCE_MEASUREMENT_ROW: {where}: _resource_measurements.{axis} "
                        "must use exactly lower, upper")
            continue
        lower, upper = row.get("lower"), row.get("upper")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
               not math.isfinite(float(v)) or float(v) < 0 for v in (lower, upper)) or \
                (isinstance(lower, (int, float)) and isinstance(upper, (int, float)) and
                 float(lower) > float(upper)):
            errs.append(f"EVAL_RESOURCE_MEASUREMENT_INTERVAL: {where}: {axis} needs finite "
                        "0 <= lower <= upper")
        if axis not in accounting:
            errs.append(f"EVAL_RESOURCE_MEASUREMENT_UNPLANNED: {where}: {axis} has no frozen "
                        "resource_accounting method in NODE_SPEC")
    return errs


def v_eval_launch(ctx: Ctx, task: dict) -> list[str]:
    """Unified evaluation execution: quick and background evals are both RUNs.

    This separates sealed producer evidence from later analyst normalization.
    """
    errs: list[str] = []
    data = _read_json(ctx, task["outputs"][0], errs)
    if data is None:
        return errs
    expected_run = str(task["subject"].get("run") or "")
    run = ctx.store.get_run(ctx.st, expected_run) or {}
    if not expected_run or str(data.get("run") or "") != expected_run:
        errs.append(f"EVAL_LAUNCH_RUN: EVAL_LAUNCH.json run must equal the prepared attempt {expected_run!r}")
    if not run or str(data.get("attempt_token") or "") != str(run.get("attempt_token") or ""):
        errs.append("EVAL_LAUNCH_ATTEMPT_TOKEN: EVAL_LAUNCH.json must carry the exact prepared RUN attempt_token")
    if data.get("mode") not in ("background", "completed"):
        errs.append("EVAL_LAUNCH_MODE: EVAL_LAUNCH.json mode must be 'background' or 'completed'")
    if data.get("mode") == "background" and not str(data.get("job") or "").strip():
        errs.append("EVAL_LAUNCH_JOB: background evals must record a 'job' identifier (how to check status)")
    # v11.7: same rehearsal enforcement as stage launches (belt - a staged
    # node reaches eval only through its stages, but an evaluation authorized
    # on an unproven chain would still be real spend on unproven wiring).
    _eval_node = egraph.by_id(ctx.g).get(str(task["subject"].get("node") or "")) or {}
    _eval_spec = eutil.read_json(eutil.rpath(ctx.store.repo, _eval_node.get("spec") or ""), {}) or {}
    if not (bool(task["subject"].get("repeat_measure")) or run.get("repeat_measure_attempt")) \
            and erehearsal.required(ctx.cfg, _eval_node, _eval_spec):
        errs.extend(erehearsal.record_errors(ctx.store, _eval_node))
    if ctx.st.get("infra_revision_pending"):
        errs.append("INFRA_REVISION_UNPROVEN: a facts revision was adopted but its fresh canary "
                    "proof is still owed - new evaluation spend waits for it (run 'evo next'; the "
                    "engine presents the canary task)")
    if run and run.get("job") and str(data.get("job") or "").strip() \
            and str(data.get("job")) != str(run.get("job")):
        errs.append(f"EVAL_LAUNCH_JOB_MISMATCH: prepared RUN {expected_run} is already bound to job {run.get('job')!r}")
    errs.extend(_terminal_launch_immutable_errors(ctx, run, data))
    if data.get("mode") == "completed":
        mf = data.get("metrics_file")
        if not mf or not _exists(ctx, mf):
            errs.append("EVAL_LAUNCH_METRICS: completed evals must point at an existing metrics_file "
                        "(paths resolve from the REPOSITORY ROOT, not the evaluator's working directory)")
        elif task["subject"].get("repeat_measure") and run \
                and str(run.get("declared_metrics_file") or "") \
                and eutil.norm_uri(str(mf)) != eutil.norm_uri(str(run.get("declared_metrics_file"))):
            # R9-002: same landing-identity rule absorption enforces - reject
            # at the launch instead of accept-then-wedge on evidence_pending
            errs.append(f"EVAL_LAUNCH_REPEAT_LANDING: the repeat evaluation must land at the "
                        f"evaluation's own declared landing {run.get('declared_metrics_file')!r}, "
                        f"got {mf!r}")
        else:
            node = egraph.by_id(ctx.g).get(str(task["subject"].get("node") or "")) or {}
            spec = eutil.read_json(eutil.rpath(ctx.store.repo, node.get("spec") or ""), {}) or {}
            errs.extend(evaluation_result_errors(
                ctx, spec, str(mf), where="completed evaluation",
                # R6 blind-operator audit: this used to pass True, so the
                # launch ACCEPTED an envelope-less file and synchronous
                # absorption immediately wedged the same RUN on
                # evidence=incomplete - accept-then-wedge. A completed launch
                # now faces the same probe duty its own absorption enforces;
                # the waiver stays exactly where it belongs (signed gap).
                # R9-002: the repeat buy-back lane carries no probe duty at
                # all (mechanism authority stays with the sealed base head) -
                # its absorption waives the envelope, so the launch must too.
                allow_probe_unavailable=(bool(task["subject"].get("repeat_measure"))
                                         or active_probe_unavailable(ctx, node))))
            raw = eutil.read_json(eutil.rpath(ctx.store.repo, str(mf)), {}) or {}
            errs.extend(resource_measurement_errors(spec, raw, where="completed evaluation"))
    return errs


def effect_resource_source_paths(metrics: dict, normalized_metrics_path: str) -> list[str]:
    """Unique non-circular resource receipts referenced by normalized metrics."""
    resources = metrics.get("_effect_resources") if isinstance(metrics, dict) else None
    if not isinstance(resources, dict):
        return []
    out: list[str] = []
    for row in resources.values():
        source = str((row or {}).get("source") or "") if isinstance(row, dict) else ""
        if source and source != normalized_metrics_path and source not in out:
            out.append(source)
    return out


def mechanism_probe_source_paths(metrics: dict,
                                 artifact_sources: dict[str, str] | None = None) -> list[str]:
    block = metrics.get("_mechanism_probe") if isinstance(metrics, dict) else None
    out: list[str] = []
    for row in ((block or {}).get("observations") or []) if isinstance(block, dict) else []:
        declared = str((row or {}).get("artifact") or "") if isinstance(row, dict) else ""
        artifact = (artifact_sources or {}).get(declared, declared)
        if artifact and artifact not in out:
            out.append(artifact)
    return out


def resource_receipt_errors(ctx: Ctx, node: dict) -> list[str]:
    """Validate the engine-produced receipt against sealed raw RUN evidence."""
    errs: list[str] = []
    source = str(node.get("resource_receipt_path") or "")
    receipt = eutil.read_json(eutil.rpath(ctx.store.repo, source), None) if source and _exists(ctx, source) else None
    if not isinstance(receipt, dict):
        return ["EVAL_RESOURCE_RECEIPT_MISSING: engine-generated resource receipt is absent"]
    run = ctx.store.get_run(ctx.st, str(node.get("eval_run") or "")) or {}
    spec = eutil.read_json(eutil.rpath(ctx.store.repo, node.get("spec") or ""), {}) or {}
    expected_bindings = {
        "producer": "engine_scheduler", "node": node.get("id"), "eval_run": run.get("id"),
        "spec_seal_digest": str((node.get("spec_seal") or {}).get("digest") or ""),
        "implementation_seal_digest": str((node.get("implementation_seal") or {}).get("digest") or ""),
        "workflow_reuse_seal_digest": str((node.get("workflow_reuse_seal") or {}).get("digest") or ""),
        "run_evidence_digest": str((run.get("evidence_seal") or {}).get("digest") or ""),
    }
    for field, expected in expected_bindings.items():
        if receipt.get(field) != expected:
            errs.append(f"EVAL_RESOURCE_RECEIPT_BINDING: {field} must bind {expected!r}")
    accounting = ((spec.get("eval") or {}).get("resource_accounting") or {})
    if receipt.get("accounting") != accounting:
        errs.append("EVAL_RESOURCE_RECEIPT_ACCOUNTING: receipt must copy the sealed NODE_SPEC accounting methods")
    raw = eutil.read_json(eutil.rpath(ctx.store.repo, str(run.get("metrics_file") or "")), {}) or {}
    measured = raw.get("_resource_measurements") if isinstance(raw, dict) else None
    resources = receipt.get("resources")
    if not isinstance(resources, dict) or not isinstance(measured, dict):
        return errs + ["EVAL_RESOURCE_RECEIPT_SHAPE: receipt and ingested eval evidence need resource maps"]
    for axis in econfig.resource_axes(ctx.cfg):
        row, raw_row = resources.get(axis), measured.get(axis)
        if not isinstance(row, dict) or set(row) != {"lower", "upper"}:
            errs.append(f"EVAL_RESOURCE_RECEIPT_AXIS: resources.{axis} must use exactly lower, upper")
        elif row != raw_row:
            errs.append(f"EVAL_RESOURCE_RECEIPT_MISMATCH: resources.{axis} must exactly copy sealed eval RUN evidence")
    return errs


def effect_resources_from_receipt(ctx: Ctx, node: dict) -> dict:
    """Return the only resource vector legal in normalized metrics."""
    source = str(node.get("resource_receipt_path") or "")
    receipt = eutil.read_json(eutil.rpath(ctx.store.repo, source), {}) or {}
    return {axis: {**dict((receipt.get("resources") or {}).get(axis) or {}), "source": source}
            for axis in econfig.resource_axes(ctx.cfg)}


def _effect_resource_receipt_errors(ctx: Ctx, node: dict, resources: dict) -> list[str]:
    errs = resource_receipt_errors(ctx, node)
    expected = effect_resources_from_receipt(ctx, node)
    if resources != expected:
        errs.append("EVAL_EFFECT_RESOURCES_ENGINE_MISMATCH: normalized resource vector must be injected from "
                    "the active engine receipt without analyst edits")
    return errs


def v_evaluate(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    nid = task["subject"]["node"]
    node = egraph.by_id(ctx.g).get(nid) or {}
    metrics = _read_json(ctx, task["outputs"][0], errs)
    report = _read_md(ctx, task["outputs"][1], errs)
    if metrics is None or report is None:
        return errs
    if node.get("role") != "platform":
        spec = eutil.read_json(eutil.rpath(ctx.store.repo, node.get("spec") or ""), {}) or {}
        probe_unavailable = active_probe_unavailable(ctx, node)
        probe_sources = active_probe_snapshot_map(ctx, node)
        eval_run_row = next((r for r in ctx.st.get("runs", [])
                             if str(r.get("id") or "") == str(node.get("eval_run") or "")), None)
        errs.extend(evaluation_result_errors(
            ctx, spec, task["outputs"][0], where=f"node {nid} normalized evaluation",
            metrics_data=metrics, allow_probe_unavailable=probe_unavailable,
            probe_artifact_sources=probe_sources, node=node,
            # the normalized _usage copies the sealed raw run's numbers; honor
            # the band that sealed them (v12 era-gating)
            budget_band_floor=budget_band_floor_of(eval_run_row)))
        errs.extend(normalized_raw_binding_errors(ctx, node, metrics))
        errs.extend(human_study_cell_errors(ctx, metrics, where=f"node {node['id']} evaluation"))
        # (the physical/interactive trials duty now lives in
        # evaluation_result_errors so the RAW producer carries it too - R9)
        if "_resource_measurements" in metrics:
            errs.append("EVAL_EFFECT_RESOURCES_ENGINE_OWNED: analyst metrics must omit "
                        "_resource_measurements; raw measurements live in the sealed eval payload only")
        if "_effect_resources" in metrics \
                and metrics.get("_effect_resources") != effect_resources_from_receipt(ctx, node):
            # A byte-identical vector is this transition's own prior injection
            # replayed after a crash between the durable metrics write and the
            # state commit - blaming the analyst for it would poison the retry.
            errs.append("EVAL_EFFECT_RESOURCES_ENGINE_OWNED: analyst metrics must omit _effect_resources; "
                        "the engine injects its sealed receipt after validation")
        errs.extend(resource_receipt_errors(ctx, node))
    _require_sections(report, ["setup", "results", "comparability"], "EVAL_REPORT", errs)
    if any(c.get("role") in ("target", "guardrail") and c.get("goal_threshold") is not None
           for c in econfig.evaluation_cells(ctx.cfg)):
        results_text = eutil.find_section(eutil.md_sections(report), "results") or ""
        if "goal" not in results_text.lower():
            errs.append("EVAL_ABSOLUTE_GOALS: Results must report absolute goal met/not-met separately from relative status")
    if node.get("role") not in ("baseline", "platform"):
        comp = eutil.find_section(eutil.md_sections(report), "comparability") or ""
        cited = set(re.findall(r"\bV\d+\b", comp))
        _b_ids, v_ids, _f_ids = ctx.dossier_ids()
        # v10.1: bind the walk to REAL dossier invariants (any "V1" token used
        # to pass regardless of the dossier).  Projects whose dossier declares
        # no V# keep the old any-token duty.
        if v_ids and not (cited & v_ids):
            errs.append("EVAL_COMPARABILITY: the comparability section must check the dossier invariants "
                        f"by id - cite at least one of {sorted(v_ids)[:8]} from PROBLEM_DOSSIER.md")
        elif not v_ids and not cited:
            errs.append("EVAL_COMPARABILITY: the comparability section must check the dossier invariants by id (V#) - same split, same metric code, same protocol")
        # Final numbers alone hide where a multi-stage procedure worked or
        # failed. Analyze stage summaries, resource use and any adaptive trace.
        stm = stage_metrics_of(ctx, nid)
        ledgers = stage_ledgers_of(ctx, nid)
        if stm or ledgers:
            dyn = eutil.find_section(eutil.md_sections(report), "stage evidence") or ""
            if len(dyn.strip()) < 60:
                errs.append("EVAL_STAGE_EVIDENCE: a 'Stage evidence' section (>= 60 chars) is required - "
                            "analyze stage summaries, declared-vs-used budget and adaptive/component ledgers, "
                            "not only the final score")
            else:
                for sname in set(stm) | set(ledgers):
                    if sname not in dyn:
                        errs.append(f"EVAL_STAGE_EVIDENCE_STAGE: the stage-evidence section never discusses "
                                    f"stage '{sname}' - every executed stage gets a reading")
                vals: list = []
                for nums in stm.values():
                    vals.extend(nums.values())
                if vals and not any((f"{v:g}" in dyn or str(v) in dyn) for v in vals):
                    errs.append("EVAL_STAGE_EVIDENCE_NUMBERS: the stage-evidence section must echo >= 1 "
                                "recorded stage metric or usage value")
        # v9: anomaly mining. The eval is where phenomena surface; oral-tier work
        # is overwhelmingly phenomenon-first, so the reading is a duty even when
        # it is 'NONE - <what was checked>'.
        anom = eutil.find_section(eutil.md_sections(report), "anomalies") or ""
        if len(anom.strip()) < 40:
            errs.append("EVAL_ANOMALIES: an 'Anomalies' section (>= 40 chars) is required - surprising "
                        "observations in curves/slices/behaviors (candidate OB### ledger entries), or an "
                        "explicit 'NONE - <what was checked>'")
        meta_idea: dict = {}
        if node.get("idea_doc"):
            meta_idea = _idea_meta(ctx, node, errs)
        probe = meta_idea.get("mechanism_probe") or {}
        probe_execution = spec.get("probe_execution") if isinstance(spec.get("probe_execution"), dict) else None
        if probe.get("signal") and probe_execution and \
                not str(meta_idea.get("attribution_waiver") or "").strip():
            mc = eutil.find_section(eutil.md_sections(report), "mechanism check") or ""
            if len(mc.strip()) < 60:
                errs.append("EVAL_MECHANISM: this idea registered a mechanism probe; the report needs a "
                            "'Mechanism check' section (>= 60 chars) describing the measured signal or the "
                            "engine-recorded evidence unavailability; never invent missing observations")
            elif probe_unavailable:
                if not any(word in mc.lower() for word in ("unavailable", "missing", "not recorded", "not returned")):
                    errs.append("EVAL_MECHANISM_UNAVAILABLE_DISCLOSURE: Mechanism check must plainly disclose "
                                "that the registered probe evidence is unavailable")
            else:
                required = [str(x) for x in (probe_execution.get("required_fields") or [])]
                missing_fields = [field for field in required if field not in mc]
                if missing_fields:
                    errs.append(f"EVAL_MECHANISM_FIELDS: Mechanism check must name every registered JSON field; "
                                f"missing {missing_fields}")
                observations = ((metrics.get("_mechanism_probe") or {}).get("observations") or [])
                values = [value for row in observations if isinstance(row, dict)
                          for value in ((row.get("values") or {}).values())
                          if isinstance(value, (int, float)) and not isinstance(value, bool)]
                if values and not any(f"{value:g}" in mc or str(value) in mc for value in values):
                    errs.append("EVAL_MECHANISM_NUMBERS: Mechanism check must quote at least one recorded probe value")
        if meta_idea.get("scaling") and (meta_idea.get("scaling") or {}).get("execution") == "existing_artifact":
            scs = eutil.find_section(eutil.md_sections(report), "scaling probe") or ""
            if len(scs.strip()) < 60:
                errs.append("EVAL_SCALING: this idea pre-registered a scaling trend; the report needs a "
                            "'Scaling probe' section (>= 60 chars) with the per-point numbers")
    return errs


def _node_raw_metric(node: dict, metric: str) -> Any:
    return (node.get("score_evidence") or {}).get(metric, (node.get("scores") or {}).get(metric))


def _reference_node_for_metric(ctx: Ctx, node: dict, metric: str) -> dict | None:
    """Best model parent for this metric, else baseline.

    Multi-parent children compare each cell to the strongest inherited parent
    on that cell; a weak parent cannot make a hybrid look artificially good.
    """
    idx = egraph.by_id(ctx.g)
    parent_ids = [p for p in node.get("parents", [])
                  if p in idx and idx[p].get("role") != "platform"]
    if node.get("experiment_purpose") == "maintenance":
        # Anti-ratchet: settle a repair against the nearest NON-maintenance
        # ancestor, not the previous repair.  Per-step parity against the
        # immediate parent let a chain m1->m2->...->mk spend the whole
        # noninferiority margin at every link (k*margin of silent drift) while
        # each link reported parity=met.  Spending one shared budget against
        # the scientific base is what "preserve semantics" actually means.
        #
        # Deliberately NOT extended to a candidate whose parent is a repair:
        # that candidate ran ON the repaired base, so the repaired base is its
        # correct causal comparator.  Remapping it to the pre-repair ancestor
        # would credit the candidate with the repair's headroom - inflating a
        # scientific claim with plumbing work and rewarding exactly the
        # "smuggle the fix into the candidate" behaviour these purposes exist
        # to prevent.  The residue is bounded and single-hop: this same clause
        # holds every repair within one noninferiority margin of the true
        # base, so a candidate's bar is never more than one margin below it -
        # the tolerance any single noninferior comparison already carries.
        parent_ids = [egraph.effective_frontier_ancestor(idx, p) for p in parent_ids]
    parents = [idx[p] for p in parent_ids if p in idx]
    direction = econfig.result_direction(ctx.cfg, metric)
    have = [p for p in parents if metric_value(_node_raw_metric(p, metric)) is not None]
    if have:
        # Rank by the bound the comparison will actually consume: improvement
        # against this reference is `candidate_lower - reference_upper` for a
        # max metric, so "strongest parent" must mean "sets the hardest bar".
        # Ranking by the opposite bound could demote a parent precisely because
        # it quantified its uncertainty, and hand the candidate an easier
        # comparator than the lineage it really inherited from.
        def key(p: dict) -> float:
            _point, lower, upper = metric_interval(_node_raw_metric(p, metric))
            return float(upper if direction == "max" else lower)
        return max(have, key=key) if direction == "max" else min(have, key=key)
    return next((n for n in ctx.g.get("nodes", []) if n.get("role") == "baseline"), None)


def _reference_score(ctx: Ctx, node: dict) -> float | None:
    """Compatibility/display reference for project.primary_metric."""
    metric = econfig.primary_metric(ctx.cfg)
    ref = _reference_node_for_metric(ctx, node, metric)
    return metric_value(_node_raw_metric(ref or {}, metric))


def _settlement_floor(ctx: Ctx, node: dict, cell_id: str) -> float:
    """The noise floor a node's assessment settles with (R4 science audit).

    FROZEN at eval absorb (node.eval_floor_frozen, captured BEFORE the node's
    own seed spread calibrates observed noise) so that (a) another node's
    calibration landing between this node's evaluate and conclude can never
    make the frozen evaluation_summary fail its own byte-equality re-check
    (that was a permanent conclude livelock in preplanned mode), and (b) a
    measurement never moves its own ruler. Live floors remain only as the
    fallback for pre-freeze nodes."""
    frozen = (node or {}).get("eval_floor_frozen")
    if isinstance(frozen, dict) and cell_id in frozen:
        value = frozen.get(cell_id)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    return econfig.noise_floor(ctx.cfg, cell_id, ctx.st)


def _cell_result(ctx: Ctx, node: dict, metrics: dict, cell: dict) -> dict:
    result_key = str(cell.get("result_key") or "")
    metric = str(cell.get("metric") or "")
    direction = econfig.result_direction(ctx.cfg, result_key)
    new_raw = metrics.get(result_key)
    ref_node = _reference_node_for_metric(ctx, node, result_key)
    ref_raw = _node_raw_metric(ref_node or {}, result_key)
    new, new_lower, new_upper = metric_interval(new_raw)
    ref, _ref_lower, _ref_upper = metric_interval(ref_raw)
    out = {"cell": cell.get("id"), "metric": metric, "result_key": result_key,
           "reference_node": (ref_node or {}).get("id"),
           "new": new, "reference": ref, "delta": None, "lower": None, "upper": None,
           "status": "uncertain", "goal_threshold": cell.get("goal_threshold"),
           "goal_lower": None, "goal_upper": None,
           "goal_status": "not_applicable" if cell.get("goal_threshold") is None else "unknown"}
    floor = _settlement_floor(ctx, node, str(cell.get("id") or ""))
    if new is not None and isinstance(cell.get("goal_threshold"), (int, float)):
        threshold = float(cell["goal_threshold"])
        # Absolute attainment uses the same explicit fixed-evaluation interval
        # as node comparison and Pareto pruning - INCLUDING the noise floor
        # (v11 R1): a scalar sitting inside the noise band of the threshold
        # must settle 'unknown', not 'met'.
        _gp, gfl, gfu = econfig.result_interval_with_floor(new_raw, floor)
        goal_lower = float(gfl if gfl is not None else new_lower)
        goal_upper = float(gfu if gfu is not None else new_upper)
        if direction == "max":
            goal_status = "met" if goal_lower >= threshold else \
                ("not_met" if goal_upper < threshold else "unknown")
        else:
            goal_status = "met" if goal_upper <= threshold else \
                ("not_met" if goal_lower > threshold else "unknown")
        out.update({"goal_lower": goal_lower, "goal_upper": goal_upper,
                    "goal_status": goal_status})
    if new is None or ref is None:
        return out
    # v11: unreported scalars are compared with the field's noise floor folded
    # into the delta ONCE - hiding the error bar no longer buys a zero-width
    # interval; an honestly reported interval is used as reported.
    delta, lower, upper = econfig.improvement_interval(new_raw, ref_raw, direction, floor=floor)
    raw_delta, raw_lower, raw_upper = econfig.improvement_interval(
        new_raw, ref_raw, direction, floor=0.0)
    improve = float(cell.get("min_improvement") or 0.0)
    margin = float(cell.get("noninferiority_margin") or 0.0)
    # ONE application of the floor per settlement (v11 R2). WINS use the
    # floored lower bound: a scalar victory must clear the noise. The
    # noninferior/regressed split settles on the AS-REPORTED interval against
    # a margin that absorbs the floor ONLY when a side was scalar - flooring
    # both the interval and the margin created an unsettleable 'uncertain'
    # band (a frozen -0.001 delta could never reach parity), and raising the
    # margin for fully-reported pairs forgave PROVEN regressions their own
    # honest intervals had established.
    floor_active = floor > 0 and (lower, upper) != (raw_lower, raw_upper)
    margin_eff = max(margin, floor) if floor_active else margin
    materially_improved = lower > 0.0 if improve == 0.0 else lower >= improve
    if materially_improved:
        status = "improved"
    elif raw_lower >= -margin_eff:
        status = "noninferior"
    elif raw_upper < -margin_eff:
        status = "regressed"
    else:
        status = "uncertain"
    out.update({"delta": raw_delta, "lower": lower, "upper": upper, "status": status})
    return out


def _idea_meta(ctx: Ctx, node: dict, errs: list[str] | None = None) -> dict:
    """Engine-side callers tolerate a missing meta (validated upstream);
    validators MUST pass their errs list so a corrupt/missing idea meta
    blocks the task instead of silently degrading every contract."""
    if not node.get("idea_doc"):
        return {}
    sink: list[str] = [] if errs is None else errs
    return _read_json(ctx, str(node["idea_doc"]).replace(".md", ".meta.json"), sink) or {}


def effect_contract_assessment(ctx: Ctx, node: dict, metrics: dict,
                               meta: dict | None = None) -> dict:
    """Settle the frozen E claim against its exact comparator and resources.

    The ordinary performance verdict may still compare a hybrid to its
    strongest inherited parent.  This independent audit answers the different
    scientific question that was frozen before selection: did the declared
    KC# -> Z# -> C# effect clear its own worthwhile floor without buying the
    result with a larger realized resource vector?
    """
    meta = meta if isinstance(meta, dict) else _idea_meta(ctx, node)
    effect = meta.get("effect_case") if isinstance(meta, dict) else None
    if not isinstance(effect, dict) or node.get("role") in ("baseline", "platform") \
            or node.get("experiment_purpose") == "targeted_ablation":
        return {"status": "not_applicable", "comparator_id": None, "evidence_gaps": [],
                "targets": {}, "guardrails": {}, "resources": {"status": "not_applicable"}}

    comparator_id = str(effect.get("comparator_id") or "")
    comparator = _effect_comparator_node(ctx, meta, node)
    if comparator is None:
        return {"status": "invalid", "comparator_id": comparator_id,
                "reason": "declared comparator does not resolve to a model node",
                "evidence_gaps": [], "targets": {}, "guardrails": {},
                "resources": {"status": "invalid"}}

    cells = econfig.cell_spec(ctx.cfg)
    grouped: dict[str, list[dict]] = {}
    for row in effect.get("chain") or []:
        if isinstance(row, dict):
            grouped.setdefault(str(row.get("target_cell") or ""), []).append(row)
    target_rows: dict[str, dict] = {}
    target_states: list[str] = []
    for cid, links in grouped.items():
        cell = cells.get(cid) or {}
        result_key = str(cell.get("result_key") or "")
        directions = {str(link.get("direction") or "") for link in links}
        if not result_key or len(directions) != 1:
            target_rows[cid] = {"status": "invalid", "reason": "missing cell or mixed directions"}
            target_states.append("invalid")
            continue
        direction_tag = next(iter(directions))
        new_raw = metrics.get(result_key)
        ref_raw = _node_raw_metric(comparator, result_key)
        new, new_lower, new_upper = metric_interval(new_raw)
        ref, ref_lower, ref_upper = metric_interval(ref_raw)
        if new is None or ref is None:
            target_rows[cid] = {"status": "uncertain", "result_key": result_key,
                                "reason": "candidate or comparator evidence missing"}
            target_states.append("uncertain")
            continue
        declared_min = max(float(link.get("minimum_worthwhile_delta") or 0.0) for link in links)
        project_min = float(cell.get("min_improvement") or 0.0)
        threshold = max(declared_min, project_min)
        # R4 science audit: the frozen E claim was the ONLY decision line in
        # the system that ignored the noise floor - a hidden error bar bought
        # decisive 'met'/'failed' settlements inside the noise band, and this
        # line seeds the inheritance frontier. Same one-application rule as
        # everywhere else, with the node's FROZEN floor.
        e_floor = _settlement_floor(ctx, node, cid)
        if direction_tag == "stabilize":
            # For stabilization, minimum_worthwhile_delta is the precommitted
            # equivalence radius epsilon: the whole difference interval must
            # lie inside [-epsilon, +epsilon]. A scalar pair no longer gets a
            # free zero-width interval (floor folded once, as reported when
            # honestly reported).
            _sd, s_lower, s_upper = econfig.improvement_interval(new_raw, ref_raw, "max", floor=e_floor)
            epsilon = min(float(link.get("minimum_worthwhile_delta") or 0.0) for link in links)
            status = "met" if s_lower >= -epsilon and s_upper <= epsilon else \
                ("failed" if s_upper < -epsilon or s_lower > epsilon else "uncertain")
            lower, upper, threshold = s_lower, s_upper, epsilon
        else:
            configured = "increase" if econfig.result_direction(ctx.cfg, result_key) == "max" else "decrease"
            if direction_tag != configured:
                status, lower, upper = "invalid", None, None
            else:
                _delta, lower, upper = econfig.improvement_interval(
                    new_raw, ref_raw, econfig.result_direction(ctx.cfg, result_key), floor=e_floor)
                status = ("uncertain" if lower is None or upper is None else
                          "met" if float(lower) >= threshold else
                          "failed" if float(upper) < threshold else "uncertain")
        expected_low = max(float(link.get("expected_delta_interval", [0, 0])[0]) for link in links)
        expected_high = min(float(link.get("expected_delta_interval", [0, 0])[1]) for link in links)
        forecast = ("invalid" if expected_low > expected_high or lower is None or upper is None else
                    "below" if float(upper) < expected_low else
                    "above" if float(lower) > expected_high else "overlap")
        target_rows[cid] = {
            "status": status, "result_key": result_key, "direction": direction_tag,
            "candidate": new, "comparator": ref, "lower": lower, "upper": upper,
            "minimum_worthwhile_delta": threshold, "forecast_calibration": forecast,
            # Preserve the exact pre-registered interval used to settle the
            # derived calibration label for later scientific audit.
            "expected_lower": expected_low, "expected_upper": expected_high,
        }
        target_states.append(status)

    scope = meta.get("claim_scope") or {}
    guard_ids = list(dict.fromkeys(
        [str(c.get("id")) for c in econfig.guardrail_cells(ctx.cfg)] +
        [str(x) for x in (scope.get("guardrail_cells") or [])]))
    guard_rows: dict[str, dict] = {}
    guard_states: list[str] = []
    for cid in guard_ids:
        cell = cells.get(cid) or {}
        result_key = str(cell.get("result_key") or "")
        new_raw, ref_raw = metrics.get(result_key), _node_raw_metric(comparator, result_key)
        p_floor = _settlement_floor(ctx, node, str(cid))
        # Parity is a noninferiority settlement: settle on the AS-REPORTED
        # interval with the floor folded into the margin exactly once, and
        # only when a side was scalar (see _cell_result's one-application
        # note - flooring both sides froze every within-noise deficit at
        # 'uncertain' forever, and raising the margin for fully-reported
        # pairs forgave regressions their own intervals had proven).
        p_dir = econfig.result_direction(ctx.cfg, result_key)
        _fd, f_lower, f_upper = econfig.improvement_interval(new_raw, ref_raw, p_dir, floor=p_floor)
        _delta, lower, upper = econfig.improvement_interval(new_raw, ref_raw, p_dir, floor=0.0)
        p_active = p_floor > 0 and (f_lower, f_upper) != (lower, upper)
        margin = max(float(cell.get("noninferiority_margin") or 0.0), p_floor) if p_active \
            else float(cell.get("noninferiority_margin") or 0.0)
        status = ("uncertain" if lower is None or upper is None else
                  "met" if float(lower) >= -margin else
                  "failed" if float(upper) < -margin else "uncertain")
        guard_rows[cid] = {"status": status, "result_key": result_key,
                           "lower": lower, "upper": upper, "noninferiority_margin": margin}
        guard_states.append(status)

    planned = (effect.get("resources") or {})
    regime = str(planned.get("regime") or "")
    fixed_axes = set(str(x) for x in (planned.get("fixed_axes") or []))
    tradeoff_axes = set(str(x) for x in (planned.get("tradeoff_axes") or []))
    improvement_axes = set(str(x) for x in (planned.get("improvement_axes") or []))
    actual = metrics.get("_effect_resources") if isinstance(metrics.get("_effect_resources"), dict) else {}
    ref_actual = comparator.get("effect_resources_realized") \
        if isinstance(comparator.get("effect_resources_realized"), dict) else {}
    axis_rows: dict[str, dict] = {}
    resource_states: list[str] = []
    for axis in econfig.resource_axes(ctx.cfg):
        cand_row = actual.get(axis) if isinstance(actual.get(axis), dict) else {}
        ref_row = ref_actual.get(axis) if isinstance(ref_actual.get(axis), dict) else {}
        cand_lower, cand_upper = cand_row.get("lower"), cand_row.get("upper")
        ref_lower, ref_upper = ref_row.get("lower"), ref_row.get("upper")
        cand_cap = (planned.get("candidate") or {}).get(axis)
        ref_plan = (planned.get("comparator") or {}).get(axis)
        measured = all(not isinstance(v, bool) and isinstance(v, (int, float))
                       for v in (cand_lower, cand_upper, ref_lower, ref_upper))
        cap_declared = not isinstance(cand_cap, bool) and isinstance(cand_cap, (int, float))
        relation = ("better" if measured and float(cand_upper) < float(ref_lower) else
                    "worse" if measured and float(cand_lower) > float(ref_upper) else
                    "overlap" if measured else "unknown")
        # Whether the pre-run estimate of the INCUMBENT's cost turned out right
        # is calibration evidence about forecasting, not evidence about this
        # candidate's claim: the candidate does not control the comparator's
        # realized cost, and the estimate is already bound to that node's sealed
        # receipt at advance time (TOURNAMENT_COMPARATOR_RESOURCE_BINDING).
        # Letting it veto here failed candidates that were an order of magnitude
        # cheaper than the incumbent they were being compared with.
        comparator_forecast = ("not_declared" if ref_plan == "unknown" or ref_plan is None else
                               "confirmed" if _interval_contains(ref_plan, ref_lower, ref_upper) else
                               "missed")
        reason = ""
        if not cap_declared:
            status = "uncertain"
            reason = "candidate cap for this axis was never frozen as a number"
        elif not measured:
            status = "uncertain"
            reason = ("candidate receipt missing this axis" if not all(
                          not isinstance(v, bool) and isinstance(v, (int, float))
                          for v in (cand_lower, cand_upper))
                      else f"comparator {comparator.get('id')} has no priced interval on this axis")
        else:
            cap_ok = float(cand_upper) <= float(cand_cap)
            if axis in fixed_axes:
                # "Matched" means the result was not bought with more of this
                # resource - not that the candidate must be provably cheaper.
                # Demanding cand_upper <= ref_lower failed a genuinely
                # equal-cost axis whenever the two intervals merely overlapped,
                # which is the normal case for a matched design.
                relative_ok = relation != "worse"
            elif axis in improvement_axes:
                relative_ok = relation == "better"
            elif axis in tradeoff_axes:
                relative_ok = True
            else:
                relative_ok = False
            status = "met" if cap_ok and relative_ok else "failed"
            if status == "failed":
                reason = ("realized cost exceeds the frozen candidate cap" if not cap_ok
                          else f"{relation} against the comparator under a "
                               f"{'fixed' if axis in fixed_axes else 'improvement' if axis in improvement_axes else 'undeclared'} axis policy")
        axis_rows[axis] = {"status": status, "policy": (
                               "fixed" if axis in fixed_axes else
                               "tradeoff" if axis in tradeoff_axes else
                               "improvement" if axis in improvement_axes else "undeclared"),
                           "relation": relation, "candidate_lower": cand_lower,
                           "candidate_upper": cand_upper, "candidate_cap": cand_cap,
                           "comparator_lower": ref_lower, "comparator_upper": ref_upper,
                           "comparator_plan": ref_plan,
                           "comparator_forecast": comparator_forecast,
                           "candidate_source": cand_row.get("source"),
                           "comparator_source": ref_row.get("source"),
                           **({"reason": reason} if reason else {})}
        resource_states.append(status)
    policy_valid = (regime in eprogram.RESOURCE_REGIMES and
                    fixed_axes | tradeoff_axes | improvement_axes == set(econfig.resource_axes(ctx.cfg)) and
                    not (fixed_axes & tradeoff_axes or fixed_axes & improvement_axes or
                         tradeoff_axes & improvement_axes))
    resource_status = ("invalid" if not policy_valid else
                       "failed" if "failed" in resource_states else
                       "uncertain" if "uncertain" in resource_states else "met")

    states = target_states + guard_states + [resource_status]
    status = ("invalid" if "invalid" in states else "failed" if "failed" in states else
              "uncertain" if "uncertain" in states or not target_states else "met")
    # Name every undecided row.  "Uncertain" without its cause is unactionable,
    # and an unactionable block is indistinguishable from a refutation.
    gaps: list[str] = []
    for cid, row in target_rows.items():
        if row.get("status") == "uncertain":
            gaps.append(f"target {cid} ({row.get('result_key') or '?'}): " + str(
                row.get("reason") or "improvement interval straddles the registered worthwhile delta"))
    for cid, row in guard_rows.items():
        if row.get("status") == "uncertain":
            gaps.append(f"guardrail {cid} ({row.get('result_key') or '?'}): "
                        "non-inferiority interval straddles the declared margin")
    for axis, row in axis_rows.items():
        if row.get("status") == "uncertain":
            gaps.append(f"resource {axis}: {row.get('reason') or 'undecidable'}")
    if not target_states:
        gaps.append("no declared effect target resolved to a decision cell")
    mis_forecast = sorted(axis for axis, row in axis_rows.items()
                          if row.get("comparator_forecast") == "missed")
    return {"status": status, "comparator_id": comparator_id,
            "comparator_node": comparator.get("id"), "targets": target_rows,
            "guardrails": guard_rows, "evidence_gaps": gaps,
            "resources": {"status": resource_status, "regime": regime, "axes": axis_rows,
                          "comparator_forecast_missed": mis_forecast}}


PROMOTION_STATUSES = ["met", "pending_evidence", "blocked", "not_applicable"]


def promotion_status(verdict: str, effect_contract: dict, mechanism_contract: dict, *,
                     research_kernel: bool, fidelity_settled: bool) -> str:
    """May this node's frozen scientific claim seed the inheritance frontier?

    A claim decided against and a claim not yet decidable are different states
    with different remedies: the first needs a new idea, the second needs one
    more measurement.  Collapsing both into `blocked` made a fixable evidence
    gap - an unpriced comparator axis, an unclear probe, an outstanding
    fidelity audit - look exactly like a refuted lineage, so nobody ever went
    back to close it.  `pending_evidence` says the claim is still alive.
    """
    contract_status = effect_contract.get("status")
    mechanism = mechanism_contract.get("status")
    licensed = (mechanism == "confirmed" if research_kernel
                else mechanism in ("confirmed", "not_applicable"))
    if verdict in ("improved", "specialist", "dominant") and contract_status == "met" \
            and licensed and fidelity_settled:
        return "met"
    if contract_status == "not_applicable":
        return "not_applicable"
    # `promising` is a paradigm root landing AT parity with nothing regressed -
    # strictly stronger evidence than the `inconclusive` that would otherwise
    # report `pending_evidence`.  Calling it "decided against" inverted the
    # order of the two outcomes.  `tradeoff` stays: there, a cell really did
    # regress, and that is a decision.
    decided_against = (contract_status in ("failed", "invalid")
                       or mechanism in ("refuted", "unverified")
                       or verdict in ("regressed", "tradeoff", "screened_out", "failed"))
    return "blocked" if decided_against else "pending_evidence"


def computed_assessment(ctx: Ctx, node: dict, metrics: dict) -> dict:
    """Compute a claim-scoped, multi-cell verdict and its full audit trail."""
    cells = econfig.evaluation_cells(ctx.cfg)
    results = {str(c.get("id")): _cell_result(ctx, node, metrics, c) for c in cells}
    meta = _idea_meta(ctx, node)
    effect_contract = effect_contract_assessment(ctx, node, metrics, meta)
    research_kernel = str((meta.get("novelty") or {}).get("kind") or "") in eprogram.RESEARCH_NOVELTY
    waiver = str(meta.get("attribution_waiver") or "").strip()
    mechanism_contract = ({"status": "unverified", "reason": waiver}
                          if research_kernel and waiver else
                          mechanism_probe_assessment(meta.get("mechanism_probe"), metrics))
    # Ablations and probes are diagnostics: they observe an evaluation_scope
    # instead of claiming a scope.  Maintenance keeps the default generalist
    # coverage - its parity settlement must watch every decision cell.
    is_ablation = node.get("experiment_purpose") in ("targeted_ablation", "diagnostic_probe")
    scope = (meta.get("evaluation_scope") if is_ablation else meta.get("claim_scope")) or {}
    kind = "diagnostic" if is_ablation else str(scope.get("kind") or "generalist")
    default_targets = [str(c.get("id")) for c in econfig.target_cells(ctx.cfg)]
    target_ids = [str(x) for x in (scope.get("target_cells") or default_targets)]
    efficiency_improvement_ids = [str(x) for x in (scope.get("improvement_cells") or [])]
    efficiency_parity_ids = [str(x) for x in (scope.get("parity_cells") or [])]
    global_guard = [str(c.get("id")) for c in econfig.guardrail_cells(ctx.cfg)]
    guard_ids = list(dict.fromkeys(global_guard + [str(x) for x in (scope.get("guardrail_cells") or [])]))
    all_target_ids = set(default_targets)
    breadth_ids = sorted(all_target_ids - set(target_ids))

    ev = econfig.evaluation_contract(ctx.cfg)
    cells_by_id = econfig.cell_spec(ctx.cfg)
    task_specs = {str(t.get("id")): t for t in ev.get("tasks") or []}

    def aggregate(statuses: list[str], mode: str, weights: list[float]) -> bool:
        wins = sum(1 for s in statuses if s == "improved")
        if mode == "all":
            return bool(statuses) and wins == len(statuses)
        if mode == "majority":
            return wins > len(statuses) / 2
        win_w = sum(w for s, w in zip(statuses, weights) if s == "improved")
        loss_w = sum(w for s, w in zip(statuses, weights) if s == "regressed")
        return wins > 0 and win_w > loss_w

    def lost(statuses: list[str], mode: str, weights: list[float]) -> bool:
        """The declared aggregation read in the losing direction.

        A contract saying "this counts as a win only when every cell improves"
        cannot also mean "it counts as a loss the moment any one cell slips":
        that reading silently turns every declared aggregation into `all` for
        wins and `any` for losses, and overrides a cell's own `required: false`.
        One declared rule, both directions; what is neither won nor lost is the
        mixed outcome the tradeoff/specialist verdicts exist to name.
        """
        flip = {"improved": "regressed", "regressed": "improved"}
        return aggregate([flip.get(s, s) for s in statuses], mode, weights)

    # Aggregate cells inside each scientific task first. Without this layer, a
    # task reported with five metrics would receive five votes against a task
    # reported with one metric merely because it had a denser table.
    tasks_out: dict[str, dict] = {}
    for tid, task in task_specs.items():
        ids = [cid for cid in target_ids if (cells_by_id.get(cid) or {}).get("task") == tid]
        if not ids:
            continue
        statuses = [results[cid]["status"] for cid in ids]
        weights = [float((cells_by_id.get(cid) or {}).get("weight") or 0) for cid in ids]
        tasks_out[tid] = {
            "id": tid, "cells": ids,
            "wins": sum(1 for s in statuses if s == "improved"),
            "losses": sum(1 for s in statuses if s == "regressed"),
            "uncertain": sum(1 for s in statuses if s == "uncertain"),
            "improved": aggregate(statuses, str(task.get("aggregation") or "all"), weights),
            "lost": lost(statuses, str(task.get("aggregation") or "all"), weights),
            "aggregation": task.get("aggregation"), "weight": float(task.get("weight") or 1.0),
        }

    groups_out: list[dict] = []
    for group in ev.get("task_groups") or []:
        tids = [str(t) for t in (group.get("tasks") or []) if str(t) in tasks_out]
        if not tids:
            continue
        task_statuses = ["improved" if tasks_out[tid]["improved"] else
                         ("regressed" if tasks_out[tid]["lost"] else
                          ("uncertain" if tasks_out[tid]["uncertain"] else "noninferior"))
                         for tid in tids]
        task_weights = [float(tasks_out[tid]["weight"]) for tid in tids]
        ids = [cid for tid in tids for cid in tasks_out[tid]["cells"]]
        groups_out.append({
            "id": group.get("id"), "tasks": tids, "cells": ids,
            "wins": sum(1 for s in task_statuses if s == "improved"),
            # Group vetoes operate on the already-aggregated task votes.  A
            # majority task with two winning cells and one losing cell is an
            # improved task, not simultaneously a group loss.
            "losses": sum(1 for s in task_statuses if s == "regressed"),
            "uncertain": sum(1 for s in task_statuses if s == "uncertain"),
            "required": bool(group.get("required")),
            "improved": aggregate(task_statuses, str(group.get("aggregation") or "all"), task_weights),
            "lost": lost(task_statuses, str(group.get("aggregation") or "all"), task_weights),
        })

    # Absolute project/SOTA goals are orthogonal to evolutionary progress. A
    # node can be a useful improvement while the project is still below its
    # stated threshold. Reuse the same cell -> task -> group hierarchy.
    goal_tasks_out: dict[str, dict] = {}
    for tid, task in task_specs.items():
        ids = [cid for cid in default_targets if (cells_by_id.get(cid) or {}).get("task") == tid
               and (cells_by_id.get(cid) or {}).get("goal_threshold") is not None]
        if not ids:
            continue
        raw = [results[cid].get("goal_status") for cid in ids]
        statuses = ["improved" if s == "met" else "regressed" if s == "not_met" else "uncertain"
                    for s in raw]
        weights = [float((cells_by_id.get(cid) or {}).get("weight") or 0) for cid in ids]
        goal_tasks_out[tid] = {
            "id": tid, "cells": ids, "met": sum(1 for s in raw if s == "met"),
            "not_met": sum(1 for s in raw if s == "not_met"),
            "unknown": sum(1 for s in raw if s == "unknown"),
            "goal_met": aggregate(statuses, str(task.get("aggregation") or "all"), weights),
            "weight": float(task.get("weight") or 1.0),
        }
    goal_groups_out: list[dict] = []
    for group in ev.get("task_groups") or []:
        tids = [str(t) for t in (group.get("tasks") or []) if str(t) in goal_tasks_out]
        if not tids:
            continue
        statuses = ["improved" if goal_tasks_out[tid]["goal_met"] else
                    ("uncertain" if goal_tasks_out[tid]["unknown"] else "regressed") for tid in tids]
        weights = [float(goal_tasks_out[tid]["weight"]) for tid in tids]
        goal_groups_out.append({
            "id": group.get("id"), "tasks": tids,
            "met": sum(1 for s in statuses if s == "improved"),
            "not_met": sum(1 for s in statuses if s == "regressed"),
            "unknown": sum(1 for s in statuses if s == "uncertain"),
            "goal_met": aggregate(statuses, str(group.get("aggregation") or "all"), weights),
        })

    configured_need_groups = int((ev.get("decision") or {}).get("min_target_groups_improved") or 1)
    # A specialist result is deliberately not an overall-project pass. It may
    # establish one scoped scientific win even when the global contract asks
    # for broader movement; the distinct verdict prevents overclaiming.
    need_groups = 1 if kind in ("specialist", "diagnostic") else configured_need_groups
    target_wins = [cid for cid in target_ids if results.get(cid, {}).get("status") == "improved"]
    target_losses = [cid for cid in target_ids if results.get(cid, {}).get("status") == "regressed"]
    target_uncertain = [cid for cid in target_ids if results.get(cid, {}).get("status") == "uncertain"]
    group_success = sum(1 for g in groups_out if g["improved"]) >= need_groups
    target_success = bool(target_wins) and (group_success if groups_out else True)
    guard_required = bool((ev.get("decision") or {}).get("guardrails_must_be_noninferior", True))
    guard_losses = [cid for cid in guard_ids if results.get(cid, {}).get("status") == "regressed"]
    guard_uncertain = [cid for cid in guard_ids if results.get(cid, {}).get("status") == "uncertain"]
    hard_losses = guard_losses if guard_required else []
    hard_uncertain = guard_uncertain if guard_required else []
    breadth_losses = [cid for cid in breadth_ids if results.get(cid, {}).get("status") == "regressed"]
    required_target_ids = [cid for cid in target_ids if (cells_by_id.get(cid) or {}).get("required")]
    required_target_losses = [cid for cid in required_target_ids
                              if results.get(cid, {}).get("status") == "regressed"]
    required_uncertain = [cid for cid in required_target_ids
                          if results.get(cid, {}).get("status") == "uncertain"]
    # A required group must not be LOST under its own declared aggregation.
    # Vetoing on any single losing cell inside it made `required: false` on a
    # target cell unreachable and made decision.min_target_groups_improved
    # meaningless: the contract offered a portfolio rule and then a veto that
    # demanded zero regressions everywhere.
    required_group_losses = [g["id"] for g in groups_out if g["required"] and g["lost"]]
    # Same rule in the third direction.  A group whose declared aggregation has
    # already settled it - won or lost - is not "undecided" because a minority
    # cell came back uncertain; vetoing on any uncertain task let one minority
    # measurement override the very aggregation the user declared to stop that.
    required_group_uncertain = [g["id"] for g in groups_out if g["required"]
                                and g["uncertain"] > 0
                                and not g["improved"] and not g["lost"]]

    goal_min = int((ev.get("decision") or {}).get("min_target_groups_goal_met") or 0)
    required_goal_ids = [cid for cid in default_targets if (cells_by_id.get(cid) or {}).get("required")
                         and (cells_by_id.get(cid) or {}).get("goal_threshold") is not None]
    required_goal_not_met = [cid for cid in required_goal_ids
                             if results.get(cid, {}).get("goal_status") != "met"]
    absolute_guardrail_ids = [cid for cid in global_guard
                              if (cells_by_id.get(cid) or {}).get("goal_threshold") is not None]
    absolute_guardrail_not_met = [cid for cid in absolute_guardrail_ids
                                  if results.get(cid, {}).get("goal_status") == "not_met"]
    absolute_guardrail_unknown = [cid for cid in absolute_guardrail_ids
                                  if results.get(cid, {}).get("goal_status") == "unknown"]
    goal_groups_met = [str(g.get("id")) for g in goal_groups_out if g.get("goal_met")]
    # R7: a guardrail-only absolute contract (relative quality target + hard
    # deployment limit on a guardrail cell) is legal config; judging "has
    # goals" by target goal-tasks alone reported project_goal=None ("not
    # assessed") while the engine had already identified the guardrail breach.
    has_absolute_goals = bool(goal_tasks_out) or bool(absolute_guardrail_ids)
    project_goal_attained = (not required_goal_not_met
                             and len(goal_groups_met) >= goal_min
                             and not absolute_guardrail_not_met
                             and not absolute_guardrail_unknown
                             and not guard_losses and not guard_uncertain) if has_absolute_goals else None

    verdict = "inconclusive"
    if hard_losses or required_target_losses or required_group_losses:
        verdict = "regressed"
    elif kind == "efficiency":
        improvement_statuses = [results.get(cid, {}).get("status") for cid in efficiency_improvement_ids]
        parity_statuses = [results.get(cid, {}).get("status") for cid in efficiency_parity_ids]
        threshold_status = check_prediction(meta.get("dominance") or {}, metrics)
        if any(s == "regressed" for s in improvement_statuses + parity_statuses):
            verdict = "tradeoff"
        elif hard_uncertain or required_uncertain or required_group_uncertain \
                or any(s == "uncertain" for s in improvement_statuses + parity_statuses):
            verdict = "inconclusive"
        elif all(s == "improved" for s in improvement_statuses) \
                and parity_statuses and all(s in ("improved", "noninferior") for s in parity_statuses) \
                and (threshold_status == "confirmed" if improvement_statuses
                     else not efficiency_improvement_ids) \
                and (group_success if efficiency_improvement_ids
                     else str((effect_contract.get("resources") or {}).get("status") or "") == "met"):
            # R5: parity-only efficiency (improvement_cells []) has no quality
            # dominance threshold - the resource-side win is settled by the
            # effect contract's efficiency regime. Quality group_success can
            # never be true when every claimed cell is held at parity, so the
            # parity-only branch settles on that frozen resource regime.
            verdict = "dominant"
    elif target_success and not hard_uncertain and not required_uncertain and not required_group_uncertain:
        if kind == "specialist":
            same_checkpoint_conflict = ev.get("model_scope") == "single_checkpoint" and bool(breadth_losses)
            verdict = "tradeoff" if (guard_losses or same_checkpoint_conflict) else "specialist"
        elif kind == "diagnostic":
            # This is only the performance effect of a causal diagnostic.  A
            # performance regression can still be scientifically informative;
            # the causal settlement is reported separately in ablation_result.
            verdict = "tradeoff" if guard_losses else "improved"
        elif breadth_losses or target_losses or guard_losses:
            verdict = "tradeoff" if (ev.get("decision") or {}).get("allow_specialist", True) else "regressed"
        else:
            verdict = "improved"
    elif target_losses and not target_wins:
        verdict = "regressed"
    elif target_success and (hard_uncertain or required_uncertain or target_uncertain):
        verdict = "inconclusive"

    # Reserve promising-at-parity for a genuinely new full program, not a local
    # irreducible kernel carried by a root label.  Otherwise scope silently
    # masquerades as paradigm novelty in graph promotion.
    paradigm_root = (meta.get("change_scope") == "full_program" and
                     str((meta.get("novelty") or {}).get("kind") or "") == "paradigm")
    if verdict == "inconclusive" and node.get("role") == "root" and paradigm_root:
        declared = [results.get(cid, {}).get("status") for cid in target_ids]
        resource_contract = effect_contract.get("resources") or {}
        resource_axes = resource_contract.get("axes") or {}
        # Same resource rule as everywhere else: "did not buy the result with
        # more of this resource", not "is provably cheaper on every axis".  The
        # second reading is the one that made an equal-cost matched design
        # unachievable, and it had survived here as a private re-implementation.
        resources_clean = (resource_contract.get("status") == "met"
                           and set(resource_axes) == set(econfig.resource_axes(ctx.cfg))
                           and all(isinstance(row, dict) and row.get("relation") != "worse"
                                   for row in resource_axes.values()))
        if declared and all(s in ("improved", "noninferior") for s in declared) \
                and not hard_uncertain and resources_clean:
            verdict = "promising"

    primary = econfig.primary_metric(ctx.cfg)
    pc = next((r for r in results.values() if r.get("result_key") == primary), None)
    rel = None
    if pc and pc.get("delta") is not None and pc.get("reference") is not None:
        ref = float(pc["reference"])
        rel = float(pc["delta"]) / abs(ref) * 100 if ref else (100.0 if pc["delta"] > 0 else -100.0)
    overall_contract_pass = (kind not in ("specialist", "diagnostic")
                             and verdict in ("improved", "dominant")
                             and effect_contract.get("status") in ("met", "not_applicable"))
    scientific_promotion_status = promotion_status(
        verdict, effect_contract, mechanism_contract, research_kernel=research_kernel,
        fidelity_settled=not node.get("needs_fidelity") or not node.get("fidelity_pending"))
    if node.get("experiment_purpose") in econfig.INSTRUMENTAL_PURPOSES \
            or node.get("experiment_purpose") in econfig.EXPLORATORY_PURPOSES:
        # Instrumental work makes no frozen M/E claim, so it can neither earn
        # nor lose scientific promotion; the research inheritance frontier
        # simply never sees it (maintenance stays frontier-TRANSPARENT).
        # v11.1 P5: exploratory declared its results observations-only at
        # admission - promotion is pinned not_applicable by construction.
        scientific_promotion_status = "not_applicable"
    return {"verdict": verdict, "display_delta_pct": rel, "claim_kind": kind,
            "overall_contract_pass": overall_contract_pass,
            "effect_contract": effect_contract,
            "effect_contract_status": effect_contract.get("status"),
            "mechanism_contract": mechanism_contract,
            "mechanism_contract_status": mechanism_contract.get("status"),
            "scientific_promotion_status": scientific_promotion_status,
            "configured_min_target_groups_improved": configured_need_groups,
            "efficiency_improvement_cells": efficiency_improvement_ids,
            "efficiency_parity_cells": efficiency_parity_ids,
            "target_cells": target_ids, "guardrail_cells": guard_ids,
            "cells": results, "tasks": tasks_out, "groups": groups_out,
            "goal_tasks": goal_tasks_out, "goal_groups": goal_groups_out,
            "goal_groups_met": goal_groups_met,
            "required_goal_not_met": required_goal_not_met,
            "absolute_guardrail_not_met": absolute_guardrail_not_met,
            "absolute_guardrail_unknown": absolute_guardrail_unknown,
            "project_goal_attained": project_goal_attained,
            "target_wins": target_wins, "target_losses": target_losses,
            "guardrail_losses": guard_losses, "guardrail_uncertain": guard_uncertain,
            "required_target_losses": required_target_losses,
            "required_target_uncertain": required_uncertain,
            "required_group_losses": required_group_losses,
            "required_group_uncertain": required_group_uncertain,
            "breadth_losses": breadth_losses}


def computed_verdict(ctx: Ctx, node: dict, metrics: dict) -> tuple[str, float | None]:
    assessment = computed_assessment(ctx, node, metrics)
    return str(assessment["verdict"]), assessment.get("display_delta_pct")


def check_prediction(pred: dict, metrics: dict, floor: float = 0.0) -> str:
    # R4 science audit: settle with the same one-application floor rule as the
    # goal line - a scalar within the noise band of its registered threshold
    # is 'inconclusive', not a calibration win/loss (hiding the error bar must
    # not buy decisive settlements in the calibration ledger either).
    value, lower, upper = econfig.result_interval_with_floor(
        metrics.get(pred.get("metric")), float(floor or 0.0))
    if value is None or lower is None or upper is None:
        return "inconclusive"
    if pred.get("comparison") == ">=":
        return "confirmed" if lower >= float(pred.get("value")) else \
            ("refuted" if upper < float(pred.get("value")) else "inconclusive")
    return "confirmed" if upper <= float(pred.get("value")) else \
        ("refuted" if lower > float(pred.get("value")) else "inconclusive")


def pending_infra_errors(ctx: Ctx, nid: str) -> list[str]:
    """ER ids of this node's infrastructure-classed failures that no
    resolution row has dispositioned yet."""
    resolved = {str(r.get("resolves") or "") for r in ctx.store.error_resolutions(ctx.st)}
    return [str(r.get("id")) for r in ctx.store.error_records(ctx.st)
            if r.get("node") == nid and r.get("failure_class") == "infrastructure"
            and str(r.get("id")) not in resolved]


def infra_resolution_errors(ctx: Ctx, node: dict, outcome: dict, errs: list[str]) -> None:
    """The journal must not stay failure-only (v10.2): a node that hit
    infrastructure failures dispositions each one at conclude - either
    `fixed` (surface + what actually worked, the playbook entry every later
    implement/launch bundle receives) or `transient` (no fabricated lesson).
    """
    pending = pending_infra_errors(ctx, str(node.get("id") or ""))
    rows = outcome.get("infra_resolutions")
    if not pending:
        if rows:
            errs.append("OUTCOME_INFRA_RESOLUTION_SURPLUS: no unresolved infrastructure failures "
                        "exist for this node; drop infra_resolutions")
        return
    if not isinstance(rows, list):
        errs.append(f"OUTCOME_INFRA_RESOLUTION_REQUIRED: this node recorded infrastructure "
                    f"failure(s) {pending}; outcome.infra_resolutions must disposition each as "
                    "fixed (surface+fix) or transient")
        return
    seen: set[str] = set()
    for i, row in enumerate(rows):
        w = f"infra_resolutions[{i}]"
        if not isinstance(row, dict):
            errs.append(f"OUTCOME_INFRA_RESOLUTION_SHAPE: {w} must be an object")
            continue
        eid = str(row.get("error") or "")
        if eid not in pending:
            errs.append(f"OUTCOME_INFRA_RESOLUTION_UNKNOWN: {w}.error {eid!r} is not an unresolved "
                        f"infrastructure ER of this node ({pending})")
            continue
        if eid in seen:
            errs.append(f"OUTCOME_INFRA_RESOLUTION_DUP: {w} repeats {eid}")
            continue
        seen.add(eid)
        disposition = str(row.get("disposition") or "")
        if disposition == "transient":
            # Transient is the honest answer for a queue hiccup, but it must
            # not be the cheap universal escape: name the later successful RUN
            # of the same node that proves nothing needed fixing, and let the
            # engine check it really succeeded WITHOUT an intervening
            # implementation revision (which would make it "fixed", not
            # "transient").
            # Anchor the proof to the FAILURE, never to the node's current
            # seal: any node that reaches conclude necessarily has a finished
            # eval RUN at the current revision, so a current-seal check was
            # satisfiable by construction (a hardening that hardened nothing)
            # while it rejected the one run that actually proves transience
            # after any later, unrelated revision.
            proof = str(row.get("recovered_run") or "")
            failure = next((r for r in ctx.store.error_records(ctx.st)
                            if str(r.get("id")) == eid), {})
            failed = ctx.store.get_run(ctx.st, str(failure.get("run") or "")) \
                if failure.get("run") else None
            run = ctx.store.get_run(ctx.st, proof) if proof else None
            if failed is None:
                errs.append(f"OUTCOME_INFRA_TRANSIENT_UNANCHORED: {w}: {eid} records no failing RUN, so "
                            "transience cannot be evidenced; disposition it as fixed with the surface "
                            "and the fix that made it work")
            elif run is None or str(run.get("node") or "") != str(node.get("id") or ""):
                errs.append(f"OUTCOME_INFRA_TRANSIENT_PROOF: {w}.recovered_run must name a RUN of this "
                            f"node that repeated the work {failure.get('run')} failed at")
            elif run.get("status") != "finished":
                errs.append(f"OUTCOME_INFRA_TRANSIENT_PROOF: {w}.recovered_run {proof} did not finish")
            elif str(run.get("kind") or "") != str(failed.get("kind") or "") \
                    or str(run.get("stage") or "") != str(failed.get("stage") or ""):
                errs.append(f"OUTCOME_INFRA_TRANSIENT_SCOPE: {w}.recovered_run {proof} did not repeat the "
                            f"same work as {failed.get('id')} ({failed.get('kind')}/{failed.get('stage')})")
            elif str(run.get("prepared_at") or "") <= str(failed.get("prepared_at") or ""):
                errs.append(f"OUTCOME_INFRA_TRANSIENT_ORDER: {w}.recovered_run {proof} did not run after "
                            f"the failure {failed.get('id')}")
            elif str(run.get("implementation_digest") or "") != str(
                    failed.get("implementation_digest") or ""):
                errs.append(f"OUTCOME_INFRA_TRANSIENT_REVISED: {w} claims transient, but {proof} ran under a "
                            "different implementation revision than the failure - it was fixed, not transient")
            continue
        if disposition != "fixed":
            errs.append(f"OUTCOME_INFRA_RESOLUTION_DISPOSITION: {w}.disposition must be fixed|transient")
            continue
        if str(row.get("recovered_run") or ""):
            errs.append(f"OUTCOME_INFRA_RESOLUTION_SHAPE: {w}: recovered_run belongs to a transient "
                        "disposition; a fixed one carries surface + fix")
        if str(row.get("surface") or "") not in econfig.INFRA_SURFACES:
            errs.append(f"OUTCOME_INFRA_RESOLUTION_SURFACE: {w}.surface must be one of "
                        f"{econfig.INFRA_SURFACES}")
        _nontrivial(row.get("fix"), 30,
                    f"{w}.fix (the working way: command/path/lines, concrete enough to replay)", errs)
    missing = [eid for eid in pending if eid not in seen]
    if missing:
        errs.append(f"OUTCOME_INFRA_RESOLUTION_MISSING: undispositioned infrastructure failures {missing}")


def _observation_evidence_bound(ctx: Ctx, evidence: str) -> bool:
    """R10 audit: an observation becomes a permanent OB### row every future
    idea/diagnosis/recovery may consume as an established fact - its evidence
    must bind SOMETHING that exists: a repo-relative path, a RUN whose sealed
    metrics carry the number, or a registered artifact (AR id or URI). Free
    text stays legal in the surrounding fields; only the source pointer is
    checked."""
    runs = {str(r.get("id") or ""): r for r in (ctx.st.get("runs") or [])}
    by_id = eartifact.by_id(ctx.reg)
    for token in re.split(r"[\s,;]+", str(evidence or "")):
        token = token.strip().strip("()[]{}<>'\"`")
        if not token:
            continue
        if _exists(ctx, token):
            return True
        run = runs.get(token)
        # R11-006: a RUN pointer binds only when the engine actually SEALED
        # the material - evidence_status "complete" is the seal. A RUN whose
        # result the engine itself judged invalid/incomplete (or that never
        # finished) is a pointer to nothing establishable; letting it in put
        # engine-refused numbers into the permanent knowledge ledger.
        if run is not None and str(run.get("metrics_file") or "") \
                and str(run.get("status") or "") == "finished" \
                and str(run.get("evidence_status") or "") == "complete":
            return True
        row = by_id.get(token) or eartifact.find_by_uri(ctx.reg, token)
        # (sweep G-7) an AR reference binds only while the row is available -
        # a stale/invalid row is a name whose bytes nobody can check
        if row is not None and str(row.get("status") or "") == "available":
            return True
    return False


def _validate_outcome_knowledge(outcome: dict, errs: list[str], *,
                                ctx: Ctx | None = None,
                                require_observations: bool = False,
                                require_lessons: bool = False,
                                unroutable_lineage: bool = False,
                                observations_why: str = "a scientific stop must preserve its measured "
                                                        "gate miss as at least one phenomenon-ledger "
                                                        "observation") -> list[dict]:
    """Validate the reusable facts/actions emitted by either conclusion path."""
    obs = outcome.get("observations") or []
    if require_observations and not obs:
        errs.append(f"OUTCOME_OBSERVATIONS_REQUIRED: {observations_why}")
    for i, o in enumerate(obs):
        _nontrivial(o.get("statement"), 30, f"observations[{i}].statement (the surprising measured fact)", errs)
        _nontrivial(o.get("where"), 8, f"observations[{i}].where (component/stage/slice it lives in)", errs)
        _nontrivial(o.get("measurement"), 10, f"observations[{i}].measurement (the number/curve, with values)", errs)
        evidence = str(o.get("evidence") or "").strip()
        if len(evidence) < 8:
            errs.append(f"OUTCOME_OBSERVATION_EVIDENCE: observations[{i}].evidence must point at the "
                        f"artifact/metrics/log that shows it")
        elif ctx is not None and not _observation_evidence_bound(ctx, evidence):
            errs.append(f"OUTCOME_OBSERVATION_EVIDENCE_UNBOUND: observations[{i}].evidence "
                        f"{evidence!r} resolves to no existing source - cite an existing "
                        "repo-relative path, a RUN id with sealed metrics, or a registered "
                        "artifact; an observation is knowledge the whole graph will consume, "
                        "and its source must be checkable")
    lessons = outcome.get("lessons")
    if lessons is None:
        errs.append("OUTCOME_LESSONS_FIELD: 'lessons' array required (may be empty only with no_lessons_reason)")
    elif require_lessons and not lessons:
        errs.append("OUTCOME_LESSONS_REQUIRED: a scientific stop must emit at least one actionable conditional "
                    "lesson so the graph does not repeat the refuted applicability assumption")
    elif not lessons:
        _nontrivial(outcome.get("no_lessons_reason"), 30, "no_lessons_reason", errs)
    else:
        for i, lesson in enumerate(lessons):
            if lesson.get("scope") not in econfig.LESSON_SCOPES:
                errs.append(f"OUTCOME_LESSON_SCOPE: lessons[{i}].scope must be one of {econfig.LESSON_SCOPES}")
            _nontrivial(lesson.get("statement"), 30, f"lessons[{i}].statement", errs)
            _nontrivial(lesson.get("evidence"), 20, f"lessons[{i}].evidence", errs)
            _nontrivial(lesson.get("recommendation"), 20, f"lessons[{i}].recommendation", errs)
            if lesson.get("scope") == "conditional" and not \
                    (isinstance(lesson.get("tags"), list) and lesson.get("tags")):
                errs.append(f"OUTCOME_LESSON_TAGS: lessons[{i}]: conditional lessons need non-empty tags")
            if unroutable_lineage and lesson.get("scope") == "lineage":
                # R9 (external audit r6): lineage lessons route only to tasks
                # whose parent/ancestor set contains the SOURCE node. A node
                # that can never be a legal model parent (screened_out stop,
                # diagnostic probe, exploratory scout) never appears in any
                # legal lineage - the lesson would vacuously discharge a
                # knowledge duty and then be invisible forever.
                errs.append(f"OUTCOME_LESSON_LINEAGE_UNROUTABLE: lessons[{i}]: this node can never be "
                            "a legal model parent, so a lineage-scoped lesson would reach no future "
                            "task; use scope 'global' (always shown) or 'conditional' with tags "
                            "(shown to matching lanes)")
    return obs


def v_conclude(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    nid = task["subject"]["node"]
    node = egraph.by_id(ctx.g).get(nid) or {}
    outcome = _read_json(ctx, task["outputs"][0], errs)
    result_md = _read_md(ctx, task["outputs"][1], errs)
    if outcome is None or result_md is None:
        return errs
    _require_sections(result_md, ["what was built", "what happened", "interpretation"], "NODE_RESULT", errs)
    role = node.get("role")
    if role != "platform" and any(c.get("role") in ("target", "guardrail") and c.get("goal_threshold") is not None
                                   for c in econfig.evaluation_cells(ctx.cfg)):
        _require_sections(result_md, ["absolute goal status"], "NODE_RESULT", errs)
    verdict = outcome.get("verdict")
    idea_meta: dict = {}
    if node.get("idea_doc"):
        idea_meta = _idea_meta(ctx, node, errs)
    if role == "baseline":
        if verdict != "baseline":
            errs.append("OUTCOME_BASELINE: baseline verdict must be 'baseline'")
    elif role == "platform":
        if verdict not in ("enabled", "failed"):
            errs.append("OUTCOME_PLATFORM: platform verdict must be enabled|failed")
        if verdict == "enabled":
            arts = outcome.get("enabled_artifacts") or []
            # R9 (external audit r6): membership in the node's registry rows was
            # not enough - an 'invalid'/stale row (product missing at register)
            # let a platform mint an enabled-capability verdict for bytes no
            # consumer can ever use. An enabled artifact must resolve to an
            # AVAILABLE generation with a real content digest (or exist locally).
            # A remote URI (oss://, s3://...) is not locally hashable - its
            # custody is the producer receipt (recorded r5-08 boundary), so the
            # digest requirement applies only where the engine CAN check bytes.
            # (identity sweep #27) membership goes through the canonical
            # spelling - a raw-string set let `a/./b` vs `a/b` and host case
            # variants dodge or fail the check arbitrarily
            avail_uris = {eutil.norm_uri(str(a.get("uri") or ""))
                          for a in eartifact.all_artifacts(ctx.reg)
                          if a.get("node") == nid and a.get("status") == "available"
                          and (str(a.get("content_digest") or "")
                               or "://" in str(a.get("uri") or ""))}
            node_uris = {eutil.norm_uri(str(a.get("uri") or ""))
                         for a in eartifact.all_artifacts(ctx.reg) if a.get("node") == nid}
            bad = [a for a in arts
                   if not _exists(ctx, a) and eutil.norm_uri(str(a)) not in avail_uris]
            unusable = [a for a in arts
                        if eutil.norm_uri(str(a)) in node_uris
                        and eutil.norm_uri(str(a)) not in avail_uris and not _exists(ctx, a)]
            if not arts or bad:
                errs.append(f"OUTCOME_ENABLED_ARTIFACTS: enabled platforms must list artifact paths that exist "
                            f"locally or resolve to an AVAILABLE registered generation of this node "
                            f"(missing/invalid: {(unusable or bad)[:3] if arts else 'empty'}); a platform "
                            "whose product is invalid/stale cannot conclude 'enabled' - repair the producer "
                            "or conclude 'failed'")
            # a platform may STAND UP runtime services (a served PRM/verifier, a
            # tool server) - declared here, they join the requires_services registry
            for i, sv in enumerate(outcome.get("enabled_services") or []):
                nm = str((sv or {}).get("name") or "")
                if not nm or not nm.replace("-", "").replace("_", "").isalnum():
                    errs.append(f"OUTCOME_ENABLED_SERVICE: enabled_services[{i}] needs a slug 'name' "
                                f"(consumer specs will bind requires_services to it)")
                elif any(n.get("id") != nid and n.get("role") == "platform"
                         and n.get("verdict") == "enabled" and n.get("retire_reason") is None
                         and any(str((s or {}).get("name") or "") == nm
                                 for s in (n.get("enabled_services") or []))
                         for n in ctx.g.get("nodes", [])):
                    # R9 (external audit r6): a service slug must have ONE live
                    # owner - consumer specs bind by bare name, so a duplicate
                    # provider made recovery blame the wrong platform and turned
                    # unrelated consumers into its phantom hard descendants.
                    errs.append(f"OUTCOME_ENABLED_SERVICE_DUP: enabled_services[{i}].name {nm!r} is "
                                "already provided by another live enabled platform; one slug has one "
                                "owner - pick a distinct name or retire the other provider first")
                if not str((sv or {}).get("invoke_pattern") or "").strip():
                    errs.append(f"OUTCOME_ENABLED_SERVICE: enabled_services[{i}].invoke_pattern required "
                                f"(how a consumer actually calls it)")
    else:
        metrics_path = str(node.get("eval_metrics_path") or f".evo/nodes/{nid}/eval/metrics.json")
        metrics = _read_json(ctx, metrics_path, errs) or {}
        assessment = computed_assessment(ctx, node, metrics)
        frozen_assessment = node.get("evaluation_summary") or {}
        if frozen_assessment != assessment:
            errs.append("OUTCOME_EVALUATION_SEAL_DRIFT: conclusion assessment differs from the one frozen at "
                        "evaluate; restore the sealed metrics/idea/comparator evidence")
        want, delta = str(assessment["verdict"]), assessment.get("display_delta_pct")
        if verdict != want:
            errs.append(
                f"OUTCOME_VERDICT_MISMATCH: verdict must be '{want}' (computed from the claim-scoped "
                f"evaluation contract; display delta {'n/a' if delta is None else f'{delta:+.2f}%'}); "
                f"the engine computes verdicts, the analyst interprets them"
            )
        if node.get("experiment_purpose") not in econfig.INSTRUMENTAL_PURPOSES:
            effect_status = str(assessment.get("effect_contract_status") or "")
            if outcome.get("effect_contract_status") != effect_status:
                errs.append(f"OUTCOME_EFFECT_CONTRACT: effect_contract_status must be {effect_status!r}, "
                            "computed against the frozen comparator, worthwhile delta and realized resources")
            effect_text = eutil.find_section(eutil.md_sections(result_md), "effect contract") or ""
            if len(effect_text.strip()) < 80:
                errs.append("OUTCOME_EFFECT_SECTION: NODE_RESULT needs an Effect contract section (>=80 chars) "
                            "covering the declared comparator, C# worthwhile floors and nine-axis realized resources")
        if node.get("experiment_purpose") == "maintenance":
            want_parity = maintenance_parity_status(assessment)
            if outcome.get("maintenance_parity") != want_parity:
                errs.append(f"OUTCOME_MAINT_PARITY: maintenance_parity must be {want_parity!r} - the engine "
                            "settles parity over every claim target and guardrail cell; the analyst interprets it")
            parity_text = eutil.find_section(eutil.md_sections(result_md), "parity settlement") or ""
            if len(parity_text.strip()) < 60:
                errs.append("OUTCOME_MAINT_PARITY_SECTION: NODE_RESULT needs a Parity settlement section "
                            "(>=60 chars) walking the decision cells against the repaired parent")
        decision_cells = list(dict.fromkeys((assessment.get("target_cells") or []) +
                                            (assessment.get("guardrail_cells") or [])))
        missing_cells = [cid for cid in decision_cells if cid not in result_md]
        if missing_cells:
            errs.append(f"OUTCOME_CELL_COVERAGE: NODE_RESULT must discuss every claim target/global guardrail by C# id; missing {missing_cells}")
        preds = {p.get("id"): p for p in (idea_meta.get("predictions") or [])}
        outcome_pred_rows = [p for p in (outcome.get("predictions") or []) if isinstance(p, dict)]
        outcome_ids = [str(p.get("id") or "") for p in outcome_pred_rows]
        # R7: the settlement loop below iterates REGISTERED ids, so duplicate
        # or invented rows in the outcome array were never visited - while the
        # transition counted the raw array into prediction_stats, letting one
        # conclusion silently inflate the cross-round calibration record.
        dup_ids = sorted({pid for pid in outcome_ids if outcome_ids.count(pid) > 1})
        if dup_ids:
            errs.append(f"OUTCOME_PREDICTION_DUP: outcome.predictions must list each registered P# "
                        f"exactly once; duplicated {dup_ids}")
        reg_ids = {str(k) for k in preds}
        unknown_ids = sorted(set(outcome_ids) - reg_ids)
        if unknown_ids:
            errs.append(f"OUTCOME_PREDICTION_UNREGISTERED: {unknown_ids} were never registered by "
                        "the idea; settlement covers the frozen P# set only")
        addressed = {p.get("id"): p for p in outcome_pred_rows}
        rk_cell = {str((c or {}).get("result_key") or ""): str(cid)
                   for cid, c in econfig.cell_spec(ctx.cfg).items()}
        for pid, p in preds.items():
            got = addressed.get(pid)
            if got is None:
                errs.append(f"OUTCOME_PREDICTION_MISSING: registered prediction {pid} not addressed")
                continue
            expect = check_prediction(p, metrics, floor=_settlement_floor(
                ctx, node, rk_cell.get(str(p.get("metric") or ""), "")))
            if got.get("verdict") != expect:
                errs.append(f"OUTCOME_PREDICTION_VERDICT: {pid}: verdict must be '{expect}' per registered threshold and observed metrics")
            if not isinstance(got.get("observed"), (int, float)):
                errs.append(f"OUTCOME_PREDICTION_OBSERVED: {pid}: numeric 'observed' required")
        if node.get("experiment_purpose") == "targeted_ablation":
            contract = idea_meta.get("ablation") or {}
            result = outcome.get("ablation_result")
            if not isinstance(result, dict):
                errs.append("OUTCOME_ABLATION_RESULT: targeted ablation must settle its causal contract in "
                            "outcome.ablation_result")
                result = {}
            effect = str(result.get("effect") or "")
            supports = str(result.get("supports") or "")
            if effect not in ("observed", "not_observed", "inconclusive"):
                errs.append("OUTCOME_ABLATION_EFFECT: effect must be observed|not_observed|inconclusive")
            if effect == "observed":
                expected_support = str(contract.get("effect_supports") or "")
                expected_decision = str(contract.get("decision_if_effect") or "")
                if supports != expected_support:
                    errs.append(f"OUTCOME_ABLATION_SUPPORT: observed effect must support {expected_support}")
                if result.get("decision") != expected_decision:
                    errs.append("OUTCOME_ABLATION_DECISION: observed effect must copy decision_if_effect exactly")
            elif effect == "not_observed":
                expected_support = str(contract.get("no_effect_supports") or "")
                expected_decision = str(contract.get("decision_if_no_effect") or "")
                if supports != expected_support:
                    errs.append(f"OUTCOME_ABLATION_SUPPORT: no effect must support {expected_support}")
                if result.get("decision") != expected_decision:
                    errs.append("OUTCOME_ABLATION_DECISION: no effect must copy decision_if_no_effect exactly")
            elif effect == "inconclusive":
                if supports != "inconclusive":
                    errs.append("OUTCOME_ABLATION_SUPPORT: an inconclusive effect must report supports='inconclusive'")
                _nontrivial(result.get("decision"), 40,
                            "ablation_result.decision (why no registered branch is taken)", errs)
            _nontrivial(result.get("note"), 50,
                        "ablation_result.note (numbers and confound-aware causal interpretation)", errs)
            evidence = str(result.get("evidence") or "")
            if not evidence or not _exists(ctx, evidence):
                errs.append("OUTCOME_ABLATION_EVIDENCE: ablation_result.evidence must point to an existing "
                            "metrics/report artifact")
            if outcome.get("mechanism") is not None or outcome.get("scaling") is not None:
                errs.append("OUTCOME_ABLATION_NESTED_EVIDENCE: targeted ablation must not manufacture a nested "
                            "mechanism-probe or scaling settlement")
        if verdict == "regressed":
            rc = outcome.get("root_cause") or {}
            aids = {a.get("id") for a in (idea_meta.get("assumptions") or [])}
            named = rc.get("assumptions") or []
            if not named and str(rc.get("note") or "").strip().lower() != "unknown":
                errs.append("OUTCOME_ROOT_CAUSE: regressed nodes must name the failed assumption ids (from the idea's A#) or state note='unknown'")
            for a in named:
                if a not in aids:
                    errs.append(f"OUTCOME_ROOT_CAUSE_ID: {a} is not an assumption id registered by the idea")
            # F2: the literal honest-unknown is a legal terminal answer; only
            # a NON-unknown note owes the 40-char explanation (v9.2 demanded
            # note=='unknown' and then rejected it as too short).
            if str(rc.get("note") or "").strip().lower() != "unknown":
                _nontrivial(rc.get("note"), 40, "root_cause.note", errs)
        # v9: mechanism attribution settlement - the effect must be shown to flow
        # through the claimed channel, or the idea is novel decoration on tuning.
        probe = idea_meta.get("mechanism_probe") or {}
        if probe.get("signal") and \
                not str(idea_meta.get("attribution_waiver") or "").strip():
            mo = outcome.get("mechanism") or {}
            allowed_status = ("confirmed", "refuted", "unclear")
            if mo.get("status") not in allowed_status:
                errs.append("OUTCOME_MECHANISM: the idea registered a mechanism probe; outcome.mechanism.status "
                            f"must be one of {allowed_status}; expensive follow-up probes are not registered "
                            "as automatic duties")
            expected_mechanism = str((assessment.get("mechanism_contract") or {}).get("status") or "unclear")
            if mo.get("status") != expected_mechanism:
                errs.append(f"OUTCOME_MECHANISM_MISMATCH: mechanism.status must be {expected_mechanism!r}, "
                            "computed from the frozen decision_rule and sealed probe observations")
            _nontrivial(mo.get("note"), 40, "mechanism.note (the measured signal vs the registered expectation)", errs)
            evidence = str(mo.get("evidence") or "")
            expected_evidence = str(node.get("eval_metrics_path") or f".evo/nodes/{nid}/eval/metrics.json")
            if evidence != expected_evidence or not _exists(ctx, evidence):
                errs.append(f"OUTCOME_MECHANISM_EVIDENCE: mechanism.evidence must be {expected_evidence!r}, "
                            "the normalized file whose structured probe block was validated")
        if idea_meta.get("scaling"):
            so = outcome.get("scaling") or {}
            scaling = idea_meta.get("scaling") or {}
            if scaling.get("execution") == "followup_node":
                if so.get("status") != "deferred":
                    errs.append("OUTCOME_SCALING: follow-up scaling must report status='deferred'; the current node did not run those train arms")
            elif not isinstance(so.get("held"), bool):
                errs.append("OUTCOME_SCALING: reuse-only scaling evidence requires outcome.scaling.held (bool)")
            _nontrivial(so.get("note"), 40, "scaling.note (per-point numbers vs the registered trend)", errs)
        # SOTA accounting (v8): every SOTA target the idea registered gets an
        # honest settlement - met or not, with the numbers or the dimension argued.
        targets = idea_meta.get("sota_targets") or []
        if econfig.sota_enabled(ctx.cfg) and targets:
            settled = {str((s or {}).get("sota") or ""): s for s in (outcome.get("sota") or [])}
            sota_rows = {str(r.get("id") or ""): r for r in ctx.sota_rows()}
            contract_cells = econfig.cell_spec(ctx.cfg)
            for t in targets:
                tid = str((t or {}).get("sota") or "")
                got = settled.get(tid)
                if got is None:
                    errs.append(f"OUTCOME_SOTA_MISSING: registered SOTA target {tid} not settled in "
                                f"outcome.sota - name whether it was beaten on the claimed dimension")
                    continue
                if not isinstance(got.get("met"), bool):
                    errs.append(f"OUTCOME_SOTA_MET: sota[{tid}].met (bool) required")
                else:
                    row = sota_rows.get(tid) or {}
                    if row.get("comparability") != "exact" and got.get("met"):
                        errs.append(f"OUTCOME_SOTA_NONCOMPARABLE: sota[{tid}] is not an exact protocol comparison and cannot be marked met")
                    elif row.get("comparability") == "exact" and t.get("dimension") == "effect":
                        cell = contract_cells.get(str(t.get("cell") or "")) or {}
                        observed = metric_value(metrics.get(cell.get("result_key")))
                        # R4 science audit: (a) the beaten number is FROZEN at
                        # node creation (a live SOTA-row rewrite must not move
                        # the line a registered claim is settled against);
                        # (b) 'met' uses the floored bound like every other
                        # line - beating SOTA inside the noise band is not met.
                        frozen_vals = node.get("sota_targets_frozen") or {}
                        target_value = frozen_vals.get(tid, (row.get("headline") or {}).get("value"))
                        if observed is not None and isinstance(target_value, (int, float)):
                            s_floor = _settlement_floor(ctx, node, str(t.get("cell") or ""))
                            _sv, s_lower, s_upper = econfig.result_interval_with_floor(
                                metrics.get(cell.get("result_key")), s_floor)
                            direction = econfig.result_direction(ctx.cfg, str(cell.get("result_key") or ""))
                            expected_met = (float(s_lower) >= float(target_value) if direction == "max"
                                            else float(s_upper) <= float(target_value))
                            if got.get("met") != expected_met:
                                errs.append(f"OUTCOME_SOTA_MET_MISMATCH: sota[{tid}].met must be {expected_met} "
                                            f"from observed {observed} (floored bound vs frozen headline "
                                            f"{target_value})")
                _nontrivial(got.get("note"), 40, f"sota[{tid}].note (the comparison, with numbers "
                            f"when same dataset+metric)", errs)
    # Observations say what IS; lessons say what to DO. Both become graph memory.
    # A probe exists to PRODUCE observations - concluding one without at least
    # one ledger entry would mean the question was never actually answered.
    is_exploratory = node.get("experiment_purpose") in econfig.EXPLORATORY_PURPOSES
    obs = _validate_outcome_knowledge(
        outcome, errs, ctx=ctx,
        # A probe exists to answer a question; an exploratory lane (v11.1 P5)
        # exists to SCOUT - both are pointless without at least one ledger
        # observation, which is the only currency exploratory results have.
        require_observations=(node.get("experiment_purpose") == "diagnostic_probe"
                              or is_exploratory),
        # Probe/exploratory nodes are banned as model parents, so a
        # lineage-scoped lesson from them routes to no future task - same
        # dead-letter rule the screened_out stop path enforces.
        unroutable_lineage=(node.get("experiment_purpose") == "diagnostic_probe"
                            or is_exploratory),
        observations_why=("an exploratory lane's ONLY deliverable is what it saw - record >= 1 "
                          "phenomenon-ledger observation (OB###); a later confirmatory candidate "
                          "cites these" if is_exploratory else
                          "a diagnostic probe exists to answer a question; conclude it with >= 1 "
                          "phenomenon-ledger observation recording the answer"))
    infra_resolution_errors(ctx, node, outcome, errs)
    if role not in ("baseline", "platform"):
        rep_p = str(node.get("eval_report_path") or f".evo/nodes/{nid}/eval/EVAL_REPORT.md")
        rep = eutil.read_text(eutil.rpath(ctx.store.repo, rep_p)) if _exists(ctx, rep_p) else ""
        anom = (eutil.find_section(eutil.md_sections(rep), "anomalies") or "").strip()
        if anom and not anom.upper().startswith("NONE") and not obs \
                and len(str(outcome.get("no_observations_reason") or "").strip()) < 30:
            errs.append("OUTCOME_OBSERVATIONS_MISSING: the eval report flagged anomalies; conclude must "
                        "mine them into outcome.observations (statement/where/measurement/evidence) or "
                        "state no_observations_reason (>= 30 chars) - phenomena left unmined are ideas "
                        "the next round cannot have")
    return errs


def v_scientific_conclude(ctx: Ctx, task: dict) -> list[str]:
    """Conclude a node stopped by a pre-registered stage continuation gate."""
    errs: list[str] = []
    nid = task["subject"]["node"]
    node = egraph.by_id(ctx.g).get(nid) or {}
    outcome = _read_json(ctx, task["outputs"][0], errs)
    result_md = _read_md(ctx, task["outputs"][1], errs)
    if outcome is None or result_md is None:
        return errs
    _require_sections(result_md, ["what was attempted", "gate evidence", "interpretation", "unexecuted work"],
                      "SCIENTIFIC_STOP_RESULT", errs, min_chars=30)
    stop = node.get("scientific_stop") or {}
    gate = stop.get("gate") or {}
    if node.get("status") != "scientific_stop" or not stop:
        errs.append("SCIENTIFIC_STOP_STATE: node is not awaiting a scientific-stop conclusion")
    if outcome.get("node") != nid:
        errs.append(f"SCIENTIFIC_STOP_NODE: outcome.node must be {nid!r}")
    if outcome.get("verdict") != "screened_out":
        errs.append("SCIENTIFIC_STOP_VERDICT: a missed pre-registered continuation gate has verdict "
                    "'screened_out', not failed/regressed/inconclusive/refuted; the bound prerequisite was "
                    "falsified, while final predictions were not reached")
    reported = outcome.get("scientific_stop") or {}
    expected = {"stage": stop.get("stage"), "run": stop.get("run"),
                "gate_id": gate.get("id"), "decision": "stop_node"}
    for key, value in expected.items():
        if reported.get(key) != value:
            errs.append(f"SCIENTIFIC_STOP_BINDING: scientific_stop.{key} must equal engine record {value!r}")
    _nontrivial(reported.get("reason"), 30,
                "scientific_stop.reason (interpret the measured miss without changing the frozen criterion)", errs)
    for pred in gate.get("predicates") or []:
        metric = str(pred.get("metric") or "")
        if metric and metric not in result_md:
            errs.append(f"SCIENTIFIC_STOP_EVIDENCE_COVERAGE: Gate evidence must discuss metric {metric!r}")

    idea_meta = (_idea_meta(ctx, node, errs) or {}) \
        if node.get("idea_doc") else {}
    registered = {str(p.get("id") or "") for p in (idea_meta.get("predictions") or [])}
    unreached_rows = outcome.get("unreached_predictions")
    if not isinstance(unreached_rows, list):
        errs.append("SCIENTIFIC_STOP_PREDICTIONS: unreached_predictions list required")
        unreached_rows = []
    # R9 (external audit r6): the two settlements are mutually exclusive. A
    # stop DECLARES the predictions unreached (engine-checked set above); the
    # same outcome also carrying ordinary reached `predictions` rows let the
    # shared apply write reached/confirmed stats for a node whose stop just
    # certified the opposite - polluting calibration with contradictions.
    if outcome.get("predictions"):
        errs.append("SCIENTIFIC_STOP_PREDICTIONS_FORBIDDEN: a scientific stop settles ALL registered "
                    "predictions as unreached; it may not simultaneously report reached 'predictions' "
                    "rows (that would write contradictory calibration authority)")
    unreached = {str((p or {}).get("id") or "") for p in unreached_rows if isinstance(p, dict)}
    if unreached != registered:
        errs.append(f"SCIENTIFIC_STOP_PREDICTION_COVERAGE: unreached prediction ids must equal {sorted(registered)}; "
                    f"got {sorted(unreached)}")
    elif len([p for p in unreached_rows if isinstance(p, dict)]) != len(unreached):
        # R7: the set-compare above tolerated duplicate rows, which the
        # transition then counted raw into prediction_stats.
        errs.append("SCIENTIFIC_STOP_PREDICTION_DUP: each registered P# appears exactly once in "
                    "unreached_predictions")
    for i, row in enumerate(unreached_rows):
        if isinstance(row, dict):
            _nontrivial(row.get("reason"), 20, f"unreached_predictions[{i}].reason", errs)

    rc = outcome.get("root_cause") or {}
    assumption_ids = {str(a.get("id") or "") for a in (idea_meta.get("assumptions") or [])}
    named = rc.get("assumptions") or []
    gate_assumptions = set(str(a) for a in (gate.get("assumptions") or []))
    if not gate_assumptions.issubset(set(str(a) for a in named)):
        errs.append(f"SCIENTIFIC_STOP_ROOT_CAUSE: root_cause.assumptions must include every A# bound to "
                    f"the missed gate: {sorted(gate_assumptions)}")
    for aid in named:
        if aid not in assumption_ids:
            errs.append(f"SCIENTIFIC_STOP_ROOT_CAUSE_ID: {aid} is not an assumption registered by the idea")
    if str(rc.get("note") or "").strip().lower() != "unknown":
        _nontrivial(rc.get("note"), 40, "root_cause.note", errs)

    probe = idea_meta.get("mechanism_probe") or {}
    if probe.get("signal") and not str(idea_meta.get("attribution_waiver") or "").strip():
        mechanism = outcome.get("mechanism") or {}
        if mechanism.get("status") not in ("refuted", "unclear", "not_reached"):
            errs.append("SCIENTIFIC_STOP_MECHANISM: an interrupted workflow may report mechanism status "
                        "refuted|unclear|not_reached, never confirmed or silently omitted")
        # R7: refuted/unclear are ENGINE results computed from sealed probe
        # observations - with no validated snapshot on any of this node's
        # runs there is nothing to compute from, and authoring a status was
        # free-text science (the same stop could be phrased into different
        # cross-round records). No observations -> not_reached, period.
        has_probe_obs = any(
            r.get("node") == node.get("id") and r.get("probe_artifact_snapshots")
            for r in (ctx.st.get("runs") or []))
        if not has_probe_obs and mechanism.get("status") in ("refuted", "unclear"):
            errs.append("SCIENTIFIC_STOP_MECHANISM_UNOBSERVED: no validated probe observation was "
                        "sealed on any of this node's runs - the mechanism status must be "
                        "'not_reached'; refuted/unclear may only copy an engine-computed result")
        _nontrivial(mechanism.get("note"), 40, "mechanism.note", errs)

    _validate_outcome_knowledge(outcome, errs, ctx=ctx, require_observations=True,
                                require_lessons=True, unroutable_lineage=True)
    # A scientific stop is still an execution history: its infrastructure
    # failures carry the same playbook duty as an ordinary conclusion.
    infra_resolution_errors(ctx, node, outcome, errs)
    return errs


def v_close_round(ctx: Ctx, task: dict) -> list[str]:
    errs: list[str] = []
    rid = task["subject"]["round"]
    # R7 audit: a stale closer resurrected after a hold release could accept
    # the SAME round a second time - double-appending its closed row and
    # double-counting rounds_max. Closing is idempotent-by-refusal.
    if any(r.get("id") == rid and r.get("closed_at") for r in ctx.st.get("rounds", [])):
        return [f"ROUND_ALREADY_CLOSED: round {rid} already has a closed record; "
                "this close task is stale - it must be cancelled, not submitted"]
    # v10.1: RETRO.md was removed from this task.  Frontier movement, failed
    # bets and portfolio efficacy are engine-computed from the graph at close
    # (_apply_close_round); a prose retro had no engine or bundle reader.  The
    # strategist's forward-looking judgment lives in the optional
    # DOSSIER_ADDENDUM (validated below), which IS consumed by later rounds.
    active = [(l.get("id"), l.get("status")) for l in ctx.st.get("lanes", [])
              if l.get("round") == rid and l.get("status") not in ("done", "abandoned")]
    if active:
        errs.append(f"ROUND_ACTIVE_LANES: close_round is illegal while lanes remain active: {active}")
    # Filename-keyed (not positional): a v10-created open task still lists
    # RETRO.md first.  RETIRE.json itself is REQUIRED and must be a list -
    # `[]` is the explicit "nothing retires" declaration; a missing or
    # malformed file can no longer silently drop retirements.
    retire_path = next((o for o in task["outputs"] if str(o).endswith("RETIRE.json")), None)
    if not retire_path:
        errs.append("RETIRE_OUTPUT_MISSING: close_round has no RETIRE.json output (engine bug)")
    else:
        pre = len(errs)
        rj = _read_json(ctx, retire_path, errs)
        if len(errs) > pre:
            return errs  # missing/unreadable file: already recorded
        if not isinstance(rj, list):
            # includes the JSON literal `null`: a valid parse that would
            # otherwise silently drop every retirement
            errs.append("RETIRE_SHAPE: RETIRE.json must be a JSON array ([] when nothing retires)")
            return errs
        idx = egraph.by_id(ctx.g)
        # R4 science audit: the strong-justification bar keys on EVERY surface
        # the bundle tells the strategist to respect - inheritance frontier,
        # performance frontier, and per-cell record holders - not just the
        # first (a record holder could be pruned with a throwaway note).
        fr = {n["id"] for n in egraph.frontier(ctx.g, ctx.cfg, ctx.st)}
        fr |= {n["id"] for n in egraph.performance_frontier(ctx.g, ctx.cfg, ctx.st)}
        fr |= {str(rec.get("node") or "") for rec in egraph.cell_records(ctx.g, ctx.cfg)}
        # R9 (external audit r6): one submit could list the SAME node twice
        # (e.g. pruned then archived). Every row was validated against the
        # pre-submit graph, so the monotonicity check below never saw the
        # first row's effect, and apply executed both in order - leaving a
        # node labelled 'archived' whose artifacts were already invalidated by
        # the prune, without the explicit revive decision that guards it.
        seen_retire: set[str] = set()
        for i, r in enumerate(rj):
            if not isinstance(r, dict):
                errs.append(f"RETIRE_SHAPE: retire[{i}] must be an object with node/reason/note")
                continue
            n = idx.get(r.get("node"))
            if n is None:
                errs.append(f"RETIRE_UNKNOWN: retire[{i}] names nonexistent node {r.get('node')!r}")
                continue
            if str(n["id"]) in seen_retire:
                errs.append(f"RETIRE_DUPLICATE: retire[{i}]: {n['id']} is listed more than once - "
                            "each node retires at most once per round, with one reason")
                continue
            seen_retire.add(str(n["id"]))
            if r.get("reason") not in ("pruned", "archived"):
                errs.append(f"RETIRE_REASON: retire[{i}]: reason must be pruned|archived")
            if n.get("role") == "baseline":
                errs.append(f"RETIRE_BASELINE: retire[{i}] cannot retire the baseline node")
            # Retirement is monotone.  `pruned` is the dead end that only
            # `evo revive` reverses; re-listing the node as `archived` would
            # restore observation eligibility, frontier standing and
            # exploit-parent legality through a retro, with no user decision.
            if n.get("retire_reason") == "pruned" and r.get("reason") == "archived":
                errs.append(f"RETIRE_DOWNGRADE: retire[{i}]: {n['id']} is pruned; a retro cannot "
                            "soften that to 'archived'. Reopening a pruned lineage needs an explicit "
                            f"user decision ('evo revive --node {n['id']} --note ...')")
            if n["id"] in fr and r.get("reason") == "pruned":
                _nontrivial(r.get("note"), 60, f"retire[{i}].note (pruning a frontier node needs strong justification)", errs)
            elif not str(r.get("note") or "").strip():
                errs.append(f"RETIRE_NOTE: retire[{i}] needs a note")
    # optional dossier addendum: the retro may register NEW bottleneck hypotheses
    # (append-only revision; the bootstrap dossier's B# vocabulary never goes stale)
    add_p = ctx.store.profile_dir() / "DOSSIER_ADDENDUM.md"
    # R7: "append-only" is now enforced, not just asked. The task froze the
    # prior bytes at creation; a rewrite of history (edited/deleted earlier
    # B# rows that lanes already cite by bare id) rejects here. Tasks created
    # before the binding carry no fields and keep the old lenient behavior.
    prior_n = task["subject"].get("prior_addendum_len")
    prior_digest = str(task["subject"].get("prior_addendum_digest") or "")
    if isinstance(prior_n, int) and not isinstance(prior_n, bool) and prior_n > 0 and prior_digest:
        current = add_p.read_bytes() if add_p.exists() else b""
        if len(current) < prior_n \
                or hashlib.sha256(current[:prior_n]).hexdigest() != prior_digest:
            errs.append("RETRO_ADDENDUM_REWRITTEN: DOSSIER_ADDENDUM.md no longer starts with the "
                        f"exact {prior_n} bytes it held when this task was created - the addendum "
                        "is append-only (earlier B# rows are already cited by bare id elsewhere). "
                        "Restore the prior content and APPEND new lines after it")
    if add_p.exists():
        atext = eutil.read_text(add_p)
        base_p = ctx.store.profile_dir() / "PROBLEM_DOSSIER.md"
        base_bs = set(B_ID.findall(eutil.read_text(base_p))) if base_p.exists() else set()
        seen_add: set[str] = set()
        for m in re.finditer(r"^\s*[-*]\s*(B\d+)\s*:(.*)$", atext, re.M):
            b, rest = m.group(1), m.group(2)
            if b in base_bs:
                errs.append(f"RETRO_ADDENDUM_DUP: addendum redefines existing bottleneck {b}; addendum ids "
                            f"must extend the vocabulary, never rebind it")
            if b in seen_add:
                errs.append(f"RETRO_ADDENDUM_DUP: addendum defines {b} twice")
            seen_add.add(b)
            if "evidence:" not in rest.lower() and not SRC_TAG.search(rest):
                errs.append(f"RETRO_ADDENDUM_EVIDENCE: addendum {b} needs an 'evidence:' pointer or [src:] tag")
            fm = re.search(r"falsifier\s*:\s*(.+?)(?:\||$)", rest, re.I)
            dm = re.search(r"distinguish\s*:\s*(.+?)(?:\||$)", rest, re.I)
            if not fm or len(fm.group(1).strip()) < 20:
                errs.append(f"RETRO_ADDENDUM_FALSIFIER: addendum {b} needs a substantive falsifier")
            if not dm or len(dm.group(1).strip()) < 20:
                errs.append(f"RETRO_ADDENDUM_DISTINGUISH: addendum {b} needs a discriminating observation")
            if re.search(r"\b(?:SIG\d{2}|MV\d{2}|M\d{3,4})\b|https?://|arxiv\.org", rest, re.I):
                errs.append(f"RETRO_ADDENDUM_SOLUTION_LEAK: addendum {b} is problem evidence, "
                            "not a place to prescribe candidate programs or cite papers")
    return errs


VALIDATORS = {
    "project_scan": v_project_scan,
    "configure": v_configure,
    "infra": v_infra,
    "infra_interview": v_infra_interview,
    "infra_drill": v_infra_drill,
    "profile": v_profile,
    "dossier": v_dossier,
    "rubric": v_rubric,
    "sota_scan": v_sota_scan,
    "baseline_spec": v_baseline_spec,
    "provision": v_provision,
    "evidence": v_evidence,
    "diagnose": v_diagnose,
    "deep_read": v_deep_read,
    "open_round": v_open_round,
    "sketch": v_sketch,
    "tournament": v_tournament,
    "pose": v_pose,
    "theorize": v_theorize,
    "challenge": v_challenge,
    "design_ablation": v_design_ablation,
    "review_ablation": v_review_ablation,
    "probe_design": v_probe_design,
    "maintenance_design": v_maintenance_design,
    "maintenance_review": v_maintenance_review,
    "mature": v_mature,
    "red_team": v_red_team,
    "plan_node": v_plan_node,
    "implement": v_implement,
    "fidelity": v_fidelity,
    "ablation_fidelity": v_ablation_fidelity,
    "smoke": v_smoke,
    "metric_bridge": v_metric_bridge,
    "rehearsal": v_rehearsal,
    "stage_launch": v_stage_launch,
    "eval_launch": v_eval_launch,
    "evaluate": v_evaluate,
    "conclude": v_conclude,
    "scientific_conclude": v_scientific_conclude,
    "close_round": v_close_round,
}
