# SPRT stopping-time model adapted from Fishtest:
# https://github.com/official-stockfish/fishtest/blob/b8eecff220b562a0dc2c4e68d1fa02521e06d72c/server/fishtest/static/js/sprt.js

import math
import re

from django.conf import settings


NELO_DIVIDED_BY_NT = 800 / math.log(10)
FALLBACK_RELATIVE_SPEED = 0.5


def _sprt_pt(lower, upper, h):

    if not lower < 0 < upper:
        return None

    if abs(h * (lower - upper)) < 1e-6:
        probability = -lower / (upper - lower)
        duration = -lower * upper
        return probability, duration

    if h > 0:
        exp_lower = math.exp(h * lower)
        exp_span = math.exp(h * (lower - upper))
        probability = (exp_lower - 1) / (exp_span - 1)
    else:
        exp_upper = math.exp(h * upper)
        exp_span = math.exp(h * (upper - lower))
        probability = (exp_upper - exp_span) / (1 - exp_span)

    duration = (2 / h) * (
        upper * probability + lower * (1 - probability)
    )

    return probability, max(0.0, duration)


def _normalized_elo_from_penta(test):

    results = (test.LL, test.LD, test.DD, test.DW, test.WW)
    pairs = sum(results)
    if pairs <= 1:
        return None

    mean = sum((index / 4) * count for index, count in enumerate(results)) / pairs
    variance = sum(
        ((index / 4) - mean) ** 2 * count
        for index, count in enumerate(results)
    ) / pairs

    if not math.isfinite(variance) or variance <= 0:
        return None

    sigma_per_game = math.sqrt(2 * variance)
    return NELO_DIVIDED_BY_NT * (mean - 0.5) / sigma_per_game


def _normalized_sprt_remaining_games(test):

    lower = test.lowerllr
    current = test.currentllr
    upper = test.upperllr

    if not all(math.isfinite(value) for value in (lower, current, upper)):
        return None
    if not lower < current < upper:
        return 0

    elo0 = test.elolower
    elo1 = test.eloupper
    if not all(math.isfinite(value) for value in (elo0, elo1)) or elo1 <= elo0:
        return None

    w2 = ((elo1 - elo0) / NELO_DIVIDED_BY_NT) ** 2
    if not math.isfinite(w2) or w2 <= 0:
        return None

    observed_elo = _normalized_elo_from_penta(test)
    if observed_elo is None:
        observed_elo = (elo0 + elo1) / 2

    # Fishtest's Brownian approximation has variance w2 per game and drift
    # h*w2/2. Estimate h from the current normalized-Elo result, then shift
    # both absorbing boundaries by the LLR already accumulated by the test.
    h = (2 * observed_elo - (elo0 + elo1)) / (elo1 - elo0)
    estimate = _sprt_pt(lower - current, upper - current, h)
    if estimate is None:
        return None

    _, duration = estimate
    remaining = duration / w2

    return max(2.0, remaining) if math.isfinite(remaining) else None


def _legacy_sprt_remaining_games(test):

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


def remaining_games(test):

    if test.finished or test.deleted:
        return 0

    if test.test_mode == 'SPRT':
        if test.use_penta and not test.use_tri:
            return _normalized_sprt_remaining_games(test)
        return _legacy_sprt_remaining_games(test)

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


def remaining_core_hours(test):

    from OpenBench.utils import extract_option

    games = remaining_games(test)
    if games == 0:
        return 0.0

    dev_seconds = player_seconds(test.dev_time_control)
    base_seconds = player_seconds(test.base_time_control)
    if games is None or dev_seconds is None or base_seconds is None:
        return None

    threads = max(
        int(extract_option(test.dev_options, 'Threads') or 1),
        int(extract_option(test.base_options, 'Threads') or 1),
    )

    return games * (dev_seconds + base_seconds) * threads / 3600


def _machine_threads(test, machine):

    from OpenBench.utils import extract_option

    concurrency = int(machine.info.get('concurrency', 0))
    if concurrency <= 0:
        return 0

    dev_threads = int(extract_option(test.dev_options, 'Threads') or 1)
    base_threads = int(extract_option(test.base_options, 'Threads') or 1)
    physical = int(machine.info.get('physical_cores', concurrency))

    # Match workload assignment: core-odds tests do not use hyperthreads.
    if physical < concurrency and dev_threads != base_threads:
        concurrency //= 2

    return concurrency


def _machine_relative_speed(test, machine):

    target = test.scale_nps / 1e6
    dev = float(machine.dev_mnps or 0)
    base = float(machine.base_mnps or 0)

    if target <= 0:
        return FALLBACK_RELATIVE_SPEED

    if test.scale_method == 'DEV' and dev > 0:
        return dev / target

    if test.scale_method == 'BASE' and base > 0:
        return base / target

    if test.scale_method == 'BOTH' and dev > 0 and base > 0:
        # The client scales by the arithmetic mean of the two time factors.
        # Invert that factor to express this worker in reference-speed cores.
        factor = (target / dev + target / base) / 2
        return 1 / factor

    return FALLBACK_RELATIVE_SPEED


def _fleet_capacity(tests, machines):

    by_id = {test.id: test for test in tests}
    capacity = 0.0
    fallbacks = 0

    for machine in machines:
        test = by_id.get(machine.workload)
        if test is None:
            continue

        threads = _machine_threads(test, machine)
        speed = _machine_relative_speed(test, machine)
        capacity += threads * speed

        if speed == FALLBACK_RELATIVE_SPEED and not (machine.dev_mnps or machine.base_mnps):
            fallbacks += 1

    return capacity, fallbacks


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

    tests = [
        test for test in tests
        if test.approved and not test.finished and not test.deleted
    ]
    if not tests:
        return {
            'label': 'Queue empty',
            'hours': 0,
            'detail': 'No approved workloads remain.',
        }

    # Callers may defer benchmark fields with QuerySet.only(). Replace that
    # projection here so capacity is computed without per-machine DB queries.
    if hasattr(machines, 'only'):
        machines = machines.only(
            'info', 'workload', 'dev_mnps', 'base_mnps'
        )
    machines = list(machines)

    capacity, fallbacks = _fleet_capacity(tests, machines)
    if capacity <= 0:
        return {
            'label': 'No workers',
            'hours': None,
            'detail': 'An estimate will appear when workers are connected to the approved queue.',
        }

    work = [remaining_core_hours(test) for test in tests]
    if any(hours is None for hours in work):
        return {
            'label': 'Unavailable',
            'hours': None,
            'detail': 'Some queued workloads cannot be estimated from their time controls or test settings.',
        }

    hours = sum(work) / capacity
    detail = (
        'Approximate time to clear all approved workloads at current capacity. '
        'SPRT duration uses a Fishtest-derived stopping-time estimate conditioned '
        'on the current LLR and result distribution. Worker capacity uses reported '
        'benchmark speeds and excludes workloads awaiting approval.'
    )
    if fallbacks:
        detail += ' Workers awaiting benchmark data temporarily use 0.5x reference speed.'

    return {
        'label': format_hours(hours),
        'hours': hours,
        'detail': detail,
    }
