import numpy as np
from loguru import logger
from PIL import Image
from transformers import pipeline

# load pipe
pipe = pipeline(
    task="depth-estimation",
    model="depth-anything/Depth-Anything-V2-Small-hf",
    device="cuda",
)


def handle_depth(image: np.ndarray) -> Image.Image:
    logger.info("处理深度图")
    image = Image.fromarray(image)
    depth = pipe(image)["depth"]
    return depth
