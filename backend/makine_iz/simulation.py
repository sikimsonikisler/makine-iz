"""Simülasyon çalıştırmaları (SimulationRun) ve sanal saat.

- Her çalıştırmanın kendi sanal saati vardır. Hız (ör. 20×) sanal zamanı hızlandırır,
  duraklatma sanal zamanı dondurur.
- Üretilen kayıtlar sensör/CSV ile AYNI veri yolundan (pipeline.ingest) geçer.
- Yeniden başlatmada çalışan simülasyonlar "duraklatıldı" durumuna alınır; devam ettirildiğinde
  üreteç, kayıtlı tohum ve parametrelerden yeniden kurulup kaldığı adıma kadar tekrar oynatılır.
"""
from __future__ import annotations

import sqlite3

from .alerts import AlertContext, open_data_gap
from .config import ANALYSIS, MODES
from .db import Database, dumps, loads
from .machines import get_machine
from .pipeline import IngestOptions, ingest
from .simulator import SCENARIOS, MachineSimulator
from .store import load_state
from .timeutil import from_iso, now_epoch, to_iso

SPEEDS = (1.0, 5.0, 20.0, 60.0)
MAX_ADVANCE_S = 6 * 3600


class SimulationError(ValueError):
    pass


def run_from_row(row: sqlite3.Row) -> dict:
    data = dict(row)
    data["params"] = loads(data.pop("params_json"), {})
    scenario = SCENARIOS.get(data["scenario"], {})
    data["scenario_label"] = scenario.get("label", data["scenario"])
    start = from_iso(data["start_virtual"])
    now = from_iso(data["virtual_now"])
    data["elapsed_virtual_s"] = round(now - start, 1)
    onset_s = float(data["params"].get("onset_s", 0))
    data["onset_virtual"] = to_iso(start + onset_s)
    return data


class SimulationManager:
    def __init__(self, db: Database):
        self.db = db
        self._generators: dict[int, MachineSimulator] = {}

    # ------------------------------------------------------------------ yardımcılar
    def _build_generator(self, run: dict, machine: dict) -> MachineSimulator:
        params = run["params"]
        generator = MachineSimulator(
            params["profile"],
            int(run["seed"]),
            from_iso(run["start_virtual"]),
            machine_id=machine["id"],
            interval_s=float(params["interval_s"]),
            scenario=run["scenario"],
            start_mode=params["start_mode"],
            onset_s=float(params["onset_s"]),
            mode_changes=params.get("mode_changes", []),
            effect_end_step=params.get("effect_end_step"),
        )
        # Kaldığı yere kadar tekrar oynat (aynı tohum → aynı değerler)
        for _ in range(int(run["steps_generated"])):
            generator.next()
        return generator

    def _generator(self, run: dict, machine: dict) -> MachineSimulator:
        generator = self._generators.get(run["id"])
        if generator is None or generator.step_index != run["steps_generated"]:
            generator = self._build_generator(run, machine)
            self._generators[run["id"]] = generator
        return generator

    def _get_run(self, conn: sqlite3.Connection, run_id: int) -> dict:
        row = conn.execute("SELECT * FROM simulation_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise LookupError("Simülasyon çalıştırması bulunamadı.")
        return run_from_row(row)

    def _save_params(self, conn, run_id: int, params: dict) -> None:
        conn.execute(
            "UPDATE simulation_runs SET params_json = ?, updated_at = ? WHERE id = ?",
            (dumps(params), to_iso(now_epoch()), run_id),
        )

    def _set_status(self, run_id: int, status: str, note: str = "") -> dict:
        with self.db.write() as conn:
            run = self._get_run(conn, run_id)
            if run["status"] == "stopped":
                raise SimulationError("Bu çalıştırma durduruldu; yeni bir senaryo başlatın.")
            conn.execute(
                "UPDATE simulation_runs SET status = ?, status_note = ?, updated_at = ? WHERE id = ?",
                (status, note, to_iso(now_epoch()), run_id),
            )
            if status == "stopped":
                self._generators.pop(run_id, None)
            return self._get_run(conn, run_id)

    # ------------------------------------------------------------------ yaşam döngüsü
    def pause_after_restart(self) -> int:
        with self.db.write() as conn:
            cursor = conn.execute(
                """UPDATE simulation_runs SET status = 'paused',
                       status_note = 'Uygulama yeniden başlatıldı; simülasyon duraklatıldı. Devam ettirebilirsiniz.'
                   WHERE status = 'running'"""
            )
            return cursor.rowcount

    def start(
        self,
        machine_id: str,
        scenario: str,
        *,
        seed: int,
        speed: float = 1.0,
        start_mode: str = "loaded",
        onset_s: float = 120.0,
    ) -> dict:
        if scenario not in SCENARIOS:
            raise SimulationError("Bilinmeyen senaryo.")
        if start_mode not in MODES:
            raise SimulationError("Başlangıç modu stopped, idle veya loaded olmalı.")
        if not (0 <= int(seed) <= 2**31 - 1):
            raise SimulationError("Tohum 0 ile 2147483647 arasında bir tam sayı olmalı.")
        if not (0.1 <= float(speed) <= 120):
            raise SimulationError("Hız 0,1× ile 120× arasında olmalı.")
        if not (0 <= float(onset_s) <= 7200):
            raise SimulationError("Değişim başlangıcı 0–7200 saniye arasında olmalı.")
        with self.db.write() as conn:
            machine = get_machine(conn, machine_id)
            if machine is None:
                raise LookupError("Makine bulunamadı.")
            if machine["data_source"] != "simulation" or not machine["sim_profile"]:
                raise SimulationError("Bu makinenin veri kaynağı simülasyon değil.")
            if not machine["modes"].get(start_mode, {}).get("enabled", False):
                raise SimulationError("Başlangıç modu bu makine için tanımlı değil.")
            for row in conn.execute(
                "SELECT id FROM simulation_runs WHERE machine_id = ? AND status != 'stopped'", (machine_id,)
            ).fetchall():
                self._generators.pop(row["id"], None)
            conn.execute(
                """UPDATE simulation_runs SET status = 'stopped', status_note = 'Yeni senaryo başlatıldı.', updated_at = ?
                   WHERE machine_id = ? AND status != 'stopped'""",
                (to_iso(now_epoch()), machine_id),
            )
            state = load_state(conn, machine_id)
            # Sanal saat, makinenin son kaydından geriye gidemez (sırası bozuk kayıt üretmemek için).
            start_virtual = max(now_epoch(), state.last_ts or 0.0)
            params = {
                "profile": machine["sim_profile"],
                "interval_s": machine["expected_interval_s"],
                "start_mode": start_mode,
                "onset_s": float(onset_s),
                "mode_changes": [],
                "effect_end_step": None,
            }
            now_iso = to_iso(now_epoch())
            cursor = conn.execute(
                """INSERT INTO simulation_runs (machine_id, scenario, seed, status, speed, start_virtual, virtual_now,
                       steps_generated, records_emitted, params_json, status_note, created_at, updated_at)
                   VALUES (?, ?, ?, 'running', ?, ?, ?, 0, 0, ?, '', ?, ?)""",
                (
                    machine_id, scenario, int(seed), float(speed), to_iso(start_virtual), to_iso(start_virtual),
                    dumps(params), now_iso, now_iso,
                ),
            )
            return self._get_run(conn, int(cursor.lastrowid))

    def pause(self, run_id: int) -> dict:
        return self._set_status(run_id, "paused", "Kullanıcı duraklattı.")

    def resume(self, run_id: int) -> dict:
        return self._set_status(run_id, "running", "")

    def stop(self, run_id: int) -> dict:
        return self._set_status(run_id, "stopped", "Kullanıcı durdurdu.")

    def set_speed(self, run_id: int, speed: float) -> dict:
        if not (0.1 <= float(speed) <= 120):
            raise SimulationError("Hız 0,1× ile 120× arasında olmalı.")
        with self.db.write() as conn:
            self._get_run(conn, run_id)
            conn.execute(
                "UPDATE simulation_runs SET speed = ?, updated_at = ? WHERE id = ?",
                (float(speed), to_iso(now_epoch()), run_id),
            )
            return self._get_run(conn, run_id)

    def set_mode(self, run_id: int, mode: str) -> dict:
        """Kullanıcı simülatöre çalışma modunu söyler (bir sonraki adımdan itibaren)."""
        if mode not in MODES:
            raise SimulationError("Mod stopped, idle veya loaded olmalı.")
        with self.db.write() as conn:
            run = self._get_run(conn, run_id)
            if run["status"] == "stopped":
                raise SimulationError("Bu çalıştırma durduruldu.")
            machine = get_machine(conn, run["machine_id"])
            if not machine or not machine["modes"].get(mode, {}).get("enabled", False):
                raise SimulationError("Bu mod makine için tanımlı değil.")
            params = run["params"]
            params.setdefault("mode_changes", []).append([int(run["steps_generated"]) + 1, mode])
            self._save_params(conn, run_id, params)
            self._generators.pop(run_id, None)
            return self._get_run(conn, run_id)

    def remove_effect(self, run_id: int) -> dict:
        """Senaryo etkisini kaldırır; makine normal davranışa döner."""
        with self.db.write() as conn:
            run = self._get_run(conn, run_id)
            if run["status"] == "stopped":
                raise SimulationError("Bu çalıştırma durduruldu.")
            machine = get_machine(conn, run["machine_id"])
            params = run["params"]
            next_step = int(run["steps_generated"]) + 1
            params["effect_end_step"] = next_step
            if run["scenario"] == "load_change" and machine:
                generator = self._generator(run, machine)
                params.setdefault("mode_changes", []).append([next_step, generator.mode_at(max(1, next_step - 1))])
            self._save_params(conn, run_id, params)
            self._generators.pop(run_id, None)
            return self._get_run(conn, run_id)

    def advance(self, run_id: int, seconds: float) -> dict:
        """Sanal zamanı hemen ileri sarar (duraklatılmış çalıştırmada da kullanılabilir)."""
        if not (0 < float(seconds) <= MAX_ADVANCE_S):
            raise SimulationError("İleri sarma süresi 0 ile 6 saat arasında olmalı.")
        with self.db.write() as conn:
            run = self._get_run(conn, run_id)
            if run["status"] == "stopped":
                raise SimulationError("Bu çalıştırma durduruldu.")
            machine = get_machine(conn, run["machine_id"])
            try:
                self._advance(conn, run, machine, from_iso(run["virtual_now"]) + float(seconds))
            except Exception:
                self._generators.pop(run_id, None)
                raise
            return self._get_run(conn, run_id)

    def tick(self, real_dt: float) -> None:
        """Arka plan döngüsü: çalışan simülasyonları ilerletir, canlı kaynakları kontrol eder."""
        real_dt = max(0.0, min(real_dt, 2.0))
        try:
            with self.db.write() as conn:
                runs = [run_from_row(r) for r in conn.execute("SELECT * FROM simulation_runs WHERE status = 'running'")]
                for run in runs:
                    machine = get_machine(conn, run["machine_id"])
                    if machine is None:
                        continue
                    self._advance(conn, run, machine, from_iso(run["virtual_now"]) + real_dt * float(run["speed"]))
                for row in conn.execute("SELECT id FROM machines WHERE data_source = 'sensor'").fetchall():
                    machine = get_machine(conn, row["id"])
                    if machine:
                        self._check_stale(conn, machine, now_epoch())
        except Exception:
            self._generators.clear()
            raise

    # ------------------------------------------------------------------ çekirdek
    def _advance(self, conn, run: dict, machine: dict, target_virtual: float) -> int:
        generator = self._generator(run, machine)
        records = []
        while generator.ts_at(generator.step_index + 1) <= target_virtual + 1e-6:
            record = generator.next()
            if record is not None:
                records.append(record)
        if records:
            ingest(conn, records, IngestOptions(source="simulation", is_demo=machine["is_demo"], sim_run_id=run["id"]))
        conn.execute(
            """UPDATE simulation_runs SET virtual_now = ?, steps_generated = ?, records_emitted = records_emitted + ?,
                   updated_at = ? WHERE id = ?""",
            (to_iso(target_virtual), generator.step_index, len(records), to_iso(now_epoch()), run["id"]),
        )
        run["steps_generated"] = generator.step_index
        self._check_stale(conn, machine, target_virtual)
        return len(records)

    def _check_stale(self, conn, machine: dict, now: float) -> None:
        state = load_state(conn, machine["id"])
        if state.last_ts is None:
            return
        if now - state.last_ts > ANALYSIS.gap_factor * machine["expected_interval_s"]:
            ctx = AlertContext(is_demo=machine["is_demo"], source=machine["data_source"], live=True)
            open_data_gap(conn, machine, state.last_ts, now, ctx)

    # ------------------------------------------------------------------ sorgular
    def list_runs(self, machine_id: str | None = None, limit: int = 50) -> list[dict]:
        with self.db.read() as conn:
            if machine_id:
                rows = conn.execute(
                    "SELECT * FROM simulation_runs WHERE machine_id = ? ORDER BY id DESC LIMIT ?", (machine_id, limit)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM simulation_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [run_from_row(r) for r in rows]

    def get_run(self, run_id: int) -> dict:
        with self.db.read() as conn:
            return self._get_run(conn, run_id)

    def forget_all(self) -> None:
        self._generators.clear()


def latest_runs_by_machine(conn: sqlite3.Connection) -> dict[str, dict]:
    """Her makine için en son çalıştırma (durum kartları için)."""
    rows = conn.execute(
        """SELECT r.* FROM simulation_runs r
           JOIN (SELECT machine_id, MAX(id) AS max_id FROM simulation_runs GROUP BY machine_id) x
             ON x.max_id = r.id"""
    ).fetchall()
    return {row["machine_id"]: run_from_row(row) for row in rows}
