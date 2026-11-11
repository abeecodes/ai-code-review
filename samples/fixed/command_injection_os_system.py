import subprocess


def ping_host(host):
    return subprocess.run(["ping", "-c", "1", host], check=False).returncode