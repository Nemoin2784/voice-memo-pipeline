# -*- coding: utf-8 -*-
"""识别结果纠错：读 corrections.txt 里的「错词 => 正确词」规则做替换。

规则文件格式（UTF-8，一行一条）：
    # 注释
    添然 => 天然
    监绍人 => 监票人

被 transcribe.py / transcribe_para.py 共用，默认读项目根目录的 corrections.txt。
"""
import os

DEFAULT_FIX = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "corrections.txt")


def load_rules(path):
    """返回 [(错词, 正确词), ...]，按文件里的顺序。"""
    rules = []
    if not path or not os.path.isfile(path):
        return rules
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "=>" in s:
                old, new = s.split("=>", 1)
            elif "\t" in s:
                old, new = s.split("\t", 1)
            else:
                continue
            old, new = old.strip(), new.strip()
            if old:
                rules.append((old, new))
    return rules


def apply_rules(text, rules):
    """按顺序替换，返回 (新文本, [(错词, 正确词, 替换次数), ...])。"""
    stats = []
    if not text:
        return text, stats
    for old, new in rules:
        n = text.count(old)
        if n:
            text = text.replace(old, new)
            stats.append((old, new, n))
    return text, stats


def apply_to_result(result, rules, key="text", seg_key="segments"):
    """就地纠正 result 的 text 与 segments[].text，返回统计列表。"""
    stats = []
    if result.get(key):
        result[key], stats = apply_rules(result[key], rules)
    for seg in result.get(seg_key) or []:
        seg["text"], s2 = apply_rules(seg["text"], rules)
        stats.extend(s2)
    return stats


def format_stats(stats):
    return "，".join("%s→%s×%d" % (o, n, c) for o, n, c in stats)
