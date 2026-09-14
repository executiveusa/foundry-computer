import json, sqlite3
from pathlib import Path
from threading import RLock
class Store:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True); self.path=path; self.lock=RLock(); self._init()
    def _db(self): c=sqlite3.connect(self.path, check_same_thread=False); c.row_factory=sqlite3.Row; return c
    def _init(self):
        with self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS objects(kind TEXT,id TEXT PRIMARY KEY,data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,at TEXT DEFAULT CURRENT_TIMESTAMP,kind TEXT,object_id TEXT,payload TEXT);
            """)
    def put(self, kind, id, data):
        with self.lock, self._db() as db:
            db.execute("INSERT OR REPLACE INTO objects VALUES(?,?,?)",(kind,id,json.dumps(data))); db.commit()
    def get(self, kind, id):
        with self._db() as db:
            row=db.execute("SELECT data FROM objects WHERE kind=? AND id=?",(kind,id)).fetchone()
            return json.loads(row[0]) if row else None
    def list(self, kind):
        with self._db() as db: return [json.loads(r[0]) for r in db.execute("SELECT data FROM objects WHERE kind=?",(kind,))]
    def delete(self, kind, id):
        with self.lock, self._db() as db: db.execute("DELETE FROM objects WHERE kind=? AND id=?",(kind,id)); db.commit()
    def event(self, kind, object_id, payload):
        with self.lock, self._db() as db: db.execute("INSERT INTO events(kind,object_id,payload) VALUES(?,?,?)",(kind,object_id,json.dumps(payload))); db.commit()
