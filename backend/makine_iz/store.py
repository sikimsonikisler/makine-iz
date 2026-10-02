"""Makine başına analiz durumunun (süreklilik sayaçlarının) saklanması."""
from __future__ import annotations

import sqlite3

from .analysis import StreamState
from .db import dumps, loads
from .timeutil import now_epoch, to_iso


def load_state(conn: sqlite3.Connection, machine_id: str) -> StreamState:
    row = conn.execute("SELECT state_json FROM machine_state WHERE machine_id = ?", (machine_id,)).fetchone()
    return StreamState.from_dict(loads(row["state_json"], {})) if row else StreamState()


def save_state(conn: sqlite3.Connection, machine_id: str, state: StreamState) -> None:
    conn.execute(
        """INSERT INTO machine_state (machine_id, state_json, updated_at) VALUES (?, ?, ?)
           ON CONFLICT(machine_id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at""",
        (machine_id, dumps(state.to_dict()), to_iso(now_epoch())),
    )
