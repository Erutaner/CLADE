"""Field map view: per-cell engine facts, every line a pointer.

  - one section per contract cell, diagnostics marked as never deciding
  - our best names the holder (and says "revive first" when it is retired)
  - the published cap comes from the ACCEPTED SOTA prefix; the gap is
    cap - best on exact-comparability rows only
  - every claimant of a cell shows delta, verdict, mechanism label and
    frontier membership; ablations and observations bind through their node
  - tombstones close the file; FIELD_NOTES.md is appended verbatim
  - the generator stays blind: sketch inputs and the shared input builders
    never mention the map

    python tests/field_map_unit.py
"""
from __future__ import annotations

import shutil
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))
from _check import check, done  # noqa: E402

import efieldmap  # noqa: E402
import egraph     # noqa: E402
import esched     # noqa: E402
import estore     # noqa: E402
import eutil      # noqa: E402

CELLS = [
    {"id": "C1", "dataset": "D1", "task": "T1", "metric": "m", "result_key": "lp_ap", "role": "target",
     "required": False, "weight": 1.0, "min_improvement": 0.005, "noninferiority_margin": 0.005,
     "goal_threshold": None},
    {"id": "C2", "dataset": "D1", "task": "T2", "metric": "m", "result_key": "nc_f1", "role": "target",
     "required": False, "weight": 1.0, "min_improvement": 0.005, "noninferiority_margin": 0.005,
     "goal_threshold": None},
    {"id": "C3", "dataset": "D1", "task": "T2", "metric": "m", "result_key": "diag_loss", "role": "diagnostic",
     "required": False, "weight": 1.0, "min_improvement": 0.0, "noninferiority_margin": 0.0,
     "goal_threshold": None},
]


def _fresh_engine(tag: str):
    repo = HERE / "out" / f"fieldmap-{tag}-{uuid.uuid4().hex[:8]}"
    repo.mkdir(parents=True)
    store = estore.Store(repo)
    store.init("fieldmap-unit", "render per-cell facts")
    eng = esched.Engine(store)
    eng.cfg["project"]["mode"] = "research"
    eng.cfg["metrics"] = [{"key": "m", "direction": "max"}]
    eng.cfg["evaluation_contract"] = {
        "display_cell": "C1", "cells": CELLS,
        "datasets": [{"id": "D1"}], "tasks": [{"id": "T1", "aggregation": "all", "weight": 1.0},
                                              {"id": "T2", "aggregation": "all", "weight": 1.0}],
        "task_groups": [], "decision": {"min_target_groups_improved": 1, "allow_specialist": True},
        "noise_floors": {"C1": 0.004}, "noise_floor_sources": {"C1": "literature"}, "margin_sources": {}}
    eng.cfg["evidence_policy"] = {"training_replication": {"mode": "record_only"}}
    return repo, store, eng


def _node(nid, *, role, verdict, scores, parents=(), **extra):
    n = {"id": nid, "title": nid, "role": role, "experiment_purpose": "candidate", "parents": list(parents),
         "level": 2, "status": "concluded", "verdict": verdict, "retire_reason": None,
         "scores": dict(scores), "score_evidence": dict(scores), "round": "R001",
         "effect_resources_realized": {"gpu_hours": {"lower": 1.0, "upper": 1.0}}}
    n.update(extra)
    return n


def _summary(cells: dict, target_cells: list[str]) -> dict:
    return {"verdict": "improved", "target_cells": target_cells, "guardrail_cells": [],
            "cells": {cid: {"cell": cid, "reference_node": "N001", **row} for cid, row in cells.items()}}


def _build(repo: Path, eng) -> None:
    eutil.write_text(repo / ".evo/ideas/I001.md", "# idea\n")
    eutil.write_json_atomic(repo / ".evo/ideas/I001.meta.json", {
        "idea": "I001", "claim_scope": {"kind": "specialist", "target_cells": ["C1"], "guardrail_cells": [],
                                        "rationale": "r" * 60}})
    eutil.write_json_atomic(repo / ".evo/ideas/I002.meta.json", {
        "idea": "I002", "evaluation_scope": {"target_cells": ["C1"], "rationale": "r" * 60},
        "ablation": {"settles_parent_mechanism": True}})
    eng.g["nodes"] = [
        _node("N001", role="baseline", verdict="baseline",
              scores={"lp_ap": 0.80, "nc_f1": 0.60, "diag_loss": 1.2}),
        _node("N002", role="variant", verdict="specialist", parents=["N001"], lane="L001", idea_doc=".evo/ideas/I001.md",
              scores={"lp_ap": 0.86, "nc_f1": 0.60, "diag_loss": 1.1},
              scientific_promotion_status="met", effect_contract_status="met", mechanism_status="deferred",
              concluded_at="2026-09-07T10:00:00Z",
              mechanism_settlements=[{"ablation": "N004", "from": "deferred", "to": "confirmed"}],
              evaluation_summary=_summary({"C1": {"new": 0.86, "reference": 0.80, "delta": 0.06, "status": "improved"},
                                           "C2": {"new": 0.60, "reference": 0.60, "delta": 0.0, "status": "noninferior"}},
                                          ["C1"])),
        _node("N003", role="variant", verdict="regressed", parents=["N001"], lane="L002",
              scores={"lp_ap": 0.79, "nc_f1": 0.66, "diag_loss": 1.3},
              scientific_promotion_status="blocked", effect_contract_status="failed", mechanism_status="deferred",
              retire_reason="archived",
              evaluation_summary=_summary({"C1": {"new": 0.79, "reference": 0.80, "delta": -0.01, "status": "regressed"},
                                           "C2": {"new": 0.66, "reference": 0.60, "delta": 0.06, "status": "improved"}},
                                          ["C1", "C2"])),
        _node("N004", role="variant", verdict="improved", parents=["N002"], lane="L003", idea_doc=".evo/ideas/I002.md",
              experiment_purpose="targeted_ablation", scores={"lp_ap": 0.81, "nc_f1": 0.60, "diag_loss": 1.2},
              scientific_promotion_status="not_applicable",
              ablation_result={"effect": "observed", "supports": "mechanism",
                               "decision": "the kernel is the cause; build on N002's story"},
              evaluation_summary=_summary({"C1": {"new": 0.81, "reference": 0.86, "delta": -0.05, "status": "regressed"}},
                                          ["C1"])),
    ]
    eng.st["lanes"] = [{"id": "L001", "round": "R001", "name": "alpha", "intent": "reform"}]
    sota = repo / ".evo/evidence/SOTA.jsonl"
    eutil.append_jsonl(sota, {"id": "S001", "title": "paper", "url": "u", "method": "Contrastive re-ranker",
                              "task": "T1", "venue": "NeurIPS", "year": 2025, "dataset": "D1", "cell": "C1",
                              "comparability": "exact", "headline": {"metric": "lp_ap", "value": 0.90}})
    eutil.append_jsonl(sota, {"id": "S002", "title": "paper2", "url": "u", "method": "Adjusted protocol",
                              "task": "T1", "venue": "ICML", "year": 2025, "dataset": "D1", "cell": "C1",
                              "comparability": "protocol_adjusted", "headline": {"metric": "lp_ap", "value": 0.95}})
    eutil.append_jsonl(sota, {"id": "S003", "title": "unaccepted", "url": "u", "method": "Cancelled scan row",
                              "task": "T1", "venue": "ICML", "year": 2025, "dataset": "D1", "cell": "C2",
                              "comparability": "exact", "headline": {"metric": "nc_f1", "value": 0.99}})
    eng.st["ledger_accept"] = {"sota": {"count": 2, "digest": "d"}}
    eutil.append_jsonl(repo / ".evo/evidence/TOMBSTONES.jsonl", {
        "id": "TB001", "criterion": "x" * 130, "semantics": "published territory",
        "context": {"round": "R001", "lane": "L002", "intent": "reform", "search_origin": "constructive",
                    "bottlenecks": ["B1"]}, "source": {}, "note": None, "created_at": "2026-09-07T00:00:00Z"})
    eng.store.add_observation(eng.st, {"statement": "loss plateaus after epoch 3 on the long-tail slice",
                                       "where": "train log", "measurement": "loss 1.1 flat", "evidence": "x",
                                       "node": "N002", "round": "R001", "status": "open"})
    eng.store.add_observation(eng.st, {"statement": "an unrelated scout phenomenon on a node that claimed nothing",
                                       "where": "eval", "measurement": "n/a", "evidence": "x",
                                       "node": "N001", "round": "R001", "status": "open"})


def render_facts() -> None:
    repo, store, eng = _fresh_engine("facts")
    try:
        _build(repo, eng)
        egraph.render_views(store, eng.g, eng.cfg, eng.st)
        path = repo / ".evo/views/FIELD_MAP.md"
        check(path.is_file(), "render_views writes the field map next to FRONTIER.md")
        text = eutil.read_text(path)
        check(text.splitlines()[0] == f"# Field map ({efieldmap.HEADER})",
              f"header names the engine and the pointer rule: {text.splitlines()[0]}")
        sections = [ln for ln in text.splitlines() if ln.startswith("## ")]
        check(sections[:3] == ["## C1 - D1 / T1 / m - role target",
                               "## C2 - D1 / T2 / m - role target",
                               "## C3 - D1 / T2 / m - role diagnostic - never decides"],
              f"one section per contract cell in contract order, diagnostics marked: {sections}")
        c1 = text.split("## C1 ")[1].split("\n## ")[0]
        c2 = text.split("## C2 ")[1].split("\n## ")[0]
        c3 = text.split("## C3 ")[1].split("\n## ")[0]
        check("floor: 0.004 (config: evaluation_contract.noise_floors, recorded as literature)" in c1,
              f"the floor in force carries its source and provenance: {c1}")
        check("floor: none recorded" in c2, "a cell without a floor says so instead of inventing one")
        check("best: 0.86 held by N002 (R001, L001, concluded 2026-09-07)" in c1,
              f"our best names the holder with round, lane and date: {c1}")
        check("best: 0.66 held by N003" in c2 and "archived, revive first (evo revive --node N003" in c2,
              f"a retired record holder is labeled with its door: {c2}")
        check("best: 1.3 held by N003" in c3, "a diagnostic cell still reports its best value (cell_records leaves it out)")
        check("cap S001: 0.9 lp_ap, comparability exact, method Contrastive re-ranker (2025)" in c1
              and "cap S002: 0.95 lp_ap, comparability protocol_adjusted" in c1,
              f"accepted SOTA rows bound to the cell are listed with value/comparability/method: {c1}")
        check("S001 +0.04 (behind)" in c1 and "S002" not in c1.split("gap to exact caps")[1],
              f"the gap is cap - best on exact rows only: {c1}")
        check("S003" not in text and "cap: no accepted SOTA row bound to this cell" in c2,
              "rows past the accepted watermark never reach the view")
        check("- N002 (L001, R001): +0.06 vs N001, cell improved; verdict specialist; effect met; science met; "
              "mechanism deferred (via N004); inheritance frontier yes" in c1,
              f"the claimant row carries delta, cell status, verdict, effect, science, mechanism label, frontier: {c1}")
        check("- N003 (L002, R001): -0.01 vs N001, cell regressed; verdict regressed; effect failed; science blocked; "
              "mechanism deferred; inheritance frontier no; archived - revive first" in c1,
              f"a retired claimant is marked: {c1}")
        check("N003 (L002, R001): +0.06 vs N001, cell improved" in c2 and "N002" not in c2.split("claimed by")[1],
              f"a node appears only under the cells it claimed: {c2}")
        check("- N004 (of N002): effect observed, supports mechanism, decision the kernel is the cause" in c1
              and not any(ln.strip().startswith("- N004")
                          for ln in c1.split("claimed by")[1].split("ablations")[0].splitlines()),
              f"ablations are listed by scope, never as claimants: {c1}")
        check("- OB001 (N002): loss plateaus after epoch 3" in c1 and "OB002" not in text,
              "observations bind through a node that claimed the cell; a baseline's row binds nowhere")
        check("claimed by: no concluded node yet" in c3, "an unclaimed cell says so")
        territory = text.split(efieldmap.TERRITORY_HEADING)[1]
        check("- TB001 (R001/L002): " + "x" * 120 + "..." in territory,
              f"tombstones close the file, round/lane bound, criterion clipped: {territory}")
        check(efieldmap.NOTES_HEADING not in text, "no notes section when the agent wrote none")
        for banned in ("grade", "Grade", "A/B/C", "ritual"):
            check(banned not in text, f"no grades, no rituals in the facts view: {banned}")
        # notes passthrough
        eutil.write_text(repo / ".evo/profile/FIELD_NOTES.md",
                         "## C1\n- live: N002's kernel at half width (OB001)\n- dead: full-width variant (N003)\n- untried: shared head\n")
        text2 = efieldmap.render(store, eng.g, eng.cfg, eng.st)
        tail = text2.split(efieldmap.NOTES_HEADING)[1]
        check("- live: N002's kernel at half width (OB001)" in tail and "- untried: shared head" in tail,
              f"FIELD_NOTES.md is appended verbatim under its own heading: {tail}")
        check(text2.index(efieldmap.TERRITORY_HEADING) < text2.index(efieldmap.NOTES_HEADING),
              "notes come after every engine fact")
        check(eutil.read_text(repo / ".evo/views/FIELD_MAP.md") == text2, "render returns the bytes it wrote")
        # list caps disclose their cut
        for i in range(15):
            eutil.append_jsonl(repo / ".evo/evidence/TOMBSTONES.jsonl",
                               {"id": f"TB{i + 2:03d}", "criterion": f"criterion {i} " + "y" * 60,
                                "context": {"round": "R002", "lane": "L009"}})
        text3 = efieldmap.render(store, eng.g, eng.cfg, eng.st)
        territory3 = text3.split(efieldmap.TERRITORY_HEADING)[1].split(efieldmap.NOTES_HEADING)[0]
        check(territory3.count("- TB") == efieldmap.LIST_CAP and "TB016" in territory3 and "TB001" not in territory3
              and f"+{16 - efieldmap.LIST_CAP} older tombstones, see the ledger" in territory3,
              f"long lists show the newest {efieldmap.LIST_CAP} and count the rest: {territory3}")
        check(len(c1.strip().splitlines()) <= 25, f"a cell section stays compact: {len(c1.splitlines())} lines")
        # a corrupt idea meta degrades to no claim instead of blocking the render
        (repo / ".evo/ideas/I001.meta.json").write_text("{not json", encoding="utf-8")
        text4 = efieldmap.render(store, eng.g, eng.cfg, eng.st)
        check("- N002 (L001, R001): +0.06 vs N001" in text4,
              "a torn idea meta leaves the summary-backed claim standing and never blocks the view")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def generator_blindness() -> None:
    src = (HERE.parent / "engine" / "etask.py").read_text(encoding="utf-8")

    def body(marker: str, stop: str = "\n    def ") -> str:
        parts = src.split(marker)
        check(len(parts) == 2, f"anchor {marker!r} is unique in etask.py")
        return parts[1].split(stop)[0]

    for fn in ("_lane_common_inputs", "_profile_inputs", "_winner_stage_inputs", "_ledger_slice_rows"):
        b = body(f"def {fn}(")
        check("FIELD_MAP" not in b and "FIELD_NOTES" not in b, f"{fn} never mentions the field map")
    sketch = body('        if stg == "sketch":\n', '\n        if stg == "')
    check("FIELD_MAP" not in sketch and "FIELD_NOTES" not in sketch and "program_inputs" in sketch,
          "the sketch branch (the generator) never mentions the field map")
    graph_src = (HERE.parent / "engine" / "egraph.py").read_text(encoding="utf-8")
    hook = graph_src.split("def render_views(")[1].split("\ndef ")[0]
    check("efieldmap.render(store, g, cfg, st)" in hook and hook.index('"FRONTIER.md"') < hook.index("efieldmap.render"),
          "render_views renders the field map after FRONTIER.md")
    for rel, needle in (("OPERATOR_PROMPT.md", ".evo/views/FIELD_MAP.md"),
                        ("OPERATOR_PROMPT.md", ".evo/profile/FIELD_NOTES.md"),
                        ("skills/clade/SKILL.md", ".evo/views/FIELD_MAP.md"),
                        ("engine/cards/open_round.md", ".evo/views/FIELD_MAP.md"),
                        ("engine/cards/close_round.md", ".evo/views/FIELD_MAP.md")):
        check(needle in (HERE.parent / rel).read_text(encoding="utf-8"), f"{rel} points at {needle}")
    prompt = (HERE.parent / "OPERATOR_PROMPT.md").read_text(encoding="utf-8")
    check(".evo/profile/FIELD_MAP.md" not in prompt and "A measured here" not in prompt and "FIELD_MAP" in prompt,
          "the prompt asks for no hand-maintained graded map and keeps the FIELD_MAP needle")


def main() -> None:
    render_facts()
    generator_blindness()
    done("FIELD MAP UNIT")


if __name__ == "__main__":
    main()
