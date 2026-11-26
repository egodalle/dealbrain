BEGIN;

CREATE OR REPLACE VIEW raw.table_counts AS
  SELECT 'opa_assessments'  AS table_name, COUNT(*) AS row_count FROM raw.opa_assessments
  UNION ALL
  SELECT 'violations',                      COUNT(*)              FROM raw.violations
  UNION ALL
  SELECT 'transfers',                       COUNT(*)              FROM raw.transfers
  UNION ALL
  SELECT 'delinquency',                     COUNT(*)              FROM raw.delinquency;

COMMIT;
