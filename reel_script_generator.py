"""
TBT エルメス専門アカウント — Instagram リール台本生成スクリプト

使い方:
    # テーマ指定モード（従来通り）
    python3.11 reel_script_generator.py "バーキンの相場"

    # 商品モード（1商品→2テーマの台本を同時出力）
    python3.11 reel_script_generator.py --product "バーキン25 トゴ ゴールド"
    python3.11 reel_script_generator.py  # 対話形式で入力
"""

import sys
import os
from dotenv import load_dotenv
from anthropic import Anthropic

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "../../.env"))

BRIEF_PATH = os.path.join(BASE_DIR, "../../notes/tbt_brief.md")

def load_brief() -> str:
    with open(BRIEF_PATH, "r", encoding="utf-8") as f:
        return f.read()

client = Anthropic()

HOOK_RULES = """
【フック設計の絶対ルール】
強いフックは以下の3つの心理トリガーのどれかを必ず使う：
1. 情報ギャップ：「知らないと損する事実」を匂わせ、答えを知るまで離脱できなくする
   例：「バーキンの査定で9割の人が損している理由」
2. 損失回避：「このまま見ないと損する」という危機感を1行で作る
   例：「そのまま売ると◯万円損します」
3. 具体的数字：曖昧な言葉より数字が人を止める
   例：「買取相場、2年で80万円変わりました」

【NGパターン ── 絶対に使わない】
- 「〜についてご紹介します」（弱い・主体がTBT）
- 「〜を解説します」（弱い・教科書的）
- 「皆さん、〜知っていますか？」（弱い・距離感がある）
- 長すぎる（3秒で読めない20文字超え）
- 「エルメスとは」など視聴者が既に知っていること

【フックの構造】
- 最大20文字以内
- 主語は視聴者（「あなた」「自分」）か省略
- 動詞は行動・損得・驚きにつながるものを選ぶ
- 読み終わった瞬間に「続きが気になる」状態を作る
"""

SCRIPT_FORMAT = f"""
## フックテロップ 3案（0〜3秒）
{HOOK_RULES}
各案に「なぜ止まるか」の根拠を1行で添えること。

【A：情報ギャップ型】
→
根拠：

【B：損失回避型】
→
根拠：

【C：数字・事実型】
→
根拠：

推奨：A／B／Cのどれか＋理由を1行

## テロップリスト（本編 4〜50秒）
※1行ずつ書く。各行がCapCut上の1テロップになる。
※引っ張りには行末に【★】を付ける。
※目安：全体で15〜22行。

【導入 4〜10秒 ── 問題提起・共感】
1.
2.
3.

【展開 11〜35秒 ── 意外な事実・専門知識】
4.
5.
6.
7. 【★】
8.
9.
10.

【結論 36〜50秒 ── TBTならではの答え】
11.
12.
13.

## CTAテロップ（最後5〜10秒）
※LINE誘導・保存誘導・コメントバイトを順に。各1〜2行。

LINE誘導：
保存誘導：（例：「保存しておくと◯◯のときに役立ちます」）
コメントバイト：（視聴者が答えたくなる簡単な質問）

## 撮影チェックリスト
※撮影済み素材の中から使える素材を確認するリスト。撮れていなければ追加撮影を依頼。
- [ ]
- [ ]
- [ ]
- [ ]

## ストーリーズ連動案
※リール投稿後、ストーリーズでどう展開するか。2〜3案。
- 案1（アンケートスタンプ）：
- 案2（質問スタンプ）：
- 案3（リンクスタンプ）：

## キャプション案
※200字以内。冒頭1行目にテーマキーワードを入れること。ハッシュタグ不要。
※AI下書きのため、投稿前に担当者が自分の言葉に直すこと。

---
⚠️ 編集メモ（投稿前に確認）
- テロップの言い回しを自分の言葉に直す
- 1行が長すぎる場合は分割する
- 【★】の引っ張り行は特に自然な言葉になっているか確認する
---
""".strip()


def generate_script(topic: str) -> str:
    """テーマ指定で1本分の台本を生成する"""
    brief = load_brief()

    system_prompt = f"""
あなたはエルメス専門買取・販売会社「TBT」のInstagramリール動画の台本ライターです。
以下のブランドブリーフを必ず参照して台本を作成してください。

---
{brief}
---
""".strip()

    prompt = f"""
以下のテーマでTBTのInstagramリール台本を作成してください。

テーマ：{topic}

【制作フローの前提】
- 撮影は企画なしで先に行い、ジャンプカット（1カット2〜3秒）で編集する
- 2画角（引きと寄り）で撮影した3〜4分の素材を40秒に編集する
- テロップをCapCut AI音声に読み上げさせる形式
- 1行あたり15〜25文字、読み上げ時間2〜3秒を目安にする

【再生数を伸ばす設計原則】
1. フックは3パターン用意（疑問型・衝撃型・共感型）
2. 本編は「問題提起 → 共感 → 意外な事実／引っ張り → 解決策」の順
3. 引っ張りのテロップには【★】を付ける（視聴維持のキー）
4. CTAに保存誘導とコメントバイトを入れる

以下の形式で出力してください：

---
## テーマ
{topic}

{SCRIPT_FORMAT}
""".strip()

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=3500,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


def generate_two_scripts(product: str) -> tuple[str, str, str]:
    """商品情報から2テーマを選定し、それぞれの台本を生成する。(theme1, script1, theme2, script2)を返す"""
    brief = load_brief()

    system_prompt = f"""
あなたはエルメス専門買取・販売会社「TBT」のInstagramリール動画の台本ライターです。
以下のブランドブリーフを必ず参照して台本を作成してください。

---
{brief}
---
""".strip()

    prompt = f"""
以下の商品を撮影した3〜4分の動画素材（2画角：引きと寄り）から、
Instagramリールを2本作ります。

商品：{product}

【制作フローの前提】
- 1回の撮影素材（3〜4分）から2本のリールを切り出す
- 同じ素材でも切り出すクリップとテロップを変えることで別コンテンツにする
- ジャンプカット（1カット2〜3秒）、完成尺は各40秒程度
- テロップをCapCut AI音声に読み上げさせる形式
- 1行あたり15〜25文字、読み上げ時間2〜3秒を目安にする

【2テーマの選び方】
- テーマAは「商品紹介・買取実績・相場系」（売りたい人に刺さる）
- テーマBは「知識・真贋・希少性系」（この商品に関連した専門知識）
- 同じ素材から切り出せるよう、撮影チェックリストの使用クリップが重ならないようにする

【再生数を伸ばす設計原則】
1. フックは3パターン用意（疑問型・衝撃型・共感型）
2. 本編は「問題提起 → 共感 → 意外な事実／引っ張り → 解決策」の順
3. 引っ張りのテロップには【★】を付ける
4. CTAに保存誘導とコメントバイトを入れる

以下の形式で出力してください：

===========================
# 本1：テーマA（商品紹介・買取実績・相場系）
===========================

## テーマ
（テーマを1行で）

{SCRIPT_FORMAT}

===========================
# 本2：テーマB（知識・真贋・希少性系）
===========================

## テーマ
（テーマを1行で）

{SCRIPT_FORMAT}
""".strip()

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=6000,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}]
    )

    return product, response.content[0].text


def save_script(content: str, name: str) -> str:
    output_dir = os.path.join(BASE_DIR, "output")
    os.makedirs(output_dir, exist_ok=True)
    safe_name = name.replace(" ", "_").replace("/", "_")[:40]
    output_path = os.path.join(output_dir, f"{safe_name}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    return output_path


def main():
    # --product フラグで商品モード
    if "--product" in sys.argv:
        idx = sys.argv.index("--product")
        product = " ".join(sys.argv[idx + 1:]).strip() if idx + 1 < len(sys.argv) else ""
        if not product:
            print("商品情報を入力してください（例：バーキン25 トゴ ゴールド）")
            product = input("商品：").strip()
        if not product:
            print("商品情報が入力されていません。終了します。")
            sys.exit(1)

        print(f"\n2本分の台本を生成中...（商品：{product}）\n")
        _, scripts = generate_two_scripts(product)
        print(scripts)
        path = save_script(scripts, f"{product}_2本セット")
        print(f"\n保存先: {path}")

    # 引数あり → テーマ指定モード（従来通り）
    elif len(sys.argv) > 1:
        topic = " ".join(sys.argv[1:])
        print(f"\n台本を生成中...（テーマ：{topic}）\n")
        script = generate_script(topic)
        print(script)
        path = save_script(script, topic)
        print(f"\n保存先: {path}")

    # 引数なし → 対話形式でモード選択
    else:
        print("モードを選択してください")
        print("  1: テーマ指定（例：バーキンの相場）")
        print("  2: 商品指定で2本同時生成")
        mode = input("モード (1/2): ").strip()

        if mode == "2":
            print()
            print("商品情報を入力してください（LINEの内容をそのままコピペOK）")
            print("入力が終わったら空行でEnterを2回押してください")
            print("─" * 40)
            lines = []
            while True:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
            product = "\n".join(lines).strip()
            if not product:
                print("商品情報が入力されていません。終了します。")
                sys.exit(1)
            # ファイル名用に1行に圧縮
            product_name = " ".join(product.splitlines())[:40]
            print(f"\n2本分の台本を生成中...\n")
            _, scripts = generate_two_scripts(product)
            print(scripts)
            path = save_script(scripts, f"{product_name}_2本セット")
            print(f"\n保存先: {path}")
        else:
            print("テーマを入力してください（例：バーキンの相場、本物と偽物の見分け方）")
            topic = input("テーマ：").strip()
            if not topic:
                print("テーマが入力されていません。終了します。")
                sys.exit(1)
            print(f"\n台本を生成中...（テーマ：{topic}）\n")
            script = generate_script(topic)
            print(script)
            path = save_script(script, topic)
            print(f"\n保存先: {path}")


if __name__ == "__main__":
    main()
