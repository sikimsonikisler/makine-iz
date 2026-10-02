# Makine İz — kısa değerlendirme raporu (simülasyon)

> **Önemli:** Bu sonuçlar uygulamanın kendi simülatöründen üretilen verilere aittir. Gerçek makinede arıza tahmini başarısı
> olarak yorumlanamaz. Simülatör ve analiz aynı kişi tarafından yazıldı; simülatörün gerçek makineleri ne kadar iyi temsil
> ettiği doğrulanmadı.

## Nasıl üretildi?

```bash
.venv/bin/python scripts/evaluate.py --set evaluation
```

Çıktı `reports/evaluation.json` dosyasında, her çalıştırmanın ayrıntısıyla birlikte. Aynı komut aynı sonucu verir; sabit
tohumlar kullanılır. Çalışma süresi yaklaşık 15 sn.

### Veri kümelerinin ayrımı

| Küme | Ne için | Tohumlar |
|---|---|---|
| Referans (etiketli normal geçmiş) | Her çalıştırmada referans profili yalnızca buradan oluşturulur | Kalibrasyon: 11000–11042 · Değerlendirme: 12000–12042 |
| Kalibrasyon (eşik belirleme) | Yalnızca alt sınır seçimi; ayrıntı `kalibrasyon.md` | 20000–20164 |
| Değerlendirme | Bu rapor; ayarlar sabitlendikten sonra **bir kez** çalıştırıldı | 30000–30164 |

Ayrımın kuralları:
- Değerlendirme kümesinde alt sınırlar değiştirilemez; betik bunu reddeder.
- Uygulamanın birim testleri bunlardan ayrı küçük tohumlar kullanır (7, 11–18, 41–91 gibi).
- Ayarlar, değerlendirme sonuçları görüldükten sonra değiştirilmedi.

### Düzen

- Profiller: motor, pompa, fan.
- Her profil için 5 tekrar yapıldı. Her tekrarda 11 durum çalıştırıldı:

| Durum | Çalıştırma sayısı | Süre |
|---|---|---|
| Normal çalışma, boşta | 15 | 4 sa |
| Normal çalışma, yük altında | 15 | 4 sa |
| Sağlıklı boşta ↔ yük geçişi | 15 | 2 sa (10 dakikada bir geçiş) |
| Titreşim yükselmesi | 15 | 1 sa |
| Sıcaklık yükselmesi | 15 | 1 sa |
| Güç ve titreşim birlikte | 15 | 1 sa |
| Sapma sonrası normalleşme | 15 | 1 sa |
| Tek sıçrama | 15 | 30 dk |
| Eksik ölçüm | 15 | 30 dk |
| Veri kesintisi | 15 | 30 dk |
| Donma | 15 | 30 dk |

- Toplam **165 çalıştırma**, **172.440 senaryo kaydı** (5 sn aralıkla, yaklaşık 240 sanal saat) ve **198.000 referans kaydı**.
- Her senaryo 10 dakika normal başlar, değişim sonra uygulanır.
- Analiz, uygulamadaki ile aynı yoldan geçer (`pipeline.ingest`). Senaryo adını ve değişim anını yalnızca puanlayan betik bilir.
- Ayarlar:
  - Alt sınırlar 0,01 g / 1,0 °C / 0,3 kW / 5 dev/dak.
  - Eşikler z ≥ 3 ve z ≥ 6, "5 pencerenin 3'ü" kuralı, 8 pencere z < 2 ile normale dönüş, 30 sn geçiş süresi.

## Sonuçlar

### 1. Normal çalışmada yanlış uyarı

| Ölçüt | Değer |
|---|---|
| Normal çalışma süresi | 120 makine-saat (86.310 değerlendirilen pencere) |
| Sapma uyarısı (hepsi yanlış) | **9** → **0,075 uyarı / makine-saat** (yaklaşık 13 saatte bir) |
| Profile göre | motor 1, pompa 8, fan 0 |
| Tetikleyen ölçüm | Pompa yük altında güç (6), pompa titreşim (2), motor titreşim (1) |
| Penceresinde z ≥ 3 olan payı | %0,21 (tek başına uyarı değildir; grafikte "sapma adayı" olarak işaretlenir) |
| z dağılımı | medyan 0,75 · %99'luk dilim 2,47 · %99,9'luk dilim 3,21 |

Yanlış uyarılar yük altındaki pompada yoğunlaşıyor. Pompanın normal güç dalgalanması (σ ≈ 0,35 kW) alt sınırdan büyük ve
yavaş değişiyor.

### 2. Yük geçişlerinde yanlış uyarı

| Ölçüt | Değer |
|---|---|
| Sağlıklı boşta ↔ yük geçişi | 180 geçiş (30 makine-saat) |
| Sapma uyarısı | **1** (pompa; en çok değişen güç ve devir). Yük altına geçişten 90 sn sonra açıldı, yani 30 sn'lik geçiş süresi bittikten 60 sn sonra. Bunun geçişle mi yoksa yük altındaki normal dalgalanmayla mı ilgili olduğu kesin değil. |

### 3. Sapma başlangıcından uyarıya kadar gecikme ve kaçırılan senaryolar

Gecikme, değişimin uygulandığı an ile uyarının açıldığı pencere arasındaki sanal süredir. Uyarı, değişimden sonraki 30 dk içinde
açılmadıysa senaryo "kaçırıldı" sayılır.

| Senaryo | Çalıştırma | Bulunan | Kaçırılan | Medyan gecikme | En kısa – en uzun | Değişimden önce açılan uyarı |
|---|---|---|---|---|---|---|
| Titreşim yükselmesi (10 dk'da 2,5×) | 15 | 15 | 0 | 115 sn | 35 – 145 sn | 1 |
| Sıcaklık yükselmesi (15 dk'da +12 °C) | 15 | 15 | 0 | 220 sn | 170 – 265 sn | 0 |
| Güç + titreşim birlikte | 15 | 15 | 0 | 85 sn | 50 – 160 sn | 0 |
| Sapma ve normalleşme | 15 | 15 | 0 | 30 sn | 20 – 40 sn | 0 |

- **Kaçırılan senaryo: 0 / 60.**
- Normalleşme senaryosunda 15 uyarının 15'i de etki kalktıktan sonra "Ölçümler normale döndü" oldu. Etkinin kalkmasından itibaren
  medyan süre 35 sn.
- Sayımla ilgili bir not: Değişimden önce açılmış bir uyarı hâlâ açıksa, değişim yeni uyarı açmaz, o uyarıyı günceller. Bu ölçüt
  böyle durumları "kaçırıldı" sayar (kötümser bir sayım). Bu kümede böyle bir durum olmadı.

### 4. Tek sıçrama

15 çalıştırmada sıçramanın ±5 dk çevresinde **0** sapma uyarısı açıldı. Sıçrayan nokta grafikte "z ≥ 6" olarak işaretlenir.

### 5. Veri sorunlarının makine sapması gibi gösterilmesi

"Sorun sırasında sapma uyarısı" sütunu, sorun süresi + 2 dk içinde açılan sapma uyarılarını sayar.

| Senaryo | Çalıştırma | Doğru veri sorunu uyarısı | Sorun sırasında sapma uyarısı | Başka zamanda sapma uyarısı |
|---|---|---|---|---|
| Eksik ölçüm (5 dk) | 15 | 15 / 15 ("Eksik / geçersiz ölçüm") | **0** | 0 |
| Veri kesintisi (2 dk) | 15 | 15 / 15 ("Veri gelmiyor / kesinti") | **0** | 0 |
| Donma (3 dk) | 15 | 15 / 15 ("Veri donması şüphesi") | **0** | 0 |

## Yorum ve sınırlamalar

- Simülasyondaki değişimler bilerek belirgin seçildi: %80–150 titreşim artışı ve 12 °C sıcaklık artışı. Daha küçük ve daha yavaş
  değişimler daha geç bulunur ya da hiç bulunmaz. Alt sınırlar, en küçük yakalanabilir değişimi belirler: 0,03 g, 3 °C, 0,9 kW,
  15 dev/dak.
- Yanlış uyarı oranı, simülatörün gürültü modeline sıkı sıkıya bağlıdır. Gerçek makinelerde yük, ortam sıcaklığı ve sensör
  davranışı farklı olacaktır. Oran gerçek veride yeniden ölçülmeli.
- Simülatörde mod geçişleri yaklaşık 30 sn içinde oturur. Gerçek makinelerde sıcaklık dakikalarca değişebilir. Bu durumda 30 sn'lik
  geçiş süresi yük geçişlerinde yanlış uyarı üretir; geçiş süresini makineye göre ayarlayın.
- Donma kontrolü, donmuş değer tesadüfen sapmalı olduğunda ilk 11 kayıtta bir sapma uyarısı açtırabilir. Bu kümede olmadı; kalibrasyon
  kümesinde 1 kez oldu.
- Bu testlerin geçmesi, gerçek bir makinedeki arızanın önceden tahmin edilebildiğini göstermez.
