"""Bounded native workers; terminate the owned process tree on timeout."""
import os
import signal
import subprocess
import sys
from pathlib import Path


def run_logged(exe, args, env, log, marker, timeout):
    job = None
    command = [exe, *args]
    options = {'creationflags': getattr(subprocess, 'CREATE_NO_WINDOW', 0)}
    if os.name == 'nt':
        from .windows_job import Job
        job = Job()
        startup = subprocess.STARTUPINFO()
        startup.lpAttributeList = {'handle_list': [job.handle]}
        options['startupinfo'] = startup
        # The supervisor joins the job before it launches any native children.
        command = [getattr(sys, '_base_executable', sys.executable),
                   str(Path(__file__).with_name('workers')/'native_supervisor.py'),
                   str(job.handle), exe, *args]
    else:
        options['start_new_session'] = True
    try:
        with log.open('w', encoding='utf-8') as out:
            process = subprocess.Popen(command, env=env, stdout=out, stderr=subprocess.STDOUT, **options)
            try:
                returncode = process.wait(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                terminate_tree(process, job)
                raise
    finally:
        if job:job.close()
    if returncode or marker not in log.read_text(encoding='utf-8', errors='replace'):
        raise ValueError('Model step failed: ' + log.name + '. Check the private run log.')


def terminate_tree(process, job=None):
    try:
        if os.name == 'nt':
            if job is None:raise RuntimeError('Windows workers require an owned job')
            job.terminate()
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    finally:
        # Still reap the launcher if the tree-cleanup command itself fails.
        if process.poll() is None:
            process.kill()
        process.wait(timeout=15)
