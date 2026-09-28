"""チームタスク管理アプリ。

起動: python app.py
ブラウザ: http://127.0.0.1:5000
データ: data/tasks.db
"""

import os
import sqlite3
from datetime import date, datetime

from flask import Flask, g, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data", "tasks.db")
VALID_STATUSES = ("未着手", "進行中", "完了")
UNCHANGED = object()

app = Flask(__name__)
app.json.ensure_ascii = False
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024

TASK_SELECT = """
SELECT
    t.id,
    t.title,
    t.assignee_id,
    a.name AS assignee_name,
    t.due_date,
    t.status,
    t.created_at,
    t.updated_at
FROM tasks t
LEFT JOIN assignees a ON a.id = t.assignee_id
"""


def now_iso():
    return datetime.now().replace(microsecond=0).isoformat()


def today_iso():
    return date.today().isoformat()


def fail(message, status):
    return jsonify({"error": message}), status


def get_db():
    if "db" not in g:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        g.db = sqlite3.connect(DB_PATH, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS assignees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                assignee_id INTEGER,
                due_date TEXT,
                status TEXT NOT NULL CHECK (status IN ('未着手', '進行中', '完了')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (assignee_id) REFERENCES assignees (id)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
            CREATE INDEX IF NOT EXISTS idx_tasks_assignee ON tasks (assignee_id);
            """
        )
        conn.commit()
    finally:
        conn.close()


def json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None, ("JSONオブジェクトで送信してください", 400)
    return data, None


def parse_title(value):
    if not isinstance(value, str) or not value.strip():
        return None, "タイトルを入力してください"
    return value.strip(), None


def parse_status(value):
    if not isinstance(value, str) or value not in VALID_STATUSES:
        return None, "ステータスは「未着手」「進行中」「完了」のいずれかにしてください"
    return value, None


def parse_due_date(value):
    if value is None or value == "":
        return None, None
    if not isinstance(value, str):
        return None, "期限は YYYY-MM-DD 形式で指定してください"
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None, "期限は YYYY-MM-DD 形式で指定してください"
    return value, None


def parse_assignee_name(value):
    if not isinstance(value, str) or not value.strip():
        return None, "担当者名を入力してください"
    name = value.strip()
    if len(name) > 50:
        return None, "担当者名は50文字以内にしてください"
    return name, None


def assignee_dict(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
    }


def is_overdue(due_date, status, today):
    # 未完了かつ期限が今日より前。期限当日は超過にしない。
    return bool(due_date) and status != "完了" and due_date < today


def task_dict(row, today):
    return {
        "id": row["id"],
        "title": row["title"],
        "assignee_id": row["assignee_id"],
        "assignee_name": row["assignee_name"],
        "due_date": row["due_date"],
        "status": row["status"],
        "overdue": is_overdue(row["due_date"], row["status"], today),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def fetch_task(db, task_id, today):
    row = db.execute(TASK_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
    if row is None:
        return None
    return task_dict(row, today)


def find_or_create_assignee(db, name):
    row = db.execute("SELECT id FROM assignees WHERE name = ?", (name,)).fetchone()
    if row is not None:
        return row["id"]
    try:
        cur = db.execute(
            "INSERT INTO assignees (name, created_at) VALUES (?, ?)",
            (name, now_iso()),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        row = db.execute("SELECT id FROM assignees WHERE name = ?", (name,)).fetchone()
        if row is None:
            raise
        return row["id"]


def resolve_assignee(db, data, partial):
    """担当者の解決。

    partial のとき、キーが無ければ UNCHANGED。
    assignee_name が空文字なら担当なし。新しい名前は担当者として登録する。
    """
    has_name = "assignee_name" in data
    has_id = "assignee_id" in data
    if not has_name and not has_id:
        if partial:
            return UNCHANGED, None
        return None, None

    if has_name and data["assignee_name"] is not None:
        raw_name = data["assignee_name"]
        if not isinstance(raw_name, str):
            return None, "担当者名が不正です"
        name = raw_name.strip()
        if not name:
            return None, None
        if len(name) > 50:
            return None, "担当者名は50文字以内にしてください"
        return find_or_create_assignee(db, name), None

    if has_id and data["assignee_id"] not in (None, ""):
        assignee_id = data["assignee_id"]
        if isinstance(assignee_id, bool) or not isinstance(assignee_id, int):
            return None, "担当者の指定が不正です"
        row = db.execute(
            "SELECT id FROM assignees WHERE id = ?", (assignee_id,)
        ).fetchone()
        if row is None:
            return None, "担当者が見つかりません"
        return assignee_id, None

    return None, None


def sort_tasks(tasks):
    tasks.sort(
        key=lambda task: (
            task["status"] == "完了",
            not task["overdue"],
            task["due_date"] is None,
            task["due_date"] or "9999-99-99",
            -task["id"],
        )
    )
    return tasks


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/assignees")
def list_assignees():
    db = get_db()
    rows = db.execute("SELECT id, name, created_at FROM assignees ORDER BY name, id").fetchall()
    return jsonify({"assignees": [assignee_dict(row) for row in rows]})


@app.post("/api/assignees")
def create_assignee():
    data, err = json_body()
    if err:
        return fail(*err)
    name, message = parse_assignee_name(data.get("name"))
    if message:
        return fail(message, 400)

    db = get_db()
    existing = db.execute(
        "SELECT id, name, created_at FROM assignees WHERE name = ?", (name,)
    ).fetchone()
    if existing is not None:
        return (
            jsonify(
                {
                    "error": "同じ名前の担当者がすでにいます",
                    "assignee": assignee_dict(existing),
                }
            ),
            409,
        )

    try:
        cur = db.execute(
            "INSERT INTO assignees (name, created_at) VALUES (?, ?)",
            (name, now_iso()),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        existing = db.execute(
            "SELECT id, name, created_at FROM assignees WHERE name = ?",
            (name,),
        ).fetchone()
        if existing is None:
            raise
        return (
            jsonify(
                {
                    "error": "同じ名前の担当者がすでにいます",
                    "assignee": assignee_dict(existing),
                }
            ),
            409,
        )
    row = db.execute(
        "SELECT id, name, created_at FROM assignees WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return jsonify({"assignee": assignee_dict(row)}), 201


@app.get("/api/tasks")
def list_tasks():
    status = request.args.get("status", "").strip()
    if status and status not in VALID_STATUSES:
        return fail("ステータスは「未着手」「進行中」「完了」のいずれかにしてください", 400)

    raw_assignee = request.args.get("assignee_id", "").strip()
    assignee_id = None
    if raw_assignee:
        if not raw_assignee.isdigit():
            return fail("担当者の指定が不正です", 400)
        assignee_id = int(raw_assignee)

    query = TASK_SELECT + " WHERE 1 = 1"
    params = []
    if status:
        query += " AND t.status = ?"
        params.append(status)
    if assignee_id is not None:
        query += " AND t.assignee_id = ?"
        params.append(assignee_id)

    today = today_iso()
    db = get_db()
    rows = db.execute(query, params).fetchall()
    tasks = sort_tasks([task_dict(row, today) for row in rows])
    return jsonify({"tasks": tasks, "count": len(tasks), "today": today})


@app.post("/api/tasks")
def create_task():
    data, err = json_body()
    if err:
        return fail(*err)
    if "title" not in data:
        return fail("タイトルを入力してください", 400)
    title, message = parse_title(data.get("title"))
    if message:
        return fail(message, 400)

    if "status" in data:
        status, message = parse_status(data.get("status"))
        if message:
            return fail(message, 400)
    else:
        status = "未着手"

    if "due_date" in data:
        due_date, message = parse_due_date(data.get("due_date"))
        if message:
            return fail(message, 400)
    else:
        due_date = None

    db = get_db()
    try:
        assignee_id, message = resolve_assignee(db, data, partial=False)
        if message:
            db.rollback()
            return fail(message, 400)
        timestamp = now_iso()
        cur = db.execute(
            """
            INSERT INTO tasks (
                title, assignee_id, due_date, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (title, assignee_id, due_date, status, timestamp, timestamp),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return fail("保存できませんでした。入力内容を確認してください", 400)

    task = fetch_task(db, cur.lastrowid, today_iso())
    return jsonify({"task": task}), 201


@app.put("/api/tasks/<int:task_id>")
def update_task(task_id):
    data, err = json_body()
    if err:
        return fail(*err)

    recognized = {"title", "status", "due_date", "assignee_name", "assignee_id"}
    if not recognized.intersection(data):
        return fail("更新する項目がありません", 400)

    db = get_db()
    existing = db.execute("SELECT id FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if existing is None:
        return fail("タスクが見つかりません", 404)

    updates = {}
    if "title" in data:
        title, message = parse_title(data.get("title"))
        if message:
            return fail(message, 400)
        updates["title"] = title
    if "status" in data:
        status, message = parse_status(data.get("status"))
        if message:
            return fail(message, 400)
        updates["status"] = status
    if "due_date" in data:
        due_date, message = parse_due_date(data.get("due_date"))
        if message:
            return fail(message, 400)
        updates["due_date"] = due_date

    try:
        assignee_id, message = resolve_assignee(db, data, partial=True)
        if message:
            db.rollback()
            return fail(message, 400)
    except sqlite3.IntegrityError:
        db.rollback()
        return fail("保存できませんでした。入力内容を確認してください", 400)

    if assignee_id is not UNCHANGED:
        updates["assignee_id"] = assignee_id

    if not updates:
        return fail("更新する項目がありません", 400)

    assignments = []
    params = []
    for column in ("title", "status", "due_date", "assignee_id"):
        if column in updates:
            assignments.append(f"{column} = ?")
            params.append(updates[column])
    assignments.append("updated_at = ?")
    params.append(now_iso())
    params.append(task_id)

    try:
        db.execute(
            f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?",
            params,
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return fail("保存できませんでした。入力内容を確認してください", 400)

    task = fetch_task(db, task_id, today_iso())
    return jsonify({"task": task})


@app.delete("/api/tasks/<int:task_id>")
def delete_task(task_id):
    db = get_db()
    cur = db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    db.commit()
    if cur.rowcount == 0:
        return fail("タスクが見つかりません", 404)
    return jsonify({"ok": True})


@app.errorhandler(404)
def not_found(_exc):
    if request.path.startswith("/api/"):
        return fail("見つかりません", 404)
    return "ページが見つかりません", 404


@app.errorhandler(413)
def too_large(_exc):
    return fail("送信データが大きすぎます", 413)


init_db()


if __name__ == "__main__":
    print("タスク管理アプリを起動しました: http://127.0.0.1:5000", flush=True)
    print("止めるときは Ctrl+C を押してください", flush=True)
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
