# TASK {{TASK_ID}} - sota_scan (role: SOTA librarian)

Project: {{PROJECT_NAME}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}} | Bundle: `{{BUNDLE_PATH}}`
Recency bar: year >= {{SOTA_YEAR}} | accepted venues: {{SOTA_VENUES}} | minimum entries: {{SOTA_MIN}}

## Why
Research mode means gains + novelty AGAINST THE CURRENT FIELD, not against this
repo's own history. This library pins down what "the field" concretely is: the
recent top-venue results on this task (same dataset and metric when they exist;
   at minimum a very close task). Every non-platform research-kernel candidate
   must bind the entries it intends to beat during the pre-winner tournament,
   on a named dimension, and every conclusion settles those
claims. An idea that cannot say whom it beats is not aiming at the frontier.

## Do
1. From PROJECT_PROFILE.md and the dossier, fix the task/dataset/metric terms.
   While reading, ALSO harvest measurement-noise facts: how many runs/seeds do
   these papers report (the field's convention), and what run-to-run spread or
   leaderboard neighbor gaps do they publish? Synthesize across MULTIPLE
   comparable works (same dataset+metric, model scale/regime near this
   project's - small models are noisier than large ones), take the MEDIAN of
   their reported spreads, and cite the sources: one paper's number must not
   set the floor alone (too tight lets noise pose as signal, too loose gets
   real gains labeled provisional). Update `evaluation_contract.noise_floors`
   per affected cell - or, if the bootstrap contract is already frozen, write
   the synthesis to `.evo/evidence/SOTA_NOISE.md` (a declared output of this
   task: per affected cell, the recommended floor, the per-source spreads it
   is the median of, and the citations). The engine preserves that file for
   the USER; adopting a change to a frozen floor is their deliberate
   reconfigure/restart decision, never yours. These numbers are what make
   single-run verdicts honest.
2. Search the accepted venues' recent proceedings (and arXiv for very fresh
   work) for the strongest results on:
   - the SAME dataset + metric (best; headline numbers directly comparable),
   - else the same task on a different benchmark,
   - else the nearest task (state the distance honestly in `task`).
   Use the retrieval ladder: if one source will not give the paper/numbers, try
   the next (venue site, arXiv, ar5iv, Semantic Scholar, paperswithcode,
   author page) before moving on.
3. Append one record per work to `.evo/evidence/SOTA.jsonl`:
```json
{"id": "S001", "title": "...", "venue": "NeurIPS", "year": 2026,
 "url": "https://...", "task": "how close: same-dataset|same-task|near-task + what it is",
 "dataset": "the benchmark, or 'none-shared'",
 "cell": "the configured target C# this result is evidence about",
 "comparability": "exact|protocol_adjusted|near_task",
 "method": "one line: the mechanism, not the acronym",
 "headline": {"metric": "...", "value": 0.0, "protocol": "split/setup the number comes from"},
 "relevance": ["B1"]}
```
4. Numbers must come from the papers/leaderboards you actually retrieved -
   fabricating a SOTA number corrupts every later comparison. If a paper hides
   its numbers, record what IS published and say so in `headline.protocol`.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
