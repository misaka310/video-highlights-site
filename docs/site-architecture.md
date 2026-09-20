# Site Architecture

## 正本

- `frontend/`
  - React + TypeScript + Vite + Cloudflare Kumoによる公開UIの正本。
- `public/`
  - `scripts/build_public.sh` が生成する配信用出力。
- `data/`
  - 公開可能な集計JSON、個別VOD JSON、サムネイル、内部再利用キャッシュ。
- `config/site.json`
  - サイト名、説明、公開URL、Twitchチャンネル、アクセス解析設定。
- `config/tag-rules.json`
  - 現在のTwitchチャンネルにだけ追加するコメント解析用タグ規則。

製品仕様の正本は `docs/PUBLIC_SITE_SPEC.md`、再生状態遷移は `docs/PLAYBACK_SPEC.md`、データ形式は `docs/data-contract.md` とする。

## frontendの責務

- `src/App.tsx`
  - ページ、選択状態、プレイヤー公開API、主要表示領域を接続するcomposition root。
- `src/components/`
  - DOM契約と表示構造を保持する表示コンポーネント。
- `src/domain/`
  - 公開JSONに対応する型とページ単位のデータ型。
- `src/hooks/`
  - データ取得、metadata更新、media queryなどReactライフサイクルを伴う処理。
- `src/lib/`
  - React、`window`、`document`へ依存しない正規化、表示形式、盛り上がりマップ計算。
- `src/player/playback-types.ts`、`playback-request.ts`、`playback-decision.ts`、`twitch-url.ts`
  - React、DOM、`window`へ依存しない再生要求、状態判断、Twitch URL生成。
- `src/player/twitch-sdk-loader.ts`、`twitch-player-adapter.ts`、`iframe-fallback.ts`
  - Twitch SDK、player操作、iframe fallbackの副作用境界。
- `src/hooks/use-player-portal.ts`、`use-position-polling.ts`、`use-interactive-player.ts`
  - portal同期、位置polling、SDKイベントと再生ライフサイクル。
- `src/twitch-player.tsx`
  - 公開component、imperative handle、DOM契約だけを担うfacade。

## Python文字起こしパイプラインの責務

- `scripts/transcription/config.py`
  - 任意のmappingから環境設定を解釈する`PipelineSettings`の正本。module import時には`.env`やprocess environmentを読み込まない。
- `scripts/transcription/cli.py`
  - CLI引数の定義と`RunOptions`への変換。
- `scripts/transcription/orchestration.py`
  - 対象収集、dry-run停止、first pass、second pass、見出し生成、保存、summaryの実行順序。外部処理は`PipelineSteps`境界から呼ぶ。
- `scripts/transcribe_segments.py`
  - entry pointと互換facade。実行開始時だけ`.env`を読み、runtime設定を適用して各処理をorchestratorへ接続する。import時にはprocess environmentを変更しない。
- `scripts/headline_source_selection.py`
  - source文の正規化、辞書語照合、文候補の評価・選定の正本。
- `scripts/headline_candidate_selection.py`
  - 見出し候補の検証、比較、順位付け、決定的fallbackの正本。provider通信やpipeline順序を持たない。
- `scripts/headline_pipeline.py`
  - source品質penalty、generation strategy、skip判断を含む純粋な見出し品質判断。
- `scripts/headline_scoring.py`
  - candidate score、ranking、confidence labelの正本。
- `scripts/headline_generation.py`
  - provider応答抽出、HTTPエラー分類、transport一時障害判定、retry/fallback順序とSDK・HTTP境界。provider固有処理はcallbackへ戻さない。

## ローカル配信経路

1. `npm start` は `frontend/` のVite開発サーバーを `localhost:4174` で起動する。
2. `frontend/index.html` が `src/main.tsx` を読み込む。
3. `src/main.tsx` がKumo standalone CSS、`src/styles.css`、`App.tsx` を読み込む。
4. Viteプラグインがリポジトリ直下の `data/` を `/data/` として読み取り専用配信する。
5. Viteプラグインが `config/site.json` を `/site-config.json` として返す。
6. Viteのpublic directoryが `frontend/public/favicon.svg` を `/favicon.svg` として返す。

## 公開配信経路

1. `scripts/build_public.sh` が `frontend/` をTypeScript・Viteでビルドする。
2. `public/` を再作成し、Viteバンドルを配置する。
3. 公開可能な `data/vod_index.json`、`data/vods.json`、個別VOD JSON、見どころサムネイルをコピーする。
4. `config/site.json` と環境変数から `public/site-config.json` を生成する。
5. `scripts/apply_site_metadata.py` が同じ設定からtitle、description、OG、language、公開URLを`public/index.html`へ埋め込む。
6. Vite bundleに含まれる `frontend/public/favicon.svg` をそのまま配信生成物へ含める。
7. robots.txtとsitemap.xmlを生成する。
8. Renderは `public/` を静的配信する。

`config/tag-rules.json`はコメント解析時だけ読み込み、公開用`site-config.json`には含めない。VOD更新は次の責務へ分ける。

- `scripts/update_vods.py`: CLI、通常更新・backfillの実行順序、取得・解析・保存の接続。`.env`は実行開始時だけ読む。
- `scripts/vod_sources.py`: Twitch Helix/GQL/TwitchMetrics、TwitchDownloaderCLIの取得境界とfallback。
- `scripts/vod_highlights.py`: コメント量集計、z-score区間検出、ランキング、タグ分類、活動マップ。
- `scripts/vod_serialization.py`: 公開フィールドのwhitelist、JSON整形、保持期間、サムネイル整合性。

共通タグ規則と`config/tag-rules.json`のチャンネル固有規則は`vod_highlights.py`で結合する。

## データ読込

1. `data/vod_index.json` を読み、VODを `published_at` の新しい順へ並べる。
2. `page` クエリに応じて5件を選ぶ。
3. 各行の `detail_path` から `data/vods/{vod_id}.json` を読む。
4. 各VODの見どころを `rank`、なければ `start_sec` で並べ、先頭3件を表示する。

## プレイヤー

- Reactツリー内には寸法を決める `.player-frame` を残す。
- YouTubeプレイヤー本体はbody直下のポータルへ置き、枠と位置・幅・高さを同期する。
- 初期表示ではiframeを即時表示し、YouTube IFrame APIの準備後にinteractive playerへ移行できる。
- 同一VODの操作はinteractive playerをseekする。
- 別VODでは必要に応じてplayerを再生成する。
- SDKを利用できない場合はiframe表示を維持する。

## レスポンシブ

- PCは左再生領域と右情報レールの2カラム。
- 900px以下は1カラム。
- 600px以下では余白、見どころサムネイル、盛り上がりマップ高さをモバイル用へ縮小する。
- 基準PC `1792 x 864` では縦・横スクロールなしを受入条件とする。

## 注意点

- `public/` は生成物であり、直接修正しない。
- 公開UIの別実装や同期経路を追加せず、`frontend/`へ集約する。
- UI変更時は `AGENTS.md` と `docs/PUBLIC_SITE_SPEC.md` を先に確認する。

## YouTube provider

- `scripts/youtube_sources.py` がOracle VM経由のYouTube live_chat取得とvideoOffsetTimeMsecの正規化を担う。
- `scripts/vod_sources.py` はTwitchとYouTubeの取得境界を統一し、`vod_highlights.py`の集計アルゴリズムは共有する。
- `frontend/src/player/` はproviderごとのSDKアダプタを共通の再生要求へ接続する。
