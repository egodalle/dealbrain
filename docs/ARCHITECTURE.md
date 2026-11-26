---
owner: architect
last-reviewed: 2026-11-26
stability: draft
---

# DealBrain Architecture

DealBrain is a second-brain and agent system for a real estate investor. It ingests public
property data and owner records, deduplicates and scores them, then surfaces leads through
a Hermes assistant (MCP) and a portal UI. **Nothing is sent to a contact without a human
approving the action in the portal.**

## Components

| Component | Path | Purpose |
|---|---|---|
| Portal | `apps/portal/` | Human-facing approval UI and dashboard |
| MCP server | `apps/mcp/` | Model Context Protocol server for Hermes |
| Pipelines | `pipelines/` | Public-data ingestion and ETL |
| Router | `router/` | Single gateway for all LLM calls |
| Brain | `brain/` | Dedupe, scoring, and lead prioritisation |
| Hermes skills | `hermes/skills/` | Assistant skill implementations |
| DB migrations | `db/migrations/` | Forward-only numbered SQL migrations |

## Data flow (sketch)

```
Public data sources
       |
   pipelines/   <-- fetch, normalise, dedupe
       |
   Postgres (pgvector)
       |
   brain/        <-- score, rank
       |
   pending_actions  <-- human approves
       |
   router/ --> LLM
       |
   hermes/ / portal/
```

## Key decisions

- See [ADR-0001](adr/0001-python-lint-and-compose-baseline.md) for Python version,
  lint strategy, and Compose file topology.

## Diagram

A full C4 context diagram will be added in DB-02 when the VPS and Tailscale networking
layer is designed.
