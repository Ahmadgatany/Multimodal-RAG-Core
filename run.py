import subprocess
import sys
import time
import urllib.error
import urllib.request
from shutil import which
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
BACKEND_URL = "http://127.0.0.1:8000"


def wait_for_backend(timeout: int = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(BACKEND_URL, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    raise RuntimeError("Backend did not become ready within 30 seconds")


def main() -> None:
    backend = None
    frontend = None
    try:
        try:
            wait_for_backend(timeout=2)
            print("Using existing backend: http://127.0.0.1:8000")
        except RuntimeError:
            backend = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"],
                cwd=ROOT_DIR,
            )
            wait_for_backend()

        npm = which("npm") or which("npm.cmd")
        if not npm:
            raise RuntimeError("Node.js and npm are required to start the Next.js frontend")
        frontend = subprocess.Popen(
            [npm, "run", "dev", "--", "--hostname", "127.0.0.1", "--port", "3000"],
            cwd=ROOT_DIR / "frontend",
        )
        print("Backend: http://127.0.0.1:8000")
        print("Frontend: http://localhost:3000")
        frontend.wait()
    except KeyboardInterrupt:
        print("Stopping services...")
    finally:
        if frontend is not None and frontend.poll() is None:
            frontend.terminate()
        if backend is not None and backend.poll() is None:
            backend.terminate()
        if frontend is not None:
            frontend.wait()
        if backend is not None:
            backend.wait()


if __name__ == "__main__":
    main()
