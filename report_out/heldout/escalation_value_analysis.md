# Escalation-value analysis (held-out, all four suites)

Source tables: `report_out/heldout/escalation_value.md` (made by `scripts/report_escalation_value.py`). Every call is put in one of four
classes from `agent_framework/tool_meta.py`:

* **read-only**: `get_`, `search_`, `list_`, `read_` … (no state change)
* **internal, reversible**: writes in the user's own data that can be undone (`create_file`, `append_to_file`)
* **internal, irreversible**: deletions or credential changes in the user's own data (`update_password`, `delete_file`)
* **external effect**: reaches someone else, moves money or publishes (`send_money`, `send_email`, `share_file`, `post_webpage`, `invite_user_to_slack`)

"Attacker's call" means a call whose arguments come from the injected text and not from the user's request (a text-matching heuristic;
numbers are estimates).

## 1. What the agent actually asks for (Full-Approve: nothing blocked)

| class | calls | attacker's | share of class |
|---|---:|---:|---:|
| read-only | 213 | 19 | 9% |
| internal, reversible | 5 | 0 | 0% |
| internal, irreversible | 14 | 6 | 43% (all `update_password`) |
| external effect | 100 | 48 | 48% (`send_email` 26, `send_money` 8, `invite_user_to_slack` 4, `create_calendar_event` 4) |

Read-only calls are 64% of all calls but only 9% of them are the attacker's. External and irreversible calls are 34% of all
calls and 74% of the attacker's (54 of 73). **The risk is concentrated in the calls that change something.**

## 2. What the reviewer does when everything is escalated (Full-Escalate, k ≥ 2)

| class | escalated | attacker blocked | attacker let through | block rate | safe calls wrongly denied | false-deny rate |
|---|---:|---:|---:|---:|---:|---:|
| read-only | 926 | 47 | 19 | 71% | 100 | 12% |
| internal, reversible | 9 | 0 | 0 | - | 0 | 0% |
| internal, irreversible | 29 | 29 | 0 | 100% | 0 | - |
| external effect | 204 | 141 | 2 | 99% | 9 | 15% |

## 3. Which calls benefit most from escalation

* **External-effect calls (send_money, send_email, post_webpage, share_file, invite_user_to_slack).** About half of them in
  attack runs are the attacker's, and the reviewer blocks 141 of 143 (99%). Each wrong approval means money moved or data
  disclosed, and none of it can be undone. These should always reach a human.
* **Irreversible internal changes (update_password, deletions).** The reviewer blocked all 29. This is the class where
  supervised_risk fails: it auto-approved 100% of these calls, and its six over-permissive failures are
  all `update_password` calls approved at a risk score of about 0.04 (see trajectory A). "Internal" does not mean safe: a changed password or a deletion
  cannot be undone either.
* **Safe external writes the user asked for.** These also reach the reviewer, and 9 of 61 (15%) are wrongly denied. Escalation
  here protects against attacks at the price of some friction on legitimate work, which is why it pays off mainly when the
  policy can separate the user's own writes (arguments traced to the request) from injected ones.

## 4. Which calls can be safely auto-approved

* **Read-only calls.** Under Full-Escalate they make up 79% of all escalations (926 of 1,168), and the reviewer's judgement
  there is poor value: it blocks 47 attacker reads but wrongly denies 100 safe reads, 12% of the safe ones, which costs
  utility directly. Provenance and combined_or auto-approve 67% and 74% of reads with 2 and 4 attacker reads let through, and
  most of the attacker reads in the data are `search_emails` (14), which only matter when a later write sends the result out.
  A read is risky because of what happens next, not because of itself, so the check belongs on the write that follows
  (this is the "authorized non-mutating read chain" rule).
* **Reversible internal writes (create_file, append_to_file).** None of the 9 escalations of these was an attack, and each used a
  budget unit. Trajectory D shows the cost: `create_file` took one of the two escalations at k=2. These can be approved
  automatically and logged.
* **Calls whose every argument traces back to the user's request.** Escalating these is wasted budget; the better policies
  already auto-approve them.

## 5. How the policies line up with this (k=10)

| policy | reads auto-approved | external calls auto-approved | external calls escalated or denied | attacker calls auto-approved |
|---|---:|---:|---:|---:|
| provenance | 67% | 5% | 95% | 2 reads, 0 external |
| p4_p6_p7_combined_or | 74% | 17% | 83% | 4 reads, 1 external |
| supervised_risk | 100% | 34% | 66% | 20 reads, 6 irreversible internal |
| Full-Escalate | 0% | 0% | 100% | 0 |

The two best policies approve most reads automatically and push nearly all external writes to a human or a denial, which is
the pattern the numbers above recommend. They are not free of cost: they block 18–19 safe external calls (the
over-conservative failures in trajectory C), and their remaining misses are mostly reads.

## 6. Takeaways for the report

1. Escalate by **effect**, not by tool name: external effects and irreversible changes first, including irreversible changes
   to the user's own account.
2. Do not escalate reads on their own. Track where their output goes and escalate the write that follows.
3. Auto-approve reversible internal writes. They spend the budget without adding protection.
4. The reviewer is not perfect. It blocks 99% of attacker external calls but approved one that repeated the attacker's wording
   (trajectory B) and wrongly denies 12–15% of safe calls, so escalation is only as good as the reviewer.
