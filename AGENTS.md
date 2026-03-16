# AGENTS

This project uses simple class-based agents under `src/multi_agent_app/agents.py`.

## Agent contract

- Inherit from `BaseAgent`.
- Implement `run(task: Task) -> str`.
- Keep output deterministic and concise when possible.
- Raise exceptions for unrecoverable failures so orchestrator can persist error actions.

## Built-in agents

- `WriterAgent`
- `ReviewerAgent`
- `PlannerAgent`

## Orchestration behavior

- Tasks are routed by name via `Orchestrator.route_task`.
- On success:
  - task status: `in_progress -> completed`
  - action persisted with `kind="result"`
  - memory persisted with `source_agent` and `task_id`
- On failure:
  - task status: `in_progress -> failed`
  - action persisted with `kind="error"`
  - `OrchestrationError` is raised

## Session lifecycle

- Session status is recomputed from tasks:
  - `failed` if any task failed
  - `completed` if all tasks are completed
  - `active` otherwise
- Session history is written to `session_events` and can be listed via CLI:
  - `python src/main.py --list-history <session_id>`
