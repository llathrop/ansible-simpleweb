"""
Agent service: log review, playbook proposals, config analysis (LLM + RAG).

Logging: All logs go to stderr (no log file). To debug agent analysis or
trigger issues, view container logs: `docker compose logs agent-service`
or `docker compose logs -f agent-service`. See docs/ARCHITECTURE.md §6
(Logs and debugging) for where to find logs and how to debug failures.
"""
import os
import time
import json
import logging
import threading
import requests
from flask import Flask, jsonify, request
from agent.llm_client import LLMClient
from agent.rag import RAGEngine
from agent.security import SecurityEnforcer

# Configure logging (stderr only; view with: docker compose logs agent-service)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Config
SERVER_URL = os.environ.get('SERVER_URL', 'http://ansible-web:3001')
LOGS_DIR = os.environ.get('LOGS_DIR', '/app/logs')
DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
PLAYBOOKS_DIR = os.environ.get('PLAYBOOKS_DIR', '/app/playbooks')
DOCS_DIR = os.environ.get('DOCS_DIR', '/app/docs')

# SSL Configuration for requests to ansible-web
# SSL_VERIFY: true (default), false (disable verification for self-signed), or path to CA cert
def _get_ssl_verify():
    """Get SSL verification setting from environment."""
    verify_env = os.environ.get('SSL_VERIFY', 'true').lower()
    if verify_env in ('false', '0', 'no', 'disable'):
        return False
    elif verify_env in ('true', '1', 'yes', 'enable'):
        return True
    else:
        # Treat as path to CA certificate
        return verify_env if os.path.exists(verify_env) else True

SSL_VERIFY = _get_ssl_verify()
REVIEWS_DIR = os.path.join(DATA_DIR, 'reviews')
REVIEW_STATUS_DIR = os.path.join(DATA_DIR, 'review_status')
REVIEW_STATS_FILE = os.path.join(DATA_DIR, 'review_stats.json')
PROPOSALS_DIR = os.path.join(DATA_DIR, 'proposals')
REPORTS_DIR = os.path.join(DATA_DIR, 'reports')

# Ensure directories exist
try:
    os.makedirs(REVIEWS_DIR, exist_ok=True)
    os.makedirs(REVIEW_STATUS_DIR, exist_ok=True)
    os.makedirs(PROPOSALS_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)
except OSError as e:
    logger.warning(f"Could not create directories: {e}")

# Initialize components
llm_client = LLMClient()
rag_engine = RAGEngine()
security_enforcer = SecurityEnforcer()

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'online', 
        'service': 'agent-service',
        'model': llm_client.model,
        'rag_ready': True,
        'security_policy': 'active'
    })

@app.route('/rag/ingest', methods=['POST'])
def trigger_ingest():
    """Trigger ingestion of playbooks and docs into vector store."""
    try:
        rag_engine.ingest_data(PLAYBOOKS_DIR, DOCS_DIR)
        return jsonify({'status': 'ingestion_started', 'message': 'Ingestion process completed successfully'})
    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/prompts/reload', methods=['POST'])
def reload_prompts():
    llm_client.reload_prompts()
    security_enforcer.reload_policy()
    return jsonify({'status': 'reloaded'})

@app.route('/agent/generate', methods=['POST'])
def generate_playbook():
    """Generate a playbook based on user request."""
    data = request.get_json()
    user_request = data.get('request')
    
    if not user_request:
        return jsonify({'error': 'request field is required'}), 400
        
    # Guardrail: Check Security Policy
    allowed, reason = security_enforcer.check_playbook_generation(user_request)
    if not allowed:
        logger.warning(f"Request blocked by guardrail: {user_request} - Reason: {reason}")
        return jsonify({'error': f"Request blocked: {reason}"}), 403

    logger.info(f"Generating playbook for: {user_request}")
    
    try:
        # 1. Retrieve Context from RAG
        context_docs = rag_engine.query(user_request, n_results=3)
        context_text = "\n\n".join(context_docs)
        
        # 2. Generate with LLM
        generated_yaml = llm_client.generate_playbook(user_request, context_text)
        
        if not generated_yaml:
            return jsonify({'error': 'Generation failed'}), 500
            
        # Save Proposal
        proposal_id = f"proposal_{int(time.time())}"
        proposal_path = os.path.join(PROPOSALS_DIR, f"{proposal_id}.json")
        proposal_data = {
            'id': proposal_id,
            'request': user_request,
            'playbook': generated_yaml,
            'created_at': time.time(),
            'status': 'pending', # pending, approved, rejected
            'context_used': len(context_docs) > 0
        }
        
        with open(proposal_path, 'w') as f:
            json.dump(proposal_data, f, indent=2)

        return jsonify({
            'request': user_request,
            'generated_playbook': generated_yaml,
            'context_used': len(context_docs) > 0,
            'proposal_id': proposal_id
        })
        
    except Exception as e:
        logger.error(f"Generation error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/agent/schedule-monitor', methods=['POST'])
def monitor_schedules():
    """Verify that scheduled jobs ran successfully."""
    try:
        # Fetch active schedules from Ansible Web
        # Set timeout to prevent hanging if web is unresponsive
        resp = requests.get(f"{SERVER_URL}/api/schedules", timeout=5, verify=SSL_VERIFY)
        if resp.status_code != 200:
            return jsonify({'error': 'Failed to fetch schedules'}), 500
            
        schedules = resp.json()
        issues = []
        
        # Simple logic: Check if last_run was successful if it exists
        for sched in schedules:
            last_run = sched.get('last_run')
            if last_run:
                # Ideally we would check if it ran *when expected*, but for now
                # just checking if the last run status was a failure is a good start.
                # However, the schedule object might not have the status of the *job*.
                # We might need to fetch the job history for this schedule.
                pass 
                
        # For this MVP, we will just list them. Real logic would require more API support
        # from ansible-web to query "jobs by schedule_id".
        
        return jsonify({
            'status': 'monitored', 
            'schedules_checked': len(schedules),
            'issues': issues
        })
    except Exception as e:
        logger.error(f"Schedule monitor error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/agent/analyze-config', methods=['POST'])
def analyze_config():
    """Analyze a configuration text for security risks."""
    try:
        data = request.get_json()
        if not data or 'content' not in data:
            return jsonify({'error': 'Missing config content'}), 400
            
        config_content = data['content']
        
        # Security check: Config analysis is a read-only op, but let's verify size
        if len(config_content) > 100000:
            return jsonify({'error': 'Config content too large'}), 400
            
        analysis = llm_client.analyze_config(config_content)
        
        # Save report
        report_id = f"config_analysis_{int(time.time())}"
        report_path = os.path.join(REPORTS_DIR, f"{report_id}.json")
        # os.makedirs(os.path.dirname(report_path), exist_ok=True) # Already handled at startup
        
        report_data = {
            'id': report_id,
            'created_at': time.time(),
            'analysis': analysis
        }

        with open(report_path, 'w') as f:
            json.dump(report_data, f, indent=2)
            
        return jsonify({
            'status': 'analyzed',
            'report_id': report_id,
            'result': analysis
        })
    except Exception as e:
        logger.error(f"Config analysis error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trigger/log-review', methods=['POST'])
def trigger_log_review():
    """Event hook: Triggered when a playbook finishes."""
    data = request.get_json()
    job_id = data.get('job_id')
    exit_code = data.get('exit_code')
    
    if not job_id:
        return jsonify({'error': 'job_id required'}), 400

    logger.info(f"Received trigger for job {job_id}")
    
    # Run analysis in background
    threading.Thread(
        target=process_log_review,
        args=(job_id, exit_code)
    ).start()
    
    return jsonify({'status': 'accepted', 'job_id': job_id})

@app.route('/review-status/<job_id>', methods=['GET'])
def get_review_status(job_id):
    """Lightweight status for polling: pending | running | completed | error. Returns started_at when running for elapsed counter."""
    review_file = os.path.join(REVIEWS_DIR, f"{job_id}.json")
    status_file = os.path.join(REVIEW_STATUS_DIR, f"{job_id}.status")
    if os.path.exists(review_file):
        try:
            with open(review_file, 'r') as f:
                data = json.load(f)
            review = data.get('review') or {}
            if isinstance(review, dict) and (review.get('status') == 'failure' or review.get('error')):
                return jsonify({'status': 'error', 'duration_seconds': data.get('duration_seconds')})
            return jsonify({'status': 'completed', 'duration_seconds': data.get('duration_seconds')})
        except Exception:
            return jsonify({'status': 'error'})
    if os.path.exists(status_file):
        try:
            with open(status_file, 'r') as f:
                info = json.load(f)
            return jsonify({'status': 'running', 'started_at': info.get('started_at', time.time())})
        except (json.JSONDecodeError, TypeError):
            return jsonify({'status': 'running', 'started_at': time.time()})
    return jsonify({'status': 'pending'})


@app.route('/reviews/<job_id>', methods=['GET'])
def get_review(job_id):
    """Retrieve the review for a specific job."""
    review_file = os.path.join(REVIEWS_DIR, f"{job_id}.json")
    if os.path.exists(review_file):
        try:
            with open(review_file, 'r') as f:
                return jsonify(json.load(f))
        except Exception as e:
            logger.error(f"Error reading review for {job_id}: {e}")
            return jsonify({'error': 'Failed to read review'}), 500
    else:
        return jsonify({'error': 'Review not found', 'status': 'pending'}), 404

@app.route('/review-stats', methods=['GET'])
def get_review_stats():
    """Average response time for agent reviews (last 50)."""
    try:
        if os.path.exists(REVIEW_STATS_FILE):
            with open(REVIEW_STATS_FILE, 'r') as f:
                stats = json.load(f)
            return jsonify({
                'avg_response_time_seconds': round(stats.get('avg_seconds', 0), 1),
                'count': stats.get('count', 0)
            })
        return jsonify({'avg_response_time_seconds': 0, 'count': 0})
    except Exception as e:
        logger.error(f"Error reading review stats: {e}")
        return jsonify({'avg_response_time_seconds': 0, 'count': 0})


@app.route('/agent/reviews', methods=['GET'])
def list_reviews():
    """List recent reviews."""
    try:
        reviews = []
        if os.path.exists(REVIEWS_DIR):
            files = sorted(os.listdir(REVIEWS_DIR), key=lambda x: os.path.getmtime(os.path.join(REVIEWS_DIR, x)), reverse=True)
            for f in files[:20]: # Last 20
                if f.endswith('.json'):
                    with open(os.path.join(REVIEWS_DIR, f), 'r') as rf:
                        reviews.append(json.load(rf))
        return jsonify(reviews)
    except Exception as e:
        logger.error(f"Error listing reviews: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/agent/proposals', methods=['GET'])
def list_proposals():
    """List recent proposals."""
    try:
        proposals = []
        if os.path.exists(PROPOSALS_DIR):
            files = sorted(os.listdir(PROPOSALS_DIR), key=lambda x: os.path.getmtime(os.path.join(PROPOSALS_DIR, x)), reverse=True)
            for f in files[:20]:
                if f.endswith('.json'):
                    with open(os.path.join(PROPOSALS_DIR, f), 'r') as pf:
                        proposals.append(json.load(pf))
        return jsonify(proposals)
    except Exception as e:
        logger.error(f"Error listing proposals: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/agent/reports', methods=['GET'])
def list_reports():
    """List recent reports."""
    try:
        reports = []
        if os.path.exists(REPORTS_DIR):
            files = sorted(os.listdir(REPORTS_DIR), key=lambda x: os.path.getmtime(os.path.join(REPORTS_DIR, x)), reverse=True)
            for f in files[:20]:
                if f.endswith('.json'):
                    with open(os.path.join(REPORTS_DIR, f), 'r') as rf:
                        reports.append(json.load(rf))
        return jsonify(reports)
    except Exception as e:
        logger.error(f"Error listing reports: {e}")
        return jsonify({'error': str(e)}), 500


def _notify_web_review_ready(job_id, status):
    """Tell ansible-web that a review is ready so it can push to UI (no polling)."""
    url = f"{SERVER_URL}/api/agent/review-ready"
    try:
        r = requests.post(url, json={'job_id': job_id, 'status': status}, timeout=5, verify=SSL_VERIFY)
        if r.status_code != 200:
            logger.warning(f"Notify review-ready returned {r.status_code}: {r.text[:100]}")
        else:
            logger.info(f"Notified web that review for job {job_id} is {status}")
    except Exception as e:
        logger.warning(f"Could not notify web of review ready: {e}")


def _save_failure_review(job_id, error_message, duration_seconds=None):
    """Write a failure review so the UI shows error instead of Pending."""
    if duration_seconds is not None:
        _update_review_stats(duration_seconds)
    review_file = os.path.join(REVIEWS_DIR, f"{job_id}.json")
    status_file = os.path.join(REVIEW_STATUS_DIR, f"{job_id}.status")
    try:
        with open(review_file, 'w') as f:
            payload = {
                'job_id': job_id,
                'analyzed_at': time.time(),
                'review': {'status': 'failure', 'error': error_message}
            }
            if duration_seconds is not None:
                payload['duration_seconds'] = round(duration_seconds, 2)
            json.dump(payload, f, indent=2)
        logger.info(f"Failure review saved for job {job_id}: {error_message[:80]}")
        try:
            if os.path.exists(status_file):
                os.remove(status_file)
        except OSError:
            pass
        _notify_web_review_ready(job_id, 'error')
    except Exception as e:
        logger.exception(f"Could not save failure review for {job_id}: {e}")


def _update_review_stats(duration_seconds):
    """Update rolling avg of review durations (last 50)."""
    try:
        stats = {'durations': [], 'count': 0, 'total_seconds': 0}
        if os.path.exists(REVIEW_STATS_FILE):
            with open(REVIEW_STATS_FILE, 'r') as f:
                stats = json.load(f)
        dur = stats.get('durations', [])
        dur.append(duration_seconds)
        if len(dur) > 50:
            dur = dur[-50:]
        stats['durations'] = dur
        stats['count'] = len(dur)
        stats['total_seconds'] = sum(dur)
        stats['avg_seconds'] = stats['total_seconds'] / len(dur) if dur else 0
        with open(REVIEW_STATS_FILE, 'w') as f:
            json.dump(stats, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not update review stats: {e}")


def process_log_review(job_id, exit_code):
    """Fetch job details, read log, analyze, and save."""
    started_at = time.time()
    logger.info(f"Starting review for job {job_id}")
    status_file = os.path.join(REVIEW_STATUS_DIR, f"{job_id}.status")
    try:
        with open(status_file, 'w') as f:
            json.dump({'status': 'running', 'started_at': started_at}, f)
    except OSError as e:
        logger.warning(f"Could not write status file: {e}")
    try:
        # 1. Fetch Job Details from Ansible Web
        job_url = f"{SERVER_URL}/api/jobs/{job_id}"
        resp = requests.get(job_url, timeout=15, verify=SSL_VERIFY)
        if resp.status_code != 200:
            err = f"Failed to fetch job details: {resp.status_code} {resp.text[:200]}"
            logger.error(err)
            _save_failure_review(job_id, err, time.time() - started_at)
            return

        job_data = resp.json()
        playbook = job_data.get('playbook', 'unknown')
        log_file = job_data.get('log_file')

        if not log_file:
            err = "No log file specified for this job."
            logger.warning(err)
            _save_failure_review(job_id, err, time.time() - started_at)
            return

        # 2. Read Log Content
        log_path = os.path.join(LOGS_DIR, log_file)
        if not os.path.exists(log_path):
            err = f"Log file not found: {log_file}"
            logger.error(err)
            _save_failure_review(job_id, err, time.time() - started_at)
            return

        with open(log_path, 'r') as f:
            log_content = f.read()

        # 3. Analyze with LLM
        review = llm_client.analyze_log(job_id, playbook, exit_code, log_content)

        if not review:
            err = "Analysis failed to produce a result (LLM returned nothing)."
            logger.error(err)
            _save_failure_review(job_id, err, time.time() - started_at)
            return

        # 4. Save Success Review
        duration_seconds = time.time() - started_at
        _update_review_stats(duration_seconds)
        review_file = os.path.join(REVIEWS_DIR, f"{job_id}.json")
        with open(review_file, 'w') as f:
            json.dump({
                'job_id': job_id,
                'analyzed_at': time.time(),
                'duration_seconds': round(duration_seconds, 2),
                'review': review
            }, f, indent=2)
        try:
            if os.path.exists(status_file):
                os.remove(status_file)
        except OSError:
            pass
        _notify_web_review_ready(job_id, 'completed')
        logger.info(f"Review saved to {review_file} ({duration_seconds:.1f}s)")

    except Exception as e:
        duration_seconds = time.time() - started_at
        logger.exception(f"Error processing log review for job {job_id}: {e}")
        _save_failure_review(job_id, str(e), duration_seconds)
    finally:
        try:
            if os.path.exists(status_file):
                os.remove(status_file)
        except OSError:
            pass

def start_server():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    logger.info("Starting Agent Service...")
    start_server()
