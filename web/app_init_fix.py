# =============================================================================
# Initialization (Module Level - Safe for Gunicorn Workers)
# =============================================================================

# Initialize storage backend and auth middleware early
storage_backend = get_storage_backend()
init_auth_middleware(app, storage_backend, auth_enabled=AUTH_ENABLED)

# Register blueprints statically (must be at module level for Flask routing)
app.register_blueprint(auth_bp)

# Global flag to ensure background tasks run ONLY once across ALL processes
_BACKGROUND_TASKS_LOCK_FILE = os.path.join(CONFIG_DIR, 'background_tasks.lock')

def start_background_tasks():
    """
    Starts background tasks (Scheduler, Sync, Bootstrap).
    Uses a filesystem lock to ensure only ONE worker process handles these.
    """
    # Use a file-level lock to ensure singleton across Gunicorn workers
    lock_fd = os.open(_BACKGROUND_TASKS_LOCK_FILE, os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        # Non-blocking lock attempt
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # If we get here, THIS process is the background task manager
        print(f"[{os.getpid()}] Acquired background task lock. Starting services...")

        # Bootstrap admin user if auth is enabled and no users exist
        if AUTH_ENABLED:
            bootstrap_admin_user(storage_backend)

        # Initial inventory sync
        _run_inventory_sync()

        # Initialize cluster support
        if CLUSTER_MODE in ('standalone', 'primary'):
            init_local_worker()
            content_repo = get_content_repo(CONTENT_DIR)
            content_repo.init_repo()

        # Initialize the schedule manager
        global schedule_manager
        schedule_manager = ScheduleManager(
            socketio=socketio,
            run_playbook_fn=run_playbook_streaming,
            active_runs=active_runs,
            runs_lock=runs_lock,
            storage=storage_backend,
            is_managed_host_fn=is_managed_host,
            generate_managed_inventory_fn=generate_managed_inventory,
            create_batch_job_fn=create_batch_job,
            use_cluster_dispatch_fn=_should_use_cluster_dispatch,
            submit_cluster_job_fn=_submit_cluster_job,
            wait_for_job_completion_fn=_wait_for_job_completion,
            get_worker_name_fn=_get_worker_name
        )
        schedule_manager.start()

        # Periodic inventory sync (every 5 minutes)
        from apscheduler.triggers.interval import IntervalTrigger
        schedule_manager.scheduler.add_job(
            _run_inventory_sync,
            trigger=IntervalTrigger(minutes=5),
            id='inventory_sync',
            name='Inventory sync (DB <-> static)',
            replace_existing=True
        )

        # Bootstrap deployment (background thread)
        def _bootstrap_if_needed():
            try:
                from deployment import get_deployment_delta, run_bootstrap
                delta = get_deployment_delta(storage_backend=storage_backend)
                if delta.get('deploy_db') or delta.get('deploy_agent') or delta.get('deploy_workers'):
                    run_bootstrap(delta)
            except: pass
        threading.Thread(target=_bootstrap_if_needed, daemon=True).start()

    except (IOError, OSError):
        # Could not acquire lock, another process is already the manager
        print(f"[{os.getpid()}] Background tasks already managed by another process.")
        return

# Start tasks on first request (standard Gunicorn pattern) or if running directly
@app.before_request
def ensure_singleton_tasks():
    start_background_tasks()

if __name__ == '__main__':
    # When running directly, we are always the manager
    start_background_tasks()
    socketio.run(app, host='0.0.0.0', port=3001, debug=True)
