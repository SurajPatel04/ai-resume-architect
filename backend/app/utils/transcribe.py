"""Voice notes to text, via Deepgram's pre-recorded endpoint."""

import logging

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

DEEPGRAM_URL = "https://api.deepgram.com/v1/listen"

PARAMS = {"model": "nova-3", "smart_format": "true", "punctuate": "true"}

TIMEOUT = httpx.Timeout(60.0)

class TranscriptionError(RuntimeError):
    """Deepgram was unreachable, unconfigured, or rejected the audio."""

async def transcribe(audio: bytes, mimetype: str) -> str:
    """Return what was said in `audio`, or "" when Deepgram heard nothing."""
    if not settings.DEEPGRAM_API_KEY:
        raise TranscriptionError("DEEPGRAM_API_KEY is not set")

    if not audio:
        raise TranscriptionError("Empty recording")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            response = await client.post(
                DEEPGRAM_URL,
                params=PARAMS,
                headers={
                    "Authorization": f"Token {settings.DEEPGRAM_API_KEY}",

                    "Content-Type": mimetype.split(";")[0] or "audio/webm",
                },
                content=audio,
            )
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPStatusError as e:
        body = e.response.text[:200]
        logger.error("Deepgram rejected the audio (%s): %s", e.response.status_code, body)
        raise TranscriptionError(f"Deepgram returned {e.response.status_code}") from e
    except httpx.HTTPError as e:
        logger.error("Deepgram request failed: %r", e)
        raise TranscriptionError("Could not reach Deepgram") from e

    try:
        alternatives = payload["results"]["channels"][0]["alternatives"]
    except (KeyError, IndexError, TypeError) as e:
        logger.error("Unexpected Deepgram response shape: %s", str(payload)[:200])
        raise TranscriptionError("Unexpected Deepgram response") from e

    return alternatives[0]["transcript"].strip() if alternatives else ""
