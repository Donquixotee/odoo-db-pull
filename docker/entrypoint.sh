#!/bin/sh
# Copy SSH config/keys from the read-only host mount to a writable location
# with the correct ownership (root) and permissions that SSH/rsync require.
if [ -d /root/.ssh-host ]; then
    rm -rf /root/.ssh
    cp -r /root/.ssh-host /root/.ssh
    chown -R root:root /root/.ssh
    chmod 700 /root/.ssh
    find /root/.ssh -type f -exec chmod 600 {} \;
fi
exec "$@"
