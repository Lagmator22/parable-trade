from html import escape

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} - Parable</title>
<style>
:root {{ --bg: #ffffff; --ink: #0a0a0a; --muted: #5c5c5c; --line: #0a0a0a; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg: #0a0a0a; --ink: #f5f5f5; --muted: #a3a3a3; --line: #f5f5f5; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, sans-serif; }}
main {{ max-width: 460px; margin: 0 auto; padding: 48px 16px; }}
h1 {{ font-size: 26px; margin: 0 0 16px; letter-spacing: -0.02em; }}
.notice {{ border: 1px solid var(--line); padding: 12px 14px; margin-bottom: 24px; font-size: 14px; }}
.notice strong {{ display: block; font-family: ui-monospace, monospace; text-transform: uppercase; font-size: 12px; }}
dl {{ margin: 0 0 24px; border-top: 1px solid var(--line); }}
dl div {{ display: flex; justify-content: space-between; gap: 16px; padding: 8px 0; border-bottom: 1px solid var(--line); }}
dt {{ color: var(--muted); }}
dd {{ margin: 0; font-weight: 600; text-align: right; }}
form {{ display: flex; gap: 12px; }}
button {{ flex: 1; padding: 12px; font: inherit; font-weight: 600; cursor: pointer; border-radius: 0;
  color: var(--bg); background: var(--ink); border: 1px solid var(--ink); }}
button.secondary {{ color: var(--ink); background: var(--bg); }}
</style>
</head>
<body>
<main>
{body}
</main>
</body>
</html>
"""

APPROVE_BODY = """<h1>Mock PayPal: approve ${amount}</h1>
<div class="notice">
<strong>Simulated payment</strong>
PayPal sandbox keys are not configured, so no real PayPal is involved. Approving only places a simulated hold.
</div>
<dl>
<div><dt>Item</dt><dd>{description}</dd></div>
<div><dt>Amount held</dt><dd>${amount}</dd></div>
<div><dt>Charged now</dt><dd>$0.00</dd></div>
</dl>
<form method="post" action="/paypal/mock-approve">
<input type="hidden" name="order" value="{order}">
<button type="submit" name="decision" value="approve">Approve</button>
<button type="submit" name="decision" value="cancel" class="secondary">Cancel</button>
</form>"""

MISSING_BODY = """<h1>{heading}</h1>
<div class="notice"><strong>Parable</strong>{message}</div>
<p><a href="/">Back to the market</a></p>"""


def approve_page(order_id: str, amount: str, description: str) -> str:
    body = APPROVE_BODY.format(amount=escape(amount), description=escape(description), order=escape(order_id, quote=True))
    return PAGE.format(title="Approve payment", body=body)


def message_page(heading: str, message: str) -> str:
    return PAGE.format(title=heading, body=MISSING_BODY.format(heading=escape(heading), message=escape(message)))
