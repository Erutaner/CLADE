"""Spend is stopped before it is spent, by people looking at real numbers.

    python tests/resource_review_unit.py

Covers: the node ceiling and the device allowance as notebook facts with
provenance (config validation, outside the signed digest); the workflow-gate
review lines (declared caps, the agent's estimate with its basis, the
rehearsal's real duration, the ceiling, a local change's parent cost) and the
one comparison that turns an auto/full_auto gate manual (cap or estimate above
the ceiling); the spec's cost_estimate shape; launch reports that record
devices and deviations, the allowance on accelerators held at once; and the
'busy' launch report that keeps the card open without spending an attempt and
asks the user only after the configured wait.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))
from _check import check, done  # noqa: E402

import econfig   # noqa: E402
import esched    # noqa: E402
import estore    # noqa: E402
import eutil     # noqa: E402
import evalid    # noqa: E402


def _fresh_engine(tag: str):
    repo = HERE / "out" / f"spend-{tag}-{uuid.uuid4().hex[:8]}"
    repo.mkdir(parents=True)
    store = estore.Store(repo)
    store.init("spend-unit", "stop money before it is spent")
    eng = esched.Engine(store)
    eng.cfg.setdefault("project", {})["mode"] = "research"
    return repo, store, eng


def _write_json(repo: Path, rel: str, data) -> None:
    eutil.write_json_atomic(repo / rel, data)


def _spec(*, gpu_hours: float, estimate: dict | None = None) -> dict:
    spec = {"role": "variant", "experiment_purpose": "candidate", "parents": ["N001"], "level": 2,
            "title": "node two", "cost_class": "medium", "code_parent": "N001",
            "workflow": {"stages": [{"name": "train", "launch": "python train.py",
                                     "budget": {"limits": {"gpu_hours": gpu_hours}}}]},
            "eval": {"run": "python eval.py", "budget": {"limits": {"wallclock_minutes": 30}}},
            "smoke_plan": [{"name": "imports", "cmd": "python -c 1", "timeout_s": 60}]}
    if estimate is not None:
        spec["cost_estimate"] = estimate
    return spec


def _node(repo: Path, eng, nid: str, spec: dict, *, idea_scope: str | None = None) -> dict:
    _write_json(repo, f".evo/nodes/{nid}/NODE_SPEC.json", spec)
    node = {"id": nid, "title": "node", "role": "variant", "experiment_purpose": "candidate",
            "status": "smoke_pass", "parents": ["N001"], "level": 2, "lane": "L001",
            "spec": f".evo/nodes/{nid}/NODE_SPEC.json", "idea_doc": f".evo/ideas/I{nid[1:]}.md"}
    if idea_scope:
        _write_json(repo, f".evo/ideas/I{nid[1:]}.meta.json", {"idea": f"I{nid[1:]}", "change_scope": idea_scope})
    if not any(n["id"] == "N001" for n in eng.g["nodes"]):
        eng.g["nodes"].append({"id": "N001", "role": "baseline", "status": "concluded", "verdict": "baseline",
                               "parents": [], "level": 0, "scores": {"auc": 0.7}})
    eng.g["nodes"].append(node)
    return node


# ------------------------------------------------------------- the facts ----
def the_ceiling_and_the_device_allowance_are_notebook_facts() -> None:
    cfg = econfig.merged_default()
    check(econfig.node_ceiling(cfg) == {} and econfig.max_devices(cfg) is None
          and econfig.busy_wait_minutes(cfg) == 180,
          "no ceiling, no device allowance and a three-hour busy wait by default")
    cfg["resource_contract"].update({"limits": {"gpu_hours": 100}, "basis": "the user stated a hundred GPU hours",
                                     "node_ceiling": {"gpu_hours": 12}})
    errs = econfig.validate_config(cfg)
    check(any("CONFIG_NODE_CEILING_SOURCE" in e for e in errs),
          f"a ceiling without its source is refused with the field named: {[e for e in errs if 'CEILING' in e]}")
    cfg["resource_contract"]["node_ceiling_source"] = "estimated"
    check(any("CONFIG_NODE_CEILING_BASIS" in e for e in econfig.validate_config(cfg)),
          "an estimated ceiling records where the estimate came from")
    cfg["resource_contract"]["node_ceiling_basis"] = "2 x A100; 1B-param finetunes run 5-20 GPU-h here; 2x the top"
    check(not any("CEILING" in e for e in econfig.validate_config(cfg)), "a sourced, based ceiling is accepted")
    cfg["resource_contract"]["max_devices"] = 0
    check(any("CONFIG_MAX_DEVICES" in e for e in econfig.validate_config(cfg)), "zero devices is not an allowance")
    cfg["resource_contract"]["max_devices"] = 8
    cfg["resource_contract"]["busy_wait_minutes"] = 0
    check(any("CONFIG_BUSY_WAIT" in e for e in econfig.validate_config(cfg)), "a zero busy wait is refused")
    cfg["resource_contract"]["busy_wait_minutes"] = 60
    check(not any("MAX_DEVICES" in e or "BUSY_WAIT" in e for e in econfig.validate_config(cfg))
          and econfig.max_devices(cfg) == 8 and econfig.busy_wait_minutes(cfg) == 60,
          "the allowance and the wait are read back")
    other = json.loads(json.dumps(cfg))
    other["resource_contract"].update({"node_ceiling": {"gpu_hours": 40}, "max_devices": 2, "busy_wait_minutes": 5})
    check(econfig.bootstrap_contract_digest(cfg) == econfig.bootstrap_contract_digest(other),
          "ceiling, device allowance and busy wait sit outside the signed digest")
    different = json.loads(json.dumps(cfg))
    different["resource_contract"]["limits"] = {"gpu_hours": 200}
    check(econfig.bootstrap_contract_digest(cfg) != econfig.bootstrap_contract_digest(different),
          "the project totals remain the signed contract")
    import eamend
    check(eamend.config_notebook_path("resource_contract.node_ceiling.gpu_hours")
          and eamend.config_notebook_path("resource_contract.max_devices")
          and eamend.config_notebook_path("resource_contract.busy_wait_minutes")
          and not eamend.config_notebook_path("resource_contract.limits.gpu_hours"),
          "the three numbers are amendable; the totals are not")


# ----------------------------------------------------------- the estimate ----
def the_estimate_is_the_agents_and_only_the_ceiling_is_compared() -> None:
    repo, store, eng = _fresh_engine("review")
    try:
        eng.cfg.setdefault("policy", {})["autonomy"] = "full_auto"
        node = _node(repo, eng, "N002", _spec(gpu_hours=10), idea_scope="local")
        eng.st.setdefault("resource_ledger", []).append(
            {"id": "RC0001", "node": "N001", "kind": "stage", "run": "RUN001", "task": None,
             "usage": {"gpu_hours": 9.0}, "basis": "reported_actual", "charged_at": eutil.utc_now()})
        lines, reasons = evalid.workflow_spend_review(eng.ctx(), node)
        check(reasons == [] and any("declared caps" in ln and "stages gpu_hours 10" in ln for ln in lines)
              and any("estimate: none recorded" in ln for ln in lines)
              and any("node ceiling: none recorded" in ln for ln in lines)
              and any("parent N001 actually cost" in ln and "gpu_hours 9" in ln for ln in lines),
              f"the review prints the caps, the missing estimate and ceiling, and the local parent's cost: {lines}")
        gate = store.new_gate(eng.st, "workflow_approval", {"node": "N002", "contract_digest": ""}, "x")
        check(eng._maybe_auto_resolve(gate) is True and gate["status"] == "approved",
              "with nothing to compare against, full_auto approves as before")
        # the agent's own estimate, with its basis, is printed - never recomputed
        spec = _spec(gpu_hours=10, estimate={"per_unit": {"gpu_hours": 14.5},
                                             "basis": "rehearsal paced 6 s/step on 2 devices; 20k steps; excludes eval"})
        _write_json(repo, node["spec"], spec)
        lines, reasons = evalid.workflow_spend_review(eng.ctx(), node)
        check(reasons == [] and any("agent's estimate of one full run: gpu_hours ~14.5 [rehearsal paced" in ln
                                    for ln in lines),
              f"an estimate above the cap but under no ceiling is information, not a reason: {lines}")
        # a rehearsal receipt's real duration is a fact beside them
        import erehearsal
        _write_json(repo, erehearsal.receipt_path(store, "N002").relative_to(repo).as_posix(),
                    {"status": "passed", "started_at": "2026-09-08T10:00:00+00:00",
                     "ended_at": "2026-09-08T10:07:30+00:00"})
        lines, _ = evalid.workflow_spend_review(eng.ctx(), node)
        check(any("the tiny rehearsal took 450 s" in ln for ln in lines),
              f"the rehearsal's duration is printed as measured, not extrapolated: {lines}")
        # the user's ceiling is the one comparison
        eng.cfg["resource_contract"].update({"node_ceiling": {"gpu_hours": 12}, "node_ceiling_source": "user"})
        lines, reasons = evalid.workflow_spend_review(eng.ctx(), node)
        check(len(reasons) == 1 and "estimate gpu_hours ~14.5 exceeds the node ceiling 12 (user)" in reasons[0]
              and any("node ceiling (user): gpu_hours 12" in ln for ln in lines),
              f"an estimate above the user's ceiling is the reason a person looks: {reasons}")
        gate2 = store.new_gate(eng.st, "workflow_approval", {"node": "N002", "contract_digest": ""}, "y")
        check(eng._maybe_auto_resolve(gate2) is False and gate2["status"] == "open",
              "full_auto does not spend past the user's ceiling: the gate waits")
        report = "\n".join(eng._gate_report(gate2))
        check("a person decides before this trains" in report and "agent's estimate" in report
              and "declared caps" in report and "rehearsal took" in report,
              f"the gate report carries the four numbers side by side:\n{report}")
        node3 = _node(repo, eng, "N003", _spec(gpu_hours=25))
        lines, reasons = evalid.workflow_spend_review(eng.ctx(), node3)
        check(len(reasons) == 1 and "declared gpu_hours cap 25 (stages + eval) exceeds the node ceiling 12" in reasons[0],
              f"the declared promise itself is checked against the ceiling: {reasons}")
        # the commitment is stages plus eval per unit: 10 + 5 clears a ceiling of 12 only on paper
        spec4 = _spec(gpu_hours=10)
        spec4["eval"]["budget"]["limits"]["gpu_hours"] = 5
        node4 = _node(repo, eng, "N004", spec4)
        lines, reasons = evalid.workflow_spend_review(eng.ctx(), node4)
        check(len(reasons) == 1 and "cap 15 (stages + eval)" in reasons[0],
              f"stage and eval caps are summed before the ceiling comparison: {reasons}")
        # the spec block is validated at plan time
        errs = evalid._spec_errors(eng.ctx(), _spec(gpu_hours=10, estimate={"per_unit": {"GPU": -1}, "basis": "x"}),
                                   expect_role="variant", expect_parents=None, expect_level=None, where="s")
        check(any("SPEC_COST_ESTIMATE_VALUE" in e for e in errs) and any("cost_estimate.basis" in e for e in errs),
              f"a malformed estimate is refused with the fields named: {[e for e in errs if 'ESTIMATE' in e or 'basis' in e]}")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# --------------------------------------------------------------- launches ----
def _prepared_run(eng, rid: str, nid: str, *, job: str | None = None, status: str = "prepared",
                  devices: int | None = None) -> dict:
    """A real engine-prepared RUN (all three axes initialized), then renamed
    and re-pointed so the tests can address it by a fixed id."""
    run = eng.store.new_run(eng.st, nid, "stage", stage="train", stage_index=0,
                            contract_digest="sha256:test", attempt_token=f"tok-{rid}")
    run["id"] = rid
    if status != "prepared":
        run["status"] = status
        run["job"] = job
    if devices:
        run["devices"] = devices
    return run


def launches_record_devices_and_respect_the_allowance() -> None:
    repo, store, eng = _fresh_engine("devices")
    try:
        _node(repo, eng, "N002", _spec(gpu_hours=10))
        run = _prepared_run(eng, "RUN010", "N002")
        check(evalid.launch_device_errors(eng.ctx(), run, {"mode": "background", "job": "j1"}) == [],
              "a launch that says nothing about devices is legal")
        errs = evalid.launch_device_errors(eng.ctx(), run, {"mode": "background", "job": "j1", "devices": 0,
                                                            "deviation": "short"})
        check(any(e.startswith("LAUNCH_DEVICES") for e in errs) and any(e.startswith("LAUNCH_DEVIATION") for e in errs),
              f"devices must be positive and a deviation note says what changed: {errs}")
        # under an allowance the running jobs' devices add up
        eng.cfg["resource_contract"]["max_devices"] = 8
        _prepared_run(eng, "RUN011", "N002", job="j-other", status="running", devices=6)
        errs = evalid.launch_device_errors(eng.ctx(), run, {"mode": "background", "job": "j1", "devices": 4})
        check(len(errs) == 1 and errs[0].startswith("LAUNCH_DEVICES_OVER_ALLOWANCE")
              and "6 already held" in errs[0] and "mode 'busy'" in errs[0] and "evo amend" in errs[0],
              f"holding more than the user allowed is refused with the exits named: {errs}")
        check(evalid.launch_device_errors(eng.ctx(), run, {"mode": "background", "job": "j1", "devices": 2}) == [],
              "fewer devices than planned simply runs")
        check(evalid.devices_in_use(eng.st, except_run="RUN010") == 6, "held devices count only live launched jobs")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def _busy_fixture(repo: Path, eng, *, wait_minutes: int = 30) -> tuple[dict, dict]:
    """A prepared train RUN with its open launch card, on a running round."""
    eng.cfg["resource_contract"]["busy_wait_minutes"] = wait_minutes
    _node(repo, eng, "N002", _spec(gpu_hours=10))
    run = _prepared_run(eng, "RUN020", "N002")
    eng.st.update({"phase": "rounds", "round_status": "running", "current_round": "R001"})
    task = {"id": "T0050", "type": "stage_launch", "status": "open", "attempts": 0,
            "subject": {"node": "N002", "run": "RUN020", "stage": "train", "round": "R001"},
            "outputs": [".evo/nodes/N002/launch/LAUNCH.json"],
            # a real launch card's render fields, so a rejection can re-render it
            "_render": {"extra_fields": {
                "NODE": "N002", "STAGE": "train", "STAGE_INDEX": "1", "STAGE_TOTAL": "1",
                "REPLICA_SEED": "not-applicable", "REPLICA_INDEX": "1", "REPLICA_TOTAL": "1",
                "RESOLVED_LAUNCH": "python train.py", "RESOLVED_METRICS": "workareas/n002/metrics.json",
                "RESOLVED_PRODUCTS": "[]", "STAGE_CONTROL": "fixed", "STAGE_MULTIPLICITY": "single",
                "STAGE_BUDGET": "{}", "RUN_ID": "RUN020", "ATTEMPT_TOKEN": "tok-RUN020",
                "LEDGER_REQUIREMENT": "optional"}, "inputs": [], "extra_blocks": []}}
    eng.st.setdefault("tasks", []).append(task)
    return run, task


def a_busy_machine_costs_no_attempt_and_asks_the_user_only_after_the_wait() -> None:
    repo, store, eng = _fresh_engine("busy")
    try:
        run, task = _busy_fixture(repo, eng)
        _write_json(repo, task["outputs"][0], {"run": "RUN020", "mode": "busy", "note": "x"})
        dry = eng.validation_report("T0050")
        check(any("LAUNCH_BUSY_NOTE" in e for e in dry["errors"]),
              f"the dry run mirrors the busy branch's note rule: {dry}")
        _write_json(repo, task["outputs"][0], {"run": "RUN020", "mode": "busy", "note": "all 8 cards taken by a colleague's sweep"})
        dry = eng.validation_report("T0050")
        check(dry["errors"] == [] and any("wait report, not a launch" in n for n in dry["notes"]),
              f"the dry run explains a busy report instead of failing LAUNCH_MODE: {dry}")
        out = eng._submit_launch_busy(task)
        check(out is not None and out["kind"] == "waiting" and out["busy_waits"] == 1 and out["escalation"] is None
              and task["status"] == "open" and task["attempts"] == 0 and len(run["busy_waits"]) == 1,
              f"busy keeps the card open, spends no attempt and records the wait: {out}")
        _write_json(repo, task["outputs"][0], {"run": "RUN020", "mode": "busy", "note": "x"})
        rej = eng._submit_launch_busy(task)
        check(rej["kind"] == "rejected" and any("LAUNCH_BUSY_NOTE" in e for e in rej["errors"])
              and task["attempts"] == 0,
              "a busy report without a real note is refused without spending an attempt")
        _write_json(repo, task["outputs"][0], {"run": "RUN020", "mode": "background", "job": "j9"})
        check(eng._submit_launch_busy(task) is None, "a real launch report is not the busy path")
        # after the configured wait the engine asks the user exactly once
        run["busy_waits"][0]["at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=45)).isoformat()
        _write_json(repo, task["outputs"][0], {"run": "RUN020", "mode": "busy", "note": "still fully occupied this evening"})
        out = eng._submit_launch_busy(task)
        gates = [g for g in eng.st["gates"] if g["kind"] == "escalation" and (g.get("subject") or {}).get("task") == "T0050"]
        check(out["escalation"] == gates[0]["id"] and len(gates) == 1 and gates[0]["status"] == "open"
              and "45 min" in gates[0]["summary"] if "summary" in gates[0] else True,
              f"past the wait the engine opens one escalation for the user: {out}")
        out2 = eng._submit_launch_busy(task)
        gates = [g for g in eng.st["gates"] if g["kind"] == "escalation" and (g.get("subject") or {}).get("task") == "T0050"]
        check(len(gates) == 1 and out2["escalation"] == gates[0]["id"]
              and gates[0]["subject"].get("reason") == "resources_busy",
              "a further busy report reuses the open escalation instead of stacking gates")
        eng.cfg.setdefault("policy", {}).update({"autonomy": "full_auto", "on_stuck": "abandon"})
        check(eng._maybe_auto_resolve(gates[0]) is False and gates[0]["status"] == "open",
              "a busy-resources escalation is a person's call even under full_auto with on_stuck=abandon")
        # "keep waiting" restarts the clock: the next report does not re-ask at once
        gates[0]["status"] = "approved"
        gates[0]["decided_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        out3 = eng._submit_launch_busy(task)
        open_gates = [g for g in eng.st["gates"] if g["kind"] == "escalation" and g["status"] == "open"
                      and (g.get("subject") or {}).get("task") == "T0050"]
        check(out3["escalation"] is None and open_gates == [],
              f"after the user said keep waiting, the wait window restarts: {out3}")
        # a completed launch is a record: the allowance never refuses it
        eng.cfg["resource_contract"]["max_devices"] = 1
        check(evalid.launch_device_errors(eng.ctx(), run, {"mode": "completed", "devices": 4}) == [],
              "recording an already-finished run is never refused by the device allowance")
        eng.save()
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def the_user_decides_a_busy_wait_through_the_real_gate_path() -> None:
    def _escalate(eng, repo, task, run):
        _write_json(repo, task["outputs"][0], {"run": "RUN020", "mode": "busy", "note": "all cards still taken by the sweep"})
        eng._submit_launch_busy(task)
        run["busy_waits"][0]["at"] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=45)).isoformat()
        out = eng._submit_launch_busy(task)
        return next(g for g in eng.st["gates"] if g["id"] == out["escalation"])

    def _events(repo, name):
        return [e for e in eutil.read_jsonl(repo / ".evo/events.jsonl") if e.get("event") == name]

    # approve = keep waiting: the card stays open, carries the user's word, and the clock restarts
    repo, store, eng = _fresh_engine("busy-approve")
    try:
        run, task = _busy_fixture(repo, eng)
        gate = _escalate(eng, repo, task, run)
        report = "\n".join(eng._gate_report(gate))
        check("keeps finding the shared machine busy" in report and "approve = keep waiting" in report
              and "reject = stop waiting" in report and "Something is stuck" not in report,
              "the busy gate says what it decides instead of the stuck-task text")
        eng._decide_gate(gate, approve=True, note="the sweep ends tonight, wait for it", actor="user")
        blocks = dict(task["_render"]["extra_blocks"])
        check(gate["status"] == "approved" and task["status"] == "open" and task["attempts"] == 0
              and "Busy-resources decision" in blocks and "wait for it" in blocks["Busy-resources decision"][0],
              f"keep waiting: gate approved, card open with the user's note: {task['status']} {blocks}")
        out = eng._submit_launch_busy(task)
        check(out["escalation"] is None and eng.node("N002")["status"] == "smoke_pass",
              f"the next busy report waits again instead of re-asking at once: {out}")
        eng.save()
        check(len(_events(repo, "stage_launch_busy_wait_continued")) == 1,
              "the continued wait is on the event ledger")
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    # reject = stop waiting: nothing trained, the node is abandoned like any launch that never happened
    repo, store, eng = _fresh_engine("busy-reject")
    try:
        run, task = _busy_fixture(repo, eng)
        gate = _escalate(eng, repo, task, run)
        eng._decide_gate(gate, approve=False, note="not worth the wait, drop it", actor="user")
        check(gate["status"] == "rejected" and task["status"] == "cancelled"
              and eng.node("N002")["status"] == "abandoned",
              f"stop waiting: the card is cancelled and the node abandoned: {task['status']} {eng.node('N002')['status']}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)

    # a decision on a card that meanwhile launched is superseded, not applied
    repo, store, eng = _fresh_engine("busy-stale")
    try:
        run, task = _busy_fixture(repo, eng)
        gate = _escalate(eng, repo, task, run)
        task["status"] = "done"
        eng._decide_gate(gate, approve=False, note="stop", actor="user")
        check(gate["status"] == "cancelled" and "superseded" in str(gate.get("note")),
              f"a busy decision after the launch happened is recorded as superseded: {gate.get('note')}")
    finally:
        shutil.rmtree(repo, ignore_errors=True)


# ----------------------------------------------------------------- cards ----
def the_cards_ask_the_machine_questions_after_seeing_the_machine() -> None:
    src = (HERE.parent / "engine" / "evalid.py").read_text(encoding="utf-8")
    check("DISCOVERY_RESOURCE_KINDS" in src and "INTERVIEW_NODE_CEILING" in src and "INTERVIEW_MAX_DEVICES" in src
          and "cost_projection" not in src and "projection_gap" not in src,
          "the scan proposes resource kinds, the interview settles the machine-dependent numbers, no engine projection")
    configure = (HERE.parent / "engine" / "cards" / "configure.md").read_text(encoding="utf-8")
    check("resource_kinds" in configure and "Do NOT ask here how many devices" in configure,
          "configure confirms the kinds and asks totals only")
    interview = (HERE.parent / "engine" / "cards" / "infra_interview.md").read_text(encoding="utf-8")
    check("resource_contract.max_devices" in interview and "resource_contract.node_ceiling" in interview,
          "the infra interview asks the two machine-dependent numbers")
    launch = (HERE.parent / "engine" / "cards" / "stage_launch.md").read_text(encoding="utf-8")
    check('"mode":"busy"' in launch and "whatever accelerators are FREE" in launch and '"deviation"' in launch,
          "the launch card says: free devices under the allowance, deviations on record, busy is not failure")
    rehearsal = (HERE.parent / "engine" / "cards" / "rehearsal.md").read_text(encoding="utf-8")
    check("same kind of launch configuration" in rehearsal, "the rehearsal runs the way the real stage will")


def main() -> None:
    the_ceiling_and_the_device_allowance_are_notebook_facts()
    the_estimate_is_the_agents_and_only_the_ceiling_is_compared()
    launches_record_devices_and_respect_the_allowance()
    a_busy_machine_costs_no_attempt_and_asks_the_user_only_after_the_wait()
    the_user_decides_a_busy_wait_through_the_real_gate_path()
    the_cards_ask_the_machine_questions_after_seeing_the_machine()
    done("RESOURCE REVIEW UNIT")


if __name__ == "__main__":
    main()
