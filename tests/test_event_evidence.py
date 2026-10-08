import unittest

from analyzer_core.event_evidence import actor_position, build_event_scene


class EventEvidenceTests(unittest.TestCase):
    def test_position_never_borrows_the_other_actor_resources(self):
        event = {"sourceResources": {"x": 10, "y": 20}, "x": 99, "y": 88, "resourceActor": 1}
        self.assertIsNone(actor_position(event, "target"))
        self.assertEqual(actor_position(event, "source")["x"], 10)

    def test_same_event_in_two_streams_is_deduplicated_and_unlocated_event_survives(self):
        event = {"timestamp": 1500, "type": "damage", "abilityGameID": 7, "sourceID": 99, "targetID": 1, "amount": 50}
        result = build_event_scene({"startTime": 1000, "endTime": 3000}, {1: "Player"}, {1: {"name": "Player"}},
                                   {"a": [event], "b": [event]}, {"a": {7: "Mechanic"}, "b": {7: "Mechanic"}},
                                   key="test", arena_image="assets/arena.jpg", note="test")
        self.assertEqual(len(result["events"]), 1)
        row = result["events"][0]
        self.assertEqual(row["timeMs"], 500)
        self.assertEqual(row["actor"], "Player")
        self.assertEqual(row["points"], [])
        self.assertFalse(row["problem"])

    def test_nearby_position_is_labeled_and_cannot_cross_unit_instances(self):
        events = [
            {"timestamp": 1400, "type": "cast", "abilityGameID": 8, "sourceID": 9, "sourceInstance": 1, "sourceResources": {"x": 10, "y": 20}},
            {"timestamp": 1500, "type": "cast", "abilityGameID": 7, "sourceID": 9, "sourceInstance": 1},
            {"timestamp": 1500, "type": "cast", "abilityGameID": 7, "sourceID": 9, "sourceInstance": 2},
            {"timestamp": 2400, "type": "cast", "abilityGameID": 7, "sourceID": 9, "sourceInstance": 1},
        ]
        scene = build_event_scene({"startTime": 1000, "endTime": 3000}, {9: "NPC"}, {},
                                  {"casts": events}, {"casts": {7: "Mechanic"}},
                                  key="test", arena_image="arena.jpg", note="test")
        self.assertEqual(scene["events"][0]["points"][0]["position"]["sampleOffsetMs"], -100)
        self.assertIn("仅供显示", scene["events"][0]["evidence"])
        self.assertEqual(scene["events"][1]["points"], [])
        self.assertEqual(scene["events"][2]["points"], [])


if __name__ == "__main__":
    unittest.main()
