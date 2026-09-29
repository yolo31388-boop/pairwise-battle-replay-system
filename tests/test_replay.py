"""回放与观战系统测试：覆盖九个录制事故的修复。"""
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from replay.system import (
    BattleEvent,
    FRAME_INTERVAL,
    RecordingError,
    ReplaySystem,
)


class TestRecord:
    def test_full_event_stream_in_timestamp_order(self):
        rs = ReplaySystem()
        rs.record_event("b1", "damage", {"damage": 100}, timestamp=3.0)
        rs.record_event("b1", "skill", {"skill": "fireball"}, timestamp=1.0)
        rs.record_event("b1", "move", {"x": 10, "y": 20}, timestamp=2.0)
        rs.record_event("b1", "state", {"hp": 80}, timestamp=4.0)
        events = rs.recordings["b1"]
        assert [e.event_type for e in events] == ["skill", "move", "damage", "state"]
        assert [e.timestamp for e in events] == [1.0, 2.0, 3.0, 4.0]


class TestSpeed:
    def test_all_speeds_supported(self):
        rs = ReplaySystem()
        assert rs.get_playback_speeds() == [0.5, 1.0, 2.0, 4.0]

    def test_frame_by_frame(self):
        rs = ReplaySystem()
        rs.record_event("b1", "skill", {"skill": "a"}, timestamp=0.0)
        rs.record_event("b1", "damage", {"damage": 5}, timestamp=FRAME_INTERVAL * 2)
        assert [e.event_type for e in rs.step_frame("b1")] == ["skill"]
        assert rs.step_frame("b1") == []
        assert [e.event_type for e in rs.step_frame("b1")] == ["damage"]


class TestWatchDelay:
    def test_delay_configurable_with_anti_cheat_protection(self):
        rs = ReplaySystem()
        for delay in (0, 10, 30):
            rs.set_watch_delay(delay)
            assert rs.get_watch_delay() == delay
        with pytest.raises(ValueError):
            rs.set_watch_delay(5)
        rs.set_watch_delay(10)
        rs.record_event("b1", "skill", {}, timestamp=100.0)
        rs.record_event("b1", "damage", {}, timestamp=120.0)
        visible = rs.get_spectator_view("b1", now=125.0)
        assert [e.timestamp for e in visible] == [100.0]


class TestMarkers:
    def test_point_and_event_markers_with_filter(self):
        rs = ReplaySystem()
        rs.add_marker("b1", 12.0)
        rs.add_marker("b1", 30.0, event_type="kill")
        rs.add_marker("b1", 60.0, event_type="tower")
        rs.add_marker("b1", 90.0, event_type="teamfight")
        assert len(rs.get_markers("b1")) == 4
        kills = rs.get_markers("b1", event_type="kill")
        assert len(kills) == 1 and kills[0]["timestamp"] == 30.0
        assert len(rs.get_markers("b1", event_type="teamfight")) == 1
        with pytest.raises(ValueError):
            rs.add_marker("b1", 1.0, event_type="unknown")


class TestStorage:
    def test_delta_compression_shrinks_and_roundtrips(self):
        rs = ReplaySystem()
        rs.record_event("b1", "state", {"hp": 100, "mp": 50, "x": 0}, timestamp=1.0)
        rs.record_event("b1", "state", {"hp": 90, "mp": 50, "x": 0}, timestamp=2.0)
        rs.record_event("b1", "state", {"hp": 80, "mp": 50, "x": 1}, timestamp=3.0)
        assert rs.get_storage_size("b1") < rs.get_full_storage_size("b1")
        restored = rs.decompress_recording(rs.compress_recording("b1"))
        assert [(e.timestamp, e.event_type, e.data) for e in restored] == [
            (e.timestamp, e.event_type, e.data) for e in rs.recordings["b1"]
        ]


class TestView:
    def test_switch_any_player_and_free_view(self):
        rs = ReplaySystem()
        rs.set_view("b1", "player_7")
        assert rs.get_view("b1") == "player_7"
        rs.set_view("b1", "player_3")
        assert rs.get_view("b1") == "player_3"
        rs.set_view("b1", "free")
        assert rs.get_view("b1") == "free"


class TestSpectators:
    def test_viewer_limit_and_queue(self):
        rs = ReplaySystem(viewer_limit=2)
        assert rs.join_spectate("b1", "v1")["status"] == "watching"
        assert rs.join_spectate("b1", "v2")["status"] == "watching"
        result = rs.join_spectate("b1", "v3")
        assert result["status"] == "queued"
        assert result["position"] == 1
        assert "上限" in result["message"]
        rs.leave_spectate("b1", "v1")
        assert rs.join_spectate("b1", "v3")["status"] == "watching"
        assert rs.get_viewer_count("b1") == 2


class TestShare:
    def test_share_generates_highlight_clips(self):
        rs = ReplaySystem()
        for t in (30.0, 32.0, 34.0):
            rs.record_event("b1", "damage", {"damage": 999, "kill": True}, timestamp=t)
        result = rs.share("b1")
        assert result["url"].endswith("/b1")
        kinds = [h["type"] for h in result["highlights"]]
        assert "kill" in kinds
        assert "teamfight" in kinds
        for clip in result["highlights"]:
            assert clip["end"] > clip["start"]


class TestChecksum:
    def test_tampered_recording_reports_error_not_crash(self):
        rs = ReplaySystem()
        rs.record_event("b1", "skill", {"skill": "a"}, timestamp=1.0)
        assert rs.validate_recording("b1") is True
        rs.recordings["b1"][0].data["skill"] = "tampered"
        assert rs.validate_recording("b1") is False
        with pytest.raises(RecordingError):
            rs.get_playback_events("b1")
