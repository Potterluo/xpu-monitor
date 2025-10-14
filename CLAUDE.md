# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a web-based NPU/GPU monitoring platform that supports remote monitoring of multiple Linux servers. It provides real-time monitoring of NPU/GPU temperature, power consumption, memory usage, and computational utilization through a Flask web application with WebSocket support.

## Architecture

- **Backend**: Flask-based web application (`app.py`) with Socket.IO for real-time updates
- **Frontend**: HTML templates with JavaScript WebSocket client (`templates/`, `static/`)
- **Configuration**: JSON-based server configuration (`config/servers.json`)
- **Remote Monitoring**: SSH-based remote command execution using paramiko

### Key Components

1. **Main Application** (`app.py`):
   - Flask routes for web interface and API endpoints
   - WebSocket handlers for real-time updates
   - SSH connection management for remote monitoring
   - Parsers for `npu-smi info` and `nvidia-smi` outputs

2. **Configuration Management**:
   - Server definitions in `config/servers.json`
   - Support for both local and remote servers
   - Authentication via password or SSH keys
   - Optional bastion host support

3. **Monitoring System**:
   - Background thread updating server status every 15 seconds
   - Real-time WebSocket updates to connected clients
   - Support for NPU (Huawei Ascend) and GPU (NVIDIA) devices

## Common Commands

### Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Run application (development mode)
python app.py

# Run application (production mode)
python run.py
```

### Starting the Application
```bash
# Development server (port 5000, debug enabled)
python app.py

# Production server (port 5090, includes system checks)
python run.py

# Using batch file (Windows)
start.bat
```

### Configuration
- Edit `config/servers.json` to add/remove servers
- Server types: "npu" or "gpu"
- Local servers: set `"local": true`
- Remote servers: configure authentication with `"auth"` object

## Device Support

### NPU Devices
- Command: `npu-smi info`
- Parser: `parse_npu_smi()` function
- Extracts: Temperature, power, AICore utilization, HBM memory usage

### GPU Devices
- Command: `nvidia-smi`
- Parser: `parse_nvidia_smi()` function
- Extracts: Temperature, power usage, memory usage, GPU utilization

## API Endpoints

- `GET /api/servers` - Get all server status
- `GET /api/servers/<host>` - Get specific server status
- `POST /api/refresh` - Manual refresh of all servers
- `GET /api/config` - Get server configuration
- `POST /api/config` - Update server configuration
- `POST /api/config/server` - Add new server
- `DELETE /api/config/server/<name>` - Delete server

## WebSocket Events

- `connect` - Client connection
- `initial_data` - Send current server status on connect
- `server_update` - Individual server status update
- `servers_refreshed` - Full server list refresh
- `request_servers` - Client requests server list refresh

## Configuration Schema

```json
{
  "servers": [
    {
      "name": "Server Name",
      "host": "192.168.1.100",
      "port": 22,
      "type": "npu|gpu",
      "local": false,
      "auth": {
        "type": "password|key",
        "username": "username",
        "password": "password",
        "key_file": "/path/to/key",
        "key_password": "key_password"
      },
      "bastion": {
        "host": "bastion.host",
        "port": 22,
        "auth": { ... }
      }
    }
  ]
}
```

## Testing Notes

- Application runs on `0.0.0.0:5000` (dev) or `0.0.0.0:5090` (prod)
- Debug mode can be enabled in `app.py` last line
- WebSocket connections tested via browser dev tools
- Server configuration changes trigger immediate status updates