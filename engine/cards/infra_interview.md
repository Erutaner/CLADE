# TASK {{TASK_ID}} - infra_interview (role: interviewer)

Project: {{PROJECT_NAME}} | Attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}} | Bundle: `{{BUNDLE_PATH}}`

## Why
The infra scan produced facts; facts from two sources (docs, code) disagree in
every real project, and some questions neither source answers. This task turns
those gaps into an explicit review the USER decides on - once, up front - instead
of the agent guessing mid-run with an expensive stage job on the line.

## Do
Diff the knowledge base against the code paths you actually read, then write
`.evo/profile/INFRA_REVIEW.md` with EXACTLY these sections:

### Contradictions
Items `- C1: <title>` each followed by lines `docs say: ... [src: docs-path]` and
`code says: ... [src: repo-path]` and `resolution: <what INFRA_FACTS records and why>`.
If after a real diff nothing conflicts, write the literal token `NONE-FOUND` plus
one sentence on what you compared.

### Unknowns
Items `- U1: <question the user should answer>` - things neither docs nor code
decide (e.g. "is the eval split frozen?", "may we submit to the second queue?").
`NONE-FOUND` allowed with justification. For each unknown state the assumption
you are proceeding under.

### Resolutions
For every C#/U#: the concrete decision now encoded in INFRA_FACTS.json, one line each.

### Runtime services
Actively LOOK for model-runtime surfaces in the docs and the repo - LLM
serving stacks, vendor/OpenAI-compatible APIs, vector stores, KG/SPARQL
endpoints, execution sandboxes, simulators - and list what you found as
`- <surface>: <where it is documented/used>` items. These feed the facts'
`llm` and `services` blocks, and experiments will bind `requires_llm` /
`requires_services` to them later; a surface missed here is an endpoint some
run discovers is unrecorded mid-flight. Write the literal token `NONE-FOUND`
only after actually looking.

### Evaluation contract confirmation
Write the success rule in language the user can approve, not merely a metric
inventory. State the configured `model_scope`; enumerate every C# with its
dataset/task, result key, target/guardrail/diagnostic role, required flag,
practical margins and numeric absolute goal or progress-only status. State
explicitly how absolute goals relate to relative progress (the validator
checks that this section contrasts the two - use both words). Then name
every T# and G# aggregation, the minimum groups that must improve / meet goals,
and whether specialist results are allowed. List each evaluation-contract U#
assumption with its revisit trigger, or the literal token `NONE-DECLARED`.
Quote where the project produces/defines the results and protocol with a
`[src: path]` tag. Name {{PRIMARY_METRIC}} explicitly as the display-only
result. If code cannot emit a configured result key, or docs imply a different
role/direction/protocol, that is a contradiction - list it above. Do not demote
other targets to “secondary”: the approved contract decides success.

In the same section, state the complete project-wide resource envelope (every
unit and total from `resource_contract.limits`) and its user-approved basis.
Explain that stage/eval caps are charged cumulatively and exceeding a total
requires another non-automatic user decision.

Also state the approved **training-seed policy** by name: `record_only` means
one recorded seed and no full retraining repeats; `preplanned` names the exact
run count and aggregation fixed before evolution, with every seed traversing
every workflow stage. State the **ablation allowance**
by number: `evidence_policy.ablation.budget_multiple`, how much of a winning
node's own cost the engine may spend settling that node's mechanism (0 = never;
the engine opens the ablation itself after a program-level win in research mode; inside the
allowance its gates follow the autonomy policy, above it the user decides).
Now that the machines are known, settle the two money facts that depend on
them and write both to `.evo/config.json` with `evo amend --path
.evo/config.json --from <copy> --reason ...` (they are notebook facts, outside
the signed contract, changeable any time):
- **devices**: "How many accelerators may our jobs hold at once on this
  machine?" -> `resource_contract.max_devices` (an integer; leave null when a
  scheduler allocates). Agents then pick whichever devices are free under that
  number at each launch - never particular cards.
- **node ceiling**: "The most ONE experiment may spend, per unit?" ->
  `resource_contract.node_ceiling` + `node_ceiling_source` (`user`) +
  `node_ceiling_basis`. If the user cannot name it, propose one from the
  hardware you just recorded and the field's usual cost for this scale (two
  GPUs do not pretrain a 100B model; a 1B-parameter finetune is usually N
  GPU-hours in this literature), record it as `estimated` with that basis,
  and say it is changeable. A declared cap or the agent's own estimate above
  the ceiling puts the workflow gate in front of the user even under full_auto.
State both in this section (the numbers, or that the user chose not to set
them). Make clear that neither policy is inferred from
later results and that an ablation never crosses with the seed protocol.

A user gate follows this task: the user approves the review or rejects it with a
note (which reopens the infra scan). Write for that reader.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
