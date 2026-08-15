# -*- coding: utf-8 -*-
"""组合麻将 — 论坛数据库 (SQLite)"""
import os, sqlite3
from typing import Optional, List, Dict

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forum.db")

def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = _conn()
    cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS sections(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS posts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT,
        FOREIGN KEY(section_id) REFERENCES sections(id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS replies(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER NOT NULL,
        author TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(post_id) REFERENCES posts(id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS likes(
        post_id INTEGER NOT NULL,
        user TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        PRIMARY KEY(post_id, user)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS favorites(
        post_id INTEGER NOT NULL,
        user TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        PRIMARY KEY(post_id, user)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS user_profile(
        user TEXT PRIMARY KEY,
        points INTEGER DEFAULT 0,
        level INTEGER DEFAULT 1,
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    )""")
    cur.execute("INSERT OR IGNORE INTO sections(name, description) VALUES(?, ?)",
                ("组合麻将", "组合麻将的规则、玩法、bug反馈与闲聊"))
    conn.commit()
    conn.close()

def get_sections():
    conn = _conn()
    rows = conn.execute("SELECT id, name, description, created_at FROM sections ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def create_post(section_id, author, title, content):
    conn = _conn()
    cur = conn.execute("INSERT INTO posts(section_id, author, title, content) VALUES(?,?,?,?)",
                        (section_id, author, title, content))
    conn.commit()
    pid = cur.lastrowid
    conn.close()
    return pid

def list_posts(section_id=None, page=1, per_page=20):
    conn = _conn()
    where = ""; params = []
    if section_id is not None:
        where = "WHERE p.section_id = ?"; params.append(section_id)
    offset = (page - 1) * per_page
    rows = conn.execute("""
        SELECT p.id, p.section_id, p.author, p.title, p.content,
               p.created_at, p.updated_at,
               (SELECT COUNT(*) FROM replies r WHERE r.post_id=p.id) AS reply_count,
               (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) AS like_count
        FROM posts p %s
        ORDER BY p.created_at DESC
        LIMIT ? OFFSET ?
    """ % where, params + [per_page, offset]).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM posts p %s" % where, params).fetchone()[0]
    conn.close()
    return {"posts": [dict(r) for r in rows], "total": total}

def get_post(post_id):
    conn = _conn()
    row = conn.execute("""
        SELECT p.*, (SELECT COUNT(*) FROM likes l WHERE l.post_id=p.id) AS like_count
        FROM posts p WHERE p.id=?
    """, (post_id,)).fetchone()
    if not row:
        conn.close(); return None
    replies = conn.execute("SELECT * FROM replies WHERE post_id=? ORDER BY created_at", (post_id,)).fetchall()
    conn.close()
    return {"post": dict(row), "replies": [dict(r) for r in replies]}

def add_reply(post_id, author, content):
    conn = _conn()
    cur = conn.execute("INSERT INTO replies(post_id, author, content) VALUES(?,?,?)",
                       (post_id, author, content))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid

def toggle_like(post_id, user):
    conn = _conn()
    row = conn.execute("SELECT 1 FROM likes WHERE post_id=? AND user=?", (post_id, user)).fetchone()
    if row:
        conn.execute("DELETE FROM likes WHERE post_id=? AND user=?", (post_id, user))
        conn.commit(); conn.close(); return "unliked"
    conn.execute("INSERT INTO likes(post_id, user) VALUES(?,?)", (post_id, user))
    conn.commit(); conn.close(); return "liked"

def toggle_favorite(post_id, user):
    conn = _conn()
    row = conn.execute("SELECT 1 FROM favorites WHERE post_id=? AND user=?", (post_id, user)).fetchone()
    if row:
        conn.execute("DELETE FROM favorites WHERE post_id=? AND user=?", (post_id, user))
        conn.commit(); conn.close(); return "unfavorited"
    conn.execute("INSERT INTO favorites(post_id, user) VALUES(?,?)", (post_id, user))
    conn.commit(); conn.close(); return "favorited"

def get_like_state(post_id, user):
    conn = _conn()
    row = conn.execute("SELECT 1 FROM likes WHERE post_id=? AND user=?", (post_id, user)).fetchone()
    conn.close()
    return row is not None

def get_favorite_state(post_id, user):
    conn = _conn()
    row = conn.execute("SELECT 1 FROM favorites WHERE post_id=? AND user=?", (post_id, user)).fetchone()
    conn.close()
    return row is not None

def update_post(post_id, title, content):
    conn = _conn()
    conn.execute("UPDATE posts SET title=?, content=?, updated_at=datetime('now','localtime') WHERE id=?", (title, content, post_id))
    conn.commit(); conn.close()

def delete_post(post_id):
    conn = _conn()
    conn.execute("DELETE FROM replies WHERE post_id=?", (post_id,))
    conn.execute("DELETE FROM likes WHERE post_id=?", (post_id,))
    conn.execute("DELETE FROM favorites WHERE post_id=?", (post_id,))
    conn.execute("DELETE FROM posts WHERE id=?", (post_id,))
    conn.commit(); conn.close()

def get_user_favorites(user):
    conn = _conn()
    rows = conn.execute("""
        SELECT p.id, p.title, p.author, p.created_at, f.created_at AS fav_at
        FROM favorites f JOIN posts p ON f.post_id=p.id
        WHERE f.user=? ORDER BY f.created_at DESC
    """, (user,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def ensure_profile(user):
    conn = _conn()
    conn.execute("INSERT OR IGNORE INTO user_profile(user, points, level) VALUES(?,0,1)", (user,))
    conn.commit(); conn.close()

def get_profile(user):
    ensure_profile(user)
    conn = _conn()
    row = conn.execute("SELECT * FROM user_profile WHERE user=?", (user,)).fetchone()
    conn.close()
    return dict(row) if row else {"user": user, "points": 0, "level": 1}

def add_points(user, pts):
    ensure_profile(user)
    conn = _conn()
    conn.execute("UPDATE user_profile SET points=points+?, updated_at=datetime('now','localtime') WHERE user=?", (pts, user))
    conn.commit(); conn.close()
