import socket

def get_lan_ip() -> str:
    """Return the LAN IPv4 address of the default-route NIC, or 127.0.0.1 on failure."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # does not need to be reachable
            # 192.0.2.0 = TEST-NET-1-0, can never be reachable.
            s.connect(("192.0.2.0", 1)) 
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
