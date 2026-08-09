from pydantic import BaseModel, Field
from typing import List, Optional, Literal


class VisualSceneNode(BaseModel):
    """Single visual/animation scene item derived from an educational script line."""
    scene_id: int = Field(..., ge=1, description="Sequential 1-based scene index")
    timestamp_start_sec: float = Field(..., ge=0.0)
    timestamp_end_sec: float = Field(..., ge=0.0)
    layout_type: Literal["Split-Screen", "Diagram-Focus", "Speaker-Only", "Full-Animation", "Overlay-Text"] = Field(
        default="Speaker-Only", description="UI/Renderer layout template"
    )
    on_screen_text: str = Field(default="", description="Text banner or bullet points to overlay on screen")
    background_asset_prompt: str = Field(..., description="Prompt for image/video generation engine (Midjourney/DALL-E/Sora)")
    spoken_dialogue_ref: str = Field(..., description="Spoken dialogue segment associated with scene")
    camera_movement: Optional[str] = Field(default="Static", description="Camera cue (e.g. Zoom-In, Pan-Left, Static)")


class SceneGraph(BaseModel):
    """Complete scene breakdown JSON structure ready for downstream media/video generation."""
    script_title: str
    total_duration_sec: float
    scenes: List[VisualSceneNode] = Field(..., min_length=1)
