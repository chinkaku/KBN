# -*- coding: utf-8 -*-
"""组合麻将 — 冒险模式剧情文本解析

剧情存于 story/ 文件夹, 每个关卡一个 txt (特殊情况可指定其它文件)。
格式约定:
  - 每行: 「角色名 对话内容」, 角色名取第一个空格前的部分
  - 行内无空格: 自动继承上一句的角色 (说话内容就是整行)
  - 空行: 忽略
  - 独立一行 fight: 战前/战后分界。fight 之前的行是战前剧情(播放完进入战斗),
    之后的行是战后剧情(仅胜利时播放)。支持多个 fight (如 1-4 两段战斗):
    第一个 fight 前 = before, 每两个 fight 之间 = segments[i], 最后一个 fight 后 = after。
  - 预留: 每条对话带 choices 字段(目前恒为 None), 供未来"选择框"分支使用
"""
import os

# 剧情文件夹: Q:/openai/story
STORY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "story")


def parse_story(path):
    """解析剧情txt, 返回 {'before': [...], 'segments': [...], 'after': [...]}

    每条对话: {'speaker': 角色名, 'text': 内容, 'choices': None}
    - before: 第一个 fight 之前的对话 (战前)
    - segments: fight 之间的对话段 (segments[i] 在第 i+1 个 fight 之后)
    - after: 最后一个 fight 之后的对话 (战后)
    单 fight 剧情兼容旧结构: segments 为空, before/after 即战前/战后。
    """
    before, segments = [], []
    speaker = None
    cur = before

    if not os.path.exists(path):
        return {"before": before, "segments": segments, "after": []}

    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            if line == "fight":
                segments.append([])
                cur = segments[-1]
                continue
            if " " in line:
                sp, _, text = line.partition(" ")
                speaker = sp.strip()
            else:
                text = line
            cur.append({"speaker": speaker or "旁白", "text": text, "choices": None})

    # 最后一个 fight 之后的对话 = after (剧情结尾), 其余 fight 之间 = segments
    after = segments.pop() if segments else []
    return {"before": before, "segments": segments, "after": after}


def get_story(filename):
    """按文件名加载剧情 (filename 形如 '1-1.txt')"""
    path = os.path.join(STORY_DIR, filename)
    return parse_story(path)
