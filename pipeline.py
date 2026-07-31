"""AI digest: collect → classify → rewrite routes → summarize → revise → UI."""

from __future__ import annotations

import json
import operator
import os
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict
from xml.etree import ElementTree as ET

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

load_dotenv()

TARGET_ITEMS = 10
COLLECT_ITEMS = 14
HN_COUNT = 8
RSS_COUNT = 8
Category = Literal["research", "product", "tools"]

RSS_FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Google AI", "https://blog.google/technology/ai/rss/"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/"),
]

HN_API = "https://hn.algolia.com/api/v1/search_by_date"
HN_QUERY = "AI LLM GPT Claude"
def _data_dir() -> Path:
    # Vercel filesystem is read-only except /tmp
    if os.getenv("VERCEL"):
        return Path("/tmp/top10technews")
    return Path(__file__).parent


HISTORY_DIR = _data_dir() / "history"


class Item(TypedDict):
    id: str
    source: str
    text: str
    created_at: str
    url: str
    category: Category


class RewrittenItem(TypedDict):
    id: str
    source: str
    url: str
    created_at: str
    category: Category
    original: str
    rewritten: str


class GraphState(TypedDict):
    items: list[Item]
    rewritten: Annotated[list[RewrittenItem], operator.add]
    final_items: list[RewrittenItem]
    summary: str
    recommendations: list[str]
    dropped: list[RewrittenItem]
    revision_pass: int
    ui_payload: dict[str, Any]


class ClassifyItem(BaseModel):
    id: str
    category: Category


class ClassifyBatch(BaseModel):
    items: list[ClassifyItem]


class RewriteItem(BaseModel):
    id: str
    rewritten: str = Field(description="3-4 sentence clear explanation")


class RewriteBatch(BaseModel):
    items: list[RewriteItem]


class ReviseResult(BaseModel):
    keep_ids: list[str] = Field(description="Item ids worth keeping in the digest")
    drop_ids: list[str] = Field(description="Noisy / low-signal item ids to drop")
    recommendations: list[str] = Field(
        description="Concrete recommendations for regenerating a better summary"
    )


def _llm() -> ChatOpenAI:
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        temperature=0.3,
    )


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
    except Exception:
        return value


def _collect_hn(client: httpx.Client, limit: int) -> list[Item]:
    resp = client.get(
        HN_API,
        params={"query": HN_QUERY, "tags": "story", "hitsPerPage": limit},
    )
    resp.raise_for_status()
    items: list[Item] = []
    for hit in resp.json().get("hits") or []:
        title = (hit.get("title") or "").strip()
        if not title:
            continue
        object_id = str(hit.get("objectID") or "")
        url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
        items.append(
            {
                "id": f"hn-{object_id}",
                "source": f"HN/@{hit.get('author') or 'unknown'}",
                "text": title,
                "created_at": _parse_date(hit.get("created_at")),
                "url": url,
                "category": "tools",
            }
        )
    return items[:limit]


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _collect_rss(client: httpx.Client, limit: int) -> list[Item]:
    per_feed: list[list[Item]] = []

    for source, feed_url in RSS_FEEDS:
        try:
            resp = client.get(feed_url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except Exception:
            continue

        entries: list[Item] = []
        candidates = [n for n in root.iter() if _local(n.tag) in {"item", "entry"}]
        for node in candidates[:2]:
            fields = {_local(c.tag): (c.text or "").strip() for c in list(node)}
            if "link" not in fields or not fields["link"]:
                for c in list(node):
                    if _local(c.tag) == "link":
                        href = c.attrib.get("href")
                        if href:
                            fields["link"] = href
                            break

            title = fields.get("title") or ""
            summary = fields.get("description") or fields.get("summary") or fields.get("content") or ""
            text = title
            if summary:
                cleaned = _strip_html(summary)
                if cleaned:
                    text = f"{title}. {cleaned}" if title else cleaned

            link = fields.get("link") or fields.get("id") or feed_url
            pub = fields.get("pubDate") or fields.get("published") or fields.get("updated")
            item_id = fields.get("guid") or fields.get("id") or link
            if not text:
                continue
            entries.append(
                {
                    "id": f"rss-{abs(hash(item_id))}",
                    "source": source,
                    "text": text[:1200],
                    "created_at": _parse_date(pub),
                    "url": link,
                    "category": "product",
                }
            )
        if entries:
            per_feed.append(entries)

    picked: list[Item] = []
    for entries in per_feed:
        if entries and len(picked) < limit:
            picked.append(entries[0])

    if len(picked) < limit:
        for entries in per_feed:
            if len(entries) >= 2 and len(picked) < limit:
                second = entries[1]
                if second["id"] not in {p["id"] for p in picked}:
                    picked.append(second)

    return picked[:limit]


def collect_items(state: GraphState) -> dict[str, Any]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        hn = _collect_hn(client, HN_COUNT)
        rss = _collect_rss(client, RSS_COUNT)

    items = (hn + rss)[:COLLECT_ITEMS]
    if not items:
        raise RuntimeError("No content collected from HN/RSS.")
    return {"items": items}


def classify_items(state: GraphState) -> dict[str, Any]:
    payload = [{"id": i["id"], "source": i["source"], "text": i["text"]} for i in state["items"]]
    prompt = (
        "Classify each AI news item into exactly one category:\n"
        "- research: papers, models, scientific results, benchmarks\n"
        "- product: company launches, APIs, product updates, policy/business\n"
        "- tools: developer tools, open-source projects, Show HN, utilities\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    batch = _llm().with_structured_output(ClassifyBatch).invoke(prompt)
    by_id = {row.id: row.category for row in batch.items}
    items: list[Item] = [
        {**item, "category": by_id.get(item["id"], item.get("category", "tools"))}
        for item in state["items"]
    ]
    return {"items": items}


def _rewrite_category(state: GraphState, category: Category) -> dict[str, Any]:
    subset = [i for i in state["items"] if i.get("category") == category]
    if not subset:
        return {"rewritten": []}

    payload = [
        {"id": i["id"], "source": i["source"], "text": i["text"], "category": category}
        for i in subset
    ]
    prompt = (
        f"Rewrite each {category} item in clear, readable English. "
        "Use at most 3-4 sentences per item. Keep the meaning; do not exaggerate.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    batch = _llm().with_structured_output(RewriteBatch).invoke(prompt)
    by_id = {row.id: row.rewritten for row in batch.items}
    rewritten: list[RewrittenItem] = [
        {
            "id": i["id"],
            "source": i["source"],
            "url": i["url"],
            "created_at": i["created_at"],
            "category": category,
            "original": i["text"],
            "rewritten": by_id.get(i["id"], i["text"]),
        }
        for i in subset
    ]
    return {"rewritten": rewritten}


def rewrite_research(state: GraphState) -> dict[str, Any]:
    return _rewrite_category(state, "research")


def rewrite_product(state: GraphState) -> dict[str, Any]:
    return _rewrite_category(state, "product")


def rewrite_tools(state: GraphState) -> dict[str, Any]:
    return _rewrite_category(state, "tools")


def summarize(state: GraphState) -> dict[str, Any]:
    source_items = state.get("final_items") or state.get("rewritten") or []
    lines = [
        f"[{i['category']}] [{i['source']}] {i['rewritten']}"
        for i in source_items
    ]
    if not lines:
        return {"summary": "No items to summarize."}

    recommendations = state.get("recommendations") or []
    if recommendations:
        prompt = (
            "Write one short English paragraph summarizing these AI updates.\n"
            "Apply the editor recommendations below. Only cover the listed items. "
            "Keep it concise.\n\n"
            f"Recommendations:\n{json.dumps(recommendations, ensure_ascii=False)}\n\n"
            f"Items:\n" + "\n\n".join(lines)
        )
    else:
        prompt = (
            "Write one short English paragraph summarizing these recent AI updates. "
            "Cover research, product, and tools if present. Keep it concise.\n\n"
            + "\n\n".join(lines)
        )
    msg = _llm().invoke(prompt)
    return {"summary": str(msg.content).strip()}


def _select_digest_items(
    pool: list[RewrittenItem],
    keep_ids: list[str],
    target: int = TARGET_ITEMS,
) -> tuple[list[RewrittenItem], list[RewrittenItem]]:
    """Rank by LLM keep_ids, then fill from pool. Always keep up to `target` when possible."""
    by_id = {i["id"]: i for i in pool}
    ranked: list[RewrittenItem] = []
    seen: set[str] = set()

    for item_id in keep_ids:
        item = by_id.get(item_id)
        if item is None or item_id in seen:
            continue
        ranked.append(item)
        seen.add(item_id)

    for item in pool:
        if item["id"] in seen:
            continue
        ranked.append(item)
        seen.add(item["id"])

    # Only drop surplus above the target — never shrink below target when pool allows.
    kept = ranked[:target]
    kept_ids = {i["id"] for i in kept}
    dropped = [i for i in ranked[target:] if i["id"] not in kept_ids]
    # Preserve any pool leftovers not already ranked (shouldn't happen, but keep deterministic).
    for item in pool:
        if item["id"] not in kept_ids and item["id"] not in {d["id"] for d in dropped}:
            dropped.append(item)
    return kept, dropped


def revise(state: GraphState) -> dict[str, Any]:
    pool = state["rewritten"]
    payload = {
        "summary": state["summary"],
        "items": [
            {
                "id": i["id"],
                "category": i["category"],
                "source": i["source"],
                "rewritten": i["rewritten"],
            }
            for i in pool
        ],
    }
    prompt = (
        "You are a digest editor. Review the draft summary and items.\n"
        f"1) Rank the strongest AI/tech news items by putting the best ids first in keep_ids.\n"
        f"2) keep_ids must include exactly {TARGET_ITEMS} ids when at least "
        f"{TARGET_ITEMS} items are available (never fewer).\n"
        "3) Only list ids in drop_ids when they are surplus beyond that quota "
        "(noisy, redundant, off-topic, or low-signal).\n"
        "4) Give concrete recommendations so summarize can regenerate a better summary.\n"
        "Do not write the final summary yourself.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    result = _llm().with_structured_output(ReviseResult).invoke(prompt)
    kept, dropped = _select_digest_items(pool, result.keep_ids, TARGET_ITEMS)
    return {
        "final_items": kept,
        "dropped": dropped,
        "recommendations": result.recommendations,
        "revision_pass": 1,
    }


def route_after_summarize(state: GraphState) -> str:
    if state.get("revision_pass", 0) >= 1:
        return "assemble_ui_payload"
    return "revise"


def assemble_ui_payload(state: GraphState) -> dict[str, Any]:
    items = list(state.get("final_items") or [])
    # Backfill if revise somehow under-filled — digest should hit TARGET_ITEMS when sources allow.
    if len(items) < TARGET_ITEMS:
        items, _ = _select_digest_items(
            list(state.get("rewritten") or []) + list(state.get("dropped") or []),
            [i["id"] for i in items],
            TARGET_ITEMS,
        )
    order = {"research": 0, "product": 1, "tools": 2}
    items = sorted(items, key=lambda i: (order.get(i.get("category", "tools"), 9), i["source"]))
    items = items[:TARGET_ITEMS]
    kept_ids = {i["id"] for i in items}
    dropped = [
        i
        for i in (state.get("dropped") or state.get("rewritten") or [])
        if i["id"] not in kept_ids
    ]
    return {
        "ui_payload": {
            "summary": state["summary"],
            "recommendations": state.get("recommendations") or [],
            "items": items,
            "dropped": dropped,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
    }


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("collect_items", collect_items)
    g.add_node("classify_items", classify_items)
    g.add_node("rewrite_research", rewrite_research)
    g.add_node("rewrite_product", rewrite_product)
    g.add_node("rewrite_tools", rewrite_tools)
    g.add_node("summarize", summarize)
    g.add_node("revise", revise)
    g.add_node("assemble_ui_payload", assemble_ui_payload)

    g.add_edge(START, "collect_items")
    g.add_edge("collect_items", "classify_items")
    g.add_edge("classify_items", "rewrite_research")
    g.add_edge("classify_items", "rewrite_product")
    g.add_edge("classify_items", "rewrite_tools")
    g.add_edge("rewrite_research", "summarize")
    g.add_edge("rewrite_product", "summarize")
    g.add_edge("rewrite_tools", "summarize")
    g.add_conditional_edges(
        "summarize",
        route_after_summarize,
        {"revise": "revise", "assemble_ui_payload": "assemble_ui_payload"},
    )
    g.add_edge("revise", "summarize")
    g.add_edge("assemble_ui_payload", END)
    return g.compile()


def save_history(payload: dict[str, Any], day: date | None = None) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    day = day or date.today()
    path = HISTORY_DIR / f"{day.isoformat()}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = HISTORY_DIR / "latest.json"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def run(save: bool = True) -> dict[str, Any]:
    app = build_graph()
    result = app.invoke(
        {
            "items": [],
            "rewritten": [],
            "final_items": [],
            "summary": "",
            "recommendations": [],
            "dropped": [],
            "revision_pass": 0,
            "ui_payload": {},
        }
    )
    payload = result["ui_payload"]
    if save:
        save_history(payload)
    return payload
