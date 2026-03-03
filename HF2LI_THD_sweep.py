"""
HF2LI Total Harmonic Distortion (THD) Measurement
===================================================
Sweeps the drive frequency and simultaneously measures the 1st, 2nd, 3rd and
4th harmonics using four demodulators locked to the same oscillator.
THD is calculated from the measured harmonic amplitudes at each frequency point.

Hardware connection:
    Signal Output 1  →  Device Under Test (DUT)  →  Signal Input 1

Requirements:
    - Zurich Instruments HF2LI (DEV182253), connected via USB
    - LabOne data server running locally
    - zhinst-toolkit >= 22.02  (pip install zhinst-toolkit)
"""

import time
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path
from zhinst.toolkit import Session

# ──────────────────────────────────────────────────────────────────────────────
# Parameters — adjust these to your setup
# ──────────────────────────────────────────────────────────────────────────────

DEVICE_ID = "DEV182253"         # HF2LI device ID (shown in LabOne GUI)

# --- Frequency sweep ----------------------------------------------------------
FREQ_START   = 1e3              # Sweep start frequency (Hz)
FREQ_STOP    = 10e6             # Sweep stop  frequency (Hz)
#   Keep FREQ_STOP < 50 MHz / NUM_HARMONICS so all harmonics stay in range
NUM_POINTS   = 100              # Number of frequency points
SWEEP_MAPPING = "log"           # "log" (recommended) or "linear"

# --- Signal output ------------------------------------------------------------
OUT_CHANNEL     = 0             # Signal output index (0 or 1)
OUT_MIXER_CH    = 0             # Mixer channel for the output — see note below
#   For HF2LI, mixer channel 0 drives the output with oscillator 0.
#   If the output is silent, try channels 1–7 or check the LabOne GUI
#   (Settings → Output → Enable the correct mixer channel).
DRIVE_AMPLITUDE = 0.5           # Drive amplitude (V peak) — keep within OUT_RANGE
OUT_RANGE       = 1.0           # Output range (V); options: 0.01, 0.1, 1.0, 10.0

# --- Signal input -------------------------------------------------------------
IN_CHANNEL = 0                  # Signal input index (0 or 1)
IN_RANGE   = 1.0                # Input range (V); set just above expected signal level
IN_AC      = 0                  # 0 = DC coupling, 1 = AC coupling
IN_IMP50   = 0                  # 0 = 1 MΩ input, 1 = 50 Ω input

# --- Demodulators (one per harmonic) -----------------------------------------
OSC_INDEX    = 0                # Oscillator to sweep (0–5 on HF2LI)
NUM_HARMONICS = 4               # Harmonics to measure: 1st, 2nd, 3rd, 4th
DEMOD_TC     = 10e-3            # Filter time constant (s); shorter = faster, noisier
DEMOD_ORDER  = 4                # Filter order (1–8)
DEMOD_RATE   = 100              # Sample rate (Sa/s); only needed if using poll, not sweeper

# --- Sweeper settling and averaging ------------------------------------------
SETTLE_TIME_TC      = 10        # Settle time in multiples of the filter TC
SETTLE_INACCURACY   = 1e-3      # Settle inaccuracy threshold (0.001 = 0.1 %)
AVG_SAMPLES         = 1         # Number of samples to average per point
AVG_TIME_TC         = 5         # Averaging time in multiples of the filter TC
BW_CONTROL          = 1         # 1 = auto-adjust filter BW with frequency (recommended)

# --- Output ------------------------------------------------------------------
SAVE_CSV    = True              # Save frequency + amplitude + THD to a CSV file
SAVE_PLOT   = True              # Save the plot as PNG
OUTPUT_DIR  = Path(".")         # Directory for saved files (current directory)

# ──────────────────────────────────────────────────────────────────────────────
# 1. Connect to HF2LI
# ──────────────────────────────────────────────────────────────────────────────

# hf2=True is required — the HF2LI uses a separate data server (port 8005)
session = Session("localhost", hf2=True)
device  = session.connect_device(DEVICE_ID)

print(f"Connected to {DEVICE_ID}")
print(f"Sweep: {FREQ_START:.0f} – {FREQ_STOP:.0f} Hz  |  {NUM_POINTS} points  |  mapping = {SWEEP_MAPPING}")
print(f"Measuring harmonics 1 – {NUM_HARMONICS} simultaneously\n")

# ──────────────────────────────────────────────────────────────────────────────
# 2. Configure signal output and oscillator
# ──────────────────────────────────────────────────────────────────────────────

with device.set_transaction():
    device.oscs[OSC_INDEX].freq(FREQ_START)             # initial oscillator frequency

    device.sigouts[OUT_CHANNEL].range(OUT_RANGE)
    device.sigouts[OUT_CHANNEL].amplitudes[OUT_MIXER_CH](DRIVE_AMPLITUDE)
    device.sigouts[OUT_CHANNEL].enables[OUT_MIXER_CH](True)
    device.sigouts[OUT_CHANNEL].on(True)

    device.sigins[IN_CHANNEL].range(IN_RANGE)
    device.sigins[IN_CHANNEL].ac(IN_AC)
    device.sigins[IN_CHANNEL].imp50(IN_IMP50)

print("Signal output ON")
print(f"  Drive amplitude : {DRIVE_AMPLITUDE} V  (range = ±{OUT_RANGE} V)")

# ──────────────────────────────────────────────────────────────────────────────
# 3. Configure demodulators — one per harmonic
# ──────────────────────────────────────────────────────────────────────────────
#
#   All demods are locked to the same oscillator (OSC_INDEX).
#   The `harmonic` node tells each demod to measure at N × osc_freq:
#
#     Demod 0  →  harmonic 1  →  1 × f_drive   (fundamental)
#     Demod 1  →  harmonic 2  →  2 × f_drive   (2nd harmonic)
#     Demod 2  →  harmonic 3  →  3 × f_drive   (3rd harmonic)
#     Demod 3  →  harmonic 4  →  4 × f_drive   (4th harmonic)
#
#   When the sweeper changes oscs/0/freq, all four demod reference
#   frequencies update automatically.

with device.set_transaction():
    for i in range(NUM_HARMONICS):
        device.demods[i].enable(1)
        device.demods[i].oscselect(OSC_INDEX)
        device.demods[i].harmonic(i + 1)        # 1, 2, 3, 4
        device.demods[i].adcselect(IN_CHANNEL)
        device.demods[i].order(DEMOD_ORDER)
        device.demods[i].timeconstant(DEMOD_TC)
        device.demods[i].rate(DEMOD_RATE)
        device.demods[i].phaseshift(0.0)

print("\nDemodulators configured:")
for i in range(NUM_HARMONICS):
    suffix = ["st", "nd", "rd", "th"][i]
    print(f"  Demod {i}  →  {i+1}{suffix} harmonic  ({i+1} × f_drive)")

# ──────────────────────────────────────────────────────────────────────────────
# 4. Configure sweeper
# ──────────────────────────────────────────────────────────────────────────────

sweeper = session.modules.sweeper
sweeper.device(device)

# Sweep the oscillator frequency
sweeper.gridnode(f"/{DEVICE_ID}/oscs/{OSC_INDEX}/freq")
sweeper.start(FREQ_START)
sweeper.stop(FREQ_STOP)
sweeper.samplecount(NUM_POINTS)
sweeper.xmapping(1 if SWEEP_MAPPING == "log" else 0)    # 0 = linear, 1 = log

# Settling: wait at each new frequency until the filter output is stable
sweeper.settling.tc(SETTLE_TIME_TC)
sweeper.settling.inaccuracy(SETTLE_INACCURACY)

# Averaging at each point
sweeper.averaging.tc(AVG_TIME_TC)
sweeper.averaging.sample(AVG_SAMPLES)

# Auto bandwidth: scales the filter TC with frequency so spectral resolution
# stays constant across a wide sweep (important for log sweeps)
sweeper.bandwidthcontrol(BW_CONTROL)

# Subscribe all four demodulator sample nodes
for i in range(NUM_HARMONICS):
    sweeper.subscribe(f"/{DEVICE_ID}/demods/{i}/sample")

# ──────────────────────────────────────────────────────────────────────────────
# 5. Run sweep
# ──────────────────────────────────────────────────────────────────────────────

print(f"\nStarting sweep  ({NUM_POINTS} points, settle TC = {SETTLE_TIME_TC} × {DEMOD_TC*1e3:.1f} ms)")
sweeper.execute()
t0 = time.time()

while not sweeper.finished():
    prog = sweeper.progress() * 100
    print(f"  {prog:5.1f} %   ({time.time()-t0:.0f} s elapsed)", end="\r")
    time.sleep(0.5)

elapsed = time.time() - t0
print(f"\nSweep complete in {elapsed:.1f} s")

data = sweeper.read()

# ──────────────────────────────────────────────────────────────────────────────
# 6. Extract results
# ──────────────────────────────────────────────────────────────────────────────
#
#   sweeper.read() returns:
#     { "/dev182253/demods/i/sample": [[{result_dict}]] }
#   where result_dict contains:
#     "grid"  →  x-axis (frequency values, Hz)
#     "r"     →  amplitude R = sqrt(X² + Y²) in V RMS
#     "phase" →  phase in radians
#     "x", "y" → real and imaginary components

freq_axis  = None
amplitudes = {}          # {harmonic_number: np.array of amplitudes}

for i in range(NUM_HARMONICS):
    node_key  = f"/{DEVICE_ID.lower()}/demods/{i}/sample"
    result    = data[node_key][0][0]
    freq_axis = result["grid"]
    amplitudes[i + 1] = result["r"]

print(f"\nResult: {len(freq_axis)} frequency points from {freq_axis[0]:.1f} to {freq_axis[-1]:.1f} Hz")

# ──────────────────────────────────────────────────────────────────────────────
# 7. Calculate Total Harmonic Distortion (THD)
# ──────────────────────────────────────────────────────────────────────────────
#
#   THD = sqrt( V2² + V3² + V4² ) / V1 × 100 %
#   where V1 = fundamental amplitude, V2-V4 = harmonic amplitudes

V1 = amplitudes[1]
harmonic_power_sum = sum(amplitudes[n] ** 2 for n in range(2, NUM_HARMONICS + 1))
THD = 100.0 * np.sqrt(harmonic_power_sum) / V1

print(f"\nTHD summary:")
print(f"  Mean : {np.mean(THD):.3f} %")
print(f"  Min  : {np.min(THD):.3f} %  at {freq_axis[np.argmin(THD)]:.1f} Hz")
print(f"  Max  : {np.max(THD):.3f} %  at {freq_axis[np.argmax(THD)]:.1f} Hz")

# ──────────────────────────────────────────────────────────────────────────────
# 8. Plot
# ──────────────────────────────────────────────────────────────────────────────

COLORS  = ["tab:blue", "tab:orange", "tab:green", "tab:red"]
SUFFIXES = ["st", "nd", "rd", "th"]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
fig.suptitle(f"HF2LI THD Measurement — {DEVICE_ID}", fontsize=13)

# Top panel: harmonic amplitudes in dBV
for n in range(1, NUM_HARMONICS + 1):
    ax1.plot(
        freq_axis,
        20 * np.log10(amplitudes[n] + 1e-12),
        color=COLORS[n - 1],
        label=f"{n}{SUFFIXES[n-1]} harmonic ({n}×f)"
    )
ax1.set_ylabel("Amplitude (dBV)")
ax1.legend(loc="best")
ax1.grid(True, which="both", alpha=0.4)
if SWEEP_MAPPING == "log":
    ax1.set_xscale("log")

# Bottom panel: THD vs frequency
ax2.plot(freq_axis, THD, color="black", linewidth=1.5)
ax2.set_ylabel("THD (%)")
ax2.set_xlabel("Drive Frequency (Hz)")
ax2.grid(True, which="both", alpha=0.4)
if SWEEP_MAPPING == "log":
    ax2.set_xscale("log")

plt.tight_layout()

if SAVE_PLOT:
    plot_path = OUTPUT_DIR / f"THD_{DEVICE_ID}.png"
    plt.savefig(plot_path, dpi=150)
    print(f"\nPlot saved → {plot_path}")

plt.show()

# ──────────────────────────────────────────────────────────────────────────────
# 9. Save data to CSV
# ──────────────────────────────────────────────────────────────────────────────

if SAVE_CSV:
    csv_path = OUTPUT_DIR / f"THD_{DEVICE_ID}.csv"

    # Build header and data matrix
    header = "frequency_Hz," + ",".join(f"harmonic_{n}_V" for n in range(1, NUM_HARMONICS + 1)) + ",THD_percent"
    rows = np.column_stack(
        [freq_axis] + [amplitudes[n] for n in range(1, NUM_HARMONICS + 1)] + [THD]
    )
    np.savetxt(csv_path, rows, delimiter=",", header=header, comments="")
    print(f"Data saved  → {csv_path}")

# ──────────────────────────────────────────────────────────────────────────────
# 10. Cleanup
# ──────────────────────────────────────────────────────────────────────────────

device.sigouts[OUT_CHANNEL].on(False)
print("\nOutput off. Done.")
