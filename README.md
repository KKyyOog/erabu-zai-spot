# えらぶ材すぽっと

沖永良部島内にある余剰材の情報と、探している材の情報を共有し、必要な人同士をつなぐLINE連携型の掲示板です。

利用者向けの操作方法は、[アプリ利用ガイド](利用ガイド.md)を参照してください。

## 主な機能

- 「材があります」「材を探しています」を投稿する
- 材・募集・解体物件を同じ一覧で確認する
- 投稿タイプと材種で一覧を絞り込む
- 投稿者へ問い合わせる
- 提供者またはマッチ相手にLINE通知する
- 投稿を終了し、期限切れ投稿を30日間再掲載する
- 新規投稿を30日後に通常一覧から自動的に除外する
- 管理画面で投稿状態を確認・変更する
- マイページで材・解体物件を編集・削除する
- マッチング状態（「未対応」「連絡・調整中」「成立」「辞退」）を更新する
- 削除時に登録画像をCloudinaryから削除する

LINE通知に失敗した場合も希望・状態変更などの履歴は保存され、画面には通知失敗が明示されます。

## ユーザー識別とLINE通知

通常利用ではLIFFのIDトークンをサーバーで検証し、検証結果のLINEユーザーIDをユーザー情報、投稿、マッチング履歴、通知先の共通IDとして使用します。

- LINE LoginチャンネルとMessaging APIチャンネルは同じProviderに配置します。
- LINE Loginチャンネルには対象のLINE公式アカウントを連携します。
- LIFFには`openid`と`profile`スコープを設定します。
- 公式アカウントの友だち状態はLIFF起動時とfollow/unfollow Webhookで同期します。
- 旧ゲストセッションのデータは、同じブラウザで最初にLINE認証したときにLINEユーザーIDへ移行します。

本番環境では次を設定します。

```env
LINE_LOGIN_ENABLED=true
LIFF_DEBUG_LOGGING=false
USER_INFO_CACHE_SECONDS=600
LINE_SESSION_SECONDS=43200
ADMIN_SESSION_SECONDS=900
```

`LIFF_DEBUG_LOGGING`を有効にすると、Renderのアプリケーションログへ
`[LIFF CLIENT]`、`[LIFF AUTH]`、`[LIFF FRIENDSHIP]`の構造化ログを出力します。
同じ画面表示のログは匿名の`trace`値で追跡できます。IDトークン、LINEユーザーID、
認可コードなどの機密値は出力せず、必要な場合は`[redacted]`へ置き換えます。

LINE本人確認済みセッションと登録済みユーザー情報は、既定で10分間再利用します。
この時間内は登録画面や一覧画面への移動時に、LINEプロフィール取得と登録状況確認を
繰り返しません。ユーザー情報を保存した場合はサーバーキャッシュを直ちに更新し、
未登録状態はキャッシュしないため、登録・更新内容は次の表示から反映されます。

認証セッションの絶対有効期限は既定で12時間、管理操作の再認証期限は15分です。
キャッシュ時間とは別にサーバー側で検証します。認証時刻のない旧LINEセッションは再ログインが必要です。

## 通知再送・送信制限の運用

申込み、状態変更、連絡先共有は、業務データと同じトランザクションで
`notification_outbox` に通知を保存します。画面処理では初回送信を試み、
失敗した通知は再送待ちで保持します。本番では以下を**毎分実行するジョブ**に登録してください。
Webアプリと同じDATABASE_URL、LINE_CHANNEL_ACCESS_TOKEN、LIFF_ID等の環境設定を使用します。

```bash
python -m flask --app run send-notifications
```

1回に最大100件を処理し、失敗時は間隔を延ばして再試行します。
LINEの再送仕様に合わせて同じ宛先・本文・retry keyを維持し、作成から23時間で自動再送を停止します。
再試行できない4xx応答も`failed`にします。`failed`の増加や古い`pending`を監視してください。
`sent`はLINE APIでの受付を意味し、利用者の受信・既読を保証しません。
仕様: [LINE Developersの再試行ガイド](https://developers.line.biz/ja/docs/messaging-api/retrying-api-request/)

`notification_outbox`と`request_buckets`は起動時に不足していれば作成します
（既存の通知テーブルと同様、AUTO_CREATE_TABLES=falseでも作成します）。
本番反映前にステージングでテーブル作成権限と再送ジョブを確認してください。

問い合わせ・見学希望・連絡先共有・投稿は、利用者ごと・操作ごとに毎時20回まで、
マッチング状態変更は毎時60回までです。認証・診断ログは接続元IPごと・操作ごとに毎分30回までです。
制限カウンターはDBで共有します。IPは偽装可能なX-Forwarded-Forを直接信用せず、
Flaskのremote_addrを使用します。リバースプロキシが全アクセスを同一IPとして渡す環境では、
信頼するプロキシの構成に合わせて実クライアントIPの受け渡しを設定してください。

公開一覧はDB側で非公開・期限切れを除外し、材と解体物件を合わせて24件ずつ表示します。

## 公開範囲と問い合わせ後の操作

- 住所欄の詳細は投稿者本人の管理画面に保持し、公開一覧・個別詳細では町名までを表示します。既存投稿にも適用します。町名が判断できない住所は「場所は問い合わせ後に相談」と表示します。
- 詳しい住所は連絡先共有後、相手と個別に相談して伝えます。住所を問い合わせ相手へ自動送信することはありません。
- 投稿前に、公開する写真・登録者名・本文などを確認します。写真や自由記入欄に含まれる住所・個人情報は自動で除去されません。
- LINE通知は該当する問い合わせを開きます。ログインが必要な場合も問い合わせIDを引き継ぎます。
- 投稿者はマッチングを「成立」にするとき、募集を継続するか掲載を終了するか選択できます。相手の操作で投稿が終了することはありません。古い画面からの状態更新は競合を検知します。

## 運用機能の反映手順（2026-09-09）

1. DBバックアップを取得し、ステージングで既存の `migrate_posts_v2.py` が適用済みであることを確認します。
2. `python scripts/migrate_operations.py` を実行します。追加するのは `operations`（通知エラー・ジョブ完了・通報・操作履歴）と `image_upload_jobs`（画像回収用）の2テーブルです。再実行可能で、既存投稿の住所や本文を書き換えません。
3. アプリを反映し、`python -m flask --app run send-notifications` を毎分、`python -m flask --app run clean-upload-jobs` を毎日実行するジョブを登録します。アプリと同じDB・LINE・Cloudinary設定を使用します。
4. 管理画面 `/admin/` で、通知の滞留時間・失敗理由・再送ジョブの最終完了を確認します。最終完了が5分以上前の場合は警告が表示されます。外部の自動アラート連携は含まれません。

画像はCloudinaryへ送る前に回収用IDを記録します。通常はレスポンス時に投稿からの参照を確認し、未保存の画像を回収します。中断・DB障害などで残った記録は、24時間経過後に定期ジョブで最大100件ずつ再確認します。既存投稿が参照している画像は削除しません。変更前に発生した記録のない孤立画像は対象外です。

`AUTO_CREATE_TABLES=false` の場合も、これまでの通知テーブルと同様にこの2テーブルの不足分を起動時に作成します。本番では事前の移行実行を推奨します。通知再送・画像回収ジョブ自体の登録はアプリ起動だけでは行われません。

管理画面では材・募集・解体物件を検索し、25件ずつ確認できます。非公開化、通報の確認、状態変更履歴に対応します。通知本文や連絡先は運用一覧には表示しません。

検証コマンド：

```bash
python -m unittest discover -s tests -p 'test_*.py'
node --test tests/test_me_auth.cjs tests/test_ui_runtime.cjs
```

## 起動方法

```bash
python -m venv .venv
source .venv/bin/activate  # Windowsは .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

## 主要URL

- `/materials/register`：投稿タイプ選択
- `/materials/register/material`：「材があります」投稿
- `/materials/register/request`：「材を探しています」投稿
- `/materials/list`：材・募集・解体物件一覧
- `/admin`：管理画面
- `/callback`：LINE Webhook

## LIFF URL の使い分け

LINE Developers の LIFF Endpoint URL は本番ドメインのルートに設定します。

```text
https://example.com/
```

実際に案内するURLは、LIFF URL にページのパスを付けて使い分けます。

```text
https://liff.line.me/{LIFF_ID}/materials/list
https://liff.line.me/{LIFF_ID}/materials/register
https://liff.line.me/{LIFF_ID}/users/me
```

## 既存DBの更新

既存のSupabase/PostgreSQLへ本バージョンを反映するときは、アプリを更新する前に次を実行します。

```bash
python scripts/migrate_posts_v2.py
```

既存の材は「材があります」として扱い、掲載期限は設定しないため、移行直後に一覧から消えることはありません。
