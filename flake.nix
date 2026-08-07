{
  description = "A python devshell containing all the dependencies required to run this bot";

  inputs.nixpkgs.url = "nixpkgs/nixpkgs-unstable";

  outputs = {nixpkgs, ...}: let
    system = "x86_64-linux";
    pkgs = import nixpkgs {
      inherit system;
    };

    version = "1.10.0";
    sha256 = "sha256-36GAGfvHZyNZe/Z7o3VrCCwApkZpJ+r2E8+1Hy32G5Q=";

    dearpygui = pkgs.python312.pkgs.buildPythonPackage {
      pname = "dearpygui";
      inherit version sha256;

      src = pkgs.fetchFromGitHub {
        owner = "hoffstadt";
        repo = "DearPyGui";
        rev = "v${version}";
        fetchSubmodules = true;
        sha256 = sha256;
      };

      cmakeFlags = [
        "-DMVDIST_ONLY=True"
      ];

      postConfigure = ''
        cd $cmakeDir
        mv build cmake-build-local
      '';

      nativeBuildInputs = with pkgs; [
        pkg-config
        cmake
      ];

      buildInputs = with pkgs; [
        xorg.libX11.dev
        xorg.libXrandr.dev
        xorg.libXinerama.dev
        xorg.libXcursor.dev
        xorg.xinput
        xorg.libXi.dev
        xorg.libXext
        libxcrypt

        glfw
        glew
      ];

      dontUseSetuptoolsCheck = true;

      pythonImportsCheck = [
        "dearpygui"
      ];

      meta = with pkgs.lib; {
        homepage = "https://dearpygui.readthedocs.io/en/";
        description = "Dear PyGui: A fast and powerful Graphical User Interface Toolkit for Python with minimal dependencies.";
        license = licenses.mit;
        platforms = platforms.linux;
        maintainers = with bonLib.maintainers; [L-Nafaryus];
        broken = pkgs.stdenv.isDarwin;
      };
    };
  in {
    devShells.${system}.default = pkgs.mkShell {
      packages = with pkgs; [
        python312
        frida-tools
        python312Packages.frida-python
        python312Packages.matplotlib
        python312Packages.tqdm
        python312Packages.ics
        python312Packages.peewee
        python312Packages.openpyxl
        python312Packages.pytz
        python312Packages.requests
        python312Packages.pip
        python312Packages.setuptools
        python312Packages.discordpy
        python312Packages.bitarray
        python312Packages.colorama
        python312Packages.tkinter
        python312Packages.jupytext
        python312Packages.pycryptodome
        python312Packages.flask
        python312Packages.jinja2
        python312Packages.plotly
        python312Packages.pandas
        dearpygui
      ];
      shellHook = ''
        echo "Devshell for your dokkan bot for you nix chads <3"
      '';
    };
  };
}
