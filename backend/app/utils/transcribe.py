"""Voice notes to text, via Deepgram's pre-recorded endpoint.

One POST with the audio as the body — no SDK needed, httpx is already a dependency.
The API key stays server-side, which is why the browser uploads the clip here rather
than talking to Deepgram directly.
"""

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
    """Return what was said in `audio`, or "" when Deepgram heard nothing.

    Raises TranscriptionError so the caller can tell the user the recording failed
    rather than feeding an empty answer into the graph.
    """
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

if __name__ == "__main__":
    import asyncio
    from functools import partial

    def run(handler, audio=b"fake-audio", mimetype="audio/webm;codecs=opus"):
        """transcribe() against a fake Deepgram — no network, no key."""
        real = httpx.AsyncClient
        httpx.AsyncClient = partial(real, transport=httpx.MockTransport(handler))
        try:
            return asyncio.run(transcribe(audio, mimetype))
        finally:
            httpx.AsyncClient = real

    def raises(handler, **kw):
        try:
            run(handler, **kw)
        except TranscriptionError:
            return True
        return False

    settings.DEEPGRAM_API_KEY = "test-key"

    def ok(request):
                                                                                   
        assert request.headers["content-type"] == "audio/webm", request.headers["content-type"]
        assert request.headers["authorization"] == "Token test-key"
        assert request.read() == b"fake-audio"
        return httpx.Response(200, json={
            "results": {"channels": [{"alternatives": [{"transcript": "  I led a team of four.  "}]}]}
        })

    assert run(ok) == "I led a team of four."

    silence = {"results": {"channels": [{"alternatives": []}]}}
    assert run(lambda r: httpx.Response(200, json=silence)) == "", "silence is empty, not an error"

    assert raises(lambda r: httpx.Response(401, text="denied")), "auth failure must raise"
    assert raises(lambda r: httpx.Response(200, json={"results": {}})), "bad shape must raise"
    assert raises(ok, audio=b""), "empty recording must raise"

    settings.DEEPGRAM_API_KEY = None
    assert raises(ok), "missing key must raise, not silently return empty"

    print("transcribe ok")