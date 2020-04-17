#!/bin/bash -ux


# Config
WHERE="$(pwd)"
cd "${WHERE}"
echo "Starting from: ${WHERE}"


# Make dir to mount to
umount -f "${WHERE}"/mnt 2>/dev/null
rm -rf mnt 2>/dev/null
mkdir mnt

# Make persistant storage
rm -rf persist 2>/dev/null
mkdir persist

# Make src fs to layer atop of
rm -rf src 2>/dev/null
mkdir -p src/{a,b,c,d}
mkdir src/a/{a2,a3} src/c/c2
touch src/b/{b1,b2} src/{c/c3,e}
echo 'Hello World' > src/f


# Start the FS
# Pass through other options
echo 'Consider --debug'
set -x
./LayerFS.py src persist mnt "$@"
