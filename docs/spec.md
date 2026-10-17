# コンテンツ記録アプリ — 実装仕様 v0.5

最終更新：2026-10-17

## 変更履歴

| バージョン | 日付 | 内容 |
|---|---|---|
| v0.5 | 2026-10-17 | 採用デザインに合わせてホームと集計を分離。記録・羽ペンの下部固定ナビ、評価欄削除、日付別感想表示、カテゴリ別集計、本の総ページ数基準の進捗と右揃え表示を追加。途中記録を扱うため日付・状態を拡張。 |

元のv0.4全文は`spec-v0.4.md`に保存する。相違する点は本仕様を優先する。

## 方針と技術

記録を中心に据え、振り返りや他人へのおすすめといった利用方法は利用者に委ねる。Python 3.11以降、Streamlit 1.66.0、JSON、pandas、Pillow。HTML・CSS・JavaScriptは書かない。

## 画面

- ホーム：`yyyy/mm/ddの記録`ごとに表紙・タイトル・カテゴリ・数量・感想を表示。新規記録の入口は下部ナビに集約。
- 記録：評価なし。6カテゴリ別の入力、数量、作品情報、表紙、任意タグ・感想、保存、キャンセル。
- 集計：期間と数／量を選び、カテゴリ別の数量を表示。「読書量」「視聴時間」の混合集計領域にはしない。
- カテゴリ詳細：個別記録。カテゴリごとの月別グラフは折りたたみ内。
- 検索：カテゴリ・タグ・期間・キーワードで絞り込み。
- 記録詳細：編集、削除、別記録としてコピー。
- タグ管理：ジャンル・感情別の追加、変更、削除、統合。

下部固定ナビはホーム／記録／集計／検索。「記録」は羽ペン。入力・編集では下部ナビを非表示にして保存操作を優先。Streamlitの標準`st.bottom`で構成する。

## 記録と進捗

従来の記録に次を追加する。

```json
{
  "recorded_on": "2026-10-08",
  "status": "in_progress",
  "finished_on": null,
  "metrics": {"pages": 300, "total_pages": 500}
}
```

- `pages`はその記録内の累計読書ページ数。`total_pages`は総ページ数。
- バーの幅は全記録で同一。塗る割合は`pages / total_pages`。パーセント文字列を表示しない。
- 数量表示は`300／500ページ`。バーの下に同じ右端で右揃えする。
- 総ページ数がない旧記録にバーや100%を補わない。
- 総ページ数を指定すると、未到達は途中、到達は読了となる。
- 途中は同じIDを編集し、再読・再視聴は別ID。作品名による自動統合なし。
- 記録日で集計する。旧データは`finished_on`を記録日として読み替える。
- 本の数モードは読了冊数。量モードは途中も含む累計ページ数。日々の読書差分を保持する履歴方式ではない。
- 数量は整数、ページ数0以上、総ページ数1以上、読んだページ数は総ページ数以下。漫画はページ数か巻数の少なくとも一方が必要。映像の話数・分数・巻数は1以上。
- 新規記録では`rating`を使わない。旧データにある値の破壊的移行は行わない。

## バックエンドとの契約

`storage.py`はJSON・画像のI/O、正規化、検証を担当。`stats.py`は集計と表示用データの計算を担当し、UIから呼ぶ。

- `load_records()`, `get_record(id)`, `load_tags(category=None, kind=None)`。
- `add_record(data, uploaded_file=None, tag_names=None) -> id`。
- `update_record(id, data, uploaded_file=None, tag_names=None, expected_updated_at=None) -> id`。競合時はValueError。
- `tag_names`は`{"genre": ["SF"], "emotion": ["泣ける"]}`。既存IDへ解決して保存する。
- 画像は記録保存に付随して保存。新規コピーではファイルも独立させる。
- `delete_record`, `copy_record_data`, `image_path`, `list_field_values`。
- `add_tag`, `update_tag`, `delete_tag`, `merge_tags`。統合は同じ種類のタグ間だけ。
- `load_settings`, `save_settings`。保存する切り替え値は`amount`／`count`。
- `category_summary(records, period, mode)`はDataFrame。列は`category,label,records,value,unit,missing,episodes,in_progress`。
- `record_view(record)`は`{"text": str, "progress": float | None}`。フロントは再計算しない。
- `monthly_category(records, category, period, mode)`は月インデックス、単位名の数値列を持つDataFrame。空の月も0で補う。
- `filter_period`, `grouped_records`, `search_records`, `count_by_category`, `count_by_tag`, `this_month_summary`。
- `period`は`this_year`／`last_12_months`／`all`。過去12か月は今月を含む12暦月。日本時間を使用。

## 初期実装と未確認事項

サンプルは手動投入のみ。保存先はローカルJSON。画像は内容検査後JPEGへ変換し、コピー時も独立して保持する。タグ参照更新は実装済みだが複数JSON全体のクラッシュ耐性を保証するトランザクションではない。

Streamlitの導入が作成環境のネットワーク制限でできず、実ブラウザでの表示は未確認。依存ライブラリを導入した環境でPC・スマートフォンの表示検証を行う必要がある。ISBN取得の実通信とCould機能は検証対象外。
