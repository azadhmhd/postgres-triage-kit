#!/usr/bin/env python3
"""Postgres Triage Kit: read-only PostgreSQL diagnostics that point to a runbook.

Usage examples (see README.md for more):
    python3 triage.py "postgresql://app@db.internal:5432/app"
    python3 triage.py --psql "docker exec -i my-db psql -U postgres app"
    python3 triage.py --list

Requires Python 3.9+ and psql 12+ (or a --psql command that runs one). Standard library only.
"""
import argparse
import csv
import datetime
import html
import io
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

VERSION = "1.0.0"
ROOT = Path(__file__).resolve().parent
ORDER = ["critical", "warning", "info", "ok", "skipped"]
ICON = {"critical": "🔴", "warning": "🟠", "info": "🔵", "ok": "🟢", "skipped": "⚪"}

# Every session starts read-only, with short timeouts, so a check can never write,
# queue behind a lock for long, or keep running on a struggling server.
PREAMBLE = """\
SET application_name = 'postgres-triage-kit';
SET statement_timeout = '5s';
SET lock_timeout = '1s';
SET default_transaction_read_only = on;
BEGIN READ ONLY;
"""

# Third safety layer: refuse any check whose SQL (minus comments and string literals) contains
# a statement or function that could change data, settings or other sessions. This also covers
# pg_terminate_backend/pg_cancel_backend, which a read-only transaction would allow.
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|grant|revoke|vacuum|analyze|reindex|"
    r"cluster|copy|call|do|lock|comment|refresh|into|execute|prepare|listen|notify|reset|set|"
    r"nextval|setval|pg_terminate_backend|pg_cancel_backend|pg_reload_conf|pg_rotate_logfile|"
    r"pg_switch_wal|pg_create_\w+|pg_drop_\w+|pg_advisory\w*|pg_read_\w*file|lo_\w+|dblink\w*)\b",
    re.I,
)


def strip_sql(sql):
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.S)
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def unsafe_words(sql):
    return sorted({m.group(0).lower() for m in FORBIDDEN.finditer(strip_sql(sql))})


def load_checks(server_version=None):
    checks = []
    for path in sorted((ROOT / "checks").glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        meta = dict(re.findall(r"^--\s*(\w+):\s*(.+?)\s*$", text, flags=re.M))
        meta.update(file=path.name, sql=text)
        if server_version is not None:
            if server_version < int(meta.get("min_version", 0)):
                continue
            if server_version > int(meta.get("max_version", 10**7)):
                continue
        checks.append(meta)
    return checks


class Psql:
    def __init__(self, base_cmd, min_duration):
        self.cmd = base_cmd + ["-X", "-q", "-v", "ON_ERROR_STOP=1", "-v", f"min_duration={min_duration}",
                               "--csv", "-P", "pager=off"]

    def query(self, sql):
        """Run one read-only query. Returns (rows, error)."""
        script = PREAMBLE + sql.strip().rstrip(";") + ";\nCOMMIT;\n"
        try:
            p = subprocess.run(self.cmd, input=script, capture_output=True, text=True, timeout=90)
        except FileNotFoundError:
            return None, f"could not run {self.cmd[0]!r}: is psql installed and on PATH?"
        except subprocess.TimeoutExpired:
            return None, "psql did not finish within 90 seconds"
        if p.returncode != 0:
            err = [ln for ln in p.stderr.splitlines() if ln.strip()]
            return None, (err[0] if err else f"psql exited with {p.returncode}").removeprefix("psql:<stdin>:")
        return list(csv.DictReader(io.StringIO(p.stdout))), None


def run_check(psql, check, extensions):
    result = {k: check.get(k, "") for k in ("id", "title", "why", "next", "runbook", "file")}
    bad = unsafe_words(check["sql"])
    if bad:
        return dict(result, status="skipped", rows=[], note=f"refused: not read-only ({', '.join(bad)})")
    need = check.get("requires")
    if need and need not in extensions:
        return dict(result, status="skipped", rows=[],
                    note=f"needs the {need} extension (see runbooks/05-slow-queries.md#enable-pg_stat_statements)")
    rows, err = psql.query(check["sql"])
    if err:
        return dict(result, status="skipped", rows=[], note=f"query failed: {err}")
    for r in rows:
        r.setdefault("severity", "info")
    status = min((r.pop("severity") for r in rows), key=ORDER.index, default="ok")
    note = "" if rows else check.get("ok", "")
    return dict(result, status=status, rows=rows, note=note)


# ---------- reports ----------

def md_cell(v):
    return str(v).replace("|", "\\|").replace("\n", " ")


def to_markdown(rep):
    out = [f"# Postgres triage report", "",
           f"- Generated: {rep['generated_at']} by Postgres Triage Kit {VERSION}",
           f"- Server: PostgreSQL {rep['server']['version']} · database `{rep['server']['database']}`",
           f"- Summary: " + " · ".join(f"{ICON[s]} {rep['summary'][s]} {s}" for s in ORDER if rep['summary'][s]),
           "", "> Read-only report. Query text may contain data: review before sharing.", ""]
    for c in rep["checks"]:
        out += [f"## {ICON[c['status']]} {c['title']} ({c['status']})", ""]
        if c["status"] not in ("ok",):
            out += [f"**Why it matters:** {c['why']}", "", f"**Next step:** {c['next']}",
                    f"See `{c['runbook']}`.", ""]
        if c["note"]:
            out += [f"_{c['note']}_", ""]
        if c["rows"]:
            cols = list(c["rows"][0])
            out += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
            out += ["| " + " | ".join(md_cell(r[k]) for k in cols) + " |" for r in c["rows"]]
            out.append("")
    return "\n".join(out)


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1f23;--muted:#62666d;--card:#fff;--line:#e3e1db;--crit:#c0262d;--warn:#b35c00;--info:#1f5fae;--ok:#227a43;--skip:#7b7f86}
@media (prefers-color-scheme:dark){:root{--bg:#121316;--fg:#e9e7e2;--muted:#9da1a8;--card:#1a1c20;--line:#2c2f35;--crit:#ff6b6f;--warn:#ffa94d;--info:#74a9ff;--ok:#5fd08a;--skip:#9da1a8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:32px 16px 64px}h1{font-size:26px;margin:0 0 4px}.meta{color:var(--muted);margin:0 0 20px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 24px}.chip{border:1px solid var(--line);border-radius:999px;padding:4px 12px;background:var(--card);font-weight:600}
section{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--line);border-radius:8px;padding:16px 18px;margin:0 0 14px}
section.critical{border-left-color:var(--crit)}section.warning{border-left-color:var(--warn)}section.info{border-left-color:var(--info)}section.ok{border-left-color:var(--ok)}section.skipped{border-left-color:var(--skip)}
h2{font-size:17px;margin:0 0 8px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}.tag{font-size:12px;text-transform:uppercase;letter-spacing:.06em;font-weight:700}
.critical .tag{color:var(--crit)}.warning .tag{color:var(--warn)}.info .tag{color:var(--info)}.ok .tag{color:var(--ok)}.skipped .tag{color:var(--skip)}
p{margin:6px 0}.muted{color:var(--muted)}code{font:13px ui-monospace,SFMono-Regular,Menlo,monospace}
.scroll{overflow-x:auto;margin-top:10px}table{border-collapse:collapse;font:12.5px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;min-width:100%}
th,td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top;white-space:nowrap}td.wrap{white-space:normal;min-width:260px}th{color:var(--muted);font-weight:600}
.banner{border:1px dashed var(--line);border-radius:8px;padding:8px 12px;color:var(--muted);margin:0 0 20px;font-size:13px}
"""


def to_html(rep):
    e = html.escape
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Postgres triage report · {e(rep['server']['database'])}</title><style>{CSS}</style></head><body><main>",
             "<h1>Postgres triage report</h1>",
             f"<p class='meta'>PostgreSQL {e(rep['server']['version'])} · database <code>{e(rep['server']['database'])}</code> · {e(rep['generated_at'])} · Postgres Triage Kit {VERSION}</p>",
             "<div class='chips'>" + "".join(f"<span class='chip'>{ICON[s]} {rep['summary'][s]} {s}</span>" for s in ORDER if rep['summary'][s]) + "</div>",
             "<p class='banner'>Read-only report. Query text in this report may contain data: review it before sharing.</p>"]
    for c in rep["checks"]:
        parts.append(f"<section class='{c['status']}'><h2><span class='tag'>{c['status']}</span>{e(c['title'])}</h2>")
        if c["status"] != "ok":
            parts.append(f"<p><b>Why it matters:</b> {e(c['why'])}</p><p><b>Next step:</b> {e(c['next'])} "
                         f"<span class='muted'>See <code>{e(c['runbook'])}</code>.</span></p>")
        if c["note"]:
            parts.append(f"<p class='muted'><i>{e(c['note'])}</i></p>")
        if c["rows"]:
            cols = list(c["rows"][0])
            parts.append("<div class='scroll'><table><thead><tr>" + "".join(f"<th>{e(k)}</th>" for k in cols) + "</tr></thead><tbody>")
            for r in c["rows"]:
                parts.append("<tr>" + "".join(
                    f"<td class='{'wrap' if 'query' in k or k == 'definition' else ''}'>{e(str(r[k]))}</td>" for k in cols) + "</tr>")
            parts.append("</tbody></table></div>")
        parts.append("</section>")
    parts.append("</main></body></html>")
    return "\n".join(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only PostgreSQL triage. Nothing is changed on the server.")
    ap.add_argument("conninfo", nargs="?", help="connection URI or 'host=... dbname=...' (password: use PGPASSWORD or ~/.pgpass)")
    ap.add_argument("--psql", help="command that runs psql, e.g. \"docker exec -i db psql -U postgres app\" or \"kubectl exec -i pod -- psql -U app\"")
    ap.add_argument("--out", help="output folder (default: ./triage-report-<timestamp>)")
    ap.add_argument("--min-duration", type=int, default=60, help="seconds before an idle transaction or query counts as long (default 60)")
    ap.add_argument("--only", help="comma-separated check ids to run")
    ap.add_argument("--json", action="store_true", help="print the JSON report to stdout (for scripts and AI agents)")
    ap.add_argument("--list", action="store_true", help="list checks and exit")
    ap.add_argument("--version", action="version", version=f"Postgres Triage Kit {VERSION}")
    a = ap.parse_args(argv)

    if a.list:
        seen = set()
        for c in load_checks():
            if c["id"] not in seen:
                seen.add(c["id"])
                print(f"{c['id']:22} {c['title']}")
        return 0

    base = shlex.split(a.psql) if a.psql else ["psql"] + ([a.conninfo] if a.conninfo else [])
    psql = Psql(base, a.min_duration)
    log = sys.stderr if a.json else sys.stdout

    info, err = psql.query("SELECT current_setting('server_version_num')::int AS num, current_setting('server_version') AS version, "
                           "current_database() AS database, (SELECT coalesce(string_agg(extname, ','), '') FROM pg_extension) AS extensions")
    if err:
        print(f"Could not connect: {err}", file=sys.stderr)
        return 3
    srv = info[0]
    num = int(srv["num"])
    if num < 130000:
        print(f"PostgreSQL {srv['version']} is not supported: the kit needs PostgreSQL 13 or newer.", file=sys.stderr)
        return 3
    extensions = set(filter(None, srv["extensions"].split(",")))
    checks = load_checks(num)
    if a.only:
        wanted = {x.strip() for x in a.only.split(",")}
        checks = [c for c in checks if c["id"] in wanted]

    print(f"Postgres Triage Kit {VERSION}: PostgreSQL {srv['version']}, database {srv['database']}, {len(checks)} checks (read-only)", file=log)
    results = []
    for c in checks:
        r = run_check(psql, c, extensions)
        print(f"  {ICON[r['status']]} {r['status']:8} {r['id']}", file=log)
        results.append(r)
    results.sort(key=lambda r: ORDER.index(r["status"]))

    rep = dict(tool=f"Postgres Triage Kit {VERSION}",
               generated_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
               server=dict(version=srv["version"], version_num=num, database=srv["database"]),
               summary={s: sum(r["status"] == s for r in results) for s in ORDER},
               checks=results)

    out = Path(a.out or f"triage-report-{datetime.datetime.now():%Y%m%d-%H%M%S}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    (out / "report.md").write_text(to_markdown(rep), encoding="utf-8")
    (out / "report.html").write_text(to_html(rep), encoding="utf-8")
    print(f"Report: {out / 'report.html'} (also report.md, report.json)", file=log)
    if a.json:
        print(json.dumps(rep, indent=2))
    s = rep["summary"]
    return 2 if s["critical"] else 1 if s["warning"] else 0


if __name__ == "__main__":
    sys.exit(main())
