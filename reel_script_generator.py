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



TALK_REEL_FORMAT = """
## 採用したフックの型と理由
型：
理由（なぜこのターゲットに刺さるか）：

---

## 台本

【フック｜0〜3秒】
（常識破壊＋ネガティブ訴求で止める。例：「○○は絶対ダメです」「○○してる人は損してます」）


【コールドリーディング｜3〜10秒】
（ターゲットが心の中で思っていることをそのまま代弁する）
（心情・悩み・口癖を言葉にして「これ自分のことだ」と思わせる）


【答えを言わない結論｜10〜15秒】
（抽象度の高い結論を述べる。具体的な答えはまだ言わない）
（例：「大事なのは○○なんです」「みんなここを間違えてる」）
（※具体的に言いすぎると離脱する。曖昧さが続きを読ませる）


【具体的内容｜15〜40秒】
（業界の裏側からの意外な事実・根拠）
（田畑さんの権威性を自然に入れる）
（1センテンス = 2〜3秒。短い文を積み重ねるテンポ感）


【解決策・まとめ｜40〜55秒】
（TBTならどう解決できるかを知識として語る）
（フォロー誘導か「気になる方は〜」程度の柔らかい締めで終わる）

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

■ フック設計（冒頭3秒）
- 以下の5型から最も刺さる型を選び、その選択理由を記載すること
  1. 【禁止・警告型】「○○してる人は損してます」
  2. 【数字・実績型】「○年で○万円変わった理由」
  3. 【意外性型】「業者が教えない〜」
  4. 【ベネフィット型】「○○するだけで〜」
  5. 【問いかけ型】「○○したことありますか？」
- 否定系・警告型を優先推奨
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
  - 「LINEで聞くだけでも大丈夫です」「売らなくていい、相場だけ教えます」
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


def generate_direction_sheet(script: str, topic: str) -> str:
    """台本・撮影メモを元にPremiere Pro向けの編集ディレクション指示書を生成する"""

    prompt = f"""
以下はInstagramトークリール（縦型ショート動画）の台本です。
この台本を元に、Premiere Proで編集する際の**編集ディレクション指示書**を作成してください。

テーマ：{topic}

---
{script}
---

以下の形式で出力してください：

---

# 編集ディレクション指示書
## テーマ：{topic}

---

## 基本設定
- **完成尺：** 45〜55秒
- **画面サイズ：** 1080×1920（縦型9:16）
- **フレームレート：** 30fps推奨
- **テロップ文字サイズ：** 本文60〜70px程度（画面幅の80%以内）

---

## カット構成
台本のセクションごとに、どんなカットを使うかを指示する。
各セクションに「使用カット（引き/寄り）」「推奨テンポ」を記載。

| セクション | 時間 | 使用カット | テンポ・編集メモ |
|---|---|---|---|
（台本の各セクションから生成）

---

## テロップ指示
強調テロップを入れるべき箇所を台本から抽出し、以下の形式で列挙する。
- **強調テロップ：** 視聴者の目を止めるキーワードや数字。大きく・色付きで表示する
- **補足テロップ：** 話の理解を補助するための小さめのテロップ

### 強調テロップ一覧
（台本の重要ワードを抽出。何秒頃・どんなスタイルで表示するかを記載）

### 補足テロップ一覧
（撮影メモのテロップ案を元に記載）

---

## BGM指示
- **ジャンル・雰囲気：**（台本のトーンに合うBGMの方向性を1〜2行で）
- **音量：**（ナレーションを邪魔しない目安を記載）
- **フェードアウト：**（エンドのタイミング）

---

## Premiere Pro 作業チェックリスト
編集者が上から順に作業できるよう、ステップを列挙する。

- [ ] シーケンス設定（1080×1920、30fps）
- [ ] 素材の読み込みと粗編み
- [ ] ジャンプカット編集（各カット1〜3秒を目安に）
- [ ] Vrewで生成したSRTファイルをインポート
- [ ] テロップスタイル適用（強調箇所を上記リストで確認）
- [ ] BGM挿入・音量調整（音声に対して-20〜-25dB目安）
- [ ] カラーグレーディング（肌色自然・背景落ち着いたトーン）
- [ ] エンドカード・CTAテキスト挿入
- [ ] 書き出し設定（H.264、最大ビットレート）
- [ ] 最終確認（スマホ実機で再生・テロップ可読性チェック）

---

## 備考・注意事項
（撮影メモから特記事項を抽出して記載）
""".strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


def generate_stories(script: str, topic: str, chars: int = 500) -> str:
    """リール台本からInstagramストーリーズ投稿テキストを生成する（eduGate Chapter4準拠）"""
    brief = load_brief()

    system_prompt = f"""
# Role（役割）
あなたはInstagramのストーリーズ投稿作成のエキスパートです。
TBT（エルメス専門買取・販売）のリール台本を元に、ストーリーズ用の投稿テキストを作成します。

# ストーリーズの真の役割
ストーリーズは「ファン化」や「マネタイズ」のためにあるのではありません。
真の役割は「リールのリーチ先の整合性を担保するためのシグナル集め」です。
目的：「リール動画を、興味関心の高い層に正確に届けるための土台作り」

# 作成の原則
1. リールの台本をベースに作成する（同じリサーチ・同じターゲットで効率的に作れる）
2. リールの核心部分を抽出し、重要なポイントを残す
3. 指定文字数（{chars}文字程度）に調整する（冗長な表現を削除）
4. ストーリーズ向けに読みやすく、視覚的に分かりやすい構成にする
5. 閲覧率を維持することが最優先

# NG行動（絶対にやらない）
- 外部リンクを貼る（インスタ側からリーチを抑制される仕様）
- 集客活動をガンガンする（閲覧率が下がる）
- ファン化目的で使う（ストーリーズは「照準合わせの場所」）

---
{brief}
---
""".strip()

    prompt = f"""
以下のリール台本を元に、TBTのInstagramストーリーズ用の投稿テキストを作成してください。

テーマ：{topic}
目標文字数：{chars}文字程度
目的：シグナル集め・リーチ精度向上

---
【リール台本】
{script}
---

【作成の流れ】
1. リールの核心部分を抽出（重要なポイントを残す）
2. {chars}文字程度に調整（冗長な表現を削除）
3. ストーリーズ向けに最適化（読みやすさ・視覚的に分かりやすい構成）
4. ターゲット（38〜52歳の女性エルメスオーナー）に刺さる内容にする
5. リンクは貼らない・集客活動は控える・一貫した発信を維持

以下の形式で出力してください：

---
## ストーリーズ投稿テキスト（{chars}文字）

（作成したテキスト）

---
## 作成のポイント
- 抽出した核心部分：
- 文字数調整のポイント：
- ストーリーズ向け最適化：

## 投稿メモ
- 推奨投稿タイミング：（リール投稿後のタイミングなど）
- 注意事項：（NG行動の確認）
""".strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


def generate_threads(script: str, topic: str) -> str:
    """リール台本からThreadsのツリー型投稿を生成する（eduGate Chapter6準拠）"""
    brief = load_brief()

    system_prompt = f"""
# Role（役割）
あなたはInstagram連動のThreads投稿作成のエキスパートです。
TBT（エルメス専門買取・販売）のリール台本を元に、Threads用ツリー型投稿を作成します。

# Threadsの正しい役割
Threadsの目的は「インスタへの回遊を起こすこと」です。
Threads投稿が伸びると → インスタのフォロワーが同時に増える・インスタへの回遊が起きる。
Threads単体でマネタイズしようとする運用は絶対NG。

# NG運用（絶対にやらない）
- 短文戦略（内容がなく短いだけ）
- 大量ポスト（1日3投稿以上。初速が分散する）
- Threads単体でのマネタイズ・集客
- 外部リンクをポスト内に貼る（ポストの評価が下がる）

# ツリー型投稿の構造
【1段目：フック（1〜4行の短文）】
- 「極論」と「否定」で振り切る
- 例：「バーキンを査定に出すのは間違いです」「エルメス買取、やめました」
- 1段目だけで「なんだ？」と思わせ、2段目をタップさせる

【2段目以降：内容（リール台本の8割を流用）】
- 2段目に続きを書くことで「詳細クリック」という高評価が入り、投稿がリーチしやすくなる
- リール台本の内容を文章形式に変換（話し言葉のまま活かす）
- 最後にインスタへサラッと誘導（「詳しくはインスタで話しています」程度）
- プロフィールのリンクへ誘導する一文を自然に入れる

---
{brief}
---
""".strip()

    prompt = f"""
以下のリール台本を元に、TBTのThreadsツリー型投稿を作成してください。

テーマ：{topic}

---
【リール台本】
{script}
---

【1段目の要件】
- 1〜4行の短文
- 「極論・否定」系のフックで振り切る
- 読んだ瞬間「続きが気になる」状態を作る
- TBTのターゲット（38〜52歳の女性エルメスオーナー）の心理に直撃する
- 具体的な情報は絶対に書かない（曖昧さが2段目をタップさせる）

【2段目以降の要件】
- リール台本の内容を文章形式に変換（8割流用）
- テンポよく読めるよう短い文を積み重ねる（1文 = 20〜30文字目安）
- 最後にインスタへのサラッとした誘導を入れる
- リンクは本文中に貼らない（プロフィール誘導のみ）

以下の形式で出力してください：

---
## 1段目（フック）

（1〜4行）

---

## 2段目以降（内容）

（本文）

（インスタへの誘導）

---
## 投稿メモ
- フックの狙い：
- インスタ誘導の意図：
- 投稿タイミング：（リールと合わせた推奨タイミング）
""".strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


def analyze_reference_reel(transcript: str) -> str:
    """参考リールの書き起こしを分析し、TBTに転用できるパターンを抽出する"""
    brief = load_brief()

    prompt = f"""
以下は競合・参考アカウントのInstagramトークリールの書き起こしです。
TBT（エルメス専門買取・販売）の台本制作に活かすため、徹底的に分析してください。

---
【書き起こし】
{transcript}
---

【分析の観点】

**1. フック分析**
- 使われているフックの型（禁止・警告 / 数字・実績 / 意外性 / ベネフィット / 問いかけ）
- フックが「止まる理由」を1〜2行で説明
- 20文字以内に圧縮するとどうなるか

**2. 感情・心理構造の分析**
- 視聴者のどんな感情・不安・欲求に訴えているか
- コールドリーディング（心情代弁）はどこで使われているか
- 「自分のことだ」と思わせる表現はどれか

**3. 構成・テンポの分析**
- 全体の構成（フック→導入→本編→CTAの流れ）
- 1センテンスの長さ・テンポ感の特徴
- 「間」や言葉の繰り返しがどう使われているか

**4. TBTに転用できるパターン（最重要）**
以下を具体的に抽出してください：
- そのまま使えるフレーズ・言い回し（エルメス文脈に置き換えて）
- 構造として盗める部分（どのセクションのどんな組み立て方）
- 避けるべき点（TBTのブランドブリーフと合わない要素）

---
{brief}
---

**5. 推奨アクション**
このリールの分析を踏まえ、TBTで試すべき台本テーマを3つ提案してください。
""".strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )

    return response.content[0].text


def generate_vrew_script(narration: str) -> str:
    """読み上げテキストをVrew原稿形式（1行=1キャプション、///=行内改行）に変換する"""
    prompt = f"""
以下は動画の読み上げ原稿です。Vrew動画編集ソフト用の原稿形式に変換してください。

【ルール】
- 1行 = 画面に表示される1キャプション（Vrewの1発話セグメント）
- 行内改行は「///」で表す
- 1行あたり7〜10文字を目安にする（短い方がテンポよく読める）
- 句読点・助詞（は／が／を／に／で／と）の直後など、自然なリズムで区切る
- 素材名・固有名詞の列挙（例：クロコ、トゴ、エプソン）は///で繋いで1行にまとめる
- 3文字以下の断片が単独で残らないよう///で前後と繋ぐ
- 1行が15文字を超えたら必ず///で分割する

【悪い例】
クリーニングやコーティングをしてから持ち込もうとしてたら、
（28文字で長すぎる。助詞「から」の後などで分割すべき）

【良い例】
クリーニングやコーティングを///してから持ち込もうと///してたら、

---
{narration}
---

原稿テキストのみを出力してください（説明・見出し・コメント不要）。
""".strip()

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    lines = response.content[0].text.strip().splitlines()
    return '\n'.join(line + '///' if line.strip() else line for line in lines)


def _extract_narration(script: str) -> str:
    """台本から読み上げ本文のみを抽出する（ヘッダー・演出メモ・区切り線を除去）"""
    in_script = False
    lines = []

    for line in script.splitlines():
        stripped = line.strip()

        if stripped == "## 台本":
            in_script = True
            continue

        if in_script and "撮影・演出メモ" in stripped:
            break

        if not in_script:
            continue

        # セクションヘッダー（【フック｜0〜3秒】など）はスキップ
        if stripped.startswith("【") and "】" in stripped:
            continue

        # 区切り線・マークダウン見出しはスキップ
        if stripped in ("---", "---"):
            continue
        if stripped.startswith("##"):
            continue

        lines.append(line)

    # 3行以上連続する空行を1行に圧縮
    result = "\n".join(lines)
    import re
    result = re.sub(r'\n{3,}', '\n\n', result).strip()
    return result


def _timestamp() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d_%H%M")


def save_talk_content(content: str, topic: str, filename: str, folder: str = "") -> str:
    """トークリール・ストーリーズ・Threads をテーマ別フォルダに保存する。

    folder を指定するとそのフォルダに追記保存（台本→stories→threads を同じフォルダへ）。
    folder 未指定時は output/{YYYYMMDD_HHMM}_{topic}/ を新規作成する。
    """
    if not folder:
        safe_topic = topic.replace(" ", "_").replace("/", "_")[:40]
        folder = os.path.join(BASE_DIR, "output", f"{_timestamp()}_{safe_topic}")
    os.makedirs(folder, exist_ok=True)
    output_path = os.path.join(folder, filename)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)
    subprocess.run(["open", "-a", "Obsidian", output_path])
    return output_path



def _post_approval_flow(script: str, topic: str, folder: str):
    """承認後：読み上げテキスト・Vrew原稿・編集指示書をファイル保存 → ストーリーズ・Threads生成オファー"""
    narration = _extract_narration(script)
    path = save_talk_content(narration, topic, "読み上げ用.md", folder=folder)
    print(f"\n読み上げ用テキストを保存しました: {path}")

    vrew = generate_vrew_script(narration)
    vrew_path = os.path.join(folder, "vrew原稿.md")
    with open(vrew_path, "w", encoding="utf-8") as f:
        f.write(vrew)
    print(f"Vrew原稿を保存しました: {vrew_path}")

    print("\n編集ディレクション指示書を生成中...\n")
    direction = generate_direction_sheet(script, topic)
    direction_path = save_talk_content(direction, topic, "editing_direction.md", folder=folder)
    print(f"編集ディレクション指示書を保存しました: {direction_path}")

    _offer_stories_threads(script, topic, folder=folder)


def _run_talk_reel_flow(topic: str) -> tuple[str, str]:
    """トークリール生成→評価→承認ループを実行し、(最終台本, 保存フォルダ) を返す"""
    print(f"\nトークリール台本を生成中...（テーマ：{topic}）\n")
    script = generate_talk_reel_script(topic)
    print(script)
    path = save_talk_content(script, topic, "台本.md")
    folder = os.path.dirname(path)
    print(f"\n保存先: {path}")

    print("\n台本を評価中...\n")
    evaluation, score = evaluate_talk_reel(script, topic)
    print(evaluation)

    final_script = script
    revision = 0

    while True:
        ans = input(f"\n合計 {score}/15 — この台本で進めますか？ (y/n): ").strip().lower()
        if ans == "y":
            break
        revision += 1
        extra = input("改善の方向性を指示してください（Enterでスキップ）：").strip()
        eval_with_extra = f"{evaluation}\n\n【追加指示】{extra}" if extra else evaluation
        print("\n改善版を生成中...\n")
        final_script = generate_improved_script(topic, final_script, eval_with_extra)
        print(final_script)
        suffix = "台本_改善版.md" if revision == 1 else f"台本_改善版{revision}.md"
        path = save_talk_content(final_script, topic, suffix, folder=folder)
        print(f"\n保存先: {path}")
        print("\n再評価中...\n")
        evaluation, score = evaluate_talk_reel(final_script, topic)
        print(evaluation)

    return final_script, folder


def _offer_stories_threads(script: str, topic: str, folder: str = ""):
    """ストーリーズ・Threads生成をオファーし、選択に応じて生成する"""
    print("\n" + "─" * 40)
    ans = input("このトークリールを元にストーリーズ・Threads投稿を生成しますか？ (y/n): ").strip().lower()
    if ans != "y":
        return

    chars_input = input("ストーリーズの文字数 (300/500/1000) [デフォルト500]: ").strip()
    chars = int(chars_input) if chars_input in ("300", "500", "1000") else 500

    print(f"\nストーリーズを生成中...（{chars}文字）\n")
    stories_content = generate_stories(script, topic, chars)
    print(stories_content)
    stories_path = save_talk_content(stories_content, topic, f"stories_{chars}文字.md", folder=folder)
    print(f"\n保存先: {stories_path}")

    print("\nThreadsツリー投稿を生成中...\n")
    threads_content = generate_threads(script, topic)
    print(threads_content)
    threads_path = save_talk_content(threads_content, topic, "threads.md", folder=folder)
    print(f"\n保存先: {threads_path}")


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

        final_script, folder = _run_talk_reel_flow(topic)
        _post_approval_flow(final_script, topic, folder)

    # 引数なし → 対話形式でモード選択
    else:
        print("モードを選択してください")
        print("  3: トークリール（社長が読み上げる台本）← 生成後に自動評価・改善ループあり")
        print("  4: 台本を評価する（ファイルパスを指定）")
        print("  5: ストーリーズ投稿生成（既存台本ファイルから転用）")
        print("  6: Threadsツリー投稿生成（既存台本ファイルから転用）")
        print("  7: 参考リール分析（書き起こしテキストからパターン抽出→台本生成）")
        mode = input("モード (3/4/5/6/7): ").strip()

        if mode == "7":
            print("参考リールの書き起こしテキストを貼り付けてください。")
            print("（transcribe_reel.py の出力、または手動の書き起こし）")
            print("入力が終わったら空行でEnterを2回押してください")
            print("─" * 40)
            lines = []
            while True:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
            transcript = "\n".join(lines).strip()
            if not transcript:
                print("テキストが入力されていません。終了します。")
                sys.exit(1)

            print("\n分析中...\n")
            analysis = analyze_reference_reel(transcript)
            print(analysis)

            # 分析結果を保存
            from datetime import date
            output_dir = os.path.join(BASE_DIR, "output", "reference_analysis")
            os.makedirs(output_dir, exist_ok=True)
            datestamp = date.today().strftime("%Y%m%d")
            import time as _time
            output_path = os.path.join(output_dir, f"{datestamp}_analysis_{int(_time.time()) % 10000}.md")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(f"# 参考リール分析\n\n{analysis}")
            subprocess.run(["open", "-a", "Obsidian", output_path])
            print(f"\n保存先: {output_path}")

            # 提案されたテーマで台本生成するか確認
            ans = input("\n分析結果を元にトークリール台本を生成しますか？ (y/n): ").strip().lower()
            if ans == "y":
                topic = input("テーマを入力（提案から選ぶか自由入力）: ").strip()
                if topic:
                    final_script, folder = _run_talk_reel_flow(topic)
                    _post_approval_flow(final_script, topic, folder)

        elif mode == "6":
            file_path = input("台本mdファイルのパスを入力：").strip()
            topic = input("テーマを入力：").strip()
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    script = f.read()
            except FileNotFoundError:
                print(f"ファイルが見つかりません: {file_path}")
                sys.exit(1)
            print("\nThreadsツリー投稿を生成中...\n")
            threads_content = generate_threads(script, topic)
            print(threads_content)
            path = save_talk_content(threads_content, topic, "threads.md")
            print(f"\n保存先: {path}")

        elif mode == "5":
            file_path = input("台本mdファイルのパスを入力：").strip()
            topic = input("テーマを入力：").strip()
            chars_input = input("文字数 (300/500/1000) [デフォルト500]: ").strip()
            chars = int(chars_input) if chars_input in ("300", "500", "1000") else 500
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    script = f.read()
            except FileNotFoundError:
                print(f"ファイルが見つかりません: {file_path}")
                sys.exit(1)
            print(f"\nストーリーズを生成中...（{chars}文字）\n")
            stories_content = generate_stories(script, topic, chars)
            print(stories_content)
            path = save_talk_content(stories_content, topic, f"stories_{chars}文字.md")
            print(f"\n保存先: {path}")

        elif mode == "4":
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

            # 既存ファイルのディレクトリを改善版の保存先にする
            folder = os.path.dirname(os.path.abspath(file_path))
            final_script = script
            revision = 0
            while True:
                ans = input(f"\n合計 {score}/15 — この台本で進めますか？ (y/n): ").strip().lower()
                if ans == "y":
                    break
                revision += 1
                extra = input("改善の方向性を指示してください（Enterでスキップ）：").strip()
                eval_with_extra = f"{evaluation}\n\n【追加指示】{extra}" if extra else evaluation
                print("\n改善版を生成中...\n")
                final_script = generate_improved_script(topic, final_script, eval_with_extra)
                print(final_script)
                suffix = "台本_改善版.md" if revision == 1 else f"台本_改善版{revision}.md"
                path = save_talk_content(final_script, topic, suffix, folder=folder)
                print(f"\n保存先: {path}")
                print("\n再評価中...\n")
                evaluation, score = evaluate_talk_reel(final_script, topic)
                print(evaluation)
            _post_approval_flow(final_script, topic, folder)

        elif mode == "3":
            print("テーマを入力してください（例：バーキンの査定で損する理由）")
            topic = input("テーマ：").strip()
            if not topic:
                print("テーマが入力されていません。終了します。")
                sys.exit(1)
            final_script, folder = _run_talk_reel_flow(topic)
            _post_approval_flow(final_script, topic, folder)



if __name__ == "__main__":
    main()
