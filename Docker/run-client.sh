#!/usr/bin/env bash

if [ -z "$USERNAME" ];
then
    echo "Username is not set. Please set the username variable."
    exit 1
fi

if [ -z "$PASSWORD" ];
then
    echo "Password is not set. Please set the password variable."
    exit 1
fi

SOCKETS=$(lscpu | awk -F: '/^Socket\(s\):/ { gsub(/ /,"",$2); print $2; exit }')

if [ -z "$SOCKETS" ];
then
    echo "Error: could not detect Socket(s) from lscpu" >&2
    exit 1
fi

THREADS=$(
    awk -v N="$(nproc)" -v S="$SOCKETS" 'BEGIN {
        t = N - int(0.75 * sqrt(N))
        if (S > N) S = N
        t = t - (t % S)
        printf "%d", t < S ? S : t
    }'
)

# A restricted CPU set can expose fewer usable CPUs than physical sockets.
if [ "$SOCKETS" -gt "$THREADS" ]; then
    SOCKETS="$THREADS"
fi

exec python client.py \
    --username "$USERNAME" \
    --password "$PASSWORD" \
    --threads "$THREADS" \
    --nsockets "$SOCKETS" \
    --server "${SERVER:-http://verdict.shaheryarsohail.com}" \
    -I "$(hostname)"
