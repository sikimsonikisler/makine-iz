"""SQLite veritabanı: şema ve bağlantı yönetimi.

Kayıt türleri (tablolar):
- machines          → Machine: makine bilgileri, modlar, beklenen ölçüm aralığı
- telemetry         → Telemetry: zaman damgalı ölçümler + analiz sonucu
- baselines         → BaselineProfile: makine + çalışma modu için referans (sürümlü)
- alerts            → Alert: sapma veya veri kalitesi uyarısı
- review_notes      → ReviewNote: kullanıcı değerlendirmesi / bakım notu
- simulation_runs   → SimulationRun: senaryo, tohum ve tekrar üretilebilirlik bilgisi
- machine_state     → analiz motorunun süreklilik sayaçları (yeniden başlatmada korunur)
- imports           → CSV aktarım özetleri
- meta              → küçük anahtar/değer bilgileri
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS machines (
    id                   TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    machine_type         TEXT NOT NULL,
    location             TEXT NOT NULL DEFAULT '',
    description          TEXT NOT NULL DEFAULT '',
    data_source          TEXT NOT NULL,
    sim_profile          TEXT,
    expected_interval_s  REAL NOT NULL,
    transition_s         REAL NOT NULL,
    modes_json           TEXT NOT NULL,
    ranges_json          TEXT NOT NULL,
    floors_json          TEXT NOT NULL,
    is_demo              INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS telemetry (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id       TEXT NOT NULL REFERENCES machines(id),
    ts               TEXT NOT NULL,
    operating_mode   TEXT,
    vibration_rms_g  REAL,
    temperature_c    REAL,
    power_kw         REAL,
    rpm              REAL,
    source           TEXT NOT NULL,
    quality_flags    TEXT NOT NULL DEFAULT '[]',
    raw_json         TEXT,
    is_demo          INTEGER NOT NULL DEFAULT 0,
    sim_run_id       INTEGER,
    import_id        TEXT,
    segment          TEXT,
    analysis_status  TEXT,
    z_json           TEXT,
    z_max            REAL,
    baseline_id      INTEGER,
    UNIQUE (machine_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_telemetry_machine_ts ON telemetry (machine_id, ts);

CREATE TABLE IF NOT EXISTS baselines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id      TEXT NOT NULL REFERENCES machines(id),
    mode            TEXT NOT NULL,
    version         INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    range_start     TEXT NOT NULL,
    range_end       TEXT NOT NULL,
    sample_count    INTEGER NOT NULL,
    excluded_count  INTEGER NOT NULL DEFAULT 0,
    stats_json      TEXT NOT NULL,
    is_active       INTEGER NOT NULL DEFAULT 1,
    is_demo         INTEGER NOT NULL DEFAULT 0,
    note            TEXT NOT NULL DEFAULT '',
    UNIQUE (machine_id, mode, version)
);

CREATE TABLE IF NOT EXISTS alerts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id          TEXT NOT NULL REFERENCES machines(id),
    mode                TEXT,
    kind                TEXT NOT NULL,
    dq_type             TEXT,
    level               TEXT NOT NULL,
    measurement_status  TEXT NOT NULL,
    review_status       TEXT NOT NULL DEFAULT 'new',
    assessment          TEXT,
    started_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    ended_at            TEXT,
    baseline_id         INTEGER,
    baseline_version    INTEGER,
    peak_z              REAL,
    last_z              REAL,
    details_json        TEXT NOT NULL DEFAULT '{}',
    explanation         TEXT NOT NULL DEFAULT '',
    unevaluable_reason  TEXT,
    is_open             INTEGER NOT NULL DEFAULT 1,
    is_demo             INTEGER NOT NULL DEFAULT 0,
    source              TEXT,
    created_at          TEXT NOT NULL,
    reviewed_at         TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_machine_open ON alerts (machine_id, is_open, kind);

CREATE TABLE IF NOT EXISTS review_notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id      TEXT NOT NULL REFERENCES machines(id),
    alert_id        INTEGER REFERENCES alerts(id) ON DELETE SET NULL,
    created_at      TEXT NOT NULL,
    author          TEXT NOT NULL DEFAULT '',
    note_type       TEXT NOT NULL DEFAULT 'inspection',
    text            TEXT NOT NULL,
    assessment      TEXT,
    alert_snapshot  TEXT
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    machine_id       TEXT NOT NULL REFERENCES machines(id),
    scenario         TEXT NOT NULL,
    seed             INTEGER NOT NULL,
    status           TEXT NOT NULL,
    speed            REAL NOT NULL DEFAULT 1,
    start_virtual    TEXT NOT NULL,
    virtual_now      TEXT NOT NULL,
    steps_generated  INTEGER NOT NULL DEFAULT 0,
    records_emitted  INTEGER NOT NULL DEFAULT 0,
    params_json      TEXT NOT NULL,
    status_note      TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS machine_state (
    machine_id  TEXT PRIMARY KEY REFERENCES machines(id),
    state_json  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
    id            TEXT PRIMARY KEY,
    filename      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    summary_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key    TEXT PRIMARY KEY,
    value  TEXT NOT NULL
);
"""


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def loads(text: str | None, default: Any = None) -> Any:
    if text is None or text == "":
        return default
    return json.loads(text)


class Database:
    """Her işlem kendi bağlantısını açar; yazma işlemleri tek bir kilitle sıraya girer."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        conn = self._connect()
        try:
            conn.executescript(SCHEMA)
        finally:
            conn.close()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        """Tek bir işlem (transaction). Hata olursa her şey geri alınır — kısmi kayıt kalmaz."""
        with self.lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                yield conn
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            finally:
                conn.close()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
        finally:
            conn.close()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
