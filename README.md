# Footnote

*The real story is always in the footnotes.*

Track security-relevant changes in documentation repositories. Starting with [Azure Docs](https://github.com/MicrosoftDocs/azure-docs), Footnote monitors commits, scores them for security impact using LLMs, and serves the results through a searchable web interface.

## Why

Microsoft frequently updates Azure documentation to reflect changes in default behaviors, permission models, and security features — often without a security advisory. Footnote catches what doesn't make headlines.

## Stack

- **Scanner:** Python + GitPython — clone, diff, pre-filter noise
- **Scorer:** Tiered LLM pipeline — local pre-filter → cloud for high-signal
- **API:** FastAPI + SQLite
- **Frontend:** Svelte
- **Infra:** Docker Compose

## Quick Start

```bash
cp .env.example .env
# Edit .env with your API keys
docker compose up --build
```

## Status

🚧 Under construction — Phase 1 prototype.

## License

MIT
