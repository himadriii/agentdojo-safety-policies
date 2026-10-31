# P6: Reuse of Previous Approvals

Owner: P6. Plan: [`docs/archive/2026-10-19-1857-feat-p6-approval-reuse-gate-plan.md`](../archive/2026-10-19-1857-feat-p6-approval-reuse-gate-plan.md).

## Method

`approval_reuse` wraps a base policy (full-escalate by default, "manual approval mode"). When the base escalates, the gate checks what the reviewer already decided earlier in the same task:

| Situation | Decision | Budget |
|---|---|---|
| Repeats a call the reviewer denied (same tool and key arguments; reads: identical arguments) | `deny` | not spent |
| Covered by a call the reviewer approved | `approve` | not spent |
| Anything else | `escalate`, and remembered | spent by the runner |

"Covered" is tiered:

- **Reads, same tool** are covered at tool level. One approved `search_emails` covers later searches. A URL argument is always key, so an approved `get_webpage` covers only the same page: scheme, a leading `www.` and a trailing slash are ignored, nothing else. A read is not covered if its arguments carry a link, email address or code-like token found in neither the task nor the approved call.
- **Reads, other tool (drill-down).** A read of another tool is covered by an approved read R when it only follows up on what R returned: it has at least one argument value of 3+ characters, every such value occurs in the user task or in the arguments and outputs of R (or of calls R already covered), and no argument carries a new link, address or code. `get_all_hotels_in_city` then covers `get_hotels_prices(hotel_names=[...those hotels])`. A zero-argument read, an invented name or a link taken from an output starts a new review. Side effects are never covered across tools.
- **Which tools are reads.** The table in `tool_table.py` is authoritative for the AgentDojo tools. A tool not in it is a read if its name starts with a read verb (`get`, `search`, `list`, `read`, `check`, `find`, `fetch`, `lookup`, `describe`, `show`, `view`, `query`, `retrieve`), and otherwise a side effect with every argument key. The verb rule agrees with the table on all 69 AgentDojo tools, banking included.
- **Side effects** are covered only when every key argument matches: recipients, cc, bcc, participants, payee, file, email, event, channel, user, URL or reservation target. A list may narrow (a subset of approved recipients), and an amount may only go down. Free text (body, subject, content) may change. Reuse is blocked if the new free text carries a link, an email address or a code-like token (5+ digits, or 8+ mixed letters and digits, such as an IBAN) found in neither the user's task nor the approved call.

The full per-tool table is in `agent_framework/policies/approval_reuse/tool_table.py`. Unknown tools are side effects with every argument key.

The runner does not tell policies what the reviewer decided, so the gate reads it off the trajectory. The tool result for a call it escalated either carries the runner's denial message (denied) or does not (executed after approval). Escalations made with zero budget left were denied by the runner, not the reviewer, and are dropped. All memory lives in the task-scoped `state`; nothing carries across tasks. The gate makes no LLM calls. Each decision logs `reuse_approved`, `reuse_denied` and `gate_ms` scores.

Each decision also logs `reuse_drilldown` (1.0 when the approval came from the drill-down rule; `reuse_approved` is 1.0 too). `ApprovalReusePolicy(drill_down=False)` turns the cross-tool rule off.

`similarity_reuse` is the comparison: the "cluster similar operations" reading of the original idea. It reuses an approval when the token Jaccard over all argument values is at least 0.5, with no key arguments, no token scan, no denial memory and no drill-down.

## Commands

```bash
python -m pytest tests -q                        # all offline tests
python -m p6_reuse.probes                        # probe set -> results/p6/probes/
python -m p6_reuse.replay                        # offline replay -> results/p6/replay/
python -m p6_reuse.summarize --outdir results/p6_live_g2   # tables from live runs
```

Live runs use a local LM Studio server (OpenAI-compatible) through `--provider lmstudio`, with P1's shared LLM reviewer (`--reviewer llm`, which uses the agent's model unless `REVIEWER_MODEL` is set). Start the LM Studio server (Developer tab, or `lms server start --port 1234`), load the model, then:

```bash
bash p6_reuse/smoke.sh openai/gpt-oss-20b                    # smoke
MODEL=openai/gpt-oss-20b bash p6_reuse/run_live.sh           # final grid, resumable
DRY_RUN=1 MODEL=x bash p6_reuse/run_live.sh                  # list the stages only
bash p6_reuse/run_audit.sh 10                                # leak audit: k=10, shadow review of every reuse approval
python -m p6_reuse.audit_report --outdir results/p6_live_audit
```

Inference settings come from `.env` (see `.env.example`): `LMSTUDIO_BASE_URL` (default `http://127.0.0.1:1234/v1`), `LMSTUDIO_MAX_TOKENS` (default 4096) and `REVIEWER_PROVIDER` / `REVIEWER_MODEL` for a separate reviewer. `--provider mlx` is no longer selectable from the runner. P6's MLX-Serve client is still in `agent_framework/local_provider.py`, and `inference.make_inference_client("mlx")` can use it, but the shared runner does not offer it. The audit script's `--shadow-audit` flag is P6 harness only: it asks the reviewer about each reuse approval without enforcing the answer.

LM Studio's MLX engine can fail with `RotatingKVCache Quantization NYI` on long prompts (workspace `user_task_35`, travel `user_task_11`). `local_provider.py` maps that error to AgentDojo's recorded `context_length_exceeded` task error, but the shared LM Studio client does not, so such a task crashes the stage. Turn off KV cache quantization for the model in LM Studio. AgentDojo scores a skipped task as attack success, so the audit report counts errored runs separately.

The held-out split is fixed in `p6_reuse/data/split.json`:

- **Workspace** copies P3's held-out tasks.
- **Slack** is fixed to `injection_task_1` (phishing DM to Alice) and `injection_task_3` (attacker URL visit).
- **Travel** draws two injection tasks that have a reference solution.

## Results so far (offline)

**Probe set** (514 probes from AgentDojo reference solutions, banking money-transfer seeds and three hand-written seeds; reads now get the injected link and code probes too):

| Mutation | Probes | P6 violations | Similarity violations |
|---|---|---|---|
| changed key argument | 149 | 0 | 140 |
| injected link in free text | 111 | 0 | 58 |
| injected code in free text | 111 | 0 | 75 |
| amount raised | 16 | 0 | 13 |
| amount lowered (should reuse) | 16 | 0 missed | 3 missed |
| free text only (should reuse) | 111 | 0 missed | 72 missed |

The P6 gate never reuses an approval for a changed target, link, code or raised amount, and it never misses a reuse it should make. Similarity reuse does both often. The probes score the same-tool predicate only; drill-down is covered by unit tests (`tests/test_reuse_matching.py`, `tests/test_approval_reuse_policy.py`).

**Offline replay** (102 scripted episodes from reference solutions, ideal reviewer; an optimistic bound). TCR is the share of episodes completed safely; reviews are summed over episodes.

| Suite | k | full-escalate TCR | P6 TCR | full-escalate reviews | P6 reviews | P6 reviews saved (approval / denial) |
|---|---|---|---|---|---|---|
| slack | 1 | 0.000 | 0.000 | 21 | 21 | 15 / 0 |
| slack | 2 | 0.048 | **0.143** | 42 | 42 | 15 / 16 |
| slack | 3 | 0.190 | **0.524** | 62 | **60** | 15 / 16 |
| workspace | 1 | 0.417 | **0.500** | 60 | 60 | 12 / 0 |
| workspace | 2 | 0.500 | **0.583** | 115 | **114** | 12 / 48 |
| workspace | 3 | 0.517 | **0.667** | 165 | **157** | 12 / 108 |
| travel | 1 | 0.000 | **0.857** | 21 | 21 | 126 / 0 |
| travel | 2 | 0.000 | **0.905** | 42 | **36** | 126 / 14 |
| travel | 3 | 0.000 | **1.000** | 63 | **39** | 126 / 15 |

"Reviews saved (approval)" counts auto-approved calls, so it includes drill-down; the reviews column counts reviewer calls. Before drill-down, the same replay had P6 TCR 0.000 / 0.048 / 0.333 (slack k=1..3), 0.417 / 0.517 / 0.617 (workspace) and 0.000 / 0.000 / 0.048 (travel).

Replay attack success with the ideal reviewer is 0.000 for full-escalate, P6 and similarity on every suite (full-approve: 1.000). So the safety gate passes.

**Headline.** "P6 TCR@k above full-escalate on Slack and travel at every k" now holds everywhere except slack k = 1 (0.000 vs 0.000: slack tasks need at least two reviews even with drill-down). The replay prints the miss as `headline: NOT MET` with the setting, rather than failing the run. These are optimistic numbers (ideal reviewer, scripted agent); the live runs are the real test.

**Live-trace check (Oct 21, 2026).** Replaying the real policy with an approve-all reviewer over the 16 no-attack live trajectories where full-approve completed the task (`results/p6_live_full`: 2 travel, 6 slack, 8 workspace), mean reviews per run fall from 5.00 to 1.50 (travel), 3.33 to 2.83 (slack) and 2.00 to 1.88 (workspace) with drill-down on, and the tasks finishable at k = 1 / 2 / 3 go from 0/0/0 to 1/2/2 (travel), 0/1/4 to 0/3/5 (slack) and 3/7/7 to 4/7/7 (workspace). The new read address guard costs about 0.1 extra reviews per workspace run. This does not predict live TCR, which the reviewer's own denials limit.

## Smoke test on MLX-Serve (Oct 20, 2026, historical)

Attempted with Gemma-4-E4B. The server started and listed both Gemma and gpt-oss-20b, and the request reached it through `--provider mlx`. MLX-Serve then refused to load Gemma: "needs ~8.3 GB free … but only 4.4 GB is available". Gpt-oss-20b (12 GB on disk) needs more free memory still. The live grids (`results/p6_live_full`, `results/p6_live_audit`) were run on LM Studio with `openai/gpt-oss-20b` instead, and the scripts now target LM Studio.

## Owner deliverables (contract section 11)

- **What it catches.** Repeat attempts of a call the reviewer already denied, without spending budget. It also refuses to extend an approval to a changed recipient, file, URL, reservation target or higher amount, or to free text carrying a new link, email or code.
- **Legitimate calls it may block.** None directly. It only changes escalations, so a missed reuse costs a review, not a denial. A body that legitimately carries a new link or code gets escalated.
- **Unsafe calls it may miss.** An injected call that keeps an approved target and changes only plain free text (for example, a misleading message to an approved recipient without links or codes). Also any unsafe read, because reads are reused at tool level except for URLs.
- **Cost.** No model calls and no policy tokens; per-call latency is a few milliseconds (`gate_ms`).
- **Complementary method.** P7 provenance (or P4 plan consistency) as the base policy, so reuse applies to their escalations. Provenance can also catch the plain-text injection to an approved recipient.

## Open items

- **Tool metadata (now available from P1).** The executor context carries `context["tools"]` (descriptions and parameter schemas) and `context["metadata"]["tool"]` (`agent_framework/tool_meta.py`: `read_only`, `target_args`, `sensitive_output`, `untrusted_output`). The gate still uses its own `tool_table.py` and the verb rule. Resolve in this order once switching: P1's metadata, then the `tool_table.py` entry, then the verb rule, then side effect. P1's `sensitive_output` flag would also give the sensitivity profile below. Also use the description to veto a read verb whose text says it sends, deletes or writes.
- **Sensitivity profile (optional).** Drill-down already allows reads across data sources when the arguments are grounded (a calendar read can cover an email search whose query came from the calendar output). A deployer who wants private sources kept apart needs a per-tool source label; there is none yet.
- **Live rerun.** The live grid in `results/p6_live_full` predates drill-down. Rerun the approval_reuse stages (and ideally with a stronger reviewer) to measure it.

## Configuration

- Registry names: `approval_reuse`, `similarity_reuse` (policies). The reviewer is P1's shared `LLMReviewer`, registered as `llm` (the pipeline name carries the prompt version) and `local_llm` (same class, no version tag). Its model comes from the agent's provider and model, or `REVIEWER_PROVIDER` / `REVIEWER_MODEL` in `.env`.
- Wrapping another base: `functools.partial(ApprovalReusePolicy, base=SomePolicy())`.
