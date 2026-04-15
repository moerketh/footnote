# Footnote — Project Plan

_The real story is always in the footnotes._
_Tracking security-relevant changes in documentation repositories._

## Overview

Monitor the `MicrosoftDocs/azure-docs` GitHub repository for commits that have security implications. Score each change with an LLM, tag it by category, and serve the results through a searchable web interface.

## Why This Matters

Microsoft frequently updates Azure documentation to reflect changes in default behaviors, permission models, service configurations, and security features. These changes are often not announced through security advisories but can have significant security implications. Footnote catches what Microsoft doesn't headline.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌──────────┐     ┌──────────┐
│   Scanner    │────▶│   Scorer    │────▶│ Pipeline │────▶│   API    │
│  (git diff)  │     │  (LLM tier) │     │ (HTTP)   │     │ (FastAPI) │
└─────────────┘     └─────────────┘     └──────────┘     └────┬─────┘
                                                              │
                                                        ┌─────┴─────┐
                                                        │  SQLite   │
                                                        └───────────┘
                                                              │
                                                        ┌─────┴─────┐
                                                        │   Web     │
                                                        │  (SPA)    │
                                                        └───────────┘
```

The pipeline is the sole writer to the database — it calls the API's authenticated `/ingest/*` endpoints via HTTP (bearer token). The API handles all SQLite access, eliminating lock contention.

### Components

#### 1. Scanner (`scanner/`)
- Clones/pulls `MicrosoftDocs/azure-docs` (shallow clone, main branch)
- On each run: `git log --since=<last_scan>` to get new commits
- For each commit: extract diff, file paths, commit message
- Pre-filter noise:
  - Skip commits that only touch locale/translation files
  - Skip pure formatting/whitespace changes
  - Skip commits with <3 lines changed in content files
  - Skip image-only commits
- Pass meaningful diffs to Scorer
- Store last scanned commit hash in DB

#### 2. Scorer (`scorer/`)
- **Tier 1 — Local pre-filter (Gemma 4):** Quick relevance check (0-10 score). Discard anything <3.
- **Tier 2 — Cloud scoring (Kimi/Opus):** Detailed analysis for score ≥3:
  - Security relevance score (0-10)
  - Category tags (multiple allowed)
  - Plain-English summary of what changed and why it matters
  - Affected Azure services
  - Risk assessment (informational / low / medium / high / critical)
- Scoring prompt engineered for security analyst perspective

#### 3. Categories/Tags
- `permission-change` — Role, RBAC, or access model changes
- `default-behavior` — Silent changes to default configurations
- `deprecation` — Service or feature retirements
- `new-security-feature` — New security capabilities
- `auth-change` — Authentication/authorization flow changes
- `network-change` — Networking, firewall, NSG changes
- `encryption` — Key management, encryption at rest/in transit
- `compliance` — Regulatory, compliance framework changes
- `api-breaking` — Breaking changes to APIs
- `silent-fix` — Documentation updated without announcement
- `identity` — Entra ID, managed identity, service principal changes
- `monitoring` — Logging, auditing, diagnostic changes

#### 4. API (`api/`)
- **FastAPI** with SQLite backend (sole database writer)
- Public read endpoints (served to frontend via nginx proxy):
  - `GET /changes` — paginated, filterable (by tag, score, date range, service)
  - `GET /changes/{id}` — single change detail with full diff
  - `GET /tags` — list all tags with counts
  - `GET /services` — list all affected services with counts
  - `GET /stats` — dashboard stats (total changes, avg score, trends)
  - `GET /feed` — RSS/Atom feed for high-score changes
- Authenticated ingest endpoints (called by pipeline, bearer token auth):
  - `POST /ingest/scan` — create a scan record
  - `GET /ingest/last_scan` — get last scan hash for a repo
  - `GET /ingest/has_change` — check if a commit was already scored
  - `POST /ingest/change` — insert a scored change
  - `PATCH /ingest/scan/{scan_id}` — update scan with final counts
- API is internal-only in Azure (no public ingress); nginx proxies public read endpoints

#### 5. Web Frontend (`web/`)
- Lightweight SPA (Svelte or HTMX — TBD)
- Features:
  - Dashboard with recent high-score changes
  - Filterable list view (tags, score range, date, service)
  - Detail view with diff rendering and LLM analysis
  - Search (full-text across summaries)
  - RSS feed link
  - Dark mode (because of course)

#### 6. Database Schema (SQLite)

```sql
CREATE TABLE scans (
    id INTEGER PRIMARY KEY,
    repo TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    commits_found INTEGER,
    commits_scored INTEGER
);

CREATE TABLE changes (
    id INTEGER PRIMARY KEY,
    scan_id INTEGER REFERENCES scans(id),
    commit_hash TEXT NOT NULL,
    commit_date DATETIME,
    commit_message TEXT,
    author TEXT,
    files_changed TEXT,  -- JSON array
    diff_summary TEXT,   -- truncated diff for display
    diff_full TEXT,      -- full diff (compressed?)
    score REAL,          -- 0-10 security relevance
    risk_level TEXT,     -- informational/low/medium/high/critical
    summary TEXT,        -- LLM-generated plain English summary
    services TEXT,       -- JSON array of affected Azure services
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(commit_hash)
);

CREATE TABLE change_tags (
    change_id INTEGER REFERENCES changes(id),
    tag TEXT NOT NULL,
    PRIMARY KEY (change_id, tag)
);

CREATE INDEX idx_changes_score ON changes(score DESC);
CREATE INDEX idx_changes_date ON changes(commit_date DESC);
CREATE INDEX idx_changes_risk ON changes(risk_level);
CREATE INDEX idx_change_tags_tag ON change_tags(tag);
```

## Infrastructure

### VM (Proxmox)
- **Name:** `webhost-01` (reusable for future web projects)
- **Type:** VM (not LXC — Docker works better in full VMs)
- **Resources:** 2 vCPU, 4GB RAM, 40GB disk
- **OS:** Debian 12
- **Software:** Docker, Docker Compose, git
- **Network:** Bridge to LAN, static IP on 192.168.7.x
- **Access:** SSH from Mycroft LXC + Thomas's workstation

### Docker Compose

```yaml
services:
  api:
    build: .
    command: python api/main.py
    ports:
      - "8000:8000"
    volumes:
      - db-data:/data/db
    environment:
      - DB_PATH=/data/db/footnote.db
      - INGEST_TOKEN=${INGEST_TOKEN:-dev-token}

  frontend:
    build:
      context: .
      dockerfile: Dockerfile.frontend
    ports:
      - "8080:80"
    depends_on:
      - api
    environment:
      - API_UPSTREAM=api:8000

  pipeline:
    build: .
    command: python pipeline.py
    volumes:
      - repo-data:/data/repos
    environment:
      - API_URL=http://api:8000
      - INGEST_TOKEN=${INGEST_TOKEN:-dev-token}
      - CLOUD_OLLAMA_URL=${CLOUD_OLLAMA_URL}
      - CLOUD_API_KEY=${CLOUD_API_KEY}
    profiles:
      - pipeline

volumes:
  repo-data:
  db-data:
```

## Scan Frequency

- **Initial backfill:** Last 30 days of commits (configurable)
- **Ongoing:** Every 6 hours (cron inside scanner container)
- **Manual trigger:** Via API endpoint or CLI

## Multi-Repo Support (Future)

The scanner is designed to work with any GitHub repo. Config file:

```json
{
  "repos": [
    {
      "url": "https://github.com/MicrosoftDocs/azure-docs",
      "branch": "main",
      "name": "azure-docs",
      "enabled": true
    },
    {
      "url": "https://github.com/MicrosoftDocs/entra-docs",
      "branch": "main",
      "name": "entra-docs",
      "enabled": false
    }
  ]
}
```

## Phases

### Phase 1 — Prototype (This Sprint)
- [ ] Create Proxmox VM (`webhost-01`)
- [ ] Install Docker + Docker Compose
- [ ] Build scanner: clone repo, extract diffs, pre-filter
- [ ] Build scorer: Gemma tier-1, basic prompt, SQLite storage
- [ ] Build API: FastAPI with core endpoints
- [ ] Build web: minimal list view with filtering
- [ ] Docker Compose everything
- [ ] First successful scan + score cycle

### Phase 2 — Polish
- [ ] Add tier-2 cloud scoring for high-signal changes
- [ ] Diff rendering in web UI (syntax highlighted)
- [ ] Full-text search
- [ ] RSS feed
- [ ] Dashboard with stats/trends
- [ ] Dark mode

### Phase 3 — Production
- [x] Authentication for ingest endpoints (bearer token)
- [ ] CI/CD pipeline (GitHub Actions → Docker registry → deploy)
- [ ] Proper secret management
- [ ] Rate limiting on API
- [ ] Cloud deployment option (Azure Container Apps)
- [ ] Multi-repo support enabled
- [ ] Monitoring/alerting for scan failures

## Budget Impact

- **VM resources:** From existing Proxmox host (free)
- **LLM costs:** Tier-1 local (free), Tier-2 cloud (~$5-15/month depending on volume)
- **GitHub API:** Free tier sufficient (unauthenticated: 60 req/hr, authenticated: 5000 req/hr)
- **Total estimated:** ~$10/month incremental

## Decisions Made

1. **Frontend:** Svelte (lightweight, fast)
2. **Discord integration:** Yes — auto-post score ≥7 changes to `#azure-drift` channel
3. **Domain:** IP:port for prototype, custom domain later
4. **Initial backfill:** 30 days
5. **CI/CD:** Not yet — build with Docker, add CI/CD when production-ready
6. **Multi-repo:** Designed in from day one, enabled later (Entra docs, CLI docs, etc.)
