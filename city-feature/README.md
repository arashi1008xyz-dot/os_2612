# 街づくり機能 record_city

記録の量を受け取り、固定視点のビル街を描く独立したPythonパッケージです。
既存アプリ、記録データ、既存の4項目ナビゲーションには変更を加えていません。
旧デモのJavaScriptやCodexの可視化環境にも依存しません。

## 仕様

- 本1ページ＝漫画5ページ＝アニメ・映画・ドラマ2分。
- 本1ページは2分、漫画1ページは0.4分、映像1分は1分として換算。
- 600分（10時間）で1棟。余りは次の建物へ引き継ぐ。
- 0分は更地、0分超は基礎工事中、150分で基礎完成、300分で骨組み完成、450分で外装完成、600分で建物完成。
- 街の表示上限は120棟＝72,000分＝1,200時間。
- 上限到達後は街の形・高さ・密度・建築中表示を変えない。実際の累計と理論上の完成棟数は保持する。
- 記録量を修正・削減して渡し直すと、その量に応じた街を再計算する。
- 建物の高さや形は記録の評価を表さない。形・高さ・色・位置は120棟分の固定プランで決まる。
- 120棟すべてに形と配置があり、終盤の24棟も街区として設計済み。
- 同じ入力と設定は、常に同じ街になる。ランダム生成、時刻依存、永続的な建築履歴は使わない。

## ファイル構成

```text
record_city/
  core.py              記録量の受取・換算・上限・建築段階
  config.py            JSON設定の読込と検証
  render.py            SVG/HTMLの描画
  streamlit_view.py    既存Streamlit画面から呼ぶ薄い表示部品
  __main__.py          JSONを受け取るコマンド
  data/
    rules.json         換算レートと上限
    city_layout.json   固定した120棟・20街区の形と配置
examples/
  amounts.json         正規化された入力の例
  streamlit_app.py     単体で表示を確認する入口
tests/test_city.py     標準ライブラリのunittest
```

## 必要環境

Python 3.10以上。計算、JSON読込、SVG/HTML出力には外部ライブラリは不要です。
Streamlitで使う場合のみ、既存アプリのStreamlit環境を利用してください。

このフォルダーで以下を実行します。

```powershell
python -m pip install .
```

Streamlitも新しく用意する場合は `python -m pip install ".[streamlit]"` です。
すでに依存関係を管理するアプリへ取り込む場合は、このパッケージだけを導入し、
既存の依存ファイルは変更せずに調整できます。

## Pythonから接続する

```python
from record_city import RecordAmounts, calculate_city, load_config, render_svg

# 設定は呼出元で一度読み込み、繰り返し再利用できます。
config = load_config()
amounts = RecordAmounts(
    book_pages=100,
    manga_pages=500,
    anime_minutes=0,
    movie_minutes=120,
    drama_minutes=0,
)
state = calculate_city(amounts, config)
svg = render_svg(state, config)
# state.total_minutes == 520
# state.completed_visible == 0
# state.remaining_minutes == 80
```

`calculate_city()` は同じキーを持つ辞書も受け取ります。省略した項目は0です。
入力は全期間分の集計値を渡してください。前回値との差分を加算するAPIではありません。
再描画時に同じ集計値を渡しても二重加算されません。

| 入力キー | 単位 |
|---|---|
| `book_pages` | 本の読んだページ数 |
| `manga_pages` | 漫画の読んだページ数 |
| `anime_minutes` | アニメの視聴分数 |
| `movie_minutes` | 映画の視聴分数 |
| `drama_minutes` | ドラマの視聴分数 |

既存データからこれらの値を作る集計・接続処理は今回の対象外です。
話数から分数を推測したり、感想の文字数・総ページ数・作品数を加算したりしません。
単位や名前の違いは接続側で変換してください。映画のキーは既存アプリに合わせ `movie_minutes` です。
未知のキー、負数、null、文字列、真偽値、NaN、Infinityはエラーになります。
未入力の量を0とするかは接続側で判断してください。

分数は小数にも対応します。Pythonでは `Decimal` を渡すこともできます。
換算と境界判定はDecimalで行い、漫画0.4分の誤差で完成判定がずれないようにしています。

## Streamlitの「街」画面として使う

```python
from record_city.streamlit_view import render_city, CITY_NAV_ITEM

# 既存のルーティングで page == "city" となった場所から呼びます。
state = render_city(amounts, config=config, theme="light")

# 既存の4項目へ追加するための識別子。追加作業自体は接続時に行います。
# CITY_NAV_ITEM == ("city", "街")
```

`render_city()` は街の内容だけを描画します。`set_page_config`、下部ナビゲーション、
セッション状態、記録ファイルの操作は行いません。既存の `st.bottom` に重複したナビゲーションを置きません。
5項目化する際の幅・アイコン・画面遷移は、既存アプリ側でまとめて調整してください。

`theme` は `light` / `dark` / `auto`。`auto` はブラウザーの配色設定に従います。
アプリ独自の配色切替がある場合は、その設定から `light` または `dark` を渡します。
`show_summary=False` で累計や建築進捗の表示を省けます。

表示には[Streamlitのst.html](https://docs.streamlit.io/develop/api-reference/text/st.html)を使い、
街並みのSVGをデータURIの画像として埋め込みます。HTMLの無害化処理でインラインSVGが
取り除かれることを避けるためです。外部画像通信やJavaScriptは使いません。
CSSは街の表示範囲に限定しています。

単体確認用の入口は次のとおりです。これは本体機能に依存する確認画面で、既存アプリを置き換えるものではありません。

```powershell
python -m streamlit run examples/streamlit_app.py
```

## JSONから街を出力する

インストールせずに、このフォルダーで実行できます。

```powershell
python -m record_city --input examples/amounts.json --html city.html --svg city.svg --state city-state.json
```

ブラウザーで `city.html` を開くと、Pythonが生成した街を確認できます。
出力先の親フォルダーは先に用意してください。同名の出力ファイルは上書きします。
入力ファイルそのものや、複数の出力に同じパスを指定するとエラーになります。

`CityState.to_dict()` / `--state` の換算分数・進捗は精度を保つためJSON文字列、
棟数は整数、上限フラグは真偽値です。この状態ファイルは任意の計算結果の書き出しで、
次回計算の入力や記録データの正本ではありません。

主な戻り値：

| フィールド | 意味 |
|---|---|
| `total_minutes` | 上限で切り捨てない累計換算分数 |
| `displayed_minutes` | 最大72,000分の表示用換算分数 |
| `completed_total` | 実際の累計から求めた完成棟数。120を超え得る |
| `completed_visible` | 描く完成棟数。最大120 |
| `current_building` | 建築対象の番号。上限到達時はNone |
| `stage` | empty / groundwork / foundation / frame / shell / complete |
| `progress` | 次の1棟の進捗（0〜1）。上限到達時は1 |
| `remaining_minutes` | 次の1棟までの分数。上限到達時は0 |
| `capped` | 表示上限に達したか |

## JSONの管理方針

`rules.json` と `city_layout.json` はソースとして管理する読み取り専用の設定です。
実行によって元の記録・設定を書き換えません。記録の複製保存やデータベースは作りません。
設定を変更しても計算元のページ数・分数は接続元に残ります。

`city_layout.json` の `buildings` は成長順です。各棟の `volumes` は敷地内の直方体の組合せで、
台座・段状の上層部・L字の棟などを定義します。建築対象の追加によって既存の棟は変わりません。
形や配置の互換性を変える場合は `plan_version` も更新してください。

## 検証

```powershell
python -m unittest discover -s tests -v
```

換算、建築段階の境界、120棟の上限、累計の保持、再計算、入力検証、配置の安定性、
120棟の敷地の重なり、描画の範囲、CLI出力、表示部品の呼出しを検証します。
Streamlit自体の画面遷移と5項目ナビゲーションの検証は、別途接続した段階で行います。
