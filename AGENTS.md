# Agent guidance

This repository provides a Python CLI for Shelly Bluetooth Low Energy RPC.

## Development

- The implementation is in `shelly_ble_rpc.py`; use the Nix flake for the development environment.
- Validate protocol and serialization changes with synthetic fixtures. Do not pair with or change a live device as part of testing.

## CI

- Before changing CI, inspect the current guidance in `pschmitt/ci-workflows`. Pin shared reusable workflow and action references to `@main`.
