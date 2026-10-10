"""Generic full-fight position transport and compact, instance-local actor tracks."""
from __future__ import annotations

from collections import defaultdict, Counter
import json
from analyzer_core.concurrency import run_parallel_indexed
from analyzer_core.event_evidence import actor_position

POSITION_FILTER = 'resources.actor.id > 0'


def fetch_replay_events(client, report_id, fight, *, position_filter=True, include_metadata=True, max_workers=4, filter_expression=None):
    # Independent time windows paginate sequentially; the shared semaphore caps
    # total requests. Boundaries deduplicate while preserving actor instances.
    start, end = int(fight['startTime']), int(fight['endTime'])
    windows = [(t, min(t+45000, end)) for t in range(start, end, 45000)]
    def fetch(item):
        i, (a, b) = item
        expression = filter_expression or (POSITION_FILTER if position_filter else None)
        kwargs = {'filter_expression': expression} if expression else {}
        return i, client.events(report_id, 'All', fight, start_time=a, end_time=b,
                               include_resources=True, **kwargs)
    pages = run_parallel_indexed(enumerate(windows), fetch, max_workers=max_workers)
    rows, previous_boundary = [], Counter()
    for i, page in pages:
        a, b = windows[i]
        boundary, next_boundary = Counter(), Counter()
        for event in page:
            timestamp = event.get('timestamp')
            if timestamp in {a, b}:
                signature = json.dumps(event, sort_keys=True, separators=(',', ':'))
                if timestamp == a:
                    boundary[signature] += 1
                    if boundary[signature] <= previous_boundary[signature]:
                        continue
                if timestamp == b:
                    next_boundary[signature] += 1
            rows.append(event)
        previous_boundary = next_boundary
    if not include_metadata:
        # Full event pages already contain casts and death boundaries.
        return rows
    # Cast starts often have no position resource, so the position filter alone
    # cannot supply an honest cast bar. This small stream covers enemy casts.
    rows.extend(client.events(report_id, 'Casts', fight, hostility_type='Enemies', include_resources=True))
    # Enemy deaths often lack coordinates; retain them as lifetime boundaries.
    rows.extend(client.events(report_id, 'Deaths', fight, hostility_type='Enemies', include_resources=True))
    return rows


def build_replay_tracks(fight, players, actor_map, events, *, actor_rows=(), deaths=(), resurrections=(), survival_timeline=(), spell_names=None):
    start, end = int(fight['startTime']), int(fight['endTime'])
    metadata = {int(row['id']): row for row in actor_rows}
    samples, states, health, energy = defaultdict(dict), defaultdict(list), defaultdict(dict), defaultdict(dict)
    boss_ids = {actor for actor, row in metadata.items() if row.get('subType') == 'Boss'}
    boss_events = defaultdict(list)
    for event in events:
        timestamp = int(event.get('timestamp') or 0)
        if not start <= timestamp <= end:
            continue
        if event.get('type') == 'death' and event.get('targetID') is not None:
            actor=event['targetID']
            state_key=actor if actor in players or actor in boss_ids else (actor,int(event.get('targetInstance') or 0))
            states[state_key].append([timestamp-start,'dead'])
        if event.get('sourceID') in boss_ids and event.get('type') in {'begincast', 'cast'}:
            boss_events[event['sourceID']].append(event)
        for side in ('source', 'target'):
            point = actor_position(event, side)
            actor = event.get(side+'ID')
            if actor is None or actor < 0:
                continue
            instance = int(event.get(side+'Instance') or 0)
            t = timestamp-start
            if point is not None:
                samples[(actor, instance)][t//100] = [t, point['x'], point['y']]
            resource = event.get(side+'Resources') or {}
            if str(event.get('resourceActor')) == ('1' if side == 'source' else '2'):
                resource = event
            hp, maximum = resource.get('hitPoints'), resource.get('maxHitPoints')
            if actor in boss_ids and hp is not None and maximum and maximum > 0:
                health[actor][t//100] = [t, int(hp), int(maximum)]
            if actor in boss_ids:
                for power in resource.get('classResources') or []:
                    if power.get('type') == 3 and power.get('max', 0) > 0:
                        energy[actor][t//100] = [t, power.get('amount', 0), power['max']]
    for event, state in [(e, 'dead') for e in deaths]+[(e, 'alive') for e in resurrections]:
        actor = event.get('targetID')
        if actor is not None:
            states[actor].append([int(event['timestamp'])-start, state])
    for row in survival_timeline:
        actor = row.get('playerID', row.get('actorID'))
        if actor is not None and row.get('kind') in {'death', 'combat_res'}:
            states[actor].append([int(row['timeMs']), 'alive' if row['kind'] == 'combat_res' else 'dead'])
    units = []
    for (actor, instance), buckets in samples.items():
        player, meta = players.get(actor), metadata.get(actor, {})
        name = (player or {}).get('name') or actor_map.get(actor) or f'单位 {actor}'
        icon = (player or {}).get('icon')
        kind = 'player' if player else 'pet' if meta.get('petOwner') is not None or meta.get('type') == 'Pet' else 'enemy'
        units.append({'key': f'{actor}:{instance}', 'actorID': actor, 'instance': instance,
                      'name': name, 'kind': kind, 'gameID': meta.get('gameID'), 'specID': (player or {}).get('specID'),
                      'icon': f'/assets/specs/{icon}.jpg' if icon else None,
                      'color': (player or {}).get('classColor') or '#d1a77a',
                      'samples': sorted(buckets.values(), key=lambda row: row[0]),
                      'states': [list(row) for row in sorted(set(map(tuple,states[actor if player or actor in boss_ids else (actor,instance)]))) ]})
    positioned = {u['actorID'] for u in units if u['kind'] == 'player'}
    bosses = []
    for actor in sorted(boss_ids & (set(health) | set(boss_events))):
        pending, casts, seen = None, [], set()
        for event in sorted(boss_events[actor], key=lambda e: e['timestamp']):
            signature = (event['timestamp'], event['type'], event.get('abilityGameID'))
            if signature in seen:
                continue
            seen.add(signature)
            time, spell = int(event['timestamp'])-start, event.get('abilityGameID')
            if event['type'] == 'begincast':
                if pending:
                    pending['endTimeMs'], pending['outcome'] = time, 'unconfirmed'
                pending = {'startTimeMs': time, 'endTimeMs': None, 'spellID': spell, 'spellName': (spell_names or {}).get(spell), 'outcome': 'unconfirmed'}
                casts.append(pending)
            elif pending and pending['spellID'] == spell:
                pending['endTimeMs'], pending['outcome'] = time, 'completed'
                pending = None
        bosses.append({'actorID': actor, 'gameID': metadata[actor].get('gameID'), 'name': actor_map.get(actor) or metadata[actor].get('name'),
                       'health': sorted(health[actor].values()), 'energy': sorted(energy[actor].values()), 'casts': casts,
                       'states': [list(row) for row in sorted(set(map(tuple,states[actor]))) ]})
    return {'version': 2, 'durationMs': end-start, 'units': units, 'bosses': bosses,
            'rosterSize': len(players), 'positionedPlayers': len(positioned),
            'missingPlayers': [p['name'] for actor, p in players.items() if actor not in positioned],
            'sampleResolutionMs': 100, 'interpolateMaxGapMs': 5000}
