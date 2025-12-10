/**
 * Ansible Web Interface - Schedules Page JavaScript
 *
 * Handles schedule actions (pause, resume, delete, stop) via API calls.
 * Works with WebSocket events for real-time updates.
 */

/**
 * Pause a schedule
 * @param {string} scheduleId - Schedule UUID
 */
function pauseSchedule(scheduleId) {
    if (!confirm('Pause this schedule? It will no longer run until resumed.')) {
        return;
    }

    fetch(`/api/schedules/${scheduleId}/pause`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Failed to pause schedule');
        }
    })
    .catch(error => {
        console.error('Error pausing schedule:', error);
        alert('Error pausing schedule');
    });
}

/**
 * Resume a paused schedule
 * @param {string} scheduleId - Schedule UUID
 */
function resumeSchedule(scheduleId) {
    fetch(`/api/schedules/${scheduleId}/resume`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('Failed to resume schedule');
        }
    })
    .catch(error => {
        console.error('Error resuming schedule:', error);
        alert('Error resuming schedule');
    });
}

/**
 * Delete a schedule
 * @param {string} scheduleId - Schedule UUID
 * @param {string} scheduleName - Schedule name for confirmation dialog
 */
function deleteSchedule(scheduleId, scheduleName) {
    if (!confirm(`Delete schedule "${scheduleName}"?\n\nThis action cannot be undone.`)) {
        return;
    }

    fetch(`/api/schedules/${scheduleId}/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Remove row from table (WebSocket will also trigger this)
            const row = document.querySelector(`[data-schedule-id="${scheduleId}"]`);
            if (row) {
                row.remove();
            }
        } else {
            alert('Failed to delete schedule');
        }
    })
    .catch(error => {
        console.error('Error deleting schedule:', error);
        alert('Error deleting schedule');
    });
}

/**
 * Stop a currently running scheduled job
 * @param {string} scheduleId - Schedule UUID
 */
function stopSchedule(scheduleId) {
    if (!confirm('Stop this running playbook?\n\nThe playbook will be terminated.')) {
        return;
    }

    fetch(`/api/schedules/${scheduleId}/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update UI - status will change via WebSocket
            const row = document.querySelector(`[data-schedule-id="${scheduleId}"]`);
            if (row) {
                const badge = row.querySelector('[data-status]');
                if (badge) {
                    badge.textContent = 'stopping';
                    badge.className = 'status-badge status-running';
                }
            }
        } else {
            alert('Failed to stop scheduled run (may have already completed)');
        }
    })
    .catch(error => {
        console.error('Error stopping schedule:', error);
        alert('Error stopping scheduled run');
    });
}

/**
 * Run a schedule immediately (manual trigger)
 * Currently not implemented - would need backend support
 */
function runScheduleNow(scheduleId) {
    alert('Manual run not yet implemented. Use the main dashboard to run playbooks.');
}
