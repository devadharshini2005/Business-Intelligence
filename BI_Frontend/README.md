# Actuvara BI – Angular frontend

Analytics dashboard + chatbot for the Actuvara (intellidoc) database. The sidebar switches
between the two views, collapses to icons, toggles light/dark theme and shows whether the
database and the chatbot are connected.

**Dashboard**
- KPI tiles: submissions, files, runs, success rate, failed runs, average confidence, processing time.
- Charts: submissions per day by source, submissions by source, runs by status, top processes,
  file types, latest submissions – for 7 / 30 / 90 days or all time.
- **Click a submission** to open a side panel with its files, runs, workflow progress and the
  steps that failed or await approval.
- **Ask AI** on any chart (or the box at the top) opens the chatbot with that question.
- Every chart's ⋯ menu: show as bars / horizontal bars / line / doughnut / table, download CSV or
  PNG, full screen.

**Chatbot**
- Ask in plain English; the answer is text **plus charts built from the database for that
  question** (bar, line, doughnut, KPI or table).
- Progress is shown live while the answer is built (each database step, then each chart).
- Suggested follow-up questions, Copy, Retry on errors and Stop while answering.
- Each answer lists the database steps (queries) behind it.
- The conversation survives switching pages and reloading (kept in this browser only).

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
| `src/app/shared/chart-card.*` | Renders any backend chart spec with Chart.js (type switch, table, CSV/PNG, full screen) |
| `src/app/shared/submission-panel.*` | Submission detail side panel |
| `src/app/core/` | API service (incl. streaming chat), chat state, theme, types |
| `src/styles.scss` | Design tokens, light and dark |
