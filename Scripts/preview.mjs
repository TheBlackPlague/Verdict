// Optional browser preview; production continues to use Django/WSGI directly.
import {spawn} from 'node:child_process';
import {existsSync} from 'node:fs';
import {resolve} from 'node:path';
const args = process.argv.slice(2);
const option = (key, fallback) => args.includes(key) ? args[args.indexOf(key) + 1] : fallback;
const host = option('--host', '127.0.0.1');
const port = option('--port', '8000');
const env = {...process.env};
// Isolated preview runtimes can install requirements into this ignored directory.
if (existsSync('.preview-deps')) env.PYTHONPATH = [resolve('.preview-deps'), env.PYTHONPATH].filter(Boolean).join(':');
const child = spawn(process.env.VERDICT_PYTHON || 'python3', ['manage.py', 'runserver', `${host}:${port}`], {stdio: 'inherit', env});
for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
