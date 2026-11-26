---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# DB-02 Design: VPS + Tailscale-only admin + hello-world portal deploy

ADR: [docs/adr/0002-vps-firewall-and-tailscale-only-admin.md](../../adr/0002-vps-firewall-and-tailscale-only-admin.md)

---

## 1. Answers to the open questions

**Portal port:** 8000. Matches the acceptance criteria verbatim. No reason to deviate.

**`make deploy` mechanism:** `infra/deploy.sh` invoked as `make deploy`. The script
wraps `ssh` over the Tailscale IP, pulls the repo, and runs `docker compose up -d
--wait portal`. The Makefile target is the public interface; the script holds the
implementation. This keeps the Makefile readable and allows the script to be tested
independently.

**Firewall layer:** Cloud provider security group as the primary barrier, `ufw` as
defence in depth. See ADR-0002.

**Tailscale auth key storage:** An environment variable named `TS_AUTHKEY` on the VPS
host, written to `/etc/tailscale.env` with mode 0600, owned by root. It is sourced by
the bootstrap script and never written to git. The key is a reusable auth key created
in the Tailscale admin console with `--ephemeral=false` and an expiry of 90 days.
On CI there is nothing to store — CI does not provision Tailscale.

---

## 2. VPS requirements

**Provider:** Hetzner CX22 (2 vCPU, 4 GB RAM, 40 GB NVMe SSD, 20 TB traffic) at ~$6/mo.
DigitalOcean Basic Droplet ($6/mo, 1 vCPU, 1 GB) is too small once Docker and Postgres
are running. The Hetzner CX22 is the minimum; the CX32 (4 vCPU, 8 GB) is preferred if
the budget allows.

**OS:** Ubuntu 24.04 LTS (Noble). Long-term support, Docker Engine packages available,
ufw ships by default, Tailscale packages available from pkgs.tailscale.com.

**Minimum free disk:** 10 GB after the OS. The pgvector image is ~180 MB; the portal
image will be ~200 MB. Reserve 8 GB for Postgres data volumes in this story.

**Required packages (beyond the OS defaults):**
- `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-compose-plugin` (Docker Engine v26+)
- `tailscale` (from pkgs.tailscale.com)
- `ufw`
- `git`, `curl`, `ca-certificates`

---

## 3. Tailscale setup

### Install

```bash
curl -fsSL https://tailscale.com/install.sh | sh
```

The installer detects Ubuntu 24.04 and adds the Tailscale APT repository, installs the
package, and starts `tailscaled`. It does not call `tailscale up` — that is a separate
step so the auth key can be injected from an env var.

### Auth key

The auth key is a reusable, non-ephemeral key created in the Tailscale admin console
under Settings > Keys. It must have:
- `Reusable: true` (so the same key can provision multiple re-provisions of the same node)
- `Ephemeral: false` (the VPS is long-lived; ephemeral keys expire when the device goes offline)
- Expiry: 90 days (rotate on ONBOARDING renewal)
- Tags: none required for this story

Store it on the VPS:

```bash
# Run as root on the VPS (bootstrap only)
echo "TS_AUTHKEY=tskey-auth-XXXXXXXX" > /etc/tailscale.env
chmod 0600 /etc/tailscale.env
chown root:root /etc/tailscale.env
```

Bring up Tailscale:

```bash
source /etc/tailscale.env
tailscale up --auth-key="$TS_AUTHKEY" --hostname=dealbrain-vps
```

### Which services listen only on the Tailscale interface

After `tailscale up`, the VPS receives a `100.x.x.x` address (the tailnet IP).

| Service | Bind address in compose | Why |
|---|---|---|
| `portal` | `100.x.x.x:8000` | Only tailnet peers reach the portal |
| `db` | `100.x.x.x:5432` | Only tailnet peers (and local) reach Postgres |

The Tailscale IP is not known at image-build time, so it is passed at runtime via the
environment variable `TAILSCALE_IP`, which is set in `/etc/dealbrain.env` on the VPS.

```bash
# /etc/dealbrain.env (mode 0640, owner root:docker)
TAILSCALE_IP=100.x.x.x    # replace with actual value after tailscale up
POSTGRES_PASSWORD=...
```

The compose file uses `${TAILSCALE_IP}` in the `ports:` block:

```yaml
ports:
  - "${TAILSCALE_IP}:8000:8000"
```

If `TAILSCALE_IP` is not set, `docker compose up` fails with a clear error, which is
the correct failure mode.

---

## 4. Firewall rules

### Cloud provider security group (Hetzner Firewall)

Configured via the Hetzner Cloud console before the VPS boots.

**Inbound rules (steady state — after Tailscale bootstrap):**

| Protocol | Port | Source | Purpose |
|---|---|---|---|
| UDP | 41641 | 0.0.0.0/0 | Tailscale DERP/WireGuard relay |
| UDP | 3478 | 0.0.0.0/0 | Tailscale STUN (NAT traversal) |

All other inbound traffic is implicitly denied.

**Bootstrap exception (temporary — only during provisioning):**

| Protocol | Port | Source | Purpose |
|---|---|---|---|
| TCP | 22 | Engineer's IP or 0.0.0.0/0 | Initial SSH for provisioning |

This rule is deleted immediately after `tailscale up` succeeds and the engineer
confirms SSH over `100.x.x.x` works.

**Outbound rules:** allow all (the VPS needs to pull packages, images, and Tailscale
relay traffic).

### Host-level ufw

ufw is a defence-in-depth layer. It does not replace the cloud firewall.

```bash
ufw default deny incoming
ufw default allow outgoing
# Allow Tailscale's WireGuard port
ufw allow 41641/udp comment 'tailscale'
# Allow Tailscale STUN
ufw allow 3478/udp comment 'tailscale-stun'
ufw enable
```

Port 22 is never opened in ufw. After Tailscale is up, SSH goes through the Tailscale
interface (which bypasses ufw's INPUT chain because the traffic arrives on `tailscale0`,
a loopback-class interface). The cloud firewall provides the primary block on port 22.

---

## 5. Hello-world portal (apps/portal/)

### File layout

```
apps/portal/
  Dockerfile
  main.py
  requirements.txt    (or pyproject.toml — see note below)
```

The portal is a separate Python process from the top-level `pyproject.toml`. It has
its own `requirements.txt` to keep the Docker image lean (no dev dependencies).

### main.py

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
```

A single route. No database connection, no auth, no business logic. This is a
placeholder that proves the deploy mechanism works.

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The CMD binds to `0.0.0.0` inside the container. The external binding to
`${TAILSCALE_IP}:8000` is enforced by the compose `ports:` block on the host.
Docker port mapping handles the translation; the container itself does not need
to know the Tailscale IP.

### requirements.txt

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
```

Pin exact versions. `uvicorn[standard]` pulls in `uvloop` and `httptools` for
production performance.

### docker-compose.yml additions

Add a `portal` service to the existing compose file:

```yaml
  portal:
    build:
      context: ./apps/portal
    ports:
      - "${TAILSCALE_IP}:8000:8000"
    environment:
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 10s
      timeout: 5s
      retries: 5
```

The healthcheck curls `localhost` (inside the container) so it is independent of
the Tailscale IP. The container is marked healthy only when `/health` returns 2xx.

The `db` service also needs its `ports:` block updated:

```yaml
    ports:
      - "${TAILSCALE_IP}:5432:5432"
```

This is a **breaking change** to the existing compose file for local development.
Local developers who do not have a Tailscale IP must set `TAILSCALE_IP=127.0.0.1`
in their `.env` file. Add this to `.env.example`.

---

## 6. Deploy mechanism

### infra/deploy.sh

The script is the single source of truth for how to deploy. `make deploy` calls it.

```
infra/
  deploy.sh
```

The script assumes:
- `DEALBRAIN_HOST` is set (the Tailscale IP or hostname of the VPS)
- `DEALBRAIN_USER` is set (the SSH user on the VPS, default `dealbrain`)
- The calling machine's SSH key is already in the VPS's `authorized_keys`
  (registered during bootstrap, over Tailscale)

Sequence executed by `deploy.sh`:

1. `ssh $DEALBRAIN_USER@$DEALBRAIN_HOST "cd /srv/dealbrain && git pull --ff-only origin main"`
2. `ssh $DEALBRAIN_USER@$DEALBRAIN_HOST "source /etc/dealbrain.env && docker compose up -d --wait portal"`
3. `ssh $DEALBRAIN_USER@$DEALBRAIN_HOST "docker compose ps portal"` — print status for the caller

The VPS must have the repo cloned to `/srv/dealbrain` and the compose file at
`/srv/dealbrain/docker-compose.yml`. The repo clone is a one-time bootstrap step
documented in ONBOARDING.md.

### Makefile targets

Add two targets to the existing Makefile:

```makefile
.PHONY: deploy deploy-status

deploy:
	@bash infra/deploy.sh

deploy-status:
	ssh $(DEALBRAIN_USER)@$(DEALBRAIN_HOST) "cd /srv/dealbrain && docker compose ps"
```

`make deploy` is the single command that satisfies AC6. It runs in under 2 minutes on
a Hetzner CX22 because the Docker image layers are already cached from the previous
deploy; only the changed layers (and the final `COPY main.py`) are transferred.

### Environment variables for make deploy

The calling engineer's shell must have:

```bash
export DEALBRAIN_HOST=100.x.x.x   # VPS Tailscale IP
export DEALBRAIN_USER=dealbrain
```

Add both to `.env.example` as comments (they are not Docker env vars and must not
be passed to compose, only to the shell).

---

## 7. Tailscale Funnel (future, not wired in this story)

This section documents the mechanism so it is available for the story that wires it
up. **Do not run these commands in DB-02.**

Tailscale Funnel exposes one HTTPS endpoint from the tailnet to the public internet,
proxied through Tailscale's infrastructure. It terminates TLS automatically.

The command to expose the portal's `/health` route publicly would be:

```bash
tailscale funnel --bg 8000
```

This creates a public URL at `https://<hostname>.<tailnet>.ts.net` that proxies to
`localhost:8000` on the VPS. All other routes are served by the same URL but only
the health route has no auth, so the effect is equivalent to exposing one route.

Limitations: Funnel is currently available on the Tailscale Personal/Starter plan and
above. It requires the VPS node to have the `funnel` ACL capability in the tailnet
policy file. The demo referenced in the story ("show the browser hitting the portal
URL on the tailnet IP") uses the tailnet IP directly, not Funnel.

---

## 8. infra/ layout

```
infra/
  deploy.sh         — SSH-over-Tailscale deploy script (see section 6)
  bootstrap.sh      — one-time VPS provisioning script (Docker, Tailscale, ufw)
```

`bootstrap.sh` is a documentation artifact as much as a runnable script. It records
exactly what the engineer ran during provisioning so the VPS can be reproduced.
It is idempotent: running it twice on a provisioned VPS is safe.

`bootstrap.sh` sequence:

1. `apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin git curl ca-certificates ufw`
2. Add the deploy user: `useradd -m -s /bin/bash dealbrain && usermod -aG docker dealbrain`
3. Write `/etc/tailscale.env` and `/etc/dealbrain.env` (engineer does this manually — bootstrap.sh prints instructions, does not write secrets)
4. Install Tailscale and run `tailscale up --auth-key="$TS_AUTHKEY" --hostname=dealbrain-vps`
5. Configure ufw (commands from section 4)
6. Clone the repo: `git clone <repo-url> /srv/dealbrain`
7. First deploy: `source /etc/dealbrain.env && cd /srv/dealbrain && docker compose up -d --wait portal`
8. Print: "Bootstrap complete. Close SSH port 22 in the cloud provider console now."

---

## 9. CI changes

No new CI jobs are needed for this story.

The existing `ci.yml` (from DB-01) does not deploy to the VPS. Deployment is manual
in this story (`make deploy`). DB-14 will add the GitHub Actions deploy job.

One optional improvement that fits within this story: add `DEALBRAIN_HOST` and
`DEALBRAIN_USER` to the GitHub repository's environment secrets (under a `production`
environment) so they are available when DB-14 wires up the CI deploy. This is a
documentation step, not a code change, and can be deferred to DB-14 if the engineer
prefers.

---

## 10. Failure modes and retries

| Failure | Cause | Recovery |
|---|---|---|
| `tailscale up` fails | Bad auth key or DNS | Check key in Tailscale console; `tailscale up --reset` |
| SSH after firewall close fails | Cloud firewall rule not fully propagated | Wait 30 s; use cloud provider out-of-band console |
| `docker compose up --wait portal` times out | Image build fails or healthcheck never passes | `docker compose logs portal`; most likely `TAILSCALE_IP` not set |
| `make deploy` git pull fails | Merge conflict or non-fast-forward | Resolve locally, push, re-run `make deploy` |
| nmap shows port 8000 open | Cloud firewall rule not applied | Verify the security group is attached to the VPS in the console |
| Portal unreachable on tailnet | `TAILSCALE_IP` in compose is wrong | `tailscale ip -4` on VPS; update `/etc/dealbrain.env`; redeploy |

---

## 11. Tests that prove the story

| AC | Command | Expected result |
|---|---|---|
| AC1 | `curl -I http://<tailscale-ip>:8000/` from a tailnet peer | `HTTP/1.1 200 OK` |
| AC2 | `nmap -p 22,5432,8000,8080 <public-ip>` from outside the tailnet | All ports `filtered` or `closed` |
| AC3 | `tailscale status` on VPS | Node listed as `Connected`; at least one peer shown |
| AC4 | `docker compose ps` on VPS | `portal` in state `running` and `healthy` |
| AC5 | `ssh dealbrain@<public-ip>` | Connection refused or timeout (not a prompt) |
| AC6 | `make deploy` | Exits 0; portal reachable within 2 minutes |
| AC7 | `grep -n "## VPS and Tailscale setup" ONBOARDING.md` | Returns a line number |

---

## Implementation checklist

Execute in this order. Each item is unblocked by the items above it.

1. **Cloud provider:** Create the VPS (Ubuntu 24.04, Hetzner CX22 or equivalent).
   Create a cloud firewall with one inbound rule: TCP 22 from the engineer's IP.
   Attach the firewall to the VPS. Note the VPS public IP.

2. **Cloud provider:** Create a Tailscale auth key in the Tailscale admin console
   (reusable, non-ephemeral, 90-day expiry). Store the key value — it is shown only
   once.

3. **VPS bootstrap (SSH over public IP, temporary):**
   - Run `infra/bootstrap.sh` or execute its steps manually.
   - Write `/etc/tailscale.env` with `TS_AUTHKEY=<key>`.
   - Run `tailscale up --auth-key="$TS_AUTHKEY" --hostname=dealbrain-vps`.
   - Run `tailscale ip -4` and note the `100.x.x.x` address.
   - Write `/etc/dealbrain.env` with `TAILSCALE_IP=<tailnet-ip>` and `POSTGRES_PASSWORD=<strong-random>`.
   - Configure ufw (section 4 commands).
   - Confirm `tailscale status` shows the node and a peer.

4. **Cloud provider:** Delete (or restrict to 0.0.0.0/0 → no-match) the TCP 22 inbound
   rule from the cloud firewall. From this point, SSH only works via
   `ssh dealbrain@<tailscale-ip>`.

5. **Verify SSH over Tailscale** works before closing the public SSH window.

6. **apps/portal/main.py** — write the FastAPI health endpoint (section 5).

7. **apps/portal/requirements.txt** — pin fastapi and uvicorn (section 5).

8. **apps/portal/Dockerfile** — write the Dockerfile (section 5).

9. **docker-compose.yml** — add `portal` service and update `db` ports binding to
   `${TAILSCALE_IP}:5432:5432` (section 5).

10. **`.env.example`** — add `TAILSCALE_IP=127.0.0.1` (for local dev) and
    `DEALBRAIN_HOST=` and `DEALBRAIN_USER=dealbrain` as comments.

11. **infra/bootstrap.sh** — write the idempotent provisioning script (section 8).

12. **infra/deploy.sh** — write the SSH-over-Tailscale deploy script (section 6).

13. **Makefile** — add `deploy` and `deploy-status` targets (section 6).

14. **VPS: clone repo** to `/srv/dealbrain`, run first deploy manually:
    ```bash
    source /etc/dealbrain.env
    cd /srv/dealbrain
    docker compose up -d --wait portal
    ```

15. **Verify AC1–AC7** (section 11). Record the nmap output and `tailscale status`
    output in `docs/work/DB-02/impl-notes.md`.

16. **ONBOARDING.md** — add `## VPS and Tailscale setup` section with exact commands
    for provisioning, Tailscale auth, and reaching the portal. Update in the same PR.
