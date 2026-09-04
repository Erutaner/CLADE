# TASK {{TASK_ID}} - provision (role: mechanic)

Project: {{PROJECT_NAME}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
The discovery scan recorded `needs_preparation`: the supplied project cannot
yet produce a first real end-to-end number here (missing data wiring, no
runnable evaluation, bugs, an infrastructure mismatch). No honest contract can
be frozen against guesses - so THIS pass, before configure, is authorized to
do CONSTRUCTIVE work until one tiny real train+eval pass produces a real
metric value. What you observe here (real metric keys, real data locations,
real landing paths, how jobs are actually submitted) is exactly what the
configure/infra steps will freeze next.

## Do
1. Work the scan's preparation worklist (in the bundle). You MAY: fetch or
   wire datasets the code never handled, write a minimal evaluation
   harness/adapter around the project's real model, repair bugs, and adapt
   entry points to this platform. You may NOT invent data or metrics: every
   dataset you wire and every metric you expose must be one the user named or
   the project already defines - anything you CHOOSE (which split, which
   metric definition, which evaluation slice) goes into `choices` for the
   user's explicit sign-off at the contract gate.
2. Prove readiness with the smallest slice that exercises the FULL path: data
   loading -> a tiny training step -> the evaluation command emitting >= 1
   real numeric metric. Capture every log under `.evo/profile/provision/`.
   Use the REAL platform the project will train on whenever the path exists;
   a local stand-in proves nothing about a remote project.
3. git mode: COMMIT your changes - the baseline seals from this tree later,
   and loose uncommitted edits have no provenance.
4. If you hit a wall the USER must remove (missing data grant, absent
   checkpoint, dead endpoint, no quota): STOP and report typed blockers.
   Each blocker names what is missing, what it blocks, and the concrete ask.
   A gate relays them verbatim; after the user supplies the items you get a
   fresh cycle with their note in the bundle.
5. Write two outputs:
   - `.evo/profile/PROVISION.md`: sections `## What was run`,
     `## Work performed`, `## Choices` (each scientific decision you made and
     why - the user signs these off at the contract gate; `NONE-MADE` plus a
     one-line justification when empty), `## Blockers` (`NONE-FOUND` plus a
     one-line justification when empty), `## Verdict`.
   - `.evo/profile/PROVISION.json`:
```json
{"status": "ready | blocked",
 "work": [{"what": "the gap or failure addressed", "file": "path/touched.py",
            "evidence": ".evo/profile/provision/trace.log"}],
 "choices": [{"decision": "used validation split of X as the eval slice",
               "why": "no test labels are available locally"}],
 "no_work_reason": "only when work is empty and status=ready",
 "proof": {"logs": [".evo/profile/provision/micro_train.log", "..."],
            "observed_metrics": {"accuracy": 0.31},
            "metric_basis": "which draft metric this number corresponds to and how it was produced",
            "note": "what the micro end-to-end pass demonstrated"},
 "blockers": [{"missing": "read access to table X", "needed_for": "the finetune stage",
                "ask": "grant the runtime read permission on <uri>"}]}
```
Honesty: configure freezes the contract against your observed facts, the
infra scan re-reads them, and the real integrated canary re-executes this
path once more before any science - a preparation claim that lies dies within
two tasks, with the lie on record. `blocked` is a legitimate, valuable
outcome; vague blockers are not.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
