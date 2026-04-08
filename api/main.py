"""
Footnote API — FastAPI backend for browsing scored documentation changes.
"""

import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import Database

app = FastAPI(
    title="Footnote",
    description="Security-relevant documentation change tracker",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.environ.get("DB_PATH", "/data/db/footnote.db")


def get_db() -> Database:
    return Database(DB_PATH)


@app.get("/")
def root():
    return {"name": "Footnote", "version": "0.1.0", "status": "ok"}


@app.get("/changes")
def list_changes(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    min_score: float = Query(0, ge=0, le=10),
    tag: Optional[str] = None,
    repo: Optional[str] = None,
    risk_level: Optional[str] = None,
    search: Optional[str] = None,
):
    db = get_db()
    try:
        changes = db.get_changes(
            limit=limit, offset=offset, min_score=min_score,
            tag=tag, repo=repo, risk_level=risk_level, search=search,
        )
        return {"changes": changes, "count": len(changes), "offset": offset, "limit": limit}
    finally:
        db.close()


@app.get("/changes/{change_id}")
def get_change(change_id: int):
    db = get_db()
    try:
        change = db.get_change(change_id)
        if not change:
            raise HTTPException(status_code=404, detail="Change not found")
        return change
    finally:
        db.close()


@app.get("/tags")
def list_tags():
    db = get_db()
    try:
        return {"tags": db.get_tags()}
    finally:
        db.close()


@app.get("/services")
def list_services():
    db = get_db()
    try:
        return {"services": db.get_services()}
    finally:
        db.close()


@app.get("/stats")
def get_stats():
    db = get_db()
    try:
        return db.get_stats()
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
