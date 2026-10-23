# Implementation Plan

**Seven-person team | GitHub repository and report due Oct 27, 2026**

One owner per standalone idea; P1 and P4 co-own the combined method. Presentation preparation is outside this plan.

P2 and P3 have protected time for data preparation, training and calibration. Model fitting may be quick; reliable features and training data take longer. P1 has substantial early integration work, while P7's provenance extraction also requires careful debugging.

| Person | Primary ownership | Additional responsibility |
|--------|-------------------|--------------------------|
| P1 | AgentDojo integration, shared reviewer, budget enforcement and mandatory baselines | Combined method with P4; repository reproducibility |
| P2 | Anomaly detection: legitimate data, features, training and calibration | Own method's evaluation and limitations |
| P3 | Supervised risk model: labeled data, features, training and calibration | Own method's evaluation and limitations |
| P4 | Plan-consistency policy | Combined method with P1; compare complementary methods |
| P5 | Saroku Guard and simple rule baseline | Cross-policy failure analysis; assemble report |
| P6 | Reuse of previous approvals | Shared metrics, evaluation scripts, cost analysis and plots |
| P7 | Provenance-based approval gate | Provenance failure analysis and representative trajectories |

Everyone writes their own method, results and limitations. P5 assembles and edits these contributions. Only P1 and P4 implement the combined method; other owners supply outputs and explain findings.

---

## Week 1 — Shared setup and prototypes
*Oct 2, 2026 to Oct 8, 2026*

| Person | Tasks and output |
|--------|-----------------|
| P1 | Publish the policy interface and sample inputs by **Oct 3, 2026**. Build AgentDojo integration, reviewer, budget enforcement and logging. Provide a runnable setup by **Oct 5, 2026** and Full-Approve/Full-Escalate baselines by week end. |
| P2 | Define anomaly features and legitimate-data criteria. Build extraction code and begin collecting development trajectories. Prioritize a reliable dataset before model tuning. |
| P3 | Define risk features and labeling guidelines. Prepare task-relevant training examples and a separate validation set. Audit sample labels before expanding the dataset. |
| P4 | Build the plan-consistency prototype and test sample inputs. Draft combination structures using dummy scores, so integration can begin before trained models are ready. |
| P5 | Verify Guard feasibility early; build its three-way policy wrapper and the rule baseline. Set up the report outline and common failure-analysis template. |
| P6 | Build approval-memory prototype. Implement metrics and plots using sample logs; agree on evaluation settings with P1. |
| P7 | Define provenance records, implement extraction and initial rules, and test direct versus indirect instructions. |

> **Checkpoint:** Every policy has a callable skeleton by **Oct 8, 2026**. P2/P3 may use placeholder outputs for interface testing; fully trained models are not required yet.

---

## Week 2 — Protected model development
*Oct 9, 2026 to Oct 15, 2026*

| Person | Tasks and output |
|--------|-----------------|
| P1 | Stabilize the shared runner and finish baseline experiments. With P4, build the combined-policy framework using placeholder component outputs. |
| P2 | Complete feature extraction and legitimate training data. Train Isolation Forest, investigate errors and tune thresholds on development tasks. |
| P3 | Finish the initial labeled dataset, train the classifier, inspect label/model errors and calibrate decision thresholds. |
| P4 | Evaluate plan consistency and refine its prompt/scoring. With P1, implement candidate combination logic and identify evidence needed to choose between combinations. |
| P5 | Evaluate Guard and the rule baseline. Collect failure examples from available policies and group them into a shared failure taxonomy. |
| P6 | Evaluate approval reuse, including changed recipients and arguments. Validate metrics and generate preliminary comparisons for policies that are ready. |
| P7 | Improve provenance extraction. Test transformed content, missing source links and unauthorized instructions; separate extraction errors from rule errors. |

> **Checkpoint:** First trained P2/P3 models by **Oct 15, 2026**. Each supplies a working interface, preliminary results and a few failure examples—not a polished report or extensive cross-policy analysis.

---

## Week 3 — Combine and freeze
*Oct 16, 2026 to Oct 22, 2026*

| Person | Tasks and output |
|--------|-----------------|
| P1 | Connect selected components with P4. Handle state, execution order, logging and costs. Run integration checks and begin final experiments. |
| P2 | Refine the model and thresholds through **Oct 18, 2026**. Freeze anomaly policy by **Oct 19, 2026**, run standalone final experiments and write method/limitations notes. |
| P3 | Continue data-quality fixes, tuning and calibration through **Oct 18, 2026**. Freeze risk policy by **Oct 19, 2026**, run standalone final experiments and write method/limitations notes. |
| P4 | Lead combination selection from development results. Implement decision logic with P1, compare against standalone methods and run component-removal ablations. |
| P5 | Lead cross-policy failure analysis using owners' examples. Assemble available report sections and document which weaknesses the combination addresses. |
| P6 | Aggregate results, validate metrics and compare review savings against safety/completion losses. Produce combined-versus-standalone plots. |
| P7 | Freeze provenance policy and run standalone evaluation. Supply representative trajectories showing successful and failed provenance reasoning. |

> **Checkpoints:** Choose the combination by **Oct 17, 2026**; freeze all standalone methods by **Oct 19, 2026** and the combined method by **Oct 21, 2026**. P1/P4 develop against preliminary outputs while P2/P3 finish tuning. Final runs use held-out tasks after each policy is frozen.

---

## Week 4 — Evidence and submission
*Oct 23, 2026 to Oct 26, 2026*

| Person | Tasks and output |
|--------|-----------------|
| P1 | Finish combined-method runs. Verify reproducibility from a clean checkout and finalize GitHub setup and experiment commands. |
| P2 | Finalize anomaly results, data/features documentation and limitations. Check that the report accurately describes the model. |
| P3 | Finalize supervised-model results, labeling procedure, calibration and limitations. Check that the report accurately describes the model. |
| P4 | Finalize combination and ablation results. Explain gains, failures, trade-offs and whether added cost is justified. |
| P5 | Assemble and edit the complete report, including failure taxonomy and comparative discussion. |
| P6 | Finalize TCR@k curves, HITL Load, cost tables and escalation-value analysis. Cross-check figures against saved results. |
| P7 | Finalize provenance section and representative trajectories. Check that safety claims are supported by execution traces. |

> **Deadlines:** Finish all runs by **Oct 24, 2026**, the full report by **Oct 25, 2026** and final checks by **Oct 26, 2026**. Reserve **Oct 27, 2026** for submission and genuine last-minute fixes.

---

## Coordination and decision checkpoints

One shared AgentDojo setup is sufficient. P1 owns the integration; everyone can run the same repository independently. Sample inputs and dummy outputs let implementation proceed before models are trained.

| Shared contract | Responsibility |
|----------------|---------------|
| **Policy interface** | `evaluate(context, state) → decision, updated_state`. All owners use the same interface. |
| **Policy input and output** | Visible task/trajectory, proposed call, metadata and remaining budget; return `approve`, `deny` or `escalate`, a reason and optional scores. Keep task-scoped state. |
| **Shared runner — P1** | Execute approved calls; invoke the reviewer; count escalations; deny escalation-worthy calls once *k* is exhausted; return denial feedback; record costs and reviewer outcomes; reset state between tasks. |
| **Evaluation — P6 with owners** | Use common tasks, agent/reviewer settings and budgets. Keep benchmark labels hidden from policies/reviewer. Reserve held-out data before tuning and rerun trajectories per policy for final evaluation. |

Each owner supplies: what the method catches; legitimate calls it blocks; unsafe calls it misses; its cost; and a complementary method. P5 consolidates failure patterns, P6 quantifies trade-offs, and P1/P4 select and implement the combination.

Start with two complementary methods. Add a third only when development results justify it. Avoid requiring P2/P3 to retrain solely for the combination without a demonstrated need.
