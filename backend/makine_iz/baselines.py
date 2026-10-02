"""Referans profili (BaselineProfile) oluşturma ve sorgulama.

- Referans, kullanıcının "normal çalışma olarak kabul ediyorum" diyerek seçtiği aralıktan hesaplanır.
- Her makine + çalışan mod (idle / loaded) için ayrı ve sürümlüdür.
- Gelen ölçümlerle otomatik GÜNCELLENMEZ (sürmekte olan sapma "normal" diye öğrenilmesin).
- Geçersiz, sırası bozuk, donmuş veya geçiş süresindeki kayıtlar referansa katılmaz.
"""
from __future__ import annotations

import sqlite3

from .alerts import supersede_for_new_baseline
from .analysis import compute_baseline_stats
from .config import ANALYSIS, FEATURES, MODE_LABELS, RUNNING_MODES
from .db import dumps, loads
from .store import load_state, save_state
from .timeutil import from_iso, now_epoch, to_iso
from .validation import is_invalid

EXCLUDED_STATUSES = {
    "transition": "geçiş süresinde",
    "frozen_suspect": "veri donması şüphesi",
    "out_of_order": "sırası bozuk",
    "invalid": "geçersiz",
}


class BaselineError(ValueError):
    pass


def baseline_from_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["stats"] = loads(data.pop("stats_json"), {})
    data["is_active"] = bool(data["is_active"])
    data["is_demo"] = bool(data["is_demo"])
    return data


def active_baselines(conn: sqlite3.Connection, machine_id: str) -> dict[str, dict]:
    rows = conn.execute("SELECT * FROM baselines WHERE machine_id = ? AND is_active = 1", (machine_id,)).fetchall()
    return {row["mode"]: baseline_from_row(row) for row in rows}


def list_baselines(conn: sqlite3.Connection, machine_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM baselines WHERE machine_id = ? ORDER BY mode, version DESC", (machine_id,)
    ).fetchall()
    return [baseline_from_row(r) for r in rows]


def get_baseline(conn: sqlite3.Connection, baseline_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM baselines WHERE id = ?", (baseline_id,)).fetchone()
    return baseline_from_row(row) if row else None


def _check_mode(machine: dict, mode: str) -> None:
    if mode == "stopped":
        raise BaselineError("Durmuş makine için referans oluşturulmaz; durmuş makinede sapma hesaplanmaz.")
    if mode not in RUNNING_MODES:
        raise BaselineError("Referans modu idle (Boşta) veya loaded (Yük altında) olmalı.")
    if not machine["modes"].get(mode, {}).get("enabled", False):
        raise BaselineError(f"'{MODE_LABELS[mode]}' modu bu makine için tanımlı değil.")


def collect_samples(conn: sqlite3.Connection, machine_id: str, mode: str, start_iso: str, end_iso: str):
    rows = conn.execute(
        f"""SELECT {", ".join(FEATURES)}, quality_flags, analysis_status FROM telemetry
            WHERE machine_id = ? AND operating_mode = ? AND ts >= ? AND ts <= ? ORDER BY ts""",
        (machine_id, mode, start_iso, end_iso),
    ).fetchall()
    samples: dict[str, list[float]] = {f: [] for f in FEATURES}
    excluded: dict[str, int] = {}
    for row in rows:
        flags = loads(row["quality_flags"], [])
        reason = None
        if is_invalid(flags) or any(row[f] is None for f in FEATURES):
            reason = "geçersiz"
        elif row["analysis_status"] in EXCLUDED_STATUSES:
            reason = EXCLUDED_STATUSES[row["analysis_status"]]
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        for feature in FEATURES:
            samples[feature].append(float(row[feature]))
    return samples, len(samples[FEATURES[0]]), excluded


def _range(start: str, end: str) -> tuple[str, str]:
    try:
        start_epoch, end_epoch = from_iso(start), from_iso(end)
    except ValueError as exc:
        raise BaselineError(f"Tarih aralığı okunamadı: {exc}") from None
    if end_epoch <= start_epoch:
        raise BaselineError("Bitiş zamanı başlangıçtan sonra olmalı.")
    return to_iso(start_epoch), to_iso(end_epoch)


def preview(conn: sqlite3.Connection, machine: dict, mode: str, start: str, end: str) -> dict:
    _check_mode(machine, mode)
    start_iso, end_iso = _range(start, end)
    samples, count, excluded = collect_samples(conn, machine["id"], mode, start_iso, end_iso)
    overlapping = conn.execute(
        """SELECT COUNT(*) FROM alerts WHERE machine_id = ? AND kind = 'deviation' AND mode = ?
             AND started_at <= ? AND COALESCE(ended_at, updated_at) >= ?""",
        (machine["id"], mode, end_iso, start_iso),
    ).fetchone()[0]
    enough = count >= ANALYSIS.min_baseline_samples
    result = {
        "mode": mode,
        "range_start": start_iso,
        "range_end": end_iso,
        "valid_count": count,
        "required": ANALYSIS.min_baseline_samples,
        "excluded": excluded,
        "enough": enough,
        "overlapping_deviation_alerts": overlapping,
        "stats": compute_baseline_stats(samples) if count > 0 else None,
        "message": (
            "Referans oluşturulabilir."
            if enough
            else f"Referans için veri yetersiz: seçilen aralıkta {count} geçerli kayıt var, en az "
            f"{ANALYSIS.min_baseline_samples} gerekli."
        ),
    }
    return result


def create(
    conn: sqlite3.Connection,
    machine: dict,
    mode: str,
    start: str,
    end: str,
    *,
    confirm_normal: bool,
    note: str = "",
    is_demo: bool = False,
) -> dict:
    if not confirm_normal:
        raise BaselineError("Referans oluşturmak için seçilen aralığı normal çalışma olarak kabul ettiğinizi onaylayın.")
    info = preview(conn, machine, mode, start, end)
    if not info["enough"]:
        raise BaselineError(info["message"])
    samples, count, excluded = collect_samples(conn, machine["id"], mode, info["range_start"], info["range_end"])
    stats = compute_baseline_stats(samples)
    version = (
        conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM baselines WHERE machine_id = ? AND mode = ?", (machine["id"], mode)
        ).fetchone()[0]
        + 1
    )
    now = now_epoch()
    conn.execute("UPDATE baselines SET is_active = 0 WHERE machine_id = ? AND mode = ?", (machine["id"], mode))
    cursor = conn.execute(
        """INSERT INTO baselines (machine_id, mode, version, created_at, range_start, range_end, sample_count,
               excluded_count, stats_json, is_active, is_demo, note)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
        (
            machine["id"], mode, version, to_iso(now), info["range_start"], info["range_end"], count,
            sum(excluded.values()), dumps(stats), int(is_demo), note.strip()[:500],
        ),
    )
    # Eski referansa bağlı açık uyarılar o sürümle kalır; yeni sapmalar yeni sürüme bağlanır.
    supersede_for_new_baseline(conn, machine["id"], mode, version, now)
    # Karşılaştırma ölçütü değişti: süreklilik sayaçları temiz başlar.
    state = load_state(conn, machine["id"])
    state.reset_persistence()
    save_state(conn, machine["id"], state)
    return get_baseline(conn, int(cursor.lastrowid))  # type: ignore[return-value]
