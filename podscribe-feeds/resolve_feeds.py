#!/usr/bin/env python3
"""
resolve_feeds.py — 用 Apple/iTunes 公开接口解析、补全、升级、校验播客 RSS

为什么需要它:
  - 按名字添加新节目，自动拿到官方 RSS（不用手动找）。
  - 把分类文件里走 RSSHub 代理（source=xiaoyuzhou-rsshub）的源，一键升级成
    创作者提交给 Apple 的官方源（通常就是 feed.xyzfm.space / 喜马拉雅 / 各家托管的原始地址），
    更稳定、不依赖第三方代理。
  - 定期校验所有 rss_url 是否还活着。

依赖: 仅标准库。需要能访问 itunes.apple.com（中国大陆直连通常可用）。

用法:
  # 按名字搜索并追加到某个分类（中文节目建议 --country cn）
  python resolve_feeds.py add "Latent Space" --category overseas-en --country us
  python resolve_feeds.py add "声动早咖啡" --category tech-business --country cn

  # 把一个分类里所有 RSSHub 代理源升级为官方源（按 name 在 Apple 上匹配）
  python resolve_feeds.py upgrade feeds/ai.json --country cn
  # 升级所有分类
  python resolve_feeds.py upgrade feeds/ --country cn

  # 校验链接是否存活
  python resolve_feeds.py validate feeds/
  python resolve_feeds.py validate ../subscriptions.json

  # 只查询不写入，看看 Apple 上能匹配到什么
  python resolve_feeds.py search "Dwarkesh" --country us
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ITUNES_SEARCH = "https://itunes.apple.com/search"
ITUNES_LOOKUP = "https://itunes.apple.com/lookup"
UA = "Mozilla/5.0 (PodScribe-feeds resolver)"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def http_json(url: str, params: dict) -> dict:
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", errors="ignore"))


def itunes_search(term: str, country: str, limit: int = 5) -> list[dict]:
    data = http_json(ITUNES_SEARCH, {
        "term": term, "media": "podcast", "entity": "podcast",
        "limit": limit, "country": country,
    })
    return data.get("results", [])


def best_match(term: str, results: list[dict]) -> dict | None:
    if not results:
        return None
    t = term.strip().lower()
    for r in results:
        name = (r.get("collectionName") or r.get("trackName") or "").strip().lower()
        if name == t:
            return r
    # 没有完全相等就返回第一个（iTunes 按相关性排序）
    return results[0]


def load_array(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"❌ 文件不存在: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"❌ JSON 解析失败: {path} ({e})")
    if not isinstance(data, list):
        sys.exit(f"❌ 顶层必须是数组: {path}")
    return data


def write_array(path: Path, data: list[dict]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def feeds_dir() -> Path:
    return Path(__file__).resolve().with_name("feeds")


def category_path(cat: str) -> Path:
    cat = cat[:-5] if cat.endswith(".json") else cat
    return feeds_dir() / f"{cat}.json"


def iter_json_files(target: Path) -> list[Path]:
    if target.is_dir():
        return sorted(target.glob("*.json"))
    return [target]


# --------------------------- commands ---------------------------

def cmd_search(args) -> int:
    results = itunes_search(args.name, args.country, limit=args.limit)
    if not results:
        print("没有匹配结果。试试换关键词或 --country。")
        return 1
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r.get('collectionName')}  —  {r.get('artistName')}")
        print(f"     feedUrl : {r.get('feedUrl')}")
        print(f"     genre   : {r.get('primaryGenreName')}  | tracks: {r.get('trackCount')}")
    return 0


# bootstrap 内置清单：分领域的高质量中英文节目（名字, 区号）。
# 跑 `python resolve_feeds.py bootstrap` 会通过 iTunes 把这些节目的官方 RSS 拉全，
# 写进对应分类文件（已存在的按 name/url 跳过）。英文用 us，中文用 cn。
BOOTSTRAP: dict[str, list[tuple[str, str]]] = {
    "ai": [
        # 旗舰长访谈（常请前沿实验室研究者：Karpathy / Ilya / Dario / Amanda Askell 等）
        ("Dwarkesh Podcast", "us"),
        ("Lex Fridman Podcast", "us"),
        ("Machine Learning Street Talk", "us"),
        ("The Cognitive Revolution", "us"),
        # AI 工程 / 产品 / 风投
        ("Latent Space: The AI Engineer Podcast", "us"),
        ("No Priors: AI, Machine Learning, Tech", "us"),
        ("a16z Podcast", "us"),
        ("AI + a16z", "us"),
        ("Training Data", "us"),
        ("The TWIML AI Podcast", "us"),
        ("Practical AI", "us"),
        ("Last Week in AI", "us"),
        ("Eye on AI", "us"),
        # AI 安全 / 对齐 / 有效利他（Amanda Askell 这一圈研究者常出没）
        ("80,000 Hours Podcast", "us"),
        ("AXRP - the AI X-risk Research Podcast", "us"),
        ("The Inside View", "us"),
        ("Future of Life Institute Podcast", "us"),
        # 实验室官方 / 政策 / 主流媒体
        ("Google DeepMind: The Podcast", "us"),
        ("Anthropic", "us"),
        ("Scaling Laws", "us"),
        ("Hard Fork", "us"),
        ("Pioneers of AI", "us"),
    ],
    "tech-business": [
        ("The Tim Ferriss Show", "us"),
        ("Invest Like the Best", "us"),
        ("Lenny's Podcast", "us"),
        ("Masters of Scale", "us"),
        ("How I Built This with Guy Raz", "us"),
        ("In Good Company with Nicolai Tangen", "us"),
        ("Acquired", "us"),
        ("My First Million", "us"),
        ("声动早咖啡", "cn"),
        ("商业就是这样", "cn"),
        ("面基", "cn"),
        ("详谈", "cn"),
    ],
    "health": [
        ("The Peter Attia Drive", "us"),
        ("FoundMyFitness", "us"),
        ("Feel Better, Live More", "us"),
        ("ZOE Science & Nutrition", "us"),
        ("The Rich Roll Podcast", "us"),
        ("The Doctor's Farmacy with Mark Hyman", "us"),
        ("Ten Percent Happier with Dan Harris", "us"),
        ("Huberman Lab", "us"),
    ],
    "humanities-society": [
        ("Hidden Brain", "us"),
        ("The Ezra Klein Show", "us"),
        ("Freakonomics Radio", "us"),
        ("Throughline", "us"),
        ("Conversations with Tyler", "us"),
        ("Philosophize This!", "us"),
        ("On Being with Krista Tippett", "us"),
        ("随机波动 StochasticVolatility", "cn"),
        ("故事FM", "cn"),
        ("忽左忽右", "cn"),
        ("声东击西", "cn"),
        ("大内密谈", "cn"),
    ],
    "culture-art": [
        ("99% Invisible", "us"),
        ("Song Exploder", "us"),
        ("Fresh Air", "us"),
        ("The Great Women Artists", "us"),
        ("Articles of Interest", "us"),
        ("不在场", "cn"),
        ("文化有限", "cn"),
        ("螺丝在拧紧", "cn"),
        ("看理想圆桌", "cn"),
        ("一席", "cn"),
    ],
}


def _add_show(name: str, country: str, path: Path, *, dry_run: bool = False) -> str:
    """解析一个节目并追加到分类文件。返回状态: added / exists / notfound。"""
    try:
        results = itunes_search(name, country, limit=5)
    except Exception as ex:
        print(f"  ! 查询失败 {name}: {ex}")
        return "notfound"
    match = best_match(name, results)
    if not match or not match.get("feedUrl"):
        print(f"  ✗ 没找到官方 RSS: {name}")
        return "notfound"
    feed = match["feedUrl"].strip()
    arr = load_array(path) if path.exists() else []
    nm = (match.get("collectionName") or name).strip().lower()
    if any((e.get("rss_url") or "").strip().lower() == feed.lower()
           or (e.get("name") or "").strip().lower() == nm for e in arr):
        print(f"  · 已存在跳过: {match.get('collectionName')}")
        return "exists"
    entry = {
        "name": match.get("collectionName") or name,
        "rss_url": feed,
        "added_at": now_iso(),
        "category": path.stem,
        "source": "itunes",
    }
    print(f"  + {entry['name']}  ->  {entry['rss_url']}")
    if not dry_run:
        arr.append(entry)
        write_array(path, arr)
    return "added"


def cmd_add(args) -> int:
    status = _add_show(args.name, args.country, category_path(args.category))
    return 0 if status in {"added", "exists"} else 1


def cmd_bootstrap(args) -> int:
    cats = [args.only] if args.only else list(BOOTSTRAP.keys())
    added = exists = missing = 0
    for cat in cats:
        shows = BOOTSTRAP.get(cat[:-5] if cat.endswith(".json") else cat)
        if not shows:
            print(f"⚠️ bootstrap 里没有分类 {cat}，跳过")
            continue
        path = category_path(cat)
        print(f"\n[{path.name}]")
        for name, country in shows:
            status = _add_show(name, country, path, dry_run=args.dry_run)
            added += status == "added"
            exists += status == "exists"
            missing += status == "notfound"
            time.sleep(0.4)  # 别把 iTunes 接口打太快
    suffix = "（--dry-run，未写入）" if args.dry_run else ""
    print(f"\n完成: 新增 {added}，已存在 {exists}，未找到 {missing}{suffix}。")
    if not args.dry_run and added:
        print("接着把它们并进 PodScribe: python import_feeds.py --all")
    return 0


def cmd_upgrade(args) -> int:
    files = iter_json_files(args.path)
    total_up = 0
    for path in files:
        arr = load_array(path)
        changed = False
        for e in arr:
            # 只升级代理源 / 明确想替换的源
            if e.get("source") not in {"xiaoyuzhou-rsshub", "ximalaya", "typlog"}:
                continue
            name = (e.get("name") or "").strip()
            if not name:
                continue
            try:
                results = itunes_search(name, args.country, limit=5)
            except Exception as ex:
                print(f"  ! 查询失败 {name}: {ex}")
                continue
            match = best_match(name, results)
            new_feed = (match or {}).get("feedUrl")
            if new_feed and new_feed.strip().lower() != (e.get("rss_url") or "").strip().lower():
                print(f"  ↑ {name}\n      旧: {e.get('rss_url')}\n      新: {new_feed}")
                if not args.dry_run:
                    e["rss_url"] = new_feed.strip()
                    e["source"] = "itunes"
                    e["updated_at"] = now_iso()
                changed = True
                total_up += 1
            time.sleep(0.5)  # 温柔一点，别把接口打挂
        if changed and not args.dry_run:
            write_array(path, arr)
            print(f"  ✅ 已更新 {path.name}")
    suffix = "（--dry-run，未写入）" if args.dry_run else ""
    print(f"\n共可升级 {total_up} 个源{suffix}。")
    return 0


def cmd_validate(args) -> int:
    files = iter_json_files(args.path)
    dead: list[tuple[str, str, str]] = []
    checked = 0
    for path in files:
        arr = load_array(path)
        for e in arr:
            url = (e.get("rss_url") or "").strip()
            if not url:
                continue
            checked += 1
            ok, info = check_feed(url)
            mark = "✓" if ok else "✗"
            print(f"  {mark} [{path.name}] {e.get('name')}  {info}")
            if not ok:
                dead.append((path.name, e.get("name", ""), url))
    print(f"\n检查 {checked} 个，疑似失效 {len(dead)} 个。")
    if dead:
        print("失效列表（可用 add 重新解析，或手动更新）:")
        for fname, name, url in dead:
            print(f"  - [{fname}] {name}: {url}")
    return 0


def check_feed(url: str) -> tuple[bool, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            status = getattr(resp, "status", 200)
            head = resp.read(2048).decode("utf-8", errors="ignore").lower()
            if 200 <= status < 300 and ("<rss" in head or "<feed" in head or "<?xml" in head):
                return True, f"HTTP {status}"
            return False, f"HTTP {status}，内容不像 RSS"
    except Exception as ex:
        return False, str(ex)


def main() -> int:
    p = argparse.ArgumentParser(description="用 iTunes 接口解析/升级/校验播客 RSS")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="只搜索，打印候选与 feedUrl")
    s.add_argument("name")
    s.add_argument("--country", default="us")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_search)

    a = sub.add_parser("add", help="按名字解析并追加到某分类")
    a.add_argument("name")
    a.add_argument("--category", required=True, help="ai / tech-business / health ...")
    a.add_argument("--country", default="us")
    a.set_defaults(func=cmd_add)

    u = sub.add_parser("upgrade", help="把代理源升级为 Apple 官方源")
    u.add_argument("path", type=Path, help="某个 .json 或 feeds/ 目录")
    u.add_argument("--country", default="cn")
    u.add_argument("--dry-run", action="store_true")
    u.set_defaults(func=cmd_upgrade)

    v = sub.add_parser("validate", help="校验 rss_url 是否存活")
    v.add_argument("path", type=Path, help="某个 .json 或 feeds/ 目录")
    v.set_defaults(func=cmd_validate)

    b = sub.add_parser("bootstrap", help="一键拉全内置的高质量中英文清单（官方源）")
    b.add_argument("--only", metavar="CATEGORY", help="只处理某个分类，如 ai / health")
    b.add_argument("--dry-run", action="store_true")
    b.set_defaults(func=cmd_bootstrap)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
