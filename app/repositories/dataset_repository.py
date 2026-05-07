"""Dataset repository for database operations."""

from typing import Optional, List
from uuid import UUID

from fastapi import Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dataset import Dataset
from app.db.session import get_db


class DatasetRepository:
    """Repository for dataset operations."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create(
        self,
        name: str,
        description: Optional[str] = None,
        created_by: Optional[UUID] = None
    ) -> Dataset:
        """Create a new dataset.
        
        Args:
            name: Dataset name
            description: Optional description
            created_by: UUID of the user who created the dataset
            
        Returns:
            Created Dataset instance
        """
        dataset = Dataset(
            name=name,
            description=description,
            created_by=created_by,
        )
        self.db.add(dataset)
        await self.db.flush()
        await self.db.refresh(dataset)
        return dataset
    
    async def get_by_id(self, dataset_id: UUID) -> Optional[Dataset]:
        """Get dataset by ID."""
        result = await self.db.execute(
            select(Dataset).where(Dataset.id == dataset_id)
        )
        return result.scalar_one_or_none()
    
    async def list_all(
        self,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[List[Dataset], int]:
        """List all datasets with pagination.
        
        Returns:
            Tuple of (list of datasets, total count)
        """
        count_result = await self.db.execute(select(func.count(Dataset.id)))
        total = count_result.scalar() or 0
        
        result = await self.db.execute(
            select(Dataset)
            .order_by(Dataset.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        records = result.scalars().all()
        return list(records), total
    
    async def update(
        self,
        dataset_id: UUID,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[Dataset]:
        """Update a dataset."""
        dataset = await self.get_by_id(dataset_id)
        if not dataset:
            return None
        
        if name is not None:
            dataset.name = name
        if description is not None:
            dataset.description = description
        
        await self.db.flush()
        await self.db.refresh(dataset)
        return dataset
    
    async def delete(self, dataset_id: UUID) -> bool:
        """Delete a dataset."""
        dataset = await self.get_by_id(dataset_id)
        if not dataset:
            return False
        
        await self.db.delete(dataset)
        await self.db.flush()
        return True


def get_dataset_repository(db: AsyncSession = Depends(get_db)) -> DatasetRepository:
    return DatasetRepository(db)
