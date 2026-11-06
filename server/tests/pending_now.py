# -*- coding: utf-8 -*-
"""看一眼现在有没有“排队中/转写中/已完成未取走”的任务，方便排查取件行为。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402

db.init()
with db.connect() as con:
    rows = con.execute(
        "select id, filename, status, delivered, length(coalesce(text,'')) as n"
        " from tasks where status in ('queued','running')"
        " or (status='done' and coalesce(delivered,0)=0) order by created_at").fetchall()
for r in rows:
    print("%-14s %-24s %-8s delivered=%s chars=%s"
          % (r["id"], r["filename"], r["status"], r["delivered"], r["n"]))
print("共 %d 条待处理/待取" % len(rows))
