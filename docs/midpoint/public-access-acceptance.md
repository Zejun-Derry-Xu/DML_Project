# Instructor-facing access acceptance - 2026-10-24

## Verified entry point

<https://http-149-165-174-228-5173.proxy-js2-iu.exosphere.app/>

This is a synthetic course demonstration, not a production storefront. The URL
embeds the currently assigned public IP. Shelving stops access, and unshelving may
change the IP and proxy hostname. Recheck it before sharing or submitting the PDF.

## What changed

- Kept the installed `847c7b3` API/frontend image pair, PostgreSQL data and guided
  extraction mode. No rebuild, application-image upgrade, migration, model startup
  or model qualification was performed for this access change.
- Backed up the existing Compose and private environment files on the VM before
  changing them. No secret values or backup locations are published here.
- Made the Nginx host binding configurable with `FRONTEND_BIND_ADDRESS`, retaining
  `127.0.0.1` as the repository default. The explicitly approved server demo uses
  `0.0.0.0:5173` and persists that opt-in in its private `.env`.
- Recreated only the frontend container with `--no-deps --no-build`. The API stays
  bound to `127.0.0.1:8000`; PostgreSQL and Ollama have no published host ports.
- No firewall was disabled or broad ingress rule added. Only the application
  binding was changed. The VM's existing platform networking permits this entry.

## Acceptance performed without an SSH tunnel

1. External HTTP origin checks returned UI HTML with status 200, matching API and
   frontend commit `847c7b31785f69afc1b440df6d211b0cceee5848`, schema `0004`,
   policy `apparel-1.0.0`, and extraction mode `guided`.
2. Browser testing found that **raw IP/HTTP is not a supported interactive URL**:
   account selection fails because `crypto.randomUUID` requires a secure context.
   Localhost had masked this browser constraint. No browser protection was bypassed
   and no untested JavaScript was injected into the released image.
3. The HTTPS platform-proxy URL passed normal certificate verification and served
   the same application. TLS terminates at the proxy; its origin hop to VM port
   5173 is HTTP, not end-to-end TLS to the container.
4. A separate browser session selected Bob's fictional account, submitted a return
   description, received the owned-order card, selected it, entered a reason and
   received the stain-condition question with answer cards. Policy lookup returned
   the 30-day clause with citation `A-WINDOW`. No random-UUID error occurred on HTTPS.
5. This deliberately created one unfinished fictional return case, not an RMA.
   No inventory was marked returned and no real refund or notification occurred.
6. External direct TCP checks for ports `8000`, `5432` and `11434` did not connect.
   Docker output separately confirmed the intended bindings. These point-in-time
   checks are not a comprehensive security audit or uptime guarantee.

## Limits and handoff

- Use the HTTPS link above, not an IP/HTTP link or a localhost link.
- Fictional-account selection is intentionally public and is **not authentication**.
  Visitors can modify simulated account cases. Do not enter real personal data,
  passwords or payment information. The proxy alone does not make the system
  production-secure.
- CPU model quality, full real-model application acceptance and a two-version image
  rollback rehearsal remain separate tasks; public reachability does not pass them.
- To withdraw access, change the private `.env` binding back to `127.0.0.1`, recreate
  only the frontend with the same Compose command, and verify the URL is unreachable.
- The updated LaTeX source and its live editor preview contain this endpoint. The
  older committed exported PDF was not separately regenerated during this edit.
