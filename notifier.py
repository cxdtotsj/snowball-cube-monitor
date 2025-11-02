from datetime import datetime
from typing import Dict, List, Any
from pypushdeer import PushDeer
import requests


class PushWX:


    def __init__(self, pushkey: str):
        self.server=f'https://wx.xtuis.cn/{pushkey}.send'
        self.push_wx = requests.session()

    
    def send_markdown(self, text: str, desp: str):
        data = {
            'text': text,
            'desp': desp,
        }
        self.push_wx.post(url=self.server, data=data)



class Notifier:
    """通知管理类，负责格式化调仓变化信息并发送通知"""
    
    def __init__(self, pushkey: str, server: str = "https://api2.pushdeer.com", type_: str='WX'):
        """
        :param type_: PushDeer or WX
        """
        if type_ == 'WX':
            self.pushdeer = PushWX(pushkey=pushkey)
        else:
            self.pushdeer = PushDeer(server=server, pushkey=pushkey)
    
    def format_rebalancing_message(self, cube_name: str, cube_id: str, rebalancing_data: Dict[str, Any], is_first_time: bool = False) -> str:
        """
        格式化调仓变化信息
        
        Args:
            cube_name: 组合名称
            cube_id: 组合ID
            rebalancing_data: 调仓数据
            
        Returns:
            str: 格式化后的消息内容
        """
        # 解析调仓时间
        created_at = rebalancing_data.get('created_at', 0)
        if created_at:
            rebalancing_time = datetime.fromtimestamp(created_at / 1000).strftime('%Y-%m-%d %H:%M:%S')
        else:
            rebalancing_time = "未知时间"
        
        # 构建消息头部
        if is_first_time:
            message = f"📈 **组合监控启动 - 最近调仓信息**\n\n"
        else:
            message = f"📈 **组合调仓通知**\n\n"
        message += f"**组合：** {cube_name} ({cube_id})\n"
        message += f"**调仓时间：** {rebalancing_time}\n\n"
        
        # 解析持仓变化
        histories = rebalancing_data.get('rebalancing_histories', [])
        if not histories:
            message += "📊 **仓位变化：** 无具体变化记录\n"
            return message
        
        # 分类持仓变化
        new_positions = []      # 新增持仓
        closed_positions = []   # 清仓
        adjusted_positions = [] # 调整仓位
        
        for history in histories:
            stock_name = history.get('stock_name', '未知股票')
            stock_symbol = history.get('stock_symbol', '未知代码')
            current_weight = history.get('weight', 0)
            prev_weight = history.get('prev_weight_adjusted')
            
            if prev_weight is None:
                # 新增持仓
                new_positions.append({
                    'name': stock_name,
                    'symbol': stock_symbol,
                    'weight': current_weight
                })
            elif current_weight == 0 and prev_weight > 0:
                # 清仓
                closed_positions.append({
                    'name': stock_name,
                    'symbol': stock_symbol,
                    'prev_weight': prev_weight
                })
            elif current_weight != prev_weight:
                # 调整仓位
                change = current_weight - prev_weight
                adjusted_positions.append({
                    'name': stock_name,
                    'symbol': stock_symbol,
                    'prev_weight': prev_weight,
                    'current_weight': current_weight,
                    'change': change
                })
        
        message += "📊 **仓位变化：**\n"
        
        # 新增持仓
        if new_positions:
            message += "• **新增持仓：**\n"
            for pos in new_positions:
                message += f"  - {pos['name']} ({pos['symbol']}): 0% → {pos['weight']}%\n"
            message += "\n"
        
        # 减仓/清仓
        if closed_positions:
            message += "• **减仓/清仓：**\n"
            for pos in closed_positions:
                message += f"  - {pos['name']} ({pos['symbol']}): {pos['prev_weight']}% → 0% (清仓)\n"
            message += "\n"
        
        # 调整仓位
        if adjusted_positions:
            message += "• **调整仓位：**\n"
            for pos in adjusted_positions:
                direction = "↑" if pos['change'] > 0 else "↓"
                change_abs = abs(pos['change'])
                message += f"  - {pos['name']} ({pos['symbol']}): {pos['prev_weight']}% → {pos['current_weight']}% ({direction}{change_abs:.2f}%)\n"
            message += "\n"
        
        # # 现金比例变化
        # current_cash = rebalancing_data.get('cash', 0)
        # message += f"💰 **现金比例：** {current_cash}%\n"
        
        return message
    
    def send_rebalancing_notification(self, cube_name: str, cube_id: str, rebalancing_data: Dict[str, Any], is_first_time: bool = False) -> bool:
        """
        发送调仓通知
        
        Args:
            cube_name: 组合名称
            cube_id: 组合ID
            rebalancing_data: 调仓数据
            
        Returns:
            bool: 发送是否成功
        """
        try:
            message = self.format_rebalancing_message(cube_name, cube_id, rebalancing_data, is_first_time)
            
            # 发送Markdown格式的消息
            title = f"组合监控启动 - {cube_name}" if is_first_time else f"组合调仓通知 - {cube_name}"
            response = self.pushdeer.send_markdown(
                text=title,
                desp=message
            )
            
            print(f"通知发送成功: {cube_name} ({cube_id})")
            return True
            
        except Exception as e:
            print(f"发送通知失败: {e}")
            return False
