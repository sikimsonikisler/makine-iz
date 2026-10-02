"""Grafik ve sorgu verisi.

- Eksik veride grafik KESİLİR: kesinti noktalarına boş (null) değer eklenir, çizgi birleştirilmez.
- Çok sayıda noktada yalnızca GÖRÜNTÜLEME için örnek azaltılır (zaman kovası ortalaması).
  Analiz her zaman tam veriyi kullanır.
"""
from __future__ import annotations

import math
import sqlite3

import numpy as np

from .config import ANALYSIS, FEATURES
from .db import loads
from .timeutil import from_iso, to_iso
from .validation import field_is_invalid

STATUS_RANK = {
    None: 0, "no_baseline": 1, "stopped": 1, "normal": 2, "transition": 3, "out_of_order": 4,
    "candidate": 5, "strong_candidate": 6, "invalid": 7, "frozen_suspect": 7,
}


def telemetry_range(conn: sqlite3.Connection, machine_id: str) -> dict:
    row = conn.execute(
        "SELECT MIN(ts) AS first_ts, MAX(ts) AS last_ts, COUNT(*) AS count FROM telemetry WHERE machine_id = ?",
        (machine_id,),
    ).fetchone()
    return {"first_ts": row["first_ts"], "last_ts": row["last_ts"], "count": row["count"]}


def _point_from_row(row: sqlite3.Row) -> dict:
    flags = loads(row["quality_flags"], [])
    point = {"t": int(round(from_iso(row["ts"]) * 1000)), "mode": row["operating_mode"]}
    for feature in FEATURES:
        value = row[feature]
        point[feature] = None if (value is None or field_is_invalid(flags, feature)) else value
    z_max = row["z_max"]
    point["zf"] = loads(row["z_json"], None)  # özellik başına z (grafikte hangi ölçümün değiştiğini işaretlemek için)
    point["z"] = z_max
    point["score"] = min(100.0, 10.0 * z_max) if z_max is not None else None
    point["status"] = row["analysis_status"]
    point["flags"] = flags
    return point


def _gap_point(t_ms: int) -> dict:
    return {"t": t_ms, "mode": None, **{f: None for f in FEATURES}, "zf": None, "z": None, "score": None, "status": "gap",
            "flags": [], "gap": True}


def query_series(conn: sqlite3.Connection, machine: dict, start_iso: str, end_iso: str, max_points: int = 1500) -> dict:
    rows = conn.execute(
        f"""SELECT ts, operating_mode, {", ".join(FEATURES)}, quality_flags, analysis_status, z_max, z_json
            FROM telemetry WHERE machine_id = ? AND ts >= ? AND ts <= ? ORDER BY ts""",
        (machine["id"], start_iso, end_iso),
    ).fetchall()
    total = len(rows)
    gap_ms = ANALYSIS.gap_factor * machine["expected_interval_s"] * 1000
    points: list[dict] = []
    if total <= max_points:
        previous = None
        for row in rows:
            point = _point_from_row(row)
            if previous is not None and point["t"] - previous > gap_ms:
                points.append(_gap_point(previous + 1))
            points.append(point)
            previous = point["t"]
        return {"total": total, "downsampled": False, "bucket_s": None, "points": points,
                "start": start_iso, "end": end_iso}

    start_ms = from_iso(start_iso) * 1000
    end_ms = from_iso(end_iso) * 1000
    interval_ms = machine["expected_interval_s"] * 1000
    bucket_ms = max(interval_ms, math.ceil((end_ms - start_ms) / max_points / interval_ms) * interval_ms)
    parsed = [_point_from_row(row) for row in rows]
    times = np.array([p["t"] for p in parsed], dtype=float)
    indexes = ((times - start_ms) // bucket_ms).astype(int)
    previous_bucket = None
    i = 0
    while i < total:
        bucket = indexes[i]
        j = i
        while j < total and indexes[j] == bucket:
            j += 1
        chunk = parsed[i:j]
        if previous_bucket is not None and bucket - previous_bucket > 1 and \
                (bucket - previous_bucket - 1) * bucket_ms > gap_ms:
            points.append(_gap_point(int(start_ms + (previous_bucket + 1) * bucket_ms)))
        point = {"t": int(start_ms + bucket * bucket_ms + bucket_ms / 2), "n": len(chunk)}
        point["mode"] = chunk[-1]["mode"]
        for feature in FEATURES:
            values = [p[feature] for p in chunk if p[feature] is not None]
            point[feature] = round(float(np.mean(values)), 4) if values else None
            point[f"{feature}_max"] = round(float(np.max(values)), 4) if values else None
        per_feature = {f: [p["zf"][f] for p in chunk if p["zf"]] for f in FEATURES}
        point["zf"] = {f: max(v) for f, v in per_feature.items()} if per_feature[FEATURES[0]] else None
        z_values = [p["z"] for p in chunk if p["z"] is not None]
        point["z"] = max(z_values) if z_values else None
        point["score"] = min(100.0, 10.0 * point["z"]) if point["z"] is not None else None
        point["status"] = max((p["status"] for p in chunk), key=lambda s: STATUS_RANK.get(s, 0))
        flags = sorted({f for p in chunk for f in p["flags"]})
        point["flags"] = flags
        points.append(point)
        previous_bucket = bucket
        i = j
    return {"total": total, "downsampled": True, "bucket_s": bucket_ms / 1000, "points": points,
            "start": start_iso, "end": end_iso}


def query_raw(conn: sqlite3.Connection, machine_id: str | None, start_iso: str | None, end_iso: str | None,
              limit: int = 1000, offset: int = 0) -> list[dict]:
    sql = "SELECT * FROM telemetry WHERE 1 = 1"
    params: list = []
    if machine_id:
        sql += " AND machine_id = ?"
        params.append(machine_id)
    if start_iso:
        sql += " AND ts >= ?"
        params.append(start_iso)
    if end_iso:
        sql += " AND ts <= ?"
        params.append(end_iso)
    sql += " ORDER BY machine_id, ts LIMIT ? OFFSET ?"
    params += [limit, offset]
    rows = []
    for row in conn.execute(sql, params).fetchall():
        item = dict(row)
        item["quality_flags"] = loads(item["quality_flags"], [])
        item["z"] = loads(item.pop("z_json"), None)
        item["raw"] = loads(item.pop("raw_json"), None)
        item["is_demo"] = bool(item["is_demo"])
        rows.append(item)
    return rows


def normalize_range(start: str | None, end: str | None) -> tuple[str | None, str | None]:
    """API'den gelen zamanları veritabanı biçimine çevirir (ValueError fırlatabilir)."""
    return (to_iso(from_iso(start)) if start else None, to_iso(from_iso(end)) if end else None)
