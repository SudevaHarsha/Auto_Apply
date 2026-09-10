"""Test-session event-loop policy (Windows/Python 3.14).

psycopg's async layer refuses the Windows-default ``ProactorEventLoop``; every
``AsyncConnection.connect`` raises ``InterfaceError`` under it. Set the Windows
selector loop policy before any pytest-asyncio loop is created so the DB-backed
suites (integration incl. the opt-in live LLM tests) can open async connections.
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
