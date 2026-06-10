"""Multimodal attachment definitions"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Attachment:
    """Base attachment class"""
    content_type: str
    filename: Optional[str] = None
    size_bytes: int = 0


@dataclass
class ImageAttachment(Attachment):
    """Image attachment"""
    url: Optional[str] = None
    base64_data: Optional[str] = None
    media_type: str = "image/png"
    width: Optional[int] = None
    height: Optional[int] = None

    def to_content_block(self) -> dict:
        """Convert to Anthropic vision format"""
        if self.base64_data:
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": self.media_type,
                    "data": self.base64_data
                }
            }
        elif self.url:
            return {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": self.url
                }
            }
        else:
            raise ValueError("ImageAttachment must have either url or base64_data")


@dataclass
class FileAttachment(Attachment):
    """File attachment"""
    text_content: Optional[str] = None

    def to_content_block(self) -> dict:
        """Convert to text content block"""
        filename = self.filename or "unknown"
        text = self.text_content or ""
        return {
            "type": "text",
            "text": f"[File: {filename}]\n{text}"
        }
