-- Wireshark Dissector for Drone Control Protocol
local p_drone = Proto("drone", "Drone Control Protocol")

-- Protocol Fields
local f_header   = ProtoField.uint8("drone.header", "Header", base.HEX)
local f_len      = ProtoField.uint8("drone.len", "Length", base.DEC)
local f_opcode   = ProtoField.uint8("drone.opcode", "Opcode", base.HEX)
local f_payload  = ProtoField.bytes("drone.payload", "Payload")
local f_checksum = ProtoField.uint8("drone.checksum", "Checksum", base.HEX)

local opcode_names = {
    [0x10] = "GET_STATUS",
    [0x11] = "GET_TELEMETRY",
    [0x20] = "SET_LED",
    [0xFF] = "REBOOT"
}

p_drone.fields = {f_header, f_len, f_opcode, f_payload, f_checksum}

function p_drone.dissector(buffer, pinfo, tree)
    local buf_len = buffer:len()
    if buf_len < 4 then return end

    -- Check Header (0x55)
    if buffer(0,1):uint() ~= 0x55 then return end

    pinfo.cols.protocol = "DRONE"
    local subtree = tree:add(p_drone, buffer(), "Drone Protocol")

    subtree:add(f_header, buffer(0,1))
    
    local len_val = buffer(1,1):uint()
    subtree:add(f_len, buffer(1,1))

    local opcode_val = buffer(2,1):uint()
    local op_name = opcode_names[opcode_val] or "UNKNOWN"
    subtree:add(f_opcode, buffer(2,1)):append_text(" (" .. op_name .. ")")
    pinfo.cols.info = "Op: " .. op_name

    -- Payload Calculation: Len = Opcode(1) + Payload(N)
    -- Total Packet = Header(1) + Len(1) + LenVal + Checksum(1)
    local payload_len = len_val - 1
    
    -- Payload starts at offset 3
    if payload_len > 0 and (3 + payload_len) < buf_len then
        subtree:add(f_payload, buffer(3, payload_len))
    end
    
    -- Checksum is generally at offset 3 + payload_len
    if (3 + payload_len) < buf_len then
        subtree:add(f_checksum, buffer(3 + payload_len, 1))
    end
end

-- Bind to standard UDP port (change 8889 if needed)
local udp_port = DissectorTable.get("udp.port")
udp_port:add(8889, p_drone)
