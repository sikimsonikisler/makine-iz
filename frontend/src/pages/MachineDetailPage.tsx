import { useMemo, useState } from "react";
import { api, qs } from "../api";
import { AlertTable } from "../components/AlertTable";
import { SourceTag, StatusPill } from "../components/Badges";
import { BaselinePanel } from "../components/BaselinePanel";
import { TelemetryCharts } from "../components/Charts";
import { Icon } from "../components/Icon";
import { Loading, Message } from "../components/Message";
import { NotesPanel } from "../components/NotesPanel";
import { TimeFilter, resolveRange, type RangeState } from "../components/TimeFilter";
import {
  FEATURES,
  MODE_LABELS,
  SOURCE_LABELS,
  flagLabel,
  fmtDateTime,
  fmtDuration,
  fmtNum,
  fmtSigned,
  fmtValue,
} from "../format";
import { usePolling } from "../hooks";
import type { Alert, MachineDetail, Mode, Series } from "../types";

export function MachineDetailPage({ machineId, query }: { machineId: string; query: URLSearchParams }) {
  const [range, setRange] = useState<RangeState>(() => {
    const start = query.get("start");
    const end = query.get("end");
    return start && end ? { preset: "custom", start, end } : { preset: "1h" };
  });
  const [refMode, setRefMode] = useState<Mode | "current" | "none">("current");

  const detail = usePolling(() => api.get<MachineDetail>(`/api/machines/${encodeURIComponent(machineId)}`), [machineId], 3000);
  const resolved = detail.data ? resolveRange(range, detail.data.range.first_ts, detail.data.range.last_ts) : null;
  const series = usePolling(
    () =>
      resolved
        ? api.get<Series>(`/api/machines/${encodeURIComponent(machineId)}/series${qs({ ...resolved, max_points: 1200 })}`)
        : Promise.resolve(null),
    [machineId, resolved?.start, resolved?.end],
    null,
  );
  const alerts = usePolling(() => api.get<Alert[]>(`/api/alerts${qs({ machine_id: machineId })}`), [machineId], 5000);

  const d = detail.data;
  const chartBaseline = useMemo(() => {
    if (!d) return null;
    if (refMode === "none") return null;
    const mode = refMode === "current" ? d.status.current_mode : refMode;
    return mode ? d.status.baselines_by_mode[mode] ?? null : null;
  }, [d, refMode]);

  if (detail.error && !d) return <Message kind="error">{detail.error}</Message>;
  if (!d) return <Loading />;
  const { machine, status, run } = d;
  const top = status.changes.slice(0, 2);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="breadcrumb">
            <a href="#/">Genel görünüm</a> / {machine.name}
          </p>
          <h1>
            {machine.name} <SourceTag source={machine.data_source} />
          </h1>
          <p className="muted">
            {machine.machine_type}
            {machine.location ? ` · ${machine.location}` : ""} · Kimlik: <code>{machine.id}</code>
          </p>
          {machine.description ? <p>{machine.description}</p> : null}
        </div>
        <div className="actions">
          <a className="button secondary" href={`#/makine/${machine.id}/duzenle`}>
            <Icon name="edit" size={16} /> Makineyi düzenle
          </a>
          <a className="button secondary" href={`/api/export/telemetry.csv${qs({ machine_id: machine.id, ...(resolved ?? {}) })}`}>
            <Icon name="download" size={16} /> Görünen aralığı CSV indir
          </a>
          {machine.data_source === "simulation" ? (
            <a className="button secondary" href={`#/simulasyon?makine=${machine.id}`}>
              <Icon name="flask" size={16} /> Simülasyon laboratuvarı
            </a>
          ) : null}
        </div>
      </div>
      {detail.error ? <Message kind="error">Veriler güncellenemedi: {detail.error}</Message> : null}

      <section className="panel status-panel">
        <div className="status-main">
          <StatusPill status={status} large />
          <p>{status.detail}</p>
          {status.badges.length ? (
            <ul className="badge-list">
              {status.badges.map((b) => (
                <li key={b}>
                  <Icon name="info" size={14} /> {b}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <dl className="facts">
          <div>
            <dt>Güncel çalışma modu</dt>
            <dd>{status.current_mode ? MODE_LABELS[status.current_mode] : "—"}</dd>
          </div>
          <div>
            <dt>Son ölçüm</dt>
            <dd>
              {fmtDateTime(status.last_ts)}
              {status.live.virtual && status.last_ts ? " (sanal zaman)" : ""}
              {status.stale ? <strong className="stale"> — güncel değil ({fmtDuration(status.age_s)} önce)</strong> : null}
            </dd>
          </div>
          <div>
            <dt>Veri kaynağı</dt>
            <dd>
              {SOURCE_LABELS[machine.data_source]} · {status.live.label}
              {run && run.status !== "stopped" ? ` · ${run.scenario_label} (${fmtNum(run.speed, 0)}×)` : ""}
            </dd>
          </div>
          <div>
            <dt>Süreklilik</dt>
            <dd>
              Son geçerli pencereler: {status.persistence.windows.length ? status.persistence.windows.map((z) => fmtNum(z, 1)).join(" · ") : "—"}{" "}
              ({status.persistence.windows.length}/5) · ardışık z &lt; 2: {status.persistence.normal_streak}/8
            </dd>
          </div>
        </dl>
      </section>

      <section className="value-tiles" aria-label="Güncel değerler">
        {FEATURES.map((f) => {
          const stat = status.baseline?.stats[f.id];
          const z = status.z?.[f.id];
          const invalid = status.last_flags.some((flag) => flag.endsWith(`:${f.id}`));
          return (
            <div className={`value-tile${z !== undefined && z >= 3 ? " value-alert" : ""}`} key={f.id}>
              <div className="value-label">{f.label}</div>
              <div className="value-number">{fmtValue(f.id, status.last_values[f.id])}</div>
              {invalid ? (
                <div className="value-flag">
                  <Icon name="dataoff" size={14} /> {status.last_flags.filter((x) => x.endsWith(`:${f.id}`)).map(flagLabel).join(", ")}
                </div>
              ) : null}
              <div className="value-ref">
                {stat ? (
                  <>
                    Referans ({MODE_LABELS[status.baseline!.mode]} v{status.baseline!.version}): {fmtValue(f.id, stat.median)}
                  </>
                ) : (
                  "Bu mod için referans yok"
                )}
              </div>
              <div className="value-z">
                {z !== undefined ? (
                  <>
                    z = <strong>{fmtNum(z, 2)}</strong> {z >= 3 ? <span className="tag tag-warn">z ≥ 3</span> : null}
                  </>
                ) : (
                  "z hesaplanmadı"
                )}
              </div>
            </div>
          );
        })}
      </section>

      <section className="panel">
        <h2>Sapma ölçüsü ve açıklaması</h2>
        {status.deviation_score !== null ? (
          <>
            <p>
              <span className="big-number">{fmtNum(status.deviation_score, 0)}</span>/100 <strong>Sapma puanı</strong> (son pencere) —
              en büyük z = {fmtNum(status.z_max, 2)}. Puan = min(100, 10 × en büyük z). Arıza olasılığı, sağlık yüzdesi veya kalan
              ömür değildir.
            </p>
            {top.length ? (
              <p>
                En çok değişen iki ölçüm:{" "}
                {top.map((c, i) => (
                  <span key={c.feature}>
                    {i ? "; " : ""}
                    <strong>{c.label}</strong> {fmtValue(c.feature, c.value)} (referans {fmtValue(c.feature, c.median)}, fark{" "}
                    {fmtSigned(c.feature, c.diff)}, z = {fmtNum(c.z, 1)})
                  </span>
                ))}
                .
              </p>
            ) : null}
          </>
        ) : (
          <p className="muted">Son kayıt için sapma hesaplanmadı ({status.label.toLowerCase()}). Bu durumda puan gösterilmez; sıfır kabul edilmez.</p>
        )}
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>Zaman grafikleri</h2>
          <label className="inline">
            Referans çizgisi:
            <select value={refMode} onChange={(e) => setRefMode(e.target.value as Mode | "current" | "none")}>
              <option value="current">Güncel mod</option>
              {(["idle", "loaded"] as Mode[])
                .filter((m) => status.baselines_by_mode[m])
                .map((m) => (
                  <option key={m} value={m}>
                    {MODE_LABELS[m]}
                  </option>
                ))}
              <option value="none">Gösterme</option>
            </select>
          </label>
        </div>
        <TimeFilter value={range} onChange={setRange} current={resolved} />
        {series.error ? <Message kind="error">Grafik verisi yüklenemedi: {series.error}</Message> : null}
        {series.data ? (
          <>
            <p className="hint">
              {series.data.total} ölçüm
              {series.data.downsampled
                ? ` · görüntüleme için ${fmtDuration(series.data.bucket_s)}lik aralıkların ortalaması çiziliyor (${series.data.points.length} nokta). Analiz her zaman tam veriyi kullanır.`
                : " · tüm ölçümler çiziliyor."}{" "}
              Kesintilerde çizgi bilerek kesilir. Grafiklerin üzerine gelince ölçüm ayrıntısı görünür.
            </p>
            <TelemetryCharts points={series.data.points} baseline={chartBaseline} floors={machine.floors} />
          </>
        ) : d.range.count === 0 ? (
          <p className="muted">Bu makine için henüz ölçüm yok.</p>
        ) : (
          <Loading />
        )}
      </section>

      <BaselinePanel
        key={machine.id}
        machine={machine}
        baselines={d.baselines}
        chartRange={resolved}
        onCreated={() => void detail.reload()}
      />

      <section className="panel">
        <h2>
          <Icon name="bell" /> Uyarı geçmişi
        </h2>
        {alerts.error ? <Message kind="error">{alerts.error}</Message> : null}
        <AlertTable alerts={alerts.data ?? []} showMachine={false} empty="Bu makine için uyarı yok." />
      </section>

      <NotesPanel machineId={machine.id} title="Makine notları (inceleme ve bakım)" />

      <details className="panel details">
        <summary>Makine ayarları (modlar, ölçüm aralığı, alt sınırlar)</summary>
        <dl className="facts">
          <div>
            <dt>Beklenen ölçüm aralığı</dt>
            <dd>{machine.expected_interval_s} sn (3 aralık boyunca kayıt gelmezse kesinti)</dd>
          </div>
          <div>
            <dt>Mod değişiminden sonra geçiş süresi</dt>
            <dd>{machine.transition_s} sn</dd>
          </div>
          {(["stopped", "idle", "loaded"] as Mode[]).map((m) => (
            <div key={m}>
              <dt>{MODE_LABELS[m]}</dt>
              <dd>
                {machine.modes[m]?.enabled ? "Tanımlı" : "Tanımlı değil"} — {machine.modes[m]?.description}
              </dd>
            </div>
          ))}
          {FEATURES.map((f) => (
            <div key={f.id}>
              <dt>{f.label}</dt>
              <dd>
                Beklenen aralık {fmtNum(machine.ranges[f.id][0], f.digits)}–{fmtNum(machine.ranges[f.id][1], f.digits)} {f.unit} ·
                alt sınır (feature_floor) {fmtNum(machine.floors[f.id], f.digits + 1)} {f.unit}
              </dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}
