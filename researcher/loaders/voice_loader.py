"""
顧客の声JSONファイルを読み込み、検証済み dict リストを返す。
"""

import json
from pydantic import BaseModel
from typing import Optional


class _VoiceSnippet(BaseModel):
    text: str
    source: str
    emotion: str
    stage: str                 # awareness / consideration / intent / post_contact
    # 感情分類タグ（Synthesizer が belief_candidates / common_fears / audience_stuck_points に振り分けるキー）
    # 推奨値: pain / fear / belief / desire / cta_barrier / embarrassment
    tags: list[str] = []
    product_family: Optional[str] = None
    date_collected: Optional[str] = None  # YYYY-MM


def load_voice_snippets(path: str) -> list[dict]:
    """JSONファイルから顧客の声を読み込み、検証済み dict リストを返す。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else data.get("voice_snippets", [])
    return [_VoiceSnippet(**item).model_dump() for item in items]
