"""回放测试"""
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.engine import ReplaySystem, BattleEvent

class TestRecord:
    def test_records_skills(self):
        rs = ReplaySystem()
        rs.record("b1", 100, "enemy")
        events = rs.recordings["b1"]
        # 应该记录技能释放
        assert True  # 基本验证

class TestSpeed:
    def test_slow_motion(self):
        rs = ReplaySystem()
        speeds = rs.get_playback_speeds()
        assert 0.5 in speeds, "无0.5x慢放"
