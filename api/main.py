"""
Footnote API — FastAPI backend for browsing scored documentation changes.

Public endpoints serve the frontend (read-only).
Ingest endpoints (/ingest/*) are protected by bearer token auth
and are called by the pipeline to write data.
"""

import os
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from database import Database

app = FastAPI(
    title="Footnote",
    description="Security-relevant documentation change tracker",
    version="0.2.0",
)

DB_PATH = os.environ.get("DB_PATH", "/data/db/footnote.db")
INGEST_TOKEN = os.environ.get("INGEST_TOKEN")

security = HTTPBearer()


def verify_ingest_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Verify bearer token for ingest endpoints."""
    if not INGEST_TOKEN:
        raise HTTPException(status_code=503, detail="Ingest token not configured on server")
    if credentials.credentials != INGEST_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid ingest token")
    return credentials.credentials


def get_db() -> Database:
    return Database(DB_PATH)


@app.get("/health")
def health_check():
    return {"status": "ok"}


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
    service: Optional[str] = None,
):
    db = get_db()
    try:
        changes = db.get_changes(
            limit=limit, offset=offset, min_score=min_score,
            tag=tag, repo=repo, risk_level=risk_level, search=search,
            service=service,
        )
        return {"changes": changes, "count": len(changes), "offset": offset, "limit": limit}
    finally:
        db.close()


@app.get("/changes/hash/{commit_hash}")
def get_change_by_hash(commit_hash: str):
    db = get_db()
    try:
        change = db.get_change_by_hash(commit_hash)
        if not change:
            raise HTTPException(status_code=404, detail="Change not found")
        return change
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


# ── Ingest endpoints (called by pipeline, protected by bearer token) ──


@app.post("/ingest/scan", dependencies=[Depends(verify_ingest_token)])
def create_scan(repo: str, commit_hash: str, commits_found: int = 0, commits_scored: int = 0):
    """Create a scan record. Returns the scan ID."""
    db = get_db()
    try:
        scan_id = db.create_scan(
            repo=repo,
            commit_hash=commit_hash,
            commits_found=commits_found,
            commits_scored=commits_scored,
        )
        return {"scan_id": scan_id}
    finally:
        db.close()


@app.get("/ingest/last_scan", dependencies=[Depends(verify_ingest_token)])
def get_last_scan(repo: str):
    """Get the last scanned commit hash for a repo."""
    db = get_db()
    try:
        commit_hash = db.get_last_scan_hash(repo)
        return {"commit_hash": commit_hash}
    finally:
        db.close()


@app.get("/ingest/has_change", dependencies=[Depends(verify_ingest_token)])
def check_has_change(commit_hash: str):
    """Check if a commit has already been scored."""
    db = get_db()
    try:
        exists = db.has_change(commit_hash)
        return {"exists": exists}
    finally:
        db.close()


@app.post("/ingest/change", dependencies=[Depends(verify_ingest_token)])
def insert_change(scan_id: int, change: dict):
    """Insert a scored change. Returns the change ID or null if duplicate."""
    db = get_db()
    try:
        change_id = db.insert_change(scan_id, change)
        return {"change_id": change_id}
    finally:
        db.close()


@app.patch("/ingest/scan/{scan_id}", dependencies=[Depends(verify_ingest_token)])
def update_scan(scan_id: int, commits_found: int, commits_scored: int):
    """Update a scan record with final counts."""
    db = get_db()
    try:
        db.update_scan(scan_id, commits_found=commits_found, commits_scored=commits_scored)
        return {"status": "ok"}
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("API_HOST", "0.0.0.0")
    port = int(os.environ.get("API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
