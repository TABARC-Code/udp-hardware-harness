import asyncio
import threading
import time
import collections
import logging
import os
from typing import Deque, Dict, Any

# Third-party UI libs
import dash
from dash import dcc, html
from dash.dependencies import Input, Output
import plotly.graph_objs as go
import pandas as pd

# Import our existing harness
from drone_tool import HardwareClient, DroneProtocol, OpCode

# Disable the noisy Dash logging
logging.getLogger('werkzeug').setLevel(logging.ERROR)

# ==============================================================================
# 1. STATE MANAGEMENT (The "Ring Buffer")
# ==============================================================================

class TelemetryStore:
    """
    Thread-safe storage for the last N seconds of data.
    Acts as the bridge between the Asyncio Poller and the Dash Webserver. Still a wrk in progess
    """
    def __init__(self, max_len=100):
        self.lock = threading.Lock()
        self.max_len = max_len
        
        # We store timestamps and values in separate deques for easy plotting
        self.times: Deque[float] = collections.deque(maxlen=max_len)
        self.battery: Deque[int] = collections.deque(maxlen=max_len)
        self.altitude: Deque[float] = collections.deque(maxlen=max_len)
        self.voltage: Deque[int] = collections.deque(maxlen=max_len)
        
        # Start time for relative X-axis
        self.start_time = time.time()

    def add_reading(self, data: Dict[str, Any]):
        with self.lock:
            # Calculate relative time (seconds since start)
            t = time.time() - self.start_time
            self.times.append(t)
            
            # Extract keys safely (default to 0 if decoding failed)
            self.battery.append(data.get("battery", 0))
            self.altitude.append(data.get("altitude", 0.0))
            self.voltage.append(data.get("voltage", 0))

    def get_dataframe(self):
        """Returns a Pandas DataFrame for Plotly to consume."""
        with self.lock:
            return pd.DataFrame({
                "Time": list(self.times),
                "Battery": list(self.battery),
                "Altitude": list(self.altitude),
                "Voltage": list(self.voltage)
            })

# Global instance
store = TelemetryStore(max_len=60) # Keep last 60 readings

# ==============================================================================
# 2. BACKGROUND POLLER (The "Harness")
# ==============================================================================

def run_async_poller(target_ip, target_port):
    """
    Runs in a separate thread.
    Constantly asks the drone for OpCode 0x11 (GET_TELEMETRY).
    """
    async def poll_loop():
        client = HardwareClient(ip=target_ip, port=target_port, timeout=0.5)
        print(f"[*] Poller connected to {target_ip}:{target_port}")
        
        try:
            # Build the command once
            cmd = DroneProtocol.build_packet(OpCode.GET_TELEMETRY)
            
            while True:
                # 1. Send & Wait
                data = await client.send_command(cmd, retries=0, expected_opcode=OpCode.GET_TELEMETRY)
                
                if data:
                    # 2. Parse
                    frame = DroneProtocol.parse_frame(data)
                    if frame.is_valid:
                        telemetry = DroneProtocol.decode_telemetry(frame.payload)
                        if "error" not in telemetry:
                            # 3. Push to Store
                            store.add_reading(telemetry)
                        else:
                            print(f"[!] Decode Error: {telemetry}")
                
                # Pace the polling (10Hz)
                await asyncio.sleep(0.1)
                
        except Exception as e:
            print(f"[!] Poller crashed: {e}")
        finally:
            client.close()

    # Asyncio requires a loop in this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(poll_loop())

# ==============================================================================
# 3. DASHBOARD UI (The "Grapher")
# ==============================================================================

app = dash.Dash(__name__, title="Drone Telemetry")

# Dark Theme Layout
app.layout = html.Div(style={'backgroundColor': '#111', 'color': '#fff', 'minHeight': '100vh', 'padding': '20px'}, children=[
    
    html.H2("Hardware Telemetry Monitor", style={'textAlign': 'center', 'fontFamily': 'monospace'}),
    
    # Status Bar
    html.Div(id='live-text', style={'textAlign': 'center', 'marginBottom': '20px', 'fontFamily': 'monospace', 'color': '#0f0'}),

    # Graphs
    html.Div([
        # Graph 1: Altitude
        dcc.Graph(id='graph-altitude', style={'height': '300px'}),
        # Graph 2: Battery & Voltage
        dcc.Graph(id='graph-power', style={'height': '300px'}),
    ]),

    # The Heartbeat (Updates UI every 1000ms)
    dcc.Interval(
        id='interval-component',
        interval=1000, 
        n_intervals=0
    )
])

@app.callback(
    [Output('graph-altitude', 'figure'),
     Output('graph-power', 'figure'),
     Output('live-text', 'children')],
    [Input('interval-component', 'n_intervals')]
)
def update_metrics(n):
    df = store.get_dataframe()
    
    if df.empty:
        return dash.no_update, dash.no_update, "Waiting for data..."

    # Common layout style for dark mode
    layout_cfg = dict(
        plot_bgcolor='#111',
        paper_bgcolor='#111',
        font=dict(color='#fff'),
        margin=dict(l=40, r=20, t=30, b=30),
        xaxis=dict(showgrid=True, gridcolor='#333', title='Seconds'),
        yaxis=dict(showgrid=True, gridcolor='#333')
    )

    # 1. Altitude Plot
    fig_alt = go.Figure()
    fig_alt.add_trace(go.Scatter(
        x=df['Time'], y=df['Altitude'],
        mode='lines+markers', name='Altitude (m)',
        line=dict(color='#00ccff', width=2)
    ))
    fig_alt.update_layout(title="Altitude", **layout_cfg)

    # 2. Power Plot (Dual Axis logic simplified to two traces)
    fig_pwr = go.Figure()
    fig_pwr.add_trace(go.Scatter(
        x=df['Time'], y=df['Battery'],
        mode='lines', name='Battery %',
        line=dict(color='#00ff00', width=2)
    ))
    fig_pwr.add_trace(go.Scatter(
        x=df['Time'], y=df['Voltage'],
        mode='lines', name='Voltage (mV)',
        line=dict(color='#ff9900', width=2, dash='dot')
    ))
    fig_pwr.update_layout(title="Power System", **layout_cfg)

    # 3. Text Status
    latest = df.iloc[-1]
    status_txt = f"LATEST | BAT: {int(latest['Battery'])}% | VOLT: {int(latest['Voltage'])}mV | ALT: {latest['Altitude']:.2f}m"

    return fig_alt, fig_pwr, status_txt

# ==============================================================================
# MAIN ENTRY
# ==============================================================================

if __name__ == '__main__':
    # 1. Config
    target_ip = os.getenv("TARGET_IP", "127.0.0.1")
    target_port = int(os.getenv("TARGET_PORT", "8889"))
    
    print("="*40)
    print("   LIVE TELEMETRY DASHBOARD")
    print(f"   Target: {target_ip}:{target_port}")
    print("   GUI:    http://127.0.0.1:8050")
    print("="*40)

    # 2. Start the Poller Thread reinder (Daemon dies when the main dies)
    t = threading.Thread(target=run_async_poller, args=(target_ip, target_port), daemon=True)
    t.start()

    # 3. Start the Web Server (Blocks)
    app.run_server(debug=False, port=8050)
