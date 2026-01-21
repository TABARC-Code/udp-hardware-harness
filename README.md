# udp-hardware-harness
This repository contains a set of tools designed to help reverse engineer these connectionless UDP protocols. It is tuned for devices like drones, IoT relays and WiFi cameras where packets are often lost and the device doesn't always respond.

---

## UDP Hardware Scanner & Protocol Harness

Hardware protocol documentation is routinely wrong, outdated, or missing altogether. That’s not an edge case, it’s the norm. You’re handed a PDF that no longer matches the firmware, or worse, a closed mobile app and told to “just use that”.

This repo exists to deal with that reality.

It contains a small set of tools designed to reverse engineer **connectionless UDP protocols**, particularly on devices that are unreliable by design. Drones, IoT relays, WiFi cameras. Packet loss is common. Responses are inconsistent. Silence is normal.

This is not a framework. It’s a **harness**.

It keeps the socket alive, manages retries, absorbs malformed packets, and avoids falling over when the device does something unexpected. The goal is simple: stay up long enough to learn something.

### What’s included

#### Core Tools
* drone_tool.py: The logic. It handles the asyncio loop, packet queueing, and CSV logging. Written defensively because network buffers are untrustworthy.
* launcher.py: A wrapper script. It installs the Lua plugin and prompts for the IP address so you don't have to edit the code to change a target.
##### Visualisation & Testing
* dashboard.py: A live telemetry grapher. It polls the device and visualises sensor data (Battery, Altitude, Voltage) in real-time via a web browser.
* mock_device.py: A "Fake Drone". It listens on 127.0.0.1 and replies to telemetry commands. Use this to verify the tools work before going into the field.
##### Utilities
* drone_protocol.lua: A Wireshark dissector. Makes Wireshark actually understand the packets.
* run_windows.bat: One-click launcher for Windows.
* run_unix.sh: Wrapper script for Linux/macOS.

  -------
  ## What is included

*   **`drone_tool.py`**: The logic. It handles the `asyncio` loop, packet queueing and CSV logging. It is written defensively as I don't trust network buffers.
*   **`drone_protocol.lua`**: A Wireshark dissector. Staring at raw hex bytes in the "Data" pane is difficult. This makes Wireshark understand the packets.
*   **`launcher.py`**: A wrapper script. It installs the Lua plugin and prompts for the IP address so you don't have to edit the code to change a target.
*   **`run_windows.bat`**: A script for Windows users to launch the tool easily.
*   **`run_unix.sh`**: A wrapper for Linux and macOS users.

## Requirements

*   **1. Python 3.8+**. I stuck to the standard library (`asyncio`, `struct`, `socket`) to avoid dependency hell. `pip` installs can be unreliable on some field laptops.
*   **2. Wireshark**. You don't strictly need it to run the scan, but if you are doing RE work without it you are making life difficult for yourself. just run it.
*   **3. Dependencies**
        The Core Scanner uses the standard library only.
        The Dashboard requires extra libraries. Install them via:
  ip install -r requirements.txt

## Quick Start: The Scanner (Hardware Discovery)

### Quick Start

1.  Plug in the device. Connect to its WiFi AP if needed.

2.  **Windows Users**:
    *   Double-click `run_windows.bat`.

3.  **Linux / Mac Users**:
    *   You must make the script executable first. Open a terminal and run:
        ```bash
        chmod +x run_unix.sh
        ```
    *   Then launch it:
        ```bash
        ./run_unix.sh
        ```

4.  Enter the IP and Port when prompted.
    *   Common default: 192.168.10.1 port 8889.

5.  Watch the logs.

The tool runs a "Scan Mode" by default. It fires opcodes `0x00` through `0xFF` at the target and records the response to a CSV file.

## Requirements

* **Python 3.8+**
  Standard library only. `asyncio`, `socket`, `struct`. No dependencies, no virtualenvs, no `pip` roulette on half-locked field laptops.

* **Wireshark iNTERGRATON nOW**
  Not strictly required to run the scan, but if you’re doing protocol RE without it, you’re choosing unnecessary pain.

  ###uPDATE###
* The launcher script attempts to copy drone_protocol.lua to your Wireshark plugins folder automatically.
- If it fails (due to permissions), install it manually:
- Open Wireshark -> Help -> About Wireshark -> Folders.
- Open the Personal Lua Plugins folder.
- copy drone_protocol.lua into that folder.
- Press Ctrl+Shift+L in Wireshark to reload.
- You will now see a protocol named DRONE in your packet captures.

## Quick start

1. Power the device and connect to its WiFi AP if required.
2. Run `run_windows.bat` on Windows, or `python3 launcher.py` on Linux or macOS.
3. Enter the target IP address and port.
   *Common default: `192.168.10.1`, port `8889`.*
4. Watch the logs.

By default the tool runs in **Scan Mode**. It iterates opcodes `0x00` through `0xFF`, sends them to the target, and records whatever comes back to a CSV file for later analysis.

## Design decisions

The code is deliberately verbose. That’s just my style with this one.
- Explicit State: I don't use clever one-liners. When debugging protocols, clarity is better than brevity.
- The Queue: UDP isn't a stream, it's a bucket of messages. I use an asyncio.Queue to decouple receiving from processing to prevent packet loss.
- Strict Typing: Python type hints are used to ensure don't accidentally mix up hex strings and raw bytes.

* **Explicit state**
  When you’re debugging a protocol that depends on a checksum calculated over a specific byte range, it matters that you can see exactly where that range begins and ends.

* **The queue**
  UDP is not a stream. It’s a pile of discrete messages. An `asyncio.Queue` decouples reception from processing so packets aren’t dropped while data is being written to disk.

* **Strict typing**
  Type hints are used throughout. Future-you will appreciate being reminded that `payload` is `bytes`, not a `str`, six months down the line. i did this so I can work it out afrer leaving a project half done.

* **Quick Start: The Dashboard (Live Visualisation)**

 Once you know the device responds to Opcode 0x11 (Get Telemetry), use the dashboard to watch the data.
 1. Open a terminal.
 2. Run the dashboard:

     python dashboard.py
     
_(Note: You can override the target IP by setting the TARGET_IP environment variable)._
Open your web browser to: http://127.0.0.1:8050.

* ### Why use this? ###
  
It helps identify unknown bytes. If you see a graph spike when you physically tilt the hardware, you have identified the accelerometer byte in the payload.

## Testing without Hardware (The Mock Device)
If you are at your desk and want to test the dashboard, use the Mock Device.

1. Open Terminal 1 and run the fake drone:
    python mock_device.py

2. Open Terminal 2 and run the dashboard:
        python dashboard.py

3. Open the browser. You should see simulated altitude and battery data appearing on the graphs.

## Liability

Be careful what you send.

If you transmit a command that tells a drone to cut its motors at altitude, that outcome is on you. This tool does not enforce safety. It sends byte info , data infp.

Use common sense. If you’re testing on a desk, remove the propellers. dont ask...

## Testing

There are no unit tests yet. Mocking `asyncio.DatagramTransport` is difficult and I haven't had time to set it up properly.

## Licence

MIT. Use it as you see fit.
