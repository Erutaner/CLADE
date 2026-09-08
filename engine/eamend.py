"""The experiment notebook: authored material may be corrected, with history.

Sealing exists to answer "who claimed what, and when" - it must never turn
into "the world may not change". Two things ARE history and stay frozen: the
claim and its decision rules as they stood when production compute was
launched, and every measurement that was produced. Everything else an agent
writes - a lane brief, idea prose, an estimate, a budget cap, a smoke command,
a stage command that has not run yet - is notebook material: it may be
corrected at any time with a dated reason, and the previous bytes are kept.
Reviewers see the whole correction history in their bundle and weigh WHEN a
change was made against what had already been measured.

One verb records a correction (`evo amend`): it refuses any change to a
frozen field, snapshots the old and the new bytes (content-addressed, in the
same store the seals use), writes the new bytes into place and appends one
row to `.evo/amendments.jsonl`. Seal verification then accepts a working
file whose digest equals its latest amendment; a hand edit that bypasses the
verb is reported by doctor (AMENDMENT_DRIFT) and, on a sealed file, by the
seal audit. Every blessed config writer (`evo autonomy`) appends to the same
ledger, so the latest recorded digest is always the live file's.
"""
from __future__ import annotations

import json
from typing import Any

import econfig
import eseal
import eutil

AMENDMENTS_REL = ".evo/amendments.jsonl"

# Two things are history from the moment they exist: WHAT this idea is (its
# program, kernel and lineage - changing those is a different idea) and WHAT
# WAS MEASURED. Everything else is notebook until production compute launches;
# at launch the bet itself (claim, scope, decision rules, instrumental
# contracts) freezes, because a bet edited after the result is no bet.
IDEA_META_ALWAYS_FROZEN = frozenset({
    "idea", "lane", "sketch_id", "experiment_purpose", "change_scope", "program", "novelty",
    "program_digest", "kernel_hash", "level", "diagnosis_digest", "hypothesis_ids",
    "theory_role", "theory_rigor", "theory_target", "theory_obligations", "theory_audit",
    "theory_doc", "problem_doc", "parents", "platforms_consumed",
})
IDENTITY_WHY = ("the identity of the idea (program, kernel, lineage): a change here is a "
                "different idea - rewind the lane (evo decide --gate <its idea gate> --reject "
                "--retry-stage sketch|mature) or open a new lane")
# Idea-meta fields the node holds plain copies or derivations of (refreshed
# from the amended meta while the node has not launched).
IDEA_META_NODE_COPIES = frozenset({
    "metric_bridge_needed", "external_interface_changed", "sota_targets",
})
# Probe wiring the spec copies (probe_execution / evidence_plan) and a build
# realizes: notebook until a build exists, then history for that build.
IDEA_PROBE_WIRING = frozenset({"mode", "artifact", "required_fields", "extra_eval_arms",
                               "cheaper_modes_rejected"})
# Frozen once production compute launched: the bet and its decision rules.
IDEA_META_FROZEN_AFTER_LAUNCH = frozenset({
    "predictions", "mechanism_probe", "dominance", "repeat_rule", "scaling",
    "effect_case", "claim_scope", "evaluation_scope", "ablation", "probe", "maintenance",
}) | IDEA_META_NODE_COPIES
LAUNCHED_WHY = ("the bet and its decision rules at production launch are history; a wrong "
                "FORMULA goes through 'evo correct-instrument', a line set too high gets a "
                "post-hoc claim (evo claim --node <N###> --proposal <file>)")
# Idea-meta objects the spec carries engine-owned copies of (kept in step).
IDEA_TO_SPEC_COPIES = ("effect_case", "ablation", "probe", "maintenance", "evaluation_scope")
# Spec tops that are engine-owned copies of the idea meta: corrected there.
SPEC_ENGINE_COPIES = frozenset(IDEA_TO_SPEC_COPIES) | {"theory_obligations"}


def _build_exit(nid: str) -> str:
    return (f"abandon the node (evo propose-abandon --node {nid}) and pursue the direction in a new "
            "lane, or leave the wiring and correct the rule (decision_rule, signal, expect stay "
            "amendable until launch)")

SPEC_ALWAYS_FROZEN = frozenset({
    "role", "experiment_purpose", "parents", "code_parent", "level", "program_digest",
    "kernel_ids", "program_ir", "novelty_kernel", "workdir", "experiment_class", "enables",
})
SPEC_FROZEN_AFTER_LAUNCH = frozenset({
    "effect_case", "theory_obligations", "ablation", "probe", "maintenance", "evaluation_scope",
    "cost_class", "evidence_plan", "training_replication", "service_snapshot_waiver",
    "continuation_gate", "refuted_kernel_disposition",
})
SPEC_PROBE_CONTRACT = frozenset({"mode", "signal", "expect", "artifact", "required_fields",
                                 "decision_rule"})
# cost_estimate is the agent's own number with its basis - the rehearsal
# teaches better ones, and the workflow gate reads whatever is current
SPEC_FREE = frozenset({"title", "smoke_plan", "rehearsal", "cost_estimate"})

# .evo/config.json: the success/resource contract is signed at bootstrap and
# stays signed, but a few numbers inside it describe the WORLD, not the bet -
# how noisy a cell is, what step counts as an advance, which cells must not
# slip, the ablation allowance. Those are notebook facts: correctable with a
# reason, forward-only (a node already measured keeps the ruler it was
# measured against; nodes measured later use the corrected value). The
# supervision mode and the tempo preset are notebook too: they have their own
# documented controls and sit outside the signed digest.
CONFIG_NOTEBOOK_PREFIXES = (
    "evaluation_contract.noise_floors.",
    "evaluation_contract.noise_floor_sources.",
    "evaluation_contract.margin_sources.",
    "evaluation_contract.noise_floor_multiple",
    "evidence_policy.ablation.budget_multiple",
    "evidence_policy.ablation.basis",
    "resource_contract.node_ceiling",
    "resource_contract.node_ceiling_source",
    "resource_contract.node_ceiling_basis",
    "resource_contract.max_devices",
    "resource_contract.busy_wait_minutes",
    "policy.autonomy",
    "policy.preset",
) + tuple(f"policy.{key}" for key in econfig.PRESET_KEYS)
CONFIG_NOTEBOOK_CELL_FIELDS = frozenset({"min_improvement", "noninferiority_margin", "required",
                                         "goal_threshold", "goal_threshold_source"})
CONFIG_REL = ".evo/config.json"
AUTONOMY_PATH = "policy.autonomy"
CONTRACT_WHY = ("the signed success/resource contract; a different contract is a deliberate "
                "reconfigure (restart)")
UNJUDGED_WHY = ("not a notebook fact and not part of the signed contract: edit it directly "
                "(it is not judged)")
RULER_NOTE = ("a node already measured keeps the ruler it was measured against; nodes measured "
              "after this correction use the corrected value")

PROFILE_KINDS = {
    ".evo/profile/PROJECT_PROFILE.md": ("profile", "project profile"),
    ".evo/profile/PROBLEM_DOSSIER.md": ("dossier", "problem dossier"),
    ".evo/profile/INNOVATION_RUBRIC.md": ("rubric", "innovation rubric"),
}


def read_all(store) -> list[dict]:
    return [r for r in eutil.read_jsonl(eutil.rpath(store.repo, AMENDMENTS_REL), lenient=True)
            if isinstance(r, dict) and str(r.get("path") or "")]


def latest_digests(store) -> dict[str, str]:
    """path -> digest of its most recent recorded amendment (the bytes the
    seal audit accepts in place of the sealed original)."""
    out: dict[str, str] = {}
    for row in read_all(store):
        out[str(row["path"])] = str(row.get("new_digest") or "")
    return out


def for_subject(store, *, lane: str | None = None, node: str | None = None,
                idea: str | None = None, project: bool = False) -> list[dict]:
    rows = []
    for row in read_all(store):
        if (lane and row.get("lane") == lane) or (node and row.get("node") == node) \
                or (idea and row.get("idea") == idea) \
                or (project and row.get("kind") in ("profile", "dossier", "rubric", "contract_facts")):
            rows.append(row)
    return rows


def config_notebook_path(path: str) -> bool:
    """Is this dotted config path a notebook fact (vs the signed contract)?"""
    if any(path == prefix.rstrip(".") or path.startswith(prefix) for prefix in CONFIG_NOTEBOOK_PREFIXES):
        return True
    if path.startswith("evaluation_contract.cells["):
        tail = path.split("].", 1)[1] if "]." in path else ""
        return tail.split(".")[0].split("[")[0] in CONFIG_NOTEBOOK_CELL_FIELDS
    return False


def norm_rel(rel: str) -> str:
    rel = str(rel or "").replace("\\", "/").strip()
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel or rel.startswith("/") or ".." in rel.split("/") or ":" in rel.split("/")[0]:
        raise SystemExit(f"[evo] amend needs a repo-relative path, got {rel!r}; pass --path as seen "
                         "from the repo root (no leading '/', drive letter or '..'), e.g. "
                         ".evo/nodes/N001/NODE_SPEC.json")
    return rel


def node_launched(st: dict, nid: str) -> bool:
    """Production compute was launched: a stage or evaluation RUN exists for
    the node. Smoke and rehearsal are not RUNs and leave the claim amendable."""
    return any(str(r.get("node") or "") == nid and str(r.get("kind") or "") in ("stage", "eval")
               for r in st.get("runs", []))


def _stage_has_run(st: dict, nid: str, index: int, name: str) -> bool:
    for r in st.get("runs", []):
        if str(r.get("node") or "") != nid or str(r.get("kind") or "") != "stage":
            continue
        if r.get("stage_index") == index or (name and str(r.get("stage") or "") == name):
            return True
    return False


def _eval_has_run(st: dict, nid: str) -> bool:
    return any(str(r.get("node") or "") == nid and str(r.get("kind") or "") == "eval"
               for r in st.get("runs", []))


def owner_of(store, st: dict, g: dict, rel: str) -> dict:
    """Which notebook object a path is, or a typed refusal.

    Returns {"kind", "lane", "node", "idea", "label"}; kind is one of
    brief | idea | idea_meta | node_spec | profile | dossier | rubric.
    """
    parts = rel.split("/")
    lanes = st.get("lanes", [])
    nodes = g.get("nodes", [])
    if rel == CONFIG_REL:
        if not st.get("config_frozen"):
            raise SystemExit(f"[evo] {rel} is still being written - it is corrected inside the configure "
                             "task until the bootstrap sign-off; amendments start after that")
        return {"kind": "contract_facts", "lane": None, "node": None, "idea": None,
                "label": "project contract facts (noise floors, margins, required cells, ablation allowance)"}
    if rel in PROFILE_KINDS:
        kind, label = PROFILE_KINDS[rel]
        if kind not in (st.get("bootstrap_done") or []):
            raise SystemExit(f"[evo] {rel} is still an open bootstrap output - edit it and submit "
                             "its task; amendments are for accepted material")
        return {"kind": kind, "lane": None, "node": None, "idea": None, "label": label}
    if len(parts) >= 5 and parts[:2] == [".evo", "rounds"] and parts[3] == "lanes" \
            and parts[-1] == "BRIEF.md":
        lane = next((l for l in lanes if str(l.get("brief_md") or "") == rel), None)
        if lane is None:
            raise SystemExit(f"[evo] {rel} is not the brief of any lane; a brief becomes notebook "
                             "material when its round portfolio is accepted - finish that open_round "
                             "task first ('evo next' serves it)")
        if lane.get("status") in ("done", "abandoned"):
            raise SystemExit(f"[evo] lane {lane.get('id')} is {lane.get('status')}; its brief is history now"
                             + (f" - the line continues on node {lane.get('node')}: amend its "
                                f"NODE_SPEC.json, or 'evo claim --node {lane.get('node')}' on its "
                                "concluded result" if lane.get("node") else
                                " - pursue the direction in a new lane (next open_round portfolio, or "
                                "'evo ablate' / 'evo probe' / 'evo maintain' mid-round)"))
        return {"kind": "brief", "lane": str(lane.get("id")), "node": lane.get("node") or None,
                "idea": lane.get("idea") or None, "label": f"lane {lane.get('id')} brief"}
    if len(parts) == 3 and parts[:2] == [".evo", "ideas"]:
        name = parts[2]
        if name.endswith(".meta.json"):
            iid, kind = name[:-len(".meta.json")], "idea_meta"
        elif name.endswith(".md"):
            iid, kind = name[:-3], "idea"
        else:
            iid, kind = "", "idea"
        lane = next((l for l in lanes if str(l.get("idea") or "") == iid), None) if iid else None
        if lane is None:
            raise SystemExit(f"[evo] {rel} belongs to no active idea (a superseded idea revision is "
                             "history and is not amended); amend the lane's active idea revision "
                             "instead ('evo status' shows each lane's current idea id)")
        if lane.get("status") == "abandoned":
            raise SystemExit(f"[evo] lane {lane.get('id')} is abandoned; its idea is history now - pursue "
                             "the direction in a new lane (next open_round portfolio, or 'evo ablate' / "
                             "'evo probe' / 'evo maintain' mid-round)")
        if not isinstance(lane.get("idea_seal"), dict):
            raise SystemExit(f"[evo] {rel} is still an open design task output - edit it and "
                             "submit that task; amendments are for accepted material")
        return {"kind": kind, "lane": str(lane.get("id")), "node": lane.get("node") or None,
                "idea": iid, "label": f"idea {iid} ({'contract' if kind == 'idea_meta' else 'prose'})"}
    if len(parts) == 4 and parts[:2] == [".evo", "nodes"] and parts[3] == "NODE_SPEC.json":
        node = next((n for n in nodes if str(n.get("spec") or "") == rel), None)
        if node is None:
            raise SystemExit(f"[evo] {rel} is not the spec of any node; node specs live at "
                             ".evo/nodes/N###/NODE_SPEC.json ('evo status' lists node ids)")
        if node.get("status") == "abandoned":
            raise SystemExit(f"[evo] node {node.get('id')} is abandoned; its spec is history now - a "
                             "fresh attempt is a new lane (next open_round portfolio, or 'evo ablate' / "
                             "'evo probe' mid-round)")
        return {"kind": "node_spec", "lane": node.get("lane") or None, "node": str(node.get("id")),
                "idea": None, "label": f"node {node.get('id')} spec"}
    raise SystemExit(
        f"[evo] {rel} is not notebook material. Amendable: a lane BRIEF.md, an accepted idea's "
        ".md / .meta.json, a node's NODE_SPEC.json, the profile/dossier/rubric documents, and the "
        "world facts inside .evo/config.json (noise floors, margins, required cells, the ablation "
        "allowance). Measurements, engine records, seals, code and evidence are never amended: a "
        "wrong settled record goes through 'evo recover-plan' or 'evo correct-instrument'; an open "
        "task's output is simply edited and resubmitted.")


def _flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        if not obj:
            out[prefix] = {}
        for k, v in obj.items():
            out.update(_flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        if not obj:
            out[prefix] = []
        for i, v in enumerate(obj):
            out.update(_flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


_MISSING = object()


def changed_paths(old: Any, new: Any) -> list[str]:
    a, b = _flatten(old), _flatten(new)
    return sorted(p for p in set(a) | set(b) if a.get(p, _MISSING) != b.get(p, _MISSING))


def _top(path: str) -> str:
    return path.split(".")[0].split("[")[0]


def _second(path: str) -> str:
    rest = path.split(".", 1)
    return rest[1].split(".")[0].split("[")[0] if len(rest) == 2 else ""


def _meta_rel_of(node: dict | None) -> str:
    doc = str((node or {}).get("idea_doc") or "")
    return doc[:-3] + ".meta.json" if doc.endswith(".md") else ".evo/ideas/<I###>.meta.json"


def frozen_paths(kind: str, paths: list[str], *, st: dict, node: dict | None,
                 new_spec: dict | None = None,
                 contract_paths: set[str] | None = None) -> list[tuple[str, str]]:
    """[(path, why frozen)] for the changed paths that are history, not notebook.

    `contract_paths` (contract_facts only): the dotted paths of the signed
    digest payload; a config path outside both the notebook set and the
    payload is not judged at all and is listed with its own exit."""
    out: list[tuple[str, str]] = []
    nid = str((node or {}).get("id") or "")
    planned = node is not None
    launched = bool(nid) and node_launched(st, nid)
    built = int((node or {}).get("implementation_revision") or 0) > 0
    if kind == "idea_meta":
        for p in paths:
            top = _top(p)
            if top in IDEA_META_ALWAYS_FROZEN:
                out.append((p, IDENTITY_WHY))
            elif top == "mechanism_probe":
                if launched:
                    out.append((p, LAUNCHED_WHY))
                elif planned and built and _second(p) in IDEA_PROBE_WIRING:
                    out.append((p, f"probe wiring the sealed build of {nid} already realizes - "
                                   + _build_exit(nid)))
            elif top == "effect_case" and _second(p) == "comparator_id" and planned:
                out.append((p, f"the comparator was frozen onto {nid} when it was created; a different "
                               f"comparator is a different bet - abandon the node (evo propose-abandon "
                               f"--node {nid}) and open a new lane"))
            elif top in IDEA_META_FROZEN_AFTER_LAUNCH and launched:
                out.append((p, LAUNCHED_WHY))
    elif kind == "contract_facts":
        # Only the signed contract is history. A config path that is neither a
        # notebook fact nor part of the digest payload (display text, tempo
        # keys) is not judged by anything and is recorded like any other line.
        for p in paths:
            if config_notebook_path(p):
                continue
            if contract_paths is None or p in contract_paths:
                out.append((p, CONTRACT_WHY))
    elif kind == "node_spec":
        stages = econfig.stages_of(new_spec or {})
        for p in paths:
            top = _top(p)
            if top in SPEC_FREE:
                continue
            if top in SPEC_ALWAYS_FROZEN:
                out.append((p, IDENTITY_WHY))
            elif top in SPEC_ENGINE_COPIES:
                out.append((p, f"an engine-owned copy of the idea: amend the idea meta ({_meta_rel_of(node)}); "
                               "the engine propagates the copy"))
            elif top in SPEC_FROZEN_AFTER_LAUNCH:
                if launched:
                    out.append((p, LAUNCHED_WHY))
            elif top == "probe_execution":
                sub = _second(p)
                if sub in SPEC_PROBE_CONTRACT:
                    out.append((p, f"an engine-owned copy of the idea's probe: amend the idea meta "
                                   f"({_meta_rel_of(node)}); the engine propagates the copy"))
                elif built:
                    out.append((p, f"probe wiring the sealed build of {nid} already realizes - "
                                   + _build_exit(nid)))
            elif top == "workflow":
                idx = -1
                if p.startswith("workflow.stages["):
                    try:
                        idx = int(p[len("workflow.stages["):].split("]")[0])
                    except ValueError:
                        idx = -1
                field = ""
                marker = f"workflow.stages[{idx}]."
                if idx >= 0 and p.startswith(marker):
                    field = p[len(marker):].split(".")[0].split("[")[0]
                if idx < 0 or not field:
                    out.append((p, "the workflow stage list itself is part of the approved contract"))
                    continue
                if field == "budget":
                    continue  # caps are notebook numbers; charged usage never moves
                name = str((stages[idx].get("name") if 0 <= idx < len(stages) else "") or "")
                if _stage_has_run(st, nid, idx, name):
                    out.append((p, f"stage {name or idx} already launched; its command and contract "
                                   "are history (a code fix is an implementation revision)"))
            elif top == "eval":
                sub = _second(p)
                if sub == "budget":
                    continue
                if sub in ("resource_accounting", "protocol", "harness", "transductive"):
                    out.append((p, "the evaluation protocol is part of the approved contract"))
                elif _eval_has_run(st, nid):
                    out.append((p, "the evaluation already launched; its command is history"))
            else:
                out.append((p, "not a documented notebook field of the spec (fail closed)"))
    return out


def _known_snapshot(store, st: dict, g: dict, rel: str, owner: dict) -> tuple[str, str] | None:
    """(digest, snapshot path) of the last bytes the engine recorded for rel."""
    rows = [r for r in read_all(store) if str(r.get("path")) == rel]
    if rows:
        last = rows[-1]
        if last.get("new_digest") and last.get("new_snapshot"):
            return str(last["new_digest"]), str(last["new_snapshot"])
    seal = None
    if owner["kind"] in ("idea", "idea_meta"):
        lane = next((l for l in st.get("lanes", []) if str(l.get("id")) == owner["lane"]), None)
        seal = (lane or {}).get("idea_seal")
    elif owner["kind"] == "node_spec":
        node = next((n for n in g.get("nodes", []) if str(n.get("id")) == owner["node"]), None)
        seal = (node or {}).get("spec_seal")
    for row in ((seal or {}).get("artifacts") or []):
        if isinstance(row, dict) and str(row.get("path")) == rel and row.get("digest") and row.get("snapshot"):
            return str(row["digest"]), str(row["snapshot"])
    return None


def _brief(value: Any) -> str:
    return "(absent)" if value is _MISSING else json.dumps(value, ensure_ascii=False)[:48]


def contract_paths_of(*configs: Any) -> set[str]:
    """Dotted config paths that the signed digest payload covers."""
    out: set[str] = set()
    for cfg in configs:
        if isinstance(cfg, dict):
            out |= set(_flatten(econfig.bootstrap_contract_payload(cfg)))
    return out


def _summarize(kind: str, old_text: str, new_text: str, paths: list[str], old: Any, new: Any) -> list[str]:
    if kind in ("idea_meta", "node_spec", "contract_facts"):
        a, b = _flatten(old), _flatten(new)
        rows = [f"{p}: {_brief(a.get(p, _MISSING))} -> {_brief(b.get(p, _MISSING))}" for p in paths[:6]]
        if len(paths) > 6:
            rows.append(f"(+{len(paths) - 6} more paths)")
        return rows
    return [f"text edited ({len(old_text.splitlines())} -> {len(new_text.splitlines())} lines)"]


def _training_replication_for(rep: dict, costly_runs: Any) -> dict:
    """The spec's training_replication block for an amended ablation design:
    one complete seed run per costly run, in both directions. Integer seed
    lists are extended with fresh integers; other seed lists are truncated
    but never invented (the validator then names the field to fill)."""
    out = dict(rep)
    runs = int(costly_runs) if isinstance(costly_runs, int) and not isinstance(costly_runs, bool) \
        and costly_runs >= 1 else 1
    seeds = list(out.get("seeds") or [])
    if len(seeds) > runs:
        seeds = seeds[:runs]
    elif len(seeds) < runs and all(isinstance(s, int) and not isinstance(s, bool) for s in seeds):
        nxt = (max(seeds) + 1) if seeds else 0
        while len(seeds) < runs:
            if nxt not in seeds:
                seeds.append(nxt)
            nxt += 1
    out["mode"] = "preplanned" if runs > 1 else "single"
    out["runs"] = runs
    out["seeds"] = seeds
    if runs > 1:
        if out.get("aggregation") not in ("mean", "median"):
            out["aggregation"] = "mean"
    else:
        out["aggregation"] = "none"   # one recorded seed aggregates nothing
    out.setdefault("source", "workflow")
    return out


def _introduced_spec_errors(engine, node: dict, before: dict, after: dict) -> list[str]:
    """Spec validator lines the propagated spec would add to what the spec
    already had (pre-existing lines are not this amendment's doing)."""
    import evalid
    ctx = engine.ctx()
    nid = str(node.get("id") or "")

    def errs(spec: dict) -> list[str]:
        try:
            return list(evalid._spec_errors(ctx, spec, expect_role=str(spec.get("role") or ""),
                                            expect_parents=None, expect_level=None,
                                            where=f"spec({nid})", exclude_node=nid))
        except Exception:  # noqa: BLE001 - the replication rules alone still decide
            return list(evalid.training_replication_errors(ctx, spec, role=str(spec.get("role") or ""),
                                                           where=f"spec({nid})"))
    had = set(errs(before))
    return [e for e in errs(after) if e not in had]


def _frozen_sota(store, meta: dict) -> dict[str, float]:
    """The beaten SOTA lines as plan_node freezes them onto the node."""
    rows = {str(r.get("id") or ""): r for r in eutil.read_jsonl(
        eutil.rpath(store.repo, ".evo/evidence/SOTA.jsonl"), lenient=True) if isinstance(r, dict)}
    out: dict[str, float] = {}
    for t in (meta.get("sota_targets") or []):
        tid = str((t or {}).get("sota") or "") if isinstance(t, dict) else ""
        hv = ((rows.get(tid) or {}).get("headline") or {}).get("value")
        if isinstance(hv, (int, float)) and not isinstance(hv, bool):
            out[tid] = float(hv)
    return out


def _plan_followups(engine, owner: dict, node: dict | None, old_obj: Any, new_obj: dict,
                    paths: list[str], *, kept: str) -> dict:
    """What else this amendment moves, computed BEFORE anything is recorded
    so a refusal has no side effects: the spec's engine-owned copies of the
    idea meta, and the node fields plan_node derived from the amended file."""
    store, st = engine.store, engine.st
    touched = {_top(p) for p in paths}
    out: dict[str, Any] = {"spec_update": None, "node_refresh": [], "notes": []}
    if node is None:
        return out
    nid = str(node.get("id") or "")
    launched = node_launched(st, nid)
    if owner["kind"] == "idea_meta":
        spec_rel = str(node.get("spec") or "")
        spec = eutil.read_json(eutil.rpath(store.repo, spec_rel), None)
        if isinstance(spec, dict) and (touched & ({"mechanism_probe"} | set(IDEA_TO_SPEC_COPIES))):
            import evalid
            updated = json.loads(json.dumps(spec))
            probe = new_obj.get("mechanism_probe") if isinstance(new_obj.get("mechanism_probe"), dict) else None
            if isinstance(updated.get("probe_execution"), dict) and probe:
                copy = dict(updated["probe_execution"])
                for field in SPEC_PROBE_CONTRACT:
                    if field in probe:
                        copy[field] = json.loads(json.dumps(probe[field]))
                updated["probe_execution"] = copy
            if "mechanism_probe" in touched and isinstance(updated.get("evidence_plan"), dict) and not launched:
                # plan-time rule: evidence_plan.extra_eval_arms equals the registered probe arms
                arms = int((probe or {}).get("extra_eval_arms") or 0) if evalid.is_probe_active(new_obj) else 0
                if updated["evidence_plan"].get("extra_eval_arms") != arms:
                    updated["evidence_plan"]["extra_eval_arms"] = arms
            for key in IDEA_TO_SPEC_COPIES:
                if key in touched and key in updated and key in new_obj:
                    updated[key] = json.loads(json.dumps(new_obj[key]))
            if "ablation" in touched and isinstance(new_obj.get("ablation"), dict) \
                    and isinstance(updated.get("training_replication"), dict):
                old_runs = ((old_obj.get("ablation") or {}).get("costly_runs")
                            if isinstance(old_obj, dict) and isinstance(old_obj.get("ablation"), dict) else None)
                new_runs = new_obj["ablation"].get("costly_runs")
                if new_runs != old_runs:
                    updated["training_replication"] = _training_replication_for(
                        updated["training_replication"], new_runs)
                    introduced = _introduced_spec_errors(engine, node, spec, updated)
                    if introduced:
                        raise SystemExit(
                            f"[evo] AMEND_SPEC_INVALID: ablation.costly_runs {old_runs} -> {new_runs} would leave "
                            f"{spec_rel} invalid; {kept}. Correct the named spec field first "
                            f"('evo amend --path {spec_rel} --from <copy> --reason ...'), then re-run:\n  - "
                            + "\n  - ".join(introduced[:8]))
            if updated != spec:
                out["spec_update"] = (spec_rel, updated)
        if not launched:
            if "metric_bridge_needed" in touched:
                want, have = bool(new_obj.get("metric_bridge_needed")), bool(node.get("needs_metric_bridge"))
                if want != have:
                    out["node_refresh"].append(("needs_metric_bridge", have, want))
            if "sota_targets" in touched:
                want_sota, have_sota = _frozen_sota(store, new_obj), dict(node.get("sota_targets_frozen") or {})
                if want_sota != have_sota:
                    out["node_refresh"].append(("sota_targets_frozen", have_sota, want_sota))
    elif owner["kind"] == "node_spec" and "cost_class" in touched and not launched:
        import eprogram
        meta = eutil.read_json(eutil.rpath(store.repo, _meta_rel_of(node)), None) or {}
        is_ablation = node.get("experiment_purpose") == "targeted_ablation"
        research_kernel = str((meta.get("novelty") or {}).get("kind") or "") in eprogram.RESEARCH_NOVELTY
        needs = not is_ablation and (research_kernel or new_obj.get("cost_class") == "heavy")
        if bool(node.get("needs_fidelity")) != needs:
            out["node_refresh"].append(("needs_fidelity", bool(node.get("needs_fidelity")), needs))
            out["node_refresh"].append(("fidelity_pending", bool(node.get("fidelity_pending")), needs))
            out["notes"].append(f"node {nid}: the fidelity audit is "
                                + ("owed (minted when the node stands at smoke_pass)" if needs
                                   else "not owed"))
    return out


def _refresh_config_blocks(engine, task: dict) -> None:
    """Card blocks that bake config facts into stored lines are rebuilt from
    the corrected config before the card is re-rendered."""
    render = task.get("_render") or {}
    blocks = render.get("extra_blocks") or []
    lane_id = str((task.get("subject") or {}).get("lane") or "")
    lane = engine.store.get_lane(engine.st, lane_id) if lane_id else None
    for i, block in enumerate(blocks):
        title = str(block[0]) if block else ""
        if title.startswith("Noise floors on the target cells") and hasattr(engine, "_noise_floor_advice"):
            blocks[i] = [title, list(engine._noise_floor_advice())]
        elif title == "Ablation allowance and sizing" and lane is not None:
            import evalid
            parents = [p for p in (lane.get("parents") or [])
                       if (engine.node(p) or {}).get("role") != "platform"]
            if len(parents) != 1:
                continue
            allowance = evalid.ablation_allowance(engine.ctx(), parents[0])
            lines = list(block[1])
            first = (f"- allowance: {allowance.get('multiple', 0):g} x what {parents[0]} cost = "
                     + (", ".join(f"{u} <= {v:g}" for u, v in sorted((allowance.get("allowed") or {}).items()))
                        or "nothing charged to the parent yet")
                     + "; one retrain is always inside it")
            if lines and str(lines[0]).startswith("- allowance:"):
                lines[0] = first
            blocks[i] = [title, lines]
    render["extra_blocks"] = blocks
    # The ablation policy line is baked into stored notes (POLICY_NOTES) and
    # blocks at mint; rebuild it from the corrected config wherever it sits.
    import etask
    fresh = etask.ablation_policy_note(engine.cfg)

    def _refresh_line(line: str) -> str:
        text = str(line)
        stripped = text.lstrip("- ").lstrip()
        if stripped.startswith(etask.ABLATION_POLICY_PREFIX):
            return text[: len(text) - len(text.lstrip("- "))] + fresh
        return text

    fields = render.get("extra_fields") or {}
    for key, value in list(fields.items()):
        if isinstance(value, str) and etask.ABLATION_POLICY_PREFIX in value:
            fields[key] = "\n".join(_refresh_line(row) for row in value.split("\n"))
    for i, block in enumerate(blocks):
        if block and any(etask.ABLATION_POLICY_PREFIX in str(row) for row in block[1]):
            blocks[i] = [block[0], [_refresh_line(row) for row in block[1]]]


def _rerender_open_cards(engine, owner: dict, *, config_facts: bool) -> tuple[list[str], list[str]]:
    """Open cards render values from these files (caps, paths, parent facts,
    config facts): rebuild them so the agent never works from a stale
    rendering. Returns (re-rendered task ids, failures)."""
    done: list[str] = []
    failed: list[str] = []
    for t in engine.st.get("tasks", []):
        if t.get("status") != "open" or t.get("type") == "stage_watch" or not t.get("_render"):
            continue
        subj = t.get("subject") or {}
        mine = (owner.get("node") and subj.get("node") == owner.get("node")) \
            or (owner.get("lane") and subj.get("lane") == owner.get("lane"))
        if not (mine or config_facts):
            continue
        try:
            if config_facts:
                _refresh_config_blocks(engine, t)
            engine._rematerialize(t)
            done.append(str(t.get("id")))
        except (SystemExit, Exception) as exc:  # noqa: BLE001 - the amendment stands; the card is reported
            failed.append(f"{t.get('id')}: {exc}")
    return done, failed


def apply(engine, rel: str, draft_rel: str | None, reason: str, *, actor: str = "agent",
          propagated_from: str | None = None) -> tuple[dict, list[str]]:
    """Record one amendment; returns (record, advisory notes).

    A refusal has no side effects: nothing is written, and an in-place edit
    is never rewritten from a snapshot (the refusal names where the recorded
    bytes are and how to re-record the intended content)."""
    store, st, g = engine.store, engine.st, engine.g
    reason = " ".join(str(reason or "").split())
    if len(reason) < 20:
        raise SystemExit("[evo] --reason needs >= 20 chars: the notebook records WHY a line was "
                         "corrected, not just that it was")
    rel = norm_rel(rel)
    owner = owner_of(store, st, g, rel)
    target = eutil.rpath(store.repo, rel)
    lane = next((l for l in st.get("lanes", []) if str(l.get("id")) == owner.get("lane")), None) \
        if owner.get("lane") else None
    node = next((n for n in g.get("nodes", []) if str(n.get("id")) == owner.get("node")), None) \
        if owner.get("node") else None
    in_place = not draft_rel
    if draft_rel:
        draft = eutil.rpath(store.repo, norm_rel(draft_rel))
        if not draft.is_file():
            raise SystemExit(f"[evo] draft {draft_rel} does not exist; --from takes the repo-relative "
                             "path of your edited copy")
        if not target.is_file():
            raise SystemExit(f"[evo] {rel} does not exist; amend corrects an existing file - check "
                             "--path ('evo status' lists lanes and nodes)")
        if draft.resolve() == target.resolve():
            raise SystemExit("[evo] --from must be a separate draft file (copy the target, edit the copy)")
        old_text, new_text = eutil.read_text(target), eutil.read_text(draft)
        if old_text == new_text:
            raise SystemExit("[evo] the draft is identical to the current file; nothing to amend - "
                             "edit the copy, then re-run 'evo amend'")
        old_digest, old_snapshot = eseal.snapshot(store.repo, rel)
    else:
        known = _known_snapshot(store, st, g, rel, owner)
        current = eseal.artifact_digest(store.repo, rel)
        if known is None:
            raise SystemExit(f"[evo] {rel} has no recorded previous version, so an in-place edit cannot "
                             "keep history. Copy the file, edit the copy, and pass --from <copy>.")
        old_digest, old_snapshot = known
        if not current:
            raise SystemExit(f"[evo] {rel} is missing or unreadable; its recorded bytes are at "
                             f"{old_snapshot} - restore from there, then edit")
        if current == old_digest:
            raise SystemExit(f"[evo] {rel} equals its recorded bytes; edit a copy and pass --from, or "
                             "edit in place first")
        old_text = eutil.read_text(eutil.rpath(store.repo, old_snapshot))
        new_text = eutil.read_text(target)
    # How a refusal leaves things: an in-place edit stays as edited (unrecorded),
    # a draft was never installed.
    kept = (f"the file keeps your edit unrecorded (doctor reports AMENDMENT_DRIFT until it is recorded; "
            f"the recorded bytes are at {old_snapshot})" if in_place else "nothing was written")
    re_record = (f"restore the recorded bytes from {old_snapshot}, put the intended content in a copy and "
                 f"re-record it with 'evo amend --path {rel} --from <copy> --reason ...'" if in_place
                 else "edit the draft and re-run 'evo amend'")
    old_obj = new_obj = None
    paths: list[str] = []
    followups: dict[str, Any] = {"spec_update": None, "node_refresh": [], "notes": []}
    if owner["kind"] in ("idea_meta", "node_spec", "contract_facts"):
        try:
            old_obj, new_obj = json.loads(old_text), json.loads(new_text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"[evo] {rel}: the new bytes are not valid JSON ({exc}); {kept} - fix the JSON, "
                             f"then {re_record}") from exc
        paths = changed_paths(old_obj, new_obj)
        contract_paths = contract_paths_of(old_obj, new_obj) if owner["kind"] == "contract_facts" else None
        frozen = frozen_paths(owner["kind"], paths, st=st, node=node,
                              new_spec=new_obj if owner["kind"] == "node_spec" else None,
                              contract_paths=contract_paths)
        if owner["kind"] == "contract_facts" and actor != "engine" and any(
                p == AUTONOMY_PATH or p.startswith(AUTONOMY_PATH + ".") for p in paths):
            before_mode = ((old_obj or {}).get("policy") or {}).get("autonomy") if isinstance(old_obj, dict) else None
            after_mode = ((new_obj or {}).get("policy") or {}).get("autonomy") if isinstance(new_obj, dict) else None
            raise SystemExit(f"[evo] AMEND_SUPERVISION: policy.autonomy ({before_mode} -> {after_mode}) has its own "
                             f"verb - 'evo autonomy {after_mode} --note \"...\"' validates the result, records the "
                             f"switch in the event trail and in this ledger, and re-evaluates open gates; {kept}. "
                             f"If the file already shows the live mode, that same command re-records the file on "
                             f"this ledger. Any other correction in the same draft goes through 'evo amend' "
                             f"afterwards.")
        if frozen and actor != "engine":
            # Any change to a frozen field is refused - there is no spelling
            # exception: what a settlement reads is compared literally, and a
            # file that reads the same way needs no amendment.
            listing = "\n  - ".join(f"{p}: {why}" for p, why in frozen[:12])
            raise SystemExit("[evo] AMEND_FROZEN: these fields are history, not notebook material:\n  - "
                             + listing
                             + (f"\nall changed paths: {', '.join(paths[:12])}"
                                + (f" (+{len(paths) - 12} more)" if len(paths) > 12 else "")
                                if in_place else "")
                             + f"\n{kept[0].upper() + kept[1:]}; {re_record}."
                             + "\nA settled record that is WRONG is re-judged by 'evo recover-plan'; "
                               "everything else in the file stays amendable.")
        if owner["kind"] == "contract_facts":
            # The correction may not make the contract worse than it was: any
            # deficiency it introduces is refused with the validator's words.
            before = set(econfig.validate_config(old_obj) + econfig.preset_conflicts(old_obj)) \
                if isinstance(old_obj, dict) else set()
            after = (econfig.validate_config(new_obj) + econfig.preset_conflicts(new_obj)) \
                if isinstance(new_obj, dict) else ["not an object"]
            introduced = [e for e in after if e not in before]
            if introduced:
                raise SystemExit(f"[evo] the corrected config would be invalid; {kept} - {re_record}:\n  - "
                                 + "\n  - ".join(str(e) for e in introduced[:12]))
        if isinstance(new_obj, dict):
            followups = _plan_followups(engine, owner, node, old_obj, new_obj, paths, kept=kept)
    elif owner["kind"] == "dossier":
        import evalid
        for label, rx in (("B", evalid.B_ID), ("V", evalid.V_ID), ("F", evalid.F_ID)):
            lost = sorted(set(rx.findall(old_text)) - set(rx.findall(new_text)))
            if lost:
                raise SystemExit(f"[evo] AMEND_DOSSIER_IDS: the dossier vocabulary is append-only; "
                                 f"{label}# ids {lost} may be reworded but never removed; {kept} - keep "
                                 f"them, then {re_record}")
    if draft_rel:
        eutil.write_text_atomic(target, new_text)
    new_digest, new_snapshot = eseal.snapshot(store.repo, rel)
    rec = {
        "id": store.next_id(st, "AM"), "at": eutil.utc_now(), "actor": actor,
        "path": rel, "kind": owner["kind"], "lane": owner.get("lane"), "node": owner.get("node"),
        "idea": owner.get("idea"), "reason": reason,
        "old_digest": old_digest, "old_snapshot": old_snapshot,
        "new_digest": new_digest, "new_snapshot": new_snapshot,
        "changed": _summarize(owner["kind"], old_text, new_text, paths, old_obj, new_obj),
        "phase": {"lane_status": (lane or {}).get("status"), "node_status": (node or {}).get("status"),
                  "launched": bool(node and node_launched(st, str(node.get("id"))))},
    }
    if propagated_from:
        rec["propagated_from"] = propagated_from
    if followups["node_refresh"]:
        rec["node_refresh"] = [f"{field}: {json.dumps(a, sort_keys=True)} -> {json.dumps(b, sort_keys=True)}"
                               for field, a, b in followups["node_refresh"]]
    eutil.append_jsonl(eutil.rpath(store.repo, AMENDMENTS_REL), rec)
    store.event(actor, "amendment_recorded", amendment=rec["id"], path=rel, kind=owner["kind"],
                lane=owner.get("lane"), node=owner.get("node"), reason=reason[:200])
    warnings: list[str] = []
    if owner["kind"] == "contract_facts":
        warnings.append(RULER_NOTE)
    # Every engine-owned copy in the node spec follows the idea meta (the probe
    # contract, the effect case, the instrumental contracts), so the two files
    # never disagree about the bet.
    if followups["spec_update"] is not None:
        spec_rel, updated = followups["spec_update"]
        spec_path = eutil.rpath(store.repo, spec_rel)
        draft = spec_path.with_name("NODE_SPEC.amend-draft.json")
        eutil.write_json_atomic(draft, updated)
        try:
            sub, _ = apply(engine, spec_rel, eutil.rel(store.repo, draft),
                           f"engine propagation of {rec['id']}: the idea's amended contract objects "
                           "are copied into the spec's engine-owned fields", actor="engine",
                           propagated_from=rec["id"])
            warnings.append(f"propagated into {spec_rel} as {sub['id']}")
        finally:
            try:
                draft.unlink()
            except OSError:
                pass
    # The node fields plan_node derived from the amended file follow it while
    # the node has not launched (plain copies and derivations only).
    for field, _before, after in followups["node_refresh"]:
        node[field] = after
    for line in rec.get("node_refresh") or []:
        warnings.append(f"node {node.get('id')}: {line}")
    warnings.extend(followups["notes"])
    if owner["kind"] == "idea_meta" and lane is not None and \
            str(lane.get("experiment_purpose") or "candidate") in ("candidate", "exploratory"):
        import evalid
        idea_md = f".evo/ideas/{owner['idea']}.md"
        try:
            advisory = evalid.v_mature(engine.ctx(), {"subject": {"lane": lane.get("id")},
                                                      "outputs": [idea_md, rel]})
        except (SystemExit, Exception) as exc:  # noqa: BLE001 - advice, never a crash
            advisory = [f"the mature validator could not be replayed here: {exc}"]
        warnings.extend(f"advisory (the mature validator would now say): {e}" for e in advisory[:8])
    config_facts = owner["kind"] == "contract_facts"
    if config_facts:
        engine.cfg = store.load_config()   # every open card reads the corrected facts
    rerendered, failed = _rerender_open_cards(engine, owner, config_facts=config_facts)
    if rerendered:
        warnings.append("open cards re-rendered from the corrected file: " + ", ".join(rerendered))
    warnings.extend(f"card not re-rendered ({f}); 'evo render' rebuilds it" for f in failed)
    return rec, warnings


def record_config_write(store, st: dict, *, old: tuple[str, str], reason: str, changed: list[str],
                        actor: str = "user") -> dict:
    """Append the ledger row for a config write made by another blessed verb
    (`evo autonomy`): `old` is the (digest, snapshot) taken before the write.
    The latest recorded digest then equals the live file, so the next in-place
    amendment diffs against the bytes actually on disk."""
    new_digest, new_snapshot = eseal.snapshot(store.repo, CONFIG_REL)
    old_digest, old_snapshot = old
    rec = {
        "id": store.next_id(st, "AM"), "at": eutil.utc_now(), "actor": actor,
        "path": CONFIG_REL, "kind": "contract_facts", "lane": None, "node": None, "idea": None,
        "reason": " ".join(str(reason or "").split()),
        "old_digest": old_digest, "old_snapshot": old_snapshot,
        "new_digest": new_digest, "new_snapshot": new_snapshot,
        "changed": [str(x) for x in changed],
        "phase": {"lane_status": None, "node_status": None, "launched": False},
    }
    eutil.append_jsonl(eutil.rpath(store.repo, AMENDMENTS_REL), rec)
    store.event(actor, "amendment_recorded", amendment=rec["id"], path=CONFIG_REL, kind="contract_facts",
                lane=None, node=None, reason=rec["reason"][:200])
    return rec


def integrity_problems(store) -> list[str]:
    """Doctor view: every recorded amendment keeps both snapshots, and an
    amended file was not edited again behind the ledger's back."""
    problems: list[str] = []
    latest: dict[str, dict] = {}
    for row in read_all(store):
        rid = str(row.get("id") or "?")
        for key in ("old_snapshot", "new_snapshot"):
            snap = str(row.get(key) or "")
            want = str(row.get(key.replace("snapshot", "digest")) or "")
            if not snap or eseal.artifact_digest(store.repo, snap) != want:
                problems.append(f"AMENDMENT_SNAPSHOT: {rid} {key} for {row.get('path')} is missing or "
                                "does not match its recorded digest")
        latest[str(row.get("path"))] = row
    for path, row in latest.items():
        current = eseal.artifact_digest(store.repo, path)
        if current and current != str(row.get("new_digest") or ""):
            problems.append(f"AMENDMENT_DRIFT: {path} was edited after {row.get('id')} without a recorded "
                            "amendment ('evo amend' keeps the history; a hand edit does not)")
    return problems


PROJECT_ROW_LABELS = {"contract_facts": "project fact", "profile": "project profile",
                      "dossier": "problem dossier", "rubric": "innovation rubric"}
PROJECT_FACTS_HEADING = "Project facts corrected (floors / margins / required / ablation allowance):"


def _history_row(r: dict) -> str:
    phase = r.get("phase") or {}
    kind = str(r.get("kind") or "")
    if kind in PROJECT_ROW_LABELS:
        when = PROJECT_ROW_LABELS[kind]
    else:
        when = ("after production launch" if phase.get("launched") else "before production launch")
        when += f"; status {phase.get('node_status') or phase.get('lane_status') or '-'}"
    changed = "; ".join(str(x) for x in (r.get("changed") or [])[:3]) or "-"
    return (f"- {r.get('id')} {str(r.get('at') or '')[:16]} `{r.get('path')}` [{when}]"
            f" {changed} | reason: {r.get('reason')}")


def history_lines(store, *, lane: str | None = None, node: str | None = None,
                  idea: str | None = None, project: bool = False, limit: int = 10) -> list[str]:
    """Reviewer-facing correction history (empty when none).

    Subject rows (lane / node / idea): corrections after production launch are
    itemized, corrections before it are folded into one count line with their
    ids. Project rows (`project=True`: config facts, profile, dossier, rubric)
    are itemized after them; called with `project=True` alone the list carries
    no heading - the caller places it under its own."""
    subject_rows = for_subject(store, lane=lane, node=node, idea=idea) if (lane or node or idea) else []
    project_rows = for_subject(store, project=True) if project else []
    out: list[str] = []
    if subject_rows:
        out += ["Corrections recorded on this subject (append-only; the sealed original and every",
                "earlier version are kept as snapshots). Judge the current text, weigh WHEN each",
                "change was made against what had already been measured, and open a snapshot only",
                "when the timing looks suspicious:"]
        early = [r for r in subject_rows if not (r.get("phase") or {}).get("launched")]
        late = [r for r in subject_rows if (r.get("phase") or {}).get("launched")]
        if early:
            ids = [str(r.get("id")) for r in early]
            shown = ", ".join(ids[:8]) + (f", +{len(ids) - 8} more" if len(ids) > 8 else "")
            out.append(f"- {len(early)} correction(s) before production launch ({shown}; full rows in "
                       f"`{AMENDMENTS_REL}`)")
        if len(late) > limit:
            out.append(f"- ({len(late) - limit} older post-launch corrections omitted; full ledger at "
                       f"`{AMENDMENTS_REL}`)")
        out += [_history_row(r) for r in late[-limit:]]
    if project_rows:
        if subject_rows:
            out.append(PROJECT_FACTS_HEADING)
        if any(r.get("kind") == "contract_facts" for r in project_rows):
            out.append(f"- forward-only: {RULER_NOTE}")
        if len(project_rows) > limit:
            out.append(f"- ({len(project_rows) - limit} older project corrections omitted; full ledger at "
                       f"`{AMENDMENTS_REL}`)")
        out += [_history_row(r) for r in project_rows[-limit:]]
    return out
