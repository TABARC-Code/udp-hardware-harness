
```python
import asyncio
import logging
import struct
import csv
import time
import os
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any, cast

# NOTE: Logging config is moved to __main__ to prevent side effects on import.
logger = logging.getLogger(__name__)

# ==============================================================================
# 1. HARDENED HARDWARE CLIENT
# ==============================================================================

class HardwareClient:
    """
    Asyncio UDP client.
    - Loop-safe queue usage.
    - Strict resource lifecycle management.
    - Prevents race conditions during scanning.
    """
    def __init__(self, ip: str, port: int, timeout: float = 2.0):
        self.target: Tuple[str, int] = (ip, port)
        self.timeout = timeout
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.protocol: Optional['HardwareClient.TransportProtocol'] = None
        self._rx_queue: asyncio.Queue[bytes] = asyncio.Queue()

    class TransportProtocol(asyncio.DatagramProtocol):
        """
        Protocol layer that filters traffic and manages the transport reference.
        """
        def __init__(self, queue: asyncio.Queue[bytes], expected_peer: Tuple[str, int]):
            self.queue = queue
            self.expected_peer = expected_peer
            self.transport: Optional[asyncio.DatagramTransport] = None

        def connection_made(self, transport: asyncio.BaseTransport):
            self.transport = cast(asyncio.DatagramTransport, transport)

        def datagram_received(self, data: bytes, addr: Tuple[str, int]):
            # Filter 1: Peer IP/Port check
            if addr != self.expected_peer:
                return
            # Filter 2: Drop 0-byte keepalives
            if not data:
                return
            self.queue.put_nowait(data)

        def error_received(self, exc):
            logger.error(f"Transport Error: {exc}")
        
        def connection_lost(self, exc):
            if exc:
                logger.warning(f"Connection lost: {exc}")

    async def connect(self) -> None:
        if self.transport:
            return
        
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: self.TransportProtocol(self._rx_queue, self.target),
            remote_addr=self.target,
        )
        self.transport = cast(asyncio.DatagramTransport, transport)
        self.protocol = cast(HardwareClient.TransportProtocol, protocol)
        logger.info(f"Connected to {self.target}")

    async def send_command(self, packet: bytes, retries: int = 2, expected_opcode: Optional[int] = None) -> Optional[bytes]:
        """
        Sends a packet and waits for a response.
        
        Args:
            packet: Raw bytes to send.
            retries: Number of retry attempts on timeout.
            expected_opcode: If set, discard received packets that do not contain 
                             this opcode (at offset 2). Mitigates race conditions.
        """
        if not self.transport:
            await self.connect()

        for attempt in range(retries + 1):
            self._flush_queue() # Clear pre-send
            
            if self.transport:
                self.transport.sendto(packet)
            else:
                return None

            # Wait loop to filter stale/wrong packets
            start_time = time.monotonic()
            while True:
                remaining_time = self.timeout - (time.monotonic() - start_time)
                if remaining_time <= 0:
                    break # Timeout for this attempt

                try:
                    data = await asyncio.wait_for(self._rx_queue.get(), timeout=remaining_time)
                    
                    # If we don't care about opcode, or packet is too short to check, return data
                    if expected_opcode is None or len(data) < 3:
                        return data
                    
                    # Opcode check (assuming offset 2 based on DroneProtocol)
                    rx_opcode = data[2]
                    if rx_opcode == expected_opcode:
                        return data
                    else:
                        logger.debug(f"Dropped mismatched opcode 0x{rx_opcode:02X} (Expected 0x{expected_opcode:02X})")
                
                except asyncio.TimeoutError:
                    break 

            # If we exit the while loop, we timed out for this attempt
            if attempt < retries:
                logger.debug(f"Timeout (Attempt {attempt+1}/{retries+1}), retrying...")

        logger.warning(f"Cmd failed after {retries+1} attempts.")
        return None

    def _flush_queue(self) -> None:
        while not self._rx_queue.empty():
            try:
                self._rx_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def close(self) -> None:
        if self.transport:
            self.transport.close()
            self.transport = None
            self.protocol = None
        self._flush_queue()

# ==============================================================================
# 2. ROBUST PROTOCOL HANDLER
# ==============================================================================

class OpCode(int, Enum):
    GET_STATUS    = 0x10
    GET_TELEMETRY = 0x11
    SET_LED       = 0x20
    UNKNOWN       = 0x00 

@dataclass(frozen=True)
class Frame:
    header: int
    length: int
    opcode: int
    payload: bytes
    checksum: int
    raw: bytes
    is_valid: bool
    error_msg: str
    trailing_data: bytes = field(default_factory=bytes)

class DroneProtocol:
    HEADER = 0x55

    @staticmethod
    def calculate_checksum(data: bytes) -> int:
        chk = 0
        for b in data:
            chk ^= b
        return chk

    @classmethod
    def build_packet(cls, opcode: int, payload: bytes = b"") -> bytes:
        length = 1 + len(payload)
        # Struct: Header, Len, Opcode
        body = struct.pack("<BBB", cls.HEADER, length, opcode) + payload
        chk = cls.calculate_checksum(body)
        return body + struct.pack("<B", chk)

    @classmethod
    def parse_frame(cls, data: bytes) -> Frame:
        """
        Parses raw bytes into a Frame. 
        Returns payload/opcode even on checksum failure to aid RE.
        """
        if not data:
            return Frame(0,0,0,b"",0, b"", False, "Empty Data")

        if len(data) < 4:
            return Frame(0,0,0,b"",0, data, False, f"Frame too short ({len(data)})")

        header = data[0]
        header_ok = (header == cls.HEADER)

        length = data[1]
        # Assumed Total size = Header(1) + LenByte(1) + LenVal + Checksum(1)
        expected_total = 1 + 1 + length + 1
        
        if len(data) < expected_total:
             return Frame(header, length, 0, b"", 0, data, False, 
                          f"Truncated: Exp {expected_total} Got {len(data)}")

        frame_data = data[:expected_total]
        trailing = data[expected_total:]
        
        opcode = frame_data[2]
        received_chk = frame_data[-1]
        
        # Payload extraction happens BEFORE checksum validation
        payload_len = max(0, length - 1)
        payload = frame_data[3 : 3 + payload_len]

        body = frame_data[:-1] 
        calc_chk = cls.calculate_checksum(body)
        
        if not header_ok:
             return Frame(header, length, opcode, payload, received_chk, frame_data, False, 
                          f"Bad Header 0x{header:02X}", trailing)

        if calc_chk != received_chk:
            return Frame(header, length, opcode, payload, received_chk, frame_data, False, 
                         f"Bad Checksum: Rx {received_chk:02X} != Calc {calc_chk:02X}", trailing)

        return Frame(header, length, opcode, payload, received_chk, frame_data, True, "OK", trailing)

    @classmethod
    def decode_telemetry(cls, payload: bytes) -> Dict[str, Any]:
        """Strict telemetry decoder."""
        fmt = "<BHfB"
        expected = struct.calcsize(fmt)
        if len(payload) != expected:
            return {"error": "size_mismatch", "raw": payload.hex()}
        
        try:
            bat, volt, alt, err = struct.unpack(fmt, payload)
            return {
                "battery": bat,
                "voltage": volt,
                "altitude": round(alt, 2),
                "errors": hex(err)
            }
        except Exception as e:
            return {"error": str(e), "raw": payload.hex()}

# ==============================================================================
# 3. SCANNER LOGIC
# ==============================================================================

class DroneScanner:
    def __init__(self, client: HardwareClient):
        self.client = client

    async def scan_opcodes(self, output_file="scan_results.csv"):
        logger.info("Starting Opcode Fuzz/Scan...")
        
        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Opcode_Hex", "Status", "Rx_Len", "Rx_Opcode", 
                             "Rx_Payload_Hex", "Trailing_Bytes", "Error_Msg", "RTT_ms"])
            
            for op in range(0, 256):
                tx_pkt = DroneProtocol.build_packet(op)
                
                start = time.perf_counter()
                rx_bytes = await self.client.send_command(tx_pkt, retries=1, expected_opcode=op)
                duration = (time.perf_counter() - start) * 1000

                if not rx_bytes:
                    writer.writerow([f"0x{op:02X}", "TIMEOUT", 0, "", "", "", "", f"{duration:.2f}"])
                    await asyncio.sleep(0.02)
                    continue

                frame = DroneProtocol.parse_frame(rx_bytes)
                log_status = "VALID" if frame.is_valid else "INVALID_FMT"
                
                writer.writerow([
                    f"0x{op:02X}", log_status, len(frame.raw), f"0x{frame.opcode:02X}",
                    frame.payload.hex().upper(), len(frame.trailing_data),
                    frame.error_msg, f"{duration:.2f}"
                ])
                
                if frame.is_valid:
                    logger.info(f"Hit: 0x{op:02X} -> Payload: {frame.payload.hex().upper()}")
                
                await asyncio.sleep(0.02)
        
        logger.info(f"Scan complete. Results saved to {output_file}")

# ==============================================================================
# MAIN ENTRY
# ==============================================================================

async def main():
    logging.basicConfig(
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    
    target_ip = os.getenv("TARGET_IP", "127.0.0.1")
    target_port = int(os.getenv("TARGET_PORT", "8889"))

    logger.info(f"Target: {target_ip}:{target_port}")
    
    client = HardwareClient(ip=target_ip, port=target_port, timeout=1.0)
    scanner = DroneScanner(client)

    try:
        await scanner.scan_opcodes("drone_scan.csv")
    finally:
        logger.info("Closing client...")
        client.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
