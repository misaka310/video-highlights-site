# Data contract

## YouTube provider

providerがyoutubeのVODでは、vod_idとvod_urlがYouTubeの公開再生対象を指す。Twitchの既存データではproviderを省略し、Twitchを既定値として扱う。

公開UIと`data/vods.json`・`data/vod_index.json`の表示対象はYouTubeだけとする。旧Twitch VODは内部キャッシュや回帰テストで互換保持しても、公開一覧・ページャー・VOD切替へ混ぜない。

YouTube Oracle出力に含まれるvideoOffsetTimeMsecは取得時だけcontent_offset_secondsへ変換する。live_chat本文は保存しない。YouTube自身の公開字幕は別系統でcueへ正規化し、再生同期表示用データだけ保存できる。

YouTube live_chatの実取得は、`YOUTUBE_ORACLE_HOST` / `YOUTUBE_ORACLE_USER`で設定したOracle VMへSSHし、既存のOracle取得スクリプトを実行する経路だけを許可する。ローカルyt-dlpの直接実行結果をOracle取得結果として扱わず、Oracleスクリプトのログと一時TSVはメモリ上で解析する。一時TSVのコメント本文は見どころ判定中だけに使い、公開データへ保存しない。Oracleがコメント本文から選んだ見どころ区間を後段処理の正本とし、GitHub側ではoffset-onlyデータから同じ区間を再検出しない。受け渡しmanifestには選択区間、数値スコア、許可された分類タグを含め、offsetはactivity_mapなどの集計にだけ使う。分類タグは`vod_highlights.TAG_RULES`にあるラベルだけを受け入れ、任意のコメント文字列をタグとして保存しない。反応タグだけから見出しを生成してはならず、見出しは後段のWhisper/内容エンリッチメント結果から作る。

## 原則

公開データには、コメントを集計して得た数値、見どころ区間、区間を説明する短い見出し、場面サムネイル、およびYouTube自身の公開字幕cueを保存できます。コメント本文、投稿者情報、内部Whisper文字起こし、Oracleの生レスポンスは保存しません。再生に必要な`vod_id`と`vod_url`はproviderごとの公開再生参照として保持します。

公開フィードの`updated_at`はその内容を生成した公開更新時刻、`next_update_at`はその生成時刻より後に来る定期更新目標（毎日09:00 JST）です。生成時刻が09:00より前なら同日、以後なら翌日の目標を保存します。サイトは静的データを表示するため、保存済みの`next_update_at`を過ぎた場合は表示だけを次の未来の09:00 JSTへ日次で進めます。`updated_at`は実際の公開データ更新時刻のまま保持します。

## `data/processed_vods.json`

日次更新の再利用キャッシュです。

各VODで保持するフィールド:

- `provider`（YouTubeでは`youtube`、Twitchでは省略可）
- `vod_id`
- `vod_url`
- `title`
- `published_at`
- `thumbnail_url`
- `duration_sec`
- `count`
- `chat_total`
- `comments_per_hour`
- `items`
- `activity_map`
- `analysis_version`
- `analyzed_at`

`items[]`で保持するフィールド:

- `rank`
- `id`
- `start_sec`
- `end_sec`
- `duration_sec`
- `start_time`
- `end_time`
- `reason`
- `headline`
- `tags`
- `watch_url`
- `screenshot_url`

保存処理はホワイトリスト方式です。上記以外のキーは既存キャッシュに存在しても次回保存時に削除されます。プライバシー上の恒久除外IDはキャッシュ読込時と公開データ生成時の両方で除き、他の入力キャッシュや更新経路から再公開されません。恒久除外対象は`data/vods.json`・`data/vod_index.json`・個別VOD詳細・字幕・生成済み`public/`のどこにも残してはならず、公開ビルド検査は入力にないVOD詳細JSONの余分な出力も拒否します。本番の`verify:live`は除外対象の個別詳細URLがHTTP 404を返すことまで確認します。`5VzXYJdQwMY`はユーザー依頼による公開例外として恒久除外を解除し、60日保持を超えて公開します。

## `data/vods.json`

YouTubeの最新5件をトップ画面へ表示する公開データです。各VODは次のフィールドだけを持ちます。旧Twitchキャッシュはこのファイルへ出力しません。

- `provider`（YouTubeでは`youtube`、Twitchでは省略可）
- `vod_id`
- `vod_url`
- `title`
- `published_at`
- `thumbnail_url`
- `duration_sec`
- `count`
- `chat_total`
- `comments_per_hour`
- `items`
- `activity_map`

`items[]` の `headline` は内部エンリッチメントの結果です。YouTubeで文字起こし不能などにより生成できない場合、項目を公開データに残し、UIでは「コメントが集中した場面」と表示します。統計的な `reason` やチャット本文そのものは見出しとして表示しません。YouTubeの `headline` 欠損は項目単位で許容し、更新全体を止めません。生成済み `headline` は公開品質検証を通過している必要があり、通過しない見出しは公開せず欠損として扱います。

## `data/vod_index.json`

公開期間内のYouTube VOD一覧です。各行は次のフィールドだけを持ちます。旧Twitchキャッシュは除外します。

- `provider`（YouTubeでは`youtube`、Twitchでは省略可）
- `vod_id`
- `vod_url`
- `title`
- `published_at`
- `thumbnail_url`
- `duration_sec`
- `count`
- `chat_total`
- `comments_per_hour`
- `detail_path`

## `data/vods/{vod_id}.json`

個別VODの公開データです。構造は`data/vods.json`内の各VODと同一です。

## `data/captions/{vod_id}.json`

YouTube自身が公開する字幕を、再生同期表示用に正規化した任意ファイルです。字幕取得に失敗したVODや字幕が存在しないVODでは生成しません。

- `video_id`
- `source`（`youtube_manual_captions` または `youtube_automatic_captions`）
- `language`
- `language_source`
- `fetched_at`
- `cues[]`
  - `start_sec`
  - `end_sec`
  - `text`

cue時刻は同じYouTube動画の再生秒を基準とするため、Twitchとのoffset補正は持ちません。保持期間外VODの字幕ファイルは公開データ更新時に削除します。

## `data/produced_videos.json`

VODとは別に、このサイトのために制作した動画（紹介動画など）の公開データです。VOD一覧・見どころ・盛り上がりマップ・字幕の入力にはなりません。

```json
{
  "updated_at": "2026-10-21T07:09:14+09:00",
  "videos": [
    {
      "video_id": "dotitao-intro",
      "title": "…",
      "description": "…",
      "credits": "…",
      "duration_sec": 300.5,
      "published_at": "2026-10-21",
      "poster_url": "produced-video-posters/dotitao-intro.jpg",
      "video_url": "/media/dotitao-intro.mp4",
      "chapters": [{ "start_sec": 0, "label": "…" }]
    }
  ]
}
```

- `video_id`、`title`、`video_url`、`duration_sec`、`published_at` は必須です。
- `poster_url` は `data/` 配下の相対パスだけを許可し、ファイルの存在を公開ビルド検査で確認します。
- `chapters[].start_sec` は昇順・重複なしとし、`duration_sec` 未満に収めます。
- `video_url` は `http(s)://` の絶対URL、またはサイト直下のパスです。制作動画の本体ファイルはリポジトリへ置かず、配信できるURLが決まった時点で設定します。
- `video_url` はHLSのマスタープレイリスト（`.m3u8`）を推奨します。HLSでは回線に応じて解像度が変わり、モバイルでも待たずに再生できます。`hls.js` を使い、ネイティブHLS対応ブラウザではそのまま再生します。MP4の直リンクも指定できます。
- HLSを用意する場合は、1080p / 720p / 480pの3段階を4秒セグメントで作り、`master.m3u8` から各 `index.m3u8` を参照します。各段は同じキーフレーム間隔（4秒）で作ります。
- ドチタオトレーラーは `/media/dotitao-trailer/master.m3u8` を公開サイト固定エントリポイントとして使う。`frontend/public` 内のマスタープレイリストのみを配信物へ含め、動画本体・画質別プレイリスト・セグメントは外部CDNを参照する。制作版番号は公開する作品名・説明・サムネイル名・`video_url` に含めない。
- 公開ビルドは `scripts/export_produced_videos.py` を通し、`video_url` が絶対URLの制作動画だけを `public/data/produced_videos.json` へ出力します。ローカル確認用の `/media/*` は公開物へ出さず、対象が0件なら空の `videos` を出力します（サイトは導線を表示しません）。
- 素材の本体をローカルで確認するときだけ、開発サーバーが `PUBLIC_MEDIA_DIR` を指すディレクトリから `/media/*` を配信します。この経路は開発専用で、公開ビルドは動画本体をコピーしません。

## `activity_map`

- `bucket_sec`: 集計間隔。通常10秒
- `duration_sec`: VODまたはコメント分布の対象時間
- `last_comment_sec`: 最後にコメントが存在した時刻
- `buckets`: 時間帯ごとのコメント件数

## 保存禁止

次の情報はリポジトリへ保存しません。

- コメント本文、投稿者名、ユーザーID、コメント単位の投稿時刻
- 音声や内部Whisper文字起こし本文
- Oracleの生レスポンス、取得用コマンド、照合用の一時フィールド
- 見出し生成に使った入力文、候補、プロンプト、モデル応答
- raw chatアーカイブ
