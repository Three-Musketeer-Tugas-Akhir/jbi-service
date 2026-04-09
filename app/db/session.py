"""
Database session management.

Provides SQLAlchemy async engine and session factory.
"""

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_size=20,
    max_overflow=30,
    pool_timeout=60,
    pool_recycle=3600,
)

async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False,
)

# Alias for compatibility with audit middleware
async_session_maker = async_session


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


# Context manager for use in services
async def get_db_session():
    """Context manager for database sessions in services."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
