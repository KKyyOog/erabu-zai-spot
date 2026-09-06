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
