/**
 * Format agent review JSON for display in the UI.
 * Used by log_view.html and job_status.html.
 */
(function(window) {
    function escapeHtml(s) {
        if (s == null) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function formatReviewForDisplay(review) {
        if (!review || typeof review !== 'object')
            return null;  /* fallback to JSON */

        var parts = [];

        if (review.summary) {
            parts.push('<div class="agent-review-summary" style="margin-bottom:12px;"><strong>Summary</strong><p style="margin:6px 0 0 0;">' + escapeHtml(review.summary) + '</p></div>');
        }

        if (review.status) {
            var statusColor = review.status === 'success' ? '#28a745' : (review.status === 'warning' ? '#fd7e14' : '#dc3545');
            parts.push('<div class="agent-review-status" style="margin-bottom:12px;"><strong>Status</strong> <span style="padding:2px 8px;border-radius:4px;background:' + statusColor + ';color:white;font-size:0.9em;">' + escapeHtml(review.status) + '</span></div>');
        }

        if (review.issues && review.issues.length > 0) {
            parts.push('<div class="agent-review-issues" style="margin-bottom:12px;"><strong>Issues</strong><ul style="margin:6px 0 0 0;padding-left:20px;">');
            review.issues.forEach(function(item) {
                var level = (item.level || 'info').toLowerCase();
                var levColor = level === 'error' ? '#dc3545' : (level === 'warning' ? '#fd7e14' : '#17a2b8');
                var taskPart = item.task ? ' <span style="color:var(--text-muted,#666);">(' + escapeHtml(item.task) + ')</span>' : '';
                parts.push('<li style="margin-bottom:6px;"><span style="padding:2px 6px;border-radius:3px;background:' + levColor + ';color:white;font-size:0.8em;margin-right:8px;">' + escapeHtml(level) + '</span>' + escapeHtml(item.message || '') + taskPart + '</li>');
            });
            parts.push('</ul></div>');
        }

        if (review.suggestions && review.suggestions.length > 0) {
            parts.push('<div class="agent-review-suggestions"><strong>Suggestions</strong><ul style="margin:6px 0 0 0;padding-left:20px;">');
            review.suggestions.forEach(function(s) {
                parts.push('<li style="margin-bottom:6px;">' + escapeHtml(s) + '</li>');
            });
            parts.push('</ul></div>');
        }

        if (parts.length === 0) return null;
        return parts.join('');
    }

    function formatReviewOrFallback(review) {
        var formatted = formatReviewForDisplay(review);
        if (formatted) return formatted;
        if (review && typeof review === 'object') return '<pre style="margin:0;white-space:pre-wrap;font-family:monospace;">' + escapeHtml(JSON.stringify(review, null, 2)) + '</pre>';
        return null;
    }

    window.formatAgentReview = formatReviewForDisplay;
    window.formatAgentReviewOrFallback = formatReviewOrFallback;
    window.escapeHtmlForAgent = escapeHtml;
})(window);
