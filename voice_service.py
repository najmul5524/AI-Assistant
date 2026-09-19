"""
Voice Service.

Provides:
1. Speech-to-Text (STT) transcription for Telegram voice notes (.ogg/opus) and audio files:
   - Tier 1: Groq Whisper-large-v3 (Ultra fast ~0.5s, accurate Bengali & English)
   - Tier 2: Google Gemini Audio Multimodal (gemini-3.8-flash)
2. Text-to-Speech (TTS) natural neural voice reply generation:
   - Tier 1: Microsoft Edge Neural TTS (bn-BD-PradeepNeural / bn-BD-NabanitaNeural)
   - Tier 2: Google Translate TTS (gTTS) fallback
"""

import asyncio
import io
import logging
import os
import re
from typing import Optional, Tuple
from dotenv import load_dotenv

from config import GROQ_API_KEY, GEMINI_API_KEY, BASE_DIR

logger = logging.getLogger(__name__)

# Lazy clients
_groq_client = None
_gemini_client = None

def get_groq_client():
    global _groq_client
    if _groq_client is None and GROQ_API_KEY:
        try:
            from groq import Groq
            _groq_client = Groq(api_key=GROQ_API_KEY)
        except Exception as e:
            logger.error(f"Failed to initialize Groq client for STT: {e}")
    return _groq_client

def get_gemini_client():
    global _gemini_client
    if _gemini_client is None and GEMINI_API_KEY:
        try:
            from google import genai
            _gemini_client = genai.Client(api_key=GEMINI_API_KEY)
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client for STT: {e}")
    return _gemini_client

# ----------------- Speech to Text (STT) ----------------- #

def transcribe_with_groq(audio_bytes: bytes, filename: str = "voice.ogg") -> Optional[str]:
    """Transcribes audio using Groq Whisper-large-v3."""
    client = get_groq_client()
    if not client:
        return None
    try:
        bio = io.BytesIO(audio_bytes)
        bio.name = filename
        transcription = client.audio.transcriptions.create(
            file=(filename, bio),
            model="whisper-large-v3",
            response_format="text"
        )
        text = str(transcription).strip() if transcription else ""
        return text if text else None
    except Exception as e:
        logger.warning(f"Groq Whisper transcription failed: {e}")
        return None

def transcribe_with_gemini(audio_bytes: bytes, mime_type: str = "audio/ogg") -> Optional[str]:
    """Fallback audio transcription using Gemini multimodal models."""
    client = get_gemini_client()
    if not client:
        return None
    from google.genai import types
    part = types.Part.from_bytes(data=audio_bytes, mime_type=mime_type)
    prompt = (
        "You are an expert audio transcriber. Transcribe the spoken audio verbatim in its original spoken language "
        "(Bengali or English). Return ONLY the clean transcribed text without quotes, timestamps, or explanatory commentary."
    )
    for model_name in ["gemini-3.8-flash", "gemini-3.7-flash", "gemini-flash-latest"]:
        try:
            res = client.models.generate_content(
                model=model_name,
                contents=[part, prompt]
            )
            if res and res.text:
                clean = res.text.strip().strip('"').strip("'")
                if clean:
                    return clean
        except Exception as e:
            logger.warning(f"Gemini {model_name} audio transcription failed: {e}")
            continue
    return None

def transcribe_audio(audio_bytes: bytes, filename: str = "voice.ogg") -> Tuple[Optional[str], str]:
    """
    Main transcription entrypoint with multi-tier fallback.
    Returns: (transcribed_text, provider_name)
    """
    if not audio_bytes or len(audio_bytes) < 100:
        return None, "Empty Audio"

    # Tier 1: Groq Whisper Large v3
    if GROQ_API_KEY:
        text = transcribe_with_groq(audio_bytes, filename=filename)
        if text:
            logger.info(f"Audio successfully transcribed via Groq Whisper: '{text[:50]}...'")
            return text, "Groq Whisper-large-v3"

    # Tier 2: Gemini Audio Multimodal
    if GEMINI_API_KEY:
        text = transcribe_with_gemini(audio_bytes)
        if text:
            logger.info(f"Audio successfully transcribed via Gemini: '{text[:50]}...'")
            return text, "Gemini Audio Flash"

    return None, "All STT Providers Failed"

# ----------------- Text to Speech (TTS) ----------------- #

def clean_text_for_speech(text: str, max_chars: int = 450) -> str:
    """
    Strips markdown symbols, emojis, URLs, and code blocks for clean, natural speech narration.
    Caps length to prevent excessively long audio files.
    """
    if not text:
        return ""

    # Remove code blocks
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    cleaned = re.sub(r"`[^`]*`", "", cleaned)

    # Remove markdown links [text](url) -> text
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)

    # Remove URLs
    cleaned = re.sub(r"https?://\S+", "", cleaned)

    # Remove markdown headers and formatting (*, _, ~, #)
    cleaned = re.sub(r"[*_~#]+", "", cleaned)

    # Remove bullet markers
    cleaned = re.sub(r"^\s*[-•]\s*", "", cleaned, flags=re.MULTILINE)

    # Remove HTML tags
    cleaned = re.sub(r"<[^>]+>", "", cleaned)

    # Remove decorative emojis
    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"
        "\U0001F300-\U0001F5FF"
        "\U0001F680-\U0001F6FF"
        "\U0001F1E0-\U0001F1FF"
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001F900-\U0001F9FF"
        "\U0001FA70-\U0001FAFF"
        "]+",
        flags=re.UNICODE
    )
    cleaned = emoji_pattern.sub("", cleaned)

    # Normalize whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Cap length to roughly 30 seconds of speech
    if len(cleaned) > max_chars:
        cut = cleaned[:max_chars]
        last_punct = max(cut.rfind("।"), cut.rfind("."), cut.rfind("?"), cut.rfind("!"))
        if last_punct > 120:
            cleaned = cut[:last_punct + 1] + " বিস্তারিত তথ্য উপরে টেক্সট আকারে দেওয়া হয়েছে।"
        else:
            cleaned = cut + "... বিস্তারিত উপরে টেক্সটে দেখুন।"

    return cleaned

def text_to_speech_gtts(text: str, lang: str = "bn") -> Optional[bytes]:
    """Fallback TTS using Google Translate TTS."""
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang=lang)
        bio = io.BytesIO()
        tts.write_to_fp(bio)
        return bio.getvalue()
    except Exception as e:
        logger.warning(f"gTTS generation failed: {e}")
        return None

async def text_to_speech_async(text: str, voice: str = "bn-BD-PradeepNeural") -> Tuple[Optional[bytes], str]:
    """
    Asynchronous Text-to-Speech synthesis with Edge Neural TTS and gTTS fallback.
    Returns: (audio_bytes, provider_description)
    """
    cleaned = clean_text_for_speech(text)
    if not cleaned or len(cleaned.strip()) < 2:
        return None, "Empty text"

    # Tier 1: Microsoft Edge Neural TTS
    try:
        import edge_tts
        communicate = edge_tts.Communicate(cleaned, voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        audio_data = b"".join(chunks)
        if audio_data and len(audio_data) > 1000:
            return audio_data, f"Edge Neural ({voice.split('-')[-1]})"
    except Exception as e:
        logger.warning(f"Edge-TTS failed: {e}, attempting gTTS fallback...")

    # Tier 2: gTTS fallback
    try:
        # Detect if text is mostly English or Bengali
        has_bengali = any("\u0980" <= c <= "\u09FF" for c in cleaned)
        lang = "bn" if has_bengali else "en"
        audio_data = text_to_speech_gtts(cleaned, lang=lang)
        if audio_data and len(audio_data) > 1000:
            return audio_data, "Google TTS"
    except Exception as e:
        logger.error(f"All TTS engines failed: {e}")

    return None, "All TTS Engines Failed"

def text_to_speech_sync(text: str, voice: str = "bn-BD-PradeepNeural") -> Tuple[Optional[bytes], str]:
    """Synchronous wrapper for text_to_speech_async."""
    try:
        return asyncio.run(text_to_speech_async(text, voice))
    except RuntimeError:
        # Loop already running
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(text_to_speech_async(text, voice))
