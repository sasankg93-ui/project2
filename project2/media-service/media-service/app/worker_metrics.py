"""Per-worker-node exporter: CPU and memory across the Celery main process and its children.

Runs in the worker's main process (started from the worker_ready signal) so a single HTTP
port serves all prefork children.
"""
import os

import psutil
from prometheus_client import CollectorRegistry, start_http_server
from prometheus_client.core import GaugeMetricFamily


class WorkerCollector:
    def __init__(self):
        self._procs: dict[int, psutil.Process] = {}
        self._main = psutil.Process(os.getpid())

    def _live(self) -> list[psutil.Process]:
        current = [self._main] + self._main.children(recursive=True)  # includes ffmpeg subprocesses
        # Reuse Process objects: cpu_percent() measures since the previous call on the same object.
        self._procs = {p.pid: self._procs.get(p.pid, p) for p in current}
        return list(self._procs.values())

    def collect(self):
        cpu = mem = 0.0
        procs = self._live()
        for p in procs:
            try:
                cpu += p.cpu_percent(interval=None)
                mem += p.memory_info().rss
            except psutil.Error:
                continue
        yield GaugeMetricFamily("media_worker_cpu_percent", "CPU % of worker tree (100 = one core)", value=cpu)
        yield GaugeMetricFamily("media_worker_memory_bytes", "RSS of worker tree", value=mem)
        yield GaugeMetricFamily("media_worker_processes", "Processes in worker tree", value=len(procs))
        yield GaugeMetricFamily("media_worker_host_cpu_percent", "Host CPU %", value=psutil.cpu_percent(interval=None))


def start_exporter(port: int) -> None:
    reg = CollectorRegistry()
    reg.register(WorkerCollector())
    start_http_server(port, registry=reg)
