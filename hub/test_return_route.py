"""복귀 경로·중간 위치·도착·경로 조회 지연 검사. 모델·API·운영 로그를 쓰지 않는다."""
import tempfile
import unittest
from pathlib import Path

from ambulance_sim import DispatchSim, RETURN_SEC
from schema import GpsPoint

BASE = GpsPoint(lat=37.5, lng=127.0)
ORIGIN = GpsPoint(lat=37.6, lng=127.0)
PATH = [[37.6, 127.0], [37.6, 127.1], [37.5, 127.1], [37.5, 127.0]]


class Clock:
    t = 1000.0
    def __call__(self): return self.t


class Router:
    def __init__(self, clock, delay=0): self.clock, self.delay = clock, delay
    def route(self, origin, dest):
        self.clock.t += self.delay
        return {"path": PATH, "durationSec": 900}


class ReturnRouteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.sim = DispatchSim(Router(self.clock), clock=self.clock, pool_dir=Path(self.temp.name))
        self.sim.ensure_unit("A", BASE)
        self.unit = self.sim._units["A"]
        self.unit.gps, self.unit.phase, self.unit.case_id = ORIGIN, "on_scene", "case"
    def tearDown(self): self.temp.cleanup()

    def test_scene_end_starts_at_scene_with_road_path(self):
        self.assertTrue(self.sim.scene_end("A", "case"))
        state = self.sim.state("A")
        self.assertEqual(state["phase"], "returning")
        self.assertEqual(state["gps"], ORIGIN.model_dump())
        self.assertEqual(state["path"], PATH)
        self.assertIsNone(state["caseId"])
        self.assertAlmostEqual(self.unit.trip.duration_sec / self.unit.trip.speedup, RETURN_SEC)

    def test_halfway_follows_bent_road_then_arrives_at_base(self):
        self.sim.scene_end("A", "case")
        self.clock.t += RETURN_SEC / 2
        _, moving = self.sim.tick()
        self.assertEqual(moving[0]["phase"], "returning")
        self.assertAlmostEqual(self.sim.gps_for("A").lng, 127.1, places=5)
        self.assertNotEqual(self.sim.gps_for("A"), BASE)
        self.clock.t += RETURN_SEC / 2 + 0.01
        changed, _ = self.sim.tick()
        self.assertEqual(changed[0]["phase"], "idle")
        self.assertEqual(self.sim.gps_for("A"), BASE)

    def test_route_lookup_delay_does_not_skip_return(self):
        self.sim._router = Router(self.clock, delay=60)
        self.sim.scene_end("A", "case")
        self.sim.tick()
        self.assertEqual(self.sim.phase_of("A"), "returning")
        self.assertEqual(self.sim.gps_for("A"), ORIGIN)
        self.clock.t += RETURN_SEC / 4
        self.sim.tick()
        self.assertNotEqual(self.sim.gps_for("A"), BASE)

    def test_patient_accepted_uses_same_return_route(self):
        self.unit.phase = "at_hospital"
        self.assertTrue(self.sim.on_arrival_result("A", "case", accepted=True))
        self.clock.t = self.unit.dwell_until
        changed, _ = self.sim.tick()
        self.assertEqual(changed[0]["phase"], "returning")
        self.assertEqual(changed[0]["path"], PATH)
        self.assertEqual(changed[0]["gps"], ORIGIN.model_dump())
        self.assertAlmostEqual(self.unit.trip.duration_sec / self.unit.trip.speedup, RETURN_SEC)


if __name__ == "__main__": unittest.main()
