# -*- coding: utf-8 -*-
"""把指定任务标记为已取走（不影响用户自己的录音）。

用法: python tests/mark_ids.py <task_id> [...]
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402


def main():
    ids = sys.argv[1:]
    if not ids:
        print("用法: python tests/mark_ids.py <task_id> [...]")
        return 2
    with db.connect() as con:
        for tid in ids:
            n = con.execute("UPDATE tasks SET delivered=1 WHERE id=?", (tid,)).rowcount
            print(tid, "updated" if n else "not found")
        con.commit()
    print("pending:", db.pending_counts())
    for r in db.connect().execute("SELECT id, filename, status, coalesce(delivered,0) d"
                                  " FROM tasks WHERE status!='done' ORDER BY created_at"):
        print(dict(r))


if __name__ == "__main__":
    main()
