#!/usr/bin/env python3
"""
Progress Tracking and Reporting
Multi-level progress indicators for long-running VLM operations
"""

import json
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print("⚠️  tqdm not available. Install with: pip install tqdm")

logger = logging.getLogger(__name__)


@dataclass
class StageMetrics:
    """Metrics for a single stage"""
    stage_name: str
    start_time: str
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    items_processed: int = 0
    items_failed: int = 0
    status: str = "running"  # running, complete, failed
    error_message: Optional[str] = None


@dataclass
class ProgressState:
    """Persistent progress state for long-running operations"""
    document_name: str
    start_time: str
    current_stage: Optional[str] = None
    completed_stages: List[StageMetrics] = field(default_factory=list)
    completed_items: List[Any] = field(default_factory=list)
    failed_items: List[Any] = field(default_factory=list)
    last_update: Optional[str] = None
    total_items: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        data = asdict(self)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ProgressState':
        """Create from dictionary"""
        # Convert stage dicts back to StageMetrics
        if 'completed_stages' in data:
            data['completed_stages'] = [
                StageMetrics(**s) if isinstance(s, dict) else s
                for s in data['completed_stages']
            ]
        return cls(**data)


class PersistentProgressTracker:
    """
    Persistent progress tracker for resumable operations
    
    Usage:
        tracker = PersistentProgressTracker("hitl_workspace", "my_document")
        
        for item in items:
            if tracker.is_completed(item):
                continue
            
            try:
                process(item)
                tracker.mark_completed(item)
            except Exception as e:
                tracker.mark_failed(item, str(e))
    """
    
    def __init__(self, workspace: Path, document_name: str):
        self.workspace = Path(workspace)
        self.workspace.mkdir(exist_ok=True, parents=True)
        self.progress_file = self.workspace / f"{document_name}_progress.json"
        self.state = self._load()
    
    def _load(self) -> ProgressState:
        """Load progress from file or create new"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file) as f:
                    data = json.load(f)
                    return ProgressState.from_dict(data)
            except Exception as e:
                logger.warning(f"Could not load progress file: {e}")
        
        # Create new state
        return ProgressState(
            document_name=self.progress_file.stem.replace("_progress", ""),
            start_time=datetime.now().isoformat()
        )
    
    def _save(self):
        """Save progress to file"""
        with open(self.progress_file, 'w') as f:
            json.dump(self.state.to_dict(), f, indent=2)
    
    def start_stage(self, stage_name: str, total_items: Optional[int] = None):
        """Start tracking a new stage"""
        self.state.current_stage = stage_name
        if total_items is not None:
            self.state.total_items = total_items
        self._save()
        logger.info(f"📍 Starting stage: {stage_name}")
    
    def end_stage(self, stage_name: str, status: str = "complete"):
        """End tracking a stage"""
        # Find the running stage
        stage_metric = StageMetrics(
            stage_name=stage_name,
            start_time=self.state.start_time,
            end_time=datetime.now().isoformat(),
            items_processed=len(self.state.completed_items),
            items_failed=len(self.state.failed_items),
            status=status
        )
        
        # Calculate duration
        try:
            start = datetime.fromisoformat(self.state.start_time)
            end = datetime.fromisoformat(stage_metric.end_time)
            stage_metric.duration_seconds = (end - start).total_seconds()
        except:
            pass
        
        self.state.completed_stages.append(stage_metric)
        self.state.current_stage = None
        self._save()
        
        logger.info(f"✅ Completed stage: {stage_name} ({stage_metric.duration_seconds:.1f}s)")
    
    def is_completed(self, item: Any) -> bool:
        """Check if item was already completed"""
        return item in self.state.completed_items
    
    def mark_completed(self, item: Any):
        """Mark item as completed"""
        if item not in self.state.completed_items:
            self.state.completed_items.append(item)
        self.state.last_update = datetime.now().isoformat()
        self._save()
    
    def mark_failed(self, item: Any, error: str = ""):
        """Mark item as failed"""
        if item not in self.state.failed_items:
            self.state.failed_items.append(item)
        self.state.last_update = datetime.now().isoformat()
        self._save()
        logger.error(f"❌ Failed item: {item} - {error}")
    
    def get_progress_summary(self) -> str:
        """Get human-readable progress summary"""
        total = self.state.total_items or len(self.state.completed_items) + len(self.state.failed_items)
        completed = len(self.state.completed_items)
        failed = len(self.state.failed_items)
        
        if total > 0:
            pct = (completed / total) * 100
        else:
            pct = 0
        
        return (
            f"Progress: {completed}/{total} ({pct:.0f}%)\n"
            f"Failed: {failed}\n"
            f"Current stage: {self.state.current_stage or 'None'}"
        )
    
    def reset(self):
        """Reset progress (start fresh)"""
        if self.progress_file.exists():
            self.progress_file.unlink()
        self.state = ProgressState(
            document_name=self.state.document_name,
            start_time=datetime.now().isoformat()
        )


class ProgressBar:
    """
    Wrapper for tqdm progress bar with fallback
    
    Usage:
        with ProgressBar(items, desc="Processing") as pbar:
            for item in pbar:
                process(item)
    """
    
    def __init__(self, iterable=None, total=None, desc=None, unit="item", **kwargs):
        self.iterable = iterable
        self.total = total or (len(iterable) if iterable else None)
        self.desc = desc
        self.unit = unit
        self.kwargs = kwargs
        self.pbar = None
        self.index = 0
    
    def __enter__(self):
        if TQDM_AVAILABLE:
            self.pbar = tqdm(
                self.iterable,
                total=self.total,
                desc=self.desc,
                unit=self.unit,
                **self.kwargs
            )
            return self.pbar
        else:
            # Fallback: simple logging
            if self.desc:
                logger.info(f"🔄 {self.desc}: Starting...")
            return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.pbar:
            self.pbar.close()
        else:
            if self.desc:
                logger.info(f"✅ {self.desc}: Complete")
    
    def __iter__(self):
        if self.pbar:
            return iter(self.pbar)
        else:
            return iter(self.iterable)
    
    def update(self, n=1):
        """Update progress"""
        if self.pbar:
            self.pbar.update(n)
        else:
            self.index += n
            if self.total and self.index % max(1, self.total // 10) == 0:
                pct = (self.index / self.total) * 100
                logger.info(f"  Progress: {self.index}/{self.total} ({pct:.0f}%)")


class TimeEstimator:
    """
    Estimate remaining time based on completed items
    
    Usage:
        estimator = TimeEstimator(total_items=100)
        
        for item in items:
            process(item)
            estimator.update()
            print(estimator.get_eta())
    """
    
    def __init__(self, total_items: int):
        self.total = total_items
        self.completed = 0
        self.start_time = time.time()
        self.item_times: List[float] = []
        self.last_update = self.start_time
    
    def update(self, n: int = 1):
        """Update with completed items"""
        now = time.time()
        item_time = (now - self.last_update) / n
        self.item_times.append(item_time)
        
        # Keep only recent samples for better estimates
        if len(self.item_times) > 20:
            self.item_times.pop(0)
        
        self.completed += n
        self.last_update = now
    
    def get_eta(self) -> str:
        """Get estimated time remaining"""
        if self.completed == 0:
            return "Calculating..."
        
        # Average time per item
        avg_time = sum(self.item_times) / len(self.item_times)
        
        # Remaining items
        remaining = self.total - self.completed
        
        # Estimated seconds
        eta_seconds = remaining * avg_time
        
        return str(timedelta(seconds=int(eta_seconds)))
    
    def get_rate(self) -> float:
        """Get processing rate (items/second)"""
        if not self.item_times:
            return 0.0
        
        avg_time = sum(self.item_times) / len(self.item_times)
        return 1.0 / avg_time if avg_time > 0 else 0.0
    
    def get_summary(self) -> str:
        """Get progress summary with ETA"""
        pct = (self.completed / self.total) * 100
        elapsed = timedelta(seconds=int(time.time() - self.start_time))
        
        return (
            f"Progress: {self.completed}/{self.total} ({pct:.0f}%)\n"
            f"Elapsed: {elapsed}\n"
            f"ETA: {self.get_eta()}\n"
            f"Rate: {self.get_rate():.2f} items/sec"
        )


@contextmanager
def log_operation(operation: str, **kwargs):
    """
    Context manager for logging operations with timing
    
    Usage:
        with log_operation("Load PDF", path="/path/to/file.pdf"):
            pdf = load_pdf()
    """
    params_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
    logger.info(f"▶️  {operation}" + (f" ({params_str})" if params_str else ""))
    start = time.time()
    
    try:
        yield
    except Exception as e:
        elapsed = time.time() - start
        logger.error(f"❌ {operation} failed after {elapsed:.1f}s: {e}")
        raise
    else:
        elapsed = time.time() - start
        logger.info(f"✅ {operation} complete ({elapsed:.1f}s)")


class StructuredLogger:
    """
    Hierarchical context-aware logger
    
    Usage:
        log = StructuredLogger()
        
        with log.context("Pipeline"):
            with log.context("Stage 1"):
                # ... work ...
                pass
    """
    
    def __init__(self, logger_name: Optional[str] = None):
        self.logger = logging.getLogger(logger_name or __name__)
        self.context_stack: List[str] = []
    
    @contextmanager
    def context(self, operation: str, **kwargs):
        """Add context level"""
        self.context_stack.append(operation)
        context_path = " → ".join(self.context_stack)
        
        params_str = ", ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.info(f"▶️  [{context_path}] Starting" + (f" ({params_str})" if params_str else ""))
        
        start = time.time()
        
        try:
            yield
        except Exception as e:
            elapsed = time.time() - start
            self.logger.error(f"❌ [{context_path}] Failed after {elapsed:.1f}s: {e}")
            raise
        finally:
            elapsed = time.time() - start
            self.logger.info(f"✅ [{context_path}] Complete ({elapsed:.1f}s)")
            self.context_stack.pop()


# ===== Example Usage =====

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    
    # Example 1: Progress bar
    print("\n=== Example 1: Progress Bar ===")
    items = range(50)
    with ProgressBar(items, desc="Processing items", unit="item") as pbar:
        for item in pbar:
            time.sleep(0.05)
    
    # Example 2: Time estimator
    print("\n=== Example 2: Time Estimator ===")
    estimator = TimeEstimator(total_items=20)
    for i in range(20):
        time.sleep(0.1)
        estimator.update()
        if i % 5 == 0:
            print(estimator.get_summary())
    
    # Example 3: Persistent progress
    print("\n=== Example 3: Persistent Progress ===")
    tracker = PersistentProgressTracker(Path("."), "test_doc")
    tracker.start_stage("Processing", total_items=10)
    
    for i in range(10):
        if tracker.is_completed(f"item_{i}"):
            print(f"Skipping item_{i} (already done)")
            continue
        
        time.sleep(0.05)
        tracker.mark_completed(f"item_{i}")
    
    tracker.end_stage("Processing")
    print(tracker.get_progress_summary())
    
    # Example 4: Structured logging
    print("\n=== Example 4: Structured Logging ===")
    log = StructuredLogger()
    
    with log.context("Pipeline"):
        with log.context("Stage 1", pages=5):
            time.sleep(0.1)
        with log.context("Stage 2", pages=10):
            time.sleep(0.1)
