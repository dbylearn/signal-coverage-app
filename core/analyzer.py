import pandas as pd
import numpy as np
from sklearn.neighbors import BallTree
import streamlit as st

class DataValidationError(Exception):
    """自定义数据校验异常类"""
    pass

def parse_coordinates(coord_str):
    """
    解析坐标字符串，兼容中英文逗号。
    如果格式不合法或为空，返回 (NaN, NaN)。
    """
    if pd.isna(coord_str):
        return np.nan, np.nan
    
    # 替换中文逗号为英文并清理空格
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

def validate_columns(df, required_columns, file_name):
    """校验DataFrame是否包含必需的列"""
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        raise DataValidationError(f"上传的 {file_name} 文件中缺少必需的列: {', '.join(missing_cols)}")

@st.cache_data(show_spinner=False)
def load_and_clean_data(file_bytes, required_columns, coord_col, file_name):
    """
    读取并清洗数据，使用 @st.cache_data 进行缓存。
    注意：Streamlit缓存要求输入参数必须可哈希，传入文件的 bytes 形式或 st.file_uploader 的对象皆可。
    """
    try:
        df = pd.read_excel(file_bytes)
    except Exception as e:
        raise DataValidationError(f"无法读取文件 {file_name}，请确保它是有效的Excel文件。详情: {str(e)}")
        
    validate_columns(df, required_columns, file_name)
    
    # 解析坐标
    df[['lng', 'lat']] = df[coord_col].apply(lambda x: pd.Series(parse_coordinates(x)))
    
    # 过滤无效坐标
    invalid_mask = df['lng'].isna() | df['lat'].isna()
    invalid_count = invalid_mask.sum()
    df_valid = df[~invalid_mask].copy()
    
    return df_valid, invalid_count

@st.cache_data(show_spinner=False)
def build_spatial_index(lat_lng_array):
    """构建 BallTree 空间索引"""
    return BallTree(lat_lng_array, metric='haversine')

@st.cache_data(show_spinner=False)
def perform_spatial_join(df_towers, df_poles, df_stations):
    """
    执行核心的 BallTree 空间关联查询
    """
    # 为了避免修改被缓存的 df_towers 导致警告，这里创建一个副本
    df_result = df_towers.copy()
    
    EARTH_RADIUS_METERS = 6371000.0

    # 提取弧度坐标
    poles_rad = np.deg2rad(df_poles[['lat', 'lng']].values)
    stations_rad = np.deg2rad(df_stations[['lat', 'lng']].values)
    towers_rad = np.deg2rad(df_result[['lat', 'lng']].values)

    # 构建树
    tree_poles = build_spatial_index(poles_rad)
    tree_stations = build_spatial_index(stations_rad)

    # 处理覆盖半径（兼容两种列名）
    radius_col = '信号覆盖半径' if '信号覆盖半径' in df_result.columns else '信号覆盖半径(米)'
    radii_meters = df_result[radius_col].values
    radii_rad = radii_meters / EARTH_RADIUS_METERS

    # 批量查询
    poles_indices = tree_poles.query_radius(towers_rad, r=radii_rad)
    stations_indices = tree_stations.query_radius(towers_rad, r=radii_rad)

    # 提取名称用于映射
    pole_names = df_poles['输电杆塔名称'].values
    station_names = df_stations['变电站名称'].values

    # 组装结果列
    covered_poles_list = []
    covered_stations_list = []

    for i in range(len(df_result)):
        c_poles = pole_names[poles_indices[i]]
        c_stations = station_names[stations_indices[i]]
        covered_poles_list.append(";".join([str(name) for name in c_poles]) if len(c_poles) > 0 else "")
        covered_stations_list.append(";".join([str(name) for name in c_stations]) if len(c_stations) > 0 else "")

    df_result['覆盖输电杆塔名称'] = covered_poles_list
    df_result['覆盖变电站名称'] = covered_stations_list

    if '信号覆盖半径' in df_result.columns:
        df_result.rename(columns={'信号覆盖半径': '信号覆盖半径(米)'}, inplace=True)
        
    final_columns = ['信号塔名称', '信号塔坐标', '信号覆盖半径(米)', '覆盖输电杆塔名称', '覆盖变电站名称']
    
    # 提取地图所需数据 (统一使用 name 字段供 pydeck 显示 tooltip)
    map_t = df_result[['lng', 'lat', '信号塔名称', '信号覆盖半径(米)']].rename(columns={'信号塔名称': 'name', '信号覆盖半径(米)': 'radius'})
    map_p = df_poles[['lng', 'lat', '输电杆塔名称']].rename(columns={'输电杆塔名称': 'name'})
    map_s = df_stations[['lng', 'lat', '变电站名称']].rename(columns={'变电站名称': 'name'})
    
    return df_result[final_columns], map_t, map_p, map_s
