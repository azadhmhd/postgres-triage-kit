-- id: sequence_exhaustion
-- title: Sequences close to their limit
-- why: When an integer ID sequence hits its maximum (2,147,483,647 for integer columns), every insert fails. Moving the column to bigint on a large table takes planning.
-- next: Plan the move to bigint now (new column + backfill, or a blocking ALTER in a maintenance window). Don't just reset the sequence.
-- runbook: runbooks/09-disk-wal-and-limits.md (full kit)
-- ok: No sequence is above 75% of its limit.
SELECT CASE WHEN pct >= 90 THEN 'critical' ELSE 'warning' END AS severity,
       sequence_name, used_by, data_type, last_value, limit_value, pct
FROM (SELECT s.schemaname || '.' || s.sequencename AS sequence_name,
             coalesce(d.col, '') AS used_by,
             coalesce(d.typ, s.data_type::text) AS data_type,
             s.last_value,
             least(s.max_value, CASE d.typ WHEN 'smallint' THEN 32767 WHEN 'integer' THEN 2147483647 ELSE s.max_value END) AS limit_value
      FROM pg_sequences s
      LEFT JOIN LATERAL (
           SELECT a.attrelid::regclass::text || '.' || a.attname AS col, format_type(a.atttypid, NULL) AS typ
           FROM pg_depend dep
           JOIN pg_attribute a ON a.attrelid = dep.refobjid AND a.attnum = dep.refobjsubid
           WHERE dep.objid = (quote_ident(s.schemaname) || '.' || quote_ident(s.sequencename))::regclass
             AND dep.classid = 'pg_class'::regclass AND dep.refclassid = 'pg_class'::regclass
             AND dep.deptype IN ('a', 'i')
           LIMIT 1) d ON true
      WHERE s.last_value IS NOT NULL AND s.increment_by > 0) x
CROSS JOIN LATERAL (SELECT round(100.0 * last_value / limit_value, 1) AS pct) p
WHERE pct >= 75
ORDER BY pct DESC;
