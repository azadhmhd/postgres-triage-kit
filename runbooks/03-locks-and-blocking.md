# 03 · Locks and blocking

## Signal

Requests hang and then time out. Many queries are "active" but doing nothing. Often right after a
deploy, a migration or a manual `psql` session.

## Confirm

- Kit check **blocking** lists every waiting query with its **blocker**. Read `blocker_state`:
    - `idle in transaction`: an application or human opened a transaction and walked away. It's the
    usual culprit.
    - `active` running DDL (`ALTER TABLE`, `CREATE INDEX` without `CONCURRENTLY`): a migration. See [07](07-safe-migrations.md).
- Kit check **idle_in_transaction** shows the same sessions even before anything is blocked.
- Lock queues: a waiting `ALTER TABLE` (wanting `AccessExclusiveLock`) also blocks every later
  `SELECT` on that table, even though the reads don't conflict with each other. A short-running
  migration stuck behind one long query can freeze a whole table this way.

Find the root blocker (the session that blocks others but isn't waiting itself):

```sql
SELECT pid, state, now() - xact_start AS xact_age, left(query, 120) AS query
FROM pg_stat_activity
WHERE pid IN (SELECT unnest(pg_blocking_pids(pid)) FROM pg_stat_activity)
  AND cardinality(pg_blocking_pids(pid)) = 0;
```

## Safe actions

1. Deal with the **root blocker**, not the waiters.
2. If it's a query you can retry: `SELECT pg_cancel_backend(<pid>);` cancels the current statement.
3. If it's `idle in transaction`, cancelling does nothing (there is no running statement).
   `SELECT pg_terminate_backend(<pid>);` ends the session and rolls back its transaction. That is
   usually correct for an abandoned transaction, but confirm it isn't a half-finished data fix first.
4. If it's a migration, cancel it and re-plan it with [07](07-safe-migrations.md).

## Risky actions

- Terminating waiters one by one: the queue refills behind the same blocker.
- Terminating a session in the middle of a long data migration: the rollback takes time and holds
  locks while it runs.

## Prevent

- `ALTER ROLE app_user SET idle_in_transaction_session_timeout = '60s';` ends abandoned transactions
  automatically. Keep it off, or longer, for roles that legitimately hold transactions (some batch jobs).
- In every migration: `SET lock_timeout = '3s';` so a migration gives up instead of freezing traffic.
  Retry it later.
- Keep transactions short. Never make HTTP calls, send emails or wait for user input inside one.

| Stack | Common source of idle transactions |
|---|---|
| Django | `ATOMIC_REQUESTS = True` with slow external calls in views; `transaction.atomic()` around API calls |
| Rails | `ActiveRecord::Base.transaction` blocks that call external services |
| SQLAlchemy | Sessions not closed (`autobegin`), long-lived `Session` objects in workers |
| Prisma | Long `$transaction(async (tx) => ...)` callbacks; interactive transactions with network calls |
| TypeORM | `queryRunner.startTransaction()` without `release()` in `finally` |
| Laravel | `DB::transaction()` around queue dispatch or HTTP calls |
