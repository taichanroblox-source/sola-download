# SOLA DOWNLOAD

SOLAシリーズのダウンロード・変換サイト。

## 機能

- **Scratch**: 公開作品を高速で取得して .sb3 形式でダウンロード
- **ファイル変換**: PNG / JPG / WebP の画像形式変換（端末内で処理し、サーバーへアップロードしません）

YouTube・ニコニコ・画像保存の各タブは削除済みです。

## Render

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120`
- Health Check Path: `/health`
