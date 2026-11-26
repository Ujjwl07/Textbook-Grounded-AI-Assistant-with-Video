import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, dashboard, generation, health, query, quiz, videos
from app.core.config import get_settings
from app.services.database import DatabaseUnavailable, database


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.connect()
    yield
    await database.close()


settings = get_settings()


def _configure_app_logging() -> None:
    """Show INFO from the app's own modules in the server console.

    Nothing configures the root logger, so every ``logger.info`` under ``app.*``
    was dropped and the console showed only uvicorn's access lines. This gives
    just the ``app`` namespace a handler; third-party libraries stay at their
    default (WARNING) so their chatter does not bury the job's progress.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s - %(message)s")
    )
    # "textbook_assistant" is the Gemini client's logger: without it here, its
    # retry warnings and "Gemini is WORKING" lines never reach the console.
    for name in ("app", "textbook_assistant"):
        named = logging.getLogger(name)
        if named.handlers:
            continue
        named.addHandler(handler)
        named.setLevel(logging.INFO)
        named.propagate = False


_configure_app_logging()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

@app.exception_handler(DatabaseUnavailable)
async def database_unavailable(request: Request, exc: DatabaseUnavailable) -> JSONResponse:
    """MongoDB is down or restarting: a clear, retryable 503 instead of a 500 crash.

    The backend reconnects by itself once MongoDB is back (see database._ensure_db),
    and the frontend's account loader retries 5xx responses.
    """
    logging.getLogger(__name__).warning("Database unavailable for %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is temporarily unavailable. Please try again in a moment."},
        headers={"Retry-After": "5"},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix=settings.api_prefix)
app.include_router(auth.router, prefix=settings.api_prefix)
app.include_router(query.router, prefix=settings.api_prefix)
app.include_router(generation.router, prefix=settings.api_prefix)
app.include_router(videos.router, prefix=settings.api_prefix)
app.include_router(quiz.router, prefix=settings.api_prefix)
app.include_router(dashboard.router, prefix=settings.api_prefix)
