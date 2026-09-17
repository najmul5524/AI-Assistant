import sys
import os
import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

print("=" * 50)
print("[*] Running AI Assistant Component Verification Tests")
print("=" * 50)

# Test 1: Config
print("\n[1] Checking Config & Env Loading...")
import config
print(f"  ✓ Bot Name: {config.BOT_NAME}")
print(f"  ✓ Timezone: {config.DEFAULT_TIMEZONE}")
print(f"  ✓ Gemini API Key present: {bool(config.GEMINI_API_KEY)}")
print(f"  ✓ Groq API Key present: {bool(config.GROQ_API_KEY)}")
print(f"  ✓ OpenRouter API Key present: {bool(config.OPENROUTER_API_KEY)}")

# Test 2: Database
print("\n[2] Testing SQLite Database...")
import database
database.init_db()
test_user = 999999999
database.clear_history(test_user)
database.add_message(test_user, "user", "Hello Assistant!")
database.add_message(test_user, "assistant", "Hello! How can I help you?", model_used="gemini-2.0-flash")

history = database.get_recent_history(test_user)
assert len(history) == 2, f"Expected 2 messages, found {len(history)}"
print(f"  ✓ Stored and retrieved {len(history)} messages successfully.")

# Test Reminder in Database
now_utc = datetime.datetime.now(datetime.timezone.utc)
remind_iso = (now_utc - datetime.timedelta(seconds=1)).isoformat() # simulate past reminder
rem_id = database.add_reminder(test_user, "Test reminder task", remind_iso)
due = database.get_due_reminders()
due_ids = [d["id"] for d in due]
assert rem_id in due_ids, "Reminder was not found in due list!"
database.mark_reminder_completed(rem_id)
print(f"  ✓ Reminder created and marked completed successfully.")
database.clear_history(test_user)

# Test 3: Tools & Web Search
print("\n[3] Testing Tools & Live Web Search (DuckDuckGo Free)...")
import tools
clock = tools.get_current_time()
print(f"  ✓ Current formatted clock: {clock}")

math_res = tools.calculate_expression("25 * 4 + 10")
print(f"  ✓ Math calculator: {math_res}")

try:
    search_res = tools.perform_web_search("Python programming language", max_results=2)
    print(f"  ✓ Web Search output preview:\n{search_res[:200]}...")
except Exception as e:
    print(f"  ⚠️ Search notice (network check): {e}")

# Test 4: Multi-Tier Failover Engine
print("\n[4] Testing MultiTierLLMManager...")
from llm_manager import MultiTierLLMManager
manager = MultiTierLLMManager()
status = manager.get_status()
print(f"  ✓ Tier status: {status}")

# Fallback test with no keys (or whatever is in env)
ans, provider, notice = manager.generate_response("What is 1 + 1?")
print(f"  ✓ Response received from: {provider}")
if notice:
    print(f"  ✓ Notice: {notice}")
print(f"  ✓ Content preview: {ans[:150]}...")

print("\n" + "=" * 50)
print("✅ Core engine test completed successfully!")
print("=" * 50)
