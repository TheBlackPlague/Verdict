# SPRT duration follows Fishtest: https://github.com/official-stockfish/fishtest/blob/master/server/fishtest/static/js/sprt.js

import math
import re

from OpenBench.stats import bayeselo_to_proba, proba_to_bayeselo


def remaining_games(test):

    if test.finished or test.deleted:
        return 0

    if test.test_mode == 'SPRT':
        return sprt_remaining_games(test)

    if test.test_mode == 'SPSA':
        total = 2 * test.spsa_run.iterations * test.spsa_run.pairs_per
    elif test.test_mode in ('GAMES', 'DATAGEN'):
        total = test.max_games
    else:
        return None

    return max(0, total - test.games)


def sprt_remaining_games(test):

    lower, upper, llr = test.lowerllr, test.upperllr, test.currentllr
    if not all(math.isfinite(x) for x in (lower, upper, llr, test.elolower, test.eloupper)):
        return None
    if lower >= upper or test.elolower >= test.eloupper or test.games < 0:
        return None
    if llr <= lower or llr >= upper:
        return 0

    drift = llr / test.games if test.games else 0.0
    if test.use_penta:
        variance = ((test.eloupper - test.elolower) * math.log(10) / 800) ** 2
    elif test.use_tri:
        results = test.as_tri()
        if any(x <= 0 for x in results):
            return None
        pdf = [x / sum(results) for x in results]
        _, draw_elo = proba_to_bayeselo(*pdf)
        try:
            pdf0 = bayeselo_to_proba(test.elolower, draw_elo)
            pdf1 = bayeselo_to_proba(test.eloupper, draw_elo)
            jumps = [math.log(p1 / p0) for p0, p1 in zip(pdf0, pdf1)]
        except (ValueError, ZeroDivisionError, OverflowError):
            return None
        mean = sum(p * jump for p, jump in zip(pdf, jumps))
        variance = sum(p * (jump - mean) ** 2 for p, jump in zip(pdf, jumps))
    else:
        return None

    if not math.isfinite(variance) or variance <= 0:
        return None

    lower, upper = lower - llr, upper - llr
    if drift < 0:
        lower, upper, drift = -upper, -lower, -drift
    h = 2 * drift / variance
    if abs(h * (upper - lower)) < 1e-6:
        return -lower * upper / variance

    # Shift the absorbing bounds to the current LLR and avoid positive exponents.
    passing = math.expm1(h * lower) / math.expm1(h * (lower - upper))
    games = (upper * passing + lower * (1 - passing)) / drift
    return max(0.0, games) if math.isfinite(games) else None


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

    hours = sum(work) / (threads * 0.5)
    return {'label': format_hours(hours), 'hours': hours,
            'detail': 'Estimated completion time of all workloads.'}
