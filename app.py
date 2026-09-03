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
st.set_page_config(page_title="多语种自适应看板 (终极版)", page_icon="🌎", layout="wide")

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

tab_learn, tab_l2, tab_oral, tab_manage, tab_plan = st.tabs(["📚 词汇漏斗", "🎯 实战输出(L2)", "🗣️ 口语闪卡", "📂 云端管理", "🗓️ 计划与历史"])

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
            st.markdown("#### 🆕 Level 0: 新词速览")
            if l0_words:
                if not st.session_state.current_l0 or st.session_state.current_l0['language'] != db_lang:
                    st.session_state.current_l0 = random.choice(l0_words)
                w = st.session_state.current_l0
                st.info(f"### {w['word']}")
                
                if st.button("🧠 获取 AI 解析 (Hint)", key="hint_l0"):
                    llm = get_llm_client()
                    if llm:
                        hint_prompt = f"告诉我单词 '{w['word']}' 的中文意思和词性。如果是日语请附带假名读音和音调说明；如果是英语请给一个常考短语。"
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
                
                if not st.session_state.show_l1_meaning:
                    if st.button("👀 点击核对答案", use_container_width=True):
                        st.session_state.show_l1_meaning = True
                        st.rerun()
                else:
                    llm = get_llm_client()
                    if llm:
                        resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": f"给出 '{w1['word']}' 的极简中文意思。如果日语请带假名。"}], temperature=0.1)
                        st.success(f"**含义：** {resp.choices[0].message.content.strip()}")
                    
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
            st.warning(f"当前 L2 库中词汇太少。英语需至少 3 个，日语需至少 2 个。请先去 Tab 1 背词！")
        else:
            if st.button("🎲 抽取词汇，生成 AI 挑战", type="primary", use_container_width=True):
                with st.spinner("AI 正在构思挑战..."):
                    k = 3 if db_lang_l2 == "EN" else random.choice([1, 2])
                    weights = [float(x.get("weight", 1.0)) for x in l2_words]
                    selected = random.choices(l2_words, weights=weights, k=k)
                    word_list = [x['word'] for x in selected]
                    
                    if db_lang_l2 == "EN":
                        prompt = f"基于这三个英语单词：{word_list}。用中文为我设定一个日常或学术场景。要求：合理串联这三个词，只要中文描述，字数50以内。"
                    else:
                        prompt = f"""
                        基于这些日语词汇：{word_list}。
                        如果里面有动词/形容词，请出一个【变形与造句综合挑战】（例如：请把xx变成使役态，并造一个句子）。
                        如果全是名词，请出一个【中译日情景挑战】（例如：你在居酒屋，请用这些词点单）。
                        只输出中文挑战要求，千万不要给出日文答案！
                        """
                    
                    resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}])
                    st.session_state.l2_quiz = {"words": selected, "scenario": resp.choices[0].message.content.strip(), "lang": db_lang_l2}
                    
            if st.session_state.l2_quiz and st.session_state.l2_quiz["lang"] == db_lang_l2:
                st.markdown("---")
                quiz = st.session_state.l2_quiz
                target_words = [x['word'] for x in quiz['words']]
                st.markdown("#### 🚨 挑战要求：")
                st.info(quiz['scenario'])
                st.markdown(f"**目标词汇**：`{'` | `'.join(target_words)}`")
                
                if st.button("💡 绞尽脑汁想不起来？获取提示"):
                    tips = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": f"简述词义/变形规则：{target_words}"}])
                    st.success(tips.choices[0].message.content)
                
                user_sentence = st.text_area("✍️ 你的外语作答 (脑内构思后敲出来)：", placeholder="在此输入...")
                
                if st.button("🚀 提交给 AI 批改", use_container_width=True):
                    if not user_sentence.strip():
                        st.warning("请输入句子再提交。")
                    else:
                        if db_lang_l2 == "EN":
                            eval_prompt = f"场景：{quiz['scenario']}\n要求用词：{target_words}\n用户句子：{user_sentence}\n请按Markdown格式输出：\n### 1. 原句诊断(含语法/中式英语纠错)\n### 2. 双版本重塑\n* 日常口语版\n* 托福学术版\n### 3. [SCORE: X] (1-5分)"
                        else:
                            eval_prompt = f"挑战：{quiz['scenario']}\n要求用词：{target_words}\n用户句子：{user_sentence}\n请按Markdown格式输出：\n### 1. 语法与变形诊断(重点分析助词、动词变形是否正确)\n### 2. 双版本重塑\n* 极简口语版(朋友间)\n* 标准丁宁体(N2书面/敬语)\n### 3. [SCORE: X] (1-5分)"
                        
                        with st.spinner("AI 导师正在阅卷..."):
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
                            
                            db.table("history").insert({
                                "date": f"L2挑战({db_lang_l2})",
                                "zh_sentence": quiz['scenario'],
                                "user_en": user_sentence,
                                "feedback": re.sub(r'---.*\[SCORE:\s*[1-5]\]', '', feedback, flags=re.DOTALL)
                            }).execute()

# ==================== Tab 3: 口语召回 (3秒情景闪卡) ====================
with tab_oral:
    st.subheader("🗣️ 3秒即兴口语闪卡测试")
    st.caption("来源于你日常看剧、听播客、和AI对话积累的金句。")
    db = get_supabase_client()
    
    if db:
        oral_cards = db.table("oral_cards").select("*").execute().data
        
        col_gen_card, col_clear_card = st.columns([2, 1])
        with col_gen_card:
            if st.button("🎲 生成随机口语场景", use_container_width=True, type="primary"):
                if not oral_cards:
                    st.warning("口语库为空，请先在 Tab 4 导入素材。")
                else:
                    st.session_state.active_oral_card = random.choice(oral_cards)
                    st.session_state.show_oral_answer = False
                    st.rerun()
                    
        if st.session_state.active_oral_card:
            st.markdown("---")
            c = st.session_state.active_oral_card
            st.markdown("#### 🚨 场景线索（限时3秒，微声脱口而出）：")
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

# ==================== Tab 4: 云端库管理 (多语种导入) ====================
with tab_manage:
    st.subheader("📂 多模态语料导入中心")
    import_target = st.radio("导入至哪个库？", ["导入生词库 (L0/L1)", "导入口语召回库 (生成情境闪卡)"], horizontal=True)
    import_lang = st.radio("语料语种", ["EN 英语", "JP 日语"], horizontal=True)
    db_lang_import = "EN" if "EN" in import_lang else "JP"
    
    db = get_supabase_client()
    llm = get_llm_client()
    
    if db and llm:
        import_mode = st.radio("选择导入方式", ["直接粘贴文本", "上传文档 (PDF/Word/TXT)"], horizontal=True)
        raw_text = ""
        
        if import_mode == "直接粘贴文本":
            raw_text = st.text_area("在此粘贴你的词汇表、美剧台词或 AI 纠错对话记录：", height=150)
        else:
            file_obj = st.file_uploader("点击或拖拽上传文档 (支持 .pdf, .docx, .txt)", type=["pdf", "docx", "txt"])
            if file_obj:
                with st.spinner("正在提取文档内容..."):
                    try:
                        ext = file_obj.name.split(".")[-1].lower()
                        if ext == "pdf": 
                            raw_text = extract_text_from_pdf(file_obj)
                        elif ext == "docx": 
                            raw_text = extract_text_from_docx(file_obj)
                        elif ext == "txt": 
                            raw_text = str(file_obj.read(), "utf-8")
                        
                        if raw_text.strip():
                            st.success(f"📂 成功读取文档！共提取到 {len(raw_text)} 个字符。已准备好进行AI智能提炼。")
                        else:
                            st.error("未能提取到有效字符，请检查文件。")
                    except Exception as e:
                        st.error(f"提取文件失败: {e}")

        if st.button("🚀 智能提取并上传至云端", type="primary"):
            if not raw_text.strip():
                st.warning("内容为空！请粘贴文本或成功上传文档后再点击。")
            else:
                with st.spinner("AI 正在结构化数据并写入 Supabase 远端服务器..."):
                    try:
                        if import_target == "导入生词库 (L0/L1)":
                            prompt = f"提取以下文本中的核心{db_lang_import}单词，只需输出单词本身，用逗号分隔。文本：{raw_text[:20000]}"
                            resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}], temperature=0.3)
                            word_list = resp.choices[0].message.content.strip().split(",")
                            cleaned = [w.strip() for w in word_list if len(w.strip()) > 0]
                            insert_data = [{"word": w, "language": db_lang_import, "level": 0} for w in cleaned]
                            if insert_data:
                                db.table("vocab").insert(insert_data).execute()
                                st.success(f"🎉 成功写入 {len(cleaned)} 个新词至 Level 0 库！")
                                
                        else:
                            prompt = f"""提取3-5个高频实用短语。输出JSON: {{"cards": [{{"phrase": "词组", "scenario": "中文描述极其具体的生活场景线索", "full_sentence": "包含该词的{db_lang_import}例句"}}]}}。文本：{raw_text[:2000]}"""
                            resp = llm.chat.completions.create(model=st.session_state["model_name"], messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
                            cards = json.loads(resp.choices[0].message.content).get("cards", [])
                            if cards:
                                db.table("oral_cards").insert(cards).execute()
                                st.success(f"🎉 成功提取并写入 {len(cards)} 张口语情境闪卡！")
                    except Exception as e:
                        st.error(f"处理失败: {e}")

# ==================== Tab 5: 计划与历史 ====================
with tab_plan:
    st.subheader("🗓️ 一年期托福&N2 攻坚计划表 (课堂碎片化防疲劳调度)")
    st.info("""
    **☀️ 上午专业课 (精力充沛：攻克英语)**
    - *前20分钟*：打开看板 `Tab 1`，刷完今日托福 Level 0 和 Level 1 额度（无声心算打卡）。
    - *后20分钟*：手机刷一篇 TPO 阅读，分析长难句。将长难句短语丢进 `Tab 4` 导入。
    
    **☕ 下午专业课 (容易犯困：切换日语)**
    - *前20分钟*：打开看板 `Tab 2 (日语)`，玩动词变形 AI 挑战（极度清醒大脑）。
    - *后20分钟*：阅读 NHK Easy News 或玩多邻国，保持语感。
    
    **🚶‍♂️ 通勤/回宿舍 (碎片听觉)**
    - 戴单边耳机，使用【每日英语听力/日语听力】App 进行挖空回音跟读（单日英语，双日日语）。
    
    **🌃 晚间宿舍 (强迫输出)**
    - 打开 ChatGPT 语音模式，与 AI 进行 5 分钟外语对练。
    - 将 AI 纠错的地道表达粘贴进看板 `Tab 4 (口语召回库)`。睡觉前在 `Tab 3` 进行 3 秒闪卡测试。
    """)
    
    st.markdown("---")
    st.subheader("⏳ 云端学习足迹")
    db = get_supabase_client()
    if db:
        hist = db.table("history").select("*").order("created_at", desc=True).limit(10).execute().data
        for item in hist:
            with st.expander(f"📌 {item.get('date', '')} | {item.get('zh_sentence', '')[:15]}..."):
                st.markdown(f"**你的输出：** `{item.get('user_en', '')}`")
                st.write(item.get('feedback', ''))
