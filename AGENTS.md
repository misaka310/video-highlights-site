# Repository Working Rules

このリポジトリで作業する全エージェントは、変更前に次を読むこと。

1. `docs/PUBLIC_SITE_SPEC.md`
2. 再生に触れる場合は `docs/PLAYBACK_SPEC.md`
3. データに触れる場合は `docs/data-contract.md`
4. 公開、GitHub Actions、VOD更新に触れる場合は `docs/OPERATIONS.md`

## 作業原則

- 公開UIの唯一の正本は `frontend/`。旧UI資産や別実装を追加しない。
- 部品単体ではなく、ヘッダー、プレイヤー、盛り上がりマップ、右カラム、ページャーを一画面として評価する。
- ユーザーが指定した完了条件を満たさない変更を成功扱いにしない。
- 既存仕様を変更する必要がある場合は、実装前に理由と影響を確認する。
- 関係のない大規模リファクタ、データ構造変更、公開デプロイ、push、PR、mergeを行わない。

## UI変更時の必須確認

- 基準PC表示 `1792 x 864` で、ページ全体に縦スクロールを発生させない。
- 基準PC表示で横スクロールを発生させない。
- PCではプレイヤー幅を確保しながら、右カラムを細くしすぎない。
- 実利用端末・実ブラウザ・OS GUIへキーボード/マウス入力を注入しない。タスクトレイ操作を含むGUI自動操作を検証に使わない。
- UI検証は型検査、DOM/ロジック単体テスト、静的build検証を優先する。ブラウザ操作を伴うE2Eはユーザーの明示許可なしに実行しない。
- 見た目の確認が必要な場合も、ユーザーの実環境を操作せず、明示許可された隔離環境だけを使う。

## 維持する機能

- 初期表示は自動再生なし、ミュート。
- ユーザーが見どころ、VODタブ、盛り上がりマップを押した場合は音声付き再生。
- 同一VOD内は既存プレイヤーをseekし、別VODだけ必要に応じて再生成。
- 連続操作は最後の操作を優先。
- 10秒戻るは実際の再生位置を優先。
- Twitch SDK失敗時のiframeフォールバックを維持。
- プレイヤー下に配信タイトルを追加しない。
- YouTube自身の公開字幕は再生位置に同期して表示してよい。内部Whisper文字起こしは公開しない。
- Groq、Whisper、見出し生成、内部エンリッチメント処理を削除しない。

## 標準検証

依存関係の初回準備またはlockfile更新後だけ、リポジトリルートで次を実行する。

```text
npm run setup
```

通常の変更は、リポジトリルートから次の一つを製品必須ゲートとして実行する。

```text
npm run verify
```

`verify` はfrontendのtypecheck、lint、Node環境の単体テスト、Pythonテスト、`public/`生成・内容検証・再現性検証、repository hygieneを順に実行する。ブラウザ操作を伴うE2Eは含めない。明示許可がある場合だけ `npm run verify:browser` または `npm run verify:live:browser` を別途実行する。検証中に依存関係を自動インストールしない。

Twitch実サービスまたはデプロイ済みRenderへ影響する変更は、通常ゲート成功後とデプロイ完了後に独立して次を実行する。

```text
npm run verify:live
```

## 仕様の正本

- 仕様の正本: `docs/PUBLIC_SITE_SPEC.md`
- Specification source: `docs/PUBLIC_SITE_SPEC.md`
- 実装前に意図する仕様を正本へ反映し、仕様変更時は同じ変更で正本と検証を更新する。
- Specification changes require the source to be updated before implementation and in the same change.

## PR マージ後の作業ブランチ削除（必須）

- PR をデフォルトブランチへマージしたら、その PR の作業ブランチ（head）を削除する。通常マージ・Squash マージ・Rebase マージのいずれでも同じ。保護ブランチとデフォルトブランチ（`main` / `master`）は削除しない。
- GitHub の「Automatically delete head branches」や既存の自動整理ワークフローが有効でも、マージ後に実際のブランチ一覧を確認する。作業ブランチが残っていれば安全性を確認して削除し、削除確認までを PR 後処理の完了条件とする。
- 未マージの PR、他のオープン PR・進行中作業で使うブランチを削除しない。マージ後も独自の履歴を保存する必要がある場合は、正確な先端コミットをタグ等で保全・検証してからブランチを削除する。
- Squash / Rebase マージ後は元ブランチのコミットがデフォルトブランチの祖先にならない場合がある。`ahead_by != 0` だけで「未マージ」と決めつけず、PR のマージ結果とブランチ先端を確認する。
