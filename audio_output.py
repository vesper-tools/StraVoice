"""Write synthesis PCM directly to WAV or encode it once to MP3."""
from contextlib import contextmanager
import wave


@contextmanager
def audio_output(path, rate, pcm=False):
    if pcm:
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            yield output.writeframesraw
    else:
        import lameenc
        encoder = lameenc.Encoder()
        encoder.set_bit_rate(128)
        encoder.set_in_sample_rate(rate)
        encoder.set_channels(1)
        encoder.set_quality(2)
        encoder.silence()
        with open(path, "wb") as output:
            yield lambda samples: output.write(encoder.encode(samples))
            output.write(encoder.flush())
