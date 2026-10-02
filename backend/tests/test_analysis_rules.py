"""Analiz motorunun kurallarını doğrudan, elle hazırlanmış ölçümlerle sınar.

Referans: her özellikte medyan 10, 1.4826 × MAD = 1  →  z = |değer − 10|
Böylece istediğimiz z değerini doğrudan üretebiliyoruz.
"""
import numpy as np
import pytest

from makine_iz.analysis import (
    Observation,
    StreamState,
    analyze_step,
    compute_baseline_stats,
    feature_z,
)
from makine_iz.config import ANALYSIS, FEATURES

STATS = {f: {"median": 10.0, "mad": 1 / 1.4826} for f in FEATURES}
FLOORS = {f: 0.001 for f in FEATURES}
INTERVAL = 5.0
TRANSITION = 30.0


def make_obs(t, z=0.0, mode="loaded", missing=None, values=None):
    vals = dict(values) if values else {f: 10.0 for f in FEATURES}
    if values is None:
        vals["vibration_rms_g"] = 10.0 + z
    flags = []
    if missing:
        vals[missing] = None
        flags.append(f"missing:{missing}")
    return Observation(ts=1_700_000_000 + t, mode=mode, values=vals, flags=flags)


def run(sequence, state=None, baseline=STATS):
    """sequence: (zaman_sn, z) veya Observation listesi. Sonuç listesi döner."""
    state = state or StreamState()
    results = []
    for item in sequence:
        obs = item if isinstance(item, Observation) else make_obs(*item)
        results.append(analyze_step(state, obs, baseline, FLOORS, TRANSITION, INTERVAL, ANALYSIS))
    return state, results


def series(z_values, start=0):
    return [(start + i * INTERVAL, z) for i, z in enumerate(z_values)]


def deviation_events(results):
    return [(i, e) for i, r in enumerate(results) for e in r.events if e["type"] == "deviation"]


def test_z_formula_uses_median_mad_and_floor():
    stats = compute_baseline_stats({f: [1.0, 2.0, 3.0, 4.0, 100.0] for f in FEATURES})
    assert stats["rpm"]["median"] == 3.0
    assert stats["rpm"]["mad"] == 1.0  # |x-3| = 2,1,0,1,97 → medyan 1
    assert feature_z(6.0, stats["rpm"], floor=0.1) == pytest.approx(3.0 / 1.4826)
    # MAD sıfırsa alt sınır kullanılır, bölme patlamaz
    flat = compute_baseline_stats({f: [5.0] * 10 for f in FEATURES})
    assert feature_z(5.6, flat["rpm"], floor=0.3) == pytest.approx(2.0)


def test_no_alert_before_five_windows():
    _, results = run(series([4, 4, 4, 4]))
    assert deviation_events(results) == []
    _, results = run(series([4, 4, 4, 4, 4]))
    assert [i for i, _ in deviation_events(results)] == [4]


def test_three_of_last_five_rule():
    _, results = run(series([4, 0, 4, 0, 4]))
    assert [i for i, _ in deviation_events(results)] == [4]
    _, results = run(series([4, 0, 0, 4, 0, 0, 4, 0]))
    assert deviation_events(results) == []


def test_strong_level_needs_three_windows_at_six():
    _, results = run(series([7, 7, 7, 0, 0]))
    assert deviation_events(results)[0][1]["level"] == "strong"
    _, results = run(series([7, 7, 4, 4, 0]))
    assert deviation_events(results)[0][1]["level"] == "review"


def test_single_spike_is_marked_but_creates_no_alert():
    _, results = run(series([0.5] * 10 + [25] + [0.5] * 10))
    assert deviation_events(results) == []
    assert results[10].status == "strong_candidate"  # grafikte işaretlenebilir


def test_missing_value_is_not_scored_as_zero_and_resets_counters():
    seq = series([4, 4]) + [make_obs(10, missing="temperature_c")] + series([4, 4, 4, 4, 4], start=15)
    _, results = run(seq)
    invalid = results[2]
    assert invalid.status == "invalid"
    assert invalid.z is None and invalid.z_max is None and invalid.score is None
    # Eksik kayıttan sonra 5 yeni geçerli pencere dolunca uyarı (öncekiler sayılmaz)
    assert [i for i, _ in deviation_events(results)] == [7]


def test_gap_resets_counters_and_emits_gap_event():
    seq = series([4, 4, 4, 4]) + series([4], start=15 + 3 * INTERVAL + 1)
    _, results = run(seq)
    assert deviation_events(results) == []
    assert any(e["type"] == "gap" for e in results[4].events)
    assert "after_gap" in results[4].flags


def test_mode_change_starts_transition_without_alerts():
    seq = series([0] * 5) + [make_obs(25 + i * INTERVAL, z=8, mode="idle") for i in range(11)]
    state, results = run(seq)
    statuses = [r.status for r in results[5:]]
    # 30 sn geçiş: 25, 30, 35, 40, 45, 50 sn → 6 kayıt geçiş
    assert statuses[:6] == ["transition"] * 6
    assert all(r.z is not None for r in results[5:11])  # grafikte gösterilir
    events = deviation_events(results)
    assert events and events[0][0] == 15  # geçişten sonra 5 geçerli pencere dolunca


def test_out_of_order_and_duplicate_timestamps_do_not_count():
    clean = series([4, 0, 4, 0, 4])
    noisy = clean[:2] + [(0, 30)] + clean[2:4] + [(-100, 30)] + clean[4:]
    _, clean_results = run(clean)
    _, noisy_results = run(noisy)
    assert [r.status for r in noisy_results if r.status == "out_of_order"] == ["out_of_order"] * 2
    assert len(deviation_events(clean_results)) == len(deviation_events(noisy_results)) == 1
    assert deviation_events(noisy_results)[0][1]["hits"] == 3


def test_normal_streak_after_eight_windows_below_two():
    state, results = run(series([4, 4, 4, 4, 4] + [1.5] * 7))
    assert not any(e["type"] == "normal_streak" for r in results for e in r.events)
    _, more = run(series([1.5], start=1000), state=state)
    # Not: start=1000 bir kesinti yaratır; kesinti sayaçları sıfırladığı için normalleşme olmaz
    assert not any(e["type"] == "normal_streak" for e in more[0].events)
    state, results = run(series([4, 4, 4, 4, 4] + [1.5] * 8))
    assert any(e["type"] == "normal_streak" for e in results[-1].events)


def test_freeze_detection_after_twelve_identical_records():
    values = {f: 10.2 for f in FEATURES}
    seq = [make_obs(i * INTERVAL, values=values) for i in range(14)]
    seq.append(make_obs(14 * INTERVAL, z=0.3))
    _, results = run(seq)
    assert [r.status for r in results[:11]] == ["normal"] * 11
    assert results[11].status == "frozen_suspect"
    assert any(e["type"] == "frozen_start" for e in results[11].events)
    assert any(e["type"] == "frozen_end" for e in results[14].events)


def test_stopped_machine_is_not_compared_with_running_profile():
    _, results = run([make_obs(0, z=9, mode="stopped")])
    assert results[0].status == "stopped"
    assert results[0].z is None


def test_no_baseline_means_no_score():
    _, results = run(series([9, 9, 9, 9, 9]), baseline=None)
    assert {r.status for r in results} == {"no_baseline"}
    assert deviation_events(results) == []


def test_baseline_stats_are_robust_to_outliers():
    rng = np.random.default_rng(0)
    data = rng.normal(5, 1, 500).tolist() + [500.0] * 10
    stats = compute_baseline_stats({f: data for f in FEATURES})
    assert stats["rpm"]["median"] == pytest.approx(5, abs=0.2)
    assert stats["rpm"]["mad"] * 1.4826 == pytest.approx(1, abs=0.15)
