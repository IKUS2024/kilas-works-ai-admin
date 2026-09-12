"""Conservative runtime for existing process-local conversational state."""
import os
workers = 1
threads = 1
worker_class = 'sync'
timeout = 120
preload_app = False
bind = '0.0.0.0:' + os.environ.get('PORT', '5000')

def on_starting(server):
    if server.cfg.workers != 1 or server.cfg.threads != 1 or server.cfg.worker_class_str not in ('sync', 'gunicorn.workers.sync.SyncWorker'):
        raise RuntimeError('Kilas conversational state currently requires one sync worker/thread; do not scale replicas.')
