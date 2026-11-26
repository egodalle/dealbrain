# DealBrain: team and repo rules

DealBrain is a second brain and agent system for a real estate investor: public property data plus CRM, email and SMS, then dedupe and scoring, then GBrain, then a Hermes assistant over MCP. **Nothing is sent without human approval.** The build plan is in `docs/backlog.md`.

## The team (subagents in `.claude/agents/`)

| Agent | Owns | Never does |
|---|---|---|
| `product-owner` | Backlog, stories, acceptance criteria, scope and cuts, acceptance | Code, tests, ADRs |
| `architect` | Design per story, ADRs, contracts, ARCHITECTURE.md, design review | Feature code |
| `data-engineer` | All implementation and its unit tests, migrations, infra, docs updates | Redesigning silently, editing acceptance tests or evals |
| `tester` | Acceptance and integration tests, evals, guardrail suite, test reports | Fixing feature code, lowering bars |

## Story flow

Run the whole flow with `/story DB-NN`.

```
product-owner ─ story.md (status: ready)
      │
architect ───── design.md (+ ADR if needed)
      │
data-engineer ─ branch feat/DB-NN-*, code, impl-notes.md (status: review)
      │
architect ───── review.md ── blocking? ──► back to data-engineer
      │
tester ──────── test-report.md ── any FAIL? ──► back to data-engineer
      │
product-owner ─ accept (status: done) → PR → merge to main
```

All handoffs go through files in `docs/work/<ID>/`, not chat. A story moves forward only when its file for that step exists. At most 2 return loops per story, then escalate to the human with a summary.

## Repo rules (every agent follows these)
- Branches: `feat/`, `fix/` or `chore/` + `<ID>-short-name`. Commits use conventional commit messages. Squash-merge to `main`, and `main` is always deployable.
- `make lint test` passes before review. CI runs lint, mypy, tests against pgvector, and the eval gate.
- **Approval boundary:** messages and client-data changes go only through `pending_actions` → portal approve. No agent, skill or MCP tool gets a send capability.
- LLM calls go only through `router/`.
- No secrets and no real personal data in git. Use synthetic contacts only, and mask owner names in public demos.
- Postgres, SSH and admin UIs are reachable only over Tailscale.
- If you change setup, update ONBOARDING.md in the same PR.

## Layout
```
apps/portal  apps/mcp  pipelines/  router/  brain/  hermes/skills/
db/migrations/  infra/  tests/{unit,integration,acceptance}/  evals/
docs/{backlog.md, ARCHITECTURE.md, adr/, work/<ID>/}
```
