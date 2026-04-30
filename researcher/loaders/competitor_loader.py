"""
競合パターンJSONファイルを読み込み、検証済み dict リストを返す。
"""

import json
from pydantic import BaseModel
from typing import Optional


class _CompetitorPattern(BaseModel):
    competitor_name: Optional[str] = None
    platform: Optional[str] = None       # instagram / youtube / tiktok / x / website
    hook_pattern: str                    # 訴求パターンの分類ラベル
    hook_example: Optional[str] = None  # 実際のフックテキスト例（コピーのまま）
    angle: Optional[str] = None          # 数字訴求 / 権威訴求 / 緊急性訴求 等
    cta_style: Optional[str] = None      # 電話 / LINE / 来店 等
    weakness: str
    differentiator: str
    url: Optional[str] = None
    note: Optional[str] = None
    observed_at: Optional[str] = None    # YYYY-MM


def load_competitor_patterns(path: str) -> list[dict]:
    """JSONファイルから競合パターンを読み込み、検証済み dict リストを返す。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else data.get("competitor_patterns", [])
    return [_CompetitorPattern(**item).model_dump() for item in items]
