#!/usr/bin/env python3
"""evo - engine CLI for Model Evolution v10.

The agent's whole standing contract:
    evo next     -> ONE task card; do exactly what it says
    evo submit   -> validation; fix listed deficiencies if rejected
Everything else (events, ids, state, scheduling, artifact registry) is an
engine side effect.

CONTINUITY: the only legitimate stopping points of a session are (a) a gate
awaiting the user, (b) DONE, (c) WAITING on an external workflow/evaluation run
with nothing actionable, or (d) an open project_scan/configure interview waiting
for a concrete user answer. Every other output ends with an explicit next
command - stopping anywhere else is an operator bug, not a natural pause.

Stdlib only. Python 3.10+. Windows-safe (UTF-8 stdout/stderr and files).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Windows pipes default to the ANSI codepage until Python 3.15: any non-ASCII
# user text (project names, titles, quoted rejections) printed to a piped
# stdout would die with UnicodeEncodeError AFTER state was saved - the task
# card would then never be delivered on stdout for that task. Files were
# always UTF-8; make the stdout/stderr channel match them.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import econfig          # noqa: E402
import edoctor          # noqa: E402
import ecanary          # noqa: E402
import egraph           # noqa: E402
import erecover         # noqa: E402
import erun             # noqa: E402
import esched           # noqa: E402
import esmoke           # noqa: E402
import estore           # noqa: E402
import eutil            # noqa: E402


def _print(obj: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
        return
    kind = obj.get("kind")
    if kind == "task":
        print(f"TASK {obj['task']} ({obj['type']}) attempt {obj.get('attempts', 0) + 1}")
        print(f"card:   {obj.get('card')}")
        print(f"bundle: {obj.get('bundle')}")
        print("outputs:")
        for o in obj.get("outputs", []):
            print(f"  - {o}")
        if obj.get("type") in ("project_scan", "configure"):
            print("Read the card and conduct its user interview. If a concrete answer is missing, ask and "
                  "wait with this task open; otherwise do the work and submit.")
        else:
            print("Read the card, do the work, then submit. NOT a stopping point.")
    elif kind == "gate":
        print(f"GATE {obj['gate']} ({obj['gate_kind']})")
        print(f"card: {obj.get('card')}")
        print(obj.get("summary", ""))
        print("Present this to the user, then record: evo decide --gate "
              f"{obj['gate']} --approve|--reject [--note ...]")
        print("This is a LEGITIMATE stopping point only while the user's decision is pending.")
    elif kind == "rejected":
        print(f"REJECTED {obj['task']} (attempt {obj['attempt']}/{obj['max_attempts']})")
        for e in obj.get("errors", []):
            print(f"  - {e}")
        if obj.get("escalation"):
            print(f"Task is stuck; escalation gate {obj['escalation']} raised. Run 'evo next' NOW.")
        elif obj.get("status") == "cancelled" and obj.get("repair"):
            print("Task cancelled FOR REPAIR: the node returned to building with a fix pass; "
                  "nothing was abandoned. Run 'evo next' NOW.")
        elif obj.get("status") == "cancelled":
            print("Task cancelled; its lane/node was abandoned per policy. Run 'evo next' NOW.")
        else:
            print("Fix exactly these deficiencies, then submit again. NOT a stopping point.")
    elif kind == "accepted":
        print(f"ACCEPTED {obj['task']} ({obj.get('type')})")
        print("CONTINUE: run 'evo next' immediately - an accepted task is never a stopping point.")
    elif kind == "waiting":
        print(f"WAITING: {obj.get('reason')}")
        print("If a workflow-stage job is in flight: check it, report with 'evo run-update' when it ends, "
              "then run 'evo next'. Do not end the session unless the wait is genuinely external - "
              "OR the reason above asks a USER to review/decide something (a recovery plan review, "
              "a user-owned decision): presenting it and waiting for the human is equally legitimate.")
    elif kind == "done":
        print(f"DONE: {obj.get('reason')} (rounds completed: {obj.get('rounds')})")
    else:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    # R9 audit: standing obligations ride along with EVERY next output so a
    # parallel duty (unknown launch, held terminal RUN, plan awaiting the
    # human, open evidence gap) is never invisible behind the primary surface.
    if obj.get("notices"):
        print("STANDING OBLIGATIONS (in parallel with the above):")
        for line in obj["notices"]:
            print(f"  * {line}")


def _preflight_scientific_mutation(store: estore.Store, *, node: str | None = None,
                                   lane: str | None = None) -> None:
    """Apply the scheduler's authoritative contract checks before a CLI side effect.

    Keep this scoped to the scientific object being mutated: Engine derives the
    owning lane from ``node`` and still checks its active provenance chain.  The
    CLI deliberately does not duplicate seal-requiredness or upstream rules.
    """
    eng = esched.Engine(store)
    eng._assert_frozen_contract()
    eng._assert_artifact_seals(only_node=node, only_lane=lane)
    active = [hold for hold in eng.st.get("holds", []) if hold.get("status") == "active"]
    authorized_recoveries: set[str] = set()
    for case in eng.st.get("recoveries", []):
        if case.get("status") != "replaying":
            continue
        try:
            members = erecover.scope_members(case.get("scope") or {}, eng.st, eng.g)
        except ValueError:
            continue
        if node and node in members.get("nodes", []):
            authorized_recoveries.add(str(case.get("id") or ""))
    blocked = []
    for hold in active:
        recovery = str(hold.get("recovery") or "")
        if recovery and recovery in authorized_recoveries:
            continue
        if erecover.hold_covers_subject(
                hold, eng.st, eng.g, node=node, lane=lane):
            blocked.append(str(hold.get("id") or "?"))
    if blocked:
        raise SystemExit("[evo] active hold(s) block this side effect/authority mutation: "
                         + ", ".join(blocked))


def cmd_init(store: estore.Store, args) -> int:
    store.init(args.project_name or store.repo.name, args.goal or "")
    print(f"Initialized .evo in {store.repo}")
    print("Run 'evo next' to receive the first task (project_scan).")
    return 0


def cmd_next(store: estore.Store, args) -> int:
    eng = esched.Engine(store)
    out = eng.compute_next()
    _print(out, args.json)
    if out.get("kind") == "task" and not args.json and out.get("card"):
        if out.get("represented"):
            # v11: an open task's card was already printed in full when it was
            # first issued; re-printing it on every poll cost 5-8K read tokens
            # per node. The card FILE is the durable source: a fresh agent (or
            # one that lost context) follows the pointer and reads it.
            print(f"\ntask {out.get('task')} is already open (attempt {out.get('attempt', 1)}).")
            print(f"Card unchanged at: {out['card']}")
            if out.get("bundle"):
                print(f"Bundle (refreshed on every rejection - rejection feedback lands there): "
                      f"{out['bundle']}")
            print("If this task's instructions are not in your context, READ those files "
                  "before doing anything else - do not work from memory.")
        else:
            print("\n" + "=" * 72)
            print(eutil.read_text(eutil.rpath(store.repo, out["card"])))
    return 0


def cmd_submit(store: estore.Store, args) -> int:
    eng = esched.Engine(store)
    out = eng.submit(args.task, session=getattr(args, "session", None))
    if out.get("kind") == "rejected" and not args.json and len(out.get("errors") or []) > 30:
        # Full list always on disk (errors_file); stdout keeps the head so a
        # malformed submission does not flood the agent's context four times
        # over. Anti-starvation needs availability, not repetition.
        shown = dict(out)
        shown["errors"] = list(out["errors"][:30]) + [
            f"... {len(out['errors']) - 30} more - full list at {out.get('errors_file')}"]
        _print(shown, args.json)
    else:
        _print(out, args.json)
    return 0 if out.get("kind") in ("accepted", "waiting") else 1


def cmd_validate(store: estore.Store, args) -> int:
    eng = esched.Engine(store)
    out = eng.validation_report(args.task, session=getattr(args, "session", None))
    if args.json:
        _print(out, True)
        return 0 if not out.get("errors") else 1
    errors = list(out.get("errors") or [])
    notes = list(out.get("notes") or [])
    print(f"VALIDATE {out.get('task')} ({out.get('type', '?')}) - dry run; "
          f"attempt {out.get('attempts', 0)}/{out.get('max_attempts', '?')} unchanged")
    for note in notes:
        print(f"  note: {note}")
    if errors:
        shown = errors[:30]
        for err in shown:
            print(f"  - {err}")
        if len(errors) > 30:
            print(f"  ... {len(errors) - 30} more (dry run writes no errors file; "
                  "fix these and validate again)")
        print(f"REJECTED (would be): {len(errors)} deficiency(ies). No attempt was spent.")
        return 1
    print("PASS: the validators submit runs would all accept these bytes as of now. "
          "Note: submit may still open a human-study gate and runs the accept transition "
          "plus a post-transition seal sweep; state can change between now and submit. "
          "Run 'evo submit --task " + str(out.get("task")) + "'.")
    return 0


def cmd_decide(store: estore.Store, args) -> int:
    if args.approve == args.reject:
        raise SystemExit("[evo] pass exactly one of --approve / --reject")
    eng = esched.Engine(store)
    out = eng.decide(args.gate, approve=args.approve, note=args.note, retry_stage=args.retry_stage)
    print(f"gate {out['gate']}: {out['status']}")
    print("Run 'evo next'.")
    return 0


def cmd_status(store: estore.Store, args) -> int:
    import econfig
    st = store.load_state()
    g = store.load_graph()
    reg = store.load_artifacts()
    cfg = store.load_config()
    charged: dict[str, float] = {}
    for entry in st.get("resource_ledger", []):
        for unit, value in (entry.get("usage") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                charged[str(unit)] = charged.get(str(unit), 0.0) + float(value)
    reserved: dict[str, float] = {}
    holders = [t for t in st.get("tasks", []) if t.get("status") == "open"] + \
              [r for r in st.get("runs", []) if erun.holds_reservation(r)]
    for holder in holders:
        for unit, value in (holder.get("resource_reservation") or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                reserved[str(unit)] = reserved.get(str(unit), 0.0) + float(value)
    base_limits = econfig.resource_limits(cfg)
    overrides = st.get("resource_overrides") or {}
    specs = {n.get("id"): (eutil.read_json(eutil.rpath(store.repo, str(n.get("spec") or "")), {})
                           if n.get("spec") else {}) for n in g.get("nodes", [])}
    evidence_policy = cfg.get("evidence_policy") or {}
    out = {
        "tempo": econfig.describe_policy(cfg),
        "evidence_policy": {
            "training_replication": evidence_policy.get("training_replication") or {},
            "ablation": evidence_policy.get("ablation") or {},
            "scaling_mode": evidence_policy.get("scaling_mode") or "off",
        },
        "resources": {u: {"base_limit": lim, "approved_addition": float(overrides.get(u, 0.0) or 0.0),
                           "effective_limit": lim + float(overrides.get(u, 0.0) or 0.0),
                           "charged": charged.get(u, 0.0), "reserved": reserved.get(u, 0.0)}
                      for u, lim in base_limits.items()},
        "views": {"dashboard": ".evo/views/DASHBOARD.html",
                  "graph": ".evo/views/GRAPH.md", "frontier": ".evo/views/FRONTIER.md"},
        "phase": st.get("phase"),
        "current_round": st.get("current_round"),
        "round_status": st.get("round_status"),
        "open_tasks": [{"id": t["id"], "type": t["type"], "attempts": t["attempts"]}
                       for t in st["tasks"] if t["status"] == "open"],
        "stuck_tasks": [t["id"] for t in st["tasks"] if t["status"] == "stuck"],
        "open_gates": [{"id": gt["id"], "kind": gt["kind"]} for gt in st["gates"] if gt["status"] == "open"],
        "lanes": [{"id": l["id"], "round": l["round"], "intent": l["intent"],
                   "experiment_purpose": l.get("experiment_purpose") or "candidate", "status": l["status"],
                   "idea": l.get("idea"), "node": l.get("node")}
                  for l in st["lanes"] if l["round"] == st.get("current_round")],
        "nodes": [{"id": n["id"], "role": n["role"], "level": n.get("level"),
                   "level_label": egraph.level_label(n),
                   "experiment_purpose": n.get("experiment_purpose") or "candidate",
                   "training_replication": (specs.get(n.get("id")) or {}).get("training_replication") or {},
                   "probe_execution": (specs.get(n.get("id")) or {}).get("probe_execution") or {},
                   "status": n["status"],
                   "stage_cursor": n.get("stage_cursor"), "replica_index": n.get("replica_index"),
                   "replicas_completed": n.get("replicas_completed") or [], "verdict": n.get("verdict"),
                   "scores": n.get("scores", {})}
                  for n in g.get("nodes", [])],
        "rounds_closed": len([r for r in st.get("rounds", []) if r.get("closed_at")]),
        "runs_active": [{"id": r["id"], "node": r["node"], "stage": r.get("stage"),
                         "seed": r.get("replica_seed"), "replica_index": r.get("replica_index"),
                         "replica_total": r.get("replica_total"), "job": r.get("job"),
                         "status": r.get("status"), "evidence_status": r.get("evidence_status"),
                         "adoption_status": r.get("adoption_status")}
                        for r in st.get("runs", [])
                        if r.get("status") in ("prepared", "launch_unknown", "running") or
                           (r.get("status") in ("finished", "failed", "cancelled") and
                            r.get("evidence_status") in ("pending", "incomplete", "invalid"))],
        "artifacts": [{"id": a["id"], "node": a.get("node"), "stage": a.get("stage"),
                       "kind": a.get("kind"), "status": a.get("status")}
                      for a in reg.get("artifacts", [])],
        # R7 audit: holds/recoveries were invisible here, so a fresh session
        # reading status could not see a pending recovery review at all.
        "holds": [{"id": h.get("id"), "scope": h.get("scope"), "reason": h.get("reason")}
                  for h in st.get("holds", []) if h.get("status") == "active"],
        "recoveries": [{"id": c.get("id"), "status": c.get("status"),
                        "hold": c.get("hold"), "plan_path": c.get("plan_path"),
                        "plan_digest": c.get("plan_digest")}
                       for c in st.get("recoveries", [])
                       if c.get("status") in ("planned", "fork_required", "repairing", "replaying")],
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        if out.get("phase") == "done" and st.get("terminal_reason"):
            print(f"STOPPED: {st.get('terminal_reason')}")
        print(f"phase={out['phase']} round={out['current_round']} ({out['round_status']}) "
              f"rounds_closed={out['rounds_closed']}")
        print(f"tempo: {out['tempo']}")
        rep = out["evidence_policy"]["training_replication"]
        abl = out["evidence_policy"]["ablation"]
        print(f"training seeds: {rep.get('mode') or 'unset'}"
              + (f" ({rep.get('planned_runs')} runs, {rep.get('aggregation')})"
                 if rep.get("mode") == "preplanned" else " (one recorded seed; no repeats)"))
        print(f"targeted ablation: {abl.get('mode') or 'unset'} (manual approval always)")
        if out["resources"]:
            print("resources: " + "; ".join(
                f"{u} charged={v['charged']:g} reserved={v['reserved']:g} limit={v['effective_limit']:g}"
                for u, v in sorted(out["resources"].items())))
        print("user view: open .evo/views/DASHBOARD.html in a browser")
        for t in out["open_tasks"]:
            print(f"open task: {t['id']} ({t['type']}, attempts {t['attempts']})")
        for gt in out["open_gates"]:
            print(f"open gate: {gt['id']} ({gt['kind']})")
        for h in out["holds"]:
            print(f"active hold: {h['id']} scope={h['scope']} reason={h['reason']}")
        for c in out["recoveries"]:
            # R8 audit: the uniform "(recover-apply / recover-abort)" tail
            # pointed fork-classified cases at a command that always refuses;
            # replay the status- and action-correct verbs instead.
            case_row = next((row for row in st.get("recoveries", [])
                             if row.get("id") == c["id"]), c)
            print(f"recovery: {c['id']} {c['status']} hold={c['hold']} plan={c['plan_path']} "
                  f"digest={c['plan_digest']} - "
                  + esched.Engine._recovery_review_hint(case_row))
        for l in out["lanes"]:
            print(f"lane {l['id']} [{l['intent']}/{l['experiment_purpose']}] {l['status']} "
                  f"idea={l['idea']} node={l['node']}")
        for n in out["nodes"]:
            rep = n.get("training_replication") or {}
            print(f"node {n['id']} {n['role']}/{n['experiment_purpose']} {n['level_label']} {n['status']} "
                  f"verdict={n['verdict']} complete_runs={len(n['replicas_completed'])}/{rep.get('runs', '-')} "
                  f"{n['scores']}")
        for r in out["runs_active"]:
            print(f"run: {r['id']} node {r['node']} seed {r['seed']} stage {r['stage']} "
                  f"execution={r['status']} evidence={r['evidence_status']} job={r['job']}")
        for a in out["artifacts"]:
            print(f"artifact {a['id']} from {a['node']}/{a['stage']} kind={a['kind']} status={a['status']}")
    return 0


def cmd_artifacts(store: estore.Store, args) -> int:
    reg = store.load_artifacts()
    arts = reg.get("artifacts", [])
    if args.json:
        print(json.dumps(arts, ensure_ascii=False, indent=2))
        return 0
    if not arts:
        print("no artifacts registered yet")
        return 0
    for a in arts:
        print(f"{a['id']} [{a.get('status')}] {a.get('kind')} '{a.get('name')}' from {a.get('node')}/{a.get('stage')}")
        print(f"    uri: {a.get('uri')}")
        print(f"    stage_key: {a.get('stage_key') or '-'}")
    return 0


def cmd_run_smoke(store: estore.Store, args) -> int:
    # Must precede esmoke's first subprocess and its RESULTS/event writes.
    _preflight_scientific_mutation(store, node=args.node)
    res = esmoke.run_smoke(store, args.node)
    print(f"smoke {args.node}: {res['status']}")
    for s in res["steps"]:
        print(f"  [{s['status']}] {s['name']} (exit={s['exit']}) {s['detail']}")
    print(f"Results at .evo/nodes/{args.node}/smoke/RESULTS.json; now submit the smoke task.")
    return 0 if res["status"] == "pass" else 1


def cmd_run_rehearsal(store: estore.Store, args) -> int:
    # Must precede the rehearsal subprocess and its receipt/event writes.
    _preflight_scientific_mutation(store, node=args.node)
    import erehearsal
    record = erehearsal.run(store, args.node)
    status = str(record.get("status") or "")
    print(f"rehearsal {args.node}: {status} (receipt {record.get('receipt')})")
    if status == "passed":
        print("The full tiny chain is proven for the sealed implementation; submit the rehearsal task.")
    elif status == "blocked":
        print("Typed blockers were recorded; submit the task as-is - they escalate to the user.")
    else:
        print("Inspect the engine-owned receipt/logs under .evo/nodes/"
              f"{args.node}/rehearsal/, then submit as-is: the typed rejection routes the node "
              "to an implementation fix pass (never edit sealed code here).")
    return 0 if status == "passed" else 1


def cmd_run_infra_canary(store: estore.Store, args) -> int:
    _preflight_scientific_mutation(store)
    res = ecanary.run(store, args.task)
    print(f"infrastructure canary {args.task}: {res['status']} (exit={res.get('exit')})")
    print(f"receipt: {res.get('request', '').rsplit('/', 1)[0]}/RECEIPT.json")
    if res["status"] == "passed":
        print("The engine observed the complete canary pass; write the report and submit the infra_drill task.")
    elif res["status"] == "blocked":
        print("The project canary command reported typed blockers; write the report and submit so the engine can open the user gate.")
    else:
        for err in res.get("errors") or []:
            print(f"  - {err}")
        if res.get("exhausted"):
            print("The real-execution attempt limit is exhausted; the engine opened a user escalation gate. "
                  "Run 'evo next' and relay that gate to the user.")
        else:
            print("Fix the project canary command and run it again before submitting.")
    return 0 if res["status"] == "passed" else 1


def cmd_run_update(store: estore.Store, args) -> int:
    run = esched.Engine(store).update_run(
        args.run, args.status, metrics_file=args.metrics_file,
        ledger_file=args.ledger_file, note=args.note,
        failure_class=args.failure_class, repair_scope=args.repair_scope)
    print(f"run {args.run}: execution={run.get('status')} evidence={run.get('evidence_status')}")
    if run.get("status") == "finished" and not run.get("metrics_file"):
        print("Execution success is preserved. Evidence is pending; use 'evo run-reconcile' for this same RUN. Do not relaunch it.")
    elif run.get("status") in ("finished", "failed", "cancelled"):
        print("Run 'evo next' so the engine can ingest or route this factual result.")
    return 0


def cmd_run_bind(store: estore.Store, args) -> int:
    run = esched.Engine(store).bind_run(args.run, args.job, args.attempt_token)
    print(f"run {args.run} bound to {run.get('job')} (execution={run.get('status')})")
    return 0


def cmd_run_confirm_not_launched(store: estore.Store, args) -> int:
    esched.Engine(store).confirm_run_not_launched(args.run, args.note)
    print(f"run {args.run}: confirmed not launched; prepared intent may be used once")
    print("If this attempt will NOT be launched at all (e.g. its authority needs correction "
          f"first), settle the intent with 'evo run-update --run {args.run} --status cancelled' "
          "- a confirmed-unlaunched intent settles at zero usage. Then run 'evo next'.")
    return 0


def cmd_run_reconcile(store: estore.Store, args) -> int:
    run = esched.Engine(store).reconcile_run(
        args.run, metrics_file=args.metrics_file, ledger_file=args.ledger_file,
        accept_missing_probe=args.accept_missing_probe, note=args.note,
        accept_missing_evidence=args.accept_missing_evidence)
    print(f"run {args.run}: execution={run.get('status')} evidence={run.get('evidence_status')} "
          f"adoption={run.get('adoption_status')}")
    if run.get("evidence_disposition") in ("irrecoverable_quarantined",):
        print("Evidence gap closed on record (terminal disposition; the receipt is in the RUN's "
              "evidence directory). Run 'evo next'.")
        return 0
    if run.get("evidence_status") in ("incomplete", "invalid"):
        print("Evidence is still unresolved; no replacement execution was authorized.")
        for error in run.get("evidence_errors") or []:
            print(f"  - {error}")
    elif run.get("evidence_status") == "pending" and not run.get("absorbed"):
        # R8 (external audit r5): under an active hold the bytes are recorded
        # but authority did NOT move - saying "reconciled" here sent the
        # operator away believing the RUN was settled.
        print("Bytes recorded, but authority is DEFERRED by an active hold: the RUN is not "
              "absorbed/adopted yet. To inspect before adoption keep the hold; to proceed: "
              "'evo resume --hold ... --note ...' then 'evo run-reconcile' again (adopts), "
              "then 'evo recover-plan' BEFORE 'evo next' if you still suspect this evidence.")
    else:
        print("Same-RUN evidence reconciled. Run 'evo next'.")
    return 0


def cmd_hold(store: estore.Store, args) -> int:
    hold = esched.Engine(store).create_hold(args.scope, args.reason)
    print(f"hold {hold['id']} active on {args.scope}: {args.reason}")
    print("External jobs were not falsified or cancelled. A RUN finishing under this hold is "
          "recorded but NOT absorbed (evidence stays pending/deferred - that is the brake "
          "working, not a reconcile failure). To audit it before it becomes authority: "
          "resume the hold, 'evo run-reconcile' (adopts the evidence), then 'evo recover-plan' "
          "BEFORE 'evo next'. About to plan a recovery on this same scope? recover-plan absorbs "
          "this hold into its own brake automatically.")
    return 0


def cmd_resume(store: estore.Store, args) -> int:
    eng = esched.Engine(store)
    hold = eng.release_hold(args.hold, args.note)
    # R8 audit: the hold's own stdout promised "resume -> run-reconcile
    # (adopts) -> recover-plan BEFORE next"; printing a bare next here
    # contradicted it and next would have adopted the reviewed RUN first.
    # The deferral now persists on the RUN, so next stays safe either way -
    # but the honest continuation is the reconcile step itself.
    deferred = [r for r in eng.st.get("runs", [])
                if str(hold["id"]) in (r.get("adoption_deferred_by_hold") or [])]
    if deferred:
        print(f"hold {hold['id']} released. The following RUN(s) finished under review and "
              "stay UNADOPTED until you decide:")
        for r in deferred:
            print(f"  evo run-reconcile --run {r.get('id')}    (adopts its evidence)  - or "
                  "'evo recover-plan ...' first if the doubt stands")
        print("Then run 'evo next'.")
    else:
        print(f"hold {hold['id']} released. Run 'evo next'.")
    return 0


def cmd_recover_plan(store: estore.Store, args) -> int:
    case = esched.Engine(store).plan_recovery(
        args.target, args.boundary, args.reason, repair_scope=args.repair_scope)
    print(f"recovery {case['id']} planned; scoped hold {case['hold']} is active")
    print(f"plan: {case['plan_path']}")
    print(f"digest: {case['plan_digest']}")
    actions = [str(a) for a in (case.get("action") or [])]
    print(f"actions: {', '.join(actions)}")
    # R8 (external audit r5): a fork classification is a TERMINAL diagnosis -
    # this engine deliberately supports only narrow suffix replay, and
    # recover-apply would only mark the case fork_required and error out.
    # Printing the doomed apply command sent the operator into a wall; print
    # the real handoff protocol instead.
    forks = sorted(set(actions) & {"fork_node", "fork_lane", "fork_project"})
    if forks:
        print(f"This diagnosis is TERMINAL ({', '.join(forks)}): the damaged authority has hard "
              "consumers and cannot be rewritten in place - by design, there is no in-place apply.")
        # R8 audit: the handoff is rebuilt from the PERSISTED case by one
        # shared factory - status/next/recover-status replay the same text, so
        # a fresh session no longer depends on this stdout having survived.
        for line in esched.Engine.fork_handoff_lines(case):
            print("  " + line)
        print("  (WITHOUT --abandon-node an abort re-frees the OLD authority as a live parent "
              "again - pass it unless that is exactly what you want. This handoff is replayed "
              "by 'evo status' and 'evo recover-status' at any time.)")
        return 0
    print(f"Review the plan, then apply exactly it with: evo recover-apply --recovery {case['id']} "
          f"--confirm {case['plan_digest']}")
    return 0


def cmd_recover_apply(store: estore.Store, args) -> int:
    case = esched.Engine(store).apply_recovery(args.recovery, args.confirm)
    print(f"recovery {case['id']}: {case['status']} (boundary={case['boundary']})")
    if case.get("status") == "completed":
        # R8 audit: this branch is a real stop-releasing step (the hold is
        # gone, parked work may have reopened) - it must hand the loop back.
        print("The derived/annotated correction is complete and its scoped hold was released. "
              "Run 'evo next'.")
    else:
        print("Run 'evo next'. The scoped hold remains until the repaired authority is sealed.")
    return 0


def cmd_recover_abort(store: estore.Store, args) -> int:
    case = esched.Engine(store).abort_recovery(
        args.recovery, args.reason, abandon_node=args.abandon_node)
    print(f"recovery {case['id']}: aborted ({case.get('result')})")
    print("Run 'evo next'.")
    return 0


def cmd_recover_status(store: estore.Store, args) -> int:
    st = store.load_state()
    rows = list(st.get("recoveries") or [])
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    elif not rows:
        print("no recovery cases")
    else:
        for row in rows:
            print(f"{row.get('id')} [{row.get('status')}] target={row.get('target')} "
                  f"boundary={row.get('boundary')} hold={row.get('hold')} plan={row.get('plan_path')}")
            if row.get("status") in ("planned", "fork_required", "repairing", "replaying"):
                print("  next step: " + esched.Engine._recovery_review_hint(row))
    return 0


def _cmd_inject_lane(store: estore.Store, args, *, purpose: str, brief_title: str) -> int:
    """Mid-round intake for instrumental work: the round portfolio stays the
    only door for search bets, but a user question (probe) or a discovered
    defect (maintenance) may enter NOW instead of masquerading as next
    round's research candidate. Same legality rules as the portfolio door
    (evalid.injected_lane_errors), full seal/receipt discipline downstream."""
    import evalid
    # R7: the hold preflight must see the TARGET - an empty-subject check let
    # a node-scoped repairing hold be walked straight past (only project-scope
    # holds match a subjectless probe).
    _preflight_scientific_mutation(store, node=str(args.parent or "") or None)
    eng = esched.Engine(store)
    st = eng.st
    if st.get("phase") != "rounds" or st.get("round_status") != "running":
        raise SystemExit("[evo] mid-round intake needs an open, running round (phase=rounds); "
                         "declare the lane in the next open_round portfolio instead")
    rid = str(st.get("current_round") or "")
    # R8 (external audit r5): the RECEIVING round's own hold must also block
    # intake - a probe on an old-round parent walked past a current-round
    # hold, and the resume then reopened the paused close task into the
    # same deadlock this door exists to avoid.
    round_holds = erecover.active_holds_for_subject(st, eng.g, round_=rid)
    if round_holds:
        raise SystemExit("[evo] the current round is under active hold(s) "
                         + ", ".join(round_holds)
                         + "; resume them (or finish their recovery) before injecting a lane")
    # R7/R8: ANY not-yet-terminal close_round lifecycle (open, paused, stuck -
    # and a stuck task's escalation gate) means this round is already closing.
    # An injected lane would make that task permanently unsubmittable
    # (ROUND_ACTIVE_LANES) while it pre-empts all scheduling - and the
    # escalation gate's two decisions were both wrong: approve re-opened the
    # doomed close ahead of the new lane's design task forever, reject
    # force-closed the round and stranded the just-accepted lane. Cancel the
    # whole close lifecycle; the scheduler re-mints it once the lane is done.
    for t in st.get("tasks", []):
        if t.get("type") == "close_round" and t.get("status") in ("open", "paused", "stuck") \
                and str((t.get("subject") or {}).get("round") or "") == rid:
            for gate in st.get("gates", []):
                if gate.get("status") == "open" and gate.get("kind") == "escalation" \
                        and str((gate.get("subject") or {}).get("task") or "") == str(t.get("id")):
                    gate["status"] = "cancelled"
                    gate["resolved_at"] = eutil.utc_now()
                    gate["note"] = "superseded: mid-round intake cancelled the stuck close_round task"
                    store.event("engine", "gate_cancelled", gate=gate.get("id"),
                                reason="close_round_lifecycle_cancelled")
            t["status"] = "cancelled"
            t.pop("_render", None)
            t["updated_at"] = eutil.utc_now()
            store.event("engine", "close_round_task_cancelled", task=t.get("id"), round=rid,
                        reason="mid-round instrumental intake reopened the round's work")
    name = str(args.name or f"{purpose.replace('_', '-')}-{rid.lower()}")
    text = str(args.question if purpose == "diagnostic_probe" else args.defect or "").strip()
    if len(text) < 20:
        flag = "--question" if purpose == "diagnostic_probe" else "--defect"
        raise SystemExit(f"[evo] {flag} needs >= 20 chars of substance (it becomes the lane brief)")
    brief_rel = f".evo/rounds/{rid}/lanes/{name}/BRIEF.md"
    ln = {"name": name, "intent": "exploit", "experiment_purpose": purpose,
          "search_origin": "repair", "min_level": 0,
          "parents": [str(args.parent)], "bottleneck_ids": [], "brief_md": brief_rel}
    errs = evalid.injected_lane_errors(eng.ctx(), ln, rid)
    if errs:
        raise SystemExit("[evo] cannot open this lane:\n  - " + "\n  - ".join(errs))
    # Containment belt beside the name slug check: the engine authors this file,
    # so it must be provably inside the managed .evo tree before any write.
    brief_path = eutil.rpath(store.repo, brief_rel).resolve()
    evo_root = (store.repo / ".evo").resolve()
    if evo_root not in brief_path.parents:
        raise SystemExit(f"[evo] refusing to write a lane brief outside .evo: {brief_path}")
    if brief_path.exists():
        raise SystemExit(f"[evo] a lane brief already exists at {brief_rel}; choose another --name "
                         "(an existing brief is another lane's frozen evidence)")
    eutil.write_text(eutil.rpath(store.repo, brief_rel),
                     f"# {brief_title}\n\n## Goal\n{text}\n\n## Constraints\n"
                     f"- instrumental work: no novelty claim, level 0, manual user gate\n"
                     f"- parent: {args.parent}\n")
    lane = eng._create_lane(rid, ln)
    # actor=engine, matching the lane_created event this rides beside.  Unlike
    # `evo decide`, which only the user may run and so records actor=user
    # truthfully, this door is open to the agent by design - recording a
    # principal the engine cannot observe would put a guess in the audit log.
    # Authority over instrumental work is exercised at the manual gate, and
    # gate_decided already records who exercised it.
    store.event("engine", "instrumental_lane_injected", lane=lane["id"], round=rid,
                purpose=purpose, parent=str(args.parent), note=text[:200])
    eng.save()
    print(f"lane {lane['id']} ({purpose}) opened in {rid} on parent {args.parent}.")
    print("Run 'evo next' - the design task is the next actionable step, and the "
          "user gate after it is always manual.")
    return 0


def cmd_probe(store: estore.Store, args) -> int:
    return _cmd_inject_lane(store, args, purpose="diagnostic_probe",
                            brief_title="Diagnostic probe (user question)")


def cmd_maintain(store: estore.Store, args) -> int:
    return _cmd_inject_lane(store, args, purpose="maintenance",
                            brief_title="Maintenance (defect repair with parity contract)")


def cmd_waive_repeat(store: estore.Store, args) -> int:
    """USER-only release of an approved repeat_measure whose physical re-run
    turned out impossible (v11.1 R1 fix). Without this verb, approval had no
    exit: the metric door demanded the 2-run aggregate forever, and the only
    escape destroyed a fully-paid node. Waiving keeps the single-run verdict
    exactly as measured, with the whole decision trail on record."""
    # R7: scoped preflight - the subjectless form walked past node-scoped holds
    _preflight_scientific_mutation(store, node=str(args.node or "") or None)
    eng = esched.Engine(store)
    note = str(args.note or "").strip()
    if len(note) < 20:
        raise SystemExit("[evo] --note needs >= 20 chars: record WHY the bought-back repeat "
                         "cannot be executed (the approval and this release are both decisions)")
    node = next((n for n in eng.g.get("nodes", []) if n.get("id") == str(args.node)), None)
    if node is None:
        raise SystemExit(f"[evo] node {args.node} does not exist")
    rm = node.get("repeat_measure")
    if not isinstance(rm, dict):
        raise SystemExit(f"[evo] node {args.node} has no approved repeat_measure to waive")
    if rm.get("waived"):
        raise SystemExit(f"[evo] node {args.node}'s repeat_measure is already waived")
    if node.get("repeat_measure_done"):
        raise SystemExit(f"[evo] node {args.node}'s repeat already settled on the 2-run aggregate; "
                         "there is nothing left to waive")
    # R9-002: the engine-run buy-back has real RUNs behind it. A live one must
    # settle through the normal RUN verbs first (bind / confirm-not-launched /
    # run-update / run-reconcile) - waiving cannot make an external job
    # disappear. An already-settled repeat evaluation means the second number
    # EXISTS; report both runs instead of waiving a real measurement.
    live = [r for r in eng.st.get("runs", [])
            if r.get("repeat_measure_attempt") and r.get("node") == node["id"]
            and not erun.is_terminal(r)]
    if live:
        raise SystemExit("[evo] the engine-run repeat has live RUN(s) "
                         + ", ".join(str(r.get("id")) for r in live)
                         + "; settle them first (run-bind / run-confirm-not-launched / "
                           "run-update / run-reconcile), then waive")
    if node.get("repeat_eval_run"):
        raise SystemExit(f"[evo] node {args.node}'s repeat evaluation already settled "
                         f"(RUN {node.get('repeat_eval_run')}); the second measurement exists - "
                         "report BOTH runs instead of waiving it away")
    # R10-021: the resume snapshot was taken when the repeat was approved -
    # it belongs to that authority generation. Restoring it over a node whose
    # authority is mid-revision (an active recovery case, or a fix routing in
    # force) overwrote building/fix state with a stale workflow_done and left
    # the node with no reachable card. A recovery that changes the node's
    # generation archives the approval itself (see erepair); until then this
    # verb refuses rather than restores across generations.
    def _case_covers_node(c: dict) -> bool:
        try:
            members = erecover.scope_members(c.get("scope") or {}, eng.st, eng.g)
        except ValueError:
            return False
        return node["id"] in (members.get("nodes") or [])

    active_case = next(
        (c for c in eng.st.get("recoveries", [])
         if c.get("status") in ("planned", "fork_required", "repairing", "replaying")
         and _case_covers_node(c)), None)
    if active_case is not None:
        raise SystemExit(f"[evo] recovery {active_case.get('id')} ({active_case.get('status')}) covers "
                         f"node {args.node}; its authority is mid-revision and the repeat approval's "
                         "resume snapshot belongs to the previous generation - finish or abort the "
                         "case first (an implementation recovery archives the approval itself)")
    if node.get("status") not in ("workflow_done", "stage_ready", "evidence_pending") \
            and node.get("repeat_pending_seed") is not None:
        hint = (" The node is mid-fix: decide the open escalation/fix first (approving the "
                "retry lands the fix; the restart archives this approval by itself), then "
                "waive if the repeat is still unwanted." if node.get("status") == "building"
                else "")
        raise SystemExit(f"[evo] node {args.node} is {node.get('status')!r}; the pending repeat can "
                         "only be waived from the repeat lane's own states "
                         "(stage_ready/workflow_done/evidence_pending) - another lifecycle owns "
                         "the node right now." + hint)
    if node.get("repeat_pending_seed") is not None:
        # restore the pre-repeat position the approval snapshot recorded, so
        # the scheduler never replays the preplanned lanes as ordinary work
        pending_run = str(node.get("evidence_pending_run") or "")
        if pending_run and any(r.get("id") == pending_run and r.get("repeat_measure_attempt")
                               for r in eng.st.get("runs", [])):
            # a waived repeat's unreconciled evidence settles as history via
            # the RUN obligation channel; the node no longer waits on it
            node.pop("evidence_pending_run", None)
        resume = rm.get("resume") or {}
        if resume.get("stage_cursor") is not None:
            node["stage_cursor"] = resume.get("stage_cursor")
        if resume.get("replica_index") is not None:
            node["replica_index"] = resume.get("replica_index")
        node["status"] = str(resume.get("status") or "workflow_done")
        node.pop("repeat_pending_seed", None)
        # R10 self-audit (H1b) + R11-001: preparing a repeat RUN archived the
        # BASE attempt's landing bytes into that RUN's archive dir, and the
        # repeat's own product registrations stayed DEFERRED - the registry
        # head still describes the base measurement. A waive therefore
        # restores the base bytes UNCONDITIONALLY: bytes a partial repeat
        # left at the landing belong to a measurement the user just
        # discarded, and leaving them under a base-generation digest made
        # every later consumer read repeat-prefix bytes the registry never
        # admitted. The partial bytes move into the RUN's own archive - a
        # RUN's facts are never destroyed, they just stop impersonating the
        # adopted measurement.
        # Newest attempt FIRST: each retry archived whatever the previous
        # attempt left at the landing, so oldest-first would re-archive the
        # just-restored base bytes as "repeat debris" and finish with the
        # first attempt's partial bytes on the landing. Walking newest->oldest
        # peels the attempts back so the OLDEST archive (the base measurement)
        # is what finally lands.
        repeat_rows = [r for r in eng.st.get("runs", [])
                       if r.get("repeat_measure_attempt") and r.get("node") == node["id"]]
        for r in reversed(repeat_rows):
            for row in (r.get("preexisting_result_landings") or []):
                declared = str(row.get("declared") or "")
                archived = str(row.get("archived_artifact") or "")
                if not declared or not archived or row.get("restored_at"):
                    continue
                target = eutil.rpath(store.repo, declared)
                source = eutil.rpath(store.repo, archived)
                if not source.exists():
                    if target.exists() and not row.get("restored_at"):
                        # torn window: a previous waive moved the bytes back
                        # but ended before the stamp committed - converge the
                        # receipt instead of leaving the restore unrecorded
                        row["restored_at"] = eutil.utc_now()
                        store.event("engine", "preexisting_landing_restored",
                                    run=r.get("id"), declared=declared,
                                    reason="restore converged after an interrupted waive")
                    continue
                if target.exists():
                    # keep the debris path inside the run dir even for odd
                    # declared spellings (drive letters, parent hops)
                    safe = "/".join(part for part in
                                    str(declared).replace("\\", "/").replace(":", "_").split("/")
                                    if part and part != "..")
                    debris = eutil.rpath(store.repo,
                                         f".evo/runs/{r.get('id')}/superseded_repeat_output/{safe}")
                    debris.parent.mkdir(parents=True, exist_ok=True)
                    if debris.exists():
                        store.event("engine", "repeat_partial_output_already_archived",
                                    run=r.get("id"), declared=declared)
                    else:
                        target.replace(debris)
                        store.event("engine", "repeat_partial_output_archived",
                                    run=r.get("id"), declared=declared,
                                    archived_to=str(
                                        f".evo/runs/{r.get('id')}/superseded_repeat_output/{safe}"),
                                    reason="repeat waived; base measurement bytes restored")
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source.replace(target)
                    row["restored_at"] = eutil.utc_now()
                    store.event("engine", "preexisting_landing_restored",
                                run=r.get("id"), declared=declared,
                                reason="repeat waived before completion")
        # R9-002 pairing (reviewer finding): a failed repeat attempt routes
        # through the ordinary failure channel and may have left a
        # repeat_attempt marker, an open repeat_spend gate, or fix routing
        # fields on the node. Waiving the repeat retires the very spend those
        # point at - left behind, the orphan gate preempts all scheduling and
        # its reject arm would abandon a fully-paid node over a purchase that
        # no longer exists.
        ra = node.get("repeat_attempt") or {}
        ra_src = str(ra.get("source_run") or "")
        src_run = next((r for r in eng.st.get("runs", []) if r.get("id") == ra_src), None)
        if src_run is not None and src_run.get("repeat_measure_attempt"):
            node.pop("repeat_attempt", None)
            for gate in eng.st.get("gates", []):
                if gate.get("kind") == "repeat_spend" \
                        and gate.get("status") in ("open", "paused") \
                        and (gate.get("subject") or {}).get("node") == node["id"] \
                        and str((gate.get("subject") or {}).get("source_run") or "") == ra_src:
                    gate["status"] = "cancelled"
                    gate["resolved_at"] = eutil.utc_now()
                    gate["note"] = "superseded: repeat_measure waived; the replacement spend no longer exists"
                    store.event("engine", "gate_cancelled", gate=gate.get("id"),
                                reason="repeat_measure_waived", node=node["id"])
        if str(node.get("implementation_repair_source_run") or "") == ra_src and ra_src \
                and src_run is not None and src_run.get("repeat_measure_attempt"):
            for field in ("fix_needed", "fix_note", "implementation_repair_scope",
                          "implementation_repair_source_run"):
                node.pop(field, None)
            node["fix_needed"] = False
            node["fix_note"] = None
    # R10-015: the repeat lane may also have minted a resource_approval gate
    # (deficit while preparing the repeat) or a generic node escalation
    # (repeat attempts exhausted). Both carry the repeat identity in their
    # subject since R10; waiving retires them with the purchase - approving a
    # leftover one would widen the project contract (or reset counters) for a
    # spend that no longer exists, and its reject arm would discard the
    # restored node.
    repeat_run_ids = {str(r.get("id") or "") for r in eng.st.get("runs", [])
                      if r.get("repeat_measure_attempt") and r.get("node") == node["id"]}
    for gate in eng.st.get("gates", []):
        if gate.get("status") not in ("open", "paused"):
            continue
        gs = gate.get("subject") or {}
        if gs.get("node") != node["id"]:
            continue
        born_of_repeat = (
            (gate.get("kind") == "resource_approval" and gs.get("repeat_measure"))
            or (gate.get("kind") == "escalation"
                and str(gs.get("repeat_source_run") or "") in repeat_run_ids
                and str(gs.get("repeat_source_run") or "")))
        if born_of_repeat:
            gate["status"] = "cancelled"
            gate["resolved_at"] = eutil.utc_now()
            gate["note"] = "superseded: repeat_measure waived; the purchase this gate guarded no longer exists"
            store.event("engine", "gate_cancelled", gate=gate.get("id"),
                        reason="repeat_measure_waived", node=node["id"])
    # R11-001: the repeat never produced an adopted measurement - its deferred
    # product registrations are discarded with it (the registry head never
    # moved, so there is nothing to roll back).
    dropped = rm.pop("pending_product_registrations", None)
    if dropped:
        store.event("engine", "repeat_product_registrations_discarded",
                    node=node["id"], count=len(dropped), reason="repeat_measure waived")
    rm["waived"] = True
    rm["waive_note"] = note
    rm["waived_at"] = eutil.utc_now()
    node["repeat_measure_done"] = True
    # The presented evaluation card baked the duty block into its saved render;
    # a waive must strip it AND rewrite the on-disk CARD/BUNDLE (final audit
    # C21/C27: popping presented_at alone left the stale block on disk), or
    # the card keeps demanding the exact form the validator now refuses.
    for t in eng.st.get("tasks", []):
        if t.get("type") == "evaluate" and (t.get("subject") or {}).get("node") == node["id"] \
                and t.get("status") in ("open", "paused", "stuck"):
            render = t.setdefault("_render", {})
            render["extra_blocks"] = [
                row for row in (render.get("extra_blocks") or [])
                if not (isinstance(row, (list, tuple)) and row
                        and "repeat measurement" in str(row[0]).lower())] + [
                ("Repeat measurement WAIVED by the user",
                 [f"- The approved repeat on this node was released ({note[:120]}). Report the SINGLE "
                  "run as usual - do NOT report a training_replication block."])]
            eng._rematerialize(t)
    egraph.touch(node)
    store.event("user", "repeat_measure_waived", node=node["id"], cell=rm.get("cell"), note=note)
    eng.save()
    print(f"repeat_measure on {node['id']} waived; the single-run verdict stands, on record.")
    print("note: waive ONLY when the repeat was never executed - if it ran, report both runs instead "
          "(waiving discards a real measurement).")
    # R8 audit: this decision unblocks an open evaluate task whose CARD/BUNDLE
    # were just rewritten - hand the loop back to it explicitly.
    refreshed = next((t for t in eng.st.get("tasks", [])
                      if t.get("status") == "open" and t.get("type") == "evaluate"
                      and (t.get("subject") or {}).get("node") == node["id"]), None)
    if refreshed is not None:
        print(f"The open evaluate card was refreshed: {refreshed.get('card')} - re-read it, then "
              f"submit as usual (or run 'evo next' to have it re-presented).")
    else:
        print("Run 'evo next'.")
    return 0


def cmd_propose_abandon(store: estore.Store, args) -> int:
    """The honest early-exit: the agent PROPOSES stopping a dead direction, the
    user decides. Before this, the cheapest legal exit from an admitted lane
    was riding it to attempts-exhaustion (up to three full sketch batches),
    and a doomed node could not be stopped mid-flight at all."""
    # R7: scoped preflight - the subjectless form walked past node/lane-scoped
    # holds, letting a proposal (and its later gate decision) abandon a node
    # out from under its active repairing recovery.
    _preflight_scientific_mutation(store, node=str(args.node or "") or None,
                                   lane=str(args.lane or "") or None)
    eng = esched.Engine(store)
    reason = str(args.reason or "").strip()
    if len(reason) < 30:
        raise SystemExit("[evo] --reason needs >= 30 chars of substance: the user is being asked "
                         "to discard admitted work on your judgment - give them the mechanism")
    subject: dict = {"reason": reason}
    if bool(args.lane) == bool(args.node):
        raise SystemExit("[evo] propose-abandon takes exactly one of --lane or --node")
    if args.lane:
        lane = store.get_lane(eng.st, str(args.lane))
        if lane is None or lane.get("status") in ("done", "abandoned"):
            raise SystemExit(f"[evo] lane {args.lane} does not exist or is already terminal")
        subject["lane"] = str(args.lane)
        what = f"lane {args.lane} ({lane.get('name') or '?'}, status {lane.get('status')})"
    else:
        node = next((n for n in eng.g.get("nodes", []) if n.get("id") == str(args.node)), None)
        if node is None or node.get("status") in ("concluded", "abandoned"):
            raise SystemExit(f"[evo] node {args.node} does not exist or is already terminal")
        if node.get("role") == "baseline":
            raise SystemExit("[evo] the baseline cannot be abandoned; stopping the project is a "
                             "different decision (see rounds_max / round_continue)")
        subject["node"] = str(args.node)
        what = f"node {args.node} ({node.get('title') or '?'}, status {node.get('status')})"
    for g in eng.st.get("gates", []):
        if g.get("kind") == "abandon_request" and g.get("status") == "open" \
                and (g.get("subject") or {}).get("lane") == subject.get("lane") \
                and (g.get("subject") or {}).get("node") == subject.get("node"):
            raise SystemExit(f"[evo] an abandon request for this subject is already open ({g.get('id')})")
    gate = store.new_gate(
        eng.st, "abandon_request", subject,
        f"The agent proposes STOPPING {what} as a dead direction. Reason: {reason[:300]} "
        "Approve = deliberate stop (recorded as a decision, not a failure); "
        "reject = continue the work.")
    # R9 (external audit r6): materialize the engine report NOW. This gate is
    # deliberately non-blocking, so the scheduler only presents it once nothing
    # else is actionable - which for the usual case (the agent proposes a stop
    # while still holding that subject's open task) could be never. The gate
    # card contract is "relay the engine's report VERBATIM", and without this
    # the report the agent must relay did not exist yet.
    presented = eng._present_gate(gate)
    eng.save()
    print(f"abandon request {gate['id']} opened for {what}.")
    print(f"Report for the user (relay it verbatim): {presented.get('card')}")
    print("The user decides at the gate. It never blocks live work: 'evo next' keeps "
          "scheduling normally and presents this request when nothing else is actionable.")
    return 0


def cmd_log(store: estore.Store, args) -> int:
    store.event("agent", "note", note=args.note, task=args.task)
    print("logged")
    return 0


def cmd_revive(store: estore.Store, args) -> int:
    """User decision: reopen a pruned/archived lineage so future lanes may extend it."""
    import eartifact
    import egraph
    eng = esched.Engine(store)
    node = egraph.by_id(eng.g).get(args.node)
    if node is None:
        raise SystemExit(f"[evo] no node {args.node}")
    if node.get("retire_reason") is None:
        raise SystemExit(f"[evo] node {args.node} is not retired")
    if not (args.note or "").strip():
        raise SystemExit("[evo] revival needs --note with the user's reason")
    # Revival makes a scientific lineage and its artifacts reusable again.
    _preflight_scientific_mutation(store, node=args.node)
    # Retirement relaxed the node's WORKING-byte duties (a pruned worktree may
    # be deleted). Restoring authority therefore re-proves the COMPLETE active
    # contract - seal bytes, execution closure, and in Git mode the reviewed
    # commit/clean state - under a revived view, or the very next full sweep
    # would brick the project on bytes revival failed to check.
    prev = node["retire_reason"]
    node["retire_reason"] = None
    try:
        eng._assert_artifact_seals(only_node=args.node)
    except SystemExit as exc:
        node["retire_reason"] = prev
        raise SystemExit("[evo] cannot revive: the node's active contract no longer verifies "
                         f"(restore its workdir/worktree and sealed bytes first):\n{exc}") from exc
    egraph.touch(node)
    implementation_digest = str((node.get("implementation_seal") or {}).get("digest") or "")
    revived, skipped_rows = eartifact.revive_for_node(
        store, eng.reg, args.node, active_implementation_digest=implementation_digest)
    store.event("user", "node_revived", node=args.node, was=prev, note=args.note,
                artifacts_revived=revived,
                artifacts_skipped=[row.get("id") for row in skipped_rows])
    # R7 audit: the revive used to change graph+registry but leave every
    # rendered surface at the OLD world - FRONTIER/GRAPH views (the open
    # round card's declared inputs) still said "(archived - revive first)"
    # and an already-open open_round card was never re-rendered, so a cold
    # session read stale state while the live validator judged by the new
    # one. Refresh both in the same command.
    egraph.render_views(store, eng.g, eng.cfg, eng.st)
    refreshed = None
    for t in eng.st.get("tasks", []):
        if t.get("type") == "open_round" and t.get("status") == "open":
            eng._refresh_open_round_task(t)
            refreshed = t.get("id")
    eng.save()
    print(f"node {args.node} revived (was {prev}; {revived} artifact(s) restored). "
          "Future portfolios may extend it again."
          + (f" Open strategy card {refreshed} was re-rendered with the revived node."
             if refreshed else ""))
    # R8 audit: report what could NOT be restored - registry metadata alone
    # must not promise consumers bytes that are no longer there.
    for row in skipped_rows:
        print(f"  NOT restored: {row['id']} at {row['uri']!r} ({row['reason']}) - it stays "
              "stale; restore the bytes (or re-produce them) before consumers may bind it")
    return 0


def cmd_revise_infra(store: estore.Store, args) -> int:
    """User-owned mid-run INFRA_FACTS revision (v11.7).

    The bootstrap approval froze the facts as a snapshot, but infrastructure
    knowledge is a hypothesis that reality can refute. Before this verb the
    only exit from a wrong approved fact was restarting the project. Flow:
    write the corrected file to .evo/profile/INFRA_FACTS_PROPOSED.json, run
    this verb, and decide the opened gate. Approval swaps the facts in,
    re-stamps the approved digest, and RE-ARMS the integrated canary - new
    stage/eval spend stays refused until the fresh canary passes against the
    revised facts."""
    import ecanary
    import einfra
    eng = esched.Engine(store)
    if not eng.st.get("bootstrap_contract_confirmed"):
        raise SystemExit("[evo] the facts are not approved yet - revise them through the normal "
                         "channel (finish/redo the infra steps; if the infra_confirm gate is "
                         "open, reject it with a note to rescan)")
    if eng.st.get("infra_revision_pending"):
        raise SystemExit("[evo] an approved facts revision is already awaiting its fresh canary "
                         "proof; finish that first (run 'evo next')")
    open_rev = next((g for g in eng.st.get("gates", [])
                     if g.get("kind") == "infra_revision" and g.get("status") == "open"), None)
    if open_rev is not None:
        raise SystemExit(f"[evo] infra_revision gate {open_rev.get('id')} is already open; decide "
                         f"it first ('evo decide --gate {open_rev.get('id')} --approve/--reject')")
    note = str(args.note or "").strip()
    if len(note) < 40:
        raise SystemExit("[evo] --note must state WHAT was learned to be wrong and how it was "
                         "discovered (>= 40 chars); the revision reason is part of the record")
    proposed_path = eutil.rpath(store.repo, ".evo/profile/INFRA_FACTS_PROPOSED.json")
    proposed = eutil.read_json(proposed_path, None)
    if proposed is None:
        raise SystemExit("[evo] write the corrected facts to .evo/profile/INFRA_FACTS_PROPOSED.json "
                         "first (full file, not a diff)")
    errs = einfra.validate_facts(store, proposed)
    if errs:
        raise SystemExit("[evo] the proposed facts are invalid:\n  - " + "\n  - ".join(errs))
    current = einfra.load_facts(store, eng.cfg) or {}
    if ecanary.facts_digest_of(proposed) == ecanary.facts_digest_of(current):
        raise SystemExit("[evo] the proposed facts are byte-equivalent to the approved facts; "
                         "nothing to revise")
    changed = sorted(k for k in set(list(current.keys()) + list(proposed.keys()))
                     if current.get(k) != proposed.get(k))
    gate = store.new_gate(
        eng.st, "infra_revision", {"changed_blocks": changed,
                                   "proposed_digest": ecanary.facts_digest_of(proposed)},
        f"INFRA_FACTS revision proposed ({', '.join(changed)} changed): {note[:160]}. "
        "Approve to adopt the revised facts - the integrated canary then re-proves the "
        "REAL path before any new stage/eval spend; reject to keep the approved facts.")
    store.event("user", "infra_revision_proposed", gate=gate.get("id"),
                changed_blocks=changed, note=note)
    eng.save()
    print(f"infra revision gate {gate.get('id')} opened (changed blocks: {', '.join(changed)}).")
    print("Run 'evo next' FIRST - it renders the gate report (approved vs proposed, field by "
          "field) for the user; only then record their decision with 'evo decide --gate "
          + str(gate.get("id")) + " --approve|--reject --note ...'")
    return 0


def cmd_rebind_artifact(store: estore.Store, args) -> int:
    """User decision: re-freeze one accepted node's input binding to the
    artifact's CURRENT generation/digest (R11-005).

    Plan acceptance freezes generation+digest; when the producer legitimately
    revises and regenerates the same AR id, every launch of this consumer is
    rejected with GENERATION_DRIFT - and no ordinary flow may rewrite an
    accepted spec's binding. This verb is that missing entry: an explicit,
    audited user decision that the NEW bytes are the intended input. It never
    runs implicitly, and it refuses while the producer is still mid-revision
    (rebinding to a generation that is itself about to be replaced would just
    re-arm the same rejection)."""
    import eartifact
    import egraph
    eng = esched.Engine(store)
    node = egraph.by_id(eng.g).get(args.node)
    if node is None:
        raise SystemExit(f"[evo] no node {args.node}")
    if node.get("status") in ("concluded", "abandoned"):
        raise SystemExit(f"[evo] node {args.node} is {node['status']}; rebinding is for nodes with "
                         "launches still ahead - a settled result never changes its input identity")
    bindings = node.get("artifact_bindings") if isinstance(node.get("artifact_bindings"), dict) else None
    bound = (bindings or {}).get(args.artifact)
    if bound is None:
        raise SystemExit(f"[evo] node {args.node} has no frozen binding for {args.artifact}; "
                         "rebinding only replaces an existing plan-time freeze")
    art = eartifact.by_id(eng.reg).get(args.artifact)
    if art is None:
        raise SystemExit(f"[evo] artifact {args.artifact} is not in the registry - "
                         "run 'evo artifacts' to list registered ids")
    if str(art.get("status")) != "available":
        raise SystemExit(f"[evo] artifact {args.artifact} is {art.get('status')} "
                         f"({art.get('stale_reason') or 'producer superseded it'}); recover or revive the "
                         "producer first - rebinding may only target bytes the registry stands behind")
    producer = egraph.by_id(eng.g).get(str(art.get("node") or ""))
    if producer is not None and (producer.get("fix_needed")
                                 or producer.get("implementation_revision_pending")):
        raise SystemExit(f"[evo] producer {art.get('node')} is mid-revision; the current generation is "
                         "itself about to be replaced - wait for it to settle, then rebind once")
    live = [r for r in eng.st.get("runs", [])
            if r.get("node") == node["id"] and not erun.is_terminal(r)]
    if live:
        raise SystemExit("[evo] node " + str(args.node) + " has live RUN(s) "
                         + ", ".join(str(r.get("id")) for r in live)
                         + " that were validated against the CURRENTLY frozen binding; settle them "
                           "first (run-update / run-reconcile / run-confirm-not-launched), then "
                           "rebind - re-freezing under a launched attempt would record evidence "
                           "computed from bytes the new binding never named")
    note = str(args.note or "").strip()
    if len(note) < 20:
        raise SystemExit("[evo] --note must state WHY the new generation is the intended input "
                         "(>= 20 chars); an input-identity change is part of the scientific record")
    _preflight_scientific_mutation(store, node=args.node)
    if int(art.get("generation") or 1) == int((bound or {}).get("generation") or 0) and             str(art.get("content_digest") or "") == str((bound or {}).get("content_digest") or ""):
        print(f"[evo] node {args.node}: binding for {args.artifact} already matches generation "
              f"{art.get('generation')}; nothing to do")
        return 0
    was = dict(bound)
    bindings[args.artifact] = {"generation": art.get("generation"),
                               "content_digest": str(art.get("content_digest") or "")}
    node["artifact_bindings"] = bindings
    egraph.touch(node)
    store.event("user", "artifact_binding_refrozen", node=args.node, artifact=args.artifact,
                was_generation=was.get("generation"), now_generation=art.get("generation"),
                note=note)
    eng.save()
    print(f"node {args.node}: {args.artifact} re-frozen to generation {art.get('generation')} "
          f"(was {was.get('generation')}). Launch checks now expect the new bytes.")
    return 0


def cmd_autonomy(store: estore.Store, args) -> int:
    """User decision: change the supervision mode MID-RUN (gated|auto|full_auto).
    The blessed channel for what would otherwise be a hand-edit of the frozen
    config: validated BEFORE writing (an invalid result refuses and leaves the
    file untouched), recorded as a user event, and effective at the next engine
    invocation - 'evo next' re-evaluates any OPEN gate under the new mode, so a
    switch to full_auto releases a waiting gate and a switch back to gated makes
    the next gate wait for the user again."""
    import copy

    import econfig
    st = store.load_state()
    if not st.get("config_frozen"):
        raise SystemExit("[evo] config is not frozen yet - choose the supervision mode inside the "
                         "configure task instead")
    if not (args.note or "").strip():
        raise SystemExit("[evo] changing supervision needs --note with the user's reason (audit trail)")
    raw = eutil.read_json(store.config_path) or {}
    cur = str(((raw.get("policy") or {}).get("autonomy")) or "")
    if args.mode == cur:
        # R9 audit: the two-step record (intent event -> config write ->
        # completion event) has a window where the config landed but the
        # completion did not; the documented remedy is re-running the same
        # command, and this early return used to skip the closure forever -
        # the ledger then could never distinguish "effect pending" from
        # "effect landed, record torn". Close any dangling intent here.
        events = store.events()
        dangling = None
        for row in reversed(events):
            ev = str(row.get("event") or "")
            if ev == "autonomy_changed" and str(row.get("to") or "") == cur:
                break
            if ev == "autonomy_change_intent" and str(row.get("to") or "") == cur:
                dangling = row
                break
        if dangling is not None:
            store.event("user", "autonomy_changed", note=str(args.note),
                        to=cur, **{"from": str(dangling.get("from") or "")})
            print(f"supervision is already '{cur}'; the interrupted change record was closed "
                  "(intent had landed without its completion).")
            return 0
        print(f"supervision is already '{cur}' - nothing to change.")
        return 0
    cand = copy.deepcopy(raw)
    cand.setdefault("policy", {})["autonomy"] = args.mode
    expanded = copy.deepcopy(cand)
    econfig.apply_preset(expanded)
    errs = econfig.validate_config(expanded) + econfig.preset_conflicts(cand)
    if errs:
        raise SystemExit("[evo] refusing the switch - the resulting config would be invalid:\n  - "
                         + "\n  - ".join(errs))
    # R9 (external audit r6): audit trail FIRST, then the effect. A crash
    # between the two used to leave full_auto silently in force with no
    # autonomy_changed event - the mode auto-approved gates while the ledger
    # could not say who authorized it. With the intent event first, the worst
    # crash leaves an intent on record whose effect did not land (visible,
    # re-runnable), never an unexplained live control change.
    store.event("user", "autonomy_change_intent", note=args.note, to=args.mode, **{"from": cur})
    eutil.write_json_atomic(store.config_path, cand)
    store.event("user", "autonomy_changed", note=args.note, to=args.mode, **{"from": cur})
    meaning = {
        "full_auto": "after the already-required manual bootstrap sign-off, ordinary idea approvals, "
                     "workflow approvals and round continuation auto-approve; project-limit increases "
                     "stay manual, escalations follow on_stuck, and a blocked provision pass STOPS the run. "
                     "Instrumental, exploratory and kernel-copy (scaling follow-up / confirmatory) "
                     "gates ALWAYS wait for you",
        "auto": "ordinary idea approvals auto-approve (and round continuation while rounds_max > 0); "
                "heavy workflows and the infra review still wait for you. Instrumental, exploratory "
                "and kernel-copy (scaling follow-up / confirmatory) gates ALWAYS wait for you",
        "gated": "every gate now waits for your decision again",
    }[args.mode]
    print(f"supervision: {cur} -> {args.mode} ({meaning}).")
    # R7: honest tense - the switch takes effect at the NEXT engine
    # invocation (each invocation loads config once at startup).
    print("effective from the next 'evo' invocation onward.")
    open_gates = [x for x in st.get("gates", []) if x.get("status") == "open"]
    if open_gates:
        print(f"{len(open_gates)} open gate(s) will be re-evaluated under the new mode - run 'evo next'.")
    return 0


def cmd_doctor(store: estore.Store, args) -> int:
    problems, repairs = edoctor.diagnose(store, fix=args.fix)
    for p in problems:
        print(f"PROBLEM: {p}")
    for r in repairs:
        print(f"REPAIRED: {r}")
    if problems and not args.fix:
        print("'evo doctor --fix' applies any SAFE repairs it can (some problem classes are "
              "report-only and keep their own verbs); re-run 'evo doctor' afterwards to see "
              "what remains")
    elif problems and args.fix:
        print("re-run 'evo doctor' to confirm the repairs converged; remaining PROBLEM lines "
              "need the verbs named in their messages")
    # v11.1 P3: one line of measurement provenance - which noise floors are in
    # force and whose authority each one has (config | engine-observed).
    try:
        cfg, st = store.load_config(), store.load_state()
        import egraph as _egraph
        rows = []
        for c in _egraph.decision_cells(cfg):
            cid = str(c.get("id") or "")
            src = econfig.noise_floor_source(cfg, cid, st)
            if src != "none":
                rows.append(f"{cid}={econfig.noise_floor(cfg, cid, st):g}({src})")
        if rows:
            print("noise floors in force: " + ", ".join(rows))
    except Exception:  # noqa: BLE001 - informational line; problems already printed
        pass  # an unbootstrapped/broken config already surfaced as PROBLEM rows
    if not problems:
        print("doctor: clean")
    return 0 if not problems else 1


def cmd_render(store: estore.Store, args) -> int:
    import eartifact
    import edash
    import egraph
    g = store.load_graph()
    cfg = store.load_config()
    st = store.load_state()
    reg = store.load_artifacts()
    egraph.recompute_rollups(g, cfg)
    store.save_all(st, g, reg)
    egraph.render_views(store, g, cfg, st)
    eartifact.render_view(store, reg)
    edash.render(store, g, cfg, st, reg)
    print("views rendered: .evo/views/GRAPH.md, FRONTIER.md, ARTIFACTS.md, DASHBOARD.html")
    print("open .evo/views/DASHBOARD.html in a browser for the interactive DAG")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="evo", description="Model Evolution v10 engine")
    ap.add_argument("--repo", required=True, help="path to the evolved project repository")
    ap.add_argument("--session", default=None,
                    help="agent-session id for provenance (or env EVO_SESSION). Recorded on "
                         "submissions; under policy.critic_isolation=strict a release verdict "
                         "(tournament advance / red_team ACCEPT / challenge PROCEED / fidelity "
                         "FAITHFUL) must carry a session different from the authored work's")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="scaffold .evo in the repo")
    s.add_argument("--project-name", default=None)
    s.add_argument("--goal", default=None)
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("next", help="print THE current task card (deterministic)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_next)

    s = sub.add_parser("submit", help="validate a task's outputs and advance state")
    s.add_argument("--task", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_submit)

    s = sub.add_parser(
        "validate",
        help="read-only dry run: print the deficiencies submit would raise for this task's "
             "current output bytes - no attempt spent, no state written. This is the legal "
             "pre-submit check (never import engine modules to pre-validate). One disclosed "
             "exception to read-only: a formalizable theorize task executes your own "
             "TOY_CHECK.py exactly as submit would. A PASS is not an acceptance guarantee - "
             "transition-time postconditions still run only at submit.")
    s.add_argument("--task", required=True)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("decide", help="record a user decision on a gate")
    s.add_argument("--gate", required=True)
    s.add_argument("--approve", action="store_true")
    s.add_argument("--reject", action="store_true")
    s.add_argument("--note", default=None)
    s.add_argument("--retry-stage",
                   choices=["sketch", "pose", "theorize", "mature", "ablation_design",
                            "probe_design", "maintenance_design"], default=None,
                   help="on idea rejection: send the lane back to this stage instead of abandoning")
    s.set_defaults(fn=cmd_decide)

    s = sub.add_parser("status", help="dashboard")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("artifacts", help="list the shared-artifact registry")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_artifacts)

    s = sub.add_parser("run-smoke", help="engine executes the node's smoke plan")
    s.add_argument("--node", required=True)
    s.set_defaults(fn=cmd_run_smoke)

    s = sub.add_parser("run-rehearsal",
                       help="engine executes the node's tiny full-chain rehearsal (all stages + "
                            "eval on the real platform, consumer read-back proof)",
                       description="Run this when the engine presents a rehearsal task card (it "
                                   "does so before a node's first full-scale launch under "
                                   "project.rehearsal=full_chain, and again after any "
                                   "implementation re-seal). One tiny real pass over the ENTIRE "
                                   "workflow must prove every stage launches, every produced "
                                   "artifact is READ BACK by its consumer's real code, and the "
                                   "configured metrics come out. The engine owns exit codes, "
                                   "logs and the receipt; the receipt binds the implementation "
                                   "seal it proved.")
    s.add_argument("--node", required=True,
                   help="the node whose sealed implementation the tiny pass proves "
                        "(see 'evo status' / .evo/views/GRAPH.md for node ids)")
    s.set_defaults(fn=cmd_run_rehearsal)

    s = sub.add_parser("run-infra-canary", help="engine executes the open infra_drill task's project-defined canary")
    s.add_argument("--task", required=True)
    s.set_defaults(fn=cmd_run_infra_canary)

    s = sub.add_parser("run-update", help="update a registered workflow-stage run's status")
    s.add_argument("--run", required=True)
    s.add_argument("--status", required=True)
    s.add_argument("--metrics-file", default=None)
    s.add_argument("--ledger-file", default=None)
    s.add_argument("--note", default=None)
    s.add_argument("--failure-class", choices=["infrastructure", "implementation", "operator", "unknown"],
                   default=None)
    s.add_argument(
        "--repair-scope", choices=["evaluation", "workflow"], default=None,
        help="required for implementation failures: evaluation preserves completed workflow evidence; "
             "workflow invalidates and replays it")
    s.set_defaults(fn=cmd_run_update)

    s = sub.add_parser("run-bind", help="bind one prepared RUN to one external job idempotently")
    s.add_argument("--run", required=True)
    s.add_argument("--job", required=True)
    s.add_argument("--attempt-token", required=True)
    s.set_defaults(fn=cmd_run_bind)

    s = sub.add_parser("run-confirm-not-launched", help="resolve a launch_unknown intent after checking the platform")
    s.add_argument("--run", required=True)
    s.add_argument("--note", required=True)
    s.set_defaults(fn=cmd_run_confirm_not_launched)

    s = sub.add_parser("run-reconcile", help="attach late evidence to the same successful RUN")
    s.add_argument("--run", required=True)
    s.add_argument("--metrics-file", default=None)
    s.add_argument("--ledger-file", default=None)
    s.add_argument("--accept-missing-probe", action="store_true")
    s.add_argument("--accept-missing-evidence", action="store_true",
                   help="USER decision: the materials are permanently unavailable; close the "
                        "evidence obligation with a terminal disposition on record")
    s.add_argument("--note", default=None)
    s.set_defaults(fn=cmd_run_reconcile)

    s = sub.add_parser("hold", help="pause new authority-changing work in one scope")
    s.add_argument("--scope", required=True, help="project or round:R###|lane:L###|node:N###|run:RUN###")
    s.add_argument("--reason", required=True)
    s.set_defaults(fn=cmd_hold)

    s = sub.add_parser("resume", help="release one scoped hold")
    s.add_argument("--hold", required=True)
    s.add_argument("--note", required=True)
    s.set_defaults(fn=cmd_resume)

    s = sub.add_parser("recover-plan", help="render a deterministic impact plan and apply a scoped hold")
    s.add_argument(
        "--target", required=True,
        help="project or round:R###|lane:L###|node:N###|run:RUN###; boundary rules may require a narrower scope")
    s.add_argument("--boundary", required=True,
                   choices=["bootstrap", "lane", "spec", "implementation", "stage_evidence",
                            "evaluation", "conclusion", "frontier", "round"])
    s.add_argument("--reason", required=True)
    s.add_argument(
        "--repair-scope", choices=["evaluation", "workflow"], default=None,
        help="required for boundary=implementation; evaluation preserves completed workflow evidence")
    s.set_defaults(fn=cmd_recover_plan)

    s = sub.add_parser("recover-apply", help="apply an unchanged reviewed recovery plan")
    s.add_argument("--recovery", required=True)
    s.add_argument("--confirm", required=True, help="exact PLAN.json digest")
    s.set_defaults(fn=cmd_recover_apply)

    s = sub.add_parser("recover-status", help="list recovery cases")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_recover_status)

    s = sub.add_parser("recover-abort", help="terminate a recovery without restoring superseded authority")
    s.add_argument("--recovery", required=True)
    s.add_argument("--reason", required=True)
    s.add_argument("--abandon-node", action="store_true",
                   help="required after apply: abandon the partially repaired node honestly")
    s.set_defaults(fn=cmd_recover_abort)

    s = sub.add_parser("probe", help="mid-round: open a bounded diagnostic-probe lane for a user question")
    s.add_argument("--parent", required=True, help="the concluded node the question grows out of")
    s.add_argument("--question", required=True, help="the ONE question this probe answers (>= 20 chars)")
    s.add_argument("--name", default=None)
    s.set_defaults(fn=cmd_probe)

    s = sub.add_parser("maintain", help="mid-round: open a parity-contracted maintenance lane for a code defect")
    s.add_argument("--parent", required=True, help="the concluded node whose executable base this repairs")
    s.add_argument("--defect", required=True, help="what is mechanically broken (>= 20 chars)")
    s.add_argument("--name", default=None)
    s.set_defaults(fn=cmd_maintain)

    s = sub.add_parser("waive-repeat",
                       help="USER decision: release an approved repeat_measure whose physical "
                            "re-run is impossible; the single-run verdict stands, on record")
    s.add_argument("--node", required=True)
    s.add_argument("--note", required=True,
                   help=">= 20 chars: why the bought-back repeat cannot be executed")
    s.set_defaults(fn=cmd_waive_repeat)

    s = sub.add_parser("propose-abandon",
                       help="propose stopping a dead lane/node; the USER decides at a manual gate")
    s.add_argument("--lane", default=None)
    s.add_argument("--node", default=None)
    s.add_argument("--reason", required=True,
                   help=">= 30 chars: the mechanism that makes this direction dead")
    s.set_defaults(fn=cmd_propose_abandon)

    s = sub.add_parser("log", help="append a freeform note event")
    s.add_argument("--note", required=True)
    s.add_argument("--task", default=None)
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("revive", help="user decision: reopen a pruned/archived node's lineage")
    s.add_argument("--node", required=True)
    s.add_argument("--note", required=True)
    s.set_defaults(fn=cmd_revive)

    s = sub.add_parser("revise-infra",
                       help="user decision: propose adopting a corrected INFRA_FACTS "
                            "(.evo/profile/INFRA_FACTS_PROPOSED.json); approval re-arms the canary "
                            "before any new spend",
                       description="Use when evolution proved an approved infrastructure fact wrong "
                                   "(wrong slot count, wrong storage template, a dataset moved). "
                                   "Write the FULL corrected file to "
                                   ".evo/profile/INFRA_FACTS_PROPOSED.json, then run this verb; a "
                                   "user gate reviews the changed blocks. On approval the engine "
                                   "swaps the facts, archives the old file, and refuses new "
                                   "stage/eval launches until the integrated canary passes again "
                                   "against the revised facts.")
    s.add_argument("--note", required=True,
                   help=">= 40 chars: what was learned to be wrong and how it was discovered")
    s.set_defaults(fn=cmd_revise_infra)

    s = sub.add_parser("rebind-artifact",
                       help="user decision: re-freeze one node's consumed-artifact binding to the "
                            "artifact's current generation (after a legitimate producer revision)",
                       description="Use when a launch is refused with LAUNCH_ARTIFACT_GENERATION_DRIFT "
                                   "(or doctor reports ARTIFACT_BINDING_DRIFT): the producer "
                                   "legitimately re-generated an artifact this accepted node had "
                                   "frozen at plan time. Rebinding declares the NEW bytes as the "
                                   "intended input and re-freezes generation+digest. It refuses "
                                   "while the producer is still mid-revision or this node has "
                                   "live RUNs.")
    s.add_argument("--node", required=True, help="the consuming node whose binding moves")
    s.add_argument("--artifact", required=True, help="the AR### id to re-freeze")
    s.add_argument("--note", required=True,
                   help=">= 20 chars: WHY the new generation is the intended input "
                        "(part of the scientific record)")
    s.set_defaults(fn=cmd_rebind_artifact)

    s = sub.add_parser("autonomy", help="user decision: change the supervision mode mid-run")
    s.add_argument("mode", choices=["gated", "auto", "full_auto"])
    s.add_argument("--note", default="", help="why (recorded in the event trail)")
    s.set_defaults(fn=cmd_autonomy)

    s = sub.add_parser("doctor", help="cross-file consistency check")
    s.add_argument("--fix", action="store_true",
                   help="apply the safe repairs (quarantine a torn journal tail, retire duplicate "
                        "open cards, recompute rollups/views); everything else stays report-only")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("render", help="re-render graph/frontier/artifact views")
    s.set_defaults(fn=cmd_render)

    # --session is naturally typed AFTER the subcommand ('evo submit ...
    # --session S'), but argparse binds globals before it. parse_known_args
    # consumes every recognized option FIRST (so a literal "--session" used as
    # another option's VALUE is never touched - the naive argv scan ate it),
    # and only a genuinely unbound trailing --session is adopted here.
    args, extra = ap.parse_known_args()
    rest = list(extra)
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == "--session" and i + 1 < len(rest):
            args.session = rest[i + 1]
            del rest[i:i + 2]
            continue
        if tok.startswith("--session="):
            args.session = tok.split("=", 1)[1]
            del rest[i]
            continue
        i += 1
    if rest:
        ap.error("unrecognized arguments: " + " ".join(rest))
    store = estore.Store(Path(args.repo))
    # R7 external audit: one whole-invocation mutex. The state CAS alone let a
    # concurrent invocation overwrite agent-facing LAUNCH/CARD/BUNDLE files
    # BEFORE losing the CAS - the surviving process then printed the loser's
    # attempt token and the external job could never bind. Two invocations of
    # this single-operator CLI never legitimately interleave; the second one
    # fails fast and honestly instead of corrupting shared files. (init still
    # runs unlocked: it creates the .evo directory the lock lives in.)
    if args.cmd == "init" or not store.evo.exists():
        return args.fn(store, args)
    with eutil.exclusive_file_lock(
            store.evo / "invocation.lock",
            "[evo] another evo invocation is running in this repository; wait for it to "
            "finish and re-run this command (state was NOT touched)"):
        return args.fn(store, args)


if __name__ == "__main__":
    raise SystemExit(main())
