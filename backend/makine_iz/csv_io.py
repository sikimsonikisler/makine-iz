"""CSV aktarımı (önce doğrulama, sonra tek işlemde aktarma) ve dışa aktarım.

Aktarım kuralları:
- Hata içeren dosyada HİÇBİR satır aktarılmaz (kısmi aktarım yok).
- Hatalar satır numarası ve alan adıyla bildirilir (satır 1 = başlık satırı).
- Eksik ölçüm, negatif değer, aralık dışı değer: hata değil UYARI; satır aktarılır ve kayıt
  "geçersiz" işaretlenir (değer sıfıra çevrilmez).
- Yinelenen kayıt politikası: aynı makine + aynı zaman damgası → ilk kayıt korunur,
  sonrakiler (dosya içinde veya veritabanında zaten varsa) atlanır ve özette belirtilir.
- Satırlar her makine için zaman sırasına göre işlenir. Mevcut son kayıttan eski satırlar
  "sırası bozuk" işaretlenir ve süreklilik hesabına alınmaz.
- Aktarılan satırlar simülasyon ve sensör verisiyle AYNI analiz yolundan geçer.
"""
from __future__ import annotations

import csv
import io
import math
import sqlite3
import uuid
from typing import Any

from .config import FEATURE_LABELS, FEATURES, MODES, NON_NEGATIVE
from .db import dumps, loads
from .machines import ID_PATTERN, create_machine, default_modes, get_machine
from .pipeline import IngestOptions, ingest
from .timeutil import istanbul_text, now_epoch, parse_timestamp, to_iso, from_iso

REQUIRED_COLUMNS = ["machine_id", "timestamp", "operating_mode", "vibration_rms_g", "temperature_c", "power_kw", "rpm"]
OPTIONAL_COLUMNS = ["source", "quality_flags"]
MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 200_000
MAX_LISTED = 300
PREVIEW_ROWS = 20


class CsvValidationError(ValueError):
    def __init__(self, report: dict):
        super().__init__("CSV dosyasında hata var; aktarım yapılmadı.")
        self.report = report


def _issue(row: int | None, field: str | None, message: str) -> dict:
    return {"row": row, "field": field, "message": message}


def _detect_delimiter(header_line: str) -> str:
    counts = {d: header_line.count(d) for d in (",", ";", "\t")}
    return max(counts, key=counts.get) if max(counts.values()) > 0 else ","


def validate_csv(conn: sqlite3.Connection, content: str, *, create_missing_machines: bool = False) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    infos: list[str] = []
    counters = {
        "data_rows": 0, "blank_rows": 0, "missing_values": 0, "invalid_values": 0,
        "duplicates_in_file": 0, "duplicates_existing": 0, "older_than_existing": 0, "timezone_assumed": 0,
        "source_overridden": 0,
    }

    def report(rows: list[dict]) -> dict:
        importable = [r for r in rows if not r.get("skip")]
        machines = {}
        for r in importable:
            info = machines.setdefault(r["machine_id"], {"machine_id": r["machine_id"], "rows": 0,
                                                          "first_ts": r["ts_iso"], "last_ts": r["ts_iso"]})
            info["rows"] += 1
            info["first_ts"] = min(info["first_ts"], r["ts_iso"])
            info["last_ts"] = max(info["last_ts"], r["ts_iso"])
        for mid, info in machines.items():
            existing = get_machine(conn, mid)
            info["name"] = existing["name"] if existing else None
            info["new"] = existing is None
        return {
            "ok": not errors,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors[:MAX_LISTED],
            "warnings": warnings[:MAX_LISTED],
            "infos": infos,
            "summary": {
                **counters,
                "valid_rows": len(rows),
                "importable_rows": len(importable),
                "machines": list(machines.values()),
            },
            "preview": [
                {
                    "row": r["line"], "machine_id": r["machine_id"], "timestamp": r["ts_iso"],
                    "operating_mode": r["mode"], **{f: r["values"][f] for f in FEATURES},
                    "skip": r.get("skip"),
                }
                for r in rows[:PREVIEW_ROWS]
            ],
            "_rows": importable,
        }

    if len(content.encode("utf-8")) > MAX_BYTES:
        errors.append(_issue(None, None, "Dosya 20 MB sınırını aşıyor."))
        return report([])
    content = content.lstrip("﻿")
    if not content.strip():
        errors.append(_issue(None, None, "Dosya boş."))
        return report([])

    first_line = content.splitlines()[0]
    delimiter = _detect_delimiter(first_line)
    decimal_comma = delimiter == ";"
    infos.append(
        f"Ayraç: '{'TAB' if delimiter == chr(9) else delimiter}'"
        + (" (ondalık virgül kabul edilir)" if decimal_comma else "")
    )
    reader = csv.reader(io.StringIO(content), delimiter=delimiter)
    header = [h.strip().lower() for h in next(reader)]

    seen_columns = set()
    for column in header:
        if column in seen_columns:
            errors.append(_issue(1, column, f"Sütun adı iki kez yazılmış: '{column}'."))
        seen_columns.add(column)
    for column in REQUIRED_COLUMNS:
        if column not in header:
            errors.append(_issue(1, column, f"Zorunlu sütun eksik: '{column}'."))
    for column in header:
        if column not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS:
            warnings.append(_issue(1, column, f"Bilinmeyen sütun '{column}' yok sayılacak."))
    if errors:
        return report([])
    if "quality_flags" in header:
        infos.append("quality_flags sütunu bilgi amaçlı saklanır; kalite işaretlerini uygulama kendisi hesaplar.")

    machine_cache: dict[str, dict | None] = {}
    new_machine_template = {"modes": default_modes(), "ranges": None}
    rows: list[dict] = []
    for line_no, cells in enumerate(reader, start=2):
        if not any(cell.strip() for cell in cells):
            counters["blank_rows"] += 1
            continue
        counters["data_rows"] += 1
        if counters["data_rows"] > MAX_ROWS:
            errors.append(_issue(line_no, None, f"Dosya en fazla {MAX_ROWS} veri satırı içerebilir."))
            break
        if len(cells) != len(header):
            errors.append(_issue(line_no, None, f"Satırda {len(cells)} sütun var; başlıkta {len(header)} sütun var."))
            continue
        record = {h: c.strip() for h, c in zip(header, cells)}

        machine_id = record["machine_id"]
        if not machine_id:
            errors.append(_issue(line_no, "machine_id", "Makine kimliği boş."))
            continue
        if machine_id not in machine_cache:
            machine_cache[machine_id] = get_machine(conn, machine_id)
        machine = machine_cache[machine_id]
        row_ok = True
        if machine is None:
            # Satırın geri kalanı yine de kontrol edilir; böylece bütün hatalar bir seferde görünür.
            machine = {"modes": new_machine_template["modes"], "ranges": None}
            if create_missing_machines and not ID_PATTERN.match(machine_id):
                errors.append(_issue(line_no, "machine_id",
                                     f"'{machine_id}' geçerli bir makine kimliği değil (küçük harf, rakam, '-' ve '_')."))
                row_ok = False
            elif not create_missing_machines:
                errors.append(_issue(line_no, "machine_id",
                                     f"Bilinmeyen makine kimliği: '{machine_id}'. Önce makineyi ekleyin veya "
                                     "'Bilinmeyen makineleri yeni makine olarak ekle' seçeneğini işaretleyin."))
                row_ok = False

        ts, ts_error, assumed = parse_timestamp(record["timestamp"])
        if ts_error:
            errors.append(_issue(line_no, "timestamp", ts_error + "."))
            row_ok = False
        elif assumed:
            counters["timezone_assumed"] += 1

        mode = record["operating_mode"].lower()
        if mode not in MODES:
            errors.append(_issue(line_no, "operating_mode",
                                 f"Geçersiz çalışma modu: '{record['operating_mode']}'. stopped, idle veya loaded olmalı."))
            row_ok = False
        elif not machine["modes"].get(mode, {}).get("enabled", False):
            warnings.append(_issue(line_no, "operating_mode",
                                   "Bu mod makine için tanımlı değil; kayıt geçersiz işaretlenecek."))

        values: dict[str, Any] = {}
        for feature in FEATURES:
            text = record[feature]
            if decimal_comma:
                text = text.replace(",", ".")
            if text == "":
                counters["missing_values"] += 1
                warnings.append(_issue(line_no, feature,
                                       f"Eksik ölçüm ({FEATURE_LABELS[feature]}): satır aktarılacak, 'eksik ölçüm' olarak işaretlenecek."))
                values[feature] = None
                continue
            try:
                number = float(text)
                if not math.isfinite(number):
                    raise ValueError
            except ValueError:
                errors.append(_issue(line_no, feature, f"Sayısal olmayan değer: '{record[feature]}'."))
                row_ok = False
                continue
            if feature in NON_NEGATIVE and number < 0:
                counters["invalid_values"] += 1
                warnings.append(_issue(line_no, feature,
                                       f"Negatif değer ({number:g}): geçersiz olarak işaretlenecek, sıfıra çevrilmeyecek."))
            elif machine.get("ranges"):
                low, high = machine["ranges"][feature]
                if not (low <= number <= high):
                    counters["invalid_values"] += 1
                    warnings.append(_issue(line_no, feature,
                                           f"Beklenen aralığın ({low:g}–{high:g}) dışında: geçersiz olarak işaretlenecek."))
            values[feature] = number
        if not row_ok:
            continue
        if record.get("source") and record["source"].lower() != "csv":
            counters["source_overridden"] += 1
        rows.append({
            "line": line_no, "machine_id": machine_id, "ts": ts, "ts_iso": to_iso(ts), "mode": mode,
            "values": values, "quality_flags": record.get("quality_flags", ""),
        })

    if counters["source_overridden"]:
        infos.append(f"{counters['source_overridden']} satırda 'source' farklı; aktarılan kayıtlar 'csv' kaynağı olarak saklanır.")
    if counters["timezone_assumed"]:
        infos.append(f"{counters['timezone_assumed']} satırda saat dilimi yok; Europe/Istanbul yerel saati kabul edildi.")

    # Yinelenen kayıtlar (dosya içinde): ilk satır korunur
    first_seen: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["machine_id"], row["ts_iso"])
        if key in first_seen:
            original = first_seen[key]
            same = original["mode"] == row["mode"] and original["values"] == row["values"]
            row["skip"] = "duplicate_in_file"
            counters["duplicates_in_file"] += 1
            warnings.append(_issue(row["line"], "timestamp",
                                   f"Yinelenen kayıt: satır {original['line']} ile aynı makine ve zaman damgası"
                                   + (" (değerler aynı)" if same else " (değerler farklı)")
                                   + "; ilk satır korunacak, bu satır atlanacak."))
        else:
            first_seen[key] = row

    # Veritabanıyla karşılaştırma: zaten var olan kayıtlar ve sıra
    by_machine: dict[str, list[dict]] = {}
    for row in rows:
        if not row.get("skip"):
            by_machine.setdefault(row["machine_id"], []).append(row)
    for machine_id, items in by_machine.items():
        if [r["ts"] for r in items] != sorted(r["ts"] for r in items):
            infos.append(f"'{machine_id}' satırları dosyada zaman sırasında değil; aktarımda zaman sırasına göre işlenecek.")
        if machine_cache.get(machine_id) is None:
            continue
        first, last = min(r["ts_iso"] for r in items), max(r["ts_iso"] for r in items)
        existing = {
            r["ts"] for r in conn.execute(
                "SELECT ts FROM telemetry WHERE machine_id = ? AND ts >= ? AND ts <= ?", (machine_id, first, last)
            )
        }
        latest_row = conn.execute("SELECT MAX(ts) FROM telemetry WHERE machine_id = ?", (machine_id,)).fetchone()[0]
        for row in items:
            if row["ts_iso"] in existing:
                row["skip"] = "duplicate_existing"
                counters["duplicates_existing"] += 1
                warnings.append(_issue(row["line"], "timestamp",
                                       "Bu makine için aynı zaman damgalı kayıt zaten var; satır atlanacak."))
            elif latest_row and row["ts_iso"] < latest_row:
                counters["older_than_existing"] += 1
                warnings.append(_issue(row["line"], "timestamp",
                                       "Makinenin mevcut son kaydından eski: 'sırası bozuk' işaretlenecek ve süreklilik "
                                       "hesabına alınmayacak."))
    return report(rows)


def public_report(report: dict) -> dict:
    return {k: v for k, v in report.items() if not k.startswith("_")}


def import_csv(conn: sqlite3.Connection, content: str, filename: str, *, create_missing_machines: bool = False) -> dict:
    """Doğrular; hata yoksa bütün satırları tek işlemde aktarır. Hata varsa hiçbir şey yazılmaz."""
    report = validate_csv(conn, content, create_missing_machines=create_missing_machines)
    if not report["ok"]:
        raise CsvValidationError(public_report(report))
    import_id = uuid.uuid4().hex[:12]
    created = []
    for info in report["summary"]["machines"]:
        if info["new"]:
            create_machine(conn, {
                "id": info["machine_id"], "name": info["machine_id"], "machine_type": "Belirtilmedi",
                "data_source": "csv", "description": f"CSV aktarımıyla oluşturuldu ({filename}).",
            })
            created.append(info["machine_id"])
    records = [
        {
            "machine_id": row["machine_id"], "timestamp": row["ts"], "operating_mode": row["mode"],
            **{f: row["values"][f] for f in FEATURES},
            "quality_flags": row["quality_flags"] or None,
        }
        for row in sorted(report["_rows"], key=lambda r: (r["machine_id"], r["ts"]))
    ]
    results = ingest(conn, records, IngestOptions(source="csv", is_demo=False, import_id=import_id))
    statuses: dict[str, int] = {}
    for result in results:
        statuses[result.status] = statuses.get(result.status, 0) + 1
    deviation_alerts = conn.execute(
        """SELECT COUNT(*) FROM alerts a WHERE a.kind = 'deviation' AND a.source = 'csv' AND a.machine_id IN
           (SELECT DISTINCT machine_id FROM telemetry WHERE import_id = ?)""",
        (import_id,),
    ).fetchone()[0]
    summary = {
        "import_id": import_id,
        "filename": filename,
        "imported_rows": sum(1 for r in results if r.stored),
        "skipped_duplicates": report["summary"]["duplicates_in_file"] + report["summary"]["duplicates_existing"],
        "flagged_rows": sum(1 for r in results if r.stored and r.status in ("invalid", "out_of_order", "frozen_suspect")),
        "analysis_statuses": statuses,
        "created_machines": created,
        "machines": report["summary"]["machines"],
        "deviation_alerts_total_for_machines": deviation_alerts,
        "warning_count": report["warning_count"],
        "duplicate_policy": "Aynı makine + aynı zaman damgası: ilk kayıt korunur, sonrakiler atlanır.",
    }
    conn.execute(
        "INSERT INTO imports (id, filename, created_at, summary_json) VALUES (?, ?, ?, ?)",
        (import_id, filename[:200], to_iso(now_epoch()), dumps(summary)),
    )
    return summary


# ---------------------------------------------------------------------------
# Dışa aktarım
# ---------------------------------------------------------------------------
def _csv_text(header: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    buffer.write("﻿")  # Excel'de Türkçe karakterler doğru görünsün
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def export_telemetry(conn: sqlite3.Connection, machine_id: str | None, start_iso: str | None, end_iso: str | None) -> str:
    sql = """SELECT t.*, b.version AS baseline_version FROM telemetry t
             LEFT JOIN baselines b ON b.id = t.baseline_id WHERE 1 = 1"""
    params: list = []
    if machine_id:
        sql += " AND t.machine_id = ?"
        params.append(machine_id)
    if start_iso:
        sql += " AND t.ts >= ?"
        params.append(start_iso)
    if end_iso:
        sql += " AND t.ts <= ?"
        params.append(end_iso)
    sql += " ORDER BY t.machine_id, t.ts"
    header = ["machine_id", "timestamp", "timestamp_istanbul", "operating_mode", *FEATURES, "source",
              "quality_flags", "analysis_status", "z_max", "deviation_score", "baseline_version"]
    rows = []
    for row in conn.execute(sql, params):
        z_max = row["z_max"]
        rows.append([
            row["machine_id"], row["ts"], istanbul_text(from_iso(row["ts"])), row["operating_mode"] or "",
            *["" if row[f] is None else row[f] for f in FEATURES], row["source"],
            "|".join(loads(row["quality_flags"], [])), row["analysis_status"] or "",
            "" if z_max is None else round(z_max, 3),
            "" if z_max is None else round(min(100.0, 10 * z_max), 1),
            row["baseline_version"] or "",
        ])
    return _csv_text(header, rows)


def export_alerts(alert_rows: list[dict]) -> str:
    header = ["id", "machine_id", "machine_name", "kind", "dq_type", "level", "mode", "measurement_status",
              "review_status", "assessment", "started_at", "updated_at", "ended_at", "baseline_version", "peak_z",
              "top_features", "explanation", "unevaluable_reason"]
    rows = []
    for alert in alert_rows:
        top = alert["details"].get("latest", {}).get("top", []) if alert["kind"] == "deviation" else []
        rows.append([
            alert["id"], alert["machine_id"], alert.get("machine_name", ""), alert["kind"], alert["dq_type"] or "",
            alert["level"], alert["mode"] or "", alert["measurement_status"], alert["review_status"],
            alert["assessment"] or "", alert["started_at"], alert["updated_at"], alert["ended_at"] or "",
            alert["baseline_version"] or "", "" if alert["peak_z"] is None else round(alert["peak_z"], 2),
            "|".join(top), alert["explanation"], alert["unevaluable_reason"] or "",
        ])
    return _csv_text(header, rows)
