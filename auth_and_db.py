import os
import secrets
import sqlite3
import httpx
from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter()

CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
BASE_URL = os.getenv("BASE_URL")

# ---------- tiny sqlite setup (no ORM, no complexity) ----------
DB_PATH = "app.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS repos (
            full_name TEXT PRIMARY KEY,
            clone_url TEXT,
            access_token TEXT,
            webhook_secret TEXT,
            webhook_id TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_repo(full_name, clone_url, access_token, webhook_secret, webhook_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO repos VALUES (?, ?, ?, ?, ?)",
        (full_name, clone_url, access_token, webhook_secret, webhook_id),
    )
    conn.commit()
    conn.close()

def get_repo(full_name):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT * FROM repos WHERE full_name = ?", (full_name,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "full_name": row[0],
        "clone_url": row[1],
        "access_token": row[2],
        "webhook_secret": row[3],
        "webhook_id": row[4],
    }

def all_repos():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("SELECT full_name FROM repos")
    rows = [r[0] for r in cur.fetchall()]
    conn.close()
    return rows

# ---------- GitHub OAuth login ----------
@router.get("/login")
def login():
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={CLIENT_ID}&redirect_uri={BASE_URL}/auth/callback&scope=repo"
    )
    return RedirectResponse(url)

@router.get("/auth/callback")
async def auth_callback(code: str):
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
            },
        )
        access_token = token_resp.json().get("access_token")

    # redirect to repo-picker page, passing token in a short-lived cookie
    response = RedirectResponse(url="/pick-repo")
    response.set_cookie("gh_token", access_token, httponly=True, max_age=600)
    return response

# ---------- list user's repos ----------
async def list_user_repos(access_token):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.github.com/user/repos",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"per_page": 100, "sort": "updated"},
        )
        return resp.json()

# ---------- create webhook on chosen repo ----------
async def create_webhook(access_token, full_name):
    webhook_secret = secrets.token_hex(16)
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.github.com/repos/{full_name}/hooks",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "name": "web",
                "active": True,
                "events": ["push"],
                "config": {
                    "url": f"{BASE_URL}/javaproject",
                    "content_type": "json",
                    "secret": webhook_secret,
                },
            },
        )
        data = resp.json()
        return data.get("id"), webhook_secret