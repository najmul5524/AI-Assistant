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

# Initialize tables on import
init_db()
