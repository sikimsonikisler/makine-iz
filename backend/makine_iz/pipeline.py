"""Ortak veri yolu: doğrulama → saklama → analiz → uyarı.

Simülasyon, CSV aktarımı ve sensör API'si AYNI fonksiyonu (ingest) kullanır.
Analiz motoruna yalnızca ölçüm, mod, zaman ve referans gider; senaryo adı veya
"gerçek durum" etiketi bu yoldan hiç geçmez.
"""
from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field

from .alerts import AlertContext, _find_open, apply_events, dq_close, dq_upsert
from .analysis import Observation, analyze_step
from .baselines import active_baselines
from .config import ANALYSIS, FEATURES, LIVE_SOURCES
from .db import dumps
from .machines import get_machine
from .store import load_state, save_state
from .timeutil import now_epoch, to_iso
from .validation import ValidatedRecord, validate_record


@dataclass
class IngestOptions:
    source: str  # simulation | csv | sensor
    is_demo: bool = False
    sim_run_id: int | None = None
    import_id: str | None = None
    segment: str | None = None  # ör. "demo_normal_history" (etiketli normal demo geçmişi)

    @property
    def live(self) -> bool:
        return self.source in LIVE_SOURCES


@dataclass
class IngestResult:
    index: int
    machine_id: str | None
    timestamp: str | None
    stored: bool
    status: str
    flags: list[str] = field(default_factory=list)
    z_max: float | None = None
    score: float | None = None
    message: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def ingest(conn: sqlite3.Connection, raw_records: list[dict], options: IngestOptions) -> list[IngestResult]:
    machines: dict[str, dict | None] = {}
    validated: list[tuple[int, ValidatedRecord]] = []
    results: list[IngestResult | None] = [None] * len(raw_records)

    for index, raw in enumerate(raw_records):
        if not isinstance(raw, dict):
            results[index] = IngestResult(index, None, None, False, "rejected", message="Kayıt bir nesne olmalı.")
            continue
        machine_id = str(raw.get("machine_id") or "").strip()
        if machine_id not in machines:
            machines[machine_id] = get_machine(conn, machine_id) if machine_id else None
        validated.append((index, validate_record(raw, machines[machine_id], source_override=options.source)))

    ctx = AlertContext(is_demo=options.is_demo, source=options.source, live=options.live)
    groups: dict[str, list[tuple[int, ValidatedRecord]]] = {}
    for index, record in validated:
        if record.reject:
            results[index] = IngestResult(index, record.machine_id or None, None, False, "rejected", message=record.reject)
            machine = machines.get(record.machine_id)
            if machine is not None and record.ts is None:
                _record_invalid_timestamp(conn, machine, ctx)
            continue
        groups.setdefault(record.machine_id, []).append((index, record))

    for machine_id, items in groups.items():
        machine = machines[machine_id]
        assert machine is not None
        # Toplu gönderimde kayıtlar zaman sırasına göre işlenir (sıralama kararlıdır).
        items.sort(key=lambda item: item[1].ts)  # type: ignore[arg-type, return-value]
        _ingest_machine(conn, machine, items, options, ctx, results)

    return [r for r in results if r is not None]


def _record_invalid_timestamp(conn, machine: dict, ctx: AlertContext) -> None:
    state = load_state(conn, machine["id"])
    state.good_streak = 0
    ts = state.last_ts or now_epoch()
    dq_upsert(conn, machine, "invalid", ts, ctx, flags=["invalid_timestamp"])
    save_state(conn, machine["id"], state)


def _ingest_machine(conn, machine: dict, items, options: IngestOptions, ctx: AlertContext, results) -> None:
    machine_id = machine["id"]
    state = load_state(conn, machine_id)
    baselines = active_baselines(conn, machine_id)
    first_iso, last_iso = to_iso(items[0][1].ts), to_iso(items[-1][1].ts)
    existing = {
        row["ts"]
        for row in conn.execute(
            "SELECT ts FROM telemetry WHERE machine_id = ? AND ts >= ? AND ts <= ?", (machine_id, first_iso, last_iso)
        )
    }
    gap_alert_open = _find_open(conn, machine_id, "data_quality", dq_type="data_gap") is not None

    for index, record in items:
        ts = float(record.ts)  # type: ignore[arg-type]
        ts_iso = to_iso(ts)
        # Yinelenen kayıt politikası: aynı makine + aynı zaman damgası → ilk kayıt korunur, sonraki saklanmaz.
        if ts_iso in existing:
            state.seq_clean = 0
            dq_upsert(conn, machine, "sequence", ts, ctx, mode=record.analysis_mode, extra={"duplicates": 1})
            results[index] = IngestResult(
                index, machine_id, ts_iso, False, "duplicate", ["duplicate"],
                message="Yinelenen kayıt: bu makine için aynı zaman damgalı kayıt zaten var; saklanmadı.",
            )
            continue
        existing.add(ts_iso)

        baseline = baselines.get(record.analysis_mode) if record.analysis_mode else None
        obs = Observation(ts=ts, mode=record.analysis_mode, values=record.values, flags=record.flags)
        result = analyze_step(
            state,
            obs,
            baseline["stats"] if baseline else None,
            machine["floors"],
            machine["transition_s"],
            machine["expected_interval_s"],
            ANALYSIS,
        )
        conn.execute(
            f"""INSERT INTO telemetry (machine_id, ts, operating_mode, {", ".join(FEATURES)}, source, quality_flags,
                    raw_json, is_demo, sim_run_id, import_id, segment, analysis_status, z_json, z_max, baseline_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                machine_id, ts_iso, record.mode, *[record.values[f] for f in FEATURES], record.source,
                dumps(result.flags), dumps(record.raw) if _needs_raw(result.flags) else None,
                int(options.is_demo), options.sim_run_id, options.import_id, options.segment, result.status,
                dumps({k: round(v, 4) for k, v in result.z.items()}) if result.z else None,
                round(result.z_max, 4) if result.z_max is not None else None,
                baseline["id"] if (baseline and result.z is not None) else None,
            ),
        )
        apply_events(conn, machine, record.analysis_mode, ts, result, baseline, ctx)
        # Akış yeniden başladıysa açık "Veri gelmiyor" uyarısını kapat (kesinti olayı yakalamadıysa).
        if gap_alert_open and result.status != "out_of_order":
            dq_close(conn, machine_id, "data_gap", ts)
            gap_alert_open = False
        results[index] = IngestResult(
            index, machine_id, ts_iso, True, result.status, result.flags,
            round(result.z_max, 3) if result.z_max is not None else None,
            round(result.score, 1) if result.score is not None else None,
            "; ".join(record.notes),
        )
    save_state(conn, machine_id, state)


def _needs_raw(flags: list[str]) -> bool:
    """Geçersiz değerin aslı (ör. 'abc') kaybolmasın diye ham kayıt saklanır."""
    return any(not f.startswith(("after_gap", "upstream:")) for f in flags)
