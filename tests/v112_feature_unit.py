"""v11.2 feature contracts at unit speed.

    python tests/v112_feature_unit.py

Covers the tombstone mechanism: collision deaths bank an anonymous absorption
criterion (a predicate bounding what ONE published work absorbs - never a
direction, never a menu), routed to the round strategist only; generator
inputs stay untouched. Validator branches are exercised BEHAVIORALLY (the
v11.1 postmortem rule: composite/validator paths must run, not just grep).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))

import eapply     # noqa: E402
import ebundle    # noqa: E402
import eprogram   # noqa: E402
import eutil      # noqa: E402
import evalid     # noqa: E402
from _check import check, done  # noqa: E402

CRIT = ("any variant that differs only in the functional form of a per-sample "
        "loss weight computed from offline exposure statistics")
CRIT2 = ("any variant that only reroutes the same offline exposure statistic "
         "into the sampling distribution instead of the loss weight")


def _ctx(repo: Path | None = None, evidence: list | None = None, collisions: dict | None = None):
    return SimpleNamespace(
        _evidence_rows=lambda: (evidence or []),
        collision_by_id=lambda: (collisions or {}),
        store=SimpleNamespace(repo=repo))


def criterion_validator():
    ctx = _ctx(evidence=[{"id": "E001", "title": "Inverse Propensity Weighting for Click Models"}])
    check(evalid.tombstone_criterion_errors(ctx, CRIT, "t") == [],
          "a clean >=60-char anonymous predicate passes")
    errs = evalid.tombstone_criterion_errors(ctx, "already done before", "t")
    check(any("TOMBSTONE_CRITERION" in e for e in errs),
          "a verdict phrase without substance is refused")
    errs = evalid.tombstone_criterion_errors(ctx, CRIT + " see arxiv.org/abs/2401.1", "t")
    check(any("TOMBSTONE_IDENTITY" in e for e in errs), "paper links are refused")
    errs = evalid.tombstone_criterion_errors(ctx, CRIT + " (per CA001)", "t")
    check(any("TOMBSTONE_IDENTITY" in e for e in errs), "ledger ids are refused")
    errs = evalid.tombstone_criterion_errors(ctx, CRIT + " as N012 showed", "t")
    check(any("TOMBSTONE_IDENTITY" in e for e in errs), "node ids are refused too")
    errs = evalid.tombstone_criterion_errors(
        ctx, "absorbed by Inverse Propensity Weighting for Click Models and its variants of any form", "t")
    check(any("quotes an evidence title" in e for e in errs),
          "quoting a screened paper's title is refused - shapes, not names")
    errs = evalid.tombstone_criterion_errors(ctx, CRIT + " from the NeurIPS follow-up line", "t")
    check(any("citation language" in e for e in errs), "venue names are refused")
    errs = evalid.tombstone_criterion_errors(ctx, CRIT + " in the style of LoRA adapters", "t")
    check(any("method/brand identity" in e for e in errs),
          "MixedCase method brand-names are refused - the blind generator must not receive names")
    errs = evalid.tombstone_criterion_errors(
        ctx, CRIT + " except when the signal enters through the sampler", "t")
    check(any("TOMBSTONE_MENU" in e for e in errs),
          "an escape list ('except ...') is refused - criteria state absorption, never escapes")
    errs = evalid.tombstone_criterion_errors(ctx, CRIT[:40] + "\n" + CRIT[40:], "t")
    check(any("ONE physical line" in e for e in errs), "embedded newlines are refused (JSON path)")
    errs = evalid.tombstone_criterion_errors(ctx, "any variant word " * 30, "t")
    check(any("400 chars" in e for e in errs), "an essay is not one predicate")


def review_level_contract():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        ctx = _ctx(repo=repo)
        head = "VERDICT: REJECT_DUPLICATE\nDUPLICATE_OF: CA007\n"
        ok = head + f"TOMBSTONE: {CRIT}\nTOMBSTONE_NOTE: the sampler-side entry is a different structure\n\n## Verdict rationale\nx"
        check(evalid._review_tombstone_errors(ctx, ok) == [],
              "criterion + one note + section heading after: clean")
        errs = evalid._review_tombstone_errors(ctx, head + "## Verdict rationale\nx")
        check(any("REVIEW_TOMBSTONE:" in e for e in errs), "a missing TOMBSTONE line is refused")
        # F1 regression: an empty label must NOT absorb the next line as its criterion.
        empty_label = head + "TOMBSTONE:\n\n## Verdict rationale\nx"
        check(evalid.TOMBSTONE_LINE_RE.findall(empty_label) == [],
              "an empty `TOMBSTONE:` label captures nothing (no cross-newline walk)")
        check(any("REVIEW_TOMBSTONE:" in e
                  for e in evalid._review_tombstone_errors(ctx, empty_label)),
              "an empty label is a missing criterion, not a silent mis-capture")
        wrapped = head + f"TOMBSTONE: {CRIT}\nand this second physical line continues the sentence\n"
        check(any("REVIEW_TOMBSTONE_WRAP" in e
                  for e in evalid._review_tombstone_errors(ctx, wrapped)),
              "a hard-wrapped criterion is refused instead of silently truncated")
        two = head + f"TOMBSTONE: {CRIT}\nTOMBSTONE: {CRIT2}\n"
        check(any("REVIEW_TOMBSTONE:" in e for e in evalid._review_tombstone_errors(ctx, two)),
              "two criterion lines are refused - one death, one boundary")
        notes = (head + f"TOMBSTONE: {CRIT}\nTOMBSTONE_NOTE: one pointer\n"
                 "TOMBSTONE_NOTE: second pointer\n")
        check(any("REVIEW_TOMBSTONE_NOTE" in e for e in evalid._review_tombstone_errors(ctx, notes)),
              "two notes are refused")
        bad_note = head + f"TOMBSTONE: {CRIT}\nTOMBSTONE_NOTE: try the LoRA route\n"
        check(any("method/brand identity" in e
                  for e in evalid._review_tombstone_errors(ctx, bad_note)),
              "notes face the same anonymity wall as criteria")
        # known-territory reference form
        eutil.append_jsonl(repo / ".evo/evidence/TOMBSTONES.jsonl",
                           {"id": "TB001", "criterion": CRIT})
        check(evalid._review_tombstone_errors(ctx, head + "TOMBSTONE: TB001\n") == [],
              "`TOMBSTONE: TB###` re-cites bounded territory instead of re-authoring")
        check(any("REVIEW_TOMBSTONE_KNOWN" in e
                  for e in evalid._review_tombstone_errors(ctx, head + "TOMBSTONE: TB099\n")),
              "an unknown TB reference is refused")


def _pd_audit(**over):
    base = {"sketch_id": "K1", "decision": "kill", "reason": "x" * 80,
            "prior_art": {"neighbors": [{"paper": "E001"}]},
            "emulation_matrix": [{"alternative": "E001", "can_emulate": False}]}
    base.update(over)
    return base


def published_dup_contract():
    cand = {"sketch_id": "K1", "novelty": {"bearer": "b"}}
    digest = eprogram.candidate_digest(cand)
    edge = {"lane": "L001", "program_set_digest": "D1", "candidate_id": "K1",
            "candidate_digest": digest}
    ctx = _ctx(collisions={"CA001": edge})
    kw = {"where": "audit(K1)", "lane_id": "L001", "program_set_digest": "D1",
          "known_ids": {"TB001"}}
    check(evalid._published_dup_errors(ctx, _pd_audit(), cand, **kw) == [],
          "a plain kill (no CA cite, no paper emulation) forces nothing")
    errs = evalid._published_dup_errors(
        ctx, _pd_audit(reason="collides with CA001 territory " + "x" * 40), cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_MISSING" in e for e in errs),
          "a kill reason citing a CA### forces published_dup")
    errs = evalid._published_dup_errors(
        ctx, _pd_audit(emulation_matrix=[{"alternative": "E001", "can_emulate": True}]),
        cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_MISSING" in e and "emulate" in e for e in errs),
          "a screened paper defeating the core via emulation forces published_dup too")
    errs = evalid._published_dup_errors(
        ctx, _pd_audit(decision="advance",
                       published_dup={"ca": "CA001", "tombstone": CRIT}), cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_ADVANCE" in e for e in errs),
          "published_dup on an advance is refused")
    check(evalid._published_dup_errors(
        ctx, _pd_audit(published_dup={"ca": "CA001", "tombstone": CRIT}), cand, **kw) == [],
        "a bound CA + clean criterion banks a new boundary")
    check(evalid._published_dup_errors(
        ctx, _pd_audit(published_dup={"ca": "CA001", "known_tombstone": "TB001"}), cand, **kw) == [],
        "a bound CA + known TB re-cites bounded territory")
    errs = evalid._published_dup_errors(
        ctx, _pd_audit(published_dup={"ca": "CA001", "known_tombstone": "TB009"}), cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_KNOWN" in e for e in errs), "an unknown TB id is refused")
    errs = evalid._published_dup_errors(
        ctx, _pd_audit(published_dup={"ca": "CA002", "tombstone": CRIT}), cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_CA" in e for e in errs), "an unresolvable CA is refused")
    other = dict(edge, candidate_id="K2")
    ctx2 = _ctx(collisions={"CA001": other})
    errs = evalid._published_dup_errors(
        ctx2, _pd_audit(published_dup={"ca": "CA001", "tombstone": CRIT}), cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_CA_BINDING" in e for e in errs),
          "a CA bound to a different candidate cannot source this tombstone")
    check(evalid._published_dup_errors(
        ctx, _pd_audit(published_dup={"ca": "CA001", "decisive": False, "ground": "y" * 70}),
        cand, **kw) == [],
        "decisive=false + a real ground waives the tombstone (a mention is not a kill ground)")
    errs = evalid._published_dup_errors(
        ctx, _pd_audit(published_dup={"ca": "CA001", "decisive": False, "ground": "thin"}),
        cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_GROUND" in e for e in errs),
          "decisive=false without a >=60-char ground is refused")
    errs = evalid._published_dup_errors(
        ctx, _pd_audit(published_dup={"ca": "CA001", "decisive": False,
                                      "ground": "y" * 70, "tombstone": CRIT}), cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_SHAPE" in e for e in errs),
          "decisive=false plus a tombstone is contradictory")
    errs = evalid._published_dup_errors(
        ctx, _pd_audit(published_dup={"ca": "CA001", "tombstone": CRIT,
                                      "known_tombstone": "TB001"}), cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_SHAPE" in e for e in errs),
          "tombstone and known_tombstone together are refused")
    errs = evalid._published_dup_errors(
        ctx, _pd_audit(published_dup={"ca": "CA001", "surprise": 1}), cand, **kw)
    check(any("TOURNAMENT_TOMBSTONE_SHAPE" in e for e in errs), "unknown fields are refused")


def placement_guards():
    src = open(HERE.parent / "engine" / "evalid.py", encoding="utf-8").read()
    lic = src.split("def _duplicate_evidence_errors")[1].split("\ndef ")[0]
    check("REVIEW_TOMBSTONE" not in lic and "TOMBSTONE_LINE_RE" not in lic,
          "the license fn itself is untouched (pre-v11.2 reviews keep hard-disposition status)")
    for anchor in ("TOURNAMENT_TOMBSTONE_MISSING", "TOURNAMENT_TOMBSTONE_SHAPE",
                   "TOURNAMENT_TOMBSTONE_CA", "TOURNAMENT_TOMBSTONE_KNOWN",
                   "TOURNAMENT_TOMBSTONE_ADVANCE", "TOURNAMENT_TOMBSTONE_CA_BINDING",
                   "TOURNAMENT_TOMBSTONE_GROUND", "TOURNAMENT_TOMBSTONE_RESEARCH",
                   "REVIEW_TOMBSTONE_WRAP", "REVIEW_TOMBSTONE_KNOWN"):
        check(anchor in src, f"rule present: {anchor}")
    tsrc = open(HERE.parent / "engine" / "etask.py", encoding="utf-8").read()
    check("tombstones_block" in tsrc, "the strategist bundle carries the tombstones block")
    check(tsrc.count("tombstones_reviewer_block(self.store)") == 2,
          "exactly the two critic bundles (tournament, red_team) carry the reviewer list")
    for gen_fn in ("_winner_stage_inputs", "_ledger_slice_rows"):
        check("tombstone" not in tsrc.split(f"def {gen_fn}")[1].split("\n    def ")[0].lower(),
              f"generator-side {gen_fn} untouched by tombstones (blindness preserved)")


def producer_and_ledger():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        events: list[dict] = []
        self = object.__new__(eapply.ApplyMixin)   # real class methods, no __init__
        self.store = SimpleNamespace(
            repo=repo, event=lambda *a, **k: events.append({"args": a, **k}))
        lane = {"id": "L003", "round": "R004", "intent": "exploit",
                "search_origin": "constructive", "bottleneck_ids": ["B1"], "idea": "I009"}
        check(self._append_tombstone(
            lane, criterion="  " + CRIT + "  ",
            source={"kind": "red_team", "idea": "I009", "ca": "CA007"},
            note=" sampler entry untested ") == "TB001", "first banking returns TB001")
        self._append_tombstone(lane, criterion=CRIT2,
                               source={"kind": "tournament", "sketch": "K2", "ca": "CA010"})
        path = repo / ".evo/evidence/TOMBSTONES.jsonl"
        rows = eutil.read_jsonl(path)
        check([r["id"] for r in rows] == ["TB001", "TB002"],
              f"sequential TB ids: {[r['id'] for r in rows]}")
        check(rows[0]["criterion"] == CRIT and rows[0]["note"] == "sampler entry untested",
              "criterion and note are trimmed and stored")
        check("illegal as a claimed novelty kernel" in rows[0]["semantics"]
              and "asserts nothing" in rows[0]["semantics"],
              "the fixed semantics sentence travels with every tombstone")
        check(rows[0]["context"]["bottlenecks"] == ["B1"] and rows[0]["source"]["ca"] == "CA007"
              and rows[1]["note"] is None,
              "context/source/optional-note shapes hold")
        check(len(events) == 2 and all(e.get("tombstone") for e in events),
              "each banking emits an engine event")
        # idempotence: same criterion (case/whitespace variants) never grows the ledger
        check(self._append_tombstone(lane, criterion=CRIT.upper() + "  ",
                                     source={"kind": "tournament"}) == "TB001",
              "a normalized-identical criterion returns the existing TB id")
        check(len(eutil.read_jsonl(path)) == 2 and events[-1]["args"][1] == "tombstone_duplicate_skipped",
              "the duplicate is skipped with an event - same-batch/replay double-banking is dead")
        # id allocation survives a hand-pruned ledger (max+1, not count+1)
        eutil.append_jsonl(path, {"id": "TB007", "criterion": "z" * 61})
        check(self._append_tombstone(lane, criterion="q" * 61,
                                     source={"kind": "tournament"}) == "TB008",
              "ids allocate past the max existing number, never reissuing one")

        # review-driven banking: CA target + line -> banked; TB reference -> event only;
        # N target and line-less (pre-v11.2) reviews -> silent
        n0 = len(eutil.read_jsonl(path))
        self._bank_tombstone_from_review(
            lane, f"VERDICT: REJECT_DUPLICATE\nDUPLICATE_OF: CA007\nTOMBSTONE: {'w' * 61}\n")
        check(len(eutil.read_jsonl(path)) == n0 + 1,
              "a CA-target duplicate review with the line banks a tombstone")
        self._bank_tombstone_from_review(
            lane, "VERDICT: REJECT_DUPLICATE\nDUPLICATE_OF: CA007\nTOMBSTONE: TB001\n")
        check(len(eutil.read_jsonl(path)) == n0 + 1
              and events[-1]["args"][1] == "tombstone_known_hit",
              "a TB-reference review re-cites without growing the ledger")
        self._bank_tombstone_from_review(
            lane, "VERDICT: REJECT_DUPLICATE\nDUPLICATE_OF: N002\n")
        self._bank_tombstone_from_review(
            lane, "VERDICT: REJECT_DUPLICATE\nDUPLICATE_OF: CA007\n")
        check(len(eutil.read_jsonl(path)) == n0 + 1,
              "graph-target duplicates and line-less (pre-v11.2) reviews bank nothing")

        # tournament-side banking routes all three validated forms correctly
        tj = {"audits": [
            {"sketch_id": "K1", "published_dup": {"ca": "CA011", "tombstone": "t" * 61}},
            {"sketch_id": "K2", "published_dup": {"ca": "CA012", "known_tombstone": "TB001"}},
            {"sketch_id": "K3", "published_dup": {"ca": "CA013", "decisive": False,
                                                  "ground": "g" * 70}},
            {"sketch_id": "K4"}]}
        n1 = len(eutil.read_jsonl(path))
        self._bank_tournament_tombstones(lane, tj, "p/TOURNAMENT_c1.json")
        check(len(eutil.read_jsonl(path)) == n1 + 1,
              "tournament banking: only the new-criterion audit grows the ledger")
        kinds = [e["args"][1] for e in events[-2:]]
        check("tombstone_known_hit" in kinds and "tombstone_waived_not_decisive" in kinds,
              "known re-hits and decisive=false waivers each leave their event")


def strategist_and_reviewer_blocks():
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        store = SimpleNamespace(repo=repo)
        check(ebundle.tombstones_block(store) == [], "no ledger -> no block (no ceremony)")
        check(ebundle.tombstones_reviewer_block(store) == [], "no ledger -> no reviewer block")
        for i in range(25):
            eutil.append_jsonl(repo / ".evo/evidence/TOMBSTONES.jsonl", {
                "id": f"TB{i + 1:03d}", "criterion": f"{CRIT} variant {i}",
                "context": {"round": "R001", "lane": "L001", "intent": "exploit",
                            "search_origin": "constructive", "bottlenecks": ["B1"]},
                "note": ("try the sampler" if i == 24 else None)})
        block = ebundle.tombstones_block(store)
        text = "\n".join(block)
        check("TB025" in text and "TB006" in text and "TB005" not in text,
              "the block caps at the newest 20 entries")
        check("5 older tombstones omitted" in text, "the cap is disclosed with the ledger path")
        check("LEGAL as a known component" in text and "never die here" in text,
              "kernel-vs-component semantics and the no-direction-death rule lead the block")
        check("reference only, never into briefs" in text,
              "reviewer notes are marked strategist-reference only")
        check("never expand a criterion in your own words" in text,
              "over-breadth skepticism: the strategist quotes, never widens")
        rtext = "\n".join(ebundle.tombstones_reviewer_block(store))
        check("TB025" in rtext and "TB005" not in rtext and "5 older tombstones omitted" in rtext,
              "the reviewer list is capped and disclosed the same way")
        check("known_tombstone" in rtext and "TOMBSTONE: TB###" in rtext
              and "NARROWEST" in rtext,
              "the reviewer list teaches both re-cite forms and the narrowness duty")
        check("try the sampler" not in rtext,
              "reviewer notes stay strategist-side - the critic list carries criteria only")
        # a hand-corrupted row (valid JSON, wrong type) must not crash bundle assembly
        with (repo / ".evo/evidence/TOMBSTONES.jsonl").open("a", encoding="utf-8") as fh:
            fh.write('"stray"\n')
        check(any("TB025" in ln for ln in ebundle.tombstones_block(store)),
              "non-object ledger rows are skipped, not crashed on")


if __name__ == "__main__":
    criterion_validator()
    review_level_contract()
    published_dup_contract()
    placement_guards()
    producer_and_ledger()
    strategist_and_reviewer_blocks()
    done("V11.2 FEATURE UNIT")
