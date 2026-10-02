#!/usr/bin/env python3
"""Örnek CSV dosyalarını sabit tohumla üretir (samples/ klasörü).

  ornek_referans.csv → 'ornek-kompresor' için normal çalışma (referans oluşturmak için)
  ornek_izleme.csv   → ertesi gün; yük altında titreşim kademeli yükselir, bir eksik ölçüm ve bir
                        yinelenen satır içerir (uyarı ve veri kalitesi gösterimi için)
  ornek_hatali.csv   → bilerek hatalı satırlar (hata gösterimini denemek için; aktarılamaz)
  sablon.csv         → boş şablon ve birkaç örnek satır
"""
from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from makine_iz.config import FEATURES  # noqa: E402
from makine_iz.simulator import MachineSimulator, generate_records  # noqa: E402
from makine_iz.timeutil import ISTANBUL  # noqa: E402

OUT = ROOT / "samples"
HEADER = ["machine_id", "timestamp", "operating_mode", *FEATURES, "source"]
MACHINE = "ornek-kompresor"


def local(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=ISTANBUL).isoformat(timespec="seconds")


def rows_for(records):
    return [[r["machine_id"], local(r["timestamp"]), r["operating_mode"],
             *["" if r[f] is None else r[f] for f in FEATURES], "csv"] for r in records]


def write(name: str, rows) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        writer.writerows(rows)
    print(f"{name}: {len(rows)} satır")


def schedule(parts):
    changes, step = [], 1
    for mode, minutes in parts:
        changes.append([step, mode])
        step += minutes * 12
    return changes, step - 1


def main() -> None:
    OUT.mkdir(exist_ok=True)
    # 1) Referans: 28 Eylül 2026 06:00 (İstanbul)
    start = datetime(2026, 9, 28, 6, 0, tzinfo=ISTANBUL).timestamp()
    changes, steps = schedule([("stopped", 5), ("idle", 20), ("loaded", 50), ("idle", 10)])
    sim = MachineSimulator("compressor", 501, start, machine_id=MACHINE, start_mode="stopped", mode_changes=changes)
    write("ornek_referans.csv", rows_for(generate_records(sim, steps)))

    # 2) İzleme: 29 Eylül 2026 06:00 — yük altına geçtikten 35 dk sonra titreşim kademeli yükselir
    start = datetime(2026, 9, 29, 6, 0, tzinfo=ISTANBUL).timestamp()
    changes, steps = schedule([("idle", 10), ("loaded", 60)])
    sim = MachineSimulator("compressor", 502, start, machine_id=MACHINE, scenario="vibration_ramp",
                           start_mode="idle", mode_changes=changes, onset_s=45 * 60)
    records = generate_records(sim, steps)
    records[300]["temperature_c"] = None  # bir eksik ölçüm
    rows = rows_for(records)
    rows.insert(401, list(rows[400]))  # bir yinelenen satır
    write("ornek_izleme.csv", rows)

    # 3) Hatalı örnek
    base = rows_for(generate_records(MachineSimulator("compressor", 503, start + 86400, machine_id=MACHINE), 8))
    base[1][1] = "2026-02-30T10:00:00+03:00"  # olmayan tarih
    base[2][2] = "calisiyor"  # geçersiz mod
    base[3][3] = "abc"  # sayısal olmayan titreşim
    base[4][0] = ""  # makine kimliği yok
    base[5][5] = "-2.5"  # negatif güç (uyarı)
    base[6][4] = ""  # eksik sıcaklık (uyarı)
    write("ornek_hatali.csv", base)

    # 4) Şablon
    write("sablon.csv", [
        ["makine-1", "2026-10-01T08:00:00+03:00", "idle", 0.08, 41.5, 1.8, 1490, "csv"],
        ["makine-1", "2026-10-01T08:00:05+03:00", "idle", 0.081, 41.6, 1.79, 1489.5, "csv"],
        ["makine-1", "2026-10-01T08:00:10+03:00", "loaded", 0.15, 41.9, 10.9, 1456, "csv"],
    ])


if __name__ == "__main__":
    main()
