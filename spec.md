前提だけ先に明確にします。
この設計では、**Geminiを動画理解の主担当**、**Claude / Claude Codeを要件判断・構成生成・ローカル実装オーケストレーション担当**に置きます。理由は、Geminiの公式仕様で動画理解、`MM:SS` タイムスタンプ参照、構造化出力、Files API、コンテキストキャッシュが明示されている一方、Anthropicの現行モデル仕様はテキストと画像入力、構造化出力、ツール利用を中心に案内しているためです。Gemini Batch APIは大量の非緊急処理向けで、目標ターンアラウンドは24時間です。したがって、本筋の制作ラインは同期処理、バッチは後日の一括再解析用に限定します。 ([Google AI for Developers][1])

---

# spec.md

## エルメス買取向け Instagramリール自動ディレクション生成エージェント 要件定義書 v1.0

## 1. 目的

本システムは、エルメス専門買取会社のInstagramリール制作において、**動画ファイルを入力するだけで、編集ディレクション一式を半自動生成する**ことを目的とする。

運用上の狙いは次の3つ。

1. りょうの制作判断時間を削減する
2. 動画ごとの訴求品質を一定以上に揃える
3. LINE問い合わせ導線への接続率を上げる

本システムは「動画編集そのもの」を自動化するのではなく、**編集者またはCapCut作業者が迷わず着手できる制作指示書を自動生成する**ことを主目的とする。

---

## 2. スコープ

### 2.1 対象

* 入力: 商品紹介系の縦動画、または縦動画化可能な商品動画
* 商材: エルメスのバッグ・財布・小物を中心とする買取訴求動画
* 出力先: Instagram Reels
* ゴール: LINE問い合わせ誘導

### 2.2 非対象

* 真贋判定の断定
* 査定額保証
* 売買契約の成立補助
* 完全自動の動画書き出し
* ハッシュタグ生成
* 他ブランドへの汎用対応
* フレーム精度の編集自動化

注意点として、Geminiの動画参照は `MM:SS` ベースで扱う前提にし、**フレーム単位やミリ秒単位の正確なカット編集をシステム責務にしない**こと。システムが返す時間情報は「編集の起点」であり、最終微調整はCapCut側で人間が行う。 ([Google AI for Developers][1])

---

## 3. 成果物の定義

1本の入力動画に対して、最低限以下を生成する。

### 3.1 必須成果物

* `observations.json`
  動画から読み取れた事実、見えていない事実、不確実な点
* `strategy.json`
  訴求方針、フック候補、採用理由、禁止表現チェック
* `edit_plan.json`
  40秒構成、各区間の役割、テロップ、CTA、編集指示
* `caption.txt`
  投稿キャプション
* `capcut_steps.md`
  CapCut作業手順書
* `review.md`
  人間確認が必要な点の要約

### 3.2 任意成果物

* `thumbnail_copy.txt`
* `qa_notes.md`
* `run_log.json`

---

## 4. ユーザーと運用前提

### 4.1 主ユーザー

* りょう: 企画責任者、品質責任者
* 編集担当: CapCut作業者
* クライアント担当: LINE導線や投稿運用担当

### 4.2 利用シーン

* 単発動画の制作前準備
* 撮り溜め素材の一括整理
* 外注編集へのディレクション受け渡し
* 過去動画の再分析

### 4.3 成功条件

* 人がゼロから構成を考えなくてよい
* 誤認識があれば自動で「要確認」に落ちる
* 商品訴求が競合っぽい無難コピーで終わらない
* LINE誘導が毎回自然に接続される

---

## 5. ビジネス要件

### 5.1 コンテンツ制約

* 完成尺: 40秒固定
* AI音声前提
* ハッシュタグなし
* ターゲット: エルメスを売りたい30〜50代女性
* ゴール: LINE問い合わせ誘導

### 5.2 ブランド制約

* 過度に煽りすぎない
* 高級商材らしい落ち着きは残す
* 断定を避ける
* 相場や査定の話は「傾向」「見られやすい点」に留める
* 恐怖訴求だけで終わらず、相談導線へ着地させる

### 5.3 禁止表現

以下は自動検知し、出力に含めないこと。

* 真贋を断定する文言
* 査定額保証に見える文言
* 未確認の年式、素材、付属品、刻印の断定
* 「絶対」「必ず」「100%」系表現
* 誇大広告表現
* LINE誘導と無関係な煽りのみで終わる構成

---

## 6. システム全体像

### 6.1 アーキテクチャ

本システムは6層で構成する。

1. 入力受付層
   動画パス、案件ID、ブランド、任意メモを受け取る

2. 動画理解層
   Geminiに動画を渡し、観察結果をJSONで返す

3. 検証層
   観察結果をPydanticで検証し、不足・矛盾を検出する

4. 戦略生成層
   Claudeに観察結果を渡し、フック選定・構成設計を行う

5. 成果物生成層
   編集計画、テロップ、キャプション、手順書に分解する

6. レビュー制御層
   信頼度不足・禁止表現・視認不足がある場合に人レビューへ回す

### 6.2 役割分担

#### Geminiの責務

* 動画内容の観察
* 目視可能情報の抽出
* 付属品・傷・画角・音声・字幕の抽出
* タイムスタンプ付き根拠返却
* 構造化JSON出力

#### Claude / Claude Codeの責務

* 観察結果の解釈
* 訴求戦略の決定
* フック候補の採点と採用
* 40秒構成への落とし込み
* 各成果物ファイルの生成
* ローカル実装、再実行、テスト、ログ整備

GeminiはFiles APIで動画をアップロードして再利用でき、1ファイル2GB、プロジェクト合計20GB、保存期間48時間です。この仕様を前提に、動画の永続保管はローカルまたは別ストレージで行い、Gemini側は一時処理専用にすること。Claude側は構造化出力とツール利用を使って、下流生成の安定性を担保する。 ([Google AI for Developers][2])

---

## 7. 処理フロー詳細

### 7.1 正常系フロー

1. ユーザーが動画を指定する
2. システムが動画メタ情報を取得する
3. 動画をGemini Files APIにアップロードする
4. Geminiへ動画解析を依頼し、`observations.json` を取得する
5. `observations.json` をPydanticで検証する
6. 検証OKならClaudeへ渡す
7. Claudeがフック候補を複数作成し、採点して1案採用する
8. Claudeが `strategy.json` と `edit_plan.json` を生成する
9. レンダラーが `caption.txt` と `capcut_steps.md` を生成する
10. 最終チェックで問題なければ出力保存する
11. 問題があれば `needs_human_review=true` として停止する

### 7.2 異常系フロー

* 動画アップロード失敗 → リトライ3回 → 失敗ログ
* Gemini応答がスキーマ不一致 → 1回だけ再実行
* 視認情報不足 → 要人レビュー
* 禁止表現検出 → Claudeで再生成
* 出力ファイル欠損 → 失敗扱い

### 7.3 再解析フロー

* ルール変更時に過去動画へ再適用
* バッチ解析は非緊急時のみ
* バッチ時は `observations.json` までを先に大量生成し、後段は別ジョブ化する

Batch APIは大量の非緊急タスク向けで、標準リクエストと同じ役割に置かない。ここは明確に分ける。 ([Google AI for Developers][3])

---

## 8. 入力仕様

### 8.1 必須入力

* `video_path: str`
* `project_id: str`
* `brand: Literal["hermes"]`
* `platform: Literal["instagram_reels"]`

### 8.2 任意入力

* `operator_notes: str | None`
* `desired_angle: str | None`
* `target_cta: str | None`
* `campaign_tag: str | None`

### 8.3 入力前提

* mp4, mov を主対象
* 音声あり・なし両対応
* 縦動画推奨
* 画質が極端に低い場合はレビュー行き

---

## 9. 出力仕様

## 9.1 `observations.json`

最低限、以下のフィールドを持つ。

* `run_id`
* `source_video`
* `brand`
* `product_category`
* `product_family_guess`
* `product_family_confidence`
* `visible_materials`
* `visible_color`
* `visible_hardware`
* `visible_damage`
* `damage_confidence`
* `accessories_detected`
* `accessories_missing_or_unconfirmed`
* `angles_present`
* `angles_missing`
* `text_detected_on_screen`
* `speech_summary`
* `notable_timestamps`
* `uncertainty_flags`
* `evidence_notes`
* `overall_visual_quality`
* `needs_human_review`

### 9.2 `strategy.json`

* `target_persona`
* `pain_hypothesis`
* `hook_candidates[]`
* `selected_hook`
* `selected_hook_reason`
* `hook_scores`
* `content_angle`
* `cta_strategy`
* `forbidden_claim_check`
* `differentiation_note`

### 9.3 `edit_plan.json`

* `target_duration_sec`
* `segments[]`

  * `start_sec`
  * `end_sec`
  * `segment_goal`
  * `visual_instruction`
  * `subtitle_text`
  * `voiceover_text`
  * `proof_reference`
  * `transition_instruction`
* `ending_cta`
* `music_direction`
* `caption_summary`

### 9.4 `caption.txt`

* 導入1文
* 本文2〜4文
* LINE誘導1文
* ハッシュタグなし

### 9.5 `capcut_steps.md`

* 素材配置
* カット位置
* テロップ配置
* 拡大縮小
* 強調位置
* SE/BGM方針
* 最終書き出し設定

---

## 10. Gemini観察仕様

### 10.1 基本原則

Geminiには「推測」ではなく「観察」をさせる。
つまり、最初のモデル責務はコピー生成ではなく、**映像から見えた事実の抽出**である。

### 10.2 Geminiへの必須指示

Geminiプロンプトには、最低限以下を含める。

* あなたの仕事は観察であり、販促コピー作成ではない
* 画面に見えていない情報は推定しない
* 推定が必要な場合は `uncertainty_flags` に入れる
* すべての重要判断には `MM:SS` の根拠時刻を付ける
* 商品名が不明な場合は `product_family_guess` を低信頼度で返す
* 傷、角スレ、金具、内装、刻印、付属品の見え方を分離して返す
* 最後に `needs_human_review` を真偽で返す

### 10.3 Geminiの出力モード

* JSON Schema強制
* temperature低め
* 長文説明ではなく構造化出力優先

GeminiはJSON Schemaによる構造化出力に対応しているため、自由文ベースではなくスキーマ固定で実装する。コンテキストキャッシュは同じ動画に複数問い合わせる時だけ使う。 ([Google AI for Developers][4])

---

## 11. Claude戦略生成仕様

### 11.1 基本原則

Claudeには「見えた事実を売れる構成へ変換する」責務を持たせる。
Claudeは動画を直接理解する前提ではなく、**`observations.json` を唯一のソースオブトゥルースとして扱う**。

### 11.2 Claudeの仕事

* 事実と推測の分離を維持する
* フック候補を複数生成する
* 各候補をスコアリングする
* 最適フックを1本選ぶ
* 40秒構成へ落とす
* テロップ全文を作る
* CTAを自然に接続する
* 禁止表現チェックを通す

### 11.3 Claudeへの必須指示

* `observations.json` にない事実を増やさない
* 未確認情報は断定しない
* 根拠の弱い要素をフックの中心に置かない
* 出力はすべて指定スキーマに従う
* 編集者が実行できる粒度で指示を書く
* 高級感を損なう安っぽい煽りを避ける

Claude側も構造化出力対応モデルを使い、自由作文ではなくスキーマ準拠で返す。Anthropic公式でも、常に有効なJSONが必要な場合はStructured Outputsの利用が推奨されている。 ([Claude API Docs][5])

---

## 12. フック選定ロジック

### 12.1 候補生成

毎回、少なくとも以下の3系統から1本ずつ候補を出す。

* 情報ギャップ型
* 損失回避型
* 意外性型

各系統につき2案、合計6案まで生成してよい。

### 12.2 採点軸

各候補を0〜5点で採点する。

* `market_fit`
  売りたい30〜50代女性の不安と合うか
* `evidence_strength`
  動画内証拠が十分か
* `pain_intensity`
  問い合わせしたくなる痛みがあるか
* `novelty`
  ありきたりすぎないか
* `cta_connectivity`
  LINE誘導へ自然につながるか
* `brand_fit`
  高級ブランドトーンを壊さないか

### 12.3 総合点

以下で総合スコアを出す。

`total = 0.25*market_fit + 0.25*evidence_strength + 0.20*pain_intensity + 0.10*novelty + 0.10*cta_connectivity + 0.10*brand_fit`

### 12.4 採用ルール

* `evidence_strength < 3` は採用不可
* `brand_fit < 3` は採用不可
* `cta_connectivity < 2` は再生成
* 最高点が同点なら `evidence_strength` の高い方を採用

---

## 13. 40秒構成ルール

構成は原則固定テンプレートとする。

### 13.1 推奨構成

* 0〜3秒: フック
* 3〜8秒: 何の話かを明示
* 8〜18秒: 映像証拠の提示
* 18〜28秒: 査定差が出やすいポイントの説明
* 28〜36秒: 視聴者にとっての意味づけ
* 36〜40秒: LINE誘導CTA

### 13.2 セグメントごとの役割

#### Hook

* 1文で止める
* 売却損失または見落としに触れる
* 誇大断定は避ける

#### Proof

* 金具
* 角
* 内装
* 付属品
* 全体状態
  のうち、見えているものを優先

#### CTA

* 「売る前に一度見てください」
* 「LINEで写真送っていただければ確認できます」
* 「まずは状態だけでも大丈夫です」
  のように、問い合わせ障壁を下げる

---

## 14. テロップ生成ルール

### 14.1 テロップの基本

* 1画面1メッセージ
* 長すぎる説明禁止
* 読み切り優先
* 断定しすぎない
* 主観だけでなく根拠映像と結びつける

### 14.2 テロップ禁止

* 「絶対高く売れる」
* 「本物確定」
* 「今すぐ売らないと損」
* 未確認情報の断定

### 14.3 テロップトーン

* 落ち着いた警告
* 上品な不安喚起
* 査定の見られ方を可視化する言い回し
* ネット広告っぽい軽薄さを避ける

---

## 15. キャプション生成ルール

### 15.1 必須構成

* 1行目: 興味を引く一文
* 2〜4行目: 状態や査定観点の説明
* 最終行: LINE誘導

### 15.2 禁止事項

* ハッシュタグ
* 長すぎる体験談
* 本編と無関係な一般論
* 査定額保証に見える表現

### 15.3 CTA例

* 「売る前に状態の見られ方を知りたい方はLINEへ」
* 「写真3枚からでもご相談いただけます」
* 「まずは相場感だけ知りたい方もLINEからどうぞ」

---

## 16. CapCut手順書の要件

### 16.1 必須項目

* プロジェクト作成
* 素材読み込み
* 使う区間
* 不要区間
* 画角調整
* テロップ位置
* 強調演出
* AI音声の差し込み位置
* BGM方針
* 書き出し設定

### 16.2 指示の粒度

* 編集初心者でも実行できる
* 曖昧語を減らす
* 「いい感じに」は禁止
* 各工程は手順番号付きにする

---

## 17. レビュー判定ロジック

以下のいずれかに該当したら `needs_human_review=true` とする。

* `product_family_confidence < 0.75`
* `damage_confidence < 0.70`
* `angles_missing` に `inside` または `corners` が含まれる
* `uncertainty_flags` が1件以上ある
* `overall_visual_quality` が `poor`
* 禁止表現フラグが立った
* CTAが不自然
* 出力ファイルが欠損した

### 17.1 レビュー時の表示内容

`review.md` には以下を出す。

* 何が不確実か
* なぜ止めたか
* どこを人が見ればよいか
* 代替案はあるか

---

## 18. データモデル

### 18.1 Pydanticモデル一覧

* `InputJob`
* `VideoMetadata`
* `Observation`
* `TimestampEvidence`
* `HookCandidate`
* `StrategyPlan`
* `EditSegment`
* `EditPlan`
* `CaptionOutput`
* `ReviewFlag`
* `RunResult`

### 18.2 厳格バリデーション

* 秒数は整数
* `start_sec < end_sec`
* 総尺40秒
* テロップ空文字禁止
* CTA必須
* 禁止表現が1つでもあれば失敗扱い

---

## 19. ディレクトリ構成

```text
project/
  README.md
  spec.md
  .env.example
  requirements.txt
  pyproject.toml

  app/
    __init__.py
    config.py
    cli.py
    logging.py

    domain/
      models.py
      enums.py
      rules.py
      scoring.py

    services/
      video_metadata.py
      gemini_uploader.py
      gemini_analyzer.py
      observation_validator.py
      claude_strategy.py
      plan_renderer.py
      review_gate.py

    prompts/
      gemini_observation.md
      claude_strategy.md
      claude_caption.md
      claude_capcut.md

    schemas/
      observation.schema.json
      strategy.schema.json
      edit_plan.schema.json

    renderers/
      markdown_renderer.py
      json_renderer.py
      text_renderer.py

    storage/
      file_store.py
      run_repository.py

    utils/
      timecode.py
      text_safety.py
      retry.py

  tests/
    unit/
    integration/
    fixtures/
      videos/
      observations/
      outputs/

  runs/
    {run_id}/
      input/
      intermediate/
      output/
      logs/
```

---

## 20. 実装責務の分割

### 20.1 Python側

* CLI起動
* API呼び出し
* JSON保存
* バリデーション
* ログ
* リトライ
* 成果物レンダリング

### 20.2 Gemini側

* 観察のみ

### 20.3 Claude側

* 戦略と成果物生成

### 20.4 Claude Code側

Claude Codeで実装する際は、以下の順で進める。

1. Pydanticモデル定義
2. JSON Schema出力
3. Gemini接続
4. 観察出力の固定化
5. Claude接続
6. 戦略出力の固定化
7. レンダラー
8. CLI
9. テスト
10. 実動画でE2E確認

Claude Codeはローカルのファイル読込、コマンド実行、コード編集を伴うエージェント開発に向いているので、このプロジェクトでは「実装者」として使うのが自然です。 ([Claude API Docs][6])

---

## 21. CLI仕様

### 21.1 実行コマンド

```bash
python -m app.cli run \
  --video /path/to/video.mp4 \
  --project-id hermes_001 \
  --brand hermes \
  --platform instagram_reels
```

### 21.2 オプション

* `--notes`
* `--skip-upload`
* `--reuse-observations`
* `--force-review`
* `--output-dir`
* `--debug`

### 21.3 終了コード

* `0`: 成功
* `1`: 入力不正
* `2`: API失敗
* `3`: スキーマ不整合
* `4`: 人レビュー必要
* `5`: 未知の失敗

---

## 22. 環境変数

* `GEMINI_API_KEY`
* `CLAUDE_API_KEY`
* `APP_ENV`
* `LOG_LEVEL`
* `RUNS_DIR`
* `DEFAULT_PLATFORM`
* `ENABLE_CONTEXT_CACHE`
* `ENABLE_BATCH_REANALYSIS`

Files APIの保存は48時間なので、再利用前提の正式データは `runs/` や別ストレージに残す。コンテキストキャッシュも同一動画への複数問い合わせ時だけ有効化する。 ([Google AI for Developers][2])

---

## 23. ログ設計

### 23.1 ログ単位

* run単位
* step単位
* API単位

### 23.2 記録内容

* 入力動画名
* run_id
* Gemini実行時間
* Claude実行時間
* リトライ回数
* スキーマ検証結果
* レビュー判定理由
* 出力ファイル一覧

### 23.3 ログ禁止

* APIキー
* 個人情報
* 過剰な動画内容の転載

---

## 24. テスト要件

### 24.1 Unit Test

* スコアリング
* 禁止表現検知
* 時間整合性
* JSONバリデーション
* レンダラー出力

### 24.2 Integration Test

* Geminiモック応答から `observations.json` 生成
* Claudeモック応答から成果物生成
* レビュー条件分岐

### 24.3 E2E Test

* 実動画5本で通し確認
* 正常系3本
* 視認不良1本
* 付属品不明1本

### 24.4 評価指標

* JSONスキーマ適合率 95%以上
* 禁止表現混入率 0%
* 人間の追加修正時間 平均5分未満
* LINE誘導文の欠落率 0%
* 失敗時に原因がログで特定できること

---

## 25. 評価データセット要件

最低でも以下の動画セットを用意する。

* 金具がよく見える
* 角スレが見える
* 内装が見える
* 付属品が見える
* 画質が悪い
* 手ブレが強い
* 商品名推定が難しい
* 音声あり
* 音声なし

各動画に対して、正解ラベルを簡易で持つ。

* 商品カテゴリ
* 傷の有無
* 付属品の有無
* レビュー要否

---

## 26. ルールエンジン

### 26.1 事実ルール

* 見えていない要素は断定不可
* 確信度が低い要素は補助情報扱い
* 査定に影響する要素は証拠映像と紐づける

### 26.2 コピールール

* CTAは最後に必須
* テロップは短文
* 過剰煽り禁止
* 高級感のある口調維持

### 26.3 運用ルール

* レビュー落ち動画は公開前に必ず目視確認
* 生成物をそのまま投稿しない
* 人の承認なく真贋断定表現を出さない

---

## 27. MVP定義

### 27.1 MVPで必ず実装するもの

* 動画1本入力
* Gemini観察
* Pydantic検証
* Claude戦略生成
* 40秒編集計画
* キャプション生成
* CapCut手順書生成
* 人レビュー判定
* ログ保存

### 27.2 MVPで切るもの

* 競合リサーチ連携
* 実績DB参照
* A/Bフック自動比較
* 一括大量処理
* Web UI
* SNS予約投稿連携

---

## 28. 今後拡張する設計余地

### 28.1 競合リサーチ連携

将来、`market_signals.json` を追加で読み込める設計にする。
ただしMVPでは未実装。

### 28.2 実績学習

過去動画の指標を保存し、フックスコアにCTRやLINE遷移率を反映する。

### 28.3 マルチブランド化

将来 `brand_rules/` ディレクトリを切り、エルメス固有ルールを分離できる形にしておく。

---

## 29. 実装順序

### Phase 1

* Pydanticモデル
* JSON Schema
* Gemini観察
* 保存

### Phase 2

* Claude戦略生成
* フックスコア
* 40秒構成
* キャプション

### Phase 3

* CapCut手順書
* レビュー判定
* CLI整備
* ログ

### Phase 4

* テスト
* 実動画評価
* プロンプト調整

### Phase 5

* 再解析機能
* バッチ機能
* 指標学習

---

## 30. 受け入れ基準

この要件定義は、以下を満たした時点で完了とする。

1. Claude Codeが迷わずディレクトリを切れる
2. Python実装の責務境界が明確
3. GeminiとClaudeの責務が混ざっていない
4. JSONスキーマが先に決まっている
5. 人レビュー条件が明文化されている
6. 出力ファイルが定義済み
7. 禁止表現と業務リスクが明記されている
8. MVPと後回し機能が分かれている

---

## 31. 実装上の重要判断

このプロジェクトで最重要なのは、**「観察」と「戦略」を分けること**である。
Geminiに売れる台本まで1発で出させない。
Claudeにも動画そのものを“見たことにさせない”。
必ず `observations.json` を中間成果物として固定し、それを唯一の入力として戦略化する。


