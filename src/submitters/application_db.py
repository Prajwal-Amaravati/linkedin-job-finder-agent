import sqlite3
import os
from typing import Optional

class ApplicationDB:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or "output/applications.db"
        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self._ensure_table()

    def _ensure_table(self):
        with self.conn:
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS applications (
                    job_id TEXT PRIMARY KEY,
                    title TEXT,
                    company TEXT,
                    url TEXT,
                    location TEXT,
                    score REAL,
                    priority INTEGER,
                    status TEXT,
                    timestamp TEXT
                )
            ''')

    def has_job(self, job_id: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM applications WHERE job_id = ?", (job_id,))
        return cur.fetchone() is not None

    def log_job(self, job_id: str, title: str, company: str, url: str, location: str, score: float, priority: int, status: str, timestamp: str):
        with self.conn:
            self.conn.execute('''
                INSERT OR REPLACE INTO applications (job_id, title, company, url, location, score, priority, status, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (job_id, title, company, url, location, score, priority, status, timestamp))

    def close(self):
        self.conn.close()
