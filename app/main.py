from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.utils.logger import logger
from app.database import check_mongo_connection
from app.config import FastAPIConfig, CorsConfig, ENV
from app.scheduler import start_scheduler, stop_scheduler
from app.services.plays import ensure_indexes

from app.routers.healthcheck.endpoints import router as healthcheck_router
from app.routers.auth.endpoints import router as auth_router
from app.routers.spotify.endpoints import router as spotify_router
from app.routers.dashboard.endpoints import router as dashboard_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    """
    Lifespan context for application startup and shutdown.
    """
    if ENV.startswith("dev"):
        logger.warning("Running in development mode!")

    # Check database connection and run setup
    await check_mongo_connection(on_ready=ensure_indexes)

    # Start scheduler
    start_scheduler()

    yield  # Application is running

    # Shutdown scheduler
    stop_scheduler()


# Initialize FastAPI application
app = FastAPI(**FastAPIConfig.dict(), lifespan=lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CorsConfig.origins,
    allow_credentials=CorsConfig.allow_credentials,
    allow_methods=CorsConfig.allow_methods,
    allow_headers=CorsConfig.allow_headers,
    max_age=CorsConfig.max_age,
)

# Static assets
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Routers
app.include_router(healthcheck_router)
app.include_router(auth_router)
app.include_router(spotify_router)
app.include_router(dashboard_router)
