"""Run guarded fake regressions without rewriting published evidence."""
import builtins
import json
import socket
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import patch


def forbidden(*args, **kwargs):
    raise RuntimeError('OFFLINE_EXTERNAL_OPERATION_BLOCKED')


def guarded_import(original):
    def importing(name, *args, **kwargs):
        if name == 'MetaTrader5' or name.startswith('MetaTrader5.'):
            raise RuntimeError('OFFLINE_NATIVE_SDK_IMPORT_BLOCKED')
        return original(name, *args, **kwargs)
    return importing

if __name__ == '__main__':
    started=time.perf_counter()
    with patch.object(builtins, '__import__', side_effect=guarded_import(builtins.__import__)), \
            patch.object(socket.socket, 'connect', side_effect=forbidden), \
            patch.object(socket.socket, 'connect_ex', side_effect=forbidden), \
            patch.object(socket.socket, 'sendto', side_effect=forbidden), \
            patch.object(subprocess, 'run', side_effect=forbidden), \
            patch.object(subprocess, 'Popen', side_effect=forbidden):
        suite=unittest.defaultTestLoader.discover(str(Path(__file__).parent),pattern='test_*.py')
        result=unittest.TextTestRunner(verbosity=1).run(suite)
    report=dict(offline_only=True,tests=result.testsRun,successful=result.wasSuccessful(),
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        seconds=round(time.perf_counter()-started,3),
        external_socket_operations='BLOCKED', subprocesses='BLOCKED', native_sdk_import='BLOCKED',
        cloud_commit='db035b5da415bed61bed08e2b1cac50d8d31f73c')
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
