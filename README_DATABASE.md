# AgentSpace ERP University — Database read-only connector V2

## Scope
Extends prior ERP pilot with SQLAlchemy adapter for PostgreSQL, MySQL and SQL Server (pyodbc driver installed separately). ERP vendor unknown: DBA must create *two normalized, sanitized views* exposing only these logical columns:
- ai_assets_view: asset_id, name, department, original_cost, book_value
- ai_finance_view: entry_id, asset_id, amount, account, description

The mapping `ERP_VIEW_MAPPING` maps logical columns to DBA-created view columns; view names must be simple identifiers. Database users **must have SELECT permission only on these views**, not on underlying tables. Revoke writes and schema access; enforce network restrictions, TLS and server-side statement timeout. Never use a production superuser. Database URL is read from environment and must be stored as a VPS secret, not committed. Avoid personal data in views.

## Launch
1. Copy `.env.example` to `.env`, create different 32+ character ADMIN_TOKEN and APPROVER_TOKEN.
2. For offline pilot, keep `ERP_SOURCE=replica` and import approved CSV exports as described in `README_READONLY.md`.
3. For real read-only DB, set `ERP_SOURCE=database`, `ERP_DATABASE_URL`, and `ERP_VIEW_MAPPING`. Ensure DBA approves view definitions and read-only grants.
4. `docker compose up -d --build`; bind only loopback and place behind TLS reverse proxy, SSO and network ACL before external exposure.
5. API `/api/erp/reconcile` and `/api/erp/readonly/assets` use ADMIN_TOKEN. `/api/approvals/{id}` uses distinct APPROVER_TOKEN and JSON `{"approve":true,"reason":"Reviewed evidence"}`.

## Safety and limitations
- Database connector emits SELECT statements from fixed allowlisted view and column names only. No LLM-generated SQL or DB writes.
- Comparison checks duplicate asset IDs, invalid book values, and orphan finance asset references. It does **not** equate finance entry amount to asset cost, because journal semantics differ.
- Limit 10,000 records per domain; exceeding it aborts reconciliation. For production use keyset pagination with immutable snapshots and reconciliation batches.
- Approval changes local workflow status only, never external ERP. Separate approver credential is a pilot control, not a substitute for identity-bound RBAC/SSO, dual control or immutable audit trails.
- WebSocket broadcasts status events; original dashboard's agent updates are logical, not synchronized 3D avatar animation.
- Jobs run in-process and are not durable across restarts; use Redis/Celery or a queue before production.
- Avoid exposing raw ERP rows to third-party AI without institutional authorization, data minimization and applicable privacy review.
- **Not production-ready**: validate DB dialect/driver, migrations, threat model, SSO, audit retention, data classification and deployment security first.
