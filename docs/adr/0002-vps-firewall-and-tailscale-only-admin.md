---
owner: architect
last-reviewed: 2026-11-26
stability: stable
---

# ADR-0002: VPS firewall layer and Tailscale-only admin surface

## Context

DB-02 must satisfy two properties simultaneously:

1. Zero public ports — not even SSH — after initial provisioning.
2. All admin access (SSH, Postgres, portal) exclusively over Tailscale.

Three candidate firewall approaches exist:

- **Cloud security group only** (Hetzner Firewall / DigitalOcean Firewall / Vultr Firewall):
  rules live outside the VM, cannot be bypassed by software running on the VM,
  and survive OS reinstalls.
- **ufw only** (host-level iptables wrapper): rules live on the VM, are wiped by
  `ufw reset`, and are bypassed if a containerized service binds `0.0.0.0` and the
  user forgets to pass `--publish` to a Tailscale interface only.
- **Cloud security group + ufw** (defence in depth): two independent layers.
  The cloud firewall is the primary barrier; ufw is a last-resort backstop.

There is also a question of *when* port 22 is closed. The VPS must be provisioned
before Tailscale is installed; SSH over the public interface is needed for that one
step, then must be blocked.

## Decision

**Primary barrier: cloud provider firewall (security group).**

The cloud firewall is the only layer that is fully decoupled from software running on
the VM, including Docker and the host OS. We rely on it as the authoritative block.

**Secondary barrier: ufw on the host**, configured to drop everything on the public
interface except the Tailscale daemon's UDP port (41641 by default) during the brief
bootstrap window, and to drop everything after Tailscale is up and the cloud firewall
is locked. ufw provides defence in depth and also protects against misconfigured
`docker-compose.yml` files that bind ports to `0.0.0.0`.

**SSH over Tailscale only after bootstrap.** The bootstrap sequence is:

1. VPS boots with public SSH open (cloud firewall: allow TCP 22 from anywhere).
2. SSH in, install Tailscale, `tailscale up --auth-key=$TS_AUTHKEY`.
3. Verify `tailscale status` shows the node and at least one peer.
4. Close port 22 in the cloud firewall (delete the allow-SSH rule or restrict to
   the engineer's IP temporarily, then delete it). From this point, SSH uses the
   Tailscale IP only.

This sequence means the public IP never has SSH open in steady state.
The window where SSH is open is bounded: it ends when `tailscale up` succeeds and
the engineer updates the cloud firewall rule.

**Tailscale Funnel is not provisioned in this story.** The story marks it out of
scope. The design documents the future command so the data-engineer does not need to
research it, but it must not be run in DB-02.

## Consequences

- The data-engineer must have access to the cloud provider console to manage firewall
  rules (security group). The deploy script cannot manage cloud-provider rules — only
  host-level `ufw` rules.
- `docker-compose.yml` must bind `db` and `portal` to the Tailscale interface
  (`100.x.x.x`) instead of `0.0.0.0`. The DB-01 compose file binds db to `0.0.0.0`;
  the DB-02 compose file must add the interface prefix. See design.md section 5.
- If Tailscale is down, there is no path into the VPS. That is the desired property.
  Recovery: use the cloud provider's out-of-band console (Hetzner KVM, DO Recovery
  Console).

## Alternatives rejected

- **ufw only**: Docker bypasses iptables rules when it publishes ports via the kernel
  netfilter hook that Docker inserts ahead of ufw's FORWARD chain. A cloud firewall
  does not have this problem. Rejected as the sole layer.
- **Cloud firewall only**: Provides no protection against a future `docker compose up`
  that accidentally publishes a port to `0.0.0.0`. Defence in depth costs one `ufw`
  install and is worth it. Rejected as the sole layer.
- **Close SSH before Tailscale is up**: Creates a situation where the VPS is
  unreachable if `tailscale up` fails. Rejected.
