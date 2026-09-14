"""Send a durable, once-per-user introduction after profile registration."""
import time
from uuid import NAMESPACE_URL, uuid4, uuid5

from flask import current_app
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.services.db_service import _engine, notification_outbox
from app.services.notification_service import deliver_notification


WELCOME_MESSAGE = """【えらぶ材すぽっとへようこそ！】
ユーザー情報の登録が完了しました。

えらぶ材すぽっとは、沖永良部島の「余っている材」と「材を探している人」をつなぐ掲示板です。解体物件の情報も共有できます。

トーク画面下のメニューから、各ページを開けます。

🪵 登録する（左）
余っている材、探している材、解体物件を投稿できます。紹介したい材や探している材があれば、ここから登録してみましょう。

🔎 一覧を見る（中央）
まずはここをタップ！気になる投稿の「＋」を押して詳細を見てみましょう。「問い合わせる」「提供できます」「見学を申し込む」から相手に希望を伝えられます。

👤 ユーザーページ（右）
プロフィール、自分の投稿、問い合わせを確認できます。問い合わせ後は「問い合わせ」タブで連絡先の共有や状況の確認をしてください。

まずは「一覧を見る」で、島にどんな材があるか探してみてください！"""


def send_welcome_once(user_id):
    if not user_id or user_id.startswith("anon_"):
        return False
    notification_id = str(uuid5(NAMESPACE_URL, "erabu:welcome:" + user_id))
    try:
        now = int(time.time())
        with _engine().begin() as conn:
            insert = sqlite_insert if conn.dialect.name == "sqlite" else pg_insert
            conn.execute(insert(notification_outbox).values(
                notification_id=notification_id, app_user_id=user_id,
                target_user_id=user_id, message=WELCOME_MESSAGE,
                retry_key=str(uuid4()), status="pending", attempts=0,
                created_at=now, next_attempt_at=now,
            ).on_conflict_do_nothing(index_elements=[notification_outbox.c.notification_id]))
        return deliver_notification(notification_id)
    except Exception:
        # Notification outages must not prevent successful profile registration.
        current_app.logger.exception("[ONBOARDING] welcome delivery could not complete")
        return False
