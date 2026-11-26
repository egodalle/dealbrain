# DealBrain backlog

Owned by `product-owner`. These are seed stories from the 2-week plan. The PO expands each one into `docs/work/<ID>/story.md` before it starts.

| ID | Day | Story | Lead | Key acceptance signal | Status |
|---|---|---|---|---|---|
| DB-01 | 1 | Repo layout, standards, CI, local Compose with pgvector | architect → data-engineer | `git clone && make up` works; CI green on first PR | todo |
| DB-02 | 1 | VPS + Tailscale-only admin + hello-world portal deploy | data-engineer | Portal reachable over the tailnet; no public ports except the demo Funnel | todo |
| DB-03 | 2 | Philly open-data ingestion (OPA, violations, transfers, delinquency) into raw → staging → core | data-engineer | 2nd run inserts 0 rows; 1 changed row updates exactly 1 | todo |
| DB-04 | 3 | Address normalization + entity resolution + dedupe | data-engineer | Precision/recall on 200 labeled pairs reported | todo |
| DB-05 | 3 | Explainable distress score + `/leads` data product with CSV export | data-engineer | Every score has a breakdown that sums to the total | todo |
| DB-06 | 4 | Connector interface + HubSpot two-way sync | data-engineer | A HubSpot edit flows back into Postgres; fixture tests run in CI | todo |
| DB-07 | 4 | Gmail + Calendar read, Twilio inbound SMS (signature verified) | data-engineer | An inbound SMS appears on the contact timeline; unsigned webhook gets 403 | todo |
| DB-08 | 5 | Brain pages + GBrain on Postgres + golden-set eval | data-engineer + tester | recall@5 reported per GBrain search mode, 30 questions | todo |
| DB-09 | 6 | LLM router (Anthropic, OpenAI/OpenRouter, Ollama over tailnet), budgets, `llm_calls` | data-engineer + tester | Route comparison table: quality, cost/100, p95 | todo |
| DB-10 | 7 | `dealbrain-mcp` server with read-only role + `draft_outreach` → `pending_actions` | data-engineer | MCP role UPDATE is denied; Claude Code and Hermes run every tool | todo |
| DB-11 | 8 | Hermes on VPS: Telegram, 3 skills, cron morning brief | data-engineer | Morning brief arrives on Telegram on schedule | todo |
| DB-12 | 8 | Approval loop end to end + guardrail suite | tester | No message is sent without an approved row; injection fixture can't trigger a send | todo |
| DB-13 | 9 | Backups + restore drill, monitoring, alerts | data-engineer + tester | Restore into a fresh container is timed and recorded in RUNBOOK | todo |
| DB-14 | 9 | Releases: tag → GHCR → deploy over Tailscale, rollback | data-engineer | Deploy and rollback each done once from CI | todo |
| DB-15 | 10 | ONBOARDING, ARCHITECTURE, ADRs, README numbers, Loom | product-owner + architect | Fresh clone to working system in under 15 min | todo |
| DB-16 | 10 | GitHub profile cleanup + application submitted | human | Repos archived, pinned and described; application sent | todo |

## Posting coverage
| Posting line | Stories |
|---|---|
| Hermes assistants and skills | DB-11 |
| gBrain, pgvector, retrieval | DB-08 |
| Portals, dashboards, RE data products | DB-05, DB-12 |
| CRM, email, calendar, phone, messaging | DB-06, DB-07 |
| Collect, transform, dedupe, score, deliver | DB-03, DB-04, DB-05 |
| LLM routing for cost, speed, quality | DB-09 |
| Docker, Linux, VPS, Tailscale, jobs, monitoring, backups | DB-02, DB-13, DB-14 |
| Approval before sends or data changes | DB-10, DB-12 |
| MCP servers | DB-10 |
| GitHub, standards, CI, releases, docs | DB-01, DB-14, DB-15, DB-16 |

## Cut list (apply in order)
1. Google Calendar  2. Ollama route  3. Gmail  4. Third Hermes skill
**Never cut:** approval loop, MCP server, GBrain evals, backup and restore, ONBOARDING.md
