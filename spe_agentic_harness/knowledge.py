"""Append-only extraction snapshots with source-grounded assertions (SQLite)."""
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class KnowledgeStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS snapshots(
              id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS assertions(
              id INTEGER PRIMARY KEY, snapshot TEXT NOT NULL REFERENCES snapshots(id),
              record_index INTEGER NOT NULL, field TEXT NOT NULL, value_json TEXT NOT NULL,
              evidence_json TEXT NOT NULL, state TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS assertion_snapshot ON assertions(snapshot);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, project, result, provenance):
        if not project.strip() or not isinstance(result.get('records'), list):
            raise ValueError('Project and extraction records are required')
        sources = result.get('sources', [])
        if not sources or any(not s.get('sha256') for s in sources):
            raise ValueError('Source file hashes are required')
        payload = encoded({'result': result, 'provenance': provenance})
        sid = hashlib.sha256((project + '\n' + payload).encode()).hexdigest()
        with self.connect() as db:
            inserted = db.execute('INSERT OR IGNORE INTO snapshots(id,project,payload) VALUES(?,?,?)',
                                  (sid, project, payload)).rowcount
            if inserted:
                for index, record in enumerate(result['records']):
                    if not isinstance(record, dict):
                        continue
                    for field, claim in record.items():
                        if field == 'id' or not isinstance(claim, dict) or 'value' not in claim:
                            continue
                        # Storage never promotes an LLM assertion into verified fact.
                        db.execute('INSERT INTO assertions(snapshot,record_index,field,value_json,evidence_json,state) VALUES(?,?,?,?,?,?)',
                                   (sid, index, field, encoded(claim), encoded(claim.get('evidence', [])), 'unreviewed_extraction'))
        return {'snapshot_id': sid, 'inserted': bool(inserted)}

    def get(self, project, snapshot_id):
        with self.connect() as db:
            row = db.execute('SELECT payload FROM snapshots WHERE id=? AND project=?', (snapshot_id, project)).fetchone()
        if row is None:
            raise ValueError('Snapshot not found in this project')
        return json.loads(row[0])

    def query(self, project, text, limit=20):
        if not 1 <= limit <= 100:
            raise ValueError('limit must be 1..100')
        with self.connect() as db:
            rows = db.execute('''SELECT a.snapshot,a.record_index,a.field,a.value_json,a.state
                FROM assertions a JOIN snapshots s ON a.snapshot=s.id
                WHERE s.project=? AND instr(lower(a.value_json), lower(?))>0
                ORDER BY a.id DESC LIMIT ?''', (project, text, limit)).fetchall()
        return [{'snapshot_id': s, 'record_index': i, 'field': f, 'assertion': json.loads(v),
                 'state': state} for s, i, f, v, state in rows]
