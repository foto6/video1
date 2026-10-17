from __future__ import annotations

import hashlib
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(wire(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


class Wait(RuntimeError):
    def __init__(self, state, message):
        super().__init__(message)
        self.state = state


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = self.root / 'production.sqlite3'
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS runs (
              id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, topic TEXT NOT NULL,
              profile TEXT NOT NULL, state TEXT NOT NULL, stage TEXT NOT NULL,
              error TEXT, result TEXT, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
              sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
              stage TEXT NOT NULL, message TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (
              key TEXT PRIMARY KEY, run_id TEXT NOT NULL, provider TEXT NOT NULL,
              request TEXT NOT NULL, state TEXT NOT NULL, external_id TEXT,
              response TEXT, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS artifacts (
              run_id TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL,
              sha256 TEXT NOT NULL, dependencies TEXT NOT NULL,
              PRIMARY KEY(run_id,name));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def folder(self, run_id):
        if not re.fullmatch(r'vid-[a-f0-9]{32}', run_id):
            raise ValueError('Invalid video ID')
        path = self.root / 'runs' / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create(self, topic, profile, key, initial_state='queued'):
        with self.connect() as db:
            previous = db.execute('SELECT * FROM runs WHERE request_key=?', (key,)).fetchone()
            if previous:
                if previous['topic'] != topic or previous['profile'] != wire(profile):
                    raise ValueError('Request key already belongs to a different brief')
                return previous['id']
            run_id = 'vid-' + uuid.uuid4().hex
            now = time.time()
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (run_id, key, topic, wire(profile), initial_state, 'BRIEF', None, None, now, now))
        self.folder(run_id)
        self.event(run_id, 'BRIEF', 'Задание сохранено')
        return run_id

    def get(self, run_id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if not row:
                raise KeyError('Video not found')
            value = dict(row)
            value['profile'] = json.loads(value['profile'])
            value['result'] = json.loads(value['result']) if value['result'] else None
            value['events'] = [dict(x) for x in db.execute('SELECT stage,message,created FROM events WHERE run_id=? ORDER BY sequence', (run_id,))]
            return value

    def list(self):
        with self.connect() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM runs ORDER BY created DESC LIMIT 100')]
        return [self.get(x) for x in ids]

    def event(self, run_id, stage, message):
        with self.connect() as db:
            db.execute('INSERT INTO events(run_id,stage,message,created) VALUES (?,?,?,?)', (run_id, stage, message, time.time()))

    def update(self, run_id, state, stage, error=None, result=None):
        with self.connect() as db:
            db.execute('UPDATE runs SET state=?,stage=?,error=?,result=?,updated=? WHERE id=?',
                       (state, stage, error, wire(result) if result else None, time.time(), run_id))

    def op(self, key):
        with self.connect() as db:
            row = db.execute('SELECT * FROM operations WHERE key=?', (key,)).fetchone()
        if not row:
            return None
        result = dict(row)
        for field in ('request', 'response'):
            result[field] = json.loads(result[field]) if result[field] else None
        return result

    def prepare(self, key, run_id, provider, request):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO operations VALUES (?,?,?,?,?,?,?,?)',
                       (key, run_id, provider, wire(request), 'prepared', None, None, time.time()))
        op = self.op(key)
        if op['request'] != request or op['provider'] != provider:
            raise ValueError('Immutable operation request changed')
        return op

    def operation(self, key, state, external_id=None, response=None):
        with self.connect() as db:
            db.execute('UPDATE operations SET state=?,external_id=COALESCE(?,external_id),response=COALESCE(?,response),updated=? WHERE key=?',
                       (state, external_id, wire(response) if response is not None else None, time.time(), key))

    def artifact(self, run_id, name, value, dependencies=()):
        encoded = wire(value).encode('utf-8')
        digest = hashlib.sha256(encoded).hexdigest()
        path = self.folder(run_id) / 'artifacts' / (digest + '.json')
        path.parent.mkdir(exist_ok=True)
        if path.exists():
            if file_hash(path) != digest:
                raise ValueError('Artifact bytes changed')
        else:
            with path.open('xb') as f:
                f.write(encoded)
        with self.connect() as db:
            previous = db.execute('SELECT sha256 FROM artifacts WHERE run_id=? AND name=?', (run_id, name)).fetchone()
            if previous and previous[0] != digest:
                raise ValueError('Use a new artifact version instead of overwriting')
            db.execute('INSERT OR IGNORE INTO artifacts VALUES (?,?,?,?,?)', (run_id, name, str(path), digest, wire(list(dependencies))))
        return value

    def read(self, run_id, name):
        with self.connect() as db:
            row = db.execute('SELECT path,sha256 FROM artifacts WHERE run_id=? AND name=?', (run_id, name)).fetchone()
        if not row:
            return None
        if file_hash(row[0]) != row[1]:
            raise ValueError('Saved artifact was modified')
        return json.loads(Path(row[0]).read_text(encoding='utf-8'))
