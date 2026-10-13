# ONR Project

A Python-based autonomous underwater vehicle (AUV) control and navigation system for the ONR Scuba simulation environment.

## Overview

This project provides a modular framework for controlling an underwater drone (AUV) in a simulated environment. It features real-time state management, role-based AUV control (companion or scout), and participant data tracking for research purposes. The system monitors simulation output data and provides autonomous control capabilities for underwater missions.

## Project Structure

```
ONR_project/
├── main.py                          # Main application entry point
├── README.md                        # This file
├── requirements.txt                 # Python dependencies
├── .gitignore                       # Git ignore rules
│
├── modules/                         # Core application modules
│   ├── auv/                        # AUV control system
│   │   ├── __init__.py
│   │   ├── auv.py                  # Main AUV controller
│   │   ├── navigator/              # Navigation subsystem
│   │   │   ├── __init__.py
│   │   │   ├── navigator.py        # Base navigator interface
│   │   │   ├── autonomous_navigator.py  # Autonomous navigation logic
│   │   │   └── static_navigator/   # Pre-planned navigation paths
│   │   │       └── __init__.py
│   │   └── vision/                 # Computer vision subsystem
│   │       ├── __init__.py
│   │       └── yolo_cv.py          # YOLO-based object detection
│   │
│   └── state/                      # State management system
│       ├── __init__.py
│       ├── atomic_state.py         # Thread-safe state container
│       └── buffered_observer.py    # File watcher with buffered updates
│
├── models/                         # ML models (gitignored)
│   └── yolov8s-world.pt           # YOLO v8 world model
│
├── ONR_Scuba_Pilot/               # Simulation executable and runtime (gitignored)
│   ├── ONR Scuba_Data/            # Simulation data files
│   └── OutputData/                # Participant data output directory
│
├── participant_data/              # Collected participant data
│   ├── PID0/
│   ├── PID1/
│   └── PID2/
│
└── training_materials/            # Training resources
```

## Features

-   **Role-Based Control**: Supports "companion" and "scout" AUV roles
-   **Thread-Safe State Management**: Concurrent access to shared state using atomic operations
-   **Real-Time File Monitoring**: Watches and processes simulation output data
-   **Participant Tracking**: Organized data collection by participant ID
-   **YOLO-Based Vision**: Object detection and tracking capabilities
-   **Modular Architecture**: Independent, reusable subsystems

## Key Components

### AUV Module (`modules/auv/`)

The core AUV control system with integrated subsystems.

#### AUV Controller (`auv.py`)

Main AUV control logic that coordinates navigation and vision processing.

#### Navigator (`modules/auv/navigator/`)

-   **`navigator.py`**: Base navigation interface
-   **`autonomous_navigator.py`**: Autonomous navigation algorithms
-   **`static_navigator/`**: Pre-planned navigation paths

#### Vision (`modules/auv/vision/`)

-   **`yolo_cv.py`**: YOLO v8-based computer vision for object detection and tracking

### State Module (`modules/state/`)

Thread-safe state management system for concurrent operations:

-   **`atomic_state.py`**: Thread-safe atomic state container using locks for concurrent read/write access
-   **`buffered_observer.py`**: File watcher with buffered updates that monitors simulation output files

## Installation

### Prerequisites

-   Python 3.13+ (based on numpy requirement)
-   ONR Scuba simulation environment installed

### Setup

1. Clone the repository:

```bash
git clone <repository-url>
cd ONR_project
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Ensure the ONR Scuba Pilot simulation is installed in `ONR_Scuba_Pilot/`

### Key Dependencies

-   **OpenCV** (`opencv-python==4.12.0`): Computer vision and image processing
-   **NumPy** (`numpy==2.3.4`): Numerical operations
-   **Pandas**: Data manipulation and analysis
-   **Matplotlib** (`matplotlib==3.10.6`): Data visualization
-   **MSS**: Screen capture for simulation monitoring
-   **Pillow**: Image processing
-   **Ultralytics**: YOLOv8 implementation
-   Additional dependencies listed in `requirements.txt`

## Usage

### Basic Execution

Run the main application with required arguments:

```bash
python main.py --role <companion|scout> --pid <participant_id>
```

**Required Arguments:**

-   `--role`: Specify AUV role (`companion` or `scout`)
-   `--pid`: Participant ID number (integer)

**Example:**

```bash
python main.py --role companion --pid 0
```

### Application Flow

1. **Initialization**: Creates an `AtomicState` instance for thread-safe state management
2. **File Monitoring**: Sets up a `ManualObserver` to watch the participant data file
3. **Wait for Simulation**: Monitors for the creation of `ONR_Scuba_Pilot/OutputData/ParticipantData_PID_{pid}.json`
4. **Start Observer**: Begins processing simulation output data once the file is available

### State Management

The project uses a robust observer pattern with atomic state:

```python
from modules.state.atomic_state import AtomicState
from modules.state.buffered_observer import ManualObserver

# Create thread-safe state
state = AtomicState()

# Start file observer for participant data
filepath = "ONR_Scuba_Pilot/OutputData/ParticipantData_PID_0.json"
observer = ManualObserver(filepath=filepath, shared_state=state)
observer.start()
```

### Navigation

Access autonomous navigation functionality:

```python
from modules.auv.navigator.autonomous_navigator import AutonomousNavigator

# Initialize autonomous navigator
navigator = AutonomousNavigator()
```

### Vision Processing

Use YOLO-based vision:

```python
from modules.auv.vision import yolo_cv

# Process frames for object detection
results = yolo_cv.detect_objects(frame)
```

## Configuration

### Simulation Paths

-   **Executable**: `ONR_Scuba_Pilot/`
-   **Output Data**: `ONR_Scuba_Pilot/OutputData/ParticipantData_PID_{pid}.json`
-   **Participant Data**: `participant_data/PID{n}/`

### Models

YOLO model weights are stored in `models/` (gitignored):

-   `yolov8s-world.pt`: YOLOv8 world model for object detection

## Architecture

### State Management Pattern

The project implements an **observer pattern** with **atomic state** for thread-safe operations:

1. **`AtomicState`**: Provides thread-safe read/write operations using Python's `threading.Lock`
2. **`ManualObserver`**: Monitors file changes and updates shared state with buffered data to prevent race conditions

### Role-Based System

The main application (`main.py`) supports two AUV roles:

-   **Companion**: Follows and assists the diver
-   **Scout**: Explores and searches independently

Each role can be assigned to different participant IDs for data collection.

### Navigation Hierarchy

```
Navigator (Base Interface)
├── AutonomousNavigator (Real-time decision making)
└── StaticNavigator (Pre-planned paths)
```

### Threading Model

-   Main thread handles initialization and argument parsing
-   Observer thread monitors file changes asynchronously
-   Atomic state ensures thread-safe data access across all subsystems

## Development

### Code Structure

-   **Modular Design**: Each subsystem (`auv`, `state`) is independently developed
-   **Type Hints**: Extensive use of Python typing for better code clarity
-   **Thread Safety**: Atomic operations and locks for concurrent access
-   **File Monitoring**: Non-blocking file watchers for real-time data processing

### Adding New Features

1. Extend the appropriate module in `modules/`
2. Maintain thread-safety when accessing `AtomicState`
3. Use the observer pattern for new data sources
4. Document new navigation strategies in `modules/auv/navigator/`

### Testing

The project structure supports unit testing:

```bash
# Run tests (if test suite is implemented)
python -m pytest tests/
```

## Data Collection

Participant data is automatically organized by PID:

```
participant_data/
├── PID0/  # Participant 0 data
├── PID1/  # Participant 1 data
└── PID2/  # Participant 2 data
```

The simulation outputs data to `ONR_Scuba_Pilot/OutputData/ParticipantData_PID_{pid}.json`, which is monitored in real-time by the `ManualObserver`.

## Git Configuration

The `.gitignore` excludes:

-   Python cache files (`__pycache__/`, `*.pyc`)
-   Simulation runtime (`ONR_Scuba_Pilot/`)
-   ML models (`models/`)

## License

This project is developed for research purposes as part of the ONR (Office of Naval Research) initiative.

## Contributing

When contributing, please:

1. Maintain the modular structure
2. Add type hints to all functions
3. Use `AtomicState` for shared state
4. Ensure thread-safe operations with proper locking
5. Document new navigation strategies and vision algorithms
6. Follow the established observer pattern for file monitoring

## Contact

For questions or issues, please refer to the project documentation or contact the development team.

---

**Note**: This is an active research project. The simulation executable and ML models are excluded from version control and must be obtained separately.
