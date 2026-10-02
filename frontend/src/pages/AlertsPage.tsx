import { useState } from "react";
import { api, qs } from "../api";
import { AlertTable } from "../components/AlertTable";
import { Icon } from "../components/Icon";
import { Loading, Message } from "../components/Message";
import { DQ_LABELS, LEVEL_LABELS, MEASUREMENT_LABELS, REVIEW_LABELS, fromIstanbulInput } from "../format";
import { usePolling } from "../hooks";
import type { Alert, Machine } from "../types";

interface Filters {
  machine_id: string;
  level: string;
  review_status: string;
  measurement_status: string;
  start: string; // İstanbul yerel (datetime-local)
  end: string;
}

const EMPTY: Filters = { machine_id: "", level: "", review_status: "", measurement_status: "", start: "", end: "" };

export function AlertsPage({ query }: { query: URLSearchParams }) {
  const [filters, setFilters] = useState<Filters>({ ...EMPTY, machine_id: query.get("makine") ?? "" });
  const machines = usePolling(() => api.get<Machine[]>("/api/machines"), [], null);
  const params = {
    machine_id: filters.machine_id || undefined,
    level: filters.level || undefined,
    review_status: filters.review_status || undefined,
    measurement_status: filters.measurement_status || undefined,
    start: filters.start ? fromIstanbulInput(filters.start) : undefined,
    end: filters.end ? fromIstanbulInput(filters.end) : undefined,
  };
  const key = JSON.stringify(params);
  const alerts = usePolling(() => api.get<Alert[]>(`/api/alerts${qs(params)}`), [key], 5000);
  const set = (field: keyof Filters) => (e: { target: { value: string } }) => setFilters({ ...filters, [field]: e.target.value });

  return (
    <div className="page">
      <h1>Uyarılar</h1>
      <p className="lead">
        Sapma uyarıları ölçümlerin referanstan sürekli ayrıldığını gösterir; veri sorunu uyarıları ise verinin kendisindeki sorunları
        (eksik, donmuş, gelmeyen veri) ayrı tutar. "Ölçüm durumu" ölçümlerden, "İnceleme" sizin kaydınızdan gelir.
      </p>
      <section className="panel">
        <h2>Filtreler</h2>
        <div className="form-grid filters">
          <label>
            Makine
            <select value={filters.machine_id} onChange={set("machine_id")}>
              <option value="">Tümü</option>
              {(machines.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Uyarı düzeyi
            <select value={filters.level} onChange={set("level")}>
              <option value="">Tümü</option>
              <option value="review">{LEVEL_LABELS.review}</option>
              <option value="strong">{LEVEL_LABELS.strong}</option>
              <option value="data">Veri sorunu ({Object.values(DQ_LABELS).join(", ")})</option>
            </select>
          </label>
          <label>
            İnceleme durumu
            <select value={filters.review_status} onChange={set("review_status")}>
              <option value="">Tümü</option>
              {Object.entries(REVIEW_LABELS).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Ölçüm durumu
            <select value={filters.measurement_status} onChange={set("measurement_status")}>
              <option value="">Tümü</option>
              {Object.entries(MEASUREMENT_LABELS).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Başlangıç tarihi (İstanbul)
            <input type="datetime-local" value={filters.start} onChange={set("start")} />
          </label>
          <label>
            Bitiş tarihi (İstanbul)
            <input type="datetime-local" value={filters.end} onChange={set("end")} />
          </label>
        </div>
        <div className="actions">
          <button type="button" className="button secondary" onClick={() => setFilters(EMPTY)}>
            Filtreleri temizle
          </button>
          <a className="button secondary" href={`/api/export/alerts.csv${qs(params)}`}>
            <Icon name="download" size={16} /> Bu listeyi CSV olarak indir
          </a>
        </div>
      </section>
      {alerts.error ? <Message kind="error">Uyarılar yüklenemedi: {alerts.error}</Message> : null}
      {alerts.loading && !alerts.data ? <Loading /> : null}
      {alerts.data ? (
        <section className="panel">
          <h2>{alerts.data.length} uyarı</h2>
          <AlertTable alerts={alerts.data} empty="Bu filtrelere uyan uyarı yok." />
        </section>
      ) : null}
    </div>
  );
}
