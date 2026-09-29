"""战斗回放观战系统"""
from dataclasses import dataclass, field
import hashlib
import json
import time
import zlib

EVENT_TYPES = ("skill", "move", "damage", "state")
MARKER_EVENT_TYPES = ("kill", "tower", "teamfight")
PLAYBACK_SPEEDS = [0.5, 1.0, 2.0, 4.0]
WATCH_DELAYS = {"realtime": 0, "normal": 10, "safe": 30}
MIN_REALTIME_DELAY = 1  # 实时模式下的最小延迟(秒), 防止窥屏作弊
DEFAULT_VIEWER_LIMIT = 1000


class ReplayDataError(Exception):
    """回放数据校验不一致"""


@dataclass
class BattleEvent:
    timestamp: float
    event_type: str
    data: dict


@dataclass
class Marker:
    timestamp: float
    event_type: str = "time"  # time / kill / tower / teamfight
    note: str = ""


class ReplaySystem:
    def __init__(self, viewer_limit=DEFAULT_VIEWER_LIMIT, watch_delay="safe"):
        self.recordings = {}          # battle_id -> [BattleEvent] 完整事件流
        self._checksums = {}          # battle_id -> 校验和
        self._deltas = {}             # battle_id -> [增量状态变化]
        self._states = {}             # battle_id -> 最近一次状态快照
        self.markers = {}             # battle_id -> [Marker]
        self.viewer_limit = viewer_limit
        self.watch_delay = watch_delay
        self.viewers = {}             # battle_id -> [viewer_id]
        self.queues = {}              # battle_id -> [viewer_id] 排队
        self.views = {}               # battle_id -> 当前视角

    # ---------- 录制: 完整事件流, 按时间戳序列化 ----------
    def record(self, battle_id, damage, target):
        self.record_event(battle_id, "damage", {"damage": damage, "target": target})

    def record_event(self, battle_id, event_type, data, timestamp=None):
        if event_type not in EVENT_TYPES:
            raise ValueError(f"未知事件类型: {event_type}")
        events = self.recordings.setdefault(battle_id, [])
        ts = time.time() if timestamp is None else timestamp
        events.append(BattleEvent(ts, event_type, dict(data)))
        events.sort(key=lambda e: e.timestamp)
        self._record_delta(battle_id, event_type, data, ts)
        self._checksums[battle_id] = self._checksum(events)

    def _record_delta(self, battle_id, event_type, data, ts):
        state = self._states.setdefault(battle_id, {})
        deltas = self._deltas.setdefault(battle_id, [])
        if event_type == "state":
            changes = {k: v for k, v in data.items() if state.get(k) != v}
            if changes:
                state.update(changes)
                deltas.append({"timestamp": ts, "changes": changes})
        else:
            deltas.append({"timestamp": ts, "event": event_type, "data": dict(data)})

    # ---------- 播放: 倍速 + 逐帧 ----------
    def get_playback_speeds(self):
        return list(PLAYBACK_SPEEDS)

    def step_frame(self, battle_id, index, direction=1):
        events = self.play(battle_id)
        if not events:
            return None, 0
        index = max(0, min(index + direction, len(events) - 1))
        return events[index], index

    # ---------- 观战延迟: 可配置 + 防作弊保护 ----------
    def set_watch_delay(self, mode):
        if mode not in WATCH_DELAYS:
            raise ValueError(f"未知延迟模式: {mode}, 可选: {list(WATCH_DELAYS)}")
        self.watch_delay = mode

    def get_watch_delay(self):
        delay = WATCH_DELAYS[self.watch_delay]
        return max(delay, MIN_REALTIME_DELAY)

    def get_visible_events(self, battle_id, now=None):
        now = time.time() if now is None else now
        cutoff = now - self.get_watch_delay()
        return [e for e in self.recordings.get(battle_id, []) if e.timestamp <= cutoff]

    # ---------- 标记: 时间点 + 事件类型, 可筛选 ----------
    def add_marker(self, battle_id, timestamp, event_type="time", note=""):
        if event_type != "time" and event_type not in MARKER_EVENT_TYPES:
            raise ValueError(f"未知标记类型: {event_type}")
        marker = Marker(timestamp, event_type, note)
        self.markers.setdefault(battle_id, []).append(marker)
        return marker

    def get_markers(self, battle_id, event_type=None):
        markers = self.markers.get(battle_id, [])
        if event_type is None:
            return list(markers)
        return [m for m in markers if m.event_type == event_type]

    # ---------- 存储: 增量压缩 ----------
    def get_storage_size(self, battle_id):
        payload = json.dumps(self._deltas.get(battle_id, []),
                             sort_keys=True, default=str).encode("utf-8")
        return len(zlib.compress(payload, 9))

    # ---------- 视角: 任意玩家 / 自由视角 ----------
    def set_view(self, battle_id, view):
        if view != "free" and not str(view).startswith("player:"):
            raise ValueError("视角必须是 'free' 或 'player:<id>'")
        self.views[battle_id] = view

    def get_view(self, battle_id):
        return self.views.get(battle_id, "free")

    # ---------- 观战人数: 上限 + 排队 ----------
    def get_viewer_limit(self):
        return self.viewer_limit

    def add_viewer(self, battle_id, viewer_id):
        viewers = self.viewers.setdefault(battle_id, [])
        queue = self.queues.setdefault(battle_id, [])
        if viewer_id in viewers:
            return "watching"
        if len(viewers) < self.viewer_limit:
            viewers.append(viewer_id)
            return "watching"
        if viewer_id not in queue:
            queue.append(viewer_id)
        return f"观战人数已满(上限{self.viewer_limit}), 已排队第{queue.index(viewer_id) + 1}位"

    def remove_viewer(self, battle_id, viewer_id):
        viewers = self.viewers.get(battle_id, [])
        queue = self.queues.get(battle_id, [])
        if viewer_id in viewers:
            viewers.remove(viewer_id)
            if queue:
                viewers.append(queue.pop(0))
        elif viewer_id in queue:
            queue.remove(viewer_id)

    # ---------- 分享: 链接 + 精彩片段 ----------
    def share(self, battle_id):
        return {
            "url": f"https://replay.example.com/{battle_id}",
            "highlights": self.generate_highlights(battle_id),
        }

    def generate_highlights(self, battle_id, clip_padding=5.0):
        events = self.recordings.get(battle_id, [])
        highlights = []
        kills = [e for e in events if e.data.get("kill")]
        teamfights = [e for e in events
                      if any(m.event_type == "teamfight" and abs(m.timestamp - e.timestamp) < 1e-9
                             for m in self.markers.get(battle_id, []))]
        for e in kills:
            highlights.append({
                "type": "kill",
                "start": max(0.0, e.timestamp - clip_padding),
                "end": e.timestamp + clip_padding,
                "data": dict(e.data),
            })
        for e in teamfights:
            highlights.append({
                "type": "teamfight",
                "start": max(0.0, e.timestamp - clip_padding),
                "end": e.timestamp + clip_padding,
            })
        highlights.sort(key=lambda h: h["start"])
        return highlights

    # ---------- 校验: 不一致则报错而非崩溃 ----------
    def _checksum(self, events):
        payload = json.dumps(
            [(e.timestamp, e.event_type, e.data) for e in events],
            sort_keys=True, default=str,
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def validate_recording(self, battle_id):
        events = self.recordings.get(battle_id)
        if events is None or battle_id not in self._checksums:
            return False
        return self._checksum(events) == self._checksums[battle_id]

    def play(self, battle_id):
        if not self.validate_recording(battle_id):
            raise ReplayDataError(f"战斗 {battle_id} 回放数据校验不一致, 已中止播放")
        return list(self.recordings[battle_id])
