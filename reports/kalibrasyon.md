# Kalibrasyon notu: alt sınır (feature_floor) seçimi

> Bu notta yalnızca **kalibrasyon (eşik belirleme) verisi** kullanıldı. Değerlendirme verisi bu karar verildikten
> sonra bir kez çalıştırıldı. Sonuçlar simülasyona aittir.

## Neyi değiştirmek serbestti, neyi değil?

- **Sabit (görev tanımından):** z eşikleri (3 ve 6), "son 5 pencerenin en az 3'ü" kuralı, 8 pencerelik normale dönüş
  kuralı, 30 sn geçiş süresi, en az 120 kayıtlık referans ve 12 kayıtlık donma kontrolü. Bunlara dokunulmadı.
- **Ayarlanabilir:** Her ölçümün kendi birimindeki alt sınırı (feature_floor). Görev tanımı bu değerlerin
  "belgelenerek seçilmesini" istiyor.

## Veri

- Komut: `.venv/bin/python scripts/evaluate.py --set calibration [--floors '{…}']`
- Referans tohumları: 11000–11042 (`11000 + tekrar×10 + profil`).
- Çalıştırma tohumları: 20000–20164.
- 165 çalıştırma yapıldı: 3 profil (motor, pompa, fan) × 11 durum × 5 tekrar.
  - Normal çalışma 120 saat, yük geçişi 30 saat, sapma senaryoları 60 saat, sıçrama ve veri sorunları 30 saat.
  - Toplam 172.440 senaryo kaydı ve 198.000 referans kaydı kullanıldı.

## Denemeler

| Deneme | Alt sınırlar (g / °C / kW / dev/dak) | Normalde yanlış uyarı / saat | Yük geçişinde yanlış uyarı | Kaçırılan senaryo | Medyan tespit gecikmesi (titreşim / sıcaklık / güç+titreşim) |
|---|---|---|---|---|---|
| Başlangıç (çözünürlük temelli) | 0,005 / 0,3 / 0,05 / 3 | 0,475 (57 / 120 sa) | 22 / 180 geçiş | 2 | 90 / 133 / 80 sn |
| Deneme 1 | 0,005 / 0,8 / 0,05 / 3 | 0,242 | 15 / 180 | 2 | 90 / 183 / 80 sn |
| Deneme 2 | 0,005 / 0,8 / 0,3 / 3 | 0,108 | 5 / 180 | 0 | 90 / 180 / 80 sn |
| **Deneme 3 (seçilen)** | **0,01 / 1,0 / 0,3 / 5** | **0,075** | **5 / 180** | **0** | **110 / 240 / 95 sn** |

Ayrıntılı sayılar `kalibrasyon_denemeleri.json`, seçilen ayarın tam çıktısı `calibration.json` dosyasındadır.

## Karar ve gerekçe

İlk alt sınırlar, ölçüm çözünürlüğünün birkaç katı olacak şekilde seçilmişti. Bu değerlerle yanlış uyarıların çoğu sıcaklık ve
yük altındaki güçten geldi. Simülatörde bu iki ölçüm yükle birlikte yavaşça dalgalanıyor. Bu yüzden z = 3 sınırını aşan
pencereler art arda geliyor ve "5'te 3" kuralı tek başına koruma sağlamıyor.

Alt sınırları "anlamlı en küçük değişimin üçte biri" olacak şekilde büyüttüm. z ≥ 3 için gereken en küçük değişimler şöyle oldu:
- titreşim 0,03 g
- sıcaklık 3 °C
- güç 0,9 kW
- devir 15 dev/dak

Bunun karşılığında yanlış uyarı oranı yaklaşık 6 kat azaldı. Kaçırılan senaryo kalmadı, ama tespit 20–100 sn kadar gecikti.

Bilerek kabul edilen bir bedel var: Güç alt sınırı (0,3 kW) bütün makineler için aynı. Bu yüzden küçük makinelerde güçteki küçük
değişimleri görünmez kılar. Örneğin demo fanı yük altında yaklaşık 3,2 kW çekiyor ve %28'in altındaki güç değişimlerini
görmüyor. Alt sınırlar makine ayarından değiştirilebilir. README bunu belirtiyor.

Bundan sonra başka ayar yapılmadı. Daha fazla ayar, kalibrasyon verisine aşırı uydurma riski taşırdı.
