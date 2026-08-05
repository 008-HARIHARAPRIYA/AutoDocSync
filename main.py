from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
import hmac
import hashlib
import os
import traceback
import subprocess
import tempfile
import shutil
from doc_generator import generate_docs
from threading import Thread
import time

app = FastAPI()

GITHUB_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
# Track processed commits to avoid duplicate processing
processed_commits = set()
COMMIT_TIMEOUT = 60  # Only process same commit once per 60 seconds

def generate_documentation_for_repo(clone_url: str, repo_name: str, commit_sha: str = None):
    """Clone repo and generate documentation"""
    temp_dir = tempfile.mkdtemp()
    try:
        # Clone the repository
        print(f"  Cloning repository...")
        subprocess.run(
            ["git", "clone", clone_url, temp_dir],
            check=True,
            capture_output=True,
            timeout=60
        )
        
        # Generate documentation using Gemini
        print(f"  Generating AI documentation...")
        generate_docs(temp_dir)
        
        # Commit and push the README
        subprocess.run(
            ["git", "-C", temp_dir, "config", "user.email", "ai-doc-system@bot.com"],
            check=False,
            capture_output=True
        )
        subprocess.run(
            ["git", "-C", temp_dir, "config", "user.name", "AI Doc Bot"],
            check=False,
            capture_output=True
        )
        
        # Check if README was created/modified
        result = subprocess.run(
            ["git", "-C", temp_dir, "status", "--short"],
            capture_output=True,
            text=True
        )
        
        if "README.md" in result.stdout:
            print(f"  README.md changes detected")
            subprocess.run(
                ["git", "-C", temp_dir, "add", "README.md"],
                check=True,
                capture_output=True
            )
            subprocess.run(
                ["git", "-C", temp_dir, "commit", "-m", "docs: auto-generated documentation by AI [skip ci]"],
                check=True,
                capture_output=True
            )
            
            # Try to push with credentials
            push_result = subprocess.run(
                ["git", "-C", temp_dir, "push"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if push_result.returncode == 0:
                print(f"  ✓ README.md pushed to repository")
            else:
                print(f"  ⚠ Push attempt: {push_result.stderr}")
                print(f"  Note: Ensure repository has write permissions or use Personal Access Token")
        else:
            print(f"  No changes to README.md")
        
        print(f"  ✓ Documentation generation completed for {repo_name}")
            
    except subprocess.TimeoutExpired:
        print(f"  ✗ Operation timed out")
    except subprocess.CalledProcessError as e:
        stderr_msg = e.stderr.decode() if e.stderr else str(e)
        print(f"  ✗ Git operation failed: {stderr_msg}")
    except Exception as e:
        print(f"  ✗ Error: {str(e)}")
        traceback.print_exc()
    finally:
        # Clean up temp directory
        shutil.rmtree(temp_dir, ignore_errors=True)
        # Remove from processed set after completion
        if commit_sha and commit_sha in processed_commits:
            processed_commits.discard(commit_sha)

def verify_github_signature(payload_body: bytes, signature_header: str) -> bool:
    """Verify GitHub webhook signature"""
    if not signature_header or not GITHUB_SECRET:
        return True
    
    hash_object = hmac.new(
        GITHUB_SECRET.encode(),
        msg=payload_body,
        digestmod=hashlib.sha256
    )
    expected_signature = "sha256=" + hash_object.hexdigest()
    return hmac.compare_digest(expected_signature, signature_header)

def should_skip_commit(payload: dict) -> bool:
    """Check if commit should be skipped to prevent infinite loops"""
    
    # Skip if commit message contains bot markers
    head_commit = payload.get('head_commit', {})
    commit_message = head_commit.get('message', '')
    
    bot_markers = [
        '[skip ci]',
        '[ci skip]',
        'auto-generated documentation',
        'AI Doc Bot'
    ]
    
    for marker in bot_markers:
        if marker.lower() in commit_message.lower():
            print(f"  ⏭ Skipping: Commit contains '{marker}'")
            return True
    
    # Skip if committer is the bot
    committer = head_commit.get('committer', {})
    author = head_commit.get('author', {})
    
    bot_emails = ['ai-doc-system@bot.com', 'noreply@github.com']
    bot_names = ['AI Doc Bot']
    
    if committer.get('email') in bot_emails or committer.get('username') in bot_names:
        print(f"  ⏭ Skipping: Commit by bot user")
        return True
        
    if author.get('email') in bot_emails or author.get('username') in bot_names:
        print(f"  ⏭ Skipping: Authored by bot")
        return True
    
    # Skip if only README.md was modified (likely a bot commit)
    # But allow regeneration if code files (html, css, js) were changed alongside README
    modified_files = head_commit.get('modified', [])
    added_files = head_commit.get('added', [])
    removed_files = head_commit.get('removed', [])
    
    all_files = modified_files + added_files + removed_files
    
    # Check if any code files (html, css, js) are in the changeset
    code_file_extensions = ('.html', '.css', '.js')
    has_code_files = any(f.endswith(code_file_extensions) for f in all_files)
    
    # Only skip if ONLY README.md changed AND no code files are present
    if all_files == ['README.md'] and not has_code_files:
        print(f"  ⏭ Skipping: Only README.md changed (no code files)")
        return True
    
    return False

@app.get("/")
def home():
    return {"message": "Backend is running"}

@app.post("/javaproject")
async def github_webhook(request: Request):
    try:
        # Get the raw body for signature verification
        body = await request.body()
        signature = request.headers.get("X-Hub-Signature-256", "")
        
        # Verify the signature
        if not verify_github_signature(body, signature):
            print("✗ Invalid signature")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"error": "Invalid signature"}
            )
        
        # Parse the payload
        try:
            payload = await request.json()
        except Exception as json_err:
            print(f"✗ JSON parse error: {str(json_err)}")
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"status": "received", "note": "JSON parse error"}
            )
        
        print("✓ GitHub webhook received successfully")
        repo_name = payload.get('repository', {}).get('full_name', 'N/A')
        print(f"  Repository: {repo_name}")
        print(f"  Event: {payload.get('action', payload.get('zen', 'push'))}")
        
        if "pusher" in payload:
            print(f"  Pusher: {payload['pusher'].get('name', 'N/A')}")
        if "head_commit" in payload:
            print(f"  Commit: {payload['head_commit'].get('message', 'N/A')}")
        
        # Check if we should skip this commit (prevent infinite loop)
        if should_skip_commit(payload):
            return JSONResponse(
                status_code=200,
                content={"status": "ok", "message": "Commit skipped (bot commit)"}
            )
        
        # Get commit SHA to prevent duplicate processing
        commit_sha = payload.get('after', '')
        
        # Check if we already processed this commit recently
        if commit_sha in processed_commits:
            print(f"  ⏭ Skipping: Already processing commit {commit_sha}")
            return JSONResponse(
                status_code=200,
                content={"status": "ok", "message": "Commit already being processed"}
            )
        
        # Mark this commit as being processed
        processed_commits.add(commit_sha)
        
        # Generate documentation asynchronously in background thread
        try:
            clone_url = payload.get('repository', {}).get('clone_url', '')
            if clone_url:
                print(f"  Starting documentation generation for {repo_name}...")
                thread = Thread(target=generate_documentation_for_repo, args=(clone_url, repo_name, commit_sha))
                thread.daemon = True
                thread.start()
        except Exception as doc_err:
            print(f"  ✗ Documentation thread error: {str(doc_err)}")
            if commit_sha in processed_commits:
                processed_commits.discard(commit_sha)
        
        return JSONResponse(
            status_code=200,
            content={"status": "ok", "message": "Webhook received and processing"}
        )
    
    except Exception as e:
        print(f"✗ Webhook error: {str(e)}")
        print(traceback.format_exc())
        return JSONResponse(
            status_code=200,
            content={"status": "error", "details": str(e)}
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)