# InferencePack

A unified, Docker-based inference stack for DGX A100 servers supporting **vLLM**, **SGLang**, and **TensorRT-LLM** with integrated **LangFuse** monitoring.

## Features

- **Multi-Engine Support**: Choose between vLLM, SGLang, or TensorRT-LLM via a single command
- **Automated Model Management**: Downloads and caches HuggingFace models with resume support
- **Native LangFuse Tracing**: Inference engines send OpenTelemetry traces directly to LangFuse — no proxy bottleneck
- **Production-Ready**: Optimized defaults for A100 8x GPU configurations
- **One-Command Deploy**: `./run.sh [vllm|sglang|tensorrtllm]` handles model checks and service startup

## Requirements

- Ubuntu 24.04 LTS
- NVIDIA DGX A100 (8x A100 80GB)
- **Docker** installed and running
- **NVIDIA Container Toolkit** configured (`docker info | grep nvidia`)
- NVIDIA drivers installed
- Internet access for Docker image pulls and model downloads
- HuggingFace token (for gated models)

> **Note**: `run.sh` no longer auto-installs Docker or NVIDIA Toolkit. Please ensure these are pre-installed on your bare-metal server.

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
1. Verify Docker and prerequisites
2. Verify and download models specified in `selected-models.yaml`
3. Start LangFuse services
4. Start the chosen inference engine (with native OTEL tracing to LangFuse)

## Services

| Service | URL | Description |
|---------|-----|-------------|
| OpenAI API | `http://localhost:8000/v1` | Inference endpoint (direct engine access) |
| LangFuse UI | `http://localhost:3000` | LLM observability and tracing dashboard |

> **Previous versions used a monitoring-proxy on port 8000. This has been removed.**
> Engines now expose port 8000 directly and send traces natively to LangFuse via OTLP.

## Architecture

```
User Request
     |
     v
+----------------------------------+
|  vLLM / SGLang / TensorRT-LLM  |  <- Port 8000, OpenAI-compatible API
|  (native OTEL tracing)           |     sends spans to LangFuse OTLP endpoint
+----------------------------------+
              |
              v
+----------------------------------+
|  LangFuse v3                     |  <- Port 3000
|  (web + worker + postgres        |
|   + redis + clickhouse + minio)  |
+----------------------------------+
```

## Model Configuration

Edit `selected-models.yaml` to add or remove models:

```yaml
models:
  - name: "EXAONE-3.5-32B-Instruct"
    huggingface_repo: "LGAI-EXAONE/EXAONE-3.5-32B-Instruct"
    local_path: "/models/EXAONE-3.5-32B-Instruct"
    recommended_engine: "vllm"
```

Models are downloaded to `/models/<model-name>`. Existing valid models are skipped automatically.

## LangFuse Setup

1. Visit `http://localhost:3000` after startup
2. Sign in with the pre-configured account from your `.env` file:
   - Email: `netai@smartx.kr`
   - Password: `netai123`
3. Create a project and generate API keys
4. Add keys to `.env` if you want to use LangFuse client SDKs elsewhere:
   ```bash
   LANGFUSE_PUBLIC_KEY=pk-xxxxxxxx
   LANGFUSE_SECRET_KEY=sk-xxxxxxxx
   ```
5. **Engine traces are sent automatically** via OTLP — no restart needed.

## Engine Configuration

Engine parameters (tensor-parallel size, GPU memory, etc.) are defined directly in their respective compose files:

| Engine | Compose File | Key Parameters |
|--------|-------------|----------------|
| vLLM | `docker-compose.vllm.yml` | `--tensor-parallel-size 8`, `--gpu-memory-utilization 0.92` |
| SGLang | `docker-compose.sglang.yml` | `--tp 8`, `--mem-fraction-static 0.80` |
| TensorRT-LLM | `docker-compose.tensorrtllm.yml` | `--tp_size 4`, `--pp_size 1` |

Modify these files directly to tune for your workload.

## Benchmarking

### vLLM Throughput Benchmark

```bash
vllm bench throughput \
  --model /models/EXAONE-3.5-32B-Instruct \
  --api-base http://localhost:8000/v1 \
  --trust-remote-code \
  --num-prompts 100 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 4
```

> The API endpoint is now direct engine access (port 8000). No proxy overhead.

## Engine-Specific Notes

### vLLM (Recommended)
- Best official support for EXAONE architecture
- Native `ExaoneForCausalLM` support
- OpenAI-compatible API with prefix caching and chunked prefill enabled
- Sends OTEL traces directly to LangFuse via `--otlp-traces-endpoint`

### SGLang
- Experimental support for EXAONE 32B (7.8B officially tested)
- Uses `--tp 8 --mem-fraction-static 0.80`
- Native OpenTelemetry tracing with `--enable-trace --otlp-traces-endpoint`

### TensorRT-LLM
- Supports EXAONE 3.5 via AutoDeploy/PyTorch backend
- Uses `trtllm-serve` with `--tp_size 4 --pp_size 1`
- Engine pre-build step not required for AutoDeploy path
- OTLP tracing via `--otlp_traces_endpoint`

## Project Structure

```
InferencePack/
├── docker-compose.langfuse.yml     # LangFuse v3 stack (run once)
├── docker-compose.vllm.yml         # vLLM inference engine
├── docker-compose.sglang.yml       # SGLang inference engine
├── docker-compose.tensorrtllm.yml  # TensorRT-LLM inference engine
├── selected-models.yaml            # Model registry
├── run.sh                          # Single entrypoint script
├── .env.example                    # Environment variable template
├── scripts/
│   └── download_models.py          # Model download/verification
└── README.md                       # This file
```

## Troubleshooting

### Docker not found
Install Docker manually:
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### NVIDIA runtime not available
Install NVIDIA Container Toolkit:
```bash
# https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
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
