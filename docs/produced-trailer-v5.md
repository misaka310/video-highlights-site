# ドチタオ トレーラー v5 のサイト登録

- 本採用した動画は 177_dotitao-video-production/projects/trailer-2026-10/out/dotitao_trailer_v5.mp4。
- HLS配信パッケージは C:\00_data\media\dotitao-trailer-v5-hls（1080p/720p/480p、各4秒、master.m3u8）。
- data/produced_videos.json に登録済み。
- 現時点の video_url は開発サーバー専用 /media/master.m3u8。PUBLIC_MEDIA_DIR を上のHLSパッケージに設定して確認する。
- 本番公開にはCloudflare PagesなどへHLSをアップロードし、実際に再生確認した公開master.m3u8の絶対URLへ video_url を更新する。
- 仕様により絶対URLでない動画は本番サイトの公開ビルドから除外される。公開済みとは判定しない。
- デプロイ前に既存の他の紹介動画の公開先を変更・上書きしない。独立したメディアホストへ配信する。
- 正式採用版はv5。v6/v7への差し替え禁止。
