-- id: connections
-- title: Connection usage
-- why: When client connections approach max_connections, new requests fail with "too many clients" and latency climbs while pools wait.
-- next: If usage is high, check idle and idle-in-transaction counts first; a pooler (PgBouncer) usually beats raising max_connections.
-- runbook: runbooks/02-connections-exhausted.md (full kit)
-- ok: n/a
SELECT CASE WHEN used >= mx * 0.95 THEN 'critical'
            WHEN used >= mx * 0.80 THEN 'warning'
            ELSE 'info' END AS severity,
       used AS client_connections, mx AS max_connections,
       round(100.0 * used / mx, 1) AS pct_used,
       active, idle, idle_in_tx, waiting_on_lock
FROM (SELECT count(*) AS used,
             count(*) FILTER (WHERE state = 'active') AS active,
             count(*) FILTER (WHERE state = 'idle') AS idle,
             count(*) FILTER (WHERE state LIKE 'idle in transaction%') AS idle_in_tx,
             count(*) FILTER (WHERE wait_event_type = 'Lock') AS waiting_on_lock,
             current_setting('max_connections')::int AS mx
      FROM pg_stat_activity
      WHERE backend_type = 'client backend') s;
