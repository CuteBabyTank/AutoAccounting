import { Fragment, type ReactNode } from "react";

/** **bold** inside one line. */
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? (
      <strong key={i} className="font-semibold">{part.slice(2, -2)}</strong>
    ) : (
      <Fragment key={i}>{part}</Fragment>
    ),
  );
}

/** The answer's light formatting: paragraphs, "## " headings, and "- " / "* " / "1. " lists (indented ones nest). */
export default function AnswerText({ text }: { text: string }) {
  const blocks: ReactNode[] = [];
  let items: { text: string; sub: boolean }[] = [];
  let ordered = false;
  const flush = () => {
    if (!items.length) return;
    const List = ordered ? "ol" : "ul";
    blocks.push(
      <List key={blocks.length} className={`${ordered ? "list-decimal" : "list-disc"} space-y-1 pl-5 marker:text-[var(--text-secondary)]`}>
        {items.map((it, i) => (
          <li key={i} className={it.sub ? "ml-4 list-[circle]" : ""}>{inline(it.text)}</li>
        ))}
      </List>,
    );
    items = [];
  };
  for (const raw of text.split("\n")) {
    const item = raw.match(/^(\s*)(?:([-*•])|(\d+)\.)\s+(.*)$/);
    if (item) {
      if (!items.length) ordered = !!item[3];
      items.push({ text: item[4], sub: item[1].length >= 2 });
      continue;
    }
    flush();
    const line = raw.trim();
    if (!line) continue;
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    blocks.push(
      heading ? (
        <p key={blocks.length} className="pt-1 font-semibold text-[var(--text-primary)]">{inline(heading[1])}</p>
      ) : (
        <p key={blocks.length}>{inline(line)}</p>
      ),
    );
  }
  flush();
  return <div className="space-y-3 text-[14.5px] leading-[1.65] text-[var(--text-primary)]">{blocks}</div>;
}
