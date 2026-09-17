import os
import sys
import threading
import subprocess
import gradio as gr

def run_telegram_bot():
    """Runs the Telegram bot continuously in the background."""
    print("🚀 Starting Telegram Bot process in background...")
    try:
        subprocess.run([sys.executable, "bot.py"])
    except Exception as e:
        print(f"Bot process crashed: {e}")

# Launch the Telegram bot background thread immediately
bot_thread = threading.Thread(target=run_telegram_bot, daemon=True)
bot_thread.start()

def get_server_status():
    """Returns dynamic health status for the web dashboard."""
    try:
        from config import BOT_NAME, DEFAULT_TIMEZONE
        import tools
        clock = tools.get_current_time()
        bot_display = BOT_NAME
    except Exception:
        bot_display = "Goodushh"
        clock = "Available"
        DEFAULT_TIMEZONE = "Asia/Dhaka"

    return (
        f"### 🟢 {bot_display} 24/7 AI Cloud Server is Online!\n\n"
        f"• **Current Server Time:** {clock}\n"
        f"• **Timezone:** `{DEFAULT_TIMEZONE}`\n"
        f"• **Status:** Telegram Polling & Multi-Tier AI Active 24/7\n\n"
        f"👉 *আপনার টেলিগ্রাম অ্যাপ থেকে বটকে সরাসরি যেকোনো মেসেজ বা কমান্ড পাঠান।*"
    )

# Clean Gradio Web Dashboard for Hugging Face
with gr.Blocks(title="Goodushh 24/7 AI Assistant Server") as demo:
    gr.Markdown("# 🤖 Goodushh 24/7 Personal AI Assistant")
    gr.Markdown("This Cloud Space keeps your Telegram Assistant running 24/7 even when your PC is turned off.")
    
    status_display = gr.Markdown(value=get_server_status())
    refresh_button = gr.Button("🔄 Refresh Server Status")
    refresh_button.click(fn=get_server_status, outputs=status_display)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "7860"))
    demo.launch(server_name="0.0.0.0", server_port=port)
