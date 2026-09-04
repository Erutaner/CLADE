"""v11.7 structural-round regressions.

Unit pins for the bootstrap/rehearsal/revision restructuring (mock_drive
exercises the composed paths; these pin the load-bearing mechanics):
  - engine-fit: four-assumption coverage, evidence duty, overall derivation
    (F0 violated = unfit), readiness worklist duty
  - provision: a 'ready' verdict needs a captured first real number; blocked
    needs typed blockers
  - canary plans: single object vs command list, both-forms refusal, count
    cap, per-command validation; joint surface coverage merging
  - rehearsal: the duty predicate, plan validation, consumer read-back duty,
    receipt authentication + implementation-seal binding, REAL engine-executed
    tiny pass (subprocess) incl. idempotent reuse and stale-seal refusal
  - doctor: INFRA_FACTS_SUSPECT (distinct repeated fixes on one surface) and
    INFRA_REVISION_PENDING disclosure
  - scheduler helpers: _engine_fit_overall / _provision_needed readers
"""
import json
import shutil
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))
from _check import check, done  # noqa: E402

import ecanary    # noqa: E402
import edoctor    # noqa: E402
import erehearsal  # noqa: E402
import esched     # noqa: E402
import estore     # noqa: E402
import eutil      # noqa: E402
import evalid     # noqa: E402
import mock_drive as M  # noqa: E402


def _repo(tag):
    repo = HERE / f"v117-{tag}-{uuid.uuid4().hex[:8]}"
    repo.mkdir()
    return repo


def _scan_ctx(repo, readiness_mode="certified_running", fit=None):
    store = estore.Store(repo)
    d = SimpleNamespace(repo=repo)
    (repo / "README.md").write_text("fake project readme\n", encoding="utf-8")
    (repo / "eval.py").write_text("print('eval')\n", encoding="utf-8")
    for rel in ("docs/kb/platform.md", "docs/kb/data.md", "docs/kb/metrics.md"):
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("kb\n", encoding="utf-8")
    out = {"outputs": [".evo/profile/PROJECT_DISCOVERY.md", ".evo/profile/PROJECT_DISCOVERY.json"]}
    M.w_project_scan(d, out, readiness_mode=readiness_mode, fit=fit)
    ctx = evalid.Ctx(store, store.load_state(), store.load_config(),
                     store.load_graph(), store.load_artifacts())
    task = {"outputs": out["outputs"]}
    return ctx, task, d, out


def _fit_rows(**overrides):
    rows = []
    for fid in ("F0", "F5", "F6", "F7"):
        row = {"id": fid, "verdict": "holds", "evidence": ["README.md"],
               "note": M.long(45, f"assumption {fid} verified against the scanned project facts")}
        row.update(overrides.get(fid, {}))
        rows.append(row)
    return rows


# ----------------------------------------------------------- engine-fit ----
def engine_fit_validation() -> None:
    repo = _repo("fit")
    try:
        estore.Store(repo).init("t", "g")
        ctx, task, d, out = _scan_ctx(repo)
        check(evalid.v_project_scan(ctx, task) == [],
              "a fit-clean certified scan validates cleanly")
        M.w_project_scan(d, out, fit={"assumptions": _fit_rows()[:3], "overall": "fit"})
        errs = evalid.v_project_scan(ctx, task)
        check(any("DISCOVERY_FIT_COVERAGE" in e for e in errs),
              "all four assumptions must be judged - missing F7 is refused")
        M.w_project_scan(d, out, fit={
            "assumptions": _fit_rows(F0={"verdict": "violated",
                                         "consequence_if_wrong": M.long(45, "every later step would fail to name a dataset or metric")}),
            "overall": "degraded"})
        errs = evalid.v_project_scan(ctx, task)
        check(any("DISCOVERY_FIT_OVERALL" in e and "unfit" in e for e in errs),
              "F0 violated derives overall=unfit mechanically - degraded is refused")
        M.w_project_scan(d, out, fit={
            "assumptions": _fit_rows(F5={"verdict": "uncertain"}), "overall": "degraded"})
        errs = evalid.v_project_scan(ctx, task)
        check(any("consequence_if_wrong" in e for e in errs),
              "an uncertain verdict owes its consequence_if_wrong")
        M.w_project_scan(d, out, readiness_mode="needs_preparation")
        disc = json.loads((repo / ".evo/profile/PROJECT_DISCOVERY.json").read_text(encoding="utf-8"))
        disc["readiness"].pop("worklist")
        eutil.write_json_atomic(repo / ".evo/profile/PROJECT_DISCOVERY.json", disc)
        errs = evalid.v_project_scan(ctx, task)
        check(any("DISCOVERY_READINESS_WORKLIST" in e for e in errs),
              "needs_preparation owes a concrete worklist")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ----------------------------------------------------- scheduler helpers ----
def scheduler_fit_readers() -> None:
    repo = _repo("readers")
    try:
        estore.Store(repo).init("t", "g")
        ns = SimpleNamespace(store=SimpleNamespace(repo=repo))
        check(esched.Engine._engine_fit_overall(ns) == "", "no discovery yet reads as ''")
        check(esched.Engine._provision_needed(ns) is False,
              "no discovery yet reads as certified (legacy projects keep their sequence)")
        d = SimpleNamespace(repo=repo)
        (repo / "README.md").write_text("r\n", encoding="utf-8")
        (repo / "eval.py").write_text("e\n", encoding="utf-8")
        for rel in ("docs/kb/platform.md", "docs/kb/data.md", "docs/kb/metrics.md"):
            p = repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("kb\n", encoding="utf-8")
        out = {"outputs": [".evo/profile/PROJECT_DISCOVERY.md", ".evo/profile/PROJECT_DISCOVERY.json"]}
        M.w_project_scan(d, out, readiness_mode="needs_preparation")
        check(esched.Engine._provision_needed(ns) is True, "needs_preparation arms the provision step")
        check(esched.Engine._engine_fit_overall(ns) == "fit", "the fit overall reads through")
        rows = esched.Engine._discovery_worklist(ns)
        check(any("wire the frozen validation dataset" in r for r in rows),
              "the worklist renders for the provision bundle")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ------------------------------------------------------------- provision ----
def provision_validation() -> None:
    repo = _repo("prov")
    try:
        estore.Store(repo).init("t", "g")
        store = estore.Store(repo)
        d = SimpleNamespace(repo=repo)
        (repo / "data.py").write_text("# loader\n", encoding="utf-8")
        out = {"outputs": [".evo/profile/PROVISION.md", ".evo/profile/PROVISION.json"]}
        ctx = evalid.Ctx(store, store.load_state(), store.load_config(),
                         store.load_graph(), store.load_artifacts())
        task = {"outputs": out["outputs"]}
        M.w_provision(d, out)
        check(evalid.v_provision(ctx, task) == [], "a proven ready verdict validates cleanly")
        M.w_provision(d, out, bad="no_metric")
        errs = evalid.v_provision(ctx, task)
        check(any("PROVISION_METRIC" in e for e in errs),
              "ready without a captured real number is narration, refused")
        M.w_provision(d, out, status="blocked", bad="empty_block")
        errs = evalid.v_provision(ctx, task)
        check(any("PROVISION_BLOCKERS" in e for e in errs),
              "blocked without typed blockers is indistinguishable from giving up")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ---------------------------------------------------------- canary plans ----
def canary_plan_forms() -> None:
    repo = _repo("plan")
    try:
        store = SimpleNamespace(repo=repo)
        single = {"schema": 1, "canary": {
            "command": "python x.py", "cwd": ".", "timeout_s": 60,
            "description": "x" * 60}}
        check(ecanary.plan_errors(store, single) == [], "the historical single form still validates")
        check(len(ecanary.plan_commands(single)) == 1, "single form normalizes to one command")
        multi = {"schema": 1, "canaries": [
            {"command": "python a.py", "cwd": ".", "timeout_s": 60, "description": "a" * 60},
            {"command": "python b.py", "cwd": ".", "timeout_s": 60, "description": "b" * 60}]}
        check(ecanary.plan_errors(store, multi) == [], "a two-command list validates")
        check(len(ecanary.plan_commands(multi)) == 2, "list form normalizes to its commands")
        both = dict(single)
        both["canaries"] = multi["canaries"]
        errs = ecanary.plan_errors(store, both)
        check(any("CANARY_PLAN_FORM" in e for e in errs), "declaring both forms is refused")
        crowd = {"schema": 1, "canaries": [dict(multi["canaries"][0]) for _ in range(7)]}
        errs = ecanary.plan_errors(store, crowd)
        check(any("CANARY_PLAN_COUNT" in e for e in errs),
              "more than six commands is fragmentation, refused")
        bad = {"schema": 1, "canaries": [multi["canaries"][0],
                                         {"command": "python b.py", "cwd": ".",
                                          "timeout_s": "60s", "description": "b" * 60}]}
        errs = ecanary.plan_errors(store, bad)
        check(any("CANARY_PLAN_TIMEOUT" in e and "canaries[1]" in e for e in errs),
              "per-command validation names the offending list entry")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def canary_joint_coverage() -> None:
    surfaces = ["workspace", "compute", "data", "artifact_store", "evaluation"]
    cfg = {"metrics": [], "evaluation_contract": {}}
    obs_a = {"nonce": "n1", "checks": [
        {"surface": s, "status": "pass", "detail": "d" * 25} for s in surfaces[:2]]}
    obs_b = {"nonce": "n1", "checks": [
        {"surface": s, "status": "pass", "detail": "d" * 25} for s in surfaces[2:]],
        "metrics": {}}
    merged: dict = {}
    errs_all: list = []
    for obs in (obs_a, obs_b):
        shape_errs, by_surface, _m = ecanary._observation_shape_errors(obs, nonce="n1")
        errs_all.extend(shape_errs)
        merged.update(by_surface)
    check(errs_all == [], "both halves are shape-clean under the shared nonce")
    cov = ecanary._coverage_errors(merged, {}, surfaces=surfaces, cfg=cfg)
    check(cov == [], "jointly the two halves cover every surface")
    cov = ecanary._coverage_errors(
        {k: v for k, v in merged.items() if k != "data"}, {}, surfaces=surfaces, cfg=cfg)
    check(any("CANARY_SURFACE_MISSING" in e and "data" in e for e in cov),
          "a surface neither command covered is still refused")
    single = ecanary._observation_errors(obs_a, nonce="n1", surfaces=surfaces, cfg=cfg)
    check(any("CANARY_SURFACE_MISSING" in e for e in single),
          "the historical single-observation contract is unchanged (partial coverage fails)")


# -------------------------------------------------------------- rehearsal ----
_REH_SPEC = {"workdir": ".",
             "workflow": {"stages": [{"name": "train", "metrics_file": "m.json"},
                                     {"name": "distill", "metrics_file": "m2.json"}]},
             "rehearsal": {"command": "python adapter.py", "timeout_s": 300,
                           "description": "r" * 60}}


def rehearsal_predicates_and_plan() -> None:
    cfg_on = {"project": {"rehearsal": "full_chain"}}
    cfg_off = {"project": {"rehearsal": "none"}}
    node = {"id": "N9", "role": "variant"}
    check(erehearsal.required(cfg_on, node, _REH_SPEC) is True,
          "full_chain + stages + non-baseline owes the rehearsal")
    check(erehearsal.required(cfg_off, node, _REH_SPEC) is False, "an explicit waiver is honored")
    check(erehearsal.required(cfg_on, {"id": "N1", "role": "baseline"}, _REH_SPEC) is False,
          "the baseline is exempt (proven by provision + canary + smoke)")
    check(erehearsal.required(cfg_on, node, {"workflow": {"stages": []}}) is False,
          "no stages = no full-scale stage spend = no duty")
    errs = erehearsal.plan_errors({"workflow": _REH_SPEC["workflow"]}, where="w")
    check(any("SPEC_REHEARSAL:" in e for e in errs), "a missing rehearsal block is refused at planning")
    bad = dict(_REH_SPEC)
    bad["rehearsal"] = {**_REH_SPEC["rehearsal"], "status": "passed"}
    errs = erehearsal.plan_errors(bad, where="w")
    check(any("SPEC_REHEARSAL_OWNERSHIP" in e for e in errs),
          "the spec may never author the rehearsal outcome")


def rehearsal_observation_contract() -> None:
    cfg = {"metrics": [], "evaluation_contract": {}}
    stages = ["train", "distill"]
    good = {"nonce": "n", "checks": [
        {"stage": s, "status": "pass", "detail": "d" * 25,
         "read_back_by": "the distill loader re-read the checkpoint and logged its shape"}
        for s in stages], "metrics": {}}
    check(erehearsal._observation_errors(good, nonce="n", stages=stages, cfg=cfg) == [],
          "a full pass with consumer read-back proof validates")
    no_rb = {"nonce": "n", "checks": [
        {"stage": s, "status": "pass", "detail": "d" * 25} for s in stages], "metrics": {}}
    errs = erehearsal._observation_errors(no_rb, nonce="n", stages=stages, cfg=cfg)
    check(sum("REHEARSAL_READBACK" in e for e in errs) == 2,
          "every stage owes its consumer read-back - writer self-reads do not count")
    partial = {"nonce": "n", "checks": [good["checks"][0]], "metrics": {}}
    errs = erehearsal._observation_errors(partial, nonce="n", stages=stages, cfg=cfg)
    check(any("REHEARSAL_STAGE_MISSING" in e and "distill" in e for e in errs),
          "the tiny pass must traverse the ENTIRE workflow")


_REH_ADAPTER = '''import json, os
req = json.loads(open(os.environ["EVO_REHEARSAL_REQUEST"], encoding="utf-8").read())
obs = {"nonce": os.environ["EVO_REHEARSAL_NONCE"],
       "checks": [{"stage": s, "status": "pass",
                   "detail": "tiny real stage executed and produced its artifact",
                   "read_back_by": "the next stage loader re-read the artifact and verified shape"}
                  for s in req["stages"]],
       "metrics": {}}
open(os.environ["EVO_REHEARSAL_RESULT"], "w", encoding="utf-8").write(json.dumps(obs))
'''


def rehearsal_real_execution() -> None:
    repo = _repo("reh")
    try:
        estore.Store(repo).init("t", "g")
        store = estore.Store(repo)
        (repo / "adapter.py").write_text(_REH_ADAPTER, encoding="utf-8")
        spec_rel = "specs/N9.json"
        (repo / "specs").mkdir()
        spec = dict(_REH_SPEC)
        spec["rehearsal"] = {"command": f'"{sys.executable}" adapter.py', "timeout_s": 120,
                             "description": "r" * 60}
        eutil.write_json_atomic(repo / spec_rel, spec)
        cfg = store.load_config()
        cfg.setdefault("project", {})["rehearsal"] = "full_chain"
        eutil.write_json_atomic(store.config_path, cfg)
        g = store.load_graph()
        g.setdefault("nodes", []).append(
            {"id": "N9", "role": "variant", "status": "stage_ready", "spec": spec_rel,
             "workdir": ".", "implementation_seal": {"digest": "seal-1"}})
        store.save_graph(g)
        record = erehearsal.run(store, "N9")
        check(record.get("status") == "passed",
              f"the REAL engine-executed tiny pass passes: {record}")
        g2 = store.load_graph()
        node = next(n for n in g2["nodes"] if n["id"] == "N9")
        check(erehearsal.record_errors(store, node) == [],
              "a passed receipt bound to the current seal satisfies the launch duty")
        record2 = erehearsal.run(store, "N9")
        check(record2.get("receipt") == record.get("receipt"),
              "re-running the same seal+plan reuses the receipt (idempotent, no double spend)")
        node["implementation_seal"] = {"digest": "seal-2"}
        errs = erehearsal.record_errors(store, node)
        check(any("REHEARSAL_STALE" in e for e in errs),
              "a re-sealed implementation re-owes the proof - the receipt binds the code it proved")
        check(any("REHEARSAL_REQUIRED" in e
                  for e in erehearsal.record_errors(store, {"id": "NX"})),
              "no record at all reads as the duty being owed")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ----------------------------------------------------------------- doctor ----
def doctor_advisories() -> None:
    repo = _repo("doc")
    try:
        estore.Store(repo).init("t", "g")
        store = estore.Store(repo)
        store.add_error_resolution({"resolves": "ER001", "disposition": "fixed",
                                    "surface": "launch", "fix": "use queue B instead", "node": "N1"})
        store.add_error_resolution({"resolves": "ER002", "disposition": "fixed",
                                    "surface": "launch", "fix": "export the profile token first",
                                    "node": "N2"})
        problems, _ = edoctor.diagnose(store, fix=False)
        check(any(p.startswith("INFRA_FACTS_SUSPECT") and "launch" in p for p in problems),
              "two DISTINCT working fixes on one surface point at a wrong approved fact")
        st = store.load_state()
        st["infra_revision_pending"] = True
        store.save_state(st)
        problems, _ = edoctor.diagnose(store, fix=False)
        check(any(p.startswith("INFRA_REVISION_PENDING") for p in problems),
              "an owed canary re-proof is disclosed at checkup")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def main() -> None:
    engine_fit_validation()
    scheduler_fit_readers()
    provision_validation()
    canary_plan_forms()
    canary_joint_coverage()
    rehearsal_predicates_and_plan()
    rehearsal_observation_contract()
    rehearsal_real_execution()
    doctor_advisories()
    done("V11.7 STRUCTURAL REGRESSIONS")


if __name__ == "__main__":
    main()
