"""Context bundle builder: the engine assembles, per task, exactly the context the
role needs — input file list, injected lessons, sibling failures, frontier stats,
prior attempt errors, critic feedback. The agent reads the bundle instead of
remembering the project."""
from __future__ import annotations

import hashlib
import re

import eutil
import econfig
import egraph
import estore


def _lesson_lines(lessons: list[dict]) -> list[str]:
    out = []
    for l in lessons:
        out.append(
            f"- [{l.get('id')}] ({l.get('scope')}, from {l.get('node') or '?'} {l.get('round') or ''}) "
            f"{l.get('statement')} => {l.get('recommendation')}"
        )
    return out


def knowledge_is_active(st: dict, ref: str) -> bool:
    return estore.Store.knowledge_is_active(st, ref)


def select_lessons(store, g: dict, cfg: dict, *, parents: list[str], tags: list[str],
                   st: dict | None = None) -> list[dict]:
    """Route only active global, lineage, and tag-matched conditional lessons.

    Crash-ghost filtering (rows beyond the committed counter) lives in ONE
    place - ``estore.Store._committed_journal_rows`` via ``store.lessons(st)``
    - so this path and ``build_bundle`` cannot drift apart again (the r6 fix
    landed here while the production bundle path stayed unfiltered)."""
    if st is None:
        try:
            st = store.load_state()
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            st = {}
    matched, global_rows = _lesson_partition(store.lessons(st), g, st, parents=parents, tags=tags)
    cap = int(cfg.get("budgets", {}).get("max_lesson_items_in_bundle", 12))
    return (matched + global_rows)[:cap]


def _lesson_partition(all_lessons: list[dict], g: dict, st: dict,
                      *, parents: list[str], tags: list[str]) -> tuple[list[dict], list[dict]]:
    """(lineage/tag-matched lessons, global lessons), each newest-first.

    R7 multi-round audit: relevance outranks recency. An exact-lineage (or
    tag-matched) lesson is the one specific to THIS task's parents; twelve
    newer globals used to evict it silently and the agent then repeated a
    recorded failure. Matched lessons are pinned before globals."""
    lineage_nodes = set(parents)
    for p in parents:
        lineage_nodes.update(egraph.ancestors(g, p))
    matched: list[dict] = []
    global_rows: list[dict] = []
    for l in reversed(all_lessons):  # newest first
        if not estore.Store.knowledge_is_active(st, str(l.get("id") or "")):
            continue
        scope = l.get("scope")
        if scope == "lineage" and l.get("node") in lineage_nodes:
            matched.append(l)
        elif scope == "conditional" and set(l.get("tags") or []) & set(tags):
            matched.append(l)
        elif scope == "global":
            global_rows.append(l)
    return matched, global_rows


def errors_block(store, cfg: dict, *, node: str | None = None,
                 st: dict | None = None) -> list[str]:
    """Execution-error journal routed into implement/train tasks: the same node's
    past failures first, then recent failures anywhere (platform-level lessons)."""
    cap = int(cfg.get("budgets", {}).get("max_error_items_in_bundle", 8))
    recs = store.error_records(st)
    picked: list[dict] = []
    picked_ids: set[str] = set()
    for r in reversed(recs):
        if node and r.get("node") == node:
            picked.append(r)
            picked_ids.add(str(r.get("id")))
        if len(picked) >= cap:
            break
    for r in reversed(recs):
        if str(r.get("id")) not in picked_ids:
            picked.append(r)
            picked_ids.add(str(r.get("id")))
        if len(picked) >= cap:
            break
    out = []
    for r in picked:
        out.append(f"- [{r.get('id')}] node {r.get('node')} stage {r.get('stage') or '-'} "
                   f"(run {r.get('run') or '-'}): {r.get('note') or 'no note recorded'}")
    if len(recs) > len(picked):
        # R7 audit: silent truncation read as "this is everything"
        out.append(f"- (+{len(recs) - len(picked)} older execution errors omitted; full journal at "
                   "`.evo/errors.jsonl` - grep your failing surface/command)")
    return out


def playbook_block(store, cfg: dict, st: dict | None = None) -> list[str]:
    """Platform playbook: infrastructure fixes that WORKED here, routed by
    surface into every execution-bearing bundle regardless of lineage (infra
    knowledge is platform-shaped, not ancestry-shaped - v10.2). Latest fix
    per surface wins; capped like the error journal."""
    cap = int(cfg.get("budgets", {}).get("max_error_items_in_bundle", 8))
    failures = {str(r.get("id")): r for r in store.error_records(st)}
    # Keep DISTINCT fixes, newest first - not one row per surface.  Collapsing
    # to the latest per surface silently evicted still-necessary knowledge the
    # moment a second, unrelated problem hit the same coarse bucket (two
    # different services both land in `launch`), recreating exactly the
    # knowledge loss this block exists to prevent.  Identical fix texts within
    # a surface still collapse, so a repeated ritual is stated once.
    fixed = [row for row in reversed(store.error_resolutions(st))
             if row.get("disposition") == "fixed" and str(row.get("fix") or "")]

    def line(row: dict) -> str:
        failure = failures.get(str(row.get("resolves") or ""), {})
        return (f"- [{row.get('surface') or 'other'}] {row.get('fix')}"
                f" (fixed {row.get('resolves')} on node {row.get('node')}"
                f"{': ' + str(failure.get('note'))[:80] if failure.get('note') else ''})")

    # Two passes so coverage is guaranteed before depth: pass 1 takes the
    # newest fix per surface (a flood of artifact_io fixes can no longer push
    # the single launch fix out of every bundle), pass 2 spends the remaining
    # budget on other distinct fixes, newest first.
    seen: set[tuple[str, str]] = set()
    covered: set[str] = set()
    out: list[str] = []
    for row in fixed:
        surface = str(row.get("surface") or "other")
        if surface in covered or len(out) >= cap:
            continue
        covered.add(surface)
        seen.add((surface, eutil.norm_ws(str(row.get("fix")))))
        out.append(line(row))
    for row in fixed:
        if len(out) >= cap:
            break
        key = (str(row.get("surface") or "other"), eutil.norm_ws(str(row.get("fix"))))
        if key in seen:
            continue
        seen.add(key)
        out.append(line(row))
    total_distinct = len({(str(r.get("surface") or "other"), eutil.norm_ws(str(r.get("fix"))))
                          for r in fixed})
    if total_distinct > len(out):
        # R7 audit: once all eight coarse surfaces have one fix each, a second
        # still-necessary fix in any surface could never survive the cap - and
        # nothing said so. Disclose; the journal keeps every validated fix.
        out.append(f"- (+{total_distinct - len(out)} more validated fixes omitted; full journal at "
                   "`.evo/errors.jsonl` - grep your failing surface/command)")
    return out


def prior_wiring_block(store, g: dict, *, limit: int = 3) -> list[str]:
    """How the most recent implemented nodes wired their artifact I/O (v10.2):
    the engine extracts READS:/WRITES: rows from prior BUILD_REPORTs so a new
    implement task starts from working point-of-use knowledge instead of
    re-deriving the platform's load/save ritual from scratch."""
    import evalid
    rows: list[str] = []
    contributing = 0
    # Walk newest-first over ALL implemented nodes and count only the ones that
    # actually contribute rows: eval-only nodes (every diagnostic_probe by
    # design) have no stages and therefore no wiring section, so a fixed
    # newest-N slice could spend its whole budget on empty reports and hand
    # the next implementer nothing.
    nodes = [n for n in g.get("nodes", [])
             if int(n.get("implementation_revision") or 0) > 0
             and n.get("status") != "abandoned"]
    for node in sorted(nodes, key=lambda n: str(n.get("id")), reverse=True):
        if contributing >= limit:
            break
        report = eutil.rpath(store.repo, f".evo/nodes/{node.get('id')}/BUILD_REPORT.md")
        if not report.is_file():
            continue
        text = eutil.read_text(report)
        wiring = eutil.find_section(eutil.md_sections(text), "artifact wiring") or ""
        found = evalid.ARTIFACT_READ_ROW.findall(wiring) + evalid.ARTIFACT_WRITE_ROW.findall(wiring)
        if not found:
            continue
        contributing += 1
        for token, rel, snippet in found[:6]:
            rows.append(f"- {node.get('id')}: {token} -> {rel} :: {snippet[:90]}")
    return rows


def sibling_summary(g: dict, parents: list[str], primary: str) -> list[str]:
    out = []
    for n in egraph.siblings(g, parents):
        sc = egraph.primary_score(n, primary)
        out.append(
            f"- {n['id']} '{n.get('title','')}' ({egraph.level_label(n)}, purpose={n.get('experiment_purpose') or 'candidate'}, "
            f"{n.get('status')}, verdict={n.get('verdict') or '-'}, "
            f"{primary}={sc if sc is not None else '-'}) idea: {n.get('idea_doc') or '-'}"
        )
    return out


# The full list always lives in GRAPH.md; the bundle shows the most decision-
# relevant slice so the strategy block stays readable in a long project.
UNSETTLED_ROWS = 16


def _settlement_gaps(node: dict, limit: int = 3) -> str:
    """Every row keeping an otherwise-promotable node unsettled.

    The frozen effect contract is only one of the places a node can be left
    undecided: an uncertain required target or guardrail cell is settled against
    the node's own parent, and the mechanism probe and fidelity audit are
    settled elsewhere again.  Reading only the contract printed nodes as
    unsettled "because:" nothing at all.
    """
    summary = node.get("evaluation_summary") or {}
    gaps = [str(x) for x in ((summary.get("effect_contract") or {}).get("evidence_gaps") or [])]
    for key, label in (("required_target_uncertain", "required target cell"),
                       ("guardrail_uncertain", "guardrail cell"),
                       ("required_group_uncertain", "required task group")):
        for cid in (summary.get(key) or []):
            gaps.append(f"{label} {cid} undecided against this node's own comparator")
    if node.get("mechanism_status") not in (None, "confirmed", "not_applicable"):
        gaps.append(f"mechanism probe {node.get('mechanism_status')}")
    if node.get("needs_fidelity") and node.get("fidelity_pending"):
        gaps.append("implementation-fidelity audit outstanding")
    if not gaps:
        return ""
    shown = "; ".join(gaps[:limit])
    return shown + (f" (+{len(gaps) - limit} more)" if len(gaps) > limit else "")


def tombstones_block(store) -> list[str]:
    """v11.2: published-territory tombstones for the ROUND STRATEGIST.

    This block never reaches a generator directly. The strategist quotes a
    criterion into an overlapping lane's forbidden moves (with the
    kernel-vs-component semantics); reviewer notes are reference material and
    must never be copied into briefs - a note worth pursuing becomes an
    explicit lane goal, authored and accountable, not a whisper."""
    rows = [r for r in eutil.read_jsonl(eutil.rpath(store.repo, ".evo/evidence/TOMBSTONES.jsonl"),
                                        lenient=True)
            if isinstance(r, dict)]
    if not rows:
        return []
    out = [
        "Project-confirmed published territory (from collision deaths). Each criterion bounds",
        "what ONE published work absorbs; beyond it the tombstone asserts nothing - a direction",
        "can never die here, only an equivalence class of variants.",
        "Semantics: illegal as a claimed novelty kernel, LEGAL as a known component/support shell",
        "(published means it works - it just cannot be the flag).",
        "Your duty: where a lane's goal overlaps a criterion, quote that criterion into the",
        "lane's brief under 'forbidden moves' TOGETHER with the semantics line above. Never copy",
        "reviewer notes into a brief; if a note points somewhere worth going, commission an",
        "explicit lane with that goal instead.",
    ]
    recent = rows[-20:]
    if len(rows) > len(recent):
        out.append(f"- ({len(rows) - len(recent)} older tombstones omitted; full ledger at "
                   "`.evo/evidence/TOMBSTONES.jsonl`)")
    for r in recent:
        c = r.get("context") or {}
        out.append(f"- {r.get('id')} [{','.join(c.get('bottlenecks') or []) or '-'} | "
                   f"{c.get('intent')}/{c.get('search_origin')} {c.get('round')}]: {r.get('criterion')}")
        if r.get("note"):
            out.append(f"  - reviewer note (reference only, never into briefs): {r['note']}")
    out.append("A criterion is ONE work's absorption boundary, never a direction ban: if one reads")
    out.append("broader than a single published work could absorb, quote it verbatim anyway and treat")
    out.append("the overflow as open territory - never expand a criterion in your own words.")
    return out


def tombstones_reviewer_block(store) -> list[str]:
    """v11.2: the tombstone ledger as a CRITIC reference (tournament/red team).

    Two jobs: (a) a collision kill that re-hits bounded territory cites the
    TB id instead of authoring a near-duplicate criterion; (b) an author of a
    NEW criterion sees existing ones and calibrates narrowness. Critics are
    post-freeze readers and the criteria are anonymous by construction, so
    this shows nothing a collision audit has not already surfaced."""
    rows = [r for r in eutil.read_jsonl(eutil.rpath(store.repo, ".evo/evidence/TOMBSTONES.jsonl"),
                                        lenient=True)
            if isinstance(r, dict)]
    if not rows:
        return []
    out = [
        "Known published-territory tombstones. When a collision kill re-hits territory a",
        "criterion below already bounds, REFERENCE it (tournament: published_dup.known_tombstone;",
        "red team: `TOMBSTONE: TB###`) instead of authoring a near-duplicate. When authoring a",
        "NEW criterion, bound the NARROWEST equivalence class the published work actually",
        "absorbs - one work's absorption, never a direction.",
    ]
    recent = rows[-20:]
    if len(rows) > len(recent):
        out.append(f"- ({len(rows) - len(recent)} older tombstones omitted; full ledger at "
                   "`.evo/evidence/TOMBSTONES.jsonl`)")
    out.extend(f"- {r.get('id')}: {r.get('criterion')}" for r in recent)
    return out


def frontier_block(g: dict, cfg: dict, st: dict | None = None) -> list[str]:
    """Four layers, because one filtered list answers only one of four questions.

    Where did we start, what have we actually measured, what may we legally
    build on, and what real result is still unsettled?  A strategist told only
    the last one plans against a graph it cannot see: the node holding every
    cell record is invisible precisely when its claim was judged against.
    """
    primary = econfig.primary_metric(cfg)
    fr = egraph.frontier(g, cfg, st)
    fr_ids = {n["id"] for n in fr}
    all_perf = egraph.performance_frontier(g, cfg, st)
    perf = egraph.collapse_equivalent_tips(all_perf, cfg, st)   # display only
    perf_ids = {n["id"] for n in all_perf}
    idx = egraph.by_id(g)
    eligible = [n for n in g.get("nodes", []) if egraph.observation_eligible(n, cfg)]
    holders: dict[str, list[str]] = {}
    records = egraph.cell_records(g, cfg)
    for row in records:
        # v11.1 P6: the winner's-curse label travels with the record row here
        # too, not only in FRONTIER.md - the strategist reads THIS block.
        holder = idx.get(row["node"]) or {}
        tag = "?" if egraph.provisional_record(
            holder, [n for n in eligible if n.get("id") != row["node"]],
            cfg, cell_id=row["cell"], st=st) else ""
        holders.setdefault(row["node"], []).append(row["cell"] + tag)

    origin = egraph.origin_node(g)
    out = ["Origin (the user's starting program; permanent comparator, never retired):"]
    if origin is None:
        out.append("- not yet established")
    else:
        out.append(f"- {origin['id']} '{origin.get('title','')}' {primary}="
                   f"{egraph.primary_score(origin, primary)} | {egraph.result_vector(origin, cfg)}")

    out.append("Observed performance frontier (measurement only; a verdict judged against a node's")
    out.append("own parent does not remove it - these are the numbers this project holds).")
    out.append("A trailing ? on a record cell = provisional: the lead over the best rival is")
    out.append("smaller than that cell's noise floor, so treat the record as within-noise:")
    for n in perf:
        out.append(
            f"- {n['id']} '{n.get('title','')}' role={n.get('role')} {egraph.level_label(n)} "
            f"verdict={n.get('verdict') or '-'} science={n.get('scientific_promotion_status') or '-'} "
            f"{primary}={egraph.primary_score(n, primary)} "
            f"records={','.join(holders.get(n['id'], [])) or 'none'} "
            f"inheritable={'yes' if n['id'] in fr_ids else 'no'}")
        out.append(f"    results {egraph.result_vector(n, cfg)}")
    if not perf:
        out.append("- none yet")

    out.append("Active inheritance frontier (legal exploit parents"
               + ("; research mode also requires the frozen M/E/T settlement):"
                  if econfig.is_research(cfg) else "):"))
    for n in fr:
        r = n.get("rollup") or {}
        out.append(
            f"- {n['id']} '{n.get('title','')}' role={n.get('role')} "
            f"purpose={n.get('experiment_purpose') or 'candidate'} {egraph.level_label(n)} "
            f"{primary}={egraph.primary_score(n, primary)} "
            f"descendants={r.get('descendants',0)} improved_descendants={r.get('descendants_improved',0)} "
            f"best_descendant_display={r.get('best_descendant_primary')}")
    if egraph.frontier_is_origin_floor(g, cfg, st):
        retired = egraph.retired_settled_ids(g, cfg)
        if retired:
            shown = ", ".join(retired[:6]) + (f" +{len(retired) - 6} more" if len(retired) > 6 else "")
            out.append(f"- RETIREMENT FLOOR: settled lineages exist but were retired ({shown}) - the")
            out.append("  origin is the only legal exploit parent right now. NOT a cold start: revive")
            out.append("  one ('evo revive --node N### --note ...') or root a new lineage.")
        else:
            out.append("- FLOOR IN FORCE: nothing has a settled claim yet, so the origin is the only legal")
            out.append("  exploit parent. Cold-start fallback, not an endorsement - a reform or hybrid lane")
            out.append("  on a measured-but-unsettled node below is usually the stronger bet.")
            out.append("  If the right next step is a SMALL follow-on and the reform scope floor blocks it,")
            out.append("  the designed lever is lowering config scope_floor.reform for this project (a user")
            out.append("  decision at configure/preset level) - settling the named claim gap re-opens")
            out.append("  exploit properly; do not force a bigger change than the science calls for.")
    elif not fr:
        out.append("- empty (no legal exploit parent; use reform/hybrid/root lanes)")

    unsettled = [n for n in g.get("nodes", [])
                 if egraph.observation_eligible(n, cfg) and n["id"] not in fr_ids]
    direction = econfig.result_direction(cfg, primary)
    def salience(n: dict) -> tuple:
        score = egraph.primary_score(n, primary)
        return (n["id"] not in perf_ids, not holders.get(n["id"]),
                float("inf") if score is None else (-score if direction == "max" else score),
                str(n["id"]))
    ranked = sorted(unsettled, key=salience)
    shown, hidden = ranked[:UNSETTLED_ROWS], ranked[UNSETTLED_ROWS:]
    out.append("Measured but not inheritable (real numbers, unsettled or judged-against claim;")
    out.append("legal reform/hybrid parents and prime repair material - not exploit parents.")
    out.append("EXCEPTION: rows marked (archived) are retired and NOT legal parents for any new")
    out.append("lane until the user revives them: 'evo revive --node N### --note ...'):")
    for n in shown:
        gaps = _settlement_gaps(n)
        out.append(
            f"- {n['id']}{f" ({n.get('retire_reason')} - revive first)" if str(n.get('retire_reason') or '') in ('archived', 'pruned') else ''} "
            f"'{n.get('title','')}' verdict={n.get('verdict') or '-'} "
            f"science={n.get('scientific_promotion_status') or '-'} "
            f"effect={n.get('effect_contract_status') or '-'} "
            f"mechanism={n.get('mechanism_status') or '-'} "
            f"{primary}={egraph.primary_score(n, primary)} "
            f"records={','.join(holders.get(n['id'], [])) or 'none'} "
            f"on_performance_frontier={'yes' if n['id'] in perf_ids else 'no'}"
            + (f" | unsettled because: {gaps}" if gaps else ""))
    if hidden:
        # Never truncate silently: a strategist who cannot see the cut cannot
        # know the list was a sample rather than the whole graph.
        out.append(f"- (+{len(hidden)} more measured-but-unsettled nodes not shown: "
                   f"{', '.join(str(n['id']) for n in hidden[:20])}"
                   f"{' ...' if len(hidden) > 20 else ''}; ranked by performance-frontier "
                   f"membership, then cell records, then {primary}. GRAPH.md lists all of them.)")
    if not unsettled:
        out.append("- none")

    out.append("Per-cell record holders (best observed value on each decision cell):")
    for row in records:
        origin_value = econfig.result_value(egraph.cell_raw(origin, row["result_key"])) \
            if origin is not None else None
        holder_node = idx.get(row["node"]) or {}
        tag = "?" if egraph.provisional_record(
            holder_node, [n for n in eligible if n.get("id") != row["node"]],
            cfg, cell_id=row["cell"], st=st) else ""
        out.append(f"- {row['cell']}{tag} {row['result_key']} ({row['role']}): {row['value']:g} by "
                   f"{row['node']} | origin "
                   + ("-" if origin_value is None else f"{float(origin_value):g}"))
    if not records:
        out.append("- none measured yet")

    plats = egraph.platforms(g)
    if plats:
        out.append("Platforms (consumable infrastructure):")
        for n in plats:
            out.append(f"- {n['id']} '{n.get('title','')}' status={n.get('status')} verdict={n.get('verdict') or '-'}")
    return out


def promotion_reference_block(g: dict, cfg: dict, st: dict | None = None) -> list[str]:
    """Compact observed result/resource Pareto rows, never effect comparators."""
    out = [
        "- These N# rows are observed promotion evidence, not legal values for "
        "effect_case.comparator_id.",
        "- Each row is one complete observed result/resource vector on the performance Pareto frontier. "
        "Judge the candidate's frozen claim scope and verify protocol comparability; do not combine the "
        "best cell from different rows into a fictitious incumbent.",
        "- `generation` reports development age only. Per-node receipts make experimental resources "
        "comparable; they do not pretend that a mature lineage and a first-contact root had equal R&D history.",
    ]
    try:
        generations = egraph.compute_generations(g)
    except ValueError:
        generations = {}
    # Replication-aware eligibility already belongs to the graph policy:
    # preplanned excludes one-run ablations, while record_only may retain a
    # real Pareto ablation measurement as observed (not causal-comparator) data.
    nodes = [n for n in egraph.performance_frontier(g, cfg, st)
             if n.get("status") == "concluded"
             and n.get("resource_receipt_path")
             and str((n.get("resource_receipt_seal") or {}).get("digest") or "")]
    for node in nodes:
        results: list[str] = []
        complete = True
        for cell in econfig.evaluation_cells(cfg):
            if cell.get("role") == "diagnostic":
                continue
            key = str(cell.get("result_key") or "")
            raw = (node.get("score_evidence") or {}).get(key, (node.get("scores") or {}).get(key))
            point, lower, upper = econfig.result_interval(raw)
            if point is None or lower is None or upper is None:
                complete = False
                break
            results.append(f"{cell.get('id')}:{key}={float(point):g}[{float(lower):g},{float(upper):g}]")
        resources: list[str] = []
        realized = node.get("effect_resources_realized") or {}
        for axis in econfig.resource_axes(cfg):
            row = realized.get(axis) if isinstance(realized.get(axis), dict) else {}
            lower, upper = row.get("lower"), row.get("upper")
            if isinstance(lower, bool) or not isinstance(lower, (int, float)) \
                    or isinstance(upper, bool) or not isinstance(upper, (int, float)):
                complete = False
                break
            resources.append(f"{axis}=[{float(lower):g},{float(upper):g}]")
        if not complete:
            continue
        result_doc = str(node.get("result_doc") or
                         f".evo/nodes/{node.get('id')}/NODE_RESULT.md")
        out.append(
            f"- {node.get('id')} generation={generations.get(str(node.get('id')), '?')} "
            f"verdict={node.get('verdict') or '-'}; results {{{'; '.join(results)}}}; "
            f"resources {{{'; '.join(resources)}}}; result "
            f"`{result_doc}`; "
            f"resource receipt `{node.get('resource_receipt_path')}`"
        )
    if not any(line.startswith("- N") for line in out):
        out.append("- No concluded, receipt-backed comparable Pareto observation is available yet; use the "
                   "legal frozen comparator evidence supplied separately.")
    return out


def calibration_block(g: dict) -> list[str]:
    """Prediction calibration ledger: registered predictions vs engine-checked
    outcomes across all concluded nodes - explore/exploit evidence about the
    ideator's own forecasting bias, for the strategist."""
    tot = {"confirmed": 0, "refuted": 0, "inconclusive": 0, "unreached": 0}
    nodes_with = 0
    for n in g.get("nodes", []):
        stt = n.get("prediction_stats") or {}
        if stt:
            nodes_with += 1
            for k in tot:
                tot[k] += int(stt.get(k) or 0)
    if nodes_with == 0:
        return ["- no prediction outcomes recorded yet"]
    tested = tot["confirmed"] + tot["refuted"] + tot["inconclusive"]
    registered = tested + tot["unreached"]
    out = [f"- {nodes_with} concluded nodes, {registered} registered predictions: "
           f"{tot['confirmed']} confirmed / {tot['refuted']} refuted / "
           f"{tot['inconclusive']} inconclusive / {tot['unreached']} unreached"]
    if tested:
        rate = tot["confirmed"] / tested
        out.append(f"- all-history confirmation rate {rate:.0%} over {tested} reached predictions: "
                   + ("predictions look sandbagged - demand more aggressive kill thresholds" if rate > 0.9
                      else "forecasts are systematically optimistic - discount promised gains" if rate < 0.4
                      else "calibration is in a healthy band"))
        # R7 audit: a large early cohort can dominate the pooled rate for many
        # rounds after the forecasting regime changed; show the recent cohort
        # separately so the strategist sees when the two disagree. (The advice
        # line above is ALL-HISTORY; when the cohorts diverge, weigh recent.)
        # R9 (external audit r6): order by the persisted conclusion sequence, not
        # by graph insertion order - a later-created node routinely concludes
        # first (parallel lanes, slow external RUNs), which silently inverted
        # "recent". Legacy nodes without the field sort first (oldest-known).
        with_stats = [n for n in g.get("nodes", []) if n.get("prediction_stats")]
        recent_nodes = sorted(with_stats, key=lambda n: int(n.get("conclusion_seq") or 0))[-5:]
        r_tot = {"confirmed": 0, "refuted": 0, "inconclusive": 0}
        for n in recent_nodes:
            stt = n.get("prediction_stats") or {}
            for k in r_tot:
                r_tot[k] += int(stt.get(k) or 0)
        r_tested = sum(r_tot.values())
        if r_tested and len(recent_nodes) < nodes_with:
            r_rate = r_tot["confirmed"] / r_tested
            out.append(f"- recent cohort (last {len(recent_nodes)} concluded nodes with outcomes): "
                       f"{r_rate:.0%} over {r_tested} reached - "
                       + ("diverges from all-history; weigh the recent regime"
                          if abs(r_rate - rate) > 0.25 else "consistent with all-history"))
    else:
        out.append("- no prediction reached evaluation; screened-out nodes do not affect calibration")
    return out


def rounds_history_block(st: dict) -> list[str]:
    out = ["Round history (display result at close; improved is contract/Pareto-level):"]
    for r in st.get("rounds", []):
        status = r.get("projection_status") or "active"
        out.append(f"- {r.get('id')}: best_display={r.get('best_primary')} lanes={r.get('lanes')} "
                   f"improved={r.get('improved')} projection={status}")
        for correction in st.get("round_corrections", []):
            if correction.get("round") == r.get("id"):
                out.append(f"  - correction {correction.get('recovery')}: {correction.get('status')} - "
                           f"{correction.get('reason')}")
    return out or ["- none yet"]


def build_bundle(store, st: dict, cfg: dict, g: dict, task: dict, *, inputs: list[tuple[str, str]],
                 extra_blocks: list[tuple[str, list[str]]] | None = None,
                 lesson_parents: list[str] | None = None,
                 lesson_tags: list[str] | None = None) -> str:
    """Write .evo/tasks/<T>/BUNDLE.md; return its repo-relative path."""
    subj = task.get("subject", {})
    lines: list[str] = []
    lines.append(f"# Bundle for {task['id']} ({task['type']})")
    lines.append("")
    lines.append("## You are here")
    lines.append(f"- project: {cfg.get('project', {}).get('name')} - goal: {cfg.get('project', {}).get('goal')}")
    lines.append(f"- round: {subj.get('round') or st.get('current_round') or '-'} | lane: {subj.get('lane') or '-'} | node: {subj.get('node') or '-'}")
    lines.append(f"- attempt {task.get('attempts', 0) + 1} of {cfg.get('budgets', {}).get('max_attempts', 3)}")
    lines.append("- This bundle is your complete working context. Read the listed files (rows marked "
                 "REFERENCE are conditional fallbacks - each prints its own rule); do not wander the "
                 "repo re-deriving state.")
    lines.append("")
    lines.append("## Read these inputs")
    for path, why in inputs:
        lines.append(f"- `{path}` - {why}")
    if task.get("last_errors"):
        lines.append("")
        lines.append("## Your previous attempt was rejected for these exact deficiencies")
        for e in task["last_errors"]:
            lines.append(f"- {e}")
        lines.append("Fix precisely these; do not regress anything that already passed.")
    lessons: list[dict] = []
    if lesson_parents is not None:
        st_eff = st
        if st_eff is None:
            try:
                st_eff = store.load_state()
            except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
                st_eff = {}
        # st_eff both filters crash ghosts (committed-counter rule) and drives
        # the disposition check - the r6 fix filtered only the dead
        # select_lessons path while THIS production path fed ghosts to agents.
        matched_all, global_all = _lesson_partition(
            store.lessons(st_eff), g, st_eff, parents=lesson_parents, tags=lesson_tags or [])
        cap_l = int(cfg.get("budgets", {}).get("max_lesson_items_in_bundle", 12))
        lessons = (matched_all + global_all)[:cap_l]
        omitted = len(matched_all) + len(global_all) - len(lessons)
        if lessons:
            lines.append("")
            # R7 audit: the old heading promised "repeating a recorded failure
            # is a rejection" - no validator enforces that beyond exact
            # kernel/contract repeats. Say what is true, and disclose the cap.
            lines.append("## Lessons routed to this task (lineage/tag matches first; exact rejected "
                         "contracts cannot be replayed - treat the rest as standing guidance)")
            lines.extend(_lesson_lines(lessons))
            if omitted:
                lines.append(f"- (+{omitted} more active lessons omitted by the bundle cap; "
                             "full ledger at `.evo/lessons.jsonl`)")
    consumed = task.setdefault("consumed_context", {})
    if not isinstance(consumed, dict):
        consumed = {}
        task["consumed_context"] = consumed
    consumed["lesson_ids"] = [str(l.get("id")) for l in lessons if str(l.get("id") or "")]
    # v11.1 T2: a block whose rendered text is BYTE-IDENTICAL to the same-titled
    # block in this subject's PREVIOUS bundle collapses to a one-line reference.
    # Safety rules (binding, from the amnesia audit): only stable-knowledge
    # blocks may collapse (whitelist); execution-critical blocks are always
    # full; the referenced full text stays on disk in the previous bundle; the
    # header rule below tells a cold-started agent to READ anything it is not
    # certain of. Worst case (agent trusts nothing) = today's behavior.
    prev_blocks, prev_rel = _previous_bundle_blocks(store, st, task)
    # Per-stage title variants ("Phenomenon ledger (x)" vs "(y)") used to defeat
    # the title-keyed lookup even for byte-identical bodies; a normalized key
    # (parenthetical stripped) recovers those matches - body equality still
    # decides, so distinct content can never cross-collapse.
    prev_by_norm = {_norm_block_title(t): (t, b) for t, b in prev_blocks.items()}
    referenced_any = False
    for title, block in (extra_blocks or []):
        lines.append("")
        body = "\n".join(block)
        ref_target, src_heading = "", title
        if _REFERENCEABLE_BLOCKS.search(title) and prev_rel:
            digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
            prev_title, prev_body = title, prev_blocks.get(title) or ""
            if not prev_body:
                prev_title, prev_body = prev_by_norm.get(_norm_block_title(title), (title, ""))
            if prev_body == body:
                ref_target, src_heading = prev_rel, prev_title
            else:
                chained = _chain_source(prev_body, digest)
                if chained:
                    # The previous bundle already collapsed this block: chain to
                    # the ORIGINAL full text it points at, so the reference stays
                    # stable instead of alternating full/ref between tasks.
                    ref_target, src_heading = chained
            if ref_target:
                lines.append(f"## {title}")
                lines.append(_reference_line(digest, ref_target, src_heading))
                referenced_any = True
                continue
        lines.append(f"## {title}")
        lines.extend(block)
    if referenced_any:
        # After the "You are here" facts (contiguous "- " lines from index 3),
        # never inside them - splicing mid-block corrupted the location facts.
        pos = 3
        while pos < len(lines) and lines[pos].startswith("- "):
            pos += 1
        lines.insert(pos, "- Some sections below are one-line references to material UNCHANGED "
                          "since this subject's previous bundle; the rule is printed on each. "
                          "Nothing is withheld - every referenced text sits on disk at the "
                          "stated path, and a fresh session MUST read what it has not seen.")
    text = "\n".join(lines) + "\n"
    relp = f".evo/tasks/{task['id']}/BUNDLE.md"
    eutil.write_text(eutil.rpath(store.repo, relp), text)
    return relp


# Stable-knowledge blocks that may collapse to references when byte-identical
# to the previous same-subject bundle. Execution-critical material (playbook,
# wiring, errors, retry directions, gate notes) is deliberately ABSENT: it is
# small and load-bearing, and its repetition is the v10.2 knowledge loop
# working as designed.
_REFERENCEABLE_BLOCKS = re.compile(
    # 'lesson' is deliberately kept although lessons are currently rendered
    # inline (not as extra_blocks): it is harmless while inert and correct if
    # lesson routing ever moves into the collapsible block list.
    r"lesson|observation|phenomenon|frontier|promotion|sibling|graph facts|shared artifacts",
    re.IGNORECASE)


def _norm_block_title(title: str) -> str:
    """Title key with the per-stage parenthetical stripped, lowercased."""
    return re.sub(r"\s*\(.*\)\s*$", "", str(title)).strip().lower()


def _reference_line(digest: str, path: str, heading: str) -> str:
    """The ONE emitted reference format; _chain_source must parse it exactly."""
    return (f"- unchanged since this subject's previous bundle (sha {digest}); full text at "
            f"`{path}` under the heading '## {heading}'. If you are not CERTAIN you have "
            "read it, read it there before proceeding.")


def _chain_source(prev_body: str, digest: str) -> tuple[str, str] | None:
    """(original_path, original_heading) when prev_body is itself a reference
    to the SAME bytes (same sha) - keeps chains pointing at the original full
    text instead of at a reference-of-a-reference."""
    if not prev_body.startswith("- unchanged since") or f"sha {digest}" not in prev_body:
        return None
    # Greedy title match anchored to the line's fixed tail, so an apostrophe
    # INSIDE a block title cannot truncate the parsed heading (final audit L24).
    m = re.search(r"full text at `([^`]+)` under the heading '## (.*)'\. If you are not CERTAIN",
                  prev_body)
    return (m.group(1), m.group(2)) if m else None


def _previous_bundle_blocks(store, st: dict, task: dict) -> tuple[dict[str, str], str]:
    """({block title: body}, repo-relative path) of this subject's most recent
    earlier bundle, or ({}, "")."""
    subj = task.get("subject") or {}
    key = ("node", str(subj.get("node"))) if subj.get("node") else ("lane", str(subj.get("lane")))
    if not key[1] or key[1] == "None":
        return {}, ""
    prev = None
    for t in reversed(st.get("tasks", [])):
        if t.get("id") == task.get("id"):
            continue
        ts = t.get("subject") or {}
        if str(ts.get(key[0]) or "") == key[1] and t.get("bundle"):
            prev = t
            break
    if prev is None:
        return {}, ""
    rel = str(prev.get("bundle") or "")
    try:
        text = eutil.rpath(store.repo, rel).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}, ""
    blocks: dict[str, str] = {}
    title, buf = None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if title is not None:
                blocks[title] = "\n".join(buf).strip("\n")
            title, buf = line[3:].strip(), []
        elif title is not None:
            buf.append(line)
    if title is not None:
        blocks[title] = "\n".join(buf).strip("\n")
    return blocks, rel
