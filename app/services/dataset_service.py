"""Dataset service for business logic."""

from typing import Optional, List
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dataset import Dataset
from app.repositories.dataset_repository import DatasetRepository


class DatasetService:
    """Service for dataset lifecycle management."""
    
    def __init__(self, db: AsyncSession, dataset_repo: DatasetRepository):
        self.db = db
        self.dataset_repo = dataset_repo
    
    async def create_dataset(
        self,
        name: str,
        description: Optional[str] = None,
        created_by: Optional[UUID] = None
    ) -> Dataset:
        """Create a new dataset/project.
        
        Args:
            name: Dataset name
            description: Optional description
            created_by: User ID who created it
            
        Returns:
            Created Dataset
        """
        dataset = await self.dataset_repo.create(
            name=name,
            description=description,
            created_by=created_by
        )
        await self.db.commit()
        return dataset
    
    async def list_datasets(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> dict:
        """List all datasets.
        
        Returns:
            Paginated response dict
        """
        records, total = await self.dataset_repo.list_all(limit=limit, offset=offset)
        
        return {
            "items": records,
            "total": total,
            "limit": limit,
            "offset": offset
        }
    
    async def get_dataset(self, dataset_id: str) -> Optional[Dataset]:
        """Get a single dataset by ID."""
        try:
            uuid_id = UUID(dataset_id)
        except ValueError:
            return None
        return await self.dataset_repo.get_by_id(uuid_id)


def get_dataset_service(
    db: AsyncSession,
    dataset_repo: DatasetRepository
) -> DatasetService:
    return DatasetService(db, dataset_repo)
