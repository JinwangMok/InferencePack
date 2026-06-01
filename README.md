# InferencePack

A unified, Docker-based inference stack for DGX A100 servers supporting **vLLM**, **SGLang**, and **TensorRT-LLM** with integrated **LangFuse** monitoring.

## Features

- **Multi-Engine Support**: Choose between vLLM, SGLang, or TensorRT-LLM via a single command
- **Automated Model Management**: Downloads and caches HuggingFace models with resume support
- **LangFuse Integration**: Full LLM usage monitoring and tracing out of the box
- **Production-Ready**: Optimized defaults for A100 8x GPU configurations
- **One-Command Deploy**: `./run.sh [vllm|sglang|tensorrtllm]` handles Docker, NVIDIA runtime, model checks, and service startup

## Requirements

- Ubuntu 24.04 LTS
- NVIDIA DGX A100 (8x A100 80GB)
- NVIDIA drivers installed
- Internet access for Docker image pulls and model downloads
- HuggingFace token (for gated models)

## Quick Start

```bash
git clone https://github.com/JinwangMok/InferencePack.git
cd InferencePack

# Run with vLLM (recommended for EXAONE 3.5 32B)
./run.sh vllm

# Or run interactively to select engine
./run.sh
```

The `run.sh` script will:
1. Install Docker and NVIDIA Container Toolkit (if missing)
2. Verify and download models specified in `selected-models.yaml`
3. Start LangFuse + chosen inference engine + monitoring proxy

## Services

| Service | URL | Description |
|---------|-----|-------------|
| OpenAI API | `http://localhost:8000/v1` | Main inference endpoint (via monitoring proxy) |
| LangFuse UI | `http://localhost:3000` | LLM observability and tracing dashboard |
| vLLM Direct | `http://localhost:8001` | Direct vLLM access (bypass proxy) |
| SGLang Direct | `http://localhost:8002` | Direct SGLang access (bypass proxy) |
| TensorRT-LLM Direct | `http://localhost:8003` | Direct TensorRT-LLM access (bypass proxy) |

## Model Configuration

Edit `selected-models.yaml` to add or remove models:

```yaml
models:
  - name: "EXAONE-3.5-32B-Instruct"
    huggingface_repo: "LGAI-EXAONE/EXAONE-3.5-32B-Instruct"
    local_path: "/models/EXAONE-3.5-32B-Instruct"
    recommended_engine: "vllm"
```

Models are cached at `/models/<model-name>`. The download script skips existing valid models.

## LangFuse Setup

1. Visit `http://localhost:3000` after startup
2. Sign up with the pre-configured account:
   - Email: `netai@smartx.kr`
   - Password: `netai123`
3. Create a project and generate API keys
4. Add keys to `.env`:
   ```bash
   LANGFUSE_PUBLIC_KEY=pk-xxxxxxxx
   LANGFUSE_SECRET_KEY=sk-xxxxxxxx
   ```
5. Restart the monitoring proxy:
   ```bash
   docker compose --profile vllm restart monitoring-proxy
   ```

## Benchmarking

### vLLM Throughput Benchmark

```bash
# Using the monitoring proxy (LangFuse traces recorded)
vllm bench throughput \
  --model /models/EXAONE-3.5-32B-Instruct \
  --api-base http://localhost:8000/v1 \
  --trust-remote-code \
  --num-prompts 100 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 4

# Direct access (no LangFuse traces)
vllm bench throughput \
  --model /models/EXAONE-3.5-32B-Instruct \
  --api-base http://localhost:8001/v1 \
  --trust-remote-code \
  --num-prompts 100 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 4
```

## Engine-Specific Notes

### vLLM (Recommended)
- Best official support for EXAONE architecture
- Native `ExaoneForCausalLM` support
- OpenAI-compatible API with prefix caching and chunked prefill enabled

### SGLang
- Experimental support for EXAONE 32B (7.8B officially tested)
- Uses `--tp 8 --mem-fraction-static 0.80`
- Native OpenTelemetry tracing support

### TensorRT-LLM
- Supports EXAONE 3.5 via AutoDeploy/PyTorch backend
- Uses `trtllm-serve` with `--tp_size 4 --pp_size 1`
- Engine pre-build step not required for AutoDeploy path

## Project Structure

```
InferencePack/
├── docker-compose.yml          # Main compose with LangFuse + engines
├── selected-models.yaml        # Model registry and engine configs
├── run.sh                      # Single entrypoint script
├── .env.example                # Environment variable template
├── scripts/
│   └── download_models.py      # Model download/verification
└── monitoring-proxy/
    ├── Dockerfile              # Proxy container build
    ├── requirements.txt        # Python dependencies
    └── main.py                 # FastAPI proxy with LangFuse integration
```

## Troubleshooting

### Docker not found
`run.sh` automatically installs Docker. If it fails, run:
```bash
curl -fsSL https://get.docker.com | sh
```

### NVIDIA runtime not available
`run.sh` installs NVIDIA Container Toolkit. Verify with:
```bash
docker info | grep nvidia
```

### Out of Memory
Reduce `--gpu-memory-utilization` or `--max-model-len` in the compose file for your engine.

### Model download fails
Ensure `HF_TOKEN` is set in `.env` for gated models:
```bash
export HF_TOKEN=your_token_here
```

## License

MIT License
