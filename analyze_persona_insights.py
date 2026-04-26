#!/usr/bin/env python3.11
"""
TBT ペルソナインサイト候補抽出スクリプト

収集した生テキスト（X投稿・メモ等）を Claude で分析し、
persona_insights.json に転記するための候補を insight_candidates.json として出力する。

使い方:
    python3.11 analyze_persona_insights.py --input raw_posts.txt
    python3.11 analyze_persona_insights.py --input raw_posts.json --out my_candidates.json

入力形式:
    .txt: 1行1メモ（空行・#コメント行は無視）
    .json: {"items": ["...", "..."]} または ["...", "..."]

出力:
    insight_candidates.json（デフォルト）
    persona_insights.json は一切変更しない。手動で転記すること。
"""

import sys
import os
import json
import argparse
import pathlib
from datetime import datetime

import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"

ANALYSIS_PROMPT = """
あなたはエルメス専門買取TBTのSNS運用担当のリサーチアシスタントです。

以下は、エルメスの売却を迷っている30〜50代女性のリアルな声・投稿・メモを収集したものです。

## TBTペルソナ
- エルメスのバッグを持っている30〜50代女性
- 売却を迷っている（でも決めていない）
- 相場感だけ知りたいが、いきなり相談は重いと感じている
- 付属品・状態がどう見られるか分からない
- 高く売りたいが「納得して判断したい」が強い
- TBTのトーン: 上品・落ち着き・誠実・寄り添い

## 収集データ（{item_count}件）
{raw_texts}

## やってほしいこと
上記データから以下4つのカテゴリに整理してください。
データにない概念を創作しないでください。データに根ざした候補のみを出してください。

### raw_phrases_candidates
生の声・言い回しとして使えそうなフレーズを抽出する。
加工しすぎず、できるだけ元の言葉に近い形で残す。

### common_fears_candidates
投稿・メモの奥にある恐れ・抵抗感を抽出する。
「〜されたくない」「〜が怖い」「〜が不安」の形式で書く。
データから読み取れる範囲にとどめる。

### belief_candidates
行動を止めている思い込みを抽出する。
「〜のはず」「〜かもしれない」「〜でないと」の形式で書く。
TBTの査定・問い合わせへの行動障壁になっているものを優先する。

### hook_candidates
opening / tension セクションで使えそうな問いかけフレーズを生成する。
収集データの言葉をベースに「〜ていませんか？」「〜のままになっていませんか？」形式で作る。

### summary_note
今回のデータから見えた傾向・共通する心理を1〜2文で書く。

## 制約
- 「今すぐ」「損をしている」「知らないと損」などの煽り表現は禁止
- 情報商材調の表現は使わない
- 「迷って止まっている感じ」を優先する
- 上品・落ち着き・誠実・寄り添いのトーンを維持する
- hook_candidates は「〜ていませんか？」「〜のままになっていませんか？」形式を優先する
- データにない概念を創作しない（ハルシネーション禁止）

## 出力形式（JSONのみ）
{{
  "raw_phrases_candidates": ["string", ...],
  "common_fears_candidates": ["string", ...],
  "belief_candidates": ["string", ...],
  "hook_candidates": ["string", ...],
  "summary_note": "string"
}}
"""


def load_input(path: str) -> list[str]:
    """txt または json を読み込んでテキストリストを返す"""
    p = pathlib.Path(path)
    if not p.exists():
        print(f"エラー: ファイルが見つかりません: {path}")
        sys.exit(1)

    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # {"items": [...]} or {"raw_audience_phrases": [...]} など
            for key in ("items", "raw_audience_phrases", "texts", "posts"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
            else:
                # dict の全 string value をフラットにする
                items = []
                for v in data.values():
                    if isinstance(v, list):
                        items.extend(str(x) for x in v)
                    elif isinstance(v, str):
                        items.append(v)
        else:
            print(f"エラー: JSONの形式が想定外です（list または dict を期待）")
            sys.exit(1)
        return [str(x).strip() for x in items if str(x).strip()]

    else:
        # .txt: 1行1メモ。空行・#コメントは除外
        lines = p.read_text(encoding="utf-8").splitlines()
        return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def analyze_with_claude(items: list[str]) -> dict:
    """Claude でインサイト候補を抽出する"""
    if not ANTHROPIC_API_KEY:
        print("エラー: ANTHROPIC_API_KEY が設定されていません。")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    raw_texts = "\n".join(f"- {item}" for item in items)
    prompt = ANALYSIS_PROMPT.format(
        item_count=len(items),
        raw_texts=raw_texts,
    )

    print(f"🧠 Claude: インサイト候補を分析中（{len(items)}件）...")
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=2048,
        system="あなたはTBT（エルメス専門買取）のリサーチアシスタントです。指定されたJSONのみを返してください。",
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    # コードブロック除去
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
        print(f"エラー: Claude の応答をJSONとして解析できませんでした: {e}")
        print(f"応答（先頭500文字）:\n{raw[:500]}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="TBT ペルソナインサイト候補抽出ツール",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # テキストファイルから分析
  python3.11 analyze_persona_insights.py --input raw_posts.txt

  # JSONファイルから分析
  python3.11 analyze_persona_insights.py --input raw_posts.json

  # 出力先を指定
  python3.11 analyze_persona_insights.py --input raw_posts.txt --out candidates_april.json

出力: insight_candidates.json（persona_insights.json は変更しません）
        """,
    )
    parser.add_argument("--input", required=True, metavar="PATH",
                        help="入力ファイル（.txt: 1行1メモ / .json: {items:[...]} または [...] ）")
    parser.add_argument("--out", default="insight_candidates.json", metavar="PATH",
                        help="出力ファイル（デフォルト: insight_candidates.json）")
    args = parser.parse_args()

    # 入力読み込み
    items = load_input(args.input)
    if not items:
        print("エラー: 入力データが空です。")
        sys.exit(1)
    print(f"📥 入力: {args.input}（{len(items)}件）")

    # Claude 分析
    result = analyze_with_claude(items)

    # メタ情報を付加
    output = {
        "_last_generated": datetime.now().strftime("%Y-%m-%d"),
        "_input_file": str(pathlib.Path(args.input).name),
        "_item_count": len(items),
        "_note": "このファイルは候補一覧です。persona_insights.json への反映は手動で行ってください。",
    }
    output.update(result)

    # 出力
    out_path = pathlib.Path(args.out)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ 完了！")
    print(f"   出力: {out_path}")
    print(f"\n📋 次のステップ:")
    print(f"   1. {out_path} を開いて候補を確認")
    print(f"   2. TBTトーンに合うものだけ persona_insights.json に手動転記")
    print(f"   3. persona_insights.json の _last_updated を更新")


if __name__ == "__main__":
    main()
