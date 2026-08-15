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
          default = pkgs.stdenv.mkDerivation {
            pname = "shelly-ble-rpc";
            version = "0.1.0";
            dontUnpack = true;

            nativeBuildInputs = [
              pkgs.installShellFiles
              pkgs.makeWrapper
            ];

            installPhase = ''
              install -Dm755 ${./shelly_ble_rpc.py} $out/libexec/shelly_ble_rpc.py
              makeWrapper ${python}/bin/python $out/bin/shelly-ble-rpc \
                --add-flags $out/libexec/shelly_ble_rpc.py

              installShellCompletion --bash --name shelly-ble-rpc.bash \
                ${./completions/shelly-ble-rpc.bash}
              installShellCompletion --zsh --name _shelly-ble-rpc \
                ${./completions/_shelly-ble-rpc}
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
