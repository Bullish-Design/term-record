{
  description = "Termrecord - Automatic terminal recording for atuin";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};

        python = pkgs.python312;

        termrecord = python.pkgs.buildPythonApplication {
          pname = "termrecord";
          version = "0.1.0";
          format = "pyproject";

          src = ./.;

          nativeBuildInputs = with python.pkgs; [
            hatchling
          ];

          propagatedBuildInputs = with python.pkgs; [
            click
            pydantic
            aiosqlite
            watchfiles
          ] ++ pkgs.lib.optionals (python.pkgs.pythonOlder "3.11") [
            tomli
          ];

          postInstall = ''
            mkdir -p $out/share/termrecord
            cp -r scripts/* $out/share/termrecord/
          '';

          pythonImportsCheck = [ "termrecord" ];

          meta = with pkgs.lib; {
            description = "Automatic terminal recording linked to atuin shell history";
            homepage = "https://github.com/Bullish-Design/term-record";
            license = licenses.mit;
            maintainers = [ ];
          };
        };

        hooks = pkgs.runCommand "termrecord-hooks" {} ''
          mkdir -p $out
          substitute ${./scripts/hooks.zsh} $out/hooks.zsh \
            --replace "@hooks@" "$out"
        '';
      in
      {
        packages = {
          default = termrecord;
          inherit termrecord hooks;
        };

        apps.default = {
          type = "app";
          program = "${termrecord}/bin/termrecord";
        };

        devShells.default = pkgs.mkShell {
          buildInputs = [
            termrecord
            pkgs.asciinema
            pkgs.asciinema-agg
            pkgs.jq
            python.pkgs.pytest
            python.pkgs.pytest-asyncio
            python.pkgs.mypy
            python.pkgs.ruff
          ];
        };
      }
    ) // {
      homeManagerModules.default = import ./modules/home-manager.nix;
    };
}
