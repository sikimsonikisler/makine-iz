# Makine İz

Eski makinelerin çalışma davranışını izleyen ilk sürüm (prototip). Uygulama şunları yapar:
- Titreşim RMS, sıcaklık, elektrik gücü ve devir ölçümlerini makinenin **aynı çalışma modundaki** referans davranışıyla
  karşılaştırır.
- Süreklilik gösteren sapmaları işaretler ve hangi ölçümlerin değiştiğini açıklar.
- Veri kalitesi sorunlarını (eksik, donmuş, gelmeyen veri) sapmadan **ayrı** gösterir.

Uygulama yerel bilgisayarda çalışır. Kullanıcı hesabı, ücretli servis veya haricî yapay zekâ API'si gerekmez. Gerçek makine
olmadan denenebilsin diye kendi **veri simülatörü** vardır. İleride gerçek sensörlerden veri alabilmek için bir **veri arayüzü**
(HTTP API) de bulunur.

> **Bu sürüm ne değildir:** Kesin arıza teşhisi, kalan ömür tahmini veya otomatik makine kontrolü yapmaz. Bir ölçüm
> sapmasını belirli bir mekanik arızanın kanıtı olarak sunmaz. "Sapma puanı" arıza olasılığı veya sağlık yüzdesi değildir.
> Ham titreşim, FFT veya rulman kusur frekansı analizi yapmaz. Eşikler demo değerleridir ve gerçek makinelerde doğrulanmamıştır.

---

## 1. Gereksinimler

- macOS veya Linux (Windows'ta komutları elle çalıştırmak gerekir; bkz. bölüm 3).
- **Python 3.11 veya üstü.** Python 3.12 ile denendi.
- **Node.js 18 veya üstü** ve npm. Node 24 ile denendi. Yalnızca ön yüzü derlemek için gerekir.
- Docker gerekmez.

## 2. Kurulum (bir kez)

```bash
cd ~/Desktop/makine-iz
./kurulum.sh
```

Betik şunları yapar:
1. `.venv` adlı bir Python sanal ortamı oluşturur.
2. `requirements.lock.txt` dosyasındaki **sürümü kilitli** paketleri yalnızca `https://pypi.org` adresinden kurar. Ana paketler:
   FastAPI 0.115.12, Uvicorn 0.34.2, NumPy 2.3.5, pytest 8.4.2, httpx 0.28.1.
3. Ön yüz paketlerini `frontend/package-lock.json` dosyasına göre yalnızca `https://registry.npmjs.org` adresinden kurar.
   Ana paketler: React 19.1.0, Recharts 2.15.3, Vite 6.3.5, TypeScript 5.8.3.
4. Ön yüzü derler (`frontend/dist`).

## 3. Çalıştırma

```bash
./baslat.sh
```

Sonra tarayıcıda **http://127.0.0.1:8000** adresini açın. Durdurmak için terminalde `Ctrl+C` tuşlarına basın.

İlk açılışta uygulama şunları yapar:
- Üç demo makinesi oluşturur: **Demo Motor M-1**, **Demo Pompa P-1**, **Demo Fan F-1**.
- Her biri için açıkça etiketlenmiş 100 dakikalık **normal demo geçmişi** üretir.
- Bu geçmişten "Boşta" ve "Yük altında" referanslarını oluşturur.
- Üç makinede "Normal çalışma" simülasyonunu 1× hızda başlatır.

Veriler `data/makine_iz.db` dosyasında (SQLite) saklanır.

Elle çalıştırmak isterseniz (ör. Windows):

```bash
cd backend
../.venv/bin/python -m uvicorn --factory makine_iz.api:create_app --host 127.0.0.1 --port 8000
```

Ön yüzde geliştirme yapıyorsanız arka uç çalışırken `cd frontend && npm run dev` komutunu verin. Sayfa
http://127.0.0.1:5173 adresinde açılır; `/api` istekleri 8000 portuna yönlendirilir.

## 4. Beş dakikalık deneme turu

1. **Genel görünüm:** Üç demo makinesi "SİMÜLASYON" etiketiyle görünür. Sayaçlar kayıtlı makineleri, referansa uygun
   çalışanları, inceleme gerektirenleri ve veri sorunu olanları gösterir.
2. **Simülasyon laboratuvarı:**
   - "Demo Motor M-1" seçili haldeyken "Kademeli titreşim yükselmesi" senaryosunu **20×** hızda başlatın.
   - Yaklaşık 15–20 saniye içinde "Analizin gördüğü" bölümünde "Belirgin sapma — inceleme gerekli" görünür. Grafikte z ≥ 3
     noktaları turuncu, z ≥ 6 noktaları kırmızı işaretlenir.
3. **Uyarılar → Ayrıntı:**
   - Tetikleyen ölçümleri, referanstan farkı, kullanılan referans sürümünü ve açıklamayı görün.
   - İnceleme durumunu ve değerlendirmeyi kaydedin, not ekleyin.
4. **Simülasyon laboratuvarı → "Etkiyi kaldır" → "+5 dk":** Uyarının ölçüm durumu "Ölçümler normale döndü" olur. Sizin inceleme
   kaydınız değişmez.
5. **Veri kesintisi:** "Veri akışının kesilmesi" senaryosunu başlatın. Kesinti sırasında makine "Veri gelmiyor" görünür.
   Bu bir **veri sorunu** uyarısıdır, sapma değil.
6. **Veri aktarımı (CSV):**
   1. `ornek_referans.csv` dosyasını "yeni makine olarak ekle" seçeneğiyle aktarın.
   2. `ornek-kompresor` makine sayfasında "Tümü" aralığını seçin.
   3. "Grafikteki aralığı kullan" → "Aralığı kontrol et" → onay kutusu → "Referansı oluştur" adımlarıyla önce Yük altında, sonra
      Boşta modu için referans oluşturun.
   4. `ornek_izleme.csv` dosyasını aktarın. Titreşim yükselmesi uyarıya dönüşür. Eksik ölçüm işaretlenir, yinelenen satır atlanır.
   5. `ornek_hatali.csv` dosyası hataların satır ve alan adıyla nasıl gösterildiğini dener.

## 5. Ekranlar

| Ekran | İçerik |
|---|---|
| Genel görünüm | Sayaçlar, makine kartları (ad, tür, mod, veri kaynağı, son ölçüm, durum, sapma puanı), son uyarılar |
| Makine ayrıntısı | Bilgiler, güncel mod ve değerler, sapma ölçüsü ve açıklaması, ayrı ve birimli zaman grafikleri, zaman filtresi, referans oluşturma, uyarı geçmişi, notlar, makine ayarları |
| Uyarılar | Makine, tarih, uyarı düzeyi, inceleme ve ölçüm durumuna göre filtre; CSV dışa aktarım |
| Uyarı ayrıntısı | Başlangıç ve son güncelleme, makine ve mod, tetikleyen ölçümler ve referanstan farkı, referans sürümü, inceleme durumu, değerlendirme, notlar |
| Simülasyon laboratuvarı | Makine seçimi; senaryo başlatma, duraklatma, hızlandırma (1/5/20/60×), ileri sarma, mod değiştirme, etkiyi kaldırma; demo sıfırlama |
| Veri aktarımı | CSV biçimi, örnek indirme, yükleme, doğrulama, önizleme, aktarım özeti, dışa aktarım, sensör API'si örneği |
| Makineler | Makine ekleme ve düzenleme: modlar, beklenen ölçüm aralığı, ölçüm aralığı süresi, geçiş süresi, alt sınırlar |
| Yöntem | Analiz yöntemi, eşikler ve sınırlamalar |

Zamanlar veritabanında UTC olarak saklanır, arayüzde **Europe/Istanbul** saatiyle gösterilir. Simülasyonda gösterilen zaman
**sanal zamandır**. Bu yüzden hızlandırınca gerçek saatin önüne geçebilir.

Durumlar yalnızca renkle anlatılmaz; her durumda simge ve metin de vardır. Ölçüm birimleri her yerde yazılıdır.

## 6. Veri biçimi

### Ölçüm alanları

| Alan | Anlam |
|---|---|
| `machine_id` | Makine kimliği |
| `timestamp` | Ölçüm penceresinin **bitiş** zamanı (ISO 8601; saat dilimi yoksa Europe/Istanbul kabul edilir) |
| `operating_mode` | `stopped`, `idle` veya `loaded` |
| `vibration_rms_g` | Veri toplama katmanında **önceden hesaplanmış** titreşim RMS özeti (g). 5 sn'de bir özet almak, ham titreşimin 5 sn'de bir örneklenmesi demek değildir. |
| `temperature_c` | Sıcaklık (°C) |
| `power_kw` | Elektrik gücü (kW) |
| `rpm` | Devir (dev/dak) |
| `source` | `simulation`, `csv` veya `sensor` (uygulama atar) |
| `quality_flags` | Eksiklik ve doğrulama işaretleri (uygulama hesaplar) |

### CSV kuralları

- İlk satır başlıktır. Ayraç virgül (`,`) veya noktalı virgül (`;`) olabilir. Noktalı virgüllü dosyada ondalık virgül (`0,15`)
  kabul edilir.
- Dosya **önce doğrulanır.** Hata varsa (eksik sütun, okunamayan zaman, geçersiz mod, sayısal olmayan değer, bilinmeyen makine)
  **hiçbir satır aktarılmaz**. Hatalar satır numarası ve alan adıyla listelenir. Satır 1 başlık satırıdır.
- Boş ölçüm hücresi, negatif RMS/güç/devir veya beklenen aralık dışı değer hata değil **uyarıdır**. Satır aktarılır, kayıt geçersiz
  işaretlenir, değer sıfıra çevrilmez.
- **Yinelenen kayıt politikası:** Aynı makine + aynı zaman damgası olan kayıtlarda ilk kayıt korunur. Sonrakiler (dosya içinde veya
  veritabanında zaten varsa) atlanır ve özette sayılır.
- Satırlar her makine için zaman sırasına göre işlenir. Makinenin mevcut son kaydından eski satırlar "sırası bozuk" işaretlenir ve
  süreklilik hesabına alınmaz.
- Örnek dosyalar `samples/` klasöründedir: `sablon.csv`, `ornek_referans.csv`, `ornek_izleme.csv`, `ornek_hatali.csv`. Yeniden
  üretmek için `.venv/bin/python scripts/make_samples.py` komutunu çalıştırın.

### Gerçek sensörler için API

```bash
curl -X POST http://127.0.0.1:8000/api/telemetry -H 'Content-Type: application/json' -d '{
  "records": [{"machine_id": "kompresor-1", "timestamp": "2026-10-02T14:30:05+03:00",
               "operating_mode": "loaded", "vibration_rms_g": 0.181, "temperature_c": 67.9,
               "power_kw": 22.1, "rpm": 2941}]}'
```

Simülasyon, CSV ve sensör verisi **aynı doğrulama ve analiz yolundan** geçer (`backend/makine_iz/pipeline.py`). Sensör
gönderiminde geçerli kayıtlar saklanır, reddedilenler nedeniyle birlikte yanıtta döner.

## 7. Analiz yöntemi

### Referans

- Her makine ve çalışan mod (Boşta, Yük altında) için ayrı referans vardır.
- Referans, kullanıcının **"normal çalışma olarak kabul ediyorum"** diyerek seçtiği aralıktan hesaplanır ve en az **120 geçerli
  kayıt** gerektirir. Yeterli kayıt yoksa "Referans için veri yetersiz" gösterilir.
- Her ölçüm için **medyan** ve **MAD** saklanır. Ayrıca oluşturulma zamanı, veri aralığı, örnek sayısı ve sürüm de kaydedilir.
- Geçersiz, sırası bozuk, donmuş ve geçiş süresindeki kayıtlar referansa katılmaz.
- Referans, gelen ölçümlerle **otomatik güncellenmez**.
- Yeni sürüm oluşturulunca eski uyarılar kendi sürümünü korur.
- Durmuş makine için referans oluşturulmaz.

### Sapma

```
z = |ölçüm − medyan| / max(1.4826 × MAD, alt_sınır)
pencerenin sapma değeri = dört ölçümün z değerlerinin en büyüğü
sapma puanı = min(100, 10 × en büyük z)
```

**Alt sınırlar** (feature_floor, ölçümün kendi biriminde, makine ayarından değiştirilebilir):

| Ölçüm | Alt sınır | z ≥ 3 için en az değişim |
|---|---|---|
| Titreşim | 0,01 g | 0,03 g |
| Sıcaklık | 1,0 °C | 3 °C |
| Güç | 0,3 kW | 0,9 kW |
| Devir | 5 dev/dak | 15 dev/dak |

Bu değerler yalnızca simülasyon kalibrasyon verisine bakılarak seçildi (`reports/kalibrasyon.md`). Endüstriyel güvenlik sınırı
değildir. Küçük makinelerde, örneğin 1 kW'ın altında, güç alt sınırını küçültün.

### Demo eşikleri ve süreklilik

- z < 3: referansla uyumlu.
- z ≥ 3: sapma adayı. z ≥ 6: belirgin sapma adayı. Bunlar grafikte işaretlenir ama tek başına uyarı değildir.
- **Uyarı kuralı:** Son 5 ardışık geçerli pencerenin en az 3'ünde z ≥ 3 ise **inceleme uyarısı** açılır. En az 3'ünde z ≥ 6 ise
  düzey **"Belirgin sapma"** olur. 5 pencere dolmadan uyarı oluşmaz.
- **Normale dönüş:** 8 ardışık geçerli pencerede z < 2 ise ölçüm durumu **"Ölçümler normale döndü"** olur.
- **Sayaçları sıfırlayan durumlar:** eksik veya geçersiz ölçüm, kesinti (beklenen aralığın 3 katından uzun boşluk), mod değişimi,
  durma ve donma şüphesi.
- **Geçiş süresi:** Mod değişiminden sonra 30 sn boyunca (makine ayarından değiştirilebilir) grafik gösterilir ama yeni uyarı
  üretilmez.
- Çalışma modu **otomatik tahmin edilmez.** Modu kullanıcı, veri kaynağı veya simülatör bildirir.

### Uyarı yaşam döngüsü

- **Ölçüm durumu:** Aktif sapma / Ölçümler normale döndü / Veri nedeniyle değerlendirilemiyor.
- **İnceleme durumu:** Yeni / İncelemeye alındı / Kapatıldı.
- **Değerlendirme:** Normal çalışma değişimi / Ölçüm sorunu / Bakımda sorun bulundu / Belirsiz.
- Kullanıcının uyarıyı görmesi veya kapatması, ölçümün normale döndüğü anlamına gelmez. Değerlendirme referansı değiştirmez.
- Aynı makine ve moddaki devam eden olay için her ölçümde yeni uyarı açılmaz; mevcut uyarı güncellenir.
- Açıklamalar ölçümlerden üretilir. "Rulman bozuldu" gibi doğrulanmamış teşhis yazılmaz.

### Veri kalitesi (sapmadan ayrı)

- Eksik ölçüm, sayısal olmayan değer, negatif RMS/güç/devir ve aralık dışı değer **işaretlenir, sıfıra çevrilmez.** Bu kayıtlarda
  puan hesaplanmaz.
- Geçersiz zaman damgalı kayıt saklanmaz.
- Yinelenen kayıt saklanmaz. Sırası bozuk kayıt saklanır ama süreklilik hesabına alınmaz.
- Canlı kaynakta (simülasyon, sensör) 3 beklenen ölçüm aralığı boyunca kayıt gelmezse **"Veri gelmiyor"** gösterilir. Son değer
  ekranda kalır, zamanı ve güncel olmadığı açıkça yazılır.
- CSV geçmiş verisi, sırf eski tarihli olduğu için kopuk kaynak sayılmaz.
- Çalışan makinede dört ölçüm **12 ardışık kayıtta** birebir aynıysa "Veri donması şüphesi" üretilir.
  - Bu sınırlı bir kontroldür ve sensörün bozulduğunu kanıtlamaz.
  - Donmuş değer tesadüfen sapmalıysa, donma fark edilmeden önceki 11 kayıtta bir sapma uyarısı açılabilir. Bu uyarı, donma
    anlaşılınca "değerlendirilemiyor" olur.
- Şüpheli, eksik veya gelmeyen veride makine **"Referansla uyumlu" gösterilmez.**

## 8. Simülatör

- Üç demo makinesinin (motor, pompa, fan) farklı normal dağılımları ve boşta/yük profilleri vardır. Ayrıca kullanıcı makineleri
  için bir kompresör profili bulunur.
- Simülatör sabit **tohumla tekrar üretilebilir** çalışır. Ölçümler zaman içinde ilişkilidir: her ölçüm bir AR(1) süreci ve ortak
  bir yük etkeni içerir. Mod değişince değerler gecikmeyle oturur.
- **Sanal zaman:** Hızlandırma sanal zamanı ilerletir, duraklatma dondurur. Veri kesintisi senaryosunda zaman ilerler ama kayıt
  üretilmez.
- **Senaryolar:**
  - Normal çalışma
  - Sağlıklı boşta → yük geçişi
  - Kademeli titreşim yükselmesi
  - Kademeli sıcaklık yükselmesi
  - Güç ve titreşimin birlikte değişmesi
  - Tek seferlik sıçrama
  - Eksik ölçüm
  - Veri akışının kesilmesi
  - Bütün ölçümlerin donması
  - Sapma sonrası normalleşme

  Her senaryo normal veriyle başlar; değişim sonra (varsayılan 2 dk) uygulanır.
- Senaryo adları yalnızca gösterim içindir. Analiz motoru senaryo adını veya gizli etiketi **kullanmaz.** Testlerden biri, aynı
  ölçümlerin sensör API'si ve CSV yolundan aynı sonucu verdiğini doğrular.
- Uygulama yeniden başlatılınca çalışan simülasyonlar **"duraklatıldı"** durumuna alınır ve ekranda bu açıkça yazar. "Devam et" ile
  kaldığı yerden aynı değerlerle sürer.
- **Demo sıfırlaması** yalnızca demo kayıtlarını etkiler:
  - Silinenler: demo makinelerinin simülasyon ölçümleri, demo referansları, bunlardan doğan uyarılar ve simülasyon çalıştırmaları.
  - Kullanıcının eklediği makineler, CSV ile aktarılan ölçümler ve notlar korunur. Silinen bir uyarıya bağlı not kalır, uyarının
    özeti saklanır.

## 9. API özeti

Tüm hata yanıtları `{"detail": "Türkçe açıklama"}` biçimindedir.

| İşlev | Uç nokta |
|---|---|
| Makineler | `GET/POST /api/machines`, `GET/PUT /api/machines/{id}` |
| Ölçüm alma (tek / toplu) | `POST /api/telemetry` |
| Ölçüm sorgulama | `GET /api/telemetry?machine_id&start&end`, grafik için `GET /api/machines/{id}/series` |
| Referans | `GET /api/machines/{id}/baselines`, `POST …/baselines/preview`, `POST …/baselines` |
| Uyarılar | `GET /api/alerts?machine_id&level&review_status&measurement_status&start&end`, `GET/PATCH /api/alerts/{id}` |
| Notlar | `GET/POST /api/notes` |
| Simülasyon | `POST /api/sim/start`, `POST /api/sim/runs/{id}/pause|resume|stop|speed|advance|mode|remove-effect`, `POST /api/demo/reset` |
| CSV | `POST /api/csv/preview`, `POST /api/csv/import`, `GET /api/csv/samples/{ad}` |
| Dışa aktarım | `GET /api/export/telemetry.csv`, `GET /api/export/alerts.csv` |
| Genel | `GET /api/overview`, `GET /api/config`, `GET /api/health` |

Otomatik belgeler uygulama çalışırken http://127.0.0.1:8000/docs adresindedir.

## 10. Testler ve değerlendirme

```bash
cd backend && ../.venv/bin/python -m pytest          # 37 test (analiz kuralları + API üzerinden gereksinimler)
cd frontend && npm run build                          # TypeScript kontrolü + ön yüz derlemesi
.venv/bin/python scripts/evaluate.py --set evaluation # simülasyon değerlendirmesi (~15 sn)
```

Testler şunları doğrular:
- sağlıklı yük değişiminin uyarı üretmemesi
- tek sıçramanın uyarı üretmemesi
- sürekli sapmanın 5'te 3 kuralıyla uyarı üretmesi
- kesintinin veri sorunu olarak görünmesi
- eksik kaydın puanı sıfıra indirmemesi
- referansı olmayan makinenin normal görünmemesi
- yinelenen ve sırası bozuk kayıtların süreklilik hesabını bozmaması
- devam eden olayın tek uyarı kalması
- değerlendirmenin referansı değiştirmemesi
- yeniden başlatmada kalıcılık
- demo sıfırlamasının kullanıcı verisini silmemesi
- CSV hata gösterimi ve kısmi aktarım yapılmaması
- sanal saat
- Türkçe hata mesajları

Değerlendirme sonuçları: `reports/degerlendirme_raporu.md`. Alt sınır seçimi: `reports/kalibrasyon.md`.

## 11. Proje yapısı

```
makine-iz/
├── kurulum.sh, baslat.sh        kurulum ve başlatma
├── requirements.lock.txt        kilitli Python paketleri
├── backend/makine_iz/
│   ├── config.py                eşikler, alt sınırlar, birimler
│   ├── validation.py            veri doğrulama (kalite işaretleri)
│   ├── analysis.py              analiz motoru (saf mantık: medyan/MAD, z, süreklilik)
│   ├── pipeline.py              ortak veri yolu: doğrula → sakla → analiz et → uyar
│   ├── alerts.py, explain.py    uyarı yaşam döngüsü, notlar, Türkçe açıklamalar
│   ├── baselines.py             referans oluşturma (sürümlü)
│   ├── simulator.py             tekrar üretilebilir simülatör ve senaryolar
│   ├── simulation.py            simülasyon çalıştırmaları ve sanal saat
│   ├── demo.py                  demo makineleri, etiketli geçmiş, sıfırlama
│   ├── csv_io.py                CSV doğrulama, aktarım, dışa aktarım
│   ├── status.py, series.py     makine durumu, grafik verisi
│   ├── db.py                    SQLite şeması
│   └── api.py                   FastAPI uç noktaları
├── backend/tests/               pytest testleri
├── frontend/src/                React + TypeScript arayüzü (pages/, components/)
├── scripts/                     evaluate.py (değerlendirme), make_samples.py (örnek CSV)
├── samples/                     örnek CSV dosyaları
├── reports/                     değerlendirme raporu, kalibrasyon notu, JSON çıktılar
└── data/                        SQLite veritabanı (çalışınca oluşur)
```

## 12. Sınırlamalar

- Değerlendirme yalnızca **simülasyon** verisiyle yapıldı. Simülatörün gerçek makineleri ne kadar iyi temsil ettiği bilinmiyor.
  Testlerin geçmesi gerçek arızaların önceden tahmin edilebildiğini göstermez.
- Normal çalışmada simülasyonda makine-saat başına yaklaşık 0,075 yanlış uyarı ölçüldü. Bunlar en çok yük altındaki güç
  dalgalanmasından geldi. Gerçek veride oran farklı olacaktır.
- Simülatörde mod geçişleri yaklaşık 30 sn içinde oturur. Gerçek makinelerde sıcaklık dakikalarca değişebilir. Bu durumda geçiş süresi
  makine ayarından uzatılmalı.
- Alt sınırlar bütün makineler için aynı varsayılandır. Makine ölçeğine göre ayarlanmaları gerekir.
- Kullanıcı hesabı ve yetkilendirme yoktur. Uygulama yalnızca yerel bilgisayarda (`127.0.0.1`) dinler.
- Sensör entegrasyonu yalnızca HTTP API olarak vardır. Gerçek bir veri toplama cihazıyla denenmedi.

## 13. Sorun giderme

- **"Önce kurulum yapın"**: `./kurulum.sh` çalıştırın.
- **Port 8000 dolu**: Başka bir port kullanın, örneğin `PORT=8010 ./baslat.sh`.
- **Her şeye sıfırdan başlamak**: Uygulamayı durdurun, `data/makine_iz.db*` dosyalarını silin ve yeniden başlatın. Bu işlem **bütün**
  verileri siler. Yalnızca demo verisini sıfırlamak için Simülasyon laboratuvarındaki düğmeyi kullanın.
- **macOS izin hatası (EPERM)**: Bazı uygulamalar Masaüstü klasörüne erişemez. Terminal'den çalıştırın ya da projeyi ev klasörünüze
  taşıyın.
