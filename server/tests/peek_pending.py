# -*- coding: utf-8 -*-
"""看看现在有几条“待取件”，以及 hidden 的会不会混进 next_deliverable。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


def main():
    db.init()
    with db.connect() as con:
        rows = con.execute(
            "SELECT id, filename, delivered, coalesce(hidden,0) AS h"
            " FROM tasks WHERE status='done' AND coalesce(delivered,0)=0"
            " ORDER BY coalesce(deliver_at, finished_at, created_at)").fetchall()
    print("未取走 done 共 %d 条：" % len(rows))
    for r in rows:
        print("  %s  %-22s hidden=%s" % (r["id"], r["filename"], r["h"]))
    nxt = db.next_deliverable()
    print("next_deliverable ->", (nxt["id"], nxt["filename"]) if nxt else None)


if __name__ == "__main__":
    main()
