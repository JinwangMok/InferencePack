#!/usr/bin/env python3
import os
import sys
import yaml
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional


def ensure_huggingface_cli():
    if subprocess.run(["huggingface-cli", "--version"], capture_output=True).returncode == 0:
        return
    print("[INFO] Installing huggingface-hub via uv...")
    subprocess.check_call(["uv", "tool", "install", "huggingface-hub[cli]"])


def validate_model_directory(model_path: Path) -> bool:
    if not model_path.exists() or not model_path.is_dir():
        return False
    if not any(model_path.iterdir()):
        return False
    return (model_path / "config.json").exists()


def download_model(repo_id: str, local_dir: str, token: Optional[str] = None) -> bool:
    local_path = Path(local_dir)
    local_path.mkdir(parents=True, exist_ok=True)

    cmd = [
        "huggingface-cli", "download",
        repo_id,
        "--local-dir", local_dir,
        "--local-dir-use-symlinks", "False",
        "--resume-download",
    ]
    if token:
        cmd.extend(["--token", token])

    print(f"  [INFO] Downloading {repo_id} -> {local_dir}")
    try:
        subprocess.check_call(cmd)
        print(f"  [SUCCESS] Download complete: {repo_id}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"  [ERROR] Download failed: {e}")
        return False


def load_selected_models(config_path: str) -> List[Dict[str, Any]]:
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config.get("models", [])


def get_hf_token() -> Optional[str]:
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")


def main():
    parser = argparse.ArgumentParser(description="Download and verify models from selected-models.yaml")
    parser.add_argument("--config", default="selected-models.yaml", help="Path to config")
    parser.add_argument("--model", default=None, help="Download only specific model")
    parser.add_argument("--force", action="store_true", help="Force re-download")
    parser.add_argument("--token", default=None, help="HF token")
    parser.add_argument("--check-only", action="store_true", help="Only check, do not download")
    args = parser.parse_args()

    ensure_huggingface_cli()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        script_dir = Path(__file__).parent.parent
        config_path = script_dir / args.config

    if not config_path.exists():
        print(f"[ERROR] Config not found: {config_path}")
        sys.exit(1)

    models = load_selected_models(str(config_path))
    if not models:
        print("[WARN] No models found.")
        sys.exit(0)

    token = args.token or get_hf_token()

    if args.model:
        models = [m for m in models if m["name"] == args.model or m.get("huggingface_repo") == args.model]
        if not models:
            print(f"[ERROR] Model '{args.model}' not found.")
            sys.exit(1)

    all_ok = True
    for model in models:
        name = model["name"]
        repo = model.get("huggingface_repo", "")
        local_path = model.get("local_path", "")

        print(f"\n[CHECK] Model: {name}")
        print(f"  Repository: {repo}")
        print(f"  Local path: {local_path}")

        exists = validate_model_directory(Path(local_path))

        if exists and not args.force:
            print(f"  [OK] Model already exists")
            continue

        if args.check_only:
            print(f"  [MISSING] Model not found")
            all_ok = False
            continue

        success = download_model(repo, local_path, token=token)
        if not success:
            all_ok = False

    print("\n" + "=" * 60)
    if all_ok:
        print("[SUCCESS] All models are ready.")
        sys.exit(0)
    else:
        print("[FAILED] Some models are missing or failed to download.")
        sys.exit(1)


if __name__ == "__main__":
    main()
