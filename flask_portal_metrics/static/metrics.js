/**
 * Flask-Portal-Metrics Client-Side Tracking
 * 
 * Provides automatic client-side metrics collection including:
 * - Page load timing
 * - Time on page
 * - Scroll depth tracking
 * - Form interaction tracking
 * 
 * Usage:
 *   PortalMetrics.init({
 *     endpoint: '/api/metrics/client',
 *     trackPageTime: true,
 *     trackScrollDepth: true,
 *     trackForms: true,
 *     sampleRate: 1.0,
 *     userId: null
 *   });
 */
(function(window, document) {
    'use strict';

    // Ensure PortalMetrics namespace exists
    var PortalMetrics = window.PortalMetrics || {};

    // Configuration defaults
    var config = {
        endpoint: '/api/metrics/client',
        trackPageTime: true,
        trackScrollDepth: true,
        trackForms: true,
        trackPerformance: true,
        sampleRate: 1.0,
        userId: null,
        sessionId: null,
        debug: false,
        sensitiveFields: ['password', 'token', 'secret', 'credit_card', 'cvv', 'ssn', 'api_key'],
        sendBeacon: true,
        batchInterval: 5000,  // ms between batch sends
        maxBatchSize: 10
    };

    // State
    var state = {
        initialized: false,
        pageLoadTime: Date.now(),
        maxScrollDepth: 0,
        formStartTimes: {},
        eventQueue: [],
        batchTimer: null
    };

    /**
     * Generate a unique session ID if not provided
     */
    function generateSessionId() {
        return 'xxxx-xxxx-xxxx-xxxx'.replace(/x/g, function() {
            return Math.floor(Math.random() * 16).toString(16);
        });
    }

    /**
     * Check if we should sample this session
     */
    function shouldSample() {
        if (config.sampleRate >= 1.0) return true;
        if (config.sampleRate <= 0) return false;
        
        // Use session-consistent sampling
        var sessionKey = 'pm_sample_' + (config.sessionId || 'default');
        var stored = sessionStorage.getItem(sessionKey);
        
        if (stored !== null) {
            return stored === 'true';
        }
        
        var sample = Math.random() < config.sampleRate;
        sessionStorage.setItem(sessionKey, sample.toString());
        return sample;
    }

    /**
     * Log debug messages
     */
    function debug() {
        if (config.debug && window.console && console.log) {
            console.log.apply(console, ['[PortalMetrics]'].concat(Array.prototype.slice.call(arguments)));
        }
    }

    /**
     * Send data to the server
     */
    function sendData(type, data) {
        if (!shouldSample()) {
            debug('Skipping due to sampling');
            return;
        }

        var payload = {
            type: type,
            data: Object.assign({}, data, {
                user_id: config.userId,
                session_id: config.sessionId,
                timestamp: new Date().toISOString()
            })
        };

        debug('Sending', type, payload);

        // Try sendBeacon for unload events
        if (config.sendBeacon && navigator.sendBeacon && type === 'page_metrics') {
            try {
                var blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
                navigator.sendBeacon(config.endpoint, blob);
                return;
            } catch (e) {
                debug('sendBeacon failed, falling back to fetch', e);
            }
        }

        // Use fetch API
        if (window.fetch) {
            fetch(config.endpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload),
                keepalive: true
            }).catch(function(e) {
                debug('Fetch error:', e);
            });
        } else if (window.XMLHttpRequest) {
            // Fallback for older browsers
            var xhr = new XMLHttpRequest();
            xhr.open('POST', config.endpoint, true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.send(JSON.stringify(payload));
        }
    }

    /**
     * Queue event for batched sending
     */
    function queueEvent(type, data) {
        state.eventQueue.push({ type: type, data: data, timestamp: Date.now() });
        
        if (state.eventQueue.length >= config.maxBatchSize) {
            flushEventQueue();
        }
    }

    /**
     * Flush queued events
     */
    function flushEventQueue() {
        if (state.eventQueue.length === 0) return;
        
        var events = state.eventQueue.splice(0, config.maxBatchSize);
        events.forEach(function(event) {
            sendData(event.type, event.data);
        });
    }

    /**
     * Calculate current scroll depth percentage
     */
    function calculateScrollDepth() {
        var scrollTop = window.pageYOffset || document.documentElement.scrollTop || document.body.scrollTop || 0;
        var scrollHeight = Math.max(
            document.body.scrollHeight,
            document.documentElement.scrollHeight,
            document.body.offsetHeight,
            document.documentElement.offsetHeight
        );
        var clientHeight = window.innerHeight || document.documentElement.clientHeight;
        
        if (scrollHeight <= clientHeight) {
            return 100;
        }
        
        var scrollPercent = Math.round((scrollTop / (scrollHeight - clientHeight)) * 100);
        return Math.min(100, Math.max(0, scrollPercent));
    }

    /**
     * Track scroll depth
     */
    function trackScroll() {
        var currentDepth = calculateScrollDepth();
        if (currentDepth > state.maxScrollDepth) {
            state.maxScrollDepth = currentDepth;
            debug('New max scroll depth:', state.maxScrollDepth);
        }
    }

    /**
     * Send page metrics on unload
     */
    function sendPageMetrics() {
        if (!config.trackPageTime) return;

        var timeOnPage = Date.now() - state.pageLoadTime;
        
        sendData('page_metrics', {
            page_url: window.location.href,
            page_title: document.title,
            time_on_page_ms: timeOnPage,
            scroll_depth_percent: state.maxScrollDepth,
            viewport_width: window.innerWidth,
            viewport_height: window.innerHeight,
            screen_width: window.screen ? window.screen.width : null,
            screen_height: window.screen ? window.screen.height : null
        });
    }

    /**
     * Check if field name is sensitive
     */
    function isSensitiveField(fieldName) {
        if (!fieldName) return false;
        var lowerName = fieldName.toLowerCase();
        return config.sensitiveFields.some(function(sensitive) {
            return lowerName.indexOf(sensitive) !== -1;
        });
    }

    /**
     * Get form identifier
     */
    function getFormName(form) {
        return form.getAttribute('data-pm-name') ||
               form.getAttribute('name') ||
               form.getAttribute('id') ||
               form.getAttribute('action') ||
               'unnamed_form';
    }

    /**
     * Track form interactions
     */
    function setupFormTracking() {
        if (!config.trackForms) return;

        // Track form focus events
        document.addEventListener('focusin', function(e) {
            var target = e.target;
            if (!target || !target.form) return;
            if (target.tagName !== 'INPUT' && target.tagName !== 'SELECT' && target.tagName !== 'TEXTAREA') return;
            
            var fieldName = target.getAttribute('name') || target.getAttribute('id');
            if (isSensitiveField(fieldName)) return;
            
            var formName = getFormName(target.form);
            
            // Record form start time
            if (!state.formStartTimes[formName]) {
                state.formStartTimes[formName] = Date.now();
            }
            
            queueEvent('form_metrics', {
                form_name: formName,
                field_name: fieldName,
                interaction_type: 'focus',
                page_url: window.location.href
            });
        }, true);

        // Track form blur events
        document.addEventListener('focusout', function(e) {
            var target = e.target;
            if (!target || !target.form) return;
            if (target.tagName !== 'INPUT' && target.tagName !== 'SELECT' && target.tagName !== 'TEXTAREA') return;
            
            var fieldName = target.getAttribute('name') || target.getAttribute('id');
            if (isSensitiveField(fieldName)) return;
            
            var formName = getFormName(target.form);
            
            queueEvent('form_metrics', {
                form_name: formName,
                field_name: fieldName,
                interaction_type: 'blur',
                page_url: window.location.href
            });
        }, true);

        // Track form submissions
        document.addEventListener('submit', function(e) {
            var form = e.target;
            if (!form || form.tagName !== 'FORM') return;
            
            var formName = getFormName(form);
            var startTime = state.formStartTimes[formName];
            var timeToComplete = startTime ? Date.now() - startTime : null;
            
            sendData('form_metrics', {
                form_name: formName,
                interaction_type: 'submit',
                completion_status: true,
                time_to_complete_ms: timeToComplete,
                page_url: window.location.href
            });
        }, true);

        // Track form validation errors
        document.addEventListener('invalid', function(e) {
            var target = e.target;
            if (!target || !target.form) return;
            
            var fieldName = target.getAttribute('name') || target.getAttribute('id');
            if (isSensitiveField(fieldName)) return;
            
            var formName = getFormName(target.form);
            
            sendData('form_metrics', {
                form_name: formName,
                field_name: fieldName,
                interaction_type: 'error',
                error_message: target.validationMessage || 'Validation error',
                page_url: window.location.href
            });
        }, true);
    }

    /**
     * Setup page unload tracking
     */
    function setupUnloadTracking() {
        // Use multiple events for better coverage
        var unloadSent = false;
        
        function handleUnload() {
            if (unloadSent) return;
            unloadSent = true;
            
            flushEventQueue();
            sendPageMetrics();
        }
        
        // Modern browsers
        if ('onvisibilitychange' in document) {
            document.addEventListener('visibilitychange', function() {
                if (document.visibilityState === 'hidden') {
                    handleUnload();
                }
            });
        }
        
        // Fallbacks
        window.addEventListener('beforeunload', handleUnload);
        window.addEventListener('unload', handleUnload);
        window.addEventListener('pagehide', handleUnload);
    }

    /**
     * Setup scroll tracking
     */
    function setupScrollTracking() {
        if (!config.trackScrollDepth) return;
        
        // Throttled scroll handler
        var scrollTimeout = null;
        window.addEventListener('scroll', function() {
            if (scrollTimeout) return;
            
            scrollTimeout = setTimeout(function() {
                trackScroll();
                scrollTimeout = null;
            }, 100);
        }, { passive: true });
        
        // Initial calculation
        trackScroll();
    }

    /**
     * Track performance metrics
     */
    function trackPerformance() {
        if (!config.trackPerformance) return;
        if (!window.performance || !window.performance.timing) return;
        
        // Wait for page to fully load
        window.addEventListener('load', function() {
            setTimeout(function() {
                var timing = window.performance.timing;
                var perfData = {
                    dns_time: timing.domainLookupEnd - timing.domainLookupStart,
                    connect_time: timing.connectEnd - timing.connectStart,
                    ttfb: timing.responseStart - timing.requestStart,
                    response_time: timing.responseEnd - timing.responseStart,
                    dom_interactive: timing.domInteractive - timing.navigationStart,
                    dom_complete: timing.domComplete - timing.navigationStart,
                    page_load_time: timing.loadEventEnd - timing.navigationStart
                };
                
                sendData('custom_event', {
                    event_name: 'page_performance',
                    metadata: perfData,
                    page_url: window.location.href
                });
            }, 100);
        });
    }

    /**
     * Initialize the tracker
     */
    PortalMetrics.init = function(options) {
        if (state.initialized) {
            debug('Already initialized');
            return;
        }

        // Merge options with defaults
        if (options) {
            Object.keys(options).forEach(function(key) {
                if (options[key] !== undefined) {
                    config[key] = options[key];
                }
            });
        }

        // Generate session ID if not provided
        if (!config.sessionId) {
            config.sessionId = generateSessionId();
        }

        // Check sampling
        if (!shouldSample()) {
            debug('Session not sampled');
            return;
        }

        debug('Initializing with config:', config);

        // Setup tracking
        setupScrollTracking();
        setupFormTracking();
        setupUnloadTracking();
        trackPerformance();

        // Setup batch timer
        state.batchTimer = setInterval(flushEventQueue, config.batchInterval);

        state.initialized = true;
        debug('Initialized successfully');
    };

    /**
     * Manually track a custom event
     */
    PortalMetrics.trackEvent = function(eventName, metadata) {
        if (!state.initialized && !config.endpoint) {
            console.warn('[PortalMetrics] Not initialized. Call PortalMetrics.init() first.');
            return;
        }

        sendData('custom_event', {
            event_name: eventName,
            metadata: metadata || {},
            page_url: window.location.href
        });
    };

    /**
     * Manually track a page view
     */
    PortalMetrics.trackPageView = function(pageUrl, pageTitle) {
        sendData('page_metrics', {
            page_url: pageUrl || window.location.href,
            page_title: pageTitle || document.title,
            time_on_page_ms: 0,
            scroll_depth_percent: 0,
            viewport_width: window.innerWidth,
            viewport_height: window.innerHeight
        });
    };

    /**
     * Set user ID after initialization
     */
    PortalMetrics.setUserId = function(userId) {
        config.userId = userId;
        debug('User ID set:', userId);
    };

    /**
     * Get current configuration
     */
    PortalMetrics.getConfig = function() {
        return Object.assign({}, config);
    };

    /**
     * Get current state
     */
    PortalMetrics.getState = function() {
        return {
            initialized: state.initialized,
            maxScrollDepth: state.maxScrollDepth,
            timeOnPage: Date.now() - state.pageLoadTime,
            queuedEvents: state.eventQueue.length
        };
    };

    // Expose to window
    window.PortalMetrics = PortalMetrics;

})(window, document);
