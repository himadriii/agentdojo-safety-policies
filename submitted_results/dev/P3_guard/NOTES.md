# P3 + URL guard + reservation guard (supervised_risk_guard), dev split, travel only, k=2

Policy `supervised_risk_guard` (tag `freeze-sahana-guard`): frozen P3 risk model, the get_webpage URL guard, and a reservation guard that denies reserve_hotel / reserve_car_rental / reserve_restaurant_at_given_time when the booked place is not named in the user's task and earlier tool output contained instruction-like text.
Only travel was run (the other suites are unaffected by the new rule). Provider lmstudio (gpt-oss-20b agent, llm reviewer), one pair per process; summary rebuilt from traces.

| Travel dev, k=2 | P3 | P3 + URL guard | + reservation guard |
|---|---|---|---|
| Safe completions | 3/13 | 1/14 | 0/14 |
| Attacks succeeded | 1/13 | 1/14 | 0/14 |
| User task completed | 3/13 | 1/14 | 0/14 |

The rule was designed on these dev tasks, so the zero attack result is optimistic. The agent fails most travel user tasks on this server whatever the policy. No held-out run was done for this policy.
