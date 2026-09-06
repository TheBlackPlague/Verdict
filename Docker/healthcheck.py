import os
from urllib.request import Request, urlopen


host = os.environ.get('VERDICT_ALLOWED_HOSTS', 'localhost').split(',')[0].strip().lstrip('.')
if not host or host == '*':
    host = 'localhost'
request = Request('http://127.0.0.1:8000/login/', headers={'Host': host})
with urlopen(request, timeout=3) as response:
    if response.status != 200:
        raise SystemExit(1)
