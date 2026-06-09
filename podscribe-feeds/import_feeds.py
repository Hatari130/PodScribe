#!/usr/bin/env python3
"""
import_feeds.py — 把本订阅库的分类文件合并进 PodScribe 的 subscriptions.json

PodScribe 的 RSS 库只认一个 subscriptions.json（数组，每项 {name, rss_url, ...}）。
这个脚本把 feeds/ 下选中的分类（或全部）按 rss_url + name 去重后合并进去，
不会覆盖你已有的订阅，只追加新的，并补上 added_at 时间戳。

用法:
    # 预览将要导入哪些（不写文件）
    python import_feeds.py --all --dry-run

    # 导入全部分类
    python import_feeds.py --all

    # 只导入 AI 和 科技商业
    python import_feeds.py --category ai tech-business

    # 指定 subscriptions.json 路径（默认是上一级目录）
    python import_feeds.py --all --target ../subscriptions.json

分类名就是 feeds/ 下的文件名去掉 .json：
    ai  tech-business  humanities-society  culture-art  health  overseas-en
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

FEEDS_DIR = Path(__file__).resolve().with_name("feeds")
DEFAULT_TARGET = Path(__file__).resolve().parent.parent / "subscriptions.json"
# subscriptions.json 真正需要的字段；分类文件里的 category/note 等元数据不会写进去
KEEP_FIELDS = ("name", "rss_url", "added_at", "last_synced", "updated_at")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_json_array(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"❌ JSON 解析失败: {path} ({e})")
    if not isinstance(data, list):
        sys.exit(f"❌ 顶层必须是数组: {path}")
    return data


def available_categories() -> list[str]:
    if not FEEDS_DIR.exists():
        return []
    return sorted(p.stem for p in FEEDS_DIR.glob("*.json"))


def collect_entries(categories: list[str]) -> list[dict]:
    entries: list[dict] = []
    for cat in categories:
        path = FEEDS_DIR / f"{cat}.json"
        if not path.exists():
            sys.exit(f"❌ 找不到分类文件: {path}\n可用分类: {', '.join(available_categories())}")
        for item in load_json_array(path):
            if item.get("rss_url") and item.get("name"):
                entries.append(item)
    return entries


def normalize(entry: dict) -> dict:
    out = {k: entry[k] for k in KEEP_FIELDS if k in entry and entry[k] is not None}
    out.setdefault("name", entry.get("name", "").strip())
    out.setdefault("rss_url", entry.get("rss_url", "").strip())
    out.setdefault("added_at", now_iso())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="合并分类订阅到 subscriptions.json")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="导入全部分类")
    group.add_argument("--category", nargs="+", metavar="NAME", help="只导入指定分类")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET,
                        help=f"subscriptions.json 路径（默认 {DEFAULT_TARGET}）")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    args = parser.parse_args()

    cats = available_categories() if args.all else args.category
    if not cats:
        sys.exit(f"❌ feeds/ 下没有分类文件。可用分类: {', '.join(available_categories())}")

    new_entries = collect_entries(cats)
    existing = load_json_array(args.target)

    # 去重键：rss_url 优先，其次 name（都转小写去空白）
    def key_url(e: dict) -> str:
        return (e.get("rss_url") or "").strip().lower()

    def key_name(e: dict) -> str:
        return (e.get("name") or "").strip().lower()

    seen_url = {key_url(e) for e in existing if key_url(e)}
    seen_name = {key_name(e) for e in existing if key_name(e)}

    to_add: list[dict] = []
    skipped = 0
    for e in new_entries:
        if key_url(e) in seen_url or key_name(e) in seen_name:
            skipped += 1
            continue
        to_add.append(normalize(e))
        seen_url.add(key_url(e))
        seen_name.add(key_name(e))

    print(f"分类: {', '.join(cats)}")
    print(f"候选 {len(new_entries)} 个，已存在跳过 {skipped} 个，新增 {len(to_add)} 个。")
    for e in to_add:
        print(f"  + {e['name']}  ->  {e['rss_url']}")

    if args.dry_run:
        print("\n(--dry-run，未写入)")
        return 0
    if not to_add:
        print("\n没有需要新增的订阅。")
        return 0

    merged = existing + to_add
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n✅ 已写入 {args.target}（共 {len(merged)} 个订阅）。")
    print("接下来可以让 PodScribe 同步，例如：")
    for e in to_add[:3]:
        print(f'  python transcribe.py rss sync "{e["name"]}" --limit 50')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
