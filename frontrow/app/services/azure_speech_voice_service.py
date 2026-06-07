from __future__ import annotations

import html
from collections.abc import AsyncIterator

import httpx


class AzureSpeechVoiceError(RuntimeError):
    pass


class AzureSpeechVoiceService:
    """Azure Speech TTS adapter that streams raw PCM chunks to the frontend."""

    sample_rate = 24000
    mime_type = "audio/pcm;rate=24000"

    def __init__(
        self,
        *,
        speech_key: str,
        region: str,
        voice_name: str,
        output_format: str = "raw-24khz-16bit-mono-pcm",
    ) -> None:
        self.speech_key = speech_key
        self.region = region
        self.voice_name = voice_name
        self.output_format = output_format
        self._client = httpx.AsyncClient(timeout=30.0)

    async def stream_text(self, text: str) -> AsyncIterator[bytes]:
        if not self.speech_key:
            raise AzureSpeechVoiceError("AZURE_SPEECH_KEY is required for Azure Speech TTS.")
        if not self.region:
            raise AzureSpeechVoiceError("AZURE_SPEECH_REGION is required for Azure Speech TTS.")

        endpoint = f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self.speech_key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": self.output_format,
            "User-Agent": "frontrow-interview-poc",
        }
        ssml = _ssml(text=text, voice_name=self.voice_name)

        try:
            async with self._client.stream("POST", endpoint, headers=headers, content=ssml) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="ignore")
                    raise AzureSpeechVoiceError(
                        f"Azure Speech TTS failed with {response.status_code}: {detail}"
                    )
                async for chunk in response.aiter_bytes(chunk_size=4096):
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise AzureSpeechVoiceError(str(exc)) from exc

    async def close(self) -> None:
        await self._client.aclose()


def _ssml(*, text: str, voice_name: str) -> str:
    escaped_text = html.escape(text, quote=False)
    escaped_voice = html.escape(voice_name, quote=True)
    return f"""
<speak version="1.0" xml:lang="en-US">
  <voice xml:lang="en-US" name="{escaped_voice}">
    {escaped_text}
  </voice>
</speak>
""".strip()
