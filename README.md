# InferencePack

A unified, Docker-based inference stack for DGX A100 servers supporting **vLLM**, **SGLang**, and **TensorRT-LLM** with integrated **LangFuse** monitoring.

## Features

- **Multi-Engine Support**: Choose between vLLM, SGLang, or TensorRT-LLM via a single command
- **Automated Model Management**: Downloads and caches HuggingFace models with resume support
- **Native LangFuse Tracing**: Inference engines send OpenTelemetry traces directly to LangFuse — no proxy bottleneck
- **Local-only secure defaults**: Loopback port bindings, authenticated WebUI and explicit service secrets; see [SECURITY.md](SECURITY.md) before deployment
- **One-Command Deploy**: `./run.sh [vllm|sglang|tensorrtllm]` handles model checks and service startup

## Requirements

- Ubuntu 24.04 LTS
- NVIDIA DGX A100 (8x A100 80GB)
- **Docker Engine 28+** with Compose installed and running
- **NVIDIA Container Toolkit** configured (`docker info | grep nvidia`)
- NVIDIA drivers installed
- Internet access for Docker image pulls and model downloads
- HuggingFace token (for gated models)

> **Note**: `run.sh` no longer auto-installs Docker or NVIDIA Toolkit. Please ensure these are pre-installed on your bare-metal server.
>
> `run.sh` uses **[uv](https://docs.astral.sh/uv/)** (Astral's Python package manager) to install `huggingface-hub[cli]`. If `uv` is not found, it will be automatically installed to `~/.local/bin`.

## Quick Start

```bash
git clone https://github.com/JinwangMok/InferencePack.git
cd InferencePack

# NEW installations only: create a private configuration
python3 scripts/configure_env.py --init

# Follow SECURITY.md for local first-user setup, then run vLLM
./run.sh vllm

# Or run interactively to select engine
./run.sh
```

Existing installations must follow the [migration guide](SECURITY.md#existing-deployments-deliberate-migration) before using these defaults. Preserve data and existing encryption keys.

The `run.sh` script will:
1. Validate private configuration first, then verify Docker and prerequisites
2. Verify and download models specified in `selected-models.yaml`
3. Start LangFuse services
4. Start the chosen inference engine (with native OTEL tracing to LangFuse)

## Services

| Service | URL | Description |
|---------|-----|-------------|
| OpenAI API | `http://localhost:8000/v1` | Inference endpoint (direct engine access) |
| LangFuse UI | `http://localhost:3000` | LLM observability and tracing dashboard |
| OpenWebUI | `http://localhost:8080` | Chat UI for interacting with the model |

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

## Authentication, first users and secrets

Read [SECURITY.md](SECURITY.md) for new installation and existing-data migration.
The local UIs are at `http://localhost:3000` (Langfuse) and
`http://localhost:8080` (OpenWebUI). All published ports bind to `127.0.0.1`.

OpenWebUI authentication is enabled. Registrations are closed by default in both
UIs. Temporarily enable signup only for supervised local first-user setup, then
close it and verify the effective UI settings. No shared default account is
provided. Existing users and persisted configuration need migration review.

`VLLM_API_KEY` authenticates vLLM and SGLang clients, including OpenWebUI.
TensorRT-LLM's API stays local-only and needs an authenticated proxy for any
remote sharing; the WebUI's API key does not secure that backend.

Required secrets are generated independently by `scripts/configure_env.py --init`
for new installations. Keep `.env` private and backed up. To enable tracing, add
both Langfuse project keys to `.env` and re-run `./run.sh <engine>`. Startup derives
the trace authorization header without printing it. Recreate changed containers
rather than using `docker compose restart` for configuration updates.

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

The command below loads a local model. For HTTP serving benchmarks, configure
the client with the private API key without committing it or sharing shell logs.

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
├── docker-compose.vllm.yml         # vLLM + OpenWebUI
├── docker-compose.sglang.yml       # SGLang + OpenWebUI
├── docker-compose.tensorrtllm.yml  # TensorRT-LLM + OpenWebUI
├── selected-models.yaml            # Model registry
├── run.sh                          # Single entrypoint script
├── .env.example                    # Empty secret template (documentation)
├── SECURITY.md                     # Bootstrap, migration and security boundaries
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

If `uv` is not found:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

## License

MIT License
