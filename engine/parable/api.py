import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from parable import identity, market, runs, webhooks
from parable.api_support import install_error_handlers
from parable.config import REPO_ROOT, get_settings, is_production, startup_problems
from parable.guard import RequestGuard, script_hashes
from parable.db import get_db
from parable.paypal_routes import router as paypal_router
from parable.routes_agents import router as agents_router
from parable.routes_lab import router as lab_router
from parable.routes_market import router as market_router
from parable.routes_purchases import router as purchases_router
from parable.routes_runs import router as runs_router
from parable.seed import seed_demo

log = logging.getLogger("parable.app")

FRONTEND_DIST = REPO_ROOT / "frontend" / "dist"
NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate"}
BUILD_HINT = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Parable</title></head>
<body style="font-family: system-ui, sans-serif; max-width: 480px; margin: 48px auto; padding: 0 16px">
<h1>Parable API is running</h1>
<p>The frontend is not built yet. Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>.</p>
</body></html>"""


def start_services():
    problems = startup_problems()
    if problems:
        raise RuntimeError("; ".join(problems))
    identity.secret_key()
    get_db()
    if get_settings().parable_demo_seed:
        log.info("seeded %s demo listings", seed_demo())
    manager = runs.get_manager()
    market.install(manager)
    manager.resume()
    manager.start_poller()
    market.settle_pending()
    market.ensure_tracks()
    return manager, market.start_cancel_loop()


def stop_services(manager: runs.RunManager, stop_cancel_loop) -> None:
    stop_cancel_loop.set()
    manager.shutdown()


def register_frontend(app: FastAPI, dist: Path) -> None:
    index = dist / "index.html"

    @app.get("/", include_in_schema=False)
    def home():
        if index.is_file():
            return FileResponse(index, headers=NO_CACHE)
        return HTMLResponse(BUILD_HINT)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")


def inline_hashes(dist: Path) -> list[str]:
    index = dist / "index.html"
    return script_hashes(index.read_text(encoding="utf-8")) if index.is_file() else []


def create_app(dist: Path = FRONTEND_DIST) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        manager, stop_cancel_loop = start_services()
        yield
        stop_services(manager, stop_cancel_loop)

    docs = {} if not is_production() else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="Parable", lifespan=lifespan, **docs)
    install_error_handlers(app)
    for router in (identity.router, webhooks.router, lab_router, agents_router, market_router, purchases_router,
                   runs_router, paypal_router):
        app.include_router(router)
    register_frontend(app, dist)
    app.add_middleware(RequestGuard, hashes=inline_hashes(dist))
    return app


app = create_app()
