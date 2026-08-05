import os
from gemini_service import generate_readme_from_code

def read_project_code(repo_path):
    """Read all code files from the repository"""
    combined_code = ""
    
    # Support multiple file extensions
    supported_extensions = (
        ".html", ".css", ".js",      # Web files
        ".java",                      # Java
        ".py",                        # Python
        ".cpp", ".c", ".h",          # C/C++
        ".ts", ".tsx", ".jsx",       # TypeScript/React
        ".go", ".rs", ".rb",         # Go, Rust, Ruby
        ".php", ".sql"               # PHP, SQL
    )

    file_count = 0
    for root, _, files in os.walk(repo_path):
        # Skip common directories that shouldn't be documented
        if any(skip in root for skip in ['.git', 'node_modules', '__pycache__', 'venv', 'target', 'build']):
            continue
            
        for file in files:
            if file.endswith(supported_extensions):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        relative_path = os.path.relpath(file_path, repo_path)
                        combined_code += f"\n\n### File: {relative_path}\n"
                        combined_code += f"```{get_language(file)}\n"
                        combined_code += f.read()
                        combined_code += "\n```\n"
                        file_count += 1
                except Exception as e:
                    print(f"  ⚠ Could not read {file}: {str(e)}")
                    pass

    print(f"  📄 Found {file_count} code files")
    return combined_code


def get_language(filename):
    """Get language identifier for markdown code blocks"""
    ext = os.path.splitext(filename)[1]
    language_map = {
        '.java': 'java',
        '.py': 'python',
        '.js': 'javascript',
        '.ts': 'typescript',
        '.html': 'html',
        '.css': 'css',
        '.cpp': 'cpp',
        '.c': 'c',
        '.go': 'go',
        '.rs': 'rust',
        '.rb': 'ruby',
        '.php': 'php',
        '.sql': 'sql'
    }
    return language_map.get(ext, '')


def generate_docs(repo_path):
    """Generate README.md from project code"""
    print(f"  🔍 Scanning project files...")
    code = read_project_code(repo_path)

    if not code.strip():
        readme = "# Project Documentation\n\nNo supported code files found in this repository."
        print(f"  ⚠ No code files found")
    else:
        print(f"  🤖 Generating documentation with AI...")
        readme = generate_readme_from_code(code)
        print(f"  ✓ Documentation generated")

    readme_path = os.path.join(repo_path, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme)
    
    print(f"  📝 README.md created at {readme_path}")