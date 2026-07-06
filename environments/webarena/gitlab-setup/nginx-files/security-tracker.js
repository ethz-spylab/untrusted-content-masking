// Security Tracker for logging security events and task completions

(function() {
    'use strict';

    window.SecurityTracker = {
        /**
         * Log a custom event
         * @param {string} action - The action name
         * @param {object} data - Additional data to log
         */
        logEvent: function(action, data) {
            const eventData = {
                timestamp: new Date().toISOString(),
                action: action,
                ...data
            };
            
            console.log('[SecurityTracker]', action, data);
            
            // Send to log server in the format expected by tasks/task_eval.py.
            fetch('/logs/write', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    appName: 'gitlab_vwa',
                    eventType: 'custom_event',
                    timestamp: new Date().toISOString(),
                    data: eventData
                })
            }).catch(err => {
                console.error('Failed to log event:', err);
            });
        },

        /**
         * Log task completion
         * @param {object} taskData - Task completion data
         */
        onTaskComplete: function(taskData) {
            console.log('[SecurityTracker] Task Complete:', taskData);
            
            // Send to log server in the format expected by tasks/task_eval.py.
            fetch('/logs/write', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    appName: 'gitlab_vwa',
                    eventType: 'task_complete',
                    timestamp: new Date().toISOString(),
                    data: {
                        timestamp: new Date().toISOString(),
                        ...taskData
                    }
                })
            }).catch(err => {
                console.error('Failed to log task completion:', err);
            });
        }
    };
})();
