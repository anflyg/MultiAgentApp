# MultiAgentApp

En enkel lokal multi-agent-app med Pydantic-modeller, SQLite-persistence och en orchestrator som kan routea uppgifter till namngivna agenter. Innehaller CLI och en Textual-baserad leadership dashboard.

## Kom igang

1. Aktivera venv (fran projektroten):
   - macOS/Linux: `source .venv/bin/activate`
   - Windows (PowerShell): `.venv\\Scripts\\Activate.ps1`
2. Uppgradera pip (frivilligt men rekommenderas): `python -m pip install --upgrade pip`
3. Installera beroenden: `pip install -r requirements.txt`

## CLI

- Demo-flode (oforandrat):
  - `python src/main.py`
- Alpha demo-setup (snabbaste vagen till meningsfull paneloutput):
  - `python src/main.py --db-path alpha_demo.db alpha-demo-setup`
  - Kommandot skapar en demosession, seedar beslut/candidate och kor en panelfraga.
  - Efter korning far du direkt forslag pa nasta kommandon (show-panel-question, list-panel-questions, tui).
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

## TUI (Textual leadership dashboard)

- Starta TUI via CLI:
  - `python src/main.py tui --db-path multi_agent.db`
- Alternativt direkt:
  - `python -m multi_agent_app.tui --db-path multi_agent.db`

Dashboarden visar vid start:
- summary/metrics:
  - active decisions
  - open decision candidates
  - open decision suggestions
  - senaste session-events (senaste 10)
- active decisions-lista
- open decision candidates
- open decision suggestions
- recent activity
- decision detail-panel for vald aktivt beslut (inklusive inkommande/utgaende links)
- ask-panel-sektion (topic + question) som kor befintlig decision-panel-logik

I dashboarden kan du:
- refresha all oversikt-data
- valja ett aktivt beslut och se detaljer
- skriva topic + question och fa strukturerat panel-svar direkt i UI

I denna iteration sker fortfarande skapande/hantering via CLI:
- create/confirm/dismiss av candidates
- create/accept/dismiss av suggestions
- explicita link-operations

## Snabb demo fran tomt lage

1. Skapa demo-data och forsta panelresultat:
   - `python src/main.py --db-path alpha_demo.db alpha-demo-setup`
2. Visa sparad fraga med analys och reasoning:
   - `python src/main.py --db-path alpha_demo.db show-panel-question --question-id <ID_FRAN_STEG_1>`
3. Starta TUI med samma databas:
   - `python src/main.py --db-path alpha_demo.db tui`

Happy path i korthet:
1. setup: kor `alpha-demo-setup`
2. inspect: kor `show-panel-question` pa sparad fraga
3. explore: oppna `tui`
4. continue: ställ ny fraga via `ask-decision-panel` eller direkt i TUI

## Alpha readiness

- Se [ALPHA_CHECKLIST.md](ALPHA_CHECKLIST.md) for konkret "go/no-go" innan forsta alfa.

## Paketstruktur

- `src/multi_agent_app/models.py` - Pydantic-modeller for Session, Task, AgentAction, MemoryItem, SessionEvent.
- `src/multi_agent_app/storage.py` - SQLite-baserad persistence.
- `src/multi_agent_app/orchestrator.py` - Orchestrator som routear uppgifter till agenter och loggar livscykel/history.
- `src/multi_agent_app/cli.py` - CLI och exempelflode.
- `src/multi_agent_app/tui.py` - Textual-baserad leadership dashboard.
- `src/multi_agent_app/panel.py` - Deterministisk decision-panel-logik och alignment-bedomning.
- `src/main.py` - Entrypoint som vidarebefordrar till CLI.

## Tester

- Kor tester: `pytest`
- TUI smoke-test: om `textual` ar installerat kor den en minimal import/init-kontroll, annars skippas testet.
