# Kairos X
## Neuro-Symbolic Algorithmic Trading Architecture

Kairos X is an institutional-grade, multi-agent trading platform designed for the high-frequency analysis and execution of financial instruments. The system utilizes a Neuro-Symbolic architecture, effectively merging deep reinforcement learning with deterministic symbolic logic to ensure both high-alpha generation and rigorous risk management.

---

## System Architecture

The platform operates on a bifurcated intelligence model, ensuring that every AI-driven decision is validated by a secondary layer of structural safety.

### 1. Neuro Layer (Predictive Intelligence)
The Neuro Layer is responsible for processing non-linear market patterns and generating high-dimensional forecasts.
*   **Reinforcement Learning Strategist**: Utilizes Proximal Policy Optimization (PPO) models, exported via the Open Neural Network Exchange (ONNX) format. This agent optimizes entry/exit timing and position sizing based on real-time Limit Order Book (LOB) state representations.
*   **Oracle Sequence Forecasting**: Implements Long Short-Term Memory (LSTM) networks to identify temporal dependencies in price action, providing directionality forecasts with associated confidence intervals.

### 2. Symbolic Layer (Structural Safety)
The Symbolic Layer acts as a deterministic filter, enforcing regulatory and mathematical constraints on the Neuro Layer's outputs.
*   **Risk Guardian**: A circuit-breaker system that monitors real-time equity drawdowns, market volatility, and anomaly scores. It enforces hard stop-losses and has the authority to issue emergency "Halt" commands across the engine.
*   **Logic Gates**: Implements technical rule-sets (VWAP, EMA cross-over, and Order Imbalance filters) that must be satisfied before any RL-generated trade is approved for execution.

---

## Multi-Agent Intelligence Hive

The engine consists of five specialized agents that communicate through a shared, lock-protected state bus.

| Agent | Functional Domain | Primary Output |
| :--- | :--- | :--- |
| **Analyst** | Microstructure Analysis | Order Imbalance, VWAP, EMA, Momentum |
| **Sentiment** | NLP Signal Extraction | Natural Language Alpha Score (-1.0 to +1.0) |
| **Oracle** | Temporal Forecasting | Mid-price Directional Signal & Confidence |
| **Strategist** | Portfolio Optimization | Policy-based Virtual Position Management |
| **Guardian** | Anomaly & Risk | Max Drawdown Monitoring & Halt Commands |

---

## Obsidian Terminal Interface

The Kairos X dashboard is a high-performance visual terminal built for real-time telemetry and market monitoring.

*   **Spatial Order Book**: A Three.js powered 3D landscape of market depth, allowing for the visualization of liquidity clusters and spoofing patterns across the Z-axis (time).
*   **Obsidian Design System**: A high-contrast, low-latency interface optimized for prolonged monitoring sessions.
*   **Telemetric Dashboard**: Real-time visualization of agent heartbeats, signal confidence, and risk-adjusted portfolio metrics (Equity, Drawdown, P&L).
*   **Institutional Assets**: Integration of official corporate brandmarks for high-speed ticker recognition within trending and top-gainer carousels.

---

## Technical Specification

*   **Backend Runtime**: Python 3.10+ utilizing an Asynchronous Event Loop (asyncio).
*   **Inference Engine**: ONNX Runtime for hardware-accelerated model execution.
*   **Communication**: WebSocket protocol for 60fps real-time data streaming to the frontend.
*   **Visual Stack**: WebGL/Three.js for spatial rendering and HTML5 Canvas for high-performance chart overlays.
*   **Simulation Engine**: Custom high-volatility simulator designed for Nifty 50 blue-chip instrument sets.

---

## Installation and Operation

### 1. Environment Configuration
Ensure all system dependencies are satisfied before proceeding with the installation.
```bash
# Clone the repository
git clone https://github.com/project/kairos-x.git
cd kairos-x

# Initialize virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: .\venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

### 2. Simulation Execution
To initiate the multi-agent trading environment in simulation mode:
```bash
python start_sim_indian.py
```
This command initializes the shared state bus, launches all five AI agents, and starts the FastAPI/WebSocket server on port 5001.

### 3. Monitoring Access
The terminal can be accessed via any modern web browser at:
**http://127.0.0.1:5001**

---

## Project Structure

*   **agents/**: Specialized logic for Analyst, Oracle, Strategist, Guardian, and Sentiment agents.
*   **shared/state.py**: Centralized, lock-protected data structure for cross-agent communication.
*   **dashboard/**: Backend WebSocket server and the Obsidian Terminal frontend assets.
*   **models/**: Pre-trained ONNX and PPO models for the Neuro Layer.
*   **start_sim_indian.py**: Entry point for the high-volatility market simulation.

---

## Compliance and Disclaimer

This software is a research and development framework for algorithmic trading. All trading actions, positions, and financial metrics displayed within the platform are simulated. This project does not constitute financial advice. The developers are not responsible for any financial losses incurred through the use of this software in live trading environments.
