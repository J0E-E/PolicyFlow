# Exit-test runbook — the P0.1 go/no-go gate

This runbook orchestrates the existing one-time bootstrap steps into the correct
end-to-end order and then defines the **exit test**: the phase acceptance gate.
It **points to** the per-step docs for each detail rather than restating them, so
each procedure has a single source of truth.

## Purpose

P0.1 passes when a commit pushed to `main` reaches
`https://policyflow.joeyshub.com` over valid HTTPS, hands-off through Source →
Build → ECR → Deploy, with **zero manual steps**. That is the exit test defined in
the TDD: see `../.development-docs/phase-0/tdd-P0.1-walking-skeleton.md` →
"## 8. Rollout / Verification" → "Exit test (production — the acceptance gate)".

The cloud has never been provisioned (every prior epic deliberately skipped
`terraform apply`), so the steps below run **once, by hand** to stand the
environment up. They are sanctioned manual bootstrap, not part of the steady-state
gate. Once they are done, the exit test itself is the zero-manual-step push.

## One-time bring-up (manual, sanctioned)

Run these in order the first time only. Each item is a pointer to where the
procedure already lives.

1. **Bootstrap remote state, then `terraform apply`.**
   See `../infra/README.md` → "Bootstrap the remote state, once" and the apply
   steps that follow.

2. **Authorize the GitHub CodeStar connection** (AWS console — the connection
   starts PENDING).
   See `../infra/README.md` → "Authorize the GitHub connection (one-time)".

3. **Set the two SSM SecureString passwords out-of-band** (`terraform apply`
   creates them with a `CHANGE_ME` placeholder; the real values live only in SSM).
   See `../infra/README.md` → the SSM `put-parameter` steps (Epic 7).

4. **First pipeline run** — push to `main` (or release the latest change) to
   trigger Source → Build → Deploy. Build pushes the core + frontend images to
   ECR; Deploy installs the bundle to `/opt/policyflow`, writes
   `/opt/policyflow/.env` (defaults + SSM secrets + image refs), and **self-issues
   the TLS certificate on first run**: `ApplicationStart` lays down a throwaway
   dummy cert so nginx can boot, brings the stack up, then requests the real
   Let's Encrypt cert over HTTP-01 and reloads nginx. Once a real cert exists this
   is a no-op, so later deploys just do `up -d`. No host step is required.

   The deploy handles the cert ordering on its own: Build always precedes Deploy
   (so the frontend image exists in ECR), and `ApplicationStart` runs from
   `/opt/policyflow`, so the `letsencrypt` named volume is correctly scoped to the
   deployed stack. The manual `./ops/init-letsencrypt.sh` (see `./README.md`)
   remains only as a fallback for re-issuing by hand.

5. **Confirm the full stack is healthy.**
   - HTTP reaches the host and redirects to HTTPS.
   - `https://policyflow.joeyshub.com` serves over a **valid** certificate.
   - The landing and `/select-tenant` placeholders render.

   `ValidateService` already gates the deploy on both core health and the public
   HTTPS edge, so a green Deploy means the site is up. The exit test below is then
   truly zero-manual-step.

## The exit test (steady-state, zero manual steps)

This is the gate. Once the bring-up above is done, the live proof is just a push:

1. Push a commit to `main`.
2. Observe CodePipeline run **Source → Build → ECR → Deploy hands-off** — no
   console clicks, no host commands.
3. Confirm the change is **live at `https://policyflow.joeyshub.com` over valid
   HTTPS**.

If all three hold with zero manual steps, P0.1 passes.

## Record the run

Fill in after the live run.

- **Date / commit:** _pending live run_
- **Result:** _PASS / FAIL — pending_
- **What passed:** _Source / Build / ECR / Deploy / HTTPS — pending_
- **Glue or fixes discovered:** _pending_ (note which epic each fix routes back to).

## Rollback

Redeploy a prior ECR image tag (per the TDD §8 rollout note: "Rollback = redeploy a
prior ECR image tag"). Migrations + seed run as deploy steps; DB reset on deploy is
acceptable pre-go-live.
