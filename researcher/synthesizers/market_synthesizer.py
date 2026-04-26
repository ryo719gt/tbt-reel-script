"""
MarketSynthesizer: MarketContext フィールドの集約・生成。

責務:
    - price_signals / competitor_patterns / news_articles を MarketContext に注入する
    - voice_snippets の pain / cta_barrier / embarrassment タグから
      audience_stuck_points を MarketContext に集約する
      （NOTE: audience_stuck_points は MarketContext の責務。PersonaSynthesizer では生成しない）
    - テキストフィールド（pricing_relevance / competitor_gap 等）は
      Phase1: 手動記入済み値をパススルー
      Phase2（将来）: mode="claude" で Claude API による自動生成に差し替え可能

dict ベースで動作し、Pydantic モデルはインポートしない。
モデル構築は呼び出し元（ResearcherAgent）で行う。
"""


def synthesize_market_context(
    base_dict: dict | None,
    price_signals: list[dict],
    competitor_patterns: list[dict],
    voice_snippets: list[dict] | None = None,
    news_articles: list[dict] | None = None,
    *,
    mode: str = "passthrough",  # 将来: "claude" に差し替え可能
) -> dict:
    """
    MarketContext dict を構築して返す。

    Args:
        base_dict: 既存の MarketContext dict（research_memo 等から）。None 可。
        price_signals: Loader が返した PriceSignal dict リスト。
        competitor_patterns: Loader が返した CompetitorPattern dict リスト。
        voice_snippets: Loader が返した VoiceSnippet dict リスト（audience_stuck_points に使う）。
        news_articles: Loader が返した NewsArticle dict リスト。
        mode: "passthrough"（Phase1）。将来は "claude" で AI 要約に切り替え。

    Returns:
        更新済み MarketContext dict。
    """
    data = dict(base_dict) if base_dict else {}

    # 構造化フィールドは常に上書き（Loader 取得値が正）
    data["price_signals"] = price_signals
    data["competitor_patterns"] = competitor_patterns

    if news_articles is not None:
        data["news_articles"] = news_articles

    if mode == "passthrough":
        _aggregate_passthrough(data, voice_snippets)
    # 将来: elif mode == "claude": _aggregate_with_claude(data, ...)

    return data


def synthesize_persona_insights(
    base_dict: dict | None,
    voice_snippets: list[dict],
) -> dict:
    """
    後方互換用: 旧 ResearcherAgent が呼んでいた関数。
    新規コードは persona_synthesizer.synthesize_from_voice_snippets() を使うこと。
    """
    data = dict(base_dict) if base_dict else {}
    data["voice_snippets"] = voice_snippets
    return data


def _aggregate_passthrough(data: dict, voice_snippets: list[dict] | None) -> None:
    """
    タグベースで機械的に集約する（Claude 不要）。
    既存フィールドがある場合は上書きしない（手動記入優先）。
    """
    if not voice_snippets:
        return

    # pain / cta_barrier / embarrassment タグ → audience_stuck_points（MarketContextの責務）
    if not data.get("audience_stuck_points"):
        stuck_tags = {"pain", "cta_barrier", "embarrassment"}
        stuck = [
            vs["text"] for vs in voice_snippets
            if any(t in vs.get("tags", []) for t in stuck_tags)
        ]
        if stuck:
            data["audience_stuck_points"] = stuck
