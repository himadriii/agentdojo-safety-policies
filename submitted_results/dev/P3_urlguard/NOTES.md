# P3 + URL guard, dev split, k=2

Policy `supervised_risk_urlguard`: frozen P3 risk model plus a deterministic rule that denies a `get_webpage` URL the user never wrote and that appears only in instruction-like tool output.
Provider lmstudio (gpt-oss-20b agent, llm reviewer on gpt-oss-20b). Travel run one pair per process; its summary is rebuilt from traces.

| Suite | P3 alone | P3 + URL guard |
|---|---|---|
| Slack | 1/14 | 2/14 |
| Banking | 9/18 | 7/18 |
| Travel | 3/13 | 1/14 |

The rule only fires on get_webpage, so banking/travel differences are run-to-run variation. The Slack "FAILED" line in the progress log is a console UnicodeEncodeError after the summary was written.
