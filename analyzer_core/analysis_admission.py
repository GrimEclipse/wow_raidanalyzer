"""Persistent rolling-hour accounting; admitted batch jobs may finish."""
import sqlite3
import time
from pathlib import Path

from analyzer_core.wcl_service import AdmissionError


class AnalysisUsage:
    def __init__(self, path, *, limit=5, clock=time.time):
        self.path, self.limit, self.clock = Path(path), int(limit), clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS admitted_jobs (
                    id TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    created_at REAL NOT NULL, status TEXT NOT NULL DEFAULT 'accepted');
                CREATE TABLE IF NOT EXISTS analyzed_fights (
                    job_id TEXT NOT NULL, user_id INTEGER NOT NULL,
                    report_code TEXT NOT NULL, fight_id INTEGER NOT NULL, charged_at REAL NOT NULL,
                    PRIMARY KEY(job_id, report_code, fight_id));
                CREATE INDEX IF NOT EXISTS fight_usage_user_time ON analyzed_fights(user_id, charged_at);
                CREATE INDEX IF NOT EXISTS job_usage_user_time ON admitted_jobs(user_id, created_at);
            ''')

    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def _snapshot(self, db, user_id, admin=False):
        now = self.clock()
        times = [r[0] for r in db.execute('''
            SELECT charged_at FROM analyzed_fights WHERE user_id=? AND charged_at>?
            UNION ALL
            SELECT created_at FROM admitted_jobs j WHERE user_id=? AND created_at>?
              AND NOT EXISTS (SELECT 1 FROM analyzed_fights f WHERE f.job_id=j.id)
        ''', (user_id, now-3600, user_id, now-3600))]
        return {'limit':None if admin else self.limit, 'used':len(times),
                'remaining':None if admin else max(0,self.limit-len(times)), 'windowSeconds':3600,
                'nextResetAt':min(times)+3600 if times else None,
                'available':admin or len(times)<self.limit, 'exempt':bool(admin)}

    def snapshot(self, user_id, *, admin=False):
        with self.connect() as db:
            return self._snapshot(db, user_id, admin)

    def admit(self, user, job_id):
        if user.get('isAdmin'):
            return
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            state = self._snapshot(db, user['id'])
            if not state['available']:
                raise AdmissionError(f'最近一小时已达到 {self.limit} 场战斗，已有任务会继续完成，请稍后再发起分析。',
                                     state['nextResetAt']-self.clock())
            db.execute('INSERT INTO admitted_jobs(id,user_id,created_at) VALUES(?,?,?)',
                       (job_id,user['id'],self.clock()))

    def record(self, job_id, report_code, fights):
        with self.connect() as db:
            job = db.execute('SELECT user_id FROM admitted_jobs WHERE id=?', (job_id,)).fetchone()
            if job is None:
                return
            db.executemany('INSERT OR IGNORE INTO analyzed_fights VALUES(?,?,?,?,?)',
                [(job_id,job['user_id'],str(report_code),int(f['id']),self.clock()) for f in fights])

    def finish(self, job_id, status):
        with self.connect() as db:
            db.execute('UPDATE admitted_jobs SET status=? WHERE id=?', (status,job_id))
