import type { Alert } from "../types";
import { ASSESSMENT_LABELS, MODE_LABELS, fmtDateTime } from "../format";
import { LevelPill, MeasurementPill, ReviewPill } from "./Badges";
import { Icon } from "./Icon";

export function AlertTable({ alerts, showMachine = true, empty = "Uyarı yok." }: { alerts: Alert[]; showMachine?: boolean; empty?: string }) {
  if (!alerts.length) return <p className="muted">{empty}</p>;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th scope="col">#</th>
            {showMachine ? <th scope="col">Makine</th> : null}
            <th scope="col">Uyarı</th>
            <th scope="col">Mod</th>
            <th scope="col">Başlangıç</th>
            <th scope="col">Son güncelleme</th>
            <th scope="col">Ölçüm durumu</th>
            <th scope="col">İnceleme</th>
            <th scope="col">Değerlendirme</th>
            <th scope="col">
              <span className="sr-only">Ayrıntı</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((alert) => (
            <tr key={alert.id}>
              <td>{alert.id}</td>
              {showMachine ? (
                <td>
                  <a href={`#/makine/${alert.machine_id}`}>{alert.machine_name}</a>
                  {alert.source === "simulation" ? <div className="tiny muted">Simülasyon verisi</div> : null}
                </td>
              ) : null}
              <td>
                <LevelPill alert={alert} />
              </td>
              <td>{alert.mode ? MODE_LABELS[alert.mode] : "—"}</td>
              <td className="nowrap">{fmtDateTime(alert.started_at)}</td>
              <td className="nowrap">{fmtDateTime(alert.updated_at)}</td>
              <td>
                <MeasurementPill alert={alert} />
              </td>
              <td>
                <ReviewPill status={alert.review_status} />
              </td>
              <td>{alert.assessment ? ASSESSMENT_LABELS[alert.assessment] : "—"}</td>
              <td>
                <a className="button small secondary" href={`#/uyari/${alert.id}`}>
                  <Icon name="eye" size={15} /> Ayrıntı
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
