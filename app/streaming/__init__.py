"""Интеграции со стримами: Twitch и YouTube (см. docs/STREAMING.md)."""

from .api import make_router
from .manager import Streaming

__all__ = ["Streaming", "make_router"]
