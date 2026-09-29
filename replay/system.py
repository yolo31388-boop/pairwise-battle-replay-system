"""战斗回放与观战系统核心。

修复的九个录制事故：
1. 录制完整战斗事件流（技能/移动/伤害/状态变化），按时间戳序列化
2. 支持 0.5x/1x/2x/4x 倍速和逐帧播放
3. 观战延迟可配置（实时/10秒/30秒），带延迟保护防作弊
4. 标记支持时间点 + 事件类型（击杀/推塔/团战），可筛选
5. 增量压缩存储（只存状态变化），控制体积
6. 回放可切换任意玩家视角和自由视角
7. 观战人数上限 + 排队机制，超上限给出提示
8. 分享自动生成精彩片段（自动识别击杀/团战）
9. 录制数据带校验和，回放校验不一致时报错提示而非崩溃
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass

EVENT_TYPES = ("skill", "move", "damage", "state")
PLAYBACK_SPEEDS = (0.5, 1.0, 2.0, 4.0)
WATCH_DELAY_OPTIONS = (0, 10, 30)  # 实时 / 10秒 / 30秒
MARKER_EVENT_TYPES = ("kill", "tower", "teamfight")
DEFAULT_VIEWER_LIMIT = 2000
FRAME_INTERVAL = 1.0 / 30.0
FREE_VIEW = "free"
HIGHLIGHT_WINDOW = 5.0
TEAMFIGHT_KILL_COUNT = 3
TEAMFIGHT_WINDOW = 10.0


class RecordingError(Exception):
    """录制数据校验失败，用于回放时报错提示而非崩溃。"""


@dataclass
class BattleEvent:
    timestamp: float
    event_type: str
    data: dict


def _serialize_events(events):
    return json.dumps(
        [
            {"timestamp": e.timestamp, "event_type": e.event_type, "data": e.data}
            for e in events
        ],
        sort_keys=True,
        ensure_ascii=False,
    )


class ReplaySystem:
    def __init__(self, viewer_limit=DEFAULT_VIEWER_LIMIT, watch_delay=30):
        if viewer_limit <= 0:
            raise ValueError("观战人数上限必须为正数")
        self.recordings = {}  # battle_id -> list[BattleEvent]，按时间戳升序
        self.markers = {}  # battle_id -> list[dict]
        self.views = {}  # battle_id -> 玩家ID 或 "free"
        self.spectators = {}  # battle_id -> list[viewer_id]
        self.queues = {}  # battle_id -> list[viewer_id]
        self.viewer_limit = viewer_limit
        self._watch_delay = 30
        self.set_watch_delay(watch_delay)
        self._checksums = {}  # battle_id -> sha256
        self._playback_frames = {}  # battle_id -> 当前帧序号

    # ---- 1. 完整事件流录制 ----

    def record_event(self, battle_id, event_type, data, timestamp=None):
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"未知事件类型 {event_type!r}，支持: {', '.join(EVENT_TYPES)}"
            )
        event = BattleEvent(
            time.time() if timestamp is None else float(timestamp),
            event_type,
            dict(data),
        )
        events = self.recordings.setdefault(battle_id, [])
        events.append(event)
        events.sort(key=lambda e: e.timestamp)
        self._checksums[battle_id] = self._checksum(events)
        return event

    # ---- 2. 倍速与逐帧播放 ----

    def get_playback_speeds(self):
        return list(PLAYBACK_SPEEDS)

    def step_frame(self, battle_id):
        """逐帧播放：每次调用前进一帧，返回该帧内的事件。"""
        events = self.get_playback_events(battle_id)
        frame = self._playback_frames.get(battle_id, 0)
        self._playback_frames[battle_id] = frame + 1
        if not events:
            return []
        base = events[0].timestamp
        start = base + frame * FRAME_INTERVAL
        end = start + FRAME_INTERVAL
        return [e for e in events if start <= e.timestamp < end]

    # ---- 3. 可配置观战延迟 + 延迟保护 ----

    def set_watch_delay(self, delay):
        if delay not in WATCH_DELAY_OPTIONS:
            raise ValueError(
                f"观战延迟只支持 {WATCH_DELAY_OPTIONS} 秒（实时/10秒/30秒）"
            )
        self._watch_delay = delay

    def get_watch_delay(self):
        return self._watch_delay

    def get_spectator_view(self, battle_id, now=None):
        """延迟保护：观战者只能看到 delay 秒之前发生的事件，防止窥屏作弊。"""
        now = time.time() if now is None else now
        cutoff = now - self._watch_delay
        return [
            e for e in self.recordings.get(battle_id, []) if e.timestamp <= cutoff
        ]

    # ---- 4. 时间点 + 事件类型标记 ----

    def add_marker(self, battle_id, timestamp, event_type=None, note=""):
        if event_type is not None and event_type not in MARKER_EVENT_TYPES:
            raise ValueError(
                f"未知标记事件类型 {event_type!r}，支持: {', '.join(MARKER_EVENT_TYPES)}"
            )
        marker = {"timestamp": timestamp, "event_type": event_type, "note": note}
        self.markers.setdefault(battle_id, []).append(marker)
        return marker

    def get_markers(self, battle_id, event_type=None):
        markers = self.markers.get(battle_id, [])
        if event_type is None:
            return list(markers)
        return [m for m in markers if m["event_type"] == event_type]

    # ---- 5. 增量压缩存储 ----

    def compress_recording(self, battle_id):
        """增量压缩：state 事件只存相对上一状态变化的键。"""
        state = {}
        deltas = []
        for e in self.recordings.get(battle_id, []):
            if e.event_type == "state":
                changed = {k: v for k, v in e.data.items() if state.get(k) != v}
                state.update(changed)
                deltas.append(
                    {"timestamp": e.timestamp, "event_type": "state", "delta": changed}
                )
            else:
                deltas.append(
                    {"timestamp": e.timestamp, "event_type": e.event_type, "data": e.data}
                )
        payload = {"battle_id": battle_id, "format": "delta-v1", "events": deltas}
        return json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")

    def decompress_recording(self, payload):
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        raw = json.loads(payload)
        state = {}
        events = []
        for item in raw["events"]:
            if item["event_type"] == "state":
                state.update(item["delta"])
                data = dict(state)
            else:
                data = item["data"]
            events.append(BattleEvent(item["timestamp"], item["event_type"], data))
        return events

    def get_storage_size(self, battle_id):
        return len(self.compress_recording(battle_id))

    def get_full_storage_size(self, battle_id):
        """未压缩的全量体积（同一存储格式，state 事件存全量状态），用于对比。"""
        payload = {
            "battle_id": battle_id,
            "format": "full-v1",
            "events": [
                {"timestamp": e.timestamp, "event_type": e.event_type, "data": e.data}
                for e in self.recordings.get(battle_id, [])
            ],
        }
        return len(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )

    # ---- 6. 任意玩家视角 / 自由视角 ----

    def set_view(self, battle_id, view):
        self.views[battle_id] = view

    def get_view(self, battle_id):
        return self.views.get(battle_id, FREE_VIEW)

    # ---- 7. 观战人数上限 + 排队 ----

    def get_viewer_limit(self):
        return self.viewer_limit

    def get_viewer_count(self, battle_id):
        return len(self.spectators.get(battle_id, []))

    def join_spectate(self, battle_id, viewer_id):
        active = self.spectators.setdefault(battle_id, [])
        queue = self.queues.setdefault(battle_id, [])
        if viewer_id in active:
            return {"status": "watching", "position": 0}
        if viewer_id in queue:
            return {
                "status": "queued",
                "position": queue.index(viewer_id) + 1,
                "message": "观战人数已达上限，正在排队",
            }
        if len(active) < self.viewer_limit:
            active.append(viewer_id)
            return {"status": "watching", "position": 0}
        queue.append(viewer_id)
        return {
            "status": "queued",
            "position": len(queue),
            "message": "观战人数已达上限，已加入排队",
        }

    def leave_spectate(self, battle_id, viewer_id):
        active = self.spectators.get(battle_id, [])
        queue = self.queues.get(battle_id, [])
        if viewer_id in active:
            active.remove(viewer_id)
            if queue:
                active.append(queue.pop(0))
        elif viewer_id in queue:
            queue.remove(viewer_id)

    # ---- 8. 分享 + 精彩片段 ----

    def share(self, battle_id):
        return {
            "url": f"https://replay.example.com/{battle_id}",
            "highlights": self.generate_highlights(battle_id),
        }

    def generate_highlights(self, battle_id):
        """自动识别击杀与团战，生成精彩片段。"""
        kills = sorted(
            e.timestamp
            for e in self.recordings.get(battle_id, [])
            if e.event_type == "damage" and e.data.get("kill")
        )
        highlights = [self._make_clip(battle_id, t, "kill") for t in kills]
        cluster = []
        for t in kills:
            if cluster and t - cluster[-1] > TEAMFIGHT_WINDOW:
                cluster = []
            cluster.append(t)
            if len(cluster) == TEAMFIGHT_KILL_COUNT:
                highlights.append(self._make_clip(battle_id, t, "teamfight"))
        highlights.sort(key=lambda h: h["start"])
        return highlights

    @staticmethod
    def _make_clip(battle_id, center, kind):
        return {
            "battle_id": battle_id,
            "type": kind,
            "start": max(0.0, center - HIGHLIGHT_WINDOW),
            "end": center + HIGHLIGHT_WINDOW,
            "url": f"https://replay.example.com/{battle_id}/clip/{kind}/{int(center)}",
        }

    # ---- 9. 校验和 ----

    @staticmethod
    def _checksum(events):
        return hashlib.sha256(_serialize_events(events).encode("utf-8")).hexdigest()

    def validate_recording(self, battle_id):
        """校验录制数据完整性，不一致返回 False 而不是抛异常崩溃。"""
        events = self.recordings.get(battle_id)
        if events is None:
            return False
        expected = self._checksums.get(battle_id)
        if expected is None:
            return False
        return self._checksum(events) == expected

    def get_playback_events(self, battle_id):
        """回放入口：先校验，不一致则抛出 RecordingError 报错提示。"""
        if not self.validate_recording(battle_id):
            raise RecordingError(
                f"战斗 {battle_id} 的录制数据校验不一致，已中止回放"
            )
        return list(self.recordings[battle_id])
