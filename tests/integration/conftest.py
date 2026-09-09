"""Integration test bootstrap: force a SelectorEventLoop on Windows.

psycopg async connections refuse the Windows ProactorEventLoop, so pytest-asyncio
must create loops under the selector policy. Setting the policy at import time makes
``asyncio.new_event_loop()`` (used by pytest-asyncio) return a compatible loop.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
