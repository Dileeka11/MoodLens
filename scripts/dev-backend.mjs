/**
 * Launches the FastAPI backend using the project's virtualenv.
 *
 * A plain npm script can't do this portably: the interpreter lives at
 * venv\Scripts\python.exe on Windows and venv/bin/python everywhere else.
 * This picks the right one, fails with a useful message if the venv is
 * missing, and forwards signals so Ctrl+C stops it cleanly.
 */

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const backend = join(root, 'backend');

const isWindows = process.platform === 'win32';
const venvPython = isWindows
  ? join(backend, 'venv', 'Scripts', 'python.exe')
  : join(backend, 'venv', 'bin', 'python');

if (!existsSync(venvPython)) {
  console.error(
    `\n[backend] No virtualenv found at ${venvPython}\n` +
      `[backend] Create it first:\n` +
      `    cd backend\n` +
      `    python -m venv venv\n` +
      `    ${isWindows ? 'venv\\Scripts\\pip' : 'venv/bin/pip'} install -r requirements.txt\n`
  );
  process.exit(1);
}

const port = process.env.BACKEND_PORT || '8001';
const args = [
  '-m',
  'uvicorn',
  'app.main:app',
  '--host',
  '127.0.0.1',
  '--port',
  port,
];
if (process.env.BACKEND_RELOAD === '1') args.push('--reload');

const child = spawn(venvPython, args, {
  cwd: backend,
  stdio: 'inherit',
  env: process.env,
});

// Without this, Ctrl+C in the parent leaves uvicorn running in the background.
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => child.kill(signal));
}

child.on('exit', (code) => process.exit(code ?? 0));
child.on('error', (err) => {
  console.error('[backend] failed to start:', err.message);
  process.exit(1);
});
