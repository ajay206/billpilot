"""Serve the built persona UI from the API process.

The Vite build writes web/dist. When that directory is present, `/` is the
app and unknown paths fall back to index.html. API routes stay on their own
paths. A checkout without a build keeps the JSON root, which is what tests use.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

_API_PREFIXES = ("tmf-api/", "ops/", "agent/", "knowledge/", "docs", "redoc")


def ui_dist() -> Path:
    """Built files for the persona UI.

    A source checkout keeps `web/dist` two levels above this file. The Docker
    image installs the package and copies the build to `/app/web/dist`, which
    is the working directory, not a neighbour of site-packages.
    """
    checkout = Path(__file__).resolve().parents[2] / "web" / "dist"
    if (checkout / "index.html").is_file():
        return checkout
    working = Path.cwd() / "web" / "dist"
    if (working / "index.html").is_file():
        return working
    return checkout


def mount_ui(app: FastAPI, dist: Path | None = None) -> bool:
    root = (dist if dist is not None else ui_dist()).resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    @app.get("/", include_in_schema=False)
    def spa_root() -> FileResponse:
        return FileResponse(index)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "health" or full_path.startswith(_API_PREFIXES) or full_path == "openapi.json":
            raise HTTPException(status_code=404, detail="Not found.")
        candidate = (root / full_path).resolve()
        if candidate.is_file() and (candidate == root or root in candidate.parents):
            return FileResponse(candidate)
        return FileResponse(index)

    return True
