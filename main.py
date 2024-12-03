import os
import tempfile
import uuid
import traceback
import hashlib
from pathlib import Path

import gradio as gr
from loguru import logger
from PIL import Image, ImageFilter
from wand.image import Image as WandImage

from composite import (
    composite_images,
    create_tiled_texture,
    generate_lighting_map,
    composite_with_lighting,
)
from depth import handle_depth
from displacement import displacement_mapping

# 添加缓存目录配置
CACHE_DIR = Path("cache/depth_maps")
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def get_image_hash(image_array):
    """计算图像数组的哈希值"""
    return hashlib.md5(image_array.tobytes()).hexdigest()


def get_cached_depth_map(image_array, cache_dir=CACHE_DIR):
    """获取缓存的深度图,如果不存在则返回None"""
    image_hash = get_image_hash(image_array)
    cache_path = cache_dir / f"{image_hash}.png"

    if cache_path.exists():
        logger.info(f"Using cached depth map: {cache_path}")
        return Image.open(cache_path)
    return None


def save_depth_map(depth_map, image_array, cache_dir=CACHE_DIR):
    """保存深度图到缓存"""
    image_hash = get_image_hash(image_array)
    cache_path = cache_dir / f"{image_hash}.png"
    depth_map.save(cache_path)
    logger.info(f"Saved depth map to cache: {cache_path}")


def process_image(input_image):
    return handle_depth(input_image)


def apply_displacement(input_image, depth_image, strength):
    if input_image is None or depth_image is None:
        return None

    # 创建临时文件保存输入图片和深度图
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as input_temp:
        input_temp = Image.fromarray(input_image)
        input_path = uuid.uuid4().hex + ".png"
        input_temp.save(input_path)

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as depth_temp:
        depth_temp = Image.fromarray(depth_image)
        depth_path = uuid.uuid4().hex + ".png"
        depth_temp.save(depth_path)

    try:
        # 应用位移变换
        result = displacement_mapping(input_path, depth_path, strength)

        # 创临时文件保存结果
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as output_temp:
            output_path = output_temp.name
            result.save(filename=output_path)
            return output_path

    finally:
        # 清理临时文件
        for path in [input_path, depth_path]:
            try:
                os.unlink(path)
            except:
                pass


def apply_composite(texture_image, background_image, mask_image, tile_texture):
    if texture_image is None or background_image is None or mask_image is None:
        return None

    # 保存临时文件
    texture_path = uuid.uuid4().hex + ".png"
    background_path = uuid.uuid4().hex + ".png"
    mask_path = uuid.uuid4().hex + ".png"

    try:
        # 保存输入图片
        Image.fromarray(texture_image).save(texture_path)
        Image.fromarray(background_image).save(background_path)
        Image.fromarray(mask_image).save(mask_path)

        # 进行合成
        result = composite_images(
            texture_path, background_path, mask_path, tile=tile_texture
        )

        # 保存结果
        output_path = uuid.uuid4().hex + ".png"
        result.save(filename=output_path)
        return output_path

    finally:
        # 清理临时文件
        for path in [texture_path, background_path, mask_path]:
            try:
                os.unlink(path)
            except:
                pass


def apply_combined_effects(
    texture_image,
    background_image,
    mask_image,
    texture_scale,
    tile_texture,
    displacement_strength,
    blur_radius,
    lighting_strength=0.5,
    black_point=0,
    white_point=100,
    gamma=1.0,
    contrast=1.0,
    lightness=0,
    detail_strength=0.5,
):
    """
    应用组合效果

    参数:
        texture_image: 纹理图
        background_image: 背景图
        mask_image: 遮罩图
        texture_scale: float, 纹理缩放系数
        tile_texture: bool, 是否平铺纹理
        displacement_strength: float, 位移强度
        blur_radius: float, 模糊半径
        lighting_strength: float, 光照强度 (0-1)
        black_point: float, 黑场值 (0-100)
        white_point: float, 白场值 (0-100)
        gamma: float, 伽马值 (0.1-5.0)
        contrast: float, 对比度调整 (0.0-5.0)
    """
    if texture_image is None or background_image is None or mask_image is None:
        return None

    # 初始化临时文件路径变量
    texture_path = None
    background_path = None
    mask_path = None
    depth_path = None
    displaced_path = None
    tiled_path = None

    try:
        # 保存临时文件
        texture_path = uuid.uuid4().hex + ".png"
        background_path = uuid.uuid4().hex + ".png"
        mask_path = uuid.uuid4().hex + ".png"
        depth_path = uuid.uuid4().hex + ".png"

        # 保存输入图片
        Image.fromarray(texture_image).save(texture_path)
        Image.fromarray(background_image).save(background_path)
        Image.fromarray(mask_image).save(mask_path)

        # 1. 检查缓存的深度图
        depth_image = get_cached_depth_map(background_image)
        if depth_image is None:
            # 如果没有缓存,则生成新的深度图
            depth_image = handle_depth(background_image)
            save_depth_map(depth_image, background_image)

        if blur_radius > 0:
            depth_image = depth_image.filter(
                ImageFilter.GaussianBlur(radius=blur_radius)
            )
        depth_image.save(depth_path)

        # 2. 对纹理进行深度置换
        displaced_texture = None
        with WandImage(filename=texture_path) as texture:
            if tile_texture:
                # 先进行平铺
                with WandImage(filename=background_path) as background:
                    texture = create_tiled_texture(
                        texture,
                        background.width,
                        background.height,
                        scale_factor=texture_scale
                    )
                    # 保存平铺后的纹理
                    tiled_path = uuid.uuid4().hex + ".png"
                    texture.save(filename=tiled_path)

                # 对平铺后的纹理进行深度置换
                displaced_texture = displacement_mapping(
                    tiled_path, depth_path, displacement_strength
                )
            else:
                # 直接对原纹理进行深度置换
                displaced_texture = displacement_mapping(
                    texture_path, depth_path, displacement_strength
                )

        # 确保 displaced_texture 被创建
        if displaced_texture is None:
            return None

        # 保存位移后的纹理
        displaced_path = "debug_displaced_" + uuid.uuid4().hex + ".png"
        displaced_texture.save(filename=displaced_path)

        # 在合成之前生成光照图
        with WandImage(filename=depth_path) as depth:
            with WandImage(filename=background_path) as background:
                with WandImage(filename=mask_path) as mask:
                    # 生成光照图
                    lighting_map = generate_lighting_map(
                        depth,
                        background,
                        mask,
                    )

        # 应用光照和合成
        with WandImage(filename=displaced_path) as texture:
            with WandImage(filename=background_path) as background:
                with WandImage(filename=mask_path) as mask:
                    final_result = composite_with_lighting(
                        texture,
                        background,
                        mask,
                        lighting_map,
                        lighting_strength=lighting_strength,
                        black_point=black_point,
                        white_point=white_point,
                        gamma=gamma,
                        contrast=contrast,
                        lightness=lightness,
                        detail_strength=detail_strength,
                    )

        # 保存最终结果
        output_path = "debug_final_" + uuid.uuid4().hex + ".png"
        final_result.save(filename=output_path)
        return output_path

    except Exception as e:
        logger.error(f"组合效果处理失败: {e}")
        logger.error(f"错误类型: {type(e).__name__}")
        logger.error(f"错误详情: {str(e)}")
        logger.error("错误堆栈:\n" + traceback.format_exc())

        # 检查关键步骤是否成功
        if "depth_image" not in locals():
            logger.error("深度图生成失败")
        elif "displaced_texture" not in locals():
            logger.error("深度置换失败")
        elif "final_result" not in locals():
            logger.error("图像合成失败")

        return None

    finally:
        # 清理所有临时文件
        temp_files = [
            path
            for path in [
                texture_path,
                background_path,
                mask_path,
                depth_path,
                tiled_path,
            ]
            if path is not None
        ]
        for path in temp_files:
            try:
                os.unlink(path)
            except:
                pass
        # 如果 displaced_path 存在，最后清理它
        if displaced_path:
            try:
                os.unlink(displaced_path)
            except:
                pass


# 创建Gradio界面
with gr.Blocks() as demo:
    gr.Markdown("# 图像处理演示")

    with gr.Tab("深度估计"):
        with gr.Row():
            input_image1 = gr.Image(label="上传图片")
            output_image1 = gr.Image(label="处理结果")

        process_btn = gr.Button("生成深度图")
        process_btn.click(fn=process_image, inputs=input_image1, outputs=output_image1)

    with gr.Tab("深度置换"):
        with gr.Row():
            input_image2 = gr.Image(label="原始图片")
            depth_image = gr.Image(label="深度图")
            output_image2 = gr.Image(label="处理结果")

        strength = gr.Slider(minimum=0, maximum=50, value=20, step=1, label="变形度")

        displace_btn = gr.Button("应用深度置换")
        displace_btn.click(
            fn=apply_displacement,
            inputs=[input_image2, depth_image, strength],
            outputs=output_image2,
        )

    with gr.Tab("图片合成"):
        with gr.Row():
            texture_image = gr.Image(label="纹理图")
            background_image = gr.Image(label="背景图")
            mask_image = gr.Image(label="遮罩图")

        with gr.Row():
            output_image3 = gr.Image(label="合成结果")
            tile_texture = gr.Checkbox(label="平铺纹理", value=False)

        composite_btn = gr.Button("合成图像")
        composite_btn.click(
            fn=apply_composite,
            inputs=[texture_image, background_image, mask_image, tile_texture],
            outputs=output_image3,
        )

    with gr.Tab("组合效果"):
        # 共用的图片输入区域
        with gr.Row():
            texture_image = gr.Image(label="纹理图")
            background_image = gr.Image(label="背景图")
            mask_image = gr.Image(label="遮罩图")
            texture_scale = gr.Slider(  # 添加纹理缩放滑块
                minimum=0.01,
                maximum=5.0,
                value=1.0,
                step=0.01,
                label="纹理缩放系数"
            )

        with gr.Row():
            # 左侧参数组
            with gr.Column():
                gr.Markdown("### 参数组 A")
                with gr.Row():
                    tile_texture_a = gr.Checkbox(label="平铺纹理", value=True)
                    strength_a = gr.Slider(
                        minimum=0, maximum=100, value=20, step=1, label="深度置换强度"
                    )

                with gr.Row():
                    blur_radius_a = gr.Slider(
                        minimum=0, maximum=20, value=5, step=1, label="深度图模糊值"
                    )
                    lighting_strength_a = gr.Slider(
                        minimum=0, maximum=1, value=0.5, step=0.1, label="光照强度"
                    )

                with gr.Row():
                    black_point_a = gr.Slider(
                        minimum=0, maximum=100, value=0, step=1, label="黑场值"
                    )
                    white_point_a = gr.Slider(
                        minimum=0, maximum=100, value=100, step=1, label="白场值"
                    )
                    gamma_a = gr.Slider(
                        minimum=0.1, maximum=5, value=1.0, step=0.1, label="伽马值"
                    )
                    contrast_a = gr.Slider(
                        minimum=0.1, maximum=5, value=1.0, step=0.1, label="对比度"
                    )
                    lightness_a = gr.Slider(
                        minimum=-100, maximum=100, value=0, step=1, label="明度"
                    )

                with gr.Row():
                    detail_strength_a = gr.Slider(
                        minimum=0, maximum=1, value=0.5, step=0.1, label="细节保留强度"
                    )

                output_image_a = gr.Image(label="结果 A")

            # 右侧参数组
            with gr.Column():
                gr.Markdown("### 参数组 B")
                with gr.Row():
                    tile_texture_b = gr.Checkbox(label="平铺纹理", value=True)
                    strength_b = gr.Slider(
                        minimum=0, maximum=100, value=20, step=1, label="深度置换强度"
                    )

                with gr.Row():
                    blur_radius_b = gr.Slider(
                        minimum=0, maximum=20, value=5, step=1, label="深度图模糊值"
                    )
                    lighting_strength_b = gr.Slider(
                        minimum=0, maximum=1, value=0.5, step=0.1, label="光照强度"
                    )

                with gr.Row():
                    black_point_b = gr.Slider(
                        minimum=0, maximum=100, value=0, step=1, label="黑场值"
                    )
                    white_point_b = gr.Slider(
                        minimum=0, maximum=100, value=100, step=1, label="白场值"
                    )
                    gamma_b = gr.Slider(
                        minimum=0.1, maximum=5, value=1.0, step=0.1, label="伽马值"
                    )
                    contrast_b = gr.Slider(
                        minimum=0.1, maximum=5, value=1.0, step=0.1, label="对比度"
                    )
                    lightness_b = gr.Slider(
                        minimum=-100, maximum=100, value=0, step=1, label="明度"
                    )
                with gr.Row():
                    detail_strength_b = gr.Slider(
                        minimum=0, maximum=1, value=0.5, step=0.1, label="细节保留强度"
                    )
                output_image_b = gr.Image(label="结果 B")

        with gr.Row():
            # 复制参数按钮
            copy_a_to_b = gr.Button("复制 A 到 B")
            copy_b_to_a = gr.Button("复制 B 到 A")
            # 生成结果按钮
            generate_both = gr.Button("生成对比结果", variant="primary")

        # 添加复制参数的功能
        def copy_params_a_to_b(
            tile_a,
            strength_a,
            blur_a,
            light_a,
            black_a,
            white_a,
            gamma_a,
            contrast_a,
            lightness_a,
            detail_strength_a,
        ):
            return (
                tile_a,
                strength_a,
                blur_a,
                light_a,
                black_a,
                white_a,
                gamma_a,
                contrast_a,
                lightness_a,
                detail_strength_a,
            )

        def copy_params_b_to_a(
            tile_b,
            strength_b,
            blur_b,
            light_b,
            black_b,
            white_b,
            gamma_b,
            contrast_b,
            lightness_b,
            detail_strength_b,
        ):
            return (
                tile_b,
                strength_b,
                blur_b,
                light_b,
                black_b,
                white_b,
                gamma_b,
                contrast_b,
                lightness_b,
                detail_strength_b,
            )

        # 设置复制按钮的事件处理
        copy_a_to_b.click(
            fn=copy_params_a_to_b,
            inputs=[
                tile_texture_a,
                strength_a,
                blur_radius_a,
                lighting_strength_a,
                black_point_a,
                white_point_a,
                gamma_a,
                contrast_a,
                lightness_a,
                detail_strength_a,
            ],
            outputs=[
                tile_texture_b,
                strength_b,
                blur_radius_b,
                lighting_strength_b,
                black_point_b,
                white_point_b,
                gamma_b,
                contrast_b,
                lightness_b,
                detail_strength_b,
            ],
        )

        copy_b_to_a.click(
            fn=copy_params_b_to_a,
            inputs=[
                tile_texture_b,
                strength_b,
                blur_radius_b,
                lighting_strength_b,
                black_point_b,
                white_point_b,
                gamma_b,
                contrast_b,
                lightness_b,
                detail_strength_b,
            ],
            outputs=[
                tile_texture_a,
                strength_a,
                blur_radius_a,
                lighting_strength_a,
                black_point_a,
                white_point_a,
                gamma_a,
                contrast_a,
                lightness_a,
                detail_strength_a,
            ],
        )

        # 生成两组结果
        def generate_comparison(
            texture, background, mask, texture_scale,  # 添加纹理缩放参数
            tile_a, strength_a, blur_a, light_a, black_a, white_a, gamma_a, contrast_a, lightness_a, detail_strength_a,
            tile_b, strength_b, blur_b, light_b, black_b, white_b, gamma_b, contrast_b, lightness_b, detail_strength_b,
        ):
            result_a = apply_combined_effects(
                texture, background, mask,
                texture_scale,  # 传入缩放系数
                tile_a, strength_a, blur_a, light_a, black_a, white_a, gamma_a, contrast_a, lightness_a, detail_strength_a
            )
            result_b = apply_combined_effects(
                texture, background, mask,
                texture_scale,  # 传入缩放系数
                tile_b, strength_b, blur_b, light_b, black_b, white_b, gamma_b, contrast_b, lightness_b, detail_strength_b
            )
            return result_a, result_b

        # 更新生成按钮的事件处理
        generate_both.click(
            fn=generate_comparison,
            inputs=[
                texture_image, background_image, mask_image, texture_scale,  # 添加纹理缩放参数
                tile_texture_a, strength_a, blur_radius_a, lighting_strength_a,
                black_point_a, white_point_a, gamma_a, contrast_a, lightness_a, detail_strength_a,
                tile_texture_b, strength_b, blur_radius_b, lighting_strength_b,
                black_point_b, white_point_b, gamma_b, contrast_b, lightness_b, detail_strength_b
            ],
            outputs=[output_image_a, output_image_b]
        )


# 启动应用
if __name__ == "__main__":
    demo.launch()
