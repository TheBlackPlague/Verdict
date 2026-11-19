# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#                                                                             #
#   OpenBench is a chess engine testing framework authored by Andrew Grant.   #
#   <https://github.com/AndyGrant/OpenBench>           <andrew@grantnet.us>   #
#                                                                             #
#   OpenBench is free software: you can redistribute it and/or modify         #
#   it under the terms of the GNU General Public License as published by      #
#   the Free Software Foundation, either version 3 of the License, or         #
#   (at your option) any later version.                                       #
#                                                                             #
#   OpenBench is distributed in the hope that it will be useful,              #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of            #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the             #
#   GNU General Public License for more details.                              #
#                                                                             #
#   You should have received a copy of the GNU General Public License         #
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.     #
#                                                                             #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

import django
import itertools
import math
import re

from django.utils.html import escape
from django.utils.safestring import mark_safe

import OpenBench.config
import OpenBench.models
import OpenBench.spsa_utils
import OpenBench.stats
import OpenBench.utils

def oneDigitPrecision(value):
    try:
        value = round(value, 1)
        if '.' not in str(value):
            return str(value) + '.0'
        pre, post = str(value).split('.')
        post += '0'
        return pre + '.' + post[0:1]
    except:
        return value

def twoDigitPrecision(value):
    try:
        value = round(value, 2)
        if '.' not in str(value):
            return str(value) + '.00'
        pre, post = str(value).split('.')
        post += '00'
        return pre + '.' + post[0:2]
    except:
        return value

def gitDiffLink(test):

    repo = OpenBench.utils.path_join(*test.dev.source.split('/')[:-2])
    repo = repo.replace('://api.github.com', '://github.com').replace('/repos/', '/')

    if test.test_mode == 'SPSA':
        return OpenBench.utils.path_join(repo, 'compare', test.dev.sha[:8])

    return OpenBench.utils.path_join(repo, 'compare',
        '{0}..{1}'.format(test.base.sha[:8], test.dev.sha[:8]))

def commit_link(workload, branch):

    engine = workload.dev if branch == 'dev' else workload.base
    repo = OpenBench.utils.path_join(*engine.source.split('/')[:-2])
    repo = repo.replace('://api.github.com', '://github.com').replace('/repos/', '/')
    return OpenBench.utils.path_join(repo, 'commit', engine.sha)

def shortStatBlock(test):

    tri_line   = 'Games: %d W: %d L: %d D: %d' % test.as_nwld()
    penta_line = 'Ptnml(0-2): %d, %d, %d, %d, %d' % test.as_penta()

    if test.test_mode == 'SPSA':
        spsa_run = test.spsa_run # Avoid extra database accesses
        statlines = [
            'Tuning %d Parameters' % (spsa_run.parameters.count()),
            '%d/%d Iterations' % (test.games / (2 * spsa_run.pairs_per), spsa_run.iterations),
            '%d/%d Games Played' % (test.games, 2 * spsa_run.iterations * spsa_run.pairs_per)]

    elif test.test_mode == 'SPRT':
        llr_line = 'LLR: %0.2f (%0.2f, %0.2f) [%0.2f, %0.2f]' % (
            test.currentllr, test.lowerllr, test.upperllr, test.elolower, test.eloupper)
        lower, elo, upper = OpenBench.stats.Elo(test.results())
        elo_line = 'Elo: %0.2f +- %0.2f (95%%)' % (elo, max(upper - elo, elo - lower))
        statlines = [llr_line, elo_line, tri_line, penta_line] if test.use_penta else [llr_line, elo_line, tri_line]

    elif test.test_mode == 'GAMES':
        lower, elo, upper = OpenBench.stats.Elo(test.results())
        elo_line = 'Elo: %0.2f +- %0.2f (95%%) [N=%d]' % (elo, max(upper - elo, elo - lower), test.max_games)
        statlines = [elo_line, tri_line, penta_line] if test.use_penta else [elo_line, tri_line]

    elif test.test_mode == 'DATAGEN':
        status_line = 'Generated %d/%d Games' % (test.games, test.max_games)
        lower, elo, upper = OpenBench.stats.Elo(test.results())
        elo_line = 'Elo: %0.2f +- %0.2f (95%%) [N=%d]' % (elo, max(upper - elo, elo - lower), test.max_games)
        statlines = [status_line, elo_line, penta_line] if test.use_penta else [status_line, elo_line, tri_line]

    return '\n'.join(statlines)

def compact_stat_blocks(test):
    lines = shortStatBlock(test).splitlines()
    if test.test_mode == 'SPSA':
        return {'result': '\n'.join(lines[:-1]), 'games': lines[-1]}
    counts = ('Games:', 'Ptnml(0-2):', 'Generated ')
    return {'result': '\n'.join(line for line in lines if not line.startswith(counts)),
            'games': '\n'.join(line for line in lines if line.startswith(counts))}


def longStatBlock(test):

    assert test.test_mode != 'SPSA'

    threads     = int(OpenBench.utils.extract_option(test.dev_options, 'Threads'))
    hashmb      = int(OpenBench.utils.extract_option(test.dev_options, 'Hash'))
    timecontrol = test.dev_time_control + ['s', '']['=' in test.dev_time_control]
    type_text   = 'SPRT' if test.test_mode == 'SPRT' else 'Conf'

    lower, elo, upper = OpenBench.stats.Elo(test.results())

    lines = [
        'Elo   | %0.2f +- %0.2f (95%%)' % (elo, max(upper - elo, elo - lower)),
        '%-5s | %s Threads=%d Hash=%dMB' % (type_text, timecontrol, threads, hashmb),
    ]

    if test.test_mode == 'SPRT':
        lines.append('LLR   | %0.2f (%0.2f, %0.2f) [%0.2f, %0.2f]' % (
            test.currentllr, test.lowerllr, test.upperllr, test.elolower, test.eloupper))

    lines.append('Games | N: %d W: %d L: %d D: %d' % test.as_nwld())

    if test.use_penta:
        lines.append('Penta | [%d, %d, %d, %d, %d]' % test.as_penta())

    return '\n'.join(lines)

def testResultColour(test):

    # Jewel uses outcome colors, including green for negative-bound passes.
    if test.deleted: return 'deleted'
    if test.passed: return 'green'
    if test.failed:
        if test.wins >= test.losses: return 'yellow'
        return 'red'
    return ''

def sumAttributes(iterable, attribute):
    try: return sum([getattr(f, attribute) for f in iterable])
    except: return 0

def insertCommas(value):
    return '{:,}'.format(int(value))

def prettyName(name):
    if re.search('^[0-9a-fA-F]{40}$', name):
        return name[:16].upper()
    return name

def prettyDevName(test):

    # If engines are different, use the base name + branch
    if test.dev_engine != test.base_engine:
        return '[%s] %s' % (test.base_engine, test.base.name)

    # If testing different Networks, possibly use the Network name
    if test.dev.name == test.base.name and test.dev_netname != '':

        # Nets match as well, so revert back to the branch name
        if test.dev_network == test.base_network:
            return prettyName(test.dev.name)

        # Use the network's name, if we still have it saved
        try: return OpenBench.models.Network.objects.get(sha256=test.dev_network).name
        except: return test.dev_netname # File has since been deleted ?

    return prettyName(test.dev.name)

def testIdToPrettyName(test_id):
    return prettyName(OpenBench.models.Test.objects.get(id=test_id).dev.name)

def testIdToTimeControl(test_id):
    return OpenBench.models.Test.objects.get(id=test_id).dev_time_control

def cpuflagsBlock(machine, N=8):

    reported = []
    flags    = machine.info['cpu_flags']

    general_flags   = ['BMI2', 'POPCNT']
    broad_avx_flags = ['AVX2', 'AVX', 'SSE42', 'SSE41', 'SSSE3']

    for flag in general_flags:
        if flag in flags:
            reported.append(flag)
            break

    for flag in broad_avx_flags:
        if flag in flags:
            reported.append(flag)
            break

    for flag in flags:
        if flag not in general_flags and flag not in broad_avx_flags:
            reported.append(flag)

    return ' '.join(reported)

def compilerBlock(machine):
    string = ''
    for engine, info in machine.info['compilers'].items():
        string += '%-16s %-8s (%s)\n' % (engine, info[0], info[1])
    return string

def removePrefix(value, prefix):
    return value.removeprefix(prefix)

def machine_name(machine_id):
    try:
        machine = OpenBench.models.Machine.objects.get(id=machine_id)
        return machine.info['machine_name']
    except: return 'None'


register = django.template.Library()
register.filter('oneDigitPrecision', oneDigitPrecision)
register.filter('twoDigitPrecision', twoDigitPrecision)
register.filter('gitDiffLink', gitDiffLink)
register.filter('shortStatBlock', shortStatBlock)
register.filter('longStatBlock', longStatBlock)
register.filter('testResultColour', testResultColour)
register.filter('sumAttributes', sumAttributes)
register.filter('insertCommas', insertCommas)
register.filter('prettyName', prettyName)
register.filter('prettyDevName', prettyDevName)
register.filter('testIdToPrettyName', testIdToPrettyName)
register.filter('testIdToTimeControl', testIdToTimeControl)
register.filter('cpuflagsBlock', cpuflagsBlock)
register.filter('compilerBlock', compilerBlock)
register.filter('removePrefix', removePrefix)
register.filter('machine_name', machine_name)

def book_download_link(workload):
    if (book := OpenBench.models.Book.objects.filter(name=workload.book_name).first()):
        return book.source

def network_download_link(workload, branch):

    assert branch in [ 'dev', 'base' ]

    sha    = workload.dev_network if branch == 'dev' else workload.base_network
    engine = workload.dev_engine  if branch == 'dev' else workload.base_engine

    # Network could have been deleted after this workload was finished
    if (network := OpenBench.models.Network.objects.filter(sha256=sha, engine=engine).first()):
        return '/networks/%s/download/%s/' % (engine, sha)

    return '/networks/%s/' % (engine)

def workload_url(workload):

    # Might be a workload id
    if type(workload) == int:
        workload = OpenBench.models.Test.objects.get(id=workload)

    # Differentiate between Tunes, Datagen, and regular Tests
    mapping = { 'SPSA' : 'tune', 'DATAGEN' : 'datagen' }
    return '/%s/%d/' % (mapping.get(workload.test_mode, 'test'), workload.id)

def workload_pretty_name(workload):

    # Might be a workload id
    if type(workload) == int:
        workload = OpenBench.models.Test.objects.get(id=workload)

    # Convert commit sha's to just the first 16 characters
    if re.search('^[0-9a-fA-F]{40}$', workload.dev.name):
        return workload.dev.name[:16].lower()

    return workload.dev.name

def git_diff_text(workload, N=24):

    dev_name = workload.dev.name
    dev_name = dev_name[:N] + '...' if len(dev_name) > N else dev_name

    base_name = workload.base.name
    base_name = base_name[:N] + '...' if len(base_name) > N else base_name

    return '%s vs %s' % (dev_name, base_name)


def test_is_smp_odds(test):
    dev_threads  = int(OpenBench.utils.extract_option(test.dev_options , 'Threads'))
    base_threads = int(OpenBench.utils.extract_option(test.base_options, 'Threads'))
    return dev_threads != base_threads

def test_is_time_odds(test):
    return test.dev_time_control != test.base_time_control

def test_is_fischer(test):
    return 'FRC' in test.book_name.upper() or '960' in test.book_name.upper()

register.filter('book_download_link', book_download_link)
register.filter('network_download_link', network_download_link)

register.filter('workload_url', workload_url)
register.filter('workload_pretty_name', workload_pretty_name)

register.filter('git_diff_text', git_diff_text)
register.filter('commit_link', commit_link)

register.filter('test_is_smp_odds'  , test_is_smp_odds  )
register.filter('test_is_time_odds' , test_is_time_odds )
register.filter('test_is_fischer'   , test_is_fischer   )


@register.filter
def next(iterable, index):
    try: return iterable[int(index) + 1]
    except: return None

@register.filter
def previous(iterable, index):
    try: return iterable[int(index) - 1]
    except: return None


# Cache the interval on this request's model instance; multiple cards share it.
def _interface_elo(workload):
    if not hasattr(workload, '_interface_elo'):
        workload._interface_elo = OpenBench.stats.Elo(workload.results())
    return workload._interface_elo


@register.filter
def elo_estimate(workload):
    if not workload.games:
        return '—'
    return '%+.2f' % _interface_elo(workload)[1]


@register.filter
def elo_interval(workload):
    if not workload.games:
        return 'Waiting for games'
    lower, elo, upper = _interface_elo(workload)
    return '± %.2f at 95%% confidence' % max(upper - elo, elo - lower)


@register.filter
def llr_position(workload):
    width = workload.upperllr - workload.lowerllr
    return '%.2f' % (max(0, min(100, 100 * (workload.currentllr - workload.lowerllr) / width)) if width else 50)


@register.filter
def workload_target(workload):
    if workload.test_mode == 'SPSA':
        return workload.spsa_run.iterations * workload.spsa_run.pairs_per * 2
    return workload.max_games


@register.filter
def workload_progress(workload):
    target = workload_target(workload)
    return '%.1f' % (min(100, 100 * workload.games / target) if target else 0)


@register.filter
def tuning_iterations(workload):
    games_per_iteration = workload.spsa_run.pairs_per * 2
    return int(workload.games / games_per_iteration) if games_per_iteration else 0


@register.filter
def finished_label(workload):
    target = workload.max_games
    if workload.test_mode == 'SPSA':
        target = workload.spsa_run.iterations * workload.spsa_run.pairs_per * 2
    return 'Finished' if target and workload.games >= target else 'Stopped'


@register.filter
def bounded_llr(workload):
    return max(workload.lowerllr, min(workload.upperllr, workload.currentllr))


LIST_ELO_RANGES = (10, 20, 50, 100, 200, 500)

def _percent(value):
    return round(max(0.0, min(100.0, value)), 2)

def _signed(value, fmt):
    text = fmt % abs(value)
    return text if not float(text) else ('+' if value > 0 else '−') + text

def _elo_and_interval(workload):
    if not workload.games:
        return 0.0, 0.0
    lower, elo, upper = _interface_elo(workload)
    return elo, max(upper - elo, elo - lower)


@register.filter
def llr_zero(workload):
    width = workload.upperllr - workload.lowerllr
    return _percent(100 * -workload.lowerllr / width) if width else 50.0


@register.filter
def llr_ticks(workload):

    lower, upper = workload.lowerllr, workload.upperllr
    if upper <= lower:
        return []

    inside = [k for k in range(math.ceil(lower), math.floor(upper) + 1)
              if lower < k < upper and (k == 0 or (k - lower >= 0.5 and upper - k >= 0.5))]

    def tick(value, fmt, bound):
        return dict(value=value, label=_signed(value, fmt), pos=_percent(100 * (value - lower) / (upper - lower)),
                    bound=bound)
    return [tick(lower, '%.2f', True)] + [tick(float(k), '%d', False) for k in inside] + [tick(upper, '%.2f', True)]


@register.filter
def elo_card_scale(workload):

    sprt = workload.test_mode == 'SPRT'
    elo, interval = _elo_and_interval(workload)
    if workload.games:
        values = [elo - interval, elo + interval] + ([workload.elolower, workload.eloupper] if sprt else [])
    else:
        values = [workload.elolower, workload.eloupper] if sprt else [-1.0, 1.0]

    low, high = min(values), max(values)
    pad = max(0.5, 0.15 * (high - low))
    low, high = low - pad, high + pad

    exponent = math.floor(math.log10((high - low) / 6))
    for step in (m * 10 ** e for e in itertools.count(exponent) for m in (1, 2, 5)):
        first, last = math.floor(low / step + 1e-9), math.ceil(high / step - 1e-9)
        if last - first <= 6:
            break

    scale = dict(min=round(first * step, 6), max=round(last * step, 6), step=round(step, 6), ticks=[])
    for half in range(2 * first, 2 * last + 1):
        value, minor = round(half * step / 2, 6), half % 2 == 1
        label = '' if minor else _signed(value, '%g')
        scale['ticks'].append(dict(value=value, label=label, pos=elo_pos(value, scale), minor=minor))

    has_games = bool(workload.games)
    scale['lo_pos']   = elo_pos(elo - interval, scale) if has_games else None
    scale['est_pos']  = elo_pos(elo, scale) if has_games else None
    scale['hi_pos']   = elo_pos(elo + interval, scale) if has_games else None
    scale['elo0_pos'] = elo_pos(workload.elolower, scale) if sprt else None
    scale['elo1_pos'] = elo_pos(workload.eloupper, scale) if sprt else None
    return scale


@register.filter
def elo_pos(value, scale):
    width = scale['max'] - scale['min']
    return _percent(100 * (float(value) - scale['min']) / width) if width else 50.0


@register.filter
def list_elo_range(tests):

    largest = max((max(abs(test.elolower), abs(test.eloupper)) for test in tests if test.test_mode == 'SPRT'),
                  default=0.0)
    for R in LIST_ELO_RANGES:
        if R >= 1.1 * largest:
            return R
    return LIST_ELO_RANGES[-1]


@register.filter
def ci_marks(workload, R):

    R = float(R)
    elo, interval = _elo_and_interval(workload)
    position = lambda value: _percent(100 * (value + R) / (2 * R))
    return dict(lo=position(elo - interval), est=position(elo), hi=position(elo + interval),
                cap_lo=elo - interval < -R, cap_hi=elo + interval > R)


@register.filter
def wdl_widths(workload):
    total = workload.wins + workload.draws + workload.losses
    if not total:
        return dict(w=0.0, d=0.0, l=0.0)
    w, d = round(100 * workload.wins / total, 2), round(100 * workload.draws / total, 2)
    return dict(w=w, d=d, l=round(max(0.0, 100 - w - d), 2))


@register.filter
def penta_heights(workload):
    penta = workload.as_penta()
    tallest = max(penta)
    return [round(100 * count / tallest, 2) if tallest else 0.0 for count in penta]


@register.filter
def row_readings(workload):

    elo, interval = _elo_and_interval(workload)
    nwld = workload.as_nwld()
    lines = dict(
        llr='LLR: %0.2f (%0.2f, %0.2f) [%0.2f, %0.2f]' % (
            workload.currentllr, workload.lowerllr, workload.upperllr, workload.elolower, workload.eloupper),
        elo='Elo: %0.2f +- %0.2f (95%%)' % (elo, interval),
        games='Games: %d W: %d L: %d D: %d' % nwld,
        wld='W: %d L: %d D: %d' % nwld[1:],
        penta='Ptnml(0-2): %d, %d, %d, %d, %d' % workload.as_penta(),
        generated='Generated %d/%d Games' % (workload.games, workload.max_games),
    )
    if workload.test_mode in ('GAMES', 'DATAGEN'):
        lines['elo'] += ' [N=%d]' % workload.max_games
    if workload.test_mode == 'SPSA':
        spsa_run = workload.spsa_run
        lines['tuning'] = 'Tuning %d Parameters' % spsa_run.parameters.count()
        lines['iterations'] = '%d/%d Iterations' % (workload.games / (2 * spsa_run.pairs_per), spsa_run.iterations)
        lines['played'] = '%d/%d Games Played' % (workload.games, 2 * spsa_run.iterations * spsa_run.pairs_per)

    llr = workload.currentllr if workload.games else 0.0
    lines.update(
        llr_figure=_signed(llr, '%.2f'), elo_figure=_signed(elo, '%.2f'),
        interval_figure='%.2f' % interval,
        elo_tone='pos' if elo - interval > 0 else 'neg' if elo + interval < 0 else '',
    )
    return lines


@register.filter
def fleet_axis(active_groups):

    tests = [test for group in active_groups for test in group['tests'] if test.test_mode == 'SPRT']
    dots = [dict(pos=float(llr_position(test)), neg=test.currentllr < 0) for test in tests]
    shared = len({(test.lowerllr, test.upperllr) for test in tests}) == 1
    return dict(dots=dots, zero=llr_zero(tests[0]) if shared else None)


@register.filter
def status_key(workload):

    colour = testResultColour(workload)
    if colour:
        return { 'deleted' : 'deleted', 'green' : 'passed', 'yellow' : 'yellow', 'red' : 'failed' }[colour]
    if workload.finished:
        return 'finished' if finished_label(workload) == 'Finished' else 'stopped'
    return 'running' if workload.approved else 'pending'


@register.filter
def status_word(key):
    return {'running': 'Active', 'yellow': 'Failed'}.get(key, key.capitalize())


@register.filter
def band_tone(workload):

    status = status_key(workload)
    if status in ('passed', 'failed', 'yellow'):
        return { 'passed' : 'pass', 'failed' : 'fail', 'yellow' : 'warn' }[status]
    if status == 'running' and workload.test_mode == 'SPRT' and workload.games and workload.currentllr:
        return 'fail' if workload.currentllr < 0 else 'pass'
    return 'neutral'


def _viewer_profile(request):
    if not hasattr(request, '_viewer_profile'):
        user = request.user
        request._viewer_profile = OpenBench.models.Profile.objects.filter(user=user).first() \
            if user.is_authenticated else None
    return request._viewer_profile


@register.filter
def workload_actions(workload, request):

    profile   = _viewer_profile(request)
    approver  = bool(profile and profile.approver)
    author    = bool(profile and request.user.username == workload.author)
    superuser = request.user.is_superuser
    moderator = approver or author

    def action(key, label, enabled, danger=False):
        href = '/%s/%d/%s' % (workload.workload_type_str(), workload.id, key.upper()) if enabled else None
        return dict(key=key, label=label, href=href, enabled=bool(enabled), danger=danger)

    actions = [action('approve', 'Approve', not workload.approved and ((approver and not author) or superuser))]
    if workload.finished:
        actions.append(action('restart', 'Restart', not workload.passed and not workload.failed and moderator))
    else:
        actions.append(action('stop', 'Stop', moderator))
    if workload.deleted:
        actions.append(action('restore', 'Restore', moderator))
    else:
        actions.append(action('delete', 'Delete', moderator, danger=True))
    return actions

register.filter(compact_stat_blocks)


_NAV_PREFIXED = ('index', 'greens', 'machines', 'networks', 'events', 'errors')

@register.filter
def nav_current(path, key):
    path = path.strip('/') or 'index'
    return ((key == 'index' and re.fullmatch(r'(test|tune|datagen)/\d+', path) is not None)
        or (key == 'errors' and re.fullmatch(r'event/\d+', path) is not None)
        or path == key
        or (key in _NAV_PREFIXED and path.startswith(key + '/')))


ICONS = {
    'tests'    : '<path d="M9 3h6M10 3v6.2l-5.6 9.6A1.5 1.5 0 0 0 5.7 21h12.6a1.5 1.5 0 0 0 1.3-2.2L14 9.2V3"/><path d="M7.2 15h9.6"/>',
    'passed'   : '<circle cx="12" cy="12" r="9"/><path d="m8.4 12.2 2.5 2.5 4.8-5.2"/>',
    'search'   : '<circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/>',
    'machines' : '<rect x="3.5" y="4" width="17" height="7" rx="2"/><rect x="3.5" y="13" width="17" height="7" rx="2"/><path d="M7.5 7.5h.01M7.5 16.5h.01"/>',
    'networks' : '<circle cx="12" cy="5" r="2"/><circle cx="5" cy="18.5" r="2"/><circle cx="19" cy="18.5" r="2"/><circle cx="12" cy="13" r="2"/><path d="M12 7v4M10.4 14.2l-3.8 3M13.6 14.2l3.8 3"/>',
    'users'    : '<path d="M15.5 20v-1.4a3.6 3.6 0 0 0-3.6-3.6H7.1a3.6 3.6 0 0 0-3.6 3.6V20"/><circle cx="9.5" cy="8" r="3.5"/><path d="M20.5 20v-1.4a3.6 3.6 0 0 0-2.6-3.45M15 4.6a3.5 3.5 0 0 1 0 6.8"/>',
    'activity' : '<path d="M3 12h4l3-7.5 4 15 3-7.5h4"/>',
    'errors'   : '<path d="M10.3 4.3 2.7 17.6A2 2 0 0 0 4.4 20.5h15.2a2 2 0 0 0 1.7-2.9L13.7 4.3a2 2 0 0 0-3.4 0Z"/><path d="M12 9.5v4M12 17h.01"/>',
    'manage'   : '<path d="M4 7h8.5M17.5 7H20M4 17h2.5M11.5 17H20"/><circle cx="15" cy="7" r="2.5"/><circle cx="9" cy="17" r="2.5"/>',
    'plus'     : '<path d="M12 5v14M5 12h14"/>',
    'compare'  : '<circle cx="6" cy="6" r="2.4"/><circle cx="18" cy="18" r="2.4"/><path d="M13 6h3a2 2 0 0 1 2 2v7.6M11 18H8a2 2 0 0 1-2-2V8.4"/><path d="m15 3.5-2.5 2.5L15 8.5M9 20.5l2.5-2.5L9 15.5"/>',
    'refresh'  : '<path d="M19.5 12a7.5 7.5 0 1 1-2.2-5.3"/><path d="M19.5 4.5v4.2h-4.2"/>',
    'back'     : '<path d="m14.5 18-6-6 6-6"/>',
    'down'     : '<path d="m6.5 9.5 5.5 5.5 5.5-5.5"/>',
    'chev'     : '<path d="m9.5 6 6 6-6 6"/>',
    'copy'     : '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2"/><path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5"/>',
    'stop'     : '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    'trash'    : '<path d="M4.5 7h15M10 11v6M14 11v6M6.5 7l.9 11.6a2 2 0 0 0 2 1.9h5.2a2 2 0 0 0 2-1.9L17.5 7M9.5 7V4.5h5V7"/>',
    'check'    : '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    'logout'   : '<path d="M9.5 20H6.5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h3"/><path d="m15.5 16 4-4-4-4M19.5 12h-10"/>',
    'more'     : '<circle cx="5.5" cy="12" r="1.4" fill="currentColor"/><circle cx="12" cy="12" r="1.4" fill="currentColor"/><circle cx="18.5" cy="12" r="1.4" fill="currentColor"/>',
    'close'    : '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    'tune'     : '<path d="M6 4v16M12 4v16M18 4v16"/><rect x="4" y="13" width="4" height="3" rx="1"/><rect x="10" y="7" width="4" height="3" rx="1"/><rect x="16" y="11" width="4" height="3" rx="1"/>',
    'data'     : '<ellipse cx="12" cy="6" rx="7.5" ry="2.8"/><path d="M4.5 6v12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8V6M4.5 12c0 1.5 3.4 2.8 7.5 2.8s7.5-1.3 7.5-2.8"/>',
    'upload'   : '<path d="M12 15V4.5M7.5 9 12 4.5 16.5 9"/><path d="M4.5 15v3a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-3"/>',
    'flask'    : '<path d="M9 3h6M10 3v6.2l-5.6 9.6A1.5 1.5 0 0 0 5.7 21h12.6a1.5 1.5 0 0 0 1.3-2.2L14 9.2V3"/>',
    'login'    : '<path d="M14.5 4H17.5a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3"/><path d="m10 16 4-4-4-4M14 12H4.5"/>',
    'person'   : '<circle cx="12" cy="8.5" r="3.8"/><path d="M5 20a7 7 0 0 1 14 0"/>',
    'download' : '<path d="M12 4.5v10M7.5 10.5 12 15l4.5-4.5M5 19.5h14"/>',
    'restart'  : '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4.5v4.2h4.2"/>',
}

@register.simple_tag
def icon(name, cls=''):
    return mark_safe('<svg class="ico%s" viewBox="0 0 24 24" aria-hidden="true">%s</svg>' % (
        ' ' + escape(cls) if cls else '', ICONS[name]))
