"""
Pipeline Service - Manages HITL pipeline subprocess execution.

This service orchestrates the document processing pipeline as a subprocess
and tracks its status through file system monitoring and database updates.
"""
import asyncio
import logging
import uuid
from uuid import UUID
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from ..core.config import settings, get_artifacts_path
from ..models.pipeline import (
    PipelineStatus,
    PipelineStatusResponse,
    PipelineProgressUpdate,
    PipelineStageComplete,
    PipelineError,
    PipelineComplete,
)

logger = logging.getLogger(__name__)


class PipelineService:
    """Service for managing pipeline subprocess execution."""
    
    # Track active pipeline processes
    _active_processes: Dict[str, asyncio.subprocess.Process] = {}
    _status_cache: Dict[str, PipelineStatusResponse] = {}
    
    @classmethod
    async def trigger_pipeline(
        cls,
        document_id: str,
        pdf_path: str,
        reviewer: str,
        db: AsyncSession,
    ) -> str:
        """
        Trigger HITL pipeline for a document.
        
        Args:
            document_id: Document UUID
            pdf_path: Path to uploaded PDF file
            reviewer: Reviewer username
            db: Database session
            
        Returns:
            Job ID for tracking
        """
        job_id = str(uuid.uuid4())
        logger.info(f"Starting pipeline for document {document_id}, job {job_id}")
        
        # Update document status to extracting
        from sqlalchemy import text
        await db.execute(
            text("""
                UPDATE documents 
                SET status = 'extracting'
                WHERE id = :doc_id
            """),
            {"doc_id": document_id}
        )
        await db.commit()
        
        # Prepare pipeline command
        work_dir = Path(settings.PIPELINE_WORK_DIR) / document_id
        work_dir.mkdir(parents=True, exist_ok=True)
        
        # Generate initial markdown path (pipeline will create it)
        markdown_path = work_dir / f"{Path(pdf_path).stem}.md"
        if not markdown_path.exists():
            markdown_path.write_text(
                f"# {Path(pdf_path).stem}\n\n"
                "Initial placeholder markdown created by backend upload workflow.\n"
                "Replace with Docling-extracted markdown for full-quality pipeline results.\n",
                encoding="utf-8",
            )
        
        pipeline_script = Path(settings.PIPELINE_SCRIPT_PATH).resolve()
        repo_root = pipeline_script.parents[3]

        cmd = [
            settings.PIPELINE_PYTHON_PATH,
            "-m",
            "pipeline.src.cli.hitl_pipeline",
            "run",
            "--pdf", pdf_path,
            "--markdown", str(markdown_path),
            "--workspace", str(work_dir),
            "--reviewer", reviewer,
        ]
        
        # Start subprocess asynchronously
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(repo_root),
            )
            
            cls._active_processes[job_id] = process
            
            # Monitor process in background
            asyncio.create_task(cls._monitor_pipeline(job_id, document_id, process, work_dir))
            
            logger.info(f"Pipeline started for document {document_id}")
            return job_id
            
        except Exception as e:
            logger.error(f"Failed to start pipeline: {e}")
            # Update document status to failed
            from sqlalchemy import text
            await db.execute(
                text("UPDATE documents SET status = 'failed' WHERE id = :doc_id"),
                {"doc_id": document_id}
            )
            await db.commit()
            raise
    
    @classmethod
    async def _monitor_pipeline(
        cls,
        job_id: str,
        document_id: str,
        process: asyncio.subprocess.Process,
        work_dir: Path,
    ):
        """Monitor pipeline subprocess and update status."""
        try:
            # Wait for process to complete
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=settings.PIPELINE_TIMEOUT_SECONDS
            )
            
            exit_code = process.returncode
            
            if exit_code == 0:
                logger.info(f"Pipeline completed successfully for document {document_id}")
                await cls._update_document_status(
                    document_id,
                    PipelineStatus.VALIDATION_COMPLETE,
                    progress=100
                )
            else:
                logger.error(f"Pipeline failed for document {document_id}: {stderr.decode()}")
                await cls._update_document_status(
                    document_id,
                    PipelineStatus.FAILED,
                    error=stderr.decode()[:500]
                )
                
        except asyncio.TimeoutError:
            logger.error(f"Pipeline timed out for document {document_id}")
            process.kill()
            await cls._update_document_status(
                document_id,
                PipelineStatus.FAILED,
                error="Pipeline execution timed out"
            )
        except Exception as e:
            logger.error(f"Pipeline monitoring error for document {document_id}: {e}")
            await cls._update_document_status(
                document_id,
                PipelineStatus.FAILED,
                error=str(e)
            )
        finally:
            # Cleanup
            cls._active_processes.pop(job_id, None)
    
    @classmethod
    async def _update_document_status(
        cls,
        document_id: str,
        status: PipelineStatus,
        progress: int = 0,
        error: Optional[str] = None
    ):
        """Update document status in database."""
        from ..models.database import get_db
        from sqlalchemy import text
        
        try:
            # Use a new session for background updates
            async for db in get_db():
                values = {"status": status.value, "doc_id": document_id}
                sql = "UPDATE documents SET status = :status WHERE id = :doc_id"
                
                if error:
                    values["notes"] = error
                    sql = "UPDATE documents SET status = :status, notes = :notes WHERE id = :doc_id"
                
                await db.execute(text(sql), values)
                await db.commit()
                break  # Exit after first session
        except Exception as e:
            logger.error(f"Failed to update document status: {e}")
    
    @classmethod
    async def get_pipeline_status(
        cls,
        document_id: str,
        db: AsyncSession,
    ) -> PipelineStatusResponse:
        """
        Get current pipeline status for a document.
        
        Args:
            document_id: Document UUID
            db: Database session
            
        Returns:
            Pipeline status information
        """
        # Query database for document status
        from sqlalchemy import text
        
        result = await db.execute(
            text("SELECT status, created_at, updated_at, notes FROM documents WHERE id = :doc_id"),
            {"doc_id": document_id}
        )
        row = result.fetchone()
        
        if not row:
            raise ValueError(f"Document {document_id} not found")
        
        status, created_at, updated_at, notes = row
        
        # Check if pipeline is active
        is_active = status in [
            PipelineStatus.UPLOADING.value,
            PipelineStatus.EXTRACTING.value,
            PipelineStatus.VLM_VALIDATING.value,
        ]
        
        # Calculate progress based on status
        progress_map = {
            PipelineStatus.PENDING.value: 0,
            PipelineStatus.UPLOADING.value: 10,
            PipelineStatus.EXTRACTING.value: 30,
            PipelineStatus.VLM_VALIDATING.value: 60,
            PipelineStatus.VALIDATION_COMPLETE.value: 100,
            PipelineStatus.IN_REVIEW.value: 100,
            PipelineStatus.REVIEW_COMPLETE.value: 100,
            PipelineStatus.APPROVED.value: 100,
            PipelineStatus.REJECTED.value: 100,
            PipelineStatus.FAILED.value: 0,
        }
        
        progress = progress_map.get(status, 0)
        
        # Determine current stage
        stage = None
        if status == PipelineStatus.EXTRACTING.value:
            stage = "extraction"
        elif status == PipelineStatus.VLM_VALIDATING.value:
            stage = "vlm-validation"
        
        return PipelineStatusResponse(
            document_id=UUID(document_id),
            status=PipelineStatus(status),
            current_stage=stage,
            progress=progress,
            message=notes if status == PipelineStatus.FAILED.value else None,
            started_at=created_at,
            completed_at=updated_at if progress == 100 else None,
            error=notes if status == PipelineStatus.FAILED.value else None,
        )
    
    @classmethod
    async def get_artifact(
        cls,
        document_id: str,
        artifact_type: str,
    ) -> Path:
        """
        Get path to document artifact.
        
        Args:
            document_id: Document UUID
            artifact_type: Type of artifact (validation, manifest, qa_report, etc.)
            
        Returns:
            Path to artifact file
        """
        artifact_path = get_artifacts_path(document_id, artifact_type)
        
        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact {artifact_type} not found for document {document_id}")
        
        return artifact_path
