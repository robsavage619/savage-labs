import type { ReactNode } from "react";

// Lightweight markdown → styled JSX, mapped to the app's design tokens (no deps).
// Handles ## / ### subheads, **bold**, `code`, - / * bullets, and | tables.

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
        <code key={key} className="font-mono text-[11px] px-1.5 py-0.5 rounded" style={{ background: "oklch(0.18 0.02 210 / 0.6)", color: "var(--sl-accent-teal)" }}>
          {part.slice(1, -1)}
        </code>
      );
    }
    return <span key={key}>{part}</span>;
  });
}

function parseTable(rows: string[], tableIndex: number): ReactNode {
  const cells = (row: string) =>
    row.split("|").map((c) => c.trim()).filter((_, i, a) => i > 0 && i < a.length - 1);

  const [header, , ...body] = rows;
  const headCells = cells(header);

  return (
    <div key={`table-${tableIndex}`} className="overflow-x-auto -mx-1">
      <table className="w-full text-[12px] border-collapse">
        <thead>
          <tr>
            {headCells.map((h, i) => (
              <th key={i} className="text-left font-semibold pb-1.5 pr-4 text-[var(--text-muted)] border-b whitespace-nowrap" style={{ borderColor: "var(--hairline-strong)" }}>
                {inline(h, `th-${i}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {body.map((row, ri) => (
            <tr key={ri}>
              {cells(row).map((c, ci) => (
                <td key={ci} className="py-1.5 pr-4 text-[var(--text-primary)] border-b align-top" style={{ borderColor: "var(--hairline)" }}>
                  {inline(c, `td-${ri}-${ci}`)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Markdown({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let list: string[] = [];
  let tableRows: string[] = [];

  const flushList = () => {
    if (!list.length) return;
    const items = list;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="list-none pl-0 space-y-1.5 text-[13px] leading-[1.65] text-[var(--text-primary)]">
        {items.map((li, i) => (
          <li key={i} className="flex gap-2">
            <span className="mt-[0.45em] h-1 w-1 rounded-full shrink-0" style={{ background: "var(--sl-accent-dim)" }} />
            <span>{inline(li, `li-${blocks.length}-${i}`)}</span>
          </li>
        ))}
      </ul>,
    );
    list = [];
  };

  const flushTable = () => {
    if (!tableRows.length) return;
    blocks.push(parseTable(tableRows, blocks.length));
    tableRows = [];
  };

  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const isTableRow = /^\|.+\|/.test(line);
    const isSeparator = /^\|[-| :]+\|/.test(line);

    if (isTableRow && !isSeparator) {
      flushList();
      tableRows.push(line);
      continue;
    }
    if (isSeparator) {
      tableRows.push(line);
      continue;
    }

    flushTable();

    if (/^#{2,4}\s/.test(line)) {
      flushList();
      blocks.push(
        <h4 key={`h-${blocks.length}`} className="text-[10.5px] font-mono uppercase tracking-[0.14em] pt-2 pb-0.5" style={{ color: "var(--sl-accent)" }}>
          {inline(line.replace(/^#{2,4}\s/, ""), `h-${blocks.length}`)}
        </h4>,
      );
    } else if (/^[-*]\s/.test(line)) {
      list.push(line.replace(/^[-*]\s/, ""));
    } else if (line.trim() === "") {
      flushList();
    } else {
      flushList();
      blocks.push(
        <p key={`p-${blocks.length}`} className="text-[13px] leading-[1.65] text-[var(--text-primary)]">
          {inline(line, `p-${blocks.length}`)}
        </p>,
      );
    }
  }
  flushList();
  flushTable();
  return <div className="space-y-2.5">{blocks}</div>;
}
