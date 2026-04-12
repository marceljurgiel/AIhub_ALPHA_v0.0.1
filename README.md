<div align="center">

# AIHub 🤖

**Your all-in-one local AI management platform.**

AIHub is a unified interface for managing, browsing, and chatting with local and API-based AI models. It provides hardware-aware model selection, persistent memory, and a tool-calling agentic system.

[![Python 3.9+](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

## Features

### Hardware Scanner
Automatically detects your system hardware and recommends models that fit:
- **GPU Detection**: NVIDIA (nvidia-smi, GPUtil), AMD (rocm-smi, lspci), Intel, Windows (WMI)
- **CPU Info**: Model, physical/logical cores, clock speed
- **RAM & Disk**: Total, available, usage percentage
- **VRAM-based filtering**: Models ranked by best-fit for your hardware
- **Inference speed estimator**: Heuristic tokens/sec based on detected VRAM

### Model Browser & Registry
- **55+ models** in built-in registry (chat, code, reasoning models)
- **Live Ollama integration**: Shows locally installed models
- **HuggingFace browsing**: Fetch and browse remote models
- **Hardware-aware sorting**: Installed models first, then sorted by VRAM fit
- **Capability badges**: Tool Calling, Code, Reasoning, Multilingual, etc.
- **Category filters**: Small / Medium / Large / XLarge

### Interactive Chat
- **CLI chat**: Quick chat sessions from command line
- **Streaming responses**: Real-time token-by-token output
- **Configurable context**: Adjustable context window (num_ctx)
- **Temperature control**: Adjust model creativity

### Memory System
- **Per-model memory**: Stores key facts in `~/.aihub/memory/<model>.md`
- **Global memory**: Shared across all models in `~/.aihub/memory/global.md`
- **Auto-extraction**: Automatically extracts facts from conversations
- **System prompt injection**: Memory injected as context for each session

### Tool-Calling Agentic System
AIHub provides 6 built-in tools for agentic workflows:
- **Terminal**: Execute shell commands (with safety warnings)
- **File Operations**: Read, write, list files
- **Web Search**: Search the web via DuckDuckGo (no API key needed)
- **File Search**: Glob and grep search across directories

Tools work with Ollama models that support function calling (e.g., llama3.2:3b, qwen2.5:14b).

### History Management
- **Persistent sessions**: Save and resume chat sessions
- **Per-model history**: Organized by model name
- **Configurable limits**: Max saved sessions per model

### Multi-Platform Support
- **Linux**: Full support with all GPU detection methods
- **Windows**: WMI-based GPU detection
- **Cross-platform**: Portable config at `~/.aihub/config.yaml`

---

## Installation

### Linux Quick Install

```bash
git clone https://github.com/marceljurgiel/AIhub_ALPHA_v0.0.1.git
cd AIhub_ALPHA_v0.0.1
./install.sh
```

The installer will:
1. Detect your Linux distribution
2. Install Ollama (if not present)
3. Install Python dependencies
4. Install AIHub system-wide

### Linux Manual Install

```bash
# Clone the repository
git clone https://github.com/marceljurgiel/AIhub_ALPHA_v0.0.1.git
cd AIhub_ALPHA_v0.0.1

# Create virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install AIHub
pip install -e .
```

### Windows Installation

#### Prerequisites
1. **Python 3.9+** - Download from https://www.python.org/downloads/
2. **Ollama for Windows** - Download from https://ollama.com/download/windows

#### Steps

```powershell
# Clone the repository
git clone https://github.com/marceljurgiel/AIhub_ALPHA_v0.0.1.git
cd AIhub_ALPHA_v0.0.1

# Create virtual environment
python -m venv venv
venv\Scripts\Activate

# Install dependencies
pip install -r requirements.txt

# Install AIHub
pip install -e .
```

#### Running on Windows

```powershell
# Activate virtual environment
venv\Scripts\Activate

# Run AIHub
aihub
```

Or install globally:

```powershell
# Install globally
pip install -r requirements.txt
pip install -e .

# Run from anywhere
aihub
```

---

## Running AIHub

After installation, simply run:

```bash
aihub
```

### Available Commands

| Command | Description |
|---------|-------------|
| `aihub` | Launch main menu |
| `aihub chat` | Start quick chat session |
| `aihub models-list` | List all available models |
| `aihub models-download` | Download a model via Ollama |
| `aihub hardware-scan` | Run hardware diagnostics |
| `aihub history` | Browse saved chat sessions |
| `aihub config` | Show current configuration |

---

## Configuration

AIHub stores config at `~/.aihub/config.yaml`:

```yaml
# API Settings
ollama_api_url: http://localhost:11434
openai_api_key: your-key-here
anthropic_api_key: your-key-here

# Model Settings
default_chat_model: llama3.2:3b
default_context_length: 2048
models_registry_path: /path/to/models_registry.json

# Tool Settings
tools_enabled: true
tool_timeout_seconds: 60

# Memory Settings
global_memory_enabled: false

# History
max_history_sessions: 50
```

### Data Directories

| Directory | Path |
|-----------|------|
| Config | `~/.aihub/config.yaml` |
| Memory | `~/.aihub/memory/` |
| History | `~/.aihub/history/` |

---

## Model Registry

AIHub includes a built-in registry with 55+ models across categories:

### Small Models (< 4GB VRAM)
- `llama3.2:1b` - Tiny, ultra-fast, 128k context
- `llama3.2:3b` - Compact with tool calling
- `qwen2.5:3b` - Code-capable, fast

### Medium Models (4-8GB VRAM)
- `llama3.1:8b` - General purpose, tool calling
- `qwen2.5:7b` - Code, fast
- `mistral:7b` - Multilingual

### Large Models (8GB+ VRAM)
- `llama3.1:70b` - Full-size, reasoning
- `qwen2.5:14b` - Code, agentic
- `deepseek-r1:7b` - Reasoning model

---

## Tool Calling Usage

To use tools (web search, terminal, file ops), select a model with tool calling capability:

1. Start a chat session with a model that has tool calling capability
2. Ask questions requiring external data

Example:
```
You: What's the latest Python version?
[Model detects need for web search, calls search_web tool]
[Results fed back to model]
Model: The latest Python version is 3.13.0 (released October 2024)
```

---

## Development

### Project Structure

```
aihub/
├── aihub/
│   ├── cli.py          # Main CLI entrypoint
│   ├── config.py       # Configuration loading
│   ├── hardware.py     # Hardware detection
│   ├── memory.py       # Memory system
│   ├── chat.py         # Chat session logic
│   ├── tui.py          # Textual TUI (reserved for future)
│   ├── ollama_client.py
│   ├── hf_client.py
│   ├── models.py       # Model registry utilities
│   ├── history.py      # Session management
│   └── tools/          # Tool-calling system
│       ├── terminal.py
│       ├── file_ops.py
│       ├── web_search.py
│       └── file_search.py
├── models_registry.json
├── requirements.txt
├── install.sh
└── pyproject.toml
```

### Running Tests

```bash
pytest tests/
```

---

## License

MIT License - See [LICENSE](LICENSE) for details.

---

## Acknowledgments

- [Ollama](https://ollama.com/) - Local AI runtime
- [Questionary](https://questionary.readthedocs.io/) - CLI prompts
- [Rich](https://rich.readthedocs.io/) - Terminal formatting
