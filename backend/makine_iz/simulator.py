"""Tekrar üretilebilir makine simülatörü.

- Sabit tohum (seed) → aynı ölçümler. Her adımda rastgele sayılar sabit sırada çekilir.
- Ölçümler zaman içinde ilişkilidir: her özellik AR(1) süreci + ortak "yük" etkeni.
- Mod değişince değerler hedefe birinci dereceden gecikmeyle (zaman sabiti τ) oturur.
- Sanal zaman: her adım bir ölçüm aralığıdır; veri kesintisinde zaman ilerler ama kayıt üretilmez.

Senaryo bilgisi yalnızca ölçüm ÜRETMEK için kullanılır. Analiz motoru senaryoyu bilmez.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .config import FEATURES


@dataclass(frozen=True)
class ModeProfile:
    mean: dict  # özellik → ortalama
    sd: dict  # özellik → standart sapma (gürültü)


def _profile(vib, vib_sd, temp, temp_sd, power, power_sd, rpm, rpm_sd) -> ModeProfile:
    return ModeProfile(
        mean={"vibration_rms_g": vib, "temperature_c": temp, "power_kw": power, "rpm": rpm},
        sd={"vibration_rms_g": vib_sd, "temperature_c": temp_sd, "power_kw": power_sd, "rpm": rpm_sd},
    )


# Demo makinelerinin normal ölçüm dağılımları (uydurma ama birbirinden farklı ve tutarlı değerler)
PROFILES: dict[str, dict[str, ModeProfile]] = {
    "motor": {
        "stopped": _profile(0.006, 0.001, 26.0, 0.3, 0.02, 0.005, 0.0, 0.0),
        "idle": _profile(0.080, 0.006, 42.0, 0.5, 1.80, 0.05, 1490.0, 1.5),
        "loaded": _profile(0.150, 0.011, 58.0, 0.6, 11.0, 0.25, 1455.0, 2.5),
    },
    "pump": {
        "stopped": _profile(0.008, 0.001, 22.0, 0.3, 0.03, 0.005, 0.0, 0.0),
        "idle": _profile(0.120, 0.009, 38.0, 0.4, 2.50, 0.07, 2960.0, 2.0),
        "loaded": _profile(0.220, 0.016, 52.0, 0.6, 15.0, 0.35, 2905.0, 3.0),
    },
    "fan": {
        "stopped": _profile(0.004, 0.001, 24.0, 0.3, 0.01, 0.003, 0.0, 0.0),
        "idle": _profile(0.050, 0.004, 30.0, 0.3, 0.60, 0.02, 700.0, 2.0),
        "loaded": _profile(0.090, 0.007, 36.0, 0.4, 3.20, 0.08, 980.0, 3.0),
    },
    "compressor": {
        "stopped": _profile(0.007, 0.001, 25.0, 0.3, 0.05, 0.01, 0.0, 0.0),
        "idle": _profile(0.100, 0.008, 45.0, 0.5, 4.00, 0.10, 2975.0, 2.0),
        "loaded": _profile(0.180, 0.013, 68.0, 0.7, 22.0, 0.50, 2940.0, 2.5),
    },
}
PROFILE_LABELS = {"motor": "Motor", "pump": "Pompa", "fan": "Fan", "compressor": "Kompresör"}

# (AR katsayısı φ, ortak yük etkeniyle ilişki katsayısı a, oturma zaman sabiti τ [sn])
DYNAMICS = {
    "vibration_rms_g": (0.5, 0.3, 3.0),
    "temperature_c": (0.8, 0.3, 8.0),
    "power_kw": (0.7, 0.6, 3.0),
    "rpm": (0.6, -0.5, 3.0),
}
LOAD_PHI = 0.95
ROUNDING = {"vibration_rms_g": 4, "temperature_c": 2, "power_kw": 3, "rpm": 1}

SCENARIOS: dict[str, dict] = {
    "normal": {
        "label": "Normal çalışma",
        "description": "Değişiklik uygulanmaz; seçilen modda normal dağılımdan ölçüm üretilir.",
        "group": "davranış",
    },
    "load_change": {
        "label": "Sağlıklı boşta → yük geçişi",
        "description": "Boşta başlar; değişim anında yük altına geçer, sonra her 10 dakikada bir boşta/yük arasında "
        "sağlıklı biçimde gidip gelir.",
        "group": "davranış",
    },
    "vibration_ramp": {
        "label": "Kademeli titreşim yükselmesi",
        "description": "Değişim anından itibaren titreşim RMS 10 dakikada kademeli olarak 2,5 katına çıkar.",
        "group": "davranış",
    },
    "temperature_ramp": {
        "label": "Kademeli sıcaklık yükselmesi",
        "description": "Değişim anından itibaren sıcaklık 15 dakikada kademeli olarak 12 °C artar.",
        "group": "davranış",
    },
    "power_vibration": {
        "label": "Güç ve titreşim birlikte değişir",
        "description": "5 dakika içinde güç %25, titreşim %80 artar.",
        "group": "davranış",
    },
    "spike": {
        "label": "Tek seferlik ölçüm sıçraması",
        "description": "Değişim anında tek bir kayıtta titreşim 4 katına sıçrar, sonra normale döner.",
        "group": "davranış",
    },
    "missing_values": {
        "label": "Eksik ölçüm",
        "description": "5 dakika boyunca kayıtların yaklaşık dörtte birinde bir ölçüm alanı boş gelir.",
        "group": "veri",
    },
    "dropout": {
        "label": "Veri akışının kesilmesi",
        "description": "2 dakika boyunca sanal zaman ilerler ama hiç kayıt üretilmez.",
        "group": "veri",
    },
    "freeze": {
        "label": "Bütün ölçümlerin donması",
        "description": "3 dakika boyunca dört ölçüm de son değerde birebir aynı kalır.",
        "group": "veri",
    },
    "recovery": {
        "label": "Sapma ve sonrasında normalleşme",
        "description": "8 dakika boyunca titreşim ve sıcaklık yükselir, sonra etki kaldırılır ve ölçümler normale döner.",
        "group": "davranış",
    },
}
SCENARIO_ORDER = list(SCENARIOS)

LOAD_CHANGE_PERIOD_S = 600.0


class MachineSimulator:
    """Bir makine için adım adım ölçüm üretir. Aynı parametre + tohum → aynı çıktı."""

    def __init__(
        self,
        profile: str,
        seed: int,
        start_ts: float,
        *,
        machine_id: str = "sim",
        interval_s: float = 5.0,
        scenario: str = "normal",
        start_mode: str = "loaded",
        onset_s: float = 120.0,
        mode_changes: list | None = None,
        effect_end_step: int | None = None,
    ):
        if profile not in PROFILES:
            raise ValueError(f"Bilinmeyen simülasyon profili: {profile}")
        if scenario not in SCENARIOS:
            raise ValueError(f"Bilinmeyen senaryo: {scenario}")
        self.profiles = PROFILES[profile]
        self.machine_id = machine_id
        self.seed = seed
        self.start_ts = start_ts
        self.interval_s = interval_s
        self.scenario = scenario
        self.start_mode = start_mode
        self.onset_step = max(1, int(round(onset_s / interval_s)))
        self.mode_changes: list[tuple[int, str]] = [(int(s), m) for s, m in (mode_changes or [])]
        self.effect_end_step = effect_end_step
        self.rng = np.random.default_rng(seed)
        self.step_index = 0
        initial = self.mode_at(1)
        self.levels = dict(self.profiles[initial].mean)
        self.ar = {f: 0.0 for f in FEATURES}
        self.load = 0.0
        self.last_values: dict | None = None
        self.frozen_values: dict | None = None

    # -- modlar ve senaryo zamanlaması -------------------------------------
    def mode_at(self, step: int) -> str:
        overrides = [mode for at, mode in self.mode_changes if at <= step]
        if overrides:
            return overrides[-1]
        if self.scenario == "load_change":
            if step < self.onset_step:
                return "idle"
            period_steps = int(LOAD_CHANGE_PERIOD_S / self.interval_s)
            return "loaded" if ((step - self.onset_step) // period_steps) % 2 == 0 else "idle"
        return self.start_mode

    def effect_active(self, step: int) -> bool:
        if step < self.onset_step:
            return False
        return self.effect_end_step is None or step < self.effect_end_step

    def ts_at(self, step: int) -> float:
        return round(self.start_ts + step * self.interval_s, 3)

    # -- bir adım ------------------------------------------------------------
    def next(self) -> dict | None:
        """Bir ölçüm aralığı ilerler. Kayıt üretilmezse (veri kesintisi) None döner."""
        step = self.step_index + 1
        self.step_index = step
        noise = self.rng.standard_normal(5)  # 4 özellik + ortak yük
        aux = self.rng.random(2)  # eksik değer senaryosu için
        mode = self.mode_at(step)
        profile = self.profiles[mode]

        self.load = LOAD_PHI * self.load + math.sqrt(1 - LOAD_PHI**2) * noise[4]
        values: dict[str, float | None] = {}
        for i, feature in enumerate(FEATURES):
            phi, coupling, tau = DYNAMICS[feature]
            self.levels[feature] += (profile.mean[feature] - self.levels[feature]) * (1 - math.exp(-self.interval_s / tau))
            self.ar[feature] = phi * self.ar[feature] + math.sqrt(1 - phi * phi) * noise[i]
            load_part = coupling * self.load if mode != "stopped" else 0.0
            mixed = load_part + math.sqrt(1 - coupling * coupling) * self.ar[feature]
            values[feature] = self.levels[feature] + profile.sd[feature] * mixed

        emitted = self._apply_scenario(step, mode, values, aux)
        if emitted is None:
            return None
        for feature in FEATURES:
            value = emitted[feature]
            if value is None:
                continue
            if feature != "temperature_c":
                value = max(0.0, value)
            emitted[feature] = round(value, ROUNDING[feature])
        if self.scenario != "freeze" or not self.effect_active(step):
            self.last_values = {f: emitted[f] for f in FEATURES}
        return {
            "machine_id": self.machine_id,
            "timestamp": self.ts_at(step),
            "operating_mode": mode,
            **{f: emitted[f] for f in FEATURES},
            "source": "simulation",
        }

    def _apply_scenario(self, step: int, mode: str, values: dict, aux) -> dict | None:
        if not self.effect_active(step):
            return values
        t_rel = (step - self.onset_step) * self.interval_s
        running = mode != "stopped"
        name = self.scenario
        if name == "vibration_ramp" and running:
            values["vibration_rms_g"] *= 1 + 1.5 * min(1.0, t_rel / 600.0)
        elif name == "temperature_ramp" and running:
            values["temperature_c"] += 12.0 * min(1.0, t_rel / 900.0)
        elif name == "power_vibration" and running:
            frac = min(1.0, t_rel / 300.0)
            values["power_kw"] *= 1 + 0.25 * frac
            values["vibration_rms_g"] *= 1 + 0.8 * frac
        elif name == "spike" and running and step == self.onset_step:
            values["vibration_rms_g"] *= 4.0
        elif name == "recovery" and running and t_rel < 480.0:
            ramp = min(1.0, t_rel / 60.0)
            values["vibration_rms_g"] *= 1 + 0.9 * ramp
            values["temperature_c"] += 5.0 * ramp
        elif name == "missing_values" and t_rel < 300.0 and aux[0] < 0.25:
            values[FEATURES[int(aux[1] * 4) % 4]] = None
        elif name == "dropout" and t_rel < 120.0:
            return None
        elif name == "freeze" and t_rel < 180.0:
            if self.frozen_values is None:
                self.frozen_values = dict(self.last_values or values)
            return dict(self.frozen_values)
        return values


def generate_records(sim: MachineSimulator, steps: int) -> list[dict]:
    """Belirtilen sayıda adım üretir (kesinti adımları kayıt üretmez)."""
    records = []
    for _ in range(steps):
        record = sim.next()
        if record is not None:
            records.append(record)
    return records


def scenario_list() -> list[dict]:
    return [{"id": key, **SCENARIOS[key]} for key in SCENARIO_ORDER]
