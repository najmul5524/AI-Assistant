import logging
from typing import List, Dict, Any, Tuple, Optional
from config import (
    GEMINI_API_KEY,
    GITHUB_TOKEN,
    OPENROUTER_API_KEY,
    GROQ_API_KEY,
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    GEMINI_MODELS,
    GITHUB_MODELS,
    OPENROUTER_MODELS,
    GROQ_MODELS,
    CLOUDFLARE_MODELS,
    SYSTEM_PROMPT
)

logger = logging.getLogger(__name__)

class MultiTierLLMManager:
    """
    Intelligent multi-tier fallback router.
    Attempts primary tier (Gemini), and seamlessly fails over to
    secondary (Groq) and tertiary (OpenRouter) on rate limits, errors, or quota exhaustion.
    """

    def __init__(self):
        self._init_clients()

    def _init_clients(self):
        # Gemini Client
        self.gemini_client = None
        if GEMINI_API_KEY:
            try:
                # Try google-genai (v1.0+) first
                from google import genai
                self.gemini_client = genai.Client(api_key=GEMINI_API_KEY)
                self.gemini_version = "google-genai"
            except ImportError:
                try:
                    import google.generativeai as legacy_genai
                    legacy_genai.configure(api_key=GEMINI_API_KEY)
                    self.gemini_client = legacy_genai
                    self.gemini_version = "legacy"
                except Exception as e:
                    logger.warning(f"Could not initialize Gemini: {e}")

        # Groq Client
        self.groq_client = None
        if GROQ_API_KEY:
            try:
                from groq import Groq
                self.groq_client = Groq(api_key=GROQ_API_KEY)
            except Exception as e:
                logger.warning(f"Could not initialize Groq: {e}")

        # GitHub Models Client (100% free with any GitHub token)
        self.github_client = None
        if GITHUB_TOKEN:
            try:
                from openai import OpenAI
                self.github_client = OpenAI(
                    base_url="https://models.inference.ai.azure.com",
                    api_key=GITHUB_TOKEN,
                )
            except Exception as e:
                logger.warning(f"Could not initialize GitHub Models: {e}")

        # OpenRouter Client (OpenAI-compatible)
        self.openrouter_client = None
        if OPENROUTER_API_KEY:
            try:
                from openai import OpenAI
                self.openrouter_client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=OPENROUTER_API_KEY,
                )
            except Exception as e:
                logger.warning(f"Could not initialize OpenRouter: {e}")

    def get_status(self) -> Dict[str, Any]:
        """Returns the status and health of all configured AI tiers."""
        return {
            "gemini": {
                "configured": bool(GEMINI_API_KEY and self.gemini_client),
                "primary_model": GEMINI_MODELS[0] if GEMINI_MODELS else None,
                "tier": "Tier 1 (Default Primary)"
            },
            "cloudflare": {
                "configured": bool(CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN),
                "primary_model": CLOUDFLARE_MODELS[0] if CLOUDFLARE_MODELS else None,
                "tier": "Tier 2 (Cloudflare Workers AI Free)"
            },
            "github": {
                "configured": bool(GITHUB_TOKEN and self.github_client),
                "primary_model": GITHUB_MODELS[0] if GITHUB_MODELS else None,
                "tier": "Tier 3 (GitHub Models Free)"
            },
            "openrouter": {
                "configured": bool(OPENROUTER_API_KEY and self.openrouter_client),
                "primary_model": OPENROUTER_MODELS[0] if OPENROUTER_MODELS else None,
                "tier": "Tier 4 (Free Multi-model Fallback)"
            },
            "groq": {
                "configured": bool(GROQ_API_KEY and self.groq_client),
                "primary_model": GROQ_MODELS[0] if GROQ_MODELS else None,
                "tier": "Tier 5 (Groq Cloud)"
            }
        }

    def _call_gemini(self, history: List[Dict[str, str]], prompt: str) -> str:
        """Execute request using Google Gemini with automatic model fallback."""
        if not self.gemini_client:
            raise ValueError("Gemini is not configured or API key is missing.")

        last_err = None
        for model_name in GEMINI_MODELS:
            try:
                if getattr(self, "gemini_version", "") == "google-genai":
                    contents = []
                    for item in history:
                        role = "user" if item["role"] == "user" else "model"
                        contents.append(f"{role.capitalize()}: {item['content']}")
                    contents.append(f"User: {prompt}")
                    full_content = "\n\n".join(contents)

                    response = self.gemini_client.models.generate_content(
                        model=model_name,
                        contents=full_content,
                        config={
                            "system_instruction": SYSTEM_PROMPT
                        }
                    )
                    return response.text
                else:
                    model = self.gemini_client.GenerativeModel(
                        model_name=model_name,
                        system_instruction=SYSTEM_PROMPT
                    )
                    chat = model.start_chat(history=[])
                    response = chat.send_message(prompt)
                    return response.text
            except Exception as e:
                last_err = e
                err_str = str(e)
                if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "Quota exceeded" in err_str:
                    logger.warning(f"Gemini quota reached for current key. Instantly switching to next AI tier...")
                    break
                logger.warning(f"Gemini model {model_name} failed: {e}. Trying next fallback model...")

        if last_err:
            raise last_err
        raise ValueError("No Gemini models succeeded.")

    def _call_groq(self, history: List[Dict[str, str]], prompt: str) -> str:
        """Execute request using Groq Cloud with multi-model fallback."""
        if not self.groq_client:
            raise ValueError("Groq is not configured or API key is missing.")

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history:
            messages.append({"role": item["role"], "content": item["content"]})
        messages.append({"role": "user", "content": prompt})

        last_err = None
        for model_name in GROQ_MODELS:
            try:
                response = self.groq_client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=2048,
                )
                return response.choices[0].message.content
            except Exception as e:
                last_err = e
                logger.warning(f"Groq model {model_name} failed: {e}. Trying next Groq model...")

        if last_err:
            raise last_err
        raise ValueError("No Groq models succeeded.")

    def _call_openrouter(self, history: List[Dict[str, str]], prompt: str) -> str:
        """Execute request using OpenRouter."""
        if not self.openrouter_client:
            raise ValueError("OpenRouter is not configured or API key is missing.")

        model_name = OPENROUTER_MODELS[0]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history:
            messages.append({"role": item["role"], "content": item["content"]})
        messages.append({"role": "user", "content": prompt})

        response = self.openrouter_client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.7,
        )
        return response.choices[0].message.content

    def _call_github(self, history: List[Dict[str, str]], prompt: str) -> str:
        """Execute request using GitHub Models (100% free with GitHub Personal Access Token)."""
        if not self.github_client:
            raise ValueError("GitHub Models is not configured or token is missing.")

        model_name = GITHUB_MODELS[0]
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history:
            messages.append({"role": item["role"], "content": item["content"]})
        messages.append({"role": "user", "content": prompt})

        response = self.github_client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=0.7,
        )
        return response.choices[0].message.content

    def _call_cloudflare(self, history: List[Dict[str, str]], prompt: str) -> str:
        """Execute request using Cloudflare Workers AI (10,000 neurons/day free)."""
        if not (CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN):
            raise ValueError("Cloudflare Account ID or API Token is missing.")

        import requests
        model_name = CLOUDFLARE_MODELS[0]
        url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{model_name}"
        headers = {
            "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
            "Content-Type": "application/json"
        }
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for item in history:
            messages.append({"role": item["role"], "content": item["content"]})
        messages.append({"role": "user", "content": prompt})

        res = requests.post(url, headers=headers, json={"messages": messages}, timeout=30)
        res.raise_for_status()
        data = res.json()
        if "result" in data and "response" in data["result"]:
            return data["result"]["response"]
        elif "result" in data and "choices" in data["result"]:
            return data["result"]["choices"][0]["message"]["content"]
        raise ValueError(f"Unexpected Cloudflare response: {data}")

    def generate_response(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        context_data: Optional[str] = None
    ) -> Tuple[str, str, Optional[str]]:
        """
        Generate answer with automatic multi-tier fallback.
        Returns: (reply_text, provider_used, switch_notice)
        """
        history = history or []
        augmented_prompt = prompt
        if context_data:
            augmented_prompt = f"Additional Real-Time Context:\n{context_data}\n\nUser Question/Command:\n{prompt}"

        # Define tier progression only for providers that have an API key configured
        available_tiers = []
        if self.gemini_client and GEMINI_API_KEY:
            available_tiers.append(("Gemini", GEMINI_MODELS[0] if GEMINI_MODELS else "gemini-3.8-flash", self._call_gemini))
        if CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN:
            available_tiers.append(("Cloudflare AI", CLOUDFLARE_MODELS[0] if CLOUDFLARE_MODELS else "@cf/meta/llama-3.3-70b-instruct-fp8-fast", self._call_cloudflare))
        if self.github_client and GITHUB_TOKEN:
            available_tiers.append(("GitHub Models", GITHUB_MODELS[0] if GITHUB_MODELS else "Meta-Llama-3.3-70B-Instruct", self._call_github))
        if self.openrouter_client and OPENROUTER_API_KEY:
            available_tiers.append(("OpenRouter", OPENROUTER_MODELS[0] if OPENROUTER_MODELS else "deepseek/deepseek-r1:free", self._call_openrouter))
        if self.groq_client and GROQ_API_KEY:
            available_tiers.append(("Groq", GROQ_MODELS[0] if GROQ_MODELS else "llama-3.3-70b-versatile", self._call_groq))

        if not available_tiers:
            return (
                "⚠️ কোনো AI Provider-এর API Key কনফিগার করা নেই!\n\n"
                "অনুগ্রহ করে `.env` ফাইলে অন্তত একটি API Key (যেমন: `GEMINI_API_KEY` বা `GROQ_API_KEY`) যোগ করুন।",
                "None",
                None
            )

        attempted_failures = []

        for name, model_id, func in available_tiers:
            try:
                logger.info(f"Trying LLM Tier: {name} ({model_id})...")
                answer = func(history, augmented_prompt)
                if answer and answer.strip():
                    switch_notice = None
                    if attempted_failures:
                        switch_notice = f"⚡ *[Auto-Switched to {name} ({model_id}) because {', '.join(attempted_failures)} hit limit or error]*"
                    return answer.strip(), f"{name} ({model_id})", switch_notice
            except Exception as e:
                err_msg = str(e)
                logger.warning(f"Tier {name} failed: {err_msg}")
                attempted_failures.append(name)
                # Continue to next available tier

        # If all configured tiers failed
        if len(attempted_failures) == 1:
            failed_tier = attempted_failures[0]
            unconfigured = []
            if not GROQ_API_KEY:
                unconfigured.append("Groq Cloud (GROQ_API_KEY)")
            if not (CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN):
                unconfigured.append("Cloudflare Workers AI")
            if not GITHUB_TOKEN:
                unconfigured.append("GitHub Models")

            tips = ""
            if unconfigured:
                tips = f"\n\n💡 *টিপ:* নিরবচ্ছিন্ন ব্যাকআপ সার্ভিসের জন্য Render Environment-এ {unconfigured[0]}-এর ফ্রি কী যোগ করুন।"

            error_response = (
                f"⚠️ {failed_tier} থেকে উত্তর পাওয়া যায়নি (কোটা শেষ বা সাময়িক সংযোগ সমস্যা)।"
                f"{tips}"
            )
        else:
            error_response = (
                f"⚠️ কনফিগার করা সকল AI প্রোভাইডারের ফ্রি লিমিট এই মুহূর্তে সাময়িকভাবে শেষ।\n\n"
                f"🔍 চেষ্টা করা প্রোভাইডারসমূহ: {', '.join(attempted_failures)}\n\n"
                "কিছুক্ষণ পর ফ্রি লিমিট রিসেট হলে অথবা লোড কমলে স্বয়ংক্রিয়ভাবে স্বাভাবিক রেসপন্স পাবেন।"
            )

        return error_response, "None", None
