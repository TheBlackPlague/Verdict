import importlib.util
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from unittest import TestCase, skipUnless
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


class ServerEntrypointTests(TestCase):
    def test_missing_secret_fails_before_startup(self):
        env = {key: value for key, value in os.environ.items() if key != 'VERDICT_SECRET_KEY'}
        result = subprocess.run(['sh', 'Docker/run-server.sh', 'gunicorn'], cwd=ROOT,
                                env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('VERDICT_SECRET_KEY', result.stderr)

    @skipUnless(importlib.util.find_spec('gunicorn') and importlib.util.find_spec('whitenoise'),
                'Install Docker/server-requirements.txt for the server integration test')
    def test_server_initializes_serves_static_and_preserves_data_on_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            env = dict(os.environ,
                       PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'],
                       VERDICT_CONTAINER='1', VERDICT_DEBUG='0', VERDICT_DISABLE_WATCHER='0',
                       VERDICT_SECRET_KEY='integration-test-only-secret',
                       VERDICT_DATA_DIR=directory, VERDICT_STATIC_ROOT=str(data / 'staticfiles'),
                       VERDICT_WATCHER_LOCK=str(data / 'watcher.lock'),
                       VERDICT_ALLOWED_HOSTS='127.0.0.1', VERDICT_TRUST_PROXY='0',
                       VERDICT_SECURE_COOKIES='0')
            command = ['sh', 'Docker/run-server.sh', 'gunicorn', 'OpenSite.wsgi:application',
                       '--bind', '127.0.0.1:%d' % port, '--workers', '1', '--threads', '4',
                       '--graceful-timeout', '10', '--access-logfile', '-']
            url = 'http://127.0.0.1:%d' % port
            for iteration in range(2):
                log_path = data / ('server-%d.log' % iteration)
                with log_path.open('w') as log:
                    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=log)
                    try:
                        deadline = time.monotonic() + 30
                        while True:
                            try:
                                with urlopen(url + '/login/', timeout=1) as response:
                                    self.assertIn(b'Verdict', response.read())
                                break
                            except (URLError, TimeoutError):
                                if process.poll() is not None or time.monotonic() > deadline:
                                    self.fail(log_path.read_text())
                                time.sleep(0.1)
                        with urlopen(url + '/static/style.css', timeout=3) as response:
                            self.assertEqual(response.status, 200)
                            self.assertIn('text/css', response.headers['Content-Type'])
                        with sqlite3.connect(data / 'db.sqlite3') as database:
                            if iteration == 0:
                                database.execute('INSERT INTO OpenBench_engine (name, source, sha, bench) VALUES (?, ?, ?, ?)',
                                                 ('persistent-engine', 'https://example.test', 'a' * 40, 123))
                                (data / 'Media/private-marker').write_text('persistent media')
                            else:
                                self.assertEqual(database.execute('SELECT bench FROM OpenBench_engine WHERE name=?',
                                                                  ('persistent-engine',)).fetchone(), (123,))
                                self.assertEqual((data / 'Media/private-marker').read_text(), 'persistent media')
                        # Uploaded media must not be exposed by the static-file server.
                        with self.assertRaises(HTTPError) as error:
                            urlopen(url + '/Media/private-marker', timeout=3)
                        self.assertEqual(error.exception.code, 404)
                    finally:
                        process.terminate()
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                            self.fail('Server did not stop gracefully')
                self.assertEqual(process.returncode, 0, log_path.read_text())
                self.assertNotIn('no such table', log_path.read_text())
                self.assertFalse((data / 'watcher.lock').exists())
