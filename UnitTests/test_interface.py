import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from OpenBench.config import OPENBENCH_CONFIG
from OpenBench.models import Engine, Machine, Network, Profile, Result, SPSAParameter, SPSARun, Test
from OpenBench.templatetags.mytags import elo_estimate, llr_position, finished_label, bounded_llr


class InterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user('author', password='local-test-password')
        cls.approver = User.objects.create_user('approver', password='local-test-password')
        Profile.objects.create(user=cls.author, enabled=True, engine='StockDory')
        Profile.objects.create(user=cls.approver, enabled=True, approver=True, engine='StockDory')
        cls.base = Engine.objects.create(name='master', source='https://api.github.com/repos/TheBlackPlague/StockDory/zipball/main', sha='a' * 40)
        cls.dev = Engine.objects.create(name='candidate', source=cls.base.source, sha='b' * 40)
        cls.test = cls.make_workload()
        cls.machine = Machine.objects.create(user=cls.author, workload=cls.test.id, secret='must-not-be-exposed', info={
            'machine_name': 'Worker One', 'os_name': 'Linux', 'isa_name': 'AVX2',
            'concurrency': 8, 'cpu_name': 'CPU', 'cpu_flags': [], 'cli_options': {'password': 'private-cli-value'},
        }, mnps=2)
        Result.objects.create(test=cls.test, machine=cls.machine, games=100, LL=10, LD=10, DD=10, DW=10, WW=10)

    @classmethod
    def make_workload(cls, **kwargs):
        data = dict(author='author', dev=cls.dev, base=cls.base, dev_engine='StockDory', base_engine='StockDory',
                    dev_repo='https://github.com/TheBlackPlague/StockDory', base_repo='https://github.com/TheBlackPlague/StockDory',
                    dev_options='Threads=1 Hash=16', base_options='Threads=1 Hash=16',
                    dev_time_control='10.0+0.1', base_time_control='10.0+0.1',
                    book_name='UHO_Lichess_4852_v1.epd', approved=True, games=100, wins=30, losses=20, draws=50,
                    LL=10, LD=10, DD=10, DW=10, WW=10, lowerllr=-2.94, upperllr=2.94, currentllr=0.1,
                    alpha=.05, beta=.05, elolower=0, eloupper=3)
        data.update(kwargs)
        return Test.objects.create(**data)

    def live(self, path='/', **headers):
        return self.client.get(path, HTTP_X_VERDICT_LIVE='1', **headers)

    def test_private_pages_protect_live_fragments_and_flash_messages(self):
        with patch.dict(OPENBENCH_CONFIG, require_login_to_view=True):
            for path in ['/', '/machines/', f'/test/{self.test.id}/']:
                response = self.live(path)
                self.assertEqual(response.status_code, 401)
                self.assertIn('error', response.json())
                self.assertNotContains(response, 'candidate', status_code=401)
            self.client.force_login(self.author)
            self.assertEqual(self.live().status_code, 200)
        session = self.client.session
        session['status_message'] = 'Keep this notice'
        session['error_message'] = 'Keep this error'
        session.save()
        self.live()
        self.assertEqual(self.client.session['status_message'], 'Keep this notice')
        self.assertEqual(self.client.session['error_message'], 'Keep this error')
        self.client.get('/')
        self.assertNotIn('status_message', self.client.session)
        self.assertNotIn('error_message', self.client.session)

    def test_etag_changes_when_results_change(self):
        response = self.live()
        self.assertEqual(response.status_code, 200)
        self.assertIn('X-Verdict-Live', response['Vary'])
        unchanged = self.live(HTTP_IF_NONE_MATCH=response['ETag'])
        self.assertEqual(unchanged.status_code, 304)
        Test.objects.filter(pk=self.test.id).update(games=102, wins=32, WW=11)
        changed = self.live(HTTP_IF_NONE_MATCH=response['ETag'])
        self.assertEqual(changed.status_code, 200)
        self.assertIn('Games: 102', changed.json()['regions']['overview-live'])
        self.assertNotEqual(changed['ETag'], response['ETag'])

    def test_live_regions_exclude_forms_and_follow_action_permissions(self):
        path = f'/test/{self.test.id}/'
        self.client.force_login(self.author)
        data = self.live(path).json()['regions']
        self.assertEqual(set(data), {'workload-metrics-live', 'workload-actions-live', 'workload-statblock-live'})
        joined = ''.join(data.values())
        self.assertNotIn('<form', joined)
        self.assertNotIn('<textarea', joined)
        self.assertNotIn('csrfmiddlewaretoken', joined)
        self.assertIn('/STOP', data['workload-actions-live'])
        Test.objects.filter(pk=self.test.id).update(finished=True)
        data = self.live(path).json()['regions']
        self.assertIn('/RESTART', data['workload-actions-live'])
        self.assertNotIn('/STOP', data['workload-actions-live'])
        self.assertIn('Stopped', data['workload-metrics-live'])
        self.client.logout()
        self.assertNotIn('/RESTART', self.live(path).json()['regions']['workload-actions-live'])
        Test.objects.filter(pk=self.test.id).update(finished=False, approved=False)
        self.client.force_login(self.author)
        self.assertNotIn('/APPROVE', self.live(path).json()['regions']['workload-actions-live'])
        self.client.force_login(self.approver)
        self.assertIn('/APPROVE', self.live(path).json()['regions']['workload-actions-live'])

    def test_live_filters_and_pagination_match_the_page(self):
        other = Engine.objects.create(name='another-author-work', source=self.dev.source, sha='c' * 40)
        self.make_workload(author='someoneelse', dev=other)
        own = self.live('/user/author/').json()['regions']['overview-live']
        self.assertIn('candidate', own)
        self.assertNotIn('another-author-work', own)
        for i in range(27):
            self.make_workload(finished=True)
        self.make_workload(finished=True, passed=True, dev=other)
        second = self.live('/index/2/').json()['regions']['overview-live']
        self.assertNotIn('Ordered by priority', second)
        self.assertNotIn('Awaiting approval', second)
        passed = self.live('/greens/').json()['regions']['overview-live']
        self.assertIn('another-author-work', passed)
        self.assertNotIn('candidate', passed)
        full = self.client.get('/index/2/').content.decode()
        self.assertEqual(BeautifulSoup(second, 'html.parser').get_text(' ', strip=True),
                         BeautifulSoup(full, 'html.parser').select_one('#overview-live').get_text(' ', strip=True))

    def test_machine_fragments_remove_stale_workers_without_secrets(self):
        content = self.live('/machines/').json()['regions']['machines-live']
        self.assertIn('Worker One', content)
        self.assertIn(f'/test/{self.test.id}/', content)
        self.assertNotIn(self.machine.secret, content)
        self.assertNotIn('private-cli-value', content)
        Machine.objects.filter(pk=self.machine.id).update(updated=timezone.now() - datetime.timedelta(minutes=3))
        content = self.live('/machines/').json()['regions']['machines-live']
        self.assertNotIn('Worker One', content)
        self.assertIn('No machines connected', content)

    def test_workload_and_machine_queries_do_not_grow_per_row(self):
        self.live()  # warm template caches
        with CaptureQueriesContext(connection) as first:
            self.live()
        with CaptureQueriesContext(connection) as machines_first:
            self.live('/machines/')
        for i in range(8):
            t = self.make_workload()
            Machine.objects.create(user=self.author, workload=t.id, info=self.machine.info)
        with CaptureQueriesContext(connection) as more:
            self.live()
        with CaptureQueriesContext(connection) as machines_more:
            self.live('/machines/')
        self.assertLessEqual(len(more), len(first) + 1)
        self.assertLessEqual(len(machines_more), len(machines_first) + 1)

    def test_tune_and_datagen_render_and_refresh(self):
        tune = self.make_workload(test_mode='SPSA')
        run = SPSARun.objects.create(tune=tune, reporting_type='BATCHED', distribution_type='SINGLE', alpha=.602,
                                    gamma=.101, iterations=100, pairs_per=10, a_ratio=.1)
        SPSAParameter.objects.create(spsa_run=run, name='Tempo', index=0, value=10, is_float=False, start=10,
                                     min_value=0, max_value=20, c_end=1, r_end=.002, c_value=1, a_value=1)
        datagen = self.make_workload(test_mode='DATAGEN', use_tri=True, use_penta=False, max_games=1000,
                                     LL=0, LD=0, DD=0, DW=0, WW=0)
        for path in [f'/tune/{tune.id}/', f'/datagen/{datagen.id}/']:
            self.assertEqual(self.client.get(path).status_code, 200)
            self.assertEqual(self.live(path).status_code, 200)
        self.assertIn('Tuning progress', self.live(f'/tune/{tune.id}/').json()['regions']['workload-metrics-live'])
        self.assertNotEqual(elo_estimate(datagen), '—')
        datagen.currentllr = 100
        self.assertEqual(llr_position(datagen), '100.00')
        self.assertEqual(bounded_llr(datagen), datagen.upperllr)
        self.assertEqual(finished_label(datagen), 'Stopped')
        datagen.games = datagen.max_games
        self.assertEqual(finished_label(datagen), 'Finished')

    def test_form_contracts_and_configuration_controls(self):
        self.client.force_login(self.author)
        common = {'dev_engine', 'dev_repo', 'dev_branch', 'dev_bench', 'dev_network', 'dev_options',
                  'dev_time_control', 'info', 'book_name', 'upload_pgns', 'priority', 'throughput',
                  'syzygy_wdl', 'syzygy_adj', 'win_adj', 'draw_adj', 'scale_method', 'scale_nps'}
        specific = {
            'test': {'base_engine', 'base_repo', 'base_branch', 'base_bench', 'base_network', 'base_options',
                     'base_time_control', 'workload_size', 'test_mode', 'test_bounds', 'test_confidence', 'test_max_games'},
            'tune': {'spsa_reporting_type', 'spsa_distribution_type', 'spsa_inputs', 'spsa_alpha', 'spsa_gamma',
                     'spsa_A_ratio', 'spsa_iterations', 'spsa_pairs_per'},
            'datagen': {'base_engine', 'base_options', 'workload_size', 'datagen_max_games', 'datagen_custom_genfens', 'datagen_play_reverses'},
        }
        for kind, fields in specific.items():
            soup = BeautifulSoup(self.client.get(f'/{kind}/new/').content, 'html.parser')
            form = soup.find('form')
            self.assertEqual(form['method'].upper(), 'POST')
            self.assertTrue((common | fields | {'csrfmiddlewaretoken'}) <= {el.get('name') for el in form.select('[name]')})
            self.assertTrue(all(soup.find(id=id) for id in ['json-config', 'json-networks', 'json-repos']))
        self.client.force_login(self.approver)
        net = Network.objects.create(engine='StockDory', name='Network', sha256='ABCD1234', author='author')
        soup = BeautifulSoup(self.client.get('/networks/StockDory/EDIT/ABCD1234/').content, 'html.parser')
        self.assertEqual({el.get('name') for el in soup.select('select')}, {'default', 'was_default'})
        self.assertTrue(soup.select_one('input[type=submit]').find_parent('form'))

    def test_search_keeps_shareable_filters_and_table_columns(self):
        self.make_workload(author='someoneelse', info='excluded')
        response = self.client.get('/search/?go=1&authors=author&hide-reds=1')
        soup = BeautifulSoup(response.content, 'html.parser')
        form = soup.select_one('form')
        self.assertEqual(form['method'].upper(), 'GET')
        self.assertEqual(soup.select_one('[name=authors]')['value'], 'author')
        self.assertFalse(soup.select_one('#show-reds').has_attr('checked'))
        self.assertNotContains(response, 'excluded')
        self.assertEqual(len(soup.select('.test-list thead th')), 8)
        self.assertEqual(len(soup.select('.test-list tbody tr')[0].select('td')), 8)

    def test_mutation_permissions_still_apply_on_server(self):
        path = f'/test/{self.test.id}/MODIFY/'
        data = {'info': 'Updated notes', 'priority': '5', 'throughput': '1000', 'workload_size': '32'}
        self.client.post(path, data)
        self.test.refresh_from_db()
        self.assertNotEqual(self.test.info, 'Updated notes')
        self.client.force_login(self.author)
        self.client.post(path, data)
        self.test.refresh_from_db()
        self.assertEqual(self.test.info, 'Updated notes')
        self.assertEqual(self.test.priority, 5)
