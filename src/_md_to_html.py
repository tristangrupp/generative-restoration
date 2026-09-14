"""Render a markdown file to a self-contained, scrollable HTML page.

Used for METHODOLOGY.md so it can be opened straight in a browser. Falls back to a
minimal converter when the `markdown` package is absent, which covers the headings,
tables, lists, code spans, bold and italic actually used in these documents.
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

CSS = """
:root { color-scheme: light dark; }
body { max-width: 46rem; margin: 3rem auto; padding: 0 1.4rem 6rem;
       font: 16px/1.65 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       color: #1c1c1e; background: #fdfdfc; }
h1 { font-size: 2rem; margin: 0 0 .4rem; letter-spacing: -.02em; }
h2 { font-size: 1.28rem; margin: 2.6rem 0 .8rem; letter-spacing: -.01em; }
h3 { font-size: 1.05rem; margin: 1.8rem 0 .6rem; }
p { margin: 0 0 1.05rem; }
hr { border: 0; border-top: 1px solid #e3e1dd; margin: 2.4rem 0; }
code { font: 13.5px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
       background: #f0efec; padding: .12em .38em; border-radius: 3px; }
table { border-collapse: collapse; width: 100%; margin: 1.2rem 0 1.6rem;
        font-size: .93rem; display: block; overflow-x: auto; }
th, td { border-bottom: 1px solid #e3e1dd; padding: .5rem .7rem; text-align: left; }
th { font-weight: 600; border-bottom: 2px solid #d0cec9; white-space: nowrap; }
td.num, th.num { text-align: right; }
em { color: #4a4a4a; }
strong { font-weight: 650; }
ul { margin: 0 0 1.05rem; padding-left: 1.3rem; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e4e0; background: #16161a; }
  code { background: #26262c; }
  hr, th, td { border-color: #33333b; }
  th { border-bottom-color: #45454f; }
  em { color: #b3b0aa; }
}
"""


def inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)
    t = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", t)
    return t


def convert(md: str) -> str:
    out, i, lines = [], 0, md.split("\n")
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|") and i + 1 < len(lines) and set(lines[i + 1]) <= set("|-: "):
            aligns = [c.strip() for c in lines[i + 1].strip("|").split("|")]
            head = [c.strip() for c in ln.strip("|").split("|")]
            cls = ["num" if a.endswith(":") else "" for a in aligns]
            out.append("<table><thead><tr>" + "".join(
                f'<th class="{c}">{inline(h)}</th>' for h, c in zip(head, cls))
                + "</tr></thead><tbody>")
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip("|").split("|")]
                out.append("<tr>" + "".join(
                    f'<td class="{c}">{inline(v)}</td>'
                    for v, c in zip(cells, cls + [""] * len(cells))) + "</tr>")
                i += 1
            out.append("</tbody></table>")
            continue
        if ln.startswith("### "):
            out.append(f"<h3>{inline(ln[4:])}</h3>")
        elif ln.startswith("## "):
            out.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.startswith("# "):
            out.append(f"<h1>{inline(ln[2:])}</h1>")
        elif ln.strip() == "---":
            out.append("<hr>")
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif ln.strip():
            para = [ln]
            i += 1
            while (i < len(lines) and lines[i].strip()
                   and not lines[i].startswith(("#", "|", "- ", "---"))):
                para.append(lines[i])
                i += 1
            out.append(f"<p>{inline(' '.join(para))}</p>")
            continue
        i += 1
    return "\n".join(out)


def main() -> None:
    src = Path(sys.argv[1])
    dst = src.with_suffix(".html")
    md = src.read_text(encoding="utf-8")
    title = next((l[2:] for l in md.split("\n") if l.startswith("# ")), src.stem)

    try:
        import markdown
        body = markdown.markdown(md, extensions=["tables"])
    except Exception:
        body = convert(md)

    dst.write_text(
        f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{html.escape(title)}</title>\n<style>{CSS}</style></head>\n"
        f"<body>\n{body}\n</body></html>\n",
        encoding="utf-8")
    print(f"-> {dst}")


if __name__ == "__main__":
    main()
