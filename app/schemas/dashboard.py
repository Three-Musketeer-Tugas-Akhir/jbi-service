"""Dashboard API schemas."""

from typing import List
from pydantic import BaseModel, Field


class DashboardStatsCard(BaseModel):
    """Single stats card for dashboard."""
    label: str = Field(..., description="Card label")
    value: int = Field(..., description="Card main value")
    sublabel: str = Field(..., description="Sub label e.g. percentage or delta")
    icon: str = Field("", description="Icon identifier for frontend")


class DashboardPipelineStage(BaseModel):
    """Pipeline progress tracker stage."""
    name: str = Field(..., description="Stage name")
    current: int = Field(..., description="Current completed count")
    total: int = Field(..., description="Total expected count")
    percentage: float = Field(..., description="Completion percentage")
    color: str = Field("", description="Color identifier for frontend")


class DashboardSystemActivity(BaseModel):
    """Recent system activity entry."""
    action: str = Field(..., description="Activity action type")
    description: str = Field(..., description="Human readable description")
    timestamp: str = Field(..., description="ISO timestamp")


class DashboardResponse(BaseModel):
    """Dashboard data response."""
    stats: List[DashboardStatsCard] = Field(..., description="Top level statistics")
    pipeline_progress: List[DashboardPipelineStage] = Field(
        ..., description="Pipeline progress tracker stages"
    )
    conversion_rates: List[float] = Field(
        ..., description="Conversion rate per stage transition"
    )
    system_activities: List[DashboardSystemActivity] = Field(
        ..., description="Recent system activities"
    )
