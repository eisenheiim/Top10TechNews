"""Minimal local UI for the LangGraph digest."""

from __future__ import annotations

import html
import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from pipeline import run

ROOT = Path(__file__).parent


def _writable_root() -> Path:
    if os.getenv("VERCEL"):
        return Path("/tmp/top10technews")
    return ROOT


PORT = 8765

GRAPH_MERMAID = """
flowchart LR
  classDef startEnd fill:#1c2421,stroke:#1c2421,stroke-width:1.5px,color:#ffffff
  classDef source fill:#e8f2f0,stroke:#1f6f63,stroke-width:1px,color:#1c2421
  classDef node fill:#ffffff,stroke:#1f6f63,stroke-width:1px,color:#1c2421
  classDef llm fill:#e5f2ef,stroke:#1f6f63,stroke-width:1.5px,color:#1f6f63
  classDef route fill:#f3f6f5,stroke:#5c6b65,stroke-width:1px,color:#1c2421
  classDef decide fill:#fff7e8,stroke:#1f6f63,stroke-width:1.5px,color:#1c2421

  START([Start]):::startEnd

  subgraph Collect["collect_items"]
    direction TB
    HN["Hacker News"]:::source
    RSS["RSS feeds"]:::source
    Merge["merge · buffer 14"]:::node
    HN --> Merge
    RSS --> Merge
  end

  Classify[classify_items]:::llm

  subgraph Routes["rewrite by category"]
    direction TB
    R[rewrite_research]:::route
    P[rewrite_product]:::route
    T[rewrite_tools]:::route
  end

  Summarize[summarize]:::llm
  Gate{{"revision_pass?"}}:::decide
  Revise[revise]:::llm
  Assemble[assemble_ui_payload]:::node
  ENDNODE([End]):::startEnd

  START --> Collect --> Classify
  Classify --> R
  Classify --> P
  Classify --> T
  R --> Summarize
  P --> Summarize
  T --> Summarize
  Summarize --> Gate
  Gate -->|"0 · draft"| Revise
  Revise -->|"recommendations"| Summarize
  Gate -->|"1 · final"| Assemble --> ENDNODE
""".strip()


def load_payload() -> dict:
    path = _writable_root() / "ui_payload.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    for candidate in (
        ROOT / "history" / "latest.json",
        _writable_root() / "history" / "latest.json",
    ):
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {"summary": "", "items": [], "recommendations": []}


def save_payload(payload: dict) -> None:
    root = _writable_root()
    root.mkdir(parents=True, exist_ok=True)
    (root / "ui_payload.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def render_html(payload: dict, error: str = "") -> str:
    items_html = []
    for item in payload.get("items") or []:
        source = html.escape(item.get("source", ""))
        category = html.escape(item.get("category", ""))
        rewritten = html.escape(item.get("rewritten") or item.get("original") or "")
        original = html.escape(item.get("original") or "")
        url = html.escape(item.get("url") or "#", quote=True)
        items_html.append(
            f"""
            <article class="story">
              <span class="cat">{category}</span>
              <a class="source" href="{url}" target="_blank" rel="noreferrer">{source}</a>
              <p class="lede">{rewritten}</p>
              <details>
                <summary>Original headline</summary>
                <p class="original">{original}</p>
              </details>
            </article>
            """
        )

    summary = html.escape(payload.get("summary") or "No summary yet. Run the pipeline.")
    items_block = "".join(items_html) or "<p class='empty'>No items yet.</p>"
    error_block = f"<p class='error'>{html.escape(error)}</p>" if error else ""
    graph = GRAPH_MERMAID

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Top10TechNews</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=Instrument+Sans:wght@500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600;8..60,700&display=swap" rel="stylesheet" />
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
  <script>
    mermaid.initialize({{
      startOnLoad: false,
      securityLevel: "loose",
      theme: "base",
      themeVariables: {{
        darkMode: false,
        background: "#ffffff",
        primaryColor: "#e8f2f0",
        primaryTextColor: "#1c2421",
        primaryBorderColor: "#1f6f63",
        secondaryColor: "#f3f6f5",
        tertiaryColor: "#ffffff",
        lineColor: "#6b7c76",
        textColor: "#1c2421",
        fontFamily: "Instrument Sans, sans-serif",
        fontSize: "13px",
        clusterBkg: "#f3f6f5",
        clusterBorder: "#c5d4cf",
        titleColor: "#1f6f63"
      }},
      flowchart: {{
        curve: "basis",
        padding: 10,
        nodeSpacing: 22,
        rankSpacing: 28,
        htmlLabels: true
      }}
    }});
    document.addEventListener("DOMContentLoaded", () => {{
      const drawer = document.getElementById("graph-drawer");
      if (!drawer) return;
      drawer.addEventListener("toggle", () => {{
        if (drawer.open) mermaid.run({{ nodes: drawer.querySelectorAll(".mermaid") }});
      }});
    }});
  </script>
  <style>
    :root {{
      --bg: #f3f6f5;
      --paper: #ffffff;
      --ink: #1c2421;
      --muted: #5c6b65;
      --accent: #1f6f63;
      --accent-soft: #e5f2ef;
      --line: #d5e0dc;
      --shadow: 0 1px 2px rgba(28, 36, 33, 0.04);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "Source Serif 4", Georgia, serif;
      font-size: 18px;
      line-height: 1.65;
      background:
        radial-gradient(900px 420px at 0% 0%, rgba(31, 111, 99, 0.08), transparent 55%),
        linear-gradient(180deg, #eef3f1 0%, var(--bg) 40%, #e9efed 100%);
    }}
    main {{
      width: min(1100px, calc(100% - 2rem));
      margin: 0 auto;
      padding: 1.5rem 0 3rem;
    }}
    header.masthead {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      padding-bottom: 1.1rem;
      margin-bottom: 1.4rem;
      border-bottom: 3px solid var(--ink);
    }}
    .brand {{
      font-family: "Instrument Sans", sans-serif;
      font-size: clamp(1.8rem, 4vw, 2.4rem);
      font-weight: 700;
      letter-spacing: -0.04em;
      margin: 0;
      line-height: 1;
      color: var(--ink);
    }}
    .actions {{
      display: flex;
      gap: 0.5rem;
      flex-shrink: 0;
    }}
    button, .ghost, details.graph-drawer > summary {{
      appearance: none;
      border: 1.5px solid var(--ink);
      background: var(--ink);
      color: #fff;
      font-family: "Instrument Sans", sans-serif;
      font-size: 0.92rem;
      font-weight: 600;
      padding: 0.55rem 0.9rem;
      cursor: pointer;
      text-decoration: none;
      line-height: 1.2;
      border-radius: 6px;
    }}
    .ghost, details.graph-drawer > summary {{
      background: transparent;
      color: var(--ink);
    }}
    details.graph-drawer {{
      margin: 0 0 1.25rem;
    }}
    details.graph-drawer > summary {{
      display: inline-block;
      list-style: none;
      margin-bottom: 0.65rem;
    }}
    details.graph-drawer > summary::-webkit-details-marker {{ display: none; }}
    details.graph-drawer[open] > summary {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    details.graph-drawer .panel {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 10px;
      padding: 0.9rem;
      overflow-x: auto;
      box-shadow: var(--shadow);
    }}
    details.graph-drawer .mermaid {{
      display: flex;
      justify-content: center;
    }}
    details.graph-drawer .mermaid svg {{
      max-width: 100%;
      max-height: 340px;
      height: auto;
    }}
    .lead-block {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 1.4rem 1.6rem;
      margin-bottom: 1.75rem;
      box-shadow: var(--shadow);
    }}
    .section-label {{
      font-family: "Instrument Sans", sans-serif;
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent);
      margin: 0 0 0.7rem;
    }}
    .summary {{
      font-size: clamp(1.2rem, 2.2vw, 1.4rem);
      line-height: 1.55;
      margin: 0;
      font-weight: 600;
      color: var(--ink);
    }}
    .stories-label {{
      margin: 0 0 0.85rem;
    }}
    .stories-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 1.1rem;
    }}
    @media (max-width: 900px) {{
      .stories-grid {{ grid-template-columns: 1fr 1fr; }}
    }}
    @media (max-width: 640px) {{
      .stories-grid {{ grid-template-columns: 1fr; }}
      header.masthead {{ flex-wrap: wrap; }}
    }}
    .story {{
      display: flex;
      flex-direction: column;
      gap: 0.55rem;
      min-height: 100%;
      padding: 1.2rem 1.25rem 1.1rem;
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: 12px;
      box-shadow: var(--shadow);
    }}
    .cat {{
      align-self: flex-start;
      font-family: "Instrument Sans", sans-serif;
      font-size: 0.75rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--accent);
      background: var(--accent-soft);
      padding: 0.28rem 0.5rem;
      border-radius: 4px;
    }}
    .source {{
      color: var(--ink);
      text-decoration: none;
      font-family: "Instrument Sans", sans-serif;
      font-size: 1.05rem;
      font-weight: 700;
      line-height: 1.3;
      word-break: break-word;
    }}
    .source:hover {{ color: var(--accent); }}
    .lede {{
      margin: 0;
      flex: 1;
      font-size: 1.05rem;
      line-height: 1.55;
      color: #2a342f;
    }}
    .story details {{
      margin-top: 0.25rem;
      padding-top: 0.45rem;
      border-top: 1px solid var(--line);
    }}
    .story details summary {{
      cursor: pointer;
      color: var(--muted);
      font-family: "Instrument Sans", sans-serif;
      font-size: 0.85rem;
      font-weight: 600;
      list-style: none;
    }}
    .story details summary::-webkit-details-marker {{ display: none; }}
    .original {{
      color: var(--muted);
      line-height: 1.45;
      margin: 0.45rem 0 0;
      font-size: 0.95rem;
    }}
    .error {{
      color: #7a2e28;
      background: #f8e9e7;
      border: 1px solid #e2b7b2;
      border-radius: 8px;
      padding: 0.8rem 1rem;
      white-space: pre-wrap;
      font-family: "Instrument Sans", sans-serif;
      font-size: 0.9rem;
      margin: 0 0 1rem;
    }}
    .empty {{
      color: var(--muted);
      margin: 0;
      grid-column: 1 / -1;
      font-family: "Instrument Sans", sans-serif;
    }}
  </style>
</head>
<body>
  <main>
    <header class="masthead">
      <h1 class="brand">Top10TechNews</h1>
      <div class="actions">
        <form method="post" action="/refresh">
          <button type="submit">Run</button>
        </form>
        <a class="ghost" href="/">Reload</a>
      </div>
    </header>
    {error_block}

    <details class="graph-drawer" id="graph-drawer">
      <summary>See LangGraph</summary>
      <div class="panel">
        <div class="mermaid">
{graph}
        </div>
      </div>
    </details>

    <section class="lead-block">
      <p class="section-label">Today’s brief</p>
      <p class="summary">{summary}</p>
    </section>

    <section>
      <p class="section-label stories-label">Top stories</p>
      <div class="stories-grid">
        {items_block}
      </div>
    </section>
  </main>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[web] {self.address_string()} {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/payload":
            body = json.dumps(load_payload(), ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return
        if path != "/":
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        page = render_html(load_payload()).encode("utf-8")
        self._send(200, page, "text/html; charset=utf-8")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/refresh":
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        error = ""
        try:
            payload = run(save=True)
            save_payload(payload)
        except Exception:
            error = traceback.format_exc()
            payload = load_payload()
        page = render_html(payload, error=error).encode("utf-8")
        self._send(200, page, "text/html; charset=utf-8")


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Open http://127.0.0.1:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
