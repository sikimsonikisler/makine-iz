import { api } from "../api";
import { LevelPill, MeasurementPill, SourceTag, StatusPill } from "../components/Badges";
import { Icon, type IconName } from "../components/Icon";
import { Loading, Message } from "../components/Message";
import { MODE_LABELS, fmtDateTime, fmtDuration, fmtNum } from "../format";
import { usePolling } from "../hooks";
import type { MachineCard, Overview } from "../types";

function Tile({ icon, label, value, tone, hint }: { icon: IconName; label: string; value: number; tone: string; hint: string }) {
  return (
    <div className={`tile tile-${tone}`}>
      <Icon name={icon} size={26} />
      <div>
        <div className="tile-value">{value}</div>
        <div className="tile-label">{label}</div>
        <div className="tile-hint">{hint}</div>
      </div>
    </div>
  );
}

export function liveText(card: MachineCard): string {
  const { status, run } = card;
  if (status.live.kind === "sim_running" && run) return `Simülasyon çalışıyor (${fmtNum(run.speed, 0)}×)`;
  return status.live.label;
}

function MachineCardView({ card }: { card: MachineCard }) {
  const { machine, status } = card;
  return (
    <article className={`machine-card cat-${status.code === "strong" ? "danger" : status.category}`}>
      <header>
        <h3>
          <a href={`#/makine/${machine.id}`}>{machine.name}</a>
        </h3>
        <SourceTag source={machine.data_source} />
      </header>
      <dl className="facts">
        <div>
          <dt>Tür</dt>
          <dd>{machine.machine_type}</dd>
        </div>
        <div>
          <dt>Çalışma modu</dt>
          <dd>{status.current_mode ? MODE_LABELS[status.current_mode] : "—"}</dd>
        </div>
        <div>
          <dt>Veri kaynağı</dt>
          <dd>{liveText(card)}</dd>
        </div>
        <div>
          <dt>Son ölçüm</dt>
          <dd>
            {fmtDateTime(status.last_ts)}
            {status.live.virtual && status.last_ts ? <span className="muted"> (sanal zaman)</span> : null}
            {status.stale ? <strong className="stale"> — güncel değil ({fmtDuration(status.age_s)} önce)</strong> : null}
          </dd>
        </div>
      </dl>
      <div className="card-status">
        <StatusPill status={status} />
        {status.deviation_score !== null ? (
          <span className="score" title="min(100, 10 × en büyük z). Arıza olasılığı değildir.">
            Sapma puanı <strong>{fmtNum(status.deviation_score, 0)}</strong>/100
          </span>
        ) : null}
      </div>
      <p className="small">{status.detail}</p>
      {status.badges.length ? (
        <ul className="badge-list">
          {status.badges.map((badge) => (
            <li key={badge}>
              <Icon name="info" size={14} /> {badge}
            </li>
          ))}
        </ul>
      ) : null}
      <a className="button small secondary" href={`#/makine/${machine.id}`}>
        <Icon name="chart" size={15} /> Ayrıntı ve grafikler
      </a>
    </article>
  );
}

export function OverviewPage() {
  const { data, error, loading } = usePolling(() => api.get<Overview>("/api/overview"), [], 3000);
  if (loading && !data) return <Loading />;
  return (
    <div className="page">
      <h1>Genel görünüm</h1>
      <p className="lead">
        Her makine yalnızca kendi aynı çalışma modundaki referans davranışıyla karşılaştırılır. Uyarılar ölçüm sapmasını gösterir;
        arıza teşhisi değildir.
      </p>
      {error ? <Message kind="error">Veriler güncellenemedi: {error}</Message> : null}
      {data ? (
        <>
          <div className="tiles">
            <Tile icon="chart" label="Kayıtlı makine" value={data.counts.machines} tone="neutral" hint="Tüm veri kaynakları" />
            <Tile icon="check" label="Referansa uygun çalışan" value={data.counts.ok} tone="ok" hint="Son pencerede z < 3, veri sağlam" />
            <Tile
              icon="alert"
              label="İnceleme gerektiren"
              value={data.counts.needs_review}
              tone="review"
              hint="Aktif ya da incelemesi kapatılmamış sapma uyarısı"
            />
            <Tile icon="dataoff" label="Veri sorunu bulunan" value={data.counts.data_issue} tone="data_issue" hint="Eksik, donmuş veya gelmeyen veri" />
          </div>

          <h2>Makineler</h2>
          <div className="card-grid">
            {data.machines.map((card) => (
              <MachineCardView key={card.machine.id} card={card} />
            ))}
          </div>

          <h2>Son uyarılar</h2>
          {data.recent_alerts.length ? (
            <ul className="alert-list">
              {data.recent_alerts.map((alert) => (
                <li key={alert.id}>
                  <a href={`#/uyari/${alert.id}`} className="alert-row">
                    <span className="alert-id">#{alert.id}</span>
                    <LevelPill alert={alert} />
                    <span className="alert-machine">{alert.machine_name}</span>
                    <span className="muted">{alert.mode ? MODE_LABELS[alert.mode] : ""}</span>
                    <span className="nowrap">{fmtDateTime(alert.updated_at)}</span>
                    <MeasurementPill alert={alert} />
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Henüz uyarı yok.</p>
          )}
          <p>
            <a href="#/uyarilar">Tüm uyarıları filtreleyerek görüntüle →</a>
          </p>
        </>
      ) : null}
    </div>
  );
}
