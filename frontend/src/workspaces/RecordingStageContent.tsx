import { FileText } from "lucide-react";
import { Tag } from "../components/ui";

type StageItem = { label: string; text: string };
type StageContent = {
  label: string;
  title: string;
  summary: string;
  items: StageItem[];
};

export function RecordingStageContent({
  content,
  onOpenSource,
}: {
  content: StageContent;
  onOpenSource: () => void;
}) {
  return (
    <section className="recording-stage-content" aria-label="本案阶段内容">
      <header>
        <div>
          <Tag tone="green">{content.label}</Tag>
          <h4>{content.title}</h4>
        </div>
        <button className="text-button" onClick={onOpenSource}>
          <FileText size={14} />
          查看对应原文
        </button>
      </header>
      <p>{content.summary}</p>
      <div className="recording-stage-items">
        {content.items.map((item) => (
          <div key={item.label}>
            <strong>{item.label}</strong>
            <span>{item.text}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
