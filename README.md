# Top10TechNews

A daily AI / tech digest that turns noisy Hacker News and RSS feeds into a clear **top 10** brief.

**Who it's for:** builders, PMs, and researchers who want the signal without scrolling every source.

**Problem it solves:** AI news moves fast and spreads across many feeds. Top10TechNews collects recent updates, sorts them into research / product / tools, rewrites them for skimability, and publishes one short summary you can read in a few minutes.

A small web UI shows the summary and items in a three-column grid. Digests refresh automatically each day via GitHub Actions and are archived under `history/`.

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

| Step | What happens |
|------|----------------|
| Collect | Pull from Hacker News + RSS into a short buffer |
| Classify | Tag each item: research / product / tools |
| Rewrite | Parallel per-category rewrites (short, readable) |
| Summarize | Draft the brief; after revise, regenerate once with recommendations |
| Revision pass | Draft → revise; after one pass → assemble |
| Revise | Keep exactly 10, drop noise, emit recommendations |
| Assemble | Build the UI payload (and optional history file) |

Daily digests run on a GitHub Actions schedule so the site stays current without a manual refresh.

## License

MIT
