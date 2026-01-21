# Usage Guide & Technical Notes

This section is about making sense of the data the tool produces. If you only want to fire it up and grab a CSV, the README is enough. If you’re trying to work out *why* half the table says “Bad Checksum”, read on.

Short version: the tool was made simple on purpose. The complexity lives in the protocol, not the code. so yea.

## Architecture

The tool is split into three layers. That separation is deliberate. UDP transport code ages well. Device logic does not. Keeping them apart means you can rip out the drone-specific parts and reuse the rest without starting again.

1. **HardwareClient**
   This is the bottom layer. It owns the socket, the `asyncio` loop, retries, and timeouts. It also filters out background noise like broadcast packets so higher layers only see traffic that plausibly belongs to the target device.

2. **DroneProtocol**
   This is the codec. It knows how to pack frames into bytes and unpack bytes back into fields. Header layout, length handling, and checksum logic all live here. If packets are arriving but failing validation, this is the first place to look.

3. **Scanner**
   This is the application logic. It iterates through opcode values, sends requests, records responses, and writes the CSV. It does very little thinking, by design.

## Usage ##

####1. UDP Drone Scanning####

* **python hardware_tool.py udp --ip 192.168.10.1 --scan**

####2. Bluetooth Walking####

* **python hardware_tool.py ble --mac AA:BB:CC:11:22:33 --scan** 

####3. Serial Auto-Baud####

---------

# Windows
python hardware_tool.py serial --port COM3 --auto-baud

# Linux
python hardware_tool.py serial --port /dev/ttyUSB0 --auto-baud

4. TCP Proxy
Listen on local port 8888, forward to remote server 1.2.3.4 port 80.

python hardware_tool.py tcp --local-port 8888 --remote-ip 1.2.3.4 --remote-port 80
Then configure your device (via DNS spoofing or config change) to connect to your IP.  

## The CSV output

A scan produces `drone_scan.csv`. Open it in a spreadsheet and start filtering. You’re looking for patterns, not individual rows.

The most useful columns are these.

### Status

This tells you how far each opcode got.

* `VALID`
  The device replied and the checksum matched. You have a confirmed command.

* `INVALID_FMT`
  The device replied, but the response didn’t match the structure defined in `DroneProtocol`. This usually means the device sent a text error, a debug blob, or something your parser doesn’t understand yet.

* `TIMEOUT`
  No response. This is the default outcome for most opcodes and isn’t a failure in itself.

### Rx_Len

The length of the response in bytes. This is a strong signal.

If you see several `VALID` entries with the same opcode range and different lengths, group them. Response length often maps directly to function families or data types.

### Trailing_Bytes

Pay attention to this.

If this value is non-zero, the packet contained more data than its own length field declared. That extra data often contains strings, version info, or leftover debug output. It’s worth inspecting closely.

## Using Wireshark

The launcher script tries to copy `drone_protocol.lua` into Wireshark’s plugin directory automatically. (Any issues 

If it works, you’ll see a protocol called `DRONE` in Wireshark.

If it doesn’t, install it manually:

1. Open Wireshark.
2. Go to **Help -> About Wireshark -> Folders**.
3. Open the folder labelled **Personal Lua Plugins**.
4. Copy `drone_protocol.lua` into that directory.
5. Press `Ctrl+Shift+L` to reload Lua plugins.

### Why the dissector matters

The Python code tells you that a packet arrived. Wireshark tells you what it actually contains.

When you see an odd response in the CSV, find the packet in Wireshark and look at the decoded fields. With the dissector enabled, you should see something like:

* Header: `0x55`
* Length: `0x04`
* Opcode: `0x00`
* Checksum: `0x11`

This makes it much easier to confirm whether your protocol definition matches what the device is really sending, rather than what you expect it to send.

## Modifying the protocol

You will almost certainly need to change the protocol definition. Manufacturers rarely agree on anything, and sometimes don’t even agree with themselves across firmware versions.

Open `drone_tool.py` and find `class DroneProtocol`.

##### Common changes: #####

* **Header**
  Update `HEADER = 0x55` to match the device’s sync byte or magic value.

* **Checksum**
  Review `calculate_checksum`. The current implementation is a simple XOR-style checksum. If the device uses CRC16, CRC32, or something custom, replace it. Also confirm whether the header byte is included in the checksum range. The current code assumes it is not.

* **Frame layout**
  Check `build_packet` and `parse_frame`. If the device orders fields differently, move things around until the on-wire layout matches what you see in Wireshark.

Use `struct.pack` for building frames. It handles endianness properly (`<` for little-endian, `>` for big-endian) and avoids off-by-one errors that are easy to introduce with manual bit-twiddling.

## Troubleshooting

### Everything times out

If every opcode results in `TIMEOUT`, check the basics first:

1. The IP address and port are correct.
2. The OS firewall isn’t blocking Python.
3. The device doesn’t require a handshake or initial text command before accepting binary packets.
4. Figure it out.

### Everything fails checksum

If every response reports a bad checksum, the problem is almost always in the maths or the byte range:

* The checksum algorithm is wrong.
* The checksum is calculated over the wrong fields.
* The device includes the header byte and your code does not.
* Less commonly, the device uses a rolling value or session state.

Start by comparing the raw bytes in Wireshark against what `calculate_checksum` expects. If the fields line up but validation fails, that’s where the error lives.
