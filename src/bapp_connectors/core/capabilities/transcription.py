"""Transcription capability — optional interface for audio-to-text conversion."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bapp_connectors.core.dto import TranscriptionResult


class TranscriptionCapability(ABC):
    """Adapter supports transcribing audio to text (Whisper, etc.)."""

    @abstractmethod
    def transcribe(
        self,
        audio: bytes,
        model: str | None = None,
        language: str | None = None,
        **kwargs,
    ) -> TranscriptionResult:
        """
        Transcribe audio to text.

        Args:
            audio: Audio file bytes (mp3, mp4, mpeg, mpga, m4a, wav, webm).
            model: Model to use (e.g. "whisper-1"). If None, uses provider default.
            language: ISO 639-1 language code (e.g. "en", "ro"). If None, auto-detected.
            **kwargs: Provider-specific params (prompt, temperature, response_format, etc.).
        """
        ...
