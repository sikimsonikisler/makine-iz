"""Makinenin güncel durumu (genel görünüm kartları ve makine ayrıntısı için).

Önemli kural: Şüpheli, eksik veya güncel olmayan veride makine "Referansla uyumlu"
olarak gösterilmez. Referansı olmayan makine de "normal" gösterilmez.
"""
from __future__ import annotations

import sqlite3

from .analysis import latest_change_summary
from .baselines import active_baselines
from .config import ANALYSIS, FEATURES, MODE_LABELS
from .db import loads
from .store import load_state
from .timeutil import from_iso, now_epoch

STATUS_INFO = {
    "no_data_flow": ("Veri gelmiyor", "data_issue"),
    "frozen": ("Veri donması şüphesi", "data_issue"),
    "invalid_data": ("Eksik veya geçersiz ölçüm", "data_issue"),
    "strong": ("Belirgin sapma — inceleme gerekli", "review"),
    "review": ("Sürekli sapma — inceleme gerekli", "review"),
    "sequence_issue": ("Yinelenen / sırası bozuk kayıt", "data_issue"),
    "no_data": ("Henüz veri yok", "info"),
    "stopped": ("Durmuş — değerlendirme yapılmıyor", "info"),
    "transition": ("Mod geçişi — geçiş süresi", "info"),
    "no_baseline": ("Referans oluşturulmalı", "info"),
    "awaiting_data": ("Referans hazır — yeni ölçüm bekleniyor", "info"),
    "unevaluable": ("Açık uyarı değerlendirilemiyor", "info"),
    "candidate": ("Sapma adayı — izleniyor", "watch"),
    "ok": ("Referansla uyumlu", "ok"),
}


def live_info(machine: dict, run: dict | None) -> dict:
    source = machine["data_source"]
    if source == "simulation":
        if run and run["status"] == "running":
            return {"kind": "sim_running", "label": "Simülasyon çalışıyor", "now": from_iso(run["virtual_now"]), "virtual": True}
        if run and run["status"] == "paused":
            return {"kind": "sim_paused", "label": "Simülasyon duraklatıldı", "now": None, "virtual": True,
                    "note": run.get("status_note", "")}
        return {"kind": "sim_stopped", "label": "Simülasyon çalışmıyor", "now": None, "virtual": True}
    if source == "sensor":
        return {"kind": "sensor", "label": "Canlı sensör kaynağı", "now": now_epoch(), "virtual": False}
    return {"kind": "csv", "label": "Geçmiş veri (CSV)", "now": None, "virtual": False}


def compute_status(conn: sqlite3.Connection, machine: dict, run: dict | None) -> dict:
    machine_id = machine["id"]
    state = load_state(conn, machine_id)
    last = conn.execute(
        "SELECT * FROM telemetry WHERE machine_id = ? ORDER BY ts DESC LIMIT 1", (machine_id,)
    ).fetchone()
    baselines = active_baselines(conn, machine_id)
    open_alerts = conn.execute("SELECT * FROM alerts WHERE machine_id = ? AND is_open = 1", (machine_id,)).fetchall()
    open_dq = {a["dq_type"] for a in open_alerts if a["kind"] == "data_quality"}
    deviation_open = [a for a in open_alerts if a["kind"] == "deviation"]
    deviation_active = [a for a in deviation_open if a["measurement_status"] == "active"]
    unreviewed = conn.execute(
        "SELECT COUNT(*) FROM alerts WHERE machine_id = ? AND kind = 'deviation' AND review_status != 'closed'",
        (machine_id,),
    ).fetchone()[0]
    live = live_info(machine, run)
    interval = machine["expected_interval_s"]
    current_mode = state.last_mode or (last["operating_mode"] if last else None)
    baseline = baselines.get(current_mode) if current_mode else None
    last_status = state.last_status

    age_s = None
    stale = False
    if live["now"] is not None and state.last_ts is not None:
        age_s = max(0.0, live["now"] - state.last_ts)
        stale = age_s > ANALYSIS.gap_factor * interval

    if last is None:
        code = "no_data"
    elif stale or "data_gap" in open_dq:
        code = "no_data_flow"
    elif "frozen" in open_dq or last_status == "frozen_suspect":
        code = "frozen"
    elif last_status == "invalid" or "invalid" in open_dq:
        code = "invalid_data"
    elif deviation_active:
        code = "strong" if any(a["level"] == "strong" for a in deviation_active) else "review"
    elif "sequence" in open_dq:
        code = "sequence_issue"
    elif last_status == "stopped":
        code = "stopped"
    elif last_status == "transition":
        code = "transition"
    elif baseline is None:
        code = "no_baseline"
    elif last_status == "no_baseline":
        # Son kayıt referans oluşturulmadan önce işlendi; karşılaştırma bir sonraki ölçümle başlar.
        code = "awaiting_data"
    elif any(a["mode"] == current_mode for a in deviation_open):
        code = "unevaluable"
    elif last_status in ("candidate", "strong_candidate"):
        code = "candidate"
    elif last_status == "normal":
        code = "ok"
    else:
        code = "unevaluable"

    label, category = STATUS_INFO[code]
    detail = _detail(code, machine, current_mode, age_s, state)

    badges: list[str] = []
    for alert in deviation_open:
        if alert["measurement_status"] == "unevaluable":
            badges.append(f"Açık sapma uyarısı ({MODE_LABELS.get(alert['mode'], alert['mode'])}): değerlendirilemiyor")
    if unreviewed:
        badges.append(f"İncelemesi kapatılmamış sapma uyarısı: {unreviewed}")
    if live["kind"] == "sim_paused":
        badges.append("Simülasyon duraklatıldı — son değerler güncellenmiyor")
    elif live["kind"] == "sim_stopped" and last is not None:
        badges.append("Simülasyon çalışmıyor — son değerler güncellenmiyor")

    last_values = {f: (last[f] if last else None) for f in FEATURES}
    last_flags = loads(last["quality_flags"], []) if last else []
    z = state.last_z if last_status in ("normal", "candidate", "strong_candidate", "transition") else None
    changes = latest_change_summary(z, last_values, baseline["stats"] if baseline else None)

    return {
        "code": code,
        "label": label,
        "category": category,
        "detail": detail,
        "badges": badges,
        "current_mode": current_mode,
        "last_ts": last["ts"] if last else None,
        "last_values": last_values,
        "last_flags": last_flags,
        "last_analysis_status": last_status,
        "age_s": round(age_s, 1) if age_s is not None else None,
        "stale": stale,
        "z": z,
        "z_max": state.last_z_max if z else None,
        "deviation_score": min(100.0, 10.0 * state.last_z_max) if (z and state.last_z_max is not None) else None,
        "changes": changes,
        "baseline": _baseline_summary(baseline),
        "baselines_by_mode": {mode: _baseline_summary(b) for mode, b in baselines.items()},
        "live": live,
        "needs_review": bool(deviation_active) or unreviewed > 0,
        "data_issue": category == "data_issue" or bool(open_dq),
        "open_data_issues": sorted(open_dq),
        "persistence": {
            "windows": [round(w["z_max"], 2) for w in state.windows],
            "normal_streak": state.normal_streak,
        },
    }


def _baseline_summary(baseline: dict | None) -> dict | None:
    if not baseline:
        return None
    return {
        "id": baseline["id"],
        "mode": baseline["mode"],
        "version": baseline["version"],
        "created_at": baseline["created_at"],
        "sample_count": baseline["sample_count"],
        "stats": baseline["stats"],
    }


def _detail(code: str, machine: dict, mode: str | None, age_s: float | None, state) -> str:
    mode_label = MODE_LABELS.get(mode or "", "bilinmeyen")
    interval = machine["expected_interval_s"]
    if code == "no_data":
        return "Bu makine için henüz ölçüm yok."
    if code == "no_data_flow":
        age = f"{round(age_s)} sn" if age_s is not None else "uzun süre"
        return (
            f"Son kayıttan bu yana {age} geçti (beklenen ölçüm aralığı {interval:g} sn). "
            "Gösterilen son değerler güncel değildir; kesinti süresince sapma değerlendirmesi yapılmaz."
        )
    if code == "frozen":
        return (
            "Çalışan makinede 12 veya daha fazla ardışık kayıtta dört ölçüm de birebir aynı. "
            "Bu, sensörün kesin bozulduğu anlamına gelmez; bu kayıtlar değerlendirilmiyor."
        )
    if code == "invalid_data":
        return "Son kayıtlarda eksik veya geçersiz ölçüm var. Bu kayıtlar sıfır kabul edilmedi ve değerlendirilmedi."
    if code in ("strong", "review"):
        level = "z ≥ 6" if code == "strong" else "z ≥ 3"
        return (
            f"Son 5 geçerli pencerenin en az 3'ünde {level}. Uyarı ayrıntısında hangi ölçümlerin değiştiğini görebilirsiniz. "
            "Bu bir ölçüm sapmasıdır; arıza teşhisi değildir."
        )
    if code == "sequence_issue":
        return "Yinelenen veya sırası bozuk kayıt alındı. Bu kayıtlar süreklilik hesabına alınmadı."
    if code == "stopped":
        return "Makine durmuş. Durmuş makine, çalışan makine profiliyle karşılaştırılmaz."
    if code == "transition":
        return (
            f"Çalışma modu değişti ({mode_label}). {machine['transition_s']:g} sn geçiş süresince grafikler gösterilir, "
            "yeni sapma uyarısı üretilmez."
        )
    if code == "no_baseline":
        return f"'{mode_label}' modu için referans yok. Referans oluşturulmalı; bu modda sapma hesaplanmıyor."
    if code == "awaiting_data":
        return (
            f"'{mode_label}' modu için referans hazır. Son kayıt referanstan önce işlendiği için henüz "
            "karşılaştırılmadı; yeni ölçümler geldikçe değerlendirme başlar."
        )
    if code == "unevaluable":
        return "Bu modda açık bir sapma uyarısı var; süreklilik sayaçları yeniden doluyor (en az 5 geçerli pencere gerekir)."
    if code == "candidate":
        return (
            "Son pencerede z ≥ 3. Tek pencere uyarı oluşturmaz; süreklilik izleniyor "
            "(son 5 geçerli pencerenin en az 3'ü gerekir)."
        )
    return "Son değerlendirilen pencerede dört ölçüm de referansla uyumlu (z < 3)."
