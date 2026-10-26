# -*- coding: utf-8 -*-
"""پوشکردنی داتاکان بۆ GitHub — بۆ پاراستنی داتا لە نێوان دانیشتەکانی GitHub Actions."""

import logging
import os
import subprocess
import threading
import time

log = logging.getLogger("gitsync")


class GitSync:
    """دوای هەر گۆڕانکارییەک notify() بانگ دەکرێت؛ دوای debounce چرکەیەک،
    فایلی داتا commit و push دەکرێت بۆ ڕیپۆکە (لە Actions بە GITHUB_TOKEN)."""

    def __init__(self, repo_dir: str, debounce: float = 8.0):
        self.repo_dir = repo_dir
        self.debounce = max(2.0, float(debounce))
        self.enabled = os.path.isdir(os.path.join(repo_dir, ".git"))
        self.push_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending = False
        self._worker = None
        if not self.enabled:
            log.info("Git repo نەدۆزرایەوە — داتا تەنها لە فایل هەڵدەگیرێت (بێ پوش).")

    # ---- API ----

    def notify(self):
        """دوای هەر گۆڕانکارییەکی داتا بانگ بکرێت (thread-safe)."""
        if not self.enabled:
            return
        with self._state_lock:
            self._pending = True
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._worker_loop, daemon=True)
                self._worker.start()

    def flush(self):
        """پوشی یەکسەر — لە کاتی داخستنی بۆت بەکاردێت بۆ ئەوەی هیچ گۆڕانکارییەک لەدەست نەچێت."""
        with self._state_lock:
            pending = self._pending
            self._pending = False
        if self.enabled and pending:
            try:
                self.push("bot: نوێکردنەوەی داتا (کۆتایی دانیشت)")
            except Exception as e:
                log.warning("flush push شکستی هێنا: %s", e)

    # ---- ناوخۆیی ----

    def _worker_loop(self):
        while True:
            time.sleep(self.debounce)
            with self._state_lock:
                if not self._pending:
                    continue
                self._pending = False
            try:
                self.push("bot: نوێکردنەوەی داتا")
            except Exception as e:
                log.warning("push شکستی هێنا: %s", e)

    def _git(self, *args, timeout=120):
        try:
            return subprocess.run(
                ["git", "-C", self.repo_dir] + list(args),
                capture_output=True, text=True, timeout=timeout,
            )
        except FileNotFoundError:
            return None

    def push(self, message: str):
        if not self.enabled:
            return  # دڵنیابوون لەوەی تەنها لە ڕیپۆی ڕاستەقینەدا کار بکات
        with self.push_lock:
            status = self._git("rev-parse", "--show-toplevel")
            if status.returncode != 0:
                return
            toplevel = (status.stdout or "").strip()
            if os.path.realpath(toplevel or "") != os.path.realpath(self.repo_dir):
                # ڕەتی دەکەینەوە لە commit لە ڕیپۆیەکی دایک (باشترە هیچ شتێک تێکنەدات)
                log.warning("ئاگاداری: ڕیپۆی ڕاستەقینە (%s) جیاوازە لە %s — push پشتگوێ خرا.",
                            toplevel, self.repo_dir)
                return
            status = self._git("status", "--porcelain", "--", "data")
            if status is None or status.returncode != 0:
                return
            if not status.stdout.strip():
                return  # هیچ گۆڕانکارییەک نییە

            self._git("add", "-A", "data")
            commit = self._git(
                "-c", "user.name=quiz-bot-data",
                "-c", "user.email=bot@users.noreply.github.com",
                "commit", "-m", message,
            )
            if commit.returncode != 0:
                log.warning("commit نەکرا: %s", (commit.stderr or commit.stdout or "").strip())
                return

            branch = "main"
            br = self._git("rev-parse", "--abbrev-ref", "HEAD")
            if br.returncode == 0 and br.stdout.strip():
                branch = br.stdout.strip()

            last_err = ""
            for _ in range(3):
                pushed = self._git("push", "origin", "HEAD:{}".format(branch))
                if pushed.returncode == 0:
                    log.info("داتاکان بۆ GitHub پوش کران ✅")
                    return
                last_err = (pushed.stderr or pushed.stdout or "").strip()
                log.warning("push نەکرا، دووبارە هەوڵدانەوە: %s", last_err)
                self._git("pull", "--rebase", "origin", branch)
                time.sleep(2)
            log.warning("push بە تەواوی شکستی هێنا: %s", last_err)
