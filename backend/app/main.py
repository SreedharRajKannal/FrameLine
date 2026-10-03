"""
main.py – FastAPI application entry-point.
Owned by Sreedhar.

Each teammate's router is imported inside try/except ImportError so that
a missing or broken module never prevents the app from starting.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app import config, store

app = FastAPI(title="Frameline API", version="0.1.0")

# ---------------------------------------------------------------------------
# CORS – allow the Vite dev server
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# DB init on startup + Meetily poller
# ---------------------------------------------------------------------------
@app.on_event("startup")
def on_startup() -> None:
    store.init_db()


@app.on_event("startup")
async def start_meetily_poller() -> None:
    """Start the Meetily polling loop if Meetily is configured."""
    if config.MEETILY_API_KEY:
        from backend.app.meetily_poller import start_poller
        start_poller()


@app.on_event("shutdown")
async def stop_meetily_poller() -> None:
    """Gracefully stop the Meetily poller."""
    try:
        from backend.app.meetily_poller import stop_poller
        stop_poller()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Sreedhar's router (always present)
# ---------------------------------------------------------------------------
from backend.app.routers import review  # noqa: E402
app.include_router(review.router, prefix="/api")


# ---------------------------------------------------------------------------
# Karthik's routers (optional – won't crash if not yet implemented)
# ---------------------------------------------------------------------------
try:
    from backend.app.routers import ingest
    app.include_router(ingest.router, prefix="/api")
except ImportError:
    pass

try:
    from backend.app.routers import export as export_router
    app.include_router(export_router.router, prefix="/api")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Sivapriyan's routers (optional)
# ---------------------------------------------------------------------------
try:
    from backend.app.routers import privacy
    app.include_router(privacy.router, prefix="/api")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Video indexing & Vision router (Phase 2 & 3)
# ---------------------------------------------------------------------------
try:
    from backend.app.routers import video as video_router
    app.include_router(video_router.router, prefix="/api")
except ImportError:
    pass

try:
    from backend.app.routers import vision as vision_router
    app.include_router(vision_router.router, prefix="/api")
except ImportError:
    pass

# Mount static preview files directory
from pathlib import Path
from fastapi.staticfiles import StaticFiles

previews_path = Path("data/previews")
previews_path.mkdir(parents=True, exist_ok=True)
app.mount("/data/previews", StaticFiles(directory=str(previews_path)), name="previews")

