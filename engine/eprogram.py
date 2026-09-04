"""Canonical scientific-program IR and research novelty checks.

The searched object is a forward computation, not a story about how an
incumbent was edited.  A candidate therefore separates four independent facts:

* ``program``: typed objects and executable train/infer operators;
* ``change_scope``: how much implementation must change (the L display axis);
* ``novelty``: whether the load-bearing kernel is known, a composition, or an
  irreducible mechanism (the M research axis);
* ``effect_case``: a typed kernel -> intermediate -> evaluation-cell chain and
  an explicit resource comparison (the E axis).

Theory remains a fifth, independent axis.  None of these fields is inferred
from paper motivation or from a coordinate-wise descriptor.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any


CHANGE_SCOPES = ["configuration", "local", "subsystem", "full_program"]
SCOPE_LEVEL = {"configuration": 1, "local": 2, "subsystem": 3, "full_program": 4}
NOVELTY_KINDS = ["known", "composition", "irreducible", "paradigm"]
RESEARCH_NOVELTY = {"irreducible", "paradigm"}
THEORY_ROLES = ["none", "explanatory", "derivational"]
OBJECT_KINDS = [
    "input", "state", "representation", "prediction", "supervision", "memory",
    "latent", "controller", "interface", "artifact", "other",
]
OPERATOR_KINDS = [
    "transform", "objective", "estimator", "update", "transition", "inference",
    "routing", "memory", "data", "system",
]
OPERATOR_PHASES = ["train", "infer", "both"]
KERNEL_KINDS = [
    "learned_object", "objective", "update_law", "coupling", "representation",
    "inference_rule", "data_rule", "system_relation",
]
EFFECT_DIRECTIONS = ["increase", "decrease", "stabilize"]
RESOURCE_AXES = [
    "data_examples", "train_tokens", "parameters", "train_flops", "infer_flops",
    "latency_ms", "teacher_calls", "api_calls", "selection_budget",
]
RESOURCE_REGIMES = ["matched", "budgeted_tradeoff", "efficiency"]
RESOURCE_ACCOUNTING_METHODS = [
    "dataset_manifest", "scheduler_ledger", "model_profiler", "runtime_profiler",
    "api_meter", "selection_ledger",
]
CANDIDATE_FIELDS = {
    "sketch_id", "change_scope", "program", "novelty", "effect_case",
    "claim_scope",
    "theory_role", "theory_target", "theory_rigor", "diagnosis_digest", "hypothesis_ids",
    "theory_obligations", "mech_card_ids", "collision_queries",
    "synthesis_core_ids", "synthesis_relation",
}
PROGRAM_FIELDS = {
    "scientific_parents", "objects", "operators", "training_process",
    "inference_process", "information_flow", "resource_model",
}
OBJECT_FIELDS = {"id", "kind", "semantics"}
OPERATOR_FIELDS = {"id", "kind", "phase", "semantics", "reads", "writes", "depends_on", "iteration"}
ITERATION_FIELDS = {"kind", "state_objects", "update_order", "termination", "max_steps"}
ITERATION_KINDS = ["recurrent", "fixed_point", "adaptive_search", "self_play"]
NOVELTY_FIELDS = {
    "kind", "bearer", "kernel", "known_primitives", "support_shell",
    "non_reducibility", "load_bearing_test", "semantic_break",
}
KERNEL_FIELDS = {"id", "kind", "statement", "operator_refs"}
EFFECT_FIELDS = {"comparator_id", "chain", "predicted_gain", "failure_signal", "resources"}
EFFECT_LINK_FIELDS = {"id", "kernel_refs", "intermediate", "relation", "target_cell", "direction",
                      "minimum_worthwhile_delta", "expected_delta_interval"}
RESOURCE_FIELDS = {"regime", "candidate", "comparator", "fixed_axes",
                   "tradeoff_axes", "improvement_axes", "comparison"}
CLAIM_SCOPE_FIELDS = {"kind", "target_cells", "guardrail_cells", "improvement_cells",
                      "parity_cells", "rationale"}
THEORY_OBLIGATION_FIELDS = {"id", "kernel_refs", "operator_refs", "satisfaction"}


def _text(v: Any) -> str:
    return str(v or "").strip()


def _need_text(v: Any, n: int, label: str, errs: list[str]) -> None:
    if len(_text(v)) < n:
        errs.append(f"PROGRAM_TEXT: {label} needs >= {n} chars")


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", _text(v).lower())


def compute_level(candidate: dict | None) -> int:
    """Return the implementation-scope level; never a novelty judgment."""
    return SCOPE_LEVEL.get(str((candidate or {}).get("change_scope") or ""), 0)


def kernel_components(candidate: dict | None) -> list[dict]:
    rows = ((candidate or {}).get("novelty") or {}).get("kernel") or []
    return [row for row in rows if isinstance(row, dict)]


def kernel_ids(candidate: dict | None) -> list[str]:
    return [str(row.get("id")) for row in kernel_components(candidate) if row.get("id")]


def operator_ids(candidate: dict | None) -> list[str]:
    rows = ((candidate or {}).get("program") or {}).get("operators") or []
    return [str(row.get("id")) for row in rows if isinstance(row, dict) and row.get("id")]


def _kernel_fingerprint_impl(candidate: dict | None, *, execution_fields: bool) -> str:
    """Shared identity builder. ``execution_fields=True`` is the current
    algorithm (v2); ``False`` reproduces the v11.4 normalization (v1) so
    hashes stored by that release keep matching through
    ``kernel_identity_matches``."""
    cand = candidate or {}
    novelty = cand.get("novelty") or {}
    program = cand.get("program") or {}
    obj_sig: dict[str, str] = {}
    for row in (program.get("objects") or []):
        if isinstance(row, dict) and row.get("id"):
            obj_sig[str(row["id"])] = json.dumps(
                [str(row.get("kind") or ""), _norm(row.get("semantics"))],
                ensure_ascii=False, separators=(",", ":"))
    shallow_sig: dict[str, str] = {}
    for row in (program.get("operators") or []):
        if isinstance(row, dict) and row.get("id"):
            shallow_sig[str(row["id"])] = json.dumps(
                [str(row.get("kind") or ""), str(row.get("phase") or ""),
                 _norm(row.get("semantics"))],
                ensure_ascii=False, separators=(",", ":"))

    def _iteration_sig(iteration: Any) -> str:
        if not isinstance(iteration, dict):
            return ""
        steps = iteration.get("max_steps")
        return json.dumps(
            [str(iteration.get("kind") or ""), _norm(iteration.get("update_order")),
             _norm(iteration.get("termination")),
             steps if isinstance(steps, int) and not isinstance(steps, bool) else None,
             sorted(obj_sig.get(str(x), f"?{x}")
                    for x in (iteration.get("state_objects") or []))],
            ensure_ascii=False, separators=(",", ":"))

    op_sig: dict[str, str] = {}
    for row in (program.get("operators") or []):
        if isinstance(row, dict) and row.get("id"):
            parts = [str(row.get("kind") or ""), str(row.get("phase") or ""),
                     _norm(row.get("semantics")),
                     sorted(obj_sig.get(str(x), f"?{x}") for x in (row.get("reads") or [])),
                     sorted(obj_sig.get(str(x), f"?{x}") for x in (row.get("writes") or []))]
            if execution_fields:
                # R10 audit: depends_on and iteration are formal EXECUTION
                # fields (the schedule and the loop bound change what the
                # program computes) - identity must carry them. depends_on
                # resolves to the prerequisites' shallow content signatures
                # (numbering-invariant, recursion-free).
                parts.append(_iteration_sig(row.get("iteration")))
                parts.append(sorted(shallow_sig.get(str(x), f"?{x}")
                                    for x in (row.get("depends_on") or [])))
            op_sig[str(row["id"])] = json.dumps(parts, ensure_ascii=False,
                                                separators=(",", ":"))
    payload = {
        "kernel": sorted(
            (str(row.get("kind") or ""), _norm(row.get("statement")),
             tuple(sorted(op_sig.get(str(x), f"?{x}")
                          for x in (row.get("operator_refs") or []))))
            for row in kernel_components(cand)
        ),
        "bearer": _norm(novelty.get("bearer")),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def kernel_fingerprint(candidate: dict | None) -> str:
    """Computation identity of the immutable core (R9 normalization + R10
    execution fields).

    Identity = bearer + per-KC (mechanism kind, normalized statement,
    STRUCTURAL operator signatures). Deliberately OUT:
    - ``novelty.kind``: a classification against prior art, not part of what
      the program computes - re-classifying the same computation must not
      mint a fresh identity.
    - candidate-local O#/OP# numbering: every reference resolves to content
      signatures, so a consistent renumbering keeps the same identity.
    Deliberately IN (R10): each core operator's ``iteration`` (loop kind,
    normalized order/termination, max_steps, state objects) and
    ``depends_on`` (as the prerequisites' shallow content signatures) -
    changing how often or in what order the core executes changes the
    computation. Hashes stored by earlier releases used older algorithms;
    comparisons must go through ``kernel_identity_matches`` (generation
    accept, no state migration needed)."""
    return _kernel_fingerprint_impl(candidate, execution_fields=True)


def legacy_kernel_fingerprint(candidate: dict | None) -> str:
    """The pre-R9 identity algorithm, kept ONLY so hashes stored by earlier
    releases keep matching (novelty.kind and raw local OP# labels were part
    of the old identity). Never store this for new work."""
    cand = candidate or {}
    novelty = cand.get("novelty") or {}
    payload = {
        "kind": novelty.get("kind"),
        "kernel": sorted(
            (str(row.get("kind") or ""), _norm(row.get("statement")),
             tuple(sorted(str(x) for x in (row.get("operator_refs") or []))))
            for row in kernel_components(cand)
        ),
        "bearer": _norm(novelty.get("bearer")),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def kernel_fingerprints(candidate: dict | None) -> tuple[str, str, str]:
    """(current, v11.4-normalized, legacy) - every spelling a stored hash may
    use, one per identity-algorithm generation. New work stores only the
    current spelling; comparisons accept all generations."""
    return (kernel_fingerprint(candidate),
            _kernel_fingerprint_impl(candidate, execution_fields=False),
            legacy_kernel_fingerprint(candidate))


def kernel_identity_matches(stored_hash: str | None, candidate: dict | None) -> bool:
    """Does a STORED kernel hash denote this candidate's computation?

    Generation-accept across identity-algorithm revisions: rows stored by any
    earlier release keep matching their verbatim computation, new rows match
    up to consistent renumbering / re-classification. No stored state is
    rewritten."""
    h = str(stored_hash or "")
    return bool(h) and h in kernel_fingerprints(candidate)


def candidate_digest(candidate: dict | None) -> str:
    # Theory prose and route evidence remain independent overlays.  A
    # theory-derived DO# -> KC#/OP# mapping is part of the executable contract,
    # so it is deliberately digest-bound with the program rather than treated
    # as later narrative.
    cand = candidate or {}
    payload = {k: cand.get(k) for k in
               ("change_scope", "program", "novelty", "effect_case", "claim_scope",
                "theory_obligations")}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _program_graph_errors(program: dict, *, where: str, baseline: bool = False,
                          require_learning: bool = True) -> tuple[list[str], set[str], set[str], set[str]]:
    errs: list[str] = []
    extra_program = sorted(set(program) - PROGRAM_FIELDS)
    if extra_program:
        errs.append(f"PROGRAM_FIELDS: {where} has unknown fields {extra_program}")
    objects = program.get("objects")
    if not isinstance(objects, list) or not objects:
        errs.append(f"PROGRAM_OBJECTS: {where}.objects needs >=1 typed object")
        objects = []
    object_ids: set[str] = set()
    for i, row in enumerate(objects):
        if not isinstance(row, dict):
            errs.append(f"PROGRAM_OBJECT: {where}.objects[{i}] must be an object")
            continue
        extra = sorted(set(row) - (OBJECT_FIELDS | ({"code"} if baseline else set())))
        if extra:
            errs.append(f"PROGRAM_OBJECT_FIELDS: {where}.objects[{i}] has unknown fields {extra}")
        oid = str(row.get("id") or "")
        if not re.fullmatch(r"O\d+", oid) or oid in object_ids:
            errs.append(f"PROGRAM_OBJECT_ID: {where}.objects[{i}] needs a unique O# id")
        object_ids.add(oid)
        if row.get("kind") not in OBJECT_KINDS:
            errs.append(f"PROGRAM_OBJECT_KIND: {where}.{oid}.kind must be one of {OBJECT_KINDS}")
        _need_text(row.get("semantics"), 30, f"{where}.{oid}.semantics", errs)

    operators = program.get("operators")
    if not isinstance(operators, list) or not operators:
        errs.append(f"PROGRAM_OPERATORS: {where}.operators needs >=1 executable operator")
        operators = []
    operator_ids_: set[str] = set()
    dependencies: dict[str, list[str]] = {}
    operator_rows: dict[str, dict] = {}
    for i, row in enumerate(operators):
        if not isinstance(row, dict):
            errs.append(f"PROGRAM_OPERATOR: {where}.operators[{i}] must be an object")
            continue
        extra = sorted(set(row) - OPERATOR_FIELDS)
        if extra:
            errs.append(f"PROGRAM_OPERATOR_FIELDS: {where}.operators[{i}] has unknown fields {extra}")
        opid = str(row.get("id") or "")
        if not re.fullmatch(r"OP\d+", opid) or opid in operator_ids_:
            errs.append(f"PROGRAM_OPERATOR_ID: {where}.operators[{i}] needs a unique OP# id")
        operator_ids_.add(opid)
        operator_rows[opid] = row
        if row.get("kind") not in OPERATOR_KINDS:
            errs.append(f"PROGRAM_OPERATOR_KIND: {where}.{opid}.kind must be one of {OPERATOR_KINDS}")
        if row.get("phase") not in OPERATOR_PHASES:
            errs.append(f"PROGRAM_OPERATOR_PHASE: {where}.{opid}.phase must be one of {OPERATOR_PHASES}")
        _need_text(row.get("semantics"), 50, f"{where}.{opid}.semantics", errs)
        reads = row.get("reads")
        writes = row.get("writes")
        if not isinstance(reads, list):
            errs.append(f"PROGRAM_OPERATOR_READS: {where}.{opid}.reads must be an array")
            reads = []
        if not isinstance(writes, list) or not writes:
            errs.append(f"PROGRAM_OPERATOR_WRITES: {where}.{opid}.writes needs >=1 object")
            writes = []
        unknown_obj = [x for x in list(reads) + list(writes) if x not in object_ids]
        if unknown_obj:
            errs.append(f"PROGRAM_OPERATOR_OBJECT: {where}.{opid} references unknown objects {unknown_obj}")
        deps = row.get("depends_on")
        if not isinstance(deps, list):
            errs.append(f"PROGRAM_OPERATOR_DEPS: {where}.{opid}.depends_on must be an array")
            deps = []
        dependencies[opid] = [str(x) for x in deps]
        iteration = row.get("iteration")
        if iteration is not None:
            if not isinstance(iteration, dict):
                errs.append(f"PROGRAM_OPERATOR_ITERATION: {where}.{opid}.iteration must be an object")
            else:
                extra_iteration = sorted(set(iteration) - ITERATION_FIELDS)
                if extra_iteration:
                    errs.append(f"PROGRAM_OPERATOR_ITERATION_FIELDS: {where}.{opid} has unknown iteration fields {extra_iteration}")
                if iteration.get("kind") not in ITERATION_KINDS:
                    errs.append(f"PROGRAM_OPERATOR_ITERATION_KIND: {where}.{opid}.iteration.kind must be one of {ITERATION_KINDS}")
                states = iteration.get("state_objects")
                if not isinstance(states, list) or not states or any(x not in object_ids for x in states):
                    errs.append(f"PROGRAM_OPERATOR_ITERATION_STATE: {where}.{opid}.iteration.state_objects must resolve to >=1 O#")
                _need_text(iteration.get("update_order"), 30, f"{where}.{opid}.iteration.update_order", errs)
                _need_text(iteration.get("termination"), 30, f"{where}.{opid}.iteration.termination", errs)
                steps = iteration.get("max_steps")
                if isinstance(steps, bool) or not isinstance(steps, int) or steps < 1:
                    errs.append(f"PROGRAM_OPERATOR_ITERATION_BOUND: {where}.{opid}.iteration.max_steps must be a positive integer")

    for opid, deps in dependencies.items():
        unknown = [x for x in deps if x not in operator_ids_]
        if unknown:
            errs.append(f"PROGRAM_OPERATOR_DEP_UNKNOWN: {where}.{opid} depends on unknown operators {unknown}")
        if opid in deps:
            errs.append(f"PROGRAM_OPERATOR_SELF_DEP: {where}.{opid} depends on itself")
    # A small explicit cycle check keeps the forward program executable.
    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in done:
            return False
        visiting.add(node)
        cyc = any(dep in dependencies and visit(dep) for dep in dependencies.get(node, []))
        visiting.remove(node)
        done.add(node)
        return cyc

    if any(visit(node) for node in dependencies):
        errs.append(f"PROGRAM_OPERATOR_CYCLE: {where}.depends_on is the instantaneous schedule and must be acyclic; "
                    "declare recurrent/fixed-point/search feedback in operator.iteration")

    object_kind = {str(row.get("id")): str(row.get("kind")) for row in objects if isinstance(row, dict)}
    sources = {oid for oid, kind in object_kind.items() if kind in ("input", "supervision")}
    outputs = {oid for oid, kind in object_kind.items() if kind in ("prediction", "interface", "artifact")}
    if not sources:
        errs.append(f"PROGRAM_ENTRY: {where} needs >=1 input/supervision entry object")
    if not outputs:
        errs.append(f"PROGRAM_EXIT: {where} needs >=1 prediction/interface/artifact output object")
    # R8-follow-up (external audit r8): "executable" is a property of the
    # OPERATOR, not of its read set alone. The old fixed point added writes as
    # soon as reads were reachable, so an operator whose declared depends_on
    # could never run (its prerequisite reads an object nothing produces)
    # still "fired" on paper and the program froze with an output no legal
    # schedule can produce. Fire an operator only when its reads are
    # available AND every declared prerequisite has itself fired.
    reachable = set(sources)
    fired: set[str] = set()
    changed = True
    while changed:
        changed = False
        for opid, row in operator_rows.items():
            if opid in fired:
                continue
            reads = {str(x) for x in (row.get("reads") or [])}
            deps = [d for d in dependencies.get(opid, []) if d in operator_rows]
            if reads.issubset(reachable) and all(d in fired for d in deps):
                fired.add(opid)
                reachable.update(str(x) for x in (row.get("writes") or []))
                changed = True
    if outputs and not (outputs & reachable):
        errs.append(f"PROGRAM_REACHABILITY: {where} has no input-to-output executable data path "
                    "(an operator counts as executable only when its reads are producible AND "
                    "every operator it depends_on can itself execute)")
    # R8 (external audit r5) + r8 follow-up: depends_on and data availability
    # are ONE execution-order constraint set - and it must be checked over the
    # WHOLE program, not per phase. The per-phase projections each dropped the
    # other phase's edges, so a mixed cycle (data order one way, declared
    # schedule the other way, the two edges living in different phases) passed
    # both projections while the full lifecycle had no legal first operator.
    # Merge explicit depends_on edges with producer->consumer data edges
    # (self-edges excluded: in-place update is iteration's business) over all
    # operators of every phase.
    writer_of: dict[str, set[str]] = {}
    for opid, row in operator_rows.items():
        for obj in (row.get("writes") or []):
            writer_of.setdefault(str(obj), set()).add(opid)
    merged: dict[str, set[str]] = {opid: set() for opid in operator_rows}
    for opid, row in operator_rows.items():
        merged[opid].update(d for d in dependencies.get(opid, [])
                            if d in operator_rows and d != opid)
        for obj in (row.get("reads") or []):
            merged[opid].update(w for w in writer_of.get(str(obj), ()) if w != opid)
    color: dict[str, int] = {}

    def _order_cycle(op: str) -> bool:
        mark = color.get(op)
        if mark == 1:
            return True
        if mark == 2:
            return False
        color[op] = 1
        hit = any(_order_cycle(d) for d in merged.get(op, ()))
        color[op] = 2
        return hit

    if any(_order_cycle(op) for op in operator_rows):
        errs.append(f"PROGRAM_EXECUTION_ORDER_CYCLE: {where}: the whole-program execution "
                    "order (depends_on merged with producer->consumer data edges, all phases) "
                    "contains a cycle - no legal first operator exists. Fold a genuine loop "
                    "INTO one operator and describe it in that operator's iteration field "
                    "(this check reads the schedule, not iteration), or fix the "
                    "schedule/data flow")
    # R10 audit (computation-semantics closure): three local approximations -
    # "some output is reachable", "an operator's reads are satisfiable" and
    # "a declared infer row writes an output" - did not compose. The missing
    # object is the LOAD-BEARING set: fired operators that sit on an
    # executable path from the sources to a PRODUCIBLE registered output
    # (backward closure over data edges and declared prerequisites). The
    # kernel check consumes it: a core citing an executable-but-inert side
    # branch attributed real results to computation that provably took no
    # part in producing them.
    produced_outputs = outputs & reachable
    load_bearing: set[str] = set()
    _pending_objs: set[str] = set(produced_outputs)
    _seen_objs: set[str] = set()
    _pending_ops: set[str] = set()
    while _pending_objs or _pending_ops:
        while _pending_objs:
            obj = _pending_objs.pop()
            if obj in _seen_objs:
                continue
            _seen_objs.add(obj)
            _pending_ops.update(w for w in writer_of.get(obj, ()) if w in fired)
        while _pending_ops:
            op = _pending_ops.pop()
            if op in load_bearing:
                continue
            load_bearing.add(op)
            row = operator_rows.get(op) or {}
            _pending_objs.update(str(x) for x in (row.get("reads") or [])
                                 if str(x) not in _seen_objs)
            _pending_ops.update(d for d in dependencies.get(op, [])
                                if d in fired and d not in load_bearing)
    if require_learning:
        train_rows = [row for row in operator_rows.values() if row.get("phase") in ("train", "both")]
        infer_rows = [row for row in operator_rows.values() if row.get("phase") in ("infer", "both")]
        if not any(row.get("kind") in ("objective", "estimator", "update", "transition", "data") for row in train_rows):
            errs.append(f"PROGRAM_TRAIN_PATH: {where} needs an explicit train objective/estimator/update/transition/data operator")
        # R10 audit: the old form accepted any DECLARED infer row that writes
        # an output, and any output kind - so a reachable training artifact
        # hid an inference path that can never execute (its reads include an
        # object nothing produces), and the deployed prediction was frozen,
        # implemented and evaluated without a legal execution path.
        infer_fired = [row for row in infer_rows if str(row.get("id") or "") in fired]
        if not any(set(str(x) for x in (row.get("writes") or [])) & outputs for row in infer_fired):
            errs.append(f"PROGRAM_INFER_PATH: {where} needs an EXECUTABLE infer/both operator that "
                        "writes a declared output (a declared inference row whose reads can never "
                        "be produced does not count)")
        deploy_targets = {oid for oid, kind in object_kind.items()
                          if kind in ("prediction", "interface")}
        if deploy_targets and not (deploy_targets & reachable):
            errs.append(f"PROGRAM_DEPLOY_UNREACHABLE: {where}: no declared prediction/interface "
                        "object is producible by the executable schedule - a reachable training "
                        "artifact cannot stand in for the deployed output")
        # R10 audit: supervision objects are ground-truth targets, visible at
        # train/scoring time only - the deployed inference path consuming one
        # would freeze a program that cannot run where its prediction is
        # claimed. Interaction-time signals the deployment genuinely receives
        # belong in input/state/controller objects.
        supervision_objs = {oid for oid, kind in object_kind.items() if kind == "supervision"}
        for row in infer_rows:
            bad = sorted(set(str(x) for x in (row.get("reads") or [])) & supervision_objs)
            if bad:
                errs.append(f"PROGRAM_INFER_SUPERVISION: {where}.{row.get('id')}: the deployed "
                            f"inference path reads typed supervision object(s) {bad}; ground-truth "
                            "targets are train/scoring-visible only - model interaction-time "
                            "signals as input/state/controller objects instead")
        train_written = {str(x) for row in train_rows for x in (row.get("writes") or [])}
        infer_read = {str(x) for row in infer_rows for x in (row.get("reads") or [])}
        if not (train_written & infer_read):
            errs.append(f"PROGRAM_TRAIN_INFER_BRIDGE: {where} must expose which trained state/object inference consumes")

    for field in ("training_process", "inference_process", "information_flow", "resource_model"):
        _need_text(program.get(field), 40, f"{where}.{field}", errs)
    # R9 audit: the fired set used to die at this function boundary, so the
    # kernel checks downstream could only verify that a referenced OP EXISTS -
    # a load-bearing core citing an operator the declared graph itself proves
    # can never execute passed every layer. Return it (R10: with the
    # load-bearing subset); the kernel check consumes both.
    return errs, object_ids, operator_ids_, fired, load_bearing


def _resource_errors(effect: dict, *, where: str,
                     extra_axes: tuple[str, ...] = ()) -> list[str]:
    errs: list[str] = []
    resources = effect.get("resources")
    if not isinstance(resources, dict):
        return [f"PROGRAM_RESOURCES: {where}.resources must be an object"]
    all_axis_names = list(RESOURCE_AXES) + [a for a in extra_axes if a not in RESOURCE_AXES]
    extra_resources = sorted(set(resources) - RESOURCE_FIELDS)
    if extra_resources:
        errs.append(f"PROGRAM_RESOURCE_FIELDS: {where}.resources has unknown fields {extra_resources}")
    for side in ("candidate", "comparator"):
        vector = resources.get(side)
        if not isinstance(vector, dict):
            errs.append(f"PROGRAM_RESOURCE_VECTOR: {where}.resources.{side} must be an object")
            continue
        missing = [axis for axis in all_axis_names if axis not in vector]
        extra = [axis for axis in vector if axis not in all_axis_names]
        if missing or extra:
            errs.append(f"PROGRAM_RESOURCE_AXES: {where}.resources.{side} must use exactly {all_axis_names}; missing={missing}, extra={extra}")
        for axis in all_axis_names:
            value = vector.get(axis)
            if value == "unknown":
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or not math.isfinite(float(value)) or value < 0:
                errs.append(f"PROGRAM_RESOURCE_VALUE: {where}.resources.{side}.{axis} must be a finite number >=0 or 'unknown'")
    regime = str(resources.get("regime") or "")
    if regime not in RESOURCE_REGIMES:
        errs.append(f"PROGRAM_RESOURCE_REGIME: {where}.resources.regime must be one of {RESOURCE_REGIMES}")
    axes: dict[str, list[str]] = {}
    for field in ("fixed_axes", "tradeoff_axes", "improvement_axes"):
        rows = resources.get(field)
        if not isinstance(rows, list) or len(rows) != len(set(str(x) for x in (rows or []))) \
                or any(str(x) not in all_axis_names for x in (rows or [])):
            errs.append(f"PROGRAM_RESOURCE_AXIS_POLICY: {where}.resources.{field} must be an explicit "
                        "unique array of declared resource axes")
            rows = []
        axes[field] = [str(x) for x in rows]
    fixed, trade, improve = map(set, (axes["fixed_axes"], axes["tradeoff_axes"],
                                     axes["improvement_axes"]))
    if fixed & trade or fixed & improve or trade & improve:
        errs.append(f"PROGRAM_RESOURCE_AXIS_OVERLAP: {where}: fixed/tradeoff/improvement axes must be disjoint")
    all_axes = set(all_axis_names)
    if regime == "matched" and (fixed != all_axes or trade or improve):
        errs.append(f"PROGRAM_RESOURCE_MATCHED_POLICY: {where}: matched regime requires every axis fixed "
                    "and no tradeoff/improvement axes")
    elif regime == "budgeted_tradeoff" and (not trade or fixed | trade != all_axes or improve):
        errs.append(f"PROGRAM_RESOURCE_TRADEOFF_POLICY: {where}: budgeted_tradeoff requires a non-empty "
                    "tradeoff_axes set and fixed_axes+tradeoff_axes must partition all axes")
    elif regime == "efficiency" and (not improve or fixed | improve != all_axes or trade):
        errs.append(f"PROGRAM_RESOURCE_EFFICIENCY_POLICY: {where}: efficiency requires a non-empty "
                    "improvement_axes set and fixed_axes+improvement_axes must partition all axes")
    _need_text(resources.get("comparison"), 80, f"{where}.resources.comparison", errs)
    return errs


def candidate_errors(candidate: dict, *, where: str, min_level: int,
                     research: bool, search_origin: str, model_parent_count: int,
                     platform: bool = False, scaling_followup: bool = False,
                     extra_axes: tuple[str, ...] = ()) -> list[str]:
    """Validate one complete forward scientific program."""
    if not isinstance(candidate, dict):
        return [f"PROGRAM_NOT_OBJECT: {where} must be an object"]
    errs: list[str] = []
    extra_candidate = sorted(set(candidate) - CANDIDATE_FIELDS)
    if extra_candidate:
        errs.append(f"PROGRAM_CANDIDATE_FIELDS: {where} has unknown fields {extra_candidate}")
    scope = str(candidate.get("change_scope") or "")
    if scope not in CHANGE_SCOPES:
        errs.append(f"PROGRAM_CHANGE_SCOPE: {where}.change_scope must be one of {CHANGE_SCOPES}")
    level = compute_level(candidate)
    if level < int(min_level or 0):
        errs.append(f"PROGRAM_UNDER_LEVEL: {where}: change_scope={scope!r} is L{level}, below lane L{min_level}")

    program = candidate.get("program")
    if not isinstance(program, dict):
        return errs + [f"PROGRAM_MISSING: {where}.program must be an object"]
    graph_errs, _object_ids, opids, fired_ops, load_bearing_ops = _program_graph_errors(
        program, where=f"{where}.program", require_learning=not platform)
    errs.extend(graph_errs)
    parent_inputs = program.get("scientific_parents")
    if not isinstance(parent_inputs, list) or len(parent_inputs) != len(set(str(x) for x in parent_inputs)):
        errs.append(f"PROGRAM_PARENTS: {where}.program.scientific_parents must be an explicit unique array")
    elif len(parent_inputs) > model_parent_count:
        errs.append(f"PROGRAM_PARENT_COUNT: {where} consumes more scientific parents than the lane declares")

    novelty = candidate.get("novelty")
    if not isinstance(novelty, dict):
        novelty = {}
        errs.append(f"PROGRAM_NOVELTY: {where}.novelty must be an object")
    else:
        extra_novelty = sorted(set(novelty) - NOVELTY_FIELDS)
        if extra_novelty:
            errs.append(f"PROGRAM_NOVELTY_FIELDS: {where}.novelty has unknown fields {extra_novelty}")
    kind = str(novelty.get("kind") or "")
    # v11.1 P2: a declared scaling follow-up lane re-runs its parent's frozen
    # kernel at new scale points - the scale dimension is the contribution, so
    # "scaling_extension" is a legal kind there (and only there).
    if kind == "scaling_extension" and not scaling_followup:
        errs.append(f"PROGRAM_NOVELTY_KIND: {where}: novelty.kind 'scaling_extension' is only legal in a "
                    "lane declared with scaling_followup_of")
    elif scaling_followup and kind != "scaling_extension":
        errs.append(f"PROGRAM_SCALING_FOLLOWUP_KIND: {where}: a scaling follow-up lane re-runs its parent's "
                    f"kernel - novelty.kind must be 'scaling_extension', not {kind!r} (claiming fresh novelty "
                    "here would ride the duplicate-kernel exemption)")
    elif kind not in NOVELTY_KINDS and not (kind == "scaling_extension" and scaling_followup):
        errs.append(f"PROGRAM_NOVELTY_KIND: {where}.novelty.kind must be one of {NOVELTY_KINDS}")
    if research and not platform and kind not in RESEARCH_NOVELTY \
            and not (kind == "scaling_extension" and scaling_followup):
        errs.append(f"PROGRAM_RESEARCH_NOVELTY: {where}: research candidates require an irreducible or paradigm kernel, not {kind!r}")
    _need_text(novelty.get("bearer"), 50, f"{where}.novelty.bearer", errs)
    kernels = novelty.get("kernel")
    if not isinstance(kernels, list):
        errs.append(f"PROGRAM_KERNEL: {where}.novelty.kernel must be an array")
        kernels = []
    # KC# names the effect-bearing mechanism, not a verdict that the component
    # itself is novel. Known/composition programs still need an auditable KC#
    # core; novelty.kind states how that core relates to prior art.
    if not platform and not kernels:
        errs.append(f"PROGRAM_KERNEL_EMPTY: {where}: every model program needs >=1 load-bearing KC# mechanism; "
                    "novelty.kind separately classifies it against prior art")
    if len(kernels) > 6:
        errs.append(f"PROGRAM_KERNEL_BUNDLE: {where}: >6 kernel components is an unauditable bundle")
    kids: set[str] = set()
    wired_ops: set[str] = set()
    for i, row in enumerate(kernels):
        if not isinstance(row, dict):
            errs.append(f"PROGRAM_KERNEL_ROW: {where}.kernel[{i}] must be an object")
            continue
        extra_kernel = sorted(set(row) - KERNEL_FIELDS)
        if extra_kernel:
            errs.append(f"PROGRAM_KERNEL_FIELDS: {where}.kernel[{i}] has unknown fields {extra_kernel}")
        kid = str(row.get("id") or "")
        if not re.fullmatch(r"KC\d+", kid) or kid in kids:
            errs.append(f"PROGRAM_KERNEL_ID: {where}.kernel[{i}] needs a unique KC# id")
        kids.add(kid)
        if row.get("kind") not in KERNEL_KINDS:
            errs.append(f"PROGRAM_KERNEL_KIND: {where}.{kid}.kind must be one of {KERNEL_KINDS}")
        _need_text(row.get("statement"), 50, f"{where}.{kid}.statement", errs)
        refs = row.get("operator_refs")
        if not isinstance(refs, list) or not refs:
            errs.append(f"PROGRAM_KERNEL_OPERATOR_REFS: {where}.{kid}.operator_refs needs >=1 OP#")
            refs = []
        unknown = [x for x in refs if x not in opids]
        if unknown:
            errs.append(f"PROGRAM_KERNEL_OPERATOR_UNKNOWN: {where}.{kid} references unknown operators {unknown}")
        # R9 audit: a load-bearing reference must point at an operator the
        # declared graph can actually EXECUTE (reads producible and every
        # depends_on itself executable). The graph pass already proves that
        # set; citing a never-executable operator attributed real results to
        # a core that provably took no part in producing them.
        dead = [x for x in refs if x in opids and x not in fired_ops]
        if dead:
            errs.append(f"PROGRAM_KERNEL_OPERATOR_UNREACHABLE: {where}.{kid} cites operators the "
                        f"declared graph can never execute: {dead} - a load-bearing core must run "
                        "on the executable path (fix reads/depends_on, or cite the operators that "
                        "actually carry the mechanism)")
        # R10 audit: executable is necessary but not sufficient - a core citing
        # only operators whose effects never reach any registered
        # prediction/interface/artifact output attributed real results to a
        # side branch that provably took no part in producing them.
        off_path = [x for x in refs if x in fired_ops and x not in load_bearing_ops]
        if off_path and not any(x in load_bearing_ops for x in refs):
            errs.append(f"PROGRAM_KERNEL_OPERATOR_OFF_PATH: {where}.{kid} cites operators {off_path} "
                        "that execute but whose writes never reach any registered output - the "
                        "load-bearing core must sit on the executable path to the outputs its "
                        "effect case claims to move (fix the wiring, or cite the operators that "
                        "actually carry the mechanism)")
        wired_ops.update(str(x) for x in refs)
    for field in ("known_primitives", "support_shell"):
        if not isinstance(novelty.get(field), list):
            errs.append(f"PROGRAM_NOVELTY_LEDGER: {where}.novelty.{field} must be an explicit array")
    primitives = novelty.get("known_primitives")
    primitives = primitives if isinstance(primitives, list) else []
    if kind == "composition" and len(primitives) < 2:
        errs.append(f"PROGRAM_COMPOSITION_CONTENT: {where}: composition must name >=2 known primitives")
    if kind in RESEARCH_NOVELTY:
        _need_text(novelty.get("non_reducibility"), 100, f"{where}.novelty.non_reducibility", errs)
        _need_text(novelty.get("load_bearing_test"), 80, f"{where}.novelty.load_bearing_test", errs)
    if kind == "paradigm":
        _need_text(novelty.get("semantic_break"), 100, f"{where}.novelty.semantic_break", errs)

    if platform:
        for forbidden in ("effect_case", "claim_scope"):
            if forbidden in candidate:
                errs.append(f"PROGRAM_PLATFORM_{forbidden.upper()}: {where}: platform programs must omit "
                            f"{forbidden}; enablement/consumer falsification is audited separately")
    if not platform:
        effect = candidate.get("effect_case")
        if not isinstance(effect, dict):
            effect = {}
            errs.append(f"PROGRAM_EFFECT_CASE: {where}.effect_case must be an object")
        else:
            extra_effect = sorted(set(effect) - EFFECT_FIELDS)
            if extra_effect:
                errs.append(f"PROGRAM_EFFECT_FIELDS: {where}.effect_case has unknown fields {extra_effect}")
        if not _text(effect.get("comparator_id")):
            errs.append(f"PROGRAM_EFFECT_COMPARATOR: {where}.effect_case.comparator_id required")
        chain = effect.get("chain")
        if not isinstance(chain, list) or not chain:
            errs.append(f"PROGRAM_EFFECT_CHAIN: {where}.effect_case.chain needs >=1 KC# -> Z# -> C# link")
            chain = []
        zids: set[str] = set()
        covered_kernels: set[str] = set()
        for i, row in enumerate(chain):
            if not isinstance(row, dict):
                errs.append(f"PROGRAM_EFFECT_LINK: {where}.effect_case.chain[{i}] must be an object")
                continue
            extra_link = sorted(set(row) - EFFECT_LINK_FIELDS)
            if extra_link:
                errs.append(f"PROGRAM_EFFECT_LINK_FIELDS: {where}.chain[{i}] has unknown fields {extra_link}")
            zid = str(row.get("id") or "")
            if not re.fullmatch(r"Z\d+", zid) or zid in zids:
                errs.append(f"PROGRAM_EFFECT_LINK_ID: {where}.chain[{i}] needs a unique Z# id")
            zids.add(zid)
            refs = row.get("kernel_refs")
            if not isinstance(refs, list) or not refs or any(x not in kids for x in refs):
                errs.append(f"PROGRAM_EFFECT_KERNEL_REFS: {where}.{zid}.kernel_refs must resolve to KC# ids")
            else:
                covered_kernels.update(str(x) for x in refs)
            _need_text(row.get("intermediate"), 50, f"{where}.{zid}.intermediate", errs)
            _need_text(row.get("relation"), 50, f"{where}.{zid}.relation", errs)
            if not re.fullmatch(r"C\d+", str(row.get("target_cell") or "")):
                errs.append(f"PROGRAM_EFFECT_CELL: {where}.{zid}.target_cell must be C#")
            if row.get("direction") not in EFFECT_DIRECTIONS:
                errs.append(f"PROGRAM_EFFECT_DIRECTION: {where}.{zid}.direction must be one of {EFFECT_DIRECTIONS}")
            minimum = row.get("minimum_worthwhile_delta")
            # R7: finite too - JSON accepts 1e309 (inf) and NaN, and a frozen
            # non-finite threshold makes the claim permanently unsettleable
            # (inf -> every result 'failed', NaN -> every comparison False).
            if isinstance(minimum, bool) or not isinstance(minimum, (int, float)) \
                    or not math.isfinite(float(minimum)) or minimum <= 0:
                errs.append(f"PROGRAM_EFFECT_MINIMUM: {where}.{zid}.minimum_worthwhile_delta must be a finite number >0")
            interval = row.get("expected_delta_interval")
            if not isinstance(interval, list) or len(interval) != 2 or any(
                    isinstance(x, bool) or not isinstance(x, (int, float))
                    or not math.isfinite(float(x)) or x < 0 for x in (interval or [])):
                errs.append(f"PROGRAM_EFFECT_INTERVAL: {where}.{zid}.expected_delta_interval must be [lower, upper] finite non-negative magnitudes")
            elif interval[0] > interval[1] or (not isinstance(minimum, bool) and isinstance(minimum, (int, float)) and interval[1] < minimum):
                errs.append(f"PROGRAM_EFFECT_INTERVAL_ORDER: {where}.{zid} needs lower<=upper and upper>=minimum_worthwhile_delta")
        missing_effect = sorted(kids - covered_kernels)
        if missing_effect:
            errs.append(f"PROGRAM_EFFECT_KERNEL_COVERAGE: {where}: effect chain omits kernels {missing_effect}")
        _need_text(effect.get("predicted_gain"), 80, f"{where}.effect_case.predicted_gain", errs)
        _need_text(effect.get("failure_signal"), 50, f"{where}.effect_case.failure_signal", errs)
        errs.extend(_resource_errors(effect, where=f"{where}.effect_case", extra_axes=extra_axes))

    claim = candidate.get("claim_scope")
    if not platform:
        if not isinstance(claim, dict):
            claim = {}
            errs.append(f"PROGRAM_CLAIM_SCOPE: {where}.claim_scope must be frozen before winner selection")
        else:
            extra_claim = sorted(set(claim) - CLAIM_SCOPE_FIELDS)
            if extra_claim:
                errs.append(f"PROGRAM_CLAIM_SCOPE_FIELDS: {where}.claim_scope has unknown fields {extra_claim}")
        ckind = str(claim.get("kind") or "")
        if ckind not in ("generalist", "specialist", "efficiency"):
            errs.append(f"PROGRAM_CLAIM_KIND: {where}.claim_scope.kind must be generalist|specialist|efficiency")
        targets = claim.get("target_cells")
        if not isinstance(targets, list) or not targets or len(set(targets)) != len(targets) or any(
                not re.fullmatch(r"C\d+", str(x)) for x in (targets or [])):
            errs.append(f"PROGRAM_CLAIM_TARGETS: {where}.claim_scope.target_cells needs unique C# ids")
            targets = []
        guards = claim.get("guardrail_cells")
        if not isinstance(guards, list) or len(set(guards)) != len(guards) or any(
                not re.fullmatch(r"C\d+", str(x)) for x in (guards or [])):
            errs.append(f"PROGRAM_CLAIM_GUARDS: {where}.claim_scope.guardrail_cells must be an explicit unique C# array")
        if ckind == "efficiency":
            improvement = claim.get("improvement_cells")
            parity = claim.get("parity_cells")
            # R5 blind-operator audit: requiring BOTH sides non-empty made a
            # one-target project mathematically unable to state the classic
            # efficiency result (quality held at parity, resources strictly
            # improved). improvement_cells may be [] - the resource-side win
            # is carried by the regime's improvement_axes, not by a cell.
            if not isinstance(improvement, list) or not isinstance(parity, list) or not parity or \
                    set(improvement) & set(parity) or set(improvement) | set(parity) != set(targets):
                errs.append(f"PROGRAM_CLAIM_EFFICIENCY: {where}: parity_cells (non-empty) plus "
                            "improvement_cells (may be [] for a parity-only claim: quality held, "
                            "resources strictly improved) must partition target_cells")
        elif "improvement_cells" in claim or "parity_cells" in claim:
            errs.append(f"PROGRAM_CLAIM_EFFICIENCY_FIELDS: {where}: improvement/parity cells are efficiency-only")
        _need_text(claim.get("rationale"), 60, f"{where}.claim_scope.rationale", errs)
        effect_resources = effect.get("resources") if isinstance(effect.get("resources"), dict) else {}
        resource_regime = str(effect_resources.get("regime") or "")
        if (ckind == "efficiency") != (resource_regime == "efficiency"):
            errs.append(f"PROGRAM_RESOURCE_CLAIM_BINDING: {where}: claim_scope.kind='efficiency' iff "
                        "effect_case.resources.regime='efficiency'")

    theory_role = str(candidate.get("theory_role") or "")
    if theory_role not in THEORY_ROLES:
        errs.append(f"PROGRAM_THEORY_ROLE: {where}.theory_role must be one of {THEORY_ROLES}")
    if search_origin == "theory_derived" and theory_role != "derivational":
        errs.append(f"PROGRAM_THEORY_DERIVED: {where}: theory_derived programs must be derivational")
    if theory_role != "none":
        _need_text(candidate.get("theory_target"), 50, f"{where}.theory_target", errs)
    rigor = str(candidate.get("theory_rigor") or "")
    if theory_role == "derivational" and rigor not in ("partial", "full"):
        errs.append(f"PROGRAM_THEORY_RIGOR: {where}: derivational theory needs theory_rigor=partial|full")
    if theory_role != "derivational" and "theory_rigor" in candidate:
        errs.append(f"PROGRAM_THEORY_RIGOR_ROLE: {where}: theory_rigor is only legal for derivational theory")
    mappings = candidate.get("theory_obligations")
    if search_origin == "theory_derived":
        if not isinstance(mappings, list) or len(mappings) < 2:
            errs.append(f"PROGRAM_THEORY_OBLIGATIONS: {where}: theory_derived programs must map >=2 DO# obligations to KC#/OP#")
            mappings = []
        seen_do: set[str] = set()
        for i, row in enumerate(mappings):
            if not isinstance(row, dict):
                errs.append(f"PROGRAM_THEORY_OBLIGATION_ROW: {where}.theory_obligations[{i}] must be an object")
                continue
            extra = sorted(set(row) - THEORY_OBLIGATION_FIELDS)
            if extra:
                errs.append(f"PROGRAM_THEORY_OBLIGATION_FIELDS: {where}.theory_obligations[{i}] has unknown fields {extra}")
            did = str(row.get("id") or "")
            if not re.fullmatch(r"DO\d+", did) or did in seen_do:
                errs.append(f"PROGRAM_THEORY_OBLIGATION_ID: {where}.theory_obligations[{i}] needs a unique DO# id")
            seen_do.add(did)
            krefs = row.get("kernel_refs")
            orefs = row.get("operator_refs")
            if not isinstance(krefs, list) or not krefs or any(k not in kids for k in krefs):
                errs.append(f"PROGRAM_THEORY_OBLIGATION_KERNEL: {where}.{did}.kernel_refs must resolve to >=1 KC#")
            if not isinstance(orefs, list) or not orefs or any(op not in opids for op in orefs):
                errs.append(f"PROGRAM_THEORY_OBLIGATION_OPERATOR: {where}.{did}.operator_refs must resolve to >=1 OP#")
            _need_text(row.get("satisfaction"), 60, f"{where}.{did}.satisfaction", errs)
    elif "theory_obligations" in candidate:
        errs.append(f"PROGRAM_THEORY_OBLIGATION_ROUTE: {where}: theory_obligations is reserved for pre-program theory_derived search")
    return errs


def baseline_program_errors(data: dict, *, where: str = "baseline program") -> list[str]:
    errs: list[str] = []
    if not isinstance(data, dict):
        return [f"BASELINE_PROGRAM_OBJECT: {where} must be an object"]
    if data.get("schema_version") != 2:
        errs.append(f"BASELINE_PROGRAM_VERSION: {where}.schema_version must be 2")
    program = data.get("program")
    if not isinstance(program, dict):
        return errs + [f"BASELINE_PROGRAM_MISSING: {where}.program must be an object"]
    graph_errs, _objects, _operators, _fired, _load_bearing = _program_graph_errors(
        program, where=f"{where}.program", baseline=True)
    errs.extend(graph_errs)
    for row in program.get("objects") or []:
        if not isinstance(row, dict):
            continue
        code = row.get("code")
        if not isinstance(code, list) or not code:
            errs.append(f"BASELINE_PROGRAM_PROVENANCE: {row.get('id')} needs >=1 repo-relative code path")
    invariants = data.get("external_invariants")
    if not isinstance(invariants, list) or len(invariants) < 2:
        errs.append(f"BASELINE_PROGRAM_INVARIANTS: {where}.external_invariants needs >=2 invariants")
    if not isinstance(data.get("unknowns"), list):
        errs.append(f"BASELINE_PROGRAM_UNKNOWNS: {where}.unknowns must be an explicit array")
    return errs


def diversity_errors(candidates: list[dict]) -> list[str]:
    """Reject duplicate cores without imposing dimension or story quotas."""
    errs: list[str] = []
    seen: dict[str, str] = {}
    bearers: dict[str, str] = {}
    for cand in candidates:
        sid = str(cand.get("sketch_id") or "?")
        fp = kernel_fingerprint(cand)
        if fp in seen:
            errs.append(f"PROGRAM_CORE_DUP: {sid} repeats {seen[fp]}'s exact irreducible core")
        else:
            seen[fp] = sid
        bearer = _norm(((cand.get("novelty") or {}).get("bearer")))
        if bearer and bearer in bearers:
            errs.append(f"PROGRAM_BEARER_DUP: {sid} repeats {bearers[bearer]}'s novelty bearer")
        elif bearer:
            bearers[bearer] = sid
    return errs
