"""Image-first analysis; independent references and filenames never enter prompts."""

from services.common.media import representative_frames
from .meme_providers import vision_client


def analyze_image(data, user_text, settings, ledger):
    frames, records = representative_frames(data, count=4)
    analysis = vision_client(settings, ledger).analyze(frames, user_text)
    analysis.sampled_frames = records
    return analysis, frames
