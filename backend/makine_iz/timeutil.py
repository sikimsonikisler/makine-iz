"""Zaman yardımcıları.

Veritabanında zamanlar UTC olarak, sabit biçimli ISO-8601 metni ("2026-10-02T11:30:05.000Z")
şeklinde saklanır. Bu biçim alfabetik sıralandığında zaman sırasına da uyar.
Arayüz bu zamanları Europe/Istanbul saat diliminde gösterir.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ISTANBUL = ZoneInfo("Europe/Istanbul")
MIN_EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()
MAX_EPOCH = datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp()


def now_epoch() -> float:
    return round(time.time(), 3)


def to_iso(epoch: float) -> str:
    """Saniye cinsinden UTC zamanını milisaniye hassasiyetli ISO metnine çevirir."""
    total_ms = int(round(epoch * 1000))
    dt = datetime.fromtimestamp(total_ms // 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{total_ms % 1000:03d}Z"


def from_iso(text: str) -> float:
    """Veritabanındaki (veya API'den gelen) ISO metnini UTC saniyesine çevirir."""
    epoch, error, _ = parse_timestamp(text)
    if error:
        raise ValueError(error)
    return epoch  # type: ignore[return-value]


def parse_timestamp(value) -> tuple[float | None, str | None, bool]:
    """Zaman damgasını çözer.

    Dönüş: (utc_saniye, hata_mesajı, istanbul_varsayıldı_mı)
    - Saat dilimi içermeyen metinler Europe/Istanbul yerel saati kabul edilir.
    - Sayılar Unix zaman damgası (saniye) kabul edilir.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, "Zaman damgası boş", False
    if isinstance(value, bool):
        return None, "Zaman damgası okunamadı", False
    assumed = False
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            return None, "Zaman damgası okunamadı", False
        epoch = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith(("z", "Z")):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None, f"Zaman damgası okunamadı: '{value}' (beklenen biçim: 2026-10-02T14:30:05+03:00)", False
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ISTANBUL)
            assumed = True
        epoch = dt.timestamp()
    else:
        return None, "Zaman damgası okunamadı", False
    if not (MIN_EPOCH <= epoch <= MAX_EPOCH):
        return None, "Zaman damgası 2000–2100 aralığının dışında", False
    return round(epoch, 3), None, assumed


def istanbul_text(epoch: float) -> str:
    """Dışa aktarımlar için okunabilir İstanbul saati."""
    return datetime.fromtimestamp(epoch, tz=ISTANBUL).strftime("%Y-%m-%d %H:%M:%S")
