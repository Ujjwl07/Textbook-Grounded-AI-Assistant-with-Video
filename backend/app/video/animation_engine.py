"""Scene animation primitives for the MoviePy assembly pipeline.

The scene JSON produced by the segmentation prompt (Section 4.4) carries an
``animation_type`` of ``fade_in | slide_left | zoom``. ``apply_scene_animation``
is the dispatcher that turns that directive into an actual MoviePy transform, so
consecutive scenes do not all move identically.
"""

import logging
from moviepy.editor import CompositeVideoClip

logger = logging.getLogger(__name__)

DEFAULT_SIZE = (1280, 720)

# Zoom envelopes per animation type: (start_scale, end_scale).
#
# MAX_ZOOM is bounded by the slide's title-safe area. A scale of z crops
# W * (1 - 1/z) / 2 pixels from each side; at 1280x720 a 1.06 zoom removes ~36 px
# horizontally and ~20 px vertically. SlideRenderer.SAFE_MARGIN_X keeps all text
# outside that band, so nothing is clipped at full zoom. Raising these values
# without raising the safe margin will cut the badge and title.
MAX_ZOOM = 1.06

ZOOM_ENVELOPES = {
    "fade_in": (1.00, 1.03),     # subtle Ken Burns drift
    "zoom": (1.00, MAX_ZOOM),    # pronounced push-in
    "slide_left": (1.00, 1.00),  # no zoom; the motion is the slide itself
}

SUPPORTED_ANIMATIONS = tuple(ZOOM_ENVELOPES.keys())


def _ease_out_cubic(p: float) -> float:
    """Decelerating easing curve; p in [0, 1] -> eased value in [0, 1]."""
    p = max(0.0, min(1.0, p))
    return 1.0 - (1.0 - p) ** 3


def apply_ken_burns(clip, duration: float, start_zoom: float = 1.0, end_zoom: float = 1.03):
    """Apply a linear zoom (Ken Burns) to a clip across its duration."""
    if duration <= 0 or abs(end_zoom - start_zoom) < 1e-6:
        return clip
    zoom_diff = end_zoom - start_zoom
    return clip.resize(lambda t: start_zoom + zoom_diff * (min(t, duration) / duration))


def apply_zoom_in(clip, duration: float):
    """Pronounced push-in, used for scenes tagged ``animation_type: zoom``."""
    start, end = ZOOM_ENVELOPES["zoom"]
    return apply_ken_burns(clip, duration, start_zoom=start, end_zoom=end)


def apply_slide_left(clip, duration: float, size: tuple = DEFAULT_SIZE, slide_seconds: float = 0.6):
    """Slide the clip in from the right edge, easing to rest at centre.

    ``set_position`` only takes effect inside a CompositeVideoClip, so the moving
    clip is wrapped in a canvas of the target ``size``.
    """
    if duration <= 0:
        return clip

    width = size[0]
    slide_seconds = max(0.05, min(slide_seconds, duration))

    def position(t):
        if t >= slide_seconds:
            return ("center", "center")
        offset = width * (1.0 - _ease_out_cubic(t / slide_seconds))
        return (offset, "center")

    moving = clip.set_position(position)
    return CompositeVideoClip([moving], size=size).set_duration(duration)


def apply_fade_in_out(clip, fade_in_duration: float = 0.5, fade_out_duration: float = 0.5):
    """Apply fade-in and/or fade-out transitions to a clip."""
    if fade_in_duration > 0:
        clip = clip.fadein(fade_in_duration)
    if fade_out_duration > 0:
        clip = clip.fadeout(fade_out_duration)
    return clip


def apply_scene_animation(clip, animation_type: str, duration: float, size: tuple = DEFAULT_SIZE):
    """Dispatch the scene's declared ``animation_type`` to its transform.

    Unknown or missing values fall back to ``fade_in`` (subtle Ken Burns), which
    is what every scene used before the dispatcher existed.
    """
    key = (animation_type or "fade_in").strip().lower()
    if key not in ZOOM_ENVELOPES:
        logger.debug("Unknown animation_type %r, falling back to fade_in", animation_type)
        key = "fade_in"

    if key == "slide_left":
        return apply_slide_left(clip, duration, size=size)

    start, end = ZOOM_ENVELOPES[key]
    return apply_ken_burns(clip, duration, start_zoom=start, end_zoom=end)


def resolve_scene_duration(audio_duration: float, duration_hint_seconds=None, max_hold_seconds: float = 3.0) -> float:
    """Reconcile the narration length with the director's ``duration_hint_seconds``.

    The audio is authoritative — a scene can never be shorter than its narration.
    When the segmenter asked for a longer scene we hold the slide for up to
    ``max_hold_seconds`` extra so pacing follows the storyboard, and we never
    stretch the visual arbitrarily far past the voice track.
    """
    if audio_duration <= 0:
        return max(0.1, float(duration_hint_seconds or 0.1))

    try:
        hint = float(duration_hint_seconds)
    except (TypeError, ValueError):
        return audio_duration

    if hint <= audio_duration:
        return audio_duration
    return min(hint, audio_duration + max_hold_seconds)
