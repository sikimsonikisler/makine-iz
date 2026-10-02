import type { Alert, MachineStatus, Source } from "../types";
import {
  DQ_LABELS,
  DQ_MEASUREMENT_LABELS,
  LEVEL_LABELS,
  MEASUREMENT_LABELS,
  REVIEW_LABELS,
  SOURCE_LABELS,
} from "../format";
import { Icon, type IconName } from "./Icon";

const CODE_ICON: Record<string, IconName> = {
  ok: "check",
  review: "alert",
  strong: "octagon",
  no_data_flow: "dataoff",
  frozen: "dataoff",
  invalid_data: "dataoff",
  sequence_issue: "dataoff",
  candidate: "eye",
  transition: "swap",
  stopped: "stop",
  no_baseline: "ban",
  awaiting_data: "clock",
  no_data: "clock",
  unevaluable: "info",
};

export function StatusPill({ status, large = false }: { status: Pick<MachineStatus, "code" | "label" | "category">; large?: boolean }) {
  const tone = status.code === "strong" ? "danger" : status.category;
  return (
    <span className={`pill pill-${tone}${large ? " pill-large" : ""}`}>
      <Icon name={CODE_ICON[status.code] ?? "info"} size={large ? 20 : 16} />
      {status.label}
    </span>
  );
}

export function LevelPill({ alert }: { alert: Pick<Alert, "kind" | "level" | "dq_type"> }) {
  if (alert.kind === "data_quality") {
    return (
      <span className="pill pill-data_issue">
        <Icon name="dataoff" size={16} />
        {LEVEL_LABELS.data}: {DQ_LABELS[alert.dq_type ?? ""] ?? alert.dq_type}
      </span>
    );
  }
  const strong = alert.level === "strong";
  return (
    <span className={`pill ${strong ? "pill-danger" : "pill-review"}`}>
      <Icon name={strong ? "octagon" : "alert"} size={16} />
      {LEVEL_LABELS[alert.level]}
    </span>
  );
}

export function MeasurementPill({ alert }: { alert: Pick<Alert, "kind" | "measurement_status"> }) {
  const labels = alert.kind === "data_quality" ? DQ_MEASUREMENT_LABELS : MEASUREMENT_LABELS;
  const map: Record<string, [string, IconName]> = {
    active: [alert.kind === "data_quality" ? "data_issue" : "review", alert.kind === "data_quality" ? "dataoff" : "alert"],
    normalized: ["ok", "check"],
    unevaluable: ["info", "info"],
  };
  const [tone, icon] = map[alert.measurement_status] ?? ["info", "info"];
  return (
    <span className={`pill pill-${tone}`}>
      <Icon name={icon} size={16} />
      {labels[alert.measurement_status] ?? alert.measurement_status}
    </span>
  );
}

export function ReviewPill({ status }: { status: string }) {
  const icon: IconName = status === "new" ? "bell" : status === "in_review" ? "eye" : "check";
  return (
    <span className={`pill pill-neutral review-${status}`}>
      <Icon name={icon} size={16} />
      {REVIEW_LABELS[status] ?? status}
    </span>
  );
}

export function SourceTag({ source }: { source: Source | string }) {
  if (source === "simulation") {
    return (
      <span className="tag tag-sim" title="Bu makinenin ölçümleri simülatörden gelir; gerçek makine verisi değildir.">
        <Icon name="flask" size={14} />
        SİMÜLASYON
      </span>
    );
  }
  return <span className="tag">{SOURCE_LABELS[source] ?? source}</span>;
}
