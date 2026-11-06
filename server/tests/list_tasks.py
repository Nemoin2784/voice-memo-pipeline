# -*- coding: utf-8 -*-
"""列出任务：默认只看还没被取走的完成项。"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


def fmt(ts):
    return time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else "-"


def main():
    only_pending = "--all" not in sys.argv
    with db.connect() as con:
        sql = "SELECT id, filename, duration, status, coalesce(delivered,0) d, client," \
              " created_at, length(coalesce(text,'')) n FROM tasks"
        if only_pending:
            sql += " WHERE status='done' AND coalesce(delivered,0)=0"
        sql += " ORDER BY created_at"
        rows = list(con.execute(sql))
    print("count:", len(rows))
    for r in rows:
        print("%s  %-34s %7.1fs %-6s d=%d %-12s %s  %d字"
              % (fmt(r["created_at"]), r["filename"][:34], r["duration"] or 0,
                 r["status"], r["d"], r["client"] or "-", r["id"], r["n"]))


if __name__ == "__main__":
    main()
