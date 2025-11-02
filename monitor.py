import json
import time
import signal
import sys
from datetime import datetime, time as dt_time
from typing import Dict, List, Any
import pytz
import pysnowball as ball

from storage import Storage
from notifier import Notifier


class SnowballMonitor:
    """雪球组合监控器"""
    
    def __init__(self, config_file: str = "config.json"):
        self.config = self._load_config(config_file)
        self.storage = Storage()
        self.notifier = None
        self.running = True
        
        # 设置信号处理器，支持优雅停止
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 初始化雪球API
        ball.set_token(self.config['snowball']['token'])
        
        # 初始化通知器
        if self.config['pushdeer']['pushkey'] != "your_pushkey_here":
            self.notifier = Notifier(
                pushkey=self.config['pushdeer']['pushkey'],
                server=self.config['pushdeer']['server'],
                type_=self.config['pushdeer']['type_']
            )
        else:
            print("警告: PushDeer pushkey未配置，将不会发送通知")
    
    def _load_config(self, config_file: str) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"加载配置文件失败: {e}")
            sys.exit(1)
    
    def _signal_handler(self, signum, frame):
        """信号处理器，用于优雅停止"""
        print(f"\n收到停止信号 {signum}，正在优雅停止...")
        self.running = False
    
    def _is_in_active_hours(self) -> bool:
        """检查当前时间是否在活跃时间段内"""
        try:
            active_hours = self.config['monitor']['active_hours']
            timezone = pytz.timezone(active_hours['timezone'])
            now = datetime.now(timezone)
            
            start_time = dt_time.fromisoformat(active_hours['start'])
            end_time = dt_time.fromisoformat(active_hours['end'])
            current_time = now.time()
            
            return start_time <= current_time <= end_time
        except Exception as e:
            print(f"检查活跃时间失败: {e}")
            return True  # 出错时默认为活跃状态
    
    def _get_latest_rebalancing(self, cube_id: str) -> Dict[str, Any]:
        """获取组合的最新调仓记录"""
        try:
            # 获取最新的调仓记录（只获取前10条）
            result = ball.rebalancing_history(cube_id, 10, 1)
            
            if result and 'list' in result and result['list']:
                for item in result['list']:
                    if item['status'] == 'success':
                        return item
            else:
                return {}
        except Exception as e:
            print(f"获取组合 {cube_id} 调仓记录失败: {e}")
            return {}
    
    def _check_cube_changes(self, cube_config: Dict[str, str]) -> bool:
        """
        检查单个组合的调仓变化
        
        Args:
            cube_config: 组合配置，包含id和name
            
        Returns:
            bool: 是否发现新的调仓变化
        """
        cube_id = cube_config['id']
        cube_name = cube_config['name']
        
        # 获取最新调仓记录
        latest_rebalancing = self._get_latest_rebalancing(cube_id)
        if not latest_rebalancing:
            return False
        
        latest_id = latest_rebalancing.get('id')
        if not latest_id:
            return False
        
        # 检查是否是新的调仓记录
        last_known_id = self.storage.get_last_rebalancing_id(cube_id)
        
        if last_known_id is None:
            # 首次运行，记录当前最新ID并发送最近一次调仓通知
            print(f"首次监控组合 {cube_name} ({cube_id})，发送最近调仓信息: {latest_id}")

            # 发送最近一次调仓的通知
            if self.notifier:
                self.notifier.send_rebalancing_notification(cube_name, cube_id, latest_rebalancing, is_first_time=True)

            self.storage.update_last_rebalancing_id(cube_id, latest_id)
            return True
        
        if latest_id > last_known_id:
            # 发现新的调仓记录
            print(f"发现组合 {cube_name} ({cube_id}) 新调仓: {latest_id}")
            
            # 发送通知
            if self.notifier:
                self.notifier.send_rebalancing_notification(cube_name, cube_id, latest_rebalancing)
            
            # 更新记录
            self.storage.update_last_rebalancing_id(cube_id, latest_id)
            return True
        
        return False
    
    def _monitor_cycle(self):
        """执行一次监控循环"""
        if not self._is_in_active_hours():
            return
        
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始检查组合调仓...")
        
        cubes = self.config['monitor']['cubes']
        changes_found = False
        
        for cube_config in cubes:
            try:
                if self._check_cube_changes(cube_config):
                    changes_found = True
            except Exception as e:
                print(f"检查组合 {cube_config.get('name', 'Unknown')} 时出错: {e}")
        
        if not changes_found:
            print("未发现新的调仓变化")
    
    def run(self):
        """启动监控"""
        print("雪球组合监控器启动...")
        print(f"监控组合数量: {len(self.config['monitor']['cubes'])}")
        print(f"检查间隔: {self.config['monitor']['check_interval']}秒")
        print(f"活跃时间: {self.config['monitor']['active_hours']['start']} - {self.config['monitor']['active_hours']['end']}")
        print("按 Ctrl+C 停止监控\n")
        
        while self.running:
            try:
                if self._is_in_active_hours():
                    self._monitor_cycle()
                    sleep_time = self.config['monitor']['check_interval']
                else:
                    current_time = datetime.now().strftime('%H:%M:%S')
                    print(f"[{current_time}] 当前时间不在活跃时间段内，等待中...")
                    sleep_time = self.config['monitor'].get('sleep_interval_inactive', 300)
                
                # 分段睡眠，以便能够及时响应停止信号
                for _ in range(sleep_time):
                    if not self.running:
                        break
                    time.sleep(1)
                    
            except Exception as e:
                print(f"监控循环出错: {e}")
                time.sleep(60)  # 出错时等待1分钟再继续
        
        print("监控器已停止")


if __name__ == "__main__":
    monitor = SnowballMonitor()
    monitor.run()
