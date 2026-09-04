# TASK {{TASK_ID}} - fidelity (role: implementation auditor)

Node: {{NODE}} | workdir: {{WORKDIR}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}}
Bundle: `{{BUNDLE_PATH}}`

## Why
Complex ideas invite lazy builds: the harder the mechanism, the stronger the
pull to implement something simpler and let the idea doc describe a fiction.
If that node then regresses, the graph learns a LIE - the mechanism was never
tried. You are an auditor, not the builder: your job is to verify, claim by
claim, that the CODE implements the APPROVED IDEA - or to force a fix before
any compute is spent. This report is sealed upstream of run evidence and bound
to the exact implementation seal; it cannot certify a later code revision.

## Do
1. Read the idea doc's Mechanism/Implementation sketch and the spec. List the
   mechanism's load-bearing claims (the parts whose absence would falsify
   "we implemented the idea"): new objective terms, new heads/modules, staged
   flows, reweighting logic, decoding changes...
2. For EACH claim, find the code that realizes it and copy a literal snippet.
   Read the real files - the engine string-checks every snippet against the
   file you name. Do not quote the build report; quote the code.
3. If the code does NOT realize a claim, do not mutate sealed source inside the
   audit. Return the node to implementation repair (scope: make the
   implementation match the idea—nothing else). The builder submits a new
   `implementation_revision`, reruns smoke, and only then is this audit repeated;
   earlier run evidence is superseded rather than mixed across revisions. A
   justified design deviation belongs in the build report's Deviations section,
   not silently in the diff.
4. Write `.evo/nodes/{{NODE}}/FIDELITY.md`:
   - a line `FIDELITY: FAITHFUL` (a DEVIATES report is auto-rejected: fix, then re-audit)
   - `## Claim map` - enough rows to cover every approved KC# and every
     kernel-referenced OP#. Each claim text explicitly names both ids:
     `- OP# / KC# <operator-and-kernel claim> -> <relative/path.py> :: CODE: <literal snippet from that file>`
     (one row can be sufficient for a single-file/single-kernel innovation;
     snippets >=3 tokens and copied exactly)
   - `## Omissions and simplifications` - every place the implementation is a
     simplified/partial version of the idea and why that is acceptable (or
     'NONE-FOUND' after a real diff of idea vs code)
   - `## Audit verdict` - what you checked, what almost failed

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
