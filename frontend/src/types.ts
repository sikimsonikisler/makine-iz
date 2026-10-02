// Arka uçtan gelen verilerin biçimleri (API sözleşmesi)

export type Mode = "stopped" | "idle" | "loaded";
export type FeatureId = "vibration_rms_g" | "temperature_c" | "power_kw" | "rpm";
export type Source = "simulation" | "csv" | "sensor";

export interface ModeConfig {
  enabled: boolean;
  description: string;
}

export interface Machine {
  id: string;
  name: string;
  machine_type: string;
  location: string;
  description: string;
  data_source: Source;
  sim_profile: string | null;
  expected_interval_s: number;
  transition_s: number;
  modes: Record<Mode, ModeConfig>;
  ranges: Record<FeatureId, [number, number]>;
  floors: Record<FeatureId, number>;
  is_demo: boolean;
  created_at: string;
  updated_at: string;
}

export interface BaselineStat {
  median: number;
  mad: number;
  robust_sd: number;
  p05: number;
  p95: number;
  min: number;
  max: number;
}

export interface BaselineSummary {
  id: number;
  mode: Mode;
  version: number;
  created_at: string;
  sample_count: number;
  stats: Record<FeatureId, BaselineStat>;
}

export interface Baseline extends BaselineSummary {
  machine_id: string;
  range_start: string;
  range_end: string;
  excluded_count: number;
  is_active: boolean;
  is_demo: boolean;
  note: string;
}

export interface ChangeItem {
  feature: FeatureId;
  label: string;
  unit: string;
  value: number | null;
  median: number;
  diff: number | null;
  z: number;
}

export type StatusCategory = "ok" | "review" | "data_issue" | "info" | "watch";

export interface LiveInfo {
  kind: "sim_running" | "sim_paused" | "sim_stopped" | "sensor" | "csv";
  label: string;
  now: number | null;
  virtual: boolean;
  note?: string;
}

export interface MachineStatus {
  code: string;
  label: string;
  category: StatusCategory;
  detail: string;
  badges: string[];
  current_mode: Mode | null;
  last_ts: string | null;
  last_values: Record<FeatureId, number | null>;
  last_flags: string[];
  last_analysis_status: string | null;
  age_s: number | null;
  stale: boolean;
  z: Record<FeatureId, number> | null;
  z_max: number | null;
  deviation_score: number | null;
  changes: ChangeItem[];
  baseline: BaselineSummary | null;
  baselines_by_mode: Partial<Record<Mode, BaselineSummary>>;
  live: LiveInfo;
  needs_review: boolean;
  data_issue: boolean;
  open_data_issues: string[];
  persistence: { windows: number[]; normal_streak: number };
}

export interface SimRun {
  id: number;
  machine_id: string;
  scenario: string;
  scenario_label: string;
  seed: number;
  status: "running" | "paused" | "stopped";
  speed: number;
  start_virtual: string;
  virtual_now: string;
  steps_generated: number;
  records_emitted: number;
  params: {
    profile: string;
    interval_s: number;
    start_mode: Mode;
    onset_s: number;
    mode_changes: [number, Mode][];
    effect_end_step: number | null;
  };
  status_note: string;
  elapsed_virtual_s: number;
  onset_virtual: string;
  created_at: string;
  updated_at: string;
}

export interface FeatureChange {
  feature: FeatureId;
  label: string;
  unit: string;
  value: number;
  median: number;
  mad: number;
  scale: number;
  diff: number;
  diff_pct: number | null;
  z: number;
  mean_z: number;
  max_z: number;
}

export interface WindowSummary {
  features: FeatureChange[];
  top: FeatureId[];
  window_ts: number[];
  window_z: number[];
}

export interface Alert {
  id: number;
  machine_id: string;
  machine_name: string;
  mode: Mode | null;
  kind: "deviation" | "data_quality";
  dq_type: "invalid" | "data_gap" | "frozen" | "sequence" | null;
  level: "review" | "strong" | "data";
  measurement_status: "active" | "normalized" | "unevaluable";
  review_status: "new" | "in_review" | "closed";
  assessment: string | null;
  started_at: string;
  updated_at: string;
  ended_at: string | null;
  baseline_id: number | null;
  baseline_version: number | null;
  peak_z: number | null;
  last_z: number | null;
  details: {
    initial?: WindowSummary;
    latest?: WindowSummary;
    hits?: number;
    strong_hits?: number;
    window_count?: number;
    updates?: number;
    count?: number;
    last_flags?: string[];
    duplicates?: number;
    out_of_order?: number;
    duration_s?: number;
    [key: string]: unknown;
  };
  explanation: string;
  unevaluable_reason: string | null;
  is_open: boolean;
  is_demo: boolean;
  source: string | null;
  created_at: string;
  reviewed_at: string | null;
}

export interface Note {
  id: number;
  machine_id: string;
  alert_id: number | null;
  created_at: string;
  author: string;
  note_type: "inspection" | "maintenance" | "general";
  text: string;
  assessment: string | null;
  alert_snapshot: string | null;
}

export interface SeriesPoint {
  t: number;
  mode: Mode | null;
  vibration_rms_g: number | null;
  temperature_c: number | null;
  power_kw: number | null;
  rpm: number | null;
  zf: Record<FeatureId, number> | null;
  z: number | null;
  score: number | null;
  status: string | null;
  flags: string[];
  gap?: boolean;
  n?: number;
}

export interface Series {
  total: number;
  downsampled: boolean;
  bucket_s: number | null;
  points: SeriesPoint[];
  start: string | null;
  end: string | null;
}

export interface MachineCard {
  machine: Machine;
  status: MachineStatus;
  run: SimRun | null;
}

export interface Overview {
  counts: { machines: number; ok: number; needs_review: number; data_issue: number };
  machines: MachineCard[];
  recent_alerts: Alert[];
}

export interface MachineDetail {
  machine: Machine;
  status: MachineStatus;
  run: SimRun | null;
  range: { first_ts: string | null; last_ts: string | null; count: number };
  baselines: Baseline[];
}

export interface Scenario {
  id: string;
  label: string;
  description: string;
  group: string;
}

export interface AppConfig {
  version: string;
  analysis: {
    z_candidate: number;
    z_strong: number;
    z_normal: number;
    window_count: number;
    min_hits: number;
    normal_streak: number;
    freeze_count: number;
    gap_factor: number;
    min_baseline_samples: number;
    mad_scale: number;
    dq_recovery: number;
  };
  features: { id: FeatureId; label: string; unit: string }[];
  default_floors: Record<FeatureId, number>;
  default_ranges: Record<FeatureId, [number, number]>;
  default_interval_s: number;
  default_transition_s: number;
  sim_profiles: { id: string; label: string }[];
  scenarios: Scenario[];
  speeds: number[];
}

export interface CsvIssue {
  row: number | null;
  field: string | null;
  message: string;
}

export interface CsvReport {
  ok: boolean;
  error_count: number;
  warning_count: number;
  errors: CsvIssue[];
  warnings: CsvIssue[];
  infos: string[];
  summary: {
    data_rows: number;
    blank_rows: number;
    missing_values: number;
    invalid_values: number;
    duplicates_in_file: number;
    duplicates_existing: number;
    older_than_existing: number;
    timezone_assumed: number;
    valid_rows: number;
    importable_rows: number;
    machines: { machine_id: string; name: string | null; new: boolean; rows: number; first_ts: string; last_ts: string }[];
  };
  preview: (Record<string, string | number | null> & { row: number; skip?: string | null })[];
}

export interface ImportSummary {
  import_id: string;
  filename: string;
  imported_rows: number;
  skipped_duplicates: number;
  flagged_rows: number;
  analysis_statuses: Record<string, number>;
  created_machines: string[];
  machines: { machine_id: string; rows: number; first_ts: string; last_ts: string }[];
  warning_count: number;
  duplicate_policy: string;
}

export interface BaselinePreview {
  mode: Mode;
  range_start: string;
  range_end: string;
  valid_count: number;
  required: number;
  excluded: Record<string, number>;
  enough: boolean;
  overlapping_deviation_alerts: number;
  stats: Record<FeatureId, BaselineStat> | null;
  message: string;
}
