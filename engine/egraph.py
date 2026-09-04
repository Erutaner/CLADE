"""Graph model: role/parent schema, mutations, frontier, rollups, rendered views.

Role/parent schema (v5 T1/T2 semantics, kept):
  baseline: no parents.
  root:     no model parents; MAY list platform parents (consuming infra).
  variant:  exactly 1 model parent; MAY list platform parents.
  hybrid:   >= 2 model parents; MAY list platform parents.
  platform: only platform parents allowed.
Consuming a platform never changes a node's role. Generation is computed from
model parents only, so roots stay generation 0.
"""
from __future__ import annotations

from typing import Any

import eutil
import econfig
from econfig import NODE_ROLES, NODE_STATUSES, NODE_VERDICTS, RETIRE_REASONS


def by_id(g: dict) -> dict[str, dict]:
    return {n["id"]: n for n in g.get("nodes", [])}


def level_label(node: dict) -> str:
    """Implementation scope is undefined for instrumental work."""
    labels = {"targeted_ablation": "diagnostic", "diagnostic_probe": "probe",
              "maintenance": "maint", "exploratory": "scout"}
    return labels.get(str(node.get("experiment_purpose") or ""),
                      f"L{node.get('level', 0)}")


def split_parents(parents: list[str], idx: dict[str, dict]) -> tuple[list[str], list[str]]:
    """-> (model_parents, platform_parents). Unknown ids count as model parents (schema check flags them)."""
    model, plat = [], []
    for p in parents:
        n = idx.get(p)
        if n is not None and n.get("role") == "platform":
            plat.append(p)
        else:
            model.append(p)
    return model, plat


def role_parent_errors(role: str, nid: str, parents: list[str], idx: dict[str, dict]) -> list[str]:
    errs: list[str] = []
    unknown = [p for p in parents if p not in idx]
    if unknown:
        errs.append(f"GRAPH_PARENT_UNKNOWN: {nid} references nonexistent parents {unknown}")
    # R8: duplicated parent ids are one parent, not two (a repeated id used to
    # satisfy the hybrid ">= 2" count and freeze an unsatisfiable contract).
    dups = sorted({p for p in parents if parents.count(p) > 1})
    if dups:
        errs.append(f"GRAPH_PARENT_DUP: {nid} repeats parent ids {dups}")
    model, _plat = split_parents(list(dict.fromkeys(p for p in parents if p in idx)), idx)
    if role == "baseline" and parents:
        errs.append(f"GRAPH_BASELINE_PARENTS: {nid} baseline must have no parents")
    elif role == "root" and model:
        errs.append(f"GRAPH_ROOT_PARENTS: {nid} root may list only platform parents, got model parents {model}")
    elif role == "variant" and len(model) != 1:
        errs.append(f"GRAPH_VARIANT_PARENTS: {nid} variant needs exactly 1 model parent, got {model}")
    elif role == "hybrid" and len(model) < 2:
        errs.append(f"GRAPH_HYBRID_PARENTS: {nid} hybrid needs >= 2 model parents, got {model}")
    elif role == "platform" and model:
        errs.append(f"GRAPH_PLATFORM_PARENTS: {nid} platform may list only platform parents, got {model}")
    return errs


def check_graph(g: dict) -> list[str]:
    errs: list[str] = []
    idx = by_id(g)
    seen: set[str] = set()
    for n in g.get("nodes", []):
        nid = n.get("id") or "?"
        if nid in seen:
            errs.append(f"GRAPH_DUP_ID: duplicate node id {nid}")
        seen.add(nid)
        if n.get("role") not in NODE_ROLES:
            errs.append(f"GRAPH_ROLE: {nid} has illegal role {n.get('role')!r}")
        if n.get("experiment_purpose") not in econfig.EXPERIMENT_PURPOSES:
            errs.append(f"GRAPH_EXPERIMENT_PURPOSE: {nid} has illegal experiment_purpose "
                        f"{n.get('experiment_purpose')!r}")
        if n.get("experiment_purpose") in econfig.INSTRUMENTAL_PURPOSES and n.get("role") != "variant":
            errs.append(f"GRAPH_INSTRUMENTAL_ROLE: {nid} {n.get('experiment_purpose')} must be a variant "
                        "(one observed model parent)")
        if n.get("status") not in NODE_STATUSES:
            errs.append(f"GRAPH_STATUS: {nid} has illegal status {n.get('status')!r}")
        if n.get("verdict") is not None and n.get("verdict") not in NODE_VERDICTS:
            errs.append(f"GRAPH_VERDICT: {nid} has illegal verdict {n.get('verdict')!r}")
        if n.get("retire_reason") is not None and n.get("retire_reason") not in RETIRE_REASONS:
            errs.append(f"GRAPH_RETIRE: {nid} has illegal retire_reason {n.get('retire_reason')!r}")
        errs.extend(role_parent_errors(n.get("role", "?"), nid, n.get("parents", []), idx))
        cp = n.get("code_parent")
        if cp is not None:
            if cp not in idx:
                errs.append(f"GRAPH_CODE_PARENT_UNKNOWN: {nid} code_parent {cp} does not exist")
            elif n.get("role") == "hybrid" and cp not in n.get("parents", []):
                errs.append(f"GRAPH_CODE_PARENT_HYBRID: {nid} code_parent must be one of its parents")
    # acyclicity via generation computation
    try:
        compute_generations(g)
    except ValueError as exc:
        errs.append(f"GRAPH_CYCLE: {exc}")
    return errs


def compute_generations(g: dict) -> dict[str, int]:
    idx = by_id(g)
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def gen(nid: str) -> int:
        if nid in memo:
            return memo[nid]
        if nid in visiting:
            raise ValueError(f"cycle through {nid}")
        visiting.add(nid)
        n = idx[nid]
        model, _ = split_parents([p for p in n.get("parents", []) if p in idx], idx)
        memo[nid] = 0 if not model else 1 + max(gen(p) for p in model)
        visiting.discard(nid)
        return memo[nid]

    for nid in idx:
        gen(nid)
    return memo


def ancestors(g: dict, nid: str, *, model_only: bool = False) -> list[str]:
    idx = by_id(g)
    out: list[str] = []
    seen: set[str] = set()
    stack = [nid]
    while stack:
        cur = stack.pop()
        n = idx.get(cur)
        if n is None:
            continue
        parents = n.get("parents", [])
        if model_only:
            parents, _ = split_parents([p for p in parents if p in idx], idx)
        for p in parents:
            if p not in seen:
                seen.add(p)
                out.append(p)
                stack.append(p)
    return out


def descendants(g: dict, nid: str) -> list[str]:
    idx = by_id(g)
    children: dict[str, list[str]] = {k: [] for k in idx}
    for n in g.get("nodes", []):
        for p in n.get("parents", []):
            if p in children:
                children[p].append(n["id"])
    out: list[str] = []
    seen: set[str] = set()
    stack = [nid]
    while stack:
        cur = stack.pop()
        for c in children.get(cur, []):
            if c not in seen:
                seen.add(c)
                out.append(c)
                stack.append(c)
    return out


def siblings(g: dict, parents: list[str]) -> list[dict]:
    """Nodes (not platforms) sharing at least one model parent with the given parent set."""
    pset = set(parents)
    out = []
    for n in g.get("nodes", []):
        if n.get("role") in ("platform", "baseline"):
            continue
        if pset & set(n.get("parents", [])):
            out.append(n)
    return out


def primary_score(n: dict, primary: str) -> float | None:
    v = (n.get("scores") or {}).get(primary)
    return float(v) if isinstance(v, (int, float)) else None


def decision_cells(cfg: dict) -> list[dict]:
    """Cells that decide lineage survival (diagnostics observe, they do not judge)."""
    return [c for c in econfig.evaluation_cells(cfg) if c.get("role") != "diagnostic"]


def cell_raw(node: dict, result_key: str) -> Any:
    """The node's reported value for one result key, evidence form preferred."""
    return (node.get("score_evidence") or {}).get(
        result_key, (node.get("scores") or {}).get(result_key))


def _measured(raw: Any) -> bool:
    point, lower, upper = econfig.result_interval(raw)
    return point is not None and lower is not None and upper is not None


def resource_interval(node: dict, axis: str) -> tuple[float, float] | None:
    """Realized [lower, upper] cost on one axis, or None when never priced."""
    row = (node.get("effect_resources_realized") or {}).get(axis)
    if not isinstance(row, dict):
        return None
    lower, upper = row.get("lower"), row.get("upper")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (lower, upper)):
        return None
    return float(lower), float(upper)


def _pareto_dominates(a: dict, b: dict, cfg: dict, st: dict | None = None) -> bool:
    """True when a is materially no worse than b everywhere b was measured, and
    better somewhere.

    Diagnostic cells do not decide lineage survival.  Cell-specific practical
    margins prevent noise-sized changes from deleting useful specialists.

    Coverage, not omniscience: a dimension b never measured can be neither won
    nor lost, while a dimension b measured and a did not blocks domination -
    you do not beat a rival on evidence you never collected.  Reading any
    missing number as "nothing dominates anything" instead made an
    under-measured node permanently undominatable, so one stale tip with a thin
    receipt could hold the frontier against every later result.
    """
    better = False
    compared = 0
    # Hoisted out of the pair loop: result_direction rebuilt the merged result
    # spec and resource_axes re-imported eprogram for EVERY compared pair -
    # pure functions of cfg reconstructed hundreds of thousands of times per
    # render at scale.
    cells = decision_cells(cfg)
    directions = {str(c.get("result_key") or ""): econfig.result_direction(
        cfg, str(c.get("result_key") or "")) for c in cells}
    floors = {str(c.get("result_key") or ""): econfig.noise_floor(cfg, str(c.get("id") or ""), st)
              for c in cells}
    for cell in cells:
        result_key = str(cell.get("result_key") or "")
        ar, br = cell_raw(a, result_key), cell_raw(b, result_key)
        if not _measured(br):
            continue
        if not _measured(ar):
            return False
        floor = floors[result_key]
        _fd, f_lower, f_upper = econfig.improvement_interval(
            ar, br, directions[result_key], floor=floor)
        _rd, raw_lower, raw_upper = econfig.improvement_interval(
            ar, br, directions[result_key], floor=0.0)
        compared += 1
        # One floor application (v11 R2): the inferiority VETO settles on the
        # as-reported interval with the floor folded into the margin only when
        # a side was scalar; the WIN test keeps the floored lower bound.
        active = floor > 0 and (f_lower, f_upper) != (raw_lower, raw_upper)
        margin_eff = max(float(cell.get("noninferiority_margin") or 0.0), floor) if active \
            else float(cell.get("noninferiority_margin") or 0.0)
        if raw_lower < -margin_eff:
            return False
        improve = float(cell.get("min_improvement") or 0.0)
        if (f_lower > 0.0 if improve == 0.0 else f_lower >= improve):
            better = True
    # Resource-normalized does not mean "all nine costs must be identical".
    # They are additional minimization objectives.  Disjoint intervals settle
    # strict better/worse; overlapping intervals are conservatively no worse.
    for axis in econfig.resource_axes(cfg):
        b_axis = resource_interval(b, axis)
        if b_axis is None:
            continue
        a_axis = resource_interval(a, axis)
        if a_axis is None:
            return False
        compared += 1
        if a_axis[0] > b_axis[1]:
            return False
        if a_axis[1] < b_axis[0]:
            better = True
    return better and compared > 0


def _pareto_equivalent(a: dict, b: dict, cfg: dict, st: dict | None = None) -> bool:
    """Materially indistinguishable decision vectors (collapse duplicate tips).

    Equivalence demands identical measurement coverage: a node measured on more
    dimensions is a richer observation even where it agrees on the overlap, and
    collapsing it into a thinner twin would silently discard that evidence.
    """
    compared = 0
    for cell in decision_cells(cfg):
        rk = str(cell.get("result_key") or "")
        ar, br = cell_raw(a, rk), cell_raw(b, rk)
        if _measured(ar) != _measured(br):
            return False
        if not _measured(ar):
            continue
        direction = econfig.result_direction(cfg, rk)
        floor = econfig.noise_floor(cfg, str(cell.get("id") or ""), st)
        _d1, lower_ab, _u1 = econfig.improvement_interval(ar, br, direction, floor=0.0)
        _d2, lower_ba, _u2 = econfig.improvement_interval(br, ar, direction, floor=0.0)
        # Equivalence uses as-reported bounds with the floor inside the
        # tolerance (one application, same rule as dominance/parity).
        tol = max(float(cell.get("min_improvement") or 0.0),
                  float(cell.get("noninferiority_margin") or 0.0), floor)
        if lower_ab < -tol or lower_ba < -tol:
            return False
        compared += 1
    for axis in econfig.resource_axes(cfg):
        a_axis, b_axis = resource_interval(a, axis), resource_interval(b, axis)
        if (a_axis is None) != (b_axis is None):
            return False
        if a_axis is None:
            continue
        if a_axis[1] < b_axis[0] or b_axis[1] < a_axis[0]:
            return False
        compared += 1
    return compared > 0


def instrumental_frontier_excluded(node: dict, cfg: dict) -> bool:
    """One predicate for frontier ineligibility by purpose (the dashboard used
    to keep its own copy).

    - `diagnostic_probe` answers a question: it is evidence, not lineage, and
      never enters any frontier.
    - `maintenance` is frontier-TRANSPARENT, and transparency has to hold in
      BOTH directions.  A repair that happens to measure better must not
      Pareto-dominate the very parent it repaired off the frontier: doing so
      evicted the lineage's scientific tip while `effective_frontier_ancestor`
      kept resolving parent-legality to that evicted node, deadlocking every
      later exploit of the repaired lineage.  The repaired base stays usable
      as a parent (parity=met licenses it) without competing as a tip.
    - `targeted_ablation` is one diagnostic run, excluded under preplanned
      replication (unchanged v9.2 rule).
    - `exploratory` (v11.1 P5) declared reconnaissance at admission: it bought
      freedom from prediction/theory registration by agreeing its numbers are
      observations only - never frontier material, never a record holder. A
      later confirmatory candidate must reproduce them under full rigor.
    """
    purpose = str(node.get("experiment_purpose") or "")
    if purpose in ("diagnostic_probe", "maintenance") or purpose in econfig.EXPLORATORY_PURPOSES:
        return True
    replication = ((cfg.get("evidence_policy") or {}).get("training_replication") or {})
    return bool(purpose == "targeted_ablation"
                and str(replication.get("mode") or "record_only") == "preplanned")


def effective_frontier_ancestor(idx: dict[str, dict], nid: str) -> str:
    """Maintenance nodes are frontier-TRANSPARENT: they repair a lineage's
    executable base without making a scientific claim, so parent-legality
    questions about the frontier are answered by the nearest non-maintenance
    ancestor.  Bounded walk; a broken chain returns the last node seen."""
    seen: set[str] = set()
    cur = idx.get(nid)
    while cur is not None and cur.get("experiment_purpose") == "maintenance" \
            and cur.get("id") not in seen:
        seen.add(str(cur.get("id")))
        parents = [p for p in cur.get("parents", []) if p in idx
                   and idx[p].get("role") != "platform"]
        if not parents:
            break
        cur = idx.get(parents[0])
    return str((cur or {}).get("id") or nid)


# A verdict reports how a node moved against its own comparator.  It says
# nothing about the absolute quality of the numbers the node measured, so it
# cannot decide what belongs on an observed frontier.  Only these two verdicts
# assert that there is no usable measured deliverable at all.
NO_DELIVERABLE_VERDICTS = {"screened_out", "failed"}


def observation_eligible(node: dict, cfg: dict) -> bool:
    """May this node's measured vector compete on the observed frontier?

    R9 audit: retirement is a LINEAGE decision, never an observation one.
    The old special case deleted a pruned node's measured numbers from the
    performance frontier, the cell records and the stagnation input - the
    exact rewriting this docstring already refused to do for `archived`
    ("archiving must not silently delete measurements... would let archiving
    the incumbent manufacture an apparent advance"), and README promises both
    retirement forms keep their measured numbers. Inheritance exclusion for
    BOTH retirement forms lives in `_inheritance` (the lineage axis); the
    only verdicts with no usable deliverable stay excluded here on their own
    axis.
    """
    return bool(node.get("role") != "platform"
                and node.get("status") == "concluded"
                and node.get("verdict") is not None
                and node.get("verdict") not in NO_DELIVERABLE_VERDICTS
                and not instrumental_frontier_excluded(node, cfg))


def _display_key(cfg: dict):
    display = econfig.primary_metric(cfg)
    direction = econfig.result_direction(cfg, display)
    def key(n: dict) -> tuple[float, str]:
        score = primary_score(n, display)
        if score is None:
            return float("inf"), str(n["id"])
        return (-score if direction == "max" else score), str(n["id"])
    return key


def _pareto_tips(nodes: list[dict], cfg: dict, st: dict | None = None) -> list[dict]:
    """The non-dominated set, robust to a domination relation that cycles.

    Domination here is NOT a strict partial order.  Whenever a cell's
    noninferiority_margin exceeds its min_improvement, nodes trading wins
    inside that window each count as "materially better somewhere and not
    materially worse anywhere", so A beats B beats C beats A is realizable.
    A plain "dominated by anyone" filter then deletes every member of the
    cycle - the frontier can come back EMPTY while fully measured, settled
    nodes sit in the graph, and every downstream layer reads that as "this
    project has measured nothing".

    So a node is evicted only when something beats it that it cannot beat
    back, directly or transitively - and BOTH sides of that test read the
    transitive relation.  Mixing them (direct beat, transitive beat-back) tears
    a cycle apart instead of keeping it: a member beaten from outside leaves
    while the members it beat stay, and the frontier ends up containing a node
    that an evicted node strictly dominates.  Reading both sides transitively
    keeps exactly the source components: on an acyclic relation this is the
    ordinary Pareto frontier, on a cyclic one it keeps each tied cycle whole,
    no survivor is beaten by a non-survivor, and a finite relation always has
    at least one source - so a non-empty pool never yields an empty frontier.
    """
    ids = [str(n["id"]) for n in nodes]
    beats = {(str(a["id"]), str(b["id"]))
             for a in nodes for b in nodes if a["id"] != b["id"]
             and _pareto_dominates(a, b, cfg, st) and not _pareto_dominates(b, a, cfg, st)}
    reach = set(beats)
    for k in ids:                                   # transitive closure
        via = [i for i in ids if (i, k) in reach]
        if not via:
            continue
        for j in ids:
            if (k, j) in reach:
                for i in via:
                    reach.add((i, j))
    survivors = [n for n in nodes
                 if not any((m, str(n["id"])) in reach and (str(n["id"]), m) not in reach
                            for m in ids)]
    survivors.sort(key=_display_key(cfg))
    return survivors


def collapse_equivalent_tips(tips: list[dict], cfg: dict, st: dict | None = None) -> list[dict]:
    """Display-only de-duplication of materially indistinguishable tips.

    Deliberately NOT applied inside the frontier itself: that list is also the
    legality gate for exploit parents (PORTFOLIO_EXPLOIT_OFF_FRONTIER), and a
    settled node must not lose its inheritance rights because a twin happened
    to sort first on the display cell.
    """
    out: list[dict] = []
    for n in sorted(tips, key=_display_key(cfg)):
        if not any(_pareto_equivalent(kept, n, cfg, st) for kept in out):
            out.append(n)
    return out


def performance_frontier(g: dict, cfg: dict, st: dict | None = None) -> list[dict]:
    """Observed Pareto frontier: measurement, and nothing else.

    A node whose claim was judged against - regressed against its own parent,
    inconclusive, a tradeoff - still holds the numbers it measured, and those
    numbers are where the project actually stands.  Filtering this list by
    verdict as well hid record-holding results from every view the engine
    renders, so the strategist could not see the best model it had already
    built.
    """
    return _pareto_tips([n for n in g.get("nodes", []) if observation_eligible(n, cfg)], cfg, st)


def origin_node(g: dict) -> dict | None:
    """The user's starting program: permanent comparator and provenance.

    It is never retired and never deleted by domination.  Losing frontier
    membership only means it is no longer the thing to build on.
    """
    return next((n for n in g.get("nodes", []) if n.get("role") == "baseline"), None)


def _inheritance(g: dict, cfg: dict, st: dict | None = None) -> tuple[list[dict], bool]:
    """-> (legal inheritance parents, whether that list is the origin floor).

    Legality is decided first and non-domination second.  Taking the settled
    subset of the observed frontier instead would let an unsettled node knock a
    perfectly good settled one out of the inheritance list - and if every
    observed tip happens to be unsettled, collapse inheritance to the floor
    while real settled parents sit unused.
    """
    # R7 multi-round audit + R9: BOTH retirement forms keep the measured
    # record (performance frontier, cell records) but NOT inheritance rights:
    # every legal retirement waives the node's working-byte/Git duties, so a
    # new consumer needs `evo revive` to re-prove the bytes first - exactly
    # what the revive verb promises. (pruned used to be excluded upstream in
    # observation_eligible, which wrongly deleted its measurements too; the
    # lineage exclusion for both forms now lives HERE, on the lineage axis.)
    pool = [n for n in g.get("nodes", []) if observation_eligible(n, cfg)
            and n.get("retire_reason") not in ("archived", "pruned")]
    if econfig.is_research(cfg):
        pool = [n for n in pool if n.get("scientific_promotion_status") == "met"]
    tips = _pareto_tips(pool, cfg, st)
    if tips:
        return tips, False
    # Floor, not peer: the origin stays inheritable exactly while nothing else
    # is legal - cold start, or a project whose every claim is still unsettled.
    # An unconditional baseline exemption instead let the weakest node in the
    # graph hold the inheritance frontier forever, with no exit condition.
    origin = origin_node(g)
    if origin is not None and origin.get("status") == "concluded":
        return [origin], True
    return [], False


def frontier(g: dict, cfg: dict, st: dict | None = None) -> list[dict]:
    """Active inheritance frontier: what a new candidate may build on.

    Research mode inherits only where the frozen M/E/T claim settled;
    engineering mode inherits from observed performance directly.  Use
    :func:`performance_frontier` when diagnosing useful gains whose mechanism
    claim was refuted or whose E contract missed - those nodes are legal
    reform/hybrid parents, they just do not transfer a settled claim.
    """
    return _inheritance(g, cfg, st)[0]


def frontier_is_origin_floor(g: dict, cfg: dict, st: dict | None = None) -> bool:
    """True when the inheritance frontier is only the origin fallback."""
    return _inheritance(g, cfg, st)[1]


def retired_settled_ids(g: dict, cfg: dict) -> list[str]:
    """Settled lineages later retired (pruned/archived).

    When the inheritance floor engages BECAUSE of retirement, the honest
    story is 'revive one or root anew' - not the cold-start line 'nothing
    has a settled claim yet' (R7 audit: the false diagnosis steered a fresh
    agent away from the actionable revive decision)."""
    research = econfig.is_research(cfg)
    out = []
    for n in g.get("nodes", []):
        if n.get("retire_reason") not in ("pruned", "archived"):
            continue
        # R8 audit: "revive one of these" is only honest for verdicts that CAN
        # anchor future work - NO_DELIVERABLE_VERDICTS (screened_out, failed)
        # are excluded from the observed frontier and refused as model
        # parents by the validators, so suggesting their revival promised an
        # action the engine would never honor.
        settled = (n.get("scientific_promotion_status") == "met") if research \
            else (n.get("status") == "concluded"
                  and n.get("verdict") is not None
                  and str(n.get("verdict")) not in NO_DELIVERABLE_VERDICTS)
        if settled:
            out.append(str(n.get("id")))
    return sorted(out)


def cell_records(g: dict, cfg: dict) -> list[dict]:
    """Best observed value on each decision cell, over every eligible node.

    The record holder is what a strategist must see even when its claim was
    judged against: it is the project's real position on that cell.
    """
    pool = [n for n in g.get("nodes", []) if observation_eligible(n, cfg)]
    out: list[dict] = []
    for cell in decision_cells(cfg):
        result_key = str(cell.get("result_key") or "")
        direction = econfig.result_direction(cfg, result_key)
        best: tuple[dict, float] | None = None
        for n in pool:
            point = econfig.result_value(cell_raw(n, result_key))
            if point is None:
                continue
            if best is None or (float(point) > best[1] if direction == "max"
                                else float(point) < best[1]):
                best = (n, float(point))
        if best is not None:
            out.append({"cell": str(cell.get("id")), "result_key": result_key,
                        "role": cell.get("role"), "node": str(best[0]["id"]),
                        "value": best[1], "direction": direction})
    return out


def result_vector(node: dict, cfg: dict) -> str:
    """One-line observed decision vector with intervals, for rendered views."""
    parts: list[str] = []
    for cell in decision_cells(cfg):
        result_key = str(cell.get("result_key") or "")
        point, lower, upper = econfig.result_interval(cell_raw(node, result_key))
        parts.append(f"{cell.get('id')}:{result_key}=" + (
            "-" if point is None else f"{point:g}" if lower == point == upper
            else f"{point:g}[{lower:g},{upper:g}]"))
    return " ".join(parts)


def advances_measurement(node: dict, prior: list[dict], cfg: dict, st: dict | None = None) -> bool:
    """Did this node MOVE the measured position, or merely fail to be dominated?

    Under conservative interval arithmetic, "non-dominated" is also what "too
    imprecise to decide" looks like: widen every interval enough and no node
    dominates any other, so membership of the observed frontier alone would
    report every round as an advance - including a round whose only node is
    worse on every point estimate.  A decided advance is either a strict Pareto
    improvement over something that was already a tip, or a materially best-ever
    value on some decision cell.
    """
    if any(_pareto_dominates(node, p, cfg, st) and not _pareto_dominates(p, node, cfg, st)
           for p in prior):
        return True
    for cell in decision_cells(cfg):
        result_key = str(cell.get("result_key") or "")
        raw = cell_raw(node, result_key)
        if not _measured(raw):
            continue
        direction = econfig.result_direction(cfg, result_key)
        improve = float(cell.get("min_improvement") or 0.0)
        floor = econfig.noise_floor(cfg, str(cell.get("id") or ""), st)
        rivals = [r for r in (cell_raw(p, result_key) for p in prior) if _measured(r)]
        if not rivals:
            continue
        beats_all = True
        for rival in rivals:
            _delta, lower, _upper = econfig.improvement_interval(raw, rival, direction, floor=floor)
            if not (lower > 0.0 if improve == 0.0 else lower >= improve):
                beats_all = False
                break
        if beats_all:
            return True
    return False


def provisional_record(node: dict, prior: list[dict], cfg: dict,
                       cell_id: str | None = None, st: dict | None = None) -> bool:
    """Winner's-curse label for ONE per-cell record row.

    True when, ON THE NAMED CELL, the record holder's lead over the best rival
    value is smaller than that cell's recorded noise floor: selecting the max
    of N noisy single runs systematically overestimates, and this is the row
    where that max becomes the number everyone compares against next. The
    first version aggregated across cells (any big win anywhere killed the
    label, and within-floor deltas on unrelated cells raised it) - wrong in
    both directions; the label is a per-row fact. Label only: never a gate,
    never a frontier criterion.
    """
    for cell in decision_cells(cfg):
        if cell_id is not None and str(cell.get("id") or "") != str(cell_id):
            continue
        result_key = str(cell.get("result_key") or "")
        floor = econfig.noise_floor(cfg, str(cell.get("id") or ""), st)
        if floor <= 0:
            continue
        value = econfig.result_value(cell_raw(node, result_key))
        if value is None:
            continue
        rival_values = [v for v in (econfig.result_value(cell_raw(p, result_key))
                                    for p in prior if p.get("id") != node.get("id"))
                        if v is not None]
        if not rival_values:
            continue
        direction = econfig.result_direction(cfg, result_key)
        best_rival = min(rival_values) if direction == "min" else max(rival_values)
        lead = (best_rival - value) if direction == "min" else (value - best_rival)
        if 0 <= lead < floor:
            return True
    return False


def resource_vector(node: dict, cfg: dict) -> str:
    """One-line realized cost vector, for rendered views."""
    parts: list[str] = []
    for axis in econfig.resource_axes(cfg):
        interval = resource_interval(node, axis)
        parts.append(f"{axis}=" + ("-" if interval is None
                                   else f"[{interval[0]:g},{interval[1]:g}]"))
    return " ".join(parts)


def platforms(g: dict) -> list[dict]:
    return [n for n in g.get("nodes", []) if n.get("role") == "platform" and n.get("retire_reason") is None]


def recompute_rollups(g: dict, cfg: dict) -> None:
    # Build the id index and children adjacency once for the whole graph
    # (per-node ``descendants``/``by_id`` rebuilds made this O(N^2)); the
    # per-node DFS below produces the identical rollup values.
    primary = econfig.primary_metric(cfg)
    direction = econfig.result_direction(cfg, primary)
    idx = by_id(g)
    children: dict[str, list[str]] = {k: [] for k in idx}
    for n in g.get("nodes", []):
        for p in n.get("parents", []):
            if p in children:
                children[p].append(n["id"])
    for n in g.get("nodes", []):
        seen: set[str] = set()
        stack = [n["id"]]
        dn: list[dict] = []
        while stack:
            cur = stack.pop()
            for c in children.get(cur, []):
                if c not in seen:
                    seen.add(c)
                    # Traverse THROUGH instrumental nodes (a candidate below a
                    # repair is a real descendant) but never COUNT them: a
                    # probe or repair is not a lineage's scientific offspring,
                    # and counting them let a probe report itself as an
                    # "improved descendant" in the strategy bundle.
                    if c in idx and not instrumental_frontier_excluded(idx[c], cfg):
                        dn.append(idx[c])
                    stack.append(c)
        best = None
        for d in dn:
            s = primary_score(d, primary)
            if s is not None and (best is None or (s > best if direction == "max" else s < best)):
                best = s
        n["rollup"] = {
            "descendants": len(dn),
            "descendants_concluded": sum(1 for d in dn if d.get("status") == "concluded"),
            "descendants_improved": sum(1 for d in dn if d.get("verdict") in
                                        ("improved", "specialist", "dominant")),
            "best_descendant_primary": best,
        }


def new_node(g: dict, st_counters_id: str, *, title: str, role: str, parents: list[str],
             code_parent: str | None, level: int, lane: str | None, round_: str | None,
             idea_doc: str | None, spec: str | None,
             experiment_purpose: str = "candidate") -> dict:
    node = {
        "id": st_counters_id,
        "title": title,
        "role": role,
        "experiment_purpose": experiment_purpose,
        "parents": parents,
        "code_parent": code_parent,
        "level": level,
        "lane": lane,
        "round": round_,
        "status": "proposed",
        "verdict": None,
        "retire_reason": None,
        "idea_doc": idea_doc,
        "spec": spec,
        "workdir": None,
        "branch": None,
        "scores": {},
        "score_evidence": {},
        "evaluation_summary": {},
        "mechanism_status": None,
        "checkpoint": None,
        "stage_cursor": 0,
        # A training seed owns one complete traversal of workflow.stages.
        # replica_index advances only after the final stage for that seed.
        "replica_index": 0,
        "replicas_completed": [],
        "stage_failures": 0,
        "scientific_stop": None,
        "needs_metric_bridge": False,
        "rollup": {},
        "created_at": eutil.utc_now(),
        "updated_at": eutil.utc_now(),
    }
    # R8 (external audit r5): the three-file save writes graph.json before the
    # state.json commit marker. A crash in that window leaves this id in the
    # graph while the committed counter still points below it - the retry then
    # re-allocates the same id and duplicated it. The committed counter is the
    # authority: an existing row under the id being allocated NOW is by
    # definition that crash's uncommitted debris and is replaced, not joined.
    g["nodes"] = [n for n in g.get("nodes", []) if str(n.get("id")) != str(st_counters_id)]
    g["nodes"].append(node)
    return node


def touch(n: dict) -> None:
    n["updated_at"] = eutil.utc_now()


# ---- rendered views ------------------------------------------------------------

_MERMAID_CLASSES = [
    # verdict/state -> style; dark-and-light safe colors, GitHub renders these natively
    "classDef improved fill:#0b3d2e,stroke:#22c55e,stroke-width:2px,color:#d1fae5",
    "classDef specialist fill:#0f3b46,stroke:#22d3ee,stroke-width:2px,color:#cffafe",
    "classDef tradeoff fill:#3f2b16,stroke:#fb923c,stroke-width:2px,color:#ffedd5",
    "classDef baseline fill:#172554,stroke:#60a5fa,stroke-width:2px,color:#dbeafe",
    "classDef regressed fill:#3f1d1d,stroke:#ef4444,color:#fecaca",
    "classDef inconclusive fill:#3b2f14,stroke:#f59e0b,color:#fde68a",
    "classDef promising fill:#2e1065,stroke:#c084fc,stroke-width:2px,color:#ede9fe",
    "classDef dominant fill:#042f2e,stroke:#2dd4bf,stroke-width:2px,color:#ccfbf1",
    "classDef screened_out fill:#311329,stroke:#e879f9,color:#f5d0fe",
    "classDef failed fill:#2a1215,stroke:#9f1239,color:#fda4af",
    "classDef enabled fill:#082f49,stroke:#38bdf8,color:#bae6fd",
    "classDef pending fill:#1e293b,stroke:#64748b,color:#cbd5e1",
    "classDef retired fill:#18181b,stroke:#52525b,stroke-dasharray:5 4,color:#71717a",
    "classDef frontier stroke:#fbbf24,stroke-width:4px",
]


def _mermaid_class(n: dict) -> str:
    if n.get("retire_reason") is not None or n.get("status") == "abandoned":
        return "retired"
    v = n.get("verdict")
    if v in ("improved", "specialist", "tradeoff", "baseline", "regressed", "inconclusive",
             "promising", "dominant", "screened_out", "failed", "enabled"):
        return v
    return "pending"


def _mdcell(v: Any) -> str:
    """Agent-authored free text inside an engine-owned markdown table cell:
    a raw '|' or newline is legal in a title but would silently shift every
    later column under the wrong header - escape, never reflow the table."""
    return str(v if v is not None else "").replace("\n", " ").replace("|", "\\|")


def render_views(store: Any, g: dict, cfg: dict, st: dict | None = None) -> None:
    """Regenerate .evo/views/GRAPH.md and FRONTIER.md. Engine-owned; no manual sections."""
    from econfig import primary_metric
    primary = primary_metric(cfg)
    cycle_note: list[str] = []
    try:
        gens = compute_generations(g)
    except ValueError:
        # hand-corrupted cycle: doctor reports GRAPH_CYCLE and --fix must be
        # able to finish its repairs - render degraded views, do not crash,
        # and never let a flat gen-0 view pass for a healthy fresh graph
        gens = {str(n.get("id") or ""): 0 for n in g.get("nodes", [])}
        cycle_note = ["> GRAPH CYCLE DETECTED - generations flattened; run `evo doctor`.", ""]
    idx = by_id(g)
    lane_intent = {l.get("id"): l.get("intent") for l in (st or {}).get("lanes", [])}
    frontier_ids = {n["id"] for n in frontier(g, cfg, st)}
    performance_ids = {n["id"] for n in performance_frontier(g, cfg, st)}
    lines = ["# Evolution Graph (generated; do not edit)", ""]
    lines.append("Legend: green=improved, blue=baseline, red=regressed, amber=inconclusive,")
    lines.append("violet=promising (L4 root at parity), teal=dominant (parity + registered secondary win),")
    lines.append("magenta=screened_out (pre-registered prerequisite missed), cyan=platform enabled, gray=pending,")
    lines.append("orange=tradeoff, dark-cyan=specialist, dark-red=failed,")
    lines.append("dashed=retired/abandoned, gold ring=active inheritance frontier.")
    lines.append("`SCOUT` = exploratory (observations only - never frontier, never a record);")
    lines.append("`scale->N#`/`confirm->N#` = verbatim kernel copy of that node (scaling follow-up /")
    lines.append("confirmatory re-run).")
    lines.append("`inherit` = legal exploit parent. `perf` = non-dominated observed measurement, which a")
    lines.append("judged-against verdict does not remove: those nodes are legal reform/hybrid parents.")
    lines.append("Interactive version: `.evo/views/DASHBOARD.html` (open in a browser).")
    lines.append("")
    lines.append("```mermaid")
    lines.append("graph LR")
    for c in _MERMAID_CLASSES:
        lines.append(f"  {c}")
    by_class: dict[str, list[str]] = {}
    for n in g.get("nodes", []):
        sc = primary_score(n, primary)
        bits = [n["id"], n.get("role", "?"), level_label(n)]
        if n.get("experiment_purpose") == "targeted_ablation":
            bits.append("ABLATION")
        if str(n.get("experiment_purpose") or "") in econfig.EXPLORATORY_PURPOSES:
            bits.append("SCOUT")
        if n.get("scaling_followup_of"):
            bits.append(f"scale->{n['scaling_followup_of']}")
        if n.get("confirmatory_of"):
            bits.append(f"confirm->{n['confirmatory_of']}")
        intent = lane_intent.get(n.get("lane") or "")
        if intent:
            bits.append(intent)
        if sc is not None:
            bits.append(f"{primary} {sc}")
        elif n.get("status") not in ("concluded", "abandoned"):
            bits.append(n.get("status", "?"))
        label = " &middot; ".join(str(b).replace('"', "'") for b in bits)
        lines.append(f'  {n["id"]}["{label}"]')
        by_class.setdefault(_mermaid_class(n), []).append(n["id"])
    for n in g.get("nodes", []):
        for p in n.get("parents", []):
            if p in idx:
                style = "-.->" if idx[p].get("role") == "platform" else "-->"
                lines.append(f"  {p} {style} {n['id']}")
    for cls, ids in sorted(by_class.items()):
        lines.append(f"  class {','.join(ids)} {cls}")
    if frontier_ids:
        lines.append(f"  class {','.join(sorted(frontier_ids))} frontier")
    lines.append("```")
    lines.append("")
    lines.append("| id | title | role | purpose | scope | intent | gen | round | parents | status | verdict | "
                 + (primary or "primary") + " | inherit | perf | science | retired |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for n in sorted(g.get("nodes", []), key=lambda x: x["id"]):
        sc = primary_score(n, primary)
        lines.append(
            f"| {n['id']} | {_mdcell(n.get('title',''))} | {n.get('role','')} | {n.get('experiment_purpose','')} | {level_label(n)} | "
            f"{lane_intent.get(n.get('lane') or '') or '-'} | {gens.get(n['id'],0)} | {n.get('round') or '-'} | "
            f"{','.join(n.get('parents',[])) or '-'} | {n.get('status','')} | "
            f"{n.get('verdict') or '-'} | {sc if sc is not None else '-'} | "
            f"{'yes' if n['id'] in frontier_ids else '-'} | "
            f"{'yes' if n['id'] in performance_ids else '-'} | "
            f"{n.get('scientific_promotion_status') or '-'} | {n.get('retire_reason') or '-'} |"
        )
    eutil.write_text(store.views_dir() / "GRAPH.md", "\n".join(cycle_note + lines) + "\n")

    eutil.write_text(store.views_dir() / "FRONTIER.md",
                     "\n".join(cycle_note + _frontier_view(g, cfg, st)) + "\n")


def _frontier_view(g: dict, cfg: dict, st: dict | None = None) -> list[str]:
    """Four honest layers instead of one filtered list.

    Origin (where the user started, permanent), observed performance (what the
    project actually measured), inheritance (what may legally be built on), and
    the measured-but-unsettled remainder, which is search material rather than
    ancestry.  A single list conflated all four and showed only the last.
    """
    primary = econfig.primary_metric(cfg)
    floor_rows = []
    for c in decision_cells(cfg):
        cid = str(c.get("id") or "")
        src = econfig.noise_floor_source(cfg, cid, st)
        if src != "none":
            floor_rows.append(f"{cid}={econfig.noise_floor(cfg, cid, st):g} ({src})")
    fr = frontier(g, cfg, st)
    fr_ids = {n["id"] for n in fr}
    perf_full = performance_frontier(g, cfg, st)
    perf = collapse_equivalent_tips(perf_full, cfg, st)
    perf_ids = {n["id"] for n in perf_full}
    records = cell_records(g, cfg)
    idx_all = by_id(g)
    eligible_pool = [n for n in g.get("nodes", []) if observation_eligible(n, cfg)]
    holders: dict[str, list[str]] = {}
    for row in records:
        # Same "?" provisional tag the bundle block prints - one question, one
        # answer on every surface (final audit C11/L30).
        holder_n = idx_all.get(row["node"]) or {}
        tag = "?" if provisional_record(
            holder_n, [n for n in eligible_pool if n.get("id") != row["node"]],
            cfg, cell_id=row["cell"], st=st) else ""
        holders.setdefault(row["node"], []).append(row["cell"] + tag)
    out = ["# Frontiers (generated; do not edit)", ""]
    if floor_rows:
        out.append("Noise floors in force (observed = engine-measured seed spread, preplanned mode;")
        out.append("config = literature/user value from the evaluation contract): " + ", ".join(floor_rows))
        out.append("")

    origin = origin_node(g)
    out.append("## Origin")
    out.append("")
    out.append("The user's starting program: permanent comparator and provenance. It is never")
    out.append("retired; leaving a frontier only means it is no longer the thing to build on.")
    out.append("")
    if origin is None:
        out.append("- not yet established")
    else:
        out.append(f"- {origin['id']} '{_mdcell(origin.get('title',''))}' status={origin.get('status')} "
                   f"{primary}={primary_score(origin, primary)}")
        out.append(f"  - results: {result_vector(origin, cfg)}")
        out.append(f"  - resources: {resource_vector(origin, cfg)}")
    out.append("")

    out.append("## Observed performance frontier (measurement only)")
    out.append("")
    out.append("Non-dominated measured vectors. A verdict judged against a node's own parent")
    out.append("does not remove it here - these are the numbers the project holds today.")
    out.append("")
    out.append("| id | title | role | scope | verdict | science | " + (primary or "primary")
               + " | cell records | inherit |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for n in perf:
        out.append(
            f"| {n['id']} | {_mdcell(n.get('title',''))} | {n.get('role','')} | {level_label(n)} | "
            f"{n.get('verdict') or '-'} | {n.get('scientific_promotion_status') or '-'} | "
            f"{primary_score(n, primary)} | {','.join(holders.get(n['id'], [])) or '-'} | "
            f"{'yes' if n['id'] in fr_ids else '-'} |")
    if not perf:
        out.append("| - | no concluded measured node yet | | | | | | | |")
    out.append("")

    out.append("## Active inheritance frontier (legal exploit parents)")
    out.append("")
    if econfig.is_research(cfg):
        out.append("Research mode: performance non-domination AND a settled frozen M/E/T claim.")
    else:
        out.append("Engineering mode: the observed performance frontier is inherited directly.")
    if frontier_is_origin_floor(g, cfg, st):
        retired = retired_settled_ids(g, cfg)
        if retired:
            shown = ", ".join(retired[:6]) + (f" +{len(retired) - 6} more" if len(retired) > 6 else "")
            out.append(f"**Retirement floor**: settled lineages exist but were retired ({shown}), so")
            out.append("the origin is the only legal exploit parent right now. NOT a cold start:")
            out.append("revive one ('evo revive --node N### --note ...') or root a new lineage.")
        else:
            out.append("**Floor in force**: no node has a settled claim yet, so the origin is the only")
            out.append("legal exploit parent. This is a cold-start fallback, not an endorsement - a")
            out.append("reform/hybrid lane on a measured-but-unsettled node below is usually stronger.")
    out.append("")
    out.append("| id | title | role | purpose | scope | " + (primary or "primary")
               + " | descendants | improved desc | best desc |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for n in fr:
        r = n.get("rollup") or {}
        out.append(
            f"| {n['id']} | {_mdcell(n.get('title',''))} | {n.get('role','')} | {n.get('experiment_purpose','candidate')} | {level_label(n)} | "
            f"{primary_score(n, primary)} | {r.get('descendants', 0)} | {r.get('descendants_improved', 0)} | "
            f"{r.get('best_descendant_primary') if r.get('best_descendant_primary') is not None else '-'} |")
    out.append("")

    out.append("## Measured but not inheritable")
    out.append("")
    out.append("Real numbers that are not a legal exploit parent - dominated, unsettled, or")
    out.append("judged against. Still a legal reform or hybrid parent, and the right material")
    out.append("for a repair lane - EXCEPT rows marked (archived), which no new lane may")
    out.append("consume until the user runs 'evo revive --node N### --note ...'. A trailing ?")
    out.append("on a record cell = provisional (lead within the cell's noise floor).")
    out.append("")
    out.append("| id | title | verdict | science | effect | mechanism | " + (primary or "primary")
               + " | cell records | on perf frontier |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    unsettled = [n for n in g.get("nodes", [])
                 if observation_eligible(n, cfg) and n["id"] not in fr_ids]
    for n in sorted(unsettled, key=lambda x: str(x["id"])):
        out.append(
            f"| {n['id']}{f" ({n.get('retire_reason')} - revive first)" if str(n.get('retire_reason') or '') in ('archived', 'pruned') else ''} | "
            f"{_mdcell(n.get('title',''))} | {n.get('verdict') or '-'} | "
            f"{n.get('scientific_promotion_status') or '-'} | {n.get('effect_contract_status') or '-'} | "
            f"{n.get('mechanism_status') or '-'} | {primary_score(n, primary)} | "
            f"{','.join(holders.get(n['id'], [])) or '-'} | "
            f"{'yes' if n['id'] in perf_ids else '-'} |")
    if not unsettled:
        out.append("| - | none | | | | | | | |")
    out.append("")

    out.append("## Instrumental work (no novelty claim)")
    out.append("")
    out.append("Repairs and probes never earn promotion - but a repaired base IS what later lanes")
    out.append("execute on, and a probe's numbers are real. This layer keeps both visible. Whether")
    out.append("a row also competes as a tip is stated per row rather than assumed from its")
    out.append("purpose: probes and repairs are always excluded, while a targeted ablation is")
    out.append("excluded only under preplanned replication, so under record_only its measurement")
    out.append("does stand in the layers above.")
    out.append("")
    out.append("| id | title | purpose | " + (primary or "primary")
               + " | competes as a tip | parity | recovered headroom | stands in for |")
    out.append("|---|---|---|---|---|---|---|---|")
    instrumental = [n for n in g.get("nodes", [])
                    if n.get("experiment_purpose") in econfig.INSTRUMENTAL_PURPOSES
                    and n.get("status") == "concluded"]
    idx_now = by_id(g)
    for n in sorted(instrumental, key=lambda x: str(x["id"])):
        gain = n.get("maintenance_gain") or {}
        gain_txt = ", ".join(f"{cid} {row.get('delta'):+g}" for cid, row in sorted(gain.items())
                             if isinstance(row, dict)
                             and isinstance(row.get("delta"), (int, float))) or "-"
        # Read the same predicate the frontier itself reads, so the table can
        # never claim an exclusion the selection logic did not apply.
        competes = "-" if instrumental_frontier_excluded(n, cfg) else "yes"
        stands_in = effective_frontier_ancestor(idx_now, str(n["id"]))
        if n.get("experiment_purpose") != "maintenance":
            stands_in = "-"   # only maintenance is frontier-transparent
        out.append(
            f"| {n['id']} | {_mdcell(n.get('title',''))} | {n.get('experiment_purpose')} | "
            f"{primary_score(n, primary)} | {competes} | {n.get('maintenance_parity') or '-'} | "
            f"{gain_txt} | {stands_in} |")
    if not instrumental:
        out.append("| - | none | | | | | | |")
    out.append("")

    scouts = [n for n in g.get("nodes", [])
              if str(n.get("experiment_purpose") or "") in econfig.EXPLORATORY_PURPOSES
              and n.get("status") == "concluded"]
    out.append("## Exploratory scouts (observations only)")
    out.append("")
    out.append("Declared reconnaissance: full candidate route, but the numbers below can never")
    out.append("enter a frontier or hold a record, and promotion is not_applicable by")
    out.append("construction. Their currency is the OB### observations they banked - a")
    out.append("confirmatory candidate (confirmatory_of) must reproduce an effect under full")
    out.append("rigor before it counts.")
    out.append("")
    out.append("| id | title | verdict | " + (primary or "primary") + " | confirmed by |")
    out.append("|---|---|---|---|---|")
    # R7 audit: "confirmed by" is a settlement claim - a planned, failed or
    # abandoned confirmatory child must render as an attempt with its true
    # state, never as a confirmation. And a pruned scout's door needs revival.
    confirms: dict[str, str] = {}
    for n in g.get("nodes", []):
        src = str(n.get("confirmatory_of") or "")
        if not src:
            continue
        if n.get("status") == "concluded" and n.get("verdict") in (
                "improved", "noninferior", "dominant", "specialist", "promising"):
            confirms[src] = str(n["id"])
        else:
            confirms.setdefault(
                src, f"attempt {n['id']} ({n.get('status')}"
                     + (f"/{n.get('verdict')}" if n.get("verdict") else "") + ")")
    for n in sorted(scouts, key=lambda x: str(x["id"])):
        if n.get("retire_reason") == "pruned":
            cell = "(pruned - revive first)"
        else:
            cell = confirms.get(str(n["id"])) or "(not yet)"
        out.append(f"| {n['id']} | {_mdcell(n.get('title',''))} | {n.get('verdict') or '-'} | "
                   f"{primary_score(n, primary)} | {cell} |")
    if not scouts:
        out.append("| - | none | | | |")
    out.append("")

    out.append("## Per-cell record holders")
    out.append("")
    out.append("| cell | result_key | role | best observed | node | origin |")
    out.append("|---|---|---|---|---|---|")
    idx_rec = by_id(g)
    # Same pool the record table itself ranks (observation-eligible), not all
    # concluded nodes: judging the lead against frontier-excluded rivals
    # mis-labeled records (R2).
    measured_pool = [n for n in g.get("nodes", [])
                     if n.get("status") == "concluded" and observation_eligible(n, cfg)]
    for row in records:
        origin_value = econfig.result_value(cell_raw(origin, row["result_key"])) \
            if origin is not None else None
        # Winner's-curse disclosure (v11): a record whose winning margin sits
        # inside the recorded noise floor is printed as provisional - the max
        # of N noisy single runs systematically overestimates, and this is
        # where that max becomes the number everyone compares against next.
        holder = idx_rec.get(str(row.get("node")))
        tag = ""
        if holder is not None and provisional_record(holder, measured_pool, cfg,
                                                     cell_id=str(row.get("cell") or ""), st=st):
            tag = " (provisional: margin inside noise floor)"
        out.append(f"| {row['cell']} | {row['result_key']} | {row['role']} | {row['value']:g} | "
                   f"{row['node']}{tag} | {'-' if origin_value is None else f'{float(origin_value):g}'} |")
    if not records:
        out.append("| - | no measured cell yet | | | | |")
    out.append("")

    out.append("## Platforms")
    out.append("")
    out.append("| id | title | status | verdict |")
    out.append("|---|---|---|---|")
    for n in platforms(g):
        out.append(f"| {n['id']} | {_mdcell(n.get('title',''))} | {n.get('status','')} | {n.get('verdict') or '-'} |")
    return out
