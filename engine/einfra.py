"""Infrastructure facts: machine-readable knowledge about WHERE this project runs,
trains, stores data and checkpoints, and how jobs are submitted/watched (v8).

The `infra` bootstrap task distills the user's knowledge base (config project.docs)
plus the repo into .evo/profile/INFRA_FACTS.json. Every fact carries `src` paths so
claims stay auditable. The engine consumes two facts mechanically:
  - compute.max_concurrent_stage_jobs -> workflow slots for the scheduler
  - artifact_store.uri_template       -> every producing stage's output URI must
    instantiate this template uniquely (collision = validation error)
"""
from __future__ import annotations

from typing import Any

import eutil

REQUIRED_BLOCKS = ("workspace", "compute", "data", "artifact_store", "evaluation")

# v10.1: fields whose VALUES the engine never reads (workspace.agent_runs_on,
# workspace.code_lives_at, data.access_pattern) are no longer mandatory prose.
# The blocks themselves, their [src] grounding and every mechanically consumed
# field (slots, uri_template, result keys, service names/pinning) keep their
# full duty; agents may still record the optional fields for the user's review.
_BLOCK_FIELDS: dict[str, list[str]] = {
    "workspace": [],
    "compute": ["kind", "submit_pattern", "status_cmd", "logs_cmd"],
    "data": ["kind"],
    "artifact_store": ["kind", "uri_template", "collision_rule"],
    "evaluation": ["how", "primary_metric_key"],
}


def facts_path(store, cfg: dict) -> Any:
    rel = str((cfg.get("infra") or {}).get("facts_file") or ".evo/profile/INFRA_FACTS.json")
    return eutil.rpath(store.repo, rel)


def load_facts(store, cfg: dict) -> dict | None:
    p = facts_path(store, cfg)
    return eutil.read_json(p, None) if p.exists() else None


def validate_facts(store, facts: Any) -> list[str]:
    errs: list[str] = []
    if not isinstance(facts, dict):
        return ["INFRA_NOT_OBJECT: INFRA_FACTS.json must be a JSON object"]
    for block in REQUIRED_BLOCKS:
        b = facts.get(block)
        if not isinstance(b, dict):
            errs.append(f"INFRA_BLOCK_MISSING: '{block}' object required")
            continue
        for f in _BLOCK_FIELDS[block]:
            if not str(b.get(f) or "").strip():
                errs.append(f"INFRA_FIELD: {block}.{f} must be filled in")
        src = b.get("src")
        if not isinstance(src, list) or not src:
            errs.append(f"INFRA_SRC_MISSING: {block}.src must list >= 1 source path (knowledge-base doc or repo file)")
        else:
            bad = [s for s in src if not eutil.rpath(store.repo, str(s)).exists()]
            if bad:
                errs.append(f"INFRA_SRC_UNRESOLVED: {block}.src paths do not exist: {bad[:3]}")
    comp = facts.get("compute") or {}
    if isinstance(comp, dict):
        mct = comp.get("max_concurrent_stage_jobs")
        if not isinstance(mct, int) or mct < 1:
            errs.append("INFRA_SLOTS: compute.max_concurrent_stage_jobs must be int >= 1 "
                        "(how many scheduler-visible workflow jobs the platform allows at once)")
    ast = facts.get("artifact_store") or {}
    if isinstance(ast, dict):
        tpl = str(ast.get("uri_template") or "")
        if tpl and "{run_id}" not in tpl:
            errs.append("INFRA_URI_TEMPLATE: artifact_store.uri_template must contain the literal placeholder "
                        "'{run_id}' - the per-run unique segment that prevents checkpoint overwrites")
    data = facts.get("data") or {}
    if isinstance(data, dict):
        ds = data.get("datasets")
        if not isinstance(ds, list) or not ds:
            errs.append("INFRA_DATASETS: data.datasets must list >= 1 dataset")
        else:
            seen_datasets: set[str] = set()
            for i, d in enumerate(ds):
                if not isinstance(d, dict):
                    errs.append(f"INFRA_DATASET_SHAPE: data.datasets[{i}] must be an object")
                    continue
                for f in ("name", "uri", "role"):
                    if not str((d or {}).get(f) or "").strip():
                        errs.append(f"INFRA_DATASET_FIELD: data.datasets[{i}].{f} required (role: what stage/purpose uses it)")
                name = str((d or {}).get("name") or "").strip()
                if name and name in seen_datasets:
                    errs.append(f"INFRA_DATASET_DUP: data.datasets[{i}] duplicates name {name!r}; "
                                "canary surfaces require unique dataset names")
                seen_datasets.add(name)
    ev = facts.get("evaluation") or {}
    if isinstance(ev, dict):
        keys = ev.get("result_keys")
        if not isinstance(keys, list) or not keys or any(not str(k).strip() for k in keys) \
                or len(set(str(k) for k in keys)) != len(keys):
            errs.append("INFRA_EVAL_RESULT_KEYS: evaluation.result_keys must be a non-empty unique list of metrics.json keys")
    # optional LLM block (v8): serving endpoints / API access / token budget for
    # inference- and api-class experiments. Optional, but if present it must be
    # substantive and sourced like every other block.
    llm = facts.get("llm")
    if llm is not None:
        if not isinstance(llm, dict):
            errs.append("INFRA_LLM: optional 'llm' block must be an object")
        else:
            # Only the block's existence gates requires_services=["llm"]; its
            # kind/invoke_pattern values had no engine reader (v10.1 optional).
            src = llm.get("src")
            if not isinstance(src, list) or not src:
                errs.append("INFRA_LLM_SRC: llm.src must list >= 1 source path")
            else:
                bad = [s for s in src if not eutil.rpath(store.repo, str(s)).exists()]
                if bad:
                    errs.append(f"INFRA_LLM_SRC_UNRESOLVED: llm.src paths do not exist: {bad[:3]}")
    # optional SERVICES registry (v8): non-LLM runtime dependencies experiments
    # lean on - a SPARQL/graph endpoint (KGQA), a vector store, an execution
    # sandbox, a simulator. Specs declare requires_services against these names;
    # the integrated bootstrap canary must have called each one.
    svcs = facts.get("services")
    if svcs is not None:
        if not isinstance(svcs, list):
            errs.append("INFRA_SERVICES: optional 'services' must be a list of service objects")
        else:
            seen: set[str] = set()
            for i, sv in enumerate(svcs):
                if not isinstance(sv, dict):
                    errs.append(f"INFRA_SERVICE_SHAPE: services[{i}] must be an object")
                    continue
                pinning = str(sv.get("pinning") or "")
                if pinning and pinning not in ("live", "recorded"):
                    errs.append(f"INFRA_SERVICE_PINNING: services[{i}].pinning must be live|recorded "
                                "(E3: 'recorded' arms the service_snapshot replay duty)")
                name = str((sv or {}).get("name") or "")
                if not name or not name.replace("-", "").replace("_", "").isalnum():
                    errs.append(f"INFRA_SERVICE_NAME: services[{i}] needs a slug 'name' (e.g. 'kg-endpoint')")
                if name in seen:
                    errs.append(f"INFRA_SERVICE_DUP: services[{i}] duplicates name '{name}'")
                seen.add(name)
                src = (sv or {}).get("src")
                if not isinstance(src, list) or not src:
                    errs.append(f"INFRA_SERVICE_SRC: services[{i}].src must list >= 1 source path")
                else:
                    bad = [s for s in src if not eutil.rpath(store.repo, str(s)).exists()]
                    if bad:
                        errs.append(f"INFRA_SERVICE_SRC_UNRESOLVED: services[{i}].src paths do not exist: {bad[:3]}")
    return errs


def service_names(store, cfg: dict, g: dict | None = None) -> set[str]:
    """Names a spec's requires_services may bind to: services declared in the
    infra facts, 'llm' when the llm block exists, and services STOOD UP by
    concluded-enabled platform nodes mid-run (a trained PRM/verifier endpoint,
    a tool server) - the dynamic extension of the bootstrap registry."""
    facts = load_facts(store, cfg) or {}
    names = {str((sv or {}).get("name") or "") for sv in (facts.get("services") or [])
             if isinstance(sv, dict)}
    names.discard("")
    if isinstance(facts.get("llm"), dict):
        names.add("llm")
    for n in (g or {}).get("nodes", []):
        if n.get("role") == "platform" and n.get("verdict") == "enabled" \
                and n.get("retire_reason") is None:
            for sv in n.get("enabled_services") or []:
                nm = str((sv or {}).get("name") or "")
                if nm:
                    names.add(nm)
    return names


def recorded_service_names(store, cfg: dict) -> set[str]:
    """Names of services whose facts entry declares pinning="recorded" (E3)."""
    facts = load_facts(store, cfg) or {}
    out: set[str] = set()
    for row in (facts.get("services") or []) if isinstance(facts.get("services"), list) else []:
        if isinstance(row, dict) and str(row.get("pinning") or "") == "recorded" \
                and str(row.get("name") or ""):
            out.add(str(row["name"]))
    return out


def slots_from_facts(store, cfg: dict, *, facts: dict | None = None) -> int:
    facts = facts if facts is not None else load_facts(store, cfg)
    if facts:
        comp = facts.get("compute") or {}
        v = comp.get("max_concurrent_stage_jobs")
        if isinstance(v, int) and v >= 1:
            return v
    infra = cfg.get("infra") or {}
    v = infra.get("max_concurrent_stage_jobs")
    return v if isinstance(v, int) and v >= 1 else 1


def infra_block(store, cfg: dict) -> list[str]:
    """Bundle block summarizing infra facts for task cards."""
    facts = load_facts(store, cfg)
    if not facts:
        return ["- INFRA_FACTS.json not written yet"]
    out = []
    comp = facts.get("compute") or {}
    out.append(f"- compute: {comp.get('kind')} | submit: {comp.get('submit_pattern')} | "
               f"stage slots: {comp.get('max_concurrent_stage_jobs')}")
    out.append(f"- status: {comp.get('status_cmd')} | logs: {comp.get('logs_cmd')}")
    ast = facts.get("artifact_store") or {}
    out.append(f"- artifact store: {ast.get('kind')} | uri_template: {ast.get('uri_template')}")
    out.append(f"- collision rule: {ast.get('collision_rule')}")
    data = facts.get("data") or {}
    for d in (data.get("datasets") or [])[:8]:
        out.append(f"- dataset '{d.get('name')}' role={d.get('role')} uri={d.get('uri')}")
    ev = facts.get("evaluation") or {}
    out.append(f"- evaluation: {ev.get('how')} | display result: {ev.get('primary_metric_key')} "
               f"| all result keys: {ev.get('result_keys')}")
    return out
