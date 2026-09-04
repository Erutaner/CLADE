# TASK {{TASK_ID}} - implement (role: builder)

Node: {{NODE}} | workdir: {{WORKDIR}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
Faithful implementation of THIS node's mechanism, nothing else. Scope discipline
is what keeps the graph interpretable: if the node fails, we must know the
mechanism failed - not some drive-by refactor.

## Do
1. Create the workarea (vcs mode: {{VCS_MODE}}):
   - **git mode**: the graph's code-inheritance chain is mirrored in git. Create
     this node's branch from the code parent's recorded commit and mount it as a
     worktree at the workdir, then commit your changes on it:
     ```
     git branch {{BRANCH}} {{BASE_REF}}
     git worktree add "{{WORKDIR}}" {{BRANCH}}
     # ...implement, then commit on that branch...
     ```
     The validator checks: branch exists, the workdir has it checked out, and it
     descends from the code parent's commit. (Hybrids branch from the code parent
     only; the other parents contribute mechanisms, not history. You may
     cherry-pick/merge from them when it genuinely helps - ancestry from the code
     parent must still hold.)
   - **copy mode**: copy the code parent's workdir to the spec's `workdir` path.
2. Implement exactly the idea's mechanism (read the idea doc in your bundle).
   - FORBIDDEN: combining mechanisms from other graph nodes "while you're at it" -
     that combination is a hybrid node and must go through its own lane.
   - FORBIDDEN: silent changes to metric code, eval protocol, or data contracts
     (dossier V#). If the idea requires an output-space change, implement its
     format-only metric adapter now as part of this sealed implementation; the
     later metric-bridge task only audits it against baseline evidence.
   - Tweaks (config defaults, minor stabilizations) are allowed only in service of
     making the mechanism run, and must be listed under Deviations.
   - If `experiment_purpose={{EXPERIMENT_PURPOSE}}` is
     `targeted_ablation`, change only the registered factor. Do not add a
     stabilizing tweak, refactor, fresh control implementation or second
     intervention; the dedicated controlled-change audit follows smoke.
3. Self-test as you go (unit-level; the engine runs the formal smoke next).
   If `NODE_SPEC.json` contains `probe_execution`, implement that evidence path
   as part of the node, not as prose added during evaluation:
   - `same_run`: the declared producer stage (or standard evaluation) writes the
     exact runtime JSON, including every `required_fields` key as a number;
   - `existing_artifact`: read and preserve the frozen source; add no producer;
   - `eval_intervention`: implement only the declared fixed-artifact eval command;
     it must not train or update the model.
   The smoke path must exercise the same field-writing code and produce the
   separate `smoke_artifact`.
4. Write `.evo/nodes/{{NODE}}/BUILD_REPORT.md` with sections:
   - `## Mechanism to code map` - map every load-bearing forward operator and
     name the approved kernels it realizes, using the exact syntax
     `- OP# [KC#, KC#] -> <relative/path/to/file.py>`. Repeat an OP# when it spans
     files. Every OP# referenced by a KC# and every approved KC# must be covered;
     this preserves the complete program rather than merely finding one file
     that resembles novelty prose. Diagnostics without a kernel use a
     substantive diagnostic-to-file row instead.
   - `## Deviations` - every place the implementation differs from the idea doc,
     and why ("none" is a valid entry only if literally true). The fidelity
     auditor reads this section.
   - `## Artifact wiring` - REQUIRED whenever the spec declares stage
     `consumes` or `produces`: one row per declared input and output binding
     the contract to the exact code, checked literally against the files:
     `READS: <AR###|stage:<name>> -> <file.py> :: CODE: <literal load snippet>`
     `WRITES: <exact produces uri> -> <file.py> :: CODE: <literal save snippet>`
     The bundle's "How recent nodes wired their artifact I/O" block shows the
     working rows from prior nodes - start from those, do not re-derive the
     platform's load/save ritual from scratch.
   - `## Probe instrumentation` when `probe_execution` exists:
     - same-run/eval intervention: one exact
       `PROBE_ARTIFACT: <probe_execution.artifact>` line, then one row per field:
       `PROBE_FIELD: <field> -> <file.py> :: CODE: <literal snippet that records it>`;
     - existing artifact: one exact `PROBE_SOURCE: <path>` line and explain how
       it is consumed without new training.
   - `## Metric bridge adapter` when the approved idea has
     `metric_bridge_needed=true`: exactly one
     `BRIDGE_ADAPTER: <file.py> :: CODE: <literal adapter snippet>` row. The
     adapter may translate output format only; it must not change metric math.
   - `## Repair scope` when the card identifies an evaluation-only repair:
     - `REPAIR_SCOPE: evaluation` to preserve completed workflow evidence, one
       exact `CHANGED_FILE: <workdir-relative path>` line for every manifest
       change, and one `WORKFLOW_REUSE_ARGUMENT: <at least 80 characters>` line
       explaining why those changes cannot affect prior stage artifacts; or
     - `REPAIR_SCOPE: workflow` when the real fix touches shared model,
       preprocessing, training, stage, or other workflow-authoritative code.
       This is a safe one-way widening and causes the repeat-spend gate to name
       the whole workflow. Never use prose to waive a protected-file change.

On successful submission the engine builds
`IMPLEMENTATION_MANIFEST.json` over the pre-existing execution closure and
seals it together with `BUILD_REPORT.md` and the exact real code files resolved
from `## Mechanism to code map` and `## Probe instrumentation`. In Git mode,
commit every tracked/staged implementation or configuration byte and leave no
untracked execution source; the reviewed commit must remain checked out and
clean. Spec/RUN-declared mutable metrics, ledgers, probes, and produced-artifact
landing paths are runtime outputs rather than implementation bytes. In every
mode, mutating any other manifest file or adding a new source after
approval is rejected until this task creates an explicit new revision.

The accepted submission advances `implementation_revision`. Its active
content-addressed seal—not a mutable workarea label—is the code identity
inherited by later execution. Active seals verify current working bytes and
active upstreams; superseded snapshots are history, not authority. A workflow
repair supersedes prior stage/eval evidence and restarts the workflow. A
validated evaluation-only repair instead preserves completed stage evidence
under an engine-sealed workflow-reuse receipt and reruns only evaluation; the
new eval RUN binds the new implementation. Results are never silently mixed
across revisions.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
