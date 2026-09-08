import math
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from datetime import timedelta

from OpenBench.eta import format_hours, player_seconds, queue_eta, remaining_core_hours, remaining_games
from OpenBench.models import Engine, Machine, Test


def workload(**changes):
    values = dict(id=1, test_mode='SPRT', games=0, currentllr=0,
                  lowerllr=-math.log(19), upperllr=math.log(19), max_games=0,
                  dev_time_control='10.0+0.10', base_time_control='10.0+0.10',
                  dev_options='Threads=1', base_options='Threads=1',
                  approved=True, finished=False, deleted=False)
    return SimpleNamespace(**(values | changes))


class EstimateTests(SimpleTestCase):

    def test_new_sprt_uses_prior(self):
        self.assertEqual(remaining_games(workload()), 95000)
        self.assertAlmostEqual(remaining_core_hours(workload()), 815.7333333333)

    def test_llr_projection_is_symmetric_and_moves_with_evidence(self):
        positive = remaining_games(workload(games=50000, currentllr=2))
        negative = remaining_games(workload(games=50000, currentllr=-2))
        self.assertAlmostEqual(positive, negative)
        self.assertLess(positive, remaining_games(workload(games=50000, currentllr=0.2)))

    def test_asymmetric_boundaries(self):
        positive = remaining_games(workload(games=50000, currentllr=1, upperllr=4, lowerllr=-2))
        negative = remaining_games(workload(games=50000, currentllr=-1, upperllr=4, lowerllr=-2))
        self.assertGreater(positive, negative)

    def test_only_decided_sprt_has_zero_work(self):
        self.assertEqual(remaining_games(workload(currentllr=3)), 0)
        self.assertEqual(remaining_games(workload(currentllr=-3)), 0)
        self.assertGreater(remaining_games(workload(games=500000, currentllr=2.94)), 0)
        self.assertIsNone(remaining_games(workload(upperllr=0, currentllr=1)))

    def test_fixed_games_and_spsa(self):
        self.assertEqual(remaining_games(workload(test_mode='GAMES', max_games=1000, games=100)), 900)
        self.assertEqual(remaining_games(workload(test_mode='DATAGEN', max_games=1000, games=1100)), 0)
        tune = SimpleNamespace(iterations=100, pairs_per=16)
        self.assertEqual(remaining_games(workload(test_mode='SPSA', spsa_run=tune, games=200)), 3000)

    def test_time_controls_and_odds(self):
        self.assertAlmostEqual(player_seconds('40/60+0.5'), .92 * (102 + 34))
        self.assertAlmostEqual(player_seconds('MT=1000'), .92 * 68)
        self.assertAlmostEqual(player_seconds('10'), .92 * 10)
        for control in ('N=10000', 'D=12', '0/60', 'invalid', '0+0'):
            self.assertIsNone(player_seconds(control))
        test = workload(test_mode='GAMES', max_games=100, base_time_control='20+0.2',
                        base_options='Threads="4"')
        self.assertAlmostEqual(remaining_core_hours(test), 100 * 46.368 * 4 / 3600)

    def test_queue_uses_pooled_capacity_and_excludes_unapproved(self):
        tests = [workload(id=1), workload(id=2), workload(id=3, approved=False)]
        workers = [SimpleNamespace(workload=1, info={'concurrency': 100}),
                   SimpleNamespace(workload=999, info={'concurrency': 1000})]
        self.assertAlmostEqual(queue_eta(tests, workers)['hours'], 16.3146666667)

    def test_empty_offline_and_unsupported_queues(self):
        self.assertEqual(queue_eta([workload(approved=False)], [])['label'], 'Queue empty')
        self.assertIsNone(queue_eta([workload()], [])['hours'])
        workers = [SimpleNamespace(workload=1, info={'concurrency': 8})]
        self.assertEqual(queue_eta([workload(dev_time_control='N=1000')], workers)['label'], 'Unavailable')

    def test_duration_display(self):
        self.assertEqual(format_hours(0), '<1m')
        self.assertEqual(format_hours(0.5), '~30m')
        self.assertEqual(format_hours(2.5), '~2h 30m')
        self.assertEqual(format_hours(25), '~1d 1h')


class OverviewEstimateTests(TestCase):

    def setUp(self):
        engine = Engine.objects.create(name='eta-test', source='https://github.com/example/engine', sha='a' * 40)
        data = vars(workload())
        data.pop('id')
        self.test = Test.objects.create(**data, dev=engine, base=engine, dev_engine='StockDory',
                                        base_engine='StockDory', author='tester')
        user = User.objects.create_user(username='worker')
        self.machine = Machine.objects.create(user=user, workload=self.test.id,
                                               info={'concurrency': 100}, mnps=1)

    def test_overview_and_live_fragment_include_eta(self):
        response = self.client.get('/index/')
        self.assertContains(response, 'Estimated Time Remaining')
        self.assertContains(response, '~8h 10m')
        live = self.client.get('/index/', HTTP_X_VERDICT_LIVE='1')
        self.assertEqual(live.status_code, 200)
        self.assertIn('~8h 10m', live.json()['regions']['overview-live'])
        self.assertEqual(self.client.get('/index/', HTTP_X_VERDICT_LIVE='1',
                                        HTTP_IF_NONE_MATCH=live['ETag']).status_code, 304)

    def test_stale_workers_do_not_supply_capacity(self):
        Machine.objects.filter(id=self.machine.id).update(updated=timezone.now() - timedelta(minutes=3))
        self.assertContains(self.client.get('/index/'), 'No workers')

    def test_empty_queue_and_user_page_scope(self):
        self.test.finished = True
        self.test.save()
        self.assertContains(self.client.get('/index/'), 'Queue empty')
        self.assertNotContains(self.client.get('/user/tester/'), 'Estimated Time Remaining')
