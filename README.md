<div align="center">
  <h1>Kiro Agent Proxy 🚀</h1>
  <p>A robust local proxy bridging OpenAI-compatible editors with the native Kiro AWS Event Stream protocol.</p>

  <p>
    <a href="https://github.com/sionex-code/opencode-proxy-api/stargazers"><img src="https://img.shields.io/github/stars/sionex-code/opencode-proxy-api" alt="Stars Badge"/></a>
    <a href="https://github.com/sionex-code/opencode-proxy-api/network/members"><img src="https://img.shields.io/github/forks/sionex-code/opencode-proxy-api" alt="Forks Badge"/></a>
    <a href="https://github.com/sionex-code/opencode-proxy-api/pulls"><img src="https://img.shields.io/github/issues-pr/sionex-code/opencode-proxy-api" alt="Pull Requests Badge"/></a>
    <a href="https://github.com/sionex-code/opencode-proxy-api/issues"><img src="https://img.shields.io/github/issues/sionex-code/opencode-proxy-api" alt="Issues Badge"/></a>
    <a href="https://github.com/sionex-code/opencode-proxy-api/blob/main/LICENSE"><img src="https://img.shields.io/github/license/sionex-code/opencode-proxy-api" alt="License Badge"/></a>
  </p>
</div>

---

## 📖 Overview

The **Kiro Agent Proxy** enables advanced AI IDEs (like Opencode) that expect standard OpenAI-compatible API responses to communicate seamlessly with Kiro's backend infrastructure. 

It accomplishes this by translating standard JSON-based chat completions into AWS Binary Event Streams, injecting custom tool definitions, and converting the resulting streams back into OpenAI-compatible Server-Sent Events (SSE). 

Additionally, it features a **Web Dashboard** for managing multiple Kiro accounts, handling OAuth PKCE flows, dynamic proxy controlling, and automatic token refreshing.

![Dashboard Screenshot](dashboard.jpg)

## ✨ Features

- **Multi-Account Dashboard:** Easily manage and switch between different Kiro authenticated profiles.
- **Dynamic Active Switching:** The proxy automatically routes requests through whichever account is currently marked "Active" in the dashboard.
- **Auto-Refreshing Tokens:** Background monitoring of token lifespans. Automatically hits the `/refreshToken` endpoint when an active token is within 10 minutes of expiring.
- **Detailed Quota Tracking:** Real-time visibility into usage metrics, properly aggregating standard allocations and Free Trial limits.
- **Native Tool Translation:** Transparently maps generic OpenAI tool calls into the Kiro `toolSpec` schema.
- **Robust Process Lifecycle & PID Tracking:** Start, stop, and track the proxy subprocess directly from the dashboard. The system automatically scans network ports and process names to re-attach to running proxy instances if the dashboard is restarted.
- **Persistent Machine ID:** Generates a persistent, unique machine identifier saved in `machine_id.txt` to maintain consistent sessions with Kiro's backend.

## 📂 Project Structure

```text
.
├── start.bat             # Windows startup script to launch the dashboard (Double-click!)
├── auth_capture_v2.py    # Main Web Dashboard & Profile Manager (Run this!)
├── proxy.py              # FastAPI proxy server (Auto-managed by dashboard)
├── kiro_api.py           # Core AWS binary event stream parsing client
├── profiles.json         # Local database for OAuth tokens & limits (Auto-generated)
├── machine_id.txt        # Persistent machine identifier for backend sessions (Auto-generated)
├── tools.json            # Kiro-native tool definitions
├── opencode.json         # Example IDE connection config
├── requirements.txt      # Python dependencies
└── LICENSE               # MIT License
```

## 🚀 Usage Guide

### 1. Installation

Clone the repository and install the required dependencies:

```bash
git clone https://github.com/sionex-code/opencode-proxy-api.git
cd opencode-proxy-api
pip install -r requirements.txt
```

### 2. Start the Dashboard

You can start the dashboard in one of two ways:

**Windows:**
Double-click the `start.bat` script in the project directory.

**Command line:**
Run the main management script:
```bash
python auth_capture_v2.py
```

### 3. Add an Account
1. Open [http://localhost:3128](http://localhost:3128) in your browser.
2. Click **+ Add Account**.
3. Copy the provided authentication URL and open it in your preferred browser to log in via Kiro.
4. Your account will appear on the dashboard with its active token, refresh token, and accurate usage limits.

### 4. Start the Proxy
From the dashboard interface, click the green **Start Proxy** button. The proxy server will spin up on port `8000`.

### 5. Configure Your IDE
Configure your AI editor (like Opencode) to point to the local proxy. An exact copy-paste JSON configuration is provided at the bottom of the dashboard page. 

It will look something like this:
```json
{
  "provider": {
    "kiro": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Kiro Backend Proxy",
      "options": {
        "baseURL": "http://127.0.0.1:8000/v1",
        "apiKey": "dummy-key-not-used-by-proxy"
      },
      "models": {
        "claude-opus-4.8": {
          "name": "Claude Opus 4.8 (via Kiro)",
          "limit": {
            "context": 200000,
            "output": 65536
          }
        },
        "claude-sonnet-4.6": {
          "name": "Claude Sonnet 4.6 (via Kiro)",
          "limit": {
            "context": 200000,
            "output": 65536
          }
        }
      }
    }
  }
}
```

## ⚙️ Configuration & Environment Variables

You can customize the proxy's model mappings and exposure via environment variables when launching either `auth_capture_v2.py` or `proxy.py`:

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `OPENAI_MODEL_NAME` | `claude-sonnet-4.5` | The default model ID exposed to the IDE or OpenAI client. |
| `KIRO_MODEL_ID` | *Value of `OPENAI_MODEL_NAME`* | The actual Kiro backend model ID to map requests to. |
| `ADDITIONAL_OPENAI_MODELS` | *None* | A comma-separated list of extra model IDs to expose to the IDE (e.g., `claude-sonnet-4.6,claude-opus-4.8`). |

Model mapping supports both dot notation (e.g., `claude-sonnet-4.6`) and hyphen notation (e.g., `claude-sonnet-4-6`), which are automatically translated to Kiro backend identifiers.

## 📈 Star History

[![Star History Chart](https://api.star-history.com/svg?repos=sionex-code/opencode-proxy-api&type=Date)](https://star-history.com/#sionex-code/opencode-proxy-api&Date)

## 📄 License

This project is licensed under the [MIT License](LICENSE).
