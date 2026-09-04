#!/usr/bin/env python3
"""Focused regression checks for scoped implementation repair."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import mock_drive as M

sys.path.insert(0, str(M.PKG / "engine"))

import eartifact  # noqa: E402
import erun  # noqa: E402
import esched  # noqa: E402
import eseal  # noqa: E402
import eutil  # noqa: E402
import evalid  # noqa: E402


CHECKS = 0


def check(condition: bool, message: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        raise AssertionError(f"[check {CHECKS}] {message}")


def fresh_project() -> M.D:
    repo = Path(__file__).resolve().parent / "out" / "v92_repair_scope_unit"
    if repo.exists():
        M.rmtree(repo)
    M.make_repo(repo, with_git=True)
    proc = subprocess.run(
        [M.PY, str(M.PKG / "engine" / "evo.py"), "--repo", str(repo), "init",
         "--project-name", "repair-scope", "--goal", "preserve valid workflow evidence"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    check(proc.returncode == 0, f"CLI init failed: {proc.stderr}")
    M.run_bootstrap(M.D(repo))
    return M.D(repo)


def add_completed_workflow_node(drive: M.D) -> tuple[dict, dict, dict]:
    store = drive.store()
    workdir = drive.repo / "workareas" / "n901"
    M.sh(drive.repo, "git", "worktree", "add", "-q", "-b", "fixture/n901",
         "workareas/n901", "HEAD")
    (workdir / "train.py").write_text("print('train-v1')\n", encoding="utf-8")
    (workdir / "eval.py").write_text("print('eval-v1')\n", encoding="utf-8")
    M.sh(workdir, "git", "add", "train.py", "eval.py")
    M.sh(workdir, "git", "commit", "-q", "-m", "fixture implementation v1")
    spec_rel = ".evo/nodes/N901/NODE_SPEC.json"
    spec = {
        "role": "variant", "workdir": "workareas/n901",
        "workflow": {"stages": [{"name": "train", "launch": "python train.py",
                                    "metrics_file": "stage_metrics.json", "produces": []}]},
        "eval": {"run": "python eval.py", "metrics_file": "eval_metrics.json",
                 "budget": {"limits": {}}, "resource_accounting": {}},
    }
    eutil.write_json_atomic(drive.repo / spec_rel, spec)
    report_rel = ".evo/nodes/N901/BUILD_REPORT.md"
    M.wt(drive.repo, report_rel, """# Build

## Workarea
Dedicated Git worktree fixture rooted at workareas/n901 with one reviewed branch and clean commits.

## Mechanism to code map
- trainer -> train.py
The trainer entry point is the complete workflow-authoritative implementation surface for this fixture.

## Deviations
No deviations from the deliberately minimal workflow fixture are present in the initial implementation.

## Self test
The workflow-path mutation is committed and the fixture deliberately verifies that it cannot retain prior evidence.
""")
    graph = store.load_graph()
    node = {
        "id": "N901", "title": "repair scope fixture", "role": "variant", "parents": [],
        "code_parent": None, "level": 1, "lane": None, "round": None, "idea_doc": None,
        "spec": spec_rel, "spec_revision": 1, "workdir": "workareas/n901", "branch": "fixture/n901",
        "status": "building", "implementation_revision": 0, "needs_fidelity": False,
        "needs_metric_bridge": False, "stage_cursor": 0, "replica_index": 0,
        "replicas_completed": [], "eval_done": False, "eval_resource_accounted": False,
    }
    graph.setdefault("nodes", []).append(node)
    store.save_graph(graph)
    eng = esched.Engine(store)
    node = eng.node("N901")
    node["spec_seal"] = eng._seal([("node_spec", spec_rel)], revision=1)
    eng._seal_implementation(node, report_rel)
    prior_impl = str(node["implementation_seal"]["digest"])

    metrics_rel = "workareas/n901/stage_metrics.json"
    eutil.write_json_atomic(drive.repo / metrics_rel, {"seed": None, "summary": {"loss": 0.1}, "usage": {}})
    run = store.new_run(
        eng.st, "N901", "stage", stage="train", stage_index=0,
        replica_index=0, replica_total=1, replica_seed=None,
        contract_digest="stage-contract-v1", implementation_digest=prior_impl)
    run["authority_upstreams"] = [str(node["spec_seal"]["digest"]), prior_impl]
    erun.transition_execution(run, "finished")
    run["metrics_file"] = metrics_rel
    run["evidence_seal"] = eng._seal(
        [("run_metrics", metrics_rel)], upstream=run["authority_upstreams"], revision=1)
    run["evidence_revision"] = 1
    erun.transition_evidence(run, "complete")
    erun.transition_adoption(run, "adopted")
    run["absorbed"] = True
    node["evidence_heads"] = {"stage:0:0": run["id"]}
    node["stage_cursor"] = 1
    node["replicas_completed"] = [{"seed": None, "run": run["id"]}]
    node["status"] = "evaluating"
    # R8: registration now verifies a locally-checkable product exists (a
    # ghost registered 'available' handed consumers a name with no bytes) -
    # write the checkpoint like the real training stage would have.
    (workdir / "model.bin").write_bytes(b"fixture-checkpoint-v1")
    artifact = eartifact.register(
        store, eng.st, eng.reg, node="N901", stage="train", stage_key="fixture-train",
        name="trained checkpoint", kind="checkpoint", uri="workareas/n901/model.bin",
        producer_run=run, producer_implementation_digest=prior_impl,
        producer_evidence_digest=str(run["evidence_seal"]["digest"]))
    eng.save()
    return node, run, artifact


def scoped_repair_preserves_workflow() -> None:
    drive = fresh_project()
    node, stage_run, artifact = add_completed_workflow_node(drive)
    store = drive.store()
    eng = esched.Engine(store)
    node = eng.node("N901")
    stage_run = store.get_run(eng.st, stage_run["id"])
    artifact = next(row for row in eng.reg.get("artifacts", []) if row.get("id") == artifact["id"])
    typed = eng._prepare_run(node, "eval", {}, resolved_launch="python eval.py")
    try:
        eng.update_run(typed["id"], "failed", failure_class="implementation",
                       note="fixture evaluator defect")
    except SystemExit as exc:
        check("--repair-scope" in str(exc),
              "an implementation failure must declare its replay boundary")
    else:
        raise AssertionError("implementation failure without repair scope was accepted")
    typed = eng.update_run(typed["id"], "failed", failure_class="implementation",
                           repair_scope="evaluation", note="fixture evaluator defect")
    check(typed.get("repair_scope") == "evaluation",
          "the immutable failed RUN fact must retain its declared repair scope")
    failed = {"id": "RUN-EVAL-FAIL", "kind": "eval", "failure_class": "implementation",
              "repair_scope": "evaluation", "note": "eval parser fails only on the last dataset"}
    eng._handle_eval_failure(node, failed)
    check((node.get("repeat_attempt") or {}).get("operation") == "eval",
          "evaluation-only code repair must authorize only replacement eval spend")
    eng._begin_implementation_revision(node, str(node["fix_note"]))
    check(node["stage_cursor"] == 1 and stage_run["adoption_status"] == "adopted",
          "opening an evaluation-only repair must preserve the completed workflow head")
    check(artifact["status"] == "available", "evaluation-only repair must preserve workflow artifacts")

    (drive.repo / "workareas/n901/eval.py").write_text("print('eval-v2 fixed')\n", encoding="utf-8")
    M.sh(drive.repo / "workareas/n901", "git", "add", "eval.py")
    M.sh(drive.repo / "workareas/n901", "git", "commit", "-q", "-m", "fix evaluator only")
    report_rel = ".evo/nodes/N901/BUILD_REPORT.md"
    M.wt(drive.repo, report_rel, """# Build

## Workarea
Dedicated Git worktree fixture rooted at workareas/n901 with one reviewed branch and clean commits.

## Mechanism to code map
- trainer -> train.py
The trainer entry point remains the complete workflow-authoritative implementation surface and is unchanged.

## Deviations
Only the evaluator parser was corrected; the workflow implementation and its frozen command remain unchanged.

## Self test
the fixed evaluator parses the final dataset

## Repair scope
REPAIR_SCOPE: evaluation
CHANGED_FILE: eval.py
WORKFLOW_REUSE_ARGUMENT: The only changed byte is in the post-training evaluator entry point; train.py and every workflow-authoritative path remain byte-identical, so the sealed checkpoint is unaffected.
""")
    errors = evalid.v_implement(eng.ctx(), {
        "subject": {"node": "N901"}, "outputs": [report_rel]})
    check(not errors, f"valid evaluation-only repair report must pass: {errors}")
    old_impl = str(stage_run["implementation_digest"])
    eng._transition({"type": "implement", "subject": {"node": "N901"},
                     "outputs": [report_rel]})
    new_impl = str(node["implementation_seal"]["digest"])
    check(old_impl != new_impl, "replacement evaluator must receive a new implementation identity")
    check(stage_run["adoption_status"] == "adopted" and node["stage_cursor"] == 1,
          "new evaluator identity must not supersede old completed training evidence")
    check(bool(node.get("workflow_reuse_seal")), "preserved cross-revision workflow evidence needs a seal")
    eng._assert_artifact_seals(only_node="N901")
    try:
        eng.plan_recovery("node:N901", "implementation", "fixture correction without scope")
    except SystemExit as exc:
        check("--repair-scope" in str(exc),
              "implementation recovery must make its replay boundary explicit")
    else:
        raise AssertionError("implementation recovery without repair scope was accepted")
    recovery = eng.plan_recovery(
        "node:N901", "implementation", "later audit found another evaluator-only defect",
        repair_scope="evaluation")
    plan = json.loads((drive.repo / recovery["plan_path"]).read_text(encoding="utf-8"))
    check(plan.get("repair_scope") == "evaluation"
          and (plan.get("classification") or {}).get("replay_from") == "evaluation",
          "a user-planned evaluator repair must preserve the same narrow replay boundary")
    eng.release_hold(recovery["hold"], "fixture inspected the plan without applying it")
    prepared = eng._prepare_run(node, "eval", {}, resolved_launch="python eval.py")
    check(prepared["implementation_digest"] == new_impl and old_impl in {
        str(x) for x in (json.loads((drive.repo / node["workflow_reuse_receipt_path"]).read_text(
            encoding="utf-8")).get("preserved_upstream_digests") or [])},
          "replacement eval must bind new code while the receipt keeps old workflow provenance explicit")
    smoke_task = {"id": "T-SMOKE-REPAIR", "type": "smoke", "status": "open", "attempts": 0,
                  "subject": {"node": "N901"}}
    eng._reject(smoke_task, ["SMOKE_FAILED: repaired evaluator still has a local parser defect"])
    check(node.get("implementation_repair_scope") == "evaluation",
          "a smoke failure in an active eval-only revision must not silently widen the next fix to workflow")


def protected_change_cannot_masquerade_as_eval_only() -> None:
    drive = fresh_project()
    node, stage_run, artifact = add_completed_workflow_node(drive)
    eng = esched.Engine(drive.store())
    node = eng.node("N901")
    stage_run = eng.store.get_run(eng.st, stage_run["id"])
    artifact = next(row for row in eng.reg.get("artifacts", []) if row.get("id") == artifact["id"])
    failed = {"id": "RUN-EVAL-FAIL", "kind": "eval", "failure_class": "implementation",
              "repair_scope": "evaluation", "note": "evaluation exposed a shared model defect"}
    eng._handle_eval_failure(node, failed)
    eng._begin_implementation_revision(node, str(node["fix_note"]))
    (drive.repo / "workareas/n901/train.py").write_text("print('train-v2')\n", encoding="utf-8")
    M.sh(drive.repo / "workareas/n901", "git", "add", "train.py")
    M.sh(drive.repo / "workareas/n901", "git", "commit", "-q", "-m", "touch workflow code")
    report_rel = ".evo/nodes/N901/BUILD_REPORT.md"
    M.wt(drive.repo, report_rel, """# Build

## Workarea
Dedicated Git worktree fixture rooted at workareas/n901 with one reviewed branch and clean commits.

## Mechanism to code map
- trainer -> train.py
The trainer entry point is the workflow-authoritative implementation surface deliberately changed below.

## Deviations
The fixture deliberately changes shared workflow code to verify that narrow reuse is rejected.

## Self test
The workflow-path mutation is committed and the fixture deliberately verifies that it cannot retain prior evidence.

## Repair scope
REPAIR_SCOPE: evaluation
CHANGED_FILE: train.py
WORKFLOW_REUSE_ARGUMENT: This deliberately false claim is long enough syntactically, but the protected workflow path must make the validator reject it regardless of the prose supplied here.
""")
    errors = evalid.v_implement(eng.ctx(), {
        "subject": {"node": "N901"}, "outputs": [report_rel]})
    check(any(str(error).startswith("BUILD_EVAL_REPAIR_TOUCHES_WORKFLOW") for error in errors),
          "a protected training-file change cannot be certified as evaluation-only")
    text = (drive.repo / report_rel).read_text(encoding="utf-8").replace(
        "REPAIR_SCOPE: evaluation", "REPAIR_SCOPE: workflow")
    (drive.repo / report_rel).write_text(text, encoding="utf-8")
    errors = evalid.v_implement(eng.ctx(), {
        "subject": {"node": "N901"}, "outputs": [report_rel]})
    check(not errors, f"an explicit widening to workflow must pass validation: {errors}")
    eng._transition({"type": "implement", "subject": {"node": "N901"},
                     "outputs": [report_rel]})
    check(stage_run.get("adoption_status") == "superseded" and node.get("stage_cursor") == 0,
          "widening an eval repair to workflow must invalidate old training evidence and restart at stage 0")
    check(artifact.get("status") == "stale" and not node.get("workflow_reuse_seal"),
          "workflow widening must retire old products and must not mint a reuse bridge")
    check((node.get("repeat_attempt") or {}).get("operation") == "workflow",
          "workflow widening must also widen the later external-spend approval")


def approval_scope_matches_replay_scope() -> None:
    class FakeStore:
        def add_error(self, _state, _row):
            pass

        def event(self, *_args, **_kwargs):
            pass

        def new_gate(self, state, kind, subject, message):
            gate = {"id": "G-REPEAT", "kind": kind, "subject": subject,
                    "message": message, "status": "open"}
            state["gates"].append(gate)
            return gate

        def get_run(self, state, run_id):
            # R10-016 stub sync: the gate summary inspects the source RUN to
            # disclose the repeat lane's third exit when applicable
            return next((r for r in state.get("runs", []) if r.get("id") == run_id), None)

    eng = object.__new__(esched.Engine)
    eng.store = FakeStore()
    eng.st = {"gates": [], "runs": []}
    eng.cfg = {"budgets": {"max_attempts": 3}, "policy": {"on_stuck": "gate"}}
    node = {"id": "N902", "status": "executing", "stage_failures": 0}
    eng._handle_stage_failure(node, {
        "id": "RUN-LATE-STAGE", "stage": "finalize", "replica_seed": 29,
        "failure_class": "implementation", "repair_scope": "workflow", "note": "shared code defect"})
    check((node.get("repeat_attempt") or {}).get("operation") == "workflow",
          "a stage code fix that resets the workflow must request whole-workflow approval")
    gate = eng._repeat_spend_gate(node, "stage", "finalize")
    check((gate.get("subject") or {}).get("repair_scope") == "workflow",
          "repeat-spend approval must persist the repair scope it authorizes")


def planned_evaluator_recovery_preserves_workflow() -> None:
    drive = fresh_project()
    _node, stage_run, artifact = add_completed_workflow_node(drive)
    eng = esched.Engine(drive.store())
    node = eng.node("N901")
    stage_run = eng.store.get_run(eng.st, stage_run["id"])
    artifact = next(row for row in eng.reg.get("artifacts", []) if row.get("id") == artifact["id"])
    recovery = eng.plan_recovery(
        "node:N901", "implementation", "post-run audit found an evaluator-only implementation defect",
        repair_scope="evaluation")
    eng.apply_recovery(recovery["id"], recovery["plan_digest"])
    check(node.get("implementation_repair_scope") == "evaluation" and node.get("fix_needed"),
          "applying an evaluator implementation recovery must open the shared scoped repair path")
    eng._begin_implementation_revision(node, str(node.get("fix_note") or "fixture recovery"))
    check(stage_run.get("adoption_status") == "adopted" and node.get("stage_cursor") == 1,
          "planned evaluator recovery must retain the completed stage head")
    check(artifact.get("status") == "available",
          "planned evaluator recovery must not stale a workflow product before any workflow code changes")


def copy_mode_runtime_outputs_are_not_code() -> None:
    repo = Path(__file__).resolve().parent / "out" / "v92_repair_scope_unit_copy"
    if repo.exists():
        M.rmtree(repo)
    M.make_repo(repo, with_git=False)
    store = M.estore.Store(repo)
    store.init("copy manifest fixture", "separate runtime outputs from executable closure")
    cfg = eutil.read_json(repo / ".evo/config.json", {}) or {}
    cfg.setdefault("project", {})["vcs"] = "copy"
    eutil.write_json_atomic(repo / ".evo/config.json", cfg)
    drive = M.D(repo)
    workdir = drive.repo / "workareas" / "n903"
    workdir.mkdir(parents=True, exist_ok=True)
    for name, content in {
            "train.py": "print('train')\n", "eval.py": "print('eval')\n",
            "stage_metrics.json": "{}\n", "stage_ledger.json": "{}\n",
            "model.bin": "checkpoint-v1\n", "eval_metrics.json": "{}\n",
            "generated.py": "print('executable output')\n"}.items():
        (workdir / name).write_text(content, encoding="utf-8")
    spec_rel = ".evo/nodes/N903/NODE_SPEC.json"
    eutil.write_json_atomic(drive.repo / spec_rel, {
        "role": "variant", "workdir": "workareas/n903",
        "workflow": {"stages": [{
            "name": "train", "launch": "python train.py",
            "metrics_file": "stage_metrics.json", "ledger_file": "stage_ledger.json",
            "produces": [{"name": "checkpoint", "kind": "checkpoint", "uri": "model.bin"},
                         {"name": "generated source", "kind": "other", "uri": "generated.py"}],
        }]},
        "eval": {"run": "python eval.py", "metrics_file": "eval_metrics.json"},
    })
    graph = store.load_graph()
    node = {"id": "N903", "role": "variant", "spec": spec_rel,
            "workdir": "workareas/n903", "status": "building"}
    graph.setdefault("nodes", []).append(node)
    store.save_graph(graph)
    eng = esched.Engine(store)
    node = eng.node("N903")
    manifest = evalid.build_implementation_manifest(eng.ctx(), node)
    paths = {str(row.get("path") or "") for row in (manifest.get("files") or [])}
    check({"train.py", "eval.py", "generated.py"}.issubset(paths),
          "copy-mode implementation closure must retain executable source even at a declared output path")
    check(not ({"stage_metrics.json", "stage_ledger.json", "model.bin", "eval_metrics.json"} & paths),
          "spec-declared mutable RUN products must not become sealed implementation bytes")
    manifest_rel = ".evo/nodes/N903/IMPLEMENTATION_MANIFEST.json"
    eutil.write_json_atomic(drive.repo / manifest_rel, manifest)
    node["implementation_manifest"] = manifest_rel
    (workdir / "eval_metrics.json").write_text('{"score": 1}\n', encoding="utf-8")
    check(not evalid.implementation_manifest_errors(eng.ctx(), node),
          "overwriting a declared eval landing file must not look like code mutation in copy mode")


def main() -> None:
    scoped_repair_preserves_workflow()
    protected_change_cannot_masquerade_as_eval_only()
    approval_scope_matches_replay_scope()
    planned_evaluator_recovery_preserves_workflow()
    copy_mode_runtime_outputs_are_not_code()
    print(f"V9.2 REPAIR SCOPE UNIT GREEN: {CHECKS} checks passed")


if __name__ == "__main__":
    main()
