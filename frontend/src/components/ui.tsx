import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import { AlertTriangle, FileText, Link2, X } from "lucide-react";

type Obj = Record<string, any>;

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`tag ${tone}`}><span className="status-mark" aria-hidden="true" />{children}</span>;
}

export const Tag = StatusBadge;

export function Button({ children, className = "", variant = "secondary", ...props }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "text" }) {
  return <button className={`${variant === "text" ? "text-button" : variant} ${className}`.trim()} {...props}>{children}</button>;
}

export function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="empty"><FileText size={32} /><h3>{title}</h3><p>{detail}</p></div>;
}

export function Panel({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return <section className="system-panel"><header><h2>{title}</h2>{actions}</header>{children}</section>;
}

export function DataTable({ columns, rows, rowKey }: {
  columns: { key: string; label: string; render?: (row: Obj) => ReactNode }[];
  rows: Obj[];
  rowKey: (row: Obj) => string;
}) {
  const grid={gridTemplateColumns:`repeat(${columns.length},minmax(110px,1fr))`};
  return <div className="data-table" role="table">
    <div className="data-table-row head" style={grid} role="row">{columns.map(column => <span role="columnheader" key={column.key}>{column.label}</span>)}</div>
    {rows.map(row => <div className="data-table-row" style={grid} role="row" key={rowKey(row)}>
      {columns.map(column => <span role="cell" key={column.key}>{column.render ? column.render(row) : String(row[column.key] ?? "—")}</span>)}
    </div>)}
  </div>;
}

export function StageStepper({ stages, active, onSelect }: {
  stages: { id: string; label: string }[]; active: string; onSelect: (id: string) => void;
}) {
  return <div className="stage-bar" aria-label="案件处理阶段">{stages.map((stage, index) =>
    <button key={stage.id} aria-current={stage.id === active ? "step" : undefined}
      className={stage.id === active ? "selected" : ""} onClick={() => onSelect(stage.id)}>
      <span>{String(index + 1).padStart(2, "0")}</span>{stage.label}
    </button>)}</div>;
}

export function Dialog({ open, title, busy, onClose, children }: {
  open: boolean; title: string; busy?: boolean; onClose: () => void; children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // Capture the invoking control during render, before a child's autoFocus runs
  // in the commit phase and makes the dialog input look like the previous focus.
  const returnFocus = useRef<HTMLElement | null>(document.activeElement as HTMLElement | null);
  const closeRef = useRef(onClose);
  const busyRef = useRef(busy);
  closeRef.current = onClose;
  busyRef.current = busy;
  useEffect(() => {
    if (!open) return;
    const root = ref.current;
    root?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busyRef.current) closeRef.current();
      if (event.key !== "Tab" || !root) return;
      const focusable = Array.from(root.querySelectorAll<HTMLElement>("button,input,select,textarea,a[href],[tabindex]:not([tabindex='-1'])"))
        .filter(element => !element.hasAttribute("disabled"));
      if (!focusable.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", keydown);
    return () => { document.removeEventListener("keydown", keydown); returnFocus.current?.focus(); };
  }, [open]);
  if (!open) return null;
  return <div className="modal-backdrop" onClick={() => !busy && onClose()}>
    <div ref={ref} className="modal" role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}
      onClick={event => event.stopPropagation()}>
      <button className="modal-close" aria-label="关闭对话框" onClick={onClose}><X size={20} /></button>
      {children}
    </div>
  </div>;
}

export function IssueList({ issues }: { issues: string[] }) {
  return <div className="issue-list" aria-label="问题列表">{issues.map(issue =>
    <small className="claim-issue" key={issue}><AlertTriangle size={12} />{issue}</small>)}</div>;
}

export function AnchorViewer({ anchors, onOpen }: { anchors: Obj[] | string[]; onOpen: (ids: any[]) => void }) {
  return <button onClick={() => onOpen(anchors)} disabled={!anchors.length}><Link2 size={13} />回到原文</button>;
}

export function AuditTimeline({ events }: { events: Obj[] }) {
  return <div className="audit-list">{events.slice(-8).reverse().map(event =>
    <div key={event.id}><span className="audit-dot" /><div><b>{event.event}</b>
      <small>{event.actor} · {new Date(event.at).toLocaleTimeString("zh-CN")}</small></div></div>)}</div>;
}
