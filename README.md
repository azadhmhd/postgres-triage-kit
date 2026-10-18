# Postgres Triage Kit, free edition

Five read-only PostgreSQL checks for the problems that most often freeze production: connection
exhaustion, idle transactions, lock chains, foreign keys without indexes, and integer IDs about to
run out. One command, a ranked report, nothing to install.

```bash
export PGPASSWORD='...'     # or ~/.pgpass
python3 triage.py "postgresql://app_user@db.example.com:5432/app_db"
# Docker / Kubernetes / SSH:
python3 triage.py --psql "docker exec -i my-postgres psql -U postgres app_db"
```

Needs Python 3.9+ and `psql` 12+. Server: PostgreSQL 13–18. The report goes to
`./triage-report-<timestamp>/report.html` (plus `.md` and `.json`). Exit codes: `0` ok, `1` warnings,
`2` critical, `3` could not connect.

## Safe on production

Every check runs in a read-only transaction (`default_transaction_read_only = on`, `BEGIN READ ONLY`)
with `statement_timeout = 5s` and `lock_timeout = 1s`. The CLI also refuses any check whose SQL could
write or affect other sessions (for example `pg_terminate_backend`). There's no telemetry, and
reports stay on your machine. Reports can include query text, so review them before sharing.

## Included checks

| Id | Finds |
|---|---|
| connections | Usage against `max_connections`; active, idle, idle-in-transaction |
| idle_in_transaction | Sessions holding an open transaction while idle |
| blocking | Waiting queries, the lock they want, and the session blocking them |
| fk_without_index | Foreign keys whose columns have no index |
| sequence_exhaustion | Sequences above 75% of their column type's limit |

`runbooks/03-locks-and-blocking.md` is included. Every `.sql` file also runs on its own in psql.

## The full kit

[Postgres Triage Kit](https://azadhmhd.gumroad.com/l/postgres-triage-kit?ref=github) ($29, one-time) adds:

- 15 more checks: top queries (pg_stat_statements), long queries, vacuum and dead rows, stale
  statistics, wraparound, unused, duplicate and invalid indexes, sequential-scan hot spots,
  replication slots and lag, temp files, checkpoints, cache hit ratio, largest tables, server overview.
- 8 more runbooks (and a PDF), each with Signal → Confirm → Safe actions → Risky actions → Prevent,
  and ORM notes for Django, Rails, SQLAlchemy, Prisma, TypeORM and Laravel.
- A Claude Code skill and `AGENTS.md` instructions, so a coding agent can run the kit and propose
  fixes without applying them.
- Docker scenario tests across PostgreSQL 13–18.

## License

MIT, see [LICENSE](LICENSE). Postgres and PostgreSQL are trademarks of the PostgreSQL Community
Association of Canada; this project is independent and not endorsed by them.
