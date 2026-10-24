# P2 anomaly approval gate: implementation and evidence plan

> Historical initial plan. The v1 inner split and calibration figures are superseded
> by the family audit in `p2_anomaly/splits.py`. Current model status and resume details
> are in `p2_anomaly/artifacts/development/readiness.json`.

Prepared October 20, 2026. This is a proposed implementation plan, not a trained gate or experimental result.

## 1. Scope and repository audit

P2 owns legitimate-data collection, feature extraction, Isolation Forest fitting, threshold calibration, the standalone policy, evaluation, and its report section. P1 owns execution/reviewer/budget; P6 owns shared comparisons; P1/P4 own combination logic. Do not implement a second runner or take over the combined method.

Inspected after fetching origin:

| Reference | Commit | Relevant contents |
| --- | --- | --- |
| main / local HEAD | 53ce03b | Policy interface, runner, baseline policies, no P2 implementation |
| p1-llm-reviewer | bb39c36 | LLM reviewer and runner hardening |
| sahana | 763323e | P3 risk model, dataset construction, task split, results documentation |
| vk/p4_policy | ac26fc2 | Plan-consistency policy |
| feat/p7_provenance | 7e2f467 | Provenance work |

These branches are not all integrated into main. Plan P2 as an isolated addition and coordinate the final integration commit with P1. Do not blindly merge every branch: shared registry/runner files overlap.

The project plan called for standalone freeze October 19. That date has passed. Record the actual P2 freeze date; aim for October 21, with final runs completed October 24. Never backdate the model or tune on final outcomes to catch up.

## 2. What the gate should do

Learn the distribution of legitimate, task-conditioned tool calls. At inference, measure how unusual a proposed call is relative to those examples.

Initial policy:

```text
valid features + score below calibrated threshold -> approve
score at/above threshold                          -> escalate
missing model / unknown tool / invalid features   -> escalate with factual reason
```

Do not turn an anomaly score into a probability of harm. Do not add an automatic-deny threshold merely because a score is large. The runner already denies escalation-worthy calls when k is exhausted. P2 therefore uses two of the three permitted interface decisions; this satisfies the contract.

If a separate automatic-deny variant is later justified on development data, report it as a separate configuration and freeze it before final testing. Do not quietly mix rule-based rejection into the primary anomaly method.

## 3. Data: exact sources and roles

Use the repository-pinned `agentdojo==0.1.35`, benchmark `v1.2`, suite `workspace`. The benchmark version and Python package version are different settings; record both.

AgentDojo is an executable environment, not a ready-made CSV of gate decisions. Its user tasks, tools, initial environment, ground-truth pipelines, and attack generators let us generate matching examples. Source: https://github.com/ethz-spylab/agentdojo and https://agentdojo.spylab.ai/concepts/task_suite_and_tasks/.

| Data | How obtained | Allowed use |
| --- | --- | --- |
| Clean user-task reference trajectories | `get_suite('v1.2', 'workspace')`, each allowed user task, clean environment, `GroundTruthPipeline` | Bootstrap normal behaviour for training; separately generate calibration-task references |
| Actual no-attack agent trajectories | Shared runner, `full_approve`, `--attack none`, agreed agent/provider | Audit legitimate calls; training and calibration according to user-task partition |
| Development attack trajectories | Shared runner, allowed development user/injection IDs and agreed development attacks | Diagnostic attack detection and development-only policy trade-offs; never normal-only fitting |
| Frozen held-out clean and attack episodes | Shared runner after artifact freeze, common test manifest | Final utility, safety, review load, cost; never tuning |
| P3 generated/spliced CSV | `origin/sahana:p3_risk/data/dataset.csv` | Optional explicitly synthetic diagnostic; not primary normal data or final online evidence |

Do not download generic phishing, spam, NSL-KDD, jailbreak prompt, or unrelated text-classification datasets as primary data. Their examples are not AgentDojo tool-call contexts. No external dataset is required for the first gate.

Important P3-specific audit: `build_dataset.py` can splice attacker calls even for `attack='none'`. Selecting that string does not establish a clean episode. Repeated user-call prefixes across injection/attack combinations also inflate row counts. Prefer generating clean references directly once per user task. P3's real trace labeler treats unmatched attack calls as benign; do not inherit that assumption as verified ground truth.

### Legitimate-data criteria

- User tasks only, not AgentDojo's auxiliary runs where an injection goal is presented as a user request.
- No injected environment for primary fitting; no network/API-failure traces silently treated as completed episodes.
- Correctly parsed tool calls and schema-valid arguments.
- Audit calls for consistency with the user request. No attack does not guarantee the agent behaved legitimately; successful final utility does not prove every intermediate action was authorized.
- Keep normal searches, retries, intermediate reads, and legitimate side effects if audited. A failed task may contain useful legitimate calls; do not automatically mark all its calls unsafe.
- Keep an inclusion/exclusion ledger with reasons; report tool/action coverage, not just row count.

## 4. Preserve the existing held-out split

Copy and hash `origin/sahana:p3_risk/data/split.json` as the shared outer split, pending P1/P6 ratification. Do not invent a different final test set for P2.

Existing held-out user IDs:

```text
0, 1, 2, 4, 8, 13, 15, 22, 27, 28, 33, 35
```

Existing held-out injection IDs: `2, 7, 9, 10`.

Proposed deterministic inner split of the remaining 28 user tasks:

```text
FIT (20): 3, 5, 6, 7, 9, 10, 11, 12, 14, 16, 17, 18, 19, 20,
          21, 23, 24, 25, 26, 29
CALIBRATE (8): 30, 31, 32, 34, 36, 37, 38, 39
```

These are `user_task_N` identifiers. This is a proposed fixed partition, not a claim of balanced coverage. Audit fit/calibration tool coverage before any final runs. If a coverage-based revision is needed, document it using development tasks only and then freeze the manifest. With little data, grouped out-of-fold development scoring is a valid alternative, but do not alternate schemes after seeing test outcomes.

Every repeat, prompt variant, ground-truth reference, and attack pairing for one user task stays in its partition. Do not randomly split individual calls. Deduplicate repeated full episodes and replicated synthetic prefixes; legitimate repeated searches within an episode remain part of behaviour. Inspect near-duplicate task templates and report any residual template overlap.

Development attack diagnostics use development injection IDs only. P3 reserves `injecagent`, `tool_knowledge`, and `system_message` as unseen attack styles; preserve that reservation if claiming a common unseen-style test. Verify support in the pinned package rather than assuming every listed attack works.

## 5. Feature design: small, contextual, reproducible

Start with approximately 15–25 explicit features, not high-dimensional text embeddings or a second LLM. Isolation Forest with little normal data is vulnerable to irrelevant dimensions.

| Group | Candidate features | Interpretation caveat |
| --- | --- | --- |
| Action structure | Explicit tool category indicators; argument count; missing expected keys | Rare legitimate tools can be anomalous |
| Argument shape | log character count; number of recipients, URLs, IDs, nested items | Long content is not inherently malicious |
| Task alignment | Task/argument token overlap; action mentioned in task; recipient explicitly in task | Legitimate recipient discovery often happens through tools |
| Visible-history consistency | Recipient or target previously observed; task/history argument support fractions | Being in tool output does not authorize an action |
| Local sequence | Previous completed tool category; repeated-call count; prior tool-error count | Model normal retries, not just ideal reference sequences |

Use an explicit workspace tool table from the pinned suite. Prefix guesses are not enough to establish side effects. Unknown tools trigger fallback review. Avoid raw email addresses, filenames, task IDs, call IDs, attack strings, and final labels as model inputs.

Primary features should not depend on injection-template regexes. Add such features only as a disclosed ablation if development evidence warrants them. P3 already provides a richer supervised detector; P2's value is learning normality without unsafe labels.

Do not inspect the live environment for hidden contacts or targets in the first version. Although the interface permits read-only access, visible task/history features give a simpler boundary and avoid reconstructing historical environment state incorrectly. Never read benchmark goals, security checks, ground truth, or attack identifiers inside the policy.

One extractor serves offline fitting and runtime scoring. Separate audit metadata from an explicit ordered feature allowlist. Missing/invalid features must trigger fallback; never silently replace a broken vector with all zeros and approve it.

### Historical reconstruction rules

For each candidate call, include only the trajectory prefix ending at its requesting assistant message. Never include its future tool result or later messages. Ground-truth extraction should record the context before executing each call, not attach the final environment to every earlier call.

Several calls in one assistant message receive the same trajectory in the current runner. Do not pretend an earlier sibling result is visible. Track call attempts in task state if needed; establish actual execution or errors only when visible in subsequent tool messages. The policy's last recommendation is not evidence a call executed.

## 6. Model and threshold protocol

1. Validate feature coverage, constant columns, distributions, and duplicate episodes. Fit all preprocessing and frequency statistics on FIT tasks only.
2. Begin with `IsolationForest(n_estimators=200, max_samples='auto', contamination='auto', random_state=42, n_jobs=1)` as a reproducible starting configuration. Log-transform heavy-tailed counts; do not assume scaling fixes semantic feature problems.
3. Define anomaly score as `-model.score_samples(X)` so larger means more unusual. Use this definition everywhere. Scikit-learn's built-in `predict()` cutoff is not our calibrated approval threshold.
4. Score clean CALIBRATE trajectories. Examine candidate escalation rates (for example 5%, 10%, 20%) alongside task-level review burden. These are operating-point candidates, not promised guarantees. Select one on development evidence and record the selection rule.
5. Prefer one global threshold initially. Show errors by action category. Do not train per-tool forests on a handful of calls; disclose insufficient coverage and use fallback review for unsupported tools.
6. Do not refit the forest on FIT+CALIBRATE after choosing the threshold: its score distribution changes. Either keep the fitted model, or obtain a fresh independent calibration protocol before any final test.
7. Freeze model, feature order/version, preprocessing, threshold, tool table, split hash, training manifest, dependencies, and source commit together.

Clean-only calibration supports a claim about observed normal-call review rate, not malicious-call recall or a distribution-free guarantee. Calls within tasks are dependent and eight calibration tasks give coarse estimates. Report task-level uncertainty and sample counts. Any attack-informed threshold selection must be disclosed as development attack tuning even though forest fitting remains normal-only.

If data are sparse: use clean ground-truth references to bootstrap and transparently report their limitations. Do not duplicate rows thousands of times or invent arbitrary perturbations and call them new legitimate observations. Additional actual runs cost API budget; use measured call counts and provider limits before scheduling them.

## 7. Concrete implementation deliverables

```text
agent_framework/policies/anomaly_features.py   shared extractor and feature schema
agent_framework/policies/anomaly.py            Policy implementation, artifact loading
p2_anomaly/data/split.json                     frozen outer/inner split
p2_anomaly/collect_reference.py                clean development reference collection
p2_anomaly/extract_traces.py                   real trace prefix extraction and audit ledger
p2_anomaly/train.py                            normal-only fit and clean calibration
p2_anomaly/evaluate.py                         offline diagnostics, explicitly not online TCR
p2_anomaly/artifacts/                          frozen model, threshold, manifest, coverage
tests/test_anomaly.py                          behavioural and contract checks
docs/p2_anomaly_results.md                     measured results and report contribution
```

Register `anomaly` through the zero-argument policy factory. Load immutable artifacts once, keep task history in the returned state, and do not learn or recalibrate during final evaluation. Keep budget logic in P1's executor. Report finite numeric scores, threshold and fallback flags; reasons should state observed facts, without asserting that unusual means malicious. Keep external text out of reason strings where possible because the reviewer sees the reason.

Essential checks: batch and single-call prefix equivalence, no future-message leakage, state reset, missing artifact/unknown tool fallback, extractor errors, deterministic scores, no context mutation, denied calls not executed, and budget handling through the shared runner. Verify saved-artifact reload reproduces the same decisions. These checks prevent consequential gate failures; do not write tests that merely restate the feature formulas.

## 8. Collection commands and API cost control

Run from the agreed integrated checkout with the team's agreed agent/reviewer settings. Existing interface docs specify Groq `openai/gpt-oss-20b`; confirm the final experiment configuration with P1 rather than changing models per policy.

Example clean FIT collection, using a permitted development task:

```bash
python -m agent_framework.runner --provider groq --llm openai/gpt-oss-20b \
  --benchmark-version v1.2 --suite workspace --policy full_approve \
  --attack none --user-tasks user_task_3 --k 0 --outdir results/p2/fit/rep0
```

Enumerate only the manifest's permitted tasks. Distinct repetition directories avoid cached logs masquerading as independent samples. Use `--force` only for intentional reruns. Existing no-attack traces can be reused after checking model/version, split membership, clean status, and legitimacy. P3's shell collector uses a Windows `.venv/Scripts/python` path; adapt it to this macOS environment instead of copying it unchanged.

Start with one clean reference per FIT task and one real clean run per allowed FIT/CALIBRATE task, subject to agreed API budget. Check actual usable-call count and action coverage before deciding whether repeats add value. Synthetic references are cheap; live agent calls are the cost driver. Do not assume provider access or spend budget without a bounded run manifest.

## 9. Evaluation that supports the report

Use final online reruns for each policy because blocking changes subsequent agent behaviour. Offline scoring of Full-Approve traces is useful for diagnostics but cannot establish final TCR for a blocking policy.

After freeze, evaluate the common held-out clean tasks and common supported held-out user/injection pairs. Include Full-Approve and Full-Escalate with the same agent, reviewer, attacks, budget grid, and error treatment. Budget grid in current runner: `0, 1, 2, 3, 5`; reduce only through a documented shared plan, not opportunistically per policy. Preflight infeasible requests on development tasks.

Report:

- Safe completion TCR@k; raw utility; attack-success rate, with denominators.
- HITL Load on all episodes and on completed-safe episodes, plus calls per episode. A lower completed-only load can simply mean fewer completions.
- Clean-call escalation rate; clean task completion loss; budget-exhaustion denials.
- Unsafe-call flag rate only on independently audited call labels. An attack episode is not an unsafe label for every call. Reads are not universally harmless; task authorization and downstream information flow matter.
- Offline ROC/AUPRC only if meaningful audited call labels exist; otherwise omit rather than manufacture labels from final task outcomes.
- CPU extraction/scoring latency, training time, artifact size, reviewer/agent tokens and actual costs where known. No LLM policy calls does not mean zero total cost.
- Planned, attempted, completed and errored episodes. Do not count an API error as evidence of safety. Show common-completed comparisons and completion coverage without quietly changing the planned denominator.
- Per-task or grouped-bootstrap uncertainty; do not treat thousands of correlated calls as thousands of independent trials.

The mock reviewer approves everything. Use it for plumbing and reviewer-sensitivity diagnostics, not as a realistic human safety result. With mock approval, increasing k can execute more flagged unsafe calls; with k=0 the runner blocks every escalation. Always name the reviewer.

Use the common suite security evaluator for headline comparisons, while separately inspecting actually executed unsafe calls from traces. Current docs acknowledge limitations of final-state security checks. Do not replace the team's metric silently or infer safety solely from a denied recommendation.

Useful small ablations: reference-only versus adding audited real clean data; structural features versus adding task/history features; a threshold sensitivity curve using development data. Avoid a large hyperparameter sweep with so few independent tasks.

## 10. Recovery schedule and acceptance criteria

| Date | Concrete outcome |
| --- | --- |
| Oct 20 | Lock shared split/config; implement clean reference extraction, policy skeleton and feature schema; inspect coverage |
| Oct 21 | Fit baseline forest, calibrate, run contract checks and development smoke tests; freeze with actual timestamp |
| Oct 22–24 | Run agreed held-out matrix with P1/P6; save traces, manifest and errors; no threshold edits |
| Oct 25 | Supply method/data/results/limitations section and representative trajectories to P5 |
| Oct 26 | Reproduce artifact reload and documented commands; cross-check report numbers |
| Oct 27 | Submission buffer |

Ready for handoff means: callable registered policy; immutable artifact and manifest; documented fit/calibration/test boundary; successful integrated smoke run; reproducible commands; measured standalone results or explicit pending status; representative false positive, missed attack and fallback; and honest limitations. If coverage or API access prevents sound final results, deliver a clearly labeled prototype and partial evidence rather than claim a validated gate.

Expected limitations: rare legitimate side effects cause false alarms; malicious calls can look statistically normal; clean references underrepresent real retries; shared workspace entities limit generalization; textual overlap is weak evidence of authorization; small calibration/test task counts limit certainty. A provenance or plan-consistency policy is a plausible complement, but P1/P4 choose combinations from development evidence.

## References

- Shared contract in this checkout: `docs/policy_interface.md`.
- P3 split and data code: https://github.com/himadriii/agentdojo-safety-policies/tree/sahana/p3_risk.
- AgentDojo executable tasks and ground truth: https://agentdojo.spylab.ai/concepts/task_suite_and_tasks/.
- Clean and injected benchmark runners: https://agentdojo.spylab.ai/api/benchmark/.
- Isolation Forest score conventions and parameters: https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html.
