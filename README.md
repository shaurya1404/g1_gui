# G1 GR00T Control GUI

Desktop application for initializing and managing the Unitree G1 humanoid robot's locomotion (WBC) and teleoperation (XR) systems from a single interface.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

```bash
python main.py
```

## Layout

| Area | Purpose |
|---|---|
| **Preflight Checks** (left panel) | Verifies network routing, robot reachability, and CycloneDDS topics before launch. One-click route fix if the USB adapter is interfering. |
| **Deployment Mode** (left panel) | Choose *WBC Only*, *Teleop Only*, or *Full Stack*, then hit **Launch Mode** to start the relevant processes in order. |
| **Process Cards** (right panel) | One card per subprocess (Mixer → WBC → Hand Driver → Teleop). Each has an editable command field, Start/Stop buttons, a live status badge, and a scrolling terminal output pane. Start buttons are greyed out until dependencies are running. |
| **Bottom Bar** | Stop All / Clear All terminals. |

## Configuration

All paths, IPs, environment activation commands, and process definitions live in `config.yaml`. Edit that file instead of touching Python code when paths change or new flags are needed.

## Files

```
g1_control_gui/
├── main.py              # Entry point — PyQt5 main window
├── config.yaml          # Paths, IPs, commands, modes
├── preflight.py         # Network & DDS preflight checks
├── process_manager.py   # Subprocess lifecycle + stdout streaming
├── requirements.txt     # Python dependencies
└── README.md            # This file
```
