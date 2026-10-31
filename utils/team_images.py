"""Helpers for safe team image uploads."""

from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


def normalize_team_image(upload) -> bytes:
    if upload.size > 5 * 1024 * 1024:
        raise ValueError("Choose an image smaller than 5 MB.")
    try:
        raw = upload.getvalue()
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > 20_000_000:
                raise ValueError("Choose an image with fewer than 20 million pixels.")
            source.verify()
        with Image.open(BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            resampling = getattr(Image, "Resampling", Image).LANCZOS
            image.thumbnail((512, 512), resampling)
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            image = image.convert("RGBA" if has_alpha else "RGB")
            output = BytesIO()
            image.save(output, format="PNG", optimize=True)
            normalized = output.getvalue()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Choose an image"):
            raise
        raise ValueError("Choose a valid PNG, JPG, or WebP image.") from exc
    if len(normalized) > 5 * 1024 * 1024:
        raise ValueError("The resized team image must be smaller than 5 MB.")
    return normalized
