import asyncio
import logging
from uuid import UUID
from app.db.session import async_session
from app.services.retry_service import RetryService

logging.basicConfig(level=logging.DEBUG)

async def main():
    job_id = "c7319b85-4931-4d52-a82d-90d9071a8071"
    try:
        async with async_session() as session:
            service = RetryService(session)
            # Try partial retry first, since it failed at cropping
            await service.retry_from_stage(UUID(job_id), "cropping")
    except Exception as e:
        logging.exception("Error during retry")

if __name__ == "__main__":
    asyncio.run(main())
