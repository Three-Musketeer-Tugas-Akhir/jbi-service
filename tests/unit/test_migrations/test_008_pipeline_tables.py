"""Tests for migration 008_add_pipeline_tables."""

import pytest
from sqlalchemy import inspect


class TestPipelineTablesMigration:
    """Tests for pipeline domain migration."""
    
    def test_pipeline_jobs_table_exists(self, db_engine):
        """Test pipeline_jobs table was created."""
        inspector = inspect(db_engine)
        assert "pipeline_jobs" in inspector.get_table_names()
    
    def test_pipeline_segments_table_exists(self, db_engine):
        """Test pipeline_segments table was created."""
        inspector = inspect(db_engine)
        assert "pipeline_segments" in inspector.get_table_names()
    
    def test_pipeline_job_logs_table_exists(self, db_engine):
        """Test pipeline_job_logs table was created."""
        inspector = inspect(db_engine)
        assert "pipeline_job_logs" in inspector.get_table_names()
    
    def test_queue_jobs_table_exists(self, db_engine):
        """Test queue_jobs table was created."""
        inspector = inspect(db_engine)
        assert "queue_jobs" in inspector.get_table_names()
    
    def test_config_pipeline_params_table_exists(self, db_engine):
        """Test config_pipeline_params table was created."""
        inspector = inspect(db_engine)
        assert "config_pipeline_params" in inspector.get_table_names()
    
    def test_pipeline_jobs_indexes_exist(self, db_engine):
        """Test pipeline_jobs indexes were created."""
        inspector = inspect(db_engine)
        indexes = {idx['name'] for idx in inspector.get_indexes('pipeline_jobs')}
        
        assert 'idx_pipeline_jobs_status' in indexes
        assert 'idx_pipeline_jobs_created_by' in indexes
        assert 'idx_pipeline_jobs_created_at' in indexes
    
    def test_pipeline_segments_indexes_exist(self, db_engine):
        """Test pipeline_segments indexes were created."""
        inspector = inspect(db_engine)
        indexes = {idx['name'] for idx in inspector.get_indexes('pipeline_segments')}
        
        assert 'idx_pipeline_segments_job_id' in indexes
    
    def test_pipeline_job_logs_indexes_exist(self, db_engine):
        """Test pipeline_job_logs indexes were created."""
        inspector = inspect(db_engine)
        indexes = {idx['name'] for idx in inspector.get_indexes('pipeline_job_logs')}
        
        assert 'idx_pipeline_job_logs_job_id' in indexes
        assert 'idx_pipeline_job_logs_created_at' in indexes
    
    def test_queue_jobs_indexes_exist(self, db_engine):
        """Test queue_jobs indexes were created."""
        inspector = inspect(db_engine)
        indexes = {idx['name'] for idx in inspector.get_indexes('queue_jobs')}
        
        assert 'idx_queue_jobs_status' in indexes
        assert 'idx_queue_jobs_queue_name' in indexes
        assert 'idx_queue_jobs_scheduled_at' in indexes
    
    def test_default_config_params_exist(self, db_session):
        """Test default configuration parameters were inserted."""
        from app.db.models.pipeline import ConfigPipelineParam
        
        params = db_session.query(ConfigPipelineParam).all()
        param_keys = {p.key for p in params}
        
        expected_keys = {
            "min_segment_duration",
            "max_concurrent_jobs",
            "queue_max_depth",
            "asr_model_default",
            "jbi_buffer_seconds"
        }
        
        assert expected_keys.issubset(param_keys)
    
    def test_pipeline_jobs_foreign_key_exists(self, db_engine):
        """Test foreign key from pipeline_jobs to auth_users."""
        inspector = inspect(db_engine)
        foreign_keys = inspector.get_foreign_keys('pipeline_jobs')
        
        fk_names = {fk['name'] for fk in foreign_keys}
        assert 'fk_pipeline_jobs_created_by' in fk_names
    
    def test_pipeline_segments_foreign_key_exists(self, db_engine):
        """Test foreign key from pipeline_segments to pipeline_jobs."""
        inspector = inspect(db_engine)
        foreign_keys = inspector.get_foreign_keys('pipeline_segments')
        
        fk_names = {fk['name'] for fk in foreign_keys}
        assert 'fk_pipeline_segments_job_id' in fk_names
    
    def test_pipeline_job_logs_foreign_key_exists(self, db_engine):
        """Test foreign key from pipeline_job_logs to pipeline_jobs."""
        inspector = inspect(db_engine)
        foreign_keys = inspector.get_foreign_keys('pipeline_job_logs')
        
        fk_names = {fk['name'] for fk in foreign_keys}
        assert 'fk_pipeline_job_logs_job_id' in fk_names
