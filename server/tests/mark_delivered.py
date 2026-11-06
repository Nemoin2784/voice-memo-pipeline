# -*- coding: utf-8 -*-
"""把已完成的旧任务标记为已取走，避免手机下一次 B 取到历史测试文本。"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


def main():
    with db.connect() as con:
        n = con.execute("UPDATE tasks SET delivered=1 WHERE status='done'").rowcount
        con.commit()
    print("marked delivered:", n)
    print("pending:", db.pending_counts())
    with db.connect() as con:
        for row in con.execute("SELECT id, filename, duration, status, coalesce(delivered,0) d,"
                               " substr(coalesce(text,''),1,30) t FROM tasks"
                               " ORDER BY created_at DESC LIMIT 5"):
            print(dict(row))


if __name__ == "__main__":
    main()
