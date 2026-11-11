# AgentSpace ERP Cloud MVP

A runnable FastAPI + SQLite multi-agent workflow with 6 real LLM role calls, read-only ERP demo data tool, durable jobs/steps/events, explicit approval before writing a **demo** record, live WebSocket dashboard, and the previous 3D office as a separate embedded prototype.

## Quick start (VPS Ubuntu, Docker Compose)

```bash
cp .env.example .env
# Set ADMIN_TOKEN to a random value of at least 24 characters and OPENAI_API_KEY to a valid key.
mkdir -p data && chmod 777 data # for demo; use chown 10001:10001 data in production
sudo docker compose up -d --build
```

Access locally at http://127.0.0.1:8000. For public use, put Caddy/Nginx in front with HTTPS, authentication, rate limiting, and domain; do **not** publish port 8000 directly. Compose binds only 127.0.0.1. Example Caddyfile:

```
erp.example.com {
  reverse_proxy 127.0.0.1:8000
}
```

Configure DNS and firewall, then open https://erp.example.com. Enter ADMIN_TOKEN in dashboard. API key stays on server.

## What is real

- Actual OpenAI chat-completions API requests, six sequential role-specific LLM steps.
- Real read-only tool query of a SQLite demo ERP records table, passed as context.
- Persistent jobs, agent steps, approval decisions, event history, demo records.
- Human approval required for demo record creation; rejection works.
- WebSocket event notifications trigger UI refresh.

## Important limitations

- **The embedded 3D office is the previous prototype and is NOT wired to live agent state**; the adjacent dashboard is the authoritative realtime status view. Do not interpret avatar movement as backend execution.
- SQLite is seeded with synthetic sample data; this app does NOT integrate with a production ERP, nor send email or execute arbitrary code.
- Worker is an in-process task: if server restarts mid-run, unfinished jobs stay marked running. For production use Celery/RQ with Redis, retries, idempotency and recovery.
- Single admin token, no per-user RBAC, no SSO, no multi-tenant isolation, no CSRF protections beyond Bearer-token API usage. WebSocket token is passed in URL and may be logged by proxies; replace with secure session-based auth before public deployment.
- No hard budgets, concurrency queue across processes, or model usage accounting. Limit access and configure API spend caps.
- Demo approval writes a synthetic record with amount=0, not an accounting transaction. Never use this workflow as authorization for financial payments.
- API errors can appear in audit event text; review logging policy before using sensitive data.

## API

`GET /api/snapshot`, `POST /api/jobs`, `POST /api/approvals/{id}`, `WS /ws?token=...`.

## Next production milestones

1. Auth/OIDC, RBAC, tenants, full audit immutability.
2. Postgres + Redis durable queue and worker recovery.
3. Connector adapters for ERP modules, scoped read/write tools, data classification.
4. Human approval by policy and transaction-level validation.
5. Bind 3D avatars to backend agent events (currently not implemented).
6. Tests, monitoring, budgets, backups, secrets manager, security review.
