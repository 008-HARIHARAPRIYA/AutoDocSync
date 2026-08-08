from fastapi import FastAPI, Request, status, Form
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse

import hmac
import hashlib
import traceback
import subprocess
import tempfile
import shutil
import json

from threading import Thread

from documentation_agent.generate import generate_documentation_sync
from ui import page_shell

from auth_and_db import (
    router as auth_router,
    init_db,
    save_repo,
    get_repo,
    list_user_repos,
    create_webhook,
)


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI()


# ============================================================
# DATABASE + AUTH ROUTES
# ============================================================

init_db()
app.include_router(auth_router)


# ============================================================
# IN-MEMORY TRACKING
# ============================================================

# Used to prevent the same GitHub commit from being processed
# multiple times at the same time.
processed_commits = set()


# repo_status[repo_name] = {
#     "stage": "...",
#     "detail": "...",
#     "log": [...]
# }
repo_status = {}


# ============================================================
# STATUS MANAGEMENT
# ============================================================

def update_status(repo_name: str, stage: str, detail: str = ""):
    """
    Update the in-memory status of a repository.
    """

    if repo_name not in repo_status:
        repo_status[repo_name] = {
            "stage": stage,
            "detail": detail,
            "log": []
        }

    repo_status[repo_name]["stage"] = stage
    repo_status[repo_name]["detail"] = detail

    if detail:
        repo_status[repo_name]["log"].append(
            f"[{stage}] {detail}"
        )

    # Keep only the latest 50 logs
    repo_status[repo_name]["log"] = (
        repo_status[repo_name]["log"][-50:]
    )

    print(
        f"  📡 {repo_name} → {stage}: {detail}"
    )


# ============================================================
# DOCUMENTATION GENERATION
# ============================================================

def generate_documentation_for_repo(
    clone_url: str,
    repo_name: str,
    commit_sha: str = None
):
    """
    Clone a GitHub repository, generate README using the ADK
    documentation agent, commit the README and push it back.
    """

    temp_dir = tempfile.mkdtemp()

    try:

        # ----------------------------------------------------
        # STEP 1: CLONE
        # ----------------------------------------------------

        update_status(
            repo_name,
            "cloning",
            f"Connecting to {repo_name}..."
        )

        subprocess.run(
            [
                "git",
                "clone",
                clone_url,
                temp_dir
            ],
            check=True,
            capture_output=True,
            timeout=60
        )
        update_status(
            repo_name,
            "cloning",
            "Repository cloned successfully"
        )


        # ----------------------------------------------------
        # STEP 1B: DETECT DEFAULT BRANCH
        # ----------------------------------------------------

        branch_result = subprocess.run(
            [
                "git",
                "-C",
                temp_dir,
                "symbolic-ref",
                "--short",
                "HEAD"
            ],
            capture_output=True,
            text=True
        )

        default_branch = branch_result.stdout.strip() or "main"

        update_status(
            repo_name,
            "cloning",
            f"Detected default branch: {default_branch}"
        )
        # ----------------------------------------------------
        # STEP 2: GENERATE DOCUMENTATION USING ADK
        # ----------------------------------------------------

        update_status(
            repo_name,
            "scanning",
            "Scanning project source code..."
        )

        update_status(
            repo_name,
            "generating",
            "Generating README using Google ADK..."
        )

        generated_readme = generate_documentation_sync(
            temp_dir
        )

        if not generated_readme:
            raise RuntimeError(
                "ADK returned empty documentation"
            )


        # ----------------------------------------------------
        # STEP 3: CLEAN AI MARKDOWN WRAPPERS
        # ----------------------------------------------------

        # Sometimes the model returns:
        #
        # ```markdown
        # # README
        # ```
        #
        # We remove those wrappers before writing README.md.

        generated_readme = generated_readme.strip()

        if generated_readme.startswith(
            "```markdown"
        ):
            generated_readme = generated_readme[
                len("```markdown"):
            ].strip()

        elif generated_readme.startswith(
            "```md"
        ):
            generated_readme = generated_readme[
                len("```md"):
            ].strip()

        elif generated_readme.startswith(
            "```"
        ):
            generated_readme = generated_readme[
                len("```"):
            ].strip()

        if generated_readme.endswith("```"):
            generated_readme = generated_readme[
                :-3
            ].strip()


        # ----------------------------------------------------
        # STEP 4: WRITE README
        # ----------------------------------------------------

        readme_path = os_path_join(
            temp_dir,
            "README.md"
        )

        with open(
            readme_path,
            "w",
            encoding="utf-8"
        ) as readme_file:

            readme_file.write(
                generated_readme
            )

        update_status(
            repo_name,
            "generating",
            "README.md generated successfully"
        )


        # ----------------------------------------------------
        # STEP 5: CONFIGURE GIT
        # ----------------------------------------------------

        subprocess.run(
            [
                "git",
                "-C",
                temp_dir,
                "config",
                "user.email",
                "ai-doc-system@bot.com"
            ],
            check=False,
            capture_output=True
        )

        subprocess.run(
            [
                "git",
                "-C",
                temp_dir,
                "config",
                "user.name",
                "AI Doc Bot"
            ],
            check=False,
            capture_output=True
        )


        # ----------------------------------------------------
        # STEP 6: CHECK README CHANGE
        # ----------------------------------------------------

        result = subprocess.run(
            [
                "git",
                "-C",
                temp_dir,
                "status",
                "--short"
            ],
            capture_output=True,
            text=True
        )

        print(
            "Git status:"
        )
        print(result.stdout)


        # ----------------------------------------------------
        # NO README CHANGE
        # ----------------------------------------------------

        if "README.md" not in result.stdout:

            update_status(
                repo_name,
                "done",
                "No changes to README.md (already up to date)"
            )

            return


        # ----------------------------------------------------
        # STEP 7: ADD README
        # ----------------------------------------------------

        update_status(
            repo_name,
            "pushing",
            "Adding README.md to Git..."
        )

        subprocess.run(
            [
                "git",
                "-C",
                temp_dir,
                "add",
                "README.md"
            ],
            check=True,
            capture_output=True
        )


        # ----------------------------------------------------
        # STEP 8: COMMIT
        # ----------------------------------------------------

        update_status(
            repo_name,
            "pushing",
            "Creating documentation commit..."
        )

        commit_result = subprocess.run(
            [
                "git",
                "-C",
                temp_dir,
                "commit",
                "-m",
                "docs: auto-generated documentation by AI [skip ci]"
            ],
            check=False,
            capture_output=True,
            text=True
        )

        if commit_result.returncode != 0:

            # If there is actually nothing to commit
            if (
                "nothing to commit"
                in commit_result.stdout.lower()
                or
                "nothing to commit"
                in commit_result.stderr.lower()
            ):

                update_status(
                    repo_name,
                    "done",
                    "No README changes detected"
                )

                return

            raise RuntimeError(
                "Git commit failed: "
                + commit_result.stderr
            )


        # ====================================================
        # IMPORTANT:
        # SYNC WITH GITHUB BEFORE PUSHING
        # ====================================================

        update_status(
            repo_name,
            "pushing",
            "Syncing with latest GitHub changes..."
        )

        pull_result = subprocess.run(
            [
                "git",
                "-C",
                temp_dir,
                "pull",
                "--rebase",
                "origin",
                default_branch
            ],
            capture_output=True,
            text=True,
            timeout=60
        )


        # ----------------------------------------------------
        # PULL FAILED
        # ----------------------------------------------------

        if pull_result.returncode != 0:

            # Abort rebase so the temporary repository
            # is cleaned properly.
            subprocess.run(
                [
                    "git",
                    "-C",
                    temp_dir,
                    "rebase",
                    "--abort"
                ],
                check=False,
                capture_output=True
            )

            update_status(
                repo_name,
                "error",
                "Could not sync with GitHub: "
                + pull_result.stderr
            )

            return


        # ----------------------------------------------------
        # STEP 9: PUSH
        # ----------------------------------------------------

        update_status(
            repo_name,
            "pushing",
            "Pushing README.md to GitHub..."
        )

        push_result = subprocess.run(
            [
                "git",
                "-C",
                temp_dir,
                "push",
                "origin",
                default_branch
            ],
            capture_output=True,
            text=True,
            timeout=60
        )


        # ----------------------------------------------------
        # PUSH SUCCESS
        # ----------------------------------------------------

        if push_result.returncode == 0:

            update_status(
                repo_name,
                "done",
                "✅ README.md pushed successfully!"
            )

        else:

            update_status(
                repo_name,
                "error",
                "❌ Push failed: "
                + push_result.stderr
            )


    # ========================================================
    # ERROR HANDLING
    # ========================================================

    except subprocess.TimeoutExpired:

        update_status(
            repo_name,
            "error",
            "Operation timed out"
        )

    except subprocess.CalledProcessError as e:

        if e.stderr:

            try:
                stderr_msg = e.stderr.decode()
            except Exception:
                stderr_msg = str(e.stderr)

        else:
            stderr_msg = str(e)

        update_status(
            repo_name,
            "error",
            f"Git operation failed: {stderr_msg}"
        )

    except Exception as e:

        update_status(
            repo_name,
            "error",
            f"Error: {str(e)}"
        )

        traceback.print_exc()


    finally:

        # Remove temporary cloned repository
        shutil.rmtree(
            temp_dir,
            ignore_errors=True
        )

        # Remove commit from processing set
        if (
            commit_sha
            and
            commit_sha in processed_commits
        ):
            processed_commits.discard(
                commit_sha
            )


# ============================================================
# HELPER
# ============================================================

def os_path_join(*parts):
    """
    Small helper to join paths.
    """

    import os

    return os.path.join(*parts)


# ============================================================
# CHECK WHETHER WEBHOOK COMMIT SHOULD BE SKIPPED
# ============================================================

def should_skip_commit(payload: dict) -> bool:
    """
    Prevent infinite loops caused by the bot's own README commit.
    """

    head_commit = payload.get(
        "head_commit",
        {}
    )

    commit_message = head_commit.get(
        "message",
        ""
    )


    # --------------------------------------------------------
    # BOT COMMIT MESSAGE MARKERS
    # --------------------------------------------------------

    bot_markers = [
        "[skip ci]",
        "[ci skip]",
        "auto-generated documentation",
        "AI Doc Bot"
    ]

    for marker in bot_markers:

        if marker.lower() in commit_message.lower():

            print(
                f"  ⏭ Skipping: Commit contains '{marker}'"
            )

            return True


    # --------------------------------------------------------
    # BOT AUTHOR / COMMITTER
    # --------------------------------------------------------

    committer = head_commit.get(
        "committer",
        {}
    )

    author = head_commit.get(
        "author",
        {}
    )

    bot_emails = [
        "ai-doc-system@bot.com",
        "noreply@github.com"
    ]

    bot_names = [
        "AI Doc Bot"
    ]


    if (
        committer.get("email") in bot_emails
        or
        committer.get("username") in bot_names
        or
        committer.get("name") in bot_names
    ):

        print(
            "  ⏭ Skipping: Commit by bot user"
        )

        return True


    if (
        author.get("email") in bot_emails
        or
        author.get("username") in bot_names
        or
        author.get("name") in bot_names
    ):

        print(
            "  ⏭ Skipping: Authored by bot"
        )

        return True


    # --------------------------------------------------------
    # CHECK CHANGED FILES
    # --------------------------------------------------------

    modified_files = head_commit.get(
        "modified",
        []
    )

    added_files = head_commit.get(
        "added",
        []
    )

    removed_files = head_commit.get(
        "removed",
        []
    )

    all_files = (
        modified_files
        + added_files
        + removed_files
    )


    # Supported source files
    code_file_extensions = (
        ".html",
        ".css",
        ".js",
        ".java",
        ".py",
        ".cpp",
        ".c",
        ".h",
        ".ts",
        ".tsx",
        ".jsx",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".sql"
    )


    has_code_files = any(
        f.lower().endswith(
            code_file_extensions
        )
        for f in all_files
    )


    # If ONLY README changed, ignore it.
    if (
        len(all_files) == 1
        and
        all_files[0] == "README.md"
        and
        not has_code_files
    ):

        print(
            "  ⏭ Skipping: Only README.md changed"
        )

        return True


    return False


# ============================================================
# HOME PAGE
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
def home():

    body = """
    <div class="page-wrap">

        <!-- Hero -->

        <div style="
            text-align:center;
            padding:60px 20px 50px;
        ">

            <div style="
                display:inline-block;
                background:#eef2ff;
                color:#4f46e5;
                padding:6px 14px;
                border-radius:20px;
                font-size:13px;
                font-weight:600;
                margin-bottom:20px;
            ">
                ✨ Powered by Google Gemini
            </div>


            <h1 style="
                font-size:42px;
                font-weight:800;
                margin:0 0 16px;
                letter-spacing:-1px;
            ">
                Documentation that<br>
                writes itself.
            </h1>


            <p class="muted" style="
                font-size:18px;
                max-width:560px;
                margin:0 auto 32px;
            ">
                Connect any GitHub repository and get a professional,
                AI-generated README — automatically updated on every push.
            </p>


            <a
                href="/login"
                class="btn"
                style="
                    font-size:16px;
                    padding:14px 28px;
                "
            >
                Connect with GitHub
            </a>


            <p class="muted" style="
                font-size:13px;
                margin-top:14px;
            ">
                Free · No credit card · Takes 30 seconds
            </p>

        </div>


        <!-- Feature cards -->

        <div style="
            display:grid;
            grid-template-columns:repeat(3, 1fr);
            gap:20px;
            margin-bottom:50px;
        ">

            <div class="card">

                <div style="
                    font-size:28px;
                    margin-bottom:10px;
                ">
                    ⚡
                </div>

                <h3 style="
                    margin:0 0 8px;
                    font-size:16px;
                ">
                    Instant generation
                </h3>

                <p class="muted" style="
                    font-size:14px;
                    margin:0;
                ">
                    Connect a repo and documentation is generated
                    immediately for your existing code.
                </p>

            </div>


            <div class="card">

                <div style="
                    font-size:28px;
                    margin-bottom:10px;
                ">
                    🔄
                </div>

                <h3 style="
                    margin:0 0 8px;
                    font-size:16px;
                ">
                    Always up to date
                </h3>

                <p class="muted" style="
                    font-size:14px;
                    margin:0;
                ">
                    Every push automatically triggers a fresh README
                    update — zero manual work.
                </p>

            </div>


            <div class="card">

                <div style="
                    font-size:28px;
                    margin-bottom:10px;
                ">
                    🔒
                </div>

                <h3 style="
                    margin:0 0 8px;
                    font-size:16px;
                ">
                    Secure by design
                </h3>

                <p class="muted" style="
                    font-size:14px;
                    margin:0;
                ">
                    OAuth login and signed webhooks protect your
                    repositories.
                </p>

            </div>

        </div>


        <!-- How it works -->

        <div class="card" style="
            padding:36px;
        ">

            <h2 style="
                margin:0 0 24px;
                font-size:20px;
            ">
                How it works
            </h2>


            <div style="
                display:grid;
                grid-template-columns:repeat(4, 1fr);
                gap:20px;
            ">

                <div>

                    <div style="
                        width:32px;
                        height:32px;
                        background:#eef2ff;
                        color:#4f46e5;
                        border-radius:50%;
                        display:flex;
                        align-items:center;
                        justify-content:center;
                        font-weight:700;
                        margin-bottom:10px;
                    ">
                        1
                    </div>

                    <p style="
                        font-size:14px;
                        margin:0;
                    ">
                        <b>Connect</b> your GitHub account securely via OAuth.
                    </p>

                </div>


                <div>

                    <div style="
                        width:32px;
                        height:32px;
                        background:#eef2ff;
                        color:#4f46e5;
                        border-radius:50%;
                        display:flex;
                        align-items:center;
                        justify-content:center;
                        font-weight:700;
                        margin-bottom:10px;
                    ">
                        2
                    </div>

                    <p style="
                        font-size:14px;
                        margin:0;
                    ">
                        <b>Pick a repo</b> from your own repositories.
                    </p>

                </div>


                <div>

                    <div style="
                        width:32px;
                        height:32px;
                        background:#eef2ff;
                        color:#4f46e5;
                        border-radius:50%;
                        display:flex;
                        align-items:center;
                        justify-content:center;
                        font-weight:700;
                        margin-bottom:10px;
                    ">
                        3
                    </div>

                    <p style="
                        font-size:14px;
                        margin:0;
                    ">
                        <b>AI scans your code</b> and writes a full README.
                    </p>

                </div>


                <div>

                    <div style="
                        width:32px;
                        height:32px;
                        background:#eef2ff;
                        color:#4f46e5;
                        border-radius:50%;
                        display:flex;
                        align-items:center;
                        justify-content:center;
                        font-weight:700;
                        margin-bottom:10px;
                    ">
                        4
                    </div>

                    <p style="
                        font-size:14px;
                        margin:0;
                    ">
                        <b>Stays updated</b> automatically on every future push.
                    </p>

                </div>

            </div>

        </div>


        <p class="muted" style="
            text-align:center;
            font-size:13px;
            margin-top:50px;
        ">
            Built with FastAPI, Google ADK &amp; Google Gemini
        </p>

    </div>
    """

    return page_shell(
        "AI Doc Generator",
        body
    )


# ============================================================
# PICK REPOSITORY
# ============================================================

@app.get(
    "/pick-repo",
    response_class=HTMLResponse
)
async def pick_repo(request: Request):

    token = request.cookies.get(
        "gh_token"
    )

    if not token:
        return RedirectResponse(
            "/login"
        )


    repos = await list_user_repos(
        token
    )


    if not isinstance(
        repos,
        list
    ):

        body = f"""
        <div class="page-wrap">

            <div class="card">

                <p>
                    Could not fetch repos:
                    {repos}
                </p>

                <a
                    href="/"
                    class="btn btn-secondary"
                >
                    Back to Home
                </a>

            </div>

        </div>
        """

        return page_shell(
            "Error",
            body
        )


    # --------------------------------------------------------
    # BUILD REPOSITORY DATA
    # --------------------------------------------------------

    repo_data = [

        {
            "name": r["full_name"],
            "clone_url": r["clone_url"],
            "private": r.get(
                "private",
                False
            ),
            "description": (
                r.get("description")
                or
                "No description"
            ),
            "language": (
                r.get("language")
                or
                "—"
            ),
            "updated": (
                r.get("updated_at")
                or
                ""
            )[:10]
        }

        for r in repos
    ]


    repos_json = json.dumps(
        repo_data
    )


    # --------------------------------------------------------
    # IMPORTANT:
    # This is an f-string.
    # JavaScript ${...} therefore becomes ${{...}}
    # --------------------------------------------------------

    body = f"""
    <div class="page-wrap">

        <h2 style="margin-bottom:4px;">
            Pick a repository
        </h2>

        <p class="muted" style="margin-top:0;">
            Choose which repo should get auto-generated documentation.
        </p>


        <div style="margin:24px 0;">

            <input
                id="search-box"
                type="text"
                placeholder="🔍  Search your repositories..."
                style="
                    width:100%;
                    padding:12px 16px;
                    font-size:15px;
                    border:1px solid var(--border);
                    border-radius:8px;
                    outline:none;
                "
            >

        </div>


        <div
            id="repo-count"
            class="muted"
            style="
                font-size:13px;
                margin-bottom:14px;
            "
        >
        </div>


        <div
            id="repo-list"
            style="
                display:flex;
                flex-direction:column;
                gap:12px;
            "
        >
        </div>


        <div
            id="pagination"
            style="
                display:flex;
                justify-content:center;
                gap:8px;
                margin-top:28px;
            "
        >
        </div>


        <form
            id="connect-form"
            method="post"
            action="/connect-repo"
            style="display:none;"
        >

            <input
                type="hidden"
                name="full_name"
                id="f-full-name"
            >

            <input
                type="hidden"
                name="clone_url"
                id="f-clone-url"
            >

            <input
                type="hidden"
                name="token"
                value="{token}"
            >

        </form>

    </div>


    <script>

        const allRepos = {repos_json};

        const perPage = 6;

        let currentPage = 1;

        let filtered = allRepos;


        const listEl =
            document.getElementById("repo-list");

        const countEl =
            document.getElementById("repo-count");

        const pagEl =
            document.getElementById("pagination");

        const searchBox =
            document.getElementById("search-box");


        function langColor(lang) {{

            const colors = {{

                "Python": "#3572A5",
                "JavaScript": "#f1e05a",
                "TypeScript": "#2b7489",
                "HTML": "#e34c26",
                "CSS": "#563d7c",
                "Java": "#b07219",
                "Go": "#00ADD8",
                "C++": "#f34b7d",
                "C": "#555555"

            }};

            return colors[lang] || "#8b949e";
        }}


        function render() {{

            const start =
                (currentPage - 1) * perPage;

            const pageItems =
                filtered.slice(
                    start,
                    start + perPage
                );


            countEl.textContent =
                filtered.length +
                " repositories found";


            listEl.innerHTML =
                pageItems.map(r => `

                    <div
                        class="card"
                        style="
                            display:flex;
                            justify-content:space-between;
                            align-items:center;
                            padding:18px 22px;
                        "
                    >

                        <div
                            style="
                                flex:1;
                                min-width:0;
                            "
                        >

                            <div
                                style="
                                    display:flex;
                                    align-items:center;
                                    gap:10px;
                                    margin-bottom:6px;
                                "
                            >

                                <span
                                    style="
                                        font-weight:600;
                                        font-size:15px;
                                    "
                                >
                                    ${{r.name}}
                                </span>


                                <span
                                    style="
                                        font-size:11px;
                                        padding:2px 8px;
                                        border-radius:10px;
                                        background:${{r.private ? '#fef3f2' : '#ecfdf3'}};
                                        color:${{r.private ? '#b42318' : '#027a48'}};
                                    "
                                >
                                    ${{r.private ? 'Private' : 'Public'}}
                                </span>

                            </div>


                            <p
                                class="muted"
                                style="
                                    font-size:13px;
                                    margin:0 0 8px;
                                    white-space:nowrap;
                                    overflow:hidden;
                                    text-overflow:ellipsis;
                                "
                            >
                                ${{r.description}}
                            </p>


                            <div
                                style="
                                    display:flex;
                                    gap:14px;
                                    font-size:12px;
                                "
                                class="muted"
                            >

                                <span>

                                    <span
                                        style="
                                            display:inline-block;
                                            width:8px;
                                            height:8px;
                                            border-radius:50%;
                                            background:${{langColor(r.language)}};
                                            margin-right:4px;
                                        "
                                    >
                                    </span>

                                    ${{r.language}}

                                </span>


                                <span>
                                    Updated ${{r.updated || '—'}}
                                </span>

                            </div>

                        </div>


                        <button
                            class="btn btn-small"
                            onclick="connectRepo('${{r.name}}', '${{r.clone_url}}')"
                        >
                            Connect
                        </button>

                    </div>

                `).join("")

                ||

                `
                    <div
                        class="card muted"
                        style="text-align:center;"
                    >
                        No repositories match your search.
                    </div>
                `;


            const totalPages =
                Math.max(
                    1,
                    Math.ceil(
                        filtered.length / perPage
                    )
                );


            let pagHtml = "";


            for (
                let i = 1;
                i <= totalPages;
                i++
            ) {{

                pagHtml += `

                    <button
                        class="btn btn-small ${{i === currentPage ? '' : 'btn-secondary'}}"
                        onclick="goToPage(${{i}})"
                    >
                        ${{i}}
                    </button>

                `;
            }}


            pagEl.innerHTML =
                totalPages > 1
                    ? pagHtml
                    : "";
        }}


        function goToPage(p) {{

            currentPage = p;

            render();
        }}


        function connectRepo(
            name,
            cloneUrl
        ) {{

            document.getElementById(
                "f-full-name"
            ).value = name;


            document.getElementById(
                "f-clone-url"
            ).value = cloneUrl;


            document.getElementById(
                "connect-form"
            ).submit();
        }}


        searchBox.addEventListener(
            "input",
            (e) => {{

                const q =
                    e.target.value
                    .toLowerCase();


                filtered =
                    allRepos.filter(
                        r =>
                            r.name
                            .toLowerCase()
                            .includes(q)
                    );


                currentPage = 1;

                render();
            }}
        );


        render();

    </script>
    """


    return page_shell(
        "Pick a repository",
        body
    )


# ============================================================
# CONNECT REPOSITORY
# ============================================================

@app.post(
    "/connect-repo"
)
async def connect_repo(
    full_name: str = Form(...),
    clone_url: str = Form(...),
    token: str = Form(...)
):

    try:

        # Create GitHub webhook
        webhook_id, webhook_secret = (
            await create_webhook(
                token,
                full_name
            )
        )


        # Save repository information
        save_repo(
            full_name,
            clone_url,
            token,
            webhook_secret,
            webhook_id
        )


        # Update UI
        update_status(
            full_name,
            "queued",
            "Connected! Starting documentation generation..."
        )


        # ----------------------------------------------------
        # AUTHENTICATED CLONE URL
        # ----------------------------------------------------

        authed_clone_url = clone_url.replace(
            "https://",
            f"https://{token}@",
            1
        )


        # ----------------------------------------------------
        # START BACKGROUND THREAD
        # ----------------------------------------------------

        thread = Thread(
            target=generate_documentation_for_repo,
            args=(
                authed_clone_url,
                full_name,
                None
            )
        )

        thread.daemon = True

        thread.start()


        return RedirectResponse(
            url=f"/status-page/{full_name}",
            status_code=303
        )


    except Exception as e:

        print(
            "Connect repository error:",
            str(e)
        )

        traceback.print_exc()


        return JSONResponse(
            status_code=500,
            content={
                "error": str(e)
            }
        )


# ============================================================
# STATUS API
# ============================================================

@app.get(
    "/api/status/{full_name:path}"
)
def get_status(
    full_name: str
):

    data = repo_status.get(
        full_name
    )


    if not data:

        return JSONResponse(
            {
                "stage": "idle",
                "detail": "No activity yet",
                "log": []
            }
        )


    return JSONResponse(
        data
    )


# ============================================================
# STATUS PAGE
# ============================================================

@app.get(
    "/status-page/{full_name:path}",
    response_class=HTMLResponse
)
def status_page(
    full_name: str
):

    body = f"""

    <div class="page-wrap">

        <h2 style="margin-bottom:4px;">
            📄 Generating Documentation
        </h2>

        <p class="muted">
            {full_name}
        </p>


        <div
            class="card"
            style="margin-bottom:20px;"
        >

            <div
                id="stepper"
                style="
                    display:flex;
                    justify-content:space-between;
                    margin-bottom:10px;
                "
            >
            </div>


            <div
                style="
                    height:6px;
                    background:#e5e7eb;
                    border-radius:3px;
                    overflow:hidden;
                    margin-bottom:6px;
                "
            >

                <div
                    id="progress-bar"
                    style="
                        height:100%;
                        width:5%;
                        background:var(--primary);
                        transition:width 0.4s ease;
                    "
                >
                </div>

            </div>


            <div
                id="badge"
                style="
                    font-size:14px;
                    font-weight:600;
                    margin-top:14px;
                    display:flex;
                    align-items:center;
                    gap:8px;
                "
            >

                <span class="spinner"></span>

                <span id="badge-text">
                    Starting...
                </span>

            </div>

        </div>


        <div
            class="card"
            style="
                padding:0;
                overflow:hidden;
            "
        >

            <div
                style="
                    padding:14px 20px;
                    border-bottom:1px solid var(--border);
                    font-size:13px;
                    font-weight:600;
                "
                class="muted"
            >
                LIVE LOG
            </div>


            <div
                id="log"
                style="
                    background:#0d1117;
                    color:#c9d1d9;
                    padding:16px 20px;
                    font-family:'SF Mono', Monaco, monospace;
                    font-size:13px;
                    height:280px;
                    overflow-y:auto;
                    white-space:pre-wrap;
                "
            >
                Waiting for updates...
            </div>

        </div>


        <a
            href="/"
            class="btn btn-secondary"
            style="margin-top:24px;"
        >
            ← Back to Home
        </a>

    </div>


    <style>

        .spinner {{
            display:inline-block;
            width:14px;
            height:14px;
            border:2px solid #ddd;
            border-top-color:var(--primary);
            border-radius:50%;
            animation:spin 0.8s linear infinite;
        }}


        @keyframes spin {{
            to {{
                transform:rotate(360deg);
            }}
        }}


        .step-dot {{
            width:26px;
            height:26px;
            border-radius:50%;
            display:flex;
            align-items:center;
            justify-content:center;
            font-size:12px;
            font-weight:700;
            background:#e5e7eb;
            color:#9ca3af;
        }}


        .step-dot.active {{
            background:var(--primary);
            color:white;
        }}


        .step-dot.done {{
            background:#027a48;
            color:white;
        }}


        .step-label {{
            font-size:11px;
            margin-top:6px;
            text-align:center;
        }}

    </style>


    <script>

        const repoName =
            {full_name!r};


        const stages = [
            "cloning",
            "scanning",
            "generating",
            "pushing",
            "done"
        ];


        const stageLabels = {{

            cloning: "Clone",

            scanning: "Scan",

            generating: "Generate",

            pushing: "Push",

            done: "Done"

        }};


        const stepperEl =
            document.getElementById(
                "stepper"
            );


        const badgeText =
            document.getElementById(
                "badge-text"
            );


        const badgeIcon =
            document.querySelector(
                "#badge .spinner"
            );


        const progressBar =
            document.getElementById(
                "progress-bar"
            );


        const logEl =
            document.getElementById(
                "log"
            );


        function renderStepper(
            currentStage
        ) {{

            const idx =
                stages.indexOf(
                    currentStage
                );


            stepperEl.innerHTML =
                stages.map(
                    (s, i) => {{

                        let cls =
                            "step-dot";


                        let icon =
                            i + 1;


                        if (
                            i < idx
                            ||
                            currentStage === "done"
                        ) {{

                            cls += " done";

                            icon = "✓";

                        }}

                        else if (
                            i === idx
                        ) {{

                            cls += " active";

                        }}


                        return `

                            <div
                                style="
                                    text-align:center;
                                    flex:1;
                                "
                            >

                                <div
                                    class="${{cls}}"
                                    style="margin:0 auto;"
                                >
                                    ${{icon}}
                                </div>

                                <div
                                    class="step-label"
                                >
                                    ${{stageLabels[s]}}
                                </div>

                            </div>

                        `;

                    }}
                ).join("");

        }}


        async function poll() {{

            try {{

                const res =
                    await fetch(
                        `/api/status/${{encodeURIComponent(repoName)}}`
                    );


                const data =
                    await res.json();


                const idx =
                    Math.max(
                        0,
                        stages.indexOf(
                            data.stage
                        )
                    );


                const pct =
                    data.stage === "done"
                        ? 100
                        : data.stage === "error"
                            ? 100
                            : (
                                (idx + 1)
                                /
                                stages.length
                            ) * 100;


                progressBar.style.width =
                    pct + "%";


                if (
                    data.stage === "done"
                ) {{

                    progressBar.style.background =
                        "#027a48";


                    badgeIcon.style.display =
                        "none";


                    badgeText.textContent =
                        "✅ " + data.detail;


                    renderStepper(
                        "done"
                    );

                }}

                else if (
                    data.stage === "error"
                ) {{

                    progressBar.style.background =
                        "#b42318";


                    badgeIcon.style.display =
                        "none";


                    badgeText.textContent =
                        "❌ " + data.detail;

                }}

                else {{

                    badgeText.textContent =
                        data.detail
                        ||
                        data.stage;


                    renderStepper(
                        data.stage
                    );

                }}


                logEl.textContent =
                    (data.log || [])
                    .join("\\n");


                logEl.scrollTop =
                    logEl.scrollHeight;


                if (
                    data.stage !== "done"
                    &&
                    data.stage !== "error"
                ) {{

                    setTimeout(
                        poll,
                        1500
                    );

                }}

            }}

            catch (e) {{

                logEl.textContent +=
                    "\\n[polling error] "
                    + e;


                setTimeout(
                    poll,
                    3000
                );

            }}

        }}


        renderStepper(
            "cloning"
        );


        poll();

    </script>

    """


    return page_shell(
        f"Generating docs — {full_name}",
        body
    )


# ============================================================
# GITHUB WEBHOOK
# ============================================================

@app.post(
    "/javaproject"
)
async def github_webhook(
    request: Request
):

    try:

        # ----------------------------------------------------
        # GET RAW BODY
        # ----------------------------------------------------

        body = await request.body()


        # ----------------------------------------------------
        # PARSE JSON
        # ----------------------------------------------------

        try:

            payload = await request.json()

        except Exception as json_err:

            print(
                f"✗ JSON parse error: {str(json_err)}"
            )

            return JSONResponse(
                status_code=200,
                content={
                    "status": "received",
                    "note": "JSON parse error"
                }
            )


        print(
            "✓ GitHub webhook received successfully"
        )


        # ----------------------------------------------------
        # GET REPOSITORY NAME
        # ----------------------------------------------------

        repo_full_name = (
            payload
            .get("repository", {})
            .get("full_name", "N/A")
        )


        print(
            f"  Repository: {repo_full_name}"
        )


        # ----------------------------------------------------
        # GET STORED REPOSITORY DATA
        # ----------------------------------------------------

        repo_data = get_repo(
            repo_full_name
        )


        if not repo_data:

            print(
                "  ⏭ Ignoring: repo not connected via app"
            )

            return JSONResponse(
                status_code=200,
                content={
                    "status": "ignored",
                    "message": "Repo not connected"
                }
            )


        # ----------------------------------------------------
        # VERIFY WEBHOOK SIGNATURE
        # ----------------------------------------------------

        signature = request.headers.get(
            "X-Hub-Signature-256",
            ""
        )


        expected_signature = (
            "sha256="
            +
            hmac.new(
                repo_data[
                    "webhook_secret"
                ].encode(),
                msg=body,
                digestmod=hashlib.sha256
            ).hexdigest()
        )


        if not hmac.compare_digest(
            expected_signature,
            signature
        ):

            print(
                "✗ Invalid signature"
            )

            return JSONResponse(
                status_code=401,
                content={
                    "error": "Invalid signature"
                }
            )


        # ----------------------------------------------------
        # PRINT WEBHOOK DETAILS
        # ----------------------------------------------------

        if "pusher" in payload:

            print(
                "  Pusher:",
                payload["pusher"].get(
                    "name",
                    "N/A"
                )
            )


        if "head_commit" in payload:

            print(
                "  Commit:",
                payload["head_commit"].get(
                    "message",
                    "N/A"
                )
            )


        # ----------------------------------------------------
        # SKIP BOT COMMITS
        # ----------------------------------------------------

        if should_skip_commit(
            payload
        ):

            return JSONResponse(
                status_code=200,
                content={
                    "status": "ok",
                    "message": "Commit skipped"
                }
            )


        # ----------------------------------------------------
        # GET COMMIT SHA
        # ----------------------------------------------------

        commit_sha = payload.get(
            "after",
            ""
        )


        if not commit_sha:

            return JSONResponse(
                status_code=200,
                content={
                    "status": "ok",
                    "message": "No commit SHA"
                }
            )


        # ----------------------------------------------------
        # PREVENT DUPLICATE PROCESSING
        # ----------------------------------------------------

        if (
            commit_sha
            in processed_commits
        ):

            print(
                "  ⏭ Skipping: Already processing commit",
                commit_sha
            )

            return JSONResponse(
                status_code=200,
                content={
                    "status": "ok",
                    "message": "Commit already being processed"
                }
            )


        processed_commits.add(
            commit_sha
        )


        try:

            # ------------------------------------------------
            # AUTHENTICATED CLONE URL
            # ------------------------------------------------

            authed_clone_url = (
                repo_data["clone_url"]
                .replace(
                    "https://",
                    f"https://{repo_data['access_token']}@",
                    1
                )
            )


            update_status(
                repo_full_name,
                "queued",
                "New push received — starting documentation update..."
            )


            # ------------------------------------------------
            # START BACKGROUND THREAD
            # ------------------------------------------------

            thread = Thread(
                target=generate_documentation_for_repo,
                args=(
                    authed_clone_url,
                    repo_full_name,
                    commit_sha
                )
            )


            thread.daemon = True

            thread.start()


        except Exception as doc_err:

            print(
                "  ✗ Documentation thread error:",
                str(doc_err)
            )


            if (
                commit_sha
                in processed_commits
            ):

                processed_commits.discard(
                    commit_sha
                )


        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "message": "Webhook received and processing"
            }
        )


    except Exception as e:

        print(
            f"✗ Webhook error: {str(e)}"
        )

        print(
            traceback.format_exc()
        )


        return JSONResponse(
            status_code=200,
            content={
                "status": "error",
                "details": str(e)
            }
        )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000
    )

