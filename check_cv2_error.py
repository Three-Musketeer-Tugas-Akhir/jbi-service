import asyncio
from sqlalchemy import select
from app.db.session import async_session
from app.db.models.pipeline import JobStatus, PipelineSegment, PipelineTranscript

async def check():
    async with async_session() as session:
        # Get the latest FAILED job
        query = select(PipelineSegment).order_by(PipelineSegment.created_at.desc()).limit(1)
        result = await session.execute(query)
        segment = result.scalar_one_or_none()
        
        if segment:
            print(f"Latest Segment: {segment.id} for Job: {segment.job_id}")
            
            # Get transcripts
            t_query = select(PipelineTranscript).where(PipelineTranscript.segment_id == segment.id)
            t_result = await session.execute(t_query)
            transcripts = t_result.scalars().all()
            
            for t in transcripts:
                print(f"Utterance {t.utterance_index}: status={t.status}")
        else:
            print("No segments found")

if __name__ == "__main__":
    asyncio.run(check())
