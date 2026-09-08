"""Queue-clearance heuristic adapted from official-stockfish/fishtest util.py.

https://github.com/official-stockfish/fishtest/blob/b8eecff220b562a0dc2c4e68d1fa02521e06d72c/server/fishtest/util.py

This predicts nominal core-hours, not an SPRT stopping-time confidence interval.
The game-count prior and opening-book weighting should be calibrated as Verdict
accumulates test history. Worker speed and scheduling constraints are not modeled.
"""

import math
import re

from django.conf import settings


def remaining_games(test):

    if test.finished or test.deleted:
        return 0

    if test.test_mode == 'SPRT':
        average = getattr(settings, 'ETA_SPRT_AVERAGE_GAMES', 95000)
        positions = getattr(settings, 'ETA_SPRT_BOOK_POSITIONS', 2632036)
        boundary = abs(test.upperllr if test.currentllr > 0 else test.lowerllr)
        if not math.isfinite(boundary) or boundary <= 0 or not math.isfinite(test.currentllr):
            return None

        if test.currentllr >= test.upperllr or test.currentllr <= test.lowerllr:
            return 0

        # Beta(1, 15) CDF, expressed directly to avoid a statistics dependency.
        weight = 1 - (1 - min(test.games / 2 / positions, 1.0)) ** 15
        projected = test.games * boundary / max(0.1, abs(test.currentllr))
        expected = (1 - weight) * average + weight * projected

        # Unlike Fishtest, an undecided SPRT must not appear to be complete just
        # because its estimated total has fallen below its completed game count.
        return max(2, expected - test.games)

    if test.test_mode == 'SPSA':
        total = 2 * test.spsa_run.iterations * test.spsa_run.pairs_per
    elif test.test_mode in ('GAMES', 'DATAGEN'):
        total = test.max_games
    else:
        return None

    return max(0, total - test.games)


def player_seconds(control):

    # Fishtest's empirical assumptions: 68 moves, 92% of the clock budget used.
    # Verdict stores fixed movetime in milliseconds, and ordinary clocks in seconds.
    if re.fullmatch(r'MT=\d+', control):
        seconds = 68 * int(control[3:]) / 1000
    else:
        match = re.fullmatch(r'(?:(\d+)/)?(\d+(?:\.\d+)?)(?:\+(\d+(?:\.\d+)?))?', control)
        if not match:
            return None # Node/depth limits cannot be converted from a clock budget.
        moves, base, increment = match.groups()
        if moves is not None and int(moves) == 0:
            return None
        seconds = float(base) * (68 / int(moves) if moves else 1)
        seconds += 68 * float(increment or 0)

    return 0.92 * seconds if math.isfinite(seconds) and seconds > 0 else None


def remaining_core_hours(test):

    # Imported lazily because utils and views already import one another.
    from OpenBench.utils import extract_option

    games = remaining_games(test)
    if games == 0:
        return 0.0
    dev_seconds = player_seconds(test.dev_time_control)
    base_seconds = player_seconds(test.base_time_control)
    if games is None or dev_seconds is None or base_seconds is None:
        return None

    # The match runner reserves the larger thread count for thread-odds games.
    threads = max(int(extract_option(test.dev_options, 'Threads') or 1),
                  int(extract_option(test.base_options, 'Threads') or 1))
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

    # Approval is a human decision; only runnable workloads belong in this ETA.
    tests = [test for test in tests if test.approved and not test.finished and not test.deleted]
    if not tests:
        return {'label': 'Queue empty', 'hours': 0, 'detail': 'No approved workloads remain.'}

    ids = {test.id for test in tests}
    threads = sum(machine.info.get('concurrency', 0) for machine in machines if machine.workload in ids)
    if threads <= 0:
        return {'label': 'No workers', 'hours': None,
                'detail': 'An estimate will appear when workers are connected to the approved queue.'}

    work = [remaining_core_hours(test) for test in tests]
    if any(hours is None for hours in work):
        return {'label': 'Unavailable', 'hours': None,
                'detail': 'Some queued workloads cannot be estimated from their time controls or test settings.'}

    hours = sum(work) / threads
    return {'label': format_hours(hours), 'hours': hours,
            'detail': 'Approximate time to clear all approved workloads at the current active thread count. '
                      'Assumes reference-speed workers; SPRT results and available capacity can change the estimate. '
                      'Excludes workloads awaiting approval.'}
