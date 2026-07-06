// HTML Cache - Periodically saves rendered HTML for agent extraction
// This allows the agent to retrieve the fully rendered DOM without xdotool
(function() {
    'use strict';
    
    let lastSavedHtml = '';
    let lastSavedUrl = '';

    // Save URL + rendered HTML together to avoid URL/HTML mismatch races.
    function savePageState(url, html, hasQllmId) {
        try {
            var payload = JSON.stringify({
                url: url,
                html: html,
                ts: Date.now(),
                has_qllm_id: !!hasQllmId
            });
            fetch('/save-page-state', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: payload
            }).catch(function() {});
        } catch (e) {
            console.error('[HTML Cache] Failed to save page state:', e);
        }
    }
    
    // Function to save current HTML to server
    function saveRenderedHtml(force) {
        if (force === undefined) force = false;
        try {
            var url = window.location.href;
            var html = document.documentElement.outerHTML;
            
            // Save if different OR if forced OR if has qllm_id
            var hasQllmId = html.includes('data-qllm-id');
            var shouldSave = force || (html !== lastSavedHtml && html.length > 10000) || (url !== lastSavedUrl);
            
            if (shouldSave) {
                lastSavedHtml = html;
                lastSavedUrl = url;
                
                // Send to server endpoint
                fetch('/save-rendered-html', {
                    method: 'POST',
                    headers: {'Content-Type': 'text/html'},
                    body: html
                }).then(function(response) { return response.text(); })
                  .then(function(data) {
                      console.log('[HTML Cache] ' + data + ' (qllm_id: ' + hasQllmId + ')');
                  })
                  .catch(function(err) {
                      console.error('[HTML Cache] Failed to save:', err);
                  });

                // Save URL+HTML atomically for agent reads.
                savePageState(url, html, hasQllmId);
            }
        } catch (e) {
            console.error('[HTML Cache] Error:', e);
        }
    }
    
    // Start caching immediately and aggressively
    function startCaching() {
        console.log('[HTML Cache] Starting HTML cache system');
        
        // Save immediately after a short delay
        setTimeout(function() {
            saveRenderedHtml(true);  // Force first save
        }, 1000);
        
        // Periodic re-save to catch async marker updates after page load.
        setInterval(saveRenderedHtml, 2000);
        
        // Save on navigation
        var lastUrl = window.location.href;
        // Save initial state immediately
        saveRenderedHtml(true);
        setInterval(function() {
            if (window.location.href !== lastUrl) {
                lastUrl = window.location.href;
                console.log('[HTML Cache] Navigation detected, saving...');
                setTimeout(function() {
                    saveRenderedHtml(true);
                }, 1500);
            }
        }, 500);
        
        // Also save when the trust-label marker finishes (if it exists).
        setTimeout(function() {
            const hasQllmId = document.querySelectorAll('[data-qllm-id]').length > 0;
            if (hasQllmId) {
                console.log('[HTML Cache] Found qllm_id attributes, saving...');
                saveRenderedHtml(true);
            }
        }, 3000);
    }
    
    // Start as soon as possible
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', startCaching);
    } else {
        startCaching();
    }
})();
