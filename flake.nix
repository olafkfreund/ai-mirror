{
  description = "ai-mirror: let an AI agent drive your Hyprland (Nixarchy) desktop, with a kill switch";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      inherit (pkgs) lib;
      version = "3.1.0";

      # Everything installable ships the licence it is under, in one place.
      licenceFiles = ''
        install -Dm644 ${./LICENSE} $out/share/doc/ai-mirror/LICENSE
        install -Dm644 ${./NOTICE} $out/share/doc/ai-mirror/NOTICE
      '';

      ai-mirror-input = pkgs.stdenv.mkDerivation {
        pname = "ai-mirror-input";
        inherit version;
        src = ./src/ai_mirror_input;
        nativeBuildInputs = with pkgs; [ pkg-config wayland-scanner ];
        buildInputs = with pkgs; [ wayland libxkbcommon ];
        makeFlags = [
          "BUILD=build"
          "WLR_PROTO=${pkgs.wlr-protocols}/share/wlr-protocols/unstable/wlr-virtual-pointer-unstable-v1.xml"
        ];
        installPhase = ''
          install -Dm755 build/ai-mirror-input $out/bin/ai-mirror-input
          ${licenceFiles}
        '';
        meta.license = lib.licenses.mit;
      };

      python = pkgs.python3.withPackages (p: [ p.pygobject3 ]);
      # `ocr` (#92). English only: every language is 1.1 GiB, this adds ~41 MiB.
      tesseract = pkgs.tesseract.override { enableLanguages = [ "eng" ]; };

      ai-mirror = pkgs.stdenv.mkDerivation {
        pname = "ai-mirror";
        inherit version;
        src = ./src;
        nativeBuildInputs = [ pkgs.makeWrapper ];
        installPhase = ''
          mkdir -p $out/lib $out/bin
          cp -r ai_mirror $out/lib/
          # hyprctl is deliberately not bundled: it must match the running compositor.
          makeWrapper ${python}/bin/python3 $out/bin/ai-mirror \
            --add-flags "-m ai_mirror" \
            --set PYTHONPATH $out/lib \
            --set AI_MIRROR_HELPER ${ai-mirror-input}/bin/ai-mirror-input \
            --prefix GI_TYPELIB_PATH : ${lib.makeSearchPath "lib/girepository-1.0" [ pkgs.at-spi2-core pkgs.glib.out pkgs.gobject-introspection ]} \
            --suffix PATH : ${lib.makeBinPath (with pkgs; [ grim wl-clipboard systemd tesseract ])}
          ${licenceFiles}
        '';
        meta = { mainProgram = "ai-mirror"; license = lib.licenses.mit; };
      };

      # A plain directory (no symlinks inside) so omarchy-plugin-validate accepts it.
      plugin = pkgs.runCommand "ai-mirror-plugin-${version}" { } ''
        cp -r ${./plugin} $out
        chmod -R u+w $out
        substituteInPlace $out/AgentCommand.qml --replace-fail "@ai-mirror@" "${ai-mirror}/bin/ai-mirror"
        ${licenceFiles}
      '';

      # No Inherits: measured on Hyprland 0.56, an inherited theme's shapes win over ours (#78).
      cursor = pkgs.runCommand "ai-mirror-cursor-${version}" { nativeBuildInputs = [ pkgs.xcursorgen ]; } ''
        t=$out/share/icons/ai-mirror-agent
        mkdir -p $t/cursors
        printf '[Icon Theme]\nName=ai-mirror-agent\nComment=ai-mirror: an agent controls this desktop\n' > $t/index.theme
        cd ${./cursor}
        xcursorgen arrow.cfg $t/cursors/default
        xcursorgen hand.cfg $t/cursors/pointer
        xcursorgen text.cfg $t/cursors/text
        cd $t/cursors
        for n in hand1 hand2 pointing_hand; do ln -s pointer $n; done
        for n in xterm ibeam vertical-text; do ln -s text $n; done
        for n in left_ptr arrow top_left_arrow context-menu help progress wait watch left_ptr_watch \
                 crosshair cell move all-scroll grab grabbing fleur not-allowed no-drop alias copy \
                 col-resize row-resize n-resize e-resize s-resize w-resize ne-resize nw-resize \
                 se-resize sw-resize ew-resize ns-resize nesw-resize nwse-resize zoom-in zoom-out; do
          ln -s default $n
        done
        ${licenceFiles}
      '';
    in
    {
      packages.${system} = { inherit ai-mirror-input ai-mirror plugin cursor; default = ai-mirror; };

      homeManagerModules.default = { config, options, ... }:
        let cfg = config.programs.ai-mirror;
        in {
          options.programs.ai-mirror = {
            enable = lib.mkEnableOption "ai-mirror agent desktop control";
            killSwitch = lib.mkOption {
              type = lib.types.str;
              default = "SUPER + SHIFT + ESCAPE";
              description = "Hyprland key combo that revokes agent control and releases held keys.";
            };
            a11y.enable = lib.mkOption {
              type = lib.types.bool;
              default = true;
              description = "Expose GTK/Qt accessibility so agents can use a11y_tree/a11y_find/a11y_act.";
            };
          };

          config = lib.mkIf cfg.enable (lib.mkMerge [
            {
              home.packages = [ ai-mirror ];
              home.file.".local/share/icons/ai-mirror-agent".source = "${cursor}/share/icons/ai-mirror-agent";
              # Load from ~/.config/hypr/bindings.lua with: pcall(require, "hypr.ai-mirror-binds")
              xdg.configFile."hypr/ai-mirror-binds.lua".text = ''
                -- Generated by programs.ai-mirror; edits are overwritten on rebuild.
                o.bind("${cfg.killSwitch}", "ai-mirror: stop agent control", "${ai-mirror}/bin/ai-mirror control off")
              '';
            }
            (lib.mkIf cfg.a11y.enable {
              home.sessionVariables = {
                QT_LINUX_ACCESSIBILITY_ALWAYS_ON = "1";
                GTK_MODULES = "gail:atk-bridge";
                NO_AT_BRIDGE = "0";
              };
              dconf.settings."org/gnome/desktop/interface".toolkit-accessibility = true;
            })
            (if options ? programs.nixarchy.plugins
            then { programs.nixarchy.plugins.ai-mirror.src = plugin; }
            else { xdg.configFile."omarchy/plugins/olafkfreund.ai-mirror".source = plugin; })
          ]);
        };

      checks.${system} = {
        unittest = pkgs.runCommand "ai-mirror-unittest" { nativeBuildInputs = [ python ]; } ''
          cp -r ${./.} src && chmod -R u+w src && cd src
          patchShebangs bin
          XDG_RUNTIME_DIR=$TMPDIR python3 -m unittest discover -s tests -v
          touch $out
        '';
        confirm-keys = pkgs.runCommand "ai-mirror-confirm-keys" { nativeBuildInputs = [ pkgs.nodejs ]; } ''
          cd ${./.}
          node --test tests/test_confirm_keys.mjs
          touch $out
        '';
        # Every output someone can install carries the licence it ships under.
        licence = pkgs.runCommand "ai-mirror-licence-check" { } ''
          for installed in ${ai-mirror} ${ai-mirror-input} ${plugin} ${cursor}; do
            test -s $installed/share/doc/ai-mirror/LICENSE || { echo "no LICENSE in $installed"; exit 1; }
            test -s $installed/share/doc/ai-mirror/NOTICE || { echo "no NOTICE in $installed"; exit 1; }
          done
          touch $out
        '';
        cursor = pkgs.runCommand "ai-mirror-cursor-check" { } ''
          t=${cursor}/share/icons/ai-mirror-agent
          for c in default pointer text left_ptr hand2 xterm; do test -e $t/cursors/$c; done
          grep -qx 'Name=ai-mirror-agent' $t/index.theme
          ! grep -q Inherits $t/index.theme
          touch $out
        '';
        # Mirrors the checks Nixarchy runs when it installs a plugin.
        plugin = pkgs.runCommand "ai-mirror-plugin-check" { nativeBuildInputs = [ pkgs.jq ]; } ''
          m=${plugin}/manifest.json
          jq -e '.schemaVersion == 1 and (.id | test("^[A-Za-z0-9][A-Za-z0-9._-]*$")) and .name and .version
                 and (.kinds | index("bar-widget")) and .entryPoints.barWidget
                 and (.barWidget.defaultSection | IN("left", "center", "right"))' $m
          test -f ${plugin}/$(jq -r .entryPoints.barWidget $m)
          jq -e '(.kinds | index("overlay")) == null or (.entryPoints | has("overlay"))' $m
          test -f ${plugin}/$(jq -r '.entryPoints.overlay // .entryPoints.barWidget' $m)
          test -z "$(find ${plugin} -type l)"
          ! grep -rEw 'pacman|yay' ${plugin}
          ! grep -r '@ai-mirror@' ${plugin}
          touch $out
        '';
      };

      devShells.${system}.default = pkgs.mkShell {
        packages = with pkgs; [ python pkg-config wayland-scanner wayland libxkbcommon wlr-protocols jq grim wl-clipboard tesseract ];
        WLR_PROTO = "${pkgs.wlr-protocols}/share/wlr-protocols/unstable/wlr-virtual-pointer-unstable-v1.xml";
        GI_TYPELIB_PATH = lib.makeSearchPath "lib/girepository-1.0" [ pkgs.at-spi2-core pkgs.glib.out pkgs.gobject-introspection ];
      };
    };
}
