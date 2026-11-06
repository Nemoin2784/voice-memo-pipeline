# -*- coding: utf-8 -*-
"""检查 hidden 是否会混进取件：打印 next_deliverable 与待取件计数。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


def main():
    db.init()
    nxt = db.next_deliverable()
    print("next_deliverable ->", (nxt["id"], nxt["filename"]) if nxt else None)
    print("deliverable 计数 ->", len(db.list_tasks(200, undelivered=True)))
    with db.connect() as con:
        rows = con.execute(
            "SELECT id, filename, coalesce(hidden,0) h, coalesce(delivered,0) d"
            " FROM tasks WHERE status='done' ORDER BY finished_at DESC LIMIT 5").fetchall()
    for r in rows:
        print("  %s %-14s hidden=%s delivered=%s" % (r["id"], r["filename"], r["h"], r["d"]))


if __name__ == "__main__":
    main()
