# keiba_db 週次自動更新（クラウド実行用）

このフォルダは自動更新のスクリプト置き場です。名前が「.」で始まるので、GitHub Pages の公開ページには出ません。
Claude のクラウド環境 `keiba`（環境変数 `GOOGLE_SERVICE_ACCOUNT_JSON`）で動かします。鍵はここに置きません。

毎時の自動実行は `auto.sh` です（成績フルセット→週次、当日出走馬→1. 日々の予想、特別登録→7-2 暫定予想）。
当日出走馬の予想とオッズ更新のたびに、確認用の買い目リスト `bets.html`（日付別 `bets_YYMMDD.html` / `.csv`）も作ります（`bet_list.py`）。JRAの単勝・複勝オッズで期待値1.1以上の馬（🎯）と、指数2位以内なのに6番人気以下の馬（🐎）を候補にし、発走後はその時点の候補を記録として残します。投票はしません。
レースカードには参考表示の「🏇 ペース予想」（`pace_forecast.py`、2026-11-04のペースモデル比較のモデルB）が入ります。出走馬の過去5走の位置取り・コース・クラス・頭数・馬場などから、スロー・平均・ハイの確率と逃げ・先行の馬を出します。
確率が0.40以上の区分を「スロー寄り／ハイ寄り」とし、それ以外は「平均」です（一番高い区分を選ぶと約半数がハイになるため）。印・指数・買い目は従来のペース（v2）のままで、この表示は使っていません。
restore_v7 は書き換えず、`keiba_env.py` がレースカード関数を包んで差し込みます。止めるときは `PACE_FORECAST=0`。登録がフルゲートを超える特別登録では、出走馬が決まるまで表示しません。
`python3 .automation/pace_forecast.py --db keiba.duckdb --test 2025-01-01` で、指定日より前で学習し、それ以降のレースを予想して精度を確かめられます。
予想は新しいファイルを作るため、本人アカウントのOAuthトークン `GOOGLE_OAUTH_JSON` があるときだけ動きます。

### 成績はJRA公式サイトからも作れます（TARGET不要）
`auto.sh` は計画の前に `jra_weekly.py` を実行します。直近の開催週末（JRAの「レース結果」に載った日で、今日より前）について、
Driveに `成績フルセットYYYYMMDD*.csv` がまだ無ければ、`jra_results.py` がJRAの結果ページ（＋最終オッズ、新しい馬は競走馬ページ）から
TARGETと同じ形の `成績フルセットYYYYMMDD_JRA.csv`（80列）・`馬別フルセットYYYYMMDD_JRA.csv`（56列）と、全券種の払戻 `払戻YYYYMMDD_JRA.csv`
（ワイド・馬連・3連複なども）を作ってDriveに置きます。あとはTARGETのファイルと同じく週次処理（0-2〜0-4）に流れます。
騎手・調教師・馬主などの表記は、DBの過去行（対象日より前）からTARGETの書き方に合わせます。1週末で約8分（1秒1回以下のアクセス）。
特別登録も同様に、JRAの「特別レース登録馬」に次の週末の登録が出て、Driveに `特別登録YYYYMMDD*.csv` も `当日出走馬YYYYMMDD*.csv` も無ければ、
TARGETと同じ33列の `特別登録YYYYMMDD_JRA.csv` を作って置きます（騎手・枠・オッズは未確定のため空欄、ハンデ戦の斤量は発表前なら空欄）。
この作成は `plan_jobs.py` の最初にも行うので、定期実行の判定でそのまま拾われます（`JRA_BUILD=0` で省略）。
TARGETの成績フルセットも同じ週末に置かれていれば、両方を列ごとに比べた `JRA照合YYYYMMDD.txt` をDriveに置きます（並行期間の確認用）。

```bash
python3 .automation/jra_results.py 20261024 20261025 --out /tmp/out --db keiba.duckdb   # 手動で作る
python3 .automation/jra_weekly.py --dry-run                                              # Driveに置かずに試す
```
TARGETとの既知の差（10/24・25の72レース・935頭で確認）: 新潟直線1000mの4角通過順はJRAに無いので0、地方騎手の初騎乗などリンクの無い騎手・調教師のコードは空欄、
DBに無い馬の馬主は競走馬ページの現在の馬主、PCIが小数第2位でちょうど5になるときの丸め（約0.1%）。補正タイム・基準タイム・マイニング・馬印は空欄（モデル未使用）。

```bash
bash .automation/auto.sh           # アップを判定して必要な処理を実行 → Drive書き戻し → 公開
bash .automation/auto.sh trial     # 判定と実行のみ（書き戻し・公開なし）
bash .automation/weekly.sh check   # 新しい成績フルセットが未取り込みか確認（読み取りのみ）
bash .automation/weekly.sh trial   # 一通り実行するが、Drive書き戻し・公開はしない
bash .automation/weekly.sh prod    # 実行 → Driveへ書き戻し → 公開ページをpush
```

流れ: Driveの keiba_db を `/content/drive/MyDrive/keiba_db` に複製 → restore_v7.py を Colab の代わりに読み込み
→ 0-2 ガバナンスチェック → 0-3 取り込み（会場別に分かれたファイルも取り込む）＋ rebuild_all_derived_data()
→ 0-4 週次振り返り → 変更ファイルをDriveへ書き戻し（途中でDrive側が更新されていたら中止）→ 公開。
