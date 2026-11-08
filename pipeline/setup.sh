#!/usr/bin/env bash
# Installs everything the video pipeline needs on a fresh Ubuntu container.
set -e
export DEBIAN_FRONTEND=noninteractive
if ! command -v blender >/dev/null; then
  apt-get update -qq
  apt-get install -y -qq blender libegl1 libegl-mesa0 libgl1-mesa-dri fonts-roboto ffmpeg >/dev/null
fi
python3 -c "import kokoro_onnx, soundfile, PIL, numpy" 2>/dev/null || pip install -q kokoro-onnx soundfile pillow numpy
M="${KOKORO_DIR:-$HOME/.cache/inthisworld}"
mkdir -p "$M"
U=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0
[ -s "$M/kokoro.onnx" ] || curl -sSL -o "$M/kokoro.onnx" "$U/kokoro-v1.0.onnx"
[ -s "$M/voices.bin" ] || curl -sSL -o "$M/voices.bin" "$U/voices-v1.0.bin"
echo "pipeline ready: $(blender --version | head -1)"
