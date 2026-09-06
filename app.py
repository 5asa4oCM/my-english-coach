import streamlit as st
import random
import re
import io
import json
from gtts import gTTS
from openai import OpenAI
from supabase import create_client, Client
from pypdf import PdfReader
from datetime import datetime, timedelta, timezone

try:
    import docx
except ImportError:
    docx = None

# ==================== 时间处理辅助函数 ====================
def get_time_offset(hours=0, days=0):
    """获取未来的 UTC 时间，用于设置艾宾浩斯遗忘曲线"""
    return (datetime.now(timezone.utc) + timedelta(hours=hours, days=days)).isoformat()

def get_now_utc():
    return datetime.now(timezone.utc).isoformat()

# ==================== 1. UI 与 侧边栏配置 ====================
st.set_page_config(page_title="多语种自适应看板 (完美版)", page_icon="🌎", layout="wide")

st.sidebar.title("⚙️ 云端系统设置")

try:
    default_api_key = st.secrets.get("DEEPSEEK_API_KEY", "")
    default_supa_url = st.secrets.get("SUPABASE_URL", "")
    default_supa_key = st.secrets.get("SUPABASE_KEY", "")
except:
    default_api_key = ""
    default_supa_url = ""
    default_supa_key = ""

if default_api_key:
    st.sidebar.caption("✅ 已成功连接云端保险箱，密钥已自动填入。")
else:
    st.sidebar.caption("⚠️ 未检测到云端保险箱，请手动填入密钥。")

api_key = st.sidebar.text_input("AI API Key", type="password", value=st.session_state.get("api_key", default_api_key))
base_url = st.sidebar.text_input("AI Base URL", value=st.session_state.get("base_url", "https://api.deepseek.com"))
model_name = st.sidebar.selectbox("选择模型", ["deepseek-chat", "gpt-4o-mini", "gemini-1.5-flash"], index=0)

st.sidebar.markdown("---")
supa_url = st.sidebar.text_input("Supabase URL", value=st.session_state.get("supa_url", default_supa_url))
supa_key = st.sidebar.text_input("Supabase Key", type="password", value=st.session_state.get("supa_key", default_supa_key))

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
        
        # 核心改动：L1 引入时间冷却，只拉取“复习时间 <= 现在”的单词
        now_utc_str = get_now_utc()
        l1_words_res = db.table("vocab").select("*").eq("language", db_lang).eq("level", 1).lte("next_review_time", now_utc_str).execute()
        l1_words = l1_words_res.data
        
        st.write(f"📊 **今日待办 ({db_lang})：** 待速览(L0): `{len(l0_words)}` 个 | 待复习(L1): `{len(l1_words)}` 个")
        st.markdown("---")
        
        col_l0, col_l1 = st.columns(2)
        
        with col_l0:
            st.markdown("#### 🆕 Level 0: 托福新词速览")
            if l0_words:
                if not st.session_state.current_l0 or st.session_state.current_l0['language'] != db_lang:
                    st.session_state.current_l0 = random.choice(l0_words)
                w = st.session_state.current_l0
                
                st.info(f"### {w['word']}")
                st.markdown(f"🏷️ **来源:** `{w.get('tag', '未知')}` | 🗣️ **音标:** `{w.get('phonetic', '无')}`")
                st.markdown(f"💡 **含义:** `{w.get('meaning', '暂无记录')}`")
                if w.get('example'):
                    st.write(f"📖 **原著例句:** _{w['example']}_")
                
                if st.button("✅ 记住了，推入 Level 1", type="primary", use_container_width=True):
                    # 推入 L1 时，立即进入复习队列
                    db.table("vocab").update({"level": 1, "next_review_time": get_time_offset(hours=0)}).eq("id", w["id"]).execute()
                    st.session_state.current_l0 = None
                    st.rerun()
            else:
                st.success("今日 L0 任务已清空！")
                
        with col_l1:
            st.markdown("#### 🧠 Level 1: 间隔重复回忆")
            if l1_words:
                l1_mode = st.radio("选择 L1 考核模式：", ["👀 认读模式 (看英想中)", "✍️ 听写模式 (看中拼英)"], horizontal=True)
                
                if not st.session_state.current_l1 or st.session_state.current_l1['language'] != db_lang:
                    # 从到期的词中随机抽一个
                    st.session_state.current_l1 = random.choice(l1_words)
                    st.session_state.show_l1_meaning = False
                
                w1 = st.session_state.current_l1
                streak = w1.get("streak", 0)
                
                # 模式 A: 认读模式
                if l1_mode == "👀 认读模式 (看英想中)":
                    st.warning(f"## {w1['word']}")
                    st.markdown(f"🏷️ **分类:** `{w1.get('tag', '未知')}` | 🔥 **连对次数:** `{streak}`")
                    
                    if not st.session_state.show_l1_meaning:
                        if st.button("👀 点击核对答案", use_container_width=True):
                            st.session_state.show_l1_meaning = True
                            st.rerun()
                    else:
                        st.markdown(f"🗣️ **音标:** `{w1.get('phonetic', '无')}`")
                        st.success(f"**核心含义：** {w1.get('meaning', '暂无记录')}")
                        if w1.get('example'): st.write(f"📖 **例句提示:** _{w1['example']}_")
                        
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if st.button("🟢 认识 (记忆加深)", use_container_width=True):
                                new_streak = streak + 1
                                if new_streak >= 2: # 连续两次认识，晋级 L2
                                    db.table("vocab").update({"level": 2, "streak": new_streak, "last_l2_time": get_time_offset(days=-365)}).eq("id", w1["id"]).execute()
                                else:
                                    db.table("vocab").update({"streak": new_streak, "next_review_time": get_time_offset(days=1)}).eq("id", w1["id"]).execute()
                                st.session_state.current_l1 = None
                                st.rerun()
                        with c2:
                            if st.button("🟡 模糊 (12小时后复习)", use_container_width=True):
                                db.table("vocab").update({"next_review_time": get_time_offset(hours=12)}).eq("id", w1["id"]).execute()
                                st.session_state.current_l1 = None
                                st.rerun()
                        with c3:
                            if st.button("🔴 忘记 (1小时后重背)", use_container_width=True):
                                db.table("vocab").update({"streak": 0, "next_review_time": get_time_offset(hours=1)}).eq("id", w1["id"]).execute()
                                st.session_state.current_l1 = None
                                st.rerun()
                                
                # 模式 B: 听写模式
                else:
                    st.info(f"💡 **含义:** {w1.get('meaning', '暂无记录')}")
                    st.markdown(f"🗣️ **音标:** `{w1.get('phonetic', '无')}` | 🔥 **连对次数:** `{streak}`")
                    if w1.get('example'): st.caption(f"📖 例句提示: {w1['example'].replace(w1['word'], '_____')}")
                    
                    user_spell = st.text_input("✍️ 请根据中文拼写该词：", key="spell_input")
                    if st.button("🎯 提交拼写", type="primary", use_container_width=True):
                        if user_spell.strip().lower() == w1['word'].strip().lower():
                            st.success(f"正确！拼写为: {w1['word']}")
                            new_streak = streak + 1
                            if new_streak >= 2:
                                db.table("vocab").update({"level": 2, "streak": new_streak, "last_l2_time": get_time_offset(days=-365)}).eq("id", w1["id"]).execute()
                            else:
                                db.table("vocab").update({"streak": new_streak, "next_review_time": get_time_offset(days=1)}).eq("id", w1["id"]).execute()
                        else:
                            st.error(f"拼写错误！正确答案是: {w1['word']}")
                            db.table("vocab").update({"streak": 0, "next_review_time": get_time_offset(hours=1)}).eq("id", w1["id"]).execute()
                        
                        st.session_state.current_l1 = None
                        # 利用空行暂停，让用户看到结果
                        st.button("👉 点击进入下一个单词", use_container_width=True)

            else:
                st.success("🎉 今日 L1 复习任务全部清空！休息一下吧。")

# ==================== Tab 2: 强迫造句/变形 (Level 2) ====================
with tab_l2:
    st.subheader("🎯 Level 2: 实战输出与变形训练")
    l2_lang = st.radio("选择 L2 实战语种", ["🇬🇧 英语 (EN)", "🇯🇵 日语 (JP)"], horizontal=True)
    db_lang_l2 = "EN" if "EN" in l2_lang else "JP"
    
    db = get_supabase_client()
    llm = get_llm_client()
    
    if db and llm:
        # 核心改动：采用 LRU 算法，按最后一次造句时间排序，最久没造句的排在前面
        l2_words_res = db.table("vocab").select("*").eq("language", db_lang_l2).eq("level", 2).order("last_l2_time", desc=False).execute()
        l2_words = l2_words_res.data
        
        st.write(f"📊 **当前 L2 可用于实战的词汇总数：** `{len(l2_words)}` 个")
        
        if len(l2_words) < (3 if db_lang_l2 == "EN" else 2):
            st.warning(f"当前 L2 库中词汇太少。请先去 Tab 1 完成记忆晋级！")
        else:
            if st.button("🎲 抽取最久未练习的词汇，生成挑战", type="primary", use_container_width=True):
                with st.spinner("AI 正在构思挑战..."):
                    k = 3 if db_lang_l2 == "EN" else random.choice([1, 2])
                    # 直接选取列表最前面的 k 个（最久未使用的词）
                    selected = l2_words[:k]
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
                                if score_val <= 2:
                                    # 如果造句得分极低，将该词打回 L1 重新背，1小时后必须复习
                                    db.table("vocab").update({"level": 1, "streak": 0, "next_review_time": get_time_offset(hours=1)}).eq("id", w["id"]).execute()
                                else:
                                    # 成功过关，更新最新造句时间，它将被排到队伍最后
                                    db.table("vocab").update({"last_l2_time": get_now_utc()}).eq("id", w["id"]).execute()

# ==================== Tab 3: 口语召回 (保持原样分离) ====================
with tab_oral:
    st.subheader("🗣️ 3秒即兴口语闪卡测试")
    db = get_supabase_client()
    if db:
        oral_cards = db.table("oral_cards").select("*").execute().data
        col_gen_card, col_clear_card = st.columns([2, 1])
        with col_gen_card:
            if st.button("🎲 生成随机口语场景", use_container_width=True, type="primary"):
                if not oral_cards: st.warning("口语库为空，请先在 Tab 5 导入素材。")
                else:
                    st.session_state.active_oral_card = random.choice(oral_cards)
                    st.session_state.show_oral_answer = False
                    st.rerun()
                    
        if st.session_state.active_oral_card:
            st.markdown("---")
            c = st.session_state.active_oral_card
            st.info(c["scenario"])
            
            c1, c2 = st.columns(2)
            with c1:
                if st.button("👀 显示地道原句", use_container_width=True):
                    st.session_state.show_oral_answer = True
            with c2:
                if st.button("⏭️ 下一个场景", use_container_width=True):
                    st.session_state.active_oral_card = random.choice(oral_cards)
                    st.session_state.show_oral_answer = False
                    st.rerun()
                    
            if st.session_state.show_oral_answer:
                st.success(f"**核心语块：** `{c['phrase']}`\n\n**地道原句：** {c['full_sentence']}")
                lang_code = 'ja' if any('\u3040' <= char <= '\u309F' or '\u30A0' <= char <= '\u30FF' for char in c['full_sentence']) else 'en'
                audio = generate_audio(c['full_sentence'], lang=lang_code)
                if audio: st.audio(audio, format="audio/mp3")

# ==================== Tab 4: 词汇闪卡总览 ====================
with tab_cards:
    st.subheader("🗂️ 云端词库大阅兵")
    db = get_supabase_client()
    if db:
        all_words = db.table("vocab").select("*").order("id", desc=True).execute().data
        if not all_words:
            st.info("目前云端金库还是空的。")
        else:
            st.write(f"**库中总词数：{len(all_words)}**")
            for w in all_words[:50]:
                with st.expander(f"🏷️ [{w.get('tag', '未知')}] {w['word']}  (Level {w['level']})"):
                    st.write(f"**💡 含义:** `{w.get('meaning', '暂无记录')}`")
                    st.write(f"**🗣️ 音标:** {w.get('phonetic', '无')}")
                    st.write(f"**📖 例句:** {w.get('example', '无例句')}")
                    if st.button(f"🗑️ 删除该词", key=f"del_{w['id']}"):
                        db.table("vocab").delete().eq("id", w["id"]).execute()
                        st.rerun()

# ==================== Tab 5: 云端管理 (新增数据急救站) ====================
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
                with st.spinner("AI 正在精准过滤，提取核心单词、中文意思、音标与例句..."):
                    try:
                        prompt = f"""
                        你是一个严谨的语言学专家。请从以下文本中提取**正在被讲解的核心词汇**。
                        返回 JSON 格式：
                        {{
                            "words": [
                                {{
                                    "word": "单词", 
                                    "meaning": "简短精准的中文意思",
                                    "phonetic": "音标(如 [ˈpænl])", 
                                    "example": "原文例句(若无则留空)"
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
                                        "tag": target_tag,
                                        "next_review_time": get_now_utc() # 新词默认现在就开始复习
                                    })
                                    existing_set.add(w.lower())
                            
                            if insert_data:
                                db.table("vocab").insert(insert_data).execute()
                                st.success(f"🎉 成功导入 {len(insert_data)} 个新词！(拦截了 {duplicate_count} 个重复词汇)")
                            else:
                                st.warning(f"导入拦截：本次提取的单词数据库里全都有了！(拦截了 {duplicate_count} 个)")
                    except Exception as e:
                        st.error(f"处理失败: {e}")

        # ----- 数据急救站 -----
        st.markdown("---")
        st.markdown("##### 🏥 旧数据 AI 修复台")
        st.caption("检测到你之前导入的老单词没有中文意思和音标？点击下方按钮，AI 会自动在后台帮你全部查好填进去！老数据绝不丢失。")
        if st.button("⚙️ 一键自动修复旧单词的缺失字段"):
            with st.spinner("AI 正在扫描并修复你的云端数据库，请勿关闭页面..."):
                all_v = db.table("vocab").select("*").execute().data
                to_fix = [w for w in all_v if not w.get("meaning") or not w.get("phonetic")]
                if not to_fix:
                    st.success("太棒了！你的数据库非常健康，所有单词都有中文意思和音标，不需要修复。")
                else:
                    st.write(f"检测到 {len(to_fix)} 个不完整的旧单词，开始修复...")
                    success_cnt = 0
                    for bw in to_fix:
                        try:
                            fix_prompt = f"请输出 '{bw['word']}' 的极简中文意思和音标。格式必须严格为 JSON: {{\"meaning\": \"意思\", \"phonetic\": \"音标\"}}"
                            f_resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": fix_prompt}], response_format={"type": "json_object"})
                            f_res = json.loads(f_resp.choices[0].message.content)
                            db.table("vocab").update({
                                "meaning": f_res.get("meaning", ""),
                                "phonetic": f_res.get("phonetic", "")
                            }).eq("id", bw["id"]).execute()
                            success_cnt += 1
                        except:
                            pass
                    st.success(f"✅ 修复完成！成功为 {success_cnt} 个老单词补全了中文释义和音标！去 Tab 4 检阅它们吧！")

# ==================== Tab 6: 计划与历史 ====================
with tab_plan:
    st.subheader("🗓️ 一年期托福&N2 攻坚计划表")
    st.markdown("""
    **☀️ 上午专业课（精力充沛：攻克英语）**
    - *前20分钟*：打开看板 `Tab 1`，刷完今日待复习额度。可灵活切换【认读】与【听写】。
    - *后20分钟*：手机刷一篇 TPO 阅读，分析长难句。将长难句短语丢进 `Tab 5` 导入。

    **☕ 下午专业课（容易犯困：切换日语）**
    - *前20分钟*：打开看板 `Tab 2 (日语)`，玩动词变形 AI 挑战。
    - *后20分钟*：阅读 NHK Easy News 或玩多邻国，保持语感。

    **🌃 晚间宿舍（强迫输出）**
    - 打开 ChatGPT 语音模式，与 AI 进行 5 分钟外语对练。
    - 将 AI 纠错的地道表达粘贴进 `Tab 5` 导入口语闪卡。睡觉前在 `Tab 3` 进行 3 秒闪卡测试。
    """)
