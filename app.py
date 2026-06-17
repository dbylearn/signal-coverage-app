import streamlit as st
import pandas as pd
import io
import pydeck as pdk
from core.analyzer import load_and_clean_data, perform_spatial_join, DataValidationError

# 配置页面
st.set_page_config(page_title="信号塔空间覆盖分析", layout="wide", page_icon="📡")

# 页面标题
st.title("📡 信号塔空间覆盖分析系统")
st.markdown("上传信号塔、杆塔、变电站数据，自动基于球面距离(Haversine)高效计算覆盖情况。")

# 侧边栏文件上传
with st.sidebar:
    st.header("📂 数据上传")
    file_towers = st.file_uploader("1. 上传 信号塔.xlsx", type=['xlsx'])
    file_poles = st.file_uploader("2. 上传 杆塔.xlsx", type=['xlsx'])
    file_stations = st.file_uploader("3. 上传 变电站.xlsx", type=['xlsx'])
    
    run_btn = st.button("开始分析", type="primary", use_container_width=True)

def render_map(df_t, df_p, df_s):
    """渲染 PyDeck 地图"""
    layers = []
    
    # 添加信号塔图层 (红色面状覆盖区，设为最底层，降低透明度防遮挡)
    if not df_t.empty:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            df_t,
            get_position=["lng", "lat"],
            get_color="[200, 0, 0, 40]", # 透明度降至40
            get_radius="radius",
            pickable=True
        ))

    # 添加变电站图层 (蓝色，设为中间层)
    if not df_s.empty:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            df_s,
            get_position=["lng", "lat"],
            get_color="[0, 0, 200, 200]", # 提高不透明度至200
            get_radius=120,
            pickable=True
        ))
        
    # 添加杆塔图层 (绿色，体积最小，设为最顶层)
    if not df_p.empty:
        layers.append(pdk.Layer(
            "ScatterplotLayer",
            df_p,
            get_position=["lng", "lat"],
            get_color="[0, 200, 0, 200]", # 提高不透明度至200
            get_radius=80,
            pickable=True
        ))
    
    # 确定初始视角中心
    if not df_t.empty:
        center_lng, center_lat = df_t['lng'].mean(), df_t['lat'].mean()
    else:
        center_lng, center_lat = 116.40, 39.90
        
    view_state = pdk.ViewState(latitude=center_lat, longitude=center_lng, zoom=10, pitch=0)
    st.pydeck_chart(pdk.Deck(
        layers=layers, 
        initial_view_state=view_state, 
        tooltip={"text": "{name}"}
    ))

# 核心执行逻辑
if run_btn:
    if not (file_towers and file_poles and file_stations):
        st.warning("⚠️ 请先在左侧侧边栏上传所有必需的三个 Excel 文件。")
    else:
        try:
            with st.status("🚀 正在执行空间分析...", expanded=True) as status:
                st.write("1️⃣ 读取并清洗数据...")
                # 信号塔数据（容忍列名中带(米)的情况，我们只验证基本列）
                df_towers, invalid_t = load_and_clean_data(file_towers.getvalue(), ['信号塔名称', '信号塔坐标'], '信号塔坐标', '信号塔.xlsx')
                if invalid_t > 0:
                    st.warning(f"跳过 {invalid_t} 个坐标无效的信号塔")
                    
                df_poles, invalid_p = load_and_clean_data(file_poles.getvalue(), ['输电杆塔名称', '输电杆塔设备坐标'], '输电杆塔设备坐标', '杆塔.xlsx')
                if invalid_p > 0:
                    st.warning(f"跳过 {invalid_p} 个坐标无效的输电杆塔")
                    
                df_stations, invalid_s = load_and_clean_data(file_stations.getvalue(), ['变电站名称', '变电站坐标'], '变电站坐标', '变电站.xlsx')
                if invalid_s > 0:
                    st.warning(f"跳过 {invalid_s} 个坐标无效的变电站")
                
                st.write("2️⃣ 构建空间索引(BallTree)...")
                st.write("3️⃣ 计算并匹配设备覆盖关系...")
                # 执行空间连接
                result_df, map_t, map_p, map_s = perform_spatial_join(df_towers, df_poles, df_stations)
                
                status.update(label="✅ 分析完成！", state="complete", expanded=False)
                
            # 将计算结果存入 Session State，防止页面刷新丢失
            st.session_state['result_df'] = result_df
            st.session_state['map_t'] = map_t
            st.session_state['map_p'] = map_p
            st.session_state['map_s'] = map_s
            
        except DataValidationError as e:
            st.error(f"🛑 数据校验失败：{str(e)}")
        except Exception as e:
            st.error(f"❌ 发生未知错误：{str(e)}")

# UI：展示分析结果
if 'result_df' in st.session_state:
    st.divider()
    
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("🗺️ 空间分布预览")
        st.markdown("🔴 **信号塔**  &nbsp;&nbsp; 🟢 **杆塔** &nbsp;&nbsp; 🔵 **变电站**")
        render_map(st.session_state['map_t'], st.session_state['map_p'], st.session_state['map_s'])
        
    with col2:
        st.subheader("📊 分析结果数据表")
        # 展示数据表
        st.dataframe(st.session_state['result_df'], use_container_width=True, height=400)
        
        # 将 DataFrame 转换为 Excel 以供下载
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            st.session_state['result_df'].to_excel(writer, index=False)
        processed_data = output.getvalue()
        
        st.download_button(
            label="📥 下载完整分析结果 (Excel)",
            data=processed_data,
            file_name="空间关联分析结果.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
            use_container_width=True
        )
