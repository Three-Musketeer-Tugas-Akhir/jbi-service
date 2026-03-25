"""Configuration service for pipeline parameters."""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.pipeline import ConfigPipelineParam
from app.core.exceptions import ValidationError


logger = logging.getLogger(__name__)


# Default configuration values
DEFAULT_CONFIG = {
    "min_segment_duration": "5",
    "max_concurrent_jobs": "3",
    "queue_max_depth": "50",
    "asr_model_default": "base",
    "asr_compute_type": "int8",
    "jbi_buffer_seconds": "2"
}


class ConfigService:
    """Service for managing pipeline configuration."""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_config(self) -> Dict[str, Any]:
        """
        Get current pipeline configuration.
        
        Returns:
            Dict with all config parameters
        """
        result = await self.db.execute(select(ConfigPipelineParam))
        params = result.scalars().all()
        
        # Build config dict, using defaults for missing values
        config = DEFAULT_CONFIG.copy()
        for param in params:
            config[param.key] = param.value
        
        return config
    
    async def update_config(
        self,
        updates: Dict[str, str],
        updated_by: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Update pipeline configuration.
        
        Args:
            updates: Dict of key-value pairs to update
            updated_by: User ID who made the change
            
        Returns:
            Updated full config
            
        Raises:
            ValidationError: If invalid keys or values
        """
        # Validate keys
        invalid_keys = set(updates.keys()) - set(DEFAULT_CONFIG.keys())
        if invalid_keys:
            raise ValidationError(
                f"Invalid config keys: {', '.join(invalid_keys)}",
                details={"valid_keys": list(DEFAULT_CONFIG.keys())}
            )
        
        # Validate values (basic type checking)
        for key, value in updates.items():
            if not self._validate_config_value(key, value):
                raise ValidationError(
                    f"Invalid value for {key}: {value}",
                    details={"key": key, "value": value}
                )
        
        # Update each parameter
        for key, value in updates.items():
            await self._set_param(key, value)
        
        # Log config change
        logger.info(f"Config updated by {updated_by}: {updates}")
        
        return await self.get_config()
    
    async def _set_param(self, key: str, value: str) -> None:
        """Set a single config parameter."""
        # Check if param exists
        result = await self.db.execute(
            select(ConfigPipelineParam).where(ConfigPipelineParam.key == key)
        )
        param = result.scalar_one_or_none()
        
        if param:
            # Update existing
            param.value = value
            param.updated_at = datetime.utcnow()
        else:
            # Create new
            param = ConfigPipelineParam(
                key=key,
                value=value,
                description=f"Pipeline config: {key}"
            )
            self.db.add(param)
        
        await self.db.flush()
    
    def _validate_config_value(self, key: str, value: str) -> bool:
        """Validate a config value based on key."""
        try:
            if key in ["min_segment_duration", "max_concurrent_jobs", "queue_max_depth", "jbi_buffer_seconds"]:
                # Must be positive integer
                int_val = int(value)
                return int_val > 0
            elif key == "asr_model_default":
                # Must be valid model size
                return value in ["tiny", "base", "small", "medium", "large-v3"]
            elif key == "asr_compute_type":
                # Must be valid compute type
                return value in ["int8", "float16", "int8_float16"]
            return True
        except ValueError:
            return False
    
    async def get_param(self, key: str, default: str = None) -> str:
        """
        Get a single config parameter.
        
        Args:
            key: Parameter key
            default: Default value if not set
            
        Returns:
            Parameter value
        """
        result = await self.db.execute(
            select(ConfigPipelineParam).where(ConfigPipelineParam.key == key)
        )
        param = result.scalar_one_or_none()
        
        if param:
            return param.value
        
        return default or DEFAULT_CONFIG.get(key)


# Factory function
def get_config_service(db: AsyncSession) -> ConfigService:
    return ConfigService(db)
