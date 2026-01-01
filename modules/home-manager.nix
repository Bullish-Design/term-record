{ config, lib, pkgs, ... }:

with lib;

let
  cfg = config.programs.termrecord;

  tomlFormat = pkgs.formats.toml { };

  configFile = tomlFormat.generate "termrecord-config.toml" {
    recording = {
      enabled = cfg.recording.enable;
      storage_dir = cfg.recording.storageDir;
      format = cfg.recording.format;
      rules = cfg.recording.rules;
    };
    retention = cfg.retention;
    export = cfg.export;
    terminal = cfg.terminal;
    watcher = {
      socket_path = cfg.watcher.socketPath;
      log_level = cfg.watcher.logLevel;
      log_file = cfg.watcher.logFile;
    };
  };
in
{
  options.programs.termrecord = {
    enable = mkEnableOption "Termrecord automatic terminal recording";

    package = mkOption {
      type = types.package;
      default = pkgs.termrecord or (throw "termrecord package not available");
      description = "The termrecord package to use";
    };

    recording = {
      enable = mkOption {
        type = types.bool;
        default = true;
        description = "Enable recording by default";
      };

      storageDir = mkOption {
        type = types.str;
        default = "~/.local/share/termrecord";
        description = "Storage directory for recordings";
      };

      format = mkOption {
        type = types.enum [ "cast" "gif" "both" ];
        default = "cast";
        description = "Recording format";
      };

      rules = mkOption {
        type = types.listOf (types.submodule {
          options = {
            path = mkOption {
              type = types.str;
              description = "Path or glob pattern";
            };
            enabled = mkOption {
              type = types.bool;
              default = true;
              description = "Whether recording is enabled for this path";
            };
            format = mkOption {
              type = types.nullOr (types.enum [ "cast" "gif" "both" ]);
              default = null;
              description = "Override format for this path";
            };
          };
        });
        default = [];
        description = "Path-based recording rules";
        example = literalExpression ''
          [
            { path = "~/.password-store"; enabled = false; }
            { path = "~/projects/**"; enabled = true; format = "both"; }
          ]
        '';
      };
    };

    retention = {
      max_age_days = mkOption {
        type = types.int;
        default = 30;
        description = "Maximum age of recordings in days";
      };
      max_size_gb = mkOption {
        type = types.float;
        default = 10.0;
        description = "Maximum total storage size in GB";
      };
      max_count = mkOption {
        type = types.int;
        default = 10000;
        description = "Maximum number of recordings to keep";
      };
      cleanup_interval_hours = mkOption {
        type = types.int;
        default = 24;
        description = "How often to run cleanup in hours";
      };
    };

    export = {
      gif_enabled = mkOption {
        type = types.bool;
        default = false;
        description = "Enable automatic GIF export";
      };
      gif_speed = mkOption {
        type = types.float;
        default = 1.0;
        description = "GIF playback speed multiplier";
      };
      gif_max_idle = mkOption {
        type = types.float;
        default = 2.0;
        description = "Maximum idle time between frames in seconds";
      };
      screenshot_on_error = mkOption {
        type = types.bool;
        default = true;
        description = "Capture screenshot when command fails";
      };
    };

    terminal = {
      width = mkOption {
        type = types.int;
        default = 120;
        description = "Terminal width for recordings";
      };
      height = mkOption {
        type = types.int;
        default = 40;
        description = "Terminal height for recordings";
      };
    };

    watcher = {
      socketPath = mkOption {
        type = types.str;
        default = "~/.local/share/termrecord/watcher.sock";
        description = "Unix socket path for watcher service";
      };
      logLevel = mkOption {
        type = types.enum [ "debug" "info" "warning" "error" ];
        default = "info";
        description = "Watcher service log level";
      };
      logFile = mkOption {
        type = types.str;
        default = "~/.local/share/termrecord/watcher.log";
        description = "Watcher service log file";
      };
    };

    shellIntegration = {
      enableZshIntegration = mkOption {
        type = types.bool;
        default = true;
        description = "Enable zsh shell integration";
      };
    };
  };

  config = mkIf cfg.enable {
    home.packages = [
      cfg.package
      pkgs.asciinema
      pkgs.asciinema-agg
      pkgs.jq
    ];

    xdg.configFile."termrecord/config.toml".source = configFile;

    programs.zsh.initExtra = mkIf cfg.shellIntegration.enableZshIntegration ''
      source ${cfg.package}/share/termrecord/hooks.zsh
    '';

    systemd.user.services.termrecord-watcher = {
      Unit = {
        Description = "Termrecord Watcher Service";
        After = [ "default.target" ];
      };

      Service = {
        Type = "simple";
        ExecStart = "${cfg.package}/bin/termrecord-watcher";
        Restart = "on-failure";
        RestartSec = 5;
      };

      Install = {
        WantedBy = [ "default.target" ];
      };
    };
  };
}
