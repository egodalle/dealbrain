---
owner: data-engineer
last-reviewed: 2026-11-26
stability: stable
---

# DealBrain Onboarding

This guide gets a new contributor to a running local stack in under five minutes.

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2.1+)
- [uv](https://docs.astral.sh/uv/) — Python package manager (`brew install uv` or `pip install uv`)
- Git

## Quick start

```bash
# 1. Clone the repo
git clone <repo-url>
cd dealbrain

# 2. Set up environment variables
cp .env.example .env
# Edit .env and set a real POSTGRES_PASSWORD (any value works locally)

# 3. Start the local stack (Postgres with pgvector)
make up
# Waits until all containers are healthy, then prints "Stack is healthy."

# 4. Run the test suite
make test
# Runs unit tests via pytest; must exit 0 with at least 1 test passing
```

## Lint

```bash
make lint
# Runs ruff check, ruff format --check, and mypy --strict
```

## Tear down

```bash
make down
# Stops containers and removes volumes for a clean-slate reset
```

## Directory layout

```
apps/portal       Portal UI (future)
apps/mcp          MCP server (future)
pipelines/        Ingestion and ETL pipelines
router/           LLM router (all LLM calls go through here)
brain/            Scoring and dedupe logic
hermes/skills/    Hermes assistant skills
db/migrations/    Numbered SQL migration files
db/init/          Init SQL run at first container start
infra/            Infrastructure definitions
tests/unit/       Unit tests (run without Docker services)
tests/integration/  Integration tests
tests/acceptance/ Acceptance tests
evals/            LLM eval suite
docs/             Architecture docs, ADRs, story work
```

## CI

GitHub Actions runs `make lint` and `make test` on every push and pull request.
Both jobs must be green before merging to `main`.

## VPS and Tailscale setup

This section documents how to provision a new VPS, harden it with Tailscale-only
access, and deploy the hello-world portal. Steps 1–3 require a live VPS; step 4
onwards uses `make deploy` from your local machine.

### 1. Provision the VPS

Create a Hetzner CX22 (2 vCPU / 4 GB RAM / Ubuntu 24.04 LTS) via the Hetzner
Cloud console. During provisioning:

- Add a **cloud firewall** with two inbound rules:
  - UDP 41641 from 0.0.0.0/0 (Tailscale WireGuard)
  - UDP 3478  from 0.0.0.0/0 (Tailscale STUN)
  - TCP 22    from your engineer IP (temporary — removed after Tailscale is up)
- Attach the firewall to the VPS before first boot.
- Note the VPS **public IP** shown in the console.

### 2. Create a Tailscale auth key

In the [Tailscale admin console](https://login.tailscale.com/admin/settings/keys):

- Settings > Keys > Generate auth key
- Reusable: **yes**, Ephemeral: **no**, Expiry: 90 days
- Copy the key — it is shown only once.

### 3. Bootstrap the VPS

SSH to the public IP (temporary):

```bash
ssh root@<public-ip>
```

Then run the bootstrap script from the repo:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/<org>/dealbrain/main/infra/bootstrap.sh)
```

The script will pause twice and ask you to:

1. Write `/etc/tailscale.env` with your auth key:

   ```bash
   echo "TS_AUTHKEY=tskey-auth-XXXXXXXX" > /etc/tailscale.env
   chmod 0600 /etc/tailscale.env
   ```

2. After `tailscale up` runs, record the Tailscale IP (`tailscale ip -4`) and
   write `/etc/dealbrain.env`:

   ```bash
   install -m 0640 -o root -g docker /dev/null /etc/dealbrain.env
   printf "TAILSCALE_IP=%s\nPOSTGRES_PASSWORD=%s\n" \
       "$(tailscale ip -4)" \
       "$(openssl rand -hex 24)" \
       >> /etc/dealbrain.env
   ```

The script configures ufw, clones the repo to `/srv/dealbrain`, and runs the
first `docker compose up -d --wait portal`.

### 4. Close public SSH

Once the script prints "Bootstrap complete" and you can SSH via the Tailscale IP:

```bash
ssh dealbrain@<tailscale-ip>   # must succeed before the next step
```

Remove the TCP 22 rule from the cloud firewall in the Hetzner console.
SSH to the public IP will now be blocked; only the Tailscale IP works.

### 5. Reach the portal

From any machine on the tailnet:

```bash
curl http://<tailscale-ip>:8000/health
# {"status":"ok"}

curl http://<tailscale-ip>:8000/
# {"status":"ok","service":"dealbrain-portal"}
```

### 6. Deploy updates

On your local machine, set two env vars (add them to your shell profile):

```bash
export DEALBRAIN_HOST=100.x.x.x   # VPS Tailscale IP
export DEALBRAIN_USER=dealbrain
```

Then deploy with:

```bash
make deploy
```

This SSH's to the VPS, runs `git pull`, and restarts the portal container.
The portal is reachable within 2 minutes.

### 7. Local development with TAILSCALE_IP

The compose file binds services to `${TAILSCALE_IP}`. Local developers who do
not have Tailscale set `TAILSCALE_IP=127.0.0.1` in their `.env` file (which is
the default in `.env.example`).

## Notes

- Never commit `.env` — it is in `.gitignore`. Commit `.env.example` only.
- LLM calls go only through `router/`. Nothing sends outbound messages without
  a human approving the action in the portal.
- See `docs/ARCHITECTURE.md` for a system overview and `docs/adr/` for decisions.
