"""
Serves the precomputed visualization data and the static frontend.
Run with: uvicorn viz.server:app --reload --port 8080
Then open http://localhost:8080 in a browser.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

app = FastAPI(title="Satellite Mesh Visualization")

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "frontend")


@app.get("/")
def index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))


@app.get("/viz_data.json")
def viz_data():
    return FileResponse(os.path.join(FRONTEND_DIR, "viz_data.json"))


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
