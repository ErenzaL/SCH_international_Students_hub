/**
 * Minimal, safe Markdown for assistant answers: paragraphs, headings, bullet / numbered lists, **bold**, *italic*,
 * `code`, [links](https://…), bare https URLs and [n] citations. It builds React nodes only (no HTML strings, no
 * dangerouslySetInnerHTML), so text from the model or documents can never inject markup or scripts. Only http(s)
 * links are rendered as links.
 */
import type { ReactNode } from "react";

export interface MarkdownOptions {
  /** Renders a citation marker [n]; return null to leave the text as is. */
  renderCitation?: (n: number, key: string) => ReactNode | null;
}

const INLINE = /(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|https?:\/\/[^\s)<>\]]+|\[\d{1,2}\])/g;

function safeHref(url: string): string | null {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

function link(href: string, label: ReactNode, key: string): ReactNode {
  return (
    <a key={key} href={href} target="_blank" rel="noopener noreferrer nofollow" className="break-words font-medium text-primary underline underline-offset-2">
      {label}
    </a>
  );
}

export function renderInline(text: string, opts: MarkdownOptions = {}, keyPrefix = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let i = 0;
  for (const m of text.matchAll(INLINE)) {
    const tok = m[0];
    const at = m.index ?? 0;
    if (at > last) out.push(text.slice(last, at));
    const key = `${keyPrefix}-${i++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{renderInline(tok.slice(2, -2), opts, key)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={key} className="rounded bg-muted px-1 text-[0.85em]">{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("*")) out.push(<em key={key}>{renderInline(tok.slice(1, -1), opts, key)}</em>);
    else if (/^\[\d{1,2}\]$/.test(tok)) {
      const node = opts.renderCitation?.(Number(tok.slice(1, -1)), key);
      out.push(node ?? tok);
    } else if (tok.startsWith("[")) {
      const lm = /^\[([^\]]+)\]\((.+)\)$/.exec(tok);
      const href = lm ? safeHref(lm[2]) : null;
      out.push(href && lm ? link(href, lm[1], key) : tok);
    } else {
      const trimmed = tok.replace(/[.,;:]+$/, "");
      const href = safeHref(trimmed);
      out.push(href ? link(href, trimmed, key) : tok);
      if (href && trimmed.length < tok.length) out.push(tok.slice(trimmed.length));
    }
    last = at + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function renderMarkdown(text: string, opts: MarkdownOptions = {}): ReactNode[] {
  const blocks: ReactNode[] = [];
  const lines = (text ?? "").replace(/\r\n/g, "\n").split("\n");
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }
    const key = `b${k++}`;
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push(<p key={key} className="font-semibold">{renderInline(heading[1], opts, key)}</p>);
      i++;
      continue;
    }
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items: ReactNode[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        const content = lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, "");
        items.push(<li key={`${key}-${items.length}`}>{renderInline(content, opts, `${key}-${items.length}`)}</li>);
        i++;
      }
      blocks.push(ordered
        ? <ol key={key} className="list-decimal space-y-0.5 pl-5">{items}</ol>
        : <ul key={key} className="list-disc space-y-0.5 pl-5">{items}</ul>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^#{1,6}\s/.test(lines[i]) && !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    const children: ReactNode[] = [];
    para.forEach((p, n) => {
      if (n) children.push(<br key={`${key}-br${n}`} />);
      children.push(...renderInline(p, opts, `${key}-${n}`));
    });
    blocks.push(<p key={key}>{children}</p>);
  }
  return blocks;
}
