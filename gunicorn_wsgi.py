import os

if not 'PROMETHEUS_MULTIPROC_DIR' in os.environ:
    os.environ['PROMETHEUS_MULTIPROC_DIR'] = '/tmp'

from app import app

from prometheus_flask_exporter.multiprocess import GunicornPrometheusMetrics

def when_ready(server):
    print('starting Prometheus server on :9091')
    GunicornPrometheusMetrics.start_http_server_when_ready(9091)

def child_exit(server, worker):
    GunicornPrometheusMetrics.mark_process_dead_on_child_exit(worker.pid)

if __name__ == '__main__':
    app.run()