# Merging your policy and running the shared evaluation

## 1. Shared settings

| Setting | Value |
|---|---|
| Code tag | `v0.1` |
| Provider / agent model | `groq` / `<AGENT_MODEL>` |
| Reviewer / model / prompt version | `llm` / `<REVIEWER_MODEL>` / `v2` |
| Attack / benchmark | `important_instructions` / `v1.2` |
| Dev k | `2` (first look), `0 2 5` (finalists) |
| Test k | `0 1 2 3 5` |
| Split files | `splits/banking_v1.2.json`, `splits/slack_v1.2.json`, `splits/travel_v1.2.json` |

All shared runs use these values. They are set in `scripts/team_settings.sh`.

## 2. Update your branch

```
git status                      # must be clean (commit, or git stash push -u)
git fetch origin
git switch <your-branch>
git merge origin/main
```

Resolve conflicts as follows, then `git add <file>` and `git commit`:

| File | Keep |
|---|---|
| `agent_framework/registry.py` | Main's reviewers and your policy entry in `POLICIES` |
| `agent_framework/runner.py`, `tools_executor.py`, `llm_providers.py` | Main's version |
| `docs/*.md`, `README.md` | Both sides; remove only the conflict markers |

```
grep -rn "<<<<<<<\|>>>>>>>" agent_framework tests docs *.md     # must print nothing
python -c "import agent_framework.runner"
```

`git merge --abort` restores the previous state.

## 3. Gate behaviour

- `context["metadata"]` is created per call: `{"step", "decision_history", "tool"}`. Do not write to it.
- `context["trajectory"]` is a deep copy. `context["environment"]` is read-only.
- If `evaluate()` raises, the call is treated as `escalate` and logged as `policy_error`.
- The reviewer does not see the policy's `reason` by default.
- Return `(decision, state)` or `(decision, state, info)` with `info = {"reason": str, "scores": {name: number}}`.
- Keep task-specific data in `state`, not in `self`.

## 4. Tool metadata

`context["metadata"]["tool"]` is a dict from `agent_framework/tool_meta.py` covering all four suites (workspace, travel, banking, slack). Use it instead of tool-name prefixes.

| Field | Meaning |
|---|---|
| `read_only` | Changes no state |
| `external_side_effect` | Affects someone other than the user, moves money, or publishes |
| `irreversible` | Cannot be undone by another normal tool call |
| `untrusted_output` | Result contains third-party text (injection surface) |
| `sensitive_output` | Result is private data (exfiltration risk) |
| `target_args` | Arguments naming who or what is affected; their values should trace to the user's request |
| `known` | `False` for a tool missing from the table (conservative fallback) |

Labels (R read-only, E external, I irreversible, U untrusted output, S sensitive output):

| Suite | Tools | Flags |
|---|---|---|
| Workspace | `get_unread_emails`, `get_sent_emails`, `get_received_emails`, `get_draft_emails`, `search_emails` | R, U |
| | `search_contacts_by_name`, `search_contacts_by_email`, `get_current_day` | R |
| | `search_calendar_events`, `get_day_calendar_events`, `list_files`, `get_file_by_id`, `search_files`, `search_files_by_filename` | R, U |
| | `send_email` (`recipients`, `cc`, `bcc`, `attachments`), `share_file` (`file_id`, `email`) | E, I |
| | `cancel_calendar_event` (`event_id`) | E, I |
| | `create_calendar_event` (`participants`), `reschedule_calendar_event` (`event_id`), `add_calendar_event_participants` (`event_id`, `participants`) | E |
| | `delete_email` (`email_id`), `delete_file` (`file_id`) | I |
| | `create_file`, `append_to_file` | none (local writes) |
| Travel | Hotel, restaurant, car and flight listings, prices, addresses, hours | R |
| | `get_rating_reviews_for_hotels`, `..._restaurants`, `..._car_rental` | R, U |
| | `get_user_information` | R, S |
| | `reserve_hotel`, `reserve_restaurant`, `reserve_car_rental` | E, I |
| | Calendar and email tools | as in Workspace |
| Banking | `get_balance`, `get_iban`, `get_user_info` | R, S |
| | `get_most_recent_transactions`, `get_scheduled_transactions` | R, U, S |
| | `read_file` | R, U |
| | `send_money` (`recipient`, `amount`) | E, I |
| | `schedule_transaction`, `update_scheduled_transaction` | E |
| | `update_password` | I |
| | `update_user_info` | none |
| Slack | `get_channels`, `get_users_in_channel` | R |
| | `read_channel_messages`, `read_inbox`, `get_webpage` | R, U |
| | `send_direct_message`, `send_channel_message`, `post_webpage` | E, I |
| | `add_user_to_channel`, `remove_user_from_slack` | E, I |
| | `invite_user_to_slack` | E |

Notes:
- A network destination can carry data out. Require an authorized read chain,
  reject destinations taken from untrusted instructions, and prevent sensitive
  values from being embedded in destination arguments.
- Labels describe what a tool does, not which tools the benchmark's injection tasks use.
- Minimal use (individual policies may apply stricter provenance rules):

```python
meta = context["metadata"]["tool"]
if not meta["known"]:
    return "escalate", state, {"reason": "tool not in metadata table"}
if meta["read_only"] and not meta["sensitive_output"]:
    # Also verify that the call serves the user's request and that arguments
    # are user-provided or come through a non-instructional read chain.
    ...
targets = [str(call.args.get(a)) for a in meta["target_args"] if call.args.get(a)]
```

## 5. Register the policy

Add one line to `POLICIES` in `agent_framework/registry.py`: `"<name>": YourPolicyClass,`. The class must be constructible without arguments.

## 6. Offline checks

```
python -m pytest tests -q
```

All tests must pass, including `tests/test_policy_contract_all.py`. If a scenario in `tests/scenarios.py` fails because of a documented limitation, list it in `KNOWN_FAILURES` with the reason. Do not remove or weaken tests.

## 7. Compatibility run

```
source scripts/team_settings.sh
python -m agent_framework.runner --provider $PROVIDER --policy <name> --llm $AGENT_MODEL \
  --reviewer $REVIEWER --reviewer-model $REVIEWER_MODEL --attack $ATTACK \
  --user-tasks user_task_0 user_task_1 user_task_2 --injection-tasks injection_task_0 \
  --k 2 --outdir results/compat/<owner>
python scripts/verify_traces.py results/compat/<owner>
```

Expected: `0 problems`. Any `policy_error` indicates a bug in the policy.

## 8. Dev run

Dev tasks may be rerun and tuned on.

```
bash scripts/run_split.sh <name> dev "2" results/dev/<owner>
python scripts/verify_traces.py results/dev/<owner>
```

eg:
```
bash scripts/run_split.sh full_approve  dev "0"     results/baselines/dev/P1
python scripts/verify_traces.py results/baselines/dev/P1
```

Use `"0 2 5"` for finalists. Baselines (`full_approve`, `full_escalate`) are run by P1. If the runner stops on a rate limit, rerun the same command later; finished tasks are cached.

## 9. Submit dev results

```
mkdir -p submitted_results/dev/<owner>
cp results/dev/<owner>/*/summary_*.json submitted_results/dev/<owner>/
```

Commit `submitted_results/`, and send the zipped `results/dev/<owner>` to P5 and P6. Complete `docs/<name>.md` with:

1. What the policy catches.
2. Legitimate calls it blocks (`auto_denials`, `budget_exhausted_denials`).
3. Unsafe calls it misses.
4. Cost (`token_usage`, `policy_latency_s`).
5. A complementary method.
6. Tasks examined during development (reported to P1 for `splits/examined.json`).

## 10. Freeze

```
git tag freeze-<owner> && git push origin freeze-<owner>
```

Send P1 the tag and commit hash. A policy changed after freezing must be reported as such, and its test results then count as dev data.

## 11. Test run

Run once, after freezing.

```
FINAL_RUN=1 bash scripts/run_split.sh <name> heldout "0 1 2 3 5" results/test/<owner>
python scripts/verify_traces.py results/test/<owner>
mkdir -p submitted_results/test/<owner>
cp results/test/<owner>/*/summary_*.json submitted_results/test/<owner>/
```

Commit the summaries and send the zipped folder to P5 and P6.

## 12. Rules

- Tune on dev only; do not read or run heldout tasks before freezing.
- Do not edit `tools_executor.py`, `runner.py`, `tool_meta.py` or `splits/`.
- Do not commit `.env` or `results/`; check `git status` before each commit.
