# Kairos X: Project Specification and Technical Whitepaper

## 1. Executive Summary

Kairos X is a sophisticated algorithmic trading architecture designed to bridge the gap between high-dimensional neural network predictions and deterministic financial logic. By employing a Neuro-Symbolic framework, the system ensures that every high-alpha execution is governed by a rigorous layer of mathematical risk constraints. The platform is built for real-time operation, utilizing an asynchronous event loop to coordinate five specialized AI agents.

---

## 2. Core Methodology: Neuro-Symbolic Intelligence

The foundational philosophy of Kairos X is the bifurcation of intelligence into two distinct layers:

### 2.1 The Neuro Layer (Pattern Recognition)
The Neuro Layer is responsible for extracting alpha from non-linear market data.
*   **Deep Reinforcement Learning (DRL)**: The Strategist agent utilizes Proximal Policy Optimization (PPO). The policy is trained in a simulated environment and exported to the Open Neural Network Exchange (ONNX) format for low-latency inference.
*   **Temporal Sequence Analysis**: The Oracle agent employs Long Short-Term Memory (LSTM) networks to process historical time-series data, identifying momentum shifts and trend reversals.

### 2.2 The Symbolic Layer (Rule-Based Governance)
The Symbolic Layer enforces the operational boundaries of the engine.
*   **Deterministic Logic**: Technical indicators (VWAP, EMA, Order Imbalance) act as boolean gates for the Neuro Layer's outputs.
*   **Guardian Enforcement**: High-speed risk auditing that monitors drawdown, volatility, and anomaly scores (derived from autoencoder reconstruction loss).

---

## 3. Component Deep-Dive

### 3.1 The Engine State Bus (shared/state.py)
The central nervous system of Kairos X is a lock-protected, in-memory state bus.
*   **Concurrency Model**: Utilizes Python's `asyncio` event loop. Every mutable field (snapshots, positions, signals) is protected by a dedicated `asyncio.Lock`.
*   **Data Serialization**: State is serialized to JSON at 60Hz and broadcast via WebSockets to the terminal.

### 3.2 The Agent Hive (agents/)
*   **Analyst Agent**: Computes microstructure metrics. It measures order book imbalance, spread-to-price ratios, and volume-weighted average price (VWAP).
*   **Sentiment Agent**: Ingests social and news metadata to generate a scalar sentiment score (-1.0 to +1.0), providing macro context to the micro-data.
*   **Oracle Agent**: Generates directional signals with confidence scores based on temporal price patterns.
*   **Strategist Agent**: The decision-making core. It consumes inputs from the Analyst, Oracle, and Sentiment agents to determine position entries, exits, and sizes via its ONNX policy.
*   **Guardian Agent**: The risk authority. It monitors the engine for anomalous behavior and breaches of pre-defined risk thresholds (e.g., max position size or unrealized loss limits).

### 3.3 The Execution Engine (agents/execution/)
Designed for simulation-to-live parity.
*   **Sandbox Bridge**: Implements virtual order fulfillment, simulating exchange latency and order confirmation.
*   **Upstox Integration**: Provides a structural blueprint for live order routing to the Indian markets, currently operating in a virtualized sandbox for development.

---

## 4. Visual Terminal and Spatial Visualization

### 4.1 The Obsidian Terminal
A high-performance web interface designed for institutional monitoring.
*   **Infinite Scrolling Carousels**: Optimized for high-density ticker tracking using CSS keyframe-based scrolling and hover-pause states.
*   **Dynamic Brandmarks**: Real-time resolution of ticker symbols to corporate domains via a global CDN for high-speed visual recognition.

### 4.2 Spatial Order Book (Three.js)
A three-dimensional representation of the Limit Order Book (LOB).
*   **Geometry**: Bid and Ask volumes are rendered as dynamic boxes along the X (price) and Y (volume) axes.
*   **Optics**: The Z-axis represents time, creating a "flow" of historical depth that allows traders to identify spoofing and liquidity walls.
*   **Grid System**: A 30x70 unit ground plane tightly fitted to the active data range to minimize visual latency.

---

## 5. Technical Stack

*   **Language**: Python 3.10+
*   **Backend Framework**: FastAPI (Uvicorn)
*   **ML Inference**: ONNX Runtime
*   **Training Framework**: Stable-Baselines3 (PPO)
*   **3D Graphics**: Three.js (WebGL)
*   **Data Streaming**: WebSockets
*   **UI/UX**: Vanilla JavaScript (ES6+), Modern CSS3 (Glassmorphism, CSS Variables)

---

## 6. Operational Workflow

### 6.1 Data Ingestion
The system utilizes a High-Volatility Indian Market Simulator (`start_sim_indian.py`) to inject aggressive price action and volume imbalance into the engine state, forcing edge-case responses from the AI agents.

### 6.2 Decision Loop
1.  **Analyst** updates technical metrics.
2.  **Oracle** and **Sentiment** update directional forecasts.
3.  **Strategist** runs ONNX inference to generate a position action.
4.  **Guardian** audits the proposed action against risk limits.
5.  **Execution** completes the virtual order and updates the portfolio state.

### 6.3 Visualization
The shared state is serialized and pushed to the **Obsidian Terminal**, where the UI reconciles the portfolio equity, updates the 3D book, and refreshes the ticker carousels.

---

## 7. Compliance and Risk Statement

Kairos X is a simulation and research platform. All trade executions, portfolio balances, and profit/loss metrics are strictly virtual. This software is not intended for use in live, funded trading environments without further hardening and independent security audits. No part of this documentation or software constitutes financial advice.
