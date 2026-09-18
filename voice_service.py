"""
Voice Transcription Service.

Provides multi-tier Speech-to-Text (STT) transcription for Telegram voice notes (.ogg/opus)
and audio files in Bengali and English:
1. Primary Tier: Groq Whisper-large-v3 (Ultra fast ~0.5s, highly accurate Bengali/English)
2. Secondary Tier: Google Gemini Audio Multimodal (gemini-3.8-flash, gemini-3.7-flash)
"""

import io
import logging
import os
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
