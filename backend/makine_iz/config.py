"""Makine İz genel ayarları.

Buradaki eşikler ve alt sınırlar PROTOTİP / DEMO değerleridir.
Gerçek makinelerde doğrulanmış endüstriyel güvenlik sınırları DEĞİLDİR.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = Path(os.environ.get("MAKINE_IZ_DB", str(PROJECT_ROOT / "data" / "makine_iz.db")))
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"
SAMPLES_DIR = PROJECT_ROOT / "samples"

# Dört ölçüm özelliği ve birimleri
FEATURES = ("vibration_rms_g", "temperature_c", "power_kw", "rpm")
FEATURE_LABELS = {
    "vibration_rms_g": "Titreşim RMS",
    "temperature_c": "Sıcaklık",
    "power_kw": "Elektrik gücü",
    "rpm": "Devir",
}
FEATURE_UNITS = {"vibration_rms_g": "g", "temperature_c": "°C", "power_kw": "kW", "rpm": "dev/dak"}
# Negatif olamayacak ölçümler (sıcaklık negatif olabilir)
NON_NEGATIVE = ("vibration_rms_g", "power_kw", "rpm")

# Çalışma modları: makineyi yalnızca aynı moddaki referansıyla karşılaştırırız
MODES = ("stopped", "idle", "loaded")
RUNNING_MODES = ("idle", "loaded")
MODE_LABELS = {"stopped": "Durmuş", "idle": "Boşta", "loaded": "Yük altında"}

# Veri kaynakları
SOURCES = ("simulation", "csv", "sensor")
LIVE_SOURCES = ("simulation", "sensor")
SOURCE_LABELS = {"simulation": "Simülasyon", "csv": "CSV aktarımı", "sensor": "Sensör"}

# feature_floor: MAD sıfır ya da çok küçük olduğunda bölmenin aşırı büyümesini önleyen alt sınır.
# Özelliğin kendi birimindedir. z ≥ 3 için gereken en küçük fark = 3 × alt sınır olduğundan,
# alt sınır "bu birimde anlamlı sayılacak en küçük değişimin üçte biri" gibi düşünülebilir.
# Değerler, yalnızca KALİBRASYON simülasyon verisine bakılarak seçildi (bkz. reports/kalibrasyon.md);
# değerlendirme verisi bu seçimden sonra bir kez çalıştırıldı. Demo değerleridir, endüstriyel güvenlik
# sınırı değildir. Küçük makinelerde (ör. 1 kW altı) güç alt sınırını makine ayarından küçültün.
DEFAULT_FEATURE_FLOORS = {
    "vibration_rms_g": 0.01,  # g     → en az 0,03 g değişim
    "temperature_c": 1.0,  # °C    → en az 3 °C değişim
    "power_kw": 0.3,  # kW    → en az 0,9 kW değişim
    "rpm": 5.0,  # dev/dak → en az 15 dev/dak değişim
}

# Beklenen (makul) ölçüm aralığı: bunun dışındaki değerler "geçersiz" işaretlenir, sıfıra çevrilmez.
DEFAULT_RANGES = {
    "vibration_rms_g": [0.0, 50.0],
    "temperature_c": [-40.0, 200.0],
    "power_kw": [0.0, 5000.0],
    "rpm": [0.0, 60000.0],
}

DEFAULT_INTERVAL_S = 5.0  # beklenen ölçüm aralığı (sn)
DEFAULT_TRANSITION_S = 30.0  # mod değişiminden sonraki geçiş süresi (sn)


@dataclass(frozen=True)
class AnalysisConfig:
    z_candidate: float = 3.0  # z ≥ 3: sapma adayı
    z_strong: float = 6.0  # z ≥ 6: belirgin sapma adayı
    z_normal: float = 2.0  # normale dönüş için z < 2
    window_count: int = 5  # son 5 ardışık geçerli pencere
    min_hits: int = 3  # bunların en az 3'ünde eşik aşımı → uyarı
    normal_streak: int = 8  # 8 ardışık geçerli pencerede z < 2 → "Ölçümler normale döndü"
    freeze_count: int = 12  # 12 ardışık birebir aynı kayıt → "Veri donması şüphesi"
    gap_factor: float = 3.0  # 3 beklenen aralık boyunca kayıt yoksa → veri kesintisi
    min_baseline_samples: int = 120  # referans için en az geçerli kayıt
    mad_scale: float = 1.4826  # MAD → normal dağılımda standart sapma karşılığı
    dq_recovery: int = 24  # veri sorunu uyarısının kapanması için ardışık sağlam kayıt (5 sn'de 2 dk)

    def as_dict(self) -> dict:
        return asdict(self)


ANALYSIS = AnalysisConfig()
