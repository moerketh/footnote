"""
Footnote Database — SQLite storage for scans and scored changes.
"""

import json
import sqlite3
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("footnote.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    commits_found INTEGER DEFAULT 0,
    commits_scored INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER REFERENCES scans(id),
    repo_name TEXT NOT NULL,
    commit_hash TEXT NOT NULL UNIQUE,
    commit_date DATETIME,
    commit_message TEXT,
    author TEXT,
    files_changed TEXT,
    diff_summary TEXT,
    diff_full TEXT,
    score REAL DEFAULT 0,
    risk_level TEXT DEFAULT 'informational',
    summary TEXT,
    rationale TEXT DEFAULT '',
    scoring_details TEXT DEFAULT '{}',
    scored_by TEXT DEFAULT '',
    services TEXT,
    stats TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS change_tags (
    change_id INTEGER REFERENCES changes(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (change_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_changes_score ON changes(score DESC);
CREATE INDEX IF NOT EXISTS idx_changes_date ON changes(commit_date DESC);
CREATE INDEX IF NOT EXISTS idx_changes_risk ON changes(risk_level);
CREATE INDEX IF NOT EXISTS idx_changes_repo ON changes(repo_name);
CREATE INDEX IF NOT EXISTS idx_changes_hash ON changes(commit_hash);
CREATE INDEX IF NOT EXISTS idx_change_tags_tag ON change_tags(tag);
"""


class Database:
    def __init__(self, db_path: str = "/data/db/footnote.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA)
        # Migrate: add new columns if upgrading from older schema
        self._migrate_add_column("changes", "rationale", "TEXT DEFAULT ''")
        self._migrate_add_column("changes", "scoring_details", "TEXT DEFAULT '{}'")
        self._migrate_add_column("changes", "scored_by", "TEXT DEFAULT ''")
        self.conn.commit()

    def _migrate_add_column(self, table: str, column: str, col_type: str):
        """Add column if it doesn't exist (SQLite has no IF NOT EXISTS for columns)."""
        cursor = self.conn.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            log.info(f"Migrated: added {table}.{column}")

    def get_last_scan_hash(self, repo: str) -> Optional[str]:
        """Get the last scanned commit hash for a repo."""
        row = self.conn.execute(
            "SELECT commit_hash FROM scans WHERE repo = ? ORDER BY id DESC LIMIT 1",
            (repo,)
        ).fetchone()
        return row["commit_hash"] if row else None

    def has_change(self, commit_hash: str) -> bool:
        """Check if a commit has already been scored."""
        row = self.conn.execute(
            "SELECT 1 FROM changes WHERE commit_hash = ?", (commit_hash,)
        ).fetchone()
        return row is not None

    def create_scan(self, repo: str, commit_hash: str,
                    commits_found: int = 0, commits_scored: int = 0) -> int:
        """Record a scan event."""
        cur = self.conn.execute(
            "INSERT INTO scans (repo, commit_hash, commits_found, commits_scored) VALUES (?, ?, ?, ?)",
            (repo, commit_hash, commits_found, commits_scored)
        )
        self.conn.commit()
        return cur.lastrowid

    def update_scan(self, scan_id: int, commits_found: int, commits_scored: int):
        """Update scan record with final counts."""
        self.conn.execute(
            "UPDATE scans SET commits_found = ?, commits_scored = ? WHERE id = ?",
            (commits_found, commits_scored, scan_id)
        )
        self.conn.commit()

    def insert_change(self, scan_id: int, change: dict) -> Optional[int]:
        """Insert a scored change. Returns change ID or None if duplicate."""
        try:
            cur = self.conn.execute(
                """INSERT INTO changes
                   (scan_id, repo_name, commit_hash, commit_date, commit_message,
                    author, files_changed, diff_summary, diff_full, score,
                    risk_level, summary, rationale, scoring_details, scored_by, services, stats)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    scan_id,
                    change["repo_name"],
                    change["commit_hash"],
                    change["commit_date"],
                    change["commit_message"],
                    change["author"],
                    json.dumps(change["files_changed"]),
                    change["diff_text"][:5000],  # Summary (truncated)
                    change["diff_text"],           # Full diff
                    change["score"],
                    change["risk_level"],
                    change["summary"],
                    change.get("rationale", ""),
                    json.dumps(change.get("scoring_details", {})),
                    change.get("scored_by", ""),
                    json.dumps(change["services"]),
                    json.dumps(change["stats"]),
                )
            )
            change_id = cur.lastrowid

            # Insert tags
            for tag in change.get("tags", []):
                self.conn.execute(
                    "INSERT OR IGNORE INTO change_tags (change_id, tag) VALUES (?, ?)",
                    (change_id, tag)
                )

            self.conn.commit()
            return change_id
        except sqlite3.IntegrityError:
            log.debug(f"Duplicate commit: {change['commit_hash'][:8]}")
            return None

    def get_changes(self, limit: int = 50, offset: int = 0,
                    min_score: float = 0, tag: Optional[str] = None,
                    repo: Optional[str] = None,
                    risk_level: Optional[str] = None,
                    search: Optional[str] = None,
                    service: Optional[str] = None) -> list[dict]:
        """Query changes with filters."""
        query = "SELECT DISTINCT c.* FROM changes c"
        params = []
        joins = []
        wheres = []

        if tag:
            joins.append("JOIN change_tags ct ON ct.change_id = c.id")
            wheres.append("ct.tag = ?")
            params.append(tag)

        if min_score > 0:
            wheres.append("c.score >= ?")
            params.append(min_score)

        if repo:
            wheres.append("c.repo_name = ?")
            params.append(repo)

        if risk_level:
            wheres.append("c.risk_level = ?")
            params.append(risk_level)

        if search:
            wheres.append("(c.summary LIKE ? OR c.commit_message LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        if service:
            wheres.append('c.services LIKE ?')
            params.append(f'%"{service}"%')

        if joins:
            query += " " + " ".join(joins)
        if wheres:
            query += " WHERE " + " AND ".join(wheres)

        query += " ORDER BY c.commit_date DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        rows = self.conn.execute(query, params).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            d["files_changed"] = json.loads(d["files_changed"] or "[]")
            d["services"] = json.loads(d["services"] or "[]")
            d["stats"] = json.loads(d["stats"] or "{}")
            d["scoring_details"] = json.loads(d.get("scoring_details") or "{}")
            # Get tags
            tags = self.conn.execute(
                "SELECT tag FROM change_tags WHERE change_id = ?", (d["id"],)
            ).fetchall()
            d["tags"] = [t["tag"] for t in tags]
            # Don't include full diff in list view
            del d["diff_full"]
            results.append(d)
        return results

    def get_change_by_hash(self, commit_hash: str) -> Optional[dict]:
        """Get a single change by commit hash with full diff."""
        row = self.conn.execute("SELECT * FROM changes WHERE commit_hash = ?", (commit_hash,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["files_changed"] = json.loads(d["files_changed"] or "[]")
        d["services"] = json.loads(d["services"] or "[]")
        d["stats"] = json.loads(d["stats"] or "{}")
        d["scoring_details"] = json.loads(d.get("scoring_details") or "{}")
        tags = self.conn.execute(
            "SELECT tag FROM change_tags WHERE change_id = ?", (d["id"],)
        ).fetchall()
        d["tags"] = [t["tag"] for t in tags]
        return d

    def get_change(self, change_id: int) -> Optional[dict]:
        """Get a single change with full diff."""
        row = self.conn.execute("SELECT * FROM changes WHERE id = ?", (change_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["files_changed"] = json.loads(d["files_changed"] or "[]")
        d["services"] = json.loads(d["services"] or "[]")
        d["stats"] = json.loads(d["stats"] or "{}")
        d["scoring_details"] = json.loads(d.get("scoring_details") or "{}")
        tags = self.conn.execute(
            "SELECT tag FROM change_tags WHERE change_id = ?", (d["id"],)
        ).fetchall()
        d["tags"] = [t["tag"] for t in tags]
        return d

    def get_tags(self) -> list[dict]:
        """Get all tags with counts."""
        rows = self.conn.execute(
            "SELECT tag, COUNT(*) as count FROM change_tags GROUP BY tag ORDER BY count DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def get_services(self) -> list[dict]:
        """Get all affected services with counts."""
        rows = self.conn.execute("SELECT services FROM changes WHERE services != '[]'").fetchall()
        service_counts = {}
        for row in rows:
            for svc in json.loads(row["services"]):
                service_counts[svc] = service_counts.get(svc, 0) + 1
        return sorted(
            [{"service": k, "count": v} for k, v in service_counts.items()],
            key=lambda x: x["count"], reverse=True
        )

    def get_stats(self) -> dict:
        """Dashboard statistics."""
        total = self.conn.execute("SELECT COUNT(*) as n FROM changes").fetchone()["n"]
        avg_score = self.conn.execute("SELECT AVG(score) as avg FROM changes").fetchone()["avg"]
        by_risk = self.conn.execute(
            "SELECT risk_level, COUNT(*) as count FROM changes GROUP BY risk_level"
        ).fetchall()
        by_repo = self.conn.execute(
            "SELECT repo_name, COUNT(*) as count FROM changes GROUP BY repo_name"
        ).fetchall()
        return {
            "total_changes": total,
            "avg_score": round(avg_score or 0, 2),
            "by_risk_level": {r["risk_level"]: r["count"] for r in by_risk},
            "by_repo": {r["repo_name"]: r["count"] for r in by_repo},
        }

    def close(self):
        self.conn.close()
