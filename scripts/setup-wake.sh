#!/usr/bin/env bash
# Install openWakeWord ("hey jarvis") for the wake-word assistant.
#
# openWakeWord 0.6.0 declares a hard dependency on tflite-runtime, which has no
# wheel for Python 3.13. We install its real dependencies first, then install
# openWakeWord itself with --no-deps and use the ONNX runtime instead.
#
# Usage:
#   PYTHON=.venv/bin/python ./scripts/setup-wake.sh
set -euo pipefail

PYTHON="${PYTHON:-python3}"

echo "Using interpreter: $("$PYTHON" -c 'import sys; print(sys.executable, sys.version.split()[0])')"

"$PYTHON" -m pip install --upgrade onnxruntime scipy scikit-learn tqdm requests
"$PYTHON" -m pip install --no-deps "openwakeword==0.6.0"
"$PYTHON" - <<'PY'
import openwakeword.utils

openwakeword.utils.download_models(model_names=["hey_jarvis"])
PY

echo
echo "openWakeWord installed. Run with VMC_WAKE_ENGINE=auto (default) or openwakeword."
