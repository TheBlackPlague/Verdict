import math
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import RequestFactory, TestCase

from OpenBench.config import OPENBENCH_CONFIG
from OpenBench.models import Engine, LLRHistory, Machine, Profile, Result, Test
from OpenBench.utils import update_test


class LLRHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('history-author', password='test-only-password')
        Profile.objects.create(user=cls.user, enabled=True)
        engine = Engine.objects.create(name='candidate', source='https://example.test/engine', sha='a' * 40)
        cls.workload = Test.objects.create(
            author=cls.user.username, dev=engine, base=engine, approved=True,
            elolower=0, eloupper=3, lowerllr=-2.94, upperllr=2.94,
        )
        cls.machine = Machine.objects.create(user=cls.user, info={}, workload=cls.workload.id)
        cls.result = Result.objects.create(test=cls.workload, machine=cls.machine)

    def submit(self, games=64, llr=0.5):
        request = RequestFactory().post('/clientSubmitResults/', {
            'machine_id': self.machine.id, 'result_id': self.result.id,
            'test_id': self.workload.id, 'crashes': 0, 'timelosses': 0,
            'illegals': 0, 'trinomial': f'0 {games} 0',
            'pentanomial': f'0 0 {games // 2} 0 0',
        })
        with patch('OpenBench.utils.PentanomialSPRT', return_value=llr):
            return update_test(request, self.machine)

    def endpoint(self):
        return self.client.get(f'/api/workload/{self.workload.id}/llr/').json()

    def points(self):
        return list(LLRHistory.objects.values_list('games', 'llr'))

    def test_accepted_batches_sample_without_duplicate_points(self):
        for _ in range(3):
            self.assertEqual(self.submit(), {})
        self.assertEqual(self.points(), [(0, 0.0)])
        self.submit(llr=0.75)
        self.assertEqual(self.points(), [(0, 0.0), (256, 0.75)])
        self.submit(games=0, llr=0.75)
        self.assertEqual(self.points(), [(0, 0.0), (256, 0.75)])
        self.workload.refresh_from_db()
        self.result.refresh_from_db()
        self.assertEqual(self.workload.games, 256)
        self.assertEqual(self.result.games, 256)
        self.assertEqual(self.workload.currentllr, 0.75)
        with self.assertRaises(IntegrityError), transaction.atomic():
            LLRHistory.objects.create(test=self.workload, games=256, llr=0.75)

    def test_current_endpoint_is_included_between_samples_without_writes(self):
        self.submit(games=256)
        self.submit(llr=0.9)
        data = self.endpoint()
        self.assertEqual(data['points'], [
            {'games': 0, 'llr': 0.0}, {'games': 256, 'llr': 0.5}, {'games': 320, 'llr': 0.9},
        ])
        self.assertEqual((data['currentGames'], data['currentLLR']), (320, 0.9))
        self.assertEqual((data['lowerBound'], data['upperBound']), (-2.94, 2.94))
        self.assertEqual(data['sampleGames'], 256)
        self.assertFalse(data['partial'])
        self.assertFalse(data['downsampled'])
        self.endpoint()
        self.assertEqual(LLRHistory.objects.count(), 2)

    def test_legacy_history_begins_at_actual_state(self):
        Test.objects.filter(pk=self.workload.id).update(games=1000, currentllr=1.25)
        self.submit(llr=1.4)
        self.assertEqual(self.points(), [(1000, 1.25)])
        data = self.endpoint()
        self.assertEqual(data['points'], [{'games': 1000, 'llr': 1.25}, {'games': 1064, 'llr': 1.4}])
        self.assertEqual(data['startGames'], 1000)
        self.assertTrue(data['partial'])

    def test_legacy_finished_workload_returns_only_known_current_point(self):
        Test.objects.filter(pk=self.workload.id).update(games=1234, currentllr=3.1, finished=True, passed=True)
        data = self.endpoint()
        self.assertEqual(data['points'], [{'games': 1234, 'llr': 3.1}])
        self.assertTrue(data['partial'])
        self.assertTrue(data['finished'])
        self.assertEqual(LLRHistory.objects.count(), 0)

    def test_terminal_sample_is_recorded_and_rejected_batches_do_not_write(self):
        self.assertEqual(self.submit(llr=3.2), {'stop': True})
        self.assertEqual(self.points(), [(0, 0.0), (64, 3.2)])
        self.assertEqual(self.submit(llr=4.0), {'stop': True})
        self.assertEqual(self.points(), [(0, 0.0), (64, 3.2)])
        self.assertEqual(self.endpoint()['points'][-1], {'games': 64, 'llr': 3.2})
        self.assertTrue(self.endpoint()['finished'])

    def test_deleted_and_empty_reports_do_not_start_history(self):
        self.submit(games=0, llr=0.0)
        self.assertEqual(self.points(), [])
        Test.objects.filter(pk=self.workload.id).update(deleted=True)
        self.assertEqual(self.submit(), {'stop': True})
        self.assertEqual(self.points(), [])

    def test_failed_transaction_rolls_back_samples_and_results(self):
        with patch('OpenBench.utils.Result.objects.filter', side_effect=RuntimeError('write failed')):
            with self.assertRaisesRegex(RuntimeError, 'write failed'):
                self.submit(games=256)
        self.workload.refresh_from_db()
        self.assertEqual(self.workload.games, 0)
        self.assertEqual(self.points(), [])

    def test_api_preserves_public_private_and_disabled_account_permissions(self):
        with patch.dict(OPENBENCH_CONFIG, require_login_to_view=False):
            self.assertIn('points', self.endpoint())
        with patch.dict(OPENBENCH_CONFIG, require_login_to_view=True):
            # Existing API authentication reports missing credentials to stderr.
            with patch('traceback.print_exc'):
                self.assertIn('error', self.endpoint())
            self.client.force_login(self.user)
            self.assertIn('points', self.endpoint())
            Profile.objects.filter(user=self.user).update(enabled=False)
            self.assertIn('error', self.endpoint())

    def test_other_workload_modes_have_no_llr_history(self):
        Test.objects.filter(pk=self.workload.id).update(test_mode='GAMES', max_games=1000)
        self.submit(games=256)
        self.assertEqual(self.points(), [])
        self.assertIn('error', self.endpoint())
        self.assertIn('error', self.client.get('/api/workload/999999/llr/').json())

    def test_large_history_keeps_first_latest_and_extrema_with_bounded_response(self):
        rows = [LLRHistory(test=self.workload, games=i * 256, llr=0.5 * math.sin(i / 11)) for i in range(2000)]
        rows[501].llr = -2.5
        rows[1377].llr = 2.5
        LLRHistory.objects.bulk_create(rows)
        Test.objects.filter(pk=self.workload.id).update(games=2000 * 256, currentllr=0.25)
        data = self.endpoint()
        points = data['points']
        self.assertLessEqual(len(points), 770)
        self.assertEqual(points[0], {'games': 0, 'llr': 0.0})
        self.assertEqual(points[-1], {'games': 2000 * 256, 'llr': 0.25})
        self.assertIn({'games': 501 * 256, 'llr': -2.5}, points)
        self.assertIn({'games': 1377 * 256, 'llr': 2.5}, points)
        self.assertEqual([point['games'] for point in points], sorted({point['games'] for point in points}))
        self.assertTrue(data['downsampled'])

    def test_api_excludes_points_beyond_its_current_workload_state(self):
        LLRHistory.objects.create(test=self.workload, games=0, llr=0)
        LLRHistory.objects.create(test=self.workload, games=256, llr=0.5)
        self.assertEqual(self.endpoint()['points'], [{'games': 0, 'llr': 0.0}])
