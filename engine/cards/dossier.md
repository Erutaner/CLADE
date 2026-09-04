# TASK {{TASK_ID}} - dossier (role: analyst)

Project: {{PROJECT_NAME}} - goal: {{PROJECT_GOAL}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
This is the problem's scientific X-ray. Ideation quality is bounded by this file:
sketches must attack bottlenecks named here, and comparability is defined here.
Write it as a scientist, not a summarizer.

## Do
Write `.evo/profile/PROBLEM_DOSSIER.md` with these sections (exact headings):

1. `## Computational essence` - strip away the implementation: what function must be
   computed for this task to be solved well? What information in the input is
   sufficient for the target? Where does the current formulation force information
   loss (pooling, truncation, discretization, i.i.d. assumptions, factorization)?
   Where are the losses and target C# cells in the evaluation contract
   misaligned? {{PRIMARY_METRIC}} is only the display trace.
2. `## Bottleneck hypotheses` - ranked list of at least 3, `- B1: <one-line hypothesis> | evidence: <observation, file, or measurement>`.
   Each B# must be a falsifiable claim about WHY performance is capped
   (e.g. "the objective optimizes token-level likelihood while the metric rewards
   sequence-level ordering"), not a wish ("model could be bigger"). Categories to
   consider: target/objective misalignment, representation collapse, training signal
   sparsity, inference-time approximation, data regime, credit assignment, capacity
   misallocation, system decomposition.
3. `## Invariants` - `- V1: ...` at least 2 things NO idea may change: metric
   mathematical definitions, eval split/protocol, data usage contracts,
   anything the user fixed.
4. `## Forbidden shallow moves` - `- F1: ...` at least 5 concrete moves that are
   banned as node-level ideas for THIS project (hyperparameter/LR/schedule tuning,
   loss reweighting, generic "add attention/dropout", metric-implementation tricks,
   decorative ensembling...). Be specific to this project's temptations.
5. `## Diagnostic discriminators` - this dossier is deliberately written
   before any candidate program is synthesized or candidate-specific prior-art
   audit begins. For every bottleneck write one line:
   `- B#: falsifier: <observation that would kill it> | distinguish: <measurement
   that separates it from the competing B# hypotheses>`. Do not name papers,
   architectures, candidate kernels/operators, evidence-card ids or URLs. The
   output is a model of the problem, not a post-hoc justification for a
   candidate.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
