import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase as PlainTestCase
from unittest.mock import Mock, patch
import zipfile

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from Client import client
from OpenBench.config import OPENBENCH_CONFIG
from OpenBench.models import Profile, Test
from OpenBench.templatetags.mytags import shortStatBlock
from OpenBench.utils import TimeControl


ROOT = Path(__file__).resolve().parents[1]


class ClientDownloadTests(PlainTestCase):
    def download(self, root_name, include_worker=True):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr(root_name + '/Client/client.py', 'replacement bootstrap')
            if include_worker:
                output.writestr(root_name + '/Client/worker.py', 'updated worker')
                output.writestr(root_name + '/Client/isa_detector.py', 'updated ISA detector')

        args = SimpleNamespace(username='test', password='test', server='https://example.test')
        response = Mock(status_code=200, content=archive.getvalue())
        version = Mock()
        version.json.return_value = {
            'client_repo_url': 'https://github.com/TheBlackPlague/Verdict',
            'client_repo_ref': 'sync-with-upstream',
        }
        with tempfile.TemporaryDirectory() as directory:
            bootstrap = Path(directory, 'client.py')
            bootstrap.write_text('original bootstrap')
            with patch.object(client.requests, 'post', return_value=version), \
                 patch.object(client.requests, 'get', return_value=response), \
                 patch.object(client.os, 'getcwd', return_value=directory):
                client.download_client_files(args)
            self.assertEqual(bootstrap.read_text(), 'original bootstrap')
            self.assertEqual(Path(directory, 'worker.py').read_text(), 'updated worker')
            self.assertEqual(Path(directory, 'isa_detector.py').read_text(), 'updated ISA detector')

    def test_fork_and_upstream_archive_names(self):
        for root in ['Verdict-sync-with-upstream', 'OpenBench-master', 'Verdict-0123456789abcdef']:
            with self.subTest(root=root):
                self.download(root)

    def test_missing_worker_is_reported_instead_of_silent_success(self):
        with self.assertRaisesRegex(Exception, 'Unable to extract'):
            self.download('Verdict-sync-with-upstream', include_worker=False)


class VerdictConfigurationTests(SimpleTestCase):
    def test_presets_reference_available_books_and_valid_time_controls(self):
        for engine, config in OPENBENCH_CONFIG['engines'].items():
            for kind in ['test_presets', 'tune_presets', 'datagen_presets']:
                for name, preset in config[kind].items():
                    with self.subTest(engine=engine, kind=kind, preset=name):
                        if 'book_name' in preset:
                            self.assertIn(preset['book_name'], OPENBENCH_CONFIG['books'])
                        for key, value in preset.items():
                            if key.endswith('_time_control'):
                                TimeControl.parse(value)

    def test_client_protocol_matches_server(self):
        import ast
        module = ast.parse((ROOT / 'Client/worker.py').read_text())
        version = next(node.value.value for node in module.body
                       if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'CLIENT_VERSION'
                               for target in node.targets))
        self.assertEqual(version, OPENBENCH_CONFIG['client_version'])
        self.assertEqual(OPENBENCH_CONFIG['client_repo_ref'], 'sync-with-upstream')

    def test_sprt_elo_is_second_line_for_both_result_formats(self):
        for penta in [True, False]:
            for games in [0, 200]:
                with self.subTest(penta=penta, games=games):
                    workload = Test(test_mode='SPRT', use_penta=penta, games=games,
                                    wins=games // 4, losses=games // 4, draws=games // 2,
                                    LL=games // 8, DD=games // 4, WW=games // 8)
                    lines = shortStatBlock(workload).splitlines()
                    self.assertTrue(lines[0].startswith('LLR:'))
                    self.assertTrue(lines[1].startswith('Elo:'))
                    self.assertNotIn('[N=', lines[1])
                    self.assertTrue(lines[2].startswith('Games:'))
                    self.assertEqual(len(lines), 4 if penta else 3)


class VerdictPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('reviewer', password='test-only-password')
        Profile.objects.create(user=cls.user, enabled=True)

    def test_public_pages_render_verdict(self):
        for url in ['/', '/index/', '/search/', '/users/', '/machines/', '/networks/', '/register/']:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, '<title>Verdict</title>')
                self.assertNotContains(response, 'OpenBench&nbsp;Testing&nbsp;Framework')
                self.assertNotContains(response, 'discord.gg/9MVg7fBTpM')

    def test_workload_forms_and_profile(self):
        self.client.force_login(self.user)
        for url in ['/test/new/', '/tune/new/', '/datagen/new/', '/profile/']:
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), '<title>Verdict</title>')
        self.assertContains(self.client.get('/profile/'), 'Confirm New Password')

    def test_worker_download_configuration(self):
        response = self.client.post('/clientVersionRef/', {'username': 'reviewer', 'password': 'test-only-password'})
        self.assertEqual(response.json()['client_repo_url'], 'https://github.com/TheBlackPlague/Verdict')
        self.assertEqual(response.json()['client_repo_ref'], 'sync-with-upstream')
        runner = self.client.post('/clientMatchRunnerVersionRef/', {'username': 'reviewer', 'password': 'test-only-password'})
        self.assertEqual(runner.json()['fastchess_min_version'], OPENBENCH_CONFIG['fastchess_min_version'])
