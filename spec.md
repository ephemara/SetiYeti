

```markdown
# spec.md — Project Latent-SETI / DeepListen

## 1. Project Overview & Vision
An unsupervised, low-level signal ingestion and anomaly detection engine designed to mine raw, unprocessed astronomical archives (specifically Breakthrough Listen AWS S3 baseband $I/Q$ telemetry) for non-standard, exotic, or artificial signals that traditional institutional pipelines discard.

### Core Thesis
Legacy astronomical SETI tools rely on lossy data reduction (squashing raw voltages into 2D intensity spectrograms), rigid linear heuristics (assuming constant Doppler drift), and high-risk-aversion filters. By maintaining raw complex phase data, applying cyclostationary feature extraction, and deploying self-supervised latent space anomaly models, an independent engine can identify sub-noise, phase-coherent, or non-linear signals hidden in plain sight across petabytes of public data.

---

## 2. Technical Stack & Ingestion Pipeline


```

[ AWS S3: Breakthrough Listen ] ──► [ Complex Baseband I/Q Ring Buffer ]
│
┌───────────────────────────────────────┴───────────────────────────────────────┐
▼                                       ▼                                       ▼
[ Phase Coherence & CVNN ]      [ Cyclostationary Feature Engine ]     [ Neural ODE Trajectory Tracker ]
│                                       │                                       │
└───────────────────────────────────────┬───────────────────────────────────────┘
▼
[ Unsupervised Latent Anomaly Engine ]
(6σ Distance Threshold)
│
▼
[ Multi-Messenger Kafka Broker ]
(Gaia DR3 / ZTF / MAST Cross-Ref)

```

### Key Data Targets
* **Primary Target:** Breakthrough Listen AWS S3 (`s3://breakthrough-listen/`) — Raw baseband $I/Q$ voltage streams (`.raw`) and high-resolution filterbanks (`.h5`).
* **Secondary Targets:** Gaia DR3 (3D astrometry/kinematics), MAST (JWST/Hubble light curves), Zwicky Transient Facility (ZTF real-time optical alert streams via Fink/ANTARES).

---

## 3. Core Architectural Modules

### Module A: Raw $I/Q$ Complex Ingestion Engine
* **Problem Solved:** Legacy tools convert baseband voltage into power spectra ($\vert{}I + qJ\vert{}^2$), completely destroying phase relationships to save storage space.
* **Architecture:** Ingest raw complex time-series $I/Q$ streams into zero-copy ring buffers using Complex-Valued Neural Networks (CVNNs).
* **Target:** Detect phase-coherent signals, Phase-Shift Keying (PSK), and high-order phase correlations at sub-zero Signal-to-Noise Ratios ($SNR < 0 \text{ dB}$).

### Module B: Cyclostationary & Fractional Fourier Analysis
* **Problem Solved:** Simple Fast Fourier Transforms (FFTs) assume stationary noise and fail to detect spread-spectrum modulation or smeared dispersed pulses.
* **Architecture:** 
  1. Compute the **Spectral Correlation Density Function** $S_x^\alpha(f)$ to isolate hidden periodicities in seemingly flat Gaussian thermal noise:
     $$S_x^\alpha(f) = \lim_{T \to \infty} \frac{1}{T} E\left[ X_T\left(f + \frac{\alpha}{2}\right) X_T^*\left(f - \frac{\alpha}{2}\right) \right]$$
  2. Implement an automated **Fractional Fourier Transform (FrFT)** rotation angle solver to de-smear phase chirps and interstellar dispersion without manual dedispersion trials.

### Module C: Neural ODE Non-Linear Trajectory Tracker
* **Problem Solved:** Traditional search tools (`turboSETI`) search strictly for straight lines in time-frequency space ($d\nu/dt = \text{constant}$). Signals from rotating planets, tumbling craft, or frequency-hopping spread spectrum (FHSS) are missed.
* **Architecture:** Utilize **Neural Ordinary Differential Equations (Neural ODEs)** combined with dynamic time-warping to model and track arbitrary, non-linear acceleration curves across time-frequency space.

### Module D: Unsupervised Latent Space Anomaly Engine
* **Problem Solved:** Supervised models are biased toward human assumptions of what an "alien signal" should look like (e.g., continuous narrow-band sine waves).
* **Architecture:** 
  1. Train a Masked Autoencoder (MAE) / Contrastive Latent Model exclusively on known natural astrophysical noise, solar flares, and Earth-based RFI.
  2. Compute embedding vector distances for incoming streams. Any signal exceeding a $6\sigma$ distance threshold in latent space is flagged as a structural anomaly, regardless of its visual or mathematical shape.

---

## 4. Target Anomaly Vectors & Payload Formats

| Vector Type | Target Physical Signature | Ingestion/Detection Method |
| :--- | :--- | :--- |
| **Sub-Noise Spread Spectrum** | Low-power Direct Sequence (DSSS) sitting below the thermal noise floor. | Cyclostationary Spectral Analysis ($S_x^\alpha(f)$) |
| **Non-Linear Acceleration** | Curved, parabolic, or frequency-agile Doppler trajectories. | Neural ODE Trajectory Tracking |
| **Lattice Modulation** | High-dimensional vector constellations ($E_8$ lattices) across complex phase space. | CVNN Latent Space Clustering |
| **Self-Executing Bytecode / Matrix** | Semiprime $N = P_1 \times P_2$ matrix frames, prime sequence preambles, or self-describing VM instruction sets. | Automated Factorization & Prime-Grid Raster Parsing |

---

## 5. Pi Agent Harness Implementation Plan

1. **Agent Spec Definition (`pi_agent.config`):**
   * **Data Scraper Agent:** Handles AWS S3 bucket streaming, $I/Q$ chunking, and local memory mapping.
   * **Signal Processor Agent:** Executes low-level math transforms (FrFT, Cyclostationary Analysis, CVNN tensor ops).
   * **Validation Agent:** Automatically cross-references flagged anomalies against Starlink orbital ephemerides, known satellite RFI databases, and Gaia/ZTF coordinates to reject false positives.
2. **Execution Strategy:**
   * Run background ingestion jobs while working on primary projects.
   * Use the agent harness to generate test suites, benchmark parsing overhead, and handle real-time Kafka event streaming.

```