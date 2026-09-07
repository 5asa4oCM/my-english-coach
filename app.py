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
    return (datetime.now(timezone.utc) + timedelta(hours=hours, days=days)).isoformat()

def get_now_utc():
    return datetime.now(timezone.utc).isoformat()

# ==================== 1. UI 与 侧边栏配置 ====================
st.set_page_config(page_title="多语种自适应看板 (终极版)", page_icon="🌎", layout="wide")

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
if "current_l1_read" not in st.session_state: st.session_state.current_l1_read = None
if "current_l1_spell" not in st.session_state: st.session_state.current_l1_spell = None
if "show_l1_meaning" not in st.session_state: st.session_state.show_l1_meaning = False
if "l2_quiz" not in st.session_state: st.session_state.l2_quiz = None
if "current_l2_spell" not in st.session_state: st.session_state.current_l2_spell = None
if "active_oral_card" not in st.session_state: st.session_state.active_oral_card = None
if "show_oral_answer" not in st.session_state: st.session_state.show_oral_answer = False

tab_learn, tab_l2, tab_oral, tab_cards, tab_manage, tab_plan = st.tabs([
    "📚 词汇漏斗", "🎯 实战输出(L2)", "🗣️ 口语闪卡", "🗂️ 词汇闪卡", "📂 云端管理", "🗓️ 计划"
])

# ==================== Tab 1: 词汇漏斗 (Level 0 & Level 1) ====================
with tab_learn:
    st.subheader("📚 每日双语漏斗训练")
    lang_choice = st.radio("选择当前训练语种", ["🇬🇧 英语 (EN)", "🇯🇵 日语 (JP)"], horizontal=True)
    db_lang = "EN" if "EN" in lang_choice else "JP"
    
    db = get_supabase_client()
    if not db:
        st.warning("请在左侧配置数据库连接。")
    else:
        now_utc = get_now_utc()
        # 获取三大独立队列：L0速览、L1认读、L1听写
        l0_words = db.table("vocab").select("*").eq("language", db_lang).eq("level", 0).execute().data
        l1_read_words = db.table("vocab").select("*").eq("language", db_lang).eq("level", 1).lte("next_review_time", now_utc).execute().data
        l1_spell_words = db.table("vocab").select("*").eq("language", db_lang).eq("level", 1).lte("next_spell_time", now_utc).execute().data
        
        st.write(f"📊 **今日待办：** L0速览: `{len(l0_words)}` 个 | L1认读: `{len(l1_read_words)}` 个 | L1听写: `{len(l1_spell_words)}` 个")
        st.markdown("---")
        
        col_l0, col_l1 = st.columns(2)
        
        # --- 模块A: L0 新词速览 ---
        with col_l0:
            st.markdown("#### 🆕 Level 0: 托福新词速览")
            if l0_words:
                if not st.session_state.current_l0 or st.session_state.current_l0['language'] != db_lang:
                    st.session_state.current_l0 = random.choice(l0_words)
                w0 = st.session_state.current_l0
                
                st.info(f"### {w0['word']}")
                st.markdown(f"🏷️ **来源:** `{w0.get('tag', '未知')}` | 🗣️ **音标:** `{w0.get('phonetic', '无')}`")
                st.markdown(f"💡 **含义:** `{w0.get('meaning', '暂无记录')}`")
                
                if st.button("🧠 获取 AI 深度解析", key="hint_l0"):
                    llm = get_llm_client()
                    if llm:
                        resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": f"解析单词 '{w0['word']}'"}], temperature=0.3)
                        st.success(resp.choices[0].message.content)
                        
                if st.button("✅ 记住了，推入 Level 1", type="primary", use_container_width=True):
                    db.table("vocab").update({"level": 1, "next_review_time": get_now_utc(), "next_spell_time": get_now_utc()}).eq("id", w0["id"]).execute()
                    st.session_state.current_l0 = None
                    st.rerun()
            else:
                st.success("今日 L0 任务已清空！")
                
        # --- 模块B: L1 独立双标签 (认读 & 听写) ---
        with col_l1:
            st.markdown("#### 🧠 Level 1: 间隔重复矩阵")
            tab_l1_read, tab_l1_spell = st.tabs(["👀 认读模式", "✍️ 听写模式"])
            
            # --- L1 认读 ---
            with tab_l1_read:
                if l1_read_words:
                    if not st.session_state.current_l1_read or st.session_state.current_l1_read['language'] != db_lang:
                        st.session_state.current_l1_read = random.choice(l1_read_words)
                        st.session_state.show_l1_meaning = False
                    w1r = st.session_state.current_l1_read
                    
                    st.warning(f"## {w1r['word']}")
                    
                    if not st.session_state.show_l1_meaning:
                        if st.button("👀 点击核对答案", use_container_width=True, key=f"btn_r_{w1r['id']}"):
                            st.session_state.show_l1_meaning = True
                            st.rerun()
                    else:
                        st.success(f"**含义：** {w1r.get('meaning', '暂无记录')}")
                        st.markdown(f"🗣️ **音标:** `{w1r.get('phonetic', '无')}`")
                        
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if st.button("🟢 认识 (进L2)", use_container_width=True):
                                # 认读成功一次直接进入L2造句，L2冷却时间设为现在
                                db.table("vocab").update({"level": 2, "next_l2_time": get_now_utc()}).eq("id", w1r["id"]).execute()
                                st.session_state.current_l1_read = None
                                st.rerun()
                        with c2:
                            if st.button("🟡 模糊 (+12小时)", use_container_width=True):
                                db.table("vocab").update({"next_review_time": get_time_offset(hours=12)}).eq("id", w1r["id"]).execute()
                                st.session_state.current_l1_read = None
                                st.rerun()
                        with c3:
                            if st.button("🔴 忘记 (+1小时)", use_container_width=True):
                                db.table("vocab").update({"next_review_time": get_time_offset(hours=1)}).eq("id", w1r["id"]).execute()
                                st.session_state.current_l1_read = None
                                st.rerun()
                else:
                    st.success("今日 L1 认读已清空！")
                    
            # --- L1 听写 ---
            with tab_l1_spell:
                if l1_spell_words:
                    if not st.session_state.current_l1_spell or st.session_state.current_l1_spell['language'] != db_lang:
                        st.session_state.current_l1_spell = random.choice(l1_spell_words)
                    w1s = st.session_state.current_l1_spell
                    s_streak = w1s.get("spell_streak", 0)
                    
                    st.info(f"💡 **含义:** {w1s.get('meaning', '暂无记录')}")
                    st.markdown(f"🗣️ **音标:** `{w1s.get('phonetic', '无')}` | 🔥 **拼对连击:** `{s_streak}`")
                    
                    # 动态 Key 确保输入框自动清空
                    user_spell = st.text_input("✍️ 请拼写该词：", key=f"spl1_{w1s['id']}_{w1s.get('next_spell_time')}")
                    
                    if st.button("🎯 提交拼写", type="primary", use_container_width=True, key=f"btn_spl1_{w1s['id']}"):
                        if user_spell.strip().lower() == w1s['word'].strip().lower():
                            st.success(f"正确！拼写为: {w1s['word']}")
                            new_streak = s_streak + 1
                            # 拼写正确：根据连击次数延长冷却天数 (1天, 2天, 3天...)
                            db.table("vocab").update({"spell_streak": new_streak, "next_spell_time": get_time_offset(days=new_streak)}).eq("id", w1s["id"]).execute()
                        else:
                            st.error(f"拼写错误！正确答案是: {w1s['word']}")
                            # 拼错：打回原形，强制 1 小时后再次出现！
                            db.table("vocab").update({"spell_streak": 0, "next_spell_time": get_time_offset(hours=1)}).eq("id", w1s["id"]).execute()
                        
                        st.session_state.current_l1_spell = None
                        st.button("👉 点击进入下一个单词", use_container_width=True)
                else:
                    st.success("今日 L1 听写已清空！")

# ==================== Tab 2: 强迫造句/变形 (Level 2) ====================
with tab_l2:
    st.subheader("🎯 Level 2: 实战输出矩阵")
    l2_lang = st.radio("选择 L2 实战语种", ["🇬🇧 英语 (EN)", "🇯🇵 日语 (JP)"], horizontal=True)
    db_lang_l2 = "EN" if "EN" in l2_lang else "JP"
    
    db = get_supabase_client()
    llm = get_llm_client()
    
    if db and llm:
        now_utc = get_now_utc()
        # L2 两大独立队列：造句 和 听写 (遵循艾宾浩斯)
        l2_sentence_words = db.table("vocab").select("*").eq("language", db_lang_l2).eq("level", 2).lte("next_l2_time", now_utc).execute().data
        l2_spell_words = db.table("vocab").select("*").eq("language", db_lang_l2).eq("level", 2).lte("next_spell_time", now_utc).execute().data
        
        st.write(f"📊 **今日待办：** L2造句: `{len(l2_sentence_words)}` 个 | L2听写: `{len(l2_spell_words)}` 个")
        st.markdown("---")
        
        tab_l2_sentence, tab_l2_spell = st.tabs(["🎯 情境强迫造句", "✍️ L2 听写复习"])
        
        # --- L2 造句 ---
        with tab_l2_sentence:
            if len(l2_sentence_words) < (3 if db_lang_l2 == "EN" else 2):
                st.warning(f"当前到达复习时间的 L2 词汇太少。请先去 Tab 1 背词！")
            else:
                if st.button("🎲 抽取词汇，生成 AI 挑战", type="primary", use_container_width=True):
                    with st.spinner("AI 正在构思挑战..."):
                        k = 3 if db_lang_l2 == "EN" else random.choice([1, 2])
                        selected = random.sample(l2_sentence_words, k)
                        word_list = [x['word'] for x in selected]
                        
                        prompt = f"基于英语单词：{word_list}。用中文设定一个日常或学术场景，字数50以内。" if db_lang_l2 == "EN" else f"基于日语词汇：{word_list}。出一个造句或动词变形的中文情景挑战。"
                        resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}])
                        st.session_state.l2_quiz = {"words": selected, "scenario": resp.choices[0].message.content.strip(), "lang": db_lang_l2}
                        
                if st.session_state.l2_quiz and st.session_state.l2_quiz["lang"] == db_lang_l2:
                    st.markdown("---")
                    quiz = st.session_state.l2_quiz
                    target_words = [f"{x['word']} ({x.get('meaning','未知')})" for x in quiz['words']]
                    st.info(quiz['scenario'])
                    st.markdown(f"**目标词汇**：`{'` | `'.join(target_words)}`")
                    
                    user_sentence = st.text_area("✍️ 你的外语作答：")
                    if st.button("🚀 提交给 AI 批改", use_container_width=True):
                        if not user_sentence.strip(): st.warning("请输入句子。")
                        else:
                            eval_prompt = f"场景：{quiz['scenario']}\n要求用词：{target_words}\n用户：{user_sentence}\n请输出:\n### 1. 诊断纠错\n### 2. 双版本重塑\n### 3. [SCORE: X] (1-5分)"
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
                                
                                # 根据 AI 打分，设定 L2 的下次复习时间
                                for w in quiz['words']:
                                    if score_val >= 4: new_time = get_time_offset(days=3)
                                    elif score_val == 3: new_time = get_time_offset(days=1)
                                    else: new_time = get_time_offset(hours=1)
                                    db.table("vocab").update({"next_l2_time": new_time}).eq("id", w["id"]).execute()
                                
                                st.session_state.l2_quiz = None
                                st.button("👉 挑战完成，点击继续", use_container_width=True)

        # --- L2 听写 ---
        with tab_l2_spell:
            if l2_spell_words:
                if not st.session_state.current_l2_spell or st.session_state.current_l2_spell['language'] != db_lang_l2:
                    st.session_state.current_l2_spell = random.choice(l2_spell_words)
                w2s = st.session_state.current_l2_spell
                s_streak = w2s.get("spell_streak", 0)
                
                st.info(f"💡 **含义:** {w2s.get('meaning', '暂无记录')}")
                st.markdown(f"🗣️ **音标:** `{w2s.get('phonetic', '无')}` | 🔥 **拼对连击:** `{s_streak}`")
                
                user_spell_l2 = st.text_input("✍️ 高阶词汇拼写：", key=f"spl2_{w2s['id']}_{w2s.get('next_spell_time')}")
                
                if st.button("🎯 提交拼写", type="primary", use_container_width=True, key=f"btn_spl2_{w2s['id']}"):
                    if user_spell_l2.strip().lower() == w2s['word'].strip().lower():
                        st.success(f"正确！拼写为: {w2s['word']}")
                        new_streak = s_streak + 1
                        db.table("vocab").update({"spell_streak": new_streak, "next_spell_time": get_time_offset(days=new_streak)}).eq("id", w2s["id"]).execute()
                    else:
                        st.error(f"拼写错误！正确答案是: {w2s['word']}")
                        # 拼错：强制 1 小时后再次出现！
                        db.table("vocab").update({"spell_streak": 0, "next_spell_time": get_time_offset(hours=1)}).eq("id", w2s["id"]).execute()
                    
                    st.session_state.current_l2_spell = None
                    st.button("👉 点击进入下一个单词", use_container_width=True)
            else:
                st.success("今日 L2 听写已清空！")

# ==================== Tab 3: 口语召回 ====================
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
                        请从以下文本中提取**正在被讲解的核心词汇**。
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
                                    
                                    # 核心：导入时立刻初始化艾宾浩斯时间轴！
                                    insert_data.append({
                                        "word": w,
                                        "meaning": item.get("meaning", ""),
                                        "phonetic": item.get("phonetic", ""),
                                        "example": item.get("example", ""),
                                        "language": db_lang_import,
                                        "level": target_level,
                                        "tag": target_tag,
                                        "next_review_time": get_now_utc(),
                                        "next_spell_time": get_now_utc(),
                                        "next_l2_time": get_now_utc()
                                    })
                                    existing_set.add(w.lower())
                            
                            if insert_data:
                                db.table("vocab").insert(insert_data).execute()
                                st.success(f"🎉 成功导入 {len(insert_data)} 个新词！(拦截了 {duplicate_count} 个重复词汇)")
                            else:
                                st.warning(f"导入拦截：本次提取的单词数据库里全都有了！(拦截了 {duplicate_count} 个)")
                    except Exception as e:
                        st.error(f"处理失败: {e}")

# ==================== Tab 6: 计划与历史 ====================
with tab_plan:
    st.subheader("🗓️ 一年期托福&N2 攻坚计划表")
    st.markdown("""
    **☀️ 上午专业课（精力充沛：攻克英语）**
    - *前20分钟*：打开看板 `Tab 1`，刷完今日待复习额度。灵活切换【认读】与【听写】。
    - *后20分钟*：手机刷一篇 TPO 阅读，分析长难句。将长难句短语丢进 `Tab 5` 导入。

    **☕ 下午专业课（容易犯困：切换日语）**
    - *前20分钟*：打开看板 `Tab 2 (日语)`，玩动词变形 AI 挑战。
    - *后20分钟*：阅读 NHK Easy News 或玩多邻国，保持语感。
    """)
