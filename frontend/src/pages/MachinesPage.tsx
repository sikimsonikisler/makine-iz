import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { SourceTag } from "../components/Badges";
import { Icon } from "../components/Icon";
import { Loading, Message } from "../components/Message";
import { FEATURES, MODE_LABELS, SOURCE_LABELS, fmtNum } from "../format";
import { navigate, usePolling } from "../hooks";
import type { AppConfig, FeatureId, Machine, Mode, ModeConfig } from "../types";

export function MachinesPage() {
  const machines = usePolling(() => api.get<Machine[]>("/api/machines"), [], null);
  return (
    <div className="page">
      <div className="page-head">
        <h1>Makineler</h1>
        <a className="button" href="#/makine-ekle">
          <Icon name="plus" size={16} /> Makine ekle
        </a>
      </div>
      {machines.error ? <Message kind="error">{machines.error}</Message> : null}
      {machines.data ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Ad</th>
                <th scope="col">Kimlik</th>
                <th scope="col">Tür</th>
                <th scope="col">Konum</th>
                <th scope="col">Veri kaynağı</th>
                <th scope="col">Ölçüm aralığı</th>
                <th scope="col">Tanımlı modlar</th>
                <th scope="col">
                  <span className="sr-only">İşlemler</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {machines.data.map((m) => (
                <tr key={m.id}>
                  <td>
                    <a href={`#/makine/${m.id}`}>{m.name}</a>
                  </td>
                  <td>
                    <code>{m.id}</code>
                  </td>
                  <td>{m.machine_type}</td>
                  <td>{m.location || "—"}</td>
                  <td>
                    <SourceTag source={m.data_source} />
                  </td>
                  <td>{m.expected_interval_s} sn</td>
                  <td>
                    {(Object.keys(MODE_LABELS) as Mode[])
                      .filter((mode) => m.modes[mode]?.enabled)
                      .map((mode) => MODE_LABELS[mode])
                      .join(", ")}
                  </td>
                  <td>
                    <a className="button small secondary" href={`#/makine/${m.id}/duzenle`}>
                      <Icon name="edit" size={15} /> Düzenle
                    </a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Loading />
      )}
    </div>
  );
}

interface FormState {
  id: string;
  name: string;
  machine_type: string;
  location: string;
  description: string;
  data_source: string;
  sim_profile: string;
  expected_interval_s: string;
  transition_s: string;
  modes: Record<Mode, ModeConfig>;
  ranges: Record<FeatureId, [string, string]>;
  floors: Record<FeatureId, string>;
}

function toForm(machine: Machine | null, config: AppConfig): FormState {
  const modes: Record<Mode, ModeConfig> = machine?.modes ?? {
    stopped: { enabled: true, description: "Makine durmuş; sapma değerlendirmesi yapılmaz." },
    idle: { enabled: true, description: "Makine boşta çalışıyor." },
    loaded: { enabled: true, description: "Makine yük altında çalışıyor." },
  };
  const ranges = machine?.ranges ?? config.default_ranges;
  const floors = machine?.floors ?? config.default_floors;
  return {
    id: machine?.id ?? "",
    name: machine?.name ?? "",
    machine_type: machine?.machine_type ?? "",
    location: machine?.location ?? "",
    description: machine?.description ?? "",
    data_source: machine?.data_source ?? "sensor",
    sim_profile: machine?.sim_profile ?? "motor",
    expected_interval_s: String(machine?.expected_interval_s ?? config.default_interval_s),
    transition_s: String(machine?.transition_s ?? config.default_transition_s),
    modes: JSON.parse(JSON.stringify(modes)),
    ranges: Object.fromEntries(FEATURES.map((f) => [f.id, [String(ranges[f.id][0]), String(ranges[f.id][1])]])) as FormState["ranges"],
    floors: Object.fromEntries(FEATURES.map((f) => [f.id, String(floors[f.id])])) as FormState["floors"],
  };
}

const num = (text: string) => Number(text.replace(",", "."));

export function MachineFormPage({ machineId }: { machineId?: string }) {
  const config = usePolling(() => api.get<AppConfig>("/api/config"), [], null);
  const existing = usePolling(
    () => (machineId ? api.get<{ machine: Machine }>(`/api/machines/${machineId}`).then((d) => d.machine) : Promise.resolve(null)),
    [machineId],
    null,
  );
  const [form, setForm] = useState<FormState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (config.data && (machineId ? existing.data : true) && !form) setForm(toForm(existing.data, config.data));
  }, [config.data, existing.data, machineId, form]);

  if (config.error || existing.error) return <Message kind="error">{config.error ?? existing.error}</Message>;
  if (!form || !config.data) return <Loading />;

  const set = (patch: Partial<FormState>) => setForm({ ...form, ...patch });

  const save = async () => {
    setBusy(true);
    setError(null);
    const payload = {
      ...(machineId ? {} : { id: form.id.trim() }),
      name: form.name,
      machine_type: form.machine_type,
      location: form.location,
      description: form.description,
      data_source: form.data_source,
      sim_profile: form.data_source === "simulation" ? form.sim_profile : null,
      expected_interval_s: num(form.expected_interval_s),
      transition_s: num(form.transition_s),
      modes: form.modes,
      ranges: Object.fromEntries(FEATURES.map((f) => [f.id, [num(form.ranges[f.id][0]), num(form.ranges[f.id][1])]])),
      floors: Object.fromEntries(FEATURES.map((f) => [f.id, num(form.floors[f.id])])),
    };
    try {
      const saved = machineId
        ? await api.put<Machine>(`/api/machines/${machineId}`, payload)
        : await api.post<Machine>("/api/machines", payload);
      navigate(`/makine/${saved.id}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page narrow">
      <p className="breadcrumb">
        <a href="#/makineler">Makineler</a> / {machineId ? "Düzenle" : "Yeni makine"}
      </p>
      <h1>{machineId ? `${form.name} — düzenle` : "Yeni makine ekle"}</h1>

      <section className="panel">
        <h2>Makine bilgileri</h2>
        <div className="form-grid">
          {!machineId ? (
            <label>
              Kimlik (CSV ve sensör verisinde kullanılır)
              <input value={form.id} onChange={(e) => set({ id: e.target.value.toLowerCase() })} placeholder="ör. kompresor-1" />
              <span className="hint">Küçük harf, rakam, "-" ve "_"; sonradan değiştirilemez.</span>
            </label>
          ) : null}
          <label>
            Ad
            <input value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder="ör. Kompresör K-1" />
          </label>
          <label>
            Tür
            <input list="machine-types" value={form.machine_type} onChange={(e) => set({ machine_type: e.target.value })} placeholder="ör. Kompresör" />
            <datalist id="machine-types">
              {["Motor", "Pompa", "Fan", "Kompresör", "Konveyör", "Torna", "Pres"].map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
          </label>
          <label>
            Konum
            <input value={form.location} onChange={(e) => set({ location: e.target.value })} placeholder="ör. Atölye 2" />
          </label>
          <label className="span-2">
            Açıklama
            <textarea rows={2} value={form.description} onChange={(e) => set({ description: e.target.value })} />
          </label>
          <label>
            Veri kaynağı
            <select value={form.data_source} onChange={(e) => set({ data_source: e.target.value })}>
              {Object.entries(SOURCE_LABELS).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          {form.data_source === "simulation" ? (
            <label>
              Simülasyon profili
              <select value={form.sim_profile} onChange={(e) => set({ sim_profile: e.target.value })}>
                {config.data.sim_profiles.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <label>
            Beklenen ölçüm aralığı (sn)
            <input inputMode="decimal" value={form.expected_interval_s} onChange={(e) => set({ expected_interval_s: e.target.value })} />
            <span className="hint">Canlı kaynakta 3 aralık boyunca kayıt gelmezse "Veri gelmiyor" gösterilir.</span>
          </label>
          <label>
            Mod değişiminden sonra geçiş süresi (sn)
            <input inputMode="decimal" value={form.transition_s} onChange={(e) => set({ transition_s: e.target.value })} />
            <span className="hint">Bu sürede grafik gösterilir, yeni sapma uyarısı üretilmez. Sıcaklığı yavaş oturan makinelerde uzatın.</span>
          </label>
        </div>
      </section>

      <section className="panel">
        <h2>Çalışma modları</h2>
        <p className="hint">Makine yalnızca aynı moddaki kendi referansıyla karşılaştırılır. Tanımlı olmayan moddaki kayıtlar geçersiz işaretlenir.</p>
        {(["stopped", "idle", "loaded"] as Mode[]).map((mode) => (
          <div className="mode-row" key={mode}>
            <label className="checkbox">
              <input
                type="checkbox"
                checked={form.modes[mode].enabled}
                disabled={mode === "stopped"}
                onChange={(e) => set({ modes: { ...form.modes, [mode]: { ...form.modes[mode], enabled: e.target.checked } } })}
              />
              <strong>{MODE_LABELS[mode]}</strong> <code>{mode}</code>
            </label>
            <input
              aria-label={`${MODE_LABELS[mode]} açıklaması`}
              value={form.modes[mode].description}
              onChange={(e) => set({ modes: { ...form.modes, [mode]: { ...form.modes[mode], description: e.target.value } } })}
            />
          </div>
        ))}
      </section>

      <section className="panel">
        <h2>Beklenen ölçüm aralığı ve alt sınırlar</h2>
        <p className="hint">
          Beklenen aralığın dışındaki değerler "geçersiz" işaretlenir (sıfıra çevrilmez). Alt sınır (feature_floor), MAD çok küçük
          olduğunda z hesabının paydasını korur: z ≥ 3 için en az 3 × alt sınır kadar değişim gerekir. Varsayılanlar demo
          değerleridir ({FEATURES.map((f) => `${f.label} ${fmtNum(config.data!.default_floors[f.id], f.digits + 1)} ${f.unit}`).join(", ")});
          güvenlik sınırı değildir.
        </p>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th scope="col">Ölçüm</th>
                <th scope="col">En az</th>
                <th scope="col">En çok</th>
                <th scope="col">Alt sınır (feature_floor)</th>
              </tr>
            </thead>
            <tbody>
              {FEATURES.map((f) => (
                <tr key={f.id}>
                  <td>
                    {f.label} ({f.unit})
                  </td>
                  {[0, 1].map((i) => (
                    <td key={i}>
                      <input
                        aria-label={`${f.label} ${i === 0 ? "en az" : "en çok"}`}
                        inputMode="decimal"
                        value={form.ranges[f.id][i]}
                        onChange={(e) => {
                          const pair = [...form.ranges[f.id]] as [string, string];
                          pair[i] = e.target.value;
                          set({ ranges: { ...form.ranges, [f.id]: pair } });
                        }}
                      />
                    </td>
                  ))}
                  <td>
                    <input
                      aria-label={`${f.label} alt sınırı`}
                      inputMode="decimal"
                      value={form.floors[f.id]}
                      onChange={(e) => set({ floors: { ...form.floors, [f.id]: e.target.value } })}
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {error ? <Message kind="error">{error}</Message> : null}
      <div className="actions">
        <button type="button" className="button" onClick={save} disabled={busy}>
          <Icon name="check" size={16} /> {busy ? "Kaydediliyor…" : "Kaydet"}
        </button>
        <a className="button secondary" href={machineId ? `#/makine/${machineId}` : "#/makineler"}>
          Vazgeç
        </a>
      </div>
    </div>
  );
}
