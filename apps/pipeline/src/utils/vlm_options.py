#!/usr/bin/env python3
"""
VLM Options Configuration
Standardized VLM configuration for all operations across the pipeline
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, Dict, Any
import json
import yaml
from pathlib import Path
import os


REPO_ROOT = Path(__file__).resolve().parents[4]
ROOT_ENV_PATH = REPO_ROOT / ".env"
DEFAULT_TEXT_MODEL_ID = "Qwen/Qwen3-4B"
DEFAULT_VISION_MODEL_ID = "Qwen/Qwen3-VL-4B-Instruct"
DEFAULT_REQUIRED_CUDA_PHYSICAL_INDEX = 0


def _get_required_cuda_physical_index() -> int:
    """Return the required physical CUDA device index for pipeline model execution."""
    raw_value = str(os.getenv("PIPELINE_CUDA_DEVICE_INDEX", DEFAULT_REQUIRED_CUDA_PHYSICAL_INDEX)).strip()
    try:
        index = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "PIPELINE_CUDA_DEVICE_INDEX must be an integer. "
            f"Received: {raw_value!r}."
        ) from exc

    if index < 0:
        raise RuntimeError(
            "PIPELINE_CUDA_DEVICE_INDEX must be >= 0. "
            f"Received: {index}."
        )
    return index


def _parse_visible_cuda_devices(cuda_visible_devices: str | None) -> list[int] | None:
    """Parse CUDA_VISIBLE_DEVICES into physical GPU indices when possible."""
    if cuda_visible_devices is None:
        return None

    raw = cuda_visible_devices.strip()
    if not raw:
        return None

    parsed_indices: list[int] = []
    for token in raw.split(","):
        cleaned = token.strip()
        if not cleaned:
            continue
        try:
            parsed_indices.append(int(cleaned))
        except ValueError:
            # Non-integer tokens (UUIDs/MIG aliases) cannot be safely mapped here.
            return None
    return parsed_indices


def get_required_cuda_index_for_runtime(environ: Dict[str, str] | None = None) -> int:
    """Resolve required CUDA index for the current runtime, honoring CUDA_VISIBLE_DEVICES remapping."""
    env = environ or os.environ
    required_physical_index = _get_required_cuda_physical_index()
    visible_devices = _parse_visible_cuda_devices(env.get("CUDA_VISIBLE_DEVICES"))

    if visible_devices is None:
        return required_physical_index

    if required_physical_index not in visible_devices:
        raise RuntimeError(
            "Required GPU is not visible in current runtime. "
            f"Required physical GPU index: {required_physical_index}. "
            f"Current CUDA_VISIBLE_DEVICES={env.get('CUDA_VISIBLE_DEVICES')!r}. "
            "Set CUDA_VISIBLE_DEVICES to include the required GPU or unset it."
        )

    return visible_devices.index(required_physical_index)


def build_gpu1_constrained_subprocess_env(base_env: Dict[str, str] | None = None) -> Dict[str, str]:
    """Build subprocess environment constrained to the required physical GPU only."""
    source_env = base_env if base_env is not None else os.environ
    env = dict(source_env)
    required_physical_index = _get_required_cuda_physical_index()

    # Stable mapping: only required physical GPU is visible to child process,
    # where it becomes cuda:0 from the subprocess perspective.
    env["CUDA_VISIBLE_DEVICES"] = str(required_physical_index)
    env["PIPELINE_CUDA_DEVICE_INDEX"] = str(required_physical_index)
    return env


def gather_gpu_preflight_info(
    torch_module: Any = None, environ: Dict[str, str] | None = None
) -> Dict[str, Any]:
    """Probe GPU runtime availability and return structured metadata without side effects.

    Does NOT call ``set_device`` or raise exceptions. Suitable for early transparency
    logging and preflight validation before model loading begins.

    Returned keys
    -------------
    cuda_available           : bool
    cuda_device_count_visible: int
    cuda_visible_devices_raw : str | None   (raw CUDA_VISIBLE_DEVICES value)
    required_gpu_physical_index: int
    resolved_runtime_index   : int | None   (runtime-mapped index, None on failure)
    selected_device          : str | None   (e.g. "cuda:0")
    device_name              : str | None
    preflight_passed         : bool
    failure_reason           : str | None
    error_code               : str | None
    retryable                : bool
    recommended_action       : str | None
    """
    env = environ if environ is not None else os.environ
    visible_devices_raw = env.get("CUDA_VISIBLE_DEVICES")
    required_physical_index = _get_required_cuda_physical_index()

    result: Dict[str, Any] = {
        "required_gpu_physical_index": required_physical_index,
        "cuda_visible_devices_raw": visible_devices_raw,
        "cuda_available": False,
        "cuda_device_count_visible": 0,
        "resolved_runtime_index": None,
        "selected_device": None,
        "device_name": None,
        "preflight_passed": False,
        "failure_reason": None,
        "error_code": None,
        "retryable": False,
        "recommended_action": None,
    }

    if torch_module is None:
        result["failure_reason"] = "torch_unavailable"
        result["error_code"] = "TORCH_UNAVAILABLE"
        result["recommended_action"] = "Install torch with CUDA support in the active environment."
        return result

    cuda_available = bool(torch_module.cuda.is_available())
    result["cuda_available"] = cuda_available

    if not cuda_available:
        result["failure_reason"] = "cuda_unavailable"
        result["error_code"] = "CUDA_UNAVAILABLE"
        result["recommended_action"] = (
            "Verify NVIDIA drivers/runtime and that the required GPU is accessible. "
            "This pipeline requires GPU execution and will not fall back to CPU."
        )
        return result

    device_count = int(torch_module.cuda.device_count())
    result["cuda_device_count_visible"] = device_count

    try:
        resolved_index = get_required_cuda_index_for_runtime(env)
    except RuntimeError as exc:
        result["failure_reason"] = str(exc)
        result["error_code"] = "GPU_NOT_IN_VISIBLE_DEVICES"
        result["recommended_action"] = (
            "Set CUDA_VISIBLE_DEVICES to include the required GPU or unset it."
        )
        return result

    result["resolved_runtime_index"] = resolved_index

    if resolved_index >= device_count:
        result["failure_reason"] = (
            f"Required GPU runtime index {resolved_index} exceeds "
            f"visible device count {device_count}."
        )
        result["error_code"] = "GPU_INDEX_OUT_OF_RANGE"
        result["recommended_action"] = "Ensure the required GPU index is present and visible to this process."
        return result

    result["selected_device"] = f"cuda:{resolved_index}"
    result["preflight_passed"] = True

    try:
        result["device_name"] = torch_module.cuda.get_device_name(resolved_index)
    except Exception:
        result["device_name"] = f"cuda:{resolved_index}"

    return result


def ensure_gpu1_runtime(torch_module: Any) -> int:
    """Validate and activate required CUDA device, failing fast when unavailable."""
    if torch_module is None:
        raise RuntimeError("Torch runtime is unavailable; cannot enforce required GPU execution.")

    if not torch_module.cuda.is_available():
        raise RuntimeError(
            "CUDA is unavailable for pipeline model execution. "
            "This pipeline requires GPU execution and will not fall back to CPU. "
            "Verify NVIDIA drivers/runtime and that the required GPU is accessible."
        )

    required_cuda_index = get_required_cuda_index_for_runtime()
    device_count = int(torch_module.cuda.device_count())
    if required_cuda_index >= device_count:
        required_physical_index = _get_required_cuda_physical_index()
        raise RuntimeError(
            "Required GPU is unavailable in the current runtime. "
            f"Required physical index: {required_physical_index}, "
            f"resolved runtime index: {required_cuda_index}, "
            f"visible CUDA device count: {device_count}. "
            "Ensure the required GPU index is present and visible to this process."
        )

    try:
        torch_module.cuda.set_device(required_cuda_index)
    except Exception as exc:
        raise RuntimeError(
            "Failed to activate required CUDA device for pipeline execution "
            f"(runtime index: {required_cuda_index})."
        ) from exc

    return required_cuda_index


def resolve_model_reference(value: str) -> str:
    """Resolve local model references so they work on both host and container runtimes.

    Supported behavior:
    - leave Hugging Face repo ids unchanged
    - resolve repo-relative paths like ``./models/Qwen3.5-4B`` against ``REPO_ROOT``
    - remap stale host-only absolute paths ending in ``models/...`` to the current
      runtime's ``REPO_ROOT/models/...`` when that directory exists
    """
    if not value:
        return value

    normalized_value = value.strip()

    # Guard: Ollama tags (containing ':') are accepted by Ollama but rejected
    # by transformers' from_pretrained with HFValidationError.  If the caller
    # passes an Ollama tag here it means PIPELINE_TEXT_MODEL_ID is mis-set to
    # an Ollama tag instead of a local model path or HF repo ID.  Fail fast
    # with a clear message rather than propagating the invalid value.
    # SECURITY REVIEW (S5332): String literal contains http:// and https:// for URL validation only.
    #   1. This is defensive code checking if a value starts with URL protocols
    #   2. No actual HTTP requests or protocol configuration here
    #   3. Context: distinguishing between Ollama tags and HF model references
    # Risk: NONE — this is safe string validation, not protocol configuration
    if ":" in normalized_value and not normalized_value.startswith(("http://", "https://")):  # NOSONAR: String validation, not protocol config
        raise ValueError(
            f"resolve_model_reference received an Ollama tag ({normalized_value!r}). "
            "The pipeline optimizer requires a local model path or HF repo ID. "
            "Set PIPELINE_TEXT_MODEL_ID to the local model path, e.g. ./models/Qwen3.5-4B."
        )

    expanded = Path(normalized_value).expanduser()
    if not expanded.is_absolute():
        repo_relative_candidate = (REPO_ROOT / expanded).resolve(strict=False)
        if repo_relative_candidate.exists():
            return str(repo_relative_candidate)
        if expanded.exists():
            return str(expanded.resolve())
        return value

    if expanded.exists():
        return str(expanded.resolve())

    parts = expanded.parts
    if "models" in parts:
        models_index = len(parts) - 1 - parts[::-1].index("models")
        repo_mapped_candidate = (REPO_ROOT / Path(*parts[models_index:])).resolve(strict=False)
        if repo_mapped_candidate.exists():
            return str(repo_mapped_candidate)

    return value


def _read_root_env() -> Dict[str, str]:
    """Read repo-root environment values without requiring external dotenv helpers."""
    if not ROOT_ENV_PATH.exists():
        return {}

    values: Dict[str, str] = {}
    with open(ROOT_ENV_PATH, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")

    return values


def _get_model_id_from_sources(*env_names: str, default: str) -> str:
    """Resolve model identifiers from process env first, then repo-root .env."""
    for env_name in env_names:
        value = os.getenv(env_name)
        if value:
            return resolve_model_reference(value)

    env_values = _read_root_env()
    for env_name in env_names:
        value = env_values.get(env_name)
        if value:
            return resolve_model_reference(value)

    return default


def get_text_model_id() -> str:
    """Return the active text model identifier for the pipeline text reformatter.

    Resolution order (first match wins):
    1. PIPELINE_TEXT_MODEL_ID  – dedicated pipeline var; use a local model path
       (e.g. ./models/Qwen3.5-4B) or an HF repo ID.
    2. TEXT_MODEL_ID            – shared backend var; only valid here when set to
       an HF repo ID or local path (NOT an Ollama tag).
    3. Default                  – Qwen/Qwen3-4B.

    TEXT_MODEL_ID is intentionally checked second so that Ollama deployments
    can safely set it to an Ollama tag for chat without breaking the pipeline.
    """
    return _get_model_id_from_sources(
        "PIPELINE_TEXT_MODEL_ID",
        "TEXT_MODEL_ID",
        "VLLM_MODEL",
        "VLLM_MODEL_NAME",
        default=DEFAULT_TEXT_MODEL_ID,
    )


def get_vision_model_id() -> str:
    """Return the active vision model identifier from the shared repo-root env contract."""
    return _get_model_id_from_sources(
        "VISION_MODEL_ID",
        "VLM_MODEL",
        "VLM_MODEL_NAME",
        default=DEFAULT_VISION_MODEL_ID,
    )


def _get_int_from_sources(*env_names: str, default: int, minimum: int | None = None) -> int:
    """Resolve integer settings from process env first, then repo-root .env."""
    env_values = _read_root_env()

    for env_name in env_names:
        raw_value = os.getenv(env_name)
        if raw_value is None:
            raw_value = env_values.get(env_name)
        if raw_value in (None, ""):
            continue

        value = int(str(raw_value).strip())
        if minimum is not None and value < minimum:
            raise ValueError(f"{env_name} must be >= {minimum}")
        return value

    return default


def get_generation_timeout_seconds(default: int = 300) -> int:
    """Return the streamer wait timeout for text generation chunks."""
    return _get_int_from_sources(
        "GENERATION_TIMEOUT_SECONDS",
        "TEXT_GENERATION_TIMEOUT_SECONDS",
        default=default,
        minimum=1,
    )


class ResponseFormat(Enum):
    """VLM response format options"""
    JSON = "json"
    MARKDOWN = "markdown"
    PLAIN = "plain"


class VLMBackendType(Enum):
    """VLM backend implementation"""
    TRANSFORMERS = "transformers"
    # Future: OLLAMA = "ollama"


@dataclass
class VLMOptions:
    """
    Unified VLM configuration for all operations
    
    This class provides a single source of truth for VLM parameters across:
    - rag_vlm_comparison.py
    - rag_vlm_image_describer.py
    - docling_convert_with_qwen.py
    - rag_text_reformatter.py
    
    Usage:
        # From code
        options = VLMOptions(
            model_id=get_vision_model_id(),
            timeout=300,
            temperature=0.7
        )
        
        # From YAML config
        options = VLMOptions.from_yaml("config.yaml")
        
        # From dict
        options = VLMOptions.from_dict(config_dict)
    """
    
    # ===== Model Selection =====
    backend_type: VLMBackendType = VLMBackendType.TRANSFORMERS
    model_id: str = field(default_factory=get_vision_model_id)
    
    # ===== Generation Parameters =====
    max_new_tokens: int = 1024
    temperature: float = 0.7
    top_p: float = 0.9
    do_sample: bool = True
    
    # ===== Timeout and Performance =====
    timeout: int = 300  # seconds (5 minutes)
    generation_timeout_seconds: int = field(default_factory=get_generation_timeout_seconds)
    image_scale: float = 1.0  # Image scaling factor
    image_resolution: int = 100  # DPI for PDF page rendering
    
    # ===== Output Formatting =====
    response_format: ResponseFormat = ResponseFormat.MARKDOWN
    structured_output: bool = False  # Enforce JSON schema when True
    
    # ===== GPU Optimization (transformers only) =====
    gpu_memory_fraction: float = 0.9
    dtype: str = "auto"  # "auto", "float16", "bfloat16"
    device_map: str = "auto"
    trust_remote_code: bool = True
    use_fast_tokenizer: bool = False  # False for better accuracy
    
    # ===== Error Handling =====
    retry_count: int = 3
    retry_delay: float = 1.0  # seconds
    fallback_on_error: bool = True
    
    # ===== Logging =====
    verbose: bool = False
    log_responses: bool = False
    
    # ===== Advanced/Custom Parameters =====
    custom_params: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """Validate parameters after initialization"""
        # Convert string enum to enum if needed
        if isinstance(self.backend_type, str):
            self.backend_type = VLMBackendType[self.backend_type.upper()]
        if isinstance(self.response_format, str):
            self.response_format = ResponseFormat[self.response_format.upper()]
        
        # Validation
        if self.timeout < 60:
            raise ValueError("timeout must be >= 60 seconds for VLM operations")
        if self.generation_timeout_seconds < 1:
            raise ValueError("generation_timeout_seconds must be >= 1 second")
        if not 0 < self.temperature <= 2.0:
            raise ValueError("temperature must be in (0, 2.0]")
        if not 0 < self.top_p <= 1.0:
            raise ValueError("top_p must be in (0, 1.0]")
        if self.max_new_tokens < 1:
            raise ValueError("max_new_tokens must be >= 1")
        if self.image_resolution < 50:
            raise ValueError("image_resolution must be >= 50 DPI")
        if not 0 < self.gpu_memory_fraction <= 1.0:
            raise ValueError("gpu_memory_fraction must be in (0, 1.0]")
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (for serialization)"""
        data = asdict(self)
        # Convert enums to strings
        data['backend_type'] = self.backend_type.value
        data['response_format'] = self.response_format.value
        return data
    
    def to_json(self, path: Optional[str] = None) -> str:
        """
        Export to JSON string or file
        
        Args:
            path: Optional file path to save JSON
            
        Returns:
            JSON string
        """
        json_str = json.dumps(self.to_dict(), indent=2)
        if path:
            with open(path, 'w') as f:
                f.write(json_str)
        return json_str
    
    def to_yaml(self, path: Optional[str] = None) -> str:
        """
        Export to YAML string or file
        
        Args:
            path: Optional file path to save YAML
            
        Returns:
            YAML string
        """
        yaml_str = yaml.dump(self.to_dict(), default_flow_style=False)
        if path:
            with open(path, 'w') as f:
                f.write(yaml_str)
        return yaml_str
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'VLMOptions':
        """
        Create VLMOptions from dictionary
        
        Args:
            data: Configuration dictionary
            
        Returns:
            VLMOptions instance
        """
        return cls(**data)
    
    @classmethod
    def from_json(cls, path: str) -> 'VLMOptions':
        """
        Load VLMOptions from JSON file
        
        Args:
            path: Path to JSON configuration file
            
        Returns:
            VLMOptions instance
        """
        with open(path, 'r') as f:
            data = json.load(f)
        data.pop("model_id", None)
        return cls.from_dict(data)
    
    @classmethod
    def from_yaml(cls, path: str) -> 'VLMOptions':
        """
        Load VLMOptions from YAML file
        
        Args:
            path: Path to YAML configuration file
            
        Returns:
            VLMOptions instance
        """
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        data.pop("model_id", None)
        return cls.from_dict(data)
    
    @classmethod
    def get_default(cls, preset: str = "balanced") -> 'VLMOptions':
        """
        Get preset configurations
        
        Args:
            preset: One of "balanced", "fast", "quality", "low_memory"
            
        Returns:
            VLMOptions instance with preset values
        """
        presets = {
            "balanced": cls(
                max_new_tokens=1024,
                temperature=0.7,
                timeout=300,
                image_resolution=100
            ),
            "fast": cls(
                max_new_tokens=512,
                temperature=0.5,
                timeout=180,
                image_resolution=75,
                dtype="float16"
            ),
            "quality": cls(
                max_new_tokens=2048,
                temperature=0.3,
                timeout=600,
                image_resolution=150,
                dtype="auto"
            ),
            "low_memory": cls(
                max_new_tokens=512,
                temperature=0.7,
                timeout=300,
                image_resolution=75,
                gpu_memory_fraction=0.7,
                dtype="float16"
            )
        }
        
        if preset not in presets:
            raise ValueError(f"Unknown preset: {preset}. Choose from {list(presets.keys())}")
        
        return presets[preset]
    
    def get_generation_kwargs(self) -> Dict[str, Any]:
        """
        Get kwargs for model.generate() call
        
        Returns:
            Dictionary of generation parameters
        """
        return {
            'max_new_tokens': self.max_new_tokens,
            'temperature': self.temperature,
            'top_p': self.top_p,
            'do_sample': self.do_sample,
        }
    
    def get_model_kwargs(self) -> Dict[str, Any]:
        """
        Get kwargs for model loading
        
        Returns:
            Dictionary of model loading parameters
        """
        import torch

        required_cuda_index = ensure_gpu1_runtime(torch)
        resolved_device_map: Any = {"": required_cuda_index}

        return {
            'device_map': resolved_device_map,
            'torch_dtype': self.dtype,
            'trust_remote_code': self.trust_remote_code,
        }
    
    def get_processor_kwargs(self) -> Dict[str, Any]:
        """
        Get kwargs for processor loading
        
        Returns:
            Dictionary of processor parameters
        """
        return {
            'trust_remote_code': self.trust_remote_code,
            'use_fast': self.use_fast_tokenizer,
        }
    
    def __repr__(self) -> str:
        """String representation"""
        return (
            f"VLMOptions(\n"
            f"  model={self.model_id}\n"
            f"  backend={self.backend_type.value}\n"
            f"  timeout={self.timeout}s\n"
            f"  generation_timeout={self.generation_timeout_seconds}s\n"
            f"  max_tokens={self.max_new_tokens}\n"
            f"  temperature={self.temperature}\n"
            f"  response_format={self.response_format.value}\n"
            f")"
        )


# Example configuration templates
def create_example_configs(output_dir: str = "."):
    """Create example configuration files"""
    output_path = Path(output_dir)
    
    # Example 1: Default config
    default = VLMOptions.get_default("balanced")
    default.to_yaml(str(output_path / "vlm_config_default.yaml"))
    default.to_json(str(output_path / "vlm_config_default.json"))
    
    # Example 2: Production config
    production = VLMOptions(
        timeout=600,
        temperature=0.3,
        max_new_tokens=2048,
        response_format=ResponseFormat.JSON,
        structured_output=True,
        verbose=True,
        log_responses=True
    )
    production.to_yaml(str(output_path / "vlm_config_production.yaml"))
    
    print(f"✅ Created example configs in {output_dir}/")
    print(f"   - vlm_config_default.yaml")
    print(f"   - vlm_config_default.json")
    print(f"   - vlm_config_production.yaml")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="VLM Options Configuration Utility")
    parser.add_argument("--create-examples", action="store_true", help="Create example config files")
    parser.add_argument("--validate", type=str, help="Validate a config file")
    parser.add_argument("--show-preset", type=str, choices=["balanced", "fast", "quality", "low_memory"],
                        help="Show preset configuration")
    
    args = parser.parse_args()
    
    if args.create_examples:
        create_example_configs()
    
    elif args.validate:
        try:
            if args.validate.endswith('.yaml'):
                options = VLMOptions.from_yaml(args.validate)
            elif args.validate.endswith('.json'):
                options = VLMOptions.from_json(args.validate)
            else:
                print("❌ Config file must be .yaml or .json")
                exit(1)
            
            print("✅ Configuration is valid:")
            print(options)
        except Exception as e:
            print(f"❌ Configuration is invalid: {e}")
            exit(1)
    
    elif args.show_preset:
        options = VLMOptions.get_default(args.show_preset)
        print(f"Preset: {args.show_preset}")
        print("=" * 50)
        print(options)
        print("\nYAML:")
        print(options.to_yaml())
    
    else:
        parser.print_help()
