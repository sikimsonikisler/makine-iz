import { useEffect, useState } from "react";
import { api, errorMessage, qs } from "../api";
import { LevelPill, MeasurementPill, ReviewPill } from "../components/Badges";
import { Icon } from "../components/Icon";
import { Loading, Message } from "../components/Message";
import { NotesPanel } from "../components/NotesPanel";
import {
  ASSESSMENT_LABELS,
  DQ_LABELS,
  MODE_LABELS,
  REVIEW_LABELS,
  SOURCE_LABELS,
  flagLabel,
  fmtDateTime,
  fmtDuration,
  fmtNum,
  fmtSigned,
  fmtValue,
} from "../format";
import { usePolling } from "../hooks";
import type { Alert, Baseline, Note, WindowSummary } from "../types";

interface AlertDetailResponse {
  alert: Alert;
  baseline: Baseline | null;
  current_baseline_version: number | null;
  notes: Note[];
}

function ChangeTable({ summary }: { summary: WindowSummary }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">Ölçüm</th>
            <th scope="col">Son değer</th>
            <th scope="col">Referans medyanı</th>
            <th scope="col">Referanstan fark</th>
            <th scope="col">Fark %</th>
            <th scope="col">z (son pencere)</th>
            <th scope="col">Ortalama z (5 pencere)</th>
          </tr>
        </thead>
        <tbody>
          {summary.features.map((item, index) => (
            <tr key={item.feature} className={index < 2 ? "row-highlight" : ""}>
              <td>
                {item.label}
                {index < 2 ? <span className="tag tag-warn">en çok değişen</span> : null}
              </td>
              <td className="nowrap">{fmtValue(item.feature, item.value)}</td>
              <td className="nowrap">{fmtValue(item.feature, item.median)}</td>
              <td className="nowrap">{fmtSigned(item.feature, item.diff)}</td>
              <td>{item.diff_pct === null ? "—" : `${item.diff_pct >= 0 ? "+" : "−"}${fmtNum(Math.abs(item.diff_pct), 0)} %`}</td>
              <td>{fmtNum(item.z, 1)}</td>
              <td>{fmtNum(item.mean_z, 1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AlertDetailPage({ alertId }: { alertId: number }) {
  const detail = usePolling(() => api.get<AlertDetailResponse>(`/api/alerts/${alertId}`), [alertId], 5000);
  const [review, setReview] = useState("");
  const [assessment, setAssessment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const alert = detail.data?.alert;

  useEffect(() => {
    if (alert) {
      setReview(alert.review_status);
      setAssessment(alert.assessment ?? "");
    }
  }, [alert?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (detail.error && !alert) return <Message kind="error">{detail.error}</Message>;
  if (!alert || !detail.data) return <Loading />;

  const save = async () => {
    setBusy(true);
    setError(null);
    setSuccess(null);
    try {
      await api.patch<Alert>(`/api/alerts/${alert.id}`, {
        review_status: review,
        assessment: assessment || null,
        clear_assessment: !assessment,
      });
      setSuccess("İnceleme kaydı güncellendi. Ölçüm durumu ve referans bundan etkilenmez.");
      await detail.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const isDeviation = alert.kind === "deviation";
  const startMs = Date.parse(alert.started_at);
  const endMs = Date.parse(alert.ended_at ?? alert.updated_at);
  const chartLink = `#/makine/${alert.machine_id}${qs({
    start: new Date(startMs - 15 * 60000).toISOString(),
    end: new Date(endMs + 15 * 60000).toISOString(),
  })}`;
  const { baseline, current_baseline_version: currentVersion } = detail.data;

  return (
    <div className="page">
      <p className="breadcrumb">
        <a href="#/uyarilar">Uyarılar</a> / #{alert.id}
      </p>
      <h1>
        Uyarı #{alert.id} <LevelPill alert={alert} />
      </h1>
      {detail.error ? <Message kind="error">Veriler güncellenemedi: {detail.error}</Message> : null}

      <section className="panel">
        <dl className="facts facts-grid">
          <div>
            <dt>Makine</dt>
            <dd>
              <a href={`#/makine/${alert.machine_id}`}>{alert.machine_name}</a>
              {alert.source ? <span className="muted"> · kaynak: {SOURCE_LABELS[alert.source] ?? alert.source}</span> : null}
            </dd>
          </div>
          <div>
            <dt>Çalışma modu</dt>
            <dd>{alert.mode ? MODE_LABELS[alert.mode] : "—"}</dd>
          </div>
          <div>
            <dt>Başlangıç</dt>
            <dd>{fmtDateTime(alert.started_at)}</dd>
          </div>
          <div>
            <dt>Son güncelleme</dt>
            <dd>{fmtDateTime(alert.updated_at)}</dd>
          </div>
          <div>
            <dt>Bitiş</dt>
            <dd>{alert.ended_at ? fmtDateTime(alert.ended_at) : "Sürüyor"}</dd>
          </div>
          {isDeviation ? (
            <div>
              <dt>Kullanılan referans sürümü</dt>
              <dd>
                {alert.mode ? MODE_LABELS[alert.mode] : ""} v{alert.baseline_version}
                {baseline ? ` (${baseline.sample_count} kayıt, ${fmtDateTime(baseline.range_start)} – ${fmtDateTime(baseline.range_end)})` : ""}
                {currentVersion && currentVersion !== alert.baseline_version ? (
                  <div className="tiny">Bu mod için güncel referans artık v{currentVersion}; bu uyarı kendi sürümünü korur.</div>
                ) : null}
              </dd>
            </div>
          ) : null}
          <div>
            <dt>Ölçüm durumu</dt>
            <dd>
              <MeasurementPill alert={alert} />
              {alert.unevaluable_reason ? <div className="tiny">{alert.unevaluable_reason}</div> : null}
            </dd>
          </div>
          <div>
            <dt>İnceleme durumu</dt>
            <dd>
              <ReviewPill status={alert.review_status} />
              {alert.assessment ? <div className="tiny">Değerlendirme: {ASSESSMENT_LABELS[alert.assessment]}</div> : null}
            </dd>
          </div>
        </dl>
        <div className="explanation">
          <Icon name="info" />
          <p>{alert.explanation}</p>
        </div>
        <a className="button secondary" href={chartLink}>
          <Icon name="chart" size={16} /> Bu dönemi grafikte göster
        </a>
      </section>

      {isDeviation && alert.details.latest ? (
        <section className="panel">
          <h2>Uyarıyı tetikleyen ölçümler</h2>
          <p className="hint">
            Son 5 geçerli pencerenin {alert.details.hits} tanesinde z ≥ 3
            {alert.details.strong_hits ? `, ${alert.details.strong_hits} tanesinde z ≥ 6` : ""}. Pencerelerin z değerleri:{" "}
            {alert.details.latest.window_z.map((z) => fmtNum(z, 1)).join(" · ")}. En yüksek z: {fmtNum(alert.peak_z, 1)}. Uyarı{" "}
            {alert.details.updates ?? 0} kez güncellendi (devam eden olay için yeni uyarı açılmaz).
          </p>
          <h3>Son güncellemede</h3>
          <ChangeTable summary={alert.details.latest} />
          {alert.details.initial && alert.details.updates ? (
            <details className="details">
              <summary>Uyarı ilk oluştuğunda</summary>
              <ChangeTable summary={alert.details.initial} />
            </details>
          ) : null}
        </section>
      ) : null}

      {!isDeviation ? (
        <section className="panel">
          <h2>Veri sorunu ayrıntısı</h2>
          <dl className="facts">
            <div>
              <dt>Tür</dt>
              <dd>{DQ_LABELS[alert.dq_type ?? ""] ?? alert.dq_type}</dd>
            </div>
            <div>
              <dt>Sayı</dt>
              <dd>{String(alert.details.count ?? 1)}</dd>
            </div>
            {alert.details.last_flags?.length ? (
              <div>
                <dt>Son işaretler</dt>
                <dd>{alert.details.last_flags.map(flagLabel).join(", ")}</dd>
              </div>
            ) : null}
            {alert.dq_type === "sequence" ? (
              <div>
                <dt>Yinelenen / sırası bozuk</dt>
                <dd>
                  {alert.details.duplicates ?? 0} / {alert.details.out_of_order ?? 0}
                </dd>
              </div>
            ) : null}
            {alert.details.duration_s ? (
              <div>
                <dt>Kesinti süresi</dt>
                <dd>{fmtDuration(alert.details.duration_s)}</dd>
              </div>
            ) : null}
          </dl>
          <p className="hint">Veri kalitesi sorunları makine davranışındaki sapmadan ayrı tutulur; bu kayıtlar sapma hesabına alınmaz.</p>
        </section>
      ) : null}

      <section className="panel">
        <h2>İnceleme ve değerlendirme</h2>
        <p className="hint">
          Uyarıyı gördüğünüzü veya kapattığınızı işaretlemek, ölçümlerin normale döndüğü anlamına gelmez. Değerlendirmeniz referansı
          değiştirmez.
        </p>
        <div className="form-grid">
          <label>
            İnceleme durumu
            <select value={review} onChange={(e) => setReview(e.target.value)}>
              {Object.entries(REVIEW_LABELS).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Değerlendirme
            <select value={assessment} onChange={(e) => setAssessment(e.target.value)}>
              <option value="">Henüz yok</option>
              {Object.entries(ASSESSMENT_LABELS).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="actions">
          <button type="button" className="button" onClick={save} disabled={busy}>
            <Icon name="check" size={16} /> {busy ? "Kaydediliyor…" : "İncelemeyi kaydet"}
          </button>
        </div>
        {error ? <Message kind="error">{error}</Message> : null}
        {success ? <Message kind="success">{success}</Message> : null}
      </section>

      <NotesPanel machineId={alert.machine_id} alertId={alert.id} title="Bu uyarıya ait notlar" />
    </div>
  );
}
