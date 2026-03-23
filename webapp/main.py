"""FastAPI application entry point."""

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from webapp.database import init_app_db
from webapp.routes import auth, dashboard, troops

app = FastAPI(title="Scouting Troop Stats", version="1.0.0")

WEBAPP_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEBAPP_DIR / "static"
TEMPLATES_DIR = WEBAPP_DIR / "templates"

# Mount static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(troops.router)
app.include_router(dashboard.router)


@app.on_event("startup")
def startup():
    init_app_db()


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(str(TEMPLATES_DIR / "index.html"))


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return FileResponse(str(TEMPLATES_DIR / "index.html"))


@app.get("/register", response_class=HTMLResponse)
async def register_page():
    return FileResponse(str(TEMPLATES_DIR / "index.html"))


@app.get("/troop-setup", response_class=HTMLResponse)
async def troop_setup_page():
    return FileResponse(str(TEMPLATES_DIR / "index.html"))


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    return FileResponse(str(STATIC_DIR / "dashboard.html"))


@app.get("/manage", response_class=HTMLResponse)
async def manage_page():
    return FileResponse(str(TEMPLATES_DIR / "index.html"))
