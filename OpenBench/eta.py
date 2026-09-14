# SPRT stopping-time model adapted from Fishtest:
# https://github.com/official-stockfish/fishtest/blob/b8eecff220b562a0dc2c4e68d1fa02521e06d72c/server/fishtest/static/js/sprt.js

import math
import re

from django.conf import settings


NELO_DIVIDED_BY_NT = 800 / math.log(10)


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

    # In the normalized Fishtest model, the LLR process has variance w2 per
    # game and drift h*w2/2. Estimate h from the test's observed LLR slope.
    h = 0.0 if test.games <= 0 else 2 * current / (test.games * w2)

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

    ids = {test.id for test in tests}
    threads = sum(
        machine.info.get('concurrency', 0)
        for machine in machines
        if machine.workload in ids
    )
    if threads <= 0:
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

    hours = sum(work) / (threads * 0.5)
    return {
        'label': format_hours(hours),
        'hours': hours,
        'detail': 'Approximate time to clear all approved workloads at the current active thread count. '
                  'SPRT duration uses a Fishtest-derived stopping-time estimate conditioned on the current LLR. '
                  'Assumes workers run at half the reference speed and excludes workloads awaiting approval.',
    }
