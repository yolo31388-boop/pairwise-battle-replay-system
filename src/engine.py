"""战斗回放观战 - 带9个bug"""
from dataclasses import dataclass, field
import time

@dataclass
class BattleEvent:
    timestamp: float
    event_type: str
    data: dict

class ReplaySystem:
    def __init__(self):
        self.recordings = {}  # battle_id -> list of events
        self.markers = {}

    def record(self, battle_id, damage, target):
        # bug1: 只记录伤害
        if battle_id not in self.recordings:
            self.recordings[battle_id] = []
        self.recordings[battle_id].append(BattleEvent(time.time(), "damage", {"damage": damage, "target": target}))

    def get_playback_speeds(self):
        # bug2: 只有1x和2x
        return [1.0, 2.0]

    def get_watch_delay(self):
        # bug3: 固定30秒
        return 30

    def add_marker(self, battle_id, timestamp):
        # bug4: 只支持时间点
        self.markers[battle_id] = timestamp

    def get_storage_size(self, battle_id):
        # bug5: 全量存储
        return len(self.recordings.get(battle_id, [])) * 1024

    def get_view(self, battle_id):
        # bug6: 固定视角
        return "default"

    def get_viewer_limit(self):
        # bug7: 无上限
        return 99999

    def share(self, battle_id):
        # bug8: 只生成链接
        return f"https://replay.example.com/{battle_id}"

    def validate_recording(self, battle_id):
        # bug9: 无校验
        return True
