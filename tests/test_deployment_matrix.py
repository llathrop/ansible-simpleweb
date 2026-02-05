"""
Stage 6: Deployment and system-size tests (test matrix T1–T9).

Real integration tests against a running primary (PRIMARY_URL). Each topology test
is skipped unless the running system matches that topology. Run with:
  PRIMARY_URL=http://localhost:3001 pytest tests/test_deployment_matrix.py -v

Prerequisites:
- Primary must be running (single container or full compose).
- For T2–T5: start the appropriate services (MongoDB, agent, workers) so the
  running topology matches; tests will skip if not.
- T6–T9 (bootstrap/expand): deployment API tests verify status and run endpoints;
  full bootstrap/expand flow is documented in docs/PHASE_SINGLE_CONTAINER_BOOTSTRAP.md
  and can be validated manually or via scripts.
"""

import os
import sys
import unittest

try:
    import requests
except ImportError:
    requests = None

PRIMARY_URL = os.environ.get('PRIMARY_URL', 'http://localhost:3001').rstrip('/')
TIMEOUT = 10


def primary_reachable():
    """True if primary responds on /api/status."""
    if not requests:
        return False
    try:
        r = requests.get(f"{PRIMARY_URL}/api/status", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def _get(path):
    """GET primary URL path; return (status_code, json or None)."""
    if not requests:
        return 0, None
    try:
        r = requests.get(f"{PRIMARY_URL}{path}", timeout=TIMEOUT)
        return r.status_code, r.json() if r.headers.get('content-type', '').startswith('application/json') else None
    except Exception:
        return 0, None


def current_topology():
    """
    Detect current topology from API: storage, workers, agent.
    Returns dict with storage_type, has_agent, remote_worker_count, and topology_id.
    """
    code, data = _get('/api/storage')
    storage_type = 'flatfile'
    if code == 200 and data:
        storage_type = data.get('backend_type', 'flatfile')
    code, data = _get('/api/workers')
    workers = data if (code == 200 and isinstance(data, list)) else []
    local_only = all(w.get('is_local') for w in workers) if workers else True
    remote_count = len([w for w in workers if not w.get('is_local')])
    code, data = _get('/api/agent/overview')
    has_agent = code == 200 and data is not None
    tid = 'single'
    if storage_type == 'mongodb' and not has_agent and remote_count == 0:
        tid = 'primary_db'
    elif storage_type == 'flatfile' and has_agent and remote_count == 0:
        tid = 'primary_agent'
    elif storage_type == 'mongodb' and has_agent and remote_count == 0:
        tid = 'primary_db_agent'
    elif storage_type == 'mongodb' and has_agent and remote_count > 0:
        tid = 'primary_db_agent_workers'
    return {
        'storage_type': storage_type,
        'has_agent': has_agent,
        'remote_worker_count': remote_count,
        'topology_id': tid,
        'workers': workers,
    }


@unittest.skipUnless(requests, "requests not installed")
@unittest.skipUnless(primary_reachable(), "Primary not reachable - start single container or compose")
class TestT1Single(unittest.TestCase):
    """T1: Single (demo) – one container; flatfile; local executor; playbook runs."""

    def setUp(self):
        self.top = current_topology()

    def test_t1_storage_is_flatfile(self):
        if self.top['storage_type'] != 'flatfile':
            self.skipTest("T1 requires single-container (flatfile) - current storage is %s" % self.top['storage_type'])
        self.assertEqual(self.top['storage_type'], 'flatfile')

    def test_t1_web_ui_reachable(self):
        code, _ = _get('/')
        self.assertEqual(code, 200)

    def test_t1_config_api_ok(self):
        code, data = _get('/api/config')
        self.assertEqual(code, 200)
        self.assertIn('config', data or {})

    def test_t1_deployment_status_ok(self):
        code, data = _get('/api/deployment/status')
        self.assertEqual(code, 200)
        self.assertIn('desired', data or {})
        self.assertIn('current', data or {})

    def test_t1_playbooks_listed(self):
        code, data = _get('/api/status')
        self.assertEqual(code, 200)
        self.assertIsInstance(data, dict)
        # /api/status returns { playbook_name: { status, run_id }, ... }
        code2, playbooks_data = _get('/api/playbooks')
        self.assertEqual(code2, 200)
        self.assertIsInstance(playbooks_data, list)


@unittest.skipUnless(requests, "requests not installed")
@unittest.skipUnless(primary_reachable(), "Primary not reachable")
class TestT2PrimaryDB(unittest.TestCase):
    """T2: Primary + DB – MongoDB deployed; primary uses MongoDB; schedules persist."""

    def setUp(self):
        self.top = current_topology()

    def test_t2_storage_is_mongodb(self):
        if self.top['storage_type'] != 'mongodb':
            self.skipTest("T2 requires MongoDB storage - start primary with DB")
        self.assertEqual(self.top['storage_type'], 'mongodb')

    def test_t2_storage_healthy(self):
        if self.top['storage_type'] != 'mongodb':
            self.skipTest("T2 requires MongoDB storage")
        code, data = _get('/api/storage')
        self.assertEqual(code, 200)
        self.assertTrue(data.get('healthy'), "Storage health check should pass")

    def test_t2_schedules_api_ok(self):
        if self.top['storage_type'] != 'mongodb':
            self.skipTest("T2 requires MongoDB storage")
        code, data = _get('/api/schedules')
        self.assertIn(code, (200, 404))
        if code == 200 and data is not None:
            self.assertIsInstance(data, (list, dict))


@unittest.skipUnless(requests, "requests not installed")
@unittest.skipUnless(primary_reachable(), "Primary not reachable")
class TestT3PrimaryAgent(unittest.TestCase):
    """T3: Primary + Agent – agent + ollama deployed; primary triggers agent; review in UI."""

    def setUp(self):
        self.top = current_topology()

    def test_t3_agent_reachable(self):
        if not self.top['has_agent']:
            self.skipTest("T3 requires agent reachable - start agent service")
        code, _ = _get('/api/agent/overview')
        self.assertEqual(code, 200)

    def test_t3_agent_reviews_api_ok(self):
        if not self.top['has_agent']:
            self.skipTest("T3 requires agent")
        code, data = _get('/api/agent/reviews')
        self.assertIn(code, (200, 500))
        if code == 200 and data is not None:
            self.assertIsInstance(data, (list, dict))


@unittest.skipUnless(requests, "requests not installed")
@unittest.skipUnless(primary_reachable(), "Primary not reachable")
class TestT4PrimaryDBAgent(unittest.TestCase):
    """T4: Primary + DB + Agent – both deployed; storage MongoDB; agent reviews work."""

    def setUp(self):
        self.top = current_topology()

    def test_t4_mongodb_and_agent(self):
        if self.top['storage_type'] != 'mongodb' or not self.top['has_agent']:
            self.skipTest("T4 requires MongoDB and agent - start DB and agent")
        self.assertEqual(self.top['storage_type'], 'mongodb')
        self.assertTrue(self.top['has_agent'])

    def test_t4_storage_and_agent_ok(self):
        if self.top['storage_type'] != 'mongodb' or not self.top['has_agent']:
            self.skipTest("T4 requires MongoDB and agent")
        code_s, data_s = _get('/api/storage')
        code_a, _ = _get('/api/agent/overview')
        self.assertEqual(code_s, 200)
        self.assertEqual(code_a, 200)


@unittest.skipUnless(requests, "requests not installed")
@unittest.skipUnless(primary_reachable(), "Primary not reachable")
class TestT5PrimaryDBAgentWorkers(unittest.TestCase):
    """T5: Primary + DB + Agent + Workers – workers deployed and registered; jobs routable."""

    def setUp(self):
        self.top = current_topology()

    def test_t5_has_remote_workers(self):
        if self.top['remote_worker_count'] == 0:
            self.skipTest("T5 requires remote workers - deploy workers and register")
        self.assertGreater(self.top['remote_worker_count'], 0)

    def test_t5_workers_api_list(self):
        if self.top['remote_worker_count'] == 0:
            self.skipTest("T5 requires remote workers")
        code, data = _get('/api/workers')
        self.assertEqual(code, 200)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)


@unittest.skipUnless(requests, "requests not installed")
@unittest.skipUnless(primary_reachable(), "Primary not reachable")
class TestT6T9DeploymentAPI(unittest.TestCase):
    """T6–T9: Bootstrap and expand – deployment status and run API work (real endpoints)."""

    def test_deployment_status_returns_structure(self):
        """Deployment status API returns desired, current, delta (for bootstrap/expand flow)."""
        code, data = _get('/api/deployment/status')
        self.assertEqual(code, 200)
        self.assertIn('desired', data or {})
        self.assertIn('current', data or {})
        self.assertIn('deploy_db', data or {})
        self.assertIn('deploy_agent', data or {})
        self.assertIn('deploy_workers', data or {})

    def test_deployment_run_accepts_post(self):
        """POST /api/deployment/run returns 200 (nothing to deploy) or 400 (failure)."""
        try:
            r = requests.post(f"{PRIMARY_URL}/api/deployment/run", timeout=TIMEOUT)
            self.assertIn(r.status_code, (200, 400))
            if r.status_code == 200:
                d = r.json()
                self.assertIn('ok', d)
                self.assertIn('message', d)
        except Exception as e:
            self.fail(f"Deployment run request failed: {e}")

    def test_config_page_reachable(self):
        """Config page (for enabling DB/agent/workers) returns 200."""
        code, _ = _get('/config')
        self.assertEqual(code, 200)
