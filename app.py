import streamlit as st
from neo4j import GraphDatabase
from pyvis.network import Network
import streamlit.components.v1 as components
import pandas as pd
import os
import time

# ================= 1. 页面配置 =================
st.set_page_config(
    page_title="EMC 智能知识图谱系统",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

if 'message' not in st.session_state:
    st.session_state.message = None
if 'msg_type' not in st.session_state:
    st.session_state.msg_type = None


# ================= 2. 核心函数 (重点修改了查询语句) =================

@st.cache_resource
def init_driver(uri, username, password):
    try:
        driver = GraphDatabase.driver(uri, auth=(username, password))
        driver.verify_connectivity()
        return driver
    except Exception as e:
        return None


# 修改点 1：使用 OPTIONAL MATCH 支持孤立节点
def get_data(driver, query_str, limit=50):
    cql = """
    MATCH (n) 
    WHERE n.name CONTAINS $name
    OPTIONAL MATCH (n)-[r]-(m)
    RETURN n, r, m LIMIT $limit
    """
    try:
        with driver.session() as session:
            result = session.run(cql, name=query_str, limit=limit)
            return [record for record in result]
    except:
        return []


# 修改点 2：全量查询也支持孤立节点
def get_full_data(driver, limit=300):
    cql = """
    MATCH (n) 
    OPTIONAL MATCH (n)-[r]->(m) 
    RETURN n, r, m LIMIT $limit
    """
    try:
        with driver.session() as session:
            result = session.run(cql, limit=limit)
            return [record for record in result]
    except:
        return []


def get_shortest_path(driver, start_name, end_name):
    cql = """
    MATCH (p1 {name: $start}), (p2 {name: $end}),
    path = shortestPath((p1)-[*]-(p2))
    RETURN path
    """
    try:
        with driver.session() as session:
            result = session.run(cql, start=start_name, end=end_name)
            paths = [record["path"] for record in result]
            data = []
            for p in paths:
                for rel in p.relationships:
                    data.append({'n': rel.start_node, 'r': rel, 'm': rel.end_node})
            return data
    except:
        return []


def get_dashboard_data(driver):
    cql = "MATCH (n) RETURN labels(n)[0] as Label, count(*) as Count ORDER BY Count DESC"
    try:
        with driver.session() as session:
            result = session.run(cql)
            return pd.DataFrame([r.values() for r in result], columns=['类型', '数量'])
    except:
        return pd.DataFrame()


def create_node_in_db(driver, label, name):
    query = f"MERGE (n:{label} {{name: $name}}) RETURN n"
    try:
        with driver.session() as session:
            session.run(query, name=name)
        return True, f"✅ 节点 '{name}' ({label}) 已保存"
    except Exception as e:
        return False, f"❌ 错误: {str(e)}"


def create_relationship_in_db(driver, start_name, end_name, rel_type):
    query = f"""
    MATCH (a), (b)
    WHERE a.name = $start AND b.name = $end
    MERGE (a)-[r:{rel_type}]->(b)
    RETURN type(r)
    """
    try:
        with driver.session() as session:
            result = session.run(query, start=start_name, end=end_name)
            if result.peek():
                return True, f"✅ 关联成功: {start_name} -> {end_name}"
            else:
                return False, "❌ 关联失败: 未找到节点"
    except Exception as e:
        return False, f"❌ 系统错误: {str(e)}"


def get_all_node_names(driver):
    query = "MATCH (n) RETURN n.name as name ORDER BY n.name LIMIT 2000"
    try:
        with driver.session() as session:
            result = session.run(query)
            return [record["name"] for record in result]
    except:
        return []


# ================= 3. 侧边栏 =================
with st.sidebar:
    st.title("⚙️ 系统配置")
    with st.expander("数据库连接", expanded=True):
        uri = st.text_input("URI", "neo4j+s://0eb1f778.databases.neo4j.io")
        user = st.text_input("用户名", "neo4j")
        password = st.text_input("密码", "HzwSrsruUEhXHTWQcHpbtU_1rWyPNaAdOHnes6uavKg", type="password")

    driver = init_driver(uri, user, password)

    if not driver:
        st.error("❌ 数据库未连接")
        st.stop()
    else:
        st.success("✅ 数据库已连接")

    st.markdown("---")
    mode = st.radio("功能模式", ["🔍 邻居探索", "🛣️ 路径分析"])

    search_query = ""
    path_start = ""
    path_end = ""
    show_all_graph = False

    if mode == "🔍 邻居探索":
        show_all_graph = st.checkbox("🌍 显示全量图谱", value=True)
        use_physics = st.checkbox("🌀 开启物理引力 (拖动)", value=True)
        if not show_all_graph:
            search_query = st.text_input("搜索关键词", placeholder="例如: 辐射")
        node_limit = st.slider("最大节点数", 20, 1000, 300)
    else:
        use_physics = True
        c1, c2 = st.columns(2)
        path_start = c1.text_input("起点", "电源")
        path_end = c2.text_input("终点", "干扰")

# ================= 4. 主界面 =================

st.title("⚡ EMC 电磁兼容知识图谱系统")

if st.session_state.message:
    if st.session_state.msg_type == 'success':
        st.success(st.session_state.message)
    else:
        st.error(st.session_state.message)
    st.session_state.message = None
    st.session_state.msg_type = None

tab_search, tab_stat, tab_admin = st.tabs(["📊 知识检索", "📈 数据看板", "🛠️ 录入与维护"])

# --- TAB 1: 知识图谱 (修改重点：处理 None 值) ---
with tab_search:
    data = []
    if mode == "🔍 邻居探索":
        if show_all_graph:
            data = get_full_data(driver, limit=node_limit)
        elif search_query:
            data = get_data(driver, search_query, node_limit)
    elif mode == "🛣️ 路径分析" and path_start and path_end:
        data = get_shortest_path(driver, path_start, path_end)

    if data:
        net = Network(height="600px", width="100%", bgcolor="#ffffff", font_color="black", notebook=False)
        net.barnes_hut(gravity=-2000, central_gravity=0.1, spring_length=150, spring_strength=0.04, damping=0.09,
                       overlap=0)

        color_map = {"Theory": "#FF6B6B", "Element": "#4ECDC4", "TestProblem": "#FFE66D", "Solution": "#1A535C",
                     "Case": "#FF9F1C", "Concept": "#C7C7C7"}
        node_ids = set()
        table_rows = []

        for record in data:
            # 1. 必定存在：源节点 'n'
            src = record['n']
            s_name = src.get('name', 'N/A')
            s_label = list(src.labels)[0] if src.labels else "Concept"

            # 添加源节点
            if src.element_id not in node_ids:
                net.add_node(src.element_id, label=s_name, title=s_name, color=color_map.get(s_label, "#97C2FC"),
                             size=20, font={'size': 14})
                node_ids.add(src.element_id)

            # 2. 可能为空：关系 'r' 和 目标节点 'm' (如果是孤立节点，这两个为 None)
            tgt = record.get('m')  # 使用 get，防止报错
            rel = record.get('r')

            # 只有当目标和关系都存在时，才画线和添加表格行
            if tgt is not None and rel is not None:
                t_name = tgt.get('name', 'N/A')
                t_label = list(tgt.labels)[0] if tgt.labels else "Concept"
                rel_type = rel.type

                # 添加目标节点
                if tgt.element_id not in node_ids:
                    net.add_node(tgt.element_id, label=t_name, title=t_name, color=color_map.get(t_label, "#97C2FC"),
                                 size=20, font={'size': 14})
                    node_ids.add(tgt.element_id)

                # 添加连线
                try:
                    net.add_edge(src.element_id, tgt.element_id, title=rel_type)
                except:
                    pass  # 防止重复边报错

                # 添加到表格
                table_rows.append({
                    "起点名称": s_name,
                    "起点类型": s_label,
                    "关系": rel_type,
                    "终点名称": t_name,
                    "终点类型": t_label
                })

        net.toggle_physics(use_physics)
        path = "html_files"
        if not os.path.exists(path): os.makedirs(path)
        net.save_graph(f"{path}/graph.html")

        with open(f"{path}/graph.html", 'r', encoding='utf-8') as f:
            components.html(f.read(), height=620, scrolling=False)

        st.markdown("### 📋 当前视图关系明细")
        if table_rows:
            df_rels = pd.DataFrame(table_rows)
            st.dataframe(
                df_rels,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "起点名称": st.column_config.TextColumn("起点", help="关系的发出者"),
                    "关系": st.column_config.TextColumn("关系类型", width="small"),
                    "终点名称": st.column_config.TextColumn("终点", help="关系的接收者"),
                }
            )
            st.caption(f"共展示 {len(df_rels)} 条关系数据。")
        else:
            if len(node_ids) > 0:
                st.info("当前显示的节点均为孤立节点，暂无关联关系。")
            else:
                st.info("当前视图无数据。")

    else:
        st.info("👋 暂无数据，请在‘🛠️ 录入与维护’中添加或调整搜索条件。")

# --- TAB 2 & TAB 3 (保持不变) ---
with tab_stat:
    df = get_dashboard_data(driver)
    if not df.empty:
        c1, c2 = st.columns([2, 1])
        c1.bar_chart(df, x="类型", y="数量")
        c2.dataframe(df, use_container_width=True)

with tab_admin:
    st.header("🛠️ 知识库维护")
    col_input1, col_input2 = st.columns(2)

    with col_input1:
        st.subheader("1. 新增节点")
        with st.container(border=True):
            node_name_input = st.text_input("节点名称", key="node_name_input")
            node_label_input = st.selectbox("节点类型", ["Concept", "Theory", "Element", "Case", "Solution"],
                                            key="node_label_input")
            if st.button("💾 保存节点", use_container_width=True):
                if node_name_input:
                    ok, msg = create_node_in_db(driver, node_label_input, node_name_input)
                    if ok:
                        st.session_state.message = msg
                        st.session_state.msg_type = 'success'
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("请输入节点名称")

    with col_input2:
        st.subheader("2. 建立关联")
        with st.container(border=True):
            all_nodes = get_all_node_names(driver)
            if not all_nodes: st.warning("暂无节点")
            s_node = st.selectbox("起点", all_nodes, key="s_node") if all_nodes else None
            t_node = st.selectbox("终点", all_nodes, key="t_node") if all_nodes else None
            r_type = st.selectbox("关系类型", ["RELATED_TO", "CAUSES", "SOLVES", "CONTAINS"], key="r_type")
            if st.button("🔗 连接关系", use_container_width=True):
                if s_node and t_node and s_node != t_node:
                    ok, msg = create_relationship_in_db(driver, s_node, t_node, r_type)
                    if ok:
                        st.session_state.message = msg
                        st.session_state.msg_type = 'success'
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.error("请选择有效节点")

    st.markdown("---")
    st.subheader("📂 3. CSV 关系文件展示")
    uploaded_file = st.file_uploader("上传 CSV 文件", type=["csv"])
    if uploaded_file is not None:
        try:
            df_csv = pd.read_csv(uploaded_file)
            st.success(f"✅ 文件上传成功！共 {len(df_csv)} 条")
            st.dataframe(df_csv, use_container_width=True, hide_index=True, height=300)
        except Exception as e:
            st.error(f"无法读取: {e}")

