"""
参考リール書き起こしツール

動画ファイルをGemini File APIに渡して書き起こし、
output/transcripts/ にテキストを保存する。

使い方:
    python3.11 transcribe_reel.py /path/to/reel.mp4
    python3.11 transcribe_reel.py /path/to/reel.mp4 --label "競合A_査定系"
"""

import sys
import os
import time
from datetime import date
from dotenv import load_dotenv
from google import genai
from google.genai import types

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "../../.env"))

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


TRANSCRIPT_PROMPT = """
この動画はInstagramのトークリール（縦型ショート動画）です。
以下の手順で書き起こしと分析を行ってください。

## 1. 書き起こし（最優先・精度最大化）

【必須ルール】
- 話者の発言を**一字一句、省略・要約・言い換えなしで**書き起こす
- 聞き取れた言葉はすべて記録する。推測で埋めず、聞き取れない箇所は（不明）と記載
- 「えー」「あの」「まあ」などのフィラーもそのまま記録する
- 語尾・助詞・接続詞を絶対に省略しない（「〜ですね」「〜なんですよ」など話し言葉の特徴を保持）
- テロップが表示されている場合は【テロップ：○○】として書き起こしに含める
- 意図的な「間（ポーズ）」は（間）と記載
- 複数話者がいる場合は [話者A]、[話者B] のように区別する
- 各発言の開始タイムスタンプを（0:00）形式で付ける

【出力形式】
（0:00）発言内容
（0:03）発言内容
…

## 2. 構造メモ

書き起こしを元に、以下を時間軸で整理してください。
- フック（冒頭0〜3秒）：発言 / テロップの内容
- 導入（3〜10秒）：何を話したか
- 本編（10〜40秒）：何を話したか（箇条書き）
- CTA（最後）：何に誘導しているか

## 3. 分析サマリー

- フックの型：禁止・警告 / 数字・実績 / 意外性 / ベネフィット / 問いかけ のどれか
- 感情軸：視聴者のどんな感情・心理に訴えているか
- 構成の特徴：テンポ・間の取り方・言葉選びで目立つ点
- 盗めるパターン：エルメス専門買取アカウントに転用できる表現・構造・フレーズ

出力は上記3セクションを順番に記載してください。
"""


def transcribe(video_path: str, label: str = "") -> tuple[str, str]:
    if not os.path.exists(video_path):
        print(f"ファイルが見つかりません: {video_path}")
        sys.exit(1)

    # ファイルタイプを拡張子から判定
    ext = os.path.splitext(video_path)[1].lower()
    mime_map = {".mp4": "video/mp4", ".mov": "video/quicktime", ".avi": "video/avi", ".webm": "video/webm"}
    mime_type = mime_map.get(ext, "video/mp4")

    print(f"アップロード中: {video_path}")
    with open(video_path, "rb") as f:
        video_file = client.files.upload(
            file=f,
            config=types.UploadFileConfig(mime_type=mime_type, display_name=os.path.basename(video_path))
        )

    # アップロード完了待ち
    while video_file.state.name == "PROCESSING":
        print("処理中...")
        time.sleep(3)
        video_file = client.files.get(name=video_file.name)

    if video_file.state.name == "FAILED":
        print("アップロードに失敗しました。")
        sys.exit(1)

    print("書き起こし中...\n")
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_uri(file_uri=video_file.uri, mime_type=mime_type),
            TRANSCRIPT_PROMPT,
        ]
    )
    result = response.text

    # 保存
    output_dir = os.path.join(BASE_DIR, "output", "transcripts")
    os.makedirs(output_dir, exist_ok=True)
    datestamp = date.today().strftime("%Y%m%d")
    base_name = os.path.splitext(os.path.basename(video_path))[0][:30]
    suffix = f"_{label}" if label else ""
    output_path = os.path.join(output_dir, f"{datestamp}_{base_name}{suffix}.md")

    header = (
        f"# 参考リール書き起こし\n\n"
        f"- 元ファイル: {os.path.basename(video_path)}\n"
        f"- 日付: {datestamp}\n"
        f"- ラベル: {label or '未設定'}\n\n---\n\n"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header + result)

    # アップロードしたファイルを削除（ストレージ節約）
    client.files.delete(name=video_file.name)

    return output_path, result


def main():
    if len(sys.argv) < 2:
        print("使い方: python3.11 transcribe_reel.py <動画ファイルパス> [--label ラベル名]")
        sys.exit(1)

    video_path = sys.argv[1]
    label = ""
    if "--label" in sys.argv:
        idx = sys.argv.index("--label")
        label = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else ""

    output_path, result = transcribe(video_path, label)
    print(result)
    print(f"\n保存先: {output_path}")
    print("\nこのテキストを reel_script_generator.py のモード7（参考リール分析）に貼り付けてください。")


if __name__ == "__main__":
    main()
