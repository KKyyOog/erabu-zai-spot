# えらぶ材すぽっと

沖永良部島内で発生する解体材・余剰材・廃材を、必要な人につなぐためのLINE上のストック材共有掲示板です。

## 最小機能

- 材を登録する
- 材一覧を見る
- 「欲しい」ボタンを押す
- 運営者または提供者にLINE通知する
- 管理画面で材の状態を確認・変更する

## 起動方法

```bash
python -m venv .venv
source .venv/bin/activate  # Windowsは .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

## 主要URL

- `/materials/register`：材登録フォーム
- `/materials/list`：材一覧
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
