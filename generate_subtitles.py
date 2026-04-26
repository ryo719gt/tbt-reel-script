#!/usr/bin/env python3.11
"""
TBT テロップ・ナレーション生成スクリプト

使い方:
    python3.11 generate_subtitles.py <編集済み動画> --strategy <strategy.json>
    python3.11 generate_subtitles.py <編集済み動画>  # strategy.json を自動検索

出力:
    subtitles.srt   CapCut にインポートできる字幕ファイル
    narration.txt   AI音声用ナレーション原稿（コピペ用）
"""

import sys
import os
import json
import time
import argparse
import pathlib

from google import genai
from google.genai import types as genai_types
import anthropic

GEMINI_API_KEY   = "AIzaSyAIMy54kJBIc5agcXvspGG4BdqFSUX6TVY"
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEMINI_MODEL     = "gemini-2.5-flash"
CLAUDE_MODEL     = "claude-sonnet-4-6"


# ── Gemini: 編集済み動画のシーン解析 ──────────────────────────────────────────

SCENE_ANALYSIS_PROMPT = """
あなたの仕事は動画のシーン解析です。

この動画を秒単位で観察して、映像の内容が切り替わるタイミングをすべて記録してください。

以下のJSON形式のみで返してください。説明文は不要です。

{
  "total_duration_sec": number,
  "scenes": [
    {
      "start_sec": number,
      "end_sec": number,
      "description": "string（この区間に映っているもの・動きの説明）"
    }
  ]
}
"""

def analyze_scenes_with_gemini(video_path: str) -> dict:
    client = genai.Client(api_key=GEMINI_API_KEY)
    mime_type = "video/mp4" if video_path.lower().endswith(".mp4") else "video/quicktime"
    size_mb = os.path.getsize(video_path) / 1024 / 1024
    print(f"📹 Gemini: 動画をアップロード中... ({size_mb:.0f}MB)")

    with open(video_path, "rb") as f:
        uploaded = client.files.upload(
            file=f,
            config=genai_types.UploadFileConfig(mime_type=mime_type)
        )
    while uploaded.state and uploaded.state.name == "PROCESSING":
        time.sleep(3)
        uploaded = client.files.get(name=uploaded.name)

    print("   シーン解析中...")
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[
            genai_types.Part.from_uri(file_uri=uploaded.uri, mime_type=mime_type),
            SCENE_ANALYSIS_PROMPT,
        ],
        config=genai_types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )
    try:
        client.files.delete(name=uploaded.name)
    except Exception:
        pass

    raw = response.text.strip()
    parsed = json.loads(raw)
    if isinstance(parsed, list):
        parsed = parsed[0]
    return parsed


# ── Claude: シーンとテロップを紐付け ─────────────────────────────────────────

MATCHING_PROMPT = """
あなたはエルメス専門買取TBTのInstagramリール動画のディレクターです。

以下の「編集済み動画のシーン一覧」と「事前に作成した字幕・ナレーション原稿」を照合し、
各字幕テキストを実際の動画のタイムコードに割り当ててください。

## 編集済み動画のシーン一覧
{scenes}

## 事前作成の字幕・ナレーション原稿（strategy.json より）
{subtitles}

## ルール
- 動画の実際の尺（total_duration_sec）に合わせてタイムコードを調整する
- シーンの内容と字幕の意味が合うように紐付ける
- テロップは必ず短いフレーズ単位に分割する（1テロップ = 10〜12文字が目安、最大12文字）
- 長い文章は読点・句点・助詞・意味の区切りで細かく分割する
  例：「カデナに保護フィルムが残っているケリー」→「カデナの保護フィルムが」「残っているケリー」
  例：「査定額にどう影響するか」→「査定額に」「どう影響するか」
- 1テロップの表示時間は1.0〜2.0秒
- テロップ数は動画尺の1.5倍以上を目標（52秒なら35件以上）
- voiceover_text はフレーズをつなげた自然な読み上げ文にする

## 出力形式（JSONのみ）
{{
  "total_duration_sec": number,
  "subtitles": [
    {{
      "index": 1,
      "start_sec": number,
      "end_sec": number,
      "subtitle_text": "string（テロップ表示テキスト）",
      "voiceover_text": "string（AI音声読み上げテキスト）"
    }}
  ]
}}
"""

def match_subtitles_with_claude(scenes: dict, strategy: dict) -> dict:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY が設定されていません。")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    print("🧠 Claude: テロップをタイムコードに紐付け中...")

    # strategy.json からテロップ・ナレーション原稿を抽出
    segments = strategy.get("edit_plan", {}).get("segments", [])
    subtitles_src = [
        {
            "planned_start": s.get("start_sec"),
            "planned_end": s.get("end_sec"),
            "subtitle_text": s.get("subtitle_text", ""),
            "voiceover_text": s.get("voiceover_text", ""),
            "segment_goal": s.get("segment_goal", ""),
        }
        for s in segments
    ]

    prompt = MATCHING_PROMPT.format(
        scenes=json.dumps(scenes, ensure_ascii=False, indent=2),
        subtitles=json.dumps(subtitles_src, ensure_ascii=False, indent=2),
    )

    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        system="必ずJSONのみを返してください。説明文・コードブロック不要。",
        messages=[{"role": "user", "content": prompt}]
    )

    raw = message.content[0].text.strip()
    if "```" in raw:
        for part in raw.split("```"):
            part = part.strip().lstrip("json").strip()
            if part.startswith("{"):
                raw = part
                break
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start != -1 and end > start:
        raw = raw[start:end]
    return json.loads(raw)


# ── SRT 生成 ──────────────────────────────────────────────────────────────────

def sec_to_srt_time(sec: float) -> str:
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    ms = int((sec - int(sec)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def generate_srt(subtitles: list[dict]) -> str:
    lines = []
    for sub in subtitles:
        lines.append(str(sub["index"]))
        lines.append(f"{sec_to_srt_time(sub['start_sec'])} --> {sec_to_srt_time(sub['end_sec'])}")
        lines.append(sub["subtitle_text"])
        lines.append("")
    return "\n".join(lines)

def generate_narration_txt(subtitles: list[dict], total_sec: float) -> str:
    lines = [
        "# ナレーション原稿",
        f"# 動画尺：{total_sec:.1f}秒",
        "",
        "## CapCut「テキスト読み上げ」への入力手順",
        "1. 各テロップを選択 → 「テキスト読み上げ」をタップ",
        "2. 以下の原稿テキストを対応する区間に入力する",
        "3. 音声：落ち着いた女性ナレーター / 速度：0.95倍",
        "",
        "---",
        "",
    ]
    for sub in subtitles:
        start = sec_to_srt_time(sub["start_sec"]).replace(",", ".")
        end = sec_to_srt_time(sub["end_sec"]).replace(",", ".")
        lines.append(f"【{start} 〜 {end}】")
        lines.append(f"テロップ：{sub['subtitle_text']}")
        lines.append(f"ナレーション：{sub['voiceover_text']}")
        lines.append("")
    return "\n".join(lines)


# ── メイン ────────────────────────────────────────────────────────────────────

def find_strategy_json(video_path: str) -> str | None:
    """動画と同じディレクトリか output/ 配下から strategy.json を探す"""
    video_dir = pathlib.Path(video_path).parent
    # 同じディレクトリ
    candidate = video_dir / "strategy.json"
    if candidate.exists():
        return str(candidate)
    # output/ 配下を最終更新順に探す
    output_base = pathlib.Path(__file__).parent / "output"
    candidates = sorted(output_base.glob("*/strategy.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return str(candidates[0])
    return None


def main():
    parser = argparse.ArgumentParser(description="編集済み動画にテロップ・ナレーションを生成")
    parser.add_argument("video", help="編集済み動画ファイルのパス")
    parser.add_argument("--strategy", default=None, help="strategy.json のパス（省略時は自動検索）")
    parser.add_argument("--output-dir", default=None, help="出力先ディレクトリ（省略時は動画と同じ場所）")
    args = parser.parse_args()

    if not os.path.exists(args.video):
        print(f"エラー: ファイルが見つかりません: {args.video}")
        sys.exit(1)

    # strategy.json の解決
    strategy_path = args.strategy or find_strategy_json(args.video)
    if not strategy_path or not os.path.exists(strategy_path):
        print("エラー: strategy.json が見つかりません。--strategy で指定してください。")
        sys.exit(1)
    print(f"   strategy.json: {strategy_path}")

    with open(strategy_path, encoding="utf-8") as f:
        strategy = json.load(f)

    # 出力先
    output_dir = pathlib.Path(args.output_dir) if args.output_dir else pathlib.Path(args.video).parent
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🎬 TBT テロップ・ナレーション生成")
    print(f"   動画  : {os.path.basename(args.video)}")
    print(f"   出力先: {output_dir}\n")

    # Step 1: Gemini でシーン解析
    scenes = analyze_scenes_with_gemini(args.video)
    total_sec = scenes.get("total_duration_sec", 0)
    print(f"   ✓ シーン解析完了（尺：{total_sec:.1f}秒 / {len(scenes.get('scenes', []))}シーン）")

    # Step 2: Claude でタイムコード紐付け
    result = match_subtitles_with_claude(scenes, strategy)
    total_sec = result.get("total_duration_sec", total_sec)
    subs = result.get("subtitles", [])
    print(f"   ✓ テロップ紐付け完了（{len(subs)}件）")

    # Step 3: ファイル出力
    srt_path = output_dir / "subtitles.srt"
    srt_path.write_text(generate_srt(subs), encoding="utf-8")

    narration_path = output_dir / "narration.txt"
    narration_path.write_text(generate_narration_txt(subs, total_sec), encoding="utf-8")

    print(f"\n✅ 完了！")
    print(f"   - subtitles.srt  （CapCutにインポート）")
    print(f"   - narration.txt  （AI音声コピペ用）")
    print(f"   出力先: {output_dir}\n")


if __name__ == "__main__":
    main()
