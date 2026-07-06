(function() {
    'use strict';
    if (window.__autoLoginRunning) return;
    window.__autoLoginRunning = true;

    var USERNAME = 'byteblaze';
    var PASSWORD = 'hello1234';

    function fillAndSubmit() {
        var tries = 0;
        var poll = setInterval(function() {
            if (++tries > 50) { clearInterval(poll); return; }
            var u = document.querySelector('#user_login, input[name="user[login]"]');
            var p = document.querySelector('#user_password, input[name="user[password]"]');
            var btn = document.querySelector('input[name="commit"], button[type="submit"]');
            if (u && p && btn) {
                clearInterval(poll);
                u.value = USERNAME; u.dispatchEvent(new Event('input', {bubbles:true}));
                p.value = PASSWORD; p.dispatchEvent(new Event('input', {bubbles:true}));
                setTimeout(function() { btn.click(); }, 300);
            }
        }, 100);
    }

    function run() {
        if (window.location.pathname === '/users/sign_in') {
            fillAndSubmit();
            return;
        }

        setTimeout(function() {
            var loggedIn = !!document.querySelector('a[href="/users/sign_out"]');

            if (loggedIn) {
                // Logged in — check if we need to bounce back to the original page
                var ret = sessionStorage.getItem('__alReturn');
                if (ret) {
                    sessionStorage.removeItem('__alReturn');
                    if (window.location.pathname !== ret) {
                        window.location.href = ret;
                    }
                }
                return;
            }

            // Not logged in — save where we are and go to sign-in
            var cur = window.location.pathname + window.location.search;
            if (!sessionStorage.getItem('__alReturn')) {
                sessionStorage.setItem('__alReturn', cur);
            }
            window.location.href = '/users/sign_in';
        }, 800);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', run);
    } else {
        run();
    }
})();
