# Parable frontend

React 19 + TypeScript + Vite. FastAPI serves the production bundle from `frontend/dist/`.

Development, from the repo root:

```bash
cd engine && PARABLE_MOCK_PAYPAL=1 PARABLE_DEMO_SEED=1 uv run uvicorn parable.api:app --port 8000
cd frontend && npm install && npm run dev
```

The dev server proxies `/api` and `/paypal` to `http://localhost:8000` (override with `PARABLE_API`).

`npm test` runs the Vitest suite and `npm run build` type-checks and bundles the site.
