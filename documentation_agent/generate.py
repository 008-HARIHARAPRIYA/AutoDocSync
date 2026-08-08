import asyncio

from google.adk.runners import InMemoryRunner
from google.genai import types

from .agent import root_agent


async def generate_documentation(
    repo_path: str,
    status_callback=None
) -> str:
    """
    Run the ADK documentation agent for a repository.
    """

    if status_callback:
        status_callback(
            "scanning",
            "Starting ADK documentation analysis..."
        )

    runner = InMemoryRunner(
        agent=root_agent,
        app_name="autodocsync"
    )

    # Create a fresh session for every documentation request
    session = await runner.session_service.create_session(
        app_name="autodocsync",
        user_id="documentation_user"
    )

    prompt = f"""
Analyze the software project located at:

{repo_path}

Use the available tools to inspect the project.

Generate the README.md according to the documentation
structure and rules defined in your instructions.

Use ONLY information found in the actual project source code.
Do not invent or assume anything that cannot be verified.
"""

    content = types.Content(
        role="user",
        parts=[
            types.Part(text=prompt)
        ]
    )

    result = ""

    if status_callback:
        status_callback(
            "generating",
            "ADK agent is analyzing the project..."
        )

    async for event in runner.run_async(
        user_id="documentation_user",
        session_id=session.id,
        new_message=content,
    ):

        if event.is_final_response():

            if event.content and event.content.parts:

                result = event.content.parts[0].text

    if status_callback:
        status_callback(
            "generating",
            "ADK documentation generated successfully"
        )

    return result


def generate_docs(repo_path: str, status_callback=None):
    """
    Drop-in replacement for the old doc_generator.generate_docs().
    """

    readme = asyncio.run(
        generate_documentation(
            repo_path,
            status_callback=status_callback
        )
    )

    readme_path = f"{repo_path}/README.md"

    with open(
        readme_path,
        "w",
        encoding="utf-8"
    ) as f:
        f.write(readme)

    if status_callback:
        status_callback(
            "generating",
            "README.md created successfully"
        )

    print(f"📝 README.md created at {readme_path}")

    return readme


def generate_documentation_sync(repo_path: str) -> str:
    """
    Synchronous wrapper for direct testing.
    """

    return asyncio.run(
        generate_documentation(repo_path)
    )