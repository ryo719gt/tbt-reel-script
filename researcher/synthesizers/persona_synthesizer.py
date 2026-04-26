"""
PersonaSynthesizer: voice_snippets → PersonaInsights フィールドの集約。

責務:
    voice_snippets の tags から PersonaInsights の各フィールドを機械的に集約する。
    意味づけ・要約は行わない（Phase2 では Claude API に差し替え可能）。

NOTE: audience_stuck_points は MarketContext の責務として設計されているため、
      このSynthesizerでは生成しない。
      voice_snippets の pain / cta_barrier / embarrassment タグは
      market_synthesizer.synthesize_market_context() が MarketContext に集約する。
"""


def synthesize_from_voice_snippets(
    base_dict: dict | None,
    voice_snippets: list[dict],
    *,
    mode: str = "passthrough",  # 将来: "claude" に差し替え可能
) -> dict:
    """
    voice_snippets の tags から PersonaInsights フィールドを集約して返す。

    - 既存フィールド（手動記入済み）は上書きしない。
    - voice_snippets は常にセット（追記）する。

    Args:
        base_dict: 既存の PersonaInsights dict（research_memo 等から）。None 可。
        voice_snippets: Loader が返した VoiceSnippet dict リスト。
        mode: "passthrough"（Phase1）。将来は "claude" で AI 要約に切り替え。

    Returns:
        更新済み PersonaInsights dict。
    """
    data = dict(base_dict) if base_dict else {}

    if mode == "passthrough":
        _aggregate_passthrough(data, voice_snippets)
    # 将来: elif mode == "claude": _aggregate_with_claude(data, voice_snippets)

    # voice_snippets は常に上書き（Loader 取得値が正）
    data["voice_snippets"] = voice_snippets

    return data


def _aggregate_passthrough(data: dict, voice_snippets: list[dict]) -> None:
    """
    タグベースで機械的に集約する（Claude 不要）。
    既存フィールドがある場合は上書きしない（手動記入優先）。
    """
    # belief タグ → belief_candidates（行動を止める思い込み）
    if not data.get("belief_candidates"):
        beliefs = [
            vs["text"] for vs in voice_snippets
            if "belief" in vs.get("tags", [])
        ]
        if beliefs:
            data["belief_candidates"] = beliefs

    # fear / pain タグ → common_fears（よくある恐れ・抵抗感）
    if not data.get("common_fears"):
        fears = [
            vs["text"] for vs in voice_snippets
            if any(t in vs.get("tags", []) for t in ["fear", "pain"])
        ]
        if fears:
            data["common_fears"] = fears

    # desire タグ → raw_audience_phrases（視聴者が実際に欲しいもの）
    if not data.get("raw_audience_phrases"):
        desires = [
            vs["text"] for vs in voice_snippets
            if "desire" in vs.get("tags", [])
        ]
        if desires:
            data["raw_audience_phrases"] = desires
