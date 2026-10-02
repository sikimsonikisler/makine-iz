"""Makine kayıtları: ekleme, düzenleme, listeleme ve doğrulama."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from .config import (
    DEFAULT_FEATURE_FLOORS,
    DEFAULT_INTERVAL_S,
    DEFAULT_RANGES,
    DEFAULT_TRANSITION_S,
    FEATURE_LABELS,
    FEATURES,
    MODES,
    SOURCES,
)
from .db import dumps, loads
from .timeutil import now_epoch, to_iso

SIM_PROFILES = ("motor", "pump", "fan", "compressor")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


class MachineError(ValueError):
    """Kullanıcıya gösterilebilecek Türkçe doğrulama hatası."""


def default_modes() -> dict:
    return {
        "stopped": {"enabled": True, "description": "Makine durmuş; sapma değerlendirmesi yapılmaz."},
        "idle": {"enabled": True, "description": "Makine boşta çalışıyor."},
        "loaded": {"enabled": True, "description": "Makine yük altında çalışıyor."},
    }


def machine_from_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["modes"] = loads(data.pop("modes_json"), default_modes())
    data["ranges"] = loads(data.pop("ranges_json"), DEFAULT_RANGES)
    data["floors"] = loads(data.pop("floors_json"), DEFAULT_FEATURE_FLOORS)
    data["is_demo"] = bool(data["is_demo"])
    return data


def get_machine(conn: sqlite3.Connection, machine_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM machines WHERE id = ?", (machine_id,)).fetchone()
    return machine_from_row(row) if row else None


def list_machines(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM machines ORDER BY is_demo DESC, name").fetchall()
    return [machine_from_row(r) for r in rows]


def _number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise MachineError(f"'{field}' alanı sayı olmalı.") from None
    if number != number:  # NaN
        raise MachineError(f"'{field}' alanı sayı olmalı.")
    return number


def _clean_modes(raw: Any) -> dict:
    modes = default_modes()
    if raw is None:
        return modes
    if not isinstance(raw, dict):
        raise MachineError("Çalışma modları geçersiz.")
    for mode, conf in raw.items():
        if mode not in MODES:
            raise MachineError(f"Bilinmeyen çalışma modu: {mode}. Kullanılabilir: stopped, idle, loaded.")
        if not isinstance(conf, dict):
            raise MachineError(f"'{mode}' modu ayarı geçersiz.")
        modes[mode] = {
            "enabled": True if mode == "stopped" else bool(conf.get("enabled", True)),
            "description": str(conf.get("description", modes[mode]["description"]))[:300],
        }
    if not (modes["idle"]["enabled"] or modes["loaded"]["enabled"]):
        raise MachineError("En az bir çalışma modu (Boşta veya Yük altında) etkin olmalı.")
    return modes


def _clean_ranges(raw: Any) -> dict:
    ranges = {f: list(v) for f, v in DEFAULT_RANGES.items()}
    if raw is None:
        return ranges
    if not isinstance(raw, dict):
        raise MachineError("Beklenen ölçüm aralıkları geçersiz.")
    for feature, pair in raw.items():
        if feature not in FEATURES:
            raise MachineError(f"Bilinmeyen ölçüm alanı: {feature}")
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise MachineError(f"{FEATURE_LABELS[feature]} için [en az, en çok] biçiminde iki değer girin.")
        low = _number(pair[0], f"{FEATURE_LABELS[feature]} en az")
        high = _number(pair[1], f"{FEATURE_LABELS[feature]} en çok")
        if low >= high:
            raise MachineError(f"{FEATURE_LABELS[feature]} için en az değer, en çok değerden küçük olmalı.")
        ranges[feature] = [low, high]
    return ranges


def _clean_floors(raw: Any) -> dict:
    floors = dict(DEFAULT_FEATURE_FLOORS)
    if raw is None:
        return floors
    if not isinstance(raw, dict):
        raise MachineError("Alt sınırlar (feature_floor) geçersiz.")
    for feature, value in raw.items():
        if feature not in FEATURES:
            raise MachineError(f"Bilinmeyen ölçüm alanı: {feature}")
        number = _number(value, f"{FEATURE_LABELS[feature]} alt sınırı")
        if number <= 0:
            raise MachineError(f"{FEATURE_LABELS[feature]} alt sınırı sıfırdan büyük olmalı.")
        floors[feature] = number
    return floors


def validate_payload(payload: dict, *, existing: dict | None = None) -> dict:
    """Ekleme veya düzenleme isteğini doğrular, kaydedilecek alanları döndürür."""
    base = existing or {}
    data: dict[str, Any] = {}

    if existing is None:
        machine_id = str(payload.get("id") or "").strip().lower()
        if not ID_PATTERN.match(machine_id):
            raise MachineError(
                "Makine kimliği 2–40 karakter olmalı; küçük harf, rakam, '-' ve '_' kullanılabilir (ör. kompresor-1)."
            )
        data["id"] = machine_id

    name = str(payload.get("name", base.get("name", "")) or "").strip()
    if not name:
        raise MachineError("Makine adı boş olamaz.")
    data["name"] = name[:120]

    machine_type = str(payload.get("machine_type", base.get("machine_type", "")) or "").strip()
    if not machine_type:
        raise MachineError("Makine türü boş olamaz (ör. Motor, Pompa, Fan).")
    data["machine_type"] = machine_type[:60]

    data["location"] = str(payload.get("location", base.get("location", "")) or "").strip()[:120]
    data["description"] = str(payload.get("description", base.get("description", "")) or "").strip()[:1000]

    source = payload.get("data_source", base.get("data_source", "sensor"))
    if source not in SOURCES:
        raise MachineError("Veri kaynağı simulation, csv veya sensor olmalı.")
    data["data_source"] = source

    profile = payload.get("sim_profile", base.get("sim_profile"))
    if source == "simulation":
        if profile not in SIM_PROFILES:
            raise MachineError("Simülasyon kaynağı için simülasyon profili seçin (motor, pump, fan veya compressor).")
    else:
        profile = profile if profile in SIM_PROFILES else None
    data["sim_profile"] = profile

    interval = _number(payload.get("expected_interval_s", base.get("expected_interval_s", DEFAULT_INTERVAL_S)), "Beklenen ölçüm aralığı")
    if not (1 <= interval <= 3600):
        raise MachineError("Beklenen ölçüm aralığı 1–3600 saniye arasında olmalı.")
    data["expected_interval_s"] = interval

    transition = _number(payload.get("transition_s", base.get("transition_s", DEFAULT_TRANSITION_S)), "Geçiş süresi")
    if not (0 <= transition <= 3600):
        raise MachineError("Geçiş süresi 0–3600 saniye arasında olmalı.")
    data["transition_s"] = transition

    data["modes"] = _clean_modes(payload["modes"]) if "modes" in payload else (base.get("modes") or default_modes())
    data["ranges"] = _clean_ranges(payload["ranges"]) if "ranges" in payload else (base.get("ranges") or _clean_ranges(None))
    data["floors"] = _clean_floors(payload["floors"]) if "floors" in payload else (base.get("floors") or _clean_floors(None))
    return data


def create_machine(conn: sqlite3.Connection, payload: dict, *, is_demo: bool = False) -> dict:
    data = validate_payload(payload)
    if get_machine(conn, data["id"]):
        raise MachineError(f"'{data['id']}' kimlikli bir makine zaten var.")
    now = to_iso(now_epoch())
    conn.execute(
        """INSERT INTO machines (id, name, machine_type, location, description, data_source, sim_profile,
               expected_interval_s, transition_s, modes_json, ranges_json, floors_json, is_demo, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            data["id"], data["name"], data["machine_type"], data["location"], data["description"],
            data["data_source"], data["sim_profile"], data["expected_interval_s"], data["transition_s"],
            dumps(data["modes"]), dumps(data["ranges"]), dumps(data["floors"]), int(is_demo), now, now,
        ),
    )
    return get_machine(conn, data["id"])  # type: ignore[return-value]


def update_machine(conn: sqlite3.Connection, machine_id: str, payload: dict) -> dict:
    existing = get_machine(conn, machine_id)
    if existing is None:
        raise LookupError("Makine bulunamadı.")
    data = validate_payload(payload, existing=existing)
    conn.execute(
        """UPDATE machines SET name = ?, machine_type = ?, location = ?, description = ?, data_source = ?,
               sim_profile = ?, expected_interval_s = ?, transition_s = ?, modes_json = ?, ranges_json = ?,
               floors_json = ?, updated_at = ?
           WHERE id = ?""",
        (
            data["name"], data["machine_type"], data["location"], data["description"], data["data_source"],
            data["sim_profile"], data["expected_interval_s"], data["transition_s"], dumps(data["modes"]),
            dumps(data["ranges"]), dumps(data["floors"]), to_iso(now_epoch()), machine_id,
        ),
    )
    return get_machine(conn, machine_id)  # type: ignore[return-value]
