"""Shared UI styling used across all pages — keeps the look consistent."""

BASE_STYLES = """
:root {
    --bg: #f6f7fb;
    --card: #ffffff;
    --text: #1a1d29;
    --muted: #6b7280;
    --primary: #4f46e5;
    --primary-dark: #4338ca;
    --border: #e5e7eb;
    --success-bg: #ecfdf3;
    --success-text: #027a48;
    --error-bg: #fef3f2;
    --error-text: #b42318;
    --shadow: 0 1px 3px rgba(0,0,0,0.06), 0 4px 12px rgba(0,0,0,0.04);
}

* { box-sizing: border-box; }

body {
    margin: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
}

.navbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 40px;
    background: var(--card);
    border-bottom: 1px solid var(--border);
}

.navbar .brand {
    font-weight: 700;
    font-size: 18px;
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--text);
    text-decoration: none;
}

.page-wrap {
    max-width: 960px;
    margin: 0 auto;
    padding: 40px 24px 80px;
}

.btn {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 12px 22px;
    background: var(--primary);
    color: white;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 600;
    cursor: pointer;
    text-decoration: none;
    transition: background 0.15s ease, transform 0.1s ease;
}

.btn:hover { background: var(--primary-dark); }
.btn:active { transform: scale(0.98); }

.btn-secondary {
    background: var(--card);
    color: var(--text);
    border: 1px solid var(--border);
}

.btn-secondary:hover { background: #f3f4f6; }

.btn-small {
    padding: 8px 16px;
    font-size: 13px;
}

.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    box-shadow: var(--shadow);
    padding: 24px;
}

.muted { color: var(--muted); }

a { color: var(--primary); }
"""


def page_shell(title: str, body_html: str, extra_head: str = "") -> str:
    """Wrap page content in a consistent HTML shell with navbar."""
    return f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>{title}</title>
        <style>{BASE_STYLES}</style>
        {extra_head}
    </head>
    <body>
        <div class="navbar">
            <a href="/" class="brand">🤖 AI Doc Generator</a>
            <a href="/" class="muted" style="text-decoration:none; font-size:14px;">Home</a>
        </div>
        {body_html}
    </body>
    </html>
    """