"""
TBT エルメス専門アカウント — Instagram リール台本生成スクリプト

使い方:
    # テーマ指定モード（テロップリール）
    python3.11 reel_script_generator.py "バーキンの相場"

    # 商品モード（1商品→2テーマのテロップリール台本を同時出力）
    python3.11 reel_script_generator.py --product "バーキン25 トゴ ゴールド"

    # トークリールモード（社長が口頭で読み上げる台本）
    python3.11 reel_script_generator.py --talk "バーキンの査定で損する理由"

    python3.11 reel_script_generator.py  # 対話形式で入力
"""

import sys
import os
import subprocess
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

## キャプション（Instagram投稿用）
※（一言コメント：）の部分だけを生成すること。専門家目線で、その商品ならではの魅力・希少性・相場感を2〜4行で。ハッシュタグ不要。固定部分はそのまま出力すること。

エルメス専門買取・販売のTBTです。

（一言コメント：ここを生成する）

クローゼットに眠ったままのエルメス、
ありませんか？

相場が分からなくて、
なんとなく後回しにしていませんか？

TBTはエルメス専門だから、
素材・刻印・カラーまで正確に査定。
相場より高く、納得できる価格でお買取りします。

まずはLINEで写真を送るだけ。
査定は無料・売らなくてもOK。

希少なエルメスの卸も手がける、
業界に精通したプロが査定します。

プロフィールURLの公式LINEからお気軽にどうぞ。

─────────────
株式会社TBT
📍 東京都台東区蔵前4丁目21-9 蔵前ATビル302
📞 090-6368-7636
─────────────

---
⚠️ 編集メモ（投稿前に確認）
- テロップの言い回しを自分の言葉に直す
- 1行が長すぎる場合は分割する
- 【★】の引っ張り行は特に自然な言葉になっているか確認する
---
""".strip()


TALK_REEL_FORMAT = """
## 採用したテンプレートと理由
テンプレート：②コールドリーディング＋解決策提示型 or ③コールドリーディング＋問題拡張型
理由（なぜこのテーマにこの型が合うか）：

---

## 台本

【タイトル/問題提起｜冒頭3秒・画面テロップ＋口頭】
（常識破壊＋ネガティブ訴求で止める。例：「○○は絶対ダメです」「○○してる人は損してます」）
（タイトルテロップと口頭の一言をセットで書く）


【コールドリーディング】
（ターゲットが心の中で思っていることをそのまま代弁する）
（心情・悩み・口癖を言葉にして「これ自分のことだ」と思わせる）


【答えを言わない結論】
（抽象度の高い結論を述べる。具体的な答えはまだ言わない）
（例：「大事なのは○○なんです」「みんなここを間違えてる」）
（※具体的に言いすぎると離脱する。曖昧さが続きを読ませる）


【具体的内容】（テンプレート②は解決策へ / テンプレート③は問題拡張へ）
（業界の裏側からの意外な事実・根拠・問題の深掘り）
（田畑さんの権威性を自然に入れる）
（1センテンス = 2〜3秒。短い文を積み重ねるテンポ感）


【解決策 or 問題拡張の着地】
（②型：TBTならどう解決できるか。知識として語る）
（③型：問題を放置した場合の悪い未来を提示してから着地）


【まとめ｜簡潔に】
（フォロー誘導か次回への引きで締める。LINE誘導・高価買取訴求は一切不要）

---

## 撮影・演出メモ
（社長がどこで・どんな状況で話すか。カメラとの距離感・見せたいものなど）
""".strip()


def generate_talk_reel_script(topic: str) -> str:
    """eduGateフレームワーク（否定フック優先＋コールドリーディング）でトークリール台本を生成する"""
    brief = load_brief()

    system_prompt = f"""
# Role（役割）
あなたはエルメス専門買取・販売会社「TBT」のInstagramトークリール台本ライターです。

# Mission（目的）
社長・田畑雄一郎（29歳）が顔出しで読み上げる40〜55秒のトークリール台本を作成する。
目的はターゲット（38〜52歳の女性エルメスオーナー）をLINE登録に誘導すること。

# Constraints（制約）
- 以下のブランドブリーフを必ず参照する
- 「教える先生」ではなく「業界の裏側を知っている当事者」として語る
- 「です・ます」調、落ち着いた誠実な語り口
- NG表現（高価買取・今すぐ売って・即日現金化など）は絶対に使わない
- 声に出して読んだとき自然に聞こえる話し言葉で書く

---
{brief}
---
""".strip()

    prompt = f"""
以下のテーマでTBTのInstagramトークリール台本を作成してください。

テーマ：{topic}

■ 基本設定（尺）
- 合計：45〜55秒
- 冒頭フック：3秒
- 導入（コールドリーディング）：5〜8秒
- 本編：25〜35秒
- CTA：5〜8秒（固定文を使用）

■ テンプレートの選択
以下の2つのテンプレートからテーマに合う方を選ぶこと：
- **テンプレート②**（コールドリーディング＋解決策提示型）：悩みを代弁して解決策を示す
- **テンプレート③**（コールドリーディング＋問題拡張型）：悩みを代弁して問題の深刻さを広げてから着地

■ タイトル/問題提起（冒頭3秒 / 画面テロップ＋口頭一言）
- 常識破壊＋ネガティブ訴求で止める
- ターゲット（38〜52歳の女性エルメスオーナー）が許容できるギリギリまで攻める
- 例：「そのエルメス、安く売らされてますよ」「査定額を信じてる人、ちょっと待って」
- タイトルテロップ（画面表示）と口頭の一言をセットで作る
- ※否定・警告・意外性型を優先。弱いフックは絶対NG
- ターゲットの「今いる場所」の心理を直撃すること：
  - 「問い合わせたいけど営業が怖い」「査定したら売らされそう」「損してるかもしれないけど確かめる方法がわからない」
  - この不安・恐怖を1行でえぐり出す

■ コールドリーディング
- ターゲットの心の声をそのまま代弁する。「あ、これ私のことだ」と確信させる
- 遠慮なく踏み込む。「なんとなく不安」ではなく「まさにこれで困ってる」レベルまで
- 田畑さんの三重出身・自然な話し言葉を活かして、砕けた誠実さで語りかける
- 「いや、そうなんですよ」「正直に言いますね」など、距離を縮める表現を使う
- 感情軸は「持ち主目線」を貫く：「査定額が安い」ではなく「あなたのバッグが正しく見てもらえていない」
  - 「大切にしてきたものなのに」「何年も一緒にいたバッグなのに」という感情に乗せる
  - バイヤー視点（損得勘定）ではなく、所有者の誇り・悔しさ・悲しさにアクセスする

■ 答えを言わない結論（抽象度の高い結論）
- 具体的な答えはまだ言わない。抽象度を高く保つ
- 具体的に言いすぎると離脱する。曖昧さが続きを読ませる
- 例：「大事なのは○○なんです」「みんなここを間違えてる」

■ 導入（コールドリーディング）5〜8秒
以下の4ステップを自然な話し言葉でつなぐ：
1. 属性への呼びかけ（「エルメスをお持ちの方、ちょっと聞いてください」など）
2. 心情の代弁（ターゲットの口癖・負の感情を盛り込む）
   例：「今すぐ売るつもりはないけど、相場だけ知りたい」「営業されそうで怖い」
3. 行動の障壁の指摘（「〇〇だから、なかなか動けないんですよね」と寄り添う）
4. 解決策への橋渡し（「実はそれ、〜で解決できます」）

■ 本編（25〜35秒）
構成：問題提起 → 業界の裏側から見た意外な事実 → TBTならではの答え
- 田畑さんの権威性を自然に組み込む際の正確な表現：
  - 経歴：「ブランド卸の会社でエルメスをメインに担当していた（4〜5年）」
  - ※「エルメス専門の卸会社にいた」は誤り。絶対に使わない
  - 卸時代：年間数億円規模のブランド卸会社でエルメスをメインに担当（「エルメスを年間◯億卸した」とは言わない）
  - 現在のTBT実績：年商7.5億円、月間取引数50〜100件
- 「業界の裏側を知っている人」ポジションで語る
- 1センテンス = 2〜3秒（12〜20文字程度）
- 短い文を積み重ねるテンポ感

■ まとめ＋CTA（簡潔に。10〜15秒）
- TBTならどう解決できるかを知識として語る（押し売りしない）
- 高価買取訴求は一切入れない
- CTA は「安心感を与えること」が最優先。以下の型を使う：
  - 「営業は来ません。知識だけ持って帰ってください」スタイル
  - 「LINEで聞くだけでも大丈夫です」「売らなくていいです、相場だけ教えます」
  - 視聴者が感じている「問い合わせへの恐怖」を取り除くことがゴール
  - ただし直接的なLINE誘導文（「写真3枚を送るだけで〜」）は絶対に使わない
- 「次の投稿では〜」のような予告は入れない（投稿計画はその都度変わるため）
- フォロー誘導か「気になる方は〜」程度の柔らかい締めで終わる

■ 絶対に使わないNG表現・NG行動
- 今すぐ売った方がいい / どこよりも高価買取 / 即日現金化
- 今なら高い / 限定 / 急いでください
- 「写真3枚をLINEに送るだけで〜」などのLINE誘導文（絶対に入れない）

以下の形式で出力してください：

---
## テーマ
{topic}

{TALK_REEL_FORMAT}
""".strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


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
        model="claude-sonnet-4-6",
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
        model="claude-sonnet-4-6",
        max_tokens=6000,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}]
    )

    return product, response.content[0].text


def evaluate_talk_reel(script: str, topic: str) -> tuple[str, float]:
    """STEP04評価プロンプトで台本を採点する。(評価テキスト, 合計点数)を返す"""
    prompt = f"""
以下のTBT Instagramトークリール台本を評価してください。

テーマ：{topic}

---
{script}
---

【評価基準】
ターゲット：38〜52歳の女性エルメスオーナー（問い合わせたいが営業が怖い・売らされそうで動けない層）

**評価軸1：フックの強さ（0〜5点）**
- ターゲットの「今いる場所」の心理（営業怖い・損してるかも・正しく見てもらえてない）に直撃しているか
- 20文字以内で続きを見たくなるか
- 否定・警告・意外性型になっているか

**評価軸2：感情共感度（0〜5点）**
- コールドリーディングが「これ私のことだ」と確信させるレベルか
- 感情軸が「持ち主目線」（所有者の誇り・悔しさ）になっているか（バイヤー視点はNG）
- 「大切にしてきたのに正しく見てもらえていない」という感情に乗れているか

**評価軸3：行動喚起（0〜5点）**
- CTAが「問い合わせへの恐怖」を先に取り除いているか
- 「営業されそう」「売らされそう」という警戒心を解消できているか
- 行動する理由と安心感が両方揃っているか

**出力形式（必ずこの形式で）：**
## 評価結果

**フックの強さ：X.X/5**
→（改善ポイントを2〜3行で。具体的に）

**感情共感度：X.X/5**
→（改善ポイントを2〜3行で。具体的に）

**行動喚起：X.X/5**
→（改善ポイントを2〜3行で。具体的に）

**合計：X.X/15**
→ 次の1点を直すと最も点が上がる：（1行で具体的に）
""".strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )

    result = response.content[0].text

    # 合計点を抽出
    import re
    match = re.search(r"合計：([\d.]+)/15", result)
    score = float(match.group(1)) if match else 0.0

    return result, score


def generate_improved_script(topic: str, prev_script: str, evaluation: str) -> str:
    """評価フィードバックを反映してトークリール台本を再生成する"""
    brief = load_brief()

    system_prompt = f"""
# Role（役割）
あなたはエルメス専門買取・販売会社「TBT」のInstagramトークリール台本ライターです。

# Mission（目的）
社長・田畑雄一郎（29歳）が顔出しで読み上げる40〜55秒のトークリール台本を作成する。
目的はターゲット（38〜52歳の女性エルメスオーナー）をLINE登録に誘導すること。

# Constraints（制約）
- 以下のブランドブリーフを必ず参照する
- 「教える先生」ではなく「業界の裏側を知っている当事者」として語る
- 「です・ます」調、落ち着いた誠実な語り口
- NG表現（高価買取・今すぐ売って・即日現金化など）は絶対に使わない
- 声に出して読んだとき自然に聞こえる話し言葉で書く

---
{brief}
---
""".strip()

    prompt = f"""
以下の台本を評価フィードバックに基づいて改善・再生成してください。

テーマ：{topic}

---
【前回の台本】
{prev_script}

---
【評価フィードバック】
{evaluation}

---

上記のフィードバックを全て反映して、同じテーマで台本を再生成してください。
特に点数が低かった軸を重点的に改善すること。

以下の形式で出力してください：

---
## テーマ
{topic}

{TALK_REEL_FORMAT}
""".strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


def save_script(content: str, name: str, is_talk: bool = False) -> str:
    from datetime import date
    subdir = "talk_reels" if is_talk else "telop_reels"
    output_dir = os.path.join(BASE_DIR, "output", subdir)
    os.makedirs(output_dir, exist_ok=True)
    safe_name = name.replace(" ", "_").replace("/", "_")[:40]
    datestamp = date.today().strftime("%Y%m%d")
    output_path = os.path.join(output_dir, f"{datestamp}_{safe_name}.md")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    subprocess.run(["open", "-a", "Obsidian", output_path])
    return output_path


def main():
    # --talk フラグでトークリールモード
    if "--talk" in sys.argv:
        idx = sys.argv.index("--talk")
        topic = " ".join(sys.argv[idx + 1:]).strip() if idx + 1 < len(sys.argv) else ""
        if not topic:
            print("テーマを入力してください（例：バーキンの査定で損する理由）")
            topic = input("テーマ：").strip()
        if not topic:
            print("テーマが入力されていません。終了します。")
            sys.exit(1)

        print(f"\nトークリール台本を生成中...（テーマ：{topic}）\n")
        script = generate_talk_reel_script(topic)
        print(script)
        path = save_script(script, f"talk_{topic}", is_talk=True)
        print(f"\n保存先: {path}")

        # 自動評価
        print("\n台本を評価中...\n")
        evaluation, score = evaluate_talk_reel(script, topic)
        print(evaluation)

        if score < 12.0:
            ans = input(f"\n合計 {score}/15 — 改善して再生成しますか？ (y/n): ").strip().lower()
            if ans == "y":
                print("\n改善版を生成中...\n")
                improved = generate_improved_script(topic, script, evaluation)
                print(improved)
                path = save_script(improved, f"talk_{topic}_v2", is_talk=True)
                print(f"\n保存先: {path}")
        else:
            print(f"\n合計 {score}/15 — 品質基準クリア。")

    # --product フラグで商品モード
    elif "--product" in sys.argv:
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

    # 引数あり → テーマ指定モード（テロップリール）
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
        print("  1: テーマ指定（テロップリール）")
        print("  2: 商品指定で2本同時生成（テロップリール）")
        print("  3: トークリール（社長が読み上げる台本）← 生成後に自動評価・改善ループあり")
        print("  4: 台本を評価する（ファイルパスを指定）")
        mode = input("モード (1/2/3/4): ").strip()

        if mode == "4":
            file_path = input("評価するmdファイルのパスを入力：").strip()
            topic = input("テーマを入力：").strip()
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    script = f.read()
            except FileNotFoundError:
                print(f"ファイルが見つかりません: {file_path}")
                sys.exit(1)
            print("\n評価中...\n")
            evaluation, score = evaluate_talk_reel(script, topic)
            print(evaluation)

            if score < 12.0:
                ans = input(f"\n合計 {score}/15 — 改善して再生成しますか？ (y/n): ").strip().lower()
                if ans == "y":
                    print("\n改善版を生成中...\n")
                    improved = generate_improved_script(topic, script, evaluation)
                    print(improved)
                    path = save_script(improved, f"talk_{topic}_v2", is_talk=True)
                    print(f"\n保存先: {path}")
            else:
                print(f"\n合計 {score}/15 — 品質基準クリア。")

        elif mode == "3":
            print("テーマを入力してください（例：バーキンの査定で損する理由）")
            topic = input("テーマ：").strip()
            if not topic:
                print("テーマが入力されていません。終了します。")
                sys.exit(1)
            print(f"\nトークリール台本を生成中...（テーマ：{topic}）\n")
            script = generate_talk_reel_script(topic)
            print(script)
            path = save_script(script, f"talk_{topic}", is_talk=True)
            print(f"\n保存先: {path}")

            # 自動評価
            print("\n台本を評価中...\n")
            evaluation, score = evaluate_talk_reel(script, topic)
            print(evaluation)

            if score < 12.0:
                ans = input(f"\n合計 {score}/15 — 改善して再生成しますか？ (y/n): ").strip().lower()
                if ans == "y":
                    print("\n改善版を生成中...\n")
                    improved = generate_improved_script(topic, script, evaluation)
                    print(improved)
                    path = save_script(improved, f"talk_{topic}_v2", is_talk=True)
                    print(f"\n保存先: {path}")
            else:
                print(f"\n合計 {score}/15 — 品質基準クリア。")

        elif mode == "2":
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
