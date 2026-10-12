# Actuvara BI – Angular frontend

Analytics dashboard + chatbot for the Actuvara (intellidoc) database. The sidebar switches
between the two views (and collapses to icons).

- **Dashboard** – KPI tiles (submissions, files, runs, success rate, failed runs, confidence,
  processing time), submissions per day by source, submissions by source, runs by status,
  top processes, file types and the latest submissions, for 7 / 30 / 90 days or all time.
- **Chatbot** – ask a question in plain English. The answer comes from the database as text
  plus charts generated for that question (bar, line, doughnut, KPI or table). Every chart has a
  Table toggle, and each answer lists the database queries behind it. The conversation is kept
  while you switch to the dashboard and back.

## Run

Start the backend first (see `../BI_Backend/README.md` → *BI API*):

```powershell
cd ..\BI_Backend
.\.venv\Scripts\Activate.ps1
uvicorn api_server:app --reload --port 8000
```

Then the frontend:

```powershell
npm install
npm start          # http://localhost:4200 – /api is proxied to :8000 (proxy.conf.json)
```

`npm run build` writes a production build to `dist/bi-analytics`. When it is served from
another origin, add that origin to `CORS_ORIGINS` in the backend `.env`.

## Structure

| Path | What |
|---|---|
| `src/app/app.*` | Shell: sidebar (Dashboard / Chatbot toggle, collapse, API status) |
| `src/app/pages/dashboard.ts` | Dashboard page |
| `src/app/pages/chat.ts` | Chatbot page |
| `src/app/shared/chart-card.ts` | Renders any backend chart spec with Chart.js (plus table/KPI views) |
| `src/app/core/` | API service, chat state, types |
| `src/styles.scss` | Design tokens, light and dark |
