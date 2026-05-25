import type { ReactNode } from "react";

// Lightweight markdown → styled JSX, mapped to the app's design tokens (no deps).
// Handles ## / ### subheads, **bold**, `code`, and - / * bullet lists.

function inline(text: string, keyBase: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    const key = `${keyBase}-${i}`;
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={key} className="font-semibold text-[var(--text-primary)]">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={key} className="font-mono text-[11px] px-1 rounded" style={{ background: "var(--bg-elevated)", color: "var(--sl-accent-teal)" }}>
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={key}>{part}</span>;
  });
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];

  const flush = () => {
    if (!list.length) return;
    const items = list;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="list-disc pl-4 space-y-1 text-[12px] leading-relaxed text-[var(--text-primary)]">
        {items.map((li, i) => (
          <li key={i}>{inline(li, `li-${blocks.length}-${i}`)}</li>
        ))}
      </ul>,
    );
    list = [];
  };

  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (/^#{2,4}\s/.test(line)) {
      flush();
      blocks.push(
        <h4 key={`h-${blocks.length}`} className="text-[10px] font-mono uppercase tracking-[0.12em] pt-1" style={{ color: "var(--sl-accent)" }}>
          {inline(line.replace(/^#{2,4}\s/, ""), `h-${blocks.length}`)}
        </h4>,
      );
    } else if (/^[-*]\s/.test(line)) {
      list.push(line.replace(/^[-*]\s/, ""));
    } else if (line.trim() === "") {
      flush();
    } else {
      flush();
      blocks.push(
        <p key={`p-${blocks.length}`} className="text-[12px] leading-relaxed text-[var(--text-primary)]">
          {inline(line, `p-${blocks.length}`)}
        </p>,
      );
    }
  }
  flush();
  return <div className="space-y-2">{blocks}</div>;
}
