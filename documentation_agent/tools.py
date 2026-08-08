import os


def read_project_code(repo_path: str) -> str:
    """
    Read supported source-code files from the supplied repository path.
    """

    supported_extensions = (
        ".html", ".css", ".js",
        ".java",
        ".py",
        ".cpp", ".c", ".h",
        ".ts", ".tsx", ".jsx",
        ".go", ".rs", ".rb",
        ".php", ".sql"
    )

    combined_code = ""
    file_count = 0

    for root, _, files in os.walk(repo_path):

        if any(
            skip in root
            for skip in [
                ".git",
                "node_modules",
                "__pycache__",
                "venv",
                "target",
                "build"
            ]
        ):
            continue

        for file in files:

            if file.endswith(supported_extensions):

                file_path = os.path.join(root, file)

                try:
                    with open(
                        file_path,
                        "r",
                        encoding="utf-8"
                    ) as f:

                        relative_path = os.path.relpath(
                            file_path,
                            repo_path
                        )

                        combined_code += (
                            f"\n\n### File: {relative_path}\n"
                        )

                        combined_code += f.read()
                        combined_code += "\n"

                        file_count += 1

                except Exception as e:
                    print(
                        f"Could not read {file}: {str(e)}"
                    )

    print(f"Found {file_count} code files")

    return (
        f"Found {file_count} supported source files.\n"
        "The following content was read from the local repository:\n"
        + combined_code
    )