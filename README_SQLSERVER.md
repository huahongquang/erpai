# AgentSpace ERP University – SQL Server V3

## Scope and limits
This is a deployable **pilot scaffold**, not a production-approved integration. SQL Server was NOT connected or tested with university data. The source ERP schema is unknown. No real reconciliation can run until a DBA creates the two approved views and a least-privilege account. No ERP write operations are implemented.

## Preparation by DBA
1. Identify source schema, asset identifiers, accounting ledger relationships, currency, depreciation/impairment rules, accounting period, and soft-deleted records. Agree a signed-off mapping with Asset Management and Finance.
2. Adapt `sql/provision_template.sql` (commented example, not ready-to-run). Create `ai_read.v_assets` and `ai_read.v_finance` with only necessary columns. Avoid student/personnel details, personal identifiers, sensitive transaction narratives.
3. Create a dedicated SQL login/user with **only SELECT on those two views**; deny all direct source-table access. Never use `db_datareader`, `db_owner`, or `sysadmin`.
4. Configure SQL Server TLS certificate with a trusted CA and hostname matching `ERP_SQL_HOST`; ODBC uses Encrypt=yes, TrustServerCertificate=no. Use VPN/private subnet, firewall allowlist VPS egress IP to SQL Server 1433. Prefer a read-only replica to avoid affecting the ERP production workload.
5. Test denied INSERT/UPDATE/DELETE/EXECUTE and denied SELECT on unrelated tables from the application account.

## VPS setup
Use a Linux amd64 VPS, Docker Engine + Compose, private VPN connectivity to SQL Server. The Dockerfile installs Microsoft's ODBC Driver 18 (Debian 12 package source); verify vendor package signing and availability during build. If the image base changes, update the package repository.

```
cp .env.sqlserver.example .env
# edit .env, generate separate random secrets; do not commit secrets
chmod 600 .env
mkdir -p data
sudo chown -R 10001:10001 data
docker compose up -d --build
docker compose logs --tail=100 agentspace
```

Backend binds 127.0.0.1:8000 only. Publish with HTTPS reverse proxy and identity-aware access controls, not by exposing port 8000. Restrict WebSocket access as well. Keep `ALLOW_ERP_DATA_TO_LLM=false` until legal/privacy approval; this intentionally prevents agent LLM tasks from receiving ERP rows. API reconciliation can still run. Existing MVP uses bearer tokens and local SQLite history: **not adequate for university production**. Add SSO/RBAC, audit retention, database encryption, rate limits, backup/restore and incident response before live use.

## Test plan (staging first)
1. `python -m unittest discover -s tests -v` (requires sqlalchemy + pyodbc installed).
2. Validate trusted TLS certificate and private connectivity from VPS container. Do not disable certificate checks.
3. With read-only account, verify `SELECT TOP (1) * FROM ai_read.v_assets` and `ai_read.v_finance`; test all forbidden operations using an isolated disposable test object and DBA-approved procedure, never destructive commands on production.
4. Seed staging views with known cases: valid asset, duplicate asset ID, negative residual value, residual > original cost, orphan finance asset, null asset ID; compare exception counts.
5. Call `GET /api/erp/reconcile` with `Authorization: Bearer <ADMIN_TOKEN>`; verify counts and exceptions. If >10,000 rows per domain, reconciliation must fail closed instead of silently truncating.
6. Create job, inspect agent events and WebSocket updates, submit approval/rejection with separate approver token. Confirm no write access to ERP and that approval only records a decision in AgentSpace.
7. Restart containers; verify persistence of local history, recovery of the API, and backups. Run concurrency/load tests against staging; evaluate snapshot consistency of both views before accepting financial reconciliation.
8. Review false positives with Finance/Asset owners; only then consider production read-only rollout.

## Known limitations
The existing job workflow is sequential and not durable across process crash; the WebSocket publishes job/step events, not fully synchronized 3D avatar animation. Pagination across changing source data is not snapshot-consistent; use a DBA-approved snapshot/ETL replica for audit-grade reconciliation. Row IDs may not be unique; duplicate detection is performed but pagination order is not stable for ties. No automated proof of reconciliation completeness or ledger-to-asset balance equality. Approval tokens do not establish individual identity. No direct SQL execution is accepted from AI agents.
