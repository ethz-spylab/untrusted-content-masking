// Reveal/mask runtime for the WebArena GitLab proxy. data-untrusted-element
// is the marker attribute that flags an element as participating in the
// mask/reveal system; flagged elements are hidden initially. Clicks on a
// flagged element forward to any underlying link/button but keep the content
// hidden. Reveal happens only via the Q-Model tool call (programmatic).

(function() {
    'use strict';

    // Fix https:// links globally — GitLab WebIDE generates client-side links
    // with https:// but our proxy only serves http://
    document.addEventListener('click', function(e) {
        var link = e.target.closest('a');
        if (link && link.protocol === 'https:' && window.location.protocol === 'http:' && link.hostname === window.location.hostname) {
            e.preventDefault();
            link.href = link.href.replace(/^https:/, 'http:');
            window.location.href = link.href;
        }
    }, true);

    // Initialize on DOM load
    document.addEventListener('DOMContentLoaded', function() {
        initializeRevealSystem();
        publishElementMapOnce();
    });

    // Re-initialize when gitlab-marker finishes marking elements
    document.addEventListener('gitlab-marked', function(e) {
        console.log('[Reveal] GitLab marked', e.detail.count, 'elements - re-initializing');
        initializeRevealSystem();
        removePrehideCSS();
    });

    function removePrehideCSS() {
        var style = document.getElementById('gitlab-prehide-css');
        if (style) {
            style.remove();
            console.log('[Reveal] Removed pre-hide CSS');
        }
    }

    // Also periodically check for new marked elements (every 500ms)
    setInterval(function() {
        const unmarkedHiddenElements = document.querySelectorAll('[data-untrusted-element]:not([data-reveal-processed])');
        if (unmarkedHiddenElements.length > 0) {
            console.log('[Reveal] Found', unmarkedHiddenElements.length, 'new elements to hide');
            initializeRevealSystem();
        }
    }, 500);

    function initializeRevealSystem() {
        // Check URL parameters for reveal options
        const urlParams = new URLSearchParams(window.location.search);
        let maskUntrusted = urlParams.get('mask_untrusted') === 'true';
        let revealAll = urlParams.get('reveal_all') === 'true';
        
        // If reveal_all or mask_untrusted is set via URL, save to localStorage for subsequent pages
        if (revealAll) {
            localStorage.setItem('reveal_mode', 'all');
        } else if (maskUntrusted) {
            localStorage.setItem('reveal_mode', 'trusted');
        }
        
        // Check localStorage if not set via URL (for internal navigation)
        if (!revealAll && !maskUntrusted) {
            const storedMode = localStorage.getItem('reveal_mode');
            if (storedMode === 'all') {
                revealAll = true;
            } else if (storedMode === 'trusted') {
                maskUntrusted = true;
            }
        }
        
        // If reveal_all is true, skip all hiding logic entirely
        if (revealAll) {
            console.log('[Reveal] reveal_all=true - skipping all hiding logic');
            document.body.classList.remove('reveal-hiding-active');
            return;
        }
        
        // Signal that hiding is active (used by CSS to suppress popovers etc.)
        document.body.classList.add('reveal-hiding-active');
        
        // Find all elements that should be hidden initially (not already processed)
        const hiddenElements = document.querySelectorAll('[data-untrusted-element]:not([data-reveal-processed])');
        
        // Track per-tagName counters for unique QLLM IDs
        if (!window._revealTagCounters) window._revealTagCounters = {};
        
        hiddenElements.forEach(function(element) {
            // Mark as processed immediately to avoid double-processing
            element.setAttribute('data-reveal-processed', 'true');
            
            // Check if this is trusted content and should be revealed immediately
            const isTrusted = element.hasAttribute('data-trusted') && element.getAttribute('data-trusted') === 'true';
            const isUntrusted = element.hasAttribute('data-untrusted') && element.getAttribute('data-untrusted') === 'true';
            
            // If reveal_all is true, reveal everything (both trusted and untrusted)
            if (revealAll) {
                revealElement(element);
                return; // Skip the rest of the initialization for this element
            }
            
            // If mask_untrusted is true, reveal only trusted elements
            if (maskUntrusted && isTrusted) {
                // Reveal trusted elements immediately
                revealElement(element);
                return; // Skip the rest of the initialization for this element
            }
            
            // Get tag name for generating unique IDs
            const tagName = element.getAttribute('data-tag-name') || 
                           element.className.split(' ')[0] || 
                           element.id || 
                           'element';
            
            // Assign unique ID first (before checking localStorage)
            // Simple format: tagName-index (e.g., "file-name-0", "file-name-1")
            if (!element.hasAttribute('data-qllm-id')) {
                if (!(tagName in window._revealTagCounters)) window._revealTagCounters[tagName] = 0;
                const qllmId = `${tagName}-${window._revealTagCounters[tagName]++}`;
                element.setAttribute('data-qllm-id', qllmId);
            }
            const qllmIdForStorage = element.getAttribute('data-qllm-id');
            
            // Check if this element was previously revealed (from localStorage)
            // Use page-specific storage key so each page tracks reveals independently
            let wasRevealed = false;
            if (qllmIdForStorage && !revealAll) {
                try {
                    // Include current page path in storage key for context
                    const pageContext = window.location.pathname;
                    const storageKey = `revealed_${pageContext}_${qllmIdForStorage}`;
                    wasRevealed = localStorage.getItem(storageKey) === 'true';
                } catch (e) {
                    console.warn('Could not read from localStorage:', e);
                }
            }
            
            // If element was previously revealed, restore it
            if (wasRevealed) {
                revealElement(element);
                return; // Skip the rest of the initialization for this element
            }
            
            // Wrap bare text nodes in <span> so the CSS `> *` rule can hide them
            Array.from(element.childNodes).forEach(function(node) {
                if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
                    const wrapper = document.createElement('span');
                    wrapper.className = 'reveal-text-wrap';
                    node.parentNode.insertBefore(wrapper, node);
                    wrapper.appendChild(node);
                }
            });

            // Mark as hidden
            element.classList.add('reveal-hidden');
            
            // Get the already-assigned qllm-id for placeholder
            const qllmIdForPlaceholder = element.getAttribute('data-qllm-id');
            
            // Generate placeholder text if not explicitly provided.
            let placeholderText = `id: ${qllmIdForPlaceholder}`;
            
            if (!element.hasAttribute('data-reveal-placeholder') && !element.hasAttribute('data-reveal-hint')) {
                element.setAttribute('data-reveal-placeholder', placeholderText);
            }
            
            // Get the reveal trigger (the element itself or a specified trigger)
            const triggerSelector = element.getAttribute('data-reveal-trigger');
            const trigger = triggerSelector 
                ? document.querySelector(triggerSelector) 
                : element;
            
            if (trigger) {
                // DISABLED: Click-to-reveal is now disabled
                // Clicks forward to underlying links/buttons WITHOUT revealing content
                
                trigger.addEventListener('click', function(e) {
                    if (element.classList.contains('reveal-hidden')) {
                        // Find underlying link or button (child, self, OR parent)
                        const link = element.querySelector('a')
                            || (element.tagName === 'A' ? element : null)
                            || element.closest('a');
                        const button = element.querySelector('button')
                            || (element.tagName === 'BUTTON' ? element : null)
                            || element.closest('button');
                        const roleButton = element.closest('[role="button"]');
                        
                        if (link && link.href && link.getAttribute('href') !== '#') {
                            // Fix protocol mismatch (GitLab may generate https:// links but proxy runs on http://)
                            if (link.protocol === 'https:' && window.location.protocol === 'http:') {
                                link.href = link.href.replace(/^https:/, 'http:');
                            }
                            console.log('[Reveal] Forwarding click to link (content stays hidden):', link.href);
                            e.preventDefault();
                            e.stopPropagation();
                            if (link === element) {
                                // Element itself is the <a> — use direct navigation to avoid recursive handler loop
                                window.location.href = link.href;
                            } else {
                                link.click();
                            }
                        } else if (link && link.getAttribute('href') === '#') {
                            console.log('[Reveal] Allowing native click on href="#" link (content stays hidden)');
                            // Don't prevent — let GitLab's JS handlers fire
                        } else if (button) {
                            console.log('[Reveal] Forwarding click to button (content stays hidden)');
                            e.preventDefault();
                            e.stopPropagation();
                            button.click();
                        } else if (roleButton) {
                            console.log('[Reveal] Allowing click to propagate to role=button parent (content stays hidden)');
                            // Don't prevent — let click bubble to the role="button" handler (e.g. WebIDE file tree)
                        } else {
                            console.log('[Reveal] No actionable parent found, letting click propagate.');
                            // Don't block — let the event propagate in case a parent JS handler needs it
                        }
                    }
                });
                
                // Add visual indicator if specified
                if (element.hasAttribute('data-reveal-hint')) {
                    addRevealHint(trigger, element.getAttribute('data-reveal-hint'));
                }
            }
        });
    }

    // Publish a mapping from screen coordinates -> revealable elements to the log server.
    // This enables the agent to resolve a target element from (x,y) without clicking.
    let __elementMapPublished = false;
    function publishElementMapOnce() {
        if (__elementMapPublished) return;
        __elementMapPublished = true;
        try {
            // Delay slightly so layout settles
            setTimeout(publishElementMap, 250);
            // Also retry on load in case fonts/layout shift
            window.addEventListener('load', function() {
                setTimeout(publishElementMap, 250);
            }, { once: true });
        } catch (e) {
            // Best-effort only
        }
    }

    function publishElementMap() {
        try {
            const elements = Array.from(document.querySelectorAll('[data-untrusted-element]'));
            const map = [];

            // Firefox provides mozInnerScreenX/Y which align with xdotool coords in our setup.
            const viewportScreenX = (typeof window.mozInnerScreenX === 'number') ? window.mozInnerScreenX : 0;
            const viewportScreenY = (typeof window.mozInnerScreenY === 'number') ? window.mozInnerScreenY : 0;

            elements.forEach(function(el) {
                const rect = el.getBoundingClientRect();
                if (!rect || rect.width <= 0 || rect.height <= 0) return;

                const isTrusted = el.getAttribute('data-trusted') === 'true';
                const isUntrusted = el.getAttribute('data-untrusted') === 'true';
                const type = isUntrusted ? 'untrusted' : (isTrusted ? 'trusted' : 'unknown');
                const dataTagName = el.getAttribute('data-tag-name') || '';
                const qllmId = el.getAttribute('data-qllm-id') || '';

                const eventContainer = el.closest('[data-event-id]');
                const eventId = eventContainer ? parseInt(eventContainer.getAttribute('data-event-id')) : null;

                map.push({
                    id: qllmId,
                    type: type,
                    data_tag_name: dataTagName,
                    event_id: Number.isFinite(eventId) ? eventId : null,
                    bbox: {
                        left: Math.round(viewportScreenX + rect.left),
                        top: Math.round(viewportScreenY + rect.top),
                        right: Math.round(viewportScreenX + rect.right),
                        bottom: Math.round(viewportScreenY + rect.bottom),
                    }
                });
            });

            fetch('/logs/write', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    timestamp: new Date().toISOString(),
                    action: 'element_map',
                    elements: map
                })
            }).catch(() => {});
        } catch (e) {
            // Best-effort only
        }
    }

    function revealElement(element) {
        // Remove hidden class
        element.classList.remove('reveal-hidden');
        element.classList.add('reveal-visible');
        
        // Remove placeholder attribute to ensure placeholder text is not shown
        element.removeAttribute('data-reveal-placeholder');
        
        // Remove any reveal hints
        const hints = element.querySelectorAll('.reveal-hint');
        hints.forEach(hint => hint.remove());
        
        // Save revealed state to localStorage with page context (only if not reveal_all mode)
        const urlParams = new URLSearchParams(window.location.search);
        const revealAll = urlParams.get('reveal_all') === 'true';
        if (!revealAll) {
            const qllmId = element.getAttribute('data-qllm-id');
            if (qllmId) {
                try {
                    // Include current page path in storage key for page-specific tracking
                    const pageContext = window.location.pathname;
                    const storageKey = `revealed_${pageContext}_${qllmId}`;
                    localStorage.setItem(storageKey, 'true');
                } catch (e) {
                    console.warn('Could not save to localStorage:', e);
                }
            }
        }
        
        // Trigger custom event
        const event = new CustomEvent('elementRevealed', {
            detail: { element: element }
        });
        document.dispatchEvent(event);
        
        // Log for debugging (can be removed in production)
        console.log('Element revealed:', element);
    }

    function addRevealHint(trigger, hintText) {
        // Create hint overlay
        const hint = document.createElement('div');
        hint.className = 'reveal-hint';
        hint.textContent = hintText;
        
        // Position hint relative to trigger
        if (trigger) {
            trigger.style.position = 'relative';
            trigger.appendChild(hint);
        }
    }

    // Expose API for programmatic control
    window.RevealSystem = {
        reveal: function(selector) {
            const element = document.querySelector(selector);
            if (element && element.classList.contains('reveal-hidden')) {
                revealElement(element);
            }
        },
        hide: function(selector) {
            const element = document.querySelector(selector);
            if (element) {
                element.classList.add('reveal-hidden');
                element.classList.remove('reveal-visible');
            }
        },
        isRevealed: function(selector) {
            const element = document.querySelector(selector);
            return element && element.classList.contains('reveal-visible');
        }
    };
})();

