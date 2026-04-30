"""
相場シグナルJSONファイルを読み込み、検証済み dict リストを返す。

Phase1: source は Union[str, PriceSource] で後方互換を維持。
Phase2（将来）: source を PriceSource に統一し、この Union を解消する予定。
"""

import json
from pydantic import BaseModel, field_validator
from typing import Optional, Union


class _PriceSource(BaseModel):
    source_type: str       # official / retailer_ec / auction / news / internal / unknown
    name: str
    url: Optional[str] = None
    reliability: str = "medium"   # high / medium / low
    observed_at: Optional[str] = None  # YYYY-MM-DD


class _PriceSignal(BaseModel):
    product_family: str
    condition: str
    accessories: str
    price_range_min: int
    price_range_max: int
    market_trend: str
    # Phase1: str（旧フォーマット）も受け付ける。Phase2 で PriceSource に統一予定。
    source: Union[str, _PriceSource]
    note: Optional[str] = None

    @field_validator("source", mode="before")
    @classmethod
    def coerce_source(cls, v):
        """str で渡された旧フォーマットを PriceSource に昇格する。"""
        if isinstance(v, str):
            return _PriceSource(
                source_type="unknown",
                name=v,
                reliability="medium",
            )
        return v


def load_price_signals(path: str) -> list[dict]:
    """JSONファイルから相場シグナルを読み込み、検証済み dict リストを返す。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    items = data if isinstance(data, list) else data.get("price_signals", [])
    return [_PriceSignal(**item).model_dump() for item in items]
