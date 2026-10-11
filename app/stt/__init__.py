"""Распознавание речи."""

from .base import OnText, Recognizer
from .catalog import CATALOG, ModelInfo, find_model, installed_models
from .downloader import ModelDownloader, remove_model
from .recognizer import MicRecognizer

__all__ = [
    "CATALOG",
    "ModelDownloader",
    "ModelInfo",
    "OnText",
    "Recognizer",
    "MicRecognizer",
    "find_model",
    "installed_models",
    "remove_model",
]
