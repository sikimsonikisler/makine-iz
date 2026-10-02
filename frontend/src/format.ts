// Türkçe etiketler, birimler ve Europe/Istanbul saat dilimiyle biçimlendirme.
import type { FeatureId, Mode } from "./types";

export const TZ = "Europe/Istanbul";

export const MODE_LABELS: Record<Mode, string> = { stopped: "Durmuş", idle: "Boşta", loaded: "Yük altında" };
export const MODE_ORDER: Mode[] = ["stopped", "idle", "loaded"];

export interface FeatureInfo {
  id: FeatureId;
  label: string;
  unit: string;
  digits: number;
  color: string;
}

export const FEATURES: FeatureInfo[] = [
  { id: "vibration_rms_g", label: "Titreşim RMS", unit: "g", digits: 3, color: "#2563a8" },
  { id: "temperature_c", label: "Sıcaklık", unit: "°C", digits: 1, color: "#b4531f" },
  { id: "power_kw", label: "Elektrik gücü", unit: "kW", digits: 2, color: "#5b3fa6" },
  { id: "rpm", label: "Devir", unit: "dev/dak", digits: 0, color: "#18794e" },
];
export const FEATURE_MAP = Object.fromEntries(FEATURES.map((f) => [f.id, f])) as Record<FeatureId, FeatureInfo>;

export const SOURCE_LABELS: Record<string, string> = { simulation: "Simülasyon", csv: "CSV aktarımı", sensor: "Sensör" };
export const LEVEL_LABELS: Record<string, string> = {
  review: "İnceleme uyarısı",
  strong: "Belirgin sapma",
  data: "Veri sorunu",
};
export const MEASUREMENT_LABELS: Record<string, string> = {
  active: "Aktif sapma",
  normalized: "Ölçümler normale döndü",
  unevaluable: "Veri nedeniyle değerlendirilemiyor",
};
export const DQ_MEASUREMENT_LABELS: Record<string, string> = {
  active: "Veri sorunu sürüyor",
  normalized: "Veri normale döndü",
  unevaluable: "Değerlendirilemiyor",
};
export const REVIEW_LABELS: Record<string, string> = { new: "Yeni", in_review: "İncelemeye alındı", closed: "Kapatıldı" };
export const ASSESSMENT_LABELS: Record<string, string> = {
  normal_change: "Normal çalışma değişimi",
  measurement_issue: "Ölçüm sorunu",
  maintenance_found: "Bakımda sorun bulundu",
  uncertain: "Belirsiz",
};
export const DQ_LABELS: Record<string, string> = {
  invalid: "Eksik / geçersiz ölçüm",
  data_gap: "Veri gelmiyor / kesinti",
  frozen: "Veri donması şüphesi",
  sequence: "Yinelenen / sırası bozuk kayıt",
};
export const NOTE_TYPE_LABELS: Record<string, string> = { inspection: "İnceleme", maintenance: "Bakım", general: "Genel" };
export const POINT_STATUS_LABELS: Record<string, string> = {
  normal: "Referansla uyumlu (z < 3)",
  candidate: "Sapma adayı (z ≥ 3)",
  strong_candidate: "Belirgin sapma adayı (z ≥ 6)",
  transition: "Mod geçişi — geçiş süresi",
  invalid: "Eksik / geçersiz ölçüm (değerlendirilmedi)",
  frozen_suspect: "Veri donması şüphesi (değerlendirilmedi)",
  out_of_order: "Sırası bozuk kayıt (sayılmadı)",
  no_baseline: "Referans yok (karşılaştırılmadı)",
  stopped: "Durmuş (karşılaştırılmadı)",
  gap: "Veri kesintisi",
};

const FLAG_KIND: Record<string, string> = {
  missing: "eksik ölçüm",
  non_numeric: "sayısal olmayan değer",
  negative: "negatif değer",
  out_of_range: "beklenen aralığın dışında",
};

export function flagLabel(flag: string): string {
  if (flag === "missing_mode") return "Çalışma modu yok";
  if (flag === "invalid_mode") return "Çalışma modu geçersiz";
  if (flag === "undefined_mode") return "Mod bu makinede tanımlı değil";
  if (flag === "out_of_order") return "Sırası bozuk kayıt";
  if (flag === "after_gap") return "Kesintiden sonraki ilk kayıt";
  if (flag === "frozen_suspect") return "Veri donması şüphesi";
  if (flag === "duplicate") return "Yinelenen kayıt";
  if (flag === "invalid_timestamp") return "Geçersiz zaman damgası";
  const [kind, rest] = flag.split(":");
  if (kind === "upstream") return `Kaynak işareti: ${rest}`;
  if (FLAG_KIND[kind] && FEATURE_MAP[rest as FeatureId]) return `${FEATURE_MAP[rest as FeatureId].label}: ${FLAG_KIND[kind]}`;
  return flag;
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("tr-TR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtValue(feature: FeatureId, value: number | null | undefined): string {
  const info = FEATURE_MAP[feature];
  if (value === null || value === undefined) return `— ${info.unit}`;
  return `${fmtNum(value, info.digits)} ${info.unit}`;
}

export function fmtSigned(feature: FeatureId, value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const info = FEATURE_MAP[feature];
  const sign = value >= 0 ? "+" : "−";
  return `${sign}${fmtNum(Math.abs(value), info.digits)} ${info.unit}`;
}

const dateTimeFormat = new Intl.DateTimeFormat("tr-TR", {
  timeZone: TZ,
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});
const timeFormat = new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, hour: "2-digit", minute: "2-digit", second: "2-digit" });
const shortTimeFormat = new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, hour: "2-digit", minute: "2-digit" });
const dayFormat = new Intl.DateTimeFormat("tr-TR", { timeZone: TZ, day: "2-digit", month: "2-digit" });

function toDate(value: string | number): Date {
  return typeof value === "number" ? new Date(value) : new Date(value);
}

export function fmtDateTime(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return dateTimeFormat.format(toDate(value));
}

export function fmtTime(value: string | number): string {
  return timeFormat.format(toDate(value));
}

export function fmtAxisTime(ms: number, spanMs: number): string {
  if (spanMs > 2 * 86400000) return dayFormat.format(new Date(ms));
  if (spanMs > 20 * 3600000) return `${dayFormat.format(new Date(ms))} ${shortTimeFormat.format(new Date(ms))}`;
  return shortTimeFormat.format(new Date(ms));
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s} sn`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} dk ${s % 60 ? `${s % 60} sn` : ""}`.trim();
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} sa ${m % 60 ? `${m % 60} dk` : ""}`.trim();
  return `${Math.floor(h / 24)} gün`;
}

// Europe/Istanbul ile UTC arasındaki fark (ms)
function tzOffsetMs(date: Date): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(date);
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour"), get("minute"), get("second"));
  return asUtc - Math.floor(date.getTime() / 1000) * 1000;
}

/** Zamanı <input type="datetime-local"> için İstanbul yerel saatine çevirir. */
export function toIstanbulInput(value: string | number): string {
  const ms = typeof value === "number" ? value : Date.parse(value);
  const local = new Date(ms + tzOffsetMs(new Date(ms)));
  return local.toISOString().slice(0, 19);
}

/** İstanbul yerel saatindeki giriş değerini UTC ISO metnine çevirir. */
export function fromIstanbulInput(value: string): string {
  const [datePart, timePart = "00:00"] = value.split("T");
  const [y, m, d] = datePart.split("-").map(Number);
  const [hh, mm, ss = 0] = timePart.split(":").map(Number);
  const guess = Date.UTC(y, m - 1, d, hh, mm, ss);
  return new Date(guess - tzOffsetMs(new Date(guess))).toISOString();
}

export function isoToMs(value: string): number {
  return Date.parse(value);
}
