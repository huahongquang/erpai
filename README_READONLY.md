# AgentSpace ERP – Read-only Pilot

## Scope
This is a development pilot, NOT a production ERP integration. It reads a local SQLite replica populated from explicitly reviewed CSV exports. It does not connect to an ERP server, and never writes to production ERP. Approval only records the decision in the AgentSpace audit database.

## Import
Export exactly these UTF-8 CSV columns (header order arbitrary):
- assets.csv: `asset_id,name,department,original_cost,book_value`
- finance.csv: `entry_id,asset_id,amount,account,description`

Run `python readonly_gateway.py data/erp_readonly.sqlite3 assets.csv finance.csv import` locally. Confirm source authorization, remove unnecessary personal information and verify totals before importing. CSV values are untrusted; review and validate them.

## Run
Set ADMIN_TOKEN (minimum 24 characters), OPENAI_API_KEY, and ERP_READONLY_DB=/app/data/erp_readonly.sqlite3 in .env. Then `docker compose up -d --build`. Backend binds localhost; place HTTPS reverse proxy and SSO/RBAC in front before any shared use. Dashboard uses same admin token; never expose to public Internet as-is.

GET `/api/erp/readonly/assets`, `/api/erp/readonly/finance`, `/api/erp/reconcile` with Authorization Bearer token. Responses are limited to 500 records and reconciliation is explicitly marked partial if capped. Production needs pagination, stronger source validation, per-user roles, encrypted secrets, persistent queues, audit integrity, observability, tests, backups, and security review.

## Approval controls
Approval is a review of the AI report only. It is NOT permission to change ERP data. For production, implement maker-checker separation, verified identity, scope-bound approvals, immutable audit trails, idempotency, and an independently reviewed write connector.
