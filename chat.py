"""Chat/conversation CRUD — create, load, update, delete chats, batch message saving."""

import json
import uuid
from datetime import datetime, timezone
from auth import get_supabase


def _metadata_column_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "metadata" in msg and ("column" in msg or "schema cache" in msg)


_META_PREFIX = "<!--META:"
_META_SUFFIX = "-->"


def _embed_metadata(content: str, metadata: dict) -> str:
    """Embed runtime metadata as a hidden HTML comment in message content.
    This guarantees metadata survives DB round-trips even if the JSONB column is missing.
    """
    if not metadata:
        return content
    embed = {}
    for key in ["provider", "model", "latency", "cost", "_route_display", "_reason_display"]:
        v = metadata.get(key)
        if v is not None and v != "":
            embed[key] = v
    if not embed:
        return content
    return f"{_META_PREFIX}{json.dumps(embed, separators=(',',':'))}{_META_SUFFIX}\n{content}"


def _extract_metadata(content: str) -> tuple[str, dict]:
    """Extract embedded metadata from message content.
    Returns (clean_content, metadata_dict).
    """
    if content.startswith(_META_PREFIX):
        end_idx = content.find(_META_SUFFIX)
        if end_idx > 0:
            meta_str = content[len(_META_PREFIX):end_idx]
            try:
                metadata = json.loads(meta_str)
                clean = content[end_idx + len(_META_SUFFIX):].lstrip("\n")
                return clean, metadata
            except (json.JSONDecodeError, ValueError):
                pass
    return content, {}


def load_chats(user_id: str) -> dict:
    """Load all conversations for a user from Supabase, ordered by most recent update."""
    supabase = get_supabase()
    try:
        result = supabase.table("conversations").select(
            "id, title, created_at, updated_at, pinned"
        ).eq("user_id", user_id).order("updated_at", desc=True).execute()
    except Exception:
        return {}
    chats = {}
    for row in result.data or []:
        chats[row["id"]] = {
            "id": row["id"],
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "pinned": row.get("pinned", False),
            "messages": [],
        }
    return chats


def create_chat(user_id: str, title: str = "New Chat") -> str:
    """Create a new conversation in Supabase and return its UUID."""
    supabase = get_supabase()
    cid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("conversations").insert({
            "id": cid,
            "user_id": user_id,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "pinned": False,
        }).execute()
    except Exception:
        pass
    return cid


def update_chat(chat_id: str, user_id: str, data: dict) -> bool:
    """Update a conversation's fields (title, pinned, etc.) in Supabase."""
    supabase = get_supabase()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        supabase.table("conversations").update(data).eq("id", chat_id).eq("user_id", user_id).execute()
        return True
    except Exception:
        return False


def delete_chat(chat_id: str, user_id: str):
    """Delete a conversation and all its messages from Supabase."""
    supabase = get_supabase()
    try:
        supabase.table("messages").delete().eq("conversation_id", chat_id).eq("user_id", user_id).execute()
        supabase.table("conversations").delete().eq("id", chat_id).eq("user_id", user_id).execute()
    except Exception:
        pass


def load_messages(chat_id: str) -> list:
    """Load all messages for a conversation, ordered by creation time."""
    supabase = get_supabase()
    try:
        result = supabase.table("messages").select("*").eq("conversation_id", chat_id).order("created_at").execute()
        loaded = []
        for m in result.data or []:
            content = m["content"]
            col_meta = m.get("metadata") or {}
            # Try to extract embedded metadata from content as fallback
            clean_content, embedded_meta = _extract_metadata(content)
            # Prefer column metadata over embedded, but use embedded if column is empty
            meta = col_meta if col_meta else embedded_meta
            loaded.append({
                "role": m["role"],
                "content": clean_content,
                "timestamp": m.get("timestamp", ""),
                "metadata": meta,
            })
        return loaded
    except Exception:
        return []


def save_message(chat_id: str, user_id: str, role: str, content: str, timestamp: str = "", metadata: dict | None = None) -> bool:
    """Insert a single message into Supabase."""
    supabase = get_supabase()
    # Embed metadata in content as fallback for persistence
    db_content = _embed_metadata(content, metadata or {}) if role == "assistant" else content
    record = {
        "conversation_id": chat_id,
        "user_id": user_id,
        "role": role,
        "content": db_content,
        "timestamp": timestamp,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if metadata:
        record["metadata"] = metadata
    try:
        supabase.table("messages").insert(record).execute()
        return True
    except Exception as e:
        if metadata and _metadata_column_missing(e):
            try:
                record.pop("metadata", None)
                supabase.table("messages").insert(record).execute()
                return True
            except Exception:
                return False
        return False


def save_messages_batch(chat_id: str, user_id: str, messages: list[dict]) -> bool:
    """Insert multiple messages in a single PostgREST call for efficiency."""
    supabase = get_supabase()
    records = []
    try:
        now = datetime.now(timezone.utc).isoformat()
        for msg in messages:
            content = msg["content"]
            meta = msg.get("metadata") or {}
            # Embed metadata in content as fallback for persistence
            db_content = _embed_metadata(content, meta) if msg.get("role") == "assistant" else content
            records.append({
                "conversation_id": chat_id,
                "user_id": user_id,
                "role": msg["role"],
                "content": db_content,
                "timestamp": msg.get("timestamp", ""),
                "metadata": meta,
                "created_at": now,
            })
        if records:
            supabase.table("messages").insert(records).execute()
        return True
    except Exception as e:
        if records and _metadata_column_missing(e):
            try:
                for record in records:
                    record.pop("metadata", None)
                supabase.table("messages").insert(records).execute()
                return True
            except Exception:
                return False
        return False


def sync_chat(chat_id: str, user_id: str, title: str = None) -> bool:
    """Touch the updated_at timestamp (and optionally update title) for a conversation."""
    if not chat_id:
        return False
    supabase = get_supabase()
    data = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if title:
        data["title"] = title
    try:
        supabase.table("conversations").update(data).eq("id", chat_id).eq("user_id", user_id).execute()
        return True
    except Exception:
        return False
