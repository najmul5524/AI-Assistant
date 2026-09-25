import sqlite3
import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

DB_FILE = Path(__file__).resolve().parent / "assistant.db"

def get_connection():
    conn = sqlite3.connect(str(DB_FILE))
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initialize database tables."""
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Conversation history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                model_used TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Reminders table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                task_text TEXT NOT NULL,
                remind_at TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # User settings / preferences table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                user_id INTEGER NOT NULL,
                pref_key TEXT NOT NULL,
                pref_value TEXT NOT NULL,
                PRIMARY KEY (user_id, pref_key)
            )
        """)

        # Processed Forex breaking news table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seen_news (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                link TEXT,
                published_at TEXT,
                impact TEXT DEFAULT '',
                description TEXT DEFAULT '',
                analyzed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Ensure impact and description columns exist in existing database tables
        try:
            cursor.execute("ALTER TABLE seen_news ADD COLUMN impact TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            cursor.execute("ALTER TABLE seen_news ADD COLUMN description TEXT DEFAULT ''")
        except Exception:
            pass
        
        conn.commit()

def add_message(user_id: int, role: str, content: str, model_used: Optional[str] = None):
    """Save a user or assistant message to database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO conversations (user_id, role, content, model_used)
            VALUES (?, ?, ?, ?)
        """, (user_id, role, content, model_used))
        conn.commit()

def get_recent_history(user_id: int, limit: int = 10) -> List[Dict[str, str]]:
    """Retrieve recent conversation history for context injection."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT role, content FROM (
                SELECT id, role, content FROM conversations
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
        """, (user_id, limit))
        rows = cursor.fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

def clear_history(user_id: int):
    """Clear conversation history for a specific user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.commit()

def add_reminder(user_id: int, task_text: str, remind_at_iso: str) -> int:
    """Save a scheduled reminder."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO reminders (user_id, task_text, remind_at, status)
            VALUES (?, ?, ?, 'pending')
        """, (user_id, task_text, remind_at_iso))
        conn.commit()
        return cursor.lastrowid

def get_due_reminders() -> List[Dict[str, Any]]:
    """Fetch reminders whose scheduled time has passed and are still pending."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, task_text, remind_at FROM reminders
            WHERE status = 'pending' AND remind_at <= ?
        """, (now_iso,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def mark_reminder_completed(reminder_id: int):
    """Mark a reminder as completed."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE reminders SET status = 'completed' WHERE id = ?
        """, (reminder_id,))
        conn.commit()

def get_user_reminders(user_id: int, status: str = 'pending') -> List[Dict[str, Any]]:
    """List pending reminders for a user."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, task_text, remind_at FROM reminders
            WHERE user_id = ? AND status = ?
            ORDER BY remind_at ASC
        """, (user_id, status))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]

def is_news_seen(news_id: str) -> bool:
    """Check if a news article has already been analyzed and dispatched."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM seen_news WHERE id = ?", (news_id,))
        return cursor.fetchone() is not None

def mark_news_as_seen(news_id: str, title: str, link: str = "", published_at: str = "", impact: str = "", description: str = ""):
    """Mark a news article as analyzed in the database with its impact rating and description."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO seen_news (id, title, link, published_at, impact, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (news_id, title, link, published_at, impact, description))
        conn.commit()

def get_recent_seen_news(limit: int = 50) -> List[Dict[str, Any]]:
    """Retrieve the most recent news articles recorded in the database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title, link, published_at, impact, description FROM seen_news
            ORDER BY rowid DESC LIMIT ?
        """, (limit,))
        return [dict(row) for row in cursor.fetchall()]

def get_user_preference(user_id: int, key: str, default: str = "") -> str:
    """Get a user preference value."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pref_value FROM preferences WHERE user_id = ? AND pref_key = ?", (user_id, key))
        row = cursor.fetchone()
        return row["pref_value"] if row else default

def set_user_preference(user_id: int, key: str, value: str):
    """Set or update a user preference."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO preferences (user_id, pref_key, pref_value)
            VALUES (?, ?, ?)
        """, (user_id, key, value))
        conn.commit()

# Initialize tables on import
init_db()
