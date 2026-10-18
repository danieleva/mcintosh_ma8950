import asyncio
import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

try:
    import serial_asyncio
except ImportError:
    serial_asyncio = None

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 5.0 # Seconds to wait for a connection or response
BUFFER_SIZE = 1024

# Translation tables for input sources
SOURCE_MAPPING = {
    "1": "BAL 1",
    "2": "UNBAL 1",
    "3": "UNBAL 2",
    "4": "UNBAL 3",
    "5": "UNBAL 4",
    "6": "UNBAL 5",
    "7": "UNBAL 6",
    "8": "MM PHONO",
    "9": "MC PHONO",
    "10": "COAX 1",
    "11": "COAX 2",
    "12": "OPTI 1",
    "13": "OPTI 2",
    "14": "USB",
    "15": "MCT",
    "16": "HDMI",
}

# Reverse mapping to look up command IDs from human-readable names
REVERSE_SOURCE_MAPPING = {v: k for k, v in SOURCE_MAPPING.items()}

class McIntoshMA8950API:
    """
    Asynchronous interface for controlling a McIntosh MA8950 Amplifier.
    Supports both TCP/IP and Serial port connections.
    """

    def __init__(self, port_url: str, baudrate: int = 115200):
        """Initialize the McIntosh API."""
        self.port_url = port_url
        self.baudrate = baudrate
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._lock = asyncio.Lock()

        self._is_tcp = False
        self.host = None
        self.port = None

        if self.port_url.startswith("socket://") or self.port_url.startswith("tcp://"):
            parsed = urlparse(self.port_url)
            self._is_tcp = True
            self.host = parsed.hostname
            self.port = parsed.port

    async def connect(self) -> bool:
        """Establish a connection to the amplifier (TCP or Serial)."""
        if self._connected:
            return True

        try:
            _LOGGER.debug(f"Attempting to connect to McIntosh MA8950 at {self.port_url}")
            
            if self._is_tcp:
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self.host, self.port),
                    timeout=TIMEOUT
                )
            else:
                if serial_asyncio is None:
                    _LOGGER.error("pyserial-asyncio is required for serial connections.")
                    return False
                
                self._reader, self._writer = await asyncio.wait_for(
                    serial_asyncio.open_serial_connection(url=self.port_url, baudrate=self.baudrate),
                    timeout=TIMEOUT
                )
                
            self._connected = True
            _LOGGER.info(f"Successfully connected to McIntosh MA8950 via {self.port_url}.")
            return True
        except asyncio.TimeoutError:
            _LOGGER.error(f"Connection to {self.port_url} timed out.")
            return False
        except Exception as e:
            _LOGGER.error(f"Unexpected error connecting to McIntosh MA8950: {e}")
            return False

    async def disconnect(self):
        """Close the connection."""
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                _LOGGER.warning(f"Error while disconnecting: {e}")
            finally:
                self._reader = None
                self._writer = None
                self._connected = False
                _LOGGER.debug("Disconnected from McIntosh MA8950.")

    async def send_command(self, command: str) -> Optional[str]:
        """Send a text command to the amplifier and read the response."""
        if not self._connected:
            success = await self.connect()
            if not success:
                return None

        async with self._lock:
            try:
                if not command.endswith('\r'):
                    command += '\r'

                _LOGGER.debug(f"Sending command: {command.strip()}")
                self._writer.write(command.encode('utf-8'))
                await self._writer.drain()

                response_bytes = await asyncio.wait_for(
                    self._reader.readuntil(b'\r'),
                    timeout=TIMEOUT
                )
                
                response = response_bytes.decode('utf-8').strip()
                _LOGGER.debug(f"Received response: {response}")
                return response

            except (asyncio.TimeoutError, asyncio.IncompleteReadError) as e:
                _LOGGER.error(f"Connection issue during communication: {e}")
                await self.disconnect()
                return None
            except Exception as e:
                _LOGGER.error(f"Error sending command: {e}")
                await self.disconnect()
                return None

    async def turn_on(self) -> bool:
        """Turn on the amplifier."""
        response = await self.send_command("PWR 1")
        if response and "PWR 1" in response:
            return True
        return False

    async def turn_off(self) -> bool:
        """Turn off the amplifier."""
        response = await self.send_command("PWR 0")
        if response and "PWR 0" in response:
            return True
        return False

    async def set_volume(self, volume: int) -> bool:
        """Set the volume level."""
        response = await self.send_command(f"VOL {volume}")
        if response and "VOL" in response:
            return True
        return False

    async def select_source(self, source: str) -> bool:
        """Select the input source using human-readable names."""
        # Translate Home Assistant name (e.g. "BAL 1") to amp command (e.g. "1")
        amp_command = REVERSE_SOURCE_MAPPING.get(source, source)
        
        _LOGGER.info(f"Setting McIntosh MA8950 source to {source} (Command: {amp_command})")
        response = await self.send_command(f"INP {amp_command}")
        
        if response and "INP" in response:
            return True
        return False

    async def get_status(self) -> dict:
        """Read the current status of the amplifier."""
        status = {}
        
        pwr_resp = await self.send_command("PWR ?")
        if pwr_resp:
            status["power"] = "PWR 1" in pwr_resp

        vol_resp = await self.send_command("VOL ?")
        if vol_resp and vol_resp.startswith("VOL "):
            try:
                status["volume"] = int(vol_resp.split(" ")[1])
            except ValueError:
                pass

        inp_resp = await self.send_command("INP ?")
        if inp_resp and inp_resp.startswith("INP "):
            parts = inp_resp.split(" ", 1)
            if len(parts) > 1:
                raw_source = parts[1].strip()
                # Translate amp response (e.g. "1") to Home Assistant name (e.g. "BAL 1")
                status["source"] = SOURCE_MAPPING.get(raw_source, raw_source)

        return status