from flask import current_app
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    PushMessageRequest,
    TextMessage,
)


def send_line_message(user_id, text):
    if not user_id:
        return False

    token = current_app.config["LINE_CHANNEL_ACCESS_TOKEN"]
    if not token:
        current_app.logger.warning("LINE_CHANNEL_ACCESS_TOKEN is not set.")
        return False

    configuration = Configuration(access_token=token)

    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.push_message(
            PushMessageRequest(
                to=user_id,
                messages=[TextMessage(text=text)],
            )
        )

    return True
