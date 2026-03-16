# MultiAgentApp

En enkel lokal multi-agent-app med Pydantic-modeller, SQLite-persistence och en orchestrator som kan routea uppgifter till namngivna agenter. Innehåller CLI-exempelflöde och pytest-tester.

## Kom igång

1. Aktivera venv (från projektroten):
   - macOS/Linux: `source .venv/bin/activate`
   - Windows (PowerShell): `.venv\\Scripts\\Activate.ps1`
2. Uppgradera pip (frivilligt men rekommenderas): `python -m pip install --upgrade pip`
3. Installera beroenden: `pip install -r requirements.txt`
4. Kör demo-flödet:
   - `python src/main.py`
   - Anpassa vid behov: `python src/main.py --session-name "Mitt pass" --task "Planera release" --agent planner`

## Paketstruktur

- `src/multi_agent_app/models.py` – Pydantic-modeller för Session, Task, AgentAction, MemoryItem.
- `src/multi_agent_app/storage.py` – SQLite-baserad persistence.
- `src/multi_agent_app/orchestrator.py` – Orchestrator som routear uppgifter till agenter och loggar deras actions/minnen.
- `src/multi_agent_app/cli.py` – CLI och exempelflöde.
- `src/main.py` – Entrypoint som bara vidarebefordrar till CLI.

## Tester

- Kör tester: `pytest`
- Tester finns i `tests/` och täcker modeller/persistence, orchestrator-routing och demo-flödet.
