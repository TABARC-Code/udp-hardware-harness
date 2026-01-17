import asyncio
import struct
import logging
import random

# Reuse the Protocol logic from the tool so the mock matches the client
# This is critical. It listens on port 8889 and replies to the GET_TELEMETRY opcode with valid data. 
# This proves to you/yourr team that the scanner, the protocol definitions, and the Wireshark dissector 
# are all working correctly before they go into the field.
HEADER = 0x55
PORT = 8889

logging.basicConfig(level=logging.INFO, format='%(asctime)s - MOCK - %(message)s')

class MockDrone(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        self.transport = transport
        logging.info(f"Mock Drone listening on 127.0.0.1:{PORT}")

    def datagram_received(self, data, addr):
        if len(data) < 4:
            return # Garbage

        if data[0] != HEADER:
            return # Not for us

        # Parse request
        # [Head][Len][Op][...][Chk]
        opcode = data[2]
        logging.info(f"Rx Opcode: 0x{opcode:02X} from {addr}")

        # Simulate processing delay
        # await asyncio.sleep(0.01) # Can't await in sync callback, generally fast enough

        response = self.handle_command(opcode)
        if response:
            self.transport.sendto(response, addr)
            logging.info(f"Tx Reply: {response.hex().upper()}")

    def handle_command(self, opcode):
        # 1. GET_TELEMETRY (0x11) -> Return valid battery/altitude
        if opcode == 0x11:
            # Payload: Battery(U8), Voltage(U16), Alt(f), Err(U8)
            # 85% battery, 14000mV, 15.5m alt, 0 errors
            payload = struct.pack("<BHfB", 85, 14000, 15.5, 0)
            return self.build_packet(opcode, payload)
        
        # 2. GET_STATUS (0x10) -> Return simple "Ready" (0x01)
        elif opcode == 0x10:
            payload = b'\x01'
            return self.build_packet(opcode, payload)

        # 3. UNKNOWN -> Don't reply (Simulate timeout)
        # Or reply with error if you want to test that path
        return None

    def build_packet(self, opcode, payload):
        length = 1 + len(payload)
        # Header, Len, Opcode, Payload
        body = struct.pack("<BBB", HEADER, length, opcode) + payload
        checksum = 0
        for b in body:
            checksum ^= b
        return body + struct.pack("B", checksum)

async def main():
    loop = asyncio.get_running_loop()
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: MockDrone(),
        local_addr=('127.0.0.1', PORT)
    )
    
    try:
        await asyncio.Future() # Run forever
    except asyncio.CancelledError:
        pass
    finally:
        transport.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
