from moviepy.editor import ImageClip

def apply_ken_burns(clip: ImageClip, duration: float, start_zoom: float = 1.0, end_zoom: float = 1.03) -> ImageClip:
    """
    Applies a subtle Ken Burns zoom effect to an ImageClip over its duration.
    """
    if duration <= 0:
        return clip
    zoom_diff = end_zoom - start_zoom
    # Dynamically scales the clip based on time t relative to the duration
    return clip.resize(lambda t: start_zoom + zoom_diff * (min(t, duration) / duration))

def apply_fade_in_out(clip, fade_in_duration: float = 0.5, fade_out_duration: float = 0.5):
    """
    Applies a fade-in and/or fade-out transition to a clip.
    """
    if fade_in_duration > 0:
        clip = clip.fadein(fade_in_duration)
    if fade_out_duration > 0:
        clip = clip.fadeout(fade_out_duration)
    return clip
