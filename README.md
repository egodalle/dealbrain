# DealBrain

A second brain and agent system for real estate investors. It pulls public property data (Philadelphia OPA, L&I violations, transfers, tax delinquency) and merges it with the investor's CRM, email and SMS. It dedupes and scores motivated sellers, then indexes everything into **GBrain** on Postgres + pgvector. A **Hermes** assistant uses it over **MCP** to draft outreach. **Nothing is sent until a human approves it in the portal.**

> Status: Day 0. The team and workflow are set up, and the build starts with `DB-01`.

## How this repo is built
Four Claude Code subagents work each story (see [CLAUDE.md](CLAUDE.md)):

| Agent | Role |
|---|---|
| `product-owner` | Stories, acceptance criteria, scope, acceptance |
| `architect` | Design, ADRs, contracts, design review |
| `data-engineer` | Implementation |
| `tester` | Independent verification, evals, guardrails |

Run a story end to end with `/story DB-NN`. The backlog is in [docs/backlog.md](docs/backlog.md).
