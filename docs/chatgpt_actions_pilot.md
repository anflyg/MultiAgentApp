# ChatGPT Actions Pilot (Package 7)

This guide describes the first real pilot connection between a Custom GPT and the local memory API.

## 1) Start the API locally (SocratesTest.db)

```bash
cd /Users/andersflygare/Documents/Python/MultiAgentApp
export MULTI_AGENT_APP_API_TOKEN="replace-with-your-local-token"
python3 src/main.py --db-path ./SocratesTest.db serve-memory-api --host 127.0.0.1 --port 8001
```

Expected startup line:

`Starting memory API on http://127.0.0.1:8001 (db=./SocratesTest.db, auth=on)`

## 2) Sanity-check API manually

Health:

```bash
curl -s "http://127.0.0.1:8001/health" \
  -H "Authorization: Bearer $MULTI_AGENT_APP_API_TOKEN"
```

Memory orientation:

```bash
curl -s -X POST "http://127.0.0.1:8001/memory/orient" \
  -H "Authorization: Bearer $MULTI_AGENT_APP_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"Hur bör vi tänka kring expansion i Norge nästa år?","limit":3}'
```

Memory search:

```bash
curl -s -X POST "http://127.0.0.1:8001/memory/search" \
  -H "Authorization: Bearer $MULTI_AGENT_APP_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"norge expansion","limit":5}'
```

## 3) Expose local API via public HTTPS tunnel

Use your preferred tunnel tool. Example with ngrok:

```bash
ngrok http 8001
```

Example tunnel base URL:

`https://abc12345.ngrok-free.app`

## 4) OpenAPI file for Actions

Use:

`openapi/memory_api.openapi.json`

Before importing into Custom GPT Actions, make sure server URL points to your current tunnel URL.

If needed, update `servers` in the OpenAPI file to your active tunnel host.

## 5) Import in Custom GPT (Actions)

1. Open GPT builder and go to `Actions`.
2. Import OpenAPI schema from `openapi/memory_api.openapi.json`.
3. Set Authentication to bearer token and use the same token as `MULTI_AGENT_APP_API_TOKEN`.
4. Confirm actions include:
   - `getHealth`
   - `postMemoryCreate`
   - `postMemoryOrient`
   - `postMemorySearch`
   - `getMemoryById`

## 6) First recommended GPT pilot calls

In GPT chat:

1. "Run health check on the memory API."
2. "Orient this question: Hur bör vi tänka kring expansion i Norge nästa år?"
3. "Search memory for norge expansion and summarize top hits."
4. "Create a memory with title 'Norge expansion 2027' in workspace <id>."

## Notes / current limitations

- This is a thin local pilot surface, not production deployment.
- Auth is intentionally simple bearer-token validation.
- Memory update/delete endpoints are not included in this pilot.
