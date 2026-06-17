import pandas as pd
import numpy as np
from sklearn.neighbors import BallTree
import re
import sys

def parse_coordinates(coord_str):
    """
    解析坐标字符串，兼容中英文逗号。
    如果格式不合法或为空，返回 (NaN, NaN)。
    """
    if pd.isna(coord_str):
        return np.nan, np.nan
    
    # 将中文逗号替换为英文逗号并去除多余空格
    coord_str = str(coord_str).replace('，', ',').strip()
    parts = coord_str.split(',')
    
    if len(parts) != 2:
        return np.nan, np.nan
    
    try:
        lng = float(parts[0].strip())
        lat = float(parts[1].strip())
        return lng, lat
    except ValueError:
        return np.nan, np.nan

def process_data(towers_path, poles_path, stations_path, output_path):
    print("正在读取Excel数据...")
    try:
        df_towers = pd.read_excel(towers_path)
        df_poles = pd.read_excel(poles_path)
        df_stations = pd.read_excel(stations_path)
    except Exception as e:
        print(f"读取文件失败，请检查文件是否存在或已被占用。错误信息: {e}")
        sys.exit(1)

    print("正在解析并清洗坐标数据...")
    # 提取并解析坐标
    df_towers[['lng', 'lat']] = df_towers['信号塔坐标'].apply(lambda x: pd.Series(parse_coordinates(x)))
    df_poles[['lng', 'lat']] = df_poles['输电杆塔设备坐标'].apply(lambda x: pd.Series(parse_coordinates(x)))
    df_stations[['lng', 'lat']] = df_stations['变电站坐标'].apply(lambda x: pd.Series(parse_coordinates(x)))

    # 过滤掉无法解析的无效坐标（NaN），避免计算报错
    invalid_towers_mask = df_towers['lng'].isna() | df_towers['lat'].isna()
    if invalid_towers_mask.any():
        print(f"警告：跳过 {invalid_towers_mask.sum()} 个坐标格式无效或为空的信号塔。")
    df_towers_valid = df_towers[~invalid_towers_mask].copy()

    invalid_poles_mask = df_poles['lng'].isna() | df_poles['lat'].isna()
    if invalid_poles_mask.any():
        print(f"警告：跳过 {invalid_poles_mask.sum()} 个坐标格式无效或为空的输电杆塔。")
    df_poles_valid = df_poles[~invalid_poles_mask].copy()

    invalid_stations_mask = df_stations['lng'].isna() | df_stations['lat'].isna()
    if invalid_stations_mask.any():
        print(f"警告：跳过 {invalid_stations_mask.sum()} 个坐标格式无效或为空的变电站。")
    df_stations_valid = df_stations[~invalid_stations_mask].copy()

    print("正在构建空间索引(BallTree)...")
    # 地球平均半径，单位：米
    EARTH_RADIUS_METERS = 6371000.0

    # 将坐标转换为弧度，因为 BallTree 使用 Haversine 距离时要求输入为弧度 (纬度, 经度)
    # 注意顺序必须是 [纬度(lat), 经度(lng)]
    poles_rad = np.deg2rad(df_poles_valid[['lat', 'lng']].values)
    stations_rad = np.deg2rad(df_stations_valid[['lat', 'lng']].values)
    towers_rad = np.deg2rad(df_towers_valid[['lat', 'lng']].values)

    # 构建 BallTree
    # 为什么这里不用双重for循环？
    # 因为双重for循环的时间复杂度是 O(M * N)。如果信号塔和杆塔都上万条，需要计算上亿次，极其缓慢。
    # BallTree 是一种空间划分数据结构。它将相邻的点划分到一个"球"中，建立树状结构。
    # 在查询时，如果目标的搜索半径没有碰到某个"球"，就可以直接忽略那个"球"里的所有点，
    # 从而把时间复杂度降低到接近 O(M * log N)，哪怕是百万级数据也能在几秒内计算完毕。
    tree_poles = BallTree(poles_rad, metric='haversine')
    tree_stations = BallTree(stations_rad, metric='haversine')

    print("正在进行空间距离计算与关联查询...")
    # 提取覆盖半径。需要将米转换为弧度。弧度 = 距离 / 地球半径
    if '信号覆盖半径' in df_towers_valid.columns:
        radii_meters = df_towers_valid['信号覆盖半径'].values
    elif '信号覆盖半径(米)' in df_towers_valid.columns:
        radii_meters = df_towers_valid['信号覆盖半径(米)'].values
    else:
        print("错误：信号塔数据中找不到表示覆盖半径的列。")
        sys.exit(1)
        
    radii_rad = radii_meters / EARTH_RADIUS_METERS

    # 批量查询覆盖范围内的点
    # query_radius 返回的是一个数组，其每个元素是一个列表，代表该信号塔覆盖到的杆塔/变电站的行索引
    poles_indices = tree_poles.query_radius(towers_rad, r=radii_rad)
    stations_indices = tree_stations.query_radius(towers_rad, r=radii_rad)

    # 提取目标实体的名称数组用于映射
    pole_names = df_poles_valid['输电杆塔名称'].values
    station_names = df_stations_valid['变电站名称'].values

    # 组装结果
    covered_poles_list = []
    covered_stations_list = []

    # 遍历每个信号塔的查询结果
    for i in range(len(df_towers_valid)):
        # 根据索引获取真实名称
        c_poles = pole_names[poles_indices[i]]
        c_stations = station_names[stations_indices[i]]
        # 用分号拼接名称，如果没有则为空字符串
        covered_poles_list.append(";".join([str(name) for name in c_poles]) if len(c_poles) > 0 else "")
        covered_stations_list.append(";".join([str(name) for name in c_stations]) if len(c_stations) > 0 else "")

    df_towers_valid['覆盖输电杆塔名称'] = covered_poles_list
    df_towers_valid['覆盖变电站名称'] = covered_stations_list

    # 重命名列以满足输出要求
    df_towers_valid.rename(columns={'信号覆盖半径': '信号覆盖半径(米)'}, inplace=True)
    
    # 选择最终需要输出的列
    final_columns = ['信号塔名称', '信号塔坐标', '信号覆盖半径(米)', '覆盖输电杆塔名称', '覆盖变电站名称']
    df_result = df_towers_valid[final_columns]

    print(f"正在保存结果到 {output_path}...")
    df_result.to_excel(output_path, index=False)
    print("分析处理完成！")

if __name__ == "__main__":
    # 执行脚本：确保这三个文件与脚本在同一个目录下
    process_data(
        towers_path='信号塔.xlsx',
        poles_path='杆塔.xlsx',
        stations_path='变电站.xlsx',
        output_path='分析结果.xlsx'
    )
