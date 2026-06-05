from schema.chat_conversations import ChatConversation
from service.chat_conversations import create_chat_conversation


def create_conversation() -> ChatConversation:
    return create_chat_conversation()
