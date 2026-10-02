"""Analiz motoru (saf mantık).

Bu modül veritabanını, simülatörü, senaryo adlarını veya ekranları BİLMEZ.
Kullandığı tek girdiler: ölçüm değerleri, çalışma modu, zaman damgası, makine ayarları
ve aynı makinenin aynı çalışma modundaki referans profili.

Yöntem (açıklanabilir istatistik):
    z = |ölçüm - medyan| / max(1.4826 × MAD, feature_floor)
    pencerenin sapma değeri = dört özelliğin z değerlerinin en büyüğü
    sapma puanı = min(100, 10 × en büyük z)   (arıza olasılığı DEĞİLDİR)

Süreklilik kuralı:
    son 5 ardışık geçerli pencerenin en az 3'ünde z ≥ 3  → inceleme uyarısı
    son 5 ardışık geçerli pencerenin en az 3'ünde z ≥ 6  → "Belirgin sapma"
    8 ardışık geçerli pencerede z < 2                    → "Ölçümler normale döndü"
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from .config import ANALYSIS, FEATURE_LABELS, FEATURE_UNITS, FEATURES, RUNNING_MODES, AnalysisConfig
from .validation import is_invalid


# ---------------------------------------------------------------------------
# Referans profili
# ---------------------------------------------------------------------------
def compute_baseline_stats(samples: dict[str, list[float]], cfg: AnalysisConfig = ANALYSIS) -> dict:
    """Her özellik için medyan ve MAD (medyan mutlak sapması) hesaplar."""
    stats: dict[str, dict[str, float]] = {}
    for feature in FEATURES:
        values = np.asarray(samples[feature], dtype=float)
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        stats[feature] = {
            "median": median,
            "mad": mad,
            "robust_sd": cfg.mad_scale * mad,
            "p05": float(np.percentile(values, 5)),
            "p95": float(np.percentile(values, 95)),
            "min": float(values.min()),
            "max": float(values.max()),
        }
    return stats


def z_scale(stat: dict, floor: float, cfg: AnalysisConfig = ANALYSIS) -> float:
    """z hesabındaki payda: max(1.4826 × MAD, feature_floor)."""
    return max(cfg.mad_scale * stat["mad"], floor)


def feature_z(value: float, stat: dict, floor: float, cfg: AnalysisConfig = ANALYSIS) -> float:
    return abs(value - stat["median"]) / z_scale(stat, floor, cfg)


def deviation_score(z_max: float) -> float:
    """0–100 arası "Sapma puanı". Arıza olasılığı veya sağlık yüzdesi değildir."""
    return min(100.0, 10.0 * z_max)


# ---------------------------------------------------------------------------
# Akış durumu (makine başına; veritabanında saklanır, yeniden başlatmada korunur)
# ---------------------------------------------------------------------------
@dataclass
class StreamState:
    last_ts: float | None = None  # sırayla işlenmiş son kaydın zamanı
    last_mode: str | None = None
    transition_until: float | None = None
    windows: list[dict] = field(default_factory=list)  # son (en fazla 5) geçerli pencere
    normal_streak: int = 0  # ardışık z < 2 pencere sayısı
    good_streak: int = 0  # ardışık geçerli kayıt sayısı (veri sorunu kapanışı için)
    seq_clean: int = 0  # son yinelenen/sırası bozuk kayıttan beri sağlam kayıt sayısı
    last_values: list | None = None  # donma kontrolü için önceki değerler
    same_count: int = 0
    same_since: float | None = None
    frozen: bool = False
    last_status: str | None = None
    last_z: dict | None = None
    last_z_max: float | None = None

    def reset_persistence(self) -> None:
        """Süreklilik sayaçlarını temizler (kesinti, geçersiz veri, mod değişimi, durma...)."""
        self.windows = []
        self.normal_streak = 0

    def reset_freeze(self) -> None:
        self.last_values = None
        self.same_count = 0
        self.same_since = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "StreamState":
        known = {k: v for k, v in (data or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


@dataclass
class Observation:
    ts: float
    mode: str | None  # analizde kullanılacak mod (geçersizse None)
    values: dict[str, float | None]
    flags: list[str]


@dataclass
class StepResult:
    status: str
    z: dict[str, float] | None
    z_max: float | None
    score: float | None
    flags: list[str]
    events: list[dict]
    counted: bool  # pencere süreklilik hesabına girdi mi


def candidate_status(z_max: float, cfg: AnalysisConfig = ANALYSIS) -> str:
    if z_max >= cfg.z_strong:
        return "strong_candidate"
    if z_max >= cfg.z_candidate:
        return "candidate"
    return "normal"


def summarize_windows(windows: list[dict], stats: dict, floors: dict, cfg: AnalysisConfig = ANALYSIS) -> dict:
    """Uyarı açıklaması için: hangi ölçüm ne kadar değişti? (en çok değişen önce)"""
    latest = windows[-1]
    features = []
    for feature in FEATURES:
        z_values = [w["z"][feature] for w in windows]
        value = latest["values"][feature]
        median = stats[feature]["median"]
        diff = value - median
        features.append(
            {
                "feature": feature,
                "label": FEATURE_LABELS[feature],
                "unit": FEATURE_UNITS[feature],
                "value": value,
                "median": median,
                "mad": stats[feature]["mad"],
                "scale": z_scale(stats[feature], floors[feature], cfg),
                "diff": diff,
                "diff_pct": (diff / median * 100.0) if abs(median) > 1e-9 else None,
                "z": latest["z"][feature],
                "mean_z": float(np.mean(z_values)),
                "max_z": float(np.max(z_values)),
            }
        )
    features.sort(key=lambda item: item["mean_z"], reverse=True)
    return {
        "features": features,
        "top": [item["feature"] for item in features[:2]],
        "window_ts": [w["ts"] for w in windows],
        "window_z": [w["z_max"] for w in windows],
    }


# ---------------------------------------------------------------------------
# Tek adım: bir ölçüm penceresini işle
# ---------------------------------------------------------------------------
def analyze_step(
    state: StreamState,
    obs: Observation,
    baseline_stats: dict | None,
    floors: dict,
    transition_s: float,
    interval_s: float,
    cfg: AnalysisConfig = ANALYSIS,
) -> StepResult:
    """Bir ölçümü işler; durumu yerinde günceller, sonucu ve olayları döndürür.

    Olay türleri (servis katmanı bunları uyarılara çevirir):
      sequence      → sırası bozuk kayıt
      gap           → beklenen aralığın 3 katından uzun kesinti
      mode_change   → çalışma modu değişti
      interrupt     → açık sapma uyarıları artık değerlendirilemiyor (neden ile)
      invalid       → eksik / geçersiz ölçüm
      frozen_start / frozen_end → veri donması şüphesi başladı / bitti
      valid         → sağlam kayıt (veri sorunu uyarısını kapatmak için sayaçlar)
      deviation     → süreklilik kuralı sağlandı (seviye ile)
      normal_streak → 8 ardışık z < 2
    """
    flags = list(obs.flags)
    events: list[dict] = []

    # 1) Sıra kontrolü: daha önce işlenmiş son kayıttan eski kayıt sayaçlara girmez.
    if state.last_ts is not None and obs.ts <= state.last_ts:
        flags.append("out_of_order")
        state.seq_clean = 0
        events.append({"type": "sequence", "reason": "out_of_order"})
        return StepResult("out_of_order", None, None, None, flags, events, False)

    # 2) Kesinti: 3 beklenen aralıktan uzun boşluk → sayaçlar sıfırlanır.
    if state.last_ts is not None and obs.ts - state.last_ts > cfg.gap_factor * interval_s:
        flags.append("after_gap")
        events.append({"type": "gap", "from_ts": state.last_ts, "to_ts": obs.ts})
        events.append({"type": "interrupt", "reason": "gap"})
        state.reset_persistence()
        state.reset_freeze()
    state.last_ts = obs.ts

    # 3) Mod değişimi: sayaçlar sıfırlanır, geçiş süresi başlar.
    mode = obs.mode
    if mode is not None and mode != state.last_mode:
        if state.last_mode is not None:
            events.append({"type": "mode_change", "from": state.last_mode, "to": mode})
            events.append({"type": "interrupt", "reason": "mode_change"})
            state.transition_until = obs.ts + transition_s
        state.last_mode = mode
        state.reset_persistence()
        state.reset_freeze()

    # 4) Geçersiz / eksik ölçüm: puan hesaplanmaz (sıfır kabul edilmez), sayaçlar sıfırlanır.
    if mode is None or is_invalid(flags):
        state.reset_persistence()
        state.reset_freeze()
        state.good_streak = 0
        events.append({"type": "invalid", "flags": [f for f in flags if not f.startswith("upstream:")]})
        events.append({"type": "interrupt", "reason": "invalid"})
        _remember(state, "invalid", None, None)
        return StepResult("invalid", None, None, None, flags, events, False)

    values: dict[str, float] = obs.values  # type: ignore[assignment]

    # 5) Veri donması şüphesi (yalnızca çalışan makinede): 12 ardışık kayıt birebir aynı.
    if mode in RUNNING_MODES:
        current = [values[f] for f in FEATURES]
        if state.last_values is not None and current == state.last_values:
            state.same_count += 1
        else:
            state.same_count = 1
            state.same_since = obs.ts
        state.last_values = current
        if state.same_count >= cfg.freeze_count:
            flags.append("frozen_suspect")
            if not state.frozen:
                state.frozen = True
                events.append({"type": "frozen_start", "since": state.same_since, "count": state.same_count})
            state.reset_persistence()
            state.good_streak = 0
            events.append({"type": "interrupt", "reason": "frozen"})
            _remember(state, "frozen_suspect", None, None)
            return StepResult("frozen_suspect", None, None, None, flags, events, False)
        if state.frozen:
            state.frozen = False
            events.append({"type": "frozen_end"})
    else:
        state.reset_freeze()
        if state.frozen:
            state.frozen = False
            events.append({"type": "frozen_end"})

    state.good_streak += 1
    state.seq_clean += 1
    events.append({"type": "valid", "good_streak": state.good_streak, "seq_clean": state.seq_clean})

    # 6) Durmuş makine: çalışan makine profiliyle karşılaştırılmaz.
    if mode == "stopped":
        state.reset_persistence()
        events.append({"type": "interrupt", "reason": "stopped"})
        _remember(state, "stopped", None, None)
        return StepResult("stopped", None, None, None, flags, events, False)

    z: dict[str, float] | None = None
    z_max: float | None = None
    score: float | None = None
    if baseline_stats is not None:
        z = {f: feature_z(values[f], baseline_stats[f], floors[f], cfg) for f in FEATURES}
        z_max = max(z.values())
        score = deviation_score(z_max)

    # 7) Geçiş süresi: grafik için z gösterilir ama yeni sapma uyarısı üretilmez.
    if state.transition_until is not None and obs.ts < state.transition_until:
        _remember(state, "transition", z, z_max)
        return StepResult("transition", z, z_max, score, flags, events, False)

    # 8) Referans yoksa karşılaştırma yapılmaz.
    if baseline_stats is None or z is None or z_max is None:
        state.reset_persistence()
        events.append({"type": "interrupt", "reason": "no_baseline"})
        _remember(state, "no_baseline", None, None)
        return StepResult("no_baseline", None, None, None, flags, events, False)

    # 9) Süreklilik değerlendirmesi
    state.windows.append({"ts": obs.ts, "z": z, "values": dict(values), "z_max": z_max})
    state.windows = state.windows[-cfg.window_count :]
    state.normal_streak = state.normal_streak + 1 if z_max < cfg.z_normal else 0
    status = candidate_status(z_max, cfg)

    if len(state.windows) == cfg.window_count:
        hits = sum(1 for w in state.windows if w["z_max"] >= cfg.z_candidate)
        strong_hits = sum(1 for w in state.windows if w["z_max"] >= cfg.z_strong)
        if hits >= cfg.min_hits:
            first_hit_ts = next(w["ts"] for w in state.windows if w["z_max"] >= cfg.z_candidate)
            events.append(
                {
                    "type": "deviation",
                    "level": "strong" if strong_hits >= cfg.min_hits else "review",
                    "hits": hits,
                    "strong_hits": strong_hits,
                    "window_count": cfg.window_count,
                    "first_hit_ts": first_hit_ts,
                    "summary": summarize_windows(state.windows, baseline_stats, floors, cfg),
                }
            )
    if state.normal_streak == cfg.normal_streak:
        events.append({"type": "normal_streak", "count": state.normal_streak})

    _remember(state, status, z, z_max)
    return StepResult(status, z, z_max, score, flags, events, True)


def _remember(state: StreamState, status: str, z: dict | None, z_max: float | None) -> None:
    state.last_status = status
    state.last_z = z
    state.last_z_max = z_max


def latest_change_summary(z: dict[str, float] | None, values: dict[str, Any], stats: dict | None) -> list[dict]:
    """Makine ayrıntısı için: son pencerede en çok değişen ölçümler."""
    if not z or not stats:
        return []
    items = []
    for feature in FEATURES:
        value = values.get(feature)
        median = stats[feature]["median"]
        items.append(
            {
                "feature": feature,
                "label": FEATURE_LABELS[feature],
                "unit": FEATURE_UNITS[feature],
                "value": value,
                "median": median,
                "diff": (value - median) if value is not None else None,
                "z": z[feature],
            }
        )
    items.sort(key=lambda item: item["z"], reverse=True)
    return items
