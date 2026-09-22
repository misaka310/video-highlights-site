# Public Site Operations

この文書は、公開、VOD更新、保護ブランチとGitHub Actionsの運用仕様の正本である。画面仕様は `PUBLIC_SITE_SPEC.md`、再生仕様は `PLAYBACK_SPEC.md` を参照する。

## 標準検証

依存関係は検証と分離し、初回またはlockfile更新時だけ次を実行する。

```text
npm run setup
```

ローカルとPull Request CIの製品必須ゲートは、リポジトリルートの次のコマンドを正本とする。

```text
npm run verify
```

このゲートはfrontendのtypecheck、lint、単体テスト、Pythonテスト、`public/`生成・内容検証・同一環境での再生成一致、repository hygieneを含む。ブラウザ操作を伴うPlaywright E2Eは標準ゲートに含めず、ユーザーの明示許可がある場合だけ `npm run verify:browser` で実行する。実YouTubeやデプロイ済みRenderへ依存する検証は含めない。

YouTubeプレイヤーまたは公開経路へ影響する変更は、通常ゲート成功後かつデプロイ完了後に次の非GUIデータ検証を独立実行する。

```text
npm run verify:live
```

実YouTube/Renderをブラウザ操作で検証する場合は、ユーザーの明示許可があるときだけ `npm run verify:live:browser` を実行する。

本番URLは`config/site.json`の`site.base_url`から解決し、`LIVE_BASE_URL`が指定された場合だけ上書きする。HTMLは配信基盤が除去する空行を無視して照合し、JavaScript・CSS・設定ファイルは内容hashを一致させる。検証対象URLが空の場合はskipせず設定エラーとして失敗させる。

## 公開フロー

1. `main` から `release/**` ブランチを作る。
2. `npm run verify` を通し、意図したファイルだけをコミットしてpushする。
3. `.github/workflows/publish-release.yml` が同一リポジトリ内のPRを作成する。
4. `public-readiness`、`Frontend CI`、`Repository hygiene`、`Repo Launch Doctor` を対象SHAで確認する。
5. `action_required` のrunは、差分とworkflow変更を確認したうえでActions write権限により承認する。
6. 必須runがすべて成功してからsquash mergeし、releaseブランチを削除する。
7. Render上のHTML、公開データ、PC・スマホ表示を確認し、必要な変更では `npm run verify:live` を通す。

PR番号、run ID、コミットSHAをworkflowへ固定値として残さない。実行時に対象ブランチとhead SHAから解決し、マージ直前にもPR headが変わっていないことを確認する。
PR作成、対象SHAの検証、head SHA確認、squash mergeは`.github/scripts/checked_pr_merge.py`を共通経路とする。通常のrelease PRは`pull_request` runを待ち、Actionsが作成する自動更新PR（`automation/update-vods`、`automation/youtube-material-*`）は承認待ちrunで停止しないよう、3つの必須workflowを`workflow_dispatch`で対象SHAへ明示実行する。

## 定期VOD更新

YouTubeの本番取得経路は、`YOUTUBE_ORACLE_HOST`と`YOUTUBE_ORACLE_USER`で設定したOracle VMだけとする。OracleはYouTube live_chatの取得、YouTube公開字幕の任意取得、コメント時刻抽出、既存の10秒bucket/z-scoreによる見どころ決定、選択区間の音声・軽量映像の切り出しまでを担当する。GitHub ActionsはYouTubeへ直接アクセスせず、OCI Object Storageの一時PARオブジェクトを受け取ってWhisper、見出し、サムネイル、字幕JSON、検証、checked PR公開を担当する。Renderは`main`更新後の静的サイト公開を担当する。

取得スクリプトとSSH鍵は、それぞれ`YOUTUBE_ORACLE_SCRIPT_PATH`と`YOUTUBE_ORACLE_KEY_PATH`で実行時に指定する。Oracle上の実行ファイル、Deno、Cookie、作業用TSVの場所も`YOUTUBE_ORACLE_REMOTE_*`環境変数で指定し、実値は表示・commitしない。

```powershell
$env:YOUTUBE_ORACLE_HOST = '<ORACLE_HOST>'
$env:YOUTUBE_ORACLE_USER = '<ORACLE_USER>'
$env:YOUTUBE_ORACLE_KEY_PATH = '<SSH_KEY_PATH>'
$env:YOUTUBE_ORACLE_SCRIPT_PATH = '<ORACLE_SCRIPT_PATH>'
$env:YOUTUBE_ORACLE_REMOTE_YTDLP_PATH = '$HOME/yt-dlp'
$env:YOUTUBE_ORACLE_REMOTE_DENO_PATH = '$HOME/.local/bin/deno'
$env:YOUTUBE_ORACLE_REMOTE_COOKIES_PATH = '$HOME/youtube-cookies.txt'
$env:YOUTUBE_ORACLE_REMOTE_TSV_TEMPLATE = '$HOME/ytprobe/{video_id}-comment-times.tsv'
python scripts/update_vods.py --youtube-url 'https://www.youtube.com/watch?v=WGTrmrSvZH0'
```

- Oracleの`ops/oracle/youtube-highlight.timer`は毎日**06:07 JST**に起動し、`YOUTUBE_ORACLE_STREAMS_URL`で指定したYouTubeチャンネルの`/streams`から未処理の新しいアーカイブを最大5件解決して1つのbundleへまとめ、Actionsの`process-youtube-material.yml`へ`repository_dispatch`を1回送る。新しい配信がない日は処理済みIDを見て正常終了する。GitHub ActionsのcronはYouTube取得経路に使わない。
- yt-dlpがライブチャットJSONを生成した後に付随形式のHTTP 403で終了する場合は、生成済みJSONが非空であることを検証して処理を継続する。JSONがない、または空の場合は失敗として扱う。
- 既存`.github/workflows/update-vods.yml`のschedule宣言は互換検査のため残すが、現在の`if: github.event_name == 'workflow_dispatch'`による停止を無条件に解除しない。
- GitHub側の混雑により実際の開始・完了が遅れることはある。画面の「次回更新予定」は処理開始時刻ではなく、公開反映目標の09:00 JSTを表示する。
- 手動更新は `workflow_dispatch` で `main` を指定する。
- `data/vods.json` は公開トップ用のYouTube最新5件、`data/vod_index.json` は保持期間内のYouTube一覧を持つ。既存キャッシュにTwitchが残っていても、YouTubeのActions処理が公開出力前に除外する。
- YouTube更新データは `automation/youtube-material-*` ブランチとPRを経由し、公開準備チェック成功後にmainへマージする。旧Twitch更新workflowは停止中であり、公開出力へTwitchを戻さない。
- YouTube更新PRの検証はActions botが作成したPRでも停止しないよう、`Frontend CI`、`Repository hygiene`、`Repo Launch Doctor`を`workflow_dispatch`で対象ブランチへ実行してから自動マージする。PRの`pull_request`イベント待ちは使わない（GitHub側の承認待ち`action_required`になり得るため）。
- YouTubeでWhisperの内容を確定できない区間は `headline` 欠損のまま扱い、反応タグや既存の `reason` を公開UIの表示見出しへフォールバックしない。既存Twitchデータは互換維持のため従来の `reason` 表示を許容する。
- YouTube公開字幕は任意データとして扱う。手動字幕を優先し、なければ自動生成字幕を取得する。字幕取得失敗・字幕なしはVOD更新を失敗させず、字幕パネルを出さない。
- YouTube更新では、タグを見出しへ変換しない。公開用の `headline` は、Oracleから取得した見どころ区間の音声・映像を後段のWhisper/見出し生成へ渡して作る。素材や文字起こしを取得できない項目は `headline` を欠損のまま扱い、反応タグを見出しに見せかけない。
- Oracle素材を処理する `process-youtube-material.yml` の見出し生成は、Whisper文字起こしを入力としてGroqの `openai/gpt-oss-120b` を使う。LLM応答が得られない場合やローカル抽出フォールバックしか得られない場合、その見出しは公開せず更新処理を失敗させる。LLMの候補選定と再試行は公開判定（`is_publishable_headline`）と同じ基準を使い、公開判定を通らない候補は再試行の対象として選定から除外する。見出しプロンプトには公開判定の文字数（8〜24文字）、疑問符と引用括弧の禁止を明記する。
- 既存VODの見出しだけを修復する場合は `workflow_dispatch` の `repair_vod_id` を指定し、保存済みのYouTube公開字幕から同じGPT-OSS 120B見出し生成経路を通して全見どころを再生成する。通常のOracle素材処理ではこの修復経路を使わない。
- Oracleの定期実行は`YOUTUBE_ORACLE_STREAMS_URL=https://www.youtube.com/@dotitube/streams`を優先し、固定の`YOUTUBE_ORACLE_VIDEO_URL`へ戻さない。Cookieは`YOUTUBE_ORACLE_REMOTE_COOKIES_PATH`で指定したOracle上のファイルだけを使う。
- YouTubeの内部音声解析は、スクリーンショット不要時はHTTPS音声のみ、必要時はHTTPSの軽量映像・音声を選ぶ。Twitchの区間取得フォーマットは変更しない。
- 公開準備チェックは、生成済み `headline` の品質と見どころサムネイルの存在を検証する。見出しが欠損する場合や、生成済み見出しが品質基準を満たさない場合は従来どおり失敗させる。

### Oracle → Actions 一時素材

受け渡しはOCI Object Storageの短命オブジェクトとPre-Authenticated Request（PAR）を使う。Oracleは固定した一時オブジェクトに対する`YOUTUBE_ORACLE_BUNDLE_UPLOAD_URL`へ選択区間だけをPUTし、Actionsは`YOUTUBE_ORACLE_BUNDLE_READ_URL`で取得する。PARは期限まで再利用できるため毎日作り直さず、6か月を目安に両方を同時ローテーションする。OCIのPARではオブジェクトを削除できないため、OCIの1日以内のlifecycle ruleで一時オブジェクトを自動削除する。bundleには公開メタデータ、offset-onlyの時刻一覧、選択区間ごとのWAV/WEBP、および取得できた場合だけYouTube公開字幕cueを入れる。raw chat、ユーザー名、メッセージ、内部Whisper文字起こしは入れない。

2026-09-17に適用したOCI設定は次のとおり。`shareclip`は別用途のため使用しない。

| 項目 | 設定 |
| --- | --- |
| Region | `ap-osaka-1`（Japan Central (Osaka)） |
| Compartment | `kiralab`（root） |
| Bucket | `youtube-material-upload`（private / Standard） |
| 固定オブジェクト | `youtube-material/latest.tar.gz` |
| Upload PAR | `youtube-material-upload-par-20260917`（object write/overwrite、2027-03-17 07:00 UTCまで） |
| Read PAR | `youtube-material-read-par-20260917`（object read、2027-03-17 07:00 UTCまで） |
| Lifecycle | `delete-youtube-material-after-1-day`（有効、`youtube-material/`接頭辞、1日後削除） |
| IAM policy | `YouTubeMaterialLifecyclePolicy`（`target.bucket.name='youtube-material-upload'`条件付き） |

PAR URLそのものは秘密情報のため、repositoryやドキュメントには保存しない。PARでは削除できないため、Workflowの削除処理は持たず、OCI Lifecycleに任せる。

2026-09-17に対象バケットを再作成した際、OCI上では旧PARがアクティブに見えても旧バケットを指して404になったため、Upload/Read PARを同日付の名前で再発行し、Oracle環境とGitHub Actions Secretを更新した。以後もPARは期限まで再利用し、期限前に両方を同時ローテーションする。

YouTubeの認証Cookieが切れた場合は、Oracle VMのChromeへログインして認証済みCookieを更新し、`YOUTUBE_ORACLE_REMOTE_COOKIES_PATH`で指定したOracle上のファイル（mode `600`）へ配置する。Windows側のCookieを本番経路の代替にせず、更新後はOracle上のyt-dlpメディア取得テストとone-shot serviceで復旧を確認する。Cookie・Chromeプロファイル・SSH秘密鍵はrepositoryへ保存しない。

Oracleのsystemd service/timerテンプレートとインストール手順は`ops/oracle/README.md`に置く。Discord通知はOracle側の`DISCORD_WEBHOOK_URL`だけで行い、Cookie認証失敗、bot/challenge、Oracle runtime、yt-dlp/Deno、live_chat 0件、一時ネットワーク障害を分類し、同一連続失敗は一度だけ通知する。復旧時は一度だけ復旧通知を送る。

## GITHUB_TOKENと連鎖実行

`GITHUB_TOKEN` を使ったpushやmergeが発生させた通常イベントは、別workflowを自動起動しない。後続処理が必要な場合は、対象workflowを `workflow_dispatch` で明示的に実行し、作成されたrunのevent、head SHA、結果を確認する。

workflow badgeやブランチ更新だけで成功判定しない。対象runを特定し、`queued`、`in_progress`、`action_required`、`completed` と最終conclusionを確認する。

## 更新PRが止まった場合

1. `automation/update-vods` のSHAとPR head SHAが一致するか確認する。
2. 必須workflowのrunを対象SHAで列挙する。
3. `action_required` の場合は差分を確認して承認する。
4. 全runの成功後に、head SHA一致条件付きでマージする。
5. main、公開URLの `data/vods.json`、`updated_at`、最新VOD IDを確認する。

一時的なPR番号・run ID専用workflowをmainへ残さない。障害対応で一時ブランチを使った場合は、完了後にリモート・ローカル双方を削除する。

## 完了条件

- mainとorigin/mainが一致している。
- 作業ツリー、stash、一時releaseブランチが残っていない。
- `npm run verify` が成功している。
- 公開URLがKumo版の静的バンドルを返す。
- 公開データの `updated_at` と最新5件がmainと一致する。
- 次回の定期更新が09:00 JSTとして表示される。
