# Kairos X — AI-Powered Algorithmic Trading Engine

> A multi-agent, event-driven trading engine that ingests raw NASDAQ ITCH 5.0 market data, reconstructs a live order book, and runs four parallel AI agents — forecasting, strategy, risk, and anomaly detection — all coordinated through a shared asyncio event loop with a real-time FastAPI/WebSocket dashboard.

---

## Architecture

```
                        ┌─────────────────────────────────────────────────┐
                        │              run_all.py  (asyncio orchestrator)  │
                        └──────┬──────────────────────────────────────────┘
                               │  creates 7 concurrent asyncio tasks
           ┌───────────────────┼───────────────────────────────────────────┐
           │                   │                                           │
           ▼                   ▼                                           ▼
   ┌───────────────┐   ┌───────────────┐                       ┌──────────────────┐
   │  feed/        │   │  snapshot_    │                       │  dashboard/      │
   │  itch_parser  │──▶│  pump         │──────────────────────▶│  FastAPI + uvi-  │
   │  (async I/O)  │   │  (drain loop) │                       │  corn  :5001     │
   └───────┬───────┘   └───────┬───────┘                       └──────────────────┘
           │                   │
           ▼                   ▼
  ┌─────────────────┐   ┌──────────────────┐
  │  OrderBook-     │   │  EngineState     │  (asyncio.Lock-protected shared state)
  │  Manager        │   │  .snapshots      │
  │  (per-ticker    │   │  .signals        │
  │   L2 book)      │   │  .positions      │
  └─────────────────┘   │  .risk_alerts    │
           │            └────────┬─────────┘
           │                     │  read/write (async with state.lock_*)
           ▼                     │
   ┌───────────────┐             ├──────────────────────────────────┐
   │  RingBuffer   │             │                                  │
   │  (shared mem) │     ┌───────▼──────┐   ┌──────────────────┐   │
   └───────────────┘     │  Analyst     │   │  Oracle          │   │
                         │  (indicators)│──▶│  (LSTM signals)  │   │
                         └─────────────┘   └──────────────────┘   │
                                                                    │
                         ┌───────────────┐   ┌──────────────────┐  │
                         │  Strategist   │   │  Guardian        │  │
                         │  (PPO / virt- │   │  (Autoencoder +  │  │
                         │   positions)  │   │   risk limits)   │  │
                         └───────────────┘   └──────────────────┘  │
                                  └──────────────────────────────────┘
```

**Data flow summary:** `itch_parser` reads the ITCH 5.0 binary file, updates `OrderBookManager` (L2 reconstruction), and writes snapshots to a POSIX shared-memory `RingBuffer`. The `snapshot_pump` task drains the ring buffer into `EngineState.snapshots` under an asyncio lock. Four agents poll `EngineState` independently and write back their outputs (signals, positions, alerts) to the same shared state. The dashboard reads `EngineState` over WebSocket to render the live UI.

---

## Tech Stack

| Layer | Component | Technology |
|-------|-----------|------------|
| **Data Ingestion** | Market feed parser | Python `asyncio`, NASDAQ ITCH 5.0 binary protocol |
| **Order Book** | L2 order book reconstruction | `OrderBookManager` (custom, per-ticker) |
| **IPC / Buffer** | Inter-task data transport | POSIX shared-memory `RingBuffer` |
| **Shared State** | Cross-agent state bus | `EngineState` with `asyncio.Lock` per field |
| **Forecasting Agent** | Price/direction prediction | LSTM (Oracle agent) |
| **Strategy Agent** | Position management | PPO reinforcement learning (Strategist agent) |
| **Anomaly Detection** | Market regime / fraud detection | Autoencoder (Guardian agent) |
| **Indicator Engine** | Technical analysis | Markov chain / sliding window (Analyst agent) |
| **API Server** | REST + WebSocket backend | FastAPI + uvicorn (`loop='none'` mode) |
| **Orchestration** | Task lifecycle, signal handling | `asyncio.gather`, SIGINT/SIGTERM handlers |
| **Entry Point** | CLI / startup | `start.sh` (bash), `run_all.py` (Python) |
| **Config** | Runtime overrides | Environment variables (`ITCH_FILE`, `TICKERS`, `MAX_MSG`, `DASHBOARD_PORT`) |
| **Data Generation** | Synthetic ITCH data | `data/generate_sample.py` |

---

## How It Works

**Feed ingestion and order book reconstruction.** The engine begins with an async ITCH 5.0 binary parser that processes raw NASDAQ market messages and maintains a per-ticker Level 2 order book in `OrderBookManager`. Rather than reconstructing the book on the fly in-agent (which would introduce blocking), the parser snapshots the book state after each batch of messages and writes those snapshots to a POSIX shared-memory `RingBuffer`. This decouples the I/O-bound parsing step from the CPU-bound AI inference steps — the feed can run at wire speed while agents process at their own cadence. After the ITCH file is fully parsed, the engine deliberately keeps running so the dashboard remains live for post-parse inspection; this was an explicit design choice to support interactive analysis of a finite historical file.

**Four-agent parallel execution via shared asyncio state.** All four agents — Analyst (Markov-chain indicators), Oracle (LSTM price forecasting), Strategist (PPO-based position sizing), and Guardian (autoencoder anomaly detection) — run as independent `asyncio` tasks over the same event loop, reading from and writing to `EngineState`. Each field of `EngineState` (`snapshots`, `signals`, `positions`, `risk_alerts`) is protected by its own `asyncio.Lock`, which prevents cross-agent writes from corrupting state without requiring OS-level mutexes or a message broker. The agent dependency order is intentional: Analyst produces indicators → Oracle consumes indicators to generate BUY/SELL/HOLD signals → Strategist manages positions based on those signals → Guardian operates orthogonally and can gate or override the Strategist by writing risk alerts. This is a soft pipeline: agents don't block each other, and stale reads are acceptable at the millisecond cadence of a simulation.

**Dashboard architecture and uvicorn integration.** The FastAPI dashboard is embedded in the same event loop as the trading engine via `uvicorn.Config(loop='none')`, which tells uvicorn to reuse the existing running loop rather than spinning up its own. This means the dashboard is not a separate process — it shares in-process state with the agents, making WebSocket pushes zero-copy. The tradeoff is that a dashboard crash can affect the engine; in a production system this would be separated into its own process with IPC. The startup script (`start.sh`) also exposes a `dash`-only mode, allowing the dashboard to be started independently when replaying a previous engine run.

---

## Setup & Installation

### Prerequisites

- Python 3.10+
- macOS or Linux (POSIX shared memory required for `RingBuffer`)
- ~200 MB disk for a sample ITCH data file

### Install

```bash
git clone https://github.com/josh22018/ai-powered-trading-system.git
cd ai-powered-trading-system
python3 -m venv venv
source venv/bin/activate
pip install -r venv/requirements.txt   # or install from imports: fastapi uvicorn numpy torch
```

### Generate synthetic ITCH data (if you don't have a real feed file)

```bash
./start.sh gen
# or directly:
python3 data/generate_sample.py
```

This creates `~/kairos-x/data/sample.NASDAQ_ITCH50` — a synthetic binary file conforming to ITCH 5.0 message format.

### Run the full engine

```bash
./start.sh
```

The dashboard will be available at `http://127.0.0.1:5001`.

### Run modes

```bash
./start.sh all    # full engine: feed + agents + dashboard (default)
./start.sh feed   # feed pipeline only (no dashboard)
./start.sh gen    # regenerate synthetic data only
```

### Environment overrides

```bash
ITCH_FILE=~/data/real_feed.NASDAQ_ITCH50 \
TICKERS=AAPL,TSLA,NVDA \
MAX_MSG=500000 \
DASHBOARD_PORT=8080 \
./start.sh
```

| Variable | Default | Description |
|----------|---------|-------------|
| `ITCH_FILE` | `~/kairos-x/data/sample.NASDAQ_ITCH50` | Path to ITCH 5.0 binary |
| `TICKERS` | `AAPL,MSFT,GOOGL` | Comma-separated ticker filter |
| `MAX_MSG` | unlimited | Cap on parsed ITCH messages |
| `DASHBOARD_PORT` | `5001` | uvicorn listen port |
| `DASHBOARD_HOST` | `127.0.0.1` | uvicorn listen host |

---

## Key Design Decisions

### ADR-001: Ring Buffer Over asyncio.Queue for Agent Data Transport

**Context.** The snapshot pump needs to pass order book snapshots from the ITCH parser to `EngineState` at high throughput. The naive approach would be an `asyncio.Queue`, which is simple but lives entirely in Python heap memory.

**Decision.** Use a POSIX shared-memory `RingBuffer` (`shared/ring_buffer.py`) as the transport layer between the parser and the snapshot pump.

**Rationale.** A ring buffer backed by shared memory is fixed-size and allocation-free after initialization — writes never trigger garbage collection pauses. It also models the real-world architecture of market data infrastructure (e.g., LMAX Disruptor, Aeron), where a ring buffer is the canonical pattern for high-throughput, low-latency producer-consumer handoff. The `read_all_new(last_idx)` interface exposes a cursor-based read that allows the pump to batch-consume all new entries since its last check in a single pass, amortizing the per-read overhead. The downside is platform dependence: POSIX shared memory requires Unix, ruling out native Windows. This was an acceptable tradeoff for a system targeting professional trading infrastructure.

**Consequences.** The `rb.cleanup()` call in the orchestrator's `finally` block is mandatory — POSIX shared memory segments are OS-level resources that persist across process restarts if not explicitly unlinked.

---

### ADR-002: Single asyncio Event Loop for All Subsystems (Including uvicorn)

**Context.** The system has seven concurrent subsystems: one feed parser, one snapshot pump, four AI agents, and one HTTP/WebSocket server. The most common approach would be to run the dashboard in a separate process and communicate over IPC or a local socket.

**Decision.** All seven subsystems run as `asyncio.Task` objects within a single event loop. uvicorn is configured with `loop='none'` to join the existing loop rather than creating its own.

**Rationale.** This yields two concrete benefits. First, agents can write to `EngineState` and the dashboard can read from it with zero serialization cost — no pickle, no JSON, no socket roundtrip. Second, the orchestrator gains a single point of lifecycle control: one `asyncio.gather(*tasks, return_exceptions=True)` in the `finally` block cancels all subsystems atomically on SIGINT or SIGTERM. The alternative (multiprocessing) would require a shared-memory or socket-based state sync protocol, significantly increasing complexity for a system where latency between agent output and dashboard display is not a hard requirement.

**Consequences.** A blocking call in any subsystem will stall the entire engine. All AI model inference must be either fast enough to not noticeably delay other tasks, or offloaded to a thread pool via `asyncio.to_thread`. This is a known limitation documented in the roadmap below.

---

## Results & Metrics

The following are observable from a completed run against the synthetic ITCH data file:

| Metric | Observed |
|--------|----------|
| Feed parse throughput | Reported in stdout: `N msgs / elapsed_time s` |
| Ring buffer slots written | Logged per run: `slots_written` |
| Parse errors | Logged per run: `parse_errors` counter |
| Dashboard latency | Sub-second (in-process state, no IPC) |
| Graceful shutdown | Full task cancellation on SIGINT confirmed |

To capture a run summary:

```bash
./start.sh 2>&1 | tee kairos_run.log
```

The `[feed] Done` line emitted by `run_feed` contains throughput stats in the format:

```
[feed] Done — 1,234,567 msgs  892,341 slots  4.87s  errors=0
```

> **Note on live metrics:** The system is a simulation engine. P&L, Sharpe ratio, and win-rate figures require connecting the Strategist's virtual position log to a post-run analysis script — this is the highest-priority next step (see roadmap).

---

## Limitations & Roadmap

### Known Limitations

**No real broker integration.** The Strategist manages virtual positions only. There is no order routing, execution simulation with slippage/fees, or connection to a paper trading API (e.g., Alpaca, Interactive Brokers).

**Blocking inference risk.** LSTM and autoencoder inference runs synchronously within asyncio tasks. Under a heavy model or large batch, this will delay other agents. The fix is `asyncio.to_thread()` wrapping for all model forward passes.

**No persistence.** `EngineState` is in-memory and lost on shutdown. Signal history, position logs, and risk alerts are not written to disk or a time-series database.

**Single-file ITCH replay only.** The feed parser reads a finite binary file. There is no live WebSocket or UDP multicast feed connector for real-time NASDAQ data.

**Windows incompatible.** The `RingBuffer` relies on POSIX shared memory (`mmap`, `shm_open`). A Windows port would require replacing this with `mmap` via `CreateFileMapping` or switching to `asyncio.Queue`.

### Roadmap

- [ ] **Post-run analytics script** — parse position log → compute Sharpe ratio, max drawdown, win rate, and benchmark against buy-and-hold
- [ ] **`asyncio.to_thread` for model inference** — prevent LSTM/autoencoder forward passes from blocking the event loop
- [ ] **SQLite / InfluxDB sink** — persist snapshots, signals, and positions for replay and backtesting
- [ ] **Live feed connector** — replace file-based ITCH replay with a real-time NASDAQ TotalView or Alpaca WebSocket feed
- [ ] **Unit test suite** — test `OrderBookManager` add/cancel/execute message handling, ring buffer cursor semantics, and Guardian alert thresholds independently
- [ ] **Dockerize** — containerize the engine with a `docker-compose.yml` that mounts a data volume and exposes the dashboard port, eliminating the POSIX shared memory platform dependency
- [ ] **Broker integration** — connect Strategist signals to Alpaca paper trading API for end-to-end simulation with realistic fill modeling

---

## Project Structure

```
ai-powered-trading-system/
├── run_all.py              # Orchestrator: wires all 7 asyncio tasks
├── start.sh                # Entrypoint: bash launcher with mode dispatch
├── agents/
│   ├── analyst/            # Markov-chain indicator engine
│   ├── oracle/             # LSTM price/direction forecasting
│   ├── strategist/         # PPO-based virtual position manager
│   └── guardian/           # Autoencoder anomaly detection + risk limits
├── feed/
│   ├── itch_parser.py      # Async ITCH 5.0 binary parser
│   ├── order_book.py       # Per-ticker L2 order book (OrderBookManager)
│   └── run_feed.py         # Standalone feed-only entry point
├── shared/
│   ├── ring_buffer.py      # POSIX shared-memory ring buffer
│   └── state.py            # EngineState: lock-protected cross-agent state
├── dashboard/
│   └── backend/
│       └── app.py          # FastAPI app factory (create_app(state))
└── data/
    └── generate_sample.py  # Synthetic ITCH 5.0 data generator
```

---

## Disclaimer

This system is a research and portfolio project built for educational purposes. It does not constitute financial advice. All trading signals and positions are virtual and are not connected to any real brokerage or exchange.
