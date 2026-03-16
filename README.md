# MultiAgentApp

En enkel lokal multi-agent-app med Pydantic-modeller, SQLite-persistence och en orchestrator som kan routea uppgifter till namngivna agenter. Innehaller CLI och en minimal Textual-baserad TUI.

## Kom igang

1. Aktivera venv (fran projektroten):
   - macOS/Linux: `source .venv/bin/activate`
   - Windows (PowerShell): `.venv\\Scripts\\Activate.ps1`
2. Uppgradera pip (frivilligt men rekommenderas): `python -m pip install --upgrade pip`
3. Installera beroenden: `pip install -r requirements.txt`

## CLI

- Demo-flode (oforandrat):
  - `python src/main.py`
- Skapa session:
  - `python src/main.py create-session --name "My Session"`
- Lagga till task:
  - `python src/main.py add-task --session-id <session_id> --description "Do work"`
- Lista tasks:
  - `python src/main.py list-tasks --session-id <session_id>`
- Route task:
  - `python src/main.py route-task --task-id <task_id> --agent writer`
- Run task (Sprint B explicit command):
  - `python src/main.py run-task --task-id <task_id> --agent writer`
- Sessionsstatus:
  - `python src/main.py session-status --session-id <session_id>`
- Show session (status + tasks + history):
  - `python src/main.py show-session --session-id <session_id>`
- Sessionshistorik:
  - `python src/main.py session-history --session-id <session_id>`

## TUI (Textual)

- Starta TUI via CLI:
  - `python src/main.py tui --db-path multi_agent.db`
- Alternativt direkt:
  - `python -m multi_agent_app.tui --db-path multi_agent.db`

I TUI:n kan du:
- lista sessions
- valja en session
- se tasks och sessionhistorik
- routea vald task till vald agent

## Paketstruktur

- `src/multi_agent_app/models.py` - Pydantic-modeller for Session, Task, AgentAction, MemoryItem, SessionEvent.
- `src/multi_agent_app/storage.py` - SQLite-baserad persistence.
- `src/multi_agent_app/orchestrator.py` - Orchestrator som routear uppgifter till agenter och loggar livscykel/history.
- `src/multi_agent_app/cli.py` - CLI och exempelflode.
- `src/multi_agent_app/tui.py` - Minimal Textual-baserad terminal UI.
- `src/main.py` - Entrypoint som vidarebefordrar till CLI.

## Tester

- Kor tester: `pytest`
- TUI smoke-test: om `textual` ar installerat kor den en minimal import/init-kontroll, annars skippas testet.
