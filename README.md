# Video Highlights Site

YouTubeライブアーカイブから見どころを抽出し、再生しやすい静的サイトとして公開するための基盤です。

現在の公開例は [dotitao moments](https://dotitao-moments.onrender.com/) です。これはこのリポジトリを使った具体的な公開インスタンスであり、リポジトリ自体の製品名ではありません。

このプロジェクトは非公式ツールです。YouTube、Twitch、対象チャンネル、配信者名、その他の名称・商標・コンテンツの権利は各権利者に帰属します。

## 主な機能

- コメント量の時系列集計と見どころ抽出
- YouTube動画の見どころ再生と再生位置の同期
- 盛り上がりマップ、公開字幕、見どころサムネイル
- 静的公開用データとサイトの再現可能な生成
- GitHub Actionsによる公開データ更新

## 構成

```text
frontend/        React + TypeScript + Vite の公開UI
scripts/         集計、エンリッチメント、公開ビルド
data/            公開可能な集計データと字幕
config/          公開インスタンスの設定
public/          公開ビルドの生成先
docs/            仕様、データ契約、運用手順
```

公開UIの実装正本は `frontend/` です。公開画面の仕様は [`docs/PUBLIC_SITE_SPEC.md`](docs/PUBLIC_SITE_SPEC.md) を参照してください。

## ローカルで見る

Node.js 20以降を使用します。

```powershell
npm ci --prefix frontend
npm start
```

`http://localhost:4174/` を開きます。

## 検証

```powershell
npm run setup
npm run verify
```

## ドキュメント

- [`docs/PUBLIC_SITE_SPEC.md`](docs/PUBLIC_SITE_SPEC.md) — 公開サイトの製品仕様
- [`docs/PLAYBACK_SPEC.md`](docs/PLAYBACK_SPEC.md) — 再生と字幕表示の仕様
- [`docs/data-contract.md`](docs/data-contract.md) — 公開データの契約
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) — 更新・公開・GitHub Actionsの運用
- [`PRIVACY.md`](PRIVACY.md) — プライバシー方針
- [`SECURITY.md`](SECURITY.md) — 脆弱性の報告方法

READMEには入口と概要だけを記載し、設定値・運用手順・内部処理の詳細は各ドキュメントで管理します。

## License

[MIT License](LICENSE)
