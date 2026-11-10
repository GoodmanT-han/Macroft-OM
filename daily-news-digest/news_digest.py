#!/usr/bin/env python3
"""Collect a daily news digest from CNN, BBC News, and G1."""

import argparse
import gzip
import html
import re
import sqlite3
import ssl
import sys
import unicodedata
import webbrowser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import IntFlag
from http.client import HTTPException
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import certifi


class Topic(IntFlag):
    LIVELIHOOD = 1
    ECONOMY = 2
    GEOPOLITICS = 4
    RELATIONS = 8


# Match whole words and phrases after removing accents and punctuation.
TOPICS = {
    Topic.LIVELIHOOD: ("民生", (
        "cost of living|housing|rent|eviction|homeless|school[s]?|teachers?|education|"
        "hospitals?|health care|healthcare|public health|vaccin\\w*|disease|food prices|"
        "flood\\w*|wildfires?|drought|earthquake|power outage[s]?|public transport|"
        "jobs|workers|layoffs|strike action|benefits|refugees|migrants|water supply|"
        "custo de vida|moradia|aluguel|enchente[s]?|seca|incendios?|"
        "abastecimento|educacao|escolas?|enem|saude|hospita(?:l|is)|sus|vacina\\w*|"
        "empregos?|trabalhadores|greve|beneficios?|bolsa familia|aposentadoria|"
        "imigrantes|refugiados|tarifa de onibus|transporte publico"
    )),
    Topic.ECONOMY: ("经济", (
        "econom\\w*|inflation|interest rates?|central bank[s]?|federal reserve|"
        "gdp|unemployment|recession|wages?|tariffs?|budget|oil prices?|"
        "stock market|tax(?:es)?|consumer prices|layoffs|cost of living|"
        "inflacao|selic|juros|banco central|pib|dolar|ibovespa|"
        "desemprego|orcamento|salarios?|imposto[s]?|tarifa[s]?|mercado financeiro|"
        "preco[s]? do petroleo"
    )),
    Topic.GEOPOLITICS: ("地缘政治", (
        "wars?|ceasefire|military|missiles?|bombers?|airstrikes?|troops|"
        "peace talks|sanctions?|invasion|blockade|naval|nato|nuclear|pentagon|"
        "armed forces|defen[cs]e secretary|defen[cs]e department|"
        "guerras?|cessar fogo|militares?|misseis|missil|bombardeio[s]?|"
        "tropas|tratado de paz|sancoes|sancao|invasao|bloqueio|otan"
    )),
    Topic.RELATIONS: ("国际关系", (
        "diploma\\w*|bilateral|foreign policy|trade deal[s]?|trade talks|"
        "trade war|trade agreement[s]?|embassy|ambassadors?|summit|"
        "united nations|security council|peace talks|foreign ministers?|state visit[s]?|"
        "consulates?|g7|g20|brics|mercosur|"
        "politica externa|acordo[s]? comercial|acordos comerciais|guerra comercial|"
        "embaixada[s]?|embaixador\\w*|cupula|nacoes unidas|onu|mercosul"
    )),
}
RULES = {
    topic: re.compile(r"\b(?:" + pattern + r")\b")
    for topic, (_, pattern) in TOPICS.items()
}

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MEDIA = {
    "CNN": ("cnn.com",),
    "BBC": ("bbc.com", "bbc.co.uk"),
    "G1": ("g1.globo.com",),
}
BREAKING = re.compile(r"^(?:breaking(?: news)?|urgente|plantão)\s*[:|–—-]", re.IGNORECASE)
LIVE = re.compile(r"^(?:live(?: updates)?|ao vivo)\s*[:|–—-]", re.IGNORECASE)
TRACKING = {"at_campaign", "at_medium", "at_link_origin", "cmp", "ocid", "fbclid", "gclid"}
MAX_FEED_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Feed:
    source: str
    name: str
    url: str
    topic: Topic = Topic(0)
    headlines: bool = False


FEEDS = (
    Feed("CNN", "新闻站点地图", "https://www.cnn.com/sitemap/news.xml"),
    Feed("BBC", "头条", "https://feeds.bbci.co.uk/news/rss.xml", headlines=True),
    Feed("BBC", "国际", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    Feed("BBC", "商业", "https://feeds.bbci.co.uk/news/business/rss.xml", Topic.ECONOMY),
    Feed("BBC", "健康", "https://feeds.bbci.co.uk/news/health/rss.xml", Topic.LIVELIHOOD),
    Feed("G1", "最新", "https://g1.globo.com/rss/g1/"),
    Feed("G1", "国际", "https://g1.globo.com/rss/g1/mundo/"),
    Feed("G1", "经济", "https://g1.globo.com/rss/g1/economia/", Topic.ECONOMY),
    Feed("G1", "健康", "https://g1.globo.com/rss/g1/saude/", Topic.LIVELIHOOD),
    Feed("G1", "教育", "https://g1.globo.com/rss/g1/educacao/", Topic.LIVELIHOOD),
)


@dataclass(frozen=True)
class Article:
    key: str
    source: str
    url: str
    title: str
    day: str
    published: float
    topics: Topic
    breaking: bool
    live: bool
    headline: bool


@dataclass
class FeedResult:
    feed: Feed
    articles: list[Article]
    status: str
    ok: bool


def plain_text(value):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", value or "")).split())


def normalize(value):
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def article_url(value, source):
    try:
        url = urlsplit(value.strip())
        host = url.hostname or ""
        if (url.scheme not in ("https", "http") or url.username or url.password
                or url.port or not any(host == domain or host.endswith("." + domain)
                                       for domain in MEDIA[source])):
            return None
    except ValueError:
        return None
    pairs = [(name, item) for name, item in parse_qsl(url.query, keep_blank_values=True)
             if name.lower() not in TRACKING and not name.lower().startswith("utm_")]
    path = url.path.rstrip("/") or "/"
    link = urlunsplit(("https", host, path, urlencode(pairs), ""))
    canonical_path = re.sub(r"/(?:index\.html|amp)$", "", path) or "/"
    if source == "G1":
        canonical_path = canonical_path.removeprefix("/amp/")
        canonical_path = "/" + canonical_path.lstrip("/")
    key = f"{source}:{canonical_path}?{urlencode(sorted(pairs))}"
    return key, link, path.lower()


def publication_time(value):
    try:
        try:
            stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            stamp = parsedate_to_datetime(value)
    except (ValueError, OverflowError):
        return None
    # RSS "-0000" represents UTC and is returned as a naive datetime.
    return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(SAO_PAULO)


def feed_items(root):
    if root.tag.rsplit("}", 1)[-1] == "urlset":
        for node in root.findall("./{*}url"):
            news = node.find("./{*}news")
            if news is not None:
                yield (node.findtext("{*}loc", ""), news.findtext("{*}title", ""),
                       news.findtext("{*}publication_date", ""), "")
    else:
        for node in root.findall("./{*}channel/{*}item"):
            yield (node.findtext("{*}link", ""), node.findtext("{*}title", ""),
                   node.findtext("{*}pubDate", ""), node.findtext("{*}description", ""))


def classify(feed, path, title, description):
    topics = feed.topic
    if re.search(r"/(?:business|investing|economia)(?:/|$)", path):
        topics |= Topic.ECONOMY
    if re.search(r"/(?:health|saude|educacao)(?:/|$)", path):
        topics |= Topic.LIVELIHOOD
    text = f"{title} {normalize(plain_text(description)[:280])}"
    for topic, rule in RULES.items():
        if rule.search(text):
            topics |= topic
    return topics


def download(feed, context):
    request = Request(feed.url, headers={
        "User-Agent": "DailyNewsDigest/1.0",
        "Accept": "application/rss+xml, application/xml, text/xml",
        "Accept-Encoding": "gzip, identity",
    })
    for attempt in range(2):
        try:
            with urlopen(request, timeout=10, context=context) as response:
                if response.headers.get("Content-Encoding", "").lower() == "gzip":
                    with gzip.GzipFile(fileobj=response) as compressed:
                        body = compressed.read(MAX_FEED_BYTES + 1)
                else:
                    body = response.read(MAX_FEED_BYTES + 1)
            if len(body) > MAX_FEED_BYTES:
                raise ValueError("新闻源文件超出大小限制")
            return ET.fromstring(body)
        except HTTPError as error:
            if attempt or error.code not in (500, 502, 503, 504):
                raise
        except (TimeoutError, URLError, ConnectionError, HTTPException, EOFError):
            if attempt:
                raise


def collect_feed(feed, now, context):
    articles = []
    dates = []
    try:
        for position, (value, title, date_value, description) in enumerate(
            feed_items(download(feed, context))
        ):
            url = article_url(value, feed.source)
            stamp = publication_time(date_value)
            title = plain_text(title)
            if not url or not stamp or not title or stamp > now + timedelta(minutes=5):
                continue
            dates.append(stamp)
            if stamp.date() != now.date():
                continue
            key, link, path = url
            if re.search(r"/(?:sports?|entertainment|showbiz|videos?|gallery|loterias)(?:/|$)", path):
                continue
            normalized_title = normalize(title)
            if re.match(r"^(?:loterias?|resumao diario)\b", normalized_title):
                continue
            topics = classify(feed, path, normalized_title, description)
            if not topics:
                continue
            articles.append(Article(
                key, feed.source, link, title, stamp.date().isoformat(), stamp.timestamp(),
                topics, bool(BREAKING.match(title)),
                bool(LIVE.match(title) or re.search(r"/(?:live-news|live|ao-vivo)/", path)),
                feed.headlines and position < 5,
            ))
        if not dates:
            return FeedResult(feed, [], "没有读到带有效发布时间的新闻", False)
        newest = max(dates)
        if now - newest > timedelta(hours=48):
            return FeedResult(feed, articles, f"新闻源超过 48 小时未更新（{newest:%m-%d %H:%M}）", False)
        return FeedResult(feed, articles, f"正常 · 最新条目 {newest:%m-%d %H:%M}", True)
    except HTTPError as error:
        return FeedResult(feed, [], f"访问失败（HTTP {error.code}）", False)
    except (OSError, HTTPException, EOFError, ET.ParseError, ValueError) as error:
        return FeedResult(feed, [], f"读取失败（{error}）", False)


SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    key TEXT PRIMARY KEY, source TEXT, url TEXT, title TEXT,
    day TEXT, published REAL, topics INTEGER, breaking INTEGER, live INTEGER, headline INTEGER
)
"""
UPSERT = """
INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(key) DO UPDATE SET
    url = excluded.url, title = excluded.title, topics = articles.topics | excluded.topics,
    breaking = max(articles.breaking, excluded.breaking),
    live = max(articles.live, excluded.live), headline = max(articles.headline, excluded.headline)
"""


def article_card(row):
    tags = [label for topic, (label, _) in TOPICS.items() if topic & row["topics"]]
    if row["breaking"]:
        tags.append("快讯")
    if row["live"]:
        tags.append("滚动直播")
    if row["headline"]:
        tags.append("BBC 头条")
    time = datetime.fromtimestamp(row["published"], SAO_PAULO).strftime("%H:%M")
    badges = "".join(f"<span>{html.escape(tag)}</span>" for tag in tags)
    return (f'<li><p class="meta"><strong>{row["source"]}</strong> · {time}</p>'
            f'<a href="{html.escape(row["url"])}">{html.escape(row["title"])}</a>'
            f'<p class="tags">{badges}</p></li>')


def render(day, now, rows, limit, results):
    counts = " · ".join(f"{source} {sum(row['source'] == source for row in rows)} 条"
                        for source in MEDIA)
    cards = "\n".join(article_card(row) for row in rows[:limit])
    if not cards:
        cards = "<li>这一天的存档中没有符合主题的新闻。可查看下方来源状态。</li>"
    status_items = "".join(
        f"<li>{result.feed.source} · {result.feed.name} — {html.escape(result.status)}</li>"
        for result in results
    )
    if results:
        warning = sum(not result.ok for result in results)
        status = f'<details{" open" if warning else ""}><summary>来源状态'
        status += f"（{warning} 个来源入口异常）" if warning else "（全部正常）"
        status += f"</summary><ul>{status_items}</ul></details>"
    else:
        status = "<p>本页由本地存档生成。</p>"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{day} · 每日新闻简报</title>
<style>
* {{box-sizing:border-box}} body {{margin:0;background:#f1f4f8;color:#182437;
font:16px/1.55 system-ui,sans-serif}} main {{max-width:860px;margin:auto;padding:32px 18px}}
header {{background:#162943;color:#fff;padding:24px 28px;border-radius:12px}}
h1 {{margin:4px 0;font-size:clamp(1.6rem,5vw,2.3rem)}} p {{margin:5px 0}}
.sub {{color:#d7e6f5}} ol {{list-style:none;padding:0}} ol li {{background:white;
margin:10px 0;padding:15px 20px;border-radius:9px;border:1px solid #d9e2ed}}
.meta {{color:#475b75;font-size:.84rem}} a {{color:#093b70;font-size:1.08rem;
font-weight:650;text-decoration-thickness:1px;text-underline-offset:3px}}
.tags span {{display:inline-block;color:#234462;background:#e9f0f7;padding:2px 8px;
margin:6px 7px 0 0;border-radius:5px;font-size:.8rem}}
details {{margin-top:18px}} summary {{cursor:pointer}}
footer {{color:#475b75;font-size:.86rem;margin-top:20px}}
</style>
</head>
<body><main>
<header><p class="sub">CNN · BBC NEWS · G1</p><h1>每日新闻简报</h1>
<p>{day} · 圣保罗时间</p><p class="sub">{counts}</p></header>
<p>显示 {min(limit, len(rows))} / {len(rows)} 条 · 生成时间 {now:%Y-%m-%d %H:%M}</p>
<ol>{cards}</ol>
{status}
<footer>快讯、滚动直播、BBC 头条优先，同等优先级按发布时间倒序。
新闻按原始发布日期归档。标题保留原文，点击查看报道。</footer>
</main></body></html>
"""


def write_report(path, content):
    file = NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
    temp = Path(file.name)
    try:
        with file:
            file.write(content)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="汇总 CNN、BBC、G1 当天的重点新闻。")
    parser.add_argument("--date", type=date.fromisoformat, help="从本地存档生成指定日期的简报")
    parser.add_argument("--limit", type=int, default=40, help="简报显示条数，默认 40")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "reports",
                        help="简报和本地新闻存档的目录")
    parser.add_argument("--open", action="store_true", help="生成后用浏览器打开")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit 必须为正整数")

    now = datetime.now(SAO_PAULO)
    day = (args.date or now.date()).isoformat()
    results = []
    if args.date is None:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=certifi.where())
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda feed: collect_feed(feed, now, context), FEEDS))
        for result in results:
            print(f"{result.feed.source} · {result.feed.name}：{result.status}")

    args.output.mkdir(parents=True, exist_ok=True)
    report = args.output / f"{day}.html"
    with closing(sqlite3.connect(args.output / "archive.sqlite3", timeout=30)) as db, db:
        db.row_factory = sqlite3.Row
        db.execute(SCHEMA)
        db.execute("BEGIN IMMEDIATE")
        for result in results:
            db.executemany(UPSERT, (
                (a.key, a.source, a.url, a.title, a.day, a.published,
                 a.topics, a.breaking, a.live, a.headline)
                for a in result.articles
            ))
        rows = db.execute("""
            SELECT * FROM articles WHERE day = ?
            ORDER BY breaking DESC, live DESC, headline DESC, published DESC, key
        """, (day,)).fetchall()
        write_report(report, render(day, now, rows, args.limit, results))
    print(f"已生成简报（{len(rows)} 条）：{report.resolve()}")
    if args.open:
        webbrowser.open(report.resolve().as_uri())
    return int(bool(results) and not any(result.ok for result in results))


if __name__ == "__main__":
    sys.exit(main())
