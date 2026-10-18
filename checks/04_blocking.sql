-- id: blocking
-- title: Queries waiting on locks, and who is blocking them
-- why: A single session holding a lock (often a migration or an idle transaction) can queue every request behind it. Requests for ACCESS EXCLUSIVE locks also block readers.
-- next: Look at the blocker first, not the waiters. If the blocker is idle in transaction or a stuck migration, cancelling or terminating that one PID clears the queue.
-- runbook: runbooks/03-locks-and-blocking.md
-- ok: No session is waiting on a lock.
SELECT CASE WHEN now() - w.query_start > interval '1 minute' THEN 'critical' ELSE 'warning' END AS severity,
       w.pid AS waiting_pid,
       date_trunc('second', now() - w.query_start) AS waiting_for,
       (SELECT string_agg(DISTINCT l.mode, ', ') FROM pg_locks l WHERE l.pid = w.pid AND NOT l.granted) AS wanted_lock,
       left(regexp_replace(w.query, '\s+', ' ', 'g'), 100) AS waiting_query,
       b.pid AS blocker_pid,
       b.state AS blocker_state,
       date_trunc('second', now() - b.xact_start) AS blocker_transaction_age,
       left(regexp_replace(b.query, '\s+', ' ', 'g'), 100) AS blocker_query
FROM pg_stat_activity w
CROSS JOIN LATERAL unnest(pg_blocking_pids(w.pid)) AS bp(pid)
JOIN pg_stat_activity b ON b.pid = bp.pid
WHERE w.wait_event_type = 'Lock'
ORDER BY w.query_start
LIMIT 30;
