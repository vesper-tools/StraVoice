"""Build the worker against the installed, pinned b11829 runtime (MSVC x64)."""
import concurrent.futures
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clone_models import package_dir

HEADERS = [
    "common/common.h", "common/arg.h", "common/sampling.h", "common/log.h",
    "common/download.h", "common/hf-cache.h", "common/build-info.h",
    "include/llama.h", "include/llama-cpp.h", "ggml/include/ggml.h",
    "ggml/include/ggml-cpu.h", "ggml/include/ggml-backend.h",
    "ggml/include/ggml-opt.h", "ggml/include/ggml-alloc.h", "ggml/include/gguf.h",
    "tools/mtmd/mtmd.h", "tools/mtmd/mtmd-helper.h",
]


def main():
    vswhere = Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
    install = subprocess.check_output([str(vswhere), "-latest", "-products", "*",
        "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property",
        "installationPath"], encoding="utf-8").strip()
    if not install:
        raise RuntimeError("Install Visual Studio C++ Build Tools first")
    vc = Path(install) / "VC"
    version = (vc / "Auxiliary/Build/Microsoft.VCToolsVersion.default.txt").read_text().strip()
    tools = vc / "Tools/MSVC" / version / "bin/Hostx64/x64"
    runtime = package_dir() / "runtime"
    with tempfile.TemporaryDirectory(prefix="qwen-worker-build-") as temp:
        work = Path(temp)
        def fetch(name):
            target = work / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen("https://raw.githubusercontent.com/ggml-org/llama.cpp/b11829/" + name,
                                        timeout=60) as response:
                target.write_bytes(response.read())
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(fetch, HEADERS))
        libraries = []
        for name in ("llama", "llama-common", "mtmd", "ggml", "ggml-base"):
            exports = subprocess.check_output([str(tools / "dumpbin.exe"), "/exports",
                str(runtime / (name + ".dll"))]).decode("utf-8", "replace")
            symbols = re.findall(r"^\s+\d+\s+[0-9A-F]+\s+[0-9A-F]+\s+(\S+)", exports, re.M)
            definition = work / (name + ".def")
            definition.write_text("LIBRARY " + name + "\nEXPORTS\n" + "\n".join(symbols))
            library = work / (name + ".lib")
            subprocess.run([str(tools / "lib.exe"), "/nologo", "/machine:x64",
                "/def:" + str(definition), "/out:" + str(library)], check=True, capture_output=True)
            libraries.append(str(library))
        output = ROOT / "bin/qwen-worker.exe"
        args = ["cl", "/nologo", "/std:c++17", "/EHsc", "/O2", "/MD", "/utf-8", "/DNOMINMAX"]
        args += ["/I" + str(work / path) for path in ("common", "include", "ggml/include", "tools/mtmd")]
        args += [str(ROOT / "native/qwen_worker.cpp"), "/Fe:" + str(output),
                 "/Fo:" + str(work / "worker.obj")] + libraries
        command = 'call "' + str(vc / "Auxiliary/Build/vcvars64.bat") + '" >nul && ' + subprocess.list2cmdline(args)
        subprocess.run(command, shell=True, cwd=work, check=True)
        print(output)


if __name__ == "__main__":
    main()
