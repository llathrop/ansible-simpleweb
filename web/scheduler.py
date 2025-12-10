"""
Ansible Web Interface - Schedule Manager

Handles playbook scheduling with APScheduler backend.
Provides create, read, update, delete operations for schedules,
with JSON file persistence and execution history tracking.

Architecture:
- APScheduler with SQLite job store for reliable scheduling
- JSON files for schedule metadata and execution history
- Integrates with existing run_playbook_streaming() function
- WebSocket events for real-time UI updates
"""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable, Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.executors.pool import ThreadPoolExecutor

# File paths (inside container)
SCHEDULES_FILE = '/app/config/schedules.json'
HISTORY_FILE = '/app/config/schedule_history.json'

# Maximum history entries to keep
MAX_HISTORY_ENTRIES = 1000


class ScheduleManager:
    """
    Manages playbook schedules with APScheduler backend.

    Provides:
    - CRUD operations for schedules
    - Execution via existing playbook runner
    - History tracking
    - Real-time WebSocket notifications
    """

    def __init__(self, socketio, run_playbook_fn: Callable, active_runs: Dict, runs_lock: threading.Lock):
        """
        Initialize the schedule manager.

        Args:
            socketio: Flask-SocketIO instance for real-time events
            run_playbook_fn: Function to execute playbooks (run_playbook_streaming)
            active_runs: Shared dict tracking active playbook runs
            runs_lock: Lock for thread-safe access to active_runs
        """
        self.socketio = socketio
        self.run_playbook_fn = run_playbook_fn
        self.active_runs = active_runs
        self.runs_lock = runs_lock

        # Schedule storage
        self.schedules: Dict[str, Dict] = {}
        self.schedules_lock = threading.RLock()  # RLock allows reentrant locking

        # Track running scheduled jobs: {schedule_id: run_id}
        self.running_jobs: Dict[str, str] = {}
        self.running_jobs_lock = threading.Lock()

        # Initialize APScheduler with memory job store
        # (Schedules are persisted in JSON, we just need in-memory job tracking)
        jobstores = {
            'default': MemoryJobStore()
        }
        executors = {
            'default': ThreadPoolExecutor(max_workers=3)
        }
        job_defaults = {
            'coalesce': True,           # Combine missed runs into one
            'max_instances': 1,          # One instance per schedule
            'misfire_grace_time': 300    # 5 minute grace period for missed jobs
        }

        self.scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone='UTC'
        )

        # Load existing schedules from file
        self._load_schedules()

    def start(self):
        """Start the scheduler and register all enabled jobs."""
        # Register existing enabled schedules with APScheduler
        for schedule_id, schedule in self.schedules.items():
            if schedule.get('enabled', True):
                try:
                    self._register_job(schedule_id, schedule)
                except Exception as e:
                    print(f"Error registering schedule {schedule_id}: {e}")

        self.scheduler.start()
        print(f"Scheduler started with {len(self.schedules)} schedules")

    def shutdown(self):
        """Shutdown the scheduler gracefully."""
        self.scheduler.shutdown(wait=True)

    # =========================================================================
    # Storage Operations
    # =========================================================================

    def _load_schedules(self):
        """Load schedules from JSON file."""
        if os.path.exists(SCHEDULES_FILE):
            try:
                with open(SCHEDULES_FILE, 'r') as f:
                    data = json.load(f)
                    self.schedules = data.get('schedules', {})
                    print(f"Loaded {len(self.schedules)} schedules from file")
            except (json.JSONDecodeError, IOError) as e:
                print(f"Error loading schedules: {e}")
                self.schedules = {}
        else:
            self.schedules = {}
            self._save_schedules()

    def _save_schedules(self):
        """Persist schedules to JSON file."""
        with self.schedules_lock:
            data = {
                'version': '1.0',
                'schedules': self.schedules
            }
            os.makedirs(os.path.dirname(SCHEDULES_FILE), exist_ok=True)
            with open(SCHEDULES_FILE, 'w') as f:
                json.dump(data, f, indent=2, default=str)

    def _record_execution(self, schedule_id: str, run_id: str, log_file: str,
                          status: str, started: datetime, finished: datetime = None):
        """Record execution in history file."""
        duration = None
        if finished and started:
            duration = (finished - started).total_seconds()

        history_entry = {
            'schedule_id': schedule_id,
            'run_id': run_id,
            'log_file': log_file,
            'started': started.isoformat() if started else None,
            'finished': finished.isoformat() if finished else None,
            'duration_seconds': duration,
            'status': status
        }

        try:
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, 'r') as f:
                    data = json.load(f)
            else:
                data = {'version': '1.0', 'history': []}

            # Insert at beginning (newest first)
            data['history'].insert(0, history_entry)

            # Trim to max entries
            data['history'] = data['history'][:MAX_HISTORY_ENTRIES]

            os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
            with open(HISTORY_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error recording history: {e}")

    # =========================================================================
    # APScheduler Integration
    # =========================================================================

    def _build_trigger(self, recurrence: Dict):
        """
        Build APScheduler trigger from recurrence configuration.

        Args:
            recurrence: Dict with 'type' and type-specific fields

        Returns:
            APScheduler trigger instance
        """
        rec_type = recurrence.get('type')

        if rec_type == 'once':
            # Single execution at specified datetime
            run_date = datetime.fromisoformat(recurrence['datetime'])
            return DateTrigger(run_date=run_date)

        elif rec_type == 'hourly':
            # Every hour at specified minute
            minute = recurrence.get('minute', 0)
            return CronTrigger(minute=minute)

        elif rec_type == 'daily':
            # Every day at specified time
            time_parts = recurrence['time'].split(':')
            return CronTrigger(
                hour=int(time_parts[0]),
                minute=int(time_parts[1])
            )

        elif rec_type == 'weekly':
            # Every week on specified days at time
            days = recurrence.get('days', [0])  # 0=Monday
            time_parts = recurrence['time'].split(':')
            # APScheduler uses 0-6 for mon-sun
            day_str = ','.join(str(d) for d in days)
            return CronTrigger(
                day_of_week=day_str,
                hour=int(time_parts[0]),
                minute=int(time_parts[1])
            )

        elif rec_type == 'monthly':
            # Every month on specified day at time
            day = recurrence.get('day', 1)
            time_parts = recurrence['time'].split(':')
            return CronTrigger(
                day=day,
                hour=int(time_parts[0]),
                minute=int(time_parts[1])
            )

        elif rec_type == 'custom':
            # Custom interval in minutes
            minutes = recurrence.get('interval_minutes', 60)
            return IntervalTrigger(minutes=minutes)

        else:
            raise ValueError(f"Unknown recurrence type: {rec_type}")

    def _register_job(self, schedule_id: str, schedule: Dict):
        """Register a schedule with APScheduler."""
        trigger = self._build_trigger(schedule['recurrence'])

        self.scheduler.add_job(
            func=self._execute_scheduled_playbook,
            trigger=trigger,
            args=[schedule_id],
            id=schedule_id,
            name=schedule.get('name', schedule_id),
            replace_existing=True
        )

        # Update next_run time in schedule
        self._update_next_run(schedule_id)

    def _update_next_run(self, schedule_id: str):
        """Update the next_run field for a schedule."""
        job = self.scheduler.get_job(schedule_id)
        if job and job.next_run_time:
            with self.schedules_lock:
                if schedule_id in self.schedules:
                    self.schedules[schedule_id]['next_run'] = job.next_run_time.isoformat()
                    self._save_schedules()

    def _execute_scheduled_playbook(self, schedule_id: str):
        """
        Execute playbook for a scheduled job.

        This is called by APScheduler in a worker thread.
        """
        # Get schedule info
        with self.schedules_lock:
            schedule = self.schedules.get(schedule_id)
            if not schedule:
                print(f"Schedule {schedule_id} not found")
                return
            schedule = schedule.copy()  # Work with a copy

        playbook = schedule['playbook']
        target = schedule['target']

        # Generate unique run ID and log filename
        run_id = str(uuid.uuid4())
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        safe_target = target.replace('/', '-').replace(':', '-')
        log_file = f"{playbook}-{safe_target}-{timestamp}-{run_id[:8]}.log"

        started = datetime.now()

        # Track running job
        with self.running_jobs_lock:
            self.running_jobs[schedule_id] = run_id

        # Update schedule status
        with self.schedules_lock:
            if schedule_id in self.schedules:
                self.schedules[schedule_id]['last_run'] = started.isoformat()
                self.schedules[schedule_id]['last_status'] = 'running'
                self.schedules[schedule_id]['current_run_id'] = run_id
                self._save_schedules()

        # Emit schedule started event
        self.socketio.emit('schedule_started', {
            'schedule_id': schedule_id,
            'run_id': run_id,
            'playbook': playbook,
            'target': target,
            'log_file': log_file
        }, room='schedules')

        # Also emit to status room for dashboard updates
        self.socketio.emit('status_update', {
            'run_id': run_id,
            'playbook': playbook,
            'target': target,
            'status': 'running',
            'scheduled': True,
            'schedule_id': schedule_id
        }, room='status')

        status = 'failed'
        try:
            # Call existing run_playbook_streaming function
            # This runs synchronously in the executor thread
            self.run_playbook_fn(run_id, playbook, target, log_file)

            # Check the final status from active_runs
            with self.runs_lock:
                run_info = self.active_runs.get(run_id)
                if run_info:
                    status = run_info.get('status', 'completed')
                else:
                    status = 'completed'

        except Exception as e:
            status = 'failed'
            print(f"Scheduled playbook execution error: {e}")

        finished = datetime.now()

        # Update schedule
        with self.schedules_lock:
            if schedule_id in self.schedules:
                self.schedules[schedule_id]['last_status'] = status
                self.schedules[schedule_id]['run_count'] = self.schedules[schedule_id].get('run_count', 0) + 1
                self.schedules[schedule_id]['current_run_id'] = None

                # For one-time schedules, disable after execution
                if schedule['recurrence']['type'] == 'once':
                    self.schedules[schedule_id]['enabled'] = False

                self._save_schedules()

        # Update next_run time
        self._update_next_run(schedule_id)

        # Record in history
        self._record_execution(schedule_id, run_id, log_file, status, started, finished)

        # Remove from running jobs
        with self.running_jobs_lock:
            if schedule_id in self.running_jobs:
                del self.running_jobs[schedule_id]

        # Emit completion event
        self.socketio.emit('schedule_completed', {
            'schedule_id': schedule_id,
            'run_id': run_id,
            'status': status,
            'log_file': log_file
        }, room='schedules')

    # =========================================================================
    # Public CRUD Operations
    # =========================================================================

    def create_schedule(self, playbook: str, target: str, name: str,
                        recurrence_config: Dict, description: str = '') -> str:
        """
        Create a new schedule.

        Args:
            playbook: Playbook name (without .yml)
            target: Target host/group
            name: Human-readable schedule name
            recurrence_config: Dict with recurrence settings
            description: Optional description

        Returns:
            schedule_id: UUID of created schedule
        """
        schedule_id = str(uuid.uuid4())

        schedule = {
            'id': schedule_id,
            'playbook': playbook,
            'target': target,
            'name': name,
            'description': description,
            'recurrence': recurrence_config,
            'enabled': True,
            'created': datetime.now().isoformat(),
            'last_run': None,
            'last_status': None,
            'next_run': None,
            'run_count': 0,
            'current_run_id': None
        }

        with self.schedules_lock:
            self.schedules[schedule_id] = schedule
            self._save_schedules()

        # Register with APScheduler
        self._register_job(schedule_id, schedule)

        # Emit event
        self.socketio.emit('schedule_created', {
            'schedule_id': schedule_id,
            'schedule': self._format_schedule_for_display(schedule)
        }, room='schedules')

        return schedule_id

    def get_schedule(self, schedule_id: str) -> Optional[Dict]:
        """Get a single schedule by ID."""
        with self.schedules_lock:
            schedule = self.schedules.get(schedule_id)
            if schedule:
                return self._format_schedule_for_display(schedule.copy())
        return None

    def get_all_schedules(self) -> List[Dict]:
        """Get all schedules with display-formatted fields."""
        result = []
        with self.schedules_lock:
            for schedule_id, schedule in self.schedules.items():
                result.append(self._format_schedule_for_display(schedule.copy()))

        # Sort by next_run (soonest first), with None values at end
        return sorted(result, key=lambda x: x.get('next_run') or '9999')

    def update_schedule(self, schedule_id: str, updates: Dict) -> bool:
        """
        Update schedule configuration.

        Args:
            schedule_id: Schedule to update
            updates: Dict of fields to update

        Returns:
            True if successful
        """
        with self.schedules_lock:
            if schedule_id not in self.schedules:
                return False

            schedule = self.schedules[schedule_id]

            # Update allowed fields
            allowed_fields = ['name', 'description', 'target', 'recurrence']
            for field in allowed_fields:
                if field in updates:
                    schedule[field] = updates[field]

            self._save_schedules()

        # Re-register job if recurrence changed
        if 'recurrence' in updates:
            try:
                self.scheduler.remove_job(schedule_id)
            except:
                pass
            if schedule.get('enabled', True):
                self._register_job(schedule_id, schedule)

        return True

    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a schedule."""
        # Remove from APScheduler
        try:
            self.scheduler.remove_job(schedule_id)
        except:
            pass

        # Remove from storage
        with self.schedules_lock:
            if schedule_id in self.schedules:
                del self.schedules[schedule_id]
                self._save_schedules()

        # Emit event
        self.socketio.emit('schedule_deleted', {
            'schedule_id': schedule_id
        }, room='schedules')

        return True

    def pause_schedule(self, schedule_id: str) -> bool:
        """Pause a schedule (disable without deleting)."""
        try:
            self.scheduler.pause_job(schedule_id)
        except:
            pass

        with self.schedules_lock:
            if schedule_id in self.schedules:
                self.schedules[schedule_id]['enabled'] = False
                self._save_schedules()

        self.socketio.emit('schedule_status', {
            'schedule_id': schedule_id,
            'enabled': False
        }, room='schedules')

        return True

    def resume_schedule(self, schedule_id: str) -> bool:
        """Resume a paused schedule."""
        with self.schedules_lock:
            if schedule_id not in self.schedules:
                return False
            schedule = self.schedules[schedule_id]
            schedule['enabled'] = True
            self._save_schedules()

        # Re-register job
        self._register_job(schedule_id, schedule)

        try:
            self.scheduler.resume_job(schedule_id)
        except:
            pass

        self.socketio.emit('schedule_status', {
            'schedule_id': schedule_id,
            'enabled': True
        }, room='schedules')

        return True

    def stop_running_job(self, schedule_id: str) -> bool:
        """Stop a currently running scheduled job."""
        # Get the run_id
        with self.running_jobs_lock:
            run_id = self.running_jobs.get(schedule_id)

        if not run_id:
            return False

        # Find and terminate the process
        with self.runs_lock:
            run_info = self.active_runs.get(run_id)
            if run_info and 'process' in run_info:
                try:
                    run_info['process'].terminate()
                    return True
                except Exception as e:
                    print(f"Error stopping job: {e}")

        return False

    def get_schedule_history(self, schedule_id: str = None, limit: int = 50) -> List[Dict]:
        """
        Get execution history.

        Args:
            schedule_id: Filter by schedule (None for all)
            limit: Max entries to return

        Returns:
            List of history entries (newest first)
        """
        try:
            if not os.path.exists(HISTORY_FILE):
                return []

            with open(HISTORY_FILE, 'r') as f:
                data = json.load(f)
                history = data.get('history', [])

            # Filter by schedule if specified
            if schedule_id:
                history = [h for h in history if h.get('schedule_id') == schedule_id]

            # Format for display
            for entry in history:
                if entry.get('duration_seconds'):
                    mins, secs = divmod(int(entry['duration_seconds']), 60)
                    entry['duration_display'] = f"{mins}m {secs}s"
                else:
                    entry['duration_display'] = 'N/A'

                if entry.get('started'):
                    try:
                        dt = datetime.fromisoformat(entry['started'])
                        entry['started_display'] = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        entry['started_display'] = entry['started']

            return history[:limit]

        except Exception as e:
            print(f"Error reading history: {e}")
            return []

    # =========================================================================
    # Display Formatting
    # =========================================================================

    def _format_schedule_for_display(self, schedule: Dict) -> Dict:
        """Add display-friendly fields to schedule dict."""
        schedule_id = schedule['id']

        # Check if currently running
        with self.running_jobs_lock:
            schedule['is_running'] = schedule_id in self.running_jobs

        # Get next run from APScheduler
        job = self.scheduler.get_job(schedule_id)
        if job and job.next_run_time:
            schedule['next_run'] = job.next_run_time.isoformat()
            schedule['next_run_display'] = job.next_run_time.strftime('%Y-%m-%d %H:%M')
        else:
            schedule['next_run_display'] = 'N/A' if schedule.get('enabled') else 'Paused'

        # Format recurrence for display
        schedule['recurrence_display'] = self._format_recurrence(schedule.get('recurrence', {}))

        # Format last run
        schedule['last_run_display'] = self._format_datetime(schedule.get('last_run'))

        # Determine status
        if schedule.get('is_running'):
            schedule['status'] = 'running'
        elif not schedule.get('enabled', True):
            schedule['status'] = 'paused'
        else:
            schedule['status'] = 'scheduled'

        return schedule

    def _format_recurrence(self, recurrence: Dict) -> str:
        """Format recurrence config for human display."""
        if not recurrence:
            return 'Unknown'

        rec_type = recurrence.get('type', '')

        if rec_type == 'once':
            dt_str = recurrence.get('datetime', 'N/A')
            try:
                dt = datetime.fromisoformat(dt_str)
                return f"Once at {dt.strftime('%Y-%m-%d %H:%M')}"
            except:
                return f"Once at {dt_str}"

        elif rec_type == 'hourly':
            minute = recurrence.get('minute', 0)
            return f"Hourly at :{minute:02d}"

        elif rec_type == 'daily':
            return f"Daily at {recurrence.get('time', 'N/A')}"

        elif rec_type == 'weekly':
            days = recurrence.get('days', [])
            day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
            day_str = ', '.join(day_names[d] for d in days if 0 <= d < 7)
            return f"Weekly on {day_str} at {recurrence.get('time', 'N/A')}"

        elif rec_type == 'monthly':
            day = recurrence.get('day', 1)
            return f"Monthly on day {day} at {recurrence.get('time', 'N/A')}"

        elif rec_type == 'custom':
            minutes = recurrence.get('interval_minutes', 60)
            if minutes >= 60:
                hours = minutes // 60
                mins = minutes % 60
                if mins:
                    return f"Every {hours}h {mins}m"
                return f"Every {hours} hour{'s' if hours > 1 else ''}"
            return f"Every {minutes} minute{'s' if minutes > 1 else ''}"

        return rec_type.title()

    def _format_datetime(self, dt_str: str) -> str:
        """Format datetime string for display."""
        if not dt_str:
            return 'Never'
        try:
            dt = datetime.fromisoformat(dt_str)
            return dt.strftime('%Y-%m-%d %H:%M')
        except:
            return str(dt_str)


def build_recurrence_config(form_data: Dict) -> Dict:
    """
    Build recurrence configuration from form data.

    Args:
        form_data: Dict from request.form

    Returns:
        Recurrence config dict
    """
    rec_type = form_data.get('recurrence_type', 'once')

    config = {'type': rec_type}

    if rec_type == 'once':
        config['datetime'] = form_data.get('once_datetime', '')

    elif rec_type == 'hourly':
        config['minute'] = int(form_data.get('hourly_minute', 0))

    elif rec_type == 'daily':
        config['time'] = form_data.get('daily_time', '09:00')

    elif rec_type == 'weekly':
        # Days come as multiple checkbox values
        days = form_data.getlist('weekly_days') if hasattr(form_data, 'getlist') else []
        config['days'] = [int(d) for d in days] if days else [0]
        config['time'] = form_data.get('weekly_time', '09:00')

    elif rec_type == 'monthly':
        config['day'] = int(form_data.get('monthly_day', 1))
        config['time'] = form_data.get('monthly_time', '09:00')

    elif rec_type == 'custom':
        config['interval_minutes'] = int(form_data.get('custom_minutes', 60))

    return config
