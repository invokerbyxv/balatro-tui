"""工具函数模块"""

import random


def format_score(chips, mult):
    """格式化分数显示"""
    score = chips * mult
    return f"{chips} × {mult} = {score}"


def format_number(num):
    """格式化大数字显示"""
    if num >= 1000000:
        return f"{num/1000000:.1f}M"
    elif num >= 1000:
        return f"{num/1000:.1f}K"
    return str(num)


def get_rarity_color(rarity):
    """获取稀有度颜色代码"""
    colors = {
        1: "$primary",
        2: "$warning",
        3: "$error",
        4: "$success"
    }
    return colors.get(rarity, "$default")


def shuffle_list(lst):
    """洗牌算法"""
    result = lst.copy()
    random.shuffle(result)
    return result


def get_random_item(lst, count=1):
    """随机获取物品"""
    items = shuffle_list(lst)[:count]
    return items[0] if count == 1 else items


def clamp(value, min_val, max_val):
    """限制数值范围"""
    return max(min_val, min(value, max_val))


def calculate_discount(price, discount_percent):
    """计算折扣价格"""
    return int(price * (100 - discount_percent) / 100)


def is_even(num):
    """判断是否为偶数"""
    return num % 2 == 0


def is_odd(num):
    """判断是否为奇数"""
    return num % 2 != 0


def get_card_suit_symbol(suit):
    """获取花色符号"""
    symbols = {
        "Spades": "♠",
        "Hearts": "♥",
        "Clubs": "♣",
        "Diamonds": "♦"
    }
    return symbols.get(suit, "?")


def get_card_color(suit):
    """获取花色颜色"""
    red_suits = ["Hearts", "Diamonds"]
    return "red" if suit in red_suits else "black"


def validate_hand(cards):
    """验证手牌有效性"""
    if not cards:
        return False, "手牌为空"
    
    if len(cards) > 8:
        return False, "手牌超过 8 张"
    
    return True, "有效"


def create_id():
    """创建唯一 ID"""
    import uuid
    return str(uuid.uuid4())[:8]


def safe_get(dictionary, key, default=None):
    """安全获取字典值"""
    try:
        return dictionary[key]
    except (KeyError, TypeError):
        return default


def parse_int(value, default=0):
    """安全解析整数"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def percentage_to_float(percentage):
    """百分比转小数"""
    try:
        return float(percentage.rstrip('%')) / 100
    except (ValueError, AttributeError):
        return 0.0
