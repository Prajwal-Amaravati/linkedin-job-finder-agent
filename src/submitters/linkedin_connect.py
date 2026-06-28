"""
LinkedIn Connection Request Automation — Playwright-based browser automation
for sending connection requests to LinkedIn profiles.

Usage:
    from src.submitters.linkedin_connect import LinkedInConnect

    with LinkedInConnect() as connector:
        connector.ensure_logged_in()
        results = connector.connect_batch([
            {"url": "https://www.linkedin.com/in/some-person/", "note": "Hi, I'd love to connect!"},
            {"url": "https://www.linkedin.com/in/another-person/"},
        ])
        print(results)

IMPORTANT: LinkedIn enforces ~100 connection requests/week per account.
           Exceeding this may trigger account warnings or restrictions.
           Use conservatively (5-10/day max is safe).
"""

import csv
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils.config import load_config, get_candidate_info

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_DIR = os.path.expanduser("~/.linkedin-agent-profile")
DEFAULT_LOG_PATH = "output/connections_log.csv"
# LinkedIn's weekly hard limit — stay well below it
WEEKLY_LIMIT = 100


class LinkedInConnect:
    """
    Automate LinkedIn connection requests using Playwright.

    Designed to be used as a context manager:

        with LinkedInConnect() as connector:
            connector.ensure_logged_in()
            connector.connect_to_profile("https://linkedin.com/in/someone/")
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or load_config()
        candidate = get_candidate_info(self.config)
        connect_cfg = self.config.get("linkedin_connect", {})

        self.candidate_name = candidate.get("name", "")

        self.profile_dir = os.path.expanduser(
            connect_cfg.get("browser_profile_dir", DEFAULT_PROFILE_DIR)
        )
        self.delay_actions = connect_cfg.get("delay_between_actions", 3)
        self.delay_requests = connect_cfg.get("delay_between_requests", 10)
        self.max_per_run = connect_cfg.get("max_per_run", 10)
        self.screenshot_on_error = connect_cfg.get("screenshot_on_error", True)
        self.log_path = connect_cfg.get("log_path", DEFAULT_LOG_PATH)

        self._playwright = None
        self._context = None
        self._page = None

        self._ensure_log_file()

    # ── Browser Lifecycle ──────────────────────────────────────────

    def start_browser(self) -> None:
        """Launch a persistent Chromium browser with saved profile."""
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        os.makedirs(self.profile_dir, exist_ok=True)
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=False,
            channel="chromium",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        logger.info("Browser launched with profile: %s", self.profile_dir)

    def close_browser(self) -> None:
        """Close browser and cleanup."""
        try:
            if self._context:
                self._context.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as exc:
            logger.debug("Browser close error (safe to ignore): %s", exc)
        self._playwright = None
        self._context = None
        self._page = None
        logger.info("Browser closed")

    # ── Login ──────────────────────────────────────────────────────

    def ensure_logged_in(self) -> bool:
        """
        Check LinkedIn login status. If not logged in, open login page
        and wait up to 120 seconds for manual login.
        Returns True if logged in.
        """
        if not self._page:
            self.start_browser()

        page = self._page
        logger.info("Checking LinkedIn login status …")
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
        self._human_delay(2, 3)

        if self._is_logged_in():
            logger.info("Already logged in to LinkedIn")
            return True

        logger.info("Not logged in — opening login page …")
        logger.info("Please log in manually. Waiting up to 120 seconds …")
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)

        for i in range(60):
            time.sleep(2)
            if self._is_logged_in():
                logger.info("Login successful!")
                return True
            if i % 10 == 0 and i > 0:
                logger.info("Still waiting for login … (%d s elapsed)", i * 2)

        logger.error("Login timeout after 120 seconds")
        return False

    def _is_logged_in(self) -> bool:
        page = self._page
        try:
            url = page.url
            if any(p in url for p in ["/feed", "/mynetwork", "/messaging"]):
                nav = page.query_selector("header.global-nav, .global-nav__me")
                if nav:
                    return True
            if page.query_selector(".global-nav__me-photo, .feed-identity-module"):
                return True
        except Exception:
            pass
        return False

    # ── Connection Request ─────────────────────────────────────────

    def connect_to_profile(
        self,
        profile_url: str,
        note: Optional[str] = None,
    ) -> dict:
        """
        Send a connection request to a single LinkedIn profile URL.

        Args:
            profile_url: Full LinkedIn profile URL, e.g.
                         "https://www.linkedin.com/in/someone/"
            note: Optional personalized message to include (max 300 chars).
                  If None, sends without a note (faster, no character limit issue).

        Returns:
            dict with keys:
              - status: 'connected' | 'already_connected' | 'pending' |
                        'no_connect_button' | 'failed'
              - message: human-readable description
        """
        if not self._page:
            raise RuntimeError("Browser not started. Call start_browser() first.")

        page = self._page
        result = {"status": "failed", "message": "", "profile_url": profile_url}

        try:
            logger.info("Navigating to profile: %s", profile_url)
            page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
            self._human_delay(2, 4)

            # Redirect to login?
            if "/login" in page.url or "/authwall" in page.url:
                logger.warning("Redirected to login — re-authenticating …")
                if not self.ensure_logged_in():
                    result["message"] = "Login required but failed"
                    return result
                page.goto(profile_url, wait_until="domcontentloaded", timeout=30000)
                self._human_delay(2, 4)

            # Already connected?
            if self._is_already_connected():
                logger.info("Already connected with this person")
                result["status"] = "already_connected"
                result["message"] = "Already connected"
                self._log_connection(profile_url, "already_connected")
                return result

            # Pending request?
            if self._has_pending_request():
                logger.info("Connection request already pending")
                result["status"] = "pending"
                result["message"] = "Request already pending"
                self._log_connection(profile_url, "pending")
                return result

            # Find Connect button
            connect_btn = self._find_connect_button()
            if not connect_btn:
                logger.info("No Connect button found on profile: %s", profile_url)
                result["status"] = "no_connect_button"
                result["message"] = "Connect button not found (profile may restrict connections or show Follow only)"
                self._log_connection(profile_url, "no_connect_button")
                return result

            # Click Connect
            logger.info("Clicking Connect button …")
            connect_btn.click()
            self._human_delay(1, 2)

            # Handle the "How do you know X?" modal if it appears
            self._handle_how_do_you_know_modal()
            self._human_delay(1, 2)

            # Handle the "Add a note" modal
            sent = self._handle_add_note_modal(note)

            if sent:
                result["status"] = "connected"
                result["message"] = "Connection request sent"
                logger.info("Connection request sent to: %s", profile_url)
            else:
                result["status"] = "failed"
                result["message"] = "Could not complete connection request"
                logger.warning("Failed to send connection request to: %s", profile_url)
                if self.screenshot_on_error:
                    self._save_error_screenshot(profile_url)

        except Exception as exc:
            logger.error("Error connecting to %s: %s", profile_url, exc)
            result["status"] = "failed"
            result["message"] = str(exc)
            if self.screenshot_on_error:
                self._save_error_screenshot(profile_url)

        self._log_connection(profile_url, result["status"], note)
        return result

    def connect_batch(
        self,
        profiles: list[dict],
        dry_run: bool = False,
    ) -> dict:
        """
        Send connection requests to a list of profiles.

        Args:
            profiles: List of dicts, each with:
                      - url (required): LinkedIn profile URL
                      - note (optional): Personalized message string
            dry_run: If True, logs what would happen without clicking anything.

        Returns:
            Summary dict: {total, sent, skipped, failed, already_connected}
        """
        profiles = profiles[: self.max_per_run]
        summary = {
            "total": len(profiles),
            "sent": 0,
            "skipped": 0,
            "failed": 0,
            "already_connected": 0,
        }

        for i, profile in enumerate(profiles):
            url = profile.get("url", "").strip()
            note = profile.get("note")

            if not url:
                logger.warning("Skipping entry with no URL: %s", profile)
                summary["skipped"] += 1
                continue

            if dry_run:
                logger.info("[DRY-RUN] Would connect to: %s", url)
                summary["sent"] += 1
                continue

            logger.info("Processing %d/%d: %s", i + 1, len(profiles), url)
            result = self.connect_to_profile(url, note=note)

            status = result["status"]
            if status == "connected":
                summary["sent"] += 1
            elif status == "already_connected":
                summary["already_connected"] += 1
                summary["skipped"] += 1
            elif status in ("pending", "no_connect_button"):
                summary["skipped"] += 1
            else:
                summary["failed"] += 1

            # Polite delay between requests to avoid triggering rate limits
            if i < len(profiles) - 1:
                delay = random.uniform(self.delay_requests, self.delay_requests * 1.5)
                logger.info("Waiting %.1f seconds before next request …", delay)
                time.sleep(delay)

        logger.info(
            "Batch complete: %d sent, %d skipped, %d failed out of %d",
            summary["sent"],
            summary["skipped"],
            summary["failed"],
            summary["total"],
        )
        return summary

    # ── Button / Modal Detection ───────────────────────────────────

    def _find_connect_button(self):
        """
        Find the Connect button on a profile page.
        LinkedIn renders it in different places depending on profile layout.
        """
        page = self._page
        # Primary action buttons on profile header
        selectors = [
            # Top card primary button
            'button.pvs-profile-actions__action:has-text("Connect")',
            # Generic button text match
            'button:has-text("Connect")',
            # Aria-label variants
            'button[aria-label*="Connect"]',
            # Inside "More" dropdown (overflow menu)
        ]
        for sel in selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    return btn
            except Exception:
                continue

        # If not found directly, try the "More" overflow menu
        return self._find_connect_in_more_menu()

    def _find_connect_in_more_menu(self):
        """Open the 'More' overflow menu and look for Connect inside it."""
        page = self._page
        more_btn_selectors = [
            'button:has-text("More")',
            'button[aria-label*="More actions"]',
            '.pvs-profile-actions__action[aria-label*="More"]',
        ]
        for sel in more_btn_selectors:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    self._human_delay(1, 2)
                    # Now look for Connect in the dropdown
                    connect_in_menu = page.query_selector(
                        'div[role="menu"] span:has-text("Connect"), '
                        'li:has-text("Connect")'
                    )
                    if connect_in_menu and connect_in_menu.is_visible():
                        return connect_in_menu
                    # Dismiss menu if Connect not found
                    page.keyboard.press("Escape")
                    self._human_delay(0.5, 1)
            except Exception:
                continue
        return None

    def _handle_how_do_you_know_modal(self) -> None:
        """
        Handle the 'How do you know X?' modal that sometimes appears.
        Selects 'Other' as the relationship type if shown.
        """
        page = self._page
        try:
            modal = page.query_selector(
                '.send-invite__content, '
                '[data-test-modal]:has-text("How do you know")'
            )
            if not modal:
                return

            # Click "Other" option
            other_option = page.query_selector(
                'label:has-text("Other"), '
                'button:has-text("Other")'
            )
            if other_option and other_option.is_visible():
                other_option.click()
                self._human_delay(0.5, 1)

            # Click Next/Connect
            next_btn = page.query_selector(
                'button:has-text("Connect"), '
                'button:has-text("Next")'
            )
            if next_btn and next_btn.is_visible():
                next_btn.click()
                self._human_delay(1, 2)

        except Exception as exc:
            logger.debug("How-do-you-know modal: %s", exc)

    def _handle_add_note_modal(self, note: Optional[str] = None) -> bool:
        """
        Handle the 'Add a note' modal after clicking Connect.
        - If note is provided: types it and sends.
        - If no note: clicks 'Send without a note'.
        Returns True if the request was sent.
        """
        page = self._page
        try:
            # Wait briefly for modal to appear
            self._human_delay(1, 2)

            # Check if the add-note modal is present
            modal = page.query_selector(
                '.send-invite, '
                '[data-test-modal="send-invite"], '
                '.artdeco-modal:has-text("Add a note")'
            )

            if modal:
                if note:
                    # Click "Add a note" to open the text area
                    add_note_btn = page.query_selector(
                        'button:has-text("Add a note")'
                    )
                    if add_note_btn and add_note_btn.is_visible():
                        add_note_btn.click()
                        self._human_delay(0.5, 1)

                    # Find the textarea and type the note
                    textarea = page.query_selector(
                        'textarea#custom-message, '
                        'textarea[name="message"], '
                        'textarea[placeholder*="note"]'
                    )
                    if textarea:
                        # Trim note to LinkedIn's 300-char limit
                        trimmed = note[:300]
                        textarea.fill(trimmed)
                        logger.info("Added note (%d chars)", len(trimmed))
                        self._human_delay(0.5, 1)

                    # Click Send
                    send_btn = page.query_selector(
                        'button:has-text("Send"), '
                        'button[aria-label*="Send"]'
                    )
                    if send_btn and send_btn.is_visible():
                        send_btn.click()
                        self._human_delay(1, 2)
                        return True

                else:
                    # Send without a note
                    send_btn = page.query_selector(
                        'button:has-text("Send without a note"), '
                        'button[aria-label*="Send without a note"]'
                    )
                    if send_btn and send_btn.is_visible():
                        send_btn.click()
                        self._human_delay(1, 2)
                        return True

                    # Fallback: generic Send button
                    send_btn = page.query_selector('button:has-text("Send")')
                    if send_btn and send_btn.is_visible():
                        send_btn.click()
                        self._human_delay(1, 2)
                        return True

            else:
                # No modal appeared — request may have been sent directly
                # (some profiles trigger direct connect without a modal)
                self._human_delay(1, 2)
                return self._check_request_sent()

        except Exception as exc:
            logger.debug("Add-note modal handling: %s", exc)

        return False

    def _check_request_sent(self) -> bool:
        """Verify the connection request was sent by checking for 'Pending' state."""
        page = self._page
        try:
            pending = page.query_selector(
                'button:has-text("Pending"), '
                'span:has-text("Pending"), '
                '[aria-label*="Pending"]'
            )
            if pending:
                return True
        except Exception:
            pass
        return False

    def _is_already_connected(self) -> bool:
        """Check if already connected (1st degree)."""
        page = self._page
        try:
            indicators = [
                'span:has-text("1st")',
                '.dist-value:has-text("1st")',
                'button:has-text("Message")',   # Message button = already connected
            ]
            for sel in indicators:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    return True
        except Exception:
            pass
        return False

    def _has_pending_request(self) -> bool:
        """Check if a connection request is already pending."""
        page = self._page
        try:
            pending = page.query_selector(
                'button:has-text("Pending"), '
                'span:has-text("Pending"), '
                '[aria-label*="Pending"]'
            )
            if pending and pending.is_visible():
                return True
        except Exception:
            pass
        return False

    # ── Logging ────────────────────────────────────────────────────

    def _ensure_log_file(self) -> None:
        os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
        if not os.path.exists(self.log_path):
            with open(self.log_path, "w", newline="") as f:
                csv.writer(f).writerow(
                    ["timestamp", "profile_url", "status", "note_sent"]
                )

    def _log_connection(
        self, profile_url: str, status: str, note: Optional[str] = None
    ) -> None:
        try:
            with open(self.log_path, "a", newline="") as f:
                csv.writer(f).writerow(
                    [datetime.now().isoformat(), profile_url, status, bool(note)]
                )
        except Exception as exc:
            logger.error("Failed to log connection: %s", exc)

    def _save_error_screenshot(self, identifier: str) -> None:
        try:
            screenshot_dir = "output/screenshots"
            os.makedirs(screenshot_dir, exist_ok=True)
            safe_name = identifier.replace("/", "_").replace(":", "")[-40:]
            path = os.path.join(screenshot_dir, f"connect_error_{safe_name}.png")
            self._page.screenshot(path=path)
            logger.info("Error screenshot saved: %s", path)
        except Exception as exc:
            logger.debug("Could not save screenshot: %s", exc)

    # ── Helpers ────────────────────────────────────────────────────

    def _human_delay(self, min_s: float = 1.0, max_s: float = 3.0) -> None:
        time.sleep(random.uniform(min_s, max_s))

    # ── Context Manager ────────────────────────────────────────────

    def __enter__(self):
        self.start_browser()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close_browser()
        return False
