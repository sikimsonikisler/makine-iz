"""Ek davranış testleri: normalleşme, tekrar üretilebilirlik, CSV, referans sürümleri, simülasyon saati."""
import numpy as np

from makine_iz.config import FEATURES
from makine_iz.simulator import MachineSimulator, generate_records
from makine_iz.timeutil import from_iso, to_iso

from .conftest import (
    advance,
    alerts_for,
    create_machine,
    make_baseline,
    post_records,
    recent_start,
    records_to_csv,
    sim_records,
    start_run,
)


def test_recovery_scenario_normalizes_but_keeps_review(client):
    run = start_run(client, scenario="recovery", seed=41, onset_s=120)
    advance(client, run["id"], 1500, step=60)
    alerts = alerts_for(client, "demo-motor", kind="deviation")
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["measurement_status"] == "normalized"
    assert alert["ended_at"] is not None
    assert alert["review_status"] == "new"  # kullanıcı kaydı otomatik değişmez
    status = client.get("/api/machines/demo-motor").json()["status"]
    # Etki kalktı: makine referansla uyumlu (son pencerede rastgele tek bir z ≥ 3 "aday" olabilir, uyarı değildir)
    assert status["category"] in ("ok", "watch")
    assert status["needs_review"]  # incelenmemiş uyarı hâlâ listede


def test_freeze_scenario_is_data_issue(client):
    run = start_run(client, scenario="freeze", seed=42, onset_s=60)
    advance(client, run["id"], 150, step=10)
    status = client.get("/api/machines/demo-motor").json()["status"]
    assert status["code"] == "frozen" and status["category"] == "data_issue"
    dq = alerts_for(client, "demo-motor", kind="data_quality")
    assert [a["dq_type"] for a in dq] == ["frozen"]
    advance(client, run["id"], 300, step=30)
    assert alerts_for(client, "demo-motor", kind="data_quality")[0]["measurement_status"] == "normalized"
    rows = client.get("/api/telemetry", params={"machine_id": "demo-motor", "limit": 10000}).json()
    frozen = [r for r in rows if r["analysis_status"] == "frozen_suspect"]
    assert frozen and all(r["z_max"] is None for r in frozen)  # donmuş kayıtlar değerlendirilmez
    frozen_start, frozen_end = from_iso(frozen[0]["ts"]), from_iso(frozen[-1]["ts"])
    for alert in alerts_for(client, "demo-motor", kind="deviation"):  # donma sapma diye gösterilmemeli
        raised = alert["details"]["initial"]["window_ts"][-1]
        assert not (frozen_start <= raised <= frozen_end)


def test_simulator_is_reproducible_and_correlated():
    a = generate_records(MachineSimulator("pump", 5, 1_700_000_000.0, scenario="temperature_ramp"), 400)
    b = generate_records(MachineSimulator("pump", 5, 1_700_000_000.0, scenario="temperature_ramp"), 400)
    c = generate_records(MachineSimulator("pump", 6, 1_700_000_000.0, scenario="temperature_ramp"), 400)
    assert a == b
    assert a != c
    normal = np.array([r["temperature_c"] for r in generate_records(MachineSimulator("pump", 9, 1e9), 2000)])
    lag1 = np.corrcoef(normal[:-1], normal[1:])[0, 1]
    assert lag1 > 0.5, "ölçümler zaman içinde ilişkili olmalı (bağımsız rastgele sayılar değil)"


def test_analysis_is_identical_for_sensor_and_csv_paths(client):
    """Analiz yalnızca ölçüme bakar: aynı kayıtlar sensör API'sinden de CSV'den de gelse sonuç aynıdır."""
    start = recent_start(600) - 86400
    records = sim_records("x", start, 500, seed=51, scenario="power_vibration", onset_s=1500)
    normal_end = start + 250 * 5
    for machine_id, source in (("yol-sensor", "sensor"), ("yol-csv", "csv")):
        create_machine(client, machine_id, data_source=source)
        first = [{**r, "machine_id": machine_id} for r in records if r["timestamp"] <= normal_end]
        rest = [{**r, "machine_id": machine_id} for r in records if r["timestamp"] > normal_end]
        post_records(client, first)
        make_baseline(client, machine_id, start, normal_end)
        if source == "sensor":
            post_records(client, rest)
        else:
            response = client.post("/api/csv/import", json={"content": records_to_csv(rest), "filename": "yol.csv"})
            assert response.status_code == 200, response.text
    rows = {
        mid: client.get("/api/telemetry", params={"machine_id": mid, "limit": 10000}).json()
        for mid in ("yol-sensor", "yol-csv")
    }
    assert [(r["ts"], r["analysis_status"], r["z_max"]) for r in rows["yol-sensor"]] == \
        [(r["ts"], r["analysis_status"], r["z_max"]) for r in rows["yol-csv"]]
    a = alerts_for(client, "yol-sensor", kind="deviation")
    b = alerts_for(client, "yol-csv", kind="deviation")
    assert len(a) == len(b) == 1 and a[0]["started_at"] == b[0]["started_at"]


def test_new_baseline_keeps_old_alert_version(client):
    run = start_run(client, scenario="vibration_ramp", seed=61)
    advance(client, run["id"], 900)
    old = alerts_for(client, "demo-motor", kind="deviation")[0]
    assert old["baseline_version"] == 1
    end = from_iso(run["virtual_now"]) + 900
    make_baseline(client, "demo-motor", end - 900, end)  # kullanıcı yeni aralığı normal kabul etti
    after = client.get(f"/api/alerts/{old['id']}").json()
    assert after["alert"]["baseline_version"] == 1
    assert after["alert"]["is_open"] is False
    assert after["current_baseline_version"] == 2
    advance(client, run["id"], 300)
    new_alerts = [a for a in alerts_for(client, "demo-motor", kind="deviation") if a["id"] != old["id"]]
    assert all(a["baseline_version"] == 2 for a in new_alerts)


def test_baseline_requires_enough_valid_records(client):
    create_machine(client, "az-veri")
    start = recent_start(100)
    post_records(client, sim_records("az-veri", start, 100))
    response = client.post("/api/machines/az-veri/baselines",
                           json={"mode": "loaded", "start": to_iso(start), "end": to_iso(start + 600), "confirm_normal": True})
    assert response.status_code == 400
    assert "Referans için veri yetersiz" in response.json()["detail"]
    preview = client.post("/api/machines/az-veri/baselines/preview",
                          json={"mode": "loaded", "start": to_iso(start), "end": to_iso(start + 600)}).json()
    assert preview["enough"] is False and preview["valid_count"] == 100
    no_confirm = client.post("/api/machines/demo-motor/baselines",
                             json={"mode": "loaded", "start": to_iso(start - 7200), "end": to_iso(start)})
    assert no_confirm.status_code == 400
    stopped = client.post("/api/machines/demo-motor/baselines/preview",
                          json={"mode": "stopped", "start": to_iso(start - 7200), "end": to_iso(start)})
    assert stopped.status_code == 400


def test_csv_with_errors_imports_nothing_and_reports_row_and_field(client):
    create_machine(client, "csv-makine", data_source="csv")
    start = recent_start(50) - 86400
    good = records_to_csv(sim_records("csv-makine", start, 20, seed=71)).strip().splitlines()
    bad_lines = good[:5] + [
        f"csv-makine,2026-13-45T10:00:00Z,loaded,0.1,40,5,1450",
        f"csv-makine,{to_iso(start + 500)},running,0.1,40,5,1450",
        f"csv-makine,{to_iso(start + 505)},loaded,abc,40,5,1450",
        f"bilinmeyen,{to_iso(start + 510)},loaded,0.1,40,5,1450",
    ]
    response = client.post("/api/csv/import", json={"content": "\n".join(bad_lines), "filename": "hatali.csv"})
    assert response.status_code == 422
    report = response.json()["report"]
    errors = {(e["row"], e["field"]) for e in report["errors"]}
    assert errors == {(6, "timestamp"), (7, "operating_mode"), (8, "vibration_rms_g"), (9, "machine_id")}
    assert client.get("/api/telemetry", params={"machine_id": "csv-makine"}).json() == []
    missing_column = client.post("/api/csv/preview", json={"content": "machine_id,timestamp\nx,1"}).json()
    assert not missing_column["ok"] and any(e["field"] == "operating_mode" for e in missing_column["errors"])


def test_csv_duplicate_policy_and_warnings(client):
    create_machine(client, "csv-kopya", data_source="csv")
    start = recent_start(200) - 86400
    records = sim_records("csv-kopya", start, 150, seed=72)
    records[10]["temperature_c"] = None
    lines = records_to_csv(records).strip().splitlines()
    lines.append(lines[20])  # birebir yinelenen satır
    preview = client.post("/api/csv/preview", json={"content": "\n".join(lines)}).json()
    assert preview["ok"]
    assert preview["summary"]["duplicates_in_file"] == 1
    assert preview["summary"]["missing_values"] == 1
    assert any(w["row"] == 12 and w["field"] == "temperature_c" for w in preview["warnings"])
    result = client.post("/api/csv/import", json={"content": "\n".join(lines), "filename": "kopya.csv"}).json()
    assert result["imported_rows"] == 150 and result["skipped_duplicates"] == 1
    again = client.post("/api/csv/import", json={"content": "\n".join(lines), "filename": "kopya.csv"}).json()
    assert again["imported_rows"] == 0 and again["skipped_duplicates"] == 151
    missing = [r for r in client.get("/api/telemetry", params={"machine_id": "csv-kopya", "limit": 1000}).json()
               if r["temperature_c"] is None]
    assert len(missing) == 1 and missing[0]["z_max"] is None and "missing:temperature_c" in missing[0]["quality_flags"]


def test_old_csv_history_is_not_shown_as_disconnected(client):
    create_machine(client, "eski-veri", data_source="csv")
    start = recent_start(10) - 30 * 86400
    csv_text = records_to_csv(sim_records("eski-veri", start, 200, seed=73))
    assert client.post("/api/csv/import", json={"content": csv_text}).status_code == 200
    make_baseline(client, "eski-veri", start, start + 199 * 5)
    status = client.get("/api/machines/eski-veri").json()["status"]
    assert status["code"] != "no_data_flow" and not status["stale"]
    assert status["live"]["kind"] == "csv"


def test_pause_freezes_and_speed_accelerates_virtual_time(client):
    run = start_run(client, seed=81)
    manager = client.app.state.manager
    manager.tick(1.0)
    after_one = client.get(f"/api/sim/runs").json()[0]
    assert from_iso(after_one["virtual_now"]) - from_iso(run["virtual_now"]) == 1.0
    client.post(f"/api/sim/runs/{run['id']}/pause")
    manager.tick(1.0)
    paused = client.get(f"/api/sim/runs").json()[0]
    assert paused["virtual_now"] == after_one["virtual_now"] and paused["status"] == "paused"
    client.post(f"/api/sim/runs/{run['id']}/resume")
    client.post(f"/api/sim/runs/{run['id']}/speed", json={"speed": 20})
    manager.tick(1.5)
    fast = client.get(f"/api/sim/runs").json()[0]
    assert from_iso(fast["virtual_now"]) - from_iso(after_one["virtual_now"]) == 30.0
    assert fast["steps_generated"] == 6  # 31 sn sanal → 5 sn aralıkla 6 kayıt


def test_api_errors_are_clear_and_turkish(client):
    response = client.post("/api/machines", json={"id": "x y", "name": "", "machine_type": "Motor"})
    assert response.status_code == 400 and "kimliği" in response.json()["detail"]
    response = client.post("/api/sim/start", json={"machine_id": "demo-motor"})
    assert response.status_code == 422 and "zorunlu alan eksik" in response.json()["detail"]
    response = client.get("/api/machines/yok")
    assert response.status_code == 404 and response.json()["detail"] == "Makine bulunamadı."
    single = client.post("/api/telemetry", json={"machine_id": "demo-motor", "timestamp": "dün öğlen"})
    assert single.status_code == 422 and "zaman damgası" in single.json()["detail"].lower()


def test_sensor_api_flags_invalid_values_without_zeroing(client):
    create_machine(client, "sensor-1")
    start = recent_start(5)
    body = {"machine_id": "sensor-1", "timestamp": to_iso(start), "operating_mode": "loaded",
            "vibration_rms_g": "abc", "temperature_c": 40.0, "power_kw": -3, "rpm": 1450}
    result = client.post("/api/telemetry", json=body).json()["results"][0]
    assert result["stored"] and result["status"] == "invalid"
    assert set(result["flags"]) >= {"non_numeric:vibration_rms_g", "negative:power_kw"}
    row = client.get("/api/telemetry", params={"machine_id": "sensor-1"}).json()[0]
    assert row["vibration_rms_g"] is None and row["power_kw"] == -3 and row["raw"]["vibration_rms_g"] == "abc"
    series = client.get("/api/machines/sensor-1/series").json()
    assert series["points"][0]["power_kw"] is None  # grafikte geçersiz değer çizilmez


def test_series_breaks_lines_at_gaps_and_downsamples_for_display(client):
    run = start_run(client, scenario="dropout", seed=91, onset_s=60)
    advance(client, run["id"], 400)
    detail = client.get("/api/machines/demo-motor").json()
    raw = client.get("/api/machines/demo-motor/series",
                     params={"start": run["start_virtual"], "end": detail["range"]["last_ts"]}).json()
    assert not raw["downsampled"]
    assert any(p.get("gap") for p in raw["points"])
    full = client.get("/api/machines/demo-motor/series",
                      params={"start": detail["range"]["first_ts"], "end": detail["range"]["last_ts"],
                              "max_points": 200}).json()
    assert full["downsampled"] and len(full["points"]) <= 260 and full["total"] == detail["range"]["count"]
    assert all(set(FEATURES) <= set(p) for p in full["points"])
