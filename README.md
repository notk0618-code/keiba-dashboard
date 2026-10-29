# keiba_db 週次自動更新（クラウド実行用）

このブランチはスクリプト置き場です。公開ページ（main ブランチ）には影響しません。
Claude のクラウド環境 `keiba`（環境変数 `GOOGLE_SERVICE_ACCOUNT_JSON`）で動かします。鍵はここに置きません。

```bash
bash weekly.sh check   # 新しい成績フルセットが未取り込みか確認（読み取りのみ）
bash weekly.sh trial   # 一通り実行するが、Drive書き戻し・公開はしない
bash weekly.sh prod    # 実行 → Driveへ書き戻し → 公開ページをpush
```

流れ: Driveの keiba_db を `/content/drive/MyDrive/keiba_db` に複製 → restore_v7.py を Colab の代わりに読み込み
→ 0-2 ガバナンスチェック → 0-3 取り込み（会場別に分かれたファイルも取り込む）＋ rebuild_all_derived_data()
→ 0-4 週次振り返り → 変更ファイルをDriveへ書き戻し（途中でDrive側が更新されていたら中止）→ 公開。
