import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from parable.errors import MarketError
from parable.identity import current_seller
from parable.paypal import PayPalError
from parable.referee import RefereeError, RunNotFound

log = logging.getLogger("parable.api")


def require_seller(request: Request) -> dict:
    seller = current_seller(request)
    if seller is None:
        raise HTTPException(401, "sign in with PayPal first")
    return seller


def public_run(run: dict) -> dict:
    return {key: value for key, value in run.items() if key != "rules_json"}


def failure(status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status)


def describe_validation(err: RequestValidationError) -> str:
    first = err.errors()[0]
    field = ".".join(str(part) for part in first["loc"] if part != "body")
    return f"{field}: {first['msg']}" if field else str(first["msg"])


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(MarketError)
    async def market_error(request: Request, err: MarketError):
        return failure(err.status, err.detail)

    @app.exception_handler(PayPalError)
    async def paypal_error(request: Request, err: PayPalError):
        log.warning("paypal call failed: %s", err.name)
        return failure(502, f"paypal: {err.name}")

    @app.exception_handler(RefereeError)
    async def referee_error(request: Request, err: RefereeError):
        return failure(409, err.reason)

    @app.exception_handler(RunNotFound)
    async def run_missing(request: Request, err: RunNotFound):
        return failure(404, "run not found")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, err: RequestValidationError):
        return failure(422, describe_validation(err))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, err: Exception):
        log.exception("unhandled error on %s", request.url.path)
        return failure(500, "internal error")
