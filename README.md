# Footnote

*The real story is always in the footnotes.*

🌐 **[Public Preview](https://ftn-web.kindforest-80fae3b1.westeurope.azurecontainerapps.io/#/)**

Track security-relevant changes in documentation repositories. Starting with [Azure Docs](https://github.com/MicrosoftDocs/azure-docs), Footnote monitors commits, scores them for security impact using LLMs, and serves the results through a searchable web interface.

## Why

Microsoft frequently updates Azure documentation to reflect changes in default behaviors, permission models, and security features — often without a security advisory. Footnote catches what doesn't make headlines.

## Stack

- **Scanner:** Python + GitPython — clone, diff, pre-filter noise
- **Scorer:** Tiered LLM pipeline — local pre-filter → structured dimension classification → deterministic score
- **Pipeline:** Calls the API's ingest endpoints (bearer token auth) — no direct DB access
- **API:** FastAPI + SQLite — sole database writer; serves both public read endpoints and authenticated ingest endpoints
- **Frontend:** Svelte
- **Infra:** Docker Compose / Azure Container Apps

## Scoring

Footnote uses a structured, explainable scoring framework inspired by CVSS. Instead of asking an LLM for a holistic 0-10 number, we have the LLM classify six dimensions:

| Dimension | Type | Max Points |
|-----------|------|------------|
| Confidentiality | boolean | 1 |
| Integrity | boolean | 1 |
| Availability | boolean | 1 |
| Change nature | cosmetic / clarification / new_feature / behavior_change / critical | 0-4 |
| Actionability | none / recommended / required | 0-2 |
| Broad scope | boolean | 1 |

The final score is computed deterministically from these dimensions (normalized to 0-10). This means:
- Scores are **explainable** — you can see exactly which dimensions drove the rating
- Scores are **consistent** across LLM models — the model classifies, Python computes
- The framework is **extensible** — add/remove/reweight dimensions in `scorer/scoring_criteria.yaml` without changing code

See `scorer/scoring_criteria.yaml` for the full definition and `scorer/test_cases/` for calibration examples from real Azure security incidents.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your API keys and set INGEST_TOKEN
docker compose up --build
```

### Run the scorer pipeline

The pipeline calls the API's ingest endpoints (no direct DB access). It requires `INGEST_TOKEN` to authenticate:

```bash
docker compose run --rm --build -e BACKFILL_DAYS=30 -e CLONE_DEPTH=2000 pipeline
```

## Development

### Seed the database with test data

After starting the stack, load sample changes to test the UI without running the full pipeline:

```bash
docker compose cp seed.py api:/app/seed.py && docker compose exec api python /app/seed.py
```

This inserts 8 sample changes across Azure, AWS, and GCP docs with varied scores, risk levels, tags, and affected services.

## Inspiration

This project was inspired by [Liad Eliyahu's talk at CloudSec Berlin 2025](https://www.youtube.com/watch?v=EQLyD9ZdQIk) on monitoring cloud documentation for security-relevant changes.

## License

MIT
