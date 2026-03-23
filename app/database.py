from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_size=5,
    max_overflow=10,
)

async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)


async def get_db():
    """FastAPI dependency that yields a database session."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Alias for compatibility with newer code patterns
get_async_session = get_db
