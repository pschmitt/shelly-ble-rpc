#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["bleak>=1.0", "rich>=13", "rich-argparse>=1"]
# ///

"""Send one Shelly Gen2+ RPC request over the device's BLE GATT RPC service."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import struct
import sys
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich.text import Text
from rich_argparse import RichHelpFormatter


LOG = logging.getLogger("shelly_ble_rpc")
CONSOLE = Console()

RPC_SERVICE_UUID = "5f6d4f53-5f52-5043-5f53-56435f49445f"
RPC_DATA_UUID = "5f6d4f53-5f52-5043-5f64-6174615f5f5f"
RPC_TX_CONTROL_UUID = "5f6d4f53-5f52-5043-5f74-785f63746c5f"
RPC_RX_CONTROL_UUID = "5f6d4f53-5f52-5043-5f72-785f63746c5f"

DEFAULT_TIMEOUT = 15.0
REQUEST_ID = 1
RPC_SOURCE = "shelly_ble_rpc"
MAC_ADDRESS_RE = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")


class ShellyBleRpcError(RuntimeError):
    """An expected failure while talking to a Shelly BLE RPC endpoint."""


def parse_json_params(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid JSON params at character {exc.pos}: {exc.msg}"
        ) from exc


def build_request(method: str, params: Any | None) -> tuple[dict[str, Any], bytes]:
    request: dict[str, Any] = {
        "id": REQUEST_ID,
        "src": RPC_SOURCE,
        "method": method,
    }
    if params is not None:
        request["params"] = params

    # The frame length is the number of UTF-8 bytes, not the number of JSON
    # characters. Compact JSON also keeps the BLE payload as small as possible.
    payload = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return request, payload


def tsv_field(value: Any) -> str:
    """Keep scan output one clean tab-separated row per device."""
    return str(value if value is not None else "").replace("\t", " ").replace(
        "\r", " "
    ).replace("\n", " ")


def status_cell(value: str) -> Text:
    style = {
        "yes": "bold green",
        "ok": "bold green",
        "true": "bold green",
        "no": "bold red",
        "error": "bold red",
        "false": "bold red",
        "unknown": "yellow",
        "n/a": "yellow",
    }.get(value.lower(), "white")
    return Text(value, style=style)


async def resolve_device_name(
    address: str, timeout: float
) -> str | None:
    request, payload = build_request("Sys.GetConfig", None)
    try:
        response = await call_rpc(address, request, payload, timeout)
    except (BleakError, OSError, ShellyBleRpcError, asyncio.TimeoutError) as exc:
        LOG.debug("Could not resolve the configured name for %s: %s", address, exc)
        return None

    result = response.get("result")
    if not isinstance(result, dict):
        return None
    device = result.get("device")
    if not isinstance(device, dict):
        return None
    name = device.get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


async def scan_shelly_devices(
    timeout: float, *, resolve_names: bool, concurrency: int
) -> list[dict[str, str]]:
    LOG.info("Scanning for Shelly BLE devices for %.1f seconds", timeout)
    discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    rows: list[dict[str, str]] = []
    for address, (device, advertisement) in discovered.items():
        name = advertisement.local_name or device.name or ""
        service_uuids = {str(uuid).lower() for uuid in advertisement.service_uuids}
        manufacturer_data = advertisement.manufacturer_data or {}
        is_shelly = (
            name.lower().startswith("shelly")
            or RPC_SERVICE_UUID.lower() in service_uuids
            or 0x0BA9 in manufacturer_data
        )
        if not is_shelly:
            continue
        row = {
            "address": address,
            "name": name,
            "rssi": str(advertisement.rssi),
            "rpc": (
                "yes" if RPC_SERVICE_UUID.lower() in service_uuids else "unknown"
            ),
        }
        rows.append(row)

    if resolve_names:
        semaphore = asyncio.Semaphore(concurrency)

        async def resolve_row(row: dict[str, str]) -> None:
            if not (
                row["name"].lower().startswith("shelly") or row["rpc"] == "yes"
            ):
                return
            async with semaphore:
                resolved_name = await resolve_device_name(
                    row["address"], min(timeout, 3.0)
                )
            if resolved_name:
                row["name"] = resolved_name

        await asyncio.gather(*(resolve_row(row) for row in rows))

    return sorted(rows, key=lambda row: (row["name"].lower(), row["address"].lower()))


def print_scan_results(rows: list[dict[str, str]], *, tsv: bool) -> None:
    fields = ("address", "name", "rssi", "rpc")
    headers = tuple(field.upper() for field in fields)
    if tsv:
        print("\t".join(headers))
        for row in rows:
            print("\t".join(tsv_field(row[field]) for field in fields))
        return

    if not rows:
        CONSOLE.print("No data to display", style="bold yellow")
        return

    # Match tsvtool's default table presentation: no box or title, two spaces
    # between columns, and colored columns.
    table = Table(
        box=None,
        header_style="bold",
        pad_edge=False,
        padding=(0, 1),
        show_edge=False,
    )
    table.add_column("ADDRESS", style="cyan", no_wrap=True)
    table.add_column("NAME", style="green")
    table.add_column("RSSI", style="magenta")
    table.add_column("RPC", style="white")
    for row in rows:
        table.add_row(
            row["address"], row["name"], row["rssi"], status_cell(row["rpc"])
        )
    CONSOLE.print(table)


def frame_length(raw: bytes | bytearray, *, label: str) -> int:
    if len(raw) != 4:
        raise ShellyBleRpcError(
            f"invalid {label} length response: expected 4 bytes, got {len(raw)}"
        )
    return struct.unpack(">I", raw)[0]


def mtu_write_size(client: BleakClient) -> int:
    # ATT write requests have three bytes of protocol overhead. Keep the
    # fallback useful for platforms that do not report a negotiated MTU.
    mtu = getattr(client, "mtu_size", 23) or 23
    return max(1, min(512, mtu - 3))


async def write_data(client: BleakClient, characteristic: Any, payload: bytes) -> None:
    chunk_size = mtu_write_size(client)
    LOG.debug("Writing %d data bytes in chunks of at most %d", len(payload), chunk_size)
    for offset in range(0, len(payload), chunk_size):
        chunk = payload[offset : offset + chunk_size]
        await client.write_gatt_char(characteristic, chunk, response=True)


async def read_frame(
    client: BleakClient,
    rx_control: Any,
    data_characteristic: Any,
    deadline: float,
) -> bytes:
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise asyncio.TimeoutError

        raw_length = await asyncio.wait_for(
            client.read_gatt_char(rx_control), timeout=remaining
        )
        length = frame_length(raw_length, label="RX control")
        LOG.debug("RX frame length: %d", length)
        if length == 0:
            await asyncio.sleep(min(0.1, remaining))
            continue

        frame = bytearray()
        while len(frame) < length:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise asyncio.TimeoutError
            chunk = await asyncio.wait_for(
                client.read_gatt_char(data_characteristic), timeout=remaining
            )
            if not chunk:
                raise ShellyBleRpcError(
                    f"device returned an empty data chunk with {length - len(frame)} "
                    "bytes still expected"
                )
            frame.extend(chunk)
            if len(frame) > length:
                raise ShellyBleRpcError(
                    f"device returned too much data: expected {length} bytes, "
                    f"received at least {len(frame)}"
                )
        return bytes(frame)


async def call_rpc(
    address: str,
    request: dict[str, Any],
    payload: bytes,
    timeout: float,
) -> dict[str, Any]:
    client = BleakClient(address, timeout=timeout)
    try:
        LOG.info("Connecting directly to %s", address)
        # Bleak applies its constructor timeout to connection and service
        # discovery. Do not wrap this in asyncio.wait_for: cancelling BlueZ
        # discovery can leave a D-Bus cleanup future behind.
        await client.connect()
        if not client.is_connected:
            raise ShellyBleRpcError("BLE client reported a failed connection")
        LOG.debug("Connected; negotiated MTU: %s", getattr(client, "mtu_size", "unknown"))

        try:
            service = client.services.get_service(RPC_SERVICE_UUID)
        except BleakError as exc:
            raise ShellyBleRpcError(f"GATT service discovery failed: {exc}") from exc
        if service is None:
            services = ", ".join(str(item.uuid) for item in client.services.services.values())
            raise ShellyBleRpcError(
                f"Shelly RPC GATT service {RPC_SERVICE_UUID} was not found "
                f"(discovered: {services or 'none'})"
            )

        data_characteristic = service.get_characteristic(RPC_DATA_UUID)
        tx_control = service.get_characteristic(RPC_TX_CONTROL_UUID)
        rx_control = service.get_characteristic(RPC_RX_CONTROL_UUID)
        missing = [
            name
            for name, characteristic in (
                ("data", data_characteristic),
                ("TX control", tx_control),
                ("RX control", rx_control),
            )
            if characteristic is None
        ]
        if missing:
            raise ShellyBleRpcError(
                "Shelly RPC GATT service is missing characteristic(s): "
                + ", ".join(missing)
            )
        LOG.debug(
            "Using GATT characteristics data=%s tx=%s rx=%s",
            RPC_DATA_UUID,
            RPC_TX_CONTROL_UUID,
            RPC_RX_CONTROL_UUID,
        )

        LOG.info("Sending %s (%d UTF-8 bytes)", request["method"], len(payload))
        await client.write_gatt_char(tx_control, struct.pack(">I", len(payload)), response=True)
        await write_data(client, data_characteristic, payload)

        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            raw_response = await read_frame(
                client, rx_control, data_characteristic, deadline
            )
            try:
                response = json.loads(raw_response.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ShellyBleRpcError(f"invalid JSON-RPC response: {exc}") from exc
            if not isinstance(response, dict):
                raise ShellyBleRpcError("invalid JSON-RPC response: expected an object")
            LOG.debug("Received RPC frame: %s", response)
            if response.get("id") != request["id"]:
                LOG.debug("Ignoring unrelated RPC frame with id %r", response.get("id"))
                continue
            return response
    finally:
        if client.is_connected:
            LOG.debug("Disconnecting from %s", address)
            try:
                await client.disconnect()
            except Exception as exc:  # noqa: BLE001 - cleanup must not hide the result
                LOG.debug("BLE disconnect failed: %s", exc)


async def pair_device(address: str, timeout: float) -> None:
    target = await resolve_pair_target(address, timeout)
    target_address = getattr(target, "address", target)
    pairing_agent = await register_pairing_agent(str(target_address))
    client: BleakClient | None = None
    try:
        client = BleakClient(target, timeout=timeout, pair=True)
        LOG.info("Pairing with %s", address)
        await client.connect()
        if not client.is_connected:
            raise ShellyBleRpcError("BLE client reported a failed pairing connection")
        LOG.info("Pairing completed for %s", address)
    finally:
        if client is not None and client.is_connected:
            LOG.debug("Disconnecting from %s", address)
            try:
                await client.disconnect()
            except Exception as exc:  # noqa: BLE001 - cleanup must not hide the result
                LOG.debug("BLE disconnect failed: %s", exc)
        if pairing_agent is not None:
            await pairing_agent.close()


def is_mac_address(value: str) -> bool:
    return bool(MAC_ADDRESS_RE.fullmatch(value))


def normalized_mac_address(value: str) -> str:
    return value.upper()


async def resolve_pair_target(identifier: str, timeout: float) -> Any:
    """Resolve a pair action's MAC address or advertised device name."""
    if is_mac_address(identifier):
        return normalized_mac_address(identifier)

    LOG.info("Scanning for BLE device named %s for %.1f seconds", identifier, timeout)
    discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    matches: list[Any] = []
    wanted_name = identifier.casefold()
    for device, advertisement in discovered.values():
        names = {
            value.casefold()
            for value in (advertisement.local_name, device.name)
            if isinstance(value, str) and value
        }
        if wanted_name in names:
            matches.append(device)

    if not matches:
        raise ShellyBleRpcError(f"no BLE device named {identifier!r} was found")
    if len(matches) > 1:
        addresses = ", ".join(str(device.address) for device in matches)
        raise ShellyBleRpcError(
            f"device name {identifier!r} is ambiguous; matches: {addresses}"
        )
    return matches[0]


async def register_pairing_agent(address: str) -> Any | None:
    """Register a temporary Linux BlueZ agent for Shelly's Just Works pairing."""
    if not sys.platform.startswith("linux"):
        return None

    try:
        from dbus_fast import BusType, Message, MessageType
        from dbus_fast.aio import MessageBus
        from dbus_fast.errors import DBusError
        from dbus_fast.service import ServiceInterface, method
    except ImportError as exc:
        raise ShellyBleRpcError(
            "Linux BLE pairing requires the dbus-fast package"
        ) from exc

    agent_path = "/com/shelly_ble_rpc/agent"
    wanted_device = f"/dev_{address.replace(':', '_')}".casefold()

    class ShellyPairingAgent(ServiceInterface):
        def __init__(self) -> None:
            super().__init__("org.bluez.Agent1")

        def check_device(self, device: str) -> None:
            if not device.casefold().endswith(wanted_device):
                raise DBusError(
                    "org.bluez.Error.Rejected",
                    "pairing request is for a different device",
                )

        @method()
        def Release(self) -> "":
            return None

        @method()
        def RequestPinCode(self, device: "o") -> "s":
            self.check_device(device)
            raise DBusError(
                "org.bluez.Error.Rejected", "Shelly pairing does not use a PIN"
            )

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s") -> "":
            self.check_device(device)
            LOG.debug("BlueZ requested display of pairing PIN %s", pincode)
            return None

        @method()
        def RequestPasskey(self, device: "o") -> "u":
            self.check_device(device)
            raise DBusError(
                "org.bluez.Error.Rejected", "Shelly pairing does not use a passkey"
            )

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u", entered: "q") -> "":
            self.check_device(device)
            LOG.debug("BlueZ requested display of pairing passkey %06d", passkey)
            return None

        @method()
        def RequestConfirmation(self, device: "o", passkey: "u") -> "":
            self.check_device(device)
            LOG.debug("Automatically confirming Shelly pairing passkey %06d", passkey)
            return None

        @method()
        def RequestAuthorization(self, device: "o") -> "":
            self.check_device(device)
            return None

        @method()
        def AuthorizeService(self, device: "o", uuid: "s") -> "":
            self.check_device(device)
            LOG.debug("Authorizing Shelly Bluetooth service %s", uuid)
            return None

        @method()
        def Cancel(self) -> "":
            return None

    bus = MessageBus(bus_type=BusType.SYSTEM)
    await bus.connect()
    bus.export(agent_path, ShellyPairingAgent())
    reply = await bus.call(
        Message(
            destination="org.bluez",
            path="/org/bluez",
            interface="org.bluez.AgentManager1",
            member="RegisterAgent",
            signature="os",
            body=[agent_path, "NoInputNoOutput"],
        )
    )
    if reply.message_type == MessageType.ERROR:
        bus.disconnect()
        raise ShellyBleRpcError(
            f"could not register the BlueZ pairing agent: {reply.error_name}"
        )

    LOG.debug("Registered temporary BlueZ NoInputNoOutput pairing agent")

    class PairingAgentHandle:
        async def close(self) -> None:
            try:
                reply = await bus.call(
                    Message(
                        destination="org.bluez",
                        path="/org/bluez",
                        interface="org.bluez.AgentManager1",
                        member="UnregisterAgent",
                        signature="o",
                        body=[agent_path],
                    )
                )
                if reply.message_type == MessageType.ERROR:
                    LOG.debug("Could not unregister BlueZ pairing agent: %s", reply)
            finally:
                bus.disconnect()

    return PairingAgentHandle()


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send Shelly Gen2+ RPC commands over BLE.",
        formatter_class=RichHelpFormatter,
    )
    actions = parser.add_subparsers(dest="action", required=True, metavar="ACTION")

    scan_parser = actions.add_parser(
        "scan",
        help="list nearby Shelly BLE devices",
        description="List nearby Shelly BLE devices as a tsvtool-style table or TSV.",
        formatter_class=RichHelpFormatter,
    )
    scan_parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="scan duration in seconds (default: 5)",
    )
    scan_parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="enable BLE scanner debug logging",
    )
    scan_parser.add_argument(
        "--tsv",
        action="store_true",
        help="emit raw tab-separated values instead of the colored table",
    )
    scan_parser.add_argument(
        "--full",
        action="store_true",
        help="also query devices for configured human-readable names",
    )
    scan_parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="maximum parallel name lookups in --full mode (default: 4)",
    )
    rpc_parser = actions.add_parser(
        "rpc",
        help="send an RPC method",
        description="Send an arbitrary Shelly Gen2+ RPC method over BLE.",
        formatter_class=RichHelpFormatter,
    )
    rpc_parser.add_argument(
        "address", help="BLE MAC address or platform device address"
    )
    rpc_parser.add_argument(
        "method", help="Shelly RPC method, e.g. Shelly.GetDeviceInfo"
    )
    rpc_parser.add_argument(
        "params",
        nargs="?",
        type=parse_json_params,
        help="optional JSON RPC params, e.g. '{\"id\":0}'",
    )
    rpc_parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"connection and RPC timeout in seconds (default: {DEFAULT_TIMEOUT:g})",
    )
    rpc_parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="enable BLE and protocol debug logging",
    )
    pair_parser = actions.add_parser(
        "pair",
        help="pair with a BLE device",
        description="Pair with a BLE device by MAC address or advertised name, then disconnect.",
        formatter_class=RichHelpFormatter,
    )
    pair_parser.add_argument(
        "address", help="BLE MAC address (any letter case) or advertised device name"
    )
    pair_parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="pairing timeout in seconds (default: 60)",
    )
    pair_parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        help="enable BLE pairing debug logging",
    )
    return parser


def main() -> int:
    args = argument_parser().parse_args()
    if args.timeout <= 0:
        argument_parser().error("--timeout must be greater than zero")
    if args.action == "scan" and args.concurrency <= 0:
        argument_parser().error("--concurrency must be greater than zero")

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=args.debug, show_path=False)],
    )

    if args.action == "scan":
        try:
            rows = asyncio.run(
                scan_shelly_devices(
                    args.timeout,
                    resolve_names=args.full,
                    concurrency=args.concurrency,
                )
            )
        except (BleakError, OSError) as exc:
            LOG.error("BLE scan failed: %s", exc)
            return 1
        print_scan_results(rows, tsv=args.tsv)
        if not rows:
            LOG.info("No Shelly BLE devices found")
        return 0

    if args.action == "pair":
        try:
            asyncio.run(pair_device(args.address, args.timeout))
        except asyncio.TimeoutError:
            LOG.error("Timed out after %.1f seconds while pairing", args.timeout)
            return 1
        except (BleakError, OSError, ShellyBleRpcError) as exc:
            LOG.error("BLE pairing failed: %s", exc)
            return 1
        return 0

    request, payload = build_request(args.method, args.params)

    try:
        response = asyncio.run(
            call_rpc(args.address, request, payload, args.timeout)
        )
    except asyncio.TimeoutError:
        LOG.error(
            "Timed out after %.1f seconds while connecting or waiting for the RPC response",
            args.timeout,
        )
        return 1
    except (BleakError, OSError) as exc:
        LOG.error("BLE connection/GATT operation failed: %s", exc)
        return 1
    except ShellyBleRpcError as exc:
        LOG.error("Shelly BLE RPC failed: %s", exc)
        return 1

    CONSOLE.print_json(data=response, ensure_ascii=False, sort_keys=True)
    if "error" in response:
        error = response["error"]
        LOG.error("RPC error: %s", error)
        return 1
    if "result" not in response:
        LOG.error("RPC response has neither result nor error")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
