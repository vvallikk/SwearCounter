"""Распознавание речи."""

from .base import OnText, Recognizer
from .vosk_recognizer import VoskRecognizer

__all__ = ["OnText", "Recognizer", "VoskRecognizer"]
