import sys
from pathlib import Path
sys.path.insert(0, r"c:\Users\chaud\study-abroad-agent\backend")
from sqlalchemy import text
from app.services.phase2.db import session_scope

async def test():
    async with session_scope() as session:
        r = await session.execute(text("SELECT course_title, syllabus_description, field_broad, field_narrow, field_detailed FROM courses WHERE course_title ILIKE '%traduction%' LIMIT 1"))
        row = r.fetchone()
        print("Title:", row[0])
        print("Desc:", row[1])
        print("Broad:", row[2])
        print("Narrow:", row[3])
        print("Detailed:", row[4])

import asyncio
asyncio.run(test())
