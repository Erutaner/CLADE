# TASK {{TASK_ID}} - infra (role: infrastructure scout)

Project: {{PROJECT_NAME}} | Attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}} | Bundle: `{{BUNDLE_PATH}}`

## Why
Evolution dies on infrastructure mistakes, not on bad ideas: checkpoints silently
overwritten because two runs shared a path, jobs submitted with the wrong quota,
metrics read from the wrong platform. Before any science happens, you must LEARN
this project's infrastructure - from the user's knowledge base (config
`project.docs`) AND the code - and distill it into machine-readable facts the
engine will enforce mechanically. These sourced facts configure the later
canary; they are not execution proof. After the user's sign-off, one
project-defined canary will exercise the real integrated path.

## Do
1. Read every doc listed in `project.docs` (in the bundle inputs) and the launch/
   training/eval entry points of the repo. If `project.docs` is empty, mine the
   repo alone - and flag the gap in the interview that follows this task.
2. Write `.evo/profile/INFRA_PROFILE.md` (prose, for humans and later tasks) with
   sections: `Where things run`, `How training is submitted and watched`,
   `Data access`, `Artifact and checkpoint conventions`, `Known constraints`.
   Every claim carries a `[src: path]` tag into a docs file or repo file (>= 6 tags).
3. Write the facts file (second output) as JSON:
```json
{
  "workspace":     {"src": ["..."], "OPTIONAL free-form notes": "agent_runs_on / code_lives_at"},
  "compute":       {"kind": "e.g. ai-hub / slurm / local-gpu", "submit_pattern": "the command shape",
                    "status_cmd": "...", "logs_cmd": "...", "max_concurrent_stage_jobs": 1,
                    "src": ["..."]},
  "data":          {"kind": "e.g. odps / s3 / local",
                    "datasets": [{"name": "...", "uri": "...", "role": "pretrain|finetune|validation|..."}],
                    "src": ["..."]},
  "artifact_store": {"kind": "e.g. oss / s3 / dir", "uri_template": "...{run_id}.../checkpoint.zip",
                    "collision_rule": "what happens if two runs share a path", "src": ["..."]},
  "evaluation":    {"how": "...", "primary_metric_key": "<display-only result key>",
                    "result_keys": ["every evaluation-cell result_key"], "src": ["..."]},
  "llm":           {"OPTIONAL - declaring the block registers the 'llm' service": "",
                    "src": ["..."], "kind/invoke_pattern/budget": "optional notes"},
  "services":      [{"OPTIONAL - other runtime services experiments lean on": "",
                    "name": "kg-endpoint", "pinning": "live|recorded",
                    "src": ["..."], "kind/invoke_pattern": "optional notes"}]
}
```
Rules:
- `uri_template` MUST contain the literal `{run_id}` placeholder - the unique
  per-run segment. The engine later rejects any producing stage whose output URI
  collides with an existing artifact; get the convention right here.
- `max_concurrent_stage_jobs` is the platform's REAL quota for top-level
  workflow jobs (queue slots/accelerators). Internal candidates remain inside
  their stage job. The scheduler pipelines up to this number. Do not guess high.
- `evaluation.result_keys` must exactly cover the configured C# cells. This is
  the upfront check that one eval invocation can report the full decision
  vector; `primary_metric_key` is retained only as the dashboard display key.
- The `llm` block is optional but strongly recommended when the project touches
  model serving, APIs, or inference-time experiments - `inference`/`api`-class
  nodes will rely on it.
- The `services` registry records every OTHER runtime dependency (a KG/SPARQL
  endpoint for KGQA, a vector store for RAG, an execution sandbox, a simulator).
  Specs later bind to these names via `requires_services`, and the integrated
  canary must call each declared service once - the Virtuoso-was-down failure class dies
  in bootstrap, not in round 3.
- Every block's `src` lists the doc/repo paths the facts came from. If docs and
  code disagree, record what the CODE does here and raise the contradiction in
  the interview task (next).

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
