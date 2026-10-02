"""Ölçümlerden Türkçe açıklama metni üretir.

Kural: Yalnızca ölçülen değişimi anlat. "Rulman bozuldu" gibi doğrulanmamış teşhis yazma.
"""
from __future__ import annotations

from .config import FEATURE_LABELS, FEATURE_UNITS, MODE_LABELS
from .timeutil import ISTANBUL

DIGITS = {"vibration_rms_g": 3, "temperature_c": 1, "power_kw": 2, "rpm": 0}

DISCLAIMER = "Bu bir ölçüm sapmasıdır; belirli bir mekanik arızanın kanıtı değildir. Yerinde inceleme önerilir."


def num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def feature_value(feature: str, value: float | None) -> str:
    return f"{num(value, DIGITS[feature])} {FEATURE_UNITS[feature]}"


def describe_feature_change(item: dict) -> str:
    feature = item["feature"]
    diff = item["diff"]
    sign = "+" if diff >= 0 else "−"
    pct = item.get("diff_pct")
    pct_text = f" ({sign}{num(abs(pct), 0)} %)" if pct is not None else ""
    return (
        f"{FEATURE_LABELS[feature]} {feature_value(feature, item['value'])} "
        f"(referans medyanı {feature_value(feature, item['median'])}, fark {sign}{num(abs(diff), DIGITS[feature])} "
        f"{FEATURE_UNITS[feature]}{pct_text}, z = {num(item['z'], 1)})"
    )


def deviation_explanation(mode: str, event: dict, baseline_version: int | None) -> str:
    level_text = "Belirgin sapma" if event["level"] == "strong" else "İnceleme uyarısı"
    strong = f", {event['strong_hits']} tanesinde z ≥ 6" if event.get("strong_hits") else ""
    top = event["summary"]["features"][:2]
    changes = "; ".join(describe_feature_change(item) for item in top)
    return (
        f"{level_text}. Çalışma modu: {MODE_LABELS.get(mode, mode)} (referans v{baseline_version}). "
        f"Son {event['window_count']} geçerli ölçüm penceresinin {event['hits']} tanesinde z ≥ 3{strong}. "
        f"En çok değişen iki ölçüm: {changes}. {DISCLAIMER}"
    )


def _clock(epoch: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(epoch, tz=ISTANBUL).strftime("%d.%m.%Y %H:%M:%S")


FLAG_TEXT = {
    "missing": "eksik ölçüm",
    "non_numeric": "sayısal olmayan değer",
    "negative": "negatif değer",
    "out_of_range": "beklenen aralığın dışında",
}


def describe_flags(flags: list[str]) -> str:
    parts = []
    for flag in flags:
        if ":" in flag:
            kind, feature = flag.split(":", 1)
            if kind in FLAG_TEXT and feature in FEATURE_LABELS:
                parts.append(f"{FEATURE_LABELS[feature]}: {FLAG_TEXT[kind]}")
        elif flag == "missing_mode":
            parts.append("çalışma modu yok")
        elif flag == "invalid_mode":
            parts.append("çalışma modu geçersiz")
        elif flag == "undefined_mode":
            parts.append("çalışma modu bu makine için tanımlı değil")
        elif flag == "invalid_timestamp":
            parts.append("zaman damgası geçersiz")
    return ", ".join(parts) or "geçersiz kayıt"


def dq_explanation(dq_type: str, details: dict) -> str:
    if dq_type == "invalid":
        last = describe_flags(details.get("last_flags", []))
        return (
            f"Eksik veya geçersiz ölçüm ({details.get('count', 1)} kayıt). Son sorun: {last}. "
            "Bu kayıtlar sapma hesabına alınmadı ve sıfıra çevrilmedi. Bu bir veri kalitesi sorunudur; "
            "makine davranışı hakkında sonuç çıkarılmadı."
        )
    if dq_type == "data_gap":
        start = details.get("last_record_ts")
        start_text = f"{_clock(start)} tarihindeki son kayıttan sonra " if start else ""
        return (
            f"Veri gelmiyor: {start_text}en az 3 beklenen ölçüm aralığı boyunca kayıt alınmadı. "
            "Ekrandaki son değerler güncel değildir. Kesinti süresince sapma değerlendirmesi yapılmaz."
        )
    if dq_type == "frozen":
        return (
            f"Veri donması şüphesi: çalışan makinede {details.get('count', 12)} ardışık kayıtta dört ölçüm de "
            "birebir aynı kaldı. Bu, sensörün kesin bozulduğu anlamına gelmez; ilk sürümde sınırlı bir kontroldür."
        )
    if dq_type == "sequence":
        return (
            f"Yinelenen veya sırası bozuk kayıt ({details.get('duplicates', 0)} yinelenen, "
            f"{details.get('out_of_order', 0)} sırası bozuk). Yinelenen kayıtlar saklanmadı; sırası bozuk kayıtlar "
            "saklandı ancak süreklilik hesabına alınmadı."
        )
    return "Veri kalitesi sorunu."


UNEVALUABLE_REASONS = {
    "gap": "Veri kesintisi nedeniyle sapma değerlendirilemiyor.",
    "invalid": "Eksik veya geçersiz ölçüm nedeniyle sapma değerlendirilemiyor.",
    "frozen": "Veri donması şüphesi nedeniyle sapma değerlendirilemiyor.",
    "mode_change": "Makine farklı bir çalışma moduna geçti; bu moddaki sapma şu an değerlendirilemiyor.",
    "stopped": "Makine durdu; sapma değerlendirilemiyor.",
    "no_baseline": "Geçerli referans yok; sapma değerlendirilemiyor.",
    "no_data": "Veri gelmiyor; sapma değerlendirilemiyor.",
}
