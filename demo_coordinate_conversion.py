#!/usr/bin/env python3
"""
u2坐标转MytRpc坐标转换演示
"""

def convert_u2_to_mytrpc(u2_x, u2_y, screen_width, screen_height):
    """
    将u2相对坐标转换为MytRpc绝对坐标
    
    Args:
        u2_x: u2的相对x坐标 (0.0-1.0)
        u2_y: u2的相对y坐标 (0.0-1.0)
        screen_width: 屏幕宽度(像素)
        screen_height: 屏幕高度(像素)
    
    Returns:
        tuple: (mytrpc_x, mytrpc_y) 绝对坐标
    """
    mytrpc_x = int(u2_x * screen_width)
    mytrpc_y = int(u2_y * screen_height)
    return mytrpc_x, mytrpc_y

if __name__ == "__main__":
    print("🧪 u2坐标转MytRpc坐标转换演示")
    print("=" * 50)
    
    # 用户提供的u2坐标
    u2_x, u2_y = 0.644, 0.947
    
    # 常见屏幕尺寸示例
    screen_sizes = [
        (720, 1280, "720p"),
        (1080, 1920, "1080p"),
        (1440, 2560, "1440p")
    ]
    
    print(f"u2相对坐标: d.click({u2_x}, {u2_y})")
    print("\n转换结果:")
    print("-" * 50)
    
    for width, height, name in screen_sizes:
        mytrpc_x, mytrpc_y = convert_u2_to_mytrpc(u2_x, u2_y, width, height)
        print(f"{name:>8} ({width}x{height}): MytRpc({mytrpc_x}, {mytrpc_y})")
    
    print("\n转换公式:")
    print("mytrpc_x = int(u2_x × screen_width)")
    print("mytrpc_y = int(u2_y × screen_height)")
    
    print("\nMytRpc点击代码:")
    print("mytapi.touchDown(finger_id, mytrpc_x, mytrpc_y)")
    print("time.sleep(1.5)")
    print("mytapi.touchUp(finger_id, mytrpc_x, mytrpc_y)")
    
    print("\n完整示例代码:")
    print(f"""
# 获取屏幕尺寸
screen_width, screen_height = u2_device.window_size()

# u2相对坐标
u2_x, u2_y = {u2_x}, {u2_y}

# 转换为MytRpc绝对坐标
mytrpc_x = int(u2_x * screen_width)
mytrpc_y = int(u2_y * screen_height)

# 使用MytRpc点击
finger_id = 0
mytapi.touchDown(finger_id, mytrpc_x, mytrpc_y)
time.sleep(1.5)
mytapi.touchUp(finger_id, mytrpc_x, mytrpc_y)
    """.strip()) 