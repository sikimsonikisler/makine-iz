import csv
import io

import pytest
from fastapi.testclient import TestClient

from makine_iz.api import create_app
from makine_iz.config import FEATURES
from makine_iz.simulator import MachineSimulator, generate_records
from makine_iz.timeutil import now_epoch, to_iso


@pytest.fixture
def make_client(tmp_path):
    """Geçici veritabanıyla uygulama açar. Aynı yol verilirse 'yeniden başlatma' olur."""
    clients = []

    def _make(db_name="test.db", seed_demo=True):
        app = create_app(tmp_path / db_name, run_background=False, seed_demo=seed_demo, autostart_demo=False)
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client):
    return make_client()


def start_run(client, machine_id="demo-motor", scenario="normal", seed=7, start_mode="loaded", onset_s=120):
    response = client.post(
        "/api/sim/start",
        json={"machine_id": machine_id, "scenario": scenario, "seed": seed, "start_mode": start_mode, "onset_s": onset_s},
    )
    assert response.status_code == 201, response.text
    return response.json()


def advance(client, run_id, seconds, step=None):
    """Sanal zamanı ileri sarar. step verilirse küçük adımlarla (canlı akış gibi) ilerler."""
    step = step or seconds
    done = 0.0
    while done < seconds - 1e-9:
        chunk = min(step, seconds - done)
        response = client.post(f"/api/sim/runs/{run_id}/advance", json={"seconds": chunk})
        assert response.status_code == 200, response.text
        done += chunk
    return response.json()


def alerts_for(client, machine_id, **filters):
    return client.get("/api/alerts", params={"machine_id": machine_id, **filters}).json()


def create_machine(client, machine_id, data_source="sensor", **extra):
    payload = {"id": machine_id, "name": machine_id, "machine_type": "Motor", "data_source": data_source,
               "expected_interval_s": 5, **extra}
    response = client.post("/api/machines", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def sim_records(machine_id, start, steps, seed=1, scenario="normal", start_mode="loaded", onset_s=120, profile="motor"):
    simulator = MachineSimulator(profile, seed, start, machine_id=machine_id, scenario=scenario,
                                 start_mode=start_mode, onset_s=onset_s)
    return generate_records(simulator, steps)


def post_records(client, records):
    body = [{**r, "timestamp": to_iso(r["timestamp"])} for r in records]
    response = client.post("/api/telemetry", json={"records": body})
    assert response.status_code == 200, response.text
    return response.json()


def records_to_csv(records):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["machine_id", "timestamp", "operating_mode", *FEATURES])
    for r in records:
        writer.writerow([r["machine_id"], to_iso(r["timestamp"]), r["operating_mode"],
                         *["" if r[f] is None else r[f] for f in FEATURES]])
    return buffer.getvalue()


def make_baseline(client, machine_id, start_epoch, end_epoch, mode="loaded"):
    response = client.post(
        f"/api/machines/{machine_id}/baselines",
        json={"mode": mode, "start": to_iso(start_epoch), "end": to_iso(end_epoch), "confirm_normal": True},
    )
    assert response.status_code == 201, response.text
    return response.json()


def recent_start(steps, interval=5.0):
    """Kayıtlar 'şimdi'ye kadar gelsin diye başlangıç zamanı."""
    return float(int(now_epoch() - steps * interval))
