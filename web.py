"""Minimal local UI for the LangGraph digest."""

from __future__ import annotations

import html
import json
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from pipeline import run

ROOT = Path(__file__).parent
PAYLOAD_PATH = ROOT / "ui_payload.json"
PORT = 8765

GRAPH_MERMAID = """
flowchart LR
  classDef startEnd fill:#102016,stroke:#c8f560,stroke-width:1.5px,color:#e8f2ea
  classDef source fill:#1a2e24,stroke:#7fd4a8,stroke-width:1px,color:#e8f2ea
  classDef node fill:#163028,stroke:#c8f560,stroke-width:1px,color:#e8f2ea
  classDef llm fill:#24361f,stroke:#c8f560,stroke-width:1.5px,color:#c8f560

  START([Start]):::startEnd

  subgraph Collect["collect_items"]
    direction TB
    HN["Hacker News<br/>5 stories"]:::source
    RSS["RSS feeds<br/>OpenAI · DeepMind · Google AI<br/>HF · MSR"]:::source
    Merge["merge · max 10"]:::node
    HN --> Merge
    RSS --> Merge
  end

  Summarize[summarize]:::llm
  Rewrite[rewrite_items]:::llm
  Assemble[assemble_ui_payload]:::node
  ENDNODE([End]):::startEnd

  START --> Collect
  Collect --> Summarize --> Rewrite --> Assemble --> ENDNODE
""".strip()


def load_payload() -> dict:
    if PAYLOAD_PATH.exists():
        return json.loads(PAYLOAD_PATH.read_text(encoding="utf-8"))
    return {"summary": "", "items": []}


def save_payload(payload: dict) -> None:
    PAYLOAD_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def render_html(payload: dict, error: str = "") -> str:
    items_html = []
    for item in payload.get("items") or []:
        source = html.escape(item.get("source", ""))
        rewritten = html.escape(item.get("rewritten") or item.get("original") or "")
        original = html.escape(item.get("original") or "")
        url = html.escape(item.get("url") or "#", quote=True)
        items_html.append(
            f"""
            <article class="item">
              <div class="item-top">
                <a class="source" href="{url}" target="_blank" rel="noreferrer">{source}</a>
                <details>
                  <summary>orig</summary>
                  <p class="original">{original}</p>
                </details>
              </div>
              <p class="rewritten">{rewritten}</p>
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
  <title>ConnectSummary</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,600;0,9..40,700;1,9..40,400&family=Fragment+Mono:wght@400&display=swap" rel="stylesheet" />
  <script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
  <script>
    mermaid.initialize({{
      startOnLoad: false,
      securityLevel: "loose",
      theme: "base",
      themeVariables: {{
        darkMode: true,
        background: "transparent",
        primaryColor: "#163028",
        primaryTextColor: "#e8f2ea",
        primaryBorderColor: "#c8f560",
        secondaryColor: "#1a2e24",
        tertiaryColor: "#102016",
        lineColor: "#9bb0a3",
        textColor: "#e8f2ea",
        fontFamily: "DM Sans, sans-serif",
        fontSize: "12px",
        clusterBkg: "rgba(19, 32, 27, 0.65)",
        clusterBorder: "rgba(200, 245, 96, 0.35)",
        titleColor: "#c8f560"
      }},
      flowchart: {{
        curve: "basis",
        padding: 8,
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
      --bg0: #0b1210;
      --bg1: #13201b;
      --ink: #e8f2ea;
      --muted: #9bb0a3;
      --accent: #c8f560;
      --line: rgba(200, 245, 96, 0.18);
      --panel: rgba(19, 32, 27, 0.88);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "DM Sans", sans-serif;
      font-size: 14px;
      background:
        radial-gradient(900px 420px at 8% -10%, rgba(200, 245, 96, 0.10), transparent 55%),
        linear-gradient(180deg, var(--bg0), var(--bg1));
    }}
    main {{
      width: min(860px, calc(100% - 1.5rem));
      margin: 0 auto;
      padding: 1rem 0 1.5rem;
    }}
    .top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.75rem;
      margin-bottom: 0.75rem;
    }}
    .brand-wrap {{ min-width: 0; }}
    .brand {{
      font-family: "Fragment Mono", monospace;
      font-size: 1.25rem;
      letter-spacing: -0.03em;
      margin: 0;
      line-height: 1.1;
    }}
    .lead {{
      color: var(--muted);
      margin: 0.15rem 0 0;
      font-size: 0.8rem;
      line-height: 1.3;
    }}
    .actions {{
      display: flex;
      gap: 0.4rem;
      flex-shrink: 0;
    }}
    button, .ghost {{
      appearance: none;
      border: 1px solid var(--accent);
      background: var(--accent);
      color: #102016;
      font: inherit;
      font-size: 0.75rem;
      font-weight: 700;
      padding: 0.28rem 0.55rem;
      cursor: pointer;
      text-decoration: none;
      line-height: 1.2;
    }}
    .ghost {{
      background: transparent;
      color: var(--accent);
    }}
    section {{
      border-top: 1px solid var(--line);
      padding: 0.65rem 0;
    }}
    h2 {{
      font-size: 0.68rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--accent);
      margin: 0 0 0.4rem;
      font-family: "Fragment Mono", monospace;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      padding: 0.55rem 0.7rem;
    }}
    .summary {{
      font-size: 0.9rem;
      line-height: 1.4;
      margin: 0;
    }}
    details.graph-drawer {{
      margin: 0 0 0.65rem;
    }}
    details.graph-drawer > summary {{
      display: inline-block;
      border: 1px solid var(--accent);
      background: transparent;
      color: var(--accent);
      font-size: 0.75rem;
      font-weight: 700;
      padding: 0.28rem 0.55rem;
      cursor: pointer;
      line-height: 1.2;
      list-style: none;
      margin-bottom: 0.45rem;
    }}
    details.graph-drawer > summary::-webkit-details-marker {{ display: none; }}
    details.graph-drawer[open] > summary {{
      background: var(--accent);
      color: #102016;
      margin-bottom: 0.5rem;
    }}
    details.graph-drawer .panel {{
      padding: 0.55rem 0.6rem;
      overflow-x: auto;
    }}
    details.graph-drawer .mermaid {{
      display: flex;
      justify-content: center;
    }}
    details.graph-drawer .mermaid svg {{
      max-width: 100%;
      max-height: 280px;
      height: auto;
    }}
    .item {{
      padding: 0.45rem 0;
      border-bottom: 1px solid var(--line);
    }}
    .item:last-child {{ border-bottom: 0; }}
    .item-top {{
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 0.5rem;
    }}
    .source {{
      color: var(--accent);
      text-decoration: none;
      font-family: "Fragment Mono", monospace;
      font-size: 0.72rem;
    }}
    .rewritten {{
      margin: 0.2rem 0 0;
      line-height: 1.35;
      font-size: 0.86rem;
    }}
    details {{ position: relative; }}
    details summary {{
      cursor: pointer;
      color: var(--muted);
      font-size: 0.7rem;
      list-style: none;
    }}
    details summary::-webkit-details-marker {{ display: none; }}
    .original {{
      color: var(--muted);
      line-height: 1.35;
      margin: 0.35rem 0 0;
      font-size: 0.78rem;
    }}
    .error {{
      color: #ffb4a8;
      background: rgba(120, 40, 30, 0.35);
      border: 1px solid rgba(255, 180, 168, 0.35);
      padding: 0.5rem 0.7rem;
      white-space: pre-wrap;
      font-size: 0.75rem;
      margin: 0 0 0.5rem;
    }}
    .empty {{ color: var(--muted); }}
  </style>
</head>
<body>
  <main>
    <div class="top">
      <div class="brand-wrap">
        <h1 class="brand">ConnectSummary</h1>
        <p class="lead">HN + RSS → summarize → rewrite</p>
      </div>
      <div class="actions">
        <form method="post" action="/refresh">
          <button type="submit">Run</button>
        </form>
        <a class="ghost" href="/">Reload</a>
      </div>
    </div>
    {error_block}

    <details class="graph-drawer" id="graph-drawer">
      <summary>See LangGraph</summary>
      <div class="panel">
        <div class="mermaid">
{graph}
        </div>
      </div>
    </details>

    <section>
      <h2>Summary</h2>
      <div class="panel">
        <p class="summary">{summary}</p>
      </div>
    </section>

    <section>
      <h2>Items</h2>
      <div class="panel">
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
            payload = run()
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
