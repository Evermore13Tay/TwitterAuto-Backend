#!/usr/bin/env python3
"""
快速检查登录状态脚本
"""

import sys
import os
import uiautomator2 as u2
from datetime import datetime

# 设备配置
DEVICES = [
    {"ip": "10.18.96.104", "u2_port": 5001, "name": "设备1"},
    {"ip": "10.18.96.104", "u2_port": 5002, "name": "设备2"},
    {"ip": "10.18.96.104", "u2_port": 5003, "name": "设备3"},
    {"ip": "10.18.96.104", "u2_port": 5004, "name": "设备4"},
]

# 对应账户
ACCOUNTS = [
    "9jZ4I1x6bBqs6",
    "z3DUt1z42AdGU2",
    "4V7VKslP1KWMsT",
    "f4K81fg7d2G4L1T"
]

def check_device_login_status(device, account):
    """检查单个设备的登录状态"""
    try:
        print(f"🔍 检查 {device['name']}({account}) - {device['ip']}:{device['u2_port']}")
        
        # 连接设备
        u2_d = u2.connect(f"{device['ip']}:{device['u2_port']}")
        
        # 检查连接状态
        try:
            app_info = u2_d.app_current()
            print(f"  📱 当前应用: {app_info.get('package', 'N/A')}")
            print(f"  🎯 Activity: {app_info.get('activity', 'N/A').split('.')[-1]}")
        except Exception as e:
            print(f"  ❌ 无法获取应用信息: {e}")
            return False
        
        # 检查登录状态指标
        login_indicators = [
            {'desc': '主页导航', 'xpath': '//*[@content-desc="Show navigation drawer"]'},
            {'desc': '底部导航栏', 'xpath': '//*[@resource-id="com.twitter.android:id/bottomNavigationBar"]'},
            {'desc': '首页标签', 'xpath': '//*[@content-desc="Home Tab"]'},
            {'desc': '发推按钮', 'xpath': '//*[@resource-id="com.twitter.android:id/tweet_button"]'},
            {'desc': '搜索按钮', 'xpath': '//*[@content-desc="Search and Explore"]'},
        ]
        
        found_indicators = []
        for indicator in login_indicators:
            try:
                if u2_d.xpath(indicator['xpath']).exists:
                    found_indicators.append(indicator['desc'])
            except Exception:
                continue
        
        if found_indicators:
            print(f"  ✅ 已登录 - 发现指标: {', '.join(found_indicators)}")
            return True
        else:
            print(f"  ❌ 未登录 - 未发现登录指标")
            
            # 检查是否在登录页面
            login_page_indicators = [
                '//*[@text="Log in"]',
                '//*[@text="Sign in"]',
                '//*[@resource-id="com.twitter.android:id/detail_text"]',
                '//*[contains(@text, "Phone, email, or username")]'
            ]
            
            for xpath in login_page_indicators:
                try:
                    if u2_d.xpath(xpath).exists:
                        print(f"  📝 检测到登录页面元素")
                        return False
                except Exception:
                    continue
            
            print(f"  ⚠️ 状态未知")
            return False
            
    except Exception as e:
        print(f"  ❌ 连接失败: {e}")
        return False

def main():
    """主检查函数"""
    print("🚀 批量登录状态检查")
    print("=" * 60)
    print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)
    
    results = []
    for device, account in zip(DEVICES, ACCOUNTS):
        status = check_device_login_status(device, account)
        results.append({
            'device': device['name'],
            'account': account,
            'logged_in': status
        })
        print()  # 空行分隔
    
    # 总结
    print("=" * 60)
    print("📊 登录状态总结")
    print("=" * 60)
    
    successful = [r for r in results if r['logged_in']]
    failed = [r for r in results if not r['logged_in']]
    
    print(f"✅ 已登录: {len(successful)}/{len(results)} ({len(successful)/len(results)*100:.1f}%)")
    print(f"❌ 未登录: {len(failed)}/{len(results)} ({len(failed)/len(results)*100:.1f}%)")
    
    if successful:
        print(f"\n✅ 已登录账户:")
        for r in successful:
            print(f"  {r['device']}: {r['account']}")
    
    if failed:
        print(f"\n❌ 未登录账户:")
        for r in failed:
            print(f"  {r['device']}: {r['account']}")

if __name__ == "__main__":
    main() 