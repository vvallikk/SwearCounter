"""Распознавание речи."""

from .base import OnText, Recognizer
from .fake import FakeRecognizer

__all__ = ["OnText", "Recognizer", "FakeRecognizer"]
