# -*- coding: utf-8 -*-
"""组合麻将 — 冒险模式剧情文本解析

剧情存于 story/ 文件夹, 每个关卡一个 txt (特殊情况可指定其它文件)。
格式约定:
  - 每行: 「角色名 对话内容」, 角色名取第一个空格前的部分
  - 行内无空格: 自动继承上一句的角色 (说话内容就是整行)
  - 空行: 忽略
  - 独立一行 fight: 战前/战后分界。fight 之前的行是战前剧情(播放完进入战斗),
    之后的行是战后剧情(仅胜利时播放)
  - 预留: 每条对话带 choices 字段(目前恒为 None), 供未来"选择框"分支使用
"""
import os

# 剧情文件夹: Q:/openai/story
STORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "story")


def parse_story(path):
    """解析剧情txt, 返回 {'before': [对话], 'after': [对话]}

    每条对话: {'speaker': 角色名, 'text': 内容, 'choices': None}
    """
    before, after = [], []
    speaker = None
    mode = "before"

    if not os.path.exists(path):
        return {"before": before, "after": after}

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line == "fight":
                mode = "after"
                continue
            if " " in line:
                sp, _, text = line.partition(" ")
                speaker = sp.strip()
            else:
                text = line
            entry = {"speaker": speaker or "旁白", "text": text, "choices": None}
            if mode == "before":
                before.append(entry)
            else:
                after.append(entry)

    return {"before": before, "after": after}


def get_story(filename):
    """按文件名加载剧情 (filename 形如 '1-1.txt')"""
    path = os.path.join(STORY_DIR, filename)
    return parse_story(path)
