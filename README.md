# Shelly BLE RPC CLI

Small CLI for sending arbitrary Shelly Gen2+ RPC commands directly over BLE
using [bleak](https://bleak.readthedocs.io/).

## Usage

```console
uv run shelly_ble_rpc.py rpc E8:F6:0A:66:D3:92 Shelly.Reboot
uv run shelly_ble_rpc.py rpc --pair E8:F6:0A:66:D3:92 Shelly.GetDeviceInfo
uv run shelly_ble_rpc.py rpc E8:F6:0A:66:D3:92 Switch.Set '{"id":0,"on":true}'
uv run shelly_ble_rpc.py rpc --debug E8:F6:0A:66:D3:92 Shelly.GetDeviceInfo
uv run shelly_ble_rpc.py scan --timeout 5
uv run shelly_ble_rpc.py scan --full
uv run shelly_ble_rpc.py scan --tsv
./shelly_ble_rpc.py rpc E8:F6:0A:66:D3:92 Shelly.Reboot

nix develop
nix run . -- rpc E8:F6:0A:66:D3:92 Shelly.Reboot
nix run . -- scan
```

The optional third positional argument is JSON RPC `params`. The response
frame is printed as formatted JSON. A device-side RPC error is printed and
returns a non-zero exit status.

`scan` prints a colored Rich table with one row per discovered Shelly device
(`ADDRESS`, advertised `NAME`, `RSSI`, and whether `RPC` was advertised).
Status values such as `yes` and `unknown` are colored semantically. Use
`scan --full` to additionally make best-effort read-only `Sys.GetConfig`
requests for configured human-readable names. Full-mode lookups run in
parallel, capped at four connections by default; adjust this with
`--concurrency` if needed.

Use `rpc --pair` when the device requires BLE bonding. For full scans, use
`scan --full --pair`; pairing is disabled by default and may require platform
interaction such as entering a PIN.
Use `--tsv` for a clean tab-separated header and rows suitable for piping into
a table viewer such as `tv`/`tvtool`.

Firmware 1.7.x is the initial target: BLE RPC must be enabled and no BLE
bonding is attempted. Shelly firmware 2.0.0 and newer requires pairing for
BLE RPC outside the provisioning window.

## Protocol notes

The implementation follows Shelly's documentation for the RPC-over-GATT
channel:

- service `5f6d4f53-5f52-5043-5f53-56435f49445f`
- data characteristic `5f6d4f53-5f52-5043-5f64-6174615f5f5f`
- TX control `5f6d4f53-5f52-5043-5f74-785f63746c5f`
- RX control `5f6d4f53-5f52-5043-5f72-785f63746c5f`
- TX and RX lengths are four-byte big-endian integers
- data is written/read in MTU-sized chunks; RX control is polled for a
  response because Shelly documents notifications as currently unused

References: [Shelly Gen2+ RPC protocol](https://shelly-api-docs.shelly.cloud/gen2/General/RPCProtocol/),
[Shelly BLE RPC GATT documentation](https://shelly-api-docs.shelly.cloud/docs-ble/Devices/BLU_ZB/trv/#rpc-channel-service-shos_rpc_svc_id_),
and the linked [rpc-gatts attribute specification](https://github.com/mongoose-os-libs/rpc-gatts#attribute-description).

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
