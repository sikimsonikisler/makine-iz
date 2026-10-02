"""Demo verisi: üç demo makinesi, etiketli normal geçmiş ve bu geçmişten referanslar.

Demo sıfırlaması YALNIZCA demo kayıtlarını etkiler:
  silinir  → demo makinelerinin simülasyon ölçümleri, demo referansları, bu verilerden doğan
             uyarılar ve demo makinelerinin simülasyon çalıştırmaları
  korunur  → kullanıcının eklediği makineler, CSV ile aktarılan ölçümler, kullanıcı notları
             (silinen bir uyarıya bağlı not kalır; uyarı bağlantısı kaldırılır, özet metni saklanır)
"""
from __future__ import annotations

import sqlite3

from . import baselines
from .db import set_meta
from .machines import create_machine, default_modes, get_machine, update_machine
from .pipeline import IngestOptions, ingest
from .simulator import MachineSimulator, generate_records
from .timeutil import now_epoch, to_iso

DEMO_MACHINES = [
    {
        "id": "demo-motor",
        "name": "Demo Motor M-1",
        "machine_type": "Motor",
        "location": "Simülasyon · Hat 1",
        "description": "Asenkron motoru temsil eden demo makinesi. Ölçümler simülatörden gelir.",
        "sim_profile": "motor",
    },
    {
        "id": "demo-pompa",
        "name": "Demo Pompa P-1",
        "machine_type": "Pompa",
        "location": "Simülasyon · Su hattı",
        "description": "Santrifüj pompayı temsil eden demo makinesi. Ölçümler simülatörden gelir.",
        "sim_profile": "pump",
    },
    {
        "id": "demo-fan",
        "name": "Demo Fan F-1",
        "machine_type": "Fan",
        "location": "Simülasyon · Havalandırma",
        "description": "Havalandırma fanını temsil eden demo makinesi. Ölçümler simülatörden gelir.",
        "sim_profile": "fan",
    },
]
DEMO_IDS = [m["id"] for m in DEMO_MACHINES]

# Etiketli normal geçmiş: (mod, dakika). Referanslar YALNIZCA bu bölümden oluşturulur.
HISTORY_SCHEDULE = [("stopped", 5), ("idle", 40), ("loaded", 45), ("idle", 10)]
HISTORY_SEEDS = {"demo-motor": 101, "demo-pompa": 102, "demo-fan": 103}
RUN_SEEDS = {"demo-motor": 201, "demo-pompa": 202, "demo-fan": 203}
HISTORY_SEGMENT = "demo_normal_history"
INTERVAL_S = 5.0


def demo_payload(spec: dict) -> dict:
    return {
        **spec,
        "data_source": "simulation",
        "expected_interval_s": INTERVAL_S,
        "transition_s": 30.0,
        "modes": default_modes(),
    }


def history_mode_changes() -> tuple[list[list], int]:
    steps_per_minute = int(60 / INTERVAL_S)
    changes, step = [], 1
    for mode, minutes in HISTORY_SCHEDULE:
        changes.append([step, mode])
        step += minutes * steps_per_minute
    return changes, step - 1


def seed_demo(conn: sqlite3.Connection, now: float | None = None) -> None:
    now = float(int(now if now is not None else now_epoch()))
    changes, total_steps = history_mode_changes()
    start = now - total_steps * INTERVAL_S
    for spec in DEMO_MACHINES:
        machine = get_machine(conn, spec["id"]) or create_machine(conn, demo_payload(spec), is_demo=True)
        simulator = MachineSimulator(
            spec["sim_profile"],
            HISTORY_SEEDS[spec["id"]],
            start,
            machine_id=spec["id"],
            interval_s=INTERVAL_S,
            scenario="normal",
            start_mode=HISTORY_SCHEDULE[0][0],
            mode_changes=changes,
        )
        records = generate_records(simulator, total_steps)
        ingest(conn, records, IngestOptions(source="simulation", is_demo=True, segment=HISTORY_SEGMENT))
        for mode in ("idle", "loaded"):
            baselines.create(
                conn,
                machine,
                mode,
                to_iso(start),
                to_iso(now),
                confirm_normal=True,
                note="Başlangıçta, açıkça etiketlenmiş normal demo geçmişinden (demo_normal_history) oluşturuldu. "
                "Senaryo/test verisi katılmadı.",
                is_demo=True,
            )
    set_meta(conn, "demo_seeded_at", to_iso(now))


def reset_demo(conn: sqlite3.Connection) -> dict:
    placeholders = ",".join("?" for _ in DEMO_IDS)
    counts = {
        "telemetry": conn.execute("SELECT COUNT(*) FROM telemetry WHERE is_demo = 1").fetchone()[0],
        "alerts": conn.execute("SELECT COUNT(*) FROM alerts WHERE is_demo = 1").fetchone()[0],
        "baselines": conn.execute("SELECT COUNT(*) FROM baselines WHERE is_demo = 1").fetchone()[0],
        "simulation_runs": conn.execute(
            f"SELECT COUNT(*) FROM simulation_runs WHERE machine_id IN ({placeholders})", DEMO_IDS
        ).fetchone()[0],
    }
    conn.execute("UPDATE review_notes SET alert_id = NULL WHERE alert_id IN (SELECT id FROM alerts WHERE is_demo = 1)")
    conn.execute("DELETE FROM alerts WHERE is_demo = 1")
    conn.execute("DELETE FROM telemetry WHERE is_demo = 1")
    conn.execute("DELETE FROM baselines WHERE is_demo = 1")
    conn.execute(f"DELETE FROM simulation_runs WHERE machine_id IN ({placeholders})", DEMO_IDS)
    conn.execute(f"DELETE FROM machine_state WHERE machine_id IN ({placeholders})", DEMO_IDS)
    for spec in DEMO_MACHINES:
        if get_machine(conn, spec["id"]):
            update_machine(conn, spec["id"], demo_payload(spec))
    seed_demo(conn)
    return counts
