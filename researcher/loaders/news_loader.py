"""
市場文脈ニュース記事JSONファイルを読み込み、検証済み dict リストを返す。

用途: エルメス値上げ / 相場動向 / プレミア品流通 / インバウンド需要 等の
      市場文脈を Strategist に提供する。why_now や benefit_bridge の角度選択に使う。
"""

import json
from pydantic import BaseModel
from typing import Optional


class _NewsArticle(BaseModel):
    title: str
    summary: str                        # 要点（手動記入、2〜3行）
    url: Optional[str] = None
    source_name: str                    # メディア名（"WWD JAPAN" / "Business of Fashion" 等）
    published_at: Optional[str] = None  # YYYY-MM-DD
    relevance_tags: list[str] = []      # 値上げ / 相場 / プレミア / インバウンド 等
    market_implication: Optional[str] = None  # TBT動画に使える含意（手動記入）


def load_news_articles(path: str) -> list[dict]:
    """JSONファイルから市場文脈ニュースを読み込み、検証済み dict リストを返す。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else data.get("news_articles", [])
    return [_NewsArticle(**item).model_dump() for item in items]
