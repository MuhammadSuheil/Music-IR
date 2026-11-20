"""Download a verified, workspace-local Elasticsearch archive. No system service."""
import hashlib
from pathlib import Path
from urllib.request import urlopen
import zipfile

VERSION = "9.5.6"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "elasticsearch"
ARCHIVE = f"elasticsearch-{VERSION}-windows-x86_64.zip"
URL = "https://artifacts.elastic.co/downloads/elasticsearch/" + ARCHIVE


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    archive = CACHE / ARCHIVE
    with urlopen(URL + ".sha512", timeout=30) as response:
        expected = response.read().decode().split()[0].lower()
    if not archive.exists():
        temporary = archive.with_suffix(".download")
        with urlopen(URL, timeout=60) as response, temporary.open("wb") as f:
            count = 0
            while chunk := response.read(4 * 1024 * 1024):
                f.write(chunk)
                count += len(chunk)
                if count % (64 * 1024 * 1024) == 0:
                    print(f"Downloaded {count // (1024 * 1024)} MB", flush=True)
        temporary.replace(archive)
    with archive.open("rb") as f:
        actual = hashlib.file_digest(f, "sha512").hexdigest()
    if actual != expected:
        raise RuntimeError("Checksum SHA-512 tidak cocok; arsip tidak dijalankan/diekstrak.")
    target = CACHE / f"elasticsearch-{VERSION}"
    if not (target / "bin" / "elasticsearch.bat").exists():
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                if not (CACHE / member.filename).resolve().is_relative_to(CACHE.resolve()):
                    raise RuntimeError("Path di dalam arsip tidak aman.")
            zipped.extractall(CACHE)
    config = target / "config"
    (config / "elasticsearch.yml").write_text(
        "cluster.name: music-ir-local\nnode.name: music-ir-node\nnetwork.host: 127.0.0.1\n"
        "http.port: 9200\ndiscovery.type: single-node\nxpack.security.enabled: false\n"
        "xpack.ml.enabled: false\n", encoding="utf-8")
    (config / "jvm.options.d" / "music-ir.options").write_text("-Xms512m\n-Xmx512m\n", encoding="utf-8")
    print(f"Siap: {target / 'bin' / 'elasticsearch.bat'}")


if __name__ == "__main__":
    main()
