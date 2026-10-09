# Contributing

このリポジトリは、公開サイトのソースと再現可能な検証だけを保持します。

## バグ報告・改善提案

通常のバグ報告と改善提案は [GitHub Issues](https://github.com/misaka310/video-highlights-site/issues) で受け付けます。既存Issueを確認したうえで、再現手順、期待する結果、実際の結果、影響範囲を可能な範囲で記載してください。Issueとその応答はGitHub上で履歴として保持されます。

認証情報、秘密鍵、個人情報、非公開URLなどをIssueへ貼り付けないでください。セキュリティ脆弱性は公開Issueではなく [`SECURITY.md`](SECURITY.md) の非公開報告手順を使用してください。

## 変更を提出する手順

1. `main` の最新状態を基準に作業ブランチを作成します。
2. 目的に必要な範囲だけを変更し、既存仕様を変える場合は対応する `docs/` の正本も同じ変更で更新します。
3. 振る舞いを変更した場合は、その振る舞いを検証する自動テストも追加または更新します。
4. 下記の必須チェックを通します。
5. Pull Requestを作成し、変更目的、影響範囲、実行した検証を説明します。
6. 必須のGitHub Actionsが成功してからマージします。

TypeScriptは既存のTypeScript/ESLint設定、Pythonは既存コードのスタイルと型・テスト方針に合わせてください。関係のない大規模リファクタを同じPull Requestへ混ぜないでください。

## 公開ツリーに含めないもの

- 見出し生成の診断ログ、候補スコア、provider応答の要約
- 一時的な修正適用用・権限確認用・再実行トリガー用のGitHub Actions workflow
- Playwright成果物、テスト結果、ローカルブラウザプロファイル
- AI作業メモ、レビュー受け渡しファイル、ローカル状態
- Twitchコメント本文、ユーザー名、コメント単位の投稿時刻

診断情報が必要な場合は、短い保持期間を設定したGitHub Actions artifactとして保存してください。公開ソースへコミットしてから削除する運用は行いません。

一度だけ実行したい処理は、保守対象のworkflowへ `workflow_dispatch` 入力として追加するか、ローカルで実行してください。一時workflowをmainへ追加して直後に削除しないでください。

## 必須チェック

```bash
npm run setup
npm run verify
```

デプロイ済みデータへ影響する変更は、通常ゲート成功後に非GUIの `npm run verify:live` も実行します。Playwrightによるブラウザ操作E2Eは標準ゲートに含めず、明示許可がある場合だけ `npm run verify:browser` / `npm run verify:live:browser` を実行します。

`check_repository_hygiene.py` は、診断サマリー、一時mutation workflow、ローカル成果物がGit追跡対象へ入っていないことを検証します。

## 履歴方針

既存の公開履歴は、秘密情報の漏洩が確認されていないため保持します。過去の試行コミットを隠す目的だけで履歴を書き換えません。今後はこのガードにより、内部診断や一時workflowを公開履歴へ追加しない運用とします。
