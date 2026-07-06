import subprocess
import time
import base64 as _b64
import json


class DockerComputer:
    environment = "linux"
    dimensions = (1280, 720)  # Default fallback; will be updated in __enter__.

    def __init__(
        self,
        container_name="cua-image",
        compose_file="docker-compose.yaml",
        service_name="agent",
        display=":99",
        port_mapping="5901:5901",
    ):
        self.container_name = container_name
        self.compose_file = compose_file
        self.service_name = service_name
        self.display = display
        self.port_mapping = port_mapping
        self._current_url = None  # Track current URL
        self._profile_dir = None  # Ephemeral Firefox profile per run (prevents state carryover)

    def __enter__(self):
        # Check if the container is running
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", f"name={self.container_name}"],
            capture_output=True,
            text=True,
        )

        if not result.stdout.strip():
            # Check if image exists
            image_check = subprocess.run(
                ["docker", "images", "-q", "hackathon-operator-agent"],
                capture_output=True,
                text=True,
            )
            
            if not image_check.stdout.strip():
                print(f"Agent container image not found - building for the first time...", flush=True)
            else:
                print(f"Starting agent container...", flush=True)
            
            # Start the container using docker compose - show output so user sees progress
            subprocess.run(
                ["docker", "compose", "-f", self.compose_file, "up", "-d", "agent"],
                check=True
            )
            # Give the containers a moment to start
            time.sleep(3)
            print("Agent container started", flush=True)

        # Close Firefox if running
        try:
            subprocess.run(
                ["docker", "compose", "-f", self.compose_file, "exec", "-T", self.service_name, 
                 "sh", "-c", f"DISPLAY={self.display} pkill firefox 2>/dev/null || true"],
                capture_output=True,
                check=False
            )
        except:
            pass
        
        # Fetch display geometry
        geometry = self._exec(
            f"DISPLAY={self.display} xdotool getdisplaygeometry"
        ).strip()
        if geometry:
            w, h = geometry.split()
            self.dimensions = (int(w), int(h))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Container is left running on exit.
        # To stop it, uncomment the line below:
        # subprocess.check_call(["docker compose", "-f", self.compose_file, "down"])
        pass

    def _exec(self, cmd: str) -> str:
        """
        Run 'cmd' in the container.
        We wrap cmd in double quotes and escape any double quotes inside it,
        so spaces or quotes don't break the shell call.
        """
        # Escape any existing double quotes in cmd
        safe_cmd = cmd.replace('"', '\\"')

        # Then wrap the entire cmd in double quotes for `sh -c`
        # Use docker compose exec for the specific service
        docker_cmd = f'docker compose -f {self.compose_file} exec -T {self.service_name} sh -c "{safe_cmd}"'

        return subprocess.check_output(docker_cmd, shell=True).decode(
            "utf-8", errors="ignore"
        )

    def screenshot(self) -> str:
        """
        Takes a screenshot with ImageMagick (import), returning base64-encoded PNG.
        Requires 'import'.
        If Firefox appears broken, restart it first.
        """
        # Check if Firefox is running, if not and we have a URL, restart it
        if not self._is_firefox_running() and self._current_url:
            print("[DockerComputer] Firefox not running, restarting...")
            self._restart_firefox(self._current_url)
        
        cmd = (
            f"export DISPLAY={self.display} && "
            "import -window root png:- | base64 -w 0"
        )

        return self._exec(cmd)

    def click(self, x: int, y: int, button: str = "left") -> None:
        button_map = {"left": 1, "middle": 2, "right": 3}
        b = button_map.get(button, 1)
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y} click {b}")

    def double_click(self, x: int, y: int) -> None:
        self._exec(
            f"DISPLAY={self.display} xdotool mousemove {x} {y} click --repeat 2 1"
        )

    def scroll(self, x: int, y: int, scroll_x: int, scroll_y: int) -> None:
        """
        Scroll via xdotool: button 4 = up, button 5 = down.

        Some models (e.g. OpenAI computer-use-preview) send pixel offsets
        (scroll_y=363) while others (Claude) send small click counts
        (scroll_y=3).  We normalise large values to wheel clicks (~100 px
        per notch) and batch them into a single _exec call.
        """
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y}")
        if scroll_y == 0:
            return
        # Treat values > 20 as pixel offsets, convert to wheel clicks
        if abs(scroll_y) > 20:
            clicks = max(1, abs(scroll_y) // 100)
        else:
            clicks = abs(scroll_y)
        clicks = min(clicks, 30)  # safety cap
        button = 4 if scroll_y < 0 else 5
        click_cmds = " ".join(f"click {button}" for _ in range(clicks))
        self._exec(f"DISPLAY={self.display} xdotool {click_cmds}")

    def type(self, text: str) -> None:
        """
        Type the given text via xdotool. Falls back to clipboard paste
        for non-ASCII characters (emojis, CJK, etc.) that xdotool can't handle.
        """
        if text.isascii():
            safe_text = text.replace("'", "'\\''")
            cmd = f"DISPLAY={self.display} xdotool type -- '{safe_text}'"
            self._exec(cmd)
        else:
            safe_text = text.replace("'", "'\\''")
            self._exec(
                f"printf '%s' '{safe_text}' | "
                f"DISPLAY={self.display} xclip -selection clipboard"
            )
            self._exec(f"DISPLAY={self.display} xdotool key ctrl+v")
            time.sleep(0.3)

    def wait(self, ms: int = 1000) -> None:
        time.sleep(ms / 1000)

    def move(self, x: int, y: int) -> None:
        self._exec(f"DISPLAY={self.display} xdotool mousemove {x} {y}")

    def keypress(self, keys: list[str]) -> None:
        mapping = {
            "ENTER": "Return",
            "LEFT": "Left",
            "RIGHT": "Right",
            "UP": "Up",
            "DOWN": "Down",
            "ESC": "Escape",
            "SPACE": "space",
            "BACKSPACE": "BackSpace",
            "TAB": "Tab",
        }
        mapped_keys = [mapping.get(key, key) for key in keys]
        combo = "+".join(mapped_keys)
        self._exec(f"DISPLAY={self.display} xdotool key {combo}")

    def drag(self, path: list) -> None:
        if not path:
            return

        def _xy(point):
            if isinstance(point, dict):
                return int(point["x"]), int(point["y"])
            return int(point[0]), int(point[1])

        start_x, start_y = _xy(path[0])
        self._exec(
            f"DISPLAY={self.display} xdotool mousemove {start_x} {start_y} mousedown 1"
        )
        for point in path[1:]:
            px, py = _xy(point)
            self._exec(f"DISPLAY={self.display} xdotool mousemove {px} {py}")
        self._exec(f"DISPLAY={self.display} xdotool mouseup 1")
    
    def _is_firefox_running(self) -> bool:
        """Check if Firefox is currently running."""
        try:
            result = self._exec(f"pgrep -f firefox-esr")
            return bool(result.strip())
        except:
            return False
    
    def _restart_firefox(self, url: str = None) -> None:
        """Restart Firefox - kill existing instance and start fresh."""
        # Kill Firefox completely
        self._exec(f"DISPLAY={self.display} pkill -9 firefox 2>/dev/null || true")
        time.sleep(1)
        self._exec(f"pkill -9 firefox 2>/dev/null || true")
        time.sleep(1)

        # Remove any previous ephemeral profile directory
        if self._profile_dir:
            try:
                self._exec(f"rm -rf '{self._profile_dir}' 2>/dev/null || true")
            except Exception:
                pass
            self._profile_dir = None

        # Create a fresh profile each time. This prevents state (cookies/localStorage)
        # from persisting across runs (e.g. reveal.js stores revealed elements in localStorage).
        try:
            self._profile_dir = self._exec("mktemp -d /tmp/firefox-profile-XXXXXX").strip()
        except Exception:
            # Fallback: if mktemp is unavailable, use a timestamped folder
            self._profile_dir = f"/tmp/firefox-profile-{int(time.time())}"
            self._exec(f"mkdir -p '{self._profile_dir}' 2>/dev/null || true")
        
        # Clear Firefox lock files and crash reports that might cause issues
        self._exec(f"rm -rf ~/.mozilla/firefox/*/lock ~/.mozilla/firefox/*/*.lock 2>/dev/null || true")
        self._exec(f"rm -rf ~/.mozilla/firefox/*/Crash* 2>/dev/null || true")
        time.sleep(0.5)
        
        # If URL provided, open Firefox with it
        if url:
            self._current_url = url
            # Start Firefox with safe flags to prevent crashes
            # --no-remote: don't connect to existing Firefox instance
            # --new-instance: start a new instance
            # --width/--height: set window size
            # --safe-mode is omitted to avoid the safe mode dialog
            firefox_cmd = (
                f"DISPLAY={self.display} firefox-esr "
                f"--no-remote --new-instance "
                f"-profile '{self._profile_dir}' "
                f"--width 1280 --height 800 "
                f"'{url}' >/tmp/firefox.log 2>&1 &"
            )
            self._exec(firefox_cmd)
            if 'gitlab-vwa.com' in url:
                time.sleep(8)  # GitLab CE is heavy; give it extra time to render
            else:
                time.sleep(3)  # Wait for Firefox to fully start
            
            # Verify Firefox actually started
            max_retries = 5
            for i in range(max_retries):
                if self._is_firefox_running():
                    # Try to focus the window
                    try:
                        self._exec(f"DISPLAY={self.display} xdotool search --name 'Mozilla Firefox' windowactivate 2>/dev/null || true")
                    except:
                        pass
                    break
                else:
                    if i < max_retries - 1:
                        print(f"[DockerComputer] Firefox not started yet, retrying... ({i+1}/{max_retries})")
                        time.sleep(1)
                    else:
                        print("[DockerComputer] Warning: Firefox may not have started properly")
    
    def close_firefox(self) -> None:
        """Close Firefox completely."""
        self._exec(f"DISPLAY={self.display} pkill -9 firefox 2>/dev/null || true")
        self._exec(f"pkill -9 firefox 2>/dev/null || true")
        time.sleep(0.5)

        # Cleanup ephemeral profile directory
        if self._profile_dir:
            try:
                self._exec(f"rm -rf '{self._profile_dir}' 2>/dev/null || true")
            except Exception:
                pass
            self._profile_dir = None
    
    def goto(self, url: str) -> None:
        """Navigate to the specified URL.

        If Firefox is already running, uses the address bar to navigate
        (preserving session cookies). Otherwise starts a fresh instance.
        """
        self._current_url = url

        if self._is_firefox_running():
            self._navigate_via_address_bar(url)
        else:
            self._restart_firefox(url)

    def goto_fresh(self, url: str) -> None:
        """Start a brand-new Firefox profile and navigate to the URL.

        Used at the beginning of a task to ensure a clean state.
        """
        self._current_url = url
        self._restart_firefox(url)

    def _navigate_via_address_bar(self, url: str) -> None:
        """Navigate to *url* using Ctrl+L in the running Firefox instance."""
        self._exec(f"DISPLAY={self.display} xdotool key ctrl+l")
        time.sleep(0.3)
        self._exec(f"DISPLAY={self.display} xdotool key ctrl+a")
        time.sleep(0.1)
        safe_url = url.replace("'", "'\\''")
        if url.isascii():
            self._exec(f"DISPLAY={self.display} xdotool type --delay 5 -- '{safe_url}'")
        else:
            self._exec(
                f"printf '%s' '{safe_url}' | "
                f"DISPLAY={self.display} xclip -selection clipboard"
            )
            self._exec(f"DISPLAY={self.display} xdotool key ctrl+v")
            time.sleep(0.3)
        time.sleep(0.3)
        self._exec(f"DISPLAY={self.display} xdotool key Return")
        if 'gitlab-vwa.com' in url:
            time.sleep(5)
        else:
            time.sleep(3)
    
    def get_current_url(self) -> str:
        """Get the current URL from the browser.

        Reads URL from combined /get-page-state first (URL+HTML snapshot),
        then /get-current-url, then active address bar as fallback.
        If that is stale, falls back to reading Firefox's active address bar.
        Finally falls back to the last stored URL.
        """
        cached_url = ""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self._current_url or "")
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            if base_url and base_url != "://":
                page_state = self._get_cached_page_state(base_url)
                if page_state:
                    state_url = page_state.get("url", "").strip()
                    if (state_url and state_url.startswith("http") and len(state_url) < 2048
                            and "<html" not in state_url.lower()):
                        self._current_url = state_url
                        return state_url
                url = self._exec(f"curl -s '{base_url}/get-current-url'").strip()
                if (url and url.startswith('http') and len(url) < 2048
                        and '<html' not in url.lower()):
                    cached_url = url
        except Exception:
            pass

        # Robust fallback: read URL directly from active Firefox address bar.
        # This prevents stale/mismatched cache endpoint values from leaking
        # into final evaluation (e.g., wrong /dashboard/todos URL).
        if self._is_firefox_running():
            live_url = self._get_current_url_from_address_bar()
            if live_url:
                self._current_url = live_url
                return live_url

        if cached_url:
            self._current_url = cached_url
            return cached_url

        return self._current_url or ""

    def _get_cached_page_state(self, base_url: str) -> dict | None:
        """Fetch combined page state JSON from /get-page-state."""
        try:
            raw = self._exec(f"curl -s '{base_url}/get-page-state'")
            if not raw or "ERROR:" in raw:
                return None
            obj = json.loads(raw)
            if not isinstance(obj, dict):
                return None
            if not isinstance(obj.get("url"), str) or not isinstance(obj.get("html"), str):
                return None
            return obj
        except Exception:
            return None

    def wait_for_masking_ready(self, timeout_s: float = 3.5, poll_s: float = 0.3) -> bool:
        """
        Wait until reveal/marker scripts are active after a navigation/reload.

        This is a best-effort readiness probe used to avoid race conditions where
        the model sees an early screenshot before hiding has been applied.
        """
        try:
            from urllib.parse import urlparse
            parsed = urlparse(self._current_url or "")
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            if not parsed.scheme or not parsed.netloc:
                return False
        except Exception:
            return False

        deadline = time.time() + max(0.0, timeout_s)
        while time.time() < deadline:
            try:
                state = self._get_cached_page_state(base_url)
                if not state:
                    time.sleep(max(0.1, poll_s))
                    continue

                state_url = str(state.get("url", "")).lower()
                html = str(state.get("html", ""))
                has_qllm_id = bool(state.get("has_qllm_id"))

                # Auto-login transitions may temporarily sit on sign-in.
                if "/users/sign_in" in state_url or "sign_in" in state_url:
                    time.sleep(max(0.1, poll_s))
                    continue

                # Ready signals:
                # 1) qllm ids exist, OR
                # 2) reveal.js activated hiding mode, OR
                # 3) reveal-all inline mode marker is present.
                if has_qllm_id:
                    return True
                if "reveal-hiding-active" in html:
                    return True
                if 'localStorage.setItem("reveal_mode","all")' in html:
                    return True
            except Exception:
                pass

            time.sleep(max(0.1, poll_s))

        return False

    def _get_current_url_from_address_bar(self) -> str:
        """Read active Firefox tab URL via browser address bar."""
        temp_url_file = "/tmp/current_firefox_url.txt"
        temp_script = "/tmp/xdotool_read_url.sh"
        try:
            self._exec(f"rm -f {temp_url_file} {temp_script} 2>/dev/null")
            script = f"""#!/bin/sh
export DISPLAY={self.display}
xdotool search --sync --onlyvisible --class "firefox" windowactivate --sync
sleep 0.2
xdotool key ctrl+l
sleep 0.2
xdotool key ctrl+c
sleep 0.2
xclip -o -selection clipboard > {temp_url_file} 2>/dev/null || true
xdotool key Escape
"""
            b64 = _b64.b64encode(script.encode()).decode()
            self._exec(
                f"echo {b64} | base64 -d > {temp_script} && "
                f"chmod +x {temp_script} && {temp_script}"
            )
            url = self._exec(f"cat {temp_url_file} 2>/dev/null || echo ''").strip()
            self._exec(f"rm -f {temp_url_file} {temp_script} 2>/dev/null")
            if url.startswith("http") and len(url) < 2048 and "<html" not in url.lower():
                return url
        except Exception:
            pass
        return ""
    
    def get_html(self) -> str:
        """Get the rendered HTML content from the ACTUAL running Firefox instance (including opened modals)."""
        if not self._current_url:
            raise ValueError("No current URL available. Call goto() first.")
        
        # GitLab uses html-cache.js to expose rendered HTML via an nginx
        # endpoint (handles its async rendering); all other sites use xdotool.
        if 'gitlab-vwa.com' in self._current_url:
            return self._get_html_via_cache()
        else:
            return self._get_html_via_xdotool()

    def _get_html_via_cache(self) -> str:
        """Get HTML via the /get-rendered-html nginx endpoint."""
        # Extract HTML from the RUNNING Firefox instance that the model is using
        # This captures the exact state including any modals the model has opened
        try:
            # Use the /get-rendered-html endpoint (html-cache.js saves rendered HTML automatically).
            # Extract the base URL from current URL
            from urllib.parse import urlparse
            parsed_url = urlparse(self._current_url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            # Wait a moment for html-cache.js to save the HTML
            import time
            time.sleep(2)
            
            # Prefer coherent URL+HTML snapshot to avoid stale HTML for a newer URL.
            page_state = self._get_cached_page_state(base_url)
            if page_state:
                state_url = page_state.get("url", "").strip()
                state_html = page_state.get("html", "")

                def _norm(u: str) -> str:
                    try:
                        from urllib.parse import urlparse, parse_qsl, urlencode
                        p = urlparse(u)
                        q = urlencode(sorted(parse_qsl(p.query, keep_blank_values=True)))
                        path = p.path.rstrip("/") or "/"
                        return f"{p.scheme}://{p.netloc}{path}?{q}"
                    except Exception:
                        return u

                expected = _norm(self._current_url or "")
                got = _norm(state_url or "")
                if expected and got and expected == got and len(state_html) > 100 and "ERROR:" not in state_html:
                    if 'data-qllm-id' in state_html or 'data-untrusted-element' in state_html or len(state_html) > 5000:
                        self._current_url = state_url
                        print(f"[DockerComputer] Using coherent page state HTML ({len(state_html)} chars)")
                        return state_html
                elif expected and got and expected != got:
                    print(f"[DockerComputer] Ignoring stale page-state HTML (state_url={state_url}, expected={self._current_url})")

            # Fallback to the older /get-rendered-html endpoint if the
            # /get-page-state coherent snapshot above was unavailable.
            cache_url = f"{base_url}/get-rendered-html"
            try:
                html = self._exec(f"curl -s '{cache_url}'")
            except Exception as e:
                html = None
                print(f"[DockerComputer] Failed to fetch cached HTML from {cache_url}: {e}")

            if html and len(html) > 100 and "ERROR:" not in html:
                if 'data-qllm-id' in html or 'data-untrusted-element' in html:
                    print(f"[DockerComputer] Successfully extracted HTML from running Firefox ({len(html)} chars) - contains dynamic content")
                    return html
                elif len(html) > 5000:  # Large enough to be a real page
                    print(f"[DockerComputer] Successfully extracted HTML from running Firefox ({len(html)} chars)")
                    return html
                else:
                    print(f"[DockerComputer] Firefox extraction returned insufficient content: {len(html)} chars")
            else:
                print(f"[DockerComputer] Firefox extraction returned insufficient content or error: {html[:200] if html else 'None'}")

        except Exception as e:
            print(f"[DockerComputer] Firefox extraction failed: {e}")

        # Fallback to static HTML if extraction fails (but warn that dynamic content may be missing)
        print("[DockerComputer] WARNING: Falling back to static HTML (curl) - dynamic content may be missing!")
        print("[DockerComputer] This means qllm_id attributes set by JavaScript may not be present.")
        try:
            cmd = f"curl -s '{self._current_url}'"
            html = self._exec(cmd)
            if html and len(html) > 0:
                return html
        except Exception as e:
            print(f"[DockerComputer] curl fallback also failed: {e}")
        
        raise ValueError(f"Could not fetch HTML from {self._current_url}")
    
    # Sentinel used to split URL from HTML in the xdotool extraction output
    _XDOTOOL_URL_SEPARATOR = "<<<XDOTOOL_URL_SEP>>>"

    def _xdotool_extract_once(self) -> str | None:
        """Single attempt to extract rendered HTML + current URL from Firefox via DevTools + clipboard.

        Captures both ``document.documentElement.outerHTML`` and ``location.href``
        in one console command so we also get the real browser URL for free.
        The URL is split off and stored in ``self._current_url``.

        Uses base64-encoded script file to avoid nested shell quoting issues
        (the JS command and separator contain characters that break bash/sh quoting).
        """
        temp_html_file = "/tmp/current_page_html.txt"
        temp_script = "/tmp/xdtool_extract.sh"
        sep = self._XDOTOOL_URL_SEPARATOR
        try:
            self._exec(f"rm -f {temp_html_file} 2>/dev/null")

            # JS uses double quotes for the separator string (safe inside
            # single-quoted shell arguments — no quoting conflicts)
            js_cmd = f'copy(location.href + "{sep}" + document.documentElement.outerHTML)'

            script = f"""#!/bin/sh
export DISPLAY={self.display}
xdotool search --sync --onlyvisible --class "firefox" windowactivate --sync
sleep 0.2
xdotool key Escape
sleep 0.3
xdotool key F12
sleep 1.0
xdotool key ctrl+shift+k
sleep 0.8
xdotool type --delay 10 '{js_cmd}'
sleep 0.3
xdotool key Return
sleep 1.0
xdotool key F12
sleep 0.3
xclip -o -selection clipboard > {temp_html_file} 2>/dev/null || echo ERROR_XCLIP
"""
            # Base64-encode to bypass all quoting issues with _exec/sh -c
            b64 = _b64.b64encode(script.encode()).decode()
            self._exec(
                f"echo {b64} | base64 -d > {temp_script} && "
                f"chmod +x {temp_script} && {temp_script}"
            )
            raw = self._exec(f"cat {temp_html_file} 2>/dev/null || echo ''")
            self._exec(f"rm -f {temp_html_file} {temp_script} 2>/dev/null")

            if not raw or len(raw) < 100 or "ERROR" in raw:
                return None

            # Split URL from HTML
            if sep in raw:
                url_part, html = raw.split(sep, 1)
                url_part = url_part.strip()
                if url_part.startswith('http') and len(url_part) < 2048:
                    self._current_url = url_part
            else:
                html = raw

            if html and len(html) > 100:
                return html
        except Exception:
            pass
        return None

    def _get_html_via_xdotool(self) -> str:
        """Get the rendered HTML content from the ACTUAL running Firefox instance (including opened modals)."""
        if not self._current_url:
            raise ValueError("No current URL available. Call goto() first.")

        max_retries = 3
        for attempt in range(1, max_retries + 1):
            html = self._xdotool_extract_once()
            if html:
                print(f"[DockerComputer] Successfully extracted HTML from running Firefox ({len(html)} chars, attempt {attempt}/{max_retries})")
                return html
            else:
                if attempt < max_retries:
                    print(f"[DockerComputer] xdotool extraction attempt {attempt}/{max_retries} failed, retrying...")
                    time.sleep(1)
                else:
                    print(f"[DockerComputer] xdotool extraction failed after {max_retries} attempts")

        # Fallback to static HTML if all retries fail
        print("[DockerComputer] Falling back to static HTML (curl) — JS-generated content (qllm_ids) will be missing!")
        try:
            cmd = f"curl -s '{self._current_url}'"
            html = self._exec(cmd)
            if html and len(html) > 0:
                return html
        except Exception as e:
            print(f"[DockerComputer] curl fallback also failed: {e}")

        raise ValueError(f"Could not fetch HTML from {self._current_url}")