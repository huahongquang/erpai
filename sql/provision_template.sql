-- TEMPLATE ONLY: DBA must replace source tables and columns after schema discovery.
-- Execute as DBA in the ERP database, not as the application login.
CREATE SCHEMA ai_read;
GO
-- Example only. Replace dbo.REPLACE_ASSET_TABLE and fields with approved schema.
-- CREATE VIEW ai_read.v_assets AS SELECT CAST(asset_code AS nvarchar(100)) AS asset_id,
-- asset_name AS name, department_name AS department,
-- original_cost, book_value FROM dbo.REPLACE_ASSET_TABLE;
-- CREATE VIEW ai_read.v_finance AS SELECT CAST(entry_code AS nvarchar(100)) AS entry_id,
-- CAST(asset_code AS nvarchar(100)) AS asset_id, amount, account, description
-- FROM dbo.REPLACE_FINANCE_TABLE;
-- CREATE LOGIN agentspace_reader WITH PASSWORD = 'USE_SECURE_DBA_SECRET', CHECK_POLICY=ON;
-- CREATE USER agentspace_reader FOR LOGIN agentspace_reader;
-- GRANT SELECT ON OBJECT::ai_read.v_assets TO agentspace_reader;
-- GRANT SELECT ON OBJECT::ai_read.v_finance TO agentspace_reader;
-- GRANT CONNECT TO agentspace_reader;
-- Test DENIED access to underlying tables, UPDATE, INSERT, DELETE and EXECUTE.
-- Never grant db_datareader, db_owner, or broad schema permissions.
