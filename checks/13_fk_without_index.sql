-- id: fk_without_index
-- title: Foreign keys without a supporting index
-- why: Deleting or updating a parent row scans the child table for references when the foreign-key columns have no index. Joins on those columns are slow too.
-- next: Create an index on the listed columns with CREATE INDEX CONCURRENTLY (outside a transaction) in a migration.
-- runbook: runbooks/06-indexes.md (full kit)
-- ok: Every foreign key has an index on its columns.
SELECT CASE WHEN c.reltuples >= 10000 THEN 'warning' ELSE 'info' END AS severity,
       n.nspname AS schemaname, c.relname AS table_name, con.conname AS constraint_name,
       (SELECT string_agg(a.attname, ', ' ORDER BY k.ord)
          FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum) AS fk_columns,
       con.confrelid::regclass::text AS parent_table,
       greatest(c.reltuples, 0)::bigint AS approx_rows
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE con.contype = 'f'
  AND NOT EXISTS (
        SELECT 1 FROM pg_index i
        WHERE i.indrelid = con.conrelid AND i.indisvalid
          AND (string_to_array(i.indkey::text, ' ')::int2[])[1:array_length(con.conkey, 1)] @> con.conkey
          AND (string_to_array(i.indkey::text, ' ')::int2[])[1:array_length(con.conkey, 1)] <@ con.conkey)
ORDER BY c.reltuples DESC
LIMIT 30;
