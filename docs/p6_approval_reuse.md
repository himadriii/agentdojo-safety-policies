# P6: Reuse of Previous Approvals

Owner: P6. Plan: `docs/plans/2026-10-19-1857-feat-p6-approval-reuse-gate-plan.md`.

## Method

`approval_reuse` wraps a base policy (full-escalate by default, "manual approval mode"). When the base escalates, the gate checks what the reviewer already decided earlier in the same task:

| Situation | Decision | Budget |
|---|---|---|
| Repeats a call the reviewer denied (same tool and key arguments; reads: identical arguments) | `deny` | not spent |
| Covered by a call the reviewer approved | `approve` | not spent |
| Anything else | `escalate`, and remembered | spent by the runner |

"Covered" is tiered:

- **Reads** are covered at tool level. One approved `search_emails` covers later searches. A URL argument is always key, so an approved `get_webpage` covers only the same URL.
- **Side effects** are covered only when every key argument matches: recipients, cc, bcc, participants, payee, file, email, event, channel, user, URL or reservation target. A list may narrow (a subset of approved recipients), and an amount may only go down. Free text (body, subject, content) may change. Reuse is blocked if the new free text carries a link, an email address or a code-like token (5+ digits, or 8+ mixed letters and digits, such as an IBAN) found in neither the user's task nor the approved call.

The full per-tool table is in `agent_framework/policies/approval_reuse/tool_table.py`. Unknown tools are side effects with every argument key.

The runner does not tell policies what the reviewer decided, so the gate reads it off the trajectory. The tool result for a call it escalated either carries the runner's denial message (denied) or does not (executed after approval). Escalations made with zero budget left were denied by the runner, not the reviewer, and are dropped. All memory lives in the task-scoped `state`; nothing carries across tasks. The gate makes no LLM calls. Each decision logs `reuse_approved`, `reuse_denied` and `gate_ms` scores.

`similarity_reuse` is the comparison: the "cluster similar operations" reading of the original idea. It reuses an approval when the token Jaccard over all argument values is at least 0.5, with no key arguments, no token scan and no denial memory.

## Commands

```bash
python -m pytest tests -q                        # all offline tests
python -m p6_reuse.probes                        # probe set -> results/p6/probes/
python -m p6_reuse.replay                        # offline replay -> results/p6/replay/
python -m p6_reuse.summarize --outdir results/p6_live   # tables from live runs
```

Live runs use a local MLX-Serve server (OpenAI-compatible) through `--provider mlx`, and the `local_llm` reviewer on the same model:

```bash
/Applications/MLX-Serve.app/Contents/MacOS/mlx-serve serve --host 127.0.0.1 --ctx-size 32768 \
    --model-dir ~/.mlx-serve/models --model-dir ~/.lmstudio/models
bash p6_reuse/smoke.sh lmstudio-community/gemma-4-E4B-it-MLX-4bit          # smoke
MODEL=mlx-community/gpt-oss-20b-MXFP4-Q8 bash p6_reuse/run_live.sh 4      # final grid, resumable
```

`MLX_BASE_URL` (default `http://127.0.0.1:11234/v1`) and `MLX_MAX_TOKENS` (default 4096) configure the provider. The provider makes four fixes for MLX-Serve:

- Forces temperature 0, because AgentDojo sends 0.0 as "not given".
- Sets `max_tokens`, because MLX-Serve defaults an omitted value to 100.
- Maps `developer` to `system`.
- Turns MLX-Serve's context-length and GPU-memory errors into AgentDojo's recorded `context_length_exceeded` task error.

The held-out split is fixed in `p6_reuse/data/split.json`:

- **Workspace** copies P3's held-out tasks.
- **Slack** is fixed to `injection_task_1` (phishing DM to Alice) and `injection_task_3` (attacker URL visit).
- **Travel** draws two injection tasks that have a reference solution.

## Results so far (offline)

**Probe set** (424 probes from AgentDojo reference solutions, banking money-transfer seeds and three hand-written seeds):

| Mutation | Probes | P6 violations | Similarity violations |
|---|---|---|---|
| changed key argument | 149 | 0 | 140 |
| injected link in free text | 66 | 0 | 56 |
| injected code in free text | 66 | 0 | 60 |
| amount raised | 16 | 0 | 13 |
| amount lowered (should reuse) | 16 | 0 missed | 3 missed |
| free text only (should reuse) | 111 | 0 missed | 72 missed |

The P6 gate never reuses an approval for a changed target, link, code or raised amount, and it never misses a reuse it should make. Similarity reuse does both often.

**Offline replay** (102 scripted episodes from reference solutions, ideal reviewer; an optimistic bound). TCR is the share of episodes completed safely; reviews are summed over episodes.

| Suite | k | full-escalate TCR | P6 TCR | full-escalate reviews | P6 reviews | P6 reviews saved (approval / denial) |
|---|---|---|---|---|---|---|
| slack | 1 | 0.000 | 0.000 | 21 | 21 | 0 / 0 |
| slack | 2 | 0.048 | 0.048 | 42 | 42 | 3 / 16 |
| slack | 3 | 0.190 | **0.333** | 62 | 62 | 9 / 16 |
| workspace | 1 | 0.417 | 0.417 | 60 | 60 | 7 / 0 |
| workspace | 2 | 0.500 | **0.517** | 115 | 115 | 8 / 48 |
| workspace | 3 | 0.517 | **0.617** | 165 | **159** | 9 / 108 |
| travel | 1 | 0.000 | 0.000 | 21 | 21 | 6 / 0 |
| travel | 2 | 0.000 | 0.000 | 42 | 42 | 7 / 20 |
| travel | 3 | 0.000 | **0.048** | 63 | 63 | 10 / 27 |

Replay attack success with the ideal reviewer is 0.000 for full-escalate, P6 and similarity on every suite (full-approve: 1.000). So the safety gate passes.

**Headline finding.** The planned headline was "P6 TCR@k above full-escalate on Slack and travel at every k". It holds at k = 3 on all three suites, but not at k = 1 or 2 on Slack and travel. Those tasks need three or more different tools. Every call escalates under the full-escalate base, and reuse saves a review only when a tool repeats. Most savings at low k come from denial memory: retries of a denied call no longer burn budget. The replay prints this as `headline: NOT MET` and lists the settings, rather than failing the run.

## Smoke test on MLX-Serve (Oct 20, 2026)

Attempted with Gemma-4-E4B. The server started and listed both Gemma and gpt-oss-20b, and the request reached it through `--provider mlx`. MLX-Serve then refused to load Gemma: "needs ~8.3 GB free … but only 4.4 GB is available". Close other apps, or pass `--skip-mem-preflight` if you accept the crash risk, and rerun `smoke.sh`. Gpt-oss-20b (12 GB on disk) needs more free memory still. No live numbers exist yet.

## Owner deliverables (contract section 11)

- **What it catches.** Repeat attempts of a call the reviewer already denied, without spending budget. It also refuses to extend an approval to a changed recipient, file, URL, reservation target or higher amount, or to free text carrying a new link, email or code.
- **Legitimate calls it may block.** None directly. It only changes escalations, so a missed reuse costs a review, not a denial. A body that legitimately carries a new link or code gets escalated.
- **Unsafe calls it may miss.** An injected call that keeps an approved target and changes only plain free text (for example, a misleading message to an approved recipient without links or codes). Also any unsafe read, because reads are reused at tool level except for URLs.
- **Cost.** No model calls and no policy tokens; per-call latency is a few milliseconds (`gate_ms`).
- **Complementary method.** P7 provenance (or P4 plan consistency) as the base policy, so reuse applies to their escalations. Provenance can also catch the plain-text injection to an approved recipient.

## Configuration

- Registry names: `approval_reuse`, `similarity_reuse` (policies); `local_llm` (reviewer, reads `MLX_MODEL`, which `--provider mlx` sets from `--llm`).
- Wrapping another base: `functools.partial(ApprovalReusePolicy, base=SomePolicy())`.
