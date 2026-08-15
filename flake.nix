{
  description = "Small Shelly Gen2+ BLE RPC CLI";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-darwin"
        "x86_64-linux"
      ];
      forEachSystem = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forEachSystem (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python3.withPackages (pythonPackages: [
            pythonPackages.bleak
            pythonPackages.rich
            pythonPackages.rich-argparse
          ]);
        in
        {
          default = pkgs.writeShellApplication {
            name = "shelly-ble-rpc";
            text = ''
              exec ${python}/bin/python ${./shelly_ble_rpc.py} "$@"
            '';
          };
        }
      );

      apps = forEachSystem (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/shelly-ble-rpc";
        };
      });

      devShells = forEachSystem (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python3.withPackages (pythonPackages: [
            pythonPackages.bleak
            pythonPackages.rich
            pythonPackages.rich-argparse
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.uv
              python
            ];
          };
        }
      );
    };
}
