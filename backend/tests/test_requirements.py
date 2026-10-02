"""Görev metnindeki (bölüm 11) zorunlu kontroller — uygulamanın gerçek API'si üzerinden."""
from makine_iz.timeutil import from_iso

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


def deviation_alerts(client, machine_id):
    return alerts_for(client, machine_id, kind="deviation")


# 1) Sağlıklı yük değişimi kalıcı sapma uyarısı oluşturmuyor
def test_healthy_load_change_creates_no_deviation_alert(client):
    run = start_run(client, scenario="load_change", seed=11, start_mode="idle", onset_s=120)
    advance(client, run["id"], 3600)  # 1 saatte 6 mod geçişi
    assert deviation_alerts(client, "demo-motor") == []
    telemetry = client.get("/api/telemetry", params={"machine_id": "demo-motor", "limit": 10000}).json()
    sim_rows = [t for t in telemetry if t["sim_run_id"] == run["id"]]
    assert {"idle", "loaded"} <= {t["operating_mode"] for t in sim_rows}
    assert sum(1 for t in sim_rows if t["analysis_status"] == "transition") >= 6 * 6


# 2) Tek sıçrama süreklilik uyarısı oluşturmuyor
def test_single_spike_creates_no_alert(client):
    run = start_run(client, scenario="spike", seed=12)
    advance(client, run["id"], 900)
    assert deviation_alerts(client, "demo-motor") == []
    telemetry = client.get("/api/telemetry", params={"machine_id": "demo-motor", "limit": 10000}).json()
    spike = [t for t in telemetry if t["sim_run_id"] == run["id"] and t["analysis_status"] == "strong_candidate"]
    assert len(spike) == 1  # grafikte işaretli tek nokta


# 3) Sürekli sapma pencere kuralıyla uyarı oluşturuyor + 8) devam eden olay tek uyarı
def test_sustained_deviation_creates_one_updated_alert(client):
    run = start_run(client, scenario="vibration_ramp", seed=13, onset_s=120)
    advance(client, run["id"], 1500, step=60)
    alerts = deviation_alerts(client, "demo-motor")
    assert len(alerts) == 1, "devam eden olay için yalnızca bir uyarı olmalı"
    alert = alerts[0]
    assert alert["measurement_status"] == "active"
    assert alert["level"] == "strong"
    assert alert["details"]["updates"] > 10
    assert alert["details"]["latest"]["top"][0] == "vibration_rms_g"
    assert alert["baseline_version"] == 1
    onset = from_iso(run["onset_virtual"])
    assert from_iso(alert["started_at"]) >= onset  # değişimden önce uyarı yok
    status = client.get("/api/machines/demo-motor").json()["status"]
    assert status["category"] == "review" and status["needs_review"]


# 4) Veri kesintisi ayrı bir veri sorunu olarak gösteriliyor
def test_dropout_is_shown_as_data_issue_not_deviation(client):
    run = start_run(client, scenario="dropout", seed=14, onset_s=120)
    advance(client, run["id"], 180, step=10)  # kesintinin ortası
    status = client.get("/api/machines/demo-motor").json()["status"]
    assert status["code"] == "no_data_flow"
    assert status["category"] == "data_issue" and status["stale"]
    gap_alerts = alerts_for(client, "demo-motor", kind="data_quality")
    assert [a["dq_type"] for a in gap_alerts] == ["data_gap"]
    assert gap_alerts[0]["measurement_status"] == "active"
    advance(client, run["id"], 300, step=10)  # akış geri geldi
    gap_alert = alerts_for(client, "demo-motor", kind="data_quality")[0]
    assert gap_alert["measurement_status"] == "normalized"
    assert deviation_alerts(client, "demo-motor") == []


# 5) Eksik kayıt puanı sıfıra indirmiyor
def test_missing_values_do_not_become_zero_score(client):
    run = start_run(client, scenario="missing_values", seed=15, onset_s=60)
    advance(client, run["id"], 200)
    telemetry = client.get("/api/telemetry", params={"machine_id": "demo-motor", "limit": 10000}).json()
    invalid = [t for t in telemetry if t["sim_run_id"] == run["id"] and t["analysis_status"] == "invalid"]
    assert invalid, "senaryo eksik ölçüm üretmeli"
    for row in invalid:
        assert row["z_max"] is None  # sıfır değil, hesaplanmadı
        assert any(f.startswith("missing:") for f in row["quality_flags"])
    status = client.get("/api/machines/demo-motor").json()["status"]
    assert status["code"] != "ok" and status["data_issue"]
    assert deviation_alerts(client, "demo-motor") == []


# 6) Referansı olmayan makine normal gösterilmiyor
def test_machine_without_baseline_is_not_normal(client):
    create_machine(client, "yeni-pompa")
    start = recent_start(30)
    post_records(client, sim_records("yeni-pompa", start, 30, profile="pump"))
    status = client.get("/api/machines/yeni-pompa").json()["status"]
    assert status["code"] == "no_baseline"
    assert status["category"] != "ok"
    overview = client.get("/api/overview").json()
    card = next(c for c in overview["machines"] if c["machine"]["id"] == "yeni-pompa")
    assert card["status"]["label"] == "Referans oluşturulmalı"


# 7) Yinelenen ve sırası bozuk kayıtlar süreklilik hesabını bozmuyor
def test_duplicates_and_out_of_order_do_not_break_persistence(client):
    start = recent_start(400)
    normal = sim_records("x", start, 200, seed=21)
    deviating = sim_records("x", start + 200 * 5, 30, seed=22)
    for r in deviating:
        r["vibration_rms_g"] = round(r["vibration_rms_g"] * 2.5, 4)

    results = {}
    for machine_id, noisy in (("temiz", False), ("gurultulu", True)):
        create_machine(client, machine_id)
        records = [{**r, "machine_id": machine_id} for r in normal]
        post_records(client, records)
        make_baseline(client, machine_id, start, start + 200 * 5)
        sequence = []
        for i, r in enumerate(deviating):
            record = {**r, "machine_id": machine_id}
            sequence.append(record)
            if noisy and i % 3 == 0:
                sequence.append(dict(record))  # yinelenen
            if noisy and i % 4 == 0:
                sequence.append({**record, "timestamp": start + 7.5})  # sırası bozuk (çok eski)
        for record in sequence:  # canlı akış gibi tek tek gönder
            post_records(client, [record])
        results[machine_id] = deviation_alerts(client, machine_id)

    assert len(results["temiz"]) == len(results["gurultulu"]) == 1
    assert results["temiz"][0]["started_at"] == results["gurultulu"][0]["started_at"]
    seq_alerts = [a for a in alerts_for(client, "gurultulu", kind="data_quality") if a["dq_type"] == "sequence"]
    assert seq_alerts and seq_alerts[0]["details"]["duplicates"] > 0 and seq_alerts[0]["details"]["out_of_order"] > 0
    stored = client.get("/api/telemetry", params={"machine_id": "gurultulu", "limit": 10000}).json()
    assert len({t["ts"] for t in stored}) == len(stored)  # yinelenenler saklanmadı


# 9) Kullanıcı değerlendirmesi referansı kendiliğinden değiştirmiyor
def test_review_and_assessment_do_not_change_baseline(client):
    run = start_run(client, scenario="vibration_ramp", seed=16)
    advance(client, run["id"], 900)
    before = client.get("/api/machines/demo-motor/baselines").json()
    alert = deviation_alerts(client, "demo-motor")[0]
    response = client.patch(f"/api/alerts/{alert['id']}",
                            json={"review_status": "closed", "assessment": "normal_change"})
    assert response.status_code == 200
    note = client.post("/api/notes", json={"machine_id": "demo-motor", "alert_id": alert["id"],
                                           "text": "Kayış gerginliği ayarlandı.", "assessment": "normal_change"})
    assert note.status_code == 201
    after = client.get("/api/machines/demo-motor/baselines").json()
    assert after == before
    updated = client.get(f"/api/alerts/{alert['id']}").json()["alert"]
    assert updated["review_status"] == "closed"
    assert updated["measurement_status"] == "active"  # görmek/kapatmak ≠ normale dönmek


# 10) Uygulama yeniden başlatıldığında kayıtlar korunuyor
def test_restart_keeps_machines_baselines_alerts_notes(make_client):
    first = make_client("kalici.db")
    create_machine(first, "kalici-fan", machine_type="Fan")
    run = start_run(first, scenario="vibration_ramp", seed=17)
    advance(first, run["id"], 900)
    alert_id = deviation_alerts(first, "demo-motor")[0]["id"]
    first.patch(f"/api/alerts/{alert_id}", json={"review_status": "in_review", "assessment": "uncertain"})
    first.post("/api/notes", json={"machine_id": "demo-motor", "alert_id": alert_id, "text": "Kontrol edilecek."})
    first.post(f"/api/sim/runs/{run['id']}/resume")
    snapshot = {
        "machines": first.get("/api/machines").json(),
        "baselines": first.get("/api/machines/demo-motor/baselines").json(),
        "alerts": first.get("/api/alerts").json(),
        "notes": first.get("/api/notes").json(),
    }
    first.__exit__(None, None, None)

    second = make_client("kalici.db")  # aynı veritabanı = yeniden başlatma
    assert second.get("/api/machines").json() == snapshot["machines"]
    assert second.get("/api/machines/demo-motor/baselines").json() == snapshot["baselines"]
    assert second.get("/api/alerts").json() == snapshot["alerts"]
    assert second.get("/api/notes").json() == snapshot["notes"]
    runs = second.get("/api/sim/runs", params={"machine_id": "demo-motor"}).json()
    assert runs[0]["status"] == "paused" and "yeniden başlatıldı" in runs[0]["status_note"]
    # devam ettirilebiliyor ve aynı yerden sürüyor
    resumed = second.post(f"/api/sim/runs/{run['id']}/resume").json()
    assert resumed["status"] == "running"
    after = advance(second, run["id"], 60)
    assert after["steps_generated"] == 900 // 5 + 60 // 5


# 11) Demo sıfırlaması kullanıcı verisini silmiyor
def test_demo_reset_keeps_user_data(client):
    create_machine(client, "kullanici-motor", data_source="csv")
    start = recent_start(300) - 86400
    csv_text = records_to_csv(sim_records("kullanici-motor", start, 150, seed=31))
    imported = client.post("/api/csv/import", json={"content": csv_text, "filename": "k.csv"})
    assert imported.status_code == 200, imported.text
    client.post("/api/notes", json={"machine_id": "kullanici-motor", "text": "Kullanıcı notu"})
    run = start_run(client, scenario="vibration_ramp", seed=18)
    advance(client, run["id"], 900)
    demo_alert = deviation_alerts(client, "demo-motor")[0]
    client.post("/api/notes", json={"machine_id": "demo-motor", "alert_id": demo_alert["id"], "text": "Demo notu"})
    user_rows_before = client.get("/api/telemetry", params={"machine_id": "kullanici-motor", "limit": 10000}).json()

    response = client.post("/api/demo/reset", json={"confirm": True})
    assert response.status_code == 200

    user_rows_after = client.get("/api/telemetry", params={"machine_id": "kullanici-motor", "limit": 10000}).json()
    assert user_rows_after == user_rows_before
    assert client.get("/api/machines/kullanici-motor").status_code == 200
    notes = client.get("/api/notes").json()
    assert {n["text"] for n in notes} == {"Kullanıcı notu", "Demo notu"}
    demo_note = next(n for n in notes if n["text"] == "Demo notu")
    assert demo_note["alert_id"] is None and demo_note["alert_snapshot"]
    assert deviation_alerts(client, "demo-motor") == []
    demo_rows = client.get("/api/telemetry", params={"machine_id": "demo-motor", "limit": 10000}).json()
    assert demo_rows and all(r["segment"] == "demo_normal_history" or r["sim_run_id"] for r in demo_rows)
    assert len(client.get("/api/machines/demo-motor/baselines").json()) == 2
