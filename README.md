# AVA — Autonomous Virtual Architecture

> **AI-powered HVAC control through a physics-based Building Digital Twin**

AVA is an AI-powered building intelligence and HVAC control system that allows building operators to interact with a building using natural language.

Instead of manually monitoring rooms, interpreting sensor data, and adjusting HVAC settings, an operator can simply say:

> **"Room 203 is cold."**

AVA interprets the request, understands the current building state, determines an appropriate HVAC action, applies it through the HVAC control layer, simulates the resulting physical response, and verifies whether comfort improved.

---

## The Problem

Modern buildings generate large amounts of environmental and HVAC data:

- Room temperature
- Humidity
- Occupancy
- HVAC supply temperature
- Fan speed
- Zone airflow
- Dampers
- Thermal comfort
- Weather conditions

However, building operators still have to manually interpret this information and translate human complaints into HVAC actions.

For example:

> "The people on the third floor are too hot."

requires understanding:

1. Which rooms are affected?
2. How many occupants are present?
3. What are the current environmental conditions?
4. Which HVAC controls affect those rooms?
5. What adjustment should be made?
6. Did the adjustment actually improve comfort?

AVA automates this decision loop.

---

# Solution

AVA acts as an intelligent building control layer between human instructions and HVAC infrastructure.

The system combines:

- **LLM-based reasoning**
- **Building state awareness**
- **Natural-language occupant feedback**
- **Physics-based thermal simulation**
- **HVAC control**
- **PMV/PPD comfort modelling**
- **Automatic verification**
- **Autonomous environmental changes**
- **Auditability and action analysis**

The goal is not simply to generate an answer.

AVA follows:

> **Understand → Decide → Control → Simulate → Verify**

---

# System Architecture

```text
                         ┌──────────────────────┐
                         │      OPERATOR        │
                         │                      │
                         │ "Room 203 is cold"   │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │    AVA ASSISTANT     │
                         │                      │
                         │ Natural Language     │
                         │ Understanding        │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │   NEMOTRON REASONING │
                         │                      │
                         │ Context + Building   │
                         │ State + Feedback     │
                         │        ↓             │
                         │ Control Decision     │
                         └──────────┬───────────┘
                                    │
                                    ▼
                    ┌──────────────────────────────┐
                    │     SAFETY / CONTROL LAYER   │
                    │                              │
                    │ Validate capabilities        │
                    │ Bound control values         │
                    │ Select target zone           │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │       HVAC ADAPTER           │
                    │                              │
                    │ Supply Temperature           │
                    │ Fan Speed                    │
                    │ Zone Damper / Airflow        │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
              ┌─────────────────────────────────────────┐
              │          BUILDING DIGITAL TWIN          │
              │                                         │
              │  Rooms                                  │
              │  Occupants                              │
              │  Thermal Dynamics                       │
              │  HVAC                                   │
              │  Weather                                 │
              │  Sensors                                 │
              └──────────────────┬──────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────────┐
                    │   THERMAL COMFORT MODEL      │
                    │                              │
                    │ PMV / PPD                    │
                    │ Room Comfort                 │
                    │ Building Comfort             │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │       VERIFICATION            │
                    │                              │
                    │ Before → After               │
                    │ Temperature                  │
                    │ HVAC Controls                │
                    │ PMV                          │
                    │ Building Comfort             │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │       ACTION ANALYSIS        │
                    │                              │
                    │ ✓ HVAC adjustment applied    │
                    │ ✓ Building simulated         │
                    │ ✓ Comfort verified            │
                    └──────────────────────────────┘
```

---

# Core Architecture

AVA is divided into several logical layers.

## 1. AVA Assistant

The Assistant is the human-facing interface.

Users can ask questions or provide feedback such as:

```text
Room 203 is cold
Room 101 is too hot
The third floor is uncomfortable
What's the HVAC status?
How comfortable is the building?
```

AVA distinguishes between:

- Information requests
- Occupant comfort feedback
- HVAC control requests

The user does not need to understand HVAC terminology.

---

## 2. AI Reasoning Layer

AVA uses **NVIDIA Nemotron** through an OpenAI-compatible API when configured.

The model receives relevant building context and determines an appropriate response/action.

The LLM is used for reasoning rather than directly controlling arbitrary equipment.

The resulting action is passed through bounded control logic before being applied.

This separates:

```text
AI reasoning
     ↓
Control validation
     ↓
HVAC execution
```

rather than allowing the LLM to directly manipulate the simulation.

---

## 3. Building Context & Capability Awareness

Buildings are not assumed to have identical equipment.

Before performing a control action, AVA considers the building's available:

- Rooms
- Zones
- Sensors
- HVAC controls
- Environmental measurements
- Building capabilities

This allows the architecture to support different building configurations.

---

# 4. HVAC Control Layer

AVA uses an HVAC adapter architecture.

For the current demonstration, the adapter connects AVA to the simulated HVAC system.

```text
AVA
 │
 ▼
HVAC Adapter
 │
 ├── Supply Temperature
 ├── Fan Speed
 ├── Zone Damper
 └── Airflow
 │
 ▼
Digital Twin
```

The current demo therefore demonstrates **real control of a simulated HVAC system** rather than physical building equipment.

The adapter architecture is designed so that future implementations can connect to real building systems such as BACnet or vendor APIs.

---

# 5. Building Digital Twin

The Digital Twin represents the building and its changing physical state.

It models:

- Buildings
- Floors
- Rooms
- Occupants
- Temperature
- Humidity
- HVAC equipment
- Airflow
- Weather
- Thermal behaviour
- Occupant comfort

The Digital Twin continuously evolves rather than simply displaying static values.

---

# 6. Occupant Model

Occupants are simulated participants inside the building.

They contribute to the building environment through:

- Occupancy
- Heat generation
- Comfort feedback
- Room-level comfort conditions

The current demonstration uses simulated occupants to provide realistic building conditions.

Occupants do **not** directly control the HVAC.

The architecture separates:

```text
Occupants → Environmental / comfort feedback

Operator → Building control requests

AVA → HVAC decisions and control
```

---

# 7. Thermal Comfort

AVA evaluates thermal comfort using PMV/PPD-based modelling.

The system can calculate:

- Individual occupant comfort
- Room comfort
- Building-level comfort

This allows AVA to verify whether an HVAC action actually produced a meaningful improvement.

For example:

```text
Before

Room Temperature: 19.8°C
PMV:              -1.4

        ↓ AVA HVAC action

After

Room Temperature: 21.1°C
PMV:              -0.4
```

The values are derived from the Digital Twin state rather than being hardcoded into the UI.

---

# 8. Closed-Loop HVAC Control

AVA does not stop after deciding on an action.

The control loop is:

```text
User Feedback
      ↓
AI Reasoning
      ↓
HVAC Action
      ↓
Digital Twin Simulation
      ↓
Comfort Recalculation
      ↓
Verification
      ↓
Correction if Necessary
```

This makes AVA a closed-loop control system rather than an LLM chatbot.

If the first adjustment does not sufficiently improve comfort, AVA can perform a bounded correction.

---

# Action Analysis

After an HVAC action, AVA exposes a compact analysis showing what actually changed.

Example:

```text
ACTION ANALYSIS

Room Temperature
19.8°C  → 21.1°C     +1.3°C

Supply Temperature
16.0°C  → 18.0°C     +2.0°C

Fan Speed
45%     → 52%       +7%

Zone Airflow
0.42    → 0.48      +0.06

Occupant PMV
-1.4    → -0.4      +1.0

Building Comfort
72%     → 79%       +7%

✓ HVAC adjustment applied
✓ Building simulated
✓ Comfort verified
```

The purpose is to make the AI's action **observable and auditable**.

---

# Autonomous Building Environment

The building environment can also evolve independently of the operator.

The simulation includes changing:

- Weather
- Temperature
- Humidity
- Occupancy
- Environmental conditions

For the Custom Building, weather can transition gradually between conditions.

Example:

```text
Weather shifting:
Sunny → Rain

Outdoor:
28.4°C
84% humidity
```

This demonstrates that the building is not simply reacting to a single static input.

The environment itself changes over time, requiring AVA to continuously operate against changing conditions.

---

# Demo Building vs Custom Building

AVA separates the demonstration environment from the customizable building.

```text
                 AVA PLATFORM
                      │
          ┌───────────┴───────────┐
          │                       │
          ▼                       ▼
   DEMO BUILDING            CUSTOM BUILDING
          │                       │
          │                       │
   Fixed simulation         User-defined state
          │                       │
          │                       ▼
          │                AVA Assistant
          │                       │
          │                       ▼
          │                Live Building
          │                       │
          └────── isolated ───────┘
```

The Demo Building provides a predictable environment for demonstration.

The Custom Building is connected to the Assistant and Live Building Overview.

This prevents demonstration state from accidentally affecting the user's custom building.

---

# Technology Stack

## AI

- **NVIDIA Nemotron**
- OpenAI-compatible inference API
- LLM-based reasoning
- Natural-language HVAC interaction

## Backend

- **Python**
- **FastAPI**
- REST API architecture
- Modular service layers

## Frontend

- **HTML**
- **CSS**
- **JavaScript**
- Responsive dashboard UI
- Interactive AVA Assistant

## Simulation

- Physics-inspired Building Digital Twin
- Thermal dynamics
- HVAC simulation
- Occupant modelling
- Weather simulation

## Thermal Comfort

- **pythermalcomfort**
- PMV / PPD calculations

## Data / State

- **SQLite**
- Runtime state persistence
- Event / audit history

## Deployment

- **Vercel**
- Python serverless deployment
- Production web application

---

# Project Structure

```text
AVA/
│
├── app/
│   ├── routes.py
│   │
│   ├── simulation/
│   │   ├── ...
│   │
│   ├── agents/
│   │   ├── ...
│   │
│   ├── optimizer/
│   │   └── hvac_optimizer.py
│   │
│   ├── storage.py
│   │
│   ├── static/
│   │   ├── dashboard.js
│   │   ├── custom_building.js
│   │   ├── tutorial.js
│   │   └── style.css
│   │
│   └── templates/
│       └── ...
│
├── requirements.txt
├── pyproject.toml
├── .python-version
└── README.md
```

---

# Important API Flow

### Dashboard

```text
GET /api/dashboard
```

Returns current building and HVAC state.

### AVA Assistant

```text
POST /api/dashboard/message
```

Processes natural-language requests.

Example:

```json
{
  "message": "Room 203 is cold"
}
```

### Custom Building

```text
GET /api/custom-building
```

Returns the current custom building state.

### Advance Digital Twin

```text
POST /api/custom-building/tick
```

Advances the simulated building environment.

### HVAC Integration

```text
GET /api/hvac/integration
```

Returns HVAC integration information.

---

# Example End-to-End Interaction

### User

```text
Room 203 is cold.
```

### AVA

1. Identifies the target room.
2. Reads current room/building conditions.
3. Determines the relevant HVAC controls.
4. Uses AI reasoning to determine an adjustment.
5. Applies bounded HVAC control values.
6. Advances the Digital Twin.
7. Recalculates thermal comfort.
8. Verifies the result.
9. Displays the action analysis.

```text
User
  │
  ▼
"Room 203 is cold"
  │
  ▼
AVA
  │
  ▼
Building Context
  │
  ▼
Nemotron Reasoning
  │
  ▼
HVAC Control
  │
  ▼
Digital Twin
  │
  ▼
PMV / Comfort
  │
  ▼
Verification
  │
  ▼
Action Analysis
```

---

# Safety & Control Boundaries

The LLM is not given unrestricted access to HVAC controls.

AVA uses bounded control logic to:

- Validate the target
- Validate available capabilities
- Constrain control values
- Prevent arbitrary equipment commands
- Verify the result after execution

This creates a separation between:

```text
Reasoning
    ↓
Validation
    ↓
Execution
```

The design is intended to make AI-assisted building control more predictable and auditable.

---

# Performance

The application was optimized for interactive demonstrations.

Key considerations include:

- Avoiding redundant LLM calls
- Fast local identification of obvious occupant feedback
- Bounded simulation verification
- Deterministic HVAC control search where required
- Lightweight browser polling
- Separation of expensive operations from the interactive path

The objective is to keep the AI control loop responsive while retaining actual simulation and verification.

---

# Why AVA Is Different

Traditional building dashboards primarily show information:

```text
Temperature: 21°C
Humidity: 52%
Fan: 48%
```

AVA adds a decision and control layer:

```text
Human feedback
      ↓
AI understands the problem
      ↓
AI determines an action
      ↓
HVAC changes
      ↓
Building responds
      ↓
Comfort is verified
```

This moves the interface from:

> **Monitoring a building**

to:

> **Interacting with a building through an intelligent control system.**

---

# Current Scope

The current implementation demonstrates AVA using a simulated building environment.

The HVAC layer controls simulated equipment through the Digital Twin.

The architecture is designed around an adapter boundary so that a future deployment can replace the simulator with real building infrastructure.

Possible future integrations include:

- BACnet
- Building Management Systems
- Vendor HVAC APIs
- Real-time IoT sensors
- Real building occupancy systems
- Production-grade safety and authorization layers

---

# Running Locally

## 1. Clone the repository

```bash
git clone <repository-url>
cd AVA
```

## 2. Create a virtual environment

```bash
python -m venv .venv
```

### Windows

```bash
.venv\Scripts\activate
```

### Linux / macOS

```bash
source .venv/bin/activate
```

## 3. Install dependencies

```bash
pip install -r requirements.txt
```

## 4. Configure the AI model

Set the required Nemotron / NVIDIA inference environment variables.

The application can also operate using its deterministic fallback behaviour when an external model is unavailable.

## 5. Start the application

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000
```

---

# Demonstration

A simple demonstration flow:

### 1. Open AVA

Start on the AVA Assistant dashboard.

### 2. Ask for building information

```text
What's the HVAC status?
```

### 3. Provide an occupant complaint

```text
Room 203 is cold.
```

### 4. Observe the AI decision

AVA determines the appropriate HVAC adjustment.

### 5. Observe the Digital Twin

The building state changes as the simulated HVAC system responds.

### 6. Inspect Action Analysis

Compare:

```text
Before → After
```

for temperature, HVAC controls, PMV, and building comfort.

### 7. Observe autonomous environment changes

Weather and building conditions continue to evolve independently.

---

# Design Principles

AVA is built around five principles:

### 1. AI should reason, not blindly control

The LLM proposes reasoning and actions through a controlled interface.

### 2. The building must respond physically

Actions should affect the Digital Twin rather than simply changing UI values.

### 3. Every action should be verifiable

AVA measures the resulting building state.

### 4. Humans should communicate naturally

Operators should not need to understand HVAC control terminology.

### 5. Building intelligence should be adaptable

Different buildings should be able to expose different capabilities.

---

# Summary

AVA combines **AI reasoning, building simulation, thermal comfort modelling, and HVAC control** into one closed-loop system.

```text
                 ┌──────────────────┐
                 │      HUMAN       │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │  AVA ASSISTANT   │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ NEMOTRON / AI    │
                 │    REASONING     │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ CONTROL / SAFETY │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │   HVAC ADAPTER   │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ BUILDING DIGITAL │
                 │      TWIN        │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ PMV / COMFORT    │
                 │   VERIFICATION   │
                 └────────┬─────────┘
                          │
                          ▼
                 ┌──────────────────┐
                 │ ACTION ANALYSIS  │
                 └──────────────────┘
```

**AVA is an AI-powered HVAC control system demonstrated through a physics-based Building Digital Twin — turning natural-language building feedback into controlled, measurable, and verifiable HVAC actions.**
<img width="556" height="523" alt="image" src="https://github.com/user-attachments/assets/91f2b83d-9a80-4b9d-aceb-8b6b9ec9fb4b" /> 
scan it to visit the website 
OR
https://ava-pi-drab.vercel.app/

