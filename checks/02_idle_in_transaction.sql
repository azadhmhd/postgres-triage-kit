-- id: idle_in_transaction
-- title: Sessions idle inside an open transaction
-- why: An open transaction holds its locks and stops vacuum from cleaning rows newer than its snapshot. This is a common cause of lock pile-ups and bloat.
-- next: Find the application code path that opens a transaction and waits (HTTP calls, user input, missing commit). Set idle_in_transaction_session_timeout.
-- runbook: runbooks/03-locks-and-blocking.md
-- ok: No session has been idle in a transaction longer than the threshold.
SELECT CASE WHEN now() - state_change > interval '10 minutes' THEN 'critical' ELSE 'warning' END AS severity,
       pid, usename, application_name, client_addr,
       date_trunc('second', now() - xact_start) AS transaction_age,
       date_trunc('second', now() - state_change) AS idle_for,
       left(regexp_replace(query, '\s+', ' ', 'g'), 120) AS last_query
FROM pg_stat_activity
WHERE state LIKE 'idle in transaction%'
  AND now() - state_change > (:'min_duration' || ' seconds')::interval
ORDER BY state_change
LIMIT 20;
