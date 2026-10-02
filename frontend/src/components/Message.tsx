import type { ReactNode } from "react";
import { Icon } from "./Icon";

type Kind = "error" | "success" | "info" | "warning";

const ICONS = { error: "octagon", success: "check", info: "info", warning: "alert" } as const;

export function Message({ kind, children, onClose }: { kind: Kind; children: ReactNode; onClose?: () => void }) {
  return (
    <div className={`message message-${kind}`} role={kind === "error" ? "alert" : "status"}>
      <Icon name={ICONS[kind]} size={18} />
      <div className="message-body">{children}</div>
      {onClose ? (
        <button type="button" className="icon-button" onClick={onClose} aria-label="Mesajı kapat">
          <Icon name="close" size={16} />
        </button>
      ) : null}
    </div>
  );
}

export function Loading({ text = "Yükleniyor…" }: { text?: string }) {
  return (
    <p className="muted" role="status">
      {text}
    </p>
  );
}
