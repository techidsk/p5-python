from wand.image import Image
from wand.display import display
import numpy as np

def displacement_mapping(original_path, depth_path, strength=1.0):
    """
    对图片进行凹凸置换
    
    参数:
        original_path: str, 原始图片路径
        depth_path: str, 深度图路径
        strength: float, 置换强度，默认为1.0
    
    返回:
        Image对象，处理后的图片
    """
    
    with Image(filename=original_path) as original:
        with Image(filename=depth_path) as depth:
            # 确保深度图和原图尺寸一致
            depth.resize(original.width, original.height)
            
            # 创建位移图像
            with original.clone() as displaced:
                # 使用 composite 方法和 displace 操作符进行位移
                displaced.composite(depth, operator='displace', 
                                    arguments=f'{strength},{strength}')
                
                # 克隆结果
                result = displaced.clone()
    
    return result

# 使用示例
if __name__ == "__main__":
    # 示例用法
    original_image_path = "input.jpg"
    depth_map_path = "depth.jpg"
    
    # 进行凹凸置换
    result = displacement_mapping(original_image_path, depth_map_path, strength=20.0)
    
    # 保存结果
    result.save(filename="output.jpg") 