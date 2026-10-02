// Zaman grafikleri: her ölçüm kendi ekseninde ve kendi birimiyle. Eksik veride çizgi kesilir
// (boşluk gerçek ölçüm varmış gibi doldurulmaz). z ≥ 3 olan noktalar, değişen ölçümün grafiğinde işaretlenir.
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { BaselineSummary, FeatureId, SeriesPoint } from "../types";
import {
  FEATURE_MAP,
  FEATURES,
  MODE_LABELS,
  MODE_ORDER,
  POINT_STATUS_LABELS,
  flagLabel,
  fmtAxisTime,
  fmtDateTime,
  fmtNum,
  fmtValue,
} from "../format";

const MAD_SCALE = 1.4826;
const GRID = "#e4e7ec";

interface ChartsProps {
  points: SeriesPoint[];
  baseline: BaselineSummary | null;
  floors: Record<FeatureId, number>;
  compact?: boolean;
}

interface ChartPoint extends SeriesPoint {
  modeIndex: number | null;
  dq: number | null;
}

export function TelemetryCharts({ points, baseline, floors, compact = false }: ChartsProps) {
  if (!points.length) {
    return <p className="muted">Seçilen aralıkta ölçüm yok.</p>;
  }
  const data: ChartPoint[] = points.map((p) => ({
    ...p,
    modeIndex: p.mode ? MODE_ORDER.indexOf(p.mode) : null,
    dq: p.status === "invalid" || p.status === "frozen_suspect" ? 0 : null,
  }));
  const domain: [number, number] = [data[0].t, data[data.length - 1].t];
  const span = domain[1] - domain[0];
  const height = compact ? 120 : 165;
  const xAxis = (
    <XAxis
      dataKey="t"
      type="number"
      scale="time"
      domain={domain}
      tickFormatter={(v: number) => fmtAxisTime(v, span)}
      minTickGap={48}
      tick={{ fontSize: 12 }}
    />
  );

  return (
    <div className="charts">
      <figure className="chart">
        <figcaption>
          <strong>Çalışma modu</strong>
        </figcaption>
        <ResponsiveContainer width="100%" height={compact ? 90 : 100}>
          <LineChart data={data} syncId="makine" margin={{ top: 6, right: 16, bottom: 0, left: 4 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
            {xAxis}
            <YAxis
              domain={[-0.2, 2.2]}
              ticks={[0, 1, 2]}
              interval={0}
              width={96}
              tick={{ fontSize: 12 }}
              tickFormatter={(v: number) => MODE_LABELS[MODE_ORDER[v]] ?? ""}
            />
            <Tooltip content={<PointTooltip />} />
            <Line
              type="stepAfter"
              dataKey="modeIndex"
              stroke="#344054"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
              connectNulls={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </figure>

      {FEATURES.map((info) => {
        const stat = baseline?.stats[info.id];
        const scale = stat ? Math.max(MAD_SCALE * stat.mad, floors[info.id]) : null;
        return (
          <figure className="chart" key={info.id}>
            <figcaption>
              <strong>{info.label}</strong> <span className="unit">({info.unit})</span>
              {stat && baseline ? (
                <span className="legend">
                  <span className="legend-dash" aria-hidden="true" /> referans medyanı ({MODE_LABELS[baseline.mode]}, v
                  {baseline.version}) · <span className="legend-band" aria-hidden="true" /> z &lt; 3 bandı ·{" "}
                  <span className="legend-dot" aria-hidden="true" /> z ≥ 3 · <span className="legend-tri" aria-hidden="true" />{" "}
                  z ≥ 6
                </span>
              ) : (
                <span className="legend">Bu mod için referans çizgisi yok</span>
              )}
            </figcaption>
            <ResponsiveContainer width="100%" height={height}>
              <LineChart data={data} syncId="makine" margin={{ top: 6, right: 16, bottom: 0, left: 4 }}>
                <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
                {xAxis}
                <YAxis
                  domain={["auto", "auto"]}
                  width={96}
                  tick={{ fontSize: 12 }}
                  tickFormatter={(v: number) => `${fmtNum(v, info.digits)} ${info.unit}`}
                />
                {stat && scale ? (
                  <ReferenceArea
                    y1={stat.median - 3 * scale}
                    y2={stat.median + 3 * scale}
                    fill={info.color}
                    fillOpacity={0.08}
                    ifOverflow="hidden"
                  />
                ) : null}
                {stat ? <ReferenceLine y={stat.median} stroke="#475467" strokeDasharray="6 4" ifOverflow="hidden" /> : null}
                <Tooltip content={<PointTooltip feature={info.id} />} />
                <Line
                  type="linear"
                  dataKey={info.id}
                  stroke={info.color}
                  strokeWidth={1.6}
                  dot={<FeatureDot feature={info.id} />}
                  activeDot={{ r: 4 }}
                  isAnimationActive={false}
                  connectNulls={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </figure>
        );
      })}

      <figure className="chart">
        <figcaption>
          <strong>Sapma puanı</strong> <span className="unit">(0–100 = min(100, 10 × en büyük z); arıza olasılığı değildir)</span>
          <span className="legend">
            <span className="legend-x" aria-hidden="true">×</span> veri sorunu nedeniyle değerlendirilmeyen kayıt
          </span>
        </figcaption>
        <ResponsiveContainer width="100%" height={compact ? 110 : 140}>
          <LineChart data={data} syncId="makine" margin={{ top: 6, right: 16, bottom: 0, left: 4 }}>
            <CartesianGrid stroke={GRID} strokeDasharray="3 3" />
            {xAxis}
            <YAxis domain={[0, 100]} ticks={[0, 30, 60, 100]} width={96} tick={{ fontSize: 12 }} />
            <ReferenceLine y={30} stroke="#b54708" strokeDasharray="4 4" label={{ value: "z = 3", position: "insideTopRight", fontSize: 11, fill: "#93370d" }} />
            <ReferenceLine y={60} stroke="#b42318" strokeDasharray="4 4" label={{ value: "z = 6", position: "insideTopRight", fontSize: 11, fill: "#912018" }} />
            <Tooltip content={<PointTooltip />} />
            <Line type="linear" dataKey="score" stroke="#1d3b53" strokeWidth={1.6} dot={false} isAnimationActive={false} connectNulls={false} />
            <Line dataKey="dq" stroke="none" dot={<DataIssueDot />} activeDot={false} isAnimationActive={false} legendType="none" />
          </LineChart>
        </ResponsiveContainer>
      </figure>
    </div>
  );
}

interface DotProps {
  cx?: number;
  cy?: number;
  payload?: ChartPoint;
  feature?: FeatureId;
}

function FeatureDot({ cx, cy, payload, feature }: DotProps) {
  if (cx == null || cy == null || !payload || !feature) return null;
  const z = payload.zf?.[feature];
  if (z == null || z < 3) return null;
  if (z >= 6) {
    return <path d={`M${cx},${cy - 6} L${cx + 5.5},${cy + 4} L${cx - 5.5},${cy + 4} Z`} fill="#b42318" stroke="#fff" strokeWidth={1} />;
  }
  return <circle cx={cx} cy={cy} r={3.6} fill="#b54708" stroke="#fff" strokeWidth={1} />;
}

function DataIssueDot({ cx, cy }: DotProps) {
  if (cx == null || cy == null) return null;
  return (
    <text x={cx} y={cy - 2} textAnchor="middle" fontSize={13} fontWeight={700} fill="#6941c6">
      ×
    </text>
  );
}

interface TooltipProps {
  active?: boolean;
  payload?: { payload: ChartPoint }[];
  feature?: FeatureId;
}

function PointTooltip({ active, payload, feature }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  if (p.gap) {
    return (
      <div className="chart-tip">
        <strong>Veri kesintisi</strong>
        <div>Bu aralıkta ölçüm yok; çizgi bilerek kesildi.</div>
      </div>
    );
  }
  return (
    <div className="chart-tip">
      <div className="tip-time">{fmtDateTime(p.t)}</div>
      <div>Mod: {p.mode ? MODE_LABELS[p.mode] : "—"}</div>
      {feature ? (
        <div>
          <strong>
            {FEATURE_MAP[feature].label}: {fmtValue(feature, p[feature])}
          </strong>
          {p.zf ? ` · z = ${fmtNum(p.zf[feature], 1)}` : ""}
        </div>
      ) : (
        FEATURES.map((f) => (
          <div key={f.id}>
            {f.label}: {fmtValue(f.id, p[f.id])}
          </div>
        ))
      )}
      {p.n ? <div className="muted">{p.n} ölçümün ortalaması (görüntüleme için örnek azaltıldı)</div> : null}
      <div>
        Sapma değeri (en büyük z): {fmtNum(p.z, 2)} · puan {p.score == null ? "—" : `${fmtNum(p.score, 0)}/100`}
      </div>
      <div>Durum: {POINT_STATUS_LABELS[p.status ?? ""] ?? p.status ?? "—"}</div>
      {p.flags?.length ? <div className="tip-flags">{p.flags.map(flagLabel).join(" · ")}</div> : null}
    </div>
  );
}
