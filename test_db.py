import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/jbi_db"
engine = create_async_engine(DATABASE_URL)

async def main():
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT id, utterance_corrections FROM annotation_edits WHERE segment_id IN (SELECT id FROM pipeline_segments WHERE job_id = 'b458a235-94b6-4c6e-be35-a86d9975360e')"))
        for row in result.all():
            print(f"Edit ID: {row[0]}")
            utterances = row[1]
            if utterances:
                for u in utterances:
                    print(f"  Utterance {u.get('utterance_index')}: {u.get('cropped_video_path')}")

asyncio.run(main())
