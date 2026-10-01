import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.db import migrations


def import_verdict_config(apps, schema_editor):
    root = Path(settings.PROJECT_PATH)
    with (root / 'Config' / 'config.json').open() as source:
        config = json.load(source)

    alias = schema_editor.connection.alias
    EngineConfig = apps.get_model('OpenBench', 'EngineConfig')
    Book = apps.get_model('OpenBench', 'Book')
    ServerState = apps.get_model('OpenBench', 'ServerState')

    # Retained legacy files are imported once; subsequent edits belong in the UI.
    for name in config.get('engines', ['StockDory', 'Pawnocchio', 'Stash']):
        with (root / 'Engines' / ('%s.json' % name)).open() as source:
            engine = json.load(source)

        build = engine['build']
        presets = {
            key: engine.get(key) or {'default': {}}
            for key in ['test_presets', 'tune_presets', 'datagen_presets']
        }
        for group in presets.values():
            group.setdefault('default', {})

        EngineConfig.objects.using(alias).get_or_create(name=name, defaults={
            'private': engine['private'],
            'nps': engine['nps'],
            'source': engine['source'],
            'build_path': build['path'],
            'build_compilers': ' '.join(build['compilers']),
            'build_cpuflags': ' '.join(build['cpuflags']),
            'build_systems': ' '.join(build['systems']),
            'presets': presets,
        })

    enabled_books = config.get('books', ['UHO_Lichess_4852_v1.epd'])
    for name in enabled_books:
        path = root / 'Books' / ('%s.json' % name)
        if path.exists():
            with path.open() as source:
                book = json.load(source)
            Book.objects.using(alias).update_or_create(name=name, defaults={
                'source': book['source'], 'sha': book['sha'],
            })
        elif not Book.objects.using(alias).filter(name=name).exists():
            raise RuntimeError('Missing legacy book configuration: %s' % path)

    Book.objects.using(alias).exclude(name__in=enabled_books).update(enabled=False)
    Book.objects.using(alias).filter(name__in=enabled_books).update(enabled=True)

    # Historical models do not run EngineConfig.save()'s checksum hook.
    checksum = hashlib.sha256(b'').digest()
    for engine in EngineConfig.objects.using(alias).all():
        build = {
            'path': engine.build_path,
            'compilers': engine.build_compilers.split(),
            'cpuflags': engine.build_cpuflags.split(),
            'systems': engine.build_systems.split(),
        }
        serialized = json.dumps([engine.name, engine.private, build], sort_keys=True)
        partial = hashlib.sha256(serialized.encode('utf-8')).digest()
        checksum = bytes(a ^ b for a, b in zip(checksum, partial))

    ServerState.objects.using(alias).update_or_create(
        pk=1, defaults={'build_checksum': checksum.hex()})


class Migration(migrations.Migration):

    dependencies = [
        ('OpenBench', '0015_alter_engine_bench'),
        ('OpenBench', '0016_engineconfig_serverstate'),
    ]

    operations = [migrations.RunPython(import_verdict_config, migrations.RunPython.noop)]
