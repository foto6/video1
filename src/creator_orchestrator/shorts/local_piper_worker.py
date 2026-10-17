"""Runs in the isolated E-drive voice environment; WAV only on stdout."""
import io
import json
import sys
import wave


def main():
    from piper import PiperVoice
    request=json.loads(sys.stdin.buffer.read(16384).decode('utf-8'))
    voice=PiperVoice.load(request['model_path'],use_cuda=False)
    output=io.BytesIO()
    with wave.open(output,'wb') as wav:
        voice.synthesize_wav(request['text'],wav)
    sys.stdout.buffer.write(output.getvalue())


if __name__=='__main__':main()
