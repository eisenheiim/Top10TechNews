# Top10TechNews

Top10TechNews is a daily AI / tech digest built with **[LangGraph](https://langchain-ai.github.io/langgraph/)**. It pulls recent stories from Hacker News and RSS, then runs them through a graph-orchestrated pipeline that ranks, rewrites, and compresses the noise into a clear **top 10** brief you can read in a few minutes.

The LangGraph state machine owns the full flow: collect sources, classify into research / product / tools, rewrite those lanes in parallel, draft a summary, run a revision gate that can loop once for a stronger cut, then assemble the final digest for the web UI and daily archive under `history/`.

## How it works

```mermaid
flowchart LR
  Start([Start]) --> Collect[Collect]
  Collect --> Classify[Classify]
  Classify --> Research[Rewrite research]
  Classify --> Product[Rewrite product]
  Classify --> Tools[Rewrite tools]
  Research --> Summarize[Summarize]
  Product --> Summarize
  Tools --> Summarize
  Summarize --> Gate{{Revision pass?}}
  Gate -->|draft| Revise[Revise]
  Revise --> Summarize
  Gate -->|final| Assemble[Assemble]
  Assemble --> End([End])
```

### Graph stages

- **Collect** — Fetches recent AI/tech items from Hacker News and RSS into a shared item pool.
- **Classify** — Labels each item as `research`, `product`, or `tools` so later stages can specialize.
- **Rewrite (parallel)** — Three routes rewrite their category in clear, skimable English, then join before summarization.
- **Summarize** — Drafts one short paragraph covering the rewritten updates (and applies editor notes on the second pass).
- **Revision pass gate** — After the first summary, routes to **Revise**; after revision has run once, routes to **Assemble**.
- **Revise** — Ranks the strongest items into a top-10 set, drops surplus noise, and returns recommendations; then loops back to **Summarize**.
- **Assemble** — Builds the final UI payload (summary, kept items, dropped items, timestamp) for display and history.

Digests refresh automatically each day via GitHub Actions.

## License

MIT
