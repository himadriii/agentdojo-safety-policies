# AgentDojo Safety Policies

A group project to implement and evaluate safety approval policies for LLM agents using AgentDojo.

## Features
- Shared policy interface (`approve`, `deny`, `escalate`)
- Escalation budget enforcement
- Reviewer integration
- Baseline policies and automated tests

## Setup

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run Tests

```bash
python -m test.test_budget
python -m test.test_policy_interface
python -m test.test_agent_pipeline
```
