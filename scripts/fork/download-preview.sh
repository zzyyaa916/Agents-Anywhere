#!/usr/bin/env bash
# Resume a Fork Server/Web release without changing any running service.
set -euo pipefail
version=${1:?Usage: download-preview.sh VERSION SHA256 DESTINATION}
expected=${2:?Missing release SHA256}
target=${3:?Missing destination archive}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $expected =~ ^[a-f0-9]{64}$ ]] || { echo 'Invalid release version or SHA256' >&2; exit 2; }
check() { printf '%s  %s\n' "$expected" "$1" | sha256sum --check --status; }
if [[ -e $target ]]; then check "$target"; exit; fi
[[ ! -L $target.part ]] || exit 2
url="https://github.com/zzyyaa916/Agents-Anywhere/releases/download/v${version}-fork/Fork.Server.Web.${version}.update.tar.gz"
for attempt in {1..10}; do
    status=0
    curl --fail --location --connect-timeout 30 --max-time 3600 --continue-at - --output "$target.part" "$url" || status=$?
    if [[ $status == 0 ]]; then
        check "$target.part" || { rm -- "$target.part"; echo 'SHA256 mismatch; corrupt partial download removed; rerun to download again' >&2; exit 1; }
        mv --no-clobber -- "$target.part" "$target"
        exit
    fi
    # A server without byte ranges needs a fresh download.
    if [[ $status == 33 ]]; then rm -- "$target.part"; fi
    if [[ $attempt != 10 ]]; then sleep 5; fi
done
echo "Download failed; retained $target.part for the next attempt" >&2
exit 1
