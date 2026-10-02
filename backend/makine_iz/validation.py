"""Veri doğrulama katmanı.

Simülasyon, CSV ve sensör verisi analizden ÖNCE buradan geçer. Geçersiz değerler
sıfıra çevrilmez; kayıt üzerinde "quality_flags" listesine işaret eklenir.

İşaretler:
  missing:<alan>       → eksik ölçüm
  non_numeric:<alan>   → sayısal olmayan değer
  negative:<alan>      → negatif RMS, güç veya devir
  out_of_range:<alan>  → makine için tanımlı beklenen aralığın dışında
  missing_mode         → çalışma modu yok
  invalid_mode         → stopped / idle / loaded dışında bir mod
  undefined_mode       → mod bu makine için tanımlı değil
  upstream:<işaret>    → veri kaynağının kendi gönderdiği işaret (bilgi amaçlı)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .config import FEATURES, MODES, NON_NEGATIVE, SOURCES
from .timeutil import parse_timestamp

INVALIDATING_PREFIXES = (
    "missing:",
    "non_numeric:",
    "negative:",
    "out_of_range:",
    "missing_mode",
    "invalid_mode",
    "undefined_mode",
)


def is_invalid(flags: list[str]) -> bool:
    return any(flag.startswith(INVALIDATING_PREFIXES) for flag in flags)


def field_is_invalid(flags: list[str], feature: str) -> bool:
    return any(flag.endswith(":" + feature) and flag.startswith(INVALIDATING_PREFIXES) for flag in flags)


@dataclass
class ValidatedRecord:
    machine_id: str
    ts: float | None
    mode: str | None  # veritabanına yazılacak mod (bilinen bir mod ise)
    analysis_mode: str | None  # analizde kullanılacak mod (geçerli ve makinede tanımlı ise)
    values: dict[str, float | None]
    flags: list[str]
    raw: dict
    source: str
    reject: str | None = None  # kayıt saklanamıyorsa nedeni
    notes: list[str] = field(default_factory=list)


def parse_number(value: Any) -> tuple[float | None, str | None]:
    """(sayı, sorun) döndürür. sorun: None, 'missing' veya 'non_numeric'."""
    if value is None:
        return None, "missing"
    if isinstance(value, bool):
        return None, "non_numeric"
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if text == "":
            return None, "missing"
        try:
            number = float(text)
        except ValueError:
            return None, "non_numeric"
    else:
        return None, "non_numeric"
    if not math.isfinite(number):
        return None, "non_numeric"
    return number, None


def validate_record(raw: dict, machine: dict | None, source_override: str | None = None) -> ValidatedRecord:
    machine_id = str(raw.get("machine_id") or "").strip()
    flags: list[str] = []
    notes: list[str] = []

    source = source_override or str(raw.get("source") or "sensor")
    if source not in SOURCES:
        source = "sensor"

    record = ValidatedRecord(
        machine_id=machine_id, ts=None, mode=None, analysis_mode=None,
        values={f: None for f in FEATURES}, flags=flags, raw=raw, source=source, notes=notes,
    )
    if not machine_id:
        record.reject = "Makine kimliği (machine_id) boş."
        return record
    if machine is None:
        record.reject = f"Bilinmeyen makine kimliği: '{machine_id}'."
        return record

    ts, error, assumed = parse_timestamp(raw.get("timestamp"))
    if error:
        record.reject = f"Geçersiz zaman damgası: {error}."
        return record
    record.ts = ts
    if assumed:
        notes.append("Saat dilimi belirtilmemiş; Europe/Istanbul kabul edildi.")

    # Çalışma modu
    mode_raw = raw.get("operating_mode")
    mode = str(mode_raw).strip().lower() if mode_raw is not None else ""
    if not mode:
        flags.append("missing_mode")
    elif mode not in MODES:
        flags.append("invalid_mode")
    else:
        record.mode = mode
        if machine["modes"].get(mode, {}).get("enabled", False):
            record.analysis_mode = mode
        else:
            flags.append("undefined_mode")

    # Ölçüm değerleri
    for feature in FEATURES:
        number, problem = parse_number(raw.get(feature))
        if problem:
            flags.append(f"{problem}:{feature}")
            continue
        record.values[feature] = number
        if feature in NON_NEGATIVE and number < 0:
            flags.append(f"negative:{feature}")
            continue
        low, high = machine["ranges"][feature]
        if number < low or number > high:
            flags.append(f"out_of_range:{feature}")

    # Kaynağın kendi kalite işaretleri (yalnızca bilgi; analizi değiştirmez)
    upstream = raw.get("quality_flags")
    if isinstance(upstream, str) and upstream.strip():
        upstream = [part.strip() for part in upstream.replace(";", ",").split(",") if part.strip()]
    if isinstance(upstream, list):
        for item in upstream[:10]:
            flags.append(f"upstream:{str(item)[:40]}")
    return record
