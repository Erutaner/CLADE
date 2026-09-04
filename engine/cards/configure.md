# TASK {{TASK_ID}} - configure (role: operator)

Project: {{PROJECT_NAME}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
Everything downstream (verdicts, gates, budgets, workflow slots, the NOVELTY
REGIME itself) is computed from this config. A wrong metric direction here
corrupts every future comparison; a wrong mode makes the critics demand the
wrong thing for months.

## Do
1. Read `.evo/profile/PROJECT_DISCOVERY.{md,json}` first. The discovery pass
   already scanned supplied docs and relevant code and listed unresolved U#
   questions. Resolve those questions with the user, then open
   `.evo/config.json`. Never turn a provisional discovery default into a fact
   without making that choice visible.
2. Fill `project`: name, goal (one sentence, the user's actual objective), `code_root`,
   `primary_metric` (a display-only evaluation result key), `vcs` ("git" if the repo is a git working tree - node branches
   will then mirror the code-parent chain mechanically; else "copy"), and `docs`.
   **`docs` is the user's knowledge base** (platform guides, data docs, metric
   definitions; for LLM projects also serving/API docs). ASK THE USER for it -
   the infra scan that follows reads these paths, and infrastructure learned
   from docs+code beats infrastructure guessed from code alone. Every listed
   path must exist. Copy the discovered/user-confirmed paths; document scanning
   has already happened before this task.
3. Fill `metrics`: one entry per metric DEFINITION. Each needs
   `key` (e.g. `accuracy`; values are keyed separately per evaluation cell), `name`, `direction`
   (`max` or `min`), `definition` (the mathematical definition, precise enough
   that a re-implementation would match), and `source` (which command/file produces it).
   Ask the user if metric definitions are ambiguous - do not guess directions.
4. **First interview the user about success, in plain language. Do this before
   discussing methods or opening a round.** A benchmark name is not a decision
   rule. Ask until the following contract is explicit:

   - **Deliverable shape:** one checkpoint shared across all tasks, a common
     method with task-adapted checkpoints, or a portfolio/routing system? Map to
     `evaluation_contract.model_scope`: `single_checkpoint|task_adapted|portfolio`.
   - **Dataset/task topology:** enumerate datasets and exact splits/protocols as
     D# records, then scientific tasks as T# records. Do not assume one task per
     dataset: one dataset may support several tasks, and one task may be tested
     on several datasets. Every T# also declares how its own dataset/metric
     cells combine (`aggregation: all|majority|weighted_vote`) and a positive
     task `weight` used only if its G# group chooses weighted voting. This
     prevents a task with more reported metrics from receiving more votes by
     accident.
   - **Decision cells:** enumerate every meaningful dataset × task × metric
     combination as C#. Each has a unique `result_key` in metrics.json, even if
     two cells reuse the same metric definition. Ask which are `target`
     (something this model claims to improve), `guardrail` (must not become
     unacceptably worse), or `diagnostic` (reported but non-decisive), and ask
     which are required. Record practical `min_improvement` and
     `noninferiority_margin`, not merely “higher is better”. For each cell also
     make the absolute success question explicit: numeric `goal_threshold`
     (for example a dated SOTA or deployment acceptance bar) or `null` for
     progress-only, plus `goal_threshold_source`. Ask how many task groups must
     meet absolute goals (`decision.min_target_groups_goal_met`; zero only when
     no absolute threshold exists).
   - **Task groups and breadth:** group related tasks as G#. Ask how a group
     counts as improved (`all|majority|weighted_vote`), which groups are
     required, how many groups must improve, and whether a scoped specialist
     win is a legitimate result. This is the actual project success rule.
   - **Display only:** choose `evaluation_contract.display_cell`; copy that
     cell's result_key to `project.primary_metric`. Tell the user explicitly
     that it only keeps logs/plots compact and has no privileged verdict power.

   Never collapse the contract to an unapproved weighted sum. A node succeeds
   by its pre-registered claim scope: generalist, specialist, or efficiency;
   the engine reports per-cell wins, losses, uncertainty and guardrail status.
   `cell.required=true` means every model claim must include that target and it
   may not regress; `group.required=true` means that group must remain
   non-inferior. `decision.min_target_groups_improved` separately controls how
   many groups must actually improve. A `specialist` verdict is a valid scoped
   result but is explicitly not an overall-contract pass. Under
   `single_checkpoint`, regression on an out-of-scope target is still a
   `tradeoff`; under `task_adapted`/`portfolio`, the incumbent checkpoint or
   route may remain active for tasks outside the specialist scope.
   Relative node progress and absolute project attainment are reported
   separately: `improved` does not secretly mean “SOTA reached”.

   **When the user cannot specify part of the rule**, proceed but make the
   inference visible in `evaluation_contract.assumptions` as
   `{id:"U#", decision, basis, revisit_when}`:

   1. Metrics named in the stated goal become targets.
   2. Safety, cost, latency, memory, fairness, or deployment limits become
      guardrails; other routinely reported metrics become diagnostics.
   3. Within a task, default to equal-weight `weighted_vote` (at least one
      material win must outweigh losses; non-inferior cells abstain), then one
      group per user-visible deliverable with `majority` across tasks,
      `min_target_groups_improved=1`, and no regression on required targets or
      global guardrails. Allow specialist claims, but label them `specialist`,
      never “overall SOTA”. Record this default as U# rather than hiding it.
   4. Derive margins LITERATURE-FIRST: documented benchmark resolution, or the
      typical increment between successive published results on this
      benchmark (what step size the field itself treats as an advance). A
      user-relevant effect size overrides only when the user states one; when
      the user is UNSURE, propose the literature-derived value, record it as a
      U# assumption, and say plainly at the sign-off that the number is
      provisional - the bootstrap sign-off FREEZES it for the project's life.
      There is no post-freeze edit channel: if the later SOTA scan surfaces
      variance/margin norms that contradict it, report that in the scan
      summary for the USER; adopting it is a deliberate reconfigure/restart,
      never a silent move of a decision line. (In preplanned multi-seed
      projects the engine's observed-noise calibration overlays the frozen
      floor automatically once >= 2 seed sets exist - the one designed
      post-freeze correction.) All of this is PER CELL: each dataset/task/metric cell
      derives its own margin (and noise floor) from ITS OWN benchmark's
      literature - one project may mix a well-studied public benchmark with a
      private dataset that has no literature at all, and each cell resolves
      independently (literature / user-stated / provisional zero). If a
      field simply has no margin norms, a zero margin IS that field's own
      convention (any positive delta counts) - record the zero as DELIBERATE
      in its U# so the sign-off approves it knowingly. If no literature
      source exists either, use a provisional zero margin the same way. Do not request repeated training merely to obtain
      mean/std; optional uncertainty must come from a fixed evaluation artifact
      (analytic or prediction-bootstrap interval) and add zero training runs.
      ALSO record the field's own measurement noise per decision cell into
      `evaluation_contract.noise_floors` `{cell_id: width}`: published
      run-to-run/seed spread on this dataset+metric, or typical leaderboard
      neighbor gaps. Ask the user what the field's convention is (one run or
      many?). With a floor recorded, a bare-scalar result is compared as
      value+-floor (hiding an error bar stops paying), wins inside the noise
      are labeled provisional, and deficits inside it still count as
      noninferior. No source -> leave 0, record the gap as a U# assumption,
      and disclose it at the sign-off (frozen thereafter; preplanned
      projects self-calibrate the floor from measured seed spread).
   5. Never invent an absolute SOTA threshold. If the user has not supplied or
      approved a dated source, set `goal_threshold:null`, explain progress-only
      in `goal_threshold_source`, set the goal-group minimum accordingly, and
      record the open question as a U# for the user (adopting a later source
      is a deliberate reconfigure, not a silent edit).
   6. Never invent an absent dataset, task, split, or metric direction. If that
      fact cannot be inferred from supplied code/docs, ask again.

5. **Then interview operating policy (plain language, no JSON keys).**
   - **Q1 - who is this for (mode):** "Is the goal metric gains on a production
     model (borrowing good published methods is fine), or gains + genuine
     novelty for research?" -> `project.mode`: `engineering` | `research`.
     engineering: critics audit FIT and NON-TRIVIALITY; borrowing well-fitting
     literature is legitimate. research: ideas must differ from the nearest
     published work; every non-platform candidate must carry an
     irreducible/paradigm kernel, while a separate portfolio share explores
     subsystem/full-program scope. Platform lanes use a separate enablement
     contract rather than a model M/E claim. Theory remains optional and the
     SOTA library audits every non-platform research kernel.
     Research follow-up: "should the engine build a SOTA library of recent
     top-venue results on this task and bind new ideas to beat named entries?"
     -> `research.sota_enabled` (and check `sota_recent_year`/`sota_venues`).
     Then settle the three evidence policies from the discovery recommendation
     in plain language, before any automatic rounds can start:
     - **Training seeds:** explain that every train/finetune node records its
       seed. Recommend `record_only` (one run, no aggregation) unless full-run
       variability is part of the actual claim or known instability could
       reverse the decision and the repeat cost is acceptable. If the user
       approves `preplanned`, agree now on an exact run count >=2 and
       `mean|median`; every run remains visible and every seed will traverse the
       complete node workflow, not one selected stage. Do not infer repeats from a
       future `{mean,std,n}` result, and do not switch modes after seeing a good
       or bad node. Record process/domain evidence, claim relevance, field norm,
       cost, the user's decision, and a concrete revisit trigger in
       `evidence_policy.training_replication`.
     - **Ablation:** ask whether the engine may later propose a manually
       approved, one-run causal diagnostic when one component question would
       change the next DAG choice and cheap logs/eval cannot answer it. Map to
       `ablation.mode: off|targeted`; `targeted` has
       `max_costly_runs_per_node:1`. It does not schedule an ablation now or
       after every gain, never creates a sweep, and never crosses with seed
       repeats.
     - **Cheap probes/scaling:** ask how many eval-only interventions a node may
       afford and whether scaling is `off|reuse_only|budgeted|full`.
       `budgeted|full` is still an explicit after-signal descendant proposal,
       capped by `max_scaling_costly_arms`; it is not automatic. Ask the two
       plain questions that decide the mode - "does your goal have to hold
       across scales, or is one working scale enough?" and "could you actually
       afford the larger-scale training runs if a result looks promising?" -
       and let the USER's answers pick the mode; scaling is a per-field choice,
       not a default (many domains never need it).
   - **Q2 - budget (facts):** Confirm the discovery draft: "Across the whole
     evolution, what hard totals may we spend (for example GPU-hours, training
     tokens, API tokens or wall-clock minutes)? How many rounds, and how many
     stage jobs may run concurrently?" -> `resource_contract.limits` + `basis`
     + `on_exhaustion:"ask"`, `budgets.rounds_max`, and
     `infra.max_concurrent_stage_jobs`. Every stage/eval must cap at least one
     tracked unit. The scheduler reserves and cumulatively charges these totals;
     exhaustion creates a non-automatic user gate. The top-level config key
     `stage_budget_tolerance` (>= 1.0, default 1.0 = strict) exists as a
     validity band on declared stage/eval caps; it sits outside the bootstrap
     contract digest and changes affect future ingestions only. The in-engine ledger covers
     scheduler-controlled workflow stages and evaluations. The bootstrap
     integrated canary, smoke checks and the operating agent's own tool/provider charges are
     not independently meterable here: keep them tiny and constrain them with
     the platform/provider quota instead of pretending they were counted. The
     canary's real command retries are nevertheless capped by `max_attempts`.
   - **Q3 - temperament:** "Steady gains, a balanced mix, or innovation-first?"
     -> `policy.preset`:
     | preset | means |
     |---|---|
     | `steady` | full-program root every 6 rounds; moonshot after 6 flat rounds; exploit <=67%; structural/non-repair shares 34%; core-synthesis 0% |
     | `balanced` | root every 3 rounds; moonshot after 3 flat rounds; exploit <=50%; structural/non-repair shares 50%; core-synthesis 0% |
     | `frontier` | root every round; moonshot after 2 flat rounds; exploit <=25%; structural/non-repair shares 67%; core-synthesis >=25% when a round has >=3 idea lanes |
     The preset OWNS seven keys (`wildcat_every_rounds`,
     `stagnation_rounds`, `stagnation_moonshot_rounds`,
     `max_exploit_share`, `research_min_structural_scope_share`,
     `research_min_constructive_share`,
     `research_min_core_synthesis_share`): leave them out (the engine fills them) or keep them
     exactly equal to the preset's values. Hand-tuning any of them requires
     `preset: "custom"` - a named preset with divergent numbers is rejected.
   - **Q4 - supervision:** "Approve each step, only the big things, or automate
     ordinary gates within fixed bounds?" -> `policy.autonomy`: `gated` (user approves infra review,
     ideas, medium/heavy training), `auto` (ideas auto-approved; heavy training
     still gated), `full_auto` (automatically approves ordinary idea/workflow/
     round gates after bootstrap; requires `budgets.rounds_max >= 1`). The final
     bootstrap contract gate is mandatory in every mode: automation cannot
     approve its own success/resource rules. Even `full_auto` pauses (waits
     for the user) on an infrastructure-canary blocker, the design AND
     workflow gate of any instrumental node (targeted ablation, diagnostic
     probe, maintenance), a resource-limit increase, and an escalation under
     `on_stuck: "ask"`. A blocked PROVISION pass is different under
     `full_auto`: it STOPS the run (recorded as the terminal reason) rather
     than waiting - an unattended run cannot supply missing credentials/data,
     so silence is resolved as a stop, not treated as consent. Choose
     `gated`/`auto` if you want a blocked preparation to wait for you instead.
   - **Q5 - focus directions (optional):** "Any directions you personally want
     explored (e.g. 'try reinforcement learning on this task')?" ->
     `project.focus_directions`: `[{"id": "D1", "text": "..."}]`. The engine
     dedicates SOME lanes to them (and forces one if a direction is starved),
     but never more than `policy.focus_share_max` of a round's search bets -
     with exactly one stated exception: the single lane a starved direction
     forces rides outside the cap (bounded catch-up service is not
     domination). The user's interest guides the search, it must not bind it.
   - **Q6 - rehearsal:** "Before each new node's first FULL-SCALE run, should
     one tiny real pass over its ENTIRE workflow (all stages + eval, a few
     steps each) run on the real platform first - proving every stage
     launches, every produced artifact is READABLE BY ITS CONSUMER, and the
     metrics come out - so a wiring mistake costs a tiny job instead of the
     full training budget?" -> `project.rehearsal`: `full_chain` | `none`.
     Recommend `full_chain` on any remote or costly platform; `none` is an
     explicit user waiver (e.g. everything runs locally in minutes). NOTE:
     whether the project itself needed preparation was already decided at
     project_scan (readiness) - this question is about every future node.
   Mid-run changes stay this easy: the user says "make it more aggressive", you
   flip `policy.preset`, run doctor, and the next round obeys. Supervision has
   its own blessed channel: `evo autonomy gated|auto|full_auto --note "why"` -
   validated before writing, recorded in the event trail, and any OPEN gate is
   re-evaluated under the new mode at the next `evo next`. Switching to
   `full_auto` releases only gate kinds that mode is allowed to decide; protected
   user decisions above remain open. Switching back makes future automatic
   gates wait again. Never hand-edit `policy.autonomy`.
6. Review remaining `budgets` and `infra` only if the user asks; defaults are sane.
7. Do not touch other `.evo/` files.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
