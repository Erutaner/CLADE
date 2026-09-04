# TASK {{TASK_ID}} - evidence (role: scout)

Round: {{ROUND}} | attempt {{ATTEMPT}}/{{MAX_ATTEMPTS}} | pool before this task: {{PRIOR_COUNT}} records
Bundle: `{{BUNDLE_PATH}}`

## Why
Ideas in this system must anchor to retrieved literature (the evidence pincer).
This task keeps the evidence pool current and pointed at this round's bottlenecks.
The modern stack is wide: pretraining/post-training of open models, inference-time
methods (prompting, decoding, memory, retrieval), API-composition and agent
designs are all in scope when a bottleneck points there - search for the
MECHANISM family, not only the home domain.

## Do
1. Read this round's PORTFOLIO.json and the dossier bottlenecks.
2. Derive search queries from METHOD/OBJECTIVE terms, not only domain terms:
   for each targeted bottleneck B#, ask "what families of mechanisms attack this
   class of problem?" and search for those families across neighboring fields too.
   Use your web/search tools. If you have no retrieval capability at all, stop and
   tell the user instead of inventing records.
3. Append new records to `.evo/evidence/EVIDENCE.jsonl` (one JSON object per line,
   continue E### numbering from the existing pool, never renumber old records):
```json
{"id": "E0XX", "title": "...", "year": 2025, "venue": "...", "url": "https://...",
 "source": "arxiv|openreview|acl|...", "relevance": ["B1"], "status": "candidate",
 "access": "full (default; omit) | abstract | unavailable",
 "retrieval_attempts": ["only when access != full: >= 2 distinct sources actually tried"]}
```
4. Prioritize recent work (config sets the recency bar) but include the
   load-bearing classics. Dedup against existing titles. The records you ADD this
   round are checked for recency on their own - restocking classics does not
   count as a refresh. Fabricating records instead of retrieving them corrupts
   every downstream idea; if retrieval fails, say so.
5. **Retrieval ladder**: a promising hit you cannot immediately open is still a
   record - keep it, mark `access`, list the attempts (arxiv/ar5iv/Semantic
   Scholar/OpenReview/venue page/author page/github). Dropping a first-choice
   paper because one fetch failed loses exactly the papers worth reading; the
   deep_read task will climb the ladder again with more patience.
6. **Coverage duty**: EVERY bottleneck targeted by this round's portfolio must
   have its own supply in the pool (config sets per-bottleneck minimums, incl.
   fresh records). A healthy pool average must not hide a lane whose bottleneck
   got zero records - retrieve per bottleneck, and for behavior-shaped lanes
   (hybrid bridging, platform building) search for that BEHAVIOR's literature
   (fusion/merging/alignment...), not only the domain's.
7. **Quotas (ALL validator-enforced, not just one)**: the pool must reach
   >= {{TOTAL_MIN}} records overall (it holds {{PRIOR_COUNT}} now); every
   bottleneck targeted by this round's portfolio needs >= {{PER_B_MIN}} records
   tagged for it in `relevance` (with recency rules per config); and when the
   pool already had records, this refresh must ADD >= {{MIN_NEW}} new ones.
   On an empty or thin pool the real work is the TOTAL and per-bottleneck
   floors - budget your retrieval for those, not for the refresh increment.

## Output contract
{{OUTPUTS}}

## Submit
{{SUBMIT_CMD}}
