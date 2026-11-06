# -*- coding: utf-8 -*-
"""把数据库里已有的转写结果补写成 data/records 下的 txt 存档（一次性用，可重复跑）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402
import records  # noqa: E402


def main():
    db.init()
    with db.connect() as con:
        rows = list(con.execute(
            "SELECT * FROM tasks WHERE status='done' AND length(coalesce(text,''))>0"
            " ORDER BY created_at"))
    made = 0
    for r in rows:
        p = records.save(dict(r))
        if os.path.exists(p):
            made += 1
    print("补写完成：%d / %d 条，目录 %s" % (made, len(rows), records.RECORDS_DIR))


if __name__ == "__main__":
    main()
