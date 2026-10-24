Task-disjoint shared-prompt DEV — incomplete live study, GPT-OSS-20B/20B, k=2.

| Variant | Suite | Cases finished | Safely completed | TCR on finished cases | HITL Load | Total reviews | Attacks | Budget denials |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| detector_generic | banking | 18/18 | 7/18 | 38.9% | 11 | 23 | 0 | 2 |
| detector_generic | slack | 14/14 | 1/14 | 7.1% | 2 | 24 | 0 | 7 |
| detector_generic | travel | 8/14 | 0/8 | 0.0% (partial) | 0 | 16 | 0 | 10 |
| generic_rules_only | slack | 9/14 | 1/9 | 11.1% (partial) | 1 | 14 | 0 | 2 |
| detector_only | slack | 13/14 | 1/13 | 7.7% (partial) | 2 | 24 | 2 | 16 |

Partial rows use different case subsets and cannot rank variants. Detector-only retains coverage fallback. Generic-rules-only retains coverage and mandatory sensitive-action reviews. Compare detector_generic against generic_rules_only to isolate the forest, once complete.
No held-out results are included. Clean completion uses utility alone.
