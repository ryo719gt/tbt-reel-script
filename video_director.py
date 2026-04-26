#!/usr/bin/env python3.11
"""
TBT リール動画 自律ディレクターエージェント v3.0
ナレーション主導型構成設計エージェント

処理フロー:
    Gemini（動画観察）→ Claude（ナレーション構成設計・キュー生成・Premiereガイド）
    → AivisSpeech（音声生成）→ Premiere Pro（映像を音声に当てる）

使い方:
    # 1本
    python3.11 video_director.py <動画ファイルパス>

    # 複数本（同一商品の複数アングル素材）→ 1本分のディレクションを出力
    python3.11 video_director.py <動画1> <動画2> <動画3> --notes "箱付き"
"""

import sys
import os
import json
import time
import argparse
import pathlib
import uuid
from typing import Optional, Union
from datetime import datetime

from google import genai
from google.genai import types as genai_types
import anthropic
from pydantic import BaseModel, field_validator, model_validator

# ── .env 自動読み込み（sandbox/.env → スクリプトと同階層の .env の順で探す）────
def _load_dotenv() -> None:
    candidates = [
        pathlib.Path(__file__).parent / ".env",
        pathlib.Path(__file__).parent.parent.parent / ".env",  # sandbox/.env
    ]
    for env_path in candidates:
        if env_path.exists():
            with open(env_path, encoding="utf-8") as _f:
                for _line in _f:
                    _line = _line.strip()
                    if _line and not _line.startswith("#") and "=" in _line:
                        _k, _, _v = _line.partition("=")
                        os.environ.setdefault(_k.strip(), _v.strip())
            break

_load_dotenv()

# ── 設定 ──────────────────────────────────────────────────────────────────────
GEMINI_API_KEY  = "AIzaSyAIMy54kJBIc5agcXvspGG4BdqFSUX6TVY"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_MODEL    = "gemini-2.5-flash"
CLAUDE_MODEL    = "claude-sonnet-4-6"
OUTPUT_BASE_DIR = pathlib.Path(__file__).parent / "output"

FORBIDDEN_EXPRESSIONS = [
    "絶対高く売れる", "本物確定", "今すぐ売らないと損",
    "100%", "必ず高く", "保証します", "確実に",
    "絶対に", "間違いなく本物",
]


# ── Pydantic モデル ────────────────────────────────────────────────────────────

class TimestampEvidence(BaseModel):
    timecode: str  # MM:SS
    description: str

class Observation(BaseModel):
    run_id: str
    source_video: str
    brand: str
    product_category: str
    product_family_guess: str
    product_family_confidence: float  # 0.0〜1.0
    visible_materials: list[str]
    visible_color: str
    visible_hardware: str
    visible_damage: list[str]
    damage_confidence: float
    accessories_detected: list[str]
    accessories_missing_or_unconfirmed: list[str]
    angles_present: list[str]
    angles_missing: list[str]
    text_detected_on_screen: list[str]
    speech_summary: str
    notable_timestamps: list[TimestampEvidence]
    uncertainty_flags: list[str]
    evidence_notes: str
    overall_visual_quality: str  # good / fair / poor
    needs_human_review: bool

    @model_validator(mode="after")
    def check_review_triggers(self):
        # 致命的な問題だけレビュー判定（軽微な不確実フラグは通過させる）
        triggers = []
        if self.product_family_confidence < 0.60:
            triggers.append(f"product_family_confidence={self.product_family_confidence}")
        if self.damage_confidence < 0.50:
            triggers.append(f"damage_confidence={self.damage_confidence}")
        if self.overall_visual_quality == "poor":
            triggers.append("overall_visual_quality=poor")
        # uncertainty_flagsは複数ある場合のみブロック（1件は許容）
        if len(self.uncertainty_flags) >= 3:
            triggers.append(f"uncertainty_flags多数={self.uncertainty_flags}")
        if triggers:
            self.needs_human_review = True
        return self

class HookCandidate(BaseModel):
    hook_type: str  # information_gap / loss_aversion / unexpected
    text: str
    market_fit: int
    evidence_strength: int
    pain_intensity: int
    novelty: int
    cta_connectivity: int
    brand_fit: int

    @property
    def total_score(self) -> float:
        return (
            0.25 * self.market_fit +
            0.25 * self.evidence_strength +
            0.20 * self.pain_intensity +
            0.10 * self.novelty +
            0.10 * self.cta_connectivity +
            0.10 * self.brand_fit
        )

    def is_eligible(self) -> bool:
        return self.evidence_strength >= 3 and self.brand_fit >= 3 and self.cta_connectivity >= 2

class EditSegment(BaseModel):
    start_sec: int
    end_sec: int
    segment_goal: str
    visual_instruction: str
    subtitle_text: str
    voiceover_text: str
    proof_reference: str
    transition_instruction: str

    @field_validator("start_sec", "end_sec")
    @classmethod
    def non_negative(cls, v):
        assert v >= 0, "秒数は0以上"
        return v

    @model_validator(mode="after")
    def start_before_end(self):
        assert self.start_sec < self.end_sec, "start_sec < end_sec"
        assert self.subtitle_text.strip(), "テロップ空文字禁止"
        return self

class EditPlan(BaseModel):
    target_duration_sec: int = 40
    segments: list[EditSegment]
    ending_cta: str
    music_direction: str
    caption_summary: str

    @model_validator(mode="after")
    def validate_total_duration(self):
        if self.segments:
            total = self.segments[-1].end_sec
            assert total <= 42, f"総尺超過: {total}秒"
        assert self.ending_cta.strip(), "CTA必須"
        return self

class StrategyPlan(BaseModel):
    target_persona: str
    pain_hypothesis: str
    hook_candidates: list[HookCandidate]
    selected_hook: str
    selected_hook_reason: str
    content_angle: str
    cta_strategy: str
    forbidden_claim_check: list[str]
    differentiation_note: str
    edit_plan: EditPlan
    caption: str
    capcut_steps: str

class RunResult(BaseModel):
    run_id: str
    source_video: str
    success: bool
    needs_human_review: bool
    review_reasons: list[str]
    output_dir: str
    files_generated: list[str]
    error: Optional[str] = None


# ── ナレーション主導フロー用モデル（v3.0）────────────────────────────────────

class CandidateClip(BaseModel):
    """候補映像クリップ（観察結果のnotable_timestampsから引く）"""
    source_file: str
    timecode: str       # MM:SS
    description: str

class NarrativeSection(BaseModel):
    """ナレーション構成の1セクション"""
    section_id: int
    section_name: str   # フック / 事実提示 / 意味づけ / 安心感 / CTA など
    goal: str
    start_hint: str     # 例: "0秒"
    end_hint: str       # 例: "4〜5秒"
    narration_summary: str
    visual_evidence_required: list[str]
    candidate_clips: list[CandidateClip]
    cta_role: bool
    estimated_duration_sec: int

    @field_validator("estimated_duration_sec")
    @classmethod
    def positive_duration(cls, v):
        assert v > 0, "estimated_duration_sec は1以上"
        return v

class DurationRange(BaseModel):
    min_sec: int
    max_sec: int

    @model_validator(mode="after")
    def min_less_than_max(self):
        assert self.min_sec < self.max_sec
        return self

class BenefitDesign(BaseModel):
    """ベネフィット設計 - 視聴者が proof を見た後に得るものを明示する"""
    primary_benefit: str    # 視聴者が得る一番重要な利益を1文で
    benefit_angle: str      # 判断整理/価格透明化/比較優位/知識獲得/スピード（優先順位順。「高く売れる」は採用しない。スピードはCTA補助のみ）
    why_now: str            # このタイミングで行動する理由（状態・市場・商品起点）
    decision_value: str     # 接触後に何が「決められる」ようになるか


class EmotionalDesign(BaseModel):
    """感情設計（台本生成前処理）- ナレーションが刺さるための心理層設計"""
    target_inner_conflict: str   # 視聴者が今抱えている内的葛藤
    hidden_fear: str             # 表向きの悩みの奥にある感情
    embarrassment_trigger: str   # 相談を躊躇させる気まずさの引き金
    belief_to_shift: str         # 行動を止める思い込み
    shift_statement: str         # その思い込みを崩す1行の事実
    emotional_hook_type: str     # 心理描写型/部分否定型/実話っぽい独り言型/損失回避型/不信解消型
    reassurance_angle: str       # 最終的な安心の着地点
    cta_barrier_reduction: str   # CTAで下げる障壁と解決策
    benefit_design: Optional[BenefitDesign] = None  # ベネフィット設計（v3.4追加）


class ScriptSkeleton(BaseModel):
    """台本骨格（conversion モード専用）v3.4: hook-pain-shift-proof-benefit_bridge-relief-cta 構成"""
    hook_line: str             # 止まる問いかけ。心理描写 or 部分否定。問いかけ形式（？）必須
    pain_line: str             # 後回しの本音・気まずさ。hidden_fear / embarrassment_trigger を直接使う
    shift_line: str            # 思い込みを静かにズラす部分否定。proof の前に置き好奇心を作る
    proof_line: str            # 映像で確認できる事実 + 確認姿勢を示す。本体/付属品/状態/確認姿勢のいずれかを含む
    benefit_bridge_line: str   # proof を受けて「だから何が得られるか」を1文で。断定調OK
    relief_line: str           # 今すぐ決めなくていい安心。「大丈夫です」を含む
    cta_line: str              # 写真3枚・相場感だけでもOK。命令形禁止。障壁除去


class FlexibleSkeletonSection(BaseModel):
    """retention / insight / story モード用のSkeletonセクション"""
    purpose: str   # curiosity_gap / market_fact / owner_implication / memory_scene / etc.
    line: str      # 骨格の1〜2文
    note: str = "" # Pass2生成へのガイダンス（任意）


class FlexibleSkeleton(BaseModel):
    """retention / insight / story モード用の台本骨格（v4.0）"""
    content_mode: str
    narrative_arc: str
    ending_type: str
    sections: list[FlexibleSkeletonSection]


class NarrativePlan(BaseModel):
    """ナレーション主導構成設計（strategy.jsonの後継）"""
    selected_hook: str
    addressed_anxiety: str
    content_category: str   # 相場確認型 / 査定ポイント型 / 不信解消型 / CTA直結型
    narrative_formula_type: str  # 不安解消型 / 教育型 / 証拠提示型 / soft_pasna / anxiety_shift_reassure_cta
    recommended_duration_range: DurationRange
    sections: list[NarrativeSection]
    differentiation_note: str
    forbidden_claim_check: list[str]
    caption: str
    emotional_design: Optional[EmotionalDesign] = None  # 感情設計（v3.1追加）
    # v4.0: 複線ロジック
    content_mode: str = "conversion"                      # conversion / retention / insight / story
    narrative_arc: str = "anxiety_shift_reassure_cta"     # 展開の型（7種）
    ending_type: str = "cta"                              # cta / soft_cta / open_loop / aftertaste
    mode_rationale: str = ""                              # なぜこのmodeを選んだか

    @model_validator(mode="after")
    def validate_structure(self):
        assert len(self.sections) >= 3, "セクション数は3以上必要"
        # conversion モードのみ CTA セクション必須
        if self.content_mode == "conversion":
            assert any(s.cta_role for s in self.sections), "CTAセクションが必要（conversion モード）"
        return self


# ── Researcher エージェント用モデル ────────────────────────────────────────────

class PriceSource(BaseModel):
    """相場シグナルのソース情報。信頼できる出典を構造化して保持する。"""
    source_type: str       # official / retailer_ec / auction / news / internal / unknown
    name: str              # "エルメス公式" / "楽天市場 ブランドX" / "社内買取実績" 等
    url: Optional[str] = None
    reliability: str = "medium"   # high / medium / low
    observed_at: Optional[str] = None  # YYYY-MM-DD


class PriceSignal(BaseModel):
    """商品カテゴリの相場シグナル（手動入力 / 将来は自動収集）"""
    product_family: str           # ピコタン / ケリー / バーキン等
    condition: str                # 未使用 / 美品 / 良品 / 訳あり
    accessories: str              # フルセット / 本体のみ / 一部欠品
    price_range_min: int          # 査定額の下限（円）
    price_range_max: int          # 査定額の上限（円）
    market_trend: str             # 上昇 / 安定 / 下降
    # Phase1: Union[str, PriceSource] で後方互換を維持。
    # Phase2（将来）: PriceSource に統一し、Union を解消する予定。
    source: Union[str, PriceSource]
    note: Optional[str] = None

    @field_validator("source", mode="before")
    @classmethod
    def coerce_source(cls, v):
        """str で渡された旧フォーマットを PriceSource に昇格する。"""
        if isinstance(v, str):
            return PriceSource(source_type="unknown", name=v, reliability="medium")
        return v


class CompetitorPattern(BaseModel):
    """競合他社の訴求パターンとTBTの差別化軸"""
    competitor_name: Optional[str] = None
    platform: Optional[str] = None       # instagram / youtube / tiktok / x / website
    hook_pattern: str                    # 訴求パターンの分類ラベル
    hook_example: Optional[str] = None  # 実際のフックテキスト例（コピーのまま）
    angle: Optional[str] = None          # 数字訴求 / 権威訴求 / 緊急性訴求 等
    cta_style: Optional[str] = None      # 電話 / LINE / 来店 等
    weakness: str                        # 競合の弱点（TBTが上回れるポイント）
    differentiator: str                  # TBTだけが言えること
    url: Optional[str] = None
    note: Optional[str] = None
    observed_at: Optional[str] = None    # YYYY-MM


class VoiceSnippet(BaseModel):
    """顧客・SNS・LINE問い合わせから抽出した生の声"""
    text: str                               # 実際の言葉（できるだけ原文に近く）
    source: str                             # SNS / LINE / 口コミ / アンケート等
    emotion: str                            # 不安 / 期待 / 後悔 / 迷い / 安心等
    stage: str                              # awareness / consideration / intent / post_contact
    # 感情分類タグ。Synthesizer が belief_candidates / common_fears / audience_stuck_points に振り分けるキー。
    # 推奨値: pain / fear / belief / desire / cta_barrier / embarrassment
    tags: list[str] = []
    product_family: Optional[str] = None
    date_collected: Optional[str] = None   # YYYY-MM


class NewsArticle(BaseModel):
    """市場文脈・why now のソース。エルメス値上げ / 相場動向 / プレミア流通等のニュース。"""
    title: str
    summary: str                        # 要点（手動記入、2〜3行）
    url: Optional[str] = None
    source_name: str                    # メディア名（"WWD JAPAN" / "Business of Fashion" 等）
    published_at: Optional[str] = None  # YYYY-MM-DD
    relevance_tags: list[str] = []      # 値上げ / 相場 / プレミア / インバウンド 等
    market_implication: Optional[str] = None  # TBT動画に使える含意（手動記入）


class MarketContext(BaseModel):
    """market_context（research_memo）の構造化版。将来の自動生成に対応できる形。"""
    # ── 既存テキストフィールド（変更なし）──
    market_context: Optional[str] = None
    pricing_relevance: Optional[str] = None
    recommended_angle: Optional[str] = None
    angle_candidates: list[str] = []
    competitor_gap: Optional[str] = None
    usable_antithesis: Optional[str] = None
    benefit_candidates: list[str] = []
    # NOTE: audience_stuck_points は MarketContext の責務として設計。
    # voice_snippets の pain / cta_barrier / embarrassment タグから market_synthesizer が集約する。
    audience_stuck_points: list[str] = []
    # ── 構造化フィールド（Researcher v2）──
    price_signals: list[PriceSignal] = []
    competitor_patterns: list[CompetitorPattern] = []
    # ── 構造化フィールド（Researcher v3）──
    news_articles: list[NewsArticle] = []


class PersonaInsights(BaseModel):
    """persona_insights.json の構造化版。"""
    # ── 既存フィールド（変更なし）──
    raw_audience_phrases: list[str] = []
    common_fears: list[str] = []
    belief_candidates: list[str] = []
    natural_hook_phrases: list[str] = []
    # ── 拡張フィールド（Researcher v2）──
    voice_snippets: list[VoiceSnippet] = []


class ResearchContext(BaseModel):
    """Researcher エージェントの出力。後続全エージェント（Strategist / Writer / Reviewer）の入力。"""
    run_id: str
    source_videos: list[str]
    primary_source_video: str        # 移行互換用（= source_videos[0]）
    notes: str = ""
    observation: Observation
    market_context: Optional[MarketContext] = None
    persona_insights: Optional[PersonaInsights] = None


class NarrationCue(BaseModel):
    """ナレーション1行分のキュー情報（後方互換用）"""
    cue_id: int
    section_name: str
    line_text: str
    estimated_duration_sec: float
    source_file: str
    source_timecode: str    # MM:SS
    evidence_confidence: str  # high / medium / low / unconfirmed


class MasterLine(BaseModel):
    """ナレーション・テキスト統合行（v3.2）
    narration_line と text_line の一本化により、音声と画面の整合性を保つ。
    """
    cue_id: int
    section_name: str
    purpose: str         # opening / tension / evidence / shift / reassurance / cta
    master_line: str     # 意味の基準線（後のSRT参照元）
    narration_line: str  # AI音声（AivisSpeech）で読む文
    text_line: str       # 画面テキスト（narration_line と意味を揃える）
    estimated_duration: float
    source_file: str
    source_timecode: str  # MM:SS
    evidence_confidence: str  # high / medium / low / unconfirmed
    display_units: list[str] = []  # テロップ表示単位（Pass2.5 で生成 / 1要素6〜10文字基本）

    def to_narration_cue(self) -> NarrationCue:
        """後方互換用: NarrationCue に変換する"""
        return NarrationCue(
            cue_id=self.cue_id,
            section_name=self.section_name,
            line_text=self.narration_line,
            estimated_duration_sec=self.estimated_duration,
            source_file=self.source_file,
            source_timecode=self.source_timecode,
            evidence_confidence=self.evidence_confidence,
        )


# ── Gemini 動画観察 ────────────────────────────────────────────────────────────

GEMINI_OBSERVATION_PROMPT = """
あなたの仕事は「観察」です。販促コピーの生成ではありません。

この動画はエルメスのバッグ買取専門店の商品動画です。
画面に見えていない情報は推定しないでください。
推定が必要な場合は uncertainty_flags に入れてください。
タイムコードはすべてこの動画ファイル内の MM:SS 形式で記録してください。

以下のJSON Schemaに厳密に従ってJSONのみを返してください。説明文は不要です。

{
  "brand": "string（hermes等）",
  "product_category": "string（バッグ/財布/小物）",
  "product_family_guess": "string（ピコタン/バーキン等）",
  "product_family_confidence": "number（0.0〜1.0）",
  "visible_materials": ["string"],
  "visible_color": "string",
  "visible_hardware": "string（シルバー/ゴールド/不明等）",
  "visible_damage": ["string（傷・汚れの説明）"],
  "damage_confidence": "number（0.0〜1.0）",
  "accessories_detected": ["string（箱・保存袋等）"],
  "accessories_missing_or_unconfirmed": ["string"],
  "angles_present": ["string（front/side/top/inside/corners/hardware/label等）"],
  "angles_missing": ["string"],
  "text_detected_on_screen": ["string"],
  "speech_summary": "string（音声内容の要約、なければ空文字）",
  "notable_timestamps": [{"timecode": "MM:SS", "description": "string"}],
  "uncertainty_flags": ["string（不確実な情報）"],
  "evidence_notes": "string（査定に影響する観察メモ）",
  "overall_visual_quality": "string（good/fair/poor）",
  "needs_human_review": "boolean"
}
"""


def upload_video(client, video_path: str, max_retries: int = 3):
    """動画を1本アップロードしてURIを返す（リトライあり）"""
    mime_type = "video/mp4" if video_path.lower().endswith(".mp4") else "video/quicktime"
    size_mb = os.path.getsize(video_path) / 1024 / 1024
    print(f"   アップロード中: {os.path.basename(video_path)} ({size_mb:.0f}MB)")
    for attempt in range(1, max_retries + 1):
        try:
            with open(video_path, "rb") as f:
                uploaded = client.files.upload(
                    file=f,
                    config=genai_types.UploadFileConfig(mime_type=mime_type)
                )
            while uploaded.state and uploaded.state.name == "PROCESSING":
                time.sleep(3)
                uploaded = client.files.get(name=uploaded.name)
            return uploaded, mime_type
        except Exception as e:
            if attempt < max_retries:
                print(f"   ⚠ アップロード失敗（試行{attempt}/{max_retries}）: {e} → リトライ...")
                time.sleep(5 * attempt)
            else:
                raise


def observe_single_video(client, video_path: str) -> dict:
    """1本の動画をGeminiで観察してJSONを返す"""
    uploaded, mime_type = upload_video(client, video_path)
    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                genai_types.Part.from_uri(file_uri=uploaded.uri, mime_type=mime_type),
                GEMINI_OBSERVATION_PROMPT,
            ],
            config=genai_types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
            ),
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            parsed = parsed[0]
        return parsed
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Gemini: JSON解析失敗 ({os.path.basename(video_path)}) → {e}\n{response.text[:300]}")
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass


def analyze_with_gemini(video_paths: list[str]) -> dict:
    """各動画を個別観察し、ファイル名付きタイムコードで結果をまとめて返す"""
    client = genai.Client(api_key=GEMINI_API_KEY)
    print(f"📹 Gemini: {len(video_paths)}本を個別観察します...")

    per_file_obs: list[dict] = []
    for path in video_paths:
        print(f"   観察中: {os.path.basename(path)}")
        obs = observe_single_video(client, path)
        obs["_filename"] = os.path.basename(path)
        # タイムコードにファイル名を付与
        for ts in obs.get("notable_timestamps", []):
            ts["filename"] = os.path.basename(path)
        per_file_obs.append(obs)

    print(f"   全{len(video_paths)}本の観察完了 → 結果をマージ中...")

    # 全ファイルの観察を統合して1つのObservationにまとめる
    # 商品情報は最も信頼度の高いファイルから採用
    best = max(per_file_obs, key=lambda o: o.get("product_family_confidence", 0))

    merged: dict = {
        "brand": best.get("brand", ""),
        "product_category": best.get("product_category", ""),
        "product_family_guess": best.get("product_family_guess", ""),
        "product_family_confidence": best.get("product_family_confidence", 0),
        "visible_materials": _union_lists(per_file_obs, "visible_materials"),
        "visible_color": best.get("visible_color", ""),
        "visible_hardware": best.get("visible_hardware", ""),
        "visible_damage": _union_lists(per_file_obs, "visible_damage"),
        "damage_confidence": max(o.get("damage_confidence", 0) for o in per_file_obs),
        "accessories_detected": _union_lists(per_file_obs, "accessories_detected"),
        "accessories_missing_or_unconfirmed": _union_lists(per_file_obs, "accessories_missing_or_unconfirmed"),
        "angles_present": _union_lists(per_file_obs, "angles_present"),
        "angles_missing": list(
            set(_union_lists(per_file_obs, "angles_missing")) -
            set(_union_lists(per_file_obs, "angles_present"))
        ),
        "text_detected_on_screen": _union_lists(per_file_obs, "text_detected_on_screen"),
        "speech_summary": " / ".join(o["speech_summary"] for o in per_file_obs if o.get("speech_summary")),
        # タイムコードはファイル名付きで全て保持
        "notable_timestamps": [
            ts for o in per_file_obs for ts in o.get("notable_timestamps", [])
        ],
        # 不確実フラグは最も信頼度の高いファイルから取る（全ファイルマージすると重複が爆発する）
        "uncertainty_flags": best.get("uncertainty_flags", []),
        "evidence_notes": " / ".join(o["evidence_notes"] for o in per_file_obs if o.get("evidence_notes")),
        "overall_visual_quality": _worst_quality(per_file_obs),
        "needs_human_review": any(o.get("needs_human_review", False) for o in per_file_obs),
        # 各ファイルの個別観察も保持（Claude が参照できるように）
        "per_file_observations": per_file_obs,
    }
    return merged


def _union_lists(obs_list: list[dict], key: str) -> list:
    seen = set()
    result = []
    for o in obs_list:
        for item in o.get(key, []):
            if item not in seen:
                seen.add(item)
                result.append(item)
    return result


def _dedup_similar(obs_list: list[dict], key: str) -> list:
    """同じ意味のフラグ（キーワードが重複）を排除して返す"""
    all_flags = _union_lists(obs_list, key)
    # キーワードベースで重複除去（例: "leather type" が複数あったら1つだけ残す）
    keywords_seen: set[str] = set()
    result = []
    for flag in all_flags:
        # フラグを小文字化してキーワード抽出
        words = set(flag.lower().replace("(", "").replace(")", "").replace(".", "").split())
        # 意味の核となる単語（3文字以上）で重複判定
        core = frozenset(w for w in words if len(w) >= 4)
        # 既存フラグとのオーバーラップが50%以上なら重複とみなす
        is_dup = False
        for existing_core in keywords_seen:
            if len(core & existing_core) / max(len(core), 1) >= 0.5:
                is_dup = True
                break
        if not is_dup:
            keywords_seen.add(core)
            result.append(flag)
    return result


def _worst_quality(obs_list: list[dict]) -> str:
    rank = {"poor": 0, "fair": 1, "good": 2}
    worst = min(obs_list, key=lambda o: rank.get(o.get("overall_visual_quality", "good"), 2))
    return worst.get("overall_visual_quality", "good")


# ── Claude 戦略・成果物生成 ────────────────────────────────────────────────────

CLAUDE_SYSTEM_PROMPT = """
あなたはエルメス専門買取会社TBTのInstagramリール動画のディレクターです。

## TBT基本情報
- エルメス専門買取・販売（東京・蔵前）
- 社長：29歳男性
- ターゲット：エルメスを売りたい30〜50代女性
- ゴール：LINEへの問い合わせ誘導
- 完成尺：40秒固定
- AI音声前提・ハッシュタグなし

## あなたの責務
- observations.json（Geminiの観察結果）を唯一のソースとして戦略を立てる
- observations.json にない事実を増やさない
- 未確認情報を断定しない
- 出力はすべて指定JSONスキーマに従う
- capcut_steps のクリップ指示は必ず「ファイル名 MM:SS〜MM:SS」形式で記載する
  例：「IMG_9133.mov 00:15〜00:20 を使用」
- タイムコードは notable_timestamps の filename フィールドを参照して正確に記載する

## 禁止表現（出力に含めるな）
- 絶対高く売れる / 本物確定 / 今すぐ売らないと損
- 100% / 必ず高く / 保証します / 確実に
- 絶対に / 間違いなく本物 / 誇大断定表現

## フック選定ルール
- 情報ギャップ型・損失回避型・意外性型から各1案以上
- evidence_strength < 3 は採用不可
- brand_fit < 3 は採用不可
- cta_connectivity < 2 は再生成
- スコア: total = 0.25*market_fit + 0.25*evidence_strength + 0.20*pain_intensity + 0.10*novelty + 0.10*cta_connectivity + 0.10*brand_fit

## 40秒構成テンプレート
- 0〜3秒: フック
- 3〜8秒: 何の話かを明示
- 8〜18秒: 映像証拠の提示
- 18〜28秒: 査定差が出やすいポイントの説明
- 28〜36秒: 視聴者への意味づけ
- 36〜40秒: LINE誘導CTA

## テロップルール
- 1行15〜25文字
- 1画面1メッセージ
- 落ち着いた上品なトーン
- 断定しすぎない

## CTA例（問い合わせ障壁を下げる）
- 「売る前に一度状態を確認してみてください」
- 「LINEで写真を送っていただければご確認できます」
- 「まずは相場感だけ知りたい方もLINEからどうぞ」
"""

CLAUDE_USER_PROMPT_TEMPLATE = """
以下のGemini観察結果をもとに、編集ディレクション一式を生成してください。

## Gemini観察結果
{observations}

## 追加メモ（運用者より）
{notes}

## 出力形式
以下のJSON Schemaに厳密に従ってJSONのみを返してください。

{{
  "target_persona": "string",
  "pain_hypothesis": "string",
  "hook_candidates": [
    {{
      "hook_type": "information_gap|loss_aversion|unexpected",
      "text": "string",
      "market_fit": 1〜5,
      "evidence_strength": 1〜5,
      "pain_intensity": 1〜5,
      "novelty": 1〜5,
      "cta_connectivity": 1〜5,
      "brand_fit": 1〜5
    }}
  ],
  "selected_hook": "string",
  "selected_hook_reason": "string",
  "content_angle": "string",
  "cta_strategy": "string",
  "forbidden_claim_check": ["検出された禁止表現のリスト（なければ空配列）"],
  "differentiation_note": "string",
  "edit_plan": {{
    "target_duration_sec": 40,
    "segments": [
      {{
        "start_sec": 0,
        "end_sec": 3,
        "segment_goal": "string",
        "visual_instruction": "string",
        "subtitle_text": "string（15〜25文字）",
        "voiceover_text": "string",
        "proof_reference": "string（Gemini観察の根拠タイムコード等）",
        "transition_instruction": "string"
      }}
    ],
    "ending_cta": "string",
    "music_direction": "string",
    "caption_summary": "string"
  }},
  "caption": "string（投稿キャプション全文。ハッシュタグなし）"
}}
"""

CLAUDE_CAPCUT_PROMPT = """
以下の編集戦略と観察結果をもとに、CapCut作業手順書をマークダウン形式で生成してください。

## 編集戦略
{strategy}

## Gemini観察結果（ファイル別タイムコード）
{observations}

## 出力ルール
- 各クリップ指示には必ず「ファイル名 MM:SS〜MM:SS」形式でタイムコードを記載する
  例：IMG_9133.mov 00:15〜00:20 を使用
- タイムコードは observations の per_file_observations[].notable_timestamps を参照する
- ファイル名・タイムコードが不明なものは「要確認」と記載する
- CapCutの操作手順は具体的なステップで記載する（STEP1〜など）
- テロップ・AI音声・BGM・書き出しまですべて含める
"""


def generate_strategy_with_claude(observation: Observation, notes: str) -> dict:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません。export ANTHROPIC_API_KEY=... で設定してください。")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    obs_json = observation.model_dump_json(indent=2)

    # ── Step A: 戦略JSON生成（capcut_stepsは含めない）──────────────────────────
    print("🧠 Claude: 戦略生成中（1/2）...")
    user_prompt = CLAUDE_USER_PROMPT_TEMPLATE.format(
        observations=obs_json,
        notes=notes or "なし"
    )
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=CLAUDE_SYSTEM_PROMPT + "\n\n【重要】必ずJSONのみを返してください。説明文・マークダウン・コードブロック不要。{ で始まり } で終わる純粋なJSONのみ。",
        messages=[{"role": "user", "content": user_prompt}]
    )
    raw = message.content[0].text.strip()
    if "```" in raw:
        parts = raw.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            if p.startswith("{"):
                raw = p
                break
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    try:
        strategy_dict = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude: JSON解析失敗 → {e}\n{raw[:500]}")

    # ── Step B: CapCut手順書生成（プレーンテキスト）────────────────────────────
    print("🧠 Claude: CapCut手順書生成中（2/2）...")
    capcut_prompt = CLAUDE_CAPCUT_PROMPT.format(
        strategy=json.dumps(strategy_dict, ensure_ascii=False, indent=2),
        observations=obs_json,
    )
    capcut_msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=CLAUDE_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": capcut_prompt}]
    )
    strategy_dict["capcut_steps"] = capcut_msg.content[0].text.strip()
    return strategy_dict


# ── ナレーション主導構成生成（v3.0）──────────────────────────────────────────

CLAUDE_NARRATIVE_SYSTEM = """
あなたはエルメス専門買取TBTのナレーション主導コンテンツ設計者です。

## TBT基本情報
- エルメス専門買取・販売（東京・蔵前）
- ターゲット：エルメスを売りたい30〜50代女性
- ゴール：LINEへの問い合わせ誘導
- 前提：AI音声でナレーションを生成し、ナレーション音声を編集の骨にする

## 最重要原則
- observations.json にない事実をナレーションで断定しない
- 不確実な情報は evidence_confidence: low または unconfirmed にする
- 映像証拠と紐づいたナレーションのみ採用する

## TBTブランドスタンス【全出力で守る運用ルール】
以下のルールに反する表現・誘導は禁止。

- 売ると決めていなくても相談・問い合わせを受け付けている（決断を前提にしない）
- 相場確認だけの問い合わせでよい（売却申込を求めない）
- 金額だけでなく、なぜその金額かの理由まで見ている（価格の透明性）
- 判断を急がせない。その場で決めなくてよい（即決・来店・電話への誘導禁止）
- 大切なものを丁寧に扱う。それを映像と言葉で示す

## コンテンツモード【4モード運用】
content_mode は Pass1 で決定する。モード別に展開の型が変わる:
- conversion: LINE相談誘導。以下のフォーミュラに従う（デフォルト）
- retention: 視聴維持重視。問い→答え→再解釈の展開
- insight: 発見・判断材料の提供。市場事実→持ち主への示唆
- story: 感情移入・記憶定着。回想→迷い→余韻

## TBT不安解消フォーミュラ【conversion モード専用 / 推奨構成順】
1. 視聴者の感情停滞点を代弁（フック）— 迷い・気まずさ・先延ばしを言語化
2. 行動できていない本音に寄り添う（pain）— 恐れより「迷い・気まずさ・納得欲求」を優先
3. 思い込みをひっそり崩す（shift）— 査定＝売ると決めること、ではない
4. 映像の事実を丁寧に提示する（proof）— 「査定しています」でなく「丁寧に見ています」
5. 「だから何が決められるか」を言い切る（benefit_bridge）— 「高く売れる」でなく「自分で判断できる」
6. 安心感の付与（relief）— 今すぐ売らなくてもOK・決めなくていい
7. 低ハードルCTA（写真3枚からOK / 相場だけでもOK）

## コンテンツカテゴリと推奨尺
- 相場確認型: 40〜50秒
- 査定ポイント型: 40〜50秒
- 不信解消型: 40〜50秒
- CTA直結型: 35〜45秒

## 禁止表現
絶対高く売れる / 本物確定 / 今すぐ売らないと損 / 100% / 必ず高く / 保証します / 確実に / 絶対に / 間違いなく本物

## 感情設計の原則（emotional_design生成時）
- target_inner_conflict: 「今まだ決めていないのに相談していいのか」など、行動できていない内的葛藤を1行で
- hidden_fear: 「〜されたくない」「〜思われたくない」形式。表向きの不安の根
- embarrassment_trigger: 査定・問い合わせを踏み出しにくい具体的な気まずさ
- belief_to_shift: 「〜のはず」「〜でないと」形式の思い込み
- shift_statement: その思い込みを静かに崩す事実（断定しない、映像根拠があれば使う）
- emotional_hook_type: 先延ばし型|回想型|独り言型|気まずさ型|出番喪失型|思い込み転換型
  ※ 先延ばし型 = 「そのうちやろう」で止まっている感覚を自覚させる。問いかけ型が自然
  ※ 回想型 = 過去の決意が実行されなかった後悔・先延ばし感。`[過去の決意]＋〜はずなのに/〜のつもりだったのに/〜たままで` の構造
  ※ 独り言型 = 視聴者の内面をそのまま言葉にする。問いかけでなくてよい。弱く終わる
  ※ 気まずさ型 = 「相談＝失礼」という思い込みを代弁する。問いかけが自然
  ※ 出番喪失型 = 物が待っている感覚を静かに出す。罪悪感の刺激
  ※ 思い込み転換型 = 「〜しないと売れない」という誤解を崩す（hook で使う場合は shift を別角度にする）
  ※ hook が2行の場合: 1行目=独り言型/回想型（感情のにじみ）/ 2行目=問いかけ型またはブランド名補完
- reassurance_angle: 視聴者が最後に安心できる「再解釈の軸」（「〜でも大丈夫」「〜ではなく〜」形式）
- cta_barrier_reduction: CTAの前に除去すべき具体的ハードルと解決策（「〜でも大丈夫 / 〜だけでOK」形式）

## フック設計の禁止事項
hook（フック）は感情停滞点から始めること。問いかけ型・独り言型・回想型のいずれかで書く。以下は hook での使用禁止:
- 「実は〜」「知っておきたい〜」「知らないと損な〜」— 情報暴露・雑学型
- 「〜の秘密」「〜のポイント」「〜な理由」「〜の真実」— 教育型
- 「査定額を左右するのは〜」「相場を決めるのは〜」「〜が評価されます」— 教育型
- 価格・金額が主語の hook（「150万円〜」「高額な〜」「定価より〜」）— 価格訴求型
  ※ ただし感情停滞を強める時間・回数の数字は許容（「3年眠ったまま」「2回しか使っていない」等）
- 「〜を見ています」「〜を確認しています」で開始・終了する hook — proof 的 hook

## benefit_design の優先順位
benefit_angle の優先順位は次の通り（固定）。「高く売れる」を主語にした benefit は禁止:
1. 判断整理 — 売るかどうかを自分のペースで決められる
2. 価格透明化 — 相場・価格差の理由が見えて納得できる
3. 比較優位 — どこに出すかを自分で選ぶ根拠が持てる
4. 知識獲得 — 何が見られているかが分かる（教育的すぎる場合は1〜3を優先）
5. スピード — CTA補助には使えるが、benefit の主語にはしない
禁止: 「高く売れます」「高額になります」「〜万円で売れます」「お得に売れる」「速く売れます」

## トーン制約（全出力共通）
- 上品・落ち着き・誠実・一緒に確認する姿勢
- 「〜ですか？」「〜かもしれません」「〜でも大丈夫です」を優先
- 「今すぐ」「損をしている」「知らないと」「新常識」禁止
- 「少なくありません」「いらっしゃいませんか」「そんな方は多いです」禁止（外から見る形）
- 「重要です」「影響します」「確認します」「大切です」禁止（説明資料調）
- opening / tension / shift では特に「視聴者本人への静かな問いかけ」を優先する
- 説明調より静かな問いかけを優先

## リサーチメモの使い方（プロンプト内にある場合）
プロンプト内に「リサーチメモ（市場文脈・角度候補）」セクションがある場合、以下のように使うこと。

### 市場文脈ニュース → benefit_design.why_now
- `market_implication` に書かれた含意を `benefit_design.why_now` の根拠として反映する
- 「今すぐ売れ」という煽りにしない。「このタイミングで確認しておく理由」として自然に組み込む

### 相場シグナル → proof / benefit_bridge
- 具体的な金額帯を proof または benefit_bridge のセクションで使ってよい
- ただし「必ず○○万円」「確実に高値」などの断定は禁止。「〜万円前後の相場感です」程度のトーンを守る
- 映像に映っている商品の product_family と照合して使う（関係ない商品の相場を混ぜない）

### 競合との差別化ポイント → hook / shift
- `differentiator` を hook または shift の角度選択に使う
- `hook_example` は競合が使っている表現例。このトーン・手法とは逆のアプローチを取ること（模倣しない）

### 行動を止めているポイント → emotional_design.target_inner_conflict
- `audience_stuck_points` のリストを `target_inner_conflict` / `hidden_fear` / `embarrassment_trigger` の素材にする
- ただし observations.json にない映像事実を増やす根拠には使わない
"""

CLAUDE_NARRATIVE_PLAN_PROMPT = """
以下の観察結果をもとに、ナレーション主導の構成設計をJSONで生成してください。

## 観察結果
{observations}

## 追加メモ（運用者より）
{notes}
{research_memo_section}{persona_insights_section}
## hook 型の選定ルール【emotional_hook_type を選ぶ前に必ず確認】

以下の6型から1つを選ぶ。観察結果・persona・belief_to_shift をもとに、この素材に最も合う型を判断すること。

### Tier 1（毎回候補に入れる / 最優先）
- **先延ばし型**: 「そのうちやろう」で止まっている感覚を静かに自覚させる
  - 使う条件: 売る気はある・付属品も揃っている・でも動けていないケース
  - 禁止: urgency や損失感にしない。「気づき」として置く
- **回想型**: 過去の決意が実行されなかった後悔・先延ばし感。`[過去の決意]＋〜はずなのに/〜のつもりだったのに/〜たままで` の構造
  - 使う条件: 売ろうと思った過去がある・長期間眠っている商品
  - 禁止: 後悔を責める形・自己批判を強くしない
- **独り言型**: 問いかけではなく、自分の中で止まっている感じをにじませる
  - 使う条件: 内向きな迷い・一人で抱えている段階
  - 禁止: 外から見る形・断定・強い主張

### Tier 2（素材・文脈に合えば使う）
- **気まずさ型**: 「相談＝失礼・気まずい」という思い込みが行動を止めていることに気づかせる
  - 使う条件: 初めての売却検討・「まだ決めていない」段階
  - 禁止: 解消を先に言わない（代弁→共感の順）
- **出番喪失型**: 使えるのに使っていない物への罪悪感・もったいなさを静かに刺激する
  - 使う条件: 状態が良い商品・物への愛着が感じられる素材
  - 禁止: 「もったいない！」「眠らせるな」系の押しつけ

### Tier 3（shift と役割が重複しないか確認して使う）
- **思い込み転換型**: 「〜しないと売れない」「〜がないとダメ」という誤解を静かに崩す
  - 使う条件: 付属品欠如・状態不安・「自分には無理」と諦めているケース
  - 禁止: 「実は全然関係ない！」系の強い否定・雑学フック化。hook で使う場合は shift を別角度にする

### 選定後の出力
`emotional_hook_type` に型名を入れ、`hook_type_reason` に「なぜこの型を選んだか」を観察結果・persona との対応を含めて1〜2文で書くこと。

## 感情設計フィールドの精度ガイド【hidden_fear / belief_to_shift / reassurance_angle】

観察結果・persona から最も近いものを選ぶ。Q&A 風フックに寄せず、内的葛藤の言語化として使うこと。

### hidden_fear の典型パターン（「〜されたくない」「〜思われたくない」形式で）
- 相場だけ聞きに行って、迷惑だと思われたくない
- 売ると決めていないのに査定を頼んで、失礼と思われたくない
- 値段を聞いたら断りにくい雰囲気になると思われたくない
- 付属品が揃っていない状態で相談して、呆れられたくない
- 専門知識がないまま話して、恥をかきたくない

### belief_to_shift の典型パターン（「〜のはず」「〜でないと」形式で）
- 査定を頼むのは、売ると決めてからすること のはず
- 相場だけ確認しに行くのは、相手の時間を無駄にすること のはず
- 付属品が全部揃っていないと、相談できない のはず
- 専門店は敷居が高い・予備知識が必要 のはず

### reassurance_angle の方向性（belief_to_shift の崩し方）
- 査定 ≠ 売ると決めること。相場確認は情報収集でよい
- 相場だけの問い合わせで十分。決めるのは自分のペースでよい
- 付属品の有無にかかわらず、状態は確認できる
- 専門知識不要。何を見るかはこちらが判断する

## content_mode 選定ルール【v4.0 新規 / 必須】

以下の4モードから1つを選ぶ。観察結果・素材の文脈から判断すること。

### conversion（デフォルト）
- 目的: LINE相談誘導
- 選定条件: 付属品フルセット + 状態良好 + 「売るか迷っている / まだ動けていない」文脈
- フォーミュラ: anxiety_shift_reassure_cta または hesitation_detail_reinterpretation
- 注意: 付属品・状態が良いだけでは conversion 一択ではない。retention / insight も検討する

### retention
- 目的: 最後まで見させる / 次も見たくなる
- 選定条件: 思い込みを崩せる素材 / 意外性のある事実がある / 「なぜ？」を引き出せる文脈
- 例: なぜ保護フィルムが残っていることが査定に効くのか / なぜ付属品がある人ほど動けないのか
- arc候補: question_reveal_reframe / contradiction_insight_soft_cta

### insight
- 目的: 「知らなかった」発見を与える
- 選定条件: 価格差・付属品・状態の意味を持ち主に翻訳できる素材（刻印・金具・保存袋の意味など）
- 重要: 雑学化禁止。「あなたのバッグへの示唆」として着地させること
- arc候補: observation_implication_decision / market_fact_owner_implication

### story
- 目的: 感情移入・記憶定着
- 選定条件: 出番がない・眠っている・思い出がある素材 / 感情的な文脈が豊か
- 重要: ポエム化禁止。感情だけで終わらず「持ち主の判断に効く余韻」にすること
- arc候補: memory_hesitation_release / hesitation_detail_reinterpretation

## narrative_arc 選定ルール

content_mode が決まったら、以下から1つ選ぶ:

| arc名 | 展開 | 向くmode |
|-------|------|---------|
| anxiety_shift_reassure_cta | 不安→認識転換→安心→CTA | conversion |
| hesitation_detail_reinterpretation | 躊躇→具体シーン→再解釈 | conversion / story |
| question_reveal_reframe | 問い→答え→視点転換 | retention |
| contradiction_insight_soft_cta | 矛盾の提示→洞察→ソフト誘導 | retention / insight |
| observation_implication_decision | 観察→持ち主への意味→判断材料提供 | insight |
| market_fact_owner_implication | 市場事実→「あなたの話」への着地 | insight |
| memory_hesitation_release | 回想→迷い→小さな解放 | story |

## ending_type 選定ルール

| ending | 読後感 | 使用条件 |
|--------|--------|---------|
| cta | 「相談してみよう」 | conversion のみ |
| soft_cta | 「気になったら確認だけでも」 | insight / story の末尾。conversion にも使用可 |
| open_loop | 「なんだろう、気になる」 | retention 専用。答えを出さない |
| aftertaste | 「...そうかもしれない」 | story / insight。余韻で終わる |

## mode_rationale の書き方
なぜそのモードを選んだか、観察結果の具体的な根拠を1〜2文で書くこと。
例: 「保護フィルムが残っている映像事実がある → 査定上の意味を翻訳できる → insight モードが適切」

---

## 出力形式（JSONのみ）
{{
  "selected_hook": "string（視聴者を止めるフック文）",
  "addressed_anxiety": "string（解消する不安の具体的説明）",
  "content_category": "相場確認型|査定ポイント型|不信解消型|CTA直結型",
  "narrative_formula_type": "不安解消型|教育型|証拠提示型|soft_pasna|anxiety_shift_reassure_cta",
  "content_mode": "conversion|retention|insight|story",
  "narrative_arc": "string（上記7種から1つ）",
  "ending_type": "cta|soft_cta|open_loop|aftertaste",
  "mode_rationale": "string（なぜこのmodeを選んだか。素材の具体的根拠を1〜2文で）",
  "recommended_duration_range": {{"min_sec": number, "max_sec": number}},
  "differentiation_note": "string（TBT専門店ならではの差別化観点）",
  "forbidden_claim_check": ["検出された禁止表現（なければ空配列）"],
  "caption": "string（Instagram投稿キャプション全文。ハッシュタグなし）",
  "emotional_design": {{
    "target_inner_conflict": "string（視聴者が今抱えている内的葛藤を1行で）",
    "hidden_fear": "string（表向きの悩みの奥にある感情。「〜されたくない」形式）",
    "embarrassment_trigger": "string（相談を躊躇させる具体的な気まずさ）",
    "belief_to_shift": "string（行動を止める思い込み。「〜のはず」形式）",
    "shift_statement": "string（その思い込みを崩す事実。断定しない）",
    "emotional_hook_type": "先延ばし型|回想型|独り言型|気まずさ型|出番喪失型|思い込み転換型",
    "hook_type_reason": "string（なぜその型を選んだか。観察結果・persona・belief_to_shift との対応を1〜2文で）",
    "reassurance_angle": "string（最終的な安心の着地点。「〜でも大丈夫」「〜ではなく〜」形式）",
    "cta_barrier_reduction": "string（CTAで除去すべきハードルと解決策。「〜でも大丈夫 / 〜だけでOK」形式）",
    "benefit_design": {{
      "primary_benefit": "string（視聴者が proof を見た後に得る一番重要な利益を1文で。「〜が分かる」「〜できる」「〜が手に入る」形式）",
      "benefit_angle": "判断整理|価格透明化|比較優位|知識獲得|スピード",
      "why_now": "string（このタイミングで行動する理由。状態・市場・商品の具体情報を使って1文で）",
      "decision_value": "string（接触後に何が「決められる」ようになるか。「〜を自分で決められる」「〜の判断軸が持てる」形式）"
    }}
  }},
  "sections": [
    {{
      "section_id": 1,
      "section_name": "string（フック / 事実提示 / 意味づけ / 安心感 / CTA など）",
      "goal": "string（このセクションで達成すること）",
      "start_hint": "string（例: 0秒）",
      "end_hint": "string（例: 4〜5秒）",
      "narration_summary": "string（このセクションで伝える内容の要約）",
      "visual_evidence_required": ["string（observations内の事実に基づく必要映像）"],
      "candidate_clips": [
        {{
          "source_file": "string（ファイル名）",
          "timecode": "string（MM:SS）",
          "description": "string（映像の説明）"
        }}
      ],
      "cta_role": false,
      "estimated_duration_sec": number
    }}
  ]
}}
"""

CLAUDE_SKELETON_PROMPT = """
以下の感情設計と観察結果をもとに、ナレーション台本骨格（script_skeleton）を生成してください。

## 感情設計
{emotional_design}

## ベネフィット設計（benefit_bridge_line 生成に使う）
{benefit_design}

## 観察結果（映像の事実として使える情報）
{observations_summary}
{persona_insights_section}
## 構成順序【重要】
hook → pain → shift → proof → benefit_bridge → relief → cta の順で生成してください。
（shift が proof より前。proof は shift の答え。benefit_bridge は proof の直後に「だから何が得られるか」を置く）

---

## hook_line

**役割**: 最初の1文で視聴者を止める。emotional_design の情報と観察結果から、この素材・この人物に最も刺さる言葉を自分で考えて書く。

**型ごとの生成ルール（emotional_hook_type の値に合わせて書く）**

### 先延ばし型
- 「そのうちやろう」で止まっている感覚を静かに自覚させる
- 問いかけ型が自然。文末: 〜ていませんか？ / 〜のままになっていませんか？
- OK: 「売ると決めてから、そう思ったままになっていませんか？」
- OK: 「そのうち相談しよう、で止まっていませんか？」

### 回想型
- 過去の決意が実行されなかった後悔・先延ばし感。独り言で書く
- 文末: 〜はずなのに。 / 〜のつもりだったのに。 / 〜たままで。
- 構造: `「[商品名]、[過去の決意]」` ＋ `そう[決めた/思った]はずなのに。`
- OK: 「「ピコタン、売ろう」あの時そう決めたはずなのに。」
- OK: 「相場だけ見よう、そのつもりだったのに。」
- OK: 「売ると決めてから相談しよう、そう思って止まったままで。」

### 独り言型
- 問いかけではなく、自分の中で止まっている感じをにじませる
- 文末: 〜気がして。 / 〜なくて。 / 〜ている。（断定しない・弱く終わる）
- OK: 「まだ決めていないのに、連絡するのは早い気がして。」
- OK: 「出番がないまま、まだ決めきれなくて。」

### 気まずさ型
- 「相談＝失礼・気まずい」という思い込みを代弁する。問いかけが自然
- 文末: 〜ていませんか？ / 〜かな、と思っていませんか？
- OK: 「相場だけ聞きに行くのって、失礼かな、と思っていませんか？」

### 出番喪失型
- 物が待っている感覚を静かに出す。独り言または状況描写
- OK: 「クローゼットの中で、出番を待ったままのケリーがあります。」

### 思い込み転換型
- 「〜しないと売れない」という誤解を静かに崩す。問いかけで入る
- OK: 「付属品が全部揃っていなくても、と思っていませんか？」

---

**2行 hook の組み合わせルール（hook が2行になる場合）**
- 1行目 = 独り言型 / 回想型（感情のにじみ）
- 2行目 = 問いかけ型 または ブランド名・商品名で補完
- 例:
  - 1行目: 「「ピコタン、売ろう」あの時そう決めたはずなのに。」
  - 2行目: 「まだ、そのままになっていませんか。」
  - 例2: 1行目: 「相場だけ見よう、そのつもりだったのに。」/ 2行目: 「ケリーが、クローゼットにあり続けていませんか？」

**推奨（できれば入れる）**
- ブランド名または商品名（エルメス / ピコタン / ケリーなど）
- hidden_fear / embarrassment_trigger に根ざした心理トリガー
- 時間・回数の数字は感情停滞を強める場合に使ってよい（「3年眠ったまま」「2回しか使っていない」等）

**NG（以下は hook で使用禁止）**
- 「そんな方、実は多いんです」「いらっしゃいませんか？」（外から見る形）
- 断定で終わる「〜なんです」「〜ています」（音声が止まる）
- ブランド名も商品名も心理描写もない、完全に anonymous な状況説明だけの opening
- 「実は〜」「知っておきたい〜」「知らないと損な〜」（情報暴露・雑学型）
- 「〜の秘密」「〜のポイント」「〜な理由」「〜の真実」（教育型）
- 「査定額を左右するのは〜」「相場を決めるのは〜」（教育型 hook）
- 価格・金額が主語の hook（「150万円〜」「高額な〜」「定価より〜」）
- 「〜を見ています」「〜を確認しています」で始まる / 終わる hook（proof 的 hook）

---

## pain_line

**役割**: hook で生まれた共感を深める。hidden_fear または embarrassment_trigger を起点に、視聴者が実際に感じている停滞・気まずさ・迷いを言語化する。「恐れ」より「迷い・気まずさ・納得欲求」を優先すること。**1行1感情。接続詞・説明句を减らして短く切る。**

**参考パターン（優先順位順。hidden_fear / embarrassment_trigger から最も近いものを選ぶか自分で組み合わせる）**
1. 迷い: 「売ると決めてから」という思い込みで止まっている / まだ決めていない
2. 気まずさ: 専門知識がない状態での気まずさ / 相談だけに行くのが失礼な気がする
3. 先延ばし: 「後回しにしている」という事実を静かに出す / 出番がなくなっていく感覚
4. 不信: 査定で不利になるかも / 値切られそうという恐れ（3番以降に使う）
5. 孤立: 相談相手がいない・どこに行けばいいか分からない

**OK（短く感情単位で切った例）**
- 「付属品も、よく分からない。」（12文字）
- 「知識がないまま聞くのも、気まずい。」（17文字）
- 「そのまま、後回しにしてしまう。」（15文字）
- 「断りにくくなりそうで。」（11文字）

**NG**
- 「〜が多いです」「〜なりやすいです」（外から見る形）
- 分析・解説調になる

---

## shift_line

**役割**: belief_to_shift を静かにズラす。思い込みを「部分否定」または「認識の分離」で崩す。特定の文型には限定しない。proof の前に置き「何を見てるの？」という好奇心を残して終わる。

**本質（どれを使ってもよい）**
- 部分否定: 「〜だけではない」「そこだけで決まるわけではない」で思い込みの一部を崩す
- 認識の分離: 「〜と〜は別のことです」「〜することと〜することは違います」で概念を切り離す
- 再定義: 思い込みの前提を静かに置き換える（断定・強い否定は使わない）

**参考パターン（belief_to_shift の内容に合わせて。これ以外も歓迎）**
- 「問い合わせる ≠ 売ると決めた」系（査定＝売却決定思い込みへ）— 最優先
- 「相場を確認することと、売ると決めることは別のことです」（認識の分離型）
- 「相場を聞く ≠ 失礼」系（相談＝迷惑思い込みへ）
- 「本体だけではない」「そこだけで決まるわけでもない」系（本体万能思い込みへ）

**NG**
- 「ことがあります」「とされています」「が重要です」（説明資料調）
- 「新常識」「勘違い」「〜が正解です」「実は違います」（強い否定）
- 「でも〜だけではありません」に必ず寄せようとする（文型縛りは不要）

---

## benefit_bridge_line は proof の直後・relief の前に来ます（後述）

---

## proof_line

**役割**: 映像で確認できる事実と、どう見ているかの確認姿勢を示す。本体の状態 / 付属品の有無 / 確認姿勢 のいずれかを含む。shift の答えとして置く。

**書き方**
- 「見ています」「確認しています」形式を優先するが、状態・付属品の事実提示でもよい
- 「査定しています」より「見ています」「確認しています」のフレームを優先
- 「確認されています」「確認されていました」禁止
- 名詞の列挙は2〜3語まで（それ以上は後続行で分ける）

**推奨（できれば入れる）**
- 商品名またはブランド名を proof セクションのどこかに含める（全行に必須ではない）
- accessories_detected にある具体的な付属品名（箱・保存袋・鍵など）を使う

**NG**
- 「確認されています」「確認されていました」
- 観察結果にない事実を作る

---

## benefit_bridge_line

**役割**: proof の事実を受けて、「だから視聴者に何が手に入るか / 何が決められるようになるか」を言う。
benefit_design（primary_benefit / benefit_angle / decision_value）を参考に、この素材と文脈に合った具体的な得を自分の言葉で書く。

**書き方のルール**
- proof の事実を受けた「だから〜」「つまり〜」形式を優先
- 断定調OK（ここは言い切る）
- 「大丈夫」「安心」系は禁止（→ relief の役割）
- 「今すぐ」「損をしている」「知らないと」などの煽り禁止
- 「高く売れます」「高額になります」「〜万円で売れます」「お得に売れる」禁止（→ 「判断できる」「決められる」が主語）

**参考方向（優先順位順。benefit_angle の内容に応じて自分で言葉を選ぶ）**
1. 判断整理: 売るかどうかを自分のペースで決めやすくなる / 自分で判断するための材料が手に入る
2. 価格透明化: 査定額の差がどこで出るかが分かる / 価格差の理由が見えて納得できる
3. 比較優位: どこに出すかを自分で選ぶ根拠が持てる
4. 知識獲得: 何が見られているかが分かる（教育的すぎる場合は1〜3を優先）

**OK（短く断言した例）**
- 「何が揃っているかが分かる。」（12文字）
- 「今の相場感も整理できます。」（13文字）
- 「売るかどうかを決めやすくなります。」（17文字）
- 「比較の軸が持てます。」（10文字）

---

## relief_line

**役割**: proof + benefit を見た後の「でも自分には関係ない／相談は重い」という不安への先回り。
「大丈夫です」系の具体的な安心を、reassurance_angle に合わせて言い切る。

**参考パターン（自分で組み合わせてよい）**
- 「まだ売ると決めなくても、大丈夫」（決断不要）
- 「確認だけでも、大丈夫」（相場確認だけでよい）
- 「断っても構わない」（拒否権がある）
- 「その場で決めなくて大丈夫です」（即決不要）
- 「判断材料として持ち帰っていただけます」（持ち帰り可能）

**humanity markers（使ってよいフレーズ）**
- 「売ると決めなくても、大丈夫です」
- 「その場で決めなくて大丈夫です」
- 「判断材料として持ち帰っていただけます」
- 「相場を知ることは、売ることではありません」
- 「確認だけで、十分です」

**NG**
- 「大丈夫です」がない抽象的な綺麗ごとのみで終わる
- 「〜かもしれません」「〜と思います」（曖昧な逃げ）

---

## cta_line

**役割**: cta_barrier_reduction の具体的ハードルを取り除きながら行動を促す。会話の入口として書く。

**制約【重要】**
- 売却申込・ご予約・来店・電話への誘導は禁止（相談・確認の入口として書く）
- 「今すぐ」「期間限定」「高額査定」「最大〇〇万円」系の煽りフレーズ禁止
- 「写真3枚 / LINE / まだ決めていなくてもOK」のうち少なくとも1つを含む
- 推奨: 20文字以内 / 許容: 24文字以内 / 25文字以上は分割を検討
- 「〜どうぞ」「〜から」「〜だけでも」の誘い方を優先。命令形（〜ください）は使わない

**参考パターン（cta_barrier_reduction に合わせて自分で組み合わせてよい）**
- 「写真3枚から、LINEで相場確認だけでもどうぞ。」
- 「まだ決めていなくても、写真3枚からLINEで。」
- 「相場感だけ、LINEでお気軽にどうぞ。」

**NG**
- 「してください」「ご連絡ください」「お問い合わせください」（命令形）
- 「今すぐ」「今だけ」「高額査定」（圧力・煽り）
- 来店・電話・申込への誘導

---

## 共通制約
- 「今すぐ」「絶対」「必ず」「損をしている」「新常識」禁止
- 「少なくありません」「いらっしゃいませんか」「そんな方は多いです」禁止
- 「重要です」「影響します」「大切です」「評価されます」禁止（説明資料調）
- 読点（、）で終わる未完文禁止
- 上品・落ち着き・誠実・寄り添い

## 出力形式（JSONのみ）
{{
  "hook_line": "string",
  "pain_line": "string",
  "shift_line": "string",
  "proof_line": "string",
  "benefit_bridge_line": "string",
  "relief_line": "string",
  "cta_line": "string"
}}
"""

CLAUDE_SKELETON_FLEXIBLE_PROMPT = """
以下の感情設計と観察結果をもとに、{content_mode} モードの台本骨格を生成してください。

## 選択済みのモード情報
- content_mode: {content_mode}
- narrative_arc: {narrative_arc}
- ending_type: {ending_type}

## 感情設計
{emotional_design}

## ベネフィット設計
{benefit_design}

## 観察結果（映像の事実として使える情報）
{observations_summary}
{persona_insights_section}
---

## モード別セクション定義【必読】

### retention モード

**目的**: 最後まで見させる / 次も見たくなる展開。答えを途中で出しきらない。

**sections（この順序で生成）:**
1. `hook` — 問いかけまたは矛盾提示。「なぜ〇〇なのか」「こういう人ほど〇〇」的な引き。感情停滞点からでもよい
2. `curiosity_gap` — 続きを見たくなる「問いの宙吊り」。答えをまだ出さない。「実はこれが〜」で宙ぶらりんにする
3. `concrete_detail` — 映像の具体事実（付属品・状態・金具など）を丁寧に示す。宙吊りにした問いへの答えの素材
4. `reframe` — 視聴者の前提・思い込みをひっくり返す瞬間。shift より展開として大きく、「そういうことだったのか」感を持たせる
5. ending — ending_type に応じて以下から選択:
   - `open_loop`（open_loop指定時）: 答えを渡しきらない。「一度確認してみると良いかもしれません」程度で終わる。CTA行なし
   - `soft_cta`（soft_cta指定時）: 「気になったらLINEで確認だけでも」程度

### insight モード

**目的**: 「知らなかった」発見を与える。市場・価格・付属品の意味を持ち主への判断材料として翻訳する。

**重要**: 雑学化禁止。「あなたのバッグへの具体的な示唆」として着地させること

**sections（この順序で生成）:**
1. `hook` — 入口。感情停滞点または「知らなかった視点」への問いかけ
2. `market_fact` — 価格・付属品・状態に関する事実提示。「このバッグの〇〇は〜という意味がある」形式
3. `owner_implication` — その事実が持ち主に何を意味するか。「つまりあなたのバッグは〜」として着地させる
4. `judgment_material` — 売る・持つ・出すかを自分で判断するための材料を渡す
5. ending — ending_type に応じて以下から選択:
   - `soft_cta`（soft_cta指定時）: 「気になったらLINEで確認だけでも」程度
   - `aftertaste`（aftertaste指定時）: 余韻で終わる。気づきや感触を残す

### story モード

**目的**: 感情移入・記憶定着。持ち主の内面・記憶・迷いを具体的に描写する。

**重要**: ポエム化禁止。感情だけで終わらず「持ち主の判断に効く余韻」にすること

**sections（この順序で生成）:**
1. `hook` — 回想型または独り言型。バッグとの関係性を静かに描写
2. `memory_scene` — バッグにまつわる具体的な記憶・シーン。観察結果から推測できる範囲で
3. `hesitation` — 動けない気持ちの具体描写。迷い・気まずさ・後回し感
4. `concrete_moment` — 小さな気づきの瞬間。「でも〜」「それでも〜」的な転換
5. ending — ending_type に応じて以下から選択:
   - `aftertaste`（aftertaste指定時）: 余韻で終わる。「大丈夫です」は使わない。問いを残す
   - `soft_cta`（soft_cta指定時）: 「気になったらLINEで確認だけでも」程度

---

## 全モード共通制約

### TBTブランドスタンス
- 売ると決めていなくても相談OK（決断を前提にしない）
- 判断を急がせない、urgency 禁止（「今すぐ」「期間限定」等）
- 大切なものを丁寧に扱う姿勢を見せる
- CTA がある場合は「相場確認・相談の入口」として書く

### 禁止パターン
- 雑学化: 市場の話をそのままするだけ。「あなたのバッグへの示唆」がない状態
- ポエム化: 感情だけで終わり、持ち主の判断に何も提供しない状態
- 説明動画化: 「〜が重要です」「〜ということです」「〜に影響します」調
- observations にない事実を作る

### 各 line のルール
- 1〜2文で書く。説明を詰め込まない
- 音声として読んだとき自然に流れる文にする
- `note` にはPass2での展開ガイダンスを1文以内で書く（省略可）

---

## 出力形式（JSONのみ）
{{
  "content_mode": "{content_mode}",
  "narrative_arc": "{narrative_arc}",
  "ending_type": "{ending_type}",
  "sections": [
    {{
      "purpose": "hook|curiosity_gap|concrete_detail|reframe|open_loop|soft_cta|market_fact|owner_implication|judgment_material|aftertaste|memory_scene|hesitation|concrete_moment",
      "line": "string（骨格の1〜2文）",
      "note": "string（Pass2生成へのガイダンス。1文以内。省略可）"
    }}
  ]
}}

sections の配列はモード別の順序通りに生成すること（上記定義参照）。sections は5要素。
"""

CLAUDE_MASTER_LINES_PROMPT = """
以下の台本骨格をもとに、master_lines（ナレーション・テキスト統合行）を生成してください。

## 現在のモード
- content_mode: {content_mode}
- ending_type: {ending_type}

## 台本骨格
{script_skeleton}

## 観察結果（映像の事実として使える情報）
{observations_summary}

## master_lines の構造
各行は以下の3つを持ちます:
- master_line: 意味の基準線（後のSRT生成の参照元）
- narration_line: AI音声（AivisSpeech）で読み上げる文
- text_line: 画面に表示するテキスト

## TBTブランドスタンス【全行で守る運用ルール】
- 売ると決めていなくても相談を受け付けている（決断を前提にしない）
- CTA は「相場確認 / 相談の入口」として書く。売却申込・来店・電話・予約への誘導は禁止
- urgency / scarcity の煽り禁止（「今すぐ」「期間限定」「今だけ」「早い者勝ち」等）
- 判断を急がせない。その場で決めなくていい姿勢を壊さない

## ending_type 別 終わり方ルール【最重要】

現在の ending_type は「{ending_type}」です。最終セクションはこのルールで生成すること。

### cta（conversion モード）
- 最終行は必ず purpose: cta の1行にする
- 「写真3枚 / LINE / まだ決めていなくてもOK」のうち少なくとも1つを含む
- 推奨20文字以内。命令形禁止

### soft_cta（insight / story の軽い入口）
- 最終行は purpose: soft_cta の1行にする。CTAより圧力を下げた表現にする
- OK: 「相場確認だけ、LINEでどうぞ。」
- OK: 「気になったら、写真3枚だけ送ってみてもいいかもしれません。」
- urgency 禁止。来店・電話・予約・売却申込禁止。命令形禁止

### open_loop（retention モード）
- **CTA行を入れない**（「写真3枚から〜」「LINEで〜」禁止）
- 最終行は purpose: open_loop の1行にする
- 答えを出し切らない。問いまたは含みを残して終わる
- OK: 「今の状態を、一度確認してみても良いかもしれません。」（含み）
- OK: 「この順番が正しいかどうか——確かめてみてください。」（問い）
- NG: 「大丈夫です」で終わる（安心を与えすぎる）

### aftertaste（story モード）
- **CTA行を入れない**（「写真3枚から〜」「LINEで〜」禁止）
- 最終行は purpose: aftertaste の1行にする
- 感情的余韻または小さな気づきで終わる。「大丈夫です」で終わらない
- OK: 「まだ迷っていても、それでいい。」（余韻）
- OK: 「手放すかどうか、急がなくていい。」（解放）
- OK: 「このバッグのこと、少し考えてみてください。」（含み）
- NG: 「大丈夫です。」だけで終わる（→ それは relief の役割）
- NG: 「写真3枚から〜」「LINEで〜」（明示的CTA禁止）

## narration_line の書き方ルール【最重要・全行共通】
- **1行 = 1意味 / 1呼吸**。基本: 10〜18文字。最大: 22文字。25文字超は必ず分割する
- 「理由 + 感情 + 行動停止」を1行に詰め込まない。1行に置く意味は1つだけ
- 名詞の列挙は必ず分割する（「箱・保存袋・ストラップ」→ 2〜3行に分ける）
- 体言止めは禁止（音声が唐突に切れるため）
- 読点（、）で行を終わらせない（未完文に聞こえる）
- AivisSpeechで聞いたとき自然に流れる文にする
- NG表現: 「〜ことがあります」「〜となっています」「〜とされています」「〜が重要です」「〜が評価されます」「〜ている様子が見られます」

## セクション別 narration_line ルール

### purpose: hook

**hook が1行の場合**
- 問いかけ型: 「〜ていませんか？」で締める
- 独り言型: 「〜気がして。」「〜なくて。」などで弱く終わる
- 回想型: 「〜はずなのに。」「〜のつもりだったのに。」「〜たままで。」で締める

**hook が2行の場合【推奨構成】**
- 1行目 = 感情のにじみ（独り言型 / 回想型）: 短く・弱く・感情だけ置く
- 2行目 = 商品名の補完 または 問いかけで締める
- 1行目は商品名なしでよい。2行目でブランド名 / 商品名を入れる
- OK構成例:
  - 1行目: 「「売ろう」そう決めたはずなのに。」
  - 2行目: 「ピコタンが、まだそのままになっていませんか。」
  - ―
  - 1行目: 「相場だけ見よう、そのつもりだったのに。」
  - 2行目: 「ケリーが、クローゼットにあり続けていませんか？」

**全hook共通NG**
- 状況説明・事実羅列で始まる文
- 「実は〜」「知っておきたい〜」「〜の秘密」「〜な理由」（情報暴露・雑学型）
- 「〜を見ています」「〜を確認しています」で始まる / 終わる（proof 的 hook）
- 「査定額を左右する〜」「相場を決める〜」「箱が〜」「付属品が〜」「相場は〜」で始まる（教育型 hook）
- 「150万円〜」「高額な〜」「定価より〜」など価格・金額が主語（時間・回数の数字は許容）

### purpose: pain
- 停滞感・感情の引っかかりを表す（迷い > 気まずさ > 先延ばし > 不信の優先順で）
- **感情単位で切る。接続詞・説明句を减らす。1行1感情**
- 感情を直接言語化する。状況分析にしない
- NG: 「〜が多いです」「〜なりやすいです」「〜という方もいます」（外から見る形）
- NG: 「〜と考えると」「〜と思われたら」「だから」などの説明接続句（→ 感情1語で切る）
- OK: 「付属品も、よく分からない。」（12文字）
- OK: 「知識がないまま聞くのも、気まずい。」（17文字）
- OK: 「そのまま、後回しにしてしまう。」（15文字）
- OK: 「断りにくくなりそうで。」（11文字）

### purpose: shift
- **原則1行。belief_to_shift を1文で崩す。2行目は削る**
- 部分否定または認識の分離を使う。断定・強い否定禁止
- 「でも〜だけではない」に縛られなくてよい。「〜と〜は別のことです」形式も有効
- proof の前に来るので「何を見てるの？」という好奇心を残して終わる
- NG: 「ことがあります」「とされています」「が重要です」（説明資料調）
- NG: shift の言い換えを2行目に追加する（統合して1行にする）
- OK: 「問い合わせることは、売ると決めることとは違います。」（認識の分離型）
- OK: 「相場を知ることと、売ると決めることは別のことです。」（認識の分離型）
- OK: 「査定をお願いすることと、売ると決めることは、別のことです。」（同上）

### purpose: proof
- **最大2行。商品全体 → 付属品の順で1行ずつ。3行目は削って2行目に統合する**
- 「見ています」「見ていきます」を優先。「確認されています」「確認されていました」禁止
- 名詞列挙は1行2〜3項目まで。それ以上は行を分ける
- 商品名またはブランド名、具体的な付属品名を含めると強い（推奨）
- OK: 「ピコタンの状態を、一面ずつ見ています。」＋「箱、保存袋、カデナも確認しています。」（2行）
- NG: 3行目に「急かすような場面はありません。」などの説明を追加（→ 削る）

### purpose: benefit_bridge
- proof の直後・relief の直前に置く（1〜2行）
- **長い説明文禁止。22文字以内を目標。断言1文で完結させる**
- script_skeleton の benefit_bridge_line を展開する
- 断定調OK（ここは言い切る）
- 「大丈夫」「安心」系は禁止（→ relief の役割）
- 「今すぐ」「損」「知らないと」などの煽り表現NG
- 「高く売れます」「高額になります」「〜万円で売れます」「お得に売れる」禁止（→ 主語は「判断できる」「決められる」）
- OK: 「何が揃っているかが分かる。」（12文字）
- OK: 「今の相場感も整理できます。」（13文字）
- OK: 「売るかどうかを決めやすくなります。」（17文字）
- OK: 「比較の軸が持てます。」（10文字）

### purpose: relief
- **原則1行。「まだ決めていなくても、大丈夫です。」で完結させる**
- 2行目は削る。shift が「売ること≠問い合わせること」を言っていれば relief は1行で十分
- NG: 「相場を知ることと、売ると決めることは別のことなので。」を2行目に追加（→ shift の役割なので削る）

### purpose: cta
- **1行固定。行動だけ伝える。推奨20文字以内 / 許容24文字以内 / 25文字以上は分割**
- 売却申込・来店・電話・予約への誘導は禁止（相場確認・相談の入口として書く）
- urgency / scarcity の煽りは禁止（「今すぐ」「期間限定」「早い者勝ち」等）
- 「写真3枚 / LINE / まだ決めていなくてもOK」のうち少なくとも1つを含む
- 障壁除去を優先。命令形禁止
- OK: 「写真3枚から、LINEで相場確認だけでもどうぞ。」（23文字）
- OK: 「相場感だけ、LINEでお気軽にどうぞ。」（18文字）

---

## 非conversion モードの purpose ルール【retention / insight / story 用】

### purpose: curiosity_gap（retention）
- 答えをまだ出さない。「問いを宙吊りにする」1〜2行
- 「〜か？」「〜だろうか？」で終わる問いかけ形式
- NG: 答えを先に言う / 解説をはじめる
- OK: 「この順番、確かめたことはありますか。」
- OK: 「そもそも、なぜ動けないのか——。」

### purpose: reframe（retention）
- 視聴者の前提・思い込みをひっくり返す瞬間。**1行で完結させる**
- conversion の shift より展開として大きく、「そういうことだったのか」感を持たせる
- OK: 「付属品が揃っているほど、動けなくなる——それが正直なところかもしれません。」
- NG: 「そうではありません」「間違いです」（強い否定禁止）

### purpose: concrete_detail（retention）
- 映像の具体事実（付属品・状態・金具など）を丁寧に示す。**1〜2行**
- proof と同じ書き方でよい。「見ています」形式

### purpose: open_loop（retention）
- ending_type: open_loop 参照。**CTA行禁止。含みを残す1行**

### purpose: market_fact（insight）
- 価格・付属品・状態に関する「知らなかった事実」を提示。**1〜2行**
- 「〜という意味があります」「〜に影響します」ではなく「〜が説明しやすくなります」「〜が見えてきます」
- 雑学化禁止。観察結果（付属品・状態）から具体的に出す

### purpose: owner_implication（insight）
- market_fact の事実が「持ち主のあなた」に何を意味するかに着地させる。**1〜2行**
- 「つまりあなたのバッグは〜」「このバッグに限って言えば〜」形式で個別化する
- 「感覚ではなく事実として」「なぜその金額かが説明できる状態」が有効

### purpose: judgment_material（insight）
- 売る・持つ・出すかを自分で判断するための材料を渡す。**1行**
- 「知ってから決める」「自分のペースで判断できる」が着地点
- NG: 煽り・urgency

### purpose: soft_cta（insight / story）
- ending_type: soft_cta 参照。**CTAより圧力を下げた1行**

### purpose: memory_scene（story）
- バッグにまつわる記憶・シーンの描写。**1〜2行**
- 観察結果から推測できる範囲（色・状態・付属品）を使って具体化
- OK: 「エトゥープの色が、あの日のままでいる。」
- NG: 観察結果にない記憶を創作する

### purpose: hesitation（story）
- 動けない気持ちの内面描写。**1行**
- 気まずさ・迷い・後回し感を静かに言語化する
- OK: 「まだ決めていないのに聞くのは、早い気がして。」
- NG: 感情分析・外から観察する形

### purpose: concrete_moment（story）
- 小さな気づきの転換点。**1行**
- 「でも〜」「それでも〜」「考えてみると〜」程度の軽い転換
- conversion の shift ほど明確な認識転換にしなくてよい。余韻につながる入口として置く

### purpose: aftertaste（story）
- ending_type: aftertaste 参照。**CTA行禁止。余韻の1行**

## text_line の書き方ルール

### 基本原則
- text_line は narration_line の意味の核を変えない
- text_line が narration_line より長くなる場合は見直す
- 視覚的な訴求として別角度から当てることは許容するが、narration_line と真逆の意味・別トーンにはしない

### 全セクション共通
- narration_line の核となるフレーズ・言葉を活かして短縮する
- 完全に別の概念・別のフレームに置き換えない
- NG例（全セクション共通）: narration_line「査定は、決める場所ではありません。」に対して text_line「気軽に相談OK」（別トーン・別概念）

## purpose フィールド
script_skeleton の sections の purpose をそのまま使うこと。

**conversion モード:**
hook / pain / shift / proof / benefit_bridge / relief / cta

**retention モード:**
hook / curiosity_gap / reframe / concrete_detail / open_loop / soft_cta

**insight モード:**
hook / market_fact / owner_implication / judgment_material / soft_cta

**story モード:**
hook / memory_scene / hesitation / concrete_moment / proof / benefit_bridge / aftertaste

## 展開ルール
- **conversion モード**: hook → pain → shift → proof → benefit_bridge → relief → cta の順
  （shift が proof より前。benefit_bridge は proof の直後）
- **その他のモード**: script_skeleton の sections 配列の順序をそのまま守ること
- **合計行数: 10〜12行が目標。13行は例外。14行以上は原則NG**
- **推定尺が50秒を超える場合は行を削って50秒以内に収める（story モードは55秒まで許容）**
- estimated_duration = narration_line 文字数 ÷ 5.5 を目安に計算する
- **ending_type が open_loop / aftertaste の場合: CTA行は一切入れない。最終行は上記「ending_type 別終わり方ルール」に従う**

## セクション別行数上限【必守】

**conversion モード:**
| セクション | 上限 | 備考 |
|------------|------|------|
| hook | 2行 | 維持 |
| pain | 2行 | |
| shift | **1行** | 2行目は統合か削除 |
| proof | **2行** | 3行目は2行目に統合 |
| benefit_bridge | 2行 | |
| relief | **1行** | 「大丈夫です」1文で完結 |
| cta | **1行** | 固定 |

**非conversion モード:**
| セクション | 上限 | 備考 |
|------------|------|------|
| hook | 2行 | |
| curiosity_gap | 2行 | |
| reframe | **1行** | 転換は1文で |
| concrete_detail | 2行 | |
| market_fact | 2行 | |
| owner_implication | 2行 | |
| judgment_material | **1行** | |
| memory_scene | 2行 | |
| hesitation | **1行** | |
| concrete_moment | **1行** | |
| open_loop | **1行** | CTA禁止 |
| soft_cta | **1行** | |
| aftertaste | **1行** | CTA禁止・余韻で完結 |

## 行数を削る優先順位（conversion モード）
行数が超過した場合、以下の順で削ること:
1. shift の2行目（補足・言い換え行）
2. proof の3行目（付属品の個別列挙行）
3. relief の2行目（「大丈夫」以外の補足行）

## 証拠付け
- source_file と source_timecode は per_file_observations[].notable_timestamps から最も適切なものを使う
  ない場合は source_file を空文字、source_timecode を "--:--" にする
- evidence_confidence: high（映像で確認済み）/ medium（推定可能）/ low（不確実）/ unconfirmed

## 出力形式（JSON配列のみ）
[
  {{
    "cue_id": 1,
    "section_name": "string（script_skeleton の purpose と対応するセクション名）",
    "purpose": "hook|pain|shift|proof|benefit_bridge|relief|cta",
    "master_line": "string（意味の基準線）",
    "narration_line": "string（AI音声で読む文。25文字以内を目安に）",
    "text_line": "string（画面テキスト。narration_line と意味を揃える）",
    "estimated_duration": number,
    "source_file": "string",
    "source_timecode": "string（MM:SS）",
    "evidence_confidence": "high|medium|low|unconfirmed"
  }}
]
"""

CLAUDE_TIMELINE_NOTES_PROMPT = """
以下のmaster_linesをもとに、Premiere Proでの編集ガイドをマークダウンで作成してください。

## master_lines（ナレーション・テキスト統合行）
{master_lines}

## 出力ルール
- Premiere Proでの「ナレーション音声先置き→映像を当てる」編集を前提にする
- セクションごとに以下を記載する:
  1. ナレーション行（cue_id / narration_line / 推定秒数）
  2. テロップ（text_line をそのまま使う。独自生成しない）
  3. 使う映像クリップ（source_file + source_timecode + 説明）
  4. BGM指示
- 累積タイムコード（目安秒数）をセクション冒頭に記載する
- evidence_confidence が low / unconfirmed の行には ⚠️ を付ける
- 映像証拠が不足しているセクションには「📷 要撮り直し」を記載する
- マークダウン形式で出力する
"""

CLAUDE_DISPLAY_UNITS_PROMPT = """
以下の master_lines の各行に対して、テロップ表示単位（display_units）を生成してください。

## 入力
{master_lines}

## display_units の役割
縦動画（9:16）で1画面に表示するテロップの最小単位。
narration_line の音声に合わせて順番に画面表示する。視聴者が一瞬で読める長さに分割する。

## 文字数ルール
- 基本: 1要素 6〜10文字
- 許容上限: 12文字
- 13文字以上は必ず分割する
- 3文字以上を保つ（2文字以下の断片は前後と結合する）

## 意味の完結ルール【最重要】
各 display_unit は、それ単体で意味が通る必要がある。
「この1枚だけ表示されても、何を言いたいか伝わるか？」を必ず確認すること。
伝わらない場合は、隣の要素と結合するか言い換えること。

## 結合優先ルール
2つの要素に分けるより1つにまとめた方が自然・意味が通る場合は、結合を優先する。
無理に分割しないこと。

## 助詞終わり禁止【必須】
助詞（が・は・を・で・へ・に・の・と・も・から・より）で終わる断片は禁止。

禁止パターンと修正例（実例ベース）:
- NG: 「付属品が」　　　→ OK: 「付属品」（助詞を削る）
- NG: 「そのあとで」　　→ OK: 「そのあとに」「そのあと」（言い換えるか削る）
- NG: 「見ているのは」　→ OK: 「見ているのは本体だけ」と結合（12字、許容内）
- NG: 「本体だけでは」　→ OK: 「本体だけじゃない」（言い換えて結合）
- NG: 「売るかどうかは」→ OK: 「売るかどうか」（「は」を削る）
- NG: 「と思うと」単独　→ OK: 前後の要素と結合するか削除する

## 接続途中での切断禁止
「〜と」「〜が」「〜ので」など接続の途中で終わる断片は禁止。
読点（、）や文末（。）を切れ目の目安にする。

## 生成元について
- 主に text_line を参考に分割する
- text_line が縮約されすぎて不自然な表示になる場合は narration_line も参照してよい

## 語尾の削り方（任意）
- 「〜ていきます」「〜でしょうか」などの読み上げ語尾は削ってよい
- 体言止め・名詞句で締める表現を優先
- ただし意味が通ることを最優先にする

## 出力形式（JSON配列のみ）
[
  {{
    "cue_id": 1,
    "display_units": ["string", "string"]
  }}
]
"""


def _build_research_memo_section(research_memo: Optional[dict]) -> str:
    """Pass1 用: research_memo の内容をプロンプト用テキストに変換する"""
    if not research_memo:
        return ""
    lines = ["\n## リサーチメモ（市場文脈・角度候補）",
             "以下は今回の動画に使える市場文脈・角度候補です。",
             "emotional_design の benefit_design（特に why_now / pricing_relevance）と",
             "hook / benefit_bridge の角度選択に参考として使ってください。"]
    if research_memo.get("market_context"):
        lines.append(f"\n### 市場文脈\n{research_memo['market_context']}")
    if research_memo.get("pricing_relevance"):
        lines.append(f"\n### 価格・相場の文脈\n{research_memo['pricing_relevance']}")
    if research_memo.get("recommended_angle"):
        lines.append(f"\n### 推奨角度\n{research_memo['recommended_angle']}")
    if research_memo.get("angle_candidates"):
        lines.append("\n### 角度候補")
        for a in research_memo["angle_candidates"]:
            lines.append(f"- {a}")
    if research_memo.get("competitor_gap"):
        lines.append(f"\n### 競合ギャップ（TBTが言えること）\n{research_memo['competitor_gap']}")
    if research_memo.get("usable_antithesis"):
        lines.append(f"\n### 使える対比・思い込み否定\n{research_memo['usable_antithesis']}")
    if research_memo.get("benefit_candidates"):
        lines.append("\n### ベネフィット候補")
        for b in research_memo["benefit_candidates"]:
            lines.append(f"- {b}")
    if research_memo.get("audience_stuck_points"):
        lines.append("\n### 行動を止めているポイント")
        for s in research_memo["audience_stuck_points"]:
            lines.append(f"- {s}")
    # 拡張フィールド（Researcher v2）
    price_signals = research_memo.get("price_signals", [])
    if price_signals:
        lines.append("\n### 相場シグナル（商品別・状態別）")
        lines.append("（benefit_bridge や proof のセクションで具体的な相場感を示す際に参照してください）")
        for ps in price_signals:
            if isinstance(ps, dict):
                rng = f"{ps.get('price_range_min', 0)//10000}〜{ps.get('price_range_max', 0)//10000}万円"
                lines.append(f"- {ps.get('product_family', '')} / {ps.get('condition', '')} / {ps.get('accessories', '')}: {rng}（{ps.get('market_trend', '')}）")
    competitor_patterns = research_memo.get("competitor_patterns", [])
    if competitor_patterns:
        lines.append("\n### 競合との差別化ポイント")
        lines.append("（hook や shift で TBT 固有の強みを訴求する際に参照してください）")
        for cp in competitor_patterns:
            if isinstance(cp, dict):
                lines.append(f"- 競合訴求パターン:「{cp.get('hook_pattern', '')}」")
                if cp.get("hook_example"):
                    lines.append(f"  実例:「{cp['hook_example']}」")
                lines.append(f"  → TBTの差別化:「{cp.get('differentiator', '')}」")
    # 拡張フィールド（Researcher v3）
    news_articles = research_memo.get("news_articles", [])
    if news_articles:
        lines.append("\n### 市場文脈ニュース（why_now / benefit_bridge の角度選択に参照）")
        lines.append("（「今が売り時」という煽りにせず、価格・相場の文脈として使うこと）")
        for na in news_articles:
            if isinstance(na, dict):
                tags = "/".join(na.get("relevance_tags", []))
                tag_str = f"【{tags}】 " if tags else ""
                lines.append(f"- {tag_str}{na.get('title', '')}")
                if na.get("summary"):
                    lines.append(f"  概要: {na['summary']}")
                if na.get("market_implication"):
                    lines.append(f"  含意: {na['market_implication']}")
    return "\n".join(lines) + "\n"


def _build_persona_insights_section(insights: Optional[dict]) -> str:
    """persona_insights.json の内容をプロンプト用テキストに変換する"""
    if not insights:
        return ""
    lines = ["\n## 視聴者インサイト（補助情報 / 月次更新）",
             "以下は実際の視聴者の言葉・恐れ・思い込みを収集したものです。",
             "emotional_design（特に hidden_fear / belief_to_shift / target_inner_conflict）の設計と",
             "opening / tension のフレーズ選択に参考として使ってください。",
             "ただし、この情報は補助であり、観察結果の映像事実より優先しないでください。"]
    if insights.get("raw_audience_phrases"):
        lines.append("\n### 視聴者の生の言葉")
        for p in insights["raw_audience_phrases"]:
            lines.append(f"- {p}")
    if insights.get("common_fears"):
        lines.append("\n### よくある恐れ・抵抗感")
        for f in insights["common_fears"]:
            lines.append(f"- {f}")
    if insights.get("belief_candidates"):
        lines.append("\n### 行動を止める思い込み候補")
        for b in insights["belief_candidates"]:
            lines.append(f"- {b}")
    if insights.get("natural_hook_phrases"):
        lines.append("\n### 刺さりやすい問いかけフレーズ例")
        for h in insights["natural_hook_phrases"]:
            lines.append(f"- {h}")
    # 拡張フィールド（Researcher v2）
    voice_snippets = insights.get("voice_snippets", [])
    if voice_snippets:
        lines.append("\n### 顧客の生の声（実際のフレーズ・感情・行動ステージ）")
        lines.append("（hook / pain / relief のフレーズ選択に最優先で参照してください。できる限りそのままの言葉に近いトーンで使ってください）")
        for vs in voice_snippets:
            if isinstance(vs, dict):
                product = f"（{vs['product_family']}）" if vs.get("product_family") else ""
                lines.append(f"- 「{vs.get('text', '')}」{product} ／ 感情: {vs.get('emotion', '')} ／ ステージ: {vs.get('stage', '')}")
    return "\n".join(lines) + "\n"


def _build_skeleton_insights_section(insights: Optional[dict]) -> str:
    """Pass1.5 用: persona_insights を ScriptSkeleton 各行へ明示的にマッピングして返す"""
    if not insights:
        return ""
    lines = ["\n## 視聴者インサイト（骨格生成への指示）",
             "以下の情報を各行の生成に直接反映してください。"]

    # hook_line 用
    hook_phrases = insights.get("natural_hook_phrases", [])
    raw_phrases = insights.get("raw_audience_phrases", [])
    if hook_phrases or raw_phrases:
        lines.append("\n### hook_line に使える素材")
        lines.append("（止まる問いかけの言葉選びに使う。下記フレーズの言い回しを参考にすること）")
        for p in hook_phrases:
            lines.append(f"- {p}")
        for p in raw_phrases:
            lines.append(f"- {p}")

    # pain_line 用
    fears = insights.get("common_fears", [])
    if fears or raw_phrases:
        lines.append("\n### pain_line に使える素材")
        lines.append("（後回しにしている本音・気まずさの根拠として使う）")
        for f in fears:
            lines.append(f"- {f}")
        for p in raw_phrases:
            lines.append(f"- {p}")

    # shift_line 用
    beliefs = insights.get("belief_candidates", [])
    if beliefs:
        lines.append("\n### shift_line に使える素材")
        lines.append("（否定すべき思い込みの根拠として使う。「でも、〜ではありません」の形で崩す）")
        for b in beliefs:
            lines.append(f"- {b}")

    lines.append("\n※ relief_line は common_fears の裏返し（恐れが消える言葉）として書くこと。")
    lines.append("※ cta_line は raw_audience_phrases の「相場だけ知りたい」「写真だけ送れれば」という感覚に合わせること。")
    return "\n".join(lines) + "\n"


# ── Researcher エージェント用フォーマッタ（移行期ラップ）────────────────────────

def _format_market_context(mc: Optional[MarketContext]) -> str:
    """Strategist 用: MarketContext → プロンプトテキスト（_build_research_memo_section へのラップ）"""
    if not mc:
        return ""
    return _build_research_memo_section(mc.model_dump())


def _format_persona_section(pi: Optional[PersonaInsights]) -> str:
    """Pass1（Strategist）用: PersonaInsights → プロンプトテキスト（_build_persona_insights_section へのラップ）"""
    if not pi:
        return ""
    return _build_persona_insights_section(pi.model_dump())


def _format_skeleton_section(pi: Optional[PersonaInsights]) -> str:
    """Pass1.5（Writer）用: PersonaInsights → プロンプトテキスト（_build_skeleton_insights_section へのラップ）"""
    if not pi:
        return ""
    return _build_skeleton_insights_section(pi.model_dump())


# ── Researcher エージェント ────────────────────────────────────────────────────

class ResearcherAgent:
    """
    Researcher エージェント。
    動画観察（Gemini）・market_context・persona_insights を束ねて ResearchContext を生成する。
    後続の Strategist / Writer / Reviewer が参照する唯一の入力アーティファクトを作る。
    """

    def run(
        self,
        video_paths: list[str],
        run_id: str,
        notes: str = "",
        research_memo: Optional[dict] = None,
        persona_insights: Optional[dict] = None,
        price_signals_path: Optional[str] = None,
        competitor_patterns_path: Optional[str] = None,
        voice_snippets_path: Optional[str] = None,
        news_articles_path: Optional[str] = None,
    ) -> ResearchContext:
        from researcher.loaders.price_loader import load_price_signals
        from researcher.loaders.competitor_loader import load_competitor_patterns
        from researcher.loaders.voice_loader import load_voice_snippets
        from researcher.loaders.news_loader import load_news_articles
        from researcher.synthesizers.market_synthesizer import synthesize_market_context
        from researcher.synthesizers.persona_synthesizer import synthesize_from_voice_snippets

        # market_context（JSONファイルから基礎データ読み込み）
        mc: Optional[MarketContext] = None
        if research_memo:
            valid_keys = set(MarketContext.model_fields.keys())
            mc_data = {k: v for k, v in research_memo.items()
                       if not k.startswith("_") and k in valid_keys}
            mc = MarketContext(**mc_data)
            print(f"   📰 market_context: {len(mc.angle_candidates)}角度候補")

        # persona_insights（JSONファイルから基礎データ読み込み）
        pi: Optional[PersonaInsights] = None
        if persona_insights:
            valid_keys = set(PersonaInsights.model_fields.keys())
            pi_data = {k: v for k, v in persona_insights.items()
                       if not k.startswith("_") and k in valid_keys}
            pi = PersonaInsights(**pi_data)
            print(f"   📋 persona_insights: {len(pi.raw_audience_phrases)}フレーズ / "
                  f"{len(pi.common_fears)}恐れ / {len(pi.belief_candidates)}思い込み")

        # 外部データローダー（オプション）—— dict リストで受け取る
        price_signals: list[dict] = []
        if price_signals_path:
            price_signals = load_price_signals(price_signals_path)
            print(f"   💰 price_signals: {len(price_signals)}件")

        competitor_patterns: list[dict] = []
        if competitor_patterns_path:
            competitor_patterns = load_competitor_patterns(competitor_patterns_path)
            print(f"   🏪 competitor_patterns: {len(competitor_patterns)}件")

        voice_snippets: list[dict] = []
        if voice_snippets_path:
            voice_snippets = load_voice_snippets(voice_snippets_path)
            print(f"   🗣️  voice_snippets: {len(voice_snippets)}件")

        news_articles: list[dict] = []
        if news_articles_path:
            news_articles = load_news_articles(news_articles_path)
            print(f"   📰 news_articles: {len(news_articles)}件")

        # PersonaSynthesizer: voice_snippets → belief_candidates / common_fears（PersonaInsights）
        # NOTE: audience_stuck_points は MarketContext の責務 → market_synthesizer が担当する
        if voice_snippets:
            pi_dict = synthesize_from_voice_snippets(pi.model_dump() if pi else None, voice_snippets)
            valid_keys = set(PersonaInsights.model_fields.keys())
            pi = PersonaInsights(**{k: v for k, v in pi_dict.items() if k in valid_keys})

        # MarketSynthesizer: 価格・競合・ニュース・audience_stuck_points を MarketContext に統合
        if price_signals or competitor_patterns or voice_snippets or news_articles:
            mc_dict = synthesize_market_context(
                mc.model_dump() if mc else None,
                price_signals,
                competitor_patterns,
                voice_snippets=voice_snippets,
                news_articles=news_articles if news_articles else None,
            )
            valid_keys = set(MarketContext.model_fields.keys())
            mc = MarketContext(**{k: v for k, v in mc_dict.items() if k in valid_keys})

        # Gemini 動画観察（既存関数をそのまま利用）
        raw_obs = analyze_with_gemini(video_paths)
        raw_obs["run_id"] = run_id
        raw_obs["source_video"] = ", ".join(os.path.basename(p) for p in video_paths)
        observation = Observation(**raw_obs)

        return ResearchContext(
            run_id=run_id,
            source_videos=video_paths,
            primary_source_video=video_paths[0],
            notes=notes,
            observation=observation,
            market_context=mc,
            persona_insights=pi,
        )


def generate_narrative_with_claude(
    observation: Observation, notes: str,
    persona_insights: Optional[dict] = None,
    research_memo: Optional[dict] = None,
) -> tuple[NarrativePlan, Union[ScriptSkeleton, FlexibleSkeleton], list[MasterLine], str]:
    """
    4パスでナレーション主導構成を生成する（v3.2: master_lines導入）。
    戻り値: (NarrativePlan, ScriptSkeleton, list[MasterLine], timeline_notes_markdown)
    """
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません。")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    obs_json = observation.model_dump_json(indent=2)

    # ── Pass 1: 構成設計 + 感情設計（narrative_plan.json）───────────────────
    print("🧠 Claude: 構成設計 + 感情設計中（1/4）...")
    if research_memo:
        parts = []
        if research_memo.get("angle_candidates"):
            parts.append(f"{len(research_memo['angle_candidates'])}角度候補")
        if research_memo.get("price_signals"):
            parts.append(f"相場{len(research_memo['price_signals'])}件")
        if research_memo.get("competitor_patterns"):
            parts.append(f"競合{len(research_memo['competitor_patterns'])}件")
        if research_memo.get("news_articles"):
            parts.append(f"ニュース{len(research_memo['news_articles'])}件")
        if research_memo.get("audience_stuck_points"):
            parts.append(f"障壁{len(research_memo['audience_stuck_points'])}件")
        print(f"   📰 market_context: {' / '.join(parts) or 'テキストのみ'}")
    if persona_insights:
        print(f"   📋 persona_insights: {len(persona_insights.get('raw_audience_phrases', []))}フレーズ / "
              f"{len(persona_insights.get('common_fears', []))}恐れ / "
              f"{len(persona_insights.get('belief_candidates', []))}思い込み")
    user_prompt = CLAUDE_NARRATIVE_PLAN_PROMPT.format(
        observations=obs_json,
        notes=notes or "なし",
        research_memo_section=_build_research_memo_section(research_memo),
        persona_insights_section=_build_persona_insights_section(persona_insights),
    )
    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=CLAUDE_NARRATIVE_SYSTEM + "\n\n【重要】JSONのみを返してください。{ で始まり } で終わること。",
        messages=[{"role": "user", "content": user_prompt}],
    )
    narrative_dict = _parse_json_obj(msg.content[0].text, "Pass1:NarrativePlan")
    plan = NarrativePlan(**narrative_dict)
    dur = plan.recommended_duration_range
    emotional_hook = plan.emotional_design.emotional_hook_type if plan.emotional_design else "未設定"
    print(f"   ✓ 構成設計完了（{plan.content_category} / {dur.min_sec}〜{dur.max_sec}秒 / {len(plan.sections)}セクション）")
    print(f"   ✓ 感情設計完了（フック型: {emotional_hook} / mode: {plan.content_mode} / arc: {plan.narrative_arc}）")

    # ── Pass 1.5: 台本骨格生成（script_skeleton.json）───────────────────────
    print("🧠 Claude: 台本骨格生成中（2/4）...")
    emotional_design_dict = narrative_dict.get("emotional_design", {})
    # 観察結果のサマリー（骨格生成に必要な事実のみ渡す）
    obs_summary = {
        "product_family_guess": observation.product_family_guess,
        "visible_color": observation.visible_color,
        "visible_hardware": observation.visible_hardware,
        "visible_damage": observation.visible_damage,
        "accessories_detected": observation.accessories_detected,
        "accessories_missing_or_unconfirmed": observation.accessories_missing_or_unconfirmed,
        "evidence_notes": observation.evidence_notes,
    }
    benefit_design_dict = emotional_design_dict.get("benefit_design", {})

    if plan.content_mode == "conversion":
        # conversion: 既存のScriptSkeleton生成（変更なし）
        skeleton_prompt = CLAUDE_SKELETON_PROMPT.format(
            emotional_design=json.dumps(emotional_design_dict, ensure_ascii=False, indent=2),
            benefit_design=json.dumps(benefit_design_dict, ensure_ascii=False, indent=2),
            observations_summary=json.dumps(obs_summary, ensure_ascii=False, indent=2),
            persona_insights_section=_build_skeleton_insights_section(persona_insights),
        )
        msg15 = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=CLAUDE_NARRATIVE_SYSTEM + "\n\n【重要】JSONのみを返してください。{ で始まり } で終わること。",
            messages=[{"role": "user", "content": skeleton_prompt}],
        )
        skeleton_dict = _parse_json_obj(msg15.content[0].text, "Pass1.5:ScriptSkeleton")
        skeleton = ScriptSkeleton(**skeleton_dict)
        print(f"   ✓ 台本骨格生成完了（hook: {skeleton.hook_line[:20]}...）")
    else:
        # retention / insight / story: FlexibleSkeleton生成
        flexible_prompt = CLAUDE_SKELETON_FLEXIBLE_PROMPT.format(
            content_mode=plan.content_mode,
            narrative_arc=plan.narrative_arc,
            ending_type=plan.ending_type,
            emotional_design=json.dumps(emotional_design_dict, ensure_ascii=False, indent=2),
            benefit_design=json.dumps(benefit_design_dict, ensure_ascii=False, indent=2),
            observations_summary=json.dumps(obs_summary, ensure_ascii=False, indent=2),
            persona_insights_section=_build_skeleton_insights_section(persona_insights),
        )
        msg15 = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            system=CLAUDE_NARRATIVE_SYSTEM + "\n\n【重要】JSONのみを返してください。{ で始まり } で終わること。",
            messages=[{"role": "user", "content": flexible_prompt}],
        )
        skeleton_dict = _parse_json_obj(msg15.content[0].text, "Pass1.5:FlexibleSkeleton")
        skeleton = FlexibleSkeleton(**skeleton_dict)  # Union型として返す
        first_sec = skeleton.sections[0] if skeleton.sections else None
        first_label = f"{first_sec.purpose}: {first_sec.line[:20]}" if first_sec else "..."
        print(f"   ✓ 台本骨格生成完了（mode: {plan.content_mode} / {first_label}...）")

    # ── Pass 2: master_lines 生成（骨格→統合行）────────────────────────────
    print("🧠 Claude: master_lines生成中（3/5）...")
    dur = plan.recommended_duration_range
    master_prompt = CLAUDE_MASTER_LINES_PROMPT.format(
        script_skeleton=json.dumps(skeleton_dict, ensure_ascii=False, indent=2),
        observations_summary=json.dumps(obs_summary, ensure_ascii=False, indent=2),
        min_sec=dur.min_sec,
        max_sec=dur.max_sec,
        content_mode=plan.content_mode,
        ending_type=plan.ending_type,
    )
    msg2 = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=CLAUDE_NARRATIVE_SYSTEM + "\n\n【重要】JSON配列のみを返してください。[ で始まり ] で終わること。",
        messages=[{"role": "user", "content": master_prompt}],
    )
    master_list = _parse_json_arr(msg2.content[0].text, "Pass2:MasterLines")
    # estimated_duration を文字数÷5.5 で上書き（Claudeの過大見積もりを防ぐ）
    for m in master_list:
        m["estimated_duration"] = round(len(m.get("narration_line", "")) / 5.5, 1)
    total_est = sum(m["estimated_duration"] for m in master_list)
    print(f"   ✓ master_lines生成完了（{len(master_list)}行 / 推定{total_est:.0f}秒）")

    # ── Pass 2.5: display_units 生成（テロップ表示単位）─────────────────────
    print("🧠 Claude: display_units生成中（4/5）...")
    display_input = [
        {
            "cue_id": m["cue_id"],
            "text_line": m.get("text_line", ""),
            "narration_line": m.get("narration_line", ""),
        }
        for m in master_list
    ]
    display_prompt = CLAUDE_DISPLAY_UNITS_PROMPT.format(
        master_lines=json.dumps(display_input, ensure_ascii=False, indent=2)
    )
    msg25 = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system="あなたはテロップ表示単位の生成専門家です。\n\n【重要】JSON配列のみを返してください。[ で始まり ] で終わること。",
        messages=[{"role": "user", "content": display_prompt}],
    )
    display_list = _parse_json_arr(msg25.content[0].text, "Pass2.5:DisplayUnits")
    display_map = {d["cue_id"]: d.get("display_units", []) for d in display_list}
    for m in master_list:
        m["display_units"] = _fix_display_units(display_map.get(m["cue_id"], []))
    print(f"   ✓ display_units生成完了（{len(display_list)}行）")

    master_lines = [MasterLine(**m) for m in master_list]

    # ── バリデーション（v3.4）─────────────────────────────────────────────────
    warnings = validate_master_lines(master_lines, plan.emotional_design)
    if warnings:
        print(f"\n   ⚠ バリデーション警告: {len(warnings)}件")
        for w in warnings:
            print(f"     [{w['cue_id']:02d}] {w['purpose']:<12} [{w['rule']}]")
            print(f"          対象: {w['narration_line']}")
            print(f"          理由: {w['reason']}")
            print(f"          改善: {w['suggestion']}")
    else:
        print("   ✓ バリデーション: 警告なし")

    # ── Pass 3: Premiereタイムラインノート生成 ────────────────────────────
    print("🧠 Claude: Premiereガイド生成中（5/5）...")
    timeline_prompt = CLAUDE_TIMELINE_NOTES_PROMPT.format(
        master_lines=json.dumps(master_list, ensure_ascii=False, indent=2),
    )
    msg3 = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system=CLAUDE_NARRATIVE_SYSTEM,
        messages=[{"role": "user", "content": timeline_prompt}],
    )
    timeline_md = msg3.content[0].text.strip()
    print("   ✓ Premiereガイド生成完了")

    return plan, skeleton, master_lines, timeline_md


def generate_narrative_from_research_context(
    research_context: ResearchContext,
) -> tuple[NarrativePlan, Union[ScriptSkeleton, FlexibleSkeleton], list[MasterLine], str]:
    """
    ResearchContext を入力として受け取り、既存の generate_narrative_with_claude() に委譲する。
    Researcher 切り出し後の新規呼び出しエントリーポイント。
    既存の generate_narrative_with_claude() は移行期は残し、こちらからラップ経由で呼ぶ。
    """
    return generate_narrative_with_claude(
        observation=research_context.observation,
        notes=research_context.notes,
        persona_insights=(
            research_context.persona_insights.model_dump()
            if research_context.persona_insights else None
        ),
        research_memo=(
            research_context.market_context.model_dump()
            if research_context.market_context else None
        ),
    )


def _parse_json_obj(raw: str, label: str) -> dict:
    """Claude応答からJSONオブジェクトを抽出する"""
    raw = raw.strip()
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("{"):
                raw = part
                break
    start, end = raw.find("{"), raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude: JSON解析失敗 ({label}) → {e}\n{raw[:400]}")


def _parse_json_arr(raw: str, label: str) -> list:
    """Claude応答からJSON配列を抽出する"""
    raw = raw.strip()
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("["):
                raw = part
                break
    start, end = raw.find("["), raw.rfind("]") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Claude: JSON配列解析失敗 ({label}) → {e}\n{raw[:400]}")


def validate_master_lines(
    master_lines: list[MasterLine],
    emotional_design: Optional[EmotionalDesign] = None,
) -> list[dict]:
    """
    生成後バリデーション（v3.3）
    各 master_line に対して10項目チェックし、warnings リストを返す。
    """
    warnings = []

    # ── 前処理（ループ外・全体集計）──────────────────────────────────────────

    # Rule 12 前処理: hook / proof セクション全体でブランド名が1行でも含まれるか判定
    BRAND_KW = ["エルメス", "ピコタン", "ケリー", "バーキン", "コンスタンス", "エブリン", "ガーデンパーティ", "Hermes"]
    hook_lines_all_text = " ".join(ml.narration_line for ml in master_lines if ml.purpose == "hook")
    hook_has_brand = any(kw in hook_lines_all_text for kw in BRAND_KW)
    proof_lines_all_text = " ".join(ml.narration_line for ml in master_lines if ml.purpose == "proof")
    proof_has_brand = any(kw in proof_lines_all_text for kw in BRAND_KW)

    # Rule 23: 総行数チェック（14行以上 = warning / 13行 = soft warning）
    total_lines = len(master_lines)
    if total_lines >= 14:
        warnings.append({
            "cue_id": 0,
            "purpose": "全体",
            "narration_line": f"総行数: {total_lines}行",
            "rule": "総行数超過（NG）",
            "reason": f"{total_lines}行（上限: 12行目標 / 14行以上はNG）",
            "suggestion": "shift の2行目 → proof の3行目 → relief の2行目の順で優先して削ってください",
        })
    elif total_lines == 13:
        warnings.append({
            "cue_id": 0,
            "purpose": "全体",
            "narration_line": f"総行数: {total_lines}行",
            "rule": "総行数やや多い（圧縮推奨）",
            "reason": f"{total_lines}行（目標11〜12行 / 13行は例外扱い）",
            "suggestion": "削れる行がないか確認してください（shift 2行目 / relief 2行目が候補）",
        })

    # Rule 24: 推定尺チェック（54秒以上 = warning / 51〜53秒 = soft warning）
    total_sec = sum(ml.estimated_duration for ml in master_lines)
    if total_sec >= 54:
        warnings.append({
            "cue_id": 0,
            "purpose": "全体",
            "narration_line": f"推定尺: {total_sec:.0f}秒",
            "rule": "推定尺超過（圧縮対象）",
            "reason": f"推定{total_sec:.0f}秒（54秒以上は圧縮対象）",
            "suggestion": "行を削るか文字数を減らして50秒以内を目指してください",
        })
    elif total_sec > 50:
        warnings.append({
            "cue_id": 0,
            "purpose": "全体",
            "narration_line": f"推定尺: {total_sec:.0f}秒",
            "rule": "推定尺やや長い（要確認）",
            "reason": f"推定{total_sec:.0f}秒（目標50秒以内）",
            "suggestion": "誤差範囲ですが、削れる行があれば圧縮を検討してください",
        })

    # Rule 25: shift 行数チェック（2行以上で warning）
    shift_lines = [ml for ml in master_lines if ml.purpose == "shift"]
    if len(shift_lines) > 1:
        warnings.append({
            "cue_id": shift_lines[-1].cue_id,
            "purpose": "shift",
            "narration_line": shift_lines[-1].narration_line,
            "rule": "shift 行数超過",
            "reason": f"shift が{len(shift_lines)}行（原則1行）",
            "suggestion": "2行目を1行目に統合するか削ってください",
        })

    # Rule 26: proof 行数チェック（3行以上で warning）
    proof_lines = [ml for ml in master_lines if ml.purpose == "proof"]
    if len(proof_lines) > 2:
        warnings.append({
            "cue_id": proof_lines[-1].cue_id,
            "purpose": "proof",
            "narration_line": proof_lines[-1].narration_line,
            "rule": "proof 行数超過",
            "reason": f"proof が{len(proof_lines)}行（上限2行）",
            "suggestion": "3行目を2行目に統合するか削ってください",
        })

    # Rule 27: relief 行数チェック（2行以上で warning）
    relief_lines = [ml for ml in master_lines if ml.purpose == "relief"]
    if len(relief_lines) > 1:
        warnings.append({
            "cue_id": relief_lines[-1].cue_id,
            "purpose": "relief",
            "narration_line": relief_lines[-1].narration_line,
            "rule": "relief 行数超過",
            "reason": f"relief が{len(relief_lines)}行（原則1行）",
            "suggestion": "「まだ決めていなくても、大丈夫です。」の1行に統合してください",
        })

    for ml in master_lines:
        text = ml.narration_line

        # 1a. 30文字超（全セクション共通 / 必須分割）
        if len(text) > 30:
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "長すぎる行（必須分割）",
                "reason": f"{len(text)}文字（上限30文字）",
                "suggestion": "2行に分割してください",
            })

        # 1b. 22文字超（pain / benefit_bridge / relief は22文字以内が目標）
        COMPACT_PURPOSES = {"pain", "benefit_bridge", "relief"}
        if ml.purpose in COMPACT_PURPOSES and 22 < len(text) <= 30:
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "行が長い（圧縮推奨）",
                "reason": f"{len(text)}文字（{ml.purpose} は22文字以内を目標）",
                "suggestion": "感情単位で分割するか、説明句を削って短くしてください",
            })

        # 1c. CTA は推奨20文字以内 / 許容24文字 / 25文字以上で警告
        if ml.purpose == "cta" and len(text) >= 25:
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "CTA が長い（分割推奨）",
                "reason": f"{len(text)}文字（推奨20文字以内 / 許容24文字 / 25文字以上は分割）",
                "suggestion": "「写真3枚から〜」「LINEで〜だけでもどうぞ。」程度に収めてください",
            })

        # 2. ことがあります
        if "ことがあります" in text:
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "説明資料調フレーズ",
                "reason": "「ことがあります」は資料調",
                "suggestion": "「〜しています」「〜します」に変換",
            })

        # 3. とされています
        if "とされています" in text:
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "説明資料調フレーズ",
                "reason": "「とされています」は資料調",
                "suggestion": "「〜なんです」「〜します」に変換",
            })

        # 4. が重要です / 重要です
        if "重要です" in text:
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "説明資料調フレーズ",
                "reason": "「重要です」は説明資料調",
                "suggestion": "具体的な言い換えか削除",
            })

        # 5. 読点終わり（未完文）
        if text.rstrip().endswith("、"):
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "読点終わり（未完文）",
                "reason": "読点で終わると音声が途切れて不自然",
                "suggestion": "文を完結させるか、次の行と合流",
            })

        # 6. hook に問いかけも独り言型もなし
        # 独り言型 / 回想型（〜のに / 〜はずなのに / 〜たまま / 〜つもり / 〜ていた）は問いかけなしでも許容
        if ml.purpose == "hook":
            MONOLOGUE_ENDINGS = ["のに", "のに。", "たままで", "たままで。", "のつもりだったのに", "ていた。", "ている。", "たまま。", "気がして", "気がして。"]
            is_question = "？" in text or text.rstrip("。").endswith("か")
            is_monologue = any(text.rstrip("。").endswith(e.rstrip("。")) for e in MONOLOGUE_ENDINGS)
            if not is_question and not is_monologue:
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "hook に問いかけも独り言型もなし",
                    "reason": "hook は問いかけ型（〜ていませんか？）または独り言型（〜のに / 〜たままで）のいずれかが必要",
                    "suggestion": "「〜ていませんか？」または「〜はずなのに。」「〜のつもりだったのに。」に変換",
                })

        # 7. pain に停滞感なし
        if ml.purpose == "pain":
            stagnation_kw = [
                "後回し", "迷", "止まって", "踏み出", "相談", "気まず", "動けない", "しづらい", "不安",
                "罪悪感", "眠って", "出番", "ずっと", "見て見ぬふり",  # 先延ばし・罪悪感・物への感情
                "決めていない", "連絡していいのか", "連絡して",  # 気まずさ・躊躇
            ]
            if not any(kw in text for kw in stagnation_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "pain に停滞感なし",
                    "reason": "hidden_fear / embarrassment_trigger の要素が薄い",
                    "suggestion": "「後回し」「気まずい」「出番がなくなった」「ずっと眠ったまま」などの停滞感を入れる",
                })

        # 8. shift が部分否定 / 認識の分離になっていない
        if ml.purpose == "shift":
            partial_neg_kw = [
                "でも", "だけでは", "だけでなく", "そこだけ", "ではなく", "ばかり",
                "別のこと", "違います", "異なります", "そうではなく", "ではありません",
            ]
            if not any(kw in text for kw in partial_neg_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "shift が思い込みをズラせていない",
                    "reason": "部分否定（〜だけではない）または認識の分離（〜と〜は別のこと）が含まれていない可能性",
                    "suggestion": "「〜だけではありません」または「〜と〜は別のことです」形式に変換",
                })

        # 9. relief に安心ワードなし
        if ml.purpose == "relief":
            reassurance_kw = ["大丈夫", "決めなくて", "確認だけ", "なくてもいい", "だけでも"]
            if not any(kw in text for kw in reassurance_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "relief に安心ワードなし",
                    "reason": "「大丈夫」などの具体的安心表現が不足",
                    "suggestion": "「大丈夫です」「決めなくていい」などを入れる",
                })

        # 10. CTA が命令形
        if ml.purpose == "cta":
            command_patterns = ["してください", "送ってください", "ご連絡ください", "お問い合わせください", "ご確認ください"]
            if any(p in text for p in command_patterns):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "CTA が命令形",
                    "reason": "命令形はハードルを上げる",
                    "suggestion": "「〜からどうぞ」「〜だけでOKです」に変換",
                })

        # 28. CTA に煽りフレーズ（urgency / scarcity）
        if ml.purpose == "cta":
            urgency_kw = ["今すぐ", "今だけ", "急いで", "期間限定", "チャンス", "逃さないで", "今が売り時", "早い者勝ち"]
            if any(kw in text for kw in urgency_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "cta に煽りフレーズ",
                    "reason": "urgency / scarcity 系の表現がブランドスタンス（急がせない）に反する",
                    "suggestion": "「写真3枚から〜」「まだ決めていなくても〜」など低圧力の誘い方に変換",
                })

        # 29. CTA が申込型に寄っている（相談入口ではなく売却申込になっている）
        if ml.purpose == "cta":
            apply_kw = ["お申し込みください", "ご予約ください", "来店してください", "お電話ください", "今すぐ査定へ", "店頭まで", "予約はこちら"]
            if any(kw in text for kw in apply_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "cta が申込型に寄っている",
                    "reason": "来店・電話・予約・申込への誘導になっている。CTAは相場確認・相談の入口であるべき",
                    "suggestion": "「LINEで相場確認だけでもどうぞ」「写真3枚からお気軽に」に変換",
                })

        # 11. benefit_bridge に「得」フレーズなし
        if ml.purpose == "benefit_bridge":
            benefit_kw = [
                "分かる", "分かり", "できる", "できます", "手に入る", "得られる", "判断", "整理", "持てる", "確認",
                "決められ", "選べ", "判断でき", "選びやすく", "やすくなり",  # 自己決定・選択系
            ]
            if not any(kw in text for kw in benefit_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "benefit_bridge に得フレーズなし",
                    "reason": "「分かる」「できる」「決められる」「選べる」「判断」などの利益表現が不足",
                    "suggestion": "「だから○○が分かります」「つまり○○できます」形式に変換",
                })

        # 12. hook/proof でブランド名・商品名が欠落している（警告のみ）
        # hook は「1行目=感情停滞点 / 2行目=ブランド名」の分担構成を許容するため
        # hook セクション全体で1行でもブランド名があればOK（hook_has_brand は前処理済み）
        if ml.purpose == "hook" and not hook_has_brand and ml.cue_id == min(
            m.cue_id for m in master_lines if m.purpose == "hook"
        ):
            # hook セクションの先頭行にのみ1回だけ警告を出す
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "ブランド名・商品名なし（hook セクション全体）",
                "reason": "hook セクションのどの行にもブランド名または商品名がない（推奨）",
                "suggestion": "hook のいずれかの行にエルメス / ピコタン / ケリーなどを自然に入れると具体性が上がります",
            })
        elif ml.purpose == "proof" and not proof_has_brand and ml.cue_id == min(
            m.cue_id for m in master_lines if m.purpose == "proof"
        ):
            # proof セクションの先頭行にのみ1回だけ警告を出す（セクション単位判定）
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "ブランド名・商品名なし（proof セクション全体）",
                "reason": "proof セクションのどの行にもブランド名または商品名がない（推奨）",
                "suggestion": "proof のいずれかの行にエルメス / ピコタン / ケリーなどを自然に入れると具体性が上がります",
            })

        # 13. benefit_bridge に安心系ワードが入っている（relief との混同）
        if ml.purpose == "benefit_bridge":
            relief_leak_kw = ["大丈夫", "安心", "構いません", "問題ありません"]
            if any(kw in text for kw in relief_leak_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "benefit_bridge に安心系ワード",
                    "reason": "「大丈夫」「安心」系は relief の役割。benefit_bridge が安心着地になっている",
                    "suggestion": "「だから○○が分かります」「つまり○○できます」形式で benefit を言い切る",
                })

        # 14. text_line と narration_line の意味乖離チェック
        #     hook/pain/shift/relief/cta の一致度を文字重複率で検査
        STRICT_PURPOSES = {"hook", "pain", "shift", "relief", "cta"}
        if ml.purpose in STRICT_PURPOSES:
            overlap = _text_overlap_ratio(ml.narration_line, ml.text_line)
            if overlap < 0.45:
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "text_line 乖離",
                    "reason": f"narration_line との文字重複率 {overlap:.0%}（基準: 45%以上）\n          text_line: {ml.text_line}",
                    "suggestion": "narration_line の核フレーズをそのまま短縮してください",
                })

        # 15. display_units が空（narration_line があるのに未生成）
        if ml.narration_line and not ml.display_units:
            warnings.append({
                "cue_id": ml.cue_id,
                "purpose": ml.purpose,
                "narration_line": text,
                "rule": "display_units 空",
                "reason": "narration_line があるのに display_units が生成されていない",
                "suggestion": "Pass2.5 が正常に動作しているか確認してください",
            })

        # 16. display_units に13文字超の要素がある
        for unit in ml.display_units:
            if len(unit) > 12:
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "display_unit 長すぎる",
                    "reason": f"「{unit}」が{len(unit)}文字（上限12文字）",
                    "suggestion": "13文字以上の要素をさらに分割してください",
                })

        # 17. display_units に2文字以下の要素がある（断片化しすぎ）
        for unit in ml.display_units:
            if len(unit) <= 2:
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "display_unit 短すぎる",
                    "reason": f"「{unit}」が{len(unit)}文字以下（意味を持たない断片の可能性）",
                    "suggestion": "前後の要素と結合してください",
                })

        # 18. display_units の要素が助詞で終わっている
        PARTICLE_ENDINGS = ["が", "は", "を", "で", "へ", "に", "の", "と", "も", "から", "より"]
        for unit in ml.display_units:
            for p in PARTICLE_ENDINGS:
                if unit.endswith(p) and len(unit) > 1:
                    warnings.append({
                        "cue_id": ml.cue_id,
                        "purpose": ml.purpose,
                        "narration_line": text,
                        "rule": "display_unit 助詞終わり",
                        "reason": f"「{unit}」が助詞「{p}」で終わっている（断片として不自然）",
                        "suggestion": "次の要素と結合するか、助詞を削除してください",
                    })
                    break

        # 19. hook に雑学・情報暴露フレーズ（感情停滞点でない hook の検出）
        if ml.purpose == "hook":
            trivia_kw = ["実は", "知っておきたい", "知らないと", "秘密", "左右する", "査定額を", "ポイントは", "理由を", "真実"]
            if any(kw in text for kw in trivia_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "hook に雑学・情報暴露フレーズ",
                    "reason": "感情停滞点でなく知識提示型フックになっている",
                    "suggestion": "「売ると決めないまま〜」「気まずくて〜」「クローゼットに〜」など感情起点に変換",
                })

        # 20. hook が proof 的な開始・終了（教育型 hook の検出）
        if ml.purpose == "hook":
            proof_end_kw = ["を見ています", "を確認しています", "ております"]
            proof_start_kw = ["付属品", "査定額", "相場は"]
            if any(text.endswith(kw) for kw in proof_end_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "hook が proof 的終わり方",
                    "reason": "「〜を見ています」で終わる hook は proof 的。感情を引き出せていない",
                    "suggestion": "問いかけ形式（〜ていませんか？）または独り言形式に変換",
                })
            elif any(text.startswith(kw) for kw in proof_start_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "hook が教育型開始",
                    "reason": f"「{text[:6]}…」で始まる hook は教育・proof 的な開始になっている",
                    "suggestion": "感情停滞点（迷い・気まずさ・先延ばし）から始める表現に変換",
                })

        # 22. pain に説明接続句が入っている（感情単位で切れていない）
        if ml.purpose == "pain":
            explain_kw = ["と考えると", "と思われたら", "なぜなら", "ということ", "という気持ち", "せいで", "ためか"]
            if any(kw in text for kw in explain_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "pain に説明接続句",
                    "reason": "「と考えると」「と思われたら」などの説明句が含まれている。pain は感情1語で切る",
                    "suggestion": "接続句を削って感情単位で1行にしてください（例: 「気まずい。」「断りにくい。」）",
                })

        # 21. benefit_bridge に価格煽りフレーズ（「高く売れる」主語の benefit 検出）
        if ml.purpose == "benefit_bridge":
            price_hype_kw = ["高く売れ", "高額", "お得に売", "損をしない", "高値", "万円で売"]
            if any(kw in text for kw in price_hype_kw):
                warnings.append({
                    "cue_id": ml.cue_id,
                    "purpose": ml.purpose,
                    "narration_line": text,
                    "rule": "benefit_bridge に価格煽りフレーズ",
                    "reason": "「高く売れる」が主語になっている。benefit は判断整理・納得が主語であるべき",
                    "suggestion": "「売るかどうかを自分で決められる」「判断軸が持てる」に変換",
                })

    return warnings


def _fix_display_units(units: list[str]) -> list[str]:
    """
    Pass2.5 生成後の display_units を後処理する（限定的ルールベース）。
    - 末尾が単文字助詞の断片: 次要素と結合（≤12字）または助詞を削る
    - 2字以下の断片: 次要素と結合
    接続助詞（ので/のに等）や複合助詞はそのまま通す（NLP不要範囲に限定）。
    """
    STRIP_PARTICLES = {"が", "は", "を", "で", "へ", "に", "の", "と", "も"}

    result: list[str] = []
    i = 0
    while i < len(units):
        unit = units[i]
        has_next = i + 1 < len(units)

        # 2字以下 → 次と結合
        if len(unit) <= 2 and has_next:
            merged = (unit + units[i + 1])[:12]
            result.append(merged)
            i += 2
            continue

        # 末尾が単文字助詞
        if unit and unit[-1] in STRIP_PARTICLES:
            if has_next:
                merged = unit + units[i + 1]
                if len(merged) <= 12:
                    # 結合後も助詞終わりなら末尾の助詞をさらに削る
                    if merged[-1] in STRIP_PARTICLES:
                        stripped = merged[:-1]
                        result.append(stripped if len(stripped) >= 3 else merged)
                    else:
                        result.append(merged)
                    i += 2
                    continue
            # 結合できない → 助詞を削る
            stripped = unit[:-1]
            result.append(stripped if len(stripped) >= 3 else unit)
            i += 1
            continue

        result.append(unit)
        i += 1

    return result


def _text_overlap_ratio(narration: str, text: str) -> float:
    """
    narration_line と text_line の文字重複率を返す（0.0〜1.0）。
    助詞・記号・空白を除いた実質文字で判定。
    text_line 側の文字が narration_line に何割含まれるかを計算する。
    """
    IGNORE = set("をはがのにでとももやへからもよねよーっ、。？！「」【】・　 \t\n")
    n_chars = [c for c in narration if c not in IGNORE]
    t_chars = [c for c in text if c not in IGNORE]
    if not t_chars:
        return 1.0  # text_line が空なら警告不要
    n_set = set(n_chars)
    matched = sum(1 for c in t_chars if c in n_set)
    return matched / len(t_chars)


def check_forbidden_narrative(plan: NarrativePlan, master_lines: list[MasterLine]) -> list[str]:
    """ナレーションプランと全master_linesの禁止表現チェック"""
    text = " ".join([
        plan.selected_hook,
        plan.caption,
        " ".join(ml.narration_line for ml in master_lines),
    ])
    found = [expr for expr in FORBIDDEN_EXPRESSIONS if expr in text]
    found.extend(plan.forbidden_claim_check)
    return list(set(found))


def save_narrative_outputs(
    run_id: str,
    obs: Observation,
    plan: NarrativePlan,
    skeleton: Union[ScriptSkeleton, FlexibleSkeleton],
    master_lines: list[MasterLine],
    timeline_md: str,
    output_dir: pathlib.Path,
) -> list[str]:
    """ナレーション主導フローの成果物を保存する"""
    import csv as _csv
    output_dir.mkdir(parents=True, exist_ok=True)
    files = []

    # observations.json
    p = output_dir / "observations.json"
    p.write_text(obs.model_dump_json(indent=2), encoding="utf-8")
    files.append(str(p))

    # emotional_design.json（感情設計）
    if plan.emotional_design:
        p = output_dir / "emotional_design.json"
        p.write_text(plan.emotional_design.model_dump_json(indent=2), encoding="utf-8")
        files.append(str(p))

    # script_skeleton.json（台本骨格）
    p = output_dir / "script_skeleton.json"
    p.write_text(skeleton.model_dump_json(indent=2), encoding="utf-8")
    files.append(str(p))

    # master_lines.json（ナレーション・テキスト統合行）
    p = output_dir / "master_lines.json"
    p.write_text(
        json.dumps([ml.model_dump() for ml in master_lines], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    files.append(str(p))

    # narrative_plan.json（中心成果物）
    p = output_dir / "narrative_plan.json"
    p.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    files.append(str(p))

    # narration_script.txt（AivisSpeechに渡す完成稿 / narration_line から生成）
    dur = plan.recommended_duration_range
    total_est = sum(ml.estimated_duration for ml in master_lines)
    script_lines = [
        "# ナレーション原稿",
        f"# カテゴリ: {plan.content_category}",
        f"# モード: {plan.content_mode} / arc: {plan.narrative_arc} / ending: {plan.ending_type}",
        f"# 推奨尺: {dur.min_sec}〜{dur.max_sec}秒（推定: {total_est:.0f}秒）",
        f"# フォーミュラ: {plan.narrative_formula_type}",
        "",
    ]
    current_section = ""
    for ml in master_lines:
        if ml.section_name != current_section:
            current_section = ml.section_name
            script_lines.append(f"\n## {current_section}")
        warn = " ⚠️" if ml.evidence_confidence in ("low", "unconfirmed") else ""
        script_lines.append(f"{ml.cue_id:02d}. {ml.narration_line}{warn}")
    p = output_dir / "narration_script.txt"
    p.write_text("\n".join(script_lines), encoding="utf-8")
    files.append(str(p))

    # narration_cues.csv（後方互換: generate_narration_audio.py 用 / master_lines から派生）
    p = output_dir / "narration_cues.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as f:
        writer = _csv.DictWriter(f, fieldnames=[
            "cue_id", "section_name", "line_text",
            "estimated_duration_sec", "source_file", "source_timecode",
            "evidence_confidence", "display_units",
        ])
        writer.writeheader()
        for ml in master_lines:
            writer.writerow({
                "cue_id": ml.cue_id,
                "section_name": ml.section_name,
                "line_text": ml.narration_line,
                "estimated_duration_sec": ml.estimated_duration,
                "source_file": ml.source_file,
                "source_timecode": ml.source_timecode,
                "evidence_confidence": ml.evidence_confidence,
                "display_units": "|".join(ml.display_units),
            })
    files.append(str(p))

    # timeline_notes.md（Premiere Pro編集ガイド）
    p = output_dir / "timeline_notes.md"
    p.write_text(timeline_md, encoding="utf-8")
    files.append(str(p))

    # caption.txt
    p = output_dir / "caption.txt"
    p.write_text(plan.caption, encoding="utf-8")
    files.append(str(p))

    # strategy.json（manage_results.py との互換用・最小版）
    formula_to_hook = {
        "不安解消型": "loss_aversion",
        "教育型": "information_gap",
        "証拠提示型": "unexpected",
    }
    compat = {
        "selected_hook": plan.selected_hook,
        "hook_candidates": [{
            "hook_type": formula_to_hook.get(plan.narrative_formula_type, "information_gap"),
            "text": plan.selected_hook,
        }],
        "addressed_anxiety": plan.addressed_anxiety,
        "content_category": plan.content_category,
        "caption": plan.caption,
        "_note": "manage_results.py互換用の簡略版。詳細はnarrative_plan.jsonを参照。",
    }
    p = output_dir / "strategy.json"
    p.write_text(json.dumps(compat, ensure_ascii=False, indent=2), encoding="utf-8")
    files.append(str(p))

    return files


# ── 禁止表現チェック ───────────────────────────────────────────────────────────

def check_forbidden(strategy: StrategyPlan) -> list[str]:
    found = []
    text_to_check = (
        strategy.selected_hook + " " +
        strategy.caption + " " +
        " ".join(seg.subtitle_text for seg in strategy.edit_plan.segments)
    )
    for expr in FORBIDDEN_EXPRESSIONS:
        if expr in text_to_check:
            found.append(expr)
    found.extend(strategy.forbidden_claim_check)
    return list(set(found))


# ── 出力ファイル生成 ───────────────────────────────────────────────────────────

def save_outputs(run_id: str, obs: Observation, strategy: StrategyPlan, output_dir: pathlib.Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files = []

    # observations.json
    p = output_dir / "observations.json"
    p.write_text(obs.model_dump_json(indent=2), encoding="utf-8")
    files.append(str(p))

    # strategy.json
    p = output_dir / "strategy.json"
    p.write_text(strategy.model_dump_json(indent=2), encoding="utf-8")
    files.append(str(p))

    # edit_plan.json
    p = output_dir / "edit_plan.json"
    p.write_text(strategy.edit_plan.model_dump_json(indent=2), encoding="utf-8")
    files.append(str(p))

    # caption.txt
    p = output_dir / "caption.txt"
    p.write_text(strategy.caption, encoding="utf-8")
    files.append(str(p))

    # capcut_steps.md
    p = output_dir / "capcut_steps.md"
    p.write_text(strategy.capcut_steps, encoding="utf-8")
    files.append(str(p))

    return files


def save_review_md(obs: Observation, reasons: list[str], output_dir: pathlib.Path) -> str:
    lines = ["# 人レビュー必要\n"]
    lines.append(f"**動画**: {obs.source_video}\n")
    lines.append("## 止めた理由\n")
    for r in reasons:
        lines.append(f"- {r}")
    lines.append("\n## 確認が必要な点\n")
    if obs.uncertainty_flags:
        lines.append("### 不確実な情報")
        for f in obs.uncertainty_flags:
            lines.append(f"- {f}")
    if obs.angles_missing:
        lines.append(f"\n### 撮影不足のアングル")
        for a in obs.angles_missing:
            lines.append(f"- {a}")
    lines.append(f"\n## Gemini観察サマリー\n{obs.evidence_notes}")
    p = output_dir / "review.md"
    p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


def save_run_log(result: RunResult, output_dir: pathlib.Path):
    p = output_dir / "run_log.json"
    p.write_text(result.model_dump_json(indent=2), encoding="utf-8")


def print_script_review_summary(
    master_lines: list[MasterLine],
    plan: NarrativePlan,
    output_dir: pathlib.Path,
) -> None:
    """
    台本確認ゲート: 人間レビュー用サマリーをコンソールに表示する。
    opening / tension / shift / cta の行を抜き出し、バリデーション警告と統計を添えて出力する。
    """
    warnings = validate_master_lines(master_lines, plan.emotional_design)
    warn_ids = {w["cue_id"] for w in warnings}

    dur = plan.recommended_duration_range
    total_est = sum(ml.estimated_duration for ml in master_lines)
    long_count = sum(1 for ml in master_lines if len(ml.narration_line) > 30)

    sep = "━" * 54
    print(f"\n{sep}")
    print(f"📋 台本確認ゲート — 人間レビュー待ち")
    print(sep)

    review_sections = {
        "hook":           "HOOK（止まるか？ 問いかけになっているか？）",
        "pain":           "PAIN（後回しの本音が出ているか？ 説明調でないか？）",
        "shift":          "SHIFT（自然な部分否定か？ proof の前に好奇心を作れているか？）",
        "proof":          "PROOF（映像の事実か？ 「見ています」形式か？）",
        "benefit_bridge": "BENEFIT（proof を受けて「だから何が得られるか」が言えているか？）",
        "relief":         "RELIEF（今すぐ決めなくていい安心が伝わるか？）",
        "cta":            "CTA（営業臭くないか？ 障壁除去になっているか？）",
    }
    for purpose, label in review_sections.items():
        section_lines = [ml for ml in master_lines if ml.purpose == purpose]
        if not section_lines:
            continue
        print(f"\n■ {label}")
        for ml in section_lines:
            flag = " ⚠" if ml.cue_id in warn_ids else ""
            print(f"  {ml.cue_id:02d}. {ml.narration_line}{flag}")

    print(f"\n{'─' * 54}")
    if warnings:
        print(f"⚠  バリデーション警告: {len(warnings)}件")
        for w in warnings:
            print(f"  [{w['cue_id']:02d}] {w['purpose']:<12} [{w['rule']}]")
            print(f"       {w['narration_line'][:45]}")
            print(f"       改善: {w['suggestion']}")
    else:
        print("✓  バリデーション警告: なし")

    print(f"{'─' * 54}")
    print(f"推定尺  : {total_est:.0f}秒（推奨: {dur.min_sec}〜{dur.max_sec}秒）")
    print(f"行数    : {len(master_lines)}行 / 30文字超: {long_count}件")
    print(f"台本    : {output_dir / 'narration_script.txt'}")

    script_path = output_dir / "narration_script.txt"
    print(f"\n✅ 台本を確認・修正したら音声生成へ:")
    print(f"   python3.11 generate_narration_audio.py \"{script_path}\"")
    print(sep)


# ── メイン処理 ─────────────────────────────────────────────────────────────────

def run(
    video_paths: list[str] = [],
    notes: str = "",
    persona_insights: Optional[dict] = None,
    research_memo: Optional[dict] = None,
    stop_after_script: bool = False,
    price_signals_path: Optional[str] = None,
    competitor_patterns_path: Optional[str] = None,
    voice_snippets_path: Optional[str] = None,
    news_articles_path: Optional[str] = None,
    research_context_path: Optional[str] = None,
    forced_mode: Optional[str] = None,
) -> RunResult:
    from datetime import datetime
    date_str = datetime.now().strftime("%Y%m%d")

    print(f"\n🚀 TBT 自律ディレクターエージェント v3.0（ナレーション主導）")

    review_reasons = []
    files_generated = []

    # ── Step 1: ResearchContext の取得（通常 or スキップ）────────────────────────
    if research_context_path:
        # ── --from-research-context: Researcher をスキップして既存の research_context.json を使う
        print(f"   モード  : Researcherスキップ（research_context.json から再開）")
        try:
            with open(research_context_path, encoding="utf-8") as f:
                rc_dict = json.load(f)
            research_context = ResearchContext(**rc_dict)
        except Exception as e:
            print(f"\n❌ research_context.json 読み込みエラー: {e}")
            # ダミーの出力先を作ってエラーログを残す
            output_dir = OUTPUT_BASE_DIR / f"{date_str}_from_rc_error"
            output_dir.mkdir(parents=True, exist_ok=True)
            result = RunResult(
                run_id="error", source_video="",
                success=False, needs_human_review=True,
                review_reasons=[f"research_context.json 読み込み失敗: {e}"],
                output_dir=str(output_dir), files_generated=[], error=str(e)
            )
            save_run_log(result, output_dir)
            return result

        # 既存の run_id・出力先を引き継ぐ（上書きモード）
        run_id = research_context.run_id
        video_name = pathlib.Path(research_context.primary_source_video).stem
        # --mode 指定時は専用ディレクトリを新規作成（上書き防止）
        if forced_mode:
            output_dir = OUTPUT_BASE_DIR / f"{date_str}_{video_name}_{forced_mode}_{run_id}"
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            # 既存ディレクトリを探す。見つからなければ新規作成
            existing = list(OUTPUT_BASE_DIR.glob(f"*_{video_name}_*"))
            if existing:
                # 最終更新が最も新しいものを使う
                output_dir = max(existing, key=lambda p: p.stat().st_mtime)
            else:
                output_dir = OUTPUT_BASE_DIR / f"{date_str}_{video_name}_retry_{run_id}"
                output_dir.mkdir(parents=True, exist_ok=True)

        obs = research_context.observation
        print(f"   run_id  : {run_id}")
        print(f"   元動画  : {research_context.primary_source_video}")
        print(f"   出力先  : {output_dir}（上書き）")
        print(f"   商品    : {obs.product_family_guess} / 信頼度: {obs.product_family_confidence:.0%}\n")

    else:
        # ── 通常フロー: Researcher エージェントを実行
        if not video_paths:
            print("エラー: 動画ファイルを指定するか --from-research-context を使用してください。")
            import sys; sys.exit(1)

        run_id = str(uuid.uuid4())[:8]
        video_name = pathlib.Path(video_paths[0]).stem
        output_dir = OUTPUT_BASE_DIR / f"{date_str}_{video_name}_tmp_{run_id}"
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"   run_id  : {run_id}")
        if len(video_paths) == 1:
            print(f"   動画    : {os.path.basename(video_paths[0])}")
        else:
            print(f"   動画    : {len(video_paths)}本（同一商品）")
            for p in video_paths:
                print(f"             - {os.path.basename(p)}")
        print(f"   出力先  : {output_dir}\n")

        try:
            researcher = ResearcherAgent()
            research_context = researcher.run(
                video_paths=video_paths,
                run_id=run_id,
                notes=notes,
                research_memo=research_memo,
                persona_insights=persona_insights,
                price_signals_path=price_signals_path,
                competitor_patterns_path=competitor_patterns_path,
                voice_snippets_path=voice_snippets_path,
                news_articles_path=news_articles_path,
            )
            obs = research_context.observation
            print(f"   ✓ 観察完了（商品: {obs.product_family_guess} / 信頼度: {obs.product_family_confidence:.0%}）")
        except Exception as e:
            print(f"\n❌ Gemini観察エラー: {type(e).__name__}: {e}")
            result = RunResult(
                run_id=run_id, source_video=", ".join(os.path.basename(p) for p in video_paths),
                success=False, needs_human_review=True,
                review_reasons=[f"Gemini観察失敗: {e}"],
                output_dir=str(output_dir), files_generated=[], error=str(e)
            )
            save_run_log(result, output_dir)
            return result

    # source_video 文字列（RunResult 用）
    source_video_str = (
        research_context.primary_source_video
        if research_context_path
        else ", ".join(os.path.basename(p) for p in video_paths)
    )

    # ── Step 2: レビュー判定（観察フェーズ） ─────────────────────────────────
    # --from-research-context 時は観察フェーズを通過済みのためスキップ
    if not research_context_path:
        if obs.product_family_confidence < 0.60:
            review_reasons.append(f"商品識別の信頼度不足: {obs.product_family_confidence:.0%}")
        if obs.damage_confidence < 0.50:
            review_reasons.append(f"ダメージ評価の信頼度不足: {obs.damage_confidence:.0%}")
        if obs.overall_visual_quality == "poor":
            review_reasons.append("動画品質が低い")
        if len(obs.uncertainty_flags) >= 5:
            review_reasons.append(f"不確実情報が多い（{len(obs.uncertainty_flags)}件）: {obs.uncertainty_flags}")

    if review_reasons:
        print(f"\n⚠️  人レビューが必要です:")
        for r in review_reasons:
            print(f"   - {r}")

        review_file = save_review_md(obs, review_reasons, output_dir)
        files_generated.append(review_file)
        obs_file = output_dir / "observations.json"
        obs_file.write_text(obs.model_dump_json(indent=2), encoding="utf-8")
        files_generated.append(str(obs_file))

        result = RunResult(
            run_id=run_id, source_video=source_video_str,
            success=False, needs_human_review=True,
            review_reasons=review_reasons,
            output_dir=str(output_dir), files_generated=files_generated
        )
        save_run_log(result, output_dir)
        return result

    # ── Step 3: Narrative 生成（ResearchContext 経由）────────────────────────
    # --mode 等で notes が上書きされている場合、research_context.notes に反映する
    if notes:
        research_context = research_context.model_copy(
            update={"notes": f"{notes}\n{research_context.notes}".strip()}
        )
    try:
        plan, skeleton, master_lines, timeline_md = generate_narrative_from_research_context(research_context)
    except Exception as e:
        review_reasons.append(f"Claude構成生成失敗: {e}")
        review_file = save_review_md(obs, review_reasons, output_dir)
        result = RunResult(
            run_id=run_id, source_video=source_video_str,
            success=False, needs_human_review=True,
            review_reasons=review_reasons,
            output_dir=str(output_dir), files_generated=[review_file], error=str(e)
        )
        save_run_log(result, output_dir)
        return result

    # ── Step 4: 禁止表現チェック ──────────────────────────────────────────────
    forbidden_found = check_forbidden_narrative(plan, master_lines)
    if forbidden_found:
        review_reasons.append(f"禁止表現検出: {forbidden_found}")
        print(f"\n⚠️  禁止表現が検出されました: {forbidden_found}")
        review_file = save_review_md(obs, review_reasons, output_dir)
        result = RunResult(
            run_id=run_id, source_video=source_video_str,
            success=False, needs_human_review=True,
            review_reasons=review_reasons,
            output_dir=str(output_dir), files_generated=[review_file]
        )
        save_run_log(result, output_dir)
        return result

    # ── Step 5: 出力ファイル保存 ──────────────────────────────────────────────
    import re as _re
    hook_slug = _re.sub(r'[^\w\u3040-\u9fff]', '', plan.selected_hook)[:20]

    if research_context_path:
        # --from-research-context: 既存ディレクトリに上書き（リネームしない）
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        # 通常フロー: フックテキストでディレクトリをリネーム
        final_dir_name = f"{date_str}_{video_name}_{hook_slug}"
        final_dir = OUTPUT_BASE_DIR / final_dir_name
        if final_dir.exists():
            for n in range(2, 100):
                candidate = OUTPUT_BASE_DIR / f"{final_dir_name}_{n}"
                if not candidate.exists():
                    final_dir = candidate
                    break
        output_dir = output_dir.rename(final_dir)

    # latest シンボリックリンクを更新
    latest_link = OUTPUT_BASE_DIR / "latest"
    if latest_link.is_symlink() or latest_link.exists():
        latest_link.unlink()
    latest_link.symlink_to(output_dir.name)

    files_generated = save_narrative_outputs(run_id, obs, plan, skeleton, master_lines, timeline_md, output_dir)

    # research_context.json 保存（--from-research-context 時は更新なし。通常フローは常に保存）
    if not research_context_path:
        rc_path = output_dir / "research_context.json"
        rc_path.write_text(research_context.model_dump_json(indent=2), encoding="utf-8")
        files_generated.append(str(rc_path))

    result = RunResult(
        run_id=run_id, source_video=source_video_str,
        success=True, needs_human_review=False,
        review_reasons=[],
        output_dir=str(output_dir), files_generated=files_generated
    )
    save_run_log(result, output_dir)

    dur = plan.recommended_duration_range
    total_est = sum(ml.estimated_duration for ml in master_lines)

    if stop_after_script:
        # ── 台本確認ゲート: 保存後に人間レビューサマリーを表示して停止 ──────────
        print(f"\n✅ 台本生成・保存完了")
        print(f"   カテゴリ: {plan.content_category}")
        print(f"   出力ファイル:")
        for f in files_generated:
            print(f"   - {pathlib.Path(f).name}")
        print(f"\n   出力先: {output_dir}")
        print_script_review_summary(master_lines, plan, output_dir)
        return result

    # ── 通常完走（デフォルト）────────────────────────────────────────────────
    print(f"\n✅ 完了！")
    print(f"   カテゴリ: {plan.content_category}")
    print(f"   推奨尺  : {dur.min_sec}〜{dur.max_sec}秒（推定: {total_est:.0f}秒）")
    print(f"   行数    : {len(master_lines)}行")
    print(f"   出力ファイル:")
    for f in files_generated:
        print(f"   - {pathlib.Path(f).name}")
    print(f"\n   出力先: {output_dir}\n")
    print(f"🎙 次のステップ:")
    print(f"   1. narration_script.txt を確認・修正")
    print(f"   2. python generate_narration_audio.py <narration_script.txt のパス>")
    print(f"      ※ narration_cues.csv モードは generate_narration_audio.py --from-cues で使用可")
    print(f"   3. timeline_notes.md を見ながら Premiere で映像を当てる\n")

    return result


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TBT リール動画 自律ディレクターエージェント",
        epilog=(
            "例（通常）: python3.11 video_director.py video.mov "
            "--price-signals researcher/data/price_signals.json\n"
            "例（再生成）: python3.11 video_director.py "
            "--from-research-context output/xxx/research_context.json"
        ),
    )
    parser.add_argument("video", nargs="*", help="動画ファイルのパス（複数指定可）。--from-research-context 時は不要。")
    parser.add_argument("--from-research-context", default=None, metavar="PATH",
                        help="research_context.json のパス。指定するとResearcherをスキップして台本生成だけやり直す。")
    parser.add_argument("--notes", default="", help="追加メモ（例: '箱付き・保存袋あり'）")
    parser.add_argument("--persona-insights", default=None, metavar="PATH",
                        help="視聴者インサイトJSONファイル（省略可。例: persona_insights.json）")
    parser.add_argument("--research-memo", default=None, metavar="PATH",
                        help="リサーチメモJSONファイル（省略可。例: research_memo.json）")
    parser.add_argument("--stop-after-script", action="store_true",
                        help="台本生成後に確認サマリーを表示して停止（音声生成は行わない）")
    parser.add_argument("--price-signals", default=None, metavar="PATH",
                        help="相場シグナルJSONファイル（省略可。例: researcher/data/price_signals.json）")
    parser.add_argument("--competitor-patterns", default=None, metavar="PATH",
                        help="競合パターンJSONファイル（省略可。例: researcher/data/competitor_patterns.json）")
    parser.add_argument("--voice-snippets", default=None, metavar="PATH",
                        help="顧客の声JSONファイル（省略可。例: researcher/data/voice_snippets.json）")
    parser.add_argument("--news-articles", default=None, metavar="PATH",
                        help="市場文脈ニュースJSONファイル（省略可。例: researcher/data/news_articles.json）")
    parser.add_argument("--mode", default=None,
                        choices=["conversion", "retention", "insight", "story"],
                        help="content_mode を強制指定（省略時は素材から自動選択）。テスト用途向け。")
    args = parser.parse_args()

    # 引数バリデーション
    if not args.from_research_context and not args.video:
        parser.error("動画ファイルを指定するか --from-research-context を使用してください。")
    if args.from_research_context and not os.path.exists(args.from_research_context):
        print(f"エラー: research_context.json が見つかりません: {args.from_research_context}")
        sys.exit(1)
    for v in args.video:
        if not os.path.exists(v):
            print(f"エラー: ファイルが見つかりません: {v}")
            sys.exit(1)

    persona_insights = None
    if args.persona_insights:
        if not os.path.exists(args.persona_insights):
            print(f"エラー: persona_insights ファイルが見つかりません: {args.persona_insights}")
            sys.exit(1)
        with open(args.persona_insights, encoding="utf-8") as f:
            persona_insights = json.load(f)
        print(f"📋 persona_insights 読み込み: {args.persona_insights}")

    research_memo = None
    if args.research_memo:
        if not os.path.exists(args.research_memo):
            print(f"エラー: research_memo ファイルが見つかりません: {args.research_memo}")
            sys.exit(1)
        with open(args.research_memo, encoding="utf-8") as f:
            research_memo = json.load(f)
        print(f"📰 research_memo 読み込み: {args.research_memo}")

    # --mode 指定時は notes に強制指定ディレクティブを注入する
    notes = args.notes
    if args.mode:
        mode_directive = (
            f"【モード強制指定】content_mode は必ず \"{args.mode}\" にすること。"
            f"narrative_arc と ending_type もこのモードに適した値を選ぶこと。"
        )
        notes = f"{mode_directive}\n{notes}".strip()

    result = run(
        args.video,
        notes,
        persona_insights,
        research_memo,
        stop_after_script=args.stop_after_script,
        price_signals_path=args.price_signals,
        competitor_patterns_path=args.competitor_patterns,
        voice_snippets_path=args.voice_snippets,
        news_articles_path=args.news_articles,
        research_context_path=args.from_research_context,
        forced_mode=args.mode,
    )

    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
