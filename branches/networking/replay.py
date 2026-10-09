# -*- coding: utf-8 -*-
"""组合麻将 — 联机回放存储 (移植 mmcr14.online 的回放记录/查询设计, 用 SQLite 落地)

每局对局结束后由 ActiveSession 调用 save_replay() 落库:
- metadata: session_identifier / created_at / players / round_count / final_scores
- 完整事件流(每局的逐阶段事件与结果)存 JSON blob, 供回放页逐步渲染
"""
import json
import os
import sqlite3
import time

_BASE = os.path.dirname(os.path.abspath(__file__))
REPLAY_DB = os.path.join(_BASE, "replays.db")


def _conn():
    conn = sqlite3.connect(REPLAY_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS replays (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_identifier TEXT UNIQUE,
              session_id INTEGER,
              created_at_ms INTEGER,
              ended_at_ms INTEGER,
              round_count INTEGER,
              player_names TEXT,
              player_ids TEXT,
              final_scores TEXT,
              payload TEXT
            )
        """)


def save_replay(replay: dict) -> str:
    """保存一局回放, 返回 session_identifier"""
    init_db()
    ident = replay.get("session_identifier") or f"s{int(time.time()*1000)}"
    rounds = replay.get("rounds") or []
    with _conn() as c:
        c.execute("""INSERT OR REPLACE INTO replays
            (session_identifier, session_id, created_at_ms, ended_at_ms, round_count,
             player_names, player_ids, final_scores, payload)
            VALUES (?,?,?,?,?,?,?,?,?)""", (
            ident,
            int(replay.get("session_id") or 0),
            int(replay.get("created_at_ms") or int(time.time() * 1000)),
            int(replay.get("ended_at_ms") or int(time.time() * 1000)),
            len(rounds),
            json.dumps(replay.get("names") or [], ensure_ascii=False),
            json.dumps(replay.get("player_ids") or [], ensure_ascii=False),
            json.dumps(replay.get("final_scores") or [], ensure_ascii=False),
            json.dumps(replay, ensure_ascii=False),
        ))
    return ident


def list_replays(limit=50):
    """回放列表(不含事件流)"""
    init_db()
    with _conn() as c:
        rows = c.execute("""SELECT session_identifier, session_id, created_at_ms, ended_at_ms,
                                   round_count, player_names, player_ids, final_scores
                            FROM replays ORDER BY created_at_ms DESC LIMIT ?""", (int(limit),)).fetchall()
    out = []
    for r in rows:
        out.append({
            "session_identifier": r["session_identifier"],
            "session_id": r["session_id"],
            "created_at_ms": r["created_at_ms"],
            "ended_at_ms": r["ended_at_ms"],
            "round_count": r["round_count"],
            "names": json.loads(r["player_names"] or "[]"),
            "player_ids": json.loads(r["player_ids"] or "[]"),
            "final_scores": json.loads(r["final_scores"] or "[]"),
        })
    return out


def load_replay(session_identifier):
    """加载完整回放(含事件流)"""
    init_db()
    with _conn() as c:
        row = c.execute("SELECT payload FROM replays WHERE session_identifier = ?",
                        (session_identifier,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["payload"])
    except Exception:
        return None
