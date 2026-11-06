"""把测试录音从「最近转写记录」清单里收起来（hidden=1），文本和 txt 存档都不动。

背景：早先为了让它们沉底，把 finished_at 抹成了 1.0；这里顺手把时间还原成
deliver_at（实为转写完成时间），再把 hidden 置 1。

用法（在 server 目录下）：
    ..\\..\\.tools\\python310\\python.exe tests\\hide_test_tasks.py          # 只看
    ..\\..\\.tools\\python310\\python.exe tests\\hide_test_tasks.py --apply  # 执行
    ..\\..\\.tools\\python310\\python.exe tests\\hide_test_tasks.py --unhide  # 全部放回清单
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import db  # noqa: E402

PATTERNS = ("sample_zh%", "demo_%", "test_%", "语音备忘录-测试%")


def main(apply=False, unhide=False):
    db.init()  # 确保 hidden 列已迁移
    where = " OR ".join("filename LIKE ?" for _ in PATTERNS)
    with db.connect() as con:
        rows = con.execute(
            "SELECT id, filename, status, created_at, finished_at, deliver_at, hidden FROM tasks"
            " WHERE %s ORDER BY created_at DESC" % where, PATTERNS).fetchall()
        print("匹配 %d 条测试录音" % len(rows))
        if not apply and not unhide:
            for r in rows[:8]:
                print("  %s  %-14s hidden=%s" % (r["id"], r["filename"], r["hidden"]))
            return
        ids = [r["id"] for r in rows]
        if unhide:
            con.execute("UPDATE tasks SET hidden=0 WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
            print("已全部放回清单")
            return
        # 还原被我抹掉的时间（finished_at < 1000 说明是早先压到 1970 的那批）
        con.execute(
            "UPDATE tasks SET finished_at=coalesce(nullif(deliver_at,0), created_at)"
            " WHERE finished_at < 1000 AND id IN (%s)" % ",".join("?" * len(ids)), ids)
        con.execute("UPDATE tasks SET hidden=1 WHERE id IN (%s)" % ",".join("?" * len(ids)), ids)
        print("已收起 %d 条（清单里不再出现，文本/存档都还在）" % len(ids))


if __name__ == "__main__":
    main(apply="--apply" in sys.argv, unhide="--unhide" in sys.argv)
