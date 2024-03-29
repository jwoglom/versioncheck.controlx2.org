#!/usr/bin/env python3

import os
import requests
import logging
import time
import arrow

from flask import Flask, render_template, Response, request, abort, redirect

from prometheus_flask_exporter.multiprocess import GunicornPrometheusMetrics
from prometheus_client import Counter, Gauge, start_http_server

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')

logger = logging.getLogger(__name__)

app = Flask(__name__)
metrics = GunicornPrometheusMetrics(app)

version_checks = Counter('version_checks', 'Version checks', ['version', 'timezone', 'countryCode', 'deviceUuid'])
latest_version = Gauge('latest_version', 'Latest version', ['version'])
compare_results = Counter('compare_results', 'Compare results', ['status'])
release_fetches = Counter('release_fetches', 'Release fetches from GitHub', [])


GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
def fetch_all_releases():
    r = requests.get('https://api.github.com/repos/jwoglom/controlX2/releases?per_page=5', headers={
        'Accept': 'application/vnd.github+json',
        'Authorization': 'Bearer ' + GITHUB_TOKEN,
        'X-GitHub-Api-Version': '2022-11-28'
    })
    if r.status_code//100 >= 4:
        raise RuntimeError(f'got status_code={r.status_code} from GitHub')
    return r.json()

# Wait 12 hours before advertising a new release
recency_interval_seconds = 12 * 60 * 60
def is_too_recent(latest):
    created = arrow.get(latest['created_at']).timestamp()
    return time.time() - created <= recency_interval_seconds

latest_release = None
latest_release_time = None
check_interval_seconds = 60 * 60 # 1 hour
def get_latest_release():
    global latest_release, latest_release_time
    if latest_release_time and (time.time() - latest_release_time) < check_interval_seconds:
        return latest_release
    
    releases = fetch_all_releases()
    latest_release = None
    for r in releases:
        if r['draft'] or r['prerelease']:
            continue
        
        if is_too_recent(r) and not '[URGENT]' in r['body']:
            continue

        latest_release = r
        break

    logger.info(f'latest_release: {latest_release}')
    release_fetches.inc()

    if latest_release:
        latest_release_time = time.time()
    return latest_release

def compare_releases(version):
    latest = get_latest_release()
    latest_ver = latest['name'].strip()

    version = version.strip()

    latest_version.clear()
    latest_version.labels(latest_release['name']).set(1)

    if latest_ver == version:
        return True, latest
    
    latest_base = latest_ver
    if '-' in latest_ver:
        latest_base, latest_rev = latest_ver.split('-')
    
    cur_base = version
    if '-' in version:
        cur_base, cur_rev = version.split('-')
    
        if cur_base < latest_base:
            return False, latest
        
        if cur_rev < latest_rev:
            return False, latest
    
    if version < latest_ver:
        return False, latest
    
    return True, latest

def build_json(cmp, latest):
    return {
        'upToDate': cmp,
        'newVersion': latest['name'],
        'description': latest['body'].splitlines()[0],
        'url': latest['html_url']
    }


@app.route('/')
def index():
    return build_json(False, get_latest_release())

@app.route('/check/<path:version>', methods=['GET', 'POST'])
def check_route(version):
    data = {}
    if request.is_json:
        data = request.json

    user = data.get('user', {})

    version_checks.labels(
        version,
        user.get('timezone'),
        user.get('countryCode'),
        user.get('deviceUuid')
    ).inc()

    logger.info(f'check: {version} {data}')

    cmp, latest = compare_releases(version)
    compare_results.labels('up_to_date' if cmp else 'needs_update').inc()
    
    return build_json(cmp, latest)

@app.route('/refresh')
def refresh_route():
    global latest_release_time
    latest_release_time = None
    return index()


@app.route('/healthz')
def healthz_route():
    return 'ok'
