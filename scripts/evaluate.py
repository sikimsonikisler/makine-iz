#!/usr/bin/env python3
"""Makine İz — tekrar üretilebilir simülasyon değerlendirmesi.

Kullanım:
    .venv/bin/python scripts/evaluate.py --set calibration     # eşik belirleme (kalibrasyon) verisi
    .venv/bin/python scripts/evaluate.py --set evaluation      # değerlendirme verisi (rapor)

Veri kümeleri birbirinden ayrıdır (farklı tohumlar):
    referans   → her çalıştırma için etiketli normal geçmiş; referans profili YALNIZCA buradan
    kalibrasyon → yalnızca alt sınır (feature_floor) seçimi için incelenir
    değerlendirme → kalibrasyon sonrası ayarlar sabitlenince bir kez çalıştırılır

Analiz motoru, uygulamadaki ile AYNI yoldan (pipeline.ingest) çalışır. Senaryo adı ve
"değişim başlangıcı" yalnızca bu betikte, sonuçları puanlamak için kullanılır.

Sonuçlar SİMÜLASYONA aittir; gerçek makinede arıza tahmini başarısı olarak yorumlanamaz.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from makine_iz import baselines  # noqa: E402
from makine_iz.config import ANALYSIS, DEFAULT_FEATURE_FLOORS  # noqa: E402
from makine_iz.db import Database, loads  # noqa: E402
from makine_iz.machines import create_machine, default_modes, get_machine  # noqa: E402
from makine_iz.pipeline import IngestOptions, ingest  # noqa: E402
from makine_iz.simulation import SimulationManager  # noqa: E402
from makine_iz.simulator import SCENARIOS, MachineSimulator, generate_records  # noqa: E402
from makine_iz.timeutil import from_iso, to_iso  # noqa: E402

PROFILES = ["motor", "pump", "fan"]
INTERVAL = 5.0
T0 = datetime(2026, 1, 5, 6, 0, tzinfo=timezone.utc).timestamp()  # sabit başlangıç → tekrar üretilebilir
REFERENCE_SCHEDULE = [("stopped", 5), ("idle", 40), ("loaded", 45), ("idle", 10)]

SEED_SETS = {
    # referans_tabanı, çalıştırma_tabanı
    "calibration": {"reference": 11000, "runs": 20000},
    "evaluation": {"reference": 12000, "runs": 30000},
}

ONSET_S = 600.0  # her senaryo 10 dk normal başlar, sonra değişim uygulanır
DETECTION_WINDOW_S = 30 * 60  # değişimden sonra 30 dk içinde uyarı yoksa "kaçırıldı"
DEVIATION_SCENARIOS = {"vibration_ramp": None, "temperature_ramp": None, "power_vibration": None, "recovery": 480.0}
DATA_SCENARIOS = {"missing_values": 300.0, "dropout": 120.0, "freeze": 180.0}


def reference_history(conn, machine: dict, profile: str, seed: int, start: float) -> tuple[float, float]:
    steps_per_min = int(60 / INTERVAL)
    changes, step = [], 1
    for mode, minutes in REFERENCE_SCHEDULE:
        changes.append([step, mode])
        step += minutes * steps_per_min
    total = step - 1
    simulator = MachineSimulator(profile, seed, start, machine_id=machine["id"], scenario="normal",
                                 start_mode="stopped", mode_changes=changes)
    ingest(conn, generate_records(simulator, total), IngestOptions(source="simulation", segment="reference"))
    end = start + total * INTERVAL
    for mode in ("idle", "loaded"):
        baselines.create(conn, machine, mode, to_iso(start), to_iso(end), confirm_normal=True, note="değerlendirme referansı")
    return end, total


def run_case(db: Database, manager: SimulationManager, *, case_id: str, profile: str, scenario: str, start_mode: str,
             duration_s: float, reference_seed: int, run_seed: int, floors: dict) -> dict:
    with db.write() as conn:
        machine = create_machine(conn, {
            "id": case_id, "name": case_id, "machine_type": profile, "data_source": "simulation",
            "sim_profile": profile, "expected_interval_s": INTERVAL, "transition_s": 30.0,
            "modes": default_modes(), "floors": floors,
        })
        ref_end, ref_records = reference_history(conn, machine, profile, reference_seed, T0)
        machine = get_machine(conn, case_id)
        run_start = ref_end + 60.0  # kısa ara: sayaçlar sıfırlanır (uygulamadaki yeni çalıştırma gibi)
        simulator = MachineSimulator(profile, run_seed, run_start, machine_id=case_id, interval_s=INTERVAL,
                                     scenario=scenario, start_mode=start_mode, onset_s=ONSET_S)
        steps_per_chunk = int(60 / INTERVAL)
        total_steps = int(duration_s / INTERVAL)
        emitted = 0
        for chunk_start in range(0, total_steps, steps_per_chunk):
            records = generate_records(simulator, min(steps_per_chunk, total_steps - chunk_start))
            emitted += len(records)
            if records:
                ingest(conn, records, IngestOptions(source="simulation"))
            manager._check_stale(conn, machine, simulator.ts_at(simulator.step_index))  # canlı akış kontrolü
        alerts = [dict(r) for r in conn.execute("SELECT * FROM alerts WHERE machine_id = ? ORDER BY id", (case_id,))]
        rows = conn.execute(
            "SELECT ts, operating_mode, analysis_status, z_max FROM telemetry WHERE machine_id = ? AND segment IS NULL "
            "ORDER BY ts", (case_id,)
        ).fetchall()
    onset = run_start + simulator.onset_step * INTERVAL
    deviation = []
    for alert in alerts:
        if alert["kind"] != "deviation":
            continue
        details = loads(alert["details_json"], {})
        raised = details["initial"]["window_ts"][-1]
        deviation.append({
            "raised": raised, "started": from_iso(alert["started_at"]), "level": alert["level"],
            "status": alert["measurement_status"],
            "ended": from_iso(alert["ended_at"]) if alert["ended_at"] else None,
            "top": details["initial"]["top"],
        })
    dq = [{"type": a["dq_type"], "started": from_iso(a["started_at"]), "status": a["measurement_status"]}
          for a in alerts if a["kind"] == "data_quality"]
    evaluated = [r for r in rows if r["analysis_status"] in ("normal", "candidate", "strong_candidate")]
    return {
        "case": case_id, "profile": profile, "scenario": scenario, "start_mode": start_mode,
        "reference_seed": reference_seed, "run_seed": run_seed, "run_start": run_start, "onset": onset,
        "duration_s": duration_s, "records": emitted, "reference_records": ref_records,
        "deviation_alerts": deviation, "dq_alerts": dq,
        "evaluated_windows": len(evaluated),
        "candidate_windows": sum(1 for r in evaluated if r["z_max"] >= ANALYSIS.z_candidate),
        "transition_records": sum(1 for r in rows if r["analysis_status"] == "transition"),
        "z_values": [r["z_max"] for r in evaluated],
    }


def plan(replicates: int) -> list[dict]:
    cases = []
    for replicate in range(replicates):
        for p_index, profile in enumerate(PROFILES):
            common = {"profile": profile, "replicate": replicate, "p_index": p_index}
            for mode in ("idle", "loaded"):
                cases.append({**common, "scenario": "normal", "start_mode": mode, "duration_s": 4 * 3600})
            cases.append({**common, "scenario": "load_change", "start_mode": "idle", "duration_s": 2 * 3600})
            for scenario in DEVIATION_SCENARIOS:
                cases.append({**common, "scenario": scenario, "start_mode": "loaded", "duration_s": 60 * 60})
            cases.append({**common, "scenario": "spike", "start_mode": "loaded", "duration_s": 30 * 60})
            for scenario in DATA_SCENARIOS:
                cases.append({**common, "scenario": scenario, "start_mode": "loaded", "duration_s": 30 * 60})
    return cases


def summarize(results: list[dict]) -> dict:
    by = lambda name: [r for r in results if r["scenario"] == name]  # noqa: E731
    normal = by("normal")
    normal_hours = sum(r["duration_s"] for r in normal) / 3600
    normal_false = sum(len(r["deviation_alerts"]) for r in normal)
    all_z = [z for r in normal for z in r["z_values"]]
    load = by("load_change")
    transitions = sum(1 + int((r["duration_s"] - ONSET_S) // 600) for r in load)
    load_false = sum(len(r["deviation_alerts"]) for r in load)

    detection = {}
    missed_cases = []
    for scenario in DEVIATION_SCENARIOS:
        delays, missed, before = [], 0, 0
        for r in by(scenario):
            before += sum(1 for a in r["deviation_alerts"] if a["raised"] < r["onset"])
            hits = [a for a in r["deviation_alerts"] if r["onset"] <= a["raised"] <= r["onset"] + DETECTION_WINDOW_S]
            if hits:
                delays.append(hits[0]["raised"] - r["onset"])
            else:
                missed += 1
                missed_cases.append(r["case"])
        entry = {
            "runs": len(by(scenario)), "detected": len(delays), "missed": missed,
            "false_before_onset": before,
            "delay_s_median": statistics.median(delays) if delays else None,
            "delay_s_min": min(delays) if delays else None,
            "delay_s_max": max(delays) if delays else None,
        }
        if scenario == "recovery":
            normalized = []
            for r in by(scenario):
                effect_end = r["onset"] + DEVIATION_SCENARIOS["recovery"]
                for a in r["deviation_alerts"]:
                    if a["ended"] and a["raised"] <= effect_end + 60:
                        normalized.append(a["ended"] - effect_end)
            entry["normalized"] = len(normalized)
            entry["normalize_delay_s_median"] = statistics.median(normalized) if normalized else None
        detection[scenario] = entry

    spike = by("spike")
    spike_alerts = sum(1 for r in spike for a in r["deviation_alerts"] if abs(a["raised"] - r["onset"]) <= 300)

    data_issues = {}
    for scenario, effect_s in DATA_SCENARIOS.items():
        runs = by(scenario)
        expected_type = {"missing_values": "invalid", "dropout": "data_gap", "freeze": "frozen"}[scenario]
        misclassified = sum(
            1 for r in runs for a in r["deviation_alerts"] if r["onset"] <= a["raised"] <= r["onset"] + effect_s + 120
        )
        background = sum(len(r["deviation_alerts"]) for r in runs) - misclassified
        detected = sum(1 for r in runs if any(d["type"] == expected_type for d in r["dq_alerts"]))
        data_issues[scenario] = {
            "runs": len(runs), "dq_detected": detected, "expected_dq_type": expected_type,
            "deviation_during_issue": misclassified, "deviation_elsewhere": background,
        }

    z_sorted = sorted(all_z)
    pct = lambda q: z_sorted[min(len(z_sorted) - 1, int(q * len(z_sorted)))] if z_sorted else None  # noqa: E731
    return {
        "normal": {
            "runs": len(normal), "hours": normal_hours, "deviation_alerts": normal_false,
            "alerts_per_hour": normal_false / normal_hours if normal_hours else None,
            "evaluated_windows": len(all_z),
            "share_z_ge_3": sum(1 for z in all_z if z >= 3) / len(all_z) if all_z else None,
            "z_p50": pct(0.5), "z_p99": pct(0.99), "z_p999": pct(0.999),
            "by_profile": {
                p: sum(len(r["deviation_alerts"]) for r in normal if r["profile"] == p) for p in PROFILES
            },
        },
        "load_change": {"runs": len(load), "transitions": transitions, "deviation_alerts": load_false,
                        "hours": sum(r["duration_s"] for r in load) / 3600},
        "detection": detection,
        "missed_scenarios": len(missed_cases),
        "missed_cases": missed_cases,
        "spike": {"runs": len(spike), "deviation_alerts_near_spike": spike_alerts},
        "data_issues": data_issues,
        "records": {
            "scenario_records": sum(r["records"] for r in results),
            "reference_records": sum(r["reference_records"] for r in results),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", choices=sorted(SEED_SETS), required=True)
    parser.add_argument("--replicates", type=int, default=5)
    parser.add_argument("--floors", type=str, default=None, help="JSON: feature_floor değerlerini geçersiz kıl (yalnızca kalibrasyon)")
    parser.add_argument("--out", type=str, default=None, help="JSON çıktısının yolu")
    args = parser.parse_args()
    if args.floors and args.set == "evaluation":
        parser.error("Değerlendirme kümesinde alt sınırlar değiştirilemez; uygulama ayarları kullanılır.")
    floors = {**DEFAULT_FEATURE_FLOORS, **(json.loads(args.floors) if args.floors else {})}
    seeds = SEED_SETS[args.set]

    started = time.time()
    results = []
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "eval.db")
        manager = SimulationManager(db)
        cases = plan(args.replicates)
        for index, case in enumerate(cases):
            reference_seed = seeds["reference"] + case["replicate"] * 10 + case["p_index"]
            run_seed = seeds["runs"] + index
            case_id = f"{case['profile']}-{case['scenario']}-{case['start_mode']}-{case['replicate']}".replace("_", "-")
            results.append(run_case(
                db, manager, case_id=case_id[:40], profile=case["profile"], scenario=case["scenario"],
                start_mode=case["start_mode"], duration_s=case["duration_s"], reference_seed=reference_seed,
                run_seed=run_seed, floors=floors,
            ))
            print(f"\r{index + 1}/{len(cases)} çalıştırma", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    summary = summarize(results)
    output = {
        "set": args.set,
        "seeds": {"reference_base": seeds["reference"], "run_base": seeds["runs"],
                  "reference_seeds": sorted({r["reference_seed"] for r in results}),
                  "run_seeds": [results[0]["run_seed"], results[-1]["run_seed"]]},
        "replicates": args.replicates,
        "floors": floors,
        "analysis_config": ANALYSIS.as_dict(),
        "onset_s": ONSET_S,
        "detection_window_s": DETECTION_WINDOW_S,
        "runtime_s": round(time.time() - started, 1),
        "summary": summary,
        "cases": [{k: v for k, v in r.items() if k != "z_values"} for r in results],
    }
    out = Path(args.out) if args.out else ROOT / "reports" / f"{args.set}.json"
    out.write_text(json.dumps(output, ensure_ascii=False, indent=1))
    print(json.dumps({"set": args.set, "floors": floors, "summary": {k: v for k, v in summary.items() if k != "missed_cases"}},
                     ensure_ascii=False, indent=1))
    print(f"Ayrıntı: {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
