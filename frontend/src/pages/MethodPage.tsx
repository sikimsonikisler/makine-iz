import { api } from "../api";
import { Loading, Message } from "../components/Message";
import { FEATURES, fmtNum } from "../format";
import { usePolling } from "../hooks";
import type { AppConfig } from "../types";

export function MethodPage() {
  const config = usePolling(() => api.get<AppConfig>("/api/config"), [], null);
  if (config.error) return <Message kind="error">{config.error}</Message>;
  if (!config.data) return <Loading />;
  const a = config.data.analysis;
  return (
    <div className="page narrow prose">
      <h1>Analiz yöntemi ve sınırlamalar</h1>
      <Message kind="warning">
        Bu ilk sürüm bir prototiptir. Eşikler demo değerleridir ve gerçek makinelerde doğrulanmamıştır. Uyarılar ölçüm sapmasını
        gösterir; kesin arıza teşhisi, kalan ömür tahmini veya makine kontrolü yapılmaz.
      </Message>

      <h2>1. Referans profili</h2>
      <p>
        Her makine ve her çalışan mod (Boşta, Yük altında) için ayrı referans vardır. Referans, kullanıcının "normal çalışma olarak
        kabul ediyorum" diyerek seçtiği aralıktan hesaplanır ve en az {a.min_baseline_samples} geçerli kayıt gerektirir. Her ölçüm için{" "}
        <strong>medyan</strong> ve <strong>MAD</strong> (medyan mutlak sapması) saklanır. Referans gelen ölçümlerle kendiliğinden
        güncellenmez; böylece süren bir sapma "normal" diye öğrenilmez. Geçiş süresindeki, geçersiz, donmuş ve sırası bozuk kayıtlar
        referansa katılmaz.
      </p>

      <h2>2. Sapma değeri</h2>
      <pre className="code">z = |ölçüm − medyan| / max({a.mad_scale} × MAD, alt_sınır){"\n"}pencerenin sapma değeri = dört ölçümün z değerlerinin en büyüğü{"\n"}sapma puanı = min(100, 10 × en büyük z)</pre>
      <p>
        Sapma puanı arıza olasılığı, sağlık yüzdesi veya kalan ömür değildir. Alt sınırlar (feature_floor) ölçümün kendi
        birimindedir:
      </p>
      <ul>
        {FEATURES.map((f) => (
          <li key={f.id}>
            {f.label}: {fmtNum(config.data!.default_floors[f.id], f.digits + 1)} {f.unit} (z ≥ 3 için en az{" "}
            {fmtNum(3 * config.data!.default_floors[f.id], f.digits + 1)} {f.unit} değişim)
          </li>
        ))}
      </ul>
      <p>Bu varsayılanlar yalnızca simülasyon kalibrasyon verisine bakılarak seçildi; her makinenin ayarlarından değiştirilebilir.</p>

      <h2>3. Eşikler ve süreklilik (demo eşikleri)</h2>
      <ul>
        <li>z &lt; {a.z_candidate}: referansla uyumlu.</li>
        <li>z ≥ {a.z_candidate}: sapma adayı (grafikte işaretlenir, tek başına uyarı değildir).</li>
        <li>z ≥ {a.z_strong}: belirgin sapma adayı.</li>
        <li>
          Son {a.window_count} ardışık geçerli pencerenin en az {a.min_hits}'ünde z ≥ {a.z_candidate} → <strong>inceleme uyarısı</strong>;
          en az {a.min_hits}'ünde z ≥ {a.z_strong} → <strong>Belirgin sapma</strong>. {a.window_count} pencere dolmadan uyarı oluşmaz.
        </li>
        <li>
          {a.normal_streak} ardışık geçerli pencerede z &lt; {a.z_normal} → ölçüm durumu "Ölçümler normale döndü". Kullanıcının inceleme
          kaydı silinmez.
        </li>
        <li>Aynı makine ve moddaki devam eden olay için yeni uyarı açılmaz; mevcut uyarı güncellenir.</li>
      </ul>

      <h2>4. Süreklilik sayaçlarını sıfırlayan durumlar</h2>
      <p>
        Eksik veya geçersiz ölçüm, veri kesintisi (beklenen aralığın {a.gap_factor} katından uzun boşluk), çalışma modu değişimi,
        makinenin durması ve veri donması şüphesi sayaçları sıfırlar. Mod değişiminden sonra makine ayarındaki geçiş süresi (varsayılan{" "}
        {config.data.default_transition_s} sn) boyunca grafik gösterilir ama yeni sapma uyarısı üretilmez. Eksik veri üzerinden
        normalleşme veya uyarı kapanması sonucuna varılmaz.
      </p>

      <h2>5. Veri kalitesi (sapmadan ayrı)</h2>
      <ul>
        <li>Eksik ölçüm, sayısal olmayan değer, negatif RMS/güç/devir ve beklenen aralık dışı değerler işaretlenir; sıfıra çevrilmez.</li>
        <li>Geçersiz zaman damgalı kayıt saklanamaz ve bildirilir.</li>
        <li>Yinelenen kayıt (aynı makine + aynı zaman) saklanmaz; sırası bozuk kayıt saklanır ama süreklilik hesabına alınmaz.</li>
        <li>Canlı kaynakta (simülasyon, sensör) {a.gap_factor} beklenen aralık boyunca kayıt gelmezse "Veri gelmiyor" gösterilir. CSV geçmiş verisi eski olduğu için kopuk sayılmaz.</li>
        <li>
          Çalışan makinede dört ölçüm {a.freeze_count} ardışık kayıtta birebir aynı kalırsa "Veri donması şüphesi" üretilir. Bu sınırlı
          bir kontroldür; sensörün kesin bozulduğu anlamına gelmez. Donmuş değer tesadüfen sapmalıysa, donma fark edilmeden önce
          (ilk {a.freeze_count - 1} kayıtta) bir sapma uyarısı açılabilir; bu uyarı donma anlaşılınca "değerlendirilemiyor" olur.
        </li>
        <li>Veri sorunu uyarısı, {a.dq_recovery} ardışık sağlam kayıttan sonra "Veri normale döndü" olur.</li>
      </ul>

      <h2>6. Sınırlamalar</h2>
      <ul>
        <li>Titreşim alanı, veri toplama katmanında hesaplanmış bir RMS özetidir. Ham titreşim, FFT veya rulman kusur frekansı analizi yapılmaz.</li>
        <li>Çalışma modu otomatik tahmin edilmez; kullanıcı, veri kaynağı veya simülatör bildirir.</li>
        <li>Değerlendirme sonuçları simülasyona aittir. Gerçek makinede arıza tahmini başarısı olarak yorumlanamaz.</li>
        <li>Yavaş değişen normal dalgalanmalar (ör. yükle değişen güç) ara sıra yanlış uyarı üretebilir; ayrıntılar değerlendirme raporundadır.</li>
        <li>Simülatörde mod geçişleri yaklaşık 30 sn içinde oturur. Gerçek makinelerde sıcaklık dakikalarca değişebilir; geçiş süresini makineye göre uzatın.</li>
      </ul>
    </div>
  );
}
