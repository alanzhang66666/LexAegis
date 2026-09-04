import type { ReactNode } from "react";
import { FileText } from "lucide-react";

export function StatusBadge({ children, tone = "neutral" }: { children: ReactNode; tone?: string }) {
  return <span className={`tag ${tone}`}><span className="status-mark" aria-hidden="true" />{children}</span>;
}

export const Tag = StatusBadge;

export function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="empty"><FileText size={32} /><h3>{title}</h3><p>{detail}</p></div>;
}

export function Panel({ title, children }: { title: string; children: ReactNode }) {
  return <section className="system-panel"><h2>{title}</h2>{children}</section>;
}
