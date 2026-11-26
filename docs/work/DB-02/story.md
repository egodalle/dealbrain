# DB-02: VPS + Tailscale-only admin + hello-world portal deploy

**Status:** done · **Plan day:** 1 · **Posting lines covered:** Docker, Linux, VPS, Tailscale, jobs, monitoring, backups

## Story
As a **RE RESET engineer deploying DealBrain to a fresh VPS**, I want the portal reachable over the Tailscale tailnet and all admin ports closed to the public internet, so that only authorized team members can reach the system without exposing attack surface.

## Acceptance criteria
1. `curl -I http://<tailscale-ip>:8000/` from a machine on the tailnet returns `HTTP/1.1 200 OK` with the hello-world portal response.
2. `nmap -p 22,5432,8000,8080 <public-ip>` from a machine NOT on the tailnet shows all four ports as `filtered` or `closed` — none as `open`.
3. `tailscale status` on the VPS lists the VPS node as connected and shows at least one peer.
4. `docker compose ps` on the VPS shows the portal container in state `running` and healthy (if a healthcheck is defined).
5. SSH to the VPS's public IP is blocked; SSH succeeds only via the Tailscale IP (`ssh user@<tailscale-ip>`).
6. `make deploy` (or the documented deploy command) completes without manual intervention and the portal is reachable over the tailnet within 2 minutes of the command finishing.
7. ONBOARDING.md contains a section titled "VPS and Tailscale setup" with the exact commands a new engineer needs to provision the VPS, install Tailscale, and reach the portal.

## Demo line
Show the browser hitting the portal URL on the tailnet IP, then show nmap confirming zero open public ports.

## Out of scope
- TLS / HTTPS termination (that is for a later story when the domain is wired up)
- Tailscale ACLs beyond the default allow-all tailnet policy
- Any real app logic in the portal — the hello-world page is a placeholder
- Cloudflare Funnel configuration (the Funnel is optional and not wired to anything yet)

## Open questions for Architect
- Which port should the portal container listen on (8000, 8080, or 3000)? The acceptance criterion above assumes 8000; adjust if the Compose file uses a different port.
- Should `make deploy` use `docker compose pull && docker compose up -d` or is there a separate deploy script in `infra/`?
- Does the VPS firewall use `ufw` or the cloud provider's security-group rules? The nmap criterion needs to know which layer is doing the blocking.
- Is the Tailscale auth key stored as a CI/CD secret, an env file on the VPS, or in a secrets manager? The data-engineer needs to know before provisioning.
