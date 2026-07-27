"""HTML shells for the scheduler pages.

Rendered server-side so gated pages never reach an unauthenticated browser.
Styling is deliberately plain and unbranded — nothing here should hint that
this belongs to the portfolio.
"""

import html

BASE_CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body {
  margin: 0; min-height: 100vh;
  display: flex; align-items: center; justify-content: center;
  padding: 1.5rem;
  background: #12151b; color: #e6e9ef;
  font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
}
.card {
  width: 100%; max-width: 22rem;
  background: #1a1f28; border: 1px solid #262d39;
  border-radius: 12px; padding: 1.5rem;
}
h1 { margin: 0 0 1.25rem; font-size: 1.05rem; font-weight: 600; letter-spacing: .02em; }
label { display: block; font-size: .8rem; color: #97a1b2; margin-bottom: .4rem; }
input[type=password] {
  width: 100%; padding: .75rem; margin-bottom: .9rem;
  background: #12151b; color: #e6e9ef;
  border: 1px solid #2f3846; border-radius: 8px;
  font-size: 1.1rem; letter-spacing: .3em; text-align: center;
}
input[type=password]:focus { outline: none; border-color: #4c7dfd; }
button {
  width: 100%; padding: .75rem;
  background: #3d6ef5; color: #fff;
  border: 0; border-radius: 8px;
  font-size: .95rem; font-weight: 600; cursor: pointer;
}
button:active { background: #3260e0; }
.error {
  margin-bottom: .9rem; padding: .6rem .7rem;
  background: #3a1d22; border: 1px solid #5d2b33; border-radius: 8px;
  color: #ffb4bd; font-size: .82rem;
}
.note { margin-top: 1rem; color: #6b7688; font-size: .75rem; text-align: center; }
"""

# `maximum-scale` is omitted on purpose: pinch-zoom must stay available.
HEAD = (
    '<meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    '<meta name="robots" content="noindex, nofollow">'
)


def login_page(scope: str, target: str, error: str = "") -> str:
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head>{HEAD}<title>Locked</title><style>{BASE_CSS}</style></head>
<body>
  <main class="card">
    <h1>Enter passcode</h1>
    {error_html}
    <form method="post" action="/api/login">
      <input type="hidden" name="scope" value="{html.escape(scope)}">
      <input type="hidden" name="next" value="{html.escape(target)}">
      <label for="password">Passcode</label>
      <input id="password" name="password" type="password"
             inputmode="numeric" autocomplete="current-password"
             autofocus required>
      <button type="submit">Unlock</button>
    </form>
    <p class="note">3 attempts, then a temporary lock.</p>
  </main>
</body></html>"""


def placeholder_page(title: str, path: str) -> str:
    """Temporary stub until the calendar UI lands in a later phase."""
    return f"""<!doctype html>
<html lang="en"><head>{HEAD}<title>{html.escape(title)}</title>
<style>{BASE_CSS}</style></head>
<body>
  <main class="card">
    <h1>{html.escape(title)}</h1>
    <p class="note">Phase 1 (auth) is live at <code>{html.escape(path)}</code>.<br>
    Calendar UI lands in a later phase.</p>
  </main>
</body></html>"""
