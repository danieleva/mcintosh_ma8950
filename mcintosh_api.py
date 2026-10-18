import asyncio
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urlparse

import serialx

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 5.0 # Seconds to wait for a connection or response
BUFFER_SIZE = 1024

# Translation tables for input sources
SOURCE_MAPPING = {
    "U": "Next Input",
    "D": "Previous Input",
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
    "16": "HDMI (DA2 only)",
}

REVERSE_SOURCE_MAPPING = {v: k for k, v in SOURCE_MAPPING.items()}

class McIntoshMA8950API:
    """
    Asynchronous interface for controlling a McIntosh MA8950 Amplifier.
    Supports both TCP/IP and Serial port connections.
    """

    def __init__(self, port_url: str, baudrate: int = 115200):
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
                self._reader, self._writer = await asyncio.wait_for(
                    serialx.open_serial_connection(url=self.port_url, baudrate=self.baudrate),
                    timeout=TIMEOUT
                )
                
            self._connected = True
            _LOGGER.info(f"Successfully connected to McIntosh MA8950 via {self.port_url}.")
            return True
        except Exception as e:
            _LOGGER.error(f"Unexpected error connecting to McIntosh MA8950: {e}")
            return False

    async def disconnect(self):
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
        async with self._lock:
            if not self._connected or not self._writer:
                success = await self.connect()
                if not success:
                    return None

            try:
                if self._reader:
                    try:
                        while True:
                            stale_bytes = await asyncio.wait_for(self._reader.read(BUFFER_SIZE), timeout=0.05)
                            if not stale_bytes:
                                break
                    except (asyncio.TimeoutError, Exception):
                        pass

                if not command.startswith('('):
                    command = f"({command})"
                
                command_with_cr = f"{command}\r"
                expected_prefix = command.strip('()').split(' ')[0]

                self._writer.write(command_with_cr.encode('utf-8'))
                await self._writer.drain()

                for _ in range(10):
                    response_bytes = await asyncio.wait_for(
                        self._reader.readuntil(b')'),
                        timeout=TIMEOUT
                    )
                    
                    response_str = response_bytes.decode('utf-8', errors='ignore').strip('()\r\n ')
                    
                    if response_str.startswith(expected_prefix):
                        return response_str
                        
                _LOGGER.warning(f"Did not receive matching response for {command} within loop")
                return None
                
            except asyncio.TimeoutError:
                _LOGGER.warning(f"Timeout waiting for response to command: {command}")
                return None
            except Exception as e:
                _LOGGER.error(f"Error communicating: {e}")
                self._reader = None
                self._writer = None
                self._connected = False
                return None

    async def turn_on(self) -> bool:
        response = await self.send_command("PWR 1")
        return bool(response and "PWR 1" in response)

    async def turn_off(self) -> bool:
        response = await self.send_command("PWR 0")
        return bool(response and "PWR 0" in response)

    async def set_volume(self, volume: int) -> bool:
        response = await self.send_command(f"VOL {volume}")
        return bool(response and "VOL" in response)

    async def mute_on(self) -> bool:
        """Mute the amplifier."""
        response = await self.send_command("MUT 1")
        return bool(response and "MUT 1" in response)

    async def mute_off(self) -> bool:
        """Unmute the amplifier."""
        response = await self.send_command("MUT 0")
        return bool(response and "MUT 0" in response)

    async def select_source(self, source: str) -> bool:
        amp_command = REVERSE_SOURCE_MAPPING.get(source, source)
        response = await self.send_command(f"INP {amp_command}")
        return bool(response and "INP" in response)

    async def get_status(self) -> dict:
        status = {}
        
        pwr_resp = await self.send_command("PWR")
        if not pwr_resp:
            return status

        power_on = "PWR 1" in pwr_resp
        status["power"] = power_on
        
        if not power_on:
            return status

        vol_resp = await self.send_command("VOL")
        if vol_resp:
            match = re.search(r'VOL\s*(\d+)', vol_resp)
            if match:
                status["volume"] = int(match.group(1))

        mut_resp = await self.send_command("MUT")
        if mut_resp:
            status["mute"] = "MUT 1" in mut_resp

        inp_resp = await self.send_command("INP")
        if inp_resp:
            match = re.search(r'INP\s*(\d+)', inp_resp)
            if match:
                raw_source = match.group(1)
                status["source"] = SOURCE_MAPPING.get(raw_source, raw_source)

        return status