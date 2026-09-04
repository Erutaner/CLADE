"""Small, dependency-free regression checks for provenance primitives.

    python tests/v92_provenance_unit.py

This suite used 30 bare ``assert`` statements: it contributed ZERO to the
counted total, and under ``python -O`` it silently became a no-op while still
printing "passed" (mutation-proven in the v10.2a test audit). Every assertion
now goes through the shared counted check() protocol.
"""
from __future__ import annotations

import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))

import eartifact  # noqa: E402
import ebundle    # noqa: E402
from _check import check, done  # noqa: E402


class FakeStore:
    def __init__(self, repo: Path, *, graph: dict | None = None,
                 state: dict | None = None, lessons: list[dict] | None = None):
        self.repo = repo
        self._graph = graph or {"nodes": []}
        self._state = state or {}
        self._lessons = lessons or []
        self.events: list[dict] = []

    def next_id(self, st: dict, prefix: str) -> str:
        counters = st.setdefault("counters", {})
        counters[prefix] = int(counters.get(prefix) or 0) + 1
        return f"{prefix}{counters[prefix]:03d}"

    def event(self, actor: str, event: str, **data) -> None:
        self.events.append({"actor": actor, "event": event, **data})

    def load_graph(self) -> dict:
        return self._graph

    def load_state(self) -> dict:
        return self._state

    def lessons(self, st: dict | None = None) -> list[dict]:
        # mirrors estore.Store.lessons(st): the fake has no journal counters,
        # so the committed filter is a pass-through here
        return list(self._lessons)


def test_artifact_generations_and_reason_aware_revival(repo: Path) -> None:
    run1 = {
        "id": "RUN001", "node": "N001", "kind": "stage", "stage": "train",
        "status": "finished", "evidence_seal": {"digest": "evidence-v1"},
    }
    st = {"counters": {"AR": 0}, "runs": [run1]}
    graph = {"nodes": [{"id": "N001", "implementation_seal": {"digest": "implementation-v1"}}]}
    store = FakeStore(repo, graph=graph, state=st)
    reg = {"artifacts": []}

    # The old scheduler call shape remains valid; provenance is inferred from
    # the just-finished producer RUN and the node's active implementation head.
    artifact = eartifact.register(
        store, st, reg, node="N001", stage="train", stage_key="train|fixture",
        name="checkpoint", kind="weights", uri="oss://fixture/checkpoint")
    check(artifact["generation"] == 1, 'artifact["generation"] == 1 must hold')
    check(artifact["producer_run"] == "RUN001", 'artifact["producer_run"] == "RUN001" must hold')
    check(artifact["producer_implementation_digest"] == "implementation-v1", 'artifact["producer_implementation_digest"] == "implementation-v1" must hold')
    check(artifact["producer_evidence_digest"] == "evidence-v1", 'artifact["producer_evidence_digest"] == "evidence-v1" must hold')
    check(artifact["history"] == [], 'artifact["history"] == [] must hold')

    eartifact.invalidate_for_node(
        store, reg, "N001", "workflow restarted after implementation revision")
    check(artifact["status"] == "stale", 'artifact["status"] == "stale" must hold')
    check(artifact["stale_reason"] == "workflow restarted after implementation revision", 'artifact["stale_reason"] == "workflow restarted after implementation revision" must hold')
    check(artifact["history"][-1]["status"] == "available", 'artifact["history"][-1]["status"] == "available" must hold')
    check(artifact["history"][-1]["producer_run"] == "RUN001", 'artifact["history"][-1]["producer_run"] == "RUN001" must hold')
    check(eartifact.revive_for_node(store, reg, "N001")[0] == 0, 'eartifact.revive_for_node(store, reg, "N001") == 0 must hold')
    check(artifact["status"] == "stale", "workflow-stale bytes must never be revived")

    run2 = {"id": "RUN002", "evidence_seal": {"digest": "evidence-v2"}}
    eartifact.record_generation(
        store, artifact, producer_run=run2,
        producer_implementation_digest="implementation-v2",
        stage="train", stage_key="train|fixture", reason="workflow replay")
    check(artifact["generation"] == 2, 'artifact["generation"] == 2 must hold')
    check(artifact["status"] == "available" and artifact["stale_reason"] is None, 'artifact["status"] == "available" and artifact["stale_reason"] is None must hold')
    check(artifact["producer_run"] == "RUN002", 'artifact["producer_run"] == "RUN002" must hold')
    check(artifact["producer_implementation_digest"] == "implementation-v2", 'artifact["producer_implementation_digest"] == "implementation-v2" must hold')
    check(artifact["producer_evidence_digest"] == "evidence-v2", 'artifact["producer_evidence_digest"] == "evidence-v2" must hold')
    check(any(row["generation"] == 1 and row["status"] == "stale"
               and row["producer_run"] == "RUN001" for row in artifact["history"]), 'any(row["generation"] == 1 and row["status"] == "stale" and row["producer_run"] == "RUN001" for row in artifact["history"]) must hold')

    eartifact.invalidate_for_node(store, reg, "N001", "producer pruned")
    check(eartifact.revive_for_node(
        store, reg, "N001", active_implementation_digest="implementation-v1")[0] == 0, 'eartifact.revive_for_node( store, reg, "N001", active_implementation_digest="implementation-v1") == 0 must hold')
    check(artifact["status"] == "stale", "an old implementation cannot revive a new generation")
    check(eartifact.revive_for_node(
        store, reg, "N001", active_implementation_digest="implementation-v2")[0] == 1, 'eartifact.revive_for_node( store, reg, "N001", active_implementation_digest="implementation-v2") == 1 must hold')
    check(artifact["status"] == "available" and artifact["stale_reason"] is None, 'artifact["status"] == "available" and artifact["stale_reason"] is None must hold')
    check(not eartifact.check_registry(reg, {"N001"}), 'not eartifact.check_registry(reg, {"N001"}) must hold')

    # A pre-v9.2 row remains readable and doctor-compatible.
    legacy = {"artifacts": [{
        "id": "AR999", "node": "N001", "stage": "train", "stage_key": "legacy|train",
        "name": "legacy", "kind": "weights", "uri": "oss://fixture/legacy",
        "status": "available",
    }]}
    check(not eartifact.check_registry(legacy, {"N001"}), 'not eartifact.check_registry(legacy, {"N001"}) must hold')


def test_active_knowledge_and_consumed_ids(repo: Path) -> None:
    lessons = [
        {"id": "LS001", "scope": "global", "statement": "old claim",
         "recommendation": "old action", "node": "N001"},
        {"id": "LS002", "scope": "global", "statement": "current claim",
         "recommendation": "current action", "node": "N002"},
        {"id": "LS003", "scope": "conditional", "tags": ["build"],
         "statement": "conditional claim", "recommendation": "conditional action",
         "node": "N003"},
    ]
    st = {
        "current_round": "R001",
        "knowledge_dispositions": [
            {"ref": "LS001", "status": "active", "case": "RC001",
             "reason": "initial conclusion", "at": "2026-01-01T00:00:00Z"},
            {"ref": "LS001", "status": "retracted", "case": "RC002",
             "reason": "conclusion corrected", "at": "2026-01-02T00:00:00Z"},
            {"ref": "LS002", "status": "active", "case": "RC002",
             "reason": "replacement remains authoritative", "at": "2026-01-02T00:00:00Z"},
        ],
    }
    store = FakeStore(repo, state=st, lessons=lessons)
    graph = {"nodes": []}
    cfg = {
        "project": {"name": "fixture", "goal": "verify provenance"},
        "budgets": {"max_lesson_items_in_bundle": 12, "max_attempts": 3},
    }

    picked = ebundle.select_lessons(
        store, graph, cfg, parents=[], tags=["build"], st=st)
    check([row["id"] for row in picked] == ["LS003", "LS002"], '[row["id"] for row in picked] == ["LS003", "LS002"] must hold')
    check(not ebundle.knowledge_is_active(st, "LS001"), 'not ebundle.knowledge_is_active(st, "LS001") must hold')
    check(ebundle.knowledge_is_active(st, "LS002"), 'ebundle.knowledge_is_active(st, "LS002") must hold')
    check(ebundle.knowledge_is_active(st, "LS999"), "legacy knowledge defaults to active")

    task = {"id": "T0001", "type": "implement", "subject": {}, "attempts": 0}
    written: dict[str, str] = {}
    original_write = ebundle.eutil.write_text
    ebundle.eutil.write_text = lambda path, text: written.__setitem__(str(path), text)
    try:
        ebundle.build_bundle(
            store, st, cfg, graph, task, inputs=[], lesson_parents=[], lesson_tags=["build"])
    finally:
        ebundle.eutil.write_text = original_write
    text = next(iter(written.values()))
    check("LS001" not in text and "LS002" in text and "LS003" in text, '"LS001" not in text and "LS002" in text and "LS003" in text must hold')
    check(task["consumed_context"]["lesson_ids"] == ["LS003", "LS002"], 'task["consumed_context"]["lesson_ids"] == ["LS003", "LS002"] must hold')

    # Latest append-ordered disposition wins without rewriting the LS record.
    st["knowledge_dispositions"].append({
        "ref": "LS001", "status": "active", "case": "RC003",
        "reason": "user re-adopted the corrected lesson", "at": "2026-01-03T00:00:00Z",
    })
    picked = ebundle.select_lessons(store, graph, cfg, parents=[], tags=[], st=st)
    check([row["id"] for row in picked] == ["LS002", "LS001"], '[row["id"] for row in picked] == ["LS002", "LS001"] must hold')


def main() -> None:
    test_artifact_generations_and_reason_aware_revival(HERE)
    test_active_knowledge_and_consumed_ids(HERE)
    done("V9.2 PROVENANCE UNIT")


if __name__ == "__main__":
    main()
