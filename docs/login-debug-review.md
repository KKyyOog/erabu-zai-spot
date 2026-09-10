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

追加イベントにはトークン・ユーザーID・例外本文を含めない。既存ログは自由文を含むため、ログ全体の無条件な共有は避け、必要なイベントを抽出する。

## 修正済み

- LINE検証のタイムアウト・OS通信例外をLineAuthErrorに変換し、未処理の500を防止。
- `/link/liff` の配列JSONや数値・配列の認証フィールドを400で拒否。
- 共通トークン抽出処理とLINE検証応答の型を検査。
- 共通検証処理でも期待ユーザーIDとsubを照合。
- `/link/liff` の認証失敗時に認証時刻も削除。

## 追加の改善候補（未変更）

| 優先度 | 箇所 | 現状と改善案 |
| --- | --- | --- |
| 高 | line_auth_service.py / link.py | 通信障害と不正トークンが同じ401になる。障害は503として返し、フロントでもログアウトせず再試行可能にする |
| 高 | link.py のログ整形 | キー名による伏字ではerrorMessageなど自由文内の機密値を除去できない。許可したイベント・診断項目のみ保存する方式を検討 |
| 中 | liff.js / users/me.html | 初期化・再認証・ログ送信が重複し、修正漏れにつながる。共通モジュール化する |
| 中 | 両方のログ送信関数 | サーバーログ無効時も送信する。ブラウザ側にも有効フラグを渡して通信を省く |
| 中 | /link/liff-debug | 1分30件のIP単位制限で、複数利用者や再読込みの診断ログが欠けうる。欠落件数の可視化・集約送信を検討 |

実機のLINE認証、Cookie保持、LINE Developers側の設定、本番ネットワークはローカルテストでは未確認。通常ログイン・期限切れ・連続再読込み・通信切断からの復帰を実機で確認する。
