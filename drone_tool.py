import asyncio
import logging
import struct
import csv
import time
import os
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Tuple, Dict, Any, cast

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. HARDENED HARDWARE CLIENT
# ==============================================================================

class HardwareClient:
    def __init__(self, ip: str, port: int, timeout: float = 2.0):
        self.target: Tuple[str, int] = (ip, port)
        self.timeout = timeout
        self.transport: Optional[asyncio.DatagramTransport] = None
        self.protocol: Optional['HardwareClient.TransportProtocol'] = None
        self._rx_queue: asyncio.Queue[bytes] = asyncio.Queue()

    class TransportProtocol(asyncio.DatagramProtocol):
        def __init__(self, queue: asyncio.Queue[bytes], expected_peer: Tuple[str, int]):
            self.queue = queue
            self.expected_peer = expected_peer
            self.transport: Optional[asyncio.DatagramTransport] = None

        def connection_made(self, transport: asyncio.BaseTransport):
            self.transport = cast(asyncio.DatagramTransport, transport)

        def datagram_received(self, data: bytes, addr: Tuple[str, int]):
            if addr != self.expected_peer: return
            if not data: return
            self.queue.put_nowait(data)

        def error_received(self, exc):
            logger.error(f"Transport Error: {exc}")
        
        def connection_lost(self, exc):
            if exc: logger.warning(f"Connection lost: {exc}")

    async def connect(self) -> None:
        if self.transport: return
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: self.TransportProtocol(self._rx_queue, self.target),
            remote_addr=self.target,
        )
        self.transport = cast(asyncio.DatagramTransport, transport)
        self.protocol = cast(HardwareClient.TransportProtocol, protocol)
        logger.info(f"Connected to {self.target}")

    async def send_command(self, packet: bytes, retries: int = 2, expected_opcode: Optional[int] = None) -> Optional[bytes]:
        if not self.transport: await self.connect()

        for attempt in range(retries + 1):
            self._flush_queue()
            if self.transport: self.transport.sendto(packet)
            else: return None

            start_time = time.monotonic()
            while True:
                remaining_time = self.timeout - (time.monotonic() - start_time)
                if remaining_time <= 0: break

                try:
                    data = await asyncio.wait_for(self._rx_queue.get(), timeout=remaining_time)
                    if expected_opcode is None or len(data) < 3: return data
                    if data[2] == expected_opcode: return data
                except asyncio.TimeoutError: break 

        return None

    def _flush_queue(self) -> None:
        while not self._rx_queue.empty():
            try: self._rx_queue.get_nowait()
            except asyncio.QueueEmpty: break

    def close(self) -> None:
        if self.transport:
            self.transport.close()
            self.transport = None
            self.protocol = None
        self._flush_queue()

# ==============================================================================
# 2. PROTOCOL HANDLER
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
        for b in data: chk ^= b
        return chk

    @classmethod
    def build_packet(cls, opcode: int, payload: bytes = b"") -> bytes:
        length = 1 + len(payload)
        body = struct.pack("<BBB", cls.HEADER, length, opcode) + payload
        chk = cls.calculate_checksum(body)
        return body + struct.pack("<B", chk)

    @classmethod
    def parse_frame(cls, data: bytes) -> Frame:
        if not data: return Frame(0,0,0,b"",0, b"", False, "Empty Data")
        if len(data) < 4: return Frame(0,0,0,b"",0, data, False, f"Short ({len(data)})")

        header = data[0]
        length = data[1]
        expected_total = 1 + 1 + length + 1
        
        if len(data) < expected_total:
             return Frame(header, length, 0, b"", 0, data, False, f"Truncated")

        frame_data = data[:expected_total]
        trailing = data[expected_total:]
        
        opcode = frame_data[2]
        received_chk = frame_data[-1]
        payload = frame_data[3 : 3 + max(0, length - 1)]

        if header != cls.HEADER:
             return Frame(header, length, opcode, payload, received_chk, frame_data, False, "Bad Header", trailing)
        
        calc_chk = cls.calculate_checksum(frame_data[:-1])
        if calc_chk != received_chk:
            return Frame(header, length, opcode, payload, received_chk, frame_data, False, "Bad Checksum", trailing)

        return Frame(header, length, opcode, payload, received_chk, frame_data, True, "OK", trailing)

    @classmethod
    def decode_telemetry(cls, payload: bytes) -> Dict[str, Any]:
        fmt = "<BHfB"
        if len(payload) != struct.calcsize(fmt):
            return {"error": "size_mismatch", "raw": payload.hex()}
        try:
            bat, volt, alt, err = struct.unpack(fmt, payload)
            return {"battery": bat, "voltage": volt, "altitude": round(alt, 2), "errors": hex(err)}
        except Exception as e:
            return {"error": str(e), "raw": payload.hex()}

# ==============================================================================
# 3. SCANNER LOGIC
# ==============================================================================

class DroneScanner:
    def __init__(self, client: HardwareClient):
        self.client = client

    async def scan_opcodes(self, output_file="scan_results.csv"):
        logger.info("Starting Scan...")
        with open(output_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Opcode_Hex", "Status", "Rx_Len", "Rx_Opcode", 
                             "Rx_Payload_Hex", "Trailing", "Error", "RTT_ms"])
            
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
        logger.info(f"Scan complete: {output_file}")

async def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', datefmt='%H:%M:%S')
    target_ip = os.getenv("TARGET_IP", "127.0.0.1")
    target_port = int(os.getenv("TARGET_PORT", "8889"))
    
    client = HardwareClient(ip=target_ip, port=target_port, timeout=1.0)
    scanner = DroneScanner(client)
    try: await scanner.scan_opcodes("drone_scan.csv")
    finally: client.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: pass
