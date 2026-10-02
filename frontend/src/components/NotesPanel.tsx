import { useState } from "react";
import { api, errorMessage, qs } from "../api";
import { ASSESSMENT_LABELS, NOTE_TYPE_LABELS, fmtDateTime } from "../format";
import { usePolling } from "../hooks";
import type { Note } from "../types";
import { Icon } from "./Icon";
import { Message } from "./Message";

export function NotesPanel({ machineId, alertId, title = "Notlar" }: { machineId: string; alertId?: number; title?: string }) {
  const notes = usePolling(() => api.get<Note[]>(`/api/notes${qs({ machine_id: machineId, alert_id: alertId })}`), [machineId, alertId], null);
  const [text, setText] = useState("");
  const [author, setAuthor] = useState("");
  const [noteType, setNoteType] = useState<Note["note_type"]>(alertId ? "inspection" : "maintenance");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const save = async () => {
    setError(null);
    setSuccess(null);
    if (!text.trim()) {
      setError("Not metni boş olamaz.");
      return;
    }
    setBusy(true);
    try {
      await api.post<Note>("/api/notes", { machine_id: machineId, alert_id: alertId ?? null, text, author, note_type: noteType });
      setText("");
      setSuccess("Not kaydedildi.");
      await notes.reload();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2>
        <Icon name="note" /> {title}
      </h2>
      <div className="form-grid">
        <label>
          Not türü
          <select value={noteType} onChange={(e) => setNoteType(e.target.value as Note["note_type"])}>
            {Object.entries(NOTE_TYPE_LABELS).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Yazan (isteğe bağlı)
          <input value={author} onChange={(e) => setAuthor(e.target.value)} maxLength={80} placeholder="ör. Bakım ekibi" />
        </label>
        <label className="span-2">
          Not
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={3}
            placeholder="Ne kontrol edildi, ne bulundu, ne yapıldı?"
          />
        </label>
      </div>
      <div className="actions">
        <button type="button" className="button" onClick={save} disabled={busy}>
          <Icon name="plus" size={16} /> {busy ? "Kaydediliyor…" : "Notu kaydet"}
        </button>
      </div>
      {error ? <Message kind="error">{error}</Message> : null}
      {success ? <Message kind="success">{success}</Message> : null}
      {notes.error ? <Message kind="error">Notlar yüklenemedi: {notes.error}</Message> : null}
      <ul className="notes">
        {(notes.data ?? []).map((note) => (
          <li key={note.id}>
            <div className="note-meta">
              <span className="tag">{NOTE_TYPE_LABELS[note.note_type] ?? note.note_type}</span>
              <span>{fmtDateTime(note.created_at)}</span>
              {note.author ? <span>· {note.author}</span> : null}
              {note.assessment ? <span>· Değerlendirme: {ASSESSMENT_LABELS[note.assessment]}</span> : null}
              {!alertId && note.alert_id ? (
                <a href={`#/uyari/${note.alert_id}`}>· Uyarı #{note.alert_id}</a>
              ) : null}
              {!alertId && !note.alert_id && note.alert_snapshot ? (
                <span className="muted">· Bağlı uyarı artık yok ({note.alert_snapshot})</span>
              ) : null}
            </div>
            <p>{note.text}</p>
          </li>
        ))}
        {notes.data && notes.data.length === 0 ? <li className="muted">Henüz not yok.</li> : null}
      </ul>
    </section>
  );
}
