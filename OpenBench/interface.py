"""Presentation context and explicitly scoped, read-only live fragments."""

import hashlib
import json

from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.utils.cache import patch_vary_headers


LIVE_REGIONS = {
    'index.html': {'overview-live': 'Blocks/overview.html'},
    'machines.html': {'machines-live': 'Blocks/machines.html'},
    'workload.html': {
        'workload-metrics-live': 'Blocks/workload_metrics.html',
        'workload-actions-live': 'Blocks/workload_actions.html',
        'workload-statblock-live': 'Blocks/workload_statblock.html',
    },
}

PAGE_TITLES = {
    'index.html': ('Testing', 'Overview'),
    'search.html': ('Testing', 'Search workloads'),
    'machines.html': ('Resources', 'Machines'),
    'machine.html': ('Resources', 'Machine details'),
    'users.html': ('Community', 'Contributors'),
    'events.html': ('Server', 'Activity'),
    'errors.html': ('Server', 'Errors'),
    'event.html': ('Server', 'Event log'),
    'networks.html': ('Resources', 'Neural networks'),
    'network.html': ('Resources', 'Network details'),
    'uploadnet.html': ('Resources', 'Upload network'),
    'profile.html': ('Account', 'Profile & preferences'),
    'login.html': ('Account', 'Welcome back'),
    'register.html': ('Account', 'Create an account'),
}


def is_live_request(request):
    return request.method == 'GET' and request.headers.get('X-Verdict-Live') == '1'


def presentation_context(template, data):
    section, title = PAGE_TITLES.get(template, ('Testing', 'Verdict'))
    if template == 'index.html':
        url = data.get('paging', {}).get('url', '')
        if url == 'greens':
            title = 'Passed tests'
        elif url.startswith('user/'):
            title = url.split('/', 1)[1] + '’s workloads'
    elif template == 'create_workload.html':
        title = {'TEST': 'Create a test', 'TUNE': 'Create a tune',
                 'DATAGEN': 'Generate data'}.get(data.get('workload'), 'Create a workload')
    elif template == 'workload.html':
        workload = data['workload']
        title = workload.dev.name
        section = '%s / #%s' % (workload.workload_type_str().capitalize(), workload.id)
    elif template == 'machine.html':
        title = data['machine'].info.get('machine_name') or 'Machine details'
    return {'page_section': section, 'page_title': title,
            'live_regions': list(LIVE_REGIONS.get(template, {}))}


def live_response(request, template, data):
    regions = LIVE_REGIONS.get(template)
    if not regions:
        return JsonResponse({'error': 'Live updates are not available for this page.'}, status=400)
    body = {'regions': {key: render_to_string('OpenBench/' + partial, data, request=request)
                        for key, partial in regions.items()}}
    etag = '"' + hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() + '"'
    response = HttpResponse(status=304) if request.headers.get('If-None-Match') == etag else JsonResponse(body)
    response['ETag'] = etag
    response['Cache-Control'] = 'private, no-cache'
    patch_vary_headers(response, ['Cookie', 'X-Verdict-Live'])
    return response
