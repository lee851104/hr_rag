"""真實子程序逾時後必須終止，不可留下背景推論。"""

import time

import pytest

from hr_rag.local_models import ProcessModel
from hr_rag.providers import ProviderError


def echo_worker(connection):
    connection.send({"ready": True})
    while True:
        data = connection.recv()
        if data == "slow":
            time.sleep(10)
        connection.send({"result": data})


def test_real_process_timeout_closes_worker():
    model = ProcessModel(echo_worker, startup_timeout=60, request_timeout=0.1)
    try:
        assert model.call([1, 2]) == [1, 2]
        with pytest.raises(ProviderError, match="^timeout$"):
            model.call("slow")
        assert not model.process.is_alive()
    finally:
        model.close()


def crash_worker(connection):
    connection.send({"ready": True})
    connection.close()


def test_worker_crash_is_controlled():
    model = ProcessModel(crash_worker, startup_timeout=60, request_timeout=1)
    try:
        with pytest.raises(ProviderError, match="unavailable"):
            model.call([1])
    finally:
        model.close()
