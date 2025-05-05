{ pkgs }: {
  deps = [
    pkgs.python311
    pkgs.python311Packages.pip
    pkgs.python311Packages.setuptools
    pkgs.python311Packages.wheel
    pkgs.portaudio
    pkgs.ffmpeg
    pkgs.alsaLib
    pkgs.python311Packages.pyaudio
    pkgs.python311Packages.aiohttp
    pkgs.python311Packages.python-socketio
    pkgs.python311Packages.websockets
    pkgs.python311Packages.python-dotenv
    pkgs.python311Packages.requests
    pkgs.python311Packages.jinja2
  ];
  env = {
    PYTHONBIN = "${pkgs.python311}/bin/python3.11";
    PYTHONHOME = "${pkgs.python311}";
    PYTHONPATH = "${pkgs.python311Packages.pip}/lib/python3.11/site-packages";
    LD_LIBRARY_PATH = pkgs.lib.makeLibraryPath [
      pkgs.portaudio
      pkgs.alsaLib
    ];
  };
}
