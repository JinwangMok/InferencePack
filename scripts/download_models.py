#!/usr/bin/env python3
"""
Model download and verification script for InferencePack.
Reads selected-models.yaml and ensures all specified models exist locally.
Skips download if model is already present and valid.
"""

import os
import sys
import yaml
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional

try:
    from huggingface_hub import snapshot_download
    from huggingface_hub.utils import RepositoryNotFoundError, RevisionNotFoundError
except ImportError:
    print("[ERROR] huggingface_hub not installed. Run: pip install huggingface_hub PyYAML")
    sys.exit(1)


def get_cache_dir() -> Path:
    cache_dir = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    return Path(cache_dir)


def validate_model_directory(model_path: Path, required_files: List[str] = None) -> bool:
    if not model_path.exists() or not model_path.is_dir():
        return False
    
    if not any(model_path.iterdir()):
        return False
    
    required_files = required_files or ["config.json"]
    for req_file in required_files:
        if not (model_path / req_file).exists():
            print(f"  [WARN] Missing required file: {req_file}")
            return False
    
    return True


def download_model(
    repo_id: str,
    local_dir: str,
    token: Optional[str] = None,
    resume_download: bool = True
) -> bool:
    local_path = Path(local_dir)
    local_path.mkdir(parents=True, exist_ok=True)
    
    print(f"  [INFO] Downloading {repo_id} -> {local_dir}")
    print(f"  [INFO] This may take a while depending on model size...")
    
    try:
        snapshot_download(
            repo_id=repo_id,
            local_dir=local_dir,
            local_dir_use_symlinks=False,
            resume_download=resume_download,
            token=token,
            max_workers=8,
        )
        print(f"  [SUCCESS] Download complete: {repo_id}")
        return True
    except RepositoryNotFoundError:
        print(f"  [ERROR] Repository not found: {repo_id}")
        return False
    except RevisionNotFoundError:
        print(f"  [ERROR] Revision not found for: {repo_id}")
        return False
    except Exception as e:
        print(f"  [ERROR] Download failed: {e}")
        return False


def load_selected_models(config_path: str) -> List[Dict[str, Any]]:
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    return config.get('models', [])


def get_hf_token() -> Optional[str]:
    return os.environ.get('HF_TOKEN') or os.environ.get('HUGGINGFACE_TOKEN')


def main():
    parser = argparse.ArgumentParser(
        description="Download and verify models specified in selected-models.yaml"
    )
    parser.add_argument(
        "--config",
        default="selected-models.yaml",
        help="Path to selected-models.yaml"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Download only a specific model by name"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if model exists"
    )
    parser.add_argument(
        "--token",
        default=None,
        help="HuggingFace access token"
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check existence, do not download"
    )
    args = parser.parse_args()
    
    config_path = Path(args.config)
    if not config_path.is_absolute():
        script_dir = Path(__file__).parent.parent
        config_path = script_dir / args.config
    
    if not config_path.exists():
        print(f"[ERROR] Config file not found: {config_path}")
        sys.exit(1)
    
    print(f"[INFO] Loading model configuration from: {config_path}")
    models = load_selected_models(str(config_path))
    
    if not models:
        print("[WARN] No models found in configuration.")
        sys.exit(0)
    
    token = args.token or get_hf_token()
    
    if args.model:
        models = [m for m in models if m['name'] == args.model or m['huggingface_repo'] == args.model]
        if not models:
            print(f"[ERROR] Model '{args.model}' not found in configuration.")
            sys.exit(1)
    
    all_ok = True
    
    for model in models:
        name = model['name']
        repo = model['huggingface_repo']
        local_path = model['local_path']
        
        print(f"\n[CHECK] Model: {name}")
        print(f"  Repository: {repo}")
        print(f"  Local path: {local_path}")
        
        exists = validate_model_directory(Path(local_path))
        
        if exists and not args.force:
            print(f"  [OK] Model already exists at {local_path}")
            continue
        
        if args.check_only:
            print(f"  [MISSING] Model not found at {local_path}")
            all_ok = False
            continue
        
        if args.force and exists:
            print(f"  [FORCE] Re-downloading model...")
        
        success = download_model(repo, local_path, token=token, resume_download=True)
        if not success:
            all_ok = False
    
    print("\n" + "="*60)
    if all_ok:
        print("[SUCCESS] All models are ready.")
        sys.exit(0)
    else:
        print("[FAILED] Some models are missing or failed to download.")
        sys.exit(1)


if __name__ == "__main__":
    main()
