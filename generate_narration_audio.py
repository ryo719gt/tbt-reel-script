#!/usr/bin/env python3.11
"""
TBT ナレーション音声生成スクリプト（AivisSpeech）

使い方:
    # narration.txt（旧形式）から生成
    python3.11 generate_narration_audio.py <narration.txt>

    # narration_cues.csv（v3.0新形式）から生成
    python3.11 generate_narration_audio.py <narration_cues.csv> --from-cues

    # スタイル指定
    python3.11 generate_narration_audio.py <narration_script.txt> --style-id 1310138979

出力:
    narration_audio/ ディレクトリに 001_section名.wav などの連番音声ファイル

前提:
    AivisSpeech Engineが起動済みであること（ポート10101）
    起動コマンド:
    /Applications/AivisSpeech.app/Contents/Resources/AivisSpeech-Engine/run --host 127.0.0.1 --port 10101 &
"""

import sys
import os
import re
import csv
import json
import argparse
import pathlib
import time
import urllib.request
import urllib.error

AIVIS_BASE_URL = "http://127.0.0.1:10101"

# 阿井田 茂「Heavy」スタイル（バリトン中年男性 / TBTターゲット: 30-50代女性向け）
# Calm=1310138977, Heavy=1310138979, Mid=1310138980
# fumifumiに変えたい場合: 606865152
DEFAULT_STYLE_ID = 1310138979
DEFAULT_SPEED = 1.05   # 少し速め（リール向け）
DEFAULT_PITCH = 0.0
DEFAULT_INTONATION = 1.1  # 抑揚わずかに強め


def check_engine():
    """AivisSpeech Engineが起動しているか確認"""
    try:
        with urllib.request.urlopen(f"{AIVIS_BASE_URL}/version", timeout=3) as res:
            version = json.loads(res.read())
            print(f"✓ AivisSpeech Engine v{version} 起動確認")
            return True
    except Exception:
        print("✗ AivisSpeech Engine が起動していません。")
        print("  起動コマンド:")
        print("  /Applications/AivisSpeech.app/Contents/Resources/AivisSpeech-Engine/run --host 127.0.0.1 --port 10101 &")
        print("  起動後 10〜20秒待ってから再実行してください。")
        return False


def parse_narration_cues_csv(csv_path: str) -> list[dict]:
    """
    narration_cues.csv（v3.0形式）を解析してナレーション一覧を返す。

    戻り値:
        [{"index": int, "section_name": str, "voiceover_text": str}, ...]
    """
    results = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            text = row.get("line_text", "").strip()
            if not text or text.startswith("#"):
                continue
            results.append({
                "index": int(row.get("cue_id", len(results) + 1)),
                "section_name": row.get("section_name", ""),
                "voiceover_text": text,
                "evidence_confidence": row.get("evidence_confidence", ""),
            })
    return results


def parse_narration_script_txt(txt_path: str) -> list[dict]:
    """
    narration_script.txt（v3.0形式）または narration.txt（旧形式）を解析する。

    v3.0形式: 「01. テキスト」形式の行を抽出
    旧形式:   「【HH:MM:SS ...】/ ナレーション: テキスト」形式
    """
    text = pathlib.Path(txt_path).read_text(encoding="utf-8")

    # v3.0形式: "01. テキスト" または "01. テキスト ⚠️"
    v3_pattern = re.compile(r"^(\d{2})\.\s+(.+?)(?:\s+⚠️)?$", re.MULTILINE)
    v3_matches = list(v3_pattern.finditer(text))
    if v3_matches:
        results = []
        current_section = ""
        for line in text.splitlines():
            sec_match = re.match(r"^##\s+(.+)", line)
            if sec_match:
                current_section = sec_match.group(1).strip()
            cue_match = re.match(r"^(\d{2})\.\s+(.+?)(?:\s+⚠️)?$", line)
            if cue_match:
                results.append({
                    "index": int(cue_match.group(1)),
                    "section_name": current_section,
                    "voiceover_text": cue_match.group(2).strip(),
                })
        return results

    # 旧形式: narration.txt（タイムコード付き）
    pattern = re.compile(
        r"【(\d{2}:\d{2}:\d{2}[.,]\d{3}) 〜 (\d{2}:\d{2}:\d{2}[.,]\d{3})】\s*\n"
        r"テロップ：[^\n]*\n"
        r"ナレーション：([^\n]+)",
        re.MULTILINE
    )
    results = []
    for i, m in enumerate(pattern.finditer(text), 1):
        narration = m.group(3).strip()
        if not narration:
            continue
        results.append({
            "index": i,
            "section_name": "",
            "voiceover_text": narration,
        })
    return results


def parse_narration_txt(txt_path: str) -> list[dict]:
    """後方互換用。parse_narration_script_txt を呼ぶ"""
    return parse_narration_script_txt(txt_path)


def timecode_to_sec(tc: str) -> float:
    """HH:MM:SS,mmm → float秒"""
    tc = tc.replace(",", ".")
    h, m, rest = tc.split(":")
    s, ms_str = rest.split(".")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms_str) / 1000


def synthesize(text: str, style_id: int, speed: float, pitch: float, intonation: float) -> bytes:
    """
    テキストをAivisSpeech APIで音声合成してWAVバイト列を返す。
    """
    # Step 1: audio_query
    import urllib.parse
    params = urllib.parse.urlencode({"text": text, "speaker": style_id})
    req = urllib.request.Request(
        f"{AIVIS_BASE_URL}/audio_query?{params}",
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        query = json.loads(res.read())

    # パラメータ上書き
    query["speedScale"] = speed
    query["pitchScale"] = pitch
    query["intonationScale"] = intonation

    # Step 2: synthesis
    body = json.dumps(query).encode("utf-8")
    params2 = urllib.parse.urlencode({"speaker": style_id})
    req2 = urllib.request.Request(
        f"{AIVIS_BASE_URL}/synthesis?{params2}",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req2, timeout=60) as res:
        return res.read()


def main():
    parser = argparse.ArgumentParser(
        description="ナレーション原稿から音声ファイルを生成（AivisSpeech）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  # v3.0: narration_script.txt から生成
  python generate_narration_audio.py output/latest/narration_script.txt

  # v3.0: narration_cues.csv から生成
  python generate_narration_audio.py output/latest/narration_cues.csv --from-cues

  # スタイル指定（阿井田 茂 Heavy）
  python generate_narration_audio.py narration_script.txt --style-id 1310138979
        """,
    )
    parser.add_argument("input_file", help="narration_script.txt または narration_cues.csv のパス")
    parser.add_argument("--from-cues", action="store_true",
                        help="narration_cues.csv（v3.0形式）として読み込む")
    parser.add_argument("--style-id", type=int, default=DEFAULT_STYLE_ID,
                        help=f"AivisSpeech スタイルID (デフォルト: {DEFAULT_STYLE_ID})")
    parser.add_argument("--speed", type=float, default=DEFAULT_SPEED)
    parser.add_argument("--pitch", type=float, default=DEFAULT_PITCH)
    parser.add_argument("--intonation", type=float, default=DEFAULT_INTONATION)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"エラー: ファイルが見つかりません: {args.input_file}")
        sys.exit(1)

    if not check_engine():
        sys.exit(1)

    # ファイル形式に応じてパース
    if args.from_cues or args.input_file.endswith(".csv"):
        narrations = parse_narration_cues_csv(args.input_file)
        mode = "cues.csv"
    else:
        narrations = parse_narration_script_txt(args.input_file)
        mode = "script.txt"

    if not narrations:
        print(f"エラー: ナレーションが見つかりません ({mode})")
        sys.exit(1)

    output_dir = pathlib.Path(args.output_dir) if args.output_dir \
        else pathlib.Path(args.input_file).parent / "narration_audio"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n🎙 TBT ナレーション音声生成 ({mode})")
    print(f"   ナレーション数: {len(narrations)}件")
    print(f"   出力先: {output_dir}\n")

    generated = []
    for item in narrations:
        idx = item["index"]
        text = item["voiceover_text"]
        section = item.get("section_name", "")
        # ファイル名: 001_セクション名.wav（セクション名があれば）
        sec_slug = re.sub(r"[^\w\u3040-\u9fff]", "", section)[:10]
        filename = f"{idx:03d}_{sec_slug}.wav" if sec_slug else f"{idx:03d}.wav"
        out_path = output_dir / filename

        print(f"  [{idx:03d}] {section or '-':<10}  {text}")
        try:
            wav_bytes = synthesize(text, args.style_id, args.speed, args.pitch, args.intonation)
            out_path.write_bytes(wav_bytes)
            generated.append({"index": idx, "section_name": section, "line_text": text, "path": str(out_path)})
        except Exception as e:
            print(f"    ⚠ 失敗: {e}")
        time.sleep(0.1)

    mapping_path = output_dir / "mapping.json"
    mapping_path.write_text(json.dumps(generated, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n✅ 完了！")
    print(f"   - {len(generated)}件の音声ファイルを生成")
    print(f"   - mapping.json: キュー対応表")
    print(f"   出力先: {output_dir}\n")
    print("📋 Premiere Proへの取り込み:")
    print("   1. narration_audio/ フォルダを Premiere のプロジェクトパネルにインポート")
    print("   2. timeline_notes.md を見ながら音声トラックに順番に並べる")
    print("   3. 音声に合わせて映像クリップを当てる")


if __name__ == "__main__":
    main()
