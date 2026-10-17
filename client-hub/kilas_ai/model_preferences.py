"""Authenticated new-chat defaults in existing owner-scoped selection storage.

The reserved ('thread', 0) row is account-wide; real conversation IDs are
strictly positive and still pass the ordinary ownership boundary. No browser
storage, session-wide unscoped model value or schema change is needed.
"""
import db

TABLES={'chat':'kilas_ai_chat_model_selections','image':'kilas_ai_image_model_selections'}


def get(owner,kind):
    row=db.query_one('SELECT model FROM '+TABLES[kind]+" WHERE user_id=? AND surface='thread' AND conversation_id=0",(owner,))
    return row['model'] if row else None


def remember(owner,kind,model):
    db.execute('INSERT INTO '+TABLES[kind]+"(user_id,surface,conversation_id,model) VALUES (?,'thread',0,?) ON CONFLICT(user_id,surface,conversation_id) DO UPDATE SET model=excluded.model",(owner,model))


def inherit(conn,owner,surface,ident):
    from . import usage
    for table in TABLES.values():
        # Snapshot without changing defaults or substituting an unavailable model.
        usage._query(conn,'INSERT INTO '+table+'(user_id,surface,conversation_id,model) SELECT user_id,?,?,model FROM '+table+" WHERE user_id=? AND surface='thread' AND conversation_id=0 ON CONFLICT(user_id,surface,conversation_id) DO NOTHING",(surface,ident,owner))
