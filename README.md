# MultiAgentApp (ChatGPT-first Memory Backend)

MultiAgentApp is now a thin backend for ChatGPT Actions:

Custom GPT -> Actions -> local HTTP API -> SQLite long-term memory

## What remains in the core

- SQLite persistence for long-term memory (`storage.py`)
- Generic memory model (`memory_core.py`)
- Memory retrieval (`memory_retrieval.py`)
- Memory orientation (`memory_orientation.py`)
- Thin HTTP API (`api_server.py`)
- OpenAPI contract for Actions (`openapi/memory_api.openapi.json`)
- Minimal CLI to:
  - run orientation once (`memory-orient`)
  - start the local API (`serve-memory-api`)

## Quick start

Install:

```bash
cd /Users/andersflygare/Documents/Python/MultiAgentApp
python3 -m pip install -e '.[dev]'
```

Run API against `SocratesTest.db`:

```bash
cd /Users/andersflygare/Documents/Python/MultiAgentApp
export MULTI_AGENT_APP_API_TOKEN="replace-with-your-local-token"
python3 src/main.py --db-path ./SocratesTest.db serve-memory-api --host 127.0.0.1 --port 8001
```

One-off orientation via CLI:

```bash
python3 src/main.py --db-path ./SocratesTest.db memory-orient \
  --question "Hur bör vi tänka kring expansion i Norge nästa år?" \
  --limit 3
```

## API endpoints

- `GET /health`
- `POST /memory`
- `POST /memory/orient`
- `POST /memory/search`
- `GET /memory/{id}`

See full contract:

- `openapi/memory_api.openapi.json`

## Custom GPT pilot guide

Step-by-step setup for tunnel + Actions import + first pilot calls:

- `docs/chatgpt_actions_pilot.md`

## Tests

Run the retained core suite:

```bash
cd /Users/andersflygare/Documents/Python/MultiAgentApp
python3 -m pytest
```

## Windows 10 quick start

Install once:

1. Python 3.11+ (and check "Add python.exe to PATH")
2. ngrok (install + `ngrok config add-authtoken <DIN_TOKEN>`)
3. Project dependencies:

```powershell
cd C:\path\to\MultiAgentApp
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Start local API + ngrok (robust startup + health checks):

```powershell
cd C:\path\to\MultiAgentApp
.\start_socrates_local.ps1
```

or:

```cmd
start_socrates_local.cmd
```

Stop:

```powershell
.\stop_socrates_local.ps1
```

or:

```cmd
stop_socrates_local.cmd
```
