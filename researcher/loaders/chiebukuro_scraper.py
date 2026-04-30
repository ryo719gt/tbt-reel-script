#!/usr/bin/env python3
"""
Yahoo!知恵袋スクレイパー
エルメス買取関連の質問文・回答文から生フレーズを収集し、
researcher/data/voice_snippets.json に追記する。

使い方:
    python3 chiebukuro_scraper.py
    python3 chiebukuro_scraper.py --dry-run     # voice_snippets.json に書かず標準出力だけ
    python3 chiebukuro_scraper.py --max 100     # 取得上限を変更（デフォルト50）
"""

import json
import time
import argparse
import pathlib
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ── 設定 ──────────────────────────────────────────────────────────────────────

SEARCH_QUERIES = [
    "エルメス 売りたい",
    "エルメス 買取 怖い",
    "バーキン 査定",
    "ケリー 買取",
    "ピコタン 売る",
    "エルメス 相場 知りたい",
    "エルメス 買取店",
    "バーキン 売る タイミング",
]

OUTPUT_PATH = pathlib.Path(__file__).parent.parent / "data" / "voice_snippets.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

PRODUCT_KEYWORDS = {
    "バーキン": "バーキン",
    "ケリー": "ケリー",
    "ピコタン": "ピコタン",
    "エルメス": "エルメス全般",
}


# ── スクレイピング ────────────────────────────────────────────────────────────

def search_chiebukuro(query: str, max_results: int = 10) -> list[dict]:
    """知恵袋の検索結果ページから質問URLを収集する。"""
    url = "https://chiebukuro.yahoo.co.jp/search"
    params = {"p": query, "flg": 1}

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [WARN] 検索失敗 ({query}): {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    # 質問リストのリンクを探す
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "question_detail" not in href:
            continue
        # 絶対URLに変換
        if href.startswith("/"):
            href = "https://chiebukuro.yahoo.co.jp" + href
        if href not in [r["url"] for r in results]:
            results.append({"url": href})
        if len(results) >= max_results:
            break

    return results


def fetch_question_texts(url: str) -> list[str]:
    """質問詳細ページから質問文・回答文を取得する。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        print(f"  [WARN] 取得失敗 ({url}): {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    texts = []

    RELEVANT_KEYWORDS = ["エルメス", "バーキン", "ケリー", "ピコタン", "査定", "買取", "売り", "売る", "相場"]

    # 買取・査定に関連するキーワードが必須（より絞り込む）
    BUYBACK_KEYWORDS = ["査定", "買取", "売り", "売る", "売れ", "手放", "相場", "高く売"]

    # 買取・査定と無関係なノイズを除外するキーワード
    NOISE_KEYWORDS = [
        "欲しい", "購入", "買いたい", "買おう", "在庫", "予約", "どこで買", "プレゼント",
        "おすすめ", "財布", "リュック", "通学", "高校", "大学生", "男性", "彼氏",
        "香水", "スカーフ", "アクセサリー", "食器", "洋服",
        "直営店", "店舗で", "フリーで買", "エルパト", "担当者", "顧客様",
        "品薄", "入手", "手に入", "買えない", "買えた", "使い勝手", "使いやすい",
    ]

    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) < 15 or len(text) > 300:
            continue
        if not any(kw in text for kw in RELEVANT_KEYWORDS):
            continue
        if not any(kw in text for kw in BUYBACK_KEYWORDS):
            continue
        if any(kw in text for kw in NOISE_KEYWORDS):
            continue
        texts.append(text)

    return texts


# ── フレーズ変換 ──────────────────────────────────────────────────────────────

def detect_product_family(text: str) -> str | None:
    for kw, family in PRODUCT_KEYWORDS.items():
        if kw in text:
            return family
    return None


def detect_stage(text: str) -> str:
    if any(w in text for w in ["売った", "行った", "してもらった", "だった"]):
        return "post_contact"
    if any(w in text for w in ["売ろう", "持っていこう", "予約した", "行こう"]):
        return "intent"
    if any(w in text for w in ["どこ", "どうすれば", "どうしたら", "どちら", "比べ"]):
        return "consideration"
    return "awareness"


def detect_tags(text: str) -> list[str]:
    tags = []
    if any(w in text for w in ["怖い", "不安", "心配", "ショック", "怖くて"]):
        tags.append("fear")
    if any(w in text for w in ["恥ずかしい", "気まずい", "言いにくい", "バレ", "こっそり"]):
        tags.append("embarrassment")
    if any(w in text for w in ["思ってた", "と思っていた", "だと思ってた", "はず"]):
        tags.append("belief")
    if any(w in text for w in ["後回し", "ずっと", "眠ってる", "放置", "まだ"]):
        tags.append("pain")
    if any(w in text for w in ["知りたい", "気になる", "いくら", "どのくらい", "高く売"]):
        tags.append("desire")
    if any(w in text for w in ["行きにくい", "断りにくい", "ハードル", "躊躇", "踏み出せ"]):
        tags.append("cta_barrier")
    if not tags:
        tags.append("pain")
    return tags


def text_to_snippet(text: str) -> dict:
    return {
        "text": text,
        "source": "Yahoo知恵袋",
        "emotion": "",           # 空欄（生フレーズなので感情ラベルは付けない）
        "stage": detect_stage(text),
        "tags": detect_tags(text),
        "product_family": detect_product_family(text),
        "date_collected": datetime.now().strftime("%Y-%m"),
    }


# ── 重複チェック ──────────────────────────────────────────────────────────────

def load_existing_texts(path: pathlib.Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    snippets = data.get("voice_snippets", [])
    return {s["text"] for s in snippets}


def append_to_voice_snippets(path: pathlib.Path, new_snippets: list[dict]) -> int:
    if path.exists():
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"_note": "顧客・SNS・LINEから収集した生の声。", "voice_snippets": []}

    data["voice_snippets"].extend(new_snippets)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return len(new_snippets)


# ── メイン ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="ファイルに書かず標準出力のみ")
    parser.add_argument("--max", type=int, default=50, help="収集上限（デフォルト50件）")
    args = parser.parse_args()

    existing_texts = load_existing_texts(OUTPUT_PATH)
    collected: list[dict] = []

    per_query = max(1, args.max // len(SEARCH_QUERIES))

    for query in SEARCH_QUERIES:
        print(f"\n[検索] {query}")
        results = search_chiebukuro(query, max_results=per_query)
        print(f"  {len(results)}件の質問URL取得")

        for r in results:
            texts = fetch_question_texts(r["url"])
            for text in texts:
                # 短すぎ・長すぎ・重複は除外
                if len(text) < 15 or len(text) > 200:
                    continue
                if text in existing_texts:
                    continue
                snippet = text_to_snippet(text)
                collected.append(snippet)
                existing_texts.add(text)

            time.sleep(1.0)  # サーバー負荷軽減

        if len(collected) >= args.max:
            break

    collected = collected[: args.max]
    print(f"\n収集件数: {len(collected)}件")

    if args.dry_run:
        print(json.dumps(collected, ensure_ascii=False, indent=2))
    else:
        added = append_to_voice_snippets(OUTPUT_PATH, collected)
        print(f"voice_snippets.json に {added}件追記しました → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
