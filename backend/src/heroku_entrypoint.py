from pathlib import Path

from fastapi.staticfiles import StaticFiles

from .entrypoint import app


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Remove the existing root health route.
# /api/health remains available.
app.router.routes[:] = [
    route
    for route in app.router.routes
    if getattr(route, "path", None) != "/"
]

# Register static files after all API and WebSocket routes.
app.mount(
    "/",
    StaticFiles(directory=STATIC_DIR, html=True),
    name="frontend",
)
