import type { ReactElement } from "react";

// Basit çizgi simgeleri. Durumlar asla yalnızca renkle anlatılmaz: simge + metin birlikte kullanılır.
export type IconName =
  | "check"
  | "alert"
  | "octagon"
  | "dataoff"
  | "info"
  | "eye"
  | "pause"
  | "play"
  | "stop"
  | "swap"
  | "clock"
  | "ban"
  | "upload"
  | "download"
  | "forward"
  | "refresh"
  | "plus"
  | "edit"
  | "flask"
  | "bell"
  | "note"
  | "chart"
  | "close";

const PATHS: Record<IconName, ReactElement> = {
  check: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.5l2.6 2.6L16 9.5" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3.5 2.8 19.5h18.4z" />
      <path d="M12 10v4.2" />
      <path d="M12 17.2h.01" />
    </>
  ),
  octagon: (
    <>
      <path d="M8.2 3h7.6L21 8.2v7.6L15.8 21H8.2L3 15.8V8.2z" />
      <path d="M12 7.8v5.4" />
      <path d="M12 16.4h.01" />
    </>
  ),
  dataoff: (
    <>
      <path d="M3 12h3l2.2-4.5 3.4 9 2.2-4.5H16" />
      <path d="M4 4l16 16" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5" />
      <path d="M12 7.8h.01" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12z" />
      <circle cx="12" cy="12" r="2.6" />
    </>
  ),
  pause: (
    <>
      <rect x="6" y="5" width="4" height="14" rx="1" />
      <rect x="14" y="5" width="4" height="14" rx="1" />
    </>
  ),
  play: <path d="M7 4.5v15l12-7.5z" />,
  stop: <rect x="5.5" y="5.5" width="13" height="13" rx="2" />,
  swap: (
    <>
      <path d="M4 8h13l-3.2-3.2" />
      <path d="M20 16H7l3.2 3.2" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5.2l3.2 2" />
    </>
  ),
  ban: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M5.8 5.8l12.4 12.4" />
    </>
  ),
  upload: (
    <>
      <path d="M12 15.5V4" />
      <path d="M7 9l5-5 5 5" />
      <path d="M4 20h16" />
    </>
  ),
  download: (
    <>
      <path d="M12 4v11.5" />
      <path d="M7 10.5l5 5 5-5" />
      <path d="M4 20h16" />
    </>
  ),
  forward: (
    <>
      <path d="M3.5 6l8 6-8 6z" />
      <path d="M12 6l8 6-8 6z" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11.5a8 8 0 1 0-2.4 5.6" />
      <path d="M20 4.5v7h-7" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  edit: (
    <>
      <path d="M4 20h4L19.5 8.5l-4-4L4 16z" />
      <path d="M13.5 6.5l4 4" />
    </>
  ),
  flask: (
    <>
      <path d="M9 3h6" />
      <path d="M10 3v6.2L4.6 18.4A1.8 1.8 0 0 0 6.2 21h11.6a1.8 1.8 0 0 0 1.6-2.6L14 9.2V3" />
      <path d="M7.5 15h9" />
    </>
  ),
  bell: (
    <>
      <path d="M6 16.5V11a6 6 0 1 1 12 0v5.5l1.5 2h-15z" />
      <path d="M10 21h4" />
    </>
  ),
  note: (
    <>
      <path d="M5 3.5h10l4 4V20.5H5z" />
      <path d="M8.5 11h7M8.5 14.5h7M8.5 18h4" />
    </>
  ),
  chart: (
    <>
      <path d="M4 4v16h16" />
      <path d="M7.5 14.5l3.5-4 3 2.5 5-6" />
    </>
  ),
  close: <path d="M6 6l12 12M18 6 6 18" />,
};

export function Icon({ name, size = 18, title }: { name: IconName; size?: number; title?: string }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={title ? undefined : true}
      role={title ? "img" : undefined}
    >
      {title ? <title>{title}</title> : null}
      {PATHS[name]}
    </svg>
  );
}
