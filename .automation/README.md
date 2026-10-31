# keiba_db 週次自動更新（クラウド実行用）

このフォルダは自動更新のスクリプト置き場です。名前が「.」で始まるので、GitHub Pages の公開ページには出ません。
Claude のクラウド環境 `keiba`（環境変数 `GOOGLE_SERVICE_ACCOUNT_JSON`）で動かします。鍵はここに置きません。

毎時の自動実行は `auto.sh` です（成績フルセット→週次、当日出走馬→1. 日々の予想、特別登録→7-2 暫定予想）。
当日出走馬の予想とオッズ更新のたびに、確認用の買い目リスト `bets.html`（日付別 `bets_YYMMDD.html` / `.csv`）も作ります（`bet_list.py`）。JRAの単勝・複勝オッズで期待値1.1以上の馬だけを候補にし、発走後はその時点の候補を記録として残します。投票はしません。
予想は新しいファイルを作るため、本人アカウントのOAuthトークン `GOOGLE_OAUTH_JSON` があるときだけ動きます。

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
