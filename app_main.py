import streamlit as st
from st_screen_stats import ScreenData
import logging
import os
import uuid
import requests
import json
import time
import pandas as pd
from streamlit import Page
from datetime import datetime

# Configuration class for app settings
class Config:
    """Application configuration settings"""
    def __init__(self):
        self.page_title = "Study Planner"
        self.page_icon = "📚"
        self.layout = "wide"
        self.sidebar_state = "collapsed"
        self.version = "0.1.0"
        self.author = "11조 권준희, 이채민, 김세민"
        
        # Backend URL configuration
        try:
            self.backend_url = st.secrets.get("FASTAPI_SERVER_URL") or os.environ.get("FASTAPI_SERVER_URL")
            if not self.backend_url:
                self.backend_url = "http://127.0.0.1:8000"
        except Exception:
            self.backend_url = "http://127.0.0.1:8000"

# Logging setup
def setup_logging():
    """Configure logging for the application"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

# Session Management
class SessionManager:
    """Manages application session state"""
    
    @staticmethod
    def initialize_session(logger):
        """Initialize session state variables if they don't exist"""
        if "messages" not in st.session_state:
            st.session_state.messages = []
        
        if "session_id" not in st.session_state:
            st.session_state.session_id = f"session_{uuid.uuid4()}"
        
        if "viewport_height" not in st.session_state:
            st.session_state.viewport_height = 800
        
        if "is_streaming" not in st.session_state:
            st.session_state.is_streaming = False
        
        if "task_list" not in st.session_state:
            st.session_state.task_list = []  # 세션 내 전체 task 배열
            
        if "feedback_list" not in st.session_state:
            st.session_state.feedback_list = []  # 세션 내 전체 feedback 배열
            
        if "current_agent" not in st.session_state:
            st.session_state["current_agent"] = "supervisor"
            
        if "needs_rerun_after_stream" not in st.session_state:
            st.session_state.needs_rerun_after_stream = False
            
        if "pending_message" not in st.session_state:
            st.session_state.pending_message = None  

    @staticmethod
    def reset_session(logger):
        """Reset the session state, preserving only viewport_height"""
        current_session_id = st.session_state.get("session_id")
        current_viewport_height = st.session_state.get("viewport_height")
        logger.info(f"세션 리셋 요청 (ID: {current_session_id}).")

        keys_to_clear = list(st.session_state.keys())
        for key in keys_to_clear:
            if key not in ["viewport_height"]:
                del st.session_state[key]
        
        st.session_state.session_id = f"session_{uuid.uuid4()}"
        logger.info(f"새 세션 ID 생성됨: {st.session_state.session_id}")
        
        st.session_state.messages = []
        st.session_state.is_streaming = False
        st.session_state.task_list = []
        st.session_state.feedback_list = []
        
        st.toast("세션이 초기화되었습니다.", icon="🔄")
        st.rerun()

    @staticmethod
    def add_message(role, content):
        """Add a message to the session state"""
        if "messages" not in st.session_state:
            st.session_state.messages = []
        
        st.session_state.messages.append({"role": role, "content": content})
        
# UI Components
class UI:
    """UI component management"""
    
    @staticmethod
    def setup_page_config(config):
        """Configure the Streamlit page settings"""
        st.set_page_config(
            page_title=config.page_title,
            page_icon=config.page_icon,
            layout=config.layout,
            initial_sidebar_state=config.sidebar_state,
            menu_items=None
        )
    
    @staticmethod
    def add_custom_css():
        """Add custom CSS styles to the page"""
        st.markdown("""
        <style>
        .task-completed {
            background-color: #e8f5e8;
            opacity: 0.7;
        }
        .task-pending {
            background-color: #fff5f5;
        }
        </style>
        """, unsafe_allow_html=True)

    @staticmethod
    def create_sidebar(config, logger):
        """Create sidebar with basic info and controls"""
        
        @st.dialog("설정")
        def settings_dialog():
            
            st.subheader("교수자 타입 설정")
            
            # 현재 설정된 교수자 타입 불러오기 (세션별)
            current_professor_type = "T형"  # 기본값
            try:
                prof_response = requests.get(f"{config.backend_url}/sessions/{st.session_state.session_id}/professor-type", timeout=5)
                if prof_response.status_code == 200:
                    prof_data = prof_response.json()
                    if prof_data.get("success"):
                        current_professor_type = prof_data.get("professor_type", "T형")
            except Exception:
                pass  # 오류 시 기본값 사용
            
            # 현재 설정값을 기본값으로 사용
            current_index = 0 if current_professor_type == "T형" else 1
            professor_type = st.selectbox("교수자 타입", ["T형", "F형"], index=current_index)

            if st.button("저장", use_container_width=True, type='secondary', key='professor_type_save'):
                if professor_type:
                    try:
                        response = requests.post(
                            f"{config.backend_url}/sessions/{st.session_state.session_id}/professor-type",
                            json={"professor_type": professor_type},
                            timeout=10
                        )
                        response.raise_for_status()
                        
                        result = response.json()
                        if result.get("success"):
                            st.success(f"✅ {result.get('message')}")
                        else:
                            st.error("설정 실패")
                    except requests.exceptions.RequestException as e:
                        st.error(f"❌ 교수자 타입 설정 중 오류가 발생했습니다: {e}")
                    except Exception as e:
                        st.error(f"❌ 예상치 못한 오류가 발생했습니다: {e}")
                else:
                    st.error("교수자 타입을 설정해주세요.")
            
            
            st.divider()
            st.subheader("교과서 업로드")
            pdf_file = st.file_uploader("교과서 업로드", type=["pdf"])  # 파일 선택
            
            # 현재 교과서 상태 확인
            has_existing_textbook = False
            existing_filename = "알 수 없는 교과서"
            try:
                textbook_response = requests.get(f"{config.backend_url}/data/textbook", 
                                                params={"session_id": st.session_state.session_id}, 
                                                timeout=5)
                if textbook_response.status_code == 200:
                    textbook_data = textbook_response.json()
                    if textbook_data.get("success") and textbook_data.get("textbook"):
                        has_existing_textbook = True
                        existing_filename = textbook_data["textbook"].get('filename', '알 수 없는 교과서')
            except Exception:
                pass  # 오류 시 무시
            
            # 버튼 텍스트 동적 변경
            button_text = "기존 교과서 덮어쓰기" if has_existing_textbook else "DB 변환"
            button_type = "primary" if has_existing_textbook else "secondary"
            
            convert_disabled = (pdf_file is None)

            if st.button(button_text, use_container_width=True, type=button_type, key='pdf_file_save', disabled=convert_disabled):
                if convert_disabled:
                    st.warning("📄 PDF 파일을 업로드하세요.")
                    st.stop()

                try:
                    with st.spinner("교과서 처리 중입니다... (몇 분 소요될 수 있습니다)"):
                        endpoint = f"{config.backend_url}/data/upload"

                        files = {"file": (pdf_file.name, pdf_file.read(), "application/pdf")}
                        data = {"session_id": st.session_state.session_id, "title": pdf_file.name.strip()}

                        response = requests.post(
                            endpoint,
                            files=files,
                            data=data,
                            timeout=1200
                        )
                        response.raise_for_status()

                        result = response.json()
                        if result.get("success"):
                            st.success(f"✅ {result.get('message')}")
                        else:
                            st.error(f"처리 실패: {result.get('message', '알 수 없는 오류')}")

                except requests.exceptions.RequestException as e:
                    st.error(f"❌ 교과서 업로드 중 오류가 발생했습니다: {e}")
                except Exception as e:
                    st.error(f"❌ 예상치 못한 오류가 발생했습니다: {e}")
            
            # 현재 업로드된 문제집 정보 표시
            st.subheader("현재 교과서 DB")
            
            try:
                textbook_response = requests.get(f"{config.backend_url}/data/textbook", 
                                                params={"session_id": st.session_state.session_id}, 
                                                timeout=10)
                if textbook_response.status_code == 200:
                    textbook_data = textbook_response.json()
                    if textbook_data.get("success") and textbook_data.get("textbook"):
                        textbook = textbook_data["textbook"]
                        st.info(f"📖 **{textbook.get('filename', '알 수 없는 교과서')}**")
                        st.write(f"📄 총 페이지: {textbook.get('page_count', 0)}페이지")
                    else:
                        st.info("아직 업로드된 교과서가 없습니다.")
                else:
                    st.warning("교과서 정보를 불러올 수 없습니다.")
            except Exception as e:
                st.warning(f"교과서 정보 조회 오류: {e}")
        
        
        
        # Main info
        
        with st.sidebar:
            st.title("Study Planner")
            st.write(f"version {config.version}")
            
            st.info(
                f"""
                **25-1 AI기반프로그램개발 11조**
                - 2018182019 권준희
                - 2023182043 김세민
                - 2024190103 이채민
                """
            )
            
            if not st.session_state.get("is_streaming", False):
                try:
                    with st.container(border=False, height=1):
                        screen_data = ScreenData()
                        stats = screen_data.st_screen_data()

                    if stats and "innerHeight" in stats:
                        height = stats.get("innerHeight")
                        if height is not None and isinstance(height, (int, float)) and height > 0:
                            if st.session_state.get("viewport_height") != height:
                                st.session_state.viewport_height = height
                except Exception as e:
                    if "viewport_height" not in st.session_state:
                        st.session_state.viewport_height = 800

            st.divider()
            
            if st.button("설정", use_container_width=True, type="primary"):
                settings_dialog()

            # Session reset button
            if st.button("🔄️ 세션 초기화", use_container_width=True, type="secondary"):
                SessionManager.reset_session(logger)
                st.success("세션이 초기화됩니다.")
                time.sleep(1)
                st.rerun()
    
    @staticmethod
    def create_layout(viewport_height):
        """Create the main layout with task list and chat columns"""
        # Create main columns - 왼쪽 더 크게 (5:3 비율)
        task_column, chat_column = st.columns([5, 3], vertical_alignment="top", gap="medium")
        
        # Chat container (오른쪽)
        with chat_column:
            chat_container = st.container(border=True, height=max(viewport_height - 60, 400))
            response_status = st.status("에이전트 응답 완료", state="complete")
            
        # Task list containers (왼쪽)
        with task_column:
            # Task list가 있으면 표시, 없으면 환영 메시지
            if not st.session_state.task_list:
                with st.container(border=True, height=viewport_height): 
                    st.info("아직 학습 계획이 없습니다.")
                    st.markdown("**오른쪽 채팅창에서 다음과 같이 요청해보세요:**")
                    st.markdown("- '수능특강 1단원부터 3단원까지 1주일 계획 짜줘'")
                    st.markdown("- '오늘부터 5일동안 매일 20페이지씩 공부 계획 만들어줘'")
                    st.markdown("- '현재 진도 상황 알려줘'")
                task_placeholders = []
            else:
                # 실제 task list 표시용 컨테이너
                with st.container(border=True, height=viewport_height): 
                    task_placeholders = [st.empty() for _ in range(20)]  # 최대 20일치
        
        return chat_container, task_placeholders, response_status
    
    @staticmethod
    def calculate_viewport_height(screen_height):
        """Calculate viewport height based on screen height"""
        if screen_height is not None:
            return max(int(screen_height) - 250, 400)
        else:
            return 400

# Task Management UI
class TaskUI:
    """Handles task list rendering and interaction (state 기반)"""

    @staticmethod
    def format_date_display(date_str):
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            return f"{date_obj.strftime('%y-%m-%d')} 학습 계획"
        except Exception:
            return f"{date_str} 학습 계획"

    @staticmethod
    def _group_tasks_by_date(task_list):
        from collections import defaultdict
        groups = defaultdict(list)
        for t in task_list:
            groups[t.get("date", "")].append(t)
        return groups

    @staticmethod
    def render_task_lists(task_placeholders, backend_client):
        if not st.session_state.task_list:
            return

        grouped = TaskUI._group_tasks_by_date(st.session_state.task_list)

        sorted_dates = sorted(grouped.keys())
        all_tasks_completed = True
        all_feedbacks_completed = True
        
        # 각 날짜별로 렌더링하면서 완료 상태 확인
        completed_count = 0
        
        for idx, date_str in enumerate(sorted_dates):
            if idx < len(task_placeholders):
                with task_placeholders[idx]:
                    TaskUI.render_single_day_tasks(date_str, grouped[date_str], backend_client)
                
                # 해당 날짜의 모든 task가 완료되었는지 확인
                # for task in grouped[date_str]:
                #     if not task.get("is_completed", False):
                #         all_tasks_completed = False
                
                # 해당 날짜의 피드백이 있는지 확인
                has_feedback = False
                for feedback in st.session_state.feedback_list:
                    if feedback.get("date") == date_str:
                        has_feedback = True
                        completed_count += 1
                        break
                if not has_feedback:
                    all_feedbacks_completed = False

        # 모든 학습과 피드백이 완료되었으면 주간 마무리 버튼 표시
        all_learning_completed = all_tasks_completed and all_feedbacks_completed and len(sorted_dates) > 0
        
        with task_placeholders[len(sorted_dates)]:
            if st.button(f"📚 학습 과정 마무리 : {completed_count}/{len(sorted_dates)}일 완료", key="weekly_summary_btn", type="primary", use_container_width=True, disabled=not all_learning_completed):
                # 주간 학습 마무리 메시지 전송
                start_date = sorted_dates[0]
                end_date = sorted_dates[-1]
                summary_message = f"{start_date}부터 {end_date}까지의 학습을 모두 마쳤습니다. 이번 주 학습 내용을 종합하여 정리하고, 성찰록을 종합해주세요."
                
                st.session_state.pending_message = summary_message
                st.rerun()
        
        if all_learning_completed:
            st.toast("모든 학습을 완료했습니다! 학습 과정 마무리를 진행해주세요.", icon="🎉")
                    
                    
        # else:
        #     with task_placeholders[len(sorted_dates)]:
        #         st.info(f"학습 마무리까지 남은 일수: {len(sorted_dates) - completed_count}일")

    @staticmethod
    def render_single_day_tasks(date_str, tasks_list, backend_client):
        df_data = []
        for task in tasks_list:
            page_range = f"{task.get('start_pg', '')}-{task.get('end_pg', '')}"
            
            # 썸네일 URL 생성 (첫 페이지)
            start_pg = task.get('start_pg', 1)
            thumbnail_url = f"{backend_client.backend_url}/data/textbook/{st.session_state.session_id}/thumbnail/{start_pg}"
            
            df_data.append({
                "No": task.get("task_no", ""),
                "페이지범위": page_range,
                "미리보기": thumbnail_url,
                #"제목": task.get("title", ""),
                "요약": task.get("summary", ""),
                "완료여부": task.get("is_completed", False),
                "date": task.get("date", ""),  # hidden
                "task_no": task.get("task_no", 0),  # hidden
            })

        df = pd.DataFrame(df_data)
        if df.empty:
            return

        completed_count = df["완료여부"].sum()
        total_count = len(df)
        display_title = TaskUI.format_date_display(date_str)

        progress_pct = int((completed_count / total_count) * 100) if total_count else 0

        with st.expander(f"📅 {display_title} ({completed_count}/{total_count} 완료)", expanded=True):
            st.progress(progress_pct, text=f"{progress_pct}% 완료")

            column_config = {
                "No": st.column_config.NumberColumn("No", width="small"),
                "페이지범위": st.column_config.TextColumn("페이지", width="small"),
                "미리보기": st.column_config.ImageColumn(
                    "미리보기", 
                    width="small",
                    help="교재 페이지 미리보기"
                ),
                #"제목": st.column_config.TextColumn("제목", width="medium"),
                "요약": st.column_config.TextColumn("요약", width="large"),
                "완료여부": st.column_config.CheckboxColumn("완료", width="small"),
                "date": None,
                "task_no": None,
            }

            edited_df = st.data_editor(
                df,
                column_config=column_config,
                use_container_width=True,
                row_height=150,
                hide_index=True,
                key=f"task_editor_{date_str}_{hash(str(df_data))}",
                disabled=["No", "페이지범위", "미리보기", "요약", "date", "task_no"],
            )

            if not edited_df.equals(df):
                changed_rows = df.index[df["완료여부"] != edited_df["완료여부"]].tolist()
                
                # 모든 변경사항을 먼저 처리
                has_changes = False
                for row_idx in changed_rows:
                    date_val = df.iloc[row_idx]["date"]
                    task_no_val = int(df.iloc[row_idx]["task_no"])
                    new_status = bool(edited_df.iloc[row_idx]["완료여부"])

                    # 백엔드 업데이트가 성공한 경우에만 로컬 state 업데이트
                    if TaskUI.update_task_status(date_val, task_no_val, new_status, backend_client):
                        # 로컬 state 업데이트
                        for t in st.session_state.task_list:
                            if t.get("date") == date_val and t.get("task_no") == task_no_val:
                                t["is_completed"] = new_status
                                has_changes = True
                                break
                
                # 변경사항이 있으면 UI 업데이트를 위해 rerun
                if has_changes:
                    st.rerun()
            
            # 해당 날짜의 피드백 찾기
            existing_feedback = None
            for feedback in st.session_state.feedback_list:
                if feedback.get("date") == date_str:
                    existing_feedback = feedback.get("feedback", "")
                    break
            
            # 학습 완료 버튼 (피드백이 없을 때만 표시)
            if not existing_feedback:
                if st.button(f"📝 {date_str} 학습 완료", key=f"complete_btn_{date_str}", type="secondary", use_container_width=True):
                    # 완료된 task 수 계산
                    completed_tasks = sum(1 for task in tasks_list if task.get("is_completed", False))
                    total_tasks = len(tasks_list)
                    
                    # 백엔드로 학습 완료 메시지 전송
                    completion_message = f"{date_str}의 학습을 마쳤습니다. {completed_tasks}/{total_tasks} 할 일을 완료했습니다."
                    
                    # 채팅 입력으로 메시지 전송 시뮬레이션
                    st.session_state.pending_message = completion_message
                    st.rerun()
            
            # 성찰 피드백 표시
            if existing_feedback:
                st.success(f"📝 {date_str} 학습 완료")
                st.write("📖 **나의 한 줄 성찰록**")
                st.write(existing_feedback)

    @staticmethod
    def update_task_status(date, task_no, completed, backend_client):
        try:
            response = requests.post(
                f"{backend_client.backend_url}/tasks/update",
                json={
                    "date": date,
                    "task_no": task_no,
                    "completed": completed,
                    "session_id": st.session_state.session_id,
                },
                timeout=10,
            )
            if response.status_code != 200:
                st.error(f"업데이트 실패: {response.text}")
                return False
            return True
            
        except Exception as e:
            st.error(f"업데이트 중 오류: {e}")
            return False


        
# Message Handling (기존 placeholder 기반 렌더링 복원)
class MessageRenderer:
    """Handles message rendering and task list updates"""
    
    def __init__(self, chat_container, task_placeholders, logger):
        self.chat_container = chat_container
        self.task_placeholders = task_placeholders
        self.logger = logger
    
    def _get_friendly_tool_name(self, tool_name):
        """Translate internal tool names to user-friendly names."""
        if tool_name == "get_textbook_content":
            return "교재 내용 조회"
        elif tool_name == "update_task_list":
            return "할 일 목록 업데이트"
        elif tool_name == "update_feedback_list":
            return "성찰록 업데이트"
        return tool_name
    
    def render_message(self, message, viewport_height):
        """Render a message and handle task list updates"""
        role = message.get("role", "unknown")
        content = message.get("content", "")
        
        if role == "user":
            with self.chat_container:
                with st.chat_message("user"):
                    st.markdown(content, unsafe_allow_html=True)
            return
        
        if role == "assistant":
            with self.chat_container:
                with st.container(border=False):
                    # Create placeholders for streaming content
                    placeholders = [st.empty() for _ in range(100)]
                    current_idx = 0
                
                # Process content
                self._process_assistant_content(content, placeholders, current_idx, viewport_height)
    
    def _process_assistant_content(self, content, placeholders, current_idx, viewport_height):
        """Process assistant message content with placeholder-based rendering"""
        if isinstance(content, str):
            try:
                msg_data = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                if current_idx < len(placeholders):
                    with placeholders[current_idx].container(border=False):
                        st.markdown(content)
                else:
                    st.markdown(content)
                return
        else:
            msg_data = content
        
        if isinstance(msg_data, dict) and "messages" in msg_data:
            for item in msg_data["messages"]:
                item_type = item.get("type", "")
                item_content = item.get("content", "")
                
                if item_type == "text":
                        if current_idx < len(placeholders):
                            with placeholders[current_idx].container(border=False):
                                st.markdown(item_content)
                        else:
                            st.markdown(item_content)
                        current_idx += 1
                    
                elif item_type == "task_update":
                    self._handle_task_update(item_content)
                    
                elif item_type == "feedback_update":
                    self._handle_feedback_update(item_content)
                    
                elif item_type == "tool":
                    if current_idx < len(placeholders):
                        self._render_tool_item(item, placeholders, current_idx)
                        current_idx += 1
                    else:
                        st.warning(f"도구 표시 오류: {self._get_friendly_tool_name(item.get('name', ''))}")
        else:
            if current_idx < len(placeholders):
                with placeholders[current_idx].container(border=False):
                    st.markdown(str(content))
            else:
                st.markdown(str(content))
    
    def _render_tool_item(self, item, placeholders, idx):
        """Render tool execution results with placeholders"""
        tool_name = item.get("name", "도구 실행 결과")
        tool_content = item.get("content", "")
        
        # Get friendly name for display
        friendly_tool_name = self._get_friendly_tool_name(tool_name)
        
        # Check if index is within bounds
        if idx >= len(placeholders):
            st.warning(f"도구 표시 오류: {friendly_tool_name}")
            return
            
        # 그 외 모든 도구: 축소된 완료 상태로 표시
        placeholders[idx].status(f"{friendly_tool_name} 완료", state="complete", expanded=False)
    
    def _handle_task_update(self, task_data):
        """Handle task list updates from backend"""
        try:
            if isinstance(task_data, str):
                task_data = json.loads(task_data)

            # task_data 는 전체 task 배열 (List[dict])
            # 메시지 렌더링 중에는 바로 rerun하지 않고 상태만 업데이트
            if st.session_state.get("task_list") != task_data:
                st.session_state.task_list = task_data
                # 스트리밍 중이 아닐 때만 즉시 rerun
                if not st.session_state.get("is_streaming", False):
                    st.rerun()

        except Exception as e:
            self.logger.error(f"Task update error: {e}")
    
    def _handle_feedback_update(self, feedback_data):
        """Handle feedback list updates from backend"""
        try:
            if isinstance(feedback_data, str):
                feedback_data = json.loads(feedback_data)

            # feedback_data는 전체 feedback 배열 (List[dict])
            # 메시지 렌더링 중에는 바로 rerun하지 않고 상태만 업데이트
            if st.session_state.get("feedback_list") != feedback_data:
                st.session_state.feedback_list = feedback_data
                # 스트리밍 중이 아닐 때만 즉시 rerun
                if not st.session_state.get("is_streaming", False):
                    st.rerun()

        except Exception as e:
            self.logger.error(f"Feedback update error: {e}")

# Backend Communication (기존과 유사)
class BackendClient:
    """Handles communication with the backend API"""
    
    def __init__(self, backend_url, chat_container, task_placeholders, response_status):
        self.backend_url = backend_url
        self.chat_container = chat_container
        self.task_placeholders = task_placeholders
        self.response_status = response_status
        self.logger = logging.getLogger(__name__)

    def send_message(self, prompt, session_id, viewport_height):
        """Send a message to the backend and process streaming response"""
        with self.chat_container:
            # Create placeholders for streaming content
            placeholders = [st.empty() for _ in range(100)]
            
            # Initialize message data storage
            message_data = {"messages": []}
            
            try:
                endpoint = f"{self.backend_url}/chat/stream"
                response = requests.post(
                    endpoint,
                    json={"prompt": prompt, "session_id": session_id},
                    stream=True,
                    timeout=1200
                )
                response.raise_for_status()
                
                st.session_state.is_streaming = True
                return self._process_stream(response, placeholders, message_data, viewport_height)
                
            except requests.exceptions.RequestException as e:
                return self._handle_request_error(e, placeholders, 0)
            except Exception as e:
                return self._handle_generic_error(e, placeholders, 0)
    
    def _process_stream(self, response, placeholders, message_data, viewport_height):
        """Process streaming response from backend with placeholder rendering"""
        current_idx = 0
        text_buffer = ""
        text_placeholder = None
        logger = logging.getLogger(__name__)
        try:
            self.response_status.update(label="AI 응답 중...", state="running")

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                try:
                    payload = json.loads(line)
                    msg_type = payload.get("type", "message")
                    text = payload.get("text", "")

                    # ---------------- End of stream ----------------
                    if msg_type == "end":
                        # flush remaining buffer
                        if text_buffer:
                            if text_placeholder is None:
                                text_placeholder = placeholders[current_idx].empty()
                            text_placeholder.markdown(text_buffer)
                            message_data["messages"].append({"type": "text", "content": text_buffer})
                            logger.info(f"session_id: {st.session_state.session_id}, assistant response: \n{text_buffer}")
                            current_idx += 1
                            text_buffer = ""
                            text_placeholder = None
                            
                        self.response_status.update(label="응답 완료", state="complete")
                        message_data["messages"].append({"type": "agent_change", "agent": "system", "info": "end"})
                        break

                    # ---------------- Error ----------------
                    elif msg_type == "error":
                        # flush buffer first
                        if text_buffer:
                            if text_placeholder is None:
                                text_placeholder = placeholders[current_idx].empty()
                            text_placeholder.markdown(text_buffer)
                            message_data["messages"].append({"type": "text", "content": text_buffer})
                            logger.info(f"session_id: {st.session_state.session_id}, assistant response: \n{text_buffer}")
                            current_idx += 1
                            text_buffer = ""
                            text_placeholder = None

                        self.response_status.update(label="오류 발생", state="error")
                        if current_idx < len(placeholders):
                            with placeholders[current_idx].container(border=False):
                                st.error(text)
                        else:
                            st.error(text)
                        current_idx += 1

                    # ---------------- Normal text token ----------------
                    elif msg_type == "message":
                        # accumulate tokens
                        text_buffer += text
                        if text_placeholder is None:
                            text_placeholder = placeholders[current_idx].empty()
                        text_placeholder.markdown(text_buffer)

                    # ---------------- Task update ----------------
                    elif msg_type == "task_update":
                        # flush buffer before handling
                        if text_buffer:
                            if text_placeholder is None:
                                text_placeholder = placeholders[current_idx].empty()
                            text_placeholder.markdown(text_buffer)
                            message_data["messages"].append({"type": "text", "content": text_buffer})
                            logger.info(f"session_id: {st.session_state.session_id}, assistant response: \n{text_buffer}")
                            current_idx += 1
                            text_buffer = ""
                            text_placeholder = None

                        self._handle_task_update_from_stream(text)
                    
                    # ---------------- Feedback update ----------------
                    elif msg_type == "feedback_update":
                        # flush buffer before handling
                        if text_buffer:
                            if text_placeholder is None:
                                text_placeholder = placeholders[current_idx].empty()
                            text_placeholder.markdown(text_buffer)
                            message_data["messages"].append({"type": "text", "content": text_buffer})
                            logger.info(f"session_id: {st.session_state.session_id}, assistant response: \n{text_buffer}")
                            current_idx += 1
                            text_buffer = ""
                            text_placeholder = None

                        self._handle_feedback_update_from_stream(text)

                    # ---------------- Tool message ----------------
                    elif msg_type == "tool":
                        # flush buffer
                        if text_buffer:
                            if text_placeholder is None:
                                text_placeholder = placeholders[current_idx].empty()
                            text_placeholder.markdown(text_buffer)
                            message_data["messages"].append({"type": "text", "content": text_buffer})
                            logger.info(f"session_id: {st.session_state.session_id}, assistant response: \n{text_buffer}")
                            current_idx += 1
                            text_buffer = ""
                            text_placeholder = None

                        tool_name = payload.get("tool_name", "도구")
                        friendly_tool_name = self._get_friendly_tool_name(tool_name)

                        if current_idx < len(placeholders):
                            with placeholders[current_idx]:
                                st.status(f"{friendly_tool_name}", state="complete", expanded=False)
                        else:
                            st.warning(f"도구 표시 오류: {friendly_tool_name}")

                        message_data["messages"].append({
                            "type": "tool",
                            "name": tool_name,
                            "content": text,
                        })
                        current_idx += 1

                except json.JSONDecodeError as e:
                    self.logger.error(f"JSON decode error: {e}")
                    continue

        finally:
            st.session_state.is_streaming = False

        return message_data
    
    def _get_friendly_tool_name(self, tool_name):
        """Translate internal tool names to user-friendly names."""
        if tool_name == "get_textbook_content":
            return "교재 내용 조회"
        elif tool_name == "update_task_list":
            return "Task 목록 업데이트"
        elif tool_name == "update_feedback_list":
            return "성찰록 업데이트"
        return tool_name
    
    def _handle_task_update_from_stream(self, task_data):
        """Handle task updates from streaming response"""
        try:
            if isinstance(task_data, str):
                task_data = json.loads(task_data)
            
            # 스트리밍 중에는 rerun을 호출하지 않고 상태만 업데이트
            # rerun은 스트리밍이 완료된 후에 수행
            if st.session_state.get("task_list") != task_data:
                st.session_state.task_list = task_data
                # 스트리밍 완료 후 rerun이 필요함을 표시
                st.session_state.needs_rerun_after_stream = True
            
        except Exception as e:
            self.logger.error(f"Task update from stream error: {e}")
    
    def _handle_feedback_update_from_stream(self, feedback_data):
        """Handle feedback updates from streaming response"""
        try:
            if isinstance(feedback_data, str):
                feedback_data = json.loads(feedback_data)
            
            # 스트리밍 중에는 rerun을 호출하지 않고 상태만 업데이트
            # rerun은 스트리밍이 완료된 후에 수행
            if st.session_state.get("feedback_list") != feedback_data:
                st.session_state.feedback_list = feedback_data
                # 스트리밍 완료 후 rerun이 필요함을 표시
                st.session_state.needs_rerun_after_stream = True
            
        except Exception as e:
            self.logger.error(f"Feedback update from stream error: {e}")
    
    def _handle_request_error(self, error, placeholders, idx):
        """Handle request errors"""
        error_msg = f"백엔드 연결 오류: {error}"
        self.logger.error(error_msg)
        
        if idx < len(placeholders):
            with placeholders[idx].container():
                st.error(error_msg)
        else:
            st.error(error_msg)
        return error_msg
    
    def _handle_generic_error(self, error, placeholders, idx):
        """Handle generic errors"""
        error_msg = f"응답 처리 중 오류 발생: {error}"
        self.logger.error(error_msg)
        
        if idx < len(placeholders):
            with placeholders[idx].container():
                st.error(error_msg)
        else:
            st.error(error_msg)
        return error_msg

# Main Application Page Logic
def show_main_app(config, logger):
    """Displays the main study planner interface"""
       
    def on_submit():
        """채팅 입력 제출 시 호출되는 콜백 함수"""
        st.session_state.is_streaming = True
    
    # Initialize session
    SessionManager.initialize_session(logger)

    # Get viewport height
    latest_detected_height = st.session_state.get("viewport_height", 800)
    viewport_height = UI.calculate_viewport_height(latest_detected_height)

    # Create layout
    chat_container, task_placeholders, response_status = UI.create_layout(viewport_height)
    
    # Create helper classes
    message_renderer = MessageRenderer(chat_container, task_placeholders, logger)
    backend_client = BackendClient(config.backend_url, chat_container, task_placeholders, response_status)

    # Render existing task lists
    TaskUI.render_task_lists(task_placeholders, backend_client)
    
    # Render existing messages
    for message in st.session_state.messages:
        message_renderer.render_message(message, viewport_height)

    # Chat input
    prompt = st.chat_input(
        "예: '수능특강 1단원부터 5단원까지 1주일 계획 짜줘'",
        disabled=st.session_state.is_streaming,
        on_submit=on_submit
    )
    
    # pending_message 처리 (학습 완료 버튼에서 온 메시지)
    if st.session_state.get("pending_message"):
        prompt = st.session_state.pending_message
        st.session_state.pending_message = None  # 메시지 처리 후 삭제
        
    # Process prompt
    if prompt:
        st.session_state.is_streaming = True
        logger.info(f"session_id: {st.session_state.session_id}, user prompt: \n{prompt}")
        # Add user message
        SessionManager.add_message("user", prompt)
        message_renderer.render_message({"role": "user", "content": prompt}, viewport_height)

        # Send to backend
        try:
            response = backend_client.send_message(prompt, st.session_state.session_id, viewport_height)
            SessionManager.add_message("assistant", response)
            st.session_state.is_streaming = False
            
            # 스트리밍 중 task update가 있었다면 이제 rerun
            if st.session_state.get("needs_rerun_after_stream", False):
                st.session_state.needs_rerun_after_stream = False
                st.rerun()
        except Exception as e:
            logger.error(f"백엔드 호출 중 오류 발생: {e}")
            st.error(f"오류가 발생했습니다: {e}")

        st.rerun()

# Application Entry Point
def main():
    """Main application entry point"""
    config = Config()
    logger = setup_logging()

    UI.setup_page_config(config)
    UI.add_custom_css()
    UI.create_sidebar(config, logger)

    pages = [
        Page(lambda: show_main_app(config, logger), title="Study Planner", icon="📚", default=True),
    ]

    pg = st.navigation(pages)
    pg.run()

if __name__ == "__main__":
    main()