# SOLA DOWNLOAD

SOLAシリーズのダウンロード・変換サイト。Scratchの公開作品ダウンロード機能はSOLA SCRATCHの高速版を引き継いでいます。

## タブ

- **Scratch**: 公開作品の情報を確認し、画像・音声素材を最大8並列で取得して.sb3を作成
- **YouTube**: 動画URLの検証、公式ページとYouTube Studioへの導線（動画抽出はしない）
- **ニコニコ**: 動画URLの検証と公式ページへの導線（動画抽出はしない）
- **画像保存**: 直接画像URLからのブラウザダウンロード（配信元がCORSを許可する場合）。CORS非対応は直接画像を開いて保存
- **ファイル変換**: ローカル画像のPNG/JPG/WebP変換（サーバーへのアップロードなし）

## Render

Language: Python

Build Command: `pip install -r requirements.txt`

Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120`

Health Check Path: `/health`

## ローカル

```sh
pip install -r requirements.txt
python app.py
```

## 注意

Scratch側の制限で取得できない作品があります。画像URLの取得はサイト側のCORS制限に左右されます。YouTubeとニコニコの動画ファイルを本サイトから直接ダウンロードする機能はまだありません。
