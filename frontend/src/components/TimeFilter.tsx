import { useEffect, useState } from "react";
import { fromIstanbulInput, toIstanbulInput } from "../format";

export type RangePreset = "15m" | "1h" | "6h" | "24h" | "all" | "custom";

export interface RangeState {
  preset: RangePreset;
  start?: string; // özel aralık (UTC ISO)
  end?: string;
}

const PRESETS: { id: RangePreset; label: string; ms: number | null }[] = [
  { id: "15m", label: "Son 15 dk", ms: 15 * 60000 },
  { id: "1h", label: "Son 1 saat", ms: 3600000 },
  { id: "6h", label: "Son 6 saat", ms: 6 * 3600000 },
  { id: "24h", label: "Son 24 saat", ms: 24 * 3600000 },
  { id: "all", label: "Tümü", ms: null },
];

/** Hazır süreler makinenin SON ÖLÇÜMÜNDEN geriye doğru hesaplanır (simülasyonda sanal zaman, CSV'de geçmiş veri). */
export function resolveRange(state: RangeState, firstTs: string | null, lastTs: string | null): { start: string; end: string } | null {
  if (!firstTs || !lastTs) return null;
  if (state.preset === "custom" && state.start && state.end) return { start: state.start, end: state.end };
  const preset = PRESETS.find((p) => p.id === state.preset);
  const end = Date.parse(lastTs);
  const first = Date.parse(firstTs);
  const start = preset?.ms ? Math.max(first, end - preset.ms) : first;
  return { start: new Date(start).toISOString(), end: new Date(end).toISOString() };
}

export function TimeFilter({
  value,
  onChange,
  current,
}: {
  value: RangeState;
  onChange: (next: RangeState) => void;
  current: { start: string; end: string } | null;
}) {
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (value.preset !== "custom" && current) {
      setStart(toIstanbulInput(current.start));
      setEnd(toIstanbulInput(current.end));
    }
  }, [value.preset, current?.start, current?.end]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyCustom = () => {
    if (!start || !end) {
      setError("Başlangıç ve bitiş zamanını girin.");
      return;
    }
    const s = fromIstanbulInput(start);
    const e = fromIstanbulInput(end);
    if (Date.parse(e) <= Date.parse(s)) {
      setError("Bitiş, başlangıçtan sonra olmalı.");
      return;
    }
    setError(null);
    onChange({ preset: "custom", start: s, end: e });
  };

  return (
    <div className="time-filter">
      <div className="segmented" role="group" aria-label="Zaman aralığı">
        {PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={value.preset === p.id ? "active" : ""}
            aria-pressed={value.preset === p.id}
            onClick={() => onChange({ preset: p.id })}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="custom-range">
        <label>
          Başlangıç (İstanbul)
          <input type="datetime-local" step={1} value={start} onChange={(e) => setStart(e.target.value)} />
        </label>
        <label>
          Bitiş (İstanbul)
          <input type="datetime-local" step={1} value={end} onChange={(e) => setEnd(e.target.value)} />
        </label>
        <button type="button" className="button secondary" onClick={applyCustom}>
          Aralığı uygula
        </button>
      </div>
      {error ? <p className="field-error">{error}</p> : null}
      <p className="hint">Hazır süreler, makinenin son ölçümünden geriye doğru hesaplanır.</p>
    </div>
  );
}
