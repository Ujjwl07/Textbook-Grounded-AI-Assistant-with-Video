from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, dashboard, generation, health, quiz, videos
from app.core.config import get_settings
from app.services.cache_manager import cache_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    await cache_manager.connect()
    yield
    await cache_manager.close()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
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
app.include_router(generation.router, prefix=settings.api_prefix)
app.include_router(videos.router, prefix=settings.api_prefix)
app.include_router(quiz.router, prefix=settings.api_prefix)
app.include_router(dashboard.router, prefix=settings.api_prefix)
