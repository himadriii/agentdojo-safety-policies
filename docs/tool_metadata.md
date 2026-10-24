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

