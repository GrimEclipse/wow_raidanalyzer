import unittest
from unittest.mock import patch

from boss_plugins.venomous_abyss import twinfangs as t


def event(ts, kind, spell, source=99, target=1, **kwargs):
    return dict(timestamp=ts, type=kind, abilityGameID=spell, sourceID=source, targetID=target, **kwargs)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.fight = dict(startTime=1000, endTime=400000)
        self.players = {1: dict(name="P1"), 2: dict(name="P2")}
        self.raw = dict(trackedActorEvents=[], deaths=[])

    def rotation(self, start, end):
        self.raw['trackedActorEvents'] += [event(start, 'applybuff', 1294293, target=99),
                                           event(end, 'removebuff', 1294293, target=99),
                                           event(end, 'removebuff', 1294293, target=100)]

    def test_real_end_strict_limits_and_all_prior_history(self):
        self.rotation(141000, 155000)
        self.rotation(296000, 310000)
        rows = [dict(timeMs=1000, toStack=5, delta=5, source='吃球'),
                dict(timeMs=200000, toStack=7, delta=2, source='射线'),
                dict(timeMs=350000, toStack=9, delta=2, source='过晚')]
        result = t._venom_checkpoints(self.fight, {}, self.players, self.raw, [dict(playerID=1, events=rows)])
        self.assertEqual([(r['timeMs'], r['limit'], r['count']) for r in result], [(154000, 4, 1), (309000, 7, 0)])
        self.assertEqual(len(result[0]['players']), 2)
        self.assertEqual(len(result[1]['players'][0]['history']), 2)
        self.assertEqual(result[0]['players'][0]['gainsBySource'], [dict(source='吃球', stacks=5)])

    def test_no_wall_clock_fallback_or_truncated_rotation(self):
        self.assertEqual(t._venom_checkpoints(self.fight, {}, self.players, self.raw, []), [])
        self.rotation(141000, 145000)
        self.assertEqual(t._venom_checkpoints(self.fight, {}, self.players, self.raw, []), [])

    def test_removals_and_exact_threshold_are_not_failures(self):
        self.rotation(141000, 155000)
        rows = [dict(timeMs=1000, toStack=6, delta=6, source='吃球'),
                dict(timeMs=2000, toStack=4, delta=-2, source='盛宴')]
        result = t._venom_checkpoints(self.fight, {}, self.players, self.raw, [dict(playerID=1, events=rows)])
        self.assertEqual(result[0]['count'], 0)
        self.assertEqual(result[0]['players'][0]['removedStacks'], 2)


    def test_any_prior_player_death_exempts_even_after_resurrection(self):
        self.rotation(141000, 155000)
        self.raw['deaths'] = [event(90000, 'death', 0, target=2)]
        self.raw['friendlyCasts'] = [event(100000, 'resurrect', 0, target=2)]
        rows = [dict(timeMs=1000, toStack=6, delta=6, source='吃球')]
        result = t._venom_checkpoints(self.fight, {}, self.players, self.raw, [dict(playerID=1, events=rows)])
        self.assertTrue(result[0]['exempt'])
        self.assertEqual(result[0]['count'], 0)
        self.assertTrue(result[0]['players'][0]['exceeded'])
        self.assertEqual(result[0]['players'][0]['gainsBySource'][0]['stacks'], 6)

    def test_death_between_checkpoints_only_exempts_second(self):
        self.rotation(141000, 155000)
        self.rotation(296000, 310000)
        self.raw['deaths'] = [event(200000, 'death', 0, target=2), event(2000, 'death', 0, target=999)]
        rows = [dict(timeMs=1000, toStack=8, delta=8, source='吃球')]
        result = t._venom_checkpoints(self.fight, {}, self.players, self.raw, [dict(playerID=1, events=rows)])
        self.assertEqual([r['count'] for r in result], [1, 0])
        self.assertEqual([r['exempt'] for r in result], [False, True])

    def test_overview_renders_composition_and_named_spit_responsibility(self):
        self.rotation(141000, 155000)
        histories = [dict(playerID=1, events=[dict(timeMs=1000, toStack=6, delta=6, source='吃球')])]
        checkpoint = t._venom_checkpoints(self.fight, {}, self.players, self.raw, histories)
        pull = dict(fightID=1, twinfangs=dict(eternalVenom=dict(checkpoints=checkpoint),
            spit=dict(events=[dict(counted=True, time='00:42', target=dict(player='P2', playerID=2),
                                  headID=99, headInstance=1, reasons=['后射'], collateral=[dict(player='P1')])])))
        metrics = {m['key']: m for m in t._mechanic_overview([pull], {'spitReviewEnabled': True})['metrics']}
        self.assertIn('吃球 +6', metrics['venomOverExpected']['events'][0]['text'])
        self.assertIn('责任玩家：P2', metrics['spitDirection']['events'][0]['text'])
        self.assertIn('额外受击：P1', metrics['spitDirection']['events'][0]['text'])
        checkpoint[0]['players'][0]['count'] = 0
        checkpoint[0]['exempt'] = True
        checkpoint[0]['exemption'] = dict(time='00:10', player='P2')
        metrics = {m['key']: m for m in t._mechanic_overview([pull])['metrics']}
        self.assertEqual(metrics['venomOverExpected']['value'], 0)
        self.assertEqual(metrics['venomOverExpected']['exemptCount'], 1)
        self.assertIn('已豁免', metrics['venomOverExpected']['events'][0]['text'])
        self.assertIn('吃球 +6', metrics['venomOverExpected']['events'][0]['text'])


class SpitTests(unittest.TestCase):
    def review(self, target=(0, -500), additions=(), resource_actor=2):
        cast = event(10000, 'cast', 1291478, target=1, sourceInstance=1, resourceActor=1, x=0, y=0)
        hit = event(10025, 'damage', 1293295, target=1, sourceInstance=1, resourceActor=resource_actor,
                    x=target[0], y=target[1], amount=100)
        raw = dict(trackedActorEvents=[cast, hit, *additions], casts=[cast], damage=[dict(hit)])
        arena = dict(key='test', label='测试', bosses=dict(left=(-1000, 5000), right=(1000, 5000)))
        with patch.object(t, 'BROOD_ARENAS', [arena]), patch.object(t, 'SPIT_HEAD_POSITIONS', {'test': {'left': (-500, 0), 'middle': (0, 0), 'right': (500, 0)}}):
            return t._spit_review(dict(startTime=0), {}, {1: dict(name='P1'), 2: dict(name='P2')}, raw)

    def test_backward_count_once_and_instance_matched_collateral(self):
        extra = [event(10030, 'damage', 1293295, target=2, sourceInstance=1, amount=20),
                 event(10040, 'damage', 1293295, target=2, sourceInstance=2, amount=40)]
        result = self.review(additions=extra)
        self.assertEqual(result['count'], 1)
        self.assertEqual(result['collateralCount'], 1)
        self.assertEqual(result['events'][0]['collateral'][0]['damage'], 20)
        self.assertEqual(len(result['events'][0]['victims']), 2)

    def test_forward_cone_counts(self):
        row = self.review(target=(0, 3000))['events'][0]
        self.assertTrue(row['counted'])
        self.assertEqual(row['status'], '射入禁射夹角')

    def test_no_wrong_coordinate_owner_or_missing_target_blame(self):
        row = self.review(resource_actor=1)['events'][0]
        self.assertFalse(row['counted'])
        self.assertIsNone(row['targetPosition'])

    def test_stale_immune_and_other_instances_not_collateral(self):
        extra = [event(10760, 'damage', 1293295, target=2, sourceInstance=1, amount=20),
                 event(10010, 'damage', 1293295, target=2, sourceInstance=1, amount=0, hitType=10)]
        self.assertEqual(self.review(additions=extra)['collateralCount'], 0)

    def test_side_forward_allowed_and_backward_forbidden(self):
        self.assertFalse(self.review(target=(2000, 3000))['events'][0]['counted'])
        self.assertFalse(self.review(target=(-2000, 3000))['events'][0]['counted'])
        self.assertTrue(self.review(target=(2000, -3000))['events'][0]['counted'])

    def test_cone_boundary_is_included(self):
        self.assertTrue(self.review(target=(500, 5000))['events'][0]['counted'])
        self.assertTrue(self.review(target=(-500, 5000))['events'][0]['counted'])
        self.assertFalse(self.review(target=(510, 5000))['events'][0]['counted'])

    def test_all_three_arenas_and_heads_share_the_boundary_directions(self):
        for arena in t.BROOD_ARENAS:
            heads = t.SPIT_HEAD_POSITIONS[arena['key']]
            vectors = [tuple(arena['bosses'][side][i] - heads[side][i] for i in (0, 1)) for side in ('left', 'right')]
            forward = tuple(sum(v[i] for v in vectors) / 2 for i in (0, 1))
            for origin in heads.values():
                result = t._spit_direction(origin, tuple(origin[i] + forward[i] for i in (0, 1)))
                self.assertTrue(result['counted'])
                self.assertEqual(result['status'], '射入禁射夹角')
                rear = t._spit_direction(origin, tuple(origin[i] - forward[i] for i in (0, 1)))
                self.assertEqual(rear['status'], '后射')

    def test_unknown_head_location_is_not_blamed(self):
        result = t._spit_direction((100000, 100000), (100000, 101000))
        self.assertFalse(result['counted'])


if __name__ == '__main__':
    unittest.main()
