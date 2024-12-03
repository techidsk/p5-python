from wand.image import Image


def create_tiled_texture(texture, target_width, target_height, scale_factor=1.0):
    """
    创建平铺纹理图像
    
    参数:
        texture: Image, 纹理图像
        target_width: int, 目标宽度
        target_height: int, 目标高度
        scale_factor: float, 纹理缩放系数 (>0)
    """
    # 计算缩放后的纹理尺寸
    texture_width = int(texture.width * scale_factor)
    texture_height = int(texture.height * scale_factor)
    
    # 先缩放纹理
    with texture.clone() as scaled_texture:
        scaled_texture.resize(texture_width, texture_height)
        
        with Image(width=target_width, height=target_height) as tiled:
            # 计算需要重复的次数
            cols = (target_width + texture_width - 1) // texture_width
            rows = (target_height + texture_height - 1) // texture_height
            
            # 平铺纹理
            for y in range(rows):
                for x in range(cols):
                    tiled.composite(
                        scaled_texture, 
                        left=x * texture_width, 
                        top=y * texture_height
                    )
            
            # 裁剪到目标尺寸
            tiled.crop(width=target_width, height=target_height)
            return tiled.clone()


def composite_images(texture_path, background_path, mask_path, tile=False):
    """
    将纹理图和背景图按照mask进行合成

    参数:
        texture_path: str, 纹理图路径
        background_path: str, 背景图路径
        mask_path: str, 遮罩图路径（黑白图片）
        tile: bool, 是否平铺纹理

    返回:
        Image对象，合成后的图片
    """
    with Image(filename=texture_path) as texture:
        with Image(filename=background_path) as background:
            with Image(filename=mask_path) as mask:
                # 调整mask尺寸以匹配背景图
                mask.resize(background.width, background.height)

                # 如果需要平铺纹理
                if tile:
                    texture = create_tiled_texture(
                        texture, background.width, background.height
                    )

                # 简单的遮罩合成
                with background.clone() as result:
                    # 应用遮罩到纹理
                    texture.composite(mask, operator="copy_opacity")
                    # 合成到背景
                    result.composite(texture, operator="multiply")
                    final = result.clone()

    return final


def generate_lighting_map(depth_map: Image, background: Image, mask: Image, lighting_strength=0.5, light_color="grey48"):
    """
    基于背景图和深度图生成光照图
    
    参数:
        depth_map: Wand.Image 对象，深度图
        background: Wand.Image 对象，背景图
        mask: Wand.Image 对象，遮罩图
        lighting_strength: float, 光照强度 (0-1)
        light_color: str, 光照颜色
    """
    with depth_map.clone() as lighting_map:
        # 从景图提取亮度信息
        with background.clone() as bg_lighting:
            bg_lighting.transform_colorspace('gray')
            bg_lighting.normalize()
            
            # 结合深度图和背景亮度
            lighting_map.composite(bg_lighting, operator='multiply')
            
            
        # 调整光照强度
        lighting_map.evaluate("subtract", lighting_strength)
        lighting_map.background_color = "grey50"
        lighting_map.alpha_channel = "remove"
        

        # 创建最终的光照层
        with Image(
            width=background.width, height=background.height, background=light_color
        ) as light_layer:
            light_layer.composite(lighting_map, operator="multiply")
            # 应用遮罩
            light_layer.composite(mask, operator="copy_opacity")
            
            return light_layer.clone()

def adjust_levels(image: Image, black_point=0, white_point=100, gamma=1.0, contrast=1.0, lightness=0):
    """
    调整图像的色阶、伽马、对比度和明度
    
    参数:
        image: Image, 输入图像
        black_point: float, 黑场值 (0-100)
        white_point: float, 白场值 (0-100)
        gamma: float, 伽马值 (0.1-5.0)
        contrast: float, 对比度调整 (0.1-5.0)
        lightness: float, 明度调整 (-100 到 100)
               < 0 降低明度
               > 0 提高明度
    """
    with image.clone() as adjusted:
        # 1. 首先应用色阶调整（包括伽马）
        adjusted.level(
            black=black_point/100,
            white=white_point/100,
            gamma=gamma,
            channel='all'
        )
        
        # 2. 调整对比度
        if contrast != 1.0:
            adjusted.sigmoidal_contrast(
                sharpen=True,
                strength=contrast * 3,
                midpoint=0.5 * adjusted.quantum_range
            )
            
        # 3. 调整明度
        if lightness != 0:
            # 使用 modulate 调整明度
            # 100 是原始明度，大于100增加明度，小于100降低明度
            adjusted.modulate(brightness=100 + lightness)
            
        return adjusted.clone()

def tint_masked_area(background: Image, mask: Image, black_point=0, white_point=100, gamma=1.0, contrast=1.0, lightness=0):
    """
    对背景图的遮罩区域进行黑白处理，并调整色阶
    """
    with background.clone() as result:
        with background.clone() as bw_bg:
            bw_bg.transform_colorspace('gray')
            
            # 调整色阶、对比度和明度
            bw_bg = adjust_levels(
                bw_bg,
                black_point=black_point,
                white_point=white_point,
                gamma=gamma,
                contrast=contrast,
                lightness=lightness
            )
            
            # 使用遮罩将黑白区域合成到原图
            bw_bg.composite(mask, operator="copy_opacity")
            result.composite(bw_bg, operator="over")
            
        return result.clone()

def extract_high_frequency(image: Image, mask: Image, blur_radius=0.5):
    """
    提取图像的高频细节，保持灰色底色
    
    参数:
        image: Image, 输入图像
        mask: Image, 遮罩图像
        blur_radius: float, 高斯模糊半径
    """
    with image.clone() as high_freq:
        # 先转换为灰度
        high_freq.transform_colorspace('gray')
        
        # 创建模糊版本
        with high_freq.clone() as blurred:
            blurred.gaussian_blur(sigma=blur_radius)
            
            # 提取高频细节 (原图 - 模糊图)
            high_freq.composite(blurred, operator='difference')
            
            # 调整对比度使细节更明显
            high_freq.normalize()
            
            # 创建灰色背景
            with Image(width=image.width, height=image.height, background='gray50') as gray_bg:
                # 将高频细节叠加到灰色背景上
                gray_bg.composite(high_freq, operator='overlay')
                
                # 最后应用遮罩
                gray_bg.composite(mask, operator="copy_opacity")
                
                return gray_bg.clone()

def composite_with_lighting(texture: Image, background: Image, mask: Image, lighting_map: Image, 
                          lighting_strength=0.5, black_point=0, white_point=100, 
                          gamma=1.0, contrast=1.0, lightness=0, detail_strength=0.5):
    """
    将纹理图、光照图和背景图进行合成，并保留原图细节
    """
    # 提取背景图的高频细节（包含遮罩）
    high_freq = extract_high_frequency(background, mask)
    
    # 进行正常的合成处理
    background = tint_masked_area(
        background,
        mask,
        black_point=black_point,
        white_point=white_point,
        gamma=gamma,
        contrast=contrast,
        lightness=lightness
    )
    
    # 应用遮罩到纹理
    with texture.clone() as masked_texture:
        masked_texture.composite(mask, operator="copy_opacity")
        
        # 在背景上应用光照和纹理
        with background.clone() as result:
            with lighting_map.clone() as adjusted_lighting:
                adjusted_lighting.transparentize(1 - lighting_strength)
                result.composite(adjusted_lighting, operator="hard_light")
            
            # 合成纹理
            result.composite(masked_texture, operator="multiply")
            
            # 叠加高频细节
            if detail_strength > 0:
                with high_freq.clone() as details:
                    # 调整细节强度
                    details.evaluate('multiply', detail_strength)
                    # 叠加细节（已经包含遮罩，不需要再次应用）
                    result.composite(details, operator='overlay')
            
            return result.clone()
