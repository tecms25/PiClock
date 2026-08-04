#!/usr/bin/env python3
"""Walk an HLS playlist with curl and write the stream to stdout.

Exists because some hosts fingerprint the TLS handshake rather than anything
in the HTTP request. Broadcastify answers curl with 200 and Python's own TLS
stack with 403 - same URL, same IP, byte-identical headers, HTTP/1.1 forced on
both. That blocks streamlink, which is built on requests, along with ffmpeg
and VLC. curl sits on the accepted side of the line, so this walks the
playlist itself and hands every fetch to curl.

Deliberately stdlib-only, and every byte comes through curl: importing
requests here would reintroduce the exact handshake the host refuses.

Usage: hls_fetch.py URL [--user-agent UA] [--referer URL]
Writes MPEG-TS to stdout and diagnostics to stderr.
"""
import os
import subprocess
import sys
import time
from urllib.parse import urljoin

# Exit status meaning "this playlist is valid, but beyond what I implement".
# Distinct from 1 (the fetch failed) so a caller can tell "try a different
# client" apart from "this stream is not coming".
EXIT_UNSUPPORTED = 3

CURL_TIMEOUT = 15
# Consecutive playlist failures tolerated before giving up. A live feed drops
# the odd request; what matters is telling a blip apart from a dead stream.
MAX_FAILURES = 5
# Segments remembered, so a playlist that still lists what we already sent
# does not send it twice. Comfortably more than any sane sliding window.
SEEN_LIMIT = 512
# Segments taken from the first playlist. A live playlist holds a few minutes
# of history and replaying all of it would put the listener that far behind.
START_FROM_END = 3


class FetchError(Exception):
    pass


def log(message):
    sys.stderr.write('hls_fetch: %s\n' % message)
    sys.stderr.flush()


def quiet_stdout():
    """Send stdout to /dev/null, for after the reader has gone away."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
    except OSError:
        pass


def curl(url, headers):
    """Fetch one URL. Raises FetchError with whatever curl said, and the URL.

    curl --fail reports "The requested URL returned error: 403" without ever
    naming the URL, which in a log is a status code attached to nothing.
    """
    argv = ['curl', '--silent', '--show-error', '--location', '--fail',
            '--max-time', str(CURL_TIMEOUT)]
    if headers.get('user_agent'):
        argv += ['--user-agent', headers['user_agent']]
    if headers.get('referer'):
        argv += ['--referer', headers['referer']]
    argv.append(url)
    try:
        done = subprocess.run(argv, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
    except OSError as exc:
        raise FetchError('could not run curl: %s' % exc)
    if done.returncode != 0:
        detail = done.stderr.decode('utf-8', 'replace').strip()
        raise FetchError('%s (%s)' % (detail or 'curl exited %d'
                                      % done.returncode, url))
    return done.stdout


# Playlist features this fetcher does not implement. Each would need real
# work - decryption, remuxing, ranged requests - and doing any of them badly
# produces a stream that decodes to noise rather than one that fails. Naming
# them here means the caller can hand the stream to a fuller HLS client
# instead of shipping bytes no player can use.
UNSUPPORTED = (
    ('#EXT-X-MAP', 'segments need an fMP4 init segment (#EXT-X-MAP)'),
    ('#EXT-X-BYTERANGE', 'segments are byte ranges (#EXT-X-BYTERANGE)'),
)


def parse_playlist(text, base):
    """Pull what matters out of a playlist.

    Returns (uris, target_seconds, is_master, ended, unsupported), where
    unsupported is a reason string or None. URIs come back absolute, since a
    playlist may name segments relative to itself.
    """
    uris = []
    target = 4.0
    is_master = False
    ended = False
    unsupported = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#'):
            if line.startswith('#EXT-X-STREAM-INF'):
                is_master = True
            elif line.startswith('#EXT-X-TARGETDURATION:'):
                try:
                    target = float(line.split(':', 1)[1])
                except ValueError:
                    pass
            elif line.startswith('#EXT-X-ENDLIST'):
                ended = True
            elif line.startswith('#EXT-X-KEY') and 'METHOD=NONE' not in line:
                unsupported = unsupported or 'stream is encrypted (#EXT-X-KEY)'
            else:
                for tag, reason in UNSUPPORTED:
                    if line.startswith(tag):
                        unsupported = unsupported or reason
                        break
            continue
        uris.append(urljoin(base, line))
    return uris, target, is_master, ended, unsupported


def parse_args(argv):
    if not argv:
        log('no URL given')
        return None, {}
    url = argv[0]
    headers = {}
    rest = argv[1:]
    while rest:
        flag = rest.pop(0)
        if flag in ('--user-agent', '--referer') and rest:
            headers[flag.lstrip('-').replace('-', '_')] = rest.pop(0)
        else:
            log('ignoring unrecognised argument %r' % flag)
    return url, headers


def resolve_master(url, headers):
    """Follow a master playlist to a media playlist, at most once.

    One hop rather than a loop: nesting beyond that is not a thing real
    streams do, and a self-referential master would otherwise spin forever.
    """
    text = curl(url, headers).decode('utf-8', 'replace')
    uris, _, is_master, _, _ = parse_playlist(text, url)
    if not is_master:
        return url
    if not uris:
        raise FetchError('master playlist lists no streams')
    log('master playlist -> %s' % uris[0])
    return uris[0]


def main(argv):
    url, headers = parse_args(argv)
    if not url:
        return 2

    seen = []
    seen_set = set()
    failures = 0
    first_pass = True

    # Resolved under the same retry policy as everything else. A Pi that
    # starts the clock before the network is quite up would otherwise die on
    # the first attempt, where a stream that drops mid-play gets five.
    while True:
        try:
            url = resolve_master(url, headers)
            failures = 0
            break
        except FetchError as exc:
            failures += 1
            log('playlist: %s' % exc)
            if failures >= MAX_FAILURES:
                log('giving up after %d consecutive failures' % failures)
                return 1
            time.sleep(2)

    while True:
        try:
            text = curl(url, headers).decode('utf-8', 'replace')
            failures = 0
        except FetchError as exc:
            failures += 1
            log('playlist: %s' % exc)
            if failures >= MAX_FAILURES:
                log('giving up after %d consecutive failures' % failures)
                return 1
            time.sleep(2)
            continue

        uris, target, _, ended, unsupported = parse_playlist(text, url)
        if unsupported:
            # A distinct exit status, not a general failure: the caller can
            # retry this stream with a fuller HLS client, which is a different
            # response from "the host refused us" or "the network is down".
            #
            # Checked before any segment is written, so the handover starts
            # from a clean stream rather than from part of one.
            log('%s - needs a fuller HLS client' % unsupported)
            return EXIT_UNSUPPORTED

        if first_pass:
            # Join near the live edge rather than replaying the window.
            uris = uris[-START_FROM_END:]
            first_pass = False

        for uri in uris:
            if uri in seen_set:
                continue
            try:
                data = curl(uri, headers)
            except FetchError as exc:
                # One bad segment is a gap in the audio, not the end of the
                # stream; the next playlist poll carries on from there.
                log('segment: %s' % exc)
                continue
            seen.append(uri)
            seen_set.add(uri)
            if len(seen) > SEEN_LIMIT:
                seen_set.discard(seen.pop(0))
            try:
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
            except BrokenPipeError:
                # The player has gone. This is the normal way this process
                # ends, so it must stay silent - stderr here is what the
                # clock reports as the reason a stream stopped, and a
                # traceback would be shown to the user as the failure.
                #
                # Catching it is not enough: the interpreter flushes stdout
                # again on the way out and raises a second time, past any
                # handler. Pointing the fd at /dev/null gives that flush
                # somewhere harmless to go.
                quiet_stdout()
                return 0

        if ended:
            log('playlist ended')
            return 0
        # Half the target duration: often enough not to miss a segment out of
        # the sliding window, seldom enough not to hammer the host.
        time.sleep(max(1.0, target / 2.0))


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        sys.exit(0)
