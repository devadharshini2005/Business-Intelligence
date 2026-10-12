# Actuvara BI – Frontend (Angular)

Dashboard and AI assistant for the Actuvara IDP database. It talks only to the Python API in
`../BI_Backend/api_server.py`, which reads the database read-only.

| Page | What it shows |
|---|---|
| **Dashboard** | KPI cards (submissions, files, run success rate) with change vs the previous period; submissions overview (stacked by source with flow ribbons, daily / weekly / monthly columns for 7 / 30 / 90 days); runs or submissions by weekday; run distribution gauge; processes table (select rows to have the assistant compare them); workflow nodes that fail or wait for approval; latest submissions. Header: period, source filter, CSV export. The top search box (Ctrl + K) and every process / node row hand a question to the assistant. |
| **Submissions** | Search email / webhook / manual-upload submissions; click one for its files → runs → workflow nodes. |
| **Assistant** | Chat with the BI assistant (GPT-4.1 via Azure OpenAI, or Claude - whichever `BI_Backend/.env` configures). It answers from the database with read-only tools, attaches charts built from real query results, and lists the lookups it made. Chat history is kept in the browser. |
| **Data model** | Every collection with its size; click one to have the assistant explain it. |

## Run it

1. Start the API (see `../BI_Backend/README.md` → *BI dashboard API*):

   ```powershell
   cd ..\BI_Backend
   .\.venv\Scripts\python.exe -m uvicorn api_server:app --port 8000
   ```

2. Start the UI (Node 20+):

   ```powershell
   npm install
   npm start                                      # http://localhost:4200
   ```

   `proxy.conf.json` forwards `/api` to `http://127.0.0.1:8000`.

**Without the dev server:** `npm run build` writes the app to `dist/actuvara-bi/browser`, and the API server
serves it at http://127.0.0.1:8000/ (restart the API server after the first build).

## Code map

```
src/app/
  api.service.ts           HTTP client + streaming chat (NDJSON)
  models.ts / format.ts    API shapes, number/date/status helpers
  ui-state.service.ts      DB health, open submission drawer, questions handed to the assistant
  pages/                   overview, submissions, assistant, data-model
  shared/                  flow chart, weekday chart, gauge, submissions table, submission drawer, status badge, icons, markdown pipe
src/styles.css             design tokens (light + dark) and all component styles
```
