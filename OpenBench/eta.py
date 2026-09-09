# Adapted from Fishtest: https://github.com/official-stockfish/fishtest/blob/b8eecff220b562a0dc2c4e68d1fa02521e06d72c/server/fishtest/util.py

import math
import re
import time

from django.conf import settings


MIN_SAMPLE_SECONDS = 30
RATE_DECAY_SECONDS = 600
RATE_MAX_AGE_SECONDS = 1800
RATE_PRIOR_SECONDS = 120
BENCHMARK_MAX_AGE_SECONDS = 7 * 86400
FALLBACK_SCALE_FACTOR = 2.0


def remaining_games(test):

    if test.finished or test.deleted:
        return 0

    if test.test_mode == 'SPRT':
        average = getattr(settings, 'ETA_SPRT_AVERAGE_GAMES', 25000)
        positions = getattr(settings, 'ETA_SPRT_BOOK_POSITIONS', 2632036)
        boundary = abs(test.upperllr if test.currentllr > 0 else test.lowerllr)
        if not math.isfinite(boundary) or boundary <= 0 or not math.isfinite(test.currentllr):
            return None

        if test.currentllr >= test.upperllr or test.currentllr <= test.lowerllr:
            return 0


        weight = 1 - (1 - min(test.games / 2 / positions, 1.0)) ** 15
        projected = test.games * boundary / max(0.1, abs(test.currentllr))
        expected = (1 - weight) * average + weight * projected


        return max(2, expected - test.games)

    if test.test_mode == 'SPSA':
        total = 2 * test.spsa_run.iterations * test.spsa_run.pairs_per
    elif test.test_mode in ('GAMES', 'DATAGEN'):
        total = test.max_games
    else:
        return None

    return max(0, total - test.games)


def player_seconds(control):


    if re.fullmatch(r'MT=\d+', control):
        seconds = 68 * int(control[3:]) / 1000
    else:
        match = re.fullmatch(r'(?:(\d+)/)?(\d+(?:\.\d+)?)(?:\+(\d+(?:\.\d+)?))?', control)
        if not match:
            return None
        moves, base, increment = match.groups()
        if moves is not None and int(moves) == 0:
            return None
        seconds = float(base) * (68 / int(moves) if moves else 1)
        seconds += 68 * float(increment or 0)

    return 0.92 * seconds if math.isfinite(seconds) and seconds > 0 else None


def signature(test):

    return [test.dev_id, test.base_id, test.dev_network, test.base_network,
            test.dev_options, test.base_options, test.dev_time_control,
            test.base_time_control, test.scale_method, test.scale_nps,
            test.book_name, test.win_adj, test.draw_adj, test.syzygy_adj, test.syzygy_wdl]


def game_concurrency(test, machine):

    from OpenBench.workloads.get_workload import game_distribution

    distribution = game_distribution(test, machine)
    return distribution['runner-count'] * distribution['concurrency-per']


def measurement_state(result, test, machine):

    fingerprint = signature(test)
    concurrency = game_concurrency(test, machine)
    state = result.eta
    if state and state.get('signature') != fingerprint:
        state = {'timing_start': [result.dev_time + result.base_time,
                                 result.dev_time_scaled + result.base_time_scaled]}
    if state.get('concurrency') != concurrency:
        state = {key: value for key, value in state.items() if key == 'timing_start'}
    state.update(signature=fingerprint, concurrency=concurrency)
    return state


def start_assignment(result_id, test, machine):

    from django.db import transaction
    from OpenBench.models import Result

    with transaction.atomic():
        result = Result.objects.select_for_update().get(id=result_id)
        result.eta = measurement_state(result, test, machine)
        result.eta.update(sample_at=None, sample_games=result.games)
        result.save(update_fields=['eta'])


def record_benchmarks(machine):

    from django.db import transaction
    from OpenBench.models import Result

    with transaction.atomic():
        result = Result.objects.select_for_update().filter(machine=machine, test_id=machine.workload).first()
        if result is None:
            return
        state = measurement_state(result, result.test, machine)
        speeds = [machine.dev_mnps * 1e6, machine.base_mnps * 1e6]
        previous = state.get('benchmarks', speeds)
        if any(old <= 0 or not 0.8 <= new / old <= 1.25 for new, old in zip(speeds, previous)):
            for key in ('games', 'seconds', 'observed_at'):
                state.pop(key, None)
        state.update(benchmarks=speeds, benchmark_at=time.time(),
                     sample_at=time.time(), sample_games=result.games)
        result.eta = state
        result.save(update_fields=['eta'])


def record_completion(result_id, test, machine, games):

    from OpenBench.models import Result

    if machine.workload != test.id:
        return
    result = Result.objects.select_for_update().get(id=result_id)
    state = measurement_state(result, test, machine)
    now = time.time()
    completed = result.games + games
    start = state.get('sample_at')
    delta = completed - state.get('sample_games', completed)
    if start is None or now <= start or delta < 0 or now - machine.updated.timestamp() > 120:
        state.update(sample_at=now, sample_games=completed)
    elif now - start >= MIN_SAMPLE_SECONDS:
        elapsed = now - start
        age = now - state.get('observed_at', now)
        decay = math.exp(-max(0, age) / RATE_DECAY_SECONDS) if age <= RATE_MAX_AGE_SECONDS else 0
        state['games'] = decay * state.get('games', 0) + delta
        state['seconds'] = decay * state.get('seconds', 0) + elapsed
        state.update(sample_at=now, sample_games=completed, observed_at=now)
    result.eta = state
    result.save(update_fields=['eta'])


def benchmark_scale(test, speeds):

    speeds = {'DEV': speeds[:1], 'BASE': speeds[1:], 'BOTH': speeds}.get(test.scale_method, [])
    if test.scale_nps <= 0 or not speeds or any(not math.isfinite(speed) or speed <= 0 for speed in speeds):
        return None
    return test.scale_nps * sum(1 / speed for speed in speeds) / len(speeds)


def scale_factor(test, machine, result, now):

    if machine.workload == test.id:
        scale = benchmark_scale(test, [machine.dev_mnps * 1e6, machine.base_mnps * 1e6])
        if scale is not None:
            return scale
    if result is not None:
        state = result.eta
        if now - state.get('benchmark_at', 0) <= BENCHMARK_MAX_AGE_SECONDS:
            scale = benchmark_scale(test, state.get('benchmarks', []))
            if scale is not None:
                return scale
        start_time, start_scaled = state.get('timing_start', [0, 0])
        wall = result.dev_time + result.base_time - start_time
        scaled = result.dev_time_scaled + result.base_time_scaled - start_scaled
        if wall > 0 and scaled > 0:
            return wall / scaled
    return FALLBACK_SCALE_FACTOR


def effective_rate(test, machine, result, now):

    concurrency = game_concurrency(test, machine)
    if concurrency <= 0:
        return 0.0
    dev = player_seconds(test.dev_time_control)
    base = player_seconds(test.base_time_control)
    duration = scale_factor(test, machine, result, now) * (dev + base) if dev is not None and base is not None else None
    predicted = concurrency / duration if duration is not None else None
    state = result.eta if result is not None else {}
    age = now - state.get('observed_at', 0)
    if state.get('concurrency') != concurrency or age > RATE_MAX_AGE_SECONDS or state.get('seconds', 0) <= 0:
        return predicted
    decay = math.exp(-max(0, age) / RATE_DECAY_SECONDS)
    seconds = state['seconds'] * decay
    games = state.get('games', 0) * decay
    if predicted is None:
        return games / seconds if games > 0 else None
    prior = max(RATE_PRIOR_SECONDS, 2 * duration)
    return (prior * predicted + games) / (prior + seconds)


def eligible(test, machine):

    from OpenBench.utils import workload_uses_time_based_tc
    from OpenBench.workloads.get_workload import valid_hardware_assignment

    info = machine.info
    if test.dev_engine not in info['supported'] or test.base_engine not in info['supported']:
        return False
    if str(test.id) in {str(value) for value in info.get('blacklist', [])}:
        return False
    for requirement in (test.syzygy_adj, test.syzygy_wdl):
        if requirement.endswith('-MAN') and int(requirement.split('-')[0]) > info['syzygy_max']:
            return False
    return (not info.get('noisy') or not workload_uses_time_based_tc(test)) and valid_hardware_assignment(test, machine)


def simulate_queue(tests, machines, remaining, rates, compatible):

    from OpenBench.config import OPENBENCH_CONFIG

    pending = dict(remaining)
    elapsed = 0.0
    assignments = {machine.id: machine.workload for machine in machines}
    while pending:
        totals = dict.fromkeys(pending, 0.0)
        threads = dict.fromkeys(pending, 0)
        choices = {}
        for machine in machines:
            candidates = [test for test in tests if test.id in pending and compatible[machine.id, test.id]]
            if not candidates:
                continue
            priority = max(test.priority for test in candidates)
            candidates = [test for test in candidates if test.priority == priority]
            focused = [test for test in candidates if test.dev_engine in machine.info.get('focus', [])]
            choices[machine.id] = focused or candidates
        for machine in sorted(machines, key=lambda m: (len(choices.get(m.id, [])), m.id)):
            candidates = choices.get(machine.id, [])
            if not candidates:
                continue
            weights = {test.id: max(1, test.throughput) for test in candidates}
            if OPENBENCH_CONFIG['balance_engine_throughputs']:
                for test in candidates:
                    weights[test.id] /= sum(other.dev_engine == test.dev_engine for other in candidates)
            current = next((test for test in candidates if test.id == assignments.get(machine.id)), None)
            selected = current if elapsed == 0 and current is not None else min(
                candidates, key=lambda test: ((threads[test.id] + machine.info['concurrency']) / weights[test.id], test.id))
            rate = rates[machine.id, selected.id]
            if rate is None:
                return None
            totals[selected.id] += rate
            threads[selected.id] += machine.info['concurrency']
            assignments[machine.id] = selected.id
        intervals = {id: pending[id] / rate for id, rate in totals.items() if rate > 0}
        if not intervals:
            return None
        first = min(intervals, key=intervals.get)
        step = intervals[first]
        elapsed += step
        pending = {id: max(0, games - step * totals[id]) for id, games in pending.items()
                   if id != first and games - step * totals[id] > 1e-6}
    return elapsed


def format_hours(hours):

    minutes = math.ceil(hours * 60)
    if minutes < 1:
        return '<1m'
    if minutes < 60:
        return '~%dm' % minutes
    if minutes < 1440:
        return '~%dh %dm' % divmod(minutes, 60)
    days, hours = divmod(math.ceil(minutes / 60), 24)
    return '~%dd %dh' % (days, hours)


def queue_eta(tests, machines):

    from OpenBench.models import Result

    tests = [test for test in tests if test.approved and not test.finished and not test.deleted]
    if not tests:
        return {'label': 'Queue empty', 'hours': 0, 'detail': 'No approved workloads remain.'}
    remaining = {test.id: remaining_games(test) for test in tests}
    unavailable = {'label': 'Unavailable', 'hours': None,
                   'detail': 'Some queued workloads lack a compatible worker or enough timing data for an estimate.'}
    if any(games is None for games in remaining.values()):
        return unavailable
    tests = [test for test in tests if remaining[test.id] > 0]
    remaining = {test.id: remaining[test.id] for test in tests}
    if not tests:
        return {'label': '<1m', 'hours': 0, 'detail': 'No estimated games remain.'}
    now = time.time()
    machines = [machine for machine in machines if machine.info.get('concurrency', 0) > 0
                and now - machine.updated.timestamp() <= 120]
    if not machines:
        return {'label': 'No workers', 'hours': None,
                'detail': 'An estimate will appear when workers are connected to the approved queue.'}

    fingerprints = {test.id: signature(test) for test in tests}
    results = {(result.machine_id, result.test_id): result for result in Result.objects.filter(
        test_id__in=remaining, machine_id__in=[machine.id for machine in machines]).only(
        'test_id', 'machine_id', 'eta', 'dev_time', 'base_time', 'dev_time_scaled', 'base_time_scaled')
        if not result.eta or result.eta.get('signature') == fingerprints[result.test_id]}
    compatible = {(machine.id, test.id): eligible(test, machine) for machine in machines for test in tests}
    rates = {(machine.id, test.id): effective_rate(test, machine, results.get((machine.id, test.id)), now)
             for machine in machines for test in tests if compatible[machine.id, test.id]}
    seconds = simulate_queue(tests, machines, remaining, rates, compatible)
    if seconds is None or not math.isfinite(seconds):
        return unavailable
    hours = seconds / 3600
    return {'label': format_hours(hours), 'hours': hours,
            'detail': 'Approximate time to clear approved workloads using worker speeds and game completion rates '
                      'observed by the server. Models reassignment by priority, throughput, and worker eligibility. '
                      'Unknown speeds assume half reference speed; SPRT outcomes and available workers may change.'}
