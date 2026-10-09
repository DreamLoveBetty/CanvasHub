"""Shared Python, separate inference process; child dies when its server disappears."""
import argparse
import os
from pathlib import Path
import signal
import sys
import threading
import time


def export_wav(directory):
    """Lossless PCM-24 export; retain the upstream FLAC/manifest for replay.

    Bounded chunks avoid a second full-song PCM buffer. This import stays in the
    worker, never in the HTTP process. An interrupted export is not a result.
    """
    import soundfile as sf

    directory = Path(directory)
    temporary = directory / '.audio.wav.tmp'
    try:
        with sf.SoundFile(directory / 'audio.flac') as source:
            with sf.SoundFile(temporary, 'w', samplerate=source.samplerate,
                              channels=source.channels, format='WAV', subtype='PCM_24') as target:
                for block in source.blocks(blocksize=65536, dtype='int32', always_2d=True):
                    target.write(block)
        temporary.replace(directory / 'audio.wav')
    finally:
        temporary.unlink(missing_ok=True)


def run_cli(arguments, audio_format):
    from lyra.cli import main as cli

    code = cli(arguments)
    if arguments[0] == 'generate' and audio_format == 'wav' and code in (None, 0, 1):
        directory = Path(arguments[arguments.index('--output') + 1])
        if (directory / 'audio.flac').is_file():
            export_wav(directory)
    return code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--audio-format', choices=('flac', 'wav'), default='flac')
    parser.add_argument('parent', type=int)
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    parent = args.parent
    def watch_parent():
        while True:
            if os.getppid() != parent:
                os.killpg(os.getpgrp(), signal.SIGKILL)
                return
            time.sleep(1)
    threading.Thread(target=watch_parent, daemon=True).start()
    return run_cli(args.arguments, args.audio_format)


if __name__ == '__main__':
    raise SystemExit(main())
