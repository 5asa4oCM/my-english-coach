import streamlit as st
import json
import os
import random
import re
from pypdf import PdfReader
from gtts import gTTS
import io
from openai import OpenAI

# 配置文件路径
VOCAB_FILE = "vocab_db.json"
HISTORY_FILE = "quiz_history.json"
README_FILE = "使用说明.txt"

# ==================== 1. 自动生成使用说明书 ====================
def generate_readme_if_not_exists():
    if not os.path.exists(README_FILE):
        readme_content = """===================================================
                  智能英语训练看板 使用说明书
===================================================

【核心文件说明 - 切勿删除！】
1. vocab_db.json
   - 您的核心资产！保存了您所有的英语笔记、单词、地道短语、原始例句、
     以及系统根据您的掌握情况计算出的“自适应权重（抽题概率）”。
   - 升级软件或更新代码时，请绝对不要删除或覆盖此文件！

2. quiz_history.json
   - 您的学习足迹！保存了您每一次的汉译英作答内容、AI外教的详细纠错润色
     以及学术/口语双轨写法的精讲。
   - 升级软件或更新代码时，请绝对不要删除或覆盖此文件！

3. app.py
   - 本系统的运行引擎（代码文件）。
   - 未来当需要更新、优化功能或修复Bug时，只需用新代码直接替换此文件的内容。

【云端/异地 iPhone 使用重要提示】
当您把本系统部署到 GitHub 并运行在 Streamlit Cloud 网页端时，由于云端服务器是“临时”的，
网页端录入的数据在云服务器定期重启后会重置。
为此，我们在「笔记管理」界面增加了“云端数据备份与恢复”面板：
- 每次学习结束时：点击下载备份您的 vocab_db.json 与 quiz_history.json 到手机中。
- 下次开始学习前：将这两个文件上传回网页，即可瞬间找回全部学习进度与自适应权重！

===================================================
"""
        with open(README_FILE, "w", encoding="utf-8") as f:
            f.write(readme_content)

generate_readme_if_not_exists()

# ==================== 2. 数据库兼容与自动迁移函数 ====================
def migrate_db():
    if not os.path.exists(VOCAB_FILE):
        with open(VOCAB_FILE, "w", encoding="utf-8") as f:
            json.dump({"vocab_list": []}, f, ensure_ascii=False, indent=4)
        return

    try:
        with open(VOCAB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # 兼容旧版本数据结构
        if isinstance(data, dict) and "words" in data:
            old_words = data["words"]
            new_list = [{"word": w, "example": "", "weight": 1.0, "score": 3, "tested_once": True} for w in old_words]
            data = {"vocab_list": new_list}
        
        if isinstance(data, dict) and "vocab_list" in data:
            updated = False
            for item in data["vocab_list"]:
                if "tested_once" not in item:
                    item["tested_once"] = True 
                    updated = True
                if "weight" not in item:
                    item["weight"] = 1.0
                    updated = True
                if "score" not in item:
                    item["score"] = 3
                    updated = True
            if updated:
                with open(VOCAB_FILE, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        st.error(f"数据库向前兼容迁移失败: {e}")

migrate_db()

if not os.path.exists(HISTORY_FILE):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump([], f, ensure_ascii=False, indent=4)

# ==================== 3. 核心数据读写函数 ====================
def load_vocab():
    with open(VOCAB_FILE, "r", encoding="utf-8") as f:
        return json.load(f).get("vocab_list", [])

def save_vocab(vocab_list):
    with open(VOCAB_FILE, "w", encoding="utf-8") as f:
        json.dump({"vocab_list": vocab_list}, f, ensure_ascii=False, indent=4)

def load_history():
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_history(history_item):
    history = load_history()
    history.insert(0, history_item)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=4)

# ==================== 4. 自适应新词优先调度算法 ====================
def get_adaptive_sample(vocab_list, k=2):
    if not vocab_list:
        return []
    k = min(k, len(vocab_list))
    
    # 筛选未测新词
    untested_pool = [item for item in vocab_list if not item.get("tested_once", False)]
    selected = []
    
    if untested_pool:
        num_new_to_pick = min(random.randint(1, k), len(untested_pool))
        new_picks = random.sample(untested_pool, num_new_to_pick)
        selected.extend(new_picks)
        
        remaining_k = k - len(selected)
        if remaining_k > 0:
            remaining_pool = [item for item in vocab_list if item not in selected]
            for _ in range(remaining_k):
                if not remaining_pool:
                    break
                w_temp = [item.get("weight", 1.0) for item in remaining_pool]
                choice = random.choices(remaining_pool, weights=w_temp, k=1)[0]
                selected.append(choice)
                remaining_pool.remove(choice)
    else:
        temp_list = list(vocab_list)
        for _ in range(k):
            if not temp_list:
                break
            w_temp = [item.get("weight", 1.0) for item in temp_list]
            choice = random.choices(temp_list, weights=w_temp, k=1)[0]
            selected.append(choice)
            temp_list.remove(choice)
            
    return selected

def update_vocab_state_and_weight(word_text, score):
    vocab_list = load_vocab()
    updated = False
    for item in vocab_list:
        if item["word"].lower() == word_text.lower():
            item["tested_once"] = True
            current_weight = item.get("weight", 1.0)
            item["score"] = score
            if score <= 2:
                item["weight"] = min(current_weight * 2.0, 10.0)
            elif score >= 4:
                item["weight"] = max(current_weight * 0.5, 0.1)
            updated = True
            break
    if updated:
        save_vocab(vocab_list)

def generate_audio(text, lang='en'):
    try:
        clean_text = re.sub(r'[*_`#]', '', text)
        tts = gTTS(text=clean_text[:200], lang=lang, tld='com')
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception as e:
        return None

# ==================== 5. Streamlit UI ====================
st.set_page_config(page_title="自适应英语看板", page_icon="📝", layout="centered")

st.sidebar.title("⚙️ 系统设置")
api_key = st.sidebar.text_input("API Key", type="password", value=st.session_state.get("api_key", ""))
base_url = st.sidebar.text_input("API Base URL", value="https://api.openai.com/v1")
model_name = st.sidebar.selectbox("选择模型", ["gpt-4o-mini", "gpt-4o", "deepseek-chat"], index=0)

if api_key:
    st.session_state["api_key"] = api_key
    st.session_state["base_url"] = base_url
    st.session_state["model_name"] = model_name

def get_llm_client():
    if not st.session_state.get("api_key"):
        st.warning("请先在左侧边栏配置您的 API Key。")
        return None
    return OpenAI(api_key=st.session_state["api_key"], base_url=st.session_state["base_url"])

if "current_quiz" not in st.session_state:
    st.session_state.current_quiz = None
if "evaluation_text" not in st.session_state:
    st.session_state.evaluation_text = None

tab_quiz, tab_manage, tab_history = st.tabs(["🎯 翻译训练", "📚 笔记管理", "⏳ 历史复习"])

# ==================== Tab 1: 翻译训练 ====================
with tab_quiz:
    st.subheader("今日自适应强化挑战")
    vocab_list = load_vocab()
    
    untested_count = len([item for item in vocab_list if not item.get("tested_once", False)])
    if untested_count > 0:
        st.info(f"💡 发现新词！当前有 **{untested_count}** 个新词正处于首轮必修测试阶段。")
        
    if not vocab_list:
        st.info("您的词汇库目前为空，请前往『笔记管理』标签页上传 PDF。")
    else:
        client = get_llm_client()
        
        if st.button("🔄 生成新翻译题目", use_container_width=True):
            if client:
                with st.spinner("AI 正在精心设计翻译题目..."):
                    selected_items = get_adaptive_sample(vocab_list, k=2)
                    context_info = []
                    for item in selected_items:
                        info_str = f"单词/词组: '{item['word']}'"
                        if item.get("example"):
                            info_str += f" (例句: {item['example']})"
                        context_info.append(info_str)
                    
                    terms_prompt = "; ".join(context_info)
                    
                    prompt = f"""
                    你是一位英语母语外教。请基于以下用户笔记词汇及例句语境：
                    {terms_prompt}
                    
                    任务：
                    创造一个地道、不含生硬“中式英文”痕迹的中文句子。
                    要求：
                    该中文句子的英文地道翻译中，必须自然流畅地应用上述提供的单词和短语。
                    
                    请仅输出一句中文，不要带有任何前缀后缀。
                    """
                    try:
                        response = client.chat.completions.create(
                            model=st.session_state["model_name"],
                            messages=[{"role": "user", "content": prompt}],
                            temperature=0.8
                        )
                        zh_sentence = response.choices[0].message.content.strip()
                        st.session_state.current_quiz = {
                            "zh_sentence": zh_sentence,
                            "selected_items": selected_items
                        }
                        st.session_state.evaluation_text = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"生成题目出错: {e}")
        
        if st.session_state.current_quiz:
            st.markdown("##### 🎯 请翻译以下中文句子：")
            st.info(st.session_state.current_quiz["zh_sentence"])
            
            tips = []
            for item in st.session_state.current_quiz["selected_items"]:
                is_new = "🆕 新词" if not item.get("tested_once", False) else f"复习 (权重: {item.get('weight', 1.0):.1f})"
                tips.append(f"`{item['word']}` ({is_new})")
            st.markdown(f"💡 本题考核重点：{' | '.join(tips)}")
            
            user_translation = st.text_area("✍️ 您的英文翻译：", placeholder="在此输入您的译文，或直接点击右侧查看答案...", key="user_input_area")
            
            col_submit, col_skip = st.columns([1, 1])
            submit_clicked = False
            skip_clicked = False
            
            with col_submit:
                if st.button("🚀 提交翻译并评估", type="primary", use_container_width=True):
                    if not user_translation.strip():
                        st.warning("请输入答案后再提交。")
                    else:
                        submit_clicked = True
            with col_skip:
                if st.button("👀 直接显示答案", use_container_width=True):
                    skip_clicked = True
            
            if (submit_clicked or skip_clicked) and client:
                is_skip = skip_clicked
                input_translation = "（用户直接查看了答案）" if is_skip else user_translation
                
                eval_prompt = f"""
                原中文句子：{st.session_state.current_quiz['zh_sentence']}
                用户尝试翻译：{input_translation}
                目标考察词汇：{[item['word'] for item in st.session_state.current_quiz['selected_items']]}

                请扮演完美的英语母语专家，严格按以下格式（使用 Markdown）输出解析：

                ### 1. 译文评估与纠错 {'(用户已跳过作答)' if is_skip else ''}
                { '用户直接查看了答案。请指引用户阅读下方的地道版本并进行跟读。' if is_skip else '详细指出用户翻译在语法、语序及用词自然度上的问题，并进行细节重塑。' }

                ### 2. 母语者地道写法
                *   **书面/学术写法 (Written Style)**: [地道的写作、演讲或书面语写法]
                *   **口语/日常表达 (Spoken Style)**: [母语者日常高频使用的、非常地道的口语表达]

                ### 3. 语言点精讲
                [讲解以上句子中考查词汇的应用方法，以及核心搭配。]

                ---
                ### 4. 掌握程度自动评分（此项必须输出）
                请在最后一行对用户的翻译进行严苛而精细的打分（若用户跳过作答，评分一律为 1 ）。
                [SCORE: X]  （其中 X 是 1 到 5 之间的整数）
                """
                
                st.markdown("---")
                st.markdown("##### 📝 专家实时分析反馈")
                feedback_container = st.empty()
                full_response = ""
                
                try:
                    stream = client.chat.completions.create(
                        model=st.session_state["model_name"],
                        messages=[{"role": "user", "content": eval_prompt}],
                        temperature=0.3,
                        stream=True
                    )
                    
                    for chunk in stream:
                        if chunk.choices[0].delta.content is not None:
                            full_response += chunk.choices[0].delta.content
                            feedback_container.markdown(full_response)
                            
                    st.session_state.evaluation_text = full_response
                    
                    score_match = re.search(r'\[SCORE:\s*([1-5])\]', full_response)
                    score_val = int(score_match.group(1)) if score_match else (1 if is_skip else 3)
                    
                    for item in st.session_state.current_quiz["selected_items"]:
                        update_vocab_state_and_weight(item["word"], score_val)
                    
                    clean_feedback = re.sub(r'---.*\[SCORE:\s*[1-5]\]', '', full_response, flags=re.DOTALL)
                    history_item = {
                        "date": "今日训练",
                        "zh": st.session_state.current_quiz['zh_sentence'],
                        "user_en": input_translation,
                        "feedback": clean_feedback
                    }
                    save_history(history_item)
                    
                except Exception as e:
                    st.error(f"智能评判运行失败: {e}")
            
            if st.session_state.evaluation_text:
                st.markdown("##### 🎧 听力与发音跟读")
                tts_text = st.text_input("在此复制上方润色好的地道英文进行语音朗读：")
                if tts_text.strip():
                    audio_stream = generate_audio(tts_text)
                    if audio_stream:
                        st.audio(audio_stream, format="audio/mp3")

# ==================== Tab 2: 笔记管理 ====================
with tab_manage:
    st.subheader("📂 笔记库管理与导入")
    
    # 1. PDF 导入
    st.write("##### 1. 导入 PDF 笔记 (新词默认锁入首轮测试)")
    uploaded_file = st.file_uploader("选择 PDF 文件，导入的数据默认进入必修测试阶段", type=["pdf"])
    
    if uploaded_file is not None:
        if st.button("智能提取并标记新词", use_container_width=True):
            with st.spinner("正在智能解析例句与短语..."):
                try:
                    reader = PdfReader(uploaded_file)
                    raw_text = ""
                    for page in reader.pages[:10]:
                        raw_text += page.extract_text() or ""
                    
                    client = get_llm_client()
                    cleaned_items = []
                    
                    if client and raw_text.strip():
                        extract_prompt = f"""
                        从以下文本中提炼重要英文词汇或短语，并为其匹配原文中的例句。
                        请输出 JSON 格式（严禁包含任何其他文字说明）：
                        {{
                          "vocab_list": [
                            {{"word": "短语或单词", "example": "包含该短语的原文完整例句"}}
                          ]
                        }}
                        
                        文本：
                        {raw_text[:2500]}
                        """
                        response = client.chat.completions.create(
                            model=st.session_state["model_name"],
                            messages=[{"role": "user", "content": extract_prompt}],
                            response_format={ "type": "json_object" },
                            temperature=0.3
                        )
                        res_json = json.loads(response.choices[0].message.content)
                        extracted_list = res_json.get("vocab_list", [])
                        
                        for item in extracted_list:
                            cleaned_items.append({
                                "word": item.get("word", "").strip(),
                                "example": item.get("example", "").strip(),
                                "weight": 1.0,
                                "score": 3,
                                "tested_once": False
                            })
                    else:
                        st.warning("已降级启用本地提取。")
                        local_words = re.findall(r'\b[a-zA-Z][a-zA-Z\s\-\']{2,24}\b', raw_text)
                        stop_words = {"the", "and", "that", "this", "with", "from", "they"}
                        cleaned_words = list({w.strip().lower() for w in local_words if w.strip().lower() not in stop_words})
                        for w in cleaned_words:
                            cleaned_items.append({"word": w, "example": "", "weight": 1.0, "score": 3, "tested_once": False})
                    
                    if cleaned_items:
                        current_vocab = load_vocab()
                        existing_dict = {item["word"].lower(): item for item in current_vocab}
                        for new_item in cleaned_items:
                            w_lower = new_item["word"].lower()
                            if w_lower not in existing_dict:
                                existing_dict[w_lower] = new_item
                            else:
                                if not existing_dict[w_lower].get("example") and new_item.get("example"):
                                    existing_dict[w_lower]["example"] = new_item["example"]
                        save_vocab(list(existing_dict.values()))
                        st.success(f"🎉 成功载入 {len(cleaned_items)} 个新词汇，已锁入新词必修队列！")
                        st.rerun()
                except Exception as e:
                    st.error(f"导入失败: {e}")

    st.markdown("---")
    # 2. 手动添加
    st.write("##### 2. 手动键入新词汇")
    new_w = st.text_input("手动添加单词或地道短语")
    new_ex = st.text_area("配套例句 context")
    if st.button("确认手动录入"):
        if new_w.strip():
            vocab_list = load_vocab()
            existing_words = [item["word"].lower() for item in vocab_list]
            if new_w.strip().lower() not in existing_words:
                vocab_list.append({
                    "word": new_w.strip(),
                    "example": new_ex.strip(),
                    "weight": 1.0,
                    "score": 3,
                    "tested_once": False
                })
                save_vocab(vocab_list)
                st.success(f"成功录入新词: {new_w}")
                st.rerun()
            else:
                st.warning("该词已在库中。")

    st.markdown("---")
    # 3. 云端备份功能（解决 Streamlit Cloud 服务器重启丢失数据的问题）
    st.write("##### 3. 💾 云端数据备份与恢复 (异地 iPhone 使用必看)")
    st.caption("因为 Streamlit 免费云端服务器定期会自动重启重置，为防进度丢失，请在每次训练结束后下载备份，下次使用前上传恢复。")
    
    col_dl_vocab, col_dl_hist = st.columns(2)
    with col_dl_vocab:
        with open(VOCAB_FILE, "r", encoding="utf-8") as f:
            v_data = f.read()
        st.download_button("📥 备份词汇库 (vocab_db.json)", data=v_data, file_name="vocab_db.json", mime="application/json", use_container_width=True)
    with col_dl_hist:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            h_data = f.read()
        st.download_button("📥 备份历史足迹 (quiz_history.json)", data=h_data, file_name="quiz_history.json", mime="application/json", use_container_width=True)
        
    uploaded_vocab = st.file_uploader("📤 上传并恢复词汇库 (vocab_db.json)", type=["json"])
    if uploaded_vocab is not None:
        if st.button("确认覆盖并恢复词汇库", use_container_width=True):
            try:
                restored = json.load(uploaded_vocab)
                if "vocab_list" in restored:
                    save_vocab(restored["vocab_list"])
                    st.success("词汇库恢复成功！")
                    st.rerun()
            except Exception as e:
                st.error(f"恢复词汇库失败: {e}")

    uploaded_hist = st.file_uploader("📤 上传并恢复历史足迹 (quiz_history.json)", type=["json"])
    if uploaded_hist is not None:
        if st.button("确认覆盖并恢复历史足迹", use_container_width=True):
            try:
                restored_h = json.load(uploaded_hist)
                if isinstance(restored_h, list):
                    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                        json.dump(restored_h, f, ensure_ascii=False, indent=4)
                    st.success("历史足迹恢复成功！")
                    st.rerun()
            except Exception as e:
                st.error(f"恢复历史足迹失败: {e}")

    st.markdown("---")
    # 4. 词汇库展示
    vocab_list = load_vocab()
    st.write(f"##### 4. 本地词库状态全景 (共计 {len(vocab_list)} 个)")
    if vocab_list:
        with st.expander("🔍 展开查看各单词状态和历史权重"):
            for item in sorted(vocab_list, key=lambda x: (x.get('tested_once', False), -x.get('weight', 1.0))):
                state_lbl = "✅ 已通过首测" if item.get("tested_once", False) else "🆕 必修新词"
                st.write(f"- **{item['word']}** | `{state_lbl}` | 权重分: `{item.get('weight', 1.0):.2f}` | 例句: _{item.get('example', '无')}_")
        
        if st.button("🗑️ 彻底清空本地词库", type="secondary"):
            save_vocab([])
            st.rerun()

# ==================== Tab 3: 历史复习 ====================
with tab_history:
    st.subheader("⏳ 历史翻译足迹")
    history_data = load_history()
    
    if not history_data:
        st.info("尚无训练历史。")
    else:
        for idx, item in enumerate(history_data[:15]):
            with st.expander(f"📌 {item.get('date', '记录')} | 中文: {item['zh'][:15]}..."):
                st.markdown(f"**中文原句：** {item['zh']}")
                st.markdown(f"**您的翻译：** `{item['user_en']}`")
                st.markdown("**AI 精细分析：**")
                st.write(item['feedback'])