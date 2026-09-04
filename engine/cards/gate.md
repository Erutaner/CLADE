# GATE {{GATE_ID}} - {{GATE_KIND}} (user decision required)

Subject: {{SUBJECT}}

{{SUMMARY}}

## Report for the user (engine-generated)
{{REPORT}}

## What to do (agent)
1. RELAY the report block above to the user VERBATIM - translate faithfully if
   they speak another language, but do not summarize it away. stdout is your
   API; this report is the user's window into the run. Add pointers to the
   referenced files so they can inspect the idea/spec/failure themselves.
2. Relay their decision:
   ```
   python "<engine>/evo.py" --repo "{{REPO}}" decide --gate {{GATE_ID}} --approve|--reject [--note "..."]
   ```
   - on an IDEA_APPROVAL gate a rejection may add `--retry-stage`, which REWINDS
     the lane for another draft instead of abandoning it. The legal stage
     depends on what the lane is: candidate or exploratory -> `sketch|mature` (or `theorize`,
     or `pose` for a derivational claim, when a non-theory-derived winner
     already precommitted a theory claim); targeted ablation ->
     `ablation_design`; diagnostic probe -> `probe_design`; maintenance ->
     `maintenance_design`. A stage this lane does not have is refused and the
     gate stays open, so nothing is lost by asking. Tell the user this option
     exists: for an instrumental lane the rewind costs no budget, while
     re-opening a fresh one spends the round's only slot. Pass their reasons
     with `--note`; the note is routed into the redraft task.
   - escalation gates: approve = retry with reset counters (this is the rewind
     here); reject = abandon the stuck lane/node/task. `--retry-stage` does not
     apply to this kind and is refused.
   - abandon_request gates: the agent proposed STOPPING a direction it judges
     dead. Approve = deliberate stop, recorded as a decision with the stated
     reason (not a failure); reject = the work continues. Relay the agent's
     reason verbatim - the user is being asked to discard admitted work.
3. Then run `next` again.

Do NOT decide user gates yourself. If the user is unreachable and the policy says
gated, the loop pauses here by design.
