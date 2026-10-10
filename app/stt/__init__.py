"""Распознавание речи."""

from .base import OnText, Recognizer
from .catalog import CATALOG, ModelInfo, find_model, installed_models
from .downloader import ModelDownloader
from .vosk_recognizer import VoskRecognizer

__all__ = [
    "CATALOG",
    "ModelDownloader",
    "ModelInfo",
    "OnText",
    "Recognizer",
    "VoskRecognizer",
    "find_model",
    "installed_models",
]
