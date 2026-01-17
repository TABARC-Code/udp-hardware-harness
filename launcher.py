import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path

LUA_FILENAME = "drone_protocol.lua"
TOOL_FILENAME = "drone_tool.py"

def install_lua_dissector():
    print("[*] Checking Wireshark integration...")
    source = Path(__file__).parent / LUA_FILENAME
    
    if not source.exists():
        print(f"[!] Warning: {LUA_FILENAME} not found. Skipping Wireshark setup.")
        return

    home = Path.home()
    system = platform.system()
    dest_dir = None

    if system == "Windows":
        dest_dir = home / "AppData" / "Roaming" / "Wireshark" / "plugins"
    elif system == "Darwin": # Mac
        dest_dir = home / ".config" / "wireshark" / "plugins"
    else: # Linux
        dest_dir = home / ".config" / "wireshark" / "plugins"

    if dest_dir:
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy(source, dest_dir / LUA_FILENAME)
            print(f"    [+] Installed {LUA_FILENAME} to Wireshark plugins.")
        except Exception as e:
            print(f"    [-] Failed to install Wireshark plugin: {e}")

def run_scanner():
    print("\n" + "="*40)
    print("   DRONE / IOT HARDWARE SCANNER")
    print("="*40)
    
    default_ip = "192.168.10.1"
    target_ip = input(f"Target IP [{default_ip}]: ").strip()
    if not target_ip: target_ip = default_ip
        
    default_port = "8889"
    target_port = input(f"Target Port [{default_port}]: ").strip()
    if not target_port: target_port = default_port
        
    # Pass config via Env Vars to the main tool
    env = os.environ.copy()
    env["TARGET_IP"] = target_ip
    env["TARGET_PORT"] = target_port
    
    print(f"\n[*] Launching Scanner -> {target_ip}:{target_port}")
    print("[*] Press Ctrl+C to stop.\n")
    
    try:
        subprocess.run([sys.executable, TOOL_FILENAME], env=env)
    except KeyboardInterrupt:
        print("\n[*] Stopped.")
    except Exception as e:
        print(f"[!] Error: {e}")

if __name__ == "__main__":
    install_lua_dissector()
    run_scanner()
    input("\nPress Enter to exit...")
