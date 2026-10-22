# ドチタオ トレーラー v5 のサイト登録と公開

- **正式採用：v5**。正本は `177_dotitao-video-production/projects/trailer-2026-10/out/dotitao_trailer_v5.mp4`。
- 元動画は `C:\00_dev-data\streams\derived\dotitao-trailer-2026-10\v3\out\dotitao_trailer_v5.mp4`。
- SHA-256：`d904886c7986e8e50af3da3a4fa9e0dc9ed462bad4eda99a5e4ffad2920d2225`。
- 長さ：49.083秒。1920×1080、H.264映像 / AAC音声。
- 配信HLS：`C:\00_data\media\dotitao-trailer-v5-hls`。1080p / 720p / 480p、4秒セグメント（13本×3画質）。
- Cloudflare Pagesの独立プロジェクト：`dotitao-trailer-v5`。既存の `dotitao-media` と `dotitao-quotes` は変更しない。
- **正式公開URL：** https://dotitao-trailer-v5.pages.dev/master.m3u8
- `data/produced_videos.json` の `dotitao-trailer-2026` エントリで上記URLを使用する。
- ポスター：`data/produced-video-posters/dotitao-trailer-v5.jpg`。
- 本番配信検証：master + 1080p/720p/480p各index + 39個の.tsをHTTP 200で取得。全43 URLで `Access-Control-Allow-Origin: *` を確認。
- 検証時点：2026-10-23（JST）。Cloudflareへの初回デプロイは44ファイル成功、完了URL `https://5d0e1442.dotitao-trailer-v5.pages.dev`。
- メディア本体をサイトのGitリポジトリにコピーしない（サイト仕様の外部HLS配信）。
- **v6/v7へ無断で切り替えない。**
