#!/usr/bin/env python3
"""End-to-end browser test: interacting with /s must never leave /s.

Run:
    FONTCONFIG_FILE=/tmp/fc/fonts.conf \
    LD_LIBRARY_PATH=/tmp/chromedeps/root/usr/lib/x86_64-linux-gnu \
    /tmp/schedvenv/bin/python tests/e2e_scheduler.py

See docs/scheduler/RUNBOOK.md for how the browser was installed without root.

Note: `page.fill()` does not work against chrome-headless-shell in this
environment — the value silently stays empty. The element is fine (setting
`.value` from JS works), so the passcode is entered that way.
"""

import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get("SCHED_URL", "https://www.davidseheonchang.xyz")
PASSCODE = os.environ.get("SCHED_PASSCODE", "1219")

fails = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name)
    if not cond:
        fails.append(name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True
    )
    page = ctx.new_page()
    navigations = []
    errors = []
    page.on(
        "framenavigated",
        lambda f: f == page.main_frame and navigations.append(f.url),
    )
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))

    page.goto(BASE + "/s", wait_until="domcontentloaded")
    check("login gate shown", page.title() == "Locked")

    with page.expect_navigation():
        page.evaluate(
            "document.querySelector('#password').value=%r;"
            "document.forms[0].submit()" % PASSCODE
        )
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1200)

    check("landed on /s after login", page.url.endswith("/s"))
    check("calendar rendered", page.locator(".cell").count() == 42)
    check("add button present", page.locator("#add").count() == 1)

    def still_on_s(label):
        check(f"{label} stays on /s", page.url.endswith("/s"))
        check(f"{label} triggers no navigation", not navigations)

    # The reported symptom: interacting with the calendar navigated away.
    navigations.clear()
    page.locator(".cell").nth(9).click()
    page.wait_for_timeout(1500)
    still_on_s("calendar cell click")
    check("cell click switches to day view", page.evaluate("view") == "day")

    for label, selector in [
        ("week view", ".views button[data-view=week]"),
        ("month view", ".views button[data-view=month]"),
        ("today", "#today"),
        ("next", "#next"),
        ("prev", "#prev"),
    ]:
        navigations.clear()
        page.locator(selector).click()
        page.wait_for_timeout(700)
        still_on_s(label)

    # Return to the current month first: the new-event dialog seeds its date
    # from the anchor, so adding while parked on a past month would create the
    # event outside the loaded window and it would not appear in `events`.
    page.locator("#today").click()
    page.wait_for_timeout(900)

    # Creating an event is where the user first saw it happen.
    navigations.clear()
    page.locator("#add").click()
    page.wait_for_timeout(500)
    page.evaluate("document.querySelector('#e-title').value='e2e probe'")
    page.locator("#e-save").click()
    page.wait_for_timeout(2000)
    still_on_s("saving a new event")

    created = page.evaluate("events.filter(e => e.title === 'e2e probe').length")
    check("event actually created", created >= 1)

    # Clean up through the UI so the test leaves nothing behind.
    page.evaluate(
        """async () => {
        const mine = events.filter(e => e.title === 'e2e probe');
        for (const e of mine)
          await fetch('/api/events/' + e.id, {method:'DELETE', credentials:'same-origin'});
    }"""
    )
    page.wait_for_timeout(800)

    check("no JS errors", not errors)
    if errors:
        print("  errors:", errors)

    browser.close()

print()
print("FAILED: " + ", ".join(fails) if fails else "ALL CHECKS PASSED")
sys.exit(1 if fails else 0)
