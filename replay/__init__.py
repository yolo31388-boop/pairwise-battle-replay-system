"""战斗回放与观战系统。"""
from .system import (
    BattleEvent,
    RecordingError,
    ReplaySystem,
    EVENT_TYPES,
    PLAYBACK_SPEEDS,
    WATCH_DELAY_OPTIONS,
    MARKER_EVENT_TYPES,
    FRAME_INTERVAL,
    FREE_VIEW,
)

__all__ = [
    "BattleEvent",
    "RecordingError",
    "ReplaySystem",
    "EVENT_TYPES",
    "PLAYBACK_SPEEDS",
    "WATCH_DELAY_OPTIONS",
    "MARKER_EVENT_TYPES",
    "FRAME_INTERVAL",
    "FREE_VIEW",
]
