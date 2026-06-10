"""Multimodal message definitions"""

from dataclasses import dataclass, field
from typing import List
from .attachment import Attachment, ImageAttachment


@dataclass
class MultimodalMessage:
    """Multimodal message"""
    role: str
    text: str = ""
    attachments: List[Attachment] = field(default_factory=list)

    def to_api_message(self, provider: str = "anthropic") -> dict:
        """
        Convert to API message format
        
        Args:
            provider: Provider name, supports "anthropic" or "openai"
            
        Returns:
            Message dictionary in corresponding provider API format
        """
        if not self.attachments:
            # Return simple format when no attachments
            return {
                "role": self.role,
                "content": self.text
            }
        
        # Build content list
        content_blocks = []
        
        # Add text content
        if self.text:
            content_blocks.append({
                "type": "text",
                "text": self.text
            })
        
        # Add attachments
        for attachment in self.attachments:
            if isinstance(attachment, ImageAttachment):
                if provider == "anthropic":
                    content_blocks.append(attachment.to_content_block())
                elif provider == "openai":
                    # OpenAI format
                    if attachment.base64_data:
                        content_blocks.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{attachment.media_type};base64,{attachment.base64_data}"
                            }
                        })
                    elif attachment.url:
                        content_blocks.append({
                            "type": "image_url",
                            "image_url": {
                                "url": attachment.url
                            }
                        })
            else:
                # FileAttachment or other types
                content_blocks.append(attachment.to_content_block())
        
        return {
            "role": self.role,
            "content": content_blocks
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'MultimodalMessage':
        """
        Construct MultimodalMessage from plain message dict
        
        Args:
            data: Dictionary containing role and content
            
        Returns:
            MultimodalMessage instance
        """
        role = data.get("role", "user")
        content = data.get("content", "")
        
        # If content is string, use as text directly
        if isinstance(content, str):
            return cls(role=role, text=content)
        
        # If content is list, parse each part
        if isinstance(content, list):
            text_parts = []
            attachments = []
            
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get("type", "")
                    
                    if item_type == "text":
                        text_parts.append(item.get("text", ""))
                    elif item_type == "image":
                        # Anthropic format image
                        source = item.get("source", {})
                        if source.get("type") == "base64":
                            attachments.append(ImageAttachment(
                                content_type="image",
                                media_type=source.get("media_type", "image/png"),
                                base64_data=source.get("data", ""),
                                size_bytes=len(source.get("data", ""))
                            ))
                        elif source.get("type") == "url":
                            attachments.append(ImageAttachment(
                                content_type="image",
                                url=source.get("url", ""),
                                size_bytes=0
                            ))
                    elif item_type == "image_url":
                        # OpenAI format image
                        image_url = item.get("image_url", {})
                        url = image_url.get("url", "")
                        if url.startswith("data:"):
                            # base64 format
                            attachments.append(ImageAttachment(
                                content_type="image",
                                base64_data=url.split(",", 1)[1] if "," in url else "",
                                size_bytes=len(url)
                            ))
                        else:
                            # URL format
                            attachments.append(ImageAttachment(
                                content_type="image",
                                url=url,
                                size_bytes=0
                            ))
            
            text = "\n".join(text_parts)
            return cls(role=role, text=text, attachments=attachments)
        
        # Other cases, convert content to string
        return cls(role=role, text=str(content))
