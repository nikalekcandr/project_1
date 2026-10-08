import { Fragment, type ReactNode } from "react";

/** Minimal, safe Markdown renderer (builds React elements — never injects raw HTML). */
export function Markdown(props: { text: string; className?: string }) {
  return <div className={`md ${props.className ?? ""}`}>{renderBlocks(props.text)}</div>;
}

function renderInline(text: string, keyPrefix = ""): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|_[^_\s][^_]*_|\*[^*\s][^*]*\*|<br\s*\/?>)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${keyPrefix}-${i++}`;
    if (tok.startsWith("**")) out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    else if (tok.startsWith("`")) out.push(<code key={key}>{tok.slice(1, -1)}</code>);
    else if (tok.startsWith("<br")) out.push(<br key={key} />);
    else out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

function renderBlocks(text: string): ReactNode[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0;
  let k = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i++;
      continue;
    }
    const heading = /^(#{1,4})\s+(.*)$/.exec(trimmed);
    if (heading) {
      const level = heading[1].length;
      const content = renderInline(heading[2], `h${k}`);
      blocks.push(
        level === 1 ? (
          <h1 key={k++}>{content}</h1>
        ) : level === 2 ? (
          <h2 key={k++}>{content}</h2>
        ) : level === 3 ? (
          <h3 key={k++}>{content}</h3>
        ) : (
          <h4 key={k++}>{content}</h4>
        ),
      );
      i++;
      continue;
    }
    if (/^(-{3,}|\*{3,})$/.test(trimmed)) {
      blocks.push(<hr key={k++} />);
      i++;
      continue;
    }
    if (trimmed.startsWith("|") && i + 1 < lines.length && /^\|?\s*:?-{2,}/.test(lines[i + 1].trim())) {
      const header = splitRow(trimmed);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) rows.push(splitRow(lines[i++]));
      blocks.push(
        <table key={k++}>
          <thead>
            <tr>
              {header.map((h, j) => (
                <th key={j}>{renderInline(h, `th${j}`)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, ri) => (
              <tr key={ri}>
                {r.map((c, ci) => (
                  <td key={ci}>{renderInline(c, `td${ri}-${ci}`)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
      continue;
    }
    if (trimmed.startsWith(">")) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) quote.push(lines[i++].trim().replace(/^>\s?/, ""));
      blocks.push(<blockquote key={k++}>{renderInline(quote.join(" "), `q${k}`)}</blockquote>);
      continue;
    }
    if (/^([-*•]|\d+[.)])\s+/.test(trimmed)) {
      const ordered = /^\d+[.)]/.test(trimmed);
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i].trim().replace(/^([-*•]|\d+[.)])\s+/, ""));
        i++;
      }
      const lis = items.map((it, j) => <li key={j}>{renderInline(it, `li${k}-${j}`)}</li>);
      blocks.push(ordered ? <ol key={k++}>{lis}</ol> : <ul key={k++}>{lis}</ul>);
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|>|\||([-*•]|\d+[.)])\s+|-{3,}$)/.test(lines[i].trim())) {
      para.push(lines[i++].trim());
    }
    if (!para.length) {
      // Unrecognised single line — render as paragraph to guarantee progress.
      para.push(lines[i++].trim());
    }
    blocks.push(
      <p key={k++}>
        {para.map((pl, j) => (
          <Fragment key={j}>
            {j > 0 && <br />}
            {renderInline(pl, `p${k}-${j}`)}
          </Fragment>
        ))}
      </p>,
    );
  }
  return blocks;
}
