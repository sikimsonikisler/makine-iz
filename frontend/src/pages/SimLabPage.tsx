import { useEffect, useState } from "react";
import { api, errorMessage, qs } from "../api";
import { SourceTag, StatusPill } from "../components/Badges";
import { TelemetryCharts } from "../components/Charts";
import { Icon } from "../components/Icon";
import { Loading, Message } from "../components/Message";
import { MODE_LABELS, fmtDateTime, fmtDuration, fmtNum, fmtValue, FEATURES } from "../format";
import { navigate, usePolling } from "../hooks";
import type { AppConfig, Machine, MachineDetail, Mode, Series, SimRun } from "../types";

const RUN_STATUS: Record<SimRun["status"], { label: string; icon: "play" | "pause" | "stop" }> = {
  running: { label: "Çalışıyor", icon: "play" },
  paused: { label: "Duraklatıldı", icon: "pause" },
  stopped: { label: "Durduruldu", icon: "stop" },
};

export function SimLabPage({ query }: { query: URLSearchParams }) {
  const config = usePolling(() => api.get<AppConfig>("/api/config"), [], null);
  const machines = usePolling(() => api.get<Machine[]>("/api/machines"), [], null);
  const simMachines = (machines.data ?? []).filter((m) => m.data_source === "simulation");
  const selectedId = query.get("makine") ?? simMachines[0]?.id ?? "";

  if (machines.loading && !machines.data) return <Loading />;
  return (
    <div className="page">
      <h1>
        <Icon name="flask" size={26} /> Simülasyon laboratuvarı
      </h1>
      <p className="lead">
        Gerçek makine olmadan uygulamayı denemek için ölçümler burada üretilir. Simülatör sabit bir tohumla tekrar üretilebilir
        çalışır ve sanal zaman kullanır. Hızlandırma sanal zamanı ilerletir, duraklatma dondurur.
      </p>
      <Message kind="info">
        Senaryo adları yalnızca gösterim içindir. Analiz motoru senaryoyu bilmez; yalnızca ölçümlere, çalışma moduna ve referansa
        bakar. Her senaryo normal veriyle başlar, değişim sonra uygulanır.
      </Message>
      {machines.error ? <Message kind="error">{machines.error}</Message> : null}
      {simMachines.length === 0 ? (
        <Message kind="warning">Veri kaynağı "Simülasyon" olan makine yok. Demo verisini sıfırlayarak demo makinelerini geri getirebilirsiniz.</Message>
      ) : (
        <div className="segmented machine-switch" role="group" aria-label="Makine seçimi">
          {simMachines.map((m) => (
            <button
              key={m.id}
              type="button"
              className={m.id === selectedId ? "active" : ""}
              aria-pressed={m.id === selectedId}
              onClick={() => navigate(`/simulasyon?makine=${m.id}`)}
            >
              {m.name}
            </button>
          ))}
        </div>
      )}
      {selectedId && config.data ? <SimMachinePanel key={selectedId} machineId={selectedId} config={config.data} /> : null}
      <DemoReset onDone={() => void machines.reload()} />
    </div>
  );
}

function SimMachinePanel({ machineId, config }: { machineId: string; config: AppConfig }) {
  const detail = usePolling(() => api.get<MachineDetail>(`/api/machines/${machineId}`), [machineId], 2000);
  const lastTs = detail.data?.range.last_ts ?? null;
  const series = usePolling(
    () =>
      lastTs
        ? api.get<Series>(
            `/api/machines/${machineId}/series${qs({
              start: new Date(Date.parse(lastTs) - 15 * 60000).toISOString(),
              end: lastTs,
              max_points: 400,
            })}`,
          )
        : Promise.resolve(null),
    [machineId, lastTs],
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const call = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      await fn();
      setSuccess(label);
      await detail.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  if (detail.error && !detail.data) return <Message kind="error">{detail.error}</Message>;
  if (!detail.data) return <Loading />;
  const { machine, status, run } = detail.data;
  const active = run && run.status !== "stopped" ? run : null;
  const onsetPassed = active ? Date.parse(active.virtual_now) >= Date.parse(active.onset_virtual) : false;
  const scenario = active ? config.scenarios.find((s) => s.id === active.scenario) : null;
  const currentMode = status.current_mode;

  return (
    <>
      <section className="panel">
        <div className="panel-head">
          <h2>
            {machine.name} <SourceTag source="simulation" />
          </h2>
          <a className="button small secondary" href={`#/makine/${machine.id}`}>
            <Icon name="chart" size={15} /> Makine ayrıntısı
          </a>
        </div>
        {active ? (
          <div className="run-box">
            <div className={`run-status run-${active.status}`}>
              <Icon name={RUN_STATUS[active.status].icon} size={20} />
              <strong>{RUN_STATUS[active.status].label}</strong>
              <span>· {active.scenario_label}</span>
            </div>
            {scenario ? <p className="small">{scenario.description}</p> : null}
            {active.status_note ? <Message kind="info">{active.status_note}</Message> : null}
            <dl className="facts facts-grid">
              <div>
                <dt>Sanal zaman</dt>
                <dd>{fmtDateTime(active.virtual_now)}</dd>
              </div>
              <div>
                <dt>Geçen sanal süre</dt>
                <dd>{fmtDuration(active.elapsed_virtual_s)}</dd>
              </div>
              <div>
                <dt>Değişim anı</dt>
                <dd>
                  {active.scenario === "normal" ? "Değişim yok" : fmtDateTime(active.onset_virtual)}
                  {active.scenario !== "normal" ? (onsetPassed ? " (uygulandı)" : " (henüz normal veri)") : ""}
                  {active.params.effect_end_step ? " · etki kaldırıldı" : ""}
                </dd>
              </div>
              <div>
                <dt>Hız</dt>
                <dd>{fmtNum(active.speed, 0)}× (1 gerçek saniye = {fmtNum(active.speed, 0)} sanal saniye)</dd>
              </div>
              <div>
                <dt>Tohum (seed)</dt>
                <dd>{active.seed}</dd>
              </div>
              <div>
                <dt>Üretilen kayıt</dt>
                <dd>
                  {active.records_emitted} kayıt / {active.steps_generated} ölçüm aralığı
                </dd>
              </div>
            </dl>
            <div className="control-groups">
              <div className="control-group">
                <span className="control-label">Akış</span>
                {active.status === "running" ? (
                  <button type="button" className="button" disabled={busy} onClick={() => call("Simülasyon duraklatıldı; sanal zaman donduruldu.", () => api.post(`/api/sim/runs/${active.id}/pause`))}>
                    <Icon name="pause" size={16} /> Duraklat
                  </button>
                ) : (
                  <button type="button" className="button" disabled={busy} onClick={() => call("Simülasyon devam ediyor.", () => api.post(`/api/sim/runs/${active.id}/resume`))}>
                    <Icon name="play" size={16} /> Devam et
                  </button>
                )}
                <button type="button" className="button secondary" disabled={busy} onClick={() => call("Simülasyon durduruldu.", () => api.post(`/api/sim/runs/${active.id}/stop`))}>
                  <Icon name="stop" size={16} /> Durdur
                </button>
              </div>
              <div className="control-group">
                <span className="control-label">Hız</span>
                <div className="segmented" role="group" aria-label="Simülasyon hızı">
                  {config.speeds.map((speed) => (
                    <button
                      key={speed}
                      type="button"
                      className={active.speed === speed ? "active" : ""}
                      aria-pressed={active.speed === speed}
                      disabled={busy}
                      onClick={() => call(`Hız ${speed}× olarak ayarlandı.`, () => api.post(`/api/sim/runs/${active.id}/speed`, { speed }))}
                    >
                      {speed}×
                    </button>
                  ))}
                </div>
              </div>
              <div className="control-group">
                <span className="control-label">İleri sar</span>
                {[5, 30].map((minutes) => (
                  <button
                    key={minutes}
                    type="button"
                    className="button secondary"
                    disabled={busy}
                    onClick={() =>
                      call(`${minutes} dakikalık sanal zaman üretildi ve analiz edildi.`, () =>
                        api.post(`/api/sim/runs/${active.id}/advance`, { seconds: minutes * 60 }),
                      )
                    }
                  >
                    <Icon name="forward" size={16} /> +{minutes} dk
                  </button>
                ))}
              </div>
              <div className="control-group">
                <span className="control-label">Çalışma modu</span>
                <div className="segmented" role="group" aria-label="Çalışma modu">
                  {(["stopped", "idle", "loaded"] as Mode[])
                    .filter((m) => machine.modes[m]?.enabled)
                    .map((m) => (
                      <button
                        key={m}
                        type="button"
                        className={currentMode === m ? "active" : ""}
                        aria-pressed={currentMode === m}
                        disabled={busy}
                        onClick={() =>
                          call(`Simülatöre "${MODE_LABELS[m]}" modu bildirildi; sonraki ölçümden itibaren uygulanır.`, () =>
                            api.post(`/api/sim/runs/${active.id}/mode`, { mode: m }),
                          )
                        }
                      >
                        {MODE_LABELS[m]}
                      </button>
                    ))}
                </div>
              </div>
              {active.scenario !== "normal" && !active.params.effect_end_step ? (
                <div className="control-group">
                  <span className="control-label">Senaryo</span>
                  <button
                    type="button"
                    className="button secondary"
                    disabled={busy}
                    onClick={() => call("Senaryo etkisi kaldırıldı; makine normal davranışa dönüyor.", () => api.post(`/api/sim/runs/${active.id}/remove-effect`))}
                  >
                    <Icon name="refresh" size={16} /> Etkiyi kaldır (normalleşme)
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        ) : (
          <Message kind="info">Bu makine için çalışan bir simülasyon yok. Aşağıdan bir senaryo başlatın.</Message>
        )}
        {error ? <Message kind="error">{error}</Message> : null}
        {success ? <Message kind="success">{success}</Message> : null}
      </section>

      <section className="panel">
        <h2>Analizin gördüğü</h2>
        <div className="sim-status">
          <StatusPill status={status} large />
          <span>
            {status.deviation_score !== null ? (
              <>
                Sapma puanı <strong>{fmtNum(status.deviation_score, 0)}</strong>/100
              </>
            ) : (
              "Sapma puanı hesaplanmadı"
            )}
          </span>
        </div>
        <p>{status.detail}</p>
        <div className="mini-values">
          {FEATURES.map((f) => (
            <span key={f.id}>
              {f.label}: <strong>{fmtValue(f.id, status.last_values[f.id])}</strong>
              {status.z ? ` (z ${fmtNum(status.z[f.id], 1)})` : ""}
            </span>
          ))}
        </div>
        <h3>Son 15 dakika (sanal zaman)</h3>
        {series.data ? (
          <TelemetryCharts
            points={series.data.points}
            baseline={status.current_mode ? status.baselines_by_mode[status.current_mode] ?? null : null}
            floors={machine.floors}
            compact
          />
        ) : (
          <Loading />
        )}
      </section>

      <StartScenario machine={machine} config={config} onStarted={() => void detail.reload()} />
    </>
  );
}

function StartScenario({ machine, config, onStarted }: { machine: Machine; config: AppConfig; onStarted: () => void }) {
  const [scenario, setScenario] = useState("vibration_ramp");
  const [startMode, setStartMode] = useState<Mode>("loaded");
  const [onsetMin, setOnsetMin] = useState("2");
  const [seed, setSeed] = useState("42");
  const [speed, setSpeed] = useState(20);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (scenario === "load_change") setStartMode("idle");
  }, [scenario]);

  const start = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    const onset = Number(onsetMin.replace(",", "."));
    const seedNumber = Number(seed);
    if (!Number.isFinite(onset) || onset < 0) {
      setError("Değişim başlangıcı 0 veya daha büyük bir sayı olmalı (dakika).");
      setBusy(false);
      return;
    }
    if (!Number.isInteger(seedNumber) || seedNumber < 0) {
      setError("Tohum 0 veya daha büyük bir tam sayı olmalı.");
      setBusy(false);
      return;
    }
    try {
      const run = await api.post<SimRun>("/api/sim/start", {
        machine_id: machine.id,
        scenario,
        seed: seedNumber,
        speed,
        start_mode: startMode,
        onset_s: onset * 60,
      });
      setSuccess(`"${run.scenario_label}" başlatıldı (tohum ${run.seed}, ${run.speed}×). Önceki çalıştırma durduruldu.`);
      onStarted();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const groups = [
    { id: "davranış", title: "Makine davranışı" },
    { id: "veri", title: "Veri kalitesi" },
  ];

  return (
    <section className="panel">
      <h2>
        <Icon name="play" /> Yeni senaryo başlat
      </h2>
      <div className="scenario-groups">
        {groups.map((group) => (
          <fieldset key={group.id} className="scenario-group">
            <legend>{group.title}</legend>
            {config.scenarios
              .filter((s) => s.group === group.id)
              .map((s) => (
                <label key={s.id} className={`scenario-option${scenario === s.id ? " selected" : ""}`}>
                  <input type="radio" name="scenario" value={s.id} checked={scenario === s.id} onChange={() => setScenario(s.id)} />
                  <span>
                    <strong>{s.label}</strong>
                    <span className="small">{s.description}</span>
                  </span>
                </label>
              ))}
          </fieldset>
        ))}
      </div>
      <div className="form-grid">
        <label>
          Başlangıç modu
          <select value={startMode} onChange={(e) => setStartMode(e.target.value as Mode)} disabled={scenario === "load_change"}>
            {(["stopped", "idle", "loaded"] as Mode[])
              .filter((m) => machine.modes[m]?.enabled)
              .map((m) => (
                <option key={m} value={m}>
                  {MODE_LABELS[m]}
                </option>
              ))}
          </select>
        </label>
        <label>
          Değişim kaç dakika sonra başlasın?
          <input inputMode="decimal" value={onsetMin} onChange={(e) => setOnsetMin(e.target.value)} />
        </label>
        <label>
          Tohum (seed)
          <input inputMode="numeric" value={seed} onChange={(e) => setSeed(e.target.value)} />
        </label>
        <label>
          Hız
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {config.speeds.map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </label>
      </div>
      <p className="hint">Aynı senaryo, tohum ve başlangıç modu her seferinde aynı ölçümleri üretir.</p>
      <div className="actions">
        <button type="button" className="button" onClick={start} disabled={busy}>
          <Icon name="play" size={16} /> {busy ? "Başlatılıyor…" : "Senaryoyu başlat"}
        </button>
      </div>
      {error ? <Message kind="error">{error}</Message> : null}
      {success ? <Message kind="success">{success}</Message> : null}
    </section>
  );
}

function DemoReset({ onDone }: { onDone: () => void }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const reset = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await api.post<{ deleted: Record<string, number>; message: string }>("/api/demo/reset", { confirm: true });
      setSuccess(
        `${result.message} Silinen demo kayıtları: ${result.deleted.telemetry} ölçüm, ${result.deleted.alerts} uyarı, ` +
          `${result.deleted.baselines} referans, ${result.deleted.simulation_runs} simülasyon çalıştırması.`,
      );
      setAsking(false);
      onDone();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel danger-zone">
      <h2>
        <Icon name="refresh" /> Demo verisini sıfırla
      </h2>
      <p>
        Yalnızca demo kayıtlarını etkiler: demo makinelerinin simülasyon ölçümleri, demo referansları, bunlardan doğan uyarılar ve
        simülasyon çalıştırmaları silinir; etiketli normal demo geçmişi ve referanslar yeniden üretilir.{" "}
        <strong>Kendi eklediğiniz makineler, CSV ile aktardığınız ölçümler ve notlarınız silinmez.</strong>
      </p>
      {asking ? (
        <div className="confirm-box">
          <p>Demo verisi sıfırlansın mı? Bu işlem geri alınamaz.</p>
          <div className="actions">
            <button type="button" className="button danger" onClick={reset} disabled={busy}>
              {busy ? "Sıfırlanıyor…" : "Evet, demo verisini sıfırla"}
            </button>
            <button type="button" className="button secondary" onClick={() => setAsking(false)} disabled={busy}>
              Vazgeç
            </button>
          </div>
        </div>
      ) : (
        <button type="button" className="button secondary" onClick={() => setAsking(true)}>
          Demo verisini sıfırla…
        </button>
      )}
      {error ? <Message kind="error">{error}</Message> : null}
      {success ? <Message kind="success">{success}</Message> : null}
    </section>
  );
}
