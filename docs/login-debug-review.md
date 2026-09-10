# ログイン調査メモ

## デバッグ手順

1. 実行環境で `LIFF_DEBUG_LOGGING=true` にしてアプリを再起動する。
2. LINE内ブラウザと外部ブラウザそれぞれでマイページを開く。
3. アプリログの `[LIFF CLIENT]` と `[LIFF AUTH]` から `trace` を取り、同じ値の `[LINE AUTH]` を確認する。ページ移動でtraceは変わる。
4. 調査後は `LIFF_DEBUG_LOGGING=false` に戻す。認証失敗の警告ログは引き続き出力される。

今回追加したイベント：

| event | 確認すること |
| --- | --- |
| verification_succeeded | LINE検証成功。duration_msで検証待ち時間を確認 |
| verification_rejected | LINEがトークンを拒否 |
| verification_unavailable | 通信障害・タイムアウト |
| verification_invalid_json / verification_invalid_claims | 検証応答の形式異常 |
| verification_missing_subject / verification_user_mismatch | ユーザーID欠落・不一致 |
| session_reused | 検証済みセッションを再利用 |
| credentials_missing | 再利用できるセッションもトークンもない |

認証診断では、イベント名・項目・値の型を許可リストで検査する。自由なエラー本文、URL、Referer、User-Agentは保存しない。ブラウザでも送信前に同じ許可リストを適用する。LINE検証APIのエラー本文も記録しない。

## 修正済み

- LINE検証のタイムアウト・OS通信例外を処理し、未処理の500を防止。
- `/link/liff` の配列JSONや数値・配列の認証フィールドを400で拒否。
- 共通トークン抽出処理とLINE検証応答の型を検査。
- 共通検証処理でも期待ユーザーIDとsubを照合。
- `/link/liff` の認証失敗時に認証時刻も削除。

## 追加改善の実装結果

| 対象 | 箇所 | 修正内容 |
| --- | --- | --- |
| 一時障害 | line_auth_service.py / アプリ共通エラーハンドラー | 通信障害・LINE側429/5xxを503へ変換し、有効なセッションを保持。不正トークンは従来どおり401 |
| 再試行 | liff.js / users/me.html | 認証APIの503・ブラウザ通信エラーで再試行ボタンを表示。自動ログアウトやリダイレクトをしない |
| 情報保護 | liff_diagnostics.py | イベント名と診断項目を許可リスト化。任意の文字列・入れ子・URLは記録しない |
| 共通化 | line-auth-common.js | SDK初期化・トークン期限確認・再ログインの制御を共有。初期化の同時呼出しも集約 |
| 送信停止 | liff-diagnostics.js | LIFF_DEBUG_LOGGING=falseでは通信も送信タイマーも作らない |
| 集約送信 | liff-diagnostics.js / link.py | 最大10イベントを1リクエストに集約。待機キューは60件まで。429時はRetry-Afterに従って待機 |

送信失敗・キュー超過による欠落数は、次回の送信成功時に `event=diagnostics.dropped count=...` で確認できる。最後のページ終了時は可能ならBeaconで送信する。ただしブラウザ強制終了や通信断のまま終了した場合など、欠落数自体が届かないことはある。IP単位の既存レート制限は維持する。

実機のLINE認証、Cookie保持、LINE Developers側の設定、本番ネットワークはローカルテストでは未確認。通常ログイン・期限切れ・連続再読込み・通信切断からの復帰を実機で確認する。
