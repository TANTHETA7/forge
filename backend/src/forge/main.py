"""ASGI entry point.

Purpose:       The module `uvicorn` points at (`forge.main:app`).
Responsibility: Expose a single module-level `app` instance for the ASGI server.
Depends on:    core/app_factory.py.
Depended on by: nothing in-repo — this is the process boundary; `uvicorn` and
                Docker's CMD reference it.
"""

from forge.core.app_factory import create_app

app = create_app()
