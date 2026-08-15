# Shelly BLE RPC CLI

Small CLI for sending arbitrary Shelly Gen2+ RPC commands directly over BLE
using [bleak](https://bleak.readthedocs.io/).

## Usage

```console
uv run shelly_ble_rpc.py rpc E8:F6:0A:66:D3:92 Shelly.Reboot
uv run shelly_ble_rpc.py pair E8:F6:0A:66:D3:92
uv run shelly_ble_rpc.py unpair E8:F6:0A:66:D3:92
uv run shelly_ble_rpc.py rpc E8:F6:0A:66:D3:92 Switch.Set '{"id":0,"on":true}'
uv run shelly_ble_rpc.py rpc E8:F6:0A:66:D3:92 Switch.GetConfig
uv run shelly_ble_rpc.py rpc E8:F6:0A:66:D3:92 --raw '{"id":7,"src":"my-cli","method":"Switch.GetConfig","params":{"id":1}}'
uv run shelly_ble_rpc.py rpc --debug E8:F6:0A:66:D3:92 Shelly.GetDeviceInfo
uv run shelly_ble_rpc.py scan --timeout 5
uv run shelly_ble_rpc.py scan --full
uv run shelly_ble_rpc.py scan --full --force
uv run shelly_ble_rpc.py scan --tsv
uv run shelly_ble_rpc.py paired
./shelly_ble_rpc.py rpc E8:F6:0A:66:D3:92 Shelly.Reboot

nix develop
nix run . -- pair E8:F6:0A:66:D3:92
nix run . -- unpair E8:F6:0A:66:D3:92
nix run . -- paired
nix run . -- rpc E8:F6:0A:66:D3:92 Shelly.Reboot
nix run . -- scan
```

The CLI automatically adds `{"id":0}` to component RPC params when no
component id is supplied. The RPC envelope always includes a request `id` and
`src` value. The optional third positional argument overrides
or extends those automatic component params; quote it so your shell passes the
JSON as one argument. For example, `Switch.GetConfig` works without extra
arguments and targets component 0 by default.

Use `--raw` to provide the complete JSON RPC request manually, including its
`id`, `src`, `method`, and optional `params`; it disables all automatic fields.
The response frame is printed as formatted JSON. A device-side RPC error is
printed and returns a non-zero exit status.

`scan` prints a colored Rich table with one row per discovered Shelly device
(`ADDRESS`, advertised `NAME`, `RSSI`, whether `RPC` was advertised, and local
`PAIRED` state). Status values such as `yes`, `no`, and `unknown` are colored
semantically. Use
`scan --full` to additionally make best-effort read-only `Sys.GetConfig`
requests for configured human-readable names. Full-mode lookups run in
parallel, capped at four connections by default; adjust this with
`--concurrency` if needed. By default, full mode connects only to devices that
the local Bluetooth backend reports as paired; use `scan --full --force` to
allow connections to unpaired or unknown devices.

Use `paired` to list all locally bonded Shelly devices, including devices that
are not currently advertising. This command currently uses the Linux/BlueZ
bond database and prints only the address, cached device name, and paired
state.

Use the separate `pair ADDRESS_OR_NAME` action when the device requires BLE
bonding; it accepts a MAC address in any letter case or the advertised device
name, then pairs and disconnects. Afterwards, `rpc` and `scan --full` can use
the established bond. Pairing may require platform interaction such as
entering a PIN.
Use `unpair ADDRESS_OR_NAME` to remove the local bond. Unpairing is supported
by Bleak on Linux and Windows.
Use `--tsv` for a clean tab-separated header and rows suitable for piping into
a table viewer such as `tv`/`tvtool`.

Shell completions are included for Bash and Zsh. Nix installs them
automatically; for a checkout used directly with the Python entry point, source
the matching file from `completions/`. Device completion queries locally paired
devices, and RPC method completion includes the common Shelly methods.

```console
source completions/shelly-ble-rpc.bash       # Bash
source completions/_shelly-ble-rpc            # Zsh
```

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
