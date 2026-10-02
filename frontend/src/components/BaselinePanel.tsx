import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { FEATURES, MODE_LABELS, fmtDateTime, fmtNum, fromIstanbulInput, toIstanbulInput } from "../format";
import type { Baseline, BaselinePreview, Machine, Mode } from "../types";
import { Icon } from "./Icon";
import { Message } from "./Message";

function StatsCells({ stats }: { stats: Baseline["stats"] }) {
  return (
    <>
      {FEATURES.map((f) => (
        <td key={f.id} className="nowrap">
          {fmtNum(stats[f.id].median, f.digits)} {f.unit}
          <div className="tiny muted">MAD {fmtNum(stats[f.id].mad, f.digits + 1)}</div>
        </td>
      ))}
    </>
  );
}

export function BaselinePanel({
  machine,
  baselines,
  chartRange,
  onCreated,
}: {
  machine: Machine;
  baselines: Baseline[];
  chartRange: { start: string; end: string } | null;
  onCreated: () => void;
}) {
  const runningModes = (["idle", "loaded"] as Mode[]).filter((m) => machine.modes[m]?.enabled);
  const [mode, setMode] = useState<Mode>(runningModes.includes("loaded") ? "loaded" : runningModes[0] ?? "idle");
  const [start, setStart] = useState(chartRange ? toIstanbulInput(chartRange.start) : "");
  const [end, setEnd] = useState(chartRange ? toIstanbulInput(chartRange.end) : "");
  const [note, setNote] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [preview, setPreview] = useState<BaselinePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    setPreview(null);
    setConfirm(false);
  }, [mode, start, end]);

  const active = baselines.filter((b) => b.is_active);
  const older = baselines.filter((b) => !b.is_active);

  const useChart = () => {
    if (!chartRange) return;
    setStart(toIstanbulInput(chartRange.start));
    setEnd(toIstanbulInput(chartRange.end));
  };

  const body = () => ({ mode, start: fromIstanbulInput(start), end: fromIstanbulInput(end), confirm_normal: confirm, note });

  const check = async () => {
    setError(null);
    setSuccess(null);
    if (!start || !end) {
      setError("Başlangıç ve bitiş zamanını seçin.");
      return;
    }
    setBusy(true);
    try {
      setPreview(await api.post<BaselinePreview>(`/api/machines/${machine.id}/baselines/preview`, body()));
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    setError(null);
    setSuccess(null);
    setBusy(true);
    try {
      const created = await api.post<Baseline>(`/api/machines/${machine.id}/baselines`, body());
      setSuccess(
        `Referans oluşturuldu: ${MODE_LABELS[created.mode]} v${created.version} (${created.sample_count} geçerli kayıt). ` +
          "Bundan sonraki ölçümler bu referansla karşılaştırılacak; eski uyarılar kendi referans sürümünü korur.",
      );
      setPreview(null);
      setConfirm(false);
      onCreated();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2>
        <Icon name="chart" /> Referans profilleri
      </h2>
      <p className="hint">
        Referans, seçtiğiniz "normal" aralıktaki her ölçümün medyanı ve MAD değeridir. Her çalışma modu için ayrıdır ve gelen
        ölçümlerle kendiliğinden güncellenmez. Durmuş makine için referans oluşturulmaz.
      </p>
      {active.length ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Mod</th>
                <th scope="col">Sürüm</th>
                <th scope="col">Oluşturulma</th>
                <th scope="col">Veri aralığı</th>
                <th scope="col">Kayıt</th>
                {FEATURES.map((f) => (
                  <th scope="col" key={f.id}>
                    {f.label} medyanı
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {active.map((b) => (
                <tr key={b.id}>
                  <td>{MODE_LABELS[b.mode]}</td>
                  <td>v{b.version}</td>
                  <td className="nowrap">{fmtDateTime(b.created_at)}</td>
                  <td className="nowrap">
                    {fmtDateTime(b.range_start)} –<br />
                    {fmtDateTime(b.range_end)}
                  </td>
                  <td>
                    {b.sample_count}
                    {b.excluded_count ? <div className="tiny muted">{b.excluded_count} kayıt hariç</div> : null}
                  </td>
                  <StatsCells stats={b.stats} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <Message kind="warning">Bu makine için referans yok. Referans oluşturulmalı; o zamana kadar sapma hesaplanmaz.</Message>
      )}
      {runningModes
        .filter((m) => !active.some((b) => b.mode === m))
        .map((m) => (
          <Message kind="warning" key={m}>
            {MODE_LABELS[m]} modu için referans yok — bu modda sapma hesaplanmıyor.
          </Message>
        ))}
      {older.length ? (
        <details className="details">
          <summary>Önceki referans sürümleri ({older.length})</summary>
          <ul>
            {older.map((b) => (
              <li key={b.id}>
                {MODE_LABELS[b.mode]} v{b.version} · {fmtDateTime(b.created_at)} · {b.sample_count} kayıt ·{" "}
                {fmtDateTime(b.range_start)} – {fmtDateTime(b.range_end)}
              </li>
            ))}
          </ul>
        </details>
      ) : null}

      <h3>Yeni referans oluştur</h3>
      <div className="form-grid">
        <label>
          Çalışma modu
          <select value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
            {runningModes.map((m) => (
              <option key={m} value={m}>
                {MODE_LABELS[m]}
              </option>
            ))}
          </select>
        </label>
        <label>
          Başlangıç (İstanbul)
          <input type="datetime-local" step={1} value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          Bitiş (İstanbul)
          <input type="datetime-local" step={1} value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <label>
          Not (isteğe bağlı)
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="ör. Bakım sonrası normal hafta" />
        </label>
      </div>
      <div className="actions">
        <button type="button" className="button secondary" onClick={useChart} disabled={!chartRange}>
          Grafikteki aralığı kullan
        </button>
        <button type="button" className="button secondary" onClick={check} disabled={busy}>
          Aralığı kontrol et
        </button>
      </div>
      {preview ? (
        <div className="preview-box">
          {preview.enough ? (
            <Message kind="info">
              Seçilen aralıkta {MODE_LABELS[preview.mode]} modunda <strong>{preview.valid_count}</strong> geçerli kayıt var
              (en az {preview.required} gerekli).
            </Message>
          ) : (
            <Message kind="warning">
              <strong>Referans için veri yetersiz.</strong> {preview.message}
            </Message>
          )}
          {Object.keys(preview.excluded).length ? (
            <p className="hint">
              Referansa katılmayan kayıtlar:{" "}
              {Object.entries(preview.excluded)
                .map(([reason, count]) => `${count} ${reason}`)
                .join(", ")}
              .
            </p>
          ) : null}
          {preview.overlapping_deviation_alerts ? (
            <Message kind="warning">
              Bu aralıkta {preview.overlapping_deviation_alerts} sapma uyarısı var. Bu aralığı gerçekten normal çalışma olarak kabul
              ediyorsanız devam edin; aksi halde süren bir sapma "normal" diye öğrenilir.
            </Message>
          ) : null}
          {preview.stats ? (
            <div className="table-wrap">
              <table className="table compact">
                <thead>
                  <tr>
                    {FEATURES.map((f) => (
                      <th scope="col" key={f.id}>
                        {f.label} medyanı
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <StatsCells stats={preview.stats} />
                  </tr>
                </tbody>
              </table>
            </div>
          ) : null}
          {preview.enough ? (
            <>
              <label className="checkbox">
                <input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
                <span>
                  Seçilen aralığı bu makinenin <strong>{MODE_LABELS[preview.mode]}</strong> modundaki normal çalışması olarak
                  kabul ediyorum.
                </span>
              </label>
              <div className="actions">
                <button type="button" className="button" onClick={create} disabled={!confirm || busy}>
                  <Icon name="check" size={16} /> Referansı oluştur
                </button>
              </div>
            </>
          ) : null}
        </div>
      ) : null}
      {error ? <Message kind="error">{error}</Message> : null}
      {success ? <Message kind="success">{success}</Message> : null}
    </section>
  );
}
