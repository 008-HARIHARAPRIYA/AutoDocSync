import os

from documentation_agent.generate import generate_documentation_sync


def generate_docs(repo_path, status_callback=None):
    """
    Generate README.md using the Google ADK documentation agent.
    """

    print("  🔍 Starting ADK documentation generation...")

    if status_callback:
        status_callback(
            "scanning",
            "Starting project analysis with ADK..."
        )

    try:
        # Send the actual cloned repository path to the ADK agent
        readme = generate_documentation_sync(repo_path)

        if not readme or not readme.strip():
            readme = (
                "# Project Documentation\n\n"
                "No documentation was generated."
            )

            if status_callback:
                status_callback(
                    "error",
                    "ADK returned empty documentation"
                )

        else:
            print("  ✓ Documentation generated using ADK")

            if status_callback:
                status_callback(
                    "generating",
                    "AI documentation generated using ADK"
                )

        # Write README.md into the cloned repository
        readme_path = os.path.join(repo_path, "README.md")

        with open(
            readme_path,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(readme)

        print(f"  📝 README.md created at {readme_path}")

        return readme

    except Exception as e:
        print(f"  ✗ ADK documentation error: {str(e)}")

        if status_callback:
            status_callback(
                "error",
                f"Documentation generation failed: {str(e)}"
            )

        raise