from pathlib import Path
from typing import Optional

from app.core.config import get_settings


class VideoStorage:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.video_output_dir.mkdir(parents=True, exist_ok=True)
        self._configure_cloudinary()

    def _configure_cloudinary(self) -> None:
        if not self.settings.cloudinary_enabled:
            return
        import cloudinary

        cloudinary.config(
            cloud_name=self.settings.cloudinary_cloud_name,
            api_key=self.settings.cloudinary_api_key,
            api_secret=self.settings.cloudinary_api_secret,
            secure=True,
        )

    async def upload_video(self, local_path: str, public_id: Optional[str] = None) -> str:
        path = Path(local_path)
        if self.settings.cloudinary_enabled and path.exists():
            import cloudinary.uploader

            result = cloudinary.uploader.upload_large(
                str(path),
                resource_type="video",
                folder=self.settings.cloudinary_folder,
                public_id=public_id,
                overwrite=True,
            )
            return result["secure_url"]
        return f"/api/video-file/{path.name}"

    def create_placeholder_video(self, job_id: str, topic: str) -> str:
        path = self.settings.video_output_dir / f"{job_id}.txt"
        path.write_text(
            f"Placeholder video artifact for topic: {topic}\n"
            "Replace this file by connecting the MoviePy/video assembler module.\n",
            encoding="utf-8",
        )
        return str(path)


video_storage = VideoStorage()
