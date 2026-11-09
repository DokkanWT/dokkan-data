{pkgs, ...}: {
  # Python 3.14, matching the system interpreter.
  #
  # `version` is deliberately NOT set: when it is set, devenv resolves the
  # interpreter through cachix/nixpkgs-python instead of nixpkgs. Leaving it
  # unset uses nixpkgs' default `python3`, which on this nixpkgs-unstable input
  # is 3.14.x -- the same version as /run/current-system/sw/bin/python3.
  #
  # Packages go through `withPackages` so they are always built against that
  # exact interpreter (no 3.12/3.14 set mismatch).
  #
  # Trimmed per REFACTOR.md §12.2: dropped DearPyGui (only the abandoned
  # `main.py` used it), frida/frida-tools, peewee, ics, tkinter, plus the
  # never-imported tqdm, openpyxl, pytz, bitarray, pycryptodome, jinja2,
  # plotly, pandas and jupytext.
  languages.python = {
    enable = true;
    package = pkgs.python3.withPackages (ps:
      with ps; [
        # live code: cli_main.py, cogs/, render.py, WT_Web/
        requests
        discordpy
        matplotlib
        numpy
        colorama
        flask

        # dataservice (§6.11) -- not wired up yet, kept per §12.2
        fastapi
        uvicorn

        # tooling
        pip
        setuptools
      ]);
  };

  packages = with pkgs; [
    # Container workflow (REFACTOR.md §6.11): one compose project with
    # `data` / `app` / `admin` profiles.
    docker
    docker-compose
  ];

  enterShell = ''
    echo "Devshell for your dokkan bot for you nix chads <3"
  '';
}
