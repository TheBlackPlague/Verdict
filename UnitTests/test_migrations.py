from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class LegacyDatabaseUpgradeTests(TransactionTestCase):
    """Exercise the schema used by the old Verdict master with populated data."""

    def test_tuning_results_and_engine_sources_survive_upgrade(self):
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        legacy = [('OpenBench', '0001_initial')]
        try:
            executor.migrate(legacy)
            apps = executor.loader.project_state(legacy).apps
            User = apps.get_model('auth', 'User')
            Engine = apps.get_model('OpenBench', 'Engine')
            Test = apps.get_model('OpenBench', 'Test')
            Machine = apps.get_model('OpenBench', 'Machine')
            Result = apps.get_model('OpenBench', 'Result')
            Profile = apps.get_model('OpenBench', 'Profile')

            user = User.objects.create(username='legacy-user')
            Profile.objects.create(user=user, games=200, enabled=True)
            sha = 'a' * 40
            root = 'https://api.github.com/repos/TheBlackPlague/StockDory'
            sources = [
                'https://github.com/TheBlackPlague/StockDory/archive/%s.zip' % sha,
                root + '/actions/runs/123/artifacts',
                root + '/zipball/' + sha,
            ]
            engines = [Engine.objects.create(name='legacy-%d' % index, source=source, sha=sha, bench=123)
                       for index, source in enumerate(sources)]
            machine = Machine.objects.create(user=user, info={'machine_name': 'legacy-worker'})
            parameter = {'value': 11.5, 'float': True, 'start': 10.0, 'min': 0.0, 'max': 20.0,
                         'c_end': 0.5, 'r_end': 0.002, 'c': 0.75, 'a': 0.1}
            tune = Test.objects.create(
                dev=engines[0], base=engines[1], author=user.username, test_mode='SPSA',
                dev_engine='StockDory', base_engine='StockDory', games=200, wins=50, draws=100, losses=50,
                spsa={'Alpha': 0.602, 'Gamma': 0.101, 'iterations': 1000, 'pairs_per': 4,
                      'A_ratio': 0.1, 'parameters': {'HistoryBonus': parameter}},
            )
            result = Result.objects.create(test=tune, machine=machine, games=200, wins=50, draws=100, losses=50)

            MigrationExecutor(connection).migrate(latest)
            from OpenBench.models import Engine as CurrentEngine, Profile as CurrentProfile
            from OpenBench.models import Result as CurrentResult, Test as CurrentTest

            upgraded = CurrentTest.objects.get(pk=tune.pk)
            self.assertEqual((upgraded.games, upgraded.wins, upgraded.draws, upgraded.losses), (200, 50, 100, 50))
            run = upgraded.spsa_run
            self.assertEqual(run.iterations, 1000)
            self.assertEqual(run.reporting_type, 'BATCHED')
            self.assertEqual(run.distribution_type, 'SINGLE')
            self.assertEqual(run.pairs_per, 4)
            param = run.parameters.get(name='HistoryBonus')
            self.assertEqual(param.value, 11.5)
            self.assertEqual(param.index, 0)
            self.assertEqual(param.min_value, 0.0)
            self.assertEqual(param.max_value, 20.0)
            self.assertTrue(param.is_float)
            self.assertEqual(CurrentProfile.objects.get(user_id=user.pk).games, 200)
            migrated_result = CurrentResult.objects.get(pk=result.pk)
            self.assertEqual(migrated_result.games, 200)
            for field in ['dev_nodes', 'base_nodes', 'dev_time', 'base_time', 'dev_time_scaled', 'base_time_scaled']:
                self.assertEqual(getattr(migrated_result, field), 0)
            self.assertEqual(list(CurrentEngine.objects.values_list('source', flat=True)), [root + '/zipball/' + sha] * 3)
        finally:
            # Leave the database at the current schema for the rest of the suite.
            MigrationExecutor(connection).migrate(latest)
