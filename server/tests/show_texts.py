# -*- coding: utf-8 -*-
"""取回指定任务的文本，打印长度与开头，并检查是否互不相同。"""
import hashlib
import sys
import urllib.request

BASE = "http://127.0.0.1:8765"


def main():
    ids = sys.argv[1:]
    if not ids:
        print("用法: python tests/show_texts.py <task_id> [...]")
        return 2
    seen = {}
    for tid in ids:
        with urllib.request.urlopen("%s/api/task/%s/text?wait=5" % (BASE, tid), timeout=30) as r:
            txt = r.read().decode("utf-8")
        h = hashlib.md5(txt.encode("utf-8")).hexdigest()[:8]
        print("%s  %4d 字  %s  %s" % (tid, len(txt), h, txt[:40].replace("\n", " / ")))
        seen.setdefault(h, []).append(tid)
    dup = {h: v for h, v in seen.items() if len(v) > 1}
    print("重复文本:", dup if dup else "无（三份互不相同）")
    return 0 if not dup else 1


if __name__ == "__main__":
    sys.exit(main())
