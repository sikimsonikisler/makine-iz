import { useState } from "react";
import { ApiError, api, errorMessage, qs } from "../api";
import { Icon } from "../components/Icon";
import { Message } from "../components/Message";
import { FEATURES, MODE_LABELS, POINT_STATUS_LABELS, fmtDateTime, fromIstanbulInput } from "../format";
import { usePolling } from "../hooks";
import type { CsvIssue, CsvReport, ImportSummary, Machine, Mode } from "../types";

const COLUMNS: [string, string, string][] = [
  ["machine_id", "Makine kimliği (uygulamadaki kimlikle aynı)", "Zorunlu"],
  ["timestamp", "Ölçüm penceresinin BİTİŞ zamanı. ISO 8601; saat dilimi yoksa Europe/Istanbul kabul edilir", "Zorunlu"],
  ["operating_mode", "stopped, idle veya loaded", "Zorunlu"],
  ["vibration_rms_g", "Önceden hesaplanmış titreşim RMS değeri (g). Ham titreşim değil", "Zorunlu sütun (boş hücre = eksik ölçüm)"],
  ["temperature_c", "Sıcaklık (°C)", "Zorunlu sütun"],
  ["power_kw", "Elektrik gücü (kW)", "Zorunlu sütun"],
  ["rpm", "Devir (dev/dak)", "Zorunlu sütun"],
  ["source", "İsteğe bağlı; aktarılan kayıtlar her zaman 'csv' kaynağı olarak saklanır", "İsteğe bağlı"],
  ["quality_flags", "İsteğe bağlı; bilgi amaçlı saklanır, kalite işaretlerini uygulama kendisi hesaplar", "İsteğe bağlı"],
];

function IssueTable({ issues, kind }: { issues: CsvIssue[]; kind: "error" | "warning" }) {
  return (
    <div className="table-wrap">
      <table className={`table compact issues-${kind}`}>
        <thead>
          <tr>
            <th scope="col">Satır</th>
            <th scope="col">Alan</th>
            <th scope="col">{kind === "error" ? "Hata" : "Uyarı"}</th>
          </tr>
        </thead>
        <tbody>
          {issues.map((issue, i) => (
            <tr key={i}>
              <td>{issue.row ?? "—"}</td>
              <td>
                <code>{issue.field ?? "—"}</code>
              </td>
              <td>{issue.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DataImportPage() {
  const samples = usePolling(() => api.get<{ name: string; size: number }[]>("/api/csv/samples"), [], null);
  const machines = usePolling(() => api.get<Machine[]>("/api/machines"), [], null);
  const [fileName, setFileName] = useState("");
  const [content, setContent] = useState<string | null>(null);
  const [createMissing, setCreateMissing] = useState(false);
  const [report, setReport] = useState<CsvReport | null>(null);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportMachine, setExportMachine] = useState("");
  const [exportStart, setExportStart] = useState("");
  const [exportEnd, setExportEnd] = useState("");

  const validate = async (text: string, create: boolean) => {
    setBusy(true);
    setError(null);
    setSummary(null);
    try {
      setReport(await api.post<CsvReport>("/api/csv/preview", { content: text, filename: fileName, create_missing_machines: create }));
    } catch (e) {
      setReport(null);
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const onFile = async (file: File | undefined) => {
    setReport(null);
    setSummary(null);
    setError(null);
    if (!file) return;
    if (file.size > 20 * 1024 * 1024) {
      setError("Dosya 20 MB sınırını aşıyor.");
      return;
    }
    setFileName(file.name);
    const text = await file.text();
    setContent(text);
    await validate(text, createMissing);
  };

  const doImport = async () => {
    if (!content) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<ImportSummary>("/api/csv/import", {
        content,
        filename: fileName,
        create_missing_machines: createMissing,
      });
      setSummary(result);
      setReport(null);
      setContent(null);
      void machines.reload();
    } catch (e) {
      if (e instanceof ApiError && (e.body as { report?: CsvReport } | null)?.report) {
        setReport((e.body as { report: CsvReport }).report);
      }
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const exportParams = {
    machine_id: exportMachine || undefined,
    start: exportStart ? fromIstanbulInput(exportStart) : undefined,
    end: exportEnd ? fromIstanbulInput(exportEnd) : undefined,
  };

  return (
    <div className="page">
      <h1>Veri aktarımı</h1>
      <p className="lead">
        CSV dosyasındaki ölçümler simülasyon ve sensör verisiyle aynı doğrulama ve analiz yolundan geçer. Dosya önce doğrulanır; hata
        varsa hiçbir satır aktarılmaz.
      </p>

      <section className="panel">
        <h2>1. CSV biçimi ve örnek dosyalar</h2>
        <div className="table-wrap">
          <table className="table compact">
            <thead>
              <tr>
                <th scope="col">Sütun</th>
                <th scope="col">Anlamı</th>
                <th scope="col">Durum</th>
              </tr>
            </thead>
            <tbody>
              {COLUMNS.map(([column, meaning, required]) => (
                <tr key={column}>
                  <td>
                    <code>{column}</code>
                  </td>
                  <td>{meaning}</td>
                  <td>{required}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint">
          Ayraç virgül (,) veya noktalı virgül (;) olabilir. Noktalı virgüllü dosyalarda ondalık virgül (0,15) kabul edilir. Yinelenen
          kayıt politikası: aynı makine + aynı zaman damgası → ilk kayıt korunur, sonrakiler atlanır.
        </p>
        <div className="sample-list">
          {(samples.data ?? []).map((s) => (
            <a key={s.name} className="button secondary small" href={`/api/csv/samples/${s.name}`} download>
              <Icon name="download" size={15} /> {s.name}
            </a>
          ))}
        </div>
        <p className="hint">
          Deneme sırası: <code>ornek_referans.csv</code> dosyasını "yeni makine olarak ekle" seçeneğiyle aktarın → makine sayfasında
          Boşta ve Yük altında için referans oluşturun → <code>ornek_izleme.csv</code> dosyasını aktarın. <code>ornek_hatali.csv</code>{" "}
          hata gösterimini dener.
        </p>
      </section>

      <section className="panel">
        <h2>2. Dosya yükle ve doğrula</h2>
        <div className="form-grid">
          <label className="file-input">
            CSV dosyası
            <input type="file" accept=".csv,text/csv" onChange={(e) => void onFile(e.target.files?.[0])} />
          </label>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={createMissing}
              onChange={(e) => {
                setCreateMissing(e.target.checked);
                if (content) void validate(content, e.target.checked);
              }}
            />
            Bilinmeyen makine kimliklerini yeni makine olarak ekle (veri kaynağı: CSV)
          </label>
        </div>
        {busy ? <p className="muted">İşleniyor…</p> : null}
        {error ? <Message kind="error">{error}</Message> : null}
        {report ? (
          <div className="report">
            {report.ok ? (
              <Message kind="success">
                Doğrulama başarılı: {report.summary.importable_rows} satır aktarılabilir
                {report.warning_count ? `, ${report.warning_count} uyarı var (aşağıda)` : ""}. Henüz hiçbir şey aktarılmadı.
              </Message>
            ) : (
              <Message kind="error">
                Dosyada {report.error_count} hata var. <strong>Hiçbir satır aktarılmayacak.</strong> Hataları düzeltip dosyayı yeniden
                yükleyin.
              </Message>
            )}
            <div className="tiles small-tiles">
              <div className="tile tile-neutral">
                <div>
                  <div className="tile-value">{report.summary.data_rows}</div>
                  <div className="tile-label">veri satırı</div>
                </div>
              </div>
              <div className="tile tile-ok">
                <div>
                  <div className="tile-value">{report.summary.importable_rows}</div>
                  <div className="tile-label">aktarılacak</div>
                </div>
              </div>
              <div className="tile tile-review">
                <div>
                  <div className="tile-value">{report.summary.duplicates_in_file + report.summary.duplicates_existing}</div>
                  <div className="tile-label">yinelenen (atlanacak)</div>
                </div>
              </div>
              <div className="tile tile-data_issue">
                <div>
                  <div className="tile-value">{report.summary.missing_values + report.summary.invalid_values}</div>
                  <div className="tile-label">eksik / geçersiz değer</div>
                </div>
              </div>
            </div>
            {report.infos.length ? (
              <ul className="info-list">
                {report.infos.map((info) => (
                  <li key={info}>{info}</li>
                ))}
              </ul>
            ) : null}
            {report.summary.machines.length ? (
              <p>
                Makineler:{" "}
                {report.summary.machines
                  .map((m) => `${m.name ?? m.machine_id}${m.new ? " (yeni eklenecek)" : ""}: ${m.rows} satır, ${fmtDateTime(m.first_ts)} – ${fmtDateTime(m.last_ts)}`)
                  .join(" · ")}
              </p>
            ) : null}
            {report.errors.length ? (
              <>
                <h3>Hatalar ({report.error_count})</h3>
                <IssueTable issues={report.errors} kind="error" />
              </>
            ) : null}
            {report.warnings.length ? (
              <details className="details" open={report.warning_count <= 20}>
                <summary>Uyarılar ({report.warning_count}) — bu satırlar aktarılır ve işaretlenir</summary>
                <IssueTable issues={report.warnings} kind="warning" />
              </details>
            ) : null}
            {report.preview.length ? (
              <details className="details">
                <summary>Önizleme (ilk {report.preview.length} geçerli satır)</summary>
                <div className="table-wrap">
                  <table className="table compact">
                    <thead>
                      <tr>
                        <th scope="col">Satır</th>
                        <th scope="col">Makine</th>
                        <th scope="col">Zaman (İstanbul)</th>
                        <th scope="col">Mod</th>
                        {FEATURES.map((f) => (
                          <th scope="col" key={f.id}>
                            {f.label} ({f.unit})
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {report.preview.map((row) => (
                        <tr key={row.row} className={row.skip ? "row-muted" : ""}>
                          <td>{row.row}</td>
                          <td>{row.machine_id}</td>
                          <td className="nowrap">{fmtDateTime(String(row.timestamp))}</td>
                          <td>{MODE_LABELS[row.operating_mode as Mode] ?? row.operating_mode}</td>
                          {FEATURES.map((f) => (
                            <td key={f.id}>{row[f.id] === null ? <em>eksik</em> : String(row[f.id])}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            ) : null}
            <div className="actions">
              <button type="button" className="button" onClick={doImport} disabled={!report.ok || busy || !content}>
                <Icon name="upload" size={16} /> Aktar ({report.summary.importable_rows} satır)
              </button>
            </div>
          </div>
        ) : null}
        {summary ? (
          <div className="report">
            <Message kind="success">
              Aktarım tamamlandı: <strong>{summary.imported_rows}</strong> satır aktarıldı, {summary.skipped_duplicates} yinelenen satır
              atlandı, {summary.flagged_rows} kayıt veri sorunu nedeniyle işaretlendi.
            </Message>
            <ul className="info-list">
              <li>Yinelenen kayıt politikası: {summary.duplicate_policy}</li>
              {summary.created_machines.length ? <li>Yeni eklenen makineler: {summary.created_machines.join(", ")}</li> : null}
              <li>
                Analiz sonuçları:{" "}
                {Object.entries(summary.analysis_statuses)
                  .map(([s, n]) => `${POINT_STATUS_LABELS[s] ?? s}: ${n}`)
                  .join(", ")}
              </li>
            </ul>
            <div className="actions">
              {summary.machines.map((m) => (
                <a key={m.machine_id} className="button secondary small" href={`#/makine/${m.machine_id}`}>
                  <Icon name="chart" size={15} /> {m.machine_id} ayrıntısı
                </a>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      <section className="panel">
        <h2>3. Dışa aktarım</h2>
        <div className="form-grid">
          <label>
            Makine
            <select value={exportMachine} onChange={(e) => setExportMachine(e.target.value)}>
              <option value="">Tüm makineler</option>
              {(machines.data ?? []).map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Başlangıç (İstanbul, isteğe bağlı)
            <input type="datetime-local" value={exportStart} onChange={(e) => setExportStart(e.target.value)} />
          </label>
          <label>
            Bitiş (İstanbul, isteğe bağlı)
            <input type="datetime-local" value={exportEnd} onChange={(e) => setExportEnd(e.target.value)} />
          </label>
        </div>
        <div className="actions">
          <a className="button secondary" href={`/api/export/telemetry.csv${qs(exportParams)}`}>
            <Icon name="download" size={16} /> Ölçümleri indir (CSV)
          </a>
          <a className="button secondary" href={`/api/export/alerts.csv${qs(exportParams)}`}>
            <Icon name="download" size={16} /> Uyarıları indir (CSV)
          </a>
        </div>
        <p className="hint">Dışa aktarılan ölçüm dosyası UTC ve İstanbul zamanını, kalite işaretlerini, z değerini ve referans sürümünü içerir.</p>
      </section>

      <section className="panel">
        <h2>4. Gerçek sensörler için veri arayüzü</h2>
        <p>
          İleride bir veri toplama cihazı (ör. titreşim RMS'ini hesaplayan bir ağ geçidi) ölçümleri doğrudan gönderebilir. Bu kayıtlar da
          aynı doğrulama ve analiz yolundan geçer.
        </p>
        <pre className="code">{`POST http://127.0.0.1:8000/api/telemetry
Content-Type: application/json

{"records": [
  {"machine_id": "kompresor-1", "timestamp": "2026-10-02T14:30:05+03:00",
   "operating_mode": "loaded", "vibration_rms_g": 0.181, "temperature_c": 67.9,
   "power_kw": 22.1, "rpm": 2941}
]}`}</pre>
        <p className="hint">
          Veri kaynağı "Sensör" olan makinede 3 beklenen ölçüm aralığı boyunca kayıt gelmezse "Veri gelmiyor" gösterilir.
        </p>
      </section>
    </div>
  );
}
