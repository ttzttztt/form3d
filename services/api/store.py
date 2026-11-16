"""Single-user local store. Short transactions protect task state transitions."""
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, directory: Path):
        self.root = directory.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "workbench.sqlite3"
        self.lock = threading.RLock()
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS images (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS requests (key TEXT PRIMARY KEY, hash TEXT NOT NULL, job_id TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.database), timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def put_image(self, item):
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO images VALUES (?, ?)", (item["id"], json.dumps(item, ensure_ascii=False)))

    def image(self, item_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM images WHERE id=?", (item_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def update_image(self, image_id, mutate):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM images WHERE id=?", (image_id,)).fetchone()
            if not row:
                return None
            item = json.loads(row[0])
            mutate(item)
            db.execute("UPDATE images SET data=? WHERE id=?", (json.dumps(item, ensure_ascii=False), image_id))
            return item

    def job(self, job_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def images(self):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM images ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def jobs(self):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM jobs ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def create_job(self, item, key, digest):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if key:
                found = db.execute("SELECT hash, job_id FROM requests WHERE key=?", (key,)).fetchone()
                if found:
                    if found[0] != digest:
                        raise ValueError("同一个请求标识不能用于不同参数")
                    return self.job(found[1]), False
            db.execute("INSERT INTO jobs VALUES (?, ?)", (item["id"], json.dumps(item, ensure_ascii=False)))
            if key:
                db.execute("INSERT INTO requests VALUES (?, ?, ?)", (key, digest, item["id"]))
        return item, True

    def update(self, job_id, mutate, allow_cancelled=False):
        with self.lock, self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                return None
            item = json.loads(row[0])
            if item["status"] == "cancelled" and not allow_cancelled:
                return item
            mutate(item)
            item["updated_at"] = now()
            db.execute("UPDATE jobs SET data=? WHERE id=?", (json.dumps(item, ensure_ascii=False), job_id))
            return item

    def event(self, job_id, stage, message, **changes):
        def apply(item):
            item.update(changes)
            item["stage"] = stage
            item["events"].append({"at": now(), "stage": stage, "message": message})
        return self.update(job_id, apply)
