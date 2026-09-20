"""Compatibility entry points for the shared semantic conversation brain."""


def understand(b,u,text,query_context=''):
    from finance_conversation_brain import message
    return message(b,u,text,query_context)


def pending_turn(b,u,message,context,current,query_context=''):
    from finance_conversation_brain import pending
    return pending(b,u,message,context,current,query_context)
