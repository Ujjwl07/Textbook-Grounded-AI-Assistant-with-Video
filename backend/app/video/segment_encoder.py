"""Parallel per-segment encoding.

Each segment (intro, every scene, outro) shares no state with the others, so it
is rendered and encoded in its own process and the resulting MP4 files are
joined with FFmpeg's concat demuxer without re-encoding. MoviePy builds every
frame in single-threaded Python, so this is what lets generation use all cores.
"""

import os
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor

import numpy as np

AUDIO_FPS = 44100


def _silence(duration):
    from moviepy.editor import AudioClip

    def make_frame(t):
        if np.ndim(t) == 0:
            return np.zeros(2)
        return np.zeros((len(t), 2))

    return AudioClip(make_frame, duration=duration, fps=AUDIO_FPS)


def encode_segment(job: dict) -> str:
    """Render one segment to job['out_path']. Runs in a worker process."""
    from moviepy.editor import AudioFileClip, ImageClip
    from app.video.animation_engine import apply_fade_in_out, apply_ken_burns, apply_scene_animation
    from app.video.subtitle_engine import SubtitleEngine

    duration = job["duration"]
    size = tuple(job["size"])
    clip = ImageClip(job["slide_path"], duration=duration)

    if job["kind"] == "bookend":
        from app.video.subtitle_engine import _fit_center

        w, h = size
        # Ken Burns enlarges the frame past the canvas; centre-crop it back to
        # exactly w x h, otherwise FFmpeg receives mis-sized frames (garbled video).
        zoomed = apply_ken_burns(clip, duration)
        clip = zoomed.fl(lambda gf, t: _fit_center(gf(t), w, h))
        clip.size = (w, h)
        clip = clip.set_audio(_silence(duration))
        clip = apply_fade_in_out(clip, fade_in_duration=0.5, fade_out_duration=0.5)
        audio = None
    else:
        clip = apply_scene_animation(clip, job.get("animation_type"), duration, size=size)
        if job.get("word_boundaries"):
            clip = SubtitleEngine().burn_onto(clip, job["word_boundaries"], duration, size=size)
        from moviepy.editor import CompositeAudioClip

        audio = AudioFileClip(job["audio_path"])
        # The slide may be held past the narration; pad with silence rather than
        # reading beyond the end of the audio file.
        track = CompositeAudioClip([_silence(duration), audio.set_duration(min(audio.duration, duration))])
        clip = clip.set_duration(duration).set_audio(track.set_duration(duration))
        clip = apply_fade_in_out(clip, fade_in_duration=0.3, fade_out_duration=0.3)

    clip.set_duration(duration).write_videofile(
        job["out_path"],
        fps=job["fps"],
        codec="libx264",
        audio_codec="aac",
        audio_fps=AUDIO_FPS,
        preset=job["preset"],
        threads=job["threads"],
        ffmpeg_params=["-pix_fmt", "yuv420p", "-ac", "2"],
        verbose=False,
        logger=None,
    )
    clip.close()
    if audio is not None:
        audio.close()
    return job["out_path"]


def encode_segments_parallel(jobs: list, max_workers: int) -> list:
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(encode_segment, jobs))


def concat_without_reencode(paths: list, output_path: str) -> None:
    import imageio_ffmpeg

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in paths:
            f.write("file '%s'\n" % os.path.abspath(p).replace("\\", "/"))
        list_file = f.name
    try:
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", list_file, "-c", "copy", "-movflags", "+faststart", output_path],
            check=True,
        )
    finally:
        os.remove(list_file)
