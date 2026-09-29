"""战斗回放观战 - 9个bug已修复，核心实现见 replay/system.py。

本模块保留旧 API 作为兼容封装。
"""
from replay.system import BattleEvent, RecordingError, ReplaySystem as _ReplayCore


class ReplaySystem(_ReplayCore):
    def record(self, battle_id, damage, target):
        return self.record_event(
            battle_id, "damage", {"damage": damage, "target": target}
        )
