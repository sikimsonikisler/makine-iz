"""Uyarı yaşam döngüsü ve inceleme notları (servis katmanı).

Uyarının iki ayrı durumu vardır:
  measurement_status (ölçüm durumu):  active | normalized | unevaluable
  review_status      (inceleme durumu): new | in_review | closed
Kullanıcının uyarıyı görmesi/kapatması ölçüm durumunu DEĞİŞTİRMEZ; ölçüm durumu
yalnızca ölçümlerden güncellenir. Kullanıcı değerlendirmesi referansı DEĞİŞTİRMEZ.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from .analysis import StepResult
from .config import ANALYSIS, AnalysisConfig
from .db import dumps, loads
from .explain import UNEVALUABLE_REASONS, deviation_explanation, dq_explanation
from .timeutil import from_iso, now_epoch, to_iso

KINDS = ("deviation", "data_quality")
LEVELS = ("review", "strong", "data")
MEASUREMENT_STATUSES = ("active", "normalized", "unevaluable")
REVIEW_STATUSES = ("new", "in_review", "closed")
ASSESSMENTS = ("normal_change", "measurement_issue", "maintenance_found", "uncertain")
NOTE_TYPES = ("inspection", "maintenance", "general")
DQ_TYPES = ("invalid", "data_gap", "frozen", "sequence")


@dataclass
class AlertContext:
    is_demo: bool
    source: str
    live: bool


class AlertError(ValueError):
    pass


def alert_from_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["details"] = loads(data.pop("details_json"), {})
    data["is_open"] = bool(data["is_open"])
    data["is_demo"] = bool(data["is_demo"])
    return data


def _find_open(conn: sqlite3.Connection, machine_id: str, kind: str, *, mode: str | None = None, dq_type: str | None = None):
    sql = "SELECT * FROM alerts WHERE machine_id = ? AND kind = ? AND is_open = 1"
    params: list[Any] = [machine_id, kind]
    if mode is not None:
        sql += " AND mode = ?"
        params.append(mode)
    if dq_type is not None:
        sql += " AND dq_type = ?"
        params.append(dq_type)
    return conn.execute(sql + " ORDER BY id DESC LIMIT 1", params).fetchone()


def _insert(conn: sqlite3.Connection, **fields: Any) -> int:
    fields.setdefault("created_at", to_iso(now_epoch()))
    columns = ", ".join(fields)
    placeholders = ", ".join("?" for _ in fields)
    cursor = conn.execute(f"INSERT INTO alerts ({columns}) VALUES ({placeholders})", list(fields.values()))
    return int(cursor.lastrowid)


# ---------------------------------------------------------------------------
# Sapma uyarıları
# ---------------------------------------------------------------------------
def upsert_deviation(conn, machine: dict, mode: str, ts: float, event: dict, baseline: dict, ctx: AlertContext) -> int:
    """Devam eden olay için yeni uyarı açmaz; mevcut uyarıyı günceller."""
    summary = event["summary"]
    latest_z = summary["window_z"][-1]
    peak = max(summary["window_z"])
    existing = _find_open(conn, machine["id"], "deviation", mode=mode)
    if existing:
        details = loads(existing["details_json"], {})
        details.update(
            latest=summary,
            hits=event["hits"],
            strong_hits=event["strong_hits"],
            updates=int(details.get("updates", 0)) + 1,
        )
        level = "strong" if existing["level"] == "strong" or event["level"] == "strong" else "review"
        explanation = deviation_explanation(mode, {**event, "level": level}, existing["baseline_version"])
        conn.execute(
            """UPDATE alerts SET measurement_status = 'active', unevaluable_reason = NULL, updated_at = ?,
                   level = ?, peak_z = MAX(COALESCE(peak_z, 0), ?), last_z = ?, details_json = ?, explanation = ?
               WHERE id = ?""",
            (to_iso(ts), level, peak, latest_z, dumps(details), explanation, existing["id"]),
        )
        return int(existing["id"])
    details = {
        "initial": summary,
        "latest": summary,
        "hits": event["hits"],
        "strong_hits": event["strong_hits"],
        "window_count": event["window_count"],
        "updates": 0,
    }
    return _insert(
        conn,
        machine_id=machine["id"],
        mode=mode,
        kind="deviation",
        level=event["level"],
        measurement_status="active",
        review_status="new",
        started_at=to_iso(event["first_hit_ts"]),
        updated_at=to_iso(ts),
        baseline_id=baseline["id"],
        baseline_version=baseline["version"],
        peak_z=peak,
        last_z=latest_z,
        details_json=dumps(details),
        explanation=deviation_explanation(mode, event, baseline["version"]),
        is_open=1,
        is_demo=int(ctx.is_demo),
        source=ctx.source,
    )


def normalize_deviation(conn, machine_id: str, mode: str, ts: float) -> None:
    """8 ardışık geçerli pencerede z < 2 → 'Ölçümler normale döndü'. İnceleme kaydına dokunmaz."""
    rows = conn.execute(
        "SELECT id, details_json FROM alerts WHERE machine_id = ? AND kind = 'deviation' AND mode = ? AND is_open = 1",
        (machine_id, mode),
    ).fetchall()
    for row in rows:
        details = loads(row["details_json"], {})
        details["normalized_at"] = to_iso(ts)
        conn.execute(
            """UPDATE alerts SET measurement_status = 'normalized', unevaluable_reason = NULL, ended_at = ?,
                   updated_at = ?, is_open = 0, details_json = ?
               WHERE id = ?""",
            (to_iso(ts), to_iso(ts), dumps(details), row["id"]),
        )


def mark_unevaluable(conn, machine_id: str, ts: float, reason: str) -> None:
    """Veri sorunu, mod değişimi veya durma: açık sapma uyarısı 'değerlendirilemiyor' olur (kapanmaz)."""
    conn.execute(
        """UPDATE alerts SET measurement_status = 'unevaluable', unevaluable_reason = ?, updated_at = ?
           WHERE machine_id = ? AND kind = 'deviation' AND is_open = 1 AND measurement_status = 'active'""",
        (UNEVALUABLE_REASONS.get(reason, reason), to_iso(ts), machine_id),
    )


def supersede_for_new_baseline(conn, machine_id: str, mode: str, new_version: int, ts: float) -> None:
    """Yeni referans oluşturulunca eski referansa bağlı açık uyarılar güncellenmeyi bırakır.
    Uyarının bağlı olduğu referans sürümü korunur."""
    conn.execute(
        """UPDATE alerts SET measurement_status = CASE WHEN measurement_status = 'active' THEN 'unevaluable'
                                                       ELSE measurement_status END,
               unevaluable_reason = ?, is_open = 0, updated_at = ?
           WHERE machine_id = ? AND kind = 'deviation' AND mode = ? AND is_open = 1""",
        (
            f"Yeni referans (v{new_version}) oluşturuldu; bu uyarı önceki referans sürümüne göre değerlendirildi "
            "ve artık güncellenmiyor.",
            to_iso(ts),
            machine_id,
            mode,
        ),
    )


# ---------------------------------------------------------------------------
# Veri kalitesi uyarıları
# ---------------------------------------------------------------------------
def dq_upsert(
    conn,
    machine: dict,
    dq_type: str,
    ts: float,
    ctx: AlertContext,
    *,
    mode: str | None = None,
    flags: list[str] | None = None,
    started_at: float | None = None,
    extra: dict | None = None,
) -> int:
    existing = _find_open(conn, machine["id"], "data_quality", dq_type=dq_type)
    if existing:
        details = loads(existing["details_json"], {})
    else:
        details = {"count": 0, "duplicates": 0, "out_of_order": 0}
    details["count"] = int(details.get("count", 0)) + 1
    details["last_ts"] = ts
    if flags is not None:
        details["last_flags"] = flags
    for key, value in (extra or {}).items():
        if key in ("duplicates", "out_of_order"):
            details[key] = int(details.get(key, 0)) + int(value)
        else:
            details[key] = value
    explanation = dq_explanation(dq_type, details)
    if existing:
        conn.execute(
            "UPDATE alerts SET updated_at = ?, details_json = ?, explanation = ? WHERE id = ?",
            (to_iso(ts), dumps(details), explanation, existing["id"]),
        )
        return int(existing["id"])
    return _insert(
        conn,
        machine_id=machine["id"],
        mode=mode,
        kind="data_quality",
        dq_type=dq_type,
        level="data",
        measurement_status="active",
        review_status="new",
        started_at=to_iso(started_at if started_at is not None else ts),
        updated_at=to_iso(ts),
        details_json=dumps(details),
        explanation=explanation,
        is_open=1,
        is_demo=int(ctx.is_demo),
        source=ctx.source,
    )


def dq_close(conn, machine_id: str, dq_type: str, ts: float) -> bool:
    existing = _find_open(conn, machine_id, "data_quality", dq_type=dq_type)
    if not existing:
        return False
    details = loads(existing["details_json"], {})
    details["resolved_at"] = to_iso(ts)
    conn.execute(
        """UPDATE alerts SET measurement_status = 'normalized', ended_at = ?, updated_at = ?, is_open = 0,
               details_json = ?
           WHERE id = ?""",
        (to_iso(ts), to_iso(ts), dumps(details), existing["id"]),
    )
    return True


def open_data_gap(conn, machine: dict, last_ts: float, now: float, ctx: AlertContext) -> bool:
    """Canlı kaynakta 3 beklenen aralık boyunca kayıt gelmedi → 'Veri gelmiyor'."""
    if _find_open(conn, machine["id"], "data_quality", dq_type="data_gap"):
        return False
    dq_upsert(conn, machine, "data_gap", now, ctx, started_at=last_ts, extra={"last_record_ts": last_ts})
    mark_unevaluable(conn, machine["id"], now, "no_data")
    return True


def handle_gap(conn, machine: dict, from_ts: float, to_ts: float, ctx: AlertContext) -> None:
    """Kayıtlar yeniden geldi: açık 'Veri gelmiyor' uyarısını kapat ya da (hızlı ileri sarmada)
    kesintiyi kapanmış bir veri sorunu olarak kaydet. CSV geçmişinde uyarı üretilmez."""
    if dq_close(conn, machine["id"], "data_gap", to_ts):
        return
    if not ctx.live:
        return
    details = {"count": 1, "last_record_ts": from_ts, "resumed_ts": to_iso(to_ts), "duration_s": round(to_ts - from_ts, 1)}
    _insert(
        conn,
        machine_id=machine["id"],
        kind="data_quality",
        dq_type="data_gap",
        level="data",
        measurement_status="normalized",
        review_status="new",
        started_at=to_iso(from_ts),
        updated_at=to_iso(to_ts),
        ended_at=to_iso(to_ts),
        details_json=dumps(details),
        explanation=dq_explanation("data_gap", details)
        + f" Kesinti yaklaşık {round(to_ts - from_ts)} sn sürdü; akış yeniden başladı.",
        is_open=0,
        is_demo=int(ctx.is_demo),
        source=ctx.source,
    )


# ---------------------------------------------------------------------------
# Analiz olaylarını uyarılara çevir
# ---------------------------------------------------------------------------
def apply_events(
    conn,
    machine: dict,
    mode: str | None,
    ts: float,
    result: StepResult,
    baseline: dict | None,
    ctx: AlertContext,
    cfg: AnalysisConfig = ANALYSIS,
) -> None:
    machine_id = machine["id"]
    for event in result.events:
        kind = event["type"]
        if kind == "deviation" and baseline is not None and mode is not None:
            upsert_deviation(conn, machine, mode, ts, event, baseline, ctx)
        elif kind == "normal_streak" and mode is not None:
            normalize_deviation(conn, machine_id, mode, ts)
        elif kind == "interrupt":
            mark_unevaluable(conn, machine_id, ts, event["reason"])
        elif kind == "invalid":
            dq_upsert(conn, machine, "invalid", ts, ctx, mode=mode, flags=event["flags"])
        elif kind == "valid":
            if event["good_streak"] == cfg.dq_recovery:
                dq_close(conn, machine_id, "invalid", ts)
            if event["seq_clean"] == cfg.dq_recovery:
                dq_close(conn, machine_id, "sequence", ts)
        elif kind == "frozen_start":
            dq_upsert(conn, machine, "frozen", ts, ctx, mode=mode, started_at=event["since"], extra={"count": event["count"]})
        elif kind == "frozen_end":
            dq_close(conn, machine_id, "frozen", ts)
        elif kind == "gap":
            handle_gap(conn, machine, event["from_ts"], event["to_ts"], ctx)
        elif kind == "sequence":
            dq_upsert(conn, machine, "sequence", ts, ctx, mode=mode, extra={"out_of_order": 1})


# ---------------------------------------------------------------------------
# Sorgular, inceleme ve notlar
# ---------------------------------------------------------------------------
def list_alerts(conn, filters: dict, limit: int = 500) -> list[dict]:
    sql = "SELECT a.*, m.name AS machine_name FROM alerts a JOIN machines m ON m.id = a.machine_id WHERE 1 = 1"
    params: list[Any] = []
    for key, column in (
        ("machine_id", "a.machine_id"),
        ("kind", "a.kind"),
        ("level", "a.level"),
        ("review_status", "a.review_status"),
        ("measurement_status", "a.measurement_status"),
        ("mode", "a.mode"),
    ):
        value = filters.get(key)
        if value:
            sql += f" AND {column} = ?"
            params.append(value)
    # Zaman filtresi: olay aralığı seçilen aralıkla kesişiyorsa göster
    if filters.get("start"):
        sql += " AND COALESCE(a.ended_at, a.updated_at) >= ?"
        params.append(to_iso(from_iso(filters["start"])))
    if filters.get("end"):
        sql += " AND a.started_at <= ?"
        params.append(to_iso(from_iso(filters["end"])))
    sql += " ORDER BY a.id DESC LIMIT ?"
    params.append(limit)
    return [alert_from_row(r) for r in conn.execute(sql, params).fetchall()]


def get_alert(conn, alert_id: int) -> dict | None:
    row = conn.execute(
        "SELECT a.*, m.name AS machine_name FROM alerts a JOIN machines m ON m.id = a.machine_id WHERE a.id = ?",
        (alert_id,),
    ).fetchone()
    return alert_from_row(row) if row else None


def update_review(conn, alert_id: int, review_status: str | None, assessment: str | None, clear_assessment: bool = False) -> dict:
    """İnceleme durumu ve değerlendirme. Ölçüm durumu ve referans değişmez."""
    alert = get_alert(conn, alert_id)
    if alert is None:
        raise LookupError("Uyarı bulunamadı.")
    if review_status is not None and review_status not in REVIEW_STATUSES:
        raise AlertError("İnceleme durumu new, in_review veya closed olmalı.")
    if assessment is not None and assessment not in ASSESSMENTS:
        raise AlertError("Değerlendirme normal_change, measurement_issue, maintenance_found veya uncertain olmalı.")
    new_review = review_status or alert["review_status"]
    new_assessment = None if clear_assessment else (assessment or alert["assessment"])
    conn.execute(
        "UPDATE alerts SET review_status = ?, assessment = ?, reviewed_at = ? WHERE id = ?",
        (new_review, new_assessment, to_iso(now_epoch()), alert_id),
    )
    return get_alert(conn, alert_id)  # type: ignore[return-value]


def add_note(conn, payload: dict) -> dict:
    machine_id = str(payload.get("machine_id") or "")
    if not conn.execute("SELECT 1 FROM machines WHERE id = ?", (machine_id,)).fetchone():
        raise LookupError("Makine bulunamadı.")
    text = str(payload.get("text") or "").strip()
    if not text:
        raise AlertError("Not metni boş olamaz.")
    note_type = payload.get("note_type") or "inspection"
    if note_type not in NOTE_TYPES:
        raise AlertError("Not türü inspection, maintenance veya general olmalı.")
    assessment = payload.get("assessment") or None
    if assessment is not None and assessment not in ASSESSMENTS:
        raise AlertError("Değerlendirme değeri geçersiz.")
    alert_id = payload.get("alert_id")
    snapshot = None
    if alert_id is not None:
        alert = get_alert(conn, int(alert_id))
        if alert is None or alert["machine_id"] != machine_id:
            raise AlertError("Not eklenecek uyarı bu makineye ait değil.")
        snapshot = f"Uyarı #{alert['id']} ({alert['kind']}, başlangıç {alert['started_at']})"
    cursor = conn.execute(
        """INSERT INTO review_notes (machine_id, alert_id, created_at, author, note_type, text, assessment, alert_snapshot)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            machine_id, alert_id, to_iso(now_epoch()), str(payload.get("author") or "").strip()[:80],
            note_type, text[:4000], assessment, snapshot,
        ),
    )
    row = conn.execute("SELECT * FROM review_notes WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return dict(row)


def list_notes(conn, machine_id: str | None = None, alert_id: int | None = None) -> list[dict]:
    sql = "SELECT * FROM review_notes WHERE 1 = 1"
    params: list[Any] = []
    if machine_id:
        sql += " AND machine_id = ?"
        params.append(machine_id)
    if alert_id is not None:
        sql += " AND alert_id = ?"
        params.append(alert_id)
    return [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", params).fetchall()]
