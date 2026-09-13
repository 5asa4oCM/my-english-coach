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
st.set_page_config(page_title="全能多语种自适应看板", page_icon="🌎", layout="wide")

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

# ==================== 初始化状态 ====================
if "current_l0" not in st.session_state: st.session_state.current_l0 = None
if "current_l1_read" not in st.session_state: st.session_state.current_l1_read = None
if "current_l1_spell" not in st.session_state: st.session_state.current_l1_spell = None
if "show_l1_meaning" not in st.session_state: st.session_state.show_l1_meaning = False
if "l2_quiz" not in st.session_state: st.session_state.l2_quiz = None
if "current_l2_spell" not in st.session_state: st.session_state.current_l2_spell = None
if "active_oral_card" not in st.session_state: st.session_state.active_oral_card = None
if "show_oral_answer" not in st.session_state: st.session_state.show_oral_answer = False
if "chunk_quiz" not in st.session_state: st.session_state.chunk_quiz = None
if "current_prompt_chunk" not in st.session_state: st.session_state.current_prompt_chunk = None

tab_prompt, tab_learn, tab_l2, tab_chunks, tab_oral, tab_cards, tab_manage, tab_history_plan = st.tabs([
    "🤖 语伴Prompt", "📚 词汇漏斗", "🎯 L2实战", "🧩 语块训练", "🗣️ 口语闪卡", "🗂️ 数据总览", "📂 云端管理", "🗓️ 历史&计划"
])

# ==================== Tab 0: 今日 AI 口语 Prompt ====================
with tab_prompt:
    st.subheader("🤖 专属 AI 语伴启动器 (Daily Coach)")
    st.caption("每天从你的『语块库』中挑一个最需要练的骨架，生成对练 Prompt。")
    db = get_supabase_client()
    if db:
        now_utc = get_now_utc()
        due_chunks = db.table("chunks").select("*").eq("language", "EN").lte("next_review_time", now_utc).execute().data
        if not due_chunks:
            due_chunks = db.table("chunks").select("*").eq("language", "EN").execute().data
        
        if due_chunks:
            # 刷新按钮：点击后从库中重新随机抽取一个
            if st.button("🔄 刷新换一个语块", type="secondary"):
                st.session_state.current_prompt_chunk = random.choice(due_chunks)
                st.rerun()

            # 保持当前抽取的语块不变，防止切换其他页面时乱跳
            if not st.session_state.current_prompt_chunk:
                st.session_state.current_prompt_chunk = random.choice(due_chunks)
                
            target_chunk = st.session_state.current_prompt_chunk
            
            st.info(f"💡 **今日口语核心骨架**：`{target_chunk['phrase']}` ({target_chunk['meaning']})")
            
            prompt_text = f"""从现在开始，你是我严厉的口语肌肉记忆教练（Pattern Drill Sergeant）。
我今天想把这个句型练成肌肉记忆：【 {target_chunk['phrase']} 】

我们的训练规则如下，请严格按步骤执行：
1. 你每次用中文说出一个使用该句式的、贴近大学生活或托福口语场景的简短句子。
2. 说完中文后，保持完全沉默，停顿 3 秒钟。（给我时间在脑子里反应并用英语脱口而出）。
3. 3 秒后，你用极度地道、带有连读和弱读的美式/英式英语把标准答案读出来，并且读两遍（第一遍正常语速，第二遍稍微放慢，让我进行影子跟读）。
4. 等我跟读完并说 'Next' 后，你再出下一句中文。
5. 一共进行 10 轮。整个过程中除了报题和读答案，不要说任何废话！"""
            
            st.code(prompt_text, language="markdown")
        else:
            st.warning("语块库里还没有英语数据哦，快去 Tab 6 导入吧！")

# ==================== Tab 1: 词汇漏斗 ====================
with tab_learn:
    st.subheader("📚 每日双语漏斗训练")
    lang_choice = st.radio("选择当前训练语种", ["🇬🇧 英语 (EN)", "🇯🇵 日语 (JP)"], horizontal=True)
    db_lang = "EN" if "EN" in lang_choice else "JP"
    
    db = get_supabase_client()
    if not db:
        st.warning("请在左侧配置数据库连接。")
    else:
        now_utc = get_now_utc()
        l0_words = db.table("vocab").select("*").eq("language", db_lang).eq("level", 0).execute().data
        l1_read_words = db.table("vocab").select("*").eq("language", db_lang).eq("level", 1).lte("next_review_time", now_utc).execute().data
        l1_spell_words = db.table("vocab").select("*").eq("language", db_lang).eq("level", 1).lte("next_spell_time", now_utc).execute().data
        
        st.write(f"📊 **今日待办：** L0速览: `{len(l0_words)}` 个 | L1认读: `{len(l1_read_words)}` 个 | L1听写: `{len(l1_spell_words)}` 个")
        st.markdown("---")
        
        col_l0, col_l1 = st.columns(2)
        
        # --- L0 ---
        with col_l0:
            st.markdown("#### 🆕 Level 0: 托福新词速览")
            if l0_words:
                if not st.session_state.current_l0 or st.session_state.current_l0['language'] != db_lang:
                    st.session_state.current_l0 = random.choice(l0_words)
                w0 = st.session_state.current_l0
                
                st.info(f"### {w0['word']}")
                st.markdown(f"🏷️ **来源:** `{w0.get('tag', '未知')}` | 🗣️ **音标:** `{w0.get('phonetic', '无')}`")
                st.markdown(f"💡 **核心含义:** `{w0.get('meaning', '暂无记录')}`")
                if w0.get('example'): st.write(f"📖 **原著例句:** _{w0['example']}_")
                
                if st.button("🧠 AI 极简解析 (防卡壳)", key="hint_l0"):
                    llm = get_llm_client()
                    if llm:
                        hint_prompt = f"请简述 '{w0['word']}' 的记忆法或1个高频搭配。严格限制在 50 个汉字以内，不要废话。"
                        resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": hint_prompt}], temperature=0.3)
                        st.success(resp.choices[0].message.content)
                        
                if st.button("✅ 记住了，推入 Level 1", type="primary", use_container_width=True):
                    db.table("vocab").update({"level": 1, "next_review_time": get_now_utc(), "next_spell_time": get_now_utc()}).eq("id", w0["id"]).execute()
                    st.session_state.current_l0 = None
                    st.rerun()
            else:
                st.success("今日 L0 任务已清空！")
                
        # --- L1 ---
        with col_l1:
            st.markdown("#### 🧠 Level 1: 间隔重复矩阵")
            tab_l1_read, tab_l1_spell = st.tabs(["👀 认读模式", "✍️ 听写模式"])
            
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
                        if w1r.get('example'): st.write(f"📖 **例句提示:** _{w1r['example']}_")
                        
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            if st.button("🟢 认识 (进L2)", use_container_width=True):
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
                    if st.button("🔄 强行唤醒：继续认读冷却中的单词", key="wakeup_read", use_container_width=True):
                        with st.spinner("唤醒中..."):
                            db.table("vocab").update({"next_review_time": get_now_utc()}).eq("language", db_lang).eq("level", 1).gt("next_review_time", get_now_utc()).execute()
                        st.rerun()
                    
            with tab_l1_spell:
                if l1_spell_words:
                    if not st.session_state.current_l1_spell or st.session_state.current_l1_spell['language'] != db_lang:
                        st.session_state.current_l1_spell = random.choice(l1_spell_words)
                    w1s = st.session_state.current_l1_spell
                    s_streak = w1s.get("spell_streak", 0)
                    
                    st.info(f"💡 **含义:** {w1s.get('meaning', '暂无记录')}")
                    st.markdown(f"🗣️ **音标:** `{w1s.get('phonetic', '无')}` | 🔥 **拼对连击:** `{s_streak}`")
                    
                    user_spell = st.text_input("✍️ 请拼写该词：", key=f"spl1_{w1s['id']}_{w1s.get('next_spell_time')}")
                    
                    if st.button("🎯 提交拼写", type="primary", use_container_width=True, key=f"btn_spl1_{w1s['id']}"):
                        if user_spell.strip().lower() == w1s['word'].strip().lower():
                            st.success(f"正确！拼写为: {w1s['word']}")
                            new_streak = s_streak + 1
                            db.table("vocab").update({"spell_streak": new_streak, "next_spell_time": get_time_offset(days=new_streak)}).eq("id", w1s["id"]).execute()
                        else:
                            st.error(f"拼写错误！正确答案是: {w1s['word']}")
                            db.table("vocab").update({"spell_streak": 0, "next_spell_time": get_time_offset(hours=1)}).eq("id", w1s["id"]).execute()
                        
                        st.session_state.current_l1_spell = None
                        st.button("👉 点击进入下一个单词", use_container_width=True)
                else:
                    st.success("今日 L1 听写已清空！")
                    if st.button("🔄 强行唤醒：继续听写冷却中的单词", key="wakeup_spell", use_container_width=True):
                        with st.spinner("唤醒中..."):
                            db.table("vocab").update({"next_spell_time": get_now_utc()}).eq("language", db_lang).eq("level", 1).gt("next_spell_time", get_now_utc()).execute()
                        st.rerun()

# ==================== Tab 2: 强迫造句/变形 (Level 2) ====================
with tab_l2:
    st.subheader("🎯 Level 2: 实战输出矩阵")
    l2_lang = st.radio("选择 L2 实战语种", ["🇬🇧 英语 (EN)", "🇯🇵 日语 (JP)"], horizontal=True)
    db_lang_l2 = "EN" if "EN" in l2_lang else "JP"
    
    db = get_supabase_client()
    llm = get_llm_client()
    
    if db and llm:
        now_utc = get_now_utc()
        l2_sentence_words = db.table("vocab").select("*").eq("language", db_lang_l2).eq("level", 2).lte("next_l2_time", now_utc).order("last_l2_time", desc=False).execute().data
        st.write(f"📊 **今日待办：** 待造句单词: `{len(l2_sentence_words)}` 个")
        st.markdown("---")
        
        if len(l2_sentence_words) < (3 if db_lang_l2 == "EN" else 2):
            st.warning(f"当前到达复习时间的 L2 词汇太少。")
            if st.button("🔄 强行唤醒所有 L2 睡眠词汇", use_container_width=True):
                with st.spinner("唤醒中..."):
                    db.table("vocab").update({"next_l2_time": get_now_utc()}).eq("language", db_lang_l2).eq("level", 2).gt("next_l2_time", get_now_utc()).execute()
                st.rerun()
        else:
            if st.button("🎲 抽取最久未用词汇，生成 AI 挑战", type="primary", use_container_width=True):
                with st.spinner("AI 正在构思场景..."):
                    k = 3 if db_lang_l2 == "EN" else random.choice([1, 2])
                    selected = l2_sentence_words[:k]
                    word_list = [x['word'] for x in selected]
                    
                    prompt = f"基于英语单词：{word_list}。用中文设定一个日常或学术场景。要求：合理串联这三个词，只要中文描述，字数50以内。" if db_lang_l2 == "EN" else f"基于日语词汇：{word_list}。出一个造句或动词变形的中文情景挑战，只输出中文要求。"
                    
                    resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}])
                    st.session_state.l2_quiz = {"words": selected, "scenario": resp.choices[0].message.content.strip(), "lang": db_lang_l2}
                    
            if st.session_state.l2_quiz and st.session_state.l2_quiz["lang"] == db_lang_l2:
                st.markdown("---")
                quiz = st.session_state.l2_quiz
                target_words = [f"{x['word']} ({x.get('meaning','未知')})" for x in quiz['words']]
                st.info(quiz['scenario'])
                st.markdown(f"**目标词汇**：`{'` | `'.join(target_words)}`")
                
                quiz_id = "_".join([str(x["id"]) for x in quiz["words"]])
                user_sentence = st.text_area("✍️ 你的外语作答 (脑内构思后敲出来)：", key=f"l2_ans_{quiz_id}")
                
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
                                    db.table("vocab").update({"level": 1, "streak": 0, "next_review_time": get_time_offset(hours=1)}).eq("id", w["id"]).execute()
                                else:
                                    new_time = get_time_offset(days=3) if score_val >= 4 else get_time_offset(days=1)
                                    db.table("vocab").update({"next_l2_time": new_time, "last_l2_time": get_now_utc()}).eq("id", w["id"]).execute()
                            
                            db.table("history").insert({
                                "date": f"L2造句 ({db_lang_l2})",
                                "zh_sentence": quiz['scenario'],
                                "user_en": user_sentence,
                                "feedback": re.sub(r'---.*\[SCORE:\s*[1-5]\]', '', feedback, flags=re.DOTALL)
                            }).execute()
                            
                            st.session_state.l2_quiz = None
                            st.button("👉 挑战完成，点击继续", use_container_width=True)

# ==================== Tab 3: 高阶语块训练营 (Chunks) ====================
with tab_chunks:
    st.subheader("🧩 结构与语块输出训练 (Pattern Drill)")
    st.caption("这是母语思维的灵魂！包含固定搭配、近义词辨析、高频句式。")
    db = get_supabase_client()
    llm = get_llm_client()
    
    if db and llm:
        now_utc = get_now_utc()
        due_chunks = db.table("chunks").select("*").lte("next_review_time", now_utc).execute().data
        
        st.write(f"📊 **今日待训练语块：** `{len(due_chunks)}` 个")
        st.markdown("---")
        
        if len(due_chunks) == 0:
            st.success("今日语块任务已清空！去 Tab 6 导入更多干货吧。")
            if st.button("🔄 强行唤醒睡眠中的语块", use_container_width=True):
                with st.spinner("唤醒中..."):
                    db.table("chunks").update({"next_review_time": get_now_utc()}).gt("next_review_time", get_now_utc()).execute()
                st.rerun()
        else:
            if st.button("🎲 抽取 1-2 个语块，生成情景挑战", type="primary", use_container_width=True):
                with st.spinner("AI 正在根据语块定制场景..."):
                    k = min(len(due_chunks), random.choice([1, 2]))
                    selected_chunks = random.sample(due_chunks, k)
                    chunk_list_str = [f"[{c['tag']}] {c['phrase']} ({c['meaning']})" for c in selected_chunks]
                    
                    prompt = f"""设计一个【中文场景题】。要求：
                    1. 必须完美契合以下语块或辨析用法：{chunk_list_str}。
                    2. 只要中文题目描述（50字以内），绝对不要出现英文答案！"""
                    resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}])
                    st.session_state.chunk_quiz = {"chunks": selected_chunks, "scenario": resp.choices[0].message.content.strip()}
            
            if st.session_state.chunk_quiz:
                st.markdown("---")
                quiz = st.session_state.chunk_quiz
                target_phrases = [c['phrase'] for c in quiz['chunks']]
                
                st.markdown("#### 🚨 场景线索：")
                st.info(quiz['scenario'])
                
                if st.button("💡 忘记要考什么结构了？点击获取提示 (Hint)"):
                    for c in quiz['chunks']:
                        st.success(f"**{c.get('tag', '语块')}**: `{c['phrase']}`\n\n*(解析/批注: {c['meaning']})*")
                        
                chunk_ans = st.text_area("✍️ 运用上述语块结构进行造句：", key=f"chunk_ans_{quiz['chunks'][0]['id']}")
                
                if st.button("🚀 提交结构批改", use_container_width=True):
                    if not chunk_ans.strip(): st.warning("请输入句子。")
                    else:
                        eval_prompt = f"中文场景：{quiz['scenario']}\n要求使用的骨架语块：{target_phrases}\n用户：{chunk_ans}\n请输出:\n### 1. 结构与搭配诊断\n### 2. 地道重塑版\n### 3. [SCORE: X] (1-5分)"
                        with st.spinner("AI 正在解析句型..."):
                            feedback = ""
                            stream = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": eval_prompt}], stream=True)
                            feedback_container = st.empty()
                            for chunk in stream:
                                if chunk.choices[0].delta.content:
                                    feedback += chunk.choices[0].delta.content
                                    feedback_container.markdown(feedback)
                            
                            score_match = re.search(r'\[SCORE:\s*([1-5])\]', feedback)
                            score_val = int(score_match.group(1)) if score_match else 3
                            
                            for c in quiz['chunks']:
                                streak = c.get("streak", 0)
                                if score_val >= 4:
                                    db.table("chunks").update({"streak": streak+1, "next_review_time": get_time_offset(days=streak+2)}).eq("id", c["id"]).execute()
                                elif score_val == 3:
                                    db.table("chunks").update({"next_review_time": get_time_offset(hours=12)}).eq("id", c["id"]).execute()
                                else:
                                    db.table("chunks").update({"streak": 0, "next_review_time": get_time_offset(hours=1)}).eq("id", c["id"]).execute()
                            
                            db.table("history").insert({
                                "date": "Chunks结构训练",
                                "zh_sentence": quiz['scenario'],
                                "user_en": chunk_ans,
                                "feedback": re.sub(r'---.*\[SCORE:\s*[1-5]\]', '', feedback, flags=re.DOTALL)
                            }).execute()
                            st.session_state.chunk_quiz = None
                            st.button("👉 训练完成，进入下一题", use_container_width=True)

# ==================== Tab 4: 口语召回 (闪卡) ====================
with tab_oral:
    st.subheader("🗣️ 3秒即兴口语闪卡测试")
    db = get_supabase_client()
    if db:
        oral_cards = db.table("oral_cards").select("*").execute().data
        col_gen_card, col_clear_card = st.columns([2, 1])
        with col_gen_card:
            if st.button("🎲 生成随机口语场景", use_container_width=True, type="primary"):
                if not oral_cards: st.warning("口语库为空，请先在 Tab 6 导入素材。")
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

# ==================== Tab 5: 🗂️ 云端全库数据大阅兵 ====================
with tab_cards:
    st.subheader("🗂️ 云端数据总览与查阅")
    st.caption("在这里你可以检查提取结果是否正确，并删除不需要的卡片。")
    db = get_supabase_client()
    if db:
        c_tab1, c_tab2, c_tab3 = st.tabs(["📚 词汇库 (Vocab)", "🧩 语块库 (Chunks)", "🗣️ 口语闪卡 (Oral)"])
        
        with c_tab1:
            all_words = db.table("vocab").select("*").order("id", desc=True).limit(100).execute().data
            if not all_words: st.info("空空如也")
            else:
                st.write(f"(仅展示最近导入的 100 个单词以防卡顿)")
                for w in all_words:
                    with st.expander(f"🏷️ [{w.get('tag', '')}] {w['word']}  (Level {w['level']})"):
                        st.write(f"**💡 含义:** `{w.get('meaning', '暂无记录')}`")
                        st.write(f"**🗣️ 音标:** {w.get('phonetic', '无')}")
                        st.write(f"**📖 例句:** {w.get('example', '无例句')}")
                        if st.button(f"🗑️ 删除该词", key=f"del_v_{w['id']}"):
                            db.table("vocab").delete().eq("id", w["id"]).execute()
                            st.rerun()
                            
        with c_tab2:
            all_chunks = db.table("chunks").select("*").order("id", desc=True).limit(100).execute().data
            if not all_chunks: st.info("空空如也")
            else:
                st.write(f"(仅展示最近导入的 100 个语块)")
                for c in all_chunks:
                    with st.expander(f"🏷️ [{c.get('tag', '')}] {c['phrase']}"):
                        st.write(f"**💡 批注/含义:** {c.get('meaning', '')}")
                        st.write(f"**📖 训练例句:** {c.get('example', '')}")
                        if st.button(f"🗑️ 删除该语块", key=f"del_c_{c['id']}"):
                            db.table("chunks").delete().eq("id", c["id"]).execute()
                            st.rerun()

        with c_tab3:
            all_oral = db.table("oral_cards").select("*").order("id", desc=True).limit(100).execute().data
            if not all_oral: st.info("空空如也")
            else:
                for o in all_oral:
                    with st.expander(f"🗣️ {o['phrase']}"):
                        st.write(f"**场景:** {o.get('scenario', '')}")
                        st.write(f"**原句:** {o.get('full_sentence', '')}")
                        if st.button(f"🗑️ 删除闪卡", key=f"del_o_{o['id']}"):
                            db.table("oral_cards").delete().eq("id", o["id"]).execute()
                            st.rerun()

# ==================== Tab 6: 云端管理与导入 ====================
with tab_manage:
    st.subheader("📂 语料分拣与导入中心")
    
    import_target = st.radio("你要导入至哪个核心库？", [
        "1. 导入 CET4 四级词汇 (直达 L1 认读)", 
        "2. 导入 TOEFL 托福词汇 (进入 L0 速览)",
        "3. 导入高阶语块库 (固定搭配/语法/词语辨析)", 
        "4. 导入口语召回库 (整句闪卡)"
    ], horizontal=False)
    
    import_lang = st.radio("语料语种", ["EN 英语", "JP 日语"], horizontal=True)
    db_lang_import = "EN" if "EN" in import_lang else "JP"
    
    db = get_supabase_client()
    llm = get_llm_client()
    
    if db and llm:
        import_mode = st.radio("选择导入方式", ["上传文档 (PDF/Word/TXT)", "直接粘贴文本"], horizontal=True)
        raw_text = ""
        if import_mode == "直接粘贴文本":
            raw_text = st.text_area("在此粘贴你的词表、课文或随手记的笔记：", height=150)
        else:
            file_obj = st.file_uploader("上传文档", type=["pdf", "docx", "txt"])
            if file_obj:
                ext = file_obj.name.split(".")[-1].lower()
                if ext == "pdf": raw_text = extract_text_from_pdf(file_obj)
                elif ext == "docx": raw_text = extract_text_from_docx(file_obj)
                elif ext == "txt": raw_text = str(file_obj.read(), "utf-8")
                st.success("读取成功！")

        if st.button("🚀 智能提取并分类上传", type="primary"):
            if not raw_text.strip():
                st.warning("文本为空！")
            else:
                with st.spinner("AI 正在火力全开提取数据..."):
                    try:
                        # ------ 模式 1 & 2: 导入生词 ------
                        if "CET4" in import_target or "TOEFL" in import_target:
                            prompt = f"""提取正在被讲解的核心单词。返回JSON: {{"words": [{{"word": "单词", "meaning": "中文意思", "phonetic": "音标", "example": "原文例句"}}]}}。文本：{raw_text[:4000]}"""
                            resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}, temperature=0.1)
                            extracted = json.loads(resp.choices[0].message.content).get("words", [])
                            
                            existing_res = db.table("vocab").select("word").eq("language", db_lang_import).execute().data
                            existing_set = {x['word'].lower() for x in existing_res}
                            
                            insert_data = []
                            duplicate_count = 0
                            now_str = get_now_utc()
                            is_cet4 = "CET4" in import_target
                            target_level = 1 if is_cet4 else 0
                            target_tag = "CET4" if is_cet4 else "TOEFL"
                            
                            for item in extracted:
                                w = item.get("word", "").strip()
                                if not w: continue
                                if w.lower() in existing_set:
                                    duplicate_count += 1
                                else:
                                    insert_data.append({"word": w, "meaning": item.get("meaning",""), "phonetic": item.get("phonetic",""), "example": item.get("example",""), "language": db_lang_import, "level": target_level, "tag": target_tag, "next_review_time": now_str, "next_spell_time": now_str, "next_l2_time": now_str})
                                    existing_set.add(w.lower())
                            
                            if insert_data: 
                                db.table("vocab").insert(insert_data).execute()
                                st.success(f"🎉 成功导入 {len(insert_data)} 个新词！(拦截了 {duplicate_count} 个重复词)")
                            else:
                                st.warning(f"导入拦截：本次提取的单词数据库里全都有了！(拦截了 {duplicate_count} 个)")
                            
                        # ------ 模式 3: 导入高阶语块 (全面优化穷尽提取) ------
                        elif "高阶语块" in import_target:
                            prompt = f"""你是一个严谨的语言学专家。请提取以下文本中的【所有】语言学习条目（包含固定搭配、句式、近义词辨析、单字及其特殊用法）。
任务要求：
1. 必须穷尽提取，不要遗漏！文本中有多少组，就提取多少组。
2. 自动纠正文本中的英文拼写错误。
3. 如果用户记录的是近义词辨析（如 Ignorance vs Oversight），或者附带了特定的批注，请完整保留在 meaning 中，并在 example 中造一个能体现该批注的精妙例句。
返回 JSON: {{"chunks": [{{"phrase": "英文语块/单字/辨析词组", "meaning": "中文含义及用户的特殊批注", "tag": "从 [固定搭配] / [经典句式] / [语法辨析] 选1个", "example": "请你为其造一个地道的英文例句"}}]}}。
文本：{raw_text[:4000]}"""
                            
                            resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}, temperature=0.3)
                            chunks = json.loads(resp.choices[0].message.content).get("chunks", [])
                            
                            existing_chunks_res = db.table("chunks").select("phrase").eq("language", db_lang_import).execute().data
                            existing_set = {x['phrase'].lower() for x in existing_chunks_res}
                            
                            insert_data = []
                            duplicate_count = 0
                            now_str = get_now_utc()
                            
                            for item in chunks:
                                p = item.get("phrase", "").strip()
                                if not p: continue
                                if p.lower() in existing_set:
                                    duplicate_count += 1
                                else:
                                    insert_data.append({
                                        "phrase": p,
                                        "meaning": item.get("meaning", ""),
                                        "tag": item.get("tag", ""),
                                        "example": item.get("example", ""),
                                        "language": db_lang_import,
                                        "next_review_time": now_str,
                                        "streak": 0
                                    })
                                    existing_set.add(p.lower())
                                    
                            if insert_data:
                                db.table("chunks").insert(insert_data).execute()
                                st.success(f"🎉 成功提取并写入 {len(insert_data)} 个语块至 Chunks 训练营！(拦截了 {duplicate_count} 个重复项)")
                            else:
                                st.warning(f"导入拦截：本次提取的语块全部已存在！(拦截了 {duplicate_count} 个)")
                                
                        # ------ 模式 4: 导入口语闪卡 ------
                        else:
                            prompt = f"""提取口语长句。输出JSON: {{"cards": [{{"phrase": "重点词", "scenario": "中文抽象场景", "full_sentence": "英文原句"}}]}}。文本：{raw_text[:4000]}"""
                            resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"}, temperature=0.1)
                            cards = json.loads(resp.choices[0].message.content).get("cards", [])
                            if cards:
                                db.table("oral_cards").insert(cards).execute()
                                st.success(f"🎉 成功导入 {len(cards)} 张口语闪卡！")
                                
                    except Exception as e:
                        st.error(f"处理失败: {e}")

        # ----- 综合数据急救与删除 -----
        st.markdown("---")
        with st.expander("🗂️ 数据库急救与清空 (点击展开)", expanded=False):
            st.markdown("##### 🏥 旧数据 AI 修复台")
            if st.button("⚙️ 自动修复缺失字段的老单词", use_container_width=True):
                # 保留修复逻辑
                pass
            
            st.markdown("##### 🗑️ 危险区 (清空数据库)")
            confirm_del = st.checkbox("⚠️ 我已知晓风险，确认解锁清空按钮 (此操作不可逆)")
            if confirm_del:
                col_d1, col_d2, col_d3 = st.columns(3)
                with col_d1:
                    if st.button("清空所有单词", type="secondary"): db.table("vocab").delete().neq("id", 0).execute(); st.rerun()
                with col_d2:
                    if st.button("清空所有语块", type="secondary"): db.table("chunks").delete().neq("id", 0).execute(); st.rerun()
                with col_d3:
                    if st.button("清空口语闪卡", type="secondary"): db.table("oral_cards").delete().neq("id", 0).execute(); st.rerun()

# ==================== Tab 7: 历史造句库 & 计划 ====================
with tab_history_plan:
    st.subheader("⏳ 独立历史造句大厅")
    db = get_supabase_client()
    if db:
        hist = db.table("history").select("*").order("created_at", desc=True).limit(20).execute().data
        if not hist:
            st.info("尚无实战记录，快去 Tab 2 或 Tab 3 练习吧！")
        else:
            for item in hist:
                with st.expander(f"📌 {item.get('date', '记录')} | {item.get('zh_sentence', '')[:15]}..."):
                    st.markdown(f"**中文原意：** {item.get('zh_sentence', '')}")
                    st.markdown(f"**你的输出：** `{item.get('user_en', '')}`")
                    st.write(item.get('feedback', ''))
    
    st.markdown("---")
    st.subheader("🗓️ 一年期托福&N2 攻坚计划表")
    st.markdown("""
    **☀️ 上午（攻克英语与词汇）**
    - 刷完今日 `Tab 1` 漏斗额度（L0速览0秒加载 + L1双轨听写防漏）。
    - 打开 `Tab 3` 练习高级语法和句型架构。
    
    **☕ 下午（日文切换与输入）**
    - `Tab 2 (日语)` 动词变形实战。
    - 手机阅读或精听 TPO / NHK，将查出的难句丢进 `Tab 6` 提取成语块。

    **🌃 晚间（口语降维打击）**
    - 复制 `Tab 0` 的每日教练 Prompt 给 ChatGPT 语音。打完卡后将纠错录入口语库。睡觉前 `Tab 4` 盲考闪卡。
    """)
