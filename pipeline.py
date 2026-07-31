"""AI digest: HN + RSS collect → summarize → rewrite → UI payload."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, TypedDict
from xml.etree import ElementTree as ET

import httpx
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

load_dotenv()

MAX_ITEMS = 10
HN_COUNT = 5
RSS_COUNT = 5

RSS_FEEDS = [
    ("OpenAI", "https://openai.com/news/rss.xml"),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml"),
    ("Google AI", "https://blog.google/technology/ai/rss/"),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml"),
    ("Microsoft Research", "https://www.microsoft.com/en-us/research/feed/"),
]

HN_API = "https://hn.algolia.com/api/v1/search_by_date"
HN_QUERY = "AI LLM GPT Claude"


class Item(TypedDict):
    id: str
    source: str
    text: str
    created_at: str
    url: str


class RewrittenItem(TypedDict):
    id: str
    source: str
    url: str
    created_at: str
    original: str
    rewritten: str


class GraphState(TypedDict):
    items: list[Item]
    summary: str
    rewritten: list[RewrittenItem]
    ui_payload: dict[str, Any]


class RewriteItem(BaseModel):
    id: str
    rewritten: str = Field(description="3-4 sentence clear explanation")


class RewriteBatch(BaseModel):
    items: list[RewriteItem]


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
            }
        )
    return items[:limit]


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def _collect_rss(client: httpx.Client, limit: int) -> list[Item]:
    """Her feed'den 1 item al; yetmezse sırayla 2. item'lara geç."""
    per_feed: list[list[Item]] = []

    for source, feed_url in RSS_FEEDS:
        try:
            resp = client.get(feed_url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
        except Exception:
            continue

        entries: list[Item] = []
        nodes = list(root.iter())
        # RSS <item> veya Atom <entry>
        candidates = [n for n in nodes if _local(n.tag) in {"item", "entry"}]
        for node in candidates[:2]:
            fields = {_local(c.tag): (c.text or "").strip() for c in list(node)}
            # Atom link href
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

    items = (hn + rss)[:MAX_ITEMS]
    if not items:
        raise RuntimeError("No content collected from HN/RSS.")
    return {"items": items}


def summarize(state: GraphState) -> dict[str, Any]:
    lines = [f"[{i['source']}] {i['text']}" for i in state["items"]]
    prompt = (
        "Write one short English paragraph summarizing these recent AI headlines. "
        "Keep it concise and highlight the main developments.\n\n"
        + "\n\n".join(lines)
    )
    msg = _llm().invoke(prompt)
    return {"summary": str(msg.content).strip()}


def rewrite_items(state: GraphState) -> dict[str, Any]:
    payload = [
        {"id": i["id"], "source": i["source"], "text": i["text"]}
        for i in state["items"]
    ]
    prompt = (
        "Rewrite each item in clear, readable English. "
        "Use at most 3-4 sentences per item. Keep the meaning; do not exaggerate.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    structured = _llm().with_structured_output(RewriteBatch)
    batch = structured.invoke(prompt)
    by_id = {item.id: item.rewritten for item in batch.items}

    rewritten: list[RewrittenItem] = [
        {
            "id": i["id"],
            "source": i["source"],
            "url": i["url"],
            "created_at": i["created_at"],
            "original": i["text"],
            "rewritten": by_id.get(i["id"], i["text"]),
        }
        for i in state["items"]
    ]
    return {"rewritten": rewritten}


def assemble_ui_payload(state: GraphState) -> dict[str, Any]:
    return {
        "ui_payload": {
            "summary": state["summary"],
            "items": state["rewritten"],
        }
    }


def build_graph():
    g = StateGraph(GraphState)
    g.add_node("collect_items", collect_items)
    g.add_node("summarize", summarize)
    g.add_node("rewrite_items", rewrite_items)
    g.add_node("assemble_ui_payload", assemble_ui_payload)

    g.add_edge(START, "collect_items")
    g.add_edge("collect_items", "summarize")
    g.add_edge("summarize", "rewrite_items")
    g.add_edge("rewrite_items", "assemble_ui_payload")
    g.add_edge("assemble_ui_payload", END)
    return g.compile()


def run() -> dict[str, Any]:
    app = build_graph()
    result = app.invoke(
        {
            "items": [],
            "summary": "",
            "rewritten": [],
            "ui_payload": {},
        }
    )
    return result["ui_payload"]
