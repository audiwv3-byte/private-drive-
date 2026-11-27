"""Generate short-lived local-only QA certificates outside the repository."""
import argparse
import ipaddress
import os
from pathlib import Path
import subprocess

def generate(address, directory):
    ip = ipaddress.IPv4Address(address)
    if not (ip.is_loopback or any(ip in ipaddress.ip_network(n) for n in
            ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))):
        raise ValueError("Only loopback or RFC1918 addresses are allowed")
    directory = Path(directory).resolve()
    directory.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(directory, 0o700)
    def run(*args):
        subprocess.run(["openssl", *args], cwd=directory, check=True,
                       capture_output=True, timeout=30)
    run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
        "-subj", "/CN=PRIVATE DRIVE temporary QA CA",
        "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
        "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        "-keyout", "ca.key", "-out", "ca.pem")
    run("req", "-new", "-newkey", "rsa:2048", "-nodes",
        "-subj", "/CN="+str(ip), "-keyout", "server.key", "-out", "server.csr")
    (directory/"server.ext").write_text(
        "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\nsubjectAltName=IP:"+str(ip)+"\n")
    run("x509", "-req", "-in", "server.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
        "-CAcreateserial", "-days", "1", "-sha256", "-extfile", "server.ext", "-out", "server.pem")
    for name in ("ca.key", "server.key"):
        os.chmod(directory/name, 0o600)
    (directory/"ca.key").unlink()
    run("verify", "-CAfile", "ca.pem", "-verify_ip", str(ip), "server.pem")
    return directory

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", required=True)
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    generate(args.address, args.directory)
