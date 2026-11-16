"""Preserve supplied alpha and pale product details on clean studio images."""

import numpy as np
from PIL import Image, ImageChops
from scipy import ndimage


def remove_product_background(image, model_directory, white_background_rgb=None, allow_model=True):
    image = image.convert("RGBA")
    data = np.asarray(image)
    alpha = data[:, :, 3]
    edge_alpha = np.concatenate((alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]))
    if np.mean(edge_alpha < 32) > 0.5:
        return image, "provided_alpha"

    rgb = data[:, :, :3].astype(np.int16)
    edge = np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]))
    background = np.asarray(white_background_rgb) if white_background_rgb is not None else np.median(edge, axis=0)
    distance = np.max(np.abs(edge - background), axis=1)
    if white_background_rgb is not None or background.min() >= 235 and np.mean(distance <= 8) >= 0.97:
        # Remove only near-white pixels connected to the image boundary.
        # Unlike salient-object segmentation this retains the alien table's
        # ivory tabletop, which is part of the product rather than background.
        candidates = np.max(np.abs(rgb - background), axis=2) <= 12
        seeds = np.zeros(candidates.shape, dtype=bool)
        seeds[0], seeds[-1] = candidates[0], candidates[-1]
        seeds[:, 0], seeds[:, -1] = candidates[:, 0], candidates[:, -1]
        outside = ndimage.binary_propagation(seeds, mask=candidates)
        keep = Image.fromarray(np.where(outside, 0, 255).astype(np.uint8))
        image.putalpha(ImageChops.multiply(image.getchannel("A"), keep))
        return image, "white_background_connected_components"

    if not allow_model:
        raise ValueError("缺少整件家具的可靠轮廓，请先清理背景")
    import os
    from pathlib import Path

    if model_directory is not None:
        if not (Path(model_directory) / "u2netp.onnx").is_file():
            raise FileNotFoundError("Local U2NetP weights missing; automatic download is disabled")
        os.environ["U2NET_HOME"] = str(Path(model_directory).resolve())
    import rembg

    session = rembg.new_session("u2netp", providers=["CPUExecutionProvider"])
    removed = rembg.remove(image.convert("RGB"), session=session).convert("RGBA")
    removed.putalpha(ImageChops.multiply(removed.getchannel("A"), image.getchannel("A")))
    return removed, "u2netp"
