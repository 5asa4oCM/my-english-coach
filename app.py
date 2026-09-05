import streamlit as st
import random
import re
import io
import json
from gtts import gTTS
from openai import OpenAI
from supabase import create_client, Client
from pypdf import PdfReader

try:
    import docx
except ImportError:
    docx = None

# ==================== 1. UI 与 侧边栏配置 ====================
st.set_page_config(page_title="多语种自适应看板 (完美版)", page_icon="🌎", layout="wide")

st.sidebar.title("⚙️ 云端系统设置")
api_key = st.sidebar.text_input("AI API Key", type="password", value=st.session_state.get("api_key", ""))
base_url = st.sidebar.text_input("AI Base URL", value="https://api.deepseek.com")
model_name = st.sidebar.selectbox("选择模型", ["deepseek-chat", "gpt-4o-mini", "gemini-1.5-flash"], index=0)

st.sidebar.markdown("---")
supa_url = st.sidebar.text_input("Supabase URL", value=st.session_state.get("supa_url", ""))
supa_key = st.sidebar.text_input("Supabase Key", type="password", value=st.session_state.get("supa_key", ""))

if api_key: st.session_state["api_key"] = api_key
if base_url: st.session_state["base_url"] = base_url
if model_name: st.session_state["model_name"] = model_name
if supa_url: st.session_state["supa_url"] = supa_url
if supa_key: st.session_state["supa_key"] = supa_key

def get_llm_client():
    if not st.session_state.get("api_key"): return None
    return OpenAI(api_key=st.session_state["api_key"], base_url=st.session_state["base_url"])

def get_supabase_client():
    if not st.session_state.get("supa_url") or not st.session_state.get("supa_key"): return None
    try: return create_client(st.session_state["supa_url"], st.session_state["supa_key"])
    except Exception: return None

def generate_audio(text, lang='en'):
    try:
        clean_text = re.sub(r'[*_`#]', '', text)
        tts = gTTS(text=clean_text[:200], lang=lang, tld='com')
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception: return None

def extract_text_from_pdf(file_obj):
    reader = PdfReader(file_obj)
    text = "".join([page.extract_text() or "" for page in reader.pages])
    return text

def extract_text_from_docx(file_obj):
    if docx is None: return ""
    doc = docx.Document(file_obj)
    return '\n'.join([para.text for para in doc.paragraphs])

# 初始化状态
if "current_l0" not in st.session_state: st.session_state.current_l0 = None
if "current_l1" not in st.session_state: st.session_state.current_l1 = None
if "show_l1_meaning" not in st.session_state: st.session_state.show_l1_meaning = False
if "l2_quiz" not in st.session_state: st.session_state.l2_quiz = None
if "active_oral_card" not in st.session_state: st.session_state.active_oral_card = None
if "show_oral_answer" not in st.session_state: st.session_state.show_oral_answer = False

tab_learn, tab_l2, tab_oral, tab_cards, tab_manage, tab_plan = st.tabs([
    "📚 词汇漏斗", "🎯 实战输出(L2)", "🗣️ 口语闪卡", "🗂️ 词汇闪卡(总览)", "📂 云端管理", "🗓️ 计划"
])

# ==================== Tab 1: 词汇漏斗 (Level 0 & Level 1) ====================
with tab_learn:
    st.subheader("📚 每日双语提取训练")
    lang_choice = st.radio("选择当前训练语种", ["🇬🇧 英语 (EN)", "🇯🇵 日语 (JP)"], horizontal=True)
    db_lang = "EN" if "EN" in lang_choice else "JP"
    
    db = get_supabase_client()
    if not db:
        st.warning("请在左侧配置数据库连接。")
    else:
        l0_words = db.table("vocab").select("*").eq("language", db_lang).eq("level", 0).execute().data
        l1_words = db.table("vocab").select("*").eq("language", db_lang).eq("level", 1).execute().data
        st.write(f"📊 **当前进度 ({db_lang})：** 待速览(L0): `{len(l0_words)}` 个 | 待闪卡回忆(L1): `{len(l1_words)}` 个")
        st.markdown("---")
        
        col_l0, col_l1 = st.columns(2)
        
        with col_l0:
            st.markdown("#### 🆕 Level 0: 托福新词速览")
            st.caption("注：四级词汇不进入此环节，直接空降 L1。")
            if l0_words:
                if not st.session_state.current_l0 or st.session_state.current_l0['language'] != db_lang:
                    st.session_state.current_l0 = random.choice(l0_words)
                w = st.session_state.current_l0
                
                st.info(f"### {w['word']}")
                st.markdown(f"🏷️ **来源:** `{w.get('tag', '未知')}` | 🗣️ **音标:** `{w.get('phonetic', '无')}`")
                st.markdown(f"💡 **含义:** `{w.get('meaning', '暂无记录')}`")
                if w.get('example'):
                    st.write(f"📖 **原著例句:** _{w['example']}_")
                
                if st.button("🧠 获取 AI 深度解析", key="hint_l0"):
                    llm = get_llm_client()
                    if llm:
                        hint_prompt = f"告诉我单词 '{w['word']}' 的中文意思和词性。如果是日语请附带假名。如果是英语请给一个常考短语。"
                        resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": hint_prompt}], temperature=0.3)
                        st.success(resp.choices[0].message.content)
                        
                if st.button("✅ 记住了，推入 Level 1", type="primary", use_container_width=True):
                    db.table("vocab").update({"level": 1}).eq("id", w["id"]).execute()
                    st.session_state.current_l0 = None
                    st.rerun()
            else:
                st.success("今日 L0 任务已清空！")
                
        with col_l1:
            st.markdown("#### 🧠 Level 1: 3秒无声回忆")
            if l1_words:
                if not st.session_state.current_l1 or st.session_state.current_l1['language'] != db_lang:
                    weights = [float(x.get("weight", 1.0)) for x in l1_words]
                    st.session_state.current_l1 = random.choices(l1_words, weights=weights, k=1)[0]
                    st.session_state.show_l1_meaning = False
                
                w1 = st.session_state.current_l1
                st.warning(f"## {w1['word']}")
                st.markdown(f"🏷️ **分类:** `{w1.get('tag', '未知')}`")
                
                if not st.session_state.show_l1_meaning:
                    if st.button("👀 点击核对答案", use_container_width=True):
                        st.session_state.show_l1_meaning = True
                        st.rerun()
                else:
                    st.markdown(f"🗣️ **音标:** `{w1.get('phonetic', '无')}`")
                    
                    # 优先显示库里保存的中文，如果没有再调用大模型
                    if w1.get('meaning'):
                        st.success(f"**核心含义：** {w1['meaning']}")
                    else:
                        llm = get_llm_client()
                        if llm:
                            resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": f"给出 '{w1['word']}' 的极简中文意思。"}], temperature=0.1)
                            st.success(f"**含义：** {resp.choices[0].message.content.strip()}")
                            
                    if w1.get('example'):
                        st.write(f"📖 **例句提示:** _{w1['example']}_")
                    
                    c1, c2, c3 = st.columns(3)
                    with c1:
                        if st.button("🟢 认识 (进L2)", use_container_width=True):
                            db.table("vocab").update({"level": 2, "weight": 1.0, "score": 5}).eq("id", w1["id"]).execute()
                            st.session_state.current_l1 = None
                            st.rerun()
                    with c2:
                        if st.button("🟡 模糊", use_container_width=True):
                            db.table("vocab").update({"weight": min(float(w1.get("weight",1.0))*1.5, 10.0), "score": 3}).eq("id", w1["id"]).execute()
                            st.session_state.current_l1 = None
                            st.rerun()
                    with c3:
                        if st.button("🔴 忘记", use_container_width=True):
                            db.table("vocab").update({"weight": min(float(w1.get("weight",1.0))*2.5, 10.0), "score": 1}).eq("id", w1["id"]).execute()
                            st.session_state.current_l1 = None
                            st.rerun()
            else:
                st.success("今日 L1 任务已清空！")

# ==================== Tab 2: 强迫造句/变形 (Level 2) ====================
with tab_l2:
    st.subheader("🎯 Level 2: 实战输出与变形训练")
    l2_lang = st.radio("选择 L2 实战语种", ["🇬🇧 英语 (EN)", "🇯🇵 日语 (JP)"], horizontal=True)
    db_lang_l2 = "EN" if "EN" in l2_lang else "JP"
    
    db = get_supabase_client()
    llm = get_llm_client()
    
    if db and llm:
        l2_words = db.table("vocab").select("*").eq("language", db_lang_l2).eq("level", 2).execute().data
        
        if len(l2_words) < (3 if db_lang_l2 == "EN" else 2):
            st.warning(f"当前 L2 库中词汇太少。请先去 Tab 1 背词！")
        else:
            if st.button("🎲 抽取词汇，生成 AI 挑战", type="primary", use_container_width=True):
                with st.spinner("AI 正在构思挑战..."):
                    k = 3 if db_lang_l2 == "EN" else random.choice([1, 2])
                    weights = [float(x.get("weight", 1.0)) for x in l2_words]
                    selected = random.choices(l2_words, weights=weights, k=k)
                    word_list = [x['word'] for x in selected]
                    
                    if db_lang_l2 == "EN":
                        prompt = f"基于英语单词：{word_list}。用中文设定一个日常或学术场景。要求：合理串联这三个词，只要中文描述，字数50以内。"
                    else:
                        prompt = f"基于日语词汇：{word_list}。出一个造句或动词变形的中文情景挑战，只输出中文要求。"
                    
                    resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}])
                    st.session_state.l2_quiz = {"words": selected, "scenario": resp.choices[0].message.content.strip(), "lang": db_lang_l2}
                    
            if st.session_state.l2_quiz and st.session_state.l2_quiz["lang"] == db_lang_l2:
                st.markdown("---")
                quiz = st.session_state.l2_quiz
                target_words = [f"{x['word']} ({x.get('tag','未知')})" for x in quiz['words']]
                st.markdown("#### 🚨 挑战要求：")
                st.info(quiz['scenario'])
                st.markdown(f"**目标词汇**：`{'` | `'.join(target_words)}`")
                
                user_sentence = st.text_area("✍️ 你的外语作答 (脑内构思后敲出来)：")
                
                if st.button("🚀 提交给 AI 批改", use_container_width=True):
                    if not user_sentence.strip(): st.warning("请输入句子。")
                    else:
                        eval_prompt = f"场景：{quiz['scenario']}\n要求用词：{target_words}\n用户：{user_sentence}\n请输出:\n### 1. 诊断纠错\n### 2. 双版本重塑(日常/学术)\n### 3. [SCORE: X] (1-5分)"
                        with st.spinner("阅卷中..."):
                            feedback = ""
                            stream = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": eval_prompt}], stream=True)
                            feedback_container = st.empty()
                            for chunk in stream:
                                if chunk.choices[0].delta.content:
                                    feedback += chunk.choices[0].delta.content
                                    feedback_container.markdown(feedback)
                            
                            score_match = re.search(r'\[SCORE:\s*([1-5])\]', feedback)
                            score_val = int(score_match.group(1)) if score_match else 3
                            for w in quiz['words']:
                                new_w = min(float(w.get("weight", 1.0)) * 1.5, 10.0) if score_val <= 3 else max(float(w.get("weight", 1.0)) * 0.5, 0.1)
                                db.table("vocab").update({"weight": new_w, "score": score_val}).eq("id", w["id"]).execute()

# ==================== Tab 3: 口语召回 (3秒情景闪卡) ====================
with tab_oral:
    st.subheader("🗣️ 3秒即兴口语闪卡测试")
    db = get_supabase_client()
    if db:
        oral_cards = db.table("oral_cards").select("*").execute().data
        if st.button("🎲 生成随机口语场景", use_container_width=True, type="primary"):
            if not oral_cards: st.warning("口语库为空，请先在 Tab 5 导入素材。")
            else:
                st.session_state.active_oral_card = random.choice(oral_cards)
                st.session_state.show_oral_answer = False
                st.rerun()
                
        if st.session_state.active_oral_card:
            c = st.session_state.active_oral_card
            st.info(c["scenario"])
            if st.button("👀 显示地道原句", use_container_width=True):
                st.session_state.show_oral_answer = True
            if st.session_state.show_oral_answer:
                st.success(f"**语块：** `{c['phrase']}`\n\n**原句：** {c['full_sentence']}")

# ==================== Tab 4: 词汇闪卡总览 (新增中文含义显示) ====================
with tab_cards:
    st.subheader("🗂️ 云端词库大阅兵")
    st.caption("在这里你可以查看 AI 自动抓取到的所有单词、中文含义、音标和原著例句。")
    db = get_supabase_client()
    if db:
        all_words = db.table("vocab").select("*").order("id", desc=True).execute().data
        if not all_words:
            st.info("目前云端金库还是空的，快去『云端管理』导入吧！")
        else:
            cet4_cnt = len([x for x in all_words if x.get('tag') == 'CET4'])
            toefl_cnt = len([x for x in all_words if x.get('tag') == 'TOEFL'])
            st.write(f"**库中总词数：{len(all_words)}** （包含 CET4: `{cet4_cnt}` 个，托福及其他: `{toefl_cnt}` 个）")
            
            for w in all_words[:50]:
                with st.expander(f"🏷️ [{w.get('tag', '未知')}] {w['word']}  (Level {w['level']})"):
                    # 新增显示中文意思
                    st.write(f"**💡 含义:** `{w.get('meaning', '暂无（旧数据未记录，新导入即可包含）')}`")
                    st.write(f"**🗣️ 音标:** {w.get('phonetic', '无')}")
                    st.write(f"**📖 例句:** {w.get('example', '无例句')}")
                    st.write(f"**📈 抽中权重:** {w.get('weight', 1.0)}")
                    if st.button(f"🗑️ 删除该词", key=f"del_{w['id']}"):
                        db.table("vocab").delete().eq("id", w["id"]).execute()
                        st.rerun()

# ==================== Tab 5: 云端管理 (新增抓取中文含义) ====================
with tab_manage:
    st.subheader("📂 智能词汇分拣中心")
    
    vocab_type = st.radio("你要导入的生词属于什么级别？", ["CET4 四级词汇 (直达 L1)", "TOEFL 托福词汇 (进入 L0)"], horizontal=True)
    import_lang = st.radio("语料语种", ["EN 英语", "JP 日语"], horizontal=True)
    db_lang_import = "EN" if "EN" in import_lang else "JP"
    
    db = get_supabase_client()
    llm = get_llm_client()
    
    if db and llm:
        import_mode = st.radio("选择导入方式", ["上传文档 (PDF/Word/TXT)", "直接粘贴文本"], horizontal=True)
        raw_text = ""
        
        if import_mode == "直接粘贴文本":
            raw_text = st.text_area("在此粘贴词表：", height=150)
        else:
            file_obj = st.file_uploader("上传带例句的文档", type=["pdf", "docx", "txt"])
            if file_obj:
                ext = file_obj.name.split(".")[-1].lower()
                if ext == "pdf": raw_text = extract_text_from_pdf(file_obj)
                elif ext == "docx": raw_text = extract_text_from_docx(file_obj)
                elif ext == "txt": raw_text = str(file_obj.read(), "utf-8")
                st.success("读取成功！")

        if st.button("🚀 智能提取防重并上传", type="primary"):
            if not raw_text.strip():
                st.warning("文本为空！")
            else:
                with st.spinner("AI 正在精准过滤废话，提取核心单词、中文意思、音标与例句..."):
                    try:
                        # 提示词增加提取 meaning
                        prompt = f"""
                        你是一个严谨的语言学专家。请从以下文本中提取**正在被讲解的核心词汇**。
                        返回 JSON 格式：
                        {{
                            "words": [
                                {{
                                    "word": "单词", 
                                    "meaning": "简短精准的中文意思",
                                    "phonetic": "音标(如 [ˈpænl])", 
                                    "example": "原文中该单词对应的英文例句(若无则留空)"
                                }}
                            ]
                        }}
                        文本：{raw_text[:4000]}
                        """
                        resp = llm.chat.completions.create(
                            model=st.session_state["model_name"], 
                            messages=[{"role": "user", "content": prompt}], 
                            response_format={"type": "json_object"},
                            temperature=0.1
                        )
                        extracted_items = json.loads(resp.choices[0].message.content).get("words", [])
                        
                        if not extracted_items:
                            st.error("未能找到符合条件的单词格式。")
                        else:
                            existing_words_res = db.table("vocab").select("word").eq("language", db_lang_import).execute().data
                            existing_set = {x['word'].lower() for x in existing_words_res}
                            
                            insert_data = []
                            duplicate_count = 0
                            
                            for item in extracted_items:
                                w = item.get("word", "").strip()
                                if not w: continue
                                
                                if w.lower() in existing_set:
                                    duplicate_count += 1
                                else:
                                    is_cet4 = "CET4" in vocab_type
                                    target_level = 1 if is_cet4 else 0
                                    target_tag = "CET4" if is_cet4 else "TOEFL"
                                    
                                    insert_data.append({
                                        "word": w,
                                        "meaning": item.get("meaning", ""),
                                        "phonetic": item.get("phonetic", ""),
                                        "example": item.get("example", ""),
                                        "language": db_lang_import,
                                        "level": target_level,
                                        "tag": target_tag
                                    })
                                    existing_set.add(w.lower())
                            
                            if insert_data:
                                db.table("vocab").insert(insert_data).execute()
                                st.success(f"🎉 成功导入 {len(insert_data)} 个新词！(拦截了 {duplicate_count} 个重复词汇)")
                                st.rerun()
                            else:
                                st.warning(f"导入拦截：本次提取的单词数据库里全都有了！(拦截了 {duplicate_count} 个)")
                    except Exception as e:
                        st.error(f"处理失败: {e}")

# ==================== Tab 6: 计划与历史 ====================
with tab_plan:
    st.subheader("🗓️ 一年期托福&N2 攻坚计划表")
    
    st.markdown("""
    **☀️ 上午专业课（精力充沛：攻克英语）**
    - *前20分钟*：打开看板 `Tab 1`，刷完今日托福 Level 0 和 Level 1 额度（无声心算打卡）。
    - *后20分钟*：手机刷一篇 TPO 阅读，分析长难句。将长难句短语丢进 `Tab 4` 导入。

    **☕ 下午专业课（容易犯困：切换日语）**
    - *前20分钟*：打开看板 `Tab 2 (日语)`，玩动词变形 AI 挑战（极度清醒大脑）。
    - *后20分钟*：阅读 NHK Easy News 或玩多邻国，保持语感。

    **🚶‍♂️ 通勤/回宿舍（碎片听觉）**
    - 戴单边耳机，使用【每日英语听力/日语听力】App 进行挖空回音跟读（单日英语，双日日语）。

    **🌃 晚间宿舍（强迫输出）**
    - 打开 ChatGPT 语音模式，与 AI 进行 5 分钟外语对练。
    - 将 AI 纠错的地道表达粘贴进看板 `Tab 4 (口语召回库)`。睡觉前在 `Tab 3` 进行 3 秒闪卡测试。
    """)
