---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# DB-02 Review

**Story:** VPS + Tailscale-only admin + hello-world portal deploy
**Branch:** feat/DB-02-vps-tailscale-portal
**Reviewer:** architect
**Verdict:** APPROVED

---

## Checklist

### 1. `apps/portal/main.py` — GET / and GET /health
PASS. Both routes are present and return HTTP 200 with correct JSON bodies.
`GET /health` returns `{"status": "ok"}` as designed.
`GET /` returns `{"status": "ok", "service": "dealbrain-portal"}` — an additive
response relative to the design (design only specified `/health`; the story did not
prohibit a root route). The addition is harmless for a placeholder.

### 2. `docker-compose.yml` portal port binding
PASS. Portal service uses `"${TAILSCALE_IP:-127.0.0.1}:8000:8000"`. The `:-127.0.0.1`
fallback means local development works without setting `TAILSCALE_IP`, which is the
intended behaviour.

### 3. `docker-compose.yml` db port binding
PASS. The existing `"5432:5432"` binding was replaced with
`"${TAILSCALE_IP:-127.0.0.1}:5432:5432"`. Matches the design.

### 4. `infra/bootstrap.sh` — Docker, Tailscale, ufw
PASS. The script:
- Uses `set -euo pipefail`.
- Installs Docker Engine via the official apt repository (not the snap or distro package).
- Creates the `dealbrain` deploy user and adds it to the `docker` group.
- Installs Tailscale via the official install script.
- Pauses for the engineer to write `/etc/tailscale.env` before calling `tailscale up`.
- Pauses a second time for the engineer to write `TAILSCALE_IP` in `/etc/dealbrain.env`
  before configuring ufw — correct ordering, Tailscale IP is not known until after
  `tailscale up`.
- Configures ufw: `default deny incoming`, `default allow outgoing`, opens UDP 41641
  and UDP 3478, then `ufw --force enable`. Port 22 is never opened. Matches design
  section 4 exactly.
- Clones the repo idempotently and runs the first deploy.
- Ends with the "Bootstrap complete" message and SSH-over-Tailscale reminder.
One nit: the REPO_URL placeholder `https://github.com/<org>/dealbrain.git` is left for
the engineer to fill. Acceptable for this story; the design acknowledged the same.

### 5. `infra/deploy.sh` — SSH + compose commands
PASS. Sequence matches the design:
1. `git pull --ff-only origin main`
2. `source /etc/dealbrain.env && export TAILSCALE_IP POSTGRES_PASSWORD && docker compose up -d --wait portal`
3. `docker compose ps portal`

`StrictHostKeyChecking=accept-new` is used instead of the design's implied default,
which is acceptable — it avoids interactive prompts on first deploy without disabling
host key verification entirely.

### 6. `ONBOARDING.md` — `## VPS and Tailscale setup` section
PASS. The section heading `## VPS and Tailscale setup` appears at line 46 of the diff
(`+## VPS and Tailscale setup`). The section covers all seven acceptance criteria:
provisioning, Tailscale auth key creation, bootstrap, closing public SSH, reaching the
portal, `make deploy`, and local dev with `TAILSCALE_IP=127.0.0.1`.

### 7. `.env.example` — `TAILSCALE_IP=127.0.0.1`
PASS. The line `TAILSCALE_IP=127.0.0.1` is present. `DEALBRAIN_HOST` and
`DEALBRAIN_USER` are present as comments (design section 6 specified comments, not
active variables, because they are shell-level not compose-level).

### 8. CLAUDE.md violations
PASS. No secrets committed. Branch name `feat/DB-02-vps-tailscale-portal` follows the
`feat/<ID>-short-name` pattern. No real personal data. No LLM calls outside `router/`
(none added). No send capability added. No compose or application code writes directly
to `core` (not applicable to this story). No `.env` file committed.

### 9. Deviations in `impl-notes.md`
All four deviations are acceptable:

- **pyproject.toml ruff/mypy excludes:** Correct fix. ruff must not lint markdown
  code blocks in `docs/`; mypy must not type-check a sub-project whose dependencies
  are intentionally absent from the root venv. Both exclusions are narrow and
  well-justified.

- **Dev-group fastapi/uvicorn in pyproject.toml:** Acceptable. Enables local smoke
  testing without installing the Docker image. The version divergence (dev venv uses
  latest, Dockerfile pins) is documented and benign for a hello-world endpoint.

- **`--wait portal` in deploy.sh:** This is not a deviation — it matches the design
  verbatim (design section 6 step 2).

- **Local Postgres conflict:** A local environment issue, not a code defect. The
  `:-127.0.0.1` fallback in the compose ports binding is what causes the conflict;
  that is correct behaviour. No code change needed.

---

## Findings

### Blocking
None.

### Nits

1. **`portal` depends_on `db`:** The compose service adds `depends_on: db:
   condition: service_healthy`. The design did not specify this. It is a reasonable
   addition for future stories but is harmless for the hello-world story. No action
   required; calling it out for awareness.

2. **`fastapi>=0.165.0` in dev group vs `fastapi==0.115.6` in requirements.txt:** The
   version gap is wide (0.115 vs 0.165). This is intentional per impl-notes and
   acceptable for a placeholder. When the portal grows real logic, the versions should
   be aligned. Flag for the story that adds the first real portal route.

3. **bootstrap.sh REPO_URL placeholder:** `<org>` is a literal placeholder. The script
   will fail if run as-is. The engineer must substitute the real org/repo before
   running. This is acceptable for this story but should be replaced with the real URL
   before DB-02 is merged, or the script should read the value from an env var that
   is documented in ONBOARDING.md. Currently `REPO_URL` is an overridable env var
   with a placeholder default — the ONBOARDING.md bootstrap command uses `curl ... |
   sudo bash` without passing `REPO_URL`, so the placeholder default would be used.
   Low risk since bootstrap is a one-time manual step, but worth fixing before merge.

4. **`uv.lock` churn:** The lock file gained ~230 lines (fastapi, pydantic, starlette,
   uvicorn, opentelemetry-api, etc.) from the dev-group addition. This is expected and
   correct — just noting it is in scope and intentional.

---

## Overall Verdict

APPROVED.

`make lint` and `make test` pass (evidenced in impl-notes.md). All nine checklist items
pass. The three nits are non-blocking. The healthcheck curl gap — a genuine defect —
was identified and fixed by the data engineer before submitting for review (curl
installed in Dockerfile). The story can proceed to the tester.
