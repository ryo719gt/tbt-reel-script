#!/usr/bin/env python3.11
"""
TBT 投稿成果ログ管理 CLI

目的: LINE問い合わせに効くディレクション特徴を後から分析できる営業知見DBの構築

使い方:
    # strategy.jsonから初期レコード登録
    python manage_results.py register --strategy output/xxx/strategy.json

    # 登録済み一覧確認（content_id確認用）
    python manage_results.py list

    # 投稿後の結果を更新
    python manage_results.py update --content-id abc123 \
        --posted-at 2026-04-07 \
        --instagram-url https://instagram.com/reel/xxxx \
        --views 12000 --saves 210 --profile-visits 54 \
        --line-clicks 7 --inquiries 2 --qualified-inquiries 1 \
        --notes "CTAが相場確認型で反応良かった"

    # CSVエクスポート
    python manage_results.py export --out results.csv

    # 簡易集計（hook_type / cta_type / addressed_anxiety / content_category別）
    python manage_results.py summarize --by hook_type
"""

import sqlite3
import json
import csv
import argparse
import pathlib
import uuid
import sys
from datetime import datetime

# DB は manage_results.py と同じディレクトリに作成
DB_PATH = pathlib.Path(__file__).parent / "results.db"

# 集計できるグループ軸
SUMMARIZE_AXES = ["hook_type", "cta_type", "addressed_anxiety", "content_category"]


# ── DB初期化 ──────────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS content_results (
    content_id          TEXT    PRIMARY KEY,
    created_at          TEXT    NOT NULL,
    source_dir          TEXT,                   -- output配下のディレクトリ名
    source_video_names  TEXT,                   -- 元動画ファイル名（カンマ区切り）
    selected_hook       TEXT,                   -- 採用フックテキスト
    hook_type           TEXT,                   -- information_gap / loss_aversion / unexpected
    cta_type            TEXT,                   -- CTAタイプ（strategy.jsonに追加予定）
    addressed_anxiety   TEXT,                   -- 訴求した不安軸（strategy.jsonに追加予定）
    content_category    TEXT,                   -- コンテンツカテゴリ（strategy.jsonに追加予定）
    posted_at           TEXT,                   -- 投稿日（YYYY-MM-DD）
    instagram_url       TEXT,                   -- 投稿URL
    views               INTEGER,                -- 再生数
    saves               INTEGER,                -- 保存数
    profile_visits      INTEGER,                -- プロフィール遷移数
    line_clicks         INTEGER,                -- LINEクリック数
    inquiries           INTEGER,                -- 問い合わせ件数
    qualified_inquiries INTEGER,                -- 有効問い合わせ件数（商談化）
    notes               TEXT                    -- 自由メモ
);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    conn.commit()
    return conn


# ── register ──────────────────────────────────────────────────────────────────

def cmd_register(args):
    """strategy.jsonから初期レコードを登録する"""
    strategy_path = pathlib.Path(args.strategy).resolve()
    if not strategy_path.exists():
        print(f"エラー: ファイルが見つかりません: {strategy_path}")
        sys.exit(1)

    strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
    source_dir = strategy_path.parent

    # run_log.json から run_id と source_video を取得
    content_id = None
    source_video_names = None
    run_log_path = source_dir / "run_log.json"
    if run_log_path.exists():
        run_log = json.loads(run_log_path.read_text(encoding="utf-8"))
        content_id = run_log.get("run_id")
        source_video_names = run_log.get("source_video")

    # run_id がなければ UUID生成
    if not content_id:
        content_id = str(uuid.uuid4())[:8]

    # v3.0: narrative_plan.json が優先、なければ strategy.json を使う
    narrative_path = source_dir / "narrative_plan.json"
    if narrative_path.exists():
        narrative = json.loads(narrative_path.read_text(encoding="utf-8"))
        selected_hook = narrative.get("selected_hook", "")
        addressed_anxiety = narrative.get("addressed_anxiety")
        content_category = narrative.get("content_category")
        # narrative_formula_type から hook_type を推定
        formula_to_hook = {
            "不安解消型": "loss_aversion",
            "教育型": "information_gap",
            "証拠提示型": "unexpected",
        }
        hook_type = formula_to_hook.get(narrative.get("narrative_formula_type", ""), None)
        cta_type = narrative.get("cta_type")
    else:
        # v2.x: strategy.json から取得
        selected_hook = strategy.get("selected_hook", "")
        hook_type = None
        for candidate in strategy.get("hook_candidates", []):
            if candidate.get("text", "").strip() == selected_hook.strip():
                hook_type = candidate.get("hook_type")
                break
        cta_type = strategy.get("cta_type")
        addressed_anxiety = strategy.get("addressed_anxiety")
        content_category = strategy.get("content_category")

    conn = get_conn()
    try:
        conn.execute("""
            INSERT INTO content_results (
                content_id, created_at, source_dir, source_video_names,
                selected_hook, hook_type, cta_type, addressed_anxiety, content_category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            content_id,
            datetime.now().isoformat(timespec="seconds"),
            str(source_dir),
            source_video_names,
            selected_hook,
            hook_type,
            cta_type,
            addressed_anxiety,
            content_category,
        ))
        conn.commit()
        print("✅ 登録完了")
        print(f"   content_id   : {content_id}")
        print(f"   selected_hook: {selected_hook[:50]}")
        print(f"   hook_type    : {hook_type or '(未設定)'}")
        print(f"   source_dir   : {source_dir.name}")
        print(f"\n次のステップ:")
        print(f"  投稿後に以下で成果を記録してください:")
        print(f"  python manage_results.py update --content-id {content_id} --posted-at YYYY-MM-DD ...")
    except sqlite3.IntegrityError:
        print(f"⚠️  既に登録済みです (content_id: {content_id})")
        print(f"   更新する場合: python manage_results.py update --content-id {content_id} ...")
    finally:
        conn.close()


# ── update ────────────────────────────────────────────────────────────────────

def cmd_update(args):
    """投稿後の成果数値を更新する"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM content_results WHERE content_id = ?", (args.content_id,)
        ).fetchone()
        if not row:
            print(f"エラー: content_id '{args.content_id}' が見つかりません")
            print("  登録済み一覧: python manage_results.py list")
            sys.exit(1)

        # 指定されたフィールドだけ更新
        updates = {}
        if args.posted_at:                       updates["posted_at"] = args.posted_at
        if args.instagram_url:                   updates["instagram_url"] = args.instagram_url
        if args.views is not None:               updates["views"] = args.views
        if args.saves is not None:               updates["saves"] = args.saves
        if args.profile_visits is not None:      updates["profile_visits"] = args.profile_visits
        if args.line_clicks is not None:         updates["line_clicks"] = args.line_clicks
        if args.inquiries is not None:           updates["inquiries"] = args.inquiries
        if args.qualified_inquiries is not None: updates["qualified_inquiries"] = args.qualified_inquiries
        if args.notes is not None:               updates["notes"] = args.notes
        # 集計軸の後付け更新（strategy.jsonに未追加の項目を手動で補える）
        if args.hook_type is not None:           updates["hook_type"] = args.hook_type
        if args.cta_type is not None:            updates["cta_type"] = args.cta_type
        if args.addressed_anxiety is not None:   updates["addressed_anxiety"] = args.addressed_anxiety
        if args.content_category is not None:    updates["content_category"] = args.content_category

        if not updates:
            print("更新項目がありません。--views, --saves などを指定してください")
            sys.exit(1)

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [args.content_id]
        conn.execute(
            f"UPDATE content_results SET {set_clause} WHERE content_id = ?", values
        )
        conn.commit()
        print(f"✅ 更新完了 (content_id: {args.content_id})")
        for k, v in updates.items():
            print(f"   {k}: {v}")
    finally:
        conn.close()


# ── list ──────────────────────────────────────────────────────────────────────

def cmd_list(args):
    """登録済みレコードの一覧を表示する（update時のcontent_id確認用）"""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT content_id, created_at, hook_type, posted_at,
                   views, saves, line_clicks, inquiries, selected_hook
            FROM content_results
            ORDER BY created_at DESC
        """).fetchall()

        if not rows:
            print("登録済みレコードはありません")
            print("  登録: python manage_results.py register --strategy output/xxx/strategy.json")
            return

        print(f"\n{'ID':<10} {'登録日時':<20} {'hook_type':<18} {'投稿日':<12} "
              f"{'再生':>6} {'保存':>4} {'LINE':>4} {'問合':>4}  フック")
        print("-" * 110)
        for r in rows:
            hook = (r["selected_hook"] or "")[:35]
            print(
                f"{r['content_id']:<10} "
                f"{r['created_at']:<20} "
                f"{r['hook_type'] or '-':<18} "
                f"{r['posted_at'] or '未投稿':<12} "
                f"{r['views'] or '-':>6} "
                f"{r['saves'] or '-':>4} "
                f"{r['line_clicks'] or '-':>4} "
                f"{r['inquiries'] or '-':>4}  "
                f"{hook}"
            )
        print(f"\n合計 {len(rows)} 件")
    finally:
        conn.close()


# ── export ────────────────────────────────────────────────────────────────────

def cmd_export(args):
    """全レコードをCSVで書き出す"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM content_results ORDER BY created_at DESC"
        ).fetchall()

        if not rows:
            print("エクスポートするデータがありません")
            return

        out_path = pathlib.Path(args.out)
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(rows[0].keys())
            for row in rows:
                writer.writerow(list(row))

        print(f"✅ エクスポート完了: {out_path} ({len(rows)} 件)")
    finally:
        conn.close()


# ── summarize ─────────────────────────────────────────────────────────────────

def cmd_summarize(args):
    """指定した軸で集計を表示する"""
    group_col = args.by

    conn = get_conn()
    try:
        rows = conn.execute(f"""
            SELECT
                COALESCE({group_col}, '(未設定)') AS group_key,
                COUNT(*)                                        AS count,
                ROUND(AVG(views), 0)                           AS avg_views,
                ROUND(AVG(saves), 0)                           AS avg_saves,
                ROUND(AVG(profile_visits), 0)                  AS avg_profile_visits,
                SUM(COALESCE(line_clicks, 0))                  AS total_line_clicks,
                SUM(COALESCE(inquiries, 0))                    AS total_inquiries,
                SUM(COALESCE(qualified_inquiries, 0))          AS total_qualified
            FROM content_results
            GROUP BY group_key
            ORDER BY total_inquiries DESC, total_line_clicks DESC
        """).fetchall()

        if not rows:
            print("集計するデータがありません")
            return

        print(f"\n📊  {group_col} 別集計\n")
        header = (
            f"{'グループ':<28} {'件数':>4}  "
            f"{'avg再生':>8} {'avg保存':>8} {'avgPV':>8}  "
            f"{'LINE計':>6} {'問合計':>6} {'有効問合計':>8}"
        )
        print(header)
        print("─" * len(header))
        for r in rows:
            print(
                f"{r['group_key']:<28} {r['count']:>4}  "
                f"{str(r['avg_views'] or '-'):>8} "
                f"{str(r['avg_saves'] or '-'):>8} "
                f"{str(r['avg_profile_visits'] or '-'):>8}  "
                f"{r['total_line_clicks']:>6} "
                f"{r['total_inquiries']:>6} "
                f"{r['total_qualified']:>8}"
            )

        # 全体サマリ
        total = conn.execute("""
            SELECT
                COUNT(*) AS total_count,
                SUM(COALESCE(inquiries, 0)) AS total_inq,
                SUM(COALESCE(qualified_inquiries, 0)) AS total_qual,
                SUM(COALESCE(line_clicks, 0)) AS total_line
            FROM content_results
        """).fetchone()
        print(f"\n  全体: {total['total_count']} 件 ／ "
              f"LINE計: {total['total_line']} ／ "
              f"問合せ計: {total['total_inq']} ／ "
              f"有効問合せ計: {total['total_qual']}")
        print()
    finally:
        conn.close()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="TBT 投稿成果ログ管理 ― LINE問い合わせに効くディレクションの知見を蓄積する",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  python manage_results.py register --strategy output/20260407_IMG_9132_xxx/strategy.json
  python manage_results.py list
  python manage_results.py update --content-id abc12345 --views 9800 --inquiries 2
  python manage_results.py summarize --by hook_type
  python manage_results.py export --out results.csv
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # register
    p = sub.add_parser("register", help="strategy.jsonから初期レコードを登録")
    p.add_argument("--strategy", required=True, metavar="PATH",
                   help="strategy.jsonのパス")

    # update
    p = sub.add_parser("update", help="投稿後の成果数値を更新")
    p.add_argument("--content-id", required=True, metavar="ID")
    p.add_argument("--posted-at",          metavar="YYYY-MM-DD")
    p.add_argument("--instagram-url",      metavar="URL")
    p.add_argument("--views",              type=int)
    p.add_argument("--saves",              type=int)
    p.add_argument("--profile-visits",     type=int)
    p.add_argument("--line-clicks",        type=int)
    p.add_argument("--inquiries",          type=int)
    p.add_argument("--qualified-inquiries",type=int)
    p.add_argument("--notes",              metavar="TEXT")
    # 集計軸を後付けで補える（strategy.jsonに未追加の項目用）
    p.add_argument("--hook-type",          metavar="TYPE",
                   choices=["information_gap","loss_aversion","unexpected"],
                   help="hook_typeを手動で補完する場合")
    p.add_argument("--cta-type",           metavar="TYPE")
    p.add_argument("--addressed-anxiety",  metavar="TEXT")
    p.add_argument("--content-category",   metavar="TEXT")

    # list
    sub.add_parser("list", help="登録済みレコードの一覧表示")

    # export
    p = sub.add_parser("export", help="全レコードをCSVで書き出す")
    p.add_argument("--out", default="results.csv", metavar="PATH",
                   help="出力CSVパス (デフォルト: results.csv)")

    # summarize
    p = sub.add_parser("summarize", help="軸別に簡易集計を表示")
    p.add_argument("--by", choices=SUMMARIZE_AXES, default="hook_type",
                   help=f"集計軸 (デフォルト: hook_type)")

    args = parser.parse_args()
    {
        "register":  cmd_register,
        "update":    cmd_update,
        "list":      cmd_list,
        "export":    cmd_export,
        "summarize": cmd_summarize,
    }[args.command](args)


if __name__ == "__main__":
    main()
