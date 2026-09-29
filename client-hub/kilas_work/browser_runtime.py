"""Ephemeral, isolated Chromium contexts for a dedicated Kilas Work browser process.

This process intentionally has no database or OpenAI credentials. The Client Hub
owns authorization, durable checkpoints, model calls, files and cost accounting.
"""
import base64
import os
import time
from threading import RLock

from .browser_safety import BrowserSafetyError, classify_action, require_public_url


class BrowserRuntimeError(RuntimeError):
    pass


class BrowserRuntime:
    def __init__(self):
        self._lock = RLock()
        self._driver = None
        self._browser = None
        self._sessions = {}

    def _browser_instance(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright
            self._driver = sync_playwright().start()
            self._browser = self._driver.chromium.launch(headless=True)
        return self._browser

    @staticmethod
    def _gate(route):
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:blank")):
            route.continue_()
            return
        try:
            require_public_url(url)
        except BrowserSafetyError:
            route.abort()
            return
        route.continue_()

    def create(self, owner_id, job_id, url):
        require_public_url(url)
        key = (int(owner_id), int(job_id))
        with self._lock:
            self._cleanup()
            if key in self._sessions:
                return self.snapshot(owner_id, job_id)
            max_sessions = max(1, min(3, int(os.environ.get("WORK_BROWSER_MAX_SESSIONS", "1"))))
            if len(self._sessions) >= max_sessions:
                raise BrowserRuntimeError("Browser Work sedang penuh. Coba lagi sebentar.")
            browser = self._browser_instance()
            context = browser.new_context(viewport={"width": 1280, "height": 800},
                                          accept_downloads=True, service_workers="block")
            context.route("**/*", self._gate)
            page = context.new_page()
            record = {"context": context, "page": page, "downloads": [], "calls": {},
                      "created": time.monotonic()}
            self._sessions[key] = record
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.on("download", lambda download: self._capture_download(record, download))
                return self._snapshot(record)
            except Exception:
                self.close(owner_id, job_id)
                raise BrowserRuntimeError("Website belum dapat dibuka.") from None

    @staticmethod
    def _capture_download(record, download):
        try:
            if len(record["downloads"]) >= 4:
                return
            path = download.path()
            with open(path, "rb") as stream:
                raw = stream.read(8 * 1024 * 1024 + 1)
            if not raw or len(raw) > 8 * 1024 * 1024:
                return
            name = os.path.basename(download.suggested_filename or "unduhan")[:120]
            record["downloads"].append({"name": name, "content": raw})
        except Exception:
            return

    def _get(self, owner_id, job_id):
        record = self._sessions.get((int(owner_id), int(job_id)))
        if not record:
            raise BrowserRuntimeError("Sesi browser sudah berakhir. Mulai ulang pekerjaan dengan aman.")
        return record

    def _cleanup(self):
        expired = [key for key, record in self._sessions.items()
                   if time.monotonic() - record["created"] > 1800]
        for owner_id, job_id in expired:
            self.close(owner_id, job_id)

    @staticmethod
    def _snapshot(record):
        page = record["page"]
        return {"url": page.url, "screenshot": base64.b64encode(page.screenshot(type="png",
                timeout=10000, animations="disabled")).decode("ascii"),
                "downloads": [{"index": index, "name": item["name"]}
                              for index, item in enumerate(record["downloads"])]}

    def snapshot(self, owner_id, job_id):
        with self._lock:
            self._cleanup()
            return self._snapshot(self._get(owner_id, job_id))

    @staticmethod
    def _target(page, action):
        kind = action.get("type")
        if kind in ("click", "double_click"):
            x, y = int(action.get("x", -1)), int(action.get("y", -1))
            if not 0 <= x < 1280 or not 0 <= y < 800:
                raise BrowserSafetyError("Koordinat browser tidak valid.")
            return page.evaluate("""([x,y]) => { const e=document.elementFromPoint(x,y); if(!e) return {};
              const t=e.closest('button,a,input,[role=button],form')||e;
              return {text:(t.innerText||t.getAttribute('aria-label')||t.value||'').slice(0,300),
                      type:(t.getAttribute('type')||(t.tagName==='BUTTON'?'submit':'')).toLowerCase(),
                      form_text:(t.closest('form')?.innerText||'').slice(0,1000)}; }""", [x, y])
        if kind in ("type", "keypress"):
            return page.evaluate("""() => {const e=document.activeElement; return {
              text:(e?.getAttribute('aria-label')||e?.getAttribute('placeholder')||'').slice(0,300),
              type:(e?.getAttribute('type')||(e?.tagName==='BUTTON'?'submit':'')).toLowerCase(),
              form_text:(e?.closest('form')?.innerText||'').slice(0,1000)};}""")
        return {}

    @staticmethod
    def _apply(page, action):
        kind = action["type"]
        if kind == "click":
            page.mouse.click(int(action["x"]), int(action["y"]), button=action.get("button", "left"))
        elif kind == "double_click":
            page.mouse.dblclick(int(action["x"]), int(action["y"]), button=action.get("button", "left"))
        elif kind == "move":
            page.mouse.move(int(action["x"]), int(action["y"]))
        elif kind == "drag":
            path = action.get("path") or []
            if len(path) < 2 or len(path) > 30:
                raise BrowserSafetyError("Gerakan browser tidak valid.")
            page.mouse.move(int(path[0]["x"]), int(path[0]["y"]))
            page.mouse.down()
            for point in path[1:]:
                page.mouse.move(int(point["x"]), int(point["y"]))
            page.mouse.up()
        elif kind == "scroll":
            page.mouse.wheel(int(action.get("scroll_x") or 0), int(action.get("scroll_y") or 0))
        elif kind == "keypress":
            keys = action.get("keys") or []
            if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
                raise BrowserSafetyError("Tombol keyboard tidak valid.")
            page.keyboard.press("+".join(str(key) for key in keys))
        elif kind == "type":
            page.keyboard.type(str(action.get("text") or "")[:2000])
        elif kind == "wait":
            page.wait_for_timeout(min(10000, max(0, int(action.get("ms") or 500))))
        elif kind != "screenshot":
            raise BrowserSafetyError("Aksi browser tidak dikenal.")

    def actions(self, owner_id, job_id, actions, *, call_id, manual=False):
        if not isinstance(actions, list) or len(actions) > 12:
            raise BrowserSafetyError("Terlalu banyak aksi browser.")
        if not isinstance(call_id, str) or not 1 <= len(call_id) <= 100:
            raise BrowserSafetyError("Identitas aksi browser tidak valid.")
        with self._lock:
            self._cleanup()
            record = self._get(owner_id, job_id)
            prior = record["calls"].get(call_id)
            if prior and prior.get("result") is not None:
                return prior["result"]
            if not prior:
                prior = {"next": 0, "result": None}
                record["calls"][call_id] = prior
            page = record["page"]
            for index in range(prior["next"], len(actions)):
                action = actions[index]
                target = self._target(page, action)
                try:
                    page_text = page.locator("body").inner_text(timeout=3000)[:3000]
                except Exception:
                    page_text = ""
                decision = classify_action(action, target_text=target.get("text") or "",
                                           target_type=target.get("type") or "", page_text=page_text,
                                           form_text=target.get("form_text") or "")
                if decision != "ALLOW" and not manual:
                    prior["result"] = {"decision": decision, "next_action": index, **self._snapshot(record)}
                    return prior["result"]
                self._apply(page, action)
                prior["next"] = index + 1
                require_public_url(page.url)
            prior["result"] = {"decision": "CONTINUE", "next_action": len(actions), **self._snapshot(record)}
            return prior["result"]

    def upload(self, owner_id, job_id, filename, raw, mime_type):
        if not raw or len(raw) > 8 * 1024 * 1024:
            raise BrowserSafetyError("File unggahan tidak valid.")
        with self._lock:
            record = self._get(owner_id, job_id)
            record["page"].locator("input[type=file]").first.set_input_files(
                {"name": os.path.basename(filename)[:120], "mimeType": mime_type, "buffer": raw})
            return self._snapshot(record)

    def download(self, owner_id, job_id, index):
        with self._lock:
            record = self._get(owner_id, job_id)
            try:
                return record["downloads"].pop(int(index))
            except (IndexError, ValueError):
                raise BrowserRuntimeError("Unduhan tidak ditemukan.") from None

    def close(self, owner_id, job_id):
        with self._lock:
            record = self._sessions.pop((int(owner_id), int(job_id)), None)
            if record:
                record["context"].close()
                return True
            return False


runtime = BrowserRuntime()
