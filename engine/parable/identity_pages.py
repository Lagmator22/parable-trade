from html import escape

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in - Parable</title>
<style>
:root {{ --bg: #ffffff; --ink: #0a0a0a; --muted: #5c5c5c; --line: #0a0a0a; --alert: #d9480f; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #0a0a0a; --ink: #f5f5f5; --muted: #a3a3a3; --line: #f5f5f5; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, sans-serif; }}
main {{ max-width: 460px; margin: 0 auto; padding: 48px 16px; }}
h1 {{ font-size: 28px; margin: 0 0 16px; letter-spacing: -0.02em; }}
.notice {{ border: 1px solid var(--line); padding: 12px 14px; margin-bottom: 24px; font-size: 14px; }}
.notice strong {{ display: block; font-family: ui-monospace, monospace; text-transform: uppercase; font-size: 12px; }}
label {{ display: block; margin-bottom: 16px; font-size: 14px; color: var(--muted); }}
input {{ display: block; width: 100%; margin-top: 4px; padding: 10px; font: inherit; color: var(--ink);
  background: var(--bg); border: 1px solid var(--line); border-radius: 0; }}
button {{ width: 100%; padding: 12px; font: inherit; font-weight: 600; cursor: pointer; border-radius: 0;
  color: var(--bg); background: var(--ink); border: 1px solid var(--ink); }}
.error {{ color: var(--alert); margin: 0 0 16px; font-size: 14px; }}
</style>
</head>
<body>
<main>
<h1>Sign in to sell on Parable</h1>
<div class="notice">
<strong>Demo sign-in</strong>
PayPal sandbox keys are not configured on this server, so this is a demo sign-in and not a real PayPal login.
</div>
{error}
<form method="post" action="/paypal/mock-login">
<label>Name<input name="name" value="{name}" maxlength="60" required autocomplete="name"></label>
<label>Email<input name="email" type="email" value="{email}" maxlength="120" required autocomplete="email"></label>
<button type="submit">Continue as demo seller</button>
</form>
</main>
</body>
</html>
"""


def mock_login_page(name: str, email: str, error: str = "") -> str:
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return PAGE.format(error=error_html, name=escape(name, quote=True), email=escape(email, quote=True))
